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


# ---------------------------------------------------------------------------
# M2.5 part 2: §2.3 unique counter + state transitions (anchors T8-T13)
# ---------------------------------------------------------------------------
#
# Unique counter (proposal §2.3): consecutive C/D judgment events only,
# A/B verdict resets, NO_CHANGE skipped (neither counted nor breaking),
# manual (M1) events never counted, count reaching CD_COUNTER_LIMIT=3 fires
# the downgrade/recheck signal and resets to 0.
#
# Transition table (proposal §2.3): A/B -> C only after 3 consecutive C/D
# (no A->B->C ladder); C -> B requires >=2 strong in the window while D -> B
# needs a single strong; a single strong never overwrites A; blocking
# evidence (verdict=D from R1) jumps A/B/C straight to D.

STRONG = attempt()


def cd_event(verdict, **overrides):
    """A judgment-event dict for the counter functions."""
    base = {"verdict": verdict, "is_manual": False}
    base.update(overrides)
    return base


class TestCDCounterFeed(unittest.TestCase):
    def test_single_c_counts_one(self):  # T8 counter part
        result = rules.feed_cd_counter(0, "C")
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["triggered"])

    def test_d_counts_like_c(self):
        result = rules.feed_cd_counter(1, "D")
        self.assertEqual(result["count"], 2)
        self.assertFalse(result["triggered"])

    def test_third_consecutive_cd_triggers_and_resets(self):
        result = rules.feed_cd_counter(2, "C")
        self.assertEqual(result["count"], 0)
        self.assertTrue(result["triggered"])

    def test_verdict_a_resets_counter(self):
        result = rules.feed_cd_counter(2, "A")
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["triggered"])

    def test_verdict_b_resets_counter(self):
        result = rules.feed_cd_counter(2, "B")
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["triggered"])

    def test_no_change_is_skipped_not_counted(self):
        result = rules.feed_cd_counter(2, "NO_CHANGE")
        self.assertEqual(result["count"], 2)
        self.assertFalse(result["triggered"])

    def test_no_change_does_not_break_streak(self):
        # C -> NO_CHANGE -> C keeps the streak alive.
        first = rules.feed_cd_counter(0, "C")
        middle = rules.feed_cd_counter(first["count"], "NO_CHANGE")
        last = rules.feed_cd_counter(middle["count"], "C")
        self.assertEqual(last["count"], 2)

    def test_manual_event_is_not_counted(self):
        result = rules.feed_cd_counter(0, "C", manual=True)
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["triggered"])

    def test_manual_event_does_not_break_streak(self):
        first = rules.feed_cd_counter(0, "C")
        middle = rules.feed_cd_counter(first["count"], "C", manual=True)
        last = rules.feed_cd_counter(middle["count"], "C")
        self.assertEqual(last["count"], 2)

    def test_count_resumes_after_trigger(self):
        # C,C,C -> trigger resets; a 4th C starts a fresh streak at 1.
        result = rules.feed_cd_counter(0, "C")
        result = rules.feed_cd_counter(result["count"], "C")
        result = rules.feed_cd_counter(result["count"], "C")
        self.assertTrue(result["triggered"])
        self.assertEqual(result["count"], 0)
        result = rules.feed_cd_counter(result["count"], "C")
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["triggered"])

    def test_unknown_verdict_raises(self):
        with self.assertRaises(ValueError):
            rules.feed_cd_counter(0, "X")

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            rules.feed_cd_counter(-1, "C")


class TestCDCounterScan(unittest.TestCase):
    def test_empty_sequence_is_zero(self):
        self.assertEqual(rules.cd_counter([]), 0)

    def test_two_consecutive_c(self):
        events = [cd_event("C"), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 2)

    def test_three_consecutive_c_reset_to_zero(self):
        events = [cd_event("C"), cd_event("C"), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 0)

    def test_four_consecutive_c_leave_one_after_trigger(self):
        events = [cd_event("C")] * 4
        self.assertEqual(rules.cd_counter(events), 1)

    def test_no_change_events_are_skipped(self):
        events = [cd_event("C"), cd_event("NO_CHANGE"), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 2)

    def test_a_verdict_clears_streak(self):
        events = [cd_event("C"), cd_event("C"), cd_event("A")]
        self.assertEqual(rules.cd_counter(events), 0)

    def test_b_verdict_clears_streak_then_c_restarts(self):
        events = [cd_event("C"), cd_event("C"), cd_event("B"), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 1)

    def test_mixed_cd_verdicts_count_together(self):
        events = [cd_event("C"), cd_event("D"), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 0)  # 3 -> trigger -> reset

    def test_manual_events_are_ignored(self):
        events = [
            cd_event("C"),
            cd_event("C", is_manual=True),
            cd_event("C"),
        ]
        self.assertEqual(rules.cd_counter(events), 2)


class TestTransitionContract(unittest.TestCase):
    def test_result_has_contract_fields(self):
        result = rules.transition_status("A", "C")
        for key in ("status", "counter", "recheck", "reason", "reason_code"):
            self.assertIn(key, result)

    def test_invalid_current_status_raises(self):
        with self.assertRaises(ValueError):
            rules.transition_status("E", "C")

    def test_invalid_verdict_raises(self):
        with self.assertRaises(ValueError):
            rules.transition_status("A", "X")


class TestTransitionUnfiled(unittest.TestCase):
    def test_unfiled_verdict_a_files_a(self):
        result = rules.transition_status(None, "A")
        self.assertEqual(result["status"], "A")

    def test_unfiled_verdict_b_files_b(self):
        result = rules.transition_status(None, "B")
        self.assertEqual(result["status"], "B")

    def test_unfiled_verdict_c_files_c(self):
        result = rules.transition_status(None, "C")
        self.assertEqual(result["status"], "C")

    def test_unfiled_verdict_d_files_d(self):
        result = rules.transition_status(None, "D")
        self.assertEqual(result["status"], "D")

    def test_unfiled_no_change_stays_unfiled(self):
        result = rules.transition_status(None, "NO_CHANGE")
        self.assertIsNone(result["status"])
        self.assertFalse(result["recheck"])


class TestTransitionA(unittest.TestCase):
    def test_single_c_keeps_a_counter_one(self):  # T8
        result = rules.transition_status("A", "C", counter=0)
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 1)
        self.assertFalse(result["recheck"])

    def test_third_consecutive_cd_downgrades_to_c(self):  # T9
        result = rules.transition_status("A", "C", counter=2)
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["counter"], 0)
        self.assertTrue(result["recheck"])
        self.assertEqual(result["reason_code"], "cd_trigger_downgrade")

    def test_blocking_verdict_beats_counter_on_a(self):
        # verdict=D (R1 blocking) jumps A -> D even when it would push the
        # counter to 3: the blocking column wins over the counter column.
        result = rules.transition_status("A", "D", counter=2)
        self.assertEqual(result["status"], "D")

    def test_a_keeps_through_counter_one_and_two(self):
        # A row counter column: 连续计数+1 直到 3, 之前保持 A.
        one = rules.transition_status("A", "C", counter=0)
        self.assertEqual(one["status"], "A")
        self.assertEqual(one["counter"], 1)
        two = rules.transition_status("A", "C", counter=one["counter"])
        self.assertEqual(two["status"], "A")
        self.assertEqual(two["counter"], 2)

    def test_verdict_a_keeps_a(self):
        result = rules.transition_status("A", "A")
        self.assertEqual(result["status"], "A")

    def test_single_strong_does_not_overwrite_a(self):
        # verdict=B (single strong, AGG incomplete) never demotes A.
        result = rules.transition_status("A", "B", window=[STRONG])
        self.assertEqual(result["status"], "A")

    def test_verdict_b_r5_keeps_a(self):
        result = rules.transition_status("A", "B")
        self.assertEqual(result["status"], "A")

    def test_blocking_evidence_jumps_to_d(self):
        result = rules.transition_status("A", "D")
        self.assertEqual(result["status"], "D")

    def test_no_change_keeps_a_and_counter(self):
        result = rules.transition_status("A", "NO_CHANGE", counter=2)
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 2)
        self.assertFalse(result["recheck"])


class TestTransitionB(unittest.TestCase):
    def test_verdict_a_promotes_to_a(self):
        result = rules.transition_status("B", "A")
        self.assertEqual(result["status"], "A")

    def test_verdict_a_resets_counter_on_promotion(self):
        # A/B verdicts clear the streak (§2.3): promotion resets the counter.
        result = rules.transition_status("B", "A", counter=2)
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 0)

    def test_verdict_b_keeps_b(self):
        result = rules.transition_status("B", "B")
        self.assertEqual(result["status"], "B")

    def test_single_c_keeps_b_counter_one(self):
        result = rules.transition_status("B", "C", counter=0)
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["counter"], 1)

    def test_third_consecutive_cd_downgrades_b_to_c(self):
        result = rules.transition_status("B", "C", counter=2)
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["counter"], 0)
        self.assertTrue(result["recheck"])

    def test_blocking_evidence_jumps_to_d(self):
        result = rules.transition_status("B", "D")
        self.assertEqual(result["status"], "D")


class TestTransitionC(unittest.TestCase):
    def test_single_strong_keeps_c(self):  # T10
        result = rules.transition_status("C", "B", window=[STRONG])
        self.assertEqual(result["status"], "C")

    def test_two_strong_in_window_promotes_to_b(self):  # T11
        result = rules.transition_status("C", "B", window=two_strong_window())
        self.assertEqual(result["status"], "B")

    def test_verdict_a_promotes_directly_to_a(self):
        result = rules.transition_status("C", "A")
        self.assertEqual(result["status"], "A")

    def test_verdict_b_with_two_strong_history_but_r5_current_promotes(self):
        # Window condition is on strong count, not on the current event being strong.
        window = two_strong_window() + [
            attempt(attempt_id="a3", score_points=7, max_points=10, created_at="2026-08-03")
        ]
        result = rules.transition_status("C", "B", window=window)
        self.assertEqual(result["status"], "B")

    def test_single_c_keeps_c_counter_one(self):
        result = rules.transition_status("C", "C", counter=0)
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["counter"], 1)
        self.assertFalse(result["recheck"])

    def test_third_consecutive_cd_triggers_recheck_only(self):
        # C stays C; the 3rd consecutive C/D fires the recheck signal, not a downgrade.
        result = rules.transition_status("C", "C", counter=2)
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["counter"], 0)
        self.assertTrue(result["recheck"])

    def test_blocking_evidence_jumps_to_d(self):
        result = rules.transition_status("C", "D")
        self.assertEqual(result["status"], "D")


class TestTransitionD(unittest.TestCase):
    def test_single_strong_promotes_to_b(self):  # T12
        result = rules.transition_status("D", "B", window=[STRONG])
        self.assertEqual(result["status"], "B")

    def test_verdict_a_promotes_to_b_not_a(self):  # D never jumps to A
        result = rules.transition_status("D", "A")
        self.assertEqual(result["status"], "B")

    def test_verdict_b_r5_promotes_to_b(self):
        result = rules.transition_status("D", "B")
        self.assertEqual(result["status"], "B")

    def test_verdict_c_keeps_d(self):
        result = rules.transition_status("D", "C")
        self.assertEqual(result["status"], "D")

    def test_verdict_d_keeps_d(self):
        result = rules.transition_status("D", "D")
        self.assertEqual(result["status"], "D")


class TestTransitionManualM1(unittest.TestCase):
    def test_manual_evidence_is_no_change_and_never_downgrades(self):  # T13
        # M1 手动错题不产判定事件: decide_verdict -> NO_CHANGE, transition no-op.
        ev = attempt(is_manual=True)
        verdict = rules.decide_verdict(ev)
        self.assertEqual(verdict["code"], "NO_CHANGE")
        result = rules.transition_status("A", verdict["code"], counter=0)
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 0)


# ---------------------------------------------------------------------------
# M2.5 part 3: §2.4 retest intervals + §3 manual evidence M0/M1 (anchors
# T16/T17/T19-T23; T18 = db-layer, T14/T15 = LLM tightening, both out of scope
# here). Interpretation notes (proposal ambiguities, documented):
#
# next_retest_at(depth, verdict, b_count, now):
#   - `depth` = number of verdict=A judgment events since the node's most
#     recent status-change-to-A anchor (cap 4), i.e. the value BEFORE this
#     event; `days` is always looked up with the INCOMING depth so the
#     achievement event itself schedules +1 day (T16: A 达成 -> 次日复测 1 天),
#     then each further verdict=A schedules intervals[new depth]
#     (3 -> 7 -> 14 -> 30, 30 capped). This is the reading that reproduces the
#     anchor sequence [1,3,7,14,30] exactly.
#   - verdict=A: new_depth = min(depth+1, 4); days = intervals[min(depth, 4)].
#   - verdict=B: new_depth unchanged; depth>=1 -> days = intervals[depth]
#     (T21 按当前间隔重排); depth=0 -> days = 3 if b_count+1 >= 3 else 1,
#     where b_count = consecutive-B count BEFORE this event (T22: the 3rd
#     consecutive B -> 3 days).
#   - verdict=C/D: reset depth 0, days = 1 (T17).
#   - NO_CHANGE: no-op (never stored -> never reschedules).
#   - next_retest_at (absolute) = _as_date(now) + days when `now` is given.
#
# manual_entry(mode, count): M0 -> always emit the system-internal retest
#   signal, zero judgment-side effect (not counted, no recheck); M1 -> retest
#   signal + action-layer independent count (threshold 3, same number as the
#   unique counter by design §4), 3rd consecutive M1 -> recheck + reset.
#   Neither mode ever produces a judgment event or downgrades (M1 batch
#   backfill is a reclassification into the same M1 path; carrier is M4).
# ---------------------------------------------------------------------------

FIXED_NOW = "2026-08-10"


class TestRetestIntervals(unittest.TestCase):
    def test_interval_table_is_1_3_7_14_30(self):  # §2.4 / T16
        self.assertEqual(rules.RETEST_INTERVALS_DAYS, [1, 3, 7, 14, 30])

    def test_a_at_depth0_schedules_next_day(self):  # T16: A 达成 -> 次日复测 1 天
        from datetime import date
        result = rules.next_retest_at(0, "A", now=FIXED_NOW)
        self.assertEqual(result["new_depth"], 1)
        self.assertEqual(result["days"], 1)
        self.assertEqual(result["next_retest_at"], date(2026, 8, 11))

    def test_a_progression_3_7_14(self):  # T16: 每次窗口级复测通过 -> 深度+1
        self.assertEqual(rules.next_retest_at(1, "A", now=FIXED_NOW)["days"], 3)
        self.assertEqual(rules.next_retest_at(2, "A", now=FIXED_NOW)["days"], 7)
        self.assertEqual(rules.next_retest_at(3, "A", now=FIXED_NOW)["days"], 14)
        self.assertEqual(rules.next_retest_at(3, "A", now=FIXED_NOW)["new_depth"], 4)

    def test_a_capped_at_30_days(self):  # T16: 30 天通过后维持 30 天
        result = rules.next_retest_at(4, "A", now=FIXED_NOW)
        self.assertEqual(result["days"], 30)
        self.assertEqual(result["new_depth"], 4)

    def test_a_resets_b_count(self):
        result = rules.next_retest_at(0, "A", b_count=2)
        self.assertEqual(result["b_count"], 0)

    def test_b_at_depth1_repeats_current_interval(self):  # T21
        from datetime import date
        result = rules.next_retest_at(2, "B", now=FIXED_NOW)
        self.assertEqual(result["new_depth"], 2)  # 深度不变
        self.assertEqual(result["days"], 7)  # 按当前间隔重排
        self.assertEqual(result["next_retest_at"], date(2026, 8, 17))

    def test_b_at_depth0_below_3_uses_one_day(self):  # T22 (b_count<3 -> 1 天)
        result = rules.next_retest_at(0, "B", b_count=0, now=FIXED_NOW)
        self.assertEqual(result["new_depth"], 0)
        self.assertEqual(result["days"], 1)

    def test_b_at_depth0_third_consecutive_uses_three_days(self):  # T22 (连续 B>=3 -> 3 天)
        result = rules.next_retest_at(0, "B", b_count=2, now=FIXED_NOW)
        self.assertEqual(result["new_depth"], 0)
        self.assertEqual(result["days"], 3)

    def test_b_after_trigger_stays_three_days(self):  # T22 boundary: b_count>=3 stays 3
        result = rules.next_retest_at(0, "B", b_count=3)
        self.assertEqual(result["days"], 3)

    def test_b_increments_b_count(self):
        result = rules.next_retest_at(1, "B", b_count=1)
        self.assertEqual(result["b_count"], 2)

    def test_c_resets_depth_and_interval(self):  # T17
        from datetime import date
        result = rules.next_retest_at(3, "C", b_count=4, now=FIXED_NOW)
        self.assertEqual(result["new_depth"], 0)
        self.assertEqual(result["days"], 1)
        self.assertEqual(result["b_count"], 0)
        self.assertEqual(result["next_retest_at"], date(2026, 8, 11))

    def test_d_resets_depth_and_interval(self):  # T17
        result = rules.next_retest_at(2, "D")
        self.assertEqual(result["new_depth"], 0)
        self.assertEqual(result["days"], 1)

    def test_no_change_is_noop(self):
        result = rules.next_retest_at(2, "NO_CHANGE", b_count=1)
        self.assertEqual(result["new_depth"], 2)
        self.assertEqual(result["days"], 0)
        self.assertEqual(result["b_count"], 1)

    def test_invalid_depth_raises(self):
        with self.assertRaises(ValueError):
            rules.next_retest_at(-1, "A")
        with self.assertRaises(ValueError):
            rules.next_retest_at("x", "A")

    def test_invalid_verdict_raises(self):
        with self.assertRaises(ValueError):
            rules.next_retest_at(0, "X")

    def test_invalid_b_count_raises(self):
        with self.assertRaises(ValueError):
            rules.next_retest_at(0, "B", b_count=-1)

    def test_now_accepts_datetime_and_date(self):
        from datetime import date, datetime
        dt_result = rules.next_retest_at(0, "A", now=datetime(2026, 8, 10, 12, 30))
        self.assertEqual(dt_result["next_retest_at"], date(2026, 8, 11))
        d_result = rules.next_retest_at(0, "A", now=date(2026, 8, 10))
        self.assertEqual(d_result["next_retest_at"], date(2026, 8, 11))


class TestRetestAntiDeathLoop(unittest.TestCase):
    def test_single_strong_retest_is_b_not_a(self):  # T23: 单题级 A 不存在
        # 单条 correct+exp>=2+sound、无历史 strong: 窗口 AGG(C1) 不满足 -> verdict=B。
        result = rules.decide_verdict(attempt())
        self.assertEqual(result["code"], "B")

    def test_b_retest_does_not_advance_depth(self):  # T23: 无每日复测死循环
        # 单题复测产出 B -> next_retest_at 深度不推进（不会 1->2->3 天递增）。
        first = rules.next_retest_at(0, "B", b_count=0)
        self.assertEqual(first["new_depth"], 0)
        self.assertEqual(first["days"], 1)
        second = rules.next_retest_at(0, "B", b_count=first["b_count"])
        self.assertEqual(second["new_depth"], 0)
        self.assertEqual(second["days"], 1)  # b_count 未达 3, 维持 1 天, 深度不涨

    def test_a_depth_advance_requires_window_level_a(self):
        # 深度推进只在窗口级 verdict=A 之后: 单题 B 之后即便再来一条 strong,
        # 只要 AGG 仍不满足就是 B, 深度保持 0。
        window = two_strong_window(day1="2026-08-01", day2="2026-08-01")  # 同日 -> C5 不满足
        retest = rules.decide_verdict(window[1], window)
        self.assertEqual(retest["code"], "B")
        schedule = rules.next_retest_at(0, retest["code"], b_count=1)
        self.assertEqual(schedule["new_depth"], 0)


class TestManualEvidence(unittest.TestCase):
    def test_m0_triggers_retest_only(self):  # T19
        result = rules.manual_entry("M0", count=2)
        self.assertTrue(result["retest"])  # 触发一次系统内复测（教学动作）
        self.assertFalse(result["counted"])  # M0 不计数
        self.assertEqual(result["count"], 2)  # 动作层计数不受影响
        self.assertFalse(result["recheck"])

    def test_m0_zero_judgment_side_effect(self):  # T19: 判定侧零作用
        result = rules.manual_entry("M0")
        self.assertFalse(result["judgment_event"])  # 不产判定事件
        self.assertFalse(result["downgrade"])  # 不降级
        self.assertEqual(result["reason_code"], "m0_retest_only")

    def test_m1_first_counts_one(self):
        result = rules.manual_entry("M1", count=0)
        self.assertTrue(result["retest"])
        self.assertTrue(result["counted"])
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["recheck"])

    def test_m1_second_counts_two(self):
        result = rules.manual_entry("M1", count=1)
        self.assertEqual(result["count"], 2)
        self.assertFalse(result["recheck"])

    def test_m1_third_triggers_recheck_and_resets(self):  # T20
        result = rules.manual_entry("M1", count=2)
        self.assertTrue(result["recheck"])
        self.assertEqual(result["count"], 0)  # 触发回查并清零
        self.assertTrue(result["retest"])

    def test_m1_fresh_streak_after_trigger(self):
        result = rules.manual_entry("M1", count=0)
        self.assertEqual(result["count"], 1)

    def test_m1_never_downgrades_or_writes_judgment(self):  # T20: 状态不变
        result = rules.manual_entry("M1", count=2)
        self.assertFalse(result["judgment_event"])
        self.assertFalse(result["downgrade"])  # 永不直接降档/D

    def test_m1_count_is_isolated_from_unique_counter(self):  # T20: 与唯一计数器隔离
        # 3 条 M1 触发动作层回查, 但 §2.3 唯一计数器不受影响 (manual 事件不计入)。
        for i in range(3):
            rules.manual_entry("M1", count=i)
        events = [cd_event("C", is_manual=True) for _ in range(3)]
        self.assertEqual(rules.cd_counter(events), 0)
        # 等价单事件视角: manual=True 的 C 不进唯一计数器。
        self.assertEqual(rules.feed_cd_counter(2, "C", manual=True)["count"], 2)

    def test_m1_does_not_enter_cd_counter_semantics(self):
        # M1 的"3 条触发"不改变唯一计数器派生值: 3 条 M1 事件后 cd_counter 仍为 0。
        result = rules.manual_entry("M1", count=2)
        self.assertTrue(result["recheck"])
        self.assertEqual(rules.cd_counter([cd_event("C", is_manual=True)] * 3), 0)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            rules.manual_entry("M2")

    def test_invalid_count_raises(self):
        with self.assertRaises(ValueError):
            rules.manual_entry("M1", count=-1)

    def test_recheck_limit_equals_unique_counter_limit(self):  # §4: 同阈值 3
        self.assertEqual(rules.MANUAL_RECHECK_LIMIT, rules.CD_COUNTER_LIMIT)


# ---------------------------------------------------------------------------
# M2.5 part 4: §4 over-diagnosis gates + §5 LLM tightening boundary
# (anchors T14/T15 + gate linkage/isolation; proposal §4/§5)
# ---------------------------------------------------------------------------
#
# Gate #1 diagnosis_budget(question_count, limit=5): one diagnostic session on
# a node asks at most `limit` questions; beyond that the session switches to
# the mainline (超限转主线). The judgment rules never perceive the question
# count — the verdict functions consume only the attempts within the compliant
# window (the wiring layer passes the budgeted slice as `window`). "已达标"
# (mastered) = the compliant window's latest verdict is A (window-level AGG,
# §2.2): the session stops early, before the cap.
#
# Gate #2 recheck_depth_limit(depth, node_status, limit=3): the judgment side
# never executes the recheck (回查) — this pure rule tells the recheck driver
# at which chain depth to narrow. Interpretation (proposal ambiguity,
# documented): within the limit (depth <= 3) the prereq chain is walked in
# full; beyond it only C/D (weak) nodes are examined ("默认 3 层，超过只查
# C/D 节点" — a narrowing, not a hard stop), so critical weak nodes are still
# found without unbounded chain walking. Unfiled nodes are never rechecked
# beyond the limit (未建档不阻塞, design:197).
#
# Gate #3 unique counter (M2.5-2) is the §4 alignment point: 连续 3 次 C/D
# 同数同义 (CD_COUNTER_LIMIT == MANUAL_RECHECK_LIMIT == 3). Linkage: the
# counter reaching 3 fires downgrade + recheck + reset in one shot. Isolation:
# 状态降级仅由系统判定事件驱动 — M1 manual entries only drive the action-layer
# count (recheck), never the archive.
#
# §5 LLM tightening: the evaluation recommendation is规约进错因归类 (evidence
# interpretation), not a third LLM role; the final verdict is decided by the
# §2.2 deterministic rules. apply_llm_tightening(verdict, recommendation) may
# only push the verdict toward the conservative end (只收紧不放宽): weak/blocked
# demote (B->C, B->D, A->C) while stable_for_now/emerging/likely_stable can
# never promote (T14/T15). deterministic_fallback(...) produces the 8/10-score
# weak judgment when the LLM path is unavailable / low-confidence / mock /
# replay — judgment proceeds and state updates are never interrupted, but the
# fallback never yields A ("确定性路径只产 weak/emerging", §1 fact 6).


class TestDiagnosisBudget(unittest.TestCase):
    def test_default_limit_is_5(self):  # 闸门 #1 默认 5 题
        self.assertEqual(rules.DIAGNOSIS_QUESTION_LIMIT, 5)

    def test_below_limit_continues(self):
        result = rules.diagnosis_budget(2)
        self.assertEqual(result["decision"], "continue")
        self.assertTrue(result["within_budget"])

    def test_last_question_within_budget_continues(self):  # 边界: 第 4 题仍可继续
        result = rules.diagnosis_budget(4)
        self.assertEqual(result["decision"], "continue")
        self.assertTrue(result["within_budget"])

    def test_at_limit_switches_to_mainline(self):  # 第 5 题: 超限转主线
        result = rules.diagnosis_budget(5)
        self.assertEqual(result["decision"], "switch_mainline")
        self.assertFalse(result["within_budget"])
        self.assertEqual(result["reason_code"], "exceeded_switch_mainline")

    def test_over_limit_switches_to_mainline(self):
        result = rules.diagnosis_budget(7)
        self.assertEqual(result["decision"], "switch_mainline")
        self.assertFalse(result["within_budget"])

    def test_mastered_stops_early(self):  # 已达标: 窗口内 verdict=A -> 提前结束
        result = rules.diagnosis_budget(2, mastered=True)
        self.assertEqual(result["decision"], "mastered")
        self.assertTrue(result["within_budget"])

    def test_mastered_wins_at_cap(self):
        result = rules.diagnosis_budget(5, mastered=True)
        self.assertEqual(result["decision"], "mastered")

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            rules.diagnosis_budget(-1)

    def test_zero_limit_raises(self):
        with self.assertRaises(ValueError):
            rules.diagnosis_budget(1, limit=0)

    def test_result_has_contract_fields(self):
        result = rules.diagnosis_budget(1)
        for key in ("decision", "within_budget", "question_count", "limit",
                    "reason_code", "reason"):
            self.assertIn(key, result)


class TestRecheckDepthLimit(unittest.TestCase):
    def test_default_limit_is_3(self):  # 闸门 #2 默认 3 层
        self.assertEqual(rules.RECHECK_DEPTH_LIMIT, 3)

    def test_within_limit_full_recheck(self):
        result = rules.recheck_depth_limit(1)
        self.assertTrue(result["within_limit"])
        self.assertFalse(result["only_cd"])
        self.assertTrue(result["should_recheck"])
        self.assertEqual(result["reason_code"], "full_recheck")

    def test_at_limit_still_full_recheck(self):  # 边界: 深度 3 层内全量回查
        result = rules.recheck_depth_limit(3)
        self.assertTrue(result["within_limit"])
        self.assertTrue(result["should_recheck"])

    def test_beyond_limit_cd_node_rechecked(self):  # 超过 3 层: 只查 C/D 节点
        result = rules.recheck_depth_limit(4, node_status="C")
        self.assertFalse(result["within_limit"])
        self.assertTrue(result["only_cd"])
        self.assertTrue(result["should_recheck"])
        self.assertEqual(result["reason_code"], "cd_only")

    def test_beyond_limit_d_node_rechecked(self):
        result = rules.recheck_depth_limit(4, node_status="D")
        self.assertTrue(result["should_recheck"])

    def test_beyond_limit_b_node_not_rechecked(self):  # 超过 3 层: B 节点不查
        result = rules.recheck_depth_limit(4, node_status="B")
        self.assertFalse(result["should_recheck"])

    def test_beyond_limit_a_node_not_rechecked(self):
        result = rules.recheck_depth_limit(4, node_status="A")
        self.assertFalse(result["should_recheck"])

    def test_beyond_limit_unfiled_not_rechecked(self):  # 未建档不阻塞 (design:197)
        result = rules.recheck_depth_limit(4, node_status=None)
        self.assertFalse(result["should_recheck"])

    def test_depth_zero_raises(self):
        with self.assertRaises(ValueError):
            rules.recheck_depth_limit(0)

    def test_invalid_node_status_raises(self):
        with self.assertRaises(ValueError):
            rules.recheck_depth_limit(4, node_status="E")

    def test_result_has_contract_fields(self):
        result = rules.recheck_depth_limit(1)
        for key in ("depth", "limit", "within_limit", "only_cd",
                    "should_recheck", "reason_code", "reason"):
            self.assertIn(key, result)


class TestGate3UniqueCounterAlignment(unittest.TestCase):
    def test_gate3_threshold_same_number_as_proposal(self):  # §4: 连续 3 次同数同义
        self.assertEqual(rules.CD_COUNTER_LIMIT, 3)
        self.assertEqual(rules.MANUAL_RECHECK_LIMIT, rules.CD_COUNTER_LIMIT)

    def test_unique_counter_counts_only_system_events(self):  # §4: 只统计系统内判定事件
        events = [cd_event("C"), cd_event("C", is_manual=True), cd_event("C")]
        self.assertEqual(rules.cd_counter(events), 2)

    def test_counter_three_linkage_downgrade_recheck_reset(self):
        # 联动: 唯一计数器到 3 -> 降级 + 回查 + 清零 (同一判定事件触发)。
        result = rules.transition_status("A", "C", counter=2)
        self.assertEqual(result["status"], "C")
        self.assertTrue(result["recheck"])
        self.assertEqual(result["counter"], 0)
        self.assertEqual(result["reason_code"], "cd_trigger_downgrade")

    def test_m1_action_layer_never_drives_downgrade(self):  # 隔离: M1 只触发回查
        result = rules.manual_entry("M1", count=2)
        self.assertTrue(result["recheck"])
        self.assertFalse(result["downgrade"])
        self.assertFalse(result["judgment_event"])

    def test_state_downgrade_only_by_system_judgment_events(self):  # §4 表头硬约束
        # 3 条 M1 (动作层计数到 3) 后节点状态仍保持 A; 唯一计数器仍为 0。
        c0 = rules.manual_entry("M1", count=0)
        c1 = rules.manual_entry("M1", count=c0["count"])
        c2 = rules.manual_entry("M1", count=c1["count"])
        self.assertTrue(c2["recheck"])
        verdict = rules.decide_verdict(attempt(is_manual=True))
        trans = rules.transition_status("A", verdict["code"], counter=0)
        self.assertEqual(trans["status"], "A")
        self.assertEqual(trans["counter"], 0)
        self.assertEqual(rules.cd_counter([cd_event("C", is_manual=True)] * 3), 0)


class TestLLMTighteningDirection(unittest.TestCase):
    def test_t14_stable_for_now_never_promotes_b_to_a(self):  # T14: AGG 缺双角色
        window = [
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-01"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_core", created_at="2026-08-02"),
        ]
        verdict = rules.decide_verdict(window[1], window)
        self.assertEqual(verdict["code"], "B")
        self.assertIn("C3", verdict["attrs"]["failed"])
        tightened = rules.apply_llm_tightening(verdict, "stable_for_now")
        self.assertEqual(tightened["code"], "B")  # LLM 只收紧不放宽: 不升 A
        self.assertFalse(tightened["attrs"]["tightened"])

    def test_t15_weak_tightens_b_to_c(self):  # T15: weak 而确定性 emerging -> C
        verdict = rules.decide_verdict(attempt())  # 单条 strong, AGG 不满足 -> B
        self.assertEqual(verdict["code"], "B")
        tightened = rules.apply_llm_tightening(verdict, "weak")
        self.assertEqual(tightened["code"], "C")
        self.assertTrue(tightened["attrs"]["tightened"])
        self.assertEqual(tightened["attrs"]["original_code"], "B")
        self.assertFalse(tightened["is_strong"])  # 收紧后不再是 strong

    def test_blocked_tightens_b_to_d(self):
        verdict = rules.decide_verdict(attempt())
        tightened = rules.apply_llm_tightening(verdict, "blocked")
        self.assertEqual(tightened["code"], "D")
        self.assertTrue(tightened["attrs"]["tightened"])

    def test_emerging_never_promotes_c(self):
        verdict = rules.decide_verdict(attempt(result="wrong", score_points=2, max_points=10))
        self.assertEqual(verdict["code"], "C")
        tightened = rules.apply_llm_tightening(verdict, "emerging")
        self.assertEqual(tightened["code"], "C")  # 不能把 C 升为 B
        self.assertFalse(tightened["attrs"]["tightened"])

    def test_likely_stable_never_promotes_c(self):
        verdict = rules.decide_verdict(attempt(result="wrong", score_points=2, max_points=10))
        tightened = rules.apply_llm_tightening(verdict, "likely_stable")
        self.assertEqual(tightened["code"], "C")

    def test_stable_for_now_never_promotes_c(self):
        verdict = rules.decide_verdict(attempt(result="wrong", score_points=2, max_points=10))
        tightened = rules.apply_llm_tightening(verdict, "stable_for_now")
        self.assertEqual(tightened["code"], "C")  # 不能把 C 升为 B/A

    def test_weak_tightens_a_to_c(self):  # 只收紧的最强形态: LLM weak 可把 A 降为 C
        window = two_strong_window()
        verdict = rules.decide_verdict(window[1], window)
        self.assertEqual(verdict["code"], "A")
        tightened = rules.apply_llm_tightening(verdict, "weak")
        self.assertEqual(tightened["code"], "C")
        self.assertTrue(tightened["attrs"]["tightened"])
        self.assertFalse(tightened["is_strong"])

    def test_d_never_changes(self):  # D 是最弱档: 任何 LLM 提示都不改 D
        verdict = rules.decide_verdict(attempt(blocking_evidence=True))
        self.assertEqual(verdict["code"], "D")
        for rec in ("stable_for_now", "emerging", "weak", "blocked"):
            self.assertEqual(rules.apply_llm_tightening(verdict, rec)["code"], "D")

    def test_no_change_never_promoted_by_llm(self):  # 资格是确定性的: LLM 不能无中生有
        verdict = rules.decide_verdict(attempt(purpose="practice"))
        self.assertEqual(verdict["code"], "NO_CHANGE")
        for rec in ("weak", "blocked", "stable_for_now"):
            self.assertEqual(rules.apply_llm_tightening(verdict, rec)["code"], "NO_CHANGE")

    def test_no_update_never_suppresses_real_verdict(self):
        verdict = rules.decide_verdict(attempt())
        self.assertEqual(verdict["code"], "B")
        tightened = rules.apply_llm_tightening(verdict, "no_update")
        self.assertEqual(tightened["code"], "B")  # no_update 不能抹掉有效判定事件
        self.assertFalse(tightened["attrs"]["tightened"])

    def test_same_verdict_kept(self):  # 同判保持
        verdict = rules.decide_verdict(attempt())
        tightened = rules.apply_llm_tightening(verdict, "emerging")
        self.assertEqual(tightened["code"], "B")
        self.assertTrue(tightened["attrs"]["llm_applied"])
        self.assertFalse(tightened["attrs"]["tightened"])

    def test_stable_for_now_on_a_keeps_a(self):  # A 门完全确定性: LLM 只确认不促成
        window = two_strong_window()
        verdict = rules.decide_verdict(window[1], window)
        self.assertEqual(verdict["code"], "A")
        tightened = rules.apply_llm_tightening(verdict, "stable_for_now")
        self.assertEqual(tightened["code"], "A")
        self.assertFalse(tightened["attrs"]["tightened"])

    def test_none_recommendation_is_noop(self):  # LLM 缺失: 不收紧, 原样返回
        verdict = rules.decide_verdict(attempt())
        tightened = rules.apply_llm_tightening(verdict, None)
        self.assertEqual(tightened["code"], "B")
        self.assertFalse(tightened["attrs"]["llm_applied"])

    def test_unknown_recommendation_raises(self):
        with self.assertRaises(ValueError):
            rules.apply_llm_tightening(rules.decide_verdict(attempt()), "great")

    def test_input_verdict_not_mutated(self):  # 纯函数
        verdict = rules.decide_verdict(attempt())
        before = dict(verdict)
        rules.apply_llm_tightening(verdict, "weak")
        self.assertEqual(verdict, before)


class TestLLMFallback(unittest.TestCase):
    def test_high_score_emerging_b(self):
        result = rules.deterministic_fallback(attempt(score_points=9, max_points=10))
        self.assertEqual(result["code"], "B")
        self.assertEqual(result["attrs"]["label"], "emerging")

    def test_low_score_weak_c(self):  # 8/10 分制: score<8 -> weak -> C
        result = rules.deterministic_fallback(attempt(score_points=7, max_points=10))
        self.assertEqual(result["code"], "C")
        self.assertEqual(result["attrs"]["label"], "weak")

    def test_boundary_score_8_is_emerging(self):  # 8/10 边界: >=8 非 weak
        result = rules.deterministic_fallback(attempt(score_points=8, max_points=10))
        self.assertEqual(result["code"], "B")

    def test_severe_gap_is_weak_even_with_high_score(self):
        result = rules.deterministic_fallback(
            attempt(score_points=10, max_points=10), severe_gap=True
        )
        self.assertEqual(result["code"], "C")
        self.assertEqual(result["attrs"]["label"], "weak")

    def test_fallback_never_yields_a(self):  # 确定性路径只产 weak/emerging
        result = rules.deterministic_fallback(attempt(score_points=10, max_points=10))
        self.assertEqual(result["code"], "B")

    def test_fallback_with_window_suppresses_a(self):  # LLM 缺失时历史窗口也不能升 A
        window = two_strong_window()
        verdict = rules.decide_verdict(window[1], window)
        self.assertEqual(verdict["code"], "A")
        fallback = rules.deterministic_fallback(window[1], window)
        self.assertEqual(fallback["code"], "B")  # 兜底降为 B: 不中断但保守

    def test_fallback_consistent_with_verdict_on_weak_evidence(self):
        # 确定性路径与判定规则同向: 答错 -> C (取两者中更弱)。
        ev = attempt(result="wrong", score_points=2, max_points=10)
        result = rules.deterministic_fallback(ev)
        self.assertEqual(result["code"], "C")

    def test_fallback_blocking_is_d(self):
        result = rules.deterministic_fallback(attempt(blocking_evidence=True))
        self.assertEqual(result["code"], "D")

    def test_fallback_ineligible_is_no_change(self):  # 资格是确定性的
        result = rules.deterministic_fallback(attempt(purpose="practice"))
        self.assertEqual(result["code"], "NO_CHANGE")

    def test_fallback_marks_provenance(self):
        result = rules.deterministic_fallback(attempt(), reason="low_confidence")
        self.assertTrue(result["attrs"]["llm_fallback"])
        self.assertEqual(result["attrs"]["fallback_reason"], "low_confidence")

    def test_fallback_default_reason_llm_unavailable(self):
        result = rules.deterministic_fallback(attempt())
        self.assertEqual(result["attrs"]["fallback_reason"], "llm_unavailable")

    def test_fallback_mock_and_replay_reasons(self):
        self.assertTrue(
            rules.deterministic_fallback(attempt(), reason="mock")["attrs"]["llm_fallback"]
        )
        self.assertTrue(
            rules.deterministic_fallback(attempt(), reason="replay")["attrs"]["llm_fallback"]
        )

    def test_invalid_reason_raises(self):
        with self.assertRaises(ValueError):
            rules.deterministic_fallback(attempt(), reason="nope")


class TestLLMConfidenceGate(unittest.TestCase):
    def test_confidence_at_threshold_usable(self):  # 契约置信门槛 0.8
        self.assertTrue(rules.llm_recommendation_usable(0.8))
        self.assertTrue(rules.llm_recommendation_usable(0.95))

    def test_confidence_below_threshold_not_usable(self):
        self.assertFalse(rules.llm_recommendation_usable(0.79))

    def test_missing_confidence_not_usable(self):  # 无置信度 -> 保守走确定性兜底
        self.assertFalse(rules.llm_recommendation_usable(None))

    def test_minimum_confidence_override(self):
        self.assertFalse(rules.llm_recommendation_usable(0.85, minimum_confidence=0.9))


class TestLLMTighteningFlow(unittest.TestCase):
    def test_t14_flow_no_promotion(self):
        # T14 全链路: 判定 B -> LLM stable_for_now 不升 A -> 状态迁移保持。
        window = [
            attempt(attempt_id="a1", structure_fingerprint="fp_core",
                    purpose_role="confirmation_core", created_at="2026-08-01"),
            attempt(attempt_id="a2", structure_fingerprint="fp_transfer",
                    purpose_role="confirmation_core", created_at="2026-08-02"),
        ]
        verdict = rules.decide_verdict(window[1], window)
        verdict = rules.apply_llm_tightening(verdict, "stable_for_now")
        self.assertEqual(verdict["code"], "B")
        trans = rules.transition_status("B", verdict["code"], window=window)
        self.assertEqual(trans["status"], "B")

    def test_t15_flow_tightening_then_counter(self):
        # T15 全链路: LLM weak 把 B 收紧为 C -> 收紧后的判定事件进入唯一计数器。
        verdict = rules.decide_verdict(attempt())
        verdict = rules.apply_llm_tightening(verdict, "weak")
        self.assertEqual(verdict["code"], "C")
        feed = rules.feed_cd_counter(1, verdict["code"])
        self.assertEqual(feed["count"], 2)  # 收紧后的 C 正常计数


if __name__ == "__main__":
    unittest.main()
