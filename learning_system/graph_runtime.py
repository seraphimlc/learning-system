from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_GRAPH_RELATIVE_PATH = Path("data/knowledge_graphs/math/math_knowledge_graph_v2.json")


@dataclass(frozen=True)
class GraphVersion:
    version: str
    sha256: str

    @property
    def lineage(self) -> str:
        return f"{self.version}+sha256:{self.sha256}"


class GraphRuntimeService:
    """Deterministic graph lookup and lineage authority for v3 runtime rows."""

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        *,
        project_root: Path | str | None = None,
        graph_path: Path | str | None = None,
    ) -> None:
        self.conn = conn
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
        self.graph_path = Path(graph_path) if graph_path is not None else self.project_root / DEFAULT_GRAPH_RELATIVE_PATH

    def current_graph_version(self) -> str:
        return self.version_info().lineage

    def graph_snapshot(self) -> dict[str, Any]:
        payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        nodes = {
            str(node["id"]): node
            for node in payload.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }
        modules: dict[str, dict[str, Any]] = {}
        strict_prerequisites: list[dict[str, str]] = []
        unlock_edges: set[tuple[str, str]] = set()
        for node_id, node in nodes.items():
            taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
            module_id = str(taxonomy.get("module_id") or "")
            if module_id:
                module = modules.setdefault(module_id, {
                    "name": str(taxonomy.get("module_name") or module_id),
                    "nodes": [],
                })
                module["nodes"].append(node_id)
            for prerequisite in node.get("prerequisites") or []:
                strict_prerequisites.append({
                    "source": str(prerequisite),
                    "target": node_id,
                })
            for target in node.get("unlocks") or []:
                unlock_edges.add((node_id, str(target)))
        strict_edge_set = {
            (edge["source"], edge["target"])
            for edge in strict_prerequisites
        }
        unlock_only_candidates = [
            {"source": source, "target": target}
            for source, target in sorted(unlock_edges - strict_edge_set)
        ]
        for module in modules.values():
            module["nodes"] = sorted(module["nodes"])
        return {
            "graph_lineage": self.current_graph_version(),
            "modules": modules,
            "nodes": nodes,
            "strict_prerequisites": sorted(
                strict_prerequisites,
                key=lambda edge: (edge["source"], edge["target"]),
            ),
            "unlock_only_candidates": unlock_only_candidates,
        }

    def version_info(self) -> GraphVersion:
        raw = self.graph_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        version = str((metadata or {}).get("version") or "unknown-graph-version")
        return GraphVersion(version=version, sha256=hashlib.sha256(raw).hexdigest())

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        if not node_id:
            return None
        if self.conn is not None:
            row = self.conn.execute("select raw_json from graph_nodes where id = ?", (node_id,)).fetchone()
            if row:
                return json.loads(row["raw_json"])
        payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        for node in payload.get("nodes", []):
            if node.get("id") == node_id:
                return node
        return None

    def prerequisite_summary(self, node_id: str) -> dict[str, Any]:
        node = self.get_node(node_id)
        if not node:
            return {
                "node_id": node_id,
                "graph_version": self.current_graph_version(),
                "lineage_status": "missing_lineage",
                "prerequisite_node_ids": [],
            }
        return {
            "node_id": node_id,
            "graph_version": self.current_graph_version(),
            "lineage_status": "current",
            "prerequisite_node_ids": list(node.get("prerequisites") or []),
        }

    def rollback_candidates(self, node_id: str) -> list[str]:
        node = self.get_node(node_id)
        if not node:
            return []
        error_diagnosis = node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}
        return list(error_diagnosis.get("rollback_to") or node.get("prerequisites") or [])

    def validate_graph_binding(self, *, node_id: str, graph_version: str) -> dict[str, Any]:
        current = self.current_graph_version()
        if not node_id or self.get_node(node_id) is None:
            return {"usable": False, "reason": "missing_lineage", "current_graph_version": current}
        if graph_version != current:
            return {"usable": False, "reason": "stale", "current_graph_version": current}
        return {"usable": True, "reason": "current", "current_graph_version": current}
