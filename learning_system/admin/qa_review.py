from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import internal_agents, model_router
from .expert_review import SEVERITY_ORDER
from .inventory import AdminPaths, _blueprints_by_node, _families_by_id, _graph_nodes_by_id, _load_assets
from .model_deadline import bind_admin_structured_model_deadline
from .production_loop import _relative


QA_CONTRACT_CHECK_SCHEMA_VERSION = "2026-07-24.codex-admin.candidate-qa-contract-check.v1"
SEMANTIC_QA_REPORT_SCHEMA_VERSION = "2026-07-23.codex-admin.candidate-qa-review.v1"
SEMANTIC_QA_RESPONSE_SCHEMA_VERSION = "2026-07-24.admin-question-qa-review.schema.v1"

REQUIRED_SEMANTIC_QA_PROFILES = (
    "mathematical_validity",
    "answer_contract_alignment",
    "graph_family_alignment",
    "child_appropriateness",
    "diagnostic_meaningfulness",
)

REQUIRED_HARD_BLOCKERS = (
    "mathematical_ambiguity",
    "prompt_answer_conflict",
    "node_or_family_mismatch",
    "age_inappropriate",
    "meaningless_formal_requirement",
)

HARD_BLOCKER_PROFILE = {
    "mathematical_ambiguity": "mathematical_validity",
    "prompt_answer_conflict": "answer_contract_alignment",
    "node_or_family_mismatch": "graph_family_alignment",
    "age_inappropriate": "child_appropriateness",
    "meaningless_formal_requirement": "diagnostic_meaningfulness",
}

SEMANTIC_PROFILE_STATUSES = {"pass", "pass_with_scope", "needs_revision", "reject"}
SCOPE_KEYS = {"support_only", "not_for_activation", "exclude_from_coverage", "reasons"}


def _candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("item"), dict):
        return dict(payload["item"])
    if isinstance(payload.get("candidate"), dict):
        return dict(payload["candidate"])
    return dict(payload)


def _load_candidate(root: Path, candidate_path: Path, *, error_prefix: str) -> tuple[Path, dict[str, Any]]:
    resolved = candidate_path if candidate_path.is_absolute() else root / candidate_path
    if not resolved.exists():
        raise ValueError(f"{error_prefix}_CANDIDATE_MISSING: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{error_prefix}_INVALID_CANDIDATE_JSON: {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{error_prefix}_CANDIDATE_MUST_BE_OBJECT: {resolved}")
    return resolved, _candidate_item(payload)


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    item: dict[str, Any],
    profile: str,
    issue_type: str = "contract_or_evidence_invalid",
) -> dict[str, str]:
    return {
        "severity": severity,
        "profile": profile,
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "issue_type": issue_type,
        "code": code,
        "message": message,
    }


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(finding.get("severity") or "") for finding in findings).items()))


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _score_point_sum(item: dict[str, Any]) -> float:
    total = 0.0
    for point in item.get("key_score_points") or []:
        if not isinstance(point, dict):
            continue
        try:
            total += float(point.get("points") or 0)
        except (TypeError, ValueError):
            continue
    return total


def build_candidate_qa_contract_check(
    *,
    root: Path,
    candidate_path: Path,
    subject: str = "math",
    version: str = "v18",
) -> dict[str, Any]:
    """Validate deterministic structure and lineage only; this is not a semantic verdict."""
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    resolved, item = _load_candidate(root, candidate_path, error_prefix="ADMIN_QA_CONTRACT")
    findings: list[dict[str, Any]] = []
    node_id = str(item.get("node_id") or "")
    family_id = str(item.get("question_type") or "")

    if not item.get("id"):
        findings.append(_finding("P0", "qa_contract_missing_item_id", "候选题缺少稳定 id。", item=item, profile="qa_contract_check"))
    if node_id not in nodes:
        findings.append(_finding("P0", "qa_contract_unknown_graph_node", "候选题绑定未知图谱节点。", item=item, profile="qa_contract_check"))
    if node_id not in blueprints:
        findings.append(_finding("P0", "qa_contract_missing_node_blueprint", "候选题节点缺少蓝图。", item=item, profile="qa_contract_check"))
    if family_id not in families:
        findings.append(_finding("P0", "qa_contract_unknown_family", "候选题题型家族未知。", item=item, profile="qa_contract_check"))

    blueprint = blueprints.get(node_id) or {}
    allowed_families = {
        str(entry.get("family_id") or "")
        for entry in blueprint.get("family_plan") or []
        if isinstance(entry, dict) and entry.get("family_id")
    }
    if allowed_families and family_id not in allowed_families:
        findings.append(_finding("P1", "qa_contract_family_not_in_node_blueprint", "题型家族不在节点蓝图 family_plan 中。", item=item, profile="qa_contract_check"))

    lineage = item.get("production_lineage") if isinstance(item.get("production_lineage"), dict) else {}
    lineage_family = str(lineage.get("family_id") or "")
    if not lineage:
        findings.append(_finding("P1", "qa_contract_missing_production_lineage", "候选题缺少 production_lineage。", item=item, profile="qa_contract_check"))
    elif lineage_family != family_id:
        findings.append(_finding("P1", "qa_contract_lineage_family_mismatch", "production_lineage.family_id 与 question_type 不一致。", item=item, profile="qa_contract_check"))

    required_string_fields = ("prompt", "answer_format")
    for field in required_string_fields:
        if not isinstance(item.get(field), str) or not str(item.get(field) or "").strip():
            findings.append(_finding("P1", f"qa_contract_missing_{field}", f"候选题缺少非空 {field}。", item=item, profile="qa_contract_check"))
    if not str(item.get("standard_answer") or item.get("expected_answer") or "").strip():
        findings.append(_finding("P1", "qa_contract_missing_answer", "候选题缺少标准答案或 expected_answer。", item=item, profile="qa_contract_check"))

    required_evidence = item.get("required_evidence")
    if not isinstance(required_evidence, list) or len(required_evidence) < 3:
        findings.append(_finding("P1", "qa_contract_weak_required_evidence", "required_evidence 必须是至少三项的列表。", item=item, profile="qa_contract_check"))
    score_points = item.get("key_score_points")
    if not isinstance(score_points, list) or len(score_points) < 3:
        findings.append(_finding("P1", "qa_contract_weak_score_points", "key_score_points 必须是至少三项的列表。", item=item, profile="qa_contract_check"))
    elif _score_point_sum(item) != 10:
        findings.append(_finding("P1", "qa_contract_score_points_not_10", "key_score_points 分值合计必须为 10。", item=item, profile="qa_contract_check"))

    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    if not str(quality.get("structure_fingerprint") or "").strip():
        findings.append(_finding("P1", "qa_contract_missing_structure_fingerprint", "缺少结构指纹，无法执行重复结构门。", item=item, profile="qa_contract_check"))

    status = "NEEDS_FIX" if any(str(finding.get("severity") or "") in {"P0", "P1"} for finding in findings) else "PASS"
    sorted_findings = sorted(findings, key=lambda finding: (SEVERITY_ORDER.get(str(finding.get("severity") or ""), 9), str(finding.get("code") or "")))
    return {
        "schema_version": QA_CONTRACT_CHECK_SCHEMA_VERSION,
        "gate_type": "deterministic_contract_check",
        "engine_type": "deterministic_contract_validation",
        "semantic_authority": False,
        "subject": subject,
        "question_bank_version": version,
        "status": status,
        "item_id": str(item.get("id") or ""),
        "node_id": node_id,
        "family_id": family_id,
        "candidate_sha256": _digest_json(item),
        "source_file_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "source_path": _relative(root, resolved),
        "reviewed_item_count": 1,
        "finding_counts": _counts(sorted_findings),
        "findings": sorted_findings,
        "staging_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["semantic_qa_review"] if status == "PASS" else ["repair_contract_or_regenerate_candidate"],
    }


def build_candidate_qa_review(
    *,
    root: Path,
    candidate_path: Path,
    subject: str = "math",
    version: str = "v18",
) -> dict[str, Any]:
    """Compatibility name for the former deterministic QA; now explicitly a contract check."""
    return build_candidate_qa_contract_check(
        root=root,
        candidate_path=candidate_path,
        subject=subject,
        version=version,
    )


def _normalization_finding(item_id: str, code: str, message: str) -> dict[str, str]:
    return {
        "severity": "P1",
        "profile": "semantic_qa_normalizer",
        "item_id": item_id,
        "node_id": "",
        "issue_type": "contract_or_evidence_invalid",
        "code": code,
        "message": message,
    }


def _valid_scope(scope: Any) -> bool:
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
        return False
    if not all(isinstance(scope.get(key), bool) for key in ("support_only", "not_for_activation", "exclude_from_coverage")):
        return False
    reasons = scope.get("reasons")
    return isinstance(reasons, list) and all(isinstance(reason, str) and reason.strip() for reason in reasons)


def _empty_scope() -> dict[str, Any]:
    return {
        "support_only": False,
        "not_for_activation": False,
        "exclude_from_coverage": False,
        "reasons": [],
    }


def normalize_semantic_qa_result(
    value: dict[str, Any],
    *,
    item_id: str,
    minimum_confidence: float,
) -> dict[str, Any]:
    """Fail closed and derive the gate status from structured profile verdicts."""
    findings = [dict(finding) for finding in value.get("findings") or [] if isinstance(finding, dict)]
    profile_reviews = [dict(review) for review in value.get("profile_reviews") or [] if isinstance(review, dict)]
    profile_counts = Counter(str(review.get("profile") or "") for review in profile_reviews)
    expected_profile_counts = Counter({profile: 1 for profile in REQUIRED_SEMANTIC_QA_PROFILES})
    profile_coverage_valid = profile_counts == expected_profile_counts
    if not profile_coverage_valid:
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_profile_coverage_invalid",
                "语义 QA 必须且只能为每个必需 profile 提交一份 verdict。",
            )
        )

    profile_statuses: dict[str, str] = {}
    for review in profile_reviews:
        profile = str(review.get("profile") or "")
        status = str(review.get("status") or "")
        if profile in REQUIRED_SEMANTIC_QA_PROFILES and profile not in profile_statuses:
            profile_statuses[profile] = status
        if status not in SEMANTIC_PROFILE_STATUSES:
            findings.append(
                _normalization_finding(
                    item_id,
                    "semantic_qa_profile_status_invalid",
                    f"profile {profile or '<missing>'} 的 verdict 不在允许集合中。",
                )
            )

    hard_blockers_value = value.get("hard_blockers")
    hard_blockers = dict(hard_blockers_value) if isinstance(hard_blockers_value, dict) else {}
    hard_blockers_valid = set(hard_blockers) == set(REQUIRED_HARD_BLOCKERS)
    detected_blockers: list[str] = []
    if hard_blockers_valid:
        for blocker in REQUIRED_HARD_BLOCKERS:
            evidence = hard_blockers.get(blocker)
            if not isinstance(evidence, dict) or not isinstance(evidence.get("detected"), bool) or not isinstance(evidence.get("evidence"), list):
                hard_blockers_valid = False
                break
            if not all(isinstance(entry, str) and entry.strip() for entry in evidence.get("evidence") or []):
                hard_blockers_valid = False
                break
            if evidence.get("detected"):
                detected_blockers.append(blocker)
                expected_profile = HARD_BLOCKER_PROFILE[blocker]
                if profile_statuses.get(expected_profile) not in {"needs_revision", "reject"}:
                    findings.append(
                        _normalization_finding(
                            item_id,
                            "semantic_qa_hard_blocker_profile_inconsistent",
                            f"hard blocker {blocker} 已检出，但对应 profile 未给出阻断 verdict。",
                        )
                    )
                if not evidence.get("evidence"):
                    hard_blockers_valid = False
    if not hard_blockers_valid:
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_hard_blockers_invalid",
                "五类 hard blockers 必须完整、结构化并在 detected 时附证据。",
            )
        )

    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < minimum_confidence:
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_low_confidence",
                f"语义 QA 置信度 {confidence:.2f} 低于应用阈值 {minimum_confidence:.2f}。",
            )
        )

    scope_value = value.get("scope")
    scope = dict(scope_value) if isinstance(scope_value, dict) else {}
    scope_valid = _valid_scope(scope)
    if not scope_valid:
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_scope_invalid",
                "语义 QA 必须始终返回完整的结构化 scope 对象。",
            )
        )
    scope_signal = any(status == "pass_with_scope" for status in profile_statuses.values())
    scope_signal = scope_signal or any(str(finding.get("severity") or "") in {"P2", "INFO"} for finding in findings)
    if scope_valid:
        scope_signal = scope_signal or any(bool(scope.get(key)) for key in ("support_only", "not_for_activation", "exclude_from_coverage"))

    if scope_signal and (
        not scope_valid
        or not any(bool(scope.get(key)) for key in ("support_only", "not_for_activation", "exclude_from_coverage"))
        or not scope.get("reasons")
    ):
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_scope_invalid",
                "PASS_WITH_SCOPE 必须提供完整 restriction flags 和非空 reasons。",
            )
        )
        scope_valid = False
    elif not scope_signal and scope_valid and scope.get("reasons"):
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_scope_invalid",
                "scope reasons 非空时必须同时存在 restriction flag。",
            )
        )
        scope_valid = False

    severities = {str(finding.get("severity") or "") for finding in findings}
    blocker_findings = [
        finding
        for finding in findings
        if str(finding.get("issue_type") or "") in REQUIRED_HARD_BLOCKERS
    ]
    if blocker_findings:
        findings.append(
            _normalization_finding(
                item_id,
                "semantic_qa_hard_issue_finding_blocks",
                "五类硬问题一旦以结构化 issue_type 检出，不得降级为 P2 或 scoped pass。",
            )
        )
        severities.add("P1")
    statuses = set(profile_statuses.values())
    normalization_invalid = any(str(finding.get("profile") or "") == "semantic_qa_normalizer" for finding in findings)
    if "reject" in statuses or "P0" in severities:
        status = "REJECT"
    elif (
        "needs_revision" in statuses
        or detected_blockers
        or "P1" in severities
        or normalization_invalid
        or confidence < minimum_confidence
        or not profile_coverage_valid
        or not hard_blockers_valid
    ):
        status = "NEEDS_FIX"
    elif scope_signal and scope_valid:
        status = "PASS_WITH_SCOPE"
    elif statuses == {"pass"} and profile_coverage_valid:
        status = "PASS"
    else:
        status = "NEEDS_FIX"

    return {
        "status": status,
        "model_reported_overall_status": str(value.get("overall_status") or ""),
        "confidence": confidence,
        "profile_reviews": profile_reviews,
        "profile_verdicts": {profile: profile_statuses.get(profile, "missing") for profile in REQUIRED_SEMANTIC_QA_PROFILES},
        "hard_blockers": hard_blockers,
        "scope": scope if scope_valid else _empty_scope(),
        "finding_counts": _counts(findings),
        "findings": sorted(
            findings,
            key=lambda finding: (
                SEVERITY_ORDER.get(str(finding.get("severity") or ""), 9),
                str(finding.get("profile") or ""),
                str(finding.get("code") or ""),
            ),
        ),
        "status_normalization": {
            "authority": "deterministic_from_profile_verdicts",
            "model_overall_status_is_advisory": True,
            "required_profiles": list(REQUIRED_SEMANTIC_QA_PROFILES),
            "required_hard_blockers": list(REQUIRED_HARD_BLOCKERS),
        },
    }


def _semantic_prompt_payload(
    *,
    root: Path,
    candidate_path: Path,
    item: dict[str, Any],
    contract_check: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    blueprints: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = internal_agents.load_contract("admin_question_qa_review", version_suffix="v1")
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    prompt_template = prompt_path.read_text(encoding="utf-8")
    node_id = str(item.get("node_id") or "")
    family_id = str(item.get("question_type") or "")
    trusted_context = {
        "schema_version": "2026-07-24.codex-admin.semantic-qa-context.v1",
        "candidate_path": str(candidate_path),
        "candidate_sha256": _digest_json(item),
        "node": nodes.get(node_id) or {},
        "node_blueprint": blueprints.get(node_id) or {},
        "question_family": families.get(family_id) or {},
        "contract_check": {
            "status": contract_check.get("status"),
            "finding_counts": contract_check.get("finding_counts") or {},
            "findings": contract_check.get("findings") or [],
        },
        "review_authority": "semantic_review_receipt_only_does_not_authorize_activation",
    }
    prompt = (
        prompt_template
        .replace("{trusted_context_json}", json.dumps(trusted_context, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{untrusted_payload_json}", json.dumps({"candidate": item}, ensure_ascii=False, indent=2, sort_keys=True))
    )
    payload = {
        "instructions": "You are admin_question_qa_review_agent. Return only schema-valid JSON for the semantic QA receipt.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    meta = {
        "prompt_template_path": _relative(root, prompt_path),
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path),
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_schema_version": str(contract.get("response_schema_version") or ""),
        "response_schema_sha256": internal_agents.canonical_json_sha256(contract.get("response_schema") or {}),
        "contract_version": str(contract.get("contract_version") or ""),
        "minimum_confidence_to_apply": contract.get("minimum_confidence_to_apply"),
    }
    return payload, meta, contract


def build_candidate_semantic_qa_review(
    *,
    root: Path,
    candidate_path: Path,
    contract_check: dict[str, Any] | None = None,
    subject: str = "math",
    version: str = "v18",
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    resolved, item = _load_candidate(root, candidate_path, error_prefix="ADMIN_SEMANTIC_QA")
    contract_check = contract_check or build_candidate_qa_contract_check(
        root=root,
        candidate_path=resolved,
        subject=subject,
        version=version,
    )
    candidate_sha256 = _digest_json(item)
    source_file_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    contract_check_sha256 = str(contract_check.get("qa_contract_check_json_sha256") or _digest_json(contract_check))
    route = model_router.question_reviewer_route()
    prompt_payload, prompt_meta, contract = _semantic_prompt_payload(
        root=root,
        candidate_path=resolved,
        item=item,
        contract_check=contract_check,
        nodes=nodes,
        blueprints=blueprints,
        families=families,
    )
    base = {
        "schema_version": SEMANTIC_QA_REPORT_SCHEMA_VERSION,
        "gate_type": "live_model_semantic_qa",
        "engine_type": "model_semantic_quality_gate",
        "subject": subject,
        "question_bank_version": version,
        "status": "BLOCKED_MODEL_NOT_CONFIGURED",
        "model_reported_overall_status": "",
        "provider_mode": "not_configured",
        "retryable": False,
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "family_id": str(item.get("question_type") or ""),
        "candidate_sha256": candidate_sha256,
        "qa_contract_report_sha256": contract_check_sha256,
        "source_file_sha256": source_file_sha256,
        "source_path": _relative(root, resolved),
        "reviewed_item_count": 1,
        "route": model_router.route_status(route).as_dict(),
        "prompt_meta": prompt_meta,
        "profile_reviews": [],
        "profile_verdicts": {},
        "hard_blockers": {},
        "scope": _empty_scope(),
        "finding_counts": {},
        "findings": [],
        "status_normalization": {
            "authority": "deterministic_from_profile_verdicts",
            "model_overall_status_is_advisory": True,
        },
        "staging_allowed": False,
        "coverage_eligible": False,
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["configure_question_reviewer_model"],
    }
    if contract_check.get("status") != "PASS":
        return {
            **base,
            "status": "BLOCKED_CONTRACT_CHECK",
            "provider_mode": "not_called",
            "next_actions": ["repair_contract_or_regenerate_candidate"],
        }
    if not route.enabled:
        return base

    transport_meta: dict[str, Any] = {}
    try:
        started = datetime.now(timezone.utc)
        with bind_admin_structured_model_deadline(
            batch_attempt_id=f"admin_question_semantic_qa:{candidate_path}",
            timeout_envs=(
                "AI_ADMIN_QUESTION_QA_REVIEW_WALL_SECONDS",
                "AI_QUESTION_REVIEW_WALL_SECONDS",
                "AI_QUESTION_REVIEW_TIMEOUT_SECONDS",
                "AI_QUESTION_TIMEOUT_SECONDS",
            ),
            default_seconds=120.0,
        ) as transport_meta:
            result = model_router.call_structured_json(
                route,
                prompt_payload,
                schema=contract.get("response_schema") or {},
                retryable_errors_fallback=True,
            )
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    except model_router.ModelCallError as exc:
        return {
            **base,
            "status": "BLOCKED_MODEL_ERROR",
            "provider_mode": "live_model",
            "retryable": model_router.is_retryable_model_call_error(exc),
            "model_error": {
                "error_class": type(exc).__name__,
                "message": str(exc)[:800],
                "status_code": exc.status_code,
                "retry_after_seconds": exc.retry_after_seconds,
                "endpoint": exc.endpoint,
                "structured_json_mode": exc.structured_json_mode,
            },
            "transport_meta": transport_meta,
            "next_actions": ["retry_or_repair_semantic_qa_route"],
        }

    normalized = normalize_semantic_qa_result(
        result.value,
        item_id=str(item.get("id") or ""),
        minimum_confidence=float(contract.get("minimum_confidence_to_apply") or 0.86),
    )
    status = str(normalized.get("status") or "NEEDS_FIX")
    return {
        **base,
        **normalized,
        "provider_mode": "live_model",
        "retryable": False,
        "route": {
            **model_router.route_status(route).as_dict(),
            "structured_json_mode": result.mode,
            "structured_json_endpoint": result.endpoint,
            "model_elapsed_ms": elapsed_ms,
            **transport_meta,
            "raw_response_sha256": hashlib.sha256(
                json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "staging_allowed": False,
        "coverage_eligible": status == "PASS",
        "next_actions": (
            ["staging_decision"]
            if status == "PASS"
            else ["retain_as_support_only"]
            if status == "PASS_WITH_SCOPE"
            else ["regenerate_candidate"]
        ),
    }


def render_candidate_qa_review_markdown(report: dict[str, Any]) -> str:
    finding_lines = [
        f"| {finding.get('severity', '')} | {finding.get('profile', '')} | {finding.get('code', '')} | {finding.get('message', '')} |"
        for finding in report.get("findings") or []
    ]
    if not finding_lines:
        finding_lines.append("| | | | |")
    title = "Candidate QA Contract Check" if report.get("gate_type") == "deterministic_contract_check" else "Candidate Semantic QA Review"
    return f"""# {title}

Status: `{report.get('status')}`

Created At: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

Gate Type: `{report.get('gate_type')}`

Item: {report.get('item_id')}

Node: {report.get('node_id')}

Family: {report.get('family_id')}

Provider Mode: `{report.get('provider_mode', 'deterministic')}`

Scope:

```json
{json.dumps(report.get('scope') or {}, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Finding Counts

```json
{json.dumps(report.get('finding_counts') or {}, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Findings

| Severity | Profile | Code | Message |
|---|---|---|---|
{chr(10).join(finding_lines)}
"""


def _write_qa_report(
    report: dict[str, Any],
    *,
    root: Path,
    apply: bool,
    report_prefix: str,
    markdown_dir: Path,
    json_dir: Path,
    id_key: str,
    markdown_key: str,
    json_key: str,
    markdown_sha_key: str,
    json_sha_key: str,
) -> dict[str, Any]:
    report_id_input = "|".join(
        [
            str(report.get("schema_version") or ""),
            str(report.get("status") or ""),
            str(report.get("item_id") or ""),
            str(report.get("source_path") or ""),
            json.dumps(report.get("finding_counts") or {}, ensure_ascii=False, sort_keys=True),
        ]
    )
    report_id = report_prefix + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    markdown_rel = markdown_dir / f"{datetime.now(timezone.utc).date()}-{report_id}.md"
    json_rel = json_dir / f"{report_id}.json"
    result = {
        **report,
        id_key: report_id,
        markdown_key: str(markdown_rel),
        json_key: str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_candidate_qa_review_markdown(report), encoding="utf-8")
    result[markdown_sha_key] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result[json_sha_key] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result


def write_candidate_qa_contract_check(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    return _write_qa_report(
        report,
        root=root,
        apply=apply,
        report_prefix="QA-CONTRACT-",
        markdown_dir=Path("docs/system/admin_reports/qa_contract_checks"),
        json_dir=Path("data/admin/qa_contract_checks"),
        id_key="qa_contract_check_report_id",
        markdown_key="qa_contract_check_markdown_path",
        json_key="qa_contract_check_json_path",
        markdown_sha_key="qa_contract_check_markdown_sha256",
        json_sha_key="qa_contract_check_json_sha256",
    )


def write_candidate_qa_review(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    """Compatibility writer for the deterministic contract-check API."""
    result = write_candidate_qa_contract_check(report, root=root, apply=apply)
    return {
        **result,
        "qa_report_id": result.get("qa_contract_check_report_id", ""),
        "qa_markdown_path": result.get("qa_contract_check_markdown_path", ""),
        "qa_json_path": result.get("qa_contract_check_json_path", ""),
        "qa_markdown_sha256": result.get("qa_contract_check_markdown_sha256", ""),
        "qa_json_sha256": result.get("qa_contract_check_json_sha256", ""),
    }


def write_candidate_semantic_qa_review(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    return _write_qa_report(
        report,
        root=root,
        apply=apply,
        report_prefix="QA-SEMANTIC-",
        markdown_dir=Path("docs/system/admin_reports/qa"),
        json_dir=Path("data/admin/qa"),
        id_key="qa_report_id",
        markdown_key="qa_markdown_path",
        json_key="qa_json_path",
        markdown_sha_key="qa_markdown_sha256",
        json_sha_key="qa_json_sha256",
    )
