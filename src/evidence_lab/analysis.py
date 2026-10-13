"""Compare independent scenario labels with what Telltale actually reported.

Ground truth comes only from the scenario file. Telltale output is recorded
as the observed result and is never written back into a scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

from .scenario import Scenario
from .telltale import Binary, ScanResult
from .util import sha256_file

FORMAT = "telltale-lab/analysis/v1"
SIGNAL_EVENT_TYPES = {"detection", "process_chain", "correlation"}
ALERTING_SEVERITIES = {"medium", "high", "critical"}
EVENT_REQUIRED = ("schema_version", "event_id", "event_type", "severity", "timestamp", "client", "session_id")
DATA_ORIGINS = {"synthetic", "snapshot", "controlled-run", "public-fixture"}


def _event_rule_ids(event: dict) -> list[str]:
    ids = list(event.get("rule_ids") or [])
    if event.get("rule_id"):
        ids.append(event["rule_id"])
    return ids


def validate_events(events: list[dict], schema_path: Path | None = None) -> dict:
    """Minimal Event 3.0 structural check, plus full JSON Schema validation when
    the optional `jsonschema` package and Telltale's schema file are available."""
    problems: list[str] = []
    for index, event in enumerate(events):
        missing = [key for key in EVENT_REQUIRED if key not in event]
        if missing:
            problems.append(f"event[{index}] missing {missing}")
        if event.get("schema_version") != "3.0":
            problems.append(f"event[{index}] schema_version={event.get('schema_version')!r}")
    result = {"event_count": len(events), "structural_problems": problems, "json_schema": "not_run"}
    if schema_path is not None:
        try:
            import jsonschema  # type: ignore[import-not-found]
        except ImportError:
            result["json_schema"] = "not_run: jsonschema package not installed"
        else:
            with open(schema_path, encoding="utf-8") as handle:
                schema = json.load(handle)
            validator = jsonschema.Draft202012Validator(schema)
            errors = [f"event[{i}]: {e.message[:200]}" for i, ev in enumerate(events) for e in validator.iter_errors(ev)]
            result["json_schema"] = "passed" if not errors else "failed"
            result["json_schema_errors"] = errors[:20]
    return result


def privacy_check(scan: ScanResult, events_path: Path | None, scenario: Scenario | None) -> dict:
    """Synthetic secret markers must not appear in Telltale output."""
    if scenario is None:
        return {"markers_checked": 0, "leaked_marker_ids": []}
    blobs = [json.dumps(scan.summary or {}, ensure_ascii=False)]
    if events_path is not None and events_path.exists():
        blobs.append(events_path.read_text(encoding="utf-8"))
    text = "\n".join(blobs)
    leaked = [s["id"] for s in scenario.secrets() if s["value"] in text]
    return {"markers_checked": len(scenario.secrets()), "leaked_marker_ids": leaked}


def summarize_scan(scan: ScanResult) -> dict:
    summary = scan.summary or {}
    processing = summary.get("source_processing") or {}
    return {
        "returncode": scan.returncode,
        "summary_present": scan.summary is not None,
        "parse_success_source_count": processing.get("parse_success_source_count"),
        "parse_error_source_count": processing.get("parse_error_source_count"),
        "visibility_limited_source_count": processing.get("visibility_limited_source_count"),
        "record_kind_counts": processing.get("record_kind_counts") or {},
        "failures": processing.get("failures") or [],
        "diagnostic_warnings": summary.get("diagnostic_warnings") or [],
        "source_counts": summary.get("source_counts"),
    }


def observed(scan: ScanResult) -> dict:
    signals = [e for e in scan.events if e.get("event_type") in SIGNAL_EVENT_TYPES]
    rule_ids = sorted({rid for e in signals for rid in _event_rule_ids(e)})
    return {
        "signal_events": [
            {
                "event_type": e.get("event_type"),
                "rule_ids": sorted(_event_rule_ids(e)),
                "severity": e.get("severity"),
                "risk_score": e.get("risk_score"),
                "categories": sorted(e.get("categories") or []),
            }
            for e in signals
        ],
        "rule_ids": rule_ids,
        "alerting": any(e.get("severity") in ALERTING_SEVERITIES for e in signals),
        "scanner_errors": [e.get("error_code") or e.get("check_name") for e in scan.events if e.get("event_type") == "scanner_error"],
    }


def evaluate(scenario: Scenario | None, scan_summary: dict, seen: dict) -> dict:
    if scenario is None:
        return {"status": "unlabeled"}
    expectations = scenario.rule_expectations()
    matched = sorted(set(expectations["must_match"]) & set(seen["rule_ids"]))
    missing = sorted(set(expectations["must_match"]) - set(seen["rule_ids"]))
    violations = sorted(set(expectations["must_not_match"]) & set(seen["rule_ids"]))
    review = scenario.data["review"]["expectation"]
    review_result = {
        "alert": "agree" if seen["alerting"] else "under-alerted",
        "hunt": "agree" if seen["rule_ids"] else "no-signal",
        "no_alert": "over-alerted" if seen["alerting"] else "agree",
        "not_evaluable": "n/a",
    }[review]

    acquired = (
        scan_summary["returncode"] == 0
        and (scan_summary["parse_success_source_count"] or 0) > 0
        and (scan_summary["parse_error_source_count"] or 0) == 0
    )
    records = sum((scan_summary["record_kind_counts"] or {}).values())
    if not acquired:
        status, reason = "not_evaluable", "acquisition_failed"
    elif records == 0:
        # A source that "parses" into nothing (for example an unsupported schema
        # generation) is a visibility gap, never a clean result.
        status, reason = "not_evaluable", "no_records_acquired"
    elif missing and (scan_summary["visibility_limited_source_count"] or 0) > 0:
        status, reason = "not_evaluable", "visibility_limited"
    elif violations:
        status, reason = "false_positive", None
    elif missing:
        status, reason = "missed", None
    elif expectations["must_match"]:
        status, reason = "detected", None
    else:
        status, reason = "clean", None
    return {
        "status": status,
        "reason": reason,
        "must_match": {"matched": matched, "missing": missing},
        "must_not_match": {"violations": violations},
        "review": {"expected": review, "result": review_result},
    }


def build_report(
    *,
    scan: ScanResult,
    binary: Binary,
    data_origin: str,
    source_id: str | None,
    scenario: Scenario | None,
    rules: list[Path],
    events_path: Path | None,
    event_schema: Path | None = None,
    generation: dict | None = None,
) -> dict:
    assert data_origin in DATA_ORIGINS, data_origin
    scan_summary = summarize_scan(scan)
    seen = observed(scan)
    return {
        "format": FORMAT,
        "data_origin": data_origin,
        "source_id": source_id,
        "scenario": None if scenario is None else {
            "id": scenario.id,
            "sha256": scenario.sha256,
            "disposition": scenario.data["disposition"],
            "review_expectation": scenario.data["review"]["expectation"],
            "expected_facts": scenario.data["expected_facts"],
            "visibility_limitations": scenario.data["visibility_limitations"],
        },
        "generation": generation,
        "telltale": binary.describe(),
        "rules": [{"name": r.name, "sha256": sha256_file(r)} for r in rules],
        "scan": scan_summary,
        "event_validation": validate_events(scan.events, event_schema),
        "observed": seen,
        "evaluation": evaluate(scenario, scan_summary, seen),
        "privacy": privacy_check(scan, events_path, scenario),
    }


def render_text(report: dict) -> str:
    """Short human summary. Contains no transcript content or paths."""
    lines = []
    sc = report.get("scenario")
    lines.append(f"scenario: {sc['id'] if sc else '(none)'}  origin: {report['data_origin']}  source: {report['source_id']}")
    tt = report["telltale"]
    lines.append(f"telltale: {tt['version']} ({tt['revision']})")
    scan = report["scan"]
    lines.append(
        f"acquisition: exit={scan['returncode']} parsed={scan['parse_success_source_count']} "
        f"errors={scan['parse_error_source_count']} visibility_limited={scan['visibility_limited_source_count']}"
    )
    for failure in scan["failures"]:
        lines.append(f"  failure: {failure.get('acquisition_code') or failure}")
    lines.append(f"observed rule ids: {', '.join(report['observed']['rule_ids']) or '(none)'}")
    ev = report["evaluation"]
    if ev["status"] != "unlabeled":
        lines.append(f"evaluation: {ev['status']}" + (f" ({ev['reason']})" if ev.get("reason") else ""))
        lines.append(f"  must_match matched={ev['must_match']['matched']} missing={ev['must_match']['missing']}")
        lines.append(f"  must_not_match violations={ev['must_not_match']['violations']}")
        lines.append(f"  review: expected={ev['review']['expected']} -> {ev['review']['result']}")
    if sc and sc["visibility_limitations"]:
        lines.append("known visibility limits:")
        lines.extend(f"  - {item}" for item in sc["visibility_limitations"])
    pv = report["privacy"]
    lines.append(f"privacy: {pv['markers_checked']} synthetic markers checked, leaked={pv['leaked_marker_ids'] or 'none'}")
    val = report["event_validation"]
    lines.append(f"events: {val['event_count']} structural_problems={len(val['structural_problems'])} json_schema={val['json_schema']}")
    return "\n".join(lines)
