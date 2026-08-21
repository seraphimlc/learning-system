"""Adapters from the durable async queue to the v20 single-slot workflows.

The queue owns scheduling. These handlers own only stage-specific model work
and the handoff of the immutable artifact produced by the preceding stage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import (
    single_slot_production,
    slot_authorization,
    slot_brief_orchestration,
    v20_bank_namespace,
)
from .async_question_pipeline import StageResult


class AsyncWorkerError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AsyncWorkerConfig:
    project_root: Path
    owner_prefix: str = "v20-async"
    manifest: dict[str, Any] | None = None
    now_factory: Callable[[], str] = _utc_now

    def root(self) -> Path:
        return Path(self.project_root)


def _relative_ref(root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if not candidate.is_file():
        raise AsyncWorkerError(f"artifact file does not exist: {path}")
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise AsyncWorkerError("artifact path escapes the project root") from exc


def _load_json_ref(root: Path, ref: str) -> dict[str, Any]:
    if not isinstance(ref, str) or not ref.strip():
        raise AsyncWorkerError("stage artifact reference is missing")
    path = (root / ref).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise AsyncWorkerError("stage artifact reference escapes the project root") from exc
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AsyncWorkerError(f"unable to load stage artifact: {ref}") from exc
    if not isinstance(value, dict):
        raise AsyncWorkerError(f"stage artifact must be an object: {ref}")
    return value


def _find_brief_ref(root: Path, slot_id: str, *, status: str, brief_sha256: str) -> str:
    base = root / "data/question_banks/v20"
    if status == "REVIEWED":
        path = base / "slot_brief_reviewed" / f"{slot_id}.json"
        if not path.exists():
            raise AsyncWorkerError("reviewed brief artifact was not published")
        return _relative_ref(root, path)
    matches: list[Path] = []
    draft_dir = base / "slot_brief_drafts"
    draft_paths = [draft_dir / f"{slot_id}.json"]
    draft_paths.extend(draft_dir.glob(f"{slot_id}-*.json"))
    for path in sorted(set(draft_paths)):
        try:
            value = _load_json_ref(root, _relative_ref(root, path))
        except AsyncWorkerError:
            continue
        if value.get("brief_sha256") == brief_sha256:
            matches.append(path)
    if not matches:
        raise AsyncWorkerError("generated brief artifact was not persisted")
    return _relative_ref(root, matches[-1])


def _result_reason(result: dict[str, Any]) -> str:
    reason = result.get("reason")
    return reason if isinstance(reason, str) and reason else "stage did not pass"


def _owner(config: AsyncWorkerConfig, stage: str, slot_id: str) -> str:
    return f"{config.owner_prefix}:{stage}:{slot_id}"


def _blocked(reason: str) -> StageResult:
    return StageResult(outcome="BLOCKED", reason=reason)


def _brief_generation_handler(config: AsyncWorkerConfig, slot: dict[str, Any]) -> StageResult:
    root = config.root()
    slot_id = slot["slot_id"]
    try:
        result = slot_brief_orchestration.run_one_slot_brief(
            project_root=root,
            slot_id=slot_id,
            owner_id=_owner(config, "brief-generation", slot_id),
            now=config.now_factory(),
            stop_after="generation",
        )
        status = result.get("status")
        if status in {"GENERATED", "REVIEWED"} and isinstance(result.get("brief"), dict):
            brief = result["brief"]
            ref = _find_brief_ref(
                root,
                slot_id,
                status=status,
                brief_sha256=brief["brief_sha256"],
            )
            return StageResult(
                outcome="PASS",
                artifact_ref=ref,
                artifact_sha256=brief["brief_sha256"],
            )
        if status == "REJECTED":
            return StageResult(outcome="RETRY", reason=_result_reason(result))
        return _blocked(_result_reason(result))
    except Exception as exc:
        return _blocked(f"brief generation failed: {exc}")


def _brief_review_handler(config: AsyncWorkerConfig, slot: dict[str, Any]) -> StageResult:
    root = config.root()
    slot_id = slot["slot_id"]
    try:
        _load_json_ref(root, slot["brief_ref"])

        def no_regeneration(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AsyncWorkerError("brief review cannot regenerate a missing draft")

        result = slot_brief_orchestration.run_one_slot_brief(
            project_root=root,
            slot_id=slot_id,
            owner_id=_owner(config, "brief-review", slot_id),
            generation_call=no_regeneration,
            now=config.now_factory(),
        )
        status = result.get("status")
        if status == "REVIEWED" and isinstance(result.get("brief"), dict):
            brief = result["brief"]
            ref = _find_brief_ref(
                root,
                slot_id,
                status="REVIEWED",
                brief_sha256=brief["brief_sha256"],
            )
            return StageResult(
                outcome="PASS",
                artifact_ref=ref,
                artifact_sha256=brief["brief_sha256"],
            )
        if status == "REJECTED":
            return StageResult(outcome="RETRY", reason=_result_reason(result))
        return _blocked(_result_reason(result))
    except Exception as exc:
        return _blocked(f"brief review failed: {exc}")


def _load_manifest(config: AsyncWorkerConfig) -> dict[str, Any]:
    if config.manifest is not None:
        return dict(config.manifest)
    return v20_bank_namespace.load_manifest(v20_bank_namespace.manifest_path(config.root()))


def _question_generation_handler(config: AsyncWorkerConfig, slot: dict[str, Any]) -> StageResult:
    root = config.root()
    slot_id = slot["slot_id"]
    try:
        brief = _load_json_ref(root, slot["brief_ref"])
        authorization = None
        if config.manifest is not None:
            manifest = _load_manifest(config)
        else:
            authorization = slot_authorization.authorize_slot(root, slot_id)
            manifest = slot_authorization.as_production_manifest(authorization)

        def no_review(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AsyncWorkerError("question generation cannot review its own candidate")

        candidate_version = slot["question_attempt"] + 1
        result = single_slot_production.run_single_slot(
            project_root=root,
            manifest=manifest,
            brief=brief,
            candidate_version=candidate_version,
            critic_call=no_review,
            stop_after="generation",
            authorization=authorization,
        )
        status = result.get("status")
        if status in {"GENERATED", "STAGED"}:
            candidate_sha256 = result.get("candidate_sha256")
            candidate_path = result.get("candidate_path")
            if not isinstance(candidate_sha256, str) or not isinstance(candidate_path, str):
                raise AsyncWorkerError("question generation returned incomplete artifact evidence")
            return StageResult(
                outcome="PASS",
                artifact_ref=_relative_ref(root, candidate_path),
                artifact_sha256=candidate_sha256,
            )
        if status == "RETRY_REQUIRED":
            return StageResult(outcome="RETRY", reason=_result_reason(result))
        return _blocked(_result_reason(result))
    except Exception as exc:
        return _blocked(f"question generation failed: {exc}")


def _question_review_handler(config: AsyncWorkerConfig, slot: dict[str, Any]) -> StageResult:
    root = config.root()
    slot_id = slot["slot_id"]
    try:
        brief = _load_json_ref(root, slot["brief_ref"])
        authorization = None
        if config.manifest is not None:
            manifest = _load_manifest(config)
        else:
            authorization = slot_authorization.authorize_slot(root, slot_id)
            manifest = slot_authorization.as_production_manifest(authorization)

        def no_regeneration(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AsyncWorkerError("question review cannot regenerate a missing candidate")

        result = single_slot_production.run_single_slot(
            project_root=root,
            manifest=manifest,
            brief=brief,
            candidate_version=slot["question_attempt"],
            model_call=no_regeneration,
            authorization=authorization,
        )
        status = result.get("status")
        if status in {"STAGED", "ACCEPTED"}:
            candidate_sha256 = result.get("candidate_sha256")
            candidate_path = result.get("candidate_path")
            if not isinstance(candidate_sha256, str) or not isinstance(candidate_path, str):
                raise AsyncWorkerError("question review returned incomplete staging evidence")
            return StageResult(
                outcome="PASS",
                artifact_ref=_relative_ref(root, candidate_path),
                artifact_sha256=candidate_sha256,
            )
        if status == "RETRY_REQUIRED":
            return StageResult(outcome="RETRY", reason=_result_reason(result))
        return _blocked(_result_reason(result))
    except Exception as exc:
        return _blocked(f"question review failed: {exc}")


def build_handlers(config: AsyncWorkerConfig) -> dict[str, Callable[[dict[str, Any]], StageResult]]:
    """Build the four production handlers without starting the pipeline."""
    return {
        "brief_generation": lambda slot: _brief_generation_handler(config, slot),
        "brief_review": lambda slot: _brief_review_handler(config, slot),
        "question_generation": lambda slot: _question_generation_handler(config, slot),
        "question_review": lambda slot: _question_review_handler(config, slot),
    }
