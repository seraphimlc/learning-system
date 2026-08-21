"""Canonical identity and append-only receipt contracts for question-bank v20."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA_VERSION = "question-bank-v20-receipt.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_FIELDS = frozenset(
    {
        "manifest_sha256",
        "slot_id",
        "operation_key",
        "candidate_version",
        "content_hash",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_kind",
        "receipt_id",
        *IDENTITY_FIELDS,
        "payload",
        "receipt_digest_sha256",
    }
)


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for every v20 digest."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _require_candidate_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("candidate_version must be a positive integer")
    return value


def _require_receipt_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("receipt_id must be a nonempty string")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("receipt_id must be a safe filename component")
    return value


def build_identity(
    *,
    manifest_sha256: str,
    slot_id: str,
    operation_key: str,
    candidate_version: int,
    content: Any = None,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """Build the complete immutable identity shared by all v20 receipts."""
    manifest_sha256 = _require_sha256(manifest_sha256, "manifest_sha256")
    slot_id = _require_text(slot_id, "slot_id")
    operation_key = _require_text(operation_key, "operation_key")
    candidate_version = _require_candidate_version(candidate_version)
    if content_hash is None:
        content_hash = sha256_json(content)
    content_hash = _require_sha256(content_hash, "content_hash")
    return {
        "manifest_sha256": manifest_sha256,
        "slot_id": slot_id,
        "operation_key": operation_key,
        "candidate_version": candidate_version,
        "content_hash": content_hash,
    }


def validate_identity(identity: Any) -> dict[str, Any]:
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise ValueError("v20 identity fields are incomplete or contain unknown fields")
    return build_identity(
        manifest_sha256=identity["manifest_sha256"],
        slot_id=identity["slot_id"],
        operation_key=identity["operation_key"],
        candidate_version=identity["candidate_version"],
        content_hash=identity["content_hash"],
    )


def identity_digest(identity: dict[str, Any]) -> str:
    return sha256_json(validate_identity(identity))


def build_receipt(
    *,
    receipt_kind: str,
    identity: dict[str, Any],
    payload: dict[str, Any],
    receipt_id: str = "",
) -> dict[str, Any]:
    identity = validate_identity(identity)
    receipt_kind = _require_text(receipt_kind, "receipt_kind")
    if not isinstance(payload, dict):
        raise TypeError("receipt payload must be an object")
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_kind": receipt_kind,
        "receipt_id": _require_receipt_id(receipt_id) if receipt_id else "",
        **identity,
        "payload": deepcopy(payload),
    }
    receipt["receipt_digest_sha256"] = sha256_json(receipt)
    return receipt


def validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError("v20 receipt fields are incomplete or contain unknown fields")
    if receipt["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported v20 receipt schema version")
    _require_text(receipt["receipt_kind"], "receipt_kind")
    if receipt["receipt_id"]:
        _require_receipt_id(receipt["receipt_id"])
    if not isinstance(receipt["payload"], dict):
        raise ValueError("receipt payload must be an object")
    identity = validate_identity(
        {field: receipt[field] for field in IDENTITY_FIELDS}
    )
    claimed = _require_sha256(receipt["receipt_digest_sha256"], "receipt_digest_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest_sha256"}
    if claimed != sha256_json(body):
        raise ValueError("receipt_digest_sha256 does not match canonical receipt content")
    return {**receipt, **identity}


def build_critic_receipt(
    *,
    identity: dict[str, Any],
    critic_role: str,
    invocation_id: str,
    verdict: str,
    confidence: float,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    critic_role = _require_text(critic_role, "critic_role")
    invocation_id = _require_text(invocation_id, "invocation_id")
    verdict = _require_text(verdict, "verdict")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be between zero and one")
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise ValueError("findings must be a list of objects")
    receipt_id = "critic-" + sha256_json(
        {"critic_role": critic_role, "invocation_id": invocation_id}
    )[:24]
    return build_receipt(
        receipt_kind="critic",
        identity=identity,
        receipt_id=receipt_id,
        payload={
            "critic_role": critic_role,
            "invocation_id": invocation_id,
            "verdict": verdict,
            "confidence": float(confidence),
            "findings": deepcopy(findings),
        },
    )


class AppendOnlyReceiptStore:
    """Persist receipts with exclusive file creation; existing evidence is immutable."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def append(self, receipt: dict[str, Any]) -> Path:
        receipt = validate_receipt(receipt)
        self.directory.mkdir(parents=True, exist_ok=True)
        receipt_id = receipt["receipt_id"] or receipt["receipt_digest_sha256"][:24]
        safe_kind = "".join(char if char.isalnum() or char in "-_" else "_" for char in receipt["receipt_kind"])
        path = self.directory / f"{safe_kind}-{receipt_id}-{receipt['receipt_digest_sha256'][:16]}.json"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(canonical_json(receipt))
            handle.write("\n")
        return path
