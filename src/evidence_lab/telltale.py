"""Invoke the Telltale CLI. Telltale owns acquisition, detection, privacy and
Event 3.0; this module only runs it in an isolated way and reads its output.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .util import LabError, sha256_file

# The revision this lab was last validated against. Newer revisions may work;
# `doctor` reports a difference rather than refusing.
TESTED_VERSION = "0.7.0-rc.3"
TESTED_REVISION = "fd4899aadcf2"
VERSION_PATTERN = re.compile(r"^telltale (\S+) \(([0-9a-f]+)\)")


@dataclass(frozen=True)
class Binary:
    path: Path
    version: str
    revision: str
    sha256: str

    def describe(self) -> dict:
        return {"version": self.version, "revision": self.revision, "sha256": self.sha256}


@dataclass
class ScanResult:
    returncode: int
    summary: dict | None
    events: list[dict]
    stderr_tail: str
    command: list[str] = field(default_factory=list)

    @property
    def detections(self) -> list[dict]:
        return [e for e in self.events if e.get("event_type") == "detection"]


def find_binary(explicit: str | None = None) -> Binary:
    candidate = explicit or os.environ.get("TELLTALE_BIN") or shutil.which("telltale")
    if not candidate:
        raise LabError("Telltale binary not found: pass --telltale, set TELLTALE_BIN, or put telltale on PATH")
    path = Path(candidate)
    if not path.is_file():
        raise LabError(f"Telltale binary does not exist: {path}")
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=30, check=False)
    except OSError as exc:
        raise LabError(f"cannot execute Telltale binary: {exc}") from exc
    match = VERSION_PATTERN.match(out.stdout.strip())
    if out.returncode != 0 or not match:
        raise LabError(f"unexpected `telltale --version` output: {out.stdout.strip()!r}")
    return Binary(path=path, version=match.group(1), revision=match.group(2), sha256=sha256_file(path))


def _run(binary: Binary, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELLTALE_")}
    return subprocess.run(
        [str(binary.path), *args], capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


def _last_json_object(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def rule_args(rules: list[Path], config_dirs: list[Path], no_default_rules: bool) -> list[str]:
    args: list[str] = []
    for rule in rules:
        args += ["--rules", str(rule)]
    if config_dirs:
        for directory in config_dirs:
            args += ["--config-dir", str(directory)]
    else:
        args.append("--no-local-config")  # never pick up the operator's own config implicitly
    if no_default_rules:
        args.append("--no-default-rules")
    return args


def validate_rules(binary: Binary, rules: list[Path], config_dirs: list[Path] | None = None) -> tuple[bool, dict | None, str]:
    proc = _run(binary, ["rules", "validate", *rule_args(rules, config_dirs or [], False)])
    return proc.returncode == 0, _last_json_object(proc.stdout), proc.stderr.strip()[-2000:]


def scan(
    binary: Binary,
    root: Path,
    out_dir: Path,
    rules: list[Path] | None = None,
    config_dirs: list[Path] | None = None,
    no_default_rules: bool = False,
    client: str | None = None,
) -> ScanResult:
    """One isolated emitting scan of a fixture-layout root into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "events.jsonl"
    state_path = out_dir / "state.json"
    for stale in (log_path, state_path):
        if stale.exists():
            stale.unlink()
    args = [
        "scan", "--root", str(root), "--once", "--allow-fixtures",
        "--log-path", str(log_path), "--state-path", str(state_path),
        "--install-inventory-disabled", "--emit-activity", "--log-rotate-disabled",
        *rule_args(rules or [], config_dirs or [], no_default_rules),
    ]
    if client:
        args += ["--client", client]
    proc = _run(binary, args)
    events: list[dict] = []
    if log_path.exists():
        with open(log_path, encoding="utf-8") as handle:
            events = [json.loads(line) for line in handle if line.strip()]
    return ScanResult(
        returncode=proc.returncode,
        summary=_last_json_object(proc.stdout),
        events=events,
        stderr_tail=proc.stderr.strip()[-2000:],
        command=["telltale", *args],
    )
