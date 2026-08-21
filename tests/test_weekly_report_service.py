"""M4-3 weekly summary (周信) generation service tests.

Contract under test: `learning_system/weekly_report_service.py` —
docs/design/specs/2026-08-20-child-learning-companion-design.md §6.1/§6.2 +
docs/design/specs/2026-08-20-mastery-criteria-proposal.md §4 (A1 硬要求):

- 周信一页纸素材: 本周覆盖节点 + 当周 A/B/C/D 快照 + 状态变化 (对比上周快照),
  错因分布 (error_cause_log, 仅 trust_status IN ('counted','rule_hit')),
  证据范围三分类 (system_only / with_manual / with_all_correct),
  下周重点一句话, 异常提示.
- A1 硬要求: 唯一计数器 (mastery_decisions 连续 C/D) ≥ 2 的节点 → narrative
  **必须**含 "已连续 2 次 C/D，注意" 预警 — 即使 LLM 叙述降级为模板填充.
- 失败路径与降级 (§6.1): LLM 叙述失败 → 模板填充不阻塞; 未确认 →
  status='unacknowledged'; 缺勤 → 调用侧跳过 (本服务不生成).
- iso_week 唯一 (UPSERT 更新, 选择: 重新生成 = 新版本, 重置未确认).
- acknowledge → status='acknowledged' + 触发周信批量确认通道
  (manual_entry_service.confirm_week_manual_errors → 该周 M0 回溯标记 M1).

Seed pattern mirrors tests/test_manual_entry_service.py /
tests/test_db_schema_m4.py (temp DB + db.init_schema + FK chains).

Run: python3 -m unittest tests.test_weekly_report_service -v
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from learning_system import db
from learning_system import weekly_report_service as wrs

# Fixed ISO-8601 timestamps: 2026-08-17 is the Monday of ISO week 2026-W34.
W34_MON = "2026-08-17T09:00:00+00:00"
W34_TUE = "2026-08-18T09:00:00+00:00"
W34_WED = "2026-08-19T09:00:00+00:00"
W34_THU = "2026-08-20T09:00:00+00:00"
W33_MON = "2026-08-10T09:00:00+00:00"
W35_MON = "2026-08-24T09:00:00+00:00"
# Week-end boundary of 2026-W34 (Monday 2026-08-24 00:00 UTC).
W34_END = "2026-08-24T00:00:00+00:00"


def _seed_node(conn, node_id: str) -> None:
    conn.execute(
        """
        insert or ignore into graph_nodes(
          id, name, stage, domain, priority, summer_mode, sequence_band,
          prerequisites_json, unlocks_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, "节点", "stage", "math", "P0", "summer", 1, "[]", "[]", "{}"),
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


def _set_learner_status(conn, node_id: str, status_code: str, updated_at: str) -> None:
    """Overwrite a node's stored status (test helper; learner_node_status is not
    an M4 append-only table)."""
    conn.execute(
        """
        insert into learner_node_status(
          node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
          status_reason, status_revision, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(node_id) do update set
          status_code = excluded.status_code,
          updated_at = excluded.updated_at,
          status_revision = learner_node_status.status_revision + 1
        """,
        (node_id, status_code, 0.9, 1, "[]", "seed", 1, updated_at),
    )


def _seed_session(conn, session_id: str = "s1") -> None:
    conn.execute(
        "insert or ignore into learning_sessions(id, title, mode, created_at) "
        "values (?, ?, ?, ?)",
        (session_id, "测试会话", "child_learning_group", W34_MON),
    )


def _seed_attempt(conn, attempt_id: str, node_id: str, created_at: str) -> None:
    _seed_session(conn)
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
            f"q-{attempt_id}", "1", "graph_generated", node_id, "[]", "retest",
            "calculation", "1", "题干", "text", "答案", "[]", "[]", "[]",
            "[]", "[]", 5, "", "{}", "{}",
        ),
    )
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


def _seed_daily_summary(
    conn, flow_id: str, summary_id: str, node_ids: list[str], created_at: str
) -> None:
    conn.execute(
        """
        insert or ignore into daily_flows(
          id, local_date, graph_version, created_at, updated_at
        ) values (?, ?, ?, ?, ?)
        """,
        (flow_id, created_at[:10], "v2", created_at, created_at),
    )
    conn.execute(
        """
        insert into daily_summaries(
          id, flow_id, flow_revision, graph_version, touched_node_ids_json, created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (summary_id, flow_id, 1, "v2", db.json_dump(node_ids), created_at),
    )


def _seed_decision(
    conn,
    decision_id: str,
    node_id: str,
    *,
    new_status_code: str,
    created_at: str,
    payload: dict | None = None,
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
            db.json_dump(payload or {}), new_status_code, created_at,
        ),
    )


def _seed_error_log(
    conn,
    log_id: str,
    error_tag: str,
    trust_status: str,
    created_at: str,
    *,
    attempt_id: str | None = None,
    manual_entry_id: str | None = None,
    node_id: str = "N1",
    confidence: float | None = None,
) -> None:
    conn.execute(
        """
        insert into error_cause_log(
          id, attempt_id, manual_entry_id, node_id, error_tag, source,
          confidence, trust_status, parent_confirmed_at, graph_version, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_id, attempt_id, manual_entry_id, node_id, error_tag,
            "system_auto" if attempt_id else "manual_entry",
            confidence, trust_status, None, "v2", created_at,
        ),
    )


def _seed_manual_entry(
    conn,
    entry_id: str,
    *,
    node_id: str = "N1",
    error_tag: str = "general",
    created_at: str = W34_TUE,
    trust_status: str = "counted",
    mode: str = "M0",
) -> None:
    conn.execute(
        """
        insert into manual_error_entries(
          id, node_id, error_tag, source, trust_status, mode, recheck_count,
          parent_confirmed_at, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, node_id, error_tag, "child_self_report", trust_status, mode,
         0, None, created_at),
    )
    _seed_error_log(
        conn, f"L-{entry_id}", error_tag, trust_status, created_at,
        manual_entry_id=entry_id, node_id=node_id,
    )


def _seed_all_correct(conn, confirm_id: str, confirm_date: str, created_at: str) -> None:
    conn.execute(
        """
        insert into daily_all_correct_confirmations(
          id, confirm_date, confirmed_by, evidence_scope_mark, source_refs_json,
          created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (confirm_id, confirm_date, "child", "with_all_correct", "[]", created_at),
    )


class WeeklyReportServiceTestCase(unittest.TestCase):
    @contextmanager
    def _db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weekly-report.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                with conn:
                    for node_id in ("N1", "N2", "N3"):
                        _seed_node(conn, node_id)
                yield conn
            finally:
                conn.close()

    @staticmethod
    def _count(conn, table: str) -> int:
        return conn.execute(f"select count(*) as n from {table}").fetchone()["n"]

    @staticmethod
    def _week_row(conn, iso_week: str):
        return conn.execute(
            "select * from weekly_summary where iso_week = ?", (iso_week,)
        ).fetchone()


class WeeklyGenerateTestCase(WeeklyReportServiceTestCase):
    def test_generate_aggregates_snapshot_coverage_distribution(self):
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "A", W34_WED)
            _seed_learner_status(conn, "N2", "C", W33_MON)
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_attempt(conn, "a2", "N2", W34_WED)
            _seed_attempt(conn, "a3", "N1", W34_THU)
            _seed_error_log(conn, "l1", "general", "counted", W34_TUE,
                            attempt_id="a1", node_id="N1")
            _seed_error_log(conn, "l2", "concept_confusion", "counted", W34_WED,
                            attempt_id="a2", node_id="N2")
            _seed_error_log(conn, "l3", "general", "pending_parent", W34_THU,
                            attempt_id="a3", node_id="N1")

            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")

            self.assertEqual("2026-W34", result["iso_week"])
            self.assertEqual("unacknowledged", result["status"])
            # snapshot: all learner_node_status nodes with their status codes
            nodes = result["node_status_snapshot_json"]["nodes"]
            self.assertEqual({"N1": "A", "N2": "C"},
                             {k: v["status_code"] for k, v in nodes.items()})
            self.assertEqual(W34_END, result["node_status_snapshot_json"]["taken_at"])
            # coverage: union of attempt nodes within the week
            self.assertEqual({"N1", "N2"}, set(result["coverage_json"]["nodes"]))
            # distribution: only counted/rule_hit rows, pending_parent excluded
            self.assertEqual({"general": 1, "concept_confusion": 1},
                             result["error_distribution_json"])
            self.assertEqual("system_only", result["evidence_scope"])
            # row persisted
            row = self._week_row(conn, "2026-W34")
            self.assertIsNotNone(row)
            self.assertEqual("unacknowledged", row["status"])

    def test_coverage_includes_daily_summary_touched_nodes(self):
        with self._db() as conn:
            _seed_daily_summary(conn, "f1", "ds1", ["N1", "N3"], W34_TUE)
            _seed_attempt(conn, "a1", "N2", W34_WED)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual({"N1", "N2", "N3"},
                             set(result["coverage_json"]["nodes"]))

    def test_coverage_excludes_outside_week_attempts(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_attempt(conn, "a2", "N3", W33_MON)  # previous week
            _seed_attempt(conn, "a3", "N2", W35_MON)  # next week
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual({"N1"}, set(result["coverage_json"]["nodes"]))

    def test_error_distribution_counts_rule_hit_too(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_error_log(conn, "l1", "general", "counted", W34_TUE,
                            attempt_id="a1")
            _seed_error_log(conn, "l2", "process_habit", "rule_hit", W34_WED,
                            attempt_id="a1")
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual({"general": 1, "process_habit": 1},
                             result["error_distribution_json"])

    def test_generate_raises_on_invalid_iso_week(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                wrs.generate_weekly_summary(conn, iso_week="2026-34")
            with self.assertRaises(ValueError):
                wrs.generate_weekly_summary(conn, iso_week="2026-W99")


class WeeklyEvidenceScopeTestCase(WeeklyReportServiceTestCase):
    def test_scope_with_manual_when_counted_manual_entry_in_week(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_manual_entry(conn, "e1", node_id="N1", error_tag="general",
                               created_at=W34_WED, trust_status="counted")
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("with_manual", result["evidence_scope"])
            # the manual tag enters the distribution too
            self.assertEqual({"general": 1}, result["error_distribution_json"])

    def test_scope_system_only_when_manual_entry_pending(self):
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_manual_entry(conn, "e1", node_id="N1", error_tag="general",
                               created_at=W34_WED, trust_status="pending_parent")
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("system_only", result["evidence_scope"],
                             "未确认 (pending_parent) 手动条目不计入证据范围")
            self.assertEqual({}, result["error_distribution_json"])

    def test_scope_with_all_correct_when_confirmation_in_week(self):
        with self._db() as conn:
            _seed_all_correct(conn, "c1", "2026-08-18", W34_TUE)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("with_all_correct", result["evidence_scope"])

    def test_scope_manual_priority_over_all_correct(self):
        """Both present → with_manual wins (manual errors are the stronger
        qualification for the error-pattern statement; choice documented)."""
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            _seed_manual_entry(conn, "e1", node_id="N1", error_tag="general",
                               created_at=W34_WED, trust_status="counted")
            _seed_all_correct(conn, "c1", "2026-08-18", W34_TUE)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("with_manual", result["evidence_scope"])

    def test_scope_system_only_by_default(self):
        with self._db() as conn:
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("system_only", result["evidence_scope"])


class A1WarningTestCase(WeeklyReportServiceTestCase):
    def test_counter_2_node_warns_in_template_narrative(self):
        with self._db() as conn:
            _seed_decision(conn, "d1", "N3", new_status_code="C", created_at=W34_TUE)
            _seed_decision(conn, "d2", "N3", new_status_code="C", created_at=W34_WED)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34",
                                                 narrative_fn=None)
            self.assertEqual(
                [{"node_id": "N3", "cd_count": 2, "message": "已连续 2 次 C/D，注意"}],
                result["narrative_json"]["a1_warnings"],
            )
            self.assertIn("已连续 2 次 C/D，注意", result["narrative_json"]["text"],
                          "模板降级叙述也必须含 A1 预警文本")

    def test_counter_2_warning_survives_llm_narrative(self):
        """LLM 叙述正常返回但未提及预警 → 结构化 a1_warnings 仍必须注入."""

        def narrative_fn(payload):
            return {"text": "本周表现平稳，继续加油。"}

        with self._db() as conn:
            _seed_decision(conn, "d1", "N3", new_status_code="C", created_at=W34_TUE)
            _seed_decision(conn, "d2", "N3", new_status_code="C", created_at=W34_WED)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34",
                                                 narrative_fn=narrative_fn)
            self.assertEqual("llm", result["narrative_json"]["source"])
            self.assertEqual(
                [{"node_id": "N3", "cd_count": 2, "message": "已连续 2 次 C/D，注意"}],
                result["narrative_json"]["a1_warnings"],
                "A1 硬要求: narrative 必须含预警，不依赖 LLM 自觉",
            )
            # 预警也强制注入叙述文本，保证下游只读 text 也看得到
            self.assertIn("已连续 2 次 C/D，注意", result["narrative_json"]["text"])

    def test_counter_3_trigger_reset_does_not_warn(self):
        """连续 3 次 → 触发降级/回查并清零 → 计数 0 → 无需预警 (改档已发生)."""
        with self._db() as conn:
            for i, ts in enumerate((W34_TUE, W34_WED, W34_THU), start=1):
                _seed_decision(conn, f"d{i}", "N3", new_status_code="C", created_at=ts)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual([], result["narrative_json"]["a1_warnings"])

    def test_streak_broken_by_strong_verdict_does_not_warn(self):
        with self._db() as conn:
            _seed_decision(conn, "d1", "N3", new_status_code="C", created_at=W34_TUE)
            _seed_decision(conn, "d2", "N3", new_status_code="C", created_at=W34_WED)
            _seed_decision(conn, "d3", "N3", new_status_code="B", created_at=W34_THU)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual([], result["narrative_json"]["a1_warnings"])

    def test_warning_only_from_events_before_week_close(self):
        """下一周开始的判定事件不计入本周计数."""
        with self._db() as conn:
            _seed_decision(conn, "d1", "N3", new_status_code="C", created_at=W34_TUE)
            _seed_decision(conn, "d2", "N3", new_status_code="C", created_at=W35_MON)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual([], result["narrative_json"]["a1_warnings"],
                             "W35 的事件不属于本周")


class NarrativeDegradationTestCase(WeeklyReportServiceTestCase):
    def test_narrative_fn_raises_degrades_to_template(self):
        def broken_narrative_fn(payload):
            raise RuntimeError("LLM unavailable")

        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34",
                                                 narrative_fn=broken_narrative_fn)
            self.assertEqual("template", result["narrative_json"]["source"])
            self.assertTrue(result["narrative_json"]["degraded"])
            self.assertIn("N1", result["narrative_json"]["text"])
            # 行仍成功落库
            row = self._week_row(conn, "2026-W34")
            self.assertIsNotNone(row)

    def test_narrative_fn_none_uses_template(self):
        with self._db() as conn:
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual("template", result["narrative_json"]["source"])
            self.assertTrue(result["narrative_json"]["degraded"])

    def test_narrative_fn_text_is_used(self):
        def narrative_fn(payload):
            return {"text": "LLM 叙述：本周整体稳定。"}

        with self._db() as conn:
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34",
                                                 narrative_fn=narrative_fn)
            self.assertEqual("llm", result["narrative_json"]["source"])
            self.assertFalse(result["narrative_json"]["degraded"])
            self.assertIn("本周整体稳定", result["narrative_json"]["text"])

    def test_narrative_fn_bad_return_degrades(self):
        def bad_narrative_fn(payload):
            return "not a dict"

        with self._db() as conn:
            result = wrs.generate_weekly_summary(conn, iso_week="2026-W34",
                                                 narrative_fn=bad_narrative_fn)
            self.assertEqual("template", result["narrative_json"]["source"])
            self.assertTrue(result["narrative_json"]["degraded"])


class WeeklyUpsertTestCase(WeeklyReportServiceTestCase):
    def test_repeated_generation_upserts_single_row(self):
        """选择: iso_week 冲突 → UPSERT 更新 (重新生成 = 新版本), 不拒绝."""
        with self._db() as conn:
            _seed_attempt(conn, "a1", "N1", W34_TUE)
            first = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            # 新数据进入本周后再生成
            _seed_attempt(conn, "a2", "N2", W34_WED)
            second = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            self.assertEqual(1, self._count(conn, "weekly_summary"))
            self.assertEqual({"N1", "N2"}, set(second["coverage_json"]["nodes"]),
                             "UPSERT 用最新数据刷新 payload")
            row = self._week_row(conn, "2026-W34")
            self.assertEqual(second["id"], row["id"])
            self.assertEqual(first["id"], second["id"], "同一周保持同一行 id")
            self.assertEqual("unacknowledged", row["status"])


class WeeklyListTestCase(WeeklyReportServiceTestCase):
    def test_list_returns_archives_newest_first_with_limit(self):
        with self._db() as conn:
            wrs.generate_weekly_summary(conn, iso_week="2026-W33")
            wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            wrs.generate_weekly_summary(conn, iso_week="2026-W35")
            rows = wrs.list_weekly_summaries(conn)
            self.assertEqual(["2026-W35", "2026-W34", "2026-W33"],
                             [r["iso_week"] for r in rows])
            rows = wrs.list_weekly_summaries(conn, limit=2)
            self.assertEqual(["2026-W35", "2026-W34"],
                             [r["iso_week"] for r in rows])
            # 返回解析后的 payload 与状态
            self.assertEqual("system_only", rows[0]["evidence_scope"])
            self.assertEqual("unacknowledged", rows[0]["status"])

    def test_list_empty_when_no_archives(self):
        with self._db() as conn:
            self.assertEqual([], wrs.list_weekly_summaries(conn))


class WeeklyAcknowledgeTestCase(WeeklyReportServiceTestCase):
    def test_acknowledge_flips_status_and_batch_confirms_week(self):
        with self._db() as conn:
            _seed_manual_entry(conn, "e1", node_id="N1", error_tag="general",
                               created_at=W34_TUE, trust_status="pending_parent",
                               mode="M0")
            _seed_manual_entry(conn, "e2", node_id="N2", error_tag="general",
                               created_at=W34_WED, trust_status="pending_parent",
                               mode="M0")
            _seed_manual_entry(conn, "e-out", node_id="N3", error_tag="general",
                               created_at=W33_MON, trust_status="pending_parent",
                               mode="M0")
            summary = wrs.generate_weekly_summary(conn, iso_week="2026-W34")

            result = wrs.acknowledge_weekly_summary(conn, summary["id"])

            self.assertEqual("acknowledged", result["status"])
            self.assertIsNotNone(result["acknowledged_at"])
            self.assertEqual(2, result["batch_confirmed"]["processed"])
            row = self._week_row(conn, "2026-W34")
            self.assertEqual("acknowledged", row["status"])
            self.assertIsNotNone(row["acknowledged_at"])
            # 周信批量确认: 该周 M0 → M1
            for eid in ("e1", "e2"):
                entry = conn.execute(
                    "select mode, trust_status, parent_confirmed_at from"
                    " manual_error_entries where id = ?", (eid,)
                ).fetchone()
                self.assertEqual("M1", entry["mode"], f"{eid} 回溯标记为 M1")
                self.assertEqual("counted", entry["trust_status"])
                self.assertIsNotNone(entry["parent_confirmed_at"])
            # 周外条目不受影响
            out = conn.execute(
                "select mode from manual_error_entries where id = 'e-out'"
            ).fetchone()
            self.assertEqual("M0", out["mode"])

    def test_acknowledge_unknown_id_raises(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                wrs.acknowledge_weekly_summary(conn, "WS-NOPE")

    def test_acknowledge_is_idempotent(self):
        with self._db() as conn:
            summary = wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            first = wrs.acknowledge_weekly_summary(conn, summary["id"])
            second = wrs.acknowledge_weekly_summary(conn, summary["id"])
            self.assertEqual(first["acknowledged_at"], second["acknowledged_at"],
                             "重复确认不覆盖原确认时间")
            self.assertEqual(0, second["batch_confirmed"]["processed"],
                             "批量确认幂等: 已确认条目不再处理")


class WeeklySnapshotDiffTestCase(WeeklyReportServiceTestCase):
    def test_diff_reports_improved_worsened_new_removed(self):
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "B", W33_MON)
            _seed_learner_status(conn, "N2", "B", W33_MON)
            _seed_learner_status(conn, "N3", "B", W33_MON)
            wrs.generate_weekly_summary(conn, iso_week="2026-W33")
            # W34 状态变化: N1 B→A (绿了), N2 B→C (转差), N3 保持 B (不变)
            _set_learner_status(conn, "N1", "A", W34_WED)
            _set_learner_status(conn, "N2", "C", W34_WED)
            wrs.generate_weekly_summary(conn, iso_week="2026-W34")

            diff = wrs.weekly_snapshot_diff(conn, "2026-W33", "2026-W34")

            self.assertIn("N1", diff["improved"])
            self.assertIn("N1", diff["turned_a"])
            self.assertIn("N2", diff["worsened"])
            self.assertEqual([], diff["new"])
            changes = {c["node_id"]: c["direction"] for c in diff["changes"]}
            self.assertEqual("improved", changes["N1"])
            self.assertEqual("worsened", changes["N2"])
            self.assertEqual(1, diff["unchanged_count"], "N3 保持 B 计入不变")

    def test_diff_with_missing_prev_treats_all_as_new(self):
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "A", W34_WED)
            wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            diff = wrs.weekly_snapshot_diff(conn, "2026-W33", "2026-W34")
            self.assertEqual(["N1"], diff["new"])
            self.assertEqual([], diff["improved"])
            self.assertEqual([], diff["worsened"])

    def test_diff_falls_back_to_live_status_for_curr(self):
        """curr 周尚无存档行 → 用 learner_node_status 现况作为 curr 快照."""
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "B", W34_WED)
            diff = wrs.weekly_snapshot_diff(conn, "2026-W33", "2026-W34")
            self.assertEqual(["N1"], diff["new"])

    def test_diff_unchanged_nodes_not_in_changes(self):
        with self._db() as conn:
            _seed_learner_status(conn, "N1", "B", W33_MON)
            wrs.generate_weekly_summary(conn, iso_week="2026-W33")
            wrs.generate_weekly_summary(conn, iso_week="2026-W34")
            diff = wrs.weekly_snapshot_diff(conn, "2026-W33", "2026-W34")
            self.assertEqual([], diff["changes"])
            self.assertEqual(1, diff["unchanged_count"])


if __name__ == "__main__":
    unittest.main()
