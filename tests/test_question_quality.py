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
from pathlib import Path
import unittest

from learning_system import question_fingerprints, question_quality


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

    def test_canonical_prompt_envelope_rejects_invalid_choice_and_field_entries(self):
        invalid_entries = [[None], ["not an object"], [{1: "non-string key"}], [{"label": object()}]]
        for entries in invalid_entries:
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    question_quality.canonical_prompt_envelope(stem="题目", choices=entries)
                with self.assertRaises(ValueError):
                    question_quality.canonical_prompt_envelope(stem="题目", fields=entries)

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

    def test_review_packet_checks_solution_step_limit_before_id_scan(self):
        packet = {
            "schema_version": "review_packet.v1",
            "reviewer_run_id": "run-1",
            "prompt_spans": [
                {"id": "p1", "start_token": 0, "end_token": 1, "instance_hash": "0" * 64, "structural_hash": "0" * 64}
            ],
            "solution_steps": [{} for _ in range(question_quality.MAX_SOLUTION_STEPS + 1)],
            "cross_node_prerequisite_relations": [],
        }
        with self.assertRaisesRegex(ValueError, "too many solution steps"):
            question_quality.validate_review_packet(packet)

    def test_review_packet_rejects_a_completely_empty_packet(self):
        packet = {
            "schema_version": "review_packet.v1",
            "reviewer_run_id": "run-1",
            "prompt_spans": [],
            "solution_steps": [],
            "cross_node_prerequisite_relations": [],
        }

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
        for target_step_id in ([], {}):
            with self.subTest(target_step_id=target_step_id):
                packet = json.loads(json.dumps(base))
                packet["cross_node_prerequisite_relations"] = [
                    {
                        "id": "r1",
                        "prerequisite_node_id": "node-1",
                        "evidence_key": "concept_recognition",
                        "target_step_id": target_step_id,
                    }
                ]
                with self.assertRaises(ValueError):
                    question_quality.validate_review_packet(packet)
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
        output[1] = "reject"
        with self.assertRaises(ValueError):
            question_quality.validate_discovery_derivation_output(output)

    def test_discovery_and_graph_enums_reject_unhashable_values_as_value_error(self):
        discovery = {
            "schema_version": "discovery_derivation.v1",
            "discovery_depth": "E2",
            "entry_point_visibility": "implicit",
            "decision_points": [],
            "solution_families": [],
            "execution_steps": 1,
            "key_insight_evidence_keys": [],
        }
        for field, value in (("discovery_depth", []), ("entry_point_visibility", {})):
            with self.subTest(field=field):
                invalid = {**discovery, field: value}
                with self.assertRaises(ValueError):
                    question_quality.validate_discovery_derivation_output(invalid)

        for field, value in (("fixed_answer_mastery_policy", []), ("fixed_answer_state_ceiling", {})):
            with self.subTest(field=field):
                invalid = {"evidence_required": ["结果正确"], field: value}
                with self.assertRaises(ValueError):
                    question_quality.normalize_graph_evidence_contract(invalid)

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
        for taxonomy in ([], {}):
            with self.subTest(taxonomy=taxonomy):
                decision["taxonomy"] = taxonomy
                with self.assertRaises(ValueError):
                    question_quality.validate_discovery_derivation_output(
                        {
                            "schema_version": "discovery_derivation.v1",
                            "discovery_depth": "E2",
                            "entry_point_visibility": "implicit",
                            "decision_points": [decision],
                            "solution_families": [family],
                            "execution_steps": 1,
                            "key_insight_evidence_keys": ["concept_recognition"],
                        },
                        solution_step_actions={},
                    )
        decision["taxonomy"] = "classify_structure"
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


class ReviewerDerivedDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = Path(__file__).parent / "fixtures" / "question_quality_review_packets.json"
        cls.cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    def _derive(self, name):
        case = self.cases[name]
        return question_quality.derive_discovery_derivation(
            case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
        )

    def test_fixture_covers_authoritative_e0_to_e4_levels(self):
        expected = {"e0": "E0", "e1": "E1", "e2": "E2", "e3": "E3", "e4": "E4"}
        for name, depth in expected.items():
            with self.subTest(name=name):
                receipt = self._derive(name)
                self.assertEqual(depth, receipt["discovery_depth"])

    def test_e0_is_marked_low_information_and_cannot_be_raised_by_execution(self):
        receipt = self._derive("e0")
        self.assertTrue(receipt["low_information"])
        self.assertFalse(receipt["scheduling_eligible"])
        self.assertEqual(1, receipt["execution_steps"])
        self.assertEqual("E0", receipt["discovery_depth"])

        case = json.loads(json.dumps(self.cases["e0"]))
        case["proposal"]["execution_steps"] = 8
        receipt = question_quality.derive_discovery_derivation(
            case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
        )
        self.assertEqual("E0", receipt["discovery_depth"])

    def test_authoritative_derive_marks_direct_operations_e0_but_real_decision_e2(self):
        def derive(prompt, *, action="apply_model", graph_contract=None, evidence_key="answer_correctness"):
            graph_contract = graph_contract or {
                "graph_lineage": "math-v2",
                "node_id": "math.direct-operation",
                "diagnosis_contract": {},
                "question_generation": {},
            }
            span = question_quality.prompt_span(
                prompt,
                start_token=0,
                end_token=len(question_quality.prompt_tokens(prompt)),
            )
            span["id"] = "p1"
            packet = {
                "schema_version": "review_packet.v1",
                "reviewer_run_id": "regression-direct-operation",
                "prompt_spans": [span],
                "solution_steps": [{
                    "id": "s1",
                    "action": action,
                    "evidence_key": evidence_key,
                    "input_step_ids": [],
                    "input_evidence_keys": [evidence_key],
                    "prompt_span_ids": ["p1"],
                }],
                "cross_node_prerequisite_relations": [],
            }
            return question_quality.derive_discovery_derivation(
                {
                    "entry_point": action,
                    "discovery_depth": "E2" if action == "resolve_sign_scope" else "E0",
                    "execution_steps": 1,
                    "required_decisions": ["resolve_sign_scope"] if action == "resolve_sign_scope" else [],
                    "required_steps": ["s1"],
                },
                review_packet=packet,
                graph_contract=graph_contract,
                prompt=prompt,
            )

        for prompt in (
            "-8 + 3",
            "2^4",
            "-7 和 -3 比较",
            "比较 -7 和 -3 的大小",
            "-7 ○ -3",
            "-7 < -3",
            "-7 ≤ -3",
            "-7 > -3",
            "-7 ≥ -3",
            "4x + 6x",
        ):
            with self.subTest(prompt=prompt):
                receipt = derive(prompt)
                self.assertEqual("E0", receipt["discovery_depth"])
                self.assertTrue(receipt["low_information"])
                self.assertFalse(receipt["scheduling_eligible"])

        decision_graph = {
            "graph_lineage": "math-v2",
            "node_id": "math.sign-scope",
            "diagnosis_contract": {
                "decision_taxonomies": {
                    "resolve_sign_scope": {
                        "alternatives": ["include_sign", "exclude_sign"],
                        "misconception_key": "sign_scope",
                    }
                }
            },
            "question_generation": {},
        }
        receipt = derive(
            "判断 -2^4 中负号的范围",
            action="resolve_sign_scope",
            graph_contract=decision_graph,
            evidence_key="concept_recognition",
        )
        self.assertEqual("E2", receipt["discovery_depth"])
        self.assertFalse(receipt["low_information"])
        self.assertTrue(receipt["scheduling_eligible"])

    def test_mechanical_detection_does_not_match_arithmetic_inside_a_rich_task(self):
        rich_prompts = (
            "在多项式 P = 6m^2n-2mn^3+3m^2n+8mn-4 中，老师要求先做同类项整理。下列哪一对项应先合并？",
            "在算式 -8 - (-5 - 7) + 4 中，可选两种策略：A 先算括号内，B 先把减法改写成加上相反数。",
        )
        for prompt in rich_prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(question_quality._is_low_information_mechanical_prompt(prompt))

    def test_prompt_that_names_number_line_is_explicit(self):
        self.assertEqual(
            "explicit",
            question_quality._entry_point_visibility(
                "在数轴上表示这四个数，并按从小到大排序。",
                {"diagnosis_contract": {}, "question_generation": {}},
                ["apply_model"],
            ),
        )

    def test_route_choice_remains_cued_even_when_an_alternative_names_a_rule(self):
        self.assertEqual(
            "cued",
            question_quality._entry_point_visibility(
                "你可按两种方式求值：1. 全部把减法改写，2. 直接按减法规则计算。",
                {"diagnosis_contract": {}, "question_generation": {}},
                ["select_operation_order"],
            ),
        )

    def test_node_contract_digest_binds_every_graph_input_used_by_derivation(self):
        family_case = json.loads(json.dumps(self.cases["e1"]))
        family_case["graph_contract"]["solution_families"] = [{
            "id": "f1",
            "step_ids": ["s1"],
            "first_action": "apply_model",
        }]
        family_receipt = self._derive_from_case(family_case)

        changed_family = json.loads(json.dumps(family_case))
        changed_family["graph_contract"]["solution_families"].append({
            "id": "f2",
            "step_ids": ["s1"],
            "first_action": "apply_model",
        })
        self.assertNotEqual(
            family_receipt["node_contract_sha256"],
            question_quality.node_contract_sha256(changed_family["graph_contract"]),
        )
        changed_receipt = self._derive_from_case(changed_family)
        self.assertNotEqual(family_receipt["solution_families"], changed_receipt["solution_families"])

        decision_case = json.loads(json.dumps(self.cases["e3"]))
        decision_receipt = self._derive_from_case(decision_case)
        changed_decision = json.loads(json.dumps(decision_case))
        changed_decision["graph_contract"]["diagnosis_contract"]["decision_taxonomies"]["select_model"]["alternatives"] = [
            "number_line",
            "decimal",
        ]
        self.assertNotEqual(
            decision_receipt["node_contract_sha256"],
            question_quality.node_contract_sha256(changed_decision["graph_contract"]),
        )
        changed_decision["proposal"]["node_contract_sha256"] = decision_receipt["node_contract_sha256"]
        with self.assertRaisesRegex(ValueError, "node contract digest"):
            self._derive_from_case(changed_decision)

    def test_candidate_level_mismatch_is_rejected(self):
        case = json.loads(json.dumps(self.cases["e2"]))
        case["proposal"]["discovery_depth"] = "E1"
        with self.assertRaisesRegex(ValueError, "proposed discovery depth"):
            question_quality.derive_discovery_derivation(
                case["proposal"],
                review_packet=case["packet"],
                graph_contract=case["graph_contract"],
                prompt=case["prompt"],
            )

    def test_pilot_can_record_untrusted_proposal_while_compiler_uses_review_evidence(self):
        case = json.loads(json.dumps(self.cases["e2"]))
        case["proposal"]["entry_point"] = "apply_model"
        receipt = question_quality.derive_discovery_derivation(
            case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
            enforce_proposal_alignment=False,
        )
        self.assertEqual("E2", receipt["discovery_depth"])
        self.assertEqual("resolve_sign_scope", receipt["decision_points"][0]["taxonomy"])

    def test_review_packet_digest_and_span_hashes_are_bound(self):
        case = self.cases["e2"]
        packet = question_quality.validate_review_packet(
            case["packet"],
            prompt=case["prompt"],
            graph_contract=case["graph_contract"],
        )
        self.assertEqual(
            question_quality.review_packet_sha256(packet),
            question_quality.review_packet_sha256(case["packet"]),
        )

        tampered = json.loads(json.dumps(case["packet"]))
        tampered["prompt_spans"][0]["instance_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "instance hash"):
            question_quality.validate_review_packet(tampered, prompt=case["prompt"])

        proposal = json.loads(json.dumps(case["proposal"]))
        proposal["review_packet_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "review packet digest"):
            question_quality.derive_discovery_derivation(
                proposal,
                review_packet=case["packet"],
                graph_contract=case["graph_contract"],
                prompt=case["prompt"],
            )

    def test_generator_only_dependencies_do_not_create_e3(self):
        case = json.loads(json.dumps(self.cases["e1"]))
        case["proposal"]["required_decisions"] = ["resolve_sign_scope"]
        case["proposal"]["depends_on"] = ["fake-decision"]
        with self.assertRaisesRegex(ValueError, "proposal"):
            question_quality.derive_discovery_derivation(
                case["proposal"],
                review_packet=case["packet"],
                graph_contract=case["graph_contract"],
                prompt=case["prompt"],
            )

    def test_graph_relation_must_be_declared_and_used_by_target_step(self):
        case = json.loads(json.dumps(self.cases["e3_relation"]))
        case["packet"]["cross_node_prerequisite_relations"][0]["evidence_key"] = "transfer"
        with self.assertRaisesRegex(ValueError, "graph contract"):
            question_quality.derive_discovery_derivation(
                case["proposal"],
                review_packet=case["packet"],
                graph_contract=case["graph_contract"],
                prompt=case["prompt"],
            )

        case = json.loads(json.dumps(self.cases["e3_relation"]))
        case["packet"]["solution_steps"][1]["input_evidence_keys"] = ["model_selection"]
        with self.assertRaisesRegex(ValueError, "target step"):
            question_quality.derive_discovery_derivation(
                case["proposal"],
                review_packet=case["packet"],
                graph_contract=case["graph_contract"],
                prompt=case["prompt"],
            )

    def test_dependency_derivation_uses_topological_transitive_solution_graph(self):
        case = json.loads(json.dumps(self.cases["e3"]))
        case["proposal"].update(
            {
                "required_decisions": ["select_model", "choose_representation"],
                "required_steps": ["s1", "s2", "s3"],
            }
        )
        case["graph_contract"]["diagnosis_contract"]["decision_taxonomies"].update(
            {
                "choose_representation": {
                    "alternatives": ["fraction", "decimal"],
                    "misconception_key": "representation_choice",
                }
            }
        )
        case["packet"]["solution_steps"] = [
            {
                "id": "s3",
                "action": "choose_representation",
                "evidence_key": "concept_recognition",
                "input_step_ids": ["s2"],
                "input_evidence_keys": ["concept_recognition"],
                "prompt_span_ids": ["p1"],
            },
            {
                "id": "s2",
                "action": "apply_model",
                "evidence_key": "model_selection",
                "input_step_ids": ["s1"],
                "input_evidence_keys": ["model_selection"],
                "prompt_span_ids": ["p1"],
            },
            {
                "id": "s1",
                "action": "select_model",
                "evidence_key": "model_selection",
                "input_step_ids": [],
                "input_evidence_keys": ["model_selection"],
                "prompt_span_ids": ["p1"],
            },
        ]

        receipt = question_quality.derive_discovery_derivation(
            case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
        )

        self.assertEqual("E3", receipt["discovery_depth"])
        self.assertEqual(["s1"], receipt["decision_points"][0]["step_ids"])
        self.assertEqual(["d1"], receipt["decision_points"][1]["depends_on"])
        self.assertEqual("s3", receipt["decision_points"][1]["step_ids"][0])

    def test_proposal_projection_must_match_authoritative_canonical_fields(self):
        for field, value in (
            ("entry_point_visibility", "explicit"),
            ("required_decisions", []),
            ("required_steps", ["s2", "s1"]),
        ):
            with self.subTest(field=field):
                case = json.loads(json.dumps(self.cases["e3"]))
                case["proposal"][field] = value
                with self.assertRaisesRegex(ValueError, "proposal"):
                    self._derive_from_case(case)

    def test_graph_identity_overrides_are_rejected_in_derivation_input(self):
        case = self.cases["e1"]
        for kwargs in (
            {"graph_lineage": "forged-lineage"},
            {"node_id": "forged.node"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "immutable graph contract"):
                    question_quality.build_discovery_derivation_input(
                        proposal=case["proposal"],
                        review_packet=case["packet"],
                        graph_contract=case["graph_contract"],
                        prompt=case["prompt"],
                        **kwargs,
                    )

    def test_proposal_envelope_fails_closed_and_derivation_input_keeps_controlled_projection(self):
        case = json.loads(json.dumps(self.cases["e1"]))
        with self.assertRaisesRegex(ValueError, "proposal"):
            self._derive_from_case({**case, "proposal": {}})

        for field, value in (("alternative_entries", "not-an-array"), ("depends_on", ["fake-decision"])):
            with self.subTest(field=field):
                invalid = json.loads(json.dumps(case))
                invalid["proposal"][field] = value
                with self.assertRaisesRegex(ValueError, "proposal"):
                    self._derive_from_case(invalid)

        derivation_input = question_quality.build_discovery_derivation_input(
            proposal=case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
        )
        self.assertEqual(
            {
                "entry_point": "apply_model",
                "required_decisions": [],
                "required_steps": ["s1"],
            },
            derivation_input["proposal"],
        )

    def _derive_from_case(self, case):
        return question_quality.derive_discovery_derivation(
            case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
        )

    def test_review_packet_rejects_cycles_and_out_of_bounds_spans(self):
        case = json.loads(json.dumps(self.cases["e3"]))
        case["packet"]["solution_steps"][0]["input_step_ids"] = ["s2"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            question_quality.validate_review_packet(case["packet"], prompt=case["prompt"])

        case = json.loads(json.dumps(self.cases["e1"]))
        case["packet"]["prompt_spans"][0]["end_token"] += 1
        with self.assertRaisesRegex(ValueError, "outside"):
            question_quality.validate_review_packet(case["packet"], prompt=case["prompt"])


class QuestionFingerprintV2Tests(unittest.TestCase):
    def _descriptor(self, *, number="3", story="apples", **changes):
        descriptor = {
            "graph_lineage": "math-v2",
            "node_id": "math.integer.order",
            "question_type": "fill_blank",
            "prompt_envelope": {
                "stem": f"{story}: compare {number}/4 and -1/2",
                "fields": [{"id": "answer", "label": "答案", "input_mode": "fraction"}],
            },
            "interaction_schema": {
                "type": "fill_blank",
                "choices": [],
                "fields": [{"id": "answer", "label": "答案", "required": True, "input_mode": "fraction"}],
            },
            "values": [{"name": "n", "type": "number", "value": number}],
            "surface_entities": [story],
            "mathematical_grammar": "fraction_ordering",
            "structural_prompt_span_hashes": ["a" * 64],
            "decision_taxonomies": ["choose_representation"],
            "solution_actions": ["choose_common_denominator", "order_values"],
            "evidence_keys": ["model_selection"],
            "misconception_keys": ["negative_order"],
        }
        descriptor.update(changes)
        return descriptor

    def test_exact_duplicates_are_rejected_and_numbers_stories_share_a_family(self):
        base = question_fingerprints.build_question_fingerprints(self._descriptor())
        duplicate = question_fingerprints.build_question_fingerprints(self._descriptor())
        with self.assertRaisesRegex(ValueError, "exact"):
            question_fingerprints.validate_family_quota("math.integer.order", [base, duplicate])

        changed_instance = question_fingerprints.build_question_fingerprints(
            self._descriptor(number="9", story="marbles")
        )
        self.assertNotEqual(base["exact_instance_fingerprint"], changed_instance["exact_instance_fingerprint"])
        self.assertEqual(base["family_fingerprint"], changed_instance["family_fingerprint"])

    def test_exact_fingerprint_binds_authoritative_discovery_receipt_digest(self):
        first = self._descriptor(discovery_derivation_sha256="a" * 64)
        second = self._descriptor(discovery_derivation_sha256="b" * 64)

        first_fingerprint = question_fingerprints.build_question_fingerprints(first)
        second_fingerprint = question_fingerprints.build_question_fingerprints(second)

        self.assertNotEqual(
            first_fingerprint["exact_instance_fingerprint"],
            second_fingerprint["exact_instance_fingerprint"],
        )

    def test_family_normalizes_surface_arrays_with_typed_placeholders(self):
        interaction_schema = {
            "type": "single_choice",
            "mode": "single_choice",
            "choices": [
                {"id": "choice-a", "label": "甲", "value": "-1/2"},
                {"id": "choice-b", "label": "乙", "value": "3/4"},
            ],
            "fields": [
                {"id": "answer-a", "label": "答案", "required": True, "input_mode": "fraction"},
            ],
        }
        base = self._descriptor(interaction_schema=interaction_schema)
        relabeled = self._descriptor(
            interaction_schema={
                **interaction_schema,
                "choices": [
                    {"id": "renamed-1", "label": "丙", "value": "other"},
                    {"id": "renamed-2", "label": "丁", "value": "another"},
                ],
                "fields": [
                    {"id": "renamed-field", "label": "填写结果", "required": True, "input_mode": "fraction"},
                ],
            }
        )
        changed_choice_count = self._descriptor(
            interaction_schema={
                **interaction_schema,
                "choices": interaction_schema["choices"] + [{"id": "choice-c", "label": "丙", "value": "0"}],
            }
        )
        changed_grammar = self._descriptor(
            interaction_schema={
                **interaction_schema,
                "fields": [
                    {"id": "answer-a", "label": "答案", "required": True, "input_mode": "decimal"},
                ],
            }
        )

        base_fingerprint = question_fingerprints.build_question_fingerprints(base)
        self.assertEqual(
            base_fingerprint["family_fingerprint"],
            question_fingerprints.build_question_fingerprints(relabeled)["family_fingerprint"],
        )
        self.assertNotEqual(
            base_fingerprint["family_fingerprint"],
            question_fingerprints.build_question_fingerprints(changed_choice_count)["family_fingerprint"],
        )
        self.assertNotEqual(
            base_fingerprint["family_fingerprint"],
            question_fingerprints.build_question_fingerprints(changed_grammar)["family_fingerprint"],
        )
        self.assertEqual(
            [
                {"id": "CHOICE_ID", "label": "CHOICE_LABEL", "value": "CHOICE_VALUE"},
                {"id": "CHOICE_ID", "label": "CHOICE_LABEL", "value": "CHOICE_VALUE"},
            ],
            base_fingerprint["family_payload"]["structural_interaction_schema"]["choices"],
        )

    def test_structural_span_and_family_normalization_replaces_cosmetic_names_but_keeps_structure(self):
        base_span = question_quality.prompt_span("张三 有 3 个 苹果", start_token=0, end_token=5)
        renamed_span = question_quality.prompt_span("李四 有 3 个 橘子", start_token=0, end_token=5)
        self.assertNotEqual(base_span["instance_hash"], renamed_span["instance_hash"])
        self.assertEqual(base_span["structural_hash"], renamed_span["structural_hash"])

        interaction = {
            "type": "single_choice",
            "mode": "single_choice",
            "choices": [],
            "choice_ids": ["choice-a", "choice-b"],
            "choice_labels": ["甲", "乙"],
            "field_ids": ["answer-a"],
            "fields": [{"id": "answer-a", "label": "答案", "required": True, "input_mode": "fraction"}],
        }
        base = self._descriptor(interaction_schema=interaction)
        renamed = self._descriptor(
            interaction_schema={
                **interaction,
                "choice_ids": ["left", "right"],
                "choice_labels": ["第一项", "第二项"],
                "field_ids": ["result"],
                "fields": [{"id": "result", "label": "填写结果", "required": True, "input_mode": "fraction"}],
            }
        )
        self.assertEqual(
            question_fingerprints.family_fingerprint(base),
            question_fingerprints.family_fingerprint(renamed),
        )
        for mutation in (
            {"mathematical_grammar": "fraction_addition"},
            {"evidence_keys": ["transfer"]},
            {"misconception_keys": ["wrong_sign_scope"]},
            {"decision_taxonomies": ["resolve_sign_scope"]},
        ):
            with self.subTest(mutation=mutation):
                self.assertNotEqual(
                    question_fingerprints.family_fingerprint(base),
                    question_fingerprints.family_fingerprint(self._descriptor(**mutation)),
                )

    def test_fingerprint_pair_uses_v2_hashes_and_keeps_legacy_aliases(self):
        instance = {
            "relations": ["C=A+3", "A<C<B"],
            "values": [{"name": "A", "value": -2.5}, {"name": "step", "value": 3}],
            "requested": ["C", "ascending_order"],
        }
        core = {
            "relation": "directed_translation_then_order",
            "evidence": ["relation", "value", "order"],
        }
        pair = question_fingerprints.fingerprint_pair(
            instance,
            core,
            graph_lineage="math-v2",
            node_id="math.integer.order",
            question_type="fill_blank",
            graph_version="math-v2",
            node_contract_sha256="a" * 64,
            interaction_schema={
                "type": "fill_blank",
                "choices": [],
                "fields": [{"id": "answer", "label": "答案"}],
            },
        )
        self.assertEqual(
            pair["exact_instance_fingerprint"],
            pair["prompt_instance_fingerprint"],
        )
        self.assertEqual(
            pair["family_fingerprint"],
            pair["core_structure_fingerprint"],
        )
        self.assertEqual("question_fingerprint.v2", pair["fingerprint_policy_version"])
        self.assertNotEqual(
            pair["prompt_instance_fingerprint"],
            question_fingerprints.descriptor_fingerprint(
                instance,
                fingerprint_type="prompt_instance",
            ),
        )

    def test_fingerprint_pair_policy_version_selects_the_actual_hash_payload(self):
        instance = {"values": [{"name": "x", "value": 3}], "requested": ["x"]}
        core = {"relation": "identity", "evidence": ["answer_correctness"]}
        v1 = question_fingerprints.fingerprint_pair(
            instance,
            core,
            policy_version="question-fingerprint.v1",
        )
        self.assertEqual("question-fingerprint.v1", v1["fingerprint_policy_version"])
        self.assertEqual(
            question_fingerprints.descriptor_fingerprint(
                instance,
                fingerprint_type="prompt_instance",
                policy_version="question-fingerprint.v1",
            ),
            v1["prompt_instance_fingerprint"],
        )
        self.assertEqual(
            question_fingerprints.descriptor_fingerprint(
                core,
                fingerprint_type="core_structure",
                policy_version="question-fingerprint.v1",
            ),
            v1["core_structure_fingerprint"],
        )
        self.assertNotIn("exact_instance_fingerprint", v1)

        v2 = question_fingerprints.fingerprint_pair(
            instance,
            core,
            policy_version="question_fingerprint.v2",
            graph_lineage="math-v2",
            node_id="math.integer.order",
            question_type="fill_blank",
            interaction_schema={
                "type": "fill_blank",
                "choices": [],
                "fields": [{"id": "answer", "label": "答案"}],
            },
        )
        self.assertEqual("question_fingerprint.v2", v2["fingerprint_policy_version"])
        self.assertIn("exact_instance_fingerprint", v2)
        self.assertNotEqual(v1["prompt_instance_fingerprint"], v2["prompt_instance_fingerprint"])

    def test_fingerprint_descriptor_rejects_malformed_authoritative_members(self):
        malformed = self._descriptor(decision_points=["not-an-object"])
        with self.assertRaises((TypeError, ValueError)):
            question_fingerprints.build_question_fingerprints(malformed)

        malformed = self._descriptor(solution_families=["not-an-object"])
        with self.assertRaises((TypeError, ValueError)):
            question_fingerprints.build_question_fingerprints(malformed)

        malformed = self._descriptor(solution_actions="apply_model")
        with self.assertRaises((TypeError, ValueError)):
            question_fingerprints.build_question_fingerprints(malformed)

        malformed = self._descriptor(values={1: "non-string key"})
        with self.assertRaises((TypeError, ValueError)):
            question_fingerprints.build_question_fingerprints(malformed)

    def test_family_fingerprint_fails_closed_without_interaction_schema(self):
        descriptor = self._descriptor()
        del descriptor["interaction_schema"]
        with self.assertRaisesRegex(ValueError, "interaction_schema"):
            question_fingerprints.family_fingerprint(descriptor)

    def test_family_fingerprint_does_not_accept_structural_schema_as_authority(self):
        descriptor = self._descriptor(
            structural_interaction_schema={
                "fields": [
                    {
                        "id": "FIELD_ID",
                        "label": "FIELD_LABEL",
                        "required": True,
                        "input_mode": "fraction",
                    }
                ]
            }
        )
        del descriptor["interaction_schema"]
        with self.assertRaisesRegex(ValueError, "interaction_schema"):
            question_fingerprints.family_fingerprint(descriptor)

    def test_family_fingerprint_rejects_forged_structural_schema_override(self):
        descriptor = self._descriptor(
            structural_interaction_schema={
                "fields": [
                    {
                        "id": "FIELD_ID",
                        "label": "FIELD_LABEL",
                        "required": True,
                        "input_mode": "decimal",
                    }
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "structural_interaction_schema"):
            question_fingerprints.family_fingerprint(descriptor)

    def test_family_fingerprint_accepts_structural_schema_only_when_it_matches_projection(self):
        authoritative = self._descriptor()
        expected = question_fingerprints.build_question_fingerprints(authoritative)
        descriptor = self._descriptor(
            structural_interaction_schema=expected["family_payload"]["structural_interaction_schema"]
        )
        actual = question_fingerprints.build_question_fingerprints(descriptor)
        self.assertEqual(expected["family_fingerprint"], actual["family_fingerprint"])

    def test_family_payload_stores_verifiable_structural_derivation_digest_only(self):
        fingerprints = question_fingerprints.build_question_fingerprints(self._descriptor())
        payload = fingerprints["family_payload"]
        self.assertNotIn("structural_derivation", payload)
        self.assertEqual(
            64,
            len(payload["structural_derivation_digest_sha256"]),
        )
        self.assertEqual(
            payload["structural_derivation_digest_sha256"],
            question_fingerprints.canonical_sha256(
                question_fingerprints._structural_derivation(self._descriptor())
            ),
        )

    def test_family_quota_recomputes_candidate_fingerprints_instead_of_trusting_supplied_hashes(self):
        existing = question_fingerprints.build_question_fingerprints(self._descriptor())
        forged_candidate = self._descriptor()
        forged_candidate.update(
            {
                "exact_instance_fingerprint": "f" * 64,
                "family_fingerprint": "e" * 64,
            }
        )
        with self.assertRaisesRegex(ValueError, "exact"):
            question_fingerprints.validate_family_quota(
                "math.integer.order",
                [forged_candidate],
                existing=[existing],
            )

    def test_family_quota_rejects_candidate_node_id_mismatch(self):
        mismatched = self._descriptor(node_id="math.other-node")
        with self.assertRaisesRegex(ValueError, "node_id"):
            question_fingerprints.validate_family_quota(
                "math.integer.order",
                [mismatched],
            )

    def test_grammar_evidence_misconception_and_decision_changes_make_new_family(self):
        base = question_fingerprints.build_question_fingerprints(self._descriptor())
        mutations = (
            {"mathematical_grammar": "signed_decimal_ordering"},
            {"evidence_keys": ["transfer"]},
            {"misconception_keys": ["zero_as_positive"]},
            {"decision_taxonomies": ["resolve_sign_scope"]},
            {"structural_prompt_span_hashes": ["b" * 64]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = question_fingerprints.build_question_fingerprints(
                    self._descriptor(**mutation)
                )
                self.assertNotEqual(base["family_fingerprint"], changed["family_fingerprint"])

    def test_family_quota_allows_only_one_distinct_second_evidence_misconception(self):
        first = question_fingerprints.build_question_fingerprints(self._descriptor())
        second = question_fingerprints.build_question_fingerprints(
            self._descriptor(evidence_keys=["transfer"], misconception_keys=["zero_as_positive"])
        )
        question_fingerprints.validate_family_quota("math.integer.order", [first, second])

        same_evidence = question_fingerprints.build_question_fingerprints(
            self._descriptor(misconception_keys=["zero_as_positive"])
        )
        with self.assertRaisesRegex(ValueError, "distinct evidence"):
            question_fingerprints.validate_family_quota(
                "math.integer.order", [first, same_evidence]
            )

        third = question_fingerprints.build_question_fingerprints(
            self._descriptor(number="11", evidence_keys=["transfer"], misconception_keys=["zero_as_positive"])
        )
        with self.assertRaisesRegex(ValueError, "at most two"):
            question_fingerprints.validate_family_quota(
                "math.integer.order", [first, second, third]
            )

    def test_fingerprint_descriptor_requires_graph_lineage_and_node_id(self):
        for field in ("graph_lineage", "node_id"):
            with self.subTest(field=field):
                descriptor = self._descriptor()
                del descriptor[field]
                with self.assertRaisesRegex(ValueError, field):
                    question_fingerprints.build_question_fingerprints(descriptor)

    def test_graph_a_and_graph_b_cannot_share_v2_fingerprints(self):
        graph_a = self._descriptor(
            graph_lineage="graph-A+lineage",
            graph_version="graph-A",
            node_contract_sha256="a" * 64,
        )
        graph_b = self._descriptor(
            graph_lineage="graph-B+lineage",
            graph_version="graph-B",
            node_contract_sha256="b" * 64,
        )
        first = question_fingerprints.build_question_fingerprints(graph_a)
        second = question_fingerprints.build_question_fingerprints(graph_b)
        self.assertNotEqual(first["exact_instance_fingerprint"], second["exact_instance_fingerprint"])
        self.assertNotEqual(first["family_fingerprint"], second["family_fingerprint"])
        self.assertNotEqual(
            first["family_payload"]["graph_lineage"],
            second["family_payload"]["graph_lineage"],
        )
        self.assertNotEqual(
            first["family_payload"]["node_contract_sha256"],
            second["family_payload"]["node_contract_sha256"],
        )

    def test_v2_interaction_schema_fails_closed_before_projection(self):
        malformed_cases = (
            {"type": "fill_blank", "choices": [], "fields": [{"label": "答案"}]},
            {"type": "fill_blank", "choices": [], "fields": [{"id": [], "label": "答案"}]},
            {"type": "fill_blank", "choices": [{"id": "a", "label": "甲", "value": {}}], "fields": []},
            {"type": "fill_blank", "choices": [], "fields": [{"id": "answer", "label": []}]},
            {"type": "fill_blank", "choices": {}, "fields": []},
            {"type": "fill_blank", "fields": []},
            {"type": "fill_blank", "choices": [], "fields": [], "label": {}},
        )
        for interaction_schema in malformed_cases:
            with self.subTest(interaction_schema=interaction_schema):
                with self.assertRaises(ValueError):
                    question_fingerprints.build_question_fingerprints(
                        self._descriptor(interaction_schema=interaction_schema)
                    )

    def test_interaction_schema_digest_uses_shared_question_quality_normalization(self):
        case = json.loads(
            (Path(__file__).parent / "fixtures" / "question_quality_review_packets.json").read_text(
                encoding="utf-8"
            )
        )["e1"]
        first = question_quality.build_discovery_derivation_input(
            proposal=case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
            interaction_schema={"label": "Ａ  ×\n Ｂ", "mode": "short_text"},
        )
        second = question_quality.build_discovery_derivation_input(
            proposal=case["proposal"],
            review_packet=case["packet"],
            graph_contract=case["graph_contract"],
            prompt=case["prompt"],
            interaction_schema={"label": "A * B", "mode": "short_text"},
        )
        self.assertEqual(first["interaction_schema_sha256"], second["interaction_schema_sha256"])


if __name__ == "__main__":
    unittest.main()
