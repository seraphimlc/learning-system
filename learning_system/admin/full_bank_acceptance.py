from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inventory import (
    AdminPaths,
    _blueprints_by_node,
    _duplicate_fingerprint_groups,
    _families_by_id,
    _graph_nodes_by_id,
    _item_fingerprint,
    _load_assets,
    _load_json,
)
from .staging import (
    staged_content_envelope_sha256,
    validate_staged_item_collision_lineage,
)


FULL_BANK_ACCEPTANCE_SCHEMA_VERSION = "2026-07-23.codex-admin.full-bank-acceptance.v1"
DEFAULT_STAGED_BANK_PATH = Path("data/question_banks/v18/staged_candidates_v18.json")
FAIL_SEVERITIES = {"P0", "P1"}
V18_ITEM_CONTRACT_VERSION = "2026-07-24.question-bank-v18.acceptance-item.v1"
V18_CANONICAL_FAMILY_FIELD = "question_type"
V18_CANONICAL_SCORE_FIELD = "key_score_points"
V18_REQUIRED_ITEM_FIELDS = (
    "id",
    "item_version",
    "node_id",
    "difficulty",
    "prompt",
    "answer_format",
    "standard_answer",
    "accepted_alternatives",
    "required_evidence",
    "solution_steps",
    "target_error_tags",
    "rollback_candidates",
    "child_surface_design",
)
V18_REQUIRED_ITEM_FIELDS_ALLOW_EMPTY_LIST = {"accepted_alternatives", "rollback_candidates"}
RECEIPT_POLICIES = {
    "machine_check": {
        "pass_statuses": {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"},
        "staging_digest_key": "machine_report_sha256",
        "artifact_hash_field": "production_json_sha256",
        "artifact_required": True,
        "artifact_schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
        "artifact_path_field": "production_json_path",
        "expected_role": "machine_contract_check",
    },
    "deterministic_expert_review": {
        "pass_statuses": {"PASS"},
        "staging_digest_key": "expert_report_sha256",
        "artifact_hash_field": "review_json_sha256",
        "artifact_required": True,
        "artifact_schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
        "artifact_path_field": "review_json_path",
        "expected_role": "deterministic_expert_review",
    },
    "model_expert_board_review": {
        "pass_statuses": {"PASS"},
        "staging_digest_key": "model_expert_report_sha256",
        "artifact_hash_field": "model_expert_review_json_sha256",
        "artifact_required": True,
        "artifact_schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
        "artifact_path_field": "model_expert_review_json_path",
        "expected_role": "live_model_expert_board_review",
    },
    "guanzhi_qa_review": {
        "pass_statuses": {"PASS"},
        "staging_digest_key": "qa_report_sha256",
        "artifact_hash_field": "qa_json_sha256",
        "artifact_required": True,
        "artifact_schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
        "artifact_path_field": "qa_json_path",
        "expected_role": "live_model_semantic_qa_review",
        "finding_prefix": "semantic_qa_review",
    },
}
QA_CONTRACT_SCHEMA_VERSION = "2026-07-24.codex-admin.candidate-qa-contract-check.v1"
QA_SCOPE_KEYS = {"support_only", "not_for_activation", "exclude_from_coverage", "reasons"}
LEGACY_REVALIDATION_CODES = {
    "machine_check_report_artifact_missing",
    "missing_qa_contract_check_receipt",
    "semantic_qa_review_gate_type_invalid",
    "semantic_qa_review_not_live_model",
    "semantic_qa_review_role_invalid",
}


def _relpath(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    item_id: str = "",
    node_id: str = "",
    profile: str = "full_bank_acceptance",
) -> dict[str, str]:
    return {
        "severity": severity,
        "profile": profile,
        "item_id": item_id,
        "node_id": node_id,
        "code": code,
        "message": message,
    }


def _counts(findings: list[dict[str, str]]) -> dict[str, int]:
    return dict(sorted(Counter(finding.get("severity", "") for finding in findings).items()))


def _source_digest(root: Path, path: Path) -> dict[str, str]:
    resolved = path if path.is_absolute() else root / path
    return {
        "path": _relpath(root, resolved),
        "sha256": _sha256(resolved),
    }


def _resolved_path(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _paths_match(root: Path, left: str, right: str) -> bool:
    if not left or not right:
        return False
    return _resolved_path(root, left).resolve() == _resolved_path(root, right).resolve()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _load_report_if_present(
    root: Path,
    path_text: str,
    *,
    artifact_hash_field: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    if not path_text:
        return None, "", ""
    resolved = _resolved_path(root, path_text)
    if not resolved.exists():
        return None, "", ""
    try:
        raw = resolved.read_bytes()
        report = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "", ""
    raw_sha = hashlib.sha256(raw).hexdigest()
    digest_payload = dict(report)
    if artifact_hash_field and not digest_payload.get(artifact_hash_field):
        digest_payload[artifact_hash_field] = raw_sha
    return report, _digest_json(digest_payload), raw_sha


def _qa_scope_is_empty(scope: Any) -> bool:
    if not isinstance(scope, dict) or set(scope) != QA_SCOPE_KEYS:
        return False
    if not all(scope.get(key) is False for key in ("support_only", "not_for_activation", "exclude_from_coverage")):
        return False
    return scope.get("reasons") == []


def _candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("item"), dict):
        return dict(payload["item"])
    if isinstance(payload.get("candidate"), dict):
        return dict(payload["candidate"])
    return dict(payload)


def _family_id_and_findings(item: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    item_id = str(item.get("id") or "")
    node_id = str(item.get("node_id") or "")
    canonical = str(item.get(V18_CANONICAL_FAMILY_FIELD) or "")
    migration_alias = str(item.get("question_family_id") or "")
    findings: list[dict[str, str]] = []
    if canonical and migration_alias and canonical != migration_alias:
        findings.append(_finding("P1", "question_family_contract_conflict", "question_type 与 question_family_id 不一致。", item_id=item_id, node_id=node_id))
    if canonical:
        if migration_alias:
            findings.append(_finding("P2", "legacy_question_family_id_present", "question_family_id 是迁移别名；正式 v18 字段为 question_type。", item_id=item_id, node_id=node_id))
        return canonical, findings
    if migration_alias:
        findings.append(_finding("P2", "legacy_question_family_id_used", "题目使用迁移别名 question_family_id；入库前应迁移为 question_type。", item_id=item_id, node_id=node_id))
        return migration_alias, findings
    findings.append(_finding("P1", "missing_question_type", "题目缺少正式 v18 题型字段 question_type。", item_id=item_id, node_id=node_id))
    return "", findings


def _score_contract_and_findings(item: dict[str, Any]) -> tuple[list[Any], list[dict[str, str]]]:
    item_id = str(item.get("id") or "")
    node_id = str(item.get("node_id") or "")
    canonical = item.get(V18_CANONICAL_SCORE_FIELD)
    migration_alias = item.get("scoring_targets")
    findings: list[dict[str, str]] = []
    if canonical not in (None, []):
        if migration_alias not in (None, []):
            findings.append(_finding("P2", "legacy_scoring_targets_present", "scoring_targets 是迁移别名；正式 v18 评分字段为 key_score_points。", item_id=item_id, node_id=node_id))
        score_points = canonical
    elif migration_alias not in (None, []):
        score_points = migration_alias
        findings.append(_finding("P2", "legacy_scoring_targets_used", "题目使用迁移别名 scoring_targets；入库前应迁移为 key_score_points。", item_id=item_id, node_id=node_id))
    else:
        findings.append(_finding("P1", "missing_answer_contract", "题目缺少正式 v18 评分合同 key_score_points。", item_id=item_id, node_id=node_id))
        return [], findings

    if not isinstance(score_points, list) or not score_points or not all(isinstance(point, dict) for point in score_points):
        findings.append(_finding("P1", "invalid_score_contract", "评分合同必须是非空对象列表。", item_id=item_id, node_id=node_id))
        return [], findings
    if len(score_points) < 3:
        findings.append(_finding("P1", "score_contract_too_shallow", "评分合同至少需要 3 个题目级评分点。", item_id=item_id, node_id=node_id))
    try:
        total_points = sum(float(point.get("points")) for point in score_points)
    except (TypeError, ValueError):
        total_points = -1
    if total_points != 10:
        findings.append(_finding("P1", "score_contract_not_10_points", f"评分合同总分必须为 10，当前为 {total_points}。", item_id=item_id, node_id=node_id))
    for point in score_points:
        if not str(point.get("key") or "") or not str(point.get("evidence") or "") or not str(point.get("mastery_dimension") or ""):
            findings.append(_finding("P1", "incomplete_score_point", "每个评分点必须包含 key、evidence、mastery_dimension。", item_id=item_id, node_id=node_id))
            break
    return score_points, findings


def _contract_findings(
    *,
    item: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    blueprints: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
) -> tuple[str, list[dict[str, str]]]:
    item_id = str(item.get("id") or "")
    node_id = str(item.get("node_id") or "")
    family_id, findings = _family_id_and_findings(item)
    for field in V18_REQUIRED_ITEM_FIELDS:
        value = item.get(field)
        if field not in item or value in (None, "") or (value == [] and field not in V18_REQUIRED_ITEM_FIELDS_ALLOW_EMPTY_LIST):
            findings.append(_finding("P1", f"missing_{field}", f"题目缺少正式 v18 必填字段：{field}。", item_id=item_id, node_id=node_id))
    _score_points, score_findings = _score_contract_and_findings(item)
    findings.extend(score_findings)
    if isinstance(item.get("required_evidence"), list) and len(item.get("required_evidence") or []) < 3:
        findings.append(_finding("P1", "required_evidence_too_shallow", "required_evidence 至少需要 3 条题目级证据。", item_id=item_id, node_id=node_id))
    if node_id not in nodes:
        findings.append(_finding("P1", "unsupported_node", f"题目绑定未知图谱节点：{node_id}。", item_id=item_id, node_id=node_id))
    if family_id not in families:
        findings.append(_finding("P1", "unsupported_family", f"题目绑定未知题型家族：{family_id}。", item_id=item_id, node_id=node_id))
    blueprint = blueprints.get(node_id) or {}
    family_entry = next((entry for entry in blueprint.get("family_plan") or [] if str(entry.get("family_id") or "") == family_id), None)
    if node_id in blueprints and family_id and family_entry is None:
        findings.append(_finding("P1", "family_not_in_node_blueprint", f"题型家族不在节点蓝图中：{family_id}。", item_id=item_id, node_id=node_id))
    if family_entry:
        allowed_difficulties = {str(value) for value in family_entry.get("difficulty") or []}
        difficulty = str(item.get("difficulty") or "")
        if allowed_difficulties and difficulty not in allowed_difficulties:
            findings.append(_finding("P1", "difficulty_not_in_family_plan", f"难度 {difficulty} 不在题型计划允许范围。", item_id=item_id, node_id=node_id))
    if not item.get("standard_answer"):
        findings.append(_finding("P1", "missing_standard_answer", "题目缺少标准答案。", item_id=item_id, node_id=node_id))
    if not _item_fingerprint(item):
        findings.append(_finding("P1", "missing_structure_fingerprint", "题目缺少结构指纹。", item_id=item_id, node_id=node_id))
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    if quality.get("activation_eligible") or item.get("activation_eligible"):
        findings.append(_finding("P1", "staged_item_self_authorizes_activation", "staged 题目不能自声明 activation_eligible。", item_id=item_id, node_id=node_id))
    if str(quality.get("review_status") or item.get("review_status") or "") != "staged":
        findings.append(_finding("P1", "item_not_staged", "全量验收题目必须处于 staged 状态。", item_id=item_id, node_id=node_id))
    return family_id, findings


def _receipt_findings(
    *,
    root: Path,
    item: dict[str, Any],
    previous_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    item_id = str(item.get("id") or "")
    node_id = str(item.get("node_id") or "")
    family_id = str(item.get(V18_CANONICAL_FAMILY_FIELD) or item.get("question_family_id") or "")
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    review_evidence = quality.get("review_evidence") if isinstance(quality.get("review_evidence"), dict) else {}
    receipts = review_evidence.get("receipts") if isinstance(review_evidence.get("receipts"), dict) else {}
    staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
    expected_candidate_sha = str(staging_receipts.get("candidate_sha256") or "")
    expected_content_envelope_sha = str(quality.get("content_envelope_sha256") or "")
    findings: list[dict[str, str]] = []
    try:
        validate_staged_item_collision_lineage(
            item,
            previous_items=previous_items,
            root=root,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        error_code = str(exc).split(":", 1)[0].strip().lower()
        findings.append(
            _finding(
                "P1",
                error_code or "semantic_collision_lineage_invalid",
                f"semantic collision lineage 不可信：{exc}",
                item_id=item_id,
                node_id=node_id,
            )
        )
    if not expected_candidate_sha:
        findings.append(_finding("P1", "missing_staging_candidate_sha256", "staged item 缺少原始候选 payload sha256。", item_id=item_id, node_id=node_id))
    if not expected_content_envelope_sha:
        findings.append(_finding("P1", "missing_content_envelope_sha256", "staged item 缺少受信内容 envelope sha256。", item_id=item_id, node_id=node_id))
    elif str(staging_receipts.get("content_envelope_sha256") or "") != expected_content_envelope_sha:
        findings.append(_finding("P1", "staging_content_envelope_sha256_mismatch", "staging receipt 与 staged item 的内容 envelope 不一致。", item_id=item_id, node_id=node_id))
    elif str(review_evidence.get("content_envelope_sha256") or "") != expected_content_envelope_sha:
        findings.append(_finding("P1", "review_content_envelope_sha256_mismatch", "review evidence 与 staged item 的内容 envelope 不一致。", item_id=item_id, node_id=node_id))
    elif staged_content_envelope_sha256(item) != expected_content_envelope_sha:
        findings.append(_finding("P1", "staged_content_envelope_sha256_mismatch", "当前 staged item 内容已偏离受信 candidate envelope。", item_id=item_id, node_id=node_id))

    candidate_path_text = str(staging_receipts.get("candidate_path") or "")
    candidate_report, _candidate_report_digest, candidate_file_sha = _load_report_if_present(root, candidate_path_text)
    if candidate_report is None:
        findings.append(_finding("P1", "candidate_artifact_missing", "原始候选题 artifact 不存在或不是合法 JSON。", item_id=item_id, node_id=node_id))
    else:
        candidate_item = _candidate_item(candidate_report)
        if _digest_json(candidate_item) != expected_candidate_sha:
            findings.append(_finding("P1", "candidate_artifact_sha256_mismatch", "原始候选题 payload 与 staged candidate_sha256 不一致。", item_id=item_id, node_id=node_id))
        if (
            expected_content_envelope_sha
            and staged_content_envelope_sha256(candidate_item) != expected_content_envelope_sha
        ):
            findings.append(_finding("P1", "candidate_content_envelope_sha256_mismatch", "原始候选题与 staged item 的内容 envelope 不一致。", item_id=item_id, node_id=node_id))
        candidate_family_id = str(candidate_item.get(V18_CANONICAL_FAMILY_FIELD) or candidate_item.get("question_family_id") or "")
        if (
            str(candidate_item.get("id") or "") != item_id
            or str(candidate_item.get("node_id") or "") != node_id
            or candidate_family_id != family_id
        ):
            findings.append(_finding("P1", "candidate_artifact_identity_mismatch", "原始候选题 artifact 与 staged item 身份不一致。", item_id=item_id, node_id=node_id))

    staging_decision_path = str(staging_receipts.get("staging_decision_path") or "")
    staging_decision, _decision_digest, decision_file_sha = _load_report_if_present(root, staging_decision_path)
    if staging_decision is None:
        findings.append(_finding("P1", "staging_decision_artifact_missing", "staging decision artifact 不存在或不是合法 JSON。", item_id=item_id, node_id=node_id))
        decision_receipts: dict[str, Any] = {}
    else:
        decision_receipts = staging_decision.get("review_receipts") if isinstance(staging_decision.get("review_receipts"), dict) else {}
        if decision_file_sha != str(staging_receipts.get("staging_decision_sha256") or ""):
            findings.append(_finding("P1", "staging_decision_sha256_mismatch", "staging decision artifact sha256 不一致。", item_id=item_id, node_id=node_id))
        if str(staging_decision.get("status") or "") != "STAGED_READY" or not staging_decision.get("staging_allowed"):
            findings.append(_finding("P1", "staging_decision_not_ready", "staging decision 不是 STAGED_READY。", item_id=item_id, node_id=node_id))
        if str(staging_decision.get("candidate_sha256") or "") != expected_candidate_sha:
            findings.append(_finding("P1", "staging_decision_candidate_sha256_mismatch", "staging decision candidate_sha256 不一致。", item_id=item_id, node_id=node_id))

    loaded_reports: dict[str, dict[str, Any]] = {}
    effective_receipts: dict[str, dict[str, Any]] = {}
    for key, policy in RECEIPT_POLICIES.items():
        finding_prefix = str(policy.get("finding_prefix") or key)
        staged_receipt = receipts.get(key) if isinstance(receipts.get(key), dict) else {}
        decision_receipt = decision_receipts.get(key) if isinstance(decision_receipts.get(key), dict) else {}
        receipt = (
            decision_receipt
            if key == "guanzhi_qa_review" and decision_receipt
            else staged_receipt
        )
        effective_receipts[key] = receipt
        if not receipt:
            findings.append(_finding("P1", f"missing_{finding_prefix}_receipt", f"题目缺少 {finding_prefix} receipt。", item_id=item_id, node_id=node_id))
            continue
        if key == "guanzhi_qa_review" and staged_receipt and decision_receipt:
            for field in ("status", "candidate_sha256", "report_sha256", "item_id", "node_id", "family_id", "schema_version"):
                if str(staged_receipt.get(field) or "") != str(decision_receipt.get(field) or ""):
                    findings.append(_finding("P1", "semantic_qa_review_staged_snapshot_mismatch", f"staged semantic QA snapshot 的 {field} 与 staging decision 不一致。", item_id=item_id, node_id=node_id))
                    break
            if str(staged_receipt.get("role") or "") == "guanzhi_qa_review" and str(decision_receipt.get("role") or "") == "live_model_semantic_qa_review":
                findings.append(_finding("P2", "legacy_guanzhi_semantic_receipt_snapshot", "staged 快照仍使用 guanzhi_qa_review 迁移槽位；语义权威取 staging decision 与 artifact。", item_id=item_id, node_id=node_id))
        status = str(receipt.get("status") or "")
        if status not in policy["pass_statuses"]:
            findings.append(_finding("P1", f"{finding_prefix}_not_passed", f"{finding_prefix} receipt 状态不是严格 PASS：{status}。", item_id=item_id, node_id=node_id))
        if str(receipt.get("role") or "") != str(policy["expected_role"]):
            findings.append(_finding("P1", f"{finding_prefix}_role_invalid", f"{finding_prefix} receipt role 不正确。", item_id=item_id, node_id=node_id))
        if str(receipt.get("schema_version") or "") != str(policy["artifact_schema_version"]):
            findings.append(_finding("P1", f"{finding_prefix}_schema_invalid", f"{finding_prefix} receipt schema 不正确。", item_id=item_id, node_id=node_id))
        receipt_digest = str(receipt.get("report_sha256") or "")
        if not _is_sha256(receipt_digest):
            findings.append(_finding("P1", f"{finding_prefix}_missing_digest", f"{finding_prefix} receipt 缺少 report sha256。", item_id=item_id, node_id=node_id))
        receipt_candidate_sha = str(receipt.get("candidate_sha256") or "")
        if not receipt_candidate_sha:
            findings.append(_finding("P1", f"{finding_prefix}_missing_candidate_sha256", f"{finding_prefix} receipt summary 缺少 candidate_sha256。", item_id=item_id, node_id=node_id))
        elif expected_candidate_sha and receipt_candidate_sha != expected_candidate_sha:
            findings.append(_finding("P1", f"{finding_prefix}_candidate_sha256_mismatch", f"{finding_prefix} receipt summary 与 staged item payload 不一致。", item_id=item_id, node_id=node_id))
        if str(receipt.get("content_envelope_sha256") or "") != expected_content_envelope_sha:
            findings.append(_finding("P1", f"{finding_prefix}_content_envelope_sha256_mismatch", f"{finding_prefix} receipt 未绑定当前内容 envelope。", item_id=item_id, node_id=node_id))
        if (
            str(receipt.get("item_id") or "") != item_id
            or str(receipt.get("node_id") or "") != node_id
            or str(receipt.get("family_id") or "") != family_id
        ):
            findings.append(_finding("P1", f"{finding_prefix}_identity_mismatch", f"{finding_prefix} receipt 未绑定当前 staged item 身份。", item_id=item_id, node_id=node_id))
        staging_digest_key = str(policy["staging_digest_key"])
        staging_digest = str(staging_receipts.get(staging_digest_key) or "")
        if staging_digest != receipt_digest:
            findings.append(_finding("P1", f"{finding_prefix}_staging_digest_mismatch", f"{finding_prefix} receipt 与 staging_receipts 摘要不一致。", item_id=item_id, node_id=node_id))
        if staging_decision is not None and str(staging_decision.get(staging_digest_key) or "") != receipt_digest:
            findings.append(_finding("P1", f"{finding_prefix}_decision_digest_mismatch", f"{finding_prefix} receipt 与 staging decision 顶层摘要不一致。", item_id=item_id, node_id=node_id))
        if not decision_receipt:
            findings.append(_finding("P1", f"{finding_prefix}_missing_from_staging_decision", f"staging decision 缺少 {finding_prefix} receipt。", item_id=item_id, node_id=node_id))
        else:
            fields = ["status", "candidate_sha256", "report_sha256", "item_id", "node_id", "family_id", "role", "schema_version"]
            for field in fields:
                if str(decision_receipt.get(field) or "") != str(receipt.get(field) or ""):
                    findings.append(_finding("P1", f"{finding_prefix}_staging_decision_mismatch", f"staging decision 中 {finding_prefix}.{field} 与 staged receipt 不一致。", item_id=item_id, node_id=node_id))
                    break

        report_path = str(receipt.get("report_path") or "")
        if report_path:
            report, legacy_report_digest, report_file_sha = _load_report_if_present(
                root,
                report_path,
                artifact_hash_field=str(policy["artifact_hash_field"]),
            )
            if report is None:
                findings.append(_finding("P1", f"{finding_prefix}_report_artifact_missing", f"{finding_prefix} report artifact 不存在或不是合法 JSON。", item_id=item_id, node_id=node_id))
            else:
                loaded_reports[key] = report
                if receipt_digest == legacy_report_digest and receipt_digest != report_file_sha:
                    findings.append(_finding("P2", f"legacy_{finding_prefix}_report_digest_used", f"{finding_prefix} 使用旧派生 digest 口径；需迁移为 artifact 文件 sha256。", item_id=item_id, node_id=node_id))
                elif receipt_digest != report_file_sha:
                    findings.append(_finding("P1", f"{finding_prefix}_report_digest_mismatch", f"{finding_prefix} report artifact 与 receipt digest 不一致。", item_id=item_id, node_id=node_id))
                if str(report.get("schema_version") or "") != str(policy["artifact_schema_version"]):
                    findings.append(_finding("P1", f"{finding_prefix}_report_schema_invalid", f"{finding_prefix} report artifact schema 不正确。", item_id=item_id, node_id=node_id))
                if str(report.get("status") or report.get("overall_status") or "") not in policy["pass_statuses"]:
                    findings.append(_finding("P1", f"{finding_prefix}_report_status_not_pass", f"{finding_prefix} report artifact 状态不是严格 PASS。", item_id=item_id, node_id=node_id))
                if str(report.get("candidate_sha256") or "") != expected_candidate_sha:
                    findings.append(_finding("P1", f"{finding_prefix}_report_candidate_sha256_mismatch", f"{finding_prefix} report candidate_sha256 不一致。", item_id=item_id, node_id=node_id))
                if (
                    str(report.get("item_id") or "") != item_id
                    or str(report.get("node_id") or "") != node_id
                    or str(report.get("family_id") or "") != family_id
                ):
                    findings.append(_finding("P1", f"{finding_prefix}_report_identity_mismatch", f"{finding_prefix} report 未绑定当前 staged item 身份。", item_id=item_id, node_id=node_id))
                if report.get("write_applied") is not True:
                    findings.append(_finding("P1", f"{finding_prefix}_report_not_applied", f"{finding_prefix} report 不是已写入 artifact。", item_id=item_id, node_id=node_id))
                if not _paths_match(root, str(report.get(policy["artifact_path_field"]) or ""), report_path):
                    findings.append(_finding("P1", f"{finding_prefix}_report_self_path_mismatch", f"{finding_prefix} report 自身路径与 receipt 不一致。", item_id=item_id, node_id=node_id))
                if key == "model_expert_board_review" and str(report.get("provider_mode") or "") != "live_model":
                    findings.append(_finding("P1", "model_expert_report_not_live", "模型专家 board 必须是 live_model receipt。", item_id=item_id, node_id=node_id))
        elif policy["artifact_required"]:
            findings.append(_finding("P1", f"{finding_prefix}_report_artifact_missing", f"{finding_prefix} receipt 缺少可重验 report artifact。", item_id=item_id, node_id=node_id))

        source_path_text = str(receipt.get("source_path") or "")
        source_file_sha = str(receipt.get("source_file_sha256") or "")
        if source_path_text:
            if not _paths_match(root, source_path_text, candidate_path_text):
                findings.append(_finding("P1", f"{finding_prefix}_source_path_mismatch", f"{finding_prefix} receipt 未绑定当前 candidate artifact。", item_id=item_id, node_id=node_id))
            if candidate_file_sha and source_file_sha != candidate_file_sha:
                findings.append(_finding("P1", f"{finding_prefix}_source_file_sha256_mismatch", f"{finding_prefix} source_file_sha256 不一致。", item_id=item_id, node_id=node_id))

    qa_contract_receipt = receipts.get("qa_contract_check") if isinstance(receipts.get("qa_contract_check"), dict) else {}
    decision_qa_contract = staging_decision.get("qa_contract_check") if isinstance((staging_decision or {}).get("qa_contract_check"), dict) else {}
    if not qa_contract_receipt:
        qa_contract_receipt = decision_qa_contract
    elif decision_qa_contract:
        contract_identity_fields = (
            "status",
            "candidate_sha256",
            "report_sha256",
            "item_id",
            "node_id",
            "family_id",
            "role",
            "schema_version",
            "gate_type",
            "source_file_sha256",
        )
        if any(
            str(qa_contract_receipt.get(field) or "") != str(decision_qa_contract.get(field) or "")
            for field in contract_identity_fields
        ):
            findings.append(_finding("P1", "qa_contract_check_staging_decision_mismatch", "staged 与 staging decision 中的 qa_contract_check receipt 身份或摘要不一致。", item_id=item_id, node_id=node_id))
        if not _paths_match(root, str(qa_contract_receipt.get("report_path") or ""), str(decision_qa_contract.get("report_path") or "")):
            findings.append(_finding("P1", "qa_contract_check_staging_decision_path_mismatch", "staged 与 staging decision 中的 qa_contract_check report_path 不一致。", item_id=item_id, node_id=node_id))
        if not _paths_match(root, str(qa_contract_receipt.get("source_path") or ""), str(decision_qa_contract.get("source_path") or "")):
            findings.append(_finding("P1", "qa_contract_check_staging_decision_source_mismatch", "staged 与 staging decision 中的 qa_contract_check source_path 不一致。", item_id=item_id, node_id=node_id))

    qa_contract_digest = ""
    if not qa_contract_receipt:
        findings.append(_finding("P1", "missing_qa_contract_check_receipt", "题目缺少确定性 qa_contract_check receipt。", item_id=item_id, node_id=node_id))
    else:
        qa_contract_digest = str(qa_contract_receipt.get("report_sha256") or "")
        if str(qa_contract_receipt.get("role") or "") != "deterministic_qa_contract_check":
            findings.append(_finding("P1", "qa_contract_check_role_invalid", "qa_contract_check receipt role 不正确。", item_id=item_id, node_id=node_id))
        if str(qa_contract_receipt.get("schema_version") or "") != QA_CONTRACT_SCHEMA_VERSION:
            findings.append(_finding("P1", "qa_contract_check_schema_invalid", "qa_contract_check receipt schema 不正确。", item_id=item_id, node_id=node_id))
        if str(qa_contract_receipt.get("gate_type") or "") != "deterministic_contract_check":
            findings.append(_finding("P1", "qa_contract_check_gate_type_invalid", "qa_contract_check receipt gate_type 不正确。", item_id=item_id, node_id=node_id))
        if str(qa_contract_receipt.get("status") or "") != "PASS":
            findings.append(_finding("P1", "qa_contract_check_not_passed", "qa_contract_check 必须严格 PASS。", item_id=item_id, node_id=node_id))
        if (
            str(qa_contract_receipt.get("item_id") or "") != item_id
            or str(qa_contract_receipt.get("node_id") or "") != node_id
            or str(qa_contract_receipt.get("family_id") or "") != family_id
        ):
            findings.append(_finding("P1", "qa_contract_check_identity_mismatch", "qa_contract_check 未绑定当前 staged item 身份。", item_id=item_id, node_id=node_id))
        if str(qa_contract_receipt.get("candidate_sha256") or "") != expected_candidate_sha:
            findings.append(_finding("P1", "qa_contract_check_candidate_sha256_mismatch", "qa_contract_check candidate_sha256 不一致。", item_id=item_id, node_id=node_id))
        if str(qa_contract_receipt.get("content_envelope_sha256") or "") != expected_content_envelope_sha:
            findings.append(_finding("P1", "qa_contract_check_content_envelope_sha256_mismatch", "qa_contract_check 未绑定当前内容 envelope。", item_id=item_id, node_id=node_id))
        if not _is_sha256(qa_contract_digest):
            findings.append(_finding("P1", "qa_contract_check_missing_digest", "qa_contract_check 缺少 report sha256。", item_id=item_id, node_id=node_id))
        if staging_decision is not None and str(staging_decision.get("qa_contract_report_sha256") or "") != qa_contract_digest:
            findings.append(_finding("P1", "qa_contract_check_decision_digest_mismatch", "qa_contract_check 与 staging decision 顶层摘要不一致。", item_id=item_id, node_id=node_id))
        qa_contract_path = str(qa_contract_receipt.get("report_path") or "")
        qa_contract_report, legacy_contract_digest, contract_file_sha = _load_report_if_present(
            root,
            qa_contract_path,
            artifact_hash_field="qa_contract_check_json_sha256",
        )
        if qa_contract_report is None:
            findings.append(_finding("P1", "qa_contract_check_report_artifact_missing", "qa_contract_check 缺少可重验 report artifact。", item_id=item_id, node_id=node_id))
        else:
            if qa_contract_digest == legacy_contract_digest and qa_contract_digest != contract_file_sha:
                findings.append(_finding("P2", "legacy_qa_contract_check_report_digest_used", "qa_contract_check 使用旧派生 digest 口径。", item_id=item_id, node_id=node_id))
            elif qa_contract_digest != contract_file_sha:
                findings.append(_finding("P1", "qa_contract_check_report_digest_mismatch", "qa_contract_check report artifact 与 receipt digest 不一致。", item_id=item_id, node_id=node_id))
            if str(qa_contract_report.get("schema_version") or "") != QA_CONTRACT_SCHEMA_VERSION:
                findings.append(_finding("P1", "qa_contract_check_report_schema_invalid", "qa_contract_check report schema 不正确。", item_id=item_id, node_id=node_id))
            if str(qa_contract_report.get("gate_type") or "") != "deterministic_contract_check":
                findings.append(_finding("P1", "qa_contract_check_report_gate_type_invalid", "qa_contract_check report gate_type 不正确。", item_id=item_id, node_id=node_id))
            if str(qa_contract_report.get("status") or "") != "PASS" or qa_contract_report.get("semantic_authority") is not False:
                findings.append(_finding("P1", "qa_contract_check_report_not_trusted", "qa_contract_check report 必须 PASS 且不声明语义裁决权。", item_id=item_id, node_id=node_id))
            if str(qa_contract_report.get("candidate_sha256") or "") != expected_candidate_sha:
                findings.append(_finding("P1", "qa_contract_check_report_candidate_sha256_mismatch", "qa_contract_check report candidate_sha256 不一致。", item_id=item_id, node_id=node_id))
            if qa_contract_report.get("write_applied") is not True:
                findings.append(_finding("P1", "qa_contract_check_report_not_applied", "qa_contract_check report 不是已写入 artifact。", item_id=item_id, node_id=node_id))
            if not _paths_match(root, str(qa_contract_report.get("qa_contract_check_json_path") or ""), qa_contract_path):
                findings.append(_finding("P1", "qa_contract_check_report_self_path_mismatch", "qa_contract_check report 自身路径与 receipt 不一致。", item_id=item_id, node_id=node_id))
            if not _paths_match(root, str(qa_contract_receipt.get("source_path") or ""), candidate_path_text):
                findings.append(_finding("P1", "qa_contract_check_source_path_mismatch", "qa_contract_check 未绑定当前 candidate artifact。", item_id=item_id, node_id=node_id))
            if candidate_file_sha and str(qa_contract_receipt.get("source_file_sha256") or "") != candidate_file_sha:
                findings.append(_finding("P1", "qa_contract_check_source_file_sha256_mismatch", "qa_contract_check source_file_sha256 不一致。", item_id=item_id, node_id=node_id))

    semantic_receipt = effective_receipts.get("guanzhi_qa_review") or {}
    semantic_report = loaded_reports.get("guanzhi_qa_review") or {}
    semantic_scope_invalid = False
    if semantic_receipt:
        if str(semantic_receipt.get("gate_type") or "") != "live_model_semantic_qa":
            findings.append(_finding("P1", "semantic_qa_review_gate_type_invalid", "semantic QA receipt 未声明 live_model_semantic_qa。", item_id=item_id, node_id=node_id))
        if str(semantic_receipt.get("provider_mode") or "") != "live_model":
            findings.append(_finding("P1", "semantic_qa_review_not_live_model", "semantic QA receipt 必须来自 live_model。", item_id=item_id, node_id=node_id))
        semantic_scope_invalid = not _qa_scope_is_empty(semantic_receipt.get("scope"))
    if semantic_report:
        if str(semantic_report.get("gate_type") or "") != "live_model_semantic_qa":
            findings.append(_finding("P1", "semantic_qa_review_report_gate_type_invalid", "semantic QA report gate_type 不正确。", item_id=item_id, node_id=node_id))
        if str(semantic_report.get("provider_mode") or "") != "live_model":
            findings.append(_finding("P1", "semantic_qa_review_report_not_live_model", "semantic QA report 必须来自 live_model。", item_id=item_id, node_id=node_id))
        semantic_scope_invalid = semantic_scope_invalid or not _qa_scope_is_empty(semantic_report.get("scope"))
        if str(semantic_report.get("qa_contract_report_sha256") or "") != qa_contract_digest:
            findings.append(_finding("P1", "semantic_qa_contract_digest_mismatch", "semantic QA 未绑定当前 qa_contract_check artifact digest。", item_id=item_id, node_id=node_id))
        route = semantic_report.get("route") if isinstance(semantic_report.get("route"), dict) else {}
        prompt_meta = semantic_report.get("prompt_meta") if isinstance(semantic_report.get("prompt_meta"), dict) else {}
        if not route.get("raw_response_sha256") or not route.get("structured_json_mode"):
            findings.append(_finding("P1", "semantic_qa_missing_route_evidence", "semantic QA 缺少真实模型响应与 structured mode 证据。", item_id=item_id, node_id=node_id))
        if not prompt_meta.get("rendered_prompt_sha256") or not prompt_meta.get("response_schema_sha256"):
            findings.append(_finding("P1", "semantic_qa_missing_prompt_evidence", "semantic QA 缺少 prompt/schema digest。", item_id=item_id, node_id=node_id))
        normalization = semantic_report.get("status_normalization") if isinstance(semantic_report.get("status_normalization"), dict) else {}
        if normalization.get("authority") != "deterministic_from_profile_verdicts" or normalization.get("model_overall_status_is_advisory") is not True:
            findings.append(_finding("P1", "semantic_qa_normalization_evidence_invalid", "semantic QA 缺少确定性状态归一化证据。", item_id=item_id, node_id=node_id))
    if semantic_scope_invalid:
        findings.append(_finding("P1", "semantic_qa_scope_not_empty", "semantic QA 必须严格 PASS 且 receipt/artifact 均没有 scope restrictions。", item_id=item_id, node_id=node_id))
    return findings


def build_full_bank_acceptance(
    *,
    root: Path,
    bank_path: Path = DEFAULT_STAGED_BANK_PATH,
    subject: str = "math",
    require_target: bool = False,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    resolved_bank = bank_path if bank_path.is_absolute() else root / bank_path
    bank_bytes = resolved_bank.read_bytes()
    bank = json.loads(bank_bytes.decode("utf-8"))
    bank_sha256 = hashlib.sha256(bank_bytes).hexdigest()

    nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    items = list(bank.get("items") or [])
    findings: list[dict[str, str]] = []

    if bank.get("status") != "staged_not_active":
        findings.append(_finding("P1", "bank_not_staged_not_active", "全量验收只能检查 staged_not_active 题库，不能检查 active 或 sample 当成正式库。"))
    if bank.get("schema_version") != "2026-07-23.codex-admin.staged-question-bank.v1":
        findings.append(_finding("P1", "unsupported_staged_bank_schema", "staged 题库 schema 不正确。"))

    if int(bank.get("item_count") or 0) != len(items):
        findings.append(_finding("P1", "bank_item_count_mismatch", f"staged 题库声明 item_count={bank.get('item_count')}，实际为 {len(items)}。"))

    raw_by_node: Counter[str] = Counter()
    raw_by_family: Counter[str] = Counter()
    raw_by_difficulty: Counter[str] = Counter()
    qualified_by_node: Counter[str] = Counter()
    qualified_by_family: Counter[str] = Counter()
    qualified_by_difficulty: Counter[str] = Counter()
    qualified_family_by_node: dict[str, Counter[str]] = defaultdict(Counter)
    provider_modes: Counter[str] = Counter()
    item_records: list[dict[str, Any]] = []
    findings_by_item: dict[str, list[dict[str, str]]] = defaultdict(list)

    previous_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item_id = str(item.get("id") or "")
        node_id = str(item.get("node_id") or "")
        family_id, item_findings = _contract_findings(
            item=item,
            nodes=nodes,
            blueprints=blueprints,
            families=families,
        )
        difficulty = str(item.get("difficulty") or "")
        raw_by_node[node_id] += 1
        raw_by_family[family_id] += 1
        raw_by_difficulty[difficulty or "unknown"] += 1
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        model_receipt = (((quality.get("review_evidence") or {}).get("receipts") or {}).get("model_expert_board_review") or {})
        provider_modes[str(model_receipt.get("role") or "")] += 1
        item_findings.extend(
            _receipt_findings(root=root, item=item, previous_items=previous_items)
        )
        findings_by_item[item_id].extend(item_findings)
        findings.extend(item_findings)
        item_records.append({
            "index": index,
            "item_id": item_id,
            "node_id": node_id,
            "family_id": family_id,
            "difficulty": difficulty or "unknown",
        })
        previous_items.append(item)

    ids_to_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in item_records:
        ids_to_records[str(record["item_id"])].append(record)
    for item_id, records in ids_to_records.items():
        if item_id and len(records) > 1:
            for record in records:
                finding = _finding("P1", "duplicate_item_id", f"题目 id 重复：{item_id}。", item_id=item_id, node_id=str(record["node_id"]))
                findings_by_item[item_id].append(finding)
                findings.append(finding)

    for duplicate in _duplicate_fingerprint_groups(items):
        duplicate_ids = [str(value) for value in duplicate.get("item_ids") or []]
        for duplicate_id in duplicate_ids:
            finding = _finding(
                "P1",
                "duplicate_structure_fingerprint",
                f"结构指纹重复：{duplicate['fingerprint']} -> {', '.join(duplicate['item_ids'])}",
                item_id=duplicate_id,
            )
            findings_by_item[duplicate_id].append(finding)
            findings.append(finding)

    qualified_item_ids: list[str] = []
    disqualified_items: list[dict[str, Any]] = []
    legacy_pending_revalidation_item_ids: list[str] = []
    migration_finding_counts: Counter[str] = Counter()
    for record in item_records:
        item_id = str(record["item_id"])
        item_findings = findings_by_item.get(item_id, [])
        for finding in item_findings:
            if finding.get("severity") == "P2":
                migration_finding_counts[str(finding.get("code") or "")] += 1
        blocking_codes = sorted({str(finding.get("code") or "") for finding in item_findings if finding.get("severity") in FAIL_SEVERITIES})
        if blocking_codes:
            qualification_status = (
                "legacy_pending_revalidation"
                if set(blocking_codes) & LEGACY_REVALIDATION_CODES
                else "disqualified"
            )
            if qualification_status == "legacy_pending_revalidation":
                legacy_pending_revalidation_item_ids.append(item_id)
            disqualified_items.append({
                "item_id": item_id,
                "node_id": record["node_id"],
                "family_id": record["family_id"],
                "qualification_status": qualification_status,
                "blocking_codes": blocking_codes,
            })
            continue
        qualified_item_ids.append(item_id)
        qualified_by_node[str(record["node_id"])] += 1
        qualified_by_family[str(record["family_id"])] += 1
        qualified_by_difficulty[str(record["difficulty"])] += 1
        qualified_family_by_node[str(record["node_id"])][str(record["family_id"])] += 1

    budget_gaps: list[dict[str, Any]] = []
    target_gaps: list[dict[str, Any]] = []
    target_shortfalls: list[dict[str, Any]] = []
    over_max_gaps: list[dict[str, Any]] = []
    family_gaps: list[dict[str, Any]] = []
    for node_id, blueprint in sorted(blueprints.items()):
        budget = blueprint.get("candidate_budget") or {}
        current = qualified_by_node.get(node_id, 0)
        raw_current = raw_by_node.get(node_id, 0)
        minimum = int(budget.get("min") or 0)
        target = int(budget.get("target") or minimum)
        maximum = int(budget.get("max") or target)
        if current < minimum:
            gap = {
                "node_id": node_id,
                "node_name": blueprint.get("node_name"),
                "current": current,
                "raw_current": raw_current,
                "min": minimum,
                "target": target,
                "max": maximum,
                "missing_to_min": minimum - current,
                "missing_to_target": max(0, target - current),
            }
            budget_gaps.append(gap)
            findings.append(_finding("P1", "node_below_min_candidate_budget", f"节点候选题低于最小预算：{current}/{minimum}。", node_id=node_id))
        elif current < target:
            gap = {
                "node_id": node_id,
                "node_name": blueprint.get("node_name"),
                "current": current,
                "raw_current": raw_current,
                "target": target,
                "max": maximum,
                "missing_to_target": target - current,
            }
            target_shortfalls.append(gap)
            if require_target:
                target_gaps.append(gap)
        if current > maximum:
            gap = {
                "node_id": node_id,
                "node_name": blueprint.get("node_name"),
                "current": current,
                "raw_current": raw_current,
                "max": maximum,
                "over_max_by": current - maximum,
            }
            over_max_gaps.append(gap)
            findings.append(_finding("P1", "node_above_max_candidate_budget", f"节点候选题超过最大预算：{current}/{maximum}。", node_id=node_id))
        for family in blueprint.get("family_plan") or []:
            family_id = str(family.get("family_id") or "")
            planned = int(family.get("target_count") or 0)
            if not family_id or planned <= 0:
                continue
            current_family = qualified_family_by_node[node_id].get(family_id, 0)
            family_minimum = 1 if not require_target else planned
            if current_family < family_minimum:
                family_gaps.append(
                    {
                        "node_id": node_id,
                        "family_id": family_id,
                        "current": current_family,
                        "required": family_minimum,
                        "planned_target": planned,
                    }
                )
                findings.append(_finding("P1", "node_family_coverage_gap", f"节点题型家族覆盖不足：{family_id} {current_family}/{family_minimum}。", node_id=node_id))

    if require_target:
        for gap in target_gaps:
            findings.append(_finding("P1", "node_below_target_candidate_budget", f"节点候选题低于目标预算：{gap['current']}/{gap['target']}。", node_id=str(gap["node_id"])))

    status = "PASS" if not any(f["severity"] in FAIL_SEVERITIES for f in findings) else "NEEDS_FIX"

    return {
        "schema_version": FULL_BANK_ACCEPTANCE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subject": subject,
        "status": status,
        "bank_path": _relpath(root, resolved_bank),
        "question_bank_version": str(bank.get("question_bank_version") or ""),
        "question_bank_status": str(bank.get("status") or ""),
        "require_target": bool(require_target),
        "source_digests": {
            "graph": _source_digest(root, paths.graph_path),
            "blueprints": _source_digest(root, paths.blueprint_path),
            "taxonomy": _source_digest(root, paths.taxonomy_path),
            "staged_bank": {"path": _relpath(root, resolved_bank), "sha256": bank_sha256},
        },
        "item_count": len(items),
        "raw_item_count": len(items),
        "qualified_item_count": len(qualified_item_ids),
        "disqualified_item_count": len(disqualified_items),
        "legacy_pending_revalidation_count": len(legacy_pending_revalidation_item_ids),
        "graph_node_count": len(nodes),
        "blueprint_node_count": len(blueprints),
        "taxonomy_family_count": len(families),
        "covered_node_count": len([node_id for node_id, count in qualified_by_node.items() if node_id and count]),
        "covered_family_count": len([family_id for family_id, count in qualified_by_family.items() if family_id and count]),
        "counts_by_node": dict(sorted(qualified_by_node.items())),
        "counts_by_family": dict(sorted(qualified_by_family.items())),
        "counts_by_difficulty": dict(sorted(qualified_by_difficulty.items())),
        "raw_counts_by_node": dict(sorted(raw_by_node.items())),
        "raw_counts_by_family": dict(sorted(raw_by_family.items())),
        "raw_counts_by_difficulty": dict(sorted(raw_by_difficulty.items())),
        "qualified_item_ids": qualified_item_ids,
        "legacy_pending_revalidation_item_ids": legacy_pending_revalidation_item_ids,
        "disqualified_items": disqualified_items,
        "v18_item_contract": {
            "version": V18_ITEM_CONTRACT_VERSION,
            "canonical_family_field": V18_CANONICAL_FAMILY_FIELD,
            "canonical_score_field": V18_CANONICAL_SCORE_FIELD,
            "migration_aliases": {
                "question_family_id": V18_CANONICAL_FAMILY_FIELD,
                "scoring_targets": V18_CANONICAL_SCORE_FIELD,
            },
            "migration_finding_counts": dict(sorted(migration_finding_counts.items())),
        },
        "model_expert_role_counts": dict(sorted(provider_modes.items())),
        "budget_gaps": budget_gaps,
        "target_gaps": target_gaps,
        "target_shortfalls": target_shortfalls,
        "over_max_gaps": over_max_gaps,
        "family_gaps": family_gaps,
        "finding_counts": _counts(findings),
        "findings": sorted(findings, key=lambda f: (f.get("severity", ""), f.get("node_id", ""), f.get("code", ""), f.get("item_id", ""))),
        "full_bank_acceptance_sha256": _digest_json(
            {
                "bank": bank_sha256,
                "raw_item_count": len(items),
                "qualified_item_count": len(qualified_item_ids),
                "counts_by_node": dict(sorted(qualified_by_node.items())),
                "counts_by_family": dict(sorted(qualified_by_family.items())),
                "findings": findings,
            }
        ),
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["continue_question_production"] if status == "NEEDS_FIX" else ["create_activation_manifest_after_browser_and_live_runtime_gates"],
    }


def render_full_bank_acceptance_markdown(report: dict[str, Any]) -> str:
    gap_lines = [
        f"| {gap.get('node_id', '')} | {gap.get('node_name', '')} | {gap.get('raw_current', '')} | {gap.get('current', '')} | {gap.get('min', '')} | {gap.get('target', '')} | {gap.get('max', '')} |"
        for gap in report.get("budget_gaps") or []
    ] or ["| | | | | | | |"]
    family_lines = [
        f"| {gap.get('node_id', '')} | {gap.get('family_id', '')} | {gap.get('current', '')} | {gap.get('required', '')} |"
        for gap in report.get("family_gaps") or []
    ] or ["| | | | |"]
    finding_lines = [
        f"| {finding.get('severity', '')} | {finding.get('node_id', '')} | {finding.get('item_id', '')} | {finding.get('code', '')} | {finding.get('message', '')} |"
        for finding in report.get("findings") or []
    ] or ["| | | | | |"]
    return f"""# Full Question Bank Acceptance

Status: `{report.get('status')}`

Created At: {report.get('created_at')}

Bank: `{report.get('bank_path')}`

Raw Items: {report.get('raw_item_count', report.get('item_count'))}

Qualified Items: {report.get('qualified_item_count')}

Disqualified Items: {report.get('disqualified_item_count')}

Covered Nodes: {report.get('covered_node_count')} / {report.get('blueprint_node_count')}

Covered Families: {report.get('covered_family_count')} / {report.get('taxonomy_family_count')}

Activation Implication: `{report.get('activation_implication')}`

## Budget Gaps

| Node | Name | Raw | Qualified | Min | Target | Max |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(gap_lines)}

## Family Gaps

| Node | Family | Current | Required |
|---|---|---:|---:|
{chr(10).join(family_lines)}

## Findings

| Severity | Node | Item | Code | Message |
|---|---|---|---|---|
{chr(10).join(finding_lines)}
"""


def write_full_bank_acceptance(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    report_id_input = "|".join([
        str(report.get("schema_version") or ""),
        str(report.get("status") or ""),
        str(report.get("bank_path") or ""),
        str(report.get("full_bank_acceptance_sha256") or ""),
    ])
    report_id = "FULL-BANK-" + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    markdown_rel = Path("docs/system/admin_reports/full_bank") / f"{datetime.now(timezone.utc).date()}-{report_id}.md"
    json_rel = Path("data/admin/full_bank") / f"{report_id}.json"
    result = {
        **report,
        "full_bank_report_id": report_id,
        "full_bank_markdown_path": str(markdown_rel),
        "full_bank_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_full_bank_acceptance_markdown(report), encoding="utf-8")
    result["full_bank_markdown_sha256"] = _sha256(markdown_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["full_bank_json_sha256"] = _sha256(json_path)
    return result
