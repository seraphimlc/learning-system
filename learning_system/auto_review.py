from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import db, model_router


CANONICAL_ERROR_TAGS = {
    "calculation_or_symbol",
    "concept_confusion",
    "modeling_or_reading",
    "process_habit",
    "visual_spatial",
    "general",
}

MIN_CONFIDENCE_TO_GRADE = 0.68
MIN_PHOTO_OCR_CONFIDENCE = 0.62

DIMENSION_GAP_ERROR_TAGS = {
    "final_answer": "calculation_or_symbol",
    "model_or_relation": "concept_confusion",
    "steps": "process_habit",
    "symbols_units": "calculation_or_symbol",
    "check_or_explanation": "process_habit",
}

@dataclass(frozen=True)
class AnswerAnalysisResult:
    """v2 answer-analysis adapter seam; validates structure before downstream use."""

    status: str
    analysis: dict[str, Any]
    pending_reason: str = ""

    @classmethod
    def from_review(cls, review: dict[str, Any]) -> "AnswerAnalysisResult":
        if review.get("needs_ai_review", review.get("needs_codex_review")):
            return cls(
                status="pending",
                analysis={},
                pending_reason=str(review.get("reason") or review.get("parent_note") or "pending_answer_analysis"),
            )
        analysis = review.get("analysis") if isinstance(review.get("analysis"), dict) else {}
        try:
            db.validate_answer_analysis(analysis)
        except ValueError as exc:
            return cls(status="pending", analysis={}, pending_reason=str(exc))
        return cls(status="valid", analysis=analysis)


def review_child_answer(
    question: dict[str, Any],
    answer_raw: str,
    *,
    has_photo: bool = False,
    answer_photo_data_url: str | None = None,
) -> dict[str, Any]:
    """Review an answer with an AI evaluator when configured.

    Reference answers and solution steps are rubric context, not string-match
    truth. If no AI evaluator is configured or the evaluator is uncertain, the
    evidence stays pending for system AI analysis instead of being heuristically
    graded.
    """
    answer = (answer_raw or "").strip()
    route = model_router.answer_analysis_route()
    if not route.enabled:
        return _pending_review(
            "未配置 OPENAI_API_KEY，不能用关键词替代 AI 判断；该证据需由系统 AI 分析后再进入学习判断。",
            status="not_configured",
        )

    photo_ocr = None
    if has_photo and answer_photo_data_url:
        photo_ocr = _review_answer_photo(question, answer, answer_photo_data_url)
        if not answer and not _photo_ocr_is_usable(photo_ocr):
            return _pending_review(
                "照片答案暂时无法可靠转写，不能凭空判断；该证据需继续由系统分析。",
                status="photo_ocr_unusable",
                ai_review={
                    "status": "photo_ocr_unusable",
                    "reason": "answer photo OCR was unavailable or low confidence",
                    "vision": _photo_ocr_audit(photo_ocr),
                },
            )

    try:
        kwargs: dict[str, Any] = {"answer_photo_data_url": answer_photo_data_url if has_photo else None}
        if photo_ocr is not None:
            kwargs["answer_photo_ocr"] = photo_ocr
        review = _call_openai_evaluator(question, answer, **kwargs)
        normalized = _normalize_ai_review(review, strict_analysis=False)
        if normalized["confidence"] < MIN_CONFIDENCE_TO_GRADE and _is_low_confidence_no_evidence_wrong(normalized):
            _complete_low_confidence_no_evidence_analysis(normalized)
        db.validate_answer_analysis(normalized["analysis"])
    except model_router.ModelCallError:
        raise
    except (AIReviewError, ValueError) as exc:
        return _pending_review(
            str(exc),
            status="error",
            ai_review={
                "status": "error",
                "reason": str(exc),
                "model": route.model,
                "provider": route.provider,
                "model_alias": route.model_alias,
                "vision": _photo_ocr_audit(photo_ocr) if photo_ocr is not None else None,
            },
        )

    if normalized["confidence"] < MIN_CONFIDENCE_TO_GRADE and _is_low_confidence_no_evidence_wrong(normalized):
        normalized["needs_ai_review"] = False
        normalized["needs_codex_review"] = False
        normalized["parent_note"] = f"AI 评估 Agent：{normalized['parent_note']}"
        normalized["ai_review"] = {
            "status": "graded",
            "model": route.model,
            "provider": route.provider,
            "model_alias": route.model_alias,
            "confidence": normalized["confidence"],
            "confidence_policy": "accepted_low_confidence_no_evidence_wrong",
            "vision": _photo_ocr_audit(photo_ocr) if photo_ocr is not None else None,
            "key_observations": normalized.pop("key_observations", []),
            "next_action": normalized.pop("next_action", ""),
        }
        return normalized

    if normalized["confidence"] < MIN_CONFIDENCE_TO_GRADE:
        return _pending_review(
            f"AI 评估置信度不足（{normalized['confidence']:.2f}），保留为系统待分析证据。",
            status="low_confidence",
            ai_review={
                **normalized,
                "status": "low_confidence",
                "model": route.model,
                "provider": route.provider,
                "model_alias": route.model_alias,
                "vision": _photo_ocr_audit(photo_ocr) if photo_ocr is not None else None,
            },
        )
    normalized["needs_ai_review"] = False
    normalized["needs_codex_review"] = False
    normalized["parent_note"] = f"AI 评估 Agent：{normalized['parent_note']}"
    normalized["ai_review"] = {
        "status": "graded",
        "model": route.model,
        "provider": route.provider,
        "model_alias": route.model_alias,
        "confidence": normalized["confidence"],
        "vision": _photo_ocr_audit(photo_ocr) if photo_ocr is not None else None,
        "key_observations": normalized.pop("key_observations", []),
        "local_guardrails": normalized.pop("local_guardrails", []),
        "next_action": normalized.pop("next_action", ""),
    }
    return normalized


def _is_low_confidence_no_evidence_wrong(review: dict[str, Any]) -> bool:
    if review.get("result") != "wrong":
        return False
    if float(review.get("score_points") or 0) != 0:
        return False
    if int(review.get("explanation_score") or 0) != 0:
        return False
    analysis = review.get("analysis") if isinstance(review.get("analysis"), dict) else {}
    process_gap = str(analysis.get("process_gap") or "").strip()
    comparison = analysis.get("comparison")
    if not process_gap or not isinstance(comparison, list) or not comparison:
        return False
    statuses_by_dimension = {
        str(item.get("dimension")): str(item.get("status"))
        for item in comparison
        if isinstance(item, dict)
    }
    if any(status in {"matched", "alternative_valid"} for status in statuses_by_dimension.values()):
        return False
    required_dimensions = {"final_answer", "model_or_relation", "steps"}
    if not required_dimensions <= set(statuses_by_dimension):
        return False
    return all(
        statuses_by_dimension.get(dimension) in {"missing", "unclear", "incorrect"}
        for dimension in required_dimensions
    )


def _complete_low_confidence_no_evidence_analysis(review: dict[str, Any]) -> None:
    analysis = review.get("analysis") if isinstance(review.get("analysis"), dict) else {}
    if not analysis:
        return
    _append_or_replace_missing_comparison(analysis, "symbols_units", "没有可读的符号、单位或表达过程。")
    _append_or_replace_missing_comparison(analysis, "check_or_explanation", "没有检验或解释证据。")
    if not str(analysis.get("process_gap") or "").strip():
        analysis["process_gap"] = "没有可用作答证据，无法判断关系、步骤、表达或检验。"
    _refresh_evaluation_support(analysis)


class AIReviewError(RuntimeError):
    pass


def _ai_enabled() -> bool:
    return model_router.answer_analysis_route().enabled


def _model_name() -> str:
    return model_router.answer_analysis_route().model


def _base_url() -> str:
    return model_router.answer_analysis_route().base_url


def _pending_review(
    reason: str,
    *,
    status: str,
    ai_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "needs_ai_review": True,
        "needs_codex_review": True,
        "reason": reason,
        "ai_review": ai_review or {"status": status, "reason": reason},
    }


def _comparison_statuses_by_dimension(analysis: dict[str, Any]) -> dict[str, str]:
    comparison = analysis.get("comparison")
    if not isinstance(comparison, list):
        return {}
    return {
        str(item.get("dimension")): str(item.get("status"))
        for item in comparison
        if isinstance(item, dict)
    }


def _append_or_replace_missing_comparison(analysis: dict[str, Any], dimension: str, detail: str) -> None:
    comparison = analysis.get("comparison")
    if not isinstance(comparison, list):
        return
    for item in comparison:
        if isinstance(item, dict) and item.get("dimension") == dimension:
            if item.get("status") == "matched":
                item["status"] = "missing"
                item["detail"] = detail
            return
    comparison.append({"dimension": dimension, "status": "missing", "detail": detail})


def _refresh_evaluation_support(analysis: dict[str, Any]) -> None:
    analysis["evaluation_support"] = db.derive_answer_evaluation_support(analysis)


def _review_prompt(
    question: dict[str, Any],
    answer: str,
    *,
    answer_photo_ocr: dict[str, Any] | None = None,
) -> str:
    photo_evidence = {}
    if answer_photo_ocr is not None:
        photo_evidence = {
            "status": answer_photo_ocr.get("status", ""),
            "confidence": answer_photo_ocr.get("confidence", 0),
            "transcript": answer_photo_ocr.get("transcript", ""),
            "math_objects": answer_photo_ocr.get("math_objects", []),
            "notes": answer_photo_ocr.get("notes", ""),
            "instruction": "Treat this as OCR evidence from the answer photo, not as ground truth. Compare it with the written answer and original image when available.",
        }
    return json.dumps(
        {
            "role": "single_child_math_evaluator",
            "expert_operating_standard": [
                "Act like a senior middle-school math diagnostician and one-on-one tutor, not a keyword grader.",
                "Judge what the learner's written evidence proves, what remains unproven, and what next teaching move follows.",
                "Reference answers and solution steps are rubric context, not exact wording requirements.",
                "A numerically correct answer is not full credit unless the model/relation, key steps, symbols/units, and explanation/check are sound.",
            ],
            "policy": [
                "Do not require exact wording from the reference answer.",
                "Judge mathematically equivalent reasoning as correct only when the final answer, core relation/model, key steps, and explanation/check are all sound.",
                "A correct final answer with missing, lucky, circular, copied, or conceptually wrong reasoning is not correct; use partial or wrong according to the reasoning evidence.",
                "Use partial when the final answer or idea is partly right but steps, model, symbols, units, explanation, or check are unstable.",
                "Use wrong for wrong result, wrong model, contradiction, blank answer, explicit stuck state, or reasoning that reaches a right answer from an invalid method.",
                "If the evidence is insufficient or image quality/text is unclear, return low confidence.",
            ],
            "evidence_dimensions": [
                "final_answer: result, unit, sign, expression, or conclusion",
                "model_or_relation: equation, invariant, diagram, sign rule, unit model, or quantity relation",
                "steps: reproducible sequence of valid transformations",
                "symbols_units: notation, brackets, variables, signs, and units",
                "check_or_explanation: substitution, inverse check, estimate, context check, or verbal justification",
            ],
            "decision_procedure": [
                "Reconstruct the optimal solution in 2-6 reliable steps.",
                "Identify valid alternative approaches before judging the child.",
                "Summarize only what the child actually wrote or what OCR visibly supports.",
                "Compare the child work against the optimal and alternatives dimension by dimension.",
                "Cap correct final answers at partial when reasoning evidence is missing, lucky, circular, copied, or conceptually wrong.",
                "Use low confidence rather than guessing when photo/OCR or written work is ambiguous.",
            ],
            "quality_bar": [
                "answer_analysis must be detailed enough for graph binding, evaluation, teaching, planning, and self-evolution.",
                "process_gap must name the smallest teachable gap; do not use vague labels.",
                "next_child_prompt must be one precise child-facing hint or next question, not backend analysis.",
            ],
            "question": {
                "id": question.get("id"),
                "node_id": question.get("node_id"),
                "prompt": question.get("prompt"),
                "answer_format": question.get("answer_format"),
                "reference_answer": question.get("expected_answer"),
                "solution_steps": question.get("solution_steps", []),
                "rubric": question.get("rubric", []),
                "target_error_tags": question.get("target_error_tags", []),
            },
            "child_answer_text": answer,
            "answer_photo_ocr_evidence": photo_evidence,
            "output_contract": {
                "result": "correct | partial | wrong",
                "score_points": "2 only when answer and reasoning are both sound; 1 for partial; 0 for wrong",
                "max_points": 2,
                "error_tags": "canonical tags only",
                "explanation_score": "0=no usable reasoning, 1=incomplete/unstable reasoning, 2=sound independent reasoning",
                "blocking_evidence": "true only when the child cannot start or a prerequisite is clearly broken",
                "confidence": "0.0 to 1.0",
                "parent_note": "one concise Chinese sentence explaining the AI judgment",
                "answer_analysis": {
                    "optimal_answer": "concise final answer, including required units/symbols",
                    "optimal_solution_steps": "best solution path in 2-6 Chinese steps",
                    "child_answer_summary": "what the child appears to have done, without inventing missing work",
                    "comparison": "matched/missing/incorrect/unclear points comparing child solution with optimal and valid alternatives",
                    "alternative_solutions": "other mathematically valid approaches, if any",
                    "process_gap": "the exact reasoning/model/step gap; empty only when no meaningful gap exists",
                    "evaluation_support": "locally re-derived support signal for evaluation and planning: evidence strength, reasoning soundness, weak dimensions, clearer-evidence need, and next evidence need",
                    "teaching_explanation": "detailed Chinese explanation suitable for system planning and child review",
                    "next_child_prompt": "one precise next question or hint for the child",
                },
            },
        },
        ensure_ascii=False,
    )


def _response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "math_answer_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "result": {"type": "string", "enum": ["correct", "partial", "wrong"]},
                "score_points": {"type": "number", "enum": [0, 1, 2]},
                "max_points": {"type": "number", "enum": [2]},
                "error_tags": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(CANONICAL_ERROR_TAGS),
                    },
                    "maxItems": 4,
                },
                "explanation_score": {"type": "integer", "enum": [0, 1, 2]},
                "blocking_evidence": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "parent_note": {"type": "string"},
                "key_observations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                },
                "next_action": {"type": "string"},
                "answer_analysis": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "optimal_answer": {"type": "string"},
                        "optimal_solution_steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 6,
                        },
                        "child_answer_summary": {"type": "string"},
                        "comparison": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "dimension": {
                                        "type": "string",
                                        "enum": [
                                            "final_answer",
                                            "model_or_relation",
                                            "steps",
                                            "symbols_units",
                                            "check_or_explanation",
                                            "other",
                                        ],
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["matched", "missing", "incorrect", "unclear", "alternative_valid"],
                                    },
                                    "detail": {"type": "string"},
                                },
                                "required": ["dimension", "status", "detail"],
                            },
                            "maxItems": 8,
                        },
                        "alternative_solutions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "process_gap": {"type": "string"},
                        "evaluation_support": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "usable_for_evaluation": {"type": "boolean"},
                                "evidence_strength": {
                                    "type": "string",
                                    "enum": sorted(db.ANALYSIS_EVIDENCE_STRENGTHS),
                                },
                                "reasoning_soundness": {
                                    "type": "string",
                                    "enum": sorted(db.ANALYSIS_REASONING_SOUNDNESS),
                                },
                                "dominant_gap_dimensions": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": sorted(db.REQUIRED_ANALYSIS_DIMENSIONS),
                                    },
                                    "maxItems": 5,
                                },
                                "needs_clearer_evidence": {"type": "boolean"},
                                "next_evidence_need": {
                                    "type": "string",
                                    "enum": sorted(db.ANALYSIS_NEXT_EVIDENCE_NEEDS),
                                },
                            },
                            "required": [
                                "usable_for_evaluation",
                                "evidence_strength",
                                "reasoning_soundness",
                                "dominant_gap_dimensions",
                                "needs_clearer_evidence",
                                "next_evidence_need",
                            ],
                        },
                        "teaching_explanation": {"type": "string"},
                        "next_child_prompt": {"type": "string"},
                    },
                    "required": [
                        "optimal_answer",
                        "optimal_solution_steps",
                        "child_answer_summary",
                        "comparison",
                        "alternative_solutions",
                        "process_gap",
                        "evaluation_support",
                        "teaching_explanation",
                        "next_child_prompt",
                    ],
                },
            },
            "required": [
                "result",
                "score_points",
                "max_points",
                "error_tags",
                "explanation_score",
                "blocking_evidence",
                "confidence",
                "parent_note",
                "key_observations",
                "next_action",
                "answer_analysis",
            ],
        },
    }


def _call_openai_evaluator(
    question: dict[str, Any],
    answer: str,
    *,
    answer_photo_data_url: str | None,
    answer_photo_ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route = model_router.answer_analysis_route()
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": _review_prompt(question, answer, answer_photo_ocr=answer_photo_ocr),
    }]
    if answer_photo_data_url:
        content.append({"type": "input_image", "image_url": answer_photo_data_url})
    payload = {
        "instructions": "You are a careful Chinese middle-school math evaluator. Return only valid JSON.",
        "input": [{"role": "user", "content": content}],
    }
    try:
        result = model_router.call_structured_json(
            route,
            payload,
            schema=_response_schema(),
            plain_json_instruction="Return only valid JSON matching the output_contract exactly; no markdown.",
        )
        return result.value
    except model_router.ModelCallError as exc:
        if model_router.is_retryable_model_call_error(exc):
            raise
        raise AIReviewError("AI 评估返回格式不可用，需系统待分析。") from exc


def _is_unsupported_json_schema_error(exc: Exception) -> bool:
    return model_router.is_response_format_unsupported_error(exc)


def _loads_model_json_object(text: str) -> dict[str, Any]:
    return model_router.loads_model_json_object(text)


def _extract_first_json_object(text: str) -> str:
    return model_router.extract_first_json_object(text)


def _extract_response_text(data: dict[str, Any]) -> str:
    return model_router.extract_response_text(data)


def _photo_ocr_response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "math_answer_photo_ocr",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["usable", "unclear"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "transcript": {"type": "string"},
                "math_objects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 12,
                },
                "notes": {"type": "string"},
            },
            "required": ["status", "confidence", "transcript", "math_objects", "notes"],
        },
    }


def _handwriting_input_response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "math_handwriting_input_recognition",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["usable", "unclear"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "transcript": {"type": "string"},
                "math_tokens": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 24,
                },
                "critical_token_uncertainties": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "token": {"type": "string"},
                            "location": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["token", "location", "reason"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": [
                "status",
                "confidence",
                "transcript",
                "math_tokens",
                "critical_token_uncertainties",
                "notes",
            ],
        },
    }


def recognize_handwriting_input(
    question: dict[str, Any],
    handwriting_image_data_url: str,
) -> dict[str, Any]:
    route = model_router.answer_photo_vision_route()
    if not route.enabled:
        return {
            "status": "not_configured",
            "confidence": 0.0,
            "transcript": "",
            "math_tokens": [],
            "critical_token_uncertainties": [],
            "notes": "vision model route is not configured",
        }
    prompt = json.dumps(
        {
            "role": "single_child_math_handwriting_input_reader",
            "task": "Transcribe only the child's handwritten answer. Do not solve, grade, or silently repair it.",
            "question_context": {
                "prompt": question.get("prompt"),
                "answer_format": question.get("answer_format"),
            },
            "recognition_rules": [
                "Preserve line order and mathematical notation.",
                "Never silently correct minus signs, decimal points, fraction bars, exponents, parentheses, equality or inequality signs.",
                "When any critical token is uncertain, list it in critical_token_uncertainties and explain the visible ambiguity in Chinese.",
                "Prefer unclear over inventing a symbol or missing step.",
                "Return Chinese transcript and notes.",
            ],
        },
        ensure_ascii=False,
    )
    result = model_router.call_structured_json(
        route,
        {
            "instructions": "You are a careful math handwriting transcription model. Return only valid JSON.",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": handwriting_image_data_url},
                    ],
                }
            ],
        },
        schema=_handwriting_input_response_schema(),
        plain_json_instruction="Return only JSON matching the schema; no markdown.",
    )
    raw = result.value
    status = str(raw.get("status") or "")
    if status not in {"usable", "unclear"}:
        raise ValueError("invalid handwriting recognition status")
    confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
    transcript = str(raw.get("transcript") or "").strip()[:4000]
    uncertainties = raw.get("critical_token_uncertainties")
    if not isinstance(uncertainties, list):
        raise ValueError("invalid handwriting critical token uncertainties")
    normalized_uncertainties = [
        {
            "token": str(item.get("token") or "")[:40],
            "location": str(item.get("location") or "")[:120],
            "reason": str(item.get("reason") or "")[:240],
        }
        for item in uncertainties[:12]
        if isinstance(item, dict)
    ]
    if status == "usable" and (not transcript or confidence < MIN_PHOTO_OCR_CONFIDENCE):
        status = "unclear"
    return {
        "status": status,
        "confidence": confidence,
        "transcript": transcript,
        "math_tokens": [str(value)[:80] for value in (raw.get("math_tokens") or [])[:24]],
        "critical_token_uncertainties": normalized_uncertainties,
        "notes": str(raw.get("notes") or "")[:500],
    }


def _review_answer_photo(
    question: dict[str, Any],
    answer: str,
    answer_photo_data_url: str,
) -> dict[str, Any]:
    route = model_router.answer_photo_vision_route()
    metadata = {
        "route": {
            "provider": route.provider if route.enabled else "",
            "model": route.model if route.enabled else "",
            "model_alias": route.model_alias if route.enabled else "",
        }
    }
    if not route.enabled:
        return {
            **metadata,
            "status": "not_configured",
            "confidence": 0.0,
            "transcript": "",
            "math_objects": [],
            "notes": "vision model route is not configured",
        }
    prompt = json.dumps(
        {
            "role": "single_child_math_answer_photo_reader",
            "task": "Read the child's handwritten or photographed math answer. Transcribe visible equations, steps, diagrams, corrections, units, and any final answer. Do not solve the problem beyond explaining what is visible.",
            "expert_operating_standard": [
                "Act like a careful math-answer transcription specialist.",
                "Your output is untrusted OCR evidence for another evaluator, not the final mathematical judgment.",
                "Prefer marking unclear over inventing missing symbols or steps.",
                "Keep line order and mathematical notation as visible as possible.",
            ],
            "question_context": {
                "prompt": question.get("prompt"),
                "answer_format": question.get("answer_format"),
            },
            "child_typed_answer": answer,
            "output_contract": {
                "status": "usable when the visible answer and steps can be read; unclear otherwise",
                "confidence": "0.0 to 1.0 OCR/transcription confidence",
                "transcript": "Chinese transcription of visible work, including equations and line breaks where helpful",
                "math_objects": "short list of equations/expressions/diagram labels visible in the photo",
                "notes": "visibility issues or ambiguity",
            },
        },
        ensure_ascii=False,
    )
    payload = {
        "instructions": "You are a careful math answer photo transcription model. Return only valid JSON.",
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": answer_photo_data_url},
            ],
        }],
    }
    try:
        result = model_router.call_structured_json(
            route,
            payload,
            schema=_photo_ocr_response_schema(),
            plain_json_instruction="Return only valid JSON matching the output_contract exactly; no markdown.",
        )
        return _normalize_photo_ocr(result.value, metadata)
    except model_router.ModelCallError as exc:
        if model_router.is_retryable_model_call_error(exc):
            raise
        return {
            **metadata,
            "status": "error",
            "confidence": 0.0,
            "transcript": "",
            "math_objects": [],
            "notes": str(exc)[:360],
        }
    except (KeyError, TypeError, ValueError) as exc:
        return {
            **metadata,
            "status": "error",
            "confidence": 0.0,
            "transcript": "",
            "math_objects": [],
            "notes": str(exc)[:360],
        }


def _normalize_photo_ocr(raw: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status")
    if status not in {"usable", "unclear"}:
        raise ValueError("invalid photo OCR status")
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid photo OCR confidence") from exc
    transcript = str(raw.get("transcript") or "").strip()[:2400]
    math_objects_raw = raw.get("math_objects")
    if not isinstance(math_objects_raw, list):
        raise ValueError("invalid photo OCR math objects")
    math_objects = [str(item).strip()[:180] for item in math_objects_raw[:12] if str(item).strip()]
    notes = str(raw.get("notes") or "").strip()[:500]
    if status == "usable" and (confidence < MIN_PHOTO_OCR_CONFIDENCE or not transcript):
        status = "unclear"
    return {
        **metadata,
        "status": status,
        "confidence": confidence,
        "transcript": transcript,
        "math_objects": math_objects,
        "notes": notes,
    }


def _photo_ocr_is_usable(value: dict[str, Any] | None) -> bool:
    if not value:
        return False
    return (
        value.get("status") == "usable"
        and float(value.get("confidence") or 0.0) >= MIN_PHOTO_OCR_CONFIDENCE
        and bool(str(value.get("transcript") or "").strip())
    )


def _photo_ocr_audit(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    route = value.get("route") if isinstance(value.get("route"), dict) else {}
    return {
        "status": value.get("status", ""),
        "confidence": float(value.get("confidence") or 0.0),
        "provider": route.get("provider", ""),
        "model": route.get("model", ""),
        "model_alias": route.get("model_alias", ""),
        "has_transcript": bool(str(value.get("transcript") or "").strip()),
        "transcript": str(value.get("transcript") or "")[:1200],
        "math_objects": value.get("math_objects", []) if isinstance(value.get("math_objects"), list) else [],
        "notes": str(value.get("notes") or "")[:360],
    }


def _normalize_ai_review(review: dict[str, Any], *, strict_analysis: bool = True) -> dict[str, Any]:
    result = review.get("result")
    if result not in {"correct", "partial", "wrong"}:
        raise AIReviewError("AI 评估结果无效，需 Codex 处理。")
    score = float(review.get("score_points", 0))
    if result == "correct":
        score = 2
    elif result == "partial":
        score = 1
    else:
        score = 0
    tags = [tag for tag in review.get("error_tags", []) if tag in CANONICAL_ERROR_TAGS]
    if result == "correct":
        tags = []
    elif not tags:
        tags = ["general"]
    explanation_score = int(review.get("explanation_score", 0))
    if explanation_score not in {0, 1, 2}:
        explanation_score = 0
    if result == "correct" and explanation_score < 2:
        result = "partial"
        score = 1
        if not tags:
            tags = ["process_habit"]
    confidence = max(0.0, min(1.0, float(review.get("confidence", 0))))
    analysis = _normalize_answer_analysis(review.get("answer_analysis"), strict=strict_analysis)
    parent_note = str(review.get("parent_note") or "已根据答案、步骤和参考 rubric 完成判断。").strip()
    support = analysis.get("evaluation_support") if isinstance(analysis.get("evaluation_support"), dict) else {}
    if result == "correct" and _analysis_blocks_full_credit(support):
        result = "partial"
        score = 1
        explanation_score = min(explanation_score, 1)
        tags = _merge_gap_tags(tags, support)
        if not tags:
            tags = ["process_habit"]
        parent_note = "AI 结构化分析仍显示过程或结论证据有缺口，不能判定为完全掌握。"
    return {
        "result": result,
        "score_points": score,
        "max_points": 2,
        "error_tags": tags,
        "explanation_score": explanation_score,
        "blocking_evidence": bool(review.get("blocking_evidence", False)) and result == "wrong",
        "confidence": confidence,
        "parent_note": parent_note[:240],
        "key_observations": [str(item)[:160] for item in review.get("key_observations", [])[:5]],
        "next_action": str(review.get("next_action") or "")[:160],
        "analysis": analysis,
    }


def _analysis_blocks_full_credit(support: dict[str, Any]) -> bool:
    return (
        support.get("usable_for_evaluation") is not True
        or support.get("reasoning_soundness") != "sound"
        or support.get("evidence_strength") != "strong"
        or support.get("needs_clearer_evidence") is True
        or bool(support.get("dominant_gap_dimensions"))
        or support.get("next_evidence_need") != "none"
    )


def _merge_gap_tags(tags: list[str], support: dict[str, Any]) -> list[str]:
    merged = [tag for tag in tags if tag in CANONICAL_ERROR_TAGS]
    for dimension in support.get("dominant_gap_dimensions") or []:
        tag = DIMENSION_GAP_ERROR_TAGS.get(str(dimension))
        if tag and tag not in merged:
            merged.append(tag)
    return merged[:4]


def _normalize_answer_analysis(raw: Any, *, strict: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AIReviewError("AI 答案分析缺失，需系统待分析。")

    def clean_text(key: str, limit: int) -> str:
        value = raw.get(key)
        if not isinstance(value, str):
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        return value.strip()[:limit]

    def clean_string_list(key: str, *, limit: int, item_limit: int) -> list[str]:
        value = raw.get(key)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        items: list[str] = []
        for item in value[:limit]:
            if not isinstance(item, str):
                raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
            text = item.strip()
            if text:
                items.append(text[:item_limit])
        return items

    comparison_raw = raw.get("comparison")
    if not isinstance(comparison_raw, list):
        raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
    comparison = []
    for item in comparison_raw[:8]:
        if not isinstance(item, dict):
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        normalized_item = item
        dimension = normalized_item.get("dimension")
        status = normalized_item.get("status")
        detail = normalized_item.get("detail")
        if dimension not in {"final_answer", "model_or_relation", "steps", "symbols_units", "check_or_explanation", "other"}:
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        if status not in {"matched", "missing", "incorrect", "unclear", "alternative_valid"}:
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        if not isinstance(detail, str):
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。")
        comparison.append({
            "dimension": dimension,
            "status": status,
            "detail": detail.strip()[:240],
        })

    analysis = {
        "agent_key": "answer_analysis_agent",
        "optimal_answer": clean_text("optimal_answer", 500),
        "optimal_solution_steps": clean_string_list("optimal_solution_steps", limit=6, item_limit=280),
        "child_answer_summary": clean_text("child_answer_summary", 500),
        "comparison": comparison,
        "alternative_solutions": clean_string_list("alternative_solutions", limit=4, item_limit=320),
        "process_gap": clean_text("process_gap", 500),
        "teaching_explanation": clean_text("teaching_explanation", 1800),
        "next_child_prompt": clean_text("next_child_prompt", 360),
    }
    comparison_statuses = {
        item["dimension"]: item["status"]
        for item in comparison
        if item.get("dimension") in db.REQUIRED_ANALYSIS_DIMENSIONS
    }
    if (
        not analysis["process_gap"]
        and db.REQUIRED_ANALYSIS_DIMENSIONS <= set(comparison_statuses)
        and not any(status in db.WEAK_ANALYSIS_STATUSES for status in comparison_statuses.values())
    ):
        analysis["no_gap_observed"] = True
    _refresh_evaluation_support(analysis)
    if strict:
        try:
            db.validate_answer_analysis(analysis)
        except ValueError as exc:
            raise AIReviewError("AI 答案分析返回格式不可用，需系统待分析。") from exc
    return analysis
