from __future__ import annotations

import sqlite3
import uuid
from collections import Counter, defaultdict
from typing import Any

from . import (
    agents,
    db,
    evolution,
    flow_nodes,
    internal_agents,
    mastery_v2_adapter,
    planner,
)


class SessionClosureStateMachine:
    """v2 close-state seam; business closure still lives in close_learning_session."""

    statuses = db.SESSION_CLOSURE_STATUSES

    @staticmethod
    def status_for_summary(summary: dict[str, Any]) -> str:
        if summary.get("missing_question_ids"):
            return "blocked"
        if summary.get("pending_attempt_ids"):
            return "waiting_ai"
        if summary.get("missing_analysis_attempt_ids"):
            return "blocked"
        if summary.get("unusable_evidence_attempt_ids"):
            return "blocked"
        return "planned"

    @classmethod
    def is_terminal(cls, closure_status: str | None) -> bool:
        return closure_status in {"blocked", "planned", "closed"}


def _contract_metadata(agent_key: str) -> dict[str, str]:
    role = internal_agents.INTERNAL_AGENT_ROLES[agent_key]
    contract = internal_agents.load_contract(role["contract_key"])
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    return {
        "prompt_version_id": contract.get("prompt_version_id", ""),
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path) if prompt_path.exists() else "",
        "response_schema_version": contract.get("response_schema_version", ""),
        "response_schema_sha256": db._digest_json(contract),
    }


def _record_internal_agent_run(
    conn: sqlite3.Connection,
    *,
    agent_key: str,
    engine_type: str,
    session_id: str,
    phase: str,
    trigger: str,
    input_refs: dict[str, Any],
    status: str = "accepted",
    confidence: float = 1.0,
    output: dict[str, Any] | None = None,
    validation_errors: list[str] | None = None,
    error_reason: str = "",
) -> dict[str, Any]:
    metadata = _contract_metadata(agent_key)
    return db.record_agent_run(
        conn,
        agent_key=agent_key,
        engine_type=engine_type,
        session_id=session_id,
        phase=phase,
        trigger=trigger,
        input_refs=input_refs,
        status=status,
        confidence=confidence,
        output=output or {},
        validation_errors=validation_errors or [],
        error_reason=error_reason,
        commit=False,
        **metadata,
    )


def _record_agent_handoff(
    conn: sqlite3.Connection,
    run: dict[str, Any],
    *,
    phase: str,
    target_node_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    attempt_ids: list[str] | None = None,
    next_action: str = "",
    mastery_decision: str = "",
    child_message: dict[str, Any] | None = None,
    audit_reason: str = "",
    accepted: bool = True,
) -> dict[str, Any]:
    handoff_id = f"AH-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into agent_handoffs(
          id, agent_run_id, agent_key, session_id, phase,
          target_node_ids_json, question_ids_json, attempt_ids_json,
          next_action, mastery_decision, child_message_json, audit_reason,
          accepted, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            handoff_id,
            run["id"],
            run["agent_key"],
            run.get("session_id"),
            phase,
            db.json_dump(target_node_ids or []),
            db.json_dump(question_ids or []),
            db.json_dump(attempt_ids or []),
            next_action,
            mastery_decision,
            db.json_dump(child_message or {}),
            audit_reason,
            1 if accepted else 0,
            db.now_iso(),
        ),
    )
    return {
        "id": handoff_id,
        "agent_run_id": run["id"],
        "agent_key": run["agent_key"],
        "session_id": run.get("session_id"),
        "phase": phase,
    }


def _record_session_step(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    run: dict[str, Any],
    phase: str,
    step_type: str,
    payload: dict[str, Any],
    status: str = "active",
) -> dict[str, Any]:
    step_id = f"SS-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into session_steps(
          id, session_id, agent_run_id, phase, step_type, payload_json, status, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            step_id,
            session_id,
            run["id"],
            phase,
            step_type,
            db.json_dump(payload),
            status,
            db.now_iso(),
        ),
    )
    return {
        "id": step_id,
        "session_id": session_id,
        "agent_run_id": run["id"],
        "phase": phase,
        "step_type": step_type,
    }


def _record_evidence_package_node(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    evidence_package: dict[str, Any],
) -> dict[str, Any]:
    readiness = "ready" if evidence_package.get("analysis_ready") else "pending"
    run = _record_internal_agent_run(
        conn,
        agent_key="session_orchestrator_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="evidence_package",
        trigger=f"session_complete:{session_id}:{readiness}",
        input_refs={
            "session_id": session_id,
            "attempt_ids": [item["attempt_id"] for item in evidence_package.get("attempts", [])],
        },
        status="accepted" if evidence_package.get("analysis_ready") else "pending",
        confidence=1.0 if evidence_package.get("analysis_ready") else 0.0,
        output={
            "object_type": evidence_package.get("object_type"),
            "analysis_ready": bool(evidence_package.get("analysis_ready")),
            "attempt_count": evidence_package.get("attempt_count", 0),
            "unclear_reason": evidence_package.get("unclear_reason", ""),
        },
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="evidence_package",
        step_type="package_submission_evidence",
        payload=evidence_package,
        status="complete" if evidence_package.get("analysis_ready") else "pending",
    )
    return run


def _record_answer_analysis_node(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    answer_package: dict[str, Any],
) -> dict[str, Any]:
    run = _record_internal_agent_run(
        conn,
        agent_key="answer_analysis_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="answer_analysis_package",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "attempt_ids": [item["attempt_id"] for item in answer_package.get("attempts", [])],
        },
        output={
            "object_type": answer_package.get("object_type"),
            "analysis_count": answer_package.get("analysis_count", 0),
            "process_gap_count": sum(1 for item in answer_package.get("attempts", []) if item.get("process_gap")),
        },
    )
    _record_agent_handoff(
        conn,
        run,
        phase="answer_analysis_package",
        target_node_ids=sorted({item["node_id"] for item in answer_package.get("attempts", [])}),
        question_ids=[item["question_id"] for item in answer_package.get("attempts", [])],
        attempt_ids=[item["attempt_id"] for item in answer_package.get("attempts", [])],
        next_action="bind_to_graph",
        audit_reason="Answer Analysis node normalized final answer, reasoning, alternatives, and process gaps.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="answer_analysis_package",
        step_type="normalize_answer_analysis",
        payload=answer_package,
        status="complete",
    )
    return run


def validate_transition(phase: str, next_action: str) -> str:
    return internal_agents.transition_next_phase(phase, next_action)


def _closure_response(
    conn: sqlite3.Connection,
    *,
    result: dict[str, Any],
    session: dict[str, Any],
    include_agent_reports: bool,
) -> dict[str, Any]:
    response = {**result, "session": session}
    if include_agent_reports:
        response["agent_reports"] = agents.build_agent_reports(conn)
    return response


def _existing_closed_result(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    include_agent_reports: bool,
) -> dict[str, Any] | None:
    session = db.get_learning_session(conn, session_id)
    if session.get("status") != "closed":
        return None
    result = dict(session.get("closure_result") or {})
    if not result:
        return None
    return _closure_response(
        conn,
        result=result,
        session=session,
        include_agent_reports=include_agent_reports,
    )


def _decision_from_attempts(attempts: list[dict[str, Any]]) -> tuple[str, str, str, bool]:
    if (
        len(attempts) >= 2
        and all(attempt["result"] == "correct" and (attempt.get("explanation_score") or 0) >= 2 for attempt in attempts)
    ):
        return "mastered_for_now", "mastered", "Closed with repeated correct answer and reasoning evidence.", True
    if attempts and all(attempt["result"] == "correct" and (attempt.get("explanation_score") or 0) >= 2 for attempt in attempts):
        return "stable_understanding", "repaired_not_mastered", "Closed with one strong evidence point; schedule later retest before mastery.", True
    if any(attempt.get("blocking_evidence") for attempt in attempts):
        return "prerequisite_blocked", "prerequisite_blocked", "Closed with blocking prerequisite evidence.", False
    if any(attempt["result"] in {"wrong", "partial"} for attempt in attempts):
        return "current_node_weak", "repaired_not_mastered", "Closed with weak or partial evidence.", True
    return "not_enough_evidence", "pending_analysis", "Closed without enough analyzed evidence.", False


def _record_close_audit(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    run = db.record_agent_run(
        conn,
        agent_key="session_orchestrator_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="session_close",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "graded_attempt_ids": summary.get("graded_attempt_ids", []),
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
        },
        prompt_version_id="2026-07-05.session-orchestrator.prompt.v1",
        status="accepted",
        confidence=1.0,
        output={
            "closure_status": result.get("closure_status"),
            "next_plan_id": (result.get("next_plan") or {}).get("id"),
            "evolution_event_id": (result.get("evolution_event") or {}).get("id"),
        },
        commit=False,
    )
    return run


# DEPRECATED (M2.5-5c): the 6-态 -> v2 decision-label mapping. Replaced by
# mastery_v2_adapter.judge_v2_node via _v2_unified_judgment_for_evaluation
# (proposal §2.1/§2.5 — the unified verdict drives stored decisions). Kept
# temporarily for rollback; physical removal in the M2.5 cleanup commit.
def _mastery_decision_from_status(evaluation: dict[str, Any]) -> tuple[str, str, str, bool]:
    mastery_state = str(evaluation.get("mastery_state") or "")
    can_advance = bool(evaluation.get("can_advance"))
    if mastery_state == "blocked":
        return "prerequisite_blocked", "prerequisite_blocked", evaluation.get("why") or "Blocked prerequisite evidence.", True
    if mastery_state == "unstable":
        return "current_node_weak", "repaired_not_mastered", evaluation.get("why") or "Current node evidence is weak.", True
    if mastery_state == "emerging":
        return "basic_understanding", "repaired_not_mastered", evaluation.get("why") or "Evidence is emerging; confirmation is still required.", True
    if mastery_state == "likely_stable" and not can_advance:
        return "stable_understanding", "repaired_not_mastered", evaluation.get("why_not_advance") or "Likely stable, but transfer confirmation is still required.", True
    if mastery_state == "stable" and can_advance:
        return "stretch_ready", "mastered", evaluation.get("why") or "Repeated varied evidence is stable.", True

    status = evaluation.get("overall_status", "unknown")
    if status == "blocked":
        return "prerequisite_blocked", "prerequisite_blocked", "Blocked prerequisite evidence.", True
    if status == "weak":
        return "current_node_weak", "repaired_not_mastered", "Current node evidence is weak.", True
    if status == "basic":
        return "basic_understanding", "repaired_not_mastered", "Basic evidence exists; consolidate before mastery.", True
    if status == "stable":
        return "stable_understanding", "repaired_not_mastered", "Stable evidence exists; use transfer before mastery.", True
    if status == "stretch_ready":
        return "stable_understanding", "repaired_not_mastered", "Repeated direct evidence exists; confirm transfer before mastery.", True
    return "not_enough_evidence", "pending_analysis", "Not enough analyzed evidence.", False


def _v2_unified_judgment_for_evaluation(
    conn: sqlite3.Connection,
    *,
    evaluation: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Run the unified mastery judgment for one v2 node evaluation (M2.5-5c).

    Feeds mastery_v2_adapter.judge_v2_node: the node's evidence rows (this
    session's usable attempts + prior 90-day window, built by flow_nodes),
    the node's applied mastery_decisions history (rows already covering this
    session's attempts excluded — the current session's row is written after
    judging), and the stored learner_node_status as current_status.
    """
    node_id = evaluation["node_id"]
    session_id = summary["session_id"]
    session_attempt_ids = set(
        str(item) for item in (evaluation.get("evidence_attempt_ids") or []) if item
    )
    evidence_rows = flow_nodes.build_v2_evidence_rows(
        conn,
        node_id=node_id,
        session_id=session_id,
        summary=summary,
    )
    decision_history: list[dict[str, Any]] = []
    for raw in conn.execute(
        """
        select id, node_id, decision, new_status_code, decision_payload_json,
               source_attempt_ids_json, created_at, applied
        from mastery_decisions
        where node_id = ?
          and applied = 1
          and created_at <= ?
        order by created_at, id
        """,
        (node_id, db.now_iso()),
    ).fetchall():
        row = dict(raw)
        source_ids = set(
            str(item) for item in (db.json_load(row.get("source_attempt_ids_json"), []) or [])
            if item
        )
        if session_attempt_ids & source_ids:
            continue
        decision_history.append(row)
    stored = conn.execute(
        "select status_code from learner_node_status where node_id = ?",
        (node_id,),
    ).fetchone()
    current_status = str(stored["status_code"]) if stored else None
    return mastery_v2_adapter.judge_v2_node(
        evidence_rows=evidence_rows,
        decision_history=decision_history,
        current_status=current_status,
        reason_base=str(
            evaluation.get("why_not_advance") or evaluation.get("why") or ""
        ),
    )


def _evaluation_payload_with_verdict(
    evaluation: dict[str, Any],
    judgment: dict[str, Any],
) -> dict[str, Any]:
    """The legacy evaluation payload plus the unified-verdict trace.

    The payload keeps the 6-态 / overall_status fields as interpretation
    metadata (proposal §2.1 point 2 / §2.5); the unified verdict (5-value +
    §2.3 counter + signals) is recorded alongside so mastery_decisions rows
    stay replayable for the counter derivation.
    """
    payload = _evaluation_payload(evaluation)
    payload["unified_verdict"] = {
        "verdict": judgment["verdict"],
        "reason_code": judgment["reason_code"],
        "decision": judgment["decision"],
        "closure_result": judgment["closure_result"],
        "cd_counter": judgment["counter"],
        "previous_cd_counter": judgment["previous_counter"],
        "recheck": judgment["recheck"],
        "downgrade": judgment["downgrade"],
        "reason": judgment["reason"],
        "attrs": judgment["attrs"],
    }
    return payload


def _planner_signal_from_evaluation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    intervention = str(payload.get("selected_intervention") or payload.get("intervention_need") or "")
    confirmation_type = str(payload.get("confirmation_type") or "")
    gap_type = str(payload.get("gap_type") or "")
    can_advance = bool(payload.get("can_advance", False))
    need_prerequisite_probe = (
        confirmation_type == "prerequisite_probe"
        or intervention == "prerequisite_repair"
        or gap_type == "prerequisite_gap"
    )
    need_same_structure = confirmation_type == "same_structure_retest"
    need_teaching_before_next = (
        not can_advance
        and intervention not in {"confirmation_only", "request_clearer_evidence"}
    )
    notes = []
    if payload.get("mastery_state") in {"emerging", "likely_stable"}:
        notes.append("Evidence is promising but does not yet prove stable varied transfer.")
    if need_prerequisite_probe:
        notes.append("Planner must verify prerequisite evidence before same-node drilling.")
    if need_same_structure:
        notes.append("Planner should confirm the same structure with changed surface values or context.")
    if need_teaching_before_next:
        notes.append("Targeted teaching/scaffold is needed before asking for more evidence.")
    if not notes:
        notes.append("Planner may use confirmation evidence without adding a new teaching step.")
    return {
        "preferred_question_kinds": planner._preferred_kinds_for_evaluation_payload(payload),
        "avoid_question_kinds": ["bare_calculation", "answer_only", "low_age_mechanical_drill"],
        "need_same_structure": need_same_structure,
        "need_prerequisite_probe": need_prerequisite_probe,
        "need_teaching_before_next": need_teaching_before_next,
        "evidence_policy_notes": notes,
    }


def _record_graph_binding_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    graph_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_package = graph_package or flow_nodes.build_graph_binding_package(conn, session_id, summary)
    bindings = graph_package.get("bindings", [])
    issues = graph_package.get("issues", [])
    run = _record_internal_agent_run(
        conn,
        agent_key="graph_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="graph_binding",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
            "question_ids": [binding["question_id"] for binding in bindings],
        },
        status="accepted" if not issues else "rejected",
        confidence=1.0 if not issues else 0.0,
        output={
            "graph_binding": graph_package,
            "bound_node_ids": graph_package.get("bound_node_ids", []),
            "issue_count": len(issues),
        },
        validation_errors=[f"node_binding_mismatch:{issue['attempt_id']}" for issue in issues],
    )
    _record_agent_handoff(
        conn,
        run,
        phase="graph_binding",
        target_node_ids=graph_package.get("bound_node_ids", []),
        question_ids=[binding["question_id"] for binding in bindings],
        attempt_ids=[binding["attempt_id"] for binding in bindings],
        next_action="evaluate_bound_evidence",
        audit_reason="Graph Agent bound analyzed attempts to question nodes and rollback candidates.",
        accepted=not issues,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="graph_binding",
        step_type="graph_bind_attempts",
        payload=graph_package,
        status="complete" if not issues else "blocked",
    )
    return run


def _evaluation_payload(evaluation: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "2026-07-08.evaluation-diagnosis.v2",
        "threshold_policy_version": "2026-07-08.single-strong-is-not-stable.v1",
        "node_id": evaluation.get("node_id", ""),
        "overall_status": evaluation.get("overall_status", "unknown"),
        "mastery_state": evaluation.get("mastery_state", "insufficient_evidence"),
        "gap_type": evaluation.get("gap_type", "evidence_gap"),
        "intervention_need": evaluation.get("intervention_need", "request_clearer_evidence"),
        "confirmation_needed": bool(evaluation.get("confirmation_needed", True)),
        "confirmation_type": evaluation.get("confirmation_type", "same_structure_retest"),
        "can_advance": bool(evaluation.get("can_advance", False)),
        "why": evaluation.get("why", ""),
        "why_not_advance": evaluation.get("why_not_advance", ""),
        "evidence_attempt_ids": evaluation.get("evidence_attempt_ids", []),
        "evidence_count": evaluation.get("evidence_count", 0),
        "strong_evidence_count": evaluation.get("strong_evidence_count", 0),
        "weak_evidence_count": evaluation.get("weak_evidence_count", 0),
        "dimension_statuses": {
            "concept": evaluation.get("concept_status", "unknown"),
            "model": evaluation.get("model_status", "unknown"),
            "calculation": evaluation.get("calculation_status", "unknown"),
            "expression": evaluation.get("expression_status", "unknown"),
            "transfer": evaluation.get("transfer_status", "unknown"),
        },
        "weakest_dimension": (evaluation.get("unstable_dimensions") or [""])[0],
        "unstable_dimensions": evaluation.get("unstable_dimensions", []),
        "process_gaps": evaluation.get("process_gaps", []),
        "question_kind_coverage": evaluation.get("question_kinds", []),
        "transfer_coverage": bool(evaluation.get("has_transfer_evidence", False)),
        "form_diversity": bool(evaluation.get("has_form_diversity", False)),
        "dominant_error_tags": evaluation.get("dominant_error_tags", []),
        "target_error_tags": evaluation.get("dominant_error_tags", []),
        "target_dimensions": evaluation.get("unstable_dimensions", []),
        "required_question_family": evaluation.get("confirmation_type", "same_structure_retest"),
        "selected_intervention": evaluation.get("intervention_need", "request_clearer_evidence"),
        "strategy_shift_needed": bool(evaluation.get("strategy_shift_needed", False)),
        "repeated_gap_count": evaluation.get("repeated_gap_count", 0),
        "confidence": 0.9 if evaluation.get("evidence_attempt_ids") else 0.0,
    }
    payload["planner_signal"] = _planner_signal_from_evaluation_payload(payload)
    return payload


def _evaluation_decisions_for_summary(
    conn: sqlite3.Connection,
    summary: dict[str, Any],
    mastery_package: dict[str, Any] | None = None,
    judgments: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if mastery_package is None:
        mastery_package = flow_nodes.build_mastery_evaluation_package(conn, summary["session_id"], summary)
    evaluations = sorted(
        mastery_package.get("evaluations", []),
        key=lambda item: item.get("node_id", ""),
    )
    decisions = []
    for evaluation in evaluations:
        judgment = (
            judgments.get(evaluation.get("node_id", ""))
            if judgments
            else _v2_unified_judgment_for_evaluation(conn, evaluation=evaluation, summary=summary)
        )
        payload = _evaluation_payload_with_verdict(evaluation, judgment)
        decisions.append({
            "node_id": evaluation.get("node_id", ""),
            "decision": judgment["decision"],
            "closure_result": judgment["closure_result"],
            "applied": judgment["applied"],
            "reason": judgment["reason"],
            "evidence_attempt_ids": evaluation.get("evidence_attempt_ids", []),
            "error_dimensions": {
                tag: 1 for tag in evaluation.get("dominant_error_tags", [])
            },
            "decision_payload": payload,
        })
    return decisions


def _status_update_from_judgment(
    evaluation: dict[str, Any],
    judgment: dict[str, Any],
) -> dict[str, Any] | None:
    """learner_node_status update driven by the unified judgment (M2.5-5c).

    Replaces the old 6-态 -> status reducer (_status_update_from_evaluation,
    whose insufficient_evidence -> C branch was the misjudgment point,
    proposal §2.1 point 3 / §2.5). NO_CHANGE verdicts return None — never
    written ("没测过 ≠ 薄弱": no row / keep-as-is).
    """
    if not judgment["applied"]:
        return None
    status_code = judgment["status"]
    return {
        "node_id": evaluation["node_id"],
        "status_code": status_code,
        "latest_score": float(evaluation.get("evidence_strength") or 0.0),
        "can_explain": status_code in {"A", "B"},
        "evidence_attempt_ids": evaluation.get("evidence_attempt_ids", []),
        "status_reason": f"Evaluation Agent: {judgment['reason']}",
    }


def _apply_evaluation_node_statuses(
    conn: sqlite3.Connection,
    *,
    evaluations: list[dict[str, Any]],
    judgments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for evaluation in evaluations:
        update = _status_update_from_judgment(
            evaluation, judgments.get(evaluation.get("node_id", ""), {})
        )
        if update is None:
            continue
        conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain, evidence_attempt_ids_json,
              status_reason, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                update["node_id"],
                update["status_code"],
                update["latest_score"],
                1 if update["can_explain"] else 0,
                db.json_dump(update["evidence_attempt_ids"]),
                update["status_reason"],
                db.now_iso(),
            ),
        )
        updates.append(update)
    return updates


def _maintenance_summary_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    attempt_ids: list[str],
) -> dict[str, Any]:
    summary = db.session_completion_summary(conn, session_id)
    usable_ids = []
    missing_analysis_ids = []
    unusable_ids = []
    pending_ids = []
    for attempt_id in attempt_ids:
        attempt = db.get_attempt(conn, attempt_id)
        if attempt["grading_status"] == "pending_review":
            pending_ids.append(attempt_id)
        elif not db.is_valid_answer_analysis(attempt.get("answer_analysis")):
            missing_analysis_ids.append(attempt_id)
        elif db.EvidenceUsePolicy.is_usable_attempt(conn, attempt):
            usable_ids.append(attempt_id)
        else:
            unusable_ids.append(attempt_id)
    summary.update({
        "graded_attempt_ids": [
            attempt_id for attempt_id in attempt_ids
            if db.get_attempt(conn, attempt_id)["grading_status"] == "graded"
        ],
        "structurally_analyzed_attempt_ids": [
            attempt_id for attempt_id in attempt_ids
            if db.is_valid_answer_analysis(db.get_attempt(conn, attempt_id).get("answer_analysis"))
        ],
        "usable_attempt_ids": usable_ids,
        "analyzed_attempt_ids": usable_ids,
        "pending_attempt_ids": pending_ids,
        "missing_analysis_attempt_ids": missing_analysis_ids,
        "unusable_evidence_attempt_ids": unusable_ids,
        "missing_or_unusable_evidence_attempt_ids": missing_analysis_ids + unusable_ids,
        "analyzed": len(usable_ids),
        "usable": len(usable_ids),
        "pending": len(pending_ids),
    })
    return summary


def _record_evaluation_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    event: dict[str, Any] | None = None,
    mastery_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = event or {}
    mastery_package = mastery_package or flow_nodes.build_mastery_evaluation_package(conn, session_id, summary)
    evaluations = sorted(
        mastery_package.get("evaluations", []),
        key=lambda item: item.get("node_id", ""),
    )
    # M2.5-5c: unified mastery judgment (proposal §2.2/§2.3). The legacy
    # 6-态 -> decision/status reducers (_mastery_decision_from_status /
    # _status_update_from_evaluation, incl. the insufficient_evidence -> C
    # misjudgment point) are replaced by mastery_v2_adapter.judge_v2_node,
    # which composes decide_verdict (R1-R6 + window AGG C1-C6) ->
    # transition_status (§2.3 table, counter from the node's
    # mastery_decisions). Only the *judgment* changed; the persistence below
    # (mastery_decisions insert + learner_node_status upsert) is untouched,
    # and NO_CHANGE verdicts are never stored (applied=False).
    judgments = {
        evaluation["node_id"]: _v2_unified_judgment_for_evaluation(
            conn, evaluation=evaluation, summary=summary
        )
        for evaluation in evaluations
    }
    decisions = _evaluation_decisions_for_summary(conn, summary, mastery_package, judgments)
    status_updates = _apply_evaluation_node_statuses(
        conn,
        evaluations=evaluations,
        judgments=judgments,
    )
    run = _record_internal_agent_run(
        conn,
        agent_key="evaluation_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="evaluation_decision",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
            "evolution_event_id": event.get("id"),
        },
        output={
            "mastery_evaluation": mastery_package,
            "decisions": decisions,
            "node_statuses": status_updates,
            "evolution_status": event.get("status"),
        },
    )
    _record_agent_handoff(
        conn,
        run,
        phase="evaluation_decision",
        target_node_ids=[decision["node_id"] for decision in decisions],
        attempt_ids=summary.get("analyzed_attempt_ids", []),
        next_action="plan_next_learning_round",
        mastery_decision=",".join(decision["decision"] for decision in decisions),
        audit_reason="Evaluation Agent converted analyzed evidence into node-level mastery decisions.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="evaluation_decision",
        step_type="evaluate_node_status",
        payload=mastery_package,
    )
    for evaluation in evaluations:
        judgment = judgments[evaluation["node_id"]]
        if not judgment["applied"]:
            # NO_CHANGE is never stored (proposal §2.1/§2.3: 没测过 ≠ 薄弱).
            continue
        existing = conn.execute(
            """
            select 1
            from mastery_decisions
            where session_id = ?
              and node_id = ?
              and agent_run_id = ?
            limit 1
            """,
            (session_id, evaluation["node_id"], run["id"]),
        ).fetchone()
        if existing:
            continue
        decision_row = db.record_mastery_decision(
            conn,
            session_id=session_id,
            node_id=evaluation["node_id"],
            decision=judgment["decision"],
            closure_result=judgment["closure_result"],
            evidence_attempt_ids=evaluation.get("evidence_attempt_ids", []),
            agent_run_id=run["id"],
            applied=True,
            reason=judgment["reason"],
            decision_payload=_evaluation_payload_with_verdict(evaluation, judgment),
            commit=False,
        )
        # Record the unified stored status on the row so the §2.3 counter
        # derivation (mastery_v2_adapter.decision_history_events) can read it.
        conn.execute(
            "update mastery_decisions set new_status_code = ? where id = ?",
            (judgment["status"] or "", decision_row["id"]),
        )
    return run


def _record_planner_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    event: dict[str, Any],
    next_plan: dict[str, Any],
) -> dict[str, Any]:
    run = _record_internal_agent_run(
        conn,
        agent_key="planner_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="planner_transition",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "evolution_event_id": event.get("id"),
            "evolution_status": event.get("status"),
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
        },
        output={
            "next_plan_id": next_plan.get("id"),
            "plan_policy_version": next_plan.get("plan_policy_version", next_plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION)),
            "planner_policy_version": next_plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION),
            "task_count": len(next_plan.get("tasks", [])),
            "round_size": next_plan.get("round_size", len(next_plan.get("tasks", []))),
            "primary_target_node_id": next_plan.get("primary_target_node_id", ""),
            "round_structure": next_plan.get("round_structure") or planner.round_structure(next_plan.get("tasks", [])),
            "planning_signal_refs": next_plan.get("planning_signal_refs") or planner.planning_signal_refs(next_plan.get("tasks", [])),
            "quality_gates": next_plan.get("quality_gates") or planner.quality_gates(conn, next_plan.get("tasks", [])),
            "confidence": next_plan.get("confidence", 1.0),
            "task_types": [task.get("task_type") for task in next_plan.get("tasks", [])],
            "node_ids": [task.get("node_id") for task in next_plan.get("tasks", [])],
            "question_ids": [task.get("question_id") for task in next_plan.get("tasks", [])],
        },
    )
    _record_agent_handoff(
        conn,
        run,
        phase="planner_transition",
        target_node_ids=[task.get("node_id") for task in next_plan.get("tasks", []) if task.get("node_id")],
        question_ids=[task.get("question_id") for task in next_plan.get("tasks", []) if task.get("question_id")],
        attempt_ids=summary.get("analyzed_attempt_ids", []),
        next_action="prepare_child_safe_feedback",
        audit_reason="Planner Agent selected the next graph-bound task group from evaluated evidence.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="planner_transition",
        step_type="generate_next_plan",
        payload={"next_plan_id": next_plan.get("id"), "task_count": len(next_plan.get("tasks", []))},
    )
    return run


def _record_teaching_decision_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    mastery_package: dict[str, Any],
    next_plan: dict[str, Any],
) -> dict[str, Any]:
    teaching_decision = flow_nodes.build_teaching_decision_package(
        conn,
        session_id,
        mastery_package,
        next_plan,
    )
    run = _record_internal_agent_run(
        conn,
        agent_key="session_orchestrator_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="teaching_decision",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
            "next_plan_id": next_plan.get("id"),
        },
        output={"teaching_decision": teaching_decision},
    )
    _record_agent_handoff(
        conn,
        run,
        phase="teaching_decision",
        target_node_ids=[teaching_decision["target_node"]] if teaching_decision.get("target_node") else [],
        attempt_ids=summary.get("analyzed_attempt_ids", []),
        next_action=teaching_decision.get("next_action", ""),
        audit_reason="Teaching Decision node selected explain, repair, consolidate, stretch, or move-next.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="teaching_decision",
        step_type="select_teaching_move",
        payload=teaching_decision,
        status="complete",
    )
    return run


def _child_message_for_close(
    *,
    summary: dict[str, Any],
    event: dict[str, Any],
    next_plan: dict[str, Any],
    child_teaching_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if child_teaching_package:
        feedback = str(child_teaching_package.get("child_feedback") or "这一组已经看完，下一组也准备好了。")
        if "复盘" not in feedback:
            feedback = f"这一组已经复盘完成。{feedback}"
        message = {
            "child_title": str(child_teaching_package.get("child_title") or "这一组完成"),
            "child_feedback": feedback,
            "review_points": child_teaching_package.get("review_points", []),
            "coach_points": child_teaching_package.get("coach_points", []),
            "child_action": f"先看下面的复盘提示；准备好了点“{child_teaching_package.get('next_action_label', '看讲解，开始下一组')}”。",
            "next_action_label": str(child_teaching_package.get("next_action_label") or "看讲解，开始下一组"),
            "next_task_count": int(child_teaching_package.get("next_task_count") or 0),
        }
        internal_agents.validate_child_safe_message(message)
        return message
    weak = bool(event.get("created_question_ids")) or event.get("status") == "evolved"
    if weak:
        feedback = "这一组已经复盘完成，可以离开。下一组会先处理刚才最不稳的一步，再用新题确认。"
    elif summary.get("analyzed", 0):
        feedback = "这一组已经复盘完成，可以离开。你的步骤和检验会作为下一组安排的依据。"
    else:
        feedback = "答案已经保存，可以离开。系统会继续看你的步骤，再安排下一组。"
    task_count = len(next_plan.get("tasks", []))
    message = {
        "child_title": "这一组完成",
        "child_feedback": feedback,
        "child_action": f"先休息一下；准备好了点“看讲解，开始下一组”，会看到 {task_count} 个新任务。",
        "next_action_label": "看讲解，开始下一组",
    }
    internal_agents.validate_child_safe_message(message)
    return message


def _record_teaching_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: dict[str, Any],
    event: dict[str, Any],
    next_plan: dict[str, Any],
    mastery_package: dict[str, Any],
    teaching_decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    child_teaching_package = flow_nodes.build_child_teaching_package(
        conn,
        session_id,
        summary,
        mastery_package,
        teaching_decision,
        next_plan,
    )
    child_message = _child_message_for_close(
        summary=summary,
        event=event,
        next_plan=next_plan,
        child_teaching_package=child_teaching_package,
    )
    run = _record_internal_agent_run(
        conn,
        agent_key="teaching_agent",
        engine_type="deterministic",
        session_id=session_id,
        phase="teaching_step",
        trigger=f"session_complete:{session_id}",
        input_refs={
            "session_id": session_id,
            "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
            "evolution_event_id": event.get("id"),
            "next_plan_id": next_plan.get("id"),
        },
        output={
            "child_message": child_message,
            "child_teaching_package": child_teaching_package,
            "teaching_decision": teaching_decision,
            "next_plan_task_count": len(next_plan.get("tasks", [])),
            "uses_internal_analysis": True,
            "child_safe": True,
        },
    )
    _record_agent_handoff(
        conn,
        run,
        phase="teaching_step",
        target_node_ids=[task.get("node_id") for task in next_plan.get("tasks", []) if task.get("node_id")],
        question_ids=[task.get("question_id") for task in next_plan.get("tasks", []) if task.get("question_id")],
        attempt_ids=summary.get("analyzed_attempt_ids", []),
        next_action="show_child_handoff",
        child_message=child_message,
        audit_reason="Teaching Agent produced child-safe completion feedback from analyzed evidence.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=run,
        phase="teaching_step",
        step_type="child_safe_handoff",
        payload={"child_message": child_message, "child_teaching_package": child_teaching_package},
    )
    return run, child_message


def close_learning_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    include_agent_reports: bool = True,
) -> dict[str, Any]:
    existing = _existing_closed_result(
        conn,
        session_id,
        include_agent_reports=include_agent_reports,
    )
    if existing is not None:
        return existing

    session = db.get_learning_session(conn, session_id)
    if session.get("status") == "closing":
        existing = _existing_closed_result(
            conn,
            session_id,
            include_agent_reports=include_agent_reports,
        )
        if existing is not None:
            return existing

    summary = db.session_completion_summary(conn, session_id)
    evidence_package = flow_nodes.build_evidence_package(conn, session_id, summary)
    evidence_run = _record_evidence_package_node(
        conn,
        session_id=session_id,
        evidence_package=evidence_package,
    )
    if summary["missing_question_ids"]:
        result = {
            "session_id": session_id,
            "closure_status": "blocked",
            "blocked_reason": "incomplete_session",
            "attempt_summary": summary,
            "next_plan": None,
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="active",
            closure_status="blocked",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )
    if summary["pending_attempt_ids"]:
        result = {
            "session_id": session_id,
            "closure_status": "waiting_ai",
            "blocked_reason": "ai_review_pending",
            "blocked_attempts": summary["pending_attempt_ids"],
            "attempt_summary": summary,
            "next_plan": None,
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="closing",
            closure_status="waiting_ai",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )
    if summary["missing_analysis_attempt_ids"]:
        result = {
            "session_id": session_id,
            "closure_status": "blocked",
            "blocked_reason": "answer_analysis_missing",
            "blocked_attempts": summary["missing_analysis_attempt_ids"],
            "attempt_summary": summary,
            "next_plan": None,
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="closing",
            closure_status="blocked",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )
    if summary.get("unusable_evidence_attempt_ids"):
        result = {
            "session_id": session_id,
            "closure_status": "blocked",
            "blocked_reason": "evidence_not_usable",
            "blocked_attempts": summary["unusable_evidence_attempt_ids"],
            "attempt_summary": summary,
            "evidence_package": evidence_package,
            "next_plan": None,
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="closing",
            closure_status="blocked",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )

    claimed = conn.execute(
        """
        update learning_sessions
        set status = 'closing',
            closure_status = 'evolving'
        where id = ?
          and (
            status = 'active'
            or (status = 'closing' and closure_status in ('waiting_ai', 'blocked'))
          )
        """,
        (session_id,),
    )
    if claimed.rowcount != 1:
        existing = _existing_closed_result(
            conn,
            session_id,
            include_agent_reports=include_agent_reports,
        )
        if existing is not None:
            return existing
        session = db.get_learning_session(conn, session_id)
        result = {
            "session_id": session_id,
            "closure_status": session.get("closure_status", "blocked"),
            "blocked_reason": "session_close_already_in_progress",
            "attempt_summary": summary,
            "next_plan": None,
        }
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )

    answer_package = flow_nodes.build_answer_analysis_package(conn, session_id, summary)
    answer_run = _record_answer_analysis_node(conn, session_id=session_id, answer_package=answer_package)
    graph_package = flow_nodes.build_graph_binding_package(conn, session_id, summary)
    graph_run = _record_graph_binding_agent(
        conn,
        session_id=session_id,
        summary=summary,
        graph_package=graph_package,
    )
    if graph_run["status"] != "accepted":
        result = {
            "session_id": session_id,
            "closure_status": "blocked",
            "blocked_reason": "graph_binding_failed",
            "attempt_summary": summary,
            "graph_binding": graph_package,
            "blocked_attempts": [issue["attempt_id"] for issue in graph_package.get("issues", [])],
            "next_plan": None,
            "agent_chain": [
                {"agent_key": "session_orchestrator_agent", "run_id": evidence_run["id"], "phase": "evidence_package"},
                {"agent_key": "answer_analysis_agent", "run_id": answer_run["id"], "phase": "answer_analysis_package"},
                {"agent_key": "graph_agent", "run_id": graph_run["id"], "phase": "graph_binding"},
            ],
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="closing",
            closure_status="blocked",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )

    mastery_package = flow_nodes.build_mastery_evaluation_package(conn, session_id, summary)
    evaluation_run = _record_evaluation_agent(
        conn,
        session_id=session_id,
        summary=summary,
        mastery_package=mastery_package,
    )
    event = evolution.run_evolution(
        conn,
        trigger=f"session_complete:{session_id}",
        session_id=session_id,
        allow_model_question_candidate=False,
        commit=False,
    )
    try:
        next_plan = planner.generate_next_plan(conn, title="本组后下一轮学习", commit=False)
    except planner.PlannerPlanError as exc:
        planner_run = db.record_agent_run(
            conn,
            agent_key="planner_agent",
            engine_type="deterministic",
            session_id=session_id,
            phase="planner_transition",
            trigger=f"session_complete:{session_id}",
            input_refs={
                "session_id": session_id,
                "evolution_event_id": event.get("id"),
                "evolution_status": event.get("status"),
                "analyzed_attempt_ids": summary.get("analyzed_attempt_ids", []),
            },
            prompt_version_id="2026-07-05.planner-transition.prompt.v1",
            status="error",
            confidence=0.0,
            output={
                "closure_status": "blocked",
                "blocked_reason": "planner_quality_gate_failed",
                "quality_gates": exc.quality_gates,
                "task_count": exc.task_count,
                "planner_policy_version": planner.PLANNER_POLICY_VERSION,
            },
            error_reason=str(exc),
            commit=False,
        )
        result = {
            "session_id": session_id,
            "closure_status": "blocked",
            "blocked_reason": "planner_quality_gate_failed",
            "attempt_summary": summary,
            "reviewed_attempts": summary["graded_attempt_ids"],
            "blocked_attempts": [],
            "evidence_package": evidence_package,
            "answer_analysis": answer_package,
            "graph_binding": graph_package,
            "mastery_evaluation": mastery_package,
            "evolution_event": event,
            "next_plan": None,
            "planner_error": {
                "message": str(exc),
                "quality_gates": exc.quality_gates,
                "task_count": exc.task_count,
            },
            "agent_chain": [
                {"agent_key": "session_orchestrator_agent", "run_id": evidence_run["id"], "phase": "evidence_package"},
                {"agent_key": "answer_analysis_agent", "run_id": answer_run["id"], "phase": "answer_analysis_package"},
                {"agent_key": "graph_agent", "run_id": graph_run["id"], "phase": "graph_binding"},
                {"agent_key": "evaluation_agent", "run_id": evaluation_run["id"], "phase": "evaluation_decision"},
                {"agent_key": "self_evolution_agent", "event_id": event.get("id"), "phase": "session_close"},
                {"agent_key": "planner_agent", "run_id": planner_run["id"], "phase": "planner_transition"},
            ],
        }
        session = db.update_session_closure_state(
            conn,
            session_id=session_id,
            status="closing",
            closure_status="blocked",
            closure_result=result,
            commit=False,
        )
        return _closure_response(
            conn,
            result=result,
            session=session,
            include_agent_reports=include_agent_reports,
        )
    planner_run = _record_planner_agent(conn, session_id=session_id, summary=summary, event=event, next_plan=next_plan)
    teaching_decision_run = _record_teaching_decision_agent(
        conn,
        session_id=session_id,
        summary=summary,
        mastery_package=mastery_package,
        next_plan=next_plan,
    )
    teaching_decision = teaching_decision_run["output"]["teaching_decision"]
    teaching_run, child_message = _record_teaching_agent(
        conn,
        session_id=session_id,
        summary=summary,
        event=event,
        next_plan=next_plan,
        mastery_package=mastery_package,
        teaching_decision=teaching_decision,
    )
    result = {
        "session_id": session_id,
        "closure_status": "planned",
        "attempt_summary": summary,
        "reviewed_attempts": summary["graded_attempt_ids"],
        "blocked_attempts": [],
        "evidence_package": evidence_package,
        "answer_analysis": answer_package,
        "graph_binding": graph_package,
        "mastery_evaluation": mastery_package,
        "teaching_decision": teaching_decision,
        "evolution_event": event,
        "next_plan": next_plan,
        "child_message": child_message,
        "agent_chain": [
            {"agent_key": "session_orchestrator_agent", "run_id": evidence_run["id"], "phase": "evidence_package"},
            {"agent_key": "answer_analysis_agent", "run_id": answer_run["id"], "phase": "answer_analysis_package"},
            {"agent_key": "graph_agent", "run_id": graph_run["id"], "phase": "graph_binding"},
            {"agent_key": "evaluation_agent", "run_id": evaluation_run["id"], "phase": "evaluation_decision"},
            {"agent_key": "self_evolution_agent", "event_id": event.get("id"), "phase": "session_close"},
            {"agent_key": "planner_agent", "run_id": planner_run["id"], "phase": "planner_transition"},
            {"agent_key": "session_orchestrator_agent", "run_id": teaching_decision_run["id"], "phase": "teaching_decision"},
            {"agent_key": "teaching_agent", "run_id": teaching_run["id"], "phase": "teaching_step"},
        ],
    }
    close_run = _record_close_audit(conn, session_id=session_id, summary=summary, result=result)
    _record_agent_handoff(
        conn,
        close_run,
        phase="session_close",
        target_node_ids=[task.get("node_id") for task in next_plan.get("tasks", []) if task.get("node_id")],
        question_ids=[task.get("question_id") for task in next_plan.get("tasks", []) if task.get("question_id")],
        attempt_ids=summary.get("analyzed_attempt_ids", []),
        next_action="close_session_with_next_plan",
        child_message=child_message,
        audit_reason="Session Orchestrator closed the completed group after all internal agents finished.",
        accepted=True,
    )
    _record_session_step(
        conn,
        session_id=session_id,
        run=close_run,
        phase="session_close",
        step_type="close_with_next_plan",
        payload={
            "closure_status": result["closure_status"],
            "next_plan_id": next_plan.get("id"),
            "evolution_event_id": event.get("id"),
        },
        status="closed",
    )
    result["agent_chain"].append({
        "agent_key": "session_orchestrator_agent",
        "run_id": close_run["id"],
        "phase": "session_close",
    })
    session = db.update_session_closure_state(
        conn,
        session_id=session_id,
        status="closed",
        closure_status="planned",
        closure_result=result,
        next_plan_id=next_plan["id"],
        closed_at=db.now_iso(),
        commit=False,
    )
    return _closure_response(
        conn,
        result=result,
        session=session,
        include_agent_reports=include_agent_reports,
    )


def run_maintenance_evolution(conn: sqlite3.Connection, *, trigger: str = "manual") -> dict[str, Any]:
    """Codex/operator maintenance path for non-active child-session evidence.

    Normal child learning groups close through close_learning_session(). This
    wrapper keeps the legacy local maintenance API behind the orchestrator
    boundary instead of letting the HTTP layer call the evolution reducer
    directly.
    """
    run = db.record_agent_run(
        conn,
        agent_key="session_orchestrator_agent",
        engine_type="deterministic",
        session_id=None,
        phase="maintenance_evolution",
        trigger=f"maintenance_evolution:{trigger}",
        input_refs={"trigger": trigger},
        prompt_version_id="2026-07-05.session-orchestrator.prompt.v1",
        status="accepted",
        confidence=1.0,
        output={"maintenance_action": "run_evolution"},
        commit=False,
    )
    session_attempt_ids: dict[str, list[str]] = {}
    for row in conn.execute(
            """
            select id, session_id
            from attempts
            where processed_evolution_event_id is null
              and grading_status = 'graded'
              and evidence_status = 'active'
            order by session_id, created_at, id
            """
        ).fetchall():
        session_attempt_ids.setdefault(row["session_id"], []).append(row["id"])
    evaluation_runs = []
    for session_id, attempt_ids in session_attempt_ids.items():
        summary = _maintenance_summary_for_session(conn, session_id, attempt_ids)
        if summary.get("analyzed_attempt_ids"):
            mastery_package = flow_nodes.build_mastery_evaluation_package(conn, session_id, summary)
            evaluation_runs.append(_record_evaluation_agent(
                conn,
                session_id=session_id,
                summary=summary,
                mastery_package=mastery_package,
            ))
    event = evolution.run_evolution(
        conn,
        trigger=trigger,
        allow_model_question_candidate=False,
        commit=False,
    )
    event.setdefault("after", {})["maintenance_evaluation_run_ids"] = [run["id"] for run in evaluation_runs]
    try:
        if event["status"] in {"evolved", "state_updated", "question_review_rejected"}:
            next_plan = planner.generate_next_plan(conn, title="进化后下一次学习", commit=False)
        else:
            next_plan = planner.latest_or_create_plan(conn, commit=False)
    except planner.PlannerPlanError as exc:
        db.record_agent_run(
            conn,
            agent_key="planner_agent",
            engine_type="hybrid",
            session_id=None,
            phase="maintenance_evolution",
            trigger=f"maintenance_plan:{trigger}",
            input_refs={
                "orchestrator_run_id": run["id"],
                "evolution_event_id": event["id"],
                "evolution_status": event["status"],
            },
            prompt_version_id="2026-07-05.planner-transition.prompt.v1",
            status="error",
            confidence=0.0,
            output={
                "blocked_reason": "planner_quality_gate_failed",
                "quality_gates": exc.quality_gates,
                "task_count": exc.task_count,
                "planner_policy_version": planner.PLANNER_POLICY_VERSION,
            },
            error_reason=str(exc),
            commit=False,
        )
        return {
            **event,
            "next_plan": None,
            "blocked_reason": "planner_quality_gate_failed",
            "planner_error": {
                "message": str(exc),
                "quality_gates": exc.quality_gates,
                "task_count": exc.task_count,
            },
            "agent_reports": agents.build_agent_reports(conn),
        }
    db.record_agent_run(
        conn,
        agent_key="planner_agent",
        engine_type="hybrid",
        session_id=None,
        phase="maintenance_evolution",
        trigger=f"maintenance_plan:{trigger}",
        input_refs={
            "orchestrator_run_id": run["id"],
            "evolution_event_id": event["id"],
            "evolution_status": event["status"],
        },
        prompt_version_id="2026-07-05.planner-transition.prompt.v1",
        status="accepted",
        confidence=1.0,
        output={
            "next_plan_id": next_plan.get("id"),
            "plan_policy_version": next_plan.get("plan_policy_version", next_plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION)),
            "planner_policy_version": next_plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION),
            "task_count": len(next_plan.get("tasks", [])),
            "round_size": next_plan.get("round_size", len(next_plan.get("tasks", []))),
            "primary_target_node_id": next_plan.get("primary_target_node_id", ""),
            "round_structure": next_plan.get("round_structure") or planner.round_structure(next_plan.get("tasks", [])),
            "planning_signal_refs": next_plan.get("planning_signal_refs") or planner.planning_signal_refs(next_plan.get("tasks", [])),
            "quality_gates": next_plan.get("quality_gates") or planner.quality_gates(conn, next_plan.get("tasks", [])),
            "confidence": next_plan.get("confidence", 1.0),
        },
        commit=False,
    )
    return {**event, "next_plan": next_plan, "agent_reports": agents.build_agent_reports(conn)}
