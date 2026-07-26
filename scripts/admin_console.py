#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from learning_system.admin.expert_ideation import build_expert_design_ideas, write_expert_design_ideas  # noqa: E402
from learning_system.admin.expert_review import (  # noqa: E402
    build_candidate_expert_review,
    build_candidate_model_expert_board_review,
    build_expert_quality_review,
    write_expert_quality_review,
    write_model_expert_board_review,
)
from learning_system.admin.gates import AdminGateError, validate_admin_readiness  # noqa: E402
from learning_system.admin.full_bank_acceptance import (  # noqa: E402
    build_full_bank_acceptance,
    write_full_bank_acceptance,
)
from learning_system.admin.inventory import (  # noqa: E402
    AdminInventoryError,
    build_node_inventory,
    build_question_bank_inventory,
    format_inventory_text,
)
from learning_system.admin.model_semantic_regression import (  # noqa: E402
    DEFAULT_ANSWER_CASES_PATH,
    run_answer_semantic_regression,
    write_answer_semantic_regression_report,
)
from learning_system.admin.question_generation import (  # noqa: E402
    build_generated_candidate_from_plan,
    write_generated_candidate_artifact,
)
from learning_system.admin.qa_review import build_candidate_qa_review, write_candidate_qa_review  # noqa: E402
from learning_system.admin.staging import build_and_write_stage_candidate_receipt  # noqa: E402
from learning_system.local_env import load_local_env_file  # noqa: E402
from learning_system.admin.production_loop import (  # noqa: E402
    AdminProductionError,
    build_candidate_check_from_paths,
    build_generation_plan,
    build_generation_plan_batch,
    build_question_requirement_plan,
    decide_loop_next_action,
    decide_staging_from_paths,
    write_production_report,
)
from learning_system.admin.source_receipts import SourceCandidate, SourceReceiptError, write_source_receipt  # noqa: E402
from learning_system.admin.production_workflow import (  # noqa: E402
    run_batch_production_workflow,
    run_slot_production_workflow,
    write_batch_production_workflow_report,
    write_slot_production_workflow_report,
)


def _print_report(report: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif str(report.get("schema_version") or "").startswith("2026-07-23.codex-admin.source-analysis"):
        print("\n".join([
            f"schema: {report.get('schema_version')}",
            f"source_id: {report.get('source_id')}",
            f"source_name: {report.get('source_name')}",
            f"source_type: {report.get('source_type')}",
            f"usage_mode: {report.get('usage_mode')}",
            f"capture_policy: {report.get('capture_policy')}",
            f"review_status: {report.get('review_status')}",
            f"risk_level: {report.get('risk_level')}",
            f"write_applied: {report.get('write_applied')}",
            f"receipt_markdown_path: {report.get('receipt_markdown_path')}",
            f"receipt_json_path: {report.get('receipt_json_path')}",
            f"decision_reason: {report.get('decision_reason')}",
        ]))
    else:
        print(format_inventory_text(report))


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--db", default="data/local_learning_system.sqlite", help="Reserved for later admin commands.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex-only admin module for content management.")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser("inventory", help="Read-only content inventory commands.")
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)

    qb = inventory_sub.add_parser("question-bank", help="Inspect a question bank inventory.")
    _add_common(qb)
    qb.add_argument("--subject", default="math")
    qb.add_argument("--version", default="v18")

    node = inventory_sub.add_parser("node", help="Inspect question inventory for one graph node.")
    _add_common(node)
    node.add_argument("--subject", default="math")
    node.add_argument("--version", default="v18")
    node.add_argument("--node-id", required=True)

    source = sub.add_parser("source", help="Source candidate and receipt commands.")
    source_sub = source.add_subparsers(dest="source_command", required=True)

    analyze = source_sub.add_parser("analyze", help="Create a source analysis receipt.")
    _add_common(analyze)
    analyze.add_argument("--name", required=True)
    analyze.add_argument("--url", default="")
    analyze.add_argument("--source-type", required=True)
    analyze.add_argument("--subject", default="math")
    analyze.add_argument("--stage", default="小升初衔接 + 七上预学")
    analyze.add_argument("--license-observation", default="unclear")
    analyze.add_argument("--terms-url", default="")
    analyze.add_argument("--direct-use-allowed", action="store_true")
    analyze.add_argument("--adaptation-allowed", action="store_true")
    analyze.add_argument("--ai-ingestion-allowed", action="store_true")
    analyze.add_argument("--commercial-use-allowed", action="store_true")
    analyze.add_argument("--attribution-required", action="store_true")
    analyze.add_argument("--attribution-text", default="")
    analyze.add_argument("--mapped-node-ids", default="")
    analyze.add_argument("--mapped-family-ids", default="")
    analyze.add_argument("--notes", default="")
    analyze.add_argument("--apply", action="store_true")

    model = sub.add_parser("model", help="Model compatibility and semantic regression commands.")
    model_sub = model.add_subparsers(dest="model_command", required=True)

    semantic = model_sub.add_parser("semantic-regression", help="Run answer-analysis semantic regression cases across candidate models.")
    _add_common(semantic)
    semantic.add_argument("--model", action="append", default=[], help="Model id to test. Repeat for multiple models.")
    semantic.add_argument("--cases", default=str(DEFAULT_ANSWER_CASES_PATH))
    semantic.add_argument("--base-url", default="https://api.amux.xyb2b.com/v1")
    semantic.add_argument("--api-key-env", default="OPENAI_API_KEY")
    semantic.add_argument("--case-id", action="append", default=[], help="Specific regression case id to run. Repeat for multiple cases.")
    semantic.add_argument("--limit", type=int, default=0)
    semantic.add_argument("--timeout-seconds", type=float, default=90.0)
    semantic.add_argument("--apply", action="store_true")

    review = sub.add_parser("review", help="Review and quality gate commands.")
    review_sub = review.add_subparsers(dest="review_command", required=True)

    expert_gate = review_sub.add_parser("expert-gate", help="Run deterministic expert quality profiles.")
    _add_common(expert_gate)
    expert_gate.add_argument("--subject", default="math")
    expert_gate.add_argument("--version", default="v18")
    expert_gate.add_argument("--apply", action="store_true")

    review_candidate = review_sub.add_parser("candidate", help="Run deterministic expert profiles for one candidate artifact.")
    _add_common(review_candidate)
    review_candidate.add_argument("--subject", default="math")
    review_candidate.add_argument("--version", default="v18")
    review_candidate.add_argument("--candidate", required=True)
    review_candidate.add_argument("--apply", action="store_true")

    model_expert_candidate = review_sub.add_parser("model-expert-candidate", help="Run model-assisted expert board review for one candidate artifact.")
    _add_common(model_expert_candidate)
    model_expert_candidate.add_argument("--subject", default="math")
    model_expert_candidate.add_argument("--version", default="v18")
    model_expert_candidate.add_argument("--candidate", required=True)
    model_expert_candidate.add_argument("--deterministic-review", default="")
    model_expert_candidate.add_argument("--apply", action="store_true")

    qa_candidate = review_sub.add_parser("qa-candidate", help="Run Guanzhi QA for one candidate artifact.")
    _add_common(qa_candidate)
    qa_candidate.add_argument("--subject", default="math")
    qa_candidate.add_argument("--version", default="v18")
    qa_candidate.add_argument("--candidate", required=True)
    qa_candidate.add_argument("--apply", action="store_true")

    gate = sub.add_parser("gate", help="Readiness and activation gate commands.")
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)

    readiness = gate_sub.add_parser("readiness", help="Run admin readiness gate.")
    _add_common(readiness)
    readiness.add_argument("--manifest", default="data/question_banks/v18/sample_gate_manifest_v18.json")
    readiness.add_argument("--mode", choices=["sample-integrity", "activation-readiness"], default="sample-integrity")
    readiness.add_argument("--expert-report", default="")

    full_bank = gate_sub.add_parser("full-bank", help="Run full staged-bank acceptance matrix.")
    _add_common(full_bank)
    full_bank.add_argument("--subject", default="math")
    full_bank.add_argument("--bank", default="data/question_banks/v18/staged_candidates_v18.json")
    full_bank.add_argument("--require-target", action="store_true")
    full_bank.add_argument("--apply", action="store_true")

    design = sub.add_parser("design", help="Expert design ideation commands.")
    design_sub = design.add_subparsers(dest="design_command", required=True)

    expert_ideas = design_sub.add_parser("expert-ideas", help="Generate expert question-type design ideas for one node.")
    _add_common(expert_ideas)
    expert_ideas.add_argument("--subject", default="math")
    expert_ideas.add_argument("--version", default="v18")
    expert_ideas.add_argument("--node-id", required=True)
    expert_ideas.add_argument("--apply", action="store_true")

    production = sub.add_parser("production", help="Question production loop commands.")
    production_sub = production.add_subparsers(dest="production_command", required=True)

    req_plan = production_sub.add_parser("requirement-plan", help="Create expert-derived per-question requirements for one graph node.")
    _add_common(req_plan)
    req_plan.add_argument("--subject", default="math")
    req_plan.add_argument("--version", default="v18")
    req_plan.add_argument("--node-id", required=True)
    req_plan.add_argument("--design-brief", default="")
    req_plan.add_argument("--max-attempts", type=int, default=3)
    req_plan.add_argument("--apply", action="store_true")

    prod_plan = production_sub.add_parser("plan", help="Create a bounded generation packet from an expert brief.")
    _add_common(prod_plan)
    prod_plan.add_argument("--subject", default="math")
    prod_plan.add_argument("--version", default="v18")
    prod_plan.add_argument("--node-id", required=True)
    prod_plan.add_argument("--family-id", required=True)
    prod_plan.add_argument("--design-brief", default="")
    prod_plan.add_argument("--requirements-plan", default="")
    prod_plan.add_argument("--slot-id", default="")
    prod_plan.add_argument("--count", type=int, default=1)
    prod_plan.add_argument("--max-attempts", type=int, default=3)
    prod_plan.add_argument("--apply", action="store_true")

    prod_plan_batch = production_sub.add_parser("plan-batch", help="Create one generation packet per selected requirement slot.")
    _add_common(prod_plan_batch)
    prod_plan_batch.add_argument("--subject", default="math")
    prod_plan_batch.add_argument("--version", default="v18")
    prod_plan_batch.add_argument("--node-id", required=True)
    prod_plan_batch.add_argument("--family-id", default="")
    prod_plan_batch.add_argument("--design-brief", default="")
    prod_plan_batch.add_argument("--requirements-plan", required=True)
    prod_plan_batch.add_argument("--limit", type=int, default=20)
    prod_plan_batch.add_argument("--max-attempts", type=int, default=3)
    prod_plan_batch.add_argument("--apply", action="store_true")

    generate_candidate = production_sub.add_parser("generate-candidate", help="Call question_designer_agent for one slot-scoped production plan.")
    _add_common(generate_candidate)
    generate_candidate.add_argument("--subject", default="math")
    generate_candidate.add_argument("--generation-plan", required=True)
    generate_candidate.add_argument("--previous-rejection", default="")
    generate_candidate.add_argument("--attempt", type=int, default=1)
    generate_candidate.add_argument("--apply", action="store_true")

    validate_candidate = production_sub.add_parser("validate-candidate", help="Machine-check one generated candidate against an expert brief.")
    _add_common(validate_candidate)
    validate_candidate.add_argument("--subject", default="math")
    validate_candidate.add_argument("--version", default="v18")
    validate_candidate.add_argument("--candidate", required=True)
    validate_candidate.add_argument("--design-brief", required=True)
    validate_candidate.add_argument("--requirements-plan", default="")
    validate_candidate.add_argument("--slot-id", default="")
    validate_candidate.add_argument("--family-id", default="")
    validate_candidate.add_argument("--previous-rejection", default="")
    validate_candidate.add_argument("--apply", action="store_true")

    staging = production_sub.add_parser("staging-decision", help="Decide whether receipts allow the candidate to continue toward staged.")
    _add_common(staging)
    staging.add_argument("--subject", default="math")
    staging.add_argument("--machine-report", required=True)
    staging.add_argument("--expert-report", required=True)
    staging.add_argument("--model-expert-report", default="")
    staging.add_argument("--qa-report", default="")
    staging.add_argument("--apply", action="store_true")

    stage_candidate = production_sub.add_parser("stage-candidate", help="Append a STAGED_READY candidate to the staged v18 bank.")
    _add_common(stage_candidate)
    stage_candidate.add_argument("--subject", default="math")
    stage_candidate.add_argument("--candidate", required=True)
    stage_candidate.add_argument("--staging-decision", required=True)
    stage_candidate.add_argument("--staged-bank", default="data/question_banks/v18/staged_candidates_v18.json")
    stage_candidate.add_argument("--apply", action="store_true")

    run_slot = production_sub.add_parser("run-slot", help="Run generate -> machine -> expert -> QA -> staging for one generation plan.")
    _add_common(run_slot)
    run_slot.add_argument("--subject", default="math")
    run_slot.add_argument("--generation-plan", required=True)
    run_slot.add_argument("--previous-rejection", default="")
    run_slot.add_argument("--staged-bank", default="data/question_banks/v18/staged_candidates_v18.json")
    run_slot.add_argument("--max-attempts", type=int, default=3)
    run_slot.add_argument("--apply", action="store_true")

    run_batch = production_sub.add_parser("run-batch", help="Run multiple slot generation plans with bounded single-slot workflows.")
    _add_common(run_batch)
    run_batch.add_argument("--subject", default="math")
    run_batch.add_argument("--generation-plan", action="append", default=[], help="Generation plan path. Repeat for multiple slots.")
    run_batch.add_argument("--plan-list", default="", help="Optional JSON array or newline-delimited file of generation plan paths.")
    run_batch.add_argument("--staged-bank", default="data/question_banks/v18/staged_candidates_v18.json")
    run_batch.add_argument("--max-attempts-per-slot", type=int, default=3)
    run_batch.add_argument("--max-slots", type=int, default=20)
    run_batch.add_argument("--max-runtime-seconds", type=float, default=1800.0)
    run_batch.add_argument("--generation-batch-size", type=int, default=1)
    run_batch.add_argument("--workers", type=int, default=1, help="Parallel single-slot workers. Applies only when --generation-batch-size is 1.")
    run_batch.add_argument("--apply", action="store_true")

    loop = production_sub.add_parser("loop-decision", help="Route the production workflow after machine/expert review.")
    _add_common(loop)
    loop.add_argument("--subject", default="math")
    loop.add_argument("--machine-report", required=True)
    loop.add_argument("--expert-report", default="")
    loop.add_argument("--attempt", type=int, default=0)
    loop.add_argument("--max-attempts", type=int, default=3)
    loop.add_argument("--apply", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        load_local_env_file(root / ".env.local")
        if args.command == "inventory" and args.inventory_command == "question-bank":
            report = build_question_bank_inventory(root=root, version=args.version, subject=args.subject)
            _print_report(report, args.format)
            return 0
        if args.command == "inventory" and args.inventory_command == "node":
            report = build_node_inventory(root=root, node_id=args.node_id, version=args.version, subject=args.subject)
            _print_report(report, args.format)
            return 0
        if args.command == "source" and args.source_command == "analyze":
            candidate = SourceCandidate(
                name=args.name,
                source_type=args.source_type,
                url_or_file=args.url,
                subject=args.subject,
                stage=args.stage,
                license_observation=args.license_observation,
                terms_url=args.terms_url,
                direct_use_allowed=args.direct_use_allowed,
                adaptation_allowed=args.adaptation_allowed,
                ai_ingestion_allowed=args.ai_ingestion_allowed,
                commercial_use_allowed=args.commercial_use_allowed,
                attribution_required=args.attribution_required,
                attribution_text=args.attribution_text,
                mapped_node_ids=_split_csv(args.mapped_node_ids),
                mapped_question_family_ids=_split_csv(args.mapped_family_ids),
                notes=args.notes,
            )
            report = write_source_receipt(candidate, root=root, apply=args.apply)
            _print_report(report, args.format)
            return 0
        if args.command == "model" and args.model_command == "semantic-regression":
            report = run_answer_semantic_regression(
                root=root,
                models=list(args.model or []),
                cases_path=Path(args.cases),
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                case_ids=list(args.case_id or []),
                limit=args.limit,
                timeout_seconds=args.timeout_seconds,
            )
            report = write_answer_semantic_regression_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"run_id: {report.get('run_id')}",
                    f"case_count: {report.get('case_count')}",
                    f"models: {', '.join(model.get('model', '') for model in report.get('models') or [])}",
                    f"write_applied: {report.get('write_applied')}",
                    f"regression_markdown_path: {report.get('regression_markdown_path')}",
                    f"regression_json_path: {report.get('regression_json_path')}",
                    "activation_implication: does_not_authorize_model_switch_or_child_runtime_activation",
                ]))
            return 0 if report["status"] == "PASS" else 1
        if args.command == "review" and args.review_command == "expert-gate":
            report = build_expert_quality_review(root=root, version=args.version, subject=args.subject)
            report = write_expert_quality_review(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"question_bank_version: {report.get('question_bank_version')}",
                    f"reviewed_item_count: {report.get('reviewed_item_count')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"review_markdown_path: {report.get('review_markdown_path')}",
                    f"review_json_path: {report.get('review_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0
        if args.command == "review" and args.review_command == "candidate":
            report = build_candidate_expert_review(
                root=root,
                candidate_path=Path(args.candidate),
                subject=args.subject,
                version=args.version,
            )
            report = write_expert_quality_review(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"review_markdown_path: {report.get('review_markdown_path')}",
                    f"review_json_path: {report.get('review_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if report["status"] == "NEEDS_FIX" else 0
        if args.command == "review" and args.review_command == "model-expert-candidate":
            deterministic_review = None
            if args.deterministic_review:
                review_path = Path(args.deterministic_review)
                if not review_path.is_absolute():
                    review_path = root / review_path
                deterministic_review = json.loads(review_path.read_text(encoding="utf-8"))
            report = build_candidate_model_expert_board_review(
                root=root,
                candidate_path=Path(args.candidate),
                deterministic_review=deterministic_review,
                subject=args.subject,
                version=args.version,
            )
            report = write_model_expert_board_review(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"provider_mode: {report.get('provider_mode')}",
                    f"item_id: {report.get('item_id')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"model_expert_review_markdown_path: {report.get('model_expert_review_markdown_path')}",
                    f"model_expert_review_json_path: {report.get('model_expert_review_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] in {"PASS", "PASS_WITH_SCOPE"} else 1
        if args.command == "review" and args.review_command == "qa-candidate":
            report = build_candidate_qa_review(
                root=root,
                candidate_path=Path(args.candidate),
                subject=args.subject,
                version=args.version,
            )
            report = write_candidate_qa_review(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"qa_markdown_path: {report.get('qa_markdown_path')}",
                    f"qa_json_path: {report.get('qa_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if report["status"] == "NEEDS_FIX" else 0
        if args.command == "gate" and args.gate_command == "readiness":
            report = validate_admin_readiness(
                root=root,
                manifest_path=Path(args.manifest),
                mode=args.mode,
                expert_report_path=Path(args.expert_report) if args.expert_report else None,
            )
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"mode: {report.get('mode')}",
                    f"base_gate_status: {report.get('base_gate_status')}",
                    f"expert_gate: {json.dumps(report.get('expert_gate'), ensure_ascii=False, sort_keys=True)}",
                    f"activation_allowed: {report.get('activation_allowed')}",
                    f"reason: {report.get('reason', '')}",
                ]))
            return 1 if report["status"] == "FAIL_CLOSED" else 0
        if args.command == "gate" and args.gate_command == "full-bank":
            report = build_full_bank_acceptance(
                root=root,
                bank_path=Path(args.bank),
                subject=args.subject,
                require_target=args.require_target,
            )
            report = write_full_bank_acceptance(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"bank: {report.get('bank_path')}",
                    f"item_count: {report.get('item_count')}",
                    f"covered_nodes: {report.get('covered_node_count')}/{report.get('blueprint_node_count')}",
                    f"covered_families: {report.get('covered_family_count')}/{report.get('taxonomy_family_count')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"full_bank_markdown_path: {report.get('full_bank_markdown_path')}",
                    f"full_bank_json_path: {report.get('full_bank_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] in {"PASS", "PASS_WITH_SCOPE"} else 1
        if args.command == "design" and args.design_command == "expert-ideas":
            report = build_expert_design_ideas(root=root, node_id=args.node_id, version=args.version, subject=args.subject)
            report = write_expert_design_ideas(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"node: {report.get('node_id')} {report.get('node_name')}",
                    f"question_bank_version: {report.get('question_bank_version')}",
                    f"current_item_count: {report.get('current_item_count')}",
                    f"missing_or_underfilled_families: {', '.join(report.get('missing_or_underfilled_families') or [])}",
                    f"idea_count: {report.get('idea_count')}",
                    f"write_applied: {report.get('write_applied')}",
                    f"design_markdown_path: {report.get('design_markdown_path')}",
                    f"design_json_path: {report.get('design_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0
        if args.command == "production" and args.production_command == "plan":
            report = build_generation_plan(
                root=root,
                node_id=args.node_id,
                family_id=args.family_id,
                version=args.version,
                subject=args.subject,
                design_brief_path=Path(args.design_brief) if args.design_brief else None,
                requirement_plan_path=Path(args.requirements_plan) if args.requirements_plan else None,
                slot_id=args.slot_id or None,
                requested_count=args.count,
                max_attempts=args.max_attempts,
            )
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"node: {report.get('node_id')} {report.get('node_name')}",
                    f"family: {report.get('family_id')} {report.get('family_name')}",
                    f"design_brief_id: {report.get('design_brief_id')}",
                    f"requested_count: {report.get('requested_count')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if report["status"] == "BLOCKED" else 0
        if args.command == "production" and args.production_command == "plan-batch":
            report = build_generation_plan_batch(
                root=root,
                node_id=args.node_id,
                requirement_plan_path=Path(args.requirements_plan),
                version=args.version,
                subject=args.subject,
                family_id=args.family_id,
                design_brief_path=Path(args.design_brief) if args.design_brief else None,
                limit=args.limit,
                max_attempts=args.max_attempts,
            )
            written_plans = []
            if args.apply:
                for plan in report.get("generation_plans") or []:
                    written_plans.append(write_production_report(plan, root=root, apply=True))
            if written_plans:
                report = {
                    **report,
                    "generation_plans": written_plans,
                    "generation_plan_paths": [plan["production_json_path"] for plan in written_plans],
                }
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"node: {report.get('node_id')} {report.get('node_name')}",
                    f"family: {report.get('family_id')}",
                    f"selected_slot_count: {report.get('selected_slot_count')}",
                    f"plan_count: {report.get('plan_count')}",
                    f"generation_plan_paths: {', '.join(report.get('generation_plan_paths') or [])}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] == "PLAN_BATCH_READY" else 1
        if args.command == "production" and args.production_command == "generate-candidate":
            report = build_generated_candidate_from_plan(
                root=root,
                generation_plan_path=Path(args.generation_plan),
                previous_rejection_path=Path(args.previous_rejection) if args.previous_rejection else None,
                generation_attempt=args.attempt,
                subject=args.subject,
            )
            report = write_generated_candidate_artifact(report, root=root, apply=args.apply)
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"provider_mode: {report.get('provider_mode')}",
                    f"item_id: {report.get('item_id', '')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"slot_id: {report.get('slot_id')}",
                    f"candidate_json_path: {report.get('candidate_json_path', '')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"next_actions: {', '.join(report.get('next_actions') or [])}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] == "CANDIDATE_READY_FOR_EXPERT_REVIEW" else 1
        if args.command == "production" and args.production_command == "requirement-plan":
            report = build_question_requirement_plan(
                root=root,
                node_id=args.node_id,
                version=args.version,
                subject=args.subject,
                design_brief_path=Path(args.design_brief) if args.design_brief else None,
                max_attempts=args.max_attempts,
            )
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"node: {report.get('node_id')} {report.get('node_name')}",
                    f"design_brief_id: {report.get('design_brief_id')}",
                    f"requirement_count: {report.get('requirement_count')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if report["status"] == "BLOCKED" else 0
        if args.command == "production" and args.production_command == "validate-candidate":
            report = build_candidate_check_from_paths(
                root=root,
                candidate_path=Path(args.candidate),
                design_brief_path=Path(args.design_brief),
                version=args.version,
                subject=args.subject,
                required_family_id=args.family_id or None,
                requirement_plan_path=Path(args.requirements_plan) if args.requirements_plan else None,
                slot_id=args.slot_id or None,
                previous_rejection_path=Path(args.previous_rejection) if args.previous_rejection else None,
            )
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"next_actions: {', '.join(report.get('next_actions') or [])}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "staging_allowed: false",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if report["status"] == "NEEDS_REGENERATION" else 0
        if args.command == "production" and args.production_command == "loop-decision":
            machine_report_path = Path(args.machine_report)
            if not machine_report_path.is_absolute():
                machine_report_path = root / machine_report_path
            expert_report = None
            if args.expert_report:
                expert_report_path = Path(args.expert_report)
                if not expert_report_path.is_absolute():
                    expert_report_path = root / expert_report_path
                expert_report = json.loads(expert_report_path.read_text(encoding="utf-8"))
            machine_report = json.loads(machine_report_path.read_text(encoding="utf-8"))
            report = decide_loop_next_action(
                machine_report=machine_report,
                expert_report=expert_report,
                generation_attempt=args.attempt or None,
                max_attempts=args.max_attempts,
                subject=args.subject,
            )
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"slot_id: {report.get('slot_id')}",
                    f"next_action: {report.get('next_action')}",
                    f"blocking_rejection_codes: {', '.join(report.get('blocking_rejection_codes') or [])}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if str(report["status"]).startswith("LOOP_BLOCKED") else 0
        if args.command == "production" and args.production_command == "staging-decision":
            report = decide_staging_from_paths(
                root=root,
                machine_report_path=Path(args.machine_report),
                expert_report_path=Path(args.expert_report),
                model_expert_report_path=Path(args.model_expert_report) if args.model_expert_report else None,
                qa_report_path=Path(args.qa_report) if args.qa_report else None,
                subject=args.subject,
            )
            report = write_production_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"staging_allowed: {report.get('staging_allowed')}",
                    f"activation_allowed: {report.get('activation_allowed')}",
                    f"finding_counts: {json.dumps(report.get('finding_counts', {}), ensure_ascii=False, sort_keys=True)}",
                    f"next_actions: {', '.join(report.get('next_actions') or [])}",
                    f"write_applied: {report.get('write_applied')}",
                    f"production_markdown_path: {report.get('production_markdown_path')}",
                    f"production_json_path: {report.get('production_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 1 if not report["staging_allowed"] else 0
        if args.command == "production" and args.production_command == "stage-candidate":
            report = build_and_write_stage_candidate_receipt(
                root=root,
                artifact_root=root,
                candidate_path=Path(args.candidate),
                staging_decision_path=Path(args.staging_decision),
                staged_bank_path=Path(args.staged_bank),
                subject=args.subject,
                apply=args.apply,
            )
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"item_id: {report.get('item_id')}",
                    f"node: {report.get('node_id')}",
                    f"family: {report.get('family_id')}",
                    f"staged_bank_path: {report.get('staged_bank_path')}",
                    f"staged_item_count: {report.get('staged_item_count')}",
                    f"write_applied: {report.get('write_applied')}",
                    f"stage_receipt_json_path: {report.get('stage_receipt_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] in {"STAGED_WRITABLE", "ALREADY_STAGED"} else 1
        if args.command == "production" and args.production_command == "run-slot":
            report = run_slot_production_workflow(
                root=root,
                generation_plan_path=Path(args.generation_plan),
                previous_rejection_path=Path(args.previous_rejection) if args.previous_rejection else None,
                staged_bank_path=Path(args.staged_bank),
                max_attempts=args.max_attempts,
                subject=args.subject,
                apply=args.apply,
            )
            report = write_slot_production_workflow_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"workflow_id: {report.get('workflow_id')}",
                    f"attempt_count: {report.get('attempt_count')}",
                    f"item_id: {report.get('item_id')}",
                    f"staged_bank_path: {report.get('staged_bank_path')}",
                    f"staging_allowed: {report.get('staging_allowed')}",
                    f"workflow_markdown_path: {report.get('workflow_markdown_path')}",
                    f"workflow_json_path: {report.get('workflow_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] == "WORKFLOW_STAGED" else 1
        if args.command == "production" and args.production_command == "run-batch":
            plan_values = list(args.generation_plan or [])
            if args.plan_list:
                plan_list_path = Path(args.plan_list)
                if not plan_list_path.is_absolute():
                    plan_list_path = root / plan_list_path
                raw = plan_list_path.read_text(encoding="utf-8")
                try:
                    loaded = json.loads(raw)
                except json.JSONDecodeError:
                    loaded = [line.strip() for line in raw.splitlines() if line.strip()]
                if not isinstance(loaded, list):
                    raise AdminProductionError("ADMIN_PRODUCTION_BATCH_PLAN_LIST_MUST_BE_ARRAY_OR_LINES")
                plan_values.extend(str(value) for value in loaded if str(value).strip())
            report = run_batch_production_workflow(
                root=root,
                generation_plan_paths=[Path(value) for value in plan_values],
                staged_bank_path=Path(args.staged_bank),
                max_attempts_per_slot=args.max_attempts_per_slot,
                max_slots=args.max_slots,
                max_runtime_seconds=args.max_runtime_seconds,
                generation_batch_size=args.generation_batch_size,
                parallel_workers=args.workers,
                subject=args.subject,
                apply=args.apply,
            )
            report = write_batch_production_workflow_report(report, root=root, apply=args.apply)
            if args.format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"schema: {report.get('schema_version')}",
                    f"status: {report.get('status')}",
                    f"batch_id: {report.get('batch_id')}",
                    f"executed_slot_count: {report.get('executed_slot_count')}",
                    f"staged_slot_count: {report.get('staged_slot_count')}",
                    f"failed_slot_count: {report.get('failed_slot_count')}",
                    f"skipped_slot_count: {report.get('skipped_slot_count')}",
                    f"generation_batch_size: {report.get('generation_batch_size')}",
                    f"parallel_workers: {report.get('parallel_workers')}",
                    f"parallel_execution_enabled: {report.get('parallel_execution_enabled')}",
                    f"batch_markdown_path: {report.get('batch_markdown_path')}",
                    f"batch_json_path: {report.get('batch_json_path')}",
                    "activation_implication: does_not_authorize_activation",
                ]))
            return 0 if report["status"] == "BATCH_COMPLETED" else 1
    except (AdminInventoryError, SourceReceiptError, AdminGateError, AdminProductionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
