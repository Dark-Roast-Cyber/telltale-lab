"""Lab configuration and the private evidence vault.

The vault is never implied: it comes from `--vault`, `TELLTALE_LAB_VAULT`, or
the config file written by `tlab init`. It must live outside any Git work
tree. The lab relies on operating-system disk encryption and file
permissions; it does not implement its own encryption.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .util import LabError, enclosing_git_worktree, read_json, write_json

VAULT_SUBDIRS = ("snapshots", "controlled-runs", "reports", "synthetic")


def config_path() -> Path:
    override = os.environ.get("TELLTALE_LAB_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "telltale-lab" / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise LabError(f"lab config is not a JSON object: {path}")
    return data


def save_config(values: dict) -> Path:
    path = config_path()
    write_json(path, values)
    return path


@dataclass(frozen=True)
class Vault:
    root: Path

    def dir(self, name: str) -> Path:
        assert name in VAULT_SUBDIRS, name
        return self.root / name


def check_vault_location(path: Path) -> None:
    if not path.is_absolute():
        raise LabError("vault path must be absolute")
    worktree = enclosing_git_worktree(path if path.exists() else _existing_ancestor(path))
    if worktree is not None:
        raise LabError("vault must not be inside a Git work tree (refusing to store evidence in a repository)")


def _existing_ancestor(path: Path) -> Path:
    for candidate in [path, *path.parents]:
        if candidate.exists():
            return candidate
    return Path(path.anchor)


def resolve_vault(explicit: str | None, required: bool = True) -> Vault | None:
    value = explicit or os.environ.get("TELLTALE_LAB_VAULT") or load_config().get("vault")
    if not value:
        if required:
            raise LabError("no vault configured: run `tlab init --vault <absolute path outside any repo>`")
        return None
    root = Path(value).expanduser()
    check_vault_location(root)
    if not root.is_dir():
        raise LabError("configured vault does not exist; run `tlab init` again")
    return Vault(root)


def init_vault(path: Path) -> Vault:
    path = path.expanduser()
    check_vault_location(path)
    path.mkdir(parents=True, exist_ok=True)
    restrict(path)
    for name in VAULT_SUBDIRS:
        sub = path / name
        sub.mkdir(exist_ok=True)
        restrict(sub)
    return Vault(path)


def restrict(path: Path) -> None:
    """Owner-only permissions on POSIX. On Windows, inherited NTFS ACLs apply;
    `doctor` reports that they were not verified."""
    if os.name != "nt":
        os.chmod(path, stat.S_IRWXU)


def permission_status(path: Path) -> dict:
    if os.name == "nt":
        return {"checked": False, "detail": "NTFS ACLs not inspected; confirm the vault is in a private, encrypted user profile"}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {"checked": True, "mode": oct(mode), "owner_only": mode & 0o077 == 0}


def encryption_status(path: Path) -> dict:
    """Best-effort detection of OS disk encryption under `path`. Returns
    `verified` only when a dm-crypt layer is found beneath the filesystem."""
    if platform.system() != "Linux":
        return {"status": "unverified", "detail": f"no automatic check on {platform.system()}; confirm BitLocker/FileVault manually"}
    try:
        source = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "--target", str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip().split("[")[0]
        if not source.startswith("/dev/"):
            return {"status": "unverified", "detail": "filesystem source is not a block device"}
        types = subprocess.run(
            ["lsblk", "-n", "-s", "-o", "TYPE", source],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unverified", "detail": f"probe failed: {type(exc).__name__}"}
    if "crypt" in types:
        return {"status": "verified", "detail": "dm-crypt layer found beneath the vault filesystem"}
    return {"status": "not_detected", "detail": "no dm-crypt layer found; data may be unencrypted at rest"}
