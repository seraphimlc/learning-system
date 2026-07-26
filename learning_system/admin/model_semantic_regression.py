from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import internal_agents, model_router
from .production_loop import AdminProductionError, _relative


ANSWER_CASES_SCHEMA_VERSION = "2026-07-23.model-semantic-regression.answer-cases.v1"
ANSWER_REGRESSION_SCHEMA_VERSION = "2026-07-23.codex-admin.model-semantic-regression.answer.v1"
DEFAULT_ANSWER_CASES_PATH = Path("data/quality_oracles/answer_semantic_cases_v1.json")
DEFAULT_BASE_URL = "https://api.amux.xyb2b.com/v1"


def _load_cases(root: Path, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else root / path
    if not resolved.exists():
        raise AdminProductionError(f"ADMIN_MODEL_REGRESSION_CASES_MISSING: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdminProductionError(f"ADMIN_MODEL_REGRESSION_CASES_INVALID_JSON: {resolved}: {exc}") from exc
    if payload.get("schema_version") != ANSWER_CASES_SCHEMA_VERSION:
        raise AdminProductionError("ADMIN_MODEL_REGRESSION_UNSUPPORTED_CASE_SCHEMA")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AdminProductionError("ADMIN_MODEL_REGRESSION_CASES_EMPTY")
    return payload


def _infer_provider(model: str) -> str:
    lowered = model.lower()
    if "doubao" in lowered:
        return "doubao"
    if "deepseek" in lowered:
        return "deepseek"
    if "glm" in lowered:
        return "glm"
    if lowered.startswith("gpt-"):
        return "gpt"
    return "openai-compatible"


def _model_api_key_env(model: str) -> str:
    return f"AI_MODEL_{model_router._env_key(model)}_API_KEY"


def _model_route(*, model: str, default_api_key: str, base_url: str, timeout_seconds: float) -> model_router.ModelRoute:
    provider = _infer_provider(model)
    api_key = os.environ.get(_model_api_key_env(model), default_api_key)
    return model_router.ModelRoute(
        agent_key="answer_analysis_agent",
        task="answer_semantic_regression",
        provider=provider,
        model=model,
        model_alias=model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        model_params={"temperature": 0},
    )


def _case_payload(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = internal_agents.load_contract("answer_review", version_suffix="v3")
    prompt_template = internal_agents.prompt_path_for_contract(contract).read_text(encoding="utf-8")
    trusted_context = {
        "schema_version": "2026-07-23.answer-semantic-regression-context.v1",
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "question": case.get("question"),
        "answer_contract": {
            "criteria": case.get("criteria") or [],
            "authority": "criterion_semantic_judgment_only",
            "do_not_calculate_score": True,
        },
    }
    untrusted_payload = {
        "child_answer": case.get("child_answer", ""),
        "photo_ocr": case.get("photo_ocr") or {},
    }
    prompt = (
        prompt_template
        .replace("{trusted_context_json}", json.dumps(trusted_context, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{untrusted_payload_json}", json.dumps(untrusted_payload, ensure_ascii=False, indent=2, sort_keys=True))
    )
    payload = {
        "instructions": "You are answer_analysis_agent. Return only schema-valid JSON.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    meta = {
        "contract_version": contract.get("contract_version"),
        "response_schema_version": contract.get("response_schema_version"),
        "prompt_template_path": str(internal_agents.prompt_path_for_contract(contract)),
        "prompt_template_sha256": internal_agents.file_sha256(internal_agents.prompt_path_for_contract(contract)),
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    return payload, meta


def _child_facing_text(output: dict[str, Any]) -> str:
    fields: list[str] = [
        str(output.get("answer_gap") or ""),
        str(output.get("expression_judgment") or ""),
        str(output.get("teaching_explanation") or ""),
    ]
    fields.extend(str(value) for value in output.get("improvement_direction") or [])
    return "\n".join(fields)


def _child_facing_has_english(output: dict[str, Any]) -> bool:
    text = _child_facing_text(output)
    english_markers = ("Missing ", "Add ", "Briefly ", "The calculation", "Optional", "correct but", "wrong because")
    return any(marker in text for marker in english_markers)


def _evaluate_case_output(case: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    expected = {str(k): str(v) for k, v in (case.get("expected_statuses") or {}).items()}
    accepted_overrides = {
        str(key): {str(item) for item in value}
        for key, value in (case.get("acceptable_statuses") or {}).items()
        if isinstance(value, list)
    }
    accepted = {
        key: sorted(accepted_overrides.get(key, {value}))
        for key, value in expected.items()
    }
    actual = {
        str(item.get("criterion_key")): str(item.get("status"))
        for item in output.get("criteria") or []
        if isinstance(item, dict)
    }
    missing_keys = sorted(set(expected) - set(actual))
    mismatches = [
        {
            "criterion_key": key,
            "expected": expected[key],
            "accepted": accepted.get(key, [expected[key]]),
            "actual": actual.get(key, ""),
        }
        for key in sorted(expected)
        if actual.get(key) not in set(accepted.get(key, [expected[key]]))
    ]
    try:
        confidence = float(output.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence_floor = float(case.get("minimum_confidence") or 0.0)
    low_confidence = confidence < confidence_floor
    english_feedback = _child_facing_has_english(output)
    child_facing_text = _child_facing_text(output)
    forbidden_feedback_hits = [
        str(marker)
        for marker in case.get("forbidden_child_feedback_substrings") or []
        if str(marker) and str(marker) in child_facing_text
    ]
    issues = []
    for key in missing_keys:
        issues.append({"code": "missing_criterion", "detail": key})
    for mismatch in mismatches:
        issues.append({"code": "status_mismatch", **mismatch})
    if low_confidence:
        issues.append({"code": "confidence_below_case_floor", "expected_minimum": confidence_floor, "actual": confidence})
    if english_feedback:
        issues.append({"code": "child_facing_feedback_contains_english"})
    for marker in forbidden_feedback_hits:
        issues.append({"code": "child_facing_feedback_forbidden_substring", "detail": marker})
    return {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "node_id": case.get("node_id"),
        "status": "PASS" if not issues else "FAIL",
        "expected_statuses": expected,
        "accepted_statuses": accepted,
        "actual_statuses": actual,
        "confidence": confidence,
        "minimum_confidence": confidence_floor,
        "issues": issues,
    }


def run_answer_semantic_regression(
    *,
    root: Path,
    models: list[str],
    cases_path: Path = DEFAULT_ANSWER_CASES_PATH,
    base_url: str = DEFAULT_BASE_URL,
    api_key_env: str = "OPENAI_API_KEY",
    case_ids: list[str] | None = None,
    limit: int = 0,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    if not models:
        raise AdminProductionError("ADMIN_MODEL_REGRESSION_REQUIRES_MODELS")
    if timeout_seconds <= 0:
        raise AdminProductionError("ADMIN_MODEL_REGRESSION_TIMEOUT_MUST_BE_POSITIVE")
    cases_payload = _load_cases(root, cases_path)
    cases = list(cases_payload.get("cases") or [])
    if case_ids:
        requested_case_ids = [str(case_id).strip() for case_id in case_ids if str(case_id).strip()]
        case_by_id = {str(case.get("case_id")): case for case in cases}
        missing_case_ids = [case_id for case_id in requested_case_ids if case_id not in case_by_id]
        if missing_case_ids:
            raise AdminProductionError(
                "ADMIN_MODEL_REGRESSION_UNKNOWN_CASE_ID: " + ", ".join(missing_case_ids)
            )
        cases = [case_by_id[case_id] for case_id in requested_case_ids]
    if limit:
        if limit < 1:
            raise AdminProductionError("ADMIN_MODEL_REGRESSION_LIMIT_MUST_BE_POSITIVE")
        cases = cases[:limit]
    api_key = os.environ.get(api_key_env, "")
    prompt_meta_by_case: dict[str, Any] = {}
    model_reports = []
    started = time.monotonic()

    for model in models:
        route = _model_route(model=model, default_api_key=api_key, base_url=base_url, timeout_seconds=timeout_seconds)
        case_reports = []
        if not route.enabled:
            model_reports.append({
                "model": model,
                "provider": route.provider,
                "status": "BLOCKED_MODEL_NOT_CONFIGURED",
                "case_count": len(cases),
                "passed_count": 0,
                "failed_count": 0,
                "blocked_count": len(cases),
                "route": model_router.route_status(route).as_dict(),
                "cases": [
                    {
                        "case_id": case.get("case_id"),
                        "category": case.get("category"),
                        "status": "BLOCKED_MODEL_NOT_CONFIGURED",
                        "issues": [{"code": "missing_api_key_env", "detail": api_key_env}],
                    }
                    for case in cases
                ],
            })
            continue
        for case in cases:
            payload, prompt_meta = _case_payload(case)
            prompt_meta_by_case[str(case.get("case_id"))] = prompt_meta
            t0 = time.monotonic()
            try:
                contract = internal_agents.load_contract("answer_review", version_suffix="v3")
                result = model_router.call_structured_json(
                    route,
                    payload,
                    schema=contract.get("response_schema") or {},
                    retryable_errors_fallback=True,
                )
                evaluation = _evaluate_case_output(case, result.value)
                case_reports.append({
                    **evaluation,
                    "elapsed_seconds": round(time.monotonic() - t0, 3),
                    "endpoint": result.endpoint,
                    "structured_json_mode": result.mode,
                    "raw_response_sha256": hashlib.sha256(json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
                    "output": result.value,
                })
            except model_router.ModelCallError as exc:
                case_reports.append({
                    "case_id": case.get("case_id"),
                    "category": case.get("category"),
                    "node_id": case.get("node_id"),
                    "status": "BLOCKED_MODEL_ERROR",
                    "elapsed_seconds": round(time.monotonic() - t0, 3),
                    "endpoint": exc.endpoint,
                    "structured_json_mode": exc.structured_json_mode,
                    "error": {
                        "error_class": type(exc).__name__,
                        "message": str(exc)[:800],
                        "status_code": exc.status_code,
                        "retry_after_seconds": exc.retry_after_seconds,
                    },
                    "issues": [{"code": "model_call_error"}],
                })
        passed_count = sum(1 for item in case_reports if item.get("status") == "PASS")
        failed_count = sum(1 for item in case_reports if item.get("status") == "FAIL")
        blocked_count = sum(1 for item in case_reports if str(item.get("status") or "").startswith("BLOCKED"))
        model_reports.append({
            "model": model,
            "provider": route.provider,
            "status": "PASS" if passed_count == len(case_reports) else ("BLOCKED" if blocked_count == len(case_reports) else "FAIL"),
            "case_count": len(case_reports),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "blocked_count": blocked_count,
            "pass_rate": round(passed_count / len(case_reports), 4) if case_reports else 0,
            "route": model_router.route_status(route).as_dict(),
            "cases": case_reports,
        })

    overall_status = (
        "BLOCKED_MODEL_NOT_CONFIGURED"
        if all(report.get("status") == "BLOCKED_MODEL_NOT_CONFIGURED" for report in model_reports)
        else "PASS"
        if model_reports and all(report.get("status") == "PASS" for report in model_reports)
        else "FAIL"
    )
    run_id_input = json.dumps(
        {
            "models": models,
            "case_digest": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "schema_version": ANSWER_REGRESSION_SCHEMA_VERSION,
        "run_id": "MSR-" + hashlib.sha256(run_id_input.encode("utf-8")).hexdigest()[:12],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": overall_status,
        "scope": "answer_analysis_semantic_regression",
        "case_schema_version": cases_payload.get("schema_version"),
        "cases_path": _relative(root, cases_path if cases_path.is_absolute() else root / cases_path),
        "case_count": len(cases),
        "models": model_reports,
        "prompt_meta_by_case": prompt_meta_by_case,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "secret_policy": "api keys are read from environment and never written to reports",
        "activation_implication": "does_not_authorize_model_switch_or_child_runtime_activation",
    }


def render_answer_semantic_regression_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Model Semantic Regression",
        "",
        f"Status: `{report.get('status')}`",
        "",
        f"Run ID: `{report.get('run_id')}`",
        "",
        f"Case Count: {report.get('case_count')}",
        "",
        "## Models",
        "",
        "| Model | Provider | Status | Pass | Fail | Blocked | Pass Rate |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for model in report.get("models") or []:
        lines.append(
            f"| {model.get('model')} | {model.get('provider')} | `{model.get('status')}` | "
            f"{model.get('passed_count')} | {model.get('failed_count')} | {model.get('blocked_count')} | {model.get('pass_rate', 0)} |"
        )
    lines.extend(["", "## Failed Or Blocked Cases", ""])
    any_issue = False
    for model in report.get("models") or []:
        for case in model.get("cases") or []:
            if case.get("status") == "PASS":
                continue
            any_issue = True
            issue_codes = ", ".join(str(issue.get("code") or "") for issue in case.get("issues") or [])
            lines.append(f"- `{model.get('model')}` / `{case.get('case_id')}` / `{case.get('status')}`: {issue_codes}")
    if not any_issue:
        lines.append("- None")
    lines.extend([
        "",
        "Activation Implication: `does_not_authorize_model_switch_or_child_runtime_activation`",
    ])
    return "\n".join(lines) + "\n"


def write_answer_semantic_regression_report(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    run_id = str(report.get("run_id") or "MSR-unknown")
    markdown_rel = Path("docs/system/admin_reports/model_regression") / f"{datetime.now(timezone.utc).date()}-{run_id}.md"
    json_rel = Path("data/admin/model_regression") / f"{run_id}.json"
    result = {
        **report,
        "regression_markdown_path": str(markdown_rel),
        "regression_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_answer_semantic_regression_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["regression_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    result["regression_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result
