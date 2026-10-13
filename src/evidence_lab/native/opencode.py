"""OpenCode SQLite generator (OpenCode v1.x schema).

Creates `opencode/opencode.db` with the v1-line project/session/message/part
tables (message and part payloads live in a JSON `data` column; ids and
foreign keys are columns). This is the schema Telltale's `opencode.sqlite`
adapter reads. OpenCode v2.0.0+ bootstraps fresh databases with
`session_v2`/`session_message` instead, which Telltale currently acquires as
zero records; see docs/harnesses/compatibility-findings.md. See docs/harnesses/opencode.md for the pinned
upstream schema this follows and what is intentionally omitted.

SQLite files are not byte-reproducible across SQLite builds, so determinism
is defined over `logical_dump()`, not the file hash.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..scenario import Scenario
from ..util import epoch_ms, offset, parse_utc, stable_id

SOURCE_ID = "opencode.sqlite"
GENERATOR_VERSION = "opencode-sqlite-v1-schema/1"
DENIED_ERROR = (
    "The user rejected permission to use this specific tool call. "
    "You may try again with different parameters."
)

SCHEMA = """
CREATE TABLE project (
  id text PRIMARY KEY, worktree text NOT NULL, vcs text, name text,
  time_created integer NOT NULL, time_updated integer NOT NULL
);
CREATE TABLE session (
  id text PRIMARY KEY, project_id text NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  parent_id text, slug text NOT NULL, directory text NOT NULL, title text NOT NULL,
  version text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL
);
CREATE TABLE message (
  id text PRIMARY KEY, session_id text NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
);
CREATE TABLE part (
  id text PRIMARY KEY, message_id text NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL,
  data text NOT NULL
);
CREATE INDEX message_session_idx ON message (session_id);
CREATE INDEX part_message_idx ON part (message_id);
CREATE INDEX part_session_idx ON part (session_id);
"""

TABLES = ("project", "session", "message", "part")


def _dump(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def _tool_part(item: dict, call_id: str, start_ms: int, end_ms: int) -> dict:
    tool = item["tool"]
    if tool == "shell":
        name, inputs = "bash", {"command": item["command"], "description": "Run shell command"}
    elif tool == "read_file":
        name, inputs = "read", {"filePath": item["path"]}
    else:
        name, inputs = "write", {"filePath": item["path"], "content": item.get("content", "")}

    result = item["result"]
    if result is None:
        state = {"status": "pending", "input": inputs, "raw": ""}
    elif result["status"] == "ok":
        output = result.get("output", "")
        metadata: dict = {"output": output, "description": inputs.get("description", name)}
        if tool == "shell":
            metadata["exit"] = result.get("exit_code", 0)
        state = {
            "status": "completed", "input": inputs, "output": output,
            "title": item.get("command", item.get("path", name)), "metadata": metadata,
            "time": {"start": start_ms, "end": end_ms},
        }
    else:
        error = result.get("output") or (DENIED_ERROR if result["status"] == "denied" else "error")
        state = {"status": "error", "input": inputs, "error": error, "time": {"start": start_ms, "end": end_ms}}
    return {"type": "tool", "callID": call_id, "tool": name, "state": state}


def write(scenario: Scenario, root: Path) -> list[Path]:
    session_cfg = scenario.session
    start = parse_utc(session_cfg["start"])
    step = float(session_cfg.get("step_seconds", 2))
    cwd = session_cfg["cwd"]
    model = session_cfg.get("model", "synthetic-model")
    provider = session_cfg.get("provider", "synthetic-provider")

    def ident(prefix: str, *parts: str, ordinal: int = 0) -> str:
        # Ordinal prefix keeps ids ascending, like OpenCode's time-ordered ids.
        return f"{prefix}_{ordinal:06d}{stable_id(scenario.id, prefix, *parts, length=20)}"

    target = root / "opencode" / "opencode.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    project_id = ident("prj", "project")
    session_id = ident("ses", "session")
    t0 = epoch_ms(start)
    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.executescript(SCHEMA)
        clock = 0.0
        messages: list[tuple] = []
        parts: list[tuple] = []
        last_user: str | None = None
        assistant: dict | None = None
        ordinal = 0

        def close_assistant() -> None:
            nonlocal assistant
            if assistant is not None:
                data = assistant["data"]
                data["time"]["completed"] = assistant["updated"]
                messages.append((assistant["id"], session_id, data["time"]["created"], assistant["updated"], _dump(data)))
                assistant = None

        for index, item in enumerate(scenario.steps):
            clock += step
            now = epoch_ms(offset(start, clock))
            ordinal += 1
            if item["type"] == "user":
                close_assistant()
                message_id = ident("msg", "user", str(index), ordinal=ordinal)
                data = {"role": "user", "time": {"created": now}, "agent": "build",
                        "model": {"providerID": provider, "modelID": model}}
                messages.append((message_id, session_id, now, now, _dump(data)))
                part = {"type": "text", "text": item["text"], "time": {"start": now, "end": now}}
                parts.append((ident("prt", str(index), ordinal=ordinal), message_id, session_id, now, now, _dump(part)))
                last_user = message_id
                continue
            if assistant is None:
                assistant = {
                    "id": ident("msg", "assistant", str(index), ordinal=ordinal),
                    "updated": now,
                    "data": {
                        "role": "assistant", "time": {"created": now}, "parentID": last_user,
                        "modelID": model, "providerID": provider, "mode": "build", "agent": "build",
                        "path": {"cwd": cwd, "root": cwd}, "cost": 0,
                        "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                    },
                }
            if item["type"] == "assistant":
                part = {"type": "text", "text": item["text"], "time": {"start": now, "end": now}}
                updated = now
            else:
                end = epoch_ms(offset(start, clock + step / 2))
                call_id = "call_" + stable_id(scenario.id, "opencode-call", str(index), length=24)
                part = _tool_part(item, call_id, now, end)
                updated = end if item["result"] is not None else now
                clock += step / 2
            parts.append((ident("prt", str(index), ordinal=ordinal), assistant["id"], session_id, now, updated, _dump(part)))
            assistant["updated"] = max(assistant["updated"], updated)
        close_assistant()

        last = max(row[3] for row in messages)
        conn.execute("INSERT INTO project VALUES (?,?,?,?,?,?)", (project_id, cwd, "git", None, t0, last))
        conn.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, project_id, None, stable_id(scenario.id, "slug", length=8), cwd,
             scenario.data["title"], "synthetic", t0, last),
        )
        conn.executemany("INSERT INTO message VALUES (?,?,?,?,?)", sorted(messages))
        conn.executemany("INSERT INTO part VALUES (?,?,?,?,?,?)", sorted(parts))
        conn.commit()
    finally:
        conn.close()
    return [target]


def logical_dump(db_path: Path) -> list:
    """Order-stable logical content used for reproducibility comparisons."""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        dump: list = []
        for table in TABLES:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()  # noqa: S608 - fixed names
            dump.append([table, [list(row) for row in rows]])
        return dump
    finally:
        conn.close()
