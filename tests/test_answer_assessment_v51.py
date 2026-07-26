import copy
import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from learning_system import db, test_support


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRE_V51_BACKUP_PATH = PROJECT_ROOT / (
    "data/backups/local_learning_system.pre-v5.1."
    "20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite"
)

ACTIVE_QUESTION_KINDS = (
    "boundary_case",
    "check_strategy",
    "communication",
    "error_spotting",
    "essence_check",
    "estimation_modeling",
    "explanation_only",
    "misconception_probe",
    "missing_condition",
    "model_selection",
    "prerequisite_probe",
    "representation",
    "reverse_reasoning",
    "self_correction",
    "standard_example",
    "stretch_transfer",
    "symbol_unit_audit",
    "transfer_retest",
    "two_method_compare",
    "variant",
)

ALLOWED_TEST_DIMENSIONS = {
    "concept",
    "model_relation",
    "procedure",
    "calculation",
    "representation",
    "expression_notation",
    "final_answer",
    "check",
    "transfer",
}

KIND_SCORING_TARGET_SPECS = {
    "boundary_case": (
        ("boundary_condition", "Identify the boundary condition", "concept", True),
        ("boundary_result", "Obtain the result at the boundary", "calculation", True),
        ("boundary_justification", "Explain why the boundary changes the rule", "check", True),
    ),
    "check_strategy": (
        ("computed_result", "Obtain the computed result", "calculation", True),
        ("independent_check", "Carry out an independent reverse or estimate check", "check", True),
        ("check_conclusion", "State whether the result passes the check", "final_answer", True),
    ),
    "communication": (
        ("mathematical_relation", "State the mathematical relation", "model_relation", True),
        ("worked_result", "Obtain the required result", "calculation", True),
        ("mathematical_conclusion", "Communicate the mathematical conclusion unambiguously", "final_answer", True),
    ),
    "error_spotting": (
        ("locate_error", "Locate the first mathematical error", "concept", True),
        ("correct_process", "Replace it with a correct process", "procedure", True),
        ("verified_correction", "Verify the corrected result", "check", True),
    ),
    "essence_check": (
        ("core_rule", "State the core rule being tested", "concept", True),
        ("rule_application", "Apply the core rule to the given data", "procedure", True),
        ("result", "Obtain the resulting conclusion", "final_answer", True),
    ),
    "estimation_modeling": (
        ("reasonable_range", "Establish a reasonable result range", "concept", True),
        ("model_relation", "Build the relation used for the estimate", "model_relation", True),
        ("estimated_result", "Obtain and interpret the estimate", "calculation", True),
    ),
    "explanation_only": (
        ("claim", "State the mathematical claim being explained", "concept", True),
        ("reason", "Give a valid mathematical reason", "procedure", True),
    ),
    "misconception_probe": (
        ("misconception", "Identify the incorrect mathematical belief", "concept", True),
        ("counter_reason", "Explain why that belief fails", "procedure", True),
        ("correct_rule", "State the correct replacement rule", "concept", True),
    ),
    "missing_condition": (
        ("missing_condition", "Identify the missing condition", "concept", True),
        ("condition_effect", "Explain how the condition changes the solution", "model_relation", True),
        ("resolved_result", "Solve after restoring the condition", "calculation", True),
    ),
    "model_selection": (
        ("candidate_models", "Distinguish the candidate mathematical models", "concept", True),
        ("selected_model", "Select the model that matches the quantities", "model_relation", True),
        ("model_result", "Use the selected model to obtain the result", "calculation", True),
    ),
    "prerequisite_probe": (
        ("prerequisite_rule", "Recall the prerequisite rule", "concept", True),
        ("prerequisite_application", "Apply the prerequisite rule correctly", "procedure", True),
    ),
    "representation": (
        ("source_relation", "Identify the relation in the source form", "model_relation", True),
        ("target_representation", "Convert it to the requested representation", "representation", True),
        ("represented_result", "Read the correct result from that representation", "final_answer", True),
    ),
    "reverse_reasoning": (
        ("target_condition", "Start from the required target condition", "concept", True),
        ("reverse_relation", "Derive the reverse relation", "model_relation", True),
        ("verified_source", "Verify that the source satisfies the target", "check", True),
    ),
    "self_correction": (
        ("own_error", "Identify the error in the proposed work", "concept", True),
        ("corrected_work", "Produce corrected mathematical work", "procedure", True),
        ("correction_check", "Check the corrected conclusion", "check", True),
    ),
    "standard_example": (
        ("rightward_relation", "Recognize that moving three units right means adding 3", "model_relation", True),
        ("c_value", "Obtain C=0.5", "calculation", True),
        ("ascending_order", "Order the points as A<C<B", "representation", True),
    ),
    "stretch_transfer": (
        ("transferred_rule", "Identify the rule that transfers", "concept", True),
        ("new_structure", "Apply it in the changed structure", "transfer", True),
        ("transfer_result", "Obtain and check the transferred result", "check", True),
    ),
    "symbol_unit_audit": (
        ("symbol_or_unit", "Identify the required symbol or unit", "expression_notation", True),
        ("consistent_use", "Use it consistently in the work", "procedure", True),
        ("audited_result", "State the result with the correct symbol or unit", "final_answer", True),
    ),
    "transfer_retest": (
        ("stable_rule", "Identify the rule retained from the earlier structure", "concept", True),
        ("changed_condition", "Account for the changed condition", "transfer", True),
        ("new_result", "Obtain the result under the new condition", "calculation", True),
    ),
    "two_method_compare": (
        ("method_one", "Carry out the first valid method", "procedure", True),
        ("method_two", "Carry out the second valid method", "procedure", True),
        ("method_comparison", "Compare when the methods are useful", "transfer", True),
    ),
    "variant": (
        ("unchanged_rule", "Identify the rule that remains unchanged", "concept", True),
        ("variant_relation", "Build the relation for the variant", "model_relation", True),
        ("variant_result", "Obtain the variant result", "calculation", True),
    ),
}


def _persist_stage3_answer_contract_fixtures(conn, checkpoint_root):
    from learning_system import (
        answer_contract_generation,
        internal_agents,
        model_router,
        semantic_agents,
    )

    contract = internal_agents.load_v5_contract_for_agent(
        "answer_contract_designer_agent"
    )
    schema_version = contract["response_schema_version"]
    route = model_router.ModelRoute(
        agent_key="answer_contract_designer_agent",
        task="answer_contract_design",
        provider="openai",
        model="gpt-5.5",
        model_alias="gpt-5.5",
        base_url="https://configured.example/v1",
        api_key="test-only-key",
        timeout_seconds=120,
        model_params={"temperature": 0},
    )
    prompt_template_sha256 = internal_agents.file_sha256(
        internal_agents.prompt_path_for_contract(contract)
    )
    response_schema_sha256 = internal_agents.canonical_json_sha256(
        contract["response_schema"]
    )

    def semantic_call(request):
        question = request.untrusted_payload["question"]
        components = {
            "expected_answer": question.get("expected_answer"),
            **{
                f"solution_steps[{index}]": step
                for index, step in enumerate(
                    question.get("solution_steps") or []
                )
            },
        }
        items = []
        for slot in request.trusted_context["slots"]:
            reference_key = slot["allowed_reference_component_keys"][0]
            reference_value = str(components.get(reference_key) or "").strip()
            reference_value = " ".join(reference_value.split())
            for separator in (";", "；", "\n"):
                reference_value = reference_value.replace(separator, "，")
            reference_value = reference_value.replace(" and also ", " and ")
            reference_value = reference_value.replace(" as well as ", " and ")
            reference_value = reference_value.replace("并且", "且")
            items.append(
                {
                    "item_handle": request.trusted_context["item_handle"],
                    "slot_key": slot["slot_key"],
                    "criterion": (
                        f"States the required {slot['slot_key']} with this concrete "
                        "mathematical evidence: "
                        f"{reference_value}"
                    ),
                    "reference_component_keys": [reference_key],
                    "confidence": 1.0,
                }
            )
        return semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_contract_designer_agent",
            phase="answer_contract_design",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=1.0,
            output={
                "schema_version": schema_version,
                "items": items,
            },
            route_meta={
                "structured_json_mode": "json_schema",
                "structured_json_endpoint": "responses",
                "prompt_template_sha256": prompt_template_sha256,
                "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
                    request
                ),
                "response_schema_sha256": response_schema_sha256,
                "raw_response_sha256": "b" * 64,
            },
            prompt_version_id=contract["prompt_version_id"],
            response_schema_version=schema_version,
        )

    with mock.patch.object(
        model_router,
        "answer_contract_design_route",
        return_value=route,
    ), mock.patch.object(
        semantic_agents,
        "call_answer_contract_designer_agent",
        side_effect=semantic_call,
    ):
        designer = answer_contract_generation.make_live_designer(conn)
        report = answer_contract_generation.run_design(
            conn,
            PROJECT_ROOT,
            designer,
            checkpoint_root,
        )
    if report["processed_items"] != 1120 or report["model_calls"] != 1120:
        raise AssertionError(f"incomplete Stage 3 fixture generation: {report}")
    rows = conn.execute(
        "select generator_run_id, review_receipt_json from answer_contracts "
        "where status = 'review_pending'"
    ).fetchall()
    if len(rows) != 1120:
        raise AssertionError("Stage 3 fixture rows must cover all 1,120 questions")
    for row in rows:
        receipt = db.json_load(row["review_receipt_json"], {})
        if (
            not row["generator_run_id"]
            or receipt.get("agent_key") != "answer_contract_designer_agent"
            or receipt.get("phase") != "answer_contract_design"
            or receipt.get("provider_mode") != "live_model"
            or receipt.get("agent_run_id") != row["generator_run_id"]
        ):
            raise AssertionError("Stage 3 fixture lineage must be exact live evidence")


def _assert_persisted_stage3_review_plan(test_case, plan):
    test_case.assertEqual(1120, plan["persisted_draft_count"])
    test_case.assertEqual(0, plan["injected_test_draft_count"])
    for node in plan["nodes"]:
        for item in node["items"]:
            test_case.assertEqual(
                "persisted_exact_version_draft", item["design_source"]
            )


class AnswerAssessmentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-assessment-v51.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _table_names(self, conn=None):
        conn = conn or self.conn
        return {
            row["name"]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    def _column_names(self, table, conn=None):
        conn = conn or self.conn
        return {
            row["name"]
            for row in conn.execute(f"pragma table_info({table})").fetchall()
        }

    def _column_info(self, table, conn=None):
        conn = conn or self.conn
        return {
            row["name"]: row
            for row in conn.execute(f"pragma table_info({table})").fetchall()
        }

    def _indexes(self, table, conn=None):
        conn = conn or self.conn
        indexes = []
        for row in conn.execute(f"pragma index_list({table})").fetchall():
            name = row["name"]
            columns = tuple(
                info["name"]
                for info in conn.execute(f"pragma index_info({name})").fetchall()
            )
            sql_row = conn.execute(
                "select sql from sqlite_master where type = 'index' and name = ?",
                (name,),
            ).fetchone()
            indexes.append(
                {
                    "name": name,
                    "columns": columns,
                    "unique": bool(row["unique"]),
                    "partial": bool(row["partial"]),
                    "sql": (sql_row["sql"] if sql_row else "") or "",
                }
            )
        return indexes

    def _assert_partial_unique_index(self, table, columns, status, conn=None):
        matching = []
        status_pattern = re.compile(
            rf"where\s+status\s*=\s*['\"]{re.escape(status)}['\"]",
            re.IGNORECASE,
        )
        for index in self._indexes(table, conn):
            if (
                index["unique"]
                and index["partial"]
                and index["columns"] == tuple(columns)
                and status_pattern.search(index["sql"])
            ):
                matching.append(index["name"])
        self.assertTrue(
            matching,
            f"missing partial unique index on {table}{tuple(columns)} where status={status!r}",
        )

    def _copy_pre_v51_backup(self, name):
        if not PRE_V51_BACKUP_PATH.is_file():
            self.skipTest("legacy pre-v5.1 database was deliberately removed with obsolete learning data")
        copied_path = Path(self.tmpdir.name) / name
        shutil.copy2(PRE_V51_BACKUP_PATH, copied_path)
        conn = sqlite3.connect(copied_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _foreign_key_targets(self, table, conn):
        return {
            (row["from"], row["table"], row["to"])
            for row in conn.execute(f"pragma foreign_key_list({table})").fetchall()
        }

    def _insert_minimal_row(self, conn, table, overrides):
        self.assertIn(table, self._table_names(conn))
        info_rows = conn.execute(f"pragma table_info({table})").fetchall()
        info = {row["name"]: row for row in info_rows}
        self.assertTrue(set(overrides).issubset(info), (table, set(overrides) - set(info)))
        foreign_keys = {
            row["from"]: (row["table"], row["to"])
            for row in conn.execute(f"pragma foreign_key_list({table})").fetchall()
        }
        values = dict(overrides)
        for name, row in info.items():
            if name in values or row["dflt_value"] is not None:
                continue
            if not row["notnull"] and not row["pk"]:
                continue
            if row["pk"] and "INT" in str(row["type"]).upper():
                continue
            if name in foreign_keys:
                parent_table, parent_column = foreign_keys[name]
                parent = conn.execute(
                    f"select {parent_column} from {parent_table} limit 1"
                ).fetchone()
                self.assertIsNotNone(parent, f"missing parent for {table}.{name}")
                values[name] = parent[0]
            elif name.endswith("_json"):
                values[name] = "{}"
            elif "INT" in str(row["type"]).upper():
                values[name] = 1
            elif any(token in name for token in ("sha256", "digest")):
                values[name] = "a" * 64
            elif name.endswith("_at"):
                values[name] = db.now_iso()
            else:
                values[name] = f"test-{table}-{name}"
        columns = tuple(values)
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"insert into {table} ({', '.join(columns)}) values ({placeholders})",
            tuple(values[column] for column in columns),
        )

    def _insert_contract(
        self,
        conn,
        *,
        row_id,
        stable_contract_id,
        contract_version,
        question_id,
        item_version,
        status="draft",
        digest=None,
    ):
        self._insert_minimal_row(
            conn,
            "answer_contracts",
            {
                "id": row_id,
                "stable_contract_id": stable_contract_id,
                "contract_version": contract_version,
                "question_id": question_id,
                "item_version": item_version,
                "contract_digest_sha256": digest or (row_id.encode().hex() + "0" * 64)[:64],
                "status": status,
            },
        )

    def _first_questions(self, conn, count=2):
        rows = conn.execute(
            "select id, item_version from question_items order by id limit ?",
            (count,),
        ).fetchall()
        self.assertEqual(count, len(rows))
        return rows

    def test_creates_answer_contract_and_attempt_assessment_tables(self):
        self.assertTrue(
            {"answer_contracts", "attempt_assessments"}.issubset(self._table_names())
        )

    def test_daily_flows_pins_assessment_policy_version(self):
        self.assertIn(
            "assessment_policy_version",
            self._column_names("daily_flows"),
        )

    def test_flow_steps_capture_answer_contract_identity(self):
        self.assertTrue(
            {"answer_contract_id", "answer_contract_version"}.issubset(
                self._column_names("flow_steps")
            )
        )

    def test_attempts_capture_clarification_role_and_lineage(self):
        self.assertTrue(
            {"clarifies_attempt_id", "attempt_role"}.issubset(
                self._column_names("attempts")
            )
        )

    def test_evidence_validations_reference_exact_assessment_version(self):
        self.assertTrue(
            {
                "assessment_id",
                "assessment_version",
                "assessment_digest_sha256",
            }.issubset(self._column_names("evidence_validations"))
        )

    def test_only_one_active_contract_exists_per_question_item_version(self):
        self._assert_partial_unique_index(
            "answer_contracts",
            ("question_id", "item_version"),
            "active",
        )

    def test_only_one_accepted_assessment_exists_per_attempt_version(self):
        self._assert_partial_unique_index(
            "attempt_assessments",
            ("attempt_id", "attempt_version"),
            "accepted",
        )

    def test_reference_columns_are_nullable_foreign_keys_to_authority_rows(self):
        conn = self._copy_pre_v51_backup("foreign-key-contract.sqlite")
        try:
            db.init_schema(conn)
            self.assertIn(
                ("answer_contract_id", "answer_contracts", "id"),
                self._foreign_key_targets("flow_steps", conn),
            )
            self.assertIn(
                ("assessment_id", "attempt_assessments", "id"),
                self._foreign_key_targets("evidence_validations", conn),
            )
            nullable_columns = {
                "flow_steps": (
                    "answer_contract_id",
                    "answer_contract_version",
                    "answer_contract_digest_sha256",
                ),
                "attempts": ("clarifies_attempt_id",),
                "evidence_validations": (
                    "assessment_id",
                    "assessment_version",
                    "assessment_digest_sha256",
                ),
            }
            for table, columns in nullable_columns.items():
                info = self._column_info(table, conn)
                for column in columns:
                    self.assertIn(column, info)
                    self.assertEqual(0, info[column]["notnull"], f"{table}.{column}")
                    self.assertNotIn(
                        str(info[column]["dflt_value"]).strip(),
                        {"''", '""'},
                        f"{table}.{column} must use NULL for no reference",
                    )
                    self.assertEqual(
                        0,
                        conn.execute(
                            f"select count(*) from {table} where {column} = ''"
                        ).fetchone()[0],
                        f"{table}.{column} contains empty-string references",
                    )
        finally:
            conn.close()


_BaseAnswerAssessmentSchemaTests = AnswerAssessmentSchemaTests


class AssessmentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = importlib.import_module("learning_system.assessment_policy")

    def _question(self, kind="standard_example", **overrides):
        target_specs = KIND_SCORING_TARGET_SPECS[kind]
        scoring_targets = [
            {
                "key": key,
                "criterion": criterion,
                "dimension": dimension,
                "required_for_pass": required,
                "reference_component": key,
            }
            for key, criterion, dimension, required in target_specs
        ]
        question = {
            "id": f"Q-{kind}",
            "item_version": "2026-07-08.bank.v11",
            "node_id": "M-G7-NUMBER-LINE",
            "kind": kind,
            "question_type": f"{kind} contract probe",
            "prompt": "数轴上 A=-2.5，点 C 在 A 右边 3 个单位，求 C 并排列 A、B、C。"
            + " 请分别完成："
            + "；".join(target["criterion"] for target in scoring_targets),
            "answer_format": "关系、结果和顺序",
            "expected_answer": "C=0.5，A<C<B",
            "solution_steps": ["C=A+3", "C=0.5", "A<C<B"],
            "scoring_targets": scoring_targets,
            "allowed_mastery_dimensions": sorted(ALLOWED_TEST_DIMENSIONS),
            "status": "reviewed",
        }
        question.update(overrides)
        return question

    def _number_line_contract(self):
        scoring_targets = copy.deepcopy(self._question()["scoring_targets"])
        return {
            "question_id": "QB11-M-G7-NUMBER-LINE-05",
            "item_version": "2026-07-08.bank.v11",
            "node_id": "M-G7-NUMBER-LINE",
            "reference_solution": {
                "answer": "C=0.5, A<C<B",
                "key_relation": "C=A+3",
            },
            "scoring_targets": scoring_targets,
            "score_points": [
                {
                    "key": "right_means_add_three",
                    "criterion": "Recognizes that moving three units right means adding 3",
                    "points": 3,
                    "dimension": "model_relation",
                    "required_for_pass": True,
                    "source_target_key": "rightward_relation",
                },
                {
                    "key": "value_of_c",
                    "criterion": "Obtains C=0.5",
                    "points": 4,
                    "dimension": "calculation",
                    "required_for_pass": True,
                    "source_target_key": "c_value",
                },
                {
                    "key": "ascending_order",
                    "criterion": "Orders the points as A<C<B",
                    "points": 3,
                    "dimension": "representation",
                    "required_for_pass": True,
                    "source_target_key": "ascending_order",
                },
            ],
        }

    def _met_judgments(self, contract):
        return [
            {
                "criterion_key": point["key"],
                "status": "met",
                "child_evidence": f"grounded evidence for {point['key']}",
                "reason": "The child response satisfies this criterion.",
            }
            for point in contract["score_points"]
        ]

    def test_build_answer_contract_covers_all_twenty_active_kinds(self):
        built = {
            kind: self.policy.build_answer_contract(self._question(kind))
            for kind in ACTIVE_QUESTION_KINDS
        }
        self.assertEqual(set(ACTIVE_QUESTION_KINDS), set(built))
        self.assertEqual(20, len(built))

    def test_each_kind_builds_a_strict_ten_point_atomic_contract(self):
        for kind in ACTIVE_QUESTION_KINDS:
            with self.subTest(kind=kind):
                contract = self.policy.build_answer_contract(self._question(kind))
                reference = contract.get("reference_solution")
                self.assertTrue(reference)
                points = contract.get("score_points")
                self.assertIsInstance(points, list)
                self.assertGreaterEqual(len(points), 2)
                self.assertLessEqual(len(points), 4)
                keys = [point.get("key") for point in points]
                self.assertTrue(all(isinstance(key, str) and key.strip() for key in keys))
                self.assertEqual(len(keys), len(set(keys)))
                self.assertTrue(
                    all(
                        isinstance(point.get("criterion"), str)
                        and point["criterion"].strip()
                        and isinstance(point.get("points"), int)
                        and not isinstance(point.get("points"), bool)
                        and point["points"] > 0
                        and point.get("dimension") in ALLOWED_TEST_DIMENSIONS
                        and isinstance(point.get("required_for_pass"), bool)
                        for point in points
                    ),
                    points,
                )
                self.assertEqual(10, sum(point["points"] for point in points))
                self.assertTrue(any(point["required_for_pass"] for point in points))
                target_keys = {
                    target["key"] for target in self._question(kind)["scoring_targets"]
                }
                source_target_keys = [
                    point.get("source_target_key") for point in points
                ]
                self.assertTrue(
                    all(isinstance(key, str) and key.strip() for key in source_target_keys),
                    points,
                )
                self.assertEqual(len(source_target_keys), len(set(source_target_keys)))
                self.assertTrue(set(source_target_keys).issubset(target_keys))
                if set(source_target_keys) != target_keys:
                    self.assertEqual(
                        set(source_target_keys),
                        set(contract.get("selected_scoring_target_keys") or []),
                    )
                    self.assertTrue(contract.get("omitted_scoring_target_reasons"))
                self.policy.validate_contract(contract)

    def test_twenty_kinds_use_distinct_multicomponent_scoring_target_samples(self):
        signatures = set()
        for kind in ACTIVE_QUESTION_KINDS:
            with self.subTest(kind=kind):
                targets = self._question(kind)["scoring_targets"]
                self.assertGreaterEqual(len(targets), 2)
                self.assertLessEqual(len(targets), 4)
                keys = tuple(target["key"] for target in targets)
                self.assertEqual(len(keys), len(set(keys)))
                signatures.add(keys)
        self.assertEqual(20, len(signatures))

    def test_number_line_scoring_targets_remain_three_independent_sources(self):
        question = self._question("standard_example")
        self.assertEqual(
            {"rightward_relation", "c_value", "ascending_order"},
            {target["key"] for target in question["scoring_targets"]},
        )
        contract = self.policy.build_answer_contract(question)
        self.assertEqual(
            {"rightward_relation", "c_value", "ascending_order"},
            {point["source_target_key"] for point in contract["score_points"]},
        )
        self.assertEqual(
            len(contract["score_points"]),
            len({point["source_target_key"] for point in contract["score_points"]}),
        )

    def test_validate_contract_rejects_structural_and_scoring_invalidity(self):
        valid = self._number_line_contract()
        invalid_contracts = []
        missing_reference = copy.deepcopy(valid)
        missing_reference["reference_solution"] = {}
        invalid_contracts.append(missing_reference)
        too_few = copy.deepcopy(valid)
        too_few["score_points"] = too_few["score_points"][:1]
        invalid_contracts.append(too_few)
        duplicate_key = copy.deepcopy(valid)
        duplicate_key["score_points"][1]["key"] = duplicate_key["score_points"][0]["key"]
        invalid_contracts.append(duplicate_key)
        wrong_total = copy.deepcopy(valid)
        wrong_total["score_points"][0]["points"] = 2
        invalid_contracts.append(wrong_total)
        no_required = copy.deepcopy(valid)
        for point in no_required["score_points"]:
            point["required_for_pass"] = False
        invalid_contracts.append(no_required)
        invalid_dimension = copy.deepcopy(valid)
        invalid_dimension["score_points"][0]["dimension"] = "invented_dimension"
        invalid_contracts.append(invalid_dimension)

        self.policy.validate_contract(valid)
        for invalid in invalid_contracts:
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.policy.validate_contract(invalid)

    def test_criterion_judgments_require_exact_keys(self):
        contract = self._number_line_contract()
        valid = self._met_judgments(contract)
        self.policy.validate_criterion_judgments(contract, valid)

        missing = valid[:-1]
        duplicate = copy.deepcopy(valid)
        duplicate[-1]["criterion_key"] = duplicate[0]["criterion_key"]
        unknown = copy.deepcopy(valid)
        unknown[-1]["criterion_key"] = "unknown_key"
        for judgments in (missing, duplicate, unknown):
            with self.subTest(judgments=judgments):
                with self.assertRaises((TypeError, ValueError)):
                    self.policy.validate_criterion_judgments(contract, judgments)

    def test_criterion_judgments_reject_invalid_status(self):
        contract = self._number_line_contract()
        judgments = self._met_judgments(contract)
        judgments[0]["status"] = "partly_met"
        with self.assertRaises((TypeError, ValueError)):
            self.policy.validate_criterion_judgments(contract, judgments)

    def test_validate_contract_rejects_duplicate_or_multi_source_targets(self):
        contract = self._number_line_contract()
        duplicate_source = copy.deepcopy(contract)
        duplicate_source["score_points"][1]["source_target_key"] = duplicate_source[
            "score_points"
        ][0]["source_target_key"]
        multi_source_list = copy.deepcopy(contract)
        multi_source_list["score_points"][0]["source_target_key"] = [
            "rightward_relation",
            "c_value",
        ]
        multi_source_field = copy.deepcopy(contract)
        multi_source_field["score_points"][0]["source_target_keys"] = [
            "rightward_relation",
            "c_value",
        ]
        for invalid in (duplicate_source, multi_source_list, multi_source_field):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.policy.validate_contract(invalid)

    def test_met_judgment_requires_grounded_child_evidence(self):
        contract = self._number_line_contract()
        judgments = self._met_judgments(contract)
        judgments[0]["child_evidence"] = ""
        with self.assertRaises((TypeError, ValueError)):
            self.policy.validate_criterion_judgments(contract, judgments)

    def test_unclear_judgment_prevents_final_score(self):
        contract = self._number_line_contract()
        judgments = self._met_judgments(contract)
        judgments[1].update(
            status="unclear",
            child_evidence="The photo is unreadable at C.",
            reason="The value cannot be judged safely.",
        )
        self.policy.validate_criterion_judgments(contract, judgments)
        result = self.policy.calculate_assessment(contract, judgments)
        self.assertFalse(result["finalized"])
        self.assertIsNone(result["score_out_of_10"])
        self.assertFalse(result["question_passed"])

    def test_calculate_assessment_is_deterministic_and_required_point_aware(self):
        contract = self._number_line_contract()
        judgments = self._met_judgments(contract)
        judgments[0].update(
            status="not_met",
            child_evidence="The response never states the rightward movement relation.",
            reason="Required model relation is missing.",
        )
        result = self.policy.calculate_assessment(contract, judgments)
        self.assertTrue(result["finalized"])
        self.assertEqual(7, result["score_out_of_10"])
        self.assertFalse(result["question_passed"])
        self.assertAlmostEqual(1.4, result["compatibility_score_points"])

    def test_number_line_equivalent_expression_scores_ten_out_of_ten(self):
        contract = self._number_line_contract()
        judgments = [
            {
                "criterion_key": "right_means_add_three",
                "status": "met",
                "child_evidence": "c=a+3",
                "reason": "Right by three is expressed as adding three.",
            },
            {
                "criterion_key": "value_of_c",
                "status": "met",
                "child_evidence": "c=a+3=0.5",
                "reason": "The value of C is correct.",
            },
            {
                "criterion_key": "ascending_order",
                "status": "met",
                "child_evidence": "a,c,b",
                "reason": "The sequence is intent-equivalent to A<C<B.",
            },
        ]
        result = self.policy.calculate_assessment(contract, judgments)
        self.assertTrue(result["finalized"])
        self.assertEqual(10, result["score_out_of_10"])
        self.assertTrue(result["question_passed"])
        self.assertEqual(2, result["compatibility_score_points"])

    def test_presentation_only_omissions_are_not_invented_as_score_points(self):
        presentation_only_requirements = [
            "写完整句子",
            "圈出最容易错的一步",
            "展开例行代入",
        ]
        question = self._question(
            "standard_example",
            prompt=(
                "求 C 并按从小到大排列 A、B、C。"
                "请写完整句子，圈出最容易错的一步，并展开例行代入。"
            ),
            expected_answer="C=0.5，A<C<B",
            presentation_only_requirements=presentation_only_requirements,
            prompt_required_expression="写完整句子",
        )
        scoring_target_text = " ".join(
            f"{target['key']} {target['criterion']}"
            for target in question["scoring_targets"]
        )
        for requirement in presentation_only_requirements:
            self.assertIn(requirement, question["prompt"])
            self.assertNotIn(requirement, scoring_target_text)
        contract = self.policy.build_answer_contract(question)
        criteria_and_sources = " ".join(
            f"{point['criterion']} {point['source_target_key']}"
            for point in contract["score_points"]
        )
        for requirement in presentation_only_requirements:
            self.assertNotIn(requirement, criteria_and_sources)
        self.assertNotIn(
            "prompt_required_expression",
            {point["source_target_key"] for point in contract["score_points"]},
        )
        self.assertNotIn("写完整句子", criteria_and_sources)
        result = self.policy.calculate_assessment(contract, self._met_judgments(contract))
        self.assertEqual(10, result["score_out_of_10"])
        self.assertTrue(result["question_passed"])

    def test_fallback_contract_does_not_zero_correct_math_for_missing_meta_step(self):
        question = self._question(
            "check_strategy",
            id="QB11-M-PRE-INTEGER-OPS-04",
            node_id="M-PRE-INTEGER-OPS",
            prompt=(
                "判断 754 ÷ 6 = 125 余 4 是否正确，并写验算。"
                "请先指出要使用的结构，做完后把最容易错的一步圈出来。"
            ),
            expected_answer="6×125+4=754，4<6，正确",
            solution_steps=[
                "有余数除法满足 被除数=除数×商+余数，且余数小于除数。",
                "计算 6×125+4=754。",
                "检验 4<6，所以判断正确。",
                "最容易错的是忘记检查余数是否小于除数。",
            ],
            scoring_targets=None,
        )
        contract = self.policy.build_answer_contract(question)

        self.assertEqual("draft_unreviewed", contract["status"])
        self.assertNotIn(
            "solution_step_1",
            {point["key"] for point in contract["score_points"]},
        )
        required_keys = {
            point["key"]
            for point in contract["score_points"]
            if point["required_for_pass"]
        }
        self.assertEqual(
            {"reference_answer", "mathematical_execution"},
            required_keys,
        )

        judgments = self._met_judgments(contract)
        for judgment in judgments:
            if judgment["criterion_key"] == "verification_or_explanation":
                judgment.update(
                    status="not_met",
                    child_evidence=(
                        "The response verifies 6×125+4=754 but omits the "
                        "explicit 4<6 check and the requested common-mistake note."
                    ),
                    reason="Missing a non-core explanatory/check detail cannot erase the core math.",
                )
        result = self.policy.calculate_assessment(contract, judgments)

        self.assertTrue(result["finalized"])
        self.assertGreaterEqual(result["score_out_of_10"], 6)
        self.assertNotEqual(0, result["score_out_of_10"])
        self.assertTrue(result["question_passed"])

    def test_integer_remainder_prerequisite_is_rejected_as_low_value_mainline(self):
        from learning_system import question_bank

        item = {
            "id": "QB11-M-PRE-INTEGER-OPS-04",
            "item_version": question_bank.QUESTION_BANK_VERSION,
            "node_id": "M-PRE-INTEGER-OPS",
            "kind": "check_strategy",
            "source_type": "graph_generated",
            "prompt": (
                "判断 754 ÷ 6 = 125 余 4 是否正确，并写验算。"
                "请先指出要使用的结构，再解答。"
            ),
            "expected_answer": "6×125+4=754，4<6，正确",
            "solution_steps": [
                "有余数除法满足 被除数=除数×商+余数，且余数小于除数。",
                "计算 6×125+4=754。",
            ],
            "quality": {
                "review_status": "approved",
                "age_floor": question_bank.INCOMING_GRADE_7_AGE_FLOOR,
                "requires_reasoning": True,
                "has_high_signal_structure": True,
                "no_mechanical_drill": True,
            },
        }

        review = question_bank.review_item_quality(item)

        self.assertEqual("rejected", review["review_status"])
        self.assertIn(
            "incoming_grade_7_low_value_integer_remainder_prerequisite",
            review["rejection_reasons"],
        )

    def test_contract_profiles_never_rebind_known_semantic_misbindings(self):
        known_misbindings = (
            self._question(
                "model_selection",
                id="QB11-M-G7-NUMBER-LINE-19",
                node_id="M-G7-NUMBER-LINE",
                prompt="求二维数表第12行第15列的规律数。",
                expected_answer="208",
            ),
            self._question(
                "representation",
                id="QB11-M-G7-RATIONAL-ADD-SUB-09",
                node_id="M-G7-RATIONAL-ADD-SUB",
                prompt="3支笔和2本本子共28元，本子比笔贵5元，列方程。",
                expected_answer="3x+2(x+5)=28",
            ),
        )
        forbidden_repair_keys = {
            "corrected_node_id",
            "rebound_node_id",
            "suggested_node_id",
            "question_node_alignment",
        }
        for question in known_misbindings:
            with self.subTest(question_id=question["id"]):
                original = copy.deepcopy(question)
                contract = self.policy.build_answer_contract(question)
                self.assertEqual(original, question)
                self.assertEqual(question["id"], contract["question_id"])
                self.assertEqual(question["node_id"], contract["node_id"])
                self.assertTrue(forbidden_repair_keys.isdisjoint(contract))
                self.assertNotEqual("active", contract.get("status"))

class AnswerAssessmentSchemaTests(_BaseAnswerAssessmentSchemaTests):
    def test_invalid_flow_step_contract_reference_is_rejected_on_insert(self):
        conn = self._copy_pre_v51_backup("invalid-flow-contract.sqlite")
        try:
            db.init_schema(conn)
            flow = conn.execute("select id, graph_version from daily_flows limit 1").fetchone()
            self.assertIsNotNone(flow)
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_minimal_row(
                    conn,
                    "flow_steps",
                    {
                        "id": "FS-invalid-contract-ref",
                        "flow_id": flow["id"],
                        "step_handle": "step-invalid-contract-ref",
                        "position": 9999,
                        "step_type": "question",
                        "graph_version": flow["graph_version"],
                        "answer_contract_id": "AC-missing",
                        "answer_contract_version": 1,
                        "answer_contract_digest_sha256": "f" * 64,
                    },
                )
        finally:
            conn.close()


_BaseAnswerAssessmentSchemaTestsV2 = AnswerAssessmentSchemaTests


class AssessmentStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "assessment-store-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.store = importlib.import_module("learning_system.assessment_store")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "assessment-store.sqlite"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        db.init_schema(self.conn)
        self._create_runtime_fixture()

    def tearDown(self):
        if hasattr(self, "conn"):
            self.conn.close()
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def _create_reviewer_agent_run(
        self,
        run_id,
        *,
        agent_key="answer_contract_reviewer_agent",
        phase="answer_contract_review",
        status="accepted",
        model_provider="openai",
        model_name="gpt-5.5",
    ):
        self.conn.execute(
            """
            insert into agent_runs(
              id, agent_key, engine_type, phase, trigger,
              model_provider, model_name, model_alias,
              status, confidence, created_at
            ) values (?, ?, 'internal_learning_agent', ?, 'contract_activation_review',
                      ?, ?, ?, ?, 0.99, ?)
            """,
            (
                run_id,
                agent_key,
                phase,
                model_provider,
                model_name,
                model_name,
                status,
                db.now_iso(),
            ),
        )

    def _restore_canonical_reviewer_run(self):
        self.conn.execute(
            """
            update agent_runs
            set agent_key = 'answer_contract_reviewer_agent',
                phase = 'answer_contract_review',
                status = 'accepted',
                model_provider = 'openai',
                model_name = 'gpt-5.5',
                model_alias = 'gpt-5.5'
            where id = ?
            """,
            (self.reviewer_run_id,),
        )
        self.conn.execute(
            "update question_review_records set reviewer_run_id = ? where id = ?",
            (self.reviewer_run_id, self.review_record_id),
        )
        self.conn.commit()

    def _create_runtime_fixture(self):
        question_row = self.conn.execute(
            """
            select qi.*
            from question_items qi
            join question_review_records qrr on qrr.question_id = qi.id
            where qrr.review_status = 'approved' and qrr.active_eligible = 1
            order by qi.id
            limit 1
            """
        ).fetchone()
        self.assertIsNotNone(question_row)
        self.question = db.row_to_question(question_row)
        review_row = self.conn.execute(
            """
            select *
            from question_review_records
            where question_id = ? and review_status = 'approved' and active_eligible = 1
            order by reviewed_at desc, id desc
            limit 1
            """,
            (self.question["id"],),
        ).fetchone()
        self.assertIsNotNone(review_row)
        self.reviewer_run_id = "RUN-answer-contract-review-live"
        self._create_reviewer_agent_run(self.reviewer_run_id)
        self.review_record_id = "QRR-answer-contract-review-live"
        self.conn.execute(
            "update question_review_records set active_eligible = 0 where question_id = ?",
            (self.question["id"],),
        )
        cloned_review = dict(review_row)
        cloned_review.update(
            id=self.review_record_id,
            candidate_sha256="e" * 64,
            reviewer_run_id=self.reviewer_run_id,
            review_contract_version="answer_contract_review.v1",
            review_status="approved",
            active_eligible=1,
            reviewed_at=db.now_iso(),
        )
        review_columns = tuple(cloned_review)
        self.conn.execute(
            f"insert into question_review_records ({', '.join(review_columns)}) "
            f"values ({', '.join('?' for _ in review_columns)})",
            tuple(cloned_review[column] for column in review_columns),
        )
        self.session_id = "LS-assessment-store"
        self.flow_id = "DF-assessment-store"
        self.flow_step_id = "FS-assessment-store"
        self.attempt_id = "ATT-assessment-store"
        now = db.now_iso()
        graph_version = "2026-07-04.v2"
        self.conn.execute(
            "insert into learning_sessions(id, title, mode, created_at) values (?, ?, ?, ?)",
            (self.session_id, "assessment store", "review", now),
        )
        self.conn.execute(
            """
            insert into daily_flows(
              id, child_key, local_date, mode, status, graph_version,
              legacy_session_id, assessment_policy_version, created_at, updated_at
            ) values (?, 'single-child', '2026-07-14', 'review', 'active', ?, ?, 'v5.1', ?, ?)
            """,
            (self.flow_id, graph_version, self.session_id, now, now),
        )
        self.conn.execute(
            """
            insert into flow_steps(
              id, flow_id, step_handle, position, step_type, status, graph_version,
              node_id, question_bank_version, question_id, question_item_version,
              review_record_id, created_at, updated_at
            ) values (?, ?, ?, 1, 'question', 'selected', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.flow_step_id,
                self.flow_id,
                "step-assessment-store",
                graph_version,
                self.question["node_id"],
                self.question["item_version"],
                self.question["id"],
                self.question["item_version"],
                self.review_record_id,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            insert into attempts(
              id, session_id, question_id, node_id, result, grading_status,
              score_points, max_points, error_tags_json, answer_raw, parent_note,
              answer_analysis_json, interaction_response_json, flow_step_id,
              graph_version, question_bank_version, attempt_version,
              analysis_status, client_idempotency_key, answer_source,
              evidence_digest_sha256, attachment_ids_json, review_record_id, created_at
            ) values (?, ?, ?, ?, 'pending', 'pending_review', 0, 2, '[]', ?, '', '{}', ?, ?, ?, ?, 1,
                      'pending', 'submit-store-1', 'text', ?, ?, ?, ?)
            """,
            (
                self.attempt_id,
                self.session_id,
                self.question["id"],
                self.question["node_id"],
                "a,c,b\nc=a+3=0.5",
                json.dumps({"selected": ["A", "C", "B"]}),
                self.flow_step_id,
                graph_version,
                self.question["item_version"],
                "d" * 64,
                json.dumps(["ATTACHMENT-ORIGINAL"]),
                self.review_record_id,
                now,
            ),
        )
        self.conn.execute(
            "update flow_steps set attempt_id = ? where id = ?",
            (self.attempt_id, self.flow_step_id),
        )
        self.conn.commit()

    def _contract(self, *, version=1, digest=None):
        return {
            "stable_contract_id": f"AC-{self.question['id']}",
            "contract_version": version,
            "contract_digest_sha256": digest or str(version) * 64,
            "question_id": self.question["id"],
            "item_version": self.question["item_version"],
            "node_id": self.question["node_id"],
            "reference_solution": {
                "answer": "C=0.5, A<C<B",
                "key_relation": "C=A+3",
            },
            "score_points": [
                {
                    "key": "rightward_relation",
                    "criterion": "Moving right three means adding three",
                    "source_target_key": "rightward_relation",
                    "points": 3,
                    "dimension": "model_relation",
                    "required_for_pass": True,
                },
                {
                    "key": "c_value",
                    "criterion": "C equals 0.5",
                    "source_target_key": "c_value",
                    "points": 4,
                    "dimension": "calculation",
                    "required_for_pass": True,
                },
                {
                    "key": "ascending_order",
                    "criterion": "The order is A<C<B",
                    "source_target_key": "ascending_order",
                    "points": 3,
                    "dimension": "representation",
                    "required_for_pass": True,
                },
            ],
            "review_run_id": self.reviewer_run_id,
            "review_receipt_sha256": "r" * 64,
            "review_provider_mode": "live_model",
            "question_correctness": "pass",
            "question_node_alignment": "aligned",
            "evidence_role_alignment": "aligned",
            "prompt_instance_fingerprint": f"instance-{version}",
            "core_structure_fingerprint": "number-line-rightward-order",
            "fingerprint_policy_version": "question-fingerprint.v1",
            "status": "draft",
        }

    def _activate(self, contract=None):
        return self.store.activate_contract(
            self.conn,
            self.question,
            self.review_record_id,
            contract or self._contract(),
            "assessment-contract-generator.v1",
        )

    def _judgments(self, *, unclear=False):
        judgments = [
            {
                "criterion_key": "rightward_relation",
                "status": "met",
                "child_evidence": "c=a+3",
                "reason": "The rightward relation is correct.",
            },
            {
                "criterion_key": "c_value",
                "status": "unclear" if unclear else "met",
                "child_evidence": "c=a+3=0.5" if not unclear else "unreadable value",
                "reason": "The value is correct." if not unclear else "Cannot judge safely.",
            },
            {
                "criterion_key": "ascending_order",
                "status": "met",
                "child_evidence": "a,c,b",
                "reason": "Intent-equivalent to A<C<B.",
            },
        ]
        return judgments

    def _feedback(self):
        return {
            "reference_answer": "C=0.5, A<C<B",
            "answer_gap": "没有影响得分的数学差距。",
            "improvement_direction": ["可以把代入过程写出来。"],
            "expression_judgment": "a,c,b 在这里与 A<C<B 的数学意图一致。",
            "teaching_explanation": "数轴上向右移动表示加。",
        }

    def _record_pending(self, contract, *, input_digest="i" * 64):
        return self.store.record_pending_assessment(
            self.conn,
            attempt_id=self.attempt_id,
            attempt_version=1,
            contract=contract,
            assessment_input_digest_sha256=input_digest,
        )

    def _accept(self, pending, *, unclear=False, digest="a" * 64):
        return self.store.accept_assessment(
            self.conn,
            assessment_id=pending["id"],
            criterion_judgments=self._judgments(unclear=unclear),
            score_out_of_10=None if unclear else 10,
            question_passed=False if unclear else True,
            feedback=self._feedback(),
            assessment_digest_sha256=digest,
            answer_analysis_agent_run_id=None,
            provider_mode="recorded_model",
        )

    def test_contract_activation_reuses_digest_and_versions_immutably(self):
        first = self._activate()
        retry = self._activate()
        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(first["contract_digest_sha256"], retry["contract_digest_sha256"])

        conflicting = self._contract(version=1, digest="9" * 64)
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._activate(conflicting)

        second = self._activate(self._contract(version=2, digest="2" * 64))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(2, second["contract_version"])

    def test_active_query_and_flow_step_bind_exact_contract_lineage(self):
        contract = self._activate()
        active = self.store.active_contract_for_question(
            self.conn,
            self.question["id"],
            self.question["item_version"],
        )
        self.assertEqual(contract["id"], active["id"])
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        row = self.conn.execute(
            """
            select answer_contract_id, answer_contract_version, answer_contract_digest_sha256
            from flow_steps where id = ?
            """,
            (self.flow_step_id,),
        ).fetchone()
        self.assertEqual(contract["id"], row["answer_contract_id"])
        self.assertEqual(contract["contract_version"], row["answer_contract_version"])
        self.assertEqual(contract["contract_digest_sha256"], row["answer_contract_digest_sha256"])

    def test_pending_assessment_retry_returns_canonical_row(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        first = self._record_pending(contract)
        retry = self._record_pending(contract)
        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(first["assessment_version"], retry["assessment_version"])

    def test_accept_writes_authority_and_compatibility_without_mutating_raw_evidence(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        before = self.conn.execute(
            "select answer_raw, attachment_ids_json, interaction_response_json from attempts where id = ?",
            (self.attempt_id,),
        ).fetchone()
        accepted = self._accept(self._record_pending(contract))
        current = self.store.accepted_assessment_for_attempt(
            self.conn, self.attempt_id, 1
        )
        self.assertEqual(accepted["id"], current["id"])
        attempt = self.conn.execute(
            """
            select answer_raw, attachment_ids_json, interaction_response_json,
                   score_points, max_points, result, answer_analysis_json
            from attempts where id = ?
            """,
            (self.attempt_id,),
        ).fetchone()
        self.assertEqual(before["answer_raw"], attempt["answer_raw"])
        self.assertEqual(before["attachment_ids_json"], attempt["attachment_ids_json"])
        self.assertEqual(before["interaction_response_json"], attempt["interaction_response_json"])
        self.assertEqual(2, attempt["score_points"])
        self.assertEqual(2, attempt["max_points"])
        self.assertEqual("correct", attempt["result"])
        self.assertTrue(json.loads(attempt["answer_analysis_json"]))

    def test_second_accepted_rejects_until_supersession_and_retries_are_canonical(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        first_pending = self._record_pending(contract)
        first = self._accept(first_pending)
        retry = self._accept(first_pending)
        self.assertEqual(first["id"], retry["id"])

        second_pending = self._record_pending(contract, input_digest="j" * 64)
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._accept(second_pending, digest="b" * 64)

        superseded = self.store.supersede_assessment(
            self.conn,
            assessment_id=first["id"],
            reason="correctness quarantine",
        )
        self.assertEqual("superseded", superseded["status"])
        second = self._accept(second_pending, digest="b" * 64)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["id"], second["superseded_assessment_id"])
        current = self.store.accepted_assessment_for_attempt(
            self.conn, self.attempt_id, 1
        )
        self.assertEqual(second["id"], current["id"])

    def test_feedback_projection_is_exact_and_child_safe(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        accepted = self._accept(self._record_pending(contract))
        projection = self.store.assessment_feedback_projection(accepted)
        self.assertEqual(
            {
                "score_label",
                "reference_answer",
                "answer_gap",
                "improvement_direction",
                "expression_judgment",
            },
            set(projection),
        )
        self.assertEqual("10/10", projection["score_label"])
        self.assertNotIn("teaching_explanation", projection)
        serialized = json.dumps(projection, ensure_ascii=False).lower()
        for forbidden in (
            "criterion",
            "provider",
            "assessment_id",
            "contract_id",
            "agent_run",
            "prompt_version",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_unclear_criterion_cannot_be_accepted_as_final_score(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        pending = self._record_pending(contract)
        with self.assertRaises((TypeError, ValueError)):
            self._accept(pending, unclear=True)
        self.assertIsNone(
            self.store.accepted_assessment_for_attempt(self.conn, self.attempt_id, 1)
        )

    def test_contract_fk_version_and_digest_mismatches_fail_closed(self):
        contract = self._activate()
        tampered = dict(contract)
        tampered["contract_version"] = contract["contract_version"] + 1
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, tampered)
        tampered = dict(contract)
        tampered["contract_digest_sha256"] = "f" * 64
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._record_pending(tampered)

    def test_activation_requires_review_record_reviewer_run(self):
        self.conn.execute(
            "update question_review_records set reviewer_run_id = null where id = ?",
            (self.review_record_id,),
        )
        self.conn.commit()
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._activate()

    def test_activation_rejects_contract_and_review_record_run_mismatch(self):
        contract = self._contract()
        contract["review_run_id"] = "RUN-other-review"
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._activate(contract)

    def test_activation_rejects_missing_referenced_agent_run(self):
        self.conn.execute(
            "update question_review_records set reviewer_run_id = 'RUN-missing' where id = ?",
            (self.review_record_id,),
        )
        self.conn.commit()
        contract = self._contract()
        contract["review_run_id"] = "RUN-missing"
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            self._activate(contract)

    def test_activation_rejects_non_live_or_wrong_reviewer_lineage(self):
        invalid_variants = (
            {"status": "succeeded"},
            {"model_provider": "recorded_fixture"},
            {"model_name": "gpt-5.4-mini"},
            {"agent_key": "question_reviewer_agent"},
            {"phase": "question_review"},
        )
        for overrides in invalid_variants:
            with self.subTest(overrides=overrides):
                self._restore_canonical_reviewer_run()
                assignments = ", ".join(f"{column} = ?" for column in overrides)
                self.conn.execute(
                    f"update agent_runs set {assignments} where id = ?",
                    (*overrides.values(), self.reviewer_run_id),
                )
                self.conn.commit()
                with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
                    self._activate()

    def test_only_exact_accepted_live_answer_contract_reviewer_run_activates(self):
        contract = self._activate()
        self.assertEqual(self.reviewer_run_id, contract["review_run_id"])
        self.assertEqual("active", contract["status"])

    def test_accept_derives_full_credit_compatibility_without_caller_projection(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        self._accept(self._record_pending(contract))
        attempt = self.conn.execute(
            "select score_points, max_points, result from attempts where id = ?",
            (self.attempt_id,),
        ).fetchone()
        self.assertEqual((2, 2, "correct"), tuple(attempt))

    def test_accept_derives_partial_and_zero_compatibility_from_authority(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        pending = self._record_pending(contract)
        partial_judgments = self._judgments()
        partial_judgments[0].update(
            status="not_met",
            child_evidence="No rightward relation was stated.",
            reason="A required point is not met.",
        )
        self.store.accept_assessment(
            self.conn,
            assessment_id=pending["id"],
            criterion_judgments=partial_judgments,
            score_out_of_10=7,
            question_passed=False,
            feedback=self._feedback(),
            assessment_digest_sha256="p" * 64,
            answer_analysis_agent_run_id=None,
            provider_mode="recorded_model",
        )
        partial = self.conn.execute(
            "select score_points, max_points, result from attempts where id = ?",
            (self.attempt_id,),
        ).fetchone()
        self.assertAlmostEqual(1.4, partial["score_points"])
        self.assertEqual(2, partial["max_points"])
        self.assertEqual("partial", partial["result"])

    def test_accept_derives_zero_score_as_wrong(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        pending = self._record_pending(contract)
        judgments = self._judgments()
        for judgment in judgments:
            judgment.update(
                status="not_met",
                child_evidence="No supported mathematical evidence.",
                reason="The criterion is not met.",
            )
        self.store.accept_assessment(
            self.conn,
            assessment_id=pending["id"],
            criterion_judgments=judgments,
            score_out_of_10=0,
            question_passed=False,
            feedback=self._feedback(),
            assessment_digest_sha256="z" * 64,
            answer_analysis_agent_run_id=None,
            provider_mode="recorded_model",
        )
        attempt = self.conn.execute(
            "select score_points, max_points, result from attempts where id = ?",
            (self.attempt_id,),
        ).fetchone()
        self.assertEqual((0, 2, "wrong"), tuple(attempt))

    def test_accept_rejects_contradictory_caller_compatibility_values(self):
        contract = self._activate()
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        pending = self._record_pending(contract)
        with self.assertRaises((TypeError, ValueError)):
            self.store.accept_assessment(
                self.conn,
                assessment_id=pending["id"],
                criterion_judgments=self._judgments(),
                score_out_of_10=10,
                question_passed=True,
                compatibility_score_points=0,
                compatibility_result="wrong",
                feedback=self._feedback(),
                assessment_digest_sha256="c" * 64,
                answer_analysis_agent_run_id=None,
                provider_mode="recorded_model",
            )

    def test_pending_assessment_schema_has_full_idempotency_unique_key(self):
        expected = (
            "attempt_id",
            "attempt_version",
            "answer_contract_id",
            "assessment_input_digest_sha256",
        )
        indexes = []
        for index in self.conn.execute(
            "pragma index_list(attempt_assessments)"
        ).fetchall():
            if not index["unique"]:
                continue
            columns = tuple(
                row["name"]
                for row in self.conn.execute(
                    f"pragma index_info({index['name']})"
                ).fetchall()
            )
            indexes.append(columns)
        self.assertIn(expected, indexes)

    def test_two_connections_converge_on_one_pending_assessment(self):
        contract = dict(self._activate())
        self.store.bind_contract_to_flow_step(self.conn, self.flow_step_id, contract)
        self.conn.commit()
        barrier = threading.Barrier(2)

        def record_from_connection():
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("pragma foreign_keys = on")
                conn.execute("pragma busy_timeout = 10000")
                barrier.wait(timeout=5)
                return self.store.record_pending_assessment(
                    conn,
                    attempt_id=self.attempt_id,
                    attempt_version=1,
                    contract=contract,
                    assessment_input_digest_sha256="concurrent-input".ljust(64, "0"),
                )
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(record_from_connection) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0]["id"], results[1]["id"])
        count = self.conn.execute(
            """
            select count(*) from attempt_assessments
            where attempt_id = ? and attempt_version = 1
              and answer_contract_id = ? and assessment_input_digest_sha256 = ?
            """,
            (
                self.attempt_id,
                contract["id"],
                "concurrent-input".ljust(64, "0"),
            ),
        ).fetchone()[0]
        self.assertEqual(1, count)

class AnswerAssessmentSchemaTests(_BaseAnswerAssessmentSchemaTestsV2):
    def test_invalid_evidence_validation_assessment_reference_is_rejected_on_insert(self):
        conn = self._copy_pre_v51_backup("invalid-assessment-ref.sqlite")
        try:
            db.init_schema(conn)
            attempt = conn.execute("select id, attempt_version from attempts limit 1").fetchone()
            self.assertIsNotNone(attempt)
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_minimal_row(
                    conn,
                    "evidence_validations",
                    {
                        "id": "EV-invalid-assessment-ref",
                        "attempt_id": attempt["id"],
                        "attempt_version": attempt["attempt_version"],
                        "assessment_id": "AS-missing",
                        "assessment_version": 1,
                        "assessment_digest_sha256": "e" * 64,
                    },
                )
        finally:
            conn.close()

    def test_contract_row_identity_and_exact_lineage_columns_are_explicit(self):
        self.assertTrue(
            {
                "id",
                "stable_contract_id",
                "contract_version",
                "question_id",
                "item_version",
                "contract_digest_sha256",
            }.issubset(self._column_names("answer_contracts"))
        )
        exact_lineage = {
            "answer_contract_id",
            "answer_contract_version",
            "answer_contract_digest_sha256",
        }
        self.assertTrue(exact_lineage.issubset(self._column_names("flow_steps")))
        self.assertTrue(exact_lineage.issubset(self._column_names("attempt_assessments")))

    def test_contract_versions_have_stable_and_question_version_uniqueness(self):
        conn = self._copy_pre_v51_backup("contract-version-uniqueness.sqlite")
        try:
            db.init_schema(conn)
            first, second = self._first_questions(conn)
            self._insert_contract(
                conn,
                row_id="AC-row-1",
                stable_contract_id="AC-stable",
                contract_version=1,
                question_id=first["id"],
                item_version=first["item_version"],
            )
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_contract(
                    conn,
                    row_id="AC-row-2",
                    stable_contract_id="AC-stable",
                    contract_version=1,
                    question_id=second["id"],
                    item_version=second["item_version"],
                )
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_contract(
                    conn,
                    row_id="AC-row-3",
                    stable_contract_id="AC-other",
                    contract_version=1,
                    question_id=first["id"],
                    item_version=first["item_version"],
                )
        finally:
            conn.close()

    def test_pre_v51_backup_migration_is_idempotent_and_preserves_rows(self):
        conn = self._copy_pre_v51_backup("migration-idempotency.sqlite")
        try:
            critical_tables = (
                "question_items",
                "question_review_records",
                "learning_sessions",
                "daily_flows",
                "flow_steps",
                "attempts",
                "evidence_validations",
            )
            before = {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in critical_tables
            }
            db.init_schema(conn)
            db.init_schema(conn)
            after = {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in critical_tables
            }
            self.assertEqual(before, after)
            self.assertEqual("ok", conn.execute("pragma integrity_check").fetchone()[0])
            self.assertEqual([], conn.execute("pragma foreign_key_check").fetchall())
            self.assertIn("answer_contracts", self._table_names(conn))
            self.assertIn("attempt_assessments", self._table_names(conn))
        finally:
            conn.close()

    def test_partial_unique_indexes_reject_second_active_and_accepted_rows(self):
        conn = self._copy_pre_v51_backup("partial-unique-enforcement.sqlite")
        try:
            db.init_schema(conn)
            question = self._first_questions(conn, 1)[0]
            self._insert_contract(
                conn,
                row_id="AC-active-1",
                stable_contract_id="AC-active-stable-1",
                contract_version=1,
                question_id=question["id"],
                item_version=question["item_version"],
                status="active",
                digest="1" * 64,
            )
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_contract(
                    conn,
                    row_id="AC-active-2",
                    stable_contract_id="AC-active-stable-2",
                    contract_version=2,
                    question_id=question["id"],
                    item_version=question["item_version"],
                    status="active",
                    digest="2" * 64,
                )
            conn.rollback()

            attempt = conn.execute("select id, attempt_version from attempts limit 1").fetchone()
            self.assertIsNotNone(attempt)
            assessment_base = {
                "attempt_id": attempt["id"],
                "attempt_version": attempt["attempt_version"],
                "answer_contract_id": "AC-active-1",
                "answer_contract_version": 1,
                "answer_contract_digest_sha256": "1" * 64,
                "status": "accepted",
            }
            self._insert_minimal_row(
                conn,
                "attempt_assessments",
                {"id": "AS-accepted-1", "assessment_version": 1, **assessment_base},
            )
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_minimal_row(
                    conn,
                    "attempt_assessments",
                    {"id": "AS-accepted-2", "assessment_version": 2, **assessment_base},
                )
        finally:
            conn.close()


class AnswerContractReviewUnitTests(unittest.TestCase):
    PROVIDER_SCOPE = "recorded_oracle"
    ITEM_VERSION = "2026-07-08.bank.v11"

    def _review_module(self):
        return importlib.import_module("learning_system.answer_contract_review")

    def _fingerprint_module(self):
        return importlib.import_module("learning_system.question_fingerprints")

    def _item(self, index, *, node_id="M-G7-NUMBER-LINE", question_id=None):
        question_id = question_id or f"QB11-{node_id}-{index:02d}"
        return {
            "review_item_handle": f"review-item-{index:02d}",
            "question_id": question_id,
            "item_version": self.ITEM_VERSION,
            "question_digest_sha256": f"{index + 1:064x}",
            "contract_id": f"AC-{question_id}",
            "contract_version": 1,
            "contract_digest_sha256": f"{index + 1001:064x}",
            "node_id": node_id,
            "kind": "standard_example",
            "evidence_role": "direct",
        }

    def _review_result(
        self,
        item,
        *,
        question_correctness="pass",
        node_alignment="aligned",
        evidence_alignment="aligned",
        contract_verdict="approved",
    ):
        contract_rejected = contract_verdict != "approved"
        return {
            "item_handle": item["review_item_handle"],
            "question_correctness": {
                "verdict": question_correctness,
                "independent_solution": "Independent mathematical solution.",
                "rationale": "The expected answer follows from the stated relations.",
            },
            "question_node_alignment": {
                "verdict": node_alignment,
                "actual_mathematical_core": "Number-line position and order.",
                "tested_node_evidence": "The child must use movement and ordering.",
                "rationale": "The mathematical core is compared with the bound node.",
                "advisory_candidate_node": None,
            },
            "evidence_role_alignment": {
                "verdict": evidence_alignment,
                "actual_evidence_demand": "Direct relation, value, and order evidence.",
                "rationale": "The prompt elicits the declared evidence role.",
            },
            "answer_contract_review": {
                "verdict": contract_verdict,
                "reference_solution_correct": not contract_rejected,
                "criteria_atomic_and_observable": True,
                "weights_and_dimensions_valid": True,
                "required_for_pass_valid": True,
                "corrections": (
                    []
                    if not contract_rejected
                    else ["Regenerate the answer-contract draft without changing the question."]
                ),
            },
            "normalized_instance_descriptor": {
                "relations": ["C=A+3", "A<C<B"],
                "values": [
                    {"name": "A", "value": -2.5},
                    {"name": "step", "value": 3},
                ],
                "requested": ["C", "ascending_order"],
            },
            "normalized_core_structure_descriptor": {
                "relation": "directed_translation_then_order",
                "evidence": ["relation", "value", "order"],
            },
            "confidence": 0.99,
        }

    def _recorded_shards_and_receipts(self, review):
        items = [self._item(index) for index in range(20)]
        shards = review.plan_review_shards(items)
        receipts = []
        for shard in shards:
            validated = self._bind_and_validate(
                review,
                shard["items"],
                [self._review_result(item) for item in shard["items"]],
                provider_mode=self.PROVIDER_SCOPE,
            )
            receipts.append(
                review.build_shard_receipt(
                    shard,
                    validated,
                    provider_mode=self.PROVIDER_SCOPE,
                )
            )
        return shards, receipts

    def _bind_semantic_results(self, review, expected_items, semantic_results):
        return review.bind_semantic_review_results(
            expected_items,
            semantic_results,
            item_handles=[item["review_item_handle"] for item in expected_items],
        )

    def _bind_and_validate(
        self,
        review,
        expected_items,
        semantic_results,
        *,
        provider_mode,
        minimum_confidence=0.8,
    ):
        bound = self._bind_semantic_results(
            review,
            expected_items,
            semantic_results,
        )
        return review.validate_review_items(
            expected_items,
            bound,
            provider_mode=provider_mode,
            minimum_confidence=minimum_confidence,
        )

    def _assert_rejected_or_none(self, operation):
        try:
            result = operation()
        except (TypeError, ValueError):
            return
        self.assertIsNone(result)

    def test_five_item_shard_order_and_digest_are_stable(self):
        review = self._review_module()
        items = [self._item(index) for index in range(5)]

        first = review.plan_review_shards(list(reversed(items)))
        second = review.plan_review_shards(copy.deepcopy(items))

        self.assertEqual(1, len(first))
        self.assertEqual(first, second)
        shard = first[0]
        self.assertEqual("M-G7-NUMBER-LINE", shard["node_id"])
        self.assertEqual(
            sorted(item["question_id"] for item in items),
            [item["question_id"] for item in shard["items"]],
        )
        self.assertEqual(5, len(shard["items"]))
        self.assertRegex(shard["shard_digest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            shard["shard_digest_sha256"],
            review.shard_digest(copy.deepcopy(shard["items"])),
        )

    def test_review_item_schema_and_validator_are_exact_and_fail_closed(self):
        review = self._review_module()
        item = self._item(0)
        result = self._review_result(item)

        validated = self._bind_and_validate(
            review,
            [item],
            [result],
            provider_mode=self.PROVIDER_SCOPE,
        )
        self.assertEqual(1, len(validated))
        self.assertEqual("approved", validated[0]["review_status"])
        self.assertFalse(validated[0]["activation_eligible"])
        self.assertEqual(self.PROVIDER_SCOPE, validated[0]["provider_mode"])
        for field in (
            "question_id",
            "item_version",
            "question_digest_sha256",
            "contract_id",
            "contract_version",
            "contract_digest_sha256",
        ):
            self.assertNotIn(field, result)
            self.assertEqual(item[field], validated[0][field])

        invalid_cases = {}
        missing_field = copy.deepcopy(result)
        missing_field.pop("normalized_core_structure_descriptor")
        invalid_cases["missing field"] = [missing_field]

        unknown_field = copy.deepcopy(result)
        unknown_field["unexpected_reviewer_claim"] = True
        invalid_cases["unknown field"] = [unknown_field]

        model_authored_hash = copy.deepcopy(result)
        model_authored_hash["prompt_instance_fingerprint"] = "f" * 64
        invalid_cases["model-authored fingerprint"] = [model_authored_hash]

        invalid_enum = copy.deepcopy(result)
        invalid_enum["question_node_alignment"]["verdict"] = "ambiguous"
        invalid_cases["invalid enum"] = [invalid_enum]

        unknown_item = copy.deepcopy(result)
        unknown_item["item_handle"] = "review-item-unknown"
        invalid_cases["unknown item handle"] = [unknown_item]

        invalid_cases["missing item"] = []
        invalid_cases["duplicate item"] = [result, copy.deepcopy(result)]

        for label, candidate_results in invalid_cases.items():
            with self.subTest(label=label):
                with self.assertRaises((TypeError, ValueError)):
                    self._bind_and_validate(
                        review,
                        [item],
                        candidate_results,
                        provider_mode=self.PROVIDER_SCOPE,
                    )

        second = self._item(1)
        with self.assertRaises((TypeError, ValueError)):
            self._bind_semantic_results(
                review,
                [item, second],
                [self._review_result(second), self._review_result(item)],
            )

    def test_known_semantic_misbindings_are_rejected_and_routed_to_repair(self):
        review = self._review_module()
        fixtures = (
            self._item(
                18,
                node_id="M-G7-NUMBER-LINE",
                question_id="QB11-M-G7-NUMBER-LINE-19",
            ),
            self._item(
                8,
                node_id="M-G7-RATIONAL-ADD-SUB",
                question_id="QB11-M-G7-RATIONAL-ADD-SUB-09",
            ),
        )
        outputs = []
        for item in fixtures:
            output = self._review_result(
                item,
                node_alignment="misbound",
                contract_verdict="rejected",
            )
            output["question_node_alignment"].update(
                actual_mathematical_core=(
                    "Two-dimensional table row/column pattern"
                    if item["question_id"].endswith("NUMBER-LINE-19")
                    else "One-variable equation from pen and notebook prices"
                ),
                tested_node_evidence="The bound node is not actually tested.",
                advisory_candidate_node="question-bank-repair-required",
            )
            outputs.append(output)

        validated = self._bind_and_validate(
            review,
            list(fixtures),
            outputs,
            provider_mode=self.PROVIDER_SCOPE,
        )

        self.assertEqual(2, len(validated))
        for expected, outcome in zip(fixtures, validated):
            self.assertEqual(expected["question_id"], outcome["question_id"])
            self.assertEqual(expected["node_id"], outcome["bound_node_id"])
            self.assertEqual("rejected", outcome["review_status"])
            self.assertTrue(outcome["repair_required"])
            self.assertIn("repair_route", outcome)
            self.assertEqual(
                {
                    "owner": "question_bank",
                    "action": "new_immutable_question_version",
                    "reason_code": "question_node_misalignment",
                    "preserve_bound_node": True,
                },
                outcome["repair_route"],
            )
            self.assertFalse(outcome["activation_eligible"])
            self.assertNotIn("replacement_question", outcome)
            self.assertNotIn("rebound_node_id", outcome)

    def test_contract_only_rejection_has_distinct_repair_route(self):
        review = self._review_module()
        item = self._item(0)
        result = self._review_result(item, contract_verdict="rejected")

        outcome = self._bind_and_validate(
            review,
            [item],
            [result],
            provider_mode=self.PROVIDER_SCOPE,
        )[0]

        self.assertEqual("rejected", outcome["review_status"])
        self.assertIn("repair_route", outcome)
        self.assertEqual(
            {
                "owner": "answer_contract",
                "action": "regenerate_contract_draft",
                "reason_code": "answer_contract_rejected",
                "preserve_bound_node": True,
            },
            outcome["repair_route"],
        )
        self.assertNotEqual(
            "question_node_misalignment",
            outcome["repair_route"]["reason_code"],
        )
        self.assertNotEqual(
            "new_immutable_question_version",
            outcome["repair_route"]["action"],
        )

    def test_shard_receipt_revalidates_tampering_and_derives_all_aggregates(self):
        review = self._review_module()
        items = [self._item(index) for index in range(5)]
        shard = review.plan_review_shards(items)[0]
        validated = self._bind_and_validate(
            review,
            shard["items"],
            [self._review_result(item) for item in shard["items"]],
            provider_mode=self.PROVIDER_SCOPE,
        )
        expected_question_ids = [item["question_id"] for item in shard["items"]]

        receipt = review.build_shard_receipt(
            shard,
            validated,
            provider_mode=self.PROVIDER_SCOPE,
        )
        self.assertEqual(expected_question_ids, receipt["question_ids"])
        self.assertEqual(5, receipt["item_count"])
        expected_counts = {
            "approved_count": 5,
            "rejected_count": 0,
            "repair_required_count": 0,
        }
        for field, expected in expected_counts.items():
            self.assertEqual(expected, receipt[field])
        self.assertEqual(self.PROVIDER_SCOPE, receipt["provider_mode"])
        self.assertFalse(receipt["activation_eligible"])
        self.assertRegex(receipt["receipt_digest_sha256"], r"^[0-9a-f]{64}$")

        tamper_cases = []
        for field, value in (
            ("activation_eligible", True),
            ("review_status", "rejected"),
            ("provider_mode", "live_model"),
            ("question_digest_sha256", "f" * 64),
        ):
            tampered = copy.deepcopy(validated)
            tampered[0][field] = value
            tamper_cases.append((field, tampered))

        for label, tampered in tamper_cases:
            with self.subTest(label=label):
                try:
                    rebuilt = review.build_shard_receipt(
                        shard,
                        tampered,
                        provider_mode=self.PROVIDER_SCOPE,
                    )
                except (TypeError, ValueError):
                    continue
                self.assertEqual(expected_question_ids, rebuilt["question_ids"])
                self.assertEqual(5, rebuilt["item_count"])
                for field, expected in expected_counts.items():
                    self.assertEqual(expected, rebuilt[field])
                self.assertEqual(self.PROVIDER_SCOPE, rebuilt["provider_mode"])
                self.assertFalse(rebuilt["activation_eligible"])
                self.assertEqual(
                    receipt["receipt_digest_sha256"],
                    rebuilt["receipt_digest_sha256"],
                )

    def test_node_receipt_rejects_tampered_or_duplicate_shard_receipts(self):
        review = self._review_module()
        shards, receipts = self._recorded_shards_and_receipts(review)
        self.assertEqual(4, len(shards))

        tamper_cases = []
        field_mutations = (
            ("question_ids", receipts[0]["question_ids"][:-1]),
            ("item_count", 4),
            ("counts", {"approved": 4, "rejected": 0, "pending": 0}),
            ("activation_eligible", True),
            ("receipt_digest_sha256", "0" * 64),
            ("provider_mode", "live_model"),
        )
        for field, value in field_mutations:
            tampered = copy.deepcopy(receipts)
            tampered[0][field] = value
            tamper_cases.append((field, tampered))

        duplicate_digest = copy.deepcopy(receipts)
        duplicate_digest[1]["receipt_digest_sha256"] = duplicate_digest[0][
            "receipt_digest_sha256"
        ]
        tamper_cases.append(("duplicate receipt digest", duplicate_digest))

        for label, candidate_receipts in tamper_cases:
            with self.subTest(label=label):
                self._assert_rejected_or_none(
                    lambda candidate_receipts=candidate_receipts: review.build_node_receipt(
                        "M-G7-NUMBER-LINE",
                        expected_shards=shards,
                        shard_receipts=candidate_receipts,
                    )
                )

    def test_descriptor_schema_is_exact_nested_and_fingerprints_are_local(self):
        review = self._review_module()
        fingerprints = self._fingerprint_module()
        item = self._item(0)
        result = self._review_result(item)

        outcome = self._bind_and_validate(
            review,
            [item],
            [result],
            provider_mode=self.PROVIDER_SCOPE,
        )[0]
        expected_pair = fingerprints.fingerprint_pair(
            result["normalized_instance_descriptor"],
            result["normalized_core_structure_descriptor"],
            policy_version=fingerprints.FINGERPRINT_POLICY_VERSION,
        )
        for field, expected in expected_pair.items():
            self.assertEqual(expected, outcome[field])

        invalid_descriptors = []
        unknown_instance = copy.deepcopy(result)
        unknown_instance["normalized_instance_descriptor"]["notes"] = "not approved"
        invalid_descriptors.append(("unknown instance field", unknown_instance))

        unknown_core = copy.deepcopy(result)
        unknown_core["normalized_core_structure_descriptor"]["metadata"] = {}
        invalid_descriptors.append(("unknown core field", unknown_core))

        nested_unknown = copy.deepcopy(result)
        nested_unknown["normalized_instance_descriptor"]["values"][0]["value"] = {
            "raw": -2.5
        }
        invalid_descriptors.append(("unknown nested value shape", nested_unknown))

        invalid_evidence = copy.deepcopy(result)
        invalid_evidence["normalized_core_structure_descriptor"]["evidence"] = [
            {"name": "relation"}
        ]
        invalid_descriptors.append(("unknown nested evidence shape", invalid_evidence))

        for forbidden_name in (
            "answerHash",
            "FingerprintOverride",
            "sourceDIGEST",
        ):
            forbidden = copy.deepcopy(result)
            forbidden["normalized_instance_descriptor"]["values"].append(
                {"name": forbidden_name, "value": "x"}
            )
            invalid_descriptors.append((forbidden_name, forbidden))

        for label, candidate in invalid_descriptors:
            with self.subTest(label=label):
                with self.assertRaises((TypeError, ValueError)):
                    self._bind_and_validate(
                        review,
                        [item],
                        [candidate],
                        provider_mode=self.PROVIDER_SCOPE,
                    )

    def test_activation_eligibility_is_derived_only_from_live_exact_approval(self):
        review = self._review_module()
        item = self._item(0)
        approved = self._review_result(item)

        recorded = self._bind_and_validate(
            review,
            [item],
            [approved],
            provider_mode=self.PROVIDER_SCOPE,
        )[0]
        live = self._bind_and_validate(
            review,
            [item],
            [approved],
            provider_mode="live_model",
        )[0]
        self.assertFalse(recorded["activation_eligible"])
        self.assertTrue(live["activation_eligible"])

        supplied_eligibility = copy.deepcopy(approved)
        supplied_eligibility["activation_eligible"] = True
        with self.assertRaises((TypeError, ValueError)):
            self._bind_and_validate(
                review,
                [item],
                [supplied_eligibility],
                provider_mode=self.PROVIDER_SCOPE,
            )

        ineligible_variants = (
            {"question_correctness": "fail"},
            {"node_alignment": "unclear"},
            {"evidence_alignment": "misaligned"},
            {"contract_verdict": "rejected"},
        )
        for overrides in ineligible_variants:
            with self.subTest(overrides=overrides):
                candidate = self._review_result(item, **overrides)
                outcome = self._bind_and_validate(
                    review,
                    [item],
                    [candidate],
                    provider_mode="live_model",
                )[0]
                self.assertFalse(outcome["activation_eligible"])

        for forbidden_lineage_field, value in (
            ("question_id", item["question_id"]),
            ("item_version", item["item_version"]),
            ("question_digest_sha256", item["question_digest_sha256"]),
            ("contract_id", item["contract_id"]),
            ("contract_version", item["contract_version"]),
            ("contract_digest_sha256", item["contract_digest_sha256"]),
            ("shard_digest_sha256", "f" * 64),
            ("activation_eligible", True),
        ):
            with self.subTest(forbidden_lineage_field=forbidden_lineage_field):
                forged_lineage = self._review_result(item)
                forged_lineage[forbidden_lineage_field] = value
                with self.assertRaises((TypeError, ValueError)):
                    self._bind_and_validate(
                        review,
                        [item],
                        [forged_lineage],
                        provider_mode="live_model",
                    )

    def test_fingerprint_pair_is_deterministic_versioned_and_separates_instance(self):
        fingerprints = self._fingerprint_module()
        instance = {
            "relations": ["C=A+3", "A<C<B"],
            "values": [
                {"name": "step", "value": 3},
                {"name": "A", "value": -2.5},
            ],
            "requested": ["C", "ascending_order"],
        }
        same_instance_different_key_order = {
            "requested": ["C", "ascending_order"],
            "values": [
                {"value": -2.5, "name": "A"},
                {"value": 3, "name": "step"},
            ],
            "relations": ["C=A+3", "A<C<B"],
        }
        changed_instance = copy.deepcopy(instance)
        changed_instance["values"][1]["value"] = -1.5
        core = {
            "evidence": ["relation", "value", "order"],
            "relation": "directed_translation_then_order",
        }
        version = fingerprints.FINGERPRINT_POLICY_VERSION

        first = fingerprints.fingerprint_pair(instance, core, policy_version=version)
        retry = fingerprints.fingerprint_pair(
            same_instance_different_key_order,
            copy.deepcopy(core),
            policy_version=version,
        )
        changed = fingerprints.fingerprint_pair(
            changed_instance,
            core,
            policy_version=version,
        )

        self.assertEqual(first, retry)
        self.assertEqual(version, first["fingerprint_policy_version"])
        self.assertRegex(first["prompt_instance_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertRegex(first["core_structure_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            first["prompt_instance_fingerprint"],
            changed["prompt_instance_fingerprint"],
        )
        self.assertEqual(
            first["core_structure_fingerprint"],
            changed["core_structure_fingerprint"],
        )

    def test_partial_shard_receipts_cannot_complete_node(self):
        review = self._review_module()
        items = [self._item(index) for index in range(20)]
        shards = review.plan_review_shards(items)
        self.assertEqual(4, len(shards))

        receipts = []
        for shard in shards:
            results = [self._review_result(item) for item in shard["items"]]
            validated = self._bind_and_validate(
                review,
                shard["items"],
                results,
                provider_mode=self.PROVIDER_SCOPE,
            )
            receipts.append(
                review.build_shard_receipt(
                    shard,
                    validated,
                    provider_mode=self.PROVIDER_SCOPE,
                )
            )

        self.assertIsNone(
            review.build_node_receipt(
                "M-G7-NUMBER-LINE",
                expected_shards=shards,
                shard_receipts=receipts[:3],
            )
        )
        complete = review.build_node_receipt(
            "M-G7-NUMBER-LINE",
            expected_shards=shards,
            shard_receipts=receipts,
        )
        self.assertEqual("complete", complete["status"])
        self.assertEqual(20, complete["item_count"])
        self.assertEqual(self.PROVIDER_SCOPE, complete["provider_mode"])
        self.assertFalse(complete["activation_eligible"])


class AnswerContractAgentArtifactTests(unittest.TestCase):
    CONTRACT_PATH = (
        PROJECT_ROOT
        / "learning_system/agent_contracts/answer_contract_review.v1.json"
    )
    PROMPT_PATH = (
        PROJECT_ROOT
        / "learning_system/prompts/answer_contract_review.v1.md"
    )

    def _contract(self):
        self.assertTrue(self.CONTRACT_PATH.is_file(), self.CONTRACT_PATH)
        return json.loads(self.CONTRACT_PATH.read_text(encoding="utf-8"))

    def _assert_exact_object_schema(self, schema, required):
        self.assertEqual("object", schema["type"])
        self.assertIs(False, schema["additionalProperties"])
        self.assertEqual(set(required), set(schema["required"]))
        self.assertEqual(set(required), set(schema["properties"]))

    def _recorded_output(self, contract):
        unit = AnswerContractReviewUnitTests()
        item = unit._item(0)
        result = unit._review_result(item)
        schema_version = contract["response_schema"]["properties"]["schema_version"][
            "const"
        ]
        return item, {
            "schema_version": schema_version,
            "items": [result],
        }

    def _bind_recorded_items(self, item, semantic_items):
        from learning_system import answer_contract_review

        return answer_contract_review.bind_semantic_review_results(
            [item],
            semantic_items,
            item_handles=[item["review_item_handle"]],
        )

    def _call_recorded(
        self,
        output,
        *,
        trusted_context=None,
        untrusted_payload=None,
        source_refs=None,
        agent_key="answer_contract_reviewer_agent",
        phase="answer_contract_review",
        provider_mode="recorded_model",
    ):
        from learning_system import semantic_agents

        caller = getattr(
            semantic_agents,
            "call_answer_contract_reviewer_agent",
        )
        return caller(
            semantic_agents.SemanticAgentRequest(
                agent_key=agent_key,
                phase=phase,
                trusted_context=trusted_context or {},
                untrusted_payload=untrusted_payload or {},
                source_refs=source_refs or {},
                provider_mode=provider_mode,
            )
        )

    def _assert_recorded_request_rejected(self, operation):
        try:
            envelope = operation()
        except (KeyError, TypeError, ValueError):
            return
        self.assertNotEqual("accepted", envelope.status)

    def test_internal_agent_registry_maps_reviewer_to_v1_contract(self):
        from learning_system import internal_agents

        self.assertIn(
            "answer_contract_reviewer_agent",
            internal_agents.INTERNAL_AGENT_ROLES,
        )
        role = internal_agents.INTERNAL_AGENT_ROLES[
            "answer_contract_reviewer_agent"
        ]
        self.assertEqual("answer_contract_review", role["v5_contract_key"])
        self.assertEqual("v1", role["v5_contract_version_suffix"])
        contract = internal_agents.load_v5_contract_for_agent(
            "answer_contract_reviewer_agent"
        )
        self.assertEqual("answer_contract_reviewer_agent", contract["agent_key"])
        self.assertEqual("answer_contract_review", contract["contract_key"])
        self.assertEqual(self.CONTRACT_PATH, internal_agents.contract_path(
            "answer_contract_review", version_suffix="v1"
        ))

    def test_agent_contract_has_exact_max_five_review_item_schema(self):
        contract = self._contract()
        self.assertEqual("answer_contract_reviewer_agent", contract["agent_key"])
        self.assertEqual("answer_contract_review", contract["contract_key"])
        self.assertEqual(
            "learning_system/prompts/answer_contract_review.v1.md",
            contract["prompt_template_path"],
        )

        response = contract["response_schema"]
        self._assert_exact_object_schema(response, {"schema_version", "items"})
        items = response["properties"]["items"]
        self.assertEqual("array", items["type"])
        self.assertEqual(1, items["minItems"])
        self.assertEqual(5, items["maxItems"])

        item_required = {
            "item_handle",
            "question_correctness",
            "question_node_alignment",
            "evidence_role_alignment",
            "answer_contract_review",
            "normalized_instance_descriptor",
            "normalized_core_structure_descriptor",
            "confidence",
        }
        item_schema = items["items"]
        self._assert_exact_object_schema(item_schema, item_required)
        properties = item_schema["properties"]
        self.assertEqual("string", properties["item_handle"]["type"])
        self.assertGreaterEqual(properties["item_handle"].get("minLength", 0), 1)
        forbidden_authority = {
            "question_id",
            "item_version",
            "question_digest_sha256",
            "contract_id",
            "contract_version",
            "contract_digest_sha256",
            "shard_digest_sha256",
            "review_record_id",
            "agent_run_id",
            "provider_mode",
            "activation_eligible",
            "prompt_instance_fingerprint",
            "core_structure_fingerprint",
            "receipt_digest_sha256",
        }
        self.assertTrue(forbidden_authority.isdisjoint(properties))
        self.assertEqual(
            {"pass", "fail"},
            set(properties["question_correctness"]["properties"]["verdict"]["enum"]),
        )
        self.assertEqual(
            {"aligned", "misbound", "unclear"},
            set(properties["question_node_alignment"]["properties"]["verdict"]["enum"]),
        )
        self.assertEqual(
            {"aligned", "misaligned", "unclear"},
            set(properties["evidence_role_alignment"]["properties"]["verdict"]["enum"]),
        )
        self.assertEqual(
            {"approved", "rejected"},
            set(properties["answer_contract_review"]["properties"]["verdict"]["enum"]),
        )

        instance = properties["normalized_instance_descriptor"]
        core = properties["normalized_core_structure_descriptor"]
        self._assert_exact_object_schema(instance, {"relations", "values", "requested"})
        self._assert_exact_object_schema(core, {"relation", "evidence"})
        values = instance["properties"]["values"]
        self.assertEqual("array", values["type"])
        self._assert_exact_object_schema(values["items"], {"name", "value"})
        descriptor_text = json.dumps(
            {"instance": instance, "core": core},
            ensure_ascii=False,
        ).lower()
        for model_hash_field in (
            "prompt_instance_fingerprint",
            "core_structure_fingerprint",
            "receipt_digest_sha256",
        ):
            self.assertNotIn(f'"{model_hash_field}"', descriptor_text)

    def test_prompt_requires_independent_semantic_review_and_json_only(self):
        self.assertTrue(self.PROMPT_PATH.is_file(), self.PROMPT_PATH)
        prompt = self.PROMPT_PATH.read_text(encoding="utf-8")
        lowered = prompt.lower()
        required_concepts = (
            ("independent solve", "独立求解", "独立解题"),
            ("node essence", "节点本质"),
            ("question-generation contract", "命题合同"),
            ("evidence role", "证据角色"),
            ("do not edit", "不可修改题目", "不得修改题目"),
            ("rebind", "重绑"),
            ("do not provide hash", "不得提供hash", "不可输出hash", "不得输出指纹"),
            ("item_handle", "opaque item handle", "不透明条目句柄"),
            ("fixed order", "same order", "保持顺序", "按输入顺序"),
            ("question ids", "不得输出question_id", "不要返回question_id"),
            ("contract ids", "不得输出contract_id", "不要返回contract_id"),
            ("digest fields", "不得输出digest", "不要返回digest"),
            ("activation decisions", "不得输出激活", "不要返回activation"),
            ("at most 5", "<=5", "不超过5题", "最多5题"),
            ("json only", "only json", "只返回json", "仅返回json"),
        )
        for alternatives in required_concepts:
            with self.subTest(concept=alternatives[0]):
                self.assertTrue(
                    any(phrase in lowered for phrase in alternatives),
                    alternatives,
                )

    def test_semantic_agent_accepts_recorded_fixture_but_never_marks_it_eligible(self):
        from learning_system import answer_contract_review, semantic_agents

        contract = self._contract()
        item, output = self._recorded_output(contract)
        caller = getattr(
            semantic_agents,
            "call_answer_contract_reviewer_agent",
        )
        envelope = caller(
            semantic_agents.SemanticAgentRequest(
                agent_key="answer_contract_reviewer_agent",
                phase="answer_contract_review",
                trusted_context={
                    "recorded_agent_output": output,
                    "recorded_fixture_id": "answer-contract-review-unit-v1",
                },
                untrusted_payload={},
                provider_mode="recorded_model",
            )
        )
        self.assertEqual("accepted", envelope.status)
        self.assertEqual("recorded_model", envelope.provider_mode)
        self.assertEqual("recorded_agent_output", envelope.route_meta["source"])
        validated = answer_contract_review.validate_review_items(
            [item],
            self._bind_recorded_items(item, envelope.output["items"]),
            provider_mode=envelope.provider_mode,
        )
        self.assertEqual(1, len(validated))
        self.assertFalse(validated[0]["activation_eligible"])

    def test_recorded_fixture_requires_trusted_lineage_and_exact_route_identity(self):
        contract = self._contract()
        item, output = self._recorded_output(contract)
        fixture_id = "answer-contract-review-trusted-v1"

        self._assert_recorded_request_rejected(
            lambda: self._call_recorded(
                output,
                untrusted_payload={
                    "recorded_agent_output": output,
                    "recorded_fixture_id": fixture_id,
                },
            )
        )

        trusted = self._call_recorded(
            output,
            trusted_context={
                "recorded_agent_output": output,
                "recorded_fixture_id": fixture_id,
            },
        )
        sourced = self._call_recorded(
            output,
            source_refs={
                "recorded_agent_output": output,
                "recorded_fixture_id": fixture_id,
            },
        )
        for envelope in (trusted, sourced):
            self.assertEqual("accepted", envelope.status)
            self.assertEqual("recorded_model", envelope.provider_mode)

        self._assert_recorded_request_rejected(
            lambda: self._call_recorded(
                output,
                trusted_context={
                    "recorded_agent_output": output,
                    "recorded_fixture_id": fixture_id,
                },
                agent_key="answer_analysis_agent",
            )
        )
        self._assert_recorded_request_rejected(
            lambda: self._call_recorded(
                output,
                trusted_context={
                    "recorded_agent_output": output,
                    "recorded_fixture_id": fixture_id,
                },
                phase="answer_analysis",
            )
        )

        from learning_system import answer_contract_review

        validated = answer_contract_review.validate_review_items(
            [item],
            self._bind_recorded_items(item, trusted.output["items"]),
            provider_mode=trusted.provider_mode,
        )
        self.assertFalse(validated[0]["activation_eligible"])

    def test_recorded_agent_enforces_min_length_and_local_descriptor_names(self):
        contract = self._contract()
        _, valid_output = self._recorded_output(contract)
        invalid_outputs = []

        empty_handle = copy.deepcopy(valid_output)
        empty_handle["items"][0]["item_handle"] = ""
        invalid_outputs.append(("item-handle-minLength", empty_handle))

        for forbidden_field, value in (
            ("question_id", "QB11-M-G7-NUMBER-LINE-01"),
            ("question_digest_sha256", "a" * 64),
            ("contract_id", "AC-forged"),
            ("contract_digest_sha256", "b" * 64),
            ("shard_digest_sha256", "c" * 64),
            ("activation_eligible", True),
        ):
            forbidden = copy.deepcopy(valid_output)
            forbidden["items"][0][forbidden_field] = value
            invalid_outputs.append((f"forbidden-lineage:{forbidden_field}", forbidden))

        for forbidden_key in (
            "answerHash",
            "FingerprintOverride",
            "sourceDIGEST",
        ):
            forbidden = copy.deepcopy(valid_output)
            forbidden["items"][0]["normalized_instance_descriptor"]["values"].append(
                {"name": forbidden_key, "value": "model-authored"}
            )
            invalid_outputs.append((f"descriptor-name:{forbidden_key}", forbidden))

        for label, output in invalid_outputs:
            with self.subTest(label=label):
                with self.assertRaises((TypeError, ValueError)):
                    self._call_recorded(
                        output,
                        trusted_context={
                            "recorded_agent_output": output,
                            "recorded_fixture_id": f"invalid-{label}",
                        },
                    )

    def test_minimum_confidence_blocks_recorded_and_live_activation_eligibility(self):
        from learning_system import answer_contract_review

        contract = self._contract()
        self.assertEqual(0.8, contract["minimum_confidence_to_apply"])
        item, output = self._recorded_output(contract)
        output["items"][0]["confidence"] = 0.79
        envelope = self._call_recorded(
            output,
            trusted_context={
                "recorded_agent_output": output,
                "recorded_fixture_id": "low-confidence-recorded-v1",
            },
        )
        self.assertEqual("accepted", envelope.status)

        for provider_mode in (envelope.provider_mode, "live_model"):
            with self.subTest(provider_mode=provider_mode):
                outcome = answer_contract_review.validate_review_items(
                    [item],
                    self._bind_recorded_items(item, envelope.output["items"]),
                    provider_mode=provider_mode,
                    minimum_confidence=contract["minimum_confidence_to_apply"],
                )[0]
                self.assertFalse(outcome["activation_eligible"])
                self.assertTrue(
                    outcome.get("needs_retry")
                    or outcome.get("review_status") == "rejected"
                    or "low_confidence" in set(outcome.get("blockers") or []),
                    outcome,
                )

    def test_prompt_path_rejects_absolute_traversal_symlink_and_missing_files(self):
        from learning_system import internal_agents

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "project"
            prompt_root = root / "learning_system/prompts"
            prompt_root.mkdir(parents=True)
            valid_prompt = prompt_root / "valid.v1.md"
            valid_prompt.write_text("valid prompt", encoding="utf-8")
            outside = Path(temp_name) / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            symlink = prompt_root / "escape.v1.md"
            symlink.symlink_to(outside)

            with mock.patch.object(internal_agents, "PROJECT_ROOT", root), mock.patch.object(
                internal_agents, "PROMPT_ROOT", prompt_root
            ):
                valid = internal_agents.prompt_path_for_contract(
                    {
                        "prompt_template_path": (
                            "learning_system/prompts/valid.v1.md"
                        )
                    }
                )
                self.assertEqual("valid prompt", valid.read_text(encoding="utf-8"))

                invalid_paths = (
                    str(outside),
                    "learning_system/prompts/../../outside.md",
                    "learning_system/prompts/escape.v1.md",
                    "learning_system/prompts/missing.v1.md",
                )
                for configured in invalid_paths:
                    with self.subTest(configured=configured):
                        with self.assertRaises((FileNotFoundError, ValueError)):
                            internal_agents.prompt_path_for_contract(
                                {"prompt_template_path": configured}
                            )


class AnswerContractDryRunTests(unittest.TestCase):
    SCRIPT_PATH = PROJECT_ROOT / "scripts/activate_answer_contracts.py"
    STABLE_DIGEST_KEYS = (
        "manifest_digest_sha256",
        "draft_contracts_digest_sha256",
        "shard_plan_digest_sha256",
        "receipt_digest_sha256",
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "answer-contract-dry-run-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-contract-dry-run.sqlite"
        shutil.copy2(self._seed_path, self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _counts(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return {
                "answer_contracts": conn.execute(
                    "select count(*) from answer_contracts"
                ).fetchone()[0],
                "active_contracts": conn.execute(
                    "select count(*) from answer_contracts where status = 'active'"
                ).fetchone()[0],
                "agent_runs": conn.execute(
                    "select count(*) from agent_runs"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def _reset_db(self):
        shutil.copy2(self._seed_path, self.db_path)

    def _mutate_db(self, operation):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            operation(conn)
            conn.commit()
        finally:
            conn.close()

    def _assert_dry_run_rejected(self):
        result, payload = self._run("--dry-run")
        self.assertNotEqual(0, result.returncode, payload)
        self.assertFalse(payload.get("activation_ready", False))
        self.assertEqual(0, self._counts()["active_contracts"])
        return payload

    def _run(self, mode):
        self.assertTrue(self.SCRIPT_PATH.is_file(), self.SCRIPT_PATH)
        result = subprocess.run(
            [
                "python3",
                str(self.SCRIPT_PATH),
                "--db",
                str(self.db_path),
                mode,
                "--json",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        return result, payload

    def test_dry_run_reports_exact_bank_without_semantic_approval_or_writes(self):
        before = self._counts()
        result, report = self._run("--dry-run")
        after = self._counts()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1120, report["active_questions"])
        self.assertEqual(56, report["nodes"])
        self.assertEqual(20, report["kinds"])
        self.assertEqual(1120, report["draft_contracts"])
        self.assertEqual(224, report["shards"])
        self.assertEqual(5, report["max_shard_size"])
        self.assertEqual(1, report["review_concurrency"])
        self.assertEqual(0, report["semantic_approved"])
        self.assertFalse(report["activation_ready"])
        self.assertIn("semantic_review_required", report["blockers"])
        self.assertEqual(0, report["model_calls"])
        self.assertEqual(before, after)
        self.assertEqual(0, after["answer_contracts"])

    def test_repeat_dry_run_has_stable_receipt_and_digests(self):
        first_result, first = self._run("--dry-run")
        second_result, second = self._run("--dry-run")
        self.assertEqual(0, first_result.returncode, first_result.stderr)
        self.assertEqual(0, second_result.returncode, second_result.stderr)

        for key in self.STABLE_DIGEST_KEYS:
            with self.subTest(key=key):
                self.assertRegex(first[key], r"^[0-9a-f]{64}$")
                self.assertEqual(first[key], second[key])
        self.assertEqual(0, self._counts()["answer_contracts"])

    def test_audit_and_activate_without_live_receipts_fail_closed(self):
        before = self._counts()
        audit_result, audit = self._run("--audit")
        activate_result, activate = self._run("--activate")
        after = self._counts()

        self.assertNotEqual(0, audit_result.returncode, audit)
        self.assertNotEqual(0, activate_result.returncode, activate)
        self.assertFalse(audit.get("activation_ready", False))
        self.assertFalse(activate.get("activation_ready", False))
        self.assertEqual(before, after)
        self.assertEqual(0, after["active_contracts"])

    def test_dry_run_reads_unique_active_ledger_instead_of_version_constant(self):
        alternate_version = "2026-07-14.bank.v11-ledger-alternate"

        def switch_ledger(conn):
            conn.execute(
                """
                update question_bank_version_ledger
                set question_bank_version = ?, updated_at = ?
                where status = 'active'
                """,
                (alternate_version, db.now_iso()),
            )

        self._mutate_db(switch_ledger)
        payload = self._assert_dry_run_rejected()
        self.assertEqual(alternate_version, payload["active_bank_version"])

    def test_dry_run_rejects_multiple_active_or_manifest_count_mismatch(self):
        corruption_cases = {
            "multiple active ledger": lambda conn: (
                conn.execute("drop index idx_question_bank_version_ledger_active"),
                conn.execute(
                    """
                    insert into question_bank_version_ledger(
                      id, question_bank_version, graph_version, manifest_id,
                      manifest_sha256, node_count, item_count, status,
                      activated_at, reason, created_at, updated_at
                    ) values (
                      'QBL-corrupt-second-active', 'corrupt.second.active',
                      '2026-07-04.v2', 'corrupt-manifest', ?, 56, 1120,
                      'active', ?, 'corruption fixture', ?, ?
                    )
                    """,
                    ("b" * 64, db.now_iso(), db.now_iso(), db.now_iso()),
                ),
            ),
            "item count mismatch": lambda conn: conn.execute(
                "update question_bank_version_ledger set item_count = 1119 where status = 'active'"
            ),
            "node count mismatch": lambda conn: conn.execute(
                "update question_bank_version_ledger set node_count = 55 where status = 'active'"
            ),
        }

        for label, mutation in corruption_cases.items():
            with self.subTest(label=label):
                self._reset_db()
                self._mutate_db(mutation)
                self._assert_dry_run_rejected()

    def test_dry_run_rejects_invalid_question_review_digest_or_reviewer_lineage(self):
        corruption_cases = {
            "candidate digest mismatch": lambda conn: conn.execute(
                """
                update question_review_records
                set candidate_sha256 = ?
                where id = (
                  select id from question_review_records
                  where review_status = 'approved' and active_eligible = 1
                  order by id limit 1
                )
                """,
                ("f" * 64,),
            ),
            "missing reviewer lineage": lambda conn: conn.execute(
                """
                update question_review_records
                set reviewer_run_id = null
                where id = (
                  select id from question_review_records
                  where review_status = 'approved' and active_eligible = 1
                  order by id limit 1
                )
                """
            ),
        }

        for label, mutation in corruption_cases.items():
            with self.subTest(label=label):
                self._reset_db()
                self._mutate_db(mutation)
                self._assert_dry_run_rejected()


class AnswerContractLiveReviewTests(unittest.TestCase):
    KNOWN_MISBOUND_IDS = {
        "QB11-M-G7-NUMBER-LINE-19",
        "QB11-M-G7-RATIONAL-ADD-SUB-09",
    }

    class RetryableReviewError(RuntimeError):
        retryable = True
        status_code = 503
        retry_after = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "answer-contract-live-review-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
            _persist_stage3_answer_contract_fixtures(
                conn,
                Path(cls._seed_dir.name) / "answer-contract-design-checkpoints",
            )
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-contract-live-review.sqlite"
        self.checkpoint_root = Path(self.tmpdir.name) / "checkpoints"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _activation(self):
        return importlib.import_module("learning_system.answer_contract_activation")

    def _plan(self):
        plan = self._activation().build_review_plan(self.conn, PROJECT_ROOT)
        _assert_persisted_stage3_review_plan(self, plan)
        return plan

    def test_build_review_plan_fails_closed_without_generated_drafts(self):
        activation = self._activation()
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "missing-stage3-drafts.sqlite"
            conn = sqlite3.connect(path)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("pragma foreign_keys = on")
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
                self.assertEqual(
                    0,
                    conn.execute(
                        "select count(*) from answer_contracts "
                        "where status = 'review_pending'"
                    ).fetchone()[0],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "answer.contract|design|draft",
                ):
                    activation.build_review_plan(conn, PROJECT_ROOT)
            finally:
                conn.close()

    def _review_result(self, item):
        return AnswerContractReviewUnitTests()._review_result(item)

    def _fake_reviewer(
        self,
        *,
        provider_mode="live_model",
        failures=None,
        evidence_scope="injected_test_fixture",
        agent_run_id=None,
    ):
        queued_failures = list(failures or [])
        calls = []

        def reviewer(packet):
            calls.append(copy.deepcopy(packet))
            if queued_failures:
                failure = queued_failures.pop(0)
                if failure is not None:
                    raise failure
            return {
                "agent_key": "answer_contract_reviewer_agent",
                "phase": "answer_contract_review",
                "status": "accepted",
                "provider_mode": provider_mode,
                "model_alias": "gpt-5.5",
                "prompt_version_id": packet["prompt_version_id"],
                "response_schema_version": packet["response_schema_version"],
                "route_policy_digest_sha256": packet[
                    "route_policy_digest_sha256"
                ],
                "shard_digest_sha256": packet["shard_digest_sha256"],
                "evidence_scope": evidence_scope,
                "agent_run_id": agent_run_id,
                "output": {
                    "schema_version": packet["response_schema_version"],
                    "items": [
                        self._review_result(item) for item in packet["items"]
                    ],
                },
            }

        reviewer.calls = calls
        return reviewer

    def _insert_exact_reviewer_run(
        self,
        run_id,
        packet,
        output,
        **overrides,
    ):
        rendered_prompt_sha256 = packet.get("rendered_prompt_sha256") or hashlib.sha256(
            json.dumps(
                packet,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        response_schema_sha256 = packet.get(
            "response_schema_sha256"
        ) or packet["response_schema_digest_sha256"]
        values = {
            "id": run_id,
            "agent_key": "answer_contract_reviewer_agent",
            "engine_type": "internal_learning_agent",
            "phase": "answer_contract_review",
            "trigger": "contract_activation_review",
            "input_refs_json": json.dumps(
                {"shard_digest_sha256": packet["shard_digest_sha256"]},
                sort_keys=True,
            ),
            "input_digest_sha256": packet["shard_digest_sha256"],
            "prompt_version_id": packet["prompt_version_id"],
            "prompt_template_sha256": packet["prompt_template_sha256"],
            "rendered_prompt_sha256": rendered_prompt_sha256,
            "model_provider": "openai",
            "model_name": "gpt-5.5",
            "model_alias": "gpt-5.5",
            "model_params_json": json.dumps({"temperature": 0}, sort_keys=True),
            "response_schema_version": packet["response_schema_version"],
            "response_schema_sha256": response_schema_sha256,
            "status": "accepted",
            "confidence": 0.99,
            "output_json": json.dumps(
                output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "output_digest_sha256": hashlib.sha256(
                json.dumps(
                    output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "validation_errors_json": "[]",
            "error_reason": "",
            "created_at": db.now_iso(),
        }
        values.update(overrides)
        columns = tuple(values)
        self.conn.execute(
            f"insert into agent_runs ({', '.join(columns)}) "
            f"values ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        self.conn.commit()

    def _reviewer_with_db_run(self, run_id, *, overrides=None, claimed_scope="forged"):
        calls = []

        def reviewer(packet):
            calls.append(copy.deepcopy(packet))
            output = {
                "schema_version": packet["response_schema_version"],
                "items": [self._review_result(item) for item in packet["items"]],
            }
            self._insert_exact_reviewer_run(
                run_id,
                packet,
                output,
                **dict(overrides or {}),
            )
            return {
                "agent_key": "answer_contract_reviewer_agent",
                "phase": "answer_contract_review",
                "status": "accepted",
                "provider_mode": "live_model",
                "model_alias": "gpt-5.5",
                "prompt_version_id": packet["prompt_version_id"],
                "prompt_template_sha256": packet["prompt_template_sha256"],
                "rendered_prompt_sha256": hashlib.sha256(
                    json.dumps(
                        packet,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "response_schema_version": packet["response_schema_version"],
                "response_schema_sha256": packet.get(
                    "response_schema_sha256"
                ) or packet["response_schema_digest_sha256"],
                "route_policy_digest_sha256": packet[
                    "route_policy_digest_sha256"
                ],
                "shard_digest_sha256": packet["shard_digest_sha256"],
                "evidence_scope": claimed_scope,
                "agent_run_id": run_id,
                "output": output,
            }

        reviewer.calls = calls
        return reviewer

    def _receipt_digest(self, payload):
        canonical = dict(payload)
        claimed = canonical.pop("receipt_digest_sha256")
        calculated = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(calculated, claimed)

    def _first_node(self, plan):
        self.assertTrue(plan["nodes"])
        node = plan["nodes"][0]
        self.assertEqual(20, len(node["items"]))
        self.assertEqual(4, len(node["shards"]))
        self.assertTrue(all(len(shard["items"]) == 5 for shard in node["shards"]))
        return node

    def _active_contract_count(self):
        return self.conn.execute(
            "select count(*) from answer_contracts where status = 'active'"
        ).fetchone()[0]

    def test_real_node_twenty_items_create_four_sealed_shards_and_node_receipt(self):
        activation = self._activation()
        plan = self._plan()
        node = self._first_node(plan)
        reviewer = self._fake_reviewer()

        report = activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            reviewer,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=4,
        )

        self.assertEqual(4, len(reviewer.calls))
        self.assertEqual("injected_test_fixture", report["evidence_scope"])
        self.assertFalse(report["live_semantic_pass"])
        node_dir = (
            self.checkpoint_root / plan["bank_version"] / node["node_id"]
        )
        shard_paths = sorted(node_dir.glob("shard-*.json"))
        self.assertEqual(4, len(shard_paths))
        for path in shard_paths:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(checkpoint["sealed"])
            self.assertEqual("accepted", checkpoint["status"])
            self.assertEqual(
                "answer_contract_reviewer_agent", checkpoint["agent_key"]
            )
            self.assertEqual("answer_contract_review", checkpoint["phase"])
            self.assertEqual("live_model", checkpoint["provider_mode"])
            self.assertEqual("gpt-5.5", checkpoint["model_alias"])
            self.assertEqual(
                plan["prompt_version_id"], checkpoint["prompt_version_id"]
            )
            self.assertEqual(
                plan["response_schema_version"],
                checkpoint["response_schema_version"],
            )
            self.assertEqual(
                plan["route_policy_digest_sha256"],
                checkpoint["route_policy_digest_sha256"],
            )
            self.assertEqual("injected_test_fixture", checkpoint["evidence_scope"])
            self.assertFalse(checkpoint["activation_eligible"])
            self._receipt_digest(checkpoint)

        node_receipt_path = node_dir / "node-receipt.json"
        self.assertTrue(node_receipt_path.is_file())
        node_receipt = json.loads(node_receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(node["node_id"], node_receipt["node_id"])
        self.assertEqual(4, node_receipt["shard_receipt_count"])
        self.assertEqual(20, node_receipt["item_count"])
        self.assertFalse(node_receipt["activation_eligible"])
        self._receipt_digest(node_receipt)

    def test_retryable_first_failure_reuses_shard_digest_then_succeeds(self):
        activation = self._activation()
        plan = self._plan()
        node = self._first_node(plan)
        reviewer = self._fake_reviewer(
            failures=[self.RetryableReviewError("temporary 503"), None]
        )
        sleeps = []

        activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            reviewer,
            self.checkpoint_root,
            sleep_fn=sleeps.append,
            max_shards=1,
        )

        self.assertEqual(2, len(reviewer.calls))
        self.assertEqual(
            reviewer.calls[0]["shard_digest_sha256"],
            reviewer.calls[1]["shard_digest_sha256"],
        )
        self.assertEqual([20], sleeps)
        shard_path = sorted(
            (
                self.checkpoint_root
                / plan["bank_version"]
                / node["node_id"]
            ).glob("shard-*.json")
        )[0]
        checkpoint = json.loads(shard_path.read_text(encoding="utf-8"))
        self.assertEqual(2, checkpoint["attempt_count"])
        self.assertEqual("accepted", checkpoint["status"])
        self.assertEqual(
            node["shards"][0]["shard_digest_sha256"],
            checkpoint["shard_digest_sha256"],
        )

    def test_resume_reuses_valid_live_checkpoints_but_not_recorded_tamper(self):
        activation = self._activation()
        plan = self._plan()
        node = self._first_node(plan)
        first = self._fake_reviewer()
        activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            first,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=4,
        )
        self.assertEqual(4, len(first.calls))

        resume = self._fake_reviewer()
        resumed = activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            resume,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=4,
        )
        self.assertEqual(0, len(resume.calls))
        self.assertEqual(4, resumed["reused_shards"])

        node_dir = (
            self.checkpoint_root / plan["bank_version"] / node["node_id"]
        )
        tampered_path = sorted(node_dir.glob("shard-*.json"))[0]
        tampered = json.loads(tampered_path.read_text(encoding="utf-8"))
        tampered["provider_mode"] = "recorded_model"
        tampered_path.write_text(
            json.dumps(tampered, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

        repair = self._fake_reviewer()
        repaired = activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            repair,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=4,
        )
        self.assertEqual(1, len(repair.calls))
        self.assertEqual(3, repaired["reused_shards"])
        restored = json.loads(tampered_path.read_text(encoding="utf-8"))
        self.assertEqual("live_model", restored["provider_mode"])

    def test_current_v11_known_misbound_oracles_block_activation_and_zero_active(self):
        activation = self._activation()
        plan = self._plan()
        planned_ids = {
            item["question_id"]
            for node in plan["nodes"]
            for item in node["items"]
        }
        if not self.KNOWN_MISBOUND_IDS.issubset(planned_ids):
            self.skipTest("deprecated QB11 oracle fixtures were removed with the obsolete question bank")
        reviewer = self._fake_reviewer()

        report = activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            reviewer,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=None,
        )
        audit = activation.audit_review(self.conn, plan, self.checkpoint_root)

        self.assertEqual(224, len(reviewer.calls))
        self.assertEqual("injected_test_fixture", report["evidence_scope"])
        self.assertFalse(audit["activation_ready"])
        self.assertEqual(
            self.KNOWN_MISBOUND_IDS,
            set(audit["known_misbound_oracles"]),
        )
        self.assertIn("known_misbound_oracle", audit["activation_blockers"])
        self.assertEqual(0, self._active_contract_count())
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            activation.activate_reviewed_contracts(
                self.conn,
                plan,
                self.checkpoint_root,
            )
        self.assertEqual(0, self._active_contract_count())
        self.assertFalse(
            (
                self.checkpoint_root
                / plan["bank_version"]
                / "global-receipt.json"
            ).exists()
        )

    def test_live_scope_is_derived_only_from_exact_authoritative_agent_run(self):
        activation = self._activation()
        plan = self._plan()
        node = self._first_node(plan)

        invalid_claims = [
            ("no agent run", self._fake_reviewer(
                evidence_scope="live_model_call",
                agent_run_id=None,
            )),
            ("missing agent run", self._fake_reviewer(
                evidence_scope="live_model_call",
                agent_run_id="RUN-missing-reviewer",
            )),
        ]
        wrong_run_variants = (
            ("wrong agent", {"agent_key": "question_reviewer_agent"}),
            ("wrong phase", {"phase": "question_review"}),
            ("wrong status", {"status": "succeeded"}),
            ("wrong provider", {"model_provider": "recorded_fixture"}),
            ("wrong model", {"model_name": "gpt-5.4", "model_alias": "gpt-5.4"}),
            ("wrong prompt", {"prompt_version_id": "wrong-prompt"}),
            ("wrong schema", {"response_schema_version": "wrong-schema"}),
            ("wrong input digest", {"input_digest_sha256": "1" * 64}),
            ("wrong output digest", {"output_digest_sha256": "2" * 64}),
        )
        for index, (label, overrides) in enumerate(wrong_run_variants):
            invalid_claims.append((
                label,
                self._reviewer_with_db_run(
                    f"RUN-invalid-reviewer-{index}",
                    overrides=overrides,
                    claimed_scope="live_model_call",
                ),
            ))

        for index, (label, reviewer) in enumerate(invalid_claims):
            with self.subTest(label=label):
                root = self.checkpoint_root / f"invalid-{index}"
                try:
                    activation.run_live_review(
                        self.conn,
                        PROJECT_ROOT,
                        reviewer,
                        root,
                        sleep_fn=lambda _seconds: None,
                        max_shards=1,
                    )
                except (sqlite3.IntegrityError, TypeError, ValueError):
                    continue
                shard_paths = sorted(
                    (root / plan["bank_version"] / node["node_id"]).glob(
                        "shard-*.json"
                    )
                )
                self.assertTrue(shard_paths)
                checkpoint = json.loads(
                    shard_paths[0].read_text(encoding="utf-8")
                )
                self.assertFalse(checkpoint["activation_eligible"])
                self.assertNotEqual(
                    "live_model_call", checkpoint.get("evidence_scope")
                )

        valid_run_id = "RUN-exact-answer-contract-reviewer"
        exact = self._reviewer_with_db_run(
            valid_run_id,
            claimed_scope="injected_test_fixture",
        )
        exact_root = self.checkpoint_root / "exact"
        activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            exact,
            exact_root,
            sleep_fn=lambda _seconds: None,
            max_shards=1,
        )
        exact_path = sorted(
            (exact_root / plan["bank_version"] / node["node_id"]).glob(
                "shard-*.json"
            )
        )[0]
        exact_checkpoint = json.loads(exact_path.read_text(encoding="utf-8"))
        self.assertEqual(valid_run_id, exact_checkpoint["agent_run_id"])
        self.assertEqual("live_model_call", exact_checkpoint["evidence_scope"])
        self.assertTrue(exact_checkpoint["activation_eligible"])

    def test_audit_and_activation_rebuild_plan_authority_from_database(self):
        activation = self._activation()
        plan = self._plan()
        self.assertEqual(56, len(plan["nodes"]))
        self.assertEqual(224, sum(len(node["shards"]) for node in plan["nodes"]))
        for required in (
            "plan_digest_sha256",
            "ledger_id",
            "bank_version",
            "manifest_id",
            "manifest_sha256",
            "route_policy_digest_sha256",
        ):
            self.assertIn(required, plan)

        baseline = activation.audit_review(
            self.conn,
            plan,
            self.checkpoint_root,
        )
        self.assertNotIn(
            "plan_authority_mismatch",
            baseline["activation_blockers"],
        )

        oracle_id = plan["nodes"][0]["items"][0]["question_id"]
        removed_oracle = copy.deepcopy(plan)
        for node in removed_oracle["nodes"]:
            node["items"] = [
                item for item in node["items"] if item["question_id"] != oracle_id
            ]
            for shard in node["shards"]:
                shard["items"] = [
                    item
                    for item in shard["items"]
                    if item["question_id"] != oracle_id
                ]

        removed_node = copy.deepcopy(plan)
        removed_node["nodes"].pop()

        removed_shard = copy.deepcopy(plan)
        removed_shard["nodes"][0]["shards"].pop()

        wrong_route = copy.deepcopy(plan)
        wrong_route["route_policy_digest_sha256"] = "f" * 64

        tampered_plans = (
            ("known oracle removed", removed_oracle),
            ("node removed", removed_node),
            ("shard removed", removed_shard),
            ("route digest changed", wrong_route),
        )
        for label, candidate in tampered_plans:
            with self.subTest(label=label):
                audit = activation.audit_review(
                    self.conn,
                    candidate,
                    self.checkpoint_root,
                )
                self.assertFalse(audit["activation_ready"])
                self.assertIn(
                    "plan_authority_mismatch",
                    audit["activation_blockers"],
                )
                with self.assertRaises(
                    (sqlite3.IntegrityError, TypeError, ValueError)
                ):
                    activation.activate_reviewed_contracts(
                        self.conn,
                        candidate,
                        self.checkpoint_root,
                    )
                self.assertEqual(0, self._active_contract_count())

        self.conn.execute(
            """
            update question_bank_version_ledger
            set question_bank_version = ?, updated_at = ?
            where status = 'active'
            """,
            ("2026-07-14.bank.authority-switch", db.now_iso()),
        )
        self.conn.commit()
        switched = activation.audit_review(
            self.conn,
            plan,
            self.checkpoint_root,
        )
        self.assertFalse(switched["activation_ready"])
        self.assertIn(
            "plan_authority_mismatch",
            switched["activation_blockers"],
        )
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            activation.activate_reviewed_contracts(
                self.conn,
                plan,
                self.checkpoint_root,
            )
        self.assertEqual(0, self._active_contract_count())


class AnswerContractLiveAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "answer-contract-live-adapter-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
            _persist_stage3_answer_contract_fixtures(
                conn,
                Path(cls._seed_dir.name) / "answer-contract-design-checkpoints",
            )
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-contract-live-adapter.sqlite"
        self.checkpoint_root = Path(self.tmpdir.name) / "checkpoints"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _modules(self):
        from learning_system import (
            answer_contract_activation,
            model_router,
            question_fingerprints,
            semantic_agents,
        )

        return (
            answer_contract_activation,
            model_router,
            question_fingerprints,
            semantic_agents,
        )

    def _plan_packet(self, activation):
        plan = activation.build_review_plan(self.conn, PROJECT_ROOT)
        _assert_persisted_stage3_review_plan(self, plan)
        node = plan["nodes"][0]
        shard = node["shards"][0]
        packet = activation._packet(plan, node, shard)
        return plan, node, shard, packet

    def _output(self, packet, *, confidence=0.99):
        from learning_system import answer_contract_activation

        unit = AnswerContractReviewUnitTests()
        items = []
        handles = answer_contract_activation._review_item_handles(packet)
        for handle, item in zip(handles, packet["items"]):
            fixture_item = {**item, "review_item_handle": handle}
            result = unit._review_result(fixture_item)
            result["confidence"] = confidence
            items.append(result)
        return {
            "schema_version": packet["response_schema_version"],
            "items": items,
        }

    def _enabled_route(self, model_router, *, model="gpt-5.5"):
        return model_router.ModelRoute(
            agent_key="answer_contract_reviewer_agent",
            task="answer_contract_review",
            provider="openai",
            model=model,
            model_alias=model,
            base_url="https://configured.example/v1",
            api_key="test-only-key",
            timeout_seconds=120,
            model_params={"temperature": 0},
        )

    def _envelope(
        self,
        semantic_agents,
        activation,
        packet,
        *,
        status="accepted",
        provider_mode="live_model",
        output=None,
        confidence=0.99,
    ):
        output = output if output is not None else self._output(
            packet, confidence=confidence
        )
        return semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_contract_reviewer_agent",
            phase="answer_contract_review",
            status=status,
            provider_mode=provider_mode,
            retryable=False,
            confidence=confidence,
            output=output,
            route_meta={
                "structured_json_mode": "json_schema",
                "prompt_template_sha256": packet["prompt_template_sha256"],
                "rendered_prompt_sha256": activation._rendered_prompt_digest(packet),
                "response_schema_sha256": packet[
                    "response_schema_digest_sha256"
                ],
                "raw_response_sha256": "a" * 64,
            },
            prompt_version_id=packet["prompt_version_id"],
            response_schema_version=packet["response_schema_version"],
        )

    def _accepted_reviewer_run_count(self):
        return self.conn.execute(
            """
            select count(*) from agent_runs
            where agent_key = 'answer_contract_reviewer_agent'
              and phase = 'answer_contract_review'
              and status = 'accepted'
            """
        ).fetchone()[0]

    def _semantic_outcome(self, packet, outcome):
        confidence = 0.79 if outcome == "low_confidence" else 0.99
        output = self._output(packet, confidence=confidence)
        first = output["items"][0]
        if outcome == "misbound":
            first["question_node_alignment"].update(
                verdict="misbound",
                actual_mathematical_core="A different mathematical structure.",
                tested_node_evidence="The bound node is not actually tested.",
                rationale="Independent solving shows a node mismatch.",
                advisory_candidate_node="question-bank-repair-required",
            )
        elif outcome == "contract_rejected":
            first["answer_contract_review"].update(
                verdict="rejected",
                reference_solution_correct=False,
                corrections=["Regenerate the contract without changing the question."],
            )
        elif outcome != "low_confidence":
            raise ValueError(f"unsupported semantic outcome: {outcome}")
        return output, confidence

    def _expected_repair_route(self, outcome):
        if outcome == "misbound":
            return {
                "owner": "question_bank",
                "action": "new_immutable_question_version",
                "reason_code": "question_node_misalignment",
                "preserve_bound_node": True,
            }
        if outcome == "contract_rejected":
            return {
                "owner": "answer_contract",
                "action": "regenerate_contract_draft",
                "reason_code": "answer_contract_rejected",
                "preserve_bound_node": True,
            }
        if outcome == "low_confidence":
            return {
                "owner": "answer_contract_review",
                "action": "manual_confidence_review",
                "reason_code": "semantic_review_low_confidence",
                "preserve_bound_node": True,
            }
        raise ValueError(f"unsupported semantic outcome: {outcome}")

    def test_answer_contract_review_route_is_independent_configurable_and_honest(self):
        _, model_router, _, _ = self._modules()

        with mock.patch.dict(os.environ, {}, clear=True):
            unconfigured = model_router.answer_contract_review_route()
        self.assertEqual("answer_contract_reviewer_agent", unconfigured.agent_key)
        self.assertEqual("answer_contract_review", unconfigured.task)
        self.assertEqual("gpt-5.5", unconfigured.model)
        self.assertFalse(unconfigured.enabled)
        self.assertEqual(
            {
                "model_provider": "",
                "model_name": "",
                "model_alias": "",
                "model_params": {},
            },
            unconfigured.audit_metadata(),
        )

        configured_env = {
            "OPENAI_API_KEY": "shared-key",
            "OPENAI_BASE_URL": "https://shared.example/v1",
        }
        with mock.patch.dict(os.environ, configured_env, clear=True):
            configured = model_router.answer_contract_review_route()
        self.assertTrue(configured.enabled)
        self.assertEqual("gpt-5.5", configured.model)
        self.assertEqual("shared-key", configured.api_key)
        self.assertEqual("https://shared.example/v1", configured.base_url)

        with mock.patch.dict(
            os.environ,
            {**configured_env, "AI_ANSWER_CONTRACT_REVIEW_MODEL": "gpt-5.5-review-pin"},
            clear=True,
        ):
            overridden = model_router.answer_contract_review_route()
        self.assertEqual("gpt-5.5-review-pin", overridden.model)
        self.assertEqual("gpt-5.5-review-pin", overridden.model_alias)

    def test_shared_openai_route_matches_registered_review_contract_lineage(self):
        activation, model_router, _, _ = self._modules()
        from learning_system import internal_agents

        contract = internal_agents.load_v5_contract_for_agent(
            "answer_contract_reviewer_agent"
        )
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://shared.example/v1",
            },
            clear=True,
        ):
            route = model_router.answer_contract_review_route()
            reviewer = activation.make_live_reviewer(self.conn)

        self.assertTrue(callable(reviewer))
        self.assertEqual(contract["agent_key"], route.agent_key)
        self.assertEqual(contract["contract_key"], route.task)
        self.assertEqual("openai", route.provider)
        self.assertEqual("gpt-5.5", route.model)

    def test_loaded_review_contract_schema_is_recursively_strict_for_openai(self):
        from learning_system import internal_agents

        contract = internal_agents.load_v5_contract_for_agent(
            "answer_contract_reviewer_agent"
        )
        failures = []

        def inspect(schema, path="$"):
            if not isinstance(schema, dict):
                return
            properties = schema.get("properties")
            if isinstance(properties, dict):
                required = schema.get("required")
                if not isinstance(required, list):
                    failures.append(f"{path}: required must be an array")
                elif set(required) != set(properties):
                    failures.append(
                        f"{path}: required={sorted(required)} "
                        f"properties={sorted(properties)}"
                    )
                for key, child in properties.items():
                    inspect(child, f"{path}.properties.{key}")
            items = schema.get("items")
            if isinstance(items, dict):
                inspect(items, f"{path}.items")
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                inspect(additional, f"{path}.additionalProperties")
            for keyword in ("propertyNames", "not", "contains", "if", "then", "else"):
                child = schema.get(keyword)
                if isinstance(child, dict):
                    inspect(child, f"{path}.{keyword}")
            for keyword in ("oneOf", "anyOf", "allOf", "prefixItems"):
                branches = schema.get(keyword)
                if isinstance(branches, list):
                    for index, child in enumerate(branches):
                        inspect(child, f"{path}.{keyword}[{index}]")

        inspect(contract["response_schema"])
        self.assertEqual([], failures)

    def test_invalid_local_strict_schema_is_rejected_before_transport(self):
        _, model_router, _, _ = self._modules()
        route = self._enabled_route(model_router)
        invalid_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["outer"],
            "properties": {
                "outer": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["required_value"],
                    "properties": {
                        "required_value": {"type": "string"},
                        "optional_value": {"type": ["string", "null"]},
                    },
                }
            },
        }
        payload = {
            "instructions": "Return JSON.",
            "input": [{"role": "user", "content": "test"}],
        }
        with mock.patch.object(model_router, "call_responses") as responses, mock.patch.object(
            model_router, "call_chat_completions"
        ) as chat:
            with self.assertRaises(model_router.ModelJSONParseError):
                model_router.call_structured_json(
                    route,
                    payload,
                    schema=invalid_schema,
                )
        responses.assert_not_called()
        chat.assert_not_called()

    def test_loaded_review_contract_uses_provider_supported_exact_values_shape(self):
        from learning_system import internal_agents

        contract = internal_agents.load_v5_contract_for_agent(
            "answer_contract_reviewer_agent"
        )
        schema = contract["response_schema"]

        def contains_property_names(value):
            if isinstance(value, dict):
                return "propertyNames" in value or any(
                    contains_property_names(child) for child in value.values()
                )
            if isinstance(value, list):
                return any(contains_property_names(child) for child in value)
            return False

        self.assertFalse(contains_property_names(schema))
        values = schema["properties"]["items"]["items"]["properties"][
            "normalized_instance_descriptor"
        ]["properties"]["values"]
        self.assertEqual("array", values["type"])
        self.assertEqual(
            {"name", "value"},
            set(values["items"]["properties"]),
        )
        self.assertEqual(
            {"name", "value"},
            set(values["items"]["required"]),
        )
        self.assertIs(False, values["items"]["additionalProperties"])

    def test_unsupported_strict_schema_keyword_is_rejected_before_transport(self):
        _, model_router, _, _ = self._modules()
        route = self._enabled_route(model_router)
        invalid_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["outer"],
            "properties": {
                "outer": {
                    "type": "object",
                    "propertyNames": {"pattern": "^[a-z]+$"},
                    "additionalProperties": {"type": "string"},
                }
            },
        }
        payload = {
            "instructions": "Return JSON.",
            "input": [{"role": "user", "content": "test"}],
        }
        with mock.patch.object(model_router, "call_responses") as responses, mock.patch.object(
            model_router, "call_chat_completions"
        ) as chat:
            with self.assertRaises(model_router.ModelJSONParseError):
                model_router.call_structured_json(
                    route,
                    payload,
                    schema=invalid_schema,
                )
        responses.assert_not_called()
        chat.assert_not_called()

    def test_live_reviewer_request_separates_trusted_lineage_from_untrusted_content(self):
        activation, _, _, _ = self._modules()
        _, _, _, packet = self._plan_packet(activation)
        request = activation._semantic_review_request(packet)

        self.assertNotIn("review_packet", request.trusted_context)
        trusted_text = json.dumps(
            request.trusted_context,
            ensure_ascii=False,
            sort_keys=True,
        )
        for content_field in (
            '"items"',
            '"node_context"',
            '"question"',
            '"prompt"',
            '"expected_answer"',
            '"solution_steps"',
            '"draft_contract"',
        ):
            self.assertNotIn(content_field, trusted_text)
        for lineage_value in (
            packet["prompt_version_id"],
            packet["response_schema_version"],
            packet["route_policy_digest_sha256"],
        ):
            self.assertIn(lineage_value, trusted_text)

        self.assertEqual(
            {"node_context", "items"},
            set(request.untrusted_payload),
        )
        self.assertEqual(
            packet["node_context"],
            request.untrusted_payload["node_context"],
        )
        expected_handles = activation._review_item_handles(packet)
        untrusted_items = request.untrusted_payload["items"]
        self.assertEqual(len(packet["items"]), len(untrusted_items))
        contract_lineage_fields = {
            "stable_contract_id",
            "contract_version",
            "question_id",
            "item_version",
            "node_id",
            "question_digest_sha256",
            "contract_digest_sha256",
            "review_record_id",
        }
        for expected_handle, expected_item, untrusted_item in zip(
            expected_handles,
            packet["items"],
            untrusted_items,
        ):
            self.assertEqual(expected_handle, untrusted_item["item_handle"])
            self.assertEqual(expected_item["question"], untrusted_item["question"])
            self.assertEqual(
                {
                    key: value
                    for key, value in expected_item["draft_contract"].items()
                    if key not in contract_lineage_fields
                },
                untrusted_item["draft_contract"],
            )
            self.assertTrue(
                contract_lineage_fields.isdisjoint(
                    untrusted_item["draft_contract"]
                )
            )
        self.assertEqual(
            {"shard_digest_sha256": packet["shard_digest_sha256"]},
            request.source_refs,
        )

    def test_live_adapter_records_exact_run_and_returns_eligible_lineage(self):
        activation, model_router, question_fingerprints, semantic_agents = self._modules()
        plan, node, shard, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        captured_requests = []

        def semantic_call(request):
            captured_requests.append(request)
            self.assertEqual("answer_contract_reviewer_agent", request.agent_key)
            self.assertEqual("answer_contract_review", request.phase)
            self.assertEqual(
                {"shard_digest_sha256": packet["shard_digest_sha256"]},
                request.source_refs,
            )
            return self._envelope(semantic_agents, activation, packet)

        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ), mock.patch.object(
            semantic_agents,
            "call_answer_contract_reviewer_agent",
            side_effect=semantic_call,
        ):
            reviewer = activation.make_live_reviewer(self.conn)
            report = activation.run_live_review(
                self.conn,
                PROJECT_ROOT,
                reviewer,
                self.checkpoint_root,
                sleep_fn=lambda _seconds: None,
                max_shards=1,
            )

        self.assertEqual(1, len(captured_requests))
        self.assertEqual("live_model_call", report["evidence_scope"])
        self.assertTrue(report["live_semantic_pass"])
        checkpoint_path = sorted(
            (
                self.checkpoint_root
                / plan["bank_version"]
                / node["node_id"]
            ).glob("shard-*.json")
        )[0]
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        raw_semantic_output = self._output(packet)
        from learning_system import answer_contract_review

        bound_items = answer_contract_review.bind_semantic_review_results(
            packet["items"],
            raw_semantic_output["items"],
            item_handles=activation._review_item_handles(packet),
        )
        expected_bound_output = {
            "schema_version": raw_semantic_output["schema_version"],
            "items": bound_items,
        }
        forbidden_model_authority = {
            "question_id",
            "item_version",
            "question_digest_sha256",
            "contract_id",
            "contract_version",
            "contract_digest_sha256",
            "shard_digest_sha256",
            "review_record_id",
            "agent_run_id",
            "provider_mode",
            "activation_eligible",
            "prompt_instance_fingerprint",
            "core_structure_fingerprint",
            "receipt_digest_sha256",
        }
        for semantic_item in raw_semantic_output["items"]:
            self.assertTrue(forbidden_model_authority.isdisjoint(semantic_item))

        self.assertIn("semantic_output", checkpoint)
        self.assertIn("semantic_output_digest_sha256", checkpoint)
        self.assertIn("bound_output_digest_sha256", checkpoint)
        self.assertEqual(raw_semantic_output, checkpoint["semantic_output"])
        self.assertEqual(expected_bound_output, checkpoint["output"])
        self.assertNotEqual(checkpoint["semantic_output"], checkpoint["output"])
        self.assertEqual(
            question_fingerprints.canonical_sha256(raw_semantic_output),
            checkpoint["semantic_output_digest_sha256"],
        )
        self.assertEqual(
            question_fingerprints.canonical_sha256(expected_bound_output),
            checkpoint["bound_output_digest_sha256"],
        )
        self.assertTrue(checkpoint["activation_eligible"])
        self.assertEqual("live_model_call", checkpoint["evidence_scope"])
        self.assertTrue(checkpoint["agent_run_id"])

        row = self.conn.execute(
            "select * from agent_runs where id = ?",
            (checkpoint["agent_run_id"],),
        ).fetchone()
        self.assertIsNotNone(row)
        expected = {
            "agent_key": "answer_contract_reviewer_agent",
            "engine_type": "internal_learning_agent",
            "phase": "answer_contract_review",
            "trigger": "contract_activation_review",
            "input_digest_sha256": shard["shard_digest_sha256"],
            "prompt_version_id": plan["prompt_version_id"],
            "prompt_template_sha256": plan["prompt_template_sha256"],
            "rendered_prompt_sha256": activation._rendered_prompt_digest(packet),
            "model_provider": "openai",
            "model_name": "gpt-5.5",
            "model_alias": "gpt-5.5",
            "response_schema_version": plan["response_schema_version"],
            "response_schema_sha256": plan["response_schema_digest_sha256"],
            "status": "accepted",
            "output_digest_sha256": question_fingerprints.canonical_sha256(
                raw_semantic_output
            ),
        }
        for field, value in expected.items():
            self.assertEqual(value, row[field], field)
        self.assertEqual(
            {"shard_digest_sha256": shard["shard_digest_sha256"]},
            db.json_load(row["input_refs_json"], {}),
        )
        self.assertEqual(raw_semantic_output, db.json_load(row["output_json"], {}))
        self.assertNotEqual(checkpoint["output"], db.json_load(row["output_json"], {}))
        self.assertEqual([], db.json_load(row["validation_errors_json"], []))

    def test_valid_live_nonapproval_always_records_accepted_raw_agent_run(self):
        activation, model_router, question_fingerprints, semantic_agents = self._modules()
        _, _, shard, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)

        for outcome in ("misbound", "contract_rejected", "low_confidence"):
            with self.subTest(outcome=outcome):
                raw_output, confidence = self._semantic_outcome(packet, outcome)
                envelope = self._envelope(
                    semantic_agents,
                    activation,
                    packet,
                    output=raw_output,
                    confidence=confidence,
                )
                before = self._accepted_reviewer_run_count()
                with mock.patch.object(
                    model_router,
                    "answer_contract_review_route",
                    return_value=route,
                ), mock.patch.object(
                    semantic_agents,
                    "call_answer_contract_reviewer_agent",
                    return_value=envelope,
                ):
                    reviewer = activation.make_live_reviewer(self.conn)
                    try:
                        result = reviewer(copy.deepcopy(packet))
                    except (TypeError, ValueError) as exc:
                        self.fail(
                            f"schema-valid {outcome} was treated as invalid: {exc}"
                        )

                self.assertEqual(before + 1, self._accepted_reviewer_run_count())
                self.assertEqual("accepted", result["status"])
                self.assertFalse(result["activation_eligible"])
                row = self.conn.execute(
                    "select * from agent_runs where id = ?",
                    (result["agent_run_id"],),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual("accepted", row["status"])
                self.assertEqual("answer_contract_reviewer_agent", row["agent_key"])
                self.assertEqual("answer_contract_review", row["phase"])
                self.assertEqual(shard["shard_digest_sha256"], row["input_digest_sha256"])
                self.assertEqual("openai", row["model_provider"])
                self.assertEqual("gpt-5.5", row["model_name"])
                self.assertEqual(raw_output, db.json_load(row["output_json"], {}))
                self.assertEqual(
                    question_fingerprints.canonical_sha256(raw_output),
                    row["output_digest_sha256"],
                )

    def test_valid_nonapproval_creates_nonterminal_checkpoint_with_repair_route(self):
        activation, model_router, _, semantic_agents = self._modules()
        plan, node, _, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)

        for outcome in ("misbound", "contract_rejected", "low_confidence"):
            with self.subTest(outcome=outcome):
                root = self.checkpoint_root / outcome
                raw_output, confidence = self._semantic_outcome(packet, outcome)
                envelope = self._envelope(
                    semantic_agents,
                    activation,
                    packet,
                    output=raw_output,
                    confidence=confidence,
                )
                with mock.patch.object(
                    model_router,
                    "answer_contract_review_route",
                    return_value=route,
                ), mock.patch.object(
                    semantic_agents,
                    "call_answer_contract_reviewer_agent",
                    return_value=envelope,
                ):
                    reviewer = activation.make_live_reviewer(self.conn)
                    try:
                        activation.run_live_review(
                            self.conn,
                            PROJECT_ROOT,
                            reviewer,
                            root,
                            sleep_fn=lambda _seconds: None,
                            max_shards=1,
                        )
                    except activation.ReviewRunError as exc:
                        self.fail(
                            f"schema-valid {outcome} became terminal failure: {exc}"
                        )

                checkpoint_path = activation._checkpoint_path(
                    root,
                    plan["bank_version"],
                    node["node_id"],
                    node["shards"][0]["shard_index"],
                )
                failure_path = checkpoint_path.with_suffix(".failure.json")
                self.assertTrue(checkpoint_path.is_file())
                self.assertFalse(failure_path.exists())
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                self.assertTrue(checkpoint["sealed"])
                self.assertEqual("accepted", checkpoint["status"])
                self.assertEqual("live_model_call", checkpoint["evidence_scope"])
                self.assertFalse(checkpoint["activation_eligible"])
                self.assertEqual(raw_output, checkpoint["semantic_output"])
                first = checkpoint["validated_items"][0]
                self.assertEqual(
                    self._expected_repair_route(outcome),
                    first["repair_route"],
                )
                if outcome == "low_confidence":
                    self.assertTrue(first["needs_retry"])
                    self.assertIn("low_confidence", first["blockers"])

    def test_only_malformed_lineage_or_transport_failures_are_terminal(self):
        activation, model_router, _, semantic_agents = self._modules()
        plan, node, _, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        malformed = self._envelope(
            semantic_agents,
            activation,
            packet,
            output={"schema_version": packet["response_schema_version"]},
        )
        accepted = self._envelope(
            semantic_agents,
            activation,
            packet,
        )
        wrong_lineage = semantic_agents.SemanticAgentEnvelope(
            **{**accepted.__dict__, "phase": "question_review"}
        )
        transport_failure = model_router.ModelCallError(
            "HTTP 503 temporarily unavailable",
            status_code=503,
            endpoint="responses",
            structured_json_mode="json_schema",
        )
        cases = (
            ("malformed", malformed, 1),
            ("lineage", wrong_lineage, 1),
            ("transport", transport_failure, 3),
        )

        for label, result_or_error, expected_calls in cases:
            with self.subTest(label=label):
                root = self.checkpoint_root / f"terminal-{label}"
                before = self._accepted_reviewer_run_count()
                patch_value = (
                    {"side_effect": result_or_error}
                    if isinstance(result_or_error, Exception)
                    else {"return_value": result_or_error}
                )
                with mock.patch.object(
                    model_router,
                    "answer_contract_review_route",
                    return_value=route,
                ), mock.patch.object(
                    semantic_agents,
                    "call_answer_contract_reviewer_agent",
                    **patch_value,
                ) as semantic_call:
                    reviewer = activation.make_live_reviewer(self.conn)
                    with self.assertRaises(activation.ReviewRunError) as raised:
                        activation.run_live_review(
                            self.conn,
                            PROJECT_ROOT,
                            reviewer,
                            root,
                            sleep_fn=lambda _seconds: None,
                            max_shards=1,
                        )

                self.assertEqual(expected_calls, semantic_call.call_count)
                self.assertEqual(before, self._accepted_reviewer_run_count())
                receipt_path = Path(raised.exception.report["failure_receipt_path"])
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                self.assertTrue(receipt["sealed"])
                self.assertEqual("terminal_failure", receipt["status"])
                self.assertFalse(receipt["activation_eligible"])
                accepted_path = activation._checkpoint_path(
                    root,
                    plan["bank_version"],
                    node["node_id"],
                    node["shards"][0]["shard_index"],
                )
                self.assertFalse(accepted_path.exists())

    def test_probe_report_separates_transport_validity_approval_and_activation(self):
        activation, model_router, _, semantic_agents = self._modules()
        route = self._enabled_route(model_router)

        for outcome, expected_approval in (
            ("misbound", False),
            ("low_confidence", True),
        ):
            with self.subTest(outcome=outcome):
                root = self.checkpoint_root / f"probe-{outcome}"

                def semantic_call(request):
                    item = {
                        "review_item_handle": request.untrusted_payload["items"][0][
                            "item_handle"
                        ]
                    }
                    raw_item = AnswerContractReviewUnitTests()._review_result(item)
                    confidence = 0.79 if outcome == "low_confidence" else 0.99
                    raw_item["confidence"] = confidence
                    if outcome == "misbound":
                        raw_item["question_node_alignment"].update(
                            verdict="misbound",
                            actual_mathematical_core="A different mathematical structure.",
                            tested_node_evidence="The bound node is not actually tested.",
                            rationale="Independent solving shows a node mismatch.",
                            advisory_candidate_node="question-bank-repair-required",
                        )
                    raw_output = {
                        "schema_version": request.trusted_context[
                            "response_schema_version"
                        ],
                        "items": [raw_item],
                    }
                    return semantic_agents.SemanticAgentEnvelope(
                        agent_key="answer_contract_reviewer_agent",
                        phase="answer_contract_review",
                        status="accepted",
                        provider_mode="live_model",
                        retryable=False,
                        confidence=confidence,
                        output=raw_output,
                        route_meta={
                            "structured_json_mode": "json_schema",
                            "prompt_template_sha256": request.trusted_context[
                                "prompt_template_sha256"
                            ],
                            "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
                                request
                            ),
                            "response_schema_sha256": request.trusted_context[
                                "response_schema_digest_sha256"
                            ],
                            "raw_response_sha256": "a" * 64,
                        },
                        prompt_version_id=request.trusted_context[
                            "prompt_version_id"
                        ],
                        response_schema_version=request.trusted_context[
                            "response_schema_version"
                        ],
                    )

                with mock.patch.object(
                    model_router,
                    "answer_contract_review_route",
                    return_value=route,
                ), mock.patch.object(
                    semantic_agents,
                    "call_answer_contract_reviewer_agent",
                    side_effect=semantic_call,
                ):
                    reviewer = activation.make_live_reviewer(self.conn)
                    try:
                        report = activation.run_live_probe(
                            self.conn,
                            PROJECT_ROOT,
                            reviewer,
                            root,
                            probe_items=1,
                            sleep_fn=lambda _seconds: None,
                        )
                    except activation.ReviewRunError as exc:
                        self.fail(
                            f"schema-valid {outcome} probe became terminal: {exc}"
                        )

                expected = {
                    "transport_pass": True,
                    "semantic_response_valid": True,
                    "semantic_approval": expected_approval,
                    "activation_eligible": False,
                }
                self.assertEqual(
                    expected,
                    {field: report.get(field) for field in expected},
                )
                receipt = json.loads(
                    Path(report["probe_receipt_path"]).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    expected,
                    {field: receipt.get(field) for field in expected},
                )

    def test_valid_rejection_checkpoint_survives_resume_and_never_activates(self):
        activation, model_router, _, semantic_agents = self._modules()
        plan, node, _, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        raw_output, confidence = self._semantic_outcome(packet, "misbound")
        envelope = self._envelope(
            semantic_agents,
            activation,
            packet,
            output=raw_output,
            confidence=confidence,
        )
        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ), mock.patch.object(
            semantic_agents,
            "call_answer_contract_reviewer_agent",
            return_value=envelope,
        ):
            reviewer = activation.make_live_reviewer(self.conn)
            first = activation.run_live_review(
                self.conn,
                PROJECT_ROOT,
                reviewer,
                self.checkpoint_root,
                sleep_fn=lambda _seconds: None,
                max_shards=1,
            )

        checkpoint_path = activation._checkpoint_path(
            self.checkpoint_root,
            plan["bank_version"],
            node["node_id"],
            node["shards"][0]["shard_index"],
        )
        before = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(raw_output, before["semantic_output"])
        self.assertFalse(before["activation_eligible"])
        accepted_runs = self._accepted_reviewer_run_count()

        resumed_calls = []

        def must_not_call(_packet):
            resumed_calls.append(True)
            raise AssertionError("valid rejection checkpoint must be reused")

        resumed = activation.run_live_review(
            self.conn,
            PROJECT_ROOT,
            must_not_call,
            self.checkpoint_root,
            sleep_fn=lambda _seconds: None,
            max_shards=1,
        )
        after = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual([], resumed_calls)
        self.assertEqual(1, first["processed_shards"])
        self.assertEqual(1, resumed["reused_shards"])
        self.assertEqual(0, resumed["model_calls"])
        self.assertEqual(accepted_runs, self._accepted_reviewer_run_count())
        self.assertEqual(before, after)

        audit = activation.audit_review(self.conn, plan, self.checkpoint_root)
        self.assertFalse(audit["activation_ready"])
        self.assertIn(packet["items"][0]["question_id"], audit["rejected_question_ids"])
        with self.assertRaises((sqlite3.IntegrityError, TypeError, ValueError)):
            activation.activate_reviewed_contracts(
                self.conn,
                plan,
                self.checkpoint_root,
            )
        self.assertEqual(
            0,
            self.conn.execute(
                "select count(*) from answer_contracts where status = 'active'"
            ).fetchone()[0],
        )

    def test_semantic_agent_route_meta_uses_canonical_plan_schema_digest(self):
        activation, model_router, _, semantic_agents = self._modules()
        plan, _, _, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        output = self._output(packet)
        request = activation._semantic_review_request(packet)
        result = model_router.StructuredJSONResult(
            value=output,
            mode="json_schema",
            endpoint="responses",
            raw_response={"output_text": json.dumps(output, ensure_ascii=False)},
        )

        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=result,
        ):
            envelope = semantic_agents.call_answer_contract_reviewer_agent(request)

        self.assertEqual("accepted", envelope.status)
        self.assertEqual(
            plan["response_schema_digest_sha256"],
            envelope.route_meta["response_schema_sha256"],
        )

    def test_non_live_or_malformed_envelopes_never_record_accepted_run(self):
        activation, model_router, _, semantic_agents = self._modules()
        _, _, _, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        malformed = {"schema_version": packet["response_schema_version"]}
        cases = (
            (
                "blocked",
                self._envelope(
                    semantic_agents,
                    activation,
                    packet,
                    status="blocked",
                    provider_mode="not_configured",
                    output={},
                    confidence=0,
                ),
            ),
            (
                "recorded",
                self._envelope(
                    semantic_agents,
                    activation,
                    packet,
                    provider_mode="recorded_model",
                ),
            ),
            (
                "malformed",
                self._envelope(
                    semantic_agents,
                    activation,
                    packet,
                    output=malformed,
                ),
            ),
        )

        for label, envelope in cases:
            with self.subTest(label=label):
                before = self._accepted_reviewer_run_count()
                with mock.patch.object(
                    model_router,
                    "answer_contract_review_route",
                    return_value=route,
                ), mock.patch.object(
                    semantic_agents,
                    "call_answer_contract_reviewer_agent",
                    return_value=envelope,
                ):
                    reviewer = activation.make_live_reviewer(self.conn)
                    try:
                        result = reviewer(copy.deepcopy(packet))
                    except (TypeError, ValueError):
                        result = None
                self.assertEqual(before, self._accepted_reviewer_run_count())
                if result is not None:
                    self.assertFalse(result.get("activation_eligible", False))
                    self.assertFalse(result.get("agent_run_id"))

    def test_same_shard_retry_creates_distinct_exact_runs_and_ignores_bad_accepted(self):
        activation, model_router, _, semantic_agents = self._modules()
        plan, _, shard, packet = self._plan_packet(activation)
        route = self._enabled_route(model_router)
        bad_run_id = "RUN-bad-accepted-same-shard"
        self.conn.execute(
            """
            insert into agent_runs(
              id, agent_key, engine_type, phase, trigger,
              input_refs_json, input_digest_sha256, prompt_version_id,
              model_provider, model_name, model_alias, status, confidence,
              output_json, output_digest_sha256, created_at
            ) values (?, 'answer_contract_reviewer_agent', 'internal_learning_agent',
                      'answer_contract_review', 'contract_activation_review', ?, ?, ?,
                      'openai', 'wrong-model', 'wrong-model', 'accepted', 0.99,
                      '{}', ?, ?)
            """,
            (
                bad_run_id,
                json.dumps({"shard_digest_sha256": shard["shard_digest_sha256"]}),
                shard["shard_digest_sha256"],
                plan["prompt_version_id"],
                "f" * 64,
                db.now_iso(),
            ),
        )
        self.conn.commit()
        envelope = self._envelope(semantic_agents, activation, packet)

        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ), mock.patch.object(
            semantic_agents,
            "call_answer_contract_reviewer_agent",
            return_value=envelope,
        ) as semantic_call:
            reviewer = activation.make_live_reviewer(self.conn)
            first = reviewer(copy.deepcopy(packet))
            second = reviewer(copy.deepcopy(packet))

        self.assertEqual(2, semantic_call.call_count)
        self.assertNotEqual(bad_run_id, first["agent_run_id"])
        self.assertNotEqual(bad_run_id, second["agent_run_id"])
        self.assertNotEqual(first["agent_run_id"], second["agent_run_id"])
        rows = self.conn.execute(
            """
            select id, model_name, status, input_digest_sha256
            from agent_runs
            where agent_key = 'answer_contract_reviewer_agent'
              and phase = 'answer_contract_review'
              and input_digest_sha256 = ?
            order by created_at, id
            """,
            (shard["shard_digest_sha256"],),
        ).fetchall()
        self.assertEqual(3, len(rows))
        exact_rows = [row for row in rows if row["id"] != bad_run_id]
        self.assertTrue(all(row["model_name"] == "gpt-5.5" for row in exact_rows))
        self.assertTrue(all(row["status"] == "accepted" for row in exact_rows))

    def test_review_live_cli_without_model_config_fails_json_and_writes_no_checkpoint(self):
        before_runs = self._accepted_reviewer_run_count()
        script = PROJECT_ROOT / "scripts/activate_answer_contracts.py"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AI_") and not key.startswith("OPENAI_")
        }
        result = subprocess.run(
            [
                "python3",
                str(script),
                "--db",
                str(self.db_path),
                "--review-live",
                "--max-shards",
                "1",
                "--checkpoint-root",
                str(self.checkpoint_root),
                "--json",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        payload = json.loads(result.stdout)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(payload["activation_ready"])
        self.assertIn("model_not_configured", payload["blockers"])
        self.assertEqual(0, len(list(self.checkpoint_root.rglob("*.json"))))
        self.assertEqual(before_runs, self._accepted_reviewer_run_count())


class AnswerContractLiveTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "answer-contract-live-transport-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
            _persist_stage3_answer_contract_fixtures(
                conn,
                Path(cls._seed_dir.name) / "answer-contract-design-checkpoints",
            )
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-contract-live-transport.sqlite"
        self.checkpoint_root = Path(self.tmpdir.name) / "checkpoints"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _modules(self):
        from learning_system import answer_contract_activation, model_router

        return answer_contract_activation, model_router

    def _route(self, model_router, *, timeout_seconds=120):
        return model_router.ModelRoute(
            agent_key="answer_contract_reviewer_agent",
            task="answer_contract_review",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://configured.example/v1",
            api_key="test-only-key",
            timeout_seconds=timeout_seconds,
            model_params={"temperature": 0},
        )

    def _plan_shard(self, activation):
        plan = activation.build_review_plan(self.conn, PROJECT_ROOT)
        _assert_persisted_stage3_review_plan(self, plan)
        node = plan["nodes"][0]
        shard = node["shards"][0]
        self.assertEqual(5, len(shard["items"]))
        return plan, node, shard

    def _output(self, packet):
        unit = AnswerContractReviewUnitTests()
        return {
            "schema_version": packet["response_schema_version"],
            "items": [unit._review_result(item) for item in packet["items"]],
        }

    def _envelope(self, packet):
        return {
            "agent_key": "answer_contract_reviewer_agent",
            "phase": "answer_contract_review",
            "status": "accepted",
            "provider_mode": "live_model",
            "model_alias": "gpt-5.5",
            "prompt_version_id": packet["prompt_version_id"],
            "response_schema_version": packet["response_schema_version"],
            "route_policy_digest_sha256": packet[
                "route_policy_digest_sha256"
            ],
            "shard_digest_sha256": packet["shard_digest_sha256"],
            "output": self._output(packet),
        }

    def _retryable_error(self, model_router, message, *, status_code=504):
        return model_router.ModelCallError(
            message,
            status_code=status_code,
            endpoint="responses",
            structured_json_mode="json_schema",
        )

    def _assert_receipt_digest(self, payload):
        body = dict(payload)
        claimed = body.pop("receipt_digest_sha256")
        calculated = hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(calculated, claimed)

    def test_retryable_504_retries_only_the_strict_responses_json_schema_lane(self):
        activation, model_router = self._modules()
        from learning_system import semantic_agents

        route = self._route(model_router)
        plan, node, shard = self._plan_shard(activation)
        packet = activation._packet(plan, node, shard)
        payloads = []

        def responses_call(_route, payload):
            payloads.append(copy.deepcopy(payload))
            raise model_router.ModelCallError("HTTP 504 gateway timeout")

        request = semantic_agents.SemanticAgentRequest(
            agent_key="answer_contract_reviewer_agent",
            phase="answer_contract_review",
            trusted_context={"review_packet": copy.deepcopy(packet)},
            untrusted_payload={},
            provider_mode="live_model",
            source_refs={
                "shard_digest_sha256": packet["shard_digest_sha256"]
            },
        )

        with mock.patch.dict(
            os.environ,
            {
                "AI_ENDPOINT_MODE": "responses,chat_completions",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
            },
            clear=True,
        ), mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ), mock.patch.object(
            model_router,
            "call_responses",
            side_effect=responses_call,
        ) as responses, mock.patch.object(
            model_router,
            "call_chat_completions",
            side_effect=model_router.ModelCallError(
                "HTTP 504 gateway timeout"
            ),
        ) as chat:
            with self.assertRaisesRegex(
                model_router.ModelCallError,
                "HTTP 504",
            ):
                semantic_agents.call_answer_contract_reviewer_agent(request)

        self.assertEqual(1, responses.call_count)
        chat.assert_not_called()
        self.assertEqual(
            ["json_schema"],
            [
                payload.get("text", {}).get("format", {}).get("type")
                for payload in payloads
            ],
        )

    def test_shard_review_uses_one_wall_deadline_and_never_exceeds_three_attempts(self):
        activation, model_router = self._modules()
        route = self._route(model_router, timeout_seconds=25)
        clock = {"now": 0.0}
        calls = []
        sleeps = []

        def reviewer(packet):
            calls.append(packet["shard_digest_sha256"])
            clock["now"] += 12.0
            raise self._retryable_error(
                model_router,
                "HTTP 504 gateway timeout",
            )

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=route,
        ):
            with self.assertRaises(Exception):
                activation.run_live_review(
                    self.conn,
                    PROJECT_ROOT,
                    reviewer,
                    self.checkpoint_root / "deadline",
                    sleep_fn=sleep,
                    monotonic_fn=lambda: clock["now"],
                    max_shards=1,
                    shard_wall_seconds=25,
                )

        self.assertEqual(1, len(calls))
        self.assertLessEqual(clock["now"], 25.0)
        self.assertLessEqual(sum(sleeps), 13.0)

        max_attempt_calls = []

        def always_retryable(packet):
            max_attempt_calls.append(packet["shard_digest_sha256"])
            raise self._retryable_error(
                model_router,
                "HTTP 503 temporarily unavailable",
                status_code=503,
            )

        generous_route = self._route(model_router, timeout_seconds=500)
        with mock.patch.object(
            model_router,
            "answer_contract_review_route",
            return_value=generous_route,
        ):
            with self.assertRaises(Exception):
                activation.run_live_review(
                    self.conn,
                    PROJECT_ROOT,
                    always_retryable,
                    self.checkpoint_root / "attempt-limit",
                    sleep_fn=lambda _seconds: None,
                    max_shards=1,
                    shard_wall_seconds=500,
                )
        self.assertEqual(3, len(max_attempt_calls))
        self.assertEqual(1, len(set(max_attempt_calls)))

    def test_retryable_http_statuses_and_retry_after_control_bounded_sleep(self):
        activation, model_router = self._modules()
        cases = (
            ("504-default", 504, "HTTP 504 gateway timeout", None, 20),
            ("429-retry-after", 429, "HTTP 429 rate limit", 45, 45),
            ("503-retry-after", 503, "HTTP 503 temporarily unavailable", 90, 90),
            ("429-retry-after-cap", 429, "HTTP 429 rate limit", 240, 180),
        )

        for label, status_code, message, retry_after, expected_sleep in cases:
            with self.subTest(case=label):
                calls = []
                sleeps = []

                def reviewer(packet):
                    calls.append(packet["shard_digest_sha256"])
                    if len(calls) == 1:
                        raise model_router.ModelCallError(
                            message,
                            status_code=status_code,
                            retry_after_seconds=retry_after,
                            endpoint="responses",
                            structured_json_mode="json_schema",
                        )
                    return self._envelope(packet)

                try:
                    report = activation.run_live_review(
                        self.conn,
                        PROJECT_ROOT,
                        reviewer,
                        self.checkpoint_root / label,
                        sleep_fn=sleeps.append,
                        max_shards=1,
                        shard_wall_seconds=500,
                    )
                except model_router.ModelCallError as exc:
                    self.fail(
                        f"retryable HTTP {status_code} was not retried: {exc}"
                    )
                self.assertEqual(2, len(calls))
                self.assertEqual([expected_sleep], sleeps)
                self.assertEqual(2, report["model_calls"])

    def test_terminal_failure_checkpoint_records_attempts_and_survives_resume(self):
        activation, model_router = self._modules()
        plan, node, shard = self._plan_shard(activation)
        calls = []

        def reviewer(packet):
            calls.append(packet["shard_digest_sha256"])
            raise self._retryable_error(
                model_router,
                "HTTP 504 gateway timeout",
            )

        with self.assertRaises(activation.ReviewRunError) as raised:
            activation.run_live_review(
                self.conn,
                PROJECT_ROOT,
                reviewer,
                self.checkpoint_root,
                sleep_fn=lambda _seconds: None,
                max_shards=1,
            )

        self.assertEqual(3, len(calls))
        checkpoint_path = Path(
            raised.exception.report["failure_receipt_path"]
        )
        self.assertTrue(checkpoint_path.is_file(), checkpoint_path)
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertTrue(checkpoint["sealed"])
        self.assertEqual("terminal_failure", checkpoint["status"])
        self.assertFalse(checkpoint["activation_eligible"])
        self.assertEqual(3, checkpoint["attempt_count"])
        self.assertEqual(3, checkpoint["model_calls"])
        self.assertEqual([1, 2, 3], [item["attempt"] for item in checkpoint["attempts"]])
        self.assertTrue(all(item["retryable"] for item in checkpoint["attempts"]))
        self.assertTrue(
            all(item["status_code"] == 504 for item in checkpoint["attempts"])
        )
        self.assertTrue(
            all(
                item["transport_endpoint"] == "responses"
                for item in checkpoint["attempts"]
            )
        )
        self.assertTrue(
            all(
                item["structured_json_mode"] == "json_schema"
                for item in checkpoint["attempts"]
            )
        )
        self.assertIn("504", checkpoint["terminal_error"]["message"])
        self._assert_receipt_digest(checkpoint)
        receipt_digest = checkpoint["receipt_digest_sha256"]

        resumed_calls = []

        def must_not_call(_packet):
            resumed_calls.append(True)
            raise AssertionError("sealed terminal failure must survive resume")

        try:
            activation.run_live_review(
                self.conn,
                PROJECT_ROOT,
                must_not_call,
                self.checkpoint_root,
                sleep_fn=lambda _seconds: None,
                max_shards=1,
            )
        except Exception:
            pass
        self.assertEqual([], resumed_calls)
        resumed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt_digest, resumed["receipt_digest_sha256"])
        self.assertEqual(checkpoint, resumed)

    def test_one_item_live_probe_keeps_the_authoritative_five_item_shard_unchanged(self):
        activation, _ = self._modules()
        plan, node, shard = self._plan_shard(activation)
        original_items = copy.deepcopy(shard["items"])
        original_digest = shard["shard_digest_sha256"]
        question_id = shard["items"][0]["question_id"]
        calls = []

        def reviewer(packet):
            calls.append(copy.deepcopy(packet))
            return self._envelope(packet)

        try:
            report = activation.run_live_probe(
                self.conn,
                PROJECT_ROOT,
                reviewer,
                self.checkpoint_root,
                probe_items=1,
                sleep_fn=lambda _seconds: None,
            )
        except TypeError as exc:
            self.fail(f"one-item live probe seam is missing: {exc}")

        self.assertEqual(1, len(calls))
        self.assertEqual(
            [question_id],
            [item["question_id"] for item in calls[0]["items"]],
        )
        self.assertTrue(report["probe_only"])
        self.assertEqual([question_id], report["question_ids"])
        self.assertEqual(1, report["probe_items"])
        self.assertFalse(report["activation_eligible"])
        self.assertEqual(1, report["model_calls"])
        self.assertEqual([], list(self.checkpoint_root.rglob("shard-*.json")))
        self.assertTrue(Path(report["probe_receipt_path"]).is_file())

        rebuilt = activation.build_review_plan(self.conn, PROJECT_ROOT)
        _assert_persisted_stage3_review_plan(self, rebuilt)
        rebuilt_shard = rebuilt["nodes"][0]["shards"][0]
        self.assertEqual(original_items, rebuilt_shard["items"])
        self.assertEqual(original_digest, rebuilt_shard["shard_digest_sha256"])
        self.assertEqual(5, rebuilt["route_policy"]["shard_size"])

    def test_review_live_cli_accepts_one_item_probe_option(self):
        script_path = PROJECT_ROOT / "scripts/activate_answer_contracts.py"
        spec = importlib.util.spec_from_file_location(
            "activate_answer_contracts_transport_test",
            script_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            args = module._parse_args(
                [
                    "--db",
                    str(self.db_path),
                    "--review-live",
                    "--probe-items",
                    "1",
                    "--checkpoint-root",
                    str(self.checkpoint_root),
                    "--json",
                ]
            )
        except ValueError as exc:
            self.fail(f"one-item live probe CLI option is missing: {exc}")

        self.assertTrue(args.review_live)
        self.assertIsNone(args.max_shards)
        self.assertEqual(1, args.probe_items)

    def test_missing_local_schema_is_rejected_before_any_transport_call(self):
        _, model_router = self._modules()
        route = self._route(model_router)
        payload = {
            "instructions": "Return JSON.",
            "input": [{"role": "user", "content": "test"}],
        }

        with mock.patch.object(
            model_router,
            "call_responses",
        ) as responses, mock.patch.object(
            model_router,
            "call_chat_completions",
        ) as chat:
            observed_error = None
            try:
                model_router.call_structured_json(
                    route,
                    payload,
                    schema=None,
                )
            except Exception as exc:
                observed_error = exc
            responses.assert_not_called()
            chat.assert_not_called()
        self.assertIsInstance(
            observed_error,
            model_router.ModelJSONParseError,
            f"missing schema must fail closed with ModelJSONParseError, got {observed_error!r}",
        )


class AnswerReviewV3ArtifactTests(unittest.TestCase):
    CONTRACT_PATH = PROJECT_ROOT / "learning_system/agent_contracts/answer_review.v3.json"
    PROMPT_PATH = PROJECT_ROOT / "learning_system/prompts/answer_review.v3.md"

    def test_answer_analysis_agent_selects_strict_v3_criterion_contract(self):
        from learning_system import internal_agents

        self.assertTrue(self.CONTRACT_PATH.is_file(), self.CONTRACT_PATH)
        contract = internal_agents.load_v5_contract_for_agent(
            "answer_analysis_agent"
        )
        self.assertEqual("answer_review", contract["contract_key"])
        self.assertEqual(
            "learning_system/prompts/answer_review.v3.md",
            contract["prompt_template_path"],
        )
        schema = contract["response_schema"]
        expected = {
            "schema_version",
            "criteria",
            "answer_gap",
            "improvement_direction",
            "expression_judgment",
            "teaching_explanation",
            "confidence",
        }
        self.assertEqual("object", schema["type"])
        self.assertIs(False, schema["additionalProperties"])
        self.assertEqual(expected, set(schema["required"]))
        self.assertEqual(expected, set(schema["properties"]))
        criterion = schema["properties"]["criteria"]["items"]
        self.assertIs(False, criterion["additionalProperties"])
        self.assertEqual(
            {"criterion_key", "status", "child_evidence", "reason"},
            set(criterion["required"]),
        )
        self.assertEqual(
            {"met", "not_met", "contradicted", "unclear"},
            set(criterion["properties"]["status"]["enum"]),
        )
        for forbidden in (
            "score",
            "score_points",
            "max_points",
            "score_out_of_10",
            "question_passed",
            "evaluation_support",
            "mastery",
            "next_action",
            "next_evidence_need",
        ):
            self.assertNotIn(forbidden, schema["properties"])

    def test_v3_prompt_limits_model_to_semantic_criterion_judgment(self):
        self.assertTrue(self.PROMPT_PATH.is_file(), self.PROMPT_PATH)
        prompt = self.PROMPT_PATH.read_text(encoding="utf-8").lower()
        required_concepts = (
            ("semantic equivalence", "语义等价"),
            ("alternative valid method", "替代方法", "不同正确方法"),
            ("child evidence", "孩子证据", "作答证据"),
            ("preloaded criteria", "预加载判据", "既定判据"),
            ("presentation", "表达形式", "格式偏好"),
            ("simplified chinese", "中文输出", "简体中文"),
            ("has learned the math", "数学掌握"),
            ("write it more formally", "规范表达"),
            ("simple prerequisite arithmetic", "简单前置运算"),
        )
        forbidden_authority = (
            ("do not calculate", "不得计算总分", "不要计算总分"),
            ("mastery", "不得判断掌握", "不要判断掌握"),
            ("next action", "不得选择下一步", "不要选择下一步"),
        )
        for alternatives in required_concepts + forbidden_authority:
            with self.subTest(concept=alternatives[0]):
                self.assertTrue(
                    any(phrase in prompt for phrase in alternatives),
                    alternatives,
                )


class AnswerAssessmentRuntimeV51Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "answer-assessment-runtime-v51-seed.sqlite"
        conn = sqlite3.connect(cls._seed_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma foreign_keys = on")
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
            conn.close()
            from scripts import activate_lightweight_answer_contracts

            activate_lightweight_answer_contracts.activate(
                cls._seed_path,
                project_root=PROJECT_ROOT,
            )
        finally:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        from learning_system import daily_runtime

        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "answer-assessment-runtime-v51.sqlite"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        self.runtime = daily_runtime.DailyLearningRuntime(
            self.conn,
            project_root=PROJECT_ROOT,
        )
        self.day_key = "2099-07-14-answer-assessment-v51"
        self.started = self.runtime.start_review_mode(client_day_key=self.day_key)
        self.step = self.started["current_step"]
        self._pin_v51_contract()

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _pin_v51_contract(self):
        from learning_system import assessment_policy, assessment_store, question_fingerprints

        step_row = self.conn.execute(
            "select * from flow_steps where step_handle = ?",
            (self.step["step_handle"],),
        ).fetchone()
        self.assertIsNotNone(step_row)
        self.flow_id = step_row["flow_id"]
        self.question = db.get_question(self.conn, step_row["question_id"])
        existing_contract = assessment_store.active_contract_for_question(
            self.conn,
            self.question["id"],
            self.question["item_version"],
        )
        if existing_contract:
            self.conn.execute(
                """
                update flow_steps
                set answer_contract_id = ?, answer_contract_version = ?,
                    answer_contract_digest_sha256 = ?
                where id = ?
                """,
                (
                    existing_contract["id"],
                    existing_contract["contract_version"],
                    existing_contract["contract_digest_sha256"],
                    step_row["id"],
                ),
            )
            self.conn.execute(
                "update daily_flows set assessment_policy_version = 'v5.1' where id = ?",
                (self.flow_id,),
            )
            self._force_single_question_step(step_row["id"])
            self.conn.commit()
            self.contract = existing_contract
            self.contract_id = existing_contract["id"]
            self.contract_digest = existing_contract["contract_digest_sha256"]
            return
        contract = assessment_policy.build_answer_contract(self.question)
        assessment_policy.validate_contract(contract)
        contract_id = f"AC-runtime-v51-{self.question['id']}"
        versioned = {
            "stable_contract_id": contract_id,
            "contract_version": 1,
            **contract,
        }
        contract_digest = question_fingerprints.canonical_sha256(versioned)
        now = db.now_iso()
        self.conn.execute(
            """
            insert into answer_contracts(
              id, stable_contract_id, question_id, item_version, contract_version,
              contract_digest_sha256, question_digest_sha256, graph_version,
              question_bank_version, reference_solution_json, score_points_json,
              generator_version, review_record_id, review_receipt_json,
              review_receipt_sha256, fingerprint_policy_version,
              prompt_instance_fingerprint, core_structure_fingerprint,
              status, approved_at, activated_at, created_at, updated_at
            ) values (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?,
                      'assessment-contract-generator.v1', ?, ?, ?,
                      'question-fingerprint.v1', ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                contract_id,
                contract_id,
                self.question["id"],
                self.question["item_version"],
                contract_digest,
                question_fingerprints.canonical_sha256(self.question),
                step_row["graph_version"],
                step_row["question_bank_version"],
                db.json_dump(contract["reference_solution"]),
                db.json_dump(contract["score_points"]),
                step_row["review_record_id"],
                db.json_dump({"status": "accepted", "provider_mode": "live_model"}),
                "r" * 64,
                question_fingerprints.canonical_sha256(
                    {"question_id": self.question["id"], "instance": True}
                ),
                question_fingerprints.canonical_sha256(
                    {"node_id": self.question["node_id"], "core": True}
                ),
                now,
                now,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            update flow_steps
            set answer_contract_id = ?, answer_contract_version = 1,
                answer_contract_digest_sha256 = ?
            where id = ?
            """,
            (contract_id, contract_digest, step_row["id"]),
        )
        self.conn.execute(
            "update daily_flows set assessment_policy_version = 'v5.1' where id = ?",
            (self.flow_id,),
        )
        self._force_single_question_step(step_row["id"])
        self.conn.commit()
        self.contract = versioned
        self.contract_id = contract_id
        self.contract_digest = contract_digest

    def _force_single_question_step(self, step_id):
        step_row = self.conn.execute(
            "select selection_reason_json from flow_steps where id = ?",
            (step_id,),
        ).fetchone()
        reason = json.loads(step_row["selection_reason_json"] or "{}")
        mini_group = reason.get("mini_group")
        if isinstance(mini_group, dict):
            mini_group["size"] = 1
            mini_group["defer_analysis_until_group_end"] = False
            reason["mini_group"] = mini_group
            self.conn.execute(
                "update flow_steps set selection_reason_json = ? where id = ?",
                (json.dumps(reason, ensure_ascii=False), step_id),
            )

    def _set_step_group_size(self, step_handle, size):
        step_row = self.conn.execute(
            "select id, selection_reason_json from flow_steps where step_handle = ?",
            (step_handle,),
        ).fetchone()
        reason = json.loads(step_row["selection_reason_json"] or "{}")
        mini_group = reason.get("mini_group")
        self.assertIsInstance(mini_group, dict)
        mini_group["size"] = int(size)
        mini_group["defer_analysis_until_group_end"] = int(size) > 1
        reason["mini_group"] = mini_group
        self.conn.execute(
            "update flow_steps set selection_reason_json = ? where id = ?",
            (json.dumps(reason, ensure_ascii=False), step_row["id"]),
        )
        self.conn.commit()

    def _activate_contract_for_projected_step(self, state):
        from learning_system import assessment_policy, assessment_store, question_fingerprints

        step = state["current_step"]
        step_row = self.conn.execute(
            "select * from flow_steps where step_handle = ? and position = ?",
            (step["step_handle"], step["position"]),
        ).fetchone()
        question = db.get_question(self.conn, step_row["question_id"])
        existing = assessment_store.active_contract_for_question(
            self.conn,
            question["id"],
            question["item_version"],
        )
        if existing:
            self.conn.execute(
                """
                update flow_steps
                set answer_contract_id = ?, answer_contract_version = ?,
                    answer_contract_digest_sha256 = ?
                where id = ?
                """,
                (
                    existing["id"],
                    existing["contract_version"],
                    existing["contract_digest_sha256"],
                    step_row["id"],
                ),
            )
            self.conn.commit()
            return existing
        contract = assessment_policy.build_answer_contract(question)
        assessment_policy.validate_contract(contract)
        contract_id = f"AC-runtime-v51-{question['id']}-{uuid.uuid4().hex[:6]}"
        versioned = {
            "id": contract_id,
            "stable_contract_id": contract_id,
            "contract_version": 1,
            **contract,
        }
        contract_digest = question_fingerprints.canonical_sha256(versioned)
        now = db.now_iso()
        self.conn.execute(
            """
            insert into answer_contracts(
              id, stable_contract_id, question_id, item_version, contract_version,
              contract_digest_sha256, question_digest_sha256, graph_version,
              question_bank_version, reference_solution_json, score_points_json,
              generator_version, review_record_id, review_receipt_json,
              review_receipt_sha256, fingerprint_policy_version,
              prompt_instance_fingerprint, core_structure_fingerprint,
              status, approved_at, activated_at, created_at, updated_at
            ) values (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?,
                      'assessment-contract-generator.v1', ?, ?, ?,
                      'question-fingerprint.v1', ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                contract_id,
                contract_id,
                question["id"],
                question["item_version"],
                contract_digest,
                question_fingerprints.canonical_sha256(question),
                step_row["graph_version"],
                step_row["question_bank_version"],
                db.json_dump(contract["reference_solution"]),
                db.json_dump(contract["score_points"]),
                step_row["review_record_id"],
                db.json_dump({"status": "accepted", "provider_mode": "live_model"}),
                "r" * 64,
                question_fingerprints.canonical_sha256(
                    {"question_id": question["id"], "instance": True}
                ),
                question_fingerprints.canonical_sha256(
                    {"node_id": question["node_id"], "core": True}
                ),
                now,
                now,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            update flow_steps
            set answer_contract_id = ?, answer_contract_version = 1,
                answer_contract_digest_sha256 = ?
            where id = ?
            """,
            (contract_id, contract_digest, step_row["id"]),
        )
        self.conn.commit()
        return versioned

    def _submit_projected_step(self, state, answer_text, key):
        from learning_system import daily_runtime

        step = state["current_step"]
        return self.runtime.persist_child_response(
            daily_runtime.CurrentStepSubmission(
                step_handle=step["step_handle"],
                position=step["position"],
                client_idempotency_key=key,
                answer_text=answer_text,
            )
        )

    def _submit_text(self, answer_text, key):
        from learning_system import daily_runtime

        self.runtime.persist_child_response(
            daily_runtime.CurrentStepSubmission(
                step_handle=self.step["step_handle"],
                position=self.step["position"],
                client_idempotency_key=key,
                answer_text=answer_text,
            )
        )
        attempt = self.conn.execute(
            "select * from attempts where client_idempotency_key = ?",
            (key,),
        ).fetchone()
        self.assertIsNotNone(attempt)
        return dict(attempt)

    def _v3_output(self, attempt, *, first_status="met", confidence=0.97):
        judgments = []
        for index, point in enumerate(self.contract["score_points"]):
            status = first_status if index == 0 else "met"
            judgments.append(
                {
                    "criterion_key": point["key"],
                    "status": status,
                    "child_evidence": (
                        "The child answer directly supports this criterion."
                        if status == "met"
                        else "The required relation is absent."
                    ),
                    "reason": (
                        "Grounded in the submitted answer."
                        if status == "met"
                        else "The criterion is not supported by the answer."
                    ),
                }
            )
        return {
            "schema_version": "2026-07-14.answer-review.v5.schema.v3",
            "criteria": judgments,
            "answer_gap": (
                "没有影响得分的数学差距。"
                if first_status == "met"
                else "第一条关键关系还没有写出来。"
            ),
            "improvement_direction": [
                "先写出题目需要的关键关系，再进行计算。"
            ],
            "expression_judgment": "按提交内容里的数学意图判断表达是否成立。",
            "teaching_explanation": "先使用正确关系，再检验结论。",
            "confidence": confidence,
        }

    def _live_route(self, model_router):
        return model_router.ModelRoute(
            agent_key="answer_analysis_agent",
            task="answer_review",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://unit.invalid/v1",
            api_key="test-only-key",
            timeout_seconds=120,
            model_params={"temperature": 0},
        )

    def test_review_short_group_advances_without_analysis_until_group_end(self):
        self._set_step_group_size(self.step["step_handle"], 2)

        with mock.patch.object(
            self.runtime,
            "_active_answer_contract_for_question",
            return_value=self.contract,
        ):
            next_state = self._submit_projected_step(
                self.started,
                "先写关键关系，再计算并检验。",
                "submit-runtime-v51-group-first",
            )

        self.assertEqual("current_step", next_state["child_state"])
        self.assertGreater(next_state["current_step"]["position"], self.step["position"])
        first_attempt = self.conn.execute(
            "select * from attempts where client_idempotency_key = ?",
            ("submit-runtime-v51-group-first",),
        ).fetchone()
        self.assertIsNotNone(first_attempt)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from background_jobs where attempt_id = ?",
            (first_attempt["id"],),
        ).fetchone()[0])
        first_step = self.conn.execute(
            "select status from flow_steps where id = ?",
            (first_attempt["flow_step_id"],),
        ).fetchone()
        self.assertEqual("completed", first_step["status"])

    def test_simple_foundation_node_uses_short_validation_profile(self):
        flow = dict(self.conn.execute(
            "select * from daily_flows where id = ?",
            (self.flow_id,),
        ).fetchone())

        review_reason = self.runtime._mini_group_selection_reason(
            {},
            flow=flow,
            step_type="question",
            group_role="review_short_set",
            target_node_id="M-G7-NUMBER-LINE",
            question_id=self.question["id"],
        )
        review_group = review_reason["mini_group"]
        self.assertEqual(2, review_group["size"])
        self.assertTrue(review_group["defer_analysis_until_group_end"])
        self.assertEqual("simple_foundation", review_group["practice_profile"])

        repair_reason = self.runtime._mini_group_selection_reason(
            {},
            flow=flow,
            step_type="micro_check",
            group_role="repair_micro_set",
            target_node_id="M-G7-NUMBER-LINE",
            question_id=self.question["id"],
        )
        repair_group = repair_reason["mini_group"]
        self.assertEqual(1, repair_group["size"])
        self.assertFalse(repair_group["defer_analysis_until_group_end"])
        self.assertEqual("simple_foundation", repair_group["practice_profile"])

    def test_simple_foundation_correct_answer_prioritizes_transfer_not_same_structure(self):
        flow = dict(self.conn.execute(
            "select * from daily_flows where id = ?",
            (self.flow_id,),
        ).fetchone())
        selected = {
            "question": {
                "id": "Q-simple-transfer",
                "node_id": "M-G7-NUMBER-LINE",
                "kind": "transfer_retest",
            },
            "review_record_id": "RR-simple-transfer",
            "candidate_packet": {
                "packet_id": "CP-simple-transfer",
                "packet_hash": "h" * 64,
                "candidates": [
                    {
                        "question_id": "Q-simple-transfer",
                        "kind": "transfer_retest",
                        "slot_role": "near_transfer",
                    }
                ],
            },
            "selection_reason": {"candidate_packet_id": "CP-simple-transfer"},
        }
        attempt = {
            "id": "ATT-simple-correct",
            "node_id": "M-G7-NUMBER-LINE",
            "result": "correct",
            "answer_analysis": {"evaluation_support": {"dominant_gap_dimensions": []}},
            "error_tags": [],
        }
        with mock.patch.object(
            self.runtime,
            "_select_question_for_node",
            return_value=selected,
        ) as select_question:
            planned = self.runtime._next_selection_after_attempt(flow, attempt=attempt)

        self.assertEqual("near_transfer_retest", planned["action"])
        self.assertIn("不难", planned["reason"])
        kwargs = select_question.call_args.kwargs
        self.assertEqual("simple_foundation_extension", kwargs["selection_intent"])
        self.assertNotIn("standard_example", kwargs["preferred_kinds"])
        self.assertIn("stretch_transfer", kwargs["preferred_kinds"])

    def test_high_score_light_formality_gap_does_not_force_reteach(self):
        contract = {
            "score_points": [
                {
                    "key": "answer",
                    "points": 4,
                    "dimension": "final_answer",
                    "required_for_pass": True,
                },
                {
                    "key": "execution",
                    "points": 4,
                    "dimension": "calculation",
                    "required_for_pass": True,
                },
                {
                    "key": "formal_check",
                    "points": 2,
                    "dimension": "check",
                    "required_for_pass": True,
                },
            ]
        }
        judgments = [
            {"criterion_key": "answer", "status": "met"},
            {"criterion_key": "execution", "status": "met"},
            {"criterion_key": "formal_check", "status": "not_met"},
        ]

        output = self.runtime._v51_deterministic_evaluation_output(
            contract=contract,
            criterion_judgments=judgments,
            score_out_of_10=8,
            question_passed=False,
        )

        self.assertEqual("emerging", output["mastery_recommendation"])
        self.assertFalse(output["planner_signal"]["needs_teaching_before_next"])
        self.assertEqual(
            "near_transfer_retest",
            output["planner_signal"]["next_evidence_goal"],
        )
        self.assertTrue(output["planner_signal"]["light_gap_only"])
        self.assertIn("核心掌握证据成立", output["reason"])

    def test_high_score_final_answer_gap_still_requires_teaching(self):
        contract = {
            "score_points": [
                {
                    "key": "answer",
                    "points": 2,
                    "dimension": "final_answer",
                    "required_for_pass": True,
                },
                {
                    "key": "execution",
                    "points": 8,
                    "dimension": "procedure",
                    "required_for_pass": True,
                },
            ]
        }
        judgments = [
            {"criterion_key": "answer", "status": "not_met"},
            {"criterion_key": "execution", "status": "met"},
        ]

        output = self.runtime._v51_deterministic_evaluation_output(
            contract=contract,
            criterion_judgments=judgments,
            score_out_of_10=8,
            question_passed=False,
        )

        self.assertEqual("weak", output["mastery_recommendation"])
        self.assertTrue(output["planner_signal"]["needs_teaching_before_next"])
        self.assertEqual(
            "same_structure_retest",
            output["planner_signal"]["next_evidence_goal"],
        )
        self.assertFalse(output["planner_signal"]["light_gap_only"])

    def test_high_score_model_relation_gap_still_requires_teaching(self):
        contract = {
            "score_points": [
                {
                    "key": "relation",
                    "points": 2,
                    "dimension": "model_relation",
                    "required_for_pass": True,
                },
                {
                    "key": "answer",
                    "points": 8,
                    "dimension": "final_answer",
                    "required_for_pass": True,
                },
            ]
        }
        judgments = [
            {"criterion_key": "relation", "status": "not_met"},
            {"criterion_key": "answer", "status": "met"},
        ]

        output = self.runtime._v51_deterministic_evaluation_output(
            contract=contract,
            criterion_judgments=judgments,
            score_out_of_10=8,
            question_passed=False,
        )

        self.assertEqual("weak", output["mastery_recommendation"])
        self.assertTrue(output["planner_signal"]["needs_teaching_before_next"])
        self.assertEqual(
            "same_structure_retest",
            output["planner_signal"]["next_evidence_goal"],
        )
        self.assertFalse(output["planner_signal"]["light_gap_only"])

    def test_group_final_submission_enqueues_attempts_and_waits_once(self):
        self._set_step_group_size(self.step["step_handle"], 2)
        with mock.patch.object(
            self.runtime,
            "_active_answer_contract_for_question",
            return_value=self.contract,
        ):
            second_state = self._submit_projected_step(
                self.started,
                "先写关键关系，再计算并检验。",
                "submit-runtime-v51-group-final-first",
            )
        self._activate_contract_for_projected_step(second_state)

        analyzing_state = self._submit_projected_step(
            second_state,
            "换一个条件也用同一条关系，再检查结果。",
            "submit-runtime-v51-group-final-second",
        )

        self.assertEqual("analyzing", analyzing_state["child_state"])
        attempts = self.conn.execute(
            """
            select id
            from attempts
            where client_idempotency_key in (?, ?)
            order by created_at, id
            """,
            (
                "submit-runtime-v51-group-final-first",
                "submit-runtime-v51-group-final-second",
            ),
        ).fetchall()
        self.assertEqual(2, len(attempts))
        jobs = self.conn.execute(
            """
            select id, attempt_id, job_type, depends_on_job_id, status, payload_json
            from background_jobs
            where flow_id = ?
            order by created_at, id
            """,
            (self.flow_id,),
        ).fetchall()
        self.assertEqual(1, len(jobs))
        self.assertEqual("group_answer_analysis", jobs[0]["job_type"])
        self.assertEqual(attempts[1]["id"], jobs[0]["attempt_id"])
        self.assertEqual("", jobs[0]["depends_on_job_id"] or "")
        self.assertEqual("queued", jobs[0]["status"])
        payload = json.loads(jobs[0]["payload_json"])
        self.assertEqual(2, payload["mini_group_size"])
        self.assertEqual(
            [attempts[0]["id"], attempts[1]["id"]],
            [item["attempt_id"] for item in payload["group_items"]],
        )

    def test_group_answer_analysis_uses_one_model_call_and_creates_group_feedback(self):
        from learning_system import assessment_store, daily_runtime, model_router

        self._set_step_group_size(self.step["step_handle"], 2)
        with mock.patch.object(
            self.runtime,
            "_active_answer_contract_for_question",
            return_value=self.contract,
        ):
            second_state = self._submit_projected_step(
                self.started,
                "先写关键关系，再计算并检验。",
                "submit-runtime-v51-group-handler-first",
            )
        self._activate_contract_for_projected_step(second_state)
        self._submit_projected_step(
            second_state,
            "换一个条件也用同一条关系，再检查结果。",
            "submit-runtime-v51-group-handler-second",
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (self.flow_id,),
        ).fetchone())
        payload = json.loads(job["payload_json"])
        output_items = []
        for group_item in payload["group_items"]:
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            output_items.append({
                "attempt_id": group_item["attempt_id"],
                "criteria": [
                    {
                        "criterion_key": point["key"],
                        "status": "met",
                        "child_evidence": "孩子写出了关键关系、计算和检查。",
                        "reason": "提交内容满足这个得分点。",
                    }
                    for point in contract["score_points"]
                ],
                "answer_gap": "没有影响得分的数学差距。",
                "improvement_direction": ["保持把关键关系、计算和检查连起来写。"],
                "expression_judgment": "表达能看出数学意图，判定有效。",
                "teaching_explanation": "先看清关系，再计算并检验结论。",
                "confidence": 0.96,
            })
        structured = model_router.StructuredJSONResult(
            value={
                "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                "items": output_items,
                "confidence": 0.96,
            },
            mode="json_schema",
            raw_response={"fixture": "group_answer_analysis"},
            endpoint="unit://structured-json",
        )

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ) as model_call:
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual(1, model_call.call_count)
        self.assertEqual("succeeded", result["job_status"], result)
        self.assertEqual("v5.1_true_group_single_model_call", result["pipeline_mode"])
        self.assertEqual("mini_group_assessment_feedback", result["next_action"])
        attempts = self.conn.execute(
            """
            select id, grading_status, analysis_status, result
            from attempts
            where client_idempotency_key in (?, ?)
            order by created_at, id
            """,
            (
                "submit-runtime-v51-group-handler-first",
                "submit-runtime-v51-group-handler-second",
            ),
        ).fetchall()
        self.assertEqual(["graded", "graded"], [row["grading_status"] for row in attempts])
        self.assertEqual(["valid", "valid"], [row["analysis_status"] for row in attempts])
        feedback_steps = self.conn.execute(
            "select * from flow_steps where flow_id = ? and step_type = 'assessment_feedback'",
            (self.flow_id,),
        ).fetchall()
        self.assertEqual(1, len(feedback_steps))

    def test_text_answer_uses_one_call_and_accepted_assessment_is_score_authority(self):
        from learning_system import assessment_store, model_router, semantic_agents

        attempt = self._submit_text(
            "I state the relation, calculate, and verify the result.",
            "submit-runtime-v51-one-call",
        )
        output = self._v3_output(attempt)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.97,
            output=output,
            route_meta={"source": "runtime-v51-unit-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as semantic_call, mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("v5.1 must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("v5.1 must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("v5.1 must not call teaching model"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual(1, semantic_call.call_count)
        self.assertEqual("succeeded", result["job_status"])
        accepted = assessment_store.accepted_assessment_for_attempt(
            self.conn,
            attempt["id"],
            int(attempt["attempt_version"]),
        )
        self.assertIsNotNone(accepted)
        self.assertEqual(10, accepted["score_out_of_10"])
        self.assertTrue(accepted["question_passed"])
        current_attempt = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual(2, current_attempt["score_points"])
        self.assertEqual(2, current_attempt["max_points"])
        self.assertEqual("correct", current_attempt["result"])
        validation = self.conn.execute(
            """
            select assessment_id, assessment_version, assessment_digest_sha256
            from evidence_validations where attempt_id = ?
            order by created_at desc limit 1
            """,
            (attempt["id"],),
        ).fetchone()
        self.assertEqual(accepted["id"], validation["assessment_id"])
        self.assertEqual(accepted["assessment_version"], validation["assessment_version"])
        self.assertEqual(
            accepted["assessment_digest_sha256"],
            validation["assessment_digest_sha256"],
        )
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from background_jobs
            where attempt_id = ?
              and job_type in ('evaluation_update','planner_decision','teaching_generation')
            """,
            (attempt["id"],),
        ).fetchone()[0])
        child_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        self.assertEqual("assessment_feedback", child_state["child_state"])
        feedback = child_state["current_step"]["assessment_feedback"]
        self.assertEqual("10/10", feedback["score_label"])
        self.assertTrue(feedback["reference_answer"])
        self.assertEqual(output["answer_gap"], feedback["answer_gap"])
        self.assertEqual(
            output["improvement_direction"],
            feedback["improvement_direction"],
        )
        self.assertEqual(
            output["expression_judgment"],
            feedback["expression_judgment"],
        )
        mastery = self.conn.execute(
            """
            select decision, new_status_code
            from mastery_decisions
            where source_attempt_ids_json like ?
            order by created_at desc limit 1
            """,
            (f"%{attempt['id']}%",),
        ).fetchone()
        self.assertEqual("basic_understanding", mastery["decision"])
        self.assertEqual("B", mastery["new_status_code"])
        self.assertEqual(1, self.conn.execute(
            "select count(*) from next_step_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        feedback_step = child_state["current_step"]
        continued = self.runtime.continue_current_step(
            step_handle=feedback_step["step_handle"],
            position=feedback_step["position"],
        )
        self.assertIn(continued["child_state"], {"current_step", "summary"})
        self.assertEqual(1, self.conn.execute(
            "select count(*) from next_step_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        retried = self.runtime.continue_current_step(
            step_handle=feedback_step["step_handle"],
            position=feedback_step["position"],
        )
        self.assertEqual(continued["child_state"], retried["child_state"])
        replay = self.runtime._replay_answer_analysis_refs_for_processed_attempt(
            job,
            db.get_attempt(self.conn, attempt["id"]),
        )
        self.assertEqual("assessment_feedback", replay["next_action"])
        self.assertEqual(accepted["id"], replay["assessment_id"])
        self.assertEqual(result["feedback_step_id"], replay["feedback_step_id"])

    def test_english_answer_feedback_is_replaced_before_child_projection(self):
        from learning_system import model_router, semantic_agents

        attempt = self._submit_text(
            "E=-0.8, E<0",
            "submit-runtime-v51-english-feedback",
        )
        output = self._v3_output(attempt)
        output["answer_gap"] = (
            "Missing the requested error-spotting part: it does not state the common wrong step."
        )
        output["improvement_direction"] = [
            "Add one sentence identifying the easiest mistake.",
            "Briefly state the number-line rule.",
        ]
        output["expression_judgment"] = (
            "The calculation and comparison are concise and mathematically clear."
        )
        output["teaching_explanation"] = (
            "Use the approved relation, then verify the conclusion."
        )
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.97,
            output=output,
            route_meta={"source": "runtime-v51-unit-english-feedback-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"])
        child_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        feedback = child_state["current_step"]["assessment_feedback"]
        rendered = json.dumps(feedback, ensure_ascii=False)
        for forbidden in ("Missing", "Add one sentence", "Briefly", "The calculation"):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("关键说明", feedback["answer_gap"])
        self.assertTrue(
            all(re.search(r"[\u4e00-\u9fff]", item) for item in feedback["improvement_direction"])
        )
        self.assertIn("数学意图", feedback["expression_judgment"])

    def test_semantic_checkpoint_rolls_back_with_failed_assessment_and_retry_calls_model_again(self):
        from learning_system import assessment_store, model_router, semantic_agents

        attempt = self._submit_text(
            "I state the relation, calculate, and verify the result.",
            "submit-runtime-v51-checkpoint-replay",
        )
        output = self._v3_output(attempt)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.97,
            output=output,
            route_meta={"source": "runtime-v51-checkpoint-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())
        real_accept = assessment_store.accept_assessment

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as semantic_call, mock.patch.object(
            assessment_store,
            "accept_assessment",
            side_effect=RuntimeError("crash after semantic checkpoint"),
        ):
            with self.assertRaisesRegex(RuntimeError, "crash after semantic checkpoint"):
                self.runtime._handle_answer_analysis_job(job)

        checkpoint = self.conn.execute(
            """
            select semantic_output_digest_sha256, semantic_output_json
            from attempt_assessments
            where attempt_id = ?
            """,
            (attempt["id"],),
        ).fetchone()
        self.assertIsNone(checkpoint)
        self.assertEqual(1, semantic_call.call_count)

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as retry_semantic_call, mock.patch.object(
            assessment_store,
            "accept_assessment",
            side_effect=real_accept,
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual(1, retry_semantic_call.call_count)
        self.assertEqual("succeeded", result["job_status"])
        accepted = assessment_store.accepted_assessment_for_attempt(
            self.conn,
            attempt["id"],
            int(attempt["attempt_version"]),
        )
        self.assertIsNotNone(accepted)
        self.assertEqual(10, accepted["score_out_of_10"])

    def test_v51_missing_answer_contract_fails_closed_without_legacy_chain(self):
        from learning_system import model_router, semantic_agents

        self.conn.execute(
            """
            update flow_steps
            set answer_contract_id = null,
                answer_contract_version = null,
                answer_contract_digest_sha256 = null
            where step_handle = ?
            """,
            (self.step["step_handle"],),
        )
        self.conn.commit()
        attempt = self._submit_text(
            "I wrote a normal answer.",
            "submit-runtime-v51-missing-contract",
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())
        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("missing v5.1 contract must not call answer model"),
        ), mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("missing v5.1 contract must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("missing v5.1 contract must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("missing v5.1 contract must not call teaching model"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("blocked", result["job_status"])
        self.assertEqual("v5.1_answer_contract_missing", result["reason"])
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from background_jobs
            where attempt_id = ?
              and job_type in ('evaluation_update','planner_decision','teaching_generation')
            """,
            (attempt["id"],),
        ).fetchone()[0])

    def test_i_do_not_know_text_queues_model_review_and_creates_no_scored_assessment_on_submit(self):
        from learning_system import semantic_agents

        with mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("submit must enqueue async review without calling GPT inline"),
        ) as semantic_call:
            attempt = self._submit_text(
                "我不会",
                "submit-runtime-v51-stuck",
            )

        self.assertEqual(0, semantic_call.call_count)
        self.assertEqual("v3_text", attempt["answer_source"])
        self.assertEqual("pending_review", attempt["grading_status"])
        self.assertEqual("missing", attempt["analysis_status"])
        self.assertEqual(1, self.conn.execute(
            "select count(*) from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])

    def test_partial_v51_assessment_shows_feedback_and_routes_to_repair_without_more_models(self):
        from learning_system import model_router, semantic_agents

        attempt = self._submit_text(
            "I wrote a result but missed the first required relation.",
            "submit-runtime-v51-partial-feedback",
        )
        output = self._v3_output(attempt, first_status="not_met")
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.97,
            output=output,
            route_meta={"source": "runtime-v51-partial-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as semantic_call, mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("v5.1 repair routing must be deterministic"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("v5.1 repair routing must be deterministic"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("v5.1 repair explanation comes from the one answer call"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual(1, semantic_call.call_count)
        self.assertEqual("assessment_feedback", result["next_action"])
        child_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        self.assertEqual("assessment_feedback", child_state["child_state"])
        self.assertNotEqual("10/10", child_state["current_step"]["assessment_feedback"]["score_label"])
        decision = self.conn.execute(
            "select action from next_step_decisions where id = ?",
            (result["next_step_decision_id"],),
        ).fetchone()
        self.assertEqual("same_structure_retest", decision["action"])
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from background_jobs
            where attempt_id = ?
              and job_type in ('evaluation_update','planner_decision','teaching_generation')
            """,
            (attempt["id"],),
        ).fetchone()[0])

    def test_low_confidence_v51_review_clarifies_without_score_or_mastery(self):
        from learning_system import assessment_store, model_router, semantic_agents

        attempt = self._submit_text(
            "The written work is too unclear to judge safely.",
            "submit-runtime-v51-low-confidence-clarify",
        )
        output = self._v3_output(attempt, first_status="unclear", confidence=0.2)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.2,
            output=output,
            route_meta={"source": "runtime-v51-low-confidence-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as semantic_call, mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("unclear evidence must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("unclear evidence must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("unclear evidence must not call teaching model"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual(1, semantic_call.call_count)
        self.assertEqual("clarify_evidence", result["next_action"])
        self.assertIsNone(
            assessment_store.accepted_assessment_for_attempt(
                self.conn,
                attempt["id"],
                int(attempt["attempt_version"]),
            )
        )
        pending = self.conn.execute(
            """
            select status, score_out_of_10, semantic_output_digest_sha256
            from attempt_assessments
            where attempt_id = ?
            """,
            (attempt["id"],),
        ).fetchone()
        self.assertEqual("pending", pending["status"])
        self.assertIsNone(pending["score_out_of_10"])
        self.assertTrue(pending["semantic_output_digest_sha256"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        validation = self.conn.execute(
            """
            select gate_status, predicate_result_json, assessment_id
            from evidence_validations
            where attempt_id = ?
            order by created_at desc limit 1
            """,
            (attempt["id"],),
        ).fetchone()
        self.assertNotEqual("passed", validation["gate_status"])
        self.assertIsNone(validation["assessment_id"])
        predicate = db.json_load(validation["predicate_result_json"], {})
        self.assertFalse(predicate.get("usable"))
        child_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        self.assertEqual("clarify_evidence", child_state["child_state"])
        self.assertEqual("clarification", child_state["current_step"]["answer_input_mode"])
        clarify_steps_before = self.conn.execute(
            "select count(*) from flow_steps where flow_id = ? and step_type = 'clarify_evidence'",
            (self.flow_id,),
        ).fetchone()[0]
        clarify_decisions_before = self.conn.execute(
            "select count(*) from next_step_decisions where flow_id = ? and action = 'clarify_evidence'",
            (self.flow_id,),
        ).fetchone()[0]

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("retry must reuse unclear semantic checkpoint"),
        ):
            replay = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("clarify_evidence", replay["next_action"])
        self.assertEqual("existing_clarify_step_replayed", replay["reason"])
        self.assertEqual(clarify_steps_before, self.conn.execute(
            "select count(*) from flow_steps where flow_id = ? and step_type = 'clarify_evidence'",
            (self.flow_id,),
        ).fetchone()[0])
        self.assertEqual(clarify_decisions_before, self.conn.execute(
            "select count(*) from next_step_decisions where flow_id = ? and action = 'clarify_evidence'",
            (self.flow_id,),
        ).fetchone()[0])

    def test_unclear_v51_criterion_clarifies_without_model_retry(self):
        from learning_system import assessment_store, model_router, semantic_agents

        attempt = self._submit_text(
            "I gave an answer, but one key step is ambiguous.",
            "submit-runtime-v51-unclear-criterion",
        )
        output = self._v3_output(attempt, first_status="unclear", confidence=0.91)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.91,
            output=output,
            route_meta={"source": "runtime-v51-unclear-criterion-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ) as semantic_call, mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("unclear criterion must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("unclear criterion must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("unclear criterion must not call teaching model"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual(1, semantic_call.call_count)
        self.assertEqual("clarify_evidence", result["next_action"])
        self.assertIsNone(
            assessment_store.accepted_assessment_for_attempt(
                self.conn,
                attempt["id"],
                int(attempt["attempt_version"]),
            )
        )
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        pending = self.conn.execute(
            """
            select status, score_out_of_10, semantic_output_digest_sha256
            from attempt_assessments
            where attempt_id = ?
            """,
            (attempt["id"],),
        ).fetchone()
        self.assertEqual("pending", pending["status"])
        self.assertIsNone(pending["score_out_of_10"])
        self.assertTrue(pending["semantic_output_digest_sha256"])

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("retry must reuse unclear semantic checkpoint"),
        ):
            replay = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("clarify_evidence", replay["next_action"])
        self.assertEqual("existing_clarify_step_replayed", replay["reason"])

    def test_v51_accepted_assessment_with_unusable_evidence_does_not_drive_flow(self):
        from learning_system import assessment_store, evidence_gate, model_router, semantic_agents

        attempt = self._submit_text(
            "I state the relation, calculate, and verify the result.",
            "submit-runtime-v51-evidence-rejected",
        )
        output = self._v3_output(attempt)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.97,
            output=output,
            route_meta={"source": "runtime-v51-evidence-rejected-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (attempt["id"],),
        ).fetchone())
        rejected_validation = evidence_gate.EvidenceValidationResult(
            validation_id="EV-rejected-v51-unit",
            gate_status="rejected",
            predicate=evidence_gate.EvidencePredicateResult(
                usable=False,
                projection_status="rejected",
                failed_fields=("graph_version",),
                report_label="stale_graph_version",
            ),
        )

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ), mock.patch.object(
            evidence_gate.EvidenceGate,
            "validate_attempt",
            return_value=rejected_validation,
        ), mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("rejected evidence must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("rejected evidence must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("rejected evidence must not call teaching model"),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("blocked", result["job_status"])
        self.assertEqual("stale_graph_version", result["report_label"])
        self.assertIsNotNone(
            assessment_store.accepted_assessment_for_attempt(
                self.conn,
                attempt["id"],
                int(attempt["attempt_version"]),
            )
        )
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from flow_steps
            where flow_id = ? and step_type = 'assessment_feedback'
            """,
            (self.flow_id,),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from next_step_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        flow = dict(self.runtime._flow_by_id(self.flow_id))
        self.assertEqual("blocked", flow["status"])

    def test_clarify_stuck_submission_enters_deterministic_teaching_repair(self):
        from learning_system import daily_runtime, model_router, semantic_agents

        first_attempt = self._submit_text(
            "The written work is too unclear to judge safely.",
            "submit-runtime-v51-clarify-then-stuck-first",
        )
        output = self._v3_output(first_attempt, first_status="unclear", confidence=0.2)
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.2,
            output=output,
            route_meta={"source": "runtime-v51-clarify-then-stuck-fixture"},
            prompt_version_id="2026-07-20.answer-review.v5.prompt.v4",
            response_schema_version=output["schema_version"],
        )
        first_job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
            (first_attempt["id"],),
        ).fetchone())
        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._live_route(model_router),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ):
            self.runtime._handle_answer_analysis_job(first_job)

        clarify_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        self.assertEqual("clarify_evidence", clarify_state["child_state"])
        clarify_step = clarify_state["current_step"]
        self.runtime.persist_child_response(
            daily_runtime.CurrentStepSubmission(
                step_handle=clarify_step["step_handle"],
                position=clarify_step["position"],
                client_idempotency_key="submit-runtime-v51-clarify-stuck",
                answer_text="我还是不会",
                stuck=True,
            )
        )
        clarify_attempt = dict(self.conn.execute(
            "select * from attempts where client_idempotency_key = ?",
            ("submit-runtime-v51-clarify-stuck",),
        ).fetchone())
        clarify_job = dict(self.conn.execute(
            "select * from background_jobs where attempt_id = ? and job_type = 'stuck_interruption'",
            (clarify_attempt["id"],),
        ).fetchone())

        with mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("explicit stuck must not call answer model"),
        ) as answer_model, mock.patch.object(
            semantic_agents,
            "call_evaluation_agent",
            side_effect=AssertionError("clarify stuck must not call evaluation model"),
        ), mock.patch.object(
            semantic_agents,
            "call_planner_agent",
            side_effect=AssertionError("clarify stuck must not call planner model"),
        ), mock.patch.object(
            semantic_agents,
            "call_teaching_agent",
            side_effect=AssertionError("clarify stuck must not call teaching model"),
        ):
            result = self.runtime._handle_stuck_interruption_job(clarify_job)

        self.assertEqual(0, answer_model.call_count)
        self.assertEqual("teaching_repair", result["next_action"])
        child_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(self.flow_id)
        )
        self.assertEqual("teaching", child_state["child_state"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{clarify_attempt['id']}%",),
        ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
