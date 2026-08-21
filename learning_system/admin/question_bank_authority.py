"""One authoritative candidate per v20 slot."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .v20_receipts import canonical_json, sha256_json


SCHEMA_VERSION = "question-bank-authority-index.v20"


class QuestionBankAuthorityError(RuntimeError):
    pass


def index_path(project_root: Path | str) -> Path:
    return Path(project_root) / "data/question_banks/v20/accepted_question_index_v20.json"


def _candidate_hash(root: Path, ref: str) -> str:
    path = root / ref
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionBankAuthorityError(f"accepted candidate is unavailable: {ref}") from exc
    if not isinstance(candidate, dict):
        raise QuestionBankAuthorityError(f"accepted candidate is not an object: {ref}")
    return sha256_json(candidate)


def _queue_candidates(root: Path, queue_path: Path) -> Iterable[dict[str, Any]]:
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionBankAuthorityError(f"unable to load queue: {queue_path}") from exc
    if not isinstance(queue, dict):
        raise QuestionBankAuthorityError(f"queue is not an object: {queue_path}")
    for slot in queue.get("slots", []):
        if not isinstance(slot, dict) or slot.get("status") not in {"STAGED", "ACCEPTED"}:
            continue
        ref = slot.get("question_ref")
        if not isinstance(ref, str) or not ref:
            raise QuestionBankAuthorityError(f"accepted slot has no question_ref: {queue_path}")
        candidate_hash = _candidate_hash(root, ref)
        claimed = slot.get("question_sha256") or candidate_hash
        if claimed != candidate_hash:
            raise QuestionBankAuthorityError(f"candidate hash mismatch for {slot.get('slot_id')}")
        candidate = json.loads((root / ref).read_text(encoding="utf-8"))
        yield {
            "slot_id": slot["slot_id"],
            "operation_key": slot.get("operation_key", f"v20:{slot['slot_id']}"),
            "candidate_version": candidate.get("candidate_version", slot.get("question_attempt", 0)),
            "candidate_ref": ref,
            "candidate_sha256": candidate_hash,
            "brief_sha256": slot.get("brief_sha256", ""),
            "source_queue": str(queue_path.relative_to(root)),
            "source_status": slot["status"],
            "source_updated_at": float(slot.get("updated_at", 0.0)),
        }


def rebuild_authority_index(
    project_root: Path | str,
    queue_paths: Iterable[Path | str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    if queue_paths is None:
        queue_paths = sorted((root / "data/question_banks/v20").glob("async_question_pipeline*.json"))
    selected: dict[str, dict[str, Any]] = {}
    for raw_path in queue_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        for entry in _queue_candidates(root, path):
            sid = entry["slot_id"]
            previous = selected.get(sid)
            if previous is None:
                selected[sid] = entry
                continue
            if (
                entry["candidate_version"] == previous["candidate_version"]
                and entry["candidate_sha256"] != previous["candidate_sha256"]
            ):
                raise QuestionBankAuthorityError(
                    f"conflicting candidates for one slot/version: {sid}/v{entry['candidate_version']}"
                )
            if (
                entry["candidate_version"], entry["source_updated_at"], entry["source_queue"]
            ) > (
                previous["candidate_version"], previous["source_updated_at"], previous["source_queue"]
            ):
                selected[sid] = entry
    entries = [selected[sid] for sid in sorted(selected)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "bank_version": "v20",
        "entries": entries,
        "updated_at": time.time(),
    }
    payload["index_sha256"] = sha256_json(payload)
    destination = index_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def load_authority_index(project_root: Path | str) -> dict[str, Any] | None:
    path = index_path(project_root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionBankAuthorityError(f"unable to load authority index: {path}") from exc
    claimed = value.get("index_sha256")
    body = {key: item for key, item in value.items() if key != "index_sha256"}
    if value.get("schema_version") != SCHEMA_VERSION or claimed != sha256_json(body):
        raise QuestionBankAuthorityError("authority index digest is invalid")
    return value
