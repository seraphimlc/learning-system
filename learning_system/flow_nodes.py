from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from typing import Any

from . import db


SCHEMA_VERSION = "2026-07-05.flow-nodes.v1"

MASTER_STATUSES = {"unknown", "blocked", "weak", "basic", "stable", "stretch_ready"}
TEACHING_ACTIONS = {
    "request_clearer_evidence",
    "explain",
    "retry_same_node",
    "repair_prerequisite",
    "consolidate",
    "stretch",
    "move_next_node",
    "close_session",
}

COMPARISON_TO_DIMENSION = {
    "final_answer": "final_answer_status",
    "model_or_relation": "model_or_relation_status",
    "steps": "steps_status",
    "symbols_units": "symbols_units_status",
    "check_or_explanation": "check_status",
}

STATUS_STRENGTH = {
    "matched": 4,
    "alternative_valid": 4,
    "unclear": 2,
    "missing": 1,
    "incorrect": 0,
}

DIMENSION_TO_GAP_TYPE = {
    "final_answer": "calculation_symbol_gap",
    "model_or_relation": "model_gap",
    "steps": "procedure_gap",
    "symbols_units": "symbol_expression_gap",
    "check_or_explanation": "metacognitive_gap",
}

ERROR_TAG_TO_GAP_TYPE = {
    "concept_confusion": "concept_gap",
    "modeling_or_reading": "model_gap",
    "calculation_or_symbol": "calculation_symbol_gap",
    "process_habit": "metacognitive_gap",
    "visual_spatial": "model_gap",
}

GAP_TO_INTERVENTION = {
    "prerequisite_gap": "prerequisite_repair",
    "concept_gap": "reteach_essence",
    "model_gap": "model_scaffold",
    "procedure_gap": "procedure_scaffold",
    "calculation_symbol_gap": "symbol_contrast",
    "symbol_expression_gap": "symbol_contrast",
    "transfer_gap": "transfer_bridge",
    "metacognitive_gap": "metacognitive_check",
    "evidence_gap": "request_clearer_evidence",
    "no_gap_observed": "confirmation_only",
}

TRANSFER_CONFIRMATION_KINDS = {
    "transfer_retest",
    "stretch_transfer",
    "two_method_compare",
    "representation",
    "model_selection",
    "reverse_reasoning",
    "boundary_case",
    "missing_condition",
}

STRONG_ANALYSIS_STATUSES = {"matched", "alternative_valid"}

RESULT_LABELS = {
    "correct": "基本通过",
    "partial": "还差一步",
    "wrong": "需要重做",
}


def _child_safe_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()[:limit]
    replacements = {
        "模型": "关系",
        "图谱": "学习安排",
        "节点": "这一块",
        "Agent": "",
        "agent": "",
        "Codex": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _attempts_for_summary(conn: sqlite3.Connection, session_id: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    analyzed_ids = set(summary.get("usable_attempt_ids") or summary.get("analyzed_attempt_ids", []))
    return [
        attempt for attempt in db.attempts_for_session(conn, session_id)
        if attempt["id"] in analyzed_ids
    ]


def _question_for_attempt(conn: sqlite3.Connection, attempt: dict[str, Any]) -> dict[str, Any]:
    return db.get_question(conn, attempt["question_id"])


def _node_name_for_attempt(conn: sqlite3.Connection, attempt: dict[str, Any]) -> str:
    row = conn.execute("select name from graph_nodes where id = ?", (attempt["node_id"],)).fetchone()
    return str(row["name"] if row else "这道题")


def _attachments_for_attempt(conn: sqlite3.Connection, attempt_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": attachment["id"],
            "kind": attachment["kind"],
            "content_type": attachment["content_type"],
            "byte_size": attachment["byte_size"],
            "sha256": attachment["sha256"],
        }
        for attachment in db.attachments_for_attempt(conn, attempt_id)
    ]


def _vision_meta(attempt: dict[str, Any]) -> dict[str, Any]:
    review_meta = attempt.get("review_meta") if isinstance(attempt.get("review_meta"), dict) else {}
    vision = review_meta.get("vision") if isinstance(review_meta.get("vision"), dict) else {}
    if not vision:
        return {
            "ocr_text": "",
            "ocr_confidence": 0.0,
            "image_quality": "not_provided",
        }
    status = str(vision.get("status") or "")
    confidence = float(vision.get("confidence") or 0.0)
    return {
        "ocr_text": str(vision.get("transcript") or "")[:1200],
        "ocr_confidence": confidence,
        "image_quality": "usable" if status == "usable" and confidence >= 0.62 else "unclear",
    }


def build_evidence_package(conn: sqlite3.Connection, session_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    attempts = db.attempts_for_session(conn, session_id)
    packaged_attempts = []
    for attempt in attempts:
        attachments = _attachments_for_attempt(conn, attempt["id"])
        vision = _vision_meta(attempt)
        sources = []
        if str(attempt.get("answer_raw") or "").strip():
            sources.append("typed_answer")
        if any(attachment["kind"] == "answer_photo" for attachment in attachments):
            sources.append("answer_photo")
        if vision["ocr_text"]:
            sources.append("photo_ocr")
        if attempt["grading_status"] == "pending_review":
            analysis_status = "pending_ai"
        elif db.is_valid_answer_analysis(attempt.get("answer_analysis")):
            analysis_status = "ready"
        elif attempt.get("answer_analysis"):
            analysis_status = "invalid_analysis"
        else:
            analysis_status = "missing_analysis"
        if attempt["id"] in set(summary.get("unusable_evidence_attempt_ids", [])):
            evidence_use_status = "unusable"
        elif attempt["id"] in set(summary.get("usable_attempt_ids") or summary.get("analyzed_attempt_ids", [])):
            evidence_use_status = "usable"
        elif attempt["grading_status"] == "pending_review":
            evidence_use_status = "pending"
        else:
            evidence_use_status = "blocked"
        packaged_attempts.append({
            "attempt_id": attempt["id"],
            "question_id": attempt["question_id"],
            "node_id": attempt["node_id"],
            "typed_answer": str(attempt.get("answer_raw") or "")[:1200],
            "attachments": attachments,
            "ocr_text": vision["ocr_text"],
            "ocr_confidence": vision["ocr_confidence"],
            "image_quality": vision["image_quality"],
            "evidence_sources": sources or ["empty"],
            "grading_status": attempt["grading_status"],
            "analysis_status": analysis_status,
            "evidence_use_status": evidence_use_status,
        })

    analysis_ready = (
        not summary.get("missing_question_ids")
        and not summary.get("pending_attempt_ids")
        and not summary.get("missing_analysis_attempt_ids")
        and not summary.get("unusable_evidence_attempt_ids")
    )
    unclear_reason = ""
    if summary.get("missing_question_ids"):
        unclear_reason = "incomplete_session"
    elif summary.get("pending_attempt_ids"):
        unclear_reason = "pending_ai_review"
    elif summary.get("missing_analysis_attempt_ids"):
        unclear_reason = "answer_analysis_missing"
    elif summary.get("unusable_evidence_attempt_ids"):
        unclear_reason = "evidence_not_usable"
    return {
        "object_type": "evidence_package",
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "analysis_ready": analysis_ready,
        "unclear_reason": unclear_reason,
        "attempt_count": len(packaged_attempts),
        "attempts": packaged_attempts,
    }


def _dimension_status(analysis: dict[str, Any], dimension: str) -> str:
    comparison = analysis.get("comparison") if isinstance(analysis.get("comparison"), list) else []
    statuses = [
        str(item.get("status") or "")
        for item in comparison
        if isinstance(item, dict) and item.get("dimension") == dimension
    ]
    if not statuses:
        return "missing"
    return min(statuses, key=lambda status: STATUS_STRENGTH.get(status, -1))


def build_answer_analysis_package(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    attempts = _attempts_for_summary(conn, session_id, summary)
    analyzed = []
    for attempt in attempts:
        analysis = attempt.get("answer_analysis") or {}
        statuses = {
            field: _dimension_status(analysis, dimension)
            for dimension, field in COMPARISON_TO_DIMENSION.items()
        }
        analyzed.append({
            "attempt_id": attempt["id"],
            "question_id": attempt["question_id"],
            "node_id": attempt["node_id"],
            "result": attempt["result"],
            "score_points": attempt["score_points"],
            "max_points": attempt["max_points"],
            "error_tags": attempt.get("error_tags", []),
            "explanation_score": attempt.get("explanation_score"),
            **statuses,
            "optimal_answer": str(analysis.get("optimal_answer") or "")[:500],
            "optimal_solution_steps": analysis.get("optimal_solution_steps", [])[:6],
            "child_answer_summary": str(analysis.get("child_answer_summary") or "")[:500],
            "alternative_solutions": analysis.get("alternative_solutions", [])[:4],
            "process_gap": str(analysis.get("process_gap") or "")[:500],
            "next_child_prompt": str(analysis.get("next_child_prompt") or "")[:360],
        })
    return {
        "object_type": "answer_analysis",
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "analysis_count": len(analyzed),
        "attempts": analyzed,
    }


def build_graph_binding_package(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    attempts = _attempts_for_summary(conn, session_id, summary)
    bindings = []
    issues = []
    for attempt in attempts:
        question = _question_for_attempt(conn, attempt)
        analysis = attempt.get("answer_analysis") or {}
        unstable_dimensions = [
            item.get("dimension")
            for item in analysis.get("comparison", [])
            if isinstance(item, dict) and item.get("status") in {"missing", "incorrect", "unclear"}
        ]
        if attempt["node_id"] != question["node_id"]:
            issues.append({
                "attempt_id": attempt["id"],
                "attempt_node_id": attempt["node_id"],
                "question_node_id": question["node_id"],
            })
        rollback_candidates = question.get("rollback_candidate_node_ids", [])
        bindings.append({
            "attempt_id": attempt["id"],
            "question_id": attempt["question_id"],
            "primary_node": attempt["node_id"],
            "secondary_nodes": question.get("secondary_node_ids", []),
            "evidence_dimension": list(dict.fromkeys([item for item in unstable_dimensions if item])),
            "prerequisite_suspects": rollback_candidates[:3] if attempt.get("blocking_evidence") else [],
            "rollback_candidates": rollback_candidates,
            "binding_confidence": 1.0 if attempt["node_id"] == question["node_id"] else 0.0,
            "binding_reason": "题目主节点、答案证据和候选回退链已绑定。" if attempt["node_id"] == question["node_id"] else "提交节点与题目主节点不一致。",
        })
    return {
        "object_type": "graph_binding",
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "bindings": bindings,
        "bound_node_ids": sorted({binding["primary_node"] for binding in bindings}),
        "issues": issues,
        "issue_count": len(issues),
    }


def _status_from_comparison(attempts: list[dict[str, Any]], dimensions: set[str]) -> str:
    statuses = []
    for attempt in attempts:
        analysis = attempt.get("answer_analysis") or {}
        comparison = analysis.get("comparison") if isinstance(analysis.get("comparison"), list) else []
        for item in comparison:
            if isinstance(item, dict) and item.get("dimension") in dimensions:
                statuses.append(item.get("status"))
    if any(status == "incorrect" for status in statuses):
        return "weak"
    if any(status in {"missing", "unclear"} for status in statuses):
        return "weak"
    if any(status in {"matched", "alternative_valid"} for status in statuses):
        return "stable"
    return "unknown"


def _analysis_items(attempt: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = attempt.get("answer_analysis") or {}
    comparison = analysis.get("comparison") if isinstance(analysis.get("comparison"), list) else []
    return [item for item in comparison if isinstance(item, dict)]


def _weak_dimensions_for_attempts(attempts: list[dict[str, Any]]) -> list[str]:
    dimensions: list[str] = []
    for attempt in attempts:
        for item in _analysis_items(attempt):
            if item.get("status") in {"missing", "incorrect", "unclear"}:
                dimension = str(item.get("dimension") or "")
                if dimension:
                    dimensions.append(dimension)
    return list(dict.fromkeys(dimensions))


def _has_strong_core_analysis(attempt: dict[str, Any]) -> bool:
    statuses_by_dimension: dict[str, list[str]] = {dimension: [] for dimension in COMPARISON_TO_DIMENSION}
    for item in _analysis_items(attempt):
        dimension = str(item.get("dimension") or "")
        if dimension in statuses_by_dimension:
            statuses_by_dimension[dimension].append(str(item.get("status") or ""))
    return all(
        statuses and all(status in STRONG_ANALYSIS_STATUSES for status in statuses)
        for statuses in statuses_by_dimension.values()
    )


def _question_kinds_for_attempts(conn: sqlite3.Connection, attempts: list[dict[str, Any]]) -> list[str]:
    kinds: list[str] = []
    for attempt in attempts:
        try:
            question = _question_for_attempt(conn, attempt)
        except KeyError:
            continue
        kind = str(question.get("kind") or "")
        if kind:
            kinds.append(kind)
    return list(dict.fromkeys(kinds))


def _primary_gap_type(
    *,
    attempts: list[dict[str, Any]],
    error_tags: Counter[str],
    weak_dimensions: list[str],
    has_blocking: bool,
) -> str:
    if has_blocking:
        return "prerequisite_gap"
    for tag, _ in error_tags.most_common():
        gap = ERROR_TAG_TO_GAP_TYPE.get(tag)
        if gap:
            return gap
    for dimension in weak_dimensions:
        gap = DIMENSION_TO_GAP_TYPE.get(dimension)
        if gap:
            return gap
    if any((attempt.get("explanation_score") or 0) < 2 for attempt in attempts):
        return "metacognitive_gap"
    return "no_gap_observed"


def _mastery_diagnosis(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    attempts: list[dict[str, Any]],
    ratio: float,
    has_blocking: bool,
    weak_result: bool,
    error_tags: Counter[str],
) -> dict[str, Any]:
    strong_attempts = [
        attempt for attempt in attempts
        if attempt["result"] == "correct"
        and (attempt.get("explanation_score") or 0) >= 2
        and _has_strong_core_analysis(attempt)
    ]
    weak_attempts = [
        attempt for attempt in attempts
        if attempt["result"] in {"wrong", "partial"}
        or (attempt.get("explanation_score") or 0) < 2
        or not _has_strong_core_analysis(attempt)
    ]
    weak_dimensions = _weak_dimensions_for_attempts(attempts)
    question_kinds = _question_kinds_for_attempts(conn, attempts)
    has_transfer_evidence = any(kind in TRANSFER_CONFIRMATION_KINDS for kind in question_kinds)
    has_form_diversity = len(question_kinds) >= 2
    process_gaps = [
        str((attempt.get("answer_analysis") or {}).get("process_gap") or "").strip()
        for attempt in attempts
        if str((attempt.get("answer_analysis") or {}).get("process_gap") or "").strip()
    ]
    gap_counter = Counter(process_gaps)
    repeated_gap_count = gap_counter.most_common(1)[0][1] if gap_counter else 0
    primary_gap = _primary_gap_type(
        attempts=attempts,
        error_tags=error_tags,
        weak_dimensions=weak_dimensions,
        has_blocking=has_blocking,
    )

    if has_blocking:
        mastery_state = "blocked"
    elif weak_result or ratio < 0.6 or weak_attempts:
        mastery_state = "unstable" if ratio < 0.6 or weak_result else "emerging"
    elif len(strong_attempts) >= 2 and has_transfer_evidence and has_form_diversity:
        mastery_state = "stable"
    elif len(strong_attempts) >= 2:
        mastery_state = "likely_stable"
    elif strong_attempts:
        mastery_state = "emerging"
    else:
        mastery_state = "insufficient_evidence"

    intervention_need = GAP_TO_INTERVENTION.get(primary_gap, "model_scaffold")
    strategy_shift_needed = repeated_gap_count >= 2 and primary_gap not in {"no_gap_observed", "evidence_gap"}
    if strategy_shift_needed and primary_gap != "prerequisite_gap":
        intervention_need = "prerequisite_repair" if any(error_tags.values()) else intervention_need

    if mastery_state == "stable":
        confirmation_type = "no_retest_needed"
    elif primary_gap == "prerequisite_gap" or intervention_need == "prerequisite_repair":
        confirmation_type = "prerequisite_probe"
    elif mastery_state in {"likely_stable", "emerging"} and not weak_attempts:
        confirmation_type = "near_transfer_retest"
    elif primary_gap in {"model_gap", "concept_gap", "transfer_gap"}:
        confirmation_type = "near_transfer_retest"
    else:
        confirmation_type = "same_structure_retest"

    can_advance = mastery_state == "stable"
    confirmation_needed = not can_advance
    return {
        "node_id": node_id,
        "mastery_state": mastery_state,
        "gap_type": primary_gap,
        "intervention_need": intervention_need,
        "confirmation_needed": confirmation_needed,
        "confirmation_type": confirmation_type,
        "can_advance": can_advance,
        "why": _child_safe_text(
            process_gaps[0] if process_gaps else (
                "已有跨形式稳定证据。" if can_advance else "现有证据还不足以证明已经稳定掌握。"
            ),
            360,
        ),
        "why_not_advance": "" if can_advance else _child_safe_text(
            "还需要一次同构或近迁移确认，避免把一次做对当成真正掌握。",
            220,
        ),
        "evidence_count": len(attempts),
        "strong_evidence_count": len(strong_attempts),
        "weak_evidence_count": len(weak_attempts),
        "question_kinds": question_kinds,
        "has_transfer_evidence": has_transfer_evidence,
        "has_form_diversity": has_form_diversity,
        "unstable_dimensions": weak_dimensions,
        "process_gaps": list(dict.fromkeys(process_gaps))[:3],
        "repeated_gap_count": repeated_gap_count,
        "strategy_shift_needed": strategy_shift_needed,
    }


def build_mastery_evaluation_package(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    attempts = _attempts_for_summary(conn, session_id, summary)
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        by_node[attempt["node_id"]].append(attempt)

    evaluations = []
    for node_id, node_attempts in sorted(by_node.items()):
        max_points = sum(float(attempt["max_points"]) for attempt in node_attempts)
        score = sum(float(attempt["score_points"]) for attempt in node_attempts)
        ratio = score / max_points if max_points else 0.0
        has_blocking = any(attempt.get("blocking_evidence") for attempt in node_attempts)
        can_explain = any((attempt.get("explanation_score") or 0) >= 2 for attempt in node_attempts)
        weak_result = any(attempt["result"] in {"wrong", "partial"} for attempt in node_attempts)
        if has_blocking:
            overall = "blocked"
        elif ratio >= 0.85 and can_explain and len(node_attempts) >= 2 and not weak_result:
            overall = "stretch_ready"
        elif ratio >= 0.85 and can_explain:
            overall = "basic"
        elif ratio >= 0.6:
            overall = "basic"
        else:
            overall = "weak"
        error_tags = Counter(tag for attempt in node_attempts for tag in attempt.get("error_tags", []))
        if overall == "blocked":
            recommended_direction = "repair_prerequisite"
        elif overall == "weak":
            recommended_direction = "explain_then_retry"
        elif overall == "basic":
            recommended_direction = "consolidate"
        elif overall == "stable":
            recommended_direction = "variant_transfer"
        else:
            recommended_direction = "stretch_or_move_next"
        diagnosis = _mastery_diagnosis(
            conn,
            node_id=node_id,
            attempts=node_attempts,
            ratio=ratio,
            has_blocking=has_blocking,
            weak_result=weak_result,
            error_tags=error_tags,
        )
        evaluations.append({
            "node_id": node_id,
            "overall_status": overall,
            "concept_status": _status_from_comparison(node_attempts, {"model_or_relation"}),
            "model_status": _status_from_comparison(node_attempts, {"model_or_relation", "steps"}),
            "calculation_status": _status_from_comparison(node_attempts, {"final_answer", "steps"}),
            "expression_status": _status_from_comparison(node_attempts, {"symbols_units", "check_or_explanation"}),
            "transfer_status": "stable" if overall in {"stable", "stretch_ready"} else ("weak" if weak_result else "unknown"),
            "evidence_strength": round(ratio, 2),
            "blocking_reason": "存在明确无法启动或前置断点证据。" if has_blocking else "",
            "dominant_error_tags": [tag for tag, _ in error_tags.most_common()],
            "evidence_attempt_ids": [attempt["id"] for attempt in node_attempts],
            "recommended_direction": recommended_direction,
            **diagnosis,
        })
    return {
        "object_type": "mastery_evaluation",
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "evaluations": evaluations,
    }


def build_teaching_decision_package(
    conn: sqlite3.Connection,
    session_id: str,
    mastery_package: dict[str, Any],
    next_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evaluations = mastery_package.get("evaluations", [])
    node_order = {
        row["id"]: int(row["sequence_band"])
        for row in conn.execute("select id, sequence_band from graph_nodes").fetchall()
    }

    def sort_key(evaluation: dict[str, Any]) -> tuple[int, int, str]:
        priority = {
            "blocked": 0,
            "weak": 1,
            "basic": 2,
            "stable": 3,
            "stretch_ready": 4,
            "unknown": 5,
        }.get(evaluation.get("overall_status", "unknown"), 5)
        return (priority, node_order.get(evaluation["node_id"], 999), evaluation["node_id"])

    target = sorted(evaluations, key=sort_key)[0] if evaluations else None
    if target is None:
        next_action = "request_clearer_evidence"
        target_node = ""
        task_type = "diagnostic"
        reason = "本轮没有可用的已分析证据。"
        family = "low_barrier_probe"
        feedback_type = "pending"
    else:
        target_node = target["node_id"]
        status = target["overall_status"]
        confirmation_type = str(target.get("confirmation_type") or "")
        intervention_need = str(target.get("intervention_need") or "")
        can_advance = bool(target.get("can_advance"))
        if status == "blocked" or confirmation_type == "prerequisite_probe" or intervention_need == "prerequisite_repair":
            next_action = "repair_prerequisite"
            task_type = "rollback"
            family = "prerequisite_repair"
            feedback_type = "repair"
        elif not can_advance and intervention_need in {"reteach_essence", "model_scaffold", "procedure_scaffold", "symbol_contrast", "metacognitive_check"}:
            next_action = "explain"
            task_type = "remediate" if confirmation_type != "near_transfer_retest" else "retest"
            family = confirmation_type or "same_node_reasoning_repair"
            feedback_type = "explain"
        elif not can_advance and confirmation_type in {"same_structure_retest", "near_transfer_retest"}:
            next_action = "consolidate"
            task_type = "retest"
            family = confirmation_type
            feedback_type = "consolidate"
        elif status == "weak":
            next_action = "explain"
            task_type = "remediate"
            family = "same_node_reasoning_repair"
            feedback_type = "explain"
        elif status == "basic":
            next_action = "consolidate"
            task_type = "retest"
            family = "near_transfer_consolidation"
            feedback_type = "consolidate"
        elif status == "stable" and can_advance:
            next_action = "stretch"
            task_type = "retest"
            family = "variant_or_transfer"
            feedback_type = "stretch"
        else:
            next_action = "move_next_node"
            task_type = "learn"
            family = "next_core_node"
            feedback_type = "move_on"
        reason = target.get("blocking_reason") or target.get("recommended_direction") or "根据本轮证据选择下一步。"

    return {
        "object_type": "teaching_decision",
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "next_action": next_action,
        "target_node": target_node,
        "task_type": task_type,
        "reason": reason,
        "required_question_family": family,
        "need_new_question": bool(target and target.get("overall_status") in {"blocked", "weak", "basic"}),
        "child_feedback_type": feedback_type,
        "session_should_close": True,
        "next_plan_id": (next_plan or {}).get("id"),
    }


def _review_points_for_attempts(conn: sqlite3.Connection, attempts: list[dict[str, Any]]) -> list[dict[str, str]]:
    points = []
    for position, attempt in enumerate(attempts, start=1):
        analysis = attempt.get("answer_analysis") or {}
        label = RESULT_LABELS.get(str(attempt.get("result") or ""), "已保存")
        node_name = _node_name_for_attempt(conn, attempt)
        gap = (
            analysis.get("process_gap")
            or analysis.get("child_answer_summary")
            or "这题还需要把关键步骤和理由写清楚。"
        )
        prompt = analysis.get("next_child_prompt")
        text = _child_safe_text(gap, 180)
        if prompt:
            text = f"{text} 下一次先写：{_child_safe_text(prompt, 150)}"
        points.append({
            "title": _child_safe_text(f"第{position}题：{node_name} · {label}", 80),
            "text": _child_safe_text(text, 340),
        })
    return points


def build_child_teaching_package(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
    mastery_package: dict[str, Any],
    teaching_decision: dict[str, Any],
    next_plan: dict[str, Any],
) -> dict[str, Any]:
    attempts = _attempts_for_summary(conn, session_id, summary)
    weak_attempts = [
        attempt for attempt in attempts
        if attempt["result"] in {"wrong", "partial"} or (attempt.get("explanation_score") or 0) < 2
    ]
    focus_attempt = weak_attempts[0] if weak_attempts else (attempts[0] if attempts else None)
    analysis = focus_attempt.get("answer_analysis", {}) if focus_attempt else {}
    question = _question_for_attempt(conn, focus_attempt) if focus_attempt else {}
    if focus_attempt and focus_attempt["result"] == "correct" and not analysis.get("process_gap"):
        headline = "这一组做得比较稳"
        summary_text = "系统看过你的步骤和解释，下一组会换一种角度确认是否真的稳定。"
    elif teaching_decision.get("next_action") == "repair_prerequisite":
        headline = "先补一块前置"
        summary_text = "这一组显示有一块准备知识不够稳，下一组先补这一小步。"
    else:
        headline = "先修最关键的一步"
        summary_text = str(analysis.get("process_gap") or "这一组有一步还需要说清楚方法为什么成立。")[:220]
    coach_points = []
    if question.get("answer_format"):
        coach_points.append({
            "title": "下一题先照这个格式写",
            "text": _child_safe_text(question["answer_format"], 180),
        })
    if analysis.get("teaching_explanation"):
        coach_points.append({
            "title": "你可以这样想",
            "text": _child_safe_text(analysis["teaching_explanation"], 420),
        })
    if analysis.get("next_child_prompt"):
        coach_points.append({
            "title": "下一题前先提醒自己",
            "text": _child_safe_text(analysis["next_child_prompt"], 220),
        })
    next_action = teaching_decision.get("next_action")
    if next_action == "stretch":
        next_action_label = "开始拔高题"
    elif next_action == "move_next_node":
        next_action_label = "学习下一步"
    else:
        next_action_label = "看讲解，开始下一组"
    return {
        "child_title": _child_safe_text(headline, 80),
        "child_feedback": _child_safe_text(summary_text, 240),
        "review_points": _review_points_for_attempts(conn, attempts),
        "coach_points": coach_points[:3],
        "next_action_label": next_action_label,
        "next_task_count": len(next_plan.get("tasks", [])),
    }
