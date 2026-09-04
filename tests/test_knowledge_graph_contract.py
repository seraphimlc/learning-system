"""Knowledge graph v2 contract tests (oracle style).

Guards the module<->node mapping contract (proposal R1-R5) and the
prereq_strength phase-1 backfill contract (review doc section 6, rule R7):

- R1: module codes match ^[A-Z]_[A-Z]+(_[A-Z]+)*$
- R2/R3: every node has a module_id that hits a top-level modules key (closed)
- R4: no empty modules (9/9 non-empty with the known distribution)
- R5: node taxonomy.module_name == modules[module_id].name (zero drift)
- R7a: every prerequisite edge leaving the 24 phase-1 reviewed nodes is marked
- R7b: prereq_strength is strong|soft; strong edges carry a rationale
- R7c: UNIT-CONVERSION->SEGMENT-MEASURE is the documented soft-node exception
- R7d: strong_unlock_edges entries are "from->to", valid ids, unlocks-only
- R7e: validate_graph() reports valid on the real graph
- R7f: validate_graph() actually catches broken states (mutated fixtures)

Run: python3 -m unittest tests.test_knowledge_graph_contract -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"

from learning_system.graph_contract import (  # noqa: E402
    MODULE_CODE_RE,
    PHASE1_STRONG_NODES,
    PHASE1_SOFT_NODES,
    SOFT_NODE_EXCEPTION_EDGE,
    validate_graph,
)

PHASE1_NODES = PHASE1_STRONG_NODES | PHASE1_SOFT_NODES
EXPECTED_MODULE_COUNTS = {
    "A_FOUNDATION": 4,
    "B_FRACTION_RATIO": 4,
    "C_ALGEBRA_BRIDGE": 4,
    "D_WORD_MODELS": 8,
    "E_RATIONAL_NUMBERS": 11,
    "F_EXPRESSIONS": 8,
    "G_LINEAR_EQUATION": 6,
    "H_GEOMETRY_INTRO": 10,
    "Z_LEARNING_PROCESS": 1,
}
# Review doc 6.2 lists 5 entries but NUMBER-SENSE->POS-NEG is a formal
# prerequisite edge (present in prerequisite_edges), so only the 4 truly
# unlocks-only edges belong here (see test_prereq_strength_unlock_only_edges).
EXPECTED_STRONG_UNLOCK_EDGES = {
    "M-PRE-FRACTION-MEANING→M-G7-EQ-WORD",
    "M-PRE-DECIMAL-OPS→M-G7-RATIONAL-MIXED",
    "M-BRIDGE-SOLUTION-HABIT→M-G7-EQ-SOLVE",
    "M-BRIDGE-SOLUTION-HABIT→M-G7-EQ-WORD",
}


class KnowledgeGraphContractTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        cls.nodes = {str(node["id"]): node for node in cls.graph["nodes"]}
        cls.node_ids = set(cls.nodes)
        cls.modules = cls.graph["modules"]
        cls.module_ids = set(cls.modules)
        cls.prereq_edges = cls.graph.get("prerequisite_edges", [])
        cls.edge_pairs = {(e["from"], e["to"]) for e in cls.prereq_edges}
        cls.unlock_pairs = {
            (node_id, str(unlocked))
            for node_id, node in cls.nodes.items()
            for unlocked in node.get("unlocks", [])
        }
        cls.strong_unlock_edges = set(cls.graph.get("strong_unlock_edges", []))

    def _edge(self, source: str, target: str) -> dict:
        for edge in self.prereq_edges:
            if edge["from"] == source and edge["to"] == target:
                return edge
        self.fail(f"edge {source}->{target} not found in prerequisite_edges")

    # ---- R1: module code naming ----
    def test_module_codes_match_naming_contract(self):
        for code in self.module_ids:
            self.assertRegex(code, MODULE_CODE_RE, f"module code {code!r}")

    # ---- R2/R3: closed module_id mapping ----
    def test_every_node_has_valid_module_id(self):
        missing = [
            node_id
            for node_id, node in self.nodes.items()
            if not isinstance(node.get("taxonomy", {}).get("module_id"), str)
        ]
        self.assertEqual([], missing, "nodes without taxonomy.module_id")
        dangling = [
            node_id
            for node_id, node in self.nodes.items()
            if node["taxonomy"]["module_id"] not in self.module_ids
        ]
        self.assertEqual([], dangling, "nodes referencing unknown module ids")

    def test_module_references_are_closed(self):
        referenced = {
            str(node["taxonomy"]["module_id"]) for node in self.nodes.values()
        }
        self.assertEqual(self.module_ids, referenced, "orphan modules (no node references)")

    # ---- R4: no empty modules ----
    def test_module_node_counts_match_known_distribution(self):
        counts = {}
        for node in self.nodes.values():
            module_id = str(node["taxonomy"]["module_id"])
            counts[module_id] = counts.get(module_id, 0) + 1
        self.assertEqual(EXPECTED_MODULE_COUNTS, counts)

    # ---- R5: module_name zero drift ----
    def test_module_name_matches_top_level_modules(self):
        drifted = [
            (node_id, node["taxonomy"]["module_name"])
            for node_id, node in self.nodes.items()
            if node["taxonomy"]["module_name"]
            != self.modules[node["taxonomy"]["module_id"]]["name"]
        ]
        self.assertEqual([], drifted, "module_name drift vs top-level modules")

    # ---- R7a: phase-1 out-edges are all marked ----
    def test_phase1_node_edges_all_marked(self):
        unmarked = [
            (edge["from"], edge["to"])
            for edge in self.prereq_edges
            if edge["from"] in PHASE1_NODES and "prereq_strength" not in edge
        ]
        self.assertEqual([], unmarked, "phase-1 edges missing prereq_strength")

    # ---- R7b: enum + rationale on strong ----
    def test_prereq_strength_enum_and_rationale(self):
        for edge in self.prereq_edges:
            if "prereq_strength" not in edge:
                continue
            strength = edge["prereq_strength"]
            self.assertIn(strength, {"strong", "soft"}, edge)
            if strength == "strong":
                self.assertTrue(
                    str(edge.get("strength_rationale", "")).strip(),
                    f"strong edge {edge['from']}->{edge['to']} missing rationale",
                )

    # ---- R7c: soft-node exception edge ----
    def test_unit_conversion_segment_measure_is_strong_exception(self):
        source, target = SOFT_NODE_EXCEPTION_EDGE.split("→")
        self.assertIn(source, PHASE1_SOFT_NODES)
        edge = self._edge(source, target)
        self.assertEqual("strong", edge.get("prereq_strength"))
        self.assertTrue(str(edge.get("strength_rationale", "")).strip())

    # ---- R7d: strong_unlock_edges are unlocks-only with valid ids ----
    def test_prereq_strength_unlock_only_edges(self):
        self.assertEqual(EXPECTED_STRONG_UNLOCK_EDGES, self.strong_unlock_edges)
        for entry in self.strong_unlock_edges:
            source, target = entry.split("→")
            self.assertIn(source, self.node_ids, entry)
            self.assertIn(target, self.node_ids, entry)
            self.assertIn((source, target), self.unlock_pairs, f"{entry} not an unlock")
            self.assertNotIn(
                (source, target), self.edge_pairs, f"{entry} is a formal edge, not unlocks-only"
            )

    # ---- R7e: validator reports valid on the real graph ----
    def test_validator_reports_valid_on_real_graph(self):
        report = validate_graph(self.graph)
        self.assertTrue(report["valid"], report)
        self.assertEqual([], report["errors"], report)
        self.assertEqual(56, report["node_count"], report)
        self.assertEqual(9, report["module_count"], report)

    def test_every_node_has_versioned_production_contract(self):
        required = {"contract_version", "review_status", "scope", "evidence", "question_hints", "error_model", "source_fields"}
        missing = []
        for node_id, node in self.nodes.items():
            contract = node.get("production_contract") or {}
            if contract.get("contract_version") != "node-production-contract.v1" or not required <= set(contract):
                missing.append(node_id)
        self.assertEqual([], missing, f"nodes missing production_contract: {missing}")

    def test_validator_rejects_missing_production_contract(self):
        import copy

        broken = copy.deepcopy(self.graph)
        broken["nodes"][0].pop("production_contract", None)
        report = validate_graph(broken)
        self.assertFalse(report["valid"], report)
        self.assertTrue(any("production_contract" in error for error in report["errors"]), report)

    # ---- R7f: validator catches broken states ----
    def test_validator_rejects_bad_strength_enum(self):
        import copy

        broken = copy.deepcopy(self.graph)
        broken["prerequisite_edges"][0]["prereq_strength"] = "medium"
        report = validate_graph(broken)
        self.assertFalse(report["valid"], report)
        self.assertTrue(any("prereq_strength" in error for error in report["errors"]), report)

    def test_validator_rejects_strong_edge_without_rationale(self):
        import copy

        broken = copy.deepcopy(self.graph)
        strong_edges = [
            e for e in broken["prerequisite_edges"]
            if e.get("prereq_strength") == "strong"
        ]
        if not strong_edges:
            self.skipTest("no strong edges in fixture")
        del strong_edges[0]["strength_rationale"]
        report = validate_graph(broken)
        self.assertFalse(report["valid"], report)
        self.assertTrue(any("rationale" in error for error in report["errors"]), report)

    def test_validator_rejects_dangling_module_id(self):
        import copy

        broken = copy.deepcopy(self.graph)
        broken["nodes"][0]["taxonomy"]["module_id"] = "X_NOT_A_MODULE"
        report = validate_graph(broken)
        self.assertFalse(report["valid"], report)


if __name__ == "__main__":
    unittest.main()
