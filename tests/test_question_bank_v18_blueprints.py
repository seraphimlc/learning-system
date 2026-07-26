from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import validate_question_bank_v18_blueprints, validate_question_bank_v18_sample


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QuestionBankV18BlueprintTests(unittest.TestCase):
    def test_v18_blueprints_cover_graph_and_pass_gate(self) -> None:
        report = validate_question_bank_v18_blueprints.validate()

        self.assertEqual("PASS", report["status"])
        self.assertEqual(56, report["graph_nodes"])
        self.assertEqual(56, report["blueprints"])
        self.assertGreaterEqual(report["taxonomy_families"], 40)
        self.assertEqual(["answer_check_habit", "solution_trace_repair"], report["support_families"])

    def test_v18_blueprints_encode_v17_failure_guards(self) -> None:
        blueprint_path = PROJECT_ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"
        doc = json.loads(blueprint_path.read_text(encoding="utf-8"))
        by_node = {item["node_id"]: item for item in doc["blueprints"]}

        work_rate_rejects = "\n".join(by_node["M-BRIDGE-WORK-RATE"]["review_must_reject"])
        self.assertIn("速度×时间", work_rate_rejects)
        self.assertIn("工作总量=1", work_rate_rejects)

        geo_views_rejects = "\n".join(by_node["M-G7-GEO-VIEWS"]["review_must_reject"])
        self.assertIn("角平分线", geo_views_rejects)
        self.assertIn("展开图", geo_views_rejects)

        area_rejects = "\n".join(by_node["M-PRE-GEO-AREA-VOLUME"]["review_must_reject"])
        self.assertIn("角度题", area_rejects)
        self.assertIn("单位维度", area_rejects)

        rational_rejects = "\n".join(by_node["M-G7-RATIONAL-ADD-SUB"]["review_must_reject"])
        self.assertIn("只比较大小", rational_rejects)
        self.assertIn("加减动作", rational_rejects)

    def test_v18_family_plan_has_node_specific_evidence(self) -> None:
        blueprint_path = PROJECT_ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"
        doc = json.loads(blueprint_path.read_text(encoding="utf-8"))

        for blueprint in doc["blueprints"]:
            real_family_count = 0
            for family in blueprint["family_plan"]:
                self.assertGreaterEqual(len(family["required_evidence"]), 2, blueprint["node_id"])
                joined = "\n".join(family["required_evidence"])
                self.assertNotIn("本题重点是", joined)
                if family["family_id"] not in {"answer_check_habit", "solution_trace_repair"}:
                    real_family_count += 1
            if blueprint["cluster"] == "learning_process":
                self.assertGreaterEqual(real_family_count, 2, blueprint["node_id"])
            else:
                self.assertGreaterEqual(real_family_count, 3, blueprint["node_id"])

    def test_v18_sample_60_passes_draft_quality_gate(self) -> None:
        report = validate_question_bank_v18_sample.validate()

        self.assertEqual("PASS", report["status"])
        self.assertEqual(60, report["items"])
        self.assertEqual(10, report["nodes"])
        self.assertEqual({6}, set(report["by_node"].values()))
        for node_id in [
            "M-G7-RATIONAL-ADD-SUB",
            "M-BRIDGE-WORK-RATE",
            "M-G7-GEO-VIEWS",
            "M-PRE-GEO-AREA-VOLUME",
        ]:
            self.assertIn(node_id, report["by_node"])

    def test_v18_sample_gate_manifest_binds_inputs_and_stays_scope_limited(self) -> None:
        manifest_path = PROJECT_ROOT / "data/question_banks/v18/sample_gate_manifest_v18.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("sample_static_qa_passed_scope_limited", manifest["status"])
        self.assertEqual(60, manifest["sample_item_count"])
        self.assertEqual(60, len(manifest["sample_question_ids"]))
        self.assertIn("child_runtime_activation", manifest["not_authorized_for"])
        for key in [
            "taxonomy",
            "blueprints",
            "sample",
            "blueprint_generator",
            "sample_generator",
            "blueprint_validator",
            "sample_validator",
        ]:
            self.assertRegex(manifest["input_digests"][key]["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
