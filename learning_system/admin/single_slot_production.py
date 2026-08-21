"""The first concrete-question vertical slice for v20.

This module is deliberately independent from the retired v18/v19 production
paths. It accepts one frozen slot, produces one candidate, routes only the
critics required by that slot's risk policy, and stages one item. All semantic
decisions remain model-owned; Python only enforces identity, schema, lineage,
state, leases, and immutable writes.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import model_router
from . import slot_authorization, v20_bank_namespace
from .slot_manifest import load_slot_manifest
from .v20_receipts import (
    AppendOnlyReceiptStore,
    canonical_json,
    build_identity,
    build_receipt,
    sha256_json,
    SHA256_PATTERN,
    validate_receipt,
)


CANDIDATE_SCHEMA_VERSION = "question-candidate.v20"
CHECKPOINT_SCHEMA_VERSION = "question-candidate-production-checkpoint.v20"
CONCRETE_QUEUE_SCHEMA_VERSION = "question-candidate-queue.v20"
STAGES = frozenset({"GENERATED", "CRITICIZING", "CRITICIZED", "STAGED", "RETRY_REQUIRED"})
VERDICTS = frozenset({"PASS", "REVISE", "BLOCKED"})
MODEL_OUTPUT_FIELDS = frozenset(
    {
        "question",
        "response_modality",
        "answer_contract",
        "solution",
        "teaching_note",
        "collision_basis",
        "visual_payload",
        "self_check",
        "risk_declaration",
    }
)
CRITIC_FIELDS = frozenset(
    {"verdict", "confidence", "findings", "invocation_id", "raw_response_sha256"}
)

CANDIDATE_MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(MODEL_OUTPUT_FIELDS),
    "properties": {
        "question": {"type": "string"},
        "response_modality": {"type": "string"},
        "answer_contract": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "standard_answer",
                "acceptable_answers",
                "scoring_points",
                "non_scoring_requirements",
                "common_errors",
            ],
            "properties": {
                "standard_answer": {"type": "string"},
                "acceptable_answers": {"type": "array", "items": {"type": "string"}},
                "scoring_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "points", "evidence"],
                        "properties": {
                            "id": {"type": "string"},
                            "points": {"type": "number"},
                            "evidence": {"type": "string"},
                        },
                    },
                },
                "non_scoring_requirements": {"type": "array", "items": {"type": "string"}},
                "common_errors": {"type": "array", "items": {"type": "string"}},
            },
        },
        "solution": {"type": "string"},
        "teaching_note": {"type": "string"},
        "collision_basis": {
            "type": "object",
            "additionalProperties": False,
            "required": ["signature", "distinctness_explanation", "prohibited_overlap"],
            "properties": {
                "signature": {"type": "string"},
                "distinctness_explanation": {"type": "string"},
                "prohibited_overlap": {"type": "array", "items": {"type": "string"}},
            },
        },
        "visual_payload": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["renderer_id", "payload"],
            "properties": {
                "renderer_id": {"type": "string"},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "data"],
                    "properties": {
                        "kind": {"type": "string"},
                        "data": {"type": "string"},
                    },
                },
            },
        },
        "self_check": {
            "type": "object",
            "additionalProperties": False,
            "required": ["concerns", "confidence"],
            "properties": {
                "concerns": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
        },
        "risk_declaration": {
            "type": "object",
            "additionalProperties": False,
            "required": ["needs_targeted_critic", "reason"],
            "properties": {
                "needs_targeted_critic": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        },
    },
}
CRITIC_MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "findings"],
    "properties": {
        "verdict": {"type": "string"},
        "confidence": {"type": "number"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "severity", "detail", "recommendation"],
                "properties": {
                    "code": {"type": "string"},
                    "severity": {"type": "string"},
                    "detail": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
            },
        },
    },
}


class SingleSlotProductionError(RuntimeError):
    pass


class SlotLeaseBusy(SingleSlotProductionError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SingleSlotProductionError(f"{field} must be nonempty")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SingleSlotProductionError(f"unable to load {path}") from exc
    if not isinstance(value, dict):
        raise SingleSlotProductionError(f"expected JSON object: {path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(canonical_json(value))
            handle.write("\n")
    except FileExistsError as exc:
        raise SingleSlotProductionError(f"immutable artifact already exists: {path}") from exc


def _replace_checkpoint(path: Path, value: dict[str, Any]) -> None:
    """Replace only the mutable checkpoint; all receipts remain append-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _find_receipt(base: Path, *, receipt_kind: str, candidate: dict[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    content_hash = sha256_json(candidate)
    directory = base / "concrete_receipts"
    for path in sorted(directory.glob("*.json")):
        try:
            receipt = validate_receipt(_read_json(path))
        except (OSError, ValueError, SingleSlotProductionError):
            continue
        if (
            receipt["receipt_kind"] == receipt_kind
            and receipt["slot_id"] == candidate["slot_id"]
            and receipt["operation_key"] == candidate["operation_key"]
            and receipt["candidate_version"] == candidate["candidate_version"]
            and receipt["content_hash"] == content_hash
        ):
            return path, receipt
    return None


def _assert_receipt_packet_binding(
    receipt: dict[str, Any], *, packet_sha: str, receipt_kind: str
) -> None:
    payload = receipt.get("payload")
    packet_field = "input_packet_sha256" if receipt_kind.startswith("critic_") else "packet_sha256"
    if not isinstance(payload, dict) or payload.get(packet_field) != packet_sha:
        raise SingleSlotProductionError(
            f"{receipt_kind} receipt is bound to a different generation packet"
        )


def staged_bank_digest(base: Path) -> str:
    """Digest the staged namespace without reading semantic decisions."""
    entries = []
    for path in sorted((base / "staged_candidates").glob("*.json")):
        value = _read_json(path)
        entries.append({"name": path.name, "content_sha256": sha256_json(value)})
    return sha256_json(entries)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Lease:
    def __init__(self, path: Path, *, ttl_seconds: int = 900) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.owner = uuid.uuid4().hex

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"owner": self.owner, "expires_at": time.time() + self.ttl_seconds}
        try:
            with self.path.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(payload))
                handle.write("\n")
            return
        except FileExistsError:
            try:
                existing = _read_json(self.path)
                expired = float(existing.get("expires_at", 0)) <= time.time()
            except (OSError, ValueError, TypeError, SingleSlotProductionError):
                expired = False
            if not expired:
                raise SlotLeaseBusy(f"slot lease is active: {self.path}")
            self.path.unlink(missing_ok=True)
            try:
                with self.path.open("x", encoding="utf-8") as handle:
                    handle.write(canonical_json(payload))
                    handle.write("\n")
            except FileExistsError as exc:
                raise SlotLeaseBusy(f"slot lease was acquired concurrently: {self.path}") from exc

    def release(self) -> None:
        try:
            current = _read_json(self.path)
            if current.get("owner") == self.owner:
                self.path.unlink(missing_ok=True)
        except (OSError, SingleSlotProductionError):
            return


def _validate_model_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MODEL_OUTPUT_FIELDS:
        raise SingleSlotProductionError("candidate model output fields are incomplete or contain trusted fields")
    for field in ("question", "response_modality", "solution", "teaching_note"):
        _text(value[field], field)
    for field in ("answer_contract", "collision_basis"):
        if not isinstance(value[field], dict) or not value[field]:
            raise SingleSlotProductionError(f"{field} must be a nonempty object")
    if value["visual_payload"] is not None and not isinstance(value["visual_payload"], dict):
        raise SingleSlotProductionError("visual_payload must be an object or null")
    self_check = value["self_check"]
    if not isinstance(self_check, dict) or set(self_check) != {"concerns", "confidence"}:
        raise SingleSlotProductionError("self_check fields are incomplete or unknown")
    if not isinstance(self_check["concerns"], list) or any(
        not isinstance(item, str) or not item.strip() for item in self_check["concerns"]
    ):
        raise SingleSlotProductionError("self_check concerns are invalid")
    if isinstance(self_check["confidence"], bool) or not isinstance(self_check["confidence"], (int, float)):
        raise SingleSlotProductionError("self_check confidence is invalid")
    if not 0 <= float(self_check["confidence"]) <= 1:
        raise SingleSlotProductionError("self_check confidence is out of range")
    risk = value["risk_declaration"]
    if not isinstance(risk, dict) or set(risk) != {"needs_targeted_critic", "reason"}:
        raise SingleSlotProductionError("risk_declaration fields are incomplete or unknown")
    if not isinstance(risk["needs_targeted_critic"], bool):
        raise SingleSlotProductionError("risk_declaration needs_targeted_critic is invalid")
    _text(risk["reason"], "risk_declaration.reason")
    return deepcopy(value)


def _validate_critic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CRITIC_FIELDS:
        raise SingleSlotProductionError("critic output fields are incomplete or unknown")
    if value["verdict"] not in {"PASS", "REVISE", "BLOCKED"}:
        raise SingleSlotProductionError("critic verdict is invalid")
    if isinstance(value["confidence"], bool) or not isinstance(value["confidence"], (int, float)):
        raise SingleSlotProductionError("critic confidence is invalid")
    if not 0 <= float(value["confidence"]) <= 1:
        raise SingleSlotProductionError("critic confidence is out of range")
    if not isinstance(value["findings"], list) or any(not isinstance(item, dict) for item in value["findings"]):
        raise SingleSlotProductionError("critic findings must be objects")
    _text(value["invocation_id"], "critic.invocation_id")
    if not isinstance(value["raw_response_sha256"], str) or not SHA256_PATTERN.fullmatch(value["raw_response_sha256"]):
        raise SingleSlotProductionError("critic raw_response_sha256 is invalid")
    return deepcopy(value)


def _unwrap_model_result(
    value: Any, *, default_invocation_id: str, fallback_raw_value: Any
) -> tuple[dict[str, Any], dict[str, str]]:
    if isinstance(value, dict) and set(value) == CRITIC_FIELDS:
        semantic = {key: value[key] for key in CRITIC_FIELDS if key not in {"invocation_id", "raw_response_sha256"}}
        metadata = {
            "invocation_id": value["invocation_id"],
            "raw_response_sha256": value["raw_response_sha256"],
        }
    elif (
        isinstance(value, dict)
        and {"value", "invocation_id", "raw_response_sha256"}.issubset(value)
    ):
        semantic = value["value"]
        metadata = {
            "invocation_id": value["invocation_id"],
            "raw_response_sha256": value["raw_response_sha256"],
        }
        if isinstance(value.get("duration_ms"), (int, float)):
            metadata["duration_ms"] = float(value["duration_ms"])
    else:
        semantic = value
        metadata = {
            "invocation_id": default_invocation_id,
            "raw_response_sha256": sha256_json(fallback_raw_value),
        }
    if not isinstance(semantic, dict):
        raise SingleSlotProductionError("model result value must be an object")
    _text(metadata["invocation_id"], "model.invocation_id")
    if not SHA256_PATTERN.fullmatch(metadata["raw_response_sha256"]):
        raise SingleSlotProductionError("model.raw_response_sha256 is invalid")
    return deepcopy(semantic), metadata


def _default_generation_call(
    *, packet: dict[str, Any], operation_key: str, candidate_version: int
) -> dict[str, Any]:
    route = model_router.question_designer_route()
    if not route.enabled:
        raise SingleSlotProductionError("question designer model route is not configured")
    prompt = (
        "你是 v20 数学题命题模型。只生成一个具体题目候选，严格遵守冻结 slot brief。"
        "必须给出答案合同、解法、教学提示、自检和风险声明；不要生成第二道题。"
        "只返回 schema-valid JSON。输入如下：\n"
        + canonical_json(packet)
    )
    try:
        result = model_router.call_structured_json(
            route,
            {
                "instructions": "Return exactly one candidate JSON object matching the schema.",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "temperature": 0,
            },
            schema=CANDIDATE_MODEL_SCHEMA,
            plain_json_instruction="Return only one valid JSON object matching the candidate schema; no markdown.",
            provider_idempotency_key=sha256_json(
                {
                    "operation_key": operation_key,
                    "stage": "candidate",
                    "candidate_version": candidate_version,
                }
            ),
        )
    except model_router.ModelCallError as exc:
        raise SingleSlotProductionError(f"question generation model call failed: {exc}") from exc
    return {
        "value": result.value,
        "invocation_id": f"{operation_key}:candidate:v{candidate_version}",
        "raw_response_sha256": sha256_json(result.raw_response),
        "duration_ms": result.duration_ms,
    }


def _default_critic_call(
    *,
    stage: str,
    packet: dict[str, Any],
    candidate: dict[str, Any],
    operation_key: str,
    candidate_version: int,
) -> dict[str, Any]:
    route = model_router.question_reviewer_route(stage=stage)
    if not route.enabled:
        raise SingleSlotProductionError("question reviewer model route is not configured")
    prompt = (
        "你是 v20 数学题独立批评模型。只评审一个候选，不重写题目。"
        "从指定风险视角给出 PASS、REVISE 或 BLOCKED，以及结构化理由。"
        "只返回 schema-valid JSON。风险视角："
        + stage
        + "\n输入：\n"
        + canonical_json({"packet": packet, "candidate": candidate})
    )
    try:
        result = model_router.call_structured_json(
            route,
            {
                "instructions": "Return exactly one critic result JSON object matching the schema.",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "temperature": 0,
            },
            schema=CRITIC_MODEL_SCHEMA,
            plain_json_instruction="Return only one valid JSON object matching the critic schema; no markdown.",
            provider_idempotency_key=sha256_json(
                {
                    "operation_key": operation_key,
                    "stage": stage,
                    "candidate_version": candidate_version,
                }
            ),
        )
    except model_router.ModelCallError as exc:
        raise SingleSlotProductionError(f"question critic model call failed: {exc}") from exc
    return {
        "value": result.value,
        "invocation_id": f"{operation_key}:critic:{stage}:v{candidate_version}",
        "raw_response_sha256": sha256_json(result.raw_response),
        "duration_ms": result.duration_ms,
    }


def required_critic_stages(
    brief: dict[str, Any], candidate: dict[str, Any] | None = None
) -> tuple[str, ...]:
    """Risk routing from trusted brief fields, not semantic text matching."""
    design = brief["design"]
    if design["risk_tier"] == "R3":
        stages = ["math_education", "assessment", "child_learning", "collision"]
    else:
        # Mathematical correctness is a hard gate for every concrete question.
        # Collision review remains separate: a structurally valid question can
        # still be too close to another slot.
        stages = ["math_education", "collision"]
        if (
            design["risk_tier"] == "R2"
            or design["response_modality"] == "visual_interactive"
            or design["review_route_class"] in {"targeted_critic", "collision_escalation", "coverage_escalation"}
            or (candidate is not None and candidate["risk_declaration"]["needs_targeted_critic"])
        ):
            stages.insert(0, "targeted")
    return tuple(stages)


def build_concrete_queue(
    *,
    project_root: Path | str,
    manifest: dict[str, Any],
    slot_ids: Iterable[str],
) -> dict[str, Any]:
    """Create a queue shell only from a project-authorized frozen manifest."""
    root = Path(project_root)
    authorized = v20_bank_namespace.authorize_queue(manifest, root)
    slot_manifest = load_slot_manifest(
        root / "data/question_banks/v20/slot_manifest_v20.json", require_frozen=True
    )
    inventory = _read_json(root / "data/question_banks/v20/slot_briefs_v20.json")
    briefs = {
        brief["slot_id"]: brief
        for brief in inventory.get("slots", [])
        if isinstance(brief, dict)
    }
    requested = list(slot_ids)
    if not requested:
        requested = [slot["slot_id"] for slot in slot_manifest["slots"]]
    if len(set(requested)) != len(requested):
        raise SingleSlotProductionError("concrete queue slot ids must be unique")
    manifest_slots = {slot["slot_id"] for slot in slot_manifest["slots"]}
    if any(slot_id not in manifest_slots for slot_id in requested):
        raise SingleSlotProductionError("concrete queue contains a slot outside the frozen manifest")
    if any(slot_id not in briefs or briefs[slot_id].get("status") != "REVIEWED" for slot_id in requested):
        raise SingleSlotProductionError("concrete queue requires reviewed slot briefs")
    queue = {
        "schema_version": CONCRETE_QUEUE_SCHEMA_VERSION,
        "manifest_sha256": authorized["manifest_sha256"],
        "slot_manifest_sha256": slot_manifest["slot_manifest_sha256"],
        "items": [
            {
                "slot_id": slot_id,
                "operation_key": f"v20:{slot_id}",
                "brief_sha256": briefs[slot_id]["brief_sha256"],
                "candidate_version": 1,
                "status": "QUEUED",
            }
            for slot_id in requested
        ],
        "queue_sha256": "",
    }
    queue["queue_sha256"] = sha256_json({key: value for key, value in queue.items() if key != "queue_sha256"})
    return queue


def build_generation_packet(
    *,
    manifest: dict[str, Any],
    brief: dict[str, Any],
    existing_candidates: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build a bounded model packet from a frozen brief only."""
    return {
        "schema_version": "question-candidate-generation-packet.v20",
        "manifest_sha256": manifest["manifest_sha256"],
        "slot_id": brief["slot_id"],
        "operation_key": brief["operation_key"],
        "brief_sha256": brief["brief_sha256"],
        "graph_binding": deepcopy(brief["graph_binding"]),
        "design": deepcopy(brief["design"]),
        "measurement_intent": deepcopy(brief["measurement_intent"]),
        "variation_policy": deepcopy(brief["variation_policy"]),
        "answer_contract_shape": deepcopy(brief["answer_contract_shape"]),
        "collision": deepcopy(brief["collision"]),
        "review_policy_sha256": brief["lineage"]["review_policy_sha256"],
        "prior_staged_candidates": [deepcopy(item) for item in list(existing_candidates)[:8]],
    }


def _assert_frozen_slot_binding(
    *, project_root: Path, manifest: dict[str, Any], brief: dict[str, Any]
) -> dict[str, Any]:
    """Require the worker input to be the exact brief authorized by the frozen manifest."""
    slot_manifest = load_slot_manifest(
        project_root / "data/question_banks/v20/slot_manifest_v20.json",
        require_frozen=True,
    )
    if slot_manifest["slot_manifest_sha256"] != manifest["slot_manifest_sha256"]:
        raise SingleSlotProductionError("slot manifest lineage does not match outer manifest")
    matching_slots = [
        item for item in slot_manifest["slots"] if item["slot_id"] == brief.get("slot_id")
    ]
    if len(matching_slots) != 1:
        raise SingleSlotProductionError("brief slot is not present exactly once in frozen manifest")
    if matching_slots[0]["brief_sha256"] != brief.get("brief_sha256"):
        raise SingleSlotProductionError("brief hash does not match frozen slot manifest")
    inventory = _read_json(project_root / "data/question_banks/v20/slot_briefs_v20.json")
    authoritative = [
        item for item in inventory.get("slots", [])
        if isinstance(item, dict) and item.get("slot_id") == brief.get("slot_id")
    ]
    if len(authoritative) != 1 or authoritative[0] != brief:
        raise SingleSlotProductionError("worker brief is not the frozen inventory brief")
    return deepcopy(authoritative[0])


def build_candidate(
    *,
    model_output: dict[str, Any],
    manifest: dict[str, Any],
    brief: dict[str, Any],
    candidate_version: int,
) -> dict[str, Any]:
    output = _validate_model_output(model_output)
    if output["response_modality"] != brief["design"]["response_modality"]:
        raise SingleSlotProductionError("candidate modality does not match frozen brief")
    candidate = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "slot_id": brief["slot_id"],
        "operation_key": brief["operation_key"],
        "candidate_version": candidate_version,
        "brief_sha256": brief["brief_sha256"],
        **output,
    }
    return validate_candidate(candidate, manifest=manifest, brief=brief)


def validate_candidate(
    candidate: Any, *, manifest: dict[str, Any], brief: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "schema_version", "manifest_sha256", "slot_id", "operation_key",
        "candidate_version", "brief_sha256", *MODEL_OUTPUT_FIELDS,
    }
    if not isinstance(candidate, dict) or set(candidate) != required:
        raise SingleSlotProductionError("candidate fields are incomplete or unknown")
    if candidate["schema_version"] != CANDIDATE_SCHEMA_VERSION:
        raise SingleSlotProductionError("unsupported candidate schema")
    if candidate["manifest_sha256"] != manifest["manifest_sha256"]:
        raise SingleSlotProductionError("candidate manifest lineage is stale")
    if candidate["slot_id"] != brief["slot_id"] or candidate["operation_key"] != brief["operation_key"]:
        raise SingleSlotProductionError("candidate slot identity does not match brief")
    if candidate["brief_sha256"] != brief["brief_sha256"]:
        raise SingleSlotProductionError("candidate brief lineage is stale")
    if isinstance(candidate["candidate_version"], bool) or not isinstance(candidate["candidate_version"], int) or candidate["candidate_version"] < 1:
        raise SingleSlotProductionError("candidate_version is invalid")
    _validate_model_output({field: candidate[field] for field in MODEL_OUTPUT_FIELDS})
    return deepcopy(candidate)


def checkpoint_digest(checkpoint: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"})


def build_checkpoint(
    *,
    manifest: dict[str, Any],
    brief: dict[str, Any],
    candidate_version: int,
    stage: str,
    candidate_sha256: str = "",
    receipt_ids: list[str] | None = None,
    critics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise SingleSlotProductionError("checkpoint stage is invalid")
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "slot_id": brief["slot_id"],
        "operation_key": brief["operation_key"],
        "candidate_version": candidate_version,
        "stage": stage,
        "candidate_sha256": candidate_sha256,
        "receipt_ids": sorted(receipt_ids or []),
        "critics": deepcopy(critics or []),
        "updated_at": _now(),
        "checkpoint_sha256": "",
    }
    checkpoint["checkpoint_sha256"] = checkpoint_digest(checkpoint)
    return checkpoint


def validate_checkpoint(checkpoint: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "manifest_sha256", "slot_id", "operation_key",
        "candidate_version", "stage", "candidate_sha256", "receipt_ids",
        "updated_at", "critics", "checkpoint_sha256",
    }
    if not isinstance(checkpoint, dict) or set(checkpoint) != fields:
        raise SingleSlotProductionError("checkpoint fields are incomplete or unknown")
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION or checkpoint["stage"] not in STAGES:
        raise SingleSlotProductionError("checkpoint schema or stage is invalid")
    _text(checkpoint["manifest_sha256"], "manifest_sha256")
    _text(checkpoint["slot_id"], "slot_id")
    if checkpoint["operation_key"] != f"v20:{checkpoint['slot_id']}":
        raise SingleSlotProductionError("checkpoint operation key is invalid")
    if isinstance(checkpoint["candidate_version"], bool) or not isinstance(checkpoint["candidate_version"], int) or checkpoint["candidate_version"] < 1:
        raise SingleSlotProductionError("checkpoint candidate_version is invalid")
    if checkpoint["candidate_sha256"] and not SHA256_PATTERN.fullmatch(checkpoint["candidate_sha256"]):
        raise SingleSlotProductionError("checkpoint candidate hash is invalid")
    if not isinstance(checkpoint["receipt_ids"], list) or any(
        not isinstance(item, str) or not SHA256_PATTERN.fullmatch(item)
        for item in checkpoint["receipt_ids"]
    ):
        raise SingleSlotProductionError("checkpoint receipt ids are invalid")
    if len(checkpoint["receipt_ids"]) != len(set(checkpoint["receipt_ids"])):
        raise SingleSlotProductionError("checkpoint receipt ids contain duplicates")
    if not isinstance(checkpoint["critics"], list):
        raise SingleSlotProductionError("checkpoint critics are invalid")
    critic_stages = set()
    for item in checkpoint["critics"]:
        if not isinstance(item, dict) or "stage" not in item:
            raise SingleSlotProductionError("checkpoint critics are invalid")
        stage = item["stage"]
        if stage in critic_stages or stage not in {"targeted", "math_education", "assessment", "child_learning", "collision"}:
            raise SingleSlotProductionError("checkpoint critic stages are invalid")
        critic_stages.add(stage)
        _validate_critic({key: item[key] for key in CRITIC_FIELDS})
    _text(checkpoint["updated_at"], "updated_at")
    if checkpoint["checkpoint_sha256"] != checkpoint_digest(checkpoint):
        raise SingleSlotProductionError("checkpoint digest does not match content")
    return deepcopy(checkpoint)


def _candidate_receipt(*, manifest: dict[str, Any], brief: dict[str, Any], candidate: dict[str, Any], kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    identity = build_identity(
        manifest_sha256=manifest["manifest_sha256"],
        slot_id=brief["slot_id"],
        operation_key=brief["operation_key"],
        candidate_version=candidate["candidate_version"],
        content=candidate,
    )
    return build_receipt(receipt_kind=kind, identity=identity, payload=payload)


def run_single_slot(
    *,
    project_root: Path | str,
    manifest: dict[str, Any],
    brief: dict[str, Any],
    candidate_version: int = 1,
    model_output: dict[str, Any] | None = None,
    model_call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    critic_call: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    existing_candidates: Iterable[dict[str, Any]] = (),
    stop_after: str | None = None,
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one slot; a failed candidate never blocks other slots."""
    root = Path(project_root)
    if stop_after not in {None, "generation"}:
        raise SingleSlotProductionError("unsupported concrete stop_after stage")
    if authorization is None:
        v20_bank_namespace.assert_project_authorized(manifest, "concrete_generation", root)
        _assert_frozen_slot_binding(project_root=root, manifest=manifest, brief=brief)
    else:
        slot_authorization.assert_slot_authorized(
            authorization,
            project_root=root,
            brief=brief,
        )
        if manifest.get("manifest_sha256") != authorization.get("authorization_digest"):
            raise SingleSlotProductionError(
                "slot authorization identity is not the production manifest identity"
            )
    if brief.get("status") not in {"REVIEWED", "FROZEN"}:
        raise SingleSlotProductionError("concrete generation requires a reviewed frozen slot brief")
    if brief["operation_key"] != f"v20:{brief['slot_id']}":
        raise SingleSlotProductionError("slot operation key is invalid")
    packet = build_generation_packet(manifest=manifest, brief=brief, existing_candidates=existing_candidates)
    packet_sha = sha256_json(packet)
    base = root / "data/question_banks/v20"
    lease = _Lease(base / "concrete_leases" / f"{brief['slot_id']}-v{candidate_version}.lease")
    lease.acquire()
    try:
        checkpoint_path = base / "concrete_checkpoints" / f"{brief['slot_id']}-v{candidate_version}.json"
        checkpoint: dict[str, Any] | None = None
        candidate: dict[str, Any] | None = None
        critic_results: list[tuple[str, dict[str, Any], Path | None]] = []
        if checkpoint_path.exists():
            checkpoint = validate_checkpoint(_read_json(checkpoint_path))
            if (
                checkpoint["manifest_sha256"] != manifest["manifest_sha256"]
                or checkpoint["slot_id"] != brief["slot_id"]
                or checkpoint["candidate_version"] != candidate_version
            ):
                raise SingleSlotProductionError("checkpoint lineage is stale")
            if checkpoint["stage"] == "STAGED" and checkpoint["critics"]:
                return {"status": "STAGED", "checkpoint": checkpoint, "idempotent": True}
            if checkpoint["candidate_sha256"]:
                for candidate_path in sorted(
                    (base / "candidate_versions").glob(f"{brief['slot_id']}-v{candidate_version}-*.json")
                ):
                    try:
                        loaded = _read_json(candidate_path)
                        if sha256_json(loaded) == checkpoint["candidate_sha256"]:
                            candidate = validate_candidate(loaded, manifest=manifest, brief=brief)
                            break
                    except SingleSlotProductionError:
                        continue
                if candidate is None:
                    raise SingleSlotProductionError("checkpoint candidate artifact is missing")
            elif checkpoint["stage"] in {"CRITICIZING", "CRITICIZED", "RETRY_REQUIRED", "STAGED"}:
                raise SingleSlotProductionError("checkpoint stage requires a candidate hash")
            critic_results = [(item["stage"], item, None) for item in checkpoint["critics"]]

        if candidate is None:
            for candidate_path in sorted(
                (base / "candidate_versions").glob(f"{brief['slot_id']}-v{candidate_version}-*.json")
            ):
                try:
                    candidate = validate_candidate(
                        _read_json(candidate_path), manifest=manifest, brief=brief
                    )
                    break
                except SingleSlotProductionError:
                    continue

        if candidate is None and model_output is None:
            model_result = (
                model_call(packet)
                if model_call is not None
                else _default_generation_call(
                    packet=packet,
                    operation_key=brief["operation_key"],
                    candidate_version=candidate_version,
                )
            )
            model_output, generation_metadata = _unwrap_model_result(
                model_result,
                default_invocation_id=f"{brief['operation_key']}:candidate:v{candidate_version}",
                fallback_raw_value=model_result,
            )
        else:
            generation_metadata = {
                "invocation_id": f"{brief['operation_key']}:candidate:v{candidate_version}",
                "raw_response_sha256": sha256_json(model_output if model_output is not None else candidate),
            }
        if candidate is None:
            candidate = build_candidate(
                model_output=model_output,
                manifest=manifest,
                brief=brief,
                candidate_version=candidate_version,
            )
        candidate_sha = sha256_json(candidate)
        receipt_store = AppendOnlyReceiptStore(base / "concrete_receipts")
        generated_path = base / "concrete_receipts" / "not-written"
        generated_receipt = None
        if checkpoint is not None:
            existing_generated = _find_receipt(
                base, receipt_kind="candidate_generated", candidate=candidate
            )
            if existing_generated is not None:
                generated_path, generated_receipt = existing_generated
                _assert_receipt_packet_binding(
                    generated_receipt, packet_sha=packet_sha, receipt_kind="candidate_generated"
                )
        if checkpoint is None:
            candidate_version_path = base / "candidate_versions" / f"{brief['slot_id']}-v{candidate_version}-{candidate_sha[:16]}.json"
            if not candidate_version_path.exists():
                _write_exclusive(candidate_version_path, candidate)
            elif _read_json(candidate_version_path) != candidate:
                raise SingleSlotProductionError("existing candidate artifact does not match candidate content")
            existing_generated = _find_receipt(
                base, receipt_kind="candidate_generated", candidate=candidate
            )
            if existing_generated is not None:
                generated_path, generated_receipt = existing_generated
                _assert_receipt_packet_binding(
                    generated_receipt, packet_sha=packet_sha, receipt_kind="candidate_generated"
                )
            else:
                generated_receipt = _candidate_receipt(
                    manifest=manifest,
                    brief=brief,
                    candidate=candidate,
                    kind="candidate_generated",
                    payload={
                    "packet_sha256": packet_sha,
                    "candidate_path": str(candidate_version_path.relative_to(root)),
                    "generation_invocation_id": generation_metadata["invocation_id"],
                        "raw_response_sha256": generation_metadata["raw_response_sha256"],
                        "model_duration_ms": generation_metadata.get("duration_ms", 0.0),
                    "review_policy_sha256": brief["lineage"]["review_policy_sha256"],
                    "stage": "GENERATED",
                    },
                )
                generated_path = receipt_store.append(generated_receipt)
            checkpoint = build_checkpoint(
                manifest=manifest,
                brief=brief,
                candidate_version=candidate_version,
                stage="GENERATED",
                candidate_sha256=candidate_sha,
                receipt_ids=[generated_receipt["receipt_digest_sha256"]],
            )
            _write_exclusive(checkpoint_path, checkpoint)
        elif generated_receipt is None:
            raise SingleSlotProductionError("checkpoint is missing its generation receipt")

        if stop_after == "generation":
            candidate_version_path = base / "candidate_versions" / (
                f"{brief['slot_id']}-v{candidate_version}-{candidate_sha[:16]}.json"
            )
            return {
                "status": "GENERATED",
                "candidate": candidate,
                "candidate_sha256": candidate_sha,
                "candidate_path": str(candidate_version_path),
                "checkpoint": checkpoint,
            }

        required_stages = required_critic_stages(brief, candidate)
        prior_critic_stages = {stage for stage, _, _ in critic_results}
        for critic_stage in required_stages:
            if critic_stage in prior_critic_stages:
                continue
            existing_critic = _find_receipt(
                base, receipt_kind=f"critic_{critic_stage}", candidate=candidate
            )
            if existing_critic is not None:
                critic_path, existing_receipt = existing_critic
                payload = existing_receipt["payload"]
                _assert_receipt_packet_binding(
                    existing_receipt, packet_sha=packet_sha, receipt_kind=f"critic_{critic_stage}"
                )
                if payload.get("critic_stage") != critic_stage:
                    raise SingleSlotProductionError("existing critic receipt stage does not match receipt kind")
                critic_record = {
                    "verdict": payload["verdict"],
                    "confidence": payload["confidence"],
                    "findings": deepcopy(payload["findings"]),
                    "invocation_id": payload["invocation_id"],
                    "raw_response_sha256": payload["raw_response_sha256"],
                }
                _validate_critic(critic_record)
                critic_record = {"stage": critic_stage, **critic_record}
                critic_results.append((critic_stage, critic_record, critic_path))
                prior_critic_stages.add(critic_stage)
                _replace_checkpoint(
                    checkpoint_path,
                    build_checkpoint(
                        manifest=manifest,
                        brief=brief,
                        candidate_version=candidate_version,
                        stage="CRITICIZING",
                        candidate_sha256=candidate_sha,
                        receipt_ids=list(
                            dict.fromkeys(
                                [
                                    *(checkpoint.get("receipt_ids", []) if checkpoint else []),
                                    existing_receipt["receipt_digest_sha256"],
                                ]
                            )
                        ),
                        critics=[result[1] for result in critic_results],
                    ),
                )
                checkpoint = validate_checkpoint(_read_json(checkpoint_path))
                continue
            critic_result = (
                critic_call(critic_stage, {"packet": packet, "candidate": candidate})
                if critic_call is not None
                else _default_critic_call(
                    stage=critic_stage,
                    packet=packet,
                    candidate=candidate,
                    operation_key=brief["operation_key"],
                    candidate_version=candidate_version,
                )
            )
            critic_semantic, critic_metadata = _unwrap_model_result(
                critic_result,
                default_invocation_id=f"{brief['operation_key']}:critic:{critic_stage}:v{candidate_version}",
                fallback_raw_value=critic_result,
            )
            # ``duration_ms`` is transport telemetry, not part of the critic
            # semantic contract. Keep it in the receipt metadata while
            # validating only the critic fields accepted by the contract.
            critic = _validate_critic(
                {
                    **critic_semantic,
                    "invocation_id": critic_metadata["invocation_id"],
                    "raw_response_sha256": critic_metadata["raw_response_sha256"],
                }
            )
            critic_record = {"stage": critic_stage, **critic}
            critic_receipt = _candidate_receipt(
                manifest=manifest,
                brief=brief,
                candidate=candidate,
                kind=f"critic_{critic_stage}",
                payload={
                    "critic_stage": critic_stage,
                    "input_packet_sha256": packet_sha,
                    "review_policy_sha256": brief["lineage"]["review_policy_sha256"],
                    "created_at": _now(),
                    "model_duration_ms": critic_metadata.get("duration_ms", 0.0),
                    **critic,
                },
            )
            critic_path = receipt_store.append(critic_receipt)
            critic_results.append((critic_stage, critic_record, critic_path))
            _replace_checkpoint(
                checkpoint_path,
                build_checkpoint(
                    manifest=manifest,
                    brief=brief,
                    candidate_version=candidate_version,
                    stage="CRITICIZING",
                    candidate_sha256=candidate_sha,
                    receipt_ids=[
                        *(checkpoint.get("receipt_ids", []) if checkpoint else []),
                        critic_receipt["receipt_digest_sha256"],
                    ],
                    critics=[result[1] for result in critic_results],
                ),
            )
            checkpoint = validate_checkpoint(_read_json(checkpoint_path))
        if any(result[1]["verdict"] != "PASS" for result in critic_results):
            retry_checkpoint = build_checkpoint(
                manifest=manifest,
                brief=brief,
                candidate_version=candidate_version,
                stage="RETRY_REQUIRED",
                candidate_sha256=candidate_sha,
                receipt_ids=checkpoint.get("receipt_ids", []) if checkpoint else [],
                critics=[result[1] for result in critic_results],
            )
            _replace_checkpoint(checkpoint_path, retry_checkpoint)
            return {"status": "RETRY_REQUIRED", "candidate_sha256": candidate_sha, "critics": [result[1] for result in critic_results]}

        _replace_checkpoint(
            checkpoint_path,
            build_checkpoint(
                manifest=manifest,
                brief=brief,
                candidate_version=candidate_version,
                stage="CRITICIZED",
                candidate_sha256=candidate_sha,
                receipt_ids=checkpoint.get("receipt_ids", []) if checkpoint else [],
                critics=[result[1] for result in critic_results],
            ),
        )
        generated_digest = generated_receipt["receipt_digest_sha256"] if generated_receipt else ""
        critic_receipt_ids: list[str] = []
        for critic_stage in required_stages:
            existing_critic = _find_receipt(
                base, receipt_kind=f"critic_{critic_stage}", candidate=candidate
            )
            if existing_critic is None:
                raise SingleSlotProductionError(
                    f"required critic receipt is missing before staging: {critic_stage}"
                )
            _, critic_receipt = existing_critic
            _assert_receipt_packet_binding(
                critic_receipt, packet_sha=packet_sha, receipt_kind=f"critic_{critic_stage}"
            )
            critic_receipt_ids.append(critic_receipt["receipt_digest_sha256"])
        candidate_path = base / "staged_candidates" / f"{brief['slot_id']}-v{candidate_version}-{candidate_sha[:16]}.json"
        before_bank_sha = staged_bank_digest(base)
        if not candidate_path.exists():
            _write_exclusive(candidate_path, candidate)
        elif _read_json(candidate_path) != candidate:
            raise SingleSlotProductionError("existing staged artifact does not match candidate content")
        after_bank_sha = staged_bank_digest(base)
        existing_staged = _find_receipt(base, receipt_kind="staged", candidate=candidate)
        if existing_staged is not None:
            staged_path, staged_receipt = existing_staged
            _assert_receipt_packet_binding(
                staged_receipt, packet_sha=packet_sha, receipt_kind="staged"
            )
        else:
            staged_receipt = _candidate_receipt(
                manifest=manifest,
                brief=brief,
                candidate=candidate,
                kind="staged",
                payload={
                    "candidate_path": str(candidate_path.relative_to(root)),
                    "generated_receipt": str(generated_path.relative_to(root)),
                    "critic_count": len(critic_results),
                    "required_critic_receipt_ids": critic_receipt_ids,
                    "all_required_receipt_ids": [generated_digest, *critic_receipt_ids],
                    "collision_receipt_id": critic_receipt_ids[required_stages.index("collision")]
                    if "collision" in required_stages
                    else "",
                    "packet_sha256": packet_sha,
                    "before_bank_sha256": before_bank_sha,
                    "after_bank_sha256": after_bank_sha,
                    "idempotency_key": f"{brief['operation_key']}:stage:v{candidate_version}",
                    "commit_result": "STAGED",
                },
            )
            staged_path = receipt_store.append(staged_receipt)
        if not generated_digest or checkpoint is None or not checkpoint.get("receipt_ids"):
            raise SingleSlotProductionError("staged candidate is missing generation evidence")
        final_checkpoint = build_checkpoint(
            manifest=manifest,
            brief=brief,
            candidate_version=candidate_version,
            stage="STAGED",
            candidate_sha256=candidate_sha,
            receipt_ids=list(
                dict.fromkeys(
                    [
                        *checkpoint.get("receipt_ids", []),
                        staged_receipt["receipt_digest_sha256"],
                    ]
                )
            ),
            critics=[result[1] for result in critic_results],
        )
        _replace_checkpoint(checkpoint_path, final_checkpoint)
        return {
            "status": "STAGED",
            "candidate": candidate,
            "candidate_sha256": candidate_sha,
            "candidate_path": str(candidate_path),
            "staged_receipt_path": str(staged_path),
            "checkpoint": final_checkpoint,
        }
    finally:
        lease.release()
