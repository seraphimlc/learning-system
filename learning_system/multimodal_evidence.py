from __future__ import annotations

import hashlib
import json
from typing import Any


INPUT_EVIDENCE_SCHEMA_VERSION = "2026-07-25.answer-input-evidence.v1"
INPUT_MODES = frozenset({"typed", "structured", "photo", "handwriting", "voice", "mixed"})
RECOGNITION_RUN_STATUSES = frozenset({"usable", "unclear", "not_configured", "error"})
RECOGNITION_STATUSES = frozenset(
    {"not_required", "raw_media", "recognized", "unclear", "confirmed", "corrected", "rejected"}
)
CONFIRMATION_REQUIRED_MODES = frozenset({"handwriting", "voice"})
HANDWRITING_RECOGNIZER_VERSION = "2026-07-25.handwriting-recognition.v1"
VOICE_RECOGNIZER_VERSION = "2026-07-25.browser-speech-recognition.v1"
PHOTO_ANSWER_RECOGNIZER_VERSION = "2026-07-26.photo-answer-ocr.v1"
MEDIA_VERSION = 1
RECOGNITION_TRUST_CLASSIFICATIONS = frozenset(
    {"server_verified", "client_unverified", "unknown"}
)


def normalize_input_evidence(
    raw: Any,
    *,
    fallback_mode: str,
    fallback_answer_text: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return {
            "schema_version": INPUT_EVIDENCE_SCHEMA_VERSION,
            "input_mode": fallback_mode,
            "recognition_status": "not_required",
            "recognition_source": "",
            "recognized_text": "",
            "recognition_confidence": None,
            "critical_token_uncertainties": [],
            "child_confirmed": False,
            "child_confirmed_text": fallback_answer_text,
            "raw": {},
        }
    schema_version = str(raw.get("schema_version") or INPUT_EVIDENCE_SCHEMA_VERSION)
    if schema_version != INPUT_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported answer input evidence schema")
    input_mode = str(raw.get("input_mode") or fallback_mode)
    if input_mode not in INPUT_MODES:
        raise ValueError("unknown answer input mode")
    recognition = raw.get("recognition") if isinstance(raw.get("recognition"), dict) else {}
    recognition_handle = str(
        raw.get("recognition_handle") or recognition.get("handle") or ""
    ).strip()[:160]
    recognition_status = str(raw.get("recognition_status") or "not_required")
    if recognition_status not in RECOGNITION_STATUSES:
        raise ValueError("unknown recognition status")
    confidence_raw = raw.get("recognition_confidence")
    if confidence_raw in {None, ""}:
        confidence = None
    else:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("recognition confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("recognition confidence must be between 0 and 1")
    uncertainties_raw = raw.get("critical_token_uncertainties")
    if uncertainties_raw is None:
        uncertainties_raw = []
    if not isinstance(uncertainties_raw, list) or len(uncertainties_raw) > 24:
        raise ValueError("critical token uncertainties must be a short list")
    uncertainties: list[dict[str, str]] = []
    for value in uncertainties_raw:
        if not isinstance(value, dict):
            raise ValueError("critical token uncertainty must be an object")
        uncertainties.append(
            {
                "token": str(value.get("token") or "")[:40],
                "location": str(value.get("location") or "")[:120],
                "reason": str(value.get("reason") or "")[:240],
            }
        )
    child_confirmed = bool(raw.get("child_confirmed", False))
    recognized_text = str(raw.get("recognized_text") or "").strip()[:4000]
    confirmed_text = str(raw.get("child_confirmed_text") or fallback_answer_text or "").strip()[:4000]
    if input_mode in CONFIRMATION_REQUIRED_MODES:
        if not recognition_handle or not child_confirmed or not confirmed_text:
            raise ValueError("recognized handwriting or voice must be confirmed before submission")
        recognition_status = "confirmed"
    return {
        "schema_version": schema_version,
        "input_mode": input_mode,
        "recognition_status": recognition_status,
        "recognition_source": "",
        "recognized_text": recognized_text,
        "recognition_confidence": confidence,
        "critical_token_uncertainties": uncertainties,
        "child_confirmed": child_confirmed,
        "child_confirmed_text": confirmed_text,
        "raw": {
            "recognition_handle": recognition_handle,
            "media_version": int(raw.get("media_version") or MEDIA_VERSION),
            "client_corrections": (
                raw.get("client_corrections")[:50]
                if isinstance(raw.get("client_corrections"), list)
                else []
            ),
        },
    }


def allows_downstream_evidence(value: dict[str, Any] | None) -> bool:
    if not value:
        return True
    input_mode = str(value.get("input_mode") or "typed")
    if input_mode not in CONFIRMATION_REQUIRED_MODES:
        return True
    return (
        value.get("recognition_status") in {"confirmed", "corrected"}
        and bool(value.get("child_confirmed"))
        and bool(str(value.get("child_confirmed_text") or "").strip())
    )


def recognition_trust_classification(
    *,
    input_mode: str,
    provider_mode: str,
    recognition_source: str,
) -> str:
    if (
        input_mode == "voice"
        and provider_mode == "recorded_browser_recognition"
        and recognition_source == "browser_speech_recognition"
    ):
        return "client_unverified"
    if provider_mode in {"live_model", "recorded_model"} and recognition_source:
        return "server_verified"
    return "unknown"


def allows_mastery_evidence_from_recognition(
    recognition_run: dict[str, Any] | None,
) -> bool:
    if not recognition_run:
        return True
    if str(recognition_run.get("input_mode") or "") != "voice":
        return True
    return (
        recognition_run.get("trust_classification") == "server_verified"
        and recognition_run.get("recognition_source") != "browser_speech_recognition"
    )


def validate_recognition_binding(
    recognition_run: dict[str, Any],
    *,
    flow_step_id: str,
    step_revision: int,
    question_id: str,
    input_mode: str,
    media_sha256: str,
    media_byte_size: int,
    media_version: int = MEDIA_VERSION,
) -> None:
    expected = {
        "flow_step_id": flow_step_id,
        "step_revision": int(step_revision),
        "question_id": question_id,
        "input_mode": input_mode,
        "media_sha256": media_sha256,
        "media_byte_size": int(media_byte_size),
        "media_version": int(media_version),
    }
    for key, value in expected.items():
        actual = recognition_run.get(key)
        if key in {"step_revision", "media_byte_size", "media_version"}:
            actual = int(actual or 0)
        if actual != value:
            raise ValueError(f"recognition handle {key} mismatch")
    if recognition_run.get("recognition_status") not in {"usable", "unclear"}:
        raise ValueError("recognition handle is not usable for confirmation")
    if not str(recognition_run.get("output_digest_sha256") or ""):
        raise ValueError("recognition handle is missing output lineage")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def submission_request_digest(
    *,
    step_handle: str,
    position: int,
    stuck: bool,
    answer_text: str,
    interaction_response: dict[str, Any],
    input_evidence: dict[str, Any],
    media_descriptors: list[dict[str, Any]],
) -> str:
    return canonical_sha256(
        {
            "step_handle": step_handle,
            "position": int(position),
            "stuck": bool(stuck),
            "answer_text": answer_text,
            "interaction_response": interaction_response,
            "input_evidence": {
                "schema_version": input_evidence.get("schema_version"),
                "input_mode": input_evidence.get("input_mode"),
                "child_confirmed": bool(input_evidence.get("child_confirmed")),
                "child_confirmed_text": input_evidence.get("child_confirmed_text") or "",
                "recognition_handle": (input_evidence.get("raw") or {}).get("recognition_handle") or "",
                "media_version": int((input_evidence.get("raw") or {}).get("media_version") or MEDIA_VERSION),
                "client_corrections": list((input_evidence.get("raw") or {}).get("client_corrections") or []),
            },
            "media": sorted(
                media_descriptors,
                key=lambda item: (str(item.get("kind") or ""), str(item.get("sha256") or "")),
            ),
        }
    )
