"""Integration: the planner rollback trust gate uses the trace-back engine.

The gate must keep trusting formal prerequisites and rollback_to targets, and
additionally trust strong unlocks-only edges (graph top-level
``strong_unlock_edges``) as legitimate rollback/prerequisite_probe targets,
while still rejecting arbitrary off-chain nodes. This is the review doc
section 7.3 consumer integration: rollback ordering is strength-aware.

Run: python3 -m unittest tests.test_planner_trace_back_integration -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"

from learning_system import db  # noqa: E402
from learning_system import planner  # noqa: E402


class PlannerTraceBackIntegrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))

    @contextmanager
    def _seeded_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "planner-trace.sqlite"
            with closing(db.connect(path)) as conn:
                db.init_schema(conn)
                with conn:
                    for node in self.graph["nodes"]:
                        summer = node.get("summer_execution") or {}
                        conn.execute(
                            """
                            insert into graph_nodes(
                              id, name, stage, domain, priority, summer_mode,
                              sequence_band, prerequisites_json, unlocks_json, raw_json
                            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(node["id"]),
                                str(node.get("name") or ""),
                                str(node.get("stage") or ""),
                                str(node.get("domain") or ""),
                                str(node.get("priority") or ""),
                                str(summer.get("mode") or "diagnose_only"),
                                int(summer.get("sequence_band") or 99),
                                db.json_dump(node.get("prerequisites") or []),
                                db.json_dump(node.get("unlocks") or []),
                                db.json_dump(node),
                            ),
                        )
            yield path

    def _gate(self, conn, *, task_type: str, task_node_id: str, signal_node_id: str) -> bool:
        return planner._is_trusted_signal_task_target(
            conn,
            task_type=task_type,
            task_node_id=task_node_id,
            signal_node_id=signal_node_id,
        )

    # DECIMAL-OPS -> RATIONAL-MIXED is a strong unlocks-only edge: not in
    # RATIONAL-MIXED.prerequisites nor rollback_to, but on the trace chain.
    def test_strong_unlock_edge_is_trusted_rollback_target(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertTrue(
                    self._gate(
                        conn, task_type="rollback",
                        task_node_id="M-PRE-DECIMAL-OPS",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )
                self.assertTrue(
                    self._gate(
                        conn, task_type="prerequisite_probe",
                        task_node_id="M-PRE-DECIMAL-OPS",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )

    def test_formal_prerequisite_still_trusted(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertTrue(
                    self._gate(
                        conn, task_type="rollback",
                        task_node_id="M-PRE-ORDER-OPS",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )

    def test_arbitrary_off_chain_node_rejected(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertFalse(
                    self._gate(
                        conn, task_type="rollback",
                        task_node_id="M-G7-ANGLE",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )

    def test_non_rollback_task_types_not_expanded(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertFalse(
                    self._gate(
                        conn, task_type="remediate",
                        task_node_id="M-PRE-DECIMAL-OPS",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )

    def test_same_node_always_trusted(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertTrue(
                    self._gate(
                        conn, task_type="rollback",
                        task_node_id="M-G7-RATIONAL-MIXED",
                        signal_node_id="M-G7-RATIONAL-MIXED",
                    )
                )

    def test_unknown_signal_node_rejected(self):
        with self._seeded_db() as path:
            with closing(db.connect(path)) as conn:
                self.assertFalse(
                    self._gate(
                        conn, task_type="rollback",
                        task_node_id="M-PRE-ORDER-OPS",
                        signal_node_id="M-G7-NOT-IN-DB",
                    )
                )


if __name__ == "__main__":
    unittest.main()
