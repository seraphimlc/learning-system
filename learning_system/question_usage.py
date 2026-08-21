from __future__ import annotations

import hashlib
import json
from typing import Any


USAGE_POLICY_VERSION = "2026-07-25.question-usage-policy.v2"
USAGE_CONTEXT_VERSION = "2026-07-25.step-usage-context.v2"

PURPOSES = frozenset({"teaching", "diagnostic", "practice"})
PRACTICE_FAMILIES = frozenset(
    {
        "concept_model",
        "structural_calculation",
        "application_modeling",
        "error_repair",
        "variation_reverse_reasoning",
        "controlled_synthesis",
        "controlled_stretch",
        "spaced_retrieval",
    }
)
PRACTICE_ROLES = frozenset(
    {
        "consolidate_core",
        "stabilize_fluency",
        "repair_specific_gap",
        "near_transfer",
        "far_transfer",
        "spaced_retrieval",
        "controlled_challenge",
    }
)
DIAGNOSTIC_ROLES = frozenset({"entry_probe", "confirmation_core", "confirmation_transfer", "prerequisite_probe"})
TEACHING_ROLES = frozenset({"concept_build", "worked_example", "targeted_repair"})
HINT_POLICIES = frozenset({"guided", "after_first_attempt", "no_hint"})
DIFFICULTIES = frozenset({"L1", "L2", "L3", "L4", "L5"})
SUPPORT_ROUTING_VERSION = "2026-07-28.support-routing.v1"
SELECTION_NODE_STATES = frozenset({"untested", "weak", "failed", "due", "mastered"})
SUPPORT_TRIGGER_STATUSES = frozenset({"not_met", "contradicted"})
_SELECTION_LIST_FIELDS = (
    "node_state_in",
    "requires_prior_item_ids",
    "prefer_after_evidence_keys",
    "prefer_when_error_tags_include",
    "prerequisite_node_ids",
)
_SELECTION_BOOL_FIELDS = ("do_not_select_after_equivalent_instance",)

_ERROR_KINDS = frozenset({"error_spotting", "misconception_probe", "self_correction", "symbol_unit_audit"})
_APPLICATION_KINDS = frozenset({"estimation_modeling", "model_selection", "communication"})
_VARIATION_KINDS = frozenset({"variant", "near_transfer", "far_transfer", "transfer_retest", "reverse_reasoning"})
_STRETCH_KINDS = frozenset({"stretch_transfer", "two_method_compare", "boundary_case"})
_CALCULATION_KINDS = frozenset({"standard_example", "check_strategy", "representation"})


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _explicit_policy(item: dict[str, Any]) -> dict[str, Any]:
    for source in (
        item.get("usage_policy"),
        (item.get("quality") or {}).get("usage_policy") if isinstance(item.get("quality"), dict) else None,
        (item.get("production_lineage") or {}).get("usage_policy")
        if isinstance(item.get("production_lineage"), dict)
        else None,
    ):
        if isinstance(source, dict) and source:
            return dict(source)
    return {}


def _family_for_kind(kind: str) -> str:
    if kind in _ERROR_KINDS:
        return "error_repair"
    if kind in _APPLICATION_KINDS:
        return "application_modeling"
    if kind in _VARIATION_KINDS:
        return "variation_reverse_reasoning"
    if kind in _STRETCH_KINDS:
        return "controlled_stretch"
    if kind in _CALCULATION_KINDS:
        return "structural_calculation"
    return "concept_model"


def _structure_fingerprint(item: dict[str, Any]) -> str:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    for value in (
        quality.get("canonical_structure_fingerprint"),
        quality.get("structure_fingerprint"),
        item.get("canonical_structure_fingerprint"),
        item.get("structure_fingerprint"),
        item.get("core_stem_id"),
        item.get("math_core_signature"),
    ):
        if str(value or "").strip():
            return str(value).strip()
    return f"USAGE-{canonical_sha256({'question_id': item.get('id'), 'kind': item.get('kind'), 'prompt': item.get('prompt')})[:20]}"


def normalize_selection_preconditions(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise TypeError("selection_preconditions must be a mapping")
    allowed_fields = set(_SELECTION_LIST_FIELDS) | set(_SELECTION_BOOL_FIELDS)
    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            "selection_preconditions has unknown fields: "
            + ", ".join(unknown_fields)
        )
    normalized: dict[str, Any] = {}
    for field in _SELECTION_LIST_FIELDS:
        if field not in value:
            continue
        raw_items = value[field]
        if not isinstance(raw_items, list):
            raise TypeError(f"selection_preconditions.{field} must be a list")
        items = [str(item or "").strip() for item in raw_items]
        if any(not item for item in items) or len(items) != len(set(items)):
            raise ValueError(
                f"selection_preconditions.{field} must contain unique nonempty values"
            )
        if field == "node_state_in" and any(
            item not in SELECTION_NODE_STATES for item in items
        ):
            raise ValueError("selection_preconditions.node_state_in has an unknown state")
        normalized[field] = items
    for field in _SELECTION_BOOL_FIELDS:
        if field not in value:
            continue
        if not isinstance(value[field], bool):
            raise TypeError(f"selection_preconditions.{field} must be boolean")
        normalized[field] = value[field]
    return normalized


def normalize_support_routing(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise TypeError("support_routing must be a mapping")
    if str(value.get("schema_version") or "") != SUPPORT_ROUTING_VERSION:
        raise ValueError("support_routing has an unsupported schema version")
    raw_routes = value.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("support_routing.routes must be a nonempty list")
    routes: list[dict[str, Any]] = []
    route_keys: set[tuple[str, str, str]] = set()
    for raw_route in raw_routes:
        if not isinstance(raw_route, dict):
            raise TypeError("support_routing route must be a mapping")
        unknown_fields = sorted(
            set(raw_route)
            - {
                "evidence_key",
                "source_item_id",
                "criterion_key",
                "trigger_statuses",
            }
        )
        if unknown_fields:
            raise ValueError(
                "support_routing route has unknown fields: "
                + ", ".join(unknown_fields)
            )
        evidence_key = str(raw_route.get("evidence_key") or "").strip()
        source_item_id = str(raw_route.get("source_item_id") or "").strip()
        criterion_key = str(raw_route.get("criterion_key") or "").strip()
        trigger_statuses = [
            str(status or "").strip()
            for status in (raw_route.get("trigger_statuses") or [])
        ]
        if not evidence_key or not source_item_id or not criterion_key:
            raise ValueError("support_routing route identity fields must be nonempty")
        if (
            not trigger_statuses
            or len(trigger_statuses) != len(set(trigger_statuses))
            or any(status not in SUPPORT_TRIGGER_STATUSES for status in trigger_statuses)
        ):
            raise ValueError("support_routing route has invalid trigger statuses")
        route_key = (evidence_key, source_item_id, criterion_key)
        if route_key in route_keys:
            raise ValueError("support_routing routes must be unique")
        route_keys.add(route_key)
        routes.append(
            {
                "evidence_key": evidence_key,
                "source_item_id": source_item_id,
                "criterion_key": criterion_key,
                "trigger_statuses": trigger_statuses,
            }
        )
    return {
        "schema_version": SUPPORT_ROUTING_VERSION,
        "routes": routes,
    }


def policy_for_item(item: dict[str, Any]) -> dict[str, Any]:
    explicit = _explicit_policy(item)
    kind = str(item.get("kind") or "").strip()
    support_only = bool(explicit.get("support_only", item.get("support_only", False)))
    not_for_activation = bool(explicit.get("not_for_activation", item.get("not_for_activation", False)))
    allowed_purposes = list(explicit.get("allowed_purposes") or (["teaching"] if support_only else ["teaching", "practice", "diagnostic"]))
    default_family = str(explicit.get("default_practice_family") or _family_for_kind(kind))
    default_roles = {
        "concept_model": ["consolidate_core"],
        "structural_calculation": ["stabilize_fluency"],
        "application_modeling": ["consolidate_core", "near_transfer"],
        "error_repair": ["repair_specific_gap"],
        "variation_reverse_reasoning": ["near_transfer", "far_transfer"],
        "controlled_synthesis": ["near_transfer"],
        "controlled_stretch": ["controlled_challenge"],
        "spaced_retrieval": ["spaced_retrieval"],
    }
    policy = {
        "schema_version": USAGE_POLICY_VERSION,
        "allowed_purposes": allowed_purposes,
        "default_practice_family": default_family,
        "allowed_practice_roles": list(explicit.get("allowed_practice_roles") or default_roles[default_family]),
        "diagnostic_roles": list(explicit.get("diagnostic_roles") or ["entry_probe", "confirmation_core", "confirmation_transfer"]),
        "teaching_roles": list(explicit.get("teaching_roles") or ["concept_build", "worked_example", "targeted_repair"]),
        "primary_node_id": str(explicit.get("primary_node_id") or item.get("node_id") or ""),
        "secondary_node_ids": list(explicit.get("secondary_node_ids") or item.get("secondary_node_ids") or []),
        "structure_fingerprint": str(explicit.get("structure_fingerprint") or _structure_fingerprint(item)),
        "support_only": support_only,
        "not_for_activation": not_for_activation,
        "selection_preconditions": normalize_selection_preconditions(
            explicit.get("selection_preconditions")
            if "selection_preconditions" in explicit
            else item.get("selection_preconditions")
        ),
        "support_routing": normalize_support_routing(
            explicit.get("support_routing")
        ),
        "source": "explicit" if explicit else "legacy_policy_default",
    }
    validate_policy(policy)
    return policy


def validate_policy(policy: dict[str, Any]) -> None:
    if str(policy.get("schema_version") or "") != USAGE_POLICY_VERSION:
        raise ValueError("question usage policy has an unsupported schema version")
    purposes = policy.get("allowed_purposes")
    if not isinstance(purposes, list) or not purposes or any(value not in PURPOSES for value in purposes):
        raise ValueError("question usage policy has invalid allowed purposes")
    if bool(policy.get("support_only")) and purposes != ["teaching"]:
        raise ValueError("support-only questions can only be used for teaching")
    if str(policy.get("default_practice_family") or "") not in PRACTICE_FAMILIES:
        raise ValueError("question usage policy has an unknown practice family")
    practice_roles = policy.get("allowed_practice_roles")
    if not isinstance(practice_roles, list) or any(value not in PRACTICE_ROLES for value in practice_roles):
        raise ValueError("question usage policy has an unknown practice role")
    diagnostic_roles = policy.get("diagnostic_roles")
    if not isinstance(diagnostic_roles, list) or any(value not in DIAGNOSTIC_ROLES for value in diagnostic_roles):
        raise ValueError("question usage policy has an unknown diagnostic role")
    teaching_roles = policy.get("teaching_roles")
    if not isinstance(teaching_roles, list) or any(value not in TEACHING_ROLES for value in teaching_roles):
        raise ValueError("question usage policy has an unknown teaching role")
    if not str(policy.get("primary_node_id") or "").strip():
        raise ValueError("question usage policy must bind a primary graph node")
    if not str(policy.get("structure_fingerprint") or "").strip():
        raise ValueError("question usage policy must include a structure fingerprint")
    selection_preconditions = normalize_selection_preconditions(
        policy.get("selection_preconditions")
    )
    support_routing = normalize_support_routing(policy.get("support_routing"))
    if support_routing and not bool(policy.get("support_only")):
        raise ValueError("support_routing is only valid for support-only questions")
    if support_routing:
        required_source_ids = set(
            selection_preconditions.get("requires_prior_item_ids") or []
        )
        preferred_evidence_keys = set(
            selection_preconditions.get("prefer_after_evidence_keys") or []
        )
        allowed_node_states = selection_preconditions.get("node_state_in") or []
        if not required_source_ids or not preferred_evidence_keys or not allowed_node_states:
            raise ValueError(
                "support_routing requires source items, evidence keys, and node states"
            )
        for route in support_routing["routes"]:
            if route["source_item_id"] not in required_source_ids:
                raise ValueError("support_routing source item is not permitted by selection preconditions")
            if route["evidence_key"] not in preferred_evidence_keys:
                raise ValueError("support_routing evidence key is not permitted by selection preconditions")


def policy_digest(policy: dict[str, Any]) -> str:
    validate_policy(policy)
    digest_payload = {
        "schema_version": policy["schema_version"],
        "allowed_purposes": list(policy["allowed_purposes"]),
        "default_practice_family": policy["default_practice_family"],
        "allowed_practice_roles": list(policy["allowed_practice_roles"]),
        "diagnostic_roles": list(policy["diagnostic_roles"]),
        "teaching_roles": list(policy["teaching_roles"]),
        "primary_node_id": policy["primary_node_id"],
        "secondary_node_ids": list(policy["secondary_node_ids"]),
        "structure_fingerprint": policy["structure_fingerprint"],
        "support_only": bool(policy["support_only"]),
        "not_for_activation": bool(policy["not_for_activation"]),
        "source": str(policy.get("source") or ""),
    }
    selection_preconditions = normalize_selection_preconditions(
        policy.get("selection_preconditions")
    )
    support_routing = normalize_support_routing(policy.get("support_routing"))
    if selection_preconditions:
        digest_payload["selection_preconditions"] = selection_preconditions
    if support_routing:
        digest_payload["support_routing"] = support_routing
    return canonical_sha256(digest_payload)


def matching_support_route(
    policy: dict[str, Any],
    routing_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    validate_policy(policy)
    if not bool(policy.get("support_only")) or not isinstance(routing_context, dict):
        return None
    source_item_id = str(routing_context.get("source_item_id") or "").strip()
    node_state = str(routing_context.get("node_state") or "").strip()
    criterion_statuses = routing_context.get("criterion_statuses")
    if (
        not source_item_id
        or node_state not in SELECTION_NODE_STATES
        or not isinstance(criterion_statuses, dict)
    ):
        return None
    normalized_statuses = {
        str(key or "").strip(): str(status or "").strip()
        for key, status in criterion_statuses.items()
        if str(key or "").strip()
    }
    selection_preconditions = normalize_selection_preconditions(
        policy.get("selection_preconditions")
    )
    if source_item_id not in set(
        selection_preconditions.get("requires_prior_item_ids") or []
    ):
        return None
    if node_state not in set(selection_preconditions.get("node_state_in") or []):
        return None
    preferred_evidence_keys = set(
        selection_preconditions.get("prefer_after_evidence_keys") or []
    )
    support_routing = normalize_support_routing(policy.get("support_routing"))
    for route in support_routing.get("routes") or []:
        if route["source_item_id"] != source_item_id:
            continue
        if route["evidence_key"] not in preferred_evidence_keys:
            continue
        if normalized_statuses.get(route["criterion_key"]) not in set(
            route["trigger_statuses"]
        ):
            continue
        return dict(route)
    return None


def context_for_step(
    policy: dict[str, Any],
    *,
    purpose: str,
    purpose_role: str,
    block_id: str = "",
    block_index: int = 1,
    practice_family: str = "",
    practice_role: str = "",
) -> dict[str, Any]:
    validate_policy(policy)
    if purpose not in policy["allowed_purposes"]:
        raise ValueError("question is not eligible for the requested usage purpose")
    if purpose == "teaching":
        if purpose_role not in policy["teaching_roles"]:
            raise ValueError("question is not eligible for the requested teaching role")
        hint_policy = "guided"
        positive_weight = 0.0
        instability_weight = 0.0
        mastery_eligible = False
        mastery_ceiling = "none"
        requires_confirmation = True
        family = ""
        role = ""
    elif purpose == "diagnostic":
        if purpose_role not in policy["diagnostic_roles"]:
            raise ValueError("question is not eligible for the requested diagnostic role")
        hint_policy = "no_hint"
        positive_weight = 1.0
        instability_weight = 1.0
        mastery_eligible = True
        mastery_ceiling = "A"
        requires_confirmation = False
        family = ""
        role = ""
    else:
        family = practice_family or policy["default_practice_family"]
        role = practice_role or policy["allowed_practice_roles"][0]
        if family not in PRACTICE_FAMILIES or role not in policy["allowed_practice_roles"]:
            raise ValueError("question is not eligible for the requested practice role")
        hint_policy = "after_first_attempt"
        positive_weight = 0.25
        instability_weight = 0.5
        mastery_eligible = False
        mastery_ceiling = "B"
        requires_confirmation = True
    context = {
        "schema_version": USAGE_CONTEXT_VERSION,
        "question_usage_policy_digest_sha256": policy_digest(policy),
        "purpose": purpose,
        "purpose_role": purpose_role,
        "practice_family": family,
        "practice_role": role,
        "hint_policy": hint_policy,
        "mastery_evidence_weight": positive_weight,
        "instability_signal_weight": instability_weight,
        "mastery_update_eligible": mastery_eligible,
        "mastery_state_ceiling": mastery_ceiling,
        "requires_diagnostic_confirmation": requires_confirmation,
        "block_id": block_id,
        "block_index": int(block_index),
        "structure_fingerprint": policy["structure_fingerprint"],
    }
    validate_context(context)
    return context


def validate_context(context: dict[str, Any]) -> None:
    if str(context.get("schema_version") or "") != USAGE_CONTEXT_VERSION:
        raise ValueError("step usage context has an unsupported schema version")
    purpose = str(context.get("purpose") or "")
    if purpose not in PURPOSES:
        raise ValueError("step usage context has an unknown purpose")
    if str(context.get("hint_policy") or "") not in HINT_POLICIES:
        raise ValueError("step usage context has an unknown hint policy")
    if purpose == "diagnostic" and (
        context.get("hint_policy") != "no_hint" or not bool(context.get("mastery_update_eligible"))
    ):
        raise ValueError("diagnostic usage must be no-hint and mastery eligible")
    if purpose != "diagnostic" and bool(context.get("mastery_update_eligible")):
        raise ValueError("only diagnostic usage can directly update mastery")
    if purpose == "practice" and str(context.get("mastery_state_ceiling") or "") != "B":
        raise ValueError("practice usage mastery ceiling must be B")
    if not str(context.get("structure_fingerprint") or ""):
        raise ValueError("step usage context must bind a structure fingerprint")


def context_digest(context: dict[str, Any]) -> str:
    validate_context(context)
    return canonical_sha256(context)
