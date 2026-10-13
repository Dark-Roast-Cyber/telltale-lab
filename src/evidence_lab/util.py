"""Small shared helpers: hashing, canonical JSON, atomic writes, git-tree checks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class LabError(Exception):
    """An expected, user-facing failure. The CLI prints the message and exits 2."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: str, length: int = 24) -> str:
    """Deterministic hex identifier derived from the given parts."""
    return sha256_bytes("\x1f".join(parts).encode("utf-8"))[:length]


def stable_uuid(*parts: str) -> str:
    """Deterministic RFC 4122-shaped (version 4 layout) UUID string."""
    h = sha256_bytes("\x1f".join(parts).encode("utf-8"))
    return f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_json(path: Path, value: Any) -> None:
    """Write pretty JSON atomically (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise LabError(f"timestamp must include a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def iso_ms(moment: datetime) -> str:
    """RFC 3339 UTC with millisecond precision, as Codex writes it."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def offset(start: datetime, seconds: float) -> datetime:
    return start + timedelta(seconds=seconds)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enclosing_git_worktree(path: Path) -> Path | None:
    """Return the nearest ancestor (inclusive) containing a `.git` entry, if any."""
    current = path.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None
