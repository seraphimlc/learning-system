from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REMOVAL_DECISION_SCHEMA_VERSION = "2026-07-24.codex-admin.staged-removal-decision.v1"
REMOVAL_RECEIPT_SCHEMA_VERSION = "2026-07-24.codex-admin.staged-removal-receipt.v1"


class StagedCleanupError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagedCleanupError(f"STAGED_CLEANUP_INVALID_JSON:{path}") from exc
    if not isinstance(payload, dict):
        raise StagedCleanupError(f"STAGED_CLEANUP_EXPECTED_OBJECT:{path}")
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class _ExclusiveFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_ExclusiveFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _validate_decision(decision: dict[str, Any], *, bank_path: Path, root: Path) -> list[dict[str, str]]:
    if decision.get("schema_version") != REMOVAL_DECISION_SCHEMA_VERSION:
        raise StagedCleanupError("STAGED_CLEANUP_UNSUPPORTED_DECISION_SCHEMA")
    if decision.get("decision") != "remove_from_staged_bank_and_regenerate":
        raise StagedCleanupError("STAGED_CLEANUP_UNSUPPORTED_DECISION")
    declared_path = root / str(decision.get("source_bank_path") or "")
    if declared_path.resolve() != bank_path.resolve():
        raise StagedCleanupError("STAGED_CLEANUP_BANK_PATH_MISMATCH")
    rows = decision.get("items")
    if not isinstance(rows, list) or not rows:
        raise StagedCleanupError("STAGED_CLEANUP_EMPTY_DECISION")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise StagedCleanupError("STAGED_CLEANUP_INVALID_DECISION_ROW")
        item_id = str(row.get("item_id") or "").strip()
        reason_code = str(row.get("reason_code") or "").strip()
        if not item_id or not reason_code:
            raise StagedCleanupError("STAGED_CLEANUP_INCOMPLETE_DECISION_ROW")
        if item_id in seen:
            raise StagedCleanupError(f"STAGED_CLEANUP_DUPLICATE_ITEM_ID:{item_id}")
        seen.add(item_id)
        normalized.append({"item_id": item_id, "reason_code": reason_code})
    return normalized


def remove_staged_items(
    *,
    root: Path,
    bank_path: Path,
    decision_path: Path,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    resolved_bank = (bank_path if bank_path.is_absolute() else root / bank_path).resolve()
    resolved_decision = (decision_path if decision_path.is_absolute() else root / decision_path).resolve()
    decision = _load_json(resolved_decision)
    rows = _validate_decision(decision, bank_path=resolved_bank, root=root)
    decision_id = str(decision.get("decision_id") or "").strip()
    if not decision_id:
        raise StagedCleanupError("STAGED_CLEANUP_MISSING_DECISION_ID")

    lock_path = Path(str(resolved_bank) + ".lock")
    with _ExclusiveFileLock(lock_path):
        before_bytes = resolved_bank.read_bytes()
        before_sha256 = _sha256_bytes(before_bytes)
        if before_sha256 != str(decision.get("source_bank_sha256") or ""):
            raise StagedCleanupError("STAGED_CLEANUP_SOURCE_DIGEST_MISMATCH")
        bank = json.loads(before_bytes.decode("utf-8"))
        items = list(bank.get("items") or [])
        if int(decision.get("source_item_count") or -1) != len(items):
            raise StagedCleanupError("STAGED_CLEANUP_SOURCE_COUNT_MISMATCH")

        remove_ids = {row["item_id"] for row in rows}
        existing_ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
        missing_ids = sorted(remove_ids.difference(existing_ids))
        if missing_ids:
            raise StagedCleanupError("STAGED_CLEANUP_UNKNOWN_ITEMS:" + ",".join(missing_ids))

        remaining = [item for item in items if str(item.get("id") or "") not in remove_ids]
        updated = dict(bank)
        updated["items"] = remaining
        updated["item_count"] = len(remaining)
        updated["updated_at"] = _utc_now()
        updated["status"] = "staged_not_active"
        after_sha256 = _sha256_bytes(_json_bytes(updated))
        receipt_path = root / "data/admin/removal_receipts" / f"{decision_id}.json"
        receipt = {
            "schema_version": REMOVAL_RECEIPT_SCHEMA_VERSION,
            "receipt_id": decision_id,
            "status": "DRY_RUN" if not apply else "PREPARED",
            "created_at": _utc_now(),
            "decision_path": str(resolved_decision.relative_to(root)),
            "decision_sha256": _sha256_bytes(resolved_decision.read_bytes()),
            "bank_path": str(resolved_bank.relative_to(root)),
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "before_item_count": len(items),
            "after_item_count": len(remaining),
            "removed_items": rows,
            "activation_implication": "does_not_authorize_activation",
        }
        if apply:
            _atomic_write(receipt_path, receipt)
            _atomic_write(resolved_bank, updated)
            receipt["status"] = "APPLIED"
            receipt["applied_at"] = _utc_now()
            _atomic_write(receipt_path, receipt)
        return receipt
