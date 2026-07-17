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

from learning_system import answer_contract_generation, db, model_router  # noqa: E402


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser()
    parser.add_argument("--db", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--design-live", action="store_true")
    modes.add_argument("--repair-v2-live", action="store_true")
    modes.add_argument("--canary-v2-live", action="store_true")
    modes.add_argument("--audit-v2-run", metavar="RUN_ID")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--model-call-cap", type=int)
    parser.add_argument("--provider-attempt-cap", type=int)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--probe-item")
    parser.add_argument("--checkpoint-root")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def _bounded_positive(
    value: int | float | None,
    *,
    default: int | float,
    hard_maximum: int | float,
    field: str,
) -> int | float:
    resolved = default if value is None else value
    if isinstance(resolved, bool) or resolved <= 0 or resolved > hard_maximum:
        raise ValueError(f"{field}_out_of_range")
    return resolved


def _dry_plan(path: Path) -> dict[str, Any]:
    conn = _read_only_connection(path)
    try:
        plan = answer_contract_generation.build_design_plan(conn, PROJECT_ROOT)
    finally:
        conn.close()
    return {
        "mode": "dry_run",
        "bank_version": plan["bank_version"],
        "graph_version": plan["graph_version"],
        "planned_items": len(plan["items"]),
        "plan_digest_sha256": plan["plan_digest_sha256"],
        "model_calls": 0,
        "writes": 0,
        "activation_ready": False,
        "blockers": ["live_design_required", "independent_review_required"],
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv or sys.argv[1:])
        if args.dry_run:
            report = _dry_plan(Path(args.db))
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        if not args.checkpoint_root:
            raise ValueError("checkpoint_root_required")
        db_path = Path(args.db).resolve()
        if db_path == (PROJECT_ROOT / "data/local_learning_system.sqlite").resolve():
            raise ValueError("live_probe_requires_isolated_database_copy")
        if args.probe_item and args.max_items not in {None, 1}:
            raise ValueError("probe_item_and_max_items_conflict")
        if (args.canary_v2_live or args.audit_v2_run) and args.probe_item:
            raise ValueError("batch_a_modes_do_not_accept_probe_item")
        if args.canary_v2_live:
            model_call_cap = int(
                _bounded_positive(
                    args.model_call_cap,
                    default=answer_contract_generation.CANARY_DEFAULT_MODEL_CALL_CAP,
                    hard_maximum=answer_contract_generation.CANARY_HARD_MODEL_CALL_CAP,
                    field="model_call_cap",
                )
            )
            provider_attempt_cap = int(
                _bounded_positive(
                    args.provider_attempt_cap,
                    default=answer_contract_generation.CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP,
                    hard_maximum=answer_contract_generation.CANARY_HARD_PROVIDER_ATTEMPT_CAP,
                    field="provider_attempt_cap",
                )
            )
            max_items = int(
                _bounded_positive(
                    args.max_items,
                    default=answer_contract_generation.CANARY_DEFAULT_MAX_ITEMS,
                    hard_maximum=answer_contract_generation.CANARY_HARD_MAX_ITEMS,
                    field="max_items",
                )
            )
            if max_items != answer_contract_generation.CANARY_DEFAULT_MAX_ITEMS:
                raise ValueError("canary_max_items_must_equal_40")
            max_wall_seconds = float(
                _bounded_positive(
                    args.max_wall_seconds,
                    default=answer_contract_generation.CANARY_DEFAULT_WALL_SECONDS,
                    hard_maximum=answer_contract_generation.CANARY_HARD_WALL_SECONDS,
                    field="max_wall_seconds",
                )
            )
            conn = db.connect(db_path)
            try:
                db.init_schema(conn)
                designer = answer_contract_generation.make_live_designer_v2(conn)
                reviewer = answer_contract_generation.make_live_reviewer_v2(conn)
                report = answer_contract_generation.run_v2_canary(
                    conn,
                    PROJECT_ROOT,
                    designer=designer,
                    reviewer=reviewer,
                    checkpoint_root=Path(args.checkpoint_root),
                    model_call_cap=model_call_cap,
                    provider_attempt_cap=provider_attempt_cap,
                    max_items=max_items,
                    invocation_wall_seconds=max_wall_seconds,
                )
            finally:
                conn.close()
            report = {
                **report,
                "mode": "canary_v2_live",
                "production_authority": False,
                "activation_eligible": False,
            }
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0 if report.get("status") == "completed_passed" else 3
        if args.audit_v2_run:
            conn = db.connect(db_path)
            try:
                db.init_schema(conn)
                report = answer_contract_generation.audit_v2_generation_run(
                    conn,
                    PROJECT_ROOT,
                    run_id=args.audit_v2_run,
                    checkpoint_root=Path(args.checkpoint_root),
                )
            finally:
                conn.close()
            report = {
                **report,
                "mode": "audit_v2_run",
                "production_authority": False,
                "activation_eligible": False,
            }
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0 if report.get("status") == "completed_passed" else 3
        if args.repair_v2_live and not args.probe_item:
            raise ValueError("repair_v2_live_requires_probe_item")
        if args.repair_v2_live:
            design_route = model_router.answer_contract_design_v2_route()
            review_route = model_router.answer_contract_review_v2_route()
            if not design_route.enabled or not review_route.enabled:
                payload = {
                    "mode": "answer_contract_v2_live_probe",
                    "status": "error",
                    "activation_ready": False,
                    "activation_eligible": False,
                    "error": "model_not_configured",
                    "model_calls": 0,
                }
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                return 4
            conn = db.connect(db_path)
            try:
                report = answer_contract_generation.run_live_v2_probe(
                    conn,
                    PROJECT_ROOT,
                    question_id=args.probe_item,
                    checkpoint_root=Path(args.checkpoint_root),
                )
            finally:
                conn.close()
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0 if report.get("semantic_response_valid") else 3
        route = model_router.answer_contract_design_route()
        if not route.enabled:
            payload = {
                "mode": "design_live",
                "status": "error",
                "activation_ready": False,
                "error": "model_not_configured",
                "model_calls": 0,
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 4
        conn = db.connect(db_path)
        try:
            db.init_schema(conn)
            designer = answer_contract_generation.make_live_designer(conn)
            report = answer_contract_generation.run_design(
                conn,
                PROJECT_ROOT,
                designer,
                Path(args.checkpoint_root),
                max_items=args.max_items,
                probe_question_id=args.probe_item,
            )
        finally:
            conn.close()
        payload = {
            "mode": "design_live_probe" if args.probe_item else "design_live",
            "status": "accepted",
            "activation_ready": False,
            "blockers": ["independent_review_required"],
            **report,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        payload = {
            "status": "error",
            "activation_ready": False,
            "error": str(exc),
            **(
                exc.report
                if isinstance(getattr(exc, "report", None), dict)
                else {}
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
