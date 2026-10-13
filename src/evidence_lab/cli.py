"""`tlab` command line. Console output never includes transcript content,
secret values, or private paths; detailed results go to JSON reports."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from . import analysis, capture, config, export, native, scenario, snapshot, telltale
from .util import LabError, utc_now, write_json


def _extra_scenario_dirs(args: argparse.Namespace) -> list[Path]:
    dirs = [Path(d) for d in (getattr(args, "scenario_dir", None) or [])]
    configured = config.load_config().get("scenario_dirs") or []
    return dirs + [Path(d) for d in configured]


def cmd_init(args: argparse.Namespace) -> int:
    vault = config.init_vault(Path(args.vault))
    values = config.load_config()
    values["vault"] = str(vault.root)
    if args.telltale:
        values["telltale"] = str(Path(args.telltale).resolve())
    path = config.save_config(values)
    print(f"vault initialized with subdirectories {', '.join(config.VAULT_SUBDIRS)}")
    print(f"config written: {path}")
    enc = config.encryption_status(vault.root)
    print(f"encryption at rest: {enc['status']} ({enc['detail']})")
    return 0


def _binary(args: argparse.Namespace) -> telltale.Binary:
    return telltale.find_binary(args.telltale or config.load_config().get("telltale"))


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    print(f"platform: {platform.system()} {platform.release()} python {platform.python_version()}")
    try:
        binary = _binary(args)
        tested = binary.version == telltale.TESTED_VERSION and binary.revision.startswith(telltale.TESTED_REVISION[:7])
        print(f"telltale: {binary.version} ({binary.revision}) {'[tested revision]' if tested else '[differs from tested ' + telltale.TESTED_VERSION + ' ' + telltale.TESTED_REVISION + ']'}")
    except LabError as exc:
        ok = False
        print(f"telltale: MISSING - {exc}")
    try:
        vault = config.resolve_vault(args.vault, required=False)
    except LabError as exc:
        ok = False
        vault = None
        print(f"vault: INVALID - {exc}")
    else:
        if vault is None:
            print("vault: not configured (needed for snapshot/capture; generate/analyze work with --out)")
        else:
            perm = config.permission_status(vault.root)
            enc = config.encryption_status(vault.root)
            missing = [d for d in config.VAULT_SUBDIRS if not vault.dir(d).is_dir()]
            print(f"vault: configured; permissions={perm}; encryption={enc['status']} ({enc['detail']})")
            if missing:
                ok = False
                print(f"vault: missing subdirectories {missing}; rerun `tlab init`")
            if perm.get("checked") and not perm.get("owner_only"):
                ok = False
                print("vault: WARNING group/other permissions present")
    for name in ("codex", "claude", "opencode", "qwen", "openclaw", "copilot"):
        print(f"harness {name}: {'found on PATH' if shutil.which(name) else 'not found'}")
    iso = capture.isolation_status()
    print(f"isolation: {iso['mechanism'] or 'none'} available={iso['available']} ({iso['detail']})")
    try:
        found = scenario.discover([d for d in [scenario.builtin_dir(), *_extra_scenario_dirs(args)] if d.is_dir()])
        print(f"scenarios: {len(found)} valid")
    except LabError as exc:
        ok = False
        print(f"scenarios: INVALID - {exc}")
    return 0 if ok else 1


def cmd_scenarios(args: argparse.Namespace) -> int:
    if args.id:
        sc = scenario.resolve(args.id, _extra_scenario_dirs(args))
        print(json.dumps(sc.data, indent=2, ensure_ascii=False))
        return 0
    found = scenario.discover([d for d in [scenario.builtin_dir(), *_extra_scenario_dirs(args)] if d.is_dir()])
    for sc in found.values():
        d = sc.data
        print(f"{sc.id:55} {d['disposition']:10} review={d['review']['expectation']:9} formats={','.join(sc.formats)}")
    return 0


def _generate(sc: scenario.Scenario, source_id: str, out: Path) -> dict:
    if out.exists() and any(out.iterdir()):
        raise LabError(f"output directory is not empty: {out}")
    files = native.generate(sc, source_id, out)
    record = {
        "format": "telltale-lab/generation/v1",
        "data_origin": "synthetic",
        "scenario_id": sc.id,
        "scenario_sha256": sc.sha256,
        "source_id": source_id,
        "generator": native.generator_version(source_id),
        "files": [f.relative_to(out).as_posix() for f in files],
    }
    write_json(out / "generation.json", record)
    return record


def _default_out(args: argparse.Namespace, sc: scenario.Scenario, source_id: str) -> Path:
    if args.out:
        return Path(args.out)
    vault = config.resolve_vault(args.vault)
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return vault.dir("synthetic") / sc.id / f"{source_id}-{stamp}"


def cmd_generate(args: argparse.Namespace) -> int:
    sc = scenario.resolve(args.scenario, _extra_scenario_dirs(args))
    formats = sc.formats if args.format == "all" else [args.format]
    for source_id in formats:
        out = _default_out(args, sc, source_id) if len(formats) == 1 else _default_out(args, sc, source_id) / source_id
        record = _generate(sc, source_id, out)
        print(f"generated {sc.id} as {source_id}: {len(record['files'])} file(s) -> {out}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    binary = _binary(args)
    sc = scenario.resolve(args.scenario, _extra_scenario_dirs(args)) if args.scenario else None
    rules = [Path(r).resolve() for r in args.rules or []]
    for rule in rules:
        if not rule.is_file():
            raise LabError(f"rule file not found: {rule}")
    temp: tempfile.TemporaryDirectory | None = None
    generation = None
    if args.root:
        root = Path(args.root)
        source_id = args.source_id
        origin = args.origin
        gen_file = root / "generation.json"
        if gen_file.is_file():
            generation = json.loads(gen_file.read_text(encoding="utf-8"))
            source_id = source_id or generation.get("source_id")
    else:
        if sc is None:
            raise LabError("pass --root, or --scenario with --format to generate and analyze in one step")
        source_id = args.format or sc.formats[0]
        temp = tempfile.TemporaryDirectory(prefix="tlab-")
        root = Path(temp.name) / "root"
        generation = _generate(sc, source_id, root)
        origin = "synthetic"
    try:
        out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="tlab-analysis-"))
        scan_dir = out / "telltale"
        result = telltale.scan(
            binary, root, scan_dir, rules=rules, no_default_rules=args.no_default_rules,
            config_dirs=[Path(d) for d in args.config_dir or []],
        )
        report = analysis.build_report(
            scan=result, binary=binary, data_origin=origin, source_id=source_id, scenario=sc,
            rules=rules, events_path=scan_dir / "events.jsonl",
            event_schema=Path(args.event_schema) if args.event_schema else None, generation=generation,
        )
        write_json(out / "report.json", report)
        print(analysis.render_text(report))
        print(f"report: {out / 'report.json'}")
    finally:
        if temp is not None:
            temp.cleanup()
    status = report["evaluation"]["status"]
    if args.check and status not in ("detected", "clean", "unlabeled"):
        return 1
    if report["privacy"]["leaked_marker_ids"]:
        return 1
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    vault = config.resolve_vault(args.vault)
    if args.snapshot_command == "import":
        manifest = snapshot.create(
            vault,
            sources=[Path(s) for s in args.source],
            harness=args.harness,
            harness_version=args.harness_version,
            source_os=args.source_os,
            source_identity=args.identity,
            method=args.method,
            privacy=args.privacy,
            notes=args.note or [],
        )
        print(f"snapshot {manifest['snapshot_id']}: status={manifest['status']} files={len(manifest['files'])} "
              f"skipped={len(manifest['skipped'])} errors={len(manifest['errors'])}")
        return 0 if manifest["status"] == "complete" else 1
    if args.snapshot_command == "verify":
        result = snapshot.verify(vault, args.snapshot_id)
        print(f"snapshot {args.snapshot_id}: {'OK' if result['ok'] else 'FAILED'} "
              f"checked={result['checked']} problems={len(result['problems'])}")
        for problem in result["problems"]:
            print(f"  {problem}")
        return 0 if result["ok"] else 1
    for entry in snapshot.list_snapshots(vault):
        print(f"{entry['snapshot_id']}  {entry['harness']:10} {entry['status']:10} files={entry['file_count']}")
    return 0


def cmd_export_case(args: argparse.Namespace) -> int:
    result = export.export_case(
        root=Path(args.root),
        report_path=Path(args.report),
        out=Path(args.out),
        scenario_ref=args.scenario,
        extra_dirs=_extra_scenario_dirs(args),
        allow_origin=args.allow_origin,
    )
    print(f"exported case {result['case_id']} -> {args.out} (checks: {', '.join(result['checks'])})")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    vault = config.resolve_vault(args.vault)
    sc = scenario.resolve(args.scenario, _extra_scenario_dirs(args))
    binary = _binary(args)
    record = capture.run(
        vault=vault, scenario=sc, harness=args.harness, model=args.model,
        binary=binary, timeout=args.timeout, network=args.network, dry_run=args.dry_run,
        model_endpoint=args.model_endpoint,
    )
    print(f"capture {record['run_id']}: status={record['status']} reason={record.get('termination_reason')}")
    for item in record.get("blockers", []):
        print(f"  blocker: {item}")
    return 0 if record["status"] in ("completed", "planned") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tlab", description="Telltale evidence lab")
    parser.add_argument("--vault", help="private vault (overrides TELLTALE_LAB_VAULT and config)")
    parser.add_argument("--telltale", help="Telltale binary (overrides TELLTALE_BIN, config, PATH)")
    parser.add_argument("--scenario-dir", action="append", help="extra scenario directory (repeatable)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the private vault and write lab config")
    p.add_argument("--vault", required=True, dest="vault")
    p.add_argument("--telltale", dest="telltale")
    p.set_defaults(func=cmd_init)

    sub.add_parser("doctor", help="check Telltale, vault, harnesses, isolation").set_defaults(func=cmd_doctor)

    p = sub.add_parser("scenarios", help="list scenarios or show one")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("generate", help="write deterministic source-native synthetic evidence")
    p.add_argument("scenario")
    p.add_argument("--format", default="all", help="source id (codex.sessions, opencode.sqlite) or all")
    p.add_argument("--out", help="output directory (default: vault synthetic/)")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("analyze", help="run Telltale over a fixture-layout root and compare with labels")
    p.add_argument("--root", help="fixture-layout root (from generate, export-case, or a capture)")
    p.add_argument("--scenario", help="scenario id or path supplying independent labels")
    p.add_argument("--format", help="with --scenario and no --root: generate this source id first")
    p.add_argument("--source-id", help="source id of --root when generation.json is absent")
    p.add_argument("--origin", default="synthetic", choices=sorted(analysis.DATA_ORIGINS))
    p.add_argument("--rules", action="append", help="additional rule YAML (additive --rules)")
    p.add_argument("--config-dir", action="append", help="explicit Telltale config root (rules.d etc.)")
    p.add_argument("--no-default-rules", action="store_true")
    p.add_argument("--event-schema", help="Telltale schemas/event.schema.json for full validation")
    p.add_argument("--out", help="report directory (default: new temp dir)")
    p.add_argument("--check", action="store_true", help="exit 1 unless status is detected/clean")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("snapshot", help="import/verify/list private snapshots")
    snap = p.add_subparsers(dest="snapshot_command", required=True)
    s = snap.add_parser("import", help="read-only import of explicitly selected files/directories")
    s.add_argument("--source", action="append", required=True)
    s.add_argument("--harness", required=True)
    s.add_argument("--harness-version", default="unknown")
    s.add_argument("--source-os", default="unknown")
    s.add_argument("--identity", default="unspecified", help="operator-supplied source label (no personal data)")
    s.add_argument("--method", default="local-copy")
    s.add_argument("--privacy", default="private", choices=["private", "restricted", "synthetic"])
    s.add_argument("--note", action="append")
    s = snap.add_parser("verify")
    s.add_argument("snapshot_id")
    snap.add_parser("list")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("export-case", help="package a reviewed synthetic case for public use")
    p.add_argument("--root", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--scenario", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--allow-origin", action="append", default=["synthetic"],
                   help="data origins eligible for export (default: synthetic only)")
    p.set_defaults(func=cmd_export_case)

    p = sub.add_parser("capture", help="controlled real-harness run inside an enforced sandbox")
    p.add_argument("scenario")
    p.add_argument("--harness", required=True, choices=sorted(capture.HARNESSES))
    p.add_argument("--model", required=True, help="model/backend identifier passed to the harness")
    p.add_argument("--network", default="none", choices=["none", "loopback-model"],
                   help="none = no network; loopback-model = only a local model endpoint via host loopback")
    p.add_argument("--model-endpoint", default="http://127.0.0.1:11434",
                   help="host loopback model endpoint (tunnel remote servers to loopback first)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--dry-run", action="store_true", help="check prerequisites and print the plan only")
    p.set_defaults(func=cmd_capture)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
