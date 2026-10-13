"""Evaluation statuses come from scenario labels, never from detector output alone."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence_lab import analysis, scenario  # noqa: E402

ACQUIRED = {"returncode": 0, "parse_success_source_count": 1, "parse_error_source_count": 0,
            "visibility_limited_source_count": 0, "record_kind_counts": {"tool_call": 1}}


def narrated_only(must_not_match: list[str]) -> scenario.Scenario:
    data = json.loads((ROOT / "scenarios" / "baseline.routine_read_and_install.json").read_text(encoding="utf-8"))
    data.update(id="test.narrated_only", disposition="unknown",
                review={"expectation": "not_evaluable", "rationale": "Only narration; no tool request."},
                rule_expectations={"must_match": [], "must_not_match": must_not_match})
    return scenario.Scenario(data=scenario.validate(data), path=Path("test.json"), sha256="0" * 64)


class EvaluateTests(unittest.TestCase):
    def test_silence_on_a_not_evaluable_label_is_not_clean(self) -> None:
        seen = {"rule_ids": [], "alerting": False}
        result = analysis.evaluate(narrated_only([]), ACQUIRED, seen)
        self.assertEqual((result["status"], result["reason"]), ("not_evaluable", "labeled_not_evaluable"))

    def test_false_positive_still_wins_over_a_not_evaluable_label(self) -> None:
        seen = {"rule_ids": ["rule.x"], "alerting": True}
        result = analysis.evaluate(narrated_only(["rule.x"]), ACQUIRED, seen)
        self.assertEqual(result["status"], "false_positive")


if __name__ == "__main__":
    unittest.main()
