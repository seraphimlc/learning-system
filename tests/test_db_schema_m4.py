"""Semester-mode M4-1 schema tests: the 4 new tables.

Contract under test: `learning_system/db.py` `init_schema` — the tables 裁定ed by
docs/design/specs/2026-08-20-dataflow-audit-record.md (核对项 3 新增表 + 核对项 4
FK 方案③ 旁挂侧表):

- `manual_error_entries` — FK-方案③ side table; the child/parent wrong-question
  entry carrier (append-only; M0/M1 dual channel; retest/recheck lifecycle cols
  are stored here, written by the M4-2 service layer).
- `error_cause_log` — three-year error-cause distribution, one row per tag
  (append-only; system_auto↔manual_entry exactly-one source; idempotent per
  (source-ref, error_tag); low-confidence rows filtered by service layer).
- `weekly_summary` — weekly-letter archive (append-only payload + acknowledge
  status; `iso_week` unique; `status` may be flipped to acknowledged by M4-3).
- `daily_all_correct_confirmations` — all-correct daily confirmation carrier,
  evidence-scope marking only; **mastery 判定不得读取本表**.

Run: python3 -m unittest tests.test_db_schema_m4 -v
"""

from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path

from learning_system import db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEARNING_SYSTEM_DIR = PROJECT_ROOT / "learning_system"

NEW_TABLES = (
    "manual_error_entries",
    "error_cause_log",
    "weekly_summary",
    "daily_all_correct_confirmations",
)

# Names of the idempotency/distribution/unique indexes M4-1 adds.
NEW_INDEXES = (
    "idx_manual_error_entries_node_created",
    "idx_error_cause_log_system_idempotency",
    "idx_error_cause_log_manual_idempotency",
    "idx_error_cause_log_tag_created",
    "idx_weekly_summary_iso_week",
    "idx_daily_all_correct_confirmations_date",
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    db.init_schema(conn)
    return conn


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
    return {row["name"] for row in rows}


def index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("select name from sqlite_master where type = 'index'").fetchall()
    return {row["name"] for row in rows}


def column_info(conn: sqlite3.Connection, table: str) -> dict[str, dict]:
    """column name -> {type, notnull, dflt_value, pk}."""
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    return {
        row["name"]: {
            "type": row["type"],
            "notnull": row["notnull"],
            "dflt_value": row["dflt_value"],
            "pk": row["pk"],
        }
        for row in rows
    }


def seed_node(conn: sqlite3.Connection, node_id: str = "N1") -> None:
    conn.execute(
        """
        insert or ignore into graph_nodes(
          id, name, stage, domain, priority, summer_mode, sequence_band,
          prerequisites_json, unlocks_json, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, "节点", "stage", "math", "P0", "summer", 1, "[]", "[]", "{}"),
    )
    conn.commit()


def seed_manual_entry(
    conn: sqlite3.Connection, entry_id: str = "m1", node_id: str = "N1", error_tag: str = "general"
) -> None:
    conn.execute(
        """
        insert into manual_error_entries(
          id, node_id, error_tag, prompt_ctx, source, trust_status, mode,
          retest_triggered_at, recheck_count, recheck_triggered_at,
          parent_confirmed_at, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id, node_id, error_tag, None, "child_self_report",
            "pending_parent", "M0", None, 0, None, None, "2026-08-20T00:00:00Z",
        ),
    )
    conn.commit()


def seed_attempt(
    conn: sqlite3.Connection, attempt_id: str = "a1", node_id: str = "N1"
) -> None:
    """Seed the minimal session→question→attempt chain so error_cause_log FK
    on attempts(id) can be exercised with a real row."""
    conn.execute(
        "insert or ignore into learning_sessions(id, title, mode, created_at) "
        "values (?, ?, ?, ?)",
        ("s1", "测试会话", "child_learning_group", "2026-08-20T00:00:00Z"),
    )
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
            "q1", "1", "graph_generated", node_id, "[]", "retest", "calculation",
            "1", "题干", "text", "答案", "[]", "[]", "[]", "[]", "[]",
            5, "", "{}", "{}",
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
            attempt_id, "s1", "q1", node_id, "correct", "graded",
            10, 10, "[]", "答案", "", "2026-08-20T00:00:00Z",
        ),
    )
    conn.commit()


class NewTablesPresentTestCase(unittest.TestCase):
    def test_four_new_tables_exist_after_init_schema(self):
        conn = make_conn()
        self.addCleanup(conn.close)
        present = table_names(conn)
        for table in NEW_TABLES:
            self.assertIn(table, present, f"missing new table: {table}")

    def test_new_indexes_exist_after_init_schema(self):
        conn = make_conn()
        self.addCleanup(conn.close)
        present = index_names(conn)
        for index in NEW_INDEXES:
            self.assertIn(index, present, f"missing new index: {index}")


class ManualErrorEntriesSchemaTestCase(unittest.TestCase):
    """FK-方案③ side table: child/parent wrong-question entry carrier."""

    EXPECTED_COLUMNS = {
        "id", "node_id", "error_tag", "prompt_ctx", "source", "trust_status",
        "mode", "retest_triggered_at", "recheck_count", "recheck_triggered_at",
        "parent_confirmed_at", "created_at",
    }
    NULLABLE = {"prompt_ctx", "retest_triggered_at", "recheck_triggered_at", "parent_confirmed_at"}

    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_columns_and_pk(self):
        cols = column_info(self.conn, "manual_error_entries")
        self.assertEqual(self.EXPECTED_COLUMNS, set(cols))
        self.assertEqual(1, cols["id"]["pk"])

    def test_nullable_columns_are_nullable(self):
        cols = column_info(self.conn, "manual_error_entries")
        for name in self.NULLABLE:
            self.assertEqual(0, cols[name]["notnull"], f"{name} should be nullable")

    def test_defaults(self):
        cols = column_info(self.conn, "manual_error_entries")
        self.assertEqual("'child_self_report'", cols["source"]["dflt_value"])
        self.assertEqual("0", cols["recheck_count"]["dflt_value"])
        self.assertEqual(1, cols["node_id"]["notnull"], "node_id must be NOT NULL (FK anchor)")

    def test_node_fk_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into manual_error_entries(
                  id, node_id, error_tag, source, trust_status, mode, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                ("e1", "GHOST-NODE", "general", "child_self_report", "pending_parent", "M0", "2026-08-20T00:00:00Z"),
            )

    def test_insert_is_append_only(self):
        seed_node(self.conn)
        for i in range(2):
            self.conn.execute(
                """
                insert into manual_error_entries(
                  id, node_id, error_tag, source, trust_status, mode, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"e{i}", "N1", "general", "child_self_report", "pending_parent", "M0", "2026-08-20T00:00:00Z"),
            )
        self.conn.commit()
        rows = self.conn.execute("select count(*) as n from manual_error_entries").fetchone()
        self.assertEqual(2, rows["n"])


class ErrorCauseLogSchemaTestCase(unittest.TestCase):
    """Three-year error-cause distribution: one row per tag, exactly-one source."""

    EXPECTED_COLUMNS = {
        "id", "attempt_id", "manual_entry_id", "node_id", "error_tag", "source",
        "confidence", "trust_status", "parent_confirmed_at", "graph_version", "created_at",
    }
    NULLABLE = {"attempt_id", "manual_entry_id", "confidence", "parent_confirmed_at"}

    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_columns_and_pk(self):
        cols = column_info(self.conn, "error_cause_log")
        self.assertEqual(self.EXPECTED_COLUMNS, set(cols))
        self.assertEqual(1, cols["id"]["pk"])

    def test_nullable_columns_are_nullable(self):
        cols = column_info(self.conn, "error_cause_log")
        for name in self.NULLABLE:
            self.assertEqual(0, cols[name]["notnull"], f"{name} should be nullable")

    def test_fks_enforced(self):
        seed_node(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into error_cause_log(
                  id, attempt_id, node_id, error_tag, source, trust_status,
                  graph_version, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("l1", "GHOST-ATTEMPT", "N1", "general", "system_auto", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into error_cause_log(
                  id, manual_entry_id, node_id, error_tag, source, trust_status,
                  graph_version, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("l2", "GHOST-MANUAL", "N1", "general", "manual_entry", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into error_cause_log(
                  id, attempt_id, node_id, error_tag, source, trust_status,
                  graph_version, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("l3", "a1", "GHOST-NODE", "general", "system_auto", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
            )

    def _insert_system(self, attempt_id: str, error_tag: str, row_id: str) -> None:
        seed_node(self.conn)
        seed_attempt(self.conn, attempt_id=attempt_id)
        self.conn.execute(
            """
            insert into error_cause_log(
              id, attempt_id, node_id, error_tag, source, trust_status,
              graph_version, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row_id, attempt_id, "N1", error_tag, "system_auto", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
        )

    def test_system_source_idempotency_per_tag(self):
        self._insert_system("a1", "general", "l1")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_system("a1", "general", "l1-dup")  # same (attempt, tag) → rejected
        # different tag on the same attempt is a distinct distribution row → allowed
        self._insert_system("a1", "concept_confusion", "l2")
        self.conn.commit()
        rows = self.conn.execute("select count(*) as n from error_cause_log").fetchone()
        self.assertEqual(2, rows["n"])

    def test_manual_source_idempotency_per_tag(self):
        seed_node(self.conn)
        seed_manual_entry(self.conn, entry_id="m1")
        self.conn.execute(
            """
            insert into error_cause_log(
              id, manual_entry_id, node_id, error_tag, source, trust_status,
              graph_version, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("l1", "m1", "N1", "general", "manual_entry", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into error_cause_log(
                  id, manual_entry_id, node_id, error_tag, source, trust_status,
                  graph_version, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("l1-dup", "m1", "N1", "general", "manual_entry", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
            )

    def test_system_and_manual_sources_do_not_collide(self):
        """Same tag via different sources is two distinct rows (no cross-source collision)."""
        seed_node(self.conn)
        seed_manual_entry(self.conn, entry_id="m1")
        self._insert_system("a1", "general", "l1")
        self.conn.execute(
            """
            insert into error_cause_log(
              id, manual_entry_id, node_id, error_tag, source, trust_status,
              graph_version, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("l2", "m1", "N1", "general", "manual_entry", "pending_parent", "v2", "2026-08-20T00:00:00Z"),
        )
        self.conn.commit()
        rows = self.conn.execute("select count(*) as n from error_cause_log").fetchone()
        self.assertEqual(2, rows["n"])


class WeeklySummarySchemaTestCase(unittest.TestCase):
    """Weekly-letter archive: append-only payload + acknowledge status."""

    EXPECTED_COLUMNS = {
        "id", "iso_week", "status", "node_status_snapshot_json", "coverage_json",
        "error_distribution_json", "evidence_scope", "narrative_json",
        "generated_at", "acknowledged_at",
    }
    NULLABLE = {"acknowledged_at"}

    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_columns_and_pk(self):
        cols = column_info(self.conn, "weekly_summary")
        self.assertEqual(self.EXPECTED_COLUMNS, set(cols))
        self.assertEqual(1, cols["id"]["pk"])
        self.assertEqual(0, cols["acknowledged_at"]["notnull"])

    def test_defaults(self):
        cols = column_info(self.conn, "weekly_summary")
        self.assertEqual("'unacknowledged'", cols["status"]["dflt_value"])
        self.assertEqual("'system_only'", cols["evidence_scope"]["dflt_value"])

    def _insert_week(self, iso_week: str, row_id: str) -> None:
        self.conn.execute(
            """
            insert into weekly_summary(id, iso_week, generated_at)
            values (?, ?, ?)
            """,
            (row_id, iso_week, "2026-08-20T00:00:00Z"),
        )

    def test_iso_week_unique(self):
        self._insert_week("2026-W34", "w1")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_week("2026-W34", "w2")

    def test_distinct_weeks_allowed(self):
        self._insert_week("2026-W34", "w1")
        self._insert_week("2026-W35", "w2")
        self.conn.commit()
        rows = self.conn.execute("select count(*) as n from weekly_summary").fetchone()
        self.assertEqual(2, rows["n"])

    def test_default_status_applied_on_partial_insert(self):
        self._insert_week("2026-W34", "w1")
        self.conn.commit()
        row = self.conn.execute(
            "select status, evidence_scope from weekly_summary where id = 'w1'"
        ).fetchone()
        self.assertEqual("unacknowledged", row["status"])
        self.assertEqual("system_only", row["evidence_scope"])


class DailyAllCorrectConfirmationsSchemaTestCase(unittest.TestCase):
    """All-correct confirmation carrier: evidence-scope marking only."""

    EXPECTED_COLUMNS = {
        "id", "confirm_date", "confirmed_by", "evidence_scope_mark",
        "source_refs_json", "created_at",
    }
    NULLABLE = {"source_refs_json"}

    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_columns_and_pk(self):
        cols = column_info(self.conn, "daily_all_correct_confirmations")
        self.assertEqual(self.EXPECTED_COLUMNS, set(cols))
        self.assertEqual(1, cols["id"]["pk"])
        self.assertEqual(0, cols["source_refs_json"]["notnull"])

    def test_confirmed_by_defaults_to_child(self):
        cols = column_info(self.conn, "daily_all_correct_confirmations")
        self.assertEqual("'child'", cols["confirmed_by"]["dflt_value"])

    def test_confirm_date_unique(self):
        self.conn.execute(
            """
            insert into daily_all_correct_confirmations(
              id, confirm_date, evidence_scope_mark, created_at
            ) values (?, ?, ?, ?)
            """,
            ("c1", "2026-08-20", "with_all_correct", "2026-08-20T00:00:00Z"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into daily_all_correct_confirmations(
                  id, confirm_date, evidence_scope_mark, created_at
                ) values (?, ?, ?, ?)
                """,
                ("c2", "2026-08-20", "with_all_correct", "2026-08-20T00:00:00Z"),
            )

    def test_default_confirmed_by_applied(self):
        self.conn.execute(
            """
            insert into daily_all_correct_confirmations(
              id, confirm_date, evidence_scope_mark, created_at
            ) values (?, ?, ?, ?)
            """,
            ("c1", "2026-08-20", "with_all_correct", "2026-08-20T00:00:00Z"),
        )
        self.conn.commit()
        row = self.conn.execute(
            "select confirmed_by from daily_all_correct_confirmations where id = 'c1'"
        ).fetchone()
        self.assertEqual("child", row["confirmed_by"])

    def test_mastery_must_not_read_this_table(self):
        """Schema site carries the 不进判定样本 warning (design §3.1/核对项 3)."""
        src = (LEARNING_SYSTEM_DIR / "db.py").read_text(encoding="utf-8")
        table_block = src[src.index("daily_all_correct_confirmations"):]
        self.assertIn("mastery 判定不得读取本表", table_block)


class AppendOnlyContractTestCase(unittest.TestCase):
    """No update/delete statements in the service layer may touch the new tables.

    Weekly-summary note: the draft (核对项 3) allows the acknowledge status
    (status/acknowledged_at) to be flipped in place by the M4-3 service layer;
    that is the documented, column-scoped exception — the payload columns
    (snapshots/coverage/distribution/narrative) stay insert-only, and rows are
    never deleted. Until M4-3 lands, no update/delete exists anywhere, which is
    exactly what this scan enforces.
    """

    TABLES_JOINED = "|".join(NEW_TABLES)
    WRITE_RE = re.compile(
        rf"\b(update|delete)\s+(?:from\s+)?(?:{TABLES_JOINED})\b",
        re.IGNORECASE,
    )

    def test_no_update_or_delete_statements_reference_new_tables(self):
        hits = []
        for path in sorted(LEARNING_SYSTEM_DIR.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            for match in self.WRITE_RE.finditer(src):
                line = src[: match.start()].count("\n") + 1
                hits.append(f"{path.name}:{line}: {match.group(0)}")
        self.assertEqual([], hits, "append-only violated: " + "; ".join(hits))


if __name__ == "__main__":
    unittest.main()
