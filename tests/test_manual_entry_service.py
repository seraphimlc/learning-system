"""M4-2 manual wrong-question entry service tests.

Contract under test: `learning_system/manual_entry_service.py` — the 录入侧
DB service layer with M0/M1 semantics (docs/design/specs/2026-08-20-mastery-criteria-proposal.md §3,
会审修订):

- M0 (孩子自录, 未确认): 触发一次系统内复测 (teaching action) → `retest=True` 信号;
  判定侧零作用 — no judgment event, no counting, no downgrade, no archive write.
- M1 (爸爸确认, 含周信批量确认通道): action-layer independent count (threshold 3);
  3 M1 confirmations → `recheck_triggered=True` + counter reset; 永不直接降档/D;
  永不写 mastery_decisions / learner_node_status.
- Trust boundary (§3.2): 低置信 (confidence < MIN_CONFIDENCE_TO_COUNT=0.68) 且未确认
  → `trust_status='pending_parent'`，不入错因分布; 爸爸确认或 rule_hit 才计入分布
  (分布查询纪律: trust_status IN ('counted','rule_hit')).

Seed pattern mirrors tests/test_planner_trace_back_integration.py
(temp DB + db.init_schema + few graph_nodes).

Run: python3 -m unittest tests.test_manual_entry_service -v
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from learning_system import db
from learning_system import manual_entry_service as mes
from learning_system.error_tags import CANONICAL_ERROR_TAGS

# Fixed ISO-8601 timestamps: 2026-08-17 is the Monday of ISO week 2026-W34.
W34_TUE = "2026-08-18T09:00:00+00:00"
W34_WED = "2026-08-19T09:00:00+00:00"
W34_THU = "2026-08-20T09:00:00+00:00"
W33_MON = "2026-08-10T09:00:00+00:00"
W35_TUE = "2026-08-25T09:00:00+00:00"


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


def _seed_entry(
    conn,
    entry_id: str,
    *,
    node_id: str = "N1",
    error_tag: str = "general",
    created_at: str = W34_TUE,
    mode: str = "M0",
    trust_status: str = "pending_parent",
    recheck_count: int = 0,
    parent_confirmed_at: str | None = None,
    confidence: float | None = None,
) -> None:
    conn.execute(
        """
        insert into manual_error_entries(
          id, node_id, error_tag, source, trust_status, mode, recheck_count,
          parent_confirmed_at, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id, node_id, error_tag, "child_self_report", trust_status, mode,
            recheck_count, parent_confirmed_at, created_at,
        ),
    )
    conn.execute(
        """
        insert into error_cause_log(
          id, attempt_id, manual_entry_id, node_id, error_tag, source,
          confidence, trust_status, parent_confirmed_at, graph_version, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"L-{entry_id}", None, entry_id, node_id, error_tag, "manual_entry",
            confidence, trust_status, parent_confirmed_at, "", created_at,
        ),
    )
    conn.commit()


class ManualEntryServiceTestCase(unittest.TestCase):
    @contextmanager
    def _db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manual-entry.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                with conn:
                    _seed_node(conn, "N1")
                    _seed_node(conn, "N2")
                yield conn
            finally:
                conn.close()

    @staticmethod
    def _count(conn, table: str) -> int:
        return conn.execute(f"select count(*) as n from {table}").fetchone()["n"]

    @staticmethod
    def _distribution(conn) -> dict[str, int]:
        """Distribution query discipline: only counted/rule_hit rows count."""
        rows = conn.execute(
            "select error_tag, count(*) as n from error_cause_log"
            " where trust_status in ('counted', 'rule_hit')"
            " group by error_tag order by error_tag"
        ).fetchall()
        return {row["error_tag"]: row["n"] for row in rows}

    # --- M0 recording -----------------------------------------------------

    def test_record_m0_emits_retest_signal_only(self):
        with self._db() as conn:
            result = mes.record_manual_error(conn, node_id="N1", error_tag="concept_confusion")
            self.assertTrue(result["retest"], "M0 must emit the retest signal")
            self.assertEqual("M0", result["mode"])
            self.assertEqual("pending_parent", result["trust_status"])
            self.assertEqual(0, result["recheck_count"], "M0 不计数")
            self.assertFalse(result["parent_confirmed"])
            self.assertIsNotNone(result["manual_entry_id"])

    def test_record_m0_writes_both_rows_and_zero_judgment_side(self):
        with self._db() as conn:
            result = mes.record_manual_error(conn, node_id="N1", error_tag="process_habit")
            entry = conn.execute(
                "select * from manual_error_entries where id = ?",
                (result["manual_entry_id"],),
            ).fetchone()
            self.assertIsNotNone(entry)
            self.assertEqual("M0", entry["mode"])
            self.assertEqual("pending_parent", entry["trust_status"])
            self.assertEqual(0, entry["recheck_count"])
            self.assertIsNone(entry["parent_confirmed_at"])
            self.assertIsNotNone(entry["retest_triggered_at"])

            log = conn.execute(
                "select * from error_cause_log where manual_entry_id = ?",
                (result["manual_entry_id"],),
            ).fetchone()
            self.assertIsNotNone(log)
            self.assertIsNone(log["attempt_id"], "manual entries never reference attempts")
            self.assertEqual("manual_entry", log["source"])
            self.assertEqual("pending_parent", log["trust_status"])

            # 判定侧零作用: M0 不产判定事件、不写档案
            self.assertEqual(0, self._count(conn, "mastery_decisions"))
            self.assertEqual(0, self._count(conn, "learner_node_status"))

    def test_high_confidence_m0_counts_in_distribution_without_confirmation(self):
        with self._db() as conn:
            result = mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=0.9)
            self.assertEqual("counted", result["trust_status"])
            self.assertEqual("M0", result["mode"], "high confidence does not upgrade mode")
            self.assertEqual({"general": 1}, self._distribution(conn))

    def test_low_confidence_m0_stays_pending_parent_outside_distribution(self):
        with self._db() as conn:
            result = mes.record_manual_error(conn, node_id="N1", error_tag="calculation_or_symbol", confidence=0.4)
            self.assertEqual("pending_parent", result["trust_status"])
            self.assertEqual("M0", result["mode"])
            self.assertEqual({}, self._distribution(conn), "低置信 pending_parent 不入分布")

    def test_confidence_at_threshold_counts(self):
        with self._db() as conn:
            result = mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=mes.MIN_CONFIDENCE_TO_COUNT)
            self.assertEqual("counted", result["trust_status"])
            self.assertEqual({"general": 1}, self._distribution(conn))

    def test_out_of_range_confidence_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=1.5)
            with self.assertRaises(ValueError):
                mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=-0.1)

    # --- M1 recording / confirmation --------------------------------------

    def test_record_m1_when_parent_confirmed(self):
        with self._db() as conn:
            result = mes.record_manual_error(
                conn, node_id="N1", error_tag="modeling_or_reading",
                parent_confirmed=True, confidence=0.3,
            )
            self.assertTrue(result["retest"], "M1 also triggers one retest (§3)")
            self.assertEqual("M1", result["mode"])
            self.assertEqual("counted", result["trust_status"],
                             "爸爸确认 = 高信任，低置信也计入")
            self.assertEqual(1, result["recheck_count"], "1 条 M1 = 动作层计数 +1")
            self.assertIsNotNone(result["parent_confirmed_at"])
            entry = conn.execute(
                "select * from manual_error_entries where id = ?",
                (result["manual_entry_id"],),
            ).fetchone()
            self.assertEqual("counted", entry["trust_status"])
            self.assertEqual(1, entry["recheck_count"])
            self.assertEqual(0, self._count(conn, "mastery_decisions"))

    def test_confirm_upgrades_m0_to_m1_and_increments_count(self):
        with self._db() as conn:
            rec = mes.record_manual_error(conn, node_id="N1", error_tag="visual_spatial", confidence=0.4)
            self.assertEqual("pending_parent", rec["trust_status"])
            result = mes.confirm_manual_error(conn, rec["manual_entry_id"])
            self.assertEqual("M1", result["mode"])
            self.assertEqual("counted", result["trust_status"])
            self.assertEqual(1, result["recheck_count"])
            self.assertFalse(result["recheck_triggered"])
            self.assertIsNotNone(result["parent_confirmed_at"])

            entry = conn.execute(
                "select * from manual_error_entries where id = ?",
                (rec["manual_entry_id"],),
            ).fetchone()
            self.assertEqual("M1", entry["mode"])
            self.assertEqual("counted", entry["trust_status"])
            self.assertEqual(1, entry["recheck_count"])
            self.assertIsNotNone(entry["parent_confirmed_at"])
            log = conn.execute(
                "select * from error_cause_log where manual_entry_id = ?",
                (rec["manual_entry_id"],),
            ).fetchone()
            self.assertEqual("counted", log["trust_status"])
            self.assertIsNotNone(log["parent_confirmed_at"])
            # 爸爸确认后入分布
            self.assertEqual({"visual_spatial": 1}, self._distribution(conn))

    def test_three_m1_confirmations_trigger_recheck_and_reset(self):
        with self._db() as conn:
            rec = mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=0.4)
            first = mes.confirm_manual_error(conn, rec["manual_entry_id"])
            self.assertEqual(1, first["recheck_count"])
            self.assertFalse(first["recheck_triggered"])
            second = mes.confirm_manual_error(conn, rec["manual_entry_id"])
            self.assertEqual(2, second["recheck_count"])
            self.assertFalse(second["recheck_triggered"])
            third = mes.confirm_manual_error(conn, rec["manual_entry_id"])
            self.assertTrue(third["recheck_triggered"])
            self.assertEqual(0, third["recheck_count"], "触发后清零")
            self.assertIsNotNone(third["recheck_triggered_at"])

            entry = conn.execute(
                "select * from manual_error_entries where id = ?",
                (rec["manual_entry_id"],),
            ).fetchone()
            self.assertEqual(0, entry["recheck_count"])
            self.assertIsNotNone(entry["recheck_triggered_at"])
            # 永不写判定侧（动作层独立计数，只触发回查、不降档、不写 D）
            self.assertEqual(0, self._count(conn, "mastery_decisions"))
            self.assertEqual(0, self._count(conn, "learner_node_status"))
            self.assertNotIn("D", {r["new_status_code"] for r in conn.execute(
                "select new_status_code from mastery_decisions"
            ).fetchall()})

    def test_confirm_unknown_entry_raises(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                mes.confirm_manual_error(conn, "ME-NOPE")

    # --- rule hit ---------------------------------------------------------

    def test_rule_hit_counts_low_confidence_in_distribution(self):
        with self._db() as conn:
            rec = mes.record_manual_error(conn, node_id="N1", error_tag="calculation_or_symbol", confidence=0.4)
            self.assertEqual("pending_parent", rec["trust_status"])
            result = mes.mark_rule_hit(conn, rec["manual_entry_id"])
            self.assertEqual("rule_hit", result["trust_status"])
            self.assertTrue(result["changed"])
            log = conn.execute(
                "select * from error_cause_log where manual_entry_id = ?",
                (rec["manual_entry_id"],),
            ).fetchone()
            self.assertEqual("rule_hit", log["trust_status"])
            self.assertEqual({"calculation_or_symbol": 1}, self._distribution(conn),
                             "低置信但规则命中可入分布")

    def test_rule_hit_is_idempotent_noop_when_already_counted(self):
        with self._db() as conn:
            rec = mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=0.9)
            result = mes.mark_rule_hit(conn, rec["manual_entry_id"])
            self.assertEqual("counted", result["trust_status"])
            self.assertFalse(result["changed"])
            log = conn.execute(
                "select trust_status from error_cause_log where manual_entry_id = ?",
                (rec["manual_entry_id"],),
            ).fetchone()
            self.assertEqual("counted", log["trust_status"])

    # --- validation -------------------------------------------------------

    def test_unknown_node_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                mes.record_manual_error(conn, node_id="GHOST-NODE", error_tag="general")

    def test_non_canonical_tag_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                mes.record_manual_error(conn, node_id="N1", error_tag="not_a_canonical_tag")
            # every canonical tag is accepted
            for tag in sorted(CANONICAL_ERROR_TAGS):
                result = mes.record_manual_error(conn, node_id="N1", error_tag=tag)
                self.assertEqual(tag, result["error_tag"])

    # --- weekly batch confirmation (周信批量确认通道) -------------------------

    def test_week_batch_confirm_upgrades_only_that_week(self):
        with self._db() as conn:
            _seed_entry(conn, "e1", created_at=W34_TUE)
            _seed_entry(conn, "e2", created_at=W34_WED)
            _seed_entry(conn, "e3", created_at=W34_THU)
            _seed_entry(conn, "e-out-before", created_at=W33_MON)
            _seed_entry(conn, "e-out-after", created_at=W35_TUE)
            _seed_entry(conn, "e-m1", mode="M1", trust_status="counted",
                        recheck_count=1, parent_confirmed_at=W34_WED)

            result = mes.confirm_week_manual_errors(conn, iso_week="2026-W34")
            self.assertEqual(3, result["processed"])
            self.assertEqual(0, result["recheck_triggered"])
            self.assertEqual("2026-W34", result["iso_week"])

            for eid in ("e1", "e2", "e3"):
                row = conn.execute(
                    "select mode, trust_status, parent_confirmed_at, recheck_count"
                    " from manual_error_entries where id = ?", (eid,),
                ).fetchone()
                self.assertEqual("M1", row["mode"], f"{eid} 回溯标记为 M1")
                self.assertEqual("counted", row["trust_status"])
                self.assertIsNotNone(row["parent_confirmed_at"])
                self.assertEqual(1, row["recheck_count"])
            # outside-week and already-M1 entries untouched
            for eid in ("e-out-before", "e-out-after", "e-m1"):
                row = conn.execute(
                    "select mode, recheck_count from manual_error_entries where id = ?", (eid,),
                ).fetchone()
                self.assertEqual("M1" if eid == "e-m1" else "M0", row["mode"])
                self.assertEqual(1 if eid == "e-m1" else 0, row["recheck_count"])
            # no judgment-side writes from the batch channel either
            self.assertEqual(0, self._count(conn, "mastery_decisions"))
            self.assertEqual(0, self._count(conn, "learner_node_status"))

    def test_week_batch_confirm_reports_recheck_triggers(self):
        with self._db() as conn:
            _seed_entry(conn, "e1", created_at=W34_TUE, recheck_count=2)
            _seed_entry(conn, "e2", created_at=W34_WED)
            result = mes.confirm_week_manual_errors(conn, iso_week="2026-W34")
            self.assertEqual(2, result["processed"])
            self.assertEqual(1, result["recheck_triggered"])
            row = conn.execute(
                "select recheck_count, recheck_triggered_at from manual_error_entries where id = 'e1'"
            ).fetchone()
            self.assertEqual(0, row["recheck_count"])
            self.assertIsNotNone(row["recheck_triggered_at"])

    def test_week_batch_confirm_is_idempotent(self):
        with self._db() as conn:
            _seed_entry(conn, "e1", created_at=W34_TUE)
            _seed_entry(conn, "e2", created_at=W34_WED)
            first = mes.confirm_week_manual_errors(conn, iso_week="2026-W34")
            second = mes.confirm_week_manual_errors(conn, iso_week="2026-W34")
            self.assertEqual(2, first["processed"])
            self.assertEqual(0, second["processed"], "已确认条目不再重复处理")

    def test_week_batch_confirm_invalid_week_rejected(self):
        with self._db() as conn:
            with self.assertRaises(ValueError):
                mes.confirm_week_manual_errors(conn, iso_week="2026-34")
            with self.assertRaises(ValueError):
                mes.confirm_week_manual_errors(conn, iso_week="2026-W99")

    # --- idempotency / append-only ----------------------------------------

    def test_record_is_append_only_no_record_level_dedup(self):
        """选择说明: record 层不做去重 —— 每次调用产生独立条目 (fresh id);
        幂等保护在 (manual_entry_id, error_tag) 分布行唯一索引 + 幂等返回兜底."""
        with self._db() as conn:
            a = mes.record_manual_error(conn, node_id="N1", error_tag="general")
            b = mes.record_manual_error(conn, node_id="N1", error_tag="general")
            self.assertNotEqual(a["manual_entry_id"], b["manual_entry_id"])
            self.assertEqual(2, self._count(conn, "manual_error_entries"))
            self.assertEqual(2, self._count(conn, "error_cause_log"))

    def test_record_returns_existing_on_id_collision(self):
        """幂等选择: 同 id 重复投递 → 回滚新写入并返回既有 (idempotent=True)，不抛错."""
        with self._db() as conn:
            original = mes._new_manual_entry_id
            mes._new_manual_entry_id = lambda: "ME-FIXED-COLLISION"
            try:
                first = mes.record_manual_error(conn, node_id="N1", error_tag="general")
                second = mes.record_manual_error(conn, node_id="N1", error_tag="general")
            finally:
                mes._new_manual_entry_id = original
            self.assertEqual(first["manual_entry_id"], second["manual_entry_id"])
            self.assertTrue(second["idempotent"])
            self.assertFalse(second["retest"], "幂等返回不重复发 retest 信号")
            self.assertEqual(1, self._count(conn, "manual_error_entries"))
            self.assertEqual(1, self._count(conn, "error_cause_log"))

    # --- read-only helper -------------------------------------------------

    def test_pending_parent_errors_helper(self):
        with self._db() as conn:
            mes.record_manual_error(conn, node_id="N1", error_tag="concept_confusion", confidence=0.4)
            mes.record_manual_error(conn, node_id="N1", error_tag="general", confidence=0.9)
            pending = mes.pending_parent_errors(conn)
            self.assertEqual(1, len(pending))
            self.assertEqual("concept_confusion", pending[0]["error_tag"])
            self.assertEqual("pending_parent", pending[0]["trust_status"])
            self.assertIsNotNone(pending[0]["confidence"])
            # since filter
            self.assertEqual(0, len(mes.pending_parent_errors(conn, since="2099-01-01T00:00:00+00:00")))


if __name__ == "__main__":
    unittest.main()
