#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import assessment_policy, db, knowledge_map, question_fingerprints  # noqa: E402
from learning_system.graph_runtime import GraphRuntimeService  # noqa: E402


GENERATOR_VERSION = "lightweight-local-answer-contracts.v1"


def canonical_sha256(value: object) -> str:
    return question_fingerprints.canonical_sha256(value)


def active_ledger(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select * from question_bank_version_ledger
        where status = 'active'
        order by activated_at desc, updated_at desc, id desc
        """
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("exactly one active question-bank ledger row is required")
    return dict(rows[0])


def active_reviewed_questions(
    conn: sqlite3.Connection,
    bank_version: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select qi.*, qrr.id as active_review_record_id,
               qrr.candidate_sha256 as active_candidate_sha256
        from question_items qi
        join question_review_records qrr
          on qrr.question_id = qi.id
         and qrr.item_version = qi.item_version
         and qrr.review_status = 'approved'
         and qrr.active_eligible = 1
        where qi.item_version = ?
        order by qi.node_id, qi.id
        """,
        (bank_version,),
    ).fetchall()
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        question = db.row_to_question(row)
        review_record_id = str(question.pop("active_review_record_id") or "")
        if question["id"] in seen:
            raise ValueError(f"question has multiple active review records: {question['id']}")
        seen.add(question["id"])
        if not db.question_review_record_allows_active_use(
            conn,
            question,
            review_record_id,
        ):
            raise ValueError(f"question review lineage is invalid: {question['id']}")
        question["_active_review_record_id"] = review_record_id
        question["_active_candidate_sha256"] = str(row["active_candidate_sha256"] or "")
        questions.append(question)
    if not questions:
        raise ValueError("active question bank has no active reviewed questions")
    return questions


def question_digest(question: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "question_id": question.get("id"),
            "item_version": question.get("item_version"),
            "node_id": question.get("node_id"),
            "kind": question.get("kind"),
            "prompt": question.get("prompt"),
            "answer_format": question.get("answer_format"),
            "expected_answer": question.get("expected_answer"),
            "solution_steps": question.get("solution_steps") or [],
            "reference_evidence": question.get("reference_evidence"),
        }
    )


def build_contract(question: dict[str, Any], graph_version: str, bank_version: str) -> dict[str, Any]:
    draft = assessment_policy.build_answer_contract(question)
    stable_contract_id = f"ACL-{question['id']}"
    versioned = {
        "stable_contract_id": stable_contract_id,
        "contract_version": 1,
        **draft,
        "graph_version": graph_version,
        "question_bank_version": bank_version,
    }
    return {
        **versioned,
        "id": f"ACR-{canonical_sha256({'stable_contract_id': stable_contract_id, 'version': 1})[:16]}",
        "contract_digest_sha256": canonical_sha256(versioned),
        "question_digest_sha256": question_digest(question),
        "candidate_sha256": question.get("_active_candidate_sha256") or "",
        "review_record_id": question["_active_review_record_id"],
        "fingerprint_policy_version": "lightweight-local-contract-fingerprint.v1",
        "prompt_instance_fingerprint": canonical_sha256(
            {
                "question_id": question["id"],
                "item_version": question["item_version"],
                "prompt": question["prompt"],
                "answer_format": question["answer_format"],
            }
        ),
        "core_structure_fingerprint": canonical_sha256(
            {
                "node_id": question["node_id"],
                "kind": question["kind"],
                "score_points": draft["score_points"],
            }
        ),
    }


def receipt_for(
    *,
    graph_version: str,
    ledger: dict[str, Any],
    contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    commitments = [
        {
            "question_id": contract["question_id"],
            "item_version": contract["item_version"],
            "node_id": contract["node_id"],
            "question_digest_sha256": contract["question_digest_sha256"],
            "review_record_id": contract["review_record_id"],
            "candidate_sha256": contract["candidate_sha256"],
            "contract_id": contract["id"],
            "contract_version": contract["contract_version"],
            "contract_digest_sha256": contract["contract_digest_sha256"],
        }
        for contract in contracts
    ]
    return {
        "schema_version": knowledge_map.ASSESSMENT_RECEIPT_SCHEMA,
        "status": "active",
        "activation_mode": "lightweight_local_contracts_v1",
        "graph_lineage": graph_version,
        "question_bank_ledger_id": ledger["id"],
        "question_bank_version": ledger["question_bank_version"],
        "active_contract_count": len(contracts),
        "contract_set_digest_sha256": canonical_sha256(commitments),
        "generator_version": GENERATOR_VERSION,
        "activated_at": db.now_iso(),
    }


def activate(db_path: Path, *, project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        snapshot = GraphRuntimeService(conn, project_root=project_root).graph_snapshot()
        graph_version = str(snapshot["graph_lineage"])
        ledger = active_ledger(conn)
        bank_version = str(ledger["question_bank_version"])
        questions = active_reviewed_questions(conn, bank_version)
        node_count = len({question["node_id"] for question in questions})
        contracts = [build_contract(question, graph_version, bank_version) for question in questions]
        receipt = receipt_for(graph_version=graph_version, ledger=ledger, contracts=contracts)
        sealed_receipt = {
            **receipt,
            "receipt_digest_sha256": canonical_sha256(receipt),
        }
        now = db.now_iso()
        with conn:
            conn.execute(
                """
                update question_bank_version_ledger
                set graph_version = ?, node_count = ?, item_count = ?, updated_at = ?
                where id = ? and status = 'active'
                """,
                (graph_version, node_count, len(questions), now, ledger["id"]),
            )
            for contract in contracts:
                conn.execute(
                    """
                    update answer_contracts
                    set status = 'retired', superseded_at = ?, updated_at = ?
                    where question_id = ? and item_version = ? and status = 'active'
                    """,
                    (now, now, contract["question_id"], contract["item_version"]),
                )
                conn.execute(
                    """
                    insert into answer_contracts(
                      id, stable_contract_id, question_id, item_version,
                      contract_version, contract_digest_sha256,
                      question_digest_sha256, graph_version, question_bank_version,
                      reference_solution_json, score_points_json,
                      generator_version, review_record_id, review_receipt_json,
                      review_receipt_sha256, fingerprint_policy_version,
                      prompt_instance_fingerprint, core_structure_fingerprint,
                      status, approved_at, activated_at, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'active', ?, ?, ?, ?)
                    on conflict(id) do update set
                      contract_digest_sha256 = excluded.contract_digest_sha256,
                      question_digest_sha256 = excluded.question_digest_sha256,
                      graph_version = excluded.graph_version,
                      question_bank_version = excluded.question_bank_version,
                      reference_solution_json = excluded.reference_solution_json,
                      score_points_json = excluded.score_points_json,
                      generator_version = excluded.generator_version,
                      review_record_id = excluded.review_record_id,
                      review_receipt_json = excluded.review_receipt_json,
                      review_receipt_sha256 = excluded.review_receipt_sha256,
                      fingerprint_policy_version = excluded.fingerprint_policy_version,
                      prompt_instance_fingerprint = excluded.prompt_instance_fingerprint,
                      core_structure_fingerprint = excluded.core_structure_fingerprint,
                      status = 'active',
                      activated_at = excluded.activated_at,
                      updated_at = excluded.updated_at
                    """,
                    (
                        contract["id"],
                        contract["stable_contract_id"],
                        contract["question_id"],
                        contract["item_version"],
                        contract["contract_version"],
                        contract["contract_digest_sha256"],
                        contract["question_digest_sha256"],
                        contract["graph_version"],
                        contract["question_bank_version"],
                        db.json_dump(contract["reference_solution"]),
                        db.json_dump(contract["score_points"]),
                        GENERATOR_VERSION,
                        contract["review_record_id"],
                        db.json_dump(
                            {
                                "activation_mode": "lightweight_local_contracts_v1",
                                "provider_mode": "deterministic_runtime",
                                "review_scope": "uses_existing_question_review_and_reference_solution",
                            }
                        ),
                        canonical_sha256(
                            {
                                "contract_id": contract["id"],
                                "mode": "lightweight_local_contracts_v1",
                            }
                        ),
                        contract["fingerprint_policy_version"],
                        contract["prompt_instance_fingerprint"],
                        contract["core_structure_fingerprint"],
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            conn.execute(
                "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                (knowledge_map.ASSESSMENT_RECEIPT_KEY, db.json_dump(sealed_receipt), now),
            )
        return {
            "status": "activated",
            "activation_mode": "lightweight_local_contracts_v1",
            "question_bank_version": bank_version,
            "graph_lineage": graph_version,
            "active_contract_count": len(contracts),
            "node_count": node_count,
            "receipt_digest_sha256": sealed_receipt["receipt_digest_sha256"],
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data/local_learning_system.sqlite")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = activate(args.db)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
