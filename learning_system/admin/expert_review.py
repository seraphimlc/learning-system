from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import internal_agents, model_router
from .model_deadline import bind_admin_structured_model_deadline
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


EXPERT_PROFILES = {
    "frontline_math_teacher": {
        "display": "一线初中数学老师",
        "focus": ("grade_fit", "natural_prompt", "teaching_value", "not_insulting"),
    },
    "bridge_diagnosis_teacher": {
        "display": "衔接诊断老师",
        "focus": ("graph_binding", "prerequisite_probe", "cognitive_breakpoint", "low_drill"),
    },
    "stretch_competition_teacher": {
        "display": "拔高/竞赛老师",
        "focus": ("stretch_quality", "not_pseudo_hard", "transfer_value"),
    },
    "assessment_expert": {
        "display": "测评专家",
        "focus": ("required_evidence", "score_points", "mastery_dimension_mapping", "answer_contract"),
    },
    "source_compliance_reviewer": {
        "display": "题源合规 reviewer",
        "focus": ("source_lineage", "capture_policy", "no_commercial_copy"),
    },
}

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "INFO": 3}
FAIL_SEVERITIES = {"P0", "P1"}

FORBIDDEN_CHILD_LEAKS = (
    "agent",
    "Agent",
    "图谱节点",
    "后台",
    "Missing the requested",
    "Add one sentence",
)

LOW_VALUE_PROMPT_MARKERS = (
    "直接计算",
    "口算",
    "竖式",
    "只写答案",
)

PROCESS_REQUIREMENT_MARKERS = (
    "说明",
    "解释",
    "判断",
    "验证",
    "检验",
    "依据",
    "理由",
    "过程",
    "改正",
    "指出",
    "比较",
)

COMPLETE_ANSWER_QUALIFIERS = (
    "完整作答",
    "仍需包含",
    "只代表最终结果",
    "还要说明",
    "需说明",
    "需包含",
    "不能只写",
)

MODEL_EXPERT_BOARD_SCHEMA_VERSION = "2026-07-23.codex-admin.model-expert-board-review.v1"


def _relpath(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExpertFinding:
    severity: str
    profile: str
    item_id: str
    node_id: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "profile": self.profile,
            "item_id": self.item_id,
            "node_id": self.node_id,
            "code": self.code,
            "message": self.message,
        }


def _text_of(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("prompt", "standard_answer", "expected_answer", "answer_format"):
        value = item.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("solution_steps", "required_evidence", "rubric"):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(part) for part in value)
    return "\n".join(parts)


def _add(findings: list[ExpertFinding], severity: str, profile: str, item: dict[str, Any], code: str, message: str) -> None:
    findings.append(
        ExpertFinding(
            severity=severity,
            profile=profile,
            item_id=str(item.get("id") or ""),
            node_id=str(item.get("node_id") or ""),
            code=code,
            message=message,
        )
    )


def _score_points(item: dict[str, Any]) -> float:
    points = 0.0
    for point in item.get("key_score_points") or []:
        if isinstance(point, dict):
            try:
                points += float(point.get("points") or 0)
            except (TypeError, ValueError):
                pass
    return points


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _requires_process(item: dict[str, Any]) -> bool:
    surface = "\n".join(str(value or "") for value in (item.get("prompt"), item.get("answer_format")))
    return any(marker in surface for marker in PROCESS_REQUIREMENT_MARKERS)


def _looks_like_bare_result(text: str) -> bool:
    compact = "".join(str(text).split())
    if not compact or len(compact) > 18 or _has_cjk(compact):
        return False
    math_chars = set("0123456789+-*/×÷=<>≤≥().,xyabcABCXYZ")
    signal_count = sum(1 for char in compact if char in math_chars or char.isalpha())
    return signal_count >= max(1, len(compact) - 1)


def _answer_contract_findings(item: dict[str, Any]) -> list[ExpertFinding]:
    findings: list[ExpertFinding] = []
    if _requires_process(item):
        bare_alternatives = [
            str(value)
            for value in item.get("accepted_alternatives") or []
            if _looks_like_bare_result(str(value))
        ]
        alternatives_text = "\n".join(str(value) for value in item.get("accepted_alternatives") or [])
        if bare_alternatives and not any(qualifier in alternatives_text for qualifier in COMPLETE_ANSWER_QUALIFIERS):
            _add(
                findings,
                "P1",
                "assessment_expert",
                item,
                "accepted_alternatives_answer_only_misalignment",
                "题目要求解释/判断/检验，但 accepted_alternatives 把裸结果列成完整可接受答案；需注明裸结果只代表最终形式，完整作答仍要包含过程证据。",
            )

    return findings


def _review_item(
    item: dict[str, Any],
    *,
    graph_nodes: dict[str, dict[str, Any]],
    blueprints: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
) -> list[ExpertFinding]:
    findings: list[ExpertFinding] = []
    item_id = str(item.get("id") or "")
    node_id = str(item.get("node_id") or "")
    family_id = str(item.get("question_type") or "")
    text = _text_of(item)

    if not item_id:
        _add(findings, "P0", "assessment_expert", item, "missing_item_id", "题目缺少稳定 id。")
    if node_id not in graph_nodes:
        _add(findings, "P0", "bridge_diagnosis_teacher", item, "unknown_graph_node", f"题目绑定未知图谱节点：{node_id}。")
    if node_id not in blueprints:
        _add(findings, "P0", "bridge_diagnosis_teacher", item, "missing_node_blueprint", f"题目节点没有 v18 节点蓝图：{node_id}。")
    if family_id not in families:
        _add(findings, "P0", "assessment_expert", item, "unknown_question_family", f"题目绑定未知题型家族：{family_id}。")

    blueprint = blueprints.get(node_id) or {}
    allowed_families = {entry.get("family_id") for entry in blueprint.get("family_plan") or []}
    if allowed_families and family_id not in allowed_families:
        _add(findings, "P1", "bridge_diagnosis_teacher", item, "family_not_in_node_blueprint", "题型家族不在该节点蓝图的 family_plan 中。")

    prompt = str(item.get("prompt") or "").strip()
    if len(prompt) < 18:
        _add(findings, "P1", "frontline_math_teacher", item, "prompt_too_short", "题干过短，难以形成真实诊断证据。")
    if any(marker in prompt for marker in LOW_VALUE_PROMPT_MARKERS) and len(item.get("required_evidence") or []) < 3:
        _add(findings, "P1", "frontline_math_teacher", item, "low_value_mechanical_prompt", "题目像机械计算或答案题，缺少足够过程证据。")
    if any(leak in text for leak in FORBIDDEN_CHILD_LEAKS):
        _add(findings, "P1", "frontline_math_teacher", item, "child_surface_leak", "题目或答案含后台/英文修复话术，不适合孩子端。")

    secondary_node_ids = {str(value) for value in item.get("secondary_node_ids") or []}
    if (
        node_id == "M-G7-OPPOSITE"
        and family_id == "opposite_absolute_value_model"
        and ("绝对值" in text or "|" in text)
        and "M-G7-ABSOLUTE" not in secondary_node_ids
    ):
        _add(
            findings,
            "P1",
            "bridge_diagnosis_teacher",
            item,
            "opposite_probe_mixes_absolute_without_secondary_node",
            "相反数节点候选题把绝对值作为显性诊断内容，但未标记绝对值 secondary node，容易污染掌握判断。",
        )

    if (
        family_id == "linear_equation_solving_flow"
        and "①" in prompt
        and "②" in prompt
        and "合法" in prompt
        and not any(marker in prompt for marker in ("分别说明", "每一步", "每个", "两步为什么"))
    ):
        _add(
            findings,
            "P1",
            "assessment_expert",
            item,
            "equation_flow_legality_prompt_not_complete",
            "方程流程题要求补多步，但只要求说明其中一步合法性，不能稳定诊断等式变形依据。",
        )

    required_evidence = item.get("required_evidence") or []
    key_score_points = item.get("key_score_points") or []
    if len(required_evidence) < 3:
        _add(findings, "P1", "assessment_expert", item, "weak_required_evidence", "required_evidence 少于 3 条，难支撑评估和规划。")
    if len(key_score_points) < 3:
        _add(findings, "P1", "assessment_expert", item, "weak_score_points", "key_score_points 少于 3 条，评分合同过弱。")
    if key_score_points and _score_points(item) != 10:
        _add(findings, "P1", "assessment_expert", item, "score_points_not_10", "key_score_points 分值合计不是 10 分。")
    if not item.get("standard_answer") and not item.get("expected_answer"):
        _add(findings, "P1", "assessment_expert", item, "missing_standard_answer", "题目缺少标准答案或 expected_answer。")
    findings.extend(_answer_contract_findings(item))

    source = item.get("source") or {}
    source_type = str(item.get("source_type") or source.get("source_type") or "")
    if source_type in {"commercial_reference", "publisher_catalog_reference"}:
        _add(findings, "P0", "source_compliance_reviewer", item, "commercial_source_item", "商业/出版社参考源题目不能直接进入题库题目。")
    if not source_type:
        _add(findings, "P2", "source_compliance_reviewer", item, "missing_source_type", "题目缺少来源类型，需补充来源 lineage。")

    difficulty = str(item.get("difficulty") or item.get("variant_level") or "")
    if difficulty in {"L5", "L4"}:
        if not any(marker in prompt for marker in ("为什么", "说明", "判断", "比较", "构造", "反例", "验证", "迁移")):
            _add(findings, "P2", "stretch_competition_teacher", item, "stretch_lacks_reasoning_surface", "较高难度题缺少推理/迁移表面要求，可能是伪难或硬算。")
    if difficulty == "L1":
        _add(findings, "P1", "frontline_math_teacher", item, "below_grade_floor", "题目难度低于当前六升七定位。")

    return findings


def _profile_summary(findings: list[ExpertFinding]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    grouped: defaultdict[str, list[ExpertFinding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.profile].append(finding)
    for profile_id, profile in EXPERT_PROFILES.items():
        profile_findings = grouped.get(profile_id, [])
        counts = Counter(f.severity for f in profile_findings)
        status = "PASS" if not any(f.severity in FAIL_SEVERITIES for f in profile_findings) else "NEEDS_FIX"
        summary[profile_id] = {
            "display": profile["display"],
            "status": status,
            "finding_counts": dict(sorted(counts.items())),
        }
    return summary


def _status_from_findings(findings: list[ExpertFinding], *, sample_only: bool) -> str:
    if any(f.severity == "P0" for f in findings):
        return "NEEDS_FIX"
    if any(f.severity == "P1" for f in findings):
        return "NEEDS_FIX"
    return "PASS_WITH_SCOPE" if sample_only else "PASS"


def build_expert_quality_review(*, root: Path, version: str = "v18", subject: str = "math") -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    bank_path = _question_bank_path(paths, version)
    bank = _load_json(bank_path)
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    items = list(bank.get("items") or [])

    findings: list[ExpertFinding] = []
    fingerprints = defaultdict(list)
    for item in items:
        findings.extend(_review_item(item, graph_nodes=graph_nodes, blueprints=blueprints, families=families))
        fingerprint = _item_fingerprint(item)
        if fingerprint:
            fingerprints[fingerprint].append(str(item.get("id") or ""))
    for fingerprint, item_ids in sorted(fingerprints.items()):
        if len(item_ids) > 1:
            findings.append(
                ExpertFinding(
                    severity="P1",
                    profile="assessment_expert",
                    item_id=",".join(sorted(item_ids)),
                    node_id="",
                    code="duplicate_structure_fingerprint",
                    message=f"结构指纹重复：{fingerprint}。",
                )
            )

    sample_only = bank.get("status") == "draft_generated_not_active" or "sample" in str(bank.get("question_bank_version") or "")
    finding_dicts = [finding.to_dict() for finding in sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.profile, f.item_id, f.code))]
    status = _status_from_findings(findings, sample_only=sample_only)
    return {
        "schema_version": "2026-07-23.codex-admin.expert-quality-review.v1",
        "subject": subject,
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_status": str(bank.get("status") or "unknown"),
        "source_path": str(bank_path.relative_to(root) if bank_path.is_absolute() and bank_path.is_relative_to(root) else bank_path),
        "reviewed_item_count": len(items),
        "status": status,
        "sample_only": sample_only,
        "expert_profiles": _profile_summary(findings),
        "finding_counts": dict(sorted(Counter(f.severity for f in findings).items())),
        "findings": finding_dicts,
        "activation_implication": "does_not_authorize_activation",
    }


def _candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("item"), dict):
        return dict(payload["item"])
    if isinstance(payload.get("candidate"), dict):
        return dict(payload["candidate"])
    return dict(payload)


def build_candidate_expert_review(
    *,
    root: Path,
    candidate_path: Path,
    subject: str = "math",
    version: str = "v18",
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    resolved = candidate_path if candidate_path.is_absolute() else root / candidate_path
    if not resolved.exists():
        raise ValueError(f"ADMIN_EXPERT_REVIEW_CANDIDATE_MISSING: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ADMIN_EXPERT_REVIEW_INVALID_CANDIDATE_JSON: {resolved}: {exc}") from exc
    item = _candidate_item(payload)
    candidate_sha256 = _digest_json(item)
    source_file_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    findings = _review_item(item, graph_nodes=graph_nodes, blueprints=blueprints, families=families)
    finding_dicts = [
        finding.to_dict()
        for finding in sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.profile, f.item_id, f.code))
    ]
    status = _status_from_findings(findings, sample_only=False)
    return {
        "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
        "subject": subject,
        "question_bank_version": version,
        "question_bank_status": "candidate_only",
        "source_path": str(resolved.relative_to(root) if resolved.is_absolute() and resolved.is_relative_to(root) else resolved),
        "reviewed_item_count": 1,
        "status": status,
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "family_id": str(item.get("question_type") or ""),
        "candidate_sha256": candidate_sha256,
        "source_file_sha256": source_file_sha256,
        "sample_only": False,
        "expert_profiles": _profile_summary(findings),
        "finding_counts": dict(sorted(Counter(f.severity for f in findings).items())),
        "findings": finding_dicts,
        "staging_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def _model_expert_review_prompt_payload(
    *,
    root: Path,
    candidate_path: Path,
    item: dict[str, Any],
    deterministic_review: dict[str, Any],
    graph_nodes: dict[str, dict[str, Any]],
    blueprints: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
    question_requirement: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = internal_agents.load_contract("admin_question_expert_review", version_suffix="v1")
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    prompt_template = prompt_path.read_text(encoding="utf-8")
    node_id = str(item.get("node_id") or "")
    family_id = str(item.get("question_type") or "")
    trusted_context = {
        "schema_version": "2026-07-23.codex-admin.model-expert-review-context.v1",
        "candidate_path": str(candidate_path),
        "candidate_sha256": _digest_json(item),
        "node": graph_nodes.get(node_id) or {},
        "node_blueprint": blueprints.get(node_id) or {},
        "question_family": families.get(family_id) or {},
        "question_requirement": question_requirement,
        "requirement_authority": {
            "scope": "this_candidate_slot",
            "priority": "question_requirement_over_sibling_family_coverage",
            "rule": "Judge this item against its slot evidence_goal, question_direction, must_include, must_not_include, target misconceptions, and difficulty. Family-level evidence may be distributed across sibling slots.",
        },
        "deterministic_review": {
            "status": deterministic_review.get("status"),
            "finding_counts": deterministic_review.get("finding_counts") or {},
            "findings": deterministic_review.get("findings") or [],
        },
        "review_authority": "receipt_only_does_not_authorize_activation",
    }
    untrusted_payload = {"candidate": item}
    prompt = (
        prompt_template
        .replace("{trusted_context_json}", json.dumps(trusted_context, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{untrusted_payload_json}", json.dumps(untrusted_payload, ensure_ascii=False, indent=2, sort_keys=True))
    )
    payload = {
        "instructions": "You are admin_question_expert_review_agent. Return only schema-valid JSON for the internal review receipt.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    meta = {
        "prompt_template_path": _relpath(root, prompt_path),
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path),
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_schema_version": str(contract.get("response_schema_version") or ""),
        "response_schema_sha256": internal_agents.canonical_json_sha256(contract.get("response_schema") or {}),
        "contract_version": str(contract.get("contract_version") or ""),
        "minimum_confidence_to_apply": contract.get("minimum_confidence_to_apply"),
        "question_requirement_sha256": _digest_json(question_requirement),
    }
    return payload, meta, contract


def _model_expert_status(
    overall_status: str,
    profile_reviews: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    confidence: float,
    minimum_confidence: float,
) -> str:
    if confidence < minimum_confidence or any(
        str(finding.get("severity") or "") in FAIL_SEVERITIES for finding in findings
    ):
        return "NEEDS_FIX"
    profile_statuses = {
        str(review.get("profile") or ""): str(review.get("status") or "")
        for review in profile_reviews
        if isinstance(review, dict)
    }
    if set(profile_statuses) != set(EXPERT_PROFILES):
        return "NEEDS_FIX"
    if any(status in {"reject", "needs_revision"} for status in profile_statuses.values()):
        return "NEEDS_FIX"
    if any(status not in {"pass", "pass_with_scope"} for status in profile_statuses.values()):
        return "NEEDS_FIX"
    if any(status == "pass_with_scope" for status in profile_statuses.values()):
        return "PASS_WITH_SCOPE"
    if overall_status == "pass" and set(profile_statuses.values()) == {"pass"}:
        return "PASS"
    if overall_status == "pass_with_scope":
        return "PASS_WITH_SCOPE"
    return "NEEDS_FIX"


def build_candidate_model_expert_board_review(
    *,
    root: Path,
    candidate_path: Path,
    deterministic_review: dict[str, Any] | None = None,
    question_requirement: dict[str, Any] | None = None,
    subject: str = "math",
    version: str = "v18",
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    resolved = candidate_path if candidate_path.is_absolute() else root / candidate_path
    if not resolved.exists():
        raise ValueError(f"ADMIN_MODEL_EXPERT_REVIEW_CANDIDATE_MISSING: {resolved}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    item = _candidate_item(payload)
    canonical_requirement = json.loads(json.dumps(question_requirement or {}, ensure_ascii=False))
    candidate_sha256 = _digest_json(item)
    source_file_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    deterministic_review = deterministic_review or build_candidate_expert_review(
        root=root,
        candidate_path=resolved,
        subject=subject,
        version=version,
    )
    route = model_router.admin_question_expert_review_route()
    prompt_payload, prompt_meta, contract = _model_expert_review_prompt_payload(
        root=root,
        candidate_path=resolved,
        item=item,
        deterministic_review=deterministic_review,
        graph_nodes=graph_nodes,
        blueprints=blueprints,
        families=families,
        question_requirement=canonical_requirement,
    )
    base = {
        "schema_version": MODEL_EXPERT_BOARD_SCHEMA_VERSION,
        "subject": subject,
        "question_bank_version": version,
        "question_bank_status": "candidate_only",
        "source_path": str(resolved.relative_to(root) if resolved.is_absolute() and resolved.is_relative_to(root) else resolved),
        "reviewed_item_count": 1,
        "status": "BLOCKED_MODEL_NOT_CONFIGURED",
        "overall_status": "",
        "provider_mode": "not_configured",
        "retryable": False,
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "family_id": str(item.get("question_type") or ""),
        "question_requirement_id": str(canonical_requirement.get("question_requirement_id") or ""),
        "slot_id": str(canonical_requirement.get("slot_id") or ""),
        "question_requirement": canonical_requirement,
        "question_requirement_sha256": _digest_json(canonical_requirement),
        "candidate_sha256": candidate_sha256,
        "source_file_sha256": source_file_sha256,
        "route": model_router.route_status(route).as_dict(),
        "prompt_meta": prompt_meta,
        "profile_reviews": [],
        "finding_counts": {},
        "findings": [],
        "staging_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["configure_admin_question_expert_review_model"],
    }
    if not route.enabled:
        return base
    transport_meta: dict[str, Any] = {}
    try:
        started = datetime.now(timezone.utc)
        with bind_admin_structured_model_deadline(
            batch_attempt_id=f"admin_question_expert_review:{candidate_path}",
            timeout_envs=(
                "AI_ADMIN_QUESTION_EXPERT_REVIEW_WALL_SECONDS",
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
            "next_actions": ["retry_or_repair_model_expert_review_route"],
        }
    value = result.value
    findings = list(value.get("findings") or [])
    confidence = float(value.get("confidence") or 0)
    minimum_confidence = float(contract.get("minimum_confidence_to_apply") or 0.86)
    if confidence < minimum_confidence:
        findings.append(
            {
                "severity": "P1",
                "profile": "assessment_expert",
                "item_id": str(item.get("id") or ""),
                "code": "model_expert_review_low_confidence",
                "message": f"模型专家 board 置信度 {confidence:.2f} 低于应用阈值 {minimum_confidence:.2f}。",
            }
        )
    overall_status = str(value.get("overall_status") or "")
    profile_reviews = list(value.get("profile_reviews") or [])
    profile_names = [str(review.get("profile") or "") for review in profile_reviews if isinstance(review, dict)]
    if len(profile_names) != len(EXPERT_PROFILES) or set(profile_names) != set(EXPERT_PROFILES):
        findings.append(
            {
                "severity": "P1",
                "profile": "assessment_expert",
                "item_id": str(item.get("id") or ""),
                "code": "model_expert_profile_coverage_invalid",
                "message": "模型专家 board 的五个 profile verdict 缺失、重复或身份不正确。",
            }
        )
    status = _model_expert_status(overall_status, profile_reviews, findings, confidence, minimum_confidence)
    return {
        **base,
        "status": status,
        "overall_status": overall_status,
        "provider_mode": "live_model",
        "retryable": False,
        "confidence": confidence,
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
        "profile_reviews": profile_reviews,
        "finding_counts": dict(sorted(Counter(str(finding.get("severity") or "") for finding in findings).items())),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(str(f.get("severity") or ""), 9), str(f.get("profile") or ""), str(f.get("code") or ""))),
        "next_actions": ["qa_review"] if status in {"PASS", "PASS_WITH_SCOPE"} else ["regenerate_candidate"],
    }


def render_model_expert_board_review_markdown(report: dict[str, Any]) -> str:
    finding_lines = [
        f"| {finding.get('severity', '')} | {finding.get('profile', '')} | {finding.get('item_id', '')} | {finding.get('code', '')} | {finding.get('message', '')} |"
        for finding in report.get("findings") or []
    ]
    if not finding_lines:
        finding_lines.append("| | | | | |")
    return f"""# Model Expert Board Review

Status: `{report.get('status')}`

Created At: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

Item: `{report.get('item_id')}`

Node: `{report.get('node_id')}`

Family: `{report.get('family_id')}`

Provider Mode: `{report.get('provider_mode')}`

Activation Implication: `{report.get('activation_implication')}`

## Finding Counts

```json
{json.dumps(report.get('finding_counts') or {}, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Findings

| Severity | Profile | Item | Code | Message |
|---|---|---|---|---|
{chr(10).join(finding_lines)}
"""


def write_model_expert_board_review(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    report_id_input = "|".join([
        str(report.get("schema_version") or ""),
        str(report.get("status") or ""),
        str(report.get("item_id") or ""),
        str(report.get("source_path") or ""),
        str(report.get("candidate_sha256") or ""),
        str(report.get("question_requirement_sha256") or ""),
        str((report.get("prompt_meta") or {}).get("rendered_prompt_sha256") or ""),
        str((report.get("route") or {}).get("raw_response_sha256") or ""),
        json.dumps(report.get("finding_counts") or {}, ensure_ascii=False, sort_keys=True),
    ])
    report_id = "MODEL-EXPERT-" + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    markdown_rel = Path("docs/system/admin_reports/model_expert_reviews") / f"{datetime.now(timezone.utc).date()}-{report_id}.md"
    json_rel = Path("data/admin/model_expert_reviews") / f"{report_id}.json"
    result = {
        **report,
        "model_expert_review_report_id": report_id,
        "model_expert_review_markdown_path": str(markdown_rel),
        "model_expert_review_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_content = render_model_expert_board_review_markdown(report)
    markdown_fd, markdown_temp = tempfile.mkstemp(prefix=f".{markdown_path.name}.", suffix=".tmp", dir=str(markdown_path.parent))
    with os.fdopen(markdown_fd, "w", encoding="utf-8") as handle:
        handle.write(markdown_content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(markdown_temp, markdown_path)
    result["model_expert_review_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    json_fd, json_temp = tempfile.mkstemp(prefix=f".{json_path.name}.", suffix=".tmp", dir=str(json_path.parent))
    with os.fdopen(json_fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(json_temp, json_path)
    result["model_expert_review_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result


def render_expert_quality_review_markdown(report: dict[str, Any]) -> str:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profile_lines = []
    for profile_id, profile in report["expert_profiles"].items():
        profile_lines.append(
            f"| {profile_id} | {profile['display']} | {profile['status']} | "
            f"{json.dumps(profile['finding_counts'], ensure_ascii=False, sort_keys=True)} |"
        )
    finding_lines = []
    for finding in report["findings"]:
        finding_lines.append(
            f"| {finding['severity']} | {finding['profile']} | {finding['item_id']} | "
            f"{finding['code']} | {finding['message']} |"
        )
    if not finding_lines:
        finding_lines.append("| | | | | |")
    return f"""# Expert Question Quality Review

Status: `{report['status']}`

Created At: {created_at}

Subject: {report['subject']}

Question Bank: {report['question_bank_version']}

Question Bank Status: {report['question_bank_status']}

Reviewed Items: {report['reviewed_item_count']}

Activation Implication: `{report['activation_implication']}`

## Expert Profiles

| Profile | Display | Status | Finding Counts |
|---|---|---|---|
{chr(10).join(profile_lines)}

## Finding Counts

```json
{json.dumps(report['finding_counts'], ensure_ascii=False, indent=2, sort_keys=True)}
```

## Findings

| Severity | Profile | Item | Code | Message |
|---|---|---|---|---|
{chr(10).join(finding_lines)}

## Scope

This is a deterministic expert-profile gate. It checks contracts, obvious quality risks,
source boundaries, child-surface leaks, and grading evidence coverage. It does not replace
live model semantic review or independent human expert review.
"""


def write_expert_quality_review(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    report_id_input = "|".join([
        str(report.get("schema_version") or ""),
        str(report.get("question_bank_version") or ""),
        str(report.get("status") or ""),
        str(report.get("reviewed_item_count") or ""),
        str(report.get("item_id") or ""),
        str(report.get("source_path") or ""),
    ])
    report_id = "EXPERT-QA-" + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    markdown_rel = Path("docs/system/admin_reports/reviews") / f"{datetime.now(timezone.utc).date()}-{report_id}.md"
    json_rel = Path("data/admin/reviews") / f"{report_id}.json"
    markdown = render_expert_quality_review_markdown(report)
    result = {
        **report,
        "review_report_id": report_id,
        "review_markdown_path": str(markdown_rel),
        "review_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    result["review_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["review_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result
