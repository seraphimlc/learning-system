from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import answer_contract_review, internal_agents, model_router


KNOWLEDGE_ROOT = internal_agents.PROJECT_ROOT / "learning_system/agent_knowledge"

V5_PROVIDER_MODES = {
    "live_model",
    "recorded_model",
    "mock_only",
    "not_configured",
    "deterministic_runtime",
}

V5_MODEL_AGENT_PHASES = {
    "answer_analysis": "answer_analysis_agent",
    "answer_contract_design": "answer_contract_designer_agent",
    "answer_contract_design_v2": "answer_contract_designer_agent",
    "answer_contract_review": "answer_contract_reviewer_agent",
    "answer_contract_review_v2": "answer_contract_reviewer_agent",
    "evaluation_update": "evaluation_agent",
    "planner_decision": "planner_agent",
    "teaching_generation": "teaching_agent",
}

KNOWLEDGE_PACKS_BY_AGENT = {
    "answer_analysis_agent": "answer_evidence.v1.md",
    "evaluation_agent": "mastery_evaluation.v1.md",
    "planner_agent": "adaptive_planning.v1.md",
    "teaching_agent": "teaching_interventions.v1.md",
}


@dataclass(frozen=True)
class SemanticAgentRequest:
    agent_key: str
    phase: str
    trusted_context: dict[str, Any]
    untrusted_payload: dict[str, Any]
    provider_mode: str = "not_configured"
    source_refs: dict[str, Any] = field(default_factory=dict)
    transport_timeout_seconds: float | None = None
    contract_version_suffix: str | None = None
    operation_idempotency_source: str = ""


@dataclass(frozen=True)
class SemanticAgentEnvelope:
    agent_key: str
    phase: str
    status: str
    provider_mode: str
    retryable: bool
    confidence: float
    output: dict[str, Any]
    validation_errors: tuple[str, ...] = ()
    error_reason: str = ""
    route_meta: dict[str, Any] = field(default_factory=dict)
    prompt_version_id: str = ""
    response_schema_version: str = ""

    def as_result_refs(self) -> dict[str, Any]:
        return {
            "agent_key": self.agent_key,
            "phase": self.phase,
            "status": self.status,
            "provider_mode": self.provider_mode,
            "retryable": self.retryable,
            "confidence": self.confidence,
            "validation_errors": list(self.validation_errors),
            "error_reason": self.error_reason,
            "prompt_version_id": self.prompt_version_id,
            "response_schema_version": self.response_schema_version,
        }


def blocked_envelope(
    *,
    agent_key: str,
    phase: str,
    reason: str,
    provider_mode: str = "not_configured",
    retryable: bool = False,
    contract_version_suffix: str | None = None,
) -> SemanticAgentEnvelope:
    if provider_mode not in V5_PROVIDER_MODES:
        provider_mode = "not_configured"
    contract = (
        internal_agents.load_contract_for_agent_version(
            agent_key, contract_version_suffix
        )
        if contract_version_suffix is not None
        else internal_agents.load_v5_contract_for_agent(agent_key)
    )
    return SemanticAgentEnvelope(
        agent_key=agent_key,
        phase=phase,
        status="blocked",
        provider_mode=provider_mode,
        retryable=retryable,
        confidence=0.0,
        output={},
        validation_errors=("not_implemented",),
        error_reason=reason,
        prompt_version_id=str(contract.get("prompt_version_id") or ""),
        response_schema_version=str(contract.get("response_schema_version") or ""),
    )


def accepted_envelope(
    *,
    agent_key: str,
    phase: str,
    output: dict[str, Any],
    provider_mode: str,
    confidence: float | None = None,
    route_meta: dict[str, Any] | None = None,
    contract_version_suffix: str | None = None,
) -> SemanticAgentEnvelope:
    if provider_mode not in V5_PROVIDER_MODES:
        provider_mode = "not_configured"
    contract = (
        internal_agents.load_contract_for_agent_version(
            agent_key, contract_version_suffix
        )
        if contract_version_suffix is not None
        else internal_agents.load_v5_contract_for_agent(agent_key)
    )
    return SemanticAgentEnvelope(
        agent_key=agent_key,
        phase=phase,
        status="accepted",
        provider_mode=provider_mode,
        retryable=False,
        confidence=float(confidence if confidence is not None else output.get("confidence") or 0.0),
        output=dict(output),
        route_meta=route_meta or {},
        prompt_version_id=str(contract.get("prompt_version_id") or ""),
        response_schema_version=str(contract.get("response_schema_version") or ""),
    )


def knowledge_pack_metadata(agent_key: str) -> dict[str, Any]:
    path = _knowledge_pack_path(agent_key)
    if not path.exists():
        return {}
    return {
        "knowledge_pack_path": str(path.relative_to(internal_agents.PROJECT_ROOT)),
        "knowledge_pack_version": path.stem,
        "knowledge_pack_sha256": internal_agents.file_sha256(path),
    }


def route_provider_mode(route: model_router.ModelRoute) -> str:
    if not route.enabled:
        return "not_configured"
    if route.provider in {"recorded_model", "mock_only"}:
        return route.provider
    return "live_model"


def retryable_from_exception(exc: Exception) -> bool:
    return model_router.is_retryable_model_call_error(exc)


def _recorded_output(request: SemanticAgentRequest) -> dict[str, Any] | None:
    for container in (request.trusted_context, request.source_refs):
        output = container.get("recorded_agent_output") if isinstance(container, dict) else None
        if isinstance(output, dict):
            return dict(output)
    return None


def _semantic_output_confidence(output: dict[str, Any]) -> float:
    items = output.get("items")
    if isinstance(items, list) and items:
        confidences = [
            item.get("confidence")
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("confidence"), (int, float))
            and not isinstance(item.get("confidence"), bool)
        ]
        if len(confidences) == len(items):
            return float(min(confidences))
    return float(output.get("confidence") or 0.0)


def _has_explicit_recorded_fixture(request: SemanticAgentRequest) -> bool:
    containers = (request.trusted_context, request.source_refs)
    for container in containers:
        if not isinstance(container, dict):
            continue
        if container.get("recorded_fixture_path") or container.get("recorded_fixture_id"):
            return True
        route_meta = container.get("route_meta")
        if isinstance(route_meta, dict) and (route_meta.get("recorded_fixture_path") or route_meta.get("recorded_fixture_id")):
            return True
    return False


def _route_for_phase(phase: str) -> model_router.ModelRoute:
    if phase == "answer_contract_design":
        return model_router.answer_contract_design_route()
    if phase == "answer_contract_design_v2":
        return model_router.answer_contract_design_v2_route()
    if phase == "answer_contract_review":
        return model_router.answer_contract_review_route()
    if phase == "answer_contract_review_v2":
        return model_router.answer_contract_review_v2_route()
    if phase == "answer_analysis":
        return model_router.answer_analysis_route()
    if phase == "evaluation_update":
        return model_router.evaluation_route()
    if phase == "planner_decision":
        return model_router.planner_route()
    if phase == "teaching_generation":
        return model_router.teaching_route()
    return model_router.answer_analysis_route()


def _knowledge_pack_path(agent_key: str) -> Path:
    filename = KNOWLEDGE_PACKS_BY_AGENT.get(agent_key, "")
    return KNOWLEDGE_ROOT / filename if filename else KNOWLEDGE_ROOT / "_missing.md"


def _load_knowledge_pack(agent_key: str) -> str:
    path = _knowledge_pack_path(agent_key)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _render_prompt(contract: dict[str, Any], request: SemanticAgentRequest) -> str:
    path = internal_agents.prompt_path_for_contract(contract)
    template = path.read_text(encoding="utf-8") if path.exists() else "{trusted_context_json}\n{untrusted_payload_json}"
    return template.format(
        trusted_context_json=json.dumps(request.trusted_context, ensure_ascii=False, sort_keys=True),
        untrusted_payload_json=json.dumps(request.untrusted_payload, ensure_ascii=False, sort_keys=True),
        knowledge_pack=_load_knowledge_pack(request.agent_key),
    )


def _contract_for_request(request: SemanticAgentRequest) -> dict[str, Any]:
    if request.contract_version_suffix is None:
        return internal_agents.load_v5_contract_for_agent(request.agent_key)
    return internal_agents.load_contract_for_agent_version(
        request.agent_key, request.contract_version_suffix
    )


def rendered_prompt_sha256_for_request(request: SemanticAgentRequest) -> str:
    contract = _contract_for_request(request)
    return hashlib.sha256(_render_prompt(contract, request).encode("utf-8")).hexdigest()


def _schema_for_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return contract.get("response_schema") if isinstance(contract.get("response_schema"), dict) else {}


def _validate_output_against_contract(contract: dict[str, Any], output: dict[str, Any], *, phase: str) -> None:
    errors = _validate_schema_value(_schema_for_contract(contract), output, "$")
    if errors:
        detail = "; ".join(errors[:8])
        raise model_router.ModelJSONParseError(f"{phase} output does not match schema: {detail}")
    if phase == "answer_contract_review":
        try:
            answer_contract_review.validate_review_output_shape(output.get("items"))
        except (TypeError, ValueError) as exc:
            raise model_router.ModelJSONParseError(
                f"{phase} output fails local semantic validation: {exc}"
            ) from exc
    if phase == "answer_contract_review_v2":
        try:
            answer_contract_review.validate_review_v2_output_shape(
                output.get("items")
            )
        except (TypeError, ValueError) as exc:
            raise model_router.ModelJSONParseError(
                f"{phase} output fails local semantic validation: {exc}"
            ) from exc


def _hash_route_meta_for_request(
    contract: dict[str, Any],
    request: SemanticAgentRequest,
    *,
    raw_response: dict[str, Any] | None = None,
    structured_json_mode: str = "recorded_json",
) -> dict[str, Any]:
    prompt = _render_prompt(contract, request)
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    schema = _schema_for_contract(contract)
    meta = {
        "structured_json_mode": structured_json_mode,
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path) if prompt_path.exists() else "",
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_schema_sha256": internal_agents.canonical_json_sha256(schema),
        **knowledge_pack_metadata(request.agent_key),
    }
    if raw_response is not None:
        meta["raw_response_sha256"] = hashlib.sha256(
            json.dumps(raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    return meta


def _validate_schema_value(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    if not isinstance(schema, dict) or not schema:
        return []
    errors: list[str] = []
    if isinstance(schema.get("not"), dict):
        if not _validate_schema_value(schema["not"], value, path):
            errors.append(f"{path}: value matches forbidden schema")
            return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
        return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum")
        return errors
    schema_type = schema.get("type")
    if schema_type:
        type_errors = _schema_type_errors(schema_type, value, path)
        if type_errors:
            return type_errors
    if isinstance(value, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: missing required key")
        additional = schema.get("additionalProperties", True)
        property_names = schema.get("propertyNames")
        if isinstance(property_names, dict):
            for key in value:
                errors.extend(_validate_schema_value(property_names, key, f"{path}.<propertyName>"))
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                errors.extend(_validate_schema_value(properties[key], child, child_path))
            elif additional is False:
                errors.append(f"{child_path}: additional property not allowed")
            elif isinstance(additional, dict):
                errors.extend(_validate_schema_value(additional, child, child_path))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: expected at most {schema['maxItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_schema_value(item_schema, item, f"{path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema:
            try:
                matched = re.search(str(schema["pattern"]), value, re.IGNORECASE)
            except re.error as exc:
                errors.append(f"{path}: invalid schema pattern: {exc}")
            else:
                if matched is None:
                    errors.append(f"{path}: string does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < float(schema["minimum"]):
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > float(schema["maximum"]):
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


def _schema_type_errors(schema_type: Any, value: Any, path: str) -> list[str]:
    allowed = schema_type if isinstance(schema_type, list) else [schema_type]
    for item in allowed:
        if item == "object" and isinstance(value, dict):
            return []
        if item == "array" and isinstance(value, list):
            return []
        if item == "string" and isinstance(value, str):
            return []
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return []
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return []
        if item == "boolean" and isinstance(value, bool):
            return []
        if item == "null" and value is None:
            return []
    return [f"{path}: expected type {schema_type!r}"]


def _call_agent(request: SemanticAgentRequest) -> SemanticAgentEnvelope:
    expected_agent = V5_MODEL_AGENT_PHASES.get(request.phase)
    if expected_agent is None or request.agent_key != expected_agent:
        raise ValueError(
            f"semantic route identity mismatch: {request.agent_key}:{request.phase}"
        )
    contract = _contract_for_request(request)
    recorded = _recorded_output(request)
    if recorded is not None:
        if request.provider_mode not in {"recorded_model", "mock_only"} and not _has_explicit_recorded_fixture(request):
            return blocked_envelope(
                agent_key=request.agent_key,
                phase=request.phase,
                provider_mode=request.provider_mode,
                reason=f"{request.phase} recorded output requires recorded_model/mock_only or explicit fixture lineage.",
                contract_version_suffix=request.contract_version_suffix,
            )
        _validate_output_against_contract(contract, recorded, phase=request.phase)
        return accepted_envelope(
            agent_key=request.agent_key,
            phase=request.phase,
            output=recorded,
            provider_mode=request.provider_mode if request.provider_mode in {"recorded_model", "mock_only"} else "recorded_model",
            confidence=_semantic_output_confidence(recorded),
            route_meta={
                "source": "recorded_agent_output",
                **_hash_route_meta_for_request(
                    contract,
                    request,
                    raw_response={"recorded_agent_output": recorded},
                    structured_json_mode="recorded_json",
                ),
            },
            contract_version_suffix=request.contract_version_suffix,
        )

    route = _route_for_phase(request.phase)
    if (
        isinstance(request.transport_timeout_seconds, (int, float))
        and not isinstance(request.transport_timeout_seconds, bool)
        and request.transport_timeout_seconds > 0
    ):
        route = replace(
            route,
            timeout_seconds=min(
                float(route.timeout_seconds),
                float(request.transport_timeout_seconds),
            ),
        )
    provider_mode = route_provider_mode(route)
    if provider_mode == "not_configured":
        return blocked_envelope(
            agent_key=request.agent_key,
            phase=request.phase,
            provider_mode="not_configured",
            reason=f"{request.agent_key}:{request.phase} model route is not configured.",
            contract_version_suffix=request.contract_version_suffix,
        )
    if provider_mode in {"recorded_model", "mock_only"}:
        return blocked_envelope(
            agent_key=request.agent_key,
            phase=request.phase,
            provider_mode=provider_mode,
            reason=f"{provider_mode} requires recorded_agent_output for {request.phase}.",
            contract_version_suffix=request.contract_version_suffix,
        )

    prompt = _render_prompt(contract, request)
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    schema = _schema_for_contract(contract)
    payload = {
        "instructions": "You are a v5 math-learning semantic agent. Return only schema-valid JSON.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    try:
        result = model_router.call_structured_json(
            route,
            payload,
            schema=schema,
            retryable_errors_fallback=request.phase
                not in {
                    "answer_contract_review",
                    "answer_contract_design",
                    "answer_contract_review_v2",
                    "answer_contract_design_v2",
                },
            provider_idempotency_key=(
                request.operation_idempotency_source or None
            ),
        )
    except model_router.ModelJSONParseError as exc:
        raise exc
    except model_router.ModelCallError as exc:
        raise exc
    _validate_output_against_contract(contract, result.value, phase=request.phase)
    return accepted_envelope(
        agent_key=request.agent_key,
        phase=request.phase,
        output=result.value,
        provider_mode="live_model",
        confidence=_semantic_output_confidence(result.value),
        route_meta={
            **_hash_route_meta_for_request(
                contract,
                request,
                raw_response=result.raw_response,
                structured_json_mode=result.mode,
            ),
            "structured_json_endpoint": result.endpoint,
            "provider_idempotency_enabled": (
                result.provider_idempotency_enabled
            ),
            "provider_idempotency_key_digest_sha256": (
                result.provider_idempotency_key_digest_sha256
            ),
        },
        contract_version_suffix=request.contract_version_suffix,
    )


def call_answer_analysis_agent(request: SemanticAgentRequest) -> SemanticAgentEnvelope:
    return _call_agent(request)


def call_answer_contract_reviewer_agent(
    request: SemanticAgentRequest,
) -> SemanticAgentEnvelope:
    try:
        return _call_agent(request)
    except model_router.ModelJSONParseError as exc:
        raise ValueError(str(exc)) from exc


def call_answer_contract_designer_agent(
    request: SemanticAgentRequest,
) -> SemanticAgentEnvelope:
    try:
        return _call_agent(request)
    except model_router.ModelJSONParseError as exc:
        raise ValueError(str(exc)) from exc


def call_evaluation_agent(request: SemanticAgentRequest) -> SemanticAgentEnvelope:
    return _call_agent(request)


def call_planner_agent(request: SemanticAgentRequest) -> SemanticAgentEnvelope:
    return _call_agent(request)


def call_teaching_agent(request: SemanticAgentRequest) -> SemanticAgentEnvelope:
    return _call_agent(request)
