"""Pilot: 首批试点真实题库（objective ④）+ 琢玉审查修订（objective ③）。

为两个试点节点（一个计算向 + 一个概念向）撰写**真实数学题**，经
`learning_system.question_generation_service.generate_node_bank` 管线
（sympy 校验门禁 → 元数据派生 → 入库）写入独立题库库文件
`data/question_banks/math/semester_bank_v1.sqlite`。

- 计算向：`M-PRE-DECIMAL-OPS`（小数运算）——13 题可机检计算题
  （answer_format=decimal/fraction/expression，sympy 门禁 verified）
  + 2 题概念/应用类（L1 识别题、情境列式应用题，契约 §4 允许 unverifiable）。
- 概念向：`M-G7-POS-NEG`（正数和负数）——15 题全部为概念/选择/判断类，
  按契约 §4 概念类不可机检 → 全部入库标记 unverifiable（概念节点本就以
  unverifiable 为主，不为实现门禁演示而牺牲题效）。

**琢玉审查修订（objective ③，依据 `docs/qa/pilot_bank_pedagogy_review.md`）**：
- P0：替换 POS-NEG 3 道"零的意义"算术题（5−5 / 8×0 / 0÷5）为真正的概念
  判断题（0℃ 分界 / 0 不是最小数 / 海拔 0 米基准，全部经概念判断而非算术）；
  消除 2 道答案形式歧义（DECIMAL B2-I2 注明"用小数表示"、B4-I2 注明"用分数
  表示"）；补小数除法覆盖（B2-I0 = 7.2÷0.8 标准除数小数题，solution_steps
  含"为什么移动小数点"解释）。
- P1：6 道 hard 虚高题诚实降 medium（DECIMAL B3-I1/B3-I2/B5-I0 +
  POS-NEG B3-I1/B3-I2/B4-I1）；POS-NEG B3-I1 换为真迁移（负数识别×有理数
  分类）；压缩"记作"模板重复（温度×3→×1、收支×2→×1）。
- P2：DECIMAL L1 识别档补真识别题（B1-I1 = "哪道题要对齐小数点"）；
  question_type 标签与内容一致（每题显式声明）；error_tags 贴切（温度/收支
  去 visual_spatial，电梯/数轴保留）；B3-I0 删去已给表达式以测列式并内置
  估算步（补"结果不估算"错因覆盖）。
- 每题补写 `design_rationale` 五要素（考点/难度理由/认知阶梯定位/错因陷阱/
  教学角色），直接采用审查报告 §2 或按修订微调。

**三闸门重跑**：
1. sympy 门禁：preflight_verify 逐题强校验（声明 verified 必须 verified、
   声明 unverifiable 必须 unverifiable），管线内 `verify_expected_answer`
   逐题复核；
2. 契约校验：`validate_node_bank_contract` 两节点 valid（指纹 ≥2 / transfer
   ≥1 / 难度分布 / 无 mismatch / design_rationale 全含考点）+ trivial 抽检
   为零；
3. 质量属性门禁：`check_pilot_quality` 按审查报告 P0/P1/P2 对整库断言
   （零槽位无算术题、除数小数覆盖、答案形式明确、难度诚实、error_tags
   贴切、question_type 一致）。

reviewer_fn 选择说明：审查报告是**整库/跨批**约束（如"POS-NEG 零槽位不得为
算术题""DECIMAL 必须含除数小数覆盖"），逐批 reviewer_fn 看不到整库；且
pilot 生成器确定性强，逐批规则审查门禁形同虚设。因此本次试点**不带
reviewer_fn 跑管线**，琢玉报告的修订决定直接内嵌到题目，由
`check_pilot_quality` 作为"基于审查报告意见的规则审查"在整库层面执行第三闸门；
真实琢玉逐题 LLM 重审属后续全量流程（objective ②），不在本次试点范围。

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
import re
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

# 琢玉审查报告 P0 替换的 3 个"零的意义"槽位（断言其不再是算术题）
ZERO_SLOT_QUESTION_IDS = (
    "Q-M-G7-POS-NEG-B1-I2",
    "Q-M-G7-POS-NEG-B4-I2",
    "Q-M-G7-POS-NEG-B5-I2",
)

# 琢玉审查报告 P1 降档的 6 道 hard 虚高题
DOWNGRADED_QUESTION_IDS = (
    "Q-M-PRE-DECIMAL-OPS-B3-I1",
    "Q-M-PRE-DECIMAL-OPS-B3-I2",
    "Q-M-PRE-DECIMAL-OPS-B5-I0",
    "Q-M-G7-POS-NEG-B3-I1",
    "Q-M-G7-POS-NEG-B3-I2",
    "Q-M-G7-POS-NEG-B4-I1",
)

# 本节点各保留 1 道真 hard 标杆（判定层 hard 证据来源）
HARD_BENCHMARK_IDS = {
    "M-PRE-DECIMAL-OPS": {"Q-M-PRE-DECIMAL-OPS-B4-I1"},  # 0.25×0.4（审查：hard 名副其实）
    "M-G7-POS-NEG": {"Q-M-G7-POS-NEG-B5-I0"},            # 电梯 8→1 楼（审查：本节点最佳 hard）
}

# ---------------------------------------------------------------------------
# 真实题目（实现者亲自撰写，键 = (node_id, batch_index, item_index)）
#
# 约定：
# - prompt：中文题干（计算题以「计算：<完整表达式>」起头，保证
#   extract_calculation 提取的表达式 == 完整算式，杜绝半截误提取；
#   答案形式注解（如「，用小数表示答案。」）放在表达式**之后**，不破坏提取）。
# - verification_intent：本实现者声明该题应过的门禁结果（preflight 强校验；
#   generate_fn 返回前剥离，不落库）。
# - question_type / difficulty：显式声明（覆盖矩阵槽位轮转与难度，保证
#   标签-内容一致、难度诚实——审查报告 P1#4 / P2#8）。
# - target_error_tags：显式声明错因标签（审查报告 P2#9：温度/收支去
#   visual_spatial，电梯/方向/数轴保留）。
# - design_rationale：五要素（审查报告 §2 采用/微调）。
# - solution_steps：简短解题过程（写入 solution_steps_json）。
# ---------------------------------------------------------------------------

_QUESTIONS: dict[tuple[str, int, int], dict[str, Any]] = {
    # ================= M-PRE-DECIMAL-OPS 小数运算（计算向，13 verified + 2 unverifiable）
    ("M-PRE-DECIMAL-OPS", 1, 0): {
        "prompt": "计算：3.2 + 1.7，写出答案。",
        "expected_answer": "4.9",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数加减",
        "solution_steps": ["对齐小数点：3.2 与 1.7 的十分位对齐", "3.2 + 1.7 = 4.9"],
        "design_rationale": {
            "考点": "一位小数加法与小数点对齐",
            "难度理由": "锚点题取最简，medium 是教学锚点难度而非认知难度",
            "认知阶梯定位": "标准例题（L2 套用基准线）",
            "错因陷阱": "无（锚点题不埋陷阱）",
            "教学角色": "讲本质用——'先按整数算（32+17），再点小数点'的演示载体",
        },
    },
    ("M-PRE-DECIMAL-OPS", 1, 1): {
        "prompt": "下面哪道题要先对齐小数点再计算？（　）\nA. 2.4 × 3\nB. 1.5 + 2.63\nC. 0.5 ÷ 0.1\nD. 7 × 0.5",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "小数加减",
        "target_error_tags": ["concept_confusion", "calculation_or_symbol"],
        "solution_steps": [
            "小数加减法要对齐小数点（十分位对齐十分位）",
            "A、D 是乘法（末位对齐），C 是除法（转化），都不需要对齐小数点",
            "选 B",
        ],
        "design_rationale": {
            "考点": "判断'小数点对齐'规则的适用对象（小数加减法）",
            "难度理由": "easy——规则识别，无计算",
            "认知阶梯定位": "L1 识别正宗实现：判断考点/规则而非直接计算（P2#7 补识别档）",
            "错因陷阱": "把乘法'末位对齐'误当成'小数点对齐'（concept_confusion / calculation_or_symbol）",
            "教学角色": "L1 识别脚手架，填补原 0.6×10 直接计算冒充识别的空转",
        },
    },
    ("M-PRE-DECIMAL-OPS", 1, 2): {
        "prompt": "计算：0.5 化成分数是多少？",
        "expected_answer": "1/2",
        "answer_format": "fraction",
        "verification_intent": "verified",
        "question_type": "小数与分数互化",
        "solution_steps": ["0.5 表示十分之五", "5/10 约分得 1/2"],
        "design_rationale": {
            "考点": "一位小数化分数（十分之五）",
            "难度理由": "easy（互化锚点）",
            "认知阶梯定位": "L1 识别锚点",
            "错因陷阱": "无（锚点）",
            "教学角色": "互化方向的基准示范",
        },
    },
    ("M-PRE-DECIMAL-OPS", 2, 0): {
        "prompt": "计算：7.2 ÷ 0.8",
        "expected_answer": "9",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数乘除",
        "difficulty": "medium",
        "solution_steps": [
            "除数是小数：把被除数和除数同时扩大 10 倍，商不变",
            "7.2 ÷ 0.8 = 72 ÷ 8",
            "72 ÷ 8 = 9",
            "为什么能这样：被除数和除数同时乘相同的数（10），商不变——这就是小数除法移动小数点的道理",
        ],
        "design_rationale": {
            "考点": "除数是小数的小数除法（转化法：同时扩倍）",
            "难度理由": "medium——转化一步是节点#2 错因'除数是小数不会转化'的核心，比纯套用多一步推理",
            "认知阶梯定位": "L2 套用（标准小数除法，P0#3 补覆盖）",
            "错因陷阱": "不会转化直接除（把 7.2÷0.8 当 7.2÷8）",
            "教学角色": "除数小数转化的标准变式，掌握标准'能解释小数除法为何移动小数点'的取证题",
        },
    },
    ("M-PRE-DECIMAL-OPS", 2, 1): {
        "prompt": "计算：1.2 × 3.5",
        "expected_answer": "4.2",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数乘除",
        "solution_steps": ["先按整数算：12 × 35 = 420", "两个因数各有一位小数，积有两位小数：4.20 = 4.2"],
        "design_rationale": {
            "考点": "两位×一位→两位小数乘法",
            "难度理由": "medium（整数乘 12×35 + 积位数两步）",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "积小数位数（420→4.20→4.2）",
            "教学角色": "乘法标准变式",
        },
    },
    ("M-PRE-DECIMAL-OPS", 2, 2): {
        "prompt": "计算：2/5 + 0.3，用小数表示答案。",
        "expected_answer": "0.7",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数与分数互化",
        "solution_steps": ["把 2/5 化成小数 0.4", "0.4 + 0.3 = 0.7"],
        "design_rationale": {
            "考点": "分数化小数后加法（互化+加减混合）",
            "难度理由": "medium（需先统一形式）",
            "认知阶梯定位": "L3 变式（换形式混合）",
            "错因陷阱": "2/5 误读为 2.5、互化后忘对齐",
            "教学角色": "互化-加减桥接题；题干注明'用小数表示'消除答案形式歧义（P0#2）",
        },
    },
    ("M-PRE-DECIMAL-OPS", 3, 0): {
        "prompt": "买文具花了 12.5 元，买书花了 18.75 元，一共花了多少元？",
        "expected_answer": "31.25",
        "answer_format": "decimal",
        "verification_intent": "unverifiable",
        "question_type": "小数加减",
        "target_error_tags": ["calculation_or_symbol", "modeling_or_reading"],
        "solution_steps": [
            "理解情境：求一共用加法，先自己列式 12.5 + 18.75",
            "估算核对：12.5 + 18.75 ≈ 12 + 19 = 31，答案应在 31 左右",
            "对齐小数点：12.5 + 18.75 = 31.25（元）",
        ],
        "design_rationale": {
            "考点": "不同位数小数加法的列式建模 + 对齐",
            "难度理由": "medium（进位+对齐，且需自己列式）",
            "认知阶梯定位": "L3 换语境（情境应用题；删去已给表达式以测列式，P2#10）",
            "错因陷阱": "小数点对齐（12.5 与 18.75 位数不同）+ 不估算直接算",
            "教学角色": "情境应用示范；solution_steps 内置估算步补'结果不估算'错因覆盖（P2#11）",
        },
    },
    ("M-PRE-DECIMAL-OPS", 3, 1): {
        "prompt": "计算：3 × 0.4 ÷ 0.2",
        "expected_answer": "6",
        "answer_format": "expression",
        "verification_intent": "verified",
        "question_type": "小数乘除",
        "difficulty": "medium",
        "solution_steps": [
            "从左到右：3 × 0.4 = 1.2",
            "1.2 ÷ 0.2：被除数、除数同时扩大 10 倍 → 12 ÷ 2",
            "12 ÷ 2 = 6",
        ],
        "design_rationale": {
            "考点": "同级混合运算顺序 + 除数小数转化",
            "难度理由": "降 medium：三步左到右、规则明确，够不上 hard（P1#4 诚实标定）",
            "认知阶梯定位": "L4 迁移（混合运算顺序属 M-PRE-ORDER-OPS 前置，迁移成立）",
            "错因陷阱": "÷0.2 不转化直接除（除数小数转化）",
            "教学角色": "除数小数转化覆盖点（与 B2-I0 互补：这里转化内嵌在混合运算里）",
        },
    },
    ("M-PRE-DECIMAL-OPS", 3, 2): {
        "prompt": "计算：3/4 × 0.8",
        "expected_answer": "0.6",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数与分数互化",
        "difficulty": "medium",
        "solution_steps": ["把 3/4 化成小数 0.75", "0.75 × 0.8 = 0.6"],
        "design_rationale": {
            "考点": "分数化小数后乘法",
            "难度理由": "降 medium：0.75×0.8 积位数计数是真难点，但够不上 hard（P1#4）",
            "认知阶梯定位": "L4 迁移（互化+乘双知识）",
            "错因陷阱": "积位数（0.600→0.6）",
            "教学角色": "互化-乘法迁移题",
        },
    },
    ("M-PRE-DECIMAL-OPS", 4, 0): {
        "prompt": "计算：5.3 − 1.8",
        "expected_answer": "3.5",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数加减",
        "solution_steps": [
            "对齐小数点",
            "十分位 3 − 8 不够减，向个位借 1：13 − 8 = 5",
            "个位 4 − 1 = 3，结果 3.5",
        ],
        "design_rationale": {
            "考点": "一位小数减法（含借位）",
            "难度理由": "easy 检测——借位是唯一陷阱，定位检测易档",
            "认知阶梯定位": "L2 检测",
            "错因陷阱": "借位错 / 小数点对齐错（P2#10：换有借位的 5.3−1.8，让'小数点对齐错'有处可错）",
            "教学角色": "掌握档快速检测（替换原 7.3+2.7 无陷阱琐碎题）",
        },
    },
    ("M-PRE-DECIMAL-OPS", 4, 1): {
        "prompt": "计算：0.25 × 0.4",
        "expected_answer": "0.1",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数乘除",
        "solution_steps": [
            "按整数算：25 × 4 = 100",
            "两个因数共有 3 位小数：0.100 = 0.1",
            "估算核对：0.25 × 0.4 ≈ 0.1（四分之一乘 0.4）",
        ],
        "design_rationale": {
            "考点": "积小数位数 + 去尾零",
            "难度理由": "hard 名副其实（25×4=100→0.100→0.1，三处可错）",
            "认知阶梯定位": "L3 检测 hard",
            "错因陷阱": "位数错（1 或 0.01）、去尾零遗忘",
            "教学角色": "本节点 hard 标杆，判定层 hard 证据的可靠来源",
        },
    },
    ("M-PRE-DECIMAL-OPS", 4, 2): {
        "prompt": "计算：0.75 − 1/4，用分数表示答案。",
        "expected_answer": "1/2",
        "answer_format": "fraction",
        "verification_intent": "verified",
        "question_type": "小数与分数互化",
        "solution_steps": ["把 1/4 化成小数 0.25（或把 0.75 化成分数 3/4）", "0.75 − 0.25 = 0.5", "0.5 用分数表示 = 1/2"],
        "design_rationale": {
            "考点": "小数减分数需统一形式",
            "难度理由": "medium 复测",
            "认知阶梯定位": "L3 复测",
            "错因陷阱": "1/4 化 0.25 后相减（0.5）",
            "教学角色": "防'会背不会用'复测；题干注明'用分数表示'消除答案形式歧义（P0#2）",
        },
    },
    ("M-PRE-DECIMAL-OPS", 5, 0): {
        "prompt": "用简便方法计算：10 − 3.75 − 4.25",
        "expected_answer": "2",
        "answer_format": "expression",
        "verification_intent": "verified",
        "question_type": "小数加减",
        "difficulty": "medium",
        "solution_steps": ["简便策略：先算 3.75 + 4.25 = 8（凑整）", "10 − 8 = 2"],
        "design_rationale": {
            "考点": "凑整策略（3.75 + 4.25 = 8）",
            "难度理由": "降 medium：顺序算也能得分、无错误陷阱，但'用简便方法计算'强制用策略（P1#4 + P2 表述）",
            "认知阶梯定位": "L4 复测策略题",
            "错因陷阱": "策略盲区（看不出凑整），非计算错误",
            "教学角色": "策略性复测",
        },
    },
    ("M-PRE-DECIMAL-OPS", 5, 1): {
        "prompt": "计算：0.2 × 0.3",
        "expected_answer": "0.06",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数乘除",
        "solution_steps": ["按整数算：2 × 3 = 6", "两个因数共有 2 位小数：0.06（易错点：0.6 是错的）"],
        "design_rationale": {
            "考点": "积小数位数",
            "难度理由": "easy 但陷阱密度高（0.6 vs 0.06），easy 档配陷阱题诊断力强",
            "认知阶梯定位": "L1 诊断（识别位值错因）",
            "错因陷阱": "0.6 是错的（位数数错），对应节点'结果不估算/计算符号'类错因",
            "教学角色": "最佳诊断题，直接区分'会算不会点小数点'",
        },
    },
    ("M-PRE-DECIMAL-OPS", 5, 2): {
        "prompt": "计算：3/20 化成小数",
        "expected_answer": "0.15",
        "answer_format": "decimal",
        "verification_intent": "verified",
        "question_type": "小数与分数互化",
        "solution_steps": ["3 ÷ 20 = 0.15", "注意 3/20 = 0.15（不是 1.5，易错点）"],
        "design_rationale": {
            "考点": "分数化小数（除数 20 需补位）",
            "难度理由": "medium（3÷20 心算需补位）",
            "认知阶梯定位": "L2 诊断",
            "错因陷阱": "1.5（丢零）",
            "教学角色": "互化方向诊断（分数→小数），与 B1-I2 方向互补",
        },
    },
    # ================= M-G7-POS-NEG 正数和负数（概念向，15 题全 unverifiable）
    ("M-G7-POS-NEG", 1, 0): {
        "prompt": "生活中的温度：某地气温零上 3℃ 记作 +3℃，零下 5℃ 应记作什么？",
        "expected_answer": "-5℃",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "target_error_tags": ["concept_confusion", "modeling_or_reading"],
        "solution_steps": ["零上与零下是相反意义的量", "零上用 + 表示，零下就用 − 表示", "零下 5℃ 记作 −5℃"],
        "design_rationale": {
            "考点": "用正负数表示相反意义的量（温度基准）",
            "难度理由": "medium 锚点",
            "认知阶梯定位": "标准例题（L2 套用基准）",
            "错因陷阱": "无（锚点题不埋陷阱）",
            "教学角色": "讲解'零上/零下'分界的标准情境（温度记作仅保留此题，压缩模板重复 P1#6）",
        },
    },
    ("M-G7-POS-NEG", 1, 1): {
        "prompt": "下列各组量中，具有相反意义的一组是（　）\nA. 向东走 3 米和向南走 3 米\nB. 收入 200 元和支出 200 元\nC. 上升 2 米和上升 1 米\nD. 向东走 3 米和向东走 5 米",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "相反意义量",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": ["相反意义的量：意义相反（收入↔支出），与数值大小无关", "A 东与南不是相反方向；C、D 是同一方向", "选 B"],
        "design_rationale": {
            "考点": "识别'相反意义'（方向相反/收支相反，与数值无关）",
            "难度理由": "easy",
            "认知阶梯定位": "L1 识别正宗实现",
            "错因陷阱": "东/南（方向不同但非相反）、同向不同值（C/D），对应'语境方向看反'",
            "教学角色": "概念识别脚手架，本节点最佳 L1",
        },
    },
    ("M-G7-POS-NEG", 1, 2): {
        "prompt": "0℃ 表示没有温度吗？（　）\nA. 表示，0℃ 就是没有温度\nB. 表示，0℃ 的温度是 0\nC. 不表示，0℃ 是零上与零下的分界点\nD. 不表示，0℃ 是最低的温度",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "零的意义",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": [
            "0℃ 不是'没有温度'，而是零上与零下的分界点（参照点）",
            "0 是温度的分界，0 本身不是'没有'",
            "0℃ 也不是最低温度（还有零下温度），选 C",
        ],
        "design_rationale": {
            "考点": "零的意义：0 作为分界/参照点而非'没有'",
            "难度理由": "easy（L1 概念判断）",
            "认知阶梯定位": "L1 识别（P0#1：替换琐碎算术题 5−5，必须经概念判断而非算术）",
            "错因陷阱": "把 0 当'没有'（0℃=没有温度）、把 0℃ 当最低温度",
            "教学角色": "零的意义概念题（与 B2-I2 的'0 不是正负数'互补：此处测 0 的参照意义）",
        },
    },
    ("M-G7-POS-NEG", 2, 0): {
        "prompt": "电梯从地面（0 层）上升 6 层，记作 +6 层；那么从地面下降 4 层，应记作（　）层。\nA. +4\nB. −4\nC. 4\nD. 0",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "target_error_tags": ["concept_confusion", "visual_spatial"],
        "solution_steps": ["上升记为正，下降是相反意义的量", "下降 4 层记作 −4 层", "选 B"],
        "design_rationale": {
            "考点": "用正负数表示升降",
            "难度理由": "easy",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "方向看反（选+4），对应'语境方向看反'",
            "教学角色": "空间方向情境套用（visual_spatial 标签在此成立）",
        },
    },
    ("M-G7-POS-NEG", 2, 1): {
        "prompt": "把收入记为正：收入 500 元记作 +500 元。那么支出 350 元应记作什么？",
        "expected_answer": "-350元",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "target_error_tags": ["concept_confusion", "modeling_or_reading"],
        "solution_steps": ["支出与收入是相反意义的量", "收入记 +，支出记 −", "支出 350 元记作 −350 元"],
        "design_rationale": {
            "考点": "用正负数表示收支",
            "难度理由": "medium（与 easy 档同认知，档内区分弱——结构问题，非单题错）",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "不会用负数表示亏损（节点#2 错因）",
            "教学角色": "收支情境套用（收支记作仅保留此题，压缩模板重复 P1#6）",
        },
    },
    ("M-G7-POS-NEG", 2, 2): {
        "prompt": "下列说法正确的是（　）\nA. 0 是最小的正数\nB. 0 是最小的负数\nC. 0 既不是正数也不是负数\nD. 0 是正数",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "零的意义",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": ["0 既不是正数也不是负数", "0 是正数与负数的分界，也不是最小的数", "选 C"],
        "design_rationale": {
            "考点": "0 既不是正数也不是负数",
            "难度理由": "medium",
            "认知阶梯定位": "L3 变式（从'记作'转入属性判断）",
            "错因陷阱": "把 0 当正/负（节点#1 错因）完美对应",
            "教学角色": "零的意义核心概念题",
        },
    },
    ("M-G7-POS-NEG", 3, 0): {
        "prompt": "下列说法错误的是（　）\nA. 上升 5 米与下降 5 米是相反意义的量\nB. 向东 3 米与向西 3 米是相反意义的量\nC. 收入 8 元与支出 8 元是相反意义的量\nD. 向北 3 米与向南 5 米不是相反意义的量",
        "expected_answer": "D",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "相反意义量",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": ["向北与向南方向相反，是相反意义的量，与数值大小无关", "A、B、C 说法都正确", "说法错误的是 D"],
        "design_rationale": {
            "考点": "相反意义量的辨析（含数值无关性）",
            "难度理由": "medium（反向设问+细读）",
            "认知阶梯定位": "L3 变式（双否定干扰）",
            "错因陷阱": "'向北 3 米与向南 5 米不是相反意义'——数值不同≠不是相反意义，正中核心迷思",
            "教学角色": "高辨析度变式题",
        },
    },
    ("M-G7-POS-NEG", 3, 1): {
        "prompt": "下面各数：+5、−3.2、0、1/2、−7 中，负数有（　）\nA. 2 个，是 −3.2 和 −7\nB. 3 个，是 −3.2、0 和 −7\nC. 1 个，是 −7\nD. 2 个，是 −3.2 和 1/2",
        "expected_answer": "A",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "difficulty": "medium",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": [
            "负数带 − 号：−3.2、−7 是负数",
            "0 既不是正数也不是负数，不能算进负数",
            "1/2 是正数（没有 − 号）",
            "负数有 2 个：−3.2 和 −7，选 A",
        ],
        "design_rationale": {
            "考点": "负数识别与分类（含负小数），混合有理数分类（M-G7-RATIONAL-CLASSIFY 解锁节点）知识",
            "难度理由": "降 medium（P1#4/#5：原温度记作题无迁移成分，换真迁移题）",
            "认知阶梯定位": "L4 迁移——与前后知识混合（有理数分类），真迁移",
            "错因陷阱": "把 0 当负数、把 1/2 当负数、漏掉负小数（破除'负数=负整数'迷思）",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）",
        },
    },
    ("M-G7-POS-NEG", 3, 2): {
        "prompt": "在数轴上，0 的位置把数分成左右两部分。下列说法正确的是（　）\nA. 0 左边的数都是正数\nB. 0 右边的数都是正数\nC. 0 既在正数一边也在负数一边\nD. 0 不是数",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "零的意义",
        "difficulty": "medium",
        "target_error_tags": ["concept_confusion", "visual_spatial"],
        "solution_steps": ["数轴上 0 右边是正数，左边是负数", "0 是分界点，本身既不是正数也不是负数", "选 B"],
        "design_rationale": {
            "考点": "0 在数轴上的归属（左边负/右边正/0 是分界）",
            "难度理由": "降 medium（P1#4 诚实标定）",
            "认知阶梯定位": "L4（借用数轴，属解锁节点 M-G7-NUMBER-LINE 预告；题干自带信息可自足，不构成认知阻断）",
            "错因陷阱": "0 归入正或负（节点#1 错因）",
            "教学角色": "数轴预告 + 零的意义（visual_spatial 标签成立：数轴空间）",
        },
    },
    ("M-G7-POS-NEG", 4, 0): {
        "prompt": "判断：'向东走 5 米和向东走 3 米是相反意义的量。' 这个说法（　）\nA. 正确，方向相同就是相反意义的量\nB. 正确，走的距离不同就是相反意义的量\nC. 错误，方向相同不是相反意义的量\nD. 错误，走的距离不同就不是相反意义的量",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "相反意义量",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": [
            "相反意义的量要求意义相反（一个向东、一个向西）",
            "向东 5 米和向东 3 米方向相同，不是相反意义的量",
            "与走的距离大小无关，选 C",
        ],
        "design_rationale": {
            "考点": "相反意义的量识别（判断形式）",
            "难度理由": "easy 检测",
            "认知阶梯定位": "L2 检测",
            "错因陷阱": "把'方向相同'或'距离不同'误判为相反意义（'语境方向看反'变体）",
            "教学角色": "检测易档——替换与 B1-I0 重复的温度记作题（P1#6 压缩'记作'模板）",
        },
    },
    ("M-G7-POS-NEG", 4, 1): {
        "prompt": "下面说法正确的是（　）\nA. 收入 100 元和支出 50 元是相反意义的量\nB. 收入 100 元和收入 50 元是相反意义的量\nC. 支出 100 元和支出 50 元是相反意义的量\nD. 收入 100 元和支出 100 元不是相反意义的量",
        "expected_answer": "A",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "相反意义量",
        "difficulty": "medium",
        "target_error_tags": ["concept_confusion", "modeling_or_reading"],
        "solution_steps": [
            "收入与支出意义相反，是相反意义的量，与金额大小无关",
            "B、C 都是同一方向（都是收入 / 都是支出）",
            "D 说反了：金额相同也是相反意义的量",
            "选 A",
        ],
        "design_rationale": {
            "考点": "相反意义量的辨析（收支方向，数值无关）",
            "难度理由": "降 medium（P1#4 诚实标定：原 hard 虚高）",
            "认知阶梯定位": "L3 检测",
            "错因陷阱": "把'数值不同'当成'不是相反意义'、把同向不同值当相反意义",
            "教学角色": "检测题——与 B2-I1（收支记作）去重，改测辨析而非记作（P1#6）",
        },
    },
    ("M-G7-POS-NEG", 4, 2): {
        "prompt": "0 是最小的数吗？（　）\nA. 是，0 比所有数都小\nB. 是，0 是最小的自然数\nC. 不是，还有负数比 0 小\nD. 不是，0 不是数",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "零的意义",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": [
            "负数都比 0 小，如 −1、−3.2",
            "所以 0 不是最小的数",
            "注意：0 是最小的自然数（人教版），但自然数只是数的一部分",
            "选 C",
        ],
        "design_rationale": {
            "考点": "零的意义：0 不是最小的数（负数比 0 小）",
            "难度理由": "medium 复测",
            "认知阶梯定位": "L3 复测",
            "错因陷阱": "把'最小的自然数'当成'最小的数'、把 0 当'不是数'",
            "教学角色": "零的意义复测（P0#1：替换算术题 8×0）",
        },
    },
    ("M-G7-POS-NEG", 5, 0): {
        "prompt": "电梯从 8 楼下到 1 楼。如果从 1 楼上到 8 楼记作 +7 层，那么从 8 楼下到 1 楼记作多少层？",
        "expected_answer": "-7层",
        "answer_format": "text",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "target_error_tags": ["concept_confusion", "visual_spatial"],
        "solution_steps": ["上与下是相反意义的量", "8 楼到 1 楼相差 7 层", "下 7 层记作 −7 层"],
        "design_rationale": {
            "考点": "先算楼层差再取负（参照系转换）",
            "难度理由": "hard 基本成立（两步推理）",
            "认知阶梯定位": "L4 复测",
            "错因陷阱": "只记符号忘算差（+8/−8），对应'语境方向看反'",
            "教学角色": "本节点最佳 hard，判定层 hard 证据来源",
        },
    },
    ("M-G7-POS-NEG", 5, 1): {
        "prompt": "下面各数中，是负数的是（　）\nA. +3\nB. 0\nC. −2.5\nD. 1/2",
        "expected_answer": "C",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "用正负数表示",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": ["带 − 号的数是负数", "0 不是负数，+3 是正数，1/2 是正数", "选 C"],
        "design_rationale": {
            "考点": "负数识别（含负小数）",
            "难度理由": "easy",
            "认知阶梯定位": "L1 诊断正宗实现",
            "错因陷阱": "0 当负数、正数误判",
            "教学角色": "概念诊断题，含 −2.5 破除'负数=负整数'迷思",
        },
    },
    ("M-G7-POS-NEG", 5, 2): {
        "prompt": "海拔 0 米表示没有高度吗？（　）\nA. 表示，0 米就是没有高度\nB. 不表示，海拔 0 米是海平面的高度\nC. 表示，0 米是最低的高度\nD. 不表示，海拔 0 米就是没有海拔",
        "expected_answer": "B",
        "answer_format": "choice",
        "verification_intent": "unverifiable",
        "question_type": "零的意义",
        "target_error_tags": ["concept_confusion"],
        "solution_steps": [
            "海拔 0 米以海平面为基准，是高度的分界",
            "海平面以上记正、以下记负，0 米是参照而不是'没有'",
            "0 米也不是最低高度（还有海平面以下），选 B",
        ],
        "design_rationale": {
            "考点": "零的意义：0 作为基准/参照（海拔 0 米 = 海平面）",
            "难度理由": "medium 诊断",
            "认知阶梯定位": "L2 诊断",
            "错因陷阱": "把 0 当'没有'（0 米 = 没有高度）",
            "教学角色": "零的意义诊断题（P0#1：替换算术题 0÷5），与 B1-I2（0℃）互补：0 作分界 vs 0 作基准",
        },
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


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _row_by_id(rows: list[sqlite3.Row], question_id: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row["id"]) == question_id:
            return _row_dict(row)
    return None


def check_pilot_quality(build: dict[str, Any]) -> dict[str, Any]:
    """第三闸门：审查意见规则门禁（琢玉报告 P0/P1/P2 的整库质量属性断言）。

    选择说明（见模块 docstring）：审查报告是整库/跨批约束，逐批 reviewer_fn
    看不到整库；pilot 生成器确定性强，逐批规则审查形同虚设。因此琢玉报告的
    修订决定内嵌到题目，本函数作为"基于审查报告意见的规则审查"在整库层面
    执行——等价于 reviewer_fn 的规则化实现，作用于生成结果之后。

    检查项：
    - P0#1：POS-NEG 零槽位（B1-I2/B4-I2/B5-I2）为概念判断题（choice 且非算术）；
      POS-NEG 全节点无算术题（answer_format 全为 choice/text）。
    - P0#2：DECIMAL B2-I2/B4-I2 题干已注明答案形式（用小数/分数表示）。
    - P0#3：DECIMAL 含除数是小数覆盖（B2-I0），且 solution_steps 含"为什么
      移动小数点"解释（同时扩倍/商不变）。
    - P1#4：6 道降档题 difficulty == medium；每节点 hard 仅剩审查认定的标杆。
    - P1#5/#6：POS-NEG transfer 题为真迁移（B3-I1 混合有理数分类）；"记作"
      模板已压缩（温度×1、收支×1）。
    - P2#8：question_type 标签与内容一致（抽查关键槽位显式声明）。
    - P2#9：error_tags 贴切（温度/收支无 visual_spatial；电梯/数轴保留）。
    - design_rationale 五要素每题全齐。
    - trivial 抽检为零（两节点 contract 报告 trivial_question_count == 0）。

    返回 {"ok": bool, "errors": [str]}；build_bank 在 ok=False 时抛错（fail-fast，
    同 preflight 语义）。
    """
    errors: list[str] = []
    conn = db.connect(build["db_path"])
    conn.row_factory = sqlite3.Row
    try:
        pos_neg = conn.execute(
            "select * from question_items where node_id = ?", ("M-G7-POS-NEG",)
        ).fetchall()
        decimal = conn.execute(
            "select * from question_items where node_id = ?", ("M-PRE-DECIMAL-OPS",)
        ).fetchall()

        # ---- P0#1：零槽位概念判断 + POS-NEG 无算术题 ----
        pos_neg_ids = {str(r["id"]) for r in pos_neg}
        if not ZERO_SLOT_QUESTION_IDS[0].startswith("Q-"):
            errors.append("check_pilot_quality: ZERO_SLOT_QUESTION_IDS 配置异常")
        for question_id in ZERO_SLOT_QUESTION_IDS:
            row = _row_by_id(pos_neg, question_id)
            if row is None:
                errors.append(f"零槽位题缺失: {question_id}")
                continue
            if row["answer_format"] != "choice":
                errors.append(f"零槽位 {question_id} 应为概念判断题（choice），实际 {row['answer_format']}")
            if "计算" in str(row["prompt"]):
                errors.append(f"零槽位 {question_id} 出现'计算'字样，疑似算术题")
        for row in pos_neg:
            if str(row["answer_format"]) not in {"choice", "text"}:
                errors.append(
                    f"POS-NEG 出现算术题 {row['id']}（answer_format={row['answer_format']}），"
                    "概念节点不应有算术题（审查 P0#1）"
                )

        # ---- P0#2：答案形式明确 ----
        b2i2 = _row_by_id(decimal, "Q-M-PRE-DECIMAL-OPS-B2-I2")
        b4i2 = _row_by_id(decimal, "Q-M-PRE-DECIMAL-OPS-B4-I2")
        if b2i2 is None or "用小数表示" not in str(b2i2["prompt"]):
            errors.append("DECIMAL B2-I2 未注明答案形式'用小数表示'（P0#2）")
        if b4i2 is None or "用分数表示" not in str(b4i2["prompt"]):
            errors.append("DECIMAL B4-I2 未注明答案形式'用分数表示'（P0#2）")

        # ---- P0#3：除数小数覆盖 + 移动小数点解释 ----
        divisor_decimal = [
            r for r in decimal
            if re.search(r"÷\s*0\.", str(r["prompt"]))  # 除数是小数（0.x）
        ]
        if not divisor_decimal:
            errors.append("DECIMAL 缺少'除数是小数'覆盖（P0#3，应有 ÷0.x 题）")
        b2i0 = _row_by_id(decimal, "Q-M-PRE-DECIMAL-OPS-B2-I0")
        if b2i0 is not None:
            steps = str(b2i0["solution_steps_json"])
            if not re.search(r"同时", steps) or not re.search(r"商不变|扩大", steps):
                errors.append(
                    "DECIMAL B2-I0 的 solution_steps 缺少'为什么移动小数点'解释"
                    "（同时扩倍/商不变，P0#3）"
                )
        else:
            errors.append("DECIMAL B2-I0 缺失（标准除数小数题，P0#3）")

        # ---- P1#4：6 道降档题 medium + hard 仅剩标杆 ----
        for question_id in DOWNGRADED_QUESTION_IDS:
            node_id = question_id.split("-B")[0].replace("Q-", "")
            rows = pos_neg if node_id == "M-G7-POS-NEG" else decimal
            row = _row_by_id(rows, question_id)
            if row is None:
                errors.append(f"降档题缺失: {question_id}")
            elif row["difficulty"] != "medium":
                errors.append(
                    f"{question_id} 难度应诚实降为 medium（P1#4），实际 {row['difficulty']}"
                )
        for node_id in PILOT_NODE_IDS:
            rows = pos_neg if node_id == "M-G7-POS-NEG" else decimal
            hard_ids = {str(r["id"]) for r in rows if r["difficulty"] == "hard"}
            expected_hard = HARD_BENCHMARK_IDS[node_id]
            if hard_ids != expected_hard:
                errors.append(
                    f"{node_id} hard 题应仅剩审查标杆 {sorted(expected_hard)}，实际 {sorted(hard_ids)}"
                )

        # ---- P1#5：POS-NEG transfer 真迁移（B3-I1 混合有理数分类） ----
        b3i1 = _row_by_id(pos_neg, "Q-M-G7-POS-NEG-B3-I1")
        if b3i1 is None:
            errors.append("POS-NEG B3-I1 缺失（真迁移题，P1#5）")
        else:
            if b3i1["purpose_role"] != "transfer":
                errors.append(f"POS-NEG B3-I1 应保持 purpose_role=transfer，实际 {b3i1['purpose_role']}")
            if not re.search(r"负数有", str(b3i1["prompt"])):
                errors.append("POS-NEG B3-I1 未体现真迁移（负数识别×分类）")

        # ---- P2#8：question_type 标签与内容一致（抽查关键槽位） ----
        type_expectations = {
            ("M-G7-POS-NEG", "Q-M-G7-POS-NEG-B1-I0"): "用正负数表示",
            ("M-G7-POS-NEG", "Q-M-G7-POS-NEG-B1-I1"): "相反意义量",
            ("M-G7-POS-NEG", "Q-M-G7-POS-NEG-B1-I2"): "零的意义",
            ("M-G7-POS-NEG", "Q-M-G7-POS-NEG-B4-I1"): "相反意义量",
            ("M-PRE-DECIMAL-OPS", "Q-M-PRE-DECIMAL-OPS-B1-I1"): "小数加减",
            ("M-PRE-DECIMAL-OPS", "Q-M-PRE-DECIMAL-OPS-B2-I0"): "小数乘除",
        }
        for (node_id, question_id), expected_type in type_expectations.items():
            rows = pos_neg if node_id == "M-G7-POS-NEG" else decimal
            row = _row_by_id(rows, question_id)
            if row is None:
                errors.append(f"标签一致性检查目标缺失: {question_id}")
            elif str(row["question_type"]) != expected_type:
                errors.append(
                    f"{question_id} question_type 应为 {expected_type}，实际 {row['question_type']}"
                )

        # ---- P2#9：error_tags 贴切 ----
        for question_id, label in (
            ("Q-M-G7-POS-NEG-B1-I0", "温度题"),
            ("Q-M-G7-POS-NEG-B2-I1", "收支题"),
            ("Q-M-G7-POS-NEG-B4-I1", "收支辨析题"),
        ):
            row = _row_by_id(pos_neg, question_id)
            if row is None:
                errors.append(f"error_tags 检查目标缺失: {question_id}")
                continue
            tags = json.loads(str(row["error_tags_json"]))
            if "visual_spatial" in tags:
                errors.append(f"{label} {question_id} 不应含 visual_spatial（P2#9）")
        for question_id, label in (
            ("Q-M-G7-POS-NEG-B2-I0", "电梯题"),
            ("Q-M-G7-POS-NEG-B3-I2", "数轴题"),
            ("Q-M-G7-POS-NEG-B5-I0", "电梯两步题"),
        ):
            row = _row_by_id(pos_neg, question_id)
            if row is None:
                errors.append(f"error_tags 检查目标缺失: {question_id}")
                continue
            tags = json.loads(str(row["error_tags_json"]))
            if "visual_spatial" not in tags:
                errors.append(f"{label} {question_id} 应保留 visual_spatial（P2#9）")

        # ---- design_rationale 五要素全齐（30 题） ----
        for row in pos_neg + decimal:
            rationale_raw = str(row["design_rationale_json"] or "")
            try:
                rationale = json.loads(rationale_raw) if rationale_raw else {}
            except ValueError:
                rationale = {}
            missing = [
                key for key in ("考点", "难度理由", "认知阶梯定位", "错因陷阱", "教学角色")
                if not str((rationale or {}).get(key) or "").strip()
            ]
            if missing:
                errors.append(f"{row['id']} design_rationale 缺要素 {missing}（五要素必填）")

        # ---- trivial 抽检为零 ----
        for node_id in PILOT_NODE_IDS:
            contract = build["contracts"].get(node_id) or {}
            trivial_count = contract.get("trivial_question_count")
            if trivial_count is None:
                errors.append(f"{node_id} 契约报告缺失 trivial_question_count")
            elif trivial_count != 0:
                errors.append(
                    f"{node_id} 存在琐碎题抽检警告 {trivial_count} 条"
                    f"（{contract.get('trivial_warnings')}）——审查 P0/P2 要求无琐碎"
                )
    finally:
        conn.close()
    return {"ok": not errors, "errors": errors}


def build_bank(
    db_path: Path | str = BANK_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
    commit: bool = True,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """init_schema + seed 图谱 + 逐节点跑 generate_node_bank（真实题目）→ 契约校验 → 质量门禁。"""
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
        build = {
            "db_path": str(db_path.resolve()),
            "results": results,
            "contracts": contracts,
        }
        build["quality"] = check_pilot_quality(build)
        if not build["quality"]["ok"]:
            raise AssertionError(
                "第三闸门（审查意见规则门禁）未通过：\n- "
                + "\n- ".join(build["quality"]["errors"])
            )
        return build
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
            f"难度={contract['difficulty_counts']} 校验状态={contract['answer_verification_counts']} "
            f"trivial={contract['trivial_question_count']}"
        )
        for error in contract["errors"]:
            print(f"  ERROR: {error}")
        for warning in contract["trivial_warnings"]:
            print(f"  TRIVIAL-WARN: {warning}")
    quality = build.get("quality") or {}
    print(f"\n第三闸门（审查意见规则门禁）: ok={quality.get('ok')}")
    for error in quality.get("errors", []):
        print(f"  QUALITY-ERROR: {error}")


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
