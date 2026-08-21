"""Deterministic preflight checks before starting a v20 question queue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .. import model_router
from .question_bank_authority import load_authority_index


class QuestionPipelinePreflightError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionPipelinePreflightError(f"unable to load {path}") from exc
    if not isinstance(value, dict):
        raise QuestionPipelinePreflightError(f"expected object: {path}")
    return value


def validate_slot_selection(
    project_root: Path | str,
    slot_ids: Iterable[str],
    *,
    require_reviewed_briefs: bool,
) -> dict[str, Any]:
    root = Path(project_root)
    requested = list(slot_ids)
    if not requested or len(set(requested)) != len(requested):
        raise QuestionPipelinePreflightError("slot selection must be nonempty and unique")
    manifest_path = root / "data/question_banks/v20/slot_manifest_v20.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        manifest_ids = {item.get("slot_id") for item in manifest.get("slots", []) if isinstance(item, dict)}
        missing = sorted(set(requested) - manifest_ids)
        if missing:
            raise QuestionPipelinePreflightError(
                f"slot selection is outside the frozen slot manifest: {missing}"
            )
    checked: list[dict[str, Any]] = []
    authority = load_authority_index(root)
    occupied = {item.get("slot_id") for item in (authority or {}).get("entries", [])}
    for slot_id in requested:
        if not isinstance(slot_id, str) or not slot_id.strip():
            raise QuestionPipelinePreflightError("slot id must be nonempty")
        if slot_id in occupied:
            raise QuestionPipelinePreflightError(
                f"slot already has an authoritative candidate: {slot_id}"
            )
        brief_path = root / "data/question_banks/v20/slot_brief_reviewed" / f"{slot_id}.json"
        if require_reviewed_briefs:
            brief = _load_json(brief_path)
            if brief.get("status") != "REVIEWED" or brief.get("slot_id") != slot_id:
                raise QuestionPipelinePreflightError(f"brief is not reviewed for {slot_id}")
            if brief.get("operation_key") != f"v20:{slot_id}":
                raise QuestionPipelinePreflightError(f"brief operation key is invalid for {slot_id}")
            checked.append({"slot_id": slot_id, "brief_sha256": brief.get("brief_sha256", "")})
        else:
            checked.append({"slot_id": slot_id})
    return {"slot_count": len(requested), "slots": checked}


def validate_routes() -> dict[str, dict[str, Any]]:
    routes = {
        "question_designer": model_router.question_designer_route(),
        "question_math_reviewer": model_router.question_reviewer_route(stage="math_education"),
        "question_collision_reviewer": model_router.question_reviewer_route(stage="collision"),
    }
    statuses: dict[str, dict[str, Any]] = {}
    for name, route in routes.items():
        status = model_router.route_status(route).as_dict()
        statuses[name] = status
        if not status["enabled"]:
            raise QuestionPipelinePreflightError(f"model route is not configured: {name}")
        if not status["model"] or not status["base_url"] or not status["endpoints"]:
            raise QuestionPipelinePreflightError(f"model route is incomplete: {name}")
    return statuses


def run_preflight(
    project_root: Path | str,
    slot_ids: Iterable[str],
    *,
    require_reviewed_briefs: bool,
) -> dict[str, Any]:
    selection = validate_slot_selection(
        project_root,
        slot_ids,
        require_reviewed_briefs=require_reviewed_briefs,
    )
    return {"selection": selection, "routes": validate_routes()}
