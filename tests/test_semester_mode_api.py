"""Semester-mode service API endpoint tests (objective ②).

Contract under test: `learning_system/server.py` new endpoints wiring the
M4/M5 services (`manual_entry_service` / `weekly_report_service` /
`lightup_service` / `biweekly_brief_service`) behind HTTP.

Endpoints
---------
- 孩子面 (child-safe projection; no internal ids / graph / audit wording):
  - POST /api/manual-errors            — 错题录入 (M0, child selects node via
                                          the knowledge-map opaque handle)
  - GET  /api/lightup                  — 点亮视图 (name-only projection)
- 家长面 (operator Bearer token; internal ids allowed):
  - POST /api/operator/manual-errors/confirm             — M1 错题确认
  - POST /api/operator/weekly-summaries                  — 周信生成
  - POST /api/operator/weekly-summaries/{id}/acknowledge — 周信确认 + 批量确认通道
  - GET  /api/operator/biweekly-brief                    — 双周教研简报

child-safe 硬红线: every child-facing response must contain neither internal
ids (node_id / manual_entry_id / ME-* / M-*) nor forbidden wording
(图谱/节点/审计/内部状态/模型路由/…). The assertion helper runs
`internal_agents.FORBIDDEN_CHILD_PATTERNS` (the semantic source of truth) over
the serialized child payload plus explicit key-level checks.

Seed pattern mirrors tests/test_input_recognition_api.py (temp DB +
db.init_schema + db.seed_from_assets + per-test copy) with the knowledge-map
handle secret installed so opaque handles resolve.

Run: python3 -m unittest tests.test_semester_mode_api -v
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

from learning_system import (
    db,
    goal_choice_service,
    internal_agents,
    knowledge_map,
    server,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

HANDLE_SECRET_KEY = knowledge_map.HANDLE_SECRET_KEY
HANDLE_SECRET = "11" * 32  # 64 hex chars → 32 bytes


def _current_iso_week() -> str:
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def _iso_week_bounds(iso_week: str) -> tuple[datetime, datetime]:
    year, week = int(iso_week[:4]), int(iso_week[6:8])
    jan4 = date(year, 1, 4)
    monday_w1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = monday_w1 + timedelta(weeks=week - 1)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    return start, start + timedelta(weeks=1)


def _shift_iso_week(iso_week: str, delta: int) -> str:
    start, _ = _iso_week_bounds(iso_week)
    shifted = start + timedelta(weeks=delta)
    iso_year, iso_week_num, _ = shifted.isocalendar()
    return f"{iso_year:04d}-W{iso_week_num:02d}"


def _seed_learner_status(conn, node_id: str, status_code: str, updated_at: str) -> None:
    conn.execute(
        """
        insert into learner_node_status(
          node_id, status_code, latest_score, can_explain,
          evidence_attempt_ids_json, status_reason, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, status_code, 1.0, 1, "[]", "test-seed", updated_at),
    )


def _seed_decision(conn, decision_id: str, node_id: str, new_status_code: str, created_at: str) -> None:
    conn.execute(
        """
        insert into mastery_decisions(
          id, session_id, node_id, decision, closure_result,
          new_status_code, created_at
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (decision_id, "test-session", node_id, "verdict", "applied", new_status_code, created_at),
    )


class SemesterModeAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "semester-mode-seed.sqlite"
        conn = db.connect(cls._seed_path)
        try:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            with conn:
                conn.execute(
                    "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                    (HANDLE_SECRET_KEY, HANDLE_SECRET, db.now_iso()),
                )
            cls._node_rows = [
                dict(row)
                for row in conn.execute(
                    "select id, name from graph_nodes order by id limit 2"
                ).fetchall()
            ]
            if len(cls._node_rows) != 2:
                raise AssertionError("seed graph must contain at least 2 nodes")
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "semester-mode.sqlite"
        shutil.copy2(self._seed_path, self.db_path)
        self.env = mock.patch.dict(
            os.environ,
            {
                "V3_DAILY_RUNTIME_ENABLED": "0",
                "ANSWER_ASSESSMENT_POLICY": "",
                "KNOWLEDGE_MAP_HOME_POLICY": "1",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.httpd, self.base_url = server.start_test_server(self.db_path)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # 孩子面: 错题录入
    # ------------------------------------------------------------------

    def test_child_manual_error_entry_records_m0_and_returns_child_safe_projection(self):
        node = self._node_rows[0]
        handle = self._node_handle(self.db_path, node["id"])
        response = self._request_json(
            "POST",
            "/api/manual-errors",
            {
                "handle": handle,
                "error_tag_key": "careless",
                "client_idempotency_key": "child-entry-1",
            },
        )

        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual("recorded", body["status"])
        self.assertEqual(node["name"], body["node_name"])
        self.assertEqual("算错或写错", body["error_cause_label"])
        self.assertEqual("child-entry-1", body["client_idempotency_key"])
        self.assertIn("已经记下来了", body["message"])
        self._assert_child_safe(body)
        # 孩子响应绝不携带内部标识/状态机字段
        serialized = json.dumps(body, ensure_ascii=False)
        for internal in (
            "manual_entry_id",
            "node_id",
            "error_tag",
            "trust_status",
            "mode",
            "recheck",
            "parent_confirmed",
            "retest",
            "ME-",
        ):
            self.assertNotIn(internal, serialized)

        with closing(db.connect(self.db_path)) as conn:
            rows = conn.execute(
                "select * from manual_error_entries"
            ).fetchall()
            self.assertEqual(1, len(rows))
            entry = dict(rows[0])
            self.assertEqual(node["id"], entry["node_id"])
            self.assertEqual("calculation_or_symbol", entry["error_tag"])
            self.assertEqual("child_self_report", entry["source"])
            self.assertEqual("M0", entry["mode"])
            self.assertEqual("pending_parent", entry["trust_status"])
            self.assertIsNotNone(entry["retest_triggered_at"])  # M0 也触发一次复测信号
            logs = conn.execute("select * from error_cause_log").fetchall()
            self.assertEqual(1, len(logs))
            self.assertEqual("calculation_or_symbol", logs[0]["error_tag"])

    def test_child_manual_error_entry_rejects_unknown_handle_without_writing(self):
        response = self._request_json(
            "POST",
            "/api/manual-errors",
            {
                "handle": "kn51n." + "0" * 64,
                "error_tag_key": "careless",
                "client_idempotency_key": "child-entry-bad-handle",
            },
        )
        self.assertEqual(409, response["status"], response["raw"])
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(
                0, conn.execute("select count(*) from manual_error_entries").fetchone()[0]
            )

    def test_child_manual_error_entry_rejects_unknown_tag_key_without_writing(self):
        node = self._node_rows[0]
        handle = self._node_handle(self.db_path, node["id"])
        response = self._request_json(
            "POST",
            "/api/manual-errors",
            {
                "handle": handle,
                "error_tag_key": "not-a-real-cause",
                "client_idempotency_key": "child-entry-bad-tag",
            },
        )
        self.assertEqual(400, response["status"], response["raw"])
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(
                0, conn.execute("select count(*) from manual_error_entries").fetchone()[0]
            )

    # ------------------------------------------------------------------
    # 孩子面: 点亮视图
    # ------------------------------------------------------------------

    def test_lightup_child_projection_is_name_only(self):
        week = _current_iso_week()
        week_start, _ = _iso_week_bounds(week)
        node_a, node_b = self._node_rows
        with closing(db.connect(self.db_path)) as conn:
            with conn:
                _seed_learner_status(
                    conn, node_a["id"], "A",
                    (week_start + timedelta(days=1)).isoformat(),
                )
                _seed_learner_status(
                    conn, node_b["id"], "C",
                    (week_start - timedelta(days=2)).isoformat(),
                )
                # node_a: 上周 B → 本周 A (本周点亮); node_b: 上周 C, 无变化.
                _seed_decision(
                    conn, "d1", node_a["id"], "B",
                    (week_start - timedelta(days=1)).isoformat(),
                )
                _seed_decision(
                    conn, "d2", node_a["id"], "A",
                    (week_start + timedelta(days=1)).isoformat(),
                )
                _seed_decision(
                    conn, "d3", node_b["id"], "C",
                    (week_start - timedelta(days=2)).isoformat(),
                )

        response = self._request_json("GET", "/api/lightup")
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]

        self.assertEqual("lightup-child.v1", body["schema_version"])
        self.assertIn("已点亮", body["summary"]["progress_line"])
        self.assertGreaterEqual(body["summary"]["total"], 2)
        self.assertGreaterEqual(body["summary"]["mastered"], 1)
        lit_names = [item["name"] for item in body["this_week"]["lit_up"]]
        self.assertIn(node_a["name"], lit_names)
        self.assertNotIn(node_b["name"], lit_names)
        milestone_names = [item["name"] for item in body["milestones"]]
        self.assertIn(node_a["name"], milestone_names)
        for item in body["this_week"]["lit_up"]:
            self.assertTrue(item["from_label"])
            self.assertTrue(item["to_label"])
        self._assert_child_safe(body)
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn("nodes", body)  # 服务原始 nodes 字典 (node_id 键) 必须被剔除
        for internal in (
            "node_id",
            "status_code",
            "mastery_decisions",
            "learner_node_status",
            "ME-",
            "updated_at",
        ):
            self.assertNotIn(internal, serialized)

    # ------------------------------------------------------------------
    # 家长面: 错题确认 (M1)
    # ------------------------------------------------------------------

    def test_operator_manual_error_confirm_upgrades_m0_to_m1(self):
        entry_id = self._record_child_entry()
        response = self._request_json(
            "POST",
            "/api/operator/manual-errors/confirm",
            {"manual_entry_id": entry_id, "confirmed_by": "parent"},
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual(entry_id, body["manual_entry_id"])
        self.assertEqual("M1", body["mode"])
        self.assertEqual("counted", body["trust_status"])
        self.assertEqual(1, body["recheck_count"])
        self.assertTrue(body["parent_confirmed_at"])

        with closing(db.connect(self.db_path)) as conn:
            entry = dict(conn.execute(
                "select * from manual_error_entries where id = ?", (entry_id,)
            ).fetchone())
            self.assertEqual("M1", entry["mode"])
            self.assertEqual("counted", entry["trust_status"])
            self.assertEqual(1, entry["recheck_count"])

    def test_operator_manual_error_confirm_unknown_entry_returns_404(self):
        response = self._request_json(
            "POST",
            "/api/operator/manual-errors/confirm",
            {"manual_entry_id": "ME-does-not-exist"},
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(404, response["status"], response["raw"])

    def test_operator_endpoints_require_bearer_token(self):
        response = self._request_json(
            "POST",
            "/api/operator/manual-errors/confirm",
            {"manual_entry_id": "ME-x"},
        )
        self.assertEqual(403, response["status"], response["raw"])
        brief = self._request_json(
            "GET",
            f"/api/operator/biweekly-brief?end_iso_week={_current_iso_week()}",
        )
        self.assertEqual(403, brief["status"], brief["raw"])

    # ------------------------------------------------------------------
    # 家长面: 周信生成 + 确认 (批量确认通道)
    # ------------------------------------------------------------------

    def test_operator_weekly_summary_generate_and_acknowledge_runs_batch_channel(self):
        entry_id = self._record_child_entry()
        week = _current_iso_week()

        generated = self._request_json(
            "POST",
            "/api/operator/weekly-summaries",
            {"iso_week": week},
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(200, generated["status"], generated["raw"])
        gen = generated["body"]
        self.assertEqual(week, gen["iso_week"])
        self.assertEqual("unacknowledged", gen["status"])
        self.assertEqual("template", gen["narrative_json"]["source"])
        self.assertIn("下周重点", gen["narrative_json"]["text"])
        summary_id = gen["id"]

        acknowledged = self._request_json(
            "POST",
            f"/api/operator/weekly-summaries/{summary_id}/acknowledge",
            {"acknowledged_by": "parent"},
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(200, acknowledged["status"], acknowledged["raw"])
        ack = acknowledged["body"]
        self.assertEqual(summary_id, ack["summary_id"])
        self.assertEqual("acknowledged", ack["status"])
        # 周信批量确认通道: 该周未确认的 M0 手动错题被批量升级为 M1.
        self.assertGreaterEqual(ack["batch_confirmed"]["processed"], 1)

        with closing(db.connect(self.db_path)) as conn:
            entry = dict(conn.execute(
                "select * from manual_error_entries where id = ?", (entry_id,)
            ).fetchone())
            self.assertEqual("M1", entry["mode"])
            self.assertEqual("counted", entry["trust_status"])
            summary = conn.execute(
                "select status from weekly_summary where id = ?", (summary_id,)
            ).fetchone()
            self.assertEqual("acknowledged", summary["status"])

    def test_operator_weekly_summary_rejects_malformed_iso_week(self):
        response = self._request_json(
            "POST",
            "/api/operator/weekly-summaries",
            {"iso_week": "not-a-week"},
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(400, response["status"], response["raw"])

    # ------------------------------------------------------------------
    # 家长面: 双周教研简报
    # ------------------------------------------------------------------

    def test_operator_biweekly_brief_returns_structured_report(self):
        self._record_child_entry()
        week = _current_iso_week()
        response = self._request_json(
            "GET",
            f"/api/operator/biweekly-brief?end_iso_week={week}&period_weeks=2",
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual(week, body["period"]["end_iso_week"])
        self.assertEqual(2, body["period"]["period_weeks"])
        self.assertIsInstance(body["error_distribution"], dict)
        self.assertIn("evidence_scope", body)
        self.assertIsInstance(body["stalled_nodes"], list)
        self.assertIsInstance(body["high_attempt_nodes"], list)
        self.assertIsInstance(body["weekly_letters"], list)
        self.assertEqual("template", body["narrative"]["source"])
        self.assertTrue(body["narrative"]["text"])

    # ------------------------------------------------------------------
    # 孩子面: 每周自选目标 (M5 动机层②, 有护栏的自主)
    # ------------------------------------------------------------------

    def test_goal_candidates_child_projection_is_name_handle_only(self):
        """GET /api/goal-candidates: 只暴露 name/reason_label/node_handle,
        绝不暴露 node_id/stage/priority/candidate_kind 等内部字段."""
        response = self._request_json("GET", "/api/goal-candidates")
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual("goal-candidates-child.v1", body["schema_version"])
        self.assertEqual(_current_iso_week(), body["iso_week"])
        self.assertTrue(body["candidates"])
        for cand in body["candidates"]:
            self.assertEqual({"name", "reason_label", "node_handle"}, set(cand.keys()))
        # 默认种子无状态 → 无薄弱证据, 只有主线候选 (推进序第一个未掌握节点).
        mainline = body["candidates"][0]
        self.assertEqual("正数和负数", mainline["name"])
        self.assertEqual("接下来该学这块", mainline["reason_label"])
        # opaque handle 与本地 mint 一致 (孩子可回传, 服务端反解).
        self.assertEqual(
            self._node_handle(self.db_path, "M-G7-POS-NEG"),
            mainline["node_handle"],
        )
        self._assert_child_safe(body)
        serialized = json.dumps(body, ensure_ascii=False)
        for internal in (
            "node_id",
            "stage",
            "priority",
            "candidate_kind",
            "M-G7-",
            "sequence_band",
            "unlocks",
            "status_code",
        ):
            self.assertNotIn(internal, serialized)

    def test_goal_candidates_include_weakness_when_status_seeded(self):
        """有 C/D 状态 → 薄弱候选排在首位, 文案是孩子可读的 '这块有点薄弱'."""
        with closing(db.connect(self.db_path)) as conn:
            with conn:
                _seed_learner_status(conn, "M-BRIDGE-CLOCK-ANGLE", "C", db.now_iso())
        response = self._request_json("GET", "/api/goal-candidates")
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertGreaterEqual(len(body["candidates"]), 2)
        weakness = body["candidates"][0]
        self.assertEqual("钟表角问题", weakness["name"])
        self.assertEqual("这块有点薄弱", weakness["reason_label"])
        self.assertEqual(
            self._node_handle(self.db_path, "M-BRIDGE-CLOCK-ANGLE"),
            weakness["node_handle"],
        )
        self._assert_child_safe(body)

    def test_goal_choice_records_child_selection_child_safe(self):
        """POST /api/goal-choice: 反解 handle → 落库 (当周, chosen_by=child),
        响应 child-safe (名称列表 + 孩子措辞, 无内部 id/状态)."""
        with closing(db.connect(self.db_path)) as conn:
            with conn:
                _seed_learner_status(conn, "M-BRIDGE-CLOCK-ANGLE", "C", db.now_iso())
        candidates = self._request_json("GET", "/api/goal-candidates")["body"]["candidates"]
        handles = [c["node_handle"] for c in candidates[:2]]
        names = [c["name"] for c in candidates[:2]]

        response = self._request_json(
            "POST",
            "/api/goal-choice",
            {
                "candidate_handles": handles,
                "client_idempotency_key": "goal-choice-1",
            },
        )
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual("goal-choice-child.v1", body["schema_version"])
        self.assertEqual("recorded", body["status"])
        self.assertIn("已选好下周目标", body["message"])
        self.assertEqual(names, body["node_names"])
        self.assertEqual("goal-choice-1", body["client_idempotency_key"])
        self._assert_child_safe(body)
        serialized = json.dumps(body, ensure_ascii=False)
        for internal in (
            "node_id",
            "GC-",
            "chosen_by",
            "stage",
            "priority",
            "iso_week",
            "created_at",
            "updated_at",
        ):
            self.assertNotIn(internal, serialized)

        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute("select * from weekly_goal_choices").fetchone()
            self.assertIsNotNone(row)
            record = dict(row)
            self.assertEqual(_current_iso_week(), record["iso_week"])
            self.assertEqual("child", record["chosen_by"])
            node_ids = db.json_load(record["node_ids_json"], [])
            self.assertEqual(len(handles), len(node_ids))
            for node_id in node_ids:
                self.assertIn(node_id, {"M-BRIDGE-CLOCK-ANGLE", "M-G7-POS-NEG"})

    def test_goal_choice_rejects_unknown_handle_without_writing(self):
        response = self._request_json(
            "POST",
            "/api/goal-choice",
            {
                "candidate_handles": ["kn51n." + "0" * 64],
                "client_idempotency_key": "goal-choice-bad-handle",
            },
        )
        self.assertEqual(409, response["status"], response["raw"])
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(
                0, conn.execute("select count(*) from weekly_goal_choices").fetchone()[0]
            )

    def test_goal_choice_rejects_blank_handle_without_writing(self):
        response = self._request_json(
            "POST",
            "/api/goal-choice",
            {
                "candidate_handles": [""],
                "client_idempotency_key": "goal-choice-blank-handle",
            },
        )
        self.assertEqual(409, response["status"], response["raw"])
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(
                0, conn.execute("select count(*) from weekly_goal_choices").fetchone()[0]
            )

    def test_goal_choice_rejects_invalid_selection_without_writing(self):
        for payload in (
            {"candidate_handles": [], "client_idempotency_key": "k-empty"},
            {"candidate_handles": ["h1", "h2", "h3"], "client_idempotency_key": "k-three"},
            {"candidate_handles": "not-a-list", "client_idempotency_key": "k-notlist"},
            {"candidate_handles": ["same", "same"], "client_idempotency_key": "k-dup"},
        ):
            response = self._request_json("POST", "/api/goal-choice", payload)
            self.assertEqual(400, response["status"], response["raw"])
            self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(
                0, conn.execute("select count(*) from weekly_goal_choices").fetchone()[0]
            )

    # ------------------------------------------------------------------
    # 家长面: 目标选择查看 (当前选择 + 历史)
    # ------------------------------------------------------------------

    def test_operator_goal_choice_requires_bearer_token(self):
        response = self._request_json("GET", "/api/operator/goal-choice")
        self.assertEqual(403, response["status"], response["raw"])

    def test_operator_goal_choice_returns_current_and_history(self):
        with closing(db.connect(self.db_path)) as conn:
            with conn:
                _seed_learner_status(conn, "M-BRIDGE-CLOCK-ANGLE", "C", db.now_iso())
        candidates = self._request_json("GET", "/api/goal-candidates")["body"]["candidates"]
        handles = [c["node_handle"] for c in candidates[:2]]
        self._request_json(
            "POST",
            "/api/goal-choice",
            {"candidate_handles": handles, "client_idempotency_key": "op-1"},
        )

        response = self._request_json(
            "GET", "/api/operator/goal-choice", token=server.TEST_OPERATOR_TOKEN
        )
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertEqual("operator-goal-choice.v1", body["schema_version"])
        current = body["current"]
        self.assertIsNotNone(current)
        self.assertEqual(_current_iso_week(), current["iso_week"])
        self.assertEqual("child", current["chosen_by"])
        self.assertIn("GC-", current["id"])
        self.assertEqual(2, len(current["node_ids"]))
        self.assertEqual(2, len(current["nodes"]))
        for node in current["nodes"]:
            self.assertIn("node_id", node)  # 家长面是信任方, 可暴露内部标识
            self.assertIn("name", node)
        self.assertTrue(body["history"])
        self.assertEqual(current["iso_week"], body["history"][0]["iso_week"])

    def test_operator_goal_choice_other_week_record_not_current(self):
        """别周: 过去周的选择不串到当前周 — 当前周 current=null, 历史可见;
        指定 iso_week 可查别周记录."""
        past_week = _shift_iso_week(_current_iso_week(), -2)
        with closing(db.connect(self.db_path)) as conn:
            goal_choice_service.record_goal_choice(
                conn, iso_week=past_week, node_ids=["M-G7-POS-NEG"],
                chosen_by="parent", commit=True,
            )

        response = self._request_json(
            "GET", "/api/operator/goal-choice", token=server.TEST_OPERATOR_TOKEN
        )
        self.assertEqual(200, response["status"], response["raw"])
        body = response["body"]
        self.assertIsNone(body["current"])
        weeks = [r["iso_week"] for r in body["history"]]
        self.assertIn(past_week, weeks)

        other = self._request_json(
            "GET",
            f"/api/operator/goal-choice?iso_week={past_week}",
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(200, other["status"], other["raw"])
        self.assertEqual(past_week, other["body"]["current"]["iso_week"])

    def test_operator_goal_choice_rejects_malformed_iso_week(self):
        response = self._request_json(
            "GET",
            "/api/operator/goal-choice?iso_week=not-a-week",
            token=server.TEST_OPERATOR_TOKEN,
        )
        self.assertEqual(400, response["status"], response["raw"])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _record_child_entry(self) -> str:
        node = self._node_rows[0]
        handle = self._node_handle(self.db_path, node["id"])
        response = self._request_json(
            "POST",
            "/api/manual-errors",
            {
                "handle": handle,
                "error_tag_key": "other",
                "client_idempotency_key": f"child-entry-{id(self)}",
            },
        )
        self.assertEqual(200, response["status"], response["raw"])
        with closing(db.connect(self.db_path)) as conn:
            return conn.execute(
                "select id from manual_error_entries order by created_at desc limit 1"
            ).fetchone()["id"]

    @staticmethod
    def _node_handle(db_path: Path, node_id: str) -> str:
        with closing(db.connect(db_path)) as conn:
            secret_row = conn.execute(
                "select value from system_meta where key = ?", (HANDLE_SECRET_KEY,)
            ).fetchone()
            ref = db.json_load(
                conn.execute(
                    "select value from system_meta where key = 'graph_ref'"
                ).fetchone()["value"],
                {},
            )
        secret = knowledge_map._secret_bytes(secret_row["value"])
        return knowledge_map._opaque_handle(
            secret,
            domain="node",
            graph_lineage=str(ref["lineage"]),
            canonical_id=node_id,
        )

    def _request_json(self, method, path, payload=None, token=None):
        host, port = self.base_url.replace("http://", "").split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=10)
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            return {"status": response.status, "body": json.loads(raw), "raw": raw}
        finally:
            conn.close()

    def _assert_child_safe(self, payload):
        """孩子面响应不得含任何内部 id / 图谱 / 审计 / 状态机措辞 (语义源:
        internal_agents.FORBIDDEN_CHILD_PATTERNS)."""
        serialized = json.dumps(payload, ensure_ascii=False)
        for pattern in internal_agents.FORBIDDEN_CHILD_PATTERNS:
            match = pattern.search(serialized)
            self.assertIsNone(
                match,
                f"child payload leaks forbidden pattern {pattern.pattern!r}: {serialized}",
            )


if __name__ == "__main__":
    unittest.main()
