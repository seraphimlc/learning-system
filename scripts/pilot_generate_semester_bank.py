"""Pilot: 首批试点真实题库（objective ④）。

为两个试点节点（一个计算向 + 一个概念向）撰写**真实数学题**，经
`learning_system.question_generation_service.generate_node_bank` 管线
（sympy 校验门禁 → 元数据派生 → 入库）写入独立题库库文件
`data/question_banks/math/semester_bank_v1.sqlite`。

- 计算向：`M-PRE-DECIMAL-OPS`（小数运算）——15 题全部为可机检计算题
  （answer_format=decimal/fraction/expression），sympy 门禁全 verified。
- 概念向：`M-G7-POS-NEG`（正数和负数）——概念/选择/填空类为主，
  按契约 §4 概念类不可机检 → 入库标记 unverifiable；另配 3 道零的性质
  计算题 verified，证明 sympy 门禁在概念节点同样生效。

题目为**实现者亲自撰写**（非 fake、非 LLM 生成），每题含 prompt /
expected_answer / answer_format / solution_steps，答案均经 sympy 预检
（preflight_verify 在跑管线前逐题验算，验算不过直接报错，绝不静默入库）。

契约：docs/design/specs/2026-08-20-question-bank-contract.md（§3 矩阵、
§4 校验门禁、§5 元数据派生、§6 管线）+ 图谱 v2 每节点 question_generation。

用法：
    python3 scripts/pilot_generate_semester_bank.py [--db PATH] [--preflight-only]

边界：只写题库文件；不碰 app/、不改生产服务、不接外部 LLM API。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, question_generation_service as qg  # noqa: E402
from learning_system.answer_verification import verify_expected_answer  # noqa: E402

BANK_DIR = PROJECT_ROOT / "data" / "question_banks" / "math"
BANK_PATH = BANK_DIR / "semester_bank_v1.sqlite"
GRAPH_PATH = PROJECT_ROOT / "data" / "knowledge_graphs" / "math" / "math_knowledge_graph_v2.json"

PILOT_NODE_IDS = ("M-PRE-DECIMAL-OPS", "M-G7-POS-NEG")

# ---------------------------------------------------------------------------
# 真实题目（实现者亲自撰写，键 = (node_id, batch_index, item_index)）
#
# 约定：
# - prompt：中文题干（计算题以「计算：<完整表达式>」起头，保证
#   extract_calculation 提取的表达式 == 完整算式，杜绝半截误提取）。
# - verification_intent：本实现者声明该题应过的门禁结果（preflight 强校验；
#   generate_fn 返回前剥离，不落库）。
# - solution_steps：简短解题过程（写入 solution_steps_json）。
# ---------------------------------------------------------------------------

_QUESTIONS: dict[tuple[str, int, int], dict[str, Any]] = {
    # ================= M-PRE-DECIMAL-OPS 小数运算（计算向，15 题全 verified）
    ("M-PRE-DECIMAL-OPS", 1, 0): {
        "prompt": "计算：3.2 + 1.7，写出答案。",
        "expected_answer": "4.9",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["对齐小数点：3.2 与 1.7 的十分位对齐", "3.2 + 1.7 = 4.9"],
    },
    ("M-PRE-DECIMAL-OPS", 1, 1): {
        "prompt": "计算：0.6 × 10",
        "expected_answer": "6",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["小数乘 10：小数点向右移动一位", "0.6 × 10 = 6"],
    },
    ("M-PRE-DECIMAL-OPS", 1, 2): {
        "prompt": "计算：0.5 化成分数是多少？",
        "expected_answer": "1/2",
        "answer_format": "fraction",
        "verification_intent": "verified",
        "solution_steps": ["0.5 表示十分之五", "5/10 约分得 1/2"],
    },
    ("M-PRE-DECIMAL-OPS", 2, 0): {
        "prompt": "计算：5.6 − 2.3",
        "expected_answer": "3.3",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["对齐小数点", "5.6 − 2.3 = 3.3"],
    },
    ("M-PRE-DECIMAL-OPS", 2, 1): {
        "prompt": "计算：1.2 × 3.5",
        "expected_answer": "4.2",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["先按整数算：12 × 35 = 420", "两个因数各有一位小数，积有两位小数：4.20 = 4.2"],
    },
    ("M-PRE-DECIMAL-OPS", 2, 2): {
        "prompt": "计算：2/5 + 0.3",
        "expected_answer": "0.7",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["把 2/5 化成小数 0.4", "0.4 + 0.3 = 0.7"],
    },
    ("M-PRE-DECIMAL-OPS", 3, 0): {
        "prompt": "买文具花了 12.5 元，买书花了 18.75 元，一共花了多少元？列式计算：12.5 + 18.75",
        "expected_answer": "31.25",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["理解情境：求一共用加法", "12.5 + 18.75 = 31.25（元）"],
    },
    ("M-PRE-DECIMAL-OPS", 3, 1): {
        "prompt": "计算：3 × 0.4 ÷ 0.2",
        "expected_answer": "6",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["从左到右：3 × 0.4 = 1.2", "1.2 ÷ 0.2 = 6"],
    },
    ("M-PRE-DECIMAL-OPS", 3, 2): {
        "prompt": "计算：3/4 × 0.8",
        "expected_answer": "0.6",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["把 3/4 化成小数 0.75", "0.75 × 0.8 = 0.6"],
    },
    ("M-PRE-DECIMAL-OPS", 4, 0): {
        "prompt": "计算：7.3 + 2.7",
        "expected_answer": "10",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["对齐小数点", "7.3 + 2.7 = 10.0 = 10"],
    },
    ("M-PRE-DECIMAL-OPS", 4, 1): {
        "prompt": "计算：0.25 × 0.4",
        "expected_answer": "0.1",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["按整数算：25 × 4 = 100", "两个因数共有 3 位小数：0.100 = 0.1"],
    },
    ("M-PRE-DECIMAL-OPS", 4, 2): {
        "prompt": "计算：0.75 − 1/4",
        "expected_answer": "1/2",
        "answer_format": "fraction",
        "verification_intent": "verified",
        "solution_steps": ["把 1/4 化成小数 0.25", "0.75 − 0.25 = 0.5 = 1/2"],
    },
    ("M-PRE-DECIMAL-OPS", 5, 0): {
        "prompt": "计算：10 − 3.75 − 4.25",
        "expected_answer": "2",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["凑整：3.75 + 4.25 = 8", "10 − 8 = 2"],
    },
    ("M-PRE-DECIMAL-OPS", 5, 1): {
        "prompt": "计算：0.2 × 0.3",
        "expected_answer": "0.06",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["按整数算：2 × 3 = 6", "两个因数共有 2 位小数：0.06（易错点：0.6 是错的）"],
    },
    ("M-PRE-DECIMAL-OPS", 5, 2): {
        "prompt": "计算：3/20 化成小数",
        "expected_answer": "0.15",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "solution_steps": ["3 ÷ 20 = 0.15", "注意 3/20 = 0.15（不是 1.5，易错点）"],
    },
    # ================= M-G7-POS-NEG 正数和负数（概念向，3 题 verified + 12 题 unverifiable）
    ("M-G7-POS-NEG", 1, 0): {
        "prompt": "生活中的温度：某地气温零上 3℃ 记作 +3℃，零下 5℃ 应记作什么？",
        "expected_answer": "-5℃",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["零上与零下是相反意义的量", "零上用 + 表示，零下就用 − 表示", "零下 5℃ 记作 −5℃"],
    },
    ("M-G7-POS-NEG", 1, 1): {
        "prompt": "下列各组量中，具有相反意义的一组是（　）\nA. 向东走 3 米和向南走 3 米\nB. 收入 200 元和支出 200 元\nC. 上升 2 米和上升 1 米\nD. 向东走 3 米和向东走 5 米",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["相反意义的量：意义相反（收入↔支出），与数值大小无关", "A 东与南不是相反方向；C、D 是同一方向", "选 B"],
    },
    ("M-G7-POS-NEG", 1, 2): {
        "prompt": "计算：5 − 5",
        "expected_answer": "0",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["5 − 5 = 0", "0 既不是正数也不是负数，是正数和负数的分界"],
    },
    ("M-G7-POS-NEG", 2, 0): {
        "prompt": "电梯从地面（0 层）上升 6 层，记作 +6 层；那么从地面下降 4 层，应记作（　）层。\nA. +4\nB. −4\nC. 4\nD. 0",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["上升记为正，下降是相反意义的量", "下降 4 层记作 −4 层", "选 B"],
    },
    ("M-G7-POS-NEG", 2, 1): {
        "prompt": "把收入记为正：收入 500 元记作 +500 元。那么支出 350 元应记作什么？",
        "expected_answer": "-350元",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["支出与收入是相反意义的量", "收入记 +，支出记 −", "支出 350 元记作 −350 元"],
    },
    ("M-G7-POS-NEG", 2, 2): {
        "prompt": "下列说法正确的是（　）\nA. 0 是最小的正数\nB. 0 是最小的负数\nC. 0 既不是正数也不是负数\nD. 0 是正数",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["0 既不是正数也不是负数", "0 是正数与负数的分界，也不是最小的数", "选 C"],
    },
    ("M-G7-POS-NEG", 3, 0): {
        "prompt": "下列说法错误的是（　）\nA. 上升 5 米与下降 5 米是相反意义的量\nB. 向东 3 米与向西 3 米是相反意义的量\nC. 收入 8 元与支出 8 元是相反意义的量\nD. 向北 3 米与向南 5 米不是相反意义的量",
        "expected_answer": "D",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["向北与向南方向相反，是相反意义的量，与数值大小无关", "A、B、C 说法都正确", "说法错误的是 D"],
    },
    ("M-G7-POS-NEG", 3, 1): {
        "prompt": "温度计上 0℃ 为分界：0℃ 以上 12℃ 记作 +12℃，0℃ 以下 15℃ 记作多少摄氏度？",
        "expected_answer": "-15℃",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["0℃ 是分界点", "0℃ 以下为负", "0℃ 以下 15℃ 记作 −15℃"],
    },
    ("M-G7-POS-NEG", 3, 2): {
        "prompt": "在数轴上，0 的位置把数分成左右两部分。下列说法正确的是（　）\nA. 0 左边的数都是正数\nB. 0 右边的数都是正数\nC. 0 既在正数一边也在负数一边\nD. 0 不是数",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["数轴上 0 右边是正数，左边是负数", "0 是分界点，本身既不是正数也不是负数", "选 B"],
    },
    ("M-G7-POS-NEG", 4, 0): {
        "prompt": "零上 25℃ 记作 +25℃，零下 10℃ 记作什么？",
        "expected_answer": "-10℃",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["零上与零下相反", "零下为负", "零下 10℃ 记作 −10℃"],
    },
    ("M-G7-POS-NEG", 4, 1): {
        "prompt": "某粮库运进粮食记为正：运进 30 吨记作 +30 吨，运出 45 吨记作什么？",
        "expected_answer": "-45吨",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["运出与运进是相反意义的量", "运进记 +，运出记 −", "运出 45 吨记作 −45 吨"],
    },
    ("M-G7-POS-NEG", 4, 2): {
        "prompt": "计算：8 × 0",
        "expected_answer": "0",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["任何数乘 0 都得 0", "0 既不是正数也不是负数"],
    },
    ("M-G7-POS-NEG", 5, 0): {
        "prompt": "电梯从 8 楼下到 1 楼。如果从 1 楼上到 8 楼记作 +7 层，那么从 8 楼下到 1 楼记作多少层？",
        "expected_answer": "-7层",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "solution_steps": ["上与下是相反意义的量", "8 楼到 1 楼相差 7 层", "下 7 层记作 −7 层"],
    },
    ("M-G7-POS-NEG", 5, 1): {
        "prompt": "下面各数中，是负数的是（　）\nA. +3\nB. 0\nC. −2.5\nD. 1/2",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "solution_steps": ["带 − 号的数是负数", "0 不是负数，+3 是正数，1/2 是正数", "选 C"],
    },
    ("M-G7-POS-NEG", 5, 2): {
        "prompt": "计算：0 ÷ 5",
        "expected_answer": "0",
        "answer_format": "expression",
        "verification_intent": "verified",
        "solution_steps": ["0 除以任何非零数都得 0", "0 既不是正数也不是负数，是正负数的分界"],
    },
}


def pilot_generate_fn(batch_spec: dict) -> list[dict[str, Any]]:
    """按批规格返回本批 3 道真实题目（题序 = item_index 序）。"""
    node_id = str(batch_spec["node_id"])
    batch_index = int(batch_spec["batch_index"])
    out: list[dict[str, Any]] = []
    for item_spec in batch_spec["items"]:
        item_index = int(item_spec["item_index"])
        key = (node_id, batch_index, item_index)
        if key not in _QUESTIONS:
            raise KeyError(
                f"pilot 题目缺失: {key}（每个矩阵槽位都必须有实现者撰写的真实题目）"
            )
        raw = dict(_QUESTIONS[key])
        raw["item_index"] = item_index
        # 内部声明字段不落库
        raw.pop("verification_intent", None)
        out.append(raw)
    return out


def preflight_verify() -> dict[str, Any]:
    """跑管线前逐题验算：声明 verified 的必须 verified；声明 unverifiable
    的必须 unverifiable（防止题干措辞意外触发半截提取 → mismatch 静默丢弃）。

    这是实现者的硬校验：任何一道题不过 preflight 直接抛错，绝不带着
    未验算的答案进库。
    """
    summary: dict[str, Any] = {"total": len(_QUESTIONS), "ok": 0, "failures": []}
    for (node_id, batch_index, item_index), raw in sorted(_QUESTIONS.items()):
        verdict = verify_expected_answer(str(raw["prompt"]), str(raw["expected_answer"]))["verdict"]
        expected = str(raw["verification_intent"])
        if verdict != expected:
            summary["failures"].append(
                {
                    "key": [node_id, batch_index, item_index],
                    "intent": expected,
                    "actual": verdict,
                    "prompt": raw["prompt"],
                    "expected_answer": raw["expected_answer"],
                }
            )
        else:
            summary["ok"] += 1
    if summary["failures"]:
        raise AssertionError(
            f"pilot preflight 校验失败 {len(summary['failures'])} 题（意图 {expected} vs 实际 {verdict}）："
            + json.dumps(summary["failures"], ensure_ascii=False, indent=2)
        )
    return summary


def load_graph() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def build_bank(
    db_path: Path | str = BANK_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
    commit: bool = True,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """init_schema + seed 图谱 + 逐节点跑 generate_node_bank（真实题目）→ 契约校验。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    preflight_verify()
    graph = graph if graph is not None else load_graph()

    conn: sqlite3.Connection = db.connect(db_path)
    try:
        db.init_schema(conn)
        db.seed_from_assets(conn, project_root)
        results: dict[str, Any] = {}
        contracts: dict[str, Any] = {}
        for node_id in PILOT_NODE_IDS:
            results[node_id] = qg.generate_node_bank(
                conn,
                node_id,
                generate_fn=pilot_generate_fn,
                graph=graph,
                commit=False,
            )
            contracts[node_id] = qg.validate_node_bank_contract(conn, node_id)
        if commit:
            conn.commit()
        return {
            "db_path": str(db_path.resolve()),
            "results": results,
            "contracts": contracts,
        }
    finally:
        conn.close()


def _print_report(build: dict[str, Any]) -> None:
    print(f"题库文件: {build['db_path']}")
    for node_id, stats in build["results"].items():
        contract = build["contracts"][node_id]
        print(
            f"\n[{node_id}] generated={stats['generated']} verified={stats['verified']} "
            f"unverifiable={stats['unverifiable']} mismatch_discarded={stats['mismatch_discarded']} "
            f"ingested={stats['ingested']}"
        )
        print(
            f"  契约 valid={contract['valid']} 题数={contract['question_count']} "
            f"指纹={contract['fingerprint_count']} transfer={contract['transfer_count']} "
            f"难度={contract['difficulty_counts']} 校验状态={contract['answer_verification_counts']}"
        )
        for error in contract["errors"]:
            print(f"  ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 2 节点试点真实题库（semester_bank_v1）")
    parser.add_argument("--db", default=str(BANK_PATH), help="目标 sqlite 路径")
    parser.add_argument("--preflight-only", action="store_true", help="只做 sympy 预检，不入库")
    args = parser.parse_args(argv)

    if args.preflight_only:
        summary = preflight_verify()
        print(f"preflight 通过: {summary['ok']}/{summary['total']} 题与声明门禁意图一致")
        return 0

    build = build_bank(args.db)
    _print_report(build)
    if any(not contract["valid"] for contract in build["contracts"].values()):
        print("\n契约校验未全通过！", file=sys.stderr)
        return 1
    print("\n两节点契约校验全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
