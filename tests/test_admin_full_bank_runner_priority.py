from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts/admin_full_bank_production_runner.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("admin_full_bank_production_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load admin_full_bank_production_runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdminFullBankRunnerPriorityTests(unittest.TestCase):
    def test_run_ids_do_not_collide_within_the_same_second(self) -> None:
        first = self.runner._new_run_id()
        second = self.runner._new_run_id()

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("FULLBANK-RUN-"))

    def test_runner_report_writes_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            self.runner.os,
            "replace",
            wraps=self.runner.os.replace,
        ) as replace:
            root = Path(tmp)
            json_path = root / "run.json"
            markdown_path = root / "run.md"
            payload = {"status": "RUNNING", "rounds": []}

            self.runner._write_json(json_path, payload)
            self.runner._write_markdown(markdown_path, payload)
            json_exists = json_path.exists()
            markdown_exists = markdown_path.exists()

        self.assertEqual(2, replace.call_count)
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner_module()

    def test_zero_coverage_node_preempts_handwritten_priority_chain(self) -> None:
        full_bank = {
            "budget_gaps": [
                {
                    "node_id": "M-PRE-NUMBER-SENSE",
                    "current": 4,
                    "missing_to_min": 1,
                    "missing_to_target": 8,
                },
                {
                    "node_id": "M-G7-ANGLE",
                    "current": 0,
                    "missing_to_min": 10,
                    "missing_to_target": 14,
                },
            ],
            "family_gaps": [],
            "target_gaps": [],
        }

        self.assertEqual(
            ["M-G7-ANGLE", "M-PRE-NUMBER-SENSE"],
            self.runner._prioritized_gap_nodes(full_bank),
        )

    def test_deferred_zero_coverage_still_preempts_covered_nodes(self) -> None:
        full_bank = {
            "budget_gaps": [
                {
                    "node_id": "M-PRE-NUMBER-SENSE",
                    "current": 4,
                    "missing_to_min": 1,
                    "missing_to_target": 8,
                },
                {
                    "node_id": "M-BRIDGE-WORK-RATE",
                    "current": 0,
                    "missing_to_min": 5,
                    "missing_to_target": 8,
                },
            ],
            "family_gaps": [],
            "target_gaps": [],
        }

        self.assertEqual(
            ["M-BRIDGE-WORK-RATE", "M-PRE-NUMBER-SENSE"],
            self.runner._prioritized_gap_nodes(full_bank),
        )

    def test_family_gaps_are_prioritized_before_target_only_quantity_gaps(self) -> None:
        full_bank = {
            "budget_gaps": [],
            "family_gaps": [
                {
                    "node_id": "M-G7-COMPARE",
                    "family_id": "wrong_solution_repair_number",
                    "current": 1,
                    "required": 4,
                }
            ],
            "target_gaps": [
                {
                    "node_id": "M-G7-POS-NEG",
                    "current": 14,
                    "missing_to_target": 4,
                    "target": 18,
                }
            ],
        }

        self.assertEqual(
            ["M-G7-COMPARE", "M-G7-POS-NEG"],
            self.runner._prioritized_gap_nodes(full_bank),
        )

    def test_node_is_deduplicated_when_it_has_multiple_gap_types(self) -> None:
        full_bank = {
            "budget_gaps": [
                {
                    "node_id": "M-G7-NUMBER-LINE",
                    "current": 10,
                    "missing_to_min": 4,
                    "missing_to_target": 4,
                }
            ],
            "family_gaps": [
                {
                    "node_id": "M-G7-NUMBER-LINE",
                    "family_id": "solution_trace_repair",
                    "current": 0,
                    "required": 3,
                }
            ],
            "target_gaps": [
                {
                    "node_id": "M-G7-NUMBER-LINE",
                    "current": 10,
                    "missing_to_target": 4,
                    "target": 14,
                }
            ],
        }

        records = self.runner._gap_node_records(full_bank)

        self.assertEqual(["M-G7-NUMBER-LINE"], [record["node_id"] for record in records])
        self.assertEqual(1, records[0]["stage"])
        self.assertEqual(3, records[0]["family_missing"])
        self.assertEqual(["solution_trace_repair"], records[0]["family_gap_ids"])

    def test_family_gap_ids_are_ranked_by_missing_count(self) -> None:
        self.assertEqual(
            ["wrong_solution_repair_number", "solution_trace_repair", "known_unknown_relation_marking"],
            self.runner._prioritized_family_gap_ids(
                [
                    {
                        "family_id": "known_unknown_relation_marking",
                        "current": 1,
                        "required": 2,
                    },
                    {
                        "family_id": "wrong_solution_repair_number",
                        "current": 0,
                        "required": 3,
                    },
                    {
                        "family_id": "solution_trace_repair",
                        "current": 0,
                        "required": 2,
                    },
                ]
            ),
        )

    def test_generation_plan_selection_prefers_missing_families_and_skips_staged_slots(self) -> None:
        plans = [
            {
                "family_id": "number_line_position_distance",
                "slot_id": "slot-used",
                "question_requirement_id": "req-used",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 1}},
            },
            {
                "family_id": "solution_trace_repair",
                "slot_id": "slot-repair",
                "question_requirement_id": "req-repair",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 3}},
            },
            {
                "family_id": "number_line_position_distance",
                "slot_id": "slot-position",
                "question_requirement_id": "req-position",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 2}},
            },
            {
                "family_id": "wrong_solution_repair_number",
                "slot_id": "slot-wrong",
                "question_requirement_id": "req-wrong",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 4}},
            },
        ]

        selected = self.runner._select_unstaged_generation_plans(
            plans,
            used_requirement_ids={"req-used"},
            used_slot_ids={"slot-used"},
            family_gap_ids=["wrong_solution_repair_number", "solution_trace_repair"],
            family_gap_missing_by_id={
                "wrong_solution_repair_number": 1,
                "solution_trace_repair": 1,
            },
            limit=2,
        )

        self.assertEqual(["slot-wrong", "slot-repair"], [plan["slot_id"] for plan in selected])

    def test_generation_plan_selection_does_not_overfill_one_family_gap(self) -> None:
        plans = [
            {
                "family_id": "wrong_solution_repair_number",
                "slot_id": "slot-wrong-1",
                "question_requirement_id": "req-wrong-1",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 1}},
            },
            {
                "family_id": "wrong_solution_repair_number",
                "slot_id": "slot-wrong-2",
                "question_requirement_id": "req-wrong-2",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 2}},
            },
            {
                "family_id": "solution_trace_repair",
                "slot_id": "slot-repair",
                "question_requirement_id": "req-repair",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": 3}},
            },
        ]

        selected = self.runner._select_unstaged_generation_plans(
            plans,
            used_requirement_ids=set(),
            used_slot_ids=set(),
            family_gap_ids=["wrong_solution_repair_number", "solution_trace_repair"],
            family_gap_missing_by_id={
                "wrong_solution_repair_number": 1,
                "solution_trace_repair": 1,
            },
            limit=2,
        )

        self.assertEqual(["slot-wrong-1", "slot-repair"], [plan["slot_id"] for plan in selected])

    def test_generation_plan_selection_uses_one_sibling_per_family_per_round(self) -> None:
        plans = [
            {
                "family_id": "equation_word_modeling",
                "slot_id": f"slot-equation-{index}",
                "question_requirement_id": f"req-equation-{index}",
                "bounded_candidate_packet": {"question_requirement": {"slot_order": index}},
            }
            for index in range(1, 4)
        ]
        plans.extend(
            [
                {
                    "family_id": "solution_trace_repair",
                    "slot_id": "slot-repair",
                    "question_requirement_id": "req-repair",
                    "bounded_candidate_packet": {"question_requirement": {"slot_order": 4}},
                },
                {
                    "family_id": "known_unknown_relation_marking",
                    "slot_id": "slot-marking",
                    "question_requirement_id": "req-marking",
                    "bounded_candidate_packet": {"question_requirement": {"slot_order": 5}},
                },
            ]
        )

        selected = self.runner._select_unstaged_generation_plans(
            plans,
            used_requirement_ids=set(),
            used_slot_ids=set(),
            family_gap_ids=[
                "equation_word_modeling",
                "solution_trace_repair",
                "known_unknown_relation_marking",
            ],
            family_gap_missing_by_id={
                "equation_word_modeling": 3,
                "solution_trace_repair": 2,
                "known_unknown_relation_marking": 2,
            },
            limit=3,
        )

        self.assertEqual(
            ["slot-equation-1", "slot-repair", "slot-marking"],
            [plan["slot_id"] for plan in selected],
        )

    def test_make_plans_propagates_one_staged_bank_identity(self) -> None:
        staged_bank = Path("data/custom/selected-staged-bank.json")
        requirement_report = {
            "schema_version": "2026-07-23.codex-admin.question-requirement-plan.v1",
            "status": "REQUIREMENT_PLAN_READY",
            "production_json_path": "requirements.json",
        }
        plan_batch_report = {
            "schema_version": "2026-07-23.codex-admin.production-plan-batch.v1",
            "status": "PLAN_BATCH_READY",
            "generation_plans": [],
            "generation_plan_paths": [],
            "production_json_path": "plan-batch.json",
        }
        with patch.object(
            self.runner,
            "build_expert_design_ideas",
            return_value={"status": "READY"},
        ), patch.object(
            self.runner,
            "write_expert_design_ideas",
            return_value={"status": "READY", "design_json_path": "design.json"},
        ), patch.object(
            self.runner,
            "build_question_requirement_plan",
            return_value=dict(requirement_report),
        ) as build_requirement, patch.object(
            self.runner,
            "write_production_report",
            side_effect=[dict(requirement_report), dict(plan_batch_report)],
        ), patch.object(
            self.runner,
            "_staged_requirement_and_slot_ids",
            return_value=(set(), set()),
        ) as staged_ids, patch.object(
            self.runner,
            "build_generation_plan_batch",
            return_value=dict(plan_batch_report),
        ) as build_batch:
            self.runner._make_plans_for_node(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                version="v18",
                subject="math",
                slots_per_node=1,
                max_attempts_per_slot=2,
                staged_bank_path=staged_bank,
                apply=True,
            )

        self.assertEqual(staged_bank, build_requirement.call_args.kwargs["bank_path"])
        self.assertEqual(staged_bank, build_batch.call_args.kwargs["bank_path"])
        self.assertEqual(staged_bank, staged_ids.call_args.kwargs["staged_bank_path"])

    def test_no_require_target_ignores_target_only_gaps(self) -> None:
        full_bank = {
            "require_target": False,
            "budget_gaps": [],
            "family_gaps": [],
            "target_gaps": [
                {
                    "node_id": "M-G7-POS-NEG",
                    "current": 10,
                    "target": 14,
                    "missing_to_target": 4,
                }
            ],
        }

        self.assertEqual([], self.runner._prioritized_gap_nodes(full_bank))

    def _runner_args(self, root: str, **overrides: object) -> Namespace:
        values: dict[str, object] = {
            "root": root,
            "subject": "math",
            "version": "v18",
            "staged_bank": "bank.json",
            "require_target": True,
            "apply": False,
            "max_runtime_seconds": 1.0,
            "batch_runtime_seconds": 1.0,
            "max_rounds": 0,
            "nodes_per_round": 1,
            "slots_per_node": 1,
            "max_slots_per_round": 1,
            "workers": 1,
            "max_attempts_per_slot": 1,
            "stop_on_batch_problem": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_runner_returns_nonzero_when_final_acceptance_is_not_strict_pass(self) -> None:
        unsafe_gate = {
            "status": "NEEDS_FIX",
            "require_target": True,
            "budget_gaps": [],
            "target_gaps": [],
            "family_gaps": [],
            "item_count": 1,
            "raw_item_count": 1,
            "qualified_item_count": 0,
            "disqualified_item_count": 1,
            "covered_node_count": 0,
            "blueprint_node_count": 1,
            "finding_counts": {"P1": 1},
            "full_bank_json_path": "not-written.json",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            self.runner,
            "build_full_bank_acceptance",
            return_value=unsafe_gate,
        ), patch.object(
            self.runner,
            "write_full_bank_acceptance",
            side_effect=lambda report, **_kwargs: dict(report),
        ), contextlib.redirect_stdout(io.StringIO()):
            exit_code = self.runner.run(self._runner_args(tmp))
            record_path = next((Path(tmp) / "data/admin/full_bank_runs").glob("*.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("STOPPED_ACCEPTANCE_NOT_PASS", record["status"])
        self.assertEqual("NEEDS_FIX", record["final_full_bank_status"])

    def test_runner_records_round_start_before_work_and_pass_overrides_round_limit(self) -> None:
        gap_gate = {
            "status": "NEEDS_FIX",
            "require_target": True,
            "budget_gaps": [
                {
                    "node_id": "M-G7-POS-NEG",
                    "current": 0,
                    "missing_to_min": 1,
                    "missing_to_target": 1,
                }
            ],
            "target_gaps": [],
            "family_gaps": [],
            "item_count": 0,
            "qualified_item_count": 0,
            "covered_node_count": 0,
            "blueprint_node_count": 1,
            "finding_counts": {"P1": 1},
            "full_bank_json_path": "gap.json",
        }
        pass_gate = {
            **gap_gate,
            "status": "PASS",
            "budget_gaps": [],
            "item_count": 1,
            "raw_item_count": 1,
            "qualified_item_count": 1,
            "disqualified_item_count": 0,
            "covered_node_count": 1,
            "finding_counts": {},
            "full_bank_json_path": "pass.json",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            self.runner,
            "_utc_now",
            side_effect=["run-start", "round-start", "run-finished"],
        ), patch.object(
            self.runner,
            "build_full_bank_acceptance",
            side_effect=[gap_gate, gap_gate, pass_gate],
        ) as build_acceptance, patch.object(
            self.runner,
            "write_full_bank_acceptance",
            side_effect=lambda report, **_kwargs: dict(report),
        ), patch.object(
            self.runner,
            "_make_plans_for_node",
            return_value={"node_id": "M-G7-POS-NEG", "generation_plan_paths": ["plan.json"]},
        ) as make_plans, patch.object(
            self.runner,
            "run_batch_production_workflow",
            return_value={"status": "BATCH_COMPLETED", "staged_slot_count": 1, "failed_slot_count": 0},
        ) as run_batch, patch.object(
            self.runner,
            "write_batch_production_workflow_report",
            side_effect=lambda report, **_kwargs: dict(report),
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = self.runner.run(self._runner_args(tmp, max_rounds=1))
            record_path = next((Path(tmp) / "data/admin/full_bank_runs").glob("*.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("COMPLETED_FULL_BANK_PASS", record["status"])
        self.assertEqual("round-start", record["rounds"][0]["started_at"])
        self.assertTrue(
            all(call.kwargs["bank_path"] == Path("bank.json") for call in build_acceptance.call_args_list)
        )
        self.assertEqual(Path("bank.json"), make_plans.call_args.kwargs["staged_bank_path"])
        self.assertEqual(Path("bank.json"), run_batch.call_args.kwargs["staged_bank_path"])

    def test_runner_does_not_start_planning_or_batch_after_total_deadline(self) -> None:
        gap_gate = {
            "status": "NEEDS_FIX",
            "require_target": True,
            "budget_gaps": [
                {
                    "node_id": "M-G7-POS-NEG",
                    "current": 0,
                    "missing_to_min": 1,
                    "missing_to_target": 1,
                }
            ],
            "target_gaps": [],
            "family_gaps": [],
            "item_count": 0,
            "raw_item_count": 0,
            "qualified_item_count": 0,
            "disqualified_item_count": 0,
            "covered_node_count": 0,
            "blueprint_node_count": 1,
            "finding_counts": {"P1": 1},
            "full_bank_json_path": "gap.json",
        }
        clock = iter([0.0, 0.1, 0.1, 0.1, 1.1, 1.1, 1.1, 1.1])
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            self.runner.time,
            "monotonic",
            side_effect=lambda: next(clock, 1.1),
        ), patch.object(
            self.runner,
            "build_full_bank_acceptance",
            return_value=gap_gate,
        ), patch.object(
            self.runner,
            "write_full_bank_acceptance",
            side_effect=lambda report, **_kwargs: dict(report),
        ), patch.object(
            self.runner,
            "_make_plans_for_node",
            side_effect=AssertionError("planning must not start after the total deadline"),
        ) as make_plans, patch.object(
            self.runner,
            "run_batch_production_workflow",
            side_effect=AssertionError("batch must not start after the total deadline"),
        ) as run_batch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = self.runner.run(self._runner_args(tmp, max_runtime_seconds=1.0))
            record_path = next((Path(tmp) / "data/admin/full_bank_runs").glob("*.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual(0, make_plans.call_count)
        self.assertEqual(0, run_batch.call_count)
        self.assertEqual("COMPLETED_TIME_BUDGET", record["status"])
        self.assertEqual("runner_total_deadline_exhausted_before_node_planning", record["blocked_reason"])


if __name__ == "__main__":
    unittest.main()
