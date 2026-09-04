"""Concrete, storage-free skills for the question production pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import json
import hashlib

from .question_artifact import CONTENT_SCHEMA_VERSION
from . import child_prompt, local_env, model_router


RESPONSE_MODES = {"single_choice", "multi_choice", "fill_blank", "short_answer"}
STAGES = ("qf_design", "slot_design", "brief_generation", "candidate_generation")

PRODUCTION_OBJECT_MODEL = """你必须严格遵守以下五层对象定义：

1. Node：知识图谱中的知识节点。它规定知识范围、核心概念、前置依赖、错误类型和边界。Node 是输入事实，不由当前阶段重新定义。
2. QF（Question Family）：一个稳定的题目家族，回答“这个 Node 要测哪一种独立能力”。QF 规定测量目标、题目任务类别、允许的答题形式和范围。QF 不是一道题，也不是一组数字模板；只换数字、语境或措辞不能形成新 QF。
3. Slot：一个 QF 下的一种具体测量槽位，回答“这一道题必须用什么结构证明哪一个能力”。Slot 规定题面结构、孩子必须完成的动作、必要条件、主要错因、答案形态、难度下限和拒绝条件。Slot 不是具体题目，不能写入本次题目的具体数字、最终答案或完整题干。
4. Brief：针对一个 Slot 的一次具体出题说明，回答“这一次 Candidate 应如何构造”。Brief 把 Slot 约束落实为可执行的构造步骤、参数边界、决策点、陷阱、答案合同和自检项，但仍不是孩子看到的题目，不能代替 Candidate。
5. Candidate：根据一个 Brief 实际生成的一道题。Candidate 才包含具体题干、选项和答案；一次 Brief 只能生成一道 Candidate。

层级关系只能是：Node -> QF -> Slot -> Brief -> Candidate。
当前阶段只能生成指定对象，不能顺便生成下游对象。上游输入是权威且不可修改的；如果发现上游内容有问题，只能在输出中报告约束冲突，不能自行改写上游。
"""

PRODUCTION_SYSTEM_PROMPT = "你是本学习系统的数学题目生产模型。\n" + PRODUCTION_OBJECT_MODEL
REVIEWER_SYSTEM_PROMPT = "你是本学习系统的独立语义审查模型。\n" + PRODUCTION_OBJECT_MODEL

GENERATOR_COMMON_PROMPT = """你负责生成当前阶段的对象，不负责审查别的阶段，也不负责替换上游对象。
上游 Node、QF、Slot 或 Brief 是权威输入，必须逐条继承；不能因为生成困难而删除、放宽、改写或偷偷转移约束。
生成顺序固定为：先提取上游约束和本阶段职责，再在内部形成候选设计，删除重复、越界和不可执行的设计，最后输出通过自检的结果。
内部自检必须在输出前完成，不能把“待检查”“尽量”“适当”“合理”当作已经完成的规则。
数量由当前输入中的独立能力或独立测量动作决定，不设默认数量，不为了凑数拆分，也不为了省事合并。
只返回当前阶段要求的 JSON 对象或对象数组，不返回分析过程、markdown、解释文字或其它字段。
"""

BRIEF_V2_AUTHORING_CONTRACT = """Brief v2 共享命题审计合同：
1. 先在 parameter_model 中确定一个 task_variant，并把该变体的题面动作、答案字段、答案顺序和验收条件写清；不能把多个变体留给 Candidate 临时决定。
2. 每个变量的 type 与 domain 必须一致，变量关系、精度、范围和排除条件必须能实际生成和复核合法实例。
3. evidence_plan 中每项 required 证据都必须由当前 response_mode 直接采集；short_answer 只能采集学生写出的内容，single_choice 只能采集选择结果，fill_blank 只能采集各空答案；题面清晰性属于实例验收，不是学生行为证据。
4. Brief 只能描述可变参数、关系和推导规则，不能写本次 Candidate 的具体数值、具体选项、具体答案或完整题干。
5. 不得自行增加 Slot 未要求的数量、字段或固定实例；Brief 的每个核心机制、测量动作和答案字段都必须能回溯到 Node、QF、Slot。
6. instance_acceptance.must_hold 必须包含 Slot 的最低难度、全部必需测量动作、答案字段要求和至少一个不能靠关键词、固定顺序或机械抄写完成的真实决策。
7. answer_plan.encoding、task.response_mode、evidence_plan.capture_mode、response_field_count 和 reference_answer_count 必须共同形成闭合接口，能直接映射 Candidate 的 prompt、choices、answer、rubric、solution_steps。
生成或审查前按以上顺序逐项检查；任何一项无法证明，都应先修正 Brief，而不是把不确定性留给 Candidate。
"""


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _text_object(fields: list[str]) -> dict[str, Any]:
    return _schema({field: {"type": "string"} for field in fields}, fields)


def _list_object(fields: list[str]) -> dict[str, Any]:
    return _schema({field: TEXT_LIST_SCHEMA for field in fields}, fields)


TEXT_LIST_SCHEMA = {"type": "array", "items": {"type": "string"}}
RESPONSE_MODE_SCHEMA = {
    "type": "string",
    "enum": sorted(RESPONSE_MODES),
}
RESPONSE_MODE_LIST_SCHEMA = {
    "type": "array",
    "items": RESPONSE_MODE_SCHEMA,
}
QF_ITEM_SCHEMA = _schema(
    {
        "qf_id": {"type": "string"}, "node_id": {"type": "string"}, "name": {"type": "string"},
        "task_type": {"type": "string"}, "measurement_intent": {"type": "string"},
        "independent_reason": {"type": "string"}, "allowed_response_modes": RESPONSE_MODE_LIST_SCHEMA,
        "scope": _list_object(["include", "exclude", "boundary_rules"]), "required_evidence": TEXT_LIST_SCHEMA, "reject_if": TEXT_LIST_SCHEMA,
    },
    ["qf_id", "node_id", "name", "task_type", "measurement_intent", "independent_reason", "allowed_response_modes", "scope", "required_evidence", "reject_if"],
)
SLOT_ITEM_SCHEMA = _schema(
    {
        "slot_id": {"type": "string"}, "node_id": {"type": "string"}, "qf_id": {"type": "string"},
        "task_type": {"type": "string"}, "response_mode": RESPONSE_MODE_SCHEMA, "structure": {"type": "string"},
        "measurement_target": {"type": "string"}, "conditions": TEXT_LIST_SCHEMA, "error_targets": TEXT_LIST_SCHEMA,
        "minimum_quality": TEXT_LIST_SCHEMA, "reject_if": TEXT_LIST_SCHEMA,
    },
    ["slot_id", "node_id", "qf_id", "task_type", "response_mode", "structure", "measurement_target", "conditions", "error_targets", "minimum_quality", "reject_if"],
)
CONTENT_BLUEPRINT_SCHEMA = _schema(
    {
        "target_concept": {"type": "string"},
        "mechanism_type": {"type": "string"},
        "problem_mechanism": {"type": "string"},
        "student_actions": TEXT_LIST_SCHEMA,
        "misconception_mechanism": {"type": "string"},
        "parameter_pattern": _list_object(["vary", "must_hold", "avoid", "generation_steps"]),
        "answer_derivation": {"type": "string"},
        "good_instance_pattern": {"type": "string"},
        "bad_instance_pattern": {"type": "string"},
    },
    [
        "target_concept",
        "mechanism_type",
        "problem_mechanism",
        "student_actions",
        "misconception_mechanism",
        "parameter_pattern",
        "answer_derivation",
        "good_instance_pattern",
        "bad_instance_pattern",
    ],
)
ANSWER_ENCODING_SCHEMA = {
    "type": "string",
    "enum": ["choice_text", "field_text", "response_text"],
}
FIELD_MAPPING_SCHEMA = _text_object(["prompt", "choices", "answer", "rubric", "solution_steps"])
CANDIDATE_CONTRACT_SCHEMA = _schema(
    {
        "response_mode": RESPONSE_MODE_SCHEMA,
        "answer_encoding": ANSWER_ENCODING_SCHEMA,
        "field_mapping": FIELD_MAPPING_SCHEMA,
        "response_field_count": {"type": "integer", "minimum": 1},
        "reference_answer_count": {"type": "integer", "minimum": 1},
        "answer_requirements": TEXT_LIST_SCHEMA,
        "choice_requirements": TEXT_LIST_SCHEMA,
        "prompt_requirements": TEXT_LIST_SCHEMA,
    },
    [
        "response_mode",
        "answer_encoding",
        "field_mapping",
        "response_field_count",
        "reference_answer_count",
        "answer_requirements",
        "choice_requirements",
        "prompt_requirements",
    ],
)
MECHANISM_STEP_SCHEMA = _schema(
    {
        "id": {"type": "string"},
        "purpose": {"type": "string"},
        "input": {"type": "string"},
        "student_action": {"type": "string"},
        "output": {"type": "string"},
        "success_condition": {"type": "string"},
    },
    ["id", "purpose", "input", "student_action", "output", "success_condition"],
)
MECHANISM_SCHEMA = _schema(
    {
        "type": {"type": "string"},
        "purpose": {"type": "string"},
        "steps": {"type": "array", "minItems": 1, "items": MECHANISM_STEP_SCHEMA},
        "completion_condition": {"type": "string"},
    },
    ["type", "purpose", "steps", "completion_condition"],
)
PARAMETER_VARIABLE_SCHEMA = _schema(
    {
        "name": {"type": "string"},
        "role": {"type": "string"},
        "type": {"type": "string"},
        "domain": {"type": "string"},
    },
    ["name", "role", "type", "domain"],
)
PARAMETER_MODEL_SCHEMA = _schema(
    {
        "variables": {"type": "array", "minItems": 1, "items": PARAMETER_VARIABLE_SCHEMA},
        "constraints": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "construction_steps": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    ["variables", "constraints", "construction_steps"],
)
EVIDENCE_ITEM_SCHEMA = _schema(
    {
        "evidence_id": {"type": "string"},
        "student_action": {"type": "string"},
        "observable_evidence": {"type": "string"},
        "capture_mode": RESPONSE_MODE_SCHEMA,
        "required": {"type": "boolean"},
    },
    ["evidence_id", "student_action", "observable_evidence", "capture_mode", "required"],
)
EVIDENCE_PLAN_SCHEMA = _schema(
    {"items": {"type": "array", "minItems": 1, "items": EVIDENCE_ITEM_SCHEMA}},
    ["items"],
)
ANSWER_PLAN_SCHEMA = _schema(
    {
        "encoding": ANSWER_ENCODING_SCHEMA,
        "response_field_count": {"type": "integer", "minimum": 1},
        "reference_answer_count": {"type": "integer", "minimum": 1},
        "field_mapping": FIELD_MAPPING_SCHEMA,
        "answer_evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "solution_structure": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    ["encoding", "response_field_count", "reference_answer_count", "field_mapping", "answer_evidence", "solution_structure"],
)
INSTANCE_ACCEPTANCE_SCHEMA = _schema(
    {
        "must_hold": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "uniqueness_check": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "reject_if": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    ["must_hold", "uniqueness_check", "reject_if"],
)
BRIEF_V2_SCHEMA = _schema(
    {
        "schema_version": {"type": "string", "enum": ["brief-design.v2"]},
        "brief_id": {"type": "string"},
        "node_id": {"type": "string"},
        "qf_id": {"type": "string"},
        "slot_id": {"type": "string"},
        "task": _schema({"task_type": {"type": "string"}, "response_mode": RESPONSE_MODE_SCHEMA}, ["task_type", "response_mode"]),
        "mechanism": MECHANISM_SCHEMA,
        "parameter_model": PARAMETER_MODEL_SCHEMA,
        "evidence_plan": EVIDENCE_PLAN_SCHEMA,
        "answer_plan": ANSWER_PLAN_SCHEMA,
        "instance_acceptance": INSTANCE_ACCEPTANCE_SCHEMA,
    },
    ["schema_version", "brief_id", "node_id", "qf_id", "slot_id", "task", "mechanism", "parameter_model", "evidence_plan", "answer_plan", "instance_acceptance"],
)
BRIEF_ITEM_SCHEMA = _schema(
    {
        "brief_id": {"type": "string"}, "node_id": {"type": "string"}, "qf_id": {"type": "string"}, "slot_id": {"type": "string"},
        "task": _schema({"task_type": {"type": "string"}, "response_mode": {"type": "string"}}, ["task_type", "response_mode"]),
        "content_blueprint": CONTENT_BLUEPRINT_SCHEMA,
        "candidate_contract": CANDIDATE_CONTRACT_SCHEMA,
        "construction": _list_object(["question_shape", "required_decisions", "forbidden_shortcuts"]),
        "answer_contract": _schema({"grading_mode": {"type": "string"}, "answer_shape": {"type": "string"}, "field_count": {"type": "integer"}}, ["grading_mode", "answer_shape", "field_count"]),
        "difficulty_contract": _schema({"minimum": {"type": "string"}, "decision_points": TEXT_LIST_SCHEMA}, ["minimum", "decision_points"]),
        "self_check": TEXT_LIST_SCHEMA,
    },
    ["brief_id", "node_id", "qf_id", "slot_id", "task", "content_blueprint", "candidate_contract", "construction", "answer_contract", "difficulty_contract", "self_check"],
)
CONTENT_ITEM_SCHEMA = _schema(
    {
        "schema_version": {"type": "string", "enum": [CONTENT_SCHEMA_VERSION]},
        "task_type": {"type": "string", "enum": ["calculation", "reasoning", "application"]},
        "response_mode": {"type": "string", "enum": ["single_choice", "multi_choice", "fill_blank", "short_answer"]},
        "prompt": {"type": "string"}, "choices": TEXT_LIST_SCHEMA, "answer": TEXT_LIST_SCHEMA,
        "rubric": TEXT_LIST_SCHEMA, "solution_steps": TEXT_LIST_SCHEMA,
    },
    ["schema_version", "task_type", "response_mode", "prompt", "choices", "answer", "rubric", "solution_steps"],
)
LIVE_SCHEMAS = {
    "qf-design.v1": _schema({"qfs": {"type": "array", "minItems": 1, "items": QF_ITEM_SCHEMA}}, ["qfs"]),
    "slot-design.v1": _schema({"slots": {"type": "array", "minItems": 1, "items": SLOT_ITEM_SCHEMA}}, ["slots"]),
    "brief-design.v1": BRIEF_ITEM_SCHEMA,
    "brief-design.v2": BRIEF_V2_SCHEMA,
    "question-content.v1": CONTENT_ITEM_SCHEMA,
    "semantic-review.v1": _schema(
        {
            "decision": {"type": "string", "enum": ["accepted", "rejected"]},
            "score": {"type": "number", "minimum": 0, "maximum": 10},
            "issues": TEXT_LIST_SCHEMA,
            "repair_instructions": TEXT_LIST_SCHEMA,
            "root_cause_stage": {"type": "string", "enum": ["qf_design", "slot_design", "brief_generation", "candidate_generation", "pipeline_contract", "none"]},
            "recovery_action": {"type": "string", "enum": ["retry_current_stage", "regenerate_from_stage", "stop_and_fix_contract", "none"]},
            "recovery_stage": {"type": "string", "enum": ["qf_design", "slot_design", "brief_generation", "candidate_generation", "pipeline_contract", "none"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        ["decision", "score", "issues", "repair_instructions", "root_cause_stage", "recovery_action", "recovery_stage", "confidence"],
    ),
}


@dataclass(frozen=True)
class ValidationResult:
    """Stable validator result; the orchestrator decides whether to retry."""

    status: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    retry_allowed: bool = False
    target_stage: str | None = None
    max_attempts: int | None = None
    reason: str = ""
    validator_version: str = "production-validator-v1"

    @classmethod
    def passed(cls, *, warnings: list[dict[str, Any]] | None = None) -> "ValidationResult":
        return cls(status="passed", warnings=list(warnings or []))

    @classmethod
    def rejected(
        cls,
        errors: Iterable[dict[str, Any]],
        *,
        target_stage: str | None,
        max_attempts: int = 2,
        reason: str = "",
    ) -> "ValidationResult":
        return cls(
            status="rejected",
            errors=list(errors),
            retry_allowed=True,
            target_stage=target_stage,
            max_attempts=max_attempts,
            reason=reason,
        )

    def error_codes(self) -> list[str]:
        return [str(error.get("code") or "validation_failed") for error in self.errors]


Generator = Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]
Validator = Callable[[dict[str, Any], dict[str, Any]], ValidationResult]
Reviewer = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
ReviewValidator = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], ValidationResult]


def _json_section(label: str, value: Any) -> str:
    return f"\n{label}:\n" + json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _production_node_input(node: dict[str, Any]) -> dict[str, Any]:
    """Expose the stable node identity plus the production contract only."""
    if isinstance(node.get("node"), dict):
        node = node["node"]
    contract = node.get("production_contract")
    if not isinstance(contract, dict):
        return node
    return {
        "id": node.get("id") or node.get("node_id"),
        "name": node.get("name", ""),
        "production_contract": contract,
    }


def _revision_section(revision_context: dict[str, Any] | None) -> str:
    if not revision_context:
        return ""
    return (
        "\n本次是结构修订，不是普通首次生成。只修订反馈明确指出的 QF/Slot 结构问题，"
        "逐条落实每一条反馈，保留未被指出的问题内容，不要扩大范围，不要生成下游 Brief 或 Candidate。\n"
        "修订后的 QF/Slot 必须解决反馈指出的冲突，不能只改名称或换措辞；如果反馈指出答题形式无法承载证据，必须删除该形式或改为能承载证据的形式。\n"
        + _json_section("结构修订反馈", revision_context)
    )


def build_qf_prompt(node: dict[str, Any], *, previous_qfs: list[dict[str, Any]], previous_validation_errors: list[dict[str, Any]] | list[str] | None = None, revision_context: dict[str, Any] | None = None) -> str:
    return (
        PRODUCTION_SYSTEM_PROMPT
        + "\n"
        + GENERATOR_COMMON_PROMPT
        + "\nSTAGE: QF_DESIGN\n"
        + "\n本阶段任务：只设计 QF。不要设计 Slot、Brief、Candidate，也不要生成具体题目。\n"
        "生成前先拆解 Node 中的能力：核心目标、必须证明的能力、不能作为充分证据的表现、范围边界、错误模式和受控迁移。\n"
        "每个 QF 都要完成一次独立能力盘点：它测什么独立能力、为什么不能并入其它 QF、未来需要哪些证据才能判断这项能力。\n"
        "不得默认返回全部四种答题形式；先根据要证明的证据决定是否需要选择、填空或简答，允许的答题形式只能服务于证据采集，不能为了覆盖形式而拆分 QF。\n"
        "先在内部列出 Node 可能涉及的能力，再合并同一能力的不同题型、数字和语境，删除只属于前置节点或下游节点的能力，最后输出真正需要单独测量的 QF。\n"
        "每个 QF 必须包含：qf_id、node_id、name、task_type、measurement_intent、independent_reason、allowed_response_modes、scope、required_evidence、reject_if。\n"
        "allowed_response_modes 只能使用 single_choice、multi_choice、fill_blank、short_answer；不允许判断题。\n"
        "measurement_intent 必须描述要测的能力而不是题目外观；independent_reason 必须说明为什么不能与已有 QF 合并。\n"
        "scope.include/exclude/boundary_rules 必须停留在 QF 家族边界；required_evidence 和 reject_if 必须是家族级证据与拒绝条件，不能下沉成某道题的数字、步骤或答案。\n"
        "只改变题型、数字、单位、语境、选项位置或措辞，不得形成新的 QF；variant ladder 也不是 QF 数量。\n"
        "输出前逐个确认：独立能力成立、Node 对齐、没有下游内容、没有具体题目内容。输出必须是 QF 对象数组；数组中的每个对象都是一个独立 QF。\n"
        + _revision_section(revision_context)
        + _json_section("Node", _production_node_input(node))
        + _json_section("已有 QF（用于去重，不得复制）", previous_qfs)
        + _json_section("上一次验证问题（重试时必须修复）", previous_validation_errors or [])
    )


def build_slot_prompt(node: dict[str, Any], qf: dict[str, Any], *, previous_slots: list[dict[str, Any]], previous_validation_errors: list[dict[str, Any]] | list[str] | None = None, revision_context: dict[str, Any] | None = None) -> str:
    return (
        PRODUCTION_SYSTEM_PROMPT
        + "\n"
        + GENERATOR_COMMON_PROMPT
        + "\nSTAGE: SLOT_DESIGN\n"
        + "\n本阶段任务：只根据 Node 和一个 QF 设计 Slot。不要设计 Brief、Candidate，也不要生成具体题目。\n"
        "生成前先拆解 QF 下不可替代的测量动作：学生必须完成什么动作、这个动作产生什么可观察证据、主要暴露哪一种错误。\n"
        "每个 Slot 都要写成可观察的学生动作，而不是题型名称、数字模板或难度标签。\n"
        "先确定要采集的证据，再选择能承载这些证据的答题形式：如果证据包含解释、推导或修正，不能只选 multi_choice；如果只需选择固定集合，不得额外要求无法由选择结果证明的解释。\n"
        "每个 Slot 只能承载一个主要测量动作；只有当两个动作不能由同一道题的同一证据自然覆盖时，才拆成两个 Slot。\n"
        "只改变数字、单位、语境、选项位置或措辞不算新 Slot；不要把难度等级或题目变式误当作 Slot。\n"
        "每个 Slot 必须包含：slot_id、node_id、qf_id、task_type、response_mode、structure、measurement_target、conditions、error_targets、minimum_quality、reject_if。\n"
        "structure 必须说明未来 Brief 要实现的题面骨架和学生动作；measurement_target 必须能通过作答直接观察。\n"
        "conditions 必须写生成时不可违反的结构、参数关系、信息充分性和答案条件；error_targets 必须写可观察的错误分叉，不能只写‘粗心’或‘不会’。\n"
        "minimum_quality 必须写最低思考要求、必要证据和唯一性要求；reject_if 必须能拦截机械直算、答案一眼可见、无真实决策点、越界或答案不唯一。\n"
        "conditions、error_targets、minimum_quality、reject_if 必须是具体非空数组。不要写本次题目的具体数字、选项、答案或完整题干。\n"
        "输出前逐个确认：一个 Slot 只有一个主要动作，Brief 能据此直接构造题目，且没有把下游 Candidate 内容提前写入。输出必须是 Slot 对象数组；一个 Slot 对应一个 Brief 和一个 Candidate。\n"
        "只使用修订后的上游 QF；不要把旧 QF 中已被反馈判定为冲突的证据、答题形式或边界继续复制到 Slot。\n"
        + _revision_section(revision_context)
        + _json_section("Node", _production_node_input(node))
        + _json_section("QF", qf)
        + _json_section("已有 Slot（用于去重，不得复制）", previous_slots)
        + _json_section("上一次验证问题（重试时必须修复）", previous_validation_errors or [])
    )


def build_brief_prompt(node: dict[str, Any], qf: dict[str, Any], slot: dict[str, Any], *, previous_validation_errors: list[dict[str, Any] | str] | None = None) -> str:
    return (
        PRODUCTION_SYSTEM_PROMPT
        + "\n"
        + GENERATOR_COMMON_PROMPT
        + "\nSTAGE: BRIEF_GENERATION\n"
        + "\n本阶段任务：只把一个 Slot 实例化为一个 Brief。不要生成 Candidate，不要写孩子最终看到的完整题干、具体答案、具体选项或控件。\n"
        "把每一条 Slot 条件改写成生成器可执行的规则，并包含：brief_id、node_id、qf_id、slot_id、task、content_blueprint、construction、answer_contract、difficulty_contract、self_check。\n"
        "生成前先完成四件事：确定题面骨架；确定参数生成规则；确定学生必须完成的决策和错误分叉；确定答案如何由参数和步骤唯一推出。任何一件无法具体化，都不能提交 Brief。\n"
        "一个 Brief 只能选择一种题目机制：不得在同一 Brief 中让 Candidate 自由选择一元方程、估算、数量关系等不同载体；如果机制不同，必须由不同 Slot/Brief 承载。\n"
        "content_blueprint 是本 Brief 的实质命题蓝图，不是限制清单。必须具体写出：target_concept（本题要处理的数学对象/关系）、mechanism_type（唯一题目机制，例如 equation_substitution_check、unit_error_correction、object_mapping_explanation，不得写‘综合’或并列多个机制）、problem_mechanism（题目如何让该关系真正参与解题）、student_actions（学生要依次完成的有意义动作）、misconception_mechanism（错误答案如何暴露指定误解）、parameter_pattern（vary/must_hold/avoid 三组参数规则，以及按顺序执行的 generation_steps）、answer_derivation（从参数到答案的推导路径）、good_instance_pattern（什么样的实例才算有效）、bad_instance_pattern（什么样的实例即使格式正确也要淘汰）。\n"
        "content_blueprint 中不能只写‘考查理解’‘设置干扰项’‘保证有难度’；每一项都必须能让另一个模型据此生成同类但不同数字/语境的题。generation_steps 必须是有序的构造算法，例如先确定目标结构，再选满足关系的参数，再构造正确路径和错误分叉，最后验证唯一答案；不得只写‘随机生成’或‘适当选择’。\n"
        "construction.question_shape 必须是可实例化的题面模板，写清信息、变量/数值关系、题目字段和学生要完成的动作。construction 必须包含‘参数生成规则’：范围、关系、排除条件、合法性和避免过易/多解的条件；这些规则必须与 content_blueprint.parameter_pattern 一致。\n"
        "construction.required_decisions 必须是学生真正要做的判断、选择、建模或推理；construction.forbidden_shortcuts 必须说明具体哪些生成结果即使答案正确也要拒绝。\n"
        "对选择题必须规定正确选项的构造方法、干扰项的错误机制、互斥性和唯一正确集合；对填空题必须规定空的数量、每个空对应的答案推导和答案唯一性；对简答题必须规定过程证据、rubric 所需观察点和 solution_steps 的结构。\n"
        "必须额外生成 candidate_contract，作为 Candidate 的直接执行接口：response_mode 必须与 task.response_mode 一致；answer_encoding 只能是 choice_text（选择题答案使用 choices 中的完整文本）、field_text（填空按空逐项返回）或 response_text（简答题 answer 返回参考答案文本，孩子实际自由作答，由 rubric/solution_steps 支撑）；response_field_count 表示孩子实际填写/选择的作答字段数量，single_choice、multi_choice、short_answer 通常为1，fill_blank等于空的数量；reference_answer_count 表示 question-content.v1 的 answer 数组项数，多选题可大于1，不能与作答字段数混淆；field_mapping 必须明确 prompt、choices、answer、rubric、solution_steps 各自承载什么，不能只写‘映射到下游’；answer_requirements、choice_requirements、prompt_requirements 必须写清 Candidate 可直接执行的内容。\n"
        "不要在 answer_contract.answer_shape 中只写‘选项编号’这类与 Candidate JSON 冲突的描述；如果展示层最终使用编号，Candidate 仍必须按 question-content.v1 的 choices 文本编码答案。\n"
        "answer_contract 必须明确 fixed_answer 与 model_scored 的边界、答案形态、field_count 和判定依据；difficulty_contract 必须明确最低难度、真实决策点和不能通过模板反射完成的原因。\n"
        "self_check 必须逐条复核：参数合法、题面信息充分、答案可独立推导、答案唯一、错误分叉有效、难度达标、response_mode 可展示可判定、candidate_contract 与题面字段一致、response_field_count 与 reference_answer_count 各自含义正确、没有越界内容。\n"
        "不得删除、放宽或替换 Slot 条件。Brief 不能写本次 Candidate 的具体数字、具体选项、最终答案、完整题干或控件配置。只返回一个 Brief JSON 对象。\n"
        + _json_section("Node", _production_node_input(node))
        + _json_section("QF", qf)
        + _json_section("Slot", slot)
        + _json_section("上一次验证问题（重试时必须修复）", previous_validation_errors or [])
    )


def build_brief_v2_prompt(node: dict[str, Any], qf: dict[str, Any], slot: dict[str, Any], *, previous_validation_errors: list[dict[str, Any] | str] | None = None) -> str:
    return (
        PRODUCTION_SYSTEM_PROMPT
        + "\n"
        + GENERATOR_COMMON_PROMPT
        + "\nSTAGE: BRIEF_GENERATION_V2\n"
        + "\n本阶段只生成一个 brief-design.v2 Brief，不生成 Candidate。Brief v2 是一份可执行命题计划，不是限制条件清单。\n"
        + BRIEF_V2_AUTHORING_CONTRACT
        + "先从 Slot 提取唯一测量动作和证据，再设计一个能承载它的题目机制；不得为了增加难度叠加第二个核心机制。\n"
        + "mechanism 必须包含唯一 type、业务目的 purpose、有序 steps 和 completion_condition。每个 step 必须写清 input、student_action、output、success_condition；不能写‘完成计算’‘适当判断’等没有对象的空动作。\n"
        + "parameter_model 必须列出每个变量的 name、role、type、domain，补充 constraints 和有序 construction_steps。domain 必须包含可执行的类型/范围/关系；constraints 必须能验证；不能只写‘合理范围’。\n"
        + "parameter_model 必须先定义 task_variant（例如 pairwise_comparison 或 full_ordering）及其允许值；construction_steps 必须先选定一个变体，再规定该变体的题面动作、答案字段数量、答案顺序和验收条件。不能把‘比较或排序’留给 Candidate 临时决定。变量的 type 与 domain 必须一致：positive_integer 不能允许0，非负整数不能标成 positive_integer；涉及分数/小数时必须写清刻度、分母、有效小数位和精确定位之间的关系。\n"
        + "evidence_plan 必须逐项说明学生动作、可观察证据、承载它的 response_mode，以及是否必需；每项必须逐项标明它对应的 Slot measurement_target 和 error_targets。evidence_plan 中每项 required 证据都必须由当前 response_mode 直接采集：short_answer 只能声称能从学生文字中看到的内容，single_choice 只能依赖选择结果，fill_blank 只能依赖各空答案；题面本身的清晰性、点位、刻度等属于 Candidate 实例验收，不得伪装成学生行为证据。\n"
        + "answer_plan 必须说明 encoding、response_field_count、reference_answer_count、answer_evidence、solution_structure，并用 field_mapping 明确 prompt、choices、answer、rubric、solution_steps 的固定含义。answer 是参考答案数组，不是孩子提交的原始答案。\n"
        + "instance_acceptance 必须分别列出 must_hold、uniqueness_check、reject_if；它们必须能在生成一个具体 Candidate 后执行，不能只是‘质量高’‘难度合适’。must_hold 必须包含 Slot 的最低难度、全部必需测量动作和答案字段要求；必须至少有一个不能仅凭题面关键词、标签顺序、正负号口诀或直接抄写完成的真实决策，并明确如何验收。\n"
        + "response_mode 与机制和 evidence_plan 必须相容：需要解释/推导/修正时不能选择只承载选择集合的形式；不需要选择时 choices 的映射必须明确为固定空数组。\n"
        + "Brief 不能写本次 Candidate 的具体数值、具体答案或完整题干；参数只能写可变范围、变量关系和推导规则，最终数值、选项和答案留给 Candidate。不得自行增加 Slot 未要求的数量、字段或固定实例；若需要固定数量，必须能从 Slot 的结构直接推出。\n"
        + "只返回 brief-design.v2 JSON 对象，字段必须严格是：schema_version、brief_id、node_id、qf_id、slot_id、task、mechanism、parameter_model、evidence_plan、answer_plan、instance_acceptance。\n"
        + _json_section("Node", _production_node_input(node))
        + _json_section("QF", qf)
        + _json_section("Slot", slot)
        + _json_section("上一次验证问题（重试时必须修复）", previous_validation_errors or [])
    )


def _build_candidate_v2_instructions() -> str:
    return (
        "\n本阶段任务：严格根据一个 Brief v2 生成一道 Candidate。只生成一道，不生成第二道，不自行改变题型或降低难度。\n"
        "先读取 Brief v2 的 mechanism、parameter_model、evidence_plan、answer_plan 和 instance_acceptance。按 mechanism.steps 理解学生必须完成的数学动作，按 parameter_model.construction_steps 依次生成满足 constraints 的参数，按 evidence_plan 构造题面，并逐条执行 instance_acceptance 的验收。不得自行补充 Brief 没有授权的知识点、步骤、题型或难度变化。\n"
        "Candidate 必须体现 Brief 的数学机制和证据计划，而不是只套用表面格式；parameter_model 中的变量关系、evidence_plan 中的必需证据和 instance_acceptance.reject_if 都必须在本题中可观察、可复核。\n"
        "生成后必须完成双重独立复核：第一遍按正常解题过程推导答案，第二遍不看第一遍结论，重新检查题干、选项/空格、运算、单位、答案和 Brief 约束。两遍不一致时不得输出，必须在内部重生成。\n"
        "固定答案题必须独立算出唯一答案；简答题必须独立形成 solution_steps 和 rubric 所需的过程证据。答案必须从本题实际参数重新推出，不能把 Brief 中的描述当作本题答案。\n"
    )


def _build_candidate_v1_instructions() -> str:
    return (
        "\n本阶段任务：严格根据一个旧版 Brief 生成一道 Candidate。只生成一道，不生成第二道，不自行改变题型或降低难度。\n"
        "读取 content_blueprint、candidate_contract、construction、answer_contract、difficulty_contract 和 self_check；按参数模式生成满足约束且不命中拒绝条件的具体题目。不得自行补充 Brief 没有授权的知识点、步骤、题型或难度变化。\n"
        "生成后必须独立复核题干、选项/空格、答案、数学正确性、唯一性和 Brief 约束。\n"
    )


def build_candidate_prompt(brief: dict[str, Any], *, previous_validation_errors: list[dict[str, Any]] | list[str]) -> str:
    is_v2 = brief.get("schema_version") == "brief-design.v2"
    instructions = _build_candidate_v2_instructions() if is_v2 else _build_candidate_v1_instructions()
    interface_instructions = (
        "读取 answer_plan，把它当作 Candidate JSON 的直接接口：response_mode 必须一致；choice_text 时 answer 只能逐字引用 choices 文本；field_text 时 answer 必须按题面字段顺序逐项返回；response_text 时 answer 必须按 reference_answer_count 返回参考答案文本，孩子实际作答由 rubric/solution_steps 评分；answer 数量必须等于 reference_answer_count。response_field_count 只描述孩子端实际作答字段，不用来决定 answer 数组长度。\n"
        if is_v2
        else "读取 candidate_contract，把它当作 Candidate JSON 的直接接口：response_mode 必须一致；choice_text 时 answer 只能逐字引用 choices 文本；field_text 时 answer 必须按题面字段顺序逐项返回；response_text 时 answer 必须返回参考答案文本。\n"
    )
    self_check_instructions = (
        "提交前自检：题面可直接展示且不含内部指令；题目实现 mechanism 和 evidence_plan；参数满足 parameter_model.constraints；答案与本题参数推导一致；instance_acceptance 的拒绝条件均未命中；没有一眼可见答案、歧义、无解、多解、答案泄露或格式残留。\n"
        if is_v2
        else "提交前自检：题面可直接展示且不含内部指令；题目实现 content_blueprint；参数满足 Brief 约束；答案与参数推导一致；没有一眼可见答案、歧义、无解、多解、答案泄露或格式残留。\n"
    )
    return (
        PRODUCTION_SYSTEM_PROMPT
        + "\n"
        + GENERATOR_COMMON_PROMPT
        + "\nSTAGE: CANDIDATE_GENERATION\n"
        + instructions
        + interface_instructions
        + "生成后必须完成双重独立复核：第一遍按正常解题过程推导答案，第二遍不看第一遍结论，重新检查题干、选项/空格、运算、单位、答案和上游 Brief 约束。两遍不一致时不得输出，必须在内部重生成。\n"
        + "Candidate 内容只允许包含：schema_version、task_type、response_mode、prompt、choices、answer、rubric、solution_steps。固定答案题的 rubric 和 solution_steps 返回空数组；简答题必须返回非空数组。\n"
        "schema_version 必须是 question-content.v1；prompt 必须是孩子看到的完整题干；choices 和 answer 必须是字符串数组。\n"
        "孩子端题干和选项必须使用纯文本数学表示，不得出现美元符号、反斜杠或 LaTeX 命令（例如 \\frac）；分数请写成 a/b。\n"
        "禁止输出 candidate_id、node_id、qf_id、slot_id、brief_id、控件类型、字段 ID、选项 ID、interaction_schema、grading_mode、answer_contract、数据库字段或解释文字。\n"
        "填空题 choices 必须为空数组，prompt 中每个 ____ 对应 answer 中一个答案；单选/多选答案必须引用 choices 中的文本；简答题不得伪造固定选项答案，且必须提供非空 rubric 和 solution_steps。\n"
        + self_check_instructions
        + "如果这是重试，必须修复上一次验证错误，但不能破坏 Brief 中未出错的约束；如果 Brief 无法合法实例化，不得静默放宽 Brief。\n"
        + _json_section("Brief", brief)
        + _json_section("上一次验证错误", previous_validation_errors)
    )


_REVIEWER_COMMON_PROMPT = """你是独立的语义审查模型，不是生成模型。
你的职责是审查当前阶段产物，不是替生成模型修题。不得修改、补写、替换、重绑或代替产物输出新对象。
Node、父级对象和当前产物都是输入证据：不得把生成模型的自我声明当作事实，必须根据实际内容作独立判断。
只审查当前阶段职责；不要用下游对象应有的内容惩罚上游，也不要因为 QF 或 Slot 数量不是某个预设值而拒绝。
如果一次输入包含多个产物，必须逐个检查；只要有一个产物存在阻断性问题，整体 decision 就必须是 rejected，并在 issues 中指出对应 ID。
accepted 只能表示没有阻断当前阶段持久化或进入下一阶段的问题；score 只是质量概括，不能替代问题判断。
issues 必须写具体事实和影响，不能只写“质量不高”；repair_instructions 必须能直接指导当前阶段重新生成，不能要求审查模型自己修复。
只返回 semantic-review.v1 对象：decision、0 到 10 的 score、issues、repair_instructions、root_cause_stage、recovery_action、recovery_stage、confidence。不要返回 markdown、解释文字或其它字段。
拒绝时必须定位根因所在层，而不是只重复当前阶段：root_cause_stage 可以是当前层或任一上游层；若问题只需当前层重新生成，recovery_action=retry_current_stage 且 recovery_stage=当前层；若必须回退，recovery_action=regenerate_from_stage 且 recovery_stage=根因层；若是合同或流程本身冲突，使用 stop_and_fix_contract 和 pipeline_contract。这里的 recovery_action 是给后续复盘/人工修订的建议，不是当前 Run 的自动执行命令；Orchestrator 不会自动回退 QF、Slot 或 Brief。accepted 时三个恢复字段分别使用 none，并给出对判断的置信度。
"""


def _build_layer_review_prompt(
    stage: str,
    responsibility: str,
    checklist: list[str],
    payload: dict[str, Any],
    output: list[dict[str, Any]],
) -> str:
    checklist_text = "\n".join(f"{index}. {item}" for index, item in enumerate(checklist, 1))
    return (
        REVIEWER_SYSTEM_PROMPT
        + "\n"
        + _REVIEWER_COMMON_PROMPT
        + f"\nSTAGE: {stage.upper()}_SEMANTIC_REVIEW\n"
        + f"\n{responsibility}\n"
        + "\n本层必须逐项检查：\n"
        + checklist_text
        + "\n\n审查边界：只依据下方输入和产物审查，不自行引入未提供的教材、题库或数量要求。\n"
        + _json_section("生成阶段", stage)
        + _json_section("输入上下文", payload)
        + _json_section("待审查产物", output)
    )


def build_qf_semantic_review_prompt(payload: dict[str, Any], output: list[dict[str, Any]]) -> str:
    return _build_layer_review_prompt(
        "qf_design",
        "QF 专属审查：判断这些 QF 是否把 Node 拆成了互相独立、值得单独测量的能力家族，而不是判断它们能不能直接出成一道题。",
        [
            "每个 QF 是否只对应一种独立核心能力；如果两个 QF 只换题型、数字、语境或措辞就能互相替代，拒绝重复者。",
            "每个 QF 是否确实属于当前 Node，scope 是否清楚，是否越过 Node 边界或把前置知识当成主测能力。",
            "task_type、allowed_response_modes 与 measurement_intent 是否一致；不得包含判断题或无法支持的答题形式。",
            "QF 是否停留在家族层：不得把某一道题的数字、完整题干、具体选项、答案或单个 Slot 的步骤写成 QF 定义。",
            "required_evidence 和 reject_if 是否表达家族级目标；若已经细化成某道题的操作步骤、证据字段或参数模板，拒绝下沉过度。",
            "独立性理由是否足够说明为什么需要这个 QF，而不是为了凑数量拆分 Node。",
        ],
        payload,
        output,
    )


def build_slot_semantic_review_prompt(payload: dict[str, Any], output: list[dict[str, Any]]) -> str:
    return _build_layer_review_prompt(
        "slot_design",
        "Slot 专属审查：判断每个 Slot 是否把一个 QF 变成了不可互相替代的具体测量动作，并能被下游 Brief 执行。",
        [
            "每个 Slot 是否绑定当前 QF，且测量动作是否直接服务于 QF 的独立能力；不能只是换数字、单位、语境、选项或措辞。",
            "structure、conditions、measurement_target 是否足够具体，让 Brief 能知道题面骨架、孩子必须做什么和必须满足什么条件。",
            "error_targets 是否对应可观察的典型错误或认知分叉，而不是泛泛写‘粗心’‘不会’。",
            "response_mode 与 task_type 是否可执行且符合当前 QF；不得出现判断题或无法判定的答案形态。",
            "Slot 是否仍停留在结构层：不得写本次题目的具体数字、最终答案、完整题干、选项或唯一实例。",
            "minimum_quality 和 reject_if 是否能拦截机械直算、答案一眼可见、无真实决策点或答案不唯一的题。",
        ],
        payload,
        output,
    )


def build_brief_semantic_review_prompt(payload: dict[str, Any], output: list[dict[str, Any]]) -> str:
    is_v2 = bool(output) and all(
        isinstance(item, dict) and item.get("schema_version") == "brief-design.v2"
        for item in output
    )
    if is_v2:
        checklist = [
            "每个 Brief 是否只绑定一个 Slot，且 mechanism、parameter_model、evidence_plan、answer_plan、instance_acceptance 五个块都围绕该 Slot 的一个测量动作展开；不得增加第二个核心机制或改变 Node/QF/Slot 绑定。",
            "mechanism.type 是否是唯一、具体、可执行的数学机制；purpose、steps 和 completion_condition 是否说明学生要处理的对象、动作、输出及完成条件，而不是‘综合’‘适当判断’等空话。",
            "parameter_model.variables 是否为每个变量给出 name、role、type、domain；constraints 和有序 construction_steps 是否足以生成合法实例，并且没有把具体 Candidate 数字、答案或完整题干写死。",
            "evidence_plan.items 是否逐项对应 Slot 的 measurement_target 和 error_targets，并明确 student_action、observable_evidence、capture_mode、required；每项证据是否能在 Candidate 的题面和答题结果中观察到。",
            "answer_plan 是否明确 encoding、response_field_count、reference_answer_count、field_mapping、answer_evidence 和 solution_structure；encoding 是否与 task.response_mode 一致，且 field_mapping 能直接映射 Candidate 的 prompt、choices、answer、rubric、solution_steps。",
            "instance_acceptance.must_hold、uniqueness_check、reject_if 是否是针对具体实例可执行的验收条件，能够检查信息充分、数学可解、答案唯一、难度和禁止捷径；不能只写‘质量高’或‘难度适中’。",
            "Brief 是否仍停留在构造计划层：不得输出具体 Candidate 数字、具体选项、最终答案、完整题干、控件配置或数据库字段。",
        ]
        return _build_layer_review_prompt(
            "brief_generation",
            "Brief v2 专属审查：判断这个 Brief 是否已经把一个 Slot 转成一份可执行、可验收、可直接驱动 Candidate 的命题计划。只依据 Brief v2 合同审查，不要求旧版字段。",
            [BRIEF_V2_AUTHORING_CONTRACT, *checklist],
            payload,
            output,
        )
    return _build_layer_review_prompt(
        "brief_generation",
        "旧版 Brief 专属审查：判断这个 Brief 是否已经把一个 Slot 转成一次可执行构造指令，并能产出可复核、不会漂移的 Candidate。",
        [
            "brief 是否只绑定一个 Slot，且逐条落实 Slot 的结构、条件、测量目标、错误目标和拒绝条件；不得删除或放宽上游约束。",
            "content_blueprint 是否提供了具体的 target_concept、problem_mechanism、student_actions 和 misconception_mechanism；这些内容是否描述真实数学机制，而不是‘考查理解’之类空话。",
            "content_blueprint.parameter_pattern 是否同时说明 vary、must_hold、avoid 和有序 generation_steps；generation_steps 是否足以让另一个模型稳定构造合法实例，而不是随机或适当选择。",
            "content_blueprint.answer_derivation 是否能从生成参数独立推出答案；good_instance_pattern 和 bad_instance_pattern 是否能区分有效命题实例与格式正确但无测量价值的实例。",
            "question_shape 是否给出完整题面骨架，construction 是否明确参数边界、变量关系、数量范围和生成步骤，而不是抽象口号。",
            "required_decisions 是否列出孩子必须真正做出的判断、选择、建模或推理；不得把单步机械计算伪装成思考。",
            "forbidden_shortcuts 是否具体说明哪些生成结果要拒绝，例如答案一眼可见、只需套公式、没有真实干扰项或无需使用目标能力。",
            "answer_contract 是否明确固定答案与简答题评分的边界、答案形态、空的数量或评分依据，且与 response_mode 一致。",
            "candidate_contract 是否与 task.response_mode 一致，answer_encoding 是否能直接映射到 question-content.v1 的 choices、answer、rubric 和 solution_steps；不得出现‘选项编号’与‘选项文本’冲突。",
            "difficulty_contract 和 self_check 是否可执行，能检查最低难度、数学可解性、答案唯一性和题面完整性，而不是只写‘难度适中’。",
            "Brief 是否没有越界成为最终题干、具体答案、具体选项或控件配置。",
        ],
        payload,
        output,
    )


def build_candidate_semantic_review_prompt(payload: dict[str, Any], output: list[dict[str, Any]]) -> str:
    return _build_layer_review_prompt(
        "candidate_generation",
        "Candidate 专属审查：判断孩子实际看到的这一道题是否正确、可展示、可回答、可判定，并忠实实现 Brief 的目标。",
        [
            "独立重做题目并独立复核答案；检查题干、选项、空格、答案、单位和计算过程是否数学正确，不能信任 Candidate 自带答案。",
            "题目是否严格实现 Brief 的结构、参数边界、决策点和错误分叉；不得擅自换题型、降低难度或漏掉关键动作。",
            "题目是否真正测量 Node/QF/Slot 的目标能力，而不是只做一步直接计算、背诵或一眼可见的表面识别。",
            "单选/多选的选项是否互斥、无重复且存在唯一正确集合；填空的空数是否与答案对应且答案唯一；简答题是否有足够过程证据。",
            "prompt 是否是孩子可直接理解的完整题面，不含内部元数据、生成指令、控件配置、LaTeX 或不可渲染表达。",
            "是否存在歧义、信息不足、无解、多解、答案不在选项中、选项泄露答案或不必要的阅读/书写负担。",
        ],
        payload,
        output,
    )


_SEMANTIC_REVIEW_PROMPT_BUILDERS: dict[str, Callable[[dict[str, Any], list[dict[str, Any]]], str]] = {
    "qf_design": build_qf_semantic_review_prompt,
    "slot_design": build_slot_semantic_review_prompt,
    "brief_generation": build_brief_semantic_review_prompt,
    "candidate_generation": build_candidate_semantic_review_prompt,
}


def build_semantic_review_prompt(stage: str, payload: dict[str, Any], output: list[dict[str, Any]]) -> str:
    """Build the layer-specific semantic review prompt behind the stable public API."""
    try:
        builder = _SEMANTIC_REVIEW_PROMPT_BUILDERS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown semantic review stage: {stage}") from exc
    return builder(payload, output)


def build_model_question_production_skills(model: Any, reviewers: dict[str, Reviewer] | None = None) -> dict[str, ProductionSkill]:
    """Build four Skills around a provider exposing generate_json(prompt, schema)."""

    if not callable(getattr(model, "generate_json", None)):
        raise TypeError("model must provide generate_json(prompt, schema)")

    def generate_qf(payload: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        node = payload.get("node") or payload
        return model.generate_json(build_qf_prompt(node, previous_qfs=payload.get("previous_qfs") or [], previous_validation_errors=payload.get("previous_validation_errors") or [], revision_context=payload.get("revision_context")), "qf-design.v1")

    def generate_slot(payload: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        node = payload.get("node") or {"id": payload.get("node_id", "")}
        qf = payload.get("qf") or payload
        return model.generate_json(build_slot_prompt(node, qf, previous_slots=payload.get("previous_slots") or [], previous_validation_errors=payload.get("previous_validation_errors") or [], revision_context=payload.get("revision_context")), "slot-design.v1")

    def generate_brief(payload: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        node = payload.get("node") or {"id": payload.get("node_id", "")}
        qf = payload.get("qf") or payload
        slot = payload.get("slot") or payload
        return model.generate_json(build_brief_v2_prompt(node, qf, slot, previous_validation_errors=payload.get("previous_validation_errors") or []), "brief-design.v2")

    def generate_candidate(payload: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        brief = payload.get("brief") or payload
        return model.generate_json(build_candidate_prompt(brief, previous_validation_errors=payload.get("previous_validation_errors") or []), "question-content.v1")

    return build_question_production_skills({
        "qf_design": generate_qf,
        "slot_design": generate_slot,
        "brief_generation": generate_brief,
        "candidate_generation": generate_candidate,
    }, reviewers=reviewers)


class ModelRouterQuestionProductionModel:
    """Live provider adapter; all network calls go through the shared router."""

    def __init__(self, *, question_route: Any | None = None, design_route: Any | None = None, reviewer_routes: dict[str, Any] | None = None):
        local_env.load_local_env_file()
        self.question_route = question_route or model_router.question_designer_route()
        self.design_route = design_route or model_router.slot_brief_designer_route()
        self.reviewer_routes = reviewer_routes or {
            "qf_design": model_router.qf_reviewer_route(),
            "slot_design": model_router.slot_reviewer_route(),
            "brief_generation": model_router.brief_reviewer_route(),
            "candidate_generation": model_router.candidate_reviewer_route(),
        }

    def generate_json(self, prompt: str, schema_id: str) -> dict[str, Any]:
        schema = LIVE_SCHEMAS.get(schema_id)
        if schema is None:
            raise ValueError(f"unknown question production schema: {schema_id}")
        route = self.question_route if schema_id == "question-content.v1" else self.design_route
        if not route.enabled:
            raise RuntimeError(f"model route is not configured for {schema_id}")
        result = model_router.call_structured_json(
            route,
            {
                "instructions": (
                    "Return exactly one JSON object matching the supplied schema. "
                    "Do not return markdown, explanations, or fields outside the schema."
                ),
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "temperature": 0,
            },
            schema=schema,
            plain_json_instruction="Return only one valid JSON object matching the schema.",
            provider_idempotency_key=_prompt_digest(prompt, schema_id),
        )
        value = result.value
        if schema_id == "qf-design.v1":
            return {"_items": value["qfs"]}
        if schema_id == "slot-design.v1":
            return {"_items": value["slots"]}
        return value

    def review_json(self, stage: str, prompt: str) -> dict[str, Any]:
        route = self.reviewer_routes[stage]
        if not route.enabled:
            raise RuntimeError(f"semantic reviewer route is not configured for {stage}")
        result = model_router.call_structured_json(
            route,
            {
                "instructions": "Return exactly one JSON object matching semantic-review.v1. Do not return markdown or explanations.",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "temperature": 0,
            },
            schema=LIVE_SCHEMAS["semantic-review.v1"],
            plain_json_instruction="Return only one semantic-review.v1 JSON object.",
            provider_idempotency_key=_prompt_digest(prompt, "semantic-review.v1"),
        )
        return result.value


def _prompt_digest(prompt: str, schema_id: str) -> str:
    payload = json.dumps({"schema_id": schema_id, "prompt": prompt}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_live_question_production_skills() -> dict[str, ProductionSkill]:
    """Build production Skills backed by the configured real model routes."""

    model = ModelRouterQuestionProductionModel()

    def unwrap(payload: dict[str, Any], schema_id: str) -> dict[str, Any] | list[dict[str, Any]]:
        value = model.generate_json(payload["prompt"], schema_id)
        return value.get("_items", value) if isinstance(value, dict) else value

    def semantic_reviewer(stage: str) -> Reviewer:
        def review(payload: dict[str, Any], output: list[dict[str, Any]]) -> dict[str, Any]:
            return model.review_json(stage, build_semantic_review_prompt(stage, payload, output))
        return review

    return build_question_production_skills({
        "qf_design": lambda payload: unwrap({"prompt": build_qf_prompt(payload.get("node") or payload, previous_qfs=payload.get("previous_qfs") or [], previous_validation_errors=payload.get("previous_validation_errors") or [], revision_context=payload.get("revision_context"))}, "qf-design.v1"),
        "slot_design": lambda payload: unwrap({"prompt": build_slot_prompt(payload.get("node") or payload, payload.get("qf") or payload, previous_slots=payload.get("previous_slots") or [], previous_validation_errors=payload.get("previous_validation_errors") or [], revision_context=payload.get("revision_context"))}, "slot-design.v1"),
        "brief_generation": lambda payload: unwrap({"prompt": build_brief_v2_prompt(payload.get("node") or payload, payload.get("qf") or payload, payload.get("slot") or payload, previous_validation_errors=payload.get("previous_validation_errors") or [])}, "brief-design.v2"),
        "candidate_generation": lambda payload: unwrap({"prompt": build_candidate_prompt(payload.get("brief") or payload, previous_validation_errors=payload.get("previous_validation_errors") or [])}, "question-content.v1"),
    }, reviewers={stage: semantic_reviewer(stage) for stage in STAGES})


def _error(code: str, message: str, repair_hint: str = "") -> dict[str, Any]:
    result = {"code": code, "message": message, "severity": "error"}
    if repair_hint:
        result["repair_hint"] = repair_hint
    return result


def _as_items(value: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else [value]
    if not items or any(not isinstance(item, dict) for item in items):
        raise ValueError("skill generator must return a non-empty object list")
    return items


class ProductionSkill:
    stage: str
    target_stage: str

    def __init__(self, generator: Generator, validator: Validator, reviewer: Reviewer | None = None, review_validator: ReviewValidator | None = None):
        self.generator = generator
        self.validator = validator
        self.reviewer = reviewer
        self.review_validator = review_validator or validate_semantic_review

    def run(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return _as_items(self.generator(payload))

    def validate(self, payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
        return self.validator(payload, output)

    def review(self, payload: dict[str, Any], output: list[dict[str, Any]]) -> dict[str, Any]:
        if self.reviewer is None:
            return {
                "decision": "accepted",
                "score": 0,
                "issues": [],
                "repair_instructions": [],
                "root_cause_stage": "none",
                "recovery_action": "none",
                "recovery_stage": "none",
                "confidence": 0,
                "provider_mode": "not_configured",
            }
        return self.reviewer(payload, output)

    def validate_review(self, payload: dict[str, Any], output: list[dict[str, Any]], review: dict[str, Any]) -> ValidationResult:
        return self.review_validator(payload, output, review)

    @property
    def semantic_reviewer_configured(self) -> bool:
        return callable(self.reviewer)


class QFDesignSkill(ProductionSkill):
    stage = "qf_design"
    target_stage = "qf_design"

    def __init__(self, generator: Generator, reviewer: Reviewer | None = None):
        super().__init__(generator, validate_qf, reviewer)


class SlotDesignSkill(ProductionSkill):
    stage = "slot_design"
    target_stage = "slot_design"

    def __init__(self, generator: Generator, reviewer: Reviewer | None = None):
        super().__init__(generator, validate_slot, reviewer)


class BriefGenerationSkill(ProductionSkill):
    stage = "brief_generation"
    target_stage = "brief_generation"

    def __init__(self, generator: Generator, reviewer: Reviewer | None = None):
        super().__init__(generator, validate_brief, reviewer)


class CandidateGenerationSkill(ProductionSkill):
    stage = "candidate_generation"
    target_stage = "candidate_generation"

    def __init__(self, generator: Generator, reviewer: Reviewer | None = None):
        super().__init__(generator, validate_candidate, reviewer)


def validate_semantic_review(payload: dict[str, Any], output: list[dict[str, Any]], review: dict[str, Any]) -> ValidationResult:
    errors: list[dict[str, Any]] = []
    if review.get("decision") not in {"accepted", "rejected"}:
        errors.append(_error("semantic_review_decision_invalid", "语义审查 decision 必须是 accepted 或 rejected"))
    score = review.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 10:
        errors.append(_error("semantic_review_score_invalid", "语义审查 score 必须在 0 到 10 之间"))
    for name in ("issues", "repair_instructions"):
        if not isinstance(review.get(name), list) or any(not isinstance(item, str) or not item.strip() for item in review[name]):
            errors.append(_error(f"semantic_review_{name}_invalid", f"语义审查 {name} 必须是字符串数组"))
    if review.get("decision") == "rejected" and not review.get("issues"):
        errors.append(_error("semantic_review_issues_missing", "拒绝时必须说明语义问题"))
    review_stages = set(STAGES) | {"pipeline_contract", "none"}
    if review.get("root_cause_stage") not in review_stages:
        errors.append(_error("semantic_review_root_cause_stage_invalid", "语义审查 root_cause_stage 不合法"))
    recovery_actions = {"retry_current_stage", "regenerate_from_stage", "stop_and_fix_contract", "none"}
    if review.get("recovery_action") not in recovery_actions:
        errors.append(_error("semantic_review_recovery_action_invalid", "语义审查 recovery_action 不合法"))
    if review.get("recovery_stage") not in review_stages:
        errors.append(_error("semantic_review_recovery_stage_invalid", "语义审查 recovery_stage 不合法"))
    confidence = review.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        errors.append(_error("semantic_review_confidence_invalid", "语义审查 confidence 必须在 0 到 1 之间"))
    current_stage = payload.get("stage")
    if review.get("decision") == "accepted":
        if any(review.get(field) != "none" for field in ("root_cause_stage", "recovery_action", "recovery_stage")):
            errors.append(_error("semantic_review_accepted_recovery_fields_invalid", "accepted 时恢复字段必须全部为 none"))
    elif review.get("decision") == "rejected":
        root_cause_stage = review.get("root_cause_stage")
        action = review.get("recovery_action")
        recovery_stage = review.get("recovery_stage")
        if root_cause_stage == "none":
            errors.append(_error("semantic_review_root_cause_stage_missing", "拒绝时必须定位根因阶段"))
        if action == "none":
            errors.append(_error("semantic_review_recovery_action_missing", "拒绝时必须指定恢复动作"))
        if action != "stop_and_fix_contract" and recovery_stage == "none":
            errors.append(_error("semantic_review_recovery_stage_missing", "拒绝时必须指定恢复阶段"))
        if action == "retry_current_stage" and recovery_stage != current_stage:
            errors.append(_error("semantic_review_recovery_stage_invalid", "retry_current_stage 必须指向当前阶段"))
        if action == "regenerate_from_stage":
            if recovery_stage not in STAGES or current_stage not in STAGES or STAGES.index(recovery_stage) > STAGES.index(current_stage):
                errors.append(_error("semantic_review_recovery_stage_invalid", "regenerate_from_stage 只能指向当前阶段或上游阶段"))
        if action == "stop_and_fix_contract" and recovery_stage != "pipeline_contract":
            errors.append(_error("semantic_review_recovery_stage_invalid", "stop_and_fix_contract 必须指向 pipeline_contract"))
    if errors:
        return _result(errors, "semantic_review")
    if review["decision"] == "rejected":
        return ValidationResult.rejected(
            [_error("semantic_review_rejected", "语义 Reviewer 拒绝产物", "；".join(review["repair_instructions"]))],
            target_stage=(review.get("recovery_stage") if review.get("recovery_action") == "regenerate_from_stage" else payload.get("stage")),
            reason="语义 Reviewer 判定产物不可持久化",
        )
    return ValidationResult.passed()


def validate_qf(payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
    errors = []
    if not output.get("qf_id"):
        errors.append(_error("qf_id_missing", "QF 必须有 qf_id"))
    if output.get("node_id") != payload.get("node_id"):
        errors.append(_error("qf_node_id_mismatch", "QF 必须绑定输入 Node"))
    for field_name in ("name", "task_type", "measurement_intent", "independent_reason"):
        if not str(output.get(field_name) or "").strip():
            errors.append(_error(f"qf_{field_name}_missing", f"QF 缺少 {field_name}"))
    modes = output.get("allowed_response_modes")
    if not isinstance(modes, list) or not modes or any(mode not in RESPONSE_MODES for mode in modes):
        errors.append(_error("qf_response_modes_invalid", "QF 的 allowed_response_modes 不合法"))
    for field_name in ("scope", "required_evidence", "reject_if"):
        if field_name not in output:
            errors.append(_error(f"qf_{field_name}_missing", f"QF 缺少 {field_name}"))
    return _result(errors, "qf_design")


def validate_slot(payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
    errors = []
    if not output.get("slot_id"):
        errors.append(_error("slot_id_missing", "Slot 必须有 slot_id"))
    if output.get("node_id") != payload.get("node_id"):
        errors.append(_error("slot_node_id_mismatch", "Slot 必须绑定输入 Node"))
    if output.get("qf_id") != payload.get("qf_id"):
        errors.append(_error("slot_qf_id_mismatch", "Slot 必须绑定输入 QF"))
    for field_name in ("task_type", "response_mode", "structure", "measurement_target"):
        if not str(output.get(field_name) or "").strip():
            errors.append(_error(f"slot_{field_name}_missing", f"Slot 缺少 {field_name}"))
    if output.get("response_mode") not in RESPONSE_MODES:
        errors.append(_error("slot_response_mode_invalid", "Slot 的 response_mode 不合法"))
    for field_name in ("conditions", "error_targets", "minimum_quality", "reject_if"):
        if not isinstance(output.get(field_name), list) or not output[field_name]:
            errors.append(_error(f"slot_{field_name}_invalid", f"Slot 的 {field_name} 必须是非空数组"))
    return _result(errors, "slot_design")


def _validate_brief_v2(payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
    errors: list[dict[str, Any]] = []
    if output.get("schema_version") != "brief-design.v2":
        errors.append(_error("brief_v2_schema_version_invalid", "Brief v2 的 schema_version 不正确"))
    for field_name, expected in (("node_id", "node_id"), ("qf_id", "qf_id"), ("slot_id", "slot_id")):
        if output.get(field_name) != payload.get(expected):
            errors.append(_error(f"brief_v2_{field_name}_mismatch", f"Brief v2 必须绑定输入 {field_name}"))
    if not str(output.get("brief_id") or "").strip():
        errors.append(_error("brief_v2_brief_id_missing", "Brief v2 必须有 brief_id"))
    task = output.get("task")
    if not isinstance(task, dict) or not str(task.get("task_type") or "").strip() or task.get("response_mode") not in RESPONSE_MODES:
        errors.append(_error("brief_v2_task_invalid", "Brief v2 的 task 合同不完整"))
    mechanism = output.get("mechanism")
    if not isinstance(mechanism, dict):
        errors.append(_error("brief_v2_mechanism_missing", "Brief v2 必须包含 mechanism"))
    else:
        mechanism_type = mechanism.get("type")
        if not isinstance(mechanism_type, str) or not mechanism_type.strip() or any(token in mechanism_type for token in ("或", "、", "/", "综合")):
            errors.append(_error("brief_v2_mechanism_type_invalid", "Brief v2 必须声明一个唯一机制"))
        for field_name in ("purpose", "completion_condition"):
            if not isinstance(mechanism.get(field_name), str) or not mechanism[field_name].strip():
                errors.append(_error(f"brief_v2_mechanism_{field_name}_invalid", f"mechanism.{field_name} 必须是非空说明"))
        steps = mechanism.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(_error("brief_v2_mechanism_steps_invalid", "mechanism.steps 必须是非空步骤数组"))
        else:
            step_ids: set[str] = set()
            for step in steps:
                if not isinstance(step, dict):
                    errors.append(_error("brief_v2_mechanism_step_invalid", "mechanism.steps 中每项必须是对象"))
                    continue
                step_id = str(step.get("id") or "").strip()
                if not step_id or step_id in step_ids:
                    errors.append(_error("brief_v2_mechanism_step_id_invalid", "mechanism.steps 的 id 必须非空且唯一"))
                step_ids.add(step_id)
                for field_name in ("purpose", "input", "student_action", "output", "success_condition"):
                    if not isinstance(step.get(field_name), str) or not step[field_name].strip():
                        errors.append(_error(f"brief_v2_mechanism_step_{field_name}_invalid", f"机制步骤缺少具体 {field_name}"))
    parameter_model = output.get("parameter_model")
    if not isinstance(parameter_model, dict):
        errors.append(_error("brief_v2_parameter_model_missing", "Brief v2 必须包含 parameter_model"))
    else:
        variables = parameter_model.get("variables")
        if not isinstance(variables, list) or not variables:
            errors.append(_error("brief_v2_variables_invalid", "parameter_model.variables 必须是非空数组"))
        else:
            names: set[str] = set()
            for variable in variables:
                if not isinstance(variable, dict):
                    errors.append(_error("brief_v2_variable_invalid", "parameter_model.variables 中每项必须是对象"))
                    continue
                name = str(variable.get("name") or "").strip()
                if not name or name in names:
                    errors.append(_error("brief_v2_variable_name_invalid", "参数变量 name 必须非空且唯一"))
                names.add(name)
                for field_name in ("role", "type", "domain"):
                    if not isinstance(variable.get(field_name), str) or not variable[field_name].strip():
                        errors.append(_error(f"brief_v2_variable_{field_name}_invalid", f"参数变量缺少具体 {field_name}"))
            if "task_variant" not in names:
                errors.append(_error("brief_v2_task_variant_missing", "parameter_model.variables 必须声明唯一 task_variant"))
        for field_name in ("constraints", "construction_steps"):
            if not isinstance(parameter_model.get(field_name), list) or not parameter_model[field_name]:
                errors.append(_error(f"brief_v2_parameter_{field_name}_invalid", f"parameter_model.{field_name} 必须是非空数组"))
    evidence_plan = output.get("evidence_plan")
    if not isinstance(evidence_plan, dict) or not isinstance(evidence_plan.get("items"), list) or not evidence_plan["items"]:
        errors.append(_error("brief_v2_evidence_plan_invalid", "evidence_plan.items 必须是非空数组"))
    else:
        for item in evidence_plan["items"]:
            if not isinstance(item, dict):
                errors.append(_error("brief_v2_evidence_item_invalid", "evidence_plan.items 中每项必须是对象"))
                continue
            for field_name in ("evidence_id", "student_action", "observable_evidence"):
                if not isinstance(item.get(field_name), str) or not item[field_name].strip():
                    errors.append(_error(f"brief_v2_evidence_{field_name}_invalid", f"证据项缺少具体 {field_name}"))
            if item.get("capture_mode") not in RESPONSE_MODES or not isinstance(item.get("required"), bool):
                errors.append(_error("brief_v2_evidence_capture_invalid", "证据项 capture_mode/required 不合法"))
            elif item.get("required") and isinstance(task, dict) and item.get("capture_mode") != task.get("response_mode"):
                errors.append(_error("brief_v2_evidence_capture_mode_mismatch", "required evidence 的 capture_mode 必须与 task.response_mode 一致"))
    answer_plan = output.get("answer_plan")
    if not isinstance(answer_plan, dict):
        errors.append(_error("brief_v2_answer_plan_missing", "Brief v2 必须包含 answer_plan"))
    else:
        response_mode = task.get("response_mode") if isinstance(task, dict) else None
        expected_encoding = {"single_choice": "choice_text", "multi_choice": "choice_text", "fill_blank": "field_text", "short_answer": "response_text"}.get(response_mode)
        if answer_plan.get("encoding") != expected_encoding:
            errors.append(_error("brief_v2_answer_encoding_invalid", "answer_plan.encoding 与 response_mode 不一致"))
        for field_name in ("response_field_count", "reference_answer_count"):
            if not isinstance(answer_plan.get(field_name), int) or isinstance(answer_plan.get(field_name), bool) or answer_plan[field_name] < 1:
                errors.append(_error(f"brief_v2_{field_name}_invalid", f"answer_plan.{field_name} 必须是正整数"))
        mapping = answer_plan.get("field_mapping")
        if not isinstance(mapping, dict):
            errors.append(_error("brief_v2_field_mapping_invalid", "answer_plan.field_mapping 必须说明五个下游字段"))
        else:
            for field_name in ("prompt", "choices", "answer", "rubric", "solution_steps"):
                if not isinstance(mapping.get(field_name), str) or not mapping[field_name].strip():
                    errors.append(_error(f"brief_v2_field_mapping_{field_name}_invalid", f"field_mapping.{field_name} 必须是非空说明"))
        for field_name in ("answer_evidence", "solution_structure"):
            if not isinstance(answer_plan.get(field_name), list) or not answer_plan[field_name]:
                errors.append(_error(f"brief_v2_answer_{field_name}_invalid", f"answer_plan.{field_name} 必须是非空数组"))
    acceptance = output.get("instance_acceptance")
    if not isinstance(acceptance, dict):
        errors.append(_error("brief_v2_instance_acceptance_missing", "Brief v2 必须包含 instance_acceptance"))
    else:
        for field_name in ("must_hold", "uniqueness_check", "reject_if"):
            if not isinstance(acceptance.get(field_name), list) or not acceptance[field_name]:
                errors.append(_error(f"brief_v2_acceptance_{field_name}_invalid", f"instance_acceptance.{field_name} 必须是非空数组"))
    if errors:
        return _result(errors, "brief_generation")
    return ValidationResult.passed()


def validate_brief(payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
    if output.get("schema_version") == "brief-design.v2":
        return _validate_brief_v2(payload, output)
    errors = []
    if not output.get("brief_id"):
        errors.append(_error("brief_id_missing", "Brief 必须有 brief_id"))
    if output.get("node_id") != payload.get("node_id"):
        errors.append(_error("brief_node_id_mismatch", "Brief 必须绑定输入 Node"))
    if output.get("qf_id") != payload.get("qf_id"):
        errors.append(_error("brief_qf_id_mismatch", "Brief 必须绑定输入 QF"))
    if output.get("slot_id") != payload.get("slot_id"):
        errors.append(_error("brief_slot_id_mismatch", "Brief 必须绑定输入 Slot"))
    task = output.get("task")
    if not isinstance(task, dict) or task.get("response_mode") not in RESPONSE_MODES or not task.get("task_type"):
        errors.append(_error("brief_task_invalid", "Brief 的 task 合同不完整"))
    blueprint = output.get("content_blueprint")
    if not isinstance(blueprint, dict):
        errors.append(_error("brief_content_blueprint_missing", "Brief 必须包含实质命题蓝图 content_blueprint"))
    else:
        for field_name in (
            "target_concept",
            "mechanism_type",
            "problem_mechanism",
            "misconception_mechanism",
            "answer_derivation",
            "good_instance_pattern",
            "bad_instance_pattern",
        ):
            if not isinstance(blueprint.get(field_name), str) or not blueprint[field_name].strip():
                errors.append(_error(f"brief_blueprint_{field_name}_invalid", f"命题蓝图缺少具体 {field_name}"))
        if not isinstance(blueprint.get("student_actions"), list) or not blueprint["student_actions"]:
            errors.append(_error("brief_blueprint_student_actions_invalid", "命题蓝图必须包含非空 student_actions"))
        parameter_pattern = blueprint.get("parameter_pattern")
        if not isinstance(parameter_pattern, dict):
            errors.append(_error("brief_blueprint_parameter_pattern_invalid", "命题蓝图必须包含 parameter_pattern"))
        else:
            for field_name in ("vary", "must_hold", "avoid", "generation_steps"):
                if not isinstance(parameter_pattern.get(field_name), list) or not parameter_pattern[field_name]:
                    errors.append(_error(f"brief_blueprint_parameter_{field_name}_invalid", f"parameter_pattern.{field_name} 必须是非空数组"))
    candidate_contract = output.get("candidate_contract")
    if not isinstance(candidate_contract, dict):
        errors.append(_error("brief_candidate_contract_missing", "Brief 必须包含 Candidate 直接执行合同 candidate_contract"))
    else:
        response_mode = task.get("response_mode") if isinstance(task, dict) else None
        if candidate_contract.get("response_mode") != response_mode:
            errors.append(_error("brief_candidate_contract_response_mode_mismatch", "candidate_contract.response_mode 必须与 task.response_mode 一致"))
        if candidate_contract.get("answer_encoding") == "choice_text" and response_mode not in {"single_choice", "multi_choice"}:
            errors.append(_error("brief_candidate_contract_answer_encoding_invalid", "choice_text 只能用于单选或多选"))
        if candidate_contract.get("answer_encoding") == "response_text" and response_mode != "short_answer":
            errors.append(_error("brief_candidate_contract_answer_encoding_invalid", "response_text 只能用于简答题"))
        if candidate_contract.get("answer_encoding") == "field_text" and response_mode not in {"fill_blank", "short_answer"}:
            errors.append(_error("brief_candidate_contract_answer_encoding_invalid", "field_text 只能用于填空题或结构化简答题"))
        if candidate_contract.get("answer_encoding") not in {"choice_text", "field_text", "response_text"}:
            errors.append(_error("brief_candidate_contract_answer_encoding_invalid", "candidate_contract.answer_encoding 不合法"))
        field_mapping = candidate_contract.get("field_mapping")
        if not isinstance(field_mapping, dict):
            errors.append(_error("brief_candidate_contract_field_mapping_invalid", "candidate_contract.field_mapping 必须说明五个下游字段"))
        else:
            for field_name in ("prompt", "choices", "answer", "rubric", "solution_steps"):
                if not isinstance(field_mapping.get(field_name), str) or not field_mapping[field_name].strip():
                    errors.append(_error(f"brief_candidate_contract_mapping_{field_name}_invalid", f"field_mapping.{field_name} 必须是非空说明"))
        for field_name in ("response_field_count", "reference_answer_count"):
            if not isinstance(candidate_contract.get(field_name), int) or isinstance(candidate_contract.get(field_name), bool) or candidate_contract[field_name] < 1:
                errors.append(_error(f"brief_candidate_contract_{field_name}_invalid", f"candidate_contract.{field_name} 必须是正整数"))
        for field_name in ("answer_requirements", "prompt_requirements"):
            if not isinstance(candidate_contract.get(field_name), list) or not candidate_contract[field_name]:
                errors.append(_error(f"brief_candidate_contract_{field_name}_invalid", f"candidate_contract.{field_name} 必须是非空数组"))
        choice_requirements = candidate_contract.get("choice_requirements")
        if not isinstance(choice_requirements, list):
            errors.append(_error("brief_candidate_contract_choice_requirements_invalid", "candidate_contract.choice_requirements 必须是数组"))
        elif response_mode in {"single_choice", "multi_choice"} and not choice_requirements:
            errors.append(_error("brief_candidate_contract_choice_requirements_invalid", "选择题必须提供选项构造和判定要求"))
    for field_name in ("construction", "answer_contract", "difficulty_contract", "self_check"):
        if field_name not in output:
            errors.append(_error(f"brief_{field_name}_missing", f"Brief 缺少 {field_name}"))
    return _result(errors, "brief_generation")


def validate_candidate(payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult:
    errors = []
    allowed_fields = {"candidate_id", "brief_id", "node_id", "content"}
    forbidden_fields = allowed_fields ^ set(output) if isinstance(output, dict) else set()
    forbidden_fields &= {"interaction_schema", "controls", "choices", "fields", "grading_mode", "answer_contract"}
    if forbidden_fields:
        errors.append(_error("candidate_internal_field_forbidden", "Candidate 不得携带控件、字段或判分配置"))
    if output.get("candidate_batch_size") or output.get("_candidate_batch_size"):
        errors.append(_error("candidate_must_be_single", "Candidate Skill 一次只能返回一道题"))
    if not output.get("candidate_id"):
        errors.append(_error("candidate_id_missing", "Candidate 必须有 candidate_id"))
    if output.get("brief_id") != payload.get("brief_id"):
        errors.append(_error("candidate_brief_id_mismatch", "Candidate 必须绑定输入 Brief"))
    if output.get("node_id") != payload.get("node_id"):
        errors.append(_error("candidate_node_id_mismatch", "Candidate 必须绑定输入 Node"))
    content = output.get("content")
    if not isinstance(content, dict):
        errors.append(_error("candidate_content_missing", "Candidate 必须包含 content"))
    else:
        allowed_content_fields = {"schema_version", "task_type", "response_mode", "prompt", "choices", "answer", "rubric", "solution_steps"}
        if set(content) - allowed_content_fields:
            errors.append(_error("candidate_internal_field_forbidden", "Candidate content 不得携带展示或判分字段"))
        if content.get("schema_version") != CONTENT_SCHEMA_VERSION:
            errors.append(_error("candidate_schema_version_invalid", "Candidate content schema_version 不正确"))
        if content.get("task_type") not in {"calculation", "reasoning", "application"}:
            errors.append(_error("candidate_task_type_invalid", "Candidate task_type 不合法"))
        for field_name in ("prompt", "choices", "answer"):
            if field_name not in content:
                errors.append(_error(f"candidate_{field_name}_missing", f"Candidate content 缺少 {field_name}"))
        if not isinstance(content.get("prompt"), str) or not content.get("prompt", "").strip():
            errors.append(_error("candidate_prompt_invalid", "Candidate prompt 必须是非空字符串"))
        elif content.get("response_mode") in RESPONSE_MODES:
            render_prompt = content["prompt"].replace("____", "（ ）")
            try:
                child_prompt.normalize_prompt_text(render_prompt, allow_legacy=False)
            except child_prompt.ChildPromptContractError as exc:
                errors.append(_error(
                    "candidate_prompt_not_renderable",
                    "Candidate prompt 不符合孩子端展示合同",
                    "；".join(exc.errors),
                ))
        if content.get("response_mode") not in RESPONSE_MODES:
            errors.append(_error("candidate_response_mode_invalid", "Candidate response_mode 不合法"))
        if content.get("response_mode") == "short_answer":
            for field_name in ("rubric", "solution_steps"):
                if not isinstance(content.get(field_name), list) or not content[field_name] or any(not isinstance(value, str) or not value.strip() for value in content[field_name]):
                    errors.append(_error(f"candidate_{field_name}_invalid", f"简答题必须提供非空 {field_name}"))
        if not isinstance(content.get("choices"), list) or not isinstance(content.get("answer"), list):
            errors.append(_error("candidate_answer_shape_invalid", "Candidate choices/answer 必须是数组"))
        else:
            parent_brief = payload.get("brief")
            candidate_contract = parent_brief.get("candidate_contract") if isinstance(parent_brief, dict) else None
            if isinstance(candidate_contract, dict):
                contract_mode = candidate_contract.get("response_mode")
                if contract_mode != content.get("response_mode"):
                    errors.append(_error("candidate_contract_response_mode_mismatch", "Candidate response_mode 必须执行 Brief 的 candidate_contract"))
                expected_encoding = {
                    "single_choice": "choice_text",
                    "multi_choice": "choice_text",
                    "fill_blank": "field_text",
                    "short_answer": "response_text",
                }.get(content.get("response_mode"))
                if candidate_contract.get("answer_encoding") != expected_encoding:
                    errors.append(_error("candidate_contract_answer_encoding_mismatch", "Candidate answer 编码方式不符合 Brief 的 candidate_contract"))
                reference_answer_count = candidate_contract.get("reference_answer_count")
                if isinstance(reference_answer_count, int) and not isinstance(reference_answer_count, bool) and len(content["answer"]) != reference_answer_count:
                    errors.append(_error("candidate_contract_reference_answer_count_mismatch", "Candidate answer 数量必须等于 Brief 的 reference_answer_count"))
                response_field_count = candidate_contract.get("response_field_count")
                if content.get("response_mode") in {"single_choice", "multi_choice", "short_answer"} and response_field_count != 1:
                    errors.append(_error("candidate_contract_response_field_count_mismatch", "单选、多选和简答题的 response_field_count 必须为1"))
            if any(not isinstance(value, str) or not value.strip() for value in content["choices"] + content["answer"]):
                errors.append(_error("candidate_answer_values_invalid", "Candidate choices/answer 必须是非空字符串数组"))
            if len(content["choices"]) != len(set(content["choices"])):
                errors.append(_error("candidate_choices_duplicate", "Candidate choices 不能重复"))
            mode = content.get("response_mode")
            if mode == "single_choice" and (len(content["choices"]) < 2 or len(content["answer"]) != 1 or content["answer"][0] not in content["choices"]):
                errors.append(_error("candidate_answer_not_in_choices", "单选答案必须且只能引用一个选项"))
            elif mode == "multi_choice" and (len(content["choices"]) < 2 or not content["answer"] or any(value not in content["choices"] for value in content["answer"])):
                errors.append(_error("candidate_answer_not_in_choices", "多选答案必须引用已有选项"))
            elif mode == "multi_choice" and len(content["answer"]) != len(set(content["answer"])):
                errors.append(_error("candidate_multi_choice_answers_duplicate", "多选答案不能重复"))
            elif mode == "fill_blank" and (content["choices"] or not content["answer"] or content.get("prompt", "").count("____") != len(content["answer"])):
                errors.append(_error("candidate_fill_blank_contract_invalid", "填空题必须无选项，且空数与答案数一致"))
    return _result(errors, "candidate_generation")


def _result(errors: list[dict[str, Any]], target_stage: str) -> ValidationResult:
    if not errors:
        return ValidationResult.passed()
    return ValidationResult.rejected(
        errors,
        target_stage=target_stage,
        max_attempts=2,
        reason="阶段产物未通过代码合同验证",
    )


def wrap_candidate_content(generator: Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]) -> Generator:
    """Adapt the minimal content generator to the persisted Candidate envelope."""

    def generate(payload: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        content = generator(payload)
        items = _as_items(content)
        if len(items) != 1:
            return [{
                "candidate_id": f"{payload['brief_id']}:candidate",
                "brief_id": payload["brief_id"],
                "node_id": payload["node_id"],
                "candidate_batch_size": len(items),
                "content": items[0].get("content", items[0]),
            }]
        return [
            {
                "candidate_id": f"{payload['brief_id']}:candidate",
                "brief_id": payload["brief_id"],
                "node_id": payload["node_id"],
                "content": item.get("content", item),
            }
            for item in items
        ]

    return generate


def build_question_production_skills(generators: dict[str, Generator], reviewers: dict[str, Reviewer] | None = None) -> dict[str, ProductionSkill]:
    required = set(STAGES)
    if set(generators) != required:
        raise ValueError(f"generators must exactly cover stages; missing={sorted(required - set(generators))}, unknown={sorted(set(generators) - required)}")
    return {
        "qf_design": QFDesignSkill(generators["qf_design"], (reviewers or {}).get("qf_design")),
        "slot_design": SlotDesignSkill(generators["slot_design"], (reviewers or {}).get("slot_design")),
        "brief_generation": BriefGenerationSkill(generators["brief_generation"], (reviewers or {}).get("brief_generation")),
        "candidate_generation": CandidateGenerationSkill(wrap_candidate_content(generators["candidate_generation"]), (reviewers or {}).get("candidate_generation")),
    }
