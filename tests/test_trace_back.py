"""Trace-back engine contract tests.

The engine turns the project's core pedagogical rule into a deterministic,
testable service: when a node's problem is wrong, walk the prerequisite chain
backward instead of drilling the same question type (AGENTS.md).

Contract under test (review doc docs/qa/knowledge_graph_prereq_strength_review.md
section 6 + default rule "unmarked = soft"):

- wrong_node must exist in the graph
- path is ordered: depth first (closest to the wrong node), then edge strength
  (strong before soft), then state severity (C/D before B before unknown), then
  node id (deterministic tie-break)
- strong_unlock_edges participate as depth-0 strong edges (semantic strong deps)
- mastered nodes (state A) are excluded from the active path
- invalid state values / unknown state keys are warnings, not errors
- earliest_breakpoint = deepest C/D node along the chain ("补最早断点")
- graphs with cycles must not hang

Run: python3 -m unittest tests.test_trace_back -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"

from learning_system.trace_back import (  # noqa: E402
    ordered_prerequisite_candidates,
    trace_back,
)

# Synthetic fixture: R1(root) -> N1 -> N2 -> TARGET, plus a cycle R1<->N1.
# Edges are unmarked (default soft) except N2->TARGET which is strong.
SYNTHETIC_GRAPH = {
    "nodes": [
        {"id": "R1", "name": "根节点", "prerequisites": []},
        {"id": "N1", "name": "中继1", "prerequisites": ["R1"]},
        {"id": "N2", "name": "中继2", "prerequisites": ["N1"]},
        {"id": "TARGET", "name": "错题节点", "prerequisites": ["N2"]},
    ],
    "prerequisite_edges": [
        {"from": "R1", "to": "N1", "type": "prerequisite"},
        {"from": "N1", "to": "R1", "type": "prerequisite"},  # cycle
        {"from": "N1", "to": "N2", "type": "prerequisite"},
        {
            "from": "N2",
            "to": "TARGET",
            "type": "prerequisite",
            "prereq_strength": "strong",
            "strength_rationale": "直接卡住",
        },
    ],
    "strong_unlock_edges": [],
}


class TraceBackEngineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))

    # ---- validation ----
    def test_wrong_node_must_exist(self):
        result = trace_back(self.graph, "M-G7-NOT-EXIST")
        self.assertFalse(result["valid"])
        self.assertTrue(any("wrong_node" in error for error in result["errors"]))

    def test_invalid_state_values_are_warnings(self):
        result = trace_back(self.graph, "M-G7-EQ-WORD", states={"M-PRE-INTEGER-OPS": "Z"})
        self.assertTrue(result["valid"])
        self.assertTrue(any("state" in warning for warning in result["warnings"]))

    def test_unknown_state_keys_are_warnings(self):
        result = trace_back(self.graph, "M-G7-EQ-WORD", states={"M-G7-GHOST": "C"})
        self.assertTrue(result["valid"])
        self.assertTrue(any("state" in warning for warning in result["warnings"]))

    # ---- ordering: strong direct before soft direct (EQ-WORD) ----
    def test_direct_strong_edges_lead_the_path(self):
        result = trace_back(self.graph, "M-G7-EQ-WORD")
        path_ids = [entry["node_id"] for entry in result["path"]]
        strong_direct = {
            "M-BRIDGE-WORD-PROBLEM-READING",
            "M-BRIDGE-SUM-DIFF-MULTIPLE",
            "M-BRIDGE-MOTION-BASIC",
            "M-PRE-FRACTION-MEANING",  # strong unlock into EQ-WORD
            "M-BRIDGE-SOLUTION-HABIT",  # strong unlock into EQ-WORD
        }
        soft_direct = {"M-BRIDGE-PERCENT-MODEL", "M-G7-EQ-SOLVE"}
        for strong in strong_direct:
            self.assertIn(strong, path_ids, f"strong direct {strong} missing")
        for soft in soft_direct:
            self.assertIn(soft, path_ids, f"soft direct {soft} missing")
        last_strong = max(path_ids.index(n) for n in strong_direct)
        for soft in soft_direct:
            self.assertGreater(
                path_ids.index(soft), last_strong,
                f"soft direct {soft} must come after all strong direct edges",
            )

    # ---- strong_unlock_edges are nearest-level strong edges ----
    def test_strong_unlock_edges_participate_at_depth_one(self):
        result = trace_back(self.graph, "M-G7-RATIONAL-MIXED")
        entry = next(
            (e for e in result["path"] if e["node_id"] == "M-PRE-DECIMAL-OPS"), None
        )
        self.assertIsNotNone(entry, "DECIMAL-OPS (strong unlock) missing from path")
        self.assertEqual(1, entry["depth"])
        self.assertEqual("unlock_strong", entry["relation"])
        self.assertEqual("strong", entry["edge_strength"])

    # ---- mastered nodes excluded ----
    def test_mastered_nodes_excluded_from_active_path(self):
        states = {"M-BRIDGE-WORD-PROBLEM-READING": "A"}
        result = trace_back(self.graph, "M-G7-EQ-WORD", states=states)
        path_ids = [entry["node_id"] for entry in result["path"]]
        self.assertNotIn("M-BRIDGE-WORD-PROBLEM-READING", path_ids)
        self.assertIn("M-BRIDGE-WORD-PROBLEM-READING", result["excluded_mastered"])

    # ---- state severity orders within same depth/strength ----
    def test_state_severity_orders_within_same_strength(self):
        states = {
            "M-BRIDGE-WORD-PROBLEM-READING": "C",
            "M-BRIDGE-SUM-DIFF-MULTIPLE": "unknown",
        }
        result = trace_back(self.graph, "M-G7-EQ-WORD", states=states)
        path_ids = [entry["node_id"] for entry in result["path"]]
        self.assertLess(
            path_ids.index("M-BRIDGE-WORD-PROBLEM-READING"),
            path_ids.index("M-BRIDGE-SUM-DIFF-MULTIPLE"),
            "state C must be checked before unknown within same strength group",
        )

    # ---- global invariant: path is depth-sorted ----
    def test_path_is_sorted_by_depth(self):
        result = trace_back(self.graph, "M-G7-EQ-WORD")
        depths = [entry["depth"] for entry in result["path"]]
        self.assertEqual(depths, sorted(depths), "path must be non-decreasing in depth")

    # ---- earliest breakpoint (synthetic fixture) ----
    def test_earliest_breakpoint_is_deepest_broken_node(self):
        states = {"N1": "D", "N2": "C"}
        result = trace_back(SYNTHETIC_GRAPH, "TARGET", states=states)
        self.assertTrue(result["valid"], result)
        self.assertEqual("N1", result["earliest_breakpoint"],
                         "deepest C/D node must be the earliest breakpoint")

    def test_no_breakpoint_when_nothing_broken(self):
        result = trace_back(SYNTHETIC_GRAPH, "TARGET", states={"N1": "B"})
        self.assertIsNone(result["earliest_breakpoint"])

    # ---- cycle safety ----
    def test_cycle_in_fixture_does_not_hang(self):
        result = trace_back(SYNTHETIC_GRAPH, "TARGET")
        self.assertTrue(result["valid"])
        path_ids = [entry["node_id"] for entry in result["path"]]
        self.assertIn("N2", path_ids)
        self.assertIn("N1", path_ids)
        self.assertIn("R1", path_ids)

    # ---- root node with no prerequisites (real graph root) ----
    def test_root_node_with_no_prerequisites(self):
        result = trace_back(self.graph, "M-PRE-NUMBER-SENSE")
        self.assertTrue(result["valid"])
        self.assertEqual([], result["path"])
        self.assertTrue(result["recommendation"])

    # ---- result shape ----
    def test_result_shape(self):
        result = trace_back(self.graph, "M-G7-EQ-WORD")
        for key in ("valid", "errors", "warnings", "wrong_node", "path",
                    "excluded_mastered", "earliest_breakpoint", "recommendation"):
            self.assertIn(key, result)
        for entry in result["path"]:
            for key in ("node_id", "name", "relation", "edge_strength", "depth", "state"):
                self.assertIn(key, entry)


class OrderedPrerequisiteCandidatesTestCase(unittest.TestCase):
    """Consumer-facing API used by planner/agents for rollback ordering."""

    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))

    def test_returns_ordered_chain_excluding_wrong_node(self):
        candidates = ordered_prerequisite_candidates(self.graph, "M-G7-EQ-WORD")
        self.assertNotIn("M-G7-EQ-WORD", candidates)
        strong_direct = {
            "M-BRIDGE-WORD-PROBLEM-READING",
            "M-BRIDGE-SUM-DIFF-MULTIPLE",
            "M-BRIDGE-MOTION-BASIC",
        }
        soft_direct = {"M-BRIDGE-PERCENT-MODEL", "M-G7-EQ-SOLVE"}
        last_strong = max(candidates.index(n) for n in strong_direct)
        for soft in soft_direct:
            self.assertGreater(
                candidates.index(soft), last_strong,
                f"soft direct {soft} must come after all strong direct edges",
            )

    def test_includes_strong_unlock_edges(self):
        candidates = ordered_prerequisite_candidates(self.graph, "M-G7-RATIONAL-MIXED")
        self.assertIn("M-PRE-DECIMAL-OPS", candidates)

    def test_includes_mastered_nodes(self):
        candidates = ordered_prerequisite_candidates(
            self.graph, "M-G7-EQ-WORD", states={"M-BRIDGE-WORD-PROBLEM-READING": "A"}
        )
        self.assertIn("M-BRIDGE-WORD-PROBLEM-READING", candidates)

    def test_unknown_node_returns_empty(self):
        self.assertEqual([], ordered_prerequisite_candidates(self.graph, "M-G7-NOT-EXIST"))

    def test_root_node_returns_empty(self):
        self.assertEqual([], ordered_prerequisite_candidates(self.graph, "M-PRE-NUMBER-SENSE"))


if __name__ == "__main__":
    unittest.main()
