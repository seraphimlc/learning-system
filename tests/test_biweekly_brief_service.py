"""M5 biweekly pedagogy brief service tests.

Contract under test: `learning_system/biweekly_brief_service.py` —
docs/design/specs/2026-08-20-child-learning-companion-design.md §6.1/§6.2 +
P2 双周教研简报 (标注证据范围), 素材给权衡/知几/爸爸:

- 错因分布: 过去 period_weeks 周 error_cause_log (仅 counted/rule_hit,
  对齐 manual_entry_service.DISTRIBUTION_TRUST_STATUSES) 按 error_tag 聚合.
- 状态停滞 ("卡住"清单): 周期开始前已是 C/D、现在仍 C/D、且周期内从未
  升到 C/D 之上 (无 B/A 事件) 的节点.
- 异常耗时: 周期内 attempts 数异常的节点 (简单启发式: 次数 ≥ 3 且
  ≥ 2× 该周期有作答节点的平均题量, 防"碰巧多一题"误报).
- 周信联动: 过去 period_weeks 周 weekly_summary 的 A1 预警与未确认状态.
- narrative_fn 注入 (LLM 或模板降级, 同 weekly_report 模式);
  输出结构化 JSON + 一句话摘要文本.
- 纯生成不落盘 (读聚合, 简报可随时重生成; 不新增表).

Seed pattern mirrors tests/test_weekly_report_service.py.

Run: python3 -m unittest tests.test_biweekly_brief_service -v
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from learning_system import db
from learning_system import biweekly_brief_service as bbs
from learning_system import weekly_report_service as wrs

# ISO week boundaries (2026-08-17 is the Monday of 2026-W34):
W32_MON = "2026-08-03T09:00:00+00:00"   # before the 2-week period
W33_MON = "2026-08-10T09:00:00+00:00"   # period week 1
W33_WED = "2026-08-12T09:00:00+00:00"
W34_TUE = "2026-08-18T09:00:00+00:00"   # period week 2
W34_WED = "2026-08-19T09:00:00+00:00"
W35_MON = "2026-08-24T09:00:00+00:00"   # after the period


def _seed_node(conn, node_id: str, name: str) -> None:
    conn.execute(
        """
        insert or ignore into graph_nodes(
          id, name, stage, domain, priority, summer_mode, sequence_band,
          prerequisites_json, unlocks_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, name, "七上主线", "math", "P0", "summer", 1, "[]", "[]", "{}"),
    )


def _seed_learner_status(conn, node_id: str, status_code: str, updated_at: str) -> None:
    conn.execute(
        """
        insert into learner_node_status(
          node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
          status_reason, status_revision, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, status_code, 0.9, 1, "[]", "seed", 1, updated_at),
    )


def _seed_session(conn, session_id: str = "s1") -> None:
    conn.execute(
        "insert or ignore into learning_sessions(id, title, mode, created_at) "
        "values (?, ?, ?, ?)",
        (session_id, "测试会话", "child_learning_group", W33_MON),
    )


def _seed_question(conn, question_id: str, node_id: str) -> None:
    conn.execute(
        """
        insert or ignore into question_items(
          id, item_version, source_type, node_id, secondary_node_ids_json, kind,
          question_type, variant_level, prompt, answer_format, expected_answer,
          rubric_json, solution_steps_json, error_tags_json,
          rollback_candidate_node_ids_json, rollback_candidate_relations_json,
          estimated_minutes, parent_observation, source_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id, "1", "graph_generated", node_id, "[]", "retest",
            "calculation", "1", "题干", "text", "答案", "[]", "[]", "[]",
            "[]", "[]", 5, "", "{}", "{}",
        ),
    )


def _seed_attempt(conn, attempt_id: str, node_id: str, created_at: str) -> None:
    _seed_session(conn)
    _seed_question(conn, f"q-{attempt_id}", node_id)
    conn.execute(
        """
        insert or ignore into attempts(
          id, session_id, question_id, node_id, result, grading_status,
          score_points, max_points, error_tags_json, answer_raw, parent_note,
          created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id, "s1", f"q-{attempt_id}", node_id, "correct", "graded",
            10, 10, "[]", "答案", "", created_at,
        ),
    )


def _seed_error_log(
    conn,
    log_id: str,
    error_tag: str,
    trust_status: str,
    created_at: str,
    *,
    node_id: str = "N1",
) -> None:
    conn.execute(
        """
        insert into error_cause_log(
          id, attempt_id, manual_entry_id, node_id, error_tag, source,
          confidence, trust_status, parent_confirmed_at, graph_version, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_id, None, None, node_id, error_tag, "system_auto",
            None, trust_status, None, "v2", created_at,
        ),
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


class BiweeklyBriefServiceTestCase(unittest.TestCase):
    @contextmanager
    def _db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "biweekly-brief.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                with conn:
                    for node_id in ("N1", "N2", "N3", "N4", "N5", "N6", "N7"):
                        _seed_node(conn, node_id, f"节点{node_id[1:]}")
                yield conn
            finally:
                conn.close()


class ErrorDistributionTestCase(BiweeklyBriefServiceTestCase):
    def test_distribution_two_weeks_counted_and_rule_hit_only(self):
        with self._db() as conn:
            _seed_error_log(conn, "l1", "general", "counted", W33_MON)
            _seed_error_log(conn, "l2", "concept_confusion", "counted", W34_TUE)
            _seed_error_log(conn, "l3", "general", "rule_hit", W34_WED)
            _seed_error_log(conn, "l4", "general", "pending_parent", W34_WED)
            _seed_error_log(conn, "l5", "general", "counted", W32_MON)  # 周期外
            _seed_error_log(conn, "l6", "process_habit", "counted", W35_MON)  # 周期外
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual(
                {"general": 2, "concept_confusion": 1},
                brief["error_distribution"],
                "pending_parent 与周期外行一律不计入",
            )
            self.assertEqual(["2026-W33", "2026-W34"], brief["period"]["iso_weeks"])

    def test_distribution_empty_when_no_counted_rows(self):
        with self._db() as conn:
            _seed_error_log(conn, "l1", "general", "pending_parent", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual({}, brief["error_distribution"])

    def test_invalid_end_iso_week_raises(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                bbs.generate_biweekly_brief(conn, end_iso_week="2026-34")
            with self.assertRaises(ValueError):
                bbs.generate_biweekly_brief(conn, end_iso_week="2026-W99")
            with self.assertRaises(ValueError):
                bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34",
                                            period_weeks=0)


class StalledNodesTestCase(BiweeklyBriefServiceTestCase):
    def test_stalled_when_cd_before_period_still_cd_no_upgrade(self):
        with self._db() as conn:
            # N2: 周期前已是 C, 周期内无任何判定, 现在仍 C → 卡住
            _seed_decision(conn, "d1", "N2", new_status_code="C", created_at=W32_MON)
            _seed_learner_status(conn, "N2", "C", W32_MON)
            # N6: 无判定历史, 但 learner 状态在周期开始前已是 C → 卡住
            _seed_learner_status(conn, "N6", "C", W32_MON)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            stalled = {s["node_id"]: s for s in brief["stalled_nodes"]}
            self.assertIn("N2", stalled)
            self.assertIn("N6", stalled)
            self.assertEqual("C", stalled["N2"]["status"])
            self.assertEqual("节点2", stalled["N2"]["name"])

    def test_not_stalled_when_upgraded_in_period_even_if_regressed(self):
        with self._db() as conn:
            # N3: C(周期前) → B(周期内升档) → C(又回落) → 不算"从未升档"
            _seed_decision(conn, "d1", "N3", new_status_code="C", created_at=W32_MON)
            _seed_decision(conn, "d2", "N3", new_status_code="B", created_at=W33_MON)
            _seed_decision(conn, "d3", "N3", new_status_code="C", created_at=W34_TUE)
            _seed_learner_status(conn, "N3", "C", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertNotIn("N3", {s["node_id"] for s in brief["stalled_nodes"]})

    def test_not_stalled_when_status_changed_during_period_without_prior_history(self):
        with self._db() as conn:
            # N4: 无判定历史, 状态在周期内才落为 C → 无从证明"连续 2 周 C/D"
            _seed_learner_status(conn, "N4", "C", W33_WED)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertNotIn("N4", {s["node_id"] for s in brief["stalled_nodes"]})

    def test_not_stalled_when_now_above_cd(self):
        with self._db() as conn:
            _seed_decision(conn, "d1", "N2", new_status_code="C", created_at=W32_MON)
            _seed_learner_status(conn, "N2", "B", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual([], brief["stalled_nodes"])

    def test_no_stalled_when_nothing_seeded(self):
        with self._db() as conn:
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual([], brief["stalled_nodes"])


class HighAttemptNodesTestCase(BiweeklyBriefServiceTestCase):
    def test_outlier_node_flagged(self):
        with self._db() as conn:
            for i in range(5):
                _seed_attempt(conn, f"a1-{i}", "N1", W34_TUE)
            _seed_attempt(conn, "a2-0", "N2", W33_MON)
            _seed_attempt(conn, "a3-0", "N3", W34_WED)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            flagged = {n["node_id"]: n for n in brief["high_attempt_nodes"]}
            self.assertEqual(["N1"], [n["node_id"] for n in brief["high_attempt_nodes"]])
            self.assertEqual(5, flagged["N1"]["attempts"])
            self.assertEqual("节点1", flagged["N1"]["name"])
            self.assertEqual(7, brief["attempts_total"])

    def test_balanced_attempts_not_flagged(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1-0", "N1", W33_MON)
            _seed_attempt(conn, "a1-1", "N1", W34_TUE)
            _seed_attempt(conn, "a2-0", "N2", W33_MON)
            _seed_attempt(conn, "a2-1", "N2", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual([], brief["high_attempt_nodes"])

    def test_attempts_outside_period_excluded(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1-0", "N1", W35_MON)  # 周期外
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual(0, brief["attempts_total"])
            self.assertEqual([], brief["high_attempt_nodes"])


class WeeklyLetterLinkageTestCase(BiweeklyBriefServiceTestCase):
    def test_links_a1_warnings_and_unacknowledged_status(self):
        with self._db() as conn:
            # W33: 连续 2 次 C → A1 预警, 不确认
            _seed_decision(conn, "d1", "N5", new_status_code="C", created_at=W33_MON)
            _seed_decision(conn, "d2", "N5", new_status_code="C", created_at=W33_WED)
            wrs.generate_weekly_summary(conn, iso_week="2026-W33")
            # W34: 无预警, 已确认
            summary = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            wrs.acknowledge_weekly_summary(conn, summary["id"])

            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            letters = {w["iso_week"]: w for w in brief["weekly_letters"]}
            self.assertEqual({"2026-W33", "2026-W34"}, set(letters))
            self.assertEqual("unacknowledged", letters["2026-W33"]["status"])
            self.assertEqual("acknowledged", letters["2026-W34"]["status"])
            self.assertEqual(["2026-W33"], brief["unacknowledged_weeks"])
            # A1 预警随周信带出: 计数器在 W33/W34 均未复位 (无 B/A 事件),
            # 两封周信都带同一条预警.
            expected_warning = [
                {"node_id": "N5", "cd_count": 2, "message": "已连续 2 次 C/D，注意"}
            ]
            self.assertEqual(expected_warning, letters["2026-W33"]["a1_warnings"])
            self.assertEqual(expected_warning, letters["2026-W34"]["a1_warnings"])

    def test_weekly_letters_mark_missing_weeks(self):
        with self._db() as conn:
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            letters = {w["iso_week"]: w for w in brief["weekly_letters"]}
            self.assertFalse(letters["2026-W33"]["exists"])
            self.assertFalse(letters["2026-W34"]["exists"])
            self.assertEqual(["2026-W33", "2026-W34"], brief["unacknowledged_weeks"],
                             "缺失周按未确认处理, 供爸爸补看")


class NarrativeTestCase(BiweeklyBriefServiceTestCase):
    def test_narrative_fn_text_used(self):
        def narrative_fn(payload):
            return {"text": "双周教研简讯：错因集中在计算类。"}

        with self._db() as conn:
            _seed_error_log(conn, "l1", "general", "counted", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34",
                                                narrative_fn=narrative_fn)
            self.assertEqual("llm", brief["narrative"]["source"])
            self.assertFalse(brief["narrative"]["degraded"])
            self.assertIn("双周教研简讯", brief["narrative"]["text"])

    def test_narrative_fn_broken_degrades_to_template(self):
        def broken_narrative_fn(payload):
            raise RuntimeError("LLM unavailable")

        with self._db() as conn:
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34",
                                                narrative_fn=broken_narrative_fn)
            self.assertEqual("template", brief["narrative"]["source"])
            self.assertTrue(brief["narrative"]["degraded"])
            self.assertTrue(brief["narrative"]["text"].strip())

    def test_narrative_none_uses_template_with_period_label(self):
        with self._db() as conn:
            _seed_error_log(conn, "l1", "general", "counted", W34_TUE)
            brief = bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            self.assertEqual("template", brief["narrative"]["source"])
            self.assertTrue(brief["narrative"]["degraded"])
            self.assertIn("2026-W33", brief["narrative"]["text"])
            self.assertIn("2026-W34", brief["narrative"]["text"])
            self.assertIn("general", brief["narrative"]["text"])

    def test_output_is_pure_generation_no_persist(self):
        """纯生成: 简报不落任何新表/新行 (复用 weekly_summary 只读)."""
        with self._db() as conn:
            _seed_error_log(conn, "l1", "general", "counted", W34_TUE)
            before = conn.execute(
                "select count(*) as n from weekly_summary").fetchone()["n"]
            bbs.generate_biweekly_brief(conn, end_iso_week="2026-W34")
            after = conn.execute(
                "select count(*) as n from weekly_summary").fetchone()["n"]
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
