"""CANONICAL_ERROR_TAGS single-source consolidation contract tests (M4-1 Task 1).

Contract under test: `learning_system/error_tags.py` is the *unique*
definition source for the canonical error-tag set; `learning_system/auto_review.py`
and `learning_system/question_bank.py` must import it instead of carrying
inline copies (audit record 核对项 7, docs/design/specs/2026-08-20-dataflow-audit-record.md).

Anti-drift guard (防漂移): the audit found both files had byte-identical inline
set literals with no test asserting equality — either side could diverge without
any failure, which would split the batch-grading enumeration (auto_review) from
the question-bank filtering enumeration (question_bank) and drift the three-year
error-cause distribution (`error_cause_log.error_tag`, M4-1 Task 2).

These tests pin:
- the canonical content (exactly the 6 agreed tags, nothing else);
- object *identity* with the single source (proves import, not a re-copy);
- the derived five-dimension map in auto_review stays inside the enum.

Run: python3 -m unittest tests.test_error_tags_canonical -v
"""

from __future__ import annotations

import unittest

from learning_system import auto_review, error_tags, question_bank

EXPECTED_CANONICAL_ERROR_TAGS = {
    "calculation_or_symbol",
    "concept_confusion",
    "modeling_or_reading",
    "process_habit",
    "visual_spatial",
    "general",
}


class CanonicalErrorTagsConsolidationTestCase(unittest.TestCase):
    def test_error_tags_module_is_exact_canonical_set(self):
        """The single source carries exactly the 6 canonical tags, no more."""
        self.assertEqual(EXPECTED_CANONICAL_ERROR_TAGS, error_tags.CANONICAL_ERROR_TAGS)
        self.assertEqual(6, len(error_tags.CANONICAL_ERROR_TAGS))

    def test_auto_review_imports_single_source_by_identity(self):
        """auto_review no longer carries an inline copy (identity, not equality)."""
        self.assertIs(error_tags.CANONICAL_ERROR_TAGS, auto_review.CANONICAL_ERROR_TAGS)

    def test_question_bank_imports_single_source_by_identity(self):
        """question_bank no longer carries an inline copy (identity, not equality)."""
        self.assertIs(error_tags.CANONICAL_ERROR_TAGS, question_bank.CANONICAL_ERROR_TAGS)

    def test_dimension_gap_error_tags_values_stay_inside_canonical(self):
        """auto_review's five-dimension → tag map must not drift outside the enum."""
        values = set(auto_review.DIMENSION_GAP_ERROR_TAGS.values())
        self.assertTrue(
            values <= error_tags.CANONICAL_ERROR_TAGS,
            f"dimension gap tags escaped canonical set: {values - error_tags.CANONICAL_ERROR_TAGS}",
        )


if __name__ == "__main__":
    unittest.main()
