"""Knowledge graph v2 contract validator.

Single source of truth lives on the node side: each node's
``taxonomy.module_id`` (proposal docs/design/specs/module_node_mapping_proposal.md).
The module -> nodes reverse index is a derived view built by
``learning_system/graph_runtime.py`` and is never stored.

This module implements the contract rules:

- R1: module codes match ``^[A-Z]_[A-Z]+(_[A-Z]+)*$``
- R2: every node has a non-empty string ``taxonomy.module_id``
- R3: no dangling references (module_id hits a top-level modules key) and the
      mapping is closed (every modules key is referenced by at least one node)
- R4: no empty modules
- R5: node ``taxonomy.module_name`` == ``modules[module_id].name`` (zero drift)
- R6: node ``domain`` falls inside the known legal domain set (soft warning)
- R7: phase-1 ``prereq_strength`` backfill contract (review doc
      docs/qa/knowledge_graph_prereq_strength_review.md section 6):
      every edge leaving a phase-1 reviewed node is marked strong|soft;
      strong edges carry a non-empty ``strength_rationale``;
      the documented soft-node exception edge is strong;
      ``strong_unlock_edges`` entries are valid ids, are unlocks-only, and
      their source is a phase-1 strong node.

Usage:
    python3 -m learning_system.graph_contract   # exit 1 on contract errors
    from learning_system.graph_contract import validate_graph
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"

MODULE_CODE_RE = re.compile(r"^[A-Z]_[A-Z]+(_[A-Z]+)*$")

# Phase-1 reviewed nodes (review doc section 2): 16 strong + 8 soft.
PHASE1_STRONG_NODES = {
    "M-PRE-NUMBER-SENSE",
    "M-PRE-INTEGER-OPS",
    "M-PRE-ORDER-OPS",
    "M-PRE-FRACTION-OPS",
    "M-PRE-QUANTITY-RELATION",
    "M-PRE-EQUATION-BASIC",
    "M-PRE-LETTER-EXPR",
    "M-PRE-FRACTION-MEANING",
    "M-PRE-DECIMAL-OPS",
    "M-BRIDGE-SOLUTION-HABIT",
    "M-PRE-DISTRIBUTIVE",
    "M-BRIDGE-WORD-PROBLEM-READING",
    "M-BRIDGE-SUM-DIFF-MULTIPLE",
    "M-BRIDGE-MOTION-BASIC",
    "M-PRE-ANGLE-BASIC",
    "M-PRE-PERCENT",
}
PHASE1_SOFT_NODES = {
    "M-PRE-RATIO-PROP",
    "M-BRIDGE-MOTION-CHASE",
    "M-BRIDGE-PERCENT-MODEL",
    "M-BRIDGE-PROPORTION-MODEL",
    "M-BRIDGE-CLOCK-ANGLE",
    "M-BRIDGE-WORK-RATE",
    "M-PRE-GEO-AREA-VOLUME",
    "M-PRE-UNIT-CONVERSION",
}
PHASE1_NODES = PHASE1_STRONG_NODES | PHASE1_SOFT_NODES

# Documented soft-node exception: the one edge that is strong although its
# source node is phase-1 soft (review doc section 2 note on M-PRE-UNIT-CONVERSION).
SOFT_NODE_EXCEPTION_EDGE = "M-PRE-UNIT-CONVERSION→M-G7-SEGMENT-MEASURE"

# Legal domain values from the proposal's mapping table (section 6).
LEGAL_DOMAINS = {
    "数与运算",
    "数与代数",
    "应用建模",
    "应用建模/几何",
    "有理数",
    "有理数运算",
    "代数式与整式",
    "整式加减",
    "一元一次方程",
    "几何图形初步",
    "图形与几何",
    "图形与量",
    "学习流程",
}

STRENGTH_VALUES = {"strong", "soft"}


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Validate the module mapping contract (R1-R6) and the phase-1
    prereq_strength backfill contract (R7). Read-only; never mutates input."""
    errors: list[str] = []
    warnings: list[str] = []

    modules = graph.get("modules") or {}
    module_ids = set(modules)
    nodes = graph.get("nodes") or []
    prereq_edges = graph.get("prerequisite_edges") or []
    strong_unlock_edges = graph.get("strong_unlock_edges") or []

    # ---- R1: module code naming ----
    for code in sorted(module_ids):
        if not MODULE_CODE_RE.match(code):
            errors.append(f"R1 module code invalid: {code!r}")

    # ---- R2/R3: node module_id validity and closure ----
    referenced: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id", ""))
        taxonomy = node.get("taxonomy") or {}
        module_id = taxonomy.get("module_id")
        if not isinstance(module_id, str) or not module_id.strip():
            errors.append(f"R2 node {node_id}: taxonomy.module_id missing or empty")
            continue
        if module_id not in module_ids:
            errors.append(f"R3 node {node_id}: module_id {module_id!r} not in modules keys")
            continue
        referenced.add(module_id)

        # ---- R5: module_name drift ----
        module_name = taxonomy.get("module_name")
        canonical = modules[module_id].get("name")
        if module_name != canonical:
            errors.append(
                f"R5 node {node_id}: module_name {module_name!r} != modules[{module_id!r}].name {canonical!r}"
            )

        # ---- R6: domain soft check ----
        domain = node.get("domain")
        if domain is not None and str(domain) not in LEGAL_DOMAINS:
            warnings.append(f"R6 node {node_id}: domain {domain!r} outside known domain set")

    for code in sorted(module_ids):
        if code not in referenced:
            errors.append(f"R3/R4 orphan module: {code!r} referenced by no node")

    # ---- R7a: phase-1 edges all marked ----
    phase1_unmarked: list[str] = []
    for edge in prereq_edges:
        source = edge.get("from")
        if source not in PHASE1_NODES:
            continue
        if "prereq_strength" not in edge:
            phase1_unmarked.append(f"{source}->{edge.get('to')}")
    for unmarked in phase1_unmarked:
        errors.append(f"R7a phase-1 edge unmarked: {unmarked}")

    # ---- R7b: enum + rationale on strong ----
    edge_stats = {"strong": 0, "soft": 0}
    for edge in prereq_edges:
        strength = edge.get("prereq_strength")
        if strength is None:
            continue
        if strength not in STRENGTH_VALUES:
            errors.append(
                f"R7b edge {edge.get('from')}->{edge.get('to')}: prereq_strength {strength!r} not in {sorted(STRENGTH_VALUES)}"
            )
            continue
        edge_stats[strength] += 1
        if strength == "strong":
            rationale = str(edge.get("strength_rationale", "")).strip()
            if not rationale:
                errors.append(
                    f"R7b strong edge {edge.get('from')}->{edge.get('to')} missing strength_rationale"
                )

    # ---- R7c: soft-node exception edge must be strong ----
    exception_source, exception_target = SOFT_NODE_EXCEPTION_EDGE.split("→")
    exception_edge = next(
        (
            edge
            for edge in prereq_edges
            if edge.get("from") == exception_source and edge.get("to") == exception_target
        ),
        None,
    )
    if exception_edge is None:
        errors.append(
            f"R7c exception edge {SOFT_NODE_EXCEPTION_EDGE} not found in prerequisite_edges"
        )
    elif exception_edge.get("prereq_strength") != "strong":
        errors.append(
            f"R7c exception edge {SOFT_NODE_EXCEPTION_EDGE} must be strong, got {exception_edge.get('prereq_strength')!r}"
        )

    # ---- R7d: strong_unlock_edges format and unlocks-only semantics ----
    prereq_pairs = {(edge.get("from"), edge.get("to")) for edge in prereq_edges}
    unlock_pairs = {
        (str(node.get("id")), str(unlocked))
        for node in nodes
        for unlocked in node.get("unlocks", [])
    }
    node_ids = {str(node.get("id")) for node in nodes}
    production_contract_required = {
        "contract_version",
        "review_status",
        "scope",
        "evidence",
        "question_hints",
        "error_model",
        "source_fields",
    }
    for node in nodes:
        node_id = str(node.get("id", ""))
        contract = node.get("production_contract")
        if not isinstance(contract, dict):
            errors.append(f"production_contract node {node_id}: missing or not an object")
            continue
        missing = sorted(production_contract_required - set(contract))
        if missing:
            errors.append(f"production_contract node {node_id}: missing fields {','.join(missing)}")
        if contract.get("contract_version") != "node-production-contract.v1":
            errors.append(f"production_contract node {node_id}: unsupported contract_version")
        for section in ("scope", "evidence", "question_hints", "error_model"):
            if not isinstance(contract.get(section), dict):
                errors.append(f"production_contract node {node_id}: {section} must be an object")
        if not isinstance(contract.get("source_fields"), list) or not contract.get("source_fields"):
            errors.append(f"production_contract node {node_id}: source_fields must be a non-empty list")
    for entry in strong_unlock_edges:
        if not isinstance(entry, str) or "→" not in entry:
            errors.append(f"R7d strong_unlock_edges entry not 'from→to': {entry!r}")
            continue
        source, target = entry.split("→")
        if source not in node_ids or target not in node_ids:
            errors.append(f"R7d strong_unlock_edges entry has unknown ids: {entry!r}")
        elif (source, target) not in unlock_pairs:
            errors.append(f"R7d strong_unlock_edges entry is not an unlock: {entry!r}")
        elif (source, target) in prereq_pairs:
            errors.append(
                f"R7d strong_unlock_edges entry is a formal edge (not unlocks-only): {entry!r}"
            )
        if source not in PHASE1_STRONG_NODES:
            errors.append(
                f"R7d strong_unlock_edges source {source!r} is not a phase-1 strong node"
            )

    # ---- module node counts for the report ----
    module_node_counts: dict[str, int] = {}
    for node in nodes:
        module_id = (node.get("taxonomy") or {}).get("module_id")
        if isinstance(module_id, str) and module_id:
            module_node_counts[module_id] = module_node_counts.get(module_id, 0) + 1

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "module_count": len(module_ids),
        "module_node_counts": dict(sorted(module_node_counts.items())),
        "edge_stats": {
            "prerequisite_edges": len(prereq_edges),
            "marked_strong": edge_stats["strong"],
            "marked_soft": edge_stats["soft"],
            "unmarked_phase1": len(phase1_unmarked),
            "strong_unlock_edges": len(strong_unlock_edges),
        },
    }


def _main() -> int:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    report = validate_graph(graph)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(_main())
