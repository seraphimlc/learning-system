import importlib.util
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QuestionBankV12PromptPolicyTest(unittest.TestCase):
    def test_item_reviewer_defines_process_evidence_flag_as_surface_capability(self):
        prompt = (
            PROJECT_ROOT
            / "learning_system/prompts/math_question_bank_v12_reviewer_batch.v4.md"
        ).read_text(encoding="utf-8")

        self.assertIn("All v12 items require reviewable reasoning evidence", prompt)
        self.assertIn("not a classifier for unprompted-process slots", prompt)
        self.assertIn("must be true for any approved item", prompt)

    def test_runtime_replaces_conflicting_repair_text_for_unprompted_process_slots(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-BRIDGE-MOTION-CHASE")
        raw = [{
            "slot": 14,
            "slots": [14],
            "reason": "reviewer_evidence_gate_failed",
            "semantic_evidence_errors": [
                "semantic_evidence.process_target_disclosed:must_be_false_for_unprompted",
            ],
            "repair_instructions": ["在题面明确要求写出关键关系和完整步骤。"],
        }]

        normalized = module._normalize_unprompted_process_repair_instructions(
            node=node,
            requested_slots=[14],
            repair_instructions=raw,
        )

        self.assertEqual("runtime_unprompted_process_integrity_repair", normalized[0]["reason"])
        joined = " ".join(normalized[0]["repair_instructions"])
        self.assertIn("keep the child-visible prompt natural and unprompted", joined)
        self.assertIn("generic process checklist", joined)
        self.assertIn("explain_a_relationship", joined)
        self.assertNotIn("明确要求写出关键关系", joined)
        self.assertEqual(
            ["在题面明确要求写出关键关系和完整步骤。"],
            normalized[0]["latest_source_repair_requirement"]["repair_instructions"],
        )
        self.assertIn("ignore any source request", normalized[0]["repair_precedence"])

    def test_runtime_collapses_repeated_conflicting_repairs_and_bounds_as_evidence_repair(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_repair_episode",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-BRIDGE-MOTION-CHASE")
        raw = [{
            "slot": 14,
            "slots": [14],
            "reason": "v12_node_set_semantic_review",
            "repair_scope": "global_process_disclosure",
            "repair_instructions": ["不要直接披露过程。"],
        }]
        raw.extend({
            "slot": 14,
            "slots": [14],
            "reason": "reviewer_evidence_gate_failed",
            "semantic_evidence_errors": [
                "semantic_evidence.unprompted_process_evidence:verdict_not_satisfied",
            ],
            "repair_instructions": ["明确要求孩子写出关键步骤。"],
        } for _ in range(5))

        self.assertEqual("evidence_contract_repair", module._pipeline_stage_for_slot_chunk(raw))
        normalized = module._normalize_unprompted_process_repair_instructions(
            node=node,
            requested_slots=[14],
            repair_instructions=raw,
        )

        self.assertEqual(1, len(normalized))
        self.assertEqual(["reviewer_evidence_gate_failed", "v12_node_set_semantic_review"], normalized[0]["replaced_source_reasons"])
        self.assertNotIn("明确要求孩子", " ".join(normalized[0]["repair_instructions"]))

    def test_runtime_protects_marker_driven_slot_on_non_process_node(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_non_process",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-PRE-UNIT-CONVERSION")
        self.assertFalse(module.question_bank.v12_is_process_node(node))
        raw = [{
            "slot": 9,
            "slots": [9],
            "reason": "v12_node_set_semantic_review",
            "repair_scope": "global_process_disclosure",
            "repair_instructions": ["在题面要求孩子逐步说明单位转换过程。"],
        }]

        normalized = module._normalize_unprompted_process_repair_instructions(
            node=node,
            requested_slots=[9],
            repair_instructions=raw,
        )

        self.assertEqual("runtime_unprompted_process_integrity_repair", normalized[0]["reason"])
        self.assertTrue(normalized[0]["runtime_replaced_conflicting_repair_text"])
        self.assertNotIn("逐步说明", " ".join(normalized[0]["repair_instructions"]))

    def test_force_slot_resets_only_target_state_and_preserves_unprompted_policy(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_force_slot",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-BRIDGE-MOTION-CHASE")
        accepted = {
            13: {"id": "Q13", "slot": 13},
            14: {
                "id": "Q14",
                "slot": 14,
                "elicitation_mode": "unprompted_process_evidence",
                "review_artifact": {"verdict": "approved"},
            },
        }
        pending = {14: [{
            "slot": 14,
            "slots": [14],
            "reason": "reviewer_evidence_gate_failed",
            "semantic_evidence_errors": [
                "semantic_evidence.unprompted_process_evidence:verdict_not_satisfied",
            ],
            "repair_instructions": ["明确要求写出步骤。"],
        }]}
        slot_rounds = {13: 2, 14: 3}
        counters = {
            "local_item_rounds_by_slot": {"13": 2, "14": 3},
            "node_set_review_round": 2,
            "node_set_repair_rounds_by_slot": {"14": 2},
            "cross_node_repair_rounds_by_slot": {"14": 1},
            "evidence_contract_repair_rounds_by_slot": {"14": 3},
        }

        events = module._apply_forced_slot_regeneration(
            node=node,
            graph_version="graph-v1",
            force_slots={14},
            accepted_by_slot=accepted,
            pending_repair_by_slot=pending,
            slot_rounds=slot_rounds,
            stage_counters=counters,
            repair_chain_events=[],
        )

        self.assertIn(13, accepted)
        self.assertNotIn(14, accepted)
        self.assertEqual(2, slot_rounds[13])
        self.assertEqual(0, slot_rounds[14])
        self.assertEqual(0, counters["evidence_contract_repair_rounds_by_slot"]["14"])
        self.assertEqual(0, counters["node_set_review_round"])
        self.assertEqual(1, len(pending[14]))
        self.assertEqual("unprompted_process_evidence", pending[14][0]["elicitation_mode"])
        self.assertEqual("operator_force_slot_regeneration", events[-1]["reason"])

    def test_force_slot_cli_parser_is_exact_and_deduplicated(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_force_slot_parser",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertEqual(
            {"M-G7-NUMBER-LINE": {5, 20}},
            module._parse_force_slot_specs([
                "M-G7-NUMBER-LINE:5",
                "M-G7-NUMBER-LINE:20",
                "M-G7-NUMBER-LINE:5",
            ]),
        )
        with self.assertRaises(SystemExit):
            module._parse_force_slot_specs(["M-G7-NUMBER-LINE:0"])
        with self.assertRaises(SystemExit):
            module._parse_force_slot_specs(["missing-slot"])

    def test_force_slot_mode_overrides_stale_unprompted_marker_for_concept_node(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_force_slot_mode",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-G7-NUMBER-LINE")
        self.assertFalse(module.question_bank.v12_is_process_node(node))
        raw = [{
            "slot": 20,
            "slots": [20],
            "reason": "reviewer_evidence_gate_failed",
            "elicitation_mode": "unprompted_process_evidence",
            "repair_instructions": ["Keep the task entirely unprompted."],
        }]

        normalized = module._normalize_unprompted_process_repair_instructions(
            node=node,
            requested_slots=[20],
            repair_instructions=raw,
            elicitation_mode_overrides={20: "standard"},
        )

        self.assertEqual(1, len(normalized))
        self.assertEqual("runtime_elicitation_mode_override", normalized[0]["reason"])
        self.assertEqual("standard", normalized[0]["elicitation_mode"])
        self.assertNotIn("entirely unprompted", " ".join(normalized[0]["repair_instructions"]))

    def test_force_slot_mode_parser_is_exact_and_rejects_conflicts(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_force_slot_mode_parser",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertEqual(
            {"M-G7-NUMBER-LINE": {20: "standard"}},
            module._parse_force_slot_mode_specs([
                "M-G7-NUMBER-LINE:20=standard",
                "M-G7-NUMBER-LINE:20=standard",
            ]),
        )
        with self.assertRaises(SystemExit):
            module._parse_force_slot_mode_specs(["M-G7-NUMBER-LINE:20=unknown"])
        with self.assertRaises(SystemExit):
            module._parse_force_slot_mode_specs([
                "M-G7-NUMBER-LINE:20=standard",
                "M-G7-NUMBER-LINE:20=unprompted_process_evidence",
            ])

        self.assertEqual(
            {"M-G7-NUMBER-LINE": {20: "number-line-slot20-standard-op1"}},
            module._parse_force_slot_operation_specs([
                "M-G7-NUMBER-LINE:20=number-line-slot20-standard-op1",
            ]),
        )
        with self.assertRaises(SystemExit):
            module._parse_force_slot_operation_specs([
                "M-G7-NUMBER-LINE:20=short",
            ])

    def test_force_node_review_preserves_items_and_resets_only_review_stage(self):
        spec = importlib.util.spec_from_file_location(
            "build_math_question_bank_v12_prompt_policy_force_review",
            PROJECT_ROOT / "scripts/build_math_question_bank_v12.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        graph = json.loads((
            PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
        ).read_text(encoding="utf-8"))
        node = next(item for item in graph["nodes"] if item["id"] == "M-G7-EQ-DENOM")
        accepted = {
            slot: {"id": f"Q{slot}", "slot": slot}
            for slot in range(1, 21)
        }
        counters = {
            "local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)},
            "node_set_review_round": 3,
            "node_set_repair_rounds_by_slot": {},
            "cross_node_repair_rounds_by_slot": {},
            "evidence_contract_repair_rounds_by_slot": {},
        }

        events = module._apply_forced_node_review(
            node=node,
            graph_version="graph-v1",
            accepted_by_slot=accepted,
            stage_counters=counters,
            repair_chain_events=[],
            source_review_artifact={"verdict": "approved", "model_name": "gpt-5.4"},
        )

        self.assertEqual(20, len(accepted))
        self.assertEqual(0, counters["node_set_review_round"])
        self.assertEqual("operator_force_node_review", events[-1]["reason"])
        self.assertEqual(0, events[-1]["slot"])
        self.assertTrue(events[-1]["source_review_artifact_sha256"])


if __name__ == "__main__":
    unittest.main()
