"""Planner retest scheduling via next_retest_at (M2.5 follow-up objective ①).

Contract under test: learning_system/planner.py gates interval-spaced retest
tasks (proposal §2.4). A retest task is only scheduled when it is due —
now >= last judgment event + interval — where the interval comes from the
node's mastery_decisions history replayed by
mastery_rules.derive_retest_state (A 推进 / B 重排 / C-D 归零). Nodes whose
retest is not due are left out of the round instead of being scheduled every
round; nodes with no derivable schedule (no judgment history) stay
due-by-default, preserving the planner's legacy behavior for pre-unified
statuses.

The wiring must not change any other planner path: rollback /
prerequisite_probe / remediate / learn scheduling is untouched, and the
pending-confirmation prerequisite_probe branch is not gated.

Run: python3 -m unittest tests.test_planner_retest_scheduling -v
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from learning_system import db, planner, test_support  # noqa: E402

TARGET_NODE = "M-BRIDGE-SOLUTION-HABIT"


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


class PlannerRetestSchedulingTestCase(unittest.TestCase):
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

    def _seed_b_node(self, *, decision_rows=None) -> str:
        """A B-status node backed by current active evidence + judgment
        history (mastery_decisions rows, applied=1, legacy new_status_code
        only — the planner's legacy-aware read path)."""
        session_id = db.create_session(self.conn, f"retest seed {TARGET_NODE}", mode="test")
        question = db.find_question_for_node(self.conn, TARGET_NODE)
        attempt_id = db.record_attempt(
            self.conn,
            session_id=session_id,
            question_id=question["id"],
            node_id=TARGET_NODE,
            result="correct",
            score_points=2,
            max_points=2,
            error_tags=["process_habit"],
            answer_raw="复测排期测试证据。",
            parent_note="当前题库证据。",
            answer_analysis=sample_answer_analysis(optimal_answer=question["expected_answer"]),
            explanation_score=2,
        )
        self.conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TARGET_NODE, "B", 1.0, 1,
                db.json_dump([attempt_id]),
                "Planner retest scheduling test status.",
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
                    f"MD-retest-{TARGET_NODE}-{index}",
                    session_id, TARGET_NODE, "decision", "closure",
                    db.json_dump([attempt_id]), "reason",
                    db.json_dump(row.get("payload", {})),
                    row["new_status_code"],
                    row["created_at"],
                ),
            )
        self.conn.commit()
        return attempt_id

    def _task_types_for(self, plan, node_id) -> list[str]:
        return [task["task_type"] for task in plan["tasks"] if task["node_id"] == node_id]

    # ------------------------------------------------------------------
    # planner._retest_is_due unit boundaries
    # ------------------------------------------------------------------

    def test_retest_is_due_false_before_interval(self):
        # [A, B] -> depth 1, b_count 1 -> 当前间隔 3 天; 末事件 08-10 -> 到期 08-13。
        self._seed_b_node(decision_rows=[
            {"new_status_code": "A", "created_at": "2026-08-01"},
            {"new_status_code": "B", "created_at": "2026-08-10"},
        ])
        self.assertFalse(planner._retest_is_due(self.conn, TARGET_NODE, "2026-08-12"))

    def test_retest_is_due_true_on_deadline(self):
        self._seed_b_node(decision_rows=[
            {"new_status_code": "A", "created_at": "2026-08-01"},
            {"new_status_code": "B", "created_at": "2026-08-10"},
        ])
        self.assertTrue(planner._retest_is_due(self.conn, TARGET_NODE, "2026-08-13"))

    def test_retest_is_due_no_history(self):
        self._seed_b_node()
        self.assertTrue(planner._retest_is_due(self.conn, TARGET_NODE, "2026-08-10"))

    def test_retest_is_due_cd_reset_interval_one_day(self):
        # [C] -> 归零、间隔 1 天: 同日未到期, 次日到期。
        self._seed_b_node(decision_rows=[
            {"new_status_code": "C", "created_at": "2026-08-10"},
        ])
        self.assertFalse(planner._retest_is_due(self.conn, TARGET_NODE, "2026-08-10"))
        self.assertTrue(planner._retest_is_due(self.conn, TARGET_NODE, "2026-08-11"))

    # ------------------------------------------------------------------
    # generate_next_plan wiring: retest due/not-due behavior
    # ------------------------------------------------------------------

    def test_not_due_retest_not_scheduled_in_plan(self):
        self._seed_b_node(decision_rows=[
            {"new_status_code": "B", "created_at": "2026-08-10"},
        ])
        plan = planner.generate_next_plan(self.conn, now="2026-08-10")
        self.assertNotIn("retest", self._task_types_for(plan, TARGET_NODE))

    def test_due_retest_scheduled_in_plan(self):
        self._seed_b_node(decision_rows=[
            {"new_status_code": "B", "created_at": "2026-08-10"},
        ])
        plan = planner.generate_next_plan(self.conn, now="2026-08-11")
        self.assertIn("retest", self._task_types_for(plan, TARGET_NODE))

    def test_no_history_b_node_still_scheduled(self):
        # 无判定历史 -> 默认到期: 维持 planner 旧行为 (B 节点照常排复测)。
        self._seed_b_node()
        plan = planner.generate_next_plan(self.conn, now="2026-08-10")
        self.assertIn("retest", self._task_types_for(plan, TARGET_NODE))


if __name__ == "__main__":
    unittest.main()
