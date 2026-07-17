#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date as RealDate
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable
from unittest.mock import patch
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import (  # noqa: E402
    auto_review,
    daily_runtime,
    db,
    graph_runtime,
    internal_agents,
    model_router,
    question_bank,
    reports,
    semantic_agents,
    server,
)


DEFAULT_CONTRACT = PROJECT_ROOT / "tests/fixtures/v5_10_lesson_harness_contract.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "artifacts/v5-10-lesson-harness"
DEFAULT_GRAPH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
SUBMIT_ROUTE = "/api/current-step/submit"
MODEL_PHASES = ("answer_analysis", "evaluation_update", "planner_decision", "teaching_generation")
CONCLUSION_STATES = {
    "current_step",
    "feedback_teaching",
    "clarify_evidence",
    "ready_for_new_knowledge",
    "blocked",
    "summary",
}
CHILD_FORBIDDEN_TEXT = (
    "api_key",
    "provider_mode",
    "graph_version",
    "question_id",
    "attempt_id",
    "flow_id",
    "job_id",
    "expected_answer",
    "response_schema",
    "candidate_packet",
    "codex",
    "agent_run",
)
JSON_COLUMNS = {
    "payload_json",
    "result_refs_json",
    "route_meta_json",
    "input_refs_json",
    "model_params_json",
    "output_json",
    "validation_errors_json",
    "predicate_result_json",
    "decision_payload_json",
    "dimension_scores_json",
    "source_attempt_ids_json",
    "source_evidence_validation_ids_json",
    "source_mastery_decision_ids_json",
    "source_next_step_decision_ids_json",
    "source_step_ids_json",
    "touched_node_ids_json",
    "late_evidence_included_ids_json",
    "late_evidence_excluded_ids_json",
    "report_label_json",
    "operator_summary_json",
    "child_summary_json",
    "answer_analysis_json",
    "review_meta_json",
    "error_tags_json",
    "attachment_ids_json",
    "selection_reason_json",
    "expected_evidence_json",
    "prompt_package_json",
}


def load_contract(path: Path | str = DEFAULT_CONTRACT) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if contract.get("schema_version") != "2026-07-11.v5.10-lesson-harness-contract.v2":
        issues.append("contract schema version is not v2")
    execution = contract.get("execution_contract") if isinstance(contract.get("execution_contract"), dict) else {}
    lessons = contract.get("lessons") if isinstance(contract.get("lessons"), list) else []
    if execution.get("lesson_count") != 10 or len(lessons) != 10:
        issues.append("contract must define exactly ten lessons")
    if not execution.get("independent_temp_db_per_lesson"):
        issues.append("each lesson must use an independent temporary database")
    if not execution.get("adaptive_current_step_only") or execution.get("pre_read_fixed_question_list"):
        issues.append("lesson progression must be adaptive from the current visible step")
    if execution.get("browser_entry_state") != "start_resume":
        issues.append("each browser lesson must enter through start_resume")
    lesson_ids = [str(item.get("id") or "") for item in lessons]
    lesson_dates = [str(item.get("local_date") or "") for item in lessons]
    if len(set(lesson_ids)) != 10 or "" in lesson_ids:
        issues.append("lesson ids must be non-empty and unique")
    if len(set(lesson_dates)) != 10 or "" in lesson_dates:
        issues.append("lesson local dates must be non-empty and unique")
    coverage: set[str] = set()
    for lesson in lessons:
        budget = lesson.get("interaction_budget") if isinstance(lesson.get("interaction_budget"), dict) else {}
        minimum = int(budget.get("minimum") or 0)
        maximum = int(budget.get("maximum") or 0)
        target = int(budget.get("target") or 0)
        if minimum < 10 or maximum > 20 or not minimum <= target <= maximum:
            issues.append(f"{lesson.get('id')}: interaction budget must stay within 10-20")
        if not lesson.get("target_node_id"):
            issues.append(f"{lesson.get('id')}: target_node_id is required")
        coverage.update(str(item) for item in lesson.get("coverage") or [])
    missing_coverage = sorted(set(contract.get("required_coverage") or []) - coverage)
    if missing_coverage:
        issues.append(f"missing coverage tags: {', '.join(missing_coverage)}")
    rollbacks = contract.get("prerequisite_rollback_oracles") or []
    if len(rollbacks) != 4 or any(len(item.get("chain") or []) < 4 for item in rollbacks):
        issues.append("four prerequisite rollback chains with at least four nodes are required")
    model_contract = contract.get("model_contract") if isinstance(contract.get("model_contract"), dict) else {}
    if model_contract.get("default_mode") != "recorded_model":
        issues.append("default model mode must be recorded_model")
    if model_contract.get("patched_outputs_may_be_labeled_live") is not False:
        issues.append("patched outputs must never be labeled live")
    verdict = contract.get("verdict_contract") if isinstance(contract.get("verdict_contract"), dict) else {}
    recorded = verdict.get("recorded_model") if isinstance(verdict.get("recorded_model"), dict) else {}
    if "PASS" in (recorded.get("semantic_quality_allowed") or []):
        issues.append("recorded mode cannot claim an unscoped semantic PASS")
    if "PASS" in (recorded.get("teaching_quality_allowed") or []):
        issues.append("recorded mode cannot claim an unscoped teaching PASS")
    live_fault = contract.get("live_fault_injection_contract") if isinstance(contract.get("live_fault_injection_contract"), dict) else {}
    fault_stages = live_fault.get("stages") if isinstance(live_fault.get("stages"), list) else []
    if live_fault.get("lesson_id") != "L09-model-recovery":
        issues.append("live fault injection must be scoped only to L09-model-recovery")
    if [str(item.get("fault_type") or "") for item in fault_stages] != [
        "not_configured",
        "controlled_retryable_failure",
    ]:
        issues.append("live fault injection must define not_configured then controlled_retryable_failure")
    if live_fault.get("workflow_evidence_only") is not True or live_fault.get("excluded_from_live_semantic_verdict") is not True:
        issues.append("live fault injection outcomes must be workflow-only and excluded from live semantic verdicts")
    if live_fault.get("other_live_lessons_external_model_calls_unpatched") is not True:
        issues.append("non-L09 live lessons must retain unpatched external model calls")
    return issues


def load_graph_prerequisites(path: Path | str = DEFAULT_GRAPH) -> dict[str, list[str]]:
    graph = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    return {
        str(node.get("id") or ""): [str(item) for item in node.get("prerequisites") or [] if str(item)]
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }


def live_fault_injection_spec_for_lesson(
    contract: dict[str, Any],
    lesson: dict[str, Any],
    model_mode: str,
) -> dict[str, Any] | None:
    spec = contract.get("live_fault_injection_contract")
    if not isinstance(spec, dict) or model_mode != "live_model":
        return None
    if str(lesson.get("id") or "") != str(spec.get("lesson_id") or ""):
        return None
    return spec


def _accepted_live_semantic_runs(evidence: dict[str, Any], *, phase: str | None = None) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for run in evidence.get("agent_runs") or []:
        if str(run.get("status") or "") != "accepted" or str(run.get("engine_type") or "") != "model":
            continue
        if phase and str(run.get("phase") or "") != phase:
            continue
        provider = str(run.get("model_provider") or "")
        params = run.get("model_params_value") if isinstance(run.get("model_params_value"), dict) else {}
        if not provider or provider in {"recorded_model", "mock_only"}:
            continue
        if str(params.get("provider_mode") or params.get("trust_mode") or "live_model") != "live_model":
            continue
        refs = run.get("input_refs_value") if isinstance(run.get("input_refs_value"), dict) else {}
        accepted.append({
            "agent_run_id": str(run.get("id") or ""),
            "phase": str(run.get("phase") or ""),
            "attempt_id": str(refs.get("attempt_id") or ""),
            "model_provider": provider,
            "model_name": str(run.get("model_name") or ""),
            "provider_mode": "live_model",
        })
    return accepted


def audit_live_fault_injection(
    contract: dict[str, Any],
    lesson: dict[str, Any],
    model_mode: str,
    fault_trace: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    spec = live_fault_injection_spec_for_lesson(contract, lesson, model_mode)
    all_live_runs = _accepted_live_semantic_runs(evidence)
    if spec is None:
        return {
            "applicable": False,
            "passed": True,
            "issues": [],
            "fault_injection_workflow_evidence": [],
            "live_semantic_evidence": all_live_runs,
        }
    issues: list[str] = []
    expected_stages = list(spec.get("stages") or [])
    jobs_by_id = {str(item.get("id") or ""): item for item in evidence.get("background_jobs") or []}
    live_answer_runs = _accepted_live_semantic_runs(evidence, phase="answer_analysis")
    live_runs_by_attempt: dict[str, list[dict[str, Any]]] = {}
    for run in live_answer_runs:
        live_runs_by_attempt.setdefault(str(run.get("attempt_id") or ""), []).append(run)
    semantic_evidence: list[dict[str, Any]] = []
    if len(fault_trace) != len(expected_stages):
        issues.append(
            f"live fault injection produced {len(fault_trace)} events; expected {len(expected_stages)}"
        )
    for index, stage in enumerate(expected_stages):
        if index >= len(fault_trace):
            break
        event = fault_trace[index]
        expected_type = str(stage.get("fault_type") or "")
        fault_type = str(event.get("fault_type") or "")
        attempt_id = str(event.get("attempt_id") or "")
        job_id = str(event.get("job_id") or "")
        if int(event.get("ordinal") or 0) != int(stage.get("ordinal") or index + 1):
            issues.append(f"live fault event {index + 1} has the wrong ordinal")
        if fault_type != expected_type:
            issues.append(
                f"live fault event {index + 1} is {fault_type or '<missing>'}; expected {expected_type}"
            )
        if not event.get("saved_before_injection") or not attempt_id or not job_id:
            issues.append(f"live fault event {index + 1} was not proven after durable attempt/job save")
        if not event.get("fault_injected") or event.get("semantic_evidence_eligible") is not False:
            issues.append(f"live fault event {index + 1} is not explicitly workflow-only fault_injected evidence")
        expected_status = str(stage.get("expected_job_status") or "")
        if expected_status and str(event.get("observed_job_status") or "") != expected_status:
            issues.append(
                f"live fault event {index + 1} observed job status {event.get('observed_job_status')!r}; "
                f"expected {expected_status!r}"
            )
        job = jobs_by_id.get(job_id)
        marker = job.get("payload_value", {}).get("fault_injected") if isinstance(job, dict) else None
        if not isinstance(marker, dict) or str(marker.get("fault_type") or "") != expected_type:
            issues.append(f"live fault event {index + 1} is missing its durable fault_injected job marker")
        recovered_runs = live_runs_by_attempt.get(attempt_id, [])
        if not recovered_runs:
            issues.append(
                f"live fault event {index + 1} attempt {attempt_id or '<missing>'} has no accepted real live "
                "answer-analysis recovery"
            )
        else:
            semantic_evidence.extend(recovered_runs)
    unique_semantic = {
        item["agent_run_id"]: item for item in semantic_evidence if item.get("agent_run_id")
    }
    return {
        "applicable": True,
        "passed": not issues,
        "issues": issues,
        "fault_injection_workflow_evidence": fault_trace,
        "live_semantic_evidence": list(unique_semantic.values()),
        "all_live_model_agent_runs": all_live_runs,
        "scope_statement": (
            "fault_injected events prove only save/retry/recovery workflow; only subsequent accepted real-provider "
            "agent runs are eligible live semantic evidence"
        ),
    }


def _list_field(record: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value.strip():
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item)]
    return []


def audit_prerequisite_rollback(
    rollback_contract: dict[str, Any],
    decisions: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    graph_prerequisites: dict[str, list[str]],
    *,
    terminal_state: str,
) -> dict[str, Any]:
    rollback_id = str(rollback_contract.get("id") or "unnamed_rollback")
    chain = [str(item) for item in rollback_contract.get("chain") or [] if str(item)]
    required_depth = int(rollback_contract.get("required_depth") or 0)
    safe_stop_allowed = bool(rollback_contract.get("safe_stop_allowed"))
    issues: list[str] = []
    transitions: list[dict[str, Any]] = []
    attempt_by_id = {str(item.get("id") or ""): item for item in attempts if item.get("id")}
    prerequisite_decisions = [item for item in decisions if item.get("action") == "prerequisite_probe"]
    expected_edge_index = 0
    seen_source_attempt_ids: set[str] = set()

    if len(chain) < 2:
        issues.append(f"{rollback_id}: rollback contract has no traversable chain")
    if required_depth < 1 or required_depth > max(0, len(chain) - 1):
        issues.append(f"{rollback_id}: required depth {required_depth} is outside the contract chain")
    if not prerequisite_decisions:
        issues.append(f"{rollback_id}: no prerequisite_probe decision was materialized")

    for decision in prerequisite_decisions:
        decision_id = str(decision.get("id") or "<missing-decision-id>")
        source_attempt_ids = _list_field(
            decision,
            "source_attempt_ids_value",
            "source_attempt_ids",
            "source_attempt_ids_json",
        )
        transition = {
            "decision_id": decision_id,
            "source_attempt_ids": source_attempt_ids,
            "source_attempt_id": source_attempt_ids[0] if len(source_attempt_ids) == 1 else "",
            "source_node_id": "",
            "source_result": "",
            "source_blocking_evidence": False,
            "target_node_id": str(decision.get("target_node_id") or ""),
            "direct_prerequisites": [],
            "matches_ordered_prefix": False,
        }
        transitions.append(transition)
        if len(source_attempt_ids) != 1:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} must reference exactly one source attempt"
            )
            continue
        source_attempt_id = source_attempt_ids[0]
        if source_attempt_id in seen_source_attempt_ids:
            issues.append(
                f"{rollback_id}: source attempt {source_attempt_id} drives duplicate prerequisite transitions"
            )
        seen_source_attempt_ids.add(source_attempt_id)
        attempt = attempt_by_id.get(source_attempt_id)
        if not attempt:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} references missing source attempt {source_attempt_id}"
            )
            continue
        source_node_id = str(attempt.get("node_id") or "")
        source_result = str(attempt.get("result") or "")
        source_blocking = bool(attempt.get("blocking_evidence"))
        target_node_id = transition["target_node_id"]
        direct_prerequisites = [str(item) for item in graph_prerequisites.get(source_node_id, []) if str(item)]
        transition.update({
            "source_node_id": source_node_id,
            "source_result": source_result,
            "source_blocking_evidence": source_blocking,
            "direct_prerequisites": direct_prerequisites,
        })
        if source_result != "wrong" or not source_blocking:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} source attempt {source_attempt_id} "
                "is not wrong blocking evidence"
            )
        if not source_node_id or not target_node_id:
            issues.append(f"{rollback_id}: prerequisite decision {decision_id} has an empty source or target node")
        if source_node_id and source_node_id == target_node_id:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} targets the same node {source_node_id}"
            )
        if target_node_id not in direct_prerequisites:
            issues.append(
                f"{rollback_id}: {source_node_id} -> {target_node_id} is not a graph-legal direct prerequisite"
            )
        if expected_edge_index >= len(chain) - 1:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} exceeds the ordered contract prefix"
            )
            continue
        expected_source = chain[expected_edge_index]
        expected_target = chain[expected_edge_index + 1]
        if source_node_id != expected_source or target_node_id != expected_target:
            issues.append(
                f"{rollback_id}: prerequisite decision {decision_id} does not match ordered contract prefix "
                f"{expected_source} -> {expected_target}; got {source_node_id} -> {target_node_id}"
            )
            continue
        transition["matches_ordered_prefix"] = True
        expected_edge_index += 1

    depth_proven = expected_edge_index
    if depth_proven < required_depth:
        issues.append(
            f"{rollback_id}: proven rollback depth {depth_proven} is below required depth {required_depth}"
        )
    stopped_before_chain_end = depth_proven < max(0, len(chain) - 1)
    safe_stop_used = stopped_before_chain_end and depth_proven >= required_depth
    if safe_stop_used and not safe_stop_allowed:
        issues.append(
            f"{rollback_id}: rollback stopped before the full chain but the contract does not allow safe-stop"
        )
    if safe_stop_used and terminal_state != "summary":
        issues.append(
            f"{rollback_id}: safe-stop requires terminal summary, got {terminal_state or '<missing>'}"
        )
    return {
        "id": rollback_id,
        "passed": not issues,
        "issues": issues,
        "expected_chain": chain,
        "required_depth": required_depth,
        "depth_proven": depth_proven,
        "actual_prefix": chain[: depth_proven + 1] if chain else [],
        "safe_stop_allowed": safe_stop_allowed,
        "safe_stop_used": safe_stop_used,
        "terminal_state": terminal_state,
        "transitions": transitions,
    }


def _agent_run_trust_label(run: dict[str, Any]) -> tuple[str, str]:
    engine_type = str(run.get("engine_type") or "")
    provider = str(run.get("model_provider") or "")
    params = run.get("model_params_value") if isinstance(run.get("model_params_value"), dict) else {}
    output = run.get("output_value") if isinstance(run.get("output_value"), dict) else {}
    explicit = str(
        params.get("provider_mode")
        or params.get("trust_mode")
        or output.get("provider_mode")
        or output.get("report_label")
        or ""
    )
    if engine_type == "deterministic":
        if explicit in {"deterministic_runtime", "inferred"}:
            return "deterministic_runtime", ""
        if explicit in {"pending", "blocked", "not_configured"}:
            return "pending", ""
        return "unlabeled", "accepted deterministic run lacks deterministic_runtime/inferred/pending label"
    if engine_type == "model":
        if provider == "recorded_model":
            return "recorded_model", ""
        if provider == "mock_only":
            return "mock_only", "accepted model run uses mock_only provider"
        if provider:
            return "live_model", ""
        if explicit in {"deterministic_runtime", "inferred"}:
            return "deterministic_runtime", ""
        if explicit in {"pending", "blocked", "not_configured"}:
            return "pending", ""
        return "unlabeled", "accepted model run has no live/recorded provider or explicit deterministic_runtime/inferred/pending label"
    if explicit in {"deterministic_runtime", "inferred"}:
        return "deterministic_runtime", ""
    if explicit in {"pending", "blocked", "not_configured"}:
        return "pending", ""
    return "unlabeled", f"accepted run has unsupported engine_type {engine_type or '<missing>'}"


def audit_trust_labels(evidence: dict[str, Any], *, declared_model_mode: str) -> dict[str, Any]:
    issues: list[str] = []
    scope_reasons: list[str] = []
    labels_by_source: dict[str, set[str]] = {
        "background_jobs": set(),
        "agent_runs": set(),
        "next_step_decisions": set(),
        "daily_summaries": set(),
    }
    accepted_labels: set[str] = set()

    for job in evidence.get("background_jobs") or []:
        job_id = str(job.get("id") or "<missing-job-id>")
        status = str(job.get("status") or "")
        provider_mode = str(job.get("provider_mode") or "")
        label = provider_mode or "unlabeled"
        labels_by_source["background_jobs"].add(label)
        if status == "succeeded":
            if provider_mode not in {"recorded_model", "live_model", "deterministic_runtime"}:
                issues.append(
                    f"background job {job_id} succeeded without recorded/live/deterministic provider_mode"
                )
            else:
                accepted_labels.add(provider_mode)
                if declared_model_mode == "recorded_model" and provider_mode == "live_model":
                    issues.append(f"background job {job_id} is live_model inside a recorded_model run")
                if declared_model_mode == "live_model" and provider_mode == "recorded_model":
                    issues.append(f"background job {job_id} is recorded_model inside a live_model run")

    run_labels_by_id: dict[str, str] = {}
    for run in evidence.get("agent_runs") or []:
        run_id = str(run.get("id") or "<missing-agent-run-id>")
        if str(run.get("status") or "") != "accepted":
            labels_by_source["agent_runs"].add("pending")
            continue
        phase = str(run.get("phase") or "")
        if phase not in MODEL_PHASES:
            provider = str(run.get("model_provider") or "")
            if provider == "recorded_model":
                label = "non_v5_recorded_model"
            elif provider == "mock_only":
                label = "non_v5_mock_only"
            elif provider:
                label = "non_v5_live_model"
            else:
                label = "non_v5_runtime"
            run_labels_by_id[run_id] = label
            labels_by_source["agent_runs"].add(label)
            continue
        label, issue = _agent_run_trust_label(run)
        run_labels_by_id[run_id] = label
        labels_by_source["agent_runs"].add(label)
        if label not in {"unlabeled", "pending"}:
            accepted_labels.add(label)
        if issue:
            issues.append(f"agent run {run_id}: {issue}")
        if declared_model_mode == "recorded_model" and label == "live_model":
            issues.append(f"agent run {run_id} is live_model inside a recorded_model run")
        if declared_model_mode == "live_model" and label in {"recorded_model", "mock_only"}:
            issues.append(f"agent run {run_id} is {label} inside a live_model run")

    decision_labels_by_id: dict[str, str] = {}
    for decision in evidence.get("next_step_decisions") or []:
        decision_id = str(decision.get("id") or "<missing-decision-id>")
        provider_mode = str(decision.get("provider_mode") or "")
        report_label = str(decision.get("report_label") or "")
        if provider_mode == "deterministic_runtime" or (not provider_mode and report_label == "inferred"):
            label = "deterministic_runtime"
            if report_label not in {"inferred", "deterministic_runtime"}:
                issues.append(
                    f"next-step decision {decision_id} deterministic_runtime provider lacks inferred report label"
                )
        elif provider_mode == "recorded_model":
            label = "recorded_model"
        elif provider_mode == "live_model":
            label = "live_model"
        elif provider_mode == "mock_only":
            label = "mock_only"
            issues.append(f"next-step decision {decision_id} uses mock_only provider")
        elif report_label in {"pending", "blocked", "not_configured"} or provider_mode == "not_configured":
            label = "pending"
        else:
            label = "unlabeled"
            issues.append(
                f"next-step decision {decision_id} has no recorded/live/deterministic/pending trust label"
            )
        decision_labels_by_id[decision_id] = label
        labels_by_source["next_step_decisions"].add(label)
        if label not in {"unlabeled", "pending"}:
            accepted_labels.add(label)

    for summary in evidence.get("daily_summaries") or []:
        summary_id = str(summary.get("id") or "<missing-summary-id>")
        source_decision_ids = _list_field(
            summary,
            "source_next_step_decision_ids_value",
            "source_next_step_decision_ids",
            "source_next_step_decision_ids_json",
        )
        source_labels = {
            decision_labels_by_id[decision_id]
            for decision_id in source_decision_ids
            if decision_id in decision_labels_by_id
        }
        missing_decision_ids = [item for item in source_decision_ids if item not in decision_labels_by_id]
        if missing_decision_ids:
            issues.append(
                f"daily summary {summary_id} references missing next-step decisions: {', '.join(missing_decision_ids)}"
            )
        operator = summary.get("operator_summary_value") if isinstance(summary.get("operator_summary_value"), dict) else {}
        phase_lineage = operator.get("phase_lineage") if isinstance(operator.get("phase_lineage"), dict) else {}
        lineage_modes = {str(item) for item in phase_lineage.get("provider_modes") or [] if str(item)}
        source_labels.update(
            item for item in lineage_modes if item in {"recorded_model", "live_model", "deterministic_runtime"}
        )
        if "recorded_model" in source_labels and "deterministic_runtime" in source_labels:
            label = "mixed_recorded_deterministic"
            if "deterministic_runtime" not in lineage_modes:
                scope_reasons.append(
                    f"daily summary {summary_id} is mixed because source decisions include deterministic_runtime "
                    "even though phase_lineage.provider_modes lists only durable model jobs"
                )
        elif "live_model" in source_labels and "deterministic_runtime" in source_labels:
            label = "mixed_live_deterministic"
        elif "recorded_model" in source_labels:
            label = "recorded_model"
        elif "live_model" in source_labels:
            label = "live_model"
        elif "deterministic_runtime" in source_labels:
            label = "deterministic_runtime"
        elif source_labels <= {"pending", "unlabeled"} and source_labels:
            label = "pending"
        else:
            label = "unlabeled"
            issues.append(f"daily summary {summary_id} has no traceable provider trust scope")
        labels_by_source["daily_summaries"].add(label)
        if label == "mixed_recorded_deterministic":
            accepted_labels.update({"recorded_model", "deterministic_runtime"})
        elif label == "mixed_live_deterministic":
            accepted_labels.update({"live_model", "deterministic_runtime"})
        elif label not in {"unlabeled", "pending"}:
            accepted_labels.add(label)

    if "recorded_model" in accepted_labels and "deterministic_runtime" in accepted_labels:
        effective_scope = "mixed_recorded_deterministic"
    elif "live_model" in accepted_labels and "deterministic_runtime" in accepted_labels:
        effective_scope = "mixed_live_deterministic"
    elif "recorded_model" in accepted_labels:
        effective_scope = "recorded_model"
    elif "live_model" in accepted_labels:
        effective_scope = "live_model"
    elif "deterministic_runtime" in accepted_labels:
        effective_scope = "deterministic_runtime"
    elif "mock_only" in accepted_labels:
        effective_scope = "mock_only"
    else:
        effective_scope = "pending"
    if effective_scope.startswith("mixed_"):
        scope_reasons.append(
            "accepted lineage combines model-backed stages with deterministic runtime decisions; "
            "semantic and teaching verdicts must retain mixed-trust scope"
        )
    return {
        "passed": not issues,
        "issues": issues,
        "declared_model_mode": declared_model_mode,
        "effective_scope": effective_scope,
        "labels_by_source": {key: sorted(value) for key, value in labels_by_source.items()},
        "scope_reasons": list(dict.fromkeys(scope_reasons)),
    }


def build_verdicts(
    model_mode: str,
    *,
    workflow_issues: list[str],
    semantic_issues: list[str],
    teaching_issues: list[str],
    trust_scope: str | None = None,
) -> dict[str, dict[str, Any]]:
    workflow_status = "NEEDS_FIX" if workflow_issues else "PASS"
    mixed_scope = trust_scope in {
        "mixed_recorded_deterministic",
        "mixed_live_deterministic",
        "deterministic_runtime",
        "pending",
    }
    if mixed_scope:
        semantic_status = "NEEDS_FIX" if semantic_issues else "PASS_WITH_MIXED_TRUST_SCOPE"
        teaching_status = "NEEDS_FIX" if teaching_issues else "PASS_WITH_MIXED_TRUST_SCOPE"
    elif model_mode == "live_model":
        semantic_status = "NEEDS_FIX" if semantic_issues else "PASS"
        teaching_status = "NEEDS_FIX" if teaching_issues else "PASS"
    else:
        semantic_status = "NEEDS_FIX" if semantic_issues else "PASS_WITH_RECORDED_ORACLE_SCOPE"
        teaching_status = "NEEDS_FIX" if teaching_issues else "PASS_WITH_RECORDED_ORACLE_SCOPE"
    return {
        "workflow": {"status": workflow_status, "issues": workflow_issues},
        "semantic_quality": {"status": semantic_status, "issues": semantic_issues, "trust_scope": trust_scope or model_mode},
        "teaching_quality": {"status": teaching_status, "issues": teaching_issues, "trust_scope": trust_scope or model_mode},
    }


def _recorded_route(agent_key: str, task: str) -> model_router.ModelRoute:
    return model_router.ModelRoute(
        agent_key=agent_key,
        task=task,
        provider="recorded_model",
        model="recorded-v5-10-lesson-oracle",
        model_alias="recorded-v5-10-lesson-oracle",
        base_url="recorded://v5-10-lesson-oracle",
        api_key="recorded-oracle",
        timeout_seconds=1.0,
        model_params={"mode": "recorded_model", "fixture_family": "v5_10_lesson_harness"},
    )


def _disabled_route(agent_key: str, task: str) -> model_router.ModelRoute:
    return model_router.ModelRoute(
        agent_key=agent_key,
        task=task,
        provider="",
        model="",
        model_alias="",
        base_url="",
        api_key="",
        timeout_seconds=1.0,
        model_params={},
    )


def _answer_analysis(question: dict[str, Any], answer_class: str) -> dict[str, Any]:
    optimal = str(question.get("expected_answer") or "需要按题意完成")
    optimal_steps = [str(item) for item in question.get("solution_steps") or [] if str(item).strip()]
    if not optimal_steps:
        optimal_steps = [
            "先识别题目要求的概念或数量关系。",
            "按关系写出关键步骤并完成计算。",
            "用代回、估算或反例检查结论。",
        ]
    is_correct = answer_class in {"correct", "readable_photo", "clarification_clear"}
    is_unclear = answer_class in {
        "unclear_photo",
        "ocr_hallucination",
        "text_photo_conflict",
        "clarify_cannot_provide",
    }
    if is_correct:
        statuses = {
            "final_answer": "matched",
            "model_or_relation": "matched",
            "steps": "matched",
            "symbols_units": "matched",
            "check_or_explanation": "matched",
        }
    elif answer_class == "partial":
        statuses = {
            "final_answer": "incorrect",
            "model_or_relation": "matched",
            "steps": "matched",
            "symbols_units": "incorrect",
            "check_or_explanation": "missing",
        }
    elif answer_class == "answer_only":
        statuses = {
            "final_answer": "matched",
            "model_or_relation": "missing",
            "steps": "missing",
            "symbols_units": "matched",
            "check_or_explanation": "missing",
        }
    elif answer_class == "right_answer_wrong_reason":
        statuses = {
            "final_answer": "matched",
            "model_or_relation": "incorrect",
            "steps": "incorrect",
            "symbols_units": "matched",
            "check_or_explanation": "missing",
        }
    elif is_unclear:
        statuses = {dimension: "unclear" for dimension in db.REQUIRED_ANALYSIS_DIMENSIONS}
    elif answer_class == "stuck":
        statuses = {dimension: "missing" for dimension in db.REQUIRED_ANALYSIS_DIMENSIONS}
    else:
        statuses = {dimension: "incorrect" for dimension in db.REQUIRED_ANALYSIS_DIMENSIONS}
    if answer_class == "answer_only":
        summary = "孩子只写出了最终答案，没有给出可复盘的关系、步骤或检验。"
        gap = "最终答案出现了，但缺少关系、关键步骤和检验，不能据此判断已经理解。"
    elif answer_class == "right_answer_wrong_reason":
        summary = "孩子的最终答案与参考一致，但给出的理由不能推出这个答案。"
        gap = "答案对，但理由错误；错误关系不能作为掌握证据。"
    elif answer_class == "partial":
        summary = "孩子写对了核心关系的一部分，但最终计算或表达没有完成。"
        gap = "核心关系部分成立，最后结果、符号或检验仍不稳定。"
    elif answer_class in {"wrong", "stuck"}:
        summary = "孩子当前没有建立可用的关系和步骤，需要沿前置知识确认断点。"
        gap = "关系、步骤和最终答案都不能成立，需要先确认前置规则。"
    elif is_unclear:
        summary = {
            "unclear_photo": "照片中的步骤和答案无法可靠辨认。",
            "ocr_hallucination": "OCR 文本缺少图像支持，不能作为孩子答案。",
            "text_photo_conflict": "文字答案与照片内容冲突，当前不能安全判断。",
            "clarify_cannot_provide": "孩子明确表示现在无法补充更清楚的证据。",
        }[answer_class]
        gap = summary
    elif is_correct:
        summary = "孩子写出了答案、关键关系、步骤和检验。"
        gap = ""
    else:
        summary = "当前答案证据需要进一步确认。"
        gap = "当前过程证据不足。"
    details = {
        "final_answer": "核对最终答案与题意。",
        "model_or_relation": gap or "关键关系成立。",
        "steps": gap or "关键步骤完整。",
        "symbols_units": gap or "符号和单位表达清楚。",
        "check_or_explanation": gap or "写出了检验或解释。",
    }
    return {
        "optimal_answer": optimal,
        "optimal_solution_steps": optimal_steps[:8],
        "child_answer_summary": summary,
        "comparison": [
            {"dimension": dimension, "status": statuses[dimension], "detail": details[dimension]}
            for dimension in ("final_answer", "model_or_relation", "steps", "symbols_units", "check_or_explanation")
        ],
        "alternative_solutions": ["允许与参考过程不同但逻辑等价的解法。"],
        "process_gap": gap,
        "teaching_explanation": gap or "这一步的关系、过程和检查都能相互支持。",
        "next_child_prompt": "下一步仍要写清关系、关键步骤和检查。",
    }


def _recorded_review(question: dict[str, Any], answer_class: str) -> dict[str, Any]:
    if answer_class in {"model_missing", "model_failing"}:
        raise ValueError(f"{answer_class} is a fault checkpoint and must not attach a recorded semantic output")
    is_unclear = answer_class in {
        "unclear_photo",
        "ocr_hallucination",
        "text_photo_conflict",
        "clarify_cannot_provide",
    }
    if answer_class in {"correct", "readable_photo", "clarification_clear"}:
        result, points, blocking, confidence = "correct", 2.0, False, 0.94
        tags: list[str] = []
    elif answer_class in {"partial", "answer_only", "right_answer_wrong_reason"}:
        result, points, blocking, confidence = "partial", 1.0, False, 0.86
        tags = ["calculation_or_symbol"] if answer_class == "partial" else ["process_habit"]
    elif is_unclear:
        result, points, blocking, confidence = "unclear", 0.0, False, 0.2
        tags = []
    else:
        result, points, blocking, confidence = "wrong", 0.0, True, 0.9
        tags = ["concept_confusion"] if answer_class == "wrong" else ["process_habit"]
    analysis = _answer_analysis(question, answer_class)
    derived_support = db.derive_answer_evaluation_support({
        "comparison": analysis["comparison"],
    })
    if is_unclear:
        support = {
            "usable_for_evaluation": False,
            "evidence_strength": "insufficient",
            "reasoning_soundness": "unclear",
            "dominant_gap_dimensions": sorted(db.REQUIRED_ANALYSIS_DIMENSIONS),
        }
        next_evidence_need = "clearer_solution_evidence"
    else:
        support = {
            "usable_for_evaluation": True,
            "evidence_strength": derived_support["evidence_strength"],
            "reasoning_soundness": derived_support["reasoning_soundness"],
            "dominant_gap_dimensions": derived_support["dominant_gap_dimensions"],
        }
        next_evidence_need = derived_support["next_evidence_need"]
        if answer_class == "answer_only":
            next_evidence_need = "clearer_solution_evidence"
        elif answer_class == "right_answer_wrong_reason":
            next_evidence_need = "targeted_reteach"
    return {
        "schema_version": "2026-07-11.answer-review.v5.schema.v2",
        "result": result,
        "score_points": points,
        "max_points": 2.0,
        "confidence": confidence,
        "error_tags": tags,
        "blocking_evidence": blocking,
        "answer_analysis": analysis,
        "evaluation_support": support,
        "next_evidence_need": next_evidence_need,
    }


def _attempt_answer_analysis(question: dict[str, Any], answer_class: str) -> dict[str, Any]:
    analysis = {"agent_key": "answer_analysis_agent", **_answer_analysis(question, answer_class)}
    weak = any(
        item.get("status") in db.WEAK_ANALYSIS_STATUSES
        for item in analysis.get("comparison") or []
        if isinstance(item, dict)
    )
    analysis["no_gap_observed"] = not weak and not bool(str(analysis.get("process_gap") or "").strip())
    analysis["evaluation_support"] = db.derive_answer_evaluation_support(analysis)
    return analysis


def _reject_unexpected_live_http(request: Any, *args: Any, **kwargs: Any) -> None:
    del args, kwargs
    url = getattr(request, "full_url", str(request))
    raise AssertionError(f"Recorded 10-lesson harness attempted unauthorized live HTTP: {url}")


@dataclass
class LessonState:
    lesson: dict[str, Any]
    model_mode: str
    interaction_count: int = 0
    attempt_turn: int = 0
    clarification_turn: int = 0
    photo_scenario_turn: int = 0
    failure_turn: int = 0
    pending_answer_class: str = "correct"
    route_fault: str = ""
    force_summary: bool = False
    restart_done: bool = False
    double_submit_done: bool = False
    blank_rejection_done: bool = False
    analyzing_reentry_count: int = 0
    expected_oracle: list[dict[str, Any]] = field(default_factory=list)
    state_trace: list[dict[str, Any]] = field(default_factory=list)
    request_trace: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    photo_fixture_trace: list[dict[str, Any]] = field(default_factory=list)
    fault_injection_trace: list[dict[str, Any]] = field(default_factory=list)
    worker_results: list[dict[str, Any]] = field(default_factory=list)
    harness_issues: list[str] = field(default_factory=list)

    @property
    def profile(self) -> str:
        return str(self.lesson["profile"])

    @property
    def target(self) -> int:
        return int(self.lesson["interaction_budget"]["target"])

    @property
    def minimum(self) -> int:
        return int(self.lesson["interaction_budget"]["minimum"])

    @property
    def maximum(self) -> int:
        return int(self.lesson["interaction_budget"]["maximum"])


class RecordedOracle:
    def __init__(self, state: LessonState) -> None:
        self.state = state

    def answer_route(self) -> model_router.ModelRoute:
        if self.state.route_fault == "missing":
            return _disabled_route("answer_analysis_agent", "answer_review")
        return _recorded_route("answer_analysis_agent", "answer_review")

    @staticmethod
    def evaluation_route() -> model_router.ModelRoute:
        return _recorded_route("evaluation_agent", "evaluation_update")

    @staticmethod
    def planner_route() -> model_router.ModelRoute:
        return _recorded_route("planner_agent", "planner_decision")

    @staticmethod
    def teaching_route() -> model_router.ModelRoute:
        return _recorded_route("teaching_agent", "teaching_generation")

    def photo_ocr(self, question: dict[str, Any], answer_raw: str, answer_photo_data_url: str) -> dict[str, Any]:
        del answer_raw, answer_photo_data_url
        answer_class = self.state.pending_answer_class
        expected = str(question.get("expected_answer") or "")
        route = {
            "provider": "recorded_model",
            "model": "recorded-v5-10-lesson-photo-ocr",
            "model_alias": "recorded-v5-10-lesson-photo-ocr",
        }
        if answer_class == "readable_photo":
            return {
                "route": route,
                "status": "usable",
                "confidence": 0.96,
                "transcript": f"照片中的答案为 {expected}，并写出了关键关系、步骤和检查。",
                "math_objects": [expected, "recorded_readable_solution_steps"],
                "notes": "Recorded readable-photo OCR oracle.",
            }
        if answer_class == "text_photo_conflict":
            return {
                "route": route,
                "status": "usable",
                "confidence": 0.93,
                "transcript": "照片中的最终答案为 999，与文字答案冲突。",
                "math_objects": ["999", "recorded_text_photo_conflict"],
                "notes": "Recorded clear conflict-photo OCR oracle.",
            }
        if answer_class == "ocr_hallucination":
            return {
                "route": route,
                "status": "unclear",
                "confidence": 0.12,
                "transcript": "OCR 曾猜测为 999，但图像不支持该转写。",
                "math_objects": [],
                "notes": "Recorded OCR-hallucination oracle: unsupported transcript must not be trusted.",
            }
        return {
            "route": route,
            "status": "unclear",
            "confidence": 0.15,
            "transcript": "",
            "math_objects": [],
            "notes": "Recorded unclear-photo OCR oracle.",
        }

    def evaluation_output(self, attempt: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        validation_ids = [str(item) for item in payload.get("source_evidence_validation_ids") or [] if item]
        answer_run_ids = [str(item) for item in payload.get("source_agent_run_ids") or [] if item]
        is_correct = attempt.get("result") == "correct"
        is_wrong = attempt.get("result") == "wrong"
        return {
            "schema_version": "2026-07-11.evaluation-decision.v5.schema.v2",
            "node_id": str(attempt.get("node_id") or ""),
            "source_evidence_validation_ids": validation_ids,
            "source_answer_analysis_agent_run_ids": answer_run_ids,
            "mastery_recommendation": "emerging" if is_correct else ("weak" if is_wrong else "no_update"),
            "dimension_scores": {
                "concept": 0.85 if is_correct else 0.35,
                "model_relation": 0.85 if is_correct else 0.3,
                "procedure": 0.82 if is_correct else 0.35,
                "calculation": 0.82 if is_correct else 0.4,
                "expression_notation": 0.8 if is_correct else 0.45,
                "transfer": 0.55 if is_correct else 0.2,
            },
            "planner_signal": {
                "next_evidence_goal": "near_transfer_retest" if is_correct else ("prerequisite_probe" if is_wrong else "same_structure_retest"),
                "needs_teaching_before_next": not is_correct,
                "needs_prerequisite_probe": is_wrong,
                "target_gap_dimensions": list((attempt.get("answer_analysis") or {}).get("evaluation_support", {}).get("dominant_gap_dimensions") or [])[:6],
            },
            "confidence": 0.91,
            "reason": f"Explicit recorded evaluation oracle for {attempt.get('result')} evidence.",
        }

    def planner_output(self, conn: sqlite3.Connection, attempt: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        packet = payload.get("candidate_packet") if isinstance(payload.get("candidate_packet"), dict) else {}
        candidates = list(packet.get("candidates") or [])
        step = conn.execute(
            "select flow_id, step_type from flow_steps where id = ?",
            (attempt.get("flow_step_id"),),
        ).fetchone()
        step_type = str(step["step_type"] if step else "")
        attempt_count = 0
        if step:
            attempt_count = int(conn.execute(
                "select count(*) from attempts where flow_step_id in (select id from flow_steps where flow_id = ?)",
                (step["flow_id"],),
            ).fetchone()[0])
        answer_class = self.state.pending_answer_class
        if self.state.force_summary and attempt_count >= self.state.minimum:
            action = "summary"
        elif self.state.profile == "all_correct":
            action = "near_transfer_retest"
        elif self.state.profile == "all_wrong":
            action = "prerequisite_probe"
        elif self.state.profile == "all_partial":
            action = "micro_teach" if self.state.attempt_turn % 3 == 0 else "same_structure_retest"
        elif self.state.profile == "mixed":
            if attempt.get("result") == "correct":
                action = "near_transfer_retest"
            elif attempt.get("result") == "wrong" and attempt.get("blocking_evidence"):
                action = "prerequisite_probe"
            else:
                action = "same_structure_retest"
        elif self.state.profile == "answer_only_stuck":
            action = "micro_teach" if answer_class == "stuck" else "same_structure_retest"
        elif self.state.profile in {"readable_photo", "model_recovery"}:
            action = "near_transfer_retest"
        elif self.state.profile in {"unclear_photo", "photo_conflict_hallucination"}:
            action = "near_transfer_retest" if step_type == "clarify_evidence" else "clarify_evidence"
        elif self.state.profile == "restart_double_submit":
            action = "prerequisite_probe" if attempt.get("result") == "wrong" else "near_transfer_retest"
        else:
            action = "summary"
        candidate_actions = {"same_structure_retest", "near_transfer_retest", "prerequisite_probe", "stretch"}
        source_node_id = str(attempt.get("node_id") or "")
        direct_prerequisites = set(load_graph_prerequisites().get(source_node_id, []))
        if action == "prerequisite_probe":
            selected = next(
                (
                    item for item in candidates
                    if str(item.get("node_id") or "") != source_node_id
                    and str(item.get("node_id") or "") in direct_prerequisites
                ),
                {},
            )
            if attempt.get("result") != "wrong" or not attempt.get("blocking_evidence") or not selected:
                action = "same_structure_retest"
                selected = candidates[0] if candidates else {}
        else:
            selected = candidates[0] if candidates and action in candidate_actions else {}
        if action in candidate_actions and not selected:
            action = "micro_teach"
        target_node_id = str(selected.get("node_id") or attempt.get("node_id") or "")
        return {
            "schema_version": "2026-07-11.planner-next-step.v5.schema.v2",
            "action": action,
            "target_node_id": target_node_id,
            "selected_candidate_id": str(selected.get("question_id") or ""),
            "candidate_packet_id": str(packet.get("packet_id") or ""),
            "branch_policy": {
                "uses_prerequisite_first": action == "prerequisite_probe",
                "requires_teaching_generation": action in {"micro_teach", "worked_example"},
            },
            "confidence": 0.91,
            "reason": f"Explicit recorded planner oracle selected one adaptive action: {action}.",
        }

    @staticmethod
    def teaching_output(attempt: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        analysis = attempt.get("answer_analysis") or {}
        explanation = str(
            analysis.get("teaching_explanation")
            or analysis.get("process_gap")
            or "先写清关键关系，再完成步骤和检查。"
        )
        action = str(payload.get("action") or "")
        step_type = "worked_example" if action == "worked_example" or payload.get("new_knowledge_request") else "teaching_repair"
        question_package = payload.get("question_package") if isinstance(payload.get("question_package"), dict) else {}
        return {
            "schema_version": "2026-07-12.teaching-step.v5.schema.v3",
            "target_node_id": str(payload.get("target_node_id") or attempt.get("node_id") or ""),
            "teaching_step_type": step_type,
            "child_title": "先修这一处",
            "teaching_sections": {
                "essence": {
                    "title": "本质",
                    "body": explanation,
                },
                "core_model": {
                    "title": "核心关系",
                    "body": "先找题目中的关系，再让每一步变形都保持这个关系成立。",
                },
                "worked_example": {
                    "title": "例题",
                    "problem": str(question_package.get("prompt") or "先写出题目中的核心关系。"),
                    "steps": [
                        "标出已知量、未知量和题目关系。",
                        "按同一个数学规则完成关键变形。",
                        "算完后代回原题或用反例检查。",
                    ],
                    "check": "确认关系、步骤和最终答案能够互相支持。",
                },
                "why_it_works": {
                    "title": "为什么成立",
                    "body": "每一步都保持原来的数学关系，所以得到的结论仍能回到原题验证。",
                },
                "next_micro_check": {
                    "title": "小检查",
                    "prompt": "请先说出下一题最关键的关系，再写第一步。",
                },
            },
            "next_child_action": "看完后继续做一题小检查；仍然卡住也可以直接说明。",
            "allowed_response_modes": ["continue", "stuck"],
            "confidence": 0.9,
            "source_reason": "explicit_recorded_teaching_oracle",
        }


def _fixed_date_class(local_date: str) -> type[RealDate]:
    fixed = RealDate.fromisoformat(local_date)

    class FixedDate(RealDate):
        @classmethod
        def today(cls) -> RealDate:
            return fixed

    return FixedDate


def _json_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if key in JSON_COLUMNS and isinstance(value, str):
            try:
                result[f"{key[:-5]}_value"] = json.loads(value)
            except json.JSONDecodeError:
                result[f"{key[:-5]}_value"] = None
    return result


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [_json_row(row) for row in conn.execute(query, params).fetchall()]


def _seed_target_evidence(conn: sqlite3.Connection, target_node_id: str) -> str:
    question = db.find_question_for_node(conn, target_node_id)
    seed_session = db.create_session(conn, f"v5 harness target seed {target_node_id}", mode="harness_seed", commit=False)
    analysis = _attempt_answer_analysis(question, "wrong")
    attempt_id = db.record_attempt(
        conn,
        session_id=seed_session,
        question_id=question["id"],
        node_id=target_node_id,
        result="wrong",
        score_points=0,
        max_points=2,
        error_tags=["concept_confusion"],
        answer_raw="Recorded harness seed: current target needs review.",
        parent_note="Temporary harness-only target ordering evidence.",
        answer_analysis=analysis,
        review_meta={"status": "graded", "provider": "recorded_model", "confidence": 0.99},
        explanation_score=0,
        blocking_evidence=True,
        commit=False,
    )
    graph_version = graph_runtime.GraphRuntimeService(conn, project_root=PROJECT_ROOT).current_graph_version()
    conn.execute(
        """
        insert or replace into learner_node_status(
          node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
          status_reason, graph_version, question_bank_version, mastery_decision_id,
          source_attempt_ids_json, source_evidence_validation_ids_json,
          updated_by_agent_run_id, status_revision, updated_at
        ) values (?, 'D', 0, 0, ?, ?, ?, ?, null, ?, '[]', null, 1, ?)
        """,
        (
            target_node_id,
            db.json_dump([attempt_id]),
            "Temporary v5 browser harness target ordering evidence.",
            graph_version,
            question_bank.QUESTION_BANK_VERSION,
            db.json_dump([attempt_id]),
            db.now_iso(),
        ),
    )
    conn.commit()
    return attempt_id


class LessonEnvironment:
    def __init__(self, state: LessonState, lesson_output: Path, contract: dict[str, Any]) -> None:
        self.state = state
        self.lesson_output = lesson_output
        self.contract = contract
        self.temp = TemporaryDirectory(prefix=f"v5-lesson-{state.lesson['id']}-")
        self.temp_root = Path(self.temp.name)
        self.db_path = self.temp_root / "lesson.sqlite"
        self.upload_root = self.temp_root / "answer-uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.stack = ExitStack()
        self.httpd = None
        self.base_url = ""
        self.oracle = RecordedOracle(state)
        self.live_fault_spec = live_fault_injection_spec_for_lesson(contract, state.lesson, state.model_mode)

    def __enter__(self) -> "LessonEnvironment":
        with db.connect(self.db_path) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            _seed_target_evidence(conn, str(self.state.lesson["target_node_id"]))
        self.stack.enter_context(patch.dict(os.environ, {
            "V3_DAILY_RUNTIME_ENABLED": "1",
            "V5_DAILY_FLOW_WORKER_MAX_JOBS": "20",
        }, clear=False))
        self.stack.enter_context(patch.object(daily_runtime, "date", _fixed_date_class(str(self.state.lesson["local_date"]))))
        self.stack.enter_context(patch.object(daily_runtime, "ANSWER_UPLOAD_RELATIVE_PREFIX", str(self.upload_root)))
        if self.state.model_mode == "recorded_model":
            self.stack.enter_context(patch.object(server.LearningHandler, "_start_v5_flow_processing", return_value=None))
            self.stack.enter_context(patch.object(auto_review, "_review_answer_photo", side_effect=self.oracle.photo_ocr))
            self.stack.enter_context(
                patch.object(model_router.urllib.request, "urlopen", side_effect=_reject_unexpected_live_http)
            )
            self.stack.enter_context(patch.object(model_router, "answer_analysis_route", side_effect=self.oracle.answer_route))
            self.stack.enter_context(patch.object(model_router, "evaluation_route", side_effect=self.oracle.evaluation_route))
            self.stack.enter_context(patch.object(model_router, "planner_route", side_effect=self.oracle.planner_route))
            self.stack.enter_context(patch.object(model_router, "teaching_route", side_effect=self.oracle.teaching_route))
        elif self.live_fault_spec is not None:
            # L09 alone uses a manual worker so each fault is injected only after
            # the browser submission has durably saved its attempt and job.
            self.stack.enter_context(patch.object(server.LearningHandler, "_start_v5_flow_processing", return_value=None))
        self.start_server()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop_server()
        self.stack.close()
        self.temp.cleanup()

    def start_server(self) -> str:
        self.httpd, self.base_url = server.start_test_server(self.db_path, upload_root=self.upload_root)
        return self.base_url

    def stop_server(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def restart_server(self) -> str:
        self.stop_server()
        return self.start_server()

    def connect(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    @property
    def live_fault_injection_enabled(self) -> bool:
        return self.live_fault_spec is not None

    def inject_live_fault_for_latest_attempt(self, answer_class: str) -> dict[str, Any]:
        if not self.live_fault_spec:
            raise RuntimeError("live fault injection is not enabled for this lesson")
        ordinal = len(self.state.fault_injection_trace) + 1
        stages = list(self.live_fault_spec.get("stages") or [])
        if ordinal > len(stages):
            raise RuntimeError("live fault injection budget is exhausted")
        stage = stages[ordinal - 1]
        if str(stage.get("answer_class") or "") != answer_class:
            raise RuntimeError(
                f"live fault stage {ordinal} expects {stage.get('answer_class')!r}, got {answer_class!r}"
            )
        attempt = self.latest_attempt()
        attempt_id = str(attempt.get("id") or "")
        flow_id = self.flow_id()
        with self.connect() as conn:
            row = conn.execute(
                """
                select * from background_jobs
                where flow_id = ? and attempt_id = ? and job_type = 'answer_analysis'
                  and status in ('queued','retry')
                order by created_at desc, id desc limit 1
                """,
                (flow_id, attempt_id),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"no saved answer_analysis job exists for live fault attempt {attempt_id}")
            job = dict(row)
            marker = {
                "fault_injected": True,
                "fault_type": str(stage.get("fault_type") or ""),
                "ordinal": ordinal,
                "lesson_id": str(self.state.lesson.get("id") or ""),
                "attempt_id": attempt_id,
                "workflow_evidence_only": True,
                "semantic_evidence_eligible": False,
                "injected_after_durable_save": True,
                "injected_at": db.now_iso(),
            }
            payload = db.json_load(job.get("payload_json"), {})
            route_meta = db.json_load(job.get("route_meta_json"), {})
            payload["fault_injected"] = marker
            route_meta["fault_injected"] = marker
            conn.execute(
                "update background_jobs set payload_json = ?, route_meta_json = ?, updated_at = ? where id = ?",
                (db.json_dump(payload), db.json_dump(route_meta), db.now_iso(), job["id"]),
            )
            conn.commit()
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            fault_type = marker["fault_type"]
            if fault_type == "not_configured":
                with patch.object(
                    model_router,
                    "answer_analysis_route",
                    return_value=_disabled_route("answer_analysis_agent", "answer_review"),
                ):
                    result = runtime.process_next_background_job(
                        worker_id=f"v5-live-fault-{self.state.lesson['id']}-{ordinal}",
                        flow_id=flow_id,
                    )
            elif fault_type == "controlled_retryable_failure":
                def _raise_controlled_failure(*args: Any, **kwargs: Any) -> Any:
                    del args, kwargs
                    raise model_router.ModelCallError(
                        "HTTP 503 fault_injected controlled retryable answer-analysis failure"
                    )

                with patch.object(model_router, "call_structured_json", side_effect=_raise_controlled_failure):
                    result = runtime.process_next_background_job(
                        worker_id=f"v5-live-fault-{self.state.lesson['id']}-{ordinal}",
                        flow_id=flow_id,
                    )
            else:
                raise RuntimeError(f"unsupported live fault type {fault_type!r}")
            after = conn.execute("select * from background_jobs where id = ?", (job["id"],)).fetchone()
            after_row = dict(after) if after else {}
        observed_status = str(result.get("job_status") or result.get("status") or after_row.get("status") or "")
        event = {
            "ordinal": ordinal,
            "fault_type": str(stage.get("fault_type") or ""),
            "answer_class": answer_class,
            "attempt_id": attempt_id,
            "job_id": str(job.get("id") or ""),
            "saved_before_injection": bool(attempt_id and job.get("id")),
            "fault_injected": True,
            "workflow_evidence_only": True,
            "semantic_evidence_eligible": False,
            "observed_job_status": observed_status,
            "persisted_job_status": str(after_row.get("status") or ""),
            "provider_mode_after_fault": str(after_row.get("provider_mode") or ""),
            "run_count_after_fault": int(after_row.get("run_count") or 0),
            "retry_after": str(after_row.get("retry_after") or ""),
            "worker_result": result,
        }
        self.state.fault_injection_trace.append(event)
        self.state.worker_results.append({"fault_injected": True, **result})
        return event

    def drain_live_manually(self) -> list[dict[str, Any]]:
        if not self.live_fault_injection_enabled:
            return []
        flow_id = self.flow_id()
        results: list[dict[str, Any]] = []
        for execution_index in range(1, 25):
            with self.connect() as conn:
                row = conn.execute(
                    """
                    select * from background_jobs
                    where flow_id = ? and status in ('queued','retry')
                    order by created_at, id limit 1
                    """,
                    (flow_id,),
                ).fetchone()
                if row is None:
                    break
                job = dict(row)
                claim_now = "2099-12-31T23:59:59+00:00" if job.get("status") == "retry" else None
                result = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT).process_next_background_job(
                    worker_id=f"v5-live-recovery-{self.state.lesson['id']}-{execution_index}",
                    now=claim_now,
                    flow_id=flow_id,
                )
            results.append(result)
            if result.get("job_status") in {"blocked", "waiting", "dead_letter"}:
                break
        else:
            self.state.harness_issues.append("live L09 durable job DAG did not stabilize within 24 executions")
        self.state.worker_results.extend(results)
        return results

    def flow_id(self) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "select id from daily_flows where local_date = ? order by created_at desc, id desc limit 1",
                (self.state.lesson["local_date"],),
            ).fetchone()
            return str(row["id"] if row else "")

    def visible_step(self) -> dict[str, Any]:
        flow_id = self.flow_id()
        with self.connect() as conn:
            row = conn.execute(
                """
                select s.*
                from flow_steps s
                join daily_flows f on f.id = s.flow_id
                where s.flow_id = ? and f.current_step_id = s.id
                limit 1
                """,
                (flow_id,),
            ).fetchone()
            return _json_row(row) if row else {}

    def current_question(self) -> dict[str, Any]:
        step = self.visible_step()
        if not step.get("question_id"):
            return {}
        with self.connect() as conn:
            return db.get_question(conn, str(step["question_id"]))

    def latest_attempt(self) -> dict[str, Any]:
        flow_id = self.flow_id()
        with self.connect() as conn:
            row = conn.execute(
                """
                select a.*
                from attempts a
                join flow_steps s on s.id = a.flow_step_id
                where s.flow_id = ?
                order by a.created_at desc, a.id desc
                limit 1
                """,
                (flow_id,),
            ).fetchone()
            return db.attempt_row_to_dict(row) if row else {}

    def flow_snapshot(self) -> dict[str, Any]:
        flow_id = self.flow_id()
        if not flow_id:
            return {"flow_id": "", "attempt_count": 0, "job_statuses": {}, "mastery_count": 0, "decision_count": 0}
        with self.connect() as conn:
            attempt = conn.execute(
                """
                select a.id, a.result, a.grading_status, a.analysis_status
                from attempts a join flow_steps s on s.id = a.flow_step_id
                where s.flow_id = ? order by a.created_at desc, a.id desc limit 1
                """,
                (flow_id,),
            ).fetchone()
            job_rows = conn.execute(
                "select status, count(*) as n from background_jobs where flow_id = ? group by status",
                (flow_id,),
            ).fetchall()
            latest_attempt_id = str(attempt["id"] if attempt else "")
            mastery_count = conn.execute(
                "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
                (f"%{latest_attempt_id}%",),
            ).fetchone()[0] if latest_attempt_id else 0
            return {
                "flow_id": flow_id,
                "attempt_count": conn.execute(
                    "select count(*) from attempts where flow_step_id in (select id from flow_steps where flow_id = ?)",
                    (flow_id,),
                ).fetchone()[0],
                "latest_attempt": dict(attempt) if attempt else {},
                "job_statuses": {row["status"]: row["n"] for row in job_rows},
                "mastery_count_for_latest_attempt": mastery_count,
                "decision_count": conn.execute("select count(*) from next_step_decisions where flow_id = ?", (flow_id,)).fetchone()[0],
                "summary_count": conn.execute("select count(*) from daily_summaries where flow_id = ?", (flow_id,)).fetchone()[0],
            }

    def register_oracle(
        self,
        answer_class: str,
        interaction_index: int,
        *,
        photo_fixture: dict[str, Any] | None = None,
    ) -> None:
        attempt = self.latest_attempt()
        step = self.visible_step()
        if not attempt:
            self.state.harness_issues.append(f"interaction {interaction_index}: submission did not create an attempt")
            return
        existing = next((item for item in self.state.expected_oracle if item.get("attempt_id") == attempt["id"]), None)
        entry = {
            "attempt_id": attempt["id"],
            "interaction_index": interaction_index,
            "answer_class": answer_class,
            "step_type": step.get("step_type") or "",
            "expected_result": {
                "correct": ["correct"],
                "readable_photo": ["correct"],
                "clarification_clear": ["correct"],
                "partial": ["partial"],
                "answer_only": ["partial", "wrong"],
                "right_answer_wrong_reason": ["partial", "wrong"],
                "wrong": ["wrong"],
                "stuck": ["wrong"],
                "unclear_photo": ["submitted"],
                "ocr_hallucination": ["submitted"],
                "text_photo_conflict": ["submitted"],
                "model_missing": ["submitted", "correct"],
                "model_failing": ["submitted", "correct"],
                "clarify_cannot_provide": ["submitted"],
            }.get(answer_class, ["submitted"]),
            "must_not_claim_full_mastery": answer_class not in {"correct", "readable_photo", "clarification_clear"},
            "requires_recovery_checkpoint": answer_class in {"model_missing", "model_failing"},
            "semantic_evidence_eligible": answer_class not in {"model_missing", "model_failing"},
            "photo_fixture": photo_fixture or {},
        }
        if existing is None:
            self.state.expected_oracle.append(entry)

    def _attach_fixture(self, conn: sqlite3.Connection, job: dict[str, Any], output: dict[str, Any] | None, fixture_id: str) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        route_meta = payload.get("route_meta") if isinstance(payload.get("route_meta"), dict) else {}
        payload["provider_mode"] = "recorded_model"
        payload["recorded_fixture_id"] = fixture_id
        payload["route_meta"] = {**route_meta, "provider_mode": "recorded_model", "recorded_fixture_id": fixture_id}
        if output is not None:
            payload["recorded_agent_output"] = output
        conn.execute(
            "update background_jobs set payload_json = ?, provider_mode = ?, route_meta_json = ? where id = ?",
            (db.json_dump(payload), "recorded_model", db.json_dump(payload["route_meta"]), job["id"]),
        )
        conn.commit()
        row = conn.execute("select * from background_jobs where id = ?", (job["id"],)).fetchone()
        return dict(row)

    def drain_recorded(self) -> list[dict[str, Any]]:
        flow_id = self.flow_id()
        results: list[dict[str, Any]] = []
        for execution_index in range(1, 17):
            with self.connect() as conn:
                row = conn.execute(
                    """
                    select * from background_jobs
                    where flow_id = ? and status in ('queued','retry')
                    order by created_at, id limit 1
                    """,
                    (flow_id,),
                ).fetchone()
                if row is None:
                    break
                job = dict(row)
                payload = db.json_load(job.get("payload_json"), {})
                attempt = db.get_attempt(conn, str(job.get("attempt_id") or payload.get("attempt_id") or ""))
                if job["job_type"] == "answer_analysis":
                    recorded_review = None
                    if self.state.pending_answer_class not in {"model_missing", "model_failing"}:
                        recorded_review = _recorded_review(attempt.get("question") or db.get_question(conn, attempt["question_id"]), self.state.pending_answer_class)
                    job = self._attach_fixture(
                        conn,
                        job,
                        recorded_review,
                        f"recorded-answer-{self.state.lesson['id']}-{attempt['id']}-{self.state.pending_answer_class}",
                    )
                elif job["job_type"] == "evaluation_update":
                    job = self._attach_fixture(
                        conn,
                        job,
                        self.oracle.evaluation_output(attempt, payload),
                        f"recorded-evaluation-{self.state.lesson['id']}-{attempt['id']}",
                    )
                elif job["job_type"] == "planner_decision":
                    job = self._attach_fixture(
                        conn,
                        job,
                        self.oracle.planner_output(conn, attempt, payload),
                        f"recorded-planner-{self.state.lesson['id']}-{attempt['id']}",
                    )
                elif job["job_type"] == "teaching_generation":
                    job = self._attach_fixture(
                        conn,
                        job,
                        self.oracle.teaching_output(attempt, payload),
                        f"recorded-teaching-{self.state.lesson['id']}-{attempt['id']}",
                    )
                result = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT).process_next_background_job(
                    worker_id=f"v5-harness-{self.state.lesson['id']}-{execution_index}",
                    now="2099-12-31T23:59:59+00:00" if job.get("status") == "retry" else None,
                    flow_id=flow_id,
                )
                results.append(result)
                if result.get("job_status") in {"blocked", "waiting", "dead_letter"}:
                    break
        else:
            self.state.harness_issues.append("durable job DAG did not stabilize within 16 executions")
        self.state.worker_results.extend(results)
        return results

    def collect_evidence(self) -> dict[str, Any]:
        flow_id = self.flow_id()
        with self.connect() as conn:
            flow_rows = _rows(conn, "select * from daily_flows where id = ?", (flow_id,))
            steps = _rows(conn, "select * from flow_steps where flow_id = ? order by position, created_at, id", (flow_id,))
            attempts = _rows(
                conn,
                "select * from attempts where flow_step_id in (select id from flow_steps where flow_id = ?) order by created_at, id",
                (flow_id,),
            )
            supporting_attempts = _rows(
                conn,
                """
                select * from attempts
                where id not in (
                  select a.id from attempts a
                  join flow_steps s on s.id = a.flow_step_id
                  where s.flow_id = ?
                )
                order by created_at, id
                """,
                (flow_id,),
            )
            attempt_ids = [item["id"] for item in attempts]
            placeholders = ",".join("?" for _ in attempt_ids) or "''"
            attachments = _rows(
                conn,
                f"select * from attempt_attachments where attempt_id in ({placeholders}) order by created_at, id",
                tuple(attempt_ids),
            ) if attempt_ids else []
            jobs = _rows(conn, "select * from background_jobs where flow_id = ? order by created_at, id", (flow_id,))
            legacy_session_id = str(flow_rows[0].get("legacy_session_id") or "") if flow_rows else ""
            runs = _rows(conn, "select * from agent_runs where session_id = ? order by created_at, id", (legacy_session_id,))
            validations = _rows(
                conn,
                f"select * from evidence_validations where attempt_id in ({placeholders}) order by created_at, id",
                tuple(attempt_ids),
            ) if attempt_ids else []
            mastery = _rows(conn, "select * from mastery_decisions where session_id = ? order by created_at, id", (legacy_session_id,))
            decisions = _rows(conn, "select * from next_step_decisions where flow_id = ? order by created_at, id", (flow_id,))
            summaries = _rows(conn, "select * from daily_summaries where flow_id = ? order by created_at, id", (flow_id,))
            schema_validations = _agent_schema_validations(conn, runs, attempts)
            integrity = db.lineage_integrity_audit(conn)
            daily_report = reports.generate_daily_report(conn, report_date=str(self.state.lesson["local_date"]))
            daily_markdown = reports.render_markdown(daily_report)
        evidence = {
            "model_mode": self.state.model_mode,
            "daily_flows": flow_rows,
            "flow_steps": steps,
            "attempts": attempts,
            "supporting_attempts": supporting_attempts,
            "attempt_attachments": attachments,
            "background_jobs": jobs,
            "agent_runs": runs,
            "agent_output_schema_validations": schema_validations,
            "evidence_validations": validations,
            "mastery_decisions": mastery,
            "next_step_decisions": decisions,
            "daily_summaries": summaries,
            "database_lineage_integrity": integrity,
            "daily_report": daily_report,
            "daily_report_markdown": daily_markdown,
        }
        return evidence


class BrowserDriver:
    def __init__(self, page: Any, state: LessonState, env: LessonEnvironment, lesson_output: Path, timeout_seconds: float) -> None:
        self.page = page
        self.state = state
        self.env = env
        self.lesson_output = lesson_output
        self.timeout_ms = int(timeout_seconds * 1000)
        self.screenshot_dir = lesson_output / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.page.on("request", self._record_request)
        self.page.add_init_script(
            """
            (() => {
              const originalFetch = window.fetch.bind(window);
              window.__v5HarnessPayloads = [];
              window.fetch = async (...args) => {
                const response = await originalFetch(...args);
                try {
                  const clone = response.clone();
                  const payload = await clone.json();
                  if (payload && String(payload.schema_version || '').startsWith('3.')) {
                    window.__v5HarnessPayloads.push(payload);
                  }
                } catch (_) {}
                return response;
              };
            })();
            """
        )
        for route_path in (
            "/api/daily-flow/review/start",
            "/api/daily-flow/new-knowledge/start",
            "/api/daily-flow/finish",
        ):
            self.page.route(f"**{route_path}", self._rewrite_day_key)

    def _record_request(self, request: Any) -> None:
        parsed = urlparse(request.url)
        if not parsed.path.startswith("/api/"):
            return
        post_data = request.post_data or ""
        try:
            payload = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
            payload = {"raw": post_data[:500]}
        self.state.request_trace.append({
            "method": request.method,
            "path": parsed.path,
            "payload": payload,
        })

    def _rewrite_day_key(self, route: Any) -> None:
        raw = route.request.post_data or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        payload["client_day_key"] = self.state.lesson["local_date"]
        headers = dict(route.request.headers)
        headers["content-type"] = "application/json"
        route.continue_(post_data=json.dumps(payload, ensure_ascii=False), headers=headers)

    def goto(self, base_url: str) -> dict[str, Any]:
        self.page.goto(base_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.page.wait_for_function(
            "() => Array.isArray(window.__v5HarnessPayloads) && window.__v5HarnessPayloads.length > 0",
            timeout=self.timeout_ms,
        )
        return self.wait_for_states({"start_resume", "current_step", "analyzing_pending", "blocked", "summary"})

    def payload_count(self) -> int:
        return int(self.page.evaluate("() => (window.__v5HarnessPayloads || []).length"))

    def wait_for_states(self, accepted: set[str], *, after_payload_count: int | None = None) -> dict[str, Any]:
        threshold = -1 if after_payload_count is None else int(after_payload_count)
        self.page.wait_for_function(
            """
            ({accepted, threshold}) => {
              const payloads = window.__v5HarnessPayloads || [];
              if (payloads.length <= threshold) return false;
              const payload = payloads[payloads.length - 1] || {};
              const alias = {choose_review: 'start_resume', analyzing: 'analyzing_pending', teaching: 'feedback_teaching'};
              const canonical = alias[payload.child_state] || payload.child_state || '';
              return accepted.includes(canonical);
            }
            """,
            arg={"accepted": sorted(accepted), "threshold": threshold},
            timeout=self.timeout_ms,
        )
        return self.current_state()

    def current_state(self) -> dict[str, Any]:
        return self.page.evaluate(
            """
            () => {
              const payloads = window.__v5HarnessPayloads || [];
              const payload = payloads[payloads.length - 1] || {};
              const alias = {choose_review: 'start_resume', analyzing: 'analyzing_pending', teaching: 'feedback_teaching'};
              const canonical = alias[payload.child_state] || payload.child_state || '';
              const text = (selector) => (document.querySelector(selector)?.innerText || document.querySelector(selector)?.textContent || '').trim();
              return {
                canonical_state: canonical,
                api_child_state: payload.child_state || '',
                payload_count: payloads.length,
                heading: text('#childHeading'),
                task_type: text('#childTaskType'),
                prompt: text('#childTaskContent'),
                handoff_title: text('#childHandoffTitle'),
                handoff_text: text('#childHandoffText'),
                body_text: (document.body?.innerText || '').trim(),
                form_visible: Boolean(document.querySelector('#childAttemptForm')?.offsetParent),
                primary_visible: Boolean(document.querySelector('#startNextRoundBtn')?.offsetParent),
                secondary_visible: Boolean(document.querySelector('#v3SecondaryActionBtn')?.offsetParent),
                current_step: payload.current_step || null,
                summary: payload.summary || null,
              };
            }
            """
        )

    def capture(self, label: str) -> dict[str, Any]:
        browser_state = self.current_state()
        snapshot = self.env.flow_snapshot()
        leak_terms = [term for term in CHILD_FORBIDDEN_TEXT if term in browser_state.get("body_text", "").lower()]
        entry = {
            "sequence": len(self.state.state_trace) + 1,
            "interaction_count": self.state.interaction_count,
            "label": label,
            "browser": browser_state,
            "durable": snapshot,
            "forbidden_child_text_hits": leak_terms,
        }
        self.state.state_trace.append(entry)
        screenshot = self.screenshot_dir / f"{entry['sequence']:03d}-{_safe_slug(label)}-{browser_state.get('canonical_state') or 'unknown'}.png"
        self.page.screenshot(path=str(screenshot), full_page=True)
        relative = str(screenshot.relative_to(self.lesson_output))
        self.state.screenshots.append(relative)
        return entry

    def click_start(self) -> dict[str, Any]:
        before = self.payload_count()
        self.page.locator("#startNextRoundBtn").click()
        return self.wait_for_states({"current_step", "blocked", "summary"}, after_payload_count=before)

    def blank_submit_rejected(self) -> None:
        before_requests = len([item for item in self.state.request_trace if item["path"] == SUBMIT_ROUTE])
        self.page.locator("#childAnswerRaw").fill("")
        self.page.locator("#childSubmitBtn").click()
        self.page.wait_for_function(
            "() => (document.querySelector('#toast')?.textContent || '').includes('先写一点步骤')",
            timeout=self.timeout_ms,
        )
        after_requests = len([item for item in self.state.request_trace if item["path"] == SUBMIT_ROUTE])
        if after_requests != before_requests:
            self.state.harness_issues.append("blank child evidence unexpectedly reached the submit API")

    def submit(self, *, text: str, photo_path: Path | None, stuck: bool, double_submit: bool) -> dict[str, Any]:
        before = self.payload_count()
        if text:
            self.page.locator("#childAnswerRaw").fill(text)
        else:
            self.page.locator("#childAnswerRaw").fill("")
        if photo_path is not None:
            self.page.locator("#childAnswerPhoto").set_input_files(str(photo_path))
            self.page.wait_for_function(
                "() => Boolean(document.querySelector('#childPhotoPreview') && !document.querySelector('#childPhotoPreview').hidden)",
                timeout=self.timeout_ms,
            )
        if stuck:
            button = self.page.locator("[data-v3-stuck-prompt]").first
            if button.count() == 1:
                button.click()
        if double_submit:
            self.page.evaluate(
                """
                () => {
                  const form = document.querySelector('#childAttemptForm');
                  form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
                  form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
                }
                """
            )
        else:
            self.page.locator("#childSubmitBtn").click()
        return self.wait_for_states({"analyzing_pending", "blocked", "clarify_evidence", "summary"}, after_payload_count=before)

    def refresh_after_recorded_drain(self, *, suppress_blocked_recovery: bool = False) -> dict[str, Any]:
        state = self.current_state()
        if state["canonical_state"] != "analyzing_pending":
            return state
        original_route_fault = self.state.route_fault
        if suppress_blocked_recovery:
            self.state.route_fault = "missing"
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
            return self.wait_for_states(CONCLUSION_STATES | {"analyzing_pending"})
        finally:
            self.state.route_fault = original_route_fault

    def wait_for_child_conclusion(self) -> dict[str, Any]:
        return self.wait_for_states(CONCLUSION_STATES)

    def continue_teaching(self, *, still_stuck: bool) -> dict[str, Any]:
        before = self.payload_count()
        selector = "[data-v3-continue-stuck]" if still_stuck else "[data-v3-continue-step]"
        self.page.locator(selector).click()
        return self.wait_for_states(CONCLUSION_STATES, after_payload_count=before)

    def retry_blocked(self) -> dict[str, Any]:
        before = self.payload_count()
        self.page.locator("#startNextRoundBtn").click()
        return self.wait_for_states({"analyzing_pending", "blocked", "summary", "current_step"}, after_payload_count=before)

    def finish(self) -> dict[str, Any]:
        before = self.payload_count()
        self.page.locator("#v3SecondaryActionBtn").click()
        return self.wait_for_states({"summary"}, after_payload_count=before)


def _safe_slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")[:80] or "state"


def _photo_font(size: int) -> Any:
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrapped_photo_lines(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _write_photo(
    path: Path,
    *,
    answer_class: str,
    expected: str,
    solution_step: str,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw, ImageFilter

    expected = str(expected or "No final answer supplied")
    solution_step = str(solution_step or "Write the governing relation and compute one justified step.")
    photo_answer = "999" if answer_class == "text_photo_conflict" and expected.strip() != "999" else expected
    if answer_class == "text_photo_conflict" and expected.strip() == "999":
        photo_answer = "-999"
    source_lines = [
        "V5 CURRENT-STEP PHOTO EVIDENCE",
        f"PHOTO ANSWER: {photo_answer}",
        f"STEP: {solution_step}",
        "CHECK: Substitute the result or estimate it against the original prompt.",
    ]
    source_text = "\n".join(source_lines)
    image = Image.new("RGB", (960, 640), (250, 250, 246))
    draw = ImageDraw.Draw(image)
    header_font = _photo_font(31)
    body_font = _photo_font(25)
    draw.rectangle((38, 38, 922, 602), outline=(35, 35, 35), width=3)
    draw.text((70, 70), source_lines[0], font=header_font, fill=(15, 15, 15))
    draw.line((70, 125, 890, 125), fill=(45, 45, 45), width=3)
    y = 165
    for logical_line in source_lines[1:]:
        for wrapped in _wrapped_photo_lines(draw, logical_line, body_font, 800):
            draw.text((76, y), wrapped, font=body_font, fill=(20, 20, 20))
            y += 46
        y += 18
    source_image_sha256 = hashlib.sha256(image.tobytes()).hexdigest()
    blurred_from_source = answer_class in {"unclear_photo", "ocr_hallucination"}
    rendered = image.filter(ImageFilter.GaussianBlur(radius=11)) if blurred_from_source else image.copy()
    rendered_image_sha256 = hashlib.sha256(rendered.tobytes()).hexdigest()
    rendered.save(path, format="PNG")
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "answer_class": answer_class,
        "path": str(path),
        "expected_answer": expected,
        "photo_answer": photo_answer,
        "source_text": source_text,
        "source_content_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "source_image_sha256": source_image_sha256,
        "rendered_image_sha256": rendered_image_sha256,
        "file_sha256": file_sha256,
        "blurred_from_source": blurred_from_source,
        "conflicts_with_expected": photo_answer != expected,
        "width": rendered.width,
        "height": rendered.height,
        "byte_size": path.stat().st_size,
    }


def _answer_directive(state: LessonState, env: LessonEnvironment, canonical_state: str, photo_dir: Path) -> dict[str, Any]:
    profile = state.profile
    if canonical_state == "clarify_evidence":
        state.clarification_turn += 1
        if profile == "unclear_photo" and state.interaction_count >= state.target:
            return {"answer_class": "clarify_cannot_provide", "text": "", "photo": None, "stuck": True}
        answer_class = "clarification_clear"
    elif profile == "all_correct":
        answer_class = "correct"
    elif profile == "all_wrong":
        answer_class = "wrong"
    elif profile == "all_partial":
        answer_class = "partial"
    elif profile == "mixed":
        sequence = (
            "correct",
            "right_answer_wrong_reason",
            "wrong",
            "partial",
            "wrong",
            "correct",
            "wrong",
            "partial",
            "wrong",
            "correct",
        )
        answer_class = sequence[state.attempt_turn % len(sequence)]
    elif profile == "answer_only_stuck":
        answer_class = "answer_only" if state.attempt_turn % 2 == 0 else "stuck"
    elif profile == "readable_photo":
        answer_class = "readable_photo"
    elif profile == "unclear_photo":
        answer_class = "unclear_photo"
    elif profile == "photo_conflict_hallucination":
        answer_class = "text_photo_conflict" if state.photo_scenario_turn % 2 == 0 else "ocr_hallucination"
        state.photo_scenario_turn += 1
    elif profile == "model_recovery":
        if state.failure_turn == 0:
            answer_class = "model_missing"
            state.route_fault = "missing"
            state.failure_turn += 1
        elif state.failure_turn == 1:
            answer_class = "model_failing"
            state.route_fault = ""
            state.failure_turn += 1
        else:
            answer_class = "correct"
    elif profile == "restart_double_submit":
        answer_class = "wrong" if state.attempt_turn in {1, 2, 3} else "correct"
    else:
        answer_class = "correct"
    state.attempt_turn += 1
    question = env.current_question()
    expected = str(question.get("expected_answer") or "")
    solution_steps = [str(item) for item in question.get("solution_steps") or [] if str(item).strip()]
    if answer_class in {"correct", "clarification_clear"}:
        text = f"答案：{expected}。关系与步骤：{'；'.join(solution_steps[:2]) or '按题意建立关系并完成计算'}。最后代回或估算检查。"
    elif answer_class == "partial":
        text = f"我先写出关系：{solution_steps[0] if solution_steps else '按题意列关系'}，但最后算成了 999。"
    elif answer_class == "answer_only":
        text = expected
    elif answer_class == "right_answer_wrong_reason":
        text = f"答案是 {expected}，因为无论题目条件是什么都可以直接把两个数相加。"
    elif answer_class == "wrong":
        text = "我得到 999，但没有办法用题目关系检查。"
    elif answer_class == "stuck":
        text = ""
    elif answer_class == "model_missing":
        text = f"答案：{expected}。我写了关系、步骤和检查，等待系统恢复后继续批阅。"
    elif answer_class == "model_failing":
        text = f"答案：{expected}。这是一次失败恢复路径的已保存证据。"
    elif answer_class == "text_photo_conflict":
        text = f"文字答案写 {expected}，但照片故意写成另一个结果，必须先澄清。"
    elif answer_class == "clarify_cannot_provide":
        text = ""
    else:
        text = "关键过程见当前照片。"
    photo = None
    photo_fixture = None
    if answer_class in {"readable_photo", "unclear_photo", "text_photo_conflict", "ocr_hallucination"}:
        photo = photo_dir / f"{state.attempt_turn:02d}-{answer_class}.png"
        photo_fixture = _write_photo(
            photo,
            answer_class=answer_class,
            expected=expected,
            solution_step=solution_steps[0] if solution_steps else "Write the governing relation before calculating.",
        )
        photo_fixture["artifact_path"] = f"submitted-photos/{photo.name}"
        photo_fixture["typed_text"] = text
        photo_fixture["typed_expected_present"] = bool(expected and expected in text)
        state.photo_fixture_trace.append(photo_fixture)
    return {
        "answer_class": answer_class,
        "text": text,
        "photo": photo,
        "photo_fixture": photo_fixture,
        "stuck": answer_class in {"stuck", "clarify_cannot_provide"},
    }


def _agent_schema_validations(
    conn: sqlite3.Connection,
    runs: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attempts_by_id = {item["id"]: item for item in attempts}
    validations: list[dict[str, Any]] = []
    for run in runs:
        errors = list(run.get("validation_errors_value") or [])
        phase = str(run.get("phase") or "")
        applicable = run.get("status") == "accepted" and bool(run.get("model_provider"))
        valid = not errors
        if applicable:
            detail = "accepted recorded/live agent output has no validation errors"
        elif run.get("status") == "accepted":
            detail = "deterministic runtime output is governed by its deterministic contract and lineage checks"
        else:
            detail = "no accepted semantic output was emitted for this pending/error run"
        if applicable and phase == "answer_analysis":
            refs = run.get("input_refs_value") or {}
            attempt = attempts_by_id.get(str(refs.get("attempt_id") or ""), {})
            analysis = attempt.get("answer_analysis_value") or {}
            valid = valid and db.is_valid_answer_analysis(analysis)
            detail = "answer analysis passes the strict structured validator" if valid else "answer analysis is not strict-validator valid"
        elif applicable and phase in {"evaluation_update", "planner_decision", "teaching_generation"}:
            try:
                contract = internal_agents.load_v5_contract_for_agent(str(run.get("agent_key") or ""))
                semantic_agents._validate_output_against_contract(
                    contract,
                    run.get("output_value") or {},
                    phase=phase,
                )
            except Exception as exc:
                valid = False
                errors.append(str(exc))
                detail = "strict semantic output validation failed"
        validations.append({
            "agent_run_id": run.get("id"),
            "agent_key": run.get("agent_key"),
            "phase": phase,
            "provider": run.get("model_provider"),
            "response_schema_version": run.get("response_schema_version"),
            "applicable": applicable,
            "valid": bool(valid),
            "detail": detail,
            "errors": errors,
        })
    return validations


def _lineage_audit(evidence: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    jobs = evidence["background_jobs"]
    runs = evidence["agent_runs"]
    validations = evidence["evidence_validations"]
    mastery = evidence["mastery_decisions"]
    decisions = evidence["next_step_decisions"]
    attempts = evidence["attempts"]
    summaries = evidence["daily_summaries"]
    job_ids = {item["id"] for item in jobs}
    run_ids = {item["id"] for item in runs}
    validation_ids = {item["id"] for item in validations}
    mastery_ids = {item["id"] for item in mastery}
    decision_ids = {item["id"] for item in decisions}
    attempt_ids = {item["id"] for item in attempts}
    attempt_ids.update(item["id"] for item in evidence.get("supporting_attempts") or [])
    for job in jobs:
        refs = job.get("result_refs_value") or {}
        if job.get("status") == "succeeded" and not refs:
            issues.append(f"succeeded job {job['id']} has no result refs")
        for key, valid_ids in (
            ("answer_analysis_agent_run_id", run_ids),
            ("evaluation_agent_run_id", run_ids),
            ("planner_agent_run_id", run_ids),
            ("teaching_agent_run_id", run_ids),
            ("evidence_validation_id", validation_ids),
            ("mastery_decision_id", mastery_ids),
            ("next_step_decision_id", decision_ids),
        ):
            value = refs.get(key)
            if value and value not in valid_ids:
                issues.append(f"job {job['id']} references missing {key}={value}")
        payload = job.get("payload_value") or {}
        for source_job_id in payload.get("source_job_ids") or []:
            if source_job_id not in job_ids:
                issues.append(f"job {job['id']} has missing source job {source_job_id}")
    for item in validations:
        if item.get("attempt_id") not in attempt_ids:
            issues.append(f"validation {item['id']} references missing attempt")
        if item.get("answer_analysis_agent_run_id") and item.get("answer_analysis_agent_run_id") not in run_ids:
            issues.append(f"validation {item['id']} references missing answer-analysis run")
    for item in mastery:
        for attempt_id in item.get("source_attempt_ids_value") or []:
            if attempt_id not in attempt_ids:
                issues.append(f"mastery {item['id']} references missing attempt {attempt_id}")
        for validation_id in item.get("source_evidence_validation_ids_value") or []:
            if validation_id not in validation_ids:
                issues.append(f"mastery {item['id']} references missing validation {validation_id}")
        if item.get("evaluation_agent_run_id") and item.get("evaluation_agent_run_id") not in run_ids:
            issues.append(f"mastery {item['id']} references missing evaluation run")
    for item in decisions:
        for attempt_id in item.get("source_attempt_ids_value") or []:
            if attempt_id not in attempt_ids:
                issues.append(f"decision {item['id']} references missing attempt {attempt_id}")
        for validation_id in item.get("source_evidence_validation_ids_value") or []:
            if validation_id not in validation_ids:
                issues.append(f"decision {item['id']} references missing validation {validation_id}")
        for mastery_id in item.get("source_mastery_decision_ids_value") or []:
            if mastery_id not in mastery_ids:
                issues.append(f"decision {item['id']} references missing mastery {mastery_id}")
        if item.get("planner_agent_run_id") and item.get("planner_agent_run_id") not in run_ids:
            issues.append(f"decision {item['id']} references missing planner run")
    if summaries:
        operator = summaries[-1].get("operator_summary_value") or {}
        serialized = json.dumps(operator, ensure_ascii=False)
        for expected_key in (
            "answer_analysis_job_id",
            "answer_analysis_agent_run_id",
            "evaluation_job_id",
            "evaluation_agent_run_id",
            "planner_job_id",
            "planner_agent_run_id",
            "mastery_decision_id",
            "next_step_decision_id",
            "provider_mode",
        ):
            if expected_key not in serialized:
                issues.append(f"summary operator lineage is missing {expected_key}")
    report_flows = evidence["daily_report"].get("daily_flows") or []
    if not report_flows:
        issues.append("daily report did not expose the v5 flow")
    else:
        report_flow = report_flows[0]
        for field_name in ("attempt_evidence", "mastery_updates", "next_step_decisions", "phase_lineage", "operator_summary"):
            if field_name not in report_flow:
                issues.append(f"daily report v5 flow is missing {field_name}")
        phases = (report_flow.get("phase_lineage") or {}).get("phases") or {}
        if set(phases) != set(MODEL_PHASES):
            issues.append("daily report phase lineage does not expose all durable model stages")
    schema_failures = [item for item in evidence["agent_output_schema_validations"] if item["applicable"] and not item["valid"]]
    if schema_failures:
        issues.append(f"{len(schema_failures)} accepted/output agent records fail strict schema validation")
    if evidence["database_lineage_integrity"].get("issue_count"):
        issues.append(f"database lineage audit found {evidence['database_lineage_integrity']['issue_count']} issues")
    return {"status": "PASS" if not issues else "NEEDS_FIX", "issues": issues}


def audit_photo_fixture_trace(photo_fixture_trace: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    for fixture in photo_fixture_trace:
        answer_class = str(fixture.get("answer_class") or "<missing>")
        path = Path(str(fixture.get("path") or ""))
        source_text = str(fixture.get("source_text") or "")
        expected = str(fixture.get("expected_answer") or "")
        photo_answer = str(fixture.get("photo_answer") or "")
        if not path.is_file():
            issues.append(f"{answer_class}: generated photo fixture file is missing")
            continue
        actual_bytes = path.read_bytes()
        if int(fixture.get("byte_size") or 0) != len(actual_bytes) or len(actual_bytes) <= 1000:
            issues.append(f"{answer_class}: generated photo fixture is empty or byte-size lineage is stale")
        if hashlib.sha256(actual_bytes).hexdigest() != str(fixture.get("file_sha256") or ""):
            issues.append(f"{answer_class}: generated photo fixture file hash does not match its trace")
        for required_text in ("PHOTO ANSWER:", "STEP:", "CHECK:"):
            if required_text not in source_text:
                issues.append(f"{answer_class}: source photo content is missing {required_text}")
        if not fixture.get("source_content_sha256") or not fixture.get("source_image_sha256"):
            issues.append(f"{answer_class}: source photo content/image lineage hash is missing")
        if answer_class == "readable_photo":
            if photo_answer != expected or fixture.get("blurred_from_source") or fixture.get("conflicts_with_expected"):
                issues.append("readable_photo: clear photo does not faithfully show the expected answer")
        elif answer_class == "text_photo_conflict":
            if photo_answer == expected or not fixture.get("conflicts_with_expected"):
                issues.append("text_photo_conflict: photo answer does not actually conflict with typed expected answer")
            if fixture.get("blurred_from_source"):
                issues.append("text_photo_conflict: conflict photo must remain clear")
            if not fixture.get("typed_expected_present"):
                issues.append("text_photo_conflict: typed text does not retain the expected answer side of the conflict")
        elif answer_class in {"unclear_photo", "ocr_hallucination"}:
            if photo_answer != expected:
                issues.append(f"{answer_class}: blurred source content changed the underlying answer")
            if not fixture.get("blurred_from_source"):
                issues.append(f"{answer_class}: fixture was not blurred from a meaningful clear source")
            if fixture.get("source_image_sha256") == fixture.get("rendered_image_sha256"):
                issues.append(f"{answer_class}: rendered image is identical to its claimed clear source")
    return {
        "passed": not issues,
        "issues": issues,
        "fixture_count": len(photo_fixture_trace),
        "fixtures": photo_fixture_trace,
    }


def _audit_lesson(state: LessonState, evidence: dict[str, Any], contract: dict[str, Any]) -> tuple[list[str], list[str], list[str], dict[str, Any]]:
    workflow: list[str] = list(state.harness_issues)
    semantic: list[str] = []
    teaching: list[str] = []
    flow = evidence["daily_flows"][-1] if evidence["daily_flows"] else {}
    states = [item["browser"]["canonical_state"] for item in state.state_trace]
    if not states or states[0] != "start_resume":
        workflow.append("lesson did not begin at the canonical start_resume browser state")
    if not state.minimum <= state.interaction_count <= state.maximum:
        workflow.append(f"interaction count {state.interaction_count} is outside {state.minimum}-{state.maximum}")
    if not states or states[-1] != "summary":
        workflow.append("lesson did not reach a child-visible terminal summary")
    elif state.state_trace:
        terminal_view = state.state_trace[-1]["browser"]
        if terminal_view.get("form_visible") or terminal_view.get("primary_visible") or terminal_view.get("secondary_visible"):
            workflow.append("terminal summary still exposes an answer, retry, finish, or next-step action")
    if flow.get("status") != "completed":
        workflow.append(f"daily flow ended with status {flow.get('status')!r} instead of completed")
    active_jobs = [item for item in evidence["background_jobs"] if item.get("status") in {"queued", "claimed", "running", "retry", "waiting"}]
    if active_jobs:
        workflow.append(f"{len(active_jobs)} durable jobs remain active at lesson end")
    leak_hits = [
        {"sequence": item["sequence"], "hits": item["forbidden_child_text_hits"]}
        for item in state.state_trace if item["forbidden_child_text_hits"]
    ]
    if leak_hits:
        workflow.append(f"child DOM exposed forbidden internal text in {len(leak_hits)} captured states")
    if len(state.screenshots) != len(state.state_trace):
        workflow.append("not every child-visible checkpoint has a screenshot")
    analyzing_copy_failures = [
        item["sequence"]
        for item in state.state_trace
        if item["browser"]["canonical_state"] == "analyzing_pending"
        and "答案已经保存" not in item["browser"].get("handoff_text", "")
        and "答案已保存" not in item["browser"].get("handoff_text", "")
    ]
    if analyzing_copy_failures:
        workflow.append(f"analyzing checkpoints do not clearly say saved evidence is retained: {analyzing_copy_failures}")
    required_evidence = set(contract.get("required_evidence_per_lesson") or [])
    available_evidence = set(evidence) | {
        "screenshots", "browser_state_trace", "browser_request_trace", "lineage_audit",
        "expected_oracle", "actual_outcomes", "trust_labels", "child_dom_forbidden_leak_scan", "verdicts",
        "photo_fixture_trace", "photo_fixture_audit", "fault_injection_workflow_evidence", "live_semantic_evidence",
    }
    missing_artifacts = sorted(required_evidence - available_evidence)
    if missing_artifacts:
        workflow.append(f"missing required evidence sections: {', '.join(missing_artifacts)}")
    if state.model_mode == "recorded_model":
        bad_modes = [
            item for item in evidence["background_jobs"]
            if item.get("status") == "succeeded" and item.get("provider_mode") not in {"recorded_model", "deterministic_runtime"}
        ]
        if bad_modes:
            workflow.append("a succeeded recorded-mode durable job has a non-recorded trust label")
    if "restart" in state.lesson.get("coverage", []) and not state.restart_done:
        workflow.append("restart scenario did not restart the HTTP server against the same temporary database")
    if "double_submit" in state.lesson.get("coverage", []):
        submit_requests = [item for item in state.request_trace if item["path"] == SUBMIT_ROUTE]
        duplicate_keys = [str(item["payload"].get("client_idempotency_key") or "") for item in submit_requests[:2]]
        if len(duplicate_keys) != 2 or not duplicate_keys[0] or len(set(duplicate_keys)) != 1:
            workflow.append("double-submit scenario did not send two real requests with one idempotency key")
        elif sum(1 for item in evidence["attempts"] if item.get("client_idempotency_key") == duplicate_keys[0]) != 1:
            workflow.append("double-submit idempotency key did not resolve to exactly one durable attempt")
    if "model_missing" in state.lesson.get("coverage", []):
        if not any(item.get("status") == "blocked" and item.get("provider_mode") == "not_configured" for item in evidence["background_jobs"]):
            workflow.append("model-missing scenario did not persist a not_configured blocked origin job")
    if "model_failing" in state.lesson.get("coverage", []):
        if not any(item.get("status") == "blocked" and item.get("provider_mode") == "recorded_model" for item in evidence["background_jobs"]):
            workflow.append("model-failing scenario did not persist a failed recorded origin job")
    if "repeated_stuck" in state.lesson.get("coverage", []):
        stuck_attempts = [item for item in evidence["attempts"] if item.get("answer_source") == "v3_stuck"]
        if len(stuck_attempts) < 2:
            workflow.append("repeated-stuck scenario persisted fewer than two stuck attempts")
    attempt_by_id = {item["id"]: item for item in evidence["attempts"]}
    mastery_by_attempt: dict[str, list[dict[str, Any]]] = {attempt_id: [] for attempt_id in attempt_by_id}
    for item in evidence["mastery_decisions"]:
        for attempt_id in item.get("source_attempt_ids_value") or []:
            mastery_by_attempt.setdefault(attempt_id, []).append(item)
    for oracle in state.expected_oracle:
        attempt = attempt_by_id.get(oracle["attempt_id"])
        if not attempt:
            semantic.append(f"oracle attempt {oracle['attempt_id']} is missing from final evidence")
            continue
        actual_result = str(attempt.get("result") or "")
        if actual_result not in oracle["expected_result"]:
            semantic.append(
                f"{oracle['answer_class']} attempt {attempt['id']} resolved as {actual_result}; expected one of {oracle['expected_result']}"
            )
        if oracle["must_not_claim_full_mastery"]:
            for mastery in mastery_by_attempt.get(attempt["id"], []):
                if mastery.get("new_status_code") == "A" or mastery.get("decision") in {"mastered", "stable"}:
                    semantic.append(f"{oracle['answer_class']} attempt {attempt['id']} incorrectly drove full mastery")
    for checkpoint in state.state_trace:
        canonical = checkpoint["browser"]["canonical_state"]
        latest = checkpoint["durable"].get("latest_attempt") or {}
        if canonical in {"blocked", "clarify_evidence"} and latest.get("grading_status") == "pending_review":
            if checkpoint["durable"].get("mastery_count_for_latest_attempt"):
                semantic.append(f"pending evidence drove mastery before {canonical} conclusion at checkpoint {checkpoint['sequence']}")
    profile_results = [item.get("result") for item in evidence["attempts"] if item.get("grading_status") == "graded"]
    if state.profile == "all_correct" and any(item != "correct" for item in profile_results):
        semantic.append("all_correct lesson contains a non-correct graded attempt")
    if state.profile == "all_wrong" and any(item != "wrong" for item in profile_results):
        semantic.append("all_wrong lesson contains a non-wrong graded attempt")
    if state.profile == "all_partial" and any(item != "partial" for item in profile_results):
        semantic.append("all_partial lesson contains a non-partial graded attempt")
    if state.profile == "mixed" and not {"correct", "partial", "wrong"} <= set(profile_results):
        semantic.append("mixed lesson did not retain correct, partial, and wrong evidence classes")
    if "right_answer_wrong_reason" in state.lesson.get("coverage", []):
        matching = [attempt_by_id[item["attempt_id"]] for item in state.expected_oracle if item["answer_class"] == "right_answer_wrong_reason"]
        if not matching or any(item.get("result") == "correct" for item in matching):
            semantic.append("right-answer/wrong-reason evidence was not kept below full-correct")
    photo_oracles = [item for item in state.expected_oracle if "photo" in item["answer_class"] or item["answer_class"] == "ocr_hallucination"]
    if photo_oracles and not evidence["attempt_attachments"]:
        workflow.append("photo scenario did not persist an answer attachment")
    photo_fixture_audit = audit_photo_fixture_trace(state.photo_fixture_trace)
    if photo_oracles and not state.photo_fixture_trace:
        photo_fixture_audit["issues"].append("photo scenario has no generated fixture trace")
        photo_fixture_audit["passed"] = False
    if photo_fixture_audit["issues"]:
        workflow.extend([f"photo fixture audit: {issue}" for issue in photo_fixture_audit["issues"]])
        semantic.extend([f"photo fixture audit: {issue}" for issue in photo_fixture_audit["issues"]])
    photo_classes_seen = {str(item.get("answer_class") or "") for item in state.photo_fixture_trace}
    for required_photo_class in (
        "readable_photo",
        "unclear_photo",
        "text_photo_conflict",
        "ocr_hallucination",
    ):
        if required_photo_class in state.lesson.get("coverage", []) and required_photo_class not in photo_classes_seen:
            issue = f"photo fixture audit: declared {required_photo_class} coverage was not exercised"
            workflow.append(issue)
            semantic.append(issue)
    if any(item["answer_class"] in {"unclear_photo", "ocr_hallucination", "text_photo_conflict"} for item in photo_oracles):
        if "clarify_evidence" not in states:
            semantic.append("uncertain/conflicting photo evidence did not reach clarify_evidence")
    if "feedback_teaching" in state.lesson.get("coverage", []) and "feedback_teaching" not in states:
        teaching.append("lesson contract requires feedback_teaching but no child-visible teaching state appeared")
    teaching_steps = [item for item in evidence["flow_steps"] if item.get("step_type") in {"teaching_repair", "worked_example"}]
    for step in teaching_steps:
        package = step.get("prompt_package_value") or {}
        prompt = str(package.get("prompt") or "")
        if not prompt.strip():
            teaching.append(f"teaching step {step['id']} has an empty child prompt")
        if any(term in prompt.lower() for term in CHILD_FORBIDDEN_TEXT):
            teaching.append(f"teaching step {step['id']} exposes internal terminology")
    rollback_ids = set(state.lesson.get("coverage") or []) & {
        item["id"] for item in contract.get("prerequisite_rollback_oracles") or []
    }
    rollback_checks: list[dict[str, Any]] = []
    graph_prerequisites = load_graph_prerequisites()
    for rollback_id in rollback_ids:
        rollback_contract = next(
            item for item in contract["prerequisite_rollback_oracles"] if item["id"] == rollback_id
        )
        rollback_check = audit_prerequisite_rollback(
            rollback_contract,
            evidence["next_step_decisions"],
            evidence["attempts"],
            graph_prerequisites,
            terminal_state=states[-1] if states else "",
        )
        rollback_checks.append(rollback_check)
        teaching.extend(rollback_check["issues"])
    lineage = _lineage_audit(evidence)
    workflow.extend(lineage["issues"])
    trust = audit_trust_labels(evidence, declared_model_mode=state.model_mode)
    if trust["issues"]:
        trust_issues = [f"trust audit: {issue}" for issue in trust["issues"]]
        workflow.extend(trust_issues)
        semantic.extend(trust_issues)
        teaching.extend(trust_issues)
    live_fault_audit = audit_live_fault_injection(
        contract,
        state.lesson,
        state.model_mode,
        state.fault_injection_trace,
        evidence,
    )
    if live_fault_audit["issues"]:
        live_fault_issues = [f"live fault audit: {issue}" for issue in live_fault_audit["issues"]]
        workflow.extend(live_fault_issues)
        semantic.extend(live_fault_issues)
        teaching.extend(live_fault_issues)
    actual_outcomes = {
        "interaction_count": state.interaction_count,
        "states_seen": states,
        "graded_results": profile_results,
        "attempt_ids": list(attempt_by_id),
        "job_statuses": {status: sum(1 for item in evidence["background_jobs"] if item.get("status") == status) for status in {item.get("status") for item in evidence["background_jobs"]}},
        "rollback_checks": rollback_checks,
        "summary_id": evidence["daily_summaries"][-1]["id"] if evidence["daily_summaries"] else "",
    }
    return workflow, semantic, teaching, {
        "lineage_audit": lineage,
        "actual_outcomes": actual_outcomes,
        "child_dom_forbidden_leak_scan": {"status": "PASS" if not leak_hits else "NEEDS_FIX", "hits": leak_hits},
        "trust_labels": trust,
        "photo_fixture_audit": photo_fixture_audit,
        "live_fault_injection_audit": live_fault_audit,
        "fault_injection_workflow_evidence": live_fault_audit["fault_injection_workflow_evidence"],
        "live_semantic_evidence": live_fault_audit["live_semantic_evidence"],
    }


def _validate_live_routes() -> list[str]:
    route_specs = {
        "answer_analysis": model_router.answer_analysis_route(),
        "evaluation": model_router.evaluation_route(),
        "planner": model_router.planner_route(),
        "teaching": model_router.teaching_route(),
        "photo_vision": model_router.answer_photo_vision_route(),
    }
    issues = []
    for name, route in route_specs.items():
        if not route.enabled:
            issues.append(f"live route {name} is not configured")
        elif route.provider in {"recorded_model", "mock_only"}:
            issues.append(f"live route {name} resolves to non-live provider {route.provider}")
    return issues


def _settle_recorded_step(driver: BrowserDriver, env: LessonEnvironment, state: LessonState, label: str) -> dict[str, Any]:
    for recovery_round in range(1, 7):
        results = env.drain_recorded()
        terminal_status = ""
        if results:
            terminal_status = str(results[-1].get("job_status") or results[-1].get("status") or "")
        terminal_blocked = terminal_status in {"blocked", "waiting", "dead_letter"}
        observed = driver.refresh_after_recorded_drain(suppress_blocked_recovery=terminal_blocked)
        if observed["canonical_state"] != "analyzing_pending":
            return observed
        if terminal_blocked:
            state.harness_issues.append(
                f"{label}: terminal {terminal_status} job remained child-visible as analyzing_pending"
            )
            return observed
        driver.capture(f"{label}-recovery-analyzing-{recovery_round}")
        if state.pending_answer_class == "model_failing":
            state.pending_answer_class = "correct"
            state.route_fault = ""
    state.harness_issues.append(f"{label}: recorded recovery did not reach a bounded child-visible conclusion")
    return driver.current_state()


def _settle_live_fault_step(
    driver: BrowserDriver,
    env: LessonEnvironment,
    state: LessonState,
    label: str,
    *,
    inject_current_fault: bool,
) -> dict[str, Any]:
    if inject_current_fault:
        event = env.inject_live_fault_for_latest_attempt(state.pending_answer_class)
        if event["fault_type"] == "controlled_retryable_failure":
            env.drain_live_manually()
    else:
        env.drain_live_manually()
    for recovery_round in range(1, 7):
        observed = driver.refresh_after_recorded_drain()
        if observed["canonical_state"] != "analyzing_pending":
            return observed
        driver.capture(f"{label}-live-recovery-analyzing-{recovery_round}")
        env.drain_live_manually()
    state.harness_issues.append(f"{label}: live L09 recovery did not reach a bounded child-visible conclusion")
    return driver.current_state()


def run_lesson(
    playwright: Any,
    browser: Any,
    lesson: dict[str, Any],
    contract: dict[str, Any],
    output_root: Path,
    *,
    model_mode: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    del playwright
    state = LessonState(lesson=lesson, model_mode=model_mode)
    lesson_output = output_root / str(lesson["id"])
    lesson_output.mkdir(parents=True, exist_ok=True)
    photo_dir = lesson_output / "submitted-photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    with LessonEnvironment(state, lesson_output, contract) as env:
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        driver = BrowserDriver(page, state, env, lesson_output, timeout_seconds)
        try:
            driver.goto(env.base_url)
            driver.capture("entry")
            while state.interaction_count < state.maximum + 1:
                browser_state = driver.current_state()
                canonical = browser_state["canonical_state"]
                if canonical != "analyzing_pending":
                    state.analyzing_reentry_count = 0
                if canonical == "summary":
                    break
                if canonical == "start_resume":
                    driver.click_start()
                    state.interaction_count += 1
                    driver.capture("start-resume")
                    continue
                if canonical in {"current_step", "clarify_evidence"}:
                    if state.profile == "answer_only_stuck" and not state.blank_rejection_done:
                        driver.blank_submit_rejected()
                        state.blank_rejection_done = True
                        driver.capture("blank-evidence-rejected")
                    directive = _answer_directive(state, env, canonical, photo_dir)
                    state.pending_answer_class = directive["answer_class"]
                    double_submit = state.profile == "restart_double_submit" and not state.double_submit_done
                    driver.submit(
                        text=directive["text"],
                        photo_path=directive["photo"],
                        stuck=directive["stuck"],
                        double_submit=double_submit,
                    )
                    state.interaction_count += 1
                    state.force_summary = state.interaction_count >= state.target
                    if double_submit:
                        state.double_submit_done = True
                    env.register_oracle(
                        directive["answer_class"],
                        state.interaction_count,
                        photo_fixture=directive.get("photo_fixture"),
                    )
                    driver.capture(f"submitted-{directive['answer_class']}")
                    if state.profile == "restart_double_submit" and not state.restart_done:
                        new_base_url = env.restart_server()
                        state.restart_done = True
                        driver.goto(new_base_url)
                        driver.capture("server-restarted")
                    if model_mode == "recorded_model":
                        _settle_recorded_step(driver, env, state, f"submitted-{directive['answer_class']}")
                    elif env.live_fault_injection_enabled:
                        _settle_live_fault_step(
                            driver,
                            env,
                            state,
                            f"submitted-{directive['answer_class']}",
                            inject_current_fault=directive["answer_class"] in {"model_missing", "model_failing"},
                        )
                    else:
                        driver.wait_for_child_conclusion()
                    driver.capture(f"conclusion-{directive['answer_class']}")
                    continue
                if canonical == "feedback_teaching":
                    still_stuck = state.profile == "answer_only_stuck" and state.interaction_count + 1 >= state.target
                    driver.continue_teaching(still_stuck=still_stuck)
                    state.interaction_count += 1
                    driver.capture("teaching-still-stuck" if still_stuck else "teaching-continue")
                    continue
                if canonical == "blocked":
                    can_recover = state.profile == "model_recovery" and state.interaction_count < state.target - 1
                    if can_recover:
                        state.pending_answer_class = "correct"
                        state.route_fault = ""
                        driver.retry_blocked()
                        state.interaction_count += 1
                        state.force_summary = state.interaction_count >= state.target
                        driver.capture("blocked-retry-started")
                        if model_mode == "recorded_model":
                            _settle_recorded_step(driver, env, state, "blocked-retry")
                        elif env.live_fault_injection_enabled:
                            _settle_live_fault_step(
                                driver,
                                env,
                                state,
                                "blocked-retry",
                                inject_current_fault=False,
                            )
                        else:
                            driver.wait_for_child_conclusion()
                        driver.capture("blocked-retry-conclusion")
                    else:
                        driver.finish()
                        state.interaction_count += 1
                        driver.capture("blocked-finish-summary")
                    continue
                if canonical == "ready_for_new_knowledge":
                    driver.finish()
                    state.interaction_count += 1
                    driver.capture("checkpoint-finish-summary")
                    continue
                if canonical == "analyzing_pending":
                    state.analyzing_reentry_count += 1
                    if state.analyzing_reentry_count > 2:
                        state.harness_issues.append(
                            "analyzing_pending re-entered the outer lesson loop more than twice without a conclusion"
                        )
                        break
                    if model_mode == "recorded_model":
                        _settle_recorded_step(driver, env, state, "analyzing")
                    elif env.live_fault_injection_enabled:
                        _settle_live_fault_step(
                            driver,
                            env,
                            state,
                            "analyzing",
                            inject_current_fault=False,
                        )
                    else:
                        driver.wait_for_child_conclusion()
                    driver.capture("analyzing-conclusion")
                    continue
                state.harness_issues.append(f"unsupported browser state {canonical!r}")
                break
            if driver.current_state()["canonical_state"] != "summary":
                state.harness_issues.append("adaptive lesson loop ended without summary")
            evidence = env.collect_evidence()
            workflow, semantic, teaching, audit_sections = _audit_lesson(state, evidence, contract)
            verdicts = build_verdicts(
                model_mode,
                workflow_issues=workflow,
                semantic_issues=semantic,
                teaching_issues=teaching,
                trust_scope=audit_sections["trust_labels"]["effective_scope"],
            )
            lesson_result = {
                "lesson": lesson,
                "model_mode": model_mode,
                "interaction_count": state.interaction_count,
                "screenshots": state.screenshots,
                "browser_state_trace": state.state_trace,
                "browser_request_trace": state.request_trace,
                "photo_fixture_trace": state.photo_fixture_trace,
                "fault_injection_trace": state.fault_injection_trace,
                "worker_results": state.worker_results,
                "expected_oracle": state.expected_oracle,
                **{key: value for key, value in evidence.items() if key != "daily_report_markdown"},
                **audit_sections,
                "verdicts": verdicts,
            }
            (lesson_output / "lesson-evidence.json").write_text(
                json.dumps(lesson_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (lesson_output / "daily-report.md").write_text(evidence["daily_report_markdown"], encoding="utf-8")
            return lesson_result
        finally:
            context.close()


def _aggregate_results(contract: dict[str, Any], model_mode: str, lesson_results: list[dict[str, Any]]) -> dict[str, Any]:
    workflow_issues: list[str] = []
    semantic_issues: list[str] = []
    teaching_issues: list[str] = []
    coverage_seen: set[str] = set()
    for result in lesson_results:
        lesson_id = result["lesson"]["id"]
        coverage_seen.update(result["lesson"].get("coverage") or [])
        for dimension, target in (
            ("workflow", workflow_issues),
            ("semantic_quality", semantic_issues),
            ("teaching_quality", teaching_issues),
        ):
            for issue in result["verdicts"][dimension]["issues"]:
                target.append(f"{lesson_id}: {issue}")
    selected_coverage = {
        item for lesson in [result["lesson"] for result in lesson_results] for item in lesson.get("coverage") or []
    }
    required_for_selection = (
        set(contract.get("required_coverage") or [])
        if len(lesson_results) == int(contract["execution_contract"]["lesson_count"])
        else selected_coverage
    )
    missing_coverage = sorted(required_for_selection - coverage_seen)
    if missing_coverage:
        workflow_issues.append(f"selected lessons missed declared coverage: {', '.join(missing_coverage)}")
    lesson_trust_scopes = {
        str((result.get("trust_labels") or {}).get("effective_scope") or "pending")
        for result in lesson_results
    }
    if "mixed_recorded_deterministic" in lesson_trust_scopes or (
        "recorded_model" in lesson_trust_scopes and "deterministic_runtime" in lesson_trust_scopes
    ):
        aggregate_trust_scope = "mixed_recorded_deterministic"
    elif "mixed_live_deterministic" in lesson_trust_scopes or (
        "live_model" in lesson_trust_scopes and "deterministic_runtime" in lesson_trust_scopes
    ):
        aggregate_trust_scope = "mixed_live_deterministic"
    elif model_mode in lesson_trust_scopes:
        aggregate_trust_scope = model_mode
    elif "deterministic_runtime" in lesson_trust_scopes:
        aggregate_trust_scope = "deterministic_runtime"
    else:
        aggregate_trust_scope = "pending"
    verdicts = build_verdicts(
        model_mode,
        workflow_issues=workflow_issues,
        semantic_issues=semantic_issues,
        teaching_issues=teaching_issues,
        trust_scope=aggregate_trust_scope,
    )
    fault_workflow_evidence = [
        {"lesson_id": result["lesson"]["id"], **event}
        for result in lesson_results
        for event in result.get("fault_injection_workflow_evidence") or []
    ]
    live_semantic_evidence = [
        {"lesson_id": result["lesson"]["id"], **item}
        for result in lesson_results
        for item in result.get("live_semantic_evidence") or []
    ]
    return {
        "schema_version": contract["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_mode": model_mode,
        "trust_scope": aggregate_trust_scope,
        "lesson_trust_scopes": sorted(lesson_trust_scopes),
        "fault_injection_workflow_evidence": fault_workflow_evidence,
        "live_semantic_evidence": live_semantic_evidence,
        "scope_statement": (
            "fault-injection events are workflow evidence only; live semantic evidence contains only accepted "
            "real-provider agent runs"
        ),
        "lessons_requested": len(lesson_results),
        "coverage_seen": sorted(coverage_seen),
        "verdicts": verdicts,
        "lessons": [
            {
                "id": result["lesson"]["id"],
                "local_date": result["lesson"]["local_date"],
                "interaction_count": result["interaction_count"],
                "trust_scope": (result.get("trust_labels") or {}).get("effective_scope", "pending"),
                "verdicts": result["verdicts"],
                "artifact": f"{result['lesson']['id']}/lesson-evidence.json",
            }
            for result in lesson_results
        ],
    }


def _render_run_markdown(report: dict[str, Any], output_root: Path) -> str:
    lines = [
        "# v5 10-Lesson Browser QA Harness",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Model mode: `{report['model_mode']}`",
        f"- Trust scope: `{report.get('trust_scope', 'pending')}`",
        f"- Fault-injection workflow events: `{len(report.get('fault_injection_workflow_evidence') or [])}`",
        f"- Accepted live semantic runs: `{len(report.get('live_semantic_evidence') or [])}`",
        f"- Lessons: `{report['lessons_requested']}`",
        f"- Artifact root: `{output_root}`",
        "",
        "## Verdicts",
        "",
    ]
    for dimension in ("workflow", "semantic_quality", "teaching_quality"):
        verdict = report["verdicts"][dimension]
        lines.append(f"- {dimension}: **{verdict['status']}**")
        for issue in verdict["issues"]:
            lines.append(f"  - {issue}")
    lines.extend(["", "## Lessons", ""])
    for lesson in report["lessons"]:
        lines.append(
            f"- `{lesson['id']}` / `{lesson['local_date']}` / interactions `{lesson['interaction_count']}` / "
            f"trust `{lesson.get('trust_scope', 'pending')}` / "
            f"workflow `{lesson['verdicts']['workflow']['status']}` / semantic `{lesson['verdicts']['semantic_quality']['status']}` / "
            f"teaching `{lesson['verdicts']['teaching_quality']['status']}` / `{lesson['artifact']}`"
        )
    return "\n".join(lines) + "\n"


def _select_lessons(contract: dict[str, Any], requested: list[str], limit: int | None) -> list[dict[str, Any]]:
    lessons = list(contract["lessons"])
    if requested:
        requested_set = set(requested)
        lessons = [lesson for lesson in lessons if lesson["id"] in requested_set]
        missing = requested_set - {lesson["id"] for lesson in lessons}
        if missing:
            raise ValueError(f"unknown lesson ids: {', '.join(sorted(missing))}")
    if limit is not None:
        lessons = lessons[:limit]
    return lessons


def run_harness(args: argparse.Namespace) -> tuple[int, dict[str, Any], Path]:
    contract = load_contract(args.contract)
    contract_issues = validate_contract(contract)
    if contract_issues:
        report = {"verdict": "TEST_CASE_SPEC_NEEDS_FIX", "issues": contract_issues}
        return 2, report, Path(args.output_dir or DEFAULT_OUTPUT_ROOT)
    if args.validate_contract:
        return 0, {"verdict": "TEST_CASE_SPEC_READY", "issues": []}, Path(args.output_dir or DEFAULT_OUTPUT_ROOT)
    model_mode = "live_model" if args.live_model else "recorded_model"
    if model_mode == "live_model":
        live_issues = _validate_live_routes()
        if live_issues:
            return 2, {"verdict": "QA_BLOCKED", "model_mode": model_mode, "issues": live_issues}, Path(args.output_dir or DEFAULT_OUTPUT_ROOT)
    lessons = _select_lessons(contract, args.lesson, args.limit_lessons)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / timestamp
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "contract-snapshot.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": not args.headed}
        executable = Path(args.browser_executable).expanduser() if args.browser_executable else Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if executable.is_file():
            launch_options["executable_path"] = str(executable)
        browser = playwright.chromium.launch(**launch_options)
        try:
            lesson_results = [
                run_lesson(
                    playwright,
                    browser,
                    lesson,
                    contract,
                    output_root,
                    model_mode=model_mode,
                    timeout_seconds=args.timeout_seconds,
                )
                for lesson in lessons
            ]
        finally:
            browser.close()
    report = _aggregate_results(contract, model_mode, lesson_results)
    (output_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "report.md").write_text(_render_run_markdown(report, output_root), encoding="utf-8")
    success = all(item["status"] != "NEEDS_FIX" for item in report["verdicts"].values())
    return (0 if success else 1), report, output_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser-driven v5 adaptive 10-lesson QA harness")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--lesson", action="append", default=[], help="Run one named lesson; repeat for more")
    parser.add_argument("--limit-lessons", type=int, default=None, help="Focused prefix run; default is all ten")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--browser-executable", default="")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--live-model", action="store_true", help="Use configured GPT/Doubao routes; performs real external model calls")
    parser.add_argument("--validate-contract", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    code, report, output_root = run_harness(args)
    marker = "TEST_CASE_SPEC" if args.validate_contract else ("QA_HARNESS_DONE" if code == 0 else "QA_HARNESS_NEEDS_FIX")
    print(f"{marker}: model_mode={report.get('model_mode', 'not_run')} output={output_root}")
    if report.get("verdicts"):
        for dimension in ("workflow", "semantic_quality", "teaching_quality"):
            print(f"{dimension}={report['verdicts'][dimension]['status']}")
    for issue in report.get("issues") or []:
        print(f"issue={issue}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
