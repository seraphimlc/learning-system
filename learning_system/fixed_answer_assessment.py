"""Deterministic fixed-answer response envelope primitives.

Only wire parsing and canonical receipts live here in Task 1. Exact answer
grading and mastery effects are intentionally left to later tasks.
"""

from __future__ import annotations

from typing import Any, Mapping

from .question_quality import (
    FIXED_RESPONSE_SCHEMA_VERSION,
    canonical_sha256,
    canonical_json_bytes,
    loads_strict,
)


FIXED_ANSWER_RESPONSE_SCHEMA_VERSION = FIXED_RESPONSE_SCHEMA_VERSION
MAX_RESPONSE_BYTES = 16 * 1024
MAX_RESPONSE_ITEMS = 8
MAX_VALUE_LENGTH = 128
RESPONSE_TYPES = frozenset({"single_choice", "multi_choice", "fill_blank"})


def _object(value: Any, label: str = "response") -> dict[str, Any]:
    if not isinstance(value, dict) or value is None:
        raise ValueError(f"{label} must be a non-null object")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} contains unknown keys: {sorted(unknown)}")


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_VALUE_LENGTH:
        raise ValueError(f"{label} must be a bounded non-empty string")
    return value


def _parse(payload: Any) -> dict[str, Any]:
    if isinstance(payload, (str, bytes)):
        parsed = loads_strict(payload, max_bytes=MAX_RESPONSE_BYTES)
    else:
        # Structured callers have already parsed JSON; canonical size still
        # protects this boundary from an oversized in-memory envelope.
        parsed = payload
        try:
            if len(canonical_json_bytes(parsed)) > MAX_RESPONSE_BYTES:
                raise ValueError("response payload is oversized")
        except TypeError as exc:
            raise ValueError("response payload is not JSON-compatible") from exc
    return _object(parsed)


def parse_fixed_answer_response(payload: Any) -> dict[str, Any]:
    response = _parse(payload)
    _keys(response, {"schema_version", "type", "choice_id", "choice_ids", "fields"}, "response")
    if response.get("schema_version") != FIXED_RESPONSE_SCHEMA_VERSION:
        raise ValueError("unsupported fixed-answer response version")
    response_type = response.get("type")
    if response_type not in RESPONSE_TYPES:
        raise ValueError("invalid fixed-answer response type")

    if response_type == "single_choice":
        if set(response) != {"schema_version", "type", "choice_id"}:
            raise ValueError("single-choice response has incompatible fields")
        _id(response["choice_id"], "choice_id")
    elif response_type == "multi_choice":
        if set(response) != {"schema_version", "type", "choice_ids"}:
            raise ValueError("multi-choice response has incompatible fields")
        choice_ids = response["choice_ids"]
        if not isinstance(choice_ids, list) or not choice_ids or len(choice_ids) > MAX_RESPONSE_ITEMS:
            raise ValueError("choice_ids must contain 1-8 ids")
        normalized = [_id(choice_id, "choice_id") for choice_id in choice_ids]
        if len(set(normalized)) != len(normalized):
            raise ValueError("choice_ids must be unique")
    else:
        if set(response) != {"schema_version", "type", "fields"}:
            raise ValueError("fill-blank response has incompatible fields")
        fields = response["fields"]
        if not isinstance(fields, list) or len(fields) > MAX_RESPONSE_ITEMS:
            raise ValueError("fields must contain at most 8 entries")
        field_ids: set[str] = set()
        for field in fields:
            field = _object(field, "field")
            _keys(field, {"id", "value"}, "field")
            if set(field) != {"id", "value"}:
                raise ValueError("field requires id and value")
            field_id = _id(field["id"], "field.id")
            if field_id in field_ids:
                raise ValueError("field ids must be unique")
            field_ids.add(field_id)
            if not isinstance(field["value"], str) or len(field["value"]) > MAX_VALUE_LENGTH:
                raise ValueError("field.value must be a bounded string")
    return response


def response_digest(payload: Any) -> str:
    response = parse_fixed_answer_response(payload)
    if response["type"] == "multi_choice":
        response = {**response, "choice_ids": sorted(response["choice_ids"])}
    elif response["type"] == "fill_blank":
        response = {
            **response,
            "fields": sorted(response["fields"], key=lambda field: field["id"]),
        }
    return canonical_sha256(response)


validate_fixed_answer_response = parse_fixed_answer_response
