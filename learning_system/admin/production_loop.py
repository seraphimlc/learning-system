from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .expert_ideation import FAMILY_DESIGN_KERNELS, _family_execution_contract
from .expert_review import FAIL_SEVERITIES, SEVERITY_ORDER, ExpertFinding, _review_item
from .inventory import (
    AdminPaths,
    _blueprints_by_node,
    _families_by_id,
    _graph_nodes_by_id,
    _item_fingerprint,
    _load_assets,
    _load_json,
    _question_bank_path,
)


class AdminProductionError(ValueError):
    pass


PASS_MACHINE_STATUSES = {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"}
PASS_EXPERT_STATUSES = {"PASS", "PASS_WITH_SCOPE", "pass", "pass_with_scope"}
BLOCKING_EXPERT_STATUSES = {
    "NEEDS_FIX",
    "needs_revision",
    "reject",
    "REJECT",
    "BLOCKED_MODEL_NOT_CONFIGURED",
    "BLOCKED_MODEL_ERROR",
}

RETRYABLE_MODEL_REVIEW_STATUSES = {"BLOCKED_MODEL_NOT_CONFIGURED", "BLOCKED_MODEL_ERROR"}

REQUIRED_SEMANTIC_QA_PROFILES = {
    "mathematical_validity",
    "answer_contract_alignment",
    "graph_family_alignment",
    "child_appropriateness",
    "diagnostic_meaningfulness",
}

REQUIRED_SEMANTIC_HARD_BLOCKERS = {
    "mathematical_ambiguity",
    "prompt_answer_conflict",
    "node_or_family_mismatch",
    "age_inappropriate",
    "meaningless_formal_requirement",
}

QA_SCOPE_KEYS = {"support_only", "not_for_activation", "exclude_from_coverage", "reasons"}
REQUIREMENT_EXECUTION_FIELDS = (
    "support_only",
    "not_for_activation",
    "exclude_from_coverage",
    "secondary_nodes",
)

REQUIRED_ITEM_FIELDS = (
    "id",
    "item_version",
    "node_id",
    "question_type",
    "difficulty",
    "prompt",
    "answer_format",
    "standard_answer",
    "accepted_alternatives",
    "required_evidence",
    "key_score_points",
    "solution_steps",
    "target_error_tags",
    "rollback_candidates",
)

REQUIRED_LINEAGE_FIELDS = (
    "design_brief_id",
    "family_id",
    "evidence_goal",
    "generation_rationale",
    "generation_attempt",
)

REQUIRED_ITEM_FIELDS_ALLOW_EMPTY_LIST = {"accepted_alternatives", "rollback_candidates"}


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_json_file(root: Path, path: Path) -> Any:
    resolved = path if path.is_absolute() else root / path
    if not resolved.exists():
        raise AdminProductionError(f"ADMIN_PRODUCTION_SOURCE_MISSING: {resolved}")
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdminProductionError(f"ADMIN_PRODUCTION_INVALID_JSON: {resolved}: {exc}") from exc


def _normalize_machine_report(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("machine_report")
    if isinstance(nested, dict) and nested:
        normalized = dict(nested)
        for key in ("production_report_id", "production_json_path", "production_json_sha256", "write_applied"):
            if payload.get(key) is not None:
                normalized[key] = payload.get(key)
        return normalized
    return payload


def _schema_matches(report: dict[str, Any], allowed: set[str]) -> bool:
    return str(report.get("schema_version") or "") in allowed


def _receipt_identity(report: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(report.get("item_id") or ""),
        str(report.get("node_id") or ""),
        str(report.get("family_id") or ""),
    )


def _receipt_source_path(report: dict[str, Any]) -> str:
    return str(report.get("source_path") or "").strip()


def _receipt_has_written_artifact(report: dict[str, Any], path_keys: tuple[str, ...]) -> bool:
    if not _receipt_source_path(report):
        return False
    for key in path_keys:
        if report.get(key):
            return True
    return False


def _receipt_artifact_path(report: dict[str, Any], path_keys: tuple[str, ...]) -> str:
    for key in path_keys:
        value = str(report.get(key) or "")
        if value:
            return value
    return ""


def _review_receipt_summary(
    report: dict[str, Any] | None,
    *,
    role: str,
    digest: str,
    path_keys: tuple[str, ...],
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    report = report or {}
    findings = report.get("findings") or []
    report_path = _receipt_artifact_path(report, path_keys)
    if report_path and artifact_root is not None and not Path(report_path).is_absolute():
        report_path = str(artifact_root / report_path)
    return {
        "role": role,
        "schema_version": str(report.get("schema_version") or ""),
        "status": str(report.get("status") or report.get("overall_status") or ""),
        "item_id": str(report.get("item_id") or ""),
        "node_id": str(report.get("node_id") or ""),
        "family_id": str(report.get("family_id") or ""),
        "slot_id": str(report.get("slot_id") or ""),
        "question_requirement_id": str(report.get("question_requirement_id") or ""),
        "question_requirement_sha256": str(report.get("question_requirement_sha256") or ""),
        "candidate_sha256": str(report.get("candidate_sha256") or ""),
        "source_file_sha256": str(report.get("source_file_sha256") or ""),
        "source_path": _receipt_source_path(report),
        "report_path": report_path,
        "report_sha256": digest,
        "gate_type": str(report.get("gate_type") or ""),
        "provider_mode": str(report.get("provider_mode") or ""),
        "profile_verdicts": report.get("profile_verdicts") or {},
        "scope": report.get("scope") or {},
        "finding_counts": report.get("finding_counts") or {},
        "finding_codes": [
            {
                "severity": str(finding.get("severity") or ""),
                "profile": str(finding.get("profile") or ""),
                "code": str(finding.get("code") or ""),
            }
            for finding in findings
            if isinstance(finding, dict)
        ],
    }


def _receipt_artifact_digest(report: dict[str, Any] | None, hash_keys: tuple[str, ...]) -> str:
    report = report or {}
    for key in hash_keys:
        value = str(report.get(key) or "")
        if value:
            return value
    return _digest_json(report) if report else ""


def _candidate_item(candidate_payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(candidate_payload.get("item"), dict):
        return dict(candidate_payload["item"])
    if isinstance(candidate_payload.get("candidate"), dict):
        return dict(candidate_payload["candidate"])
    return dict(candidate_payload)


def _lineage(candidate: dict[str, Any]) -> dict[str, Any]:
    lineage = candidate.get("production_lineage")
    if isinstance(lineage, dict):
        return lineage
    return {
        key: candidate.get(key)
        for key in (
            "design_brief_id",
            "question_requirement_id",
            "slot_id",
            "family_id",
            "evidence_goal",
            "generation_rationale",
            "generation_attempt",
        )
        if key in candidate
    }


def _lineage_value(candidate: dict[str, Any], key: str) -> Any:
    return _lineage(candidate).get(key) or candidate.get(key)


def _family_id(candidate: dict[str, Any]) -> str:
    return str(
        _lineage_value(candidate, "family_id")
        or candidate.get("question_type")
        or candidate.get("problem_family_id")
        or ""
    )


def _score_point_sum(item: dict[str, Any]) -> float:
    total = 0.0
    for point in item.get("key_score_points") or []:
        if isinstance(point, dict):
            try:
                total += float(point.get("points") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    item: dict[str, Any],
    profile: str = "admin_production_gate",
) -> dict[str, str]:
    return {
        "severity": severity,
        "profile": profile,
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "code": code,
        "message": message,
    }


def _finding_from_expert(finding: ExpertFinding) -> dict[str, str]:
    return finding.to_dict()


def _status_from_findings(findings: list[dict[str, str]]) -> str:
    severities = {finding.get("severity") for finding in findings}
    if severities & FAIL_SEVERITIES:
        return "NEEDS_REGENERATION"
    if "P2" in severities or "INFO" in severities:
        return "SELF_CHECKED_PASS_WITH_SCOPE"
    return "SELF_CHECKED_PASS"


def _findings_by_severity(findings: list[dict[str, str]]) -> dict[str, int]:
    return dict(sorted(Counter(str(finding.get("severity") or "") for finding in findings).items()))


def _brief_family_suggestions(design_brief: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for profile in (design_brief.get("profile_contributions") or {}).values():
        for suggestion in profile.get("suggestions") or []:
            family_id = str(suggestion.get("family_id") or "")
            if family_id:
                by_family.setdefault(family_id, []).append(suggestion)
    return by_family


def _latest_design_brief_path(root: Path, node_id: str) -> Path | None:
    design_dir = root / "data/admin/design_ideas"
    if not design_dir.exists():
        return None
    candidates = []
    for path in design_dir.glob("EXPERT-IDEAS-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("node_id") == node_id:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None


def resolve_design_brief(root: Path, *, node_id: str | None = None, design_brief_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    if design_brief_path is None:
        if not node_id:
            raise AdminProductionError("ADMIN_PRODUCTION_REQUIRES_NODE_OR_DESIGN_BRIEF")
        design_brief_path = _latest_design_brief_path(root, node_id)
        if design_brief_path is None:
            raise AdminProductionError(f"ADMIN_PRODUCTION_MISSING_DESIGN_BRIEF: {node_id}")
    resolved = design_brief_path if design_brief_path.is_absolute() else root / design_brief_path
    brief = _load_json_file(root, resolved)
    if brief.get("schema_version") != "2026-07-23.codex-admin.expert-design-ideas.v1":
        raise AdminProductionError("ADMIN_PRODUCTION_UNSUPPORTED_DESIGN_BRIEF_SCHEMA")
    return brief, resolved


def build_question_requirement_plan(
    *,
    root: Path,
    node_id: str,
    version: str = "v18",
    subject: str = "math",
    design_brief_path: Path | None = None,
    bank_path: Path | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    resolved_bank_path = _question_bank_path(paths, version, bank_path=bank_path)
    bank = _load_json(resolved_bank_path)
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    design_brief, resolved_brief_path = resolve_design_brief(root, node_id=node_id, design_brief_path=design_brief_path)
    suggestions_by_family = _brief_family_suggestions(design_brief)
    findings: list[dict[str, str]] = []
    pseudo_item = {"id": "", "node_id": node_id}

    if node_id not in graph_nodes:
        findings.append(_finding("P0", "unknown_graph_node", f"未知图谱节点：{node_id}", item=pseudo_item))
    if node_id not in blueprints:
        findings.append(_finding("P0", "missing_node_blueprint", f"节点缺少蓝图：{node_id}", item=pseudo_item))
    if design_brief.get("node_id") != node_id:
        findings.append(_finding("P0", "design_brief_node_mismatch", "专家 brief 与目标节点不一致。", item=pseudo_item))
    if max_attempts < 1 or max_attempts > 5:
        findings.append(_finding("P1", "invalid_max_attempts", "每个 slot 的重出次数必须在 1-5 之间。", item=pseudo_item))

    blueprint = blueprints.get(node_id) or {}
    slots: list[dict[str, Any]] = [dict(slot) for slot in design_brief.get("question_requirements") or []]
    for slot in slots:
        if not isinstance(slot.get("usage_policy"), dict):
            slot["usage_policy"] = _usage_policy_for_requirement(slot)
    if not slots:
        findings.append(_finding("P1", "design_brief_missing_question_requirements", "专家 brief 缺少逐题 requirement slots。", item=pseudo_item))

    seen_slot_ids: set[str] = set()
    seen_requirement_ids: set[str] = set()
    allowed_families = {str(entry.get("family_id") or "") for entry in blueprint.get("family_plan") or []}
    for index, slot in enumerate(slots):
        slot_item = {"id": slot.get("slot_id") or slot.get("question_requirement_id"), "node_id": slot.get("node_id") or node_id}
        slot.setdefault("max_attempts", max_attempts)
        if slot.get("node_id") != node_id:
            findings.append(_finding("P1", "requirement_slot_node_mismatch", "逐题 requirement 的 node_id 与目标节点不一致。", item=slot_item))
        family_id = str(slot.get("family_id") or "")
        if family_id not in families:
            findings.append(_finding("P0", "unknown_question_family", f"逐题 requirement 引用未知题型家族：{family_id}", item=slot_item))
        if allowed_families and family_id not in allowed_families:
            findings.append(_finding("P1", "requirement_family_not_in_blueprint", "逐题 requirement 题型家族不在节点蓝图中。", item=slot_item))
        if family_id not in suggestions_by_family:
            findings.append(_finding("P1", "family_missing_from_expert_brief", f"专家 brief 没有覆盖题型家族：{family_id}", item=slot_item))
        if family_id not in FAMILY_DESIGN_KERNELS:
            findings.append(_finding("P1", "family_missing_design_kernel", f"题型家族缺少专家设计内核，不能进入生产命题：{family_id}", item=slot_item))
        expected_execution = _canonical_requirement_execution_contract(
            blueprint=blueprint,
            families=families,
            family_id=family_id,
        )
        findings.extend(
            _requirement_execution_findings(
                slot=slot,
                expected=expected_execution,
                item=slot_item,
            )
        )
        if not slot.get("slot_id"):
            findings.append(_finding("P1", "requirement_missing_slot_id", "逐题 requirement 缺少 slot_id。", item=slot_item))
        elif str(slot["slot_id"]) in seen_slot_ids:
            findings.append(_finding("P1", "duplicate_requirement_slot_id", "逐题 requirement slot_id 重复。", item=slot_item))
        seen_slot_ids.add(str(slot.get("slot_id") or ""))
        if not slot.get("question_requirement_id"):
            findings.append(_finding("P1", "requirement_missing_id", "逐题 requirement 缺少 question_requirement_id。", item=slot_item))
        elif str(slot["question_requirement_id"]) in seen_requirement_ids:
            findings.append(_finding("P1", "duplicate_question_requirement_id", "逐题 requirement id 重复。", item=slot_item))
        seen_requirement_ids.add(str(slot.get("question_requirement_id") or ""))
        if int(slot.get("slot_order") or 0) != index + 1:
            findings.append(_finding("P1", "requirement_slot_order_not_contiguous", "逐题 requirement 的 slot_order 必须从 1 连续排列。", item=slot_item))
        for field in ("difficulty", "evidence_goal", "question_direction", "coverage_role"):
            if not slot.get(field):
                findings.append(_finding("P1", f"requirement_missing_{field}", f"逐题 requirement 缺少字段：{field}。", item=slot_item))

    status = "REQUIREMENT_PLAN_READY" if slots and not any(f["severity"] in FAIL_SEVERITIES for f in findings) else "BLOCKED"
    return {
        "schema_version": "2026-07-23.codex-admin.question-requirement-plan.v1",
        "status": status,
        "subject": subject,
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_path": _relative(root, resolved_bank_path),
        "design_brief_id": design_brief.get("report_id"),
        "design_brief_path": _relative(root, resolved_brief_path),
        "node_id": node_id,
        "node_name": (graph_nodes.get(node_id) or {}).get("name") or blueprint.get("node_name"),
        "requirement_count": len(slots),
        "question_requirements": slots,
        "workflow": [
            "question_requirement_ready",
            "question_designer_agent_generate_candidate",
            "admin_machine_check",
            "expert_review",
            "loop_regenerate_or_continue",
            "qa_review",
            "staging_decision",
        ],
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("code", ""))),
        "next_actions": ["generate_candidate_for_first_requirement"] if status == "REQUIREMENT_PLAN_READY" else ["repair_design_brief_or_blueprint"],
    }


def _usage_policy_for_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    coverage_role = str(requirement.get("coverage_role") or "")
    support_only = bool(requirement.get("support_only"))
    if support_only:
        allowed_purposes = ["teaching"]
        practice_family = "concept_model"
        practice_roles = []
        diagnostic_roles = []
        teaching_roles = ["concept_build", "worked_example", "targeted_repair"]
    elif coverage_role == "confirmation_or_variant":
        allowed_purposes = ["practice", "diagnostic"]
        practice_family = "variation_reverse_reasoning"
        practice_roles = ["near_transfer", "far_transfer"]
        diagnostic_roles = ["confirmation_core", "confirmation_transfer"]
        teaching_roles = []
    elif coverage_role == "transfer_or_stretch":
        allowed_purposes = ["practice", "diagnostic"]
        practice_family = "controlled_stretch"
        practice_roles = ["controlled_challenge"]
        diagnostic_roles = ["confirmation_transfer"]
        teaching_roles = []
    else:
        allowed_purposes = ["diagnostic"]
        practice_family = "concept_model"
        practice_roles = []
        diagnostic_roles = ["entry_probe", "prerequisite_probe"]
        teaching_roles = []
    return {
        "allowed_purposes": allowed_purposes,
        "default_practice_family": practice_family,
        "allowed_practice_roles": practice_roles,
        "diagnostic_roles": diagnostic_roles,
        "teaching_roles": teaching_roles,
        "support_only": support_only,
        "not_for_activation": bool(requirement.get("not_for_activation")),
    }


def _load_requirement_plan(root: Path, path: Path) -> dict[str, Any]:
    plan = _load_json_file(root, path)
    if plan.get("schema_version") != "2026-07-23.codex-admin.question-requirement-plan.v1":
        raise AdminProductionError("ADMIN_PRODUCTION_UNSUPPORTED_REQUIREMENT_PLAN_SCHEMA")
    return plan


def _canonical_requirement_execution_contract(
    *,
    blueprint: dict[str, Any],
    families: dict[str, dict[str, Any]],
    family_id: str,
) -> dict[str, Any] | None:
    family_entry = next(
        (
            entry
            for entry in blueprint.get("family_plan") or []
            if str(entry.get("family_id") or "") == family_id
        ),
        None,
    )
    if not isinstance(family_entry, dict):
        return None
    return _family_execution_contract(family_entry, families.get(family_id) or {})


def _requirement_execution_findings(
    *,
    slot: dict[str, Any],
    expected: dict[str, Any] | None,
    item: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if expected is None:
        return findings
    for field in REQUIREMENT_EXECUTION_FIELDS:
        if field not in slot:
            findings.append(
                _finding(
                    "P1",
                    f"requirement_missing_{field}",
                    f"逐题 requirement 缺少可信执行范围字段：{field}。",
                    item=item,
                )
            )
            continue
        actual = slot.get(field)
        canonical = expected[field]
        if field == "secondary_nodes":
            valid = isinstance(actual, list) and actual == canonical
        else:
            valid = isinstance(actual, bool) and actual is canonical
        if not valid:
            findings.append(
                _finding(
                    "P1",
                    f"requirement_{field}_mismatch",
                    f"逐题 requirement 的 {field} 与当前蓝图执行范围不一致。",
                    item=item,
                )
            )
    expected_role = "support_only" if expected["support_only"] else None
    if expected_role and slot.get("coverage_role") != expected_role:
        findings.append(
            _finding(
                "P1",
                "requirement_support_role_mismatch",
                "support-only family 的逐题 requirement 不能提权为 coverage 题。",
                item=item,
            )
        )
    if not expected["support_only"] and slot.get("coverage_role") == "support_only":
        findings.append(
            _finding(
                "P1",
                "requirement_coverage_role_mismatch",
                "普通 coverage family 不能被手写 requirement 降格为未声明的 support-only 角色。",
                item=item,
            )
        )
    return findings


def _requirement_by_slot(plan: dict[str, Any], slot_id: str) -> dict[str, Any] | None:
    for requirement in plan.get("question_requirements") or []:
        if requirement.get("slot_id") == slot_id or requirement.get("question_requirement_id") == slot_id:
            return dict(requirement)
    return None


def build_generation_plan(
    *,
    root: Path,
    node_id: str,
    family_id: str,
    version: str = "v18",
    subject: str = "math",
    design_brief_path: Path | None = None,
    requirement_plan_path: Path | None = None,
    bank_path: Path | None = None,
    slot_id: str | None = None,
    requested_count: int = 1,
    max_attempts: int = 3,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    design_brief, resolved_brief_path = resolve_design_brief(root, node_id=node_id, design_brief_path=design_brief_path)
    suggestions_by_family = _brief_family_suggestions(design_brief)
    slot_requirement: dict[str, Any] | None = None
    requirement_plan: dict[str, Any] | None = None
    requirement_plan_status = ""
    if slot_id:
        if requirement_plan_path is None:
            raise AdminProductionError("ADMIN_PRODUCTION_SLOT_REQUIRES_REQUIREMENT_PLAN")
        requirement_plan = _load_requirement_plan(root, requirement_plan_path)
        requirement_plan_status = str(requirement_plan.get("status") or "")
        slot_requirement = _requirement_by_slot(requirement_plan, slot_id)
        if slot_requirement is None:
            raise AdminProductionError(f"ADMIN_PRODUCTION_UNKNOWN_SLOT: {slot_id}")
        if slot_requirement.get("node_id") != node_id:
            raise AdminProductionError("ADMIN_PRODUCTION_SLOT_NODE_MISMATCH")
        if slot_requirement.get("family_id") != family_id:
            raise AdminProductionError("ADMIN_PRODUCTION_SLOT_FAMILY_MISMATCH")
        requested_count = 1

    inherited_bank_path = str((requirement_plan or {}).get("question_bank_path") or "")
    if bank_path is not None and inherited_bank_path:
        explicit_resolved = paths.resolve(bank_path).resolve()
        inherited_resolved = paths.resolve(Path(inherited_bank_path)).resolve()
        if explicit_resolved != inherited_resolved:
            raise AdminProductionError("ADMIN_PRODUCTION_QUESTION_BANK_PATH_MISMATCH")
    effective_bank_path = bank_path or (Path(inherited_bank_path) if inherited_bank_path else None)
    resolved_bank_path = _question_bank_path(paths, version, bank_path=effective_bank_path)
    bank = _load_json(resolved_bank_path)

    findings: list[dict[str, str]] = []
    pseudo_item = {"id": "", "node_id": node_id}
    if node_id not in graph_nodes:
        findings.append(_finding("P0", "unknown_graph_node", f"未知图谱节点：{node_id}", item=pseudo_item))
    if node_id not in blueprints:
        findings.append(_finding("P0", "missing_node_blueprint", f"节点缺少蓝图：{node_id}", item=pseudo_item))
    if design_brief.get("node_id") != node_id:
        findings.append(_finding("P0", "design_brief_node_mismatch", "专家 brief 与目标节点不一致。", item=pseudo_item))
    if slot_id and requirement_plan_status != "REQUIREMENT_PLAN_READY":
        findings.append(_finding("P1", "requirement_plan_not_ready", "requirement plan 未通过，不能生成 production plan。", item=pseudo_item))
    if family_id not in families:
        findings.append(_finding("P0", "unknown_question_family", f"未知题型家族：{family_id}", item=pseudo_item))
    if family_id not in suggestions_by_family:
        findings.append(_finding("P1", "family_missing_from_expert_brief", "题型家族不在专家设计 brief 中。", item=pseudo_item))
    if family_id not in FAMILY_DESIGN_KERNELS:
        findings.append(_finding("P1", "family_missing_design_kernel", f"题型家族缺少专家设计内核，不能进入生产命题：{family_id}", item=pseudo_item))
    if requested_count < 1 or requested_count > 5:
        findings.append(_finding("P1", "unbounded_generation_count", "每批必须是 1-5 道小批生成，不能一次铺开。", item=pseudo_item))

    blueprint = blueprints.get(node_id) or {}
    family_entry = next((entry for entry in blueprint.get("family_plan") or [] if entry.get("family_id") == family_id), {})
    if slot_requirement is not None:
        expected_execution = _canonical_requirement_execution_contract(
            blueprint=blueprint,
            families=families,
            family_id=family_id,
        )
        findings.extend(
            _requirement_execution_findings(
                slot=slot_requirement,
                expected=expected_execution,
                item={
                    "id": slot_requirement.get("slot_id"),
                    "node_id": node_id,
                },
            )
        )
    node_items = [item for item in bank.get("items") or [] if item.get("node_id") == node_id]
    existing_fingerprints = sorted({_item_fingerprint(item) for item in node_items if _item_fingerprint(item)})
    suggestions = suggestions_by_family.get(family_id) or []
    status = "GENERATION_PACKET_READY" if not any(f["severity"] in FAIL_SEVERITIES for f in findings) else "BLOCKED"
    return {
        "schema_version": "2026-07-23.codex-admin.production-plan.v1",
        "status": status,
        "subject": subject,
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_path": _relative(root, resolved_bank_path),
        "design_brief_id": design_brief.get("report_id"),
        "design_brief_path": _relative(root, resolved_brief_path),
        "node_id": node_id,
        "node_name": (graph_nodes.get(node_id) or {}).get("name"),
        "family_id": family_id,
        "family_name": (families.get(family_id) or {}).get("family_name"),
        "requested_count": requested_count,
        "max_attempts_per_question": max_attempts,
        "slot_id": slot_requirement.get("slot_id") if slot_requirement else "",
        "question_requirement_id": slot_requirement.get("question_requirement_id") if slot_requirement else "",
        "bounded_candidate_packet": {
            "node_capability": blueprint.get("node_capability"),
            "scope_in": blueprint.get("scope_in") or [],
            "scope_out": blueprint.get("scope_out") or [],
            "family_plan_entry": family_entry,
            "question_requirement": slot_requirement,
            "expert_suggestions": suggestions,
            "existing_structure_fingerprints": existing_fingerprints[:30],
            "review_must_reject": blueprint.get("review_must_reject") or [],
            "generation_policy": blueprint.get("generation_policy") or {},
        },
        "allowed_next_agent": "question_designer_agent",
        "candidate_authority": "candidate_only",
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("code", ""))),
        "next_actions": ["generate_candidate_from_packet"] if status == "GENERATION_PACKET_READY" else ["repair_design_brief_or_family_selection"],
    }


def build_generation_plan_batch(
    *,
    root: Path,
    node_id: str,
    requirement_plan_path: Path,
    version: str = "v18",
    subject: str = "math",
    family_id: str = "",
    design_brief_path: Path | None = None,
    bank_path: Path | None = None,
    limit: int = 20,
    max_attempts: int = 3,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise AdminProductionError("ADMIN_PRODUCTION_PLAN_BATCH_LIMIT_MUST_BE_1_TO_100")
    requirement_plan = _load_requirement_plan(root, requirement_plan_path)
    paths = AdminPaths(root=root)
    inherited_bank_path = str(requirement_plan.get("question_bank_path") or "")
    if bank_path is not None and inherited_bank_path:
        explicit_resolved = paths.resolve(bank_path).resolve()
        inherited_resolved = paths.resolve(Path(inherited_bank_path)).resolve()
        if explicit_resolved != inherited_resolved:
            raise AdminProductionError("ADMIN_PRODUCTION_QUESTION_BANK_PATH_MISMATCH")
    effective_bank_path = bank_path or (Path(inherited_bank_path) if inherited_bank_path else None)
    resolved_bank_path = _question_bank_path(paths, version, bank_path=effective_bank_path)
    pseudo_item = {"id": "", "node_id": node_id}
    findings: list[dict[str, str]] = []
    if requirement_plan.get("status") != "REQUIREMENT_PLAN_READY":
        findings.append(_finding("P1", "requirement_plan_not_ready", "requirement plan 未通过，不能批量生成 production plan。", item=pseudo_item))
    if requirement_plan.get("node_id") != node_id:
        findings.append(_finding("P1", "requirement_plan_node_mismatch", "requirement plan 与目标节点不一致。", item=pseudo_item))

    slots = [
        dict(slot)
        for slot in requirement_plan.get("question_requirements") or []
        if not family_id or slot.get("family_id") == family_id
    ]
    if not slots:
        findings.append(_finding("P1", "no_requirement_slots_selected", "没有选中任何逐题 requirement slot。", item=pseudo_item))
    selected_slots = slots[:limit]
    resolved_brief_path = design_brief_path or Path(str(requirement_plan.get("design_brief_path") or ""))
    plans = []
    if not any(f["severity"] in FAIL_SEVERITIES for f in findings):
        for slot in selected_slots:
            plans.append(
                build_generation_plan(
                    root=root,
                    node_id=node_id,
                    family_id=str(slot.get("family_id") or ""),
                    version=version,
                    subject=subject,
                    design_brief_path=resolved_brief_path,
                    requirement_plan_path=requirement_plan_path,
                    bank_path=resolved_bank_path,
                    slot_id=str(slot.get("slot_id") or ""),
                    requested_count=1,
                    max_attempts=max_attempts,
                )
            )

    plan_batch_sha256 = _digest_json([
        {
            "slot_id": plan.get("slot_id"),
            "question_requirement_id": plan.get("question_requirement_id"),
            "status": plan.get("status"),
        }
        for plan in plans
    ])
    status = "PLAN_BATCH_READY" if plans and not any(f["severity"] in FAIL_SEVERITIES for f in findings) else "BLOCKED"
    return {
        "schema_version": "2026-07-23.codex-admin.production-plan-batch.v1",
        "status": status,
        "subject": subject,
        "question_bank_path": _relative(root, resolved_bank_path),
        "node_id": node_id,
        "node_name": requirement_plan.get("node_name"),
        "family_id": family_id,
        "requirement_plan_path": _relative(root, requirement_plan_path if requirement_plan_path.is_absolute() else root / requirement_plan_path),
        "design_brief_id": requirement_plan.get("design_brief_id"),
        "design_brief_path": str(resolved_brief_path),
        "requested_slot_count": len(slots),
        "selected_slot_count": len(selected_slots),
        "plan_count": len(plans),
        "plan_batch_sha256": plan_batch_sha256,
        "generation_plans": plans,
        "generation_plan_paths": [],
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("code", ""))),
        "next_actions": ["run_batch"] if status == "PLAN_BATCH_READY" else ["repair_requirement_plan_or_filter"],
    }


def validate_candidate_against_brief(
    *,
    root: Path,
    candidate: dict[str, Any],
    design_brief: dict[str, Any],
    design_brief_path: Path | None = None,
    version: str = "v18",
    subject: str = "math",
    required_family_id: str | None = None,
    required_slot: dict[str, Any] | None = None,
    previous_rejection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    item = _candidate_item(candidate)
    lineage = _lineage(item)
    family_id = _family_id(item)
    node_id = str(item.get("node_id") or "")
    suggestions_by_family = _brief_family_suggestions(design_brief)
    findings: list[dict[str, str]] = []

    for field in REQUIRED_ITEM_FIELDS:
        if field not in item or item.get(field) in (None, ""):
            findings.append(_finding("P1", f"missing_{field}", f"候选题缺少必填字段：{field}。", item=item))
        elif item.get(field) == [] and field not in REQUIRED_ITEM_FIELDS_ALLOW_EMPTY_LIST:
            findings.append(_finding("P1", f"missing_{field}", f"候选题缺少必填字段：{field}。", item=item))
    for field in REQUIRED_LINEAGE_FIELDS:
        if not lineage.get(field):
            findings.append(_finding("P1", f"missing_lineage_{field}", f"候选题缺少生产 lineage：{field}。", item=item))

    if lineage.get("design_brief_id") != design_brief.get("report_id"):
        findings.append(_finding("P1", "design_brief_lineage_mismatch", "候选题没有绑定当前专家设计 brief。", item=item))
    if node_id != design_brief.get("node_id"):
        findings.append(_finding("P1", "candidate_node_mismatch", "候选题节点与专家 brief 不一致。", item=item))
    if required_family_id and family_id != required_family_id:
        findings.append(_finding("P1", "candidate_family_mismatch", "候选题题型家族与本次生产计划不一致。", item=item))
    if family_id not in suggestions_by_family:
        findings.append(_finding("P1", "candidate_family_not_in_design_brief", "候选题题型家族未被专家 brief 覆盖。", item=item))
    if required_slot:
        lineage_slot_id = str(lineage.get("slot_id") or "")
        lineage_requirement_id = str(lineage.get("question_requirement_id") or "")
        if lineage_slot_id != str(required_slot.get("slot_id") or ""):
            findings.append(_finding("P1", "candidate_slot_mismatch", "候选题没有绑定本次逐题 requirement slot。", item=item))
        if lineage_requirement_id != str(required_slot.get("question_requirement_id") or ""):
            findings.append(_finding("P1", "candidate_requirement_mismatch", "候选题没有绑定本次 question_requirement_id。", item=item))
        if family_id != str(required_slot.get("family_id") or ""):
            findings.append(_finding("P1", "candidate_slot_family_mismatch", "候选题题型家族与 slot 要求不一致。", item=item))
        if str(item.get("difficulty") or item.get("variant_level") or "") != str(required_slot.get("difficulty") or ""):
            findings.append(_finding("P1", "candidate_slot_difficulty_mismatch", "候选题难度与 slot 要求不一致。", item=item))
        slot_evidence = str(required_slot.get("evidence_goal") or "")
        candidate_evidence_text = "\n".join(str(value) for value in item.get("required_evidence") or []) + "\n" + str(lineage.get("evidence_goal") or item.get("evidence_goal") or "")
        if slot_evidence and slot_evidence not in candidate_evidence_text:
            findings.append(_finding("P1", "candidate_slot_evidence_mismatch", "候选题没有覆盖 slot 的目标证据。", item=item))
        for field in ("support_only", "not_for_activation", "exclude_from_coverage"):
            if item.get(field) is not required_slot.get(field):
                findings.append(
                    _finding(
                        "P1",
                        f"candidate_{field}_mismatch",
                        f"候选题没有继承逐题 requirement 的可信 {field} 范围。",
                        item=item,
                    )
                )
        expected_secondary = list(required_slot.get("secondary_nodes") or [])
        if item.get("secondary_node_ids") != expected_secondary:
            findings.append(
                _finding(
                    "P1",
                    "candidate_secondary_nodes_mismatch",
                    "候选题没有把逐题 requirement 的 secondary_nodes 绑定为可信 secondary_node_ids。",
                    item=item,
                )
            )

    blueprint = blueprints.get(node_id) or {}
    family_entry = next((entry for entry in blueprint.get("family_plan") or [] if entry.get("family_id") == family_id), {})
    if family_entry:
        allowed_difficulties = set(family_entry.get("difficulty") or [])
        difficulty = str(item.get("difficulty") or item.get("variant_level") or "")
        if allowed_difficulties and difficulty not in allowed_difficulties:
            findings.append(_finding("P1", "difficulty_not_in_family_plan", "候选题难度不在节点 family_plan 允许范围。", item=item))
        planned_evidence = set(family_entry.get("required_evidence") or [])
        item_evidence = set(str(value) for value in item.get("required_evidence") or [])
        if required_slot is None and planned_evidence and not (planned_evidence & item_evidence):
            findings.append(_finding("P1", "required_evidence_not_aligned", "候选题 required_evidence 与节点蓝图没有可追踪重合。", item=item))

    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    if item.get("activation_eligible") or quality.get("activation_eligible"):
        findings.append(_finding("P0", "candidate_self_authorizes_activation", "候选题不能自声明 activation_eligible。", item=item))
    if str(item.get("review_status") or quality.get("review_status") or "") in {"staged", "active", "qa_passed"}:
        findings.append(_finding("P0", "candidate_self_declares_late_state", "候选题不能自声明 staged/active/qa_passed。", item=item))
    if _score_point_sum(item) != 10:
        findings.append(_finding("P1", "score_points_not_10", "候选题 key_score_points 分值合计必须为 10。", item=item))
    if not _item_fingerprint(item):
        findings.append(_finding("P1", "missing_structure_fingerprint", "候选题缺少结构指纹，不能去重或避免雷同。", item=item))

    if previous_rejection:
        prior_codes = {
            str(f.get("code") or "")
            for f in previous_rejection.get("findings") or []
            if str(f.get("severity") or "") in FAIL_SEVERITIES
        }
        carried_codes = set(str(code) for code in lineage.get("previous_rejection_codes") or item.get("previous_rejection_codes") or [])
        if prior_codes and not prior_codes.issubset(carried_codes):
            findings.append(_finding("P1", "missing_rejection_reason_lineage", "重出/返修题必须携带上一轮驳回原因，避免重复犯同一错误。", item=item))

    findings.extend(
        _finding_from_expert(finding)
        for finding in _review_item(item, graph_nodes=graph_nodes, blueprints=blueprints, families=families)
    )

    status = _status_from_findings(findings)
    candidate_digest = _digest_json(item)
    return {
        "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
        "status": status,
        "subject": subject,
        "question_bank_version": version,
        "design_brief_id": design_brief.get("report_id"),
        "design_brief_path": _relative(root, design_brief_path) if design_brief_path else "",
        "slot_id": required_slot.get("slot_id") if required_slot else str(lineage.get("slot_id") or ""),
        "question_requirement_id": required_slot.get("question_requirement_id") if required_slot else str(lineage.get("question_requirement_id") or ""),
        "question_requirement_sha256": _digest_json(required_slot or {}),
        "item_id": str(item.get("id") or ""),
        "node_id": node_id,
        "family_id": family_id,
        "candidate_sha256": candidate_digest,
        "requirement_scope": {
            "support_only": bool((required_slot or {}).get("support_only")),
            "not_for_activation": bool((required_slot or {}).get("not_for_activation")),
            "exclude_from_coverage": bool((required_slot or {}).get("exclude_from_coverage")),
            "secondary_nodes": list((required_slot or {}).get("secondary_nodes") or []),
        },
        "machine_checked": True,
        "staging_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("profile", ""), f.get("code", ""))),
        "next_actions": ["expert_review"] if status in PASS_MACHINE_STATUSES else ["regenerate_candidate"],
    }


def build_candidate_check_from_paths(
    *,
    root: Path,
    candidate_path: Path,
    design_brief_path: Path,
    version: str = "v18",
    subject: str = "math",
    required_family_id: str | None = None,
    requirement_plan_path: Path | None = None,
    slot_id: str | None = None,
    previous_rejection_path: Path | None = None,
) -> dict[str, Any]:
    design_brief, resolved_brief_path = resolve_design_brief(root, design_brief_path=design_brief_path)
    candidate_payload = _load_json_file(root, candidate_path)
    previous_rejection = _load_json_file(root, previous_rejection_path) if previous_rejection_path else None
    required_slot = None
    if slot_id:
        if requirement_plan_path is None:
            raise AdminProductionError("ADMIN_PRODUCTION_SLOT_REQUIRES_REQUIREMENT_PLAN")
        requirement_plan = _load_requirement_plan(root, requirement_plan_path)
        required_slot = _requirement_by_slot(requirement_plan, slot_id)
        if required_slot is None:
            raise AdminProductionError(f"ADMIN_PRODUCTION_UNKNOWN_SLOT: {slot_id}")
        required_family_id = str(required_slot.get("family_id") or required_family_id or "")
    return validate_candidate_against_brief(
        root=root,
        candidate=candidate_payload,
        design_brief=design_brief,
        design_brief_path=resolved_brief_path,
        version=version,
        subject=subject,
        required_family_id=required_family_id,
        required_slot=required_slot,
        previous_rejection=previous_rejection,
    )


def decide_loop_next_action(
    *,
    machine_report: dict[str, Any],
    expert_report: dict[str, Any] | None = None,
    generation_attempt: int | None = None,
    max_attempts: int = 3,
    subject: str = "math",
) -> dict[str, Any]:
    attempt = int(generation_attempt or machine_report.get("generation_attempt") or 1)
    item = {"id": machine_report.get("item_id"), "node_id": machine_report.get("node_id")}
    findings: list[dict[str, str]] = []
    machine_status = str(machine_report.get("status") or "")
    expert_status = str((expert_report or {}).get("status") or (expert_report or {}).get("overall_status") or "")
    expert_counts = (expert_report or {}).get("finding_counts") or {}

    scoped_expert_result = expert_status in {"PASS_WITH_SCOPE", "pass_with_scope"}
    blocking_codes = [
        str(finding.get("code") or "")
        for finding in list(machine_report.get("findings") or []) + list((expert_report or {}).get("findings") or [])
        if (str(finding.get("severity") or "") in FAIL_SEVERITIES or scoped_expert_result) and finding.get("code")
    ]
    machine_blocks = machine_status not in PASS_MACHINE_STATUSES
    expert_blocks = bool(expert_report) and (
        expert_status in BLOCKING_EXPERT_STATUSES
        or scoped_expert_result
        or bool(expert_counts.get("P0") or expert_counts.get("P1"))
    )
    if machine_blocks:
        if machine_status in {"BLOCKED_MODEL_ERROR", "BLOCKED_MODEL_NOT_CONFIGURED"}:
            findings.append(
                _finding(
                    "P1",
                    machine_status.lower(),
                    "模型调用未完成，workflow 必须先修复模型路由/超时，不能当成候选题质量问题。",
                    item=item,
                )
            )
        else:
            findings.append(_finding("P1", "machine_check_blocks_loop", "机器检查未通过，workflow 必须回到命题 Agent。", item=item))
    if expert_blocks:
        code = "model_expert_review_retry_required" if expert_status in RETRYABLE_MODEL_REVIEW_STATUSES else "expert_review_blocks_loop"
        message = "模型专家审核未完成，workflow 必须停在模型审核重试/配置修复，不能消耗命题 attempt。" if expert_status in RETRYABLE_MODEL_REVIEW_STATUSES else "专家审核未通过，workflow 必须回到命题 Agent。"
        findings.append(_finding("P1", code, message, item=item))

    if machine_blocks or expert_blocks:
        if machine_status in RETRYABLE_MODEL_REVIEW_STATUSES:
            next_action = "retry_or_repair_model_route"
            status = machine_status
        elif expert_status in RETRYABLE_MODEL_REVIEW_STATUSES:
            next_action = "retry_or_repair_model_expert_review"
            status = expert_status
        elif attempt >= max_attempts:
            next_action = "escalate_human_design_review"
            status = "LOOP_BLOCKED_MAX_ATTEMPTS"
        else:
            next_action = "regenerate_candidate"
            status = "LOOP_REGENERATE"
    elif not expert_report:
        next_action = "expert_review"
        status = "LOOP_CONTINUE_TO_EXPERT_REVIEW"
    else:
        next_action = "qa_review"
        status = "LOOP_CONTINUE_TO_QA"

    return {
        "schema_version": "2026-07-23.codex-admin.production-loop-decision.v1",
        "status": status,
        "subject": subject,
        "item_id": machine_report.get("item_id"),
        "node_id": machine_report.get("node_id"),
        "family_id": machine_report.get("family_id"),
        "slot_id": machine_report.get("slot_id"),
        "question_requirement_id": machine_report.get("question_requirement_id"),
        "generation_attempt": attempt,
        "max_attempts": max_attempts,
        "next_action": next_action,
        "blocking_rejection_codes": sorted(set(blocking_codes)),
        "regeneration_input": {
            "previous_rejection_codes": sorted(set(blocking_codes)),
            "previous_machine_report_sha256": _digest_json(machine_report),
            "previous_expert_report_sha256": _digest_json(expert_report) if expert_report else "",
        } if next_action == "regenerate_candidate" else {},
        "attempt_accounting": {
            "provider_retry_required": next_action in {"retry_or_repair_model_route", "retry_or_repair_model_expert_review"},
            "content_regeneration_consumed": next_action == "regenerate_candidate",
        },
        "staging_allowed": False,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": findings,
    }


def _qa_scope_is_structured(scope: Any) -> bool:
    if not isinstance(scope, dict) or set(scope) != QA_SCOPE_KEYS:
        return False
    if not all(isinstance(scope.get(key), bool) for key in ("support_only", "not_for_activation", "exclude_from_coverage")):
        return False
    reasons = scope.get("reasons")
    return isinstance(reasons, list) and all(isinstance(reason, str) and reason.strip() for reason in reasons)


def decide_staging_from_receipts(
    *,
    root: Path,
    artifact_root: Path | None = None,
    machine_report: dict[str, Any],
    expert_report: dict[str, Any],
    model_expert_report: dict[str, Any] | None = None,
    qa_contract_report: dict[str, Any] | None = None,
    semantic_qa_report: dict[str, Any] | None = None,
    qa_report: dict[str, Any] | None = None,
    subject: str = "math",
) -> dict[str, Any]:
    machine_report = _normalize_machine_report(machine_report)
    receipt_root = artifact_root or root
    if qa_report:
        if str(qa_report.get("gate_type") or "") == "deterministic_contract_check" and qa_contract_report is None:
            qa_contract_report = qa_report
        elif semantic_qa_report is None:
            semantic_qa_report = qa_report

    findings: list[dict[str, str]] = []
    item = {"id": machine_report.get("item_id"), "node_id": machine_report.get("node_id")}
    expected_identity = _receipt_identity(machine_report)
    expected_candidate_sha = str(machine_report.get("candidate_sha256") or "")
    machine_status = str(machine_report.get("status") or "")
    if not _schema_matches(machine_report, {"2026-07-23.codex-admin.production-candidate-check.v1"}):
        findings.append(_finding("P1", "machine_check_schema_invalid", "机器检查 receipt schema 不正确，不能进入 staged。", item=item))
    if machine_status not in PASS_MACHINE_STATUSES:
        findings.append(_finding("P1", "machine_check_not_passed", "机器检查未通过，候选题必须重出或返修。", item=item))
    if not expected_candidate_sha:
        findings.append(_finding("P1", "machine_check_missing_candidate_sha256", "机器检查缺少 candidate_sha256，不能绑定候选题 payload。", item=item))

    expert_status = str(expert_report.get("status") or expert_report.get("overall_status") or "")
    expert_counts = expert_report.get("finding_counts") or {}
    if not _schema_matches(expert_report, {"2026-07-23.codex-admin.candidate-expert-review.v1"}):
        findings.append(_finding("P1", "expert_review_schema_invalid", "专家审核 receipt schema 不正确，不能进入 staged。", item=item))
    if _receipt_identity(expert_report) != expected_identity:
        findings.append(_finding("P1", "expert_review_identity_mismatch", "专家审核与机器检查不是同一道候选题。", item=item))
    if str(expert_report.get("candidate_sha256") or "") != expected_candidate_sha:
        findings.append(_finding("P1", "expert_review_candidate_sha256_mismatch", "专家审核 candidate_sha256 与机器检查不一致。", item=item))
    if not str(expert_report.get("source_file_sha256") or ""):
        findings.append(_finding("P1", "expert_review_missing_source_file_sha256", "专家审核缺少 source_file_sha256。", item=item))
    if not _receipt_source_path(expert_report):
        findings.append(_finding("P1", "expert_review_missing_source_path", "专家审核缺少候选题 source_path。", item=item))
    if expert_status != "PASS" or expert_counts.get("P0") or expert_counts.get("P1"):
        findings.append(_finding("P1", "expert_review_blocking_findings", "确定性专家审核必须完整 PASS。", item=item))

    model_expert_report = model_expert_report or {}
    model_expert_status = str(model_expert_report.get("status") or model_expert_report.get("overall_status") or "")
    model_expert_counts = model_expert_report.get("finding_counts") or {}
    model_expert_scope = model_expert_report.get("scope") if isinstance(model_expert_report.get("scope"), dict) else {}
    if not model_expert_report:
        findings.append(_finding("P1", "missing_model_expert_board_review", "缺少模型专家 board receipt。", item=item))
    else:
        if not _schema_matches(model_expert_report, {"2026-07-23.codex-admin.model-expert-board-review.v1"}):
            findings.append(_finding("P1", "model_expert_board_review_schema_invalid", "模型专家 board receipt schema 不正确。", item=item))
        if _receipt_identity(model_expert_report) != expected_identity:
            findings.append(_finding("P1", "model_expert_board_review_identity_mismatch", "模型专家 board 与机器检查不是同一道候选题。", item=item))
        if str(model_expert_report.get("candidate_sha256") or "") != expected_candidate_sha:
            findings.append(_finding("P1", "model_expert_board_review_candidate_sha256_mismatch", "模型专家 board candidate_sha256 与机器检查不一致。", item=item))
        if str(model_expert_report.get("question_requirement_id") or "") != str(machine_report.get("question_requirement_id") or ""):
            findings.append(_finding("P1", "model_expert_board_review_requirement_id_mismatch", "模型专家 board 未绑定当前 question_requirement_id。", item=item))
        if str(model_expert_report.get("slot_id") or "") != str(machine_report.get("slot_id") or ""):
            findings.append(_finding("P1", "model_expert_board_review_slot_id_mismatch", "模型专家 board 未绑定当前 slot_id。", item=item))
        expected_requirement_sha = str(machine_report.get("question_requirement_sha256") or "")
        if expected_requirement_sha and str(model_expert_report.get("question_requirement_sha256") or "") != expected_requirement_sha:
            findings.append(_finding("P1", "model_expert_board_review_requirement_sha256_mismatch", "模型专家 board 使用的逐题 requirement 内容与机器检查不一致。", item=item))
        if not str(model_expert_report.get("source_file_sha256") or ""):
            findings.append(_finding("P1", "model_expert_board_review_missing_source_file_sha256", "模型专家 board 缺少 source_file_sha256。", item=item))
        if not _receipt_has_written_artifact(model_expert_report, ("model_expert_review_json_path",)):
            findings.append(_finding("P1", "model_expert_board_review_missing_artifact_lineage", "模型专家 board 缺少写入产物 lineage。", item=item))
        if str(model_expert_report.get("provider_mode") or "") != "live_model":
            findings.append(_finding("P1", "model_expert_board_review_not_live_model", "模型专家 board 必须来自 live_model。", item=item))
        if not isinstance(model_expert_report.get("route"), dict) or not isinstance(model_expert_report.get("prompt_meta"), dict):
            findings.append(_finding("P1", "model_expert_board_review_missing_route_prompt_meta", "模型专家 board 缺少 route 或 prompt_meta。", item=item))
        if model_expert_status in BLOCKING_EXPERT_STATUSES or model_expert_counts.get("P0") or model_expert_counts.get("P1"):
            findings.append(_finding("P1", "model_expert_board_review_blocking_findings", "模型专家 board 存在阻断问题。", item=item))
        elif model_expert_status == "PASS_WITH_SCOPE":
            findings.append(_finding("P1", "model_expert_scope_not_staging_eligible", "模型专家 board 的 scoped verdict 不能作为普通 staged/coverage PASS。", item=item))
        elif model_expert_status != "PASS":
            findings.append(_finding("P1", "model_expert_board_review_status_invalid", "模型专家 board 必须完整 PASS。", item=item))

    qa_contract_report = qa_contract_report or {}
    contract_status = str(qa_contract_report.get("status") or "")
    contract_counts = qa_contract_report.get("finding_counts") or {}
    if not qa_contract_report:
        findings.append(_finding("P1", "missing_qa_contract_check", "缺少确定性 QA contract check receipt。", item=item))
    else:
        if not _schema_matches(qa_contract_report, {"2026-07-24.codex-admin.candidate-qa-contract-check.v1"}):
            findings.append(_finding("P1", "qa_contract_check_schema_invalid", "QA contract check schema 不正确。", item=item))
        if str(qa_contract_report.get("gate_type") or "") != "deterministic_contract_check":
            findings.append(_finding("P1", "qa_contract_check_gate_type_invalid", "QA contract receipt 未声明 deterministic_contract_check。", item=item))
        if _receipt_identity(qa_contract_report) != expected_identity:
            findings.append(_finding("P1", "qa_contract_check_identity_mismatch", "QA contract check 与机器检查不是同一道候选题。", item=item))
        if str(qa_contract_report.get("candidate_sha256") or "") != expected_candidate_sha:
            findings.append(_finding("P1", "qa_contract_check_candidate_sha256_mismatch", "QA contract check candidate_sha256 不一致。", item=item))
        if not str(qa_contract_report.get("source_file_sha256") or "") or not _receipt_source_path(qa_contract_report):
            findings.append(_finding("P1", "qa_contract_check_missing_source_lineage", "QA contract check 缺少 source lineage。", item=item))
        if not _receipt_has_written_artifact(qa_contract_report, ("qa_contract_check_json_path",)):
            findings.append(_finding("P1", "qa_contract_check_missing_artifact_lineage", "QA contract check 缺少写入产物 lineage。", item=item))
        if contract_status != "PASS" or contract_counts.get("P0") or contract_counts.get("P1"):
            findings.append(_finding("P1", "qa_contract_check_blocking_findings", "QA contract check 未完整通过。", item=item))

    semantic_qa_report = semantic_qa_report or {}
    semantic_status = str(semantic_qa_report.get("status") or "")
    semantic_counts = semantic_qa_report.get("finding_counts") or {}
    semantic_scope = semantic_qa_report.get("scope") if isinstance(semantic_qa_report.get("scope"), dict) else {}
    if not semantic_qa_report:
        findings.append(_finding("P1", "missing_semantic_qa_review", "缺少 live-model 语义 QA receipt。", item=item))
    else:
        if not _schema_matches(semantic_qa_report, {"2026-07-23.codex-admin.candidate-qa-review.v1"}):
            findings.append(_finding("P1", "semantic_qa_schema_invalid", "语义 QA receipt schema 不正确。", item=item))
        if str(semantic_qa_report.get("gate_type") or "") != "live_model_semantic_qa":
            findings.append(_finding("P1", "semantic_qa_gate_type_invalid", "语义 QA receipt 未声明 live_model_semantic_qa。", item=item))
        if _receipt_identity(semantic_qa_report) != expected_identity:
            findings.append(_finding("P1", "semantic_qa_identity_mismatch", "语义 QA 与机器检查不是同一道候选题。", item=item))
        if str(semantic_qa_report.get("candidate_sha256") or "") != expected_candidate_sha:
            findings.append(_finding("P1", "semantic_qa_candidate_sha256_mismatch", "语义 QA candidate_sha256 不一致。", item=item))
        if not str(semantic_qa_report.get("source_file_sha256") or "") or not _receipt_source_path(semantic_qa_report):
            findings.append(_finding("P1", "semantic_qa_missing_source_lineage", "语义 QA 缺少 source lineage。", item=item))
        if not _receipt_has_written_artifact(semantic_qa_report, ("qa_json_path",)):
            findings.append(_finding("P1", "semantic_qa_missing_artifact_lineage", "语义 QA 缺少写入产物 lineage。", item=item))
        expected_contract_digest = _receipt_artifact_digest(
            qa_contract_report,
            ("qa_contract_check_json_sha256",),
        )
        if str(semantic_qa_report.get("qa_contract_report_sha256") or "") != expected_contract_digest:
            findings.append(_finding("P1", "semantic_qa_contract_digest_mismatch", "语义 QA 未绑定当前 contract-check artifact。", item=item))
        if str(semantic_qa_report.get("provider_mode") or "") != "live_model":
            findings.append(_finding("P1", "semantic_qa_not_live_model", "语义 QA 必须来自 live_model。", item=item))
        route = semantic_qa_report.get("route") if isinstance(semantic_qa_report.get("route"), dict) else {}
        prompt_meta = semantic_qa_report.get("prompt_meta") if isinstance(semantic_qa_report.get("prompt_meta"), dict) else {}
        if not route.get("raw_response_sha256") or not route.get("structured_json_mode"):
            findings.append(_finding("P1", "semantic_qa_missing_route_evidence", "语义 QA 缺少真实模型 response/mode 证据。", item=item))
        if not prompt_meta.get("rendered_prompt_sha256") or not prompt_meta.get("response_schema_sha256"):
            findings.append(_finding("P1", "semantic_qa_missing_prompt_evidence", "语义 QA 缺少 prompt/schema digest。", item=item))
        normalization = semantic_qa_report.get("status_normalization") if isinstance(semantic_qa_report.get("status_normalization"), dict) else {}
        if normalization.get("authority") != "deterministic_from_profile_verdicts" or normalization.get("model_overall_status_is_advisory") is not True:
            findings.append(_finding("P1", "semantic_qa_normalization_evidence_invalid", "语义 QA 缺少确定性 profile verdict 归一化证据。", item=item))

        profile_reviews = semantic_qa_report.get("profile_reviews") if isinstance(semantic_qa_report.get("profile_reviews"), list) else []
        profile_counts = Counter(str(review.get("profile") or "") for review in profile_reviews if isinstance(review, dict))
        if profile_counts != Counter({profile: 1 for profile in REQUIRED_SEMANTIC_QA_PROFILES}):
            findings.append(_finding("P1", "semantic_qa_profile_coverage_invalid", "语义 QA profile verdict 不完整或重复。", item=item))
        profile_statuses = {
            str(review.get("status") or "")
            for review in profile_reviews
            if isinstance(review, dict)
        }
        hard_blockers = semantic_qa_report.get("hard_blockers") if isinstance(semantic_qa_report.get("hard_blockers"), dict) else {}
        if set(hard_blockers) != REQUIRED_SEMANTIC_HARD_BLOCKERS:
            findings.append(_finding("P1", "semantic_qa_hard_blocker_coverage_invalid", "语义 QA hard blockers 不完整。", item=item))
        elif any(not isinstance(entry, dict) or entry.get("detected") is not False for entry in hard_blockers.values()):
            findings.append(_finding("P1", "semantic_qa_hard_blocker_detected", "语义 QA 检出必须阻断的内容问题。", item=item))

        if semantic_status in BLOCKING_EXPERT_STATUSES or semantic_counts.get("P0") or semantic_counts.get("P1"):
            findings.append(_finding("P1", "semantic_qa_blocking_findings", "语义 QA 存在阻断问题。", item=item))
        elif semantic_status == "PASS_WITH_SCOPE":
            if not _qa_scope_is_structured(semantic_scope) or not any(
                bool(semantic_scope.get(key)) for key in ("support_only", "not_for_activation", "exclude_from_coverage")
            ) or not semantic_scope.get("reasons"):
                findings.append(_finding("P1", "semantic_qa_scope_invalid", "PASS_WITH_SCOPE 缺少完整结构化 restrictions。", item=item))
            else:
                findings.append(_finding("P2", "semantic_qa_scoped_not_staging_eligible", "受限语义结果只保留为 support，不进入 staged 或 coverage。", item=item))
        elif semantic_status == "PASS":
            if profile_statuses != {"pass"}:
                findings.append(_finding("P1", "semantic_qa_pass_profile_inconsistent", "语义 QA status=PASS 但 profile verdict 并非全部 pass。", item=item))
            if not _qa_scope_is_structured(semantic_scope) or any(
                bool(semantic_scope.get(key)) for key in ("support_only", "not_for_activation", "exclude_from_coverage")
            ) or semantic_scope.get("reasons"):
                findings.append(_finding("P1", "semantic_qa_pass_scope_inconsistent", "完整 PASS 不能携带 scope restrictions。", item=item))
        else:
            findings.append(_finding("P1", "semantic_qa_status_invalid", "语义 QA 必须是 PASS、PASS_WITH_SCOPE 或阻断状态。", item=item))

    review_source_paths = [
        _receipt_source_path(report)
        for report in (expert_report, model_expert_report, qa_contract_report, semantic_qa_report)
        if _receipt_source_path(report)
    ]
    if len(set(review_source_paths)) > 1:
        findings.append(_finding("P1", "review_receipt_source_path_mismatch", "各审核 receipt 指向的候选题文件不一致。", item=item))
    for report, label in (
        (expert_report, "expert_review"),
        (model_expert_report, "model_expert_board_review"),
        (qa_contract_report, "qa_contract_check"),
        (semantic_qa_report, "semantic_qa_review"),
    ):
        source_path = _receipt_source_path(report)
        expected_source_sha = str(report.get("source_file_sha256") or "")
        if not source_path or not expected_source_sha:
            continue
        resolved_source_path = Path(source_path)
        if not resolved_source_path.is_absolute():
            resolved_source_path = root / resolved_source_path
        if not resolved_source_path.exists():
            findings.append(_finding("P1", f"{label}_source_file_missing", f"{label} 指向的候选题源文件不存在。", item=item))
            continue
        actual_source_sha = hashlib.sha256(resolved_source_path.read_bytes()).hexdigest()
        if actual_source_sha != expected_source_sha:
            findings.append(_finding("P1", f"{label}_source_file_sha256_mismatch", f"{label} source_file_sha256 与当前文件内容不一致。", item=item))

    requirement_scope = (
        machine_report.get("requirement_scope")
        if isinstance(machine_report.get("requirement_scope"), dict)
        else {}
    )
    if not all(
        isinstance(requirement_scope.get(key), bool)
        for key in ("support_only", "not_for_activation", "exclude_from_coverage")
    ) or not isinstance(requirement_scope.get("secondary_nodes"), list):
        findings.append(
            _finding(
                "P1",
                "machine_check_requirement_scope_invalid",
                "机器检查缺少完整可信的 requirement execution scope。",
                item=item,
            )
        )
    combined_scope = {
        "support_only": bool(requirement_scope.get("support_only")) or bool(model_expert_scope.get("support_only")) or bool(semantic_scope.get("support_only")),
        "not_for_activation": bool(requirement_scope.get("not_for_activation")) or bool(model_expert_scope.get("not_for_activation")) or bool(semantic_scope.get("not_for_activation")),
        "exclude_from_coverage": bool(requirement_scope.get("exclude_from_coverage")) or bool(model_expert_scope.get("exclude_from_coverage")) or bool(semantic_scope.get("exclude_from_coverage")),
        "reasons": list(dict.fromkeys([
            *(
                ["canonical_requirement_scope"]
                if any(
                    bool(requirement_scope.get(key))
                    for key in ("support_only", "not_for_activation", "exclude_from_coverage")
                )
                else []
            ),
            *[str(reason) for reason in model_expert_scope.get("reasons") or [] if str(reason).strip()],
            *[str(reason) for reason in semantic_scope.get("reasons") or [] if str(reason).strip()],
        ])),
    }
    has_blocker = any(finding["severity"] in FAIL_SEVERITIES for finding in findings)
    scoped_only = any(
        bool(combined_scope.get(key))
        for key in ("support_only", "not_for_activation", "exclude_from_coverage")
    ) and not has_blocker
    status = "NEEDS_REGENERATION" if has_blocker else "SCOPED_NOT_STAGED" if scoped_only else "STAGED_READY"
    machine_sha = _receipt_artifact_digest(machine_report, ("production_json_sha256",))
    expert_sha = _receipt_artifact_digest(expert_report, ("review_json_sha256",))
    model_expert_sha = _receipt_artifact_digest(model_expert_report, ("model_expert_review_json_sha256",))
    qa_contract_sha = _receipt_artifact_digest(qa_contract_report, ("qa_contract_check_json_sha256",))
    semantic_qa_sha = _receipt_artifact_digest(semantic_qa_report, ("qa_json_sha256",))
    return {
        "schema_version": "2026-07-23.codex-admin.production-staging-decision.v1",
        "status": status,
        "subject": subject,
        "item_id": machine_report.get("item_id"),
        "node_id": machine_report.get("node_id"),
        "family_id": machine_report.get("family_id"),
        "slot_id": machine_report.get("slot_id"),
        "question_requirement_id": machine_report.get("question_requirement_id"),
        "question_requirement_sha256": machine_report.get("question_requirement_sha256"),
        "candidate_sha256": expected_candidate_sha,
        "machine_report_sha256": machine_sha,
        "expert_report_sha256": expert_sha,
        "model_expert_report_sha256": model_expert_sha,
        "qa_contract_report_sha256": qa_contract_sha,
        "qa_report_sha256": semantic_qa_sha,
        "semantic_qa_report_sha256": semantic_qa_sha,
        "qa_contract_check": _review_receipt_summary(
            qa_contract_report,
            role="deterministic_qa_contract_check",
            digest=qa_contract_sha,
            path_keys=("qa_contract_check_json_path",),
            artifact_root=receipt_root,
        ),
        "review_receipts": {
            "machine_check": _review_receipt_summary(
                machine_report,
                role="machine_contract_check",
                digest=machine_sha,
                path_keys=("production_json_path",),
                artifact_root=receipt_root,
            ),
            "deterministic_expert_review": _review_receipt_summary(
                expert_report,
                role="deterministic_expert_review",
                digest=expert_sha,
                path_keys=("review_json_path",),
                artifact_root=receipt_root,
            ),
            "model_expert_board_review": _review_receipt_summary(
                model_expert_report,
                role="live_model_expert_board_review",
                digest=model_expert_sha,
                path_keys=("model_expert_review_json_path",),
                artifact_root=receipt_root,
            ),
            "guanzhi_qa_review": _review_receipt_summary(
                semantic_qa_report,
                role="live_model_semantic_qa_review",
                digest=semantic_qa_sha,
                path_keys=("qa_json_path",),
                artifact_root=receipt_root,
            ),
        },
        "staging_scope": combined_scope,
        "staging_allowed": status == "STAGED_READY",
        "coverage_eligible": status == "STAGED_READY",
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "finding_counts": _findings_by_severity(findings),
        "findings": findings,
        "next_actions": (
            ["stage_candidate"]
            if status == "STAGED_READY"
            else ["retain_as_support_only", "exclude_from_coverage"]
            if status == "SCOPED_NOT_STAGED"
            else ["regenerate_candidate"]
        ),
    }


def decide_staging_from_paths(
    *,
    root: Path,
    machine_report_path: Path,
    expert_report_path: Path,
    model_expert_report_path: Path | None = None,
    qa_contract_report_path: Path | None = None,
    semantic_qa_report_path: Path | None = None,
    qa_report_path: Path | None = None,
    subject: str = "math",
) -> dict[str, Any]:
    machine_report = _load_json_file(root, machine_report_path)
    expert_report = _load_json_file(root, expert_report_path)
    model_expert_report = _load_json_file(root, model_expert_report_path) if model_expert_report_path else None
    qa_contract_report = _load_json_file(root, qa_contract_report_path) if qa_contract_report_path else None
    semantic_qa_report = _load_json_file(root, semantic_qa_report_path) if semantic_qa_report_path else None
    qa_report = _load_json_file(root, qa_report_path) if qa_report_path else None
    return decide_staging_from_receipts(
        root=root,
        machine_report=machine_report,
        expert_report=expert_report,
        model_expert_report=model_expert_report,
        qa_contract_report=qa_contract_report,
        semantic_qa_report=semantic_qa_report,
        qa_report=qa_report,
        subject=subject,
    )


def render_production_report_markdown(report: dict[str, Any]) -> str:
    finding_lines = [
        f"| {finding.get('severity', '')} | {finding.get('profile', '')} | {finding.get('code', '')} | {finding.get('message', '')} |"
        for finding in report.get("findings") or []
    ]
    if not finding_lines:
        finding_lines.append("| | | | |")
    return f"""# Admin Question Production Report

Status: `{report.get('status')}`

Created At: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

Schema: `{report.get('schema_version')}`

Subject: {report.get('subject')}

Item: {report.get('item_id', '')}

Node: {report.get('node_id', '')}

Family: {report.get('family_id', '')}

Staging Allowed: `{report.get('staging_allowed', False)}`

Activation Implication: `{report.get('activation_implication')}`

## Finding Counts

```json
{json.dumps(report.get('finding_counts') or {}, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Findings

| Severity | Profile | Code | Message |
|---|---|---|---|
{chr(10).join(finding_lines)}
"""


def write_production_report(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    report_id_input = "|".join([
        str(report.get("schema_version") or ""),
        str(report.get("status") or ""),
        str(report.get("item_id") or report.get("node_id") or ""),
        str(report.get("slot_id") or ""),
        str(report.get("question_requirement_id") or ""),
        str(report.get("candidate_sha256") or report.get("machine_report_sha256") or report.get("plan_batch_sha256") or ""),
    ])
    report_id = "PROD-" + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    markdown_rel = Path("docs/system/admin_reports/production") / f"{datetime.now(timezone.utc).date()}-{report_id}.md"
    json_rel = Path("data/admin/production") / f"{report_id}.json"
    result = {
        **report,
        "production_report_id": report_id,
        "production_markdown_path": str(markdown_rel),
        "production_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown = render_production_report_markdown(report)
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    result["production_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["production_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result
