from __future__ import annotations

import hashlib
import os
import json
import threading
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl

from .expert_review import EXPERT_PROFILES, FAIL_SEVERITIES
from .inventory import _item_fingerprint
from .production_loop import AdminProductionError, _digest_json, _load_json_file, _relative
from .qa_review import REQUIRED_HARD_BLOCKERS, REQUIRED_SEMANTIC_QA_PROFILES
from .semantic_collision import (
    validate_semantic_collision_receipt,
    validate_semantic_collision_receipt_lineage,
)


STAGED_BANK_SCHEMA_VERSION = "2026-07-23.codex-admin.staged-question-bank.v1"
STAGING_RECEIPT_SCHEMA_VERSION = "2026-07-23.codex-admin.stage-candidate-receipt.v1"
STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION = "2026-07-24.codex-admin.staged-content-envelope.v1"
DEFAULT_STAGED_BANK_PATH = Path("data/question_banks/v18/staged_candidates_v18.json")

_STAGED_BANK_LOCKS: dict[str, threading.Lock] = {}
_STAGED_BANK_LOCKS_GUARD = threading.Lock()

_REVIEW_ARTIFACT_POLICIES = {
    "machine_check": {
        "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
        "pass_statuses": {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"},
        "decision_digest_keys": ("machine_report_sha256",),
        "path_key": "production_json_path",
        "role": "machine_contract_check",
        "require_source": False,
    },
    "deterministic_expert_review": {
        "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
        "pass_statuses": {"PASS"},
        "decision_digest_keys": ("expert_report_sha256",),
        "path_key": "review_json_path",
        "role": "deterministic_expert_review",
        "require_source": True,
    },
    "model_expert_board_review": {
        "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
        "pass_statuses": {"PASS"},
        "decision_digest_keys": ("model_expert_report_sha256",),
        "path_key": "model_expert_review_json_path",
        "role": "live_model_expert_board_review",
        "require_source": True,
    },
    "qa_contract_check": {
        "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
        "pass_statuses": {"PASS"},
        "decision_digest_keys": ("qa_contract_report_sha256",),
        "path_key": "qa_contract_check_json_path",
        "role": "deterministic_qa_contract_check",
        "gate_type": "deterministic_contract_check",
        "require_source": True,
    },
    "semantic_qa_review": {
        "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
        "pass_statuses": {"PASS"},
        "decision_digest_keys": ("qa_report_sha256", "semantic_qa_report_sha256"),
        "path_key": "qa_json_path",
        "role": "live_model_semantic_qa_review",
        "gate_type": "live_model_semantic_qa",
        "require_source": True,
    },
}

_PRODUCTION_REVIEW_RECEIPT_KEYS = {
    "machine_check",
    "deterministic_expert_review",
    "model_expert_board_review",
    "guanzhi_qa_review",
}

_STAGING_ONLY_QUALITY_FIELDS = {
    "activation_eligible",
    "content_envelope_sha256",
    "review_evidence",
    "review_status",
    "staging_receipts",
    "status",
}


def _staged_bank_lock(root: Path, staged_bank_path: Path) -> threading.Lock:
    resolved = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    key = str(resolved.resolve())
    with _STAGED_BANK_LOCKS_GUARD:
        lock = _STAGED_BANK_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _STAGED_BANK_LOCKS[key] = lock
        return lock


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd = -1
    temp_name = ""
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()


def _candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("item"), dict):
        return dict(payload["item"])
    if isinstance(payload.get("candidate"), dict):
        return dict(payload["candidate"])
    return dict(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolved(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _paths_match(root: Path, left: str, right: Path) -> bool:
    if not left:
        return False
    return _resolved(root, left).resolve() == right.resolve()


def build_staged_content_envelope(item: dict[str, Any]) -> dict[str, Any]:
    content = json.loads(json.dumps(item, ensure_ascii=False))
    content.pop("question_bank_version", None)
    content["source_type"] = str(content.get("source_type") or "ai_original")
    quality = dict(content.get("quality") if isinstance(content.get("quality"), dict) else {})
    for field in _STAGING_ONLY_QUALITY_FIELDS:
        quality.pop(field, None)
    if quality:
        content["quality"] = quality
    else:
        content.pop("quality", None)
    return {
        "schema_version": STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION,
        "item": content,
    }


def staged_content_envelope_sha256(item: dict[str, Any]) -> str:
    return _digest_json(build_staged_content_envelope(item))


def validate_staged_bank_content_envelopes(bank: dict[str, Any]) -> dict[str, Any]:
    if bank.get("schema_version") != STAGED_BANK_SCHEMA_VERSION:
        raise AdminProductionError("ADMIN_STAGED_BANK_UNSUPPORTED_SCHEMA")
    if bank.get("status") != "staged_not_active":
        raise AdminProductionError("ADMIN_STAGED_BANK_STATUS_MUST_NOT_BE_ACTIVE")
    if not isinstance(bank.get("items"), list):
        raise AdminProductionError("ADMIN_STAGED_BANK_ITEMS_MUST_BE_LIST")
    items = list(bank.get("items") or [])
    if int(bank.get("item_count") or 0) != len(items):
        raise AdminProductionError("ADMIN_STAGED_BANK_ITEM_COUNT_MISMATCH")
    for item in items:
        item_id = str(item.get("id") or "")
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
        review_evidence = quality.get("review_evidence") if isinstance(quality.get("review_evidence"), dict) else {}
        expected = str(quality.get("content_envelope_sha256") or staging_receipts.get("content_envelope_sha256") or "")
        if not expected:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_MISSING_CONTENT_ENVELOPE: {item_id}")
        if str(staging_receipts.get("content_envelope_sha256") or "") != expected:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_RECEIPT_ENVELOPE_MISMATCH: {item_id}")
        if str(review_evidence.get("content_envelope_sha256") or "") != expected:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_REVIEW_ENVELOPE_MISMATCH: {item_id}")
        actual = staged_content_envelope_sha256(item)
        if actual != expected:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_CONTENT_ENVELOPE_MISMATCH: {item_id}")
        receipts = review_evidence.get("receipts") if isinstance(review_evidence.get("receipts"), dict) else {}
        if set(receipts) != set(_REVIEW_ARTIFACT_POLICIES):
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_REVIEW_RECEIPT_SET_INVALID: {item_id}")
        for receipt_name in _REVIEW_ARTIFACT_POLICIES:
            receipt = receipts.get(receipt_name) if isinstance(receipts.get(receipt_name), dict) else {}
            if str(receipt.get("content_envelope_sha256") or "") != expected:
                raise AdminProductionError(f"ADMIN_STAGED_ITEM_REVIEW_RECEIPT_ENVELOPE_MISMATCH: {item_id}:{receipt_name}")
    return {
        "status": "PASS",
        "schema_version": STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION,
        "validated_item_count": len(items),
    }


def validate_staged_item_collision_lineage(
    staged_item: dict[str, Any],
    *,
    previous_items: list[dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    item_id = str(staged_item.get("id") or "")
    quality = staged_item.get("quality") if isinstance(staged_item.get("quality"), dict) else {}
    staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
    candidate_path_text = str(staging_receipts.get("candidate_path") or "")
    receipt_path_text = str(staging_receipts.get("semantic_collision_receipt_path") or "")
    receipt_sha256 = str(staging_receipts.get("semantic_collision_receipt_sha256") or "")
    if not candidate_path_text:
        raise AdminProductionError(f"ADMIN_STAGED_ITEM_CANDIDATE_PATH_MISSING: {item_id}")
    if not receipt_path_text or not receipt_sha256:
        raise AdminProductionError(f"ADMIN_STAGED_ITEM_COLLISION_RECEIPT_MISSING: {item_id}")

    validated = validate_semantic_collision_receipt_lineage(
        root=root,
        receipt_path=_resolved(root, receipt_path_text),
        candidate_path=_resolved(root, candidate_path_text),
        expected_receipt_sha256=receipt_sha256,
    )
    expected_fields = {
        "semantic_collision_candidate_set_sha256": "candidate_set_sha256",
        "semantic_collision_base_staged_bank_sha256": "base_staged_bank_sha256",
        "semantic_collision_base_snapshot_sha256": "base_staged_snapshot_sha256",
        "semantic_collision_decision": "decision",
    }
    for staged_key, validated_key in expected_fields.items():
        if staging_receipts.get(staged_key) != validated.get(validated_key):
            raise AdminProductionError(
                f"ADMIN_STAGED_ITEM_COLLISION_BINDING_MISMATCH: {item_id}:{staged_key}"
            )

    previous_by_id = {str(item.get("id") or ""): item for item in previous_items}
    base_bindings = list(validated.get("base_staged_item_bindings") or [])
    candidate_bindings = list(validated.get("candidate_bindings") or [])
    decisions = dict(validated.get("candidate_decisions") or {})
    base_by_id = {str(binding.get("item_id") or ""): binding for binding in base_bindings}
    candidate_by_id = {
        str(binding.get("item_id") or ""): binding for binding in candidate_bindings
    }
    if len(base_by_id) != len(base_bindings) or len(candidate_by_id) != len(candidate_bindings):
        raise AdminProductionError(f"ADMIN_STAGED_ITEM_COLLISION_BINDING_IDS_INVALID: {item_id}")

    for previous_id, previous_item in previous_by_id.items():
        if previous_id in base_by_id:
            if str(base_by_id[previous_id].get("item_sha256") or "") != _digest_json(previous_item):
                raise AdminProductionError(
                    f"ADMIN_STAGED_ITEM_COLLISION_BASE_BINDING_MISMATCH: {item_id}:{previous_id}"
                )
            continue
        sibling_binding = candidate_by_id.get(previous_id)
        sibling_decision = decisions.get(previous_id) if isinstance(decisions.get(previous_id), dict) else {}
        previous_quality = previous_item.get("quality") if isinstance(previous_item.get("quality"), dict) else {}
        previous_receipts = previous_quality.get("staging_receipts") if isinstance(previous_quality.get("staging_receipts"), dict) else {}
        if (
            not sibling_binding
            or sibling_decision.get("decision") != "PASS"
            or previous_receipts.get("candidate_sha256") != sibling_binding.get("candidate_sha256")
        ):
            raise AdminProductionError(
                f"ADMIN_STAGED_ITEM_COLLISION_PREVIOUS_ITEM_NOT_REVIEWED: {item_id}:{previous_id}"
            )

    return validated


def validate_staged_bank_collision_lineage(bank: dict[str, Any], *, root: Path) -> dict[str, Any]:
    validate_staged_bank_content_envelopes(bank)
    previous_items: list[dict[str, Any]] = []
    receipt_paths: set[str] = set()
    for staged_item in bank.get("items") or []:
        validated = validate_staged_item_collision_lineage(
            staged_item,
            previous_items=previous_items,
            root=root,
        )
        receipt_paths.add(str(validated.get("receipt_path") or ""))
        previous_items.append(staged_item)
    return {
        "status": "PASS",
        "validated_item_count": len(previous_items),
        "validated_collision_receipt_count": len(receipt_paths),
    }


def _load_or_new_staged_bank(root: Path, staged_bank_path: Path) -> dict[str, Any]:
    resolved = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    if not resolved.exists():
        return {
            "schema_version": STAGED_BANK_SCHEMA_VERSION,
            "question_bank_version": "2026-07-23.bank.v18.staged",
            "status": "staged_not_active",
            "activation_policy": "Staged candidates are not child-runtime active until activation manifest and gates pass.",
            "item_count": 0,
            "items": [],
        }
    payload = _load_json_file(root, resolved)
    if payload.get("schema_version") != STAGED_BANK_SCHEMA_VERSION:
        raise AdminProductionError("ADMIN_STAGED_BANK_UNSUPPORTED_SCHEMA")
    if payload.get("status") != "staged_not_active":
        raise AdminProductionError("ADMIN_STAGED_BANK_STATUS_MUST_NOT_BE_ACTIVE")
    validate_staged_bank_content_envelopes(payload)
    return payload


def _review_logic_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "2026-07-23.codex-admin.question-review-logic.v1",
        "deterministic_expert_review": {
            "fail_severities": sorted(FAIL_SEVERITIES),
            "profiles": {
                profile_id: {
                    "display": profile.get("display", ""),
                    "focus": list(profile.get("focus") or []),
                }
                for profile_id, profile in sorted(EXPERT_PROFILES.items())
            },
            "quality_checks": [
                "graph_node_must_exist",
                "question_family_must_belong_to_node_blueprint",
                "child_prompt_must_be_self_contained",
                "child_surface_must_not_leak_internal_terms_or_english_repair_phrases",
                "required_evidence_must_have_at_least_three_items",
                "key_score_points_must_have_at_least_three_items_and_total_ten_points",
                "standard_answer_or_expected_answer_must_exist",
                "source_lineage_must_not_copy_commercial_or_private_bank_items",
                "stretch_items_must_require_reasoning_or_transfer_surface",
                "known_policy_overrides_must_hold_for_opposite_and_equation_flow_items",
            ],
        },
        "model_expert_board_review": {
            "required_provider_mode": "live_model",
            "pass_statuses": ["PASS"],
            "blocking_findings": ["P0", "P1"],
            "must_bind_same_candidate_identity": True,
            "must_include_route_and_prompt_meta": True,
            "purpose": "用模型专家组复查题目是否真正符合图谱节点、题型要求、孩子端质量、证据范围和题源边界。",
        },
        "qa_contract_check": {
            "gate_type": "deterministic_contract_check",
            "pass_statuses": ["PASS"],
            "semantic_authority": False,
        },
        "semantic_qa_review": {
            "gate_type": "live_model_semantic_qa",
            "required_provider_mode": "live_model",
            "pass_statuses": ["PASS"],
            "blocking_findings": ["P0", "P1"],
            "required_profiles": list(REQUIRED_SEMANTIC_QA_PROFILES),
            "required_hard_blockers": list(REQUIRED_HARD_BLOCKERS),
            "must_bind_qa_contract_artifact_digest": True,
        },
        "guanzhi_qa_review": {
            "gate_type": "live_model_semantic_qa",
            "required_provider_mode": "live_model",
            "pass_statuses": ["PASS"],
            "quality_checks": [
                "child_surface_has_no_internal_leaks",
                "mathematical_validity",
                "answer_contract_alignment",
                "age_and_teaching_fit",
                "single_slot_evidence_scope",
            ],
            "must_bind_qa_contract_artifact_digest": True,
        },
        "staging_decision": {
            "all_receipts_must_match_candidate_identity": True,
            "candidate_sha256_must_match_payload": True,
            "five_independent_review_artifacts_required": True,
            "activation_authority": "does_not_authorize_activation",
        },
    }


def _review_evidence_snapshot(decision: dict[str, Any], *, receipt_refs: dict[str, Any]) -> dict[str, Any]:
    review_receipts = decision.get("review_receipts") if isinstance(decision.get("review_receipts"), dict) else {}
    return {
        "schema_version": "2026-07-23.codex-admin.item-review-evidence.v1",
        "content_envelope_sha256": receipt_refs.get("content_envelope_sha256", ""),
        "review_logic": _review_logic_snapshot(),
        "receipts": {
            receipt_name: review_receipts.get(receipt_name) or {}
            for receipt_name in _REVIEW_ARTIFACT_POLICIES
        },
        "staging_decision": {
            "status": str(decision.get("status") or ""),
            "report_path": receipt_refs.get("staging_decision_path", ""),
            "report_sha256": receipt_refs.get("staging_decision_sha256", ""),
            "finding_counts": decision.get("finding_counts") or {},
            "finding_codes": [
                {
                    "severity": str(finding.get("severity") or ""),
                    "profile": str(finding.get("profile") or ""),
                    "code": str(finding.get("code") or ""),
                }
                for finding in (decision.get("findings") or [])
                if isinstance(finding, dict)
            ],
        },
        "activation_implication": "does_not_authorize_activation",
    }


def _normalize_staged_item(item: dict[str, Any], *, receipt_refs: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    staged = json.loads(json.dumps(item, ensure_ascii=False))
    staged["question_bank_version"] = "2026-07-23.bank.v18.staged"
    quality = dict(staged.get("quality") if isinstance(staged.get("quality"), dict) else {})
    quality["review_status"] = "staged"
    quality["status"] = "staged"
    quality["activation_eligible"] = False
    quality["content_envelope_sha256"] = receipt_refs.get("content_envelope_sha256", "")
    quality["staging_receipts"] = receipt_refs
    quality["review_evidence"] = _review_evidence_snapshot(decision, receipt_refs=receipt_refs)
    staged["quality"] = quality
    staged["source_type"] = str(staged.get("source_type") or "ai_original")
    return staged


def _structure_fingerprint_set(item: dict[str, Any]) -> set[str]:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return {
        value
        for value in (
            _item_fingerprint(item),
            str(quality.get("canonical_structure_fingerprint") or ""),
            str(quality.get("model_structure_fingerprint") or ""),
            str(quality.get("structure_fingerprint") or ""),
            str(item.get("math_core_signature") or ""),
            str(item.get("variant_signature") or ""),
        )
        if value
    }


def _artifact_identity(report: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(report.get("item_id") or ""),
        str(report.get("node_id") or ""),
        str(report.get("family_id") or ""),
    )


def _verify_model_expert_semantics(report: dict[str, Any]) -> None:
    if str(report.get("provider_mode") or "") != "live_model":
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_NOT_LIVE")
    route = report.get("route") if isinstance(report.get("route"), dict) else {}
    prompt_meta = report.get("prompt_meta") if isinstance(report.get("prompt_meta"), dict) else {}
    if not route.get("raw_response_sha256") or not route.get("structured_json_mode"):
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_MISSING_ROUTE_EVIDENCE")
    if not prompt_meta.get("rendered_prompt_sha256") or not prompt_meta.get("response_schema_sha256"):
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_MISSING_PROMPT_EVIDENCE")
    profile_reviews = report.get("profile_reviews") if isinstance(report.get("profile_reviews"), list) else []
    if len(profile_reviews) != len(EXPERT_PROFILES):
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_PROFILE_COVERAGE_INVALID")
    profile_statuses = {
        str(profile.get("profile") or ""): str(profile.get("status") or "")
        for profile in profile_reviews
        if isinstance(profile, dict)
    }
    if set(profile_statuses) != set(EXPERT_PROFILES):
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_PROFILE_COVERAGE_INVALID")
    if any(status != "pass" for status in profile_statuses.values()):
        raise AdminProductionError("ADMIN_STAGE_MODEL_EXPERT_PROFILE_BLOCKED")


def _verify_deterministic_expert_profiles(report: dict[str, Any]) -> None:
    profiles = report.get("expert_profiles") if isinstance(report.get("expert_profiles"), dict) else {}
    if set(profiles) != set(EXPERT_PROFILES):
        raise AdminProductionError("ADMIN_STAGE_DETERMINISTIC_EXPERT_PROFILE_COVERAGE_INVALID")
    if any(
        not isinstance(profile, dict) or str(profile.get("status") or "") != "PASS"
        for profile in profiles.values()
    ):
        raise AdminProductionError("ADMIN_STAGE_DETERMINISTIC_EXPERT_PROFILE_BLOCKED")


def _verify_qa_contract_semantics(report: dict[str, Any]) -> None:
    if str(report.get("gate_type") or "") != "deterministic_contract_check":
        raise AdminProductionError("ADMIN_STAGE_QA_CONTRACT_GATE_TYPE_INVALID")
    if str(report.get("engine_type") or "") != "deterministic_contract_validation":
        raise AdminProductionError("ADMIN_STAGE_QA_CONTRACT_ENGINE_TYPE_INVALID")
    if report.get("semantic_authority") is not False:
        raise AdminProductionError("ADMIN_STAGE_QA_CONTRACT_SEMANTIC_AUTHORITY_INVALID")


def _verify_semantic_qa_semantics(report: dict[str, Any], *, contract_artifact_sha256: str) -> None:
    if str(report.get("gate_type") or "") != "live_model_semantic_qa":
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_GATE_TYPE_INVALID")
    if str(report.get("qa_contract_report_sha256") or "") != contract_artifact_sha256:
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_CONTRACT_DIGEST_MISMATCH")
    if str(report.get("provider_mode") or "") != "live_model":
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_NOT_LIVE")
    route = report.get("route") if isinstance(report.get("route"), dict) else {}
    prompt_meta = report.get("prompt_meta") if isinstance(report.get("prompt_meta"), dict) else {}
    if not route.get("raw_response_sha256") or not route.get("structured_json_mode"):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_MISSING_ROUTE_EVIDENCE")
    if not prompt_meta.get("rendered_prompt_sha256") or not prompt_meta.get("response_schema_sha256"):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_MISSING_PROMPT_EVIDENCE")
    normalization = report.get("status_normalization") if isinstance(report.get("status_normalization"), dict) else {}
    if (
        normalization.get("authority") != "deterministic_from_profile_verdicts"
        or normalization.get("model_overall_status_is_advisory") is not True
    ):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_NORMALIZATION_INVALID")
    profile_reviews = report.get("profile_reviews") if isinstance(report.get("profile_reviews"), list) else []
    profile_counts = Counter(
        str(review.get("profile") or "")
        for review in profile_reviews
        if isinstance(review, dict)
    )
    if profile_counts != Counter({profile: 1 for profile in REQUIRED_SEMANTIC_QA_PROFILES}):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_PROFILE_COVERAGE_INVALID")
    if any(str(review.get("status") or "") != "pass" for review in profile_reviews):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_PROFILE_BLOCKED")
    if report.get("profile_verdicts") != {profile: "pass" for profile in REQUIRED_SEMANTIC_QA_PROFILES}:
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_PROFILE_VERDICTS_INVALID")
    hard_blockers = report.get("hard_blockers") if isinstance(report.get("hard_blockers"), dict) else {}
    if set(hard_blockers) != set(REQUIRED_HARD_BLOCKERS):
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_HARD_BLOCKER_COVERAGE_INVALID")
    for blocker in hard_blockers.values():
        evidence = blocker.get("evidence") if isinstance(blocker, dict) else None
        if (
            not isinstance(blocker, dict)
            or blocker.get("detected") is not False
            or not isinstance(evidence, list)
            or any(not isinstance(entry, str) or not entry.strip() for entry in evidence)
        ):
            raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_HARD_BLOCKER_INVALID")
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    expected_scope = {
        "support_only": False,
        "not_for_activation": False,
        "exclude_from_coverage": False,
        "reasons": [],
    }
    if scope != expected_scope:
        raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_PASS_SCOPE_INVALID")


def _decision_review_summaries(decision: dict[str, Any]) -> dict[str, dict[str, Any]]:
    review_receipts = decision.get("review_receipts") if isinstance(decision.get("review_receipts"), dict) else {}
    if set(review_receipts) != _PRODUCTION_REVIEW_RECEIPT_KEYS:
        raise AdminProductionError("ADMIN_STAGE_REVIEW_RECEIPT_SET_INVALID")
    contract_summary = decision.get("qa_contract_check")
    if not isinstance(contract_summary, dict) or not contract_summary:
        raise AdminProductionError("ADMIN_STAGE_QA_CONTRACT_RECEIPT_MISSING")
    return {
        "machine_check": review_receipts["machine_check"],
        "deterministic_expert_review": review_receipts["deterministic_expert_review"],
        "model_expert_board_review": review_receipts["model_expert_board_review"],
        "qa_contract_check": contract_summary,
        "semantic_qa_review": review_receipts["guanzhi_qa_review"],
    }


def _verify_artifact_summaries(
    *,
    root: Path,
    candidate_path: Path,
    item: dict[str, Any],
    candidate_sha256: str,
    content_envelope_sha256: str,
    summaries: dict[str, dict[str, Any]],
    decision: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    if set(summaries) != set(_REVIEW_ARTIFACT_POLICIES):
        raise AdminProductionError("ADMIN_STAGE_REVIEW_RECEIPT_SET_INVALID")
    expected_identity = (
        str(item.get("id") or ""),
        str(item.get("node_id") or ""),
        str(item.get("question_type") or ""),
    )
    candidate_file_sha256 = _sha256(candidate_path)
    verified: dict[str, Any] = {}
    digests: dict[str, str] = {}
    artifact_paths: set[Path] = set()
    reports: dict[str, dict[str, Any]] = {}
    for receipt_name, policy in _REVIEW_ARTIFACT_POLICIES.items():
        summary = summaries.get(receipt_name) if isinstance(summaries.get(receipt_name), dict) else {}
        report_path_text = str(summary.get("report_path") or "")
        if not report_path_text:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_PATH_MISSING: {receipt_name}")
        report_path = _resolved(root, report_path_text)
        if not report_path.exists():
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_MISSING: {receipt_name}:{report_path}")
        artifact_sha256 = _sha256(report_path)
        if str(summary.get("report_sha256") or "") != artifact_sha256:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_DIGEST_MISMATCH: {receipt_name}")
        resolved_report_path = report_path.resolve()
        if resolved_report_path in artifact_paths:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_PATH_REUSED: {receipt_name}")
        artifact_paths.add(resolved_report_path)
        for decision_digest_key in policy["decision_digest_keys"]:
            if decision is not None and str(decision.get(decision_digest_key) or "") != artifact_sha256:
                raise AdminProductionError(f"ADMIN_STAGE_DECISION_ARTIFACT_DIGEST_MISMATCH: {receipt_name}:{decision_digest_key}")
            digests[str(decision_digest_key)] = artifact_sha256
        report = _load_json_file(root, report_path)
        if not isinstance(report, dict):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_NOT_OBJECT: {receipt_name}")
        if report.get("schema_version") != policy["schema_version"]:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_SCHEMA_INVALID: {receipt_name}")
        status = str(report.get("status") or report.get("overall_status") or "")
        if status not in policy["pass_statuses"]:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_NOT_PASSED: {receipt_name}:{status}")
        if str(summary.get("status") or "") != status:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_STATUS_MISMATCH: {receipt_name}")
        if str(summary.get("role") or "") != str(policy["role"]):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_ROLE_MISMATCH: {receipt_name}")
        if str(summary.get("schema_version") or "") != str(report.get("schema_version") or ""):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_SCHEMA_MISMATCH: {receipt_name}")
        if _artifact_identity(report) != expected_identity:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_IDENTITY_MISMATCH: {receipt_name}")
        if (
            str(summary.get("item_id") or ""),
            str(summary.get("node_id") or ""),
            str(summary.get("family_id") or ""),
        ) != expected_identity:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_IDENTITY_MISMATCH: {receipt_name}")
        if str(report.get("candidate_sha256") or "") != candidate_sha256:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_CANDIDATE_MISMATCH: {receipt_name}")
        if str(summary.get("candidate_sha256") or "") != candidate_sha256:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_CANDIDATE_MISMATCH: {receipt_name}")
        expected_gate_type = str(policy.get("gate_type") or "")
        if expected_gate_type and (
            str(report.get("gate_type") or "") != expected_gate_type
            or str(summary.get("gate_type") or "") != expected_gate_type
        ):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_GATE_TYPE_MISMATCH: {receipt_name}")
        if report.get("provider_mode") is not None and str(summary.get("provider_mode") or "") != str(report.get("provider_mode") or ""):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_PROVIDER_MISMATCH: {receipt_name}")
        if (
            receipt_name == "semantic_qa_review"
            and summary.get("qa_contract_report_sha256")
            and str(summary.get("qa_contract_report_sha256") or "") != str(report.get("qa_contract_report_sha256") or "")
        ):
            raise AdminProductionError("ADMIN_STAGE_SEMANTIC_QA_SUMMARY_CONTRACT_DIGEST_MISMATCH")
        if report.get("write_applied") is not True:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_NOT_APPLIED: {receipt_name}")
        path_key = str(policy["path_key"])
        if not _paths_match(root, str(report.get(path_key) or ""), report_path):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_SELF_PATH_MISMATCH: {receipt_name}")
        findings = report.get("findings") if isinstance(report.get("findings"), list) else []
        if any(not isinstance(finding, dict) for finding in findings):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_FINDINGS_INVALID: {receipt_name}")
        finding_counts = dict(sorted(Counter(str(finding.get("severity") or "") for finding in findings).items()))
        if report.get("finding_counts") != finding_counts:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_FINDING_COUNTS_MISMATCH: {receipt_name}")
        if finding_counts.get("P0") or finding_counts.get("P1"):
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_ARTIFACT_HAS_BLOCKERS: {receipt_name}")
        finding_codes = [
            {
                "severity": str(finding.get("severity") or ""),
                "profile": str(finding.get("profile") or ""),
                "code": str(finding.get("code") or ""),
            }
            for finding in findings
        ]
        if summary.get("finding_counts") != finding_counts:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_FINDING_COUNTS_MISMATCH: {receipt_name}")
        if summary.get("finding_codes") != finding_codes:
            raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_FINDING_CODES_MISMATCH: {receipt_name}")
        if policy["require_source"]:
            if not _paths_match(root, str(report.get("source_path") or ""), candidate_path):
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SOURCE_PATH_MISMATCH: {receipt_name}")
            if str(report.get("source_file_sha256") or "") != candidate_file_sha256:
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SOURCE_DIGEST_MISMATCH: {receipt_name}")
            if not _paths_match(root, str(summary.get("source_path") or ""), candidate_path):
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_SOURCE_PATH_MISMATCH: {receipt_name}")
            if str(summary.get("source_file_sha256") or "") != candidate_file_sha256:
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_SOURCE_DIGEST_MISMATCH: {receipt_name}")
        else:
            if summary.get("source_path") and not _paths_match(root, str(summary.get("source_path") or ""), candidate_path):
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_SOURCE_PATH_MISMATCH: {receipt_name}")
            if summary.get("source_file_sha256") and str(summary.get("source_file_sha256") or "") != candidate_file_sha256:
                raise AdminProductionError(f"ADMIN_STAGE_REVIEW_SUMMARY_SOURCE_DIGEST_MISMATCH: {receipt_name}")
        if receipt_name == "model_expert_board_review":
            _verify_model_expert_semantics(report)
        if receipt_name == "deterministic_expert_review":
            _verify_deterministic_expert_profiles(report)
        if receipt_name == "qa_contract_check":
            _verify_qa_contract_semantics(report)
        reports[receipt_name] = report
        source_path = str(report.get("source_path") or "")
        source_file_sha256 = str(report.get("source_file_sha256") or "")
        if not policy["require_source"]:
            source_path = _relative(root, candidate_path)
            source_file_sha256 = candidate_file_sha256
        verified[receipt_name] = {
            "role": policy["role"],
            "schema_version": report.get("schema_version"),
            "status": status,
            "gate_type": str(report.get("gate_type") or ""),
            "provider_mode": str(report.get("provider_mode") or ""),
            "item_id": expected_identity[0],
            "node_id": expected_identity[1],
            "family_id": expected_identity[2],
            "candidate_sha256": candidate_sha256,
            "content_envelope_sha256": content_envelope_sha256,
            "source_file_sha256": source_file_sha256,
            "source_path": source_path,
            "report_path": _relative(root, report_path),
            "report_sha256": artifact_sha256,
            "qa_contract_report_sha256": str(report.get("qa_contract_report_sha256") or ""),
            "finding_counts": finding_counts,
            "finding_codes": finding_codes,
        }
    _verify_semantic_qa_semantics(
        reports["semantic_qa_review"],
        contract_artifact_sha256=verified["qa_contract_check"]["report_sha256"],
    )
    return verified, digests


def _verify_review_artifacts(
    *,
    root: Path,
    candidate_path: Path,
    item: dict[str, Any],
    candidate_sha256: str,
    content_envelope_sha256: str,
    decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    return _verify_artifact_summaries(
        root=root,
        candidate_path=candidate_path,
        item=item,
        candidate_sha256=candidate_sha256,
        content_envelope_sha256=content_envelope_sha256,
        summaries=_decision_review_summaries(decision),
        decision=decision,
    )


def validate_staged_bank_review_artifacts(bank: dict[str, Any], *, root: Path) -> dict[str, Any]:
    envelope_report = validate_staged_bank_content_envelopes(bank)
    collision_report = validate_staged_bank_collision_lineage(bank, root=root)
    verified_artifact_count = 0
    for staged_item in bank.get("items") or []:
        item_id = str(staged_item.get("id") or "")
        quality = staged_item.get("quality") if isinstance(staged_item.get("quality"), dict) else {}
        staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
        review_evidence = quality.get("review_evidence") if isinstance(quality.get("review_evidence"), dict) else {}
        candidate_path_text = str(staging_receipts.get("candidate_path") or "")
        if not candidate_path_text:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_CANDIDATE_PATH_MISSING: {item_id}")
        candidate_path = _resolved(root, candidate_path_text)
        if not candidate_path.is_file():
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_CANDIDATE_ARTIFACT_MISSING: {item_id}")
        candidate_payload = _load_json_file(root, candidate_path)
        candidate_item = _candidate_item(candidate_payload)
        candidate_sha256 = _digest_json(candidate_item)
        if str(staging_receipts.get("candidate_sha256") or "") != candidate_sha256:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_CANDIDATE_DIGEST_MISMATCH: {item_id}")
        content_envelope_sha256 = str(quality.get("content_envelope_sha256") or "")
        if staged_content_envelope_sha256(candidate_item) != content_envelope_sha256:
            raise AdminProductionError(f"ADMIN_STAGED_ITEM_CANDIDATE_ENVELOPE_MISMATCH: {item_id}")
        summaries = review_evidence.get("receipts") if isinstance(review_evidence.get("receipts"), dict) else {}
        verified, _digests = _verify_artifact_summaries(
            root=root,
            candidate_path=candidate_path,
            item=candidate_item,
            candidate_sha256=candidate_sha256,
            content_envelope_sha256=content_envelope_sha256,
            summaries=summaries,
        )
        verified_artifact_count += len(verified)
    return {
        "status": "PASS",
        "validated_item_count": envelope_report["validated_item_count"],
        "verified_artifact_count": verified_artifact_count,
        "required_artifacts_per_item": len(_REVIEW_ARTIFACT_POLICIES),
        "validated_collision_receipt_count": collision_report[
            "validated_collision_receipt_count"
        ],
    }


def build_stage_candidate_receipt(
    *,
    root: Path,
    candidate_path: Path,
    staging_decision_path: Path,
    staged_bank_path: Path = DEFAULT_STAGED_BANK_PATH,
    semantic_collision_receipt_path: Path | None = None,
    semantic_collision_receipt_sha256: str = "",
    subject: str = "math",
) -> dict[str, Any]:
    resolved_candidate = candidate_path if candidate_path.is_absolute() else root / candidate_path
    resolved_decision = staging_decision_path if staging_decision_path.is_absolute() else root / staging_decision_path
    resolved_staged_bank = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    candidate_payload = _load_json_file(root, resolved_candidate)
    decision = _load_json_file(root, resolved_decision)
    item = _candidate_item(candidate_payload)
    item_id = str(item.get("id") or "")
    if not item_id:
        raise AdminProductionError("ADMIN_STAGE_CANDIDATE_MISSING_ITEM_ID")
    if semantic_collision_receipt_path is None or not semantic_collision_receipt_sha256:
        raise AdminProductionError("ADMIN_STAGE_COLLISION_RECEIPT_REQUIRED")
    collision_binding: dict[str, Any] = {}
    validated_collision = validate_semantic_collision_receipt(
        root=root,
        receipt_path=semantic_collision_receipt_path,
        candidate_path=resolved_candidate,
        staged_bank_path=resolved_staged_bank,
        expected_receipt_sha256=semantic_collision_receipt_sha256,
    )
    collision_binding = {
        "semantic_collision_receipt_path": str(validated_collision.get("receipt_path") or ""),
        "semantic_collision_receipt_sha256": str(validated_collision.get("receipt_sha256") or ""),
        "semantic_collision_candidate_set_sha256": str(
            validated_collision.get("candidate_set_sha256") or ""
        ),
        "semantic_collision_base_staged_bank_sha256": str(
            validated_collision.get("base_staged_bank_sha256") or ""
        ),
        "semantic_collision_base_snapshot_sha256": str(
            validated_collision.get("base_staged_snapshot_sha256") or ""
        ),
        "semantic_collision_decision": dict(validated_collision.get("decision") or {}),
    }
    if decision.get("schema_version") != "2026-07-23.codex-admin.production-staging-decision.v1":
        raise AdminProductionError("ADMIN_STAGE_UNSUPPORTED_STAGING_DECISION_SCHEMA")
    if decision.get("status") != "STAGED_READY" or not decision.get("staging_allowed"):
        raise AdminProductionError("ADMIN_STAGE_DECISION_NOT_READY")
    if str(decision.get("item_id") or "") != item_id:
        raise AdminProductionError("ADMIN_STAGE_ITEM_MISMATCH")
    if str(decision.get("node_id") or "") != str(item.get("node_id") or ""):
        raise AdminProductionError("ADMIN_STAGE_NODE_MISMATCH")
    if str(decision.get("family_id") or "") != str(item.get("question_type") or ""):
        raise AdminProductionError("ADMIN_STAGE_FAMILY_MISMATCH")
    candidate_sha = _digest_json(item)
    if not decision.get("candidate_sha256"):
        raise AdminProductionError("ADMIN_STAGE_DECISION_MISSING_CANDIDATE_SHA256")
    if str(decision.get("candidate_sha256") or "") != candidate_sha:
        raise AdminProductionError("ADMIN_STAGE_CANDIDATE_SHA256_MISMATCH")
    if decision.get("write_applied") is not True:
        raise AdminProductionError("ADMIN_STAGE_DECISION_NOT_APPLIED")
    if not _paths_match(root, str(decision.get("production_json_path") or ""), resolved_decision):
        raise AdminProductionError("ADMIN_STAGE_DECISION_SELF_PATH_MISMATCH")
    content_envelope_sha = staged_content_envelope_sha256(item)
    verified_receipts, verified_digests = _verify_review_artifacts(
        root=root,
        candidate_path=resolved_candidate,
        item=item,
        candidate_sha256=candidate_sha,
        content_envelope_sha256=content_envelope_sha,
        decision=decision,
    )
    verified_decision = {
        **decision,
        **verified_digests,
        "review_receipts": verified_receipts,
    }

    bank = _load_or_new_staged_bank(root, resolved_staged_bank)
    items = list(bank.get("items") or [])
    fingerprint = _item_fingerprint(item)
    candidate_fingerprints = _structure_fingerprint_set(item)
    for existing in items:
        existing_id = str(existing.get("id") or "")
        existing_quality = existing.get("quality") if isinstance(existing.get("quality"), dict) else {}
        existing_receipts = existing_quality.get("staging_receipts") if isinstance(existing_quality.get("staging_receipts"), dict) else {}
        existing_candidate_sha = str(existing_receipts.get("candidate_sha256") or "")
        if existing_id == item_id and existing_candidate_sha and existing_candidate_sha != candidate_sha:
            raise AdminProductionError("ADMIN_STAGE_DUPLICATE_ITEM_ID_DIFFERENT_PAYLOAD")
        if existing_id == item_id:
            existing_envelope_sha = staged_content_envelope_sha256(existing)
            if existing_envelope_sha != content_envelope_sha:
                raise AdminProductionError("ADMIN_STAGE_DUPLICATE_ITEM_ID_DIFFERENT_CONTENT_ENVELOPE")
            return {
                "schema_version": STAGING_RECEIPT_SCHEMA_VERSION,
                "status": "ALREADY_STAGED",
                "subject": subject,
                "item_id": item_id,
                "node_id": item.get("node_id"),
                "family_id": item.get("question_type"),
                "candidate_sha256": candidate_sha,
                "content_envelope_sha256": content_envelope_sha,
                "structure_fingerprint": fingerprint,
                "staged_bank_path": _relative(root, resolved_staged_bank),
                "_staged_bank_resolved_path": str(resolved_staged_bank),
                "staged_item_count": len(items),
                **collision_binding,
                "activation_allowed": False,
                "activation_implication": "does_not_authorize_activation",
            }
        if candidate_fingerprints and (_structure_fingerprint_set(existing) & candidate_fingerprints):
            raise AdminProductionError("ADMIN_STAGE_DUPLICATE_STRUCTURE_FINGERPRINT")

    receipt_refs = {
        "candidate_path": _relative(root, resolved_candidate),
        "candidate_sha256": candidate_sha,
        "content_envelope_sha256": content_envelope_sha,
        "staging_decision_path": _relative(root, resolved_decision),
        "staging_decision_sha256": _sha256(resolved_decision),
        **verified_digests,
        **collision_binding,
    }
    staged_item = _normalize_staged_item(item, receipt_refs=receipt_refs, decision=verified_decision)
    if staged_content_envelope_sha256(staged_item) != content_envelope_sha:
        raise AdminProductionError("ADMIN_STAGE_NORMALIZATION_CHANGED_CONTENT_ENVELOPE")
    items.append(staged_item)
    bank["items"] = items
    bank["item_count"] = len(items)
    bank["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    validate_staged_bank_content_envelopes(bank)
    return {
        "schema_version": STAGING_RECEIPT_SCHEMA_VERSION,
        "status": "STAGED_WRITABLE",
        "subject": subject,
        "item_id": item_id,
        "node_id": staged_item.get("node_id"),
        "family_id": staged_item.get("question_type"),
        "candidate_sha256": candidate_sha,
        "content_envelope_sha256": content_envelope_sha,
        "structure_fingerprint": fingerprint,
        "staged_bank_path": _relative(root, resolved_staged_bank),
        "_staged_bank_resolved_path": str(resolved_staged_bank),
        "staged_item_count": len(items),
        "staged_bank_payload": bank,
        **collision_binding,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def write_stage_candidate_receipt(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    result = dict(report)
    staged_bank_payload = result.pop("staged_bank_payload", None)
    staged_bank_resolved_path = result.pop("_staged_bank_resolved_path", "")
    result["write_applied"] = bool(apply)
    if not apply:
        return result
    bank_path = Path(staged_bank_resolved_path) if staged_bank_resolved_path else root / str(report.get("staged_bank_path") or DEFAULT_STAGED_BANK_PATH)
    bank_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(staged_bank_payload, dict):
        _atomic_write_json(bank_path, staged_bank_payload)
        result["staged_bank_sha256"] = hashlib.sha256(bank_path.read_bytes()).hexdigest()
    receipt_id_input = "|".join([
        str(result.get("schema_version") or ""),
        str(result.get("status") or ""),
        str(result.get("item_id") or ""),
        str(result.get("candidate_sha256") or ""),
        str(result.get("content_envelope_sha256") or ""),
    ])
    receipt_id = "STAGE-" + hashlib.sha256(receipt_id_input.encode("utf-8")).hexdigest()[:12]
    json_rel = Path("data/admin/staging") / f"{receipt_id}.json"
    json_path = root / json_rel
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["stage_receipt_id"] = receipt_id
    result["stage_receipt_json_path"] = str(json_rel)
    _atomic_write_json(json_path, result)
    result["stage_receipt_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result


def build_and_write_stage_candidate_receipt(
    *,
    root: Path,
    artifact_root: Path,
    candidate_path: Path,
    staging_decision_path: Path,
    staged_bank_path: Path = DEFAULT_STAGED_BANK_PATH,
    semantic_collision_receipt_path: Path | None = None,
    semantic_collision_receipt_sha256: str = "",
    subject: str = "math",
    apply: bool = False,
) -> dict[str, Any]:
    resolved_staged_bank = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    with _staged_bank_lock(root, resolved_staged_bank):
        lock_path = resolved_staged_bank.with_suffix(resolved_staged_bank.suffix + ".lock")
        with _FileLock(lock_path):
            receipt = build_stage_candidate_receipt(
                root=artifact_root,
                candidate_path=candidate_path,
                staging_decision_path=staging_decision_path,
                staged_bank_path=resolved_staged_bank,
                semantic_collision_receipt_path=semantic_collision_receipt_path,
                semantic_collision_receipt_sha256=semantic_collision_receipt_sha256,
                subject=subject,
            )
            return write_stage_candidate_receipt(receipt, root=artifact_root, apply=apply)


def build_and_write_blocked_stage_candidate_receipt(
    *,
    root: Path,
    artifact_root: Path,
    candidate_path: Path,
    staging_decision_path: Path,
    staged_bank_path: Path = DEFAULT_STAGED_BANK_PATH,
    item_id: str = "",
    subject: str = "math",
    error: Exception,
    apply: bool = False,
) -> dict[str, Any]:
    resolved_candidate = (
        candidate_path if candidate_path.is_absolute() else artifact_root / candidate_path
    )
    resolved_decision = (
        staging_decision_path
        if staging_decision_path.is_absolute()
        else artifact_root / staging_decision_path
    )
    resolved_bank = (
        staged_bank_path
        if staged_bank_path.is_absolute()
        else root / staged_bank_path
    )
    report = {
        "schema_version": STAGING_RECEIPT_SCHEMA_VERSION,
        "status": "BLOCKED_STAGE_EXCEPTION",
        "subject": subject,
        "item_id": item_id,
        "candidate_path": _relative(artifact_root, resolved_candidate),
        "staging_decision_path": _relative(artifact_root, resolved_decision),
        "staged_bank_path": _relative(artifact_root, resolved_bank),
        "error": {
            "type": type(error).__name__,
            "message": str(error)[:1200],
        },
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }
    return write_stage_candidate_receipt(report, root=artifact_root, apply=apply)
