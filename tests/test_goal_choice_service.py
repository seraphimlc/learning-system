"""M5 weekly goal choice service tests (动机层 ② 自选目标).

Contract under test: `learning_system/goal_choice_service.py` —
docs/design/specs/2026-08-20-child-learning-companion-design.md §6.3.2
(每周让孩子从 2 个候选里自选下周目标, **有护栏的自主** — 孩子从系统策展的
2 个候选中选择, 不是自由选择):

- `goal_candidates`: 策展 2 个候选 —
  ① 薄弱候选 (C/D 优先, P0 + 影响面大/解锁多; 无 C/D 降级到 B "已学但未巩固");
  ② 主线候选 (尚未掌握 (非 A, 含未建档) 的七上主线节点中 "下一个该学" 的 1 个);
  候选不含已掌握 A 节点; 候选不足 2 个返回实际数量 (不编造).
- `record_goal_choice`: 校验 node_ids 合法 (存在 / 数量 1-2 / 去重),
  iso_week 冲突 → UPSERT (同 weekly_summary 模式, 一周一次选择可改选);
  返回记录.
- `current_goal_choice` / `goal_choice_history`: 读当周选择 / 历史 (planner
  联动与家长面用), 带出节点名 (服务层返回内部 node_id + name, child-safe
  投影由 API 层负责).

Seed pattern mirrors tests/test_lightup_service.py (temp DB + db.init_schema +
graph_nodes + learner_node_status).

Run: python3 -m unittest tests.test_goal_choice_service -v
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from learning_system import db
from learning_system import goal_choice_service as gcs

# Fixed ISO-8601 timestamps: 2026-08-24 is the Monday of ISO week 2026-W35.
W33_MON = "2026-08-10T09:00:00+00:00"
W34_MON = "2026-08-17T09:00:00+00:00"
W35_MON = "2026-08-24T09:00:00+00:00"

STAGE_MAINLINE = "七上主线"
STAGE_PRE = "小学关键前置"
STAGE_BRIDGE = "衔接桥梁"

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _seed_node(
    conn,
    node_id: str,
    name: str,
    *,
    stage: str = STAGE_MAINLINE,
    priority: str = "P0",
    sequence_band: int = 1,
    unlocks: list[str] | None = None,
    prereqs: list[str] | None = None,
) -> None:
    conn.execute(
        """
        insert or ignore into graph_nodes(
          id, name, stage, domain, priority, summer_mode, sequence_band,
          prerequisites_json, unlocks_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id, name, stage, "math", priority, "summer", sequence_band,
            db.json_dump(prereqs or []), db.json_dump(unlocks or []), "{}",
        ),
    )


def _seed_status(conn, node_id: str, status_code: str, updated_at: str = W35_MON) -> None:
    conn.execute(
        """
        insert into learner_node_status(
          node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
          status_reason, status_revision, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, status_code, 0.9, 1, "[]", "seed", 1, updated_at),
    )


def _current_iso_week() -> str:
    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


class GoalChoiceServiceTestCase(unittest.TestCase):
    @contextmanager
    def _db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "goal-choice.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                with conn:
                    # Default tiny graph: two mainline nodes (first two of the
                    # mainline sequence) + one pre node.
                    _seed_node(conn, "M-G7-POS-NEG", "正数和负数",
                               stage=STAGE_MAINLINE, sequence_band=5)
                    _seed_node(conn, "M-G7-NUMBER-LINE", "数轴",
                               stage=STAGE_MAINLINE, sequence_band=5)
                    _seed_node(conn, "M-PRE-NUMBER-SENSE", "数感",
                               stage=STAGE_PRE, sequence_band=1)
                yield conn
            finally:
                conn.close()

    def _count(self, conn, table: str) -> int:
        return conn.execute(f"select count(*) as n from {table}").fetchone()["n"]


# ---------------------------------------------------------------------------
# goal_candidates — 薄弱候选
# ---------------------------------------------------------------------------


class WeaknessCandidateTestCase(GoalChoiceServiceTestCase):
    def test_cd_weakness_prefers_p0_then_more_unlocks(self):
        """薄弱候选: C/D 中 P0 优先, 同 P0 时解锁多 (影响面大) 优先."""
        with self._db() as conn:
            _seed_node(conn, "W-P0-MANY", "P0多解锁", unlocks=["a", "b", "c"])
            _seed_node(conn, "W-P0-FEW", "P0少解锁", unlocks=["a"])
            _seed_node(conn, "W-P1", "P1节点", priority="P1", unlocks=["a", "b"])
            _seed_status(conn, "W-P0-MANY", "C")
            _seed_status(conn, "W-P0-FEW", "D")
            _seed_status(conn, "W-P1", "D")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            weakness = candidates[0]
            self.assertEqual("W-P0-MANY", weakness["node_id"])
            self.assertEqual("这块有点薄弱", weakness["reason_label"])

    def test_b_fallback_when_no_cd(self):
        """无 C/D → 降级到 B (已学但未巩固)."""
        with self._db() as conn:
            _seed_node(conn, "W-B", "B档节点", unlocks=["a", "b"])
            _seed_node(conn, "W-B2", "B档节点2", unlocks=["a"])
            _seed_status(conn, "W-B", "B")
            _seed_status(conn, "W-B2", "B")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual("W-B", candidates[0]["node_id"])
            self.assertEqual("学过但还不太牢", candidates[0]["reason_label"])

    def test_unarchived_node_is_not_a_weakness_candidate(self):
        """未建档节点无薄弱证据 → 不作为薄弱候选 (不假装薄弱)."""
        with self._db() as conn:
            _seed_node(conn, "W-NEW", "未建档", unlocks=["a", "b", "c"])
            _seed_node(conn, "W-C", "C档", unlocks=["a"])
            _seed_status(conn, "W-C", "C")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            weakness = candidates[0]
            self.assertEqual("W-C", weakness["node_id"])
            self.assertNotEqual("W-NEW", weakness["node_id"])


# ---------------------------------------------------------------------------
# goal_candidates — 主线候选
# ---------------------------------------------------------------------------


class MainlineCandidateTestCase(GoalChoiceServiceTestCase):
    def test_mainline_candidate_is_first_unmastered_mainline_node(self):
        """主线候选: 主线推进序中第一个尚未掌握 (非 A) 的七上主线节点."""
        with self._db() as conn:
            # _db 已含 M-G7-POS-NEG / M-G7-NUMBER-LINE / M-PRE-NUMBER-SENSE.
            _seed_status(conn, "M-G7-POS-NEG", "A")  # 已掌握 → 跳过
            _seed_status(conn, "M-PRE-NUMBER-SENSE", "C")  # 薄弱候选占位
            # NUMBER-LINE 未建档 → 尚未掌握 → 主线候选
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual(2, len(candidates))
            mainline = candidates[1]
            self.assertEqual("M-G7-NUMBER-LINE", mainline["node_id"])
            self.assertEqual("接下来该学这块", mainline["reason_label"])

    def test_mainline_skips_mastered_and_picks_next(self):
        """主线候选按推进序跳过已掌握, 取下一个未掌握节点."""
        with self._db() as conn:
            _seed_node(conn, "M-G7-ABSOLUTE", "绝对值", sequence_band=5)
            _seed_status(conn, "M-G7-POS-NEG", "A")
            _seed_status(conn, "M-G7-NUMBER-LINE", "A")
            _seed_status(conn, "M-PRE-NUMBER-SENSE", "C")  # 薄弱候选占位
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            mainline = candidates[1]
            self.assertEqual("M-G7-ABSOLUTE", mainline["node_id"])

    def test_mainline_candidate_never_mastered_a_node(self):
        """A 节点绝不出现在任何候选里."""
        with self._db() as conn:
            _seed_node(conn, "W-A-BIG", "A大解锁", unlocks=["a", "b", "c", "d"])
            _seed_status(conn, "W-A-BIG", "A")
            _seed_status(conn, "M-G7-POS-NEG", "A")
            _seed_status(conn, "M-G7-NUMBER-LINE", "A")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            node_ids = {c["node_id"] for c in candidates}
            self.assertNotIn("W-A-BIG", node_ids)
            self.assertNotIn("M-G7-POS-NEG", node_ids)
            self.assertNotIn("M-G7-NUMBER-LINE", node_ids)

    def test_collision_dedupe_weakness_and_mainline_distinct(self):
        """薄弱候选与主线候选撞车 → 主线候选顺延取下一个, 保证 2 个不同候选."""
        with self._db() as conn:
            # POS-NEG 同时是薄弱 (C) 与主线推进序第一个 → 主线应顺延到 NUMBER-LINE.
            _seed_status(conn, "M-G7-POS-NEG", "C")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual(2, len(candidates))
            self.assertEqual("M-G7-POS-NEG", candidates[0]["node_id"])
            self.assertEqual("M-G7-NUMBER-LINE", candidates[1]["node_id"])


# ---------------------------------------------------------------------------
# goal_candidates — 数量/边界
# ---------------------------------------------------------------------------


class CandidateCountTestCase(GoalChoiceServiceTestCase):
    def test_fewer_than_two_returns_actual_count(self):
        """候选不足 2 个 → 返回实际数量 (不编造)."""
        with self._db() as conn:
            _seed_status(conn, "M-G7-POS-NEG", "A")
            _seed_status(conn, "M-G7-NUMBER-LINE", "A")
            # 全部已掌握: 无薄弱候选也无主线候选 → 空.
            self.assertEqual([], gcs.goal_candidates(conn, iso_week="2026-W35"))

    def test_only_mainline_candidate_when_no_weakness(self):
        with self._db() as conn:
            _seed_status(conn, "M-G7-POS-NEG", "A")  # 无 C/D/B 薄弱
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual(1, len(candidates))
            self.assertEqual("M-G7-NUMBER-LINE", candidates[0]["node_id"])
            self.assertEqual("接下来该学这块", candidates[0]["reason_label"])

    def test_only_weakness_candidate_when_mainline_all_mastered(self):
        with self._db() as conn:
            _seed_status(conn, "M-G7-POS-NEG", "A")
            _seed_status(conn, "M-G7-NUMBER-LINE", "A")
            _seed_node(conn, "W-C", "C档", stage=STAGE_PRE)
            _seed_status(conn, "W-C", "C")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual(1, len(candidates))
            self.assertEqual("W-C", candidates[0]["node_id"])

    def test_limit_respected(self):
        with self._db() as conn:
            _seed_status(conn, "M-G7-POS-NEG", "C")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35", limit=1)
            self.assertEqual(1, len(candidates))

    def test_invalid_limit_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.goal_candidates(conn, iso_week="2026-W35", limit=0)

    def test_invalid_iso_week_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.goal_candidates(conn, iso_week="2026-35")

    def test_candidate_fields_child_safe(self):
        """候选字段: node_id/name/reason_label/stage/priority, name 用图谱名."""
        with self._db() as conn:
            _seed_status(conn, "M-G7-POS-NEG", "C")
            candidates = gcs.goal_candidates(conn, iso_week="2026-W35")
            self.assertEqual(2, len(candidates))
            for cand in candidates:
                self.assertIn("node_id", cand)
                self.assertIn("name", cand)
                self.assertIn("reason_label", cand)
                self.assertIn("stage", cand)
                self.assertIn("priority", cand)
            weakness, mainline = candidates
            self.assertEqual("正数和负数", weakness["name"])
            self.assertEqual(STAGE_MAINLINE, weakness["stage"])
            self.assertEqual("P0", weakness["priority"])
            self.assertEqual("数轴", mainline["name"])


# ---------------------------------------------------------------------------
# record_goal_choice
# ---------------------------------------------------------------------------


class RecordGoalChoiceTestCase(GoalChoiceServiceTestCase):
    def test_record_valid_two_nodes(self):
        with self._db() as conn:
            record = gcs.record_goal_choice(
                conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG", "M-G7-NUMBER-LINE"]
            )
            self.assertEqual("2026-W35", record["iso_week"])
            self.assertEqual(["M-G7-POS-NEG", "M-G7-NUMBER-LINE"], record["node_ids"])
            self.assertEqual("child", record["chosen_by"])
            self.assertIsNotNone(record["created_at"])
            self.assertIsNone(record["updated_at"])
            self.assertEqual(1, self._count(conn, "weekly_goal_choices"))

    def test_record_valid_single_node(self):
        with self._db() as conn:
            record = gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG"])
            self.assertEqual(["M-G7-POS-NEG"], record["node_ids"])

    def test_record_unknown_node_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["GHOST-NODE"])

    def test_record_more_than_two_rejected(self):
        with self._db() as conn:
            _seed_node(conn, "M-G7-ABSOLUTE", "绝对值", sequence_band=5)
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(
                    conn, iso_week="2026-W35",
                    node_ids=["M-G7-POS-NEG", "M-G7-NUMBER-LINE", "M-G7-ABSOLUTE"],
                )

    def test_record_empty_or_non_list_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=[])
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids="M-G7-POS-NEG")
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG", ""])

    def test_record_duplicate_ids_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(
                    conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG", "M-G7-POS-NEG"]
                )

    def test_record_bad_iso_week_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                gcs.record_goal_choice(conn, iso_week="35", node_ids=["M-G7-POS-NEG"])

    def test_record_chosen_by_honored(self):
        with self._db() as conn:
            record = gcs.record_goal_choice(
                conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG"], chosen_by="parent"
            )
            self.assertEqual("parent", record["chosen_by"])

    def test_record_upsert_same_week(self):
        """iso_week 冲突 → UPSERT 更新: 仍 1 行, created_at 保留, updated_at 置位."""
        with self._db() as conn:
            first = gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG"])
            second = gcs.record_goal_choice(
                conn, iso_week="2026-W35",
                node_ids=["M-G7-POS-NEG", "M-G7-NUMBER-LINE"], chosen_by="parent",
            )
            self.assertEqual(1, self._count(conn, "weekly_goal_choices"))
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(first["created_at"], second["created_at"])
            self.assertEqual(["M-G7-POS-NEG", "M-G7-NUMBER-LINE"], second["node_ids"])
            self.assertEqual("parent", second["chosen_by"])
            self.assertIsNotNone(second["updated_at"])

    def test_record_distinct_weeks_two_rows(self):
        with self._db() as conn:
            gcs.record_goal_choice(conn, iso_week="2026-W34", node_ids=["M-G7-POS-NEG"])
            gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-NUMBER-LINE"])
            self.assertEqual(2, self._count(conn, "weekly_goal_choices"))


# ---------------------------------------------------------------------------
# current_goal_choice / goal_choice_history
# ---------------------------------------------------------------------------


class ReadGoalChoiceTestCase(GoalChoiceServiceTestCase):
    def test_current_goal_choice_none_when_absent(self):
        with self._db() as conn:
            self.assertIsNone(gcs.current_goal_choice(conn, iso_week="2026-W35"))

    def test_current_goal_choice_returns_record_with_names(self):
        with self._db() as conn:
            gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG"])
            record = gcs.current_goal_choice(conn, iso_week="2026-W35")
            self.assertIsNotNone(record)
            self.assertEqual("2026-W35", record["iso_week"])
            self.assertEqual(["M-G7-POS-NEG"], record["node_ids"])
            self.assertEqual("正数和负数", record["nodes"][0]["name"])

    def test_current_goal_choice_defaults_to_current_week(self):
        with self._db() as conn:
            week = _current_iso_week()
            gcs.record_goal_choice(conn, iso_week=week, node_ids=["M-G7-POS-NEG"])
            record = gcs.current_goal_choice(conn)
            self.assertEqual(week, record["iso_week"])

    def test_history_empty_when_none(self):
        with self._db() as conn:
            self.assertEqual([], gcs.goal_choice_history(conn))

    def test_history_newest_first_with_limit_and_names(self):
        with self._db() as conn:
            gcs.record_goal_choice(conn, iso_week="2026-W33", node_ids=["M-G7-POS-NEG"])
            gcs.record_goal_choice(conn, iso_week="2026-W34", node_ids=["M-G7-NUMBER-LINE"])
            gcs.record_goal_choice(conn, iso_week="2026-W35", node_ids=["M-G7-POS-NEG"])
            rows = gcs.goal_choice_history(conn)
            self.assertEqual(["2026-W35", "2026-W34", "2026-W33"],
                             [r["iso_week"] for r in rows])
            rows_limited = gcs.goal_choice_history(conn, limit=2)
            self.assertEqual(["2026-W35", "2026-W34"],
                             [r["iso_week"] for r in rows_limited])
            self.assertEqual("正数和负数", rows[0]["nodes"][0]["name"])


if __name__ == "__main__":
    unittest.main()
