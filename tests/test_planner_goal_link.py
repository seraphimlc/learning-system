"""Planner honors the weekly goal choice (M2.5 motivation follow-up objective ②).

Contract under test: `learning_system/planner.py::generate_next_plan` links the
weekly goal choice (recorded via `goal_choice_service`, table
`weekly_goal_choices`) into plan generation — design intent §6.3: 孩子自选的
目标要在计划里被尊重 (自主感要真实兑现, 不能选了白选):

- 有目标选择且目标节点尚未掌握 (非 A) → 目标节点进入本周主线任务 (learn),
  且优先于通用主线填充 (排在核心路径节点之前).
- 目标节点已掌握 (A) → 不硬塞 (尊重状态, 不浪费任务).
- 目标节点是弱档 (B/C/D) → 由既有弱档阶段处理 (rollback/prerequisite_probe/
  remediate/retest), 目标联动不重复排 learn; D (已阻塞) 由回查阶段处理,
  不直接教一个被阻塞的节点.
- 无目标选择 / 别周选择 / 空或非法记录 / 未知节点 / 非法 iso_week →
  忽略, 行为与现状一致, 不崩.
- 联动是增量: retest 门控、回查、B 档、图片挑战强化/封顶等既有逻辑不动;
  `now`/`iso_week` 可注入 (同 retest 门控模式).

Seed pattern mirrors tests/test_planner_retest_scheduling.py (class-level
template DB + per-test copy).

Run: python3 -m unittest tests.test_planner_goal_link -v
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from learning_system import db, goal_choice_service as gcs, planner, test_support  # noqa: E402

# 2026-08-10 is the Monday of ISO week 2026-W33; 2026-08-17 is W34 Monday.
W33_MON = "2026-08-10"
W33 = "2026-W33"
W34 = "2026-W34"

GOAL_NODE = "M-G7-ALG-EXPR"  # CORE_LEARN_PATH index 10 — NOT in the 10-task baseline plan


def sample_answer_analysis(*, optimal_answer="38"):
    """Minimal structured answer analysis (mirror of the shared test helper)."""
    analysis = {
        "agent_key": "answer_analysis_agent",
        "optimal_answer": optimal_answer,
        "optimal_solution_steps": ["写出关系。", "按关系完成关键步骤。", "检验答案。"],
        "child_answer_summary": "孩子写出了答案并说明了思路。",
        "comparison": [
            {"dimension": "final_answer", "status": "matched", "detail": "最终答案一致。"},
            {"dimension": "model_or_relation", "status": "matched", "detail": "关系正确。"},
            {"dimension": "steps", "status": "matched", "detail": "步骤完整。"},
            {"dimension": "symbols_units", "status": "matched", "detail": "表达清楚。"},
            {"dimension": "check_or_explanation", "status": "matched", "detail": "有检验。"},
        ],
        "alternative_solutions": [],
        "process_gap": "",
        "no_gap_observed": True,
        "teaching_explanation": "测试用的结构化答案分析。",
        "next_child_prompt": "继续。",
    }
    analysis["evaluation_support"] = db.derive_answer_evaluation_support(analysis)
    return analysis


class PlannerGoalLinkTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._template_path = Path(cls._tmpdir.name) / "seed.sqlite"
        conn = sqlite3.connect(cls._template_path)
        try:
            conn.row_factory = sqlite3.Row
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "learning.sqlite"
        shutil.copy2(self._template_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _seed_status_with_attempt(self, node_id: str, status_code: str) -> str:
        """A status row backed by a real current attempt (required for
        planner._current_mastered_node_ids / the weak phase to see it)."""
        session_id = db.create_session(self.conn, f"goal link seed {node_id}", mode="test")
        question = db.find_question_for_node(self.conn, node_id)
        attempt_id = db.record_attempt(
            self.conn,
            session_id=session_id,
            question_id=question["id"],
            node_id=node_id,
            result="correct",
            score_points=2,
            max_points=2,
            error_tags=["process_habit"],
            answer_raw="目标联动测试证据。",
            parent_note="当前题库证据。",
            answer_analysis=sample_answer_analysis(optimal_answer=question["expected_answer"]),
            explanation_score=2,
        )
        self.conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, status_revision, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, status_code, 1.0, 1,
                db.json_dump([attempt_id]),
                "Planner goal link test status.",
                1,
                db.now_iso(),
            ),
        )
        self.conn.commit()
        return attempt_id

    def _seed_b_node_with_history(self, node_id: str, *, decision_rows=None) -> str:
        """A B-status node whose retest is NOT due at W33 Monday (interval 3
        days, last judgment event 2026-08-10) — mirrors
        tests/test_planner_retest_scheduling.py._seed_b_node."""
        session_id = db.create_session(self.conn, f"goal link b {node_id}", mode="test")
        question = db.find_question_for_node(self.conn, node_id)
        attempt_id = db.record_attempt(
            self.conn,
            session_id=session_id,
            question_id=question["id"],
            node_id=node_id,
            result="correct",
            score_points=2,
            max_points=2,
            error_tags=["process_habit"],
            answer_raw="复测排期目标联动测试证据。",
            parent_note="当前题库证据。",
            answer_analysis=sample_answer_analysis(optimal_answer=question["expected_answer"]),
            explanation_score=2,
        )
        self.conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, status_revision, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, "B", 1.0, 1,
                db.json_dump([attempt_id]),
                "Planner goal link B-status test.",
                1,
                db.now_iso(),
            ),
        )
        for index, row in enumerate(decision_rows or []):
            self.conn.execute(
                """
                insert into mastery_decisions(
                  id, session_id, node_id, decision, closure_result,
                  evidence_attempt_ids_json, applied, reason,
                  decision_payload_json, new_status_code, created_at
                ) values (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    f"MD-goal-link-{node_id}-{index}",
                    session_id, node_id, "decision", "closure",
                    db.json_dump([attempt_id]), "reason",
                    db.json_dump(row.get("payload", {})),
                    row["new_status_code"],
                    row["created_at"],
                ),
            )
        self.conn.commit()
        return attempt_id

    def _record_goal_choice(self, node_ids, *, iso_week=W33):
        return gcs.record_goal_choice(self.conn, iso_week=iso_week, node_ids=list(node_ids))

    def _baseline_node_ids(self) -> list[str]:
        """Node sequence of the plan with NO goal choice (regression anchor)."""
        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False)
        return [task["node_id"] for task in plan["tasks"]]

    def _plan_node_ids(self, **kwargs) -> list[str]:
        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False, **kwargs)
        return [task["node_id"] for task in plan["tasks"]]

    def _task_types_for(self, plan, node_id) -> list[str]:
        return [task["task_type"] for task in plan["tasks"] if task["node_id"] == node_id]

    # ------------------------------------------------------------------
    # 有目标选择 → 目标节点进计划且优先
    # ------------------------------------------------------------------

    def test_goal_unmastered_node_enters_plan_and_prioritized(self):
        """未掌握目标节点 → learn 任务进计划, 排在第 0 位 (优先于主线填充)."""
        baseline = self._baseline_node_ids()
        self.assertNotIn(GOAL_NODE, baseline)  # 锚点前提: 无目标时该节点不在计划

        self._record_goal_choice([GOAL_NODE])
        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False)

        node_ids = [task["node_id"] for task in plan["tasks"]]
        self.assertIn(GOAL_NODE, node_ids)
        self.assertEqual(GOAL_NODE, node_ids[0])
        self.assertEqual(["learn"], self._task_types_for(plan, GOAL_NODE))
        self.assertIn("goal", plan["tasks"][0]["reason"].lower())
        self.assertEqual(GOAL_NODE, plan["primary_target_node_id"])
        self.assertEqual(10, len(plan["tasks"]))
        # 目标节点优先 → 被挤掉的是通用填充的最后一个核心节点, 其余核心序不变.
        self.assertEqual(
            node_ids[1:],
            [node_id for node_id in baseline if node_id != GOAL_NODE][:9],
        )

    def test_goal_two_nodes_both_unmastered_enter_in_choice_order(self):
        """选择 2 个未掌握目标 → 都进计划, 按选择顺序优先."""
        second = "M-G7-LIKE-TERMS"  # CORE_LEARN_PATH index 11 — 同样不在基线计划
        baseline = self._baseline_node_ids()
        self.assertNotIn(GOAL_NODE, baseline)
        self.assertNotIn(second, baseline)

        self._record_goal_choice([GOAL_NODE, second])
        node_ids = self._plan_node_ids()

        self.assertEqual([GOAL_NODE, second], node_ids[:2])

    # ------------------------------------------------------------------
    # 目标已掌握 (A) → 不硬塞
    # ------------------------------------------------------------------

    def test_goal_mastered_node_not_forced_into_plan(self):
        """已掌握 (A) 目标节点 → 不排任务, 计划与无目标时一致."""
        self._seed_status_with_attempt(GOAL_NODE, "A")
        self._record_goal_choice([GOAL_NODE])

        node_ids = self._plan_node_ids()
        self.assertNotIn(GOAL_NODE, node_ids)
        self.assertEqual(self._baseline_node_ids(), node_ids)

    # ------------------------------------------------------------------
    # 无目标选择 → 行为与现状一致 (回归锚点)
    # ------------------------------------------------------------------

    def test_no_goal_choice_plan_unchanged(self):
        """无目标选择 → 计划与现状一致 (回归锚点)."""
        first = self._plan_node_ids()
        self.assertEqual(10, len(first))
        self.assertNotIn(GOAL_NODE, first)
        # 两次生成一致 (确定性).
        self.assertEqual(self._plan_node_ids(), first)

    # ------------------------------------------------------------------
    # 周边界 / iso_week 注入
    # ------------------------------------------------------------------

    def test_goal_choice_other_week_ignored(self):
        """别周的选择 → 不进入本周计划 (now 推导周键)."""
        self._record_goal_choice([GOAL_NODE], iso_week=W34)  # W34, 不是 now 的 W33
        node_ids = self._plan_node_ids()
        self.assertNotIn(GOAL_NODE, node_ids)
        self.assertEqual(self._baseline_node_ids(), node_ids)

    def test_explicit_iso_week_injection_honored(self):
        """显式 iso_week 注入 → 直接读该周选择 (同 retest 门控的 now 注入模式)."""
        self._record_goal_choice([GOAL_NODE], iso_week=W34)
        node_ids = self._plan_node_ids(iso_week=W34)
        self.assertIn(GOAL_NODE, node_ids)
        self.assertEqual(GOAL_NODE, node_ids[0])

    # ------------------------------------------------------------------
    # 当周选择为空/非法 → 忽略不崩
    # ------------------------------------------------------------------

    def test_empty_goal_choice_ignored(self):
        """空 node_ids 记录 → 忽略, 计划与无目标时一致."""
        baseline = self._baseline_node_ids()
        self.conn.execute(
            """
            insert into weekly_goal_choices(
              id, iso_week, node_ids_json, chosen_by, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            ("GC-empty", W33, db.json_dump([]), "child", db.now_iso(), None),
        )
        self.conn.commit()
        self.assertEqual(baseline, self._plan_node_ids())

    def test_malformed_iso_week_ignored(self):
        """非法 iso_week → 忽略目标联动, 不崩, 计划与无目标时一致."""
        baseline = self._baseline_node_ids()
        self._record_goal_choice([GOAL_NODE])
        node_ids = self._plan_node_ids(iso_week="2026-35")
        self.assertNotIn(GOAL_NODE, node_ids)
        self.assertEqual(baseline, node_ids)

    def test_unknown_goal_node_id_skipped(self):
        """目标节点已不在图谱 (幽灵 id) → 跳过该节点, 不崩; 合法目标仍进计划."""
        self.conn.execute(
            """
            insert into weekly_goal_choices(
              id, iso_week, node_ids_json, chosen_by, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            ("GC-ghost", W33, db.json_dump(["GHOST-NODE", GOAL_NODE]), "child", db.now_iso(), None),
        )
        self.conn.commit()
        node_ids = self._plan_node_ids()
        self.assertIn(GOAL_NODE, node_ids)
        self.assertEqual(GOAL_NODE, node_ids[0])

    # ------------------------------------------------------------------
    # 弱档/回查状态的目标节点 → 既有调度处理, 目标联动不重复
    # ------------------------------------------------------------------

    def test_weak_c_goal_node_not_duplicated_by_goal_phase(self):
        """C 档目标节点 → 弱档阶段排 remediate, 目标联动不重复排 learn."""
        self._seed_status_with_attempt(GOAL_NODE, "C")
        self._record_goal_choice([GOAL_NODE])

        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False)
        self.assertEqual(["remediate"], self._task_types_for(plan, GOAL_NODE))
        self.assertNotIn("learn", self._task_types_for(plan, GOAL_NODE))

    def test_b_goal_node_not_due_retest_gate_untouched_learn_added(self):
        """B 档 (复测未到期) 目标节点 → retest 门控不动 (不排 retest), 目标联动补 learn."""
        self._seed_b_node_with_history(GOAL_NODE, decision_rows=[
            {"new_status_code": "A", "created_at": "2026-08-01"},
            {"new_status_code": "B", "created_at": "2026-08-10"},
        ])
        self.assertFalse(planner._retest_is_due(self.conn, GOAL_NODE, W33_MON))
        self._record_goal_choice([GOAL_NODE])

        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False)
        self.assertNotIn("retest", self._task_types_for(plan, GOAL_NODE))
        self.assertIn("learn", self._task_types_for(plan, GOAL_NODE))

    def test_blocked_d_goal_node_handled_by_rollback_not_learn(self):
        """D 档 (已阻塞) 目标节点 → 回查阶段排 rollback (修前置), 不硬塞 learn."""
        self._seed_status_with_attempt(GOAL_NODE, "D")
        self._record_goal_choice([GOAL_NODE])

        plan = planner.generate_next_plan(self.conn, now=W33_MON, commit=False)
        # 目标节点本身不被教 (被阻塞); 计划里是它的前置修复任务.
        self.assertNotIn(GOAL_NODE, [task["node_id"] for task in plan["tasks"]])
        self.assertTrue(
            any(
                task["task_type"] == "rollback" and GOAL_NODE in task["reason"]
                for task in plan["tasks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
