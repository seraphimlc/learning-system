"""Durable one-slot orchestration for v20 brief production.

The orchestrator owns only workflow mechanics: lease ownership, checkpoints,
raw-response persistence, receipt binding, and atomic publication. Semantic
brief design and review decisions remain model-owned. A failed slot is isolated
from every other slot and can be resumed without replaying completed stages.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .. import model_router
from . import slot_architecture, slot_architecture_review
from . import slot_brief_generation, slot_brief_inventory, slot_brief_review, slot_brief_worker
from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


ORCHESTRATION_SCHEMA_VERSION = "question-slot-brief-orchestration.v20"
LEASE_SCHEMA_VERSION = "question-slot-brief-lease.v20"
MAX_SEMANTIC_ATTEMPTS = 3
TOOL_VERSION = "v20-slot-brief-orchestrator-1"


class SlotBriefOrchestrationError(RuntimeError):
    pass


GenerationCall = Callable[[dict[str, Any], dict[str, Any]], Any]
ReviewCall = Callable[[str, dict[str, Any]], Any]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotBriefOrchestrationError(f"unable to read JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise SlotBriefOrchestrationError(f"JSON artifact must be an object: {path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value) + "\n"
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != payload:
                raise SlotBriefOrchestrationError(f"immutable artifact collision: {path}")
    except FileExistsError:
        raise
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    return path


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotBriefOrchestrationError(f"{field} must be nonempty")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise SlotBriefOrchestrationError(f"{field} must be a SHA-256 digest")
    return value


def _paths(root: Path) -> dict[str, Path]:
    base = root / "data/question_banks/v20"
    return {
        "base": base,
        "queue": base / "slot_brief_generation_queue_v20.json",
        "architecture": base / "slot_architecture_v20.json",
        "architecture_policy": base / "slot_architecture_review_policy_v20.json",
        "architecture_receipts": base / "slot_architecture_receipts",
        "graph": root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json",
        "contract": base / "slot_brief_generation_contract_v20.json",
        "review_policy": base / "slot_brief_review_policy_v20.json",
        "drafts": base / "slot_brief_drafts",
        "generation_raw": base / "slot_brief_generation_raw",
        "generation_invocations": base / "slot_brief_generation_invocations",
        "checkpoints": base / "slot_brief_generation_checkpoints",
        "review_raw": base / "slot_brief_review_raw",
        "review_packets": base / "slot_brief_review_packets",
        "review_receipts": base / "slot_brief_review_receipts",
        "reviewed": base / "slot_brief_reviewed",
        "leases": base / "slot_brief_leases",
    }


class SlotBriefLeaseStore:
    """Exclusive per-slot leases with expiry-based crash recovery."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _path(self, slot_id: str) -> Path:
        return self.directory / f"{_text(slot_id, 'slot_id')}.json"

    @staticmethod
    def _validate(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {
            "schema_version", "slot_id", "operation_key", "owner_id", "lease_id",
            "acquired_at_epoch", "expires_at_epoch", "lease_sha256",
        }:
            raise SlotBriefOrchestrationError("lease fields are incomplete or unknown")
        if value["schema_version"] != LEASE_SCHEMA_VERSION:
            raise SlotBriefOrchestrationError("unsupported slot brief lease")
        _text(value["slot_id"], "lease.slot_id")
        if value["operation_key"] != f"v20:{value['slot_id']}":
            raise SlotBriefOrchestrationError("lease operation key is invalid")
        for field in ("owner_id", "lease_id"):
            _text(value[field], f"lease.{field}")
        for field in ("acquired_at_epoch", "expires_at_epoch"):
            if isinstance(value[field], bool) or not isinstance(value[field], (int, float)):
                raise SlotBriefOrchestrationError(f"lease.{field} is invalid")
        if value["expires_at_epoch"] <= value["acquired_at_epoch"]:
            raise SlotBriefOrchestrationError("lease expiry must be after acquisition")
        _sha(value["lease_sha256"], "lease_sha256")
        if value["lease_sha256"] != sha256_json({key: item for key, item in value.items() if key != "lease_sha256"}):
            raise SlotBriefOrchestrationError("lease digest does not match content")
        return deepcopy(value)

    def acquire(
        self,
        slot_id: str,
        operation_key: str,
        owner_id: str,
        *,
        ttl_seconds: float,
        now_epoch: float | None = None,
    ) -> dict[str, Any]:
        if operation_key != f"v20:{slot_id}":
            raise SlotBriefOrchestrationError("lease operation key does not match slot")
        _text(owner_id, "owner_id")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
            raise SlotBriefOrchestrationError("lease ttl_seconds is invalid")
        now = time.time() if now_epoch is None else float(now_epoch)
        path = self._path(slot_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                existing = self._validate(_read_json(path))
            except SlotBriefOrchestrationError:
                raise
            if existing["expires_at_epoch"] > now:
                raise SlotBriefOrchestrationError(f"slot brief lease already held: {slot_id}")
            path.unlink()
        lease = {
            "schema_version": LEASE_SCHEMA_VERSION,
            "slot_id": slot_id,
            "operation_key": operation_key,
            "owner_id": owner_id,
            "lease_id": sha256_json({"slot_id": slot_id, "owner_id": owner_id, "now": now})[:24],
            "acquired_at_epoch": now,
            "expires_at_epoch": now + float(ttl_seconds),
            "lease_sha256": "",
        }
        lease["lease_sha256"] = sha256_json({key: item for key, item in lease.items() if key != "lease_sha256"})
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(lease) + "\n")
        except FileExistsError as exc:
            raise SlotBriefOrchestrationError(f"slot brief lease already held: {slot_id}") from exc
        return lease

    def release(self, lease: dict[str, Any]) -> None:
        checked = self._validate(lease)
        path = self._path(checked["slot_id"])
        if not path.exists():
            return
        current = self._validate(_read_json(path))
        if current["lease_id"] != checked["lease_id"] or current["owner_id"] != checked["owner_id"]:
            return
        path.unlink()

    def assert_active(self, lease: dict[str, Any], *, now_epoch: float | None = None) -> None:
        checked = self._validate(lease)
        path = self._path(checked["slot_id"])
        if not path.exists():
            raise SlotBriefOrchestrationError("slot brief lease is missing")
        current = self._validate(_read_json(path))
        now = time.time() if now_epoch is None else float(now_epoch)
        if current["lease_id"] != checked["lease_id"] or current["owner_id"] != checked["owner_id"]:
            raise SlotBriefOrchestrationError("slot brief lease fencing token is no longer owned")
        if current["expires_at_epoch"] <= now:
            raise SlotBriefOrchestrationError("slot brief lease has expired")

    def renew(self, lease: dict[str, Any], *, ttl_seconds: float) -> dict[str, Any]:
        self.assert_active(lease)
        checked = self._validate(lease)
        now = time.time()
        renewed = deepcopy(checked)
        renewed["acquired_at_epoch"] = now
        renewed["expires_at_epoch"] = now + float(ttl_seconds)
        renewed["lease_sha256"] = sha256_json({key: item for key, item in renewed.items() if key != "lease_sha256"})
        path = self._path(checked["slot_id"])
        temp_path: Path | None = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".renew", dir=path.parent)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(canonical_json(renewed) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
        # Keep the caller's lease handle immutable. The heartbeat thread and
        # the worker thread both use it; mutating the shared dict in place can
        # expose a half-updated value to ``assert_active`` and falsely fence
        # the worker while the renewal itself is valid.
        return deepcopy(renewed)


class SlotBriefLeaseHeartbeat:
    """Keep a live worker lease fenced while an external model call runs."""

    def __init__(self, store: SlotBriefLeaseStore, lease: dict[str, Any], ttl_seconds: float) -> None:
        self.store = store
        self.lease = lease
        self.ttl_seconds = float(ttl_seconds)
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(target=self._run, name="v20-slot-lease-heartbeat", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        # Renew well before expiry. Very short leases are used by concurrency
        # tests and crash-recovery callers, where a scheduler tick can consume
        # a meaningful fraction of the lease lifetime.
        interval = max(0.005, min(self.ttl_seconds / 4.0, 5.0))
        while not self._stop.wait(interval):
            try:
                self.store.renew(self.lease, ttl_seconds=self.ttl_seconds)
            except Exception:
                self._lost.set()
                return

    def assert_active(self) -> None:
        if self._lost.is_set():
            raise SlotBriefOrchestrationError("slot brief lease heartbeat was lost")
        self.store.assert_active(self.lease)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(0.1, min(self.ttl_seconds, 5.0)))


def _load_authority(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = _paths(root)
    graph = slot_architecture.load_graph(paths["graph"])
    architecture = slot_architecture.load_and_validate(paths["architecture"], paths["graph"])
    contract = slot_brief_inventory.validate_contract(_read_json(paths["contract"]))
    review_policy = slot_brief_review.load_policy(paths["review_policy"])
    queue = slot_brief_generation.validate_queue(
        _read_json(paths["queue"]),
        graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
    )
    if queue["status"] not in {"PLANNED", "IN_PROGRESS", "COMPLETE", "BLOCKED"}:
        raise SlotBriefOrchestrationError("brief generation queue status is invalid")
    return graph, architecture, contract, review_policy, queue


def _plan_for_slot(queue: dict[str, Any], slot_id: str) -> dict[str, Any]:
    matches = [plan for plan in queue["plans"] if plan["slot_id"] == slot_id]
    if len(matches) != 1:
        raise SlotBriefOrchestrationError(f"slot is not present exactly once in queue: {slot_id}")
    return deepcopy(matches[0])


def _checkpoint_store(paths: dict[str, Path]) -> slot_brief_generation.AppendOnlyCheckpointStore:
    return slot_brief_generation.AppendOnlyCheckpointStore(paths["checkpoints"])


def _append_checkpoint(
    paths: dict[str, Path], *, queue: dict[str, Any], plan: dict[str, Any], status: str,
    attempt: int, brief_sha256: str = "", updated_at: str, event_seq: int,
) -> dict[str, Any]:
    checkpoint = slot_brief_generation.build_checkpoint(
        queue_sha256=queue["queue_sha256"], plan=plan, status=status, attempt=attempt,
        brief_sha256=brief_sha256, updated_at=updated_at, event_seq=event_seq,
    )
    try:
        _checkpoint_store(paths).append(checkpoint)
    except FileExistsError:
        pass
    return checkpoint


def _checkpoints_for_slot(paths: dict[str, Path], queue: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not paths["checkpoints"].exists():
        return result
    for path in sorted(paths["checkpoints"].glob(f"{plan['slot_id']}-*.json")):
        try:
            checkpoint = slot_brief_generation.validate_checkpoint(_read_json(path))
        except (OSError, SlotBriefGenerationError):
            continue
        if (
            checkpoint["queue_sha256"] == queue["queue_sha256"]
            and checkpoint["slot_id"] == plan["slot_id"]
            and checkpoint["plan_sha256"] == slot_brief_generation.plan_digest(plan)
        ):
            result.append(checkpoint)
    ordered = sorted(result, key=lambda item: (item["event_seq"], item["checkpoint_sha256"]))
    if [item["event_seq"] for item in ordered] != list(range(1, len(ordered) + 1)):
        raise SlotBriefOrchestrationError("slot brief checkpoint event sequence has a gap or duplicate")
    allowed = {
        None: {"PENDING", "BLOCKED"},
        "PENDING": {"PENDING", "GENERATED", "BLOCKED"},
        "GENERATED": {"REVIEWED", "REJECTED", "BLOCKED"},
        "BLOCKED": {"BLOCKED", "PENDING", "GENERATED", "REJECTED", "REVIEWED"},
        "REJECTED": {"PENDING"},
        "REVIEWED": set(),
    }
    previous: str | None = None
    for item in ordered:
        if item["status"] not in allowed[previous]:
            raise SlotBriefOrchestrationError(
                f"invalid slot brief checkpoint transition: {previous}->{item['status']}"
            )
        previous = item["status"]
    return ordered


def _next_event_seq(paths: dict[str, Path], queue: dict[str, Any], plan: dict[str, Any]) -> int:
    checkpoints = _checkpoints_for_slot(paths, queue, plan)
    return (checkpoints[-1]["event_seq"] + 1) if checkpoints else 1


def _next_attempt(paths: dict[str, Path], queue: dict[str, Any], plan: dict[str, Any]) -> int:
    checkpoints = _checkpoints_for_slot(paths, queue, plan)
    if not checkpoints:
        return 1
    latest = checkpoints[-1]
    if latest["status"] in {"PENDING", "BLOCKED"}:
        if latest["status"] == "BLOCKED" and list(
            paths["generation_raw"].glob(
                f"{plan['slot_id']}-attempt-{latest['attempt']}-generation_rejected-*.json"
            )
        ):
            # A semantic response was received but failed the trusted brief
            # contract. It must get a fresh model attempt; reusing the same
            # provider idempotency key would replay the rejected response.
            return latest["attempt"] + 1
        return max(1, latest["attempt"])
    return latest["attempt"] + 1


def _load_reviewed_current(
    paths: dict[str, Path], *, brief: dict[str, Any], architecture: dict[str, Any], graph: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any] | None:
    path = paths["reviewed"] / f"{brief['slot_id']}.json"
    if not path.exists():
        return None
    current = slot_brief_inventory.validate_brief(
        _read_json(path),
        graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
        graph=graph,
        architecture=architecture,
        contract=slot_brief_inventory.validate_contract(_read_json(paths["contract"])),
        review_policy_sha256=slot_brief_review.policy_digest(policy),
    )
    if current["brief_sha256"] != brief["brief_sha256"]:
        raise SlotBriefOrchestrationError("current reviewed brief is stale and cannot be overwritten")
    receipts = _receipts_for_brief(paths, current["slot_id"], current["brief_sha256"], brief=current)
    slot_brief_review.assert_reviewed_brief_evidence(
        brief=current, architecture=architecture, graph=graph, policy=policy, receipts=receipts
    )
    return current


def _receipts_for_brief(
    paths: dict[str, Path], slot_id: str, brief_sha256: str, *, brief: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    if not paths["review_receipts"].exists():
        return receipts
    for path in sorted(paths["review_receipts"].glob("*.json")):
        try:
            receipt = slot_brief_review.validate_review_receipt(_read_json(path))
            slot_brief_review.assert_raw_response_artifact(receipt, base_dir=paths["base"])
            if brief is not None:
                slot_brief_review.assert_review_packet_artifact(
                    receipt, brief=brief, packet_dir=paths["review_packets"]
                )
        except (OSError, SlotBriefReviewError):
            continue
        if receipt["slot_id"] == slot_id and receipt["brief_sha256"] == brief_sha256:
            receipts.append(receipt)
    return receipts


def _find_receipt(receipts: list[dict[str, Any]], review_kind: str, reviewer_role: str) -> dict[str, Any] | None:
    matches = [r for r in receipts if r["review_kind"] == review_kind and r["reviewer_role"] == reviewer_role]
    if len(matches) > 1:
        raise SlotBriefOrchestrationError(f"duplicate review receipt for {reviewer_role}")
    return matches[0] if matches else None


def _normalize_model_result(value: Any) -> tuple[dict[str, Any], Any]:
    if isinstance(value, dict) and set(value) == {"value", "raw_response"}:
        if not isinstance(value["value"], dict):
            raise SlotBriefOrchestrationError("model result value must be an object")
        return deepcopy(value["value"]), deepcopy(value["raw_response"])
    if not isinstance(value, dict):
        raise SlotBriefOrchestrationError("model result must be an object")
    return deepcopy(value), deepcopy(value)


def _build_review_packet(brief: dict[str, Any], *, role: str, focus: str) -> dict[str, Any]:
    return {
        "packet_schema": "question-slot-brief-review-input.v20",
        "review_scope": "slot_brief_only",
        "reviewer_role": role,
        "review_focus": focus,
        "brief": deepcopy(brief),
        "brief_is_not_a_question": True,
    }


def _default_review_call(role: str, packet: dict[str, Any]) -> dict[str, Any]:
    route = model_router.slot_brief_reviewer_route()
    if not route.enabled:
        raise SlotBriefOrchestrationError("slot brief reviewer model route is not configured")
    prompt = (
        "你是 v20 数学题库 slot brief 的独立评审模型。只评审一个 brief 的教育测量设计，"
        "不要生成具体题目、答案或解法。返回 verdict、confidence、findings 三个字段的 JSON。\n"
        + canonical_json(packet)
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "confidence", "findings"],
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "PASS_WITH_SCOPE", "NEEDS_FIX"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
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
    try:
        result = model_router.call_structured_json_with_fallback(
            route,
            {"instructions": "Return only the review JSON.", "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], "temperature": 0},
            schema=schema,
            fallback_model_env="AI_QUESTION_REVIEW_FALLBACK_MODEL",
            plain_json_instruction="Return only valid review JSON; no markdown.",
            provider_idempotency_key=sha256_json(
                {
                    "operation_key": packet["brief"]["operation_key"],
                    "brief_sha256": packet["brief"]["brief_sha256"],
                    "packet_sha256": sha256_json(packet),
                    "reviewer_role": role,
                }
            ),
        )
    except model_router.ModelCallError as exc:
        raise SlotBriefOrchestrationError(f"slot brief review model call failed: {exc}") from exc
    return {"value": result.value, "raw_response": result.raw_response}


def _validate_review_semantics(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"verdict", "confidence", "findings"}:
        raise SlotBriefOrchestrationError("review model output has trusted or unknown fields")
    if value["verdict"] not in slot_brief_review.VERDICTS:
        raise SlotBriefOrchestrationError("review model verdict is invalid")
    if isinstance(value["confidence"], bool) or not isinstance(value["confidence"], (int, float)):
        raise SlotBriefOrchestrationError("review model confidence is invalid")
    if not 0 <= float(value["confidence"]) <= 1:
        raise SlotBriefOrchestrationError("review model confidence is out of range")
    try:
        slot_brief_review.validate_findings(value["findings"])
    except slot_brief_review.SlotBriefReviewError as exc:
        raise SlotBriefOrchestrationError("review model findings are invalid") from exc
    return deepcopy(value)


def _persist_raw(
    paths: dict[str, Path], *, directory_key: str, slot_id: str, attempt: int, stage: str,
    packet_sha256: str, response: Any,
) -> tuple[str, str]:
    response_sha = sha256_json(response)
    artifact = {
        "schema_version": ORCHESTRATION_SCHEMA_VERSION,
        "slot_id": slot_id,
        "attempt": attempt,
        "stage": stage,
        "input_packet_sha256": packet_sha256,
        "response_sha256": response_sha,
        "response": deepcopy(response),
    }
    path = paths[directory_key] / f"{slot_id}-attempt-{attempt}-{stage}-{response_sha[:16]}.json"
    _write_exclusive(path, artifact)
    return str(path.relative_to(paths["base"])), response_sha


def _persist_generation_invocation(
    paths: dict[str, Path], *, slot_id: str, attempt: int, packet: dict[str, Any], provider_key: str,
) -> None:
    packet_sha256 = sha256_json(packet)
    artifact = {
        "schema_version": "question-slot-brief-generation-invocation.v20",
        "slot_id": slot_id,
        "attempt": attempt,
        "input_packet_sha256": packet_sha256,
        "provider_idempotency_key": provider_key,
        "packet": deepcopy(packet),
    }
    path = paths["generation_invocations"] / f"{slot_id}-attempt-{attempt}.json"
    _write_exclusive(path, artifact)


def _load_generation_invocation(paths: dict[str, Path], *, slot_id: str, attempt: int) -> dict[str, Any] | None:
    path = paths["generation_invocations"] / f"{slot_id}-attempt-{attempt}.json"
    if not path.exists():
        return None
    artifact = _read_json(path)
    if set(artifact) != {
        "schema_version", "slot_id", "attempt", "input_packet_sha256", "provider_idempotency_key", "packet"
    } or artifact["schema_version"] != "question-slot-brief-generation-invocation.v20":
        raise SlotBriefOrchestrationError("generation invocation artifact is invalid")
    if artifact["slot_id"] != slot_id or artifact["attempt"] != attempt:
        raise SlotBriefOrchestrationError("generation invocation identity is invalid")
    if sha256_json(artifact["packet"]) != artifact["input_packet_sha256"]:
        raise SlotBriefOrchestrationError("generation invocation packet digest is invalid")
    if artifact["provider_idempotency_key"] != slot_brief_worker.brief_provider_idempotency_key(
        plan={"operation_key": f"v20:{slot_id}"}, packet=artifact["packet"], attempt=attempt
    ):
        raise SlotBriefOrchestrationError("generation invocation provider key is invalid")
    return deepcopy(artifact["packet"])


def _persist_draft(paths: dict[str, Path], brief: dict[str, Any], attempt: int) -> str:
    suffix = "" if attempt == 1 else f"-attempt-{attempt}"
    path = paths["drafts"] / f"{brief['slot_id']}{suffix}.json"
    _write_exclusive(path, brief)
    return str(path.relative_to(paths["base"]))


def _persist_review_receipt(paths: dict[str, Path], receipt: dict[str, Any]) -> None:
    try:
        slot_brief_review.AppendOnlySlotBriefReviewStore(paths["review_receipts"]).append(receipt)
    except FileExistsError:
        pass


def _load_prior_reviewed_briefs(
    paths: dict[str, Path], *, architecture: dict[str, Any], graph: dict[str, Any],
    contract: dict[str, Any], policy: dict[str, Any],
) -> list[dict[str, Any]]:
    result = []
    if not paths["reviewed"].exists():
        return result
    for path in sorted(paths["reviewed"].glob("*.json")):
        try:
            brief = _read_json(path)
            if brief.get("status") != "REVIEWED":
                continue
            brief = slot_brief_inventory.validate_brief(
                brief,
                graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                graph=graph,
                architecture=architecture,
                contract=contract,
                review_policy_sha256=slot_brief_review.policy_digest(policy),
            )
            slot_brief_review.assert_reviewed_brief_evidence(
                brief=brief,
                architecture=architecture,
                graph=graph,
                policy=policy,
                receipts=_receipts_for_brief(paths, brief["slot_id"], brief["brief_sha256"], brief=brief),
            )
            result.append(brief)
        except (SlotBriefOrchestrationError, slot_brief_inventory.SlotBriefInventoryError, slot_brief_review.SlotBriefReviewError):
            continue
    return result


def _load_draft(
    paths: dict[str, Path], *, plan: dict[str, Any], graph: dict[str, Any], architecture: dict[str, Any], contract: dict[str, Any], policy_sha256: str, brief_sha256: str
) -> dict[str, Any] | None:
    candidates = sorted(paths["drafts"].glob(f"{plan['slot_id']}*.json"))
    for path in candidates:
        try:
            brief = slot_brief_generation.validate_generated_brief(
                plan=plan,
                brief=_read_json(path),
                graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                graph=graph,
                architecture=architecture,
                contract=contract,
                review_policy_sha256=policy_sha256,
            )
        except (OSError, SlotBriefOrchestrationError, slot_brief_generation.SlotBriefGenerationError):
            continue
        if brief["brief_sha256"] == brief_sha256:
            return brief
    return None


def _draft_attempt(path: Path) -> int:
    name = path.stem
    marker = "-attempt-"
    if marker not in name:
        return 1
    suffix = name.rsplit(marker, 1)[1]
    try:
        return int(suffix)
    except ValueError:
        return 1


def _load_any_draft(
    paths: dict[str, Path], *, plan: dict[str, Any], graph: dict[str, Any], architecture: dict[str, Any], contract: dict[str, Any], policy_sha256: str, desired_attempt: int | None = None,
) -> tuple[dict[str, Any], int] | None:
    """Recover a complete draft even when its checkpoint was never written."""
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    if not paths["drafts"].exists():
        return None
    for path in sorted(paths["drafts"].glob(f"{plan['slot_id']}*.json")):
        path_attempt = _draft_attempt(path)
        if desired_attempt is not None and path_attempt != desired_attempt:
            continue
        try:
            brief = slot_brief_generation.validate_generated_brief(
                plan=plan,
                brief=_read_json(path),
                graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                graph=graph,
                architecture=architecture,
                contract=contract,
                review_policy_sha256=policy_sha256,
            )
        except (OSError, SlotBriefOrchestrationError, slot_brief_generation.SlotBriefGenerationError):
            continue
        candidates.append((path_attempt, path.name, brief))
    if not candidates:
        return None
    attempt, _, brief = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    return brief, attempt


def run_one_slot_brief(
    *,
    project_root: Path | str,
    slot_id: str,
    owner_id: str,
    generation_call: GenerationCall | None = None,
    review_call: ReviewCall | None = None,
    now: str,
    lease_ttl_seconds: float = 300.0,
    stop_after: str | None = None,
) -> dict[str, Any]:
    """Run or resume exactly one brief slot.

    ``generation_call(plan, packet)`` and ``review_call(role, packet)`` are
    optional model adapters. When omitted, configured routes are used; disabled
    routes fail closed and never create a semantic artifact.
    """
    root = Path(project_root)
    if stop_after not in {None, "generation"}:
        raise SlotBriefOrchestrationError("unsupported brief stop_after stage")
    paths = _paths(root)
    started_monotonic = time.monotonic()
    stage_timings = {
        "authority_load_seconds": 0.0,
        "lease_acquire_seconds": 0.0,
        "generation_model_seconds": 0.0,
        "generation_persist_seconds": 0.0,
        "lead_review_model_seconds": 0.0,
        "targeted_review_model_seconds": 0.0,
        "publication_seconds": 0.0,
    }

    def result_payload(
        *, status: str, reason: str = "", brief: dict[str, Any] | None = None,
        model_calls: int = 0,
    ) -> dict[str, Any]:
        timings = {key: round(value, 3) for key, value in stage_timings.items()}
        timings["total_seconds"] = round(time.monotonic() - started_monotonic, 3)
        payload: dict[str, Any] = {
            "schema_version": ORCHESTRATION_SCHEMA_VERSION,
            "slot_id": slot_id,
            "status": status,
            "model_calls": model_calls,
            "timings": timings,
        }
        if reason:
            payload["reason"] = reason
        if brief is not None:
            payload["brief"] = brief
        return payload

    authority_started = time.monotonic()
    try:
        graph, architecture, contract, policy, queue = _load_authority(root)
        plan = _plan_for_slot(queue, slot_id)
        policy_sha = slot_brief_review.policy_digest(policy)
        lease_store = SlotBriefLeaseStore(paths["leases"])
        stage_timings["authority_load_seconds"] = time.monotonic() - authority_started
        lease_started = time.monotonic()
        lease = lease_store.acquire(slot_id, plan["operation_key"], owner_id, ttl_seconds=lease_ttl_seconds)
        stage_timings["lease_acquire_seconds"] = time.monotonic() - lease_started
    except Exception as exc:
        stage_timings["authority_load_seconds"] = max(
            stage_timings["authority_load_seconds"], time.monotonic() - authority_started
        )
        return result_payload(status="BLOCKED", reason=str(exc))

    generation_calls = 0
    review_calls = 0
    heartbeat = SlotBriefLeaseHeartbeat(lease_store, lease, lease_ttl_seconds)
    heartbeat.start()

    def checkpoint(**kwargs: Any) -> dict[str, Any]:
        heartbeat.assert_active()
        return _append_checkpoint(
            paths,
            queue=queue,
            plan=plan,
            event_seq=_next_event_seq(paths, queue, plan),
            **kwargs,
        )

    def record_blocked(**kwargs: Any) -> None:
        """Best-effort failure checkpoint; a fenced worker cannot write it."""
        try:
            checkpoint(**kwargs)
        except SlotBriefOrchestrationError:
            pass

    def write_artifact(path: Path, value: dict[str, Any]) -> Path:
        heartbeat.assert_active()
        return _write_exclusive(path, value)

    def persist_raw(*, directory_key: str, attempt: int, stage: str, packet_sha256: str, response: Any) -> tuple[str, str]:
        heartbeat.assert_active()
        return _persist_raw(
            paths,
            directory_key=directory_key,
            slot_id=slot_id,
            attempt=attempt,
            stage=stage,
            packet_sha256=packet_sha256,
            response=response,
        )

    def persist_draft(value: dict[str, Any], attempt: int) -> str:
        heartbeat.assert_active()
        return _persist_draft(paths, value, attempt)

    try:
        current_path = paths["reviewed"] / f"{slot_id}.json"
        if current_path.exists():
            current = _read_json(current_path)
            receipts = _receipts_for_brief(paths, slot_id, current.get("brief_sha256", ""), brief=current)
            try:
                current = slot_brief_inventory.validate_brief(
                    current,
                    graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                    graph=graph,
                    architecture=architecture,
                    contract=contract,
                    review_policy_sha256=policy_sha,
                )
                slot_brief_review.assert_reviewed_brief_evidence(
                    brief=current, architecture=architecture, graph=graph, policy=policy, receipts=receipts
                )
                return result_payload(status="REVIEWED", brief=current)
            except Exception as exc:
                return result_payload(
                    status="BLOCKED",
                    reason=f"existing reviewed artifact is invalid: {exc}",
                )

        checkpoints = _checkpoints_for_slot(paths, queue, plan)
        latest = checkpoints[-1] if checkpoints else None
        if latest and latest["attempt"] >= MAX_SEMANTIC_ATTEMPTS and latest["status"] in {"REJECTED", "BLOCKED"}:
            rejected_generation = list(
                paths["generation_raw"].glob(
                    f"{plan['slot_id']}-attempt-{latest['attempt']}-generation_rejected-*.json"
                )
            )
            if latest["status"] == "REJECTED" or rejected_generation:
                return result_payload(
                    status="BLOCKED",
                    reason=f"semantic attempt limit exhausted ({MAX_SEMANTIC_ATTEMPTS})",
                )
        attempt = _next_attempt(paths, queue, plan)
        brief: dict[str, Any] | None = None
        if latest and latest["status"] == "GENERATED" and latest["brief_sha256"]:
            brief = _load_draft(
                paths, plan=plan, graph=graph, architecture=architecture, contract=contract,
                policy_sha256=policy_sha, brief_sha256=latest["brief_sha256"],
            )
            if brief is not None:
                attempt = latest["attempt"]

        if brief is None and (latest is None or latest["status"] in {"GENERATED", "BLOCKED"}):
            recovered_draft = _load_any_draft(
                paths, plan=plan, graph=graph, architecture=architecture, contract=contract,
                policy_sha256=policy_sha,
                desired_attempt=latest["attempt"] if latest is not None else None,
            )
            if recovered_draft is not None:
                brief, recovered_attempt = recovered_draft
                attempt = max(attempt if latest else 0, recovered_attempt)

        if brief is None:
            attempt = max(attempt, 1)
            checkpoint(status="PENDING", attempt=attempt, updated_at=now)
            prior_briefs = [
                b for b in _load_prior_reviewed_briefs(
                    paths,
                    architecture=architecture,
                    graph=graph,
                    contract=contract,
                    policy=policy,
                )
                if b.get("slot_id") != slot_id
            ]
            packet = slot_brief_generation.build_generation_packet(
                plan=plan, architecture=architecture, graph=graph, contract=contract,
                prior_briefs=prior_briefs,
                attempt=attempt,
            )
            try:
                heartbeat.assert_active()
                persisted_packet = _load_generation_invocation(
                    paths, slot_id=slot_id, attempt=attempt
                )
                if persisted_packet is not None:
                    persisted_size = len(canonical_json(persisted_packet).encode("utf-8"))
                    if persisted_size < slot_brief_generation.MAX_GENERATION_PACKET_BYTES:
                        packet = persisted_packet
                    else:
                        # The previous invocation was rejected locally before
                        # a semantic model call because its context exceeded
                        # the bounded packet budget. Do not replay it; start a
                        # fresh attempt with the compact context policy.
                        attempt += 1
                        checkpoint(status="PENDING", attempt=attempt, updated_at=now)
                        packet = slot_brief_generation.build_generation_packet(
                            plan=plan,
                            architecture=architecture,
                            graph=graph,
                            contract=contract,
                            prior_briefs=prior_briefs,
                            attempt=attempt,
                        )
                packet_sha = sha256_json(packet)
                provider_key = slot_brief_worker.brief_provider_idempotency_key(
                    plan=plan, packet=packet, attempt=attempt
                )
                _persist_generation_invocation(
                    paths,
                    slot_id=slot_id,
                    attempt=attempt,
                    packet=packet,
                    provider_key=provider_key,
                )
                generation_started = time.monotonic()
                try:
                    if generation_call is None:
                        generation_calls += 1
                        result = slot_brief_worker.run_one_slot(
                            plan=plan, architecture=architecture, graph=graph, contract=contract,
                            review_policy_sha256=policy_sha, prior_briefs=prior_briefs, attempt=attempt, generation_packet=packet,
                        )
                        brief = result["brief"]
                        raw_generation_response = brief
                    else:
                        generation_calls += 1
                        semantic, raw_generation_response = _normalize_model_result(generation_call(plan, packet))
                        brief = slot_brief_worker.build_brief_from_model_output(
                            plan=plan, model_output=semantic, architecture=architecture, graph=graph,
                            contract=contract, review_policy_sha256=policy_sha, brief_version=attempt,
                        )
                finally:
                    stage_timings["generation_model_seconds"] += time.monotonic() - generation_started
                heartbeat.assert_active()
                persist_started = time.monotonic()
                persist_raw(directory_key="generation_raw", attempt=attempt, stage="generation", packet_sha256=packet_sha, response=raw_generation_response)
                persist_draft(brief, attempt)
                checkpoint(status="GENERATED", attempt=attempt, brief_sha256=brief["brief_sha256"], updated_at=now)
                stage_timings["generation_persist_seconds"] += time.monotonic() - persist_started
            except Exception as exc:
                rejected_output = getattr(exc, "model_output", None)
                if isinstance(rejected_output, dict):
                    try:
                        persist_raw(
                            directory_key="generation_raw",
                            attempt=attempt,
                            stage="generation_rejected",
                            packet_sha256=packet_sha,
                            response=rejected_output,
                        )
                    except Exception:
                        pass
                record_blocked(status="BLOCKED", attempt=attempt, updated_at=now)
                return result_payload(status="BLOCKED", reason=str(exc), model_calls=generation_calls + review_calls)

        if stop_after == "generation":
            return result_payload(
                status="GENERATED",
                brief=brief,
                model_calls=generation_calls,
            )

        review_packet_base = _build_review_packet(brief, role="slot_lead_consistency", focus="一致性、教育测量目标与可命题性")
        review_packet_sha = sha256_json(review_packet_base)
        write_artifact(paths["review_packets"] / f"{slot_id}-attempt-{attempt}-lead.json", review_packet_base)
        receipts = _receipts_for_brief(paths, slot_id, brief["brief_sha256"], brief=brief)
        lead = _find_receipt(receipts, "lead_consistency", "slot_lead_consistency")
        if lead is None:
            try:
                heartbeat.assert_active()
                review_calls += 1
                review_started = time.monotonic()
                try:
                    result = _default_review_call("slot_lead_consistency", review_packet_base) if review_call is None else review_call("slot_lead_consistency", review_packet_base)
                finally:
                    stage_timings["lead_review_model_seconds"] += time.monotonic() - review_started
                semantic, raw_response = _normalize_model_result(result)
                semantic = _validate_review_semantics(semantic)
                heartbeat.assert_active()
                raw_ref, raw_sha = persist_raw(directory_key="review_raw", attempt=attempt, stage="lead", packet_sha256=review_packet_sha, response=raw_response)
                lead = slot_brief_review.build_review_receipt(
                    brief=brief, architecture=architecture, graph=graph, policy=policy,
                    review_kind="lead_consistency", review_focus="一致性、教育测量目标与可命题性",
                    reviewer_role="slot_lead_consistency", invocation_id=f"{plan['operation_key']}:brief-review:lead:v{attempt}",
                    input_packet_sha256=review_packet_sha, raw_response_ref=raw_ref, raw_response_sha256=raw_sha,
                    created_at=now, tool_version=TOOL_VERSION, verdict=semantic["verdict"], confidence=semantic["confidence"], findings=semantic["findings"],
                )
                _persist_review_receipt(paths, lead)
                receipts.append(lead)
            except Exception as exc:
                record_blocked(status="BLOCKED", attempt=attempt, brief_sha256=brief["brief_sha256"], updated_at=now)
                return result_payload(status="BLOCKED", reason=str(exc), model_calls=generation_calls + review_calls)

        required_reasons = slot_brief_review._targeted_critic_reasons(brief)
        if lead["confidence"] < 0.90:
            required_reasons.add("lead_uncertainty")
        if lead["verdict"] not in set(policy["accepted_verdicts"]):
            checkpoint(status="REJECTED", attempt=attempt, brief_sha256=brief["brief_sha256"], updated_at=now)
            return result_payload(
                status="REJECTED",
                reason="lead review did not pass",
                model_calls=generation_calls + review_calls,
            )

        targeted_role = "assessment_architect"
        targeted = _find_receipt(receipts, "targeted_critic", targeted_role)
        if required_reasons and targeted is None:
            targeted_packet = _build_review_packet(brief, role=targeted_role, focus=",".join(sorted(required_reasons)))
            targeted_packet_sha = sha256_json(targeted_packet)
            write_artifact(paths["review_packets"] / f"{slot_id}-attempt-{attempt}-targeted.json", targeted_packet)
            try:
                heartbeat.assert_active()
                review_calls += 1
                review_started = time.monotonic()
                try:
                    result = _default_review_call(targeted_role, targeted_packet) if review_call is None else review_call(targeted_role, targeted_packet)
                finally:
                    stage_timings["targeted_review_model_seconds"] += time.monotonic() - review_started
                semantic, raw_response = _normalize_model_result(result)
                semantic = _validate_review_semantics(semantic)
                heartbeat.assert_active()
                raw_ref, raw_sha = persist_raw(directory_key="review_raw", attempt=attempt, stage="targeted", packet_sha256=targeted_packet_sha, response=raw_response)
                targeted = slot_brief_review.build_review_receipt(
                    brief=brief, architecture=architecture, graph=graph, policy=policy,
                    review_kind="targeted_critic", review_focus=",".join(sorted(required_reasons)),
                    reviewer_role=targeted_role, invocation_id=f"{plan['operation_key']}:brief-review:targeted:v{attempt}",
                    input_packet_sha256=targeted_packet_sha, raw_response_ref=raw_ref, raw_response_sha256=raw_sha,
                    created_at=now, tool_version=TOOL_VERSION, verdict=semantic["verdict"], confidence=semantic["confidence"], findings=semantic["findings"],
                )
                _persist_review_receipt(paths, targeted)
                receipts.append(targeted)
            except Exception as exc:
                record_blocked(status="BLOCKED", attempt=attempt, brief_sha256=brief["brief_sha256"], updated_at=now)
                return result_payload(status="BLOCKED", reason=str(exc), model_calls=generation_calls + review_calls)

        try:
            publication_started = time.monotonic()
            reviewed = slot_brief_review.mark_brief_reviewed(
                brief=brief, architecture=architecture, graph=graph, contract=contract, policy=policy,
                review_policy_sha256=policy_sha, receipts=receipts,
                architecture_review_policy=slot_architecture_review.load_policy(paths["architecture_policy"]),
                architecture_receipts=[slot_architecture_review.validate_review_receipt(_read_json(path)) for path in sorted(paths["architecture_receipts"].glob("*.json")) if path.name.endswith(".json")],
            )
            write_artifact(paths["reviewed"] / f"{slot_id}.json", reviewed)
            checkpoint(status="REVIEWED", attempt=attempt, brief_sha256=reviewed["brief_sha256"], updated_at=now)
            stage_timings["publication_seconds"] += time.monotonic() - publication_started
            return result_payload(
                status="REVIEWED",
                brief=reviewed,
                model_calls=generation_calls + review_calls,
            )
        except Exception as exc:
            checkpoint(status="REJECTED", attempt=attempt, brief_sha256=brief["brief_sha256"], updated_at=now)
            return result_payload(
                status="REJECTED",
                reason=str(exc),
                model_calls=generation_calls + review_calls,
            )
    finally:
        heartbeat.stop()
        lease_store.release(lease)


def run_next_slot_brief(
    *,
    project_root: Path | str,
    owner_id: str,
    generation_call: GenerationCall | None = None,
    review_call: ReviewCall | None = None,
    now: str,
    lease_ttl_seconds: float = 300.0,
) -> dict[str, Any]:
    """Claim the first unfinished queue plan without coupling other slots."""
    root = Path(project_root)
    try:
        graph, architecture, contract, policy, queue = _load_authority(root)
        paths = _paths(root)
        policy_sha = slot_brief_review.policy_digest(policy)
        # The previous implementation revalidated every reviewed brief and
        # scanned the complete receipt directory on every ``--next`` call.
        # That made dispatch cost grow with the square of the queue size. The
        # append-only checkpoint stream already records the terminal state for
        # each slot; use it for scheduling and leave full evidence validation
        # to the selected slot and the Phase 0 gate.
        plan_by_slot = {plan["slot_id"]: plan for plan in queue["plans"]}
        latest_checkpoints: dict[str, dict[str, Any]] = {}
        for path in paths["checkpoints"].glob("*.json"):
            try:
                checkpoint = slot_brief_generation.validate_checkpoint(_read_json(path))
            except (OSError, SlotBriefGenerationError):
                continue
            plan = plan_by_slot.get(checkpoint["slot_id"])
            if plan is None:
                continue
            if checkpoint["queue_sha256"] != queue["queue_sha256"]:
                continue
            if checkpoint["plan_sha256"] != slot_brief_generation.plan_digest(plan):
                continue
            previous = latest_checkpoints.get(checkpoint["slot_id"])
            if previous is None or checkpoint["event_seq"] > previous["event_seq"]:
                latest_checkpoints[checkpoint["slot_id"]] = checkpoint

        reviewed_slots = {
            slot_id
            for slot_id, checkpoint in latest_checkpoints.items()
            if checkpoint["status"] == "REVIEWED"
            and (paths["reviewed"] / f"{slot_id}.json").exists()
        }
        blocked_plans: list[dict[str, Any]] = []
        for plan in sorted(queue["plans"], key=lambda item: item["ordinal"]):
            if plan["slot_id"] in reviewed_slots:
                continue
            lease_path = paths["leases"] / f"{plan['slot_id']}.json"
            if lease_path.exists():
                try:
                    lease = SlotBriefLeaseStore(paths["leases"])._validate(_read_json(lease_path))
                    if lease["expires_at_epoch"] > time.time():
                        continue
                except SlotBriefOrchestrationError:
                    return {
                        "schema_version": ORCHESTRATION_SCHEMA_VERSION,
                        "status": "BLOCKED",
                        "reason": f"invalid existing lease for {plan['slot_id']}",
                        "model_calls": 0,
                    }
            checkpoint = latest_checkpoints.get(plan["slot_id"])
            if checkpoint and checkpoint["status"] in {"BLOCKED", "REJECTED"}:
                blocked_plans.append(plan)
                continue
            return run_one_slot_brief(
                project_root=root,
                slot_id=plan["slot_id"],
                owner_id=owner_id,
                generation_call=generation_call,
                review_call=review_call,
                now=now,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        if blocked_plans:
            plan = blocked_plans[0]
            return run_one_slot_brief(
                project_root=root,
                slot_id=plan["slot_id"],
                owner_id=owner_id,
                generation_call=generation_call,
                review_call=review_call,
                now=now,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        return {
            "schema_version": ORCHESTRATION_SCHEMA_VERSION,
            "status": "COMPLETE",
            "reason": "no unfinished slot is available",
            "model_calls": 0,
        }
    except Exception as exc:
        return {
            "schema_version": ORCHESTRATION_SCHEMA_VERSION,
            "status": "BLOCKED",
            "reason": str(exc),
            "model_calls": 0,
        }


# Local aliases keep exception handling readable without importing private names.
SlotBriefGenerationError = slot_brief_generation.SlotBriefGenerationError
SlotBriefReviewError = slot_brief_review.SlotBriefReviewError
