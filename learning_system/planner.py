from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from . import db, goal_choice_service, mastery_bridge, mastery_rules, question_bank
from .trace_back import ordered_prerequisite_candidates


LEARNING_ROUND_TASK_COUNT = 10
PLANNER_POLICY_VERSION = "2026-07-09.planner-signal-round.v1"
EVALUATION_MIN_CONFIDENCE_TO_APPLY = 0.8
MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND = question_bank.MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND
MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND = question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND
MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND = question_bank.MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND
SIGNAL_TRACED_TASK_TYPES = {"rollback", "prerequisite_probe", "remediate", "retest"}

NODE_LOCAL_MAINLINE_KIND_PREFS = [
    "two_method_compare",
    "variant",
    "error_spotting",
    "transfer_retest",
    "missing_condition",
    "reverse_reasoning",
    "representation",
    "boundary_case",
    "self_correction",
    "symbol_unit_audit",
    "check_strategy",
    "estimation_modeling",
    "misconception_probe",
    "explanation_only",
    "communication",
    "standard_example",
]


class PlannerPlanError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        quality_gates: dict[str, bool] | None = None,
        task_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.quality_gates = quality_gates or {}
        self.task_count = task_count


class PlanTaskDTO:
    """v2 child-plan seam; keeps internal graph ids out of child projections."""

    child_fields = ("position", "kind_label", "display_topic", "estimated_minutes", "question", "support")
    operator_fields = ("question_id", "node_id", "task_type", "planning_signal")

    @staticmethod
    def child_safe(task: dict[str, Any], *, position: int, kind_label: str) -> dict[str, Any]:
        question = task.get("question") if isinstance(task.get("question"), dict) else {}
        return {
            "position": position,
            "kind_label": kind_label,
            "display_topic": str(task.get("node_name") or task.get("display_topic") or "当前任务"),
            "estimated_minutes": task.get("estimated_minutes"),
            "question": {
                "prompt": question.get("prompt", ""),
                "answer_format": question.get("answer_format", "关键步骤 + 答案"),
            },
            "support": {
                "essence_or_hint": task.get("essence", ""),
            },
        }


QUESTION_KIND_PREFS = {
    "learn": [
        "stretch_transfer",
        "model_selection",
        "two_method_compare",
        "variant",
        "error_spotting",
        "transfer_retest",
        "missing_condition",
        "reverse_reasoning",
        "representation",
        "boundary_case",
        "self_correction",
        "symbol_unit_audit",
        "check_strategy",
        "estimation_modeling",
        "standard_example",
    ],
    "rollback": ["misconception_probe", "error_spotting", "representation", "two_method_compare", "prerequisite_probe"],
    "prerequisite_probe": ["misconception_probe", "model_selection", "representation", "error_spotting", "standard_example"],
    "remediate": ["evidence_driven_retest", "error_spotting", "model_selection", "two_method_compare", "stretch_transfer", "variant"],
    "retest": ["evidence_driven_retest", "stretch_transfer", "transfer_retest", "two_method_compare", "model_selection", "error_spotting"],
}

ROUND_KIND_SLOTS = {
    "learn": [
        ["stretch_transfer", "model_selection", "two_method_compare", "variant", "error_spotting"],
        ["model_selection", "two_method_compare", "stretch_transfer", "variant", "missing_condition"],
        ["two_method_compare", "error_spotting", "model_selection", "reverse_reasoning"],
        ["variant", "transfer_retest", "stretch_transfer", "model_selection"],
        ["error_spotting", "two_method_compare", "self_correction", "symbol_unit_audit"],
        ["transfer_retest", "stretch_transfer", "model_selection", "variant"],
        ["missing_condition", "model_selection", "reverse_reasoning", "representation"],
        ["representation", "model_selection", "two_method_compare", "variant"],
        ["boundary_case", "error_spotting", "two_method_compare", "stretch_transfer"],
        ["self_correction", "check_strategy", "symbol_unit_audit", "stretch_transfer"],
    ],
    "rollback": [
        ["misconception_probe", "error_spotting", "representation"],
        ["error_spotting", "two_method_compare", "prerequisite_probe"],
        ["representation", "model_selection", "misconception_probe"],
    ],
    "prerequisite_probe": [
        ["misconception_probe", "model_selection", "representation"],
        ["representation", "error_spotting", "standard_example"],
        ["model_selection", "misconception_probe", "standard_example"],
    ],
    "remediate": [
        ["evidence_driven_retest", "error_spotting", "model_selection"],
        ["model_selection", "two_method_compare", "stretch_transfer"],
        ["error_spotting", "variant", "evidence_driven_retest"],
    ],
    "retest": [
        ["evidence_driven_retest", "stretch_transfer", "transfer_retest"],
        ["transfer_retest", "two_method_compare", "model_selection"],
        ["stretch_transfer", "model_selection", "error_spotting"],
    ],
}

CORE_LEARN_PATH = [
    "M-BRIDGE-SOLUTION-HABIT",
    "M-BRIDGE-WORD-PROBLEM-READING",
    "M-G7-POS-NEG",
    "M-G7-NUMBER-LINE",
    "M-G7-ABSOLUTE",
    "M-G7-OPPOSITE",
    "M-G7-COMPARE",
    "M-G7-RATIONAL-ADD-SUB",
    "M-G7-RATIONAL-MUL-DIV",
    "M-G7-RATIONAL-MIXED",
    "M-G7-ALG-EXPR",
    "M-G7-LIKE-TERMS",
    "M-G7-COMBINE-LIKE",
    "M-G7-PARENTHESIS",
    "M-G7-POLY-ADD-SUB",
    "M-G7-EQUATION-CONCEPT",
    "M-G7-EQUALITY-PROP",
    "M-G7-EQ-SOLVE",
    "M-G7-EQ-PAREN",
    "M-G7-EQ-WORD",
]

PICTURE_LEVEL_CHALLENGE_PATH = [
    "M-BRIDGE-SOLUTION-HABIT",
    "M-PRE-NUMBER-SENSE",
    "M-PRE-INTEGER-OPS",
    "M-PRE-QUANTITY-RELATION",
    "M-BRIDGE-WORD-PROBLEM-READING",
    "M-G7-POS-NEG",
    "M-G7-NUMBER-LINE",
    "M-G7-ABSOLUTE",
    "M-G7-OPPOSITE",
    "M-G7-COMPARE",
    "M-G7-RATIONAL-ADD-SUB",
    "M-G7-RATIONAL-MUL-DIV",
    "M-G7-RATIONAL-MIXED",
]


def _empty_signal(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "evaluation_decision_id": "",
        "mastery_state": "unknown",
        "gap_type": "",
        "intervention_need": "",
        "confirmation_needed": False,
        "confirmation_type": "",
        "can_advance": False,
        "required_question_family": "",
        "preferred_question_kinds": [],
        "target_dimensions": [],
        "target_error_tags": [],
        "selected_intervention": "",
        "evidence_attempt_ids": [],
        "dominant_error_tags": [],
        "unstable_dimensions": [],
        "process_gaps": [],
        "rollback_candidates": [],
        "created_question_ids": [],
        "blocking_evidence": False,
    }


def _is_current_attempt_evidence(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    return db.is_current_usable_attempt_evidence(conn, attempt)


def _preferred_kinds_for_evaluation_payload(payload: dict[str, Any]) -> list[str]:
    planner_signal = payload.get("planner_signal") if isinstance(payload.get("planner_signal"), dict) else {}
    preferred_from_signal = planner_signal.get("preferred_question_kinds") if isinstance(planner_signal, dict) else []
    if isinstance(preferred_from_signal, list):
        preferred = [str(kind) for kind in preferred_from_signal if str(kind).strip()]
        if preferred:
            return preferred
    confirmation_type = str(payload.get("confirmation_type") or "")
    intervention = str(payload.get("intervention_need") or payload.get("selected_intervention") or "")
    gap_type = str(payload.get("gap_type") or "")
    if confirmation_type == "prerequisite_probe" or intervention == "prerequisite_repair" or gap_type == "prerequisite_gap":
        return ["misconception_probe", "prerequisite_probe", "representation", "model_selection", "error_spotting"]
    if confirmation_type == "near_transfer_retest" or gap_type in {"model_gap", "concept_gap", "transfer_gap"}:
        return ["transfer_retest", "stretch_transfer", "two_method_compare", "representation", "model_selection", "reverse_reasoning"]
    if confirmation_type == "same_structure_retest":
        return ["evidence_driven_retest", "variant", "error_spotting", "model_selection", "self_correction", "check_strategy"]
    if intervention in {"procedure_scaffold", "symbol_contrast", "metacognitive_check"}:
        return ["error_spotting", "self_correction", "symbol_unit_audit", "check_strategy", "variant"]
    return []


def _has_valid_planner_signal(payload: dict[str, Any]) -> bool:
    planner_signal = payload.get("planner_signal")
    if not isinstance(planner_signal, dict):
        return False
    required = {
        "preferred_question_kinds": list,
        "avoid_question_kinds": list,
        "need_same_structure": bool,
        "need_prerequisite_probe": bool,
        "need_teaching_before_next": bool,
        "evidence_policy_notes": list,
    }
    for key, expected_type in required.items():
        if not isinstance(planner_signal.get(key), expected_type):
            return False
    return True


def _evaluation_decision_is_planner_usable(row: sqlite3.Row, payload: dict[str, Any]) -> bool:
    if int(row["applied"] or 0) != 1:
        return False
    if not row["agent_run_id"]:
        return False
    if row["agent_run_status"] != "accepted":
        return False
    try:
        run_confidence = float(row["agent_run_confidence"] or 0.0)
        payload_confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return (
        run_confidence >= EVALUATION_MIN_CONFIDENCE_TO_APPLY
        and payload_confidence >= EVALUATION_MIN_CONFIDENCE_TO_APPLY
    )


def _latest_evaluation_decision_signal(
    conn: sqlite3.Connection,
    node_id: str,
    current_attempt_ids: list[str],
) -> dict[str, Any]:
    rows = conn.execute(
        """
        select
          md.id,
          md.decision,
          md.closure_result,
          md.evidence_attempt_ids_json,
          md.decision_payload_json,
          md.applied,
          md.agent_run_id,
          ar.status as agent_run_status,
          ar.confidence as agent_run_confidence
        from mastery_decisions md
        left join agent_runs ar on ar.id = md.agent_run_id
        where md.node_id = ?
        order by md.created_at desc, md.rowid desc
        limit 8
        """,
        (node_id,),
    ).fetchall()
    current_id_set = set(current_attempt_ids)
    for row in rows:
        evidence_ids = db.json_load(row["evidence_attempt_ids_json"], [])
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        evidence_ids = [str(item) for item in evidence_ids if str(item).strip()]
        payload = db.json_load(row["decision_payload_json"], {})
        if not isinstance(payload, dict) or not payload:
            continue
        if not _evaluation_decision_is_planner_usable(row, payload):
            continue
        payload_evidence_ids = payload.get("evidence_attempt_ids")
        if not isinstance(payload_evidence_ids, list):
            continue
        payload_evidence_ids = [str(item) for item in payload_evidence_ids if str(item).strip()]
        if (
            payload.get("schema_version") != "2026-07-08.evaluation-diagnosis.v2"
            or payload.get("threshold_policy_version") != "2026-07-08.single-strong-is-not-stable.v1"
            or payload.get("node_id") != node_id
            or not _has_valid_planner_signal(payload)
            or not evidence_ids
            or payload_evidence_ids != evidence_ids
            or not set(evidence_ids).issubset(current_id_set)
        ):
            continue
        if any(db.get_attempt(conn, attempt_id).get("node_id") != node_id for attempt_id in evidence_ids):
            continue
        preferred = _preferred_kinds_for_evaluation_payload(payload)
        return {
            "evaluation_decision_id": row["id"],
            "mastery_state": str(payload.get("mastery_state") or "unknown"),
            "gap_type": str(payload.get("gap_type") or ""),
            "intervention_need": str(payload.get("intervention_need") or payload.get("selected_intervention") or ""),
            "confirmation_needed": bool(payload.get("confirmation_needed", False)),
            "confirmation_type": str(payload.get("confirmation_type") or ""),
            "can_advance": bool(payload.get("can_advance", False)),
            "required_question_family": str(payload.get("required_question_family") or payload.get("confirmation_type") or ""),
            "preferred_question_kinds": preferred,
            "target_dimensions": [
                str(item) for item in payload.get("target_dimensions", [])
                if str(item).strip()
            ],
            "target_error_tags": [
                str(item) for item in payload.get("target_error_tags", [])
                if str(item).strip()
            ],
            "selected_intervention": str(payload.get("selected_intervention") or payload.get("intervention_need") or ""),
        }
    return {}


def _latest_planning_signal(conn: sqlite3.Connection, node_id: str) -> dict[str, Any]:
    signal = _empty_signal(node_id)
    status = conn.execute(
        "select evidence_attempt_ids_json from learner_node_status where node_id = ?",
        (node_id,),
    ).fetchone()
    attempt_ids = db.json_load(status["evidence_attempt_ids_json"], []) if status else []
    attempts = []
    if attempt_ids:
        placeholders = ",".join("?" for _ in attempt_ids)
        attempts = [
            db.attempt_row_to_dict(row)
            for row in conn.execute(
                f"""
                select a.*
                from attempts a
                join question_items q on q.id = a.question_id
                where a.id in ({placeholders})
                  and a.evidence_status = 'active'
                  and a.grading_status = 'graded'
                  and a.answer_analysis_json <> '{{}}'
                  and (
                    (q.source_type = 'graph_generated' and q.item_version = ?)
                    or (q.source_type = 'evolved' and q.item_version = ?)
                    or q.source_type not in ('graph_generated', 'evolved')
                  )
                """,
                [*attempt_ids, question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION],
            ).fetchall()
        ]
        attempts = [
            attempt for attempt in attempts
            if attempt.get("node_id") == node_id and _is_current_attempt_evidence(conn, attempt)
        ]
    if not attempts:
        attempts = [
            db.attempt_row_to_dict(row)
            for row in conn.execute(
                """
                select a.*
                from attempts a
                join question_items q on q.id = a.question_id
                where a.node_id = ?
                  and a.grading_status = 'graded'
                  and a.evidence_status = 'active'
                  and a.answer_analysis_json <> '{}'
                  and (
                    (q.source_type = 'graph_generated' and q.item_version = ?)
                    or (q.source_type = 'evolved' and q.item_version = ?)
                    or q.source_type not in ('graph_generated', 'evolved')
                  )
                order by a.created_at desc, a.id desc
                limit 6
                """,
                (node_id, question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION),
            ).fetchall()
        ]
        attempts = [
            attempt for attempt in attempts
            if attempt.get("node_id") == node_id and _is_current_attempt_evidence(conn, attempt)
        ]

    tag_counter: Counter[str] = Counter()
    dimension_counter: Counter[str] = Counter()
    process_gaps: list[str] = []
    rollback_candidates: list[str] = []
    processed_event_ids: list[str] = []
    evidence_attempt_ids: list[str] = []
    blocking = False
    for attempt in attempts:
        evidence_attempt_ids.append(attempt["id"])
        tag_counter.update(attempt.get("error_tags") or [])
        blocking = blocking or bool(attempt.get("blocking_evidence"))
        if attempt.get("processed_evolution_event_id"):
            processed_event_ids.append(attempt["processed_evolution_event_id"])
        analysis = attempt.get("answer_analysis") or {}
        if isinstance(analysis, dict) and str(analysis.get("process_gap") or "").strip():
            process_gaps.append(str(analysis.get("process_gap")).strip()[:240])
            for item in analysis.get("comparison") or []:
                if isinstance(item, dict) and item.get("status") in {"missing", "incorrect", "unclear"}:
                    dimension_counter.update([str(item.get("dimension"))])
        cause = attempt.get("cause_analysis") or {}
        if isinstance(cause, dict):
            tag_counter.update(cause.get("error_tags") or [])
            dimension_counter.update(cause.get("unstable_dimensions") or [])
            process_gap = str(cause.get("process_gap") or "").strip()
            if process_gap:
                process_gaps.append(process_gap[:240])
            rollback_candidates.extend(
                node_id for node_id in cause.get("rollback_candidates", [])
                if isinstance(node_id, str)
            )
            if isinstance(cause.get("rollback_node_id"), str):
                rollback_candidates.append(cause["rollback_node_id"])

    created_question_ids: list[str] = []
    for event_id in dict.fromkeys(processed_event_ids):
        row = conn.execute(
            "select created_question_ids_json from evolution_events where id = ?",
            (event_id,),
        ).fetchone()
        if row:
            created_question_ids.extend(db.json_load(row["created_question_ids_json"], []))

    signal.update({
        "evidence_attempt_ids": list(dict.fromkeys(evidence_attempt_ids)),
        "dominant_error_tags": [tag for tag, _ in tag_counter.most_common()],
        "unstable_dimensions": [dimension for dimension, _ in dimension_counter.most_common() if dimension],
        "process_gaps": list(dict.fromkeys(process_gaps))[:3],
        "rollback_candidates": list(dict.fromkeys(rollback_candidates)),
        "created_question_ids": list(dict.fromkeys(created_question_ids)),
        "blocking_evidence": blocking,
    })
    eval_signal = _latest_evaluation_decision_signal(conn, node_id, signal["evidence_attempt_ids"])
    if eval_signal:
        signal.update(eval_signal)
        if eval_signal.get("target_error_tags"):
            signal["dominant_error_tags"] = list(dict.fromkeys([
                *eval_signal["target_error_tags"],
                *signal["dominant_error_tags"],
            ]))
        if eval_signal.get("target_dimensions"):
            signal["unstable_dimensions"] = list(dict.fromkeys([
                *eval_signal["target_dimensions"],
                *signal["unstable_dimensions"],
            ]))
    return signal


def _task_for_node(
    conn: sqlite3.Connection,
    node_id: str,
    task_type: str,
    reason: str,
    *,
    planning_signal: dict[str, Any] | None = None,
    preferred_kinds: list[str] | None = None,
    slot_index: int = 0,
    ignore_signal_for_selection: bool = False,
) -> dict[str, Any]:
    signal = planning_signal or _latest_planning_signal(conn, node_id)
    signal_kind_prefs = signal.get("preferred_question_kinds") if isinstance(signal.get("preferred_question_kinds"), list) else []
    kind_prefs = preferred_kinds or list(dict.fromkeys([
        *[str(kind) for kind in signal_kind_prefs if str(kind).strip()],
        *(_preferred_kinds_for_slot(task_type, slot_index) or []),
    ]))
    question = db.find_question_for_node(
        conn,
        node_id,
        prefer_evolved=task_type != "learn",
        preferred_kinds=kind_prefs,
        target_error_tags=[] if ignore_signal_for_selection else signal.get("dominant_error_tags"),
        unstable_dimensions=[] if ignore_signal_for_selection else signal.get("unstable_dimensions"),
        preferred_question_ids=[] if ignore_signal_for_selection else signal.get("created_question_ids"),
        rotate_seed=f"{task_type}:{slot_index}:{node_id}:{','.join(signal.get('evidence_attempt_ids', []))}",
    )
    node = db.get_graph_node(conn, node_id)
    return {
        "task_id": f"T-{uuid.uuid4().hex[:8]}",
        "node_id": node_id,
        "node_name": node.get("name", node_id),
        "task_type": task_type,
        "reason": reason,
        "estimated_minutes": 12 if task_type in {"remediate", "rollback"} else 8,
        "question_id": question["id"],
        "question": question,
        "essence": node.get("teaching_contract", {}).get("one_sentence_essence") or node.get("essence_for_child", ""),
        "planning_signal": signal,
        "selected_question_reason": question.get("selection_reason", "latest_approved_candidate"),
    }


def _task_prompt_signature(task: dict[str, Any]) -> str:
    question = task.get("question") if isinstance(task.get("question"), dict) else {}
    prompt = str(question.get("prompt") or "")
    prompt = re.sub(r"\s*本题重点：[^。]*。?\s*$", "", prompt)
    prompt = re.sub(r"\s+", "", prompt)
    return prompt[:240]


def _question_problem_family_id(question: dict[str, Any]) -> str:
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    node_alignment = question.get("node_alignment") if isinstance(question.get("node_alignment"), dict) else {}
    quality = question.get("quality") if isinstance(question.get("quality"), dict) else {}
    return str(
        question.get("problem_family_id")
        or source.get("problem_family_id")
        or node_alignment.get("problem_family_id")
        or quality.get("problem_family_id")
        or ""
    ).strip()


def _question_core_stem_id(question: dict[str, Any]) -> str:
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    node_alignment = question.get("node_alignment") if isinstance(question.get("node_alignment"), dict) else {}
    quality = question.get("quality") if isinstance(question.get("quality"), dict) else {}
    return str(
        question.get("core_stem_id")
        or source.get("core_stem_id")
        or node_alignment.get("core_stem_id")
        or quality.get("core_stem_id")
        or ""
    ).strip()


def _question_problem_instance_id(question: dict[str, Any]) -> str:
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    node_alignment = question.get("node_alignment") if isinstance(question.get("node_alignment"), dict) else {}
    quality = question.get("quality") if isinstance(question.get("quality"), dict) else {}
    return str(
        question.get("problem_instance_id")
        or source.get("problem_instance_id")
        or node_alignment.get("problem_instance_id")
        or quality.get("problem_instance_id")
        or ""
    ).strip()


def _task_core_signature(task: dict[str, Any]) -> str:
    question = task.get("question") if isinstance(task.get("question"), dict) else {}
    if not question:
        return ""
    return question_bank.canonical_core_signature(question)


def _task_round_identity_signatures(task: dict[str, Any]) -> set[str]:
    question = task.get("question") if isinstance(task.get("question"), dict) else {}
    signatures = {f"prompt:{_task_prompt_signature(task)}"}
    core_signature = _task_core_signature(task)
    if core_signature:
        signatures.add(f"core:{core_signature}")
    problem_family_id = _question_problem_family_id(question)
    if problem_family_id:
        signatures.add(f"family:{problem_family_id}")
    core_stem_id = _question_core_stem_id(question)
    if core_stem_id:
        signatures.add(f"stem:{core_stem_id}")
    problem_instance_id = _question_problem_instance_id(question)
    if problem_instance_id:
        signatures.add(f"problem_instance:{problem_instance_id}")
    return signatures


def _is_picture_level_task(task: dict[str, Any]) -> bool:
    question = task.get("question") if isinstance(task.get("question"), dict) else {}
    return question_bank.is_picture_level_challenge_item(question)


def picture_level_task_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for task in tasks if _is_picture_level_task(task))


def node_local_mainline_task_count(tasks: list[dict[str, Any]]) -> int:
    return sum(
        1
        for task in tasks
        if question_bank.is_node_local_mainline_item(task.get("question") if isinstance(task.get("question"), dict) else {})
    )


def planning_signal_refs(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for task in tasks:
        for signal in _task_planning_signals(task):
            evidence_ids = _signal_evidence_ids(signal)
            decision_id = str(signal.get("evaluation_decision_id") or "")
            node_id = str(signal.get("node_id") or task.get("node_id") or "")
            if not evidence_ids and not decision_id:
                continue
            key = (node_id, decision_id, tuple(evidence_ids))
            if key in seen:
                continue
            seen.add(key)
            refs.append({
                "node_id": node_id,
                "evaluation_decision_id": decision_id,
                "evidence_attempt_ids": evidence_ids,
            })
    return refs


def round_structure(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "repair_or_prerequisite_count": sum(
            1 for task in tasks if task.get("task_type") in {"rollback", "prerequisite_probe", "remediate", "retest"}
        ),
        "consolidation_count": sum(1 for task in tasks if task.get("task_type") in {"learn", "remediate", "retest"}),
        "stretch_count": picture_level_task_count(tasks),
    }


def _signal_evidence_ids(signal: dict[str, Any]) -> list[str]:
    return [
        str(attempt_id)
        for attempt_id in (signal.get("evidence_attempt_ids") if isinstance(signal.get("evidence_attempt_ids"), list) else [])
        if str(attempt_id).strip()
    ]


def _signal_identity(signal: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(signal.get("node_id") or ""),
        str(signal.get("evaluation_decision_id") or ""),
        tuple(_signal_evidence_ids(signal)),
    )


def _task_planning_signals(task: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    primary = task.get("planning_signal") if isinstance(task.get("planning_signal"), dict) else {}
    if primary:
        signals.append(primary)
    merged = task.get("merged_planning_signals")
    if isinstance(merged, list):
        signals.extend(signal for signal in merged if isinstance(signal, dict) and signal)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for signal in signals:
        identity = _signal_identity(signal)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(signal)
    return unique


def quality_gates(conn: sqlite3.Connection, tasks: list[dict[str, Any]]) -> dict[str, bool]:
    question_ids = [str(task.get("question_id") or "") for task in tasks if str(task.get("question_id") or "").strip()]
    signatures = [_task_prompt_signature(task) for task in tasks]
    core_signatures = []
    for task in tasks:
        core_signature = _task_core_signature(task)
        if core_signature:
            core_signatures.append(core_signature)
    problem_family_ids: list[str] = []
    core_stem_ids: list[str] = []
    problem_instance_ids: list[str] = []
    current_active = True
    graph_bound = True
    no_low_age_mechanical_padding = True
    for task in tasks:
        node_id = str(task.get("node_id") or "")
        if not node_id or not conn.execute("select 1 from graph_nodes where id = ? limit 1", (node_id,)).fetchone():
            graph_bound = False
        try:
            question = db.get_question(conn, str(task.get("question_id") or ""))
        except KeyError:
            current_active = False
            no_low_age_mechanical_padding = False
            continue
        if question.get("node_id") != node_id or not db.is_child_schedulable_question(conn, question):
            current_active = False
        raw_quality = question.get("quality") if isinstance(question.get("quality"), dict) else {}
        review_check = question.get("review_agent_check") if isinstance(question.get("review_agent_check"), dict) else {}
        problem_family_id = _question_problem_family_id(question)
        core_stem_id = _question_core_stem_id(question)
        problem_instance_id = _question_problem_instance_id(question)
        if problem_family_id:
            problem_family_ids.append(problem_family_id)
        if core_stem_id:
            core_stem_ids.append(core_stem_id)
        if problem_instance_id:
            problem_instance_ids.append(problem_instance_id)
        if (
            raw_quality.get("no_mechanical_drill") is not True
            and review_check.get("no_mechanical_drill") is not True
        ):
            no_low_age_mechanical_padding = False
    semantic_unique = (
        len(tasks) == LEARNING_ROUND_TASK_COUNT
        and len(set(core_signatures)) == len(core_signatures)
        and len(problem_instance_ids) == len(tasks)
        and len(set(problem_family_ids)) == len(problem_family_ids)
        and len(set(core_stem_ids)) == len(core_stem_ids)
        and len(set(problem_instance_ids)) == len(problem_instance_ids)
    )
    return {
        "current_active_question_bank": current_active and len(tasks) == LEARNING_ROUND_TASK_COUNT,
        "unique_questions": len(question_ids) == LEARNING_ROUND_TASK_COUNT and len(set(question_ids)) == len(question_ids),
        "unique_prompt_surfaces": len(signatures) == LEARNING_ROUND_TASK_COUNT and len(set(signatures)) == len(signatures),
        "unique_semantic_cores": semantic_unique,
        "graph_bound_tasks": graph_bound and len(tasks) == LEARNING_ROUND_TASK_COUNT,
        "no_low_age_mechanical_padding": no_low_age_mechanical_padding and len(tasks) == LEARNING_ROUND_TASK_COUNT,
        "all_repair_tasks_trace_valid_evidence": all(
            bool([signal for signal in _task_planning_signals(task) if _signal_evidence_ids(signal)])
            for task in tasks
            if task.get("task_type") in SIGNAL_TRACED_TASK_TYPES
        ),
        "planning_signal_refs_cover_source_nodes": all(
            _task_signal_sources_are_covered(task)
            for task in tasks
            if task.get("task_type") in SIGNAL_TRACED_TASK_TYPES
        ),
    }


def _task_signal_sources_are_covered(task: dict[str, Any]) -> bool:
    source_node_ids = {
        str(source_node_id)
        for source_node_id in (task.get("source_node_ids") if isinstance(task.get("source_node_ids"), list) else [])
        if str(source_node_id).strip()
    }
    if not source_node_ids:
        return False
    signal_source_ids = {
        str(signal.get("node_id") or "")
        for signal in _task_planning_signals(task)
        if _signal_evidence_ids(signal)
    }
    return source_node_ids <= signal_source_ids


def _merge_task_reason(
    task: dict[str, Any],
    reason: str,
    source_node_id: str,
    incoming_signal: dict[str, Any] | None = None,
) -> None:
    if reason and reason not in task["reason"]:
        task["reason"] = f"{task['reason']} Also: {reason}"
    sources = task.setdefault("source_node_ids", [])
    if source_node_id not in sources:
        sources.append(source_node_id)
    if not isinstance(incoming_signal, dict) or not incoming_signal:
        return
    if not _signal_evidence_ids(incoming_signal) and not str(incoming_signal.get("evaluation_decision_id") or ""):
        return
    existing = {_signal_identity(signal) for signal in _task_planning_signals(task)}
    if _signal_identity(incoming_signal) in existing:
        return
    merged = task.setdefault("merged_planning_signals", [])
    if isinstance(merged, list):
        merged.append(incoming_signal)


def _preferred_kinds_for_slot(task_type: str, slot_index: int) -> list[str] | None:
    base = list(QUESTION_KIND_PREFS.get(task_type) or [])
    slots = ROUND_KIND_SLOTS.get(task_type) or []
    if not base:
        return None
    if not slots:
        return base
    slot = list(slots[slot_index % len(slots)])
    return [*slot, *(kind for kind in base if kind not in slot)]


def _append_task(
    conn: sqlite3.Connection,
    tasks: list[dict[str, Any]],
    scheduled_node_ids: set[str],
    scheduled_question_ids: set[str],
    scheduled_round_signatures: set[str],
    node_id: str,
    task_type: str,
    reason: str,
    source_node_id: str,
    planning_signal: dict[str, Any] | None = None,
) -> bool:
    for task in tasks:
        if task["node_id"] == node_id:
            _merge_task_reason(task, reason, source_node_id, planning_signal)
            return False

    task = None
    slot_index = len(tasks)
    max_attempts = max(1, len(ROUND_KIND_SLOTS.get(task_type) or []), len(QUESTION_KIND_PREFS.get(task_type) or []))
    for attempt_index in range(max_attempts):
        candidate = _task_for_node(
            conn,
            node_id,
            task_type,
            reason,
            planning_signal=planning_signal,
            slot_index=slot_index + attempt_index,
        )
        if candidate["question_id"] in scheduled_question_ids:
            continue
        if _task_round_identity_signatures(candidate) & scheduled_round_signatures:
            continue
        task = candidate
        break
    if task is None:
        broad_kinds = list(dict.fromkeys([
            *(_preferred_kinds_for_slot(task_type, slot_index) or []),
            *(QUESTION_KIND_PREFS.get(task_type) or []),
            *(QUESTION_KIND_PREFS.get("learn") or []),
        ]))
        for attempt_index, kind in enumerate(broad_kinds, start=max_attempts):
            candidate = _task_for_node(
                conn,
                node_id,
                task_type,
                reason,
                planning_signal=planning_signal,
                preferred_kinds=[kind, *(other for other in broad_kinds if other != kind)],
                slot_index=slot_index + attempt_index,
                ignore_signal_for_selection=True,
            )
            if candidate["question_id"] in scheduled_question_ids:
                continue
            if _task_round_identity_signatures(candidate) & scheduled_round_signatures:
                continue
            task = candidate
            break
    if task is None:
        return False
    task["source_node_ids"] = [source_node_id]
    for existing in tasks:
        if existing["question_id"] == task["question_id"]:
            _merge_task_reason(existing, reason, source_node_id, planning_signal)
            scheduled_node_ids.add(node_id)
            return False

    tasks.append(task)
    scheduled_node_ids.add(node_id)
    scheduled_question_ids.add(task["question_id"])
    scheduled_round_signatures.update(_task_round_identity_signatures(task))
    return True


def _strengthen_picture_level_round(
    conn: sqlite3.Connection,
    tasks: list[dict[str, Any]],
    scheduled_node_ids: set[str],
    scheduled_question_ids: set[str],
    scheduled_round_signatures: set[str],
) -> None:
    if picture_level_task_count(tasks) >= MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
        return
    preferred_kinds = [
        "stretch_transfer",
        "model_selection",
        "two_method_compare",
        "variant",
        "transfer_retest",
        "representation",
        "boundary_case",
        "self_correction",
    ]
    for node_id in PICTURE_LEVEL_CHALLENGE_PATH:
        if picture_level_task_count(tasks) >= MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
            break
        if picture_level_task_count(tasks) >= MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
            break
        if node_id in scheduled_node_ids and any(task["node_id"] == node_id and _is_picture_level_task(task) for task in tasks):
            continue
        try:
            candidate = _task_for_node(
                conn,
                node_id,
                "learn",
                "Round requires picture-level challenge coverage.",
                planning_signal=_empty_signal(node_id),
                preferred_kinds=preferred_kinds,
                slot_index=len(tasks),
                ignore_signal_for_selection=True,
            )
        except KeyError:
            continue
        if not _is_picture_level_task(candidate):
            continue
        candidate_signatures = _task_round_identity_signatures(candidate)
        if candidate["question_id"] in scheduled_question_ids or candidate_signatures & scheduled_round_signatures:
            continue
        replace_index = None
        for index in range(len(tasks) - 1, -1, -1):
            if not _is_picture_level_task(tasks[index]):
                replace_index = index
                break
        if replace_index is None:
            if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
                continue
            tasks.append(candidate)
        else:
            old = tasks[replace_index]
            scheduled_node_ids.discard(old["node_id"])
            scheduled_question_ids.discard(old["question_id"])
            scheduled_round_signatures.difference_update(_task_round_identity_signatures(old))
            tasks[replace_index] = candidate
        candidate["source_node_ids"] = [node_id]
        scheduled_node_ids.add(candidate["node_id"])
        scheduled_question_ids.add(candidate["question_id"])
        scheduled_round_signatures.update(candidate_signatures)


def _cap_picture_level_round(
    conn: sqlite3.Connection,
    tasks: list[dict[str, Any]],
    scheduled_node_ids: set[str],
    scheduled_question_ids: set[str],
    scheduled_round_signatures: set[str],
) -> None:
    while picture_level_task_count(tasks) > MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
        replaced = False
        for index in range(len(tasks) - 1, -1, -1):
            old = tasks[index]
            if not _is_picture_level_task(old):
                continue
            other_question_ids = scheduled_question_ids - {old["question_id"]}
            other_signatures = set(scheduled_round_signatures)
            other_signatures.difference_update(_task_round_identity_signatures(old))
            for attempt_index, kind in enumerate(NODE_LOCAL_MAINLINE_KIND_PREFS):
                try:
                    candidate = _task_for_node(
                        conn,
                        old["node_id"],
                        old.get("task_type", "learn"),
                        old.get("reason", "Use node-local mainline evidence before extension."),
                        planning_signal=old.get("planning_signal") if isinstance(old.get("planning_signal"), dict) else _empty_signal(old["node_id"]),
                        preferred_kinds=[kind, *(other for other in NODE_LOCAL_MAINLINE_KIND_PREFS if other != kind)],
                        slot_index=index + attempt_index,
                        ignore_signal_for_selection=True,
                    )
                except KeyError:
                    continue
                if not question_bank.is_node_local_mainline_item(candidate.get("question", {})):
                    continue
                candidate_signatures = _task_round_identity_signatures(candidate)
                if candidate["question_id"] in other_question_ids or candidate_signatures & other_signatures:
                    continue
                candidate["source_node_ids"] = list(old.get("source_node_ids") or [old["node_id"]])
                tasks[index] = candidate
                scheduled_question_ids.discard(old["question_id"])
                scheduled_round_signatures.difference_update(_task_round_identity_signatures(old))
                scheduled_question_ids.add(candidate["question_id"])
                scheduled_round_signatures.update(candidate_signatures)
                replaced = True
                break
            if replaced:
                break
        if not replaced:
            break


def _rollback_targets(conn: sqlite3.Connection, node_id: str, planning_signal: dict[str, Any] | None = None) -> list[str]:
    node = db.get_graph_node(conn, node_id)
    raw = (
        (planning_signal or {}).get("rollback_candidates")
        or node.get("error_diagnosis", {}).get("rollback_to")
        or node.get("prerequisites")
        or []
    )
    return [target for target in raw if conn.execute("select 1 from graph_nodes where id = ?", (target,)).fetchone()]


def _current_mastered_node_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        row["node_id"]
        for row in db.current_learner_node_status_rows(conn, status_codes=("A",))
    }


def _iso_week_for_timestamp(timestamp: str) -> str:
    """ISO week key (``YYYY-Www``) that contains ``timestamp``.

    Same key shape as goal_choice_service's weekly keys; used to map the
    plan's ``now`` onto the weekly goal choice the planner honors (objective ②
    linkage). Accepts date-only and full ISO-8601 timestamps.
    """
    parsed = datetime.fromisoformat(timestamp)
    iso_year, iso_week, _ = parsed.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def _current_goal_node_ids(
    conn: sqlite3.Connection,
    *,
    iso_week: str | None = None,
) -> list[str]:
    """Weekly goal choice node ids for ``iso_week`` (objective ② linkage).

    Degrades to ``[]`` (no goal nodes) instead of raising so the linkage can
    never break plan generation: a missing record, a malformed week key, or a
    non-list ``node_ids`` payload all mean "no goal nodes".
    """
    if not iso_week:
        return []
    try:
        choice = goal_choice_service.current_goal_choice(conn, iso_week=iso_week)
    except ValueError:
        return []
    if not isinstance(choice, dict):
        return []
    node_ids = choice.get("node_ids")
    if not isinstance(node_ids, list):
        return []
    return [str(node_id) for node_id in node_ids if str(node_id).strip()]


def _core_learn_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in CORE_LEARN_PATH)
    order_case = " ".join(f"when ? then {index}" for index, node_id in enumerate(CORE_LEARN_PATH))
    params = [*CORE_LEARN_PATH, *CORE_LEARN_PATH]
    mastered_node_ids = _current_mastered_node_ids(conn)
    rows = conn.execute(
        f"""
        select n.id
        from graph_nodes n
        where n.priority = 'P0'
          and n.id in ({placeholders})
        order by case n.id {order_case} else 999 end, n.sequence_band, n.id
        """,
        params,
    ).fetchall()
    return [row for row in rows if row["id"] not in mastered_node_ids]


def _broad_learn_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    mastered_node_ids = _current_mastered_node_ids(conn)
    rows = conn.execute(
        """
        select n.id
        from graph_nodes n
        order by
          case n.priority when 'P0' then 0 when 'P1' then 1 else 2 end,
          case n.summer_mode when 'core' then 0 when 'selective_core' then 1 else 2 end,
          n.sequence_band,
          n.id
        """
    ).fetchall()
    return [row for row in rows if row["id"] not in mastered_node_ids]


def _pending_confirmation_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          md.node_id,
          md.evidence_attempt_ids_json,
          md.decision_payload_json,
          md.applied,
          md.agent_run_id,
          ar.status as agent_run_status,
          ar.confidence as agent_run_confidence,
          n.sequence_band,
          md.created_at
        from mastery_decisions md
        left join agent_runs ar on ar.id = md.agent_run_id
        join graph_nodes n on n.id = md.node_id
        order by md.created_at desc, md.rowid desc
        """
    ).fetchall()
    seen_nodes: set[str] = set()
    pending: list[dict[str, Any]] = []
    for row in rows:
        node_id = row["node_id"]
        if node_id in seen_nodes:
            continue
        payload = db.json_load(row["decision_payload_json"], {})
        if not isinstance(payload, dict) or not payload.get("confirmation_needed"):
            continue
        if not _evaluation_decision_is_planner_usable(row, payload):
            continue
        evidence_ids = db.json_load(row["evidence_attempt_ids_json"], [])
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        evidence_ids = [str(item) for item in evidence_ids if str(item).strip()]
        payload_evidence_ids = payload.get("evidence_attempt_ids")
        if not isinstance(payload_evidence_ids, list):
            continue
        payload_evidence_ids = [str(item) for item in payload_evidence_ids if str(item).strip()]
        if (
            payload.get("schema_version") != "2026-07-08.evaluation-diagnosis.v2"
            or payload.get("threshold_policy_version") != "2026-07-08.single-strong-is-not-stable.v1"
            or payload.get("node_id") != node_id
            or not _has_valid_planner_signal(payload)
            or not evidence_ids
            or payload_evidence_ids != evidence_ids
        ):
            continue
        valid = True
        for attempt_id in evidence_ids:
            try:
                attempt = db.get_attempt(conn, attempt_id)
            except KeyError:
                valid = False
                break
            if attempt.get("node_id") != node_id or not _is_current_attempt_evidence(conn, attempt):
                valid = False
                break
        if not valid:
            continue
        seen_nodes.add(node_id)
        pending.append({
            "node_id": node_id,
            "sequence_band": int(row["sequence_band"] or 99),
            "created_at": row["created_at"],
            "confirmation_type": payload.get("confirmation_type", ""),
            "intervention_need": payload.get("intervention_need", ""),
        })
    return sorted(pending, key=lambda item: (item["sequence_band"], item["created_at"], item["node_id"]))


_TRACE_GRAPH_CACHE: dict[str, Any] | None = None


def _trace_graph() -> dict[str, Any]:
    """Lazily load the raw knowledge graph JSON for trace-back lookups.

    The daily-runtime DB stores per-node raw_json but not the top-level
    strong_unlock_edges / prereq_strength contract, so rollback targeting needs
    the graph file. Loaded once per process; the graph is frozen while v20
    question generation runs, so a cached snapshot is consistent.
    """
    global _TRACE_GRAPH_CACHE
    if _TRACE_GRAPH_CACHE is None:
        from .graph_runtime import DEFAULT_GRAPH_RELATIVE_PATH

        path = Path(__file__).resolve().parents[1] / DEFAULT_GRAPH_RELATIVE_PATH
        _TRACE_GRAPH_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _TRACE_GRAPH_CACHE


def _is_trusted_signal_task_target(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    task_node_id: str,
    signal_node_id: str,
) -> bool:
    if task_node_id == signal_node_id:
        return True
    if task_type not in {"rollback", "prerequisite_probe"}:
        return False
    try:
        signal_node = db.get_graph_node(conn, signal_node_id)
    except KeyError:
        return False
    graph_targets = [
        *(
            signal_node.get("error_diagnosis", {}).get("rollback_to")
            if isinstance(signal_node.get("error_diagnosis", {}), dict)
            else []
        ),
        *(signal_node.get("prerequisites") or []),
    ]
    graph_targets = [
        str(node_id)
        for node_id in graph_targets
        if str(node_id).strip()
        and conn.execute("select 1 from graph_nodes where id = ?", (str(node_id),)).fetchone()
    ]
    trusted = set(graph_targets)
    # Trace-back integration: strong unlocks-only edges (graph top-level
    # strong_unlock_edges) are legitimate rollback targets too — they are
    # semantic strong dependencies (review doc 6.2). ordered_prerequisite_
    # candidates returns the full chain closest-first/strong-first; only
    # candidates that exist in the DB snapshot are trusted.
    for candidate in ordered_prerequisite_candidates(_trace_graph(), signal_node_id):
        if conn.execute("select 1 from graph_nodes where id = ?", (candidate,)).fetchone():
            trusted.add(candidate)
    return task_node_id in trusted


def _signal_uses_current_evidence(
    conn: sqlite3.Connection,
    *,
    task: dict[str, Any],
    signal: dict[str, Any],
    source_node_ids: list[str],
) -> bool:
    evidence_ids = _signal_evidence_ids(signal)
    if not evidence_ids:
        return True
    signal_node_id = str(signal.get("node_id") or "").strip()
    if not signal_node_id or signal_node_id not in source_node_ids:
        return False
    if not _is_trusted_signal_task_target(
        conn,
        task_type=str(task.get("task_type") or ""),
        task_node_id=str(task.get("node_id") or ""),
        signal_node_id=signal_node_id,
    ):
        return False
    decision_id = str(signal.get("evaluation_decision_id") or "").strip()
    if decision_id:
        decision_row = conn.execute(
            """
            select
              md.node_id,
              md.evidence_attempt_ids_json,
              md.decision_payload_json,
              md.applied,
              md.agent_run_id,
              ar.status as agent_run_status,
              ar.confidence as agent_run_confidence
            from mastery_decisions md
            left join agent_runs ar on ar.id = md.agent_run_id
            where md.id = ?
            """,
            (decision_id,),
        ).fetchone()
        if not decision_row or decision_row["node_id"] != signal_node_id:
            return False
        decision_evidence_ids = db.json_load(decision_row["evidence_attempt_ids_json"], [])
        if not isinstance(decision_evidence_ids, list):
            return False
        decision_evidence_ids = [
            str(attempt_id) for attempt_id in decision_evidence_ids if str(attempt_id).strip()
        ]
        payload = db.json_load(decision_row["decision_payload_json"], {})
        if not isinstance(payload, dict) or not _evaluation_decision_is_planner_usable(decision_row, payload):
            return False
        payload_evidence_ids = payload.get("evidence_attempt_ids") if isinstance(payload, dict) else None
        if not isinstance(payload_evidence_ids, list):
            return False
        payload_evidence_ids = [
            str(attempt_id) for attempt_id in payload_evidence_ids if str(attempt_id).strip()
        ]
        if (
            payload.get("schema_version") != "2026-07-08.evaluation-diagnosis.v2"
            or payload.get("threshold_policy_version") != "2026-07-08.single-strong-is-not-stable.v1"
            or payload.get("node_id") != signal_node_id
            or not _has_valid_planner_signal(payload)
            or decision_evidence_ids != evidence_ids
            or payload_evidence_ids != evidence_ids
        ):
            return False
    for attempt_id in evidence_ids:
        try:
            attempt = db.get_attempt(conn, attempt_id)
        except KeyError:
            return False
        if (
            attempt.get("node_id") != signal_node_id
            or attempt.get("evidence_status") != "active"
            or not _is_current_attempt_evidence(conn, attempt)
        ):
            return False
    return True


def _plan_uses_current_active_bank(conn: sqlite3.Connection, plan: dict[str, Any]) -> bool:
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    if len(tasks) != LEARNING_ROUND_TASK_COUNT:
        return False
    question_ids = [task.get("question_id") for task in tasks if task.get("question_id")]
    if len(question_ids) != LEARNING_ROUND_TASK_COUNT or len(set(question_ids)) != len(question_ids):
        return False
    round_signatures: set[str] = set()
    for task in tasks:
        try:
            question = db.get_question(conn, str(task["question_id"]))
        except (KeyError, TypeError):
            return False
        if question.get("node_id") != task.get("node_id"):
            return False
        if question.get("source_type") == "graph_generated" and question.get("item_version") != question_bank.QUESTION_BANK_VERSION:
            return False
        if question.get("source_type") == "evolved" and question.get("item_version") != question_bank.EVOLVED_ITEM_VERSION:
            return False
        if not db.is_child_schedulable_question(conn, question):
            return False
        task_question = task.get("question") if isinstance(task.get("question"), dict) else {}
        if not task_question:
            return False
        if db.question_snapshot_hash(task_question) != db.question_snapshot_hash(question):
            return False
        task_signatures = _task_round_identity_signatures(task)
        if task_signatures & round_signatures:
            return False
        round_signatures.update(task_signatures)
        source_node_ids = [
            str(source_node_id)
            for source_node_id in (task.get("source_node_ids") if isinstance(task.get("source_node_ids"), list) else [])
            if str(source_node_id).strip()
        ]
        signals = _task_planning_signals(task)
        evidence_signals = [signal for signal in signals if _signal_evidence_ids(signal)]
        if task.get("task_type") in SIGNAL_TRACED_TASK_TYPES:
            if not evidence_signals or not _task_signal_sources_are_covered(task):
                return False
        for signal in evidence_signals:
            if not _signal_uses_current_evidence(
                conn,
                task=task,
                signal=signal,
                source_node_ids=source_node_ids,
            ):
                return False
    picture_count = picture_level_task_count(tasks)
    if picture_count < MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
        return False
    if picture_count > MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
        return False
    if node_local_mainline_task_count(tasks) < MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND:
        return False
    gates = quality_gates(conn, tasks)
    if not all(gates.values()):
        return False
    return True


def plan_uses_current_active_bank(conn: sqlite3.Connection, plan: dict[str, Any]) -> bool:
    return _plan_uses_current_active_bank(conn, plan)


def _retest_is_due(conn: sqlite3.Connection, node_id: str, now: str | None = None) -> bool:
    """§2.4 due check: is this node's interval-spaced retest due at `now`?

    Reads the node's mastery_decisions history (append-only, applied rows),
    derives the retest state by replaying next_retest_at's verdict logic
    (mastery_rules.derive_retest_state), and compares `now` against the last
    judgment event + the derived interval (mastery_rules.retest_due).
    A node with no derivable schedule (no history) is always due — the
    conservative default that preserves the planner's legacy behavior for
    nodes whose status predates the unified judgment.

    Only applied rows are read (retest scheduling must consider judgment
    events that actually landed; unapplied rows are NO_CHANGE-equivalent and
    never stored). Rows without a readable verdict are skipped by the bridge
    (real legacy rows often carry new_status_code='').
    """
    rows = conn.execute(
        """
        select new_status_code, decision_payload_json, created_at
        from mastery_decisions
        where node_id = ? and applied = 1
        order by created_at asc, rowid asc
        """,
        (node_id,),
    ).fetchall()
    history = mastery_bridge.retest_history([dict(row) for row in rows])
    state = mastery_rules.derive_retest_state(history["events"])
    return mastery_rules.retest_due(state, history["last_event_at"], now or db.now_iso())


def generate_next_plan(
    conn: sqlite3.Connection,
    title: str = "今日学习",
    *,
    commit: bool = True,
    now: str | None = None,
    iso_week: str | None = None,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    scheduled_node_ids: set[str] = set()
    scheduled_question_ids: set[str] = set()
    scheduled_round_signatures: set[str] = set()
    now = now or db.now_iso()
    weak_rows = sorted(
        db.current_learner_node_status_rows(conn, status_codes=("C", "D", "B")),
        key=lambda row: (
            {"D": 0, "C": 1, "B": 2}.get(str(row.get("status_code")), 3),
            int(row.get("sequence_band") or 99),
            str(row.get("updated_at") or ""),
        ),
    )[:LEARNING_ROUND_TASK_COUNT]

    for row in weak_rows:
        node_id = row["node_id"]
        signal = _latest_planning_signal(conn, node_id)
        if row["status_code"] == "D":
            targets = _rollback_targets(conn, node_id, signal) or [node_id]
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                targets[0],
                "rollback",
                f"{node_id} is blocked; repair prerequisite first.",
                node_id,
                planning_signal=signal,
            )
        elif row["status_code"] == "C":
            targets = _rollback_targets(conn, node_id, signal)
            if targets:
                _append_task(
                    conn,
                        tasks,
                        scheduled_node_ids,
                        scheduled_question_ids,
                        scheduled_round_signatures,
                    targets[0],
                    "prerequisite_probe",
                    f"{node_id} is weak; verify prerequisite before drilling.",
                    node_id,
                    planning_signal=signal,
                )
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                node_id,
                "remediate",
                "Direct evidence is weak.",
                node_id,
                planning_signal=signal,
            )
        else:
            if not _retest_is_due(conn, node_id, now):
                # §2.4: 间隔复测未到期 (now < 末次判定事件 + 间隔) — 本轮不排复测任务。
                continue
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                node_id,
                "retest",
                "Direct evidence is unstable.",
                node_id,
                planning_signal=signal,
            )
        if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
            break

    if len(tasks) < LEARNING_ROUND_TASK_COUNT:
        for row in _pending_confirmation_rows(conn):
            node_id = row["node_id"]
            if node_id in scheduled_node_ids:
                continue
            signal = _latest_planning_signal(conn, node_id)
            # 评估要求确认 (confirmation_needed) 的复测是"教学层"确认动作
            # (§2.4: C/D 档不排间隔复测、由回查/修复流程驱动, 同属教学层),
            # 不是 §2.4 的间隔复测 — 不套用 next_retest_at 到期门控,
            # 保持"评估要求确认后尽快补测"的既有调度行为。
            task_type = "prerequisite_probe" if signal.get("confirmation_type") == "prerequisite_probe" else "retest"
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                node_id,
                task_type,
                "Evaluation requires confirmation before this node can advance.",
                node_id,
                planning_signal=signal,
            )
            if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
                break

    if len(tasks) < LEARNING_ROUND_TASK_COUNT:
        goal_week = iso_week or ""
        if not goal_week:
            try:
                goal_week = _iso_week_for_timestamp(now)
            except ValueError:
                goal_week = ""
        goal_node_ids = _current_goal_node_ids(conn, iso_week=goal_week)
        if goal_node_ids:
            # 目标联动 (M2.5 motivation follow-up objective ②): 当周有目标选择时,
            # 尚未掌握的目标节点进入主线 (learn) 任务并优先于通用主线填充。
            # 不硬塞: 已掌握 (A) 尊重状态; 已阻塞 (D) 由回查 (rollback) 阶段处理,
            # 直接教被阻塞节点违反回查语义; 已在 scheduled_node_ids 的
            # (弱档/待确认阶段已排) 不重复。既有调度 (retest 门控、回查、B 档、
            # 图片挑战强化/封顶) 不动, 目标是增量。
            status_rows = db.current_learner_node_status_rows(conn, status_codes=("A", "D"))
            skip_node_ids = {row["node_id"] for row in status_rows}
            for node_id in goal_node_ids:
                if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
                    break
                if node_id in scheduled_node_ids or node_id in skip_node_ids:
                    continue
                if not conn.execute("select 1 from graph_nodes where id = ? limit 1", (node_id,)).fetchone():
                    continue
                _append_task(
                    conn,
                    tasks,
                    scheduled_node_ids,
                    scheduled_question_ids,
                    scheduled_round_signatures,
                    node_id,
                    "learn",
                    "Child-selected weekly goal.",
                    node_id,
                    planning_signal=_empty_signal(node_id),
                )

    if len(tasks) < LEARNING_ROUND_TASK_COUNT:
        for row in _core_learn_rows(conn):
            if row["id"] in scheduled_node_ids:
                continue
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                row["id"],
                "learn",
                "Initial summer core path.",
                row["id"],
                planning_signal=_empty_signal(row["id"]),
            )
            if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
                break

    if len(tasks) < LEARNING_ROUND_TASK_COUNT:
        for row in _broad_learn_rows(conn):
            if row["id"] in scheduled_node_ids:
                continue
            _append_task(
                conn,
                tasks,
                scheduled_node_ids,
                scheduled_question_ids,
                scheduled_round_signatures,
                row["id"],
                "learn",
                "Round top-up with graph-bound challenge practice.",
                row["id"],
                planning_signal=_empty_signal(row["id"]),
            )
            if len(tasks) >= LEARNING_ROUND_TASK_COUNT:
                break

    _strengthen_picture_level_round(
        conn,
        tasks,
        scheduled_node_ids,
        scheduled_question_ids,
        scheduled_round_signatures,
    )
    _cap_picture_level_round(
        conn,
        tasks,
        scheduled_node_ids,
        scheduled_question_ids,
        scheduled_round_signatures,
    )

    final_tasks = tasks[:LEARNING_ROUND_TASK_COUNT]
    gates = quality_gates(conn, final_tasks)
    if not all(gates.values()):
        failed = [key for key, value in gates.items() if not value]
        raise PlannerPlanError(
            "Planner quality gates failed: " + ", ".join(failed),
            quality_gates=gates,
            task_count=len(final_tasks),
        )
    plan = {
        "id": f"P-{uuid.uuid4().hex[:12]}",
        "title": title,
        "plan_policy_version": PLANNER_POLICY_VERSION,
        "planner_policy_version": PLANNER_POLICY_VERSION,
        "round_size": LEARNING_ROUND_TASK_COUNT,
        "primary_target_node_id": final_tasks[0]["node_id"] if final_tasks else "",
        "round_structure": round_structure(final_tasks),
        "planning_signal_refs": planning_signal_refs(final_tasks),
        "quality_gates": gates,
        "confidence": 1.0,
        "tasks": final_tasks,
        "created_at": db.now_iso(),
    }
    conn.execute(
        """
        insert into generated_plans(
          id, title, tasks_json, planner_policy_version, plan_meta_json, created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            plan["id"],
            title,
            db.json_dump(plan["tasks"]),
            PLANNER_POLICY_VERSION,
            db.json_dump({
                "plan_policy_version": plan["plan_policy_version"],
                "round_size": plan["round_size"],
                "primary_target_node_id": plan["primary_target_node_id"],
                "round_structure": plan["round_structure"],
                "planning_signal_refs": plan["planning_signal_refs"],
                "quality_gates": plan["quality_gates"],
                "confidence": plan["confidence"],
            }),
            plan["created_at"],
        ),
    )
    if commit:
        conn.commit()
    return plan


def latest_or_create_plan(conn: sqlite3.Connection, *, commit: bool = True) -> dict[str, Any]:
    row = conn.execute("select * from generated_plans order by created_at desc, rowid desc limit 1").fetchone()
    if not row:
        return generate_next_plan(conn, commit=commit)
    plan = {
        "id": row["id"],
        "title": row["title"],
        "plan_policy_version": row["planner_policy_version"],
        "planner_policy_version": row["planner_policy_version"],
        "tasks": db.json_load(row["tasks_json"], []),
        "created_at": row["created_at"],
    }
    if row["planner_policy_version"] != PLANNER_POLICY_VERSION:
        return generate_next_plan(conn, title=plan.get("title") or "今日学习", commit=commit)
    if not _plan_uses_current_active_bank(conn, plan):
        return generate_next_plan(conn, title=plan.get("title") or "今日学习", commit=commit)
    meta = db.json_load(row["plan_meta_json"], {})
    if not isinstance(meta, dict):
        meta = {}
    plan["round_size"] = meta.get("round_size", LEARNING_ROUND_TASK_COUNT)
    plan["primary_target_node_id"] = meta.get("primary_target_node_id") or (plan["tasks"][0]["node_id"] if plan["tasks"] else "")
    plan["round_structure"] = round_structure(plan["tasks"])
    plan["planning_signal_refs"] = planning_signal_refs(plan["tasks"])
    plan["quality_gates"] = quality_gates(conn, plan["tasks"])
    plan["confidence"] = float(meta.get("confidence", 1.0) or 1.0)
    return plan
