"""Generator profiles: `upstream` writes what current harness releases persist."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scenarios" / "baseline.routine_read_and_install.json"
# Failed, denied and unsettled tool calls.
OUTCOMES = (ROOT / "scenarios" / "edge.failed_and_missing_outcome.json",
            ROOT / "scenarios" / "adversarial.persistence_denied.json")
sys.path.insert(0, str(ROOT / "src"))

from evidence_lab.native import opencode  # noqa: E402


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as config_dir:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["TELLTALE_LAB_CONFIG"] = str(Path(config_dir) / "config.json")
        return subprocess.run(
            [sys.executable, "-m", "evidence_lab", *args],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )


def generate(out: Path, source_id: str, scenario: Path = BASELINE) -> None:
    result = cli("generate", str(scenario), "--format", source_id, "--profile", "upstream", "--out", str(out))
    if result.returncode:
        raise AssertionError(result.stderr)


class UpstreamProfileTests(unittest.TestCase):
    def test_codex_upstream_shape_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            texts = []
            for run in ("a", "b"):
                generate(Path(tmp) / run, "codex.sessions")
                texts.append(next((Path(tmp) / run).rglob("*.jsonl")).read_text(encoding="utf-8"))
        self.assertEqual(texts[0], texts[1])
        types = [json.loads(line)["type"] for line in texts[0].splitlines()]
        self.assertIn("token_usage_record", types)
        self.assertIn('"name":"exec_command"', texts[0])
        self.assertNotIn("bash", texts[0])

    def test_opencode_upstream_uses_v2_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dumps = []
            for run in ("a", "b"):
                generate(Path(tmp) / run, "opencode.sqlite")
                db = Path(tmp) / run / "opencode" / "opencode.db"
                connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    models = [r[0] for r in connection.execute("SELECT model FROM session_v2")]
                finally:
                    connection.close()
                dumps.append(opencode.logical_dump(db))
        self.assertEqual(dumps[0], dumps[1])
        self.assertTrue({"session_v2", "session_message"} <= tables)
        self.assertFalse({"message", "part"} & tables)
        # Upstream declares `model` as a JSON-mode text column, not a bare model name.
        self.assertEqual([json.loads(model) for model in models],
                         [{"id": "synthetic-model", "providerID": "synthetic-provider"}])

    def test_opencode_upstream_tool_errors_are_structured(self) -> None:
        errors, statuses = [], set()
        with tempfile.TemporaryDirectory() as tmp:
            for scenario in OUTCOMES:
                out = Path(tmp) / scenario.stem
                generate(out, "opencode.sqlite", scenario)
                connection = sqlite3.connect(f"file:{out / 'opencode' / 'opencode.db'}?mode=ro", uri=True)
                try:
                    rows = connection.execute("SELECT data FROM session_message WHERE type = 'assistant'").fetchall()
                finally:
                    connection.close()
                for (data,) in rows:
                    for entry in json.loads(data)["content"]:
                        if entry["type"] == "tool":
                            statuses.add(entry["state"]["status"])
                            if entry["state"]["status"] == "error":
                                errors.append(entry["state"]["error"])
        self.assertEqual(statuses, {"error", "running"})
        # Upstream's tool error is a SessionError object; a bare string is not.
        self.assertEqual(sorted(error["type"] for error in errors), ["permission.rejected", "tool.execution"])
        self.assertTrue(all(isinstance(error["message"], str) and error["message"] for error in errors))

    @unittest.skipUnless(os.environ.get("TELLTALE_BIN"), "set TELLTALE_BIN for CLI integration")
    def test_telltale_reads_upstream_shapes(self) -> None:
        # At the tested revision Telltale acquires both upstream shapes; compatibility
        # findings F1 (Codex token_usage_record) and F9 (OpenCode v2 schema) were
        # recorded against 2e8c56a. A regression here is a finding to record, not a
        # label to change.
        cases = [(scenario, source_id) for scenario in (BASELINE, *OUTCOMES)
                 for source_id in ("codex.sessions", "opencode.sqlite")]
        with tempfile.TemporaryDirectory() as tmp:
            for scenario, source_id in cases:
                with self.subTest(scenario=scenario.stem, source_id=source_id):
                    out = Path(tmp) / scenario.stem / source_id
                    result = cli("--telltale", os.environ["TELLTALE_BIN"], "analyze", "--scenario", str(scenario),
                                 "--format", source_id, "--profile", "upstream", "--out", str(out))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["generation"]["profile"], "upstream")
                    self.assertNotEqual(report["evaluation"]["status"], "not_evaluable", report["evaluation"])
                    self.assertEqual(report["scan"]["failures"], [])
                    self.assertGreater(report["scan"]["record_kind_counts"]["tool_call"], 0)


if __name__ == "__main__":
    unittest.main()
