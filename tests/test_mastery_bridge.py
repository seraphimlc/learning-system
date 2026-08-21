"""Mastery wiring adapter contract tests (M2.5 part 5a).

Contract under test: learning_system/mastery_bridge.py — the pure adapter
layer that bridges DB/external row shapes to learning_system/mastery_rules.py
(decide_verdict / cd_counter / feed_cd_counter). No I/O, no sqlite: inputs
are plain dict sequences fed in by the runtime wiring (M2.5-5b/5c).

Scope (per the M2.5-1 docstring's "wiring layer" notes):
- window building: 90-day rolling window of eligible judgment events,
  includes the current event, time-sorted (proposal §2.2 "W = 滚动 90 天");
- eligibility filtering: rules.is_eligible applied per judgment-event row;
- counter event mapping: mastery_decisions rows -> [{"verdict", "is_manual"}]
  for cd_counter/feed_cd_counter (§2.3), NO_CHANGE skipped, manual marker
  passed through;
- evidence shape normalization: external/DB row -> decide_verdict input shape
  (field aliases + contract defaults + int/str -> bool coercion).

Run: python3 -m unittest tests.test_mastery_bridge -v
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from learning_system import mastery_bridge as bridge
from learning_system import mastery_rules as rules


def row(**overrides):
    """Canonical judgment-event row in external/DB shape (ints for booleans)."""
    base = {
        "attempt_id": "a1",
        "verdict_or_code": "B",
        "is_manual": False,
        "created_at": "2026-08-01",
        "result": "correct",
        "score_points": 10,
        "max_points": 10,
        "explanation_score": 2,
        "reasoning_soundness": "sound",
        "evidence_strength": "strong",
        "next_evidence_need": "",
        "blocking_evidence": 0,
        "structure_fingerprint": "fp_core",
        "purpose_role": "confirmation_core",
        # eligibility flags in DB int shape (0/1)
        "gate_passed": 1,
        "purpose": "diagnostic",
        "hint_policy": "no_hint",
        "mastery_update_eligible": 1,
        "voice_verifiable": 1,
        "analysis_valid": 1,
    }
    base.update(overrides)
    return base


def day(n):
    """Anchor-relative date string: day(0) = anchor, day(-n) = n days before."""
    return (date(2026, 8, 10) + timedelta(days=n)).isoformat()


class TestNormalizeEvidence(unittest.TestCase):
    def test_aliases_id_to_attempt_id(self):
        normalized = bridge.normalize_evidence(row(attempt_id="a1"))
        self.assertEqual(normalized["attempt_id"], "a1")
        db_shaped = {"id": "a9", "created_at": "2026-08-01"}
        normalized = bridge.normalize_evidence(db_shaped)
        self.assertEqual(normalized["attempt_id"], "a9")
        self.assertNotIn("id", normalized)

    def test_aliases_verdict_to_verdict_or_code(self):
        normalized = bridge.normalize_evidence(row(verdict_or_code="C"))
        self.assertEqual(normalized["verdict_or_code"], "C")
        with_verdict = row()
        del with_verdict["verdict_or_code"]
        with_verdict["verdict"] = "A"
        normalized = bridge.normalize_evidence(with_verdict)
        self.assertEqual(normalized["verdict_or_code"], "A")

    def test_contract_defaults_filled_when_missing(self):
        minimal = {"result": "correct", "score_points": 10, "max_points": 10,
                   "created_at": "2026-08-01"}
        normalized = bridge.normalize_evidence(minimal)
        self.assertEqual(normalized["purpose"], "diagnostic")
        self.assertEqual(normalized["hint_policy"], "no_hint")
        self.assertIs(normalized["gate_passed"], True)
        self.assertIs(normalized["mastery_update_eligible"], True)
        self.assertIs(normalized["voice_verifiable"], True)
        self.assertIs(normalized["analysis_valid"], True)
        self.assertIs(normalized["is_manual"], False)
        self.assertIs(normalized["blocking_evidence"], False)
        self.assertEqual(normalized["next_evidence_need"], "")

    def test_bool_coercion_from_int_and_str(self):
        for value, expected in ((1, True), (0, False), ("1", True), ("0", False),
                                ("true", True), ("false", False), (True, True),
                                (False, False), (None, False)):
            normalized = bridge.normalize_evidence(
                row(gate_passed=value, is_manual=value, blocking_evidence=value)
            )
            self.assertIs(normalized["gate_passed"], expected)
            self.assertIs(normalized["is_manual"], expected)
            self.assertIs(normalized["blocking_evidence"], expected)

    def test_missing_created_at_raises(self):
        with self.assertRaises(ValueError):
            bridge.normalize_evidence({"result": "correct"})

    def test_contract_fields_pass_through(self):
        src = row(
            result="partial", score_points=7, max_points=10, explanation_score=1,
            reasoning_soundness="unclear", evidence_strength="insufficient",
            next_evidence_need="recheck", structure_fingerprint="fp_x",
            purpose_role="confirmation_transfer", created_at="2026-08-02",
        )
        normalized = bridge.normalize_evidence(src)
        self.assertEqual(normalized["result"], "partial")
        self.assertEqual(normalized["score_points"], 7)
        self.assertEqual(normalized["max_points"], 10)
        self.assertEqual(normalized["explanation_score"], 1)
        self.assertEqual(normalized["reasoning_soundness"], "unclear")
        self.assertEqual(normalized["evidence_strength"], "insufficient")
        self.assertEqual(normalized["next_evidence_need"], "recheck")
        self.assertEqual(normalized["structure_fingerprint"], "fp_x")
        self.assertEqual(normalized["purpose_role"], "confirmation_transfer")
        self.assertEqual(normalized["created_at"], "2026-08-02")

    def test_normalized_row_is_eligible_and_decide_verdict_consumes_it(self):
        normalized = bridge.normalize_evidence(row())
        self.assertTrue(rules.is_eligible(normalized))
        verdict = rules.decide_verdict(normalized)
        self.assertEqual(verdict["code"], "B")  # T1: single strong, no AGG -> B


class TestJudgmentEvent(unittest.TestCase):
    def test_eligible_row_is_a_judgment_event(self):
        self.assertTrue(bridge.is_judgment_event(row()))

    def test_ineligible_variants_are_not_judgment_events(self):
        variants = {
            "practice_purpose": row(purpose="practice"),
            "hint_used": row(hint_policy="hint"),
            "gate_failed": row(gate_passed=0),
            "mastery_update_not_eligible": row(mastery_update_eligible=0),
            "not_voice_verifiable": row(voice_verifiable=0),
            "manual": row(is_manual=True),
            "analysis_invalid": row(analysis_valid=0),
        }
        for name, r in variants.items():
            with self.subTest(variant=name):
                self.assertFalse(bridge.is_judgment_event(r))


class TestBuildWindow(unittest.TestCase):
    def test_includes_current_and_sorts_ascending(self):
        current = row(attempt_id="a_current", created_at=day(0))
        older = row(attempt_id="a_minus5", created_at=day(-5))
        oldest = row(attempt_id="a_minus10", created_at=day(-10))
        window = bridge.build_window([older, current, oldest], current)
        self.assertEqual(
            [e["attempt_id"] for e in window],
            ["a_minus10", "a_minus5", "a_current"],
        )
        self.assertIn(current["attempt_id"], [e["attempt_id"] for e in window])

    def test_clips_to_90_days_inclusive(self):
        current = row(attempt_id="a_current", created_at=day(0))
        rows = [
            row(attempt_id="a_91d", created_at=day(-91)),   # clipped
            row(attempt_id="a_90d", created_at=day(-90)),   # boundary: kept
            row(attempt_id="a_60d", created_at=day(-60)),
            row(attempt_id="a_1d", created_at=day(-1)),
            current,
        ]
        window = bridge.build_window(rows, current)
        ids = [e["attempt_id"] for e in window]
        self.assertNotIn("a_91d", ids)
        self.assertIn("a_90d", ids)
        self.assertEqual(ids, ["a_90d", "a_60d", "a_1d", "a_current"])

    def test_excludes_future_rows(self):
        current = row(attempt_id="a_current", created_at=day(0))
        future = row(attempt_id="a_future", created_at=day(7))
        window = bridge.build_window([future, current], current)
        ids = [e["attempt_id"] for e in window]
        self.assertNotIn("a_future", ids)
        self.assertIn("a_current", ids)

    def test_excludes_ineligible_events(self):
        current = row(attempt_id="a_current", created_at=day(0))
        ineligible = [
            row(attempt_id="a_practice", created_at=day(-2), purpose="practice"),
            row(attempt_id="a_manual", created_at=day(-2), is_manual=True),
            row(attempt_id="a_hint", created_at=day(-2), hint_policy="hint"),
            row(attempt_id="a_gate", created_at=day(-2), gate_passed=0),
            row(attempt_id="a_mue", created_at=day(-2), mastery_update_eligible=0),
            row(attempt_id="a_voice", created_at=day(-2), voice_verifiable=0),
            row(attempt_id="a_analysis", created_at=day(-2), analysis_valid=0),
        ]
        window = bridge.build_window(ineligible + [current], current)
        ids = [e["attempt_id"] for e in window]
        for r in ineligible:
            self.assertNotIn(r["attempt_id"], ids)
        self.assertIn("a_current", ids)

    def test_current_appended_when_missing_from_rows(self):
        current = row(attempt_id="a_current", created_at=day(0))
        window = bridge.build_window(
            [row(attempt_id="a_hist", created_at=day(-3))], current
        )
        ids = [e["attempt_id"] for e in window]
        self.assertIn("a_current", ids)
        self.assertIn("a_hist", ids)

    def test_ineligible_current_is_filtered_out(self):
        # Documented: only eligible events form a window (§2.2 judgment-event
        # granularity); an ineligible current is not a judgment event, so it is
        # filtered like any other row — decide_verdict handles it as R6
        # NO_CHANGE regardless of the window.
        current = row(attempt_id="a_manual_current", created_at=day(0), is_manual=True)
        window = bridge.build_window([current], current)
        self.assertEqual(window, [])

    def test_window_entries_normalized_for_decide_verdict(self):
        current = row(
            attempt_id="a_current", created_at=day(0), blocking_evidence=1,
            is_manual=0,
        )
        window = bridge.build_window([current], current)
        # blocking_evidence=1 int -> True bool; is_manual 0 -> False bool
        self.assertIs(window[0]["blocking_evidence"], True)
        self.assertIs(window[0]["is_manual"], False)
        # entries carry the decide_verdict evidence contract keys
        for key in ("result", "score_points", "max_points", "explanation_score",
                    "reasoning_soundness", "evidence_strength", "structure_fingerprint",
                    "purpose_role", "created_at"):
            self.assertIn(key, window[0])

    def test_built_window_feeds_decide_verdict_to_agg_a(self):
        # Two strong eligible events (different fingerprint + dual roles +
        # two days) + current -> window AGG C1-C6 all satisfied -> verdict A.
        first = row(
            attempt_id="a1", created_at=day(-1),
            structure_fingerprint="fp_core", purpose_role="confirmation_core",
        )
        current = row(
            attempt_id="a2", created_at=day(0),
            structure_fingerprint="fp_transfer", purpose_role="confirmation_transfer",
        )
        window = bridge.build_window([first, current], current)
        verdict = rules.decide_verdict(bridge.normalize_evidence(current), window)
        self.assertEqual(verdict["code"], "A")  # T2


class TestToCounterEvents(unittest.TestCase):
    def test_maps_rows_to_verdict_is_manual_events(self):
        rows = [
            row(attempt_id="a1", verdict_or_code="C", created_at="2026-07-01"),
            row(attempt_id="a2", verdict_or_code="B", created_at="2026-07-02"),
        ]
        events = bridge.to_counter_events(rows)
        self.assertEqual(
            events,
            [
                {"verdict": "C", "is_manual": False},
                {"verdict": "B", "is_manual": False},
            ],
        )

    def test_sorts_by_created_at(self):
        rows = [
            row(attempt_id="a_later", verdict_or_code="C", created_at="2026-08-02"),
            row(attempt_id="a_earlier", verdict_or_code="B", created_at="2026-08-01"),
        ]
        events = bridge.to_counter_events(rows)
        self.assertEqual(
            [e["verdict"] for e in events], ["B", "C"],
        )

    def test_manual_marker_passed_through(self):
        rows = [
            row(attempt_id="a1", verdict_or_code="C", is_manual=True),
            row(attempt_id="a2", verdict_or_code="D", is_manual=False),
        ]
        events = bridge.to_counter_events(rows)
        self.assertEqual(events[0]["is_manual"], True)
        self.assertEqual(events[1]["is_manual"], False)

    def test_no_change_rows_skipped(self):
        rows = [
            row(attempt_id="a1", verdict_or_code="C", created_at="2026-07-01"),
            row(attempt_id="a2", verdict_or_code="NO_CHANGE", created_at="2026-07-02"),
            row(attempt_id="a3", verdict_or_code="A", created_at="2026-07-03"),
        ]
        events = bridge.to_counter_events(rows)
        self.assertEqual(
            [e["verdict"] for e in events], ["C", "A"],
        )

    def test_verdict_alias_fallback(self):
        rows = [row(attempt_id="a1", verdict_or_code="B")]
        del rows[0]["verdict_or_code"]
        rows[0]["verdict"] = "B"
        events = bridge.to_counter_events(rows)
        self.assertEqual(events, [{"verdict": "B", "is_manual": False}])

    def test_unknown_verdict_raises(self):
        with self.assertRaises(ValueError):
            bridge.to_counter_events([row(verdict_or_code="stable")])

    def test_missing_verdict_field_raises(self):
        bad = row()
        del bad["verdict_or_code"]
        with self.assertRaises(ValueError):
            bridge.to_counter_events([bad])

    def test_missing_created_at_raises(self):
        bad = row()
        del bad["created_at"]
        with self.assertRaises(ValueError):
            bridge.to_counter_events([bad])

    def test_events_feed_cd_counter_directly(self):
        rows = [
            row(attempt_id="a1", verdict_or_code="C", created_at="2026-07-01"),
            row(attempt_id="a2", verdict_or_code="C", created_at="2026-07-02"),
            row(attempt_id="a3", verdict_or_code="C", created_at="2026-07-03"),
        ]
        events = bridge.to_counter_events(rows)
        # 3 consecutive C -> trigger fires (count reaches limit, resets to 0).
        count = 0
        triggered = False
        for event in events:
            result = rules.feed_cd_counter(count, event["verdict"],
                                           manual=event["is_manual"])
            count, triggered = result["count"], result["triggered"]
        self.assertTrue(triggered)
        self.assertEqual(count, 0)


class TestRetestHistory(unittest.TestCase):
    """§2.4 follow-up: bridge.retest_history maps mastery_decisions rows to
    the derivation inputs of rules.derive_retest_state / rules.retest_due
    (pure; no I/O). Legacy-aware verdict fallback per row:

        verdict_or_code (alias "verdict") ->
        decision_payload_json.unified_verdict.verdict trace ->
        new_status_code (stored A/B/C/D outcome; approximates the verdict
        for legacy rows — a keep-A event reads as A, which advances depth;
        rows written by M2.5-5b/5c always carry the exact unified trace).

    Returns {"events": [{"verdict", "is_manual"}, ...], "last_event_at":
    date | None} — the anchor date is the created_at of the last event that
    maps to a real (non-NO_CHANGE) judgment event.
    """

    @staticmethod
    def md_row(**overrides):
        """mastery_decisions-shaped row (the columns the planner reads)."""
        base = {
            "node_id": "M-G7-POS-NEG",
            "new_status_code": "B",
            "decision_payload_json": {},
            "created_at": "2026-08-01",
            "is_manual": False,
        }
        base.update(overrides)
        return base

    @staticmethod
    def trace(verdict):
        return {"unified_verdict": {"verdict": verdict}}

    def test_maps_rows_to_events_and_anchor(self):
        rows = [
            self.md_row(created_at="2026-08-01", new_status_code="C"),
            self.md_row(created_at="2026-08-02", new_status_code="B"),
        ]
        history = bridge.retest_history(rows)
        self.assertEqual(
            history["events"],
            [
                {"verdict": "C", "is_manual": False},
                {"verdict": "B", "is_manual": False},
            ],
        )
        self.assertEqual(history["last_event_at"], date(2026, 8, 2))

    def test_sorts_by_created_at(self):
        rows = [
            self.md_row(created_at="2026-08-05", new_status_code="A"),
            self.md_row(created_at="2026-08-02", new_status_code="C"),
            self.md_row(created_at="2026-08-01", new_status_code="B"),
        ]
        history = bridge.retest_history(rows)
        self.assertEqual(
            [e["verdict"] for e in history["events"]], ["B", "C", "A"],
        )
        self.assertEqual(history["last_event_at"], date(2026, 8, 5))

    def test_legacy_new_status_code_fallback(self):
        rows = [self.md_row(new_status_code="A")]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"], [{"verdict": "A", "is_manual": False}])

    def test_payload_trace_priority_over_new_status_code(self):
        # keep-A event: stored outcome A, real verdict B -> trace wins.
        rows = [self.md_row(new_status_code="A", decision_payload_json=self.trace("B"))]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"], [{"verdict": "B", "is_manual": False}])

    def test_payload_trace_accepts_json_string(self):
        import json as _json
        rows = [self.md_row(
            new_status_code="A",
            decision_payload_json=_json.dumps(self.trace("B")),
        )]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"], [{"verdict": "B", "is_manual": False}])

    def test_verdict_or_code_priority_over_trace(self):
        rows = [self.md_row(
            verdict_or_code="C",
            new_status_code="A",
            decision_payload_json=self.trace("B"),
        )]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"], [{"verdict": "C", "is_manual": False}])

    def test_no_change_rows_dropped_from_events_and_anchor(self):
        rows = [
            self.md_row(created_at="2026-08-01", new_status_code="C"),
            self.md_row(created_at="2026-08-02", new_status_code="B"),
            self.md_row(created_at="2026-08-03", new_status_code="A"),
        ]
        rows[1]["new_status_code"] = "NO_CHANGE"  # never stored in reality
        history = bridge.retest_history(rows)
        self.assertEqual(
            [e["verdict"] for e in history["events"]], ["C", "A"],
        )
        self.assertEqual(history["last_event_at"], date(2026, 8, 3))

    def test_manual_marker_passed_through(self):
        rows = [
            self.md_row(created_at="2026-08-01", new_status_code="C", is_manual=True),
            self.md_row(created_at="2026-08-02", new_status_code="B"),
        ]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"][0]["is_manual"], True)

    def test_empty_rows_no_schedule(self):
        history = bridge.retest_history([])
        self.assertEqual(history["events"], [])
        self.assertIsNone(history["last_event_at"])

    def test_missing_created_at_raises(self):
        bad = self.md_row()
        del bad["created_at"]
        with self.assertRaises(ValueError):
            bridge.retest_history([bad])

    def test_no_readable_verdict_row_skipped(self):
        # Real legacy rows often carry new_status_code='' and no unified
        # trace — such rows are not judgment events and are skipped (the
        # planner must not crash on pre-unified data; the retest gate then
        # falls back to "no schedule -> due", the conservative direction).
        rows = [
            self.md_row(created_at="2026-08-01", new_status_code="A"),
            self.md_row(created_at="2026-08-02", new_status_code=""),
        ]
        history = bridge.retest_history(rows)
        self.assertEqual(history["events"], [{"verdict": "A", "is_manual": False}])
        self.assertEqual(history["last_event_at"], date(2026, 8, 1))

    def test_events_feed_derive_retest_state(self):
        rows = [
            self.md_row(created_at="2026-08-01", new_status_code="A"),
            self.md_row(created_at="2026-08-02", new_status_code="A"),
            self.md_row(created_at="2026-08-03", new_status_code="B"),
        ]
        history = bridge.retest_history(rows)
        state = rules.derive_retest_state(history["events"])
        self.assertEqual(state["depth"], 2)
        self.assertEqual(state["b_count"], 1)
        self.assertEqual(state["days"], 7)  # depth>=1 -> 当前间隔


if __name__ == "__main__":
    unittest.main()
