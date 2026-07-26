#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from learning_system import db  # noqa: E402


QUESTION_BANK_TABLES = [
    "answer_contract_generation_provider_attempts",
    "answer_contract_generation_receipts",
    "answer_contract_generation_attempts",
    "answer_contract_generation_run_items",
    "answer_contract_generation_runs",
    "answer_contracts",
    "question_review_records",
    "question_bank_version_ledger",
    "question_items",
]

LEARNING_RECORD_TABLES = [
    "late_evidence_reconciliations",
    "daily_summaries",
    "next_step_decisions",
    "evidence_validations",
    "attempt_assessments",
    "attempt_attachments",
    "background_jobs",
    "attempts",
    "mastery_decisions",
    "learner_node_status",
    "teaching_step_events",
    "learning_target_intents",
    "review_targets",
    "flow_steps",
    "daily_flows",
    "session_steps",
    "learning_sessions",
    "generated_plans",
    "evolution_audits",
    "evolution_events",
    "agent_handoffs",
    "agent_runs",
]

RESET_META_KEY = "question_bank_reset.v1"
ANSWER_ASSESSMENT_META_KEY = "answer_assessment_active.v5.1"


def _table_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        try:
            counts[table] = int(conn.execute(f"select count(*) from {table}").fetchone()[0])
        except sqlite3.DatabaseError:
            counts[table] = -1
    return counts


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = db.now_iso().replace(":", "").replace("-", "").replace(".", "-")
    backup_path = backup_dir / f"{db_path.stem}.pre-reset.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def reset_database(db_path: Path, *, backup_dir: Path | None = None) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    backup_path = _backup_database(db_path, backup_dir) if backup_dir is not None else None
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        target_tables = QUESTION_BANK_TABLES + LEARNING_RECORD_TABLES
        before = _table_counts(conn, target_tables)
        now = db.now_iso()
        conn.execute("pragma foreign_keys = off")
        conn.execute("begin immediate")
        try:
            for table in target_tables:
                conn.execute(f"delete from {table}")
            conn.execute(
                "delete from system_meta where key = ?",
                (ANSWER_ASSESSMENT_META_KEY,),
            )
            conn.execute(
                "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                (
                    RESET_META_KEY,
                    db.json_dump(
                        {
                            "schema_version": "question-bank-reset.v1",
                            "status": "active",
                            "disable_legacy_seed": True,
                            "reason": "旧题库和错误学习记录已由用户确认全部废弃；等待新题库重新生成与审核。",
                            "backup_path": str(backup_path) if backup_path is not None else "",
                            "backup_policy": "none" if backup_path is None else "local_copy",
                            "reset_at": now,
                        }
                    ),
                    now,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("pragma foreign_keys = on")
        after = _table_counts(conn, target_tables)
        graph_counts = _table_counts(conn, ["graph_nodes", "graph_edges", "agent_profiles"])
        return {
            "db_path": str(db_path),
            "backup_path": str(backup_path) if backup_path is not None else "",
            "backup_policy": "none" if backup_path is None else "local_copy",
            "reset_meta_key": RESET_META_KEY,
            "before": before,
            "after": after,
            "preserved": graph_counts,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset local question bank and learning evidence after a bad-bank cutover.")
    parser.add_argument("--db", default=str(ROOT / "data/local_learning_system.sqlite"))
    parser.add_argument("--backup-dir", default=str(ROOT / "data/backups"))
    parser.add_argument("--no-backup", action="store_true", help="Delete without creating an archive copy.")
    parser.add_argument("--yes", action="store_true", help="Required acknowledgement for destructive reset.")
    args = parser.parse_args()
    if not args.yes:
        parser.error("destructive reset requires --yes")
    result = reset_database(
        Path(args.db),
        backup_dir=None if args.no_backup else Path(args.backup_dir),
    )
    print(db.json_dump(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
