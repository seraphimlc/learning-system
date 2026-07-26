from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_system import model_router

from .inventory import _item_fingerprint
from .model_deadline import AdminStructuredTransportObserver


SEMANTIC_COLLISION_BOARD_SCHEMA_VERSION = "2026-07-25.codex-admin.semantic-collision-board.v1"
MINIMUM_COLLISION_CONFIDENCE = 0.86


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("item"), dict):
        return dict(payload["item"])
    if isinstance(payload.get("candidate"), dict):
        candidate = payload["candidate"]
        if isinstance(candidate.get("item"), dict):
            return dict(candidate["item"])
        return dict(candidate)
    return dict(payload)


def _candidate_binding(root: Path, path: Path, item: dict[str, Any]) -> dict[str, str]:
    return {
        "item_id": str(item.get("id") or ""),
        "candidate_path": _relative(root, path),
        "candidate_sha256": _digest_json(item),
        "candidate_file_sha256": _sha256_file(path),
    }


def _candidate_set_digest(bindings: list[dict[str, str]]) -> str:
    identity = [
        {
            "item_id": binding["item_id"],
            "candidate_sha256": binding["candidate_sha256"],
            "candidate_file_sha256": binding["candidate_file_sha256"],
        }
        for binding in sorted(bindings, key=lambda value: value["item_id"])
    ]
    return _digest_json(identity)


def _base_item_bindings(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "item_id": str(item.get("id") or ""),
                "item_sha256": _digest_json(item),
            }
            for item in items
        ],
        key=lambda value: value["item_id"],
    )


def _validate_base_item_bindings(bindings: Any) -> list[dict[str, str]]:
    if not isinstance(bindings, list):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_BINDINGS_INVALID")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"item_id", "item_sha256"}:
            raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_BINDING_SCHEMA_INVALID")
        item_id = str(binding.get("item_id") or "")
        item_sha256 = str(binding.get("item_sha256") or "")
        if (
            not item_id
            or item_id in seen
            or len(item_sha256) != 64
            or any(char not in "0123456789abcdef" for char in item_sha256.lower())
        ):
            raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_BINDING_VALUE_INVALID")
        seen.add(item_id)
        normalized.append({"item_id": item_id, "item_sha256": item_sha256})
    if normalized != sorted(normalized, key=lambda value: value["item_id"]):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_BINDINGS_NOT_CANONICAL")
    return normalized


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    answer = item.get("standard_answer")
    if isinstance(answer, dict):
        answer = {
            key: answer.get(key)
            for key in ("final_answer", "answer", "reasoning", "solution")
            if answer.get(key) not in (None, "")
        }
    return {
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "family_id": str(item.get("question_type") or item.get("problem_family_id") or ""),
        "prompt": item.get("prompt") or item.get("question") or item.get("stem") or "",
        "standard_answer": answer,
        "key_score_points": item.get("key_score_points") or [],
        "math_core_signature": str(item.get("math_core_signature") or ""),
        "structure_fingerprint": _item_fingerprint(item),
    }


def _response_schema() -> dict[str, Any]:
    collision = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["item_id", "reason"],
    }
    decision = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_item_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["PASS", "COLLISION"]},
            "confidence": {"type": "number"},
            "collisions": {"type": "array", "items": collision},
            "summary": {"type": "string"},
        },
        "required": ["candidate_item_id", "decision", "confidence", "collisions", "summary"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decisions": {"type": "array", "items": decision},
            "batch_summary": {"type": "string"},
        },
        "required": ["decisions", "batch_summary"],
    }


def _prompt_payload(
    candidate_items: list[dict[str, Any]], comparison_items: list[dict[str, Any]]
) -> dict[str, Any]:
    context = {
        "schema_version": "2026-07-25.codex-admin.semantic-collision-context.v1",
        "task": "Review every candidate for semantic collision against staged items and sibling candidates.",
        "decision_rule": {
            "PASS": "The candidate tests a meaningfully distinct mathematical structure, reasoning path, misconception, representation, or transfer demand.",
            "COLLISION": "The candidate is substantially the same diagnostic task with only wording, names, numbers, surface story, or cosmetic operation changes.",
            "must_review_every_candidate_once": True,
            "do_not_use_structure_hash_as_semantic_authority": True,
            "ignore_same_item_id_when_comparing": True,
        },
        "candidate_items": candidate_items,
        "comparison_items": comparison_items,
    }
    return {
        "instructions": "You are the v18 bounded semantic collision board. Return only schema-valid JSON.",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True),
                    }
                ],
            }
        ],
        "temperature": 0,
    }


def build_semantic_collision_board(
    *,
    root: Path,
    candidate_paths: list[Path],
    staged_bank_path: Path,
    subject: str = "math",
    absolute_deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if not candidate_paths:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BOARD_REQUIRES_CANDIDATES")
    resolved_candidates = [path if path.is_absolute() else root / path for path in candidate_paths]
    candidate_items = [_candidate_item(_load_json(path)) for path in resolved_candidates]
    candidate_ids = [str(item.get("id") or "") for item in candidate_items]
    if not all(candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BOARD_CANDIDATE_IDS_INVALID")

    resolved_bank = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    bank = _load_json(resolved_bank) if resolved_bank.exists() else {"items": []}
    staged_items = [dict(item) for item in bank.get("items") or [] if isinstance(item, dict)]
    candidate_bindings = [
        _candidate_binding(root, path, item)
        for path, item in zip(resolved_candidates, candidate_items)
    ]
    binding_by_id = {binding["item_id"]: binding for binding in candidate_bindings}
    candidate_set_sha256 = _candidate_set_digest(candidate_bindings)
    base_staged_bank_sha256 = _sha256_file(resolved_bank)
    base_staged_item_bindings = _base_item_bindings(staged_items)
    base_staged_snapshot_sha256 = _digest_json(base_staged_item_bindings)
    all_comparisons = staged_items + candidate_items
    compact_candidates = [_compact_item(item) for item in candidate_items]
    compact_staged = [_compact_item(item) for item in staged_items]
    compact_comparisons = compact_staged + compact_candidates

    exact_decisions: dict[str, dict[str, Any]] = {}
    pending_items: list[dict[str, Any]] = []
    for candidate in candidate_items:
        item_id = str(candidate.get("id") or "")
        fingerprint = _item_fingerprint(candidate)
        exact_matches = [
            str(other.get("id") or "")
            for other in all_comparisons
            if str(other.get("id") or "") != item_id
            and fingerprint
            and _item_fingerprint(other) == fingerprint
        ]
        if exact_matches:
            exact_decisions[item_id] = {
                "candidate_item_id": item_id,
                "decision": "COLLISION",
                "confidence": 1.0,
                "collisions": [
                    {"item_id": matched, "reason": "exact_structure_fingerprint_match"}
                    for matched in sorted(set(exact_matches))
                ],
                "summary": "Exact structure fingerprint already exists.",
                "decision_source": "exact_hash_prefilter",
                "candidate_structure_fingerprint": fingerprint,
                "candidate_sha256": binding_by_id[item_id]["candidate_sha256"],
                "candidate_file_sha256": binding_by_id[item_id]["candidate_file_sha256"],
            }
        else:
            pending_items.append(candidate)

    route = model_router.question_reviewer_route()
    provider_mode = "not_called_exact_hash_only" if not pending_items else "not_configured"
    model_decisions: dict[str, dict[str, Any]] = {}
    route_evidence = model_router.route_status(route).as_dict()
    findings: list[dict[str, str]] = []
    transport_attempts: list[dict[str, Any]] = []
    raw_response_sha256 = ""

    if pending_items:
        if absolute_deadline_monotonic is not None and time.monotonic() >= absolute_deadline_monotonic:
            return {
                "schema_version": SEMANTIC_COLLISION_BOARD_SCHEMA_VERSION,
                "subject": subject,
                "status": "INTERRUPTED_DEADLINE",
                "provider_mode": "not_called_deadline",
                "candidate_decisions": exact_decisions,
                "candidate_paths": [_relative(root, path) for path in resolved_candidates],
                "candidate_bindings": candidate_bindings,
                "candidate_set_sha256": candidate_set_sha256,
                "comparison_items": compact_comparisons,
                "staged_bank_path": _relative(root, resolved_bank),
                "base_staged_bank_sha256": base_staged_bank_sha256,
                "base_staged_snapshot_sha256": base_staged_snapshot_sha256,
                "base_staged_item_bindings": base_staged_item_bindings,
                "finding_counts": {"P1": 1},
                "findings": [
                    {
                        "severity": "P1",
                        "code": "semantic_collision_deadline_before_model",
                        "message": "Collision board did not start because the batch deadline was exhausted.",
                    }
                ],
                "activation_implication": "does_not_authorize_activation",
            }
        if not route.enabled:
            findings.append(
                {
                    "severity": "P1",
                    "code": "semantic_collision_model_not_configured",
                    "message": "Live semantic collision board requires the question reviewer route.",
                }
            )
        else:
            provider_mode = "live_model"
            observer = AdminStructuredTransportObserver()
            binding = model_router._new_structured_transport_lifecycle_binding(
                batch_attempt_id="semantic_collision_board:" + hashlib.sha256(
                    "|".join(candidate_ids).encode("utf-8")
                ).hexdigest()[:16],
                observer=observer,
                wall_deadline_monotonic=absolute_deadline_monotonic,
            )
            try:
                with model_router.bind_structured_transport_lifecycle(binding):
                    result = model_router.call_structured_json(
                        route,
                        _prompt_payload(
                            [_compact_item(item) for item in pending_items],
                            compact_comparisons,
                        ),
                        schema=_response_schema(),
                        plain_json_instruction="Return only one valid JSON object matching the collision board schema.",
                        retryable_errors_fallback=True,
                    )
                transport_attempts = observer.attempts
                raw_response_sha256 = hashlib.sha256(
                    json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                raw_decisions = result.value.get("decisions")
                if not isinstance(raw_decisions, list):
                    raw_decisions = []
                pending_ids = {str(item.get("id") or "") for item in pending_items}
                seen_ids: set[str] = set()
                comparison_ids = {str(item.get("id") or "") for item in all_comparisons}
                for decision in raw_decisions:
                    if not isinstance(decision, dict):
                        continue
                    item_id = str(decision.get("candidate_item_id") or "")
                    if item_id not in pending_ids:
                        findings.append(
                            {
                                "severity": "P1",
                                "code": "semantic_collision_candidate_out_of_scope",
                                "message": f"Collision board returned an out-of-scope candidate: {item_id}.",
                            }
                        )
                        continue
                    if item_id in seen_ids:
                        findings.append(
                            {
                                "severity": "P1",
                                "code": "semantic_collision_duplicate_candidate_decision",
                                "message": f"Collision board returned duplicate decisions for {item_id}.",
                            }
                        )
                        continue
                    seen_ids.add(item_id)
                    normalized = dict(decision)
                    normalized["decision_source"] = "live_model_board"
                    candidate = next(item for item in pending_items if str(item.get("id") or "") == item_id)
                    normalized["candidate_structure_fingerprint"] = _item_fingerprint(candidate)
                    normalized["candidate_sha256"] = binding_by_id[item_id]["candidate_sha256"]
                    normalized["candidate_file_sha256"] = binding_by_id[item_id]["candidate_file_sha256"]
                    model_decisions[item_id] = normalized
                expected_ids = pending_ids
                if set(model_decisions) != expected_ids:
                    findings.append(
                        {
                            "severity": "P1",
                            "code": "semantic_collision_candidate_coverage_invalid",
                            "message": "Collision board must return exactly one decision for every pending candidate.",
                        }
                    )
                for item_id, decision in model_decisions.items():
                    verdict = str(decision.get("decision") or "")
                    collisions = decision.get("collisions")
                    try:
                        confidence = float(decision.get("confidence"))
                    except (TypeError, ValueError):
                        confidence = 0.0
                    if confidence < MINIMUM_COLLISION_CONFIDENCE:
                        findings.append(
                            {
                                "severity": "P1",
                                "code": "semantic_collision_low_confidence",
                                "message": f"Collision decision confidence is below {MINIMUM_COLLISION_CONFIDENCE:.2f} for {item_id}.",
                            }
                        )
                    if verdict == "PASS" and collisions != []:
                        findings.append(
                            {
                                "severity": "P1",
                                "code": "semantic_collision_pass_has_collisions",
                                "message": f"PASS decision carries collisions for {item_id}.",
                            }
                        )
                    if verdict == "COLLISION" and not collisions:
                        findings.append(
                            {
                                "severity": "P1",
                                "code": "semantic_collision_block_missing_evidence",
                                "message": f"COLLISION decision lacks comparison evidence for {item_id}.",
                            }
                        )
                    for collision in collisions or []:
                        referenced_id = str(collision.get("item_id") or "") if isinstance(collision, dict) else ""
                        if referenced_id == item_id:
                            findings.append(
                                {
                                    "severity": "P1",
                                    "code": "semantic_collision_self_reference",
                                    "message": f"Collision decision for {item_id} references itself.",
                                }
                            )
                        elif referenced_id not in comparison_ids:
                            findings.append(
                                {
                                    "severity": "P1",
                                    "code": "semantic_collision_reference_out_of_scope",
                                    "message": f"Collision decision for {item_id} references unknown item {referenced_id}.",
                                }
                            )
                route_evidence = {
                    **route_evidence,
                    "structured_json_mode": result.mode,
                    "structured_json_endpoint": result.endpoint,
                    "raw_response_sha256": raw_response_sha256,
                }
            except model_router.ModelCallError as exc:
                transport_attempts = observer.attempts
                findings.append(
                    {
                        "severity": "P1",
                        "code": "semantic_collision_model_error",
                        "message": str(exc)[:800],
                    }
                )

    decisions = {**exact_decisions, **model_decisions}
    has_blocker = bool(findings)
    has_collision = any(
        str(decision.get("decision") or "") == "COLLISION"
        for decision in decisions.values()
    )
    for item_id, decision in decisions.items():
        if str(decision.get("decision") or "") == "COLLISION":
            findings.append(
                {
                    "severity": "P1",
                    "code": "semantic_collision_detected",
                    "item_id": item_id,
                    "message": str(decision.get("summary") or "Semantic collision detected."),
                }
            )
    status = "BLOCKED" if has_blocker else "COLLISION_FOUND" if has_collision else "PASS"
    return {
        "schema_version": SEMANTIC_COLLISION_BOARD_SCHEMA_VERSION,
        "subject": subject,
        "status": status,
        "provider_mode": provider_mode,
        "candidate_paths": [_relative(root, path) for path in resolved_candidates],
        "candidate_bindings": candidate_bindings,
        "candidate_set_sha256": candidate_set_sha256,
        "candidate_decisions": decisions,
        "comparison_items": compact_comparisons,
        "staged_bank_path": _relative(root, resolved_bank),
        "base_staged_bank_sha256": base_staged_bank_sha256,
        "base_staged_snapshot_sha256": base_staged_snapshot_sha256,
        "base_staged_item_bindings": base_staged_item_bindings,
        "route": route_evidence,
        "transport_attempts": transport_attempts,
        "model_evidence": {
            "provider_mode": provider_mode,
            "route": route_evidence,
            "raw_response_sha256": raw_response_sha256,
            "transport_attempts": transport_attempts,
        },
        "finding_counts": {"P1": len(findings)} if findings else {},
        "findings": findings,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }


def write_semantic_collision_board(
    report: dict[str, Any], *, root: Path, apply: bool = False
) -> dict[str, Any]:
    digest = hashlib.sha256(
        json.dumps(
            {
                "status": report.get("status"),
                "candidate_decisions": report.get("candidate_decisions"),
                "route": report.get("route"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    report_id = "SEMANTIC-COLLISION-" + digest
    json_rel = Path("data/admin/semantic_collision") / f"{report_id}.json"
    markdown_rel = Path("docs/system/admin_reports/semantic_collision") / f"{report_id}.md"
    result = {
        **report,
        "semantic_collision_report_id": report_id,
        "semantic_collision_json_path": str(json_rel),
        "semantic_collision_markdown_path": str(markdown_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    json_path = root / json_rel
    markdown_path = root / markdown_rel
    _atomic_write_text(
        json_path,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(
        markdown_path,
        "# Semantic Collision Board\n\n"
        f"Status: `{report.get('status')}`\n\n"
        f"Candidate Decisions: `{json.dumps(report.get('candidate_decisions') or {}, ensure_ascii=False, sort_keys=True)}`\n",
    )
    result["semantic_collision_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    result["semantic_collision_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    return result


def validate_semantic_collision_receipt_lineage(
    *,
    root: Path,
    receipt_path: Path,
    candidate_path: Path,
    expected_receipt_sha256: str = "",
) -> dict[str, Any]:
    resolved_receipt = receipt_path if receipt_path.is_absolute() else root / receipt_path
    resolved_candidate = candidate_path if candidate_path.is_absolute() else root / candidate_path
    if not resolved_receipt.is_file():
        raise ValueError("ADMIN_SEMANTIC_COLLISION_RECEIPT_MISSING")
    receipt_sha256 = _sha256_file(resolved_receipt)
    if expected_receipt_sha256 and receipt_sha256 != expected_receipt_sha256:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_RECEIPT_DIGEST_MISMATCH")
    receipt = _load_json(resolved_receipt)
    if receipt.get("schema_version") != SEMANTIC_COLLISION_BOARD_SCHEMA_VERSION:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_RECEIPT_SCHEMA_MISMATCH")
    if receipt.get("write_applied") is not True:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_RECEIPT_NOT_APPLIED")
    if receipt.get("status") not in {"PASS", "COLLISION_FOUND"}:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_RECEIPT_NOT_TRUSTWORTHY")

    candidate_payload = _load_json(resolved_candidate)
    candidate_item = _candidate_item(candidate_payload)
    item_id = str(candidate_item.get("id") or "")
    bindings = receipt.get("candidate_bindings") if isinstance(receipt.get("candidate_bindings"), list) else []
    if receipt.get("candidate_set_sha256") != _candidate_set_digest(bindings):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_CANDIDATE_SET_DIGEST_MISMATCH")
    binding = next((value for value in bindings if value.get("item_id") == item_id), None)
    if not isinstance(binding, dict):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_CANDIDATE_NOT_BOUND")
    if binding.get("candidate_sha256") != _digest_json(candidate_item):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_CANDIDATE_DIGEST_MISMATCH")
    if binding.get("candidate_file_sha256") != _sha256_file(resolved_candidate):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_CANDIDATE_FILE_DIGEST_MISMATCH")
    decision = (receipt.get("candidate_decisions") or {}).get(item_id)
    if not isinstance(decision, dict) or decision.get("decision") != "PASS":
        raise ValueError("ADMIN_SEMANTIC_COLLISION_CANDIDATE_NOT_PASSED")
    if decision.get("candidate_sha256") != binding.get("candidate_sha256") or decision.get("candidate_file_sha256") != binding.get("candidate_file_sha256"):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_DECISION_BINDING_MISMATCH")
    try:
        confidence = float(decision.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < MINIMUM_COLLISION_CONFIDENCE or decision.get("collisions") != []:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_DECISION_NOT_TRUSTWORTHY")
    if decision.get("decision_source") != "live_model_board":
        raise ValueError("ADMIN_SEMANTIC_COLLISION_DECISION_SOURCE_INVALID")
    evidence = receipt.get("model_evidence") if isinstance(receipt.get("model_evidence"), dict) else {}
    route = evidence.get("route") if isinstance(evidence.get("route"), dict) else {}
    if evidence.get("provider_mode") != "live_model" or not str(evidence.get("raw_response_sha256") or "") or not str(route.get("structured_json_mode") or ""):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_MODEL_EVIDENCE_MISSING")

    base_staged_bank_sha256 = str(receipt.get("base_staged_bank_sha256") or "")
    if len(base_staged_bank_sha256) != 64:
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_STAGED_BANK_DIGEST_MISSING")
    base_staged_item_bindings = _validate_base_item_bindings(
        receipt.get("base_staged_item_bindings")
    )
    base_staged_snapshot_sha256 = str(receipt.get("base_staged_snapshot_sha256") or "")
    if base_staged_snapshot_sha256 != _digest_json(base_staged_item_bindings):
        raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_SNAPSHOT_DIGEST_MISMATCH")

    return {
        "receipt_path": _relative(root, resolved_receipt),
        "receipt_sha256": receipt_sha256,
        "candidate_set_sha256": receipt.get("candidate_set_sha256"),
        "base_staged_bank_sha256": base_staged_bank_sha256,
        "base_staged_snapshot_sha256": base_staged_snapshot_sha256,
        "base_staged_item_bindings": base_staged_item_bindings,
        "candidate_bindings": bindings,
        "candidate_decisions": dict(receipt.get("candidate_decisions") or {}),
        "decision": decision,
    }


def validate_semantic_collision_receipt(
    *,
    root: Path,
    receipt_path: Path,
    candidate_path: Path,
    staged_bank_path: Path,
    expected_receipt_sha256: str = "",
) -> dict[str, Any]:
    validated = validate_semantic_collision_receipt_lineage(
        root=root,
        receipt_path=receipt_path,
        candidate_path=candidate_path,
        expected_receipt_sha256=expected_receipt_sha256,
    )
    resolved_receipt = receipt_path if receipt_path.is_absolute() else root / receipt_path
    resolved_bank = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
    receipt = _load_json(resolved_receipt)
    bindings = list(validated.get("candidate_bindings") or [])

    current_bank_sha256 = _sha256_file(resolved_bank)
    current_bank = _load_json(resolved_bank) if resolved_bank.exists() else {"items": []}
    current_items = [item for item in current_bank.get("items") or [] if isinstance(item, dict)]
    base_bindings = list(validated.get("base_staged_item_bindings") or [])
    if current_bank_sha256 == str(receipt.get("base_staged_bank_sha256") or ""):
        if base_bindings != _base_item_bindings(current_items):
            raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_STAGED_BANK_BINDINGS_MISMATCH")
    else:
        current_by_id = {str(item.get("id") or ""): item for item in current_items}
        base_ids = {str(value.get("item_id") or "") for value in base_bindings}
        for base in base_bindings:
            base_id = str(base.get("item_id") or "")
            if base_id not in current_by_id or _digest_json(current_by_id[base_id]) != str(base.get("item_sha256") or ""):
                raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_STAGED_BANK_CHANGED")
        candidate_by_id = {str(value.get("item_id") or ""): value for value in bindings}
        decisions = receipt.get("candidate_decisions") if isinstance(receipt.get("candidate_decisions"), dict) else {}
        for extra_id, extra_item in current_by_id.items():
            if extra_id in base_ids:
                continue
            extra_binding = candidate_by_id.get(extra_id)
            extra_decision = decisions.get(extra_id) if isinstance(decisions.get(extra_id), dict) else {}
            quality = extra_item.get("quality") if isinstance(extra_item.get("quality"), dict) else {}
            staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
            if (
                not extra_binding
                or extra_decision.get("decision") != "PASS"
                or staging_receipts.get("semantic_collision_candidate_set_sha256") != receipt.get("candidate_set_sha256")
                or staging_receipts.get("candidate_sha256") != extra_binding.get("candidate_sha256")
            ):
                raise ValueError("ADMIN_SEMANTIC_COLLISION_BASE_STAGED_BANK_CHANGED")

    return validated
