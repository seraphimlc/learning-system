#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system.admin.expert_ideation import (
    build_expert_design_ideas,
    write_expert_design_ideas,
)
from learning_system.admin.full_bank_acceptance import (
    DEFAULT_STAGED_BANK_PATH,
    build_full_bank_acceptance,
    write_full_bank_acceptance,
)
from learning_system.admin.production_loop import (
    build_generation_plan_batch,
    build_question_requirement_plan,
    write_production_report,
)
from learning_system.admin.production_workflow import (
    run_batch_production_workflow,
    write_batch_production_workflow_report,
)
from learning_system.local_env import load_local_env_file


RUNNER_SCHEMA_VERSION = "2026-07-23.codex-admin.full-bank-production-runner.v1"
PRIORITY_NODE_ORDER = [
    "M-PRE-NUMBER-SENSE",
    "M-PRE-INTEGER-OPS",
    "M-PRE-DECIMAL-OPS",
    "M-PRE-ORDER-OPS",
    "M-PRE-FRACTION-MEANING",
    "M-PRE-FRACTION-OPS",
    "M-G7-POS-NEG",
    "M-G7-NUMBER-LINE",
    "M-G7-OPPOSITE",
    "M-G7-ABSOLUTE",
    "M-G7-COMPARE",
    "M-G7-RATIONAL-ADD-SUB",
    "M-G7-RATIONAL-MUL-DIV",
    "M-G7-RATIONAL-MIXED",
    "M-PRE-QUANTITY-RELATION",
    "M-PRE-EQUATION-BASIC",
    "M-G7-EQUALITY-PROP",
    "M-G7-EQ-SOLVE",
    "M-PRE-LETTER-EXPR",
    "M-G7-ALG-EXPR",
    "M-BRIDGE-SOLUTION-HABIT",
]
DEFERRED_NODE_ORDER = {
    "M-BRIDGE-CLOCK-ANGLE",
    "M-BRIDGE-WORK-RATE",
    "M-G7-GEO-VIEWS",
    "M-PRE-GEO-AREA-VOLUME",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"FULLBANK-RUN-{timestamp}-{uuid.uuid4().hex[:8]}"


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    rounds = payload.get("rounds") or []
    round_lines = [
        "| {round} | {node_count} | {plan_count} | {batch_status} | {staged_slot_count} | {failed_slot_count} | {elapsed_seconds} |".format(
            round=item.get("round_index", ""),
            node_count=len(item.get("nodes") or []),
            plan_count=len(item.get("generation_plan_paths") or []),
            batch_status=item.get("batch_status", ""),
            staged_slot_count=item.get("staged_slot_count", ""),
            failed_slot_count=item.get("failed_slot_count", ""),
            elapsed_seconds=item.get("elapsed_seconds", ""),
        )
        for item in rounds
    ] or ["| | | | | | | |"]
    _atomic_write_text(
        path,
        "\n".join(
            [
                "# Full Bank Production Runner",
                "",
                f"Status: `{payload.get('status')}`",
                "",
                f"Started At: {payload.get('started_at')}",
                "",
                f"Finished At: {payload.get('finished_at')}",
                "",
                f"Initial Full Bank: `{payload.get('initial_full_bank_report')}`",
                "",
                f"Final Full Bank: `{payload.get('final_full_bank_report')}`",
                "",
                f"Final Item Count: {payload.get('final_item_count')}",
                "",
                f"Final Raw Item Count: {payload.get('final_raw_item_count')}",
                "",
                f"Final Qualified Item Count: {payload.get('final_qualified_item_count')}",
                "",
                f"Final Disqualified Item Count: {payload.get('final_disqualified_item_count')}",
                "",
                f"Final Covered Nodes: {payload.get('final_covered_nodes')} / {payload.get('blueprint_node_count')}",
                "",
                f"Final Finding Counts: `{json.dumps(payload.get('final_finding_counts') or {}, ensure_ascii=False, sort_keys=True)}`",
                "",
                "## Rounds",
                "",
                "| Round | Nodes | Plans | Batch Status | Staged | Failed | Seconds |",
                "|---:|---:|---:|---|---:|---:|---:|",
                *round_lines,
                "",
                "Activation Implication: `does_not_authorize_activation`",
                "",
            ]
        ),
    )


def _gap_stage_for_node(
    *,
    node_id: str,
    budget_gap: dict[str, Any] | None,
    family_gaps: list[dict[str, Any]],
    target_gap: dict[str, Any] | None,
) -> int:
    if budget_gap and int(budget_gap.get("current") or 0) == 0:
        return 0
    if budget_gap:
        return 1
    if family_gaps:
        return 2
    if target_gap:
        return 3
    return 9


def _gap_node_records(full_bank: dict[str, Any]) -> list[dict[str, Any]]:
    budget_by_node = {
        str(gap.get("node_id") or ""): gap
        for gap in full_bank.get("budget_gaps") or []
        if str(gap.get("node_id") or "")
    }
    include_target = bool(full_bank.get("require_target", True))
    target_by_node = {
        str(gap.get("node_id") or ""): gap
        for gap in full_bank.get("target_gaps") or []
        if str(gap.get("node_id") or "")
    } if include_target else {}
    families_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for gap in full_bank.get("family_gaps") or []:
        node_id = str(gap.get("node_id") or "")
        if node_id:
            families_by_node[node_id].append(gap)

    node_ids = sorted(set(budget_by_node) | set(target_by_node) | set(families_by_node))
    priority_rank = {node_id: index for index, node_id in enumerate(PRIORITY_NODE_ORDER)}

    records: list[dict[str, Any]] = []
    for node_id in node_ids:
        budget_gap = budget_by_node.get(node_id)
        target_gap = target_by_node.get(node_id)
        family_gaps = families_by_node.get(node_id, [])
        family_gap_ids = _prioritized_family_gap_ids(family_gaps)
        family_gap_missing_by_id = _family_gap_missing_counts(family_gaps)
        family_missing = sum(
            max(0, int(gap.get("required") or 0) - int(gap.get("current") or 0))
            for gap in family_gaps
        )
        missing_to_min = int((budget_gap or {}).get("missing_to_min") or 0)
        missing_to_target = int((budget_gap or target_gap or {}).get("missing_to_target") or 0)
        records.append(
            {
                "node_id": node_id,
                "stage": _gap_stage_for_node(
                    node_id=node_id,
                    budget_gap=budget_gap,
                    family_gaps=family_gaps,
                    target_gap=target_gap,
                ),
                "current": int((budget_gap or target_gap or {}).get("current") or 0),
                "missing_to_min": missing_to_min,
                "missing_to_target": missing_to_target,
                "family_gap_count": len(family_gaps),
                "family_missing": family_missing,
                "family_gap_ids": family_gap_ids,
                "family_gap_missing_by_id": family_gap_missing_by_id,
                "priority_rank": priority_rank.get(node_id, 10_000),
                "is_deferred": node_id in DEFERRED_NODE_ORDER,
            }
        )

    records.sort(
        key=lambda record: (
            int(record["stage"]),
            bool(record["is_deferred"]),
            -int(record["missing_to_min"]),
            -int(record["family_missing"]),
            -int(record["missing_to_target"]),
            int(record["priority_rank"]),
            str(record["node_id"]),
        )
    )
    return records


def _prioritized_gap_nodes(full_bank: dict[str, Any]) -> list[str]:
    return [str(record["node_id"]) for record in _gap_node_records(full_bank)]


def _prioritized_family_gap_ids(family_gaps: list[dict[str, Any]]) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for gap in family_gaps:
        family_id = str(gap.get("family_id") or "")
        if not family_id:
            continue
        missing = max(0, int(gap.get("required") or 0) - int(gap.get("current") or 0))
        ranked.append((-missing, int(gap.get("current") or 0), family_id))
    return [family_id for _missing, _current, family_id in sorted(ranked)]


def _family_gap_missing_counts(family_gaps: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for gap in family_gaps:
        family_id = str(gap.get("family_id") or "")
        if not family_id:
            continue
        missing = max(0, int(gap.get("required") or 0) - int(gap.get("current") or 0))
        if missing:
            counts[family_id] = missing
    return counts


def _generation_plan_family_id(plan: dict[str, Any]) -> str:
    return str(
        plan.get("family_id")
        or ((plan.get("bounded_candidate_packet") or {}).get("question_requirement") or {}).get("family_id")
        or ""
    )


def _generation_plan_slot_order(plan: dict[str, Any]) -> int:
    requirement = (plan.get("bounded_candidate_packet") or {}).get("question_requirement") or {}
    try:
        return int(requirement.get("slot_order") or 10_000)
    except (TypeError, ValueError):
        return 10_000


def _select_unstaged_generation_plans(
    plans: list[dict[str, Any]],
    *,
    used_requirement_ids: set[str],
    used_slot_ids: set[str],
    family_gap_ids: list[str],
    family_gap_missing_by_id: dict[str, int] | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    family_rank = {family_id: index for index, family_id in enumerate(family_gap_ids)}
    family_gap_missing_by_id = dict(family_gap_missing_by_id or {})
    candidates = [
        plan
        for plan in plans
        if str(plan.get("question_requirement_id") or "") not in used_requirement_ids
        and str(plan.get("slot_id") or "") not in used_slot_ids
    ]
    candidates.sort(
        key=lambda plan: (
            family_rank.get(_generation_plan_family_id(plan), len(family_rank)),
            _generation_plan_slot_order(plan),
            str(plan.get("slot_id") or ""),
        )
    )
    selected: list[dict[str, Any]] = []
    selected_families: set[str] = set()
    for plan in candidates:
        family_id = _generation_plan_family_id(plan)
        if not family_id or family_id in selected_families:
            continue
        if family_gap_missing_by_id and int(family_gap_missing_by_id.get(family_id) or 0) <= 0:
            continue
        selected.append(plan)
        selected_families.add(family_id)
        if len(selected) >= limit:
            break
    return selected


def _make_plans_for_node(
    *,
    root: Path,
    node_id: str,
    version: str,
    subject: str,
    slots_per_node: int,
    family_gap_ids: list[str] | None = None,
    family_gap_missing_by_id: dict[str, int] | None = None,
    max_attempts_per_slot: int,
    staged_bank_path: Path,
    apply: bool,
) -> dict[str, Any]:
    design = build_expert_design_ideas(root=root, node_id=node_id, version=version, subject=subject)
    design = write_expert_design_ideas(design, root=root, apply=apply)
    design_path = Path(str(design.get("design_json_path") or ""))

    requirement = build_question_requirement_plan(
        root=root,
        node_id=node_id,
        version=version,
        subject=subject,
        design_brief_path=design_path,
        bank_path=staged_bank_path,
        max_attempts=max_attempts_per_slot,
    )
    requirement = write_production_report(requirement, root=root, apply=apply)
    requirement_path = Path(str(requirement.get("production_json_path") or ""))

    used_requirement_ids, used_slot_ids = _staged_requirement_and_slot_ids(
        root=root,
        staged_bank_path=staged_bank_path,
        node_id=node_id,
    )
    family_gap_ids = list(family_gap_ids or [])
    plan_limit = 100 if family_gap_ids else max(slots_per_node, slots_per_node + len(used_slot_ids))
    plan_batch = build_generation_plan_batch(
        root=root,
        node_id=node_id,
        requirement_plan_path=requirement_path,
        version=version,
        subject=subject,
        design_brief_path=design_path,
        bank_path=staged_bank_path,
        limit=min(100, plan_limit),
        max_attempts=max_attempts_per_slot,
    )
    written_plans = []
    if apply:
        selected_plans = _select_unstaged_generation_plans(
            list(plan_batch.get("generation_plans") or []),
            used_requirement_ids=used_requirement_ids,
            used_slot_ids=used_slot_ids,
            family_gap_ids=family_gap_ids,
            family_gap_missing_by_id=family_gap_missing_by_id,
            limit=slots_per_node,
        )
        for plan in selected_plans:
            written_plans.append(write_production_report(plan, root=root, apply=True))
    if written_plans:
        plan_batch = {
            **plan_batch,
            "generation_plans": written_plans,
            "generation_plan_paths": [plan["production_json_path"] for plan in written_plans],
        }
    plan_batch = write_production_report(plan_batch, root=root, apply=apply)
    return {
        "node_id": node_id,
        "design_status": design.get("status"),
        "design_path": design.get("design_json_path"),
        "requirement_status": requirement.get("status"),
        "requirement_path": requirement.get("production_json_path"),
        "plan_batch_status": plan_batch.get("status"),
        "plan_batch_path": plan_batch.get("production_json_path"),
        "generation_plan_paths": list(plan_batch.get("generation_plan_paths") or []),
        "skipped_existing_requirement_count": len(used_requirement_ids),
        "family_gap_ids": family_gap_ids,
        "family_gap_missing_by_id": dict(family_gap_missing_by_id or {}),
        "selected_family_ids": [_generation_plan_family_id(plan) for plan in written_plans],
        "finding_counts": {
            "requirement": requirement.get("finding_counts") or {},
            "plan_batch": plan_batch.get("finding_counts") or {},
        },
    }


def _staged_requirement_and_slot_ids(*, root: Path, staged_bank_path: Path, node_id: str) -> tuple[set[str], set[str]]:
    resolved = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    if not resolved.exists():
        return set(), set()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    requirement_ids: set[str] = set()
    slot_ids: set[str] = set()
    for item in payload.get("items") or []:
        if str(item.get("node_id") or "") != node_id:
            continue
        lineage = item.get("production_lineage") if isinstance(item.get("production_lineage"), dict) else {}
        requirement_id = str(lineage.get("question_requirement_id") or "")
        slot_id = str(lineage.get("slot_id") or "")
        if requirement_id:
            requirement_ids.add(requirement_id)
        if slot_id:
            slot_ids.add(slot_id)
    return requirement_ids, slot_ids


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    load_local_env_file(root / ".env.local")
    started_at = _utc_now()
    started = time.monotonic()
    absolute_deadline = started + args.max_runtime_seconds
    run_id = _new_run_id()
    json_path = root / "data/admin/full_bank_runs" / f"{run_id}.json"
    markdown_path = root / "docs/system/admin_reports/full_bank_runs" / f"{datetime.now(timezone.utc).date()}-{run_id}.md"

    initial_gate = write_full_bank_acceptance(
        build_full_bank_acceptance(
            root=root,
            bank_path=Path(args.staged_bank),
            subject=args.subject,
            require_target=args.require_target,
        ),
        root=root,
        apply=args.apply,
    )
    latest_gate = initial_gate
    payload: dict[str, Any] = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": "",
        "root": str(root),
        "subject": args.subject,
        "version": args.version,
        "apply": bool(args.apply),
        "require_target": bool(args.require_target),
        "staged_bank": args.staged_bank,
        "initial_full_bank_report": initial_gate.get("full_bank_json_path"),
        "rounds": [],
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "runner_json_path": str(json_path.relative_to(root)),
        "runner_markdown_path": str(markdown_path.relative_to(root)),
    }
    _write_json(json_path, payload)
    _write_markdown(markdown_path, payload)

    round_index = 0
    deadline_exhausted = False
    while time.monotonic() < absolute_deadline:
        round_index += 1
        round_started = time.monotonic()
        round_started_at = _utc_now()
        if time.monotonic() >= absolute_deadline:
            payload["blocked_reason"] = "runner_total_deadline_exhausted_before_round_acceptance"
            deadline_exhausted = True
            break
        gate = write_full_bank_acceptance(
            build_full_bank_acceptance(
                root=root,
                bank_path=Path(args.staged_bank),
                subject=args.subject,
                require_target=args.require_target,
            ),
            root=root,
            apply=args.apply,
        )
        latest_gate = gate
        gap_records = _gap_node_records(gate)
        gap_nodes = [str(record["node_id"]) for record in gap_records]
        if not gap_nodes:
            if gate.get("status") != "PASS":
                payload["status"] = "STOPPED_ACCEPTANCE_NOT_PASS"
                payload["blocked_reason"] = "full_bank_has_blocking_findings_without_actionable_generation_gaps"
            break
        selected_nodes = gap_nodes[: args.nodes_per_round]
        selected_gap_records = [
            record
            for record in gap_records
            if str(record.get("node_id") or "") in set(selected_nodes)
        ]
        gap_record_by_node = {str(record.get("node_id") or ""): record for record in selected_gap_records}
        node_reports = []
        plan_paths: list[str] = []
        for node_id in selected_nodes:
            if time.monotonic() >= absolute_deadline:
                payload["blocked_reason"] = "runner_total_deadline_exhausted_before_node_planning"
                deadline_exhausted = True
                break
            try:
                node_report = _make_plans_for_node(
                    root=root,
                    node_id=node_id,
                    version=args.version,
                    subject=args.subject,
                    slots_per_node=args.slots_per_node,
                    family_gap_ids=list(gap_record_by_node.get(node_id, {}).get("family_gap_ids") or []),
                    family_gap_missing_by_id=dict(gap_record_by_node.get(node_id, {}).get("family_gap_missing_by_id") or {}),
                    max_attempts_per_slot=args.max_attempts_per_slot,
                    staged_bank_path=Path(args.staged_bank),
                    apply=args.apply,
                )
            except Exception as exc:  # noqa: BLE001 - admin runner must record and continue.
                node_report = {
                    "node_id": node_id,
                    "status": "NODE_PLAN_FAILED",
                    "error": str(exc),
                    "generation_plan_paths": [],
                }
            node_reports.append(node_report)
            plan_paths.extend(node_report.get("generation_plan_paths") or [])

        batch_report: dict[str, Any] = {
            "status": "SKIPPED_NO_GENERATION_PLANS",
            "staged_slot_count": 0,
            "failed_slot_count": 0,
            "batch_json_path": "",
        }
        if plan_paths and not deadline_exhausted:
            remaining_runtime = absolute_deadline - time.monotonic()
            if remaining_runtime <= 0:
                payload["blocked_reason"] = "runner_total_deadline_exhausted_before_batch_workflow"
                deadline_exhausted = True
            else:
                batch_budget = min(args.batch_runtime_seconds, remaining_runtime)
                batch_report = run_batch_production_workflow(
                    root=root,
                    generation_plan_paths=[Path(path) for path in plan_paths],
                    staged_bank_path=Path(args.staged_bank),
                    max_attempts_per_slot=args.max_attempts_per_slot,
                    max_slots=min(args.max_slots_per_round, len(plan_paths)),
                    max_runtime_seconds=batch_budget,
                    generation_batch_size=1,
                    parallel_workers=args.workers,
                    subject=args.subject,
                    apply=args.apply,
                )
                batch_report = write_batch_production_workflow_report(
                    batch_report,
                    root=root,
                    apply=args.apply,
                )

        round_report = {
            "round_index": round_index,
            "started_at": round_started_at,
            "nodes": node_reports,
            "selected_gap_records": selected_gap_records,
            "generation_plan_paths": plan_paths,
            "batch_status": batch_report.get("status"),
            "batch_id": batch_report.get("batch_id"),
            "batch_json_path": batch_report.get("batch_json_path"),
            "staged_slot_count": batch_report.get("staged_slot_count", 0),
            "failed_slot_count": batch_report.get("failed_slot_count", 0),
            "executed_slot_count": batch_report.get("executed_slot_count", 0),
            "elapsed_seconds": round(time.monotonic() - round_started, 3),
        }
        payload["rounds"].append(round_report)
        _write_json(json_path, payload)
        _write_markdown(markdown_path, payload)
        print(
            json.dumps(
                {
                    "event": "full_bank_round_completed",
                    "run_id": run_id,
                    "round_index": round_index,
                    "nodes": selected_nodes,
                    "batch_status": batch_report.get("status"),
                    "staged_slot_count": batch_report.get("staged_slot_count", 0),
                    "failed_slot_count": batch_report.get("failed_slot_count", 0),
                    "elapsed_seconds": round_report["elapsed_seconds"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )

        if deadline_exhausted:
            break
        if not plan_paths:
            payload["status"] = "STOPPED_NO_GENERATION_PLANS"
            payload["blocked_reason"] = "selected_gap_nodes_produced_no_generation_plans"
            break
        if batch_report.get("status") in {"BATCH_COMPLETED_WITH_FAILURES", "BATCH_PARTIAL_BUDGET_EXHAUSTED"} and args.stop_on_batch_problem:
            payload["status"] = "STOPPED_ON_BATCH_PROBLEM"
            break
        if args.max_rounds and round_index >= args.max_rounds:
            payload["status"] = "STOPPED_ON_ROUND_LIMIT"
            break

    if time.monotonic() < absolute_deadline:
        final_gate = write_full_bank_acceptance(
            build_full_bank_acceptance(
                root=root,
                bank_path=Path(args.staged_bank),
                subject=args.subject,
                require_target=args.require_target,
            ),
            root=root,
            apply=args.apply,
        )
    else:
        final_gate = latest_gate
    if final_gate.get("status") == "PASS":
        payload["status"] = "COMPLETED_FULL_BANK_PASS"
        payload.pop("blocked_reason", None)
    elif payload.get("status") == "RUNNING":
        payload["status"] = "COMPLETED_TIME_BUDGET"
    payload.update(
        {
            "finished_at": _utc_now(),
            "final_full_bank_report": final_gate.get("full_bank_json_path"),
            "final_full_bank_status": final_gate.get("status"),
            "final_item_count": final_gate.get("item_count"),
            "final_raw_item_count": final_gate.get("raw_item_count", final_gate.get("item_count")),
            "final_qualified_item_count": final_gate.get("qualified_item_count"),
            "final_disqualified_item_count": final_gate.get("disqualified_item_count"),
            "final_covered_nodes": final_gate.get("covered_node_count"),
            "blueprint_node_count": final_gate.get("blueprint_node_count"),
            "final_finding_counts": final_gate.get("finding_counts") or {},
            "final_budget_gap_count": len(final_gate.get("budget_gaps") or []),
            "final_target_gap_count": len(final_gate.get("target_gaps") or []),
            "final_target_shortfall_count": len(final_gate.get("target_shortfalls") or []),
            "final_over_max_gap_count": len(final_gate.get("over_max_gaps") or []),
            "final_family_gap_count": len(final_gate.get("family_gaps") or []),
        }
    )
    _write_json(json_path, payload)
    _write_markdown(markdown_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if final_gate.get("status") == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run gated full-bank question production.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--subject", default="math")
    parser.add_argument("--version", default="v18")
    parser.add_argument("--staged-bank", default=str(DEFAULT_STAGED_BANK_PATH))
    parser.add_argument("--max-runtime-seconds", type=float, default=8 * 60 * 60)
    parser.add_argument("--batch-runtime-seconds", type=float, default=45 * 60)
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--nodes-per-round", type=int, default=3)
    parser.add_argument("--slots-per-node", type=int, default=3)
    parser.add_argument("--max-slots-per-round", type=int, default=9)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-attempts-per-slot", type=int, default=3)
    parser.add_argument("--require-target", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stop-on-batch-problem", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
