#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
TAXONOMY_PATH = ROOT / "data/question_banks/v18/question_type_taxonomy_v18.json"
BLUEPRINT_PATH = ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"


class ValidationError(AssertionError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _taxonomy_families(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for cluster in taxonomy.get("clusters") or []:
        cluster_id = cluster.get("cluster_id")
        for family in cluster.get("families") or []:
            family_id = family.get("family_id")
            _assert(family_id, f"taxonomy family missing family_id in {cluster_id}")
            _assert(family_id not in families, f"duplicate family_id: {family_id}")
            _assert(family.get("cluster_id") == cluster_id, f"{family_id} missing normalized cluster_id={cluster_id}")
            for key in ["family_name", "measures", "difficulty_range", "required_surface_features", "forbidden_surface_features", "scoring_basis", "typical_error_mapping"]:
                _assert(family.get(key), f"{family_id} missing {key}")
            families[family_id] = family
    _assert(len(families) >= 40, f"taxonomy too small: {len(families)} families")
    return families


def _assert(condition: Any, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate(
    graph_path: Path = GRAPH_PATH,
    taxonomy_path: Path = TAXONOMY_PATH,
    blueprint_path: Path = BLUEPRINT_PATH,
) -> dict[str, Any]:
    graph = _load(graph_path)
    taxonomy = _load(taxonomy_path)
    blueprints_doc = _load(blueprint_path)

    graph_nodes = {node["id"]: node for node in graph.get("nodes") or []}
    families = _taxonomy_families(taxonomy)
    support_families = {fid for fid, family in families.items() if family.get("support_only")}

    blueprints = blueprints_doc.get("blueprints") or []
    blueprint_ids = [bp.get("node_id") for bp in blueprints]
    _assert(len(graph_nodes) == 56, f"expected 56 graph nodes, got {len(graph_nodes)}")
    _assert(len(blueprints) == 56, f"expected 56 blueprints, got {len(blueprints)}")
    _assert(len(blueprint_ids) == len(set(blueprint_ids)), "duplicate blueprint node_id")
    _assert(set(blueprint_ids) == set(graph_nodes), "blueprint coverage does not exactly match graph nodes")

    cluster_counts: Counter[str] = Counter()
    family_use: Counter[str] = Counter()
    for bp in blueprints:
        node_id = bp["node_id"]
        graph_node = graph_nodes[node_id]
        cluster = bp.get("cluster")
        cluster_counts[cluster] += 1
        for key in [
            "node_name",
            "cluster",
            "priority",
            "module_id",
            "node_capability",
            "scope_in",
            "scope_out",
            "candidate_budget",
            "family_plan",
            "review_must_reject",
            "sample_seed_ideas",
            "generation_policy",
        ]:
            _assert(bp.get(key), f"{node_id} missing {key}")
        _assert(bp["node_name"] == graph_node["name"], f"{node_id} node_name mismatch")
        _assert(bp["priority"] == graph_node["priority"], f"{node_id} priority mismatch")

        budget = bp["candidate_budget"]
        for key in ["min", "target", "max"]:
            _assert(isinstance(budget.get(key), int), f"{node_id} budget.{key} must be int")
        _assert(budget["min"] <= budget["target"] <= budget["max"], f"{node_id} invalid budget ordering")
        if bp["priority"] == "P2":
            _assert(budget["target"] <= 8 and budget["max"] <= 10, f"{node_id} P2 budget too high: {budget}")
        if bp["priority"] == "P0":
            _assert(budget["target"] >= 12, f"{node_id} P0 target too low: {budget}")

        family_plan = bp["family_plan"]
        _assert(len(family_plan) >= 4, f"{node_id} needs at least 4 family plan entries")
        real_family_count = 0
        support_count = 0
        target_sum = 0
        for entry in family_plan:
            family_id = entry.get("family_id")
            _assert(family_id in families, f"{node_id} uses unknown family_id {family_id}")
            family = families[family_id]
            family_use[family_id] += 1
            target_sum += int(entry.get("target_count") or 0)
            _assert(entry.get("target_count", 0) > 0, f"{node_id}/{family_id} target_count must be positive")
            _assert(entry.get("difficulty"), f"{node_id}/{family_id} missing difficulty")
            _assert(entry.get("evidence_focus"), f"{node_id}/{family_id} missing evidence_focus")
            _assert(entry.get("required_evidence"), f"{node_id}/{family_id} missing required_evidence")
            _assert(len(entry["required_evidence"]) >= 2, f"{node_id}/{family_id} required_evidence too thin")
            if family_id in support_families:
                support_count += 1
            else:
                real_family_count += 1
            if family["cluster_id"] != cluster:
                _assert(entry.get("adaptation_note"), f"{node_id}/{family_id} cross-cluster use needs adaptation_note")
        _assert(target_sum == budget["target"], f"{node_id} family target sum {target_sum} != budget target {budget['target']}")
        if cluster == "learning_process":
            _assert(real_family_count >= 2, f"{node_id} process node still needs math-bearing families")
        else:
            _assert(real_family_count >= 3, f"{node_id} needs at least 3 real math families, got {real_family_count}")
            _assert(support_count <= 1, f"{node_id} support-only families cannot dominate")

        rejects = "\n".join(bp["review_must_reject"] + bp["scope_out"])
        seeds = "\n".join(bp["sample_seed_ideas"])
        _assert("低龄" in rejects or "机械" in rejects or bp["priority"] == "P2", f"{node_id} lacks low-age/mechanical reject")
        _assert("本题重点是" not in seeds, f"{node_id} sample seeds leak backend meta wording")

    _validate_regression_negative_gates({bp["node_id"]: bp for bp in blueprints})

    unused = sorted(set(families) - set(family_use))
    _assert(not unused, f"taxonomy has unused families; either remove or bind deliberately: {unused}")

    return {
        "status": "PASS",
        "graph_nodes": len(graph_nodes),
        "blueprints": len(blueprints),
        "taxonomy_families": len(families),
        "clusters": dict(sorted(cluster_counts.items())),
        "support_families": sorted(support_families),
    }


def _validate_regression_negative_gates(by_node: dict[str, dict[str, Any]]) -> None:
    required_markers = {
        "M-G7-RATIONAL-ADD-SUB": ["只比较大小", "数轴", "加减动作"],
        "M-BRIDGE-WORK-RATE": ["速度×时间", "工作总量=1", "效率"],
        "M-G7-GEO-VIEWS": ["角平分线", "展开图", "视图"],
        "M-PRE-GEO-AREA-VOLUME": ["角度题", "公式结构", "单位维度"],
    }
    for node_id, markers in required_markers.items():
        bp = by_node[node_id]
        text = "\n".join(bp.get("review_must_reject") or []) + "\n" + "\n".join(bp.get("scope_out") or [])
        for marker in markers:
            _assert(marker in text, f"{node_id} missing v17 regression reject marker: {marker}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print machine-readable validation report")
    args = parser.parse_args()
    report = validate()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("VALIDATION PASS: v18 question-bank blueprints")
        for key, value in report.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        print(f"VALIDATION FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
