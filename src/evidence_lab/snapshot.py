"""Read-only import of explicitly selected harness session collections into the
private vault, with provenance and integrity metadata.

Rules:
- Only paths the operator names are read; nothing is auto-discovered.
- Source files are opened read-only. SQLite sources are never opened with
  SQLite in place (a WAL reader may write the -shm index); the raw file set is
  copied, checked for stability, and a consistent single-file database is then
  produced from the private copy with SQLite's backup API.
- Symbolic links are recorded, never followed.
- Snapshot ids are unique and directories are created exclusively; files are
  made read-only after capture.
"""

from __future__ import annotations

import os
import platform
import secrets
import shutil
import sqlite3
import stat
from pathlib import Path

from .config import Vault, restrict
from .util import LabError, read_json, sha256_bytes, sha256_file, utc_now, write_json

FORMAT = "telltale-lab/snapshot/v1"
SQLITE_MAGIC = b"SQLite format 3\x00"
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
STABILITY_ATTEMPTS = 3


def _is_sqlite(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _new_snapshot_id() -> str:
    return f"snap-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _safe_relative(rel: Path) -> Path:
    if rel.is_absolute() or any(part in ("..", "") for part in rel.parts):
        raise LabError(f"unsafe relative path in source walk: {rel.as_posix()!r}")
    return rel


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # O_NOFOLLOW where available so a file swapped for a symlink mid-walk is refused.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(src, flags)
    with os.fdopen(fd, "rb") as reader, open(dst, "xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)


def _fingerprint(paths: list[Path]) -> list[tuple[str, int, str] | None]:
    out: list[tuple[str, int, str] | None] = []
    for path in paths:
        if path.exists():
            out.append((path.name, path.stat().st_size, sha256_file(path)))
        else:
            out.append(None)
    return out


def _capture_sqlite(src: Path, staging: Path, rel: Path) -> dict:
    """Copy a SQLite database and sidecars, require a stable source across the
    copy, then write a consistent backup produced from the private copy."""
    family = [src] + [src.with_name(src.name + suffix) for suffix in SQLITE_SIDECARS]
    raw_dir = staging / "raw-sqlite" / rel.parent
    for attempt in range(1, STABILITY_ATTEMPTS + 1):
        before = _fingerprint(family)
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        for member in family:
            if member.exists():
                _copy_file(member, raw_dir / member.name)
        after = _fingerprint(family)
        if before == after:
            break
    else:
        return {"consistency": "source_changed_during_capture", "attempts": STABILITY_ATTEMPTS}

    target = staging / "native" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    copy_db = raw_dir / src.name
    source_conn = sqlite3.connect(copy_db)  # private copy: WAL replay may write here, never to the source
    try:
        dest_conn = sqlite3.connect(target)
        try:
            source_conn.backup(dest_conn)
            dest_conn.execute("PRAGMA journal_mode=DELETE")
            integrity = dest_conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    shutil.rmtree(staging / "raw-sqlite")
    return {
        "consistency": "stable_copy_then_backup" if integrity == "ok" else "integrity_check_failed",
        "attempts": attempt,
        "integrity_check": integrity,
        "source_family": [
            {"suffix": member.name[len(src.name):] or "(db)", "size": fp[1], "sha256": fp[2]}
            for member, fp in zip(family, after) if fp is not None
        ],
    }


def create(
    vault: Vault,
    *,
    sources: list[Path],
    harness: str,
    harness_version: str,
    source_os: str,
    source_identity: str,
    method: str,
    privacy: str,
    notes: list[str],
) -> dict:
    if not sources:
        raise LabError("at least one --source is required")
    snapshot_id = _new_snapshot_id()
    final = vault.dir("snapshots") / snapshot_id
    staging = vault.dir("snapshots") / f".staging-{snapshot_id}"
    staging.mkdir()  # exclusive: fails if it exists
    restrict(staging)
    files: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    sqlite_records: list[dict] = []
    roots: list[dict] = []
    try:
        for index, raw_source in enumerate(sources):
            source = raw_source.expanduser()
            label = f"source-{index:02d}"
            if source.is_symlink():
                skipped.append({"source": label, "path": ".", "reason": "symlink_root_not_followed"})
                continue
            if not source.exists():
                errors.append({"source": label, "path": ".", "error": "not_found"})
                continue
            roots.append({
                "label": label,
                "kind": "directory" if source.is_dir() else "file",
                "path_sha256": sha256_bytes(str(source.resolve()).encode("utf-8")),
                "name": source.name,
            })
            entries: list[tuple[Path, Path]] = []
            if source.is_file():
                entries.append((source, Path(source.name)))
            else:
                def onerror(exc: OSError, label: str = label, base: Path = source) -> None:
                    rel = Path(exc.filename).relative_to(base).as_posix() if exc.filename else "?"
                    errors.append({"source": label, "path": rel, "error": type(exc).__name__})

                for dirpath, dirnames, filenames in os.walk(source, followlinks=False, onerror=onerror):
                    base = Path(dirpath)
                    for name in sorted(dirnames):
                        if (base / name).is_symlink():
                            skipped.append({"source": label, "path": (base / name).relative_to(source).as_posix(),
                                            "reason": "symlink_not_followed"})
                    dirnames[:] = sorted(d for d in dirnames if not (base / d).is_symlink())
                    for name in sorted(filenames):
                        entries.append((base / name, _safe_relative((base / name).relative_to(source))))
            sidecars = {
                src.with_name(src.name + suffix)
                for src, _ in entries if _is_sqlite(src) for suffix in SQLITE_SIDECARS
            }
            for src, rel in entries:
                dest_rel = Path(label) / rel
                try:
                    st = src.lstat()
                    if stat.S_ISLNK(st.st_mode):
                        skipped.append({"source": label, "path": rel.as_posix(), "reason": "symlink_not_followed"})
                        continue
                    if not stat.S_ISREG(st.st_mode):
                        skipped.append({"source": label, "path": rel.as_posix(), "reason": "not_regular_file"})
                        continue
                    if src in sidecars:
                        skipped.append({"source": label, "path": rel.as_posix(), "reason": "sqlite_sidecar_captured_via_backup"})
                        continue
                    if _is_sqlite(src):
                        record = _capture_sqlite(src, staging, dest_rel)
                        record["path"] = dest_rel.as_posix()
                        sqlite_records.append(record)
                        if record["consistency"] != "stable_copy_then_backup":
                            errors.append({"source": label, "path": rel.as_posix(), "error": record["consistency"]})
                            continue
                        method_used = "sqlite_backup_from_stable_copy"
                    else:
                        before = (st.st_size, st.st_mtime_ns)
                        _copy_file(src, staging / "native" / dest_rel)
                        after = src.stat()
                        if (after.st_size, after.st_mtime_ns) != before:
                            errors.append({"source": label, "path": rel.as_posix(), "error": "changed_during_copy"})
                        method_used = "byte_copy"
                    stored = staging / "native" / dest_rel
                    files.append({
                        "path": dest_rel.as_posix(),
                        "size": stored.stat().st_size,
                        "sha256": sha256_file(stored),
                        "capture": method_used,
                    })
                except OSError as exc:
                    errors.append({"source": label, "path": rel.as_posix(), "error": type(exc).__name__})

        manifest = {
            "format": FORMAT,
            "snapshot_id": snapshot_id,
            "data_origin": "snapshot",
            "collected_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "collector": {"host_os": platform.system(), "python": platform.python_version()},
            "harness": harness,
            "harness_version": harness_version,
            "source_os": source_os,
            "source_identity": source_identity,
            "acquisition_method": method,
            "privacy": privacy,
            "cloud_llm_eligible": False,
            "roots": roots,
            "files": files,
            "sqlite": sqlite_records,
            "skipped": skipped,
            "errors": errors,
            "status": "complete" if not errors and files else "incomplete",
            "limitations": [
                "Snapshot reflects files visible at collection time; deleted or overwritten history is absent.",
                "Symbolic links were recorded and not followed.",
            ] + (["One or more files failed or changed during capture; see errors."] if errors else []),
            "notes": notes,
        }
        write_json(staging / "manifest.json", manifest)
        (staging / "manifest.sha256").write_text(sha256_file(staging / "manifest.json") + "\n", encoding="utf-8")
        _make_read_only(staging)
        os.rename(staging, final)
        if os.name != "nt":
            os.chmod(final, stat.S_IRUSR | stat.S_IXUSR)
        return manifest
    except BaseException:
        _make_writable(staging)
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _make_read_only(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(Path(dirpath) / name, stat.S_IRUSR)
    if os.name != "nt":
        for dirpath, dirnames, _ in os.walk(root, topdown=False):
            for name in dirnames:
                os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IXUSR)
        # The snapshot root stays owner-writable only long enough to be renamed.


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, stat.S_IRWXU)
        for name in filenames:
            try:
                os.chmod(Path(dirpath) / name, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass


def _load_manifest(vault: Vault, snapshot_id: str) -> tuple[Path, dict]:
    if "/" in snapshot_id or "\\" in snapshot_id or snapshot_id.startswith("."):
        raise LabError("invalid snapshot id")
    root = vault.dir("snapshots") / snapshot_id
    if not (root / "manifest.json").is_file():
        raise LabError(f"snapshot not found: {snapshot_id}")
    return root, read_json(root / "manifest.json")


def verify(vault: Vault, snapshot_id: str) -> dict:
    root, manifest = _load_manifest(vault, snapshot_id)
    problems: list[str] = []
    recorded = (root / "manifest.sha256").read_text(encoding="utf-8").strip() if (root / "manifest.sha256").is_file() else None
    if recorded != sha256_file(root / "manifest.json"):
        problems.append("manifest checksum mismatch")
    expected = {entry["path"] for entry in manifest["files"]}
    for entry in manifest["files"]:
        path = root / "native" / entry["path"]
        if not path.is_file():
            problems.append(f"missing file {entry['path']}")
        elif path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            problems.append(f"content mismatch {entry['path']}")
    native_root = root / "native"
    if native_root.is_dir():
        for path in native_root.rglob("*"):
            if path.is_file() and path.relative_to(native_root).as_posix() not in expected:
                problems.append(f"unexpected file {path.relative_to(native_root).as_posix()}")
    if manifest.get("status") != "complete":
        problems.append(f"snapshot recorded as {manifest.get('status')}")
    return {"ok": not problems, "checked": len(manifest["files"]), "problems": problems}


def list_snapshots(vault: Vault) -> list[dict]:
    out = []
    for path in sorted(vault.dir("snapshots").glob("snap-*")):
        manifest = read_json(path / "manifest.json")
        out.append({
            "snapshot_id": manifest["snapshot_id"],
            "harness": manifest["harness"],
            "status": manifest["status"],
            "file_count": len(manifest["files"]),
        })
    return out
