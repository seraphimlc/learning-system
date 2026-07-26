from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from . import db, question_bank


RUNTIME_TEST_BANK_MANIFEST_ID = "runtime_test_bank_v1"


def seed_runtime_test_question_bank(
    conn: sqlite3.Connection,
    project_root: Path,
) -> dict[str, Any]:
    """Seed a reviewed synthetic bank for runtime tests only.

    Production startup must remain blocked until a formal bank passes its
    activation gate. This helper gives mechanism tests a complete schedulable
    bank without turning the empty v18 production bank into trusted content.
    """

    database_row = conn.execute("pragma database_list").fetchone()
    database_path = Path(str(database_row["file"] or "")).resolve() if database_row else None
    production_path = (project_root / "data/local_learning_system.sqlite").resolve()
    if database_path == production_path:
        raise ValueError("runtime test question bank cannot be seeded into the production database")

    active = conn.execute(
        "select * from question_bank_version_ledger where status = 'active'"
    ).fetchall()
    if active:
        if len(active) != 1:
            raise ValueError("runtime test bootstrap found multiple active question banks")
        return {
            "status": "already_active",
            "question_bank_version": active[0]["question_bank_version"],
            "item_count": int(active[0]["item_count"] or 0),
        }

    graph_path = project_root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_ref_row = conn.execute(
        "select value from system_meta where key = 'graph_ref'"
    ).fetchone()
    if not graph_ref_row:
        raise ValueError("runtime test bootstrap requires graph assets to be seeded first")
    graph_ref = db.json_load(graph_ref_row["value"], {})
    graph_version = str(graph_ref.get("lineage") or "")
    if not graph_version:
        raise ValueError("runtime test bootstrap requires graph lineage")

    items = question_bank.build_practice_bank(graph, graph_version=graph_version)
    manifest_sha256 = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with conn:
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (
                "question_bank_scope",
                db.json_dump({
                    "scope": "test_fixture",
                    "manifest_id": RUNTIME_TEST_BANK_MANIFEST_ID,
                    "production_activation_evidence": False,
                }),
                db.now_iso(),
            ),
        )
        designer_run = db.record_agent_run(
            conn,
            agent_key=question_bank.QUESTION_DESIGNER_AGENT_KEY,
            engine_type="deterministic",
            session_id=None,
            phase="test_question_design",
            trigger=f"seed_runtime_test_bank:{question_bank.QUESTION_BANK_VERSION}",
            input_refs={
                "manifest_id": RUNTIME_TEST_BANK_MANIFEST_ID,
                "question_bank_version": question_bank.QUESTION_BANK_VERSION,
                "graph_version": graph_version,
                "test_only": True,
            },
            prompt_version_id="runtime-test-bank.v1",
            status="accepted",
            confidence=1.0,
            output={"item_count": len(items), "test_only": True},
            commit=False,
        )
        for item in items:
            reviewer_run = db.record_agent_run(
                conn,
                agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                engine_type="deterministic",
                session_id=None,
                phase="test_question_quality_review",
                trigger=f"seed_runtime_test_bank_review:{item['id']}",
                input_refs={
                    "manifest_id": RUNTIME_TEST_BANK_MANIFEST_ID,
                    "question_bank_version": question_bank.QUESTION_BANK_VERSION,
                    "graph_version": graph_version,
                    "question_id": item["id"],
                    "test_only": True,
                },
                prompt_version_id="runtime-test-bank-review.v1",
                status="accepted",
                confidence=1.0,
                output={
                    "review_status": "approved",
                    "active_eligible": True,
                    "test_only": True,
                },
                commit=False,
            )
            db.upsert_question(
                conn,
                item,
                designer_run_id=designer_run["id"],
                reviewer_run_id=reviewer_run["id"],
            )

        db.backfill_current_seed_question_lineage(
            conn,
            graph_version=graph_version,
            question_bank_version=question_bank.QUESTION_BANK_VERSION,
            commit=False,
        )
        db.stage_question_bank_version(
            conn,
            question_bank_version=question_bank.QUESTION_BANK_VERSION,
            graph_version=graph_version,
            manifest_id=RUNTIME_TEST_BANK_MANIFEST_ID,
            manifest_sha256=manifest_sha256,
            node_count=len(graph["nodes"]),
            item_count=len(items),
            commit=False,
        )
        active_ledger = db.activate_question_bank_version(
            conn,
            question_bank_version=question_bank.QUESTION_BANK_VERSION,
            expected_current_version=None,
            reason="explicit runtime test fixture activation",
            commit=False,
        )

    return {
        "status": "seeded",
        "question_bank_version": question_bank.QUESTION_BANK_VERSION,
        "ledger_id": active_ledger["id"],
        "item_count": len(items),
        "node_count": len(graph["nodes"]),
    }
