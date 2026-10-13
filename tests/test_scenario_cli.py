"""Public CLI checks for synthetic scenario admission and generation."""

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


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as config_dir:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["TELLTALE_LAB_CONFIG"] = str(Path(config_dir) / "config.json")
        return subprocess.run(
            [sys.executable, "-m", "evidence_lab", *args],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )


class ScenarioCliTests(unittest.TestCase):
    def test_malformed_first_step_is_a_validation_error(self) -> None:
        scenario = json.loads(BASELINE.read_text(encoding="utf-8"))
        scenario["steps"] = [42]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "malformed.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            result = cli("scenarios", str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn("steps[0] must be an object", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_secret_is_a_validation_error(self) -> None:
        scenario = json.loads(BASELINE.read_text(encoding="utf-8"))
        scenario["synthetic_resources"]["secrets"] = [{"id": "sample", "value": 42}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "malformed.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            result = cli("scenarios", str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn("secret value must be a string", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_generate_writes_both_source_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "generated"
            result = cli("generate", str(BASELINE), "--format", "all", "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            codex = list((out / "codex.sessions").rglob("*.jsonl"))
            self.assertEqual(len(codex), 1)
            self.assertIn("pnpm install", codex[0].read_text(encoding="utf-8"))
            db = out / "opencode.sqlite" / "opencode" / "opencode.db"
            self.assertTrue(db.is_file())
            connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                self.assertGreater(connection.execute("SELECT count(*) FROM part").fetchone()[0], 0)
            finally:
                connection.close()

    @unittest.skipUnless(os.environ.get("TELLTALE_BIN"), "set TELLTALE_BIN for CLI integration")
    def test_analyze_baseline_in_both_formats(self) -> None:
        binary = os.environ["TELLTALE_BIN"]
        with tempfile.TemporaryDirectory() as tmp:
            for source_id in ("codex.sessions", "opencode.sqlite"):
                with self.subTest(source_id=source_id):
                    out = Path(tmp) / source_id
                    result = cli("--telltale", binary, "analyze", "--scenario", str(BASELINE),
                                 "--format", source_id, "--out", str(out))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["evaluation"]["status"], "clean")
                    self.assertGreater(report["scan"]["parse_success_source_count"], 0)
                    self.assertEqual(report["privacy"]["leaked_marker_ids"], [])


if __name__ == "__main__":
    unittest.main()
