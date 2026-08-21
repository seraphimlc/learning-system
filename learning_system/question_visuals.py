from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA_VERSION = "question-visual-manifest.v1"
INVENTORY_SCHEMA_VERSION = "question-visual-inventory.v1"
RENDERER_CONTRACT_VERSION = "question-visual-renderer.v1"
ACTIVE_RECEIPT_KEY = "question_visual_manifest_active.v1"
ACTIVE_RECEIPT_SCHEMA_VERSION = "question-visual-activation.v1"
REQUIRED_INVENTORY_NODE_IDS = {
    "M-G7-NUMBER-LINE",
    "M-G7-GEO-VIEWS",
}
REQUIRED_ITEM_VERSION = "2026-07-12.bank.v12"
_LEGACY_PRODUCTION_INVENTORY_SCENE_TYPES = {
    "number_line",
    "cube_net",
    "orthographic_view",
    "simple_geometry",
}
NUMBER_LINE_REFERENCE_FRAME_DIAGNOSTIC_SCENE_TYPE = (
    "number_line_reference_frame_diagnostic"
)
_REFERENCE_FRAME_PRODUCTION_INVENTORY_SCENE_TYPES = {
    *_LEGACY_PRODUCTION_INVENTORY_SCENE_TYPES,
    NUMBER_LINE_REFERENCE_FRAME_DIAGNOSTIC_SCENE_TYPE,
}
ALLOWED_SCENE_TYPES = set(_REFERENCE_FRAME_PRODUCTION_INVENTORY_SCENE_TYPES)
_PRODUCTION_INVENTORY_SCENE_PROFILES = {
    INVENTORY_SCHEMA_VERSION: {
        frozenset(_LEGACY_PRODUCTION_INVENTORY_SCENE_TYPES),
        frozenset(_REFERENCE_FRAME_PRODUCTION_INVENTORY_SCENE_TYPES),
    }
}
CHILD_VISUAL_KEYS = {"scene_type", "alt_text", "long_description", "scene"}
CHILD_VISUAL_INTERACTION_KEY = "interaction_contract"
_CHILD_VISUAL_KEYSETS = {
    frozenset(CHILD_VISUAL_KEYS),
    frozenset({*CHILD_VISUAL_KEYS, CHILD_VISUAL_INTERACTION_KEY}),
}
PRODUCTION_INVENTORY_RELATIVE_PATH = (
    "data/question_visuals/math_question_visual_inventory_v1.json"
)
_NUMBER_LINE_RENDER_SPAN = 348.0
_NUMBER_LINE_MAX_INTERVALS = 12
_NUMBER_LINE_MAX_POINTS = 8
_NUMBER_LINE_TICK_FONT_SIZE = 20.0
_NUMBER_LINE_POINT_FONT_SIZE = 20.0
_REFERENCE_FRAME_FAULT_IDS = (
    "missing_origin",
    "missing_positive_direction",
    "inconsistent_unit_length",
)

_MANIFEST_KEYS = {
    "schema_version",
    "manifest_version",
    "inventory_relative_path",
    "renderer_contract_version",
    "entries",
}
_ENTRY_KEYS = {
    "question_id",
    "item_version",
    "question_digest_sha256",
    "required",
    *CHILD_VISUAL_KEYS,
}
_ENTRY_KEYSETS = {
    frozenset(_ENTRY_KEYS),
    frozenset({*_ENTRY_KEYS, CHILD_VISUAL_INTERACTION_KEY}),
}
_RECEIPT_KEYS = {
    "receipt_schema_version",
    "manifest_version",
    "manifest_sha256",
    "inventory_version",
    "inventory_sha256",
    "relative_path",
    "inventory_relative_path",
    "renderer_contract_version",
    "required_triple_count",
    "required_triples_sha256",
    "activated_at",
}
_FORBIDDEN_KEYS = {
    "raw_svg",
    "svg",
    "html",
    "script",
    "src",
    "href",
    "url",
    "external_url",
    "data_url",
    "canvas",
}
_FORBIDDEN_TEXT = (
    "<svg",
    "<script",
    "javascript:",
    "http://",
    "https://",
    "data:image",
    "url(",
    "<canvas",
)


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"question visual JSON must be an object: {path}")
    return payload


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"question visual {label} schema is not exact")
    return value


def _plain_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"question visual {label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"question visual {label} must be finite")
    return number


def _plain_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"question visual {label} must be an integer")
    return value


def _safe_text(value: Any, label: str, *, maximum: int = 1200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"question visual {label} must be nonempty bounded text")
    lowered = value.casefold()
    if any(token in lowered for token in _FORBIDDEN_TEXT):
        raise ValueError(f"question visual {label} contains forbidden markup or resource data")
    return value


def _safe_optional_text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"question visual {label} must be bounded text")
    if value:
        _safe_text(value, label, maximum=maximum)
    return value


def _validate_safe_tree(value: Any, label: str = "scene") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                raise ValueError(f"question visual {label} contains forbidden key")
            _validate_safe_tree(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_tree(child, f"{label}[{index}]")
    elif isinstance(value, str):
        if value:
            _safe_text(value, label)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"question visual {label} contains an unsupported value")


def _grid_position(value: float, *, minimum: float, step: float) -> int:
    raw = (value - minimum) / step
    position = round(raw)
    if not math.isclose(raw, position, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("question visual number_line value is not aligned to axis step")
    return int(position)


def _estimated_svg_text_width(value: str, *, font_size: float) -> float:
    width = 0.0
    for character in value:
        category = unicodedata.category(character)
        if category.startswith("P"):
            width += font_size * 0.36
        elif ord(character) < 128 or category.startswith("S"):
            width += font_size * 0.62
        elif unicodedata.east_asian_width(character) in {"W", "F"}:
            width += font_size
        else:
            width += font_size * 0.72
    return width


def _number_token(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def _validate_complete_missing_ticks_contract(
    *,
    contract: Any,
    minimum: float,
    step: float,
    interval_count: int,
    visible_tick_values: list[float],
) -> None:
    contract = _exact_keys(
        contract,
        {
            "operation",
            "response_capture",
            "required_interaction_capabilities",
            "visible_entity_ids_for_visual",
            "required_child_produced_entity_ids",
            "answer_hidden",
        },
        "complete_missing_ticks interaction contract",
    )
    if contract["operation"] != "complete_missing_ticks":
        raise ValueError("question visual number_line operation is unsupported")
    if contract["response_capture"] != "paper_photo":
        raise ValueError("question visual missing ticks must use paper photo capture")
    if contract["required_interaction_capabilities"] != [
        "construction_interaction"
    ]:
        raise ValueError(
            "question visual missing ticks construction capability is invalid"
        )
    if contract["answer_hidden"] is not True:
        raise ValueError("question visual missing ticks answer must be hidden")

    visible_ids = contract["visible_entity_ids_for_visual"]
    required_ids = contract["required_child_produced_entity_ids"]
    if (
        not isinstance(visible_ids, list)
        or not isinstance(required_ids, list)
        or not required_ids
        or any(not isinstance(value, str) or not value for value in visible_ids)
        or any(not isinstance(value, str) or not value for value in required_ids)
        or len(visible_ids) != len(set(visible_ids))
        or len(required_ids) != len(set(required_ids))
    ):
        raise ValueError("question visual missing ticks entity ids are invalid")

    expected_visible_ids = [
        f"tick:{_number_token(value)}" for value in visible_tick_values
    ]
    all_tick_ids = [
        f"tick:{_number_token(minimum + step * index)}"
        for index in range(interval_count + 1)
    ]
    if visible_ids != expected_visible_ids:
        raise ValueError("question visual missing ticks visible entity binding is invalid")
    if set(visible_ids) & set(required_ids):
        raise ValueError("question visual missing ticks visible and required ids overlap")
    if set(visible_ids) | set(required_ids) != set(all_tick_ids):
        raise ValueError("question visual missing ticks do not cover the axis grid")


def _validate_number_line(
    scene: Any,
    interaction_contract: dict[str, Any] | None = None,
) -> None:
    scene = _exact_keys(scene, {"axis", "ticks", "points"}, "number_line scene")
    axis = _exact_keys(
        scene["axis"],
        {"min", "max", "step", "origin", "direction"},
        "number_line axis",
    )
    minimum = _plain_number(axis["min"], "number_line axis min")
    maximum = _plain_number(axis["max"], "number_line axis max")
    step = _plain_number(axis["step"], "number_line axis step")
    origin = _plain_number(axis["origin"], "number_line axis origin")
    span = maximum - minimum
    if (
        minimum >= maximum
        or step <= 0
        or not minimum <= origin <= maximum
        or span > 1_000_000
        or max(abs(minimum), abs(maximum), abs(origin), abs(step)) > 1_000_000
    ):
        raise ValueError("question visual number_line axis bounds are invalid")
    if axis["direction"] not in {"right", "left"}:
        raise ValueError("question visual number_line direction is invalid")
    raw_interval_count = span / step
    interval_count = round(raw_interval_count)
    if (
        not math.isclose(raw_interval_count, interval_count, rel_tol=0.0, abs_tol=1e-9)
        or not 1 <= interval_count <= _NUMBER_LINE_MAX_INTERVALS
    ):
        raise ValueError("question visual number_line interval density is invalid")
    origin_position = _grid_position(origin, minimum=minimum, step=step)
    if not 0 <= origin_position <= interval_count:
        raise ValueError("question visual number_line origin is not on the visible grid")
    ticks = scene["ticks"]
    points = scene["points"]
    sparse_construction = interaction_contract is not None
    if (
        not isinstance(ticks, list)
        or (
            sparse_construction
            and not 2 <= len(ticks) < interval_count + 1
        )
        or (
            not sparse_construction
            and len(ticks) != interval_count + 1
        )
    ):
        raise ValueError("question visual number_line tick budget is invalid")
    if not isinstance(points, list) or len(points) > _NUMBER_LINE_MAX_POINTS:
        raise ValueError("question visual number_line point budget is invalid")
    if sparse_construction and points:
        raise ValueError("question visual missing ticks cannot prefill points")
    tick_values: set[float] = set()
    ordered_tick_values: list[float] = []
    tick_positions: set[int] = set()
    tick_labels: list[tuple[int, str]] = []
    for tick in ticks:
        tick = _exact_keys(tick, {"value", "label"}, "number_line tick")
        value = _plain_number(tick["value"], "number_line tick value")
        label = tick["label"]
        if not isinstance(label, str) or len(label) > 12:
            raise ValueError(
                "question visual number_line tick label must be bounded text"
            )
        if value in tick_values or not minimum <= value <= maximum:
            raise ValueError("question visual number_line ticks are duplicated or out of bounds")
        position = _grid_position(value, minimum=minimum, step=step)
        tick_values.add(value)
        ordered_tick_values.append(value)
        tick_positions.add(position)
        tick_labels.append((position, label))
    if not sparse_construction and tick_positions != set(range(interval_count + 1)):
        raise ValueError("question visual number_line ticks do not represent every axis step")
    if origin_position not in tick_positions:
        raise ValueError("question visual number_line origin tick is missing")
    origin_label = next(
        label for position, label in tick_labels if position == origin_position
    )
    if not origin_label.strip():
        raise ValueError("question visual number_line origin label is missing")
    if sparse_construction:
        if ordered_tick_values != sorted(ordered_tick_values):
            raise ValueError("question visual missing ticks must be ordered by value")
        _validate_complete_missing_ticks_contract(
            contract=interaction_contract,
            minimum=minimum,
            step=step,
            interval_count=interval_count,
            visible_tick_values=ordered_tick_values,
        )
    pixels_per_interval = _NUMBER_LINE_RENDER_SPAN / interval_count
    ordered_tick_labels = sorted(tick_labels)
    for (_, left_label), (_, right_label) in zip(
        ordered_tick_labels,
        ordered_tick_labels[1:],
    ):
        needed = (
            _estimated_svg_text_width(
                left_label,
                font_size=_NUMBER_LINE_TICK_FONT_SIZE,
            )
            + _estimated_svg_text_width(
                right_label,
                font_size=_NUMBER_LINE_TICK_FONT_SIZE,
            )
        ) / 2.0 + 6.0
        if needed > pixels_per_interval:
            raise ValueError("question visual number_line tick labels would collide")
    point_keys: set[str] = set()
    point_positions: set[int] = set()
    point_labels: list[tuple[int, str]] = []
    for point in points:
        point = _exact_keys(point, {"key", "value", "label"}, "number_line point")
        key = _safe_text(point["key"], "number_line point key", maximum=80)
        value = _plain_number(point["value"], "number_line point value")
        label = _safe_text(point["label"], "number_line point label", maximum=8)
        if key in point_keys or not minimum <= value <= maximum:
            raise ValueError("question visual number_line points are duplicated or out of bounds")
        position = _grid_position(value, minimum=minimum, step=step)
        if position in point_positions:
            raise ValueError("question visual number_line points overlap")
        point_keys.add(key)
        point_positions.add(position)
        point_labels.append((position, label))
    ordered_point_labels = sorted(point_labels)
    for (left_position, left_label), (right_position, right_label) in zip(
        ordered_point_labels,
        ordered_point_labels[1:],
    ):
        available = (right_position - left_position) * pixels_per_interval
        needed = (
            _estimated_svg_text_width(
                left_label,
                font_size=_NUMBER_LINE_POINT_FONT_SIZE,
            )
            + _estimated_svg_text_width(
                right_label,
                font_size=_NUMBER_LINE_POINT_FONT_SIZE,
            )
        ) / 2.0 + 18.0
        if needed > available:
            raise ValueError("question visual number_line point labels would collide")


def _validate_number_line_reference_frame_diagnostic(scene: Any) -> None:
    scene = _exact_keys(
        scene,
        {
            "direction_marker_visible",
            "origin_tick_id",
            "origin_label_visible",
            "visible_fault_ids",
            "ticks",
        },
        "number_line_reference_frame_diagnostic scene",
    )
    if not isinstance(scene["direction_marker_visible"], bool):
        raise ValueError(
            "question visual reference frame direction marker visibility must be boolean"
        )
    if not isinstance(scene["origin_label_visible"], bool):
        raise ValueError(
            "question visual reference frame origin label visibility must be boolean"
        )
    origin_tick_id = _safe_text(
        scene["origin_tick_id"],
        "reference frame origin tick id",
        maximum=80,
    )
    ticks = scene["ticks"]
    if not isinstance(ticks, list) or not 3 <= len(ticks) <= 9:
        raise ValueError("question visual reference frame tick budget is invalid")

    tick_ids: set[str] = set()
    ordered_ticks: list[dict[str, Any]] = []
    zero_label_tick_ids: list[str] = []
    for tick in ticks:
        tick = _exact_keys(
            tick,
            {"id", "scale_index", "position", "value_label", "point_label"},
            "number_line_reference_frame_diagnostic tick",
        )
        tick_id = _safe_text(tick["id"], "reference frame tick id", maximum=80)
        scale_index = _plain_int(
            tick["scale_index"],
            "reference frame tick scale index",
        )
        position = _plain_int(tick["position"], "reference frame tick position")
        value_label = _safe_optional_text(
            tick["value_label"],
            "reference frame tick value label",
            maximum=12,
        )
        point_label = _safe_optional_text(
            tick["point_label"],
            "reference frame tick point label",
            maximum=8,
        )
        if tick_id in tick_ids:
            raise ValueError("question visual reference frame tick ids are duplicated")
        if not 0 <= position <= 100:
            raise ValueError("question visual reference frame tick position is out of bounds")
        tick_ids.add(tick_id)
        if value_label == "0":
            zero_label_tick_ids.append(tick_id)
        ordered_ticks.append(
            {
                "id": tick_id,
                "scale_index": scale_index,
                "position": position,
                "value_label": value_label,
                "point_label": point_label,
            }
        )

    ordered_ticks.sort(key=lambda tick: tick["scale_index"])
    first_scale_index = ordered_ticks[0]["scale_index"]
    expected_scale_indices = list(
        range(first_scale_index, first_scale_index + len(ordered_ticks))
    )
    if [tick["scale_index"] for tick in ordered_ticks] != expected_scale_indices:
        raise ValueError(
            "question visual reference frame scale indices must be consecutive"
        )
    positions = [tick["position"] for tick in ordered_ticks]
    if any(left >= right for left, right in zip(positions, positions[1:])):
        raise ValueError(
            "question visual reference frame tick positions must increase with scale"
        )
    origin_tick = next(
        (tick for tick in ordered_ticks if tick["id"] == origin_tick_id),
        None,
    )
    if origin_tick is None:
        raise ValueError("question visual reference frame origin tick reference is invalid")
    if origin_tick["scale_index"] != 0 or origin_tick["value_label"] != "0":
        raise ValueError("question visual reference frame origin tick is invalid")
    if zero_label_tick_ids != [origin_tick_id]:
        raise ValueError("question visual reference frame zero label binding is invalid")

    visible_fault_ids = scene["visible_fault_ids"]
    if (
        not isinstance(visible_fault_ids, list)
        or any(
            not isinstance(fault_id, str)
            or fault_id not in _REFERENCE_FRAME_FAULT_IDS
            for fault_id in visible_fault_ids
        )
        or len(set(visible_fault_ids)) != len(visible_fault_ids)
    ):
        raise ValueError("question visual reference frame visible fault ids are invalid")

    adjacent_spacings = [
        right - left for left, right in zip(positions, positions[1:])
    ]
    actual_fault_ids = []
    if not scene["origin_label_visible"]:
        actual_fault_ids.append("missing_origin")
    if not scene["direction_marker_visible"]:
        actual_fault_ids.append("missing_positive_direction")
    if len(set(adjacent_spacings)) > 1:
        actual_fault_ids.append("inconsistent_unit_length")
    if visible_fault_ids != actual_fault_ids:
        raise ValueError(
            "question visual reference frame visible faults do not match the scene"
        )


def _validate_cube_net(scene: Any) -> None:
    scene = _exact_keys(scene, {"cells"}, "cube_net scene")
    cells = scene["cells"]
    if not isinstance(cells, list) or not 1 <= len(cells) <= 6:
        raise ValueError("question visual cube_net cell budget is invalid")
    keys: set[str] = set()
    coordinates: set[tuple[int, int]] = set()
    for cell in cells:
        cell = _exact_keys(cell, {"key", "x", "y", "label"}, "cube_net cell")
        key = _safe_text(cell["key"], "cube_net cell key", maximum=80)
        coordinate = (
            _plain_int(cell["x"], "cube_net cell x"),
            _plain_int(cell["y"], "cube_net cell y"),
        )
        _safe_text(cell["label"], "cube_net cell label", maximum=80)
        if key in keys or coordinate in coordinates:
            raise ValueError("question visual cube_net cells are duplicated")
        keys.add(key)
        coordinates.add(coordinate)
    xs = [coordinate[0] for coordinate in coordinates]
    ys = [coordinate[1] for coordinate in coordinates]
    if (
        any(abs(value) > 12 for value in [*xs, *ys])
        or max(xs) - min(xs) + 1 > 6
        or max(ys) - min(ys) + 1 > 6
    ):
        raise ValueError("question visual cube_net coordinate span is invalid")


def _validate_orthographic(scene: Any) -> None:
    scene = _exact_keys(scene, {"views"}, "orthographic_view scene")
    views = scene["views"]
    if not isinstance(views, list) or not 1 <= len(views) <= 3:
        raise ValueError("question visual orthographic view budget is invalid")
    keys: set[str] = set()
    for view in views:
        view = _exact_keys(
            view,
            {"key", "label", "width", "height", "filled_cells"},
            "orthographic view",
        )
        key = _safe_text(view["key"], "orthographic view key", maximum=80)
        _safe_text(view["label"], "orthographic view label", maximum=80)
        width = _plain_int(view["width"], "orthographic width")
        height = _plain_int(view["height"], "orthographic height")
        cells = view["filled_cells"]
        if key in keys or not 1 <= width <= 12 or not 1 <= height <= 12:
            raise ValueError("question visual orthographic dimensions are invalid")
        if not isinstance(cells, list) or len(cells) > 144:
            raise ValueError("question visual orthographic filled-cell budget is invalid")
        occupied: set[tuple[int, int]] = set()
        for cell in cells:
            if not isinstance(cell, list) or len(cell) != 2:
                raise ValueError("question visual orthographic filled cell is invalid")
            coordinate = (
                _plain_int(cell[0], "orthographic cell x"),
                _plain_int(cell[1], "orthographic cell y"),
            )
            if (
                coordinate in occupied
                or not 0 <= coordinate[0] < width
                or not 0 <= coordinate[1] < height
            ):
                raise ValueError("question visual orthographic filled cell is duplicated or out of bounds")
            occupied.add(coordinate)
        keys.add(key)


def _validate_simple_geometry(scene: Any) -> None:
    scene = _exact_keys(
        scene,
        {"points", "segments", "markers"},
        "simple_geometry scene",
    )
    points = scene["points"]
    segments = scene["segments"]
    markers = scene["markers"]
    if not isinstance(points, list) or not 1 <= len(points) <= 24:
        raise ValueError("question visual simple_geometry point budget is invalid")
    if not isinstance(segments, list) or len(segments) > 48:
        raise ValueError("question visual simple_geometry segment budget is invalid")
    if not isinstance(markers, list) or len(markers) > 24:
        raise ValueError("question visual simple_geometry marker budget is invalid")
    point_keys: set[str] = set()
    for point in points:
        point = _exact_keys(point, {"key", "x", "y", "label"}, "simple_geometry point")
        key = _safe_text(point["key"], "simple_geometry point key", maximum=80)
        x = _plain_number(point["x"], "simple_geometry point x")
        y = _plain_number(point["y"], "simple_geometry point y")
        _safe_text(point["label"], "simple_geometry point label", maximum=80)
        if key in point_keys or not 0 <= x <= 100 or not 0 <= y <= 95:
            raise ValueError("question visual simple_geometry point key is duplicated")
        point_keys.add(key)
    for segment in segments:
        segment = _exact_keys(segment, {"from", "to"}, "simple_geometry segment")
        if segment["from"] not in point_keys or segment["to"] not in point_keys:
            raise ValueError("question visual simple_geometry segment reference is invalid")
    for marker in markers:
        marker = _exact_keys(marker, {"type", "at", "arms"}, "simple_geometry marker")
        if marker["type"] != "right_angle" or marker["at"] not in point_keys:
            raise ValueError("question visual simple_geometry marker is invalid")
        arms = marker["arms"]
        if (
            not isinstance(arms, list)
            or len(arms) != 2
            or any(arm not in point_keys for arm in arms)
        ):
            raise ValueError("question visual simple_geometry marker reference is invalid")


def _viewbox_proof(entry: dict[str, Any]) -> dict[str, Any]:
    scene_type = entry["scene_type"]
    scene = entry["scene"]
    if scene_type in {
        "number_line",
        NUMBER_LINE_REFERENCE_FRAME_DIAGNOSTIC_SCENE_TYPE,
    }:
        coordinates = [(26.0, 61.0), (374.0, 104.0), (26.0, 48.0), (374.0, 79.0)]
        view_box = (0.0, 0.0, 400.0, 150.0)
    elif scene_type == "cube_net":
        cells = scene["cells"]
        minimum_x = min(cell["x"] for cell in cells)
        maximum_x = max(cell["x"] for cell in cells)
        minimum_y = min(cell["y"] for cell in cells)
        maximum_y = max(cell["y"] for cell in cells)
        columns = maximum_x - minimum_x + 1
        rows = maximum_y - minimum_y + 1
        size = min(82.0, 400.0 / columns, 250.0 / rows)
        offset_x = (520.0 - columns * size) / 2.0
        offset_y = (360.0 - rows * size) / 2.0
        coordinates = []
        for cell in cells:
            x = offset_x + (cell["x"] - minimum_x) * size
            y = offset_y + (cell["y"] - minimum_y) * size
            coordinates.extend([(x, y), (x + size, y + size)])
        view_box = (0.0, 0.0, 520.0, 360.0)
    elif scene_type == "orthographic_view":
        coordinates = []
        panel_width = 220.0
        panel_gap = 20.0
        for index, view in enumerate(scene["views"]):
            origin_x = 10.0 + index * (panel_width + panel_gap)
            cell_size = min(48.0, 180.0 / view["width"], 180.0 / view["height"])
            grid_width = view["width"] * cell_size
            grid_height = view["height"] * cell_size
            grid_x = origin_x + (panel_width - grid_width) / 2.0
            grid_y = 58.0 + (190.0 - grid_height) / 2.0
            coordinates.extend([(grid_x, grid_y), (grid_x + grid_width, grid_y + grid_height)])
        view_box = (0.0, 0.0, 720.0, 300.0)
    else:
        points = {
            point["key"]: (60.0 + float(point["x"]) * 4.8, 35.0 + float(point["y"]) * 4.2)
            for point in scene["points"]
        }
        coordinates = list(points.values())
        for marker in scene["markers"]:
            at = points[marker["at"]]
            first = points[marker["arms"][0]]
            second = points[marker["arms"][1]]

            def unit(target: tuple[float, float]) -> tuple[float, float]:
                dx = target[0] - at[0]
                dy = target[1] - at[1]
                length = max(1.0, math.hypot(dx, dy))
                return dx / length, dy / length

            one = unit(first)
            two = unit(second)
            corner_one = (at[0] + one[0] * 18.0, at[1] + one[1] * 18.0)
            corner_two = (at[0] + two[0] * 18.0, at[1] + two[1] * 18.0)
            outer = (corner_one[0] + two[0] * 18.0, corner_one[1] + two[1] * 18.0)
            coordinates.extend([corner_one, corner_two, outer])
        view_box = (0.0, 0.0, 600.0, 440.0)

    minimum_x, minimum_y, width, height = view_box
    maximum_x = minimum_x + width
    maximum_y = minimum_y + height
    inside = all(
        math.isfinite(x)
        and math.isfinite(y)
        and minimum_x <= x <= maximum_x
        and minimum_y <= y <= maximum_y
        for x, y in coordinates
    )
    if not inside:
        raise ValueError("question visual scene geometry leaves the renderer viewBox")
    return {
        "question_id": entry["question_id"],
        "scene_type": scene_type,
        "view_box": [minimum_x, minimum_y, width, height],
        "geometry_inside": True,
    }


def validate_child_visual(visual: dict[str, Any]) -> dict[str, Any]:
    """Validate an embedded child-safe visual without trusting model markup."""
    if not isinstance(visual, dict) or frozenset(visual) not in _CHILD_VISUAL_KEYSETS:
        raise ValueError("question visual child visual schema is not exact")
    scene_type = visual["scene_type"]
    if scene_type not in ALLOWED_SCENE_TYPES:
        raise ValueError("question visual scene type is not allowed")
    _safe_text(visual["alt_text"], "alt text", maximum=300)
    _safe_text(visual["long_description"], "long description", maximum=1200)
    _validate_safe_tree(visual)
    interaction_contract = visual.get(CHILD_VISUAL_INTERACTION_KEY)
    if interaction_contract is not None and scene_type != "number_line":
        raise ValueError("question visual interaction contract scene is unsupported")
    validators = {
        NUMBER_LINE_REFERENCE_FRAME_DIAGNOSTIC_SCENE_TYPE: (
            _validate_number_line_reference_frame_diagnostic
        ),
        "cube_net": _validate_cube_net,
        "orthographic_view": _validate_orthographic,
        "simple_geometry": _validate_simple_geometry,
    }
    if scene_type == "number_line":
        _validate_number_line(visual["scene"], interaction_contract)
    else:
        validators[scene_type](visual["scene"])
    _viewbox_proof({"question_id": "embedded", **visual})
    return copy.deepcopy(visual)


def embedded_visual_for_question(question: dict[str, Any]) -> dict[str, Any] | None:
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    visual = question.get("question_visual")
    if visual is None:
        visual = raw.get("question_visual")
    if visual is None:
        return None
    if not isinstance(visual, dict):
        raise ValueError("embedded question visual must be an object")
    return validate_child_visual(visual)


def question_visual_sha256(visual: dict[str, Any]) -> str:
    return _canonical_sha256(validate_child_visual(visual))


def validated_embedded_visual_for_question(
    question: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate both the child visual and its immutable production lineage."""
    visual = embedded_visual_for_question(question)
    if visual is None:
        return None
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    design = question.get("child_surface_design")
    if not isinstance(design, dict):
        design = (
            raw.get("child_surface_design")
            if isinstance(raw.get("child_surface_design"), dict)
            else {}
        )
    support = (
        design.get("visual_support")
        if isinstance(design.get("visual_support"), dict)
        else {}
    )
    asset_ref = str(
        question.get("question_visual_asset_ref")
        or raw.get("question_visual_asset_ref")
        or ""
    ).strip()
    lineage = question.get("production_lineage")
    if not isinstance(lineage, dict):
        lineage = (
            raw.get("production_lineage")
            if isinstance(raw.get("production_lineage"), dict)
            else {}
        )
    if support.get("mode") != "external_asset":
        raise ValueError("embedded question visual must use an external asset binding")
    if not asset_ref or str(support.get("asset_ref") or "").strip() != asset_ref:
        raise ValueError("embedded question visual asset ref binding is invalid")
    if str(lineage.get("question_visual_asset_ref") or "").strip() != asset_ref:
        raise ValueError("embedded question visual asset lineage is invalid")
    if str(lineage.get("question_visual_sha256") or "").strip() != _canonical_sha256(visual):
        raise ValueError("embedded question visual digest lineage is invalid")
    return visual


def embedded_visual_required(question: dict[str, Any]) -> bool:
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    design = question.get("child_surface_design")
    if not isinstance(design, dict):
        design = raw.get("child_surface_design") if isinstance(raw.get("child_surface_design"), dict) else {}
    support = design.get("visual_support") if isinstance(design.get("visual_support"), dict) else {}
    return bool(
        support.get("prompt_depends_on_visual") is True
        or support.get("mode") == "external_asset"
        or question.get("question_visual") is not None
        or raw.get("question_visual") is not None
    )


class QuestionVisualManifest:
    def __init__(
        self,
        payload: dict[str, Any],
        inventory: dict[str, Any],
        audit_report: dict[str, Any],
    ) -> None:
        self.payload = copy.deepcopy(payload)
        self.inventory = copy.deepcopy(inventory)
        self.audit_report = dict(audit_report)
        self._entries = {
            (
                entry["question_id"],
                entry["item_version"],
                entry["question_digest_sha256"],
            ): copy.deepcopy(entry)
            for entry in payload["entries"]
        }
        self._requirements = {
            (item["question_id"], group["item_version"]): {
                **copy.deepcopy(item),
                "checkpoint_status": group["checkpoint_status"],
            }
            for group in inventory["groups"]
            if group.get("checkpoint_status") in {"complete", "refresh_pending"}
            for item in group["items"]
        }

    @staticmethod
    def validate_entry(entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict) or frozenset(entry) not in _ENTRY_KEYSETS:
            raise ValueError("question visual entry schema is not exact")
        _safe_text(entry["question_id"], "question id", maximum=160)
        _safe_text(entry["item_version"], "item version", maximum=160)
        digest = str(entry["question_digest_sha256"])
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("question visual question digest must be lowercase sha256")
        if entry["required"] is not True:
            raise ValueError("question visual required binding must be true")
        child_visual = {key: entry[key] for key in CHILD_VISUAL_KEYS}
        if CHILD_VISUAL_INTERACTION_KEY in entry:
            child_visual[CHILD_VISUAL_INTERACTION_KEY] = entry[
                CHILD_VISUAL_INTERACTION_KEY
            ]
        validate_child_visual(child_visual)
        _viewbox_proof(entry)
        return copy.deepcopy(entry)

    @classmethod
    def load_validated(
        cls,
        path: Path | str,
        *,
        inventory_path: Path | str | None = None,
    ) -> "QuestionVisualManifest":
        project_root = Path(__file__).resolve().parents[1]
        manifest_path = Path(path).resolve()
        payload = _load_json(manifest_path)
        _exact_keys(payload, _MANIFEST_KEYS, "manifest")
        if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
            raise ValueError("question visual manifest schema version is invalid")
        _safe_text(payload["manifest_version"], "manifest version", maximum=160)
        if payload["renderer_contract_version"] != RENDERER_CONTRACT_VERSION:
            raise ValueError("question visual renderer contract version is invalid")
        inventory_file = (
            Path(inventory_path).resolve()
            if inventory_path is not None
            else cls._safe_project_path(project_root, payload["inventory_relative_path"])
        )
        inventory = _load_json(inventory_file)
        cls._validate_inventory(inventory)

        invalid_entries: list[dict[str, Any]] = []
        valid_entries: list[dict[str, Any]] = []
        viewbox_proofs: list[dict[str, Any]] = []
        for index, entry in enumerate(payload["entries"] if isinstance(payload["entries"], list) else []):
            try:
                valid_entry = cls.validate_entry(entry)
                valid_entries.append(valid_entry)
                viewbox_proofs.append(_viewbox_proof(valid_entry))
            except ValueError as exc:
                invalid_entries.append({"index": index, "error": str(exc)})
        if not isinstance(payload["entries"], list):
            invalid_entries.append({"index": -1, "error": "entries must be a list"})

        expected: dict[tuple[str, str, str], dict[str, Any]] = {}
        pending_slots = 0
        pending_nodes: list[str] = []
        for group in inventory["groups"]:
            if group["checkpoint_status"] == "complete":
                for item in group["items"]:
                    triple = (
                        item["question_id"],
                        group["item_version"],
                        item["question_digest_sha256"],
                    )
                    expected[triple] = item
            else:
                pending_slots += len(group["items"])
                pending_nodes.append(group["node_id"])

        required_triples = [
            {
                "question_id": triple[0],
                "item_version": triple[1],
                "question_digest_sha256": triple[2],
                "scene_type": item["scene_type"],
            }
            for triple, item in sorted(expected.items())
        ]

        seen: set[tuple[str, str, str]] = set()
        duplicate_bindings: list[dict[str, str]] = []
        extra_entries: list[dict[str, str]] = []
        for entry in valid_entries:
            triple = (
                entry["question_id"],
                entry["item_version"],
                entry["question_digest_sha256"],
            )
            if triple in seen:
                duplicate_bindings.append({"question_id": entry["question_id"]})
            seen.add(triple)
            inventory_item = expected.get(triple)
            if inventory_item is None:
                extra_entries.append({"question_id": entry["question_id"]})
            elif inventory_item["scene_type"] != entry["scene_type"]:
                invalid_entries.append({
                    "question_id": entry["question_id"],
                    "error": "scene type differs from inventory",
                })
        missing_required_entries = [
            {"question_id": triple[0]}
            for triple, item in expected.items()
            if item.get("required") is True and triple not in seen
        ]
        report = {
            "manifest_sha256": _canonical_sha256(payload),
            "inventory_sha256": _canonical_sha256(inventory),
            "manifest_entry_count": len(valid_entries),
            "bound_inventory_slots": len(expected),
            "pending_inventory_slots": pending_slots,
            "pending_inventory_node": pending_nodes[0] if len(pending_nodes) == 1 else "",
            "pending_inventory_nodes": sorted(pending_nodes),
            "required_triple_count": len(required_triples),
            "required_triples_sha256": _canonical_sha256(required_triples),
            "invalid_entries": invalid_entries,
            "missing_required_entries": missing_required_entries,
            "extra_entries": extra_entries,
            "duplicate_bindings": duplicate_bindings,
            "viewbox_proof_count": len(viewbox_proofs),
            "viewbox_all_inside": len(viewbox_proofs) == len(valid_entries),
        }
        if any((invalid_entries, missing_required_entries, extra_entries, duplicate_bindings)):
            raise ValueError("question visual manifest does not exactly cover required inventory")
        return cls(payload, inventory, report)

    @classmethod
    def load_active(
        cls,
        conn: sqlite3.Connection,
        *,
        project_root: Path | str | None = None,
    ) -> "QuestionVisualManifest":
        root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
        row = conn.execute(
            "select value from system_meta where key = ?",
            (ACTIVE_RECEIPT_KEY,),
        ).fetchone()
        if not row:
            raise ValueError("question visual active manifest receipt is missing")
        receipt = json.loads(row["value"])
        _exact_keys(receipt, _RECEIPT_KEYS, "active receipt")
        if receipt["receipt_schema_version"] != ACTIVE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("question visual active receipt schema is invalid")
        manifest_path = cls._safe_project_path(root, receipt["relative_path"])
        inventory_path = cls._safe_project_path(root, receipt["inventory_relative_path"])
        payload = _load_json(manifest_path)
        inventory = _load_json(inventory_path)
        if _canonical_sha256(payload) != receipt["manifest_sha256"]:
            raise ValueError("question visual manifest receipt digest is stale")
        if _canonical_sha256(inventory) != receipt["inventory_sha256"]:
            raise ValueError("question visual inventory receipt digest is stale")
        if (
            payload.get("manifest_version") != receipt["manifest_version"]
            or inventory.get("inventory_version") != receipt["inventory_version"]
            or payload.get("renderer_contract_version") != receipt["renderer_contract_version"]
            or payload.get("inventory_relative_path") != receipt["inventory_relative_path"]
        ):
            raise ValueError("question visual active receipt lineage is invalid")
        manifest = cls.load_validated(manifest_path, inventory_path=inventory_path)
        if (
            manifest.audit_report["required_triple_count"] != receipt["required_triple_count"]
            or manifest.audit_report["required_triples_sha256"] != receipt["required_triples_sha256"]
        ):
            raise ValueError("question visual active receipt required triples are stale")
        manifest.audit_report["receipt_activated_at"] = receipt["activated_at"]
        return manifest

    @staticmethod
    def _safe_project_path(project_root: Path, relative_path: Any) -> Path:
        raw = str(relative_path or "")
        relative = Path(raw)
        root = project_root.resolve()
        candidate = (root / relative).resolve()
        if (
            not raw
            or relative.is_absolute()
            or ".." in relative.parts
            or not candidate.is_relative_to(root)
            or not candidate.is_file()
            or candidate.is_symlink()
        ):
            raise ValueError("question visual receipt path is unsafe or missing")
        return candidate

    @staticmethod
    def _validate_inventory(inventory: dict[str, Any]) -> None:
        _exact_keys(
            inventory,
            {"schema_version", "inventory_version", "allowed_scene_types", "groups"},
            "inventory",
        )
        if inventory["schema_version"] != INVENTORY_SCHEMA_VERSION:
            raise ValueError("question visual inventory schema version is invalid")
        declared_scene_types = inventory["allowed_scene_types"]
        declared_scene_type_set = (
            set(declared_scene_types)
            if isinstance(declared_scene_types, list)
            else set()
        )
        allowed_profiles = _PRODUCTION_INVENTORY_SCENE_PROFILES.get(
            inventory["schema_version"],
            set(),
        )
        if (
            not isinstance(declared_scene_types, list)
            or len(declared_scene_type_set) != len(declared_scene_types)
            or frozenset(declared_scene_type_set) not in allowed_profiles
        ):
            raise ValueError("question visual inventory scene allowlist is invalid")
        groups = inventory["groups"]
        if (
            not isinstance(groups, list)
            or len(groups) != len(REQUIRED_INVENTORY_NODE_IDS)
            or {str(group.get("node_id") or "") for group in groups if isinstance(group, dict)}
            != REQUIRED_INVENTORY_NODE_IDS
        ):
            raise ValueError("question visual inventory groups must exactly cover required nodes")
        global_question_ids: set[str] = set()
        global_triples: set[tuple[str, str, str]] = set()
        for group in groups:
            status = group.get("checkpoint_status") if isinstance(group, dict) else None
            _exact_keys(
                group,
                {"node_id", "checkpoint_status", "item_version", "items"},
                "inventory group",
            )
            if status not in {"complete", "refresh_pending"}:
                raise ValueError("question visual inventory checkpoint status is invalid")
            item_version = _safe_text(group["item_version"], "inventory item version", maximum=160)
            if not isinstance(group["items"], list) or len(group["items"]) != 20:
                raise ValueError("question visual inventory group must contain exactly 20 items")
            slots: set[int] = set()
            for item in group["items"]:
                item_keys = (
                    {"slot", "question_id", "question_digest_sha256", "required", "scene_type"}
                    if status == "complete"
                    else {"slot", "question_id", "binding_status", "required", "scene_type"}
                )
                _exact_keys(item, item_keys, "inventory item")
                slot = _plain_int(item["slot"], "inventory slot")
                question_id = _safe_text(item["question_id"], "inventory question id", maximum=160)
                if (
                    slot in slots
                    or not 1 <= slot <= 20
                    or item["required"] is not True
                    or item["scene_type"] not in declared_scene_type_set
                    or question_id in global_question_ids
                ):
                    raise ValueError("question visual inventory item is invalid")
                slots.add(slot)
                global_question_ids.add(question_id)
                if status == "refresh_pending":
                    if item["binding_status"] != "refresh_pending":
                        raise ValueError("question visual refresh-pending item is invalid")
                    continue
                digest = str(item["question_digest_sha256"] or "")
                if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                    raise ValueError("question visual inventory digest is invalid")
                triple = (question_id, item_version, digest)
                if triple in global_triples:
                    raise ValueError("question visual inventory triple is duplicated")
                global_triples.add(triple)
            if slots != set(range(1, 21)):
                raise ValueError("question visual inventory slots must exactly cover 1 through 20")

    def lookup(
        self,
        question_id: str,
        item_version: str,
        question_digest_sha256: str,
    ) -> dict[str, Any] | None:
        entry = self._entries.get((question_id, item_version, question_digest_sha256))
        return copy.deepcopy(entry) if entry else None

    def requirement_for_question(self, question: dict[str, Any]) -> dict[str, Any] | None:
        question_id = str(question.get("id") or "")
        item_version = str(
            question.get("item_version")
            or question.get("question_bank_version")
            or ""
        )
        requirement = self._requirements.get((question_id, item_version))
        return copy.deepcopy(requirement) if requirement else None

    def child_visual_for_question(self, question: dict[str, Any]) -> dict[str, Any] | None:
        question_id = str(question.get("id") or "")
        item_version = str(
            question.get("item_version")
            or question.get("question_bank_version")
            or ""
        )
        requirement = self._requirements.get((question_id, item_version))
        if requirement is None:
            return None
        if requirement["checkpoint_status"] != "complete":
            raise ValueError("question visual required binding is awaiting a sealed checkpoint")
        source = question.get("source") if isinstance(question.get("source"), dict) else {}
        raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
        digest = str(
            question.get("question_digest_sha256")
            or source.get("question_digest_sha256")
            or raw.get("question_digest_sha256")
            or ""
        )
        if digest != requirement["question_digest_sha256"]:
            raise ValueError("question visual question digest does not match required inventory")
        entry = self.lookup(question_id, item_version, digest)
        if entry is None:
            raise ValueError("question visual required manifest binding is missing")
        child_visual = {key: copy.deepcopy(entry[key]) for key in CHILD_VISUAL_KEYS}
        if CHILD_VISUAL_INTERACTION_KEY in entry:
            child_visual[CHILD_VISUAL_INTERACTION_KEY] = copy.deepcopy(
                entry[CHILD_VISUAL_INTERACTION_KEY]
            )
        return child_visual


def required_binding_for_question(
    question: dict[str, Any],
    *,
    manifest: QuestionVisualManifest,
) -> dict[str, Any] | None:
    if not isinstance(manifest, QuestionVisualManifest):
        raise TypeError("receipt-bound question visual manifest is required")
    return manifest.requirement_for_question(question)


def visual_required_by_policy(question: dict[str, Any]) -> bool:
    item_version = str(
        question.get("item_version")
        or question.get("question_bank_version")
        or ""
    )
    return embedded_visual_required(question) or (
        item_version == REQUIRED_ITEM_VERSION
        and str(question.get("node_id") or "") in REQUIRED_INVENTORY_NODE_IDS
    )
