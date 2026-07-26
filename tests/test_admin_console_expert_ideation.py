from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from learning_system.admin.expert_ideation import build_expert_design_ideas, write_expert_design_ideas


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleExpertIdeationTests(unittest.TestCase):
    def test_empty_node_gets_expert_design_ideas_for_planned_families(self) -> None:
        report = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", version="v18-sample")

        self.assertEqual("2026-07-23.codex-admin.expert-design-ideas.v1", report["schema_version"])
        self.assertEqual("M-G7-NUMBER-LINE", report["node_id"])
        self.assertEqual(0, report["current_item_count"])
        self.assertIn("number_line_reference_frame", report["missing_or_underfilled_families"])
        self.assertGreaterEqual(report["idea_count"], 5)
        self.assertEqual("does_not_authorize_activation", report["activation_implication"])
        first = report["profile_contributions"]["frontline_math_teacher"]["suggestions"][0]
        self.assertIn("三个基本要素", first["core_scenario"])
        self.assertIn("原点", first["evidence_goal"])
        for profile_id in [
            "frontline_math_teacher",
            "bridge_diagnosis_teacher",
            "stretch_competition_teacher",
            "assessment_expert",
            "source_compliance_reviewer",
        ]:
            self.assertIn(profile_id, report["profile_contributions"])
            self.assertTrue(report["profile_contributions"][profile_id]["suggestions"])

    def test_partially_covered_node_only_proposes_underfilled_families(self) -> None:
        report = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-PRE-DECIMAL-OPS", version="v18-sample")

        self.assertEqual(6, report["current_item_count"])
        self.assertIn("estimate_direction_and_magnitude", report["missing_or_underfilled_families"])
        self.assertIn("wrong_solution_repair_number", report["missing_or_underfilled_families"])

    def test_design_ideas_receipt_can_be_written(self) -> None:
        report = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", version="v18-sample")
        with tempfile.TemporaryDirectory() as tmp:
            result = write_expert_design_ideas(report, root=Path(tmp), apply=True)
            self.assertTrue((Path(tmp) / result["design_markdown_path"]).exists())
            self.assertTrue((Path(tmp) / result["design_json_path"]).exists())

    def test_v18_design_ideas_use_staged_bank(self) -> None:
        staged_path = PROJECT_ROOT / "data/question_banks/v18/staged_candidates_v18.json"
        staged = json.loads(staged_path.read_text(encoding="utf-8"))
        staged_node_count = sum(1 for item in staged["items"] if item.get("node_id") == "M-G7-NUMBER-LINE")

        report = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", version="v18")

        self.assertEqual(staged["question_bank_version"], report["question_bank_version"])
        self.assertEqual(staged["status"], report["question_bank_status"])
        self.assertEqual(staged_node_count, report["current_item_count"])
        self.assertEqual(0, report["current_item_count"])
        self.assertIn("number_line_reference_frame", report["missing_or_underfilled_families"])


if __name__ == "__main__":
    unittest.main()
