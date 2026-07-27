"""Internal v2 engine; production callers use answer_contract_generation."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from . import (
    answer_contract_activation,
    answer_contract_batch_v2,
    answer_contract_review,
    assessment_policy,
    db,
    internal_agents,
    model_router,
    question_fingerprints,
    semantic_agents,
)


DESIGNER_AGENT_KEY = "answer_contract_designer_agent"
DESIGNER_PHASE = "answer_contract_design_v2"
REVIEWER_AGENT_KEY = "answer_contract_reviewer_agent"
REVIEWER_PHASE = "answer_contract_review_v2"
DESIGN_VERSION_SUFFIX = "v2"
REVIEW_VERSION_SUFFIX = "v2"
GENERATOR_VERSION = "semantic_designer_local_compiler.v2"
MAX_CONTRACT_VERSIONS = 3
CANARY_SIZE = 40
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (20.0, 60.0)
MAX_RETRY_AFTER_SECONDS = 120.0
ITEM_WALL_SECONDS = 180.0
V12_SCORING_POLICY_GATE_QUESTION_IDS = frozenset()

QUESTION_BANK_ISSUE_CODES = {
    "question_incorrect",
    "reference_answer_incorrect",
    "question_node_misaligned",
    "evidence_role_misaligned",
}
CONTRACT_ISSUE_CODES = {
    "criterion_bundled",
    "criterion_overlap",
    "criterion_unobservable",
    "reference_evidence_broad",
    "reference_evidence_missing",
    "derived_grounding_invalid",
    "presentation_only_scored",
    "prompt_demand_missing",
    "slot_not_allowed",
    "low_confidence",
    "other_contract_issue",
}
ASSESSMENT_POLICY_ISSUE_CODES = {
    "score_weight_invalid",
    "mastery_dimension_invalid",
    "required_for_pass_invalid",
}


class ContractRepairError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


class LocalSemanticRejection(ValueError):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


def _digest(value: Any) -> str:
    return question_fingerprints.canonical_sha256(value)


def _receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "receipt_digest_sha256": _digest(payload)}


def _valid_receipt(payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("receipt_digest_sha256"), str
    ):
        return False
    body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_digest_sha256"
    }
    return payload["receipt_digest_sha256"] == _digest(body)


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty path component")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe {field}")
    return value


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _question_digest(question: dict[str, Any]) -> str:
    return _digest(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "node_id": question["node_id"],
            "kind": question["kind"],
            "prompt": question["prompt"],
            "answer_format": question.get("answer_format"),
            "expected_answer": question.get("expected_answer"),
            "solution_steps": question.get("solution_steps") or [],
            "reference_evidence": question.get("reference_evidence"),
        }
    )


def _contract_versions() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        internal_agents.load_contract_for_agent_version(
            DESIGNER_AGENT_KEY, DESIGN_VERSION_SUFFIX
        ),
        internal_agents.load_contract_for_agent_version(
            REVIEWER_AGENT_KEY, REVIEW_VERSION_SUFFIX
        ),
    )


def _generation_input_digest_for_packet(packet: dict[str, Any]) -> str:
    return _digest(
        {
            "item_handle": packet["item_handle"],
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "node_id": packet["node_id"],
            "graph_version": packet["graph_version"],
            "bank_version": packet["bank_version"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
            "repair_iteration": packet["repair_iteration"],
            "parent_contract_digest_sha256": packet[
                "parent_contract_digest_sha256"
            ],
            "review_issue_digest_sha256": packet[
                "review_issue_digest_sha256"
            ],
            "designer_attempt": packet["designer_attempt"],
            "local_compiler_issue_digest_sha256": packet[
                "local_compiler_issue_digest_sha256"
            ],
        }
    )


def build_design_packet_v2(
    *,
    question: dict[str, Any],
    graph_version: str,
    bank_version: str,
    review_record_id: str,
    repair_iteration: int = 0,
    parent_contract: dict[str, Any] | None = None,
    reviewer_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if (
        isinstance(repair_iteration, bool)
        or not isinstance(repair_iteration, int)
        or not 0 <= repair_iteration < MAX_CONTRACT_VERSIONS
    ):
        raise ValueError("repair_iteration must be zero, one, or two")
    skeleton = assessment_policy.build_contract_skeleton_v2(question)
    question_digest = _question_digest(question)
    issue_advisory = deepcopy(reviewer_issues or [])
    issue_digest = _digest(issue_advisory)
    local_compiler_issues: list[dict[str, Any]] = []
    local_issue_digest = _digest(local_compiler_issues)
    parent_digest = str((parent_contract or {}).get("contract_digest_sha256") or "")
    item_handle = "design-v2-" + _digest(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "question_digest_sha256": question_digest,
            "repair_iteration": repair_iteration,
            "parent_contract_digest_sha256": parent_digest,
            "review_issue_digest_sha256": issue_digest,
        }
    )[:24]
    sealed_skeleton = {**deepcopy(skeleton), "item_handle": item_handle}
    packet = {
        "item_handle": item_handle,
        "question_id": question["id"],
        "item_version": question["item_version"],
        "node_id": question["node_id"],
        "question_kind": question["kind"],
        "graph_version": graph_version,
        "bank_version": bank_version,
        "review_record_id": review_record_id,
        "question_digest_sha256": question_digest,
        "profile_digest_sha256": _digest(skeleton),
        "repair_iteration": repair_iteration,
        "parent_contract_id": (parent_contract or {}).get("id"),
        "parent_contract_version": (parent_contract or {}).get("contract_version"),
        "parent_contract_digest_sha256": parent_digest,
        "review_issue_digest_sha256": issue_digest,
        "reviewer_issues": issue_advisory,
        "designer_attempt": 0,
        "local_compiler_issue_digest_sha256": local_issue_digest,
        "local_compiler_issues": local_compiler_issues,
        "skeleton": sealed_skeleton,
        "question": {
            "prompt": question["prompt"],
            "answer_format": question.get("answer_format"),
            "expected_answer": deepcopy(question.get("expected_answer")),
            "solution_steps": deepcopy(question.get("solution_steps") or []),
        },
    }
    packet["generation_input_digest_sha256"] = _generation_input_digest_for_packet(
        packet
    )
    return packet


def _batch_request_lineage(
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None,
    *,
    expected_role: str,
) -> tuple[dict[str, str], dict[str, str]]:
    if batch_context is None:
        return {}, {}
    validated = answer_contract_batch_v2.validate_batch_attempt_context(
        batch_context,
        expected_role=expected_role,
        stage="request",
    )
    trusted = {
        "batch_attempt_id": validated.batch_attempt_id,
        "effective_evidence_role": validated.effective_evidence_role,
        "effective_evidence_role_policy_version": (
            validated.effective_evidence_role_policy_version
        ),
    }
    return trusted, {"batch_attempt_id": validated.batch_attempt_id}


def semantic_design_request_v2(
    packet: dict[str, Any],
    *,
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
) -> semantic_agents.SemanticAgentRequest:
    batch_trusted, batch_source_refs = _batch_request_lineage(
        batch_context,
        expected_role="designer",
    )
    catalog = [
        {
            "slot_key": slot["slot_key"],
            "description": slot["description"],
            "allowed_source_anchor_keys": deepcopy(
                slot["allowed_source_anchor_keys"]
            ),
        }
        for slot in packet["skeleton"]["allowed_slot_catalog"]
    ]
    reference_anchors = [
        {
            "key": key,
            "claim": value["claim"],
            "source": value["source"],
        }
        for key, value in packet["skeleton"]["reference_anchors"].items()
    ]
    return semantic_agents.SemanticAgentRequest(
        agent_key=DESIGNER_AGENT_KEY,
        phase=DESIGNER_PHASE,
        trusted_context={
            "agent_key": DESIGNER_AGENT_KEY,
            "phase": DESIGNER_PHASE,
            "item_handle": packet["item_handle"],
            "question_kind": packet["question_kind"],
            "profile_version": packet["skeleton"]["profile_version"],
            "allowed_slot_keys": [
                slot["slot_key"] for slot in catalog
            ],
            "allowed_slot_catalog": catalog,
            "repair_iteration": packet["repair_iteration"],
            "designer_attempt": packet["designer_attempt"],
            **batch_trusted,
        },
        untrusted_payload={
            "question": deepcopy(packet["question"]),
            "reference_anchors": reference_anchors,
            "reviewer_issues": deepcopy(packet["reviewer_issues"]),
            "local_compiler_issues": deepcopy(
                packet["local_compiler_issues"]
            ),
        },
        provider_mode="live_model",
        source_refs={
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "local_compiler_issue_digest_sha256": packet[
                "local_compiler_issue_digest_sha256"
            ],
            **batch_source_refs,
        },
        contract_version_suffix=DESIGN_VERSION_SUFFIX,
    )


def compile_design_output_v2(
    packet: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    design_contract, _review_contract = _contract_versions()
    if (
        not isinstance(output, dict)
        or set(output) != {"schema_version", "items"}
        or output.get("schema_version")
        != design_contract["response_schema_version"]
    ):
        raise ValueError("v2 designer output schema lineage mismatch")
    question = {
        "id": packet["question_id"],
        "item_version": packet["item_version"],
        "node_id": packet["node_id"],
        "kind": packet["question_kind"],
        **deepcopy(packet["question"]),
        "reference_anchors": deepcopy(packet["skeleton"]["reference_anchors"]),
    }
    return assessment_policy.compile_answer_contract_v2(
        question, packet["skeleton"], output["items"]
    )


def build_review_packet_v2(
    packet: dict[str, Any], compiled_contract: dict[str, Any]
) -> dict[str, Any]:
    _design_contract, review_contract = _contract_versions()
    contract_digest = _digest(compiled_contract)
    review_handle = "review-v2-" + _digest(
        {
            "design_item_handle": packet["item_handle"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "compiled_contract_digest_sha256": contract_digest,
        }
    )[:24]
    return {
        "item_handle": review_handle,
        "repair_iteration": packet["repair_iteration"],
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "node_id": packet["node_id"],
        "question_kind": packet["question_kind"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "compiled_contract_digest_sha256": contract_digest,
        "review_schema_version": review_contract["response_schema_version"],
        "question": deepcopy(packet["question"]),
        "compiled_contract": deepcopy(compiled_contract),
    }


def semantic_review_request_v2(
    review_packet: dict[str, Any],
    *,
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
) -> semantic_agents.SemanticAgentRequest:
    batch_trusted, batch_source_refs = _batch_request_lineage(
        batch_context,
        expected_role="reviewer",
    )
    return semantic_agents.SemanticAgentRequest(
        agent_key=REVIEWER_AGENT_KEY,
        phase=REVIEWER_PHASE,
        trusted_context={
            "agent_key": REVIEWER_AGENT_KEY,
            "phase": REVIEWER_PHASE,
            "item_handles": [review_packet["item_handle"]],
            "maximum_items": 5,
            **batch_trusted,
        },
        untrusted_payload={
            "items": [
                {
                    "item_handle": review_packet["item_handle"],
                    "bound_node_id": review_packet["node_id"],
                    "question_kind": review_packet["question_kind"],
                    "question": deepcopy(review_packet["question"]),
                    "compiled_contract": deepcopy(
                        review_packet["compiled_contract"]
                    ),
                }
            ]
        },
        provider_mode="live_model",
        source_refs={
            "compiled_contract_digest_sha256": review_packet[
                "compiled_contract_digest_sha256"
            ],
            **batch_source_refs,
        },
        contract_version_suffix=REVIEW_VERSION_SUFFIX,
    )


def validate_review_output_v2(
    review_packet: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    _design_contract, review_contract = _contract_versions()
    if (
        not isinstance(output, dict)
        or set(output) != {"schema_version", "items"}
        or output.get("schema_version")
        != review_contract["response_schema_version"]
    ):
        raise ValueError("v2 reviewer output schema lineage mismatch")
    answer_contract_review.validate_review_v2_output_shape(output["items"])
    if len(output["items"]) != 1:
        raise ValueError("single-contract v2 review requires exactly one result")
    result = deepcopy(output["items"][0])
    if result["item_handle"] != review_packet["item_handle"]:
        raise ValueError("v2 reviewer item handle mismatch")
    return result


def classify_review_result_v2(result: dict[str, Any]) -> dict[str, Any]:
    issue_codes = [issue["code"] for issue in result["issues"]]
    semantic_failures = []
    if result["question_correctness"] != "pass":
        semantic_failures.append("question_incorrect")
    if result["reference_answer_correctness"] != "pass":
        semantic_failures.append("reference_answer_incorrect")
    if result["node_alignment"] != "aligned":
        semantic_failures.append("question_node_misaligned")
    if result["evidence_role_alignment"] != "aligned":
        semantic_failures.append("evidence_role_misaligned")
    question_bank_codes = [
        code
        for code in (
            "question_incorrect",
            "reference_answer_incorrect",
            "question_node_misaligned",
            "evidence_role_misaligned",
        )
        if code in set(issue_codes).union(semantic_failures)
    ]
    contract_codes = sorted(set(issue_codes).intersection(CONTRACT_ISSUE_CODES))
    if question_bank_codes:
        return {
            "status": "question_bank_repair_required",
            "approved": False,
            "repairable_contract": False,
            "issue_codes": issue_codes,
            "repair_route": {
                "owner": "question_bank",
                "action": "new_immutable_question_version",
                "reason_code": question_bank_codes[0],
                "preserve_bound_node": True,
            },
        }
    policy_codes = [
        code
        for code in (
            "score_weight_invalid",
            "mastery_dimension_invalid",
            "required_for_pass_invalid",
        )
        if code in issue_codes
    ]
    if policy_codes:
        return {
            "status": "assessment_policy_repair_required",
            "approved": False,
            "repairable_contract": False,
            "issue_codes": issue_codes,
            "repair_route": {
                "owner": "assessment_policy",
                "action": "revise_policy_catalog",
                "reason_code": policy_codes[0],
                "preserve_bound_node": True,
            },
        }
    approved = (
        result["contract_verdict"] == "approved"
        and not issue_codes
        and float(result["confidence"]) >= 0.8
    )
    if approved:
        return {
            "status": "approved",
            "approved": True,
            "repairable_contract": False,
            "issue_codes": [],
            "repair_route": None,
        }
    return {
        "status": "contract_repair_required",
        "approved": False,
        "repairable_contract": True,
        "issue_codes": issue_codes or ["low_confidence"],
        "repair_route": {
            "owner": "answer_contract",
            "action": "regenerate_contract_draft",
            "reason_code": (issue_codes or ["low_confidence"])[0],
            "preserve_bound_node": True,
        },
    }


def _classification_for_packet(
    packet: dict[str, Any],
    result: dict[str, Any],
    *,
    compiled_contract: dict[str, Any] | None = None,
    reviewer_run_id: str = "",
) -> dict[str, Any]:
    classification = classify_review_result_v2(result)
    if (
        classification["status"] == "assessment_policy_repair_required"
        and isinstance(compiled_contract, dict)
        and isinstance(reviewer_run_id, str)
        and reviewer_run_id
    ):
        classification = deepcopy(classification)
        classification["repair_route"].update(
            {
                "question_kind": packet["question_kind"],
                "profile_version": packet["skeleton"]["profile_version"],
                "profile_digest_sha256": packet["profile_digest_sha256"],
                "selected_slot_keys": [
                    point["key"]
                    for point in compiled_contract["score_points"]
                ],
                "contract_digest_sha256": _digest(compiled_contract),
                "reviewer_run_id": reviewer_run_id,
                "review_schema_version": _contract_versions()[1][
                    "response_schema_version"
                ],
                "requires_new_profile_digest": True,
                "existing_contract_activation_allowed": False,
            }
        )
    issue_digest = _digest(result["issues"])
    if (
        packet["repair_iteration"] > 0
        and result["issues"]
        and issue_digest == packet["review_issue_digest_sha256"]
        and classification["status"] == "contract_repair_required"
    ):
        return {
            **classification,
            "status": "contract_repair_exhausted",
            "approved": False,
            "repairable_contract": False,
            "repair_route": None,
        }
    return classification


def _checkpoint_path(root: Path, packet: dict[str, Any]) -> Path:
    target = (
        root.resolve()
        / _safe_component(packet["bank_version"], "bank_version")
        / _safe_component(packet["node_id"], "node_id")
        / _safe_component(packet["question_id"], "question_id")
        / f"contract-version-{packet['repair_iteration'] + 1}.json"
    ).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("v2 checkpoint path escapes root") from exc
    return target


def _classification_decision_key(classification: dict[str, Any]) -> dict[str, Any]:
    route = classification.get("repair_route")
    route_key = None
    if isinstance(route, dict):
        route_key = {
            key: deepcopy(route.get(key))
            for key in (
                "owner",
                "action",
                "reason_code",
                "preserve_bound_node",
                "question_kind",
                "profile_version",
                "profile_digest_sha256",
                "selected_slot_keys",
                "contract_digest_sha256",
                "requires_new_profile_digest",
                "existing_contract_activation_allowed",
            )
            if key in route
        }
    return {
        "status": classification.get("status"),
        "approved": classification.get("approved"),
        "repairable_contract": classification.get("repairable_contract"),
        "issue_codes": deepcopy(classification.get("issue_codes") or []),
        "repair_route": route_key,
    }


def _canonical_version_from_row(
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    compiled: dict[str, Any],
    row: sqlite3.Row | dict[str, Any],
) -> dict[str, Any]:
    values = dict(row)
    contract_digest = _digest(compiled)
    if (
        values.get("question_id") != packet["question_id"]
        or values.get("item_version") != packet["item_version"]
        or values.get("generation_input_digest_sha256")
        != packet["generation_input_digest_sha256"]
        or values.get("contract_digest_sha256") != contract_digest
        or values.get("generator_version") != GENERATOR_VERSION
        or db.json_load(values.get("reference_solution_json"), None)
        != compiled["reference_solution"]
        or db.json_load(values.get("score_points_json"), None)
        != compiled["score_points"]
    ):
        raise ValueError("persisted v2 contract canonical content mismatch")
    design_receipt = db.json_load(values.get("design_receipt_json"), {})
    review_receipt = db.json_load(values.get("review_receipt_json"), {})
    if (
        not _valid_receipt(design_receipt)
        or not _valid_receipt(review_receipt)
        or values.get("design_receipt_sha256")
        != design_receipt.get("receipt_digest_sha256")
        or values.get("review_receipt_sha256")
        != review_receipt.get("receipt_digest_sha256")
    ):
        raise ValueError("persisted v2 contract receipt lineage is invalid")
    if values.get("generator_batch_attempt_id") or values.get(
        "review_batch_attempt_id"
    ):
        if not values.get("generator_batch_attempt_id") or not values.get(
            "review_batch_attempt_id"
        ):
            raise ValueError("persisted v2 contract batch lineage is partial")
        design_lineage = answer_contract_batch_v2.persisted_agent_lineage(
            conn,
            batch_attempt_id=values["generator_batch_attempt_id"],
            agent_run_id=values["generator_run_id"],
        )
        review_lineage = answer_contract_batch_v2.persisted_agent_lineage(
            conn,
            batch_attempt_id=values["review_batch_attempt_id"],
            agent_run_id=values["review_run_id"],
        )
        design_chain = design_lineage["provider_chain"]
        review_chain = review_lineage["provider_chain"]
        if any(
            (
                design_receipt.get("agent_lineage") != design_lineage,
                design_receipt.get("agent_lineage_digest_sha256")
                != design_lineage["agent_lineage_digest_sha256"],
                design_receipt.get("provider_chain") != design_chain,
                design_receipt.get("provider_chain_digest_sha256")
                != design_chain["provider_chain_digest_sha256"],
                review_receipt.get("agent_lineage") != review_lineage,
                review_receipt.get("agent_lineage_digest_sha256")
                != review_lineage["agent_lineage_digest_sha256"],
                review_receipt.get("provider_chain") != review_chain,
                review_receipt.get("provider_chain_digest_sha256")
                != review_chain["provider_chain_digest_sha256"],
                values.get("generator_provider_chain_digest_sha256")
                != design_chain["provider_chain_digest_sha256"],
                values.get("review_provider_chain_digest_sha256")
                != review_chain["provider_chain_digest_sha256"],
            )
        ):
            raise ValueError("persisted v2 contract provider chain is stale")
    design_run = conn.execute(
        "select * from agent_runs where id = ?",
        (values.get("generator_run_id"),),
    ).fetchone()
    review_run = conn.execute(
        "select * from agent_runs where id = ?",
        (values.get("review_run_id"),),
    ).fetchone()
    if not design_run or not review_run:
        raise ValueError("persisted v2 contract agent run is missing")
    design_output = db.json_load(design_run["output_json"], None)
    review_output = db.json_load(review_run["output_json"], None)
    if not _validate_db_agent_run(
        conn,
        packet,
        {"agent_run_id": values["generator_run_id"], "output": design_output},
        role="designer",
    ):
        raise ValueError("persisted v2 designer run lineage is invalid")
    if compile_design_output_v2(packet, design_output) != compiled:
        raise ValueError("persisted v2 designer output does not compile canonically")
    review_packet = build_review_packet_v2(packet, compiled)
    if not _validate_db_agent_run(
        conn,
        review_packet,
        {"agent_run_id": values["review_run_id"], "output": review_output},
        role="reviewer",
    ):
        raise ValueError("persisted v2 reviewer run lineage is invalid")
    review_result = validate_review_output_v2(review_packet, review_output)
    classification = _classification_for_packet(
        packet,
        review_result,
        compiled_contract=compiled,
        reviewer_run_id=values["review_run_id"],
    )
    expected_status = "approved" if classification["approved"] else "rejected"
    if values.get("status") != expected_status:
        raise ValueError("persisted v2 contract verdict conflicts with its row status")
    activation_eligible = bool(
        classification["approved"]
        and design_receipt.get("exact_live_lineage") is True
        and review_receipt.get("exact_live_lineage") is True
    )
    if (
        design_receipt.get("agent_run_id") != values["generator_run_id"]
        or design_receipt.get("generation_input_digest_sha256")
        != packet["generation_input_digest_sha256"]
        or design_receipt.get("output_digest_sha256") != _digest(design_output)
        or review_receipt.get("agent_run_id") != values["review_run_id"]
        or review_receipt.get("contract_digest_sha256") != contract_digest
        or review_receipt.get("output_digest_sha256") != _digest(review_output)
        or review_receipt.get("issue_digest_sha256")
        != _digest(review_result["issues"])
        or review_receipt.get("classification") != classification
    ):
        raise ValueError("persisted v2 contract run or verdict receipt is stale")
    version_report = {
        "contract_id": values["id"],
        "contract_version": int(values["contract_version"]),
        "contract_digest_sha256": contract_digest,
        "repair_iteration": int(values.get("repair_iteration") or 0),
        "design_run_id": values["generator_run_id"],
        "review_run_id": values["review_run_id"],
        "review_result": review_result,
        "classification": classification,
        "activation_eligible": activation_eligible,
        "reused_checkpoint": False,
        "reused_persisted_row": True,
    }
    checkpoint_body = {
        "sealed": True,
        "status": classification["status"],
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "repair_iteration": packet["repair_iteration"],
        "parent_contract_id": packet["parent_contract_id"],
        "parent_contract_version": packet["parent_contract_version"],
        "design_item_handle": packet["item_handle"],
        "designer_attempt": packet["designer_attempt"],
        "local_compiler_issue_digest_sha256": packet[
            "local_compiler_issue_digest_sha256"
        ],
        "local_compiler_issues": deepcopy(packet["local_compiler_issues"]),
        "contract_digest_sha256": contract_digest,
        "design_schema_version": _contract_versions()[0][
            "response_schema_version"
        ],
        "review_schema_version": _contract_versions()[1][
            "response_schema_version"
        ],
        "design_receipt": design_receipt,
        "review_receipt": review_receipt,
        "compiled_contract": deepcopy(compiled),
        "review_result": review_result,
        "classification": classification,
        "activation_eligible": activation_eligible,
        "design_attempts": [],
        "review_attempts": [],
        "model_calls": 0,
    }
    return {
        "row": values,
        "classification": classification,
        "review_result": review_result,
        "version_report": version_report,
        "checkpoint_body": checkpoint_body,
    }


def _persist_contract_version(
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    compiled: dict[str, Any],
    design_envelope: dict[str, Any],
    review_envelope: dict[str, Any],
    review_result: dict[str, Any],
    classification: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    design_batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
    review_batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
) -> dict[str, Any]:
    if (design_batch_context is None) != (review_batch_context is None):
        raise ValueError("v2 contract batch lineage requires both contexts")
    if design_batch_context is not None and review_batch_context is not None:
        answer_contract_batch_v2._require_issued_context(design_batch_context)
        answer_contract_batch_v2._require_issued_context(review_batch_context)
        if (
            design_batch_context.run_id != review_batch_context.run_id
            or design_batch_context.run_item_id
            != review_batch_context.run_item_id
        ):
            raise ValueError("v2 contract batch contexts do not share one run item")
    generation_digest = packet["generation_input_digest_sha256"]
    stable_id = f"AC-{packet['question_id']}"

    def persist_in_current_transaction(
        batch_write_scope: (
            answer_contract_batch_v2.BatchAuthorityWriteScope | None
        ) = None,
    ) -> dict[str, Any]:
        if design_batch_context is not None and review_batch_context is not None:
            expected_agent_attempts = (
                (
                    design_envelope["agent_run_id"],
                    design_batch_context,
                    "designer",
                ),
                (
                    review_envelope["agent_run_id"],
                    review_batch_context,
                    "reviewer",
                ),
            )
            for agent_run_id, context, expected_role in expected_agent_attempts:
                answer_contract_batch_v2.validate_completed_batch_agent_result(
                    conn,
                    context,
                    agent_run_id=agent_run_id,
                    role=expected_role,
                    write_scope=batch_write_scope,
                )
        existing = conn.execute(
            """
            select * from answer_contracts
            where question_id = ? and item_version = ?
              and generation_input_digest_sha256 = ?
            """,
            (packet["question_id"], packet["item_version"], generation_digest),
        ).fetchone()
        if existing:
            if (
                design_batch_context is not None
                and (
                    existing["generator_batch_attempt_id"]
                    != design_batch_context.batch_attempt_id
                    or existing["review_batch_attempt_id"]
                    != review_batch_context.batch_attempt_id
                    or existing["generator_provider_chain_digest_sha256"]
                    != checkpoint["design_receipt"].get(
                        "provider_chain_digest_sha256", ""
                    )
                    or existing["review_provider_chain_digest_sha256"]
                    != checkpoint["review_receipt"].get(
                        "provider_chain_digest_sha256", ""
                    )
                )
            ):
                raise ValueError("v2 existing contract batch lineage conflict")
            if existing["contract_digest_sha256"] != checkpoint["contract_digest_sha256"]:
                raise ValueError("v2 idempotency digest conflict")
            canonical = _canonical_version_from_row(conn, packet, compiled, existing)
            if _classification_decision_key(canonical["classification"]) != _classification_decision_key(
                classification
            ):
                raise ValueError("v2 same-digest retry has a conflicting review verdict")
            return {**canonical, "reused_existing": True}
        version = int(
            conn.execute(
                "select coalesce(max(contract_version), 0) from answer_contracts where stable_contract_id = ?",
                (stable_id,),
            ).fetchone()[0]
            or 0
        ) + 1
        row_id = "ACV2-" + generation_digest[:20]
        now = db.now_iso()
        status = "approved" if classification["approved"] else "rejected"
        rejection = (
            {}
            if classification["approved"]
            else {
                "reason_code": classification["status"],
                "issue_codes": classification["issue_codes"],
                "repair_route": classification["repair_route"],
            }
        )
        conn.execute(
            """
            insert into answer_contracts(
              id, stable_contract_id, question_id, item_version,
              contract_version, contract_digest_sha256,
              question_digest_sha256, graph_version, question_bank_version,
              reference_solution_json, score_points_json, generator_version,
              generation_input_digest_sha256, generator_run_id,
              generator_batch_attempt_id,
              generator_provider_chain_digest_sha256,
              parent_contract_id, parent_contract_version,
              design_contract_schema_version, review_contract_schema_version,
              design_receipt_json, design_receipt_sha256,
              repair_iteration, repair_issue_digest_sha256,
              review_record_id, review_run_id, review_batch_attempt_id,
              review_provider_chain_digest_sha256,
              review_receipt_json, review_receipt_sha256,
              status, rejection_reason_json, approved_at, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                stable_id,
                packet["question_id"],
                packet["item_version"],
                version,
                checkpoint["contract_digest_sha256"],
                packet["question_digest_sha256"],
                packet["graph_version"],
                packet["bank_version"],
                db.json_dump(compiled["reference_solution"]),
                db.json_dump(compiled["score_points"]),
                GENERATOR_VERSION,
                generation_digest,
                design_envelope["agent_run_id"],
                (
                    design_batch_context.batch_attempt_id
                    if design_batch_context is not None
                    else None
                ),
                str(
                    checkpoint["design_receipt"].get(
                        "provider_chain_digest_sha256"
                    )
                    or ""
                ),
                packet["parent_contract_id"],
                packet["parent_contract_version"],
                checkpoint["design_schema_version"],
                checkpoint["review_schema_version"],
                db.json_dump(checkpoint["design_receipt"]),
                checkpoint["design_receipt"]["receipt_digest_sha256"],
                packet["repair_iteration"],
                packet["review_issue_digest_sha256"],
                packet["review_record_id"],
                review_envelope["agent_run_id"],
                (
                    review_batch_context.batch_attempt_id
                    if review_batch_context is not None
                    else None
                ),
                str(
                    checkpoint["review_receipt"].get(
                        "provider_chain_digest_sha256"
                    )
                    or ""
                ),
                db.json_dump(checkpoint["review_receipt"]),
                checkpoint["review_receipt"]["receipt_digest_sha256"],
                status,
                db.json_dump(rejection),
                now if status == "approved" else None,
                now,
                now,
            ),
        )
        row = conn.execute(
            "select * from answer_contracts where id = ?", (row_id,)
        ).fetchone()
        if not row:
            raise ValueError("v2 persisted contract could not be read back")
        return {"row": dict(row), "reused_existing": False}

    if design_batch_context is not None and review_batch_context is not None:
        with answer_contract_batch_v2.batch_authority_write_scope(
            conn,
            contexts=(
                ("designer", design_batch_context),
                ("reviewer", review_batch_context),
            ),
            stage="contract_persistence",
        ) as authority_scope:
            return persist_in_current_transaction(authority_scope)

    if conn.in_transaction:
        conn.commit()
    conn.execute("begin immediate")
    try:
        result = persist_in_current_transaction()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def _validate_live_envelope(
    envelope: Any,
    *,
    agent_key: str,
    phase: str,
    schema_version: str,
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise TypeError("v2 agent envelope must be a mapping")
    expected = {
        "agent_key": agent_key,
        "phase": phase,
        "status": "accepted",
        "provider_mode": "live_model",
    }
    if any(envelope.get(key) != value for key, value in expected.items()):
        raise ValueError("v2 agent envelope requires exact live lineage")
    if not isinstance(envelope.get("agent_run_id"), str) or not envelope[
        "agent_run_id"
    ]:
        raise ValueError("v2 agent envelope requires a nonempty agent run id")
    output = envelope.get("output")
    if not isinstance(output, dict) or output.get("schema_version") != schema_version:
        raise ValueError("v2 agent envelope schema version mismatch")
    return envelope


def _run_input_refs(
    packet: dict[str, Any],
    *,
    role: str,
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
) -> dict[str, Any]:
    if role == "designer":
        refs = {
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "item_handle": packet["item_handle"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "repair_iteration": packet["repair_iteration"],
            "parent_contract_digest_sha256": packet[
                "parent_contract_digest_sha256"
            ],
            "review_issue_digest_sha256": packet[
                "review_issue_digest_sha256"
            ],
            "designer_attempt": packet["designer_attempt"],
            "local_compiler_issue_digest_sha256": packet[
                "local_compiler_issue_digest_sha256"
            ],
        }
    elif role == "reviewer":
        refs = {
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "item_handle": packet["item_handle"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "compiled_contract_digest_sha256": packet[
                "compiled_contract_digest_sha256"
            ],
        }
    else:
        raise ValueError("unsupported v2 agent role")
    if batch_context is not None:
        refs["batch_attempt_id"] = batch_context.batch_attempt_id
    return refs


def _design_retry_packet(
    packet: dict[str, Any], rejection: dict[str, Any], attempt: int
) -> dict[str, Any]:
    issue_code = str(
        rejection.get("local_issue_code") or "other_contract_issue"
    )
    allowed_slot_keys = [
        slot["slot_key"] for slot in packet["skeleton"]["allowed_slot_catalog"]
    ]
    rejected_slot_keys = deepcopy(rejection.get("slot_keys") or [])
    duplicate_slot_keys = sorted(
        {
            key
            for key in rejected_slot_keys
            if rejected_slot_keys.count(key) > 1
        }
    )
    unused_slot_keys = [
        key for key in allowed_slot_keys if key not in rejected_slot_keys
    ]
    correction = {
        "slot_not_allowed": (
            "Use two to four unique slot keys copied exactly from allowed_slot_keys; "
            "replace duplicates or unknown aliases with an unused allowed key, or return fewer items."
        ),
        "derived_grounding_invalid": (
            "Use direct only when claim exactly copies the cited source anchor; "
            "otherwise mark the claim derived and let the independent reviewer verify grounding."
        ),
    }.get(
        issue_code,
        "Correct only the reported criterion or reference-evidence structure.",
    )
    issue = {
        "code": issue_code,
        "detail": str(
            (rejection.get("validation_errors") or ["local compiler rejection"])[0]
        )[:800],
        "required_correction": correction,
        "allowed_slot_keys": allowed_slot_keys,
        "rejected_slot_keys": rejected_slot_keys,
        "duplicate_slot_keys": duplicate_slot_keys,
        "unused_slot_keys": unused_slot_keys,
        "rejected_output_digest_sha256": str(
            rejection.get("output_digest_sha256") or ""
        ),
    }
    updated = deepcopy(packet)
    updated["designer_attempt"] = attempt
    updated["local_compiler_issues"] = [issue]
    updated["local_compiler_issue_digest_sha256"] = _digest([issue])
    updated["item_handle"] = "design-v2-" + _digest(
        {
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "repair_iteration": packet["repair_iteration"],
            "designer_attempt": attempt,
            "local_compiler_issue_digest_sha256": updated[
                "local_compiler_issue_digest_sha256"
            ],
        }
    )[:24]
    updated["skeleton"]["item_handle"] = updated["item_handle"]
    updated["generation_input_digest_sha256"] = _generation_input_digest_for_packet(
        updated
    )
    return updated


def _validate_db_agent_run(
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    envelope: dict[str, Any],
    *,
    role: str,
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
    batch_write_scope: answer_contract_batch_v2.BatchAuthorityWriteScope | None = None,
    expected_persistence_status: str = "accepted",
    expected_validation_errors: list[str] | None = None,
) -> bool:
    if batch_context is not None:
        if batch_write_scope is None:
            raise ValueError("batch agent-run validation requires write scope")
        answer_contract_batch_v2.require_batch_authority_write_scope(
            batch_write_scope,
            conn=conn,
            context=batch_context,
            stage="agent_run_persistence",
        )
        answer_contract_batch_v2._validate_context_on_connection(
            batch_context,
            conn,
            expected_role=role,
            stage="agent_run_persistence",
        )
    elif batch_write_scope is not None:
        raise ValueError("non-batch agent-run validation cannot use batch scope")
    run_id = envelope["agent_run_id"]
    row = conn.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
    if not row:
        raise ValueError("v2 agent run does not exist")
    if role == "designer":
        agent_key = DESIGNER_AGENT_KEY
        phase = DESIGNER_PHASE
        trigger = "answer_contract_generation_v2"
        contract = _contract_versions()[0]
        route = model_router.answer_contract_design_v2_route()
        request = semantic_design_request_v2(
            packet, batch_context=batch_context
        )
    elif role == "reviewer":
        agent_key = REVIEWER_AGENT_KEY
        phase = REVIEWER_PHASE
        trigger = "answer_contract_review_v2"
        contract = _contract_versions()[1]
        route = model_router.answer_contract_review_v2_route()
        request = semantic_review_request_v2(
            packet, batch_context=batch_context
        )
    else:
        raise ValueError("unsupported v2 agent role")
    if expected_persistence_status not in {"accepted", "rejected"}:
        raise ValueError("v2 agent run persistence status is invalid")
    validation_errors = list(expected_validation_errors or [])
    if expected_persistence_status == "accepted" and validation_errors:
        raise ValueError("accepted v2 agent run cannot have validation errors")
    if expected_persistence_status == "rejected" and not validation_errors:
        raise ValueError("rejected v2 agent run requires validation errors")
    core = {
        "agent_key": agent_key,
        "engine_type": "internal_learning_agent",
        "phase": phase,
        "status": expected_persistence_status,
        "model_provider": "openai",
        "model_name": route.model,
        "model_alias": route.model_alias,
    }
    if any(row[field] != value for field, value in core.items()):
        raise ValueError("v2 agent run core lineage is not exact live evidence")
    expected_batch_attempt_id = (
        batch_context.batch_attempt_id if batch_context is not None else None
    )
    if row["batch_attempt_id"] != expected_batch_attempt_id:
        raise ValueError("v2 agent run batch attempt lineage mismatch")
    input_refs = _run_input_refs(
        packet, role=role, batch_context=batch_context
    )
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    exact = {
        "trigger": trigger,
        "prompt_version_id": contract["prompt_version_id"],
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path),
        "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
            request
        ),
        "response_schema_version": contract["response_schema_version"],
        "response_schema_sha256": internal_agents.canonical_json_sha256(
            contract["response_schema"]
        ),
        "input_digest_sha256": _digest(input_refs),
        "output_digest_sha256": _digest(envelope["output"]),
        "error_reason": validation_errors[0] if validation_errors else "",
    }
    has_exact_scalars = all(row[field] == value for field, value in exact.items())
    has_exact_json = (
        db.json_load(row["input_refs_json"], None) == input_refs
        and db.json_load(row["model_params_json"], None) == {"temperature": 0}
        and db.json_load(row["validation_errors_json"], None)
        == validation_errors
        and db.json_load(row["output_json"], None) == envelope["output"]
    )
    if batch_context is not None and expected_persistence_status == "accepted":
        attempt_row = conn.execute(
            "select provider_chain_digest_sha256 from answer_contract_generation_attempts where id = ?",
            (batch_context.batch_attempt_id,),
        ).fetchone()
        if not attempt_row or not attempt_row["provider_chain_digest_sha256"]:
            return bool(has_exact_scalars and has_exact_json)
        try:
            answer_contract_batch_v2.persisted_agent_lineage(
                conn,
                batch_attempt_id=batch_context.batch_attempt_id,
                agent_run_id=run_id,
            )
        except (TypeError, ValueError, sqlite3.Error):
            return False
    return bool(has_exact_scalars and has_exact_json)


def _persist_exact_live_run(
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    request: semantic_agents.SemanticAgentRequest,
    envelope: semantic_agents.SemanticAgentEnvelope,
    *,
    role: str,
    batch_context: answer_contract_batch_v2.BatchAttemptContext | None = None,
) -> dict[str, Any]:
    if batch_context is not None:
        answer_contract_batch_v2._require_issued_context(batch_context)
        expected_request_lineage = {
            "batch_attempt_id": batch_context.batch_attempt_id,
            "effective_evidence_role": (
                batch_context.effective_evidence_role
            ),
            "effective_evidence_role_policy_version": (
                batch_context.effective_evidence_role_policy_version
            ),
        }
        if any(
            request.trusted_context.get(key) != value
            for key, value in expected_request_lineage.items()
        ) or request.source_refs.get("batch_attempt_id") != (
            batch_context.batch_attempt_id
        ):
            raise ValueError("v2 request batch attempt lineage mismatch")
    elif any(
        key in request.trusted_context or key in request.source_refs
        for key in (
            "batch_attempt_id",
            "effective_evidence_role",
            "effective_evidence_role_policy_version",
        )
    ):
        raise ValueError("non-batch v2 request contains batch authority")
    local_validation: Callable[[], Any]
    if role == "designer":
        agent_key = DESIGNER_AGENT_KEY
        phase = DESIGNER_PHASE
        trigger = "answer_contract_generation_v2"
        contract = _contract_versions()[0]
        route = model_router.answer_contract_design_v2_route()
        local_validation = lambda: compile_design_output_v2(  # noqa: E731
            packet, envelope.output
        )
    elif role == "reviewer":
        agent_key = REVIEWER_AGENT_KEY
        phase = REVIEWER_PHASE
        trigger = "answer_contract_review_v2"
        contract = _contract_versions()[1]
        route = model_router.answer_contract_review_v2_route()
        local_validation = lambda: validate_review_output_v2(  # noqa: E731
            packet, envelope.output
        )
    else:
        raise ValueError("unsupported v2 agent role")
    if (
        envelope.agent_key != agent_key
        or envelope.phase != phase
        or envelope.status != "accepted"
        or envelope.provider_mode != "live_model"
    ):
        raise ValueError("v2 semantic agent did not return accepted live lineage")
    route_meta = envelope.route_meta or {}
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    expected_meta = {
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path),
        "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
            request
        ),
        "response_schema_sha256": internal_agents.canonical_json_sha256(
            contract["response_schema"]
        ),
    }
    if any(route_meta.get(key) != value for key, value in expected_meta.items()):
        raise ValueError("v2 semantic agent route metadata mismatch")
    input_refs = _run_input_refs(
        packet, role=role, batch_context=batch_context
    )
    batch_route_digest = ""
    batch_request_digest = ""
    batch_source_refs_digest = ""
    if batch_context is not None:
        batch_attempt = conn.execute(
            "select * from answer_contract_generation_attempts where id = ?",
            (batch_context.batch_attempt_id,),
        ).fetchone()
        if not batch_attempt:
            raise ValueError("v2 batch attempt disappeared before agent persistence")
        batch_route_digest = str(batch_attempt["route_digest_sha256"] or "")
        batch_request_digest = str(batch_attempt["request_digest_sha256"] or "")
        batch_source_refs_digest = _digest(request.source_refs)
    run_id = f"ARV2-{uuid.uuid4().hex[:16]}"
    output_digest = _digest(envelope.output)
    validation_errors = []
    local_issue_code = "other_contract_issue"
    try:
        local_validation()
    except (TypeError, ValueError) as exc:
        validation_errors.append(str(exc)[:800])
        local_issue_code = str(
            getattr(exc, "issue_code", "other_contract_issue")
        )
    run_status = "accepted" if not validation_errors else "rejected"
    result = {
        "agent_key": agent_key,
        "phase": phase,
        "status": "accepted",
        "provider_mode": "live_model",
        "agent_run_id": run_id,
        "transport_endpoint": route_meta.get(
            "structured_json_endpoint", "responses"
        ),
        "structured_json_mode": route_meta.get(
            "structured_json_mode", "json_schema"
        ),
        "output": deepcopy(envelope.output),
    }

    def insert_and_verify(
        batch_write_scope: (
            answer_contract_batch_v2.BatchAuthorityWriteScope | None
        ),
    ) -> None:
        conn.execute(
            """
            insert into agent_runs(
              id, batch_attempt_id, agent_key, engine_type, session_id, phase, trigger,
              input_refs_json, input_digest_sha256, provider_mode,
              route_digest_sha256, semantic_request_digest_sha256,
              request_source_refs_digest_sha256, prompt_version_id,
              prompt_template_sha256, rendered_prompt_sha256, model_provider,
              model_name, model_alias, model_params_json,
              response_schema_version, response_schema_sha256, status,
              confidence, output_json, output_digest_sha256,
              validation_errors_json, error_reason, created_at
            ) values (?, ?, ?, 'internal_learning_agent', null, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, 'openai', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                batch_context.batch_attempt_id if batch_context is not None else None,
                agent_key,
                phase,
                trigger,
                db.json_dump(input_refs),
                _digest(input_refs),
                envelope.provider_mode,
                batch_route_digest,
                batch_request_digest,
                batch_source_refs_digest,
                contract["prompt_version_id"],
                expected_meta["prompt_template_sha256"],
                expected_meta["rendered_prompt_sha256"],
                route.model,
                route.model_alias,
                db.json_dump({"temperature": 0}),
                contract["response_schema_version"],
                expected_meta["response_schema_sha256"],
                run_status,
                float(envelope.confidence),
                db.json_dump(envelope.output),
                output_digest,
                db.json_dump(validation_errors),
                validation_errors[0] if validation_errors else "",
                db.now_iso(),
            ),
        )
        if (
            batch_context is not None
            and run_status == "accepted"
            and answer_contract_batch_v2._has_exact_provider_response_chain(
                conn, batch_context.batch_attempt_id
            )
        ):
            attempt_row = conn.execute(
                "select * from answer_contract_generation_attempts where id = ?",
                (batch_context.batch_attempt_id,),
            ).fetchone()
            agent_row = conn.execute(
                "select * from agent_runs where id = ?",
                (run_id,),
            ).fetchone()
            if not attempt_row or not agent_row:
                raise ValueError("v2 complete agent lineage rows are missing")
            answer_contract_batch_v2._persist_agent_provider_commitment(
                conn,
                dict(attempt_row),
                dict(agent_row),
            )
        if not _validate_db_agent_run(
            conn,
            packet,
            result,
            role=role,
            batch_context=batch_context,
            batch_write_scope=batch_write_scope,
            expected_persistence_status=run_status,
            expected_validation_errors=validation_errors,
        ):
            raise ValueError("persisted v2 agent run did not round-trip exact lineage")

    if batch_context is not None:
        with answer_contract_batch_v2.batch_authority_write_scope(
            conn,
            contexts=((role, batch_context),),
            stage="agent_run_persistence",
        ) as authority_scope:
            insert_and_verify(authority_scope)
    else:
        with conn:
            insert_and_verify(None)
    if validation_errors:
        items = envelope.output.get("items")
        slot_keys = [
            item.get("slot_key")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("slot_key"), str)
        ] if isinstance(items, list) else []
        raise LocalSemanticRejection(
            validation_errors[0],
            {
                "failure_kind": "semantic_compiler_rejection",
                "transport_pass": True,
                "semantic_response_valid": True,
                "compiler_valid": False,
                "agent_run_id": run_id,
                "output_digest_sha256": output_digest,
                "semantic_output": deepcopy(envelope.output),
                "slot_keys": slot_keys,
                "validation_errors": deepcopy(validation_errors),
                "local_issue_code": local_issue_code,
            },
        )
    return result


def make_live_designer_v2(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    route = model_router.answer_contract_design_v2_route()
    if not route.enabled:
        raise ValueError("model_not_configured")

    def designer(packet: dict[str, Any]) -> dict[str, Any]:
        batch_context = packet.get("_batch_attempt_context")
        if batch_context is not None:
            answer_contract_batch_v2._require_issued_context(batch_context)
        request = replace(
            semantic_design_request_v2(packet, batch_context=batch_context),
            transport_timeout_seconds=float(
                getattr(
                    designer,
                    "current_transport_timeout_seconds",
                    route.timeout_seconds,
                )
            ),
        )
        envelope = semantic_agents.call_answer_contract_designer_agent(request)
        return _persist_exact_live_run(
            conn,
            packet,
            request,
            envelope,
            role="designer",
            batch_context=batch_context,
        )

    designer.production_live_adapter = True  # type: ignore[attr-defined]
    designer.transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    designer.current_transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    designer.transport_endpoint = "responses"  # type: ignore[attr-defined]
    designer.structured_json_mode = "json_schema"  # type: ignore[attr-defined]
    return designer


def make_live_reviewer_v2(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    route = model_router.answer_contract_review_v2_route()
    if not route.enabled:
        raise ValueError("model_not_configured")

    def reviewer(packet: dict[str, Any]) -> dict[str, Any]:
        batch_context = packet.get("_batch_attempt_context")
        if batch_context is not None:
            answer_contract_batch_v2._require_issued_context(batch_context)
        request = replace(
            semantic_review_request_v2(packet, batch_context=batch_context),
            transport_timeout_seconds=float(
                getattr(
                    reviewer,
                    "current_transport_timeout_seconds",
                    route.timeout_seconds,
                )
            ),
        )
        envelope = semantic_agents.call_answer_contract_reviewer_agent(request)
        return _persist_exact_live_run(
            conn,
            packet,
            request,
            envelope,
            role="reviewer",
            batch_context=batch_context,
        )

    reviewer.production_live_adapter = True  # type: ignore[attr-defined]
    reviewer.transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    reviewer.current_transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    reviewer.transport_endpoint = "responses"  # type: ignore[attr-defined]
    reviewer.structured_json_mode = "json_schema"  # type: ignore[attr-defined]
    return reviewer


def _retryable(exc: Exception) -> bool:
    return bool(
        getattr(exc, "retryable", False)
        or getattr(exc, "status_code", None) in {429, 500, 502, 503, 504}
        or model_router.is_retryable_model_call_error(exc)
    )


def _retry_delay(exc: Exception, attempt_index: int) -> float:
    base = BACKOFF_SECONDS[min(attempt_index, len(BACKOFF_SECONDS) - 1)]
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
        return max(base, min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(retry_after))))
    return base


def _call_live_with_retry(
    callback: Callable[[dict[str, Any]], dict[str, Any]],
    packet: dict[str, Any],
    *,
    role: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int, dict[str, Any]]:
    if not getattr(callback, "production_live_adapter", False):
        return callback(deepcopy(packet)), [], 1, packet
    started = time.monotonic()
    attempts = []
    working_packet = deepcopy(packet)
    seen_compiler_rejections = set()
    for attempt_index in range(MAX_ATTEMPTS):
        remaining = ITEM_WALL_SECONDS - max(0.0, time.monotonic() - started)
        if remaining <= 0:
            break
        if hasattr(callback, "current_transport_timeout_seconds"):
            callback.current_transport_timeout_seconds = max(  # type: ignore[attr-defined]
                0.01,
                min(
                    float(getattr(callback, "transport_timeout_seconds", remaining)),
                    remaining,
                ),
            )
        call_started = time.monotonic()
        try:
            envelope = callback(deepcopy(working_packet))
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "outcome": "accepted",
                    "duration_seconds": round(
                        max(0.0, time.monotonic() - call_started), 6
                    ),
                    "transport_endpoint": envelope.get(
                        "transport_endpoint", "responses"
                    ),
                    "structured_json_mode": envelope.get(
                        "structured_json_mode", "json_schema"
                    ),
                }
            )
            return envelope, attempts, len(attempts), working_packet
        except LocalSemanticRejection as exc:
            error_report = deepcopy(exc.report)
            rejection_key = _digest(
                {
                    "local_issue_code": error_report.get("local_issue_code"),
                    "validation_errors": error_report.get("validation_errors"),
                    "slot_keys": error_report.get("slot_keys"),
                }
            )
            repeated = rejection_key in seen_compiler_rejections
            seen_compiler_rejections.add(rejection_key)
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "outcome": "semantic_compiler_rejection",
                    "duration_seconds": round(
                        max(0.0, time.monotonic() - call_started), 6
                    ),
                    "retryable": not repeated
                    and role == "designer"
                    and attempt_index + 1 < MAX_ATTEMPTS,
                    "transport_endpoint": getattr(
                        callback, "transport_endpoint", "responses"
                    ),
                    "structured_json_mode": getattr(
                        callback, "structured_json_mode", "json_schema"
                    ),
                    **error_report,
                }
            )
            if (
                role != "designer"
                or repeated
                or attempt_index + 1 >= MAX_ATTEMPTS
            ):
                failure_kind = (
                    "repeated_semantic_compiler_rejection"
                    if repeated
                    else "semantic_compiler_repair_exhausted"
                )
                raise ContractRepairError(
                    str(exc),
                    {
                        "status": "terminal_failure",
                        "role": role,
                        "attempt_count": len(attempts),
                        "model_calls": len(attempts),
                        "attempts": deepcopy(attempts),
                        "activation_eligible": False,
                        **error_report,
                        "failure_kind": failure_kind,
                    },
                ) from exc
            working_packet = _design_retry_packet(
                working_packet, error_report, attempt_index + 1
            )
            continue
        except (
            answer_contract_batch_v2.BatchAStopRequested,
            answer_contract_batch_v2.BatchACommitUncertain,
        ):
            raise
        except Exception as exc:
            retryable = _retryable(exc)
            error_report = (
                deepcopy(exc.report)
                if isinstance(getattr(exc, "report", None), dict)
                else {}
            )
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "outcome": (
                        "retryable_failure" if retryable else "terminal_failure"
                    ),
                    "duration_seconds": round(
                        max(0.0, time.monotonic() - call_started), 6
                    ),
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:800],
                    "status_code": getattr(exc, "status_code", None),
                    "retry_after_seconds": getattr(
                        exc, "retry_after_seconds", None
                    ),
                    "transport_endpoint": getattr(
                        exc,
                        "endpoint",
                        getattr(callback, "transport_endpoint", "responses"),
                    ),
                    "structured_json_mode": getattr(
                        exc,
                        "structured_json_mode",
                        getattr(callback, "structured_json_mode", "json_schema"),
                    ),
                    **error_report,
                }
            )
            if not retryable or attempt_index + 1 >= MAX_ATTEMPTS:
                raise ContractRepairError(
                    str(exc),
                    {
                        "status": "terminal_failure",
                        "role": role,
                        "attempt_count": len(attempts),
                        "model_calls": len(attempts),
                        "attempts": deepcopy(attempts),
                        "activation_eligible": False,
                        **error_report,
                    },
                ) from exc
            delay = _retry_delay(exc, attempt_index)
            remaining_after = ITEM_WALL_SECONDS - max(
                0.0, time.monotonic() - started
            )
            if remaining_after <= delay:
                raise ContractRepairError(
                    "v2 agent item wall deadline exhausted",
                    {
                        "status": "terminal_failure",
                        "role": role,
                        "attempt_count": len(attempts),
                        "model_calls": len(attempts),
                        "attempts": deepcopy(attempts),
                        "activation_eligible": False,
                    },
                ) from exc
            attempts[-1]["sleep_seconds"] = delay
            time.sleep(delay)
    raise ContractRepairError(
        "v2 agent item wall deadline exhausted",
        {
            "status": "terminal_failure",
            "role": role,
            "attempt_count": len(attempts),
            "model_calls": len(attempts),
            "attempts": deepcopy(attempts),
            "activation_eligible": False,
        },
    )


def _validate_checkpoint(
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    checkpoint: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    if not _valid_receipt(checkpoint):
        raise ValueError("v2 checkpoint receipt digest is invalid")
    expected = {
        "sealed": True,
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "repair_iteration": packet["repair_iteration"],
        "parent_contract_id": packet["parent_contract_id"],
        "parent_contract_version": packet["parent_contract_version"],
        "design_item_handle": packet["item_handle"],
        "designer_attempt": packet["designer_attempt"],
        "local_compiler_issue_digest_sha256": packet[
            "local_compiler_issue_digest_sha256"
        ],
        "local_compiler_issues": packet["local_compiler_issues"],
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("v2 checkpoint packet lineage mismatch")
    compiled = checkpoint.get("compiled_contract")
    if not isinstance(compiled, dict):
        raise ValueError("v2 checkpoint compiled contract is missing")
    contract_digest = _digest(compiled)
    if checkpoint.get("contract_digest_sha256") != contract_digest:
        raise ValueError("v2 checkpoint contract digest mismatch")
    review_packet = build_review_packet_v2(packet, compiled)
    review_result = checkpoint.get("review_result")
    validate_review_output_v2(
        review_packet,
        {
            "schema_version": checkpoint.get("review_schema_version"),
            "items": [review_result],
        },
    )
    classification = _classification_for_packet(
        packet,
        review_result,
        compiled_contract=compiled,
        reviewer_run_id=str(
            (checkpoint.get("review_receipt") or {}).get("agent_run_id") or ""
        ),
    )
    if (
        checkpoint.get("classification") != classification
        or checkpoint.get("status") != classification["status"]
    ):
        raise ValueError("v2 checkpoint derived classification was tampered")
    design_receipt = checkpoint.get("design_receipt")
    review_receipt = checkpoint.get("review_receipt")
    if not _valid_receipt(design_receipt) or not _valid_receipt(review_receipt):
        raise ValueError("v2 checkpoint agent receipt digest is invalid")
    for receipt in (design_receipt, review_receipt):
        batch_attempt_id = receipt.get("batch_attempt_id")
        if batch_attempt_id:
            lineage = answer_contract_batch_v2.persisted_agent_lineage(
                conn,
                batch_attempt_id=batch_attempt_id,
                agent_run_id=receipt.get("agent_run_id"),
            )
            chain = lineage["provider_chain"]
            if (
                receipt.get("agent_lineage") != lineage
                or receipt.get("agent_lineage_digest_sha256")
                != lineage["agent_lineage_digest_sha256"]
                or receipt.get("provider_chain") != chain
                or receipt.get("provider_chain_digest_sha256")
                != chain["provider_chain_digest_sha256"]
            ):
                raise ValueError("v2 checkpoint provider chain was tampered")
    if (
        design_receipt.get("generation_input_digest_sha256")
        != packet["generation_input_digest_sha256"]
        or design_receipt.get("item_handle") != packet["item_handle"]
        or design_receipt.get("designer_attempt") != packet["designer_attempt"]
        or design_receipt.get("local_compiler_issue_digest_sha256")
        != packet["local_compiler_issue_digest_sha256"]
        or design_receipt.get("local_compiler_issues")
        != packet["local_compiler_issues"]
        or review_receipt.get("contract_digest_sha256") != contract_digest
        or review_receipt.get("issue_digest_sha256")
        != _digest(review_result["issues"])
        or review_receipt.get("classification") != classification
    ):
        raise ValueError("v2 checkpoint agent receipt lineage mismatch")
    design_run = conn.execute(
        "select * from agent_runs where id = ?",
        (design_receipt.get("agent_run_id"),),
    ).fetchone()
    review_run = conn.execute(
        "select * from agent_runs where id = ?",
        (review_receipt.get("agent_run_id"),),
    ).fetchone()
    if not design_run or not review_run:
        raise ValueError("v2 checkpoint references a missing agent run")
    design_output = db.json_load(design_run["output_json"], None)
    review_output = db.json_load(review_run["output_json"], None)
    design_exact = _validate_db_agent_run(
        conn,
        packet,
        {
            "agent_run_id": design_receipt["agent_run_id"],
            "output": design_output,
        },
        role="designer",
    )
    review_exact = _validate_db_agent_run(
        conn,
        review_packet,
        {
            "agent_run_id": review_receipt["agent_run_id"],
            "output": review_output,
        },
        role="reviewer",
    )
    activation_eligible = bool(
        classification["approved"] and design_exact and review_exact
    )
    if (
        design_receipt.get("exact_live_lineage") is not design_exact
        or review_receipt.get("exact_live_lineage") is not review_exact
        or checkpoint.get("activation_eligible") is not activation_eligible
    ):
        raise ValueError("v2 checkpoint live lineage derivation was tampered")
    report = checkpoint.get("version_report")
    if not isinstance(report, dict) or (
        report.get("contract_digest_sha256") != contract_digest
        or report.get("repair_iteration") != packet["repair_iteration"]
        or report.get("review_result") != review_result
        or report.get("classification") != classification
        or report.get("design_run_id") != design_receipt.get("agent_run_id")
        or report.get("review_run_id") != review_receipt.get("agent_run_id")
        or report.get("activation_eligible") is not activation_eligible
    ):
        raise ValueError("v2 checkpoint version report was tampered")
    row = conn.execute(
        "select * from answer_contracts where id = ?",
        (checkpoint.get("contract_id"),),
    ).fetchone()
    if row:
        expected_status = "approved" if classification["approved"] else "rejected"
        if (
            row["question_id"] != packet["question_id"]
            or row["item_version"] != packet["item_version"]
            or row["contract_digest_sha256"] != contract_digest
            or row["generation_input_digest_sha256"]
            != packet["generation_input_digest_sha256"]
            or row["status"] != expected_status
            or row["generator_run_id"] != design_receipt.get("agent_run_id")
            or row["review_run_id"] != review_receipt.get("agent_run_id")
        ):
            raise ValueError("v2 checkpoint database lineage mismatch")
        return dict(row), deepcopy(report), classification
    return None, deepcopy(report), classification


def _failure_checkpoint_path(path: Path, role: str) -> Path:
    return path.with_name(f"{path.stem}.{_safe_component(role, 'role')}.failure.json")


def _failure_receipt(
    packet: dict[str, Any], role: str, report: dict[str, Any]
) -> dict[str, Any]:
    return _receipt(
        {
            "sealed": True,
            "status": "terminal_failure",
            "role": role,
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "repair_iteration": packet["repair_iteration"],
            "attempt_count": int(report.get("attempt_count") or 0),
            "model_calls": int(report.get("model_calls") or 0),
            "attempts": deepcopy(report.get("attempts") or []),
            "failure_kind": str(
                report.get("failure_kind") or "transport_failure"
            ),
            "transport_pass": bool(report.get("transport_pass", False)),
            "semantic_response_valid": bool(
                report.get("semantic_response_valid", False)
            ),
            "compiler_valid": report.get("compiler_valid"),
            "agent_run_id": report.get("agent_run_id"),
            "output_digest_sha256": report.get("output_digest_sha256"),
            "semantic_output": deepcopy(report.get("semantic_output")),
            "slot_keys": deepcopy(report.get("slot_keys") or []),
            "validation_errors": deepcopy(
                report.get("validation_errors") or []
            ),
            "local_issue_code": report.get("local_issue_code"),
            "activation_eligible": False,
        }
    )


def _load_failure_receipt(
    path: Path, packet: dict[str, Any], role: str
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "sealed": True,
        "status": "terminal_failure",
        "role": role,
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "repair_iteration": packet["repair_iteration"],
        "activation_eligible": False,
    }
    if not _valid_receipt(receipt) or any(
        receipt.get(key) != value for key, value in expected.items()
    ):
        return None
    if (
        receipt.get("attempt_count") != len(receipt.get("attempts") or [])
        or receipt.get("model_calls") != receipt.get("attempt_count")
    ):
        return None
    return receipt


def run_contract_repair_loop(
    conn: sqlite3.Connection,
    *,
    question: dict[str, Any],
    graph_version: str,
    bank_version: str,
    review_record_id: str,
    designer: Callable[[dict[str, Any]], dict[str, Any]],
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
) -> dict[str, Any]:
    if not callable(designer) or not callable(reviewer):
        raise TypeError("v2 designer and reviewer must be callable")
    design_contract, review_contract = _contract_versions()
    parent: dict[str, Any] | None = None
    advisory_issues: list[dict[str, Any]] = []
    seen_contract_digests = set()
    seen_issue_digests = set()
    used_run_ids = set()
    version_reports = []
    total_model_calls = 0
    for repair_iteration in range(MAX_CONTRACT_VERSIONS):
        packet = build_design_packet_v2(
            question=question,
            graph_version=graph_version,
            bank_version=bank_version,
            review_record_id=review_record_id,
            repair_iteration=repair_iteration,
            parent_contract=parent,
            reviewer_issues=advisory_issues,
        )
        path = _checkpoint_path(checkpoint_root, packet)
        for role in ("designer", "reviewer"):
            failure = _load_failure_receipt(
                _failure_checkpoint_path(path, role), packet, role
            )
            if failure is not None:
                return {
                    "status": "terminal_failure",
                    "role": role,
                    "versions": version_reports,
                    "attempt_count": failure["attempt_count"],
                    "model_calls": 0,
                    "prior_model_calls": failure["model_calls"],
                    "attempts": deepcopy(failure["attempts"]),
                    "failure_kind": failure.get("failure_kind"),
                    "transport_pass": failure.get("transport_pass", False),
                    "semantic_response_valid": failure.get(
                        "semantic_response_valid", False
                    ),
                    "compiler_valid": failure.get("compiler_valid"),
                    "agent_run_id": failure.get("agent_run_id"),
                    "output_digest_sha256": failure.get(
                        "output_digest_sha256"
                    ),
                    "semantic_output": deepcopy(
                        failure.get("semantic_output")
                    ),
                    "slot_keys": deepcopy(failure.get("slot_keys") or []),
                    "validation_errors": deepcopy(
                        failure.get("validation_errors") or []
                    ),
                    "local_issue_code": failure.get("local_issue_code"),
                    "resumed_terminal_failure": True,
                    "activation_eligible": False,
                }
        if path.is_file():
            try:
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                if int(checkpoint.get("designer_attempt") or 0) > 0:
                    packet = deepcopy(packet)
                    packet["designer_attempt"] = int(
                        checkpoint["designer_attempt"]
                    )
                    packet["local_compiler_issues"] = deepcopy(
                        checkpoint.get("local_compiler_issues") or []
                    )
                    packet["local_compiler_issue_digest_sha256"] = str(
                        checkpoint.get(
                            "local_compiler_issue_digest_sha256"
                        )
                        or ""
                    )
                    packet["item_handle"] = str(
                        checkpoint.get("design_item_handle") or ""
                    )
                    packet["skeleton"]["item_handle"] = packet[
                        "item_handle"
                    ]
                    packet[
                        "generation_input_digest_sha256"
                    ] = _generation_input_digest_for_packet(packet)
                row, report, classification = _validate_checkpoint(
                    conn, packet, checkpoint
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "status": "checkpoint_lineage_invalid",
                    "reason_code": str(exc),
                    "versions": version_reports,
                    "activation_eligible": False,
                    "model_calls": 0,
                }
            report["reused_checkpoint"] = True
            version_reports.append(report)
            used_run_ids.update(
                {report["design_run_id"], report["review_run_id"]}
            )
            if classification["approved"]:
                return {
                    "status": "approved",
                    "versions": version_reports,
                    "final_contract_id": row["id"] if row else None,
                    "model_calls": total_model_calls,
                }
            if classification["status"] == "question_bank_repair_required":
                return {
                    "status": classification["status"],
                    "versions": version_reports,
                    "repair_route": classification["repair_route"],
                    "model_calls": total_model_calls,
                }
            if classification["status"] == "assessment_policy_repair_required":
                return {
                    "status": classification["status"],
                    "versions": version_reports,
                    "repair_route": classification["repair_route"],
                    "model_calls": total_model_calls,
                }
            parent = (
                row
                if row is not None
                else {
                    "id": report["contract_id"],
                    "contract_version": report["contract_version"],
                    "contract_digest_sha256": report[
                        "contract_digest_sha256"
                    ],
                }
            )
            advisory_issues = deepcopy(report["review_result"]["issues"])
            continue

        try:
            (
                design_value,
                design_attempts,
                design_calls,
                packet,
            ) = _call_live_with_retry(
                designer, packet, role="designer"
            )
        except ContractRepairError as exc:
            failure_path = _failure_checkpoint_path(path, "designer")
            _atomic_write(failure_path, _failure_receipt(packet, "designer", exc.report))
            exc.report["failure_checkpoint_path"] = str(failure_path)
            raise
        total_model_calls += design_calls
        design_envelope = _validate_live_envelope(
            design_value,
            agent_key=DESIGNER_AGENT_KEY,
            phase=DESIGNER_PHASE,
            schema_version=design_contract["response_schema_version"],
        )
        if design_envelope["agent_run_id"] in used_run_ids:
            raise ValueError("v2 designer run was reused across contract versions")
        design_batch_context = design_envelope.get("_batch_attempt_context")
        if design_batch_context is not None:
            design_exact_live = (
                answer_contract_batch_v2.validate_completed_batch_agent_result(
                    conn,
                    design_batch_context,
                    agent_run_id=design_envelope["agent_run_id"],
                    role="designer",
                )
            )
        else:
            design_exact_live = _validate_db_agent_run(
                conn, packet, design_envelope, role="designer"
            )
        compiled = compile_design_output_v2(packet, design_envelope["output"])
        contract_digest = _digest(compiled)
        if contract_digest in seen_contract_digests:
            return {
                "status": "contract_repair_exhausted",
                "reason_code": "repeated_contract_digest",
                "versions": version_reports,
                "model_calls": total_model_calls,
            }
        seen_contract_digests.add(contract_digest)
        review_packet = build_review_packet_v2(packet, compiled)
        try:
            (
                review_value,
                review_attempts,
                review_calls,
                _review_attempt_packet,
            ) = _call_live_with_retry(
                reviewer, review_packet, role="reviewer"
            )
        except ContractRepairError as exc:
            failure_path = _failure_checkpoint_path(path, "reviewer")
            _atomic_write(failure_path, _failure_receipt(packet, "reviewer", exc.report))
            exc.report["failure_checkpoint_path"] = str(failure_path)
            exc.report["model_calls"] = total_model_calls + int(
                exc.report.get("model_calls") or 0
            )
            raise
        total_model_calls += review_calls
        review_envelope = _validate_live_envelope(
            review_value,
            agent_key=REVIEWER_AGENT_KEY,
            phase=REVIEWER_PHASE,
            schema_version=review_contract["response_schema_version"],
        )
        if review_envelope["agent_run_id"] in used_run_ids:
            raise ValueError("v2 reviewer run was reused across contract versions")
        review_batch_context = review_envelope.get("_batch_attempt_context")
        if review_batch_context is not None:
            review_exact_live = (
                answer_contract_batch_v2.validate_completed_batch_agent_result(
                    conn,
                    review_batch_context,
                    agent_run_id=review_envelope["agent_run_id"],
                    role="reviewer",
                )
            )
        else:
            review_exact_live = _validate_db_agent_run(
                conn, review_packet, review_envelope, role="reviewer"
            )
        if (design_batch_context is None) != (review_batch_context is None):
            raise ValueError("v2 contract batch lineage requires both semantic contexts")
        if review_envelope["agent_run_id"] == design_envelope["agent_run_id"]:
            raise ValueError("v2 designer and reviewer runs must be independent")
        used_run_ids.update(
            {design_envelope["agent_run_id"], review_envelope["agent_run_id"]}
        )
        review_result = validate_review_output_v2(
            review_packet, review_envelope["output"]
        )
        classification = _classification_for_packet(
            packet,
            review_result,
            compiled_contract=compiled,
            reviewer_run_id=review_envelope["agent_run_id"],
        )
        if classification["approved"] and not (
            design_exact_live and review_exact_live
        ):
            raise ValueError(
                "v2 approval requires exact DB-backed designer and reviewer lineage"
            )
        issue_digest = _digest(review_result["issues"])
        repeated_issues = bool(review_result["issues"]) and issue_digest in seen_issue_digests
        seen_issue_digests.add(issue_digest)
        if repeated_issues and classification["status"] != "contract_repair_exhausted":
            classification = {
                **classification,
                "status": "contract_repair_exhausted",
                "approved": False,
                "repairable_contract": False,
                "repair_route": None,
            }
        design_receipt = _receipt(
            {
                "agent_key": DESIGNER_AGENT_KEY,
                "phase": DESIGNER_PHASE,
                "agent_run_id": design_envelope["agent_run_id"],
                "schema_version": design_contract["response_schema_version"],
                "generation_input_digest_sha256": packet[
                    "generation_input_digest_sha256"
                ],
                "item_handle": packet["item_handle"],
                "designer_attempt": packet["designer_attempt"],
                "local_compiler_issue_digest_sha256": packet[
                    "local_compiler_issue_digest_sha256"
                ],
                "local_compiler_issues": deepcopy(
                    packet["local_compiler_issues"]
                ),
                "output_digest_sha256": _digest(design_envelope["output"]),
                "exact_live_lineage": design_exact_live,
                **(
                    {
                        "batch_attempt_id": (
                            design_batch_context.batch_attempt_id
                        ),
                        "agent_lineage": deepcopy(
                            design_envelope["agent_lineage"]
                        ),
                        "agent_lineage_digest_sha256": design_envelope[
                            "agent_lineage_digest_sha256"
                        ],
                        "provider_chain": deepcopy(
                            design_envelope["provider_chain"]
                        ),
                        "provider_chain_digest_sha256": design_envelope[
                            "provider_chain_digest_sha256"
                        ],
                    }
                    if design_batch_context is not None
                    else {}
                ),
            }
        )
        review_receipt = _receipt(
            {
                "agent_key": REVIEWER_AGENT_KEY,
                "phase": REVIEWER_PHASE,
                "agent_run_id": review_envelope["agent_run_id"],
                "schema_version": review_contract["response_schema_version"],
                "contract_digest_sha256": contract_digest,
                "issue_digest_sha256": issue_digest,
                "output_digest_sha256": _digest(review_envelope["output"]),
                "classification": classification,
                "exact_live_lineage": review_exact_live,
                **(
                    {
                        "batch_attempt_id": (
                            review_batch_context.batch_attempt_id
                        ),
                        "agent_lineage": deepcopy(
                            review_envelope["agent_lineage"]
                        ),
                        "agent_lineage_digest_sha256": review_envelope[
                            "agent_lineage_digest_sha256"
                        ],
                        "provider_chain": deepcopy(
                            review_envelope["provider_chain"]
                        ),
                        "provider_chain_digest_sha256": review_envelope[
                            "provider_chain_digest_sha256"
                        ],
                    }
                    if review_batch_context is not None
                    else {}
                ),
            }
        )
        checkpoint_body = {
            "sealed": True,
            "status": classification["status"],
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "repair_iteration": repair_iteration,
            "parent_contract_id": packet["parent_contract_id"],
            "parent_contract_version": packet["parent_contract_version"],
            "design_item_handle": packet["item_handle"],
            "designer_attempt": packet["designer_attempt"],
            "local_compiler_issue_digest_sha256": packet[
                "local_compiler_issue_digest_sha256"
            ],
            "local_compiler_issues": deepcopy(
                packet["local_compiler_issues"]
            ),
            "contract_digest_sha256": contract_digest,
            "design_schema_version": design_contract["response_schema_version"],
            "review_schema_version": review_contract["response_schema_version"],
            "design_receipt": design_receipt,
            "review_receipt": review_receipt,
            "compiled_contract": compiled,
            "review_result": review_result,
            "classification": classification,
            "activation_eligible": classification["approved"]
            and design_exact_live
            and review_exact_live,
            "design_attempts": deepcopy(design_attempts),
            "review_attempts": deepcopy(review_attempts),
            "model_calls": design_calls + review_calls,
        }
        provisional = _receipt(checkpoint_body)
        reused_existing = False
        if design_exact_live and review_exact_live:
            persisted = _persist_contract_version(
                conn,
                packet,
                compiled,
                design_envelope,
                review_envelope,
                review_result,
                classification,
                provisional,
                design_batch_context=design_batch_context,
                review_batch_context=review_batch_context,
            )
            row = persisted["row"]
            reused_existing = bool(persisted["reused_existing"])
            if reused_existing:
                classification = deepcopy(persisted["classification"])
                review_result = deepcopy(persisted["review_result"])
                checkpoint_body = deepcopy(persisted["checkpoint_body"])
                version_report = deepcopy(persisted["version_report"])
                used_run_ids.update(
                    {
                        version_report["design_run_id"],
                        version_report["review_run_id"],
                    }
                )
        else:
            row = {
                "id": "UNPERSISTED-V2-" + packet["generation_input_digest_sha256"][:16],
                "contract_version": repair_iteration + 1,
                "contract_digest_sha256": contract_digest,
            }
        if not reused_existing:
            version_report = {
                "contract_id": row["id"],
                "contract_version": int(row["contract_version"]),
                "contract_digest_sha256": contract_digest,
                "repair_iteration": repair_iteration,
                "design_run_id": design_envelope["agent_run_id"],
                "review_run_id": review_envelope["agent_run_id"],
                "review_result": review_result,
                "classification": classification,
                "activation_eligible": classification["approved"]
                and design_exact_live
                and review_exact_live,
                "reused_checkpoint": False,
                "reused_persisted_row": False,
            }
        checkpoint = _receipt(
            {
                **checkpoint_body,
                "contract_id": row["id"],
                "contract_version": int(row["contract_version"]),
                "version_report": version_report,
            }
        )
        _atomic_write(path, checkpoint)
        version_reports.append(version_report)
        if classification["approved"]:
            return {
                "status": "approved",
                "versions": version_reports,
                "final_contract_id": row["id"],
                "model_calls": total_model_calls,
            }
        if classification["status"] == "question_bank_repair_required":
            return {
                "status": classification["status"],
                "versions": version_reports,
                "repair_route": classification["repair_route"],
                "model_calls": total_model_calls,
            }
        if classification["status"] == "assessment_policy_repair_required":
            return {
                "status": classification["status"],
                "versions": version_reports,
                "repair_route": classification["repair_route"],
                "model_calls": total_model_calls,
            }
        if classification["status"] == "contract_repair_exhausted":
            return {
                "status": "contract_repair_exhausted",
                "reason_code": "repeated_review_issues",
                "versions": version_reports,
                "model_calls": total_model_calls,
            }
        parent = row
        advisory_issues = deepcopy(review_result["issues"])
    return {
        "status": "contract_repair_exhausted",
        "reason_code": "third_contract_rejection",
        "versions": version_reports,
        "model_calls": total_model_calls,
    }


def plan_canary_questions(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    canary_size: int = CANARY_SIZE,
) -> dict[str, Any]:
    del project_root
    if canary_size != CANARY_SIZE:
        raise ValueError("the v2 canary size is fixed at forty questions")
    ledger = answer_contract_activation._active_ledger(conn)
    bank_version = str(ledger["question_bank_version"])
    questions = answer_contract_activation._authoritative_questions(
        conn, bank_version
    )
    by_kind: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for question, review_record_id in questions:
        by_kind.setdefault(question["kind"], []).append(
            (question, review_record_id)
        )
    if set(by_kind) != set(assessment_policy.ACTIVE_QUESTION_KINDS):
        raise ValueError("v2 canary requires all twenty active question kinds")
    selected = []
    for kind in sorted(by_kind):
        candidates = sorted(
            by_kind[kind], key=lambda value: (value[0]["node_id"], value[0]["id"])
        )
        if len(candidates) < 2:
            raise ValueError(f"v2 canary kind has fewer than two questions: {kind}")
        for question, review_record_id in candidates[:2]:
            selected.append(
                {
                    "question_id": question["id"],
                    "item_version": question["item_version"],
                    "node_id": question["node_id"],
                    "kind": kind,
                    "review_record_id": review_record_id,
                    "question_digest_sha256": _question_digest(question),
                }
            )
    plan = {
        "bank_version": bank_version,
        "canary_size": CANARY_SIZE,
        "questions_per_kind": 2,
        "items": selected,
    }
    plan["plan_digest_sha256"] = _digest(plan)
    return plan


def build_canary_report(
    plan: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("plan_digest_sha256") != _digest(
        {key: value for key, value in plan.items() if key != "plan_digest_sha256"}
    ):
        raise ValueError("v2 canary plan digest is invalid")
    if not isinstance(results, list):
        raise TypeError("v2 canary results must be a list")
    expected = {item["question_id"] for item in plan["items"]}
    found = set()
    status_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for result in results:
        if not isinstance(result, dict):
            raise TypeError("v2 canary result must be a mapping")
        question_id = result.get("question_id")
        if question_id not in expected or question_id in found:
            raise ValueError("v2 canary result identity mismatch")
        found.add(question_id)
        status = str(result.get("status") or "missing")
        if status == "approved":
            status = "unverified_approved"
        status_counts[status] = status_counts.get(status, 0) + 1
        for code in result.get("issue_codes") or []:
            issue_counts[str(code)] = issue_counts.get(str(code), 0) + 1
    missing = sorted(expected.difference(found))
    return {
        "bank_version": plan["bank_version"],
        "planned": len(expected),
        "reported": len(found),
        "missing_question_ids": missing,
        "status_counts": dict(sorted(status_counts.items())),
        "issue_code_counts": dict(sorted(issue_counts.items())),
        "activation_eligible": False,
        "canary_complete": not missing,
        "canary_pass": False,
        "canary_pass_authority": "none",
        "authoritative_readiness_required": True,
    }


def contract_row_is_v2_activation_eligible(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
) -> bool:
    values = dict(row)
    if v2_scoring_policy_activation_blockers(values):
        return False
    design_contract, review_contract = _contract_versions()
    structural = (
        values.get("status") == "approved"
        and values.get("generator_version") == GENERATOR_VERSION
        and values.get("design_contract_schema_version")
        == design_contract["response_schema_version"]
        and values.get("review_contract_schema_version")
        == review_contract["response_schema_version"]
        and bool(values.get("generator_run_id"))
        and bool(values.get("review_run_id"))
        and bool(values.get("design_receipt_sha256"))
        and bool(values.get("review_receipt_sha256"))
    )
    if not structural:
        return False
    try:
        question_row = conn.execute(
            "select * from question_items where id = ? and item_version = ?",
            (values["question_id"], values["item_version"]),
        ).fetchone()
        if not question_row:
            return False
        question = db.row_to_question(question_row)
        parent = None
        reviewer_issues = []
        if int(values.get("repair_iteration") or 0) > 0:
            parent_row = conn.execute(
                "select * from answer_contracts where id = ?",
                (values.get("parent_contract_id"),),
            ).fetchone()
            if not parent_row:
                return False
            parent = dict(parent_row)
            parent_review_run = conn.execute(
                "select output_json from agent_runs where id = ?",
                (parent["review_run_id"],),
            ).fetchone()
            if not parent_review_run:
                return False
            parent_output = db.json_load(parent_review_run["output_json"], {})
            parent_items = parent_output.get("items")
            if not isinstance(parent_items, list) or len(parent_items) != 1:
                return False
            reviewer_issues = deepcopy(parent_items[0].get("issues") or [])
        packet = build_design_packet_v2(
            question=question,
            graph_version=str(values.get("graph_version") or ""),
            bank_version=str(values.get("question_bank_version") or ""),
            review_record_id=str(values.get("review_record_id") or ""),
            repair_iteration=int(values.get("repair_iteration") or 0),
            parent_contract=parent,
            reviewer_issues=reviewer_issues,
        )
        design_receipt = db.json_load(values.get("design_receipt_json"), {})
        review_receipt = db.json_load(values.get("review_receipt_json"), {})
        if not _valid_receipt(design_receipt) or not _valid_receipt(review_receipt):
            return False
        if int(design_receipt.get("designer_attempt") or 0) > 0:
            packet["designer_attempt"] = int(design_receipt["designer_attempt"])
            packet["local_compiler_issues"] = deepcopy(
                design_receipt.get("local_compiler_issues") or []
            )
            packet["local_compiler_issue_digest_sha256"] = str(
                design_receipt.get("local_compiler_issue_digest_sha256") or ""
            )
            packet["item_handle"] = str(
                design_receipt.get("item_handle") or ""
            )
            packet["skeleton"]["item_handle"] = packet["item_handle"]
            packet[
                "generation_input_digest_sha256"
            ] = _generation_input_digest_for_packet(packet)
        if (
            packet["question_digest_sha256"]
            != values.get("question_digest_sha256")
            or packet["generation_input_digest_sha256"]
            != values.get("generation_input_digest_sha256")
        ):
            return False
        design_run = conn.execute(
            "select * from agent_runs where id = ?",
            (values["generator_run_id"],),
        ).fetchone()
        if not design_run:
            return False
        design_output = db.json_load(design_run["output_json"], None)
        design_envelope = {
            "agent_run_id": values["generator_run_id"],
            "output": design_output,
        }
        if not _validate_db_agent_run(
            conn, packet, design_envelope, role="designer"
        ):
            return False
        compiled = compile_design_output_v2(packet, design_output)
        if (
            _digest(compiled) != values.get("contract_digest_sha256")
            or compiled["reference_solution"]
            != db.json_load(values.get("reference_solution_json"), None)
            or compiled["score_points"]
            != db.json_load(values.get("score_points_json"), None)
        ):
            return False
        review_packet = build_review_packet_v2(packet, compiled)
        review_run = conn.execute(
            "select * from agent_runs where id = ?",
            (values["review_run_id"],),
        ).fetchone()
        if not review_run:
            return False
        review_output = db.json_load(review_run["output_json"], None)
        review_envelope = {
            "agent_run_id": values["review_run_id"],
            "output": review_output,
        }
        if not _validate_db_agent_run(
            conn, review_packet, review_envelope, role="reviewer"
        ):
            return False
        review_result = validate_review_output_v2(review_packet, review_output)
        classification = _classification_for_packet(
            packet,
            review_result,
            compiled_contract=compiled,
            reviewer_run_id=values["review_run_id"],
        )
        if not classification["approved"]:
            return False
        return (
            design_receipt.get("agent_run_id") == values["generator_run_id"]
            and design_receipt.get("generation_input_digest_sha256")
            == packet["generation_input_digest_sha256"]
            and design_receipt.get("item_handle") == packet["item_handle"]
            and design_receipt.get("designer_attempt")
            == packet["designer_attempt"]
            and design_receipt.get("local_compiler_issue_digest_sha256")
            == packet["local_compiler_issue_digest_sha256"]
            and design_receipt.get("local_compiler_issues")
            == packet["local_compiler_issues"]
            and design_receipt.get("output_digest_sha256")
            == _digest(design_output)
            and design_receipt.get("exact_live_lineage") is True
            and review_receipt.get("agent_run_id") == values["review_run_id"]
            and review_receipt.get("contract_digest_sha256")
            == values["contract_digest_sha256"]
            and review_receipt.get("issue_digest_sha256")
            == _digest(review_result["issues"])
            and review_receipt.get("output_digest_sha256")
            == _digest(review_output)
            and review_receipt.get("classification") == classification
            and review_receipt.get("exact_live_lineage") is True
        )
    except (KeyError, TypeError, ValueError, sqlite3.Error):
        return False


def v2_scoring_policy_activation_blockers(
    row: sqlite3.Row | dict[str, Any],
) -> list[str]:
    del row
    return []
