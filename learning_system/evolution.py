from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from . import db, model_router, question_bank


MIN_QUESTION_CANDIDATE_CONFIDENCE = 0.75
EVOLUTION_PROPOSAL_PROMPT_VERSION_ID = "2026-07-09.evolution-proposal.prompt.v2"
EVOLUTION_PROPOSAL_SCHEMA_VERSION = "2026-07-09.evolution-proposal.schema.v2"
QUESTION_CANDIDATE_PROMPT_VERSION_ID = "2026-07-05.question-candidate.prompt.v1"
QUESTION_CANDIDATE_SCHEMA_VERSION = "2026-07-05.question-candidate.schema.v1"


class QuestionCandidateError(RuntimeError):
    pass


class EvolutionAuditPackage:
    """v2 audit package shell for evidence-driven evolution."""

    required_fields = ("evidence_attempt_ids", "before", "after", "created_question_ids", "question_review_record_ids")

    @staticmethod
    def no_action(reason: str, *, session_id: str | None = None) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "status": "no_action",
            "no_action_reason": reason,
            "evidence_attempt_ids": [],
            "created_question_ids": [],
            "question_review_record_ids": [],
        }


def is_evolution_source_valid(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    return db.is_evolution_source_valid(conn, attempt)


def _ai_question_enabled() -> bool:
    return model_router.question_designer_route().enabled


def _question_model_name() -> str:
    return model_router.question_designer_route().model


def _base_url() -> str:
    return model_router.question_designer_route().base_url


def _question_candidate_prompt_template() -> str:
    path = Path(__file__).resolve().parent / "prompts/question_candidate.v1.md"
    return path.read_text(encoding="utf-8")


def _stable_sha256(value: Any) -> str:
    return db._digest_json(value)  # local deterministic audit helper


def _evolution_response_schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "agent_contracts/evolution_proposal.v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    schema = contract.get("response_schema")
    if not isinstance(schema, dict):
        raise ValueError("Evolution proposal contract is missing response_schema")
    return schema


def _evolution_response_schema_sha256() -> str:
    return _stable_sha256(_evolution_response_schema())


def _validate_evolution_agent_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "confidence", "evidence_gate", "proposals", "no_action_reason", "audit_summary"}
    missing = sorted(required - set(output))
    errors.extend(f"missing:{key}" for key in missing)
    if output.get("status") not in {"no_action", "proposal_ready", "blocked"}:
        errors.append("invalid:status")
    gate = output.get("evidence_gate")
    if not isinstance(gate, dict):
        errors.append("invalid:evidence_gate")
    else:
        for key in ("usable_attempt_ids", "blocked_attempt_ids", "evidence_strength", "closed_context", "graph_current", "why_evidence_is_sufficient"):
            if key not in gate:
                errors.append(f"missing:evidence_gate.{key}")
    proposals = output.get("proposals")
    if not isinstance(proposals, list):
        errors.append("invalid:proposals")
    else:
        proposal_required = {
            "action_type",
            "affected_agent_keys",
            "affected_node_ids",
            "evidence_attempt_ids",
            "change_scope",
            "proposal",
            "risk_level",
            "rollback_condition",
            "verification_signal",
            "why_not_no_action",
        }
        for index, proposal in enumerate(proposals):
            if not isinstance(proposal, dict):
                errors.append(f"invalid:proposals[{index}]")
                continue
            for key in sorted(proposal_required - set(proposal)):
                errors.append(f"missing:proposals[{index}].{key}")
    audit = output.get("audit_summary")
    if not isinstance(audit, dict):
        errors.append("invalid:audit_summary")
    else:
        for key in ("lineage_summary", "blocked_reason_summary", "child_safe_boundary"):
            if key not in audit:
                errors.append(f"missing:audit_summary.{key}")
    return errors


def _session_scope_block_reason(conn: sqlite3.Connection, session_id: str | None) -> str:
    if not session_id:
        return ""
    try:
        session = db.get_learning_session(conn, session_id)
    except KeyError:
        return "unknown_session"
    if session.get("mode") != "child_learning_group":
        return ""
    status = session.get("status")
    closure_status = session.get("closure_status")
    if status == "closed":
        return ""
    if status == "closing" and closure_status == "evolving":
        return ""
    return "child_session_not_ready_for_evolution"


def _question_candidate_response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "math_question_candidate",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "design_rationale": {"type": "string"},
                "candidate": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "question_type": {"type": "string"},
                        "variant_level": {"type": "string", "enum": ["L2", "L3", "L4"]},
                        "prompt": {"type": "string"},
                        "answer_format": {"type": "string"},
                        "expected_answer": {"type": "string"},
                        "solution_steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 6,
                        },
                        "target_error_tags": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(question_bank.CANONICAL_ERROR_TAGS),
                            },
                            "maxItems": 4,
                        },
                        "secondary_node_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "rollback_candidates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "reviewer_evidence": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "graph_bound": {"type": "boolean"},
                                "incoming_grade_7_ready": {"type": "boolean"},
                                "diagnostic_structure": {"type": "boolean"},
                                "process_evidence_required": {"type": "boolean"},
                                "not_mechanical_drill": {"type": "boolean"},
                                "child_prompt_self_contained": {"type": "boolean"},
                                "specific_expected_answer": {"type": "boolean"},
                                "review_rationale": {"type": "string"},
                            },
                            "required": [
                                "graph_bound",
                                "incoming_grade_7_ready",
                                "diagnostic_structure",
                                "process_evidence_required",
                                "not_mechanical_drill",
                                "child_prompt_self_contained",
                                "specific_expected_answer",
                                "review_rationale",
                            ],
                        },
                        "estimated_minutes": {"type": "integer", "minimum": 3, "maximum": 8},
                    },
                    "required": [
                        "question_type",
                        "variant_level",
                        "prompt",
                        "answer_format",
                        "expected_answer",
                        "solution_steps",
                        "target_error_tags",
                        "secondary_node_ids",
                        "rollback_candidates",
                        "reviewer_evidence",
                        "estimated_minutes",
                    ],
                },
            },
            "required": ["confidence", "design_rationale", "candidate"],
        },
    }


def _question_candidate_payload(
    node: dict[str, Any],
    base_question: dict[str, Any],
    attempt: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    analysis = attempt.get("answer_analysis") if isinstance(attempt.get("answer_analysis"), dict) else {}
    comparison = analysis.get("comparison") if isinstance(analysis.get("comparison"), list) else []
    unstable_dimensions = [
        item.get("dimension")
        for item in comparison
        if isinstance(item, dict) and item.get("status") in {"missing", "incorrect", "unclear"}
    ]
    trusted_context = {
        "learner_stage": question_bank.INCOMING_GRADE_7_AGE_FLOOR,
        "project_scope": "single child summer bridge from primary math gaps to grade-7 preview",
        "graph_node": {
            "id": node.get("id"),
            "name": node.get("name"),
            "stage": node.get("stage"),
            "domain": node.get("domain"),
            "priority": node.get("priority"),
            "question_types": node.get("question_types", []),
            "prerequisites": node.get("prerequisites", []),
            "teaching_contract": node.get("teaching_contract", {}),
            "error_diagnosis": node.get("error_diagnosis", {}),
        },
        "target_evidence": {
            "error_tags": attempt.get("error_tags", []),
            "result": attempt.get("result"),
            "score_points": attempt.get("score_points"),
            "explanation_score": attempt.get("explanation_score"),
            "process_gap": analysis.get("process_gap", ""),
            "unstable_dimensions": list(dict.fromkeys([item for item in unstable_dimensions if item])),
        },
        "quality_gate": {
            "must": [
                "Bind to the graph node intent.",
                "Be appropriate for an incoming grade-7 learner.",
                "Expose model/relation/step/check evidence, not only final answer.",
                "Use error analysis, misconception contrast, representation, estimation, or transfer.",
                "Keep the child-facing prompt respectful and self-contained.",
            ],
            "reject": [
                "bare arithmetic drills",
                "unit conversion drills without dimensional reasoning",
                "questions whose correctness can be judged by final answer alone",
                "child-facing words such as 回炉题, 真实错因, 孩子上次, graph node, agent, Codex, backend audit",
                "copying the prior question with only changed wording",
            ],
        },
        "canonical_error_tags": sorted(question_bank.CANONICAL_ERROR_TAGS),
    }
    untrusted_payload = {
        "base_question": {
            "id": base_question.get("id"),
            "prompt": base_question.get("prompt"),
            "answer_format": base_question.get("answer_format"),
            "expected_answer": base_question.get("expected_answer"),
            "solution_steps": base_question.get("solution_steps", []),
            "target_error_tags": base_question.get("target_error_tags", []),
        },
        "child_attempt": {
            "id": attempt.get("id"),
            "answer_raw": attempt.get("answer_raw"),
            "parent_note": attempt.get("parent_note"),
            "answer_analysis": analysis,
        },
    }
    template = _question_candidate_prompt_template()
    rendered = template.replace(
        "{trusted_context_json}",
        json.dumps(trusted_context, ensure_ascii=False, indent=2),
    ).replace(
        "{untrusted_payload_json}",
        json.dumps(untrusted_payload, ensure_ascii=False, indent=2),
    )
    return rendered, trusted_context, untrusted_payload


def _call_openai_question_candidate(
    node: dict[str, Any],
    base_question: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    route = model_router.question_designer_route()
    rendered_prompt, _, _ = _question_candidate_payload(node, base_question, attempt)
    payload = {
        "instructions": "You are a rigorous Chinese middle-school math question designer. Return only valid JSON.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": rendered_prompt}]}],
    }
    try:
        result = model_router.call_structured_json(
            route,
            payload,
            schema=_question_candidate_response_schema(),
            plain_json_instruction="Return only valid JSON matching the requested schema; no markdown.",
        )
    except model_router.ModelCallError as exc:
        raise QuestionCandidateError(f"AI 命题暂不可用：{exc}") from exc

    return result.value


def _extract_response_text(data: dict[str, Any]) -> str:
    return model_router.extract_response_text(data)


def _normalize_question_candidate_response(response: dict[str, Any]) -> tuple[dict[str, Any], float, str]:
    if not isinstance(response, dict):
        raise QuestionCandidateError("AI 命题返回不是对象。")
    try:
        confidence = max(0.0, min(1.0, float(response.get("confidence", 0))))
    except (TypeError, ValueError) as exc:
        raise QuestionCandidateError("AI 命题置信度不可用。") from exc
    candidate = response.get("candidate")
    if not isinstance(candidate, dict):
        raise QuestionCandidateError("AI 命题候选缺失。")
    candidate = dict(candidate)
    candidate["confidence"] = confidence
    candidate["design_rationale"] = str(response.get("design_rationale") or "")[:600]
    tags = [
        tag for tag in candidate.get("target_error_tags", [])
        if tag in question_bank.CANONICAL_ERROR_TAGS
    ]
    candidate["target_error_tags"] = tags or ["general"]
    candidate["solution_steps"] = [
        str(step).strip()
        for step in candidate.get("solution_steps", [])
        if str(step).strip()
    ][:6]
    candidate["secondary_node_ids"] = [
        str(node_id).strip()
        for node_id in candidate.get("secondary_node_ids", [])
        if str(node_id).strip()
    ][:4]
    candidate["rollback_candidates"] = [
        str(node_id).strip()
        for node_id in candidate.get("rollback_candidates", [])
        if str(node_id).strip()
    ][:4]
    reviewer_evidence = candidate.get("reviewer_evidence")
    if not isinstance(reviewer_evidence, dict):
        raise QuestionCandidateError("AI 命题候选缺少结构化审题证据。")
    for flag in question_bank.REVIEWER_EVIDENCE_FLAGS:
        if reviewer_evidence.get(flag) is not True:
            raise QuestionCandidateError(f"AI 命题候选未通过审题证据：{flag}。")
    if reviewer_evidence.get("specific_expected_answer") is not True:
        raise QuestionCandidateError("AI 命题候选缺少具体参考答案证据。")
    candidate["reviewer_evidence"] = {
        "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "model_candidate_self_report",
        "provenance_type": "untrusted_model_self_report",
        **reviewer_evidence,
        "review_rationale": str(reviewer_evidence.get("review_rationale") or "")[:600],
    }
    try:
        minutes = int(candidate.get("estimated_minutes", 5))
    except (TypeError, ValueError):
        minutes = 5
    candidate["estimated_minutes"] = max(3, min(8, minutes))
    rationale = str(response.get("design_rationale") or "")
    return candidate, confidence, rationale


def _candidate_graph_reference_error(
    conn: sqlite3.Connection,
    node: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    known = {row["id"] for row in conn.execute("select id from graph_nodes").fetchall()}
    secondary = [str(item) for item in candidate.get("secondary_node_ids", [])]
    rollback = [str(item) for item in candidate.get("rollback_candidates", [])]
    unknown = [item for item in secondary + rollback if item not in known]
    if unknown:
        return f"candidate_references_unknown_graph_nodes:{','.join(unknown[:4])}"
    allowed_rollback = set(node.get("prerequisites", []) or [])
    allowed_rollback.update(node.get("error_diagnosis", {}).get("rollback_to") or [])
    if rollback and not allowed_rollback:
        return "candidate_rollback_not_allowed_for_node_without_prerequisite_chain"
    if rollback and allowed_rollback:
        illegal = [item for item in rollback if item not in allowed_rollback]
        if illegal:
            return f"candidate_rollback_not_on_prerequisite_chain:{','.join(illegal[:4])}"
    return ""


def _model_question_candidate_attempt(
    conn: sqlite3.Connection,
    node: dict[str, Any],
    base_question: dict[str, Any],
    attempt: dict[str, Any],
    event_id: str,
    *,
    allow_model: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    rendered_prompt, trusted_context, untrusted_payload = _question_candidate_payload(node, base_question, attempt)
    schema = _question_candidate_response_schema()
    route = model_router.question_designer_route()
    metadata = {
        "attempt_id": attempt["id"],
        "base_question_id": base_question["id"],
        "node_id": node["id"],
        "engine_type": "model" if _ai_question_enabled() else "hybrid",
        "model_provider": route.provider if route.enabled else "",
        "model_name": route.model if route.enabled else "",
        "model_alias": route.model_alias if route.enabled else "",
        "model_params": route.model_params if route.enabled else {},
        "prompt_template_sha256": _stable_sha256(_question_candidate_prompt_template()),
        "rendered_prompt_sha256": _stable_sha256(rendered_prompt),
        "response_schema_sha256": _stable_sha256(schema),
        "response_schema_version": QUESTION_CANDIDATE_SCHEMA_VERSION,
        "input_refs": {
            "event_id": event_id,
            "attempt_id": attempt["id"],
            "base_question_id": base_question["id"],
            "node_id": node["id"],
            "trusted_context_digest": _stable_sha256(trusted_context),
            "untrusted_payload_digest": _stable_sha256(untrusted_payload),
        },
    }
    if not allow_model:
        metadata.update({
            "status": "skipped",
            "error_reason": "session_close uses deterministic question evolution; live model question design runs outside the child waiting path.",
            "confidence": 0.0,
            "output": {"fallback": "no_active_question_created"},
        })
        return None, metadata
    if not _ai_question_enabled():
        metadata.update({
            "status": "skipped",
            "error_reason": "OPENAI_API_KEY is not configured for question generation.",
            "confidence": 0.0,
            "output": {"fallback": "no_active_question_created"},
        })
        return None, metadata
    try:
        response = _call_openai_question_candidate(node, base_question, attempt)
        candidate, confidence, rationale = _normalize_question_candidate_response(response)
        metadata["confidence"] = confidence
        metadata["output"] = {
            "confidence": confidence,
            "design_rationale": rationale[:600],
            "candidate_prompt_preview": str(candidate.get("prompt", ""))[:240],
        }
        graph_ref_error = _candidate_graph_reference_error(conn, node, candidate)
        if graph_ref_error:
            metadata.update({
                "status": "rejected",
                "error_reason": graph_ref_error,
            })
            return None, metadata
        if confidence < MIN_QUESTION_CANDIDATE_CONFIDENCE:
            metadata.update({
                "status": "rejected",
                "error_reason": f"model_confidence_below_threshold:{confidence:.2f}",
            })
            return None, metadata
        item = question_bank.evolved_item_from_candidate(node, base_question, attempt, event_id, candidate)
    except (QuestionCandidateError, ValueError, model_router.ModelCallError) as exc:
        candidate_rejected = isinstance(exc, ValueError) or str(exc).startswith("AI 命题候选")
        metadata.update({
            "status": "rejected" if candidate_rejected else "error",
            "error_reason": str(exc),
            "confidence": float(metadata.get("confidence") or 0.0),
            "output": {
                **metadata.get("output", {}),
                "fallback": "no_active_question_created",
            },
        })
        return None, metadata

    item["source"]["model_name"] = route.model
    item["source"]["model_provider"] = route.provider
    item["source"]["candidate_status"] = "accepted"
    metadata.update({
        "status": "accepted",
        "error_reason": "",
        "output": {
            **metadata.get("output", {}),
            "created_question_id": item["id"],
            "quality_status": item.get("quality", {}).get("review_status"),
        },
    })
    return item, metadata


def _rejection_kind(candidate_status: str) -> str:
    if candidate_status == "skipped":
        return "generation_skipped"
    if candidate_status == "error":
        return "provider_error"
    return "review_or_contract_rejected"


def _rejected_draft_record(
    *,
    node_id: str,
    attempt: dict[str, Any],
    base_question: dict[str, Any],
    candidate_metadata: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    candidate_status = str(candidate_metadata.get("status") or "rejected")
    reason_text = str(reason or candidate_metadata.get("error_reason") or "model_candidate_not_accepted")
    output = candidate_metadata.get("output") if isinstance(candidate_metadata.get("output"), dict) else {}
    prompt_preview = str(output.get("candidate_prompt_preview") or "")[:240]
    response_schema_sha256 = str(candidate_metadata.get("response_schema_sha256") or "")
    prompt_template_sha256 = str(candidate_metadata.get("prompt_template_sha256") or "")
    draft_key = {
        "node_id": node_id,
        "attempt_id": attempt["id"],
        "base_question_id": base_question["id"],
        "candidate_status": candidate_status,
        "reason": reason_text,
        "prompt_template_sha256": prompt_template_sha256,
        "response_schema_sha256": response_schema_sha256,
        "candidate_prompt_preview": prompt_preview,
    }
    return {
        "draft_ref": f"RD-{_stable_sha256(draft_key)[:12]}",
        "node_id": node_id,
        "attempt_id": attempt["id"],
        "base_question_id": base_question["id"],
        "candidate_status": candidate_status,
        "rejection_kind": _rejection_kind(candidate_status),
        "reason": reason_text,
        "reason_code": reason_text.split(":", 1)[0][:120],
        "fallback": "no_active_question_created",
        "model_provider": candidate_metadata.get("model_provider", ""),
        "model_name": candidate_metadata.get("model_name", ""),
        "model_alias": candidate_metadata.get("model_alias", ""),
        "prompt_template_sha256": prompt_template_sha256,
        "rendered_prompt_sha256": candidate_metadata.get("rendered_prompt_sha256", ""),
        "response_schema_version": candidate_metadata.get("response_schema_version", ""),
        "response_schema_sha256": response_schema_sha256,
        "candidate_prompt_preview": prompt_preview,
        "candidate_output_sha256": _stable_sha256(output),
    }


def _created_item_record(
    item: dict[str, Any],
    *,
    node: dict[str, Any],
    base_question: dict[str, Any],
    attempt: dict[str, Any],
    event_id: str,
    candidate_metadata: dict[str, Any],
) -> dict[str, Any]:
    source = item.setdefault("source", {})
    candidate_status = source.get("candidate_status")
    if candidate_status != "accepted":
        raise ValueError("active_evolved_question_requires_accepted_model_candidate")
    fallback_used = False
    designer_engine = "model"
    designer_output = {
        "created_question_id": item["id"],
        "candidate_status": source.get("candidate_status"),
        "model_candidate_status": candidate_metadata.get("status", ""),
        "model_candidate_error_reason": candidate_metadata.get("error_reason", ""),
        "quality_status": item.get("quality", {}).get("review_status"),
        "fallback_used": fallback_used,
    }
    if candidate_metadata.get("output"):
        designer_output["model_candidate_output"] = candidate_metadata["output"]
    return {
        "item": item,
        "designer_run": {
            "agent_key": "question_designer_agent",
            "engine_type": designer_engine,
            "session_id": None,
            "phase": "question_candidate_generation",
            "trigger": f"question_candidate:{event_id}:{attempt['id']}",
            "input_refs": {
                **candidate_metadata.get("input_refs", {}),
                "fallback_used": fallback_used,
                "node_id": node["id"],
                "base_question_id": base_question["id"],
                "attempt_id": attempt["id"],
            },
            "prompt_version_id": QUESTION_CANDIDATE_PROMPT_VERSION_ID,
            "status": "accepted",
            "confidence": float(candidate_metadata.get("confidence") or (0.82 if fallback_used else 0.0)),
            "output": designer_output,
            "prompt_template_sha256": candidate_metadata.get("prompt_template_sha256", ""),
            "rendered_prompt_sha256": candidate_metadata.get("rendered_prompt_sha256", ""),
            "model_provider": candidate_metadata.get("model_provider", "") if designer_engine == "model" else "",
            "model_name": candidate_metadata.get("model_name", "") if designer_engine == "model" else "",
            "model_alias": candidate_metadata.get("model_alias", "") if designer_engine == "model" else "",
            "model_params": candidate_metadata.get("model_params", {}) if designer_engine == "model" else {},
            "response_schema_version": candidate_metadata.get("response_schema_version", ""),
            "response_schema_sha256": candidate_metadata.get("response_schema_sha256", ""),
            "error_reason": "",
        },
    }


def _reviewer_run_payload(record: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    item = record["item"]
    quality = question_bank.review_item_quality(item)
    return {
        "agent_key": "question_reviewer_agent",
        "engine_type": "deterministic",
        "session_id": None,
        "phase": "question_quality_review",
        "trigger": f"question_review:{event_id}:{item['id']}",
        "input_refs": {
            "event_id": event_id,
            "question_id": item["id"],
            "node_id": item["node_id"],
            "candidate_sha256": _stable_sha256(item),
            "candidate_status": item.get("source", {}).get("candidate_status", ""),
        },
        "prompt_version_id": "2026-07-05.question-review.prompt.v1",
        "status": "accepted" if quality["review_status"] == "approved" else "rejected",
        "confidence": 1.0,
        "output": {
            "review_status": quality["review_status"],
            "rejection_reasons": quality["rejection_reasons"],
            "active_eligible": quality["review_status"] == "approved",
            "criteria": quality.get("criteria", []),
        },
    }


def _status_from_attempts(rows: list[dict[str, Any]]) -> tuple[str, float, bool, str]:
    max_points = sum(float(row["max_points"]) for row in rows)
    score = sum(float(row["score_points"]) for row in rows)
    ratio = score / max_points if max_points else 0.0
    can_explain = any((row.get("explanation_score") or 0) >= 2 and not _has_high_score_reasoning_gap(row) for row in rows)
    has_blocking = any(row.get("blocking_evidence") for row in rows)
    if has_blocking:
        return "D", round(ratio, 2), can_explain, "Explicit skip/cannot-start evidence."
    if any(_has_high_score_reasoning_gap(row) for row in rows):
        return (
            "C",
            round(ratio, 2),
            False,
            "Final answer or score looked strong, but answer analysis says reasoning/model/steps/check evidence is incomplete or unsound.",
        )
    if ratio >= 0.85 and can_explain and len(rows) >= 2:
        return "A", round(ratio, 2), can_explain, "Repeated direct graded evidence meets mastery threshold."
    if ratio >= 0.85 and can_explain:
        return "B", round(ratio, 2), can_explain, "Single direct graded evidence is strong but not enough for mastery."
    if ratio >= 0.60:
        return "B", round(ratio, 2), can_explain, "Direct graded evidence is unstable but usable."
    return "C", round(ratio, 2), can_explain, "Direct graded evidence is weak; remediate or roll back."


def _has_high_score_reasoning_gap(attempt: dict[str, Any]) -> bool:
    try:
        ratio = float(attempt.get("score_points") or 0) / float(attempt.get("max_points") or 0)
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    if attempt.get("result") != "correct" and ratio < 0.85:
        return False
    analysis = attempt.get("answer_analysis") if isinstance(attempt.get("answer_analysis"), dict) else {}
    support = analysis.get("evaluation_support") if isinstance(analysis.get("evaluation_support"), dict) else {}
    return (
        support.get("reasoning_soundness") in {"incomplete", "unsound", "unclear"}
        or support.get("evidence_strength") in {"weak", "insufficient"}
        or support.get("next_evidence_need") not in {None, "", "none"}
    )


def _attempt_needs_repair(attempt: dict[str, Any]) -> bool:
    try:
        score = float(attempt["score_points"])
        max_points = float(attempt["max_points"])
    except (KeyError, TypeError, ValueError):
        return True
    return (
        attempt["result"] in {"wrong", "partial"}
        or score < max_points
        or _has_high_score_reasoning_gap(attempt)
    )


def _candidate_attempts(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
    attempt_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    filters = [
        "grading_status = 'graded'",
        "evidence_status = 'active'",
        "processed_evolution_event_id is null",
        "answer_analysis_json <> '{}'",
    ]
    params: list[Any] = []
    if session_id:
        filters.append("session_id = ?")
        params.append(session_id)
    if attempt_ids:
        filters.append("id in (%s)" % ",".join("?" for _ in attempt_ids))
        params.extend(attempt_ids)
    if session_id is None:
        filters.append(
            """
            not exists (
              select 1
              from learning_sessions s
              where s.id = attempts.session_id
                and s.mode = 'child_learning_group'
                and s.status != 'closed'
            )
            """
        )
    rows = conn.execute(
        f"""
        select *
        from attempts
        where {" and ".join(filters)}
        order by created_at, id
        """,
        params,
    ).fetchall()
    return [
        attempt for attempt in (db.attempt_row_to_dict(row) for row in rows)
        if db.is_evolution_source_valid(conn, attempt)
    ]


def _attempt_question_source_invalidated(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    try:
        question = db.get_question(conn, attempt["question_id"])
    except KeyError:
        return True
    if not db.is_child_schedulable_question(conn, question):
        return True
    source_type = question.get("source_type") or (question.get("source") or {}).get("type")
    if source_type != "evolved":
        return False
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    return source.get("evidence_status") == "invalidated" or raw_source.get("evidence_status") == "invalidated"


def _unprocessed_missing_analysis_count(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
    attempt_ids: list[str] | None = None,
) -> int:
    filters = [
        "grading_status = 'graded'",
        "evidence_status = 'active'",
        "processed_evolution_event_id is null",
    ]
    params: list[Any] = []
    if session_id:
        filters.append("session_id = ?")
        params.append(session_id)
    if attempt_ids:
        filters.append("id in (%s)" % ",".join("?" for _ in attempt_ids))
        params.extend(attempt_ids)
    if session_id is None:
        filters.append(
            """
            not exists (
              select 1
              from learning_sessions s
              where s.id = attempts.session_id
                and s.mode = 'child_learning_group'
                and s.status != 'closed'
            )
            """
        )
    rows = conn.execute(
        f"select * from attempts where {' and '.join(filters)}",
        params,
    ).fetchall()
    return sum(
        1
        for attempt in (db.attempt_row_to_dict(row) for row in rows)
        if not _attempt_question_source_invalidated(conn, attempt)
        and not db.is_valid_answer_analysis(attempt.get("answer_analysis"))
    )


def _base_question(conn: sqlite3.Connection, attempt: dict[str, Any]) -> dict[str, Any]:
    return db.get_question(conn, attempt["question_id"])


def _cause_analysis_from_attempt(attempt: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    analysis = attempt.get("answer_analysis") or {}
    comparison = analysis.get("comparison") if isinstance(analysis, dict) else []
    unstable_dimensions = [
        item.get("dimension")
        for item in comparison
        if isinstance(item, dict) and item.get("status") in {"missing", "incorrect", "unclear"}
    ]
    rollback_candidates = question.get("rollback_candidate_node_ids") or []
    return {
        "agent_key": "evaluation_agent",
        "attempt_id": attempt["id"],
        "node_id": attempt["node_id"],
        "error_tags": attempt.get("error_tags", []),
        "process_gap": str(analysis.get("process_gap") or "").strip(),
        "unstable_dimensions": list(dict.fromkeys([item for item in unstable_dimensions if item])),
        "rollback_node_id": rollback_candidates[0] if rollback_candidates else attempt["node_id"],
        "rollback_candidates": rollback_candidates,
        "confidence": 0.82 if analysis else 0.0,
        "evidence": {
            "result": attempt["result"],
            "score_points": attempt["score_points"],
            "explanation_score": attempt.get("explanation_score"),
        },
    }


def _evidence_strength(
    by_node: dict[str, list[dict[str, Any]]],
    *,
    before_statuses: dict[str, dict[str, Any] | None],
    rejected_drafts: list[dict[str, Any]],
) -> str:
    weak_attempts = [
        attempt
        for attempts in by_node.values()
        for attempt in attempts
        if _attempt_needs_repair(attempt)
    ]
    substantive_rejections = [
        draft for draft in rejected_drafts
        if draft.get("candidate_status") in {"rejected", "error", "skipped"}
    ]
    if substantive_rejections:
        return "rejection_learning"
    if not weak_attempts:
        prior_weak = any(
            before and before.get("status_code") in {"C", "D"}
            for before in before_statuses.values()
        )
        return "recovery_confirmed" if prior_weak else "single_local"
    weak_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    error_nodes: dict[str, set[str]] = defaultdict(set)
    for attempt in weak_attempts:
        weak_by_node[attempt["node_id"]].append(attempt)
        for tag in attempt.get("error_tags", []) or ["general"]:
            error_nodes[tag].add(attempt["node_id"])
    if any(len(nodes) >= 2 for nodes in error_nodes.values()):
        return "cross_node_pattern"
    if any(len(items) >= 2 for items in weak_by_node.values()):
        return "repeated_node_pattern"
    return "single_local"


def _change_scope_for_strength(strength: str) -> str:
    if strength == "cross_node_pattern":
        return "cross_node_local"
    if strength == "repeated_node_pattern":
        return "node_family"
    return "single_node_tentative"


def _profile_rule_metadata(strength: str) -> dict[str, str | bool]:
    if strength == "rejection_learning":
        return {
            "evidence_strength": strength,
            "change_scope": "single_node_tentative",
            "tentative": True,
            "rollback_condition": "Retire this generator/reviewer boundary rule after later candidates for the same node pass review without weakening diagnostic quality.",
            "verification_signal": "Future question candidates on the cited node avoid the rejected pattern or are skipped without creating active-use questions.",
        }
    if strength == "single_local":
        return {
            "evidence_strength": strength,
            "change_scope": "single_node_tentative",
            "tentative": True,
            "rollback_condition": "If the next same-structure or near-transfer retest is solved with sound reasoning, stop prioritizing this local repair rule.",
            "verification_signal": "A later active graded retest on the same node shows matched model/relation, steps, and check/explanation dimensions.",
        }
    if strength == "recovery_confirmed":
        return {
            "evidence_strength": strength,
            "change_scope": "single_node_tentative",
            "tentative": False,
            "rollback_condition": "If the repaired pattern remains stable for the next near-transfer item, avoid further remediation on this weakness.",
            "verification_signal": "Correct retest evidence after a previous weak status confirms the repair strategy worked.",
        }
    return {
        "evidence_strength": strength,
        "change_scope": _change_scope_for_strength(strength),
        "tentative": strength != "cross_node_pattern",
        "rollback_condition": "Retire or narrow the rule if subsequent retests no longer show the cited process gap.",
        "verification_signal": "Future attempts on the affected node family reduce the same dominant gap without introducing new prerequisite blockers.",
    }


def _proposal_contract_output(
    event: dict[str, Any],
    *,
    evidence_strength: str,
    affected_node_ids: list[str],
    rejected_drafts: list[dict[str, Any]],
    session_id: str | None,
    no_action_reason: str = "",
) -> dict[str, Any]:
    evidence_attempt_ids = list(event.get("evidence_attempt_ids", []))
    change_scope = _change_scope_for_strength(evidence_strength)
    proposals: list[dict[str, Any]] = []
    if event.get("status") in {"evolved", "question_review_rejected"}:
        if event.get("created_question_ids"):
            proposals.append({
                "action_type": "retest_candidate_request",
                "affected_agent_keys": ["question_designer_agent", "question_reviewer_agent", "planner_agent"],
                "affected_node_ids": affected_node_ids,
                "evidence_attempt_ids": evidence_attempt_ids,
                "change_scope": change_scope,
                "proposal": "Create or prefer a graph-bound retest candidate only after designer and reviewer lineage is recorded.",
                "risk_level": "medium" if evidence_strength == "single_local" else "low",
                "rollback_condition": "Retire the retest preference if source evidence is invalidated or later retest shows stable reasoning.",
                "verification_signal": "Next plan references the created question with source evidence ids, or reviewer rejection keeps it out of active use.",
                "why_not_no_action": "Usable weak evidence exists and requires an explicit retest or rejection-learning artifact.",
            })
        if rejected_drafts:
            proposals.append({
                "action_type": "question_pattern_rule",
                "affected_agent_keys": ["question_designer_agent", "question_reviewer_agent"],
                "affected_node_ids": affected_node_ids,
                "evidence_attempt_ids": evidence_attempt_ids,
                "change_scope": change_scope,
                "proposal": "Use rejected candidate reasons to tighten future question-pattern rules instead of scheduling rejected drafts.",
                "risk_level": "low",
                "rollback_condition": "Remove this tightening if future approved candidates no longer show the rejected pattern.",
                "verification_signal": "Future rejected_drafts count decreases without lowering question review quality.",
                "why_not_no_action": "Reviewer/model rejection is evidence about the generator boundary.",
            })
        proposals.append({
            "action_type": "profile_patch",
            "affected_agent_keys": ["self_evolution_agent", "question_designer_agent"],
            "affected_node_ids": affected_node_ids,
            "evidence_attempt_ids": evidence_attempt_ids,
            "change_scope": change_scope,
            "proposal": "Record a narrow learned rule tied to the cited graph node and error dimensions.",
            "risk_level": "medium" if evidence_strength == "single_local" else "low",
            "rollback_condition": "Rollback the learned rule if source evidence is invalidated or retest evidence contradicts it.",
            "verification_signal": "Future attempts show whether the cited process gap recurs, repairs, or moves to a prerequisite path.",
            "why_not_no_action": "The evidence is usable and the mutation is scoped, reversible, and audited.",
        })
    status = "no_action" if event.get("status") == "no_action" else "proposal_ready"
    return {
        "status": status,
        "confidence": 1.0 if evidence_attempt_ids or no_action_reason else 0.85,
        "evidence_gate": {
            "usable_attempt_ids": evidence_attempt_ids,
            "blocked_attempt_ids": [],
            "evidence_strength": evidence_strength,
            "closed_context": True,
            "graph_current": True,
            "why_evidence_is_sufficient": (
                "No usable evidence was available." if status == "no_action"
                else "All cited attempts passed the shared active graded valid-analysis current-question evidence gate."
            ),
        },
        "proposals": proposals[:5],
        "no_action_reason": no_action_reason if status == "no_action" else "",
        "audit_summary": {
            "lineage_summary": f"{len(evidence_attempt_ids)} usable attempt(s), {len(event.get('created_question_ids', []))} created question(s).",
            "blocked_reason_summary": no_action_reason or "; ".join(sorted({str(item.get("reason", "")) for item in rejected_drafts if item.get("reason")}))[:300],
            "child_safe_boundary": "No internal evolution details are child-facing; planner/teaching agents translate only child-safe next actions.",
        },
    }


def run_evolution(
    conn: sqlite3.Connection,
    trigger: str,
    *,
    session_id: str | None = None,
    attempt_ids: list[str] | None = None,
    allow_model_question_candidate: bool = True,
    commit: bool = True,
) -> dict[str, Any]:
    scope_block_reason = _session_scope_block_reason(conn, session_id)
    if scope_block_reason:
        event = {
            "id": f"E-{uuid.uuid4().hex[:12]}",
            "trigger": trigger,
            "status": "no_action",
            "event_type": scope_block_reason,
            "node_id": None,
            "evidence_attempt_ids": [],
            "before": {},
            "after": {"session_id": session_id, "scope_block_reason": scope_block_reason},
            "created_question_ids": [],
        }
        agent_output = _proposal_contract_output(
            event,
            evidence_strength="none",
            affected_node_ids=[],
            rejected_drafts=[],
            session_id=session_id,
            no_action_reason=scope_block_reason,
        )
        validation_errors = _validate_evolution_agent_output(agent_output)
        if validation_errors:
            raise ValueError(f"Invalid self_evolution_agent output: {validation_errors}")
        event["after"]["self_evolution_agent_output"] = agent_output
        with (conn if commit else nullcontext()):
            db.record_agent_run(
                conn,
                agent_key="self_evolution_agent",
                engine_type="hybrid",
                session_id=session_id,
                phase="session_close",
                trigger=trigger,
                input_refs={
                    "session_id": session_id,
                    "attempt_ids": attempt_ids or [],
                    "scope_block_reason": scope_block_reason,
                },
                prompt_version_id=EVOLUTION_PROPOSAL_PROMPT_VERSION_ID,
                status="accepted",
                confidence=1.0,
                output=agent_output,
                validation_errors=validation_errors,
                response_schema_version=EVOLUTION_PROPOSAL_SCHEMA_VERSION,
                response_schema_sha256=_evolution_response_schema_sha256(),
                commit=False,
            )
            _insert_event(conn, event, session_id=session_id, no_action_reason=scope_block_reason)
        return event

    attempts = _candidate_attempts(conn, session_id=session_id, attempt_ids=attempt_ids)
    if not attempts:
        missing_analysis_count = _unprocessed_missing_analysis_count(conn, session_id=session_id, attempt_ids=attempt_ids)
        event = {
            "id": f"E-{uuid.uuid4().hex[:12]}",
            "trigger": trigger,
            "status": "no_action",
            "event_type": "graded_evidence_missing_answer_analysis" if missing_analysis_count else "no_graded_analyzed_evidence",
            "node_id": None,
            "evidence_attempt_ids": [],
            "before": {},
            "after": {"missing_analysis_attempts": missing_analysis_count},
            "created_question_ids": [],
        }
        agent_output = _proposal_contract_output(
            event,
            evidence_strength="none",
            affected_node_ids=[],
            rejected_drafts=[],
            session_id=session_id,
            no_action_reason=event["event_type"],
        )
        validation_errors = _validate_evolution_agent_output(agent_output)
        if validation_errors:
            raise ValueError(f"Invalid self_evolution_agent output: {validation_errors}")
        event["after"]["self_evolution_agent_output"] = agent_output
        with (conn if commit else nullcontext()):
            db.record_agent_run(
                conn,
                agent_key="self_evolution_agent",
                engine_type="hybrid",
                session_id=session_id,
                phase="session_close" if session_id else "system_analysis",
                trigger=trigger,
                input_refs={
                    "session_id": session_id,
                    "attempt_ids": attempt_ids or [],
                    "candidate_attempt_count": 0,
                    "missing_analysis_attempts": missing_analysis_count,
                },
                prompt_version_id=EVOLUTION_PROPOSAL_PROMPT_VERSION_ID,
                status="accepted",
                confidence=1.0,
                output=agent_output,
                validation_errors=validation_errors,
                response_schema_version=EVOLUTION_PROPOSAL_SCHEMA_VERSION,
                response_schema_sha256=_evolution_response_schema_sha256(),
                commit=False,
            )
            _insert_event(conn, event, session_id=session_id, no_action_reason=event["event_type"])
        return event

    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        by_node[attempt["node_id"]].append(attempt)
    prior_profile = db.get_agent_profile(conn, "self_evolution_agent")
    prior_designer_profile = db.get_agent_profile(conn, "question_designer_agent")
    event_id = f"E-{uuid.uuid4().hex[:12]}"
    all_evidence_ids: list[str] = []
    created_item_records: list[dict[str, Any]] = []
    rejected_drafts: list[dict[str, Any]] = []
    status_proposals: dict[str, dict[str, Any]] = {}
    before_statuses: dict[str, dict[str, Any] | None] = {}
    cause_analyses: dict[str, dict[str, Any]] = {}
    all_error_tags: list[str] = []
    profile = dict(prior_profile["profile"])
    learned_rules = list(profile.get("learned_rules", []))
    designer_profile = dict(prior_designer_profile["profile"])
    designer_learned_rules = list(designer_profile.get("learned_rules", []))

    for node_id in sorted(by_node):
        evidence = by_node[node_id]
        evidence_ids = [attempt["id"] for attempt in evidence]
        all_evidence_ids.extend(evidence_ids)
        prior_status = conn.execute("select * from learner_node_status where node_id = ?", (node_id,)).fetchone()
        before_statuses[node_id] = dict(prior_status) if prior_status else None
        status_code, latest_score, can_explain, status_reason = _status_from_attempts(evidence)
        status_proposals[node_id] = {
            "status_code": status_code,
            "latest_score": latest_score,
            "can_explain": can_explain,
            "status_reason": status_reason,
            "evidence_attempt_ids": evidence_ids,
        }
        weak_evidence = [attempt for attempt in evidence if _attempt_needs_repair(attempt)]
        if not weak_evidence:
            continue
        node = db.get_graph_node(conn, node_id)
        base_question = _base_question(conn, weak_evidence[0])
        for attempt in evidence:
            cause_analyses[attempt["id"]] = _cause_analysis_from_attempt(attempt, _base_question(conn, attempt))
        error_counter = Counter(tag for attempt in evidence for tag in attempt.get("error_tags", []))
        top_error_tags = [tag for tag, _ in error_counter.most_common()]
        all_error_tags.extend(top_error_tags)
        node_strength = "repeated_node_pattern" if len(weak_evidence) >= 2 else "single_local"
        rule_metadata = _profile_rule_metadata(node_strength)
        learned_rule = {
            "node_id": node_id,
            "rule": f"真实证据显示 {node.get('name')} 在 {', '.join(top_error_tags) or 'general'} 上不稳；优先生成错因回炉题，并在计划中先复测前置链。",
            "evidence_attempt_ids": evidence_ids,
            **rule_metadata,
        }
        learned_rules.append(learned_rule)
        designer_learned_rule = {
            **learned_rule,
            "designer_action": "生成图谱绑定、错因驱动、需要过程证据的回炉题候选。",
        }
        designer_learned_rules.append(designer_learned_rule)
        weak_attempt = weak_evidence[0]
        model_item, candidate_metadata = _model_question_candidate_attempt(
            conn,
            node,
            base_question,
            weak_attempt,
            event_id,
            allow_model=allow_model_question_candidate,
        )
        if model_item is None:
            rejected_draft = _rejected_draft_record(
                node_id=node_id,
                attempt=weak_attempt,
                base_question=base_question,
                candidate_metadata=candidate_metadata,
            )
            rejected_drafts.append(rejected_draft)
            rejection_metadata = _profile_rule_metadata("rejection_learning")
            boundary_patch = {
                **rejection_metadata,
                "underlying_evidence_strength": node_strength,
                "rejected_draft_refs": [rejected_draft["draft_ref"]],
                "candidate_status": rejected_draft["candidate_status"],
                "rejection_kind": rejected_draft["rejection_kind"],
                "reason_code": rejected_draft["reason_code"],
                "fallback": "no_active_question_created",
            }
            learned_rule.update(boundary_patch)
            designer_learned_rule.update({
                **boundary_patch,
                "designer_action": "不创建 active 题；记录 rejected draft，后续命题必须避开该候选失败模式。",
            })
            continue
        try:
            created_item_records.append(_created_item_record(
                model_item,
                node=node,
                base_question=base_question,
                attempt=weak_attempt,
                event_id=event_id,
                candidate_metadata=candidate_metadata,
            ))
        except ValueError as exc:
            rejected_draft = _rejected_draft_record(
                node_id=node_id,
                attempt=weak_attempt,
                base_question=base_question,
                candidate_metadata={**candidate_metadata, "status": "rejected"},
                reason=str(exc),
            )
            rejected_drafts.append(rejected_draft)
            rejection_metadata = _profile_rule_metadata("rejection_learning")
            boundary_patch = {
                **rejection_metadata,
                "underlying_evidence_strength": node_strength,
                "rejected_draft_refs": [rejected_draft["draft_ref"]],
                "candidate_status": rejected_draft["candidate_status"],
                "rejection_kind": rejected_draft["rejection_kind"],
                "reason_code": rejected_draft["reason_code"],
                "fallback": "no_active_question_created",
            }
            learned_rule.update(boundary_patch)
            designer_learned_rule.update({
                **boundary_patch,
                "designer_action": "候选题写库前失败；不创建 active 题，并把失败模式沉淀给后续命题。",
            })

    top_error_tags = [tag for tag, _ in Counter(all_error_tags).most_common()]
    event_evidence_strength = _evidence_strength(
        by_node,
        before_statuses=before_statuses,
        rejected_drafts=rejected_drafts,
    )
    profile["focus_error_tags"] = list(dict.fromkeys(profile.get("focus_error_tags", []) + top_error_tags))
    profile["learned_rules"] = learned_rules[-20:]
    designer_profile["focus_error_tags"] = list(dict.fromkeys(designer_profile.get("focus_error_tags", []) + top_error_tags))
    designer_profile["learned_rules"] = designer_learned_rules[-20:]

    before = {
        "node_statuses": before_statuses,
        "self_evolution_agent_revision": prior_profile["revision"],
        "question_designer_agent_revision": prior_designer_profile["revision"],
        "question_count_evolved": conn.execute(
            "select count(*) from question_items where source_type = 'evolved'"
        ).fetchone()[0],
    }

    with (conn if commit else nullcontext()):
        for record in created_item_records:
            designer_payload = dict(record["designer_run"])
            designer_payload["session_id"] = session_id
            designer_run = db.record_agent_run(conn, commit=False, **designer_payload)
            reviewer_payload = _reviewer_run_payload(record, event_id=event_id)
            reviewer_payload["session_id"] = session_id
            reviewer_run = db.record_agent_run(conn, commit=False, **reviewer_payload)
            db.upsert_question(
                conn,
                record["item"],
                created_by_event_id=event_id,
                designer_run_id=designer_run["id"],
                reviewer_run_id=reviewer_run["id"],
            )
        if learned_rules != prior_profile["profile"].get("learned_rules", []) or rejected_drafts or top_error_tags:
            db.update_agent_profile(conn, "self_evolution_agent", profile)
            db.update_agent_profile(conn, "question_designer_agent", designer_profile)
        for attempt_id, cause_analysis in cause_analyses.items():
            conn.execute(
                "update attempts set cause_analysis_json = ? where id = ?",
                (db.json_dump(cause_analysis), attempt_id),
            )
        conn.execute(
            "update attempts set processed_evolution_event_id = ? where id in (%s)" % ",".join("?" for _ in all_evidence_ids),
            [event_id, *all_evidence_ids],
        )
        after_profile = db.get_agent_profile(conn, "self_evolution_agent")
        after_designer_profile = db.get_agent_profile(conn, "question_designer_agent")
        after_statuses: dict[str, dict[str, Any] | None] = {}
        for node_id in status_proposals:
            row = conn.execute("select * from learner_node_status where node_id = ?", (node_id,)).fetchone()
            after_statuses[node_id] = dict(row) if row else None
        created_items = [record["item"] for record in created_item_records]
        created_question_ids = [item["id"] for item in created_items]
        affected_node_ids = sorted(status_proposals)
        event = {
            "id": event_id,
            "trigger": trigger,
            "status": "evolved" if created_item_records else ("question_review_rejected" if rejected_drafts else "state_updated"),
            "event_type": "evidence_driven_question_and_agent_revision" if created_item_records else ("review_rejected_status_update" if rejected_drafts else "graded_evidence_status_update"),
            "node_id": affected_node_ids[0] if len(affected_node_ids) == 1 else "multiple",
            "evidence_attempt_ids": all_evidence_ids,
            "before": before,
            "after": {
                "node_statuses": after_statuses,
                "node_status_update_proposals": status_proposals,
                "self_evolution_agent_revision": after_profile["revision"],
                "question_designer_agent_revision": after_designer_profile["revision"],
                "dominant_error_tags": top_error_tags,
                "cause_analyses": list(cause_analyses.values()),
                "rejected_drafts": rejected_drafts,
                "evidence_strength": event_evidence_strength,
            },
            "created_question_ids": created_question_ids,
        }
        agent_output = _proposal_contract_output(
            event,
            evidence_strength=event_evidence_strength,
            affected_node_ids=affected_node_ids,
            rejected_drafts=rejected_drafts,
            session_id=session_id,
        )
        validation_errors = _validate_evolution_agent_output(agent_output)
        if validation_errors:
            raise ValueError(f"Invalid self_evolution_agent output: {validation_errors}")
        event["after"]["self_evolution_agent_output"] = agent_output
        db.record_agent_run(
            conn,
            agent_key="self_evolution_agent",
            engine_type="hybrid",
            session_id=session_id,
            phase="session_close" if session_id else "system_analysis",
            trigger=trigger,
            input_refs={
                "session_id": session_id,
                "attempt_ids": attempt_ids or [],
                "evidence_attempt_ids": all_evidence_ids,
                "affected_node_ids": affected_node_ids,
            },
            prompt_version_id=EVOLUTION_PROPOSAL_PROMPT_VERSION_ID,
            status="accepted",
            confidence=1.0,
            output=agent_output,
            validation_errors=validation_errors,
            response_schema_version=EVOLUTION_PROPOSAL_SCHEMA_VERSION,
            response_schema_sha256=_evolution_response_schema_sha256(),
            commit=False,
        )
        _insert_event(conn, event, session_id=session_id)
    return event


def _insert_event(
    conn: sqlite3.Connection,
    event: dict[str, Any],
    *,
    session_id: str | None = None,
    no_action_reason: str = "",
) -> None:
    conn.execute(
        """
        insert or replace into evolution_events(
          id, trigger, status, event_type, node_id, evidence_attempt_ids_json,
          before_json, after_json, created_question_ids_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["id"],
            event["trigger"],
            event["status"],
            event["event_type"],
            event.get("node_id"),
            db.json_dump(event.get("evidence_attempt_ids", [])),
            db.json_dump(event.get("before", {})),
            db.json_dump(event.get("after", {})),
            db.json_dump(event.get("created_question_ids", [])),
            db.now_iso(),
        ),
    )
    created_question_ids = event.get("created_question_ids", [])
    db.record_evolution_audit(
        conn,
        evolution_event_id=event["id"],
        session_id=session_id,
        trigger=event["trigger"],
        evidence_attempt_ids=event.get("evidence_attempt_ids", []),
        before=event.get("before", {}),
        after=event.get("after", {}),
        created_question_ids=created_question_ids,
        question_review_record_ids=db.question_review_record_ids_for_questions(conn, created_question_ids),
        no_action_reason=no_action_reason,
        commit=False,
    )


def event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["evidence_attempt_ids"] = db.json_load(data.pop("evidence_attempt_ids_json"), [])
    data["before"] = db.json_load(data.pop("before_json"), {})
    data["after"] = db.json_load(data.pop("after_json"), {})
    data["created_question_ids"] = db.json_load(data.pop("created_question_ids_json"), [])
    return data


def recent_events(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select * from evolution_events order by created_at desc, rowid desc limit ?",
        (limit,),
    ).fetchall()
    return [event_row_to_dict(row) for row in rows]
