"""Question generation & verification pipeline core tests (objective ③).

Contract under test: `learning_system/question_generation_service.py` per
docs/design/specs/2026-08-20-question-bank-contract.md (§3 每节点矩阵、
§4 校验门禁、§5 元数据派生、§6 生成管线) + 图谱 question_generation 契约.

The generator is injected (`generate_fn`); tests use fakes that produce real
sympy-checkable prompts, so the verification gate runs against the real
`learning_system.answer_verification.verify_expected_answer`.

Run: python3 -m unittest tests.test_question_generation_service -v
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from learning_system import db
from learning_system.answer_verification import verify_expected_answer
from learning_system.error_tags import CANONICAL_ERROR_TAGS

from learning_system import question_generation_service as qg  # noqa: E402

QUESTION_ITEM_VERSION = "2026-08-20.v1"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def make_node(node_id: str, **overrides) -> dict:
    node = {
        "id": node_id,
        "name": node_id,
        "stage": "pre",
        "domain": "math",
        "priority": "P0",
        "essence_for_child": "本质：位值对齐。",
        "prerequisites": [],
        "unlocks": [],
        "question_types": [],
        "diagnostic_probes": [],
        "error_diagnosis": {},
        "question_generation": {
            "minimum_daily_set": "1道标准题 + 2道变式题 + 1道错因复测题",
            "variant_ladder": [
                "L1 识别：判断考点/规则",
                "L2 套用：直接计算或列式",
                "L3 变式：换语境、换数字、加干扰条件",
                "L4 迁移：和前后知识点混合",
            ],
            "avoid": "同一套路连续刷十几题。",
            "seed_question_types": ["计算题", "应用题", "概念题"],
        },
    }
    node.update(overrides)
    return node


FIXTURE_GRAPH = {
    "metadata": {"version": "test"},
    "nodes": [
        make_node(
            "N-CALC",
            name="小数加减",
            prerequisites=["N-PRE-A", "N-PRE-B"],
            unlocks=["N-NEXT-C", "N-NEXT-D"],
            question_types=["小数加减", "小数应用题"],
            diagnostic_probes=["2道小数加减，1道小数乘除"],
            error_diagnosis={
                "likely_error_tags": ["calculation_or_symbol"],
                "rollback_to": ["N-PRE-A"],
            },
            question_generation={
                "minimum_daily_set": "1道标准题 + 2道变式题 + 1道错因复测题",
                "variant_ladder": [
                    "L1 识别：判断考点/规则",
                    "L2 套用：直接计算或列式",
                    "L3 变式：换语境、换数字、加干扰条件",
                    "L4 迁移：和前后知识点混合",
                ],
                "avoid": "避免模板反射。",
                "seed_question_types": ["小数加减", "小数乘除", "小数与分数互化"],
            },
        ),
        make_node("N-PRE-A"),
        make_node("N-PRE-B"),
        make_node("N-NEXT-C"),
        make_node("N-NEXT-D"),
    ],
    "prerequisite_edges": [
        {
            "from": "N-PRE-A",
            "to": "N-CALC",
            "type": "prerequisite",
            "prereq_strength": "strong",
            "strength_rationale": "整数是小数运算的直接基础",
        },
        {
            "from": "N-PRE-B",
            "to": "N-CALC",
            "type": "prerequisite",
            "prereq_strength": "soft",
            "strength_rationale": "弱相关",
        },
    ],
    "edges": [],
}


def seed_graph(conn: sqlite3.Connection, graph: dict = FIXTURE_GRAPH) -> None:
    for node in graph["nodes"]:
        conn.execute(
            """
            insert or replace into graph_nodes(
              id, name, stage, domain, priority, summer_mode, sequence_band,
              prerequisites_json, unlocks_json, raw_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node["id"],
                node.get("name", ""),
                node.get("stage", ""),
                node.get("domain", ""),
                node.get("priority", ""),
                "summer",
                1,
                json.dumps(node.get("prerequisites", []), ensure_ascii=False),
                json.dumps(node.get("unlocks", []), ensure_ascii=False),
                json.dumps(node, ensure_ascii=False),
            ),
        )
    conn.commit()


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    db.init_schema(conn)
    seed_graph(conn)
    return conn


# ---------------------------------------------------------------------------
# fake generators (real sympy-checkable prompts)
# ---------------------------------------------------------------------------


def fake_correct(batch_spec: dict) -> list[dict]:
    """Every item verified: prompt embeds a calculation whose value is the answer."""
    return [
        {
            "item_index": i,
            "prompt": f"计算：3 + {i} 的结果",
            "expected_answer": str(3 + i),
            "solution_steps": ["先看数位", "再计算"],
            "rubric": [{"criterion": "结果正确", "points": 2}],
        }
        for i, _ in enumerate(batch_spec["items"])
    ]


class RecordingFake:
    """Records every batch spec it receives; answers are scriptable.

    - wrong_item: which item index (within a batch) gets a wrong answer on the
      first (non-retry) call.
    - always_wrong: the wrong answer persists on retry calls too (→ discard).
    - unverifiable_items: item indexes answered with a non-machine-checkable
      concept prompt (→ marked unverifiable, kept).
    """

    def __init__(self, wrong_item: int = 0, always_wrong: bool = False, unverifiable_items=(), wrong_batches=(1,)):
        self.calls: list[dict] = []
        self.wrong_item = wrong_item
        self.always_wrong = always_wrong
        self.unverifiable_items = set(unverifiable_items)
        self.wrong_batches = set(wrong_batches)

    def __call__(self, batch_spec: dict) -> list[dict]:
        self.calls.append(batch_spec)
        batch_index = batch_spec.get("batch_index", 1)
        out = []
        for i, _ in enumerate(batch_spec["items"]):
            if i in self.unverifiable_items:
                out.append(
                    {
                        "item_index": i,
                        "prompt": "判断并说明理由：3 比 2 大对吗？",
                        "expected_answer": "对",
                    }
                )
            elif (
                i == self.wrong_item
                and batch_index in self.wrong_batches
                and (self.always_wrong or not batch_spec.get("retry"))
            ):
                out.append({"item_index": i, "prompt": f"计算：3 + {i} 的结果", "expected_answer": "999"})
            else:
                out.append({"item_index": i, "prompt": f"计算：3 + {i} 的结果", "expected_answer": str(3 + i)})
        return out


# ---------------------------------------------------------------------------
# node_batch_specs
# ---------------------------------------------------------------------------


class NodeBatchSpecsTestCase(unittest.TestCase):
    def test_graph_dict_input_honors_contract_matrix(self):
        specs = qg.node_batch_specs(FIXTURE_GRAPH, "N-CALC")
        self.assertEqual(5, len(specs))
        for spec in specs:
            self.assertEqual("N-CALC", spec["node_id"])
            self.assertGreaterEqual(len(spec["items"]), 3)
            self.assertLessEqual(len(spec["items"]), 5)
        items = [item for spec in specs for item in spec["items"]]
        self.assertEqual(15, len(items))

        std = [item for item in items if item["matrix_label"] == "标准例题"]
        self.assertEqual(1, len(std))
        self.assertEqual(("medium", "core", "L2"), (
            std[0]["difficulty"], std[0]["purpose_role"], std[0]["variant_level"],
        ))

        l1 = [item for item in items if item["matrix_label"] == "变式L1识别"]
        self.assertEqual(2, len(l1))
        self.assertTrue(all(item["difficulty"] == "easy" for item in l1))
        self.assertTrue(all(item["purpose_role"] == "core" for item in l1))

        l4 = [item for item in items if item["matrix_label"] == "变式L4迁移"]
        self.assertEqual(2, len(l4))
        for item in l4:
            self.assertEqual(("hard", "transfer", "L4"), (
                item["difficulty"], item["purpose_role"], item["variant_level"],
            ))

        probe_labels = {"检测题", "复测题", "诊断题"}
        probe_items = [item for item in items if item["matrix_label"] in probe_labels]
        self.assertEqual(6, len(probe_items))
        self.assertTrue(all(item["diagnostic_probe"] for item in probe_items))

        difficulties = {item["difficulty"] for item in items}
        self.assertEqual({"easy", "medium", "hard"}, difficulties)
        roles = {item["purpose_role"] for item in items}
        self.assertEqual({"core", "transfer"}, roles)

    def test_graph_dict_input_carries_generator_context(self):
        specs = qg.node_batch_specs(FIXTURE_GRAPH, "N-CALC")
        spec0 = specs[0]
        self.assertTrue(spec0["variant_ladder"])
        self.assertTrue(spec0["minimum_daily_set"])
        self.assertTrue(spec0["avoid"])
        self.assertEqual("小数加减", spec0["node_name"])
        for item in spec0["items"]:
            self.assertIn(item["question_type"], {"小数加减", "小数乘除", "小数与分数互化"})
            self.assertTrue(item["seed_question_type"])
            self.assertTrue(item["ladder_description"].startswith(item["variant_level"] + " "))

    def test_conn_input_reads_graph_node(self):
        conn = make_conn()
        self.addCleanup(conn.close)
        specs = qg.node_batch_specs(conn, "N-CALC")
        items = [item for spec in specs for item in spec["items"]]
        self.assertEqual(15, len(items))
        self.assertEqual({"easy", "medium", "hard"}, {item["difficulty"] for item in items})

    def test_unknown_node_raises(self):
        with self.assertRaises(KeyError):
            qg.node_batch_specs(FIXTURE_GRAPH, "N-NOT-THERE")
        conn = make_conn()
        self.addCleanup(conn.close)
        with self.assertRaises(KeyError):
            qg.node_batch_specs(conn, "N-NOT-THERE")


# ---------------------------------------------------------------------------
# metadata derivation helpers
# ---------------------------------------------------------------------------


class MetadataDerivationTestCase(unittest.TestCase):
    def test_rollback_strong_priority_from_graph(self):
        node = next(n for n in FIXTURE_GRAPH["nodes"] if n["id"] == "N-CALC")
        relations = qg.derive_rollback_candidates(node, FIXTURE_GRAPH)
        self.assertEqual(["N-PRE-A"], [r["node_id"] for r in relations])
        self.assertEqual("strong", relations[0]["strength"])

    def test_rollback_falls_back_to_node_prerequisites_order(self):
        node = next(n for n in FIXTURE_GRAPH["nodes"] if n["id"] == "N-CALC")
        relations = qg.derive_rollback_candidates(node)
        self.assertEqual(["N-PRE-A", "N-PRE-B"], [r["node_id"] for r in relations])

    def test_rollback_falls_back_to_error_diagnosis(self):
        node = make_node("N-ROOT", error_diagnosis={"rollback_to": ["N-PRE-X"]})
        relations = qg.derive_rollback_candidates(node)
        self.assertEqual(["N-PRE-X"], [r["node_id"] for r in relations])

    def test_error_tags_from_canonical_set(self):
        tags = qg.derive_error_tags({"question_type": "小数加减", "matrix_label": "标准例题", "kind": "standard_example"})
        self.assertTrue(tags)
        self.assertLessEqual(len(tags), 2)
        self.assertTrue(set(tags) <= CANONICAL_ERROR_TAGS)
        self.assertIn("calculation_or_symbol", tags)

    def test_error_tags_application_mapping(self):
        tags = qg.derive_error_tags({"question_type": "小数应用题", "matrix_label": "变式L2套用", "kind": "variant"})
        self.assertIn("modeling_or_reading", tags)
        self.assertTrue(set(tags) <= CANONICAL_ERROR_TAGS)

    def test_secondary_node_ids_only_for_transfer(self):
        node = next(n for n in FIXTURE_GRAPH["nodes"] if n["id"] == "N-CALC")
        transfer = qg.derive_secondary_node_ids({"purpose_role": "transfer"}, node)
        self.assertEqual(["N-PRE-A", "N-PRE-B", "N-NEXT-C", "N-NEXT-D"], transfer)
        core = qg.derive_secondary_node_ids({"purpose_role": "core"}, node)
        self.assertEqual([], core)

    def test_estimate_minutes_within_1_8(self):
        for difficulty in ("easy", "medium", "hard"):
            for purpose_role in ("core", "transfer"):
                minutes = qg.estimate_minutes(difficulty, purpose_role, "variant")
                self.assertGreaterEqual(minutes, 1)
                self.assertLessEqual(minutes, 8)
        self.assertEqual(2, qg.estimate_minutes("easy", "core", "variant"))
        self.assertEqual(7, qg.estimate_minutes("hard", "transfer", "variant"))


# ---------------------------------------------------------------------------
# generate_node_bank pipeline
# ---------------------------------------------------------------------------


class GenerateNodeBankTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def _rows(self):
        return self.conn.execute(
            "select * from question_items where node_id = 'N-CALC'"
        ).fetchall()

    def _stats(self, result):
        return {k: result[k] for k in ("generated", "verified", "mismatch_discarded", "unverifiable", "ingested")}

    def test_verified_path_ingests_with_verification_state(self):
        result = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake_correct)
        self.assertEqual(
            {"generated": 15, "verified": 15, "mismatch_discarded": 0, "unverifiable": 0, "ingested": 15},
            self._stats(result),
        )
        rows = self._rows()
        self.assertEqual(15, len(rows))
        for row in rows:
            self.assertEqual("verified", row["answer_verification"])
        ids = {row["id"] for row in rows}
        self.assertEqual(15, len(ids))
        self.assertIn("Q-N-CALC-B1-I0", ids)

    def test_mismatch_retried_then_corrected(self):
        fake = RecordingFake(wrong_item=0)
        result = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake)
        self.assertEqual(15, result["verified"])
        self.assertEqual(0, result["mismatch_discarded"])
        self.assertEqual(15, result["ingested"])
        retry_calls = [spec for spec in fake.calls if spec.get("retry")]
        self.assertEqual(1, len(retry_calls))
        self.assertTrue(retry_calls[0]["mismatch_reason"])
        row = self.conn.execute(
            "select answer_verification, expected_answer from question_items where id = 'Q-N-CALC-B1-I0'"
        ).fetchone()
        self.assertEqual("verified", row["answer_verification"])
        self.assertEqual("3", row["expected_answer"])

    def test_mismatch_discarded_after_max_retries(self):
        fake = RecordingFake(wrong_item=0, always_wrong=True)
        result = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake)
        self.assertEqual(1, result["mismatch_discarded"])
        self.assertEqual(14, result["ingested"])
        self.assertEqual(14, result["verified"])
        row = self.conn.execute("select 1 from question_items where id = 'Q-N-CALC-B1-I0'").fetchone()
        self.assertIsNone(row)
        retry_calls = [spec for spec in fake.calls if spec.get("retry")]
        self.assertEqual(2, len(retry_calls))
        for spec in retry_calls:
            self.assertEqual(1, len(spec["items"]))
            self.assertEqual("Q-N-CALC-B1-I0", qg.question_id_for("N-CALC", spec["batch_index"], spec["items"][0]["item_index"]))

    def test_unverifiable_kept_marked(self):
        fake = RecordingFake(unverifiable_items=(1,))
        result = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake)
        self.assertEqual(5, result["unverifiable"])
        self.assertEqual(10, result["verified"])
        self.assertEqual(15, result["ingested"])
        by_id = {row["id"]: row["answer_verification"] for row in self._rows()}
        self.assertEqual("unverifiable", by_id["Q-N-CALC-B1-I1"])
        self.assertEqual("verified", by_id["Q-N-CALC-B1-I0"])

    def test_verify_false_marks_pending(self):
        result = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake_correct, verify=False)
        self.assertEqual(15, result["ingested"])
        rows = self._rows()
        self.assertTrue(all(row["answer_verification"] == "pending" for row in rows))

    def test_metadata_derived_and_ingested(self):
        qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake_correct)
        rows = self.conn.execute(
            """
            select id, question_type, purpose_role, error_tags_json,
                   rollback_candidate_node_ids_json, rollback_candidate_relations_json,
                   secondary_node_ids_json, estimated_minutes
            from question_items where node_id = 'N-CALC'
            """
        ).fetchall()
        self.assertEqual(15, len(rows))
        for row in rows:
            tags = json.loads(row["error_tags_json"])
            self.assertTrue(tags)
            self.assertLessEqual(len(tags), 2)
            self.assertTrue(set(tags) <= CANONICAL_ERROR_TAGS)
            rollback = json.loads(row["rollback_candidate_node_ids_json"])
            self.assertTrue(rollback)
            for node_id in rollback:
                self.assertIsNotNone(
                    self.conn.execute("select 1 from graph_nodes where id = ?", (node_id,)).fetchone(),
                    f"rollback candidate {node_id} not in graph",
                )
            relations = json.loads(row["rollback_candidate_relations_json"])
            self.assertEqual([r["node_id"] for r in relations], rollback)
            self.assertGreaterEqual(row["estimated_minutes"], 1)
            self.assertLessEqual(row["estimated_minutes"], 8)
            if row["purpose_role"] == "transfer":
                secondary = json.loads(row["secondary_node_ids_json"])
                self.assertTrue(secondary, "transfer question must mark before/after nodes")
                for node_id in secondary:
                    self.assertIsNotNone(
                        self.conn.execute("select 1 from graph_nodes where id = ?", (node_id,)).fetchone()
                    )
            else:
                self.assertEqual([], json.loads(row["secondary_node_ids_json"]))

    def test_generator_count_mismatch_raises(self):
        def bad(batch_spec):
            return [{"prompt": "计算：1 + 1 的结果", "expected_answer": "2"} for _ in batch_spec["items"][:-1]]

        with self.assertRaises(ValueError):
            qg.generate_node_bank(self.conn, "N-CALC", generate_fn=bad)

    def test_rerun_is_idempotent(self):
        first = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake_correct)
        second = qg.generate_node_bank(self.conn, "N-CALC", generate_fn=fake_correct)
        self.assertEqual(first["ingested"], second["ingested"])
        rows = self._rows()
        self.assertEqual(15, len(rows))
        self.assertEqual(15, len({row["id"] for row in rows}))
        for row in rows:
            self.assertIn(row["difficulty"], {"easy", "medium", "hard"})
            self.assertEqual("verified", row["answer_verification"])
            self.assertIn(row["purpose_role"], {"core", "transfer"})


# ---------------------------------------------------------------------------
# validate_node_bank_contract
# ---------------------------------------------------------------------------


def insert_question_row(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    node_id: str = "N-CALC",
    question_type: str = "计算题",
    kind: str = "variant",
    difficulty: str = "medium",
    purpose_role: str = "core",
    answer_verification: str = "verified",
) -> None:
    conn.execute(
        """
        insert into question_items(
          id, item_version, source_type, node_id, secondary_node_ids_json, kind,
          question_type, variant_level, production_category, prompt, answer_format,
          expected_answer, rubric_json, solution_steps_json, error_tags_json,
          rollback_candidate_node_ids_json, rollback_candidate_relations_json,
          estimated_minutes, parent_observation, source_json, raw_json,
          difficulty, purpose_role, answer_verification
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id, QUESTION_ITEM_VERSION, "graph_generated", node_id, "[]",
            kind, question_type, "L2", "", "题干", "text", "答案", "[]", "[]", "[]",
            "[]", "[]", 3, "", "{}", "{}", difficulty, purpose_role, answer_verification,
        ),
    )
    conn.commit()


def seed_compliant_bank(conn: sqlite3.Connection) -> None:
    rows = [
        ("q1", "计算题", "easy", "core", "verified"),
        ("q2", "计算题", "medium", "core", "verified"),
        ("q3", "应用题", "hard", "transfer", "verified"),
        ("q4", "概念题", "easy", "core", "verified"),
        ("q5", "概念题", "medium", "core", "verified"),
        ("q6", "应用题", "hard", "core", "verified"),
    ]
    for question_id, question_type, difficulty, purpose_role, answer_verification in rows:
        insert_question_row(
            conn, question_id,
            question_type=question_type, difficulty=difficulty,
            purpose_role=purpose_role, answer_verification=answer_verification,
        )


class ValidateNodeBankContractTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.addCleanup(self.conn.close)

    def test_compliant_bank_passes(self):
        seed_compliant_bank(self.conn)
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertTrue(report["valid"], report)
        self.assertEqual([], report["errors"])
        self.assertGreaterEqual(report["fingerprint_count"], 2)
        self.assertGreaterEqual(report["transfer_count"], 1)
        self.assertEqual({"easy", "medium", "hard"}, set(report["difficulty_counts"]))
        self.assertTrue(report["checks"]["fingerprints_ok"])
        self.assertTrue(report["checks"]["transfer_ok"])
        self.assertTrue(report["checks"]["difficulty_distribution_ok"])
        self.assertTrue(report["checks"]["no_mismatch"])

    def test_single_question_type_family_fails(self):
        for i in range(4):
            insert_question_row(
                self.conn, f"s{i}", question_type="计算题",
                difficulty=("easy", "medium", "hard", "easy")[i],
                purpose_role=("core", "core", "core", "transfer")[i],
            )
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["fingerprints_ok"])
        self.assertTrue(any("指纹" in error or "fingerprint" in error for error in report["errors"]))

    def test_no_transfer_fails(self):
        insert_question_row(self.conn, "t1", question_type="计算题", difficulty="easy")
        insert_question_row(self.conn, "t2", question_type="应用题", difficulty="medium")
        insert_question_row(self.conn, "t3", question_type="概念题", difficulty="hard")
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["transfer_ok"])
        self.assertTrue(any("transfer" in error for error in report["errors"]))

    def test_missing_difficulty_level_fails(self):
        insert_question_row(self.conn, "d1", question_type="计算题", difficulty="easy", purpose_role="transfer")
        insert_question_row(self.conn, "d2", question_type="应用题", difficulty="medium")
        insert_question_row(self.conn, "d3", question_type="概念题", difficulty="easy")
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["difficulty_distribution_ok"])
        self.assertTrue(any("难度" in error or "difficulty" in error for error in report["errors"]))

    def test_mismatch_row_fails(self):
        seed_compliant_bank(self.conn)
        insert_question_row(self.conn, "bad1", question_type="计算题", difficulty="medium", answer_verification="mismatch")
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["no_mismatch"])
        self.assertTrue(any("mismatch" in error for error in report["errors"]))

    def test_empty_bank_fails(self):
        report = qg.validate_node_bank_contract(self.conn, "N-CALC")
        self.assertFalse(report["valid"])
        self.assertEqual(0, report["question_count"])


if __name__ == "__main__":
    unittest.main()
