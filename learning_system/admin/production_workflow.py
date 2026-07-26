from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .expert_review import (
    build_candidate_expert_review,
    build_candidate_model_expert_board_review,
    write_expert_quality_review,
    write_model_expert_board_review,
)
from .production_loop import decide_loop_next_action, decide_staging_from_receipts, write_production_report
from .production_attempt_state import ContentAttemptBudgetExhausted, ProductionAttemptLedger
from .model_deadline import bind_admin_absolute_deadline
from .qa_review import (
    build_candidate_qa_contract_check,
    build_candidate_semantic_qa_review,
    write_candidate_qa_contract_check,
    write_candidate_semantic_qa_review,
)
from .question_generation import (
    build_generated_candidate_batch_from_plans,
    build_generated_candidate_from_plan,
    write_generated_candidate_artifact,
)
from .staging import (
    build_and_write_blocked_stage_candidate_receipt,
    build_and_write_stage_candidate_receipt,
)
from .semantic_collision import (
    build_semantic_collision_board,
    validate_semantic_collision_receipt,
    write_semantic_collision_board,
)


class WorkflowDeadlineInterrupted(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"batch absolute deadline exhausted before stage: {stage}")
        self.stage = stage


def _require_stage_budget(absolute_deadline_monotonic: float | None, stage: str) -> None:
    if absolute_deadline_monotonic is not None and time.monotonic() >= absolute_deadline_monotonic:
        raise WorkflowDeadlineInterrupted(stage)


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


def _collision_stage_kwargs(
    checkpoint: dict[str, Any],
    *,
    root: Path,
    candidate_path: Path,
    staged_bank_path: Path,
) -> dict[str, Any]:
    if not checkpoint.get("collision_required"):
        return {}
    receipt_path = Path(str(checkpoint.get("semantic_collision_json_path") or ""))
    receipt_sha256 = str(checkpoint.get("semantic_collision_json_sha256") or "")
    validated = validate_semantic_collision_receipt(
        root=root,
        receipt_path=receipt_path,
        candidate_path=candidate_path,
        staged_bank_path=staged_bank_path,
        expected_receipt_sha256=receipt_sha256,
    )
    expected = {
        "candidate_set_sha256": validated.get("candidate_set_sha256"),
        "base_staged_bank_sha256": validated.get("base_staged_bank_sha256"),
        "base_staged_snapshot_sha256": validated.get("base_staged_snapshot_sha256"),
        "collision_decision": validated.get("decision"),
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("ADMIN_PRODUCTION_CHECKPOINT_COLLISION_BINDING_MISMATCH")
    return {
        "semantic_collision_receipt_path": receipt_path,
        "semantic_collision_receipt_sha256": receipt_sha256,
    }


def _blocked_stage_receipt(
    *,
    root: Path,
    artifact_root: Path,
    candidate_path: Path,
    staging_decision_path: Path,
    staged_bank_path: Path,
    item_id: str,
    subject: str,
    error: Exception,
    apply: bool,
) -> dict[str, Any]:
    return build_and_write_blocked_stage_candidate_receipt(
        root=root,
        artifact_root=artifact_root,
        candidate_path=candidate_path,
        staging_decision_path=staging_decision_path,
        staged_bank_path=staged_bank_path,
        item_id=item_id,
        subject=subject,
        error=error,
        apply=apply,
    )


@contextmanager
def _cap_model_wall_deadline(
    absolute_deadline_monotonic: float | None, env_name: str
):
    del env_name
    if absolute_deadline_monotonic is not None and time.monotonic() >= absolute_deadline_monotonic:
        raise WorkflowDeadlineInterrupted("model_call")
    with bind_admin_absolute_deadline(absolute_deadline_monotonic):
        yield


def _transport_attempts(report: dict[str, Any]) -> list[dict[str, Any]]:
    meta = report.get("transport_meta") if isinstance(report.get("transport_meta"), dict) else {}
    route = report.get("route") if isinstance(report.get("route"), dict) else {}
    attempts = meta.get("transport_attempts") or route.get("transport_attempts")
    return [dict(attempt) for attempt in attempts or [] if isinstance(attempt, dict)]


def _received_model_content(report: dict[str, Any]) -> bool:
    attempts = _transport_attempts(report)
    if any(str(attempt.get("outcome") or "") == "response_received" for attempt in attempts):
        return True
    return str(report.get("status") or "") not in {
        "BLOCKED_MODEL_ERROR",
        "BLOCKED_MODEL_NOT_CONFIGURED",
    }


def _plan_attempt_identity(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    requirement = (
        (payload.get("bounded_candidate_packet") or {}).get("question_requirement")
        if isinstance(payload.get("bounded_candidate_packet"), dict)
        else {}
    )
    requirement = requirement if isinstance(requirement, dict) else {}
    requirement_id = str(
        payload.get("question_requirement_id") or requirement.get("question_requirement_id") or ""
    )
    slot_id = str(payload.get("slot_id") or requirement.get("slot_id") or "")
    if not requirement_id or not slot_id:
        raise ValueError("ADMIN_PRODUCTION_PLAN_ATTEMPT_IDENTITY_MISSING")
    return requirement_id, slot_id


def _plan_question_requirement(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    packet = payload.get("bounded_candidate_packet")
    requirement = packet.get("question_requirement") if isinstance(packet, dict) else None
    if not isinstance(requirement, dict):
        raise ValueError("ADMIN_PRODUCTION_PLAN_QUESTION_REQUIREMENT_MISSING")
    requirement_id, slot_id = _plan_attempt_identity(path)
    if str(requirement.get("question_requirement_id") or "") != requirement_id:
        raise ValueError("ADMIN_PRODUCTION_PLAN_QUESTION_REQUIREMENT_ID_MISMATCH")
    if str(requirement.get("slot_id") or "") != slot_id:
        raise ValueError("ADMIN_PRODUCTION_PLAN_SLOT_ID_MISMATCH")
    return json.loads(json.dumps(requirement, ensure_ascii=False))


def _plan_question_requirement_binding(root: Path, path: Path) -> dict[str, Any]:
    requirement = _plan_question_requirement(path)
    return {
        "schema_version": "2026-07-25.codex-admin.question-requirement-binding.v1",
        "generation_plan_path": _relative(root, path),
        "generation_plan_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "question_requirement_id": str(requirement.get("question_requirement_id") or ""),
        "slot_id": str(requirement.get("slot_id") or ""),
        "question_requirement_sha256": hashlib.sha256(
            json.dumps(requirement, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "question_requirement": requirement,
    }


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _path_from_report(root: Path, report: dict[str, Any], key: str) -> Path | None:
    value = str(report.get(key) or "")
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _blocking_finding_summaries(report: dict[str, Any]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    status = str(report.get("status") or "")
    if status in {"BLOCKED_MODEL_ERROR", "BLOCKED_MODEL_NOT_CONFIGURED"}:
        model_error = report.get("model_error") if isinstance(report.get("model_error"), dict) else {}
        summaries.append(
            {
                "severity": "P1",
                "profile": "admin_production_workflow",
                "code": status.lower(),
                "message": str(model_error.get("message") or status),
            }
        )
    for finding in report.get("findings") or []:
        if str(finding.get("severity") or "") not in {"P0", "P1"}:
            continue
        summaries.append(
            {
                "severity": str(finding.get("severity") or ""),
                "profile": str(finding.get("profile") or ""),
                "code": str(finding.get("code") or ""),
                "message": str(finding.get("message") or ""),
            }
        )
    return summaries


def _workflow_blocking_codes(report: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for step in report.get("steps") or []:
        for finding in step.get("blocking_findings") or []:
            code = str(finding.get("code") or "")
            if code:
                codes.append(code)
    return sorted(set(codes))


def _refresh_workflow_identity(report: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(report)
    identity_input = "|".join(
        [
            str(refreshed.get("created_at") or ""),
            str(refreshed.get("generation_plan_path") or ""),
            str(refreshed.get("item_id") or ""),
            str(refreshed.get("status") or ""),
            json.dumps(refreshed.get("steps") or [], ensure_ascii=False, sort_keys=True),
        ]
    )
    refreshed["workflow_id"] = "WF-" + hashlib.sha256(identity_input.encode("utf-8")).hexdigest()[:12]
    return refreshed


def _collision_step(report: dict[str, Any], *, item_id: str) -> dict[str, Any]:
    decision = (report.get("candidate_decisions") or {}).get(item_id)
    decision = decision if isinstance(decision, dict) else {}
    verdict = str(decision.get("decision") or "")
    findings = []
    if verdict == "COLLISION":
        findings.append(
            {
                "severity": "P1",
                "profile": "semantic_collision_board",
                "code": "semantic_collision_detected",
                "message": str(decision.get("summary") or "Semantic collision detected."),
            }
        )
    elif verdict != "PASS":
        findings.append(
            {
                "severity": "P1",
                "profile": "semantic_collision_board",
                "code": "semantic_collision_decision_missing",
                "message": "Collision board did not produce a trustworthy decision for this candidate.",
            }
        )
    return {
        "step": "semantic_collision_review",
        "status": verdict or str(report.get("status") or "BLOCKED"),
        "item_id": item_id,
        "node_id": "",
        "family_id": "",
        "report_path": str(report.get("semantic_collision_json_path") or ""),
        "finding_counts": {"P1": len(findings)} if findings else {},
        "scope": {},
        "coverage_eligible": verdict == "PASS",
        "blocking_codes": [finding["code"] for finding in findings],
        "blocking_findings": findings,
        "next_actions": ["stage_candidate"] if verdict == "PASS" else ["regenerate_candidate"],
        "decision": decision,
    }


def _run_single_candidate_collision_review(
    *,
    artifact_root: Path,
    candidate_path: Path,
    staged_bank_path: Path,
    item_id: str,
    subject: str,
    apply: bool,
    absolute_deadline_monotonic: float | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _require_stage_budget(absolute_deadline_monotonic, "semantic_collision_review")
    report = build_semantic_collision_board(
        root=artifact_root,
        candidate_paths=[candidate_path],
        staged_bank_path=staged_bank_path,
        subject=subject,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
    )
    report = write_semantic_collision_board(report, root=artifact_root, apply=apply)
    step = _collision_step(report, item_id=item_id)
    binding = {
        "semantic_collision_json_path": str(report.get("semantic_collision_json_path") or ""),
        "semantic_collision_json_sha256": str(
            report.get("semantic_collision_json_sha256") or ""
        ),
        "candidate_set_sha256": str(report.get("candidate_set_sha256") or ""),
        "base_staged_bank_sha256": str(report.get("base_staged_bank_sha256") or ""),
        "base_staged_snapshot_sha256": str(
            report.get("base_staged_snapshot_sha256") or ""
        ),
        "collision_decision": dict(step.get("decision") or {}),
    }
    return report, step, binding


def _collision_binding_complete(binding: dict[str, Any]) -> bool:
    return all(
        binding.get(key)
        for key in (
            "semantic_collision_json_path",
            "semantic_collision_json_sha256",
            "candidate_set_sha256",
            "base_staged_bank_sha256",
            "base_staged_snapshot_sha256",
            "collision_decision",
        )
    )


def _attempt_ledger_for_report(
    *,
    root: Path,
    artifact_root: Path,
    staged_bank_path: Path,
    report: dict[str, Any],
    max_attempts: int,
    apply: bool,
) -> ProductionAttemptLedger | None:
    plan_value = str(report.get("generation_plan_path") or "")
    if not plan_value:
        return None
    plan_path = Path(plan_value)
    resolved_plan = plan_path if plan_path.is_absolute() else root / plan_path
    if not resolved_plan.exists():
        return None
    requirement_id, slot_id = _plan_attempt_identity(resolved_plan)
    return ProductionAttemptLedger(
        root=root,
        artifact_root=artifact_root,
        staged_bank_path=staged_bank_path,
        requirement_id=requirement_id,
        slot_id=slot_id,
        max_content_attempts=max_attempts,
        apply=apply,
    )


def _step(name: str, report: dict[str, Any], *, path_key: str = "") -> dict[str, Any]:
    blocking_findings = _blocking_finding_summaries(report)
    return {
        "step": name,
        "status": report.get("status"),
        "item_id": report.get("item_id"),
        "node_id": report.get("node_id"),
        "family_id": report.get("family_id"),
        "report_path": report.get(path_key) if path_key else "",
        "finding_counts": report.get("finding_counts") or {},
        "scope": report.get("scope") or {},
        "coverage_eligible": bool(report.get("coverage_eligible", False)),
        "blocking_codes": sorted({finding["code"] for finding in blocking_findings if finding.get("code")}),
        "blocking_findings": blocking_findings,
        "next_actions": report.get("next_actions") or [],
    }


def _error_step(name: str, *, status: str, error: Exception, item_id: str = "", node_id: str = "", family_id: str = "") -> dict[str, Any]:
    return {
        "step": name,
        "status": status,
        "item_id": item_id,
        "node_id": node_id,
        "family_id": family_id,
        "report_path": "",
        "finding_counts": {"P1": 1},
        "blocking_codes": ["workflow_exception"],
        "blocking_findings": [
            {
                "severity": "P1",
                "profile": "admin_production_workflow",
                "code": "workflow_exception",
                "message": str(error),
            }
        ],
        "next_actions": ["inspect_workflow_error"],
        "error": str(error),
    }


def _exception_workflow_report(
    *,
    root: Path,
    artifact_root: Path,
    generation_plan_path: Path,
    staged_bank_path: Path,
    subject: str,
    error: Exception,
) -> dict[str, Any]:
    resolved_plan = generation_plan_path if generation_plan_path.is_absolute() else root / generation_plan_path
    steps = [_error_step("workflow_exception", status="WORKFLOW_EXCEPTION", error=error)]
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    workflow_id_input = "|".join([
        created_at,
        str(resolved_plan),
        "WORKFLOW_EXCEPTION",
        str(error),
    ])
    return {
        "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
        "workflow_id": "WF-" + hashlib.sha256(workflow_id_input.encode("utf-8")).hexdigest()[:12],
        "created_at": created_at,
        "subject": subject,
        "status": "WORKFLOW_EXCEPTION",
        "generation_plan_path": _relative(root, resolved_plan),
        "staged_bank_path": _relative(root, staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path),
        "artifact_root": _relative(root, artifact_root),
        "attempt_count": 0,
        "item_id": "",
        "elapsed_seconds": 0,
        "steps": steps,
        "staged_receipt": {},
        "staging_allowed": False,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def run_slot_production_workflow(
    *,
    root: Path,
    generation_plan_path: Path,
    artifact_root: Path | None = None,
    previous_rejection_path: Path | None = None,
    staged_bank_path: Path = Path("data/question_banks/v18/staged_candidates_v18.json"),
    max_attempts: int = 3,
    subject: str = "math",
    apply: bool = False,
    absolute_deadline_monotonic: float | None = None,
    defer_stage: bool = False,
) -> dict[str, Any]:
    if max_attempts < 1 or max_attempts > 5:
        raise ValueError("ADMIN_PRODUCTION_WORKFLOW_MAX_ATTEMPTS_MUST_BE_1_TO_5")

    started_monotonic = time.monotonic()
    artifact_root = artifact_root or root
    resolved_plan = generation_plan_path if generation_plan_path.is_absolute() else root / generation_plan_path
    rejection_path = previous_rejection_path
    steps: list[dict[str, Any]] = []
    last_status = "WORKFLOW_NOT_STARTED"
    final_item_id = ""
    staged_receipt: dict[str, Any] | None = None
    interrupted_before_stage = ""
    pending_stage: dict[str, Any] = {}
    ledger: ProductionAttemptLedger | None = None
    generated_this_run = 0

    try:
        _require_stage_budget(absolute_deadline_monotonic, "generate_candidate")
        requirement_id, slot_id = _plan_attempt_identity(resolved_plan)
        requirement_binding = _plan_question_requirement_binding(root, resolved_plan)
        question_requirement = requirement_binding["question_requirement"]
        ledger = ProductionAttemptLedger(
            root=root,
            artifact_root=artifact_root,
            staged_bank_path=staged_bank_path,
            requirement_id=requirement_id,
            slot_id=slot_id,
            max_content_attempts=max_attempts,
            apply=apply,
        )
        checkpoint = ledger.pending_stage_checkpoint()
        if checkpoint:
            candidate_checkpoint = Path(str(checkpoint.get("candidate_path") or ""))
            staging_checkpoint = Path(str(checkpoint.get("staging_decision_path") or ""))
            if candidate_checkpoint.exists() and staging_checkpoint.exists():
                steps = list(checkpoint.get("steps") or [])
                final_item_id = str(checkpoint.get("item_id") or "")
                pending_stage = dict(checkpoint.get("pending_stage") or {})
                last_status = "WORKFLOW_READY_FOR_COLLISION_REVIEW"
            else:
                ledger.clear_pending_stage_checkpoint(outcome="checkpoint_artifact_missing")
        collision_pending = bool(
            checkpoint
            and checkpoint.get("collision_required")
            and not checkpoint.get("collision_reviewed")
        )
        if (
            checkpoint
            and last_status == "WORKFLOW_READY_FOR_COLLISION_REVIEW"
            and not defer_stage
            and collision_pending
        ):
            candidate_path = Path(str(pending_stage.get("candidate_path") or ""))
            resolved_staged_bank = (
                staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
            )
            collision_report, collision_step, collision_binding = (
                _run_single_candidate_collision_review(
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staged_bank_path=resolved_staged_bank,
                    item_id=final_item_id,
                    subject=subject,
                    apply=apply,
                    absolute_deadline_monotonic=absolute_deadline_monotonic,
                )
            )
            steps.append(collision_step)
            if collision_step.get("status") != "PASS" or not _collision_binding_complete(
                collision_binding
            ):
                last_status = (
                    "WORKFLOW_COLLISION_REJECTED"
                    if collision_step.get("status") == "COLLISION"
                    else "WORKFLOW_BLOCKED_COLLISION_REVIEW"
                )
            else:
                checkpoint = {
                    **checkpoint,
                    "steps": steps,
                    "collision_required": True,
                    "collision_reviewed": True,
                    **collision_binding,
                }
                ledger.save_pending_stage_checkpoint(checkpoint)
                collision_pending = False
        if (
            checkpoint
            and last_status == "WORKFLOW_READY_FOR_COLLISION_REVIEW"
            and not defer_stage
            and not collision_pending
        ):
            _require_stage_budget(absolute_deadline_monotonic, "stage_candidate")
            candidate_path = Path(str(pending_stage.get("candidate_path") or ""))
            staging_decision_path = Path(str(pending_stage.get("staging_decision_path") or ""))
            try:
                staged_receipt = build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staging_decision_path=staging_decision_path,
                    staged_bank_path=staged_bank_path,
                    subject=subject,
                    apply=apply,
                    **_collision_stage_kwargs(
                        checkpoint,
                        root=artifact_root,
                        candidate_path=candidate_path,
                        staged_bank_path=(
                            staged_bank_path
                            if staged_bank_path.is_absolute()
                            else root / staged_bank_path
                        ),
                    ),
                )
                steps.append(
                    _step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path")
                )
                last_status = (
                    "WORKFLOW_STAGED"
                    if staged_receipt.get("status") in {"STAGED_WRITABLE", "ALREADY_STAGED"}
                    else str(staged_receipt.get("status"))
                )
                ledger.clear_pending_stage_checkpoint(outcome=last_status)
                ledger.set_resume_rejection_path("")
            except Exception as exc:  # noqa: BLE001 - recovery must remain resumable and auditable.
                staged_receipt = _blocked_stage_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staging_decision_path=staging_decision_path,
                    staged_bank_path=staged_bank_path,
                    item_id=final_item_id,
                    subject=subject,
                    error=exc,
                    apply=apply,
                )
                steps.append(
                    _step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path")
                )
                last_status = "WORKFLOW_BLOCKED_STAGE_EXCEPTION"
        if rejection_path is None:
            saved_rejection = ledger.resume_rejection_path()
            rejection_path = Path(saved_rejection) if saved_rejection else None

        while last_status == "WORKFLOW_NOT_STARTED":
            review_checkpoint = ledger.pending_review_checkpoint()
            candidate_path: Path | None = None
            if review_checkpoint:
                if review_checkpoint.get("question_requirement_binding") != requirement_binding:
                    ledger.clear_pending_review_checkpoint(outcome="question_requirement_binding_changed")
                    review_checkpoint = None
            if review_checkpoint:
                candidate_path = Path(str(review_checkpoint.get("candidate_path") or ""))
                expected_candidate_file_sha = str(review_checkpoint.get("candidate_file_sha256") or "")
                actual_candidate_file_sha = (
                    hashlib.sha256(candidate_path.read_bytes()).hexdigest()
                    if candidate_path.exists()
                    else ""
                )
                if not candidate_path.exists() or not expected_candidate_file_sha or actual_candidate_file_sha != expected_candidate_file_sha:
                    ledger.clear_pending_review_checkpoint(outcome="checkpoint_artifact_missing")
                    review_checkpoint = None
            if review_checkpoint:
                generated = dict(review_checkpoint.get("generated") or {})
                machine_receipt = dict(review_checkpoint.get("machine_receipt") or {})
                lease = dict(review_checkpoint.get("lease") or {})
                steps = list(review_checkpoint.get("steps") or [])
                final_item_id = str(review_checkpoint.get("item_id") or generated.get("item_id") or "")
                attempts_consumed = int(ledger.snapshot().get("content_attempts_consumed") or 0)
            else:
                _require_stage_budget(absolute_deadline_monotonic, "generate_candidate")
                try:
                    lease = ledger.begin_content_attempt()
                except ContentAttemptBudgetExhausted:
                    last_status = "WORKFLOW_BLOCKED_MAX_ATTEMPTS"
                    break
                attempt = int(lease["content_attempt"])
                with _cap_model_wall_deadline(
                    absolute_deadline_monotonic,
                    "AI_ADMIN_QUESTION_GENERATION_WALL_SECONDS",
                ):
                    generated = build_generated_candidate_from_plan(
                        root=root,
                        generation_plan_path=resolved_plan,
                        previous_rejection_path=rejection_path,
                        generation_attempt=attempt,
                        subject=subject,
                    )
                generated_this_run += 1
                generated = write_generated_candidate_artifact(generated, root=artifact_root, apply=apply)
                generated = write_production_report(generated, root=artifact_root, apply=apply)
                ledger.record_provider_transport_attempts(
                    lease,
                    stage="generate_candidate",
                    attempts=_transport_attempts(generated),
                )
                content_received = _received_model_content(generated)
                ledger.complete_content_attempt(
                    lease,
                    consumed=content_received,
                    outcome=str(generated.get("status") or "generation_completed"),
                )
                steps.append(_step("generate_candidate", generated, path_key="production_json_path"))
                machine_receipt = write_production_report(
                    generated.get("machine_report") or generated,
                    root=artifact_root,
                    apply=apply,
                )
                steps.append(_step("machine_contract_check", machine_receipt, path_key="production_json_path"))
                final_item_id = str(generated.get("item_id") or final_item_id)

                if not content_received:
                    last_status = str(generated.get("status") or "BLOCKED_MODEL_ERROR")
                    break
                attempts_consumed = int(ledger.snapshot().get("content_attempts_consumed") or 0)

                if generated.get("status") != "CANDIDATE_READY_FOR_EXPERT_REVIEW":
                    loop = decide_loop_next_action(
                        machine_report=machine_receipt,
                        generation_attempt=attempts_consumed,
                        max_attempts=max_attempts,
                        subject=subject,
                    )
                    loop = write_production_report(loop, root=artifact_root, apply=apply)
                    steps.append(_step("loop_decision", loop, path_key="production_json_path"))
                    last_status = str(loop.get("status") or generated.get("status"))
                    if loop.get("next_action") == "regenerate_candidate" and attempts_consumed < max_attempts:
                        rejection_path = _path_from_report(artifact_root, loop, "production_json_path")
                        last_status = "WORKFLOW_NOT_STARTED"
                        continue
                    break

                candidate_path = _path_from_report(artifact_root, generated, "candidate_json_path")
                if candidate_path is None or not candidate_path.exists():
                    last_status = "WORKFLOW_BLOCKED_MISSING_CANDIDATE_ARTIFACT"
                    break
                ledger.save_pending_review_checkpoint(
                    {
                        "item_id": final_item_id,
                        "candidate_path": str(candidate_path),
                        "lease": lease,
                        "generated": generated,
                        "machine_receipt": machine_receipt,
                        "steps": steps,
                        "candidate_file_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                        "question_requirement_binding": requirement_binding,
                    }
                )

            _require_stage_budget(absolute_deadline_monotonic, "expert_review")
            expert = build_candidate_expert_review(root=root, candidate_path=candidate_path, subject=subject)
            expert = write_expert_quality_review(expert, root=artifact_root, apply=apply)
            steps.append(_step("expert_review", expert, path_key="review_json_path"))
            if expert.get("status") != "PASS":
                ledger.clear_pending_review_checkpoint(outcome=str(expert.get("status") or "expert_rejected"))
                loop = decide_loop_next_action(
                    machine_report=generated.get("machine_report") or generated,
                    expert_report=expert,
                    generation_attempt=attempts_consumed,
                    max_attempts=max_attempts,
                    subject=subject,
                )
                loop = write_production_report(loop, root=artifact_root, apply=apply)
                steps.append(_step("loop_decision", loop, path_key="production_json_path"))
                last_status = str(loop.get("status") or expert.get("status"))
                if loop.get("next_action") == "regenerate_candidate" and attempts_consumed < max_attempts:
                    rejection_path = _path_from_report(artifact_root, expert, "review_json_path")
                    last_status = "WORKFLOW_NOT_STARTED"
                    continue
                break

            _require_stage_budget(absolute_deadline_monotonic, "model_expert_board_review")
            with _cap_model_wall_deadline(
                absolute_deadline_monotonic,
                "AI_ADMIN_QUESTION_EXPERT_REVIEW_WALL_SECONDS",
            ):
                model_expert = build_candidate_model_expert_board_review(
                    root=root,
                    candidate_path=candidate_path,
                    deterministic_review=expert,
                    question_requirement=question_requirement,
                    subject=subject,
                )
            model_expert = write_model_expert_board_review(model_expert, root=artifact_root, apply=apply)
            ledger.record_provider_transport_attempts(
                lease,
                stage="model_expert_board_review",
                attempts=_transport_attempts(model_expert),
            )
            steps.append(_step("model_expert_board_review", model_expert, path_key="model_expert_review_json_path"))
            if model_expert.get("status") != "PASS":
                if model_expert.get("status") in {"BLOCKED_MODEL_NOT_CONFIGURED", "BLOCKED_MODEL_ERROR"}:
                    last_status = str(model_expert.get("status") or "WORKFLOW_BLOCKED_MODEL_EXPERT")
                    break
                ledger.clear_pending_review_checkpoint(
                    outcome=str(model_expert.get("status") or "model_expert_rejected")
                )
                loop = decide_loop_next_action(
                    machine_report=generated.get("machine_report") or generated,
                    expert_report=model_expert,
                    generation_attempt=attempts_consumed,
                    max_attempts=max_attempts,
                    subject=subject,
                )
                loop = write_production_report(loop, root=artifact_root, apply=apply)
                steps.append(_step("loop_decision", loop, path_key="production_json_path"))
                last_status = str(loop.get("status") or model_expert.get("status"))
                if loop.get("next_action") == "regenerate_candidate" and attempts_consumed < max_attempts:
                    rejection_path = _path_from_report(artifact_root, model_expert, "model_expert_review_json_path")
                    last_status = "WORKFLOW_NOT_STARTED"
                    continue
                break

            _require_stage_budget(absolute_deadline_monotonic, "qa_contract_check")
            qa_contract = build_candidate_qa_contract_check(root=root, candidate_path=candidate_path, subject=subject)
            qa_contract = write_candidate_qa_contract_check(qa_contract, root=artifact_root, apply=apply)
            steps.append(_step("qa_contract_check", qa_contract, path_key="qa_contract_check_json_path"))
            if qa_contract.get("status") != "PASS":
                ledger.clear_pending_review_checkpoint(
                    outcome=str(qa_contract.get("status") or "qa_contract_rejected")
                )
                last_status = str(qa_contract.get("status") or "WORKFLOW_BLOCKED_QA_CONTRACT")
                if attempts_consumed < max_attempts:
                    rejection_path = _path_from_report(artifact_root, qa_contract, "qa_contract_check_json_path")
                    last_status = "WORKFLOW_NOT_STARTED"
                    continue
                break

            _require_stage_budget(absolute_deadline_monotonic, "semantic_qa_review")
            with _cap_model_wall_deadline(
                absolute_deadline_monotonic,
                "AI_ADMIN_QUESTION_QA_REVIEW_WALL_SECONDS",
            ):
                semantic_qa = build_candidate_semantic_qa_review(
                    root=root,
                    candidate_path=candidate_path,
                    contract_check=qa_contract,
                    subject=subject,
                )
            semantic_qa = write_candidate_semantic_qa_review(semantic_qa, root=artifact_root, apply=apply)
            ledger.record_provider_transport_attempts(
                lease,
                stage="semantic_qa_review",
                attempts=_transport_attempts(semantic_qa),
            )
            steps.append(_step("semantic_qa_review", semantic_qa, path_key="qa_json_path"))
            semantic_status = str(semantic_qa.get("status") or "")
            if semantic_status != "PASS":
                if semantic_status == "PASS_WITH_SCOPE":
                    ledger.clear_pending_review_checkpoint(outcome=semantic_status)
                    last_status = "WORKFLOW_SCOPED_NOT_STAGED"
                    break
                if semantic_status in {"BLOCKED_MODEL_NOT_CONFIGURED", "BLOCKED_MODEL_ERROR"}:
                    last_status = semantic_status
                    break
                ledger.clear_pending_review_checkpoint(
                    outcome=semantic_status or "semantic_qa_rejected"
                )
                last_status = semantic_status or "WORKFLOW_BLOCKED_SEMANTIC_QA"
                if attempts_consumed < max_attempts:
                    rejection_path = _path_from_report(artifact_root, semantic_qa, "qa_json_path")
                    last_status = "WORKFLOW_NOT_STARTED"
                    continue
                break

            _require_stage_budget(absolute_deadline_monotonic, "staging_decision")
            staging = decide_staging_from_receipts(
                root=root,
                artifact_root=artifact_root,
                machine_report=machine_receipt,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
                subject=subject,
            )
            staging = write_production_report(staging, root=artifact_root, apply=apply)
            steps.append(_step("staging_decision", staging, path_key="production_json_path"))
            if not staging.get("staging_allowed"):
                ledger.clear_pending_review_checkpoint(
                    outcome=str(staging.get("status") or "staging_decision_rejected")
                )
                last_status = str(staging.get("status") or "WORKFLOW_BLOCKED_STAGING")
                break

            staging_decision_path = _path_from_report(artifact_root, staging, "production_json_path")
            if staging_decision_path is None or not staging_decision_path.exists():
                ledger.clear_pending_review_checkpoint(outcome="staging_decision_artifact_missing")
                last_status = "WORKFLOW_BLOCKED_MISSING_STAGING_DECISION_ARTIFACT"
                break
            pending_stage = {
                "candidate_path": str(candidate_path),
                "staging_decision_path": str(staging_decision_path),
            }
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": final_item_id,
                    "candidate_path": str(candidate_path),
                    "staging_decision_path": str(staging_decision_path),
                    "pending_stage": pending_stage,
                    "steps": steps,
                    "collision_required": True,
                    "collision_reviewed": False,
                }
            )
            ledger.clear_pending_review_checkpoint(outcome="ready_for_stage")
            if defer_stage:
                last_status = "WORKFLOW_READY_FOR_COLLISION_REVIEW"
                break

            resolved_staged_bank = (
                staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
            )
            collision_report, collision_step, collision_binding = (
                _run_single_candidate_collision_review(
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staged_bank_path=resolved_staged_bank,
                    item_id=final_item_id,
                    subject=subject,
                    apply=apply,
                    absolute_deadline_monotonic=absolute_deadline_monotonic,
                )
            )
            steps.append(collision_step)
            if collision_step.get("status") != "PASS" or not _collision_binding_complete(
                collision_binding
            ):
                last_status = (
                    "WORKFLOW_COLLISION_REJECTED"
                    if collision_step.get("status") == "COLLISION"
                    else "WORKFLOW_BLOCKED_COLLISION_REVIEW"
                )
                break
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": final_item_id,
                    "candidate_path": str(candidate_path),
                    "staging_decision_path": str(staging_decision_path),
                    "pending_stage": pending_stage,
                    "steps": steps,
                    "collision_required": True,
                    "collision_reviewed": True,
                    **collision_binding,
                }
            )

            _require_stage_budget(absolute_deadline_monotonic, "stage_candidate")
            try:
                staged_receipt = build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staging_decision_path=staging_decision_path,
                    staged_bank_path=staged_bank_path,
                    subject=subject,
                    apply=apply,
                    semantic_collision_receipt_path=Path(
                        collision_binding["semantic_collision_json_path"]
                    ),
                    semantic_collision_receipt_sha256=collision_binding[
                        "semantic_collision_json_sha256"
                    ],
                )
                steps.append(_step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path"))
                last_status = "WORKFLOW_STAGED" if staged_receipt.get("status") in {"STAGED_WRITABLE", "ALREADY_STAGED"} else str(staged_receipt.get("status"))
                ledger.clear_pending_stage_checkpoint(outcome=last_status)
                ledger.set_resume_rejection_path("")
            except Exception as exc:  # noqa: BLE001 - staging refusal must be recorded as a slot failure.
                staged_receipt = _blocked_stage_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=candidate_path,
                    staging_decision_path=staging_decision_path,
                    staged_bank_path=staged_bank_path,
                    item_id=final_item_id,
                    subject=subject,
                    error=exc,
                    apply=apply,
                )
                steps.append(
                    _step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path")
                )
                last_status = "WORKFLOW_BLOCKED_STAGE_EXCEPTION"
            break
    except WorkflowDeadlineInterrupted as exc:
        last_status = "INTERRUPTED_DEADLINE"
        interrupted_before_stage = exc.stage

    status = last_status
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    workflow_id_input = "|".join([
        created_at,
        str(resolved_plan),
        final_item_id,
        status,
        json.dumps(steps, ensure_ascii=False, sort_keys=True),
    ])
    return {
        "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
        "workflow_id": "WF-" + hashlib.sha256(workflow_id_input.encode("utf-8")).hexdigest()[:12],
        "created_at": created_at,
        "subject": subject,
        "status": status,
        "generation_plan_path": _relative(root, resolved_plan),
        "staged_bank_path": _relative(root, staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path),
        "artifact_root": _relative(root, artifact_root),
        "attempt_count": generated_this_run,
        "item_id": final_item_id,
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "steps": steps,
        "staged_receipt": staged_receipt or {},
        "pending_stage": pending_stage,
        "interrupted_before_stage": interrupted_before_stage,
        "content_attempt_state": ledger.snapshot() if ledger is not None else {},
        "staging_allowed": status == "WORKFLOW_STAGED",
        "coverage_eligible": status == "WORKFLOW_STAGED",
        "staging_scope": next(
            (step.get("scope") or {} for step in reversed(steps) if step.get("step") == "semantic_qa_review"),
            {},
        ),
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def _finish_ready_generated_candidate(
    *,
    root: Path,
    artifact_root: Path,
    generated: dict[str, Any],
    staged_bank_path: Path,
    subject: str,
    generation_step_name: str,
    question_requirement: dict[str, Any],
    apply: bool,
    absolute_deadline_monotonic: float | None = None,
    defer_stage: bool = False,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    steps: list[dict[str, Any]] = [_step(generation_step_name, generated, path_key="production_json_path")]
    machine_receipt = write_production_report(
        generated.get("machine_report") or generated,
        root=artifact_root,
        apply=apply,
    )
    steps.append(_step("machine_contract_check", machine_receipt, path_key="production_json_path"))
    candidate_path = _path_from_report(artifact_root, generated, "candidate_json_path")
    if candidate_path is None or not candidate_path.exists():
        status = "WORKFLOW_BLOCKED_MISSING_CANDIDATE_ARTIFACT"
        staged_receipt: dict[str, Any] | None = None
    else:
        _require_stage_budget(absolute_deadline_monotonic, "expert_review")
        expert = build_candidate_expert_review(root=root, candidate_path=candidate_path, subject=subject)
        expert = write_expert_quality_review(expert, root=artifact_root, apply=apply)
        steps.append(_step("expert_review", expert, path_key="review_json_path"))
        staged_receipt = None
        if expert.get("status") != "PASS":
            status = str(expert.get("status") or "WORKFLOW_BLOCKED_EXPERT")
        else:
            _require_stage_budget(absolute_deadline_monotonic, "model_expert_board_review")
            with _cap_model_wall_deadline(
                absolute_deadline_monotonic,
                "AI_ADMIN_QUESTION_EXPERT_REVIEW_WALL_SECONDS",
            ):
                model_expert = build_candidate_model_expert_board_review(
                    root=root,
                    candidate_path=candidate_path,
                    deterministic_review=expert,
                    question_requirement=question_requirement,
                    subject=subject,
                )
            model_expert = write_model_expert_board_review(model_expert, root=artifact_root, apply=apply)
            steps.append(_step("model_expert_board_review", model_expert, path_key="model_expert_review_json_path"))
            if model_expert.get("status") not in {"PASS", "PASS_WITH_SCOPE"}:
                status = str(model_expert.get("status") or "WORKFLOW_BLOCKED_MODEL_EXPERT")
            else:
                _require_stage_budget(absolute_deadline_monotonic, "qa_contract_check")
                qa_contract = build_candidate_qa_contract_check(root=root, candidate_path=candidate_path, subject=subject)
                qa_contract = write_candidate_qa_contract_check(qa_contract, root=artifact_root, apply=apply)
                steps.append(_step("qa_contract_check", qa_contract, path_key="qa_contract_check_json_path"))
                if qa_contract.get("status") != "PASS":
                    status = str(qa_contract.get("status") or "WORKFLOW_BLOCKED_QA_CONTRACT")
                else:
                    _require_stage_budget(absolute_deadline_monotonic, "semantic_qa_review")
                    with _cap_model_wall_deadline(
                        absolute_deadline_monotonic,
                        "AI_ADMIN_QUESTION_QA_REVIEW_WALL_SECONDS",
                    ):
                        semantic_qa = build_candidate_semantic_qa_review(
                            root=root,
                            candidate_path=candidate_path,
                            contract_check=qa_contract,
                            subject=subject,
                        )
                    semantic_qa = write_candidate_semantic_qa_review(semantic_qa, root=artifact_root, apply=apply)
                    steps.append(_step("semantic_qa_review", semantic_qa, path_key="qa_json_path"))
                    semantic_status = str(semantic_qa.get("status") or "")
                    if semantic_status == "PASS_WITH_SCOPE":
                        status = "WORKFLOW_SCOPED_NOT_STAGED"
                    elif semantic_status != "PASS":
                        status = semantic_status or "WORKFLOW_BLOCKED_SEMANTIC_QA"
                    else:
                        staging = decide_staging_from_receipts(
                            root=root,
                            artifact_root=artifact_root,
                            machine_report=machine_receipt,
                            expert_report=expert,
                            model_expert_report=model_expert,
                            qa_contract_report=qa_contract,
                            semantic_qa_report=semantic_qa,
                            subject=subject,
                        )
                        staging = write_production_report(staging, root=artifact_root, apply=apply)
                        steps.append(_step("staging_decision", staging, path_key="production_json_path"))
                        if not staging.get("staging_allowed"):
                            status = str(staging.get("status") or "WORKFLOW_BLOCKED_STAGING")
                        else:
                            staging_decision_path = _path_from_report(artifact_root, staging, "production_json_path")
                            if staging_decision_path is None or not staging_decision_path.exists():
                                status = "WORKFLOW_BLOCKED_MISSING_STAGING_DECISION_ARTIFACT"
                            elif defer_stage:
                                status = "WORKFLOW_READY_FOR_COLLISION_REVIEW"
                                pending_stage = {
                                    "candidate_path": str(candidate_path),
                                    "staging_decision_path": str(staging_decision_path),
                                }
                            else:
                                resolved_staged_bank = (
                                    staged_bank_path
                                    if staged_bank_path.is_absolute()
                                    else root / staged_bank_path
                                )
                                collision_report, collision_step, collision_binding = (
                                    _run_single_candidate_collision_review(
                                        artifact_root=artifact_root,
                                        candidate_path=candidate_path,
                                        staged_bank_path=resolved_staged_bank,
                                        item_id=str(generated.get("item_id") or ""),
                                        subject=subject,
                                        apply=apply,
                                        absolute_deadline_monotonic=absolute_deadline_monotonic,
                                    )
                                )
                                steps.append(collision_step)
                                if collision_step.get("status") != "PASS" or not _collision_binding_complete(
                                    collision_binding
                                ):
                                    status = (
                                        "WORKFLOW_COLLISION_REJECTED"
                                        if collision_step.get("status") == "COLLISION"
                                        else "WORKFLOW_BLOCKED_COLLISION_REVIEW"
                                    )
                                else:
                                    _require_stage_budget(absolute_deadline_monotonic, "stage_candidate")
                                    try:
                                        staged_receipt = build_and_write_stage_candidate_receipt(
                                            root=root,
                                            artifact_root=artifact_root,
                                            candidate_path=candidate_path,
                                            staging_decision_path=staging_decision_path,
                                            staged_bank_path=staged_bank_path,
                                            subject=subject,
                                            apply=apply,
                                            semantic_collision_receipt_path=Path(
                                                collision_binding["semantic_collision_json_path"]
                                            ),
                                            semantic_collision_receipt_sha256=collision_binding[
                                                "semantic_collision_json_sha256"
                                            ],
                                        )
                                        steps.append(_step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path"))
                                        status = "WORKFLOW_STAGED" if staged_receipt.get("status") in {"STAGED_WRITABLE", "ALREADY_STAGED"} else str(staged_receipt.get("status"))
                                    except Exception as exc:  # noqa: BLE001 - staging refusal must be recorded as a slot failure.
                                        steps.append(_error_step("stage_candidate", status="WORKFLOW_BLOCKED_STAGE_EXCEPTION", error=exc, item_id=str(generated.get("item_id") or "")))
                                        status = "WORKFLOW_BLOCKED_STAGE_EXCEPTION"
    pending_stage = locals().get("pending_stage", {})
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    workflow_id_input = "|".join([
        created_at,
        str(generated.get("generation_plan_path") or ""),
        str(generated.get("item_id") or ""),
        status,
        json.dumps(steps, ensure_ascii=False, sort_keys=True),
    ])
    return {
        "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
        "workflow_id": "WF-" + hashlib.sha256(workflow_id_input.encode("utf-8")).hexdigest()[:12],
        "created_at": created_at,
        "subject": subject,
        "status": status,
        "generation_plan_path": str(generated.get("generation_plan_path") or ""),
        "staged_bank_path": _relative(root, staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path),
        "artifact_root": _relative(root, artifact_root),
        "attempt_count": 1,
        "item_id": str(generated.get("item_id") or ""),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "steps": steps,
        "staged_receipt": staged_receipt or {},
        "pending_stage": pending_stage,
        "staging_allowed": status == "WORKFLOW_STAGED",
        "coverage_eligible": status == "WORKFLOW_STAGED",
        "staging_scope": next(
            (step.get("scope") or {} for step in reversed(steps) if step.get("step") == "semantic_qa_review"),
            {},
        ),
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def render_slot_production_workflow_markdown(report: dict[str, Any]) -> str:
    step_lines = [
        f"| {step.get('step', '')} | {step.get('status', '')} | {step.get('item_id', '')} | {step.get('report_path', '')} |"
        for step in report.get("steps") or []
    ]
    if not step_lines:
        step_lines.append("| | | | |")
    return f"""# Slot Production Workflow

Status: `{report.get('status')}`

Workflow ID: `{report.get('workflow_id')}`

Created At: {report.get('created_at')}

Generation Plan: `{report.get('generation_plan_path')}`

Attempt Count: {report.get('attempt_count')}

Elapsed Seconds: {report.get('elapsed_seconds')}

Item: `{report.get('item_id')}`

Staging Allowed: `{report.get('staging_allowed')}`

Activation Implication: `{report.get('activation_implication')}`

## Steps

| Step | Status | Item | Report |
|---|---|---|---|
{chr(10).join(step_lines)}
"""


def write_slot_production_workflow_report(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    workflow_id = str(report.get("workflow_id") or "WF-unknown")
    markdown_rel = Path("docs/system/admin_reports/workflows") / f"{datetime.now(timezone.utc).date()}-{workflow_id}.md"
    json_rel = Path("data/admin/workflows") / f"{workflow_id}.json"
    result = {
        **report,
        "workflow_markdown_path": str(markdown_rel),
        "workflow_json_path": str(json_rel),
        "workflow_write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    _atomic_write_text(markdown_path, render_slot_production_workflow_markdown(report))
    result["workflow_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    _atomic_write_text(
        json_path,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    result["workflow_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result


def run_batch_production_workflow(
    *,
    root: Path,
    generation_plan_paths: list[Path],
    artifact_root: Path | None = None,
    staged_bank_path: Path = Path("data/question_banks/v18/staged_candidates_v18.json"),
    max_attempts_per_slot: int = 3,
    max_slots: int = 20,
    max_runtime_seconds: float = 1800.0,
    generation_batch_size: int = 1,
    parallel_workers: int = 1,
    subject: str = "math",
    apply: bool = False,
) -> dict[str, Any]:
    if not generation_plan_paths:
        raise ValueError("ADMIN_PRODUCTION_BATCH_REQUIRES_GENERATION_PLANS")
    if max_slots < 1:
        raise ValueError("ADMIN_PRODUCTION_BATCH_MAX_SLOTS_MUST_BE_POSITIVE")
    if max_runtime_seconds <= 0:
        raise ValueError("ADMIN_PRODUCTION_BATCH_RUNTIME_BUDGET_MUST_BE_POSITIVE")
    if generation_batch_size < 1 or generation_batch_size > 5:
        raise ValueError("ADMIN_PRODUCTION_BATCH_GENERATION_SIZE_MUST_BE_1_TO_5")
    if parallel_workers < 1 or parallel_workers > 8:
        raise ValueError("ADMIN_PRODUCTION_BATCH_PARALLEL_WORKERS_MUST_BE_1_TO_8")

    artifact_root = artifact_root or root
    started_monotonic = time.monotonic()
    absolute_deadline_monotonic = started_monotonic + max_runtime_seconds
    slot_reports: list[dict[str, Any]] = []
    blocked_reason = ""
    collision_report: dict[str, Any] = {}
    selected_plans = generation_plan_paths[:max_slots]

    if generation_batch_size <= 1:
        plan_groups = [[path] for path in selected_plans]
    else:
        plan_groups = [
            selected_plans[index:index + generation_batch_size]
            for index in range(0, len(selected_plans), generation_batch_size)
        ]

    if generation_batch_size <= 1 and parallel_workers > 1:
        if time.monotonic() >= absolute_deadline_monotonic:
            blocked_reason = "batch_runtime_budget_exhausted_before_launch"
        else:
            indexed_reports: list[dict[str, Any] | None] = [None] * len(selected_plans)

            def run_one(index: int, plan_path: Path) -> tuple[int, dict[str, Any]]:
                try:
                    slot_report = run_slot_production_workflow(
                        root=root,
                        artifact_root=artifact_root,
                        generation_plan_path=plan_path,
                        staged_bank_path=staged_bank_path,
                        max_attempts=max_attempts_per_slot,
                        subject=subject,
                        apply=apply,
                        absolute_deadline_monotonic=absolute_deadline_monotonic,
                        defer_stage=True,
                    )
                except Exception as exc:  # noqa: BLE001 - one failed slot must not crash the batch.
                    slot_report = _exception_workflow_report(
                        root=root,
                        artifact_root=artifact_root,
                        generation_plan_path=plan_path,
                        staged_bank_path=staged_bank_path,
                        subject=subject,
                        error=exc,
                    )
                return index, slot_report

            with ThreadPoolExecutor(max_workers=min(parallel_workers, len(selected_plans))) as executor:
                futures = [executor.submit(run_one, index, plan_path) for index, plan_path in enumerate(selected_plans)]
                for future in as_completed(futures):
                    index, report = future.result()
                    indexed_reports[index] = report
            slot_reports.extend(report for report in indexed_reports if report is not None)
    else:
        for plan_group in plan_groups:
            if time.monotonic() >= absolute_deadline_monotonic:
                blocked_reason = "batch_runtime_budget_exhausted"
                break
            if generation_batch_size <= 1 or len(plan_group) == 1:
                for plan_path in plan_group:
                    slot_report = run_slot_production_workflow(
                        root=root,
                        artifact_root=artifact_root,
                        generation_plan_path=plan_path,
                        staged_bank_path=staged_bank_path,
                        max_attempts=max_attempts_per_slot,
                        subject=subject,
                        apply=apply,
                        absolute_deadline_monotonic=absolute_deadline_monotonic,
                        defer_stage=True,
                    )
                    slot_reports.append(slot_report)
                continue

            _require_stage_budget(absolute_deadline_monotonic, "generate_candidate_batch")
            with _cap_model_wall_deadline(
                absolute_deadline_monotonic,
                "AI_ADMIN_QUESTION_GENERATION_WALL_SECONDS",
            ):
                batch_generation = build_generated_candidate_batch_from_plans(
                    root=root,
                    generation_plan_paths=plan_group,
                    generation_attempt=1,
                    subject=subject,
                )
            for generated in batch_generation.get("candidate_reports") or []:
                generated = write_generated_candidate_artifact(generated, root=artifact_root, apply=apply)
                generated = write_production_report(generated, root=artifact_root, apply=apply)
                if generated.get("status") == "CANDIDATE_READY_FOR_EXPERT_REVIEW":
                    slot_report = _finish_ready_generated_candidate(
                        root=root,
                        artifact_root=artifact_root,
                        generated=generated,
                        staged_bank_path=staged_bank_path,
                        subject=subject,
                        generation_step_name="generate_candidate_batch",
                        question_requirement=_plan_question_requirement(
                            Path(str(generated.get("generation_plan_path") or ""))
                            if Path(str(generated.get("generation_plan_path") or "")).is_absolute()
                            else root / Path(str(generated.get("generation_plan_path") or ""))
                        ),
                        apply=apply,
                        absolute_deadline_monotonic=absolute_deadline_monotonic,
                        defer_stage=True,
                    )
                    slot_reports.append(slot_report)
                else:
                    fallback_plan = Path(str(generated.get("generation_plan_path") or ""))
                    fallback_rejection = _path_from_report(artifact_root, generated, "production_json_path")
                    slot_report = run_slot_production_workflow(
                        root=root,
                        artifact_root=artifact_root,
                        generation_plan_path=fallback_plan,
                        previous_rejection_path=fallback_rejection,
                        staged_bank_path=staged_bank_path,
                        max_attempts=max_attempts_per_slot,
                        subject=subject,
                        apply=apply,
                        absolute_deadline_monotonic=absolute_deadline_monotonic,
                        defer_stage=True,
                    )
                    slot_reports.append(slot_report)

    ready_reports = [
        report
        for report in slot_reports
        if report.get("status") == "WORKFLOW_READY_FOR_COLLISION_REVIEW"
    ]
    if ready_reports:
        candidate_paths = [
            Path(str((report.get("pending_stage") or {}).get("candidate_path") or ""))
            for report in ready_reports
        ]
        if time.monotonic() >= absolute_deadline_monotonic:
            blocked_reason = blocked_reason or "batch_runtime_budget_exhausted_before_collision_review"
            collision_report = {
                "status": "INTERRUPTED_DEADLINE",
                "candidate_decisions": {},
                "findings": [],
                "finding_counts": {"P1": 1},
            }
        else:
            try:
                collision_report = build_semantic_collision_board(
                    root=root,
                    candidate_paths=candidate_paths,
                    staged_bank_path=staged_bank_path,
                    subject=subject,
                    absolute_deadline_monotonic=absolute_deadline_monotonic,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed and preserve slot checkpoints.
                collision_report = {
                    "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
                    "subject": subject,
                    "status": "BLOCKED",
                    "candidate_decisions": {},
                    "finding_counts": {"P1": 1},
                    "findings": [
                        {
                            "severity": "P1",
                            "code": "semantic_collision_board_exception",
                            "message": str(exc)[:800],
                        }
                    ],
                    "activation_allowed": False,
                    "activation_implication": "does_not_authorize_activation",
                }
            collision_report = write_semantic_collision_board(
                collision_report,
                root=artifact_root,
                apply=apply,
            )

        for report in ready_reports:
            item_id = str(report.get("item_id") or "")
            steps = list(report.get("steps") or [])
            collision_step = _collision_step(collision_report, item_id=item_id)
            steps.append(collision_step)
            report["steps"] = steps
            ledger = _attempt_ledger_for_report(
                root=root,
                artifact_root=artifact_root,
                staged_bank_path=staged_bank_path,
                report=report,
                max_attempts=max_attempts_per_slot,
                apply=apply,
            )
            decision = str(collision_step.get("status") or "")
            if decision == "COLLISION":
                report["status"] = "WORKFLOW_COLLISION_REJECTED"
                report["pending_stage"] = {}
                if ledger is not None:
                    ledger.clear_pending_stage_checkpoint(outcome="semantic_collision_rejected")
                    collision_path = Path(str(collision_report.get("semantic_collision_json_path") or ""))
                    if collision_path and not collision_path.is_absolute():
                        collision_path = artifact_root / collision_path
                    ledger.set_resume_rejection_path(str(collision_path))
                    report["content_attempt_state"] = ledger.snapshot()
                report["staging_allowed"] = False
                report["coverage_eligible"] = False
                report.update(_refresh_workflow_identity(report))
                continue
            if decision != "PASS":
                report["status"] = (
                    "INTERRUPTED_DEADLINE"
                    if collision_report.get("status") == "INTERRUPTED_DEADLINE"
                    else "WORKFLOW_BLOCKED_COLLISION_REVIEW"
                )
                report["interrupted_before_stage"] = (
                    "semantic_collision_review"
                    if report["status"] == "INTERRUPTED_DEADLINE"
                    else ""
                )
                report["staging_allowed"] = False
                report["coverage_eligible"] = False
                report.update(_refresh_workflow_identity(report))
                continue
            collision_binding = {
                "semantic_collision_json_path": str(
                    collision_report.get("semantic_collision_json_path") or ""
                ),
                "semantic_collision_json_sha256": str(
                    collision_report.get("semantic_collision_json_sha256") or ""
                ),
                "candidate_set_sha256": str(collision_report.get("candidate_set_sha256") or ""),
                "base_staged_bank_sha256": str(
                    collision_report.get("base_staged_bank_sha256") or ""
                ),
                "base_staged_snapshot_sha256": str(
                    collision_report.get("base_staged_snapshot_sha256") or ""
                ),
                "collision_decision": dict(collision_step.get("decision") or {}),
            }
            if ledger is not None and any(
                not collision_binding.get(key)
                for key in (
                    "semantic_collision_json_path",
                    "semantic_collision_json_sha256",
                    "candidate_set_sha256",
                    "base_staged_bank_sha256",
                    "base_staged_snapshot_sha256",
                    "collision_decision",
                )
            ):
                report["status"] = "WORKFLOW_BLOCKED_COLLISION_RECEIPT_INVALID"
                report["staging_allowed"] = False
                report["coverage_eligible"] = False
                report.update(_refresh_workflow_identity(report))
                continue
            if ledger is not None:
                checkpoint = ledger.pending_stage_checkpoint() or {}
                ledger.save_pending_stage_checkpoint(
                    {
                        **checkpoint,
                        "item_id": item_id,
                        "candidate_path": str((report.get("pending_stage") or {}).get("candidate_path") or ""),
                        "staging_decision_path": str((report.get("pending_stage") or {}).get("staging_decision_path") or ""),
                        "pending_stage": dict(report.get("pending_stage") or {}),
                        "steps": list(report.get("steps") or []),
                        "collision_required": True,
                        "collision_reviewed": True,
                        **collision_binding,
                    }
                )
            try:
                _require_stage_budget(absolute_deadline_monotonic, "stage_candidate")
                pending_stage = report.get("pending_stage") or {}
                collision_stage_kwargs = (
                    {
                        "semantic_collision_receipt_path": Path(
                            collision_binding["semantic_collision_json_path"]
                        ),
                        "semantic_collision_receipt_sha256": collision_binding[
                            "semantic_collision_json_sha256"
                        ],
                    }
                    if collision_binding["semantic_collision_json_path"]
                    and collision_binding["semantic_collision_json_sha256"]
                    else {}
                )
                staged_receipt = build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=Path(str(pending_stage.get("candidate_path") or "")),
                    staging_decision_path=Path(str(pending_stage.get("staging_decision_path") or "")),
                    staged_bank_path=staged_bank_path,
                    subject=subject,
                    apply=apply,
                    **collision_stage_kwargs,
                )
                report["steps"].append(
                    _step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path")
                )
                report["staged_receipt"] = staged_receipt
                report["status"] = (
                    "WORKFLOW_STAGED"
                    if staged_receipt.get("status") in {"STAGED_WRITABLE", "ALREADY_STAGED"}
                    else str(staged_receipt.get("status") or "WORKFLOW_BLOCKED_STAGING")
                )
                if ledger is not None:
                    ledger.clear_pending_stage_checkpoint(outcome=report["status"])
                    ledger.set_resume_rejection_path("")
                    report["content_attempt_state"] = ledger.snapshot()
            except WorkflowDeadlineInterrupted as exc:
                blocked_reason = blocked_reason or "batch_runtime_budget_exhausted_during_serial_staging"
                report["status"] = "INTERRUPTED_DEADLINE"
                report["interrupted_before_stage"] = exc.stage
            except Exception as exc:  # noqa: BLE001 - preserve checkpoint for a recoverable serial retry.
                pending_stage = report.get("pending_stage") or {}
                staged_receipt = _blocked_stage_receipt(
                    root=root,
                    artifact_root=artifact_root,
                    candidate_path=Path(str(pending_stage.get("candidate_path") or "")),
                    staging_decision_path=Path(
                        str(pending_stage.get("staging_decision_path") or "")
                    ),
                    staged_bank_path=staged_bank_path,
                    item_id=item_id,
                    subject=subject,
                    error=exc,
                    apply=apply,
                )
                report["steps"].append(
                    _step("stage_candidate", staged_receipt, path_key="stage_receipt_json_path")
                )
                report["staged_receipt"] = staged_receipt
                report["status"] = "WORKFLOW_BLOCKED_STAGE_EXCEPTION"
            report["staging_allowed"] = report.get("status") == "WORKFLOW_STAGED"
            report["coverage_eligible"] = report.get("status") == "WORKFLOW_STAGED"
            report.update(_refresh_workflow_identity(report))

    slot_reports = [
        write_slot_production_workflow_report(report, root=artifact_root, apply=apply)
        for report in slot_reports
    ]

    staged_count = sum(1 for report in slot_reports if report.get("status") == "WORKFLOW_STAGED")
    failed_count = sum(1 for report in slot_reports if report.get("status") != "WORKFLOW_STAGED")
    skipped_count = len(generation_plan_paths) - len(slot_reports)
    if blocked_reason:
        status = "BATCH_PARTIAL_BUDGET_EXHAUSTED"
    elif failed_count:
        status = "BATCH_COMPLETED_WITH_FAILURES"
    else:
        status = "BATCH_COMPLETED"

    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    batch_id_input = "|".join([
        created_at,
        json.dumps([str(path) for path in selected_plans], ensure_ascii=False, sort_keys=True),
        json.dumps([report.get("workflow_id") for report in slot_reports], ensure_ascii=False, sort_keys=True),
        status,
    ])
    return {
        "schema_version": "2026-07-23.codex-admin.batch-production-workflow.v1",
        "batch_id": "BATCH-" + hashlib.sha256(batch_id_input.encode("utf-8")).hexdigest()[:12],
        "created_at": created_at,
        "subject": subject,
        "status": status,
        "blocked_reason": blocked_reason,
        "requested_plan_count": len(generation_plan_paths),
        "selected_plan_count": len(selected_plans),
        "executed_slot_count": len(slot_reports),
        "staged_slot_count": staged_count,
        "failed_slot_count": failed_count,
        "skipped_slot_count": skipped_count,
        "max_attempts_per_slot": max_attempts_per_slot,
        "generation_batch_size": generation_batch_size,
        "parallel_workers": parallel_workers,
        "parallel_execution_enabled": generation_batch_size <= 1 and parallel_workers > 1 and not blocked_reason,
        "max_runtime_seconds": max_runtime_seconds,
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "absolute_deadline_monotonic": absolute_deadline_monotonic,
        "semantic_collision_status": collision_report.get("status"),
        "semantic_collision_json_path": collision_report.get("semantic_collision_json_path"),
        "semantic_collision_transport_attempts": collision_report.get("transport_attempts") or [],
        "staged_bank_path": _relative(root, staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path),
        "artifact_root": _relative(root, artifact_root),
        "slot_workflows": [
            {
                "workflow_id": report.get("workflow_id"),
                "status": report.get("status"),
                "attempt_count": report.get("attempt_count"),
                "elapsed_seconds": report.get("elapsed_seconds"),
                "item_id": report.get("item_id"),
                "generation_plan_path": report.get("generation_plan_path"),
                "workflow_json_path": report.get("workflow_json_path"),
                "workflow_markdown_path": report.get("workflow_markdown_path"),
                "blocking_codes": _workflow_blocking_codes(report),
            }
            for report in slot_reports
        ],
        "blocking_code_counts": dict(
            sorted(
                Counter(
                    code
                    for report in slot_reports
                    for code in _workflow_blocking_codes(report)
                ).items()
            )
        ),
        "staging_allowed": staged_count > 0 and failed_count == 0 and not blocked_reason,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def render_batch_production_workflow_markdown(report: dict[str, Any]) -> str:
    slot_lines = [
        f"| {slot.get('workflow_id', '')} | {slot.get('status', '')} | {slot.get('attempt_count', '')} | {slot.get('elapsed_seconds', '')} | {slot.get('item_id', '')} | {', '.join(slot.get('blocking_codes') or [])} | {slot.get('workflow_json_path', '')} |"
        for slot in report.get("slot_workflows") or []
    ]
    if not slot_lines:
        slot_lines.append("| | | | | | | |")
    return f"""# Batch Production Workflow

Status: `{report.get('status')}`

Batch ID: `{report.get('batch_id')}`

Created At: {report.get('created_at')}

Requested Plans: {report.get('requested_plan_count')}

Executed Slots: {report.get('executed_slot_count')}

Staged Slots: {report.get('staged_slot_count')}

Failed Slots: {report.get('failed_slot_count')}

Skipped Slots: {report.get('skipped_slot_count')}

Blocked Reason: `{report.get('blocked_reason')}`

Activation Implication: `{report.get('activation_implication')}`

Blocking Code Counts: `{json.dumps(report.get('blocking_code_counts') or {}, ensure_ascii=False, sort_keys=True)}`

## Slot Workflows

| Workflow | Status | Attempts | Seconds | Item | Blocking Codes | Report |
|---|---|---:|---:|---|---|---|
{chr(10).join(slot_lines)}
"""


def write_batch_production_workflow_report(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    batch_id = str(report.get("batch_id") or "BATCH-unknown")
    markdown_rel = Path("docs/system/admin_reports/workflows") / f"{datetime.now(timezone.utc).date()}-{batch_id}.md"
    json_rel = Path("data/admin/workflows") / f"{batch_id}.json"
    result = {
        **report,
        "batch_markdown_path": str(markdown_rel),
        "batch_json_path": str(json_rel),
        "batch_write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    _atomic_write_text(markdown_path, render_batch_production_workflow_markdown(report))
    result["batch_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    _atomic_write_text(
        json_path,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    result["batch_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result
