"""v2 runtime wiring seam tests (M2.5 part 5c).

Contract under test: learning_system/mastery_v2_adapter.py — the pure seam
between the flow_nodes v2 orchestrator judgment site (orchestrator.py
`_mastery_decision_from_status` / `_status_update_from_evaluation`, retired
by M2.5-5c) and the unified mastery rules. It composes (task M2.5-5c step 2,
same 5b pattern):

    mastery_bridge.normalize_evidence -> build_window -> decide_verdict
        -> transition_status (with the §2.3 unique counter derived from the
           node's mastery_decisions history)

Judgment-event granularity (§2.2): one eligible attempt = one judgment
event. The v2 orchestrator judges at session close, per node, aggregating
the session's attempts; this adapter folds those attempts chronologically
as judgment events (decision-time window per event), so the final result is
the node's state after the whole session — flow_nodes' session-level 聚合批判
定 is retired (§2.2). The wiring persists exactly one mastery_decisions row +
one learner_node_status row per node per session (落库机制不动).

Anchors (proposal §7 regression checklist): T1, T2, T3, T5, T9, T10, T11,
T12, T13; plus the 6-态 -> 统一 4 档 semantic mapping (emerging -> B,
stable -> A when AGG else B, likely_stable -> B, unstable -> C, blocked -> D,
insufficient_evidence -> NO_CHANGE) and the orchestrator insufficient_evidence
-> C 误判废止点 (no evidence must never file C, §2.1 point 3).

Test list:
- no evidence rows -> NO_CHANGE, never C (废止点), applied=False
- ineligible rows only (manual / practice / gate fail) -> NO_CHANGE (T13)
- single strong -> B, files B (T1; old "emerging")
- two strong same day (old "likely_stable") -> B (T3, C5 fails)
- three strong same day (old "stable" single-session aggregate) -> B:
  the "单会话 3 条证据即 A" old-criteria outcome is retired
- two strong across 2 natural days + 2 fingerprints + dual roles -> A (T2)
- wrong attempt (old "unstable") -> C, files C
- blocking evidence -> D, files D (T5; old "blocked")
- correct but reasoning info missing -> NO_CHANGE (R6), never C
- mixed wrong -> correct session folds: C keeps C (T10 semantics,
  防单条翻案 — the session does not over-claim B)
- T9: A + [C, C] history + wrong -> C, recheck, downgrade, counter reset
- T10: C + single strong -> keeps C
- T11: C + two strongs in window -> B
- T12: D + single strong -> B (never jumps to A)
- A + single strong -> keeps A (preserve_accumulated_status semantics)
- D + AGG-satisfied verdict -> B (D never jumps to A)
- NO_CHANGE event mid-fold is skipped (neither counted nor breaking)
- decision_history_events: unified / payload trace / new_status_code /
  unreadable raises
- attrs carry the fold trace (event count / eligible count)

Run: python3 -m unittest tests.test_mastery_v2_adapter -v
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from learning_system import mastery_bridge as bridge
from learning_system import mastery_rules as rules
from learning_system import mastery_v2_adapter as adapter


def row(**overrides):
    """Judgment-event row in external/DB shape (same contract as the bridge)."""
    base = {
        "attempt_id": "a1",
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
        "gate_passed": 1,
        "purpose": "diagnostic",
        "hint_policy": "no_hint",
        "mastery_update_eligible": 1,
        "voice_verifiable": 1,
        "analysis_valid": 1,
        "is_manual": 0,
    }
    base.update(overrides)
    return base


def day(n):
    """Anchor-relative date string: day(0) = anchor, day(-n) = n days before."""
    return (date(2026, 8, 10) + timedelta(days=n)).isoformat()


def strong_row(attempt_id, created_at, fingerprint="fp_core",
               purpose_role="confirmation_core"):
    return row(
        attempt_id=attempt_id,
        created_at=created_at,
        result="correct",
        score_points=10,
        max_points=10,
        explanation_score=2,
        reasoning_soundness="sound",
        evidence_strength="strong",
        structure_fingerprint=fingerprint,
        purpose_role=purpose_role,
    )


def decision_row(**overrides):
    """mastery_decisions-like row for counter derivation (legacy shape)."""
    base = {
        "id": "MD-x",
        "node_id": "N1",
        "new_status_code": "C",
        "created_at": "2026-07-01",
        "applied": 1,
    }
    base.update(overrides)
    return base


def judge(**kwargs):
    """Thin wrapper: call the adapter entry point with defaults filled."""
    defaults = {
        "evidence_rows": [],
        "decision_history": [],
        "current_status": None,
    }
    defaults.update(kwargs)
    return adapter.judge_v2_node(**defaults)


class TestNoEvidenceNeverFilesC(unittest.TestCase):
    """orchestrator insufficient_evidence -> C 误判废止点 (proposal §2.1 point 3)."""

    def test_empty_evidence_rows_is_no_change(self):
        # 无证据节点：旧 _status_update_from_evaluation 把 insufficient_evidence
        # 映射为 C（orchestrator.py:530-535 误判点）；统一口径 NO_CHANGE 不落库。
        result = judge(evidence_rows=[])
        self.assertFalse(result["applied"])
        self.assertEqual(result["verdict"], "NO_CHANGE")
        self.assertIsNone(result["status"])
        self.assertEqual(result["decision"], "not_enough_evidence")
        self.assertEqual(result["closure_result"], "pending_analysis")
        self.assertEqual(result["reason_code"], "no_change")
        self.assertEqual(result["counter"], 0)

    def test_no_evidence_keeps_existing_status(self):
        result = judge(
            evidence_rows=[],
            decision_history=[
                decision_row(new_status_code="C", created_at="2026-08-01"),
                decision_row(new_status_code="C", created_at="2026-08-02"),
            ],
            current_status="A",
        )
        self.assertFalse(result["applied"])
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["previous_counter"], 2)
        self.assertEqual(result["counter"], 2)

    def test_correct_but_missing_reasoning_info_is_no_change(self):
        # R6：correct + 高分但 reasoning_soundness/evidence_strength 缺失 ->
        # NO_CHANGE；未建档节点不写 C（没测过 ≠ 薄弱）。
        current = row(attempt_id="a_current", created_at=day(0),
                      reasoning_soundness=None, evidence_strength=None)
        result = judge(evidence_rows=[current])
        self.assertFalse(result["applied"])
        self.assertEqual(result["verdict"], "NO_CHANGE")
        self.assertIsNone(result["status"])

    def test_only_ineligible_rows_is_no_change(self):
        # T13 边界：手动/练习/证据门未过都不产判定事件 -> NO_CHANGE。
        manual = row(attempt_id="a_manual", created_at=day(0), is_manual=1)
        practice = row(attempt_id="a_practice", created_at=day(0),
                       purpose="practice")
        gate_fail = row(attempt_id="a_gate", created_at=day(0), gate_passed=0)
        result = judge(evidence_rows=[manual, practice, gate_fail])
        self.assertFalse(result["applied"])
        self.assertEqual(result["verdict"], "NO_CHANGE")
        self.assertIsNone(result["status"])
        self.assertEqual(result["attrs"].get("eligible_count"), 0)


class TestSixStateSemantics(unittest.TestCase):
    """flow_nodes 6 态 -> 统一 4 档 mapping (each old state's destination)."""

    def test_emerging_single_strong_is_b(self):  # T1
        # 旧 "emerging"（单条 strong）-> 统一 B（T1，不升 A）。
        result = judge(evidence_rows=[strong_row("a1", day(0))])
        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["decision"], "basic_understanding")
        self.assertEqual(result["closure_result"], "repaired_not_mastered")

    def test_likely_stable_two_strong_same_day_is_b(self):  # T3
        # 旧 "likely_stable"（两条 strong 无迁移/同日）-> 统一 B（C5 同日不满足）。
        first = strong_row("a1", day(0), fingerprint="fp_core")
        second = strong_row("a2", day(0), fingerprint="fp_transfer",
                            purpose_role="confirmation_transfer")
        result = judge(evidence_rows=[first, second])
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertIn("C5", result["attrs"].get("failed", []))

    def test_three_strong_same_day_is_b(self):
        # 旧 "stable" 单会话聚合（3 条 strong + 迁移题型 + 多样）曾直接 -> A；
        # 统一口径同日强证据 C5 不满足 -> B（"单会话 3 条证据即 A" 旧口径退役）。
        rows = [
            strong_row("a1", day(0), fingerprint="fp_core"),
            strong_row("a2", day(0), fingerprint="fp_variant",
                       purpose_role="confirmation_transfer"),
            strong_row("a3", day(0), fingerprint="fp_core"),
        ]
        result = judge(evidence_rows=rows)
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertIn("C5", result["attrs"].get("failed", []))

    def test_stable_across_two_days_is_a(self):  # T2 / AGG C1-C6
        # 旧 "stable" 且跨 2 自然日 + 双指纹 + 双角色 -> 统一 A。
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        second = strong_row("a2", day(0), fingerprint="fp_transfer",
                            purpose_role="confirmation_transfer")
        result = judge(evidence_rows=[first, second])
        self.assertEqual(result["verdict"], "A")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["decision"], "stretch_ready")
        self.assertEqual(result["closure_result"], "mastered")
        self.assertEqual(result["attrs"].get("failed"), [])

    def test_unstable_wrong_is_c(self):
        # 旧 "unstable"（wrong / ratio<0.6）-> 统一 C。
        wrong = row(attempt_id="a1", created_at=day(0), result="wrong",
                    score_points=3, max_points=10, explanation_score=1,
                    reasoning_soundness="incomplete",
                    evidence_strength="weak", next_evidence_need="recheck")
        result = judge(evidence_rows=[wrong])
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["decision"], "current_node_weak")
        self.assertEqual(result["closure_result"], "repaired_not_mastered")

    def test_blocked_is_d(self):  # T5
        # 旧 "blocked"（blocking_evidence）-> 统一 D。
        blocked = row(attempt_id="a1", created_at=day(0), blocking_evidence=1)
        result = judge(evidence_rows=[blocked])
        self.assertEqual(result["verdict"], "D")
        self.assertEqual(result["status"], "D")
        self.assertEqual(result["decision"], "prerequisite_blocked")
        self.assertEqual(result["closure_result"], "prerequisite_blocked")

    def test_mixed_wrong_then_correct_folds_to_c(self):
        # 会话内 wrong -> correct：逐条折叠（不是"只看最后一条"）——
        # wrong 建档 C，其后单条 strong 不足窗口 2 强（T10 防单条翻案）-> C。
        wrong = row(attempt_id="a1", created_at=day(0), result="wrong",
                    score_points=3, max_points=10, explanation_score=1,
                    reasoning_soundness="incomplete",
                    evidence_strength="weak", next_evidence_need="recheck")
        correct = strong_row("a2", day(0))
        result = judge(evidence_rows=[wrong, correct])
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "C")  # C + 单条 strong 保持 C
        self.assertEqual(result["reason_code"], "keep_c")


class TestConsecutiveCDDowngrade(unittest.TestCase):
    def test_third_consecutive_cd_downgrades_a_to_c_with_recheck(self):  # T9
        current = row(attempt_id="a_current", created_at=day(0), result="wrong",
                      score_points=2, max_points=10, explanation_score=0,
                      reasoning_soundness="incomplete",
                      evidence_strength="weak", next_evidence_need="recheck")
        history = [
            decision_row(new_status_code="C", created_at="2026-08-01"),
            decision_row(new_status_code="C", created_at="2026-08-02"),
        ]
        result = judge(
            evidence_rows=[current],
            decision_history=history,
            current_status="A",
        )
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["previous_counter"], 2)
        self.assertEqual(result["counter"], 0)
        self.assertTrue(result["recheck"])
        self.assertTrue(result["downgrade"])
        self.assertEqual(result["reason_code"], "cd_trigger_downgrade")

    def test_single_c_on_a_keeps_a_with_counter_one(self):  # T8
        current = row(attempt_id="a_current", created_at=day(0), result="wrong",
                      score_points=2, max_points=10, explanation_score=0,
                      reasoning_soundness="incomplete",
                      evidence_strength="weak", next_evidence_need="recheck")
        result = judge(evidence_rows=[current], current_status="A")
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 1)
        self.assertFalse(result["recheck"])
        self.assertFalse(result["downgrade"])

    def test_no_change_mid_fold_does_not_break_or_count(self):
        # NO_CHANGE 事件跳过：不计入、不打断连续 C/D 序列（§2.3）。
        c1 = row(attempt_id="a1", created_at=day(-2), result="wrong",
                 score_points=2, max_points=10, explanation_score=0,
                 reasoning_soundness="incomplete",
                 evidence_strength="weak", next_evidence_need="recheck")
        inert = row(attempt_id="a2", created_at=day(-1),
                    reasoning_soundness=None, evidence_strength=None)
        c2 = row(attempt_id="a3", created_at=day(0), result="wrong",
                 score_points=2, max_points=10, explanation_score=0,
                 reasoning_soundness="incomplete",
                 evidence_strength="weak", next_evidence_need="recheck")
        result = judge(evidence_rows=[c1, inert, c2], current_status="B")
        self.assertEqual(result["counter"], 2)  # NO_CHANGE 不打断
        self.assertEqual(result["status"], "B")


class TestTransitionPreservation(unittest.TestCase):
    def test_c_node_single_strong_keeps_c(self):  # T10 / 防单条翻案
        result = judge(
            evidence_rows=[strong_row("a1", day(0))],
            current_status="C",
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["reason_code"], "keep_c")

    def test_c_node_two_strong_promotes_to_b(self):  # T11
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        second = strong_row("a2", day(0), fingerprint="fp_transfer",
                            purpose_role="confirmation_transfer")
        result = judge(
            evidence_rows=[first, second],
            current_status="C",
        )
        self.assertEqual(result["verdict"], "A")
        self.assertEqual(result["status"], "A")  # AGG 全满足，C 可直接升 A
        self.assertEqual(result["reason_code"], "promote_a")

    def test_d_node_single_strong_promotes_to_b(self):  # T12
        result = judge(
            evidence_rows=[strong_row("a1", day(0))],
            current_status="D",
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["reason_code"], "promote_b")

    def test_a_node_single_strong_preserves_a(self):
        result = judge(
            evidence_rows=[strong_row("a1", day(0))],
            current_status="A",
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["decision"], "basic_understanding")
        self.assertEqual(result["reason_code"], "keep_a")

    def test_d_never_jumps_to_a_even_with_agg(self):
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        second = strong_row("a2", day(0), fingerprint="fp_transfer",
                            purpose_role="confirmation_transfer")
        result = judge(
            evidence_rows=[first, second],
            current_status="D",
        )
        self.assertEqual(result["status"], "A")  # D -> B（e1）-> A（e2）
        self.assertEqual([e["verdict"] for e in result["events"]], ["B", "A"])


class TestDecisionHistoryEvents(unittest.TestCase):
    def test_unified_verdict_rows(self):
        events = adapter.decision_history_events([
            decision_row(verdict_or_code="A", created_at="2026-07-01"),
            decision_row(verdict_or_code="C", created_at="2026-07-02"),
        ])
        self.assertEqual(events, [
            {"verdict": "A", "is_manual": False},
            {"verdict": "C", "is_manual": False},
        ])

    def test_new_status_code_legacy_rows(self):
        events = adapter.decision_history_events([
            decision_row(new_status_code="C", created_at="2026-07-01"),
            decision_row(new_status_code="B", created_at="2026-07-02"),
        ])
        self.assertEqual([e["verdict"] for e in events], ["C", "B"])

    def test_payload_unified_verdict_trace(self):
        # v2 写库行：decision_payload_json 内 unified_verdict.verdict 可读。
        import json as _json
        events = adapter.decision_history_events([
            {
                "id": "MD-v2",
                "node_id": "N1",
                "created_at": "2026-07-03",
                "applied": 1,
                "new_status_code": "",
                "decision_payload_json": _json.dumps({
                    "unified_verdict": {"verdict": "B"},
                }),
            },
        ])
        self.assertEqual([e["verdict"] for e in events], ["B"])

    def test_no_change_skipped(self):
        events = adapter.decision_history_events([
            decision_row(verdict_or_code="NO_CHANGE", created_at="2026-07-01"),
            decision_row(verdict_or_code="A", created_at="2026-07-02"),
        ])
        self.assertEqual([e["verdict"] for e in events], ["A"])

    def test_missing_verdict_raises(self):
        with self.assertRaises(ValueError):
            adapter.decision_history_events([
                {"created_at": "2026-07-01", "new_status_code": "legacy_enum"},
            ])


class TestResultTrace(unittest.TestCase):
    def test_attrs_carry_fold_trace(self):
        result = judge(evidence_rows=[strong_row("a1", day(0))])
        self.assertEqual(result["attrs"].get("event_count"), 1)
        self.assertEqual(result["attrs"].get("eligible_count"), 1)
        self.assertEqual(result["old_status"], None)
        self.assertIsInstance(result["events"], list)
        self.assertEqual(result["events"][0]["verdict"], "B")


if __name__ == "__main__":
    unittest.main()
