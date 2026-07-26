from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import child_prompt, internal_agents, model_router, question_bank, question_usage
from .expert_review import FAIL_SEVERITIES, SEVERITY_ORDER
from .inventory import canonical_structure_fingerprint_for_item
from .model_deadline import bind_admin_structured_model_deadline
from .production_loop import (
    AdminProductionError,
    _digest_json,
    _findings_by_severity,
    _load_json_file,
    _relative,
    _status_from_findings,
    resolve_design_brief,
    validate_candidate_against_brief,
)


QUESTION_CANDIDATE_ARTIFACT_SCHEMA_VERSION = "2026-07-23.codex-admin.generated-question-candidate.v1"
QUESTION_CANDIDATE_BATCH_SCHEMA_VERSION = "2026-07-23.question-candidate-batch.schema.v1"
QUESTION_CANDIDATE_BATCH_REPORT_SCHEMA_VERSION = "2026-07-23.codex-admin.generated-question-candidate-batch.v1"

_MAX_STANDARD_ANSWER_CHARS = 600
_MAX_EXPECTED_ANSWER_CHARS = 400
_MAX_ANSWER_FORMAT_CHARS = 120
_MAX_SOLUTION_STEPS = 5
_MAX_SOLUTION_STEP_CHARS = 240
_MAX_SOLUTION_TOTAL_CHARS = 800


def _minimum_written_response_lines(interaction: dict[str, Any] | None) -> int:
    if not interaction:
        return 0
    interaction_type = str(interaction.get("type") or "")
    explanation_lines = 1 if interaction.get("requires_explanation") else 0
    if interaction_type in {"single_choice", "multi_choice"}:
        return explanation_lines
    if interaction_type == "formula_input":
        return 1 + explanation_lines
    if interaction_type == "fill_blank":
        fields = interaction.get("fields") if isinstance(interaction.get("fields"), list) else []
        return (1 if fields else 0) + explanation_lines
    if interaction_type == "short_text":
        return 1
    return 0


def _load_production_plan(root: Path, path: Path) -> dict[str, Any]:
    plan = _load_json_file(root, path)
    if plan.get("schema_version") != "2026-07-23.codex-admin.production-plan.v1":
        raise AdminProductionError("ADMIN_PRODUCTION_UNSUPPORTED_GENERATION_PLAN_SCHEMA")
    return plan


def _slot_requirement(plan: dict[str, Any]) -> dict[str, Any]:
    packet = plan.get("bounded_candidate_packet")
    if not isinstance(packet, dict):
        raise AdminProductionError("ADMIN_PRODUCTION_PLAN_MISSING_BOUNDED_PACKET")
    requirement = packet.get("question_requirement")
    if not isinstance(requirement, dict) or not requirement.get("slot_id"):
        raise AdminProductionError("ADMIN_PRODUCTION_PLAN_REQUIRES_SLOT_REQUIREMENT")
    return dict(requirement)


def _blocking_codes(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict):
        return []
    codes: list[str] = []
    for code in report.get("blocking_rejection_codes") or []:
        if code:
            codes.append(str(code))
    for finding in report.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("severity") or "") in FAIL_SEVERITIES and finding.get("code"):
            codes.append(str(finding["code"]))
    return sorted(set(codes))


def _candidate_id(plan: dict[str, Any], requirement: dict[str, Any], generation_attempt: int) -> str:
    seed = "|".join(
        [
            str(plan.get("design_brief_id") or ""),
            str(requirement.get("question_requirement_id") or ""),
            str(requirement.get("slot_id") or ""),
            str(generation_attempt),
        ]
    )
    return "CAND-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _candidate_structure_fingerprint(item: dict[str, Any], plan: dict[str, Any], requirement: dict[str, Any]) -> str:
    explicit = str(
        ((item.get("quality") or {}) if isinstance(item.get("quality"), dict) else {}).get("structure_fingerprint")
        or item.get("math_core_signature")
        or ""
    ).strip()
    if explicit:
        return explicit
    seed = {
        "node_id": plan.get("node_id"),
        "family_id": plan.get("family_id"),
        "slot_id": requirement.get("slot_id"),
        "prompt": item.get("prompt"),
        "standard_answer": item.get("standard_answer") or item.get("expected_answer"),
    }
    return "AUTO-" + hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _child_surface_finding(
    severity: str,
    code: str,
    message: str,
    *,
    item: dict[str, Any],
) -> dict[str, str]:
    return {
        "severity": severity,
        "profile": "admin_generation_child_surface_gate",
        "item_id": str(item.get("id") or ""),
        "node_id": str(item.get("node_id") or ""),
        "code": code,
        "message": message,
    }


def _available_visual_resource_refs(plan: dict[str, Any]) -> set[str]:
    packet = plan.get("bounded_candidate_packet") if isinstance(plan.get("bounded_candidate_packet"), dict) else {}
    resources = packet.get("visual_resources") or []
    refs: set[str] = set()
    for resource in resources:
        if isinstance(resource, str) and resource.strip():
            refs.add(resource.strip())
            continue
        if not isinstance(resource, dict):
            continue
        for key in ("asset_ref", "id", "ref", "path"):
            value = str(resource.get(key) or "").strip()
            if value:
                refs.add(value)
    return refs


def _child_surface_findings(
    item: dict[str, Any],
    *,
    model_output: dict[str, Any],
    plan: dict[str, Any],
    requirement: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    prompt = str(item.get("prompt") or "")
    answer_format = str(item.get("answer_format") or "")
    if "\\n" in prompt:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_prompt_contains_literal_newline_escape",
                "孩子题面包含字面量 \\n；必须使用 JSON 的真实换行编码，不能把反斜杠和字母 n 显示给孩子。",
                item=item,
            )
        )

    interaction_schema = item.get("interaction_schema")
    normalized_interaction: dict[str, Any] | None = None
    if not isinstance(interaction_schema, dict):
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_interaction_schema",
                "候选题必须声明孩子端实际使用的 interaction_schema。",
                item=item,
            )
        )
    else:
        try:
            normalized_interaction = child_prompt.normalize_interaction_schema(
                interaction_schema,
                allow_legacy=False,
            )
        except child_prompt.ChildPromptContractError as exc:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_invalid_interaction_schema",
                    "interaction_schema 与当前孩子端支持合同不一致：" + ", ".join(exc.errors[:4]),
                    item=item,
                )
            )
    if normalized_interaction is not None:
        try:
            question_bank.canonical_child_surface_projection(item)
        except child_prompt.ChildPromptContractError as exc:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_projection_failed",
                    "候选题无法通过正式孩子端投影：" + ", ".join(exc.errors[:4]),
                    item=item,
                )
            )

    if len(answer_format) > _MAX_ANSWER_FORMAT_CHARS:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_answer_format_too_long",
                "answer_format 过长，已经从简短作答提示膨胀为第二份题面。",
                item=item,
            )
        )

    design = model_output.get("child_surface_design")
    if not isinstance(design, dict):
        design = item.get("child_surface_design")
    language_surface = design.get("language_surface") if isinstance(design, dict) and isinstance(design.get("language_surface"), dict) else {}
    explanation_requested = int(language_surface.get("short_explanation_requests") or 0) > 0
    if normalized_interaction is not None:
        if explanation_requested and normalized_interaction.get("allow_explanation") is False:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_answer_format_requires_missing_explanation_control",
                    "题面或 answer_format 要求解释，但 interaction_schema 没有开放解释输入。",
                    item=item,
                )
            )
        if normalized_interaction.get("requires_explanation") and not explanation_requested:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_interaction_requires_unrequested_explanation",
                    "interaction_schema 强制填写解释，但题面和 answer_format 没有提出这一要求。",
                    item=item,
                )
            )

    solution_steps = item.get("solution_steps") if isinstance(item.get("solution_steps"), list) else []
    if len(solution_steps) > _MAX_SOLUTION_STEPS or (
        int(item.get("estimated_minutes") or 0) <= 4 and len(solution_steps) > 4
    ):
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_solution_steps_too_many",
                "解析步骤超过孩子端简洁题所需上限；请合并同一数学动作，不要用展开书写制造复杂度。",
                item=item,
            )
        )
    if any(len(str(step)) > _MAX_SOLUTION_STEP_CHARS for step in solution_steps) or sum(
        len(str(step)) for step in solution_steps
    ) > _MAX_SOLUTION_TOTAL_CHARS:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_solution_steps_too_verbose",
                "单步或整份 solution_steps 过长，解析需要保留关键数学链路并删去套话。",
                item=item,
            )
        )
    if len(str(item.get("standard_answer") or "")) > _MAX_STANDARD_ANSWER_CHARS:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_standard_answer_too_long",
                "standard_answer 过长，不适合作为简洁解析的主体。",
                item=item,
            )
        )
    if len(str(item.get("expected_answer") or "")) > _MAX_EXPECTED_ANSWER_CHARS:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_expected_answer_too_long",
                "expected_answer 过长，应保留可核对的结论和必要条件。",
                item=item,
            )
        )

    if not isinstance(design, dict):
        findings.append(
            _child_surface_finding(
                "P1",
                "missing_child_surface_design",
                "候选题缺少孩子端表面设计证据，不能进入专家评审。",
                item=item,
            )
        )
        return findings

    child_deliverables = design.get("child_deliverables")
    if not isinstance(child_deliverables, list) or not child_deliverables:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_deliverables",
                "候选题必须明确孩子需要提交什么，且不能把后台证据目标直接写进题面。",
                item=item,
            )
        )
    elif len(child_deliverables) > 2:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_too_many_deliverables",
                "同一道题最多要求两个紧密相关的孩子端产出，避免用书写负担制造伪难度。",
                item=item,
            )
        )

    backend_targets = design.get("backend_evidence_targets")
    if not isinstance(backend_targets, list) or not backend_targets:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_backend_evidence_targets",
                "孩子端动作必须能映射到明确的后台证据目标。",
                item=item,
            )
        )

    writing_burden = design.get("writing_burden") if isinstance(design.get("writing_burden"), dict) else {}
    if not writing_burden or not str(writing_burden.get("why_necessary") or "").strip():
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_writing_burden_unjustified",
                "题目必须说明必要书写量为何服务于诊断，不能默认要求完整套话。",
                item=item,
            )
        )
    else:
        estimated_lines = int(writing_burden.get("estimated_response_lines") or 0)
        burden_level = str(writing_burden.get("burden_level") or "")
        minimum_written_lines = _minimum_written_response_lines(normalized_interaction)
        if estimated_lines < minimum_written_lines:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_writing_burden_understates_control",
                    "预计作答行数少于当前控件真正需要书写的输入区域。",
                    item=item,
                )
            )
        if (burden_level == "light" and estimated_lines > 3) or (
            burden_level == "moderate" and estimated_lines > 6
        ):
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_writing_burden_level_mismatch",
                    "writing_burden 的等级与预计行数不一致；light 最多 3 行，moderate 最多 6 行。",
                    item=item,
                )
            )

    if design.get("task_focus_count") != 1:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_multiple_primary_tasks",
                "候选题必须只有一个主要任务；辅助动作只能服务于同一诊断断点。",
                item=item,
            )
        )

    actions = design.get("student_actions") if isinstance(design.get("student_actions"), dict) else {}
    action_set = {
        str(actions.get("primary") or ""),
        *[str(value) for value in actions.get("supporting") or []],
    }
    fixed_bundle = {"explain_core_relation", "verify", "diagnose_error"}
    if fixed_bundle.issubset(action_set):
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_fixed_explain_verify_error_bundle",
                "同一道题同时强制解释、检验和错因诊断，会用固定作答套件制造伪难度。",
                item=item,
            )
        )

    interaction_requirements = (
        design.get("interaction_requirements")
        if isinstance(design.get("interaction_requirements"), dict)
        else {}
    )
    if not interaction_requirements:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_interaction_requirements",
                "候选题必须用结构化 interaction_requirements 声明真实作答动作，不能依赖题面关键词推断。",
                item=item,
            )
        )
    response_kind = str(interaction_requirements.get("response_kind") or "").strip()
    required_actions = interaction_requirements.get("actions")
    if not isinstance(required_actions, list):
        required_actions = []
    supported_response_types = {
        "short_text": "short_text",
        "fill_blank": "fill_blank",
        "select_one": "single_choice",
        "select_many": "multi_choice",
        "formula": "formula_input",
        "formula_input": "formula_input",
    }
    if response_kind == "direct_manipulation":
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_unrenderable_interaction_requirement",
                "题目声明需要直接拖动、绘制或操作，但当前孩子端没有可执行的对应控件。",
                item=item,
            )
        )
    elif required_actions:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_unrenderable_interaction_requirement",
                "普通输入控件不能携带 move、draw、connect 或 click_location 等直接操作动作。",
                item=item,
            )
        )
    elif response_kind and normalized_interaction is not None:
        expected_type = supported_response_types.get(response_kind)
        if expected_type is None or normalized_interaction.get("type") != expected_type:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_interaction_action_mismatch",
                    "结构化作答要求与孩子端实际 interaction_schema 不一致。",
                    item=item,
                )
            )

    if normalized_interaction is not None:
        minimum_selections = interaction_requirements.get("minimum_selections")
        maximum_selections = interaction_requirements.get("maximum_selections")
        choice_count = len(normalized_interaction.get("choices") or [])
        selection_contract_valid = True
        if response_kind == "select_one":
            selection_contract_valid = minimum_selections == 1 and maximum_selections == 1
        elif response_kind == "select_many":
            selection_contract_valid = (
                isinstance(minimum_selections, int)
                and isinstance(maximum_selections, int)
                and 1 <= minimum_selections <= maximum_selections <= choice_count
            )
        elif minimum_selections not in (None, 0) or maximum_selections not in (None, 0):
            selection_contract_valid = False
        if not selection_contract_valid:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_selection_contract_invalid",
                    "结构化选择数量约束与单选、多选控件或实际选项数量不一致。",
                    item=item,
                )
            )

    visual = design.get("visual_support") if isinstance(design.get("visual_support"), dict) else {}
    visual_mode = str(visual.get("mode") or "")
    depends_on_visual = visual.get("prompt_depends_on_visual") is True
    asset_ref = str(visual.get("asset_ref") or "").strip()
    inline_visual = str(visual.get("inline_visual") or "").strip()
    if depends_on_visual and visual_mode == "not_needed":
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_visual_dependency_without_delivery",
                "题目声明依赖视觉信息，但没有内嵌图形或可信视觉资源。",
                item=item,
            )
        )
    if visual_mode == "inline_in_prompt":
        if not inline_visual or inline_visual not in prompt:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_inline_visual_missing_from_prompt",
                    "visual_support 声明内嵌视觉，但声明的 inline_visual 没有完整出现在 prompt 中。",
                    item=item,
                )
            )
    elif inline_visual:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_unexpected_inline_visual",
                "只有 inline_in_prompt 模式可以填写 inline_visual。",
                item=item,
            )
        )
    if visual_mode == "external_asset":
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_external_visual_pipeline_not_ready",
                "外部视觉资源尚未建立从 generation plan 到 question_visual 的可信绑定，当前必须使用内嵌视觉或无视觉题面。",
                item=item,
            )
        )
    elif asset_ref:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_unexpected_visual_asset_ref",
                "只有 external_asset 模式可以填写 asset_ref；不能编造或悬空引用视觉资源。",
                item=item,
            )
        )

    language = design.get("language_surface") if isinstance(design.get("language_surface"), dict) else {}
    if language.get("semantic_review_boundary") != "requires_independent_semantic_qa":
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_independent_semantic_review_boundary",
                "自然中文和年龄尊重必须保留给独立 semantic QA；生成者自报布尔不能独立构成通过结论。",
                item=item,
            )
        )
    if language.get("natural_child_facing_chinese") is not True:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_natural_chinese_not_attested",
                "生成者没有提交自然、孩子可读中文的结构化自检；即使为 true 仍需独立 semantic QA。",
                item=item,
            )
        )
    if language.get("respectful_age_appropriate") is not True:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_not_respectful_age_appropriate",
                "生成者没有提交尊重六升七孩子的结构化自检；即使为 true 仍需独立 semantic QA。",
                item=item,
            )
        )
    if len(language.get("named_characters") or []) > 1:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_too_many_named_characters",
                "孩子题面最多使用一个有必要的命名角色，避免反复套用人物对话模板。",
                item=item,
            )
        )
    declared_explanation_requests = int(language.get("short_explanation_requests") or 0)
    if declared_explanation_requests > 1:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_repeated_short_explanation_requests",
                "同一道题最多要求一次简短解释，不能重复套用“一句话说明”。",
                item=item,
            )
        )
    if explanation_requested and declared_explanation_requests == 0:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_explanation_request_not_declared",
                "题面或 answer_format 明确要求解释，但 language_surface 没有如实记录。",
                item=item,
            )
        )
    if not explanation_requested and declared_explanation_requests > 0:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_declared_explanation_request_missing",
                "language_surface 声明题面要求解释，但 prompt 和 answer_format 中没有这一要求。",
                item=item,
            )
        )

    distractor_design = design.get("distractor_design") if isinstance(design.get("distractor_design"), dict) else {}
    for distractor in distractor_design.get("distractors") or []:
        if not isinstance(distractor, dict):
            continue
        relevance = str(distractor.get("relevance") or "")
        why_plausible = str(distractor.get("why_plausible") or "").strip()
        if relevance not in {"required_information", "plausibly_relevant_but_unneeded"} or not why_plausible:
            findings.append(
                _child_surface_finding(
                    "P1",
                    "child_surface_distractor_without_plausible_relevance",
                    "干扰条件必须真实地看似相关，并提交其相关性依据；显然无关的信息不能充当难度。",
                    item=item,
                )
            )
            break

    difficulty = design.get("difficulty_alignment") if isinstance(design.get("difficulty_alignment"), dict) else {}
    target_difficulty = str(difficulty.get("target_difficulty") or "")
    required_difficulty = str(requirement.get("difficulty") or "")
    if target_difficulty != required_difficulty:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_difficulty_mismatch",
                "孩子端设计证据中的难度与 requirement slot 不一致。",
                item=item,
            )
        )
    allowed_difficulty_sources = {
        "mathematical_structure",
        "representation_transfer",
        "error_discrimination",
        "multi_step_dependency",
        "strategy_choice",
    }
    if str(difficulty.get("difficulty_source") or "") not in allowed_difficulty_sources:
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_pseudo_difficulty_source",
                "难度必须来自数学认知要求，不能来自阅读量、机械重复或形式化书写。",
                item=item,
            )
        )
    if not str(difficulty.get("diagnostic_breakpoint") or "").strip():
        findings.append(
            _child_surface_finding(
                "P1",
                "child_surface_missing_diagnostic_breakpoint",
                "候选题必须说明它要暴露的具体认知断点。",
                item=item,
            )
        )
    return findings


def _merge_machine_findings(
    machine_report: dict[str, Any],
    extra_findings: list[dict[str, str]],
) -> dict[str, Any]:
    if not extra_findings:
        return machine_report
    findings = [*list(machine_report.get("findings") or []), *extra_findings]
    status = _status_from_findings(findings)
    return {
        **machine_report,
        "status": status,
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(
            findings,
            key=lambda finding: (
                SEVERITY_ORDER.get(finding.get("severity", ""), 9),
                finding.get("profile", ""),
                finding.get("code", ""),
            ),
        ),
        "next_actions": ["expert_review"] if status in {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"} else ["regenerate_candidate"],
    }


def _normalize_model_item(
    output: dict[str, Any],
    *,
    plan: dict[str, Any],
    requirement: dict[str, Any],
    generation_attempt: int,
    previous_rejection_codes: list[str],
) -> dict[str, Any]:
    raw_item = output.get("item") if isinstance(output.get("item"), dict) else output
    item = json.loads(json.dumps(raw_item, ensure_ascii=False))
    item_id = _candidate_id(plan, requirement, generation_attempt)
    item["id"] = item_id
    item["item_version"] = f"draft.admin-production.v1.attempt-{generation_attempt}"
    item["prompt_format"] = child_prompt.CHILD_PROMPT_FORMAT
    item["node_id"] = str(plan.get("node_id") or requirement.get("node_id") or "")
    item["question_type"] = str(plan.get("family_id") or requirement.get("family_id") or "")
    item["difficulty"] = str(requirement.get("difficulty") or item.get("difficulty") or "")
    item["evidence_goal"] = str(requirement.get("evidence_goal") or item.get("evidence_goal") or "")
    item["support_only"] = bool(requirement.get("support_only"))
    item["not_for_activation"] = bool(requirement.get("not_for_activation"))
    item["exclude_from_coverage"] = bool(requirement.get("exclude_from_coverage"))
    item["secondary_node_ids"] = list(requirement.get("secondary_nodes") or [])
    item["source_type"] = "ai_original"
    item["source"] = {
        "type": "ai_original",
        "usage_mode": "draft_original_generation",
        "basis": "generated_from_expert_requirement_slot",
    }
    lineage = dict(item.get("production_lineage") if isinstance(item.get("production_lineage"), dict) else {})
    lineage.update(
        {
            "design_brief_id": str(plan.get("design_brief_id") or ""),
            "question_requirement_id": str(requirement.get("question_requirement_id") or ""),
            "slot_id": str(requirement.get("slot_id") or ""),
            "family_id": str(requirement.get("family_id") or plan.get("family_id") or ""),
            "evidence_goal": str(requirement.get("evidence_goal") or ""),
            "generation_attempt": int(generation_attempt),
            "previous_rejection_codes": list(previous_rejection_codes),
        }
    )
    if not lineage.get("generation_rationale"):
        lineage["generation_rationale"] = str(item.get("design_rationale") or "Generated from the expert requirement slot.")
    item["production_lineage"] = lineage
    child_surface_design = output.get("child_surface_design")
    if isinstance(child_surface_design, dict):
        item["child_surface_design"] = json.loads(json.dumps(child_surface_design, ensure_ascii=False))
    required_evidence = [str(value) for value in item.get("required_evidence") or [] if str(value).strip()]
    canonical_evidence = [
        str(requirement.get("evidence_goal") or ""),
        *[str(value) for value in requirement.get("must_include") or []],
    ]
    item["required_evidence"] = list(dict.fromkeys([*required_evidence, *[value for value in canonical_evidence if value.strip()]]))
    quality = dict(item.get("quality") if isinstance(item.get("quality"), dict) else {})
    quality["review_status"] = str(quality.get("review_status") or "draft_generated")
    model_fingerprint = _candidate_structure_fingerprint(item, plan, requirement)
    quality["model_structure_fingerprint"] = str(quality.get("model_structure_fingerprint") or model_fingerprint)
    quality["canonical_structure_fingerprint"] = canonical_structure_fingerprint_for_item({**item, "quality": quality})
    quality["structure_fingerprint"] = str(quality.get("structure_fingerprint") or quality["canonical_structure_fingerprint"])
    item["quality"] = quality
    item["math_core_signature"] = str(item.get("math_core_signature") or quality["canonical_structure_fingerprint"])
    usage_policy = question_usage.policy_for_item(item)
    explicit_usage_policy = requirement.get("usage_policy")
    if isinstance(explicit_usage_policy, dict) and explicit_usage_policy:
        usage_policy.update(explicit_usage_policy)
    usage_policy.update(
        {
            "schema_version": question_usage.USAGE_POLICY_VERSION,
            "primary_node_id": item["node_id"],
            "secondary_node_ids": list(item.get("secondary_node_ids") or []),
            "structure_fingerprint": quality["canonical_structure_fingerprint"],
        }
    )
    question_usage.validate_policy(usage_policy)
    item["usage_policy"] = usage_policy
    return item


def _prompt_payload(
    *,
    root: Path,
    plan: dict[str, Any],
    requirement: dict[str, Any],
    generation_attempt: int,
    previous_rejection: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = internal_agents.load_contract("question_candidate", version_suffix="v1")
    prompt_template = internal_agents.prompt_path_for_contract(contract).read_text(encoding="utf-8")
    required_item_id = _candidate_id(plan, requirement, generation_attempt)
    trusted_context = {
        "schema_version": "2026-07-23.codex-admin.question-generation-context.v1",
        "required_item_id": required_item_id,
        "required_item_version": f"draft.admin-production.v1.attempt-{generation_attempt}",
        "generation_attempt": generation_attempt,
        "design_brief_id": plan.get("design_brief_id"),
        "node_id": plan.get("node_id"),
        "node_name": plan.get("node_name"),
        "family_id": plan.get("family_id"),
        "family_name": plan.get("family_name"),
        "question_requirement": requirement,
        "bounded_candidate_packet": _compact_bounded_candidate_packet(plan.get("bounded_candidate_packet") or {}),
        "production_defaults": {
            "source_type": "ai_original",
            "source": {
                "type": "ai_original",
                "usage_mode": "draft_original_generation",
                "basis": "generated_from_expert_requirement_slot",
            },
            "quality_review_status": "draft_generated",
        },
        "candidate_contract": {
            "answer_score_total": 10,
            "must_return_top_level_schema_version": "2026-07-23.question-candidate.schema.v1",
            "must_copy_requirement_ids_exactly": True,
            "candidate_id_is_program_assigned": True,
            "interaction_schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
            "supported_interaction_types": sorted(child_prompt.INTERACTION_TYPES),
            "unsupported_direct_manipulation_must_fail_closed": True,
            "independent_semantic_qa_required": True,
        },
    }
    untrusted_payload = {
        "previous_rejection": previous_rejection or {},
        "previous_rejection_codes": _blocking_codes(previous_rejection),
    }
    prompt = (
        prompt_template
        .replace("{trusted_context_json}", json.dumps(trusted_context, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{untrusted_payload_json}", json.dumps(untrusted_payload, ensure_ascii=False, indent=2, sort_keys=True))
    )
    payload = {
        "instructions": "You are question_designer_agent. Return only schema-valid JSON for one candidate question.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    meta = {
        "prompt_template_path": _relative(root, internal_agents.prompt_path_for_contract(contract)),
        "prompt_template_sha256": internal_agents.file_sha256(internal_agents.prompt_path_for_contract(contract)),
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_schema_version": str(contract.get("response_schema_version") or ""),
        "response_schema_sha256": internal_agents.canonical_json_sha256(contract.get("response_schema") or {}),
        "contract_version": str(contract.get("contract_version") or ""),
    }
    return payload, meta


def _batch_response_schema() -> dict[str, Any]:
    single_contract = internal_agents.load_contract("question_candidate", version_suffix="v1")
    batch_contract = internal_agents.load_contract("question_candidate_batch", version_suffix="v1")
    single_schema = single_contract.get("response_schema") or {}
    item_schema = (((single_schema.get("properties") or {}).get("item") or {}) if isinstance(single_schema, dict) else {})
    child_surface_design_schema = batch_contract.get("child_surface_design_schema")
    if not isinstance(child_surface_design_schema, dict):
        raise AdminProductionError("ADMIN_PRODUCTION_BATCH_CONTRACT_MISSING_CHILD_SURFACE_DESIGN_SCHEMA")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "confidence", "candidates"],
        "properties": {
            "schema_version": {"const": QUESTION_CANDIDATE_BATCH_SCHEMA_VERSION},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_index", "confidence", "item", "child_surface_design"],
                    "properties": {
                        "plan_index": {"type": "integer", "minimum": 0, "maximum": 4},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "item": item_schema,
                        "child_surface_design": child_surface_design_schema,
                    },
                },
            },
        },
    }


def _compact_expert_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    return {
        key: suggestion.get(key)
        for key in (
            "profile",
            "core_scenario",
            "design_idea",
            "evidence_goal",
            "variation_logic",
            "reject_patterns",
            "why",
        )
        if suggestion.get(key)
    }


def _compact_bounded_candidate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(packet, dict):
        return {}
    return {
        "node_capability": packet.get("node_capability"),
        "scope_in": packet.get("scope_in") or [],
        "scope_out": packet.get("scope_out") or [],
        "family_plan_entry": packet.get("family_plan_entry") or {},
        "expert_suggestions": [
            _compact_expert_suggestion(suggestion)
            for suggestion in (packet.get("expert_suggestions") or [])[:3]
            if isinstance(suggestion, dict)
        ],
        "existing_structure_fingerprints": list(packet.get("existing_structure_fingerprints") or [])[:12],
        "visual_resources": list(packet.get("visual_resources") or [])[:8],
        "review_must_reject": packet.get("review_must_reject") or [],
        "generation_policy": packet.get("generation_policy") or {},
    }


def _batch_prompt_payload(
    *,
    root: Path,
    plans: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    generation_attempt: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = internal_agents.load_contract("question_candidate_batch", version_suffix="v1")
    prompt_template = internal_agents.prompt_path_for_contract(contract).read_text(encoding="utf-8")
    batch_plans = []
    for index, (plan, requirement) in enumerate(zip(plans, requirements)):
        batch_plans.append({
            "plan_index": index,
            "required_item_id": _candidate_id(plan, requirement, generation_attempt),
            "required_item_version": f"draft.admin-production.v1.attempt-{generation_attempt}",
            "generation_attempt": generation_attempt,
            "design_brief_id": plan.get("design_brief_id"),
            "node_id": plan.get("node_id"),
            "node_name": plan.get("node_name"),
            "family_id": plan.get("family_id"),
            "family_name": plan.get("family_name"),
            "question_requirement": requirement,
            "bounded_candidate_packet": _compact_bounded_candidate_packet(plan.get("bounded_candidate_packet") or {}),
            "candidate_contract": {
                "answer_score_total": 10,
                "must_return_top_level_schema_version": QUESTION_CANDIDATE_BATCH_SCHEMA_VERSION,
                "must_copy_requirement_ids_exactly": True,
                "candidate_id_is_program_assigned": True,
                "child_surface_design_required": True,
                "single_primary_task_required": True,
                "maximum_supporting_actions": 2,
                "maximum_named_characters": 1,
                "maximum_short_explanation_requests": 1,
                "maximum_solution_steps": _MAX_SOLUTION_STEPS,
                "interaction_schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
                "supported_interaction_types": sorted(child_prompt.INTERACTION_TYPES),
                "unsupported_direct_manipulation_must_fail_closed": True,
                "independent_semantic_qa_required": True,
            },
        })
    trusted_context = {
        "schema_version": "2026-07-23.codex-admin.question-batch-generation-context.v1",
        "batch_size": len(batch_plans),
        "batch_plans": batch_plans,
        "production_defaults": {
            "source_type": "ai_original",
            "source": {
                "type": "ai_original",
                "usage_mode": "draft_original_generation",
                "basis": "generated_from_expert_requirement_slot",
            },
            "quality_review_status": "draft_generated",
        },
    }
    untrusted_payload = {"previous_rejections": []}
    prompt = (
        prompt_template
        .replace("{trusted_context_json}", json.dumps(trusted_context, ensure_ascii=False, indent=2, sort_keys=True))
        .replace("{untrusted_payload_json}", json.dumps(untrusted_payload, ensure_ascii=False, indent=2, sort_keys=True))
    )
    payload = {
        "instructions": "You are question_designer_agent. Return schema-valid JSON for a small batch of candidate questions.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0,
    }
    schema = _batch_response_schema()
    meta = {
        "prompt_template_path": _relative(root, internal_agents.prompt_path_for_contract(contract)),
        "prompt_template_sha256": internal_agents.file_sha256(internal_agents.prompt_path_for_contract(contract)),
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_schema_version": str(contract.get("response_schema_version") or ""),
        "response_schema_sha256": internal_agents.canonical_json_sha256(schema),
        "contract_version": str(contract.get("contract_version") or ""),
        "batch_size": len(batch_plans),
    }
    return payload, meta


def _base_candidate_report(
    *,
    root: Path,
    plan: dict[str, Any],
    requirement: dict[str, Any],
    generation_plan_path: Path,
    design_brief_path: Path,
    route: model_router.ModelRoute,
    prompt_meta: dict[str, Any],
    generation_attempt: int,
    subject: str,
) -> dict[str, Any]:
    return {
        "schema_version": QUESTION_CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "subject": subject,
        "status": "BLOCKED_MODEL_NOT_CONFIGURED",
        "provider_mode": "not_configured",
        "retryable": False,
        "generation_plan_path": _relative(root, generation_plan_path if generation_plan_path.is_absolute() else root / generation_plan_path),
        "design_brief_id": plan.get("design_brief_id"),
        "design_brief_path": _relative(root, design_brief_path),
        "node_id": plan.get("node_id"),
        "family_id": plan.get("family_id"),
        "slot_id": requirement.get("slot_id"),
        "question_requirement_id": requirement.get("question_requirement_id"),
        "generation_attempt": generation_attempt,
        "previous_rejection_codes": [],
        "candidate_authority": "candidate_only",
        "staging_allowed": False,
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
        "route": model_router.route_status(route).as_dict(),
        "prompt_meta": prompt_meta,
        "candidate": {},
        "machine_report": {},
        "finding_counts": {},
        "findings": [],
        "next_actions": ["configure_question_designer_model"],
    }


def build_generated_candidate_from_plan(
    *,
    root: Path,
    generation_plan_path: Path,
    previous_rejection_path: Path | None = None,
    generation_attempt: int = 1,
    subject: str = "math",
) -> dict[str, Any]:
    plan = _load_production_plan(root, generation_plan_path)
    requirement = _slot_requirement(plan)
    if plan.get("status") != "GENERATION_PACKET_READY":
        raise AdminProductionError("ADMIN_PRODUCTION_PLAN_NOT_READY")
    if generation_attempt < 1 or generation_attempt > int(requirement.get("max_attempts") or 5):
        raise AdminProductionError("ADMIN_PRODUCTION_INVALID_GENERATION_ATTEMPT")
    previous_rejection = _load_json_file(root, previous_rejection_path) if previous_rejection_path else None
    previous_codes = _blocking_codes(previous_rejection)
    design_brief, resolved_brief_path = resolve_design_brief(root, design_brief_path=Path(str(plan.get("design_brief_path") or "")))
    route = model_router.question_designer_route()
    payload, prompt_meta = _prompt_payload(
        root=root,
        plan=plan,
        requirement=requirement,
        generation_attempt=generation_attempt,
        previous_rejection=previous_rejection,
    )
    base_report = _base_candidate_report(
        root=root,
        plan=plan,
        requirement=requirement,
        generation_plan_path=generation_plan_path,
        design_brief_path=resolved_brief_path,
        route=route,
        prompt_meta=prompt_meta,
        generation_attempt=generation_attempt,
        subject=subject,
    )
    base_report["previous_rejection_codes"] = previous_codes
    if not route.enabled:
        return base_report

    contract = internal_agents.load_contract("question_candidate", version_suffix="v1")
    transport_meta: dict[str, Any] = {}
    try:
        started = datetime.now(timezone.utc)
        with bind_admin_structured_model_deadline(
            batch_attempt_id=f"question_candidate:{generation_plan_path}:{generation_attempt}",
            timeout_envs=(
                "AI_ADMIN_QUESTION_GENERATION_WALL_SECONDS",
                "AI_QUESTION_WALL_SECONDS",
                "AI_QUESTION_TIMEOUT_SECONDS",
            ),
            default_seconds=150.0,
        ) as transport_meta:
            result = model_router.call_structured_json(
                route,
                payload,
                schema=contract.get("response_schema") or {},
                plain_json_instruction="Return only one valid JSON object matching the field contract in the prompt; no markdown.",
                retryable_errors_fallback=True,
                include_fallback_schema=False,
            )
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    except model_router.ModelCallError as exc:
        return {
            **base_report,
            "status": "BLOCKED_MODEL_ERROR",
            "provider_mode": "live_model",
            "retryable": model_router.is_retryable_model_call_error(exc),
            "model_error": {
                "error_class": type(exc).__name__,
                "message": str(exc)[:800],
                "status_code": exc.status_code,
                "retry_after_seconds": exc.retry_after_seconds,
                "endpoint": exc.endpoint,
                "structured_json_mode": exc.structured_json_mode,
            },
            "transport_meta": transport_meta,
            "next_actions": ["retry_or_repair_model_route"],
        }

    item = _normalize_model_item(
        result.value,
        plan=plan,
        requirement=requirement,
        generation_attempt=generation_attempt,
        previous_rejection_codes=previous_codes,
    )
    machine_report = validate_candidate_against_brief(
        root=root,
        candidate={"item": item},
        design_brief=design_brief,
        design_brief_path=resolved_brief_path,
        subject=subject,
        required_family_id=str(plan.get("family_id") or ""),
        required_slot=requirement,
        previous_rejection=previous_rejection,
    )
    machine_report = _merge_machine_findings(
        machine_report,
        _child_surface_findings(
            item,
            model_output=result.value,
            plan=plan,
            requirement=requirement,
        ),
    )
    passed = machine_report.get("status") in {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"}
    status = "CANDIDATE_READY_FOR_EXPERT_REVIEW" if passed else "NEEDS_REGENERATION"
    findings = list(machine_report.get("findings") or [])
    return {
        **base_report,
        "status": status,
        "provider_mode": "live_model",
        "retryable": False,
        "route": {
            **model_router.route_status(route).as_dict(),
            "structured_json_mode": result.mode,
            "structured_json_endpoint": result.endpoint,
            "model_elapsed_ms": elapsed_ms,
            **transport_meta,
            "raw_response_sha256": hashlib.sha256(
                json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "candidate": {
            "schema_version": "2026-07-23.codex-admin.question-candidate-artifact.v1",
            "item": item,
            "model_output_sha256": _digest_json(result.value),
            "candidate_sha256": _digest_json(item),
        },
        "item_id": item.get("id"),
        "candidate_sha256": _digest_json(item),
        "machine_report": machine_report,
        "finding_counts": _findings_by_severity(findings),
        "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("profile", ""), f.get("code", ""))),
        "next_actions": ["expert_review"] if passed else ["loop_decision"],
    }


def build_generated_candidate_batch_from_plans(
    *,
    root: Path,
    generation_plan_paths: list[Path],
    generation_attempt: int = 1,
    subject: str = "math",
) -> dict[str, Any]:
    if not generation_plan_paths:
        raise AdminProductionError("ADMIN_PRODUCTION_BATCH_REQUIRES_GENERATION_PLANS")
    if len(generation_plan_paths) > 5:
        raise AdminProductionError("ADMIN_PRODUCTION_GENERATION_BATCH_MAX_5")
    if generation_attempt != 1:
        raise AdminProductionError("ADMIN_PRODUCTION_BATCH_GENERATION_ONLY_SUPPORTS_FIRST_ATTEMPT")

    plans: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    design_briefs: list[dict[str, Any]] = []
    design_brief_paths: list[Path] = []
    for path in generation_plan_paths:
        plan = _load_production_plan(root, path)
        requirement = _slot_requirement(plan)
        if plan.get("status") != "GENERATION_PACKET_READY":
            raise AdminProductionError("ADMIN_PRODUCTION_PLAN_NOT_READY")
        design_brief, resolved_brief_path = resolve_design_brief(root, design_brief_path=Path(str(plan.get("design_brief_path") or "")))
        plans.append(plan)
        requirements.append(requirement)
        design_briefs.append(design_brief)
        design_brief_paths.append(resolved_brief_path)

    route = model_router.question_designer_route()
    payload, prompt_meta = _batch_prompt_payload(root=root, plans=plans, requirements=requirements, generation_attempt=generation_attempt)
    candidate_reports = [
        _base_candidate_report(
            root=root,
            plan=plan,
            requirement=requirement,
            generation_plan_path=path,
            design_brief_path=brief_path,
            route=route,
            prompt_meta=prompt_meta,
            generation_attempt=generation_attempt,
            subject=subject,
        )
        for plan, requirement, path, brief_path in zip(plans, requirements, generation_plan_paths, design_brief_paths)
    ]
    base_report = {
        "schema_version": QUESTION_CANDIDATE_BATCH_REPORT_SCHEMA_VERSION,
        "subject": subject,
        "status": "BLOCKED_MODEL_NOT_CONFIGURED",
        "provider_mode": "not_configured",
        "retryable": False,
        "batch_size": len(generation_plan_paths),
        "generation_plan_paths": [
            _relative(root, path if path.is_absolute() else root / path)
            for path in generation_plan_paths
        ],
        "generation_attempt": generation_attempt,
        "candidate_reports": candidate_reports,
        "route": model_router.route_status(route).as_dict(),
        "prompt_meta": prompt_meta,
        "finding_counts": {},
        "findings": [],
        "next_actions": ["configure_question_designer_model"],
        "activation_allowed": False,
        "activation_implication": "does_not_authorize_activation",
    }
    if not route.enabled:
        return base_report

    schema = _batch_response_schema()
    transport_meta: dict[str, Any] = {}
    try:
        started = datetime.now(timezone.utc)
        with bind_admin_structured_model_deadline(
            batch_attempt_id="question_candidate_batch:" + "|".join(str(path) for path in generation_plan_paths),
            timeout_envs=(
                "AI_ADMIN_QUESTION_GENERATION_WALL_SECONDS",
                "AI_QUESTION_WALL_SECONDS",
                "AI_QUESTION_TIMEOUT_SECONDS",
            ),
            default_seconds=150.0,
        ) as transport_meta:
            result = model_router.call_structured_json(
                route,
                payload,
                schema=schema,
                plain_json_instruction="Return only one valid JSON object matching the batch field contract in the prompt; no markdown.",
                retryable_errors_fallback=True,
                include_fallback_schema=False,
            )
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    except model_router.ModelCallError as exc:
        error_report = {
            **base_report,
            "status": "BLOCKED_MODEL_ERROR",
            "provider_mode": "live_model",
            "retryable": model_router.is_retryable_model_call_error(exc),
            "model_error": {
                "error_class": type(exc).__name__,
                "message": str(exc)[:800],
                "status_code": exc.status_code,
                "retry_after_seconds": exc.retry_after_seconds,
                "endpoint": exc.endpoint,
                "structured_json_mode": exc.structured_json_mode,
            },
            "transport_meta": transport_meta,
            "next_actions": ["retry_or_repair_model_route"],
        }
        error_report["candidate_reports"] = [
            {**candidate, "status": "BLOCKED_MODEL_ERROR", "provider_mode": "live_model", "model_error": error_report["model_error"], "next_actions": ["retry_or_repair_model_route"]}
            for candidate in candidate_reports
        ]
        return error_report

    by_index: dict[int, dict[str, Any]] = {}
    for candidate in result.value.get("candidates") or []:
        if isinstance(candidate, dict) and isinstance(candidate.get("plan_index"), int):
            by_index[int(candidate["plan_index"])] = candidate

    completed_reports: list[dict[str, Any]] = []
    batch_findings: list[dict[str, str]] = []
    for index, (plan, requirement, design_brief, brief_path, report) in enumerate(zip(plans, requirements, design_briefs, design_brief_paths, candidate_reports)):
        output = by_index.get(index)
        if not output:
            finding = {
                "severity": "P1",
                "profile": "admin_generation_batch_gate",
                "item_id": "",
                "node_id": str(plan.get("node_id") or ""),
                "code": "missing_candidate_for_plan_index",
                "message": f"批量命题输出缺少 plan_index={index} 的候选题。",
            }
            batch_findings.append(finding)
            completed_reports.append({**report, "status": "NEEDS_REGENERATION", "provider_mode": "live_model", "findings": [finding], "finding_counts": {"P1": 1}, "next_actions": ["single_slot_regeneration"]})
            continue
        item = _normalize_model_item(
            output,
            plan=plan,
            requirement=requirement,
            generation_attempt=generation_attempt,
            previous_rejection_codes=[],
        )
        machine_report = validate_candidate_against_brief(
            root=root,
            candidate={"item": item},
            design_brief=design_brief,
            design_brief_path=brief_path,
            subject=subject,
            required_family_id=str(plan.get("family_id") or ""),
            required_slot=requirement,
        )
        machine_report = _merge_machine_findings(
            machine_report,
            _child_surface_findings(
                item,
                model_output=output,
                plan=plan,
                requirement=requirement,
            ),
        )
        passed = machine_report.get("status") in {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"}
        findings = list(machine_report.get("findings") or [])
        batch_findings.extend(findings)
        completed_reports.append({
            **report,
            "status": "CANDIDATE_READY_FOR_EXPERT_REVIEW" if passed else "NEEDS_REGENERATION",
            "provider_mode": "live_model",
            "retryable": False,
            "route": {
                **model_router.route_status(route).as_dict(),
                "structured_json_mode": result.mode,
                "structured_json_endpoint": result.endpoint,
                "model_elapsed_ms": elapsed_ms,
                **transport_meta,
                "raw_response_sha256": hashlib.sha256(json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            },
            "candidate": {
                "schema_version": "2026-07-23.codex-admin.question-candidate-artifact.v1",
                "item": item,
                "model_output_sha256": _digest_json(output),
                "candidate_sha256": _digest_json(item),
            },
            "item_id": item.get("id"),
            "candidate_sha256": _digest_json(item),
            "machine_report": machine_report,
            "finding_counts": _findings_by_severity(findings),
            "findings": sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("profile", ""), f.get("code", ""))),
            "next_actions": ["expert_review"] if passed else ["single_slot_regeneration"],
        })

    fingerprint_to_indexes: dict[str, list[int]] = {}
    for index, report in enumerate(completed_reports):
        item = ((report.get("candidate") or {}).get("item") or {}) if isinstance(report.get("candidate"), dict) else {}
        quality = (item.get("quality") or {}) if isinstance(item.get("quality"), dict) else {}
        fingerprints = {
            str(quality.get("canonical_structure_fingerprint") or "").strip(),
            str(quality.get("model_structure_fingerprint") or "").strip(),
            str(quality.get("structure_fingerprint") or "").strip(),
        }
        for fingerprint in sorted(value for value in fingerprints if value):
            fingerprint_to_indexes.setdefault(fingerprint, []).append(index)
    for fingerprint, indexes in sorted(fingerprint_to_indexes.items()):
        if len(indexes) < 2:
            continue
        for index in indexes:
            report = completed_reports[index]
            item = ((report.get("candidate") or {}).get("item") or {}) if isinstance(report.get("candidate"), dict) else {}
            finding = {
                "severity": "P1",
                "profile": "admin_generation_batch_gate",
                "item_id": str(report.get("item_id") or ""),
                "node_id": str(report.get("node_id") or ""),
                "code": "batch_duplicate_structure_fingerprint",
                "message": f"同批命题出现重复结构指纹：{fingerprint}。批量生产不能用同壳换数字凑数。",
            }
            existing_findings = list(report.get("findings") or [])
            existing_findings.append(finding)
            batch_findings.append(finding)
            completed_reports[index] = {
                **report,
                "status": "NEEDS_REGENERATION",
                "finding_counts": _findings_by_severity(existing_findings),
                "findings": sorted(existing_findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("profile", ""), f.get("code", ""))),
                "next_actions": ["single_slot_regeneration"],
            }

    ready_count = sum(1 for report in completed_reports if report.get("status") == "CANDIDATE_READY_FOR_EXPERT_REVIEW")
    failed_count = len(completed_reports) - ready_count
    return {
        **base_report,
        "status": "BATCH_CANDIDATES_READY" if failed_count == 0 else "BATCH_CANDIDATES_PARTIAL",
        "provider_mode": "live_model",
        "retryable": False,
        "route": {
            **model_router.route_status(route).as_dict(),
            "structured_json_mode": result.mode,
            "structured_json_endpoint": result.endpoint,
            "model_elapsed_ms": elapsed_ms,
            **transport_meta,
            "raw_response_sha256": hashlib.sha256(json.dumps(result.raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        },
        "candidate_reports": completed_reports,
        "ready_candidate_count": ready_count,
        "failed_candidate_count": failed_count,
        "finding_counts": _findings_by_severity(batch_findings),
        "findings": sorted(batch_findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("profile", ""), f.get("code", ""))),
        "next_actions": ["expert_review_batch_outputs"] if ready_count else ["single_slot_regeneration"],
    }


def write_generated_candidate_artifact(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    result = dict(report)
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    item = candidate.get("item") if isinstance(candidate.get("item"), dict) else {}
    if not item:
        result["candidate_write_applied"] = False
        return result
    item_id = str(item.get("id") or "candidate")
    candidate_sha = str(result.get("candidate_sha256") or candidate.get("candidate_sha256") or _digest_json(item))
    rel = Path("data/admin/candidates") / f"{item_id}-{candidate_sha[:12]}.json"
    result["candidate_json_path"] = str(rel)
    result["candidate_write_applied"] = bool(apply)
    if not apply:
        return result
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["candidate_json_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
