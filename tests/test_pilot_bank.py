"""首批试点真实题库测试（objective ④）。

验证 `scripts/pilot_generate_semester_bank.py` 生成的 2 节点真实题库：
1. 真实题目经 `generate_node_bank` 管线入库（sympy 门禁 + 元数据派生）；
2. 每题入库字段完整（difficulty/purpose_role/answer_verification 等）；
3. `validate_node_bank_contract` 两节点 valid（≥2 指纹 / ≥1 transfer /
   难度分布 / 无 mismatch）；
4. 学期链路用真实题跑通：真实题库 → 选 2-3 道计算题 → 孩子作答（模拟
   正确/错误答案）→ 判定层 judge_v51_evaluation → 落 learner_node_status。

不依赖已提交的 sqlite（*.sqlite 按仓库惯例被 gitignore）：测试自行用
pilot.build_bank 重建题库到临时文件，可重跑。

Run: python3 -m unittest tests.test_pilot_bank -v
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from learning_system import db, mastery_bridge as mbr  # noqa: E402
from learning_system import mastery_v51_adapter as v51a  # noqa: E402
from learning_system.answer_verification import is_math_equivalent  # noqa: E402
from learning_system.error_tags import CANONICAL_ERROR_TAGS  # noqa: E402
from scripts import pilot_generate_semester_bank as pilot  # noqa: E402

DAY1 = date(2026, 8, 24)
DAY2 = date(2026, 8, 25)

# 链路测试选用的 3 道真实计算题（均来自题库、sympy 已 verified）
CHAIN_QUESTION_IDS = (
    "Q-M-PRE-DECIMAL-OPS-B1-I0",  # 计算：3.2 + 1.7 = 4.9
    "Q-M-PRE-DECIMAL-OPS-B2-I1",  # 计算：1.2 × 3.5 = 4.2
    "Q-M-PRE-DECIMAL-OPS-B4-I0",  # 计算：7.3 + 2.7 = 10
)


def grade_child_answer(question_row: sqlite3.Row, child_answer: str) -> bool:
    """最小判定 oracle：选择题/简答题精确比对，计算题用 sympy 数学等价。

    真实 app 的答案评估在 answer_contract_batch_v2（含解释/过程证据），
    本 pilot 只验证「真实题库 → 作答对错 → 判定」链路，用机器可检 oracle
    判定对错（计算题），概念/选择/文本按字面比对。
    """
    expected = str(question_row["expected_answer"]).strip()
    child = str(child_answer).strip()
    answer_format = str(question_row["answer_format"] or "")
    if answer_format in {"choice", "text"}:
        return child == expected
    return is_math_equivalent(expected, child)


def wrong_answer_for(question_row: sqlite3.Row) -> str:
    """构造一个与真实标准答案不同的孩子错误答案（对错由 grade 重新判定）。"""
    expected = str(question_row["expected_answer"]).strip()
    answer_format = str(question_row["answer_format"] or "")
    if answer_format == "choice":
        for letter in ("A", "B", "C", "D"):
            if letter != expected:
                return letter
        return "E"
    if answer_format == "text":
        if expected.startswith("-"):
            return expected[1:]  # 经典错因：漏写负号
        return "错误答案"
    for candidate in ("0", "1", "999"):
        if not is_math_equivalent(candidate, expected):
            return candidate
    return "999"


def _copy_real_bank_questions(
    runtime_conn: sqlite3.Connection, bank_path: Path, node_ids=()
) -> int:
    """把题库文件里指定节点的真实题目行原样拷进 runtime DB（链路测试用）。"""
    copied = 0
    with closing(db.connect(bank_path)) as bank_conn:
        columns = [row["name"] for row in bank_conn.execute("pragma table_info(question_items)")]
        for node_id in node_ids:
            rows = bank_conn.execute(
                f"select {', '.join(columns)} from question_items where node_id = ?",
                (node_id,),
            ).fetchall()
            for row in rows:
                placeholders = ", ".join("?" for _ in columns)
                runtime_conn.execute(
                    f"insert or replace into question_items({', '.join(columns)}) "
                    f"values ({placeholders})",
                    tuple(row),
                )
                copied += 1
    return copied


def _evidence_row(attempt_id: str, node_id: str, *, result: str, created_at: str,
                  explanation_fields: bool = False) -> dict:
    row = {
        "id": attempt_id,
        "node_id": node_id,
        "result": result,
        "score_points": 10.0 if result == "correct" else 0.0,
        "max_points": 10.0,
        "created_at": created_at,
        "is_manual": False,
    }
    if explanation_fields:
        # 正确且解释充分 → 满足 R4 strong 前置（exp>=2 + sound + 无推理缺口）
        row.update({
            "explanation_score": 2,
            "reasoning_soundness": "sound",
            "evidence_strength": "strong",
            "next_evidence_need": "",
        })
    return row


class PilotBankBuildTestCase(unittest.TestCase):
    """真实题库生成 + 字段完整性 + 契约校验。"""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.bank_path = Path(cls._tmpdir.name) / "semester_bank_v1.sqlite"
        cls.build = pilot.build_bank(cls.bank_path)
        cls.conn = db.connect(cls.bank_path)
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls._tmpdir.cleanup()

    def _rows(self, node_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "select * from question_items where node_id = ?", (node_id,)
        ).fetchall()

    def test_preflight_verifies_all_30_questions(self):
        summary = pilot.preflight_verify()
        self.assertEqual(30, summary["total"])
        self.assertEqual(30, summary["ok"])
        self.assertEqual([], summary["failures"])

    def test_build_stats(self):
        results = self.build["results"]
        decimal = results["M-PRE-DECIMAL-OPS"]
        pos_neg = results["M-G7-POS-NEG"]
        self.assertEqual(15, decimal["generated"])
        self.assertEqual(15, decimal["verified"])
        self.assertEqual(0, decimal["mismatch_discarded"])
        self.assertEqual(15, decimal["ingested"])
        self.assertEqual(15, pos_neg["generated"])
        self.assertEqual(3, pos_neg["verified"])
        self.assertEqual(0, pos_neg["mismatch_discarded"])
        self.assertEqual(15, pos_neg["ingested"])

    def test_both_nodes_have_15_real_questions(self):
        for node_id in pilot.PILOT_NODE_IDS:
            rows = self._rows(node_id)
            self.assertEqual(15, len(rows), node_id)
            ids = {row["id"] for row in rows}
            self.assertEqual(15, len(ids), node_id)
            for row in rows:
                self.assertTrue(str(row["prompt"]).strip(), row["id"])
                self.assertTrue(str(row["expected_answer"]).strip(), row["id"])
                self.assertNotIn(
                    row["id"],
                    [row["id"] for row in rows if not str(row["prompt"]).strip()],
                )
                # 题目是真实撰写的：非 fake 占位（对比 fake 的「3 + i」模板）
                self.assertNotEqual("计算：3 + 0 的结果", row["prompt"])

    def test_field_completeness(self):
        for node_id in pilot.PILOT_NODE_IDS:
            for row in self._rows(node_id):
                d = dict(row)
                for field in (
                    "id", "node_id", "item_version", "source_type", "kind",
                    "question_type", "variant_level", "difficulty", "purpose_role",
                    "answer_verification", "prompt", "expected_answer",
                    "answer_format", "estimated_minutes",
                ):
                    self.assertTrue(str(d[field]).strip(), f"{d['id']}.{field}")
                self.assertIn(d["difficulty"], {"easy", "medium", "hard"})
                self.assertIn(d["purpose_role"], {"core", "transfer"})
                self.assertIn(d["answer_verification"], {"verified", "unverifiable"})
                self.assertIn(d["answer_format"], {"decimal", "fraction", "expression", "choice", "text"})
                self.assertTrue(json.loads(d["solution_steps_json"]), f"{d['id']}.solution_steps")
                tags = json.loads(d["error_tags_json"])
                self.assertTrue(tags, f"{d['id']}.error_tags")
                self.assertTrue(set(tags) <= CANONICAL_ERROR_TAGS, f"{d['id']}.error_tags")
                rollback = json.loads(d["rollback_candidate_node_ids_json"])
                self.assertTrue(rollback, f"{d['id']}.rollback")
                for node in rollback:
                    self.assertIsNotNone(
                        self.conn.execute("select 1 from graph_nodes where id = ?", (node,)).fetchone(),
                        f"{d['id']} rollback {node} not in graph",
                    )
                self.assertTrue(json.loads(d["rollback_candidate_relations_json"]))
                self.assertTrue(json.loads(d["source_json"]))
                if d["purpose_role"] == "transfer":
                    self.assertTrue(json.loads(d["secondary_node_ids_json"]), f"{d['id']}.secondary")
                else:
                    self.assertEqual([], json.loads(d["secondary_node_ids_json"]))
                self.assertGreaterEqual(d["estimated_minutes"], 1)
                self.assertLessEqual(d["estimated_minutes"], 8)

    def test_verification_ratio(self):
        decimal_rows = self._rows("M-PRE-DECIMAL-OPS")
        self.assertEqual(15, sum(1 for r in decimal_rows if r["answer_verification"] == "verified"))
        pos_neg_rows = self._rows("M-G7-POS-NEG")
        verified = sum(1 for r in pos_neg_rows if r["answer_verification"] == "verified")
        unverifiable = sum(1 for r in pos_neg_rows if r["answer_verification"] == "unverifiable")
        self.assertEqual(3, verified)
        self.assertEqual(12, unverifiable)

    def test_contract_valid_for_both_nodes(self):
        for node_id in pilot.PILOT_NODE_IDS:
            report = self.build["contracts"][node_id]
            self.assertTrue(report["valid"], f"{node_id}: {report['errors']}")
            self.assertEqual([], report["errors"])
            self.assertGreaterEqual(report["fingerprint_count"], 2)
            self.assertGreaterEqual(report["transfer_count"], 1)
            self.assertEqual({"easy", "medium", "hard"}, set(report["difficulty_counts"]))
            self.assertTrue(report["checks"]["fingerprints_ok"])
            self.assertTrue(report["checks"]["transfer_ok"])
            self.assertTrue(report["checks"]["difficulty_distribution_ok"])
            self.assertTrue(report["checks"]["no_mismatch"])

    def test_rerun_is_idempotent(self):
        # 同一路径重跑：题 ID 确定性 + upsert 覆盖 → 仍各 15 题
        pilot.build_bank(self.bank_path)
        for node_id in pilot.PILOT_NODE_IDS:
            self.assertEqual(15, len(self._rows(node_id)), node_id)


class PilotRealQuestionChainTestCase(unittest.TestCase):
    """学期链路用真实题跑通：真实题库 → 作答（正确/错误）→ 判定 → learner_node_status。"""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.bank_path = Path(cls._tmpdir.name) / "bank.sqlite"
        pilot.build_bank(cls.bank_path)
        cls.runtime_path = Path(cls._tmpdir.name) / "runtime.sqlite"
        with closing(db.connect(cls.runtime_path)) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            copied = _copy_real_bank_questions(conn, cls.bank_path, pilot.PILOT_NODE_IDS)
            conn.commit()
        cls.copied = copied

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _persist_judgment(self, conn, *, session_id: str, node_id: str,
                          judgment: dict, evidence_ids: list[str]) -> None:
        status = judgment["status"]
        if status is None or judgment.get("applied") is False:
            return
        payload = {"unified_verdict": {
            "verdict": judgment["verdict"],
            "reason_code": judgment.get("reason_code"),
            "attrs": judgment.get("attrs"),
            "counter": judgment.get("counter"),
            "recheck": judgment.get("recheck"),
            "downgrade": judgment.get("downgrade"),
        }}
        decision = db.record_mastery_decision(
            conn,
            session_id=session_id,
            node_id=node_id,
            decision=judgment.get("decision", "status_update"),
            closure_result="completed",
            evidence_attempt_ids=evidence_ids,
            agent_run_id=None,
            applied=True,
            reason=judgment.get("reason", ""),
            decision_payload=payload,
            commit=False,
        )
        old = conn.execute(
            "select status_revision from learner_node_status where node_id = ?", (node_id,)
        ).fetchone()
        revision = (old[0] + 1) if old else 1
        conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, graph_version,
              question_bank_version, mastery_decision_id,
              source_attempt_ids_json, source_evidence_validation_ids_json,
              updated_by_agent_run_id, status_revision, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, status, 0.0, 0,
                db.json_dump(evidence_ids), judgment.get("reason", ""),
                "", "", decision["id"],
                db.json_dump([]), db.json_dump([]),
                None, revision, judgment.get("_at", DAY1.isoformat()),
            ),
        )

    def _chain_round(self, conn, *, session_id: str, node_id: str, day: date,
                     answers: list[tuple[sqlite3.Row, str]], current_status) -> dict:
        """孩子作答一轮真实题 → 判定。answers: [(question_row, child_answer)]"""
        evidence: list[dict] = []
        evidence_ids: list[str] = []
        for index, (question_row, child_answer) in enumerate(answers):
            correct = grade_child_answer(question_row, child_answer)
            attempt_id = f"{node_id}-PILOT-{day.isoformat()}-{index}"
            evidence_ids.append(attempt_id)
            evidence.append(_evidence_row(
                attempt_id, node_id,
                result="correct" if correct else "wrong",
                created_at=day.isoformat(),
                explanation_fields=correct,
            ))
        current = mbr.normalize_evidence(evidence[-1])
        history = [mbr.normalize_evidence(e) for e in evidence[:-1]]
        judgment = v51a.judge_v51_evaluation(
            current_row=current,
            history_rows=history,
            decision_history=[],
            current_status=current_status,
            deterministic=True,
        )
        judgment["_at"] = current["created_at"]
        self._persist_judgment(conn, session_id=session_id, node_id=node_id,
                               judgment=judgment, evidence_ids=evidence_ids)
        return judgment

    def test_real_questions_copied_into_runtime_db(self):
        self.assertEqual(30, self.copied)
        with closing(db.connect(self.runtime_path)) as conn:
            for question_id in CHAIN_QUESTION_IDS:
                row = conn.execute(
                    "select * from question_items where id = ?", (question_id,)
                ).fetchone()
                self.assertIsNotNone(row, question_id)
                self.assertEqual("verified", row["answer_verification"])

    def test_child_answer_graded_against_real_expected_answer(self):
        with closing(db.connect(self.runtime_path)) as conn:
            for question_id in CHAIN_QUESTION_IDS:
                row = conn.execute(
                    "select * from question_items where id = ?", (question_id,)
                ).fetchone()
                # 用真实标准答案作答 → 判对
                self.assertTrue(
                    grade_child_answer(row, row["expected_answer"]),
                    f"{question_id} 标准答案应判对",
                )
                wrong = wrong_answer_for(row)
                self.assertFalse(
                    grade_child_answer(row, wrong),
                    f"{question_id} 构造的错误答案 {wrong!r} 应判错",
                )

    def test_judgment_chain_real_questions(self):
        node_id = "M-PRE-DECIMAL-OPS"
        with closing(db.connect(self.runtime_path)) as conn:
            session_id = db.create_session(conn, "pilot 真实题链路", mode="test")
            rows = {
                question_id: conn.execute(
                    "select * from question_items where id = ?", (question_id,)
                ).fetchone()
                for question_id in CHAIN_QUESTION_IDS
            }

            # 第 1 天：3 道真实计算题全部答错（模拟错误答案）→ C
            day1_answers = [(rows[qid], wrong_answer_for(rows[qid])) for qid in CHAIN_QUESTION_IDS]
            j1 = self._chain_round(
                conn, session_id=session_id, node_id=node_id, day=DAY1,
                answers=day1_answers, current_status=None,
            )
            self.assertEqual("C", j1["verdict"], j1)
            row = conn.execute(
                "select status_code, status_revision from learner_node_status where node_id = ?",
                (node_id,),
            ).fetchone()
            self.assertEqual("C", row[0])
            self.assertEqual(1, row[1])

            # 第 2 天：同一批真实题全部答对（用标准答案）→ strong → B
            # （deterministic 路径 §5.4 抑制 A → B；AGG 未满也只会到 B）
            day2_answers = [(rows[qid], rows[qid]["expected_answer"]) for qid in CHAIN_QUESTION_IDS]
            j2 = self._chain_round(
                conn, session_id=session_id, node_id=node_id, day=DAY2,
                answers=day2_answers, current_status="C",
            )
            self.assertEqual("B", j2["verdict"], j2)
            row = conn.execute(
                "select status_code, status_revision from learner_node_status where node_id = ?",
                (node_id,),
            ).fetchone()
            self.assertEqual("B", row[0])
            self.assertEqual(2, row[1])

            # 两次判定事件都留痕
            decisions = conn.execute(
                "select count(*) from mastery_decisions where node_id = ?", (node_id,)
            ).fetchone()[0]
            self.assertEqual(2, decisions)

            # 证据 attempt 引用了真实题库题目（prompt 落库可溯源）
            attempt_evidence = conn.execute(
                "select evidence_attempt_ids_json from mastery_decisions where node_id = ? "
                "order by created_at",
                (node_id,),
            ).fetchall()
            self.assertEqual(2, len(attempt_evidence))
            for ev in attempt_evidence:
                ids = json.loads(ev[0])
                self.assertEqual(3, len(ids))
                self.assertTrue(all(str(i).startswith(f"{node_id}-PILOT-") for i in ids))


if __name__ == "__main__":
    unittest.main()
