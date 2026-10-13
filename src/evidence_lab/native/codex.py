"""Codex rollout JSONL generator.

Emits the public rollout envelope shape (`session_meta`, `turn_context`,
`response_item`) that Codex persists under `$CODEX_HOME/sessions`. See
docs/harnesses/codex.md for the field sources and known differences between
this generator and live Codex output (for example, `event_msg` mirrors are
not emitted; see that guide before adding them).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..scenario import Scenario
from ..util import iso_ms, offset, parse_utc, stable_id, stable_uuid

SOURCE_ID = "codex.sessions"
GENERATOR_VERSION = "codex-rollout/1"
DENIED_OUTPUT = "exec command rejected by user"


def _line(record: dict) -> str:
    # Compact separators match Codex's serde_json output.
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def _shell_arguments(command: str, cwd: str) -> str:
    return json.dumps({"command": ["bash", "-lc", command], "workdir": cwd}, separators=(",", ":"))


def _function_output(result: dict) -> str:
    if result["status"] == "denied":
        return result.get("output") or DENIED_OUTPUT
    exit_code = result.get("exit_code", 0 if result["status"] == "ok" else 1)
    payload = {"output": result.get("output", ""), "metadata": {"exit_code": exit_code, "duration_seconds": 0.1}}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _patch_for(path: str, content: str) -> str:
    body = "".join(f"+{line}\n" for line in content.splitlines()) if content else ""
    return f"*** Begin Patch\n*** Add File: {path}\n{body}*** End Patch\n"


def render(scenario: Scenario) -> tuple[str, str]:
    """Return (relative path under the fixture root, JSONL text)."""
    session = scenario.session
    start = parse_utc(session["start"])
    step = float(session.get("step_seconds", 2))
    cwd = session["cwd"]
    thread_id = stable_uuid("codex-thread", scenario.id)
    lines: list[str] = []
    clock = 0.0

    def ts() -> str:
        return iso_ms(offset(start, clock))

    lines.append(_line({
        "timestamp": ts(),
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": ts(),
            "cwd": cwd,
            "originator": "codex_cli_rs",
            "cli_version": "synthetic",
            "source": "cli",
            "model_provider": session.get("provider", "synthetic-provider"),
        },
    }))
    lines.append(_line({
        "timestamp": ts(),
        "type": "turn_context",
        "payload": {
            "cwd": cwd,
            "approval_policy": "on-request",
            "sandbox_policy": {"mode": "workspace-write"},
            "model": session.get("model", "synthetic-model"),
            "summary": "auto",
        },
    }))

    for index, item in enumerate(scenario.steps):
        clock += step
        kind = item["type"]
        if kind == "user":
            lines.append(_line({"timestamp": ts(), "type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": item["text"]}]}}))
        elif kind == "assistant":
            lines.append(_line({"timestamp": ts(), "type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": item["text"]}]}}))
        else:
            call_id = "call_" + stable_id(scenario.id, "codex-call", str(index), length=24)
            tool = item["tool"]
            if tool == "write_file":
                lines.append(_line({"timestamp": ts(), "type": "response_item", "payload": {
                    "type": "custom_tool_call", "status": "completed", "call_id": call_id,
                    "name": "apply_patch", "input": _patch_for(item["path"], item.get("content", ""))}}))
            else:
                command = item["command"] if tool == "shell" else f"cat {item['path']}"
                lines.append(_line({"timestamp": ts(), "type": "response_item", "payload": {
                    "type": "function_call", "name": "shell",
                    "arguments": _shell_arguments(command, cwd), "call_id": call_id}}))
            result = item["result"]
            if result is None:
                continue  # proposal only: Codex recorded no output for this call
            clock += step / 2
            output_type = "custom_tool_call_output" if tool == "write_file" else "function_call_output"
            lines.append(_line({"timestamp": ts(), "type": "response_item", "payload": {
                "type": output_type, "call_id": call_id, "output": _function_output(result)}}))

    day = start.strftime("%Y/%m/%d")
    stamp = start.strftime("%Y-%m-%dT%H-%M-%S")
    relative = f"codex/sessions/{day}/rollout-{stamp}-{thread_id}.jsonl"
    return relative, "\n".join(lines) + "\n"


def write(scenario: Scenario, root: Path) -> list[Path]:
    relative, text = render(scenario)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return [target]
