"""Semester-mode end-to-end integration chain.

Simulates one week of real usage on a SINGLE temp DB, driving the real service
functions (not mocks): system judgment via mastery_v51_adapter → manual error
M0 → M1 confirm → weekly summary (A1 warning) → weekly acknowledge (batch
M0→M1) → lightup view → goal candidates/choice → planner plan honoring the
goal → biweekly brief. Asserts cross-service consistency on the same DB state.

Run: python3 -m unittest tests.test_semester_mode_e2e -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from learning_system import db, planner, test_support  # noqa: E402
from learning_system import (  # noqa: E402
    biweekly_brief_service as bbs,
    goal_choice_service as gcs,
    lightup_service as lus,
    manual_entry_service as mes,
    mastery_bridge as mbr,
    mastery_v51_adapter as v51a,
    weekly_report_service as wrs,
)

# 一周的时间骨架：周一..周五（2026-08-24 起），ISO 周由日期推导避免手算错
WEEK_MONDAY = date(2026, 8, 24)
DAY1 = WEEK_MONDAY
DAY2 = WEEK_MONDAY + timedelta(days=1)
DAY5 = WEEK_MONDAY + timedelta(days=4)
ISO_WEEK = f"{WEEK_MONDAY.isocalendar().year}-W{WEEK_MONDAY.isocalendar().week:02d}"
NEXT_WEEK_MONDAY = WEEK_MONDAY + timedelta(days=7)

WEAK_NODE = "M-G7-POS-NEG"  # 正数和负数（七上主线 P0）——E2E 中判为 C/D 的薄弱节点
GOAL_NODE = "M-G7-NUMBER-LINE"  # 数轴（七上主线）——目标候选可选


def _evidence_row(attempt_id: str, node_id: str, *, result: str, created_at: str,
                  score: float = 0.0, max_points: float = 10.0) -> dict:
    """Raw evidence row in the shape mastery_bridge.normalize_evidence accepts."""
    return {
        "id": attempt_id,
        "node_id": node_id,
        "result": result,
        "score_points": score,
        "max_points": max_points,
        "created_at": created_at,
        "is_manual": False,
    }


class SemesterModeE2ETestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls._tmpdir.name) / "e2e.sqlite"
        with closing(db.connect(cls.db_path)) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _persist_judgment(self, conn, *, session_id: str, node_id: str,
                          judgment: dict, evidence_ids: list[str]) -> None:
        """Persist one judgment event (mastery_decisions + learner_node_status),
        mirroring the adapters' documented caller-side persistence contract."""
        status = judgment["status"]
        if status is None or judgment.get("applied") is False:
            return  # NO_CHANGE: 不写库（"没测过 ≠ 薄弱"）
        payload = {"unified_verdict": {
            "verdict": judgment["verdict"],
            "reason_code": judgment.get("reason_code"),
            "attrs": judgment.get("attrs"),
            "counter": judgment.get("counter"),
            "recheck": judgment.get("recheck"),
            "downgrade": judgment.get("downgrade"),
        }}
        decision = db.record_mastery_decision(
            conn,
            session_id=session_id,
            node_id=node_id,
            decision=judgment.get("decision", "status_update"),
            closure_result="completed",
            evidence_attempt_ids=evidence_ids,
            agent_run_id=None,
            applied=True,
            reason=judgment.get("reason", ""),
            decision_payload=payload,
            commit=False,
        )
        old = conn.execute(
            "select status_revision from learner_node_status where node_id = ?", (node_id,)
        ).fetchone()
        revision = (old[0] + 1) if old else 1
        latest_score = 0.0
        conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, graph_version,
              question_bank_version, mastery_decision_id,
              source_attempt_ids_json, source_evidence_validation_ids_json,
              updated_by_agent_run_id, status_revision, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, status, latest_score, 0,
                db.json_dump(evidence_ids), judgment.get("reason", ""),
                "", "", decision["id"],
                db.json_dump([]), db.json_dump([]),
                None, revision, judgment.get("_at", "2026-08-24T00:00:00"),
            ),
        )

    def _run_judgment(self, conn, *, session_id: str, node_id: str,
                      wrong_days: list[str]) -> dict:
        """Two wrong attempts across the given days → one C judgment event."""
        evidence = []
        for i, day in enumerate(wrong_days):
            row = _evidence_row(f"{node_id}-E2E-{i}", node_id,
                                result="wrong", created_at=day)
            evidence.append(mbr.normalize_evidence(row))
        history = [e for e in evidence[:-1]]  # 此前证据
        current = evidence[-1]
        judgment = v51a.judge_v51_evaluation(
            current_row=current,
            history_rows=history,
            decision_history=[],
            current_status=None,
            deterministic=True,
        )
        self.assertEqual("C", judgment["verdict"], judgment)
        judgment["_at"] = current["created_at"]
        self._persist_judgment(conn, session_id=session_id, node_id=node_id,
                               judgment=judgment,
                               evidence_ids=[current["attempt_id"]])
        return judgment

    def test_full_week_chain(self):
        with closing(db.connect(self.db_path)) as conn:
            session_id = db.create_session(conn, "E2E 一周", mode="test")

            # ---- 1. 系统内做题判定：POS-NEG 周一周二各错 1 次 → 2 个 C 判定事件 ----
            j1 = self._run_judgment(conn, session_id=session_id, node_id=WEAK_NODE,
                                    wrong_days=[DAY1.isoformat()])
            j2 = self._run_judgment(conn, session_id=session_id, node_id=WEAK_NODE,
                                    wrong_days=[DAY2.isoformat()])
            row = conn.execute(
                "select status_code, status_revision from learner_node_status where node_id = ?",
                (WEAK_NODE,),
            ).fetchone()
            self.assertEqual("C", row[0])
            self.assertEqual(2, row[1])  # 两个判定事件 → revision 2

            # ---- 2. 作业错题录入 M0：POS-NEG 粗心错 ----
            m0 = mes.record_manual_error(
                conn, node_id=WEAK_NODE, error_tag="calculation_or_symbol",
                prompt_ctx="E2E 作业错题", confidence=0.9,
            )
            self.assertTrue(m0["retest"], m0)  # M0 触发复测信号
            self.assertEqual("M0", m0["mode"])

            # 第二条 M0：不手动确认，留给周信批量确认通道（第 5 步）
            m0b = mes.record_manual_error(
                conn, node_id="M-G7-ABSOLUTE", error_tag="concept_confusion",
                prompt_ctx="E2E 作业错题（待批量确认）", confidence=0.7,
            )
            self.assertEqual("M0", m0b["mode"])

            # ---- 3. 爸爸手动确认 M1：动作层计数 +1（第一条走手动通道）----
            m1 = mes.confirm_manual_error(conn, m0["manual_entry_id"])
            self.assertEqual("M1", m1["mode"])
            self.assertEqual(1, m1["recheck_count"])

            # ---- 4. 周信生成：状态快照含 POS-NEG=C；连续 2 次 C → A1 预警 ----
            ws = wrs.generate_weekly_summary(conn, iso_week=ISO_WEEK)
            self.assertEqual("C", ws["node_status_snapshot_json"]["nodes"][WEAK_NODE]["status_code"])
            a1 = ws["narrative_json"].get("a1_warnings", [])
            self.assertTrue(any(w["node_id"] == WEAK_NODE and w["cd_count"] >= 2 for w in a1),
                            f"A1 预警缺失: {ws['narrative_json']}")

            # ---- 5. 周信确认 → 批量确认该周未确认的 M0→M1（第二条）----
            ack = wrs.acknowledge_weekly_summary(conn, ws["id"])
            self.assertGreaterEqual(ack["batch_confirmed"]["processed"], 1, ack)
            row_a = conn.execute(
                "select mode from manual_error_entries where id = ?", (m0["manual_entry_id"],)
            ).fetchone()
            self.assertEqual("M1", row_a[0])  # 第一条：手动确认已生效
            row_b = conn.execute(
                "select mode from manual_error_entries where id = ?", (m0b["manual_entry_id"],)
            ).fetchone()
            self.assertEqual("M1", row_b[0])  # 第二条：已被批量确认升级

            # ---- 6. 点亮视图：进度与 learner_node_status 一致 ----
            ls = lus.lightup_snapshot(conn, iso_week=ISO_WEEK)
            # POS-NEG 是 C（未掌握），不记入 mastered
            self.assertEqual("C", ls["nodes"][WEAK_NODE]["status"])

            # ---- 7. 目标候选 → 孩子选择（选薄弱候选 POS-NEG）----
            cands = gcs.goal_candidates(conn, iso_week=ISO_WEEK)
            self.assertGreaterEqual(len(cands), 1, cands)
            chosen = next(c for c in cands if c["node_id"] == WEAK_NODE)
            gcs.record_goal_choice(conn, iso_week=ISO_WEEK,
                                   node_ids=[chosen["node_id"]], chosen_by="child")
            current = gcs.current_goal_choice(conn, iso_week=ISO_WEEK)
            self.assertIn(WEAK_NODE, current["node_ids"])

            # ---- 8. planner 下周计划：目标节点进计划 ----
            plan = planner.generate_next_plan(
                conn, title="下周计划", now=NEXT_WEEK_MONDAY.isoformat(),
                iso_week=f"{NEXT_WEEK_MONDAY.isocalendar().year}-W{NEXT_WEEK_MONDAY.isocalendar().week:02d}",
            )
            plan_node_ids = {t.get("node_id") for t in plan.get("tasks", [])}
            self.assertIn(WEAK_NODE, plan_node_ids, f"目标节点未进下周计划: {plan_node_ids}")

            # 预置一个"周期前已 C、周期内无提升"的节点 → 应列入停滞清单
            STUCK = "M-G7-COMPARE"
            conn.execute(
                """insert or replace into learner_node_status(node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json, status_reason, graph_version, question_bank_version, mastery_decision_id, source_attempt_ids_json, source_evidence_validation_ids_json, updated_by_agent_run_id, status_revision, updated_at)
                values (?, 'C', 0, 0, '[]', '', '', '', NULL, '[]', '[]', NULL, 1, ?)""",
                (STUCK, "2026-08-10T00:00:00"),
            )

            # ---- 9. 双周简报：错因分布含 E2E 的 calculation_or_symbol ----
            brief = bbs.generate_biweekly_brief(conn, end_iso_week=ISO_WEEK, period_weeks=2)
            dist = brief["error_distribution"]
            self.assertGreaterEqual(dist.get("calculation_or_symbol", 0), 1,
                                    f"错因分布缺失: {dist}")
            # 停滞清单：预置的 STUCK 节点（周期前已 C）应列入
            self.assertTrue(any(s.get("node_id") == STUCK for s in brief["stalled_nodes"]),
                            f"停滞清单缺失: {brief['stalled_nodes']}")

            # ---- 10. 一致性：周信快照 = learner_node_status；里程碑 = 判定史 ----
            live = conn.execute(
                "select status_code from learner_node_status where node_id = ?", (WEAK_NODE,)
            ).fetchone()
            self.assertEqual(live[0], ws["node_status_snapshot_json"]["nodes"][WEAK_NODE]["status_code"])
            decisions = conn.execute(
                "select count(*) from mastery_decisions where node_id = ?", (WEAK_NODE,)
            ).fetchone()[0]
            self.assertEqual(2, decisions)  # 两个判定事件都留痕


if __name__ == "__main__":
    unittest.main()
