"""M5 lightup node progress service tests.

Contract under test: `learning_system/lightup_service.py` —
docs/design/specs/2026-08-20-child-learning-companion-design.md §6.3
(动机层 ① 每节课结束"点亮图谱节点"即时反馈):

- 全节点当前状态 (learner_node_status A/B/C/D; 未建档节点 → 'unknown',
  不假装掌握).
- 进度摘要: 已掌握数 (A 档) / 总数 + 按 stage 的阶段分布
  (衔接桥梁 / 小学关键前置 / 七上主线).
- 本周点亮 ("哪些绿了"): mastery_decisions 本周净提升的节点
  (B/C/D → A 或任意升档); 无判定历史的节点绝不宣称提升 (方向不可知).
- 最近里程碑: 最近 N 条 mastery_decisions 升档事件 (节点+变化+日期),
  输出带节点名 (孩子可读, name 字段带出).

Seed pattern mirrors tests/test_weekly_report_service.py (temp DB +
db.init_schema + FK chains). 本周边界用注入的 iso_week (默认当前 ISO 周).

Run: python3 -m unittest tests.test_lightup_service -v
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from learning_system import db
from learning_system import lightup_service as lu

# Fixed ISO-8601 timestamps: 2026-08-17 is the Monday of ISO week 2026-W34.
W33_MON = "2026-08-10T09:00:00+00:00"
W34_MON = "2026-08-17T09:00:00+00:00"
W34_TUE = "2026-08-18T09:00:00+00:00"
W34_WED = "2026-08-19T09:00:00+00:00"
W35_MON = "2026-08-24T09:00:00+00:00"

STAGES = ("衔接桥梁", "小学关键前置", "七上主线")


def _seed_node(conn, node_id: str, name: str, stage: str) -> None:
    conn.execute(
        """
        insert or ignore into graph_nodes(
          id, name, stage, domain, priority, summer_mode, sequence_band,
          prerequisites_json, unlocks_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, name, stage, "math", "P0", "summer", 1, "[]", "[]", "{}"),
    )


def _seed_learner_status(conn, node_id: str, status_code: str, updated_at: str,
                         *, revision: int = 1) -> None:
    conn.execute(
        """
        insert into learner_node_status(
          node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
          status_reason, status_revision, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, status_code, 0.9, 1, "[]", "seed", revision, updated_at),
    )


def _seed_session(conn, session_id: str = "s1") -> None:
    conn.execute(
        "insert or ignore into learning_sessions(id, title, mode, created_at) "
        "values (?, ?, ?, ?)",
        (session_id, "测试会话", "child_learning_group", W34_MON),
    )


def _seed_decision(
    conn,
    decision_id: str,
    node_id: str,
    *,
    new_status_code: str,
    created_at: str,
) -> None:
    _seed_session(conn)
    conn.execute(
        """
        insert into mastery_decisions(
          id, session_id, node_id, decision, closure_result,
          decision_payload_json, new_status_code, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id, "s1", node_id, "decision", "closure",
            db.json_dump({}), new_status_code, created_at,
        ),
    )


class LightupServiceTestCase(unittest.TestCase):
    @contextmanager
    def _db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lightup.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                with conn:
                    for i, node_id in enumerate(("N1", "N2", "N3", "N4", "N5")):
                        _seed_node(conn, node_id, f"节点{i + 1}",
                                   STAGES[i % len(STAGES)])
                yield conn
            finally:
                conn.close()


class SnapshotTestCase(LightupServiceTestCase):
    def test_nodes_report_status_or_unknown(self):
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "A", W34_TUE)
            _seed_learner_status(conn, "N2", "C", W33_MON)
            # N3 未建档 → unknown, 不假装掌握
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            nodes = snap["nodes"]
            self.assertEqual("A", nodes["N1"]["status"])
            self.assertEqual("C", nodes["N2"]["status"])
            self.assertEqual("unknown", nodes["N3"]["status"])
            self.assertEqual("unknown", nodes["N4"]["status"])
            self.assertEqual("unknown", nodes["N5"]["status"])
            # 节点名带出 (孩子可读)
            self.assertEqual("节点1", nodes["N1"]["name"])
            self.assertEqual("衔接桥梁", nodes["N1"]["stage"])

    def test_summary_mastered_and_stage_distribution(self):
        with self._db() as conn:
            # _db 已按 STAGES[i % 3] 建档: N1/N4→衔接桥梁, N2/N5→小学关键前置,
            # N3→七上主线.
            _seed_learner_status(conn, "N1", "A", W34_TUE)   # 衔接桥梁
            _seed_learner_status(conn, "N2", "C", W33_MON)   # 小学关键前置
            _seed_learner_status(conn, "N3", "D", W33_MON)   # 七上主线
            _seed_learner_status(conn, "N4", "A", W34_WED)   # 衔接桥梁
            # N5 未建档 → unknown, 计入总数但不算掌握
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            summary = snap["summary"]
            self.assertEqual(5, summary["total"])
            self.assertEqual(2, summary["mastered"])
            by_stage = summary["by_stage"]
            self.assertEqual({"total": 2, "mastered": 2}, by_stage["衔接桥梁"])
            self.assertEqual({"total": 2, "mastered": 0}, by_stage["小学关键前置"])
            self.assertEqual({"total": 1, "mastered": 0}, by_stage["七上主线"])
            # 孩子可读进度行
            self.assertIn("2", summary["progress_line"])
            self.assertIn("5", summary["progress_line"])

    def test_empty_db_safe(self):
        with self._db() as conn:
            for node_id in ("N1", "N2", "N3", "N4", "N5"):
                conn.execute("delete from graph_nodes where id = ?", (node_id,))
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual({}, snap["nodes"])
            self.assertEqual(0, snap["summary"]["total"])
            self.assertEqual(0, snap["summary"]["mastered"])
            self.assertEqual([], snap["this_week"]["lit_up"])
            self.assertEqual([], snap["recent_milestones"])


class ThisWeekLitUpTestCase(LightupServiceTestCase):
    def test_upgrade_this_week_is_lit(self):
        with self._db() as conn:
            _seed_decision(conn, "d1", "N1", new_status_code="B", created_at=W33_MON)
            _seed_decision(conn, "d2", "N1", new_status_code="A", created_at=W34_TUE)
            _seed_learner_status(conn, "N1", "A", W34_TUE, revision=2)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            lit = snap["this_week"]["lit_up"]
            self.assertEqual(["N1"], snap["this_week"]["lit_up_node_ids"])
            self.assertEqual(1, len(lit))
            self.assertEqual({"node_id": "N1", "name": "节点1", "from": "B", "to": "A"},
                             lit[0])

    def test_downgrade_this_week_not_lit(self):
        with self._db() as conn:
            _seed_decision(conn, "d1", "N1", new_status_code="A", created_at=W33_MON)
            _seed_decision(conn, "d2", "N1", new_status_code="C", created_at=W34_TUE)
            _seed_learner_status(conn, "N1", "C", W34_TUE, revision=2)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual([], snap["this_week"]["lit_up"])

    def test_improvement_before_week_not_lit_this_week(self):
        """上周已提升、本周无提升事件 → 本周不点亮 (但里程碑仍可看到)."""
        with self._db() as conn:
            _seed_decision(conn, "d1", "N1", new_status_code="C", created_at=W33_MON)
            _seed_decision(conn, "d2", "N1", new_status_code="B", created_at=W33_MON)
            _seed_learner_status(conn, "N1", "B", W33_MON, revision=2)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual([], snap["this_week"]["lit_up"],
                             "提升发生在 W33, 不属于本周 W34")

    def test_first_ever_decision_not_claimed_lit(self):
        """首次判定无既往状态 → 方向不可知 → 不宣称提升 (不假装掌握)."""
        with self._db() as conn:
            _seed_decision(conn, "d1", "N1", new_status_code="A", created_at=W34_TUE)
            _seed_learner_status(conn, "N1", "A", W34_TUE, revision=1)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual([], snap["this_week"]["lit_up"])
            # 当前状态仍如实可见
            self.assertEqual("A", snap["nodes"]["N1"]["status"])

    def test_unusable_verdict_rows_skipped(self):
        """无有效判定码的行 (如旧数据 new_status_code='') 不参与点亮判断."""
        with self._db() as conn:
            _seed_decision(conn, "d1", "N1", new_status_code="B", created_at=W33_MON)
            _seed_decision(conn, "d2", "N1", new_status_code="", created_at=W34_TUE)
            _seed_learner_status(conn, "N1", "B", W33_MON, revision=2)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual([], snap["this_week"]["lit_up"])


class MilestonesTestCase(LightupServiceTestCase):
    def test_recent_milestones_last_n_upgrade_events_with_names(self):
        with self._db() as conn:
            # N1: C→B (W33), B→A (W34)
            _seed_decision(conn, "d1", "N1", new_status_code="C", created_at=W33_MON)
            _seed_decision(conn, "d2", "N1", new_status_code="B", created_at=W33_MON)
            _seed_decision(conn, "d3", "N1", new_status_code="A", created_at=W34_TUE)
            # N2: D→A (W34)
            _seed_decision(conn, "d4", "N2", new_status_code="D", created_at=W33_MON)
            _seed_decision(conn, "d5", "N2", new_status_code="A", created_at=W34_WED)
            _seed_learner_status(conn, "N1", "A", W34_TUE, revision=3)
            _seed_learner_status(conn, "N2", "A", W34_WED, revision=2)

            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            ms = snap["recent_milestones"]
            self.assertEqual(3, len(ms))
            # 按日期倒序: N2 D→A (W34_WED), N1 B→A (W34_TUE), N1 C→B (W33)
            self.assertEqual({"node_id": "N2", "name": "节点2", "from": "D", "to": "A",
                              "date": W34_WED}, ms[0])
            self.assertEqual({"node_id": "N1", "name": "节点1", "from": "B", "to": "A",
                              "date": W34_TUE}, ms[1])
            self.assertEqual({"node_id": "N1", "name": "节点1", "from": "C", "to": "B",
                              "date": W33_MON}, ms[2])

    def test_milestones_limit(self):
        with self._db() as conn:
            for i, ts in enumerate((W33_MON, W33_MON, W33_MON, W34_MON)):
                _seed_decision(conn, f"d{i + 1}", "N1", new_status_code="D",
                               created_at=ts)
            # 4 次 D 无升档 → 里程碑为空
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34")
            self.assertEqual([], snap["recent_milestones"])
            # 升档事件只取最近 2 条
            _seed_decision(conn, "d5", "N1", new_status_code="C", created_at=W34_TUE)
            _seed_decision(conn, "d6", "N1", new_status_code="B", created_at=W34_WED)
            _seed_decision(conn, "d7", "N1", new_status_code="A", created_at=W35_MON)
            snap = lu.lightup_snapshot(conn, iso_week="2026-W34", milestones=2)
            self.assertEqual(2, len(snap["recent_milestones"]))
            self.assertEqual("A", snap["recent_milestones"][0]["to"])

    def test_default_iso_week_uses_current_week(self):
        """不传 iso_week → 默认当前 ISO 周, 不抛错."""
        with self._db() as conn:
            snap = lu.lightup_snapshot(conn)
            self.assertIsNotNone(snap["iso_week"])
            self.assertIsNotNone(snap["generated_at"])


if __name__ == "__main__":
    unittest.main()
