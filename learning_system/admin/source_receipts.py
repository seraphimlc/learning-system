from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_TYPES = {
    "user_owned",
    "open_license",
    "commercial_reference",
    "public_web_reference",
    "publisher_catalog_reference",
    "ai_original",
    "teacher_original",
}
USAGE_MODES = {
    "direct_import",
    "adapted_import",
    "structure_reference_only",
    "scope_reference_only",
    "rejected",
}
CAPTURE_POLICIES = {
    "metadata_only",
    "excerpt_with_permission",
    "full_content_with_license",
    "no_capture",
}


class SourceReceiptError(ValueError):
    pass


@dataclass(frozen=True)
class SourceCandidate:
    name: str
    source_type: str
    url_or_file: str = ""
    subject: str = "math"
    stage: str = "小升初衔接 + 七上预学"
    license_observation: str = "unclear"
    terms_url: str = ""
    direct_use_allowed: bool = False
    adaptation_allowed: bool = False
    ai_ingestion_allowed: bool = False
    commercial_use_allowed: bool = False
    attribution_required: bool = False
    attribution_text: str = ""
    mapped_node_ids: list[str] = field(default_factory=list)
    mapped_question_family_ids: list[str] = field(default_factory=list)
    notes: str = ""


def _slug(text: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:48]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"source-{digest}"


def source_id_for(candidate: SourceCandidate) -> str:
    digest_input = "|".join([candidate.name, candidate.source_type, candidate.url_or_file])
    return f"SRC-{_slug(candidate.name)}-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:8]}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decide_usage(candidate: SourceCandidate) -> tuple[str, str, str, str]:
    if candidate.source_type not in SOURCE_TYPES:
        raise SourceReceiptError(f"ADMIN_INVALID_SOURCE_TYPE: {candidate.source_type}")
    commercial_like = candidate.source_type in {"commercial_reference", "publisher_catalog_reference"}
    if commercial_like:
        return (
            "structure_reference_only",
            "no_capture",
            "needs_license_review",
            "Commercial/publisher sources default to structure notes only without explicit authorization.",
        )
    if candidate.direct_use_allowed:
        capture_policy = "full_content_with_license"
        usage_mode = "direct_import"
        review_status = "approved_for_direct_import"
    elif candidate.adaptation_allowed:
        capture_policy = "excerpt_with_permission"
        usage_mode = "adapted_import"
        review_status = "approved_for_adaptation"
    elif candidate.source_type in {"open_license", "public_web_reference"}:
        capture_policy = "metadata_only"
        usage_mode = "scope_reference_only"
        review_status = "needs_license_review"
    else:
        capture_policy = "metadata_only"
        usage_mode = "scope_reference_only"
        review_status = "candidate"
    reason = "Direct/adapted import requires explicit allowed flags; otherwise use scope or structure only."
    return usage_mode, capture_policy, review_status, reason


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def build_source_receipt(candidate: SourceCandidate, *, created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_id = source_id_for(candidate)
    usage_mode, capture_policy, review_status, decision_reason = _decide_usage(candidate)
    risk_level = "high" if capture_policy == "no_capture" else "medium" if review_status == "needs_license_review" else "low"
    return {
        "schema_version": "2026-07-23.codex-admin.source-analysis-receipt.v1",
        "receipt_id": f"REC-{source_id}-{created_at[:10]}",
        "source_id": source_id,
        "created_at": created_at,
        "source_name": candidate.name,
        "source_type": candidate.source_type,
        "source_url_or_file": candidate.url_or_file,
        "subject": candidate.subject,
        "stage": candidate.stage,
        "license_observation": candidate.license_observation,
        "terms_url": candidate.terms_url,
        "direct_use_allowed": candidate.direct_use_allowed,
        "adaptation_allowed": candidate.adaptation_allowed,
        "ai_ingestion_allowed": candidate.ai_ingestion_allowed,
        "commercial_use_allowed": candidate.commercial_use_allowed,
        "attribution_required": candidate.attribution_required,
        "attribution_text": candidate.attribution_text,
        "mapped_node_ids": list(candidate.mapped_node_ids),
        "mapped_question_family_ids": list(candidate.mapped_question_family_ids),
        "usage_mode": usage_mode,
        "capture_policy": capture_policy,
        "review_status": review_status,
        "risk_level": risk_level,
        "decision_reason": decision_reason,
        "notes": candidate.notes,
    }


def render_source_receipt_markdown(receipt: dict[str, Any]) -> str:
    mapped_nodes = "\n".join(f"| {node_id} | 待人工映射 | unclear |" for node_id in receipt["mapped_node_ids"]) or "| | | |"
    mapped_families = "\n".join(
        f"| {family_id} | 待人工映射 | {receipt['usage_mode']} |"
        for family_id in receipt["mapped_question_family_ids"]
    ) or "| | | |"
    forbidden_capture = "题干、答案、解析、图片、图形、表格、版式" if receipt["capture_policy"] == "no_capture" else "未在许可中明确允许的内容"
    return f"""# Source Analysis Receipt

Status: `{receipt['review_status']}`

Receipt ID: {receipt['receipt_id']}

Source ID: {receipt['source_id']}

Created At: {receipt['created_at']}

Reviewer: Codex admin module

## Source Identity

- Name: {receipt['source_name']}
- Source type: {receipt['source_type']}
- URL or file: {receipt['source_url_or_file']}
- Accessed at: {receipt['created_at']}
- Subject: {receipt['subject']}
- Stage: {receipt['stage']}

## Access Facts

- Publicly accessible: unclear
- Login/paywall required: unclear
- User-provided authorization: no
- Captured content policy: `{receipt['capture_policy']}`

## License / Terms Observation

- Observed license: {receipt['license_observation']}
- Terms URL: {receipt['terms_url']}
- Attribution required: {_bool_text(receipt['attribution_required'])}
- Adaptation allowed: {_bool_text(receipt['adaptation_allowed'])}
- AI ingestion allowed: {_bool_text(receipt['ai_ingestion_allowed'])}
- Commercial use allowed: {_bool_text(receipt['commercial_use_allowed'])}
- Confidence: `unclear`

## Allowed Use

- Scope/reference use: yes
- Structure reference: {'yes' if receipt['usage_mode'] in {'structure_reference_only', 'scope_reference_only'} else 'review required'}
- Direct import: {_bool_text(receipt['direct_use_allowed'])}
- Adapted import: {_bool_text(receipt['adaptation_allowed'])}
- Attribution text: {receipt['attribution_text']}

## Forbidden Use

- Content not to capture: {forbidden_capture}
- Content not to generate from: full commercial/private corpus without authorization
- Terms or license risks: {receipt['decision_reason']}

## Graph Mapping

| Node ID | Why relevant | Confidence |
|---|---|---|
{mapped_nodes}

## Question Family Mapping

| Family ID | Observed structure | Use mode |
|---|---|---|
{mapped_families}

## Inventory Implications

- Coverage gap: needs inventory comparison
- Suggested original-generation task: generate original questions only after node/family mapping review
- Suggested expert reviewer: education_expert

## Risk

- Risk level: `{receipt['risk_level']}`
- Main risk: {receipt['decision_reason']}
- Required next action: source/license review before import

## Decision

- Recommended usage_mode: `{receipt['usage_mode']}`
- Recommended review_status: `{receipt['review_status']}`
- Activation implication: this receipt does not authorize child runtime activation

## Notes

{receipt['notes']}

## Signoff

- Reviewer conclusion: pending independent review
- Follow-up owner: Codex admin module
"""


def write_source_receipt(candidate: SourceCandidate, *, root: Path, apply: bool = False) -> dict[str, Any]:
    receipt = build_source_receipt(candidate)
    source_id = receipt["source_id"]
    markdown_rel = Path("docs/system/admin_reports/source_receipts") / f"{receipt['created_at'][:10]}-{source_id}.md"
    json_rel = Path("data/admin/source_receipts") / f"{source_id}.json"
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown = render_source_receipt_markdown(receipt)
    result = {
        **receipt,
        "receipt_markdown_path": str(markdown_rel),
        "receipt_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        result["receipt_markdown_preview"] = markdown
        return result
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    result["receipt_markdown_sha256"] = _sha256(markdown_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["receipt_json_sha256"] = _sha256(json_path)
    return result
