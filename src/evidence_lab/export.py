"""Package a reviewed case for public use (a detection-repo fixture or an AI
analysis package). Only synthetic data is eligible by default; snapshot data
is never eligible. Leakage checks fail closed and report categories, not
content.
"""

from __future__ import annotations

import getpass
import json
import re
import shutil
from pathlib import Path

from . import scenario as scenario_mod
from .util import LabError, read_json, write_json

FORMAT = "telltale-lab/case/v1"
NEVER_EXPORTABLE = {"snapshot"}
MAX_FILE_BYTES = 1024 * 1024
TOKEN_PATTERNS = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9\-]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
HOME_PATTERNS = re.compile(r"(/home/[^/\s\"']+|/Users/[^/\s\"']+|[A-Za-z]:\\\\?Users\\\\?[^\\\s\"']+)")
ALLOWED_HOME_SEGMENTS = {"/home/dev", "/home/user", "/home/lab", "/Users/dev"}


def _text_of(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"SQLite format 3\x00"):
        import sqlite3

        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            chunks = []
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 - names from sqlite_master
                    chunks.append(json.dumps(row, default=str, ensure_ascii=False))
            return "\n".join(chunks)
        finally:
            conn.close()
    return data.decode("utf-8", errors="replace")


def leakage_problems(items: list[tuple[str, Path]]) -> list[str]:
    """Check (label, path) pairs; problems name the label and category only."""
    problems: list[str] = []
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - best effort
        user = ""
    home = str(Path.home())
    for rel, path in items:
        if path.stat().st_size > MAX_FILE_BYTES:
            problems.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes")
            continue
        text = _text_of(path)
        for match in TOKEN_PATTERNS.findall(text):
            if not scenario_mod.FAKE_MARKER.search(match):
                problems.append(f"{rel}: credential-shaped value without a FAKE/EXAMPLE/SYNTHETIC marker")
                break
        for match in HOME_PATTERNS.findall(text):
            if match not in ALLOWED_HOME_SEGMENTS:
                problems.append(f"{rel}: user home path present")
                break
        if home and home in text:
            problems.append(f"{rel}: this machine's home directory present")
        if user and len(user) >= 3 and re.search(rf"\b{re.escape(user)}\b", text):
            problems.append(f"{rel}: local username present")
        for url in scenario_mod.URL_PATTERN.findall(text):
            host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url).split("/")[0].split(":")[0].lower()
            if not scenario_mod.RESERVED_HOST.search(host):
                problems.append(f"{rel}: non-reserved URL host")
                break
    return problems


def export_case(
    *,
    root: Path,
    report_path: Path,
    out: Path,
    scenario_ref: str,
    extra_dirs: list[Path],
    allow_origin: list[str],
) -> dict:
    report = read_json(report_path)
    origin = report.get("data_origin")
    if origin in NEVER_EXPORTABLE:
        raise LabError("snapshot evidence is private and cannot be exported; author a synthetic reconstruction instead")
    if origin not in set(allow_origin):
        raise LabError(f"data origin {origin!r} is not allowed for export (allowed: {sorted(set(allow_origin))})")
    sc = scenario_mod.resolve(scenario_ref, extra_dirs)
    reported = report.get("scenario") or {}
    if reported.get("id") != sc.id or reported.get("sha256") != sc.sha256:
        raise LabError("report was not produced from this exact scenario revision; re-run analyze")
    if out.exists() and any(out.iterdir()):
        raise LabError(f"output directory is not empty: {out}")

    native_files = [p for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ("generation.json",)]
    if not any(p.name != ".telltale-fixtures" for p in native_files):
        raise LabError("root contains no native files")
    items = [(p.relative_to(root).as_posix(), p) for p in native_files] + [("scenario.json", sc.path)]
    problems = leakage_problems(items)
    if problems:
        raise LabError("export blocked by leakage checks:\n  " + "\n  ".join(problems))

    native_out = out / "native"
    for src in native_files:
        dst = native_out / src.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (native_out / ".telltale-fixtures").write_bytes(b"")
    shutil.copyfile(sc.path, out / "scenario.json")
    case = {
        "format": FORMAT,
        "case_id": sc.id,
        "data_origin": origin,
        "source_id": report.get("source_id"),
        "scenario_sha256": sc.sha256,
        "generation": report.get("generation"),
        "labels": {
            "disposition": sc.data["disposition"],
            "review": sc.data["review"],
            "rule_expectations": sc.rule_expectations(),
            "visibility_limitations": sc.data["visibility_limitations"],
        },
    }
    write_json(out / "case.json", case)
    # Observed output is kept in its own file so it is never mistaken for a label.
    write_json(out / "observed.json", {
        "telltale": report["telltale"],
        "rules": report["rules"],
        "observed_rule_ids": report["observed"]["rule_ids"],
        "evaluation_status": report["evaluation"]["status"],
        "acquisition": {k: report["scan"][k] for k in ("parse_success_source_count", "parse_error_source_count", "visibility_limited_source_count", "failures")},
    })
    return {"case_id": sc.id, "checks": ["origin", "scenario-revision", "tokens", "home-paths", "username", "urls", "size"]}
