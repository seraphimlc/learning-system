from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from . import question_quality


FINGERPRINT_POLICY_VERSION = "question_fingerprint.v2"
FINGERPRINT_SCHEMA_VERSION = "question_fingerprint.v2"
LEGACY_FINGERPRINT_POLICY_VERSION = "question-fingerprint.v1"
_INTERACTION_TYPES = {
    "short_text",
    "fill_blank",
    "single_choice",
    "multi_choice",
    "formula_input",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def descriptor_fingerprint(
    descriptor: dict[str, Any],
    *,
    fingerprint_type: str,
    policy_version: str = FINGERPRINT_POLICY_VERSION,
) -> str:
    if not isinstance(descriptor, dict):
        raise TypeError("fingerprint descriptor must be a mapping")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("policy_version must be a nonempty string")
    if fingerprint_type not in {"prompt_instance", "core_structure"}:
        raise ValueError("unsupported fingerprint type")
    normalized_descriptor = deepcopy(descriptor)
    if fingerprint_type == "prompt_instance":
        values = normalized_descriptor.get("values")
        if isinstance(values, list) and all(
            isinstance(entry, dict) and isinstance(entry.get("name"), str)
            for entry in values
        ):
            normalized_descriptor["values"] = sorted(
                values,
                key=lambda entry: entry["name"],
            )
    return canonical_sha256(
        {
            "fingerprint_policy_version": policy_version,
            "fingerprint_type": fingerprint_type,
            "descriptor": normalized_descriptor,
        }
    )


def fingerprint_pair(
    normalized_instance_descriptor: Mapping[str, Any],
    normalized_core_structure_descriptor: Mapping[str, Any],
    *,
    policy_version: str = FINGERPRINT_POLICY_VERSION,
    graph_lineage: str | None = None,
    node_id: str | None = None,
    question_type: str | None = None,
    graph_version: str | None = None,
    node_contract_sha256: str | None = None,
    interaction_schema: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Build the requested fingerprint policy's actual payloads.

    v1 remains the original descriptor pair for callers that explicitly
    request it. The default v2 response keeps the old pair keys as aliases
    while also exposing the authoritative exact/family keys.
    """
    if not isinstance(normalized_instance_descriptor, Mapping):
        raise TypeError("instance descriptor must be a mapping")
    if not isinstance(normalized_core_structure_descriptor, Mapping):
        raise TypeError("core descriptor must be a mapping")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("policy_version must be a nonempty string")
    if policy_version == LEGACY_FINGERPRINT_POLICY_VERSION:
        instance = dict(normalized_instance_descriptor)
        core = dict(normalized_core_structure_descriptor)
        return {
            "fingerprint_policy_version": policy_version,
            "prompt_instance_fingerprint": descriptor_fingerprint(
                instance,
                fingerprint_type="prompt_instance",
                policy_version=policy_version,
            ),
            "core_structure_fingerprint": descriptor_fingerprint(
                core,
                fingerprint_type="core_structure",
                policy_version=policy_version,
            ),
        }
    if policy_version != FINGERPRINT_POLICY_VERSION:
        raise ValueError(f"unsupported fingerprint policy version: {policy_version}")
    instance = deepcopy(dict(normalized_instance_descriptor))
    core = deepcopy(dict(normalized_core_structure_descriptor))
    values = instance.get("values")
    if isinstance(values, list) and all(
        isinstance(entry, Mapping) and isinstance(entry.get("name"), str)
        for entry in values
    ):
        instance["values"] = sorted(values, key=lambda entry: entry["name"])
    if graph_lineage is None:
        graph_lineage = instance.get("graph_lineage")
        if graph_lineage is None:
            graph_lineage = core.get("graph_lineage")
    if node_id is None:
        node_id = instance.get("node_id")
        if node_id is None:
            node_id = core.get("node_id")
    if question_type is None:
        question_type = instance.get("question_type")
        if question_type is None:
            question_type = core.get("question_type")
    if graph_version is None:
        graph_version = instance.get("graph_version")
        if graph_version is None:
            graph_version = core.get("graph_version")
    if node_contract_sha256 is None:
        node_contract_sha256 = instance.get("node_contract_sha256")
        if node_contract_sha256 is None:
            node_contract_sha256 = core.get("node_contract_sha256")
    if interaction_schema is None:
        interaction_schema = instance.get("interaction_schema")
        if interaction_schema is None:
            interaction_schema = core.get("interaction_schema")
    descriptor = {
        "graph_lineage": graph_lineage,
        "node_id": node_id,
        "question_type": question_type,
        "prompt_envelope": {"instance": instance},
        "interaction_schema": interaction_schema,
        "values": instance.get("values", []),
        "surface_entities": instance.get("surface_entities", []),
        "mathematical_grammar": core.get("relation", core.get("mathematical_grammar", "")),
        "evidence_keys": core.get("evidence", core.get("evidence_keys", [])),
        "decision_taxonomies": core.get("decision_taxonomies", []),
        "solution_actions": core.get("solution_actions", []),
        "discovery_derivation": core.get("discovery_derivation", {}),
    }
    if graph_version is not None:
        descriptor["graph_version"] = graph_version
    if node_contract_sha256 is not None:
        descriptor["node_contract_sha256"] = node_contract_sha256
    fingerprints = build_question_fingerprints(descriptor)
    exact = fingerprints["exact_instance_fingerprint"]
    family = fingerprints["family_fingerprint"]
    return {
        "fingerprint_policy_version": policy_version,
        "exact_instance_fingerprint": exact,
        "family_fingerprint": family,
        "prompt_instance_fingerprint": exact,
        "core_structure_fingerprint": family,
    }


def _normalized(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("fingerprint object keys must be strings")
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, tuple):
        return [_normalized(item) for item in value]
    if isinstance(value, str):
        return question_quality.normalize_text(value)
    return deepcopy(value)


def _string_set(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{label} must be an array")
    values = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} must contain non-empty strings")
        values.append(question_quality.normalize_text(item))
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")
    return sorted(values)


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must contain non-empty strings")
    return [question_quality.normalize_text(item) for item in value]


def validate_interaction_schema(schema: Any) -> dict[str, Any]:
    """Validate the authoritative v2 interaction shape before projection."""
    if not isinstance(schema, Mapping):
        raise ValueError("interaction_schema must be an object")
    required = {"type", "choices", "fields"}
    missing = required.difference(schema)
    if missing:
        raise ValueError(
            "interaction_schema is missing required fields: "
            + ", ".join(sorted(missing))
        )
    interaction_type = schema["type"]
    if not isinstance(interaction_type, str) or interaction_type not in _INTERACTION_TYPES:
        raise ValueError("interaction_schema.type must be a supported interaction kind")

    for collection_name in ("choices", "fields"):
        collection = schema[collection_name]
        if not isinstance(collection, list):
            raise ValueError(f"interaction_schema.{collection_name} must be an array")
        for index, entry in enumerate(collection):
            if not isinstance(entry, Mapping):
                raise ValueError(
                    f"interaction_schema.{collection_name}[{index}] must be an object"
                )
            for key in ("label",):
                if key in entry and not isinstance(entry[key], str):
                    raise ValueError(
                        f"interaction_schema.{collection_name}[{index}].{key} must be a string"
                    )

    for key, value in schema.items():
        if key == "label" and not isinstance(value, str):
            raise ValueError("interaction_schema.label must be a string")
        if key in {"labels", "choice_labels", "choice_ids", "field_ids"}:
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"interaction_schema.{key} must be an array of strings")

    for index, choice in enumerate(schema["choices"]):
        if "id" not in choice or "label" not in choice:
            raise ValueError(
                f"interaction_schema.choices[{index}] requires id and label"
            )
        if not isinstance(choice["id"], str) or not choice["id"].strip():
            raise ValueError(f"interaction_schema.choices[{index}].id must be a string")
        if not isinstance(choice["label"], str):
            raise ValueError(f"interaction_schema.choices[{index}].label must be a string")
        if "value" in choice and (
            isinstance(choice["value"], (list, dict))
            or type(choice["value"]) not in {str, int, float, bool, type(None)}
        ):
            raise ValueError(
                f"interaction_schema.choices[{index}].value must be a scalar"
            )

    for index, field in enumerate(schema["fields"]):
        if "id" not in field or "label" not in field:
            raise ValueError(
                f"interaction_schema.fields[{index}] requires id and label"
            )
        if not isinstance(field["id"], str) or not field["id"].strip():
            raise ValueError(f"interaction_schema.fields[{index}].id must be a string")
        if not isinstance(field["label"], str):
            raise ValueError(f"interaction_schema.fields[{index}].label must be a string")
    return deepcopy(dict(schema))


def _project_structural_interaction_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    schema = validate_interaction_schema(schema)
    result = {}
    for key, value in schema.items():
        if key in {"label", "labels", "surface_text", "description"}:
            result[key] = "LABEL"
            continue
        if key in {"choice_labels", "choice_ids", "field_ids"}:
            if not isinstance(value, list):
                raise ValueError(f"interaction_schema.{key} must be an array")
            placeholder = "FIELD_ID" if key == "field_ids" else "CHOICE_ID" if key == "choice_ids" else "CHOICE_LABEL"
            result[key] = [placeholder for _ in value]
            continue
        if key == "choices":
            if not isinstance(value, list):
                raise ValueError("interaction_schema.choices must be an array")
            result[key] = []
            for choice in value:
                if not isinstance(choice, Mapping):
                    raise ValueError("interaction_schema.choices entries must be objects")
                result[key].append(
                    {
                        choice_key: (
                            "CHOICE_ID"
                            if choice_key in {"id", "choice_id"}
                            else "CHOICE_LABEL"
                            if choice_key in {"label", "text", "description"}
                            else "CHOICE_VALUE"
                            if choice_key in {"value", "answer", "default"}
                            else _normalized(choice_value)
                        )
                        for choice_key, choice_value in choice.items()
                    }
                )
            continue
        if key == "fields":
            if not isinstance(value, list):
                raise ValueError("interaction_schema.fields must be an array")
            result[key] = []
            for field in value:
                if not isinstance(field, Mapping):
                    raise ValueError("interaction_schema.fields entries must be objects")
                structural_field = {"type": "FIELD"}
                structural_field.update(
                    {
                        field_key: (
                            "FIELD_ID"
                            if field_key in {"id", "field_id"}
                            else "FIELD_LABEL"
                            if field_key in {"label", "placeholder", "description", "surface_text"}
                            else "FIELD_VALUE"
                            if field_key in {"value", "default"}
                            else _normalized(field_value)
                        )
                        for field_key, field_value in field.items()
                    }
                )
                result[key].append(structural_field)
        else:
            result[key] = _normalized(value)
    return result


def _structural_interaction_schema(descriptor: Mapping[str, Any]) -> Any:
    if "interaction_schema" not in descriptor:
        raise ValueError("interaction_schema is required for family fingerprinting")
    authoritative = validate_interaction_schema(descriptor["interaction_schema"])
    projected = _project_structural_interaction_schema(authoritative)
    if "structural_interaction_schema" in descriptor:
        supplied = descriptor.get("structural_interaction_schema")
        if not isinstance(supplied, Mapping):
            raise ValueError("structural_interaction_schema must be an object")
        if canonical_json(_normalized(supplied)) != canonical_json(_normalized(projected)):
            raise ValueError(
                "structural_interaction_schema does not match authoritative interaction_schema"
            )
    return projected


def _structural_derivation(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    derivation = descriptor.get("discovery_derivation", {})
    if not isinstance(derivation, Mapping):
        raise ValueError("discovery_derivation must be an object")
    result = {}
    for key in ("discovery_depth", "entry_point_visibility", "execution_steps"):
        if key in derivation:
            result[key] = _normalized(derivation[key])
    decisions = derivation.get("decision_points", descriptor.get("decision_points", []))
    if not isinstance(decisions, list):
        raise ValueError("decision_points must be an array")
    normalized_decisions = []
    for item in decisions:
        if not isinstance(item, Mapping):
            raise TypeError("decision_points entries must be objects")
        taxonomy = item.get("taxonomy")
        if not isinstance(taxonomy, str) or not taxonomy.strip():
            raise ValueError("decision point taxonomy must be a non-empty string")
        misconception_key = item.get("misconception_key")
        if not isinstance(misconception_key, str) or not misconception_key.strip():
            raise ValueError("decision point misconception_key must be a non-empty string")
        normalized_decisions.append(
            {
                "taxonomy": _normalized(taxonomy),
                "alternatives": _string_set(item.get("alternatives", []), "decision alternatives"),
                "misconception_key": _normalized(misconception_key),
                "step_ids": _string_array(item.get("step_ids", []), "decision step_ids"),
                "structural_prompt_span_hashes": _string_array(
                    item.get("structural_prompt_span_hashes", []),
                    "decision structural_prompt_span_hashes",
                ),
                "depends_on": _string_array(item.get("depends_on", []), "decision depends_on"),
            }
        )
    result["decision_points"] = normalized_decisions
    families = derivation.get("solution_families", descriptor.get("solution_families", []))
    if not isinstance(families, list):
        raise ValueError("solution_families must be an array")
    normalized_families = []
    for item in families:
        if not isinstance(item, Mapping):
            raise TypeError("solution_families entries must be objects")
        first_action = item.get("first_action")
        if not isinstance(first_action, str) or not first_action.strip():
            raise ValueError("solution family first_action must be a non-empty string")
        normalized_families.append(
            {
                "first_action": _normalized(first_action),
                "step_ids": _string_array(item.get("step_ids", []), "solution family step_ids"),
                "structural_prompt_span_hashes": _string_array(
                    item.get("structural_prompt_span_hashes", []),
                    "solution family structural_prompt_span_hashes",
                ),
            }
        )
    result["solution_families"] = normalized_families
    return result


def _require_v2_graph_identity(descriptor: Mapping[str, Any]) -> None:
    for field in ("graph_lineage", "node_id", "question_type"):
        value = descriptor.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"fingerprint descriptor.{field} must be a non-empty string")
    for field in ("graph_version",):
        if field in descriptor and (
            not isinstance(descriptor[field], str) or not descriptor[field].strip()
        ):
            raise ValueError(f"fingerprint descriptor.{field} must be a non-empty string")
    if "node_contract_sha256" in descriptor:
        value = descriptor["node_contract_sha256"]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or value.lower() != value
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("fingerprint descriptor.node_contract_sha256 must be a lowercase sha256 digest")


def _family_payload(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    _require_v2_graph_identity(descriptor)
    derivation = _structural_derivation(descriptor)
    structural_span_hashes = descriptor.get(
        "structural_prompt_span_hashes",
        descriptor.get("structural_span_hashes", []),
    )
    structural_span_hashes = _string_array(structural_span_hashes, "structural prompt span hashes")
    payload = {
        "graph_lineage": _normalized(descriptor.get("graph_lineage", "")),
        "node_id": _normalized(descriptor.get("node_id", "")),
        "question_type": _normalized(descriptor["question_type"]),
        "structural_interaction_schema": _structural_interaction_schema(descriptor),
        "structural_prompt_span_hashes": list(structural_span_hashes),
        "mathematical_grammar": _normalized(descriptor.get("mathematical_grammar", descriptor.get("answer_grammar", ""))),
        "decision_taxonomies": _string_set(
            descriptor.get("decision_taxonomies", [item.get("taxonomy") for item in derivation["decision_points"]]),
            "decision_taxonomies",
        ),
        "solution_actions": _string_array(descriptor.get("solution_actions", []), "solution_actions"),
        "evidence_keys": _string_set(descriptor.get("evidence_keys", []), "evidence_keys"),
        "misconception_keys": _string_set(descriptor.get("misconception_keys", []), "misconception_keys"),
        "structural_derivation_digest_sha256": canonical_sha256(derivation),
    }
    for field in ("graph_version", "node_contract_sha256"):
        if field in descriptor:
            payload[field] = _normalized(descriptor[field])
    return payload


def _exact_payload(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    discovery_receipt = descriptor.get(
        "discovery_derivation",
        descriptor.get("discovery_derivation_receipt", {}),
    )
    discovery_digest = descriptor.get(
        "discovery_derivation_sha256",
        descriptor.get("discovery_derivation_digest_sha256", ""),
    )
    return {
        "graph_lineage": _normalized(descriptor.get("graph_lineage", "")),
        "node_id": _normalized(descriptor.get("node_id", "")),
        "question_type": _normalized(descriptor["question_type"]),
        "prompt_envelope": _normalized(descriptor.get("prompt_envelope", descriptor.get("prompt", ""))),
        "interaction_schema": _normalized(
            validate_interaction_schema(descriptor["interaction_schema"])
        ),
        "values": _normalized(descriptor.get("values", [])),
        "surface_entities": _normalized(descriptor.get("surface_entities", [])),
        "discovery_derivation": _normalized(discovery_receipt),
        "discovery_derivation_sha256": _normalized(discovery_digest),
        "family_payload": _family_payload(descriptor),
    }


def exact_instance_fingerprint(descriptor: Mapping[str, Any]) -> str:
    if not isinstance(descriptor, Mapping):
        raise TypeError("fingerprint descriptor must be a mapping")
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "fingerprint_type": "exact_instance",
        "payload": _exact_payload(descriptor),
    }
    return canonical_sha256(payload)


def family_fingerprint(descriptor: Mapping[str, Any]) -> str:
    if not isinstance(descriptor, Mapping):
        raise TypeError("fingerprint descriptor must be a mapping")
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "fingerprint_type": "family",
        "payload": _family_payload(descriptor),
    }
    return canonical_sha256(payload)


def build_question_fingerprints(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact and structural v2 fingerprints and their audit payloads."""
    if not isinstance(descriptor, Mapping):
        raise TypeError("fingerprint descriptor must be a mapping")
    exact_payload = _exact_payload(descriptor)
    family_payload = _family_payload(descriptor)
    return {
        "fingerprint_policy_version": FINGERPRINT_POLICY_VERSION,
        "exact_instance_fingerprint": canonical_sha256({
            "schema_version": FINGERPRINT_SCHEMA_VERSION,
            "fingerprint_type": "exact_instance",
            "payload": exact_payload,
        }),
        "family_fingerprint": canonical_sha256({
            "schema_version": FINGERPRINT_SCHEMA_VERSION,
            "fingerprint_type": "family",
            "payload": family_payload,
        }),
        "node_id": descriptor.get("node_id"),
        "evidence_keys": family_payload["evidence_keys"],
        "misconception_keys": family_payload["misconception_keys"],
        "exact_instance_payload": exact_payload,
        "family_payload": family_payload,
        "fingerprint_descriptor": deepcopy(dict(descriptor)),
    }


def _fingerprint_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise TypeError("fingerprint entry must be a mapping")
    descriptor = entry.get("fingerprint_descriptor")
    if not isinstance(descriptor, Mapping):
        descriptor = entry
    return build_question_fingerprints(descriptor)


def validate_family_quota(
    node_id: str,
    candidates: Iterable[Mapping[str, Any]],
    *,
    existing: Iterable[Mapping[str, Any]] = (),
) -> None:
    """Reject exact duplicates and more than two same-node family instances."""
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("node_id must be a non-empty string")
    entries = [_fingerprint_entry(entry) for entry in [*existing, *candidates]]
    exact_seen: set[str] = set()
    families: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        entry_node_id = entry.get("node_id", node_id)
        if entry_node_id != node_id:
            raise ValueError("candidate node_id does not match quota node_id")
        exact = entry["exact_instance_fingerprint"]
        if exact in exact_seen:
            raise ValueError("exact fingerprint duplicate")
        exact_seen.add(exact)
        family_payload = entry.get("family_payload", {})
        if isinstance(family_payload, Mapping):
            quota_payload = {
                key: value
                for key, value in family_payload.items()
                if key not in {"evidence_keys", "misconception_keys"}
            }
            family_key = canonical_sha256(quota_payload)
        else:
            family_key = entry["family_fingerprint"]
        families.setdefault(family_key, []).append(entry)
    for family_entries in families.values():
        if len(family_entries) > 2:
            raise ValueError("a node family may contain at most two items")
        if len(family_entries) == 2:
            first, second = family_entries
            if set(first.get("evidence_keys", [])) == set(second.get("evidence_keys", [])):
                raise ValueError("the second family item requires distinct evidence keys")
            if set(first.get("misconception_keys", [])) == set(second.get("misconception_keys", [])):
                raise ValueError("the second family item requires distinct misconception keys")


fingerprint_pair_v2 = build_question_fingerprints
assert_family_quota = validate_family_quota
