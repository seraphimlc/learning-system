"""Versioned question-quality and graph-evidence contract primitives.

This module deliberately stops at deterministic contract validation. Derivation,
question-bank activation, persistence, and model calls belong to later layers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence


REVIEW_PACKET_SCHEMA_VERSION = "review_packet.v1"
DISCOVERY_DERIVATION_SCHEMA_VERSION = "discovery_derivation.v1"
QUESTION_FINGERPRINT_POLICY_VERSION = "question_fingerprint.v2"
FIXED_RESPONSE_SCHEMA_VERSION = "2026-08-25.fixed-answer-response.v1"
GRAPH_EVIDENCE_CONTRACT_VERSION = "graph_evidence_contract.v1"

MAX_REVIEW_PACKET_BYTES = 64 * 1024
MAX_SOLUTION_STEPS = 8
MAX_PROMPT_SPANS = 8
MAX_CROSS_NODE_RELATIONS = 4

DECISION_TAXONOMIES = frozenset(
    {
        "classify_structure",
        "choose_representation",
        "select_model",
        "select_operation_order",
        "resolve_sign_scope",
        "choose_case_split",
        "identify_invariant",
        "construct_counterexample",
    }
)
DISCOVERY_DEPTHS = frozenset({"E0", "E1", "E2", "E3", "E4"})
ENTRY_POINT_VISIBILITIES = frozenset({"explicit", "cued", "implicit", "exploratory"})
MASTERY_STATES = frozenset({"A", "B", "C", "D"})
FIXED_ANSWER_POLICIES = frozenset({"observation_only", "confirmation_eligible"})

GRAPH_EVIDENCE_MAPPING = {
    "结果正确": "answer_correctness",
    "过程可复盘": "process_explanation",
    "能口头解释": "verbal_explanation",
    "能做一道小变式": "transfer",
}
CANONICAL_EVIDENCE_KEYS = frozenset(
    {
        "answer_correctness",
        "concept_recognition",
        "model_selection",
        "process_explanation",
        "symbols_units",
        "transfer",
        "verbal_explanation",
    }
)
PROCESS_EVIDENCE_KEYS = frozenset(
    {"process_explanation", "verbal_explanation", "transfer"}
)

_OPERATOR_MAP = {
    "−": "-",
    "–": "-",
    "—": "-",
    "﹣": "-",
    "＋": "+",
    "×": "*",
    "✕": "*",
    "·": "*",
    "⋅": "*",
    "÷": "/",
    "∕": "/",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "＝": "=",
}


def normalize_text(value: str) -> str:
    """Apply the shared Unicode, operator, line-ending, and whitespace rules."""
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    for source, target in _OPERATOR_MAP.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized).strip()


def _duplicate_key_rejector(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def loads_strict(payload: str | bytes, *, max_bytes: int | None = None) -> Any:
    """Parse JSON while rejecting duplicate keys and malformed UTF-8."""
    if isinstance(payload, bytes):
        raw = payload
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("JSON payload must be UTF-8") from exc
    elif isinstance(payload, str):
        text = payload
        raw = text.encode("utf-8")
    else:
        raise TypeError("JSON payload must be str or bytes")
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValueError("JSON payload is oversized")
    try:
        return json.loads(text, object_pairs_hook=_duplicate_key_rejector)
    except (json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            raise
        raise ValueError("invalid JSON payload") from exc


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("canonical JSON does not allow non-finite numbers")
    return value


def canonical_json(value: Any, *, set_array_paths: Iterable[tuple[str, ...]] = ()) -> str:
    """Serialize canonical JSON; array order is preserved by default."""
    if set_array_paths:
        value = canonicalize_set_arrays(value, paths=set_array_paths)
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(value: Any, *, set_array_paths: Iterable[tuple[str, ...]] = ()) -> bytes:
    return canonical_json(value, set_array_paths=set_array_paths).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any, *, set_array_paths: Iterable[tuple[str, ...]] = ()) -> str:
    return sha256_hex(canonical_json_bytes(value, set_array_paths=set_array_paths))


def sort_set_array(values: Iterable[Any]) -> list[Any]:
    """Sort a set-like array by each member's normalized canonical form."""
    normalized = []
    for value in values:
        if isinstance(value, str):
            value = normalize_text(value)
        normalized.append(value)
    return sorted(normalized, key=canonical_json)


def canonicalize_set_arrays(value: Any, *, paths: set[tuple[str, ...]] | Iterable[tuple[str, ...]]) -> Any:
    """Sort only arrays at explicitly declared object-key paths."""
    path_set = set(paths)

    def visit(current: Any, path: tuple[str, ...]) -> Any:
        if isinstance(current, Mapping):
            return {key: visit(item, path + (str(key),)) for key, item in current.items()}
        if isinstance(current, list):
            items = [visit(item, path) for item in current]
            return sort_set_array(items) if path in path_set else items
        return copy.deepcopy(current)

    return visit(value, ())


def prompt_tokens(prompt: str) -> list[str]:
    """Return the versioned prompt stream used by span offsets.

    Whitespace separates tokens after normalization. This intentionally keeps
    punctuation attached to its neighboring token, matching the prompt-level
    rather than model-token-level evidence contract.
    """
    normalized = normalize_text(prompt)
    return normalized.split(" ") if normalized else []


def _structural_token(token: str) -> str:
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", token):
        return "NUMBER"
    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", token):
        return "VARIABLE"
    return token


def prompt_span(prompt: str, *, start_token: int, end_token: int) -> dict[str, Any]:
    tokens = prompt_tokens(prompt)
    if not isinstance(start_token, int) or isinstance(start_token, bool):
        raise ValueError("start_token must be an integer")
    if not isinstance(end_token, int) or isinstance(end_token, bool):
        raise ValueError("end_token must be an integer")
    if start_token < 0 or end_token <= start_token or end_token > len(tokens):
        raise ValueError("prompt span is outside the canonical token stream")
    instance_tokens = tokens[start_token:end_token]
    structural_tokens = [_structural_token(token) for token in instance_tokens]
    return {
        "start_token": start_token,
        "end_token": end_token,
        "instance_hash": canonical_sha256({"tokens": instance_tokens}),
        "structural_hash": canonical_sha256({"tokens": structural_tokens}),
    }


def canonical_prompt_envelope(
    *, stem: str, choices: Sequence[Mapping[str, Any]] | None = None, fields: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Build the ordered, normalized prompt envelope used for prompt digests."""
    if not isinstance(stem, str):
        raise TypeError("prompt stem must be a string")
    envelope: dict[str, Any] = {"stem": normalize_text(stem)}
    if choices is not None:
        envelope["choices"] = [
            {str(key): normalize_text(value) if isinstance(value, str) else copy.deepcopy(value) for key, value in choice.items()}
            for choice in choices
        ]
    if fields is not None:
        envelope["fields"] = [
            {str(key): normalize_text(value) if isinstance(value, str) else copy.deepcopy(value) for key, value in field.items()}
            for field in fields
        ]
    return envelope


def prompt_sha256(envelope: Mapping[str, Any]) -> str:
    return canonical_sha256(envelope)


canonicalize_text = normalize_text
canonical_prompt = canonical_prompt_envelope
canonical_prompt_digest = prompt_sha256
canonical_prompt_span = prompt_span
sort_set_arrays = canonicalize_set_arrays


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value is None:
        raise ValueError(f"{label} must be a non-null object")
    return value


def _check_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} contains unknown keys: {sorted(unknown)}")


def _require_keys(value: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = required - set(value)
    if missing:
        raise ValueError(f"{label} is missing keys: {sorted(missing)}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _unique_ids(entries: Any, label: str) -> set[str]:
    if not isinstance(entries, list):
        raise ValueError(f"{label} must be an array")
    ids: set[str] = set()
    for entry in entries:
        item = _require_object(entry, f"{label} item")
        identifier = _nonempty_string(item.get("id"), f"{label}.id")
        if identifier in ids:
            raise ValueError(f"duplicate {label} id: {identifier}")
        ids.add(identifier)
    return ids


def _validate_solution_steps(steps: Any, span_ids: set[str] | None = None) -> set[str]:
    step_ids = _unique_ids(steps, "solution_steps")
    if len(steps) > MAX_SOLUTION_STEPS:
        raise ValueError("too many solution steps")
    for step in steps:
        _check_keys(
            step,
            {"id", "action", "evidence_key", "input_step_ids", "input_evidence_keys", "prompt_span_ids"},
            "solution_step",
        )
        _require_keys(
            step,
            {"id", "action", "evidence_key", "input_step_ids", "input_evidence_keys", "prompt_span_ids"},
            "solution_step",
        )
        _nonempty_string(step["action"], "solution_step.action")
        _nonempty_string(step["evidence_key"], "solution_step.evidence_key")
        for key in ("input_step_ids", "input_evidence_keys", "prompt_span_ids"):
            if not isinstance(step[key], list) or any(not isinstance(item, str) or not item for item in step[key]):
                raise ValueError(f"solution_step.{key} must be an array of non-empty strings")
        if len(set(step["input_step_ids"])) != len(step["input_step_ids"]):
            raise ValueError("duplicate solution step input id")
        if span_ids is not None and not set(step["prompt_span_ids"]).issubset(span_ids):
            raise ValueError("solution step references an unknown prompt span")
    for step in steps:
        if not set(step["input_step_ids"]).issubset(step_ids):
            raise ValueError("solution step references an unknown input step")
    _assert_acyclic({step["id"]: step["input_step_ids"] for step in steps}, "solution step")
    return step_ids


def _assert_acyclic(graph: Mapping[str, Sequence[str]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"{label} graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def validate_review_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    packet = _require_object(packet, "review packet")
    _check_keys(packet, {"schema_version", "reviewer_run_id", "prompt_spans", "solution_steps", "cross_node_prerequisite_relations"}, "review packet")
    _require_keys(packet, {"schema_version", "reviewer_run_id", "prompt_spans", "solution_steps", "cross_node_prerequisite_relations"}, "review packet")
    if packet["schema_version"] != REVIEW_PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported review packet version")
    _nonempty_string(packet["reviewer_run_id"], "reviewer_run_id")
    if not isinstance(packet["prompt_spans"], list) or len(packet["prompt_spans"]) > MAX_PROMPT_SPANS:
        raise ValueError("prompt_spans must contain at most 8 entries")
    span_ids = _unique_ids(packet["prompt_spans"], "prompt_spans")
    for span in packet["prompt_spans"]:
        _check_keys(span, {"id", "start_token", "end_token", "instance_hash", "structural_hash"}, "prompt_span")
        _require_keys(span, {"id", "start_token", "end_token", "instance_hash", "structural_hash"}, "prompt_span")
        if any(not isinstance(span[key], int) or isinstance(span[key], bool) for key in ("start_token", "end_token")):
            raise ValueError("prompt span offsets must be integers")
        if span["start_token"] < 0 or span["end_token"] <= span["start_token"]:
            raise ValueError("invalid prompt span offsets")
        _hash(span["instance_hash"], "prompt_span.instance_hash")
        _hash(span["structural_hash"], "prompt_span.structural_hash")
    _validate_solution_steps(packet["solution_steps"], span_ids)
    relations = packet["cross_node_prerequisite_relations"]
    if not isinstance(relations, list) or len(relations) > MAX_CROSS_NODE_RELATIONS:
        raise ValueError("too many cross-node prerequisite relations")
    _unique_ids(relations, "cross_node_prerequisite_relations")
    step_ids = {step["id"] for step in packet["solution_steps"]}
    for relation in relations:
        _check_keys(relation, {"id", "prerequisite_node_id", "evidence_key", "target_step_id"}, "cross-node relation")
        _require_keys(relation, {"id", "prerequisite_node_id", "evidence_key", "target_step_id"}, "cross-node relation")
        _nonempty_string(relation["prerequisite_node_id"], "relation.prerequisite_node_id")
        _nonempty_string(relation["evidence_key"], "relation.evidence_key")
        if relation["target_step_id"] not in step_ids:
            raise ValueError("relation references an unknown target step")
        target = next(step for step in packet["solution_steps"] if step["id"] == relation["target_step_id"])
        if relation["evidence_key"] not in target["input_evidence_keys"]:
            raise ValueError("relation evidence is not an input to the target step")
    if len(canonical_json_bytes(packet)) > MAX_REVIEW_PACKET_BYTES:
        raise ValueError("review packet is oversized")
    return copy.deepcopy(packet)


def validate_discovery_derivation_output(output: Mapping[str, Any]) -> dict[str, Any]:
    output = _require_object(output, "discovery derivation output")
    allowed = {"schema_version", "discovery_depth", "entry_point_visibility", "decision_points", "solution_families", "execution_steps", "key_insight_evidence_keys"}
    _check_keys(output, allowed, "discovery derivation output")
    _require_keys(output, allowed, "discovery derivation output")
    if output["schema_version"] != DISCOVERY_DERIVATION_SCHEMA_VERSION:
        raise ValueError("unsupported discovery derivation version")
    if output["discovery_depth"] not in DISCOVERY_DEPTHS:
        raise ValueError("invalid discovery depth")
    if output["entry_point_visibility"] not in ENTRY_POINT_VISIBILITIES:
        raise ValueError("invalid entry-point visibility")
    if not isinstance(output["execution_steps"], int) or isinstance(output["execution_steps"], bool) or output["execution_steps"] < 0:
        raise ValueError("execution_steps must be a non-negative integer")
    for key in ("decision_points", "solution_families", "key_insight_evidence_keys"):
        if not isinstance(output[key], list):
            raise ValueError(f"{key} must be an array")
    if len(output["decision_points"]) > 4 or len(output["solution_families"]) > 3:
        raise ValueError("too many decisions or solution families")
    decision_ids = _unique_ids(output["decision_points"], "decision_points")
    for decision in output["decision_points"]:
        _check_keys(decision, {"id", "taxonomy", "alternatives", "misconception_key", "step_ids", "structural_prompt_span_hashes", "depends_on"}, "decision point")
        _require_keys(decision, {"id", "taxonomy", "alternatives", "misconception_key", "step_ids", "structural_prompt_span_hashes", "depends_on"}, "decision point")
        if decision["taxonomy"] not in DECISION_TAXONOMIES:
            raise ValueError("invalid decision taxonomy")
        _nonempty_string(decision["misconception_key"], "decision.misconception_key")
        if not isinstance(decision["alternatives"], list) or not decision["alternatives"]:
            raise ValueError("decision alternatives must be non-empty")
        for key in ("alternatives", "step_ids", "depends_on"):
            if not isinstance(decision[key], list) or any(not isinstance(item, str) or not item for item in decision[key]):
                raise ValueError(f"decision.{key} must contain strings")
        if not isinstance(decision["structural_prompt_span_hashes"], list) or any(
            not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
            for item in decision["structural_prompt_span_hashes"]
        ):
            raise ValueError("invalid decision prompt span hash")
    for decision in output["decision_points"]:
        if not set(decision["depends_on"]).issubset(decision_ids):
            raise ValueError("decision depends_on references an unknown decision")
    _assert_acyclic({decision["id"]: decision["depends_on"] for decision in output["decision_points"]}, "decision")
    _unique_ids(output["solution_families"], "solution_families")
    for family in output["solution_families"]:
        _check_keys(family, {"id", "first_action", "step_ids", "structural_prompt_span_hashes"}, "solution family")
        _require_keys(family, {"id", "first_action", "step_ids", "structural_prompt_span_hashes"}, "solution family")
        _nonempty_string(family["first_action"], "family.first_action")
    if any(not isinstance(item, str) or not item for item in output["key_insight_evidence_keys"]):
        raise ValueError("key insight evidence keys must contain strings")
    return copy.deepcopy(output)


def _normalize_evidence_list(values: Any, label: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be an array")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} contains an invalid evidence value")
        key = GRAPH_EVIDENCE_MAPPING.get(value, value)
        if key not in CANONICAL_EVIDENCE_KEYS:
            raise ValueError(f"unmapped graph evidence value: {value}")
        if key in normalized:
            raise ValueError(f"duplicate graph evidence key: {key}")
        normalized.append(key)
    return sorted(normalized)


def normalize_graph_evidence_contract(graph_node: Mapping[str, Any]) -> dict[str, Any]:
    node = _require_object(graph_node, "graph node")
    if "evidence_keys" in node:
        raw_evidence = node["evidence_keys"]
    elif "evidence_required" in node:
        raw_evidence = node["evidence_required"]
    else:
        raw_evidence = []
    evidence_keys = _normalize_evidence_list(raw_evidence, "evidence_required")
    raw_required = node["requires_for_mastery"] if "requires_for_mastery" in node else raw_evidence
    requires_for_mastery = _normalize_evidence_list(raw_required, "requires_for_mastery")
    if not set(requires_for_mastery).issubset(set(evidence_keys)):
        raise ValueError("requires_for_mastery must be included in evidence_keys")
    raw_selective = node.get("selective_core_evidence_keys", [])
    selective_core = _normalize_evidence_list(raw_selective, "selective_core_evidence_keys")
    if not set(selective_core).issubset(set(evidence_keys)):
        raise ValueError("selective_core_evidence_keys must be included in evidence_keys")
    policy = node.get("fixed_answer_mastery_policy", "observation_only")
    if policy not in FIXED_ANSWER_POLICIES:
        raise ValueError("invalid fixed-answer mastery policy")
    ceiling = node.get("fixed_answer_state_ceiling", "B")
    if ceiling not in MASTERY_STATES:
        raise ValueError("invalid fixed-answer state ceiling")
    if PROCESS_EVIDENCE_KEYS.intersection(requires_for_mastery):
        ceiling = "B"
    contract = {
        "schema_version": GRAPH_EVIDENCE_CONTRACT_VERSION,
        "evidence_keys": evidence_keys,
        "requires_for_mastery": requires_for_mastery,
        "selective_core_evidence_keys": selective_core,
        "fixed_answer_mastery_policy": policy,
        "fixed_answer_state_ceiling": ceiling,
    }
    contract["canonical_digest_sha256"] = canonical_sha256(contract)
    return contract


def effective_fixed_answer_policy(graph_node: Mapping[str, Any]) -> dict[str, str]:
    contract = normalize_graph_evidence_contract(graph_node)
    return {
        "mastery_update_mode": contract["fixed_answer_mastery_policy"],
        "mastery_state_ceiling": contract["fixed_answer_state_ceiling"],
    }


# Names used by later contract compilers; keep the primitive API explicit now.
validate_graph_evidence_contract = normalize_graph_evidence_contract
canonical_digest = canonical_sha256
