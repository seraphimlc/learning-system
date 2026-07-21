from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from learning_system import knowledge_card_generation, knowledge_cards


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCardGenerationTest(unittest.TestCase):
    def _number_line_v2_draft(self) -> dict:
        path = PROJECT_ROOT / "data/knowledge_cards/math/M-G7-NUMBER-LINE.v2.draft.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _draft(self, filename: str) -> dict:
        path = PROJECT_ROOT / f"data/knowledge_cards/math/{filename}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_generation_rules_are_machine_readable_and_registry_bound(self):
        rules = knowledge_card_generation.load_generation_rules(PROJECT_ROOT)
        registry = knowledge_cards.load_component_registry(PROJECT_ROOT)

        self.assertEqual("knowledge-card-generation-rules.v1", rules["schema_version"])
        self.assertIn("M-G7-NUMBER-LINE", rules["node_overrides"])
        self.assertLessEqual(
            set(rules["node_overrides"].values()),
            set(registry["cognitive_objects"]),
        )

    def test_generation_packet_reads_graph_node_contracts_and_component_guidance(self):
        packet = knowledge_card_generation.build_generation_packet_for_node(
            "M-PRE-DECIMAL-OPS",
            project_root=PROJECT_ROOT,
        )

        self.assertEqual("knowledge-card-generation-packet.v1", packet["schema_version"])
        self.assertEqual("M-PRE-DECIMAL-OPS", packet["graph_node"]["node_id"])
        self.assertEqual("小数运算", packet["graph_node"]["name"])
        self.assertEqual("estimation_reasonableness", packet["generation_guidance"]["cognitive_object"])
        self.assertEqual("node_override", packet["generation_guidance"]["source"])
        self.assertIn("range_slider_estimate", packet["generation_guidance"]["default_components"])
        prerequisite_names = {item["name"] for item in packet["graph_context"]["prerequisites"]}
        self.assertIn("整数四则计算", prerequisite_names)
        self.assertIn("数感与估算", prerequisite_names)
        self.assertIn("小数点对齐错", packet["teaching_inputs"]["common_mistakes"])
        self.assertEqual(64, len(packet["generation_input_digest_sha256"]))

    def test_generation_batch_plan_uses_coverage_gap_not_full_graph_prompt_dump(self):
        plan = knowledge_card_generation.plan_generation_batch(
            project_root=PROJECT_ROOT,
            limit=4,
        )

        self.assertEqual("knowledge-card-generation-batch-plan.v1", plan["schema_version"])
        self.assertEqual(56, plan["coverage"]["total_graph_nodes"])
        self.assertEqual(1, plan["coverage"]["active_card_count"])
        self.assertEqual(55, plan["coverage"]["missing_card_count"])
        self.assertGreaterEqual(plan["coverage"]["valid_draft_count"], 3)
        self.assertEqual(4, len(plan["items"]))
        planned_ids = {item["node_id"] for item in plan["items"]}
        self.assertNotIn("M-G7-NUMBER-LINE", planned_ids)
        self.assertNotIn("M-BRIDGE-SOLUTION-HABIT", planned_ids)
        self.assertNotIn("M-PRE-DECIMAL-OPS", planned_ids)
        for item in plan["items"]:
            self.assertLessEqual(set(item), {
                "node_id",
                "name",
                "module_id",
                "module_name",
                "cognitive_object",
                "cognitive_object_source",
                "confidence",
                "default_components",
                "generation_input_digest_sha256",
            })
            self.assertEqual(64, len(item["generation_input_digest_sha256"]))

    def test_review_gate_accepts_number_line_draft_with_only_extra_unlock_warning(self):
        report = knowledge_card_generation.review_draft_v2(
            self._number_line_v2_draft(),
            project_root=PROJECT_ROOT,
            expected_node_id="M-G7-NUMBER-LINE",
        )

        self.assertEqual("knowledge-card-draft-review.v1", report["schema_version"])
        self.assertEqual("accepted", report["verdict"])
        self.assertEqual(0, report["blocking_issue_count"])
        self.assertEqual(
            ["extra_unlocks_need_review"],
            [issue["code"] for issue in report["issues"]],
        )

    def test_new_draft_cards_pass_generation_review_gate(self):
        for node_id, filename in [
            ("M-BRIDGE-SOLUTION-HABIT", "M-BRIDGE-SOLUTION-HABIT.v2.draft.json"),
            ("M-PRE-DECIMAL-OPS", "M-PRE-DECIMAL-OPS.v2.draft.json"),
            ("M-PRE-INTEGER-OPS", "M-PRE-INTEGER-OPS.v2.draft.json"),
            ("M-PRE-NUMBER-SENSE", "M-PRE-NUMBER-SENSE.v2.draft.json"),
            ("M-PRE-ORDER-OPS", "M-PRE-ORDER-OPS.v2.draft.json"),
        ]:
            with self.subTest(node_id=node_id):
                report = knowledge_card_generation.review_draft_v2(
                    self._draft(filename),
                    project_root=PROJECT_ROOT,
                    expected_node_id=node_id,
                )

                self.assertEqual("accepted", report["verdict"])
                self.assertEqual(0, report["blocking_issue_count"])

    def test_review_gate_rejects_direct_prerequisite_omission(self):
        draft = self._number_line_v2_draft()
        draft["graph_binding"]["prerequisite_node_ids"] = []

        report = knowledge_card_generation.review_draft_v2(
            draft,
            project_root=PROJECT_ROOT,
            expected_node_id="M-G7-NUMBER-LINE",
        )

        self.assertEqual("needs_fix", report["verdict"])
        self.assertIn("missing_direct_prerequisites", {issue["code"] for issue in report["issues"]})

    def test_review_gate_rejects_non_evidence_template_before_activation(self):
        draft = copy.deepcopy(self._number_line_v2_draft())
        draft["component_storyboard"] = [{
            "component_id": "only-text",
            "type": "text_explanation",
            "purpose": "read_only",
            "child_action": "read",
            "target_evidence": [],
            "misconception_target": [],
            "success_signal": "孩子读完。",
            "fallback_if_failed": "再读一遍。"
        }]
        draft["child_card"]["default_sequence"] = ["only-text"]

        report = knowledge_card_generation.review_draft_v2(
            draft,
            project_root=PROJECT_ROOT,
            expected_node_id="M-G7-NUMBER-LINE",
        )

        self.assertEqual("rejected", report["verdict"])
        self.assertEqual(["schema_invalid"], [issue["code"] for issue in report["issues"]])

    def test_audit_cli_outputs_next_generation_batch(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts/audit_knowledge_card_generation.py"),
                "--limit",
                "2",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            check=True,
            capture_output=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual("knowledge-card-generation-batch-plan.v1", payload["schema_version"])
        self.assertEqual(2, len(payload["items"]))


if __name__ == "__main__":
    unittest.main()
