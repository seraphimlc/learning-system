"""Mastery verdict core contract tests (M2.5 part 1).

Contract under test: docs/design/specs/2026-08-20-mastery-criteria-proposal.md
- §2.1: storage states A/B/C/D; verdict ∈ {D, C, B, A, NO_CHANGE}; NO_CHANGE
  is never stored ("没测过 ≠ 薄弱").
- §2.2: per-judgment-event rules R1-R6 (thresholds 0.85/0.60, reasoning-gap
  interception, strong-evidence definition) + window AGG conditions C1-C6.
- §7 anchors T1-T8 (verdict-core portion; state transitions T9-T13/T16-T23
  belong to later M2.5 tasks and are out of scope here).

Scope note: this module is pure — no I/O, no sqlite. It only decides the
verdict for one eligible judgment event. The "保持 A / 计数+1" behavior of
anchor T8 lives in the §2.3 transition/counter layer (M2.5-2), so T8 here
asserts only the verdict the core produces.

Run: python3 -m unittest tests.test_mastery_rules -v
"""

from __future__ import annotations

import unittest

from learning_system import mastery_rules as rules


def attempt(**overrides):
    """Canonical eligible diagnostic attempt; override any field per test."""
    base = {
        "attempt_id": "a1",
        "result": "correct",
        "score_points": 10,
        "max_points": 10,
        "explanation_score": 2,
        "reasoning_soundness": "sound",
        "evidence_strength": "strong",
        "next_evidence_need": "",
        "blocking_evidence": False,
        "structure_fingerprint": "fp_core",
        "purpose_role": "confirmation_core",
        "created_at": "2026-08-01",
        # eligibility fields (all default to eligible)
        "gate_passed": True,
        "purpose": "diagnostic",
        "hint_policy": "no_hint",
        "mastery_update_eligible": True,
        "voice_verifiable": True,
        "is_manual": False,
        "analysis_valid": True,
    }
    base.update(overrides)
    return base


def two_strong_window(day1="2026-08-01", day2="2026-08-02"):
    """Two strong attempts: different fingerprints + dual roles + 2 days."""
    first = attempt(
        attempt_id="a1",
        structure_fingerprint="fp_core",
        purpose_role="confirmation_core",
        created_at=day1,
    )
    current = attempt(
        attempt_id="a2",
        structure_fingerprint="fp_transfer",
        purpose_role="confirmation_transfer",
        created_at=day2,
    )
    return [first, current]


class TestVerdictShape(unittest.TestCase):
    def test_verdict_has_contract_fields(self):
        result = rules.decide_verdict(attempt())
        for key in ("code", "decision", "reason", "is_strong", "attrs"):
            self.assertIn(key, result)

    def test_verdict_code_is_in_five_value_enum(self):
        cases = [
            attempt(blocking_evidence=True),
            attempt(result="wrong", score_points=2, max_points=10),
            attempt(explanation_score=1),
            attempt(),
            attempt(purpose="practice"),
        ]
        for ev in cases:
            result = rules.decide_verdict(ev)
            self.assertIn(result["code"], {"D", "C", "B", "A", "NO_CHANGE"})


class TestBlockingD(unittest.TestCase):
    def test_blocking_evidence_is_d(self):  # T5 / R1
        result = rules.decide_verdict(attempt(blocking_evidence=True))
        self.assertEqual(result["code"], "D")
        self.assertFalse(result["is_strong"])


class TestWeakC(unittest.TestCase):
    def test_wrong_result_is_c(self):  # T6 / R2
        result = rules.decide_verdict(attempt(result="wrong", score_points=2, max_points=10))
        self.assertEqual(result["code"], "C")

    def test_ratio_below_060_is_c_even_when_correct(self):  # T6 / R2 precedence
        result = rules.decide_verdict(attempt(result="correct", score_points=5, max_points=10))
        self.assertEqual(result["code"], "C")
        self.assertEqual(result["attrs"]["reason_code"], "ratio_below_0.60")

    def test_partial_result_is_c(self):  # R3
        result = rules.decide_verdict(attempt(result="partial", score_points=8, max_points=10))
        self.assertEqual(result["code"], "C")

    def test_explanation_below_2_is_c_even_with_high_ratio(self):  # R3
        result = rules.decide_verdict(attempt(score_points=10, max_points=10, explanation_score=1))
        self.assertEqual(result["code"], "C")

    def test_reasoning_soundness_incomplete_is_c(self):  # T4 / R3 over R4
        result = rules.decide_verdict(attempt(reasoning_soundness="incomplete"))
        self.assertEqual(result["code"], "C")
        self.assertEqual(result["attrs"]["reason_code"], "reasoning_gap")

    def test_reasoning_soundness_unsound_is_c(self):
        result = rules.decide_verdict(attempt(reasoning_soundness="unsound"))
        self.assertEqual(result["code"], "C")

    def test_evidence_strength_weak_is_c(self):
        result = rules.decide_verdict(attempt(evidence_strength="weak"))
        self.assertEqual(result["code"], "C")

    def test_evidence_strength_insufficient_is_c(self):
        result = rules.decide_verdict(attempt(evidence_strength="insufficient"))
        self.assertEqual(result["code"], "C")

    def test_next_evidence_need_present_is_c(self):
        result = rules.decide_verdict(attempt(next_evidence_need="需要迁移确认"))
        self.assertEqual(result["code"], "C")


class TestSingleStrongB(unittest.TestCase):
    def test_single_strong_no_history_is_b(self):  # T1
        result = rules.decide_verdict(attempt())
        self.assertEqual(result["code"], "B")
        self.assertTrue(result["is_strong"])
        self.assertIn("C1", result["attrs"]["failed"])

    def test_correct_ratio_60_to_85_is_b(self):  # R5
        result = rules.decide_verdict(attempt(score_points=7, max_points=10))
        self.assertEqual(result["code"], "B")
        self.assertFalse(result["is_strong"])

    def test_exact_ratio_060_is_b(self):  # 0.60 boundary belongs to B band
        result = rules.decide_verdict(attempt(score_points=6, max_points=10))
        self.assertEqual(result["code"], "B")

    def test_ratio_0849_is_b(self):
        result = rules.decide_verdict(attempt(score_points=17, max_points=20))
        self.assertEqual(result["code"], "B")

    def test_exact_ratio_085_single_is_b(self):  # 0.85 boundary: strong, but AGG fails alone
        result = rules.decide_verdict(attempt(score_points=17, max_points=20))
        self.assertEqual(result["code"], "B")
        self.assertTrue(result["is_strong"])


class TestPromoteA(unittest.TestCase):
    def test_two_strong_full_conditions_is_a(self):  # T2 / C1-C6 all satisfied
        window = two_strong_window()
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "A")
        self.assertTrue(result["is_strong"])
        self.assertEqual(result["attrs"]["failed"], [])

    def test_single_strong_never_a(self):  # C1 fail
        window = [attempt()]
        result = rules.decide_verdict(window[0], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C1", result["attrs"]["failed"])

    def test_same_fingerprint_fails_c2(self):
        window = [
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-01"),
            attempt(attempt_id="a2", structure_fingerprint="fp_core",
                    purpose_role="confirmation_transfer", created_at="2026-08-02"),
        ]
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C2", result["attrs"]["failed"])

    def test_missing_transfer_role_fails_c3(self):
        window = [
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-01"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_core", created_at="2026-08-02"),
        ]
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C3", result["attrs"]["failed"])

    def test_unrepaired_weakness_after_last_strong_fails_c4(self):
        # A C/D verdict newer than every strong verdict blocks A.
        window = [
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-01"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_transfer", created_at="2026-08-02"),
            attempt(attempt_id="a3", result="correct", score_points=9, max_points=10,
                    reasoning_soundness="unsound", created_at="2026-08-03"),
        ]
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C4", result["attrs"]["failed"])

    def test_repaired_weakness_allows_a(self):  # C4 positive: C/D followed by strongs
        window = [
            attempt(attempt_id="a0", result="correct", score_points=9, max_points=10,
                    reasoning_soundness="unsound", created_at="2026-08-01"),
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-02"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_transfer", created_at="2026-08-03"),
        ]
        result = rules.decide_verdict(window[2], window)
        self.assertEqual(result["code"], "A")

    def test_same_day_fails_c5(self):  # T3
        window = two_strong_window(day1="2026-08-01", day2="2026-08-01")
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C5", result["attrs"]["failed"])

    def test_window_ratio_below_085_fails_c6(self):
        window = [
            attempt(attempt_id="a0", result="wrong", score_points=3, max_points=10,
                    created_at="2026-08-01"),
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-02"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_transfer", created_at="2026-08-03"),
        ]
        result = rules.decide_verdict(window[2], window)
        self.assertEqual(result["code"], "B")
        self.assertIn("C6", result["attrs"]["failed"])

    def test_exact_085_window_ratio_is_a(self):  # C6 boundary: ≥ 0.85
        window = [
            attempt(attempt_id="a1", score_points=17, max_points=20,
                    structure_fingerprint="fp_core", purpose_role="confirmation_core",
                    created_at="2026-08-01"),
            attempt(attempt_id="a2", score_points=17, max_points=20,
                    structure_fingerprint="fp_transfer", purpose_role="confirmation_transfer",
                    created_at="2026-08-02"),
        ]
        result = rules.decide_verdict(window[1], window)
        self.assertEqual(result["code"], "A")


class TestNoChange(unittest.TestCase):
    def test_practice_purpose_is_no_change(self):  # T7
        result = rules.decide_verdict(attempt(purpose="practice"))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_gate_failed_is_no_change(self):  # T7
        result = rules.decide_verdict(attempt(gate_passed=False))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_hint_exposed_is_no_change(self):
        result = rules.decide_verdict(attempt(hint_policy="hint_after_wrong"))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_not_mastery_eligible_is_no_change(self):
        result = rules.decide_verdict(attempt(mastery_update_eligible=False))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_manual_evidence_is_no_change(self):
        result = rules.decide_verdict(attempt(is_manual=True))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_voice_not_verifiable_is_no_change(self):
        result = rules.decide_verdict(attempt(voice_verifiable=False))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_analysis_invalid_is_no_change(self):
        result = rules.decide_verdict(attempt(analysis_valid=False))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_correct_attempt_without_reasoning_info_is_no_change(self):
        # 推理缺口信息缺失 → 不产判定事件（"没测过 ≠ 薄弱"）
        result = rules.decide_verdict(attempt(
            reasoning_soundness=None, evidence_strength=None, next_evidence_need=None,
        ))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_no_change_is_never_strong(self):
        result = rules.decide_verdict(attempt(purpose="practice"))
        self.assertEqual(result["code"], "NO_CHANGE")
        self.assertFalse(result["is_strong"])


class TestT8SingleCDoesNotImmediatelyDowngrade(unittest.TestCase):
    def test_single_c_verdict_produced_on_previously_a_node(self):
        # 判定核心只产出 verdict=C；"保持 A / 计数+1" 属 §2.3 迁移层（M2.5-2）。
        ev = attempt(attempt_id="later", result="wrong", score_points=2, max_points=10)
        result = rules.decide_verdict(ev)
        self.assertEqual(result["code"], "C")
        self.assertEqual(result["attrs"]["reason_code"], "wrong")


class TestThresholdBoundaries(unittest.TestCase):
    def test_ratio_0599_is_c(self):
        result = rules.decide_verdict(attempt(score_points=599, max_points=1000))
        self.assertEqual(result["code"], "C")

    def test_ratio_085_exact_is_strong(self):
        self.assertTrue(rules.is_strong_evidence(attempt(score_points=17, max_points=20)))

    def test_ratio_0849_is_not_strong(self):
        self.assertFalse(rules.is_strong_evidence(attempt(score_points=16, max_points=19)))

    def test_ratio_060_exact_is_not_weak(self):
        self.assertNotEqual(
            rules.decide_verdict(attempt(score_points=6, max_points=10))["code"], "C"
        )

    def test_ratio_0599_weak_band(self):
        self.assertEqual(
            rules.decide_verdict(attempt(score_points=599, max_points=1000))["code"], "C"
        )


class TestHelpers(unittest.TestCase):
    def test_is_strong_evidence_positive(self):
        self.assertTrue(rules.is_strong_evidence(attempt()))

    def test_is_strong_evidence_negative_on_gap(self):
        self.assertFalse(rules.is_strong_evidence(attempt(reasoning_soundness="unclear")))

    def test_has_reasoning_gap_soundness(self):
        self.assertTrue(rules.has_reasoning_gap(attempt(reasoning_soundness="incomplete")))

    def test_has_reasoning_gap_strength(self):
        self.assertTrue(rules.has_reasoning_gap(attempt(evidence_strength="insufficient")))

    def test_has_reasoning_gap_next_need(self):
        self.assertTrue(rules.has_reasoning_gap(attempt(next_evidence_need="x")))

    def test_no_reasoning_gap_when_sound(self):
        self.assertFalse(rules.has_reasoning_gap(attempt()))

    def test_window_ratio(self):
        window = [
            attempt(score_points=10, max_points=10),
            attempt(attempt_id="a2", score_points=5, max_points=10),
        ]
        self.assertAlmostEqual(rules.window_ratio(window), 0.75)

    def test_aggregate_conditions_reports_all_six(self):
        window = two_strong_window()
        conds = rules.aggregate_conditions(window[1], window)
        self.assertEqual(set(conds.keys()), {"C1", "C2", "C3", "C4", "C5", "C6"})
        self.assertTrue(all(conds.values()))

    def test_is_eligible_defaults_true(self):
        self.assertTrue(rules.is_eligible(attempt()))

    def test_is_eligible_manual_false(self):
        self.assertFalse(rules.is_eligible(attempt(is_manual=True)))

    def test_mastery_verdict_alias_matches_decide_verdict(self):
        ev = attempt()
        self.assertEqual(rules.mastery_verdict(ev), rules.decide_verdict(ev))


if __name__ == "__main__":
    unittest.main()
