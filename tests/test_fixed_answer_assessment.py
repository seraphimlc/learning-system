"""TDD test list and focused tests for fixed-answer envelope primitives.

Test list:
- the response schema version is shared with question-quality contracts
- JSON parsing rejects duplicate keys, null/non-object envelopes, unknown keys,
  oversized payloads, wrong types, and mode-incompatible fields
- choice and fill-blank envelopes enforce unique ids and bounded values
- canonical response digests are deterministic and client result fields are
  outside the closed wire contract
"""

import json
import unittest

from learning_system import fixed_answer_assessment


class FixedAnswerEnvelopeTests(unittest.TestCase):
    def test_version_constant_and_valid_envelopes(self):
        self.assertEqual(
            "2026-08-25.fixed-answer-response.v1",
            fixed_answer_assessment.FIXED_RESPONSE_SCHEMA_VERSION,
        )
        single = fixed_answer_assessment.parse_fixed_answer_response(
            '{"schema_version":"2026-08-25.fixed-answer-response.v1","type":"single_choice","choice_id":"B"}'
        )
        self.assertEqual("B", single["choice_id"])

        multi = fixed_answer_assessment.parse_fixed_answer_response(
            {
                "schema_version": "2026-08-25.fixed-answer-response.v1",
                "type": "multi_choice",
                "choice_ids": ["C", "A"],
            }
        )
        self.assertEqual(["C", "A"], multi["choice_ids"])

        fill = fixed_answer_assessment.parse_fixed_answer_response(
            {
                "schema_version": "2026-08-25.fixed-answer-response.v1",
                "type": "fill_blank",
                "fields": [{"id": "x", "value": "10"}],
            }
        )
        self.assertEqual("10", fill["fields"][0]["value"])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            fixed_answer_assessment.parse_fixed_answer_response(
                '{"schema_version":"2026-08-25.fixed-answer-response.v1","type":"single_choice","choice_id":"A","choice_id":"B"}'
            )

    def test_null_unknown_oversized_and_invalid_mode_payloads_are_rejected(self):
        invalid_payloads = [
            None,
            {"schema_version": "2026-08-25.fixed-answer-response.v1", "type": "single_choice", "choice_id": "A", "score": 10},
            {"schema_version": "2026-08-25.fixed-answer-response.v1", "type": "multi_choice", "choice_id": "A"},
            {"schema_version": "2026-08-25.fixed-answer-response.v1", "type": "multi_choice", "choice_ids": ["A", "A"]},
            {"schema_version": "2026-08-25.fixed-answer-response.v1", "type": "fill_blank", "fields": [{"id": "x", "value": None}]},
            {"schema_version": "2026-08-25.fixed-answer-response.v1", "type": "single_choice", "choice_id": "x" * 129},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    fixed_answer_assessment.parse_fixed_answer_response(payload)

        oversized = json.dumps(
            {
                "schema_version": "2026-08-25.fixed-answer-response.v1",
                "type": "single_choice",
                "choice_id": "A",
            }
        ).encode("utf-8") + b" " * (16 * 1024)
        with self.assertRaises(ValueError):
            fixed_answer_assessment.parse_fixed_answer_response(oversized)

    def test_fill_blank_ids_are_unique_and_bounded(self):
        base = {
            "schema_version": "2026-08-25.fixed-answer-response.v1",
            "type": "fill_blank",
        }
        for fields in (
            [{"id": "x", "value": "1"}, {"id": "x", "value": "2"}],
            [{"id": str(i), "value": "1"} for i in range(9)],
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    fixed_answer_assessment.parse_fixed_answer_response({**base, "fields": fields})

    def test_canonical_digest_ignores_object_key_order(self):
        first = {
            "schema_version": "2026-08-25.fixed-answer-response.v1",
            "type": "single_choice",
            "choice_id": "A",
        }
        second = {"choice_id": "A", "type": "single_choice", "schema_version": "2026-08-25.fixed-answer-response.v1"}

        self.assertEqual(
            fixed_answer_assessment.response_digest(first),
            fixed_answer_assessment.response_digest(second),
        )


if __name__ == "__main__":
    unittest.main()
