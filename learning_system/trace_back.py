"""Deterministic trace-back engine (错因回查).

Implements the project's core pedagogical rule as a testable service: when a
node's problem is answered wrong, walk the prerequisite chain backward and
produce an ORDERED list of candidate nodes to re-check, instead of drilling the
same question type (AGENTS.md: "七上题错了，先沿前置依赖链回查").

Ordering rules (documented, deterministic):

1. depth first — nodes closest to the wrong node come first ("离错题最近");
2. within the same depth, edge strength first — strong edges (prereq_strength
   == "strong") before soft ("soft" or unmarked, default rule from review doc
   docs/qa/knowledge_graph_prereq_strength_review.md section 6.3);
3. within the same depth+strength, diagnosis state severity first — C/D before
   B before unknown;
4. node id as the final tie-break, so the output is fully deterministic.

Strong unlocks-only edges (graph top-level ``strong_unlock_edges``) participate
as nearest-level strong edges: they are semantic strong dependencies that are
not formal prerequisite edges (e.g. M-PRE-FRACTION-MEANING -> M-G7-EQ-WORD).
``depth`` is the hop distance from the wrong node: the wrong node is depth 0,
direct prerequisites are depth 1, and so on.

Nodes whose state is A (已掌握, mastered) are excluded from the active path and
reported in ``excluded_mastered``: re-diagnosing mastered nodes wastes time.

``earliest_breakpoint`` is the deepest node along the chain whose state is C/D
— the "最早断点" the diagnosis state model says to fix before anything else
("D 卡死：暂停当前七上内容，补最早断点").

The engine is pure: the graph is passed in (callers already hold a loaded
snapshot), states are an optional {node_id: "A"|"B"|"C"|"D"} map. It never
reads or writes files and never mutates its inputs.

Usage:
    from learning_system.trace_back import trace_back
    result = trace_back(graph, "M-G7-EQ-WORD", states={"M-PRE-INTEGER-OPS": "C"})
    for entry in result["path"]:
        print(entry["node_id"], entry["edge_strength"], entry["depth"])
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

STRENGTH_RANK = {"strong": 0, "soft": 1}
STATE_RANK = {"C": 0, "D": 0, "B": 1}  # unknown state gets rank 2
VALID_STATES = {"A", "B", "C", "D"}
RELATION_PREREQUISITE = "prerequisite"
RELATION_UNLOCK_STRONG = "unlock_strong"

_EDGE_FIELDS = ("node_id", "name", "relation", "edge_strength", "depth", "state")


def _edge_strength(edge: dict[str, Any]) -> str:
    strength = edge.get("prereq_strength")
    return strength if strength in STRENGTH_RANK else "soft"


def _collect_edges(graph: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    """Return (source, target, strength, kind, rationale) tuples."""
    edges: list[tuple[str, str, str, str, str]] = []
    for edge in graph.get("prerequisite_edges", []):
        edges.append((
            str(edge.get("from", "")),
            str(edge.get("to", "")),
            _edge_strength(edge),
            RELATION_PREREQUISITE,
            str(edge.get("strength_rationale", "")),
        ))
    for entry in graph.get("strong_unlock_edges", []):
        if not isinstance(entry, str) or "→" not in entry:
            continue
        source, target = entry.split("→")
        edges.append((source, target, "strong", RELATION_UNLOCK_STRONG, ""))
    return edges


def trace_back(
    graph: dict[str, Any],
    wrong_node_id: str,
    states: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ordered prerequisite trace-back for a wrong node.

    Returns a dict with keys: valid, errors, warnings, wrong_node, path,
    excluded_mastered, earliest_breakpoint, recommendation. Never raises on
    malformed input beyond a missing ``nodes`` list.
    """
    states = states or {}
    errors: list[str] = []
    warnings: list[str] = []

    nodes = {str(node.get("id", "")): node for node in graph.get("nodes", [])}
    if wrong_node_id not in nodes:
        return {
            "valid": False,
            "errors": [f"wrong_node not in graph: {wrong_node_id}"],
            "warnings": [],
            "wrong_node": wrong_node_id,
            "path": [],
            "excluded_mastered": [],
            "earliest_breakpoint": None,
            "recommendation": "",
        }

    for node_id, state in states.items():
        if node_id not in nodes:
            warnings.append(f"state key not in graph, ignored: {node_id}")
        elif state not in VALID_STATES:
            warnings.append(f"state value invalid for {node_id}: {state!r} (expected A/B/C/D)")

    entries = _build_ordered_entries(graph, wrong_node_id, states, nodes)
    path = [entry for entry in entries if entry["state"] != "A"]
    excluded_mastered = sorted(entry["node_id"] for entry in entries if entry["state"] == "A")

    # Earliest breakpoint: deepest C/D node along the chain.
    broken = [entry for entry in path if entry["state"] in {"C", "D"}]
    earliest_breakpoint = max(broken, key=lambda entry: entry["depth"])["node_id"] if broken else None

    recommendation = _recommendation(nodes[wrong_node_id], path, earliest_breakpoint)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "wrong_node": wrong_node_id,
        "path": path,
        "excluded_mastered": excluded_mastered,
        "earliest_breakpoint": earliest_breakpoint,
        "recommendation": recommendation,
    }


def _build_ordered_entries(
    graph: dict[str, Any],
    wrong_node_id: str,
    states: dict[str, str],
    nodes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reverse-BFS from the wrong node and order every chain entry by
    (depth, edge strength, state severity, node id). Includes mastered nodes:
    callers decide what to do with them. Cycle-safe via the visited set."""
    # Reverse adjacency: target -> list of (source, strength, kind, rationale).
    reverse: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for source, target, strength, kind, rationale in _collect_edges(graph):
        if source in nodes and target in nodes:
            reverse[target].append((source, strength, kind, rationale))

    depth: dict[str, int] = {wrong_node_id: 0}
    first_edge: dict[str, tuple[str, str, str]] = {}
    queue: deque[str] = deque([wrong_node_id])
    while queue:
        current = queue.popleft()
        neighbors = sorted(
            reverse.get(current, []),
            key=lambda item: (STRENGTH_RANK.get(item[1], 1), item[0]),
        )
        for source, strength, kind, rationale in neighbors:
            if source in depth:
                continue
            depth[source] = depth[current] + 1
            first_edge[source] = (strength, kind, rationale)
            queue.append(source)

    entries: list[dict[str, Any]] = []
    for node_id in depth:
        if node_id == wrong_node_id:
            continue
        state = states.get(node_id, "unknown")
        strength, kind, rationale = first_edge.get(node_id, ("soft", RELATION_PREREQUISITE, ""))
        entries.append({
            "node_id": node_id,
            "name": str(nodes[node_id].get("name", "")),
            "relation": kind,
            "edge_strength": strength,
            "edge_rationale": rationale,
            "depth": depth[node_id],
            "state": state,
        })
    entries.sort(
        key=lambda entry: (
            entry["depth"],
            STRENGTH_RANK.get(entry["edge_strength"], 1),
            STATE_RANK.get(entry["state"], 2),
            entry["node_id"],
        )
    )
    return entries


def ordered_prerequisite_candidates(
    graph: dict[str, Any],
    node_id: str,
    states: dict[str, str] | None = None,
) -> list[str]:
    """Ordered node ids on the trace-back chain of ``node_id``: formal
    prerequisites plus strong unlocks-only edges, closest first and strong
    edges before soft. Mastered nodes are included — they remain legitimate
    targets; callers deprioritize them. Returns [] for an unknown node or a
    node with no prerequisites.

    This is the consumer-facing API for planner/agents (review doc section 7.3:
    rollback ordering must check strong edges before soft edges).
    """
    states = states or {}
    nodes = {str(node.get("id", "")): node for node in graph.get("nodes", [])}
    if node_id not in nodes:
        return []
    entries = _build_ordered_entries(graph, node_id, states, nodes)
    return [entry["node_id"] for entry in entries]


def _recommendation(
    wrong_node: dict[str, Any],
    path: list[dict[str, Any]],
    earliest_breakpoint: str | None,
) -> str:
    if not path:
        return f"{wrong_node.get('name', wrong_node.get('id'))} 无前置依赖，直接在本节点诊断。"
    sequence = " → ".join(
        f"{entry['node_id']}({entry['edge_strength']}/{entry['depth']})" for entry in path
    )
    text = f"{wrong_node.get('name', wrong_node.get('id'))} 回查顺序：{sequence}"
    if earliest_breakpoint:
        text += f"；检测到薄弱节点 {earliest_breakpoint}（C/D），建议优先回退补齐"
    return text
