from __future__ import annotations

import hashlib
import json
import re
from typing import Any


CHILD_PROMPT_FORMAT = "2026-07-17.child-plain-text.v1"
QUESTION_INTERACTION_SCHEMA_V1 = "2026-07-13.question-interaction.v1"
QUESTION_INTERACTION_SCHEMA_V2 = "2026-07-17.question-interaction.v2"
CHILD_SURFACE_PROJECTION_VERSION = "2026-07-17.child-surface-projection.v1"

INTERACTION_TYPES = frozenset({
    "short_text",
    "fill_blank",
    "single_choice",
    "multi_choice",
    "formula_input",
})

FORBIDDEN_SCHEMA_KEYS = frozenset({
    "answer",
    "answers",
    "expected",
    "expected_answer",
    "correct",
    "correct_answer",
    "is_correct",
    "rubric",
    "score",
    "points",
    "solution",
    "solution_steps",
    "provider",
    "model",
    "agent",
    "node_id",
    "question_id",
    "attempt_id",
})

_SAFE_UNAVAILABLE_MESSAGE = "当前步骤还没有准备好，请稍后再试。"
_UNICODE_SUPERSCRIPT_DIGITS = str.maketrans({
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
})
_UNICODE_SUPERSCRIPT_DIGIT_CHARS = frozenset(chr(value) for value in _UNICODE_SUPERSCRIPT_DIGITS)
_LEGACY_LETTER_SUPERSCRIPTS = {
    "ᵃ": "a",
    "ᵏ": "k",
}
_FORBIDDEN_SUPERSCRIPTS = frozenset(
    "⁰¹²³⁴⁵⁶⁷⁸⁹"
    "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸ"
)
_INTERNAL_RESIDUE = (
    "trusted_context",
    "untrusted_payload",
    "slot_role",
    "evidence_goal",
    "expected_answer",
    "solution_steps",
    "review_artifact",
    "designer_artifact",
    "semantic_evidence",
    "agent_key",
    "prompt_version_id",
    "response_schema_version",
    "{{",
    "}}",
    "<trusted",
    "<untrusted",
)
_EXPONENT_TOKEN = re.compile(
    r"(?P<base>\([^()\n]+\)|[A-Za-z0-9])\^(?P<exponent>[A-Za-z]|[0-9]+)"
)
_ANY_CARET = re.compile(r"\^")
_MARKDOWN_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MARKDOWN_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]+\]\([^\)\n]+\)")
_LITERAL_ESCAPE = re.compile(r"\\(?:n|r|t|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2})")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_HTML_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")
_EXPLANATION_INSTRUCTION = re.compile(r"说明|解释|理由|依据|为什么|论证|证明|反驳|检查")


class ChildPromptContractError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = sorted(set(errors))
        super().__init__("; ".join(self.errors) or _SAFE_UNAVAILABLE_MESSAGE)


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _single_line(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _walk_forbidden_schema_values(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_SCHEMA_KEYS:
                errors.append(f"interaction_schema.forbidden_key:{path}.{key_text}")
            _walk_forbidden_schema_values(child, f"{path}.{key_text}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_schema_values(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        if normalized in FORBIDDEN_SCHEMA_KEYS:
            errors.append(f"interaction_schema.forbidden_value:{path}")


def normalize_interaction_schema(
    schema: Any,
    *,
    allow_legacy: bool,
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise ChildPromptContractError(["interaction_schema:not_object"])
    errors: list[str] = []
    _walk_forbidden_schema_values(schema, "$", errors)
    schema_version = str(schema.get("schema_version") or "")
    is_legacy = schema_version in {"", QUESTION_INTERACTION_SCHEMA_V1}
    if schema_version != QUESTION_INTERACTION_SCHEMA_V2 and not (allow_legacy and is_legacy):
        errors.append("interaction_schema:schema_version_unsupported")
    interaction_type = str(schema.get("type") or "")
    if interaction_type not in INTERACTION_TYPES:
        errors.append("interaction_schema:type_invalid")
    requires_explanation = bool(
        schema.get("requires_explanation", schema.get("explanation_required", False))
    )
    allow_explanation = bool(schema.get("allow_explanation", True))

    fields: list[dict[str, str]] = []
    raw_fields = schema.get("fields") or []
    if not isinstance(raw_fields, list):
        errors.append("interaction_schema.fields:not_array")
        raw_fields = []
    if len(raw_fields) > 8:
        errors.append("interaction_schema.fields:too_many")
    for index, field in enumerate(raw_fields):
        if not isinstance(field, dict):
            errors.append(f"interaction_schema.fields[{index}]:not_object")
            continue
        field_id = re.sub(r"[^A-Za-z0-9_-]", "", str(field.get("id") or ""))[:40]
        label = _single_line(field.get("label"), limit=80)
        if not field_id or not label:
            errors.append(f"interaction_schema.fields[{index}]:id_and_label_required")
            continue
        fields.append({
            "id": field_id,
            "label": label,
            "placeholder": _single_line(field.get("placeholder"), limit=100),
            "prefix": _single_line(field.get("prefix"), limit=40),
            "suffix": _single_line(field.get("suffix"), limit=40),
        })

    choices: list[dict[str, str]] = []
    raw_choices = schema.get("choices") or []
    if not isinstance(raw_choices, list):
        errors.append("interaction_schema.choices:not_array")
        raw_choices = []
    if len(raw_choices) > 8:
        errors.append("interaction_schema.choices:too_many")
    for index, choice in enumerate(raw_choices):
        if not isinstance(choice, dict):
            errors.append(f"interaction_schema.choices[{index}]:not_object")
            continue
        choice_id = re.sub(r"[^A-Za-z0-9_-]", "", str(choice.get("id") or ""))[:40]
        label = _single_line(choice.get("label"), limit=180)
        if not choice_id or not label:
            errors.append(f"interaction_schema.choices[{index}]:id_and_label_required")
            continue
        choices.append({"id": choice_id, "label": label})

    title = _single_line(schema.get("title"), limit=120)
    explanation_label = _single_line(schema.get("explanation_label"), limit=60)
    formula_label = _single_line(schema.get("formula_label"), limit=80)
    placeholder = _single_line(
        schema.get("placeholder", schema.get("answer_placeholder", "")),
        limit=120,
    )
    if requires_explanation and not allow_explanation:
        errors.append("interaction_schema.requires_explanation:allow_explanation_required")
    if requires_explanation and not explanation_label:
        errors.append("interaction_schema.requires_explanation:label_required")
    if interaction_type == "fill_blank" and len(fields) < 2:
        errors.append("interaction_schema.fill_blank:at_least_two_fields_required")
    if interaction_type in {"single_choice", "multi_choice"} and len(choices) < 2:
        errors.append("interaction_schema.choice:at_least_two_choices_required")
    if interaction_type == "formula_input" and not formula_label:
        errors.append("interaction_schema.formula_input:formula_label_required")
    if interaction_type == "short_text" and (fields or choices):
        errors.append("interaction_schema.short_text:fields_or_choices_not_allowed")
    if interaction_type != "fill_blank" and fields:
        errors.append("interaction_schema:fields_not_owned_by_type")
    if interaction_type not in {"single_choice", "multi_choice"} and choices:
        errors.append("interaction_schema:choices_not_owned_by_type")
    field_ids = [field["id"] for field in fields]
    choice_ids = [choice["id"] for choice in choices]
    if len(field_ids) != len(set(field_ids)):
        errors.append("interaction_schema.fields:duplicate_id")
    if len(choice_ids) != len(set(choice_ids)):
        errors.append("interaction_schema.choices:duplicate_id")
    if errors:
        raise ChildPromptContractError(errors)
    return {
        "schema_version": QUESTION_INTERACTION_SCHEMA_V2,
        "type": interaction_type,
        "title": title,
        "allow_explanation": allow_explanation,
        "requires_explanation": requires_explanation,
        "explanation_label": explanation_label,
        "fields": fields[:8],
        "choices": choices[:8],
        "formula_label": formula_label,
        "placeholder": placeholder,
    }


def _legacy_superscript_to_caret(prompt: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(prompt):
        character = prompt[index]
        if character in _UNICODE_SUPERSCRIPT_DIGIT_CHARS:
            if not output or not (output[-1][-1:].isalnum() or output[-1].endswith(")")):
                raise ChildPromptContractError(["prompt:ambiguous_legacy_superscript"])
            digits: list[str] = []
            while index < len(prompt) and prompt[index] in _UNICODE_SUPERSCRIPT_DIGIT_CHARS:
                digits.append(prompt[index].translate(_UNICODE_SUPERSCRIPT_DIGITS))
                index += 1
            output.append("^" + "".join(digits))
            continue
        if character in _LEGACY_LETTER_SUPERSCRIPTS:
            if not output or not (output[-1][-1:].isalnum() or output[-1].endswith(")")):
                raise ChildPromptContractError(["prompt:ambiguous_legacy_superscript"])
            output.append("^" + _LEGACY_LETTER_SUPERSCRIPTS[character])
            index += 1
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _repair_legacy_choice_surface(prompt: str, schema: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if schema.get("type") not in {"single_choice", "multi_choice"}:
        return prompt, schema
    lines = prompt.splitlines()
    projected = json.loads(json.dumps(schema, ensure_ascii=False))
    for choice in projected.get("choices") or []:
        choice_id = str(choice.get("id") or "").strip()
        label = str(choice.get("label") or "").strip()
        if not choice_id or label not in {choice_id, f"{choice_id}.", f"{choice_id}．"}:
            continue
        prefixes = (
            f"{choice_id}.",
            f"{choice_id}．",
            f"{choice_id}、",
            f"{choice_id})",
            f"{choice_id}）",
            f"{choice_id}:",
            f"{choice_id}：",
        )
        for line in lines:
            stripped = line.strip()
            prefix = next((value for value in prefixes if stripped.startswith(value)), "")
            if prefix and stripped[len(prefix):].strip():
                choice["label"] = stripped[len(prefix):].strip()
                break
    labels = [str(choice.get("label") or "").strip() for choice in projected.get("choices") or []]
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        duplicate = False
        for label in labels:
            if not label:
                continue
            if stripped == label:
                duplicate = True
                break
            if stripped.endswith(label):
                prefix = stripped[: -len(label)].strip().rstrip(".．、:：)）")
                if prefix and len(prefix) <= 3 and prefix.isalnum():
                    duplicate = True
                    break
        if not duplicate:
            kept.append(line)
    return "\n".join(kept), projected


def normalize_prompt_text(prompt: Any, *, allow_legacy: bool, limit: int = 2000) -> str:
    text = str(prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    if allow_legacy:
        text = _legacy_superscript_to_caret(text)
    lines = [line.rstrip(" \t") for line in text.strip().split("\n")]
    normalized_lines: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if normalized_lines and not blank:
                normalized_lines.append("")
            blank = True
            continue
        normalized_lines.append(line)
        blank = False
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    normalized = "\n".join(normalized_lines)
    errors: list[str] = []
    if not normalized:
        errors.append("prompt:empty")
    if len(normalized) > limit:
        errors.append("prompt:over_limit")
    for line in normalized.splitlines():
        if "\t" in line:
            errors.append("prompt:tab_forbidden")
        if "   " in line:
            errors.append("prompt:repeated_space_alignment_forbidden")
        if _MARKDOWN_TABLE_DELIMITER.match(line) or _MARKDOWN_PIPE_ROW.match(line):
            errors.append("prompt:markdown_table_forbidden")
        if _MARKDOWN_HEADING.match(line):
            errors.append("prompt:markdown_heading_forbidden")
    if "```" in normalized or "`" in normalized:
        errors.append("prompt:markdown_code_forbidden")
    if "**" in normalized or "__" in normalized or _MARKDOWN_LINK.search(normalized):
        errors.append("prompt:markdown_authoring_forbidden")
    if _HTML_TAG.search(normalized) or _HTML_ENTITY.search(normalized):
        errors.append("prompt:html_forbidden")
    if "$" in normalized or "\\" in normalized:
        errors.append("prompt:latex_or_backslash_residue_forbidden")
    if _LITERAL_ESCAPE.search(normalized):
        errors.append("prompt:literal_escape_residue_forbidden")
    if any(character in _FORBIDDEN_SUPERSCRIPTS for character in normalized):
        errors.append("prompt:unicode_superscript_forbidden")
    lowered = normalized.lower()
    if any(marker in lowered for marker in _INTERNAL_RESIDUE):
        errors.append("prompt:template_or_internal_metadata_residue")
    if errors:
        raise ChildPromptContractError(errors)
    return normalized


def _duplicate_choice_errors(prompt: str, schema: dict[str, Any]) -> list[str]:
    if schema.get("type") not in {"single_choice", "multi_choice"}:
        return []
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    errors: list[str] = []
    for choice in schema.get("choices") or []:
        label = str(choice.get("label") or "").strip()
        choice_id = str(choice.get("id") or "").strip()
        if not label:
            continue
        for line in lines:
            if line == label:
                errors.append(f"prompt:duplicated_choice_label:{choice_id}")
                break
            if line.endswith(label):
                prefix = line[: -len(label)].strip().rstrip(".．、:：)）")
                if prefix and len(prefix) <= 3 and prefix.isalnum():
                    errors.append(f"prompt:duplicated_choice_label:{choice_id}")
                    break
    return errors


def _prompt_schema_alignment_errors(prompt: str, schema: dict[str, Any]) -> list[str]:
    interaction_type = str(schema.get("type") or "")
    errors: list[str] = []
    if "请选择所有" in prompt and interaction_type != "multi_choice":
        errors.append("prompt_interaction:select_all_requires_multi_choice")
    if "请选择一个" in prompt and interaction_type != "single_choice":
        errors.append("prompt_interaction:select_one_requires_single_choice")
    explanation_requested = bool(_EXPLANATION_INSTRUCTION.search(prompt))
    if explanation_requested and schema.get("allow_explanation") is False:
        errors.append("prompt_interaction:explanation_control_missing")
    return errors


def prompt_segments(prompt: str) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    cursor = 0
    for match in _EXPONENT_TOKEN.finditer(prompt):
        if match.start() > cursor:
            segments.append({"type": "text", "text": prompt[cursor:match.start()]})
        source = match.group(0)
        base = match.group("base")
        exponent = match.group("exponent")
        segments.append({
            "type": "exponent",
            "source": source,
            "base": base,
            "exponent": exponent,
            "accessible_label": f"{base} 的 {exponent} 次方",
        })
        cursor = match.end()
    if cursor < len(prompt):
        segments.append({"type": "text", "text": prompt[cursor:]})
    consumed = "".join(
        segment.get("source", "") if segment.get("type") == "exponent" else segment.get("text", "")
        for segment in segments
    )
    unmatched_carets = _ANY_CARET.sub("", prompt)
    consumed_without_carets = _ANY_CARET.sub("", consumed)
    if consumed != prompt or unmatched_carets != consumed_without_carets:
        raise ChildPromptContractError(["prompt:invalid_exponent_token"])
    for segment in segments:
        if segment.get("type") == "text" and "^" in segment.get("text", ""):
            raise ChildPromptContractError(["prompt:invalid_exponent_token"])
    return segments


def _inline_projection(value: Any, *, legacy: bool, limit: int) -> dict[str, Any]:
    text = normalize_prompt_text(value, allow_legacy=legacy, limit=limit)
    if "\n" in text:
        raise ChildPromptContractError(["interaction_schema:inline_text_must_be_single_line"])
    return {"text": text, "segments": prompt_segments(text)}


def _interaction_rendering(schema: dict[str, Any], *, legacy: bool) -> dict[str, Any]:
    rendering = {
        "title": _inline_projection(schema.get("title") or "作答", legacy=legacy, limit=120),
        "explanation_label": _inline_projection(
            schema.get("explanation_label") or "补充说明",
            legacy=legacy,
            limit=60,
        ),
        "formula_label": None,
        "fields": [],
        "choices": [],
    }
    if schema.get("formula_label"):
        rendering["formula_label"] = _inline_projection(
            schema.get("formula_label"), legacy=legacy, limit=80
        )
    for field in schema.get("fields") or []:
        rendering["fields"].append({
            "id": field["id"],
            "label": _inline_projection(field["label"], legacy=legacy, limit=80),
            "prefix": (
                _inline_projection(field["prefix"], legacy=legacy, limit=40)
                if field.get("prefix") else None
            ),
            "suffix": (
                _inline_projection(field["suffix"], legacy=legacy, limit=40)
                if field.get("suffix") else None
            ),
        })
    for choice in schema.get("choices") or []:
        rendering["choices"].append({
            "id": choice["id"],
            "label": _inline_projection(choice["label"], legacy=legacy, limit=180),
        })
    return rendering


def project_child_surface(
    *,
    prompt: Any,
    interaction_schema: Any,
    prompt_format: Any = "",
    allow_legacy: bool = True,
    prompt_interaction_verdict: str = "aligned",
    limit: int = 2000,
) -> dict[str, Any]:
    source_format = str(prompt_format or "")
    legacy = not source_format
    if source_format and source_format != CHILD_PROMPT_FORMAT:
        raise ChildPromptContractError(["prompt_format:unsupported"])
    if legacy and not allow_legacy:
        raise ChildPromptContractError(["prompt_format:required"])
    if prompt_interaction_verdict != "aligned":
        raise ChildPromptContractError(["prompt_interaction:mismatch"])

    raw_schema = interaction_schema
    if legacy and raw_schema is None:
        raw_schema = {
            "schema_version": QUESTION_INTERACTION_SCHEMA_V1,
            "type": "short_text",
            "title": "我的答案",
            "allow_explanation": True,
            "explanation_label": "我的答案",
            "fields": [],
            "choices": [],
            "formula_label": "",
            "placeholder": "",
        }
    raw_prompt = str(prompt or "")
    source_schema_sha256 = _digest_json(raw_schema)
    source_prompt_sha256 = hashlib.sha256(raw_prompt.encode("utf-8")).hexdigest()
    if legacy:
        legacy_schema = normalize_interaction_schema(raw_schema, allow_legacy=True)
        if (
            isinstance(raw_schema, dict)
            and "requires_explanation" not in raw_schema
            and "explanation_required" not in raw_schema
        ):
            legacy_schema["requires_explanation"] = bool(
                _EXPLANATION_INSTRUCTION.search(raw_prompt)
            )
        raw_prompt, repaired_schema = _repair_legacy_choice_surface(raw_prompt, legacy_schema)
        normalized_schema = normalize_interaction_schema(repaired_schema, allow_legacy=True)
    else:
        normalized_schema = normalize_interaction_schema(raw_schema, allow_legacy=False)
    normalized_prompt = normalize_prompt_text(raw_prompt, allow_legacy=legacy, limit=limit)
    duplicate_errors = _duplicate_choice_errors(normalized_prompt, normalized_schema)
    alignment_errors = _prompt_schema_alignment_errors(normalized_prompt, normalized_schema)
    if duplicate_errors or alignment_errors:
        raise ChildPromptContractError([*duplicate_errors, *alignment_errors])
    segments = prompt_segments(normalized_prompt)
    interaction_rendering = _interaction_rendering(normalized_schema, legacy=legacy)
    source_changed = normalized_prompt != str(prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    projection = {
        "projection_version": CHILD_SURFACE_PROJECTION_VERSION,
        "prompt_format": CHILD_PROMPT_FORMAT,
        "prompt": normalized_prompt,
        "prompt_segments": segments,
        "interaction_schema": normalized_schema,
        "interaction_rendering": interaction_rendering,
        "source_prompt_sha256": source_prompt_sha256,
        "source_interaction_schema_sha256": source_schema_sha256,
    }
    return {
        **projection,
        "projection_sha256": _digest_json(projection),
        "legacy_compatibility_applied": legacy,
        "source_changed": source_changed,
    }


def project_prompt_only(prompt: Any, *, allow_legacy: bool = True, limit: int = 2000) -> dict[str, Any]:
    source = str(prompt or "")
    normalized = normalize_prompt_text(source, allow_legacy=allow_legacy, limit=limit)
    projection = {
        "projection_version": CHILD_SURFACE_PROJECTION_VERSION,
        "prompt_format": CHILD_PROMPT_FORMAT,
        "prompt": normalized,
        "prompt_segments": prompt_segments(normalized),
        "source_prompt_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    return {**projection, "projection_sha256": _digest_json(projection)}


def projection_errors(**kwargs: Any) -> list[str]:
    try:
        project_child_surface(**kwargs)
    except ChildPromptContractError as exc:
        return list(exc.errors)
    return []
