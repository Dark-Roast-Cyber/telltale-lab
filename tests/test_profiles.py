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


def generate(out: Path, source_id: str) -> None:
    result = cli("generate", str(BASELINE), "--format", source_id, "--profile", "upstream", "--out", str(out))
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
                finally:
                    connection.close()
                dumps.append(opencode.logical_dump(db))
        self.assertEqual(dumps[0], dumps[1])
        self.assertTrue({"session_v2", "session_message"} <= tables)
        self.assertFalse({"message", "part"} & tables)

    @unittest.skipUnless(os.environ.get("TELLTALE_BIN"), "set TELLTALE_BIN for CLI integration")
    def test_telltale_cannot_read_upstream_shapes(self) -> None:
        # Characterizes compatibility findings F1 (Codex token_usage_record) and
        # F9 (OpenCode v2 schema) at Telltale 2e8c56a. If this fails, Telltale
        # may now read these shapes: update docs/harnesses/compatibility-findings.md
        # and this test rather than relabeling anything.
        expected = {"codex.sessions": "acquisition_failed", "opencode.sqlite": "no_records_acquired"}
        with tempfile.TemporaryDirectory() as tmp:
            for source_id, reason in expected.items():
                with self.subTest(source_id=source_id):
                    out = Path(tmp) / source_id
                    result = cli("--telltale", os.environ["TELLTALE_BIN"], "analyze", "--scenario", str(BASELINE),
                                 "--format", source_id, "--profile", "upstream", "--out", str(out))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["generation"]["profile"], "upstream")
                    self.assertEqual(report["evaluation"]["status"], "not_evaluable")
                    self.assertEqual(report["evaluation"]["reason"], reason)


if __name__ == "__main__":
    unittest.main()
