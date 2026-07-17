from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from learning_system import auto_review, db, model_router


FORBIDDEN_CHILD_TERMS = (
    "Codex",
    "Agent",
    "agent",
    "图谱",
    "节点",
    "自进化",
    "审计",
    "attempt_id",
    "question_id",
    "session_id",
    "pending_review",
    "graded",
    "model_name",
    "model_provider",
)

FAKE_PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgpmYWtlLXBob3Rv"
FOLLOW_UP_TASK_TYPES = {"remediate", "rollback", "prerequisite_probe", "retest"}
REQUIRED_ANALYSIS_DIMENSIONS = (
    "final_answer",
    "model_or_relation",
    "steps",
    "symbols_units",
    "check_or_explanation",
)


@dataclass(frozen=True)
class ComparisonExpectation:
    dimension: str
    statuses: tuple[str, ...]


@dataclass(frozen=True)
class LearningScenario:
    key: str
    label: str
    answer: str
    expected_result: str
    expected_score: float
    expected_explanation_score: int
    expected_blocking: bool
    expected_error_tags: tuple[str, ...] = ()
    expected_gap_terms: tuple[str, ...] = ()
    expected_comparisons: tuple[ComparisonExpectation, ...] = ()
    has_photo: bool = False
    expected_photo_status: str | None = None
    expected_photo_min_confidence: float = 0.0

    @property
    def weak_evidence(self) -> bool:
        return self.expected_result in {"partial", "wrong"} or self.expected_score < 2


SCENARIOS: dict[str, LearningScenario] = {
    "correct_full": LearningScenario(
        key="correct_full",
        label="会：规则、关系、步骤、检验完整",
        answer="我先写完整做法：先写规则，再列关键关系，计算后检查符号、单位和括号。",
        expected_result="correct",
        expected_score=2,
        expected_explanation_score=2,
        expected_blocking=False,
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("matched",)),
            ComparisonExpectation("model_or_relation", ("matched", "alternative_valid")),
            ComparisonExpectation("steps", ("matched",)),
            ComparisonExpectation("check_or_explanation", ("matched",)),
        ),
    ),
    "answer_only": LearningScenario(
        key="answer_only",
        label="只写答案：结果有线索但没有过程证据",
        answer="只写答案：我觉得结果是 38，但没有写规则、步骤和检验。",
        expected_result="partial",
        expected_score=1,
        expected_explanation_score=1,
        expected_blocking=False,
        expected_error_tags=("process_habit",),
        expected_gap_terms=("只写答案", "步骤", "检验"),
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("matched",)),
            ComparisonExpectation("steps", ("missing",)),
            ComparisonExpectation("check_or_explanation", ("missing",)),
        ),
    ),
    "stuck": LearningScenario(
        key="stuck",
        label="卡住：不知道第一步",
        answer="我卡住了：不知道第一步怎么把题意变成关系。",
        expected_result="wrong",
        expected_score=0,
        expected_explanation_score=0,
        expected_blocking=True,
        expected_error_tags=("concept_confusion",),
        expected_gap_terms=("第一步", "关系"),
        expected_comparisons=(
            ComparisonExpectation("model_or_relation", ("missing", "unclear")),
            ComparisonExpectation("steps", ("missing",)),
        ),
    ),
    "wrong_reason_right_answer": LearningScenario(
        key="wrong_reason_right_answer",
        label="答案碰巧对：思路或关系错误",
        answer="答案看起来是对的，但我是用错关系凑出来的，没有按题意建模。",
        expected_result="partial",
        expected_score=1,
        expected_explanation_score=1,
        expected_blocking=False,
        expected_error_tags=("concept_confusion", "modeling_or_reading"),
        expected_gap_terms=("答案对", "关系错误"),
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("matched",)),
            ComparisonExpectation("model_or_relation", ("incorrect",)),
            ComparisonExpectation("steps", ("incorrect", "missing")),
        ),
    ),
    "photo_correct": LearningScenario(
        key="photo_correct",
        label="拍照可读：纸面步骤可批阅",
        answer="见照片，可读。我把纸面步骤拍上来，也补一句检查。",
        expected_result="correct",
        expected_score=2,
        expected_explanation_score=2,
        expected_blocking=False,
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("matched",)),
            ComparisonExpectation("steps", ("matched",)),
            ComparisonExpectation("check_or_explanation", ("matched",)),
        ),
        has_photo=True,
        expected_photo_status="usable",
        expected_photo_min_confidence=auto_review.MIN_PHOTO_OCR_CONFIDENCE,
    ),
    "photo_unclear": LearningScenario(
        key="photo_unclear",
        label="拍照不清：不能因为有照片就判对",
        answer="见照片，但照片不清。我没有补充可读步骤。",
        expected_result="partial",
        expected_score=1,
        expected_explanation_score=1,
        expected_blocking=False,
        expected_error_tags=("process_habit",),
        expected_gap_terms=("照片", "证据不足"),
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("unclear",)),
            ComparisonExpectation("steps", ("unclear", "missing")),
            ComparisonExpectation("check_or_explanation", ("missing", "unclear")),
        ),
        has_photo=True,
        expected_photo_status="unclear",
    ),
    "partial_relation_wrong_final": LearningScenario(
        key="partial_relation_wrong_final",
        label="局部正确：关系启动了但结果或符号错",
        answer="我关系想对了，但算到最后符号或数值错了，检查也没发现。",
        expected_result="partial",
        expected_score=1,
        expected_explanation_score=1,
        expected_blocking=False,
        expected_error_tags=("calculation_or_symbol",),
        expected_gap_terms=("关系", "符号"),
        expected_comparisons=(
            ComparisonExpectation("model_or_relation", ("matched", "alternative_valid")),
            ComparisonExpectation("final_answer", ("incorrect",)),
            ComparisonExpectation("symbols_units", ("incorrect",)),
        ),
    ),
    "blank_or_no_evidence": LearningScenario(
        key="blank_or_no_evidence",
        label="不会：没有可用作答证据",
        answer="我不会，这题先空着，没有可用步骤。",
        expected_result="wrong",
        expected_score=0,
        expected_explanation_score=0,
        expected_blocking=True,
        expected_error_tags=("concept_confusion",),
        expected_gap_terms=("没有可用", "证据"),
        expected_comparisons=(
            ComparisonExpectation("final_answer", ("unclear",)),
            ComparisonExpectation("model_or_relation", ("missing", "unclear")),
            ComparisonExpectation("steps", ("missing",)),
        ),
    ),
}

LESSON_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("correct_full", "answer_only", "stuck", "photo_correct", "partial_relation_wrong_final"),
    ("wrong_reason_right_answer", "correct_full", "answer_only", "partial_relation_wrong_final", "photo_unclear"),
    ("correct_full", "correct_full", "correct_full", "correct_full", "correct_full"),
    ("stuck", "wrong_reason_right_answer", "partial_relation_wrong_final", "answer_only", "photo_correct"),
    ("photo_unclear", "correct_full", "blank_or_no_evidence", "partial_relation_wrong_final", "answer_only"),
    ("correct_full", "wrong_reason_right_answer", "correct_full", "photo_correct", "partial_relation_wrong_final"),
    ("answer_only", "stuck", "correct_full", "photo_unclear", "correct_full"),
    ("partial_relation_wrong_final", "wrong_reason_right_answer", "answer_only", "correct_full", "photo_correct"),
    ("correct_full", "correct_full", "partial_relation_wrong_final", "answer_only", "stuck"),
    ("photo_correct", "wrong_reason_right_answer", "correct_full", "blank_or_no_evidence", "partial_relation_wrong_final"),
)


@dataclass
class SemanticValidation:
    observations: list[dict[str, Any]] = field(default_factory=list)
    scenario_counts: Counter[str] = field(default_factory=Counter)
    result_counts: Counter[str] = field(default_factory=Counter)
    error_tag_counts: Counter[str] = field(default_factory=Counter)
    plan_task_types: list[str] = field(default_factory=list)
    plan_node_ids: list[str] = field(default_factory=list)
    weak_attempt_ids: list[str] = field(default_factory=list)
    weak_node_ids: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def scenario_for(lesson: int, task_index: int) -> LearningScenario:
    pattern = LESSON_PATTERNS[(lesson - 1) % len(LESSON_PATTERNS)]
    return SCENARIOS[pattern[(task_index - 1) % len(pattern)]]


def answer_payload_for_scenario(scenario: LearningScenario) -> tuple[str, str | None]:
    return scenario.answer, FAKE_PNG_DATA_URL if scenario.has_photo else None


def fake_photo_ocr(question: dict[str, Any], answer: str, answer_photo_data_url: str) -> dict[str, Any]:
    time.sleep(0.04)
    route = model_router.answer_photo_vision_route()
    if "照片不清" in answer:
        status = "unclear"
        confidence = 0.38
        transcript = ""
        math_objects: list[str] = []
        notes = "仿真照片不清，无法可靠读取步骤。"
    else:
        status = "usable"
        confidence = 0.86
        transcript = "纸面写着：先写规则，再列式计算，最后检查。"
        math_objects = ["规则", "列式", "检查"]
        notes = "仿真照片可读。"
    return {
        "route": {
            "provider": route.provider or "doubao",
            "model": route.model or "doubao-seed-2-0-pro-260215",
            "model_alias": route.model_alias or "doubao-seed-2-0-pro-260215",
        },
        "status": status,
        "confidence": confidence,
        "transcript": transcript,
        "math_objects": math_objects,
        "notes": notes,
    }


def fake_answer_review(question: dict[str, Any], answer: str, **kwargs: Any) -> dict[str, Any]:
    time.sleep(0.18)
    scenario = scenario_from_answer(answer)
    return review_for_scenario(scenario)


def scenario_from_answer(answer: str) -> LearningScenario:
    if "只写答案" in answer:
        return SCENARIOS["answer_only"]
    if "卡住" in answer:
        return SCENARIOS["stuck"]
    if "用错关系凑出来" in answer:
        return SCENARIOS["wrong_reason_right_answer"]
    if "照片不清" in answer:
        return SCENARIOS["photo_unclear"]
    if "见照片，可读" in answer:
        return SCENARIOS["photo_correct"]
    if "关系想对了" in answer:
        return SCENARIOS["partial_relation_wrong_final"]
    if "我不会" in answer or "先空着" in answer:
        return SCENARIOS["blank_or_no_evidence"]
    return SCENARIOS["correct_full"]


def review_for_scenario(scenario: LearningScenario) -> dict[str, Any]:
    return {
        "result": scenario.expected_result,
        "score_points": scenario.expected_score,
        "max_points": 2,
        "error_tags": list(scenario.expected_error_tags),
        "explanation_score": scenario.expected_explanation_score,
        "blocking_evidence": scenario.expected_blocking,
        "confidence": 0.91,
        "parent_note": _parent_note(scenario),
        "key_observations": _observations(scenario),
        "next_action": _next_action(scenario),
        "answer_analysis": answer_analysis_for_scenario(scenario),
    }


def answer_analysis_for_scenario(scenario: LearningScenario) -> dict[str, Any]:
    process_gap = _process_gap(scenario)
    comparison = _comparison_for_scenario(scenario)
    analysis = {
        "agent_key": "answer_analysis_agent",
        "optimal_answer": "按题目条件建立关系，完成计算或说明，并用检验确认结论。",
        "optimal_solution_steps": [
            "先识别题目中的数量关系、运算规则或符号约束。",
            "把关键关系写成算式、方程、图示或清楚的文字解释。",
            "完成计算或推理后，检查符号、单位、括号和结论是否符合题意。",
        ],
        "child_answer_summary": _child_summary(scenario),
        "comparison": comparison,
        "alternative_solutions": ["也可以先画关系图或数轴，再把关系转成算式、方程或等价变形。"],
        "process_gap": process_gap,
        "no_gap_observed": _comparison_has_no_gap(comparison),
        "teaching_explanation": _teaching_explanation(scenario),
        "next_child_prompt": _next_child_prompt(scenario),
    }
    analysis["evaluation_support"] = db.derive_answer_evaluation_support(analysis)
    return analysis


def _comparison_for_scenario(scenario: LearningScenario) -> list[dict[str, str]]:
    details = {
        ("final_answer", "matched"): "最终结论可接受，但仍要看过程是否可靠。",
        ("final_answer", "incorrect"): "最终结论与题意或运算结果不一致。",
        ("final_answer", "unclear"): "没有足够清楚的最终结论证据。",
        ("model_or_relation", "matched"): "核心关系或模型启动正确。",
        ("model_or_relation", "missing"): "没有写出可用的关系或模型。",
        ("model_or_relation", "incorrect"): "使用了错误关系，不能支撑答案。",
        ("steps", "matched"): "步骤可复盘。",
        ("steps", "missing"): "步骤证据缺失，无法判断方法是否稳定。",
        ("steps", "incorrect"): "步骤从错误依据出发，不能作为可靠方法。",
        ("steps", "unclear"): "步骤证据不清楚。",
        ("symbols_units", "incorrect"): "符号、单位或数值落点出现错误。",
        ("check_or_explanation", "matched"): "有检验或解释，能说明为什么成立。",
        ("check_or_explanation", "missing"): "缺少检验或解释。",
        ("check_or_explanation", "unclear"): "检验或解释不清楚。",
    }
    items: list[dict[str, str]] = []
    for expectation in scenario.expected_comparisons:
        status = expectation.statuses[0]
        items.append({
            "dimension": expectation.dimension,
            "status": status,
            "detail": details.get((expectation.dimension, status), "该维度证据已按场景记录。"),
        })
    return _with_required_comparison_dimensions(scenario, items, details)


def _with_required_comparison_dimensions(
    scenario: LearningScenario,
    items: list[dict[str, str]],
    details: dict[tuple[str, str], str],
) -> list[dict[str, str]]:
    present = {item["dimension"] for item in items}
    defaults = _default_comparison_statuses(scenario)
    for dimension in REQUIRED_ANALYSIS_DIMENSIONS:
        if dimension in present:
            continue
        status = defaults[dimension]
        items.append({
            "dimension": dimension,
            "status": status,
            "detail": details.get((dimension, status), _default_comparison_detail(dimension, status, scenario)),
        })
    return items


def _default_comparison_statuses(scenario: LearningScenario) -> dict[str, str]:
    if scenario.expected_result == "correct":
        return {dimension: "matched" for dimension in REQUIRED_ANALYSIS_DIMENSIONS}
    if scenario.key == "wrong_reason_right_answer":
        return {
            "final_answer": "matched",
            "model_or_relation": "incorrect",
            "steps": "incorrect",
            "symbols_units": "unclear",
            "check_or_explanation": "missing",
        }
    if scenario.key == "partial_relation_wrong_final":
        return {
            "final_answer": "incorrect",
            "model_or_relation": "matched",
            "steps": "matched",
            "symbols_units": "incorrect",
            "check_or_explanation": "missing",
        }
    if scenario.key == "answer_only":
        return {
            "final_answer": "matched",
            "model_or_relation": "unclear",
            "steps": "missing",
            "symbols_units": "unclear",
            "check_or_explanation": "missing",
        }
    if scenario.key == "photo_unclear":
        return {
            "final_answer": "unclear",
            "model_or_relation": "unclear",
            "steps": "unclear",
            "symbols_units": "unclear",
            "check_or_explanation": "unclear",
        }
    return {
        "final_answer": "unclear",
        "model_or_relation": "missing",
        "steps": "missing",
        "symbols_units": "missing",
        "check_or_explanation": "missing",
    }


def _default_comparison_detail(dimension: str, status: str, scenario: LearningScenario) -> str:
    if status == "matched":
        return f"{scenario.label}：{dimension} 维度证据可接受。"
    if status == "incorrect":
        return f"{scenario.label}：{dimension} 维度存在错误，不能支撑完全掌握。"
    if status == "unclear":
        return f"{scenario.label}：{dimension} 维度证据不清楚。"
    return f"{scenario.label}：{dimension} 维度证据缺失。"


def _comparison_has_no_gap(items: list[dict[str, str]]) -> bool:
    return all(item.get("status") in {"matched", "alternative_valid"} for item in items)


def _process_gap(scenario: LearningScenario) -> str:
    return {
        "correct_full": "",
        "answer_only": "只写答案，缺少可复盘步骤和检验。",
        "stuck": "卡在第一步，没有把题意转成可用关系。",
        "wrong_reason_right_answer": "答案对但关系错误，结果不能证明方法可靠。",
        "photo_correct": "",
        "photo_unclear": "照片和文字证据不足，不能确认步骤和检验。",
        "partial_relation_wrong_final": "关系启动了，但符号或计算落点错误。",
        "blank_or_no_evidence": "没有可用作答证据，无法启动第一步。",
    }[scenario.key]


def _child_summary(scenario: LearningScenario) -> str:
    return {
        "correct": "孩子给出了答案，也说明了关键规则、步骤和检查。",
        "partial": "孩子给出了部分线索，但关键依据、步骤、符号或检验不稳定。",
        "wrong": "孩子没有形成可用关系、步骤或作答证据。",
    }[scenario.expected_result]


def _parent_note(scenario: LearningScenario) -> str:
    if scenario.expected_result == "correct":
        return "答案、步骤和检查成立。"
    if scenario.expected_blocking:
        return "孩子卡在第一步或没有可用证据，需要回退到前置关系。"
    return "答案有局部线索，但过程证据或核心关系不足。"


def _observations(scenario: LearningScenario) -> list[str]:
    if scenario.expected_result == "correct":
        return ["能说明关键规则", "能完成检查"]
    return [scenario.label, _process_gap(scenario)]


def _next_action(scenario: LearningScenario) -> str:
    if scenario.expected_blocking:
        return "回退到前置关系题"
    if scenario.weak_evidence:
        return "补过程证据并做错因回炉题"
    return "进入下一题"


def _teaching_explanation(scenario: LearningScenario) -> str:
    if scenario.expected_result == "correct":
        return "这类题不是只看最后数字，而是看关系、步骤和检验是否能互相支撑。"
    return f"当前最小缺口是：{_process_gap(scenario)} 下一题要先补这个证据。"


def _next_child_prompt(scenario: LearningScenario) -> str:
    if scenario.expected_result == "correct":
        return "下一题继续先写规则，再写关键步骤，最后补一句检查。"
    if scenario.expected_blocking:
        return "先写：这道题第一步要找哪个关系？只写第一步也可以。"
    return "请先补一句规则，再写关键步骤和检查，不要只写最后答案。"


def check_child_safe(payload: dict[str, Any], scope: str) -> list[str]:
    serialized = json.dumps(payload, ensure_ascii=False)
    return [f"{scope} leaked child-forbidden term `{term}`" for term in FORBIDDEN_CHILD_TERMS if term in serialized]


def ordered_attempts_for_session(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    session = db.get_learning_session(conn, session_id)
    attempts = db.attempts_for_session(conn, session_id)
    by_question_id = {attempt["question_id"]: attempt for attempt in attempts}
    ordered: list[dict[str, Any]] = []
    for question_id in session.get("expected_question_ids", []):
        attempt = by_question_id.get(question_id)
        if attempt:
            ordered.append(attempt)
    remaining = [attempt for attempt in attempts if attempt["question_id"] not in session.get("expected_question_ids", [])]
    return ordered + remaining


def validate_session_semantics(
    conn: sqlite3.Connection,
    session_id: str,
    lesson: int,
    scenarios: list[LearningScenario],
) -> SemanticValidation:
    validation = SemanticValidation()
    attempts = ordered_attempts_for_session(conn, session_id)
    if len(attempts) != len(scenarios):
        validation.issues.append(f"lesson {lesson}: expected {len(scenarios)} attempts, found {len(attempts)}")

    for index, (scenario, attempt) in enumerate(zip(scenarios, attempts), start=1):
        attempt = db.get_attempt(conn, attempt["id"])
        validation.scenario_counts.update([scenario.key])
        validation.result_counts.update([attempt["result"]])
        validation.error_tag_counts.update(attempt.get("error_tags") or [])
        if scenario.weak_evidence:
            validation.weak_attempt_ids.append(attempt["id"])
            validation.weak_node_ids.append(attempt["node_id"])
        validation.observations.append(_observation_row(conn, lesson, index, scenario, attempt))
        validation.issues.extend(_validate_attempt(conn, lesson, index, scenario, attempt))

    session = db.get_learning_session(conn, session_id)
    closure_result = session.get("closure_result") or {}
    next_plan = closure_result.get("next_plan") if isinstance(closure_result.get("next_plan"), dict) else {}
    next_tasks = next_plan.get("tasks") if isinstance(next_plan.get("tasks"), list) else []
    validation.plan_task_types = [str(task.get("task_type") or "") for task in next_tasks]
    validation.plan_node_ids = [str(task.get("node_id") or "") for task in next_tasks if task.get("node_id")]
    validation.issues.extend(_validate_follow_up_plan(lesson, validation, next_tasks))
    return validation


def assert_required_coverage(results: list[SemanticValidation], lessons: int) -> list[str]:
    counts: Counter[str] = Counter()
    for result in results:
        counts.update(result.scenario_counts)
    required = {
        "correct_full",
        "answer_only",
        "stuck",
        "wrong_reason_right_answer",
        "photo_correct",
        "photo_unclear",
        "partial_relation_wrong_final",
        "blank_or_no_evidence",
    }
    issues = [f"10-lesson semantic matrix missed scenario `{key}`" for key in sorted(required - set(counts))]
    if lessons >= 10:
        correct_only_seen = any(
            result.scenario_counts
            and set(result.scenario_counts) == {"correct_full"}
            for result in results
        )
        if not correct_only_seen:
            issues.append("10-lesson semantic matrix did not include a correct-only lesson")
    return issues


def _validate_attempt(
    conn: sqlite3.Connection,
    lesson: int,
    task_index: int,
    scenario: LearningScenario,
    attempt: dict[str, Any],
) -> list[str]:
    prefix = f"lesson {lesson} task {task_index} `{scenario.key}`"
    issues: list[str] = []
    if attempt["grading_status"] != "graded":
        issues.append(f"{prefix}: grading_status={attempt['grading_status']}, expected graded")
    if attempt["result"] != scenario.expected_result:
        issues.append(f"{prefix}: result={attempt['result']}, expected {scenario.expected_result}")
    if float(attempt["score_points"]) != float(scenario.expected_score):
        issues.append(f"{prefix}: score_points={attempt['score_points']}, expected {scenario.expected_score}")
    if int(attempt.get("explanation_score") or 0) != scenario.expected_explanation_score:
        issues.append(f"{prefix}: explanation_score={attempt.get('explanation_score')}, expected {scenario.expected_explanation_score}")
    if bool(attempt.get("blocking_evidence")) != scenario.expected_blocking:
        issues.append(f"{prefix}: blocking_evidence={attempt.get('blocking_evidence')}, expected {scenario.expected_blocking}")
    tags = set(attempt.get("error_tags") or [])
    for tag in scenario.expected_error_tags:
        if tag not in tags:
            issues.append(f"{prefix}: missing error tag `{tag}` from {sorted(tags)}")
    if scenario.expected_result == "correct" and tags:
        issues.append(f"{prefix}: correct scenario should not carry error tags, got {sorted(tags)}")

    analysis = attempt.get("answer_analysis") or {}
    if not db.is_valid_answer_analysis(analysis):
        issues.append(f"{prefix}: answer_analysis is missing or invalid")
    else:
        gap = str(analysis.get("process_gap") or "")
        for term in scenario.expected_gap_terms:
            if term not in gap:
                issues.append(f"{prefix}: process_gap `{gap}` does not include `{term}`")
        if not scenario.expected_gap_terms and gap:
            issues.append(f"{prefix}: expected empty process_gap for correct evidence, got `{gap}`")
        for expectation in scenario.expected_comparisons:
            if not _has_comparison(analysis, expectation.dimension, expectation.statuses):
                issues.append(
                    f"{prefix}: comparison missing {expectation.dimension} in {expectation.statuses}; "
                    f"got {analysis.get('comparison')}"
                )
        if scenario.key == "wrong_reason_right_answer" and attempt["result"] == "correct":
            issues.append(f"{prefix}: answer with unsound reasoning must not be graded correct")

    issues.extend(_validate_photo_evidence(conn, prefix, scenario, attempt))
    issues.extend(_validate_node_status(conn, prefix, scenario, attempt))
    return issues


def _validate_photo_evidence(
    conn: sqlite3.Connection,
    prefix: str,
    scenario: LearningScenario,
    attempt: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    attachments = db.attachments_for_attempt(conn, attempt["id"])
    review_meta = attempt.get("review_meta") if isinstance(attempt.get("review_meta"), dict) else {}
    vision = review_meta.get("vision") if isinstance(review_meta.get("vision"), dict) else None
    if scenario.has_photo:
        if not attachments:
            issues.append(f"{prefix}: expected saved photo attachment")
        if not vision:
            issues.append(f"{prefix}: expected photo OCR audit in review_meta.vision")
            return issues
        if vision.get("status") != scenario.expected_photo_status:
            issues.append(f"{prefix}: photo OCR status={vision.get('status')}, expected {scenario.expected_photo_status}")
        if float(vision.get("confidence") or 0.0) < scenario.expected_photo_min_confidence:
            issues.append(f"{prefix}: photo OCR confidence={vision.get('confidence')} below {scenario.expected_photo_min_confidence}")
        if scenario.expected_photo_status == "usable":
            if not vision.get("has_transcript") or not str(vision.get("transcript") or "").strip():
                issues.append(f"{prefix}: usable photo OCR must have transcript")
            if not vision.get("math_objects"):
                issues.append(f"{prefix}: usable photo OCR must include math_objects")
    else:
        if attachments:
            issues.append(f"{prefix}: unexpected photo attachment for non-photo scenario")
    return issues


def _validate_node_status(
    conn: sqlite3.Connection,
    prefix: str,
    scenario: LearningScenario,
    attempt: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    raw_status = conn.execute(
        "select * from learner_node_status where node_id = ?",
        (attempt["node_id"],),
    ).fetchone()
    current_statuses = {
        row["node_id"]: row
        for row in db.current_learner_node_status_rows(conn)
    }
    status = current_statuses.get(attempt["node_id"])
    if not status:
        if raw_status:
            issues.append(
                f"{prefix}: learner_node_status for {attempt['node_id']} is not current-valid; "
                "evidence refs may be stale, invalidated, or incomplete"
            )
        else:
            issues.append(f"{prefix}: missing learner_node_status for {attempt['node_id']}")
        return issues
    status_code = status["status_code"]
    if scenario.expected_blocking and status_code != "D":
        issues.append(f"{prefix}: blocking evidence should produce node status D, got {status_code}")
    node_attempts = [
        db.get_attempt(conn, row["id"])
        for row in conn.execute(
            """
            select id
            from attempts
            where session_id = ?
              and node_id = ?
              and evidence_status = 'active'
            """,
            (attempt["session_id"], attempt["node_id"]),
        ).fetchall()
    ]
    same_round_weak_evidence = any(
        item["id"] != attempt["id"]
        and (
            item.get("blocking_evidence")
            or item.get("result") in {"wrong", "partial"}
            or float(item.get("score_points") or 0) < float(item.get("max_points") or 2)
        )
        for item in node_attempts
    )
    if scenario.expected_result == "correct" and not same_round_weak_evidence and status_code not in {"A", "B"}:
        issues.append(f"{prefix}: correct evidence should keep node usable, got status {status_code}")
    if scenario.weak_evidence:
        latest = db.get_attempt(conn, attempt["id"])
        cause = latest.get("cause_analysis") if isinstance(latest.get("cause_analysis"), dict) else {}
        if not cause:
            issues.append(f"{prefix}: weak evidence should have cause_analysis after closure")
        else:
            if not str(cause.get("process_gap") or "").strip():
                issues.append(f"{prefix}: cause_analysis.process_gap is empty")
            for tag in scenario.expected_error_tags:
                if tag not in (cause.get("error_tags") or []):
                    issues.append(f"{prefix}: cause_analysis missing error tag `{tag}`")
    return issues


def _validate_follow_up_plan(lesson: int, validation: SemanticValidation, next_tasks: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if not next_tasks:
        issues.append(f"lesson {lesson}: closure did not create a next plan")
        return issues
    if validation.weak_attempt_ids:
        task_types = set(validation.plan_task_types)
        if not task_types & FOLLOW_UP_TASK_TYPES:
            issues.append(f"lesson {lesson}: weak evidence did not produce follow-up task types; got {validation.plan_task_types}")
        weak_attempts = set(validation.weak_attempt_ids)
        weak_nodes = set(validation.weak_node_ids)
        evidence_linked = False
        for task in next_tasks:
            signal = task.get("planning_signal") if isinstance(task.get("planning_signal"), dict) else {}
            source_nodes = set(task.get("source_node_ids") or [])
            signal_attempts = set(signal.get("evidence_attempt_ids") or [])
            rollback_candidates = set(signal.get("rollback_candidates") or [])
            if signal_attempts & weak_attempts:
                evidence_linked = True
            if source_nodes & weak_nodes:
                evidence_linked = True
            if task.get("node_id") in weak_nodes or task.get("node_id") in rollback_candidates:
                evidence_linked = True
        if not evidence_linked:
            issues.append(
                f"lesson {lesson}: next plan is not linked to weak evidence attempts/nodes; "
                f"weak_attempts={sorted(weak_attempts)}, plan_types={validation.plan_task_types}"
            )
    return issues


def _has_comparison(analysis: dict[str, Any], dimension: str, statuses: tuple[str, ...]) -> bool:
    for item in analysis.get("comparison") or []:
        if not isinstance(item, dict):
            continue
        if item.get("dimension") == dimension and item.get("status") in statuses:
            return True
    return False


def _observation_row(
    conn: sqlite3.Connection,
    lesson: int,
    task_index: int,
    scenario: LearningScenario,
    attempt: dict[str, Any],
) -> dict[str, Any]:
    analysis = attempt.get("answer_analysis") if isinstance(attempt.get("answer_analysis"), dict) else {}
    review_meta = attempt.get("review_meta") if isinstance(attempt.get("review_meta"), dict) else {}
    vision = review_meta.get("vision") if isinstance(review_meta.get("vision"), dict) else {}
    return {
        "lesson": lesson,
        "task": task_index,
        "scenario": scenario.key,
        "scenario_label": scenario.label,
        "attempt_id": attempt["id"],
        "node_id": attempt["node_id"],
        "question_id": attempt["question_id"],
        "result": attempt["result"],
        "score": attempt["score_points"],
        "explanation_score": attempt.get("explanation_score"),
        "error_tags": attempt.get("error_tags") or [],
        "blocking": bool(attempt.get("blocking_evidence")),
        "process_gap": str(analysis.get("process_gap") or ""),
        "comparison": [
            f"{item.get('dimension')}:{item.get('status')}"
            for item in analysis.get("comparison", [])
            if isinstance(item, dict)
        ],
        "photo_status": vision.get("status", ""),
        "attachment_count": len(db.attachments_for_attempt(conn, attempt["id"])),
    }


def counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(counter[key]) for key in sorted(counter)}
