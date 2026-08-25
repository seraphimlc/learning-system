"""TDD test list and focused tests for question-quality primitives.

Test list:
- canonical UTF-8 JSON uses lexicographic object keys and no extra whitespace
- semantic arrays preserve order while set-like arrays sort after normalization
- NFKC and mathematical-operator normalization are stable
- prompt spans use inclusive/exclusive token offsets and SHA-256 digests
- versioned envelopes reject nulls, unknown keys, duplicate ids, oversized data,
  and invalid enum values
- graph evidence values map only through the explicit catalog
- fixed-answer policy defaults to observation-only/B and respects graph policy
"""

import hashlib
import json
import unittest

from learning_system import question_quality


class CanonicalizationTests(unittest.TestCase):
    def test_canonical_json_is_utf8_sorted_and_preserves_semantic_order(self):
        value = {"z": "中", "semantic": ["second", "first"], "a": 1}

        canonical = question_quality.canonical_json(value)

        self.assertEqual('{"a":1,"semantic":["second","first"],"z":"中"}', canonical)
        self.assertEqual(canonical.encode("utf-8"), question_quality.canonical_json_bytes(value))

    def test_set_array_helper_sorts_only_declared_paths(self):
        value = {
            "semantic": ["b", "a"],
            "evidence_keys": ["转移", "正确"],
        }

        normalized = question_quality.canonicalize_set_arrays(
            value,
            paths={("evidence_keys",)},
        )

        self.assertEqual(["b", "a"], normalized["semantic"])
        self.assertEqual(["正确", "转移"], normalized["evidence_keys"])

    def test_text_normalization_maps_nfkc_and_math_operators(self):
        self.assertEqual(
            "x + y <= 3 / 4",
            question_quality.normalize_text(" ｘ ＋ ｙ ≤ ３ ÷ ４ \r\n"),
        )

    def test_prompt_span_offsets_and_sha256_are_canonical(self):
        prompt = "比较 −3 × 2 和 4。"
        tokens = question_quality.prompt_tokens(prompt)
        span = question_quality.prompt_span(prompt, start_token=1, end_token=4)

        self.assertEqual(["比较", "-3", "*", "2", "和", "4。"], tokens)
        self.assertEqual({"start_token", "end_token", "instance_hash", "structural_hash"}, set(span))
        self.assertEqual(1, span["start_token"])
        self.assertEqual(4, span["end_token"])
        self.assertEqual(64, len(span["instance_hash"]))
        self.assertEqual(span["instance_hash"], question_quality.sha256_hex(
            question_quality.canonical_json_bytes({"tokens": tokens[1:4]})
        ))

    def test_strict_json_parser_rejects_duplicate_object_keys(self):
        with self.assertRaises(ValueError):
            question_quality.loads_strict('{"a": 1, "a": 2}')

    def test_strict_json_parser_rejects_non_finite_constants(self):
        for payload in ('{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    question_quality.loads_strict(payload)

    def test_strict_json_parser_rejects_invalid_utf8_and_surrogates(self):
        for payload in (b'"\xff"', "\ud800", '"\\ud800"'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    question_quality.loads_strict(payload)

    def test_strict_json_parser_converts_recursion_error_to_value_error(self):
        payload = "[" * 2000 + "0" + "]" * 2000
        self.assertLessEqual(len(payload.encode("utf-8")), 16 * 1024)
        with self.assertRaises(ValueError):
            question_quality.loads_strict(payload)

    def test_canonical_json_rejects_non_string_mapping_keys(self):
        with self.assertRaises(ValueError):
            question_quality.canonical_json({1: "not a JSON object key"})


class EnvelopeValidationTests(unittest.TestCase):
    def test_version_constants_are_pinned(self):
        self.assertEqual("review_packet.v1", question_quality.REVIEW_PACKET_SCHEMA_VERSION)
        self.assertEqual("discovery_derivation.v1", question_quality.DISCOVERY_DERIVATION_SCHEMA_VERSION)
        self.assertEqual("question_fingerprint.v2", question_quality.QUESTION_FINGERPRINT_POLICY_VERSION)
        self.assertEqual("2026-08-25.fixed-answer-response.v1", question_quality.FIXED_RESPONSE_SCHEMA_VERSION)
        self.assertEqual("graph_evidence_contract.v1", question_quality.GRAPH_EVIDENCE_CONTRACT_VERSION)

    def test_review_packet_rejects_null_unknown_keys_duplicate_ids_and_oversize(self):
        with self.assertRaises(ValueError):
            question_quality.validate_review_packet(None)

        packet = {
            "schema_version": "review_packet.v1",
            "reviewer_run_id": "run-1",
            "prompt_spans": [],
            "solution_steps": [],
            "cross_node_prerequisite_relations": [],
            "unexpected": True,
        }
        with self.assertRaises(ValueError):
            question_quality.validate_review_packet(packet)

        packet.pop("unexpected")
        packet["prompt_spans"] = [
            {"id": "p1", "start_token": 0, "end_token": 1, "instance_hash": "0" * 64, "structural_hash": "0" * 64},
            {"id": "p1", "start_token": 1, "end_token": 2, "instance_hash": "1" * 64, "structural_hash": "1" * 64},
        ]
        with self.assertRaises(ValueError):
            question_quality.validate_review_packet(packet)

        packet["prompt_spans"] = []
        packet["solution_steps"] = [
            {"id": str(i), "action": "a", "evidence_key": "concept_recognition", "input_step_ids": [], "input_evidence_keys": [], "prompt_span_ids": []}
            for i in range(9)
        ]
        with self.assertRaises(ValueError):
            question_quality.validate_review_packet(packet)

    def test_review_packet_requires_canonical_nonempty_evidence_and_prompt_refs(self):
        base = {
            "schema_version": "review_packet.v1",
            "reviewer_run_id": "run-1",
            "prompt_spans": [
                {
                    "id": "p1",
                    "start_token": 0,
                    "end_token": 1,
                    "instance_hash": "0" * 64,
                    "structural_hash": "0" * 64,
                }
            ],
            "solution_steps": [
                {
                    "id": "s1",
                    "action": "classify_structure",
                    "evidence_key": "concept_recognition",
                    "input_step_ids": [],
                    "input_evidence_keys": ["concept_recognition"],
                    "prompt_span_ids": ["p1"],
                }
            ],
            "cross_node_prerequisite_relations": [],
        }
        question_quality.validate_review_packet(base)
        for field, invalid in (
            ("input_evidence_keys", []),
            ("prompt_span_ids", []),
            ("input_evidence_keys", ["unknown_evidence"]),
            ("evidence_key", "unknown_evidence"),
        ):
            with self.subTest(field=field, invalid=invalid):
                packet = json.loads(json.dumps(base))
                packet["solution_steps"][0][field] = invalid
                with self.assertRaises(ValueError):
                    question_quality.validate_review_packet(packet)

    def test_discovery_output_rejects_invalid_enum_and_unknown_keys(self):
        output = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E9",
            "entry_point_visibility": "implicit",
            "decision_points": [],
            "solution_families": [],
            "execution_steps": 1,
            "key_insight_evidence_keys": [],
        }
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(output)

        output["discovery_depth"] = "E2"
        output["extra"] = "reject"
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(output)

    def test_discovery_output_requires_bounded_decision_and_family_references(self):
        decision = {
            "id": "d1",
            "taxonomy": "classify_structure",
            "alternatives": ["left", "right"],
            "misconception_key": "concept_recognition",
            "step_ids": [],
            "structural_prompt_span_hashes": [],
            "depends_on": [],
        }
        family = {
            "id": "f1",
            "first_action": "classify_structure",
            "step_ids": [],
            "structural_prompt_span_hashes": [],
        }
        base = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E2",
            "entry_point_visibility": "implicit",
            "decision_points": [decision],
            "solution_families": [family],
            "execution_steps": 1,
            "key_insight_evidence_keys": ["concept_recognition"],
        }
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(base)

        decision["step_ids"] = ["s1"]
        decision["structural_prompt_span_hashes"] = ["0" * 64]
        family["step_ids"] = ["s1"]
        family["structural_prompt_span_hashes"] = ["0" * 64]
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(base)
        valid = question_quality.validate_discovery_derivation_output(
            base,
            solution_step_ids={"s1"},
            structural_prompt_span_hashes={"0" * 64},
            solution_step_actions={"s1": "classify_structure"},
        )
        self.assertEqual("E2", valid["discovery_depth"])

        decision["step_ids"] = ["s1"] * 9
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(base)

    def test_discovery_execution_steps_follow_depth_bounds(self):
        decision = {
            "id": "d1",
            "taxonomy": "classify_structure",
            "alternatives": ["left", "right"],
            "misconception_key": "concept_recognition",
            "step_ids": ["s1"],
            "structural_prompt_span_hashes": ["0" * 64],
            "depends_on": [],
        }
        family = {
            "id": "f1",
            "first_action": "classify_structure",
            "step_ids": ["s1"],
            "structural_prompt_span_hashes": ["0" * 64],
        }
        output = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E1",
            "entry_point_visibility": "cued",
            "decision_points": [decision],
            "solution_families": [family],
            "execution_steps": 1,
            "key_insight_evidence_keys": ["concept_recognition"],
        }
        context = {
            "solution_step_ids": {"s1"},
            "structural_prompt_span_hashes": {"0" * 64},
            "solution_step_actions": {"s1": "classify_structure"},
        }
        for depth, minimum, maximum in (("E1", 1, 6), ("E2", 1, 6), ("E3", 2, 6), ("E4", 2, 8)):
            with self.subTest(depth=depth):
                output["discovery_depth"] = depth
                for steps in (minimum, maximum):
                    output["execution_steps"] = steps
                    question_quality.validate_discovery_derivation_output(output, **context)
                for steps in (minimum - 1, maximum + 1):
                    output["execution_steps"] = steps
                    with self.assertRaises(ValueError):
                        question_quality.validate_discovery_derivation_output(output, **context)

        output["discovery_depth"] = "E0"
        output["execution_steps"] = 1
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(output, **context)

    def test_discovery_family_first_action_requires_authoritative_action_match(self):
        output = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E1",
            "entry_point_visibility": "cued",
            "decision_points": [],
            "solution_families": [{
                "id": "f1",
                "first_action": "classify_structure",
                "step_ids": ["s1"],
                "structural_prompt_span_hashes": ["0" * 64],
            }],
            "execution_steps": 1,
            "key_insight_evidence_keys": ["concept_recognition"],
        }
        context = {
            "solution_step_ids": {"s1"},
            "structural_prompt_span_hashes": {"0" * 64},
        }
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(output, **context)
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(
                output,
                **context,
                solution_step_actions={"s1": "select_model"},
            )
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(
                output,
                **context,
                solution_step_actions={"s2": "classify_structure"},
            )
        question_quality.validate_discovery_derivation_output(
            output,
            **context,
            solution_step_actions={"s1": "classify_structure"},
        )

    def test_discovery_e1_to_e4_require_family_and_canonical_key_insight(self):
        output = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E1",
            "entry_point_visibility": "cued",
            "decision_points": [],
            "solution_families": [],
            "execution_steps": 1,
            "key_insight_evidence_keys": [],
        }
        for depth, steps in (("E1", 1), ("E2", 1), ("E3", 2), ("E4", 2)):
            with self.subTest(depth=depth):
                output["discovery_depth"] = depth
                output["execution_steps"] = steps
                with self.assertRaises(ValueError):
                    question_quality.validate_discovery_derivation_output(output)

        output["solution_families"] = [{
            "id": "f1",
            "first_action": "classify_structure",
            "step_ids": ["s1"],
            "structural_prompt_span_hashes": ["0" * 64],
        }]
        output["key_insight_evidence_keys"] = ["unknown_evidence"]
        output["discovery_depth"] = "E1"
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(
                output,
                solution_step_ids={"s1"},
                structural_prompt_span_hashes={"0" * 64},
                solution_step_actions={"s1": "classify_structure"},
            )


class GraphEvidenceTests(unittest.TestCase):
    def test_explicit_graph_evidence_mapping_and_digest(self):
        graph_node = {
            "evidence_required": ["结果正确", "过程可复盘", "能口头解释", "能做一道小变式"],
            "selective_core_evidence_keys": ["answer_correctness", "transfer"],
        }

        contract = question_quality.normalize_graph_evidence_contract(graph_node)

        self.assertEqual(
            {
                "answer_correctness",
                "process_explanation",
                "verbal_explanation",
                "transfer",
            },
            set(contract["evidence_keys"]),
        )
        self.assertEqual(["answer_correctness", "transfer"], contract["selective_core_evidence_keys"])
        self.assertEqual("observation_only", contract["fixed_answer_mastery_policy"])
        self.assertEqual("B", contract["fixed_answer_state_ceiling"])
        self.assertEqual(64, len(contract["canonical_digest_sha256"]))

    def test_unmapped_graph_evidence_fails_closed(self):
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract(
                {"evidence_required": ["结果正确", "某个未配置的证据"]}
            )

    def test_evidence_required_is_authoritative_and_must_agree_with_stable_keys(self):
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract(
                {
                    "evidence_required": ["结果正确", "某个未配置的证据"],
                    "evidence_keys": ["answer_correctness"],
                }
            )
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract({})
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract({"evidence_required": []})
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract({"evidence_keys": ["answer_correctness"]})

    def test_explicit_confirmation_policy_is_preserved_but_ceiling_is_clamped(self):
        contract = question_quality.normalize_graph_evidence_contract(
            {
                "evidence_required": ["结果正确"],
                "fixed_answer_mastery_policy": "confirmation_eligible",
                "fixed_answer_state_ceiling": "A",
            }
        )

        self.assertEqual("confirmation_eligible", contract["fixed_answer_mastery_policy"])
        self.assertEqual("A", contract["fixed_answer_state_ceiling"])

        contract = question_quality.normalize_graph_evidence_contract(
            {
                "evidence_required": ["过程可复盘"],
                "fixed_answer_mastery_policy": "confirmation_eligible",
                "fixed_answer_state_ceiling": "A",
            }
        )
        self.assertEqual("B", contract["fixed_answer_state_ceiling"])

    def test_invalid_graph_policy_enum_is_rejected(self):
        with self.assertRaises(ValueError):
            question_quality.normalize_graph_evidence_contract(
                {"evidence_required": ["结果正确"], "fixed_answer_mastery_policy": "auto_mastery"}
            )


if __name__ == "__main__":
    unittest.main()
