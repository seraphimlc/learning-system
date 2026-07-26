from __future__ import annotations

import json
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AdminInventoryError(ValueError):
    pass


DEFAULT_GRAPH_PATH = Path("data/knowledge_graphs/math/math_knowledge_graph_v2.json")
DEFAULT_V18_SAMPLE_PATH = Path("data/question_banks/v18/math_v18_sample_60.json")
DEFAULT_V18_STAGED_PATH = Path("data/question_banks/v18/staged_candidates_v18.json")
DEFAULT_V18_BLUEPRINT_PATH = Path("data/question_banks/v18/node_question_blueprints_v18.json")
DEFAULT_V18_TAXONOMY_PATH = Path("data/question_banks/v18/question_type_taxonomy_v18.json")


@dataclass(frozen=True)
class AdminPaths:
    root: Path
    graph_path: Path = DEFAULT_GRAPH_PATH
    sample_path: Path = DEFAULT_V18_SAMPLE_PATH
    staged_path: Path = DEFAULT_V18_STAGED_PATH
    blueprint_path: Path = DEFAULT_V18_BLUEPRINT_PATH
    taxonomy_path: Path = DEFAULT_V18_TAXONOMY_PATH

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.root / path


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise AdminInventoryError(f"ADMIN_SOURCE_MISSING: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdminInventoryError(f"ADMIN_SOURCE_INVALID_JSON: {path}: {exc}") from exc


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _load_assets(paths: AdminPaths) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph = _load_json(paths.resolve(paths.graph_path))
    sample = _load_json(paths.resolve(paths.sample_path))
    blueprints = _load_json(paths.resolve(paths.blueprint_path))
    taxonomy = _load_json(paths.resolve(paths.taxonomy_path))
    return graph, sample, blueprints, taxonomy


def _families_by_id(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for cluster in taxonomy.get("clusters") or []:
        for family in cluster.get("families") or []:
            family_id = str(family.get("family_id") or "")
            if family_id:
                families[family_id] = family
    return families


def _blueprints_by_node(blueprints: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(blueprint.get("node_id")): blueprint
        for blueprint in blueprints.get("blueprints") or []
        if blueprint.get("node_id")
    }


def _graph_nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("id")): node
        for node in graph.get("nodes") or []
        if node.get("id")
    }


def _item_status(item: dict[str, Any]) -> str:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    review_status = str(quality.get("review_status") or item.get("review_status") or "")
    activation_eligible = bool(quality.get("activation_eligible") or item.get("activation_eligible"))
    if activation_eligible:
        return "activation_eligible"
    return review_status or "unknown"


def _item_fingerprint(item: dict[str, Any]) -> str:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return str(
        quality.get("canonical_structure_fingerprint")
        or item.get("canonical_structure_fingerprint")
        or quality.get("structure_fingerprint")
        or item.get("structure_fingerprint")
        or item.get("math_core_signature")
        or item.get("variant_signature")
        or ""
    )


def canonical_structure_fingerprint_for_item(item: dict[str, Any]) -> str:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    lineage = item.get("production_lineage") if isinstance(item.get("production_lineage"), dict) else {}

    def normalize_text(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", "#", text)
        text = re.sub(r"[a-z]", "x", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    score_keys = [
        str(point.get("key") or "")
        for point in item.get("key_score_points") or []
        if isinstance(point, dict)
    ]
    seed = {
        "node_id": item.get("node_id"),
        "family_id": item.get("question_type"),
        "difficulty": item.get("difficulty") or item.get("variant_level"),
        "evidence_goal": item.get("evidence_goal") or lineage.get("evidence_goal"),
        "answer_format": normalize_text(item.get("answer_format")),
        "prompt_shell": normalize_text(item.get("prompt")),
        "solution_shell": [normalize_text(step) for step in item.get("solution_steps") or []],
        "score_keys": score_keys,
        "target_error_tags": [str(value) for value in item.get("target_error_tags") or []],
    }
    return "CANON-" + hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _budget_gap(current_count: int, budget: dict[str, Any] | None) -> dict[str, Any]:
    budget = budget or {}
    minimum = int(budget.get("min") or 0)
    target = int(budget.get("target") or minimum)
    maximum = int(budget.get("max") or target)
    return {
        "current": current_count,
        "min": minimum,
        "target": target,
        "max": maximum,
        "missing_to_min": max(0, minimum - current_count),
        "missing_to_target": max(0, target - current_count),
        "over_max_by": max(0, current_count - maximum),
    }


def _duplicate_fingerprint_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_fp: defaultdict[str, list[str]] = defaultdict(list)
    for item in items:
        fingerprint = _item_fingerprint(item)
        if fingerprint:
            by_fp[fingerprint].append(str(item.get("id") or ""))
    return [
        {"fingerprint": fingerprint, "item_ids": sorted(item_ids)}
        for fingerprint, item_ids in sorted(by_fp.items())
        if len(item_ids) > 1
    ]


def _question_bank_path(paths: AdminPaths, version: str, *, bank_path: Path | None = None) -> Path:
    if bank_path is not None:
        return paths.resolve(bank_path)
    if version in {"v18", "v18-staged", "2026-07-23.bank.v18.staged"}:
        return paths.resolve(paths.staged_path)
    if version in {"v18-sample", "2026-07-22.bank.v18.sample-60"}:
        return paths.resolve(paths.sample_path)
    candidate = Path(version)
    if candidate.suffix == ".json":
        return paths.resolve(candidate)
    raise AdminInventoryError(f"ADMIN_UNSUPPORTED_QUESTION_BANK_VERSION: {version}")


def _question_bank_scope(bank: dict[str, Any]) -> str:
    if bank.get("status") == "draft_generated_not_active" or "sample" in str(bank.get("question_bank_version") or ""):
        return "sample"
    return "staged_or_explicit"


def build_question_bank_inventory(
    *,
    root: Path,
    version: str = "v18",
    subject: str = "math",
    bank_path: Path | None = None,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints, taxonomy = _load_assets(paths)
    resolved_bank_path = _question_bank_path(paths, version, bank_path=bank_path)
    bank = _load_json(resolved_bank_path)

    nodes_by_id = _graph_nodes_by_id(graph)
    blueprints_by_id = _blueprints_by_node(blueprints)
    families_by_id = _families_by_id(taxonomy)
    items = list(bank.get("items") or [])

    by_node: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    by_difficulty: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    unsupported_nodes: set[str] = set()
    unsupported_families: set[str] = set()
    answer_contract_like_count = 0

    for item in items:
        node_id = str(item.get("node_id") or "")
        family_id = str(item.get("question_type") or item.get("problem_family_id") or "")
        difficulty = str(item.get("difficulty") or item.get("variant_level") or "unknown")
        by_node[node_id] += 1
        by_family[family_id] += 1
        by_difficulty[difficulty] += 1
        by_status[_item_status(item)] += 1
        if node_id and node_id not in nodes_by_id:
            unsupported_nodes.add(node_id)
        if family_id and family_id not in families_by_id:
            unsupported_families.add(family_id)
        if item.get("standard_answer") and item.get("key_score_points"):
            answer_contract_like_count += 1

    budget_gaps = []
    for node_id, blueprint in sorted(blueprints_by_id.items()):
        gap = _budget_gap(by_node.get(node_id, 0), blueprint.get("candidate_budget"))
        if gap["missing_to_min"] or gap["missing_to_target"] or gap["over_max_by"]:
            budget_gaps.append({"node_id": node_id, "node_name": blueprint.get("node_name"), **gap})

    sample_only = bank.get("status") == "draft_generated_not_active" or "sample" in str(bank.get("question_bank_version") or "")
    activation_allowed = not sample_only and by_status.get("active", 0) > 0
    recommended_actions = []
    if sample_only:
        recommended_actions.append("sample_only_do_not_activate")
    if budget_gaps:
        recommended_actions.append("fill_candidate_budget_gaps")
    if unsupported_nodes or unsupported_families:
        recommended_actions.append("repair_unsupported_bindings")
    duplicate_groups = _duplicate_fingerprint_groups(items)
    if duplicate_groups:
        recommended_actions.append("review_duplicate_structure_fingerprints")

    return {
        "schema_version": "2026-07-23.codex-admin.inventory.v1",
        "subject": subject,
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_status": str(bank.get("status") or "unknown"),
        "inventory_scope": _question_bank_scope(bank),
        "source_path": str(resolved_bank_path.relative_to(root) if resolved_bank_path.is_absolute() and resolved_bank_path.is_relative_to(root) else resolved_bank_path),
        "item_count": len(items),
        "graph_node_count": len(nodes_by_id),
        "blueprint_node_count": len(blueprints_by_id),
        "taxonomy_family_count": len(families_by_id),
        "covered_node_count": len([node_id for node_id, count in by_node.items() if node_id and count]),
        "covered_family_count": len([family_id for family_id, count in by_family.items() if family_id and count]),
        "counts_by_node": _counter_dict(by_node),
        "counts_by_family": _counter_dict(by_family),
        "counts_by_difficulty": _counter_dict(by_difficulty),
        "counts_by_status": _counter_dict(by_status),
        "answer_contract_like_coverage": {
            "items_with_standard_answer_and_score_points": answer_contract_like_count,
            "total_items": len(items),
        },
        "budget_gaps": budget_gaps,
        "unsupported_nodes": sorted(unsupported_nodes),
        "unsupported_families": sorted(unsupported_families),
        "duplicate_structure_fingerprint_groups": duplicate_groups,
        "activation": {
            "sample_only": sample_only,
            "activation_allowed_by_inventory": activation_allowed,
            "note": "Inventory never grants activation; activation must pass receipt gates.",
        },
        "recommended_actions": recommended_actions,
    }


def build_node_inventory(
    *,
    root: Path,
    node_id: str,
    version: str = "v18",
    subject: str = "math",
    bank_path: Path | None = None,
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints, taxonomy = _load_assets(paths)
    resolved_bank_path = _question_bank_path(paths, version, bank_path=bank_path)
    bank = _load_json(resolved_bank_path)
    nodes_by_id = _graph_nodes_by_id(graph)
    blueprints_by_id = _blueprints_by_node(blueprints)
    families_by_id = _families_by_id(taxonomy)
    if node_id not in nodes_by_id:
        raise AdminInventoryError(f"ADMIN_UNKNOWN_GRAPH_NODE: {node_id}")

    items = [item for item in bank.get("items") or [] if item.get("node_id") == node_id]
    by_family: Counter[str] = Counter(str(item.get("question_type") or "") for item in items)
    by_difficulty: Counter[str] = Counter(str(item.get("difficulty") or "unknown") for item in items)
    by_status: Counter[str] = Counter(_item_status(item) for item in items)
    blueprint = blueprints_by_id.get(node_id, {})
    planned_families = [entry.get("family_id") for entry in blueprint.get("family_plan") or [] if entry.get("family_id")]
    missing_planned_families = sorted(set(planned_families) - set(by_family))
    unsupported_families = sorted(family for family in by_family if family and family not in families_by_id)

    return {
        "schema_version": "2026-07-23.codex-admin.node-inventory.v1",
        "subject": subject,
        "node_id": node_id,
        "node_name": nodes_by_id[node_id].get("name"),
        "priority": nodes_by_id[node_id].get("priority"),
        "stage": nodes_by_id[node_id].get("stage"),
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_status": str(bank.get("status") or "unknown"),
        "inventory_scope": _question_bank_scope(bank),
        "source_path": str(resolved_bank_path.relative_to(root) if resolved_bank_path.is_absolute() and resolved_bank_path.is_relative_to(root) else resolved_bank_path),
        "item_count": len(items),
        "candidate_budget": _budget_gap(len(items), blueprint.get("candidate_budget") if blueprint else None),
        "counts_by_family": _counter_dict(by_family),
        "counts_by_difficulty": _counter_dict(by_difficulty),
        "counts_by_status": _counter_dict(by_status),
        "planned_families": planned_families,
        "missing_planned_families": missing_planned_families,
        "unsupported_families": unsupported_families,
        "duplicate_structure_fingerprint_groups": _duplicate_fingerprint_groups(items),
        "items": [
            {
                "id": item.get("id"),
                "family_id": item.get("question_type"),
                "difficulty": item.get("difficulty"),
                "status": _item_status(item),
                "activation_eligible": bool((item.get("quality") or {}).get("activation_eligible")),
            }
            for item in items
        ],
        "recommended_actions": [
            action
            for action, enabled in [
                ("fill_candidate_budget_gap", _budget_gap(len(items), blueprint.get("candidate_budget") if blueprint else None)["missing_to_target"] > 0),
                ("add_missing_planned_families", bool(missing_planned_families)),
                ("repair_unsupported_families", bool(unsupported_families)),
            ]
            if enabled
        ],
    }


def format_inventory_text(report: dict[str, Any]) -> str:
    lines = [
        f"schema: {report.get('schema_version')}",
        f"subject: {report.get('subject')}",
        f"question_bank_version: {report.get('question_bank_version')}",
        f"question_bank_status: {report.get('question_bank_status')}",
    ]
    if "node_id" in report:
        lines.extend([
            f"node: {report.get('node_id')} {report.get('node_name')}",
            f"item_count: {report.get('item_count')}",
            f"counts_by_family: {json.dumps(report.get('counts_by_family', {}), ensure_ascii=False, sort_keys=True)}",
            f"counts_by_difficulty: {json.dumps(report.get('counts_by_difficulty', {}), ensure_ascii=False, sort_keys=True)}",
            f"recommended_actions: {', '.join(report.get('recommended_actions') or []) or 'none'}",
        ])
        return "\n".join(lines)
    lines.extend([
        f"item_count: {report.get('item_count')}",
        f"graph_node_count: {report.get('graph_node_count')}",
        f"covered_node_count: {report.get('covered_node_count')}",
        f"covered_family_count: {report.get('covered_family_count')}",
        f"counts_by_status: {json.dumps(report.get('counts_by_status', {}), ensure_ascii=False, sort_keys=True)}",
        f"budget_gap_count: {len(report.get('budget_gaps') or [])}",
        f"activation: {json.dumps(report.get('activation', {}), ensure_ascii=False, sort_keys=True)}",
        f"recommended_actions: {', '.join(report.get('recommended_actions') or []) or 'none'}",
    ])
    return "\n".join(lines)
