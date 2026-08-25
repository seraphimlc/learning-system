#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import (  # noqa: E402
    answer_contract_activation,
    answer_contract_review,
    assessment_policy,
    db,
    model_router,
    question_fingerprints,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


class DryRunValidationError(ValueError):
    def __init__(self, message: str, *, active_bank_version: str = "") -> None:
        super().__init__(message)
        self.active_bank_version = active_bank_version


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def _active_ledger(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select * from question_bank_version_ledger
        where status = 'active'
        order by activated_at desc, updated_at desc, id desc
        """
    ).fetchall()
    if len(rows) != 1:
        version = str(rows[0]["question_bank_version"]) if rows else ""
        raise DryRunValidationError(
            "exactly one active question-bank ledger row is required",
            active_bank_version=version,
        )
    return dict(rows[0])


def _active_reviewed_questions(
    conn: sqlite3.Connection, active_bank_version: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select qi.*, qrr.id as active_review_record_id
        from question_items qi
        join question_review_records qrr
          on qrr.question_id = qi.id
         and qrr.item_version = qi.item_version
         and qrr.review_status = 'approved'
         and qrr.active_eligible = 1
        where qi.item_version = ?
        order by qi.node_id, qi.id
        """,
        (active_bank_version,),
    ).fetchall()
    questions = []
    seen = set()
    for row in rows:
        question = db.row_to_question(row)
        review_record_id = question.pop("active_review_record_id", None)
        if question["id"] in seen:
            raise DryRunValidationError(
                "question has multiple active review records",
                active_bank_version=active_bank_version,
            )
        seen.add(question["id"])
        if not db.question_review_record_allows_active_use(
            conn, question, review_record_id
        ):
            raise DryRunValidationError(
                f"question review lineage is not valid: {question['id']}",
                active_bank_version=active_bank_version,
            )
        question["_active_review_record_id"] = str(review_record_id)
        questions.append(question)
    return questions


def _question_digest(question: dict[str, Any]) -> str:
    return question_fingerprints.canonical_sha256(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "node_id": question["node_id"],
            "kind": question["kind"],
            "prompt": question["prompt"],
            "answer_format": question["answer_format"],
            "expected_answer": question["expected_answer"],
            "solution_steps": question["solution_steps"],
        }
    )


def _draft_and_review_item(
    question: dict[str, Any],
    *,
    graph_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = assessment_policy.build_answer_contract(question)
    stable_contract_id = f"AC-{question['id']}"
    versioned_draft = {
        "stable_contract_id": stable_contract_id,
        "contract_version": 1,
        **draft,
    }
    contract_digest = question_fingerprints.canonical_sha256(versioned_draft)
    review_item = {
        "review_item_handle": "review-item-"
        + question_fingerprints.canonical_sha256(
            {
                "question_id": question["id"],
                "item_version": question["item_version"],
                "review_record_id": question["_active_review_record_id"],
            }
        )[:20],
        "question_id": question["id"],
        "item_version": question["item_version"],
        "question_digest_sha256": _question_digest(question),
        "contract_id": stable_contract_id,
        "contract_version": 1,
        "contract_digest_sha256": contract_digest,
        "node_id": question["node_id"],
        "kind": question["kind"],
        "question_type": question.get("question_type") or question["kind"],
        "graph_version": graph_version,
        "graph_lineage": graph_version,
        "node_contract_sha256": question.get("node_contract_sha256") or "",
        "interaction_schema": question.get("interaction_schema"),
        "evidence_role": str(
            question.get("evidence_role")
            or question.get("evidence_goal")
            or "direct"
        ),
    }
    return versioned_draft, review_item


def build_dry_run_report(db_path: Path, *, mode: str) -> dict[str, Any]:
    conn = _read_only_connection(db_path)
    try:
        ledger = _active_ledger(conn)
        active_bank_version = str(ledger["question_bank_version"])
        questions = _active_reviewed_questions(conn, active_bank_version)
    finally:
        conn.close()

    if not questions:
        raise DryRunValidationError(
            "active question-bank version has no eligible questions",
            active_bank_version=active_bank_version,
        )
    node_count = len({question["node_id"] for question in questions})
    declared_items = int(ledger.get("item_count") or 0)
    declared_nodes = int(ledger.get("node_count") or 0)
    if declared_items and declared_items != len(questions):
        raise DryRunValidationError(
            "active ledger item_count does not match eligible questions",
            active_bank_version=active_bank_version,
        )
    if declared_nodes and declared_nodes != node_count:
        raise DryRunValidationError(
            "active ledger node_count does not match eligible questions",
            active_bank_version=active_bank_version,
        )

    drafts = []
    review_items = []
    for question in questions:
        draft, review_item = _draft_and_review_item(
            question,
            graph_version=str(ledger.get("graph_version") or ""),
        )
        drafts.append(draft)
        review_items.append(review_item)
    shards = answer_contract_review.plan_review_shards(review_items)

    manifest_digest = question_fingerprints.canonical_sha256(review_items)
    drafts_digest = question_fingerprints.canonical_sha256(drafts)
    shard_plan_digest = question_fingerprints.canonical_sha256(shards)
    blockers = ["semantic_review_required"]
    if mode in {"audit", "activate"}:
        blockers.append("live_review_receipts_required")
    receipt_payload = {
        "mode": mode,
        "active_bank_version": active_bank_version,
        "manifest_digest_sha256": manifest_digest,
        "draft_contracts_digest_sha256": drafts_digest,
        "shard_plan_digest_sha256": shard_plan_digest,
        "semantic_approved": 0,
        "activation_ready": False,
        "blockers": blockers,
    }
    return {
        "mode": mode,
        "active_bank_version": active_bank_version,
        "active_questions": len(questions),
        "nodes": node_count,
        "kinds": len({question["kind"] for question in questions}),
        "draft_contracts": len(drafts),
        "shards": len(shards),
        "max_shard_size": max((len(shard["items"]) for shard in shards), default=0),
        "review_concurrency": answer_contract_review.CONCURRENCY,
        "semantic_approved": 0,
        "activation_ready": False,
        "blockers": blockers,
        "model_calls": 0,
        "manifest_digest_sha256": manifest_digest,
        "draft_contracts_digest_sha256": drafts_digest,
        "shard_plan_digest_sha256": shard_plan_digest,
        "receipt_digest_sha256": question_fingerprints.canonical_sha256(
            receipt_payload
        ),
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser()
    parser.add_argument("--db", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--activate", action="store_true")
    modes.add_argument("--review-live", action="store_true")
    parser.add_argument("--max-shards", type=int)
    parser.add_argument("--probe-items", type=int)
    parser.add_argument("--probe-question")
    parser.add_argument("--checkpoint-root")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv or sys.argv[1:])
        if args.review_live:
            route = model_router.answer_contract_review_route()
            if not route.enabled:
                payload = {
                    "mode": "review_live",
                    "activation_ready": False,
                    "blockers": ["model_not_configured"],
                    "model_calls": 0,
                }
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                return 4
            if not args.checkpoint_root:
                raise ValueError("checkpoint_root_required")
            probe_options = sum(
                value is not None
                for value in (args.probe_items, args.probe_question)
            )
            if probe_options > 1:
                raise ValueError("probe_options_are_mutually_exclusive")
            if probe_options and args.max_shards is not None:
                raise ValueError("probe_and_max_shards_are_mutually_exclusive")
            conn = db.connect(Path(args.db))
            try:
                db.init_schema(conn)
                reviewer = answer_contract_activation.make_live_reviewer(conn)
                if args.probe_question is not None:
                    report = answer_contract_activation.run_live_probe(
                        conn,
                        PROJECT_ROOT,
                        reviewer,
                        Path(args.checkpoint_root),
                        probe_question_id=args.probe_question,
                    )
                elif args.probe_items is not None:
                    report = answer_contract_activation.run_live_probe(
                        conn,
                        PROJECT_ROOT,
                        reviewer,
                        Path(args.checkpoint_root),
                        probe_items=args.probe_items,
                    )
                else:
                    report = answer_contract_activation.run_live_review(
                        conn,
                        PROJECT_ROOT,
                        reviewer,
                        Path(args.checkpoint_root),
                        max_shards=args.max_shards,
                    )
            finally:
                conn.close()
            probe_mode = probe_options > 0
            payload = {
                "mode": "review_live_probe" if probe_mode else "review_live",
                "activation_ready": False,
                "blockers": ["probe_only"] if probe_mode else ["audit_required"],
                **report,
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        mode = "dry_run" if args.dry_run else ("audit" if args.audit else "activate")
        report = build_dry_run_report(Path(args.db), mode=mode)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if args.dry_run else 3
    except Exception as exc:
        payload = {
            "status": "error",
            "activation_ready": False,
            "error": str(exc),
            "active_bank_version": getattr(exc, "active_bank_version", ""),
            **(getattr(exc, "report", {}) if isinstance(getattr(exc, "report", {}), dict) else {}),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
