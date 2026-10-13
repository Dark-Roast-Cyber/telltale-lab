"""Controlled real-harness capture inside an enforced sandbox.

Linux only for now: bubblewrap with every namespace unshared (no network), a
fresh HOME and workspace, the host root mounted read-only except /home, and
no access to the operator's home or the vault. The only optional egress is a
local model endpoint reached through a Unix-socket forwarder
(`--network loopback-model`); bytes through it are counted on the host side.

Before the harness starts, probes run inside the identical sandbox and the run
is refused unless every boundary check passes. Windows and macOS are refused
until a verified disposable VM/sandbox arrangement exists.

Lab-side observations (workspace diff, model-forwarder traffic, exit status)
are recorded separately from the harness's own session records and from
Telltale's output.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import analysis, telltale
from .config import Vault, restrict
from .scenario import Scenario
from .util import LabError, sha256_file, utc_now, write_json

SANDBOX_HOME = "/home/lab"
SANDBOX_WORKSPACE = "/workspace"
SANDBOX_TOOLS = "/opt/lab"
SANDBOX_MODEL_PORT = 11434


@dataclass(frozen=True)
class Harness:
    name: str
    executable: str
    source_id: str

    def command(self, prompt: str, model: str) -> list[str]:
        raise NotImplementedError

    def configure(self, home: Path, model: str) -> None:
        """Write harness config inside the disposable HOME (no credentials)."""

    def stage(self, home: Path, root: Path) -> list[Path]:
        """Copy only the native session store into a fixture-layout root."""
        raise NotImplementedError


class CodexHarness(Harness):
    def command(self, prompt: str, model: str) -> list[str]:
        # Codex's own sandbox stays enabled (workspace-write); the outer
        # bubblewrap boundary is what the lab relies on.
        return [f"{SANDBOX_TOOLS}/bin/codex", "exec", "--skip-git-repo-check", "--oss",
                "--local-provider", "ollama", "-m", model, "--sandbox", "workspace-write",
                "--cd", SANDBOX_WORKSPACE, prompt]

    def configure(self, home: Path, model: str) -> None:
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "config.toml").write_text(
            f'model = "{model}"\n'
            "[model_providers.ollama]\n"
            'name = "Ollama"\n'
            f'base_url = "http://127.0.0.1:{SANDBOX_MODEL_PORT}/v1"\n',
            encoding="utf-8",
        )

    def stage(self, home: Path, root: Path) -> list[Path]:
        copied = []
        for sub in ("sessions", "archived_sessions"):
            src = home / ".codex" / sub
            if src.is_dir():
                for path in sorted(src.rglob("*.jsonl")):
                    dst = root / "codex" / sub / path.relative_to(src)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dst)
                    copied.append(dst)
        return copied


class OpenCodeHarness(Harness):
    def command(self, prompt: str, model: str) -> list[str]:
        return [f"{SANDBOX_TOOLS}/bin/opencode", "run", "-m", f"ollama/{model}", prompt]

    def configure(self, home: Path, model: str) -> None:
        cfg = home / ".config" / "opencode"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "opencode.json").write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "provider": {"ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (lab loopback)",
                "options": {"baseURL": f"http://127.0.0.1:{SANDBOX_MODEL_PORT}/v1"},
                "models": {model: {"name": model}},
            }},
            "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny"},
        }, indent=2), encoding="utf-8")

    def stage(self, home: Path, root: Path) -> list[Path]:
        src = home / ".local" / "share" / "opencode" / "opencode.db"
        if not src.is_file():
            return []
        dst = root / "opencode" / "opencode.db"
        dst.parent.mkdir(parents=True, exist_ok=True)
        # The harness has exited; back up to a single consistent file.
        source = sqlite3.connect(src)
        try:
            target = sqlite3.connect(dst)
            try:
                source.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
        finally:
            source.close()
        return [dst]


HARNESSES: dict[str, Harness] = {
    "codex": CodexHarness("codex", "codex", "codex.sessions"),
    "opencode": OpenCodeHarness("opencode", "opencode", "opencode.sqlite"),
}

PROBE_SCRIPT = r"""
import json, os, socket, sys
checks = {}
def attempt(fn):
    try:
        fn(); return True
    except Exception:
        return False
forbidden = [p for p in sys.argv[1:] if p]
checks["forbidden_paths_invisible"] = all(not os.path.exists(p) for p in forbidden)
checks["workspace_writable"] = attempt(lambda: open("/workspace/.lab-probe", "w").write("x")) and attempt(lambda: os.remove("/workspace/.lab-probe"))
checks["system_read_only"] = not attempt(lambda: open("/usr/.lab-probe", "w"))
def connect(host, port):
    s = socket.create_connection((host, port), timeout=2); s.close()
checks["external_tcp_blocked"] = not attempt(lambda: connect("1.1.1.1", 443)) and not attempt(lambda: connect("8.8.8.8", 53))
checks["dns_blocked"] = not attempt(lambda: socket.getaddrinfo("example.com", 443))
checks["host_loopback_unreachable"] = not attempt(lambda: connect("127.0.0.1", 22))
print(json.dumps(checks))
"""

FORWARDER_SCRIPT = r"""
import socket, sys, threading
sock_path, port = sys.argv[1], int(sys.argv[2])
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port)); srv.listen(16)
def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except OSError: pass
    finally:
        for s in (a, b):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
while True:
    c, _ = srv.accept()
    u = socket.socket(socket.AF_UNIX); u.connect(sock_path)
    threading.Thread(target=pipe, args=(c, u), daemon=True).start()
    threading.Thread(target=pipe, args=(u, c), daemon=True).start()
"""


def isolation_status() -> dict:
    if platform.system() != "Linux":
        return {"mechanism": None, "available": False,
                "detail": f"no verified sandbox integration on {platform.system()}; live capture refused"}
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return {"mechanism": "bubblewrap", "available": False, "detail": "bwrap not installed"}
    probe = subprocess.run([bwrap, "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"],
                           capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode != 0:
        return {"mechanism": "bubblewrap", "available": False,
                "detail": f"user namespaces unavailable: {probe.stderr.strip()[:200]}"}
    return {"mechanism": "bubblewrap", "available": True, "detail": "all namespaces unshared; no network"}


class ModelForwarder:
    """Host-side Unix socket -> TCP endpoint relay with byte accounting."""

    def __init__(self, socket_path: Path, endpoint: str) -> None:
        parts = urlsplit(endpoint)
        if parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise LabError("model endpoint must be a host loopback address (tunnel remote endpoints to loopback first)")
        self.target = (parts.hostname, parts.port or 80)
        self.socket_path = socket_path
        self.stats = {"connections": 0, "bytes_to_model": 0, "bytes_from_model": 0}
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(socket_path))
        self._server.listen(16)
        self._lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def _pipe(self, src: socket.socket, dst: socket.socket, key: str) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
                with self._lock:
                    self.stats[key] += len(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(self.target, timeout=10)
            except OSError:
                client.close()
                continue
            with self._lock:
                self.stats["connections"] += 1
            threading.Thread(target=self._pipe, args=(client, upstream, "bytes_to_model"), daemon=True).start()
            threading.Thread(target=self._pipe, args=(upstream, client, "bytes_from_model"), daemon=True).start()

    def close(self) -> None:
        self._server.close()


def _workspace_state(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _diff(before: dict[str, str], after: dict[str, str]) -> dict:
    return {
        "created": sorted(set(after) - set(before)),
        "deleted": sorted(set(before) - set(after)),
        "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
    }


def _bwrap_args(run_dir: Path, harness_binary: Path, with_model: bool) -> list[str]:
    args = [
        "bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--hostname", "lab",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
        "--bind", str(run_dir / "home"), SANDBOX_HOME,
        "--bind", str(run_dir / "workspace"), SANDBOX_WORKSPACE,
        "--ro-bind", str(run_dir / "tools"), SANDBOX_TOOLS,
        "--ro-bind", str(harness_binary), f"{SANDBOX_TOOLS}/bin/{harness_binary.name}",
        "--clearenv", "--setenv", "HOME", SANDBOX_HOME, "--setenv", "USER", "lab",
        "--setenv", "PATH", f"{SANDBOX_TOOLS}/bin:/usr/bin", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TMPDIR", "/tmp", "--chdir", SANDBOX_WORKSPACE,
    ]
    if with_model:
        args += ["--bind", str(run_dir / "model.sock"), "/run/model.sock"]
    return args


def run(
    *,
    vault: Vault,
    scenario: Scenario,
    harness: str,
    model: str,
    binary: telltale.Binary,
    timeout: int,
    network: str,
    dry_run: bool,
    model_endpoint: str = "http://127.0.0.1:11434",
) -> dict:
    spec = HARNESSES[harness]
    live = scenario.data.get("live")
    run_id = f"run-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{harness}-{os.getpid()}"
    blockers: list[str] = []
    iso = isolation_status()
    if not iso["available"]:
        blockers.append(f"isolation unavailable: {iso['detail']}")
    exe = shutil.which(spec.executable)
    if not exe:
        blockers.append(f"{spec.executable} not installed")
    if not live:
        blockers.append("scenario has no `live` section (prompt and workspace files)")
    if network == "none":
        blockers.append("network=none leaves the harness no model backend; use --network loopback-model with a local model")
    record = {
        "format": "telltale-lab/controlled-run/v1",
        "run_id": run_id,
        "data_origin": "controlled-run",
        "scenario_id": scenario.id,
        "scenario_sha256": scenario.sha256,
        "harness": harness,
        "model": model,
        "network": network,
        "host_os": f"{platform.system()} {platform.release()}",
        "isolation": iso,
        "blockers": blockers,
        "status": "blocked" if blockers else "planned",
    }
    if blockers or dry_run:
        return record

    run_dir = vault.dir("controlled-runs") / run_id
    run_dir.mkdir()
    restrict(run_dir)
    for sub in ("home", "workspace", "tools", "tools/bin"):
        (run_dir / sub).mkdir()
    (run_dir / "tools" / "probe.py").write_text(PROBE_SCRIPT, encoding="utf-8")
    (run_dir / "tools" / "forward.py").write_text(FORWARDER_SCRIPT, encoding="utf-8")
    for rel, content in live.get("files", {}).items():
        target = run_dir / "workspace" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    spec.configure(run_dir / "home", model)
    harness_binary = Path(exe).resolve()
    record["harness_version"] = _version(harness_binary)

    forwarder = ModelForwarder(run_dir / "model.sock", model_endpoint)
    try:
        base = _bwrap_args(run_dir, harness_binary, with_model=True)
        forbidden = [str(Path.home()), str(vault.root)]
        probe = subprocess.run([*base, "python3", f"{SANDBOX_TOOLS}/probe.py", *forbidden],
                               capture_output=True, text=True, timeout=60, check=False)
        try:
            checks = json.loads(probe.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            checks = {"probe_failed": False}
        record["isolation"]["probes"] = checks
        record["isolation"]["verified"] = bool(checks) and all(checks.values())
        if not record["isolation"]["verified"]:
            record["status"] = "blocked"
            record["blockers"] = ["sandbox probes failed; refusing to run the harness"]
            write_json(run_dir / "run.json", record)
            return record

        before = _workspace_state(run_dir / "workspace")
        command = spec.command(live["prompt"], model)
        shell = (f"python3 {SANDBOX_TOOLS}/forward.py /run/model.sock {SANDBOX_MODEL_PORT} & "
                 'sleep 0.3; exec "$@"')
        started = utc_now()
        termination = "exited"
        with open(run_dir / "harness-output.log", "wb") as log:
            proc = subprocess.Popen([*base, "sh", "-c", shell, "sh", *command],
                                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait()
                termination = "timeout"
        ended = utc_now()
        after = _workspace_state(run_dir / "workspace")
    finally:
        forwarder.close()

    record.update({
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": ended.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "termination_reason": termination,
        "exit_code": exit_code,
        "lab_observations": {
            "workspace_changes": _diff(before, after),
            "model_traffic": dict(forwarder.stats),
            "external_network": "none possible (network namespace unshared; probes verified)",
        },
    })

    staging = run_dir / "analysis-root"
    staging.mkdir()
    (staging / ".telltale-fixtures").write_bytes(b"")
    staged = spec.stage(run_dir / "home", staging)
    record["native_records"] = [
        {"path": p.relative_to(staging).as_posix(), "size": p.stat().st_size, "sha256": sha256_file(p)} for p in staged
    ]
    if not staged:
        record["status"] = "completed"
        record["capture_completeness"] = "no_native_records_produced"
        write_json(run_dir / "run.json", record)
        return record
    scan = telltale.scan(binary, staging, run_dir / "telltale")
    report = analysis.build_report(
        scan=scan, binary=binary, data_origin="controlled-run", source_id=spec.source_id,
        scenario=scenario, rules=[], events_path=run_dir / "telltale" / "events.jsonl",
    )
    write_json(run_dir / "report.json", report)
    record["status"] = "completed"
    record["capture_completeness"] = "session_store_staged"
    record["telltale_evaluation"] = report["evaluation"]
    write_json(run_dir / "run.json", record)
    return record


def _version(path: Path) -> str:
    try:
        env = {"HOME": "/nonexistent", "PATH": "/usr/bin"}
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=30, env=env, check=False)
        return (out.stdout.strip() or out.stderr.strip()).splitlines()[-1][:200]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "unknown"


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(isolation_status()))
    sys.exit(0)
