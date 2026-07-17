from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PROJECT_ROOT / "learning_system/agent_contracts"
PROMPT_ROOT = PROJECT_ROOT / "learning_system/prompts"


INTERNAL_AGENT_ROLES: dict[str, dict[str, str]] = {
    "session_orchestrator_agent": {
        "display": "会话编排 Agent",
        "does": "控制一整轮状态机，决定下一步是讲、练、回退还是拔高",
        "does_not": "不直接出题、不直接判分",
        "contract_key": "session_orchestrator",
    },
    "graph_agent": {
        "display": "图谱 Agent",
        "does": "把题目、错因、前置依赖绑定到知识图谱节点",
        "does_not": "不凭感觉说“粗心”",
        "contract_key": "graph_binding",
    },
    "question_designer_agent": {
        "display": "命题 Agent",
        "does": "按节点、错因、目标证据生成题",
        "does_not": "不出低龄机械题",
        "contract_key": "question_candidate",
    },
    "question_reviewer_agent": {
        "display": "审题 Agent",
        "does": "拦截弱智题、答案-only题、无思路证据题",
        "does_not": "不追求题量",
        "contract_key": "question_review",
    },
    "answer_analysis_agent": {
        "display": "答案分析 Agent",
        "does": "判断答案、步骤、思路、替代解法、过程缺口，并产出可支撑评估与规划的证据摘要",
        "does_not": "不做字符串匹配、不更新掌握状态、不选择下一轮题目、不把分数当作掌握结论",
        "contract_key": "answer_review",
        "v5_contract_key": "answer_review",
        "v5_contract_version_suffix": "v3",
    },
    "answer_contract_designer_agent": {
        "display": "答案合同设计 Agent",
        "does": "根据题目本质与参考解答，为本地评分槽位编写原子、可观察的语义判据",
        "does_not": "不分配分值、维度、通过条件，不改题、不重绑、不版本化或激活合同",
        "contract_key": "answer_contract_design",
        "v5_contract_key": "answer_contract_design",
        "v5_contract_version_suffix": "v1",
    },
    "answer_contract_reviewer_agent": {
        "display": "答案合同审查 Agent",
        "does": "独立审查题目正确性、节点与证据角色对齐，以及答案合同的原子评分标准",
        "does_not": "不修改题目、不重绑节点、不生成或批准自己的指纹与摘要哈希",
        "contract_key": "answer_contract_review",
        "v5_contract_key": "answer_contract_review",
        "v5_contract_version_suffix": "v1",
    },
    "evaluation_agent": {
        "display": "评估 Agent",
        "does": "把有效答案分析证据转成节点掌握诊断与规划信号，区分概念、模型、计算、表达、迁移",
        "does_not": "不判原始答案、不直接出题或排题、不把一次做对或同构重复当完全掌握",
        "contract_key": "evaluation_decision",
        "v5_contract_key": "evaluation_decision",
        "v5_contract_version_suffix": "v2",
    },
    "teaching_agent": {
        "display": "讲解 Agent",
        "does": "给孩子生成针对性讲解和下一题前提示",
        "does_not": "不输出后台分析",
        "contract_key": "teaching_step",
        "v5_contract_key": "teaching_step",
        "v5_contract_version_suffix": "v3",
    },
    "planner_agent": {
        "display": "规划 Agent",
        "does": "根据评估规划信号、图谱依赖和当前可用题库候选包选择一个下一步动作",
        "does_not": "不评估掌握、不分析答案、不生成新题、不覆盖评估结论、不机械按日历排课",
        "contract_key": "planner_transition",
        "v5_contract_key": "planner_next_step",
        "v5_contract_version_suffix": "v2",
    },
    "self_evolution_agent": {
        "display": "自进化 Agent",
        "does": "根据真实证据改题型规则、错因规则、agent profile，并给出可审计、可回滚、可验证的进化提案",
        "does_not": "不为了测试而假进化、不直接判分/排题/讲解/批准题目、不用 pending/invalidated/stale/mock 证据进化",
        "contract_key": "evolution_proposal",
    },
}


VERSIONED_AGENT_CONTRACTS = {
    "answer_contract_designer_agent": frozenset({"v1", "v2"}),
    "answer_contract_reviewer_agent": frozenset({"v1", "v2"}),
}


PHASES = {
    "select_target_node",
    "diagnostic_intro",
    "diagnostic_batch",
    "system_analysis",
    "targeted_explanation",
    "prerequisite_probe",
    "prerequisite_repair",
    "essence_explanation",
    "worked_example",
    "guided_question",
    "answer_analysis",
    "reteach",
    "consolidation_question",
    "consolidation_set",
    "consolidation_analysis",
    "reteach_variant",
    "stretch_question",
    "stretch_set",
    "stretch_analysis",
    "session_close",
    "analysis_pending",
    "paused",
}

NEXT_ACTIONS = {
    "show_explanation",
    "ask_question",
    "analyze_batch",
    "request_clearer_evidence",
    "repair_prerequisite",
    "reteach_current_node",
    "give_consolidation",
    "give_stretch",
    "close_mastered",
    "close_repaired",
    "close_prerequisite_blocked",
    "pause_pending_analysis",
    "resume_saved_step",
}

MASTERY_DECISIONS = {
    "not_enough_evidence",
    "pending_analysis",
    "prerequisite_blocked",
    "current_node_weak",
    "basic_understanding",
    "stable_understanding",
    "stretch_ready",
    "mastered_for_now",
}

CLOSURE_RESULTS = {
    "mastered",
    "repaired_not_mastered",
    "prerequisite_blocked",
    "pending_analysis",
    "paused_time_boundary",
    "invalidated",
}

TRANSITION_TABLE = {
    ("diagnostic_intro", "ask_question"): "diagnostic_batch",
    ("diagnostic_batch", "analyze_batch"): "system_analysis",
    ("system_analysis", "show_explanation"): "targeted_explanation",
    ("targeted_explanation", "give_consolidation"): "consolidation_set",
    ("consolidation_set", "analyze_batch"): "consolidation_analysis",
    ("consolidation_analysis", "repair_prerequisite"): "prerequisite_repair",
    ("consolidation_analysis", "reteach_current_node"): "reteach_variant",
    ("consolidation_analysis", "give_stretch"): "stretch_set",
    ("stretch_set", "analyze_batch"): "stretch_analysis",
    ("stretch_analysis", "close_mastered"): "session_close",
    ("stretch_analysis", "close_repaired"): "session_close",
    ("select_target_node", "ask_question"): "prerequisite_probe",
    ("prerequisite_probe", "repair_prerequisite"): "prerequisite_repair",
    ("prerequisite_repair", "ask_question"): "prerequisite_probe",
    ("prerequisite_probe", "show_explanation"): "essence_explanation",
    ("essence_explanation", "show_explanation"): "worked_example",
    ("worked_example", "ask_question"): "guided_question",
    ("guided_question", "analyze_batch"): "answer_analysis",
    ("answer_analysis", "reteach_current_node"): "reteach",
    ("reteach", "ask_question"): "guided_question",
    ("answer_analysis", "give_consolidation"): "consolidation_question",
    ("consolidation_question", "analyze_batch"): "answer_analysis",
    ("answer_analysis", "give_stretch"): "stretch_question",
    ("stretch_question", "analyze_batch"): "stretch_analysis",
    ("analysis_pending", "resume_saved_step"): "paused",
}


CHILD_SAFE_KEYS = {
    "child_title",
    "child_explanation",
    "child_feedback",
    "child_action",
    "coach_points",
    "review_points",
    "input_hint",
    "next_action_label",
    "next_task_count",
    "photo_hint",
    "retry_prompt",
    "pending_message",
}

FORBIDDEN_CHILD_PATTERNS = (
    re.compile(r"\b(?:Agent|Codex|API|model|provider|pending_review|audit|rubric|graph|internal|model_name|model_alias|model_provider|base_url|gpt|doubao)\b", re.IGNORECASE),
    re.compile(r"\bM-[A-Z0-9-]+\b"),
    re.compile(r"\b(?:node_id|question_id|attempt_id|agent_key|error_tags|evidence_status)\b"),
    re.compile(r"(?:图谱覆盖|图谱|节点|审计|内部状态|自进化|家长报告|复制给\s*Codex|父母|家长复核|模型路由|模型|豆包|中转站)"),
    re.compile(r"(?:process_habit|concept_confusion|modeling_or_reading|calculation_or_symbol|visual_spatial)"),
)


def transition_next_phase(phase: str, next_action: str) -> str:
    try:
        return TRANSITION_TABLE[(phase, next_action)]
    except KeyError as exc:
        raise ValueError(f"Invalid teaching transition: {phase} + {next_action}") from exc


def validate_child_safe_message(payload: dict[str, Any]) -> None:
    for key in payload:
        if key not in CHILD_SAFE_KEYS:
            raise ValueError(f"Child message contains internal field: {key}")
    combined = "\n".join(str(value) for value in payload.values())
    for pattern in FORBIDDEN_CHILD_PATTERNS:
        match = pattern.search(combined)
        if match:
            raise ValueError(f"Child message leaks internal wording: {match.group(0)}")


def contract_path(contract_key: str, *, version_suffix: str = "v1") -> Path:
    return CONTRACT_ROOT / f"{contract_key}.{version_suffix}.json"


def prompt_path_for_contract(contract: dict[str, Any]) -> Path:
    configured = contract.get("prompt_template_path")
    if not isinstance(configured, str) or not configured.strip():
        raise FileNotFoundError("contract prompt_template_path is required")
    relative = Path(configured)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("prompt_template_path must be a safe relative path")
    prompt_root = PROMPT_ROOT.resolve()
    candidate = (PROJECT_ROOT / relative).resolve()
    try:
        candidate.relative_to(prompt_root)
    except ValueError as exc:
        raise ValueError("prompt_template_path escapes the prompt root") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"prompt template does not exist: {configured}")
    return candidate


def load_contract(contract_key: str, *, version_suffix: str = "v1") -> dict[str, Any]:
    path = contract_path(contract_key, version_suffix=version_suffix)
    return json.loads(path.read_text(encoding="utf-8"))


def v5_contract_key_for_agent(agent_key: str) -> str:
    try:
        role = INTERNAL_AGENT_ROLES[agent_key]
    except KeyError as exc:
        raise ValueError(f"Unknown internal agent: {agent_key}") from exc
    return str(role.get("v5_contract_key") or role["contract_key"])


def load_v5_contract_for_agent(agent_key: str) -> dict[str, Any]:
    try:
        role = INTERNAL_AGENT_ROLES[agent_key]
    except KeyError as exc:
        raise ValueError(f"Unknown internal agent: {agent_key}") from exc
    return load_contract(
        str(role.get("v5_contract_key") or role["contract_key"]),
        version_suffix=str(role.get("v5_contract_version_suffix") or "v2"),
    )


def load_contract_for_agent_version(
    agent_key: str, version_suffix: str
) -> dict[str, Any]:
    allowed = VERSIONED_AGENT_CONTRACTS.get(agent_key)
    if allowed is None or version_suffix not in allowed:
        raise ValueError(
            f"unsupported contract version for {agent_key}: {version_suffix}"
        )
    role = INTERNAL_AGENT_ROLES[agent_key]
    return load_contract(
        str(role.get("v5_contract_key") or role["contract_key"]),
        version_suffix=version_suffix,
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
