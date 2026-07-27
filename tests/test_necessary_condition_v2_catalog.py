from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from learning_system import (
    answer_contract_batch_v2,
    answer_contract_generation_v2,
    assessment_policy,
    db,
    question_bank,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NecessaryConditionRoleCatalogTests(unittest.TestCase):
    def test_necessary_condition_is_a_role_not_a_top_level_kind(self) -> None:
        active_kinds = set(assessment_policy.ACTIVE_QUESTION_KINDS)

        self.assertEqual(20, len(active_kinds))
        self.assertIn("missing_condition", active_kinds)
        self.assertNotIn("necessary_condition", active_kinds)
        self.assertEqual(active_kinds, set(assessment_policy.V2_SLOT_CATALOGS))
        self.assertEqual(active_kinds, set(question_bank.PROBLEM_FAMILY_KIND_GROUPS))
        self.assertIn("necessary_condition", question_bank.V12_SLOT_ROLES)
        self.assertEqual(
            "necessary_condition",
            question_bank._legacy_candidate_slot_role({"kind": "missing_condition"}),
        )

    def test_practice_bank_stays_at_1120_items_and_twenty_kinds(self) -> None:
        graph = json.loads(
            (
                PROJECT_ROOT
                / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
            ).read_text(encoding="utf-8")
        )
        items = question_bank.build_practice_bank(
            graph,
            graph_version=str(graph.get("version") or ""),
        )
        kind_counts = Counter(item["kind"] for item in items)
        role_counts = Counter(
            question_bank._candidate_slot_role(item) for item in items
        )

        self.assertEqual(1120, len(items))
        self.assertEqual(20, len(kind_counts))
        self.assertEqual(set(assessment_policy.ACTIVE_QUESTION_KINDS), set(kind_counts))
        self.assertEqual(0, kind_counts["necessary_condition"])
        self.assertEqual(56, kind_counts["missing_condition"])
        self.assertEqual(56, role_counts["necessary_condition"])

    def test_generation_canary_covers_two_questions_per_twenty_kinds(self) -> None:
        questions = []
        for kind in assessment_policy.ACTIVE_QUESTION_KINDS:
            for ordinal in range(2):
                questions.append(({
                    "id": f"Q-{kind}-{ordinal}",
                    "item_version": "test-v2",
                    "node_id": f"NODE-{ordinal}",
                    "kind": kind,
                    "prompt": f"Prompt for {kind} {ordinal}",
                    "answer_format": "short response",
                    "expected_answer": f"Answer for {kind} {ordinal}",
                    "solution_steps": [f"Step for {kind} {ordinal}"],
                }, f"QRR-{kind}-{ordinal}"))
        with mock.patch.object(
            answer_contract_generation_v2.answer_contract_activation,
            "_active_ledger",
            return_value={"question_bank_version": "test-v2"},
        ), mock.patch.object(
            answer_contract_generation_v2.answer_contract_activation,
            "_authoritative_questions",
            return_value=questions,
        ):
            plan = answer_contract_generation_v2.plan_canary_questions(
                mock.Mock(),
                PROJECT_ROOT,
            )

        self.assertEqual(40, answer_contract_generation_v2.CANARY_SIZE)
        self.assertEqual(40, plan["canary_size"])
        self.assertEqual(40, len(plan["items"]))
        self.assertEqual(2, plan["questions_per_kind"])
        self.assertEqual(
            {kind: 2 for kind in assessment_policy.ACTIVE_QUESTION_KINDS},
            Counter(item["kind"] for item in plan["items"]),
        )

    def test_batch_run_persists_forty_items(self) -> None:
        self.assertEqual(40, answer_contract_batch_v2.CANARY_ITEM_COUNT)
        self.assertEqual(40, answer_contract_batch_v2.CANARY_DEFAULT_MAX_ITEMS)
        items = [
            {
                "ordinal": ordinal,
                "question_id": f"Q-{ordinal}",
                "item_version": "test-v2",
                "question_digest_sha256": f"{ordinal:064x}"[-64:],
                "node_id": f"NODE-{ordinal}",
                "kind": assessment_policy.ACTIVE_QUESTION_KINDS[
                    ordinal % len(assessment_policy.ACTIVE_QUESTION_KINDS)
                ],
                "effective_evidence_role": "direct",
                "review_record_id": f"QRR-{ordinal}",
            }
            for ordinal in range(answer_contract_batch_v2.CANARY_ITEM_COUNT)
        ]
        body = {
            "run_schema_version": answer_contract_batch_v2.RUN_SCHEMA_VERSION,
            "run_kind": answer_contract_batch_v2.RUN_KIND_CANARY,
            "selection_policy_version": "test-selection-v1",
            "selection_source_digest_sha256": "1" * 64,
            "effective_evidence_role_policy_version": (
                answer_contract_batch_v2.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
            ),
            "effective_evidence_role_policy_digest_sha256": (
                answer_contract_batch_v2.EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256
            ),
            "expected_item_count": answer_contract_batch_v2.CANARY_ITEM_COUNT,
            "ledger_id": "QBL-test-v2",
            "bank_version": "test-v2",
            "manifest_sha256": "2" * 64,
            "graph_version": "graph-v2",
            "generator_policy_digest_sha256": "3" * 64,
            "designer_prompt_digest_sha256": "4" * 64,
            "designer_schema_digest_sha256": "5" * 64,
            "designer_route_digest_sha256": "6" * 64,
            "reviewer_prompt_digest_sha256": "7" * 64,
            "reviewer_schema_digest_sha256": "8" * 64,
            "reviewer_route_digest_sha256": "9" * 64,
            "designer_route": {"timeout_seconds": 30.0},
            "reviewer_route": {"timeout_seconds": 30.0},
            "items": items,
        }
        plan = {
            **body,
            "plan_digest_sha256": answer_contract_batch_v2._digest(body),
        }
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            db.init_schema(conn)
            conn.execute("pragma foreign_keys = off")
            with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
                answer_contract_batch_v2,
                "require_batch_schema_authority",
            ):
                run, _claim = answer_contract_batch_v2.create_or_resume_v2_run(
                    conn,
                    PROJECT_ROOT,
                    plan=plan,
                    checkpoint_root=Path(tmpdir),
                )
            self.assertEqual(40, run["expected_item_count"])
            self.assertEqual(40, run["new_item_count"])
            self.assertEqual(
                40,
                conn.execute(
                    "select count(*) from answer_contract_generation_run_items"
                ).fetchone()[0],
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
