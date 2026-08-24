"""question_items 生题契约 4 列 schema 测试 (objective ③ + ①).

Contract under test: `learning_system/db.py` `init_schema` — the 4 columns
裁定ed by docs/design/specs/2026-08-20-question-bank-contract.md §2
(question_items 字段扩展, 方案 A; v1.1 加 design_rationale_json):

- `difficulty` — text NOT NULL default 'medium' (easy/medium/hard, planner 挑选用,
  与 variant_level 认知阶梯正交)
- `purpose_role` — text NOT NULL default 'core' (core/transfer, A 档判定 C3 依赖)
- `answer_verification` — text NOT NULL default 'pending'
  (verified/mismatch/unverifiable/pending, sympy 校验门禁状态)
- `design_rationale_json` — text NOT NULL default '{}' (设计理由五要素,
  质量门禁 objective ①: 考点/难度理由/认知阶梯定位/错因陷阱/教学角色)

迁移模式: 新库在建表语句直接含 4 列; 旧库走 `init_schema` 内的
`_ensure_column` 迁移补列 (照 production_category 先例, db.py:1360 起).

枚举约束决策: **不加 CHECK** — 照既有 question_items 枚举列先例
(`kind`/`variant_level`/`question_type` 均为裸 `text not null`, 无 CHECK),
枚举合法性由应用层 (生成器/校验管线, objective ③) 保证. 本文件用一个
测试固化该 DB 层行为并注释说明.

Run: python3 -m unittest tests.test_db_schema_question_contract -v
"""

from __future__ import annotations

import sqlite3
import unittest

from learning_system import db

NEW_COLUMNS = {
    "difficulty": ("'medium'", "TEXT"),
    "purpose_role": ("'core'", "TEXT"),
    "answer_verification": ("'pending'", "TEXT"),
    "design_rationale_json": ("'{}'", "TEXT"),
}

# 契约 §2 之前的 question_items 建表形状 (2026-08-20 前, 无 4 新列) —
# 迁移测试用它模拟真实旧库, 再跑 init_schema 走 _ensure_column 补列路径.
OLD_QUESTION_ITEMS_DDL = """
create table if not exists question_items (
  id text primary key,
  item_version text not null,
  source_type text not null,
  node_id text not null references graph_nodes(id),
  secondary_node_ids_json text not null,
  kind text not null,
  question_type text not null,
  variant_level text not null,
  production_category text not null default '',
  prompt text not null,
  answer_format text not null,
  expected_answer text not null,
  rubric_json text not null,
  solution_steps_json text not null,
  error_tags_json text not null,
  rollback_candidate_node_ids_json text not null,
  rollback_candidate_relations_json text not null,
  estimated_minutes integer not null,
  parent_observation text not null,
  source_json text not null,
  created_by_event_id text,
  raw_json text not null
);
"""

# 旧库 fixture 里 graph_nodes 的最小形状 (与 db.py 建表对齐, 供 seed_node 用).
OLD_GRAPH_NODES_DDL = """
create table if not exists graph_nodes (
  id text primary key,
  name text not null,
  stage text not null,
  domain text not null,
  priority text not null,
  summer_mode text not null,
  sequence_band integer not null default 99,
  prerequisites_json text not null,
  unlocks_json text not null,
  raw_json text not null
);
"""


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    db.init_schema(conn)
    return conn


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


def insert_question(
    conn: sqlite3.Connection,
    question_id: str = "q1",
    node_id: str = "N1",
    **extra: str,
) -> None:
    """Insert a minimal question_items row (3 新列省略 → 走默认值, 除非 extra 显式给)."""
    cols = [
        "id", "item_version", "source_type", "node_id", "secondary_node_ids_json",
        "kind", "question_type", "variant_level", "prompt", "answer_format",
        "expected_answer", "rubric_json", "solution_steps_json", "error_tags_json",
        "rollback_candidate_node_ids_json", "rollback_candidate_relations_json",
        "estimated_minutes", "parent_observation", "source_json", "raw_json",
    ]
    values = [
        question_id, "2026-08-20.v1", "graph_generated", node_id, "[]",
        "practice", "calculation", "L2", "题干", "text", "答案", "[]", "[]", "[]",
        "[]", "[]", 3, "", "{}", "{}",
    ]
    for name, value in extra.items():
        if name not in NEW_COLUMNS:
            raise ValueError(f"unknown column: {name}")
        cols.append(name)
        values.append(value)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"insert into question_items({', '.join(cols)}) values ({placeholders})",
        values,
    )
    conn.commit()


class NewDatabaseQuestionContractTestCase(unittest.TestCase):
    """新库 (init_schema 直建): 4 列在, NOT NULL, 默认值正确."""

    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_contract_columns_exist(self):
        cols = column_info(self.conn, "question_items")
        for name, (_default, col_type) in NEW_COLUMNS.items():
            self.assertIn(name, cols, f"missing column: {name}")
            self.assertEqual(col_type, cols[name]["type"], name)
            self.assertEqual(1, cols[name]["notnull"], f"{name} must be NOT NULL")
            self.assertEqual(0, cols[name]["pk"], f"{name} must not be PK")

    def test_schema_declared_defaults(self):
        cols = column_info(self.conn, "question_items")
        for name, (default, _col_type) in NEW_COLUMNS.items():
            self.assertEqual(default, cols[name]["dflt_value"], name)

    def test_defaults_applied_on_insert(self):
        seed_node(self.conn)
        insert_question(self.conn, question_id="q1")
        row = self.conn.execute(
            "select difficulty, purpose_role, answer_verification, design_rationale_json "
            "from question_items where id = 'q1'"
        ).fetchone()
        self.assertEqual("medium", row["difficulty"])
        self.assertEqual("core", row["purpose_role"])
        self.assertEqual("pending", row["answer_verification"])
        self.assertEqual("{}", row["design_rationale_json"])

    def test_explicit_values_round_trip(self):
        seed_node(self.conn)
        insert_question(
            self.conn,
            question_id="q1",
            difficulty="hard",
            purpose_role="transfer",
            answer_verification="verified",
            design_rationale_json='{"考点": "小数加减"}',
        )
        row = self.conn.execute(
            "select difficulty, purpose_role, answer_verification, design_rationale_json "
            "from question_items where id = 'q1'"
        ).fetchone()
        self.assertEqual("hard", row["difficulty"])
        self.assertEqual("transfer", row["purpose_role"])
        self.assertEqual("verified", row["answer_verification"])
        self.assertEqual('{"考点": "小数加减"}', row["design_rationale_json"])

    def test_db_layer_accepts_out_of_domain_enum_value(self):
        """固化解决策: 4 列不加 CHECK, 枚举由应用层保证.

        照既有 question_items 枚举列先例 (kind/variant_level/question_type 均为
        裸 text not null 无 CHECK), difficulty='x' 这类域外值在 DB 层不被拒绝;
        合法性由生成器/校验管线 (objective ③, 参照 contract §4 门禁) 把关.
        """
        seed_node(self.conn)
        insert_question(
            self.conn,
            question_id="q1",
            difficulty="x",
            purpose_role="y",
            answer_verification="z",
        )
        row = self.conn.execute(
            "select difficulty, purpose_role, answer_verification "
            "from question_items where id = 'q1'"
        ).fetchone()
        self.assertEqual(("x", "y", "z"), tuple(row))


class LegacyDatabaseMigrationTestCase(unittest.TestCase):
    """旧库迁移: 先建无 4 列的表, 再跑 init_schema → _ensure_column 补列."""

    def _make_legacy_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        # 模拟 2026-08-20 前的旧库: 只有旧形状的 graph_nodes + question_items 表
        # (其余表由随后的 init_schema 补齐; question_items 因已存在而走 _ensure_column).
        conn.executescript(OLD_GRAPH_NODES_DDL + OLD_QUESTION_ITEMS_DDL)
        # 旧库里可能已有数据行.
        seed_node(conn)
        insert_question(conn, question_id="legacy1")
        return conn

    def test_migration_adds_contract_columns_with_defaults(self):
        conn = self._make_legacy_conn()
        self.addCleanup(conn.close)
        # 迁移前: 4 列不存在.
        before = column_info(conn, "question_items")
        for name in NEW_COLUMNS:
            self.assertNotIn(name, before, f"fixture 不应含新列: {name}")

        db.init_schema(conn)  # 走 _ensure_column 补列路径

        after = column_info(conn, "question_items")
        for name, (default, col_type) in NEW_COLUMNS.items():
            self.assertIn(name, after, f"迁移后缺列: {name}")
            self.assertEqual(col_type, after[name]["type"], name)
            self.assertEqual(1, after[name]["notnull"], f"{name} must be NOT NULL")
            self.assertEqual(default, after[name]["dflt_value"], name)

    def test_migration_is_idempotent(self):
        conn = self._make_legacy_conn()
        self.addCleanup(conn.close)
        db.init_schema(conn)
        db.init_schema(conn)  # 再跑一次不应报错也不应改列
        after = column_info(conn, "question_items")
        for name in NEW_COLUMNS:
            self.assertIn(name, after)

    def test_migrated_columns_defaults_for_new_rows(self):
        conn = self._make_legacy_conn()
        self.addCleanup(conn.close)
        db.init_schema(conn)
        # 旧行: 迁移后读取旧数据, 4 列应落默认值 (SQLite 旧行补默认).
        legacy = conn.execute(
            "select difficulty, purpose_role, answer_verification, design_rationale_json "
            "from question_items where id = 'legacy1'"
        ).fetchone()
        self.assertEqual(("medium", "core", "pending", "{}"), tuple(legacy))
        # 新行: 不指定 4 列 → 默认值; 指定 → 显式值.
        insert_question(conn, question_id="q2")
        insert_question(
            conn, question_id="q3",
            difficulty="hard", purpose_role="transfer", answer_verification="verified",
            design_rationale_json='{"考点": "小数加减"}',
        )
        q2 = conn.execute(
            "select difficulty, purpose_role, answer_verification, design_rationale_json "
            "from question_items where id = 'q2'"
        ).fetchone()
        q3 = conn.execute(
            "select difficulty, purpose_role, answer_verification, design_rationale_json "
            "from question_items where id = 'q3'"
        ).fetchone()
        self.assertEqual(("medium", "core", "pending", "{}"), tuple(q2))
        self.assertEqual(("hard", "transfer", "verified", '{"考点": "小数加减"}'), tuple(q3))


if __name__ == "__main__":
    unittest.main()
