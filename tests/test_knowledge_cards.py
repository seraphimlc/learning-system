from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import urllib.request
from pathlib import Path

from learning_system import daily_runtime, db, knowledge_cards, server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCardsTest(unittest.TestCase):
    def _assert_no_forbidden_keys(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                self.assertNotIn(str(key), knowledge_cards.CHILD_FORBIDDEN_KEYS)
                self._assert_no_forbidden_keys(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_forbidden_keys(item)

    def test_number_line_card_validates_as_active_card(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)

        card = service.load_active_card("M-G7-NUMBER-LINE")

        self.assertEqual("M-G7-NUMBER-LINE", card.node_id)
        self.assertEqual("2026-07-20.number-line.v1", card.card_version)
        self.assertEqual(64, len(card.digest()))
        sections = card.teaching_sections()
        self.assertEqual(
            {"essence", "core_model", "worked_example", "next_micro_check"},
            set(sections),
        )
        self.assertIn("向右", json.dumps(sections, ensure_ascii=False))
        self.assertIn("向左", json.dumps(sections, ensure_ascii=False))

    def test_knowledge_card_coverage_report_tracks_graph_wide_gap(self):
        report = knowledge_cards.knowledge_card_coverage_report(PROJECT_ROOT)

        self.assertEqual("knowledge-card-coverage.v1", report["schema_version"])
        self.assertEqual(56, report["total_graph_nodes"])
        self.assertEqual(1, report["active_card_count"])
        self.assertEqual(55, report["missing_card_count"])
        self.assertEqual(0, report["invalid_card_count"])
        self.assertEqual(0, report["orphan_active_count"])
        self.assertEqual(["M-G7-NUMBER-LINE"], [item["node_id"] for item in report["active_cards"]])
        missing_ids = {item["node_id"] for item in report["missing_cards"]}
        self.assertIn("M-PRE-DECIMAL-OPS", missing_ids)
        rational_module = next(
            item for item in report["modules"]
            if item["module_id"] == "E_RATIONAL_NUMBERS"
        )
        self.assertGreater(rational_module["total_nodes"], rational_module["active_cards"])

    def test_child_projection_excludes_internal_teaching_data(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)

        projection = service.child_projection_for_node("M-G7-NUMBER-LINE")

        self.assertEqual("knowledge-card-child.v1", projection["schema_version"])
        self.assertEqual("数轴", projection["title"])
        self.assertIn("components", projection)
        self._assert_no_forbidden_keys(projection)
        component_types = {component["type"] for component in projection["components"]}
        self.assertIn("number_line_visual", component_types)
        self.assertIn("micro_check", component_types)

    def test_runtime_packet_keeps_internal_layer_separate_from_child_layer(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)

        packet = service.runtime_packet_for_node("M-G7-NUMBER-LINE")

        self.assertIsNotNone(packet)
        assert packet is not None
        self.assertEqual("knowledge-card-runtime.v1", packet["schema_version"])
        self.assertEqual("M-G7-NUMBER-LINE", packet["node_id"])
        self.assertIn("internal_card", packet)
        self.assertIn("graph_binding", packet)
        self.assertIn("child_card_summary", packet)
        self.assertNotIn("internal_card", packet["child_card_summary"])
        self.assertIn("direction_reversal", json.dumps(packet["internal_card"], ensure_ascii=False))

    def test_teaching_step_projection_can_render_child_safe_knowledge_card_components(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
        packet = service.runtime_packet_for_node("M-G7-NUMBER-LINE")
        assert packet is not None

        dto = daily_runtime.child_teaching_step_dto({
            "step_handle": "step-card-preview",
            "position": 1,
            "step_type": "worked_example",
            "status": "selected",
            "topic_label": "数轴",
            "prompt": "先看数轴学习卡，再做一题小检查。",
            "support": {"hint": "看清 0、方向、单位长度。"},
            "teaching_sections": packet["child_card_summary"]["default_teaching_sections"],
            "knowledge_card_components": packet["child_card_components"],
        })

        self.assertIn("knowledge_card_components", dto)
        component_types = {component["type"] for component in dto["knowledge_card_components"]}
        self.assertIn("number_line_visual", component_types)
        self.assertIn("micro_check", component_types)
        self._assert_no_forbidden_keys(dto)

    def test_daily_runtime_recorded_teaching_uses_knowledge_card_sections(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
        packet = service.runtime_packet_for_node("M-G7-NUMBER-LINE")
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            db.init_schema(conn)
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            output = runtime._default_recorded_teaching_output(
                {},
                {
                    "new_knowledge_request": True,
                    "target_node_id": "M-G7-NUMBER-LINE",
                    "knowledge_card": packet,
                },
            )

        self.assertEqual("worked_example", output["teaching_step_type"])
        self.assertEqual("knowledge_card_recorded_teaching", output["source_reason"])
        self.assertEqual(
            packet["child_card_summary"]["default_teaching_sections"],
            output["teaching_sections"],
        )

    def test_invalid_child_card_internal_leak_is_rejected(self):
        path = PROJECT_ROOT / "data/knowledge_cards/math/M-G7-NUMBER-LINE.v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["child_card"]["internal_card"] = {"teaching_goal": "leak"}

        with self.assertRaises(knowledge_cards.KnowledgeCardError):
            knowledge_cards.validate_knowledge_card(payload, expected_node_id="M-G7-NUMBER-LINE")

    def test_child_card_api_and_preview_page_are_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "cards.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                db.init_schema(conn)
            httpd, base_url = server.start_test_server(db_path)
            try:
                with urllib.request.urlopen(f"{base_url}/api/knowledge-cards/number-line", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual("knowledge-card-child.v1", payload["schema_version"])
                self.assertEqual("数轴", payload["title"])
                self._assert_no_forbidden_keys(payload)

                with urllib.request.urlopen(
                    f"{base_url}/api/knowledge-cards/preview?node_id=M-PRE-NUMBER-SENSE&draft=1",
                    timeout=5,
                ) as response:
                    draft_payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual("knowledge-card-child-draft.v2", draft_payload["schema_version"])
                self.assertEqual("数感与估算", draft_payload["title"])
                self.assertIn("components", draft_payload)
                self._assert_no_forbidden_keys(draft_payload)
                serialized = json.dumps(draft_payload, ensure_ascii=False)
                self.assertNotIn("correct_range", serialized)
                self.assertNotIn('"answer"', serialized)
                self.assertNotIn("target_evidence", serialized)

                with urllib.request.urlopen(f"{base_url}/knowledge-card-preview.html", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("知识卡预览", html)
                self.assertIn("knowledge_card_preview.js", html)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_component_registry_validates_cognitive_object_component_contract(self):
        registry = knowledge_cards.load_component_registry(PROJECT_ROOT)

        self.assertEqual("knowledge-card-component-registry.v1", registry["schema_version"])
        self.assertIn("position_direction_distance", registry["cognitive_objects"])
        self.assertIn("interactive_number_line", registry["component_types"])
        self.assertTrue(registry["component_types"]["interactive_number_line"]["child_action_required"])
        self.assertIn("target_evidence", registry["required_storyboard_fields"])

    def test_number_line_v2_draft_validates_design_brief_storyboard_and_exit_rules(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)

        card = service.load_v2_draft_card("M-G7-NUMBER-LINE")

        self.assertEqual("knowledge-card.v2", card["schema_version"])
        self.assertEqual("position_direction_distance", card["design_brief"]["cognitive_object"])
        self.assertIn("interactive_number_line", card["design_brief"]["best_expression_family"])
        storyboard_types = {component["type"] for component in card["component_storyboard"]}
        self.assertIn("interactive_number_line", storyboard_types)
        self.assertIn("order_points", storyboard_types)
        self.assertLessEqual(card["exit_rules"]["max_same_structure_checks"], 2)
        self._assert_no_forbidden_keys(card["child_card"])

    def test_v2_card_rejects_missing_design_brief(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
        card = service.load_v2_draft_card("M-G7-NUMBER-LINE")
        card.pop("design_brief")

        with self.assertRaises(knowledge_cards.KnowledgeCardError):
            knowledge_cards.validate_knowledge_card_v2(
                card,
                registry=knowledge_cards.load_component_registry(PROJECT_ROOT),
                expected_node_id="M-G7-NUMBER-LINE",
            )

    def test_v2_card_rejects_unknown_component_type(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
        card = service.load_v2_draft_card("M-G7-NUMBER-LINE")
        card["component_storyboard"][1]["type"] = "decorative_fireworks"

        with self.assertRaises(knowledge_cards.KnowledgeCardError):
            knowledge_cards.validate_knowledge_card_v2(
                card,
                registry=knowledge_cards.load_component_registry(PROJECT_ROOT),
                expected_node_id="M-G7-NUMBER-LINE",
            )

    def test_v2_card_rejects_interaction_without_evidence_action(self):
        service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
        card = service.load_v2_draft_card("M-G7-NUMBER-LINE")
        card["component_storyboard"][1]["child_action"] = "continue"

        with self.assertRaises(knowledge_cards.KnowledgeCardError):
            knowledge_cards.validate_knowledge_card_v2(
                card,
                registry=knowledge_cards.load_component_registry(PROJECT_ROOT),
                expected_node_id="M-G7-NUMBER-LINE",
            )


if __name__ == "__main__":
    unittest.main()
