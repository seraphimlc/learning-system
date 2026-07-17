from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from . import question_fingerprints


SHARD_SIZE = 5
CONCURRENCY = 1

_PROVIDER_MODES = {"live_model", "recorded_model", "recorded_oracle"}
_RESULT_FIELDS = {
    "question_id",
    "item_version",
    "question_digest_sha256",
    "contract_id",
    "contract_version",
    "contract_digest_sha256",
    "question_correctness",
    "question_node_alignment",
    "evidence_role_alignment",
    "answer_contract_review",
    "normalized_instance_descriptor",
    "normalized_core_structure_descriptor",
    "confidence",
}
_AUTHORITATIVE_RESULT_FIELDS = {
    "question_id",
    "item_version",
    "question_digest_sha256",
    "contract_id",
    "contract_version",
    "contract_digest_sha256",
}
_SEMANTIC_RESULT_FIELDS = (_RESULT_FIELDS - _AUTHORITATIVE_RESULT_FIELDS) | {
    "item_handle"
}
_QUESTION_CORRECTNESS_FIELDS = {"verdict", "independent_solution", "rationale"}
_NODE_ALIGNMENT_FIELDS = {
    "verdict",
    "actual_mathematical_core",
    "tested_node_evidence",
    "rationale",
    "advisory_candidate_node",
}
_EVIDENCE_ALIGNMENT_FIELDS = {"verdict", "actual_evidence_demand", "rationale"}
_CONTRACT_REVIEW_FIELDS = {
    "verdict",
    "reference_solution_correct",
    "criteria_atomic_and_observable",
    "weights_and_dimensions_valid",
    "required_for_pass_valid",
    "corrections",
}
_VALIDATED_FIELDS = {
    "question_id",
    "item_version",
    "question_digest_sha256",
    "contract_id",
    "contract_version",
    "contract_digest_sha256",
    "bound_node_id",
    "question_correctness_verdict",
    "question_node_alignment_verdict",
    "evidence_role_alignment_verdict",
    "answer_contract_verdict",
    "normalized_instance_descriptor",
    "normalized_core_structure_descriptor",
    "confidence",
    "minimum_confidence",
    "review_status",
    "repair_required",
    "repair_route",
    "needs_retry",
    "blockers",
    "provider_mode",
    "activation_eligible",
    "fingerprint_policy_version",
    "prompt_instance_fingerprint",
    "core_structure_fingerprint",
    "validated_item_digest_sha256",
}
_SHARD_RECEIPT_FIELDS = {
    "status",
    "node_id",
    "shard_index",
    "shard_digest_sha256",
    "question_ids",
    "item_count",
    "provider_mode",
    "activation_eligible",
    "approved_count",
    "rejected_count",
    "repair_required_count",
    "validated_items",
    "receipt_digest_sha256",
}

_V2_RESULT_FIELDS = {
    "item_handle",
    "question_correctness",
    "reference_answer_correctness",
    "node_alignment",
    "evidence_role_alignment",
    "contract_verdict",
    "issues",
    "confidence",
}
_V2_ISSUE_FIELDS = {"code", "slot_key", "detail", "repairable"}
_V2_ISSUE_CODES = {
    "question_incorrect",
    "reference_answer_incorrect",
    "question_node_misaligned",
    "evidence_role_misaligned",
    "criterion_bundled",
    "criterion_overlap",
    "criterion_unobservable",
    "reference_evidence_broad",
    "reference_evidence_missing",
    "derived_grounding_invalid",
    "presentation_only_scored",
    "prompt_demand_missing",
    "slot_not_allowed",
    "score_weight_invalid",
    "mastery_dimension_invalid",
    "required_for_pass_invalid",
    "low_confidence",
    "other_contract_issue",
}


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _sha256_text(value: Any, field: str) -> str:
    value = _nonempty_text(value, field)
    if len(value) != 64 or value.lower() != value:
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a lowercase sha256 digest") from exc
    return value


def _provider_mode(value: Any) -> str:
    if value not in _PROVIDER_MODES:
        raise ValueError("unsupported review provider mode")
    return value


def _exact_mapping(
    value: Any,
    required: set[str],
    field: str,
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a mapping")
    optional = optional or set()
    if not required.issubset(value) or set(value).difference(required | optional):
        raise ValueError(f"{field} fields do not match the exact schema")
    return value


def _reject_forbidden_descriptor_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("descriptor keys must be strings")
            lowered = key.lower()
            if any(token in lowered for token in ("hash", "fingerprint", "digest")):
                raise ValueError("descriptor keys cannot contain hash lineage fields")
            _reject_forbidden_descriptor_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_descriptor_keys(nested)


def _validate_descriptors(instance: Any, core: Any) -> None:
    _reject_forbidden_descriptor_keys(instance)
    _reject_forbidden_descriptor_keys(core)
    instance = _exact_mapping(
        instance, {"relations", "values", "requested"}, "instance descriptor"
    )
    core = _exact_mapping(core, {"relation", "evidence"}, "core descriptor")

    for field in ("relations", "requested"):
        values = instance[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise TypeError(f"instance {field} must be a list of nonempty strings")
    values = instance["values"]
    if not isinstance(values, list):
        raise TypeError("instance values must be a list")
    value_names = set()
    for entry in values:
        entry = _exact_mapping(entry, {"name", "value"}, "instance value entry")
        name = _nonempty_text(entry["name"], "instance value name")
        if any(token in name.lower() for token in ("hash", "fingerprint", "digest")):
            raise ValueError("instance value names cannot contain hash lineage fields")
        if name in value_names:
            raise ValueError("instance value names must be unique")
        value_names.add(name)
        value = entry["value"]
        if value is not None and type(value) not in {str, int, float, bool}:
            raise TypeError("instance values must contain scalar values only")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("instance numeric values must be finite")

    _nonempty_text(core["relation"], "core relation")
    evidence = core["evidence"]
    if not isinstance(evidence, list) or not all(
        isinstance(value, str) and value.strip() for value in evidence
    ):
        raise TypeError("core evidence must be a list of nonempty strings")


def _validate_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TypeError("review item must be a mapping")
    for field in (
        "review_item_handle",
        "question_id",
        "item_version",
        "contract_id",
        "node_id",
        "kind",
        "evidence_role",
    ):
        _nonempty_text(item.get(field), field)
    _sha256_text(item.get("question_digest_sha256"), "question_digest_sha256")
    _sha256_text(item.get("contract_digest_sha256"), "contract_digest_sha256")
    version = item.get("contract_version")
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ValueError("contract_version must be a positive integer")
    return item


def shard_digest(items: list[dict[str, Any]]) -> str:
    if not isinstance(items, list) or not items:
        raise ValueError("shard items must be a nonempty list")
    ordered = sorted(
        (deepcopy(_validate_item(item)) for item in items),
        key=lambda item: (item["node_id"], item["question_id"]),
    )
    return question_fingerprints.canonical_sha256(
        {"shard_size_policy": SHARD_SIZE, "items": ordered}
    )


def plan_review_shards(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise TypeError("items must be a list")
    validated = [_validate_item(item) for item in items]
    ids = [item["question_id"] for item in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("review items cannot contain duplicate question ids")
    by_node: dict[str, list[dict[str, Any]]] = {}
    for item in validated:
        by_node.setdefault(item["node_id"], []).append(deepcopy(item))
    shards = []
    for node_id in sorted(by_node):
        ordered = sorted(by_node[node_id], key=lambda item: item["question_id"])
        for offset in range(0, len(ordered), SHARD_SIZE):
            shard_items = ordered[offset : offset + SHARD_SIZE]
            shards.append(
                {
                    "node_id": node_id,
                    "shard_index": offset // SHARD_SIZE,
                    "items": shard_items,
                    "shard_digest_sha256": shard_digest(shard_items),
                }
            )
    return shards


def _validate_nested_result(result: dict[str, Any]) -> None:
    correctness = _exact_mapping(
        result["question_correctness"],
        _QUESTION_CORRECTNESS_FIELDS,
        "question_correctness",
    )
    if correctness["verdict"] not in {"pass", "fail"}:
        raise ValueError("invalid question correctness verdict")
    _nonempty_text(correctness["independent_solution"], "independent_solution")
    _nonempty_text(correctness["rationale"], "question correctness rationale")

    alignment = _exact_mapping(
        result["question_node_alignment"],
        _NODE_ALIGNMENT_FIELDS,
        "question_node_alignment",
    )
    if alignment["verdict"] not in {"aligned", "misbound", "unclear"}:
        raise ValueError("invalid question-node alignment verdict")
    for field in _NODE_ALIGNMENT_FIELDS - {"verdict", "advisory_candidate_node"}:
        _nonempty_text(alignment[field], field)
    if alignment["advisory_candidate_node"] is not None:
        _nonempty_text(alignment["advisory_candidate_node"], "advisory_candidate_node")

    evidence = _exact_mapping(
        result["evidence_role_alignment"],
        _EVIDENCE_ALIGNMENT_FIELDS,
        "evidence_role_alignment",
    )
    if evidence["verdict"] not in {"aligned", "misaligned", "unclear"}:
        raise ValueError("invalid evidence-role alignment verdict")
    _nonempty_text(evidence["actual_evidence_demand"], "actual_evidence_demand")
    _nonempty_text(evidence["rationale"], "evidence-role rationale")

    contract_review = _exact_mapping(
        result["answer_contract_review"],
        _CONTRACT_REVIEW_FIELDS,
        "answer_contract_review",
    )
    if contract_review["verdict"] not in {"approved", "rejected"}:
        raise ValueError("invalid answer-contract verdict")
    checks = (
        "reference_solution_correct",
        "criteria_atomic_and_observable",
        "weights_and_dimensions_valid",
        "required_for_pass_valid",
    )
    if any(not isinstance(contract_review[field], bool) for field in checks):
        raise TypeError("answer-contract review checks must be boolean")
    corrections = contract_review["corrections"]
    if not isinstance(corrections, list) or not all(
        isinstance(value, str) and value.strip() for value in corrections
    ):
        raise TypeError("corrections must be a list of nonempty strings")
    if contract_review["verdict"] == "approved" and (
        not all(contract_review[field] for field in checks) or corrections
    ):
        raise ValueError("approved contract review is internally inconsistent")

    _validate_descriptors(
        result["normalized_instance_descriptor"],
        result["normalized_core_structure_descriptor"],
    )
    confidence = result["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be numeric")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between zero and one")


def validate_review_output_shape(review_results: Any) -> None:
    if not isinstance(review_results, list) or not 1 <= len(review_results) <= SHARD_SIZE:
        raise ValueError("review results must contain one to five items")
    handles = set()
    for result in review_results:
        if not isinstance(result, dict) or set(result) != _SEMANTIC_RESULT_FIELDS:
            raise ValueError("semantic review result fields must match the exact schema")
        handle = _nonempty_text(result.get("item_handle"), "item_handle")
        if handle in handles:
            raise ValueError("semantic review item handles must be unique")
        handles.add(handle)
        _validate_nested_result(result)


def validate_review_v2_output_shape(review_results: Any) -> None:
    if not isinstance(review_results, list) or not 1 <= len(review_results) <= SHARD_SIZE:
        raise ValueError("v2 review results must contain one to five items")
    handles = set()
    for result in review_results:
        if not isinstance(result, dict) or set(result) != _V2_RESULT_FIELDS:
            raise ValueError("v2 semantic review fields must match the exact schema")
        handle = _nonempty_text(result["item_handle"], "item_handle")
        if handle in handles:
            raise ValueError("v2 semantic review item handles must be unique")
        handles.add(handle)
        if result["question_correctness"] not in {"pass", "fail", "unclear"}:
            raise ValueError("invalid v2 question correctness verdict")
        if result["reference_answer_correctness"] not in {
            "pass",
            "fail",
            "unclear",
        }:
            raise ValueError("invalid v2 reference-answer verdict")
        if result["node_alignment"] not in {"aligned", "misbound", "unclear"}:
            raise ValueError("invalid v2 node alignment verdict")
        if result["evidence_role_alignment"] not in {
            "aligned",
            "misaligned",
            "unclear",
        }:
            raise ValueError("invalid v2 evidence-role verdict")
        if result["contract_verdict"] not in {"approved", "rejected"}:
            raise ValueError("invalid v2 contract verdict")
        confidence = result["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("v2 review confidence must be between zero and one")
        issues = result["issues"]
        if not isinstance(issues, list) or len(issues) > 12:
            raise ValueError("v2 review issues must be a list of at most twelve items")
        issue_keys = set()
        issue_codes = set()
        for issue in issues:
            issue = _exact_mapping(issue, _V2_ISSUE_FIELDS, "v2 review issue")
            code = issue["code"]
            if code not in _V2_ISSUE_CODES:
                raise ValueError("unsupported v2 review issue code")
            slot_key = issue["slot_key"]
            if slot_key is not None:
                slot_key = _nonempty_text(slot_key, "v2 review issue slot_key")
            detail = _nonempty_text(issue["detail"], "v2 review issue detail")
            if not isinstance(issue["repairable"], bool):
                raise TypeError("v2 review issue repairable must be boolean")
            issue_key = (code, slot_key, detail)
            if issue_key in issue_keys:
                raise ValueError("v2 review issues must be unique")
            issue_keys.add(issue_key)
            issue_codes.add(code)
        required_issue_codes = set()
        if result["question_correctness"] != "pass":
            required_issue_codes.add("question_incorrect")
        if result["reference_answer_correctness"] != "pass":
            required_issue_codes.add("reference_answer_incorrect")
        if result["node_alignment"] != "aligned":
            required_issue_codes.add("question_node_misaligned")
        if result["evidence_role_alignment"] != "aligned":
            required_issue_codes.add("evidence_role_misaligned")
        if not required_issue_codes.issubset(issue_codes):
            raise ValueError("v2 semantic failures require matching structured issues")
        all_semantic_pass = not required_issue_codes
        if result["contract_verdict"] == "approved":
            if issues or not all_semantic_pass:
                raise ValueError("approved v2 review cannot contain semantic issues")
        elif not issues:
            raise ValueError("rejected v2 review requires structured issues")


def route_review_v2_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        raise TypeError("v2 review issues must be a list")
    routes = []
    seen = set()
    question_bank_codes = {
        "question_incorrect",
        "reference_answer_incorrect",
        "question_node_misaligned",
        "evidence_role_misaligned",
    }
    assessment_policy_codes = {
        "score_weight_invalid",
        "mastery_dimension_invalid",
        "required_for_pass_invalid",
    }
    for issue in issues:
        issue = _exact_mapping(issue, _V2_ISSUE_FIELDS, "v2 review issue")
        code = issue.get("code")
        if code not in _V2_ISSUE_CODES:
            raise ValueError("unsupported v2 review issue code")
        owner = (
            "question_bank"
            if code in question_bank_codes
            else "assessment_policy"
            if code in assessment_policy_codes
            else "answer_contract"
        )
        route = {
            "owner": owner,
            "action": (
                "new_immutable_question_version"
                if owner == "question_bank"
                else "revise_policy_catalog"
                if owner == "assessment_policy"
                else "regenerate_contract_draft"
            ),
            "reason_code": code,
            "preserve_bound_node": True,
        }
        key = tuple(route.items())
        if key not in seen:
            seen.add(key)
            routes.append(route)
    return routes


def bind_semantic_review_results(
    expected_items: list[dict[str, Any]],
    semantic_results: list[dict[str, Any]],
    *,
    item_handles: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(expected_items, list) or not isinstance(item_handles, list):
        raise TypeError("expected items and item handles must be lists")
    if len(expected_items) != len(item_handles):
        raise ValueError("item handles must cover every expected item")
    validate_review_output_shape(semantic_results)
    if len(semantic_results) != len(expected_items):
        raise ValueError("semantic review result count does not match sealed input")
    if [result["item_handle"] for result in semantic_results] != item_handles:
        raise ValueError("semantic review result order or item handle does not match sealed input")

    bound = []
    for item, semantic in zip(expected_items, semantic_results):
        authoritative = _validate_item(item)
        result = {
            "question_id": authoritative["question_id"],
            "item_version": authoritative["item_version"],
            "question_digest_sha256": authoritative["question_digest_sha256"],
            "contract_id": authoritative["contract_id"],
            "contract_version": authoritative["contract_version"],
            "contract_digest_sha256": authoritative["contract_digest_sha256"],
            **{
                key: deepcopy(value)
                for key, value in semantic.items()
                if key != "item_handle"
            },
        }
        if set(result) != _RESULT_FIELDS:
            raise ValueError("locally bound review result fields are incomplete")
        _validate_nested_result(result)
        bound.append(result)
    return bound


def _repair_route(
    correctness: str, node_alignment: str, evidence_alignment: str, contract: str
) -> dict[str, Any] | None:
    if correctness != "pass":
        return {
            "owner": "question_bank",
            "action": "new_immutable_question_version",
            "reason_code": "question_correctness_failed",
            "preserve_bound_node": True,
        }
    if node_alignment == "misbound":
        return {
            "owner": "question_bank",
            "action": "new_immutable_question_version",
            "reason_code": "question_node_misalignment",
            "preserve_bound_node": True,
        }
    if node_alignment == "unclear":
        return {
            "owner": "question_bank",
            "action": "new_immutable_question_version",
            "reason_code": "question_node_alignment_unclear",
            "preserve_bound_node": True,
        }
    if evidence_alignment == "misaligned":
        return {
            "owner": "question_bank",
            "action": "new_immutable_question_version",
            "reason_code": "evidence_role_misalignment",
            "preserve_bound_node": True,
        }
    if evidence_alignment == "unclear":
        return {
            "owner": "question_bank",
            "action": "new_immutable_question_version",
            "reason_code": "evidence_role_alignment_unclear",
            "preserve_bound_node": True,
        }
    if contract != "approved":
        return {
            "owner": "answer_contract",
            "action": "regenerate_contract_draft",
            "reason_code": "answer_contract_rejected",
            "preserve_bound_node": True,
        }
    return None


def _derive_outcome_fields(outcome: dict[str, Any]) -> dict[str, Any]:
    semantic_route = _repair_route(
        outcome["question_correctness_verdict"],
        outcome["question_node_alignment_verdict"],
        outcome["evidence_role_alignment_verdict"],
        outcome["answer_contract_verdict"],
    )
    approved = semantic_route is None
    low_confidence = outcome["confidence"] < outcome["minimum_confidence"]
    route = semantic_route
    if route is None and low_confidence:
        route = {
            "owner": "answer_contract_review",
            "action": "manual_confidence_review",
            "reason_code": "semantic_review_low_confidence",
            "preserve_bound_node": True,
        }
    return {
        "review_status": "approved" if approved else "rejected",
        "repair_required": route is not None,
        "repair_route": route,
        "needs_retry": low_confidence,
        "blockers": ["low_confidence"] if low_confidence else [],
        "activation_eligible": approved
        and not low_confidence
        and outcome["provider_mode"] == "live_model",
    }


def _with_validated_digest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "validated_item_digest_sha256": question_fingerprints.canonical_sha256(payload),
    }


def validate_review_items(
    expected_items: list[dict[str, Any]],
    review_results: list[dict[str, Any]],
    *,
    provider_mode: str,
    minimum_confidence: float = 0.8,
) -> list[dict[str, Any]]:
    provider_mode = _provider_mode(provider_mode)
    if (
        isinstance(minimum_confidence, bool)
        or not isinstance(minimum_confidence, (int, float))
        or not 0 <= minimum_confidence <= 1
    ):
        raise ValueError("minimum_confidence must be between zero and one")
    if not isinstance(expected_items, list) or not isinstance(review_results, list):
        raise TypeError("expected items and review results must be lists")
    expected = [_validate_item(item) for item in expected_items]
    expected_by_id = {item["question_id"]: item for item in expected}
    if len(expected_by_id) != len(expected):
        raise ValueError("expected review items contain duplicate ids")
    if len(review_results) != len(expected):
        raise ValueError("review results must cover every expected item exactly once")

    if all(
        isinstance(result, dict) and set(result) == _SEMANTIC_RESULT_FIELDS
        for result in review_results
    ):
        review_results = bind_semantic_review_results(
            expected,
            review_results,
            item_handles=[item["review_item_handle"] for item in expected],
        )

    results_by_id = {}
    for result in review_results:
        if not isinstance(result, dict) or set(result) != _RESULT_FIELDS:
            raise ValueError("review result fields must match the exact schema")
        question_id = _nonempty_text(result.get("question_id"), "question_id")
        if question_id not in expected_by_id or question_id in results_by_id:
            raise ValueError("review result id is unknown or duplicated")
        item = expected_by_id[question_id]
        for field in (
            "item_version",
            "question_digest_sha256",
            "contract_id",
            "contract_version",
            "contract_digest_sha256",
        ):
            if result.get(field) != item[field]:
                raise ValueError(f"review result {field} does not match expected lineage")
        _validate_nested_result(result)
        results_by_id[question_id] = result

    validated = []
    for item in expected:
        result = results_by_id[item["question_id"]]
        payload = {
            "question_id": item["question_id"],
            "item_version": item["item_version"],
            "question_digest_sha256": item["question_digest_sha256"],
            "contract_id": item["contract_id"],
            "contract_version": item["contract_version"],
            "contract_digest_sha256": item["contract_digest_sha256"],
            "bound_node_id": item["node_id"],
            "question_correctness_verdict": result["question_correctness"]["verdict"],
            "question_node_alignment_verdict": result["question_node_alignment"]["verdict"],
            "evidence_role_alignment_verdict": result["evidence_role_alignment"]["verdict"],
            "answer_contract_verdict": result["answer_contract_review"]["verdict"],
            "normalized_instance_descriptor": deepcopy(result["normalized_instance_descriptor"]),
            "normalized_core_structure_descriptor": deepcopy(result["normalized_core_structure_descriptor"]),
            "confidence": result["confidence"],
            "minimum_confidence": float(minimum_confidence),
            "provider_mode": provider_mode,
            **question_fingerprints.fingerprint_pair(
                result["normalized_instance_descriptor"],
                result["normalized_core_structure_descriptor"],
            ),
        }
        payload.update(_derive_outcome_fields(payload))
        validated.append(_with_validated_digest(payload))
    return validated


def _validate_local_outcome(
    expected_item: dict[str, Any], outcome: Any, provider_mode: str
) -> dict[str, Any]:
    if not isinstance(outcome, dict) or set(outcome) != _VALIDATED_FIELDS:
        raise ValueError("validated outcome fields do not match the exact schema")
    payload = {key: deepcopy(value) for key, value in outcome.items() if key != "validated_item_digest_sha256"}
    if outcome["validated_item_digest_sha256"] != question_fingerprints.canonical_sha256(payload):
        raise ValueError("validated item digest mismatch")
    for source, target in (
        ("question_id", "question_id"),
        ("item_version", "item_version"),
        ("question_digest_sha256", "question_digest_sha256"),
        ("contract_id", "contract_id"),
        ("contract_version", "contract_version"),
        ("contract_digest_sha256", "contract_digest_sha256"),
        ("bound_node_id", "node_id"),
    ):
        if outcome[source] != expected_item[target]:
            raise ValueError("validated outcome does not match expected item lineage")
    if outcome["provider_mode"] != provider_mode:
        raise ValueError("validated outcome provider mismatch")
    if outcome["question_correctness_verdict"] not in {"pass", "fail"}:
        raise ValueError("invalid local correctness verdict")
    if outcome["question_node_alignment_verdict"] not in {"aligned", "misbound", "unclear"}:
        raise ValueError("invalid local node verdict")
    if outcome["evidence_role_alignment_verdict"] not in {"aligned", "misaligned", "unclear"}:
        raise ValueError("invalid local evidence verdict")
    if outcome["answer_contract_verdict"] not in {"approved", "rejected"}:
        raise ValueError("invalid local contract verdict")
    for field in ("confidence", "minimum_confidence"):
        value = outcome[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError(f"invalid local {field}")
    _validate_descriptors(
        outcome["normalized_instance_descriptor"],
        outcome["normalized_core_structure_descriptor"],
    )
    expected_fingerprints = question_fingerprints.fingerprint_pair(
        outcome["normalized_instance_descriptor"],
        outcome["normalized_core_structure_descriptor"],
    )
    if any(outcome[field] != value for field, value in expected_fingerprints.items()):
        raise ValueError("validated outcome fingerprint mismatch")
    if any(outcome[field] != value for field, value in _derive_outcome_fields(outcome).items()):
        raise ValueError("validated outcome derived fields were tampered")
    return outcome


def _receipt_digest(payload: dict[str, Any]) -> str:
    return question_fingerprints.canonical_sha256(payload)


def build_shard_receipt(
    shard: dict[str, Any],
    validated_items: list[dict[str, Any]],
    *,
    provider_mode: str,
) -> dict[str, Any] | None:
    provider_mode = _provider_mode(provider_mode)
    if not isinstance(shard, dict) or not isinstance(validated_items, list):
        raise TypeError("shard and validated items have invalid types")
    expected_digest = shard_digest(shard.get("items"))
    if shard.get("shard_digest_sha256") != expected_digest:
        raise ValueError("shard digest does not match expected items")
    expected_items = shard["items"]
    by_id = {}
    for outcome in validated_items:
        if not isinstance(outcome, dict):
            raise TypeError("validated outcome must be a mapping")
        question_id = outcome.get("question_id")
        if question_id in by_id:
            raise ValueError("validated shard items contain duplicate ids")
        by_id[question_id] = outcome
    expected_ids = [item["question_id"] for item in expected_items]
    if set(by_id) != set(expected_ids) or len(by_id) != len(expected_ids):
        return None
    ordered = [
        deepcopy(_validate_local_outcome(item, by_id[item["question_id"]], provider_mode))
        for item in expected_items
    ]
    payload = {
        "status": "complete",
        "node_id": shard["node_id"],
        "shard_index": shard.get("shard_index"),
        "shard_digest_sha256": expected_digest,
        "question_ids": expected_ids,
        "item_count": len(expected_ids),
        "provider_mode": provider_mode,
        "activation_eligible": provider_mode == "live_model"
        and all(item["activation_eligible"] for item in ordered),
        "approved_count": sum(item["review_status"] == "approved" for item in ordered),
        "rejected_count": sum(item["review_status"] == "rejected" for item in ordered),
        "repair_required_count": sum(item["repair_required"] for item in ordered),
        "validated_items": ordered,
    }
    return {**payload, "receipt_digest_sha256": _receipt_digest(payload)}


def build_node_receipt(
    node_id: str,
    *,
    expected_shards: list[dict[str, Any]],
    shard_receipts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    node_id = _nonempty_text(node_id, "node_id")
    if not isinstance(expected_shards, list) or not isinstance(shard_receipts, list):
        raise TypeError("expected shards and shard receipts must be lists")
    expected = {}
    for shard in expected_shards:
        if shard.get("node_id") != node_id:
            raise ValueError("expected shard belongs to another node")
        digest = shard_digest(shard.get("items"))
        if shard.get("shard_digest_sha256") != digest or digest in expected:
            raise ValueError("expected shard digest is invalid or duplicated")
        expected[digest] = shard

    received = {}
    receipt_digests = set()
    for receipt in shard_receipts:
        if not isinstance(receipt, dict) or set(receipt) != _SHARD_RECEIPT_FIELDS:
            raise ValueError("shard receipt fields do not match the exact schema")
        digest = receipt.get("shard_digest_sha256")
        if digest not in expected or digest in received:
            raise ValueError("unknown or duplicate shard receipt")
        if receipt["receipt_digest_sha256"] in receipt_digests:
            raise ValueError("duplicate shard receipt digest")
        rebuilt = build_shard_receipt(
            expected[digest],
            receipt["validated_items"],
            provider_mode=receipt["provider_mode"],
        )
        if rebuilt is None or rebuilt != receipt:
            raise ValueError("shard receipt content or digest was tampered")
        receipt_digests.add(receipt["receipt_digest_sha256"])
        received[digest] = receipt
    if set(received) != set(expected):
        return None
    providers = {receipt["provider_mode"] for receipt in received.values()}
    if len(providers) != 1:
        raise ValueError("node receipt cannot mix provider modes")
    provider_mode = _provider_mode(providers.pop())
    ordered = [received[digest] for digest in sorted(received)]
    payload = {
        "status": "complete",
        "node_id": node_id,
        "shard_count": len(ordered),
        "item_count": sum(receipt["item_count"] for receipt in ordered),
        "shard_digests": [receipt["shard_digest_sha256"] for receipt in ordered],
        "provider_mode": provider_mode,
        "activation_eligible": provider_mode == "live_model"
        and all(receipt["activation_eligible"] for receipt in ordered),
        "approved_count": sum(receipt["approved_count"] for receipt in ordered),
        "rejected_count": sum(receipt["rejected_count"] for receipt in ordered),
        "repair_required_count": sum(receipt["repair_required_count"] for receipt in ordered),
    }
    return {**payload, "receipt_digest_sha256": _receipt_digest(payload)}
