"""v51 runtime wiring seam tests (M2.5 part 5b).

Contract under test: learning_system/mastery_v51_adapter.py — the pure seam
between the v51 daily_runtime judgment site (_record_evaluation_update) and
the unified mastery rules. It composes (task M2.5-5b step 2):

    mastery_bridge.normalize_evidence -> build_window -> decide_verdict
        -> apply_llm_tightening (evaluation_output.mastery_recommendation as
           the §5 evidence-interpretation label, 只收紧不放宽)
        -> transition_status (with the §2.3 unique counter derived from the
           node's mastery_decisions history)

Anchors (proposal §7 regression checklist): T1, T2, T3, T8, T9, T10, T12,
T14, T15; plus the "确定性 weak -> 收紧后 C" wiring case and the A-gate
correspondence with the legacy _evidence_set_supports_stable_mastery behavior
(differences listed in the M2.5-5b report).

Test list:
- deterministic weak -> B tightened to C, unfiled -> files C
- LLM stable_for_now never promotes (T14: AGG C3 fail -> stays B)
- evidence insufficient (missing reasoning info) -> NO_CHANGE, never stored
- 3rd consecutive C/D on A -> direct downgrade to C + recheck (T9)
- A gate: 2 strong + dual roles + 2 days -> A (T2)
- A gate: same-day strongs fail C5 -> B (T3)
- A gate: gate-passed but non-strong rows -> B (stricter than legacy gate)
- C node + single strong -> keeps C (T10, 防单条翻案)
- A node + single strong -> keeps A (preserve_accumulated_status semantics)
- blocked recommendation tightens B -> D
- likely_stable never promotes C (legacy mapped it to B unconditionally)
- legacy decision_history (new_status_code only) feeds the unique counter
- deterministic path never yields A (§5.4)
- empty recommendation -> no tightening
- decision_history_events: unified / legacy / NO_CHANGE skipped / raise
- unknown recommendation raises
- attrs carry the llm_recommendation provenance

Run: python3 -m unittest tests.test_mastery_v51_adapter -v
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from learning_system import mastery_bridge as bridge
from learning_system import mastery_rules as rules
from learning_system import mastery_v51_adapter as adapter


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
        "current_row": row(),
        "history_rows": [],
        "decision_history": [],
        "evaluation_output": {},
        "current_status": None,
        "deterministic": False,
    }
    defaults.update(kwargs)
    return adapter.judge_v51_evaluation(**defaults)


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


class TestDeterministicWeakTightens(unittest.TestCase):
    def test_deterministic_weak_tightens_b_to_c_and_files_c(self):
        # 确定性 weak：单条强证据 -> decide_verdict B（T1），LLM/确定性标签
        # "weak" 只收紧 -> C；未建档节点按需建档为 C。
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            evaluation_output={"mastery_recommendation": "weak",
                               "reason": "本题确定性得分 7/10，关键得分点仍有缺口。"},
            deterministic=True,
        )
        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["decision"], "current_node_weak")
        self.assertIn("7/10", result["reason"])
        self.assertEqual(result["attrs"].get("llm_recommendation"), "weak")
        self.assertEqual(result["attrs"].get("tightened"), True)

    def test_empty_recommendation_is_no_tightening(self):
        # live_model 路径无 evaluation_output：recommendation 为空 -> 不收紧，
        # 单条强证据 -> B。
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            evaluation_output={},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["attrs"].get("llm_applied"), False)


class TestLLMTighteningBoundary(unittest.TestCase):
    def test_stable_for_now_never_promotes_to_a(self):  # T14
        # 两条强证据但都是 confirmation_core -> AGG C3 缺迁移角色 -> B；
        # LLM stable_for_now 只提示 A 候选，不能促成升 A。
        first = strong_row("a1", day(-1), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_core")
        result = judge(
            current_row=current,
            history_rows=[first],
            evaluation_output={"mastery_recommendation": "stable_for_now"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["attrs"].get("llm_recommendation"), "stable_for_now")

    def test_likely_stable_never_promotes_c(self):
        # 旧口径 likely_stable 无条件 -> B；统一口径下 LLM 只收紧不放宽，
        # wrong 证据的 verdict=C 不会被 likely_stable 抬高。
        current = row(attempt_id="a_current", created_at=day(0), result="wrong",
                      score_points=3, max_points=10, explanation_score=1,
                      reasoning_soundness="incomplete",
                      evidence_strength="weak", next_evidence_need="recheck")
        result = judge(
            current_row=current,
            evaluation_output={"mastery_recommendation": "likely_stable"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "C")

    def test_blocked_recommendation_tightens_b_to_d(self):
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            evaluation_output={"mastery_recommendation": "blocked"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "D")
        self.assertEqual(result["status"], "D")
        self.assertEqual(result["decision"], "prerequisite_blocked")

    def test_unknown_recommendation_raises(self):
        with self.assertRaises(ValueError):
            judge(
                current_row=strong_row("a_current", day(0)),
                evaluation_output={"mastery_recommendation": "stable"},
            )


class TestNoChangeNeverStored(unittest.TestCase):
    def test_evidence_insufficient_is_no_change(self):
        # correct + ratio>=0.85 + exp>=2 但 reasoning_soundness 缺失 -> R6
        # NO_CHANGE；未建档节点不写 C（没测过 ≠ 薄弱）。
        current = row(attempt_id="a_current", created_at=day(0),
                      reasoning_soundness=None, evidence_strength=None)
        result = judge(
            current_row=current,
            evaluation_output={},
            deterministic=False,
        )
        self.assertFalse(result["applied"])
        self.assertEqual(result["verdict"], "NO_CHANGE")
        self.assertIsNone(result["status"])
        self.assertEqual(result["reason_code"], "no_change")

    def test_no_change_keeps_existing_status_and_counter(self):
        current = row(attempt_id="a_current", created_at=day(0),
                      reasoning_soundness=None, evidence_strength=None)
        history = [
            decision_row(new_status_code="C", created_at="2026-08-01"),
            decision_row(new_status_code="C", created_at="2026-08-02"),
        ]
        result = judge(
            current_row=current,
            decision_history=history,
            current_status="B",
            evaluation_output={},
            deterministic=False,
        )
        self.assertFalse(result["applied"])
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["previous_counter"], 2)
        self.assertEqual(result["counter"], 2)


class TestConsecutiveCDDowngrade(unittest.TestCase):
    def test_third_consecutive_cd_downgrades_a_to_c_with_recheck(self):  # T9
        # 唯一计数器：历史 2 次 C verdict + 本次 wrong -> verdict C -> 连续 3 次
        # -> A 直接降 C、计数清零、触发回查。
        current = row(attempt_id="a_current", created_at=day(0), result="wrong",
                      score_points=2, max_points=10, explanation_score=0,
                      reasoning_soundness="incomplete",
                      evidence_strength="weak", next_evidence_need="recheck")
        history = [
            decision_row(new_status_code="C", created_at="2026-08-01"),
            decision_row(new_status_code="C", created_at="2026-08-02"),
        ]
        result = judge(
            current_row=current,
            decision_history=history,
            current_status="A",
            evaluation_output={"mastery_recommendation": "weak"},
            deterministic=True,
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
        result = judge(
            current_row=current,
            decision_history=[],
            current_status="A",
            evaluation_output={"mastery_recommendation": "weak"},
            deterministic=True,
        )
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["counter"], 1)
        self.assertFalse(result["recheck"])
        self.assertFalse(result["downgrade"])

    def test_legacy_status_codes_feed_the_counter(self):
        # 历史 mastery_decisions 行只带 new_status_code（无 unified verdict）：
        # 映射 A/B/C/D -> 统一 verdict 进唯一计数器。
        current = row(attempt_id="a_current", created_at=day(0), result="wrong",
                      score_points=2, max_points=10, explanation_score=0,
                      reasoning_soundness="incomplete",
                      evidence_strength="weak", next_evidence_need="recheck")
        history = [
            decision_row(new_status_code="C", created_at="2026-08-01"),
            decision_row(new_status_code="C", created_at="2026-08-02"),
        ]
        result = judge(
            current_row=current,
            decision_history=history,
            current_status="B",
            evaluation_output={},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "C")
        self.assertEqual(result["previous_counter"], 2)
        self.assertTrue(result["downgrade"])  # B -> C via trigger

    def test_verdict_b_resets_the_streak(self):
        history = [
            decision_row(new_status_code="C", created_at="2026-08-01"),
            decision_row(new_status_code="B", created_at="2026-08-02"),
        ]
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            decision_history=history,
            current_status="A",
            evaluation_output={"mastery_recommendation": "emerging"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "A")  # preserve A
        self.assertEqual(result["previous_counter"], 0)


class TestAGate(unittest.TestCase):
    def test_two_strong_dual_roles_two_days_is_a(self):  # T2 / AGG C1-C6
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_transfer")
        result = judge(
            current_row=current,
            history_rows=[first],
            # stable_for_now 是 A 候选：不收紧，AGG 全满足时 A 成立
            # （emerging 的 B-hint 按只收紧不放宽会把 A 降为 B，见
            # test_emerging_hint_demotes_would_be_a）。
            evaluation_output={"mastery_recommendation": "stable_for_now"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "A")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["decision"], "stable_for_now")
        self.assertEqual(result["attrs"].get("failed"), [])

    def test_emerging_hint_demotes_would_be_a(self):
        # 只收紧不放宽的最强形态之一：确定性 AGG 全满足，但 LLM 只给
        # emerging（单条 strong 标签 = B 候选）-> A 被降为 B（LLM 只收紧）。
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_transfer")
        result = judge(
            current_row=current,
            history_rows=[first],
            evaluation_output={"mastery_recommendation": "emerging"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["attrs"].get("llm_recommendation"), "emerging")

    def test_same_day_strongs_fail_c5(self):  # T3
        first = strong_row("a1", day(0), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_transfer")
        result = judge(
            current_row=current,
            history_rows=[first],
            evaluation_output={"mastery_recommendation": "stable_for_now"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertIn("C5", result["attrs"].get("failed", []))

    def test_gate_passed_but_not_strong_rows_do_not_aggregate_to_a(self):
        # 新旧 A 门差异：旧 _evidence_set_supports_stable_mastery 对任何全链
        # 通过的验证都计结构/角色（可被非 strong 证据凑出 A）；统一 AGG 只
        # 统计 strong 证据（R4 前半），两条 correct 0.7/exp2 的 B 档证据
        # C1 不满足 -> B。
        b1 = row(attempt_id="a1", created_at=day(-2), result="correct",
                 score_points=7, max_points=10, explanation_score=2,
                 reasoning_soundness="sound", evidence_strength="medium",
                 structure_fingerprint="fp_core",
                 purpose_role="confirmation_core")
        b2 = row(attempt_id="a2", created_at=day(-1), result="correct",
                 score_points=7, max_points=10, explanation_score=2,
                 reasoning_soundness="sound", evidence_strength="medium",
                 structure_fingerprint="fp_transfer",
                 purpose_role="confirmation_transfer")
        current = strong_row("a_current", day(0), fingerprint="fp_core",
                             purpose_role="confirmation_core")
        result = judge(
            current_row=current,
            history_rows=[b1, b2],
            evaluation_output={"mastery_recommendation": "stable_for_now"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertIn("C1", result["attrs"].get("failed", []))

    def test_deterministic_path_never_yields_a(self):  # §5.4
        # AGG 全满足本会产 A，但确定性路径（LLM 评估不可用）只产 weak/emerging
        # -> A 被抑制为 B（确定性兜底从不升 A）。
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_transfer")
        result = judge(
            current_row=current,
            history_rows=[first],
            # 空 recommendation：纯 §5.4 确定性 A 抑制（emerging 的 B-hint
            # 本身就会把 A 降为 B，无法单独检验 deterministic_a_suppressed）。
            evaluation_output={},
            deterministic=True,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertTrue(result["attrs"].get("deterministic_a_suppressed"))
        self.assertTrue(result["attrs"].get("deterministic"))


class TestTransitionPreservation(unittest.TestCase):
    def test_c_node_single_strong_keeps_c(self):  # T10 / 防单条翻案
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            history_rows=[],
            current_status="C",
            evaluation_output={"mastery_recommendation": "emerging"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "C")
        self.assertEqual(result["reason_code"], "keep_c")

    def test_c_node_two_strong_promotes_to_b(self):  # T11
        first = strong_row("a1", day(-2), fingerprint="fp_core",
                           purpose_role="confirmation_core")
        current = strong_row("a_current", day(0), fingerprint="fp_transfer",
                             purpose_role="confirmation_transfer")
        result = judge(
            current_row=current,
            history_rows=[first],
            current_status="C",
            evaluation_output={"mastery_recommendation": "stable_for_now"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "A")
        self.assertEqual(result["status"], "A")  # AGG 全满足，C 可直接升 A
        self.assertEqual(result["reason_code"], "promote_a")

    def test_a_node_single_strong_preserves_a(self):
        # 单条强证据不覆盖累积 A 档（旧 preserve_accumulated_status 语义）。
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            history_rows=[],
            current_status="A",
            evaluation_output={"mastery_recommendation": "emerging"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "A")
        self.assertEqual(result["decision"], "preserve_accumulated_status")
        self.assertEqual(result["reason_code"], "keep_a")

    def test_d_node_single_strong_promotes_to_b(self):  # T12
        current = strong_row("a_current", day(0))
        result = judge(
            current_row=current,
            history_rows=[],
            current_status="D",
            evaluation_output={"mastery_recommendation": "emerging"},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "B")
        self.assertEqual(result["status"], "B")
        self.assertEqual(result["reason_code"], "promote_b")

    def test_blocking_evidence_is_d_even_on_a(self):
        current = row(attempt_id="a_current", created_at=day(0),
                      blocking_evidence=1)
        result = judge(
            current_row=current,
            history_rows=[],
            current_status="A",
            evaluation_output={},
            deterministic=False,
        )
        self.assertEqual(result["verdict"], "D")
        self.assertEqual(result["status"], "D")
        self.assertEqual(result["reason_code"], "blocking_d")


class TestDecisionHistoryEvents(unittest.TestCase):
    def test_unified_verdict_rows(self):
        events = adapter.decision_history_events([
            decision_row(new_status_code="A", created_at="2026-07-01"),
            decision_row(new_status_code="C", created_at="2026-07-02"),
        ])
        self.assertEqual(events, [
            {"verdict": "A", "is_manual": False},
            {"verdict": "C", "is_manual": False},
        ])

    def test_legacy_and_unified_mixed(self):
        events = adapter.decision_history_events([
            decision_row(verdict_or_code="C", created_at="2026-07-01"),
            decision_row(new_status_code="B", created_at="2026-07-02"),
        ])
        self.assertEqual([e["verdict"] for e in events], ["C", "B"])

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


if __name__ == "__main__":
    unittest.main()
