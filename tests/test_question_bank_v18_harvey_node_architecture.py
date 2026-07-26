from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from learning_system.admin.expert_ideation import build_expert_design_ideas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = PROJECT_ROOT / "data/question_banks/v18/question_type_taxonomy_v18.json"
BLUEPRINT_PATH = PROJECT_ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"


EXPECTED_FAMILIES = {
    "M-PRE-NUMBER-SENSE": {
        "number_sense_range_benchmark",
        "number_sense_bias_direction",
        "number_sense_magnitude_reasonableness",
        "number_sense_strategy_selection",
    },
    "M-G7-NUMBER-LINE": {
        "number_line_reference_frame",
        "number_line_coordinate_location",
        "number_line_distance_relation",
        "number_line_local_scale_construction",
    },
    "M-G7-EQUALITY-PROP": {
        "equality_add_subtract_invariance",
        "equality_multiply_divide_invariance",
        "equality_illegal_operation_counterexample",
        "equality_operation_reconstruction",
    },
}


class HarveyNodeQuestionArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        blueprints = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
        cls.families = {
            family["family_id"]: family
            for cluster in taxonomy["clusters"]
            for family in cluster["families"]
        }
        cls.blueprints = {
            blueprint["node_id"]: blueprint
            for blueprint in blueprints["blueprints"]
        }

    def test_three_nodes_use_only_direct_node_families(self) -> None:
        polluted = {
            "number_line_position_distance",
            "opposite_absolute_value_model",
            "estimate_direction_and_magnitude",
            "equation_concept_boundary",
            "equation_word_modeling",
            "linear_equation_solving_flow",
            "wrong_solution_repair_number",
            "solution_trace_repair",
            "answer_check_habit",
        }
        for node_id, expected in EXPECTED_FAMILIES.items():
            blueprint = self.blueprints[node_id]
            actual = {entry["family_id"] for entry in blueprint["family_plan"]}
            self.assertEqual(expected, actual, node_id)
            self.assertFalse(actual & polluted, node_id)
            self.assertEqual({"min": 10, "target": 12, "max": 14}, blueprint["candidate_budget"])

    def test_family_plans_encode_depth_evidence_misconceptions_and_stretch_boundary(self) -> None:
        required_keys = {
            "question_direction",
            "depth_rationale",
            "difficulty_distribution",
            "observable_evidence",
            "typical_misconceptions",
            "stretch_boundary",
            "support_only",
            "not_for_activation",
            "exclude_from_coverage",
            "secondary_nodes",
        }
        for node_id in EXPECTED_FAMILIES:
            blueprint = self.blueprints[node_id]
            total = Counter()
            for entry in blueprint["family_plan"]:
                self.assertTrue(required_keys <= set(entry), f"{node_id}/{entry['family_id']}")
                distribution = entry["difficulty_distribution"]
                self.assertEqual(entry["target_count"], sum(distribution.values()))
                self.assertEqual(set(distribution), {"L2", "L3", "L4"})
                self.assertGreaterEqual(len(entry["observable_evidence"]), 3)
                self.assertGreaterEqual(len(entry["typical_misconceptions"]), 3)
                self.assertFalse(entry["support_only"])
                self.assertFalse(entry["not_for_activation"])
                self.assertFalse(entry["exclude_from_coverage"])
                self.assertEqual([], entry["secondary_nodes"])
                total.update(distribution)
            self.assertEqual(12, sum(total.values()), node_id)
            self.assertGreaterEqual(total["L2"], 2, node_id)
            self.assertGreaterEqual(total["L3"], 6, node_id)
            self.assertGreaterEqual(total["L4"], 3, node_id)

    def test_mastery_evidence_matches_each_node_essence(self) -> None:
        number_sense = json.dumps(
            self.blueprints["M-PRE-NUMBER-SENSE"]["family_plan"], ensure_ascii=False
        )
        for marker in ["估算基准", "结果范围", "偏差方向", "数量级", "合理", "策略选择"]:
            self.assertIn(marker, number_sense)

        number_line = json.dumps(
            self.blueprints["M-G7-NUMBER-LINE"]["family_plan"], ensure_ascii=False
        )
        for marker in ["原点", "正方向", "单位长度", "位置", "距离", "局部"]:
            self.assertIn(marker, number_line)

        equality = json.dumps(
            self.blueprints["M-G7-EQUALITY-PROP"]["family_plan"], ensure_ascii=False
        )
        for marker in ["两边", "同一个量", "等式保持", "非零", "非法操作", "反例"]:
            self.assertIn(marker, equality)

    def test_support_families_are_machine_readable_and_fail_closed(self) -> None:
        for family_id in ["solution_trace_repair", "answer_check_habit"]:
            family = self.families[family_id]
            self.assertTrue(family["support_only"])
            self.assertTrue(family["not_for_activation"])
            self.assertTrue(family["exclude_from_coverage"])
            self.assertEqual([], family["secondary_nodes"])

        report = build_expert_design_ideas(
            root=PROJECT_ROOT,
            node_id="M-PRE-INTEGER-OPS",
            version="v18-sample",
        )
        support_requirements = [
            requirement
            for requirement in report["question_requirements"]
            if requirement["support_only"]
        ]
        self.assertTrue(support_requirements)
        for requirement in support_requirements:
            self.assertEqual("support_only", requirement["coverage_role"])
            self.assertTrue(requirement["not_for_activation"])
            self.assertTrue(requirement["exclude_from_coverage"])
            self.assertEqual([], requirement["secondary_nodes"])

    def test_ideation_slots_follow_declared_difficulty_distribution(self) -> None:
        for node_id in EXPECTED_FAMILIES:
            report = build_expert_design_ideas(
                root=PROJECT_ROOT,
                node_id=node_id,
                version="v18-sample",
            )
            self.assertEqual(12, report["requirement_count"], node_id)
            expected = {
                entry["family_id"]: Counter(entry["difficulty_distribution"])
                for entry in self.blueprints[node_id]["family_plan"]
            }
            actual: dict[str, Counter[str]] = {
                family_id: Counter() for family_id in expected
            }
            for requirement in report["question_requirements"]:
                actual[requirement["family_id"]][requirement["difficulty"]] += 1
                self.assertFalse(requirement["support_only"])
                self.assertFalse(requirement["not_for_activation"])
                self.assertFalse(requirement["exclude_from_coverage"])
                self.assertEqual([], requirement["secondary_nodes"])
            self.assertEqual(expected, actual, node_id)

    def test_target_misconceptions_are_not_treated_as_forbidden_content(self) -> None:
        for node_id in EXPECTED_FAMILIES:
            report = build_expert_design_ideas(
                root=PROJECT_ROOT,
                node_id=node_id,
                version="v18-sample",
            )
            for requirement in report["question_requirements"]:
                misconceptions = set(requirement["target_misconceptions"])
                forbidden = set(requirement["must_not_include"])
                self.assertTrue(misconceptions, requirement["slot_id"])
                self.assertFalse(misconceptions & forbidden, requirement["slot_id"])


if __name__ == "__main__":
    unittest.main()
