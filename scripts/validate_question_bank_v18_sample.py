#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import argparse
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import validate_question_bank_v18_blueprints  # noqa: E402

SAMPLE_PATH = ROOT / "data/question_banks/v18/math_v18_sample_60.json"
BLUEPRINT_PATH = ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"


class ValidationError(AssertionError):
    pass


def _assert(condition: Any, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(sample_path: Path = SAMPLE_PATH, blueprint_path: Path = BLUEPRINT_PATH) -> dict[str, Any]:
    validate_question_bank_v18_blueprints.validate()
    sample = _load(sample_path)
    blueprints = _load(blueprint_path)
    blueprint_by_node = {bp["node_id"]: bp for bp in blueprints["blueprints"]}

    items = sample.get("items") or []
    _assert(sample.get("status") == "draft_generated_not_active", "sample must not be active")
    _assert(len(items) == 60, f"expected 60 sample items, got {len(items)}")
    _assert(sample.get("item_count") == len(items), "item_count mismatch")
    _assert(sample.get("node_count") == 10, "sample should cover 10 representative nodes")

    ids = [item.get("id") for item in items]
    prompts = ["".join(str(item.get("prompt") or "").split()).lower() for item in items]
    structures = [item.get("quality", {}).get("structure_fingerprint") for item in items]
    _assert(len(ids) == len(set(ids)), "duplicate item id")
    _assert(len(prompts) == len(set(prompts)), "duplicate prompt")
    _assert(len(structures) == len(set(structures)), "duplicate structure fingerprint")

    by_node: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    scoring_shapes: Counter[str] = Counter()
    forbidden = [
        "本题重点是",
        "Missing the requested",
        "Add one sentence",
        "agent",
        "Agent",
        "图谱节点",
        "后台",
    ]
    for item in items:
        node_id = item.get("node_id")
        family_id = item.get("question_type")
        by_node[node_id] += 1
        by_family[family_id] += 1
        _assert(node_id in blueprint_by_node, f"{item.get('id')} references unknown blueprint node {node_id}")
        allowed_families = {entry["family_id"] for entry in blueprint_by_node[node_id]["family_plan"]}
        _assert(family_id in allowed_families, f"{item.get('id')} family {family_id} not allowed for {node_id}")
        _assert(item.get("quality", {}).get("review_status") == "draft_generated", f"{item.get('id')} must remain draft")
        _assert(item.get("quality", {}).get("activation_eligible") is False, f"{item.get('id')} must not be activation eligible")
        _assert(item.get("expected_answer"), f"{item.get('id')} missing expected_answer")
        _assert(len(item.get("solution_steps") or []) >= 3, f"{item.get('id')} needs at least 3 solution steps")
        _assert(len(item.get("scoring_targets") or []) >= 3, f"{item.get('id')} needs at least 3 scoring targets")
        _assert(len(item.get("required_evidence") or []) >= 3, f"{item.get('id')} missing item-level required_evidence")
        _assert(len(item.get("key_score_points") or []) >= 3, f"{item.get('id')} missing key_score_points")
        _assert(item.get("quality", {}).get("no_mechanical_drill") is True, f"{item.get('id')} must mark no_mechanical_drill")
        scoring_shapes[json.dumps(item.get("scoring_targets") or [], ensure_ascii=False, sort_keys=True)] += 1
        text = "\n".join([
            str(item.get("prompt") or ""),
            str(item.get("expected_answer") or ""),
            "\n".join(item.get("solution_steps") or []),
            "\n".join(item.get("required_evidence") or []),
        ])
        for phrase in forbidden:
            _assert(phrase not in text, f"{item.get('id')} leaks forbidden phrase: {phrase}")

    _assert(set(by_node.values()) == {6}, f"each sample node should have 6 items: {dict(by_node)}")
    _assert(len(scoring_shapes) >= 30, f"scoring targets are too generic: {len(scoring_shapes)} unique templates")
    _assert("M-BRIDGE-WORK-RATE" in by_node, "sample must include work-rate regression node")
    _assert("M-G7-GEO-VIEWS" in by_node, "sample must include geo-views regression node")
    _assert("M-PRE-GEO-AREA-VOLUME" in by_node, "sample must include area/volume regression node")
    _assert("M-G7-RATIONAL-ADD-SUB" in by_node, "sample must include rational add/sub regression node")

    work_rate_prompts = "\n".join(item["prompt"] for item in items if item["node_id"] == "M-BRIDGE-WORK-RATE")
    _assert("总工程" in work_rate_prompts or "一项工程" in work_rate_prompts, "work-rate prompts lack project total language")
    _assert("平均速度" not in work_rate_prompts, "work-rate sample regressed into speed topic")

    geo_prompts = "\n".join(item["prompt"] for item in items if item["node_id"] == "M-G7-GEO-VIEWS")
    _assert(any(marker in geo_prompts for marker in ["展开图", "视图", "小正方体"]), "geo-views prompts lack spatial structure")
    _assert("角平分线" not in geo_prompts, "geo-views sample regressed into angle-bisector")

    area_prompts = "\n".join(item["prompt"] for item in items if item["node_id"] == "M-PRE-GEO-AREA-VOLUME")
    _assert("角平分线" not in area_prompts, "area/volume sample regressed into angle-bisector")
    _assert(any(marker in area_prompts for marker in ["面积", "体积", "单位"]), "area/volume prompts lack area-volume structure")

    return {
        "status": "PASS",
        "items": len(items),
        "nodes": len(by_node),
        "by_node": dict(sorted(by_node.items())),
        "by_family": dict(sorted(by_family.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_path", nargs="?", default=str(SAMPLE_PATH))
    parser.add_argument("blueprint_path", nargs="?", default=str(BLUEPRINT_PATH))
    args = parser.parse_args()
    report = validate(Path(args.sample_path), Path(args.blueprint_path))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        print(f"VALIDATION FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
