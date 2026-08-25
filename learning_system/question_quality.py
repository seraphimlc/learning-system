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
MAX_DISCOVERY_REFERENCE_IDS = 8
MAX_DISCOVERY_DEPENDENCIES = 4
MAX_DISCOVERY_ALTERNATIVES = 8
MAX_DISCOVERY_EVIDENCE_KEYS = 8
MAX_SOLUTION_EVIDENCE_KEYS = 8
DISCOVERY_EXECUTION_BOUNDS = {
    "E1": (1, 6),
    "E2": (1, 6),
    "E3": (2, 6),
    "E4": (2, 8),
}

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
        try:
            raw = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("JSON payload contains an invalid surrogate") from exc
    else:
        raise TypeError("JSON payload must be str or bytes")
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValueError("JSON payload is oversized")

    def reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is not allowed: {value}")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_key_rejector,
            parse_constant=reject_non_finite,
        )
        _reject_surrogates(parsed)
        return parsed
    except RecursionError as exc:
        raise ValueError("JSON payload is too deeply nested") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            raise
        raise ValueError("invalid JSON payload") from exc


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("JSON payload contains an invalid surrogate")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_surrogates(item)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str):
        _reject_surrogates(value)
        return value
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

    def normalize_entries(entries: Any, label: str) -> list[dict[str, Any]]:
        if not isinstance(entries, (list, tuple)):
            raise ValueError(f"{label} must be an array")
        normalized_entries: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError(f"{label} entries must be objects")
            normalized_entry: dict[str, Any] = {}
            for key, value in entry.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} object keys must be strings")
                try:
                    normalized_value = normalize_text(value) if isinstance(value, str) else copy.deepcopy(value)
                    canonical_json(normalized_value)
                except (TypeError, ValueError, RecursionError) as exc:
                    raise ValueError(f"{label} contains a value that cannot be canonicalized") from exc
                normalized_entry[key] = normalized_value
            normalized_entries.append(normalized_entry)
        return normalized_entries

    if choices is not None:
        envelope["choices"] = normalize_entries(choices, "choices")
    if fields is not None:
        envelope["fields"] = normalize_entries(fields, "fields")
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
        rendered = sorted(repr(key) for key in unknown)
        raise ValueError(f"{label} contains unknown keys: {rendered}")


def _require_keys(value: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = required - set(value)
    if missing:
        raise ValueError(f"{label} is missing keys: {sorted(missing)}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _enum_value(value: Any, allowed: frozenset[str], message: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(message)
    return value


def _canonical_evidence_key(value: Any, label: str) -> str:
    if not isinstance(value, str) or value not in CANONICAL_EVIDENCE_KEYS:
        raise ValueError(f"{label} must be a canonical evidence key")
    return value


def _canonical_evidence_keys(value: Any, label: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= MAX_SOLUTION_EVIDENCE_KEYS:
        raise ValueError(f"{label} must contain {minimum}-{MAX_SOLUTION_EVIDENCE_KEYS} entries")
    normalized = [_canonical_evidence_key(item, label) for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


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
    if not isinstance(steps, list):
        raise ValueError("solution_steps must be an array")
    if len(steps) > MAX_SOLUTION_STEPS:
        raise ValueError("too many solution steps")
    step_ids = _unique_ids(steps, "solution_steps")
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
        _canonical_evidence_key(step["evidence_key"], "solution_step.evidence_key")
        if not isinstance(step["input_evidence_keys"], list):
            raise ValueError("solution_step.input_evidence_keys must be an array")
        _canonical_evidence_keys(step["input_evidence_keys"], "solution_step.input_evidence_keys")
        if not isinstance(step["prompt_span_ids"], list):
            raise ValueError("solution_step.prompt_span_ids must be an array")
        if not step["prompt_span_ids"]:
            raise ValueError("solution_step.prompt_span_ids must be non-empty")
        for key in ("input_step_ids", "prompt_span_ids"):
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
    if (
        not isinstance(packet["prompt_spans"], list)
        or not packet["prompt_spans"]
        or len(packet["prompt_spans"]) > MAX_PROMPT_SPANS
    ):
        raise ValueError("prompt_spans must contain 1-8 entries")
    if not isinstance(packet["solution_steps"], list) or not packet["solution_steps"]:
        raise ValueError("solution_steps must be non-empty")
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
        _canonical_evidence_key(relation["evidence_key"], "relation.evidence_key")
        if relation["target_step_id"] not in step_ids:
            raise ValueError("relation references an unknown target step")
        target = next(step for step in packet["solution_steps"] if step["id"] == relation["target_step_id"])
        if relation["evidence_key"] not in target["input_evidence_keys"]:
            raise ValueError("relation evidence is not an input to the target step")
    if len(canonical_json_bytes(packet)) > MAX_REVIEW_PACKET_BYTES:
        raise ValueError("review packet is oversized")
    return copy.deepcopy(packet)


def _bounded_string_array(
    value: Any,
    label: str,
    *,
    maximum: int,
    minimum: int = 0,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must contain {minimum}-{maximum} entries")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must contain non-empty strings")
    if unique and len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return value


def _bounded_hash_array(value: Any, label: str, *, maximum: int) -> list[str]:
    values = _bounded_string_array(value, label, maximum=maximum, minimum=1, unique=True)
    if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in values):
        raise ValueError(f"{label} must contain lowercase SHA-256 hashes")
    return values


def _authoritative_reference_set(value: Any, label: str, *, hashes: bool) -> set[str]:
    if not isinstance(value, (set, frozenset, list, tuple)):
        raise ValueError(f"{label} must be a bounded collection of strings")
    values = list(value)
    if len(values) > MAX_DISCOVERY_REFERENCE_IDS:
        raise ValueError(f"{label} contains too many entries")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{label} must contain non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")
    if hashes and any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in values):
        raise ValueError(f"{label} must contain lowercase SHA-256 hashes")
    return set(values)


def _authoritative_action_mapping(
    value: Any,
    label: str,
    solution_step_ids: set[str] | None,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping of step ids to actions")
    if len(value) > MAX_DISCOVERY_REFERENCE_IDS:
        raise ValueError(f"{label} contains too many entries")
    actions: dict[str, str] = {}
    for step_id, action in value.items():
        _nonempty_string(step_id, f"{label}.step_id")
        _nonempty_string(action, f"{label}.action")
        if solution_step_ids is not None and step_id not in solution_step_ids:
            raise ValueError(f"{label} references an unknown solution step")
        actions[step_id] = action
    return actions


def validate_discovery_derivation_output(
    output: Mapping[str, Any],
    *,
    solution_step_ids: set[str] | None = None,
    structural_prompt_span_hashes: set[str] | None = None,
    solution_step_actions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    output = _require_object(output, "discovery derivation output")
    allowed = {"schema_version", "discovery_depth", "entry_point_visibility", "decision_points", "solution_families", "execution_steps", "key_insight_evidence_keys"}
    _check_keys(output, allowed, "discovery derivation output")
    _require_keys(output, allowed, "discovery derivation output")
    if output["schema_version"] != DISCOVERY_DERIVATION_SCHEMA_VERSION:
        raise ValueError("unsupported discovery derivation version")
    discovery_depth = _enum_value(
        output["discovery_depth"], DISCOVERY_DEPTHS, "invalid discovery depth"
    )
    if discovery_depth == "E0":
        raise ValueError("E0 cannot be an active discovery derivation output")
    _enum_value(
        output["entry_point_visibility"],
        ENTRY_POINT_VISIBILITIES,
        "invalid entry-point visibility",
    )
    execution_minimum, execution_maximum = DISCOVERY_EXECUTION_BOUNDS[discovery_depth]
    if (
        not isinstance(output["execution_steps"], int)
        or isinstance(output["execution_steps"], bool)
        or not execution_minimum <= output["execution_steps"] <= execution_maximum
    ):
        raise ValueError(
            f"execution_steps must be between {execution_minimum} and {execution_maximum}"
        )
    for key in ("decision_points", "solution_families", "key_insight_evidence_keys"):
        if not isinstance(output[key], list):
            raise ValueError(f"{key} must be an array")
    if len(output["decision_points"]) > 4 or len(output["solution_families"]) > 3:
        raise ValueError("too many decisions or solution families")
    if discovery_depth in {"E1", "E2", "E3", "E4"}:
        if not output["solution_families"]:
            raise ValueError("E1-E4 outputs require at least one solution family")
    decision_ids = _unique_ids(output["decision_points"], "decision_points")
    family_ids = _unique_ids(output["solution_families"], "solution_families")
    references_present = any(
        decision.get("step_ids") or decision.get("structural_prompt_span_hashes")
        for decision in output["decision_points"]
    ) or any(
        family.get("step_ids") or family.get("structural_prompt_span_hashes")
        for family in output["solution_families"]
    )
    if references_present and (
        solution_step_ids is None or structural_prompt_span_hashes is None
    ):
        raise ValueError(
            "solution_step_ids and structural_prompt_span_hashes are required for references"
        )
    if output["solution_families"] and solution_step_actions is None:
        raise ValueError("solution_step_actions are required for solution families")
    authoritative_step_ids = (
        _authoritative_reference_set(solution_step_ids, "solution_step_ids", hashes=False)
        if solution_step_ids is not None
        else None
    )
    authoritative_span_hashes = (
        _authoritative_reference_set(
            structural_prompt_span_hashes,
            "structural_prompt_span_hashes",
            hashes=True,
        )
        if structural_prompt_span_hashes is not None
        else None
    )
    authoritative_actions = (
        _authoritative_action_mapping(
            solution_step_actions,
            "solution_step_actions",
            authoritative_step_ids,
        )
        if solution_step_actions is not None
        else None
    )
    for decision in output["decision_points"]:
        _check_keys(decision, {"id", "taxonomy", "alternatives", "misconception_key", "step_ids", "structural_prompt_span_hashes", "depends_on"}, "decision point")
        _require_keys(decision, {"id", "taxonomy", "alternatives", "misconception_key", "step_ids", "structural_prompt_span_hashes", "depends_on"}, "decision point")
        if decision["taxonomy"] not in DECISION_TAXONOMIES:
            raise ValueError("invalid decision taxonomy")
        _nonempty_string(decision["misconception_key"], "decision.misconception_key")
        _bounded_string_array(
            decision["alternatives"],
            "decision.alternatives",
            maximum=MAX_DISCOVERY_ALTERNATIVES,
            minimum=2,
            unique=True,
        )
        step_ids = _bounded_string_array(
            decision["step_ids"],
            "decision.step_ids",
            maximum=MAX_DISCOVERY_REFERENCE_IDS,
            minimum=1,
            unique=True,
        )
        _bounded_hash_array(
            decision["structural_prompt_span_hashes"],
            "decision.structural_prompt_span_hashes",
            maximum=MAX_DISCOVERY_REFERENCE_IDS,
        )
        dependencies = _bounded_string_array(
            decision["depends_on"],
            "decision.depends_on",
            maximum=MAX_DISCOVERY_DEPENDENCIES,
            unique=True,
        )
        if authoritative_step_ids is not None and not set(step_ids).issubset(authoritative_step_ids):
            raise ValueError("decision references an unknown solution step")
        if authoritative_span_hashes is not None and not set(decision["structural_prompt_span_hashes"]).issubset(authoritative_span_hashes):
            raise ValueError("decision references an unknown structural prompt span")
        if any(dependency not in decision_ids for dependency in dependencies):
            raise ValueError("decision depends_on references an unknown decision")
    for decision in output["decision_points"]:
        if not set(decision["depends_on"]).issubset(decision_ids):
            raise ValueError("decision depends_on references an unknown decision")
    _assert_acyclic({decision["id"]: decision["depends_on"] for decision in output["decision_points"]}, "decision")
    for family in output["solution_families"]:
        _check_keys(family, {"id", "first_action", "step_ids", "structural_prompt_span_hashes"}, "solution family")
        _require_keys(family, {"id", "first_action", "step_ids", "structural_prompt_span_hashes"}, "solution family")
        _nonempty_string(family["first_action"], "family.first_action")
        family_step_ids = _bounded_string_array(
            family["step_ids"],
            "family.step_ids",
            maximum=MAX_DISCOVERY_REFERENCE_IDS,
            minimum=1,
            unique=True,
        )
        family_span_hashes = _bounded_hash_array(
            family["structural_prompt_span_hashes"],
            "family.structural_prompt_span_hashes",
            maximum=MAX_DISCOVERY_REFERENCE_IDS,
        )
        if authoritative_step_ids is not None and not set(family_step_ids).issubset(authoritative_step_ids):
            raise ValueError("family references an unknown solution step")
        if authoritative_span_hashes is not None and not set(family_span_hashes).issubset(authoritative_span_hashes):
            raise ValueError("family references an unknown structural prompt span")
        if authoritative_actions is not None:
            first_step_id = family_step_ids[0]
            if first_step_id not in authoritative_actions:
                raise ValueError("family references a step without an authoritative action")
            if family["first_action"] != authoritative_actions[first_step_id]:
                raise ValueError("family first_action does not match the authoritative step action")
    _canonical_evidence_keys(
        output["key_insight_evidence_keys"],
        "key_insight_evidence_keys",
    )
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


def _normalize_stable_evidence_list(values: Any, label: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be an array")
    if any(not isinstance(value, str) or value not in CANONICAL_EVIDENCE_KEYS for value in values):
        raise ValueError(f"{label} contains an unknown stable evidence key")
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate stable evidence key in {label}")
    return sorted(values)


def normalize_graph_evidence_contract(graph_node: Mapping[str, Any]) -> dict[str, Any]:
    node = _require_object(graph_node, "graph node")
    has_required = "evidence_required" in node
    has_stable = "evidence_keys" in node
    if not has_required:
        raise ValueError("graph node must declare authoritative evidence_required")
    required_source = _normalize_evidence_list(node["evidence_required"], "evidence_required")
    if not required_source:
        raise ValueError("evidence_required must be non-empty")
    if has_stable:
        evidence_keys = _normalize_stable_evidence_list(node["evidence_keys"], "evidence_keys")
        if not evidence_keys:
            raise ValueError("evidence_keys must be non-empty")
    else:
        evidence_keys = required_source
    if has_required and has_stable and set(required_source) != set(evidence_keys):
        raise ValueError("evidence_required and evidence_keys do not agree")
    if "requires_for_mastery" in node:
        requires_for_mastery = _normalize_stable_evidence_list(
            node["requires_for_mastery"], "requires_for_mastery"
        )
    else:
        requires_for_mastery = required_source
    if not set(requires_for_mastery).issubset(set(evidence_keys)):
        raise ValueError("requires_for_mastery must be included in evidence_keys")
    raw_selective = node.get("selective_core_evidence_keys", [])
    selective_core = _normalize_stable_evidence_list(
        raw_selective, "selective_core_evidence_keys"
    )
    if not set(selective_core).issubset(set(evidence_keys)):
        raise ValueError("selective_core_evidence_keys must be included in evidence_keys")
    policy = _enum_value(
        node.get("fixed_answer_mastery_policy", "observation_only"),
        FIXED_ANSWER_POLICIES,
        "invalid fixed-answer mastery policy",
    )
    ceiling = _enum_value(
        node.get("fixed_answer_state_ceiling", "B"),
        MASTERY_STATES,
        "invalid fixed-answer state ceiling",
    )
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
