"""Compile model-authored question candidates into runnable question artifacts.

The candidate is untrusted authoring output.  This module owns the narrow
boundary between that output and the child-facing interaction/assessment
contracts used by the runtime.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from . import child_prompt, fixed_answer_assessment


CANDIDATE_SCHEMA_VERSION = "question-candidate.v1"
CONTENT_SCHEMA_VERSION = "question-content.v1"
ARTIFACT_SCHEMA_VERSION = "question-artifact.v1"
RESPONSE_SCHEMA_VERSION = "question-response.v1"
ASSESSMENT_SCHEMA_VERSION = "question-assessment.v1"
FIXED_RESPONSE_SCHEMA_VERSION = fixed_answer_assessment.FIXED_RESPONSE_SCHEMA_VERSION

FIXED_RESPONSE_MODES = frozenset({"single_choice", "multi_choice", "fill_blank"})
RESPONSE_MODES = FIXED_RESPONSE_MODES | {"short_answer"}
TASK_TYPES = frozenset({"calculation", "reasoning", "application"})
DECIMAL_NORMALIZATION_POLICIES = frozenset({
    "decimal",
    "trim_whitespace",
    "trim_spaces",
    "trim_whitespace_and_leading_zeros",
    "normalize_decimal",
    "trim",
    "trim, normalize_decimal",
    "trim,normalize_decimal",
    "trim_whitespace;trim_trailing_zeros",
    "trim_spaces_and_trailing_zeros",
})
CHOICE_CONTROL_TYPES = frozenset({"single_choice", "multi_choice", "choice_single", "choice_multiple"})
DECIMAL_CONTROL_TYPES = frozenset({"text_input", "input", "number_input", "decimal_input"})
CONTENT_RESPONSE_MODES = frozenset({"single_choice", "multi_choice", "fill_blank"})


class ContractError(ValueError):
    """Raised when a candidate, artifact, or response cannot be trusted."""


def _content_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _content_list(value: Any, field: str, *, allow_duplicates: bool = False) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} must be a non-empty string list")
    values = [_content_text(item, f"{field}[]") for item in value]
    if not allow_duplicates and len(values) != len(set(values)):
        raise ContractError(f"{field} must not contain duplicates")
    return values


def _content_prompt_and_blanks(prompt: str, response_mode: str) -> tuple[str, int]:
    blank_count = prompt.count("____")
    if response_mode == "fill_blank" and blank_count < 1:
        raise ContractError("fill_blank prompt requires ____ placeholders")
    if response_mode != "fill_blank" and blank_count:
        raise ContractError("choice prompt cannot contain ____ placeholders")
    return prompt.replace("____", "（ ）"), blank_count


def _content_answer_type(values: list[str]) -> tuple[str, str]:
    try:
        for value in values:
            Decimal(value)
    except InvalidOperation:
        return "text", "exact"
    return "decimal", "decimal"


def compile_question_content(content: dict[str, Any], *, identity: dict[str, Any]) -> dict[str, Any]:
    """Compile the minimal model content format into a runnable artifact."""
    content = deepcopy(_object(content, "content"))
    if content.get("schema_version") != CONTENT_SCHEMA_VERSION:
        raise ContractError("unsupported content schema version")
    task_type = _content_text(content.get("task_type"), "task_type")
    response_mode = _content_text(content.get("response_mode"), "response_mode")
    if response_mode not in CONTENT_RESPONSE_MODES:
        raise ContractError("content response_mode must be a fixed-answer mode")
    prompt = _content_text(content.get("prompt"), "prompt")
    choices = content.get("choices")
    if not isinstance(choices, list):
        raise ContractError("choices must be a list")
    choices = [_content_text(choice, "choices[]") for choice in choices]
    if len(choices) != len(set(choices)):
        raise ContractError("choices must not contain duplicate text")
    answer = _content_list(
        content.get("answer"),
        "answer",
        allow_duplicates=response_mode == "fill_blank",
    )
    child_prompt_text, blank_count = _content_prompt_and_blanks(prompt, response_mode)
    if response_mode == "single_choice":
        if len(choices) < 2 or len(answer) != 1 or answer[0] not in choices:
            raise ContractError("single-choice answer must be one declared choice")
    elif response_mode == "multi_choice":
        if len(choices) < 2 or len(answer) != len(set(answer)) or not set(answer).issubset(set(choices)):
            raise ContractError("multi-choice answers must be declared choices")
    elif len(answer) != blank_count:
        raise ContractError("fill-blank answer count must match ____ count")

    question_id = _content_text(identity.get("question_id"), "identity.question_id")
    node_id = _content_text(identity.get("node_id"), "identity.node_id")
    qf_id = _content_text(identity.get("qf_id"), "identity.qf_id")
    slot_id = _content_text(identity.get("slot_id"), "identity.slot_id")
    if response_mode == "fill_blank":
        controls = [
            {
                "id": f"result_{index}",
                "control_type": "text_input",
                "value_type": _content_answer_type(answer)[0],
                "label": f"第{index}空",
                "order": index,
                "required": True,
            }
            for index in range(1, blank_count + 1)
        ]
        targets = [
            {
                "control_id": control["id"],
                "answer_type": _content_answer_type([answer[index - 1]])[0],
                "accepted_values": [answer[index - 1]],
                "normalization": _content_answer_type([answer[index - 1]])[1],
            }
            for index, control in enumerate(controls, start=1)
        ]
        fields = [
            {"id": control["id"], "label": control["label"]}
            for control in controls
        ]
        interaction_type = "fill_blank"
    else:
        controls = []
        choice_items = [
            {"id": f"choice_{index}", "label": choice, "order": index}
            for index, choice in enumerate(choices, start=1)
        ]
        targets = [{"choice_id": next(item["id"] for item in choice_items if item["label"] == value)} for value in answer]
        fields = []
        interaction_type = response_mode

    interaction_schema = {
        "schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
        "type": interaction_type,
        "response_capture": "existing_control",
        "title": "作答",
        "allow_explanation": False,
        "requires_explanation": False,
        "explanation_label": "",
        "fields": fields,
        "choices": [
            {"id": item["id"], "label": item["label"]}
            for item in (choice_items if response_mode != "fill_blank" else [])
        ],
        "formula_label": "",
        "placeholder": "",
    }
    try:
        normalized_schema = child_prompt.normalize_interaction_schema(interaction_schema, allow_legacy=False)
        surface = child_prompt.project_child_surface(
            prompt=child_prompt_text,
            prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
            interaction_schema=normalized_schema,
            allow_legacy=False,
        )
    except child_prompt.ChildPromptContractError as exc:
        raise ContractError("content cannot be rendered: " + "; ".join(exc.errors)) from exc
    grading = {"mode": "local_fixed_answer", "targets": targets}
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "identity": {
            "question_id": question_id,
            "node_id": node_id,
            "qf_id": qf_id,
            "slot_id": slot_id,
            "artifact_version": 1,
        },
        "task": {"task_type": task_type, "response_mode": response_mode},
        "content": {"prompt": prompt, "choices": choices},
        "display": {"controls": controls, "choices": interaction_schema["choices"]},
        "child_surface": {
            "prompt": surface["prompt"],
            "prompt_format": surface["prompt_format"],
            "prompt_segments": surface["prompt_segments"],
            "interaction_schema": surface["interaction_schema"],
            "interaction_rendering": surface["interaction_rendering"],
            "projection_sha256": surface["projection_sha256"],
        },
        "grading": grading,
        "diagnostic": {"node_id": node_id, "qf_id": qf_id, "slot_id": slot_id},
    }


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be an object")
    return value


def _unique_ids(items: list[dict[str, Any]], field: str) -> list[str]:
    ids = [_text(item.get("id"), f"{field}.id") for item in items]
    if len(ids) != len(set(ids)):
        raise ContractError(f"{field} ids must be unique")
    return ids


def _prompt_from_blocks(blocks: Any, *, include_blanks: bool = True) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(blocks, list) or not blocks:
        raise ContractError("content.blocks must be a non-empty list")
    prompt_parts: list[str] = []
    normalized: list[dict[str, Any]] = []
    for index, raw_block in enumerate(blocks):
        block = _object(raw_block, f"content.blocks[{index}]")
        block_type = _text(block.get("type"), f"content.blocks[{index}].type")
        if block_type == "text":
            value = _text(block.get("text"), f"content.blocks[{index}].text")
            prompt_parts.append(value)
            normalized.append({"type": "text", "text": value})
        elif block_type == "blank":
            field_id = _text(block.get("field_id"), f"content.blocks[{index}].field_id")
            if include_blanks:
                prompt_parts.append("（ ）")
                normalized.append({"type": "blank", "field_id": field_id})
        else:
            raise ContractError(f"unsupported content block type: {block_type}")
    prompt = "".join(prompt_parts).strip()
    if not prompt:
        raise ContractError("content must produce a non-empty prompt")
    return prompt, normalized


def _compile_interaction(candidate: dict[str, Any], response_mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proposal = _object(candidate.get("interaction_proposal"), "interaction_proposal")
    controls = proposal.get("controls") or []
    choices = proposal.get("choices") or []
    if not isinstance(controls, list) or not isinstance(choices, list):
        raise ContractError("interaction_proposal controls and choices must be lists")
    control_objects = [_object(item, "interaction_proposal.controls[]") for item in controls]
    choice_objects = [_object(item, "interaction_proposal.choices[]") for item in choices]
    control_ids = _unique_ids(control_objects, "interaction_proposal.controls")
    choice_ids = _unique_ids(choice_objects, "interaction_proposal.choices")

    if response_mode == "fill_blank":
        if not control_objects or not all(item.get("control_type") in DECIMAL_CONTROL_TYPES for item in control_objects):
            raise ContractError("fill_blank requires supported input controls")
        if choice_objects:
            raise ContractError("fill_blank cannot declare choices")
    elif response_mode in {"single_choice", "multi_choice"}:
        if len(choice_objects) < 2:
            raise ContractError("choice response requires at least two choices")
        if control_objects and not all(item.get("control_type") in CHOICE_CONTROL_TYPES for item in control_objects):
            raise ContractError("choice response cannot declare fill controls")
    elif response_mode == "short_answer":
        if control_objects or choice_objects:
            raise ContractError("short_answer cannot declare fixed-answer controls")

    normalized_controls: list[dict[str, Any]] = []
    for index, control in enumerate(control_objects):
        if response_mode in {"single_choice", "multi_choice"}:
            continue
        normalized_controls.append({
            "id": control_ids[index],
            "control_type": "text_input",
            "value_type": _text(control.get("value_type"), "value_type"),
            "label": _text(control.get("label"), "control.label"),
            "order": control.get("order", index + 1),
            "required": control.get("required", True),
            **({"placeholder": control["placeholder"]} if "placeholder" in control else {}),
        })
    normalized_choices: list[dict[str, Any]] = []
    for index, choice in enumerate(choice_objects):
        normalized_choices.append({
            "id": choice_ids[index],
            "label": _text(choice.get("label"), "choice.label"),
            "order": choice.get("order", index + 1),
        })

    child_schema = {
        "schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
        "type": "short_text" if response_mode == "short_answer" else response_mode,
        "response_capture": "existing_control",
        "title": "作答",
        "allow_explanation": response_mode == "short_answer",
        "requires_explanation": response_mode == "short_answer",
        "explanation_label": "请写出你的过程和理由" if response_mode == "short_answer" else "",
        "fields": [
            {
                "id": control["id"],
                "label": control["label"],
                **({"placeholder": control["placeholder"]} if "placeholder" in control else {}),
            }
            for control in normalized_controls
        ],
        "choices": [
            {"id": choice["id"], "label": choice["label"]}
            for choice in normalized_choices
        ],
        "formula_label": "",
        "placeholder": "",
    }
    try:
        normalized_schema = child_prompt.normalize_interaction_schema(
            child_schema,
            allow_legacy=False,
        )
    except child_prompt.ChildPromptContractError as exc:
        raise ContractError("interaction schema is not renderable: " + "; ".join(exc.errors)) from exc
    return normalized_schema, normalized_controls + normalized_choices


def _compile_grading(candidate: dict[str, Any], response_mode: str, controls: list[dict[str, Any]]) -> dict[str, Any]:
    proposal = _object(candidate.get("answer_proposal"), "answer_proposal")
    grading_mode = _text(proposal.get("grading_mode"), "answer_proposal.grading_mode")
    if response_mode in FIXED_RESPONSE_MODES and grading_mode != "local_fixed_answer":
        raise ContractError("fixed-answer response requires local_fixed_answer")
    if response_mode == "short_answer" and grading_mode != "model_semantic_assessment":
        raise ContractError("short_answer requires model_semantic_assessment")

    if response_mode == "short_answer":
        rubric = proposal.get("rubric")
        if not isinstance(rubric, list) or not rubric:
            raise ContractError("semantic grading requires a rubric")
        return {"mode": grading_mode, "rubric": [str(item) for item in rubric]}

    targets = proposal.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ContractError("fixed grading requires targets")
    control_ids = {item["id"] for item in controls if "control_type" in item}
    if response_mode == "fill_blank":
        if {str(item.get("control_id")) for item in targets} != control_ids:
            raise ContractError("answer target ids do not match controls")
        compiled_targets = []
        for target in targets:
            target = _object(target, "answer_proposal.targets[]")
            values = target.get("accepted_values")
            if not isinstance(values, list) or not values:
                raise ContractError("fill_blank answer target requires accepted_values")
            compiled_targets.append({
                "control_id": _text(target.get("control_id"), "answer target.control_id"),
                "answer_type": _text(target.get("answer_type"), "answer target.answer_type"),
                "accepted_values": [_text(value, "accepted value") for value in values],
                "normalization": _text(target.get("normalization"), "answer target.normalization"),
            })
            if compiled_targets[-1]["normalization"] not in DECIMAL_NORMALIZATION_POLICIES:
                raise ContractError("unsupported answer normalization policy")
            if compiled_targets[-1]["answer_type"] == "decimal":
                compiled_targets[-1]["normalization"] = "decimal"
        return {"mode": grading_mode, "targets": compiled_targets}

    choice_ids = {item["id"] for item in controls if "control_type" not in item}
    if response_mode == "single_choice":
        if len(targets) != 1 or _text(targets[0].get("choice_id"), "choice target.choice_id") not in choice_ids:
            raise ContractError("single-choice answer target is not bound to a declared choice")
        return {"mode": grading_mode, "targets": [{"choice_id": targets[0]["choice_id"]}]}
    target_ids = [
        _text(item.get("choice_id"), "choice target.choice_id")
        for item in targets
    ]
    if not target_ids or len(target_ids) != len(set(target_ids)) or not set(target_ids).issubset(choice_ids):
        raise ContractError("multi-choice answer targets are not bound to declared choices")
    return {"mode": grading_mode, "targets": [{"choice_id": value} for value in target_ids]}


def _validate_candidate(candidate: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    if candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise ContractError("unsupported candidate schema version")
    content = _object(candidate.get("content"), "content")
    task = _object(candidate.get("task"), "task")
    task_type = _text(task.get("task_type"), "task.task_type")
    response_mode = _text(task.get("response_mode"), "task.response_mode")
    if task_type not in TASK_TYPES:
        raise ContractError("unsupported task type")
    if response_mode not in RESPONSE_MODES:
        raise ContractError("unsupported response mode")
    prompt, blocks = _prompt_from_blocks(
        content.get("blocks"),
        include_blanks=response_mode == "fill_blank",
    )
    schema, interaction_items = _compile_interaction(candidate, response_mode)
    controls = [item for item in interaction_items if "control_type" in item]
    grading = _compile_grading(candidate, response_mode, interaction_items)
    if response_mode == "fill_blank":
        blank_ids = [block["field_id"] for block in blocks if block["type"] == "blank"]
        control_ids = [item["id"] for item in controls]
        if blank_ids != control_ids:
            raise ContractError("blank field ids do not match controls in order")
    return prompt, response_mode, blocks, interaction_items


def _child_surface(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    try:
        projection = child_prompt.project_child_surface(
            prompt=prompt,
            prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
            interaction_schema=schema,
            allow_legacy=False,
        )
    except child_prompt.ChildPromptContractError as exc:
        raise ContractError("child surface is not renderable: " + "; ".join(exc.errors)) from exc
    return {
        "prompt": projection["prompt"],
        "prompt_format": projection["prompt_format"],
        "prompt_segments": projection["prompt_segments"],
        "interaction_schema": projection["interaction_schema"],
        "interaction_rendering": projection["interaction_rendering"],
        "projection_sha256": projection["projection_sha256"],
    }


def compile_question_artifact(candidate: dict[str, Any], *, identity: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(_object(candidate, "candidate"))
    prompt, response_mode, blocks, interaction_items = _validate_candidate(candidate)
    task = candidate["task"]
    schema, _ = _compile_interaction(candidate, response_mode)
    grading = _compile_grading(candidate, response_mode, interaction_items)
    question_id = _text(identity.get("question_id"), "identity.question_id")
    artifact_version = identity.get("artifact_version", 1)
    if not isinstance(artifact_version, int) or isinstance(artifact_version, bool) or artifact_version < 1:
        raise ContractError("identity.artifact_version must be a positive integer")
    controls = [item for item in interaction_items if "control_type" in item]
    choices = [item for item in interaction_items if "control_type" not in item]
    child_surface = _child_surface(prompt, schema)
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "identity": {
            "question_id": question_id,
            "node_id": _text(identity.get("node_id"), "identity.node_id"),
            "qf_id": _text(identity.get("qf_id"), "identity.qf_id"),
            "slot_id": _text(identity.get("slot_id"), "identity.slot_id"),
            "candidate_version": identity.get("candidate_version", 1),
            "artifact_version": artifact_version,
        },
        "task": {"task_type": task["task_type"], "response_mode": response_mode},
        "content": {"blocks": blocks, "prompt": prompt},
        "display": {
            "controls": controls,
            "choices": choices,
        },
        "child_surface": child_surface,
        "grading": grading,
        "diagnostic": {
            "node_id": identity["node_id"],
            "qf_id": identity["qf_id"],
            "slot_id": identity["slot_id"],
        },
        "lineage": {
            "candidate_schema_version": candidate["schema_version"],
            "candidate": deepcopy(candidate.get("lineage") or {}),
        },
    }
    return artifact


def _normalize_value(value: str, normalization: str) -> str:
    if normalization in {"trim_whitespace", "trim_spaces"}:
        return value.strip()
    if normalization not in DECIMAL_NORMALIZATION_POLICIES:
        return value.strip()
    try:
        decimal = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("submitted value is not a decimal") from exc
    if not decimal.is_finite():
        raise ContractError("submitted decimal must be finite")
    normalized = format(decimal, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"", "-0"}:
        return "0"
    return normalized


def grade_response(artifact: dict[str, Any], response_envelope: dict[str, Any]) -> dict[str, Any]:
    artifact = _object(artifact, "artifact")
    identity = _object(artifact.get("identity"), "artifact.identity")
    mode = artifact.get("task", {}).get("response_mode")
    if mode == "short_answer":
        raise ContractError("semantic grading requires the model assessment route")
    response_envelope = _object(response_envelope, "response")
    if response_envelope.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        raise ContractError("unsupported response schema version")
    if response_envelope.get("question_id") != identity.get("question_id"):
        raise ContractError("response question id does not match artifact")
    if response_envelope.get("artifact_version") != identity.get("artifact_version"):
        raise ContractError("response artifact version does not match artifact")
    grading = _object(artifact.get("grading"), "artifact.grading")
    raw_response = _object(response_envelope.get("response"), "response.response")
    try:
        parsed = fixed_answer_assessment.parse_fixed_answer_response(raw_response)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    if parsed.get("type") != mode:
        raise ContractError("response type does not match artifact")
    field_results: list[dict[str, Any]] = []
    correct = True
    if mode == "fill_blank":
        targets = {item["control_id"]: item for item in grading["targets"]}
        submitted = {item["id"]: item["value"] for item in parsed["fields"]}
        if set(submitted) != set(targets):
            raise ContractError("response fields do not match grading targets")
        for control_id, target in targets.items():
            normalized = _normalize_value(submitted[control_id], target["normalization"])
            accepted = {
                _normalize_value(value, target["normalization"])
                for value in target["accepted_values"]
            }
            is_correct = normalized in accepted
            correct = correct and is_correct
            field_results.append({
                "control_id": control_id,
                "submitted_value": submitted[control_id],
                "normalized_value": normalized,
                "status": "correct" if is_correct else "wrong",
            })
    elif mode == "single_choice":
        selected = parsed["choice_id"]
        expected = grading["targets"][0]["choice_id"]
        correct = selected == expected
        field_results.append({"control_id": selected, "status": "correct" if correct else "wrong"})
    else:
        selected = set(parsed["choice_ids"])
        expected = {item["choice_id"] for item in grading["targets"]}
        correct = selected == expected
        field_results.append({"control_id": "choices", "status": "correct" if correct else "wrong"})
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "question_id": identity["question_id"],
        "artifact_version": identity["artifact_version"],
        "grading": {
            "mode": grading["mode"],
            "status": "correct" if correct else "wrong",
            "score": 1 if correct else 0,
            "field_results": field_results,
        },
        "evidence": deepcopy(artifact.get("diagnostic") or {}),
    }
