from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import question_bank_v18_activation_gate


class AdminGateError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AdminGateError(f"ADMIN_GATE_SOURCE_MISSING: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_expert_report(root: Path) -> Path | None:
    report_dir = root / "data/admin/reviews"
    reports = sorted(report_dir.glob("EXPERT-QA-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def validate_admin_readiness(
    *,
    root: Path,
    manifest_path: Path | None = None,
    mode: str = "sample-integrity",
    expert_report_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path or root / "data/question_banks/v18/sample_gate_manifest_v18.json"
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    try:
        if mode == "sample-integrity":
            base_report = question_bank_v18_activation_gate.validate_sample_integrity(manifest_path)
        elif mode == "activation-readiness":
            base_report = question_bank_v18_activation_gate.validate_activation_readiness(manifest_path)
        else:
            raise AdminGateError(f"ADMIN_GATE_UNSUPPORTED_MODE: {mode}")
    except question_bank_v18_activation_gate.GateError as exc:
        return {
            "schema_version": "2026-07-23.codex-admin.readiness-gate.v1",
            "status": "FAIL_CLOSED",
            "mode": mode,
            "base_gate_status": "FAIL",
            "reason": str(exc),
            "activation_allowed": False,
        }

    expert_path = expert_report_path
    if expert_path is None:
        expert_path = _latest_expert_report(root)
    elif not expert_path.is_absolute():
        expert_path = root / expert_path

    expert_summary: dict[str, Any] | None = None
    if expert_path is not None:
        expert = _load_json(expert_path)
        finding_counts = expert.get("finding_counts") or {}
        blocking = bool(finding_counts.get("P0") or finding_counts.get("P1") or expert.get("status") == "NEEDS_FIX")
        expert_summary = {
            "path": str(expert_path.relative_to(root) if expert_path.is_relative_to(root) else expert_path),
            "status": expert.get("status"),
            "finding_counts": finding_counts,
            "blocking": blocking,
        }
        if blocking:
            return {
                "schema_version": "2026-07-23.codex-admin.readiness-gate.v1",
                "status": "FAIL_CLOSED",
                "mode": mode,
                "base_gate_status": base_report["status"],
                "expert_gate": expert_summary,
                "reason": "expert_quality_review_has_blocking_findings",
                "activation_allowed": False,
            }

    activation_allowed = bool(base_report.get("activation_allowed")) and mode == "activation-readiness"
    return {
        "schema_version": "2026-07-23.codex-admin.readiness-gate.v1",
        "status": "PASS" if activation_allowed else "PASS_WITH_SCOPE",
        "mode": mode,
        "base_gate_status": base_report["status"],
        "base_gate": base_report,
        "expert_gate": expert_summary,
        "activation_allowed": activation_allowed,
    }
