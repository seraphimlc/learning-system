"""Single-slot model worker for v20 brief production.

The model supplies semantic design only. Identity, graph binding, allocation,
lineage, status, and visual authority are injected from the trusted plan.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable, Iterable

from .. import model_router
from .slot_architecture import architecture_content_digest, graph_content_digest
from .slot_brief_generation import build_generation_packet, validate_generated_brief
from .slot_brief_inventory import brief_digest, contract_digest
from .slot_brief_review import policy_digest
from .v20_receipts import canonical_json, sha256_bytes, sha256_json


MODEL_OUTPUT_FIELDS = frozenset(
    {
        "design",
        "measurement_intent",
        "variation_policy",
        "collision",
        "answer_contract_shape",
    }
)


class SlotBriefWorkerError(RuntimeError):
    def __init__(self, message: str, *, model_output: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.model_output = deepcopy(model_output) if isinstance(model_output, dict) else None


MODEL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(MODEL_OUTPUT_FIELDS),
    "properties": {
        "design": {
            "type": "object",
            "additionalProperties": False,
            "required": ["purpose", "family_id", "risk_tier", "response_modality", "review_route_class"],
            "properties": {
                "purpose": {"type": "string", "enum": ["diagnostic", "guided", "practice", "challenge"]},
                "family_id": {"type": "string", "enum": ["concept_model", "guided_model_use", "independent_transfer", "controlled_challenge"]},
                "risk_tier": {"type": "string", "enum": ["R1", "R2"]},
                "response_modality": {"type": "string", "enum": ["text", "choice", "fill", "photo", "voice", "handwriting", "visual_interactive"]},
                "review_route_class": {"type": "string"},
            },
        },
        "measurement_intent": {
            "type": "object",
            "additionalProperties": False,
            "required": ["intent_id", "target", "observable_evidence", "failure_signal", "non_goal"],
            "properties": {field: {"type": "string"} for field in (
                "intent_id", "target", "observable_evidence", "failure_signal", "non_goal"
            )},
        },
        "variation_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["allowed_variations", "forbidden_surface_patterns"],
            "properties": {
                "allowed_variations": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "forbidden_surface_patterns": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
        },
        "collision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["collision_group_id", "distinctness_basis"],
            "properties": {
                "collision_group_id": {"type": "string"},
                "distinctness_basis": {"type": "string"},
            },
        },
        "answer_contract_shape": {
            "type": "object",
            "additionalProperties": False,
            "required": ["contract_schema_id", "required_evidence_fields"],
            "properties": {
                "contract_schema_id": {"type": "string"},
                "required_evidence_fields": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
        },
    },
}


def build_model_prompt(packet: dict[str, Any]) -> str:
    return (
        "你是数学题库的 slot brief 设计模型。只设计一个后续命题要求，不要生成具体题目。\n"
        "不得输出题干、数字、选项、答案、解法、评分点或具体情境。\n"
        "程序会注入 slot 身份、图谱绑定、分配桶、状态和所有 lineage；不要输出这些受信字段。\n"
        "design.family_id、purpose、risk_tier 必须使用 question_families 中的一组完全匹配的组合；"
        "response_modality 必须是该 family.allowed_modalities 中的单个精确值，不能写 text_or_choice、text/choice 或自造组合。\n"
        "请只返回符合 schema 的 JSON，定义一个可观察的学习测量目标、证据形状、变化边界和碰撞边界。\n"
        "如果输入包含 prior_reviewed_briefs，必须避开其中已有的测量目标和碰撞组；不能只换数字、语境、格式或答案顺序制造差异。\n"
        "输入 packet:\n" + json.dumps(packet, ensure_ascii=False, sort_keys=True)
    )


def brief_provider_idempotency_key(*, plan: dict[str, Any], packet: dict[str, Any], attempt: int) -> str:
    return sha256_json(
        {
            "operation_key": plan["operation_key"],
            "packet_sha256": sha256_bytes(canonical_json(packet).encode()),
            "brief_version": attempt,
        }
    )


def _validate_model_output(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict) or set(output) != MODEL_OUTPUT_FIELDS:
        raise SlotBriefWorkerError("model brief output fields are incomplete or contain trusted fields")
    expected_nested = {
        "design": {"purpose", "family_id", "risk_tier", "response_modality", "review_route_class"},
        "measurement_intent": {"intent_id", "target", "observable_evidence", "failure_signal", "non_goal"},
        "variation_policy": {"allowed_variations", "forbidden_surface_patterns"},
        "collision": {"collision_group_id", "distinctness_basis"},
        "answer_contract_shape": {"contract_schema_id", "required_evidence_fields"},
    }
    for field, expected in expected_nested.items():
        if not isinstance(output[field], dict) or set(output[field]) != expected:
            raise SlotBriefWorkerError(
                f"model brief output {field} fields are incomplete or contain trusted fields"
            )
    return deepcopy(output)


def build_brief_from_model_output(
    *,
    plan: dict[str, Any],
    model_output: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
    brief_version: int = 1,
) -> dict[str, Any]:
    output = _validate_model_output(model_output)
    bucket = plan["allocation"]["bucket"]
    visual_status = "conditional_pending_authority" if bucket == "visual_interactive" else "not_applicable"
    brief = {
        "schema_version": "question-slot-brief.v20",
        "slot_id": plan["slot_id"],
        "brief_version": brief_version,
        "operation_key": plan["operation_key"],
        "status": "DRAFT",
        "lineage": {
            "architecture_sha256": architecture_content_digest(architecture),
            "graph_version": architecture["graph_source"]["version"],
            "graph_sha256": graph_content_digest(graph),
            "generation_contract_sha256": contract_digest(contract),
            "review_policy_sha256": review_policy_sha256,
        },
        "allocation": {
            "bucket": bucket,
            "matrix_cell": f"{output['design']['family_id']}:{output['design']['purpose']}:{output['design']['response_modality']}",
        },
        "graph_binding": deepcopy(plan["graph_binding"]),
        "design": {
            **output["design"],
            "production_mode": contract["production_mode"],
        },
        "measurement_intent": output["measurement_intent"],
        "variation_policy": output["variation_policy"],
        "collision": output["collision"],
        "answer_contract_shape": output["answer_contract_shape"],
        "visual_authority": {
            "status": visual_status,
            "renderer_sha256": "",
            "resource_sha256": "",
            "answer_capture_sha256": "",
        },
        "review_evidence": {"receipt_set_sha256": "", "receipt_ids": []},
        "brief_sha256": "",
    }
    brief["brief_sha256"] = brief_digest(brief)
    try:
        return validate_generated_brief(
            plan=plan,
            brief=brief,
            graph_node_ids={str(node["id"]) for node in graph["nodes"]},
            graph=graph,
            architecture=architecture,
            contract=contract,
            review_policy_sha256=review_policy_sha256,
        )
    except Exception as exc:
        raise SlotBriefWorkerError(
            f"model brief failed trusted plan validation: {exc}"
        ) from exc


def run_one_slot(
    *,
    plan: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
    model_output: dict[str, Any] | None = None,
    model_call: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    prior_briefs: Iterable[dict[str, Any]] | None = None,
    attempt: int = 1,
    generation_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = generation_packet or build_generation_packet(
        plan=plan,
        architecture=architecture,
        graph=graph,
        contract=contract,
        prior_briefs=prior_briefs,
        attempt=attempt,
    )
    prompt = build_model_prompt(packet)
    if model_output is None:
        if model_call is not None:
            model_output = model_call(prompt, MODEL_OUTPUT_SCHEMA)
        else:
            route = model_router.slot_brief_designer_route()
            if not route.enabled:
                raise SlotBriefWorkerError("slot brief model route is not configured")
            try:
                result = model_router.call_structured_json_with_fallback(
                    route,
                    {
                        "instructions": "Return only schema-valid JSON for one slot brief. Do not generate a concrete question.",
                        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                        "temperature": 0,
                    },
                    schema=MODEL_OUTPUT_SCHEMA,
                    fallback_model_env="AI_SLOT_BRIEF_FALLBACK_MODEL",
                    plain_json_instruction="Return only valid JSON matching the slot brief design schema; no markdown.",
                    provider_idempotency_key=brief_provider_idempotency_key(
                        plan=plan, packet=packet, attempt=attempt
                    ),
                )
            except model_router.ModelCallError as exc:
                raise SlotBriefWorkerError(f"slot brief model call failed: {exc}") from exc
            model_output = result.value
    try:
        brief = build_brief_from_model_output(
            plan=plan,
            model_output=model_output,
            architecture=architecture,
            graph=graph,
            contract=contract,
            review_policy_sha256=review_policy_sha256,
        )
    except SlotBriefWorkerError as exc:
        if exc.model_output is None:
            exc.model_output = deepcopy(model_output)
        raise
    return {
        "slot_id": plan["slot_id"],
        "operation_key": plan["operation_key"],
        "brief": brief,
        "input_packet_sha256": sha256_bytes(canonical_json(packet).encode()),
        "prompt_sha256": sha256_bytes(prompt.encode()),
    }
