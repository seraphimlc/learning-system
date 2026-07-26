#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_system.admin.staging import (  # noqa: E402
    STAGED_BANK_SCHEMA_VERSION,
    STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION,
    validate_staged_bank_content_envelopes,
    validate_staged_bank_review_artifacts,
)
from learning_system.admin.full_bank_acceptance import build_full_bank_acceptance  # noqa: E402


DEFAULT_MANIFEST_PATH = ROOT / "data/question_banks/v18/sample_gate_manifest_v18.json"

SAMPLE_SCOPE_LIMITED_STATUS = "sample_static_qa_passed_scope_limited"
ACTIVATION_READY_STATUS = "full_bank_qa_passed_ready_for_staging"
ACTIVATION_MANIFEST_SCHEMA_VERSION = "2026-07-24.question-bank-v18-activation-manifest.v2"
ACTIVATION_RECEIPT_SCHEMA_VERSION = "2026-07-24.question-bank-v18-activation-receipt.v1"
FULL_BANK_ACCEPTANCE_SCHEMA_VERSION = "2026-07-23.codex-admin.full-bank-acceptance.v1"
REQUIRED_ACTIVATION_RECEIPTS = {
    "expert_reviewed",
    "qa_passed",
    "answer_contracts_active",
    "candidate_packet_mapping_passed",
    "browser_child_flow_passed",
    "live_model_grading_passed",
}

_ACTIVATION_MANIFEST_KEYS = {
    "schema_version",
    "status",
    "subject",
    "question_bank",
    "full_bank_acceptance",
    "review_receipts",
    "not_authorized_for",
}
_QUESTION_BANK_BINDING_KEYS = {
    "path",
    "sha256",
    "schema_version",
    "status",
    "question_bank_version",
    "item_count",
    "content_envelope_schema_version",
}
_FULL_BANK_BINDING_KEYS = {
    "path",
    "sha256",
    "schema_version",
    "status",
    "full_bank_acceptance_sha256",
}
_ACTIVATION_RECEIPT_KEYS = {
    "receipt_type",
    "path",
    "sha256",
    "schema_version",
    "status",
    "object_identity",
}
_OBJECT_IDENTITY_KEYS = {
    "subject",
    "question_bank_version",
    "staged_bank_sha256",
    "full_bank_acceptance_sha256",
}


class GateError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid JSON artifact: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON artifact must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_exact_keys(value: Any, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise GateError(f"{label} schema mismatch: missing={missing}, extra={extra}")
    return value


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise GateError(f"{label} missing: {path}")
    return _load(path)


def _validate_file_digest(path: Path, expected: str, *, label: str) -> str:
    if not expected:
        raise GateError(f"{label} missing sha256")
    try:
        actual = _sha256(path)
    except OSError as exc:
        raise GateError(f"{label} cannot be read: {path}: {exc}") from exc
    if actual != expected:
        raise GateError(f"{label} digest mismatch")
    return actual


def _project_path(path_text: str, *, manifest_path: Path) -> Path:
    if not path_text:
        raise GateError("artifact path must not be empty")
    path = Path(path_text)
    if path.is_absolute():
        return path
    root = _infer_project_root(manifest_path)
    return root / path


def _infer_project_root(manifest_path: Path) -> Path:
    resolved = manifest_path.resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if (parent / "AGENTS.md").exists() and (parent / "data").exists():
            return parent
    return ROOT


def validate_input_digests(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest = _load(manifest_path)
    digests = manifest.get("input_digests") or {}
    if not digests:
        raise GateError("manifest missing input_digests")
    checked: dict[str, str] = {}
    for name, entry in sorted(digests.items()):
        path_text = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        if not path_text or not expected:
            raise GateError(f"manifest digest entry incomplete: {name}")
        path = _project_path(path_text, manifest_path=manifest_path)
        if not path.exists():
            raise GateError(f"manifest input missing: {name}:{path}")
        actual = _sha256(path)
        if actual != expected:
            raise GateError(f"manifest digest mismatch: {name}:{path_text}")
        checked[name] = actual
    return checked


def validate_sample_integrity(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest = _load(manifest_path)
    checked = validate_input_digests(manifest_path)
    status = str(manifest.get("status") or "")
    if status != SAMPLE_SCOPE_LIMITED_STATUS:
        raise GateError(f"sample gate manifest has unexpected status: {status}")
    if manifest.get("validation", {}).get("status") != "PASS":
        raise GateError("sample validation did not pass")
    question_ids = manifest.get("sample_question_ids") or []
    if len(question_ids) != int(manifest.get("sample_item_count") or 0):
        raise GateError("sample_question_ids count does not match sample_item_count")
    if len(question_ids) != len(set(question_ids)):
        raise GateError("sample_question_ids contains duplicates")
    if "child_runtime_activation" not in (manifest.get("not_authorized_for") or []):
        raise GateError("sample manifest must explicitly forbid child runtime activation")
    return {
        "status": "PASS",
        "mode": "sample_integrity",
        "manifest_status": status,
        "checked_inputs": sorted(checked),
        "sample_item_count": int(manifest.get("sample_item_count") or 0),
        "activation_allowed": False,
    }


def validate_activation_readiness(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    acceptance_builder=build_full_bank_acceptance,
) -> dict[str, Any]:
    manifest = _load(manifest_path)
    status = str(manifest.get("status") or "")
    if status != ACTIVATION_READY_STATUS:
        raise GateError(
            f"question bank is not activation-ready: {status}; "
            f"expected {ACTIVATION_READY_STATUS}"
        )
    _require_exact_keys(manifest, _ACTIVATION_MANIFEST_KEYS, label="activation manifest")
    if manifest.get("schema_version") != ACTIVATION_MANIFEST_SCHEMA_VERSION:
        raise GateError("activation manifest schema_version is unsupported")
    forbidden = set(manifest.get("not_authorized_for") or [])
    if "child_runtime_activation" in forbidden:
        raise GateError("manifest explicitly forbids child runtime activation")
    if not isinstance(manifest.get("not_authorized_for"), list):
        raise GateError("activation manifest not_authorized_for must be a list")

    bank_binding = _require_exact_keys(
        manifest.get("question_bank"),
        _QUESTION_BANK_BINDING_KEYS,
        label="activation manifest question_bank",
    )
    if bank_binding.get("schema_version") != STAGED_BANK_SCHEMA_VERSION:
        raise GateError("activation manifest question_bank schema_version is unsupported")
    if bank_binding.get("status") != "staged_not_active":
        raise GateError("activation manifest question_bank must remain staged_not_active")
    if bank_binding.get("content_envelope_schema_version") != STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION:
        raise GateError("activation manifest content envelope schema_version is unsupported")
    bank_path = _project_path(str(bank_binding.get("path") or ""), manifest_path=manifest_path)
    bank = _load_object(bank_path, label="staged question bank")
    staged_bank_sha256 = _validate_file_digest(
        bank_path,
        str(bank_binding.get("sha256") or ""),
        label="staged question bank",
    )
    if bank.get("schema_version") != STAGED_BANK_SCHEMA_VERSION or bank.get("status") != "staged_not_active":
        raise GateError("staged question bank schema or status mismatch")
    question_bank_version = str(bank.get("question_bank_version") or "")
    if question_bank_version != str(bank_binding.get("question_bank_version") or ""):
        raise GateError("staged question bank version mismatch")
    item_count = len(bank.get("items") or [])
    if int(bank.get("item_count") or 0) != item_count or int(bank_binding.get("item_count") or -1) != item_count:
        raise GateError("staged question bank item_count mismatch")
    try:
        envelope_report = validate_staged_bank_content_envelopes(bank)
    except ValueError as exc:
        raise GateError(f"staged question bank content envelope validation failed: {exc}") from exc
    try:
        review_artifact_report = validate_staged_bank_review_artifacts(
            bank,
            root=_infer_project_root(manifest_path),
        )
    except ValueError as exc:
        raise GateError(f"staged question bank review artifact validation failed: {exc}") from exc

    full_bank_binding = _require_exact_keys(
        manifest.get("full_bank_acceptance"),
        _FULL_BANK_BINDING_KEYS,
        label="activation manifest full_bank_acceptance",
    )
    if full_bank_binding.get("schema_version") != FULL_BANK_ACCEPTANCE_SCHEMA_VERSION:
        raise GateError("full-bank acceptance schema_version is unsupported")
    if full_bank_binding.get("status") != "PASS":
        raise GateError("activation requires full-bank acceptance PASS")
    full_bank_path = _project_path(str(full_bank_binding.get("path") or ""), manifest_path=manifest_path)
    full_bank = _load_object(full_bank_path, label="full-bank acceptance artifact")
    _validate_file_digest(
        full_bank_path,
        str(full_bank_binding.get("sha256") or ""),
        label="full-bank acceptance artifact",
    )
    if full_bank.get("schema_version") != FULL_BANK_ACCEPTANCE_SCHEMA_VERSION or full_bank.get("status") != "PASS":
        raise GateError("full-bank acceptance artifact is not PASS")
    if full_bank.get("require_target") is not True:
        raise GateError("activation requires full-bank acceptance with require_target=true")
    full_bank_acceptance_sha256 = str(full_bank.get("full_bank_acceptance_sha256") or "")
    if not full_bank_acceptance_sha256:
        raise GateError("full-bank acceptance artifact missing object digest")
    if full_bank_acceptance_sha256 != str(full_bank_binding.get("full_bank_acceptance_sha256") or ""):
        raise GateError("full-bank acceptance object digest mismatch")
    if str(full_bank.get("question_bank_version") or "") != question_bank_version:
        raise GateError("full-bank acceptance question bank version mismatch")
    if int(full_bank.get("item_count") or -1) != item_count:
        raise GateError("full-bank acceptance item_count mismatch")
    if _project_path(str(full_bank.get("bank_path") or ""), manifest_path=manifest_path).resolve() != bank_path.resolve():
        raise GateError("full-bank acceptance bank path mismatch")
    source_digests = full_bank.get("source_digests") if isinstance(full_bank.get("source_digests"), dict) else {}
    staged_source = source_digests.get("staged_bank") if isinstance(source_digests.get("staged_bank"), dict) else {}
    if _project_path(str(staged_source.get("path") or ""), manifest_path=manifest_path).resolve() != bank_path.resolve():
        raise GateError("full-bank acceptance staged bank source path mismatch")
    if str(staged_source.get("sha256") or "") != staged_bank_sha256:
        raise GateError("full-bank acceptance staged bank digest mismatch")

    project_root = _infer_project_root(manifest_path)
    try:
        recomputed_full_bank = acceptance_builder(
            root=project_root,
            bank_path=bank_path,
            subject=str(manifest.get("subject") or ""),
            require_target=True,
        )
    except Exception as exc:  # noqa: BLE001 - activation must fail closed on recomputation errors.
        raise GateError(f"full-bank acceptance recomputation failed: {exc}") from exc
    if recomputed_full_bank.get("status") != "PASS":
        raise GateError("recomputed full-bank acceptance is not PASS")
    recomputed_digest = str(recomputed_full_bank.get("full_bank_acceptance_sha256") or "")
    if not recomputed_digest or recomputed_digest != full_bank_acceptance_sha256:
        raise GateError("recomputed full-bank acceptance object digest mismatch")
    for field in (
        "qualified_item_count",
        "disqualified_item_count",
        "qualified_item_ids",
        "finding_counts",
        "counts_by_node",
        "counts_by_family",
        "source_digests",
    ):
        if recomputed_full_bank.get(field) != full_bank.get(field):
            raise GateError(f"recomputed full-bank acceptance field mismatch: {field}")

    expected_identity = {
        "subject": str(manifest.get("subject") or ""),
        "question_bank_version": question_bank_version,
        "staged_bank_sha256": staged_bank_sha256,
        "full_bank_acceptance_sha256": full_bank_acceptance_sha256,
    }
    receipt_entries = manifest.get("review_receipts")
    if not isinstance(receipt_entries, list):
        raise GateError("activation manifest review_receipts must be a list")
    checked_receipts: dict[str, str] = {}
    for entry_value in receipt_entries:
        entry = _require_exact_keys(entry_value, _ACTIVATION_RECEIPT_KEYS, label="activation receipt binding")
        receipt_type = str(entry.get("receipt_type") or "")
        if receipt_type not in REQUIRED_ACTIVATION_RECEIPTS:
            raise GateError(f"activation manifest has unsupported receipt_type: {receipt_type}")
        if receipt_type in checked_receipts:
            raise GateError(f"activation manifest has duplicate receipt_type: {receipt_type}")
        if entry.get("schema_version") != ACTIVATION_RECEIPT_SCHEMA_VERSION:
            raise GateError(f"activation receipt schema_version is unsupported: {receipt_type}")
        if entry.get("status") != "PASS":
            raise GateError(f"activation receipt is not PASS: {receipt_type}")
        identity = _require_exact_keys(entry.get("object_identity"), _OBJECT_IDENTITY_KEYS, label=f"activation receipt identity:{receipt_type}")
        if identity != expected_identity:
            raise GateError(f"activation receipt object identity mismatch: {receipt_type}")
        receipt_path = _project_path(str(entry.get("path") or ""), manifest_path=manifest_path)
        receipt = _load_object(receipt_path, label=f"activation receipt artifact:{receipt_type}")
        receipt_sha256 = _validate_file_digest(
            receipt_path,
            str(entry.get("sha256") or ""),
            label=f"activation receipt artifact:{receipt_type}",
        )
        if receipt.get("schema_version") != ACTIVATION_RECEIPT_SCHEMA_VERSION:
            raise GateError(f"activation receipt artifact schema mismatch: {receipt_type}")
        if receipt.get("receipt_type") != receipt_type or receipt.get("status") != "PASS":
            raise GateError(f"activation receipt artifact status or type mismatch: {receipt_type}")
        if receipt.get("object_identity") != expected_identity:
            raise GateError(f"activation receipt artifact identity mismatch: {receipt_type}")
        checked_receipts[receipt_type] = receipt_sha256
    missing = sorted(REQUIRED_ACTIVATION_RECEIPTS - set(checked_receipts))
    if missing:
        raise GateError("activation manifest missing receipts: " + ",".join(missing))
    return {
        "status": "PASS",
        "mode": "activation_readiness",
        "manifest_status": status,
        "question_bank_version": question_bank_version,
        "staged_bank_sha256": staged_bank_sha256,
        "full_bank_acceptance_sha256": full_bank_acceptance_sha256,
        "validated_item_count": item_count,
        "content_envelope_validation": envelope_report,
        "review_artifact_validation": review_artifact_report,
        "checked_receipts": dict(sorted(checked_receipts.items())),
        "activation_allowed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument(
        "--mode",
        choices=["sample-integrity", "activation-readiness"],
        default="sample-integrity",
    )
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    try:
        if args.mode == "sample-integrity":
            report = validate_sample_integrity(manifest_path)
        else:
            report = validate_activation_readiness(manifest_path)
    except GateError as exc:
        print(f"V18_ACTIVATION_GATE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
