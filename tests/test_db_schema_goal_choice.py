"""Weekly goal choice schema tests (动机层 ② 自选目标, M5).

Contract under test: `learning_system/db.py` `init_schema` — the
`weekly_goal_choices` table 裁定ed by
docs/design/specs/2026-08-20-child-learning-companion-design.md §6.3.2
(每周让孩子从 2 个候选里自选下周目标, 有护栏的自主):

- `weekly_goal_choices` — one row per ISO week (``iso_week`` unique, 一周一次选择);
  `node_ids_json` 存选中的 1-2 个节点; `chosen_by` 默认 'child';
  `created_at` 首次选择时间, `updated_at` 周内改选时置位 (UPSERT 语义,
  与 weekly_summary 的 iso_week 唯一模式对齐; 但本表是记录载体, 允许原地更新).

Run: python3 -m unittest tests.test_db_schema_goal_choice -v
"""

from __future__ import annotations

import sqlite3
import unittest

from learning_system import db

TABLE = "weekly_goal_choices"
INDEX = "idx_weekly_goal_choices_iso_week"

EXPECTED_COLUMNS = {
    "id", "iso_week", "node_ids_json", "chosen_by", "created_at", "updated_at",
}
NULLABLE = {"updated_at"}


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


class WeeklyGoalChoicesSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_table_and_unique_index_exist(self):
        self.assertIn(TABLE, table_names(self.conn))
        self.assertIn(INDEX, index_names(self.conn))

    def test_columns_and_pk(self):
        cols = column_info(self.conn, TABLE)
        self.assertEqual(EXPECTED_COLUMNS, set(cols))
        self.assertEqual(1, cols["id"]["pk"])
        self.assertEqual(1, cols["iso_week"]["notnull"], "iso_week must be NOT NULL")
        self.assertEqual(1, cols["node_ids_json"]["notnull"], "node_ids_json must be NOT NULL")
        self.assertEqual(1, cols["created_at"]["notnull"], "created_at must be NOT NULL")

    def test_defaults(self):
        cols = column_info(self.conn, TABLE)
        self.assertEqual("'child'", cols["chosen_by"]["dflt_value"])
        self.assertEqual(0, cols["updated_at"]["notnull"], "updated_at must be nullable")

    def _insert(self, iso_week: str, row_id: str, node_ids: str = '["N1"]') -> None:
        self.conn.execute(
            f"insert into {TABLE}(id, iso_week, node_ids_json, created_at)"
            " values (?, ?, ?, ?)",
            (row_id, iso_week, node_ids, "2026-08-24T00:00:00+00:00"),
        )

    def test_iso_week_unique(self):
        self._insert("2026-W35", "g1")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert("2026-W35", "g2")

    def test_distinct_weeks_allowed(self):
        self._insert("2026-W34", "g1")
        self._insert("2026-W35", "g2")
        self.conn.commit()
        rows = self.conn.execute(f"select count(*) as n from {TABLE}").fetchone()
        self.assertEqual(2, rows["n"])

    def test_default_chosen_by_applied(self):
        self._insert("2026-W35", "g1")
        self.conn.commit()
        row = self.conn.execute(
            f"select chosen_by, updated_at from {TABLE} where id = 'g1'"
        ).fetchone()
        self.assertEqual("child", row["chosen_by"])
        self.assertIsNone(row["updated_at"])


if __name__ == "__main__":
    unittest.main()
