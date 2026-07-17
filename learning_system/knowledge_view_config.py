from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


VIEW_SCHEMA_VERSION = "knowledge-views.v1"
VIEW_CONFIG_VERSION = "2026-07-14.v5.1"


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _edge_set(items: Iterable[Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for item in items:
        if isinstance(item, dict):
            source = item.get("source") or item.get("from")
            target = item.get("target") or item.get("to")
        else:
            source, target = item
        result.add((str(source), str(target)))
    return result


@dataclass(frozen=True)
class KnowledgeViewConfig:
    payload: dict[str, Any]
    validation_report: dict[str, Any]

    @classmethod
    def load_validated(
        cls,
        path: Path | str,
        graph_snapshot: dict[str, Any],
    ) -> "KnowledgeViewConfig":
        config_path = Path(path)
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("knowledge-view config must be a JSON object")
        report = _validate_config(payload, graph_snapshot)
        return cls(payload=payload, validation_report=report)

    def canonical_sha256(self) -> str:
        return _canonical_sha256(self.payload)

    @property
    def config_version(self) -> str:
        return str(self.payload.get("config_version") or "")

    @property
    def graph_lineage(self) -> str:
        return str(self.payload.get("graph_lineage") or "")

    def mind_map_cross_links(
        self,
        strict_edges: Iterable[Any],
    ) -> list[dict[str, str]]:
        represented = {
            (str(placement["primary_parent"]["id"]), str(node_id))
            for node_id, placement in (self.payload.get("mind_map", {}).get("nodes", {}) or {}).items()
            if isinstance(placement, dict)
            and isinstance(placement.get("primary_parent"), dict)
            and placement["primary_parent"].get("type") == "node"
        }
        return [
            {"source": source, "target": target}
            for source, target in sorted(_edge_set(strict_edges) - represented)
        ]


def _validate_config(
    payload: dict[str, Any],
    graph_snapshot: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    graph_nodes = graph_snapshot.get("nodes") if isinstance(graph_snapshot.get("nodes"), dict) else {}
    graph_modules = graph_snapshot.get("modules") if isinstance(graph_snapshot.get("modules"), dict) else {}
    node_ids = set(graph_nodes)
    module_ids = set(graph_modules)
    strict_edges = _edge_set(graph_snapshot.get("strict_prerequisites") or [])

    if payload.get("schema_version") != VIEW_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if payload.get("config_version") != VIEW_CONFIG_VERSION:
        errors.append("config_version_mismatch")
    if payload.get("graph_lineage") != graph_snapshot.get("graph_lineage"):
        errors.append("graph_lineage_mismatch")

    root = payload.get("root") if isinstance(payload.get("root"), dict) else {}
    module_order = root.get("module_order") if isinstance(root.get("module_order"), list) else []
    if len(module_order) != len(set(map(str, module_order))):
        errors.append("root_module_order_duplicate")
    if set(map(str, module_order)) != module_ids:
        errors.append("root_module_set_mismatch")

    mind_map = payload.get("mind_map") if isinstance(payload.get("mind_map"), dict) else {}
    mind_modules = mind_map.get("modules") if isinstance(mind_map.get("modules"), dict) else {}
    mind_nodes = mind_map.get("nodes") if isinstance(mind_map.get("nodes"), dict) else {}
    if set(mind_modules) != module_ids:
        errors.append("mind_map_module_set_mismatch")
    if set(mind_nodes) != node_ids:
        errors.append("mind_map_node_set_mismatch")
    module_orders: set[int] = set()
    for module_id, placement in mind_modules.items():
        if not isinstance(placement, dict):
            errors.append(f"mind_map_module_invalid:{module_id}")
            continue
        order = placement.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order in module_orders:
            errors.append(f"mind_map_module_order_invalid:{module_id}")
        else:
            module_orders.add(order)
        if not isinstance(placement.get("collapsed_by_default"), bool):
            errors.append(f"mind_map_module_collapse_invalid:{module_id}")

    sibling_orders: dict[tuple[str, str], set[int]] = {}
    represented_edges: set[tuple[str, str]] = set()
    for node_id, placement in mind_nodes.items():
        if not isinstance(placement, dict):
            errors.append(f"mind_map_node_invalid:{node_id}")
            continue
        parent = placement.get("primary_parent") if isinstance(placement.get("primary_parent"), dict) else {}
        parent_type = str(parent.get("type") or "")
        parent_id = str(parent.get("id") or "")
        if parent_type not in {"module", "node"}:
            errors.append(f"mind_map_parent_type_invalid:{node_id}")
        elif parent_type == "module":
            taxonomy = graph_nodes.get(node_id, {}).get("taxonomy") or {}
            if parent_id != str(taxonomy.get("module_id") or ""):
                errors.append(f"mind_map_module_parent_mismatch:{node_id}")
        else:
            if (parent_id, node_id) not in strict_edges:
                errors.append(f"mind_map_node_parent_not_prerequisite:{node_id}")
            represented_edges.add((parent_id, node_id))
        order = placement.get("order")
        sibling_key = (parent_type, parent_id)
        bucket = sibling_orders.setdefault(sibling_key, set())
        if not isinstance(order, int) or isinstance(order, bool) or order in bucket:
            errors.append(f"mind_map_sibling_order_invalid:{node_id}")
        else:
            bucket.add(order)
        if not isinstance(placement.get("collapsed_by_default"), bool):
            errors.append(f"mind_map_node_collapse_invalid:{node_id}")

    for start in mind_nodes:
        current = start
        seen: set[str] = set()
        while current in mind_nodes:
            if current in seen:
                errors.append(f"mind_map_parent_cycle:{start}")
                break
            seen.add(current)
            parent = mind_nodes[current].get("primary_parent") or {}
            if parent.get("type") == "module":
                break
            current = str(parent.get("id") or "")

    graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
    lanes = graph.get("lanes") if isinstance(graph.get("lanes"), list) else []
    lane_ids = [str(lane.get("id") or "") for lane in lanes if isinstance(lane, dict)]
    if len(lane_ids) != len(set(lane_ids)) or any(not lane_id for lane_id in lane_ids):
        errors.append("graph_lane_ids_invalid")
    lane_orders: set[int] = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            errors.append("graph_lane_invalid")
            continue
        order = lane.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order in lane_orders:
            errors.append(f"graph_lane_order_invalid:{lane.get('id')}")
        else:
            lane_orders.add(order)

    graph_nodes_config = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
    if set(graph_nodes_config) != node_ids:
        errors.append("graph_node_set_mismatch")
    bucket_orders: dict[tuple[str, int], set[int]] = {}
    for node_id, placement in graph_nodes_config.items():
        if not isinstance(placement, dict):
            errors.append(f"graph_node_invalid:{node_id}")
            continue
        rank = placement.get("rank")
        lane = str(placement.get("lane") or "")
        order = placement.get("order")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            errors.append(f"graph_rank_invalid:{node_id}")
        if lane not in lane_ids:
            errors.append(f"graph_lane_missing:{node_id}")
        bucket = bucket_orders.setdefault((lane, rank if isinstance(rank, int) else -1), set())
        if not isinstance(order, int) or isinstance(order, bool) or order in bucket:
            errors.append(f"graph_bucket_order_invalid:{node_id}")
        else:
            bucket.add(order)

    visibility = (
        graph.get("overview_edge_visibility")
        if isinstance(graph.get("overview_edge_visibility"), dict)
        else {}
    )
    edge_keys = {f"{source}->{target}" for source, target in strict_edges}
    if set(visibility) != edge_keys:
        errors.append("graph_visibility_edge_set_mismatch")
    for key, value in visibility.items():
        if not isinstance(value, bool):
            errors.append(f"graph_visibility_value_invalid:{key}")
    for source, target in strict_edges:
        source_rank = (graph_nodes_config.get(source) or {}).get("rank")
        target_rank = (graph_nodes_config.get(target) or {}).get("rank")
        if not isinstance(source_rank, int) or not isinstance(target_rank, int) or source_rank >= target_rank:
            errors.append(f"graph_edge_direction_invalid:{source}->{target}")

    cross_link_count = len(strict_edges - represented_edges)
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "node_count": len(node_ids),
        "module_count": len(module_ids),
        "strict_edge_count": len(strict_edges),
        "mind_map_cross_link_count": cross_link_count,
        "graph_visibility_count": len(visibility),
        "config_sha256": _canonical_sha256(payload),
    }
