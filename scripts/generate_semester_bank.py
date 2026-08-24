"""数据驱动全量题库生成框架（objective ①a：pilot 脚本 → 全量生成器）。

把 `scripts/pilot_generate_semester_bank.py` 的内联撰写模式升级为
**节点注册表 + 每节点题目数据 + 管线串联 + 审查钩子 + 报告**的数据驱动框架，
为 ①b 起的分批全量生成（56 节点）提供底座。pilot 脚本原样保留作回归参考；
本脚本是后续全量生成的入口。

## 框架构成

1. **节点注册表**：`build_registry(graph)` 从图谱 v2 读全部 56 节点
   （id/name/stage/priority）；`generation_order(graph)` 给出生成顺序：
   **七上主线 P0 → 七上主线 P1/P2 → 小学关键前置 → 衔接桥梁**（按设计稿
   优先级；阶段内按 priority P0<P1<P2，再按 id 稳定排序）。
2. **每节点题目数据**：`NODE_QUESTIONS: dict[node_id, list[question_dict]]`。
   每题 dict 自描述（prompt/expected_answer/answer_format/question_type/
   variant_level/difficulty/purpose_role/solution_steps/error_tags/
   design_rationale 五要素 + estimated_minutes 等元数据）；列表按槽位序
   B1-I0..B5-I2 排列（`slot` 字段供序校验，generate_fn 剥离，不落库）。
   现有 pilot 30 题（2 节点）**逐字迁移**进本结构（内容一字不改，仅框架搬移；
   `--check-migration` 可与 pilot 脚本逐字比对）。
3. **管线串联**：`build_bank` 对每个注册节点 → `qg.generate_node_bank`
   （generate_fn 按槽位读 NODE_QUESTIONS → sympy 校验门禁 → 元数据派生 →
   入库）→ `qg.validate_node_bank_contract` 契约校验。范围选择：
   `--nodes M-A,M-B`（按给定序）/ `--stage 七上主线` / `--all` /
   缺省 = 已有 author 题目的节点（与 pilot 行为一致）。
4. **审查钩子**：`--review` 开启规则审查——`check_node_quality` 按节点执行
   （pilot 节点沿用琢玉 P0/P1/P2 断言 + 对所有节点生效的通用结构断言：
   契约 valid / design_rationale 五要素 / trivial 为零 / 声明与矩阵槽位一致），
   `check_full_bank_quality` 做全库汇总；`PEDAGOGY_REVIEW_HOOK` 与
   `reviewer_fn` 参数为真实琢玉逐题审查的预留接入位（objective ②）。
   **不通过默认 fail-fast**（提交前中止，不入库残留）；`--review-mark`
   改为只标记不中止（失败进报告，退出码 0）。
5. **报告**：每节点统计（题数/难度分布/verified/契约 valid/trivial 警告）
   + 全库汇总；`--report PATH` 额外写 JSON 报告。

## 与 pilot 的关系

- pilot 脚本保留（回归参考 + test_pilot_bank 继续测它）；本脚本为全量框架。
- 两节点 30 题内容与 pilot **逐字一致**（回归验证：源级 `--check-migration` +
  库级列比对），仅数据结构从 `_QUESTIONS[(node,batch,item)]` 改为
  `NODE_QUESTIONS[node][slot]` 自描述 dict。库级比对中唯一差异是
  `raw_json` 的诊断键集：pilot 对未显式声明错因标签的题由管线派生
  （raw 无 target_error_tags 键），本框架每题显式声明（键存在、值相同）——
  语义完全一致，其余全部列逐字节相同。

## 边界

只写题库 sqlite（默认 `data/question_banks/math/semester_bank_v1.sqlite`）；
不碰 learning_system/、app/、tests/。题目入库的 answer_verification /
rollback / secondary / source 等字段由管线处理（照 pilot 模式）。

用法：
    python3 scripts/generate_semester_bank.py [--db PATH] [--nodes A,B|--stage S|--all] \
        [--review [--review-mark]] [--preflight-only] [--report PATH] [--check-migration]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, question_generation_service as qg  # noqa: E402
from learning_system.answer_verification import verify_expected_answer  # noqa: E402

BANK_DIR = PROJECT_ROOT / "data" / "question_banks" / "math"
BANK_PATH = BANK_DIR / "semester_bank_v1.sqlite"
GRAPH_PATH = PROJECT_ROOT / "data" / "knowledge_graphs" / "math" / "math_knowledge_graph_v2.json"

# ---------------------------------------------------------------------------
# 生成顺序常量（设计稿优先级；generation_order 据此排序）
# ---------------------------------------------------------------------------
STAGE_ORDER: tuple[str, ...] = ("七上主线", "小学关键前置", "衔接桥梁")
PRIORITY_ORDER: tuple[str, ...] = ("P0", "P1", "P2")

# ---------------------------------------------------------------------------
# 琢玉审查报告（docs/qa/pilot_bank_pedagogy_review.md）对 pilot 两节点的
# 修订验收常量（自 pilot 脚本迁移；`--review` 的节点级断言引用）
# ---------------------------------------------------------------------------
PILOT_NODE_IDS: tuple[str, ...] = ("M-PRE-DECIMAL-OPS", "M-G7-POS-NEG")

# 琢玉审查报告 P0 替换的 3 个"零的意义"槽位（断言其不再是算术题）
ZERO_SLOT_QUESTION_IDS: tuple[str, ...] = (
    "Q-M-G7-POS-NEG-B1-I2",
    "Q-M-G7-POS-NEG-B4-I2",
    "Q-M-G7-POS-NEG-B5-I2",
)

# 琢玉审查报告 P1 降档的 6 道 hard 虚高题
DOWNGRADED_QUESTION_IDS: tuple[str, ...] = (
    "Q-M-PRE-DECIMAL-OPS-B3-I1",
    "Q-M-PRE-DECIMAL-OPS-B3-I2",
    "Q-M-PRE-DECIMAL-OPS-B5-I0",
    "Q-M-G7-POS-NEG-B3-I1",
    "Q-M-G7-POS-NEG-B3-I2",
    "Q-M-G7-POS-NEG-B4-I1",
)

# 本节点各保留 1 道真 hard 标杆（判定层 hard 证据来源）
HARD_BENCHMARK_IDS: dict[str, set[str]] = {
    "M-PRE-DECIMAL-OPS": {"Q-M-PRE-DECIMAL-OPS-B4-I1"},  # 0.25×0.4（审查：hard 名副其实）
    "M-G7-POS-NEG": {"Q-M-G7-POS-NEG-B5-I0"},            # 电梯 8→1 楼（审查：本节点最佳 hard）
}

# question_type 标签一致性抽查（琢玉 P2#8：标签与内容一致）
QUESTION_TYPE_EXPECTATIONS: dict[str, str] = {
    "Q-M-G7-POS-NEG-B1-I0": "用正负数表示",
    "Q-M-G7-POS-NEG-B1-I1": "相反意义量",
    "Q-M-G7-POS-NEG-B1-I2": "零的意义",
    "Q-M-G7-POS-NEG-B4-I1": "相反意义量",
    "Q-M-PRE-DECIMAL-OPS-B1-I1": "小数加减",
    "Q-M-PRE-DECIMAL-OPS-B2-I0": "小数乘除",
}

# 琢玉 P2#9：error_tags 贴切（温度/收支去 visual_spatial，电梯/数轴保留）
ERROR_TAGS_NO_SPATIAL: tuple[tuple[str, str], ...] = (
    ("Q-M-G7-POS-NEG-B1-I0", "温度题"),
    ("Q-M-G7-POS-NEG-B2-I1", "收支题"),
    ("Q-M-G7-POS-NEG-B4-I1", "收支辨析题"),
)
ERROR_TAGS_KEEP_SPATIAL: tuple[tuple[str, str], ...] = (
    ("Q-M-G7-POS-NEG-B2-I0", "电梯题"),
    ("Q-M-G7-POS-NEG-B3-I2", "数轴题"),
    ("Q-M-G7-POS-NEG-B5-I0", "电梯两步题"),
)

# ---------------------------------------------------------------------------
# 每节点题目数据（数据驱动核心；①b 起按节点分批 author 时向此追加）
#
# 结构：dict[node_id, list[question_dict]]，list 按槽位序 B1-I0..B5-I2 排列
# （对应 qg 矩阵 5 批 × 3 题；generate_fn 按 (batch,item) 定位并校验 slot）。
# 每题 dict 自描述字段：
# - prompt/expected_answer/answer_format/question_type/solution_steps/
#   design_rationale（五要素：考点/难度理由/认知阶梯定位/错因陷阱/教学角色）
#   —— 与 pilot 逐字一致；
# - verification_intent：内部声明（preflight 强校验用；generate_fn 剥离，不落库）；
# - variant_level/difficulty/purpose_role：显式声明（覆盖矩阵槽位默认；
#   `--review` 校验 variant_level/purpose_role 与矩阵一致，防 authoring 漂移）；
# - error_tags：显式声明错因标签（generate_fn 映射为 target_error_tags 进管线；
#   缺省时管线按题型派生）；
# - estimated_minutes：可选元数据（缺省由管线派生）。
# - slot：可读槽位标识（generate_fn 剥离，不落库）。
# ---------------------------------------------------------------------------
NODE_QUESTIONS: dict[str, list[dict[str, Any]]] = {
    # ===== M-PRE-DECIMAL-OPS 小数运算（计算向：13 verified + 2 unverifiable） =====
    "M-PRE-DECIMAL-OPS": [
        {
            "slot": "B1-I0",
            "prompt": "计算：3.2 + 1.7，写出答案。",
            "expected_answer": "4.9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["对齐小数点：3.2 与 1.7 的十分位对齐", "3.2 + 1.7 = 4.9"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "一位小数加法与小数点对齐", "难度理由": "锚点题取最简，medium 是教学锚点难度而非认知难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'先按整数算（32+17），再点小数点'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪道题要先对齐小数点再计算？（　）\nA. 2.4 × 3\nB. 1.5 + 2.63\nC. 0.5 ÷ 0.1\nD. 7 × 0.5",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "小数加减",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["小数加减法要对齐小数点（十分位对齐十分位）", "A、D 是乘法（末位对齐），C 是除法（转化），都不需要对齐小数点", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "判断'小数点对齐'规则的适用对象（小数加减法）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断考点/规则而非直接计算（P2#7 补识别档）", "错因陷阱": "把乘法'末位对齐'误当成'小数点对齐'（concept_confusion / calculation_or_symbol）", "教学角色": "L1 识别脚手架，填补原 0.6×10 直接计算冒充识别的空转"},
        },
        {
            "slot": "B1-I2",
            "prompt": "计算：0.5 化成分数是多少？",
            "expected_answer": "1/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0.5 表示十分之五", "5/10 约分得 1/2"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "一位小数化分数（十分之五）", "难度理由": "easy（互化锚点）", "认知阶梯定位": "L1 识别锚点", "错因陷阱": "无（锚点）", "教学角色": "互化方向的基准示范"},
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：7.2 ÷ 0.8",
            "expected_answer": "9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数乘除",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["除数是小数：把被除数和除数同时扩大 10 倍，商不变", "7.2 ÷ 0.8 = 72 ÷ 8", "72 ÷ 8 = 9", "为什么能这样：被除数和除数同时乘相同的数（10），商不变——这就是小数除法移动小数点的道理"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "除数是小数的小数除法（转化法：同时扩倍）", "难度理由": "medium——转化一步是节点#2 错因'除数是小数不会转化'的核心，比纯套用多一步推理", "认知阶梯定位": "L2 套用（标准小数除法，P0#3 补覆盖）", "错因陷阱": "不会转化直接除（把 7.2÷0.8 当 7.2÷8）", "教学角色": "除数小数转化的标准变式，掌握标准'能解释小数除法为何移动小数点'的取证题"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：1.2 × 3.5",
            "expected_answer": "4.2",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数乘除",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先按整数算：12 × 35 = 420", "两个因数各有一位小数，积有两位小数：4.20 = 4.2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两位×一位→两位小数乘法", "难度理由": "medium（整数乘 12×35 + 积位数两步）", "认知阶梯定位": "L2 套用", "错因陷阱": "积小数位数（420→4.20→4.2）", "教学角色": "乘法标准变式"},
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：2/5 + 0.3，用小数表示答案。",
            "expected_answer": "0.7",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把 2/5 化成小数 0.4", "0.4 + 0.3 = 0.7"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分数化小数后加法（互化+加减混合）", "难度理由": "medium（需先统一形式）", "认知阶梯定位": "L3 变式（换形式混合）", "错因陷阱": "2/5 误读为 2.5、互化后忘对齐", "教学角色": "互化-加减桥接题；题干注明'用小数表示'消除答案形式歧义（P0#2）"},
        },
        {
            "slot": "B3-I0",
            "prompt": "买文具花了 12.5 元，买书花了 18.75 元，一共花了多少元？",
            "expected_answer": "31.25",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "小数加减",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["理解情境：求一共用加法，先自己列式 12.5 + 18.75", "估算核对：12.5 + 18.75 ≈ 12 + 19 = 31，答案应在 31 左右", "对齐小数点：12.5 + 18.75 = 31.25（元）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "不同位数小数加法的列式建模 + 对齐", "难度理由": "medium（进位+对齐，且需自己列式）", "认知阶梯定位": "L3 换语境（情境应用题；删去已给表达式以测列式，P2#10）", "错因陷阱": "小数点对齐（12.5 与 18.75 位数不同）+ 不估算直接算", "教学角色": "情境应用示范；solution_steps 内置估算步补'结果不估算'错因覆盖（P2#11）"},
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：3 × 0.4 ÷ 0.2",
            "expected_answer": "6",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "小数乘除",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "transfer",
            "solution_steps": ["从左到右：3 × 0.4 = 1.2", "1.2 ÷ 0.2：被除数、除数同时扩大 10 倍 → 12 ÷ 2", "12 ÷ 2 = 6"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "同级混合运算顺序 + 除数小数转化", "难度理由": "降 medium：三步左到右、规则明确，够不上 hard（P1#4 诚实标定）", "认知阶梯定位": "L4 迁移（混合运算顺序属 M-PRE-ORDER-OPS 前置，迁移成立）", "错因陷阱": "÷0.2 不转化直接除（除数小数转化）", "教学角色": "除数小数转化覆盖点（与 B2-I0 互补：这里转化内嵌在混合运算里）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：3/4 × 0.8",
            "expected_answer": "0.6",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "transfer",
            "solution_steps": ["把 3/4 化成小数 0.75", "0.75 × 0.8 = 0.6"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数化小数后乘法", "难度理由": "降 medium：0.75×0.8 积位数计数是真难点，但够不上 hard（P1#4）", "认知阶梯定位": "L4 迁移（互化+乘双知识）", "错因陷阱": "积位数（0.600→0.6）", "教学角色": "互化-乘法迁移题"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：5.3 − 1.8",
            "expected_answer": "3.5",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["对齐小数点", "十分位 3 − 8 不够减，向个位借 1：13 − 8 = 5", "个位 4 − 1 = 3，结果 3.5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "一位小数减法（含借位）", "难度理由": "easy 检测——借位是唯一陷阱，定位检测易档", "认知阶梯定位": "L2 检测", "错因陷阱": "借位错 / 小数点对齐错（P2#10：换有借位的 5.3−1.8，让'小数点对齐错'有处可错）", "教学角色": "掌握档快速检测（替换原 7.3+2.7 无陷阱琐碎题）"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：0.25 × 0.4",
            "expected_answer": "0.1",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数乘除",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["按整数算：25 × 4 = 100", "两个因数共有 3 位小数：0.100 = 0.1", "估算核对：0.25 × 0.4 ≈ 0.1（四分之一乘 0.4）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "积小数位数 + 去尾零", "难度理由": "hard 名副其实（25×4=100→0.100→0.1，三处可错）", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "位数错（1 或 0.01）、去尾零遗忘", "教学角色": "本节点 hard 标杆，判定层 hard 证据的可靠来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：0.75 − 1/4，用分数表示答案。",
            "expected_answer": "1/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把 1/4 化成小数 0.25（或把 0.75 化成分数 3/4）", "0.75 − 0.25 = 0.5", "0.5 用分数表示 = 1/2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "小数减分数需统一形式", "难度理由": "medium 复测", "认知阶梯定位": "L3 复测", "错因陷阱": "1/4 化 0.25 后相减（0.5）", "教学角色": "防'会背不会用'复测；题干注明'用分数表示'消除答案形式歧义（P0#2）"},
        },
        {
            "slot": "B5-I0",
            "prompt": "用简便方法计算：10 − 3.75 − 4.25",
            "expected_answer": "2",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "小数加减",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["简便策略：先算 3.75 + 4.25 = 8（凑整）", "10 − 8 = 2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "凑整策略（3.75 + 4.25 = 8）", "难度理由": "降 medium：顺序算也能得分、无错误陷阱，但'用简便方法计算'强制用策略（P1#4 + P2 表述）", "认知阶梯定位": "L4 复测策略题", "错因陷阱": "策略盲区（看不出凑整），非计算错误", "教学角色": "策略性复测"},
        },
        {
            "slot": "B5-I1",
            "prompt": "计算：0.2 × 0.3",
            "expected_answer": "0.06",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数乘除",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["按整数算：2 × 3 = 6", "两个因数共有 2 位小数：0.06（易错点：0.6 是错的）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "积小数位数", "难度理由": "easy 但陷阱密度高（0.6 vs 0.06），easy 档配陷阱题诊断力强", "认知阶梯定位": "L1 诊断（识别位值错因）", "错因陷阱": "0.6 是错的（位数数错），对应节点'结果不估算/计算符号'类错因", "教学角色": "最佳诊断题，直接区分'会算不会点小数点'"},
        },
        {
            "slot": "B5-I2",
            "prompt": "计算：3/20 化成小数",
            "expected_answer": "0.15",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["3 ÷ 20 = 0.15", "注意 3/20 = 0.15（不是 1.5，易错点）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数化小数（除数 20 需补位）", "难度理由": "medium（3÷20 心算需补位）", "认知阶梯定位": "L2 诊断", "错因陷阱": "1.5（丢零）", "教学角色": "互化方向诊断（分数→小数），与 B1-I2 方向互补"},
        },
    ],
    # ===== M-G7-POS-NEG 正数和负数（概念向：15 unverifiable） =====
    "M-G7-POS-NEG": [
        {
            "slot": "B1-I0",
            "prompt": "生活中的温度：某地气温零上 3℃ 记作 +3℃，零下 5℃ 应记作什么？",
            "expected_answer": "-5℃",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["零上与零下是相反意义的量", "零上用 + 表示，零下就用 − 表示", "零下 5℃ 记作 −5℃"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用正负数表示相反意义的量（温度基准）", "难度理由": "medium 锚点", "认知阶梯定位": "标准例题（L2 套用基准）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲解'零上/零下'分界的标准情境（温度记作仅保留此题，压缩模板重复 P1#6）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下列各组量中，具有相反意义的一组是（　）\nA. 向东走 3 米和向南走 3 米\nB. 收入 200 元和支出 200 元\nC. 上升 2 米和上升 1 米\nD. 向东走 3 米和向东走 5 米",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "相反意义量",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["相反意义的量：意义相反（收入↔支出），与数值大小无关", "A 东与南不是相反方向；C、D 是同一方向", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'相反意义'（方向相反/收支相反，与数值无关）", "难度理由": "easy", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "东/南（方向不同但非相反）、同向不同值（C/D），对应'语境方向看反'", "教学角色": "概念识别脚手架，本节点最佳 L1"},
        },
        {
            "slot": "B1-I2",
            "prompt": "0℃ 表示没有温度吗？（　）\nA. 表示，0℃ 就是没有温度\nB. 表示，0℃ 的温度是 0\nC. 不表示，0℃ 是零上与零下的分界点\nD. 不表示，0℃ 是最低的温度",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "零的意义",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0℃ 不是'没有温度'，而是零上与零下的分界点（参照点）", "0 是温度的分界，0 本身不是'没有'", "0℃ 也不是最低温度（还有零下温度），选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "零的意义：0 作为分界/参照点而非'没有'", "难度理由": "easy（L1 概念判断）", "认知阶梯定位": "L1 识别（P0#1：替换琐碎算术题 5−5，必须经概念判断而非算术）", "错因陷阱": "把 0 当'没有'（0℃=没有温度）、把 0℃ 当最低温度", "教学角色": "零的意义概念题（与 B2-I2 的'0 不是正负数'互补：此处测 0 的参照意义）"},
        },
        {
            "slot": "B2-I0",
            "prompt": "电梯从地面（0 层）上升 6 层，记作 +6 层；那么从地面下降 4 层，应记作（　）层。\nA. +4\nB. −4\nC. 4\nD. 0",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["上升记为正，下降是相反意义的量", "下降 4 层记作 −4 层", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "用正负数表示升降", "难度理由": "easy", "认知阶梯定位": "L2 套用", "错因陷阱": "方向看反（选+4），对应'语境方向看反'", "教学角色": "空间方向情境套用（visual_spatial 标签在此成立）"},
        },
        {
            "slot": "B2-I1",
            "prompt": "把收入记为正：收入 500 元记作 +500 元。那么支出 350 元应记作什么？",
            "expected_answer": "-350元",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["支出与收入是相反意义的量", "收入记 +，支出记 −", "支出 350 元记作 −350 元"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用正负数表示收支", "难度理由": "medium（与 easy 档同认知，档内区分弱——结构问题，非单题错）", "认知阶梯定位": "L2 套用", "错因陷阱": "不会用负数表示亏损（节点#2 错因）", "教学角色": "收支情境套用（收支记作仅保留此题，压缩模板重复 P1#6）"},
        },
        {
            "slot": "B2-I2",
            "prompt": "下列说法正确的是（　）\nA. 0 是最小的正数\nB. 0 是最小的负数\nC. 0 既不是正数也不是负数\nD. 0 是正数",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "零的意义",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["0 既不是正数也不是负数", "0 是正数与负数的分界，也不是最小的数", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "0 既不是正数也不是负数", "难度理由": "medium", "认知阶梯定位": "L3 变式（从'记作'转入属性判断）", "错因陷阱": "把 0 当正/负（节点#1 错因）完美对应", "教学角色": "零的意义核心概念题"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法错误的是（　）\nA. 上升 5 米与下降 5 米是相反意义的量\nB. 向东 3 米与向西 3 米是相反意义的量\nC. 收入 8 元与支出 8 元是相反意义的量\nD. 向北 3 米与向南 5 米不是相反意义的量",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "相反意义量",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["向北与向南方向相反，是相反意义的量，与数值大小无关", "A、B、C 说法都正确", "说法错误的是 D"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "相反意义量的辨析（含数值无关性）", "难度理由": "medium（反向设问+细读）", "认知阶梯定位": "L3 变式（双否定干扰）", "错因陷阱": "'向北 3 米与向南 5 米不是相反意义'——数值不同≠不是相反意义，正中核心迷思", "教学角色": "高辨析度变式题"},
        },
        {
            "slot": "B3-I1",
            "prompt": "下面各数：+5、−3.2、0、1/2、−7 中，负数有（　）\nA. 2 个，是 −3.2 和 −7\nB. 3 个，是 −3.2、0 和 −7\nC. 1 个，是 −7\nD. 2 个，是 −3.2 和 1/2",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "transfer",
            "solution_steps": ["负数带 − 号：−3.2、−7 是负数", "0 既不是正数也不是负数，不能算进负数", "1/2 是正数（没有 − 号）", "负数有 2 个：−3.2 和 −7，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负数识别与分类（含负小数），混合有理数分类（M-G7-RATIONAL-CLASSIFY 解锁节点）知识", "难度理由": "降 medium（P1#4/#5：原温度记作题无迁移成分，换真迁移题）", "认知阶梯定位": "L4 迁移——与前后知识混合（有理数分类），真迁移", "错因陷阱": "把 0 当负数、把 1/2 当负数、漏掉负小数（破除'负数=负整数'迷思）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "在数轴上，0 的位置把数分成左右两部分。下列说法正确的是（　）\nA. 0 左边的数都是正数\nB. 0 右边的数都是正数\nC. 0 既在正数一边也在负数一边\nD. 0 不是数",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "零的意义",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "transfer",
            "solution_steps": ["数轴上 0 右边是正数，左边是负数", "0 是分界点，本身既不是正数也不是负数", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "0 在数轴上的归属（左边负/右边正/0 是分界）", "难度理由": "降 medium（P1#4 诚实标定）", "认知阶梯定位": "L4（借用数轴，属解锁节点 M-G7-NUMBER-LINE 预告；题干自带信息可自足，不构成认知阻断）", "错因陷阱": "0 归入正或负（节点#1 错因）", "教学角色": "数轴预告 + 零的意义（visual_spatial 标签成立：数轴空间）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "判断：'向东走 5 米和向东走 3 米是相反意义的量。' 这个说法（　）\nA. 正确，方向相同就是相反意义的量\nB. 正确，走的距离不同就是相反意义的量\nC. 错误，方向相同不是相反意义的量\nD. 错误，走的距离不同就不是相反意义的量",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "相反意义量",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["相反意义的量要求意义相反（一个向东、一个向西）", "向东 5 米和向东 3 米方向相同，不是相反意义的量", "与走的距离大小无关，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "相反意义的量识别（判断形式）", "难度理由": "easy 检测", "认知阶梯定位": "L2 检测", "错因陷阱": "把'方向相同'或'距离不同'误判为相反意义（'语境方向看反'变体）", "教学角色": "检测易档——替换与 B1-I0 重复的温度记作题（P1#6 压缩'记作'模板）"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下面说法正确的是（　）\nA. 收入 100 元和支出 50 元是相反意义的量\nB. 收入 100 元和收入 50 元是相反意义的量\nC. 支出 100 元和支出 50 元是相反意义的量\nD. 收入 100 元和支出 100 元不是相反意义的量",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "相反意义量",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["收入与支出意义相反，是相反意义的量，与金额大小无关", "B、C 都是同一方向（都是收入 / 都是支出）", "D 说反了：金额相同也是相反意义的量", "选 A"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "相反意义量的辨析（收支方向，数值无关）", "难度理由": "降 medium（P1#4 诚实标定：原 hard 虚高）", "认知阶梯定位": "L3 检测", "错因陷阱": "把'数值不同'当成'不是相反意义'、把同向不同值当相反意义", "教学角色": "检测题——与 B2-I1（收支记作）去重，改测辨析而非记作（P1#6）"},
        },
        {
            "slot": "B4-I2",
            "prompt": "0 是最小的数吗？（　）\nA. 是，0 比所有数都小\nB. 是，0 是最小的自然数\nC. 不是，还有负数比 0 小\nD. 不是，0 不是数",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "零的意义",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["负数都比 0 小，如 −1、−3.2", "所以 0 不是最小的数", "注意：0 是最小的自然数（人教版），但自然数只是数的一部分", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "零的意义：0 不是最小的数（负数比 0 小）", "难度理由": "medium 复测", "认知阶梯定位": "L3 复测", "错因陷阱": "把'最小的自然数'当成'最小的数'、把 0 当'不是数'", "教学角色": "零的意义复测（P0#1：替换算术题 8×0）"},
        },
        {
            "slot": "B5-I0",
            "prompt": "电梯从 8 楼下到 1 楼。如果从 1 楼上到 8 楼记作 +7 层，那么从 8 楼下到 1 楼记作多少层？",
            "expected_answer": "-7层",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["上与下是相反意义的量", "8 楼到 1 楼相差 7 层", "下 7 层记作 −7 层"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "先算楼层差再取负（参照系转换）", "难度理由": "hard 基本成立（两步推理）", "认知阶梯定位": "L4 复测", "错因陷阱": "只记符号忘算差（+8/−8），对应'语境方向看反'", "教学角色": "本节点最佳 hard，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "下面各数中，是负数的是（　）\nA. +3\nB. 0\nC. −2.5\nD. 1/2",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用正负数表示",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["带 − 号的数是负数", "0 不是负数，+3 是正数，1/2 是正数", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "负数识别（含负小数）", "难度理由": "easy", "认知阶梯定位": "L1 诊断正宗实现", "错因陷阱": "0 当负数、正数误判", "教学角色": "概念诊断题，含 −2.5 破除'负数=负整数'迷思"},
        },
        {
            "slot": "B5-I2",
            "prompt": "海拔 0 米表示没有高度吗？（　）\nA. 表示，0 米就是没有高度\nB. 不表示，海拔 0 米是海平面的高度\nC. 表示，0 米是最低的高度\nD. 不表示，海拔 0 米就是没有海拔",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "零的意义",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["海拔 0 米以海平面为基准，是高度的分界", "海平面以上记正、以下记负，0 米是参照而不是'没有'", "0 米也不是最低高度（还有海平面以下），选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "零的意义：0 作为基准/参照（海拔 0 米 = 海平面）", "难度理由": "medium 诊断", "认知阶梯定位": "L2 诊断", "错因陷阱": "把 0 当'没有'（0 米 = 没有高度）", "教学角色": "零的意义诊断题（P0#1：替换算术题 0÷5），与 B1-I2（0℃）互补：0 作分界 vs 0 作基准"},
        },
    ],
    # ===== M-G7-NUMBER-LINE 数轴（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="数轴把数变成位置，越往右越大"；seed=画数轴/在数轴上表示数/用数轴比较大小；
    # common_mistakes=单位长度不一致/正负方向反/分数小数位置不准；diagnostic_probes=标5个数/根据点写数。
    # authoring 原则（琢玉教训）：L1 真识别（判断规则而非直接算）；hard 真难（跨 0 距离、中点策略、
    # 多语句核验）；同句式 ≤2；每题经概念判断（标点/读数/比较），无算术冒充。
    "M-G7-NUMBER-LINE": [
        {
            "slot": "B1-I0",
            "prompt": "在数轴上，点 M 在原点左边 2 个单位长度处，点 N 在原点右边 2 个单位长度处。点 M、点 N 分别表示什么数？",
            "expected_answer": "−2 和 2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["原点左边的数带负号，右边的数带正号", "M 在原点左边 2 个单位 → M 表示 −2", "N 在原点右边 2 个单位 → N 表示 2"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "根据位置写数（方向定符号 + 单位长度计数，'在数轴上表示数'）", "难度理由": "medium 锚点——两点定位是'位置↔数'双向映射的标准演示，方向+计数两步", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；两点对称顺带为相反数做预告）", "教学角色": "讲本质用——'数轴把数变成位置，越往右越大'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "画数轴必须有的三要素是（　）\nA. 刻度线、箭头、数字\nB. 原点、正方向、单位长度\nC. 直线、箭头、单位\nD. 原点、箭头、刻度",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "画数轴",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["数轴三要素：原点、正方向、单位长度", "A/C/D 都混入了'箭头/刻度'等非必要元素", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别数轴三要素（原点/正方向/单位长度，'画数轴'）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则而非动手画）", "错因陷阱": "把'刻度/箭头/数字'当要素（三要素记忆模糊，是'单位长度不一致'等错因的源头）", "教学角色": "L1 识别脚手架，本节点最佳 L1"},
        },
        {
            "slot": "B1-I2",
            "prompt": "小明画的'数轴'上，0 到 1 是一格，1 到 2 也是一格，可 −1 到 0 却画成了三格。这条'数轴'错在（　）\nA. 没有标原点\nB. 单位长度不一致\nC. 正方向标错\nD. 没有错",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "画数轴",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["数轴要求全轴单位长度统一", "0 到 1、1 到 2 各一格，−1 到 0 三格 → 单位长度不一致", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别单位长度必须全轴统一（'画数轴'三要素之单位长度）", "难度理由": "easy——单陷阱识别，但陷阱即节点头号错因", "认知阶梯定位": "L1 识别（判断'哪里画错了'）", "错因陷阱": "单位长度不一致（0 到 1 一格 vs −1 到 0 三格，节点 #1 错因）", "教学角色": "动手画之前的'看出错'脚手架"},
        },
        {
            "slot": "B2-I0",
            "prompt": "在数轴上，表示 −2 的点在（　）\nA. 原点右边\nB. 原点左边\nC. 原点上\nD. 位置不能确定",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["原点右边是正数，左边是负数", "−2 是负数 → 在原点左边", "选 B"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "负数在原点左边（方向映射，'在数轴上表示数'）", "难度理由": "easy 套用——方向单步判断", "认知阶梯定位": "L2 套用（直接运用'左负右正'）", "错因陷阱": "正负方向反（选 A，节点 #2 错因）", "教学角色": "L2 套用脚手架"},
        },
        {
            "slot": "B2-I1",
            "prompt": "0 到 1 之间平均分成 10 小格，点 A 在从 0 往右数第 7 小格处。点 A 表示什么数？（　）\nA. 0.7\nB. 7\nC. 0.07\nD. 1.7",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["1 平均分成 10 小格 → 每小格表示 0.1", "从 0 往右数第 7 小格 → 7 × 0.1 = 0.7", "选 A"],
            "error_tags": ["modeling_or_reading", "visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "单位长度细分下读小数（十分位，'在数轴上表示数'）", "难度理由": "medium——需先算每格 0.1 再数 7 格，两步", "认知阶梯定位": "L2 套用（小数标点起点）", "错因陷阱": "数格错、把第 7 小格直接当 7（忘乘每格 0.1，选项 B 即此陷阱），对应节点 #3 错因'分数小数位置不准'", "教学角色": "小数标点标准变式（choice 形式，选项 B 直接暴露'数格忘换算'）"},
        },
        {
            "slot": "B2-I2",
            "prompt": "在数轴上标出 −2、−0.5、1、3 四个点。从左到右的顺序是：",
            "expected_answer": "−2、−0.5、1、3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用数轴比较大小",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["数轴越往右数越大", "负数都在 0 左边，且 −2 < −0.5（−0.5 更靠近 0）", "排序：−2、−0.5、1、3"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用数轴比较大小（含负小数排序）", "难度理由": "medium——混合负数/负小数/正数排序，需先标点再读序", "认知阶梯定位": "L3 变式（从'标单个点'升级为'多点排序'）", "错因陷阱": "把 −0.5 放 −2 左边（小数大小误判）、把负小数当正数处理", "教学角色": "用数轴比较大小的核心变式"},
        },
        {
            "slot": "B3-I0",
            "prompt": "小明把数轴的正方向画成向左。按他的画法，原点左边第 2 格表示的数是多少？",
            "expected_answer": "2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["正方向向左 → 原点左边是正方向", "从原点往左第 2 格 → 表示 +2", "答案不是 −2（那是正方向向右的画法）"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "正方向决定正负归属（方向是约定而非固定'右正'，'在数轴上表示数'）", "难度理由": "medium——必须先换参照再读数，反直觉", "认知阶梯定位": "L3 变式（换约定条件）", "错因陷阱": "固定思维'左边必为负'（正负方向反错因的深层形态，答 −2 即中招，节点 #2 错因）", "教学角色": "方向约定可变性的辨析题"},
        },
        {
            "slot": "B3-I1",
            "prompt": "数轴上，点 A 表示 −3，点 B 表示 5。A、B 两点正中间的点 C 表示什么数？",
            "expected_answer": "1",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "数轴距离与中点",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["A 到 0 是 3 个单位，0 到 B 是 5 个单位 → A、B 相距 3 + 5 = 8 个单位", "中点把距离平分：一半是 4 个单位", "从 A 往右走 4 个单位：−3 + 4 = 1（或从 B 往左走 4 个单位：5 − 4 = 1）", "C 表示 1"],
            "error_tags": ["visual_spatial", "modeling_or_reading"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "数轴两点距离 + 中点策略（跨 0 计数，'数轴距离与中点'）", "难度理由": "hard 名副其实——跨 0 距离要分两段相加（3+5=8），再求一半并回推位置，多步且需策略，无模板可套", "认知阶梯定位": "L4 迁移——'到 0 的距离'语义正是解锁节点绝对值的核心（预告），中分策略是纯数轴推理", "错因陷阱": "只数 5−3=2（忘跨 0）、中点直接取中间数 1 却说不出理由、从 A 往右走错方向", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "在数轴上标出 −1.5、3/4、−0.25、2。下列说法正确的是（　）\nA. −1.5 在 −0.25 的右边\nB. 3/4 在 1 的右边\nC. −0.25 在 0 的左边\nD. 3/4 在 −0.25 的左边",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用数轴比较大小",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["3/4 = 0.75，先把分数统一成小数", "排序：−1.5 < −0.25 < 0.75 < 2", "A 错：−1.5 < −0.25，−1.5 应在左边；B 错：0.75 < 1，应在 1 左边；D 错：0.75 > −0.25，应在右边", "C 对：−0.25 是负数，在 0 左边"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "用数轴比较大小（分数小数混合、负数排序）", "难度理由": "hard——四个数（含分数/负小数）+ 四条语句逐一核验，任一环节错（互化错、负小数排序错）即中招", "认知阶梯定位": "L4 迁移——分数小数互化（小学前置）+ 负数大小（POS-NEG 前置）+ 数轴排序三知识混合", "错因陷阱": "3/4 误作 0.34、把 −1.5 放 −0.25 右边（绝对值大却数小）、互化错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "数轴上，原点左边 2 个单位长度处的点表示的数是多少？（　）\nA. 2\nB. −2\nC. 0\nD. −1",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["原点左边是负方向", "2 个单位长度 → 表示 −2", "选 B"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "根据位置写数（负方向，'在数轴上表示数'）", "难度理由": "easy 检测——单步，但方向反陷阱有区分度", "认知阶梯定位": "L2 检测（根据点写数，diagnostic probe 素材）", "错因陷阱": "正负方向反（选 A，节点 #2 错因）", "教学角色": "检测易档——掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "数轴上，0 到 1 之间平均分成 8 小格。从 1 往左数第 3 小格处的点表示什么数？（　）\nA. 3/8\nB. 5/8\nC. 1/8\nD. 7/8",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["每小格表示 1/8", "从 1 往左数第 3 小格 = 1 − 3/8 = 8/8 − 3/8 = 5/8", "选 B"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "细分单位下反向读数（分数位置，'在数轴上表示数'）", "难度理由": "hard——计数方向反转（从 1 往左）+ 分数减法两步，三处可错（方向错选 3/8、漏 1 的单位、分母错）", "认知阶梯定位": "L3 检测 hard——诊断'分数小数位置不准'的深层形态", "错因陷阱": "从 1 往左数第 3 小格直接写 3/8（方向错，选项 A）、不会把 1 换成 8/8 做减法", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "在数轴上，−1/2 在 −1 的哪一边？−1/2 和 −1 哪个更大？",
            "expected_answer": "−1/2 在 −1 的右边，−1/2 更大",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用数轴比较大小",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−1/2 = −0.5，在 −1 和 0 之间", "数轴越往右越大 → −1/2 在 −1 右边，且更大", "结论：−1/2 > −1"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负数分数的大小比较（数轴定位，'用数轴比较大小'）", "难度理由": "medium 复测——需先放对分数位置再比大小，防'会背不会用'（背了'负数绝对值越大越小'但不往数轴上放）", "认知阶梯定位": "L3 复测", "错因陷阱": "认为 −1/2 比 −1 小（绝对值错觉 1/2 < 1）、只比分子误判", "教学角色": "防'会背不会用'复测——必须经数轴位置判断"},
        },
        {
            "slot": "B5-I0",
            "prompt": "数轴上有三点：A 表示 −4，B 表示 1，C 表示 5。小明说：'B 到 A 的距离是 3 个单位，B 到 C 的距离是 4 个单位。'小明说得对吗？",
            "expected_answer": "不对：B 到 A 的距离是 5 个单位（从 −4 到 1 要跨过 0，共 4+1=5），B 到 C 才是 4 个单位",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "数轴距离与中点",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["B 到 A：A 在 −4，B 在 1，距离 = 4 + 1 = 5 个单位（从 −4 到 0 是 4 个，0 到 1 是 1 个）", "B 到 C：1 到 5 是 4 个单位", "小明把 B 到 A 算成 3 是错的（用 4−1 直接减，忘跨 0）"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "跨 0 的两点距离（负边界，'数轴距离与中点'）", "难度理由": "hard——两段距离都要算，且藏在'小明说法对不对'的判断里，必须先自己算出正确值再核对", "认知阶梯定位": "L4 复测——距离语义（绝对值预告）+ 多步核验，防'会背不会用'", "错因陷阱": "跨 0 距离直接用大数减小数（4−1=3，忘掉从 −4 到 0 的一段），正中'正负方向反/位置不准'错因深层", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "判断：'在数轴上，表示 −1 的点比表示 −3 的点离原点更近。'这个说法对吗？",
            "expected_answer": "对（−1 到原点 1 个单位，−3 到原点 3 个单位）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−1 在原点左边 1 个单位处", "−3 在原点左边 3 个单位处", "1 < 3，所以 −1 离原点更近，说法对"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "位置-距离关系（负数位置判断，'在数轴上表示数'）", "难度理由": "easy 诊断——单步距离比较，但需理解'离原点近'= 位置更靠近 0", "认知阶梯定位": "L1 诊断（位置感基线，diagnostic probe'标 5 个数'变体）", "错因陷阱": "以为 −3 离原点近（绝对值大即离得远的错觉）", "教学角色": "诊断易档——区分 A/B/C 档的位置感基线"},
        },
        {
            "slot": "B5-I2",
            "prompt": "数轴上，−1 到 0 之间平均分成 4 小格。点 P 在 −1 往右数第 1 小格处，点 P 表示的数是多少？",
            "expected_answer": "−3/4",
            "answer_format": "fraction",
            "verification_intent": "unverifiable",
            "question_type": "在数轴上表示数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["每小格表示 1/4", "从 −1 往右数第 1 小格：−1 + 1/4 = −3/4", "点 P 表示 −3/4"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负分数位置读数（−1 与 0 之间的细分，'在数轴上表示数'）", "难度理由": "medium 诊断——负向细分+分数加法两步，且答案 −3/4 有强迷惑性（易答 −1/4）", "认知阶梯定位": "L2 诊断（diagnostic probe'根据点写数'素材）", "错因陷阱": "从 −1 往右第 1 格直接写 −1/4（把 −1 当 0）、负分数位置不准", "教学角色": "诊断题——直接区分'会不会在负区间标分数'（节点 #3 错因探针）"},
        },
    ],
    # ===== M-G7-OPPOSITE 相反数（概念向：13 unverifiable + 2 verified 化简链；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="到0距离相等、方向相反的两个数"；seed=求相反数/化简多重负号/数轴对称；
    # common_mistakes=负数的相反数仍写负/-(-a)化简错/0的相反数不清楚；diagnostic_probes=求5个数相反数含0和多重负号。
    # authoring 原则（琢玉教训）：化简链用"计算："前缀走 sympy verified（答案必须真算对）；
    # 概念题经概念判断（识别/判断/辨析），不拿算术冒充；hard 真难（距离反推双解、0 例外、字母属性）。
    "M-G7-OPPOSITE": [
        {
            "slot": "B1-I0",
            "prompt": "在数轴上，−5 在原点左边 5 个单位长度处。和 −5 到原点距离相等、方向相反的点表示什么数？这个数就是 −5 的相反数，它是多少？",
            "expected_answer": "5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["相反数 = 到原点距离相等、方向相反", "−5 到原点距离 5 → 相反数也在距原点 5 处", "方向相反 → 在原点右边 → 是 5"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用'距离相等、方向相反'求相反数（数轴对称语义，'求相反数'）", "难度理由": "medium 锚点——两步（距离+方向），演示本质而非背'变号'口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——相反数不是'变号'而是'关于原点对称'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下列各组数中，互为相反数的是（　）\nA. 3 和 −3\nB. 3 和 1/3\nC. −3 和 −3\nD. 3 和 0",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["相反数：符号相反、绝对值相同的两个数", "A：3 和 −3 符号相反且都是 3 → 互为相反数", "B 是倒数陷阱（3 和 1/3），C 是同一个数，D 中 0 不是 3 的相反数", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别互为相反数的数对（符号相反、距离相等，'求相反数'）", "难度理由": "easy——概念识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断属性而非求值）", "错因陷阱": "把倒数（3 与 1/3）当相反数、把同数当相反数", "教学角色": "概念识别脚手架，本节点最佳 L1"},
        },
        {
            "slot": "B1-I2",
            "prompt": "0 的相反数是什么？（　）\nA. 0\nB. 没有相反数\nC. −0\nD. 无法确定",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0 到原点的距离是 0，方向也无所谓 → 0 的相反数是 0", "−0 就是 0，B 的说法错误", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "0 的相反数是 0（特殊点，'求相反数'）", "难度理由": "easy——但正是节点 #3 错因'0 的相反数不清楚'的直击", "认知阶梯定位": "L1 识别（属性判断）", "错因陷阱": "以为 0 没有相反数（选 B）、以为有 −0 这个'别的数'（选 C）", "教学角色": "零的特殊性识别题"},
        },
        {
            "slot": "B2-I0",
            "prompt": "0.5 的相反数是多少？请写出来。",
            "expected_answer": "−0.5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["相反数符号相反、数值相同", "0.5 的相反数是 −0.5"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "求小数的相反数（'求相反数'）", "难度理由": "easy 套用——直接运用定义", "认知阶梯定位": "L2 套用", "错因陷阱": "负号位置写错、把相反数当倒数", "教学角色": "小数相反数标准套用"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：−(−5) 的结果",
            "expected_answer": "5",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "化简多重负号",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−(−5) 表示 −5 的相反数", "−5 的相反数是 5", "所以 −(−5) = 5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "化简双重负号（−(−a) = a，'化简多重负号'）", "难度理由": "medium 锚点——核心子技能'化简多重负号'的标准形态，需懂'− 表示取相反数'而非'去负号'", "认知阶梯定位": "L2 套用（化简锚点）", "错因陷阱": "−(−5) 仍写 −5（'负数的相反数仍写负'节点 #1 错因）", "教学角色": "化简多重负号的标准示范（可机算 verified，答案经 sympy 验算）"},
        },
        {
            "slot": "B2-I2",
            "prompt": "化简 −(−a) 的结果是（　）\nA. −a\nB. a\nC. 0\nD. 无法确定",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "化简多重负号",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−(−a) 表示 a 的相反数的相反数", "取两次相反数回到本身 → 结果 a", "对任意数（包括负数）都成立", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含字母的双重负号化简（−(−a) = a 对任意 a 成立，'化简多重负号'）", "难度理由": "medium——从具体数升级到字母，需跳出'去负号'表面", "认知阶梯定位": "L3 变式（换字母形式）", "错因陷阱": "−(−a) 化简错（节点 #2 错因）、把 a 当正数而选 −a", "教学角色": "字母化变式——为含字母绝对值做准备"},
        },
        {
            "slot": "B3-I0",
            "prompt": "判断：'−0 和 0 互为相反数。'这个说法（　）\nA. 正确\nB. 错误，0 没有相反数\nC. 错误，−0 不是数\nD. 错误，只有正数才有相反数",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−0 = 0，0 的相反数是 0", "0 和 0 互为相反数（0 是唯一'自己和自己互为相反数'的数）", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "0 与 −0 的关系及 0 的相反数（'求相反数'）", "难度理由": "medium——反直觉（0 自己和自己互为相反数），需处理 −0 = 0 的符号特例", "认知阶梯定位": "L3 变式（符号特例辨析）", "错因陷阱": "以为 0 没有相反数（节点 #3 错因）、把 −0 当成另一个数", "教学角色": "零的特殊性变式（与 B1-I2 互补：一处问'是多少'，一处问'是否互为相反数'）"},
        },
        {
            "slot": "B3-I1",
            "prompt": "在数轴上，点 A 表示 a，点 B 表示 a 的相反数 −a。A、B 两点相距 8 个单位长度。a 是多少？",
            "expected_answer": "4 或 −4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "数轴对称",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["相反数关于原点对称 → A、B 分居原点两侧且到原点距离相等", "两点距离 = 2 × 到原点距离 = 8 → 到原点距离 = 4", "a 可以是原点右边 4（a = 4），也可以是原点左边 4（a = −4）", "答案：4 或 −4"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "数轴对称 + 距离反推（a 与 −a 的关系，'数轴对称'）", "难度理由": "hard 名副其实——需把'相距 8'翻译成'距离 = 8÷2 = 4'，还要想到 a 可能在两边（双解），多步+策略+漏解陷阱", "认知阶梯定位": "L4 迁移——数轴距离（数轴前置）+ 相反数对称 + 绝对值'到原点距离'语义（解锁预告）", "错因陷阱": "只写 4 漏 −4、把相距 8 直接当 a、以为 a 一定是正数", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "若 a 与 b 互为相反数，下列说法正确的是（　）\nA. a 和 b 在数轴上一定关于原点对称\nB. a 一定是正数，b 一定是负数\nC. a 和 b 不可能相等\nD. −a 一定是负数",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "数轴对称",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["相反数的本质：到原点距离相等、方向相反 → 关于原点对称，A 对", "B 错：0 与 0 互为相反数，不一定是正负各一", "C 错：0 的相反数是 0，a 和 b 可以相等（都等于 0）", "D 错：若 a 是负数，−a 就是正数"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "字母相反数的属性判断（含 0 例外与 −a 符号陷阱，'数轴对称'）", "难度理由": "hard——四条语句都要用'0 是例外'和'字母可正可负'逐一排除，任何一条漏判即错", "认知阶梯定位": "L4 迁移——数轴对称（数轴前置）+ 字母推理（含字母绝对值的前置）", "错因陷阱": "漏掉 0 的特例（B/C 错选）、固定思维 −a 必为负（D 错选）、'负数的相反数仍写负'变体", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "−8 的相反数是多少？（　）\nA. 8\nB. −8\nC. 1/8\nD. 0",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["相反数符号相反", "−8 的相反数是 8", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "求负数的相反数（'求相反数'）", "难度理由": "easy 检测——单步，但正是节点 #1 错因'负数的相反数仍写负'的直接检测", "认知阶梯定位": "L2 检测", "错因陷阱": "选 B（仍写负）、选 C（倒数混淆）", "教学角色": "检测易档——头号错因的快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：−(−(−0)) 的结果",
            "expected_answer": "0",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "化简多重负号",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["数负号个数：3 个负号（奇数）", "但 0 的相反数还是 0，符号对 0 无影响", "−(−(−0)) = 0（−0 就等于 0，不能按'奇数个负号得负'答 −0 之外的值）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "含 0 的多重负号化简（0 无视符号奇偶，'化简多重负号'×'求相反数'交叉）", "难度理由": "hard——'数负号个数'策略在 0 上失效，需识别 0 的特殊性，陷阱密度高", "认知阶梯定位": "L3 检测 hard——检测'0 的相反数'与'多重负号'的交叉掌握", "错因陷阱": "按奇数个负号答 1/−1、以为 −0 是负数、忘 0 的相反数是 0（节点 #3 错因）", "教学角色": "检测 hard 档，判定层 hard 证据来源（sympy 验算 verified）"},
        },
        {
            "slot": "B4-I2",
            "prompt": "已知 a 的相反数是 −5，那么 a 是多少？",
            "expected_answer": "5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'a 的相反数是 −5' → a 与 −5 互为相反数", "−5 的相反数是 5", "a = 5"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "反向求原数（已知相反数求本身，'求相反数'）", "难度理由": "medium 复测——方向反转，防'会背不会用'（背了'求相反数=变号'但读不懂反向句）", "认知阶梯定位": "L3 复测", "错因陷阱": "把'a 的相反数是 −5'读成'a = −5'（关系方向读反）", "教学角色": "防'会背不会用'复测——关系句方向辨析"},
        },
        {
            "slot": "B5-I0",
            "prompt": "有一个数，它的相反数比它本身大 6。这个数是多少？",
            "expected_answer": "−3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "数轴对称",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["相反数关于原点对称，且这个数在原点哪边，相反数就在另一边", "'相反数比它本身大' → 相反数在右边、这个数在左边（负数）", "大 6 = 两个数相距 6 = 到原点距离的 2 倍 → 距离 3", "这个数在原点左边 3 → 是 −3"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "对称关系的逆向推理（数轴-距离联动，'数轴对称'）", "难度理由": "hard——需把'大 6'翻译成'相距 6 = 2×距离'再定符号，四步推理，无模板可套", "认知阶梯定位": "L4 复测——数轴对称 + 距离联动，防'会背不会用'（背了定义不会反用）", "错因陷阱": "不会把'大 6'转成距离（答 6 或 −6）、方向定错（答 3）", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "−3、0、2 的相反数分别是什么？",
            "expected_answer": "3、0、−2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−3 的相反数是 3", "0 的相反数是 0", "2 的相反数是 −2"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "批量求相反数（含 0，'求相反数'）", "难度理由": "easy 诊断——三数直求，但含 0 暴露'0 的相反数不清楚'错因", "认知阶梯定位": "L1 诊断（diagnostic probe'求 5 个数相反数，含 0'素材）", "错因陷阱": "0 的相反数写错（节点 #3 错因）", "教学角色": "诊断题——三数批次快速分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "求下列各数的相反数：−4、0.75、−(−2)。",
            "expected_answer": "4、−0.75、−2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求相反数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−4 的相反数是 4", "0.75 的相反数是 −0.75", "−(−2) = 2，2 的相反数是 −2"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "混合求相反数（整数/小数/先化简再求，'求相反数'×'化简多重负号'）", "难度理由": "medium 诊断——第三项需先化简多重负号再取相反数，两步", "认知阶梯定位": "L2 诊断（diagnostic probe 素材：含多重负号）", "错因陷阱": "第三项忘先化简直接写 2、小数负号写丢、多重负号化简错（节点 #2 错因）", "教学角色": "诊断题——覆盖'求相反数 + 多重负号'复合档"},
        },
    ],
    # ===== M-G7-ABSOLUTE 绝对值（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="一个数到0的距离，距离永远不为负"；seed=求绝对值/绝对值方程雏形/用绝对值比较；
    # common_mistakes=认为绝对值就是去负号/|0|不清楚/含字母绝对值乱去；
    # diagnostic_probes=求6个绝对值含正负分数和0/解释绝对值含义。
    # authoring 原则（琢玉教训）：全部经概念判断（距离语义/属性判断/辨析），无算术冒充；
    # hard 真难（双解筛选、0 例外、'绝对值大≠数大'辨析）；'解释含义'类题对齐 mastery'能说出距离含义'。
    "M-G7-ABSOLUTE": [
        {
            "slot": "B1-I0",
            "prompt": "在数轴上，−5 到原点 0 的距离是 5 个单位长度，所以 |−5| = 5。那么 |3| 等于多少？它表示什么？",
            "expected_answer": "|3| = 3，表示 3 到原点 0 的距离是 3 个单位长度",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["绝对值 = 一个数到原点 0 的距离", "3 到原点 0 的距离是 3 个单位长度", "所以 |3| = 3"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用'到 0 的距离'求绝对值（距离语义，'求绝对值'）", "难度理由": "medium 锚点——值+含义双输出，演示本质而非'去负号'口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'先距离，再符号'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "绝对值表示一个数到什么的距离？（　）\nA. 1\nB. 原点 0\nC. 它本身\nD. 数轴上离它最近的整数",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["绝对值是数到原点 0 的距离", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别绝对值的定义（到原点距离，'求绝对值'）", "难度理由": "easy——定义识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则）", "错因陷阱": "把'到它本身'（选 C）当距离（'去负号'迷思的来源）", "教学角色": "定义识别脚手架，本节点最佳 L1"},
        },
        {
            "slot": "B1-I2",
            "prompt": "|0| 等于多少？（　）\nA. 0\nB. 没有意义\nC. 无法确定\nD. 1",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0 到原点 0 的距离是 0", "|0| = 0", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "|0| = 0（距离为 0，'求绝对值'）", "难度理由": "easy——但直击节点 #2 错因'|0| 不清楚'", "认知阶梯定位": "L1 识别（属性判断）", "错因陷阱": "以为 |0| 无意义（选 B）、以为绝对值最小是 1（选 D）", "教学角色": "零的绝对值识别题"},
        },
        {
            "slot": "B2-I0",
            "prompt": "|−3.5| 等于多少？请写出来。",
            "expected_answer": "3.5",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−3.5 到原点 0 的距离是 3.5 个单位长度", "|−3.5| = 3.5"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "求负小数的绝对值（'求绝对值'）", "难度理由": "easy 套用——直接运用定义", "认知阶梯定位": "L2 套用", "错因陷阱": "把 |−3.5| 写成 −3.5（'绝对值就是去负号'错因变体）", "教学角色": "小数绝对值标准套用"},
        },
        {
            "slot": "B2-I1",
            "prompt": "|−2/3| 和 |2/3| 分别是多少？",
            "expected_answer": "2/3 和 2/3",
            "answer_format": "fraction",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−2/3 到原点距离是 2/3 → |−2/3| = 2/3", "2/3 到原点距离是 2/3 → |2/3| = 2/3", "互为相反数的两个数绝对值相等"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求分数绝对值 + 相反数绝对值相等（'求绝对值'×'相反数'前置）", "难度理由": "medium——两个分数值都要求，且隐含'相反数绝对值相等'的对称规律", "认知阶梯定位": "L2 套用（分数绝对值 + 对称观察）", "错因陷阱": "负分数去负号后符号残留（写 −2/3）、两个数只求一个", "教学角色": "分数绝对值套用 + 对称规律铺垫"},
        },
        {
            "slot": "B2-I2",
            "prompt": "|−8| 和 |−3| 哪个大？",
            "expected_answer": "|−8| 大（8 > 3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用绝对值比较",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["|−8| = 8，|−3| = 3", "8 > 3", "所以 |−8| 大"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用绝对值比较（先求值再比，'用绝对值比较'）", "难度理由": "medium——两步（求值+比较），且为'负数本身大小'的比较埋对照", "认知阶梯定位": "L3 变式（用绝对值比较种子题型）", "错因陷阱": "直接比 −8 与 −3 的大小（−8 < −3）与绝对值大小（8 > 3）混淆", "教学角色": "用绝对值比较的标准变式（与 B3-I2 的辨析互补）"},
        },
        {
            "slot": "B3-I0",
            "prompt": "一个数的绝对值可以是负数吗？（　）\nA. 可以，比如 |−5| = −5\nB. 不可以，绝对值是距离，距离永远不为负\nC. 可以，只要这个数是负数\nD. 不确定",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["绝对值 = 到原点的距离", "距离不可能是负数", "|−5| = 5（不是 −5），所以绝对值不能是负数", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "绝对值非负（距离语义，'求绝对值'）", "难度理由": "medium——概念判断题，需用'距离不为负'反驳'去负号'直觉", "认知阶梯定位": "L3 变式（属性判断）", "错因陷阱": "认为 |−5| = −5（'绝对值就是去负号'错因直接暴露，节点 #1 错因）", "教学角色": "核心概念判断题——非负性的正名"},
        },
        {
            "slot": "B3-I1",
            "prompt": "|x| = 4，且 x 是负数，x 是多少？",
            "expected_answer": "−4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "绝对值方程雏形",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["|x| = 4 → x 到原点距离是 4", "距离 4 的点有两个：4 和 −4", "再加条件 x 是负数 → x = −4"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "绝对值方程雏形（|x| = a 双解 + 条件筛选，'绝对值方程雏形'）", "难度理由": "hard——先解出 ±4 双解，再用附加条件筛选，两步且漏解/漏筛都错", "认知阶梯定位": "L4 迁移——绝对值（距离语义）+ 相反数（±4 互为相反数，前置）混合", "错因陷阱": "只写 4（忘双解）、忘记用'负数'条件筛选（写 4 或 −4）", "教学角色": "判定层 transfer 证据来源（方程雏形 × 相反数）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "比较 −5 和 −3 时，小明说：'|−5| > |−3|，所以 −5 > −3。'这个说法对吗？",
            "expected_answer": "不对：|−5| > |−3| 只说明 −5 离原点更远；负数离原点越远反而越小，所以 −5 < −3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用绝对值比较",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["|−5| = 5 > 3 = |−3| → −5 离原点更远", "绝对值比的是'到原点的距离'，不是数本身的大小", "负数：离原点越远越小 → −5 < −3", "小明的推理错在把绝对值大小当成数的大小"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "绝对值大小与负数大小关系的辨析（'用绝对值比较'）", "难度理由": "hard——必须分清'距离'与'数的大小'两种比较，且要反向推理（绝对值大 ≠ 数大），单题双重概念", "认知阶梯定位": "L4 迁移——绝对值（本节点）× 负数大小比较（解锁节点 COMPARE 的提前辨析，题干自足不超纲）", "错因陷阱": "顺着小明'绝对值大所以数大'的直觉走（正数成立、负数不成立）、混淆 |−5| 与 −5", "教学角色": "判定层 transfer 证据来源"},
        },
        {
            "slot": "B4-I0",
            "prompt": "|−5| = （　）\nA. −5\nB. 5\nC. 0\nD. 无法确定",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−5 到原点距离是 5", "|−5| = 5", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "求负整数绝对值（检测档，'求绝对值'）", "难度理由": "easy 检测——单步，但选项 A 正是'去负号'错因的正面陷阱", "认知阶梯定位": "L2 检测", "错因陷阱": "选 A（|−5| = −5，节点 #1 错因）", "教学角色": "检测易档——头号错因快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "a 的绝对值是 3，b 的绝对值也是 3。a 和 b 一定相等吗？",
            "expected_answer": "不一定：a、b 可能是 3 和 −3（或反过来），也可能相等",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "绝对值方程雏形",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["|a| = 3 → a = 3 或 −3", "|b| = 3 → b = 3 或 −3", "a 和 b 可以取不同值（3 与 −3）→ 不一定相等", "只有都取同一个值时相等"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "绝对值相等 ≠ 数相等（方程雏形检测，'绝对值方程雏形'）", "难度理由": "hard——需枚举双解组合再判断，'绝对值相等推不出相等'是强反直觉点", "认知阶梯定位": "L3 检测 hard——检测'距离语义'是否真正内化（含字母，直击节点 #3 错因'含字母绝对值乱去'）", "错因陷阱": "以为 |a| = |b| 推出 a = b（把距离当数）、漏掉 ± 双解", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "小明说：'绝对值就是把负号去掉，所以 |−5| = 5。'这种说法对吗？为什么？",
            "expected_answer": "不对（或说不完整）：绝对值是数到原点的距离；'去负号'对 |−5| 碰巧结果对，但 |0| = 0、|5| = 5 都不是'去负号'能解释的",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["绝对值 = 到原点 0 的距离，不是'去负号'", "|−5| = 5 是因为 −5 到原点距离是 5", "反例：|5| = 5 没有负号可去；|0| = 0 也不是'去负号'", "所以小明的说法不对/不完整"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "戳破'绝对值就是去负号'的错误归纳（本质是距离，'求绝对值'）", "难度理由": "medium 复测——需给出反例论证，防'会背不会用'（背了'去负号'捷径）", "认知阶梯定位": "L3 复测", "错因陷阱": "认同'去负号'说法（节点 #1 错因的归纳形态）、说不出 |0| 或 |5| 的反例", "教学角色": "防'会背不会用'复测——本质归因题"},
        },
        {
            "slot": "B5-I0",
            "prompt": "下列说法正确的是（　）\nA. 绝对值越大的数一定越大\nB. 绝对值等于它本身的数一定是正数\nC. |a| = a 时，a ≥ 0\nD. 绝对值等于它的相反数的数一定是负数",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用绝对值比较",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A 错：−5 和 −3，|−5| 大但 −5 小", "B 错：0 的绝对值等于它本身，0 不是正数", "C 对：|a| = a 等价于 a ≥ 0（非负）", "D 错：0 的绝对值等于它的相反数（0 的相反数是 0），0 不是负数"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "含字母绝对值的属性判断（|a| = a ⇔ a ≥ 0，'用绝对值比较'×'求绝对值'）", "难度理由": "hard——四条语句都要处理 0 例外与字母符号，|a| = a 与 |a| = −a 的边界（≥0 vs <0）极易混，多陷阱", "认知阶梯定位": "L4 复测——含字母绝对值（节点 #3 错因）+ 非负性 + 相反数（前置）综合，防'会背不会用'", "错因陷阱": "漏 0 例外（B/D 错选）、把 |a| = a 当成 a > 0 丢掉等号、'绝对值越大的数越大'的负数反例", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "求下列各数的绝对值：−3、0、4。",
            "expected_answer": "3、0、4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−3 到原点距离 3 → |−3| = 3", "0 到原点距离 0 → |0| = 0", "4 到原点距离 4 → |4| = 4"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "批量求绝对值（含 0，'求绝对值'）", "难度理由": "easy 诊断——三数直求，含 0 暴露'|0| 不清楚'错因", "认知阶梯定位": "L1 诊断（diagnostic probe'求 6 个绝对值，含正负分数和 0'素材）", "错因陷阱": "|0| 写成 1 或无意义（节点 #2 错因）、|−3| 写成 −3", "教学角色": "诊断题——三数批次快速分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "|−5/6| 等于多少？用'到原点的距离'这句话解释一下它表示什么。",
            "expected_answer": "5/6；表示 −5/6 到原点 0 的距离是 5/6 个单位长度",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求绝对值",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−5/6 到原点 0 的距离是 5/6 个单位长度", "|−5/6| = 5/6", "含义：−5/6 到原点的距离是 5/6 个单位长度"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "求负分数绝对值 + 解释含义（'求绝对值'）", "难度理由": "medium 诊断——值+含义双输出，需说出'距离'语义（diagnostic probe'解释绝对值含义'素材）", "认知阶梯定位": "L2 诊断——直接区分'会算'与'懂含义'两档", "错因陷阱": "只会写 5/6 说不清含义（'会背不会用'）、负分数去负号后写 −5/6", "教学角色": "诊断题——mastery 判据'能说出距离含义'的取证题"},
        },
    ],
    # ===== M-G7-COMPARE 有理数大小比较（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="数轴上右边的数大；两个负数绝对值大的反而小"；
    # seed=正负数比较/负数比较/分数小数混合比较；
    # common_mistakes=负数比较按绝对值直接比/分数小数不互化/数轴方向错；
    # diagnostic_probes=8个数排序，含负分数/小数。
    # authoring 原则（琢玉教训）：全部经概念判断（比较/判断/排序/纠错），无算术冒充；
    # hard 真难（双解筛选、符号主导辨析、8 数排序）；'负数绝对值大的反而小'规则用判断/解释题取证
    # （mastery'能解释负数比较规则'）；排序句式 ≤2。
    "M-G7-COMPARE": [
        {
            "slot": "B1-I0",
            "prompt": "在数轴上，−3 在原点左边 3 个单位长度处，−1 在原点左边 1 个单位长度处。−3 和 −1 哪个大？说说你的理由。",
            "expected_answer": "−1 大。数轴上右边的数大，−1 在 −3 的右边（−1 离原点更近）；也可以说两个负数比较，绝对值小的反而大",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−3 在原点左边 3 个单位，−1 在原点左边 1 个单位 → −1 在 −3 的右边", "数轴上右边的数大 → −1 大", "另一种说法：|−1| = 1 ＜ 3 = |−3|，负数绝对值小的反而大 → −1 大"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用数轴位置比较两个负数（数轴规则 + 负数规则双出口，'负数比较'）", "难度理由": "medium 锚点——值+理由双输出，演示本质而非背口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'数轴上右边的数大；两个负数绝对值大的反而小'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "比较两个负数的大小时，正确的做法是（　）\nA. 谁的绝对值大，谁就大\nB. 谁的绝对值大，谁反而小\nC. 谁的绝对值小，谁就小\nD. 只看正负号，不看绝对值",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["两个负数比较：绝对值大的反而小", "选项 A 是错误做法（节点 #1 错因'负数比较按绝对值直接比'）", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'负数比较'的正确规则（绝对值大的反而小，'负数比较'）", "难度理由": "easy——规则识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则而非直接比较）", "错因陷阱": "选 A（'绝对值大的大'正是节点头号错因'负数比较按绝对值直接比'）", "教学角色": "L1 识别脚手架——头号错因的规则层探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "比较两个负数 −8 和 −3 时，下列说法错误的是（　）\nA. −8 的绝对值更大\nB. −8 离原点更远\nC. −8 比 −3 大\nD. −8 比 −3 小",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["|−8| = 8 ＞ 3 = |−3| → A 对（绝对值更大）", "绝对值大 → 离原点更远 → B 对", "两个负数绝对值大的反而小 → −8 ＜ −3 → D 对、C 错", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "在'绝对值'与'大小'两组说法中找出错误说法（'负数比较'）", "难度理由": "easy——但每个选项都要用负数比较规则过一遍", "认知阶梯定位": "L1 识别（找错 = 识别错因）", "错因陷阱": "把'绝对值大'等同于'数大'（C 项即节点头号错因'负数比较按绝对值直接比'的正面陷阱）", "教学角色": "找错型 L1——与 B1-I1 互补（一处问正确做法、一处找错误说法）"},
        },
        {
            "slot": "B2-I0",
            "prompt": "比较大小：−7 ○ −3（填'＞'或'＜'）。",
            "expected_answer": "−7 ＜ −3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["两个负数，绝对值大的反而小", "|−7| = 7 ＞ 3 = |−3| → −7 更小", "−7 ＜ −3"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "直接比较两个负整数（'负数比较'）", "难度理由": "easy 套用——单步规则运用", "认知阶梯定位": "L2 套用", "错因陷阱": "按绝对值直接比写成 −7 ＞ −3（节点 #1 错因）", "教学角色": "L2 套用脚手架"},
        },
        {
            "slot": "B2-I1",
            "prompt": "比较 −5/6 和 −3/4 的大小（填'＞'或'＜'）。",
            "expected_answer": "−5/6 ＜ −3/4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数小数混合比较",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先通分：−5/6 = −10/12，−3/4 = −9/12", "−10/12 ＜ −9/12（同分母比分子，分子小的分数小）", "所以 −5/6 ＜ −3/4（绝对值大的负数反而小）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "负分数比较（通分 + 负数规则，'分数小数混合比较'）", "难度理由": "medium——需先通分再套负数规则，两步", "认知阶梯定位": "L2 套用（分数比较的负数版本）", "错因陷阱": "不通分直接按分子比（5 ＞ 3 误判）、通分后按'绝对值大的大'错判（节点 #1 错因）", "教学角色": "负分数比较标准套用"},
        },
        {
            "slot": "B2-I2",
            "prompt": "把 −3/4、−0.6、−2/3 按从大到小的顺序排列。",
            "expected_answer": "−0.6、−2/3、−3/4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数小数混合比较",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先统一形式：−3/4 = −0.75，−0.6 不变，−2/3 ≈ −0.67", "比较绝对值：0.6 ＜ 0.67 ＜ 0.75", "负数绝对值小的反而大 → −0.6 ＞ −2/3 ＞ −3/4"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数与小数混合的负数排序（互化 + 负数规则，'分数小数混合比较'）", "难度理由": "medium——三数需先化同形式再比绝对值，且顺序是'从大到小'反直觉", "认知阶梯定位": "L3 变式（混合形式 + 多元素排序）", "错因陷阱": "不互化直接比（−3/4 与 −0.6 错序）、按绝对值从大到小排（节点 #1 错因）", "教学角色": "分数小数混合比较的核心变式"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列大小关系正确的是（　）\nA. −1/2 ＞ −0.4\nB. −1/3 ＜ −0.5\nC. −3/4 ＞ −0.7\nD. −5/6 ＞ −0.9",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分数小数混合比较",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["A：−1/2 = −0.5，−0.5 ＜ −0.4 → 错", "B：−1/3 ≈ −0.33，−0.33 ＞ −0.5 → 错", "C：−3/4 = −0.75，−0.75 ＜ −0.7 → 错", "D：−5/6 ≈ −0.83，−0.83 ＞ −0.9 → 对，选 D"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "四项分数小数混合大小关系判断（互化 + 负数规则逐项排除，'分数小数混合比较'）", "难度理由": "medium——四项都要互化并验证，任何一项误判即错", "认知阶梯定位": "L3 变式（判断辨析，四项干扰）", "错因陷阱": "把负分数当正数比（A 若把 −1/2 当 1/2 会误判对）、互化错（−3/4 当 −0.34）、按绝对值直接比（节点 #1 错因）", "教学角色": "L3 变式核心——四项判断综合检验互化与负数规则"},
        },
        {
            "slot": "B3-I1",
            "prompt": "已知 |a| = 4，|b| = 1，且 a ＞ b。满足条件的 a、b 各有哪些可能？",
            "expected_answer": "a = 4，b = 1 或 −1（a = −4 时不满足 a ＞ b）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "正负数比较",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["|a| = 4 → a = 4 或 −4；|b| = 1 → b = 1 或 −1", "组合四种情况：(4,1)、(4,−1)、(−4,1)、(−4,−1)", "用 a ＞ b 筛选：4 ＞ 1 ✓、4 ＞ −1 ✓、−4 ＞ 1 ✗、−4 ＞ −1 ✗", "答案：a = 4，b = 1 或 −1"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "绝对值给出候选数 + 用大小关系筛选（双解枚举，'正负数比较'×'绝对值'）", "难度理由": "hard 名副其实——先解 ±4/±1 双解，再枚举四组用 a ＞ b 筛选，多步且漏解/漏筛都错", "认知阶梯定位": "L4 迁移——绝对值（前置）× 正负数比较混合", "错因陷阱": "只写 a = 4（忘双解）、把 (−4,1) 当满足 a ＞ b（比较符号错，节点 #1 错因变体）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "小明说：'|a| ＜ |b|，说明 a 比 b 更靠近 0，所以 a 比 b 小。'已知 a 是正数、b 是负数，小明说得对吗？为什么？",
            "expected_answer": "不对。a 是正数、b 是负数，正数永远大于负数（a ＞ 0 ＞ b），跟 |a|、|b| 的大小无关；'靠近 0'只能用来比较同号的两个数",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "正负数比较",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["a 是正数 → a ＞ 0；b 是负数 → b ＜ 0", "所以 a ＞ 0 ＞ b，即 a 一定大于 b", "|a| ＜ |b| 只说 a 离原点更近，不能决定异号两数的大小", "小明把'距离'当成了'大小'，说法不对"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "异号比较中'绝对值距离'是干扰项（符号主导，'正负数比较'×'绝对值'）", "难度理由": "hard——'靠近 0'的前半句正确但结论错误，需识破'距离决定大小'只对同号成立的边界", "认知阶梯定位": "L4 迁移——绝对值（前置）× 正负数比较", "错因陷阱": "顺着'靠近 0 所以小'的直觉（把距离当大小）、不会用 a ＞ 0 ＞ b 一锤定音", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "下面哪个数最小？（　）\nA. −2\nB. 0\nC. −5\nD. 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["负数都小于 0 和正数 → 最小数在 A、C 中", "两个负数：|−5| = 5 ＞ 2 = |−2| → −5 更小", "最小的是 −5，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "从混合数中找最小（负数排序，'负数比较'）", "难度理由": "easy 检测——两步（排除正数与 0 + 比两个负数）", "认知阶梯定位": "L2 检测", "错因陷阱": "选 A（忘比 |−5| 与 |−2|）、选 B（把 0 当最小，负数概念残留）", "教学角色": "检测易档——负数排序快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下列判断正确的是（　）\nA. 绝对值大的数一定大\nB. 两个负数，离原点越远的越小\nC. −0.1 比 −0.01 大\nD. 任何数都比它的相反数大",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A 错：−5 和 −3，|−5| 大但 −5 小", "B 对：两个负数离原点越远即绝对值越大，反而越小", "C 错：−0.1 ＜ −0.01（|−0.1| = 0.1 ＞ 0.01 = |−0.01|）", "D 错：−3 的相反数是 3，−3 ＜ 3", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "四项规则判断（负数比较 + 相反数干扰，'负数比较'）", "难度理由": "hard——四条语句都要逐一验证，A/C 是'按绝对值直接比'的两个变体，D 需用相反数反例", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "选 A/C（节点 #1 错因'负数比较按绝对值直接比'）、选 D（忘负数比相反数小）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "a、b 都是负数，且 |a| ＜ |b|。a 和 b 谁大？说明理由。",
            "expected_answer": "a 大。两个负数比较，绝对值小的反而大；|a| ＜ |b| 说明 a 离原点更近",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "负数比较",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两个负数：绝对值小的反而大", "|a| ＜ |b| → a 的绝对值更小", "所以 a 更大（a 离原点更近、在数轴上更靠右）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "由绝对值大小反推负数大小（含字母，'负数比较'×'绝对值'）", "难度理由": "medium 复测——方向反转（给绝对值比大小）+ 需用文字说明规则，防'会背不会用'", "认知阶梯定位": "L3 复测", "错因陷阱": "按'绝对值大就大'答 b 大（节点 #1 错因）、只会算说不清理由（mastery 判据'能解释负数比较规则'取证）", "教学角色": "防'会背不会用'复测——含字母 + 解释要求"},
        },
        {
            "slot": "B5-I0",
            "prompt": "把下列 8 个数按从大到小的顺序排列：−3.5、2、−1/3、0、−2.5、5/4、−4、0.5",
            "expected_answer": "2、5/4、0.5、0、−1/3、−2.5、−3.5、−4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数小数混合比较",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["正数部分：2 ＞ 5/4（1.25）＞ 0.5", "0 介于正数与负数之间", "负数部分比绝对值：|−1/3| ≈ 0.33 ＜ 2.5 ＜ 3.5 ＜ 4，绝对值小的反而大", "从大到小：2、5/4、0.5、0、−1/3、−2.5、−3.5、−4"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "8 个数混合排序（负分数/负小数/正分数，diagnostic probe'8 个数排序，含负分数/小数'素材，'分数小数混合比较'）", "难度理由": "hard 名副其实——8 数含负分数/负小数/正分数，需互化 + 分段（正/0/负）+ 负数规则，多步且需排序策略", "认知阶梯定位": "L4 复测——全技能综合（互化 + 分段排序 + 负数规则），防'会背不会用'", "错因陷阱": "把 −1/3 排到 −2.5 左边（负分数大小误判）、按绝对值从大到小排（节点 #1 错因）、漏数", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "下面每组两个数中，哪个比较大？①−3 和 1　②−5 和 −2",
            "expected_answer": "① 1　② −2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "正负数比较",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["① 正数大于负数 → 1 ＞ −3", "② 两个负数绝对值大的反而小 → |−2| = 2 ＜ 5 = |−5| → −2 ＞ −5"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "正负数比较 + 负数比较两条规则快速诊断（'正负数比较'×'负数比较'）", "难度理由": "easy 诊断——两小题分别对应节点两条核心规则", "认知阶梯定位": "L1 诊断（diagnostic probe 的拆分小步）", "错因陷阱": "② 按绝对值直接比答 −5（节点 #1 错因）", "教学角色": "诊断题——两条规则各一小步快速分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "判断下列大小关系是否正确，把错的改正过来：①−1/2 ＞ −0.4　②−3/5 ＜ −0.6",
            "expected_answer": "① 错，−1/2 ＜ −0.4；② 错，−3/5 ＝ −0.6",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数小数混合比较",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["① −1/2 = −0.5，−0.5 ＜ −0.4 → 原判断错，改正为 −1/2 ＜ −0.4", "② −3/5 = −0.6 → 两者相等，原判断错，改正为 −3/5 ＝ −0.6"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数小数混合比较的纠错诊断（互化 + 相等判断，diagnostic probe 素材，'分数小数混合比较'）", "难度理由": "medium 诊断——两题都要互化，第二题需识别'相等'（= 也是大小关系）", "认知阶梯定位": "L2 诊断——直接区分'会互化不会负数规则'/'会负数规则不会互化'两档", "错因陷阱": "① 不互化按 1/2 与 0.4 比、② 把相等误判为大于（互化错）", "教学角色": "诊断题——'分数小数不互化'错因的定点探针"},
        },
    ],
    # ===== M-G7-RATIONAL-CLASSIFY 有理数分类（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="有理数包括整数和分数，正负只是另一个分类角度"；
    # seed=按整数/分数分类/按正/负/零分类/集合归类；
    # common_mistakes=有限小数不知道是分数/负分数归类漏掉/0分类错；
    # diagnostic_probes=给10个数分类。
    # authoring 原则（琢玉教训）：全部经概念判断（分类/判断/纠错），无算术冒充；
    # hard 真难（分类轴交叉推理、漏数纠错、10 数四类）；0 与有限小数是错因主战场；
    # 集合归类句式 ≤2（'把…填入集合'仅 B2-I0/B5-I0 两题，其余用判断/纠错/问答变式）。
    "M-G7-RATIONAL-CLASSIFY": [
        {
            "slot": "B1-I0",
            "prompt": "把 3、−2、1/2、−3/4 这四个数分成两类，可以按'整数和分数'分，也可以按'正数和负数'分。两种分法分别怎么分？",
            "expected_answer": "按整数/分数分：整数 3、−2；分数 1/2、−3/4。按正/负分：正数 3、1/2；负数 −2、−3/4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["分类标准一：整数（正整数、0、负整数）vs 分数（正分数、负分数）", "3、−2 是整数；1/2、−3/4 是分数", "分类标准二：正数 vs 负数（0 单独一类）", "3、1/2 是正数；−2、−3/4 是负数"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "同一组数按两种标准分类（整数/分数 与 正/负，'按整数/分数分类'×'按正/负/零分类'）", "难度理由": "medium 锚点——双标准输出，演示本质'正负只是另一个分类角度'", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'分类标准不同、结果不同'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下列各数中，属于分数的是（　）\nA. −5\nB. 0\nC. 2/3\nD. 7",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分数是能写成 a/b（b ≠ 0）形式的数，整数不是分数", "−5、0、7 都是整数", "2/3 是分数，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'分数'与'整数'的边界（'按整数/分数分类'）", "难度理由": "easy——单点识别", "认知阶梯定位": "L1 识别正宗实现（判断类别属性）", "错因陷阱": "把 −5 当分数（'带负号就是分数'迷思，是'负分数归类漏掉'的镜像错）、把 7 当分数", "教学角色": "L1 识别脚手架——整数/分数边界第一探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "把数分成'正数和负数'两类时，0 应该放在哪一类？（　）\nA. 正数\nB. 负数\nC. 既不是正数也不是负数\nD. 正数负数都可以",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "按正/负/零分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["正数都大于 0，负数都小于 0", "0 既不大于 0 也不小于 0", "所以 0 既不是正数也不是负数，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "0 在正负分类中的归属（'按正/负/零分类'）", "难度理由": "easy——但正是节点 #3 错因'0 分类错'的正面直击", "认知阶梯定位": "L1 识别（属性判断）", "错因陷阱": "选 A 或 B（把 0 当正数/负数，节点 #3 错因）、选 D（分类标准不唯一时混用）", "教学角色": "0 的归属识别题——核心概念第一关"},
        },
        {
            "slot": "B2-I0",
            "prompt": "把下列各数填入对应的集合：−4、1/2、0、−3/5、8\n整数集合：＿＿＿；分数集合：＿＿＿",
            "expected_answer": "整数集合：−4、0、8；分数集合：1/2、−3/5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["整数：正整数、负整数和 0 → −4、0、8", "分数：能写成 a/b 形式的数 → 1/2、−3/5", "−3/5 是负分数，不要漏掉"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "整数/分数集合归类（含 0 与负分数，'按整数/分数分类'）", "难度理由": "easy 套用——单标准归类，但 0 和 −3/5 是双陷阱", "认知阶梯定位": "L2 套用", "错因陷阱": "把 0 漏出整数集合、把 −3/5 漏出分数集合（节点 #2 错因'负分数归类漏掉'）", "教学角色": "L2 套用脚手架——集合归类入门"},
        },
        {
            "slot": "B2-I1",
            "prompt": "0.25、−3、−2/5、7 中，哪些是整数？哪些是分数？",
            "expected_answer": "整数：−3、7；分数：0.25、−2/5（0.25 是有限小数，可以化成 1/4，属于分数）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["有限小数可以化成分数 → 0.25 = 25/100 = 1/4，属于分数", "−3、7 是整数", "−2/5 是负分数", "分类：整数 −3、7；分数 0.25、−2/5"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "有限小数归属分数（0.25 = 1/4，'按整数/分数分类'）", "难度理由": "medium——小数化分数是隐藏一步，正是节点 #1 错因'有限小数不知道是分数'", "认知阶梯定位": "L2 套用（小数→分数的归属判断）", "错因陷阱": "把 0.25 归整数或'既不是整数也不是分数'（节点 #1 错因）、漏掉 −2/5（节点 #2 错因）", "教学角色": "头号错因'有限小数是分数'的定点套用"},
        },
        {
            "slot": "B2-I2",
            "prompt": "−1.5、0、2/3、−4、5 中，属于'非正数'的有哪些？",
            "expected_answer": "−1.5、0、−4（非正数 = 负数和 0）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按正/负/零分类",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["非正数 = 不是正数的数 = 负数和 0", "负数：−1.5、−4；0 也不是正数", "所以非正数：−1.5、0、−4"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'非正数'集合归类（负数和 0，'按正/负/零分类'）", "难度理由": "medium——'非正数'需反向推理（补集概念），0 归属是隐藏陷阱", "认知阶梯定位": "L3 变式（反向集合概念）", "错因陷阱": "漏掉 0（0 不是正数，节点 #3 错因变体）、把 2/3 误入非正数", "教学角色": "L3 变式——从'正/负/零'到'非正数/非负数'的集合语言升级"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法正确的是（　）\nA. 有限小数不是分数，所以不是有理数\nB. 有理数包括正有理数、负有理数和 0\nC. 0 是正有理数\nD. 分数不包括小数",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "集合归类",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["有限小数可以化成分数，是有理数 → A 错", "有理数 = 整数 ∪ 分数 = 正有理数 ∪ 0 ∪ 负有理数 → B 对", "0 既不是正有理数也不是负有理数 → C 错", "有限小数/循环小数都属于分数 → D 错", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "有理数整体结构判断（正有理数/0/负有理数 + 小数归属，'集合归类'）", "难度理由": "medium——四项都要对'有理数集合'结构有整体认识，A/D 直击节点 #1 错因", "认知阶梯定位": "L3 变式（集合整体判断）", "错因陷阱": "选 A（有限小数不是分数，节点 #1 错因）、选 C（0 是正有理数，节点 #3 错因）", "教学角色": "有理数集合结构的概念题"},
        },
        {
            "slot": "B3-I1",
            "prompt": "下列说法错误的是（　）\nA. 既是分数又是负数的数一定是负分数\nB. 既是整数又是正数的数一定是正整数\nC. 既是整数又是负数的数一定是负整数\nD. 既是分数又是整数的数一定存在",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "集合归类",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["整数与分数是有理数按'是不是整数'分出的两类，互不重叠", "A：分数 ∩ 负数 = 负分数 ✓ 对", "B：整数 ∩ 正数 = 正整数 ✓ 对", "C：整数 ∩ 负数 = 负整数 ✓ 对", "D：整数 ∩ 分数 = 空集，'既是分数又是整数'的数不存在 → D 错，选 D"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "两种分类标准的交叉推理（整数/分数 与 正/负，'集合归类'×'正负数'前置）", "难度理由": "hard 名副其实——需理解分类树两轴的交集（正整数/负分数等四类交叉），D 是'分类互斥'的强反直觉点（2/1 只是'可写成'分数形式，2 本身是整数）", "认知阶梯定位": "L4 迁移——正负数（前置）× 有理数分类", "错因陷阱": "以为存在'既是分数又是整数'的数（把'可写成'当'本身就是'）、把 0 卷入交叉判断", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "在数轴上，点 A 表示的数是 a。下列说法正确的是（　）\nA. 若 a 是正数，则 a 一定是正整数\nB. 若 a 在原点左边，则 a 一定是负整数\nC. 若 a 在原点右边，则 a 一定是正有理数\nD. 若 a 是负分数，则 a 一定在原点右边",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "集合归类",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["A 错：正数可以是正分数（如 1/2）", "B 错：原点左边可以是负分数（如 −1/2）", "C 对：原点右边 = 正数 = 正有理数", "D 错：负分数是负数，在原点左边", "选 C"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "数轴位置与有理数类别互推（'集合归类'×'数轴'）", "难度理由": "hard——四条语句都要在'数轴位置 ↔ 类别'两个方向推理，A/B 是'正数=正整数'的以偏概全陷阱", "认知阶梯定位": "L4 迁移——数轴（相邻节点）× 有理数分类", "错因陷阱": "把'正数'与'正整数'混为一谈（A 错选）、负分数方向记反（D 错选）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "下列各数中，是负分数的是（　）\nA. −7\nB. 0\nC. −3/8\nD. 5.2",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["负分数 = 分数且负数", "−7 是负整数，0 既不是正也不是负，5.2 是正分数（有限小数属分数）", "−3/8 是负分数，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "负分数识别（'按整数/分数分类'×'按正/负/零分类'交叉）", "难度理由": "easy 检测——单点识别，选项 D 是正分数干扰", "认知阶梯定位": "L2 检测", "错因陷阱": "选 A（把负整数当负分数，'负分数归类漏掉'错因的识别形态）、选 D（正小数当负）", "教学角色": "检测易档——负分数快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "小华把 −0.5、3/4、0、−6、2.3、−1/5 分类如下：正有理数：3/4、2.3；负有理数：−0.5、−1/5；整数：0、−6。小华的分法有没有漏数？漏掉了哪个？",
            "expected_answer": "漏掉了 −6：−6 是负整数，也是负有理数，应同时放进'负有理数'（一个数可以同时属于几个集合）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "集合归类",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["核对正有理数：3/4、2.3（2.3 是有限小数属分数）→ 对", "核对整数：0、−6 → 对", "核对负有理数：−0.5（=−1/2）、−1/5 → 少了 −6（−6 既是负整数也是负有理数）", "结论：漏掉了 −6，应同时放进负有理数集合"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "分类纠错——一个数可同时属于多个集合（−6 既负整数又负有理数，'集合归类'）", "难度理由": "hard——需逐项核对三个集合，并突破'一个数只能放一处'的直觉（整数 ⊂ 有理数）", "认知阶梯定位": "L3 检测 hard——检测'集合包含关系'是否内化", "错因陷阱": "认为 −6 放进整数就完成任务（漏掉负有理数，'负分数归类漏掉'错因的集合版）、检查不全（process_habit）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "小红说：'0 是整数，所以 0 也是正有理数。'这个说法对吗？为什么？",
            "expected_answer": "不对。0 是整数（也是有理数），但 0 既不是正有理数也不是负有理数，它单独是一类",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按正/负/零分类",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["0 是整数 ✓（整数包括正整数、0、负整数）", "有理数按正负分：正有理数、0、负有理数三类", "0 属于'0'这一类，不属于正有理数", "小红把'整数'和'正有理数'两个标准混在一起了，说法不对"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "'0 是整数'与'0 不是正有理数'两件事的辨析（'按正/负/零分类'）", "难度理由": "medium 复测——需区分两个分类标准，并给出论证，防'会背不会用'（背了'0 是整数'就答对）", "认知阶梯定位": "L3 复测", "错因陷阱": "认同'0 是整数所以是正有理数'（0 分类错，节点 #3 错因的论证形态）", "教学角色": "防'会背不会用'复测——0 的双标准辨析"},
        },
        {
            "slot": "B5-I0",
            "prompt": "把下列 10 个数分类：−7、0.5、−2/3、0、4、−1.25、3/8、−6、9、−0.2\n正整数集合：＿＿＿；负整数集合：＿＿＿；正分数集合：＿＿＿；负分数集合：＿＿＿",
            "expected_answer": "正整数集合：4、9；负整数集合：−7、−6；正分数集合：0.5、3/8；负分数集合：−2/3、−1.25、−0.2；0 是整数，但既不是正数也不是负数（单独一类）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "集合归类",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先按'是不是整数'分：整数 −7、0、4、−6、9；分数 0.5、−2/3、−1.25、3/8、−0.2", "整数再按正负：正整数 4、9；负整数 −7、−6；0 单独", "分数再按正负：正分数 0.5、3/8；负分数 −2/3、−1.25、−0.2（小数先化分数再判断）"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "10 个数四类集合归类（diagnostic probe'给 10 个数分类'素材，'集合归类'）", "难度理由": "hard 名副其实——10 数跨整数/分数/正/负两轴，含有限小数与 0，需先分轴再逐类核对，多步且漏项即错", "认知阶梯定位": "L4 复测——全技能综合（双标准交叉 + 小数归属 + 0 归属），防'会背不会用'", "错因陷阱": "0 误入正/负整数（节点 #3 错因）、0.5/−1.25/−0.2 不进分数集合（节点 #1 错因）、漏 −2/3（节点 #2 错因）", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "把 5、−2、0 分别放进'正数集合'或'负数集合'，0 应该放哪里？",
            "expected_answer": "5 放正数集合，−2 放负数集合；0 既不是正数也不是负数，两个集合都不能放",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按正/负/零分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["5 大于 0 → 正数，放正数集合", "−2 小于 0 → 负数，放负数集合", "0 既不大于 0 也不小于 0 → 不能放进这两个集合"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "正/负/零三态分类快速诊断（'按正/负/零分类'）", "难度理由": "easy 诊断——三数直分，0 的归属是唯一陷阱点", "认知阶梯定位": "L1 诊断——快速区分'知道 0 特殊'与'不知道'两档", "错因陷阱": "把 0 放进正数或负数集合（节点 #3 错因'0 分类错'）", "教学角色": "诊断题——0 分类错的即时探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "判断下面每个数是有理数中的'整数'还是'分数'：−0.25、4、−7/3、0",
            "expected_answer": "整数：4、0；分数：−0.25（=−1/4）、−7/3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按整数/分数分类",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["整数：正整数、负整数和 0 → 4、0", "分数：−0.25 = −25/100 = −1/4（有限小数化分数）→ 分数", "−7/3 是负分数 → 分数", "分类：整数 4、0；分数 −0.25、−7/3"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "混合数的整数/分数归属诊断（含负小数与负分数，'按整数/分数分类'）", "难度理由": "medium 诊断——−0.25 需先化分数，直接区分'会小数互化'与'不会'两档", "认知阶梯定位": "L2 诊断（diagnostic probe'给 10 个数分类'的缩小版）", "错因陷阱": "把 −0.25 归'既不是整数也不是分数'（节点 #1 错因）、把 −7/3 归整数（负分数归类漏掉）", "教学角色": "诊断题——'有限小数是分数'错因的中档探针"},
        },
    ],
    # ===== M-G7-RATIONAL-ADD-SUB 有理数加减（计算向：10 verified + 5 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="加减本质是在数轴上移动；减法可以转化为加相反数"；
    # seed=同号相加/异号相加/减法转加法/多项加减；
    # common_mistakes=符号错/绝对值大的符号没保留/减法没有转加法/省略括号后符号乱；
    # diagnostic_probes=10题覆盖同号/异号/减法/多项、要求说出2题规则。
    # authoring 原则（琢玉教训）：计算题走 sympy verified（答案必须真算对），符号陷阱对照
    # common_mistakes 埋（异号相加、负数减正数、去括号变号）；概念/规则/口算题 unverifiable
    # （避免'计算'前缀触发半截提取）；hard 真难（多项混合、分数混合、省略括号策略）。
    "M-G7-RATIONAL-ADD-SUB": [
        {
            "slot": "B1-I0",
            "prompt": "同号两数相加：取相同的符号，并把绝对值相加。例如 (−3) + (−5) = −8。用这个规则计算：(−4) + (−2)。",
            "expected_answer": "−6",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "同号相加",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同号（都是负数）→ 取负号", "绝对值相加：4 + 2 = 6", "结果：−6"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "同号相加规则（取同号、绝对值相加，'同号相加'）", "难度理由": "medium 锚点——规则 + 示例 + 平行练习，演示本质而非背符号表", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'同号取同号、绝对值相加'的演示载体（sympy 验算 verified）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "异号两数相加，结果的符号（　）\nA. 总是正号\nB. 总是负号\nC. 取绝对值较大的那个数的符号\nD. 取绝对值较小的那个数的符号",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "异号相加",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["异号相加：取绝对值较大的数的符号，并用较大的绝对值减较小的绝对值", "选 C"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别异号相加的符号规则（'异号相加'）", "难度理由": "easy——规则识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则而非直接计算）", "错因陷阱": "选 D（取绝对值小的符号，'绝对值大的符号没保留'错因的直接颠倒）、选 B（一律负号，符号错）", "教学角色": "L1 识别脚手架——异号相加符号规则第一关"},
        },
        {
            "slot": "B1-I2",
            "prompt": "把减法 −7 − 3 改写成'加相反数'的形式，正确的是（　）\nA. −7 + 3\nB. −7 + (−3)\nC. 7 + 3\nD. 7 + (−3)",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "减法转加法",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["减法转加法：减去一个数 = 加上这个数的相反数", "−7 − 3 = −7 + (−3)（3 的相反数是 −3，被减数 −7 不变）", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'减去一个数等于加它的相反数'的改写（'减法转加法'）", "难度理由": "easy——改写识别，选项 A 是'只变减号不变符号'的典型错", "认知阶梯定位": "L1 识别正宗实现（判断改写是否正确）", "错因陷阱": "选 A（−7 + 3，把'−3'错写成'+3'，'减法没有转加法'错因的识别形态）、选 C/D（被减数符号也动了）", "教学角色": "L1 识别脚手架——减法转加法的改写辨析"},
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：−8 + 3。",
            "expected_answer": "−5",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "异号相加",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["异号相加：取绝对值大的数的符号（|−8| = 8 大，取负号）", "绝对值相减：8 − 3 = 5", "结果：−5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "异号整数相加（'异号相加'）", "难度理由": "easy 套用——两步（定符号 + 绝对值相减）", "认知阶梯定位": "L2 套用", "错因陷阱": "写 +5（绝对值大的符号没保留，节点 #2 错因）、写 −11（异号却绝对值相加）", "教学角色": "L2 套用脚手架——异号相加标准形态"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：−1/2 + (−3/4)。",
            "expected_answer": "−5/4",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "同号相加",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同号（都是负数）→ 取负号", "先通分再算绝对值相加：1/2 = 2/4，2/4 + 3/4 = 5/4", "结果：−5/4"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "同号负分数相加（通分 + 符号，'同号相加'×'分数运算'）", "难度理由": "medium——符号 + 通分两步，分数是新增材料", "认知阶梯定位": "L2 套用（分数版同号相加）", "错因陷阱": "通分错（1/2 当 1/4）、结果写 +5/4（符号错，节点 #1 错因）", "教学角色": "同号相加的分数形态——符号与通分的双重训练"},
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：3 − (−5)。",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "减法转加法",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["减去 −5 = 加上 −5 的相反数 5：3 − (−5) = 3 + 5", "3 + 5 = 8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "减负数转加正数（'减法转加法'）", "难度理由": "medium——'负负得加'是最易错的去括号变号点，节点 #4 错因'省略括号后符号乱'的核心形态", "认知阶梯定位": "L3 变式（括号 + 双负号）", "错因陷阱": "写 −2（3 − 5，没把 −(−5) 变 +5，'减法没有转加法'错因）、写 −8（把两个负号都当减）", "教学角色": "减法转加法的核心变式——去括号变号第一关"},
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：−7/8 + 3/4。",
            "expected_answer": "−1/8",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "异号相加",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["通分：3/4 = 6/8", "异号相加：|−7/8| = 7/8 大，取负号", "绝对值相减：7/8 − 6/8 = 1/8", "结果：−1/8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "异号负分数相加（通分 + 定符号，'异号相加'×'分数运算'）", "难度理由": "medium——通分、定符号、绝对值相减三步", "认知阶梯定位": "L3 变式（分数异号相加）", "错因陷阱": "取正号（绝对值大的符号没保留，节点 #2 错因）、绝对值相加得 −13/8", "教学角色": "异号相加的分数形态——三步完整训练"},
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：−5 + 8 − (−3) − 7。",
            "expected_answer": "−1",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "多项加减",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先去括号：−(−3) = +3 → −5 + 8 + 3 − 7", "从左到右：−5 + 8 = 3；3 + 3 = 6；6 − 7 = −1", "结果：−1"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "多项整数加减混合（去括号 + 左到右顺序，'多项加减'×'运算顺序'）", "难度理由": "hard 名副其实——四项混合，去括号变号（−(−3) → +3）与负数减正数（6 − 7）双陷阱叠加，任何一步符号错即全错", "认知阶梯定位": "L4 迁移——小学运算顺序（M-PRE-ORDER-OPS 前置）× 有理数加减", "错因陷阱": "−(−3) 变 −3（'减法没有转加法'）、6 − 7 算成 +1（符号错）、省略括号后符号乱（节点 #4 错因）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：3/4 − (−1/2) + (−5/8)。",
            "expected_answer": "5/8",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "多项加减",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先去括号：−(−1/2) = +1/2，+(−5/8) = −5/8 → 3/4 + 1/2 − 5/8", "通分：3/4 = 6/8，1/2 = 4/8", "6/8 + 4/8 − 5/8 = 5/8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "多项分数加减混合（通分 + 去括号变号，'多项加减'×'分数运算'）", "难度理由": "hard——三项分数、通分与去括号变号叠加（−(−1/2) 与 +(−5/8) 两种括号），计算量大且符号易错", "认知阶梯定位": "L4 迁移——分数加减（小学分数运算）× 有理数符号规则", "错因陷阱": "+(−5/8) 去括号后变 +5/8（省略括号后符号乱，节点 #4 错因）、通分错、结果写负（符号错）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：−9 + 5。",
            "expected_answer": "−4",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "异号相加",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["异号相加：|−9| = 9 大，取负号", "绝对值相减：9 − 5 = 4", "结果：−4"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "异号整数相加检测（'异号相加'）", "难度理由": "easy 检测——单步异号规则", "认知阶梯定位": "L2 检测", "错因陷阱": "写 +4（绝对值大的符号没保留，节点 #2 错因）、写 −14（异号却绝对值相加）", "教学角色": "检测易档——异号相加头号错因快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：−3 − (−5) + (−2) − 4。",
            "expected_answer": "−4",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "多项加减",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["去括号：−(−5) = +5，+(−2) = −2 → −3 + 5 − 2 − 4", "从左到右：−3 + 5 = 2；2 − 2 = 0；0 − 4 = −4", "结果：−4"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "四项混合去括号检测（−(−5) 与 +(−2) 两种括号，'多项加减'）", "难度理由": "hard——四步符号链，−(−5) 变 +5、+(−2) 变 −2 两个变号点，任何一处错即全错", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "+(−2) 变 +2（省略括号后符号乱，节点 #4 错因）、0 − 4 算成 +4（符号错）、−(−5) 不变号（'减法没有转加法'）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "有一个数，它加上 −7 后等于 −2。这个数是多少？",
            "expected_answer": "5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "异号相加",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["设这个数为 x：x + (−7) = −2", "反向思考：x = −2 − (−7) = −2 + 7", "x = 5"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "反向求加数（已知和与一个加数，'异号相加'逆向）", "难度理由": "medium 复测——方向反转（给结果求加数），需把减法转加法反向运用，防'会背不会用'", "认知阶梯定位": "L3 复测", "错因陷阱": "把关系读反（x = −7 + (−2) = −9）、x = −2 − 7 = −9（减法没有转加法反向）", "教学角色": "防'会背不会用'复测——关系句反向理解"},
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：−2 − (−3) + 4 − (+5) − 1，先写成'省略括号的和'的形式再计算。",
            "expected_answer": "−1",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "多项加减",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["省略括号：−2 − (−3) + 4 − (+5) − 1 → −2 + 3 + 4 − 5 − 1", "从左到右：−2 + 3 = 1；1 + 4 = 5；5 − 5 = 0；0 − 1 = −1", "结果：−1"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "省略括号改写 + 多项计算（−(−3)、−(+5) 两种变号，'多项加减'）", "难度理由": "hard——强制先做'省略括号的和'改写（−(+5) → −5 是隐藏变号点）再四步计算，策略 + 符号双要求", "认知阶梯定位": "L4 复测——'省略括号后符号乱'错因（节点 #4）的对症复测", "错因陷阱": "−(+5) 变 +5（省略括号后符号乱，节点 #4 错因）、−(−3) 变 −3（'减法没有转加法'）、过程跳步（process_habit）", "教学角色": "复测 hard 档——省略括号策略的标准示范（sympy 验算 verified）"},
        },
        {
            "slot": "B5-I1",
            "prompt": "口算下面各题：①(−5) + (−3)　②(−7) + 4　③6 − (−2)",
            "expected_answer": "① −8　② −3　③ 8",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "同号相加",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["① 同号相加：取负号，5 + 3 = 8 → −8", "② 异号相加：|−7| 大取负号，7 − 4 = 3 → −3", "③ 减法转加法：6 − (−2) = 6 + 2 = 8"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三题口算快速诊断（同号/异号/减法各一，diagnostic probe 素材，'同号相加'×'异号相加'×'减法转加法'）", "难度理由": "easy 诊断——三小题覆盖三个核心子技能，每题单步", "认知阶梯定位": "L1 诊断——快速区分三规则各自掌握情况", "错因陷阱": "① 写 −2（异号规则错用）、② 写 11（异号却绝对值相加）、③ 写 4（减法没有转加法）", "教学角色": "诊断题——三种规则一键分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "先口算 −12 + 8 和 −5 − (−9)，再说出每题分别用到了什么规则。",
            "expected_answer": "−12 + 8 = −4（规则：异号相加，取绝对值大的符号、绝对值相减）；−5 − (−9) = 4（规则：减去一个数等于加上它的相反数）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "减法转加法",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−12 + 8：|−12| = 12 大取负号，12 − 8 = 4 → −4（异号相加规则）", "−5 − (−9)：减法转加法 −5 + 9，异号相加取正号（|9| 大），9 − 5 = 4 → 4", "规则总结：异号相加定符号取绝对值大的、减法转加法"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "计算 + 说规则（diagnostic probe'要求说出 2 题规则'素材，'减法转加法'×'异号相加'）", "难度理由": "medium 诊断——值 + 规则双输出，直接区分'会算'与'懂规则'两档（mastery 判据'能口述异号相加规则'取证）", "认知阶梯定位": "L2 诊断", "错因陷阱": "只会算说不清规则（'会背不会用'）、−5 − (−9) 算成 −14（减法没有转加法）", "教学角色": "诊断题——mastery'能口述规则'的取证题"},
        },
    ],
    # ===== M-G7-RATIONAL-MUL-DIV 有理数乘除（计算向：9 verified + 6 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="乘除先定符号，再算绝对值；除法可转化为乘倒数"；
    # seed=两数乘除/多个因数符号/除法转倒数/含分数乘除；
    # common_mistakes=负号个数判断错/除法忘倒数/分数约分错；
    # diagnostic_probes=8题乘除，至少2题含分数，2题多个负号；
    # mastery=正确率≥85%、能先符号后数值。
    # authoring 原则（琢玉教训）：计算题走 sympy verified（答案必须真算对）；L1 真识别
    # （判断符号规则/倒数规则而非直接算）；hard 真难（连乘符号计数、小数×分数除法链、
    # 先定符号策略复测）；'含 0'（0 无视符号规则）与'带分数→假分数'在复测/变式档布点；
    # '先符号后数值'策略用 B5-I0 强制前缀 + B5-I2 说规则双取证。
    "M-G7-RATIONAL-MUL-DIV": [
        {
            "slot": "B1-I0",
            "prompt": "同号两数相乘：正正得正，负负得正，取正号并把绝对值相乘。例如 (−3) × (−4) = 12。用这个规则计算：(−5) × (−6)。",
            "expected_answer": "30",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两数乘除",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同号（都是负数）→ 取正号", "绝对值相乘：5 × 6 = 30", "结果：30"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "同号相乘规则（负负得正、先定符号再算绝对值，'两数乘除'）", "难度理由": "medium 锚点——规则 + 示例 + 平行练习，演示本质而非背符号表", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'负负得正'记混在 B1-I1 单独设识别题）", "教学角色": "讲本质用——'乘除先定符号，再算绝对值'的演示载体（sympy 验算 verified）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "两个负数相乘，结果的符号是（　）\nA. 正号\nB. 负号\nC. 可能是正也可能是负\nD. 没有符号",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "两数乘除",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同号两数相乘得正（负负得正）", "选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别同号相乘的符号规则（'两数乘除'）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则而非直接计算）", "错因陷阱": "选 B（'负负得正'记混成得负，'负号个数判断错'错因的识别形态）", "教学角色": "L1 识别脚手架——符号规则第一关"},
        },
        {
            "slot": "B1-I2",
            "prompt": "除以一个数等于乘以这个数的（　）\nA. 相反数\nB. 倒数\nC. 绝对值\nD. 它本身",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "除法转倒数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["除法转乘法：除以一个数等于乘以它的倒数", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'除法转倒数'规则（'除法转倒数'）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则）", "错因陷阱": "选 A（把倒数当相反数——'除法忘倒数'错因的源头：分不清倒数与相反数）", "教学角色": "L1 识别脚手架——除法转倒数规则层探针"},
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：(−8) ÷ 4。",
            "expected_answer": "−2",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两数乘除",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["异号相除得负", "绝对值相除：8 ÷ 4 = 2", "结果：−2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "异号相除（先定符号再算绝对值，'两数乘除'）", "难度理由": "easy 套用——两步", "认知阶梯定位": "L2 套用", "错因陷阱": "写 +2（异号符号丢，'负号个数判断错'变体）", "教学角色": "L2 套用脚手架——异号除法标准形态"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：(−3/4) ÷ (−1/2)。",
            "expected_answer": "3/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "除法转倒数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同号相除得正，先定符号", "除法转倒数：(−3/4) ÷ (−1/2) = (−3/4) × (−2)", "绝对值相乘：3/4 × 2 = 3/2", "结果：3/2"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分数除法转倒数（'除法转倒数'×'含分数乘除'）", "难度理由": "medium——倒数转化 + 约分 + 符号三步", "认知阶梯定位": "L2 套用（分数版除法转倒数）", "错因陷阱": "忘转倒数直接乘（(−3/4)×(−1/2)=3/8，'除法忘倒数'节点 #2 错因）、约分错", "教学角色": "除法转倒数的分数形态标准变式"},
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：(−5/6) × (−3/10)。",
            "expected_answer": "1/4",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "含分数乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同号相乘得正，先定符号", "约分：5/6 × 3/10，5 与 10 约 5、3 与 6 约 3", "约分后：1/2 × 1/2 = 1/4", "结果：1/4"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "负分数相乘（符号 + 交叉约分，'含分数乘除'）", "难度理由": "medium——两步约分 + 符号", "认知阶梯定位": "L3 变式（分数材料）", "错因陷阱": "约分后符号丢（先定符号再约分，写 −1/4，'约分后符号丢'错因）、约分错（15/60 不化简）", "教学角色": "分数乘除标准变式——'先定符号再算绝对值'的完整演示"},
        },
        {
            "slot": "B3-I0",
            "prompt": "把带分数 −2 又 1/3 化成假分数，正确的是（　）\nA. −7/3\nB. −5/3\nC. 7/3\nD. −2/3",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含分数乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["带分数 −2 又 1/3 = −(2 + 1/3)", "2 + 1/3 = 6/3 + 1/3 = 7/3", "带负号：−7/3，选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "带分数化假分数（负号保留，'含分数乘除'前置技能）", "难度理由": "medium——负带分数转化是乘除计算的直接前置且易错（漏负号 / 把'又'当乘法）", "认知阶梯定位": "L3 变式（换形式：带分数→假分数）", "错因陷阱": "漏负号写 7/3（选 C）、把 −2 又 1/3 误解成 2−1/3 或 2×1/3（选 B）、符号整体丢（选 D）——'分数约分错'的源头", "教学角色": "乘除前带分数转化脚手架（B5-I2 假分数除法依赖此题铺垫）"},
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：−6 ÷ 2 × (−3) + (−4) − 5。",
            "expected_answer": "0",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两数乘除",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["乘除同级从左到右：−6 ÷ 2 = −3", "−3 × (−3) = 9（同号得正）", "9 + (−4) = 5（异号相加取正号，绝对值 9−4=5）", "5 − 5 = 0", "结果：0"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘除与加减混合（同级左到右 + 异号相加 + 去括号变号，'两数乘除'×'有理数加减'前置）", "难度理由": "hard 名副其实——四步符号链：若先算 2×(−3) 则顺序错（−6÷(−6)=1 全链崩）、+(−4) 去括号变号、末步 5−5，任一步错即全错", "认知阶梯定位": "L4 迁移——乘除 × 加减（M-G7-RATIONAL-ADD-SUB 前置）混合，同级左到右属小学运算顺序迁移", "错因陷阱": "运算顺序错（先乘后除）、+(−4) 变 +4（省略括号后符号乱）、5−5 符号错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：(−3/4) ÷ (−1/2) × (−4/3)。",
            "expected_answer": "−2",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "多个因数符号",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先数负号个数：3 个负号（奇数）→ 结果取负号", "除法转倒数：(−3/4) ÷ (−1/2) = (−3/4) × (−2)", "绝对值连乘：3/4 × 2 × 4/3 = (3/4 × 4/3) × 2 = 2", "结果：−2"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "三因数连乘除的符号计数（'多个因数符号'×'含分数乘除'）", "难度理由": "hard 名副其实——符号计数（3 负得负）+ 倒数转化 + 交叉约分三陷阱叠加，任何一处错即全错", "认知阶梯定位": "L4 迁移——分数乘除（小学分数运算 M-PRE-FRACTION-OPS 前置）× 有理数符号计数", "错因陷阱": "负号个数数错（数成 2 个得正，'负号个数判断错'节点 #1 错因）、除法忘倒数、约分错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：(−12) ÷ (−3)。",
            "expected_answer": "4",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两数乘除",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同号相除得正", "绝对值相除：12 ÷ 3 = 4", "结果：4"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "同号相除检测（'两数乘除'）", "难度理由": "easy 检测——单步，但符号陷阱有区分度（写 −4 即中招）", "认知阶梯定位": "L2 检测", "错因陷阱": "写 −4（'负负得正'记混，'负号个数判断错'）", "教学角色": "检测易档——符号规则快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：(−2.5) × (−4) ÷ (−1/2)。",
            "expected_answer": "−20",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "多个因数符号",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先数负号：3 个负号（奇数）→ 结果取负号", "绝对值计算：2.5 × 4 = 10", "10 ÷ 1/2 = 10 × 2 = 20（除法转倒数）", "结果：−20"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "小数×整数×分数除法的符号计数 + 倒数（'多个因数符号'×'除法转倒数'）", "难度理由": "hard 名副其实——三陷阱叠加：符号计数（3 负得负）、小数乘法位值（2.5×4=10）、÷(1/2) 转倒数（×2），任一处错即全错", "认知阶梯定位": "L3 检测 hard——检测'先符号后数值'策略是否内化", "错因陷阱": "负号个数数错（写 +20）、÷(−1/2) 直接除（'除法忘倒数'）、2.5×4 位值错", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "判断：'0 ÷ (−5) 的结果是负数。'这个说法对吗？（　）\nA. 对，异号相除得负\nB. 对，0 是正数\nC. 错，0 除以任何非零数都得 0，0 没有符号\nD. 错，结果应该是正数",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "两数乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["0 除以任何非零数都得 0", "0 既不是正数也不是负数，符号规则对 0 无效", "说法错，选 C"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "0 的除法与符号特例（'两数乘除'含 0）", "难度理由": "medium 复测——单陷阱但反直觉（机械套'异号得负'即中招），防'会背不会用'", "认知阶梯定位": "L3 复测——符号规则在 0 上失效的特例核验", "错因陷阱": "对 0 机械套符号规则（选 A，'负号个数判断错'深层形态）、把 0 当正数（选 B）", "教学角色": "防'会背不会用'复测——0 例外是符号规则的边界测试"},
        },
        {
            "slot": "B5-I0",
            "prompt": "先判断结果的符号，再计算：(−2/3) ÷ (−8/9) × (−3/4)。",
            "expected_answer": "−9/16",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "多个因数符号",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先定符号：3 个负号（奇数）→ 结果为负", "除法转倒数：(−2/3) ÷ (−8/9) = (−2/3) × (−9/8)", "绝对值连乘约分：(2/3) × (9/8) × (3/4) = (2×9×3)/(3×8×4)", "约分（约 3、约 2）得 9/16", "结果：−9/16"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "先定符号再算绝对值的完整策略（'多个因数符号'，mastery'能先符号后数值'取证）", "难度理由": "hard——强制先定符号（策略要求）+ 倒数转化 + 三步约分，多步多陷阱", "认知阶梯定位": "L4 复测——策略性复测，防'会背不会用'（背了'负负得正'不会先定符号）", "错因陷阱": "先算后定符号（约分中符号丢，'约分后符号丢'）、除法忘倒数、约分错", "教学角色": "复测 hard 档——'先符号后数值'策略标准示范（sympy 验算 verified）"},
        },
        {
            "slot": "B5-I1",
            "prompt": "口算下面各题：①(−6) × (−3)　②0 ÷ (−5)　③(−12) ÷ 4",
            "expected_answer": "① 18　② 0　③ −3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两数乘除",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["① 同号相乘得正：6 × 3 = 18", "② 0 除以任何非零数都得 0", "③ 异号相除得负：12 ÷ 4 = 3 → −3"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三题口算快速诊断（同号乘 / 0 的除法 / 异号除各一，diagnostic probe'8 题乘除'素材，'两数乘除'）", "难度理由": "easy 诊断——三小题单步，覆盖三个核心子技能", "认知阶梯定位": "L1 诊断——快速区分三规则各自掌握情况", "错因陷阱": "① 写 −18（'负负得正'记混）、② 写 −5（对 0 套符号规则）、③ 写 3（异号符号丢）", "教学角色": "诊断题——三规则一键分档（A/B/C/D）"},
        },
        {
            "slot": "B5-I2",
            "prompt": "先口算 (−2) × (−9) 和 (−6) ÷ (−2/3)，再说出每题先定符号的规则。",
            "expected_answer": "18 和 9；规则：同号相乘（相除）得正，先定符号再算绝对值；除法要转成乘倒数",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "除法转倒数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["(−2) × (−9)：同号得正，2 × 9 = 18", "(−6) ÷ (−2/3)：同号得正，转倒数 (−6) × (−3/2) = 18/2 = 9", "规则总结：先数负号定符号（同号得正），再算绝对值；除法先转成乘倒数"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "计算 + 说规则（值 + 策略双输出，mastery'能先符号后数值'取证，diagnostic probe 素材，'除法转倒数'）", "难度理由": "medium 诊断——值 + 规则双输出，第二题含倒数转化两步，直接区分'会算'与'懂规则'两档", "认知阶梯定位": "L2 诊断", "错因陷阱": "只会算说不清规则（'会背不会用'）、(−6)÷(−2/3) 忘转倒数（算成 4）、符号错", "教学角色": "诊断题——mastery'能先符号后数值'的取证题"},
        },
    ],
    # ===== M-G7-POWER 乘方（计算向：10 verified + 5 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="乘方是相同因数连乘，底数和指数必须看清"；
    # seed=正负数乘方/底数带括号/科学记数法前置；
    # common_mistakes=−2²和(−2)²混淆/指数当乘数/0和1的乘方不熟；
    # diagnostic_probes=6题乘方，重点含-2²与(-2)²；
    # mastery=能解释底数是谁、符号判断正确率≥90%。
    # authoring 原则（琢玉教训）：乘方题用 ASCII ^ 记法保证 sympy verified
    # （上标 ² 会触发半截提取变 mismatch）；头号错因'−2² 与 (−2)² 混淆'三档布点
    # （B1-I2 识别判断 / B4-I1 同式双形态硬检 / B4-I2 比较复测 / B5-I2 解释底数）；
    # 0 与 1 的幂（B4-I0/B5-I1）、10 的幂（B5-I1，科学记数法前置）覆盖。
    "M-G7-POWER": [
        {
            "slot": "B1-I0",
            "prompt": "乘方表示相同因数连乘，例如 2^3 = 2×2×2 = 8。用这个规则计算：3^2。",
            "expected_answer": "9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["3^2 表示 3 连乘 2 次：3 × 3", "3 × 3 = 9"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "乘方定义（相同因数连乘，'正负数乘方'）", "难度理由": "medium 锚点——定义 + 示例 + 平行练习", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'乘方是相同因数连乘，底数和指数必须看清'的演示载体（sympy 验算 verified）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "在 (−3)^2 中，底数是（　）\nA. 3\nB. −3\nC. 2\nD. 9",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "底数带括号",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["底数是'被连乘的那个数'，指数是'连乘的次数'", "括号把整个 −3 括起来 → 底数是 −3", "指数是 2，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别底数与指数（括号决定底数，'底数带括号'）", "难度理由": "easy——定义识别，无计算", "认知阶梯定位": "L1 识别正宗实现（判断'底数是谁'，mastery'能解释底数是谁'起点）", "错因陷阱": "选 A（漏负号，把底数当 3）、选 C（底数指数混淆）、选 D（把结果当底数）", "教学角色": "L1 识别脚手架——底数判定第一关"},
        },
        {
            "slot": "B1-I2",
            "prompt": "判断：'−2^2 和 (−2)^2 的结果相同。'这个说法（　）\nA. 对，都是 4\nB. 对，都是 −4\nC. 错，−2^2 = −4，(−2)^2 = 4\nD. 错，−2^2 = 4，(−2)^2 = −4",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "底数带括号",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["−2^2：底数是 2（负号在括号外），先算 2^2 = 4 再取负 → −4", "(−2)^2：底数是 −2（括号内），(−2) × (−2) = 4", "两者不同，−2^2 = −4、(−2)^2 = 4，选 C"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'−2^2 与 (−2)^2'的区别（括号决定底数，'底数带括号'）", "难度理由": "easy——规则判断无计算，但直击头号错因", "认知阶梯定位": "L1 识别正宗实现（'−2^2 看成 (−2)^2'错因的识别形态）", "错因陷阱": "选 A/D（把 −2^2 当 (−2)^2，'−2² 和 (−2)² 混淆'节点 #1 错因）", "教学角色": "L1 识别脚手架——头号错因规则层探针"},
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：2^4。",
            "expected_answer": "16",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["2^4 表示 2 连乘 4 次：2 × 2 × 2 × 2", "2 × 2 = 4，4 × 2 = 8，8 × 2 = 16", "结果：16"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "正数乘方展开（'正负数乘方'）", "难度理由": "easy 套用——连乘 4 次", "认知阶梯定位": "L2 套用", "错因陷阱": "写 8（指数当乘数 2×4，'指数当乘数'节点 #2 错因）", "教学角色": "L2 套用脚手架——展开式标准形态"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：(−2)^3。",
            "expected_answer": "−8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["(−2)^3 表示 (−2) 连乘 3 次", "(−2) × (−2) = 4，4 × (−2) = −8", "3 是奇数 → 负数乘方得负，结果：−8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "负数奇次幂（符号判断，'正负数乘方'）", "难度理由": "medium——连乘展开 + 奇偶符号两步", "认知阶梯定位": "L2 套用（负数乘方标准形态）", "错因陷阱": "写 +8（奇次幂符号错，'符号判断'错因）、写 −6（指数当乘数）", "教学角色": "L2 套用——奇偶次幂符号规则标准示范"},
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：−3^2。",
            "expected_answer": "−9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "底数带括号",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["−3^2：底数是 3，负号在外面（没有括号把 −3 括起来）", "先算 3^2 = 9，再取负：−9", "结果：−9（注意不是 9，也不是 (−3)^2）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "无括号负号乘方（底数是 3 而非 −3，'底数带括号'）", "难度理由": "medium——头号错因'−2² 看成 (−2)²'的正面对抗（写成 9 即中招）", "认知阶梯定位": "L3 变式（从括号底数转向无括号负号）", "错因陷阱": "写 9（把 −3^2 当 (−3)^2，节点 #1 错因）、写 −6（指数当乘数）", "教学角色": "头号错因核心变式——'先看底数是谁'的正名"},
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：(−1/2)^3。",
            "expected_answer": "−1/8",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["(−1/2)^3 表示 (−1/2) 连乘 3 次", "符号：3 是奇数 → 结果为负", "绝对值：(1/2) × (1/2) × (1/2) = 1/8", "结果：−1/8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "负分数乘方（符号 + 分数连乘，'正负数乘方'×'分数'）", "难度理由": "medium——奇偶符号 + 分数乘方两步，且 (1/2)^3 是 1/8 非 1/6（乘方 vs 乘法混淆陷阱）", "认知阶梯定位": "L3 变式（换分数底数材料）", "错因陷阱": "写 1/8（奇数幂符号丢）、写 −3/6 或 −1/6（把乘方当乘法，'指数当乘数'）", "教学角色": "分数底数乘方标准变式"},
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：(−2)^3 × (−3/4) ÷ (−3/8)。",
            "expected_answer": "−16",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先算乘方：(−2)^3 = −8（3 个 −2 连乘，奇数次得负）", "再算乘除（左到右）：−8 × (−3/4) = 6", "6 ÷ (−3/8) = 6 × (−8/3) = −16（除法转倒数）", "结果：−16"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘方 × 乘除链（乘方展开 + 倒数 + 符号计数，'正负数乘方'×'有理数乘除'前置）", "难度理由": "hard 名副其实——乘方符号（(−2)^3=−8）、分数乘、除法转倒数、三负号计数四步，任一步错即全错", "认知阶梯定位": "L4 迁移——乘方（本节点）× 乘除（M-G7-RATIONAL-MUL-DIV 前置）混合", "错因陷阱": "(−2)^3 写 +8（奇次幂符号错）、÷(−3/8) 忘转倒数、约分错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：−(−2)^2 + (−1)^4。",
            "expected_answer": "−3",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "底数带括号",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["−(−2)^2：底数是括号里的 −2，先算乘方 (−2)^2 = 4，外面的负号表示取相反数 → −4", "(−1)^4：4 是偶数 → (−1)^4 = 1", "−4 + 1 = −3", "结果：−3"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "多重负号 + 括号底数（−(−2)^2 的底数判定，'底数带括号'×'相反数'前置）", "难度理由": "hard——把'−(−2)^2'读成'(−(−2))^2'即得 4（括号位置迷思），叠加 (−1)^4 偶次幂与负数加法，多陷阱", "认知阶梯定位": "L4 迁移——乘方 × 相反数/负号（M-G7-OPPOSITE 前置）× 加减", "错因陷阱": "把 −(−2)^2 当 (−(−2))^2 写 4（'−2² 和 (−2)² 混淆'深层）、(−1)^4 写 −1（奇偶错）、−4 + 1 符号错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：0^5。",
            "expected_answer": "0",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0^5 表示 0 连乘 5 次", "0 乘任何数都得 0", "结果：0"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "0 的乘方（0 的任何正整数次幂都是 0，'正负数乘方'）", "难度理由": "easy 检测——单陷阱（0 的乘方不熟，节点 #3 错因）", "认知阶梯定位": "L2 检测", "错因陷阱": "写 5（把指数当结果）或 1（'0 和 1 的乘方不熟'）", "教学角色": "检测易档——0 的乘方快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：(−2)^2 − (−2^2)。",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "底数带括号",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["(−2)^2：底数是 −2，(−2) × (−2) = 4", "−2^2：底数是 2，先算 2^2 = 4 再取负 → −4", "(−2)^2 − (−2^2) = 4 − (−4) = 4 + 4 = 8", "结果：8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "同式双形态对抗（(−2)^2 与 −2^2 同题计算，'底数带括号'）", "难度理由": "hard 名副其实——两种形态一步之差符号全反：把 −2^2 当 4 则得 0，把 (−2)^2 当 −4 则得 −8，多处可错", "认知阶梯定位": "L3 检测 hard——头号错因'−2² 和 (−2)² 混淆'的正面硬检", "错因陷阱": "−2^2 当 4（得 0）、(−2)^2 当 −4、去括号变号错（4−4=0）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "(−3)^2 和 −3^2 哪个大？",
            "expected_answer": "(−3)^2 大：(−3)^2 = 9，−3^2 = −9，9 > −9",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "底数带括号",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["(−3)^2：底数是 −3，(−3) × (−3) = 9", "−3^2：底数是 3，3^2 = 9 再取负 → −9", "9 > −9，所以 (−3)^2 大"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "双形态比较（先分别求值再比大小，'底数带括号'）", "难度理由": "medium 复测——必须把两种形态都算出来再比较，防'会背不会用'（背了'括号管底数'但不会求值）", "认知阶梯定位": "L3 复测", "错因陷阱": "认为 −3^2 = 9（头号错因）、把 9 与 −9 比大小写反（负数比较前置）", "教学角色": "防'会背不会用'复测——形态区别的求值核验"},
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：2^3 + 2^4 − 2^5。",
            "expected_answer": "−8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "正负数乘方",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["分别求幂：2^3 = 8，2^4 = 16，2^5 = 32", "再算加减：8 + 16 − 32 = −8", "结果：−8"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "多幂混合求值（三幂展开 + 加减，'正负数乘方'）", "难度理由": "hard——三个幂各有'指数当乘数'陷阱（2^3=6、2^4=8、2^5=10），展开错误率叠加，且末步 8+16−32 符号易错", "认知阶梯定位": "L4 复测——多幂 + 加减混合，防'会背不会用'", "错因陷阱": "指数当乘数（2^5 写 10，节点 #2 错因）、8 + 16 − 32 符号错", "教学角色": "复测 hard 档——幂值记忆与混合求值综合"},
        },
        {
            "slot": "B5-I1",
            "prompt": "口算下面各题：①2^3　②(−1)^5　③10^2",
            "expected_answer": "① 8　② −1　③ 100",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "正负数乘方",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["① 2^3 = 2×2×2 = 8", "② (−1)^5：5 是奇数 → −1", "③ 10^2 = 10 × 10 = 100（1 后面 2 个 0）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三题口算快速诊断（幂值 / 奇偶符号 / 10 的幂各一，diagnostic probe'6 题乘方'素材，'正负数乘方'）", "难度理由": "easy 诊断——三小题单步，覆盖幂计算、负底数符号、科学记数法前置（10 的幂）", "认知阶梯定位": "L1 诊断——快速分档", "错因陷阱": "① 写 6（指数当乘数）、② 写 1（奇偶符号错）、③ 写 20（10 的幂错）", "教学角色": "诊断题——三技能一键分档（A/B/C/D）"},
        },
        {
            "slot": "B5-I2",
            "prompt": "先写出 (−3)^2 和 −3^2 各自的结果，再说出它们的底数分别是谁。",
            "expected_answer": "(−3)^2 = 9，底数是 −3（括号里整个 −3 连乘两次）；−3^2 = −9，底数是 3（只有 3 连乘两次，负号在外面）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "底数带括号",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["(−3)^2：底数是 −3，(−3) × (−3) = 9", "−3^2：底数是 3，3^2 = 9 再取负 → −9", "底数总结：有没有括号决定底数是谁——括号把 −3 整体括起来时底数才是 −3"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "计算 + 解释底数（值 + 底数双输出，mastery'能解释底数是谁'取证，diagnostic probe'重点含 -2² 与 (−2)²'素材，'底数带括号'）", "难度理由": "medium 诊断——值 + 底数双输出，直接区分'会算'与'懂底数'两档", "认知阶梯定位": "L2 诊断", "错因陷阱": "只会算说不清底数（'会背不会用'）、−3^2 底数说成 −3（头号错因）、两式结果写反", "教学角色": "诊断题——mastery'能解释底数是谁'的取证题"},
        },
    ],
    # ===== M-G7-RATIONAL-MIXED 有理数混合运算（计算向：11 verified + 4 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="混合运算是小学运算顺序 + 初一符号规则的组合"；
    # seed=含括号/含乘方/分数小数混合/简算；
    # common_mistakes=运算顺序错/符号错/分数约分错/跳步；
    # diagnostic_probes=6题混合运算，覆盖括号、乘方、分数；
    # mastery=正确率≥80%、步骤清楚不靠心算乱跳。
    # authoring 原则（琢玉教训）：每道计算题至少两层运算（乘方/括号/分数混合），
    # '先乘方再乘除后加减'顺序判断用 L1 识别题取证；hard 全为三陷阱以上；
    # 简算用'用简便方法计算'强制策略；'同级从左到右'与'括号内先算'分别
    # 在复测（B4-I2）与识别（B1-I1/B1-I2）档布点。
    "M-G7-RATIONAL-MIXED": [
        {
            "slot": "B1-I0",
            "prompt": "混合运算的顺序：先算乘除，再算加减。例如 2 + 3 × 4 = 2 + 12 = 14。用这个规则计算：5 + 2 × 3。",
            "expected_answer": "11",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "混合运算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘除：2 × 3 = 6", "再算加减：5 + 6 = 11", "结果：11"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "混合运算顺序（先乘除后加减，'混合运算'）", "难度理由": "medium 锚点——顺序规则 + 示例 + 平行练习", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；顺序陷阱在 B1-I1 识别题单独布点）", "教学角色": "讲本质用——'混合运算是小学运算顺序 + 初一符号规则的组合'的演示载体（sympy 验算 verified）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "在 2 + 3 × 4 中，先算什么？（　）\nA. 先算 2 + 3\nB. 先算 3 × 4\nC. 从左到右依次算\nD. 先算大的数",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "混合运算",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["混合运算先算乘除、再算加减", "2 + 3 × 4 中只有乘法在乘除级 → 先算 3 × 4", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别运算顺序（先乘除后加减，'混合运算'）", "难度理由": "easy——顺序规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现（判断'哪步先算'，'运算顺序错'错因的识别形态）", "错因陷阱": "选 A（先加后乘，'运算顺序错'节点 #1 错因）、选 C（同级左到右误用）", "教学角色": "L1 识别脚手架——顺序规则第一关"},
        },
        {
            "slot": "B1-I2",
            "prompt": "在 2 + 3^2 × 4 中，第一步先算什么？（　）\nA. 先算 2 + 3\nB. 先算 3^2\nC. 先算 3^2 × 4\nD. 从左到右依次算",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含乘方",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["顺序：先乘方，再乘除，后加减", "2 + 3^2 × 4 中最高级是乘方 → 第一步先算 3^2", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别乘方优先级（先乘方再乘除后加减，'含乘方'）", "难度理由": "easy——顺序识别", "认知阶梯定位": "L1 识别正宗实现（判断'哪步先算'的乘方级）", "错因陷阱": "选 C（把乘方和乘法当同级一步算，'括号内先算漏'变体）、选 A（加减抢先）", "教学角色": "L1 识别脚手架——乘方优先级规则探针"},
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：12 − 6 ÷ 3。",
            "expected_answer": "10",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "混合运算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先算乘除：6 ÷ 3 = 2", "再算加减：12 − 2 = 10", "结果：10"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "乘除先于加减的两级混合（'混合运算'）", "难度理由": "easy 套用——两级顺序两步", "认知阶梯定位": "L2 套用", "错因陷阱": "写 2（从左到右 (12−6)÷3，'运算顺序错'节点 #1 错因）", "教学角色": "L2 套用脚手架——顺序规则标准套用"},
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：(−5 + 8) × 2。",
            "expected_answer": "6",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含括号",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["括号优先：先算 −5 + 8 = 3（异号相加取正号）", "再算乘法：3 × 2 = 6", "结果：6"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "括号优先 + 异号相加（'含括号'）", "难度理由": "medium——括号内异号相加（取绝对值大的符号）再乘，两步", "认知阶梯定位": "L2 套用（含括号标准形态）", "错因陷阱": "先乘后加（−5+16=11，'括号内先算漏'）、−5+8 符号错（写 −13）", "教学角色": "括号优先标准变式"},
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：2^3 − (−4)。",
            "expected_answer": "12",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含乘方",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘方：2^3 = 8", "去括号变号：8 − (−4) = 8 + 4", "8 + 4 = 12，结果：12"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "乘方 + 去括号变号（'含乘方'×'减法转加法'前置）", "难度理由": "medium——乘方展开 + 去括号变号两步", "认知阶梯定位": "L3 变式（乘方元素进入混合）", "错因陷阱": "2^3 写 6（指数当乘数）、8 − (−4) 写 4（'−(−4)'不变号，去括号变号错）", "教学角色": "乘方 × 加减混合变式"},
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：3/4 × (−0.5) + 1/2。",
            "expected_answer": "1/8",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数小数混合",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘法：3/4 × (−0.5) = 3/4 × (−1/2) = −3/8（把 0.5 化成 1/2）", "再算加法：−3/8 + 1/2 = −3/8 + 4/8 = 1/8", "结果：1/8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数小数混合（互化统一形式 + 符号 + 通分，'分数小数混合'）", "难度理由": "medium——互化（0.5→1/2）+ 符号 + 通分三步", "认知阶梯定位": "L3 变式（分数小数混合材料）", "错因陷阱": "0.5 与分数直接乱乘（3/4×0.5 位值错）、−3/8 + 1/2 通分错、符号丢", "教学角色": "分数小数混合标准变式"},
        },
        {
            "slot": "B3-I1",
            "prompt": "用简便方法计算：(−5) × 7 + (−5) × 3。",
            "expected_answer": "−50",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "简算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["观察两个乘积有公因数 (−5)", "提取公因数：(−5) × 7 + (−5) × 3 = (−5) × (7 + 3)", "(−5) × 10 = −50", "结果：−50"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘法分配律的逆用（提取公因数简算，'简算'）", "难度理由": "hard——'用简便方法计算'强制策略（提取公因数），直接算虽可得分但三处符号易错，策略识别是本考点核心", "认知阶梯定位": "L4 迁移——乘法分配律（小学运算律 M-PRE-ORDER-OPS 前置）× 有理数符号", "错因陷阱": "看不出公因数 (−5) 直接硬算、提取后 (7+3) 符号错、公因数符号提取错", "教学角色": "判定层 transfer 证据来源（C3 双角色）——简算策略迁移"},
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：(−3)^2 × 2 − 18 ÷ (−3)。",
            "expected_answer": "24",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含乘方",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先算乘方：(−3)^2 = 9", "再算乘除（左到右）：9 × 2 = 18；18 ÷ (−3) = −6", "最后算加减：18 − (−6) = 18 + 6 = 24", "结果：24"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘方 + 乘除 + 加减的完整顺序（'含乘方'×'含括号'）", "难度理由": "hard 名副其实——乘方符号（(−3)^2=9）、除法符号（18÷(−3)=−6）、去括号变号（18−(−6)=24）三陷阱叠加，五步运算", "认知阶梯定位": "L4 迁移——乘方（M-G7-POWER 前置）× 乘除（MUL-DIV 前置）× 顺序（小学前置）", "错因陷阱": "(−3)^2 写 −9（奇偶错）、18 ÷ (−3) 写 6（符号错）、18 − (−6) 写 12（去括号变号错）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——三级运算完整链"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：20 − 4 × 5。",
            "expected_answer": "0",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "混合运算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先算乘法：4 × 5 = 20", "再算减法：20 − 20 = 0", "结果：0"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "顺序检测（先乘后减，'混合运算'）", "难度理由": "easy 检测——单顺序陷阱（答 80 即先减后乘中招）", "认知阶梯定位": "L2 检测", "错因陷阱": "写 80（先算 20 − 4，'运算顺序错'节点 #1 错因）", "教学角色": "检测易档——顺序规则快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：−2^2 + (−3) × (−4) − (−1)^3。",
            "expected_answer": "9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含乘方",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先算乘方：−2^2 = −4（底数是 2，负号在外面）；(−1)^3 = −1", "再算乘除：(−3) × (−4) = 12", "最后算加减：−4 + 12 − (−1) = −4 + 12 + 1 = 9", "结果：9"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘方 + 乘除 + 去括号的完整链（'含乘方'，含 −2^2 头号陷阱）", "难度理由": "hard 名副其实——三陷阱叠加：−2^2 当 4（乘方迷思）、(−3)×(−4) 符号、−(−1)^3 去括号变号，任一处错即全错", "认知阶梯定位": "L3 检测 hard——混合运算 + 乘方迷思的综合硬检", "错因陷阱": "−2^2 当 4、(−1)^3 当 1（奇偶错）、−4 + 12 − (−1) 去括号错", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "把 15 − 6 ÷ 2 × 3 的运算顺序标出来，再写出结果。",
            "expected_answer": "先算 6 ÷ 2 = 3（乘除同级从左到右），再算 3 × 3 = 9，最后 15 − 9 = 6",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "混合运算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["乘除同级：从左到右先算 6 ÷ 2 = 3", "再算 3 × 3 = 9（同一级内继续从左到右）", "最后算加减：15 − 9 = 6", "结果：6"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "标运算顺序（同级左到右，'混合运算'，mastery'步骤清楚不靠心算乱跳'取证）", "难度理由": "medium 复测——必须显式标出顺序（同级左到右是最高频顺序错误点），防'会背不会用'", "认知阶梯定位": "L3 复测", "错因陷阱": "先算 2 × 3 再 6 ÷ 6 = 1（同级顺序错，'同级从左到右丢步'）、跳步（process_habit）", "教学角色": "防'会背不会用'复测——顺序外显化取证题"},
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：(−2)^2 ÷ (−4) × 3 + 1/2。",
            "expected_answer": "−5/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数小数混合",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先算乘方：(−2)^2 = 4", "乘除同级从左到右：4 ÷ (−4) = −1；−1 × 3 = −3", "再算加减：−3 + 1/2 = −6/2 + 1/2 = −5/2", "结果：−5/2"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "乘方 + 同级左到右 + 分数加（'分数小数混合'×'含乘方'）", "难度理由": "hard——五步运算：乘方符号、除法符号（4÷(−4)=−1）、同级左到右（先 ÷ 后 ×）、分数通分（−3+1/2），多陷阱叠加", "认知阶梯定位": "L4 复测——完整顺序链复测，防'会背不会用'", "错因陷阱": "(−2)^2 写 −4、4 ÷ (−4) 写 1（符号错）、−1 × 3 写 4（顺序错）、−3 + 1/2 通分错", "教学角色": "复测 hard 档——'先乘方再乘除后加减'全链取证"},
        },
        {
            "slot": "B5-I1",
            "prompt": "口算下面各题：①2 + 3 × 4　②(−6) ÷ 3 + 1　③2^3 − 3",
            "expected_answer": "① 14　② −1　③ 5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "混合运算",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["① 先乘后加：2 + 12 = 14", "② 先除后加：(−6) ÷ 3 = −2，−2 + 1 = −1", "③ 先乘方后减：2^3 = 8，8 − 3 = 5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三题口算快速诊断（顺序 / 符号 / 乘方混合各一，diagnostic probe'6 题混合运算'素材，'混合运算'）", "难度理由": "easy 诊断——三小题各测一个顺序层次", "认知阶梯定位": "L1 诊断——快速分档", "错因陷阱": "① 写 20（先加后乘）、② 写 −3（异号除符号错）、③ 写 3（指数当乘数）", "教学角色": "诊断题——顺序 / 符号 / 乘方一键分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "计算：6 + (−4) × 2，并把运算顺序写在过程里。",
            "expected_answer": "−2",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "混合运算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["顺序：先乘除，后加减", "先算乘法：(−4) × 2 = −8", "再算加法：6 + (−8) = −2", "结果：−2"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "计算 + 写出运算顺序（值 + 过程双输出，mastery'步骤清楚'取证，diagnostic probe 素材，'混合运算'）", "难度理由": "medium 诊断——值 + 顺序双输出，直接区分'会算'与'步骤清楚'两档", "认知阶梯定位": "L2 诊断", "错因陷阱": "只写答案不标顺序（'跳步'，process_habit）、(−4) × 2 符号错（写 8）、6 + (−8) 写 14（异号相加错）", "教学角色": "诊断题——mastery'步骤清楚，不靠心算乱跳'的取证题"},
        },
    ],
    # ===== M-G7-SCI-NOTATION-APPROX 科学记数法与近似数（概念+计算混合：4 verified + 11 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="科学记数法是把很大或很小的数写成a×10ⁿ，近似数要看精确到哪一位"；
    # seed=科学记数法表示/还原原数/近似数与精确度/有效数字意识；
    # common_mistakes=a不在1到10之间/10的指数数错/近似到哪一位看错/四舍五入后位数不规范；
    # diagnostic_probes=3个大数小数写成科学记数法、2题判断近似数精确度。
    # authoring 原则（琢玉教训）：L1 真识别（判断形式/规则而非直接写）；hard 真难（指数理解、
    # 迁移还原×精确度、有效数字综合）；还原方向机算题由 sympy 门禁真验算，指数与位数关系
    # 内嵌进'计算：a×10^n'（还原）与'混合后科学记数法表示'（迁移）。
    "M-G7-SCI-NOTATION-APPROX": [
        {
            "slot": "B1-I0",
            "prompt": "我国 2020 年人口普查总人口约 1412000000 人。把它写成科学记数法 a×10^n 的形式，a 是多少？n 是多少？",
            "expected_answer": "a = 1.412，n = 9",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["科学记数法要求 1 ≤ a < 10，a 是一位整数加小数的数", "1412000000 的小数点向左移 9 位变 1.412 → a = 1.412", "小数点移动了几位，n 就是几 → n = 9", "1412000000 = 1.412 × 10^9"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "把大数写成科学记数法（a 的范围 + 指数 = 小数点移动位数，'科学记数法表示'）", "难度理由": "medium 锚点——a 与 n 双输出，演示本质而非背口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'a 控制在 1≤a<10、指数就是小数点移动的位数'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个数是科学记数法？（　）\nA. 12 × 10^4\nB. 3.5 × 10^6\nC. 0.8 × 10^5\nD. 3.5 × 6",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["科学记数法的形式是 a × 10^n，且 1 ≤ a < 10", "A 的 a = 12 超过 10、C 的 a = 0.8 小于 1、D 不是乘 10 的幂", "只有 B 的 a = 3.5 满足 1 ≤ a < 10，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别科学记数法的形式（a×10^n 且 1≤a<10，'科学记数法表示'）", "难度理由": "easy——规则识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断形式而非直接写）", "错因陷阱": "A（a = 12 超范围——节点 #1 错因'a 不在 1 到 10 之间'的正面陷阱）、C（a 小于 1）", "教学角色": "L1 识别脚手架——头号错因的形式层探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "科学记数法 a × 10^n 中，a 必须满足（　）\nA. 1 ≤ a < 10\nB. 0 < a < 10\nC. a 是整数\nD. a ≥ 1",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["科学记数法要求 a 是一位整数带小数的数", "即 1 ≤ a < 10（最小到 1，最大不到 10）", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "科学记数法 a 的范围规则（1≤a<10，'科学记数法表示'）", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别", "错因陷阱": "选 D（忘 a < 10 上界，会把 12×10^4 当合法——节点 #1 错因）、选 B（把 0.5 也当合法）", "教学角色": "L1 识别——与 B1-I1 互补（一处认形式、一处记规则）"},
        },
        {
            "slot": "B2-I0",
            "prompt": "3.2 × 10^4 还原成普通写法是多少？计算：3.2 × 10^4，写出结果。",
            "expected_answer": "32000",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "还原原数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["10^4 = 10000（指数 4 → 小数点向右移 4 位）", "3.2 × 10000 = 32000（或小数点右移 4 位：3.2 → 32000）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "由科学记数法还原原数（指数 = 小数点右移位数，'还原原数'）", "难度理由": "easy 套用——单步乘 10 的幂", "认知阶梯定位": "L2 套用", "错因陷阱": "320 或 320000（小数点移动位数错——节点 #2 错因'10 的指数数错'）", "教学角色": "还原方向的标准套用，mastery'能说清指数表示小数点移动几位'的取证题"},
        },
        {
            "slot": "B2-I1",
            "prompt": "把 20400000 写成科学记数法，并说明 n 是怎么来的。",
            "expected_answer": "2.04 × 10^7（n = 7：小数点从末尾向左移到 2 的后面，移动了 7 位）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先找 a：把小数点放在 2 的后面 → 2.04（1 ≤ 2.04 < 10）", "再数移动位数：20400000 的小数点向左移 7 位到 2 的后面 → n = 7", "20400000 = 2.04 × 10^7"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "大数写科学记数法 + 解释指数来源（'科学记数法表示'，mastery'能说清指数表示小数点移动几位'）", "难度理由": "medium——需自己定位小数点并数移动位数，中间 0 是干扰", "认知阶梯定位": "L2 套用", "错因陷阱": "写成 2.4 × 10^7（丢中间 0）、n 写成 6（位数数错——节点 #2 错因'10 的指数数错'）", "教学角色": "大数表示的标准套用——中间 0 是'还原原数'错因的镜像探针"},
        },
        {
            "slot": "B2-I2",
            "prompt": "把 0.00012 写成科学记数法。",
            "expected_answer": "1.2 × 10^−4",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把小数点移到 1 的后面 → a = 1.2", "小数点向右移了 4 位 → 原数小于 1，指数为负 → n = −4", "0.00012 = 1.2 × 10^−4"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "小数写科学记数法（负指数，'科学记数法表示'）", "难度理由": "medium——负指数方向反直觉", "认知阶梯定位": "L3 变式（从大数转入小数，指数符号反转）", "错因陷阱": "n 写成 +4（指数符号反）、a 写成 12（小数点位置错——节点 #1 错因）", "教学角色": "小数表示核心变式——负指数认知点"},
        },
        {
            "slot": "B3-I0",
            "prompt": "把 4.995 精确到百分位（保留两位小数），结果是 5.00 还是 5？说说你的理由。",
            "expected_answer": "5.00。4.995 的千分位是 5，向百分位进 1：4.99 + 0.01 = 5.00；精确到百分位要保留两位小数，写 5 只精确到个位，不规范",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "近似数与精确度",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["找目标数位：精确到百分位 → 看百分位 9 的下一位千分位", "千分位是 5，满 5 进 1 → 4.99 的百分位 9 加 1 进位 → 5.00", "精确到百分位必须保留两位小数 → 写 5.00，不能写 5"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "四舍五入 + 精确度的书写规范（'近似数与精确度'，mastery'能判断近似数精确度'）", "难度理由": "medium——进位 + 尾零书写双陷阱", "认知阶梯定位": "L3 变式（近似数 + 追问理由）", "错因陷阱": "写 5（丢尾零——节点 #4 错因'四舍五入后位数不规范'）、4.99 不进位", "教学角色": "近似数精确度的核心变式——'位数不规范'错因的定点探针"},
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：4 × 10^4 + 3 × 10^3，结果用科学记数法表示。",
            "expected_answer": "4.3 × 10^4",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "科学记数法表示",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先还原：4 × 10^4 = 40000，3 × 10^3 = 3000", "相加：40000 + 3000 = 43000", "再写成科学记数法：43000 = 4.3 × 10^4（不能直接 4 + 3 = 7 得 7 × 10^4，指数不同不能加系数）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "科学记数法与有理数运算混合（还原 → 相加 → 再表示，'还原原数'×'科学记数法表示'）", "难度理由": "hard 名副其实——两步还原 + 求和 + 指数再定位，头号陷阱'直接 4+3=7 得 7×10^4'是'指数数错'的深层形态", "认知阶梯定位": "L4 迁移——乘方（前置）× 科学记数法混合", "错因陷阱": "7 × 10^4（指数不同的数不能直接加系数）、43000 忘再表示", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "近似数 3.20 × 10^4 精确到哪一位？说明理由。",
            "expected_answer": "精确到百位。3.20 × 10^4 = 32000，3.20 的最后一位 0 在 32000 中处于百位（3 在万位、2 在千位、0 在百位），所以精确到百位，不是百分位",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "近似数与精确度",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先还原：3.20 × 10^4 = 32000", "看 3.20 最后一位 0 在 32000 中的位置：从右往左个、十、百、千、万 → 0 在百位", "精确到百位（不能说精确到百分位！）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "科学记数法形式近似数的精确度判断（还原后看最后一位位置，'近似数与精确度'×'还原原数'）", "难度理由": "hard——需先还原再定位，'精确到百分位'是强干扰（节点 #3 错因'近似到哪一位看错'的迁移形态）", "认知阶梯定位": "L4 迁移——还原 × 精确度双知识混合", "错因陷阱": "答'百分位'（把 a 的小数位当精确度——节点 #3 错因）、32000 还原错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：2.5 × 10^3，并把结果用普通写法写出来。",
            "expected_answer": "2500",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "还原原数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["10^3 = 1000", "2.5 × 1000 = 2500（小数点右移 3 位：2.5 → 2500）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "还原原数快速检测（'还原原数'）", "难度理由": "easy 检测——单步", "认知阶梯定位": "L2 检测", "错因陷阱": "250（位数差一）或 25000（多一位——节点 #2 错因'10 的指数数错'）", "教学角色": "掌握档快速检测——还原方向探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下列写法正确的是（　）\nA. 34000 = 34 × 10^3\nB. 0.0005 = 5 × 10^−4\nC. 12.5 × 10^5 是科学记数法\nD. 6 × 10^2 = 60000",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A 错：34 不在 1 ≤ a < 10 范围（应写 3.4 × 10^4）", "B 对：0.0005 小数点向右移 4 位 → 5 × 10^−4", "C 错：12.5 的 a 超过 10，不是科学记数法", "D 错：6 × 10^2 = 600，不是 60000", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "四项判断（a 范围 / 负指数 / 还原，'科学记数法表示'×'还原原数'）", "难度理由": "hard——四条都要逐一核查，A/C 是 a 范围错因的两个变体、D 是还原错", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "选 A/C（节点 #1 错因'a 不在 1 到 10 之间'）、选 D（指数算错——节点 #2 错因'10 的指数数错'）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "用四舍五入法把 0.0586 精确到千分位。",
            "expected_answer": "0.059",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "近似数与精确度",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["千分位是小数点后第三位：0.0586 的千分位是 8", "看千分位的下一位万分位：6，满 5 进 1", "8 + 1 = 9 → 0.059"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "四舍五入取近似数（精确到千分位，'近似数与精确度'）", "难度理由": "medium 复测——需先认清千分位再进位", "认知阶梯定位": "L3 复测", "错因陷阱": "0.058（忘进位）、0.06（进位后位数不规范——节点 #4 错因）", "教学角色": "防'会背不会用'复测——四舍五入流程外显取证"},
        },
        {
            "slot": "B5-I0",
            "prompt": "下列各近似数各有几个有效数字？\n①0.0305　②3.20　③5.6 × 10^3",
            "expected_answer": "① 3 个（3、0、5）　② 3 个（3、2、0）　③ 2 个（5、6）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "有效数字意识",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["有效数字：从左边第一个非零数字起，到末位止的所有数字", "① 0.0305：前导 0 不算，从 3 开始 → 3、0、5 共 3 个（中间 0 算）", "② 3.20：3、2、0 共 3 个（末尾 0 算，表示精确到百分位）", "③ 5.6 × 10^3：只看 a 部分 5.6 → 5、6 共 2 个（10 的幂不算有效数字）"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "有效数字判断（前导零不算、中间零算、科学记数法只看 a，'有效数字意识'）", "难度理由": "hard 名副其实——三题覆盖三个易错规则，且 ③ 需理解 10^n 不占有效数字", "认知阶梯定位": "L4 复测——有效数字综合防'会背不会用'", "错因陷阱": "① 数成 4 个（前导零误算）、② 数成 2 个（末尾零丢）、③ 数成 5 个（把 10^3 也算进去）", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "把 450000 用科学记数法表示，正确的是（　）\nA. 45 × 10^4\nB. 4.5 × 10^5\nC. 0.45 × 10^6\nD. 4.5 × 10^6",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "科学记数法表示",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["a 必须满足 1 ≤ a < 10", "450000 小数点向左移 5 位 → 4.5，n = 5", "450000 = 4.5 × 10^5，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "a 范围 + 指数诊断（'科学记数法表示'，diagnostic probe'3 个大数写成科学记数法'素材）", "难度理由": "easy 诊断——单题分档", "认知阶梯定位": "L1 诊断", "错因陷阱": "选 A（a = 45 超范围——节点 #1 错因）、选 C（a = 0.45 小于 1）、选 D（指数多一——节点 #2 错因）", "教学角色": "诊断题——a 范围与指数两个错因一键分档"},
        },
        {
            "slot": "B5-I2",
            "prompt": "计算：5 × 10^−2，并把结果用小数写出来。",
            "expected_answer": "0.05",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "还原原数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["指数 −2 → 小数点向左移 2 位", "5 → 0.05（移动 2 位要在 5 前面补一个 0）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负指数还原（小数点左移，'还原原数'，diagnostic probe 素材）", "难度理由": "medium 诊断——负指数 + 补位", "认知阶梯定位": "L2 诊断", "错因陷阱": "0.5（只移 1 位）、50（方向反，把 −2 当 +2）", "教学角色": "诊断题——负指数方向与补位错因的定点探针"},
        },
    ],
    # ===== M-G7-ALG-EXPR 代数式（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="代数式是用数字、字母和运算符号表达数量关系"；
    # seed=文字语言写代数式/代数式表示实际意义/规范书写；
    # common_mistakes=数量关系反写/单位量和总量混淆/乘号省略不规范；
    # diagnostic_probes=5道文字转代数式，含多/少/倍/平均。
    # authoring 原则（琢玉教训）：L1 真识别（判断书写规范/规则而非直接列式）；hard 真难
    # （折扣多对象、图形规律、年龄双时间点）；迁移与'用字母表示数'（小学前置 LETTER-EXPR）
    # 混合；每题经概念判断，无算术冒充（本节点无机算题，全部 unverifiable）。
    "M-G7-ALG-EXPR": [
        {
            "slot": "B1-I0",
            "prompt": "小明的年龄是 a 岁，爸爸的年龄比小明的 2 倍还多 3 岁。爸爸的年龄用代数式怎样表示？",
            "expected_answer": "2a + 3（岁）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先翻译'小明的 2 倍'：a 的 2 倍 = 2a", "再'还多 3 岁'：2a + 3", "检验：a = 10 时 2 × 10 + 3 = 23（岁），合理"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "文字关系翻译成代数式（倍 + 多两步，'文字语言写代数式'）", "难度理由": "medium 锚点——两步关系演示'文字 → 式子'", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；solution_steps 内置检验步示范自查习惯）", "教学角色": "讲本质用——'先用自然语言说关系，再符号化'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个式子书写规范？（　）\nA. a3\nB. 3 × a\nC. 3a\nD. 3·a·1",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "规范书写",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["数字与字母相乘：数字写在前面、乘号省略", "A 把字母写前面（a3 不规范）、B 保留乘号（不规范）、D 系数 1 冗余（3·a·1 = 3a）", "只有 C 的 3a 规范，选 C"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别代数式规范书写（数字在前、乘号省略，'规范书写'）", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "选 A（'a × 3 写成 a3'——节点 #3 错因'乘号省略不规范'的正面陷阱）、选 B（保留乘号）", "教学角色": "L1 识别脚手架——书写规范规则探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "小明把'x 除以 3'写成 x ÷ 3，把'a × 4'写成 a4。下列说法正确的是（　）\nA. 两种写法都规范\nB. x ÷ 3 应写成 x/3（分数线），a4 不规范应写成 4a\nC. a4 规范，x ÷ 3 不规范\nD. 两种写法都不规范，都应保留乘号和除号",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "规范书写",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["除法写成分数线：x ÷ 3 = x/3", "数字与字母相乘省略乘号且数字在前：a × 4 = 4a（不是 a4）", "两种写法都有规范形式，选 B"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "判断书写规范（除法分数线 + 数字在前，'规范书写'）", "难度理由": "easy——两条规范判断", "认知阶梯定位": "L1 识别（判断对错）", "错因陷阱": "选 A（保留 ÷ 和 a4 都接受——节点 #3 错因'乘号省略不规范'与'除法没写成分数线'）", "教学角色": "L1 识别——书写规范纠错脚手架"},
        },
        {
            "slot": "B2-I0",
            "prompt": "每本笔记本 x 元，买 3 本一共需要多少元？",
            "expected_answer": "3x（元）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["单价 × 数量 = 总价：x × 3", "规范书写：数字在前省略乘号 → 3x 元"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "单价×数量列式（'文字语言写代数式'）", "难度理由": "easy 套用——单步关系", "认知阶梯定位": "L2 套用", "错因陷阱": "写成 x3（乘号省略不规范——节点 #3 错因）", "教学角色": "L2 套用脚手架"},
        },
        {
            "slot": "B2-I1",
            "prompt": "一支钢笔 a 元，一支铅笔比钢笔便宜 b 元。买一支钢笔和一支铅笔一共要多少元？",
            "expected_answer": "2a − b（元）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["铅笔价格 = 钢笔价 − b = a − b", "一共 = 钢笔 a + 铅笔 (a − b) = a + a − b = 2a − b", "检验：a = 5、b = 1 时 2 × 5 − 1 = 9（钢笔 5 + 铅笔 4 = 9）✓"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两步和差关系列式（先算铅笔价再求和，'文字语言写代数式'）", "难度理由": "medium——两步关系 + 字母合并（a + a = 2a，'用字母表示数'前置）", "认知阶梯定位": "L2 套用", "错因陷阱": "只写 a − b（漏钢笔价——'单位量和总量混淆'错因）、写 a + b（'便宜'反写成加——'数量关系反写'错因）", "教学角色": "和差关系标准套用——反写与漏总量的定点探针"},
        },
        {
            "slot": "B2-I2",
            "prompt": "'m 与 n 的差的 3 倍'用代数式表示，正确的是（　）\nA. m − 3n\nB. 3m − n\nC. 3(m − n)\nD. m − n − 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'m 与 n 的差'先写成 m − n", "'的 3 倍'再乘 3 → 3(m − n)，括号不能丢", "选 C"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "差与倍的组合（先差后倍需括号，'文字语言写代数式'）", "难度理由": "medium——运算顺序决定括号位置", "认知阶梯定位": "L3 变式（组合关系 + 选项辨析）", "错因陷阱": "选 A/B（把 3 只乘一个量——括号丢失/关系拆分，节点'数量关系反写'错因）", "教学角色": "括号必要性变式——'先算的部分要加括号'规则示范"},
        },
        {
            "slot": "B3-I0",
            "prompt": "代数式 x/2 + 5 可以表示下面哪个情境？（　）\nA. x 的一半与 5 的和\nB. x 与 2 的和再乘 5\nC. x 的 2 倍加 5\nD. x 除以 5 加 2",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "代数式表示实际意义",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["x/2 表示 x 的一半（分数线 = 除法）", "x/2 + 5 = x 的一半与 5 的和", "B 是 (x + 2) × 5、C 是 2x + 5、D 是 x/5 + 2 → 选 A"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "由代数式反说实际意义（'代数式表示实际意义'，分数线含义）", "难度理由": "medium——逆向翻译 + 分数线含义", "认知阶梯定位": "L3 变式（方向反转：式 → 文字）", "错因陷阱": "把 x/2 读成 x 的 2 倍（除法含义混淆）、选 B（运算顺序错）", "教学角色": "逆向翻译变式——与 B1-I0（文字 → 式）方向互补"},
        },
        {
            "slot": "B3-I1",
            "prompt": "商场促销：一件原价 m 元的衣服打八折出售，再减 5 元；一条原价 n 元的裤子打七折。买这两件一共要花多少元？（用代数式表示）",
            "expected_answer": "0.8m − 5 + 0.7n（元）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["打八折 = 原价 × 0.8 → 衣服 0.8m", "再减 5 元 → 衣服实付 0.8m − 5", "打七折 → 裤子 0.7n", "一共 = 0.8m − 5 + 0.7n（检验：m = 100、n = 200 时 80 − 5 + 140 = 215 元）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "折扣情境两步列式（小数系数 + 减法 + 多对象，'文字语言写代数式'×'用字母表示数'）", "难度理由": "hard——折扣含义 + 小数系数 + 减价与两对象叠加，多项关系易漏", "认知阶梯定位": "L4 迁移——用字母表示数（小学前置）的情境迁移", "错因陷阱": "漏减 5 或漏 0.7n（漏总量——'单位量和总量混淆'）、写 0.8 − 5m（关系乱序——'数量关系反写'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "用火柴棒摆三角形：摆 1 个三角形要 3 根火柴棒，摆 2 个要 5 根，摆 3 个要 7 根。摆 n 个三角形要多少根火柴棒？",
            "expected_answer": "2n + 1（根）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["找规律：3、5、7 → 每次多 2 根", "第 n 个 = 3 + 2(n − 1) = 2n + 1", "检验：n = 3 时 2 × 3 + 1 = 7 ✓"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "图形规律 → 代数式（数列规律符号化，'文字语言写代数式'×'用字母表示数'）", "难度理由": "hard——先找规律再符号化，抽象两步", "认知阶梯定位": "L4 迁移——'字母表达一类情况'（小学前置 LETTER-EXPR）的迁移", "错因陷阱": "写 3n（把'每次多 2'当成'每个 3'——规律误读）、写 2n（漏初始的 1）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "x 的 3 倍与 y 的差，用代数式表示是（　）\nA. 3x − y\nB. 3(x − y)\nC. x − 3y\nD. 3x + y",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'x 的 3 倍'→ 3x", "'与 y 的差'→ 减去 y → 3x − y", "选 A"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "倍与差列式快速检测（'文字语言写代数式'）", "难度理由": "easy 检测——单层关系", "认知阶梯定位": "L2 检测", "错因陷阱": "选 C（'3 倍'放错位置——'数量关系反写'）、选 B（误加括号）", "教学角色": "掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下列书写规范的是（　）\nA. a × 5 写成 a5\nB. 1 × x 写成 1x\nC. x ÷ 4 写成 x ÷ 4\nD. (a + b) × 2 写成 2(a + b)",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "规范书写",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A 错：数字与字母相乘数字在前 → 应写 5a", "B 错：系数 1 与字母相乘应省略 → 写 x，不是 1x", "C 错：除法写成分数线 → 应写 x/4", "D 对：数字在前、省略乘号、括号保留 → 2(a + b) 规范", "选 D"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "规范书写四项判断（数字在前 / 系数 1 省略 / 分数线 / 括号保留，'规范书写'，mastery'书写规范'取证）", "难度理由": "hard——四条规范逐一核查，B/C 是高频书写错误", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "选 B（把 1x 当规范——'乘号省略不规范'变体）、选 C（除法保留 ÷）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "把下面的式子改写成规范写法：\n①a × 3　②x ÷ 5　③b × 1　④m × n × 2",
            "expected_answer": "① 3a　② x/5　③ b　④ 2mn",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "规范书写",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["① 数字在前省略乘号 → 3a", "② 除法写成分数线 → x/5", "③ 系数 1 省略 → b（不是 1b）", "④ 数字在前、字母按顺序省略乘号 → 2mn"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "规范书写综合改写（数字在前 / 分数线 / 系数 1 / 多字母，'规范书写'，mastery'书写规范'取证）", "难度理由": "medium 复测——四式覆盖全部书写规范，防'会背不会用'", "认知阶梯定位": "L3 复测", "错因陷阱": "① 写 a3、③ 写 1b（系数 1 不省略）、④ 写 2m·n 或 m2n", "教学角色": "防'会背不会用'复测——书写规范全项取证"},
        },
        {
            "slot": "B5-I0",
            "prompt": "今年小明 x 岁，爷爷的年龄比小明的 4 倍少 5 岁。5 年后，小明和爷爷的年龄各是多少岁？（用代数式表示）",
            "expected_answer": "小明 5 年后：x + 5（岁）；爷爷今年：4x − 5（岁），5 年后：4x（岁）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["爷爷今年 = 4x − 5", "小明 5 年后 = x + 5", "爷爷 5 年后 = 4x − 5 + 5 = 4x", "检验：x = 10 时爷爷今年 35、5 年后 40，小明 15，40 = 4 × 10 ✓"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "年龄情境两步列式（今年 → 5 年后，'文字语言写代数式'×'数量关系'）", "难度理由": "hard——两个对象 × 两个时间点，'4 倍少 5'与'+5'抵消是隐蔽点", "认知阶梯定位": "L4 复测——复杂关系防'会背不会用'", "错因陷阱": "爷爷 5 年后写 4x − 5（忘 +5）、小明 5 年后写 5x（'5 年后'误解为乘 5——'数量关系反写'变体）", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "n 表示一个数，'n 的 2 倍与 3 的和'用代数式表示是（　）\nA. 2n + 3\nB. 2(n + 3)\nC. n + 6\nD. 3n + 2",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'n 的 2 倍'→ 2n", "'与 3 的和'→ 加 3 → 2n + 3", "选 A"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "倍与和列式快速诊断（'文字语言写代数式'，diagnostic probe'5 道文字转代数式'素材）", "难度理由": "easy 诊断——单题分档", "认知阶梯定位": "L1 诊断", "错因陷阱": "选 B（'和'先算——运算顺序反）、选 D（倍与和位置互换——'数量关系反写'）", "教学角色": "诊断题——关系反写错因定点探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "把 m 个苹果平均分给 4 个小朋友，每人分得多少个？",
            "expected_answer": "m/4（个）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "文字语言写代数式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["平均分用除法：m ÷ 4", "规范书写：除法写成分数线 → m/4", "检验：m = 12 时 12 ÷ 4 = 3 ✓"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "平均分列式（除法 → 分数线，'文字语言写代数式'，diagnostic probe'含平均'素材）", "难度理由": "medium 诊断——'平均分'关系的符号化", "认知阶梯定位": "L2 诊断", "错因陷阱": "写 4m（'平均分'误用乘法——关系反写）、写 m ÷ 4（保留除号——书写不规范）", "教学角色": "诊断题——平均分关系 + 分数线书写双探针"},
        },
    ],
    # ===== M-G7-EXPR-VALUE 代数式求值（计算向：4 verified + 11 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="求值就是把字母换成给定数字，再按运算规则计算"；
    # seed=直接代入/含负数代入/含分数代入；
    # common_mistakes=负数代入不加括号/运算顺序错/把字母值抄错；
    # diagnostic_probes=4题代入求值，至少2题含负数。
    # authoring 原则（琢玉教训）：代入判断（含负数加括号）本质不可机算 → unverifiable 为主；
    # verified 题取'代入后计算环节'（题干示范/给出代入结果，sympy 真验算值）——诚实声明于
    # design_rationale；hard 真难（双字母+乘方+符号叠加、先合并再代入迁移）；每题经概念判断。
    "M-G7-EXPR-VALUE": [
        {
            "slot": "B1-I0",
            "prompt": "当 x = 3 时，求 2x + 5 的值。请写出代入和计算的过程。",
            "expected_answer": "2x + 5 = 2 × 3 + 5 = 6 + 5 = 11",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "直接代入",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把 x = 3 代入：2x + 5 = 2 × 3 + 5（代入时先加括号更稳妥）", "先算乘法：2 × 3 = 6", "再算加法：6 + 5 = 11"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "直接代入求值（值 + 过程双输出，'直接代入'）", "难度理由": "medium 锚点——演示'替换 → 计算'两步本质", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；过程外显防'跳步'）", "教学角色": "讲本质用——'代入就是把字母换成数字，再按运算规则计算'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "求值时，把 x = −2 代入 x + 3，正确的做法是（　）\nA. 直接写 −2 + 3，不用管括号\nB. 先把负号丢掉，写 2 + 3\nC. 把负数加括号写成 (−2) + 3，再计算\nD. 写成 −(−2) + 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含负数代入",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["代入时字母被负数替换，先加括号最稳妥", "(−2) + 3 = 1", "A 结果虽然也对，但遇到乘方、乘除时'不加括号'必然出错；C 是规范习惯，选 C"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别负数代入的正确姿势（先加括号，'含负数代入'，mastery'负数代入会加括号'取证）", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "选 A（负号直接代入不加括号——节点 #1 错因'负数代入不加括号'）、选 D（双负号）", "教学角色": "L1 识别脚手架——头号错因的规则层探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "把 x = −2 代入 x² + 1，下面哪个写法是正确的？（　）\nA. −2² + 1\nB. (−2)² + 1\nC. 2² + 1\nD. (−2) + 1²",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含负数代入",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["字母被负数替换要加括号：x² = (−2)²（负号在括号内，表示整个 −2 平方）", "A 的 −2² 表示 2 的平方取负，结果是 −4，与 (−2)² = 4 不同", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别乘方中负数代入必须加括号（'含负数代入'，节点 #1 错因的直接形态）", "难度理由": "easy——单点判断", "认知阶梯定位": "L1 识别", "错因陷阱": "选 A（−2² = −4 vs (−2)² = 4——'负数代入不加括号'在乘方中的致命形态）", "教学角色": "L1 识别——乘方 × 负数代入的括号必要性示范"},
        },
        {
            "slot": "B2-I0",
            "prompt": "把 x = 5 代入 3x + 2，代入后得到算式 3 × 5 + 2。计算：3 × 5 + 2",
            "expected_answer": "17",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "直接代入",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先算乘法：3 × 5 = 15", "再算加法：15 + 2 = 17"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "代入后数值计算（先乘后加，'直接代入'的计算环节）", "难度理由": "easy 套用——单步计算", "认知阶梯定位": "L2 套用", "错因陷阱": "先加后乘得 21（运算顺序错——节点 #2 错因'运算顺序错'）", "教学角色": "L2 套用——求值计算环节的标准应用（代入环节由题干示范，与 B2-I2 起的整题代入互补）"},
        },
        {
            "slot": "B2-I1",
            "prompt": "把 x = −2 代入 3x − 1，正确写法是 3 × (−2) − 1。计算：3 × (−2) − 1",
            "expected_answer": "−7",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含负数代入",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘法：3 × (−2) = −6（异号得负）", "再算减法：−6 − 1 = −7"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含负数代入的计算（乘法符号 + 连续减号，'含负数代入'）", "难度理由": "medium——负号乘法与减号两步", "认知阶梯定位": "L2 套用（负数版本）", "错因陷阱": "3 × (−2) 写 6（符号错）、−6 − 1 写 −5（减法错）；题干示范'加括号'正确写法防节点 #1 错因", "教学角色": "含负数代入标准套用——'代入先加括号'习惯的正面示范"},
        },
        {
            "slot": "B2-I2",
            "prompt": "当 x = 1/2 时，求 4x + 3 的值。",
            "expected_answer": "5",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "含分数代入",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["代入：4x + 3 = 4 × 1/2 + 3", "4 × 1/2 = 2（4 和分母 2 约分）", "2 + 3 = 5"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分数代入求值（分数乘整数约分，'含分数代入'）", "难度理由": "medium——分数乘整数需约分", "认知阶梯定位": "L3 变式（从整数代入转入分数）", "错因陷阱": "4 × 1/2 写成 4.5 或 4/2 忘约分、把 x = 1/2 代入成 41/2（抄错——节点 #3 错因'把字母值抄错'）", "教学角色": "分数代入核心变式"},
        },
        {
            "slot": "B3-I0",
            "prompt": "当 x = −2 时，求 x² + 1 的值。",
            "expected_answer": "5",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "含负数代入",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["代入：x² = (−2)²（负数平方先加括号）", "(−2)² = 4", "4 + 1 = 5"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "负数代入乘方求值（(−2)² 加括号，'含负数代入'×乘方前置）", "难度理由": "medium——乘方括号陷阱", "认知阶梯定位": "L3 变式（负数 × 乘方叠加）", "错因陷阱": "写 −4 + 1 = −3（−2² 不加括号——节点 #1 错因的乘方形态）、把 x² 当 2x", "教学角色": "负数代入乘方的核心变式——括号必要性的实战题"},
        },
        {
            "slot": "B3-I1",
            "prompt": "当 a = −2，b = 3 时，求 a² − 2b 的值。",
            "expected_answer": "−2",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "含负数代入",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["代入：a² = (−2)² = 4，2b = 2 × 3 = 6", "4 − 6 = −2（即 4 + (−6)）", "注意 (−2)² 要加括号，不能写 −2²"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "双字母代入 + 乘方 + 乘法混合（'含负数代入'×有理数混合运算前置）", "难度理由": "hard——乘方、乘法、异号减法三陷阱叠加", "认知阶梯定位": "L4 迁移——有理数混合运算（前置）× 代入求值", "错因陷阱": "(−2)² 写 −4（不加括号）、2b 当 2 + 3 或 −2 × 3、4 − 6 符号错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "先合并再代入：当 x = −2 时，求 2x + x − 3 的值。",
            "expected_answer": "−9",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "直接代入",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先合并：2x + x = 3x（两个 x 加一个 x，'用字母表示数'的合并思想）", "原式 = 3x − 3", "代入 x = −2：3 × (−2) − 3 = −6 − 3 = −9", "直接代入检验：2×(−2) + (−2) − 3 = −4 − 2 − 3 = −9 ✓"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "先合并再代入（2x + x = 3x，'直接代入'×'用字母表示数'前置）", "难度理由": "hard——化简意识 + 负数代入两步，'先算后化简顺序错'错因的直接对应", "认知阶梯定位": "L4 迁移——'字母表示数'（小学前置）的合并思想 × 求值，为整式加减（解锁节点）铺路", "错因陷阱": "不合并直接算（−4 − 2 − 3 也对但考的是化简意识）、2x + x 写 2x²（概念错）、代入漏负号", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "当 x = 4 时，2x − 3 的值是（　）\nA. 5\nB. 11\nC. 8\nD. 1",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "直接代入",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["代入：2x − 3 = 2 × 4 − 3", "先算乘法：2 × 4 = 8", "再算减法：8 − 3 = 5，选 A"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "直接代入快速检测（'直接代入'）", "难度理由": "easy 检测——单步", "认知阶梯定位": "L2 检测", "错因陷阱": "选 C（忘减 3：只算 2 × 4 = 8）、选 D（只算 x − 3：忘乘 2）", "教学角色": "掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "当 x = −3 时，求 x² − 2x 的值。",
            "expected_answer": "15",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "含负数代入",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["代入：x² = (−3)² = 9，2x = 2 × (−3) = −6", "9 − (−6) = 9 + 6 = 15", "注意 (−3)² 加括号、减负数变加"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "负数代入乘方与乘法的组合检测（'含负数代入'，diagnostic probe'至少 2 题含负数'素材）", "难度理由": "hard——(−3)²、2×(−3)、9−(−6) 三处符号陷阱", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "−9 − 6 = −15（(−3)² 不加括号 + 减负号错）、9 − (−6) 写 3", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "把 x = −3 代入 x^2 − 1，正确写法是 (−3)^2 − 1。计算：(−3)^2 − 1",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含负数代入",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘方：(−3)² = 9（负号在括号内，结果为正）", "再算减法：9 − 1 = 8"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负数代入乘方的计算复测（'含负数代入'，mastery'负数代入会加括号'取证）", "难度理由": "medium 复测——乘方先算 + 括号", "认知阶梯定位": "L3 复测", "错因陷阱": "(−3)² 写 −9（不加括号或符号错——节点 #1 错因）、9 − 1 写 10", "教学角色": "防'会背不会用'复测——'代入先加括号'习惯的取证题"},
        },
        {
            "slot": "B5-I0",
            "prompt": "当 a = 1/2，b = −4 时，求 2a + b/2 的值。",
            "expected_answer": "−1",
            "answer_format": "decimal",
            "verification_intent": "unverifiable",
            "question_type": "含分数代入",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["代入：2a = 2 × 1/2 = 1，b/2 = −4 ÷ 2 = −2", "1 + (−2) = −1", "注意分数与负数同时代入"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "分数 + 负数双代入综合（'含分数代入'×'含负数代入'，diagnostic probe 素材）", "难度理由": "hard——两类特殊代入叠加 + 除法分数线", "认知阶梯定位": "L4 复测——防'会背不会用'", "错因陷阱": "2 × 1/2 写成 1/4（分数乘法错）、b/2 写成 2 ÷ (−4)（关系反写）、1 + (−2) 写 3（符号错）", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "当 x = 2 时，3x + 1 的值是（　）\nA. 7\nB. 6\nC. 9\nD. 8",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "直接代入",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["代入：3x + 1 = 3 × 2 + 1", "先算乘法：3 × 2 = 6", "6 + 1 = 7，选 A"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "直接代入快速诊断（'直接代入'，diagnostic probe 素材）", "难度理由": "easy 诊断——单步分档", "认知阶梯定位": "L1 诊断", "错因陷阱": "选 C（先加后乘：3 × (2 + 1) = 9——运算顺序错，节点 #2 错因）", "教学角色": "诊断题——运算顺序错因的一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "把 x = 1/2 代入 6x + 2，代入后得到算式 6 × 1/2 + 2。计算：6 × 1/2 + 2",
            "expected_answer": "5",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含分数代入",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算乘法：6 × 1/2 = 3（6 和 2 约分）", "再算加法：3 + 2 = 5"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数代入后的计算诊断（约分 + 顺序，'含分数代入'）", "难度理由": "medium 诊断——分数约分", "认知阶梯定位": "L2 诊断", "错因陷阱": "6 × 1/2 写 6.5 或 3/1（分数乘法错）、先加后乘 6 × (1/2 + 2)（顺序错——节点 #2 错因）", "教学角色": "诊断题——分数乘法与运算顺序双探针"},
        },
    ],
    # ===== M-G7-MONOMIAL 单项式（概念为主：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="单项式是数字和字母乘积组成的一项"；
    # seed=识别单项式/系数/次数；common_mistakes=系数符号漏掉/次数把系数也算进去/π当字母；
    # diagnostic_probes=给8个式子判断单项式并写系数次数；mastery=能准确识别系数和次数、负号不漏。
    # authoring 原则（琢玉教训）：全部经概念判断（识别/辨析/求系数次数），无算术冒充；
    # 系数/次数是概念读取而非算术运算，故全部 unverifiable（诚实声明，不拿半截提取充 verified）；
    # hard 真难（x/2 形式转化、隐含系数 1、乘方系数、6 式子综合）；同句式 ≤2；
    # 迁移与'用字母表示数'（LETTER-EXPR 小学前置）/代数式书写（ALG-EXPR 前置）混合。

    "M-G7-MONOMIAL": [
        {
            "slot": "B1-I0",
            "prompt": "单项式 3x²y 是'数字 3 与字母 x、y 的乘积'组成的一项。它的系数是多少？次数是多少？",
            "expected_answer": "系数是 3，次数是 3（字母 x 的指数 2 与字母 y 的指数 1 相加：2 + 1 = 3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["单项式中的数字因数叫系数：3x²y 的数字因数是 3", "次数是所有字母的指数和：x 的指数 2 + y 的指数 1 = 3（系数 3 的指数不参与）", "答案：系数 3，次数 3"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用'数字因数是系数、字母指数和是次数'求单项式的系数与次数（本质演示：单项式=数字×字母的乘积）", "难度理由": "medium 锚点——系数与次数双输出，演示本质而非背口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'先分清数字因数和字母部分'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个是单项式？（　）\nA. x + 1\nB. 3xy\nC. 2/x\nD. x + y",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别单项式",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["单项式是数字与字母的乘积组成的一项，不含加减", "A、D 都是几个单项式的和（多项式），不是单项式", "C 的分母含字母（2 ÷ x），不是单项式", "B 是 3 与 x、y 的乘积，是单项式，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别单项式（数字×字母的乘积；排除多项式与分母含字母式）", "难度理由": "easy——概念识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断属性而非计算）", "错因陷阱": "把多项式 x+1 当单项式、把分母含字母的 2/x 当单项式（'把多项式当单项式'错因）", "教学角色": "L1 识别脚手架，本节点最佳 L1"},
        },
        {
            "slot": "B1-I2",
            "prompt": "下列说法正确的是（　）\nA. 单独一个数 5 不是单项式\nB. 单独一个字母 a 不是单项式\nC. 单独一个数 5 和单独一个字母 a 都是单项式\nD. 只有'数字×字母'的式子才是单项式",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别单项式",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["单独一个数或字母也是单项式（可以看成系数×1）", "5 = 5×1 是单项式，a = 1×a 是单项式", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'单独的数或字母也是单项式'（外延完整性）", "难度理由": "easy——但直击'数/字母不是单项式'的常见迷思", "认知阶梯定位": "L1 识别（属性判断）", "错因陷阱": "把单独的数 5、单独的字母 a 排除在单项式之外", "教学角色": "概念边界识别题——补'单项式=一项'的完整外延"},
        },
        {
            "slot": "B2-I0",
            "prompt": "单项式 −7x 的系数是多少？",
            "expected_answer": "−7",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "系数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["系数是单项式中的数字因数", "−7x 的数字因数是 −7（负号属于系数）", "答案：−7"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "求含负号的单项式的系数（系数带符号）", "难度理由": "easy 套用——单步，但负号是唯一陷阱", "认知阶梯定位": "L2 套用", "错因陷阱": "系数漏符号写 7（节点 #1 错因'系数符号漏掉'）", "教学角色": "L2 套用脚手架——系数带符号的标准示范"},
        },
        {
            "slot": "B2-I1",
            "prompt": "单项式 2πr 的系数是（　）\nA. 2\nB. π\nC. 2π\nD. 2πr",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["π 是一个数（圆周率），不是字母", "2πr 的数字因数是 2π，字母部分是 r", "系数是 2π，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求含 π 的单项式的系数（π 是数不是字母）", "难度理由": "medium——π 的身份判断是隐藏一步", "认知阶梯定位": "L2 套用", "错因陷阱": "把 π 当字母（选 B 或 D），节点 #3 错因'π 当字母'", "教学角色": "π 系数的定点套用——破除'π 是字母'迷思"},
        },
        {
            "slot": "B2-I2",
            "prompt": "单项式 −1/2 x³y² 的次数是多少？",
            "expected_answer": "次数是 5（字母 x 的指数 3 加字母 y 的指数 2：3 + 2 = 5）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "次数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["次数是所有字母的指数和", "x 的指数是 3，y 的指数是 2", "3 + 2 = 5；系数 −1/2 的指数不参与", "答案：5"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求分数系数的单项式的次数（字母指数和，不含系数）", "难度理由": "medium——分数系数是干扰，需排除系数的指数", "认知阶梯定位": "L3 变式（分数系数干扰）", "错因陷阱": "把系数 −1/2 的指数算进次数、只看一个字母的指数（节点 #2 错因'次数把系数也算进去'）", "教学角色": "次数核心变式——'系数不参与次数'的取证题"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法正确的是（　）\nA. 单项式 −3x²y 的系数是 3\nB. 单项式 −3x²y 的次数是 2\nC. 单项式 −3x²y 的系数是 −3，次数是 3\nD. 单项式 −3x²y 的系数是 −3，次数是 5",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["系数带符号：−3x²y 的系数是 −3（不是 3）", "次数是字母指数和：x 的 2 + y 的 1 = 3（系数 3 不参与）", "A 漏负号、B 只数 x、D 把系数算进次数，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "系数与次数的双属性辨析（符号 + 字母指数和）", "难度理由": "medium——三个陷阱选项分别对应三个经典错法", "认知阶梯定位": "L3 变式（多陷阱辨析）", "错因陷阱": "漏负号（A）、次数只数一个字母（B）、把系数指数算进次数（D）——节点 #1/#2 错因集中", "教学角色": "L3 变式核心——系数次数双属性综合辨析"},
        },
        {
            "slot": "B3-I1",
            "prompt": "小明把'x 的一半'写成 x/2。x/2 是单项式吗？如果是，它的系数和次数各是多少？请说明理由。",
            "expected_answer": "是单项式。x/2 = 1/2 × x，可以看成数字 1/2 与字母 x 的乘积，所以是单项式；系数是 1/2，次数是 1（x 的指数是 1）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别单项式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["把除法形式转化为乘法：x/2 = 1/2 × x", "1/2 是数字因数（系数），x 是字母部分 → 是单项式", "系数 = 1/2，次数 = x 的指数 1", "常见错：看到除号就以为不是单项式"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "判断除法书写形式的式子是否为单项式（x/2 = 1/2·x 的转化）", "难度理由": "hard——需把'除以 2'转化为'乘 1/2'再判断，分数系数 + 形式转化 + 理由论证，多步且反直觉", "认知阶梯定位": "L4 迁移——代数式规范书写（ALG-EXPR 前置：除法写成分数线）× 单项式概念", "错因陷阱": "见除号以为不是单项式、系数把分母 2 当系数、次数把 2 算进去", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "用 n 个边长为 a 的小正方形拼成一排，组成一个长方形，面积是 na²。na² 是单项式吗？它的系数和次数各是多少？",
            "expected_answer": "是单项式。系数是 1（数字因数 1 省略不写，n 和 a 都是字母因数），次数是 3（n 的指数 1 + a 的指数 2）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["na² = 1 × n × a²，数字因数是 1（省略不写）", "字母部分 n 和 a²：n 的指数 1，a 的指数 2", "系数 = 1，次数 = 1 + 2 = 3", "常见错：把 n 当系数（n 是字母因数不是数字因数）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "情境中求单项式的系数与次数（隐含系数 1 + 双字母）", "难度理由": "hard——需从'拼图形面积'情境读出 na² 的结构，并识别省略的系数 1 与 n 的指数 1，多步且多陷阱", "认知阶梯定位": "L4 迁移——用字母表示数（LETTER-EXPR 小学前置）的情境建模 × 单项式属性", "错因陷阱": "把 n 当系数、漏 n 的指数 1、把 a 的指数当系数", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "单项式 5x³ 的系数和次数分别是（　）\nA. 系数 5，次数 3\nB. 系数 5，次数 1\nC. 系数 1，次数 3\nD. 系数 3，次数 5",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["系数是数字因数 5", "次数是字母指数和：x 的指数是 3", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "系数与次数的快速检测（数字因数 + 字母指数和）", "难度理由": "easy 检测——单步双属性", "认知阶梯定位": "L2 检测", "错因陷阱": "把指数 3 当系数（D）、次数漏看（B）", "教学角色": "检测易档——掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "单项式 −(2/3)²x³y 的系数和次数分别是（　）\nA. 系数 −2/3，次数 4\nB. 系数 −4/9，次数 4\nC. 系数 −4/9，次数 6\nD. 系数 −2/3，次数 6",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先算系数的乘方：−(2/3)² = −4/9（先平方再取负）", "系数是 −4/9（不是 −2/3）", "次数是字母指数和：x 的 3 + y 的 1 = 4（系数的指数 2 不参与）", "A 系数忘平方、C/D 把系数指数算进次数，选 B"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "乘方形式的系数 + 次数排除系数指数（综合检测）", "难度理由": "hard 名副其实——系数先算乘方（−4/9）、次数不含系数指数（4），三处可错且互为干扰", "认知阶梯定位": "L3 检测 hard——检测'系数带符号'与'次数不含系数'双属性", "错因陷阱": "系数忘平方（A/D）、次数把系数指数算进去（C/D，节点 #2 错因）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "单项式 −x²y 的系数是（　）\nA. −1\nB. 1\nC. −x\nD. 没有系数",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["系数是数字因数，−x²y 的数字因数是 −1（省略不写）", "字母 x、y 不是系数", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "求隐含系数 −1（负号 + 省略的 1）", "难度理由": "medium 复测——隐含系数是'会背不会用'的典型盲区", "认知阶梯定位": "L3 复测", "错因陷阱": "漏隐含系数写 1（B）、把字母当系数（C）、以为没有系数（D）", "教学角色": "防'会背不会用'复测——'系数 1 省略但负号保留'的取证题"},
        },
        {
            "slot": "B5-I0",
            "prompt": "下面 6 个式子中，单项式有哪些？请写出它们的系数和次数：\n5，−2x，x/3，a + b，πr²，2/x",
            "expected_answer": "单项式：5（系数 5，次数 0）、−2x（系数 −2，次数 1）、x/3（系数 1/3，次数 1）、πr²（系数 π，次数 2）。a + b 是多项式不是单项式；2/x 分母含字母，不是单项式",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别单项式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["逐式判断：5 是单独的数（单项式，次数 0）；−2x 是单项式（系数 −2，次数 1）", "x/3 = 1/3·x 是单项式（系数 1/3，次数 1）；πr² 是单项式（π 是数，系数 π，次数 2）", "a + b 是多项式；2/x 分母含字母，都不是单项式"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "6 式子综合判断单项式并写系数次数（含单独数/分数系数/π/分母含字母，diagnostic probe'给 8 个式子判断单项式并写系数次数'素材）", "难度理由": "hard 名副其实——6 式 ×（判断 + 系数 + 次数），含次数 0、分数系数、π、非单项式多重陷阱，需逐项核对", "认知阶梯定位": "L4 复测——全技能综合，防'会背不会用'", "错因陷阱": "5 的次数写 1（忘零次）、x/3 系数写 2、π 当字母、2/x 误判为单项式", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "下列各式中，不是单项式的是（　）\nA. 3\nB. ab\nC. −1/2 x\nD. x + 2",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别单项式",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["A 是单独的数（单项式），B 是字母乘积（单项式），C 是分数系数 × 字母（单项式）", "D 是 x 与 2 的和（多项式），不是单项式", "选 D"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "找出非单项式（诊断：单项式外延是否完整）", "难度理由": "easy 诊断——单题分档", "认知阶梯定位": "L1 诊断", "错因陷阱": "把多项式 x + 2 当单项式（'把多项式当单项式'错因）", "教学角色": "诊断题——单项式概念外延的一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "写出单项式 −3/4 ab² 的系数和次数。",
            "expected_answer": "系数是 −3/4，次数是 3（a 的指数 1 + b 的指数 2）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "系数与次数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["系数是数字因数 −3/4（负号属于系数）", "次数是字母指数和：a 的指数 1 + b 的指数 2 = 3", "答案：系数 −3/4，次数 3"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数系数的系数与次数诊断（负号 + 指数和）", "难度理由": "medium 诊断——负号与双字母指数是两处陷阱", "认知阶梯定位": "L2 诊断（diagnostic probe 素材）", "错因陷阱": "系数漏负号写 3/4、次数漏 a 的指数 1 写成 2", "教学角色": "诊断题——直接区分'会写系数'与'会数次数'两档"},
        },
    ],
    # ===== M-G7-POLYNOMIAL 多项式（概念向：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="多项式是几个单项式的和，每个部分叫一项"；
    # seed=识别项/次数/常数项/几次几项式；common_mistakes=减号后面项的符号漏掉/次数取错/常数项漏写符号；
    # diagnostic_probes=3个多项式写项、次数、常数项；mastery=能带符号分项、能判断多项式次数。
    # authoring 原则（琢玉教训）：全部经概念判断（分项/求次数/辨析/整式分类），无算术冒充；
    # hard 真难（由单项式构造多项式、整式概念链、3 多项式 × 3 属性、最高次项找错辨析）；同句式 ≤2；
    # 迁移与单项式（MONOMIAL 前置）/整式概念链混合。

    "M-G7-POLYNOMIAL": [
        {
            "slot": "B1-I0",
            "prompt": "多项式 3x² − 2x + 1 是三个单项式的和：3x²、−2x、1。它的项数是多少？常数项是什么？次数是多少？",
            "expected_answer": "项数是 3（3x²、−2x、1）；常数项是 1；次数是 2（最高次项 3x² 的次数是 2）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别项",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["多项式是几个单项式的和，每个单项式（带符号）就是一项", "3x²、−2x、1 共 3 项；不含字母的项 1 是常数项", "次数取最高次项的次数：3x² 是 2 次 → 多项式次数是 2"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "多项式的项数、常数项与次数（本质演示：多项式=几个单项式的和）", "难度理由": "medium 锚点——三项属性演示'符号跟着项走'与'次数取最高'", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'先用竖线分项，符号跟着项走'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "多项式 3x² − 2x + 1 的项是（　）\nA. 3x²、2x、1\nB. 3x²、−2x、1\nC. 3x²、−2x\nD. x²、x、1",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别项",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["多项式的项是带符号的单项式", "3x² − 2x + 1 = 3x² + (−2x) + 1，三项是 3x²、−2x、1", "A 漏了 −2x 的负号，C 漏常数项，D 丢系数，选 B"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别多项式的项（符号跟着项走）", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别正宗实现（判断分项是否正确）", "错因陷阱": "减号后面项的符号漏掉（A，节点 #1 错因'减号后面项的符号漏掉'）", "教学角色": "L1 识别脚手架——头号错因的规则层探针"},
        },
        {
            "slot": "B1-I2",
            "prompt": "多项式 2a − 5 中，常数项是（　）\nA. 2a\nB. −5\nC. 5\nD. a",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "常数项",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["常数项是不含字母的项，符号属于该项", "2a − 5 = 2a + (−5)，常数项是 −5", "选 B"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别常数项（带符号）", "难度理由": "easy——单点识别", "认知阶梯定位": "L1 识别", "错因陷阱": "常数项漏写符号（选 C，节点 #3 错因'常数项漏写符号'）", "教学角色": "常数项识别脚手架"},
        },
        {
            "slot": "B2-I0",
            "prompt": "把多项式 x³ − 4x + 7 按项分开，写出每一项（带符号）。",
            "expected_answer": "x³、−4x、7",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别项",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先看成和的形式：x³ + (−4x) + 7", "每一项带符号写出：x³、−4x、7", "注意 −4x 的负号不能丢"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "带符号分项（和的形式转化）", "难度理由": "easy 套用——单步分项", "认知阶梯定位": "L2 套用", "错因陷阱": "−4x 漏负号写成 4x（节点 #1 错因'减号后面项的符号漏掉'）", "教学角色": "L2 套用脚手架——'符号跟着项走'的标准示范"},
        },
        {
            "slot": "B2-I1",
            "prompt": "多项式 2x²y − 3xy + 5 的次数是多少？",
            "expected_answer": "次数是 3（最高次项 2x²y 的次数是 2 + 1 = 3；−3xy 的次数是 2，常数项 5 的次数是 0）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "次数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先看每项的次数：2x²y 是 2+1=3 次，−3xy 是 1+1=2 次，5 是 0 次", "多项式次数 = 最高次项的次数 = 3", "答案：3"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "多项式的次数（最高次项的次数）", "难度理由": "medium——三项次数都要算，再取最高", "认知阶梯定位": "L2 套用", "错因陷阱": "次数取错：取 −3xy 的 2、把常数项次数当最高（节点 #2 错因'次数取错'）", "教学角色": "多项式次数标准套用——'逐项算次数再取最高'示范"},
        },
        {
            "slot": "B2-I2",
            "prompt": "多项式 −x² + 2x − 1 是几次几项式？（　）\nA. 二次三项式\nB. 三次二项式\nC. 二次二项式\nD. 三次三项式",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "几次几项式",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["次数 = 最高次项 −x² 的次数 = 2 → 二次", "项数 = −x²、2x、−1 共 3 项 → 三项式", "合起来是二次三项式，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "判断'几次几项式'（次数 + 项数双属性）", "难度理由": "medium——次数与项数都要判，−1 是容易被漏的第三项", "认知阶梯定位": "L3 变式", "错因陷阱": "项数数错（漏 −1 成二项，节点 #1 错因变体）、次数取错", "教学角色": "几次几项式核心变式——'几项'必须带符号数"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法正确的是（　）\nA. 多项式 3x − 4 的常数项是 4\nB. 多项式 3x − 4 的常数项是 −4\nC. 多项式 3x − 4 的项是 3x、4\nD. 多项式 3x − 4 的次数是 0",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "常数项",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["3x − 4 = 3x + (−4)，常数项是 −4（负号属于常数项）", "项是 3x、−4（C 漏负号）", "次数是最高次项 3x 的次数 = 1（D 错）", "选 B"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "常数项带符号辨析 + 项/次数干扰", "难度理由": "medium——四个选项对应四个不同属性，需逐一核验", "认知阶梯定位": "L3 变式（多属性辨析）", "错因陷阱": "常数项漏写符号（A/C，节点 #3 错因）、把常数项次数当多项式次数（D）", "教学角色": "L3 变式核心——常数项符号与次数取值的综合辨析"},
        },
        {
            "slot": "B3-I1",
            "prompt": "一个多项式由单项式 3a²、−2ab 和常数项 4 组成（写成'和的形式'）。这个多项式怎么写？它是几次几项式？",
            "expected_answer": "3a² − 2ab + 4（写成 3a² + (−2ab) + 4 也可）；它是二次三项式（3a² 与 −2ab 的次数都是 2，项数 3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "几次几项式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["把三个单项式写成和：3a² + (−2ab) + 4，通常写成 3a² − 2ab + 4", "次数：3a² 是 2 次、−2ab 是 1+1=2 次、4 是 0 次，最高 2 → 二次", "项数 3 → 三项式，合起来二次三项式"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "由单项式构造多项式并判断几次几项式（整式概念链）", "难度理由": "hard——'和的形式'翻译成标准书写 + 逐项算次数取最高 + 数项数，多步", "认知阶梯定位": "L4 迁移——单项式（MONOMIAL 前置）× 多项式结构", "错因陷阱": "−2ab 的负号在'和的形式'中漏掉、次数把常数项 4 当最高、项数数错", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "单项式和多项式统称整式。下面 6 个式子中，属于整式的有哪些？\n3x，x + 1，5，2/x，x² − 1，π",
            "expected_answer": "整式：3x、x + 1、5、x² − 1、π（它们都是单项式或多项式）；2/x 分母含字母，既不是单项式也不是多项式，不是整式",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "整式判断",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["整式 = 单项式 ∪ 多项式", "3x、5、π 是单项式（π 是数）；x + 1、x² − 1 是多项式 → 都是整式", "2/x 分母含字母，不是单项式也不是多项式 → 不是整式"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "整式分类判断（单项式与多项式的并集，含 π 与分母含字母）", "难度理由": "hard——6 式子跨单项式/多项式/非整式三类，π 与 2/x 是两处陷阱", "认知阶梯定位": "L4 迁移——单项式（MONOMIAL 前置）× 整式概念链", "错因陷阱": "把 π 当字母排除出整式、把 2/x 当整式、漏 x + 1", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "多项式 −2x + 3y − 4 的项有（　）\nA. 2x、3y、4\nB. −2x、3y、−4\nC. −2x、3y、4\nD. 2x、−3y、−4",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别项",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["把多项式看成和：−2x + 3y + (−4)", "项是 −2x、3y、−4（符号跟着项走）", "选 B"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "带符号分项快速检测", "难度理由": "easy 检测——单步分项", "认知阶梯定位": "L2 检测", "错因陷阱": "减号后面项的符号漏掉（A/C，节点 #1 错因）", "教学角色": "检测易档——头号错因快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "关于多项式 3x²y − 2xy + 5，下列说法错误的是（　）\nA. 它的常数项是 5\nB. 它的项是 3x²y、−2xy、5\nC. 它是二次三项式\nD. 它的次数是 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "几次几项式",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A：常数项 5 ✓；B：项带符号 ✓", "次数：3x²y 是 2+1=3 次，−2xy 是 2 次，最高 3 → 三次（D 对）", "C 说二次是错的（最高次项 3x²y 是三次），选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "几次几项式与常数项/项的核验（找错误说法）", "难度理由": "hard——四项都要核验，'最高次项找错'（把 −2xy 当最高）是核心陷阱", "认知阶梯定位": "L3 检测 hard", "错因陷阱": "把 −2xy 的次数 2 当多项式次数（最高次项找错，节点 #2 错因）、常数项漏符号", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "一个多项式是'二次三项式'，下面哪个不可能是它？（　）\nA. x² + x + 1\nB. x² − 2x\nC. 2x² − 3x + 5\nD. −x² + 4x − 1",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "几次几项式",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["二次三项式 = 次数是 2 且项数是 3", "A、C、D 都是三项且最高次是 2，符合", "B 只有两项（x²、−2x），是二次二项式，不可能是二次三项式", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "由'几次几项式'反向筛选（排除法）", "难度理由": "medium 复测——需把定义反用，防'会背不会用'", "认知阶梯定位": "L3 复测", "错因陷阱": "只数项数不看次数、以为二项也能算三项式", "教学角色": "防'会背不会用'复测——'几次几项式'定义的逆向取证"},
        },
        {
            "slot": "B5-I0",
            "prompt": "分别写出下面 3 个多项式的项、次数和常数项：\n①x² − 3x + 2　②−2a³ + a　③5 − 4b",
            "expected_answer": "①项：x²、−3x、2；次数 2；常数项 2。②项：−2a³、a；次数 3；常数项：无（没有常数项）。③项：5、−4b；次数 1；常数项 5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别项",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["①x² − 3x + 2：项 x²、−3x、2；最高次 2 → 次数 2；常数项 2", "②−2a³ + a：项 −2a³、a；最高次 3 → 次数 3；没有常数项", "③5 − 4b：项 5、−4b；最高次 1 → 次数 1；常数项 5", "注意每项带符号、次数取最高"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "3 个多项式写项、次数、常数项（diagnostic probe'3 个多项式写项、次数、常数项'素材）", "难度理由": "hard 名副其实——3 式 × 3 属性 = 9 个输出，符号、最高次、无常数项三处易错，需逐式核对", "认知阶梯定位": "L4 复测——全技能综合，防'会背不会用'", "错因陷阱": "−3x 漏负号、②把 a 的 1 次当最高、③常数项 5 与次数 1 混淆", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "多项式 x⁴ − 2x² + 5 中，最高次项是（　）\nA. x⁴\nB. −2x²\nC. 5\nD. x²",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "次数",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["最高次项 = 次数最大的那一项", "x⁴ 是 4 次、−2x² 是 2 次、5 是 0 次", "最高次项是 x⁴，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "找出最高次项（次数最大的项）", "难度理由": "easy 诊断——单步但含'数字大≠次数高'陷阱", "认知阶梯定位": "L1 诊断", "错因陷阱": "把 −2x² 当最高次项（数字 2 大但次数 2 < 4，'最高次项找错'）", "教学角色": "诊断题——'最高次项'概念的一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "多项式 5x² − 3x − 2 的常数项是多少？把它按项分开，写出每一项。",
            "expected_answer": "常数项是 −2；项：5x²、−3x、−2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "常数项",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["看成和：5x² + (−3x) + (−2)", "项带符号：5x²、−3x、−2；常数项 −2", "注意两个减号后面的项都带负号"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "带符号分项与常数项诊断（含两个负号项）", "难度理由": "medium 诊断——两处负号是双重陷阱", "认知阶梯定位": "L2 诊断（diagnostic probe 素材）", "错因陷阱": "常数项漏写符号写 2（节点 #3 错因）、−3x 写成 3x", "教学角色": "诊断题——'符号跟着项走'的直接取证"},
        },
    ],
    # ===== M-G7-LIKE-TERMS 同类项（概念+判断：15 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # 节点契约：essence="同类项看字母和字母指数是否完全相同，和系数无关"；
    # seed=识别同类项/根据同类项求指数/分类整理；common_mistakes=只看字母不看指数/受系数影响/字母顺序变化就不认；
    # diagnostic_probes=8组项判断是否同类；mastery=正确率≥90%、能说出同类项标准。
    # authoring 原则（琢玉教训）：全部经概念判断（识别/求指数/分类整理/纠错论证），无算术冒充；
    # hard 真难（多字母比对、8 组全景判断、8 项分类整理）；同句式 ≤2；
    # 迁移为合并同类项（COMBINE-LIKE 解锁节点）预告——'下列哪组可以合并成一项'式。

    "M-G7-LIKE-TERMS": [
        {
            "slot": "B1-I0",
            "prompt": "3x²y 和 −5x²y 是同类项吗？为什么？",
            "expected_answer": "是。字母部分完全相同（都是 x²y：x 的指数都是 2、y 的指数都是 1），与系数 3 和 −5 无关",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同类项要求：字母相同 + 相同字母的指数相同", "3x²y 和 −5x²y 的字母部分都是 x²y，x、y 的指数分别相同", "系数不同不影响 → 是同类项"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用'字母相同 + 相同字母指数相同'判断同类项（本质演示：与系数无关）", "难度理由": "medium 锚点——判断 + 理由双输出，演示本质而非背口诀", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——'同类项看字母部分，不看系数'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "判断两个单项式是不是同类项，应该看（　）\nA. 字母相同且相同字母的指数相同\nB. 系数相同\nC. 次数相同\nD. 字母相同就行",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同类项的标准：字母相同且相同字母的指数也相同", "系数（B）、次数（C）、只有字母（D）都不够", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别同类项的判定标准（规则识别）", "难度理由": "easy——规则识别无计算", "认知阶梯定位": "L1 识别正宗实现（判断规则而非直接判断）", "错因陷阱": "只看字母（D，节点 #1 错因'只看字母不看指数'）、受系数影响（B）", "教学角色": "L1 识别脚手架——同类项标准第一关"},
        },
        {
            "slot": "B1-I2",
            "prompt": "单项式 7ab 和 −3ab 是同类项吗？它们的系数相同吗？",
            "expected_answer": "是同类项（字母部分都是 ab，a、b 的指数都是 1）；系数分别是 7 和 −3，不相同——同类项与系数无关",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["7ab 和 −3ab 的字母部分都是 ab → 是同类项", "系数分别是 7 和 −3", "系数不同不影响同类项判断"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'同类项与系数无关'的识别（含负系数）", "难度理由": "easy——双问双答", "认知阶梯定位": "L1 识别", "错因陷阱": "受系数影响（认为系数 7 ≠ −3 就不是同类项，节点 #2 错因'受系数影响'）", "教学角色": "'系数无关'的定点识别题"},
        },
        {
            "slot": "B2-I0",
            "prompt": "下面哪组是同类项？（　）\nA. 2x 和 2y\nB. 3x² 和 3x\nC. −4ab 和 5ab\nD. 2 和 2x",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同类项：字母相同且指数相同", "A 字母不同（x 与 y）；B 指数不同（2 与 1）；D 一个含字母一个不含", "C 字母部分都是 ab → 是同类项，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "从四组中选出同类项（含系数/指数/字母干扰）", "难度理由": "easy 套用——单步判断", "认知阶梯定位": "L2 套用", "错因陷阱": "把不同字母当同类（A）、只看系数（B）、常数与含字母项混同类（D）", "教学角色": "L2 套用脚手架"},
        },
        {
            "slot": "B2-I1",
            "prompt": "若 2x^m y 与 −3x² yⁿ 是同类项，m 和 n 各是多少？",
            "expected_answer": "m = 2（x 的指数要相同），n = 1（y 的指数要相同）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据同类项求指数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同类项要求相同字母的指数相同", "x 的指数：m 要等于 2 → m = 2", "y 的指数：n 要等于 1 → n = 1", "系数 2 与 −3 不影响"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "由同类项反求字母指数（指数相等原理）", "难度理由": "medium——需把'同类'翻译成'指数相等'两个等式", "认知阶梯定位": "L2 套用", "错因陷阱": "把系数当指数（n 取 −3）、只对一个字母的指数", "教学角色": "'根据同类项求指数'种子题型的标准套用"},
        },
        {
            "slot": "B2-I2",
            "prompt": "下面关于 x²y 和 xy² 的判断，正确的是（　）\nA. 它们是同类项，因为字母一样\nB. 它们不是同类项，因为 x 的指数不同（x²y 中 x 的指数是 2，xy² 中 x 的指数是 1）\nC. 它们是同类项，因为次数都是 3\nD. 它们不是同类项，因为系数不同",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同类项要求每个相同字母的指数都相同", "x²y 中 x 的指数 2、y 的指数 1；xy² 中 x 的指数 1、y 的指数 2 → 指数不同", "不是同类项，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "x²y 与 xy² 的辨析（指数不同不是同类）", "难度理由": "medium——两字母指数交叉不同，节点头号错因的正面直击", "认知阶梯定位": "L3 变式", "错因陷阱": "只看字母不看指数（A，节点 #1 错因'只看字母不看指数'）、把次数相同当同类（C）、受系数影响（D）", "教学角色": "头号错因的核心变式——'x²y ≠ xy²'的定点题"},
        },
        {
            "slot": "B3-I0",
            "prompt": "把下列单项式按'是同类项'分成两组：3x²、−2x、5x²、4x。可以分成哪两组？",
            "expected_answer": "一组：3x² 和 5x²（字母部分 x² 相同）；另一组：−2x 和 4x（字母部分 x 相同）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分类整理",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先看每个单项式的字母部分：3x² 与 5x² 都是 x²", "−2x 与 4x 都是 x", "分组：{3x², 5x²} 和 {−2x, 4x}"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分类整理同类项（seed 题型'分类整理'）", "难度理由": "medium——4 项两两归类，需先读字母部分再配对", "认知阶梯定位": "L3 变式", "错因陷阱": "把 3x² 与 4x 放一组（只看字母 x 不看指数，节点 #1 错因）", "教学角色": "分类整理的标准变式——'遮住系数看字母部分'策略示范"},
        },
        {
            "slot": "B3-I1",
            "prompt": "下面哪个式子中的两个单项式可以合并成一项（即是同类项）？（　）\nA. 2x²y + 3xy²\nB. 5ab²c + 5a²bc\nC. −4mn² + 3n²m\nD. x³ + x²",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["逐项看字母与指数：A 中 x 的指数 2 vs 1，y 的指数 1 vs 2，不同", "B 中 ab²c 与 a²bc：a、b 指数不同；D 中 x³ 与 x² 指数不同", "C 中 mn² 与 n²m 的字母部分相同（m 的 1 次、n 的 2 次），是同类项", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "多字母同类项判断 + 字母顺序变化（合并同类项预告）", "难度理由": "hard——4 选项 × 多字母逐一比对指数，C 的字母顺序变化（mn² 与 n²m）是反直觉的正确项", "认知阶梯定位": "L4 迁移——同类项 × 合并同类项（COMBINE-LIKE 解锁节点）预告：'可以合并成一项'", "错因陷阱": "只看字母不看指数（A/B/D）、字母顺序变化就不认（C 项正是节点 #3 错因'字母顺序变化就不认'的正面）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——'下列哪组可以合并'式预告"},
        },
        {
            "slot": "B3-I2",
            "prompt": "已知 2x^m yⁿ 与 −3y²x³ 是同类项，则 m + n = （　）\nA. 3\nB. 4\nC. 5\nD. 6",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据同类项求指数",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["−3y²x³ 中 y 的指数是 2、x 的指数是 3（字母顺序不影响）", "同类项要求指数对应相等：m = 3（x），n = 2（y）", "m + n = 3 + 2 = 5，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "字母顺序变化下的指数匹配与求和（同类项 × 单项式字母部分）", "难度理由": "hard——顺序变化（y²x³ vs x^m yⁿ）需先按字母归类再配对，两未知数 + 求和多步", "认知阶梯定位": "L4 迁移——同类项 × 单项式字母部分（MONOMIAL/POLYNOMIAL 前置）", "错因陷阱": "字母顺序变化就不认（认为不是同类项）、m/n 配错（把 y 的指数 2 给 x）、把系数指数算进和（D）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "下列各组中，是同类项的是（　）\nA. 3x 和 3y\nB. 5a²b 和 5ab²\nC. −2 和 7\nD. x 和 x²",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["A 字母不同（x 与 y）；B 指数不同；D 指数不同", "C 都是常数项，所有常数项都是同类项", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "含'常数项互为同类项'的检测", "难度理由": "easy 检测——但 C 是易漏的正确项", "认知阶梯定位": "L2 检测", "错因陷阱": "漏'常数项都是同类项'的事实、把不同字母/指数当同类（A/B/D）", "教学角色": "检测易档——'常数同类'事实的快速探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "判断下面 8 组是不是同类项，把'是'的序号写出来：\n①3x 与 −2x　②x²y 与 xy²　③−5 与 8　④ab 与 ba　⑤2a² 与 3a　⑥mn² 与 −4n²m　⑦x³ 与 x²　⑧0.5x²y 与 −1/2 x²y",
            "expected_answer": "是同类项：①、③、④、⑥、⑧（①字母部分 x；③都是常数项；④ ab 与 ba 字母相同；⑥ mn² 与 n²m 字母部分相同；⑧ 0.5 与 −1/2 系数不影响判断）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["逐组核对字母与指数：①x 相同 ✓；②x、y 指数交叉不同 ✗；③常数项 ✓", "④ab 与 ba 字母相同 ✓；⑤a 的指数 2 vs 1 ✗；⑥mn² 与 n²m 相同 ✓", "⑦指数不同 ✗；⑧字母部分 x²y 相同，系数不同不影响 ✓", "答案：①③④⑥⑧"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "8 组同类项判断（diagnostic probe'8 组项判断是否同类'素材）", "难度理由": "hard 名副其实——8 组 ×（字母 + 指数）双核对，含常数同类、字母顺序、分数系数多重陷阱，需逐组核对", "认知阶梯定位": "L3 检测 hard——头号错因的全景检测", "错因陷阱": "②⑤⑦只看字母不看指数、④⑥字母顺序变化就不认、⑧受系数影响（节点 #1/#2/#3 错因全覆盖）", "教学角色": "检测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "小明说：'2x² 和 2x 是同类项，因为它们都有 2x。'这个说法对吗？为什么？",
            "expected_answer": "不对。同类项要求字母相同且相同字母的指数相同；2x² 中 x 的指数是 2，2x 中 x 的指数是 1，指数不同，所以不是同类项。'都有 2x'只看了系数和字母，没看指数",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["复述标准：字母相同 + 相同字母指数相同", "2x² 的 x 指数是 2，2x 的 x 指数是 1 → 指数不同", "不是同类项，小明只看了'都有 2x'，漏了指数"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "戳破'只看字母不看指数'的错误归纳（论证形态）", "难度理由": "medium 复测——需用标准逐条反驳，mastery'能说出同类项标准'取证", "认知阶梯定位": "L3 复测", "错因陷阱": "认同'都有 2x 就是同类项'（节点 #1 错因的归纳形态）", "教学角色": "防'会背不会用'复测——同类项标准的归因题"},
        },
        {
            "slot": "B5-I0",
            "prompt": "把下列 8 个单项式分类整理（同类项放一组）：\n3x²y，−2xy²，5x²y，4xy²，−x²y，2xy²，7，−3",
            "expected_answer": "第一组（字母部分 x²y）：3x²y、5x²y、−x²y；第二组（字母部分 xy²）：−2xy²、4xy²、2xy²；第三组（常数项）：7、−3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分类整理",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["先看每个单项式的字母部分：x²y 有 3x²y、5x²y、−x²y（−x²y 的系数是 −1）", "xy² 有 −2xy²、4xy²、2xy²", "常数项 7、−3 单独一组（所有常数项互为同类项）"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "8 个单项式分类整理（含负系数与常数项，seed'分类整理'）", "难度理由": "hard——8 项跨 3 组，x²y 与 xy² 极易混组，−x²y 的负号与常数同类都是陷阱", "认知阶梯定位": "L4 复测——全技能综合，防'会背不会用'", "错因陷阱": "x²y 与 xy² 混组（节点 #1 错因）、−x²y 漏读负号、把 7、−3 归入字母组", "教学角色": "复测 hard 档，判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "下面说法正确的是（　）\nA. −5x³ 和 2x³ 不是同类项，因为系数不同\nB. −5x³ 和 2x³ 是同类项，因为字母部分相同（都是 x³）\nC. −5x³ 和 2x³ 不是同类项，因为符号不同\nD. −5x³ 和 2x³ 不是同类项，因为次数不同",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别同类项",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["字母部分都是 x³，x 的指数都是 3", "系数 −5 与 2 不同不影响", "是同类项，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "同类项判断快速诊断（含负系数）", "难度理由": "easy 诊断——单步分档", "认知阶梯定位": "L1 诊断", "错因陷阱": "受系数影响（选 A，节点 #2 错因'受系数影响'）、把符号当判断依据（选 C）", "教学角色": "诊断题——'系数无关'的一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "已知单项式 3a²b 与 −a^m bⁿ 是同类项。m 和 n 分别是多少？请说明判断理由。",
            "expected_answer": "m = 2，n = 1（同类项要求相同字母的指数相同：a 的指数 2 对应 m = 2，b 的指数 1 对应 n = 1）；系数 3 与 −1 不同不影响",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据同类项求指数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同类项要求 a、b 的指数分别相同", "a 的指数：m = 2；b 的指数：n = 1", "理由要点：比字母部分（指数），不比系数"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "由同类项求指数 + 说出标准（含隐系数 −1）", "难度理由": "medium 诊断——指数匹配 + 理由说明双要求", "认知阶梯定位": "L2 诊断（diagnostic probe'8 组项判断'的求指数变体）", "错因陷阱": "把系数 3 当 m、说不出'指数相同'的理由（mastery'能说出同类项标准'取证）", "教学角色": "诊断题——'会判断'与'能说标准'两档的区分题"},
        },
    ],
    # # ===== M-G7-COMBINE-LIKE 合并同类项（计算向：3 verified + 12 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # # 节点契约：essence="合并同类项只合并系数，字母部分不变"；
    # # seed=直接合并/多项式整理/含负系数；common_mistakes=字母指数也相加/符号漏掉/非同类项硬合并；
    # # diagnostic_probes=6题合并同类项，含负系数；mastery=正确率≥85%、能解释为什么字母部分不变。
    # # authoring 原则（琢玉教训）：代数式答案是符号答案（sympy 提取正则只认数字表达式）→ 诚实标
    # # unverifiable（每题答案已人工+符号复核双算）；verified 只取'系数合并'纯算术环节（sympy 真验算）；
    # # hard 真难（五项混合、双字母负系数、情境周长）；L1 真识别；同句式 ≤2；迁移=实际情境（周长）。
    "M-G7-COMBINE-LIKE": [
        {
          "slot": "B1-I0",
          "prompt": "合并同类项：3x + 5x。写出合并的过程，并解释：为什么结果里字母部分还是 x，而不是 x²？",
          "expected_answer": "8x。3x + 5x = (3 + 5)x = 8x；3x 表示 3 个 x，5x 表示 5 个 x，一共 3 + 5 = 8 个 x，所以字母部分仍是 x。只有 x 与 x 相乘才会得到 x²，合并同类项只把系数相加，不把字母相乘",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "合并同类项只合并系数：3x 的系数是 3，5x 的系数是 5",
            "系数相加：3 + 5 = 8",
            "字母部分 x 不变：3x + 5x = 8x",
            "为什么不是 x²：x² 表示 x × x，合并同类项是'几个 x 加几个 x'，不是 x 与 x 相乘"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "合并同类项的本质：只合并系数、字母部分不变（'直接合并'）",
            "难度理由": "medium 锚点——合并 + 解释双输出，演示本质而非背口诀",
            "认知阶梯定位": "标准例题（L2 套用基准线）",
            "错因陷阱": "无（锚点题不埋陷阱；'为什么不是 x²'内嵌头号错因'字母指数也相加'的预防性解释）",
            "教学角色": "讲本质用——'3 个 x + 5 个 x = 8 个 x'苹果模型的演示载体"
          }
        },
        {
          "slot": "B1-I1",
          "prompt": "合并同类项时，正确的做法是（　）\nA. 系数相加，字母部分不变\nB. 系数相加，字母部分也相加\nC. 系数相加，字母部分相乘\nD. 系数和字母都要相加",
          "expected_answer": "A",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "合并同类项的规则：系数相加，字母部分不变",
            "选 A"
          ],
          "error_tags": [
            "concept_confusion"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "识别合并同类项的规则（'直接合并'）",
            "难度理由": "easy——规则识别无计算",
            "认知阶梯定位": "L1 识别正宗实现（判断规则而非直接计算）",
            "错因陷阱": "选 B/D（'字母指数也相加'错因）、选 C（把合并当乘法）",
            "教学角色": "L1 识别脚手架——'只动系数、字母不动'规则第一关"
          }
        },
        {
          "slot": "B1-I2",
          "prompt": "下面哪一组可以直接合并成一个项？（　）\nA. 3x 和 5y\nB. 2x² 和 3x\nC. −4a 和 7a\nD. x 和 x²",
          "expected_answer": "C",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "能合并的前提：是同类项（字母部分完全相同）",
            "A 字母不同（x 与 y）；B、D 指数不同（x² 与 x）；C 字母部分都是 a，可以合并",
            "选 C"
          ],
          "error_tags": [
            "concept_confusion"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "识别'哪组能合并'（同类项才能合并，'直接合并'×LIKE-TERMS 前置）",
            "难度理由": "easy——单步判断，但含指数/字母双干扰",
            "认知阶梯定位": "L1 识别",
            "错因陷阱": "把不同字母当可合并（A）、把 x² 与 x 当可合并（B/D，'字母指数也相加'的前置形态）",
            "教学角色": "L1 识别——'合并前提是同类'的判断题"
          }
        },
        {
          "slot": "B2-I0",
          "prompt": "合并同类项：4x + 6x 时，先把两个系数相加。计算：4 + 6",
          "expected_answer": "10",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "直接合并",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "合并同类项只合并系数：4x 的系数是 4，6x 的系数是 6",
            "系数相加：4 + 6 = 10",
            "字母部分 x 不变：4x + 6x = 10x（整式为符号答案，本环节只验算系数加法）"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "合并同类项的系数相加环节（'直接合并'）",
            "难度理由": "easy 套用——单步系数加法，题干内嵌'字母部分不变'的提醒",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "把指数也相加得 10x²（'字母指数也相加'错因）、系数算错",
            "教学角色": "L2 套用脚手架——'系数相加、字母不动'的分步训练（sympy 只验算纯算术环节，整式 10x 已人工核对）"
          }
        },
        {
          "slot": "B2-I1",
          "prompt": "合并同类项：−3x + 7x，写出结果。",
          "expected_answer": "4x",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "含负系数",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "把符号带进系数：−3 和 7",
            "系数相加：−3 + 7 = 4",
            "字母部分 x 不变：结果 4x"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "含负系数的直接合并（'含负系数'，diagnostic probe'含负系数'素材）",
            "难度理由": "medium——符号带进系数是节点 #2 错因'符号漏掉'的核心形态",
            "认知阶梯定位": "L2 套用（负系数版本）",
            "错因陷阱": "把 −3 当 3 得 10x（'符号漏掉'）、−3 + 7 算成 −10（异号相加错）",
            "教学角色": "含负系数标准套用"
          }
        },
        {
          "slot": "B2-I2",
          "prompt": "合并同类项：2x + 3y + 5x − y",
          "expected_answer": "7x + 2y",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "多项式整理",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "先找同类项：2x 与 5x 同类；3y 与 −y 同类",
            "分别合并：2x + 5x = 7x；3y − y = 2y",
            "不同类的项不能硬合并，结果 7x + 2y"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "多项合并（同类分别合并、不同类不合并，'多项式整理'）",
            "难度理由": "medium——两组同类项 + 含负系数 y 项",
            "认知阶梯定位": "L3 变式（从单项合并转入多项整理）",
            "错因陷阱": "把 2x 与 3y 硬合并成 5xy（'非同类项硬合并'错因）、3y − y 写 4y（符号漏）",
            "教学角色": "多项式整理核心变式"
          }
        },
        {
          "slot": "B3-I0",
          "prompt": "合并同类项：4x² + 3x − 2x² + x",
          "expected_answer": "2x² + 4x",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "多项式整理",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "找同类项：4x² 与 −2x² 同类；3x 与 x 同类",
            "分别合并：4x² − 2x² = 2x²；3x + x = 4x",
            "x² 与 x 不是同类不能合并，结果 2x² + 4x"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "含平方项的多项式整理（x² 与 x 不合并，'多项式整理'）",
            "难度理由": "medium——不同指数项并存，'字母指数也相加'错因的直接战场",
            "认知阶梯定位": "L3 变式",
            "错因陷阱": "把 4x² 与 3x 合并（'字母指数也相加'）、−2x² 的负号漏掉",
            "教学角色": "多项式整理核心变式——'x² 与 x 井水不犯河水'"
          }
        },
        {
          "slot": "B3-I1",
          "prompt": "一个三角形的三条边分别是 2x cm、3x cm、4x cm。求这个三角形的周长，并写出列式和合并过程。",
          "expected_answer": "周长 = 2x + 3x + 4x = 9x cm（系数 2 + 3 + 4 = 9，字母部分 x 不变）",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "周长 = 三边之和：2x + 3x + 4x",
            "系数相加：2 + 3 + 4 = 9",
            "字母部分不变：周长 = 9x cm"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "modeling_or_reading"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "把合并同类项用到实际情境的列式与化简（'直接合并'×周长建模）",
            "难度理由": "hard——需自己列式再合并，系数相加与单位书写都要处理",
            "认知阶梯定位": "L4 迁移——实际情境（周长/面积化简，任务指定迁移方向）",
            "错因陷阱": "把 2x + 3x 当 5x²（'字母指数也相加'）、列式漏一项、漏写单位 cm",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）——实际情境中的合并"
          }
        },
        {
          "slot": "B3-I2",
          "prompt": "合并同类项：3a²b − 2ab² + 5a²b + ab²",
          "expected_answer": "8a²b − ab²",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "含负系数",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "找同类项：3a²b 与 5a²b 同类；−2ab² 与 ab² 同类（ab² 的系数是 +1）",
            "分别合并：3a²b + 5a²b = 8a²b；−2ab² + ab² = −ab²",
            "a²b 与 ab² 不是同类不能合并，结果 8a²b − ab²"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "双字母 + 负系数的多项式整理（a²b 与 ab² 辨析，'含负系数'）",
            "难度理由": "hard——双字母指数交叉、负系数、隐系数 +1 三处陷阱叠加（LIKE-TERMS 前置'x²y 与 xy² 不同类'的合并版）",
            "认知阶梯定位": "L4 迁移——同类项识别 × 合并（LIKE-TERMS 前置）",
            "错因陷阱": "把 a²b 与 ab² 硬合并（'非同类项硬合并'）、−2ab² + ab² 符号漏、漏 ab² 的隐系数 +1",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）"
          }
        },
        {
          "slot": "B4-I0",
          "prompt": "合并同类项：7m + 3m。合并后 m 的系数是几？先算系数之和。计算：7 + 3",
          "expected_answer": "10",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "直接合并",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "合并同类项只合并系数：7 + 3 = 10",
            "字母部分 m 不变",
            "所以 7m + 3m = 10m，m 的系数是 10（整式为符号答案，本环节只验算系数加法）"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "合并的系数相加环节快速检测（'直接合并'）",
            "难度理由": "easy 检测——单步系数加法，需先识别 7 和 3 是系数",
            "认知阶梯定位": "L2 检测",
            "错因陷阱": "系数算错、答成 10m 或 10m²（把字母部分也处理错，'字母指数也相加'）",
            "教学角色": "掌握档快速检测（sympy 验算系数环节 verified，整式 10m 已人工核对）"
          }
        },
        {
          "slot": "B4-I1",
          "prompt": "合并同类项：5x² − 2x + 3x − x² + 4",
          "expected_answer": "4x² + x + 4",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "多项式整理",
          "variant_level": "L3",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "找同类项：5x² 与 −x² 同类；−2x 与 3x 同类；常数项 4 单独一类",
            "分别合并：5x² − x² = 4x²；−2x + 3x = x；4 不变",
            "结果 4x² + x + 4"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 6,
          "design_rationale": {
            "考点": "五项混合整理（x² / x / 常数三类，'多项式整理'，diagnostic probe'6 题合并同类项'素材）",
            "难度理由": "hard——三类项并存 + 负系数 + 常数项，漏项、符号漏都是陷阱",
            "认知阶梯定位": "L3 检测 hard",
            "错因陷阱": "漏合并常数项 4、−2x + 3x 写 −x、把 5x² 与 −2x 硬合并",
            "教学角色": "检测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B4-I2",
          "prompt": "小文说：'3x + 5y 合并后是 8xy，因为 3 加 5 等于 8。'这个说法对吗？为什么？",
          "expected_answer": "不对。3x 和 5y 不是同类项（字母部分不同，一个含 x 一个含 y），不能合并；即使合并同类项，也只能系数相加、字母部分不变，绝不会出现 xy",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "合并的前提是同类项：3x 与 5y 字母部分不同，不是同类项",
            "不同类的项不能合并，只能照抄：3x + 5y",
            "所以 3x + 5y ≠ 8xy（'3 加 5 等于 8'只适用同类项）"
          ],
          "error_tags": [
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "戳破'非同类项硬合并'的错误归纳（'直接合并'的论证形态）",
            "难度理由": "medium 复测——需用'同类项标准'逐条反驳，mastery'能解释为什么字母部分不变'取证",
            "认知阶梯定位": "L3 复测",
            "错因陷阱": "认同 3x + 5y = 8xy（'非同类项硬合并'错因）、'3+5=8 所以能合并'的归纳",
            "教学角色": "防'会背不会用'复测——合并前提的归因题"
          }
        },
        {
          "slot": "B5-I0",
          "prompt": "合并同类项：2x²y − 3xy² + x²y + 5xy²",
          "expected_answer": "3x²y + 2xy²",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "多项式整理",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "找同类项：2x²y 与 x²y 同类（x²y 系数是 +1）；−3xy² 与 5xy² 同类",
            "分别合并：2x²y + x²y = 3x²y；−3xy² + 5xy² = 2xy²",
            "x²y 与 xy² 不是同类不能合并，结果 3x²y + 2xy²"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 6,
          "design_rationale": {
            "考点": "双字母项 + 负系数复测（'多项式整理'）",
            "难度理由": "hard——x²y 与 xy² 两族并存、负系数合并、隐系数 +1，全节点最综合的合并题",
            "认知阶梯定位": "L4 复测——防'会背不会用'",
            "错因陷阱": "x²y 与 xy² 混合并（'字母指数也相加'）、−3xy² + 5xy² 符号错、漏 x²y 的隐系数 1",
            "教学角色": "复测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B5-I1",
          "prompt": "下面哪个合并结果是正确的？（　）\nA. 3x + 2y = 5xy\nB. 3x + 2x = 5x\nC. 3x + 2x = 5x²\nD. 3x + 2x = 5",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "直接合并",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "3x + 2x：系数 3 + 2 = 5，字母部分 x 不变 → 5x",
            "A 是非同类项硬合并（x 与 y 不同类）；C 把指数相加；D 丢了字母部分",
            "选 B"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "合并正误快速诊断（'直接合并'，diagnostic probe 素材）",
            "难度理由": "easy 诊断——单步分档，但 A/C/D 覆盖三个头号错因",
            "认知阶梯定位": "L1 诊断",
            "错因陷阱": "选 A（'非同类项硬合并'）、选 C（'字母指数也相加'）、选 D（'符号漏掉/字母写丢'）",
            "教学角色": "诊断题——三类错因一键探针"
          }
        },
        {
          "slot": "B5-I2",
          "prompt": "合并同类项：−3a + 5a − a 时，把三个系数（带符号）相加。计算：(−3) + 5 + (−1)",
          "expected_answer": "1",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "含负系数",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "把符号带进系数：−3、+5、−1（−a 的系数是 −1）",
            "系数相加：(−3) + 5 + (−1) = 1",
            "字母部分 a 不变：−3a + 5a − a = a（系数是 1 时省略不写）"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "含负系数合并的系数环节诊断（'含负系数'，diagnostic probe'含负系数'素材）",
            "难度理由": "medium——三系数异号求和，−a 的隐系数 −1 是核心陷阱",
            "认知阶梯定位": "L2 诊断",
            "错因陷阱": "−a 的系数漏 −1（算成 2）、(−3) + 5 忘带括号、结果写 1a 未化简",
            "教学角色": "诊断题——负系数符号错因的探针（sympy 验算系数环节 verified，整式 a 已人工核对）"
          }
        },
    ],
    # # ===== M-G7-PARENTHESIS 去括号（计算向：3 verified + 12 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # # 节点契约：essence="括号前是正号不变，括号前是负号每一项都变号"；
    # # seed=正号去括号/负号去括号/括号前有系数/多重括号；
    # # common_mistakes=只变第一项/漏乘括号内某项/负号和系数同时出现就乱；
    # # diagnostic_probes=6题去括号，含负号和括号前系数；mastery=正确率≥85%、能说出每一项如何变化。
    # # authoring 原则（琢玉教训）：符号答案 → unverifiable 为主（人工+符号复核）；verified 取
    # # '括号前系数×括号内项'数值环节（含分配律口算迁移 4×26，sympy 真验算）；多重括号从内向外；
    # # hard 真难（分数系数、负号+系数同现）；L1 真识别；纠错复测防'只变第一项'模板反射。
    "M-G7-PARENTHESIS": [
        {
          "slot": "B1-I0",
          "prompt": "去括号：−(x + 3)。写出过程，并说明括号内每一项发生了什么变化。",
          "expected_answer": "−x − 3。括号前是负号，去掉括号后括号内每一项都变号：x 变成 −x，+3 变成 −3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "负号去括号",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "看括号前的符号：这里是负号",
            "负号去括号：括号内每一项都变号",
            "x → −x，+3 → −3，结果 −x − 3"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "负号去括号的规则演示（'负号去括号'）",
            "难度理由": "medium 锚点——去括号 + 变号解释双输出",
            "认知阶梯定位": "标准例题（L2 套用基准线）",
            "错因陷阱": "无（锚点题不埋陷阱；'每一项都变号'是头号错因'只变第一项'的预防）",
            "教学角色": "讲本质用——'负号像反光镜，每项都翻面'的演示载体"
          }
        },
        {
          "slot": "B1-I1",
          "prompt": "去括号时，如果括号前是负号，正确的是（　）\nA. 括号内每一项都变号\nB. 只把第一项变号\nC. 符号都不变\nD. 去掉括号，符号随便写",
          "expected_answer": "A",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "负号去括号",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "括号前是负号：去掉括号后每一项都变号",
            "选 A"
          ],
          "error_tags": [
            "concept_confusion"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "识别负号去括号规则（'负号去括号'）",
            "难度理由": "easy——规则识别无计算",
            "认知阶梯定位": "L1 识别正宗实现",
            "错因陷阱": "选 B（'只变第一项'错因）、选 C（忘变号）",
            "教学角色": "L1 识别脚手架——负号去括号规则第一关"
          }
        },
        {
          "slot": "B1-I2",
          "prompt": "下面哪个去括号的结果是正确的？（　）\nA. −(x + 2) = −x + 2\nB. −(x + 2) = −x − 2\nC. −(x + 2) = x − 2\nD. −(x + 2) = x + 2",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "负号去括号",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "括号前是负号：每一项都变号",
            "x → −x，+2 → −2，结果 −x − 2",
            "选 B"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "判断负号去括号结果（'负号去括号'）",
            "难度理由": "easy——四选一辨析",
            "认知阶梯定位": "L1 识别",
            "错因陷阱": "选 A（'只变第一项'错因）、选 C/D（符号规则记反）",
            "教学角色": "L1 识别——去括号正误的辨析题"
          }
        },
        {
          "slot": "B2-I0",
          "prompt": "去括号并化简：x + (2x + 3)",
          "expected_answer": "3x + 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "正号去括号",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "括号前是正号：各项不变，直接去括号",
            "x + 2x + 3",
            "合并同类项：x + 2x = 3x，结果 3x + 3"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "正号去括号（不变号）+ 合并（'正号去括号'，COMBINE-LIKE 支持性操作）",
            "难度理由": "easy——去括号不变号 + 一步合并",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "正号却变号（写成 x − 2x + 3）、合并漏项",
            "教学角色": "正号去括号标准套用——'正号不动'的基准示范"
          }
        },
        {
          "slot": "B2-I1",
          "prompt": "去括号并化简：5x − (2x + 3)",
          "expected_answer": "3x − 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "负号去括号",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "括号前是负号：每一项都变号，−(2x + 3) = −2x − 3",
            "原式 = 5x − 2x − 3",
            "合并：5x − 2x = 3x，结果 3x − 3"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "负号去括号 + 合并两步（'负号去括号'）",
            "难度理由": "medium——'减号后忘变号'的直接战场（常数项 3 要变 −3）",
            "认知阶梯定位": "L2 套用（负号版本）",
            "错因陷阱": "写 3x + 3（常数项忘变号，'只变第一项'）、5x − 2x 漏算",
            "教学角色": "负号去括号标准套用——'括号前减号，括号里全翻面'"
          }
        },
        {
          "slot": "B2-I2",
          "prompt": "去括号：3(2x + 1)，写出结果。",
          "expected_answer": "6x + 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "括号前有系数",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "括号前系数 3 要乘括号内每一项（乘法分配律）",
            "3 × 2x = 6x，3 × 1 = 3",
            "结果 6x + 3"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "括号前有系数的去括号（分配律，'括号前有系数'，M-PRE-DISTRIBUTIVE 前置）",
            "难度理由": "medium——'漏乘括号内某项'错因的直接战场",
            "认知阶梯定位": "L3 变式（从正负号转入系数分配）",
            "错因陷阱": "只乘第一项得 6x + 1（'漏乘括号内某项'）、3 × 2x 写 5x（乘加混淆）",
            "教学角色": "括号前有系数的核心变式"
          }
        },
        {
          "slot": "B3-I0",
          "prompt": "去括号并化简：3x − (x − (2x + 1))",
          "expected_answer": "4x + 1",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "多重括号",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "从最里面开始：−(2x + 1) = −2x − 1",
            "中间层：x − (2x + 1) 变 x − 2x − 1 = −x − 1",
            "最外层：3x − (−x − 1) = 3x + x + 1 = 4x + 1（减负变加）"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "多重括号去括号（从内向外逐层，'多重括号'）",
            "难度理由": "medium——三层括号逐层变号，'负号和系数同时出现就乱'的层级形态",
            "认知阶梯定位": "L3 变式",
            "错因陷阱": "外层去括号时内层符号看错（3x − (−x−1) 写 3x − x − 1）、只变第一项",
            "教学角色": "多重括号的核心变式——'从里到外一层一层翻'"
          }
        },
        {
          "slot": "B3-I1",
          "prompt": "用分配律口算：4 × 26 = 4 × (20 + 6) = 4 × 20 + 4 × 6。计算：4 × 26",
          "expected_answer": "104",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "括号前有系数",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "把 26 拆成 20 + 6：4 × 26 = 4 × (20 + 6)",
            "分配律：4 × 20 + 4 × 6",
            "4 × 20 = 80，4 × 6 = 24",
            "80 + 24 = 104"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 6,
          "design_rationale": {
            "考点": "数字版分配律口算（去括号的数值对应物，'括号前有系数'×M-PRE-DISTRIBUTIVE 前置）",
            "难度理由": "hard——需完成'拆数 → 分配 → 求和'三步，体现去括号与小学分配律的同一结构",
            "认知阶梯定位": "L4 迁移——分配律（前置）数值形态 × 去括号规则",
            "错因陷阱": "不分配只列竖式（模板反射）、分配时漏一项（漏 4 × 6）",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）——'去括号就是分配律'的数值示范（sympy 验算 verified）"
          }
        },
        {
          "slot": "B3-I2",
          "prompt": "去括号并化简：−2(3x − 1) − (x + 2)",
          "expected_answer": "−7x",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "括号前有系数",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "第一组：−2(3x − 1) = −6x + 2（系数 −2 乘每一项，−2 × (−1) = +2）",
            "第二组：−(x + 2) = −x − 2（负号全变号）",
            "合并：−6x − x = −7x，2 − 2 = 0，结果 −7x"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "负号与系数同时出现的综合去括号（'括号前有系数'×'负号去括号'，节点 #3 错因'负号和系数同时出现就乱'的正面直击）",
            "难度理由": "hard——两组括号两种规则 + 合并，三处符号陷阱",
            "认知阶梯定位": "L4 迁移——两组括号规则联合应用",
            "错因陷阱": "−2(3x − 1) 写 −6x − 1（漏乘 −1 的变号）、−(x + 2) 写 −x + 2（'只变第一项'）",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）——规则组合应用"
          }
        },
        {
          "slot": "B4-I0",
          "prompt": "去括号：−(x + 5)。括号前系数是 −1，常数项 +5 要乘 −1。计算：(−1) × 5",
          "expected_answer": "−5",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "负号去括号",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "−(x + 5) = −x + (−1) × 5",
            "常数项：(−1) × 5 = −5",
            "所以 −(x + 5) = −x − 5（常数项由 +5 变 −5）"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "负号去括号中常数项的变号计算（'负号去括号'，diagnostic probe'含负号'素材）",
            "难度理由": "easy 检测——单步'−1 × 常数项'，直接对应'只变第一项'错因的数值核心",
            "认知阶梯定位": "L2 检测",
            "错因陷阱": "(−1) × 5 写 5（忘变号）、写 −x + 5（'只变第一项'）",
            "教学角色": "掌握档快速检测（sympy 验算常数项环节 verified，整式 −x − 5 已人工核对）"
          }
        },
        {
          "slot": "B4-I1",
          "prompt": "去括号并化简：−(3x − 2) − 2(x + 1)",
          "expected_answer": "−5x",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "括号前有系数",
          "variant_level": "L3",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "第一组：−(3x − 2) = −3x + 2（负号全变号，−2 → +2）",
            "第二组：−2(x + 1) = −2x − 2（系数 −2 乘每一项）",
            "合并：−3x − 2x = −5x，2 − 2 = 0，结果 −5x"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 6,
          "design_rationale": {
            "考点": "负号与系数并存的综合去括号（'括号前有系数'，节点 #3 错因的直接战场）",
            "难度理由": "hard——两组括号两种规则 + 合并，三处符号陷阱",
            "认知阶梯定位": "L3 检测 hard",
            "错因陷阱": "−(3x − 2) 写 −3x − 2（忘给 −2 变号）、−2(x + 1) 只乘第一项写 −2x + 1、常数 2 − 2 漏算",
            "教学角色": "检测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B4-I2",
          "prompt": "小美去括号：−(x + 3) 写成 −x + 3。她说：'x 变号了，3 不用变。'她的做法对吗？为什么？",
          "expected_answer": "不对。括号前是负号，括号内每一项都要变号，+3 也要变成 −3，正确结果是 −x − 3；只给第一项变号是错的",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "负号去括号",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "规则：括号前是负号，每一项都变号",
            "x → −x，+3 → −3，正确结果 −x − 3",
            "小美只变了第一项（'只变第一项'错因）"
          ],
          "error_tags": [
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "戳破'只变第一项'的错误归纳（'负号去括号'的论证形态）",
            "难度理由": "medium 复测——需用'每一项都变号'标准反驳，mastery'能说出每一项如何变化'取证",
            "认知阶梯定位": "L3 复测",
            "错因陷阱": "认同'x 变了 3 不用变'（节点 #1 错因'只变第一项'）",
            "教学角色": "防'会背不会用'复测——去括号标准的归因题"
          }
        },
        {
          "slot": "B5-I0",
          "prompt": "去括号并化简：1/2 (2x + 4) − 3(x − 1)",
          "expected_answer": "−2x + 5",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "括号前有系数",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "第一组：1/2(2x + 4) = x + 2（1/2 × 2x = x，1/2 × 4 = 2）",
            "第二组：−3(x − 1) = −3x + 3（−3 × (−1) = +3）",
            "合并：x − 3x = −2x，2 + 3 = 5，结果 −2x + 5"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "分数系数与负系数并存的综合去括号（'括号前有系数'）",
            "难度理由": "hard——分数系数分配 + 负号分配 + 合并三步叠加",
            "认知阶梯定位": "L4 复测——防'会背不会用'",
            "错因陷阱": "1/2 × 2x 写 1x 忘约分、−3(x − 1) 写 −3x − 3（忘给 −1 变号）、合并符号错",
            "教学角色": "复测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B5-I1",
          "prompt": "下面哪个去括号正确？（　）\nA. 3(x + 2) = 3x + 2\nB. 3(x + 2) = 3x + 6\nC. 3(x + 2) = x + 6\nD. 3(x + 2) = 3x + 5",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "括号前有系数",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "系数 3 乘括号内每一项：3 × x = 3x，3 × 2 = 6",
            "结果 3x + 6，选 B"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "括号前有系数的正误诊断（'括号前有系数'，diagnostic probe'含括号前系数'素材）",
            "难度理由": "easy 诊断——单步分档",
            "认知阶梯定位": "L1 诊断",
            "错因陷阱": "选 A（'漏乘括号内某项'）、选 C（系数忘乘第一项）、选 D（乘加混淆）",
            "教学角色": "诊断题——'漏乘某项'错因的一键探针"
          }
        },
        {
          "slot": "B5-I2",
          "prompt": "去括号：−3(x + 2)。常数项部分：−3 乘括号内的 2。计算：(−3) × 2",
          "expected_answer": "−6",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "括号前有系数",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "−3(x + 2) = −3x + (−3) × 2",
            "常数项：(−3) × 2 = −6",
            "所以 −3(x + 2) = −3x − 6（x 项系数 −3，常数项 −6）"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "负系数分配中常数项的计算诊断（'括号前有系数'×负数乘法前置，diagnostic probe'含负号和括号前系数'素材）",
            "难度理由": "medium——负系数乘常数项是'负号和系数同时出现就乱'错因的数值核心",
            "认知阶梯定位": "L2 诊断",
            "错因陷阱": "(−3) × 2 写 6（符号错）、漏乘常数项、只乘第一项",
            "教学角色": "诊断题——负号与系数同现的算术探针（sympy 验算 verified，整式 −3x − 6 已人工核对）"
          }
        },
    ],
    # # ===== M-G7-POLY-ADD-SUB 整式加减（计算向：3 verified + 12 unverifiable；难度 5 easy/6 medium/4 hard） =====
    # # 节点契约：essence="整式加减就是先去括号，再合并同类项"；
    # # seed=整式加法/整式减法/先化简再求值/实际背景中的整式；
    # # common_mistakes=减去多项式忘变号/同类项合并错/先求值后化简导致复杂；
    # # diagnostic_probes=4题整式加减，1题先化简再求值；mastery=正确率≥80%、步骤固定：去括号→找同类→合并。
    # # authoring 原则（琢玉教训）：符号答案 → unverifiable 为主（人工+符号复核）；verified 取
    # # '化简后求值/系数合并'数值环节（sympy 真验算）；迁移=求值前化简（EXPR-VALUE 前置）+ A−B 字母整式；
    # # 复测含纠错论证；L1 真识别流程；hard 真难（三项减法、周长列式+化简求值）。
    "M-G7-POLY-ADD-SUB": [
        {
          "slot": "B1-I0",
          "prompt": "计算：(3x + 2) + (2x + 1)。按步骤写：先去括号，再合并同类项。",
          "expected_answer": "5x + 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式加法",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "第一步 去括号：(3x + 2) + (2x + 1) = 3x + 2 + 2x + 1（括号前都是正号，各项不变）",
            "第二步 合并同类项：3x + 2x = 5x，2 + 1 = 3",
            "结果 5x + 3"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "process_habit"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "整式加法的两步流程（去括号 → 合并，'整式加法'）",
            "难度理由": "medium 锚点——流程示范（mastery'步骤固定：去括号→找同类→合并'取证）",
            "认知阶梯定位": "标准例题（L2 套用基准线）",
            "错因陷阱": "无（锚点题不埋陷阱；两步标题内嵌'步骤固定'习惯）",
            "教学角色": "讲本质用——'整式加减 = 去括号 + 合并'的流程演示载体"
          }
        },
        {
          "slot": "B1-I1",
          "prompt": "整式加减的计算顺序是（　）\nA. 先合并同类项，再去括号\nB. 先去括号，再合并同类项\nC. 直接代入数字算\nD. 先算乘除，再算加减",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "整式加法",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "整式加减的标准流程：先去括号，再合并同类项",
            "选 B（C 是求值，D 是有理数运算顺序，都不是整式加减流程）"
          ],
          "error_tags": [
            "process_habit",
            "concept_confusion"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "识别整式加减的流程顺序（'整式加法'，mastery'步骤固定'取证）",
            "难度理由": "easy——规则识别",
            "认知阶梯定位": "L1 识别正宗实现",
            "错因陷阱": "选 A（流程颠倒）、选 D（与运算顺序混淆）",
            "教学角色": "L1 识别脚手架——流程卡第一关"
          }
        },
        {
          "slot": "B1-I2",
          "prompt": "计算 (3x + 2) − (x + 1)，去括号后的第一步正确的是（　）\nA. 3x + 2 − x + 1\nB. 3x + 2 − x − 1\nC. 3x + 2 + x + 1\nD. 3x − 2 − x − 1",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "整式减法",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "括号前是减号：括号内每一项都变号",
            "(x + 1) → −x − 1",
            "所以 3x + 2 − x − 1，选 B"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "识别整式减法去括号的正确形态（'整式减法'，节点 #1 错因'减去多项式忘变号'的直接形态）",
            "难度理由": "easy——改写识别",
            "认知阶梯定位": "L1 识别",
            "错因陷阱": "选 A（'只变第一项'/忘变号）、选 C（减号当加号）",
            "教学角色": "L1 识别——减法去括号的改写辨析"
          }
        },
        {
          "slot": "B2-I0",
          "prompt": "计算：(2x + 3) + (x + 4)",
          "expected_answer": "3x + 7",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式加法",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "去括号（正号不变）：2x + 3 + x + 4",
            "合并同类项：2x + x = 3x，3 + 4 = 7",
            "结果 3x + 7"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "整式加法标准套用（'整式加法'）",
            "难度理由": "easy 套用——正号去括号 + 单类合并",
            "认知阶梯定位": "L2 套用",
            "错因陷阱": "2x + x 写 2x²（'同类项合并错'）、漏常数项 4",
            "教学角色": "L2 套用脚手架"
          }
        },
        {
          "slot": "B2-I1",
          "prompt": "计算：(5x + 3) − (2x + 1)",
          "expected_answer": "3x + 2",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式减法",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "去括号：减号后每一项变号，−(2x + 1) = −2x − 1",
            "原式 = 5x + 3 − 2x − 1",
            "合并：5x − 2x = 3x，3 − 1 = 2，结果 3x + 2"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "整式减法标准套用（'整式减法'，节点 #1 错因'减去多项式忘变号'的核心战场）",
            "难度理由": "medium——减号去括号 + 合并两步",
            "认知阶梯定位": "L2 套用（减法版本）",
            "错因陷阱": "写 3x + 4（常数项 1 忘变号，'减去多项式忘变号'）、5x − 2x 漏算",
            "教学角色": "整式减法标准套用"
          }
        },
        {
          "slot": "B2-I2",
          "prompt": "计算：(3x² + 2x) − (x² − x)",
          "expected_answer": "2x² + 3x",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式减法",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "去括号：−(x² − x) = −x² + x（减号后全变号，−x → +x）",
            "合并：3x² − x² = 2x²，2x + x = 3x",
            "结果 2x² + 3x"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "含平方项的整式减法（'整式减法'）",
            "难度理由": "medium——减号去括号 + x² 族合并",
            "认知阶梯定位": "L3 变式（从一次项转入二次项）",
            "错因陷阱": "−(x² − x) 写 −x² − x（忘给 −x 变号）、x² 与 x 合并错",
            "教学角色": "整式减法的二次项变式"
          }
        },
        {
          "slot": "B3-I0",
          "prompt": "一班收集废纸 (3x + 5) 千克，二班收集 (2x − 3) 千克，两个班一共收集了多少千克？",
          "expected_answer": "5x + 2 千克",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "实际背景中的整式",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "列式：一共 = (3x + 5) + (2x − 3)",
            "去括号（正号不变）：3x + 5 + 2x − 3",
            "合并：3x + 2x = 5x，5 − 3 = 2，答案 5x + 2 千克"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "modeling_or_reading"
          ],
          "estimated_minutes": 4,
          "design_rationale": {
            "考点": "实际情境中的整式加法建模（'实际背景中的整式'）",
            "难度理由": "medium——先列式再计算，含负常数项",
            "认知阶梯定位": "L3 变式（换语境）",
            "错因陷阱": "列式漏括号、5 − 3 写 8（'同类项合并错'）、漏写单位",
            "教学角色": "实际背景的标准变式——'先列式，再按流程算'"
          }
        },
        {
          "slot": "B3-I1",
          "prompt": "先化简再求值：当 x = −2 时，求 (3x + 2) + (x + 1) 的值。（提示：先合并化简，再代入）",
          "expected_answer": "化简得 4x + 3；代入 x = −2：4 × (−2) + 3 = −5",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "先化简再求值",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "先化简：(3x + 2) + (x + 1) = 4x + 3",
            "再代入：x = −2 时，4x + 3 = 4 × (−2) + 3",
            "4 × (−2) + 3 = −8 + 3 = −5"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "process_habit"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "先化简再求值的完整流程（'先化简再求值'，EXPR-VALUE 前置迁移）",
            "难度理由": "hard——化简 + 负数代入两步，'先求值后化简导致复杂'错因的正面示范",
            "认知阶梯定位": "L4 迁移——代数式求值（前置）× 整式加减（任务指定迁移方向）",
            "错因陷阱": "先代入后化简（失去化简意识）、化简错（4x + 3 漏 +1）、(−2) 代入不加括号",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）——求值前化简"
          }
        },
        {
          "slot": "B3-I2",
          "prompt": "已知 A = 2x + 1，B = 3x − 2，求 A − B。",
          "expected_answer": "−x + 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式减法",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "transfer",
          "solution_steps": [
            "代入：A − B = (2x + 1) − (3x − 2)",
            "去括号：−(3x − 2) = −3x + 2，原式 = 2x + 1 − 3x + 2",
            "合并：2x − 3x = −x，1 + 2 = 3，结果 −x + 3"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "用字母表示整式的减法（'整式减法'×代数式前置）",
            "难度理由": "hard——先正确代入 A、B（B 整体加括号）再减，负号分配两处",
            "认知阶梯定位": "L4 迁移——用字母表示数（前置）× 整式减法",
            "错因陷阱": "A − B 漏括号（2x + 1 − 3x − 2 = −x − 1，'减去多项式忘变号'）、1 + 2 符号错",
            "教学角色": "判定层 transfer 证据来源（C3 双角色）"
          }
        },
        {
          "slot": "B4-I0",
          "prompt": "整式 (6a + 2b) + (3a + b) 相加时，a 的系数相加。计算：6 + 3",
          "expected_answer": "9",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "整式加法",
          "variant_level": "L2",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "整式加法：先去括号（正号不变），再合并同类项",
            "a 的系数：6 + 3 = 9，所以 a 项合并为 9a",
            "完整结果：(6a + 2b) + (3a + b) = 9a + 3b（整式为符号答案，本环节只验算系数加法）"
          ],
          "error_tags": [
            "calculation_or_symbol"
          ],
          "estimated_minutes": 3,
          "design_rationale": {
            "考点": "整式加法中系数的合并计算（'整式加法'）",
            "难度理由": "easy 检测——单步系数加法，需先识别 a 的系数",
            "认知阶梯定位": "L2 检测",
            "错因陷阱": "6 + 3 算错、把 6a 与 3a 当 9a²（'同类项合并错'）",
            "教学角色": "掌握档快速检测（sympy 验算系数环节 verified，整式 9a + 3b 已人工核对）"
          }
        },
        {
          "slot": "B4-I1",
          "prompt": "计算：(4x² − 3x + 2) − (x² + 2x − 1)",
          "expected_answer": "3x² − 5x + 3",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "整式减法",
          "variant_level": "L3",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "去括号：4x² − 3x + 2 − x² − 2x + 1（减号后全变号）",
            "合并同类项：4x² − x² = 3x²；−3x − 2x = −5x；2 + 1 = 3",
            "结果 3x² − 5x + 3"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 6,
          "design_rationale": {
            "考点": "三项整式的减法综合（'整式减法'，diagnostic probe'4 题整式加减'素材）",
            "难度理由": "hard——三项去括号变号 + 三类项合并，'减去多项式忘变号'错因的最大覆盖",
            "认知阶梯定位": "L3 检测 hard",
            "错因陷阱": "−(x² + 2x − 1) 忘给 −1 变号（常数得 1 而非 3）、−3x − 2x 写 −x、漏项",
            "教学角色": "检测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B4-I2",
          "prompt": "先化简再求值：化简 (2x + 3) − (x − 1) 得 x + 4。当 x = 3 时，计算：3 + 4",
          "expected_answer": "7",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "先化简再求值",
          "variant_level": "L3",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "验证化简： (2x + 3) − (x − 1) = 2x + 3 − x + 1 = x + 4 ✓",
            "代入 x = 3：x + 4 = 3 + 4",
            "3 + 4 = 7"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "process_habit"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "先化简再求值的求值环节复测（'先化简再求值'，diagnostic probe'1 题先化简再求值'素材）",
            "难度理由": "medium 复测——化简验证 + 代入计算，'先求值后化简'错因的防复发",
            "认知阶梯定位": "L3 复测",
            "错因陷阱": "先代入后化简（(2×3+3)−(3−1) = 7 也对但失去化简意识）、x + 4 代入错",
            "教学角色": "防'会背不会用'复测——化简-求值流程的取证题（sympy 验算求值环节 verified）"
          }
        },
        {
          "slot": "B5-I0",
          "prompt": "一个长方形的长是 (3x + 2) cm，宽是 (x + 1) cm。先列式求周长并化简，再求 x = 2 时的周长。",
          "expected_answer": "周长 = 2(3x + 2) + 2(x + 1) = 8x + 6 cm；当 x = 2 时，周长 = 8 × 2 + 6 = 22 cm",
          "answer_format": "text",
          "verification_intent": "unverifiable",
          "question_type": "实际背景中的整式",
          "variant_level": "L4",
          "difficulty": "hard",
          "purpose_role": "core",
          "solution_steps": [
            "列式：周长 = 2(3x + 2) + 2(x + 1)",
            "化简：6x + 4 + 2x + 2 = 8x + 6",
            "代入 x = 2：8 × 2 + 6 = 16 + 6 = 22 cm"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "modeling_or_reading"
          ],
          "estimated_minutes": 7,
          "design_rationale": {
            "考点": "实际背景中的整式加减 + 化简求值综合（'实际背景中的整式'）",
            "难度理由": "hard——列式、系数分配、合并、代入四步，'实际背景中的整式'种子题型的完整形态",
            "认知阶梯定位": "L4 复测——防'会背不会用'",
            "错因陷阱": "周长公式漏乘 2、−/＋ 分配错、代入后计算错、漏写单位",
            "教学角色": "复测 hard 档，判定层 hard 证据来源"
          }
        },
        {
          "slot": "B5-I1",
          "prompt": "下面哪个整式加减的结果是正确的？（　）\nA. (3x + 2) + (x + 1) = 4x + 2\nB. (3x + 2) + (x + 1) = 4x + 3\nC. (3x + 2) + (x + 1) = 3x² + 3\nD. (3x + 2) + (x + 1) = 3x + 3",
          "expected_answer": "B",
          "answer_format": "choice",
          "verification_intent": "unverifiable",
          "question_type": "整式加法",
          "variant_level": "L1",
          "difficulty": "easy",
          "purpose_role": "core",
          "solution_steps": [
            "去括号（正号不变）：3x + 2 + x + 1",
            "合并：3x + x = 4x，2 + 1 = 3，结果 4x + 3",
            "选 B"
          ],
          "error_tags": [
            "concept_confusion",
            "calculation_or_symbol"
          ],
          "estimated_minutes": 2,
          "design_rationale": {
            "考点": "整式加法正误快速诊断（'整式加法'，diagnostic probe 素材）",
            "难度理由": "easy 诊断——单步分档，但 A/C/D 覆盖常见合并错",
            "认知阶梯定位": "L1 诊断",
            "错因陷阱": "选 A（漏常数项 1）、选 C（'同类项合并错'，3x + x 当 3x²）、选 D（漏 x 系数）",
            "教学角色": "诊断题——整式加法错因一键探针"
          }
        },
        {
          "slot": "B5-I2",
          "prompt": "整式 (5x + 3) − (2x + 1) 中，去括号后 x 的系数是 5 和 −2（减号后要变号），它们相加。计算：5 + (−2)",
          "expected_answer": "3",
          "answer_format": "decimal",
          "verification_intent": "verified",
          "question_type": "整式减法",
          "variant_level": "L2",
          "difficulty": "medium",
          "purpose_role": "core",
          "solution_steps": [
            "去括号：5x + 3 − 2x − 1（减号后每一项变号）",
            "x 的系数：5 + (−2) = 3；常数项：3 + (−1) = 2",
            "完整结果：(5x + 3) − (2x + 1) = 3x + 2（整式为符号答案，本环节只验算系数环节）"
          ],
          "error_tags": [
            "calculation_or_symbol",
            "concept_confusion"
          ],
          "estimated_minutes": 5,
          "design_rationale": {
            "考点": "整式减法去括号后系数的计算诊断（'整式减法'，节点 #1 错因'减去多项式忘变号'的数值核心）",
            "难度理由": "medium——必须把减号后的系数记为 −2 再相加",
            "认知阶梯定位": "L2 诊断",
            "错因陷阱": "写 5 + 2 = 7（忘变号，'减去多项式忘变号'）、5 + (−2) 符号错",
            "教学角色": "诊断题——减法变号的算术探针（sympy 验算系数环节 verified，整式 3x + 2 已人工核对）"
          }
        },
    ],

    # ===== M-G7-EQUATION-CONCEPT 方程与一元一次方程概念（概念向：13 unverifiable + 2 verified） =====
    "M-G7-EQUATION-CONCEPT": [
        {
            "slot": "B1-I0",
            "prompt": "判断：x + 3 = 7 是不是方程？请说出你的根据。（提示：从'含未知数'和'等式'两个条件想）",
            "expected_answer": "是。它含有未知数 x，又用等号连接两边（是等式），两个条件都满足，所以是方程。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "判断方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "方程的两个条件：①含未知数；②是等式（用等号连接两边）",
                "x + 3 = 7 含有未知数 x ✓",
                "x + 3 = 7 用等号连接两边，是等式 ✓",
                "两个条件都满足 → 是方程"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "用'含未知数'和'等式'两条件判断方程（'判断方程'）",
                "难度理由": "medium 锚点——两条件判定示范（essence'方程是含未知数的等式'取证）",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；答案按两条件逐条核对，示范'缺一不可'）",
                "教学角色": "讲本质用——'方程 = 含未知数 + 等式'双条件判定的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "下列式子中，是方程的是（　）\nA. 3x + 2\nB. 5 > 3\nC. x + 1 = 4\nD. 2 + 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "方程要同时满足：含未知数 + 是等式",
                "A 含未知数但没有等号，是代数式，不是等式 ✗",
                "B 是比大小的不等式 ✗",
                "D 是算式，没有未知数 ✗",
                "C 含未知数 x 且用等号连接，两个条件都满足，选 C"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "在混合式子中识别方程（'判断方程'，节点 #1 错因'把代数式当方程'）",
                "难度理由": "easy——四选一识别，选项覆盖代数式/不等式/算式三种陷阱",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 A（把代数式当方程——节点 #1 错因）、选 B（不等式当等式）、选 D（无未知数）",
                "教学角色": "L1 识别脚手架——方程两条件的快速探针"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "小刚说：'2x + 1 是方程，因为它含有未知数 x。' 他的说法对吗？（　）\nA. 对，含未知数就是方程\nB. 不对，2x + 1 没有等号，只是代数式，不是方程\nC. 对，含字母的式子都是方程\nD. 不对，方程里不能有数字",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "方程的两个条件缺一不可：含未知数 + 是等式",
                "2x + 1 含有未知数 x，但没有等号，不是等式",
                "没有等号的含字母式子叫代数式，不是方程",
                "选 B"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "辨析'含未知数 ≠ 方程'（'判断方程'，节点 #1 错因'把代数式当方程'的直接形态）",
                "难度理由": "easy——单条件纠错判断",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 A/C（只看'含未知数'不看等号——'把代数式当方程'）",
                "教学角色": "L1 识别——'条件缺一不可'的纠错脚手架"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "用方程表示下面的等量关系：x 的 3 倍与 5 的和等于 20。",
            "expected_answer": "3x + 5 = 20",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据等量关系列方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "'x 的 3 倍' → 3x",
                "'与 5 的和' → 3x + 5",
                "'等于 20' → 3x + 5 = 20"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "把文字等量关系写成方程（'根据等量关系列方程'，小学简易方程前置的七上化）",
                "难度理由": "easy 套用——单句关系直译",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "写 3 + x + 5 = 20（'3 倍'翻错）、漏等号（写成代数式）",
                "教学角色": "L2 套用脚手架——'等号 = 等于'的建立示范"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "判断：x² + 2 = 6 是一元一次方程吗？请说出理由。",
            "expected_answer": "不是。它只有一个未知数 x，也是等式，但 x 的最高次数是 2，不是 1，所以不是一元一次方程。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "判断一元一次方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "一元一次方程三条件：一个未知数 + 未知数次数都是 1 + 等式",
                "x² + 2 = 6：只有一个未知数 x ✓",
                "但 x 的最高次数是 2（x²），不满足'次数是 1' ✗",
                "所以不是一元一次方程"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "用'一元''一次'判定方程类型（'判断一元一次方程'，节点 #2 错因'次数判断错'）",
                "难度理由": "medium——需主动检查次数并组织理由",
                "认知阶梯定位": "L2 套用（带理由）",
                "错因陷阱": "只看'一个未知数'忽略次数、把 x² 当 x 的 1 次（次数判断错）",
                "教学角色": "一元一次判定的标准套用——三条件逐条核对"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "下列各式中，是一元一次方程的是（　）\nA. x + y = 3\nB. x² = 4\nC. 2x + 1\nD. 3 − x = 2",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断一元一次方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "一元一次方程：一个未知数 + 未知数次数是 1 + 等式",
                "A 有两个未知数 x、y（不是'一元'）✗",
                "B 未知数次数是 2（不是'一次'）✗",
                "C 没有等号，是代数式不是方程 ✗",
                "D 一个未知数、次数 1、有等号 ✓，选 D"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "综合三条件判定一元一次方程（'判断一元一次方程'，节点 #2 错因'未知数个数/次数判断错'）",
                "难度理由": "medium——三条件 × 四选项，每项对应一个具体错误",
                "认知阶梯定位": "L3 变式（多条件组合判定）",
                "错因陷阱": "选 A（'一元'看错——两个未知数）、选 B（'一次'看错——二次）、选 C（把代数式当方程）",
                "教学角色": "L3 变式——三条件分解判定的定点探针"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "小华说：'x = 2 是方程 x + 3 = 5 的解。' 他说的对吗？为什么？",
            "expected_answer": "对。把 x = 2 代入方程左边：2 + 3 = 5，右边也是 5，左边 = 右边，所以 x = 2 是方程的解。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "方程的解",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "方程的解的定义：能使方程左右两边相等的未知数的值",
                "代入检验：把 x = 2 代入左边 x + 3，得 2 + 3 = 5",
                "右边 = 5，左边 = 右边 ✓",
                "所以 x = 2 是方程 x + 3 = 5 的解，小华说得对"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "用代入检验判断一个数是否为方程的解（'方程的解'，节点 #3 错因'方程的解不代入检验'）",
                "难度理由": "medium——先会检验再下结论，检验步骤即理由",
                "认知阶梯定位": "L3 变式（从'给解'到'验解'）",
                "错因陷阱": "不代入直接说'对'（凭感觉）、代入时 2 + 3 算错",
                "教学角色": "方程的解核心题——检验习惯的正面示范"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "妈妈买了 x 千克苹果，每千克 6 元，又买了 4 元的香蕉，一共花了 22 元。根据这些信息列一个方程。",
            "expected_answer": "6x + 4 = 22",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据等量关系列方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "找等量关系：苹果的钱 + 香蕉的钱 = 一共花的钱",
                "苹果的钱 = 单价 × 数量 = 6 × x = 6x（元）",
                "列方程：6x + 4 = 22"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "实际情境中等量关系建模列方程（'根据等量关系列方程'×小学简易方程前置）",
                "难度理由": "hard——先找等量关系再翻译，'一共 22 元'决定等号位置",
                "认知阶梯定位": "L4 迁移——小学简易方程（根据等量关系列方程）的任务指定迁移方向",
                "错因陷阱": "写 6 + x + 4 = 22（单价乘数量翻错）、漏香蕉 4 元、把 22 放左边",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——等量关系 → 方程"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "下列 4 个式子：\n① x + y = 2　② x² = 9　③ 3x − 1 = 2　④ x + 1\n其中是一元一次方程的共有（　）\nA. 1 个\nB. 2 个\nC. 3 个\nD. 4 个",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断一元一次方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "① 有两个未知数（x、y），不是'一元' ✗",
                "② 未知数次数是 2，不是'一次' ✗",
                "③ 一个未知数、次数 1、有等号 ✓",
                "④ 没有等号，是代数式，不是方程 ✗",
                "只有 1 个，选 A"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "批量判定混合式子中的一元一次方程（'判断一元一次方程'×代数式前置）",
                "难度理由": "hard——4 个式子分别套三条件再计数，任何一处误判都错",
                "认知阶梯定位": "L4 迁移——代数式识别（前置）× 方程概念综合判定",
                "错因陷阱": "把 ④（代数式）算进去、把 ②（二次）算进去、漏 ① 的二元性",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——概念综合应用"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "检验 x = 4 是不是方程 x + 2 = 6 的解：把 x = 4 代入左边。计算：4 + 2",
            "expected_answer": "6",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "方程的解",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "代入：x + 2 = 4 + 2",
                "4 + 2 = 6",
                "左边 = 6 = 右边，所以 x = 4 是方程 x + 2 = 6 的解"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "检验方程的解的代入计算环节（'方程的解'）",
                "难度理由": "easy 检测——单步代入加法，需先识别'代入左边'",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "把 x = 4 代入成 4 × 2、4 + 2 算错（检验过程错）",
                "教学角色": "掌握档快速检测（sympy 验算代入环节 verified，'是方程的解'结论已人工核对）"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "下列关于 x 的方程中，是一元一次方程的是（　）\nA. x² = x + 1\nB. 2/x = 3\nC. x + 2 = 2x − 1\nD. x + y = 1",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断一元一次方程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "一元一次方程：一个未知数、未知数次数都是 1、等号两边都是整式",
                "A 有 x²，次数是 2 ✗",
                "B 的未知数 x 在分母里（2/x 不是整式）✗",
                "D 有两个未知数 x、y ✗",
                "C 一个未知数 x、次数 1、两边都是整式 ✓，选 C"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "判定含干扰形态的一元一次方程（'判断一元一次方程'，整式条件）",
                "难度理由": "hard——三种干扰形态（二次/分式/二元）各对应一个错误判断",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "选 B（忽略'整式'条件，把 x 在分母的式子当一元一次）、选 A（次数判断错）、选 D（一元判断错）",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "检验 x = 3 是不是方程 2x + 1 = 7 的解。代入左边计算：2 × 3 + 1",
            "expected_answer": "7",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "方程的解",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "代入：2x + 1 = 2 × 3 + 1",
                "2 × 3 + 1 = 6 + 1 = 7",
                "左边 = 7 = 右边，所以 x = 3 是方程 2x + 1 = 7 的解"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "检验方程的解的乘加代入复测（'方程的解'，diagnostic probe 素材）",
                "难度理由": "medium 复测——先乘后加两步代入，'方程的解不代入检验'错因的防复发",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "先加后乘（2 + 3 × 1 = 5）、2 × 3 算错",
                "教学角色": "防'会背不会用'复测——检验流程的取证题（sympy 验算代入环节 verified）"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "x = −1 是方程 3x + 2 = −1 的解吗？请检验并判断。",
            "expected_answer": "是。检验：3 × (−1) + 2 = −3 + 2 = −1，左边 = 右边，所以 x = −1 是方程 3x + 2 = −1 的解。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "方程的解",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "代入检验：把 x = −1 代入左边 3x + 2",
                "3 × (−1) + 2 = −3 + 2 = −1",
                "右边也是 −1，左边 = 右边 ✓",
                "所以 x = −1 是方程 3x + 2 = −1 的解"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "负数值代入检验方程的解（'方程的解'×负数运算）",
                "难度理由": "hard——负数代入（3 × (−1)）与符号处理两处可错",
                "认知阶梯定位": "L4 复测（负数混合）",
                "错因陷阱": "3 × (−1) 写 3（负号丢失）、−3 + 2 写 −5（符号处理错）",
                "教学角色": "复测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "下列各式中，是方程的是（　）\nA. 2x + 3\nB. 3 + 2 = 5\nC. x − 4 = 0\nD. x > 2",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "方程两条件：含未知数 + 是等式",
                "A 含未知数但没有等号（代数式）✗",
                "B 是等式但没有未知数 ✗（最容易漏）",
                "D 是比大小的不等式 ✗",
                "C 含未知数 x 且是等式 ✓，选 C"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "方程两条件的诊断（'判断方程'，diagnostic probe 素材）",
                "难度理由": "easy 诊断——选项 B 专门测'等式但无未知数'这一易漏条件",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 B（只看'等式'忘'含未知数'——条件缺一）、选 A（把代数式当方程）",
                "教学角色": "诊断题——方程两条件一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "判断 x = 3 是不是方程 2x + 4 = 10 的解。下面哪个检验过程是正确的？（　）\nA. 代入左边：2 × 3 + 4 = 10，左边 = 右边，是方程的解\nB. 代入左边：2 × 3 + 4 = 14，左边 ≠ 右边，不是方程的解\nC. 代入：2 + 3 + 4 = 9，不是方程的解\nD. 代入：3 × 2 − 4 = 2，不是方程的解",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "方程的解",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "检验方法：把 x = 3 代入方程左边，计算并与右边比",
                "A：2 × 3 + 4 = 6 + 4 = 10，右边也是 10，左边 = 右边 ✓",
                "B 算错（6 + 4 = 10 不是 14）；C 把 2x 当成 2 + x；D 符号抄错（应是 +4）",
                "选 A"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "检验过程的正确性诊断（'方程的解'，节点 #3 错因'方程的解不代入检验'及代入错误的区分）",
                "难度理由": "medium 诊断——四个选项覆盖代入算错/系数当加数/符号抄错三类错误",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "选 B（2 × 3 + 4 算错）、选 C（2x 当 2 + x）、选 D（符号抄错）",
                "教学角色": "诊断题——代入检验过程的错因分类探针"
            }
        },
    ],

    # ===== M-G7-EQUALITY-PROP 等式性质（概念+微计算：11 unverifiable + 4 verified） =====
    "M-G7-EQUALITY-PROP": [
        {
            "slot": "B1-I0",
            "prompt": "等式 x − 3 = 5。要在左边把 −3 消去、让 x 单独留下，应该两边同时做什么？做完后等式变成什么？",
            "expected_answer": "两边同时加 3（等式性质 1：两边同加同一个数，等式仍成立），得到 x = 8。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两边同加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "目标：让 x 单独留下。左边是 x − 3，要消去 −3",
                "−3 的相反数是 +3，两边同时加 3（等式性质 1）",
                "左边：x − 3 + 3 = x；右边：5 + 3 = 8",
                "得到 x = 8"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "等式性质 1 的两边同加操作（'两边同加减'，essence'两边做同样的事'取证）",
                "难度理由": "medium 锚点——'消去什么就做什么'的操作示范",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；答案内嵌'两边同时'关键词示范）",
                "教学角色": "讲本质用——天平平衡 → 两边同操作的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "等式性质 1 说的是（　）\nA. 等式两边同时加上或减去同一个数（或式子），等式仍成立\nB. 等式两边同时加上不同的数，等式仍成立\nC. 只给等式的一边加一个数，等式仍成立\nD. 等式两边同时乘不同的数，等式仍成立",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式性质识别",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 1：两边同时加上或减去同一个数（或式子），等式仍成立",
                "A 与定义一致 ✓",
                "B 错在'不同的数'、C 错在'只给一边'、D 错在'乘不同的数'",
                "选 A"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别等式性质 1 的完整表述（'等式性质识别'，节点 #1 错因'只对一边操作'）",
                "难度理由": "easy——规则识别，干扰项各对应一个性质误用",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 B/D（'同一个数'记成'不同的数'）、选 C（只改一边——节点 #1 错因）",
                "教学角色": "L1 识别脚手架——性质表述第一关"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "判断：由等式 3x = 9，两边同时除以 3，得到 x = 3。这一步对吗？（　）\nA. 对。两边同时除以同一个数 3（3 ≠ 0），等式仍成立\nB. 错。应该两边同时加 3\nC. 对。两边同时减去 3\nD. 错。应该只给右边除以 3",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "两边同乘除",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "要把 x 的系数 3 化掉：3x 是 3 乘 x，应两边同时除以 3（等式性质 2）",
                "3x ÷ 3 = x，9 ÷ 3 = 3，得到 x = 3",
                "除数 3 ≠ 0，符合条件 ✓",
                "选 A"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "判断两边同除操作的正确性（'两边同乘除'，性质 2 的除法版本）",
                "难度理由": "easy——单步判断，选项覆盖加减除混淆与只改一边",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 B/C（加减乘除性质用混）、选 D（只对一边操作——节点 #1 错因）",
                "教学角色": "L1 识别——同除操作的改写辨析"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "等式 x + 5 = 12 两边同时减去 5。计算：12 − 5",
            "expected_answer": "7",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两边同加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 1：两边同时减去 5，等式仍成立",
                "左边：x + 5 − 5 = x",
                "右边：12 − 5 = 7，所以 x = 7"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "两边同减的应用计算（'两边同加减'）",
                "难度理由": "easy 套用——识别'减 5'后做一步减法",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "算成 12 + 5 = 17（把减当加——'移项口诀代替理解'的苗头）",
                "教学角色": "L2 套用脚手架（sympy 验算同减环节 verified）"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "等式 3x = 12 两边同时除以 3，x 等于多少？计算：12 ÷ 3",
            "expected_answer": "4",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两边同乘除",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 2：两边同时除以 3（3 ≠ 0），等式仍成立",
                "左边：3x ÷ 3 = x",
                "右边：12 ÷ 3 = 4，所以 x = 4"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "两边同除的系数化为 1（'两边同乘除'）",
                "难度理由": "medium——必须识别'除以 3'而非减 3，再算除法",
                "认知阶梯定位": "L2 套用（除法版本）",
                "错因陷阱": "算 12 − 3 = 9（同减代替同除）、12 ÷ 3 算错",
                "教学角色": "性质 2 标准套用（sympy 验算同除环节 verified）"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "由等式 x/4 = 8，两边同时乘 4，得到 x = 32。下面说法正确的是（　）\nA. 正确。依据是等式性质 2：两边同时乘同一个数，等式仍成立\nB. 正确。依据是等式性质 1：两边同时加同一个数\nC. 错误。应该两边同时除以 4\nD. 错误。应该只给右边乘 4",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "两边同乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "x/4 表示 x ÷ 4，要消去 ÷4 应两边同时乘 4（乘除互逆）",
                "等式性质 2：两边同时乘同一个数（4），等式仍成立",
                "左边：x/4 × 4 = x；右边：8 × 4 = 32，得到 x = 32 ✓",
                "选 A"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "分数形式等式的同乘变形（'两边同乘除'，乘除互逆）",
                "难度理由": "medium——分数线隐含除法，需选对'乘 4'",
                "认知阶梯定位": "L3 变式（从整系数转入分数系数）",
                "错因陷阱": "选 B（性质用混）、选 C（除以 4 得 x/16）、选 D（只对一边操作）",
                "教学角色": "性质 2 的分数变式——乘除互逆的辨析"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "小明解方程 x + 3 = 7 时，第二步写成 x = 7 − 3。他说这是'移项'。移项和等式性质有关系吗？（　）\nA. 有关系。移项就是'两边同时减去 3'的简写，所以移项要变号\nB. 没关系。移项是另一种方法，和等式性质无关\nC. 有关系，但移项不用变号\nD. 没关系。移项只能用在乘法里",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式变形判断",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "x + 3 = 7 两边同时减去 3（等式性质 1）：x + 3 − 3 = 7 − 3，即 x = 7 − 3",
                "所以'移项'（把 +3 移到右边变 −3）本质是两边同减 3 的压缩写法",
                "移项必须变号，因为移的是'两边同时减'的结果",
                "选 A"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "移项与等式性质 1 的关系（'等式变形判断'，节点 #3 错因'移项口诀代替理解'）",
                "难度理由": "medium——需要把口诀'移项变号'还原成性质操作",
                "认知阶梯定位": "L3 变式（口诀 → 原理的还原）",
                "错因陷阱": "选 B（口诀与原理脱节——'移项口诀代替理解'）、选 C（不变号）",
                "教学角色": "变式核心——'先两边同操作，再压缩成移项'教学策略的落实题"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "天平左边放 2 个一样的苹果和 1 个 50 克的砝码，右边放 1 个苹果和 3 个 50 克的砝码，天平平衡（每个苹果重 x 克）。现在从两边同时拿走 1 个苹果和 1 个 50 克的砝码，天平还平衡吗？这时你能得到什么等式？",
            "expected_answer": "还平衡。两边同时拿走同样的东西，相当于等式两边同时减去同一个量（x + 50）：2x + 50 = x + 150 变成 x = 100，即左边剩 1 个苹果，右边剩 2 个 50 克砝码（100 克），仍平衡。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "天平模型",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "先列天平等式：2x + 50 = x + 150（左边 2 苹果 + 50 克，右边 1 苹果 + 150 克）",
                "两边同时拿走 1 个苹果和 1 个 50 克砝码 = 两边同时减去 (x + 50)（等式性质 1）",
                "左边剩 1 个苹果（x 克），右边剩 2 个 50 克砝码（100 克）",
                "天平仍平衡，得到 x = 100"
            ],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "用天平模型理解'两边同时做同样的事'（'天平模型'，essence'等式像天平'取证）",
                "难度理由": "hard——先列等式再执行同减操作，天平直觉 × 符号化两步",
                "认知阶梯定位": "L4 迁移——天平模型/两边平衡直觉（任务指定迁移方向）",
                "错因陷阱": "只回答'平衡'说不清等式（缺符号化）、拿走时只减苹果不减砝码（只对一边操作）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——本质的直观化迁移"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "小刚说：'由等式 4x = 2x，两边同时除以 2x，得到 4 = 2。' 这个变形错在哪里？（　）\nA. 因为由 4x = 2x 可知 x = 0，所以 2x = 0，等式两边不能同时除以 0\nB. 因为 4 ÷ 2x 算错了\nC. 因为等式两边不能同时除以同一个式子\nD. 这个变形没有错，4 = 2 是对的",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式变形判断",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "等式性质 2 有个条件：两边同除的数不能是 0",
                "由 4x = 2x，两边同时减去 2x：2x = 0，所以 x = 0，2x = 0",
                "两边同时除以 2x 就是除以 0，不合法",
                "所以 4 = 2 的错误根源是'除以 0'，选 A"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "等式性质 2 的'除数不为 0'边界条件（'等式变形判断'，节点 #2 错因'除以含 0 可能性忽略'）",
                "难度理由": "hard——受控拓展：需先推出 2x = 0 再判断除以 0，并识破'4 = 2 荒谬'信号",
                "认知阶梯定位": "L4 迁移——代数式（含字母式子作除数）× 性质边界条件",
                "错因陷阱": "选 B（找错原因）、选 D（把荒谬结果当真——'除以含 0 可能性忽略'）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——性质适用条件的深层理解"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "等式 x − 5 = 3 两边同时加 5。计算：3 + 5",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两边同加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 1：两边同时加 5，等式仍成立",
                "左边：x − 5 + 5 = x",
                "右边：3 + 5 = 8，所以 x = 8"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "两边同加的检测（'两边同加减'）",
                "难度理由": "easy 检测——单步同加计算",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "算 3 − 5 = −2（把加当减——'移项口诀代替理解'的苗头）",
                "教学角色": "掌握档快速检测（sympy 验算同加环节 verified）"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "下面等式变形中，正确的是（　）\nA. 由 x − 2 = 6 得 x = 4（两边同时减 2）\nB. 由 x + 4 = 7 得 x = 11（两边同时加 4）\nC. 由 3x = 9 得 x = 3（两边同时除以 3）\nD. 由 2x = 6 得 x = 8（两边同时加 2）",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式变形判断",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "A：x − 2 = 6 应两边同加 2 得 x = 8，同减 2 得 x = 4 是错的 ✗",
                "B：x + 4 = 7 应两边同减 4 得 x = 3，同加 4 得 x = 11 是错的 ✗",
                "C：3x = 9 两边同除 3 得 x = 3 ✓",
                "D：2x = 6 应同除 2 得 x = 3，同加 2 得 x = 8 是错的 ✗",
                "选 C"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "四路等式变形正误判定（'等式变形判断'，diagnostic probe'4 道等式变形判断'素材）",
                "难度理由": "hard——四个变形逐一核对性质与结果，两处可错",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "选 A（'消去 −2'误用同减）、选 B（同加代替同减）、选 D（方法错但结果碰巧对）",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "等式 −3x = 9 两边同时除以 −3。计算：9 ÷ (−3)",
            "expected_answer": "−3",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "两边同乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 2：两边同时除以 −3（−3 ≠ 0），等式仍成立",
                "左边：−3x ÷ (−3) = x",
                "右边：9 ÷ (−3) = −3，所以 x = −3"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "负系数等式的同除复测（'两边同乘除'，为 EQ-SOLVE 的负系数处理铺路）",
                "难度理由": "medium 复测——负数除法符号处理，防'会背不会用'",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "算 9 ÷ 3 = 3（丢负号——'负系数处理错'的苗头）、(−3) 除法符号错",
                "教学角色": "复测 medium——负系数处理取证（sympy 验算同除环节 verified）"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "用等式性质把 2x + 3 = 11 变形成 x = 4。写出两步变形，并写出每一步的依据。",
            "expected_answer": "第一步：两边同时减去 3（等式性质 1），得 2x = 8；第二步：两边同时除以 2（等式性质 2，2 ≠ 0），得 x = 4。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "等式变形应用",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "目标：让 x 单独留下。先处理常数项 3：两边同时减去 3（等式性质 1）",
                "2x + 3 − 3 = 11 − 3，得 2x = 8",
                "再处理系数 2：两边同时除以 2（等式性质 2，2 ≠ 0）",
                "2x ÷ 2 = 8 ÷ 2，得 x = 4"
            ],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "两步等式变形的完整流程与依据（'等式变形应用'，mastery'知道每步两边同操作'取证）",
                "难度理由": "hard——两步操作 + 每步写依据，教学策略'每步写依据'的直接落实",
                "认知阶梯定位": "L4 复测（解方程前夜）",
                "错因陷阱": "只写一步、漏依据（'移项口诀代替理解'）、第二步把 11 直接除 2（漏先减 3）",
                "教学角色": "复测 hard 档——EQ-SOLVE 解锁前的桥接证据"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "小刚把等式 x + 3 = 7 只给左边减去 3，写成 x = 7。他错在哪里？（　）\nA. 等式两边必须同时减同一个数，等式才仍成立；只改一边会破坏平衡\nB. 应该只给右边减 3\nC. 他没写'解'字\nD. 他没错，x = 7 是对的",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式性质识别",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 1 要求：两边同时加或减同一个数，等式才仍成立",
                "只给左边减 3：x + 3 − 3 = x，右边还是 7，左边 ≠ 右边，等式被破坏",
                "正确做法：两边同时减 3，x + 3 − 3 = 7 − 3，得 x = 4",
                "选 A"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "诊断'只对一边操作'错误（'等式性质识别'，节点 #1 错因的直接形态）",
                "难度理由": "easy 诊断——单步定位错误操作",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 D（接受只改一边的结果）、选 B（换一边改）",
                "教学角色": "诊断题——节点头号错因一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "下面说法正确的是（　）\nA. 等式两边同时除以 0，等式仍成立\nB. 等式两边同时乘同一个数，等式不一定仍成立\nC. 等式两边同时乘同一个数，或除以同一个不为 0 的数，等式仍成立\nD. 等式两边同时除以同一个数（可以是 0），等式仍成立",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "等式性质识别",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "等式性质 2：两边同时乘同一个数，或除以同一个不为 0 的数，等式仍成立",
                "A 错：除以 0 无意义；B 错：同乘一定仍成立；D 错：除数不能是 0",
                "C 与定义一致，选 C"
            ],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "性质 2 的'乘任意数、除非零数'边界诊断（'等式性质识别'，节点 #2 错因'除以含 0 可能性忽略'）",
                "难度理由": "medium 诊断——区分'乘 0 可以、除 0 不可以'的对称性陷阱",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "选 A/D（'除以含 0 可能性忽略'）、选 B（把'同乘'也当成有条件）",
                "教学角色": "诊断题——性质 2 适用条件的分类探针"
            }
        },
    ],

    # ===== M-G7-EQ-SOLVE 解一元一次方程基础（计算向：12 unverifiable + 3 verified） =====
    "M-G7-EQ-SOLVE": [
        {
            "slot": "B1-I0",
            "prompt": "解方程：x + 3 = 7，写出每一步。（提示：目标是把 x 单独留下，用等式性质）",
            "expected_answer": "x = 4（两边同时减去 3，得 x = 4；检验：4 + 3 = 7 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "目标：让 x 单独留下。左边是 x + 3，先消去 +3",
                "两边同时减去 3（等式性质 1）：x + 3 − 3 = 7 − 3",
                "x = 4",
                "检验：4 + 3 = 7，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "一步方程的标准解法流程（'一步方程'，essence'把未知数单独留下'取证）",
                "难度理由": "medium 锚点——流程示范（解 + 检验两步习惯）",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；答案内嵌检验步示范'能代回检验'习惯）",
                "教学角色": "讲本质用——'目标导向 + 每步写依据'的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "解方程 x − 5 = 9，第一步应两边同时做什么？（　）\nA. 同时加 5\nB. 同时减 5\nC. 同时乘 5\nD. 同时除以 5",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "要让 x 单独留下，左边是 x − 5，要消去 −5",
                "−5 的相反数是 +5，两边同时加 5（等式性质 1）",
                "选 A"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别一步方程的第一步操作（'一步方程'，'消去什么就做什么'）",
                "难度理由": "easy——操作识别",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 B（'减'字迷惑——两边同减 5 反而更糟）、选 C/D（加减乘除用混）",
                "教学角色": "L1 识别脚手架——解方程第一步卡"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "解方程 3x = 12，要把 x 的系数化为 1，两边应同时做什么？（　）\nA. 同时除以 3\nB. 同时减 3\nC. 同时乘 3\nD. 同时加 3",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "系数化为1",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "3x 表示 3 乘 x，要把系数 3 化掉，乘用除来消",
                "两边同时除以 3（等式性质 2，3 ≠ 0）：3x ÷ 3 = x，12 ÷ 3 = 4",
                "选 A"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别系数化为 1 的操作（'系数化为1'）",
                "难度理由": "easy——操作识别",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 B（'系数化 1'误用减——'系数化 1 除错'的苗头）、选 C（乘 3 得 9x）",
                "教学角色": "L1 识别——系数化 1 操作卡"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "解方程 x − 4 = 10：两边同时加 4。计算：10 + 4",
            "expected_answer": "14",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "两边同时加 4（等式性质 1）：x − 4 + 4 = 10 + 4",
                "x = 14",
                "检验：14 − 4 = 10 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "一步方程的同加套用（'一步方程'）",
                "难度理由": "easy 套用——识别'加 4'后做一步加法",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "算 10 − 4 = 6（把'加 4'想成'减 4'——'移项不变号'的苗头）",
                "教学角色": "L2 套用脚手架（sympy 验算同加环节 verified）"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "解方程 −2x = 8，两边同时除以 −2。计算：8 ÷ (−2)",
            "expected_answer": "−4",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "系数化为1",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "两边同时除以 −2（等式性质 2，−2 ≠ 0）：−2x ÷ (−2) = x",
                "8 ÷ (−2) = −4",
                "所以 x = −4；检验：−2 × (−4) = 8 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "负系数方程的系数化 1（'系数化为1'，节点 #3 错因'负系数处理错'）",
                "难度理由": "medium——负数除法符号处理",
                "认知阶梯定位": "L2 套用（负系数版本）",
                "错因陷阱": "算 8 ÷ 2 = 4（丢负号）、符号规则错（'负系数处理错'）",
                "教学角色": "负系数处理标准套用（sympy 验算同除环节 verified）"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "解方程：3x + 4 = 13（写出两步）",
            "expected_answer": "x = 3（两边同时减 4 得 3x = 9，再两边同时除以 3 得 x = 3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "目标：让 x 单独留下。先处理常数项 4：两边同时减 4（等式性质 1）",
                "3x + 4 − 4 = 13 − 4，得 3x = 9",
                "再处理系数 3：两边同时除以 3（等式性质 2），得 x = 3",
                "检验：3 × 3 + 4 = 13 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "两步方程的标准流程（'两步方程'，从一步到两步）",
                "难度理由": "medium——先常数项后系数，两步顺序是关键",
                "认知阶梯定位": "L3 变式（步数递增）",
                "错因陷阱": "先除后减（顺序错）、13 − 4 或 9 ÷ 3 算错、漏检验",
                "教学角色": "两步方程标准套用——'先移常数，再化系数'"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "解方程：2x + 3 = x + 7（提示：把含 x 的项移到左边，常数移到右边，注意变号）",
            "expected_answer": "x = 4（2x − x = 7 − 3，x = 4；检验：2 × 4 + 3 = 11，4 + 7 = 11 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "移项合并",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "移项：把右边的 x 移到左边变 −x，左边的 3 移到右边变 −3（移项 = 两边同减的简写，要变号）",
                "2x − x = 7 − 3",
                "合并同类项：x = 4",
                "检验：2 × 4 + 3 = 11，4 + 7 = 11，左边 = 右边 ✓"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "移项 + 合并的方程（'移项合并'，节点 #1 错因'移项不变号'的核心战场）",
                "难度理由": "medium——两处移项变号 + 合并",
                "认知阶梯定位": "L3 变式（引入移项压缩写法）",
                "错因陷阱": "2x + 3 = x + 7 移项忘变号（2x + x = 7 + 3 → 3x = 10 错）、常数项变号错",
                "教学角色": "移项合并标准套用——'移项 = 两边同减，必须变号'"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "小明解方程 x + 5 = 2x − 1 得到 x = 6。请检验他的解是否正确，写出检验过程。",
            "expected_answer": "把 x = 6 代入左边：6 + 5 = 11；代入右边：2 × 6 − 1 = 11。左边 = 右边，所以 x = 6 是方程的解，小明解对了。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "移项合并",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "检验方法：把解代入方程两边，分别计算，看是否相等",
                "左边：6 + 5 = 11",
                "右边：2 × 6 − 1 = 12 − 1 = 11",
                "左边 = 右边，所以 x = 6 是方程的解 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "解完方程的代入检验迁移（'移项合并'×SOLUTION-HABIT 桥梁）",
                "难度理由": "hard——需分别算两边（含 2 × 6 − 1 两步），再作判断",
                "认知阶梯定位": "L4 迁移——'代入检验'解题习惯（任务指定桥梁方向）",
                "错因陷阱": "只代一边、2 × 6 − 1 算错、检验后不下结论（'不检验'错因的正面示范）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——检验习惯落地"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "解方程：x/2 − 1 = 3（提示：先把常数项处理掉，再处理分数系数）",
            "expected_answer": "x = 8（两边同时加 1 得 x/2 = 4，再两边同时乘 2 得 x = 8）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "先处理常数项：两边同时加 1（等式性质 1）：x/2 − 1 + 1 = 3 + 1，得 x/2 = 4",
                "再处理分数系数：两边同时乘 2（等式性质 2）：x/2 × 2 = 4 × 2",
                "x = 8",
                "检验：8/2 − 1 = 4 − 1 = 3 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "含分数系数的两步方程（'两步方程'×有理数前置）",
                "难度理由": "hard——分数系数（乘除互逆）与两步顺序叠加",
                "认知阶梯定位": "L4 迁移——分数运算（RATIONAL-MIXED 前置）× 解方程",
                "错因陷阱": "x/2 处理成减 2、两边乘 2 时只乘一边、4 × 2 算错",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——分数系数方程"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "解方程 x + 7 = 15：两边同时减 7。计算：15 − 7",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "两边同时减 7（等式性质 1）：x + 7 − 7 = 15 − 7",
                "x = 8",
                "检验：8 + 7 = 15 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "一步方程检测（'一步方程'）",
                "难度理由": "easy 检测——单步同减计算",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "算 15 + 7 = 22（'移项不变号'的苗头）",
                "教学角色": "掌握档快速检测（sympy 验算同减环节 verified）"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "解方程：−2x + 5 = 11",
            "expected_answer": "x = −3（两边同时减 5 得 −2x = 6，再两边同时除以 −2 得 x = −3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "先处理常数项：两边同时减 5（等式性质 1）：−2x + 5 − 5 = 11 − 5，得 −2x = 6",
                "再处理系数：两边同时除以 −2（等式性质 2）：x = 6 ÷ (−2)",
                "x = −3",
                "检验：−2 × (−3) + 5 = 6 + 5 = 11 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "负系数两步方程检测（'两步方程'，diagnostic probe'含负系数'素材）",
                "难度理由": "hard——同减 + 负系数化 1 两步，负号两处可丢",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "6 ÷ (−2) 写 3（丢负号——'负系数处理错'）、11 − 5 算错",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "解方程：2x − 7 = 5（写出两步）",
            "expected_answer": "x = 6（两边同时加 7 得 2x = 12，再两边同时除以 2 得 x = 6）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "先处理常数项 −7：两边同时加 7（等式性质 1）：2x − 7 + 7 = 5 + 7，得 2x = 12",
                "再处理系数：两边同时除以 2（等式性质 2）：x = 12 ÷ 2",
                "x = 6",
                "检验：2 × 6 − 7 = 12 − 7 = 5 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "两步方程复测（'两步方程'，防'会背不会用'）",
                "难度理由": "medium 复测——负常数项同加 + 系数化 1",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "同加 7 写成同减 7、12 ÷ 2 算错",
                "教学角色": "复测 medium——两步流程的防退化取证"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "解方程：2x + 3 = x + 8，并检验你的解。",
            "expected_answer": "x = 5（移项：2x − x = 8 − 3，x = 5；检验：2 × 5 + 3 = 13，5 + 8 = 13，左边 = 右边 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "移项合并",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "移项：2x + 3 = x + 8，把 x 移到左边变 −x，3 移到右边变 −3（移项要变号）",
                "2x − x = 8 − 3",
                "合并：x = 5",
                "检验：2 × 5 + 3 = 13，5 + 8 = 13，左边 = 右边 ✓"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "移项合并 + 检验的综合复测（'移项合并'，mastery'能代回检验'取证）",
                "难度理由": "hard——两处移项变号 + 合并 + 检验四步",
                "认知阶梯定位": "L4 复测",
                "错因陷阱": "移项不变号（2x + x = 8 + 3 → 3x = 11 错——节点 #1 错因）、漏检验",
                "教学角色": "复测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "小明解方程 x + 3 = 7 时，第二步写成 x = 7 + 3，得到 x = 10。他错在哪里？（　）\nA. 移项没变号：+3 移到右边应变成 −3，x = 7 − 3 = 4\nB. 他忘了写'解'字\nC. 应该两边同时乘 3\nD. 他没错，x = 10 是对的",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "移项合并",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "x + 3 = 7 移项：+3 移到右边变 −3（移项 = 两边同时减 3，要变号）",
                "x = 7 − 3 = 4",
                "小明的 x = 7 + 3 是移项不变号",
                "选 A"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "诊断'移项不变号'错误（'移项合并'，节点 #1 错因的直接形态）",
                "难度理由": "easy 诊断——单步定位变号错误",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 D（接受错误结果）、选 B（把错误归因于格式）",
                "教学角色": "诊断题——节点头号错因一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "解方程：x/4 = 3（提示：分数线表示除以 4，要把 x 单独留下）",
            "expected_answer": "x = 12（两边同时乘 4，x = 3 × 4 = 12）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "系数化为1",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "x/4 表示 x ÷ 4，要把 ÷4 消去，两边同时乘 4（等式性质 2，乘除互逆）",
                "x/4 × 4 = 3 × 4",
                "x = 12",
                "检验：12/4 = 3 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "分数系数方程的系数化 1 诊断（'系数化为1'，diagnostic probe'含分数系数'素材）",
                "难度理由": "medium 诊断——需识别'乘 4'而非除 4（乘除互逆）",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "两边同除 4（得 x/16）、3 × 4 算错（'系数化 1 除错'）",
                "教学角色": "诊断题——分数系数处理的算术探针"
            }
        },
    ],

    # ===== M-G7-EQ-PAREN 含括号方程（计算向：13 unverifiable + 2 verified） =====
    "M-G7-EQ-PAREN": [
        {
            "slot": "B1-I0",
            "prompt": "解方程：3(x + 2) = 15，写出每一步。（提示：先去括号，再按基础方程流程解）",
            "expected_answer": "x = 3（去括号：3x + 6 = 15；两边同时减 6：3x = 9；两边同时除以 3：x = 3；检验：3 × (3 + 2) = 3 × 5 = 15 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "先处理括号：3 要乘括号里的每一项，3(x + 2) = 3x + 6",
                "3x + 6 = 15，两边同时减 6（等式性质 1）：3x = 9",
                "两边同时除以 3（等式性质 2）：x = 3",
                "检验：3 × (3 + 2) = 3 × 5 = 15，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "去括号 + 基础方程全流程（'含括号方程'，essence'先正确去括号，再按基础方程流程解'取证）",
                "难度理由": "medium 锚点——完整流程示范（去括号 → 移项 → 系数化 1 → 检验）",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；答案内嵌检验步示范'能代回检验'习惯）",
                "教学角色": "讲本质用——'去括号与解方程分两阶段'教学策略的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "解方程 2(x + 3) = 10，第一步去括号。下面哪个是正确的？（　）\nA. 2x + 3 = 10（只乘了第一项）\nB. 2x + 6 = 10（每一项都乘 2）\nC. x + 6 = 10（系数 2 丢了）\nD. 2x + 3x = 10（把每一项都再乘个 x）",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去括号",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去括号规则：括号前的数要乘括号里的每一项",
                "2(x + 3) = 2 × x + 2 × 3 = 2x + 6",
                "选 B"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别去括号的正确结果（'去括号'，括号前系数要乘每一项）",
                "难度理由": "easy——去括号单步识别，选项覆盖漏乘/丢系数/乱乘",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 A（只乘第一项——'去括号漏乘'）、选 C（丢系数）、选 D（把 x 也乘）",
                "教学角色": "L1 识别脚手架——'去括号漏乘'头号错因探针"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "去括号：−(x − 3)。下面哪个是正确的？（　）\nA. −x − 3（−3 没变号）\nB. −x + 3（负号乘进去，−3 变 +3）\nC. x − 3（丢了负号）\nD. x + 3",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去括号",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "括号前是负号，去掉括号时每一项都要变号",
                "−(x − 3) = −x + 3（−x 不变符号，−3 变 +3）",
                "选 B"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "括号前是负号的去括号变号（'去括号'，'负号变号漏项'错因的直接形态）",
                "难度理由": "easy——单步变号识别",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 A（−3 没变号——'负号变号漏项'）、选 C/D（丢负号）",
                "教学角色": "L1 识别——负号去括号的变号规则探针"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "解方程 4(x + 2) = 20，先去括号得 4x + 8 = 20，再两边同时减去 8。计算：20 − 8",
            "expected_answer": "12",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含括号方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去括号：4(x + 2) = 4x + 8，方程变成 4x + 8 = 20",
                "两边同时减去 8（等式性质 1）：4x + 8 − 8 = 20 − 8",
                "20 − 8 = 12，所以 4x = 12"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "去括号后的同减计算环节（'含括号方程'）",
                "难度理由": "easy 套用——识别'去括号得 4x + 8'后做一步减法",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "算 20 + 8 = 28（同加代替同减——'移项不变号'的苗头）",
                "教学角色": "L2 套用脚手架（sympy 验算同减环节 verified）"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "解方程：5(x − 1) = 20（写出两步：先去括号，再解）",
            "expected_answer": "x = 5（去括号：5x − 5 = 20；两边同时加 5：5x = 25；两边同时除以 5：x = 5；检验：5 × (5 − 1) = 5 × 4 = 20 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去括号：5 乘括号里每一项，5(x − 1) = 5x − 5，方程变成 5x − 5 = 20",
                "两边同时加 5（等式性质 1）：5x = 25",
                "两边同时除以 5（等式性质 2）：x = 5",
                "检验：5 × (5 − 1) = 5 × 4 = 20，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "括号前系数的去括号 + 解方程（'含括号方程'）",
                "难度理由": "medium——去括号（5 乘每一项）与两步解方程",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "去括号漏乘（写 5x − 1）、25 − 5 算错、漏检验",
                "教学角色": "L2 套用——去括号系数处理的标准应用"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "解方程：2(3x − 1) = 10",
            "expected_answer": "x = 2（去括号：6x − 2 = 10；两边同时加 2：6x = 12；两边同时除以 6：x = 2；检验：2 × (3 × 2 − 1) = 2 × 5 = 10 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去括号：2 乘括号里每一项，2(3x − 1) = 6x − 2，方程变成 6x − 2 = 10",
                "两边同时加 2（等式性质 1）：6x = 12",
                "两边同时除以 6（等式性质 2）：x = 2",
                "检验：2 × (3 × 2 − 1) = 2 × 5 = 10，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "括号内含 x 项与常数的去括号（'含括号方程'，'去括号漏乘'的变式）",
                "难度理由": "medium——2 乘 (3x − 1) 需同时处理系数与负常数",
                "认知阶梯定位": "L3 变式（括号内更复杂）",
                "错因陷阱": "写 6x − 1（漏乘 −1——'去括号漏乘'）、10 + 2 算错",
                "教学角色": "变式核心——系数 × 括号内两项"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "解方程：3(x + 2) = 2(x + 5)（两边都有括号）",
            "expected_answer": "x = 4（去括号：3x + 6 = 2x + 10；移项：3x − 2x = 10 − 6；合并：x = 4；检验：3 × (4 + 2) = 18，2 × (4 + 5) = 18，左边 = 右边 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "两边分别去括号：3(x + 2) = 3x + 6，2(x + 5) = 2x + 10",
                "3x + 6 = 2x + 10，移项（两边同减 2x、同减 6 的简写，要变号）：3x − 2x = 10 − 6",
                "合并：x = 4",
                "检验：3 × 6 = 18，2 × 9 = 18，左边 = 右边 ✓"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "两边都有括号的方程（'含括号方程'，seed type'两边都有括号'）",
                "难度理由": "medium——两边分别去括号 + 移项两处变号",
                "认知阶梯定位": "L3 变式",
                "错因陷阱": "只去一边括号、移项不变号（写 2x + 3x = 10 + 6——'移项再错一次'）",
                "教学角色": "变式核心——'两边都有括号'标准形态"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "解方程：2(x + 3) + 3(x − 1) = 18（提示：先去括号，再合并同类项）",
            "expected_answer": "x = 3（去括号：2x + 6 + 3x − 3 = 18；合并同类项：5x + 3 = 18；两边同时减 3：5x = 15；两边同时除以 5：x = 3；检验：2 × 6 + 3 × 2 = 12 + 6 = 18 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "两处去括号：2(x + 3) = 2x + 6，3(x − 1) = 3x − 3",
                "2x + 6 + 3x − 3 = 18，合并同类项（2x + 3x = 5x，6 − 3 = 3）：5x + 3 = 18",
                "两边同时减 3：5x = 15；两边同时除以 5：x = 3",
                "检验：2 × (3 + 3) + 3 × (3 − 1) = 12 + 6 = 18，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "去括号 × 合并同类项混合（'含括号方程'×合并同类项前置）",
                "难度理由": "hard——两处去括号 + 合并同类项 + 移项四步",
                "认知阶梯定位": "L4 迁移——去括号（PARENTHESIS 前置）× 合并同类项",
                "错因陷阱": "去括号漏乘（2x + 6 写 2x + 3）、合并 2x + 3x 算错、常数 6 − 3 处理错",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——去括号与合并的综合"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "小明解方程 2(x − 1) = 8，得到 x = 5。请检验他的解是否正确，写出检验过程。",
            "expected_answer": "正确。把 x = 5 代入左边：2 × (5 − 1) = 2 × 4 = 8；右边也是 8。左边 = 右边，所以 x = 5 是方程 2(x − 1) = 8 的解，小明解对了。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "检验方法：把解代入方程，分别计算两边，看是否相等",
                "代入左边：2 × (5 − 1)，先算括号内：5 − 1 = 4，再乘：2 × 4 = 8",
                "右边 = 8，左边 = 右边 ✓",
                "所以 x = 5 是方程的解，小明解对了"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "代入检验 × 含括号方程（'含括号方程'×检验习惯桥接）",
                "难度理由": "hard——需先算括号内再乘（2 × (5 − 1)）并作判断",
                "认知阶梯定位": "L4 迁移——'代入检验'解题习惯",
                "错因陷阱": "只代一边、先乘后减（写 2 × 5 − 1 = 9）、检验后不下结论（'不检验'错因的正面示范）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——检验习惯落地"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "解方程 3(x + 1) = 12，先去括号得 3x + 3 = 12，再两边同时减去 3。计算：12 − 3",
            "expected_answer": "9",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "含括号方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去括号：3(x + 1) = 3x + 3，方程变成 3x + 3 = 12",
                "两边同时减去 3（等式性质 1）：3x + 3 − 3 = 12 − 3",
                "12 − 3 = 9，所以 3x = 9"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "去括号方程的同减检测（'含括号方程'）",
                "难度理由": "easy 检测——单步同减计算",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "算 12 + 3 = 15（同加代替同减——'移项不变号'的苗头）",
                "教学角色": "掌握档快速检测（sympy 验算同减环节 verified）"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "解方程：2(x + 3) = 3x + 4（全流程：去括号、移项、合并、系数化为 1）",
            "expected_answer": "x = 2（去括号：2x + 6 = 3x + 4；移项：2x − 3x = 4 − 6，得 −x = −2；系数化为 1：x = 2；检验：2 × (2 + 3) = 10，3 × 2 + 4 = 10，左边 = 右边 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "去括号：2(x + 3) = 2x + 6，得 2x + 6 = 3x + 4",
                "移项（要变号）：2x − 3x = 4 − 6，合并得 −x = −2",
                "系数化为 1：两边同时除以 −1，x = 2",
                "检验：2 × (2 + 3) = 10，3 × 2 + 4 = 10，左边 = 右边 ✓"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "去括号 + 移项 + 合并 + 系数化 1 全流程（'含括号方程'，diagnostic probe'4 道含括号方程'素材）",
                "难度理由": "hard——两处移项变号（2x − 3x、4 − 6）+ −x 化 1 的符号",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "移项不变号（写 2x + 3x = 4 + 6）、−x = −2 化 1 时符号错",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "小明解方程 2(x − 3) = 10：\n① 去括号得 2x − 3 = 10\n② 移项得 2x = 13\n③ 得 x = 6.5\n他哪一步做错了？（　）\nA. ① 去括号错了：2 要乘括号里的每一项，应为 2x − 6 = 10\nB. ② 移项错了\nC. ③ 系数化 1 错了\nD. 他没做错",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去括号规则：括号前的数乘括号里每一项",
                "2(x − 3) = 2 × x + 2 × (−3) = 2x − 6",
                "小明写成 2x − 3，漏乘了 −3（只乘了第一项）",
                "选 A；正确解为 2x − 6 = 10，2x = 16，x = 8"
            ],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "去括号漏乘的错因复测（'含括号方程'，'去括号漏乘'直接形态）",
                "难度理由": "medium 复测——定位第一步错误并说出正确去括号",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "选 B/C（被后续步骤带偏）、选 D（接受错误去括号）",
                "教学角色": "防'会背不会用'复测——头号错因的定点取证"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "解方程并检验：2(x − 3) + 5 = 3(x + 1) − 2",
            "expected_answer": "x = −2（去括号：2x − 6 + 5 = 3x + 3 − 2；合并：2x − 1 = 3x + 1；移项：2x − 3x = 1 + 1，得 −x = 2；系数化为 1：x = −2；检验：2 × (−2 − 3) + 5 = −5，3 × (−2 + 1) − 2 = −5，左边 = 右边 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含括号方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "两边分别去括号：2(x − 3) + 5 = 2x − 6 + 5，3(x + 1) − 2 = 3x + 3 − 2",
                "合并常数：2x − 1 = 3x + 1",
                "移项（要变号）：2x − 3x = 1 + 1，得 −x = 2，系数化为 1：x = −2",
                "检验：2 × (−5) + 5 = −10 + 5 = −5，3 × (−1) − 2 = −3 − 2 = −5，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 8,
            "design_rationale": {
                "考点": "两边括号 + 合并 + 负解 + 检验的综合复测（'含括号方程'，mastery'去括号正确率≥90%'取证）",
                "难度理由": "hard——两边去括号、常数合并（−6 + 5、3 − 2）、移项、负解、检验五处可错",
                "认知阶梯定位": "L4 复测",
                "错因陷阱": "去括号变号漏项（2x − 6 + 5 写 2x − 11）、移项不变号、检验代错",
                "教学角色": "复测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "去括号：3 − (x + 2)。下面哪个是正确的？（　）\nA. 3 − x − 2（负号乘进去，x 变 −x，2 变 −2）\nB. 3 − x + 2（2 没变号）\nC. 3 + x − 2（x 没变号）\nD. 3 − x",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去括号",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "括号前是负号，去掉括号时括号里每一项都变号",
                "3 − (x + 2) = 3 − x − 2（x 变 −x，2 变 −2）",
                "选 A"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "括号前负号的去括号诊断（'去括号'，'负号变号漏项'错因的直接探针）",
                "难度理由": "easy 诊断——单步变号分档",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 B（+2 没变号——'负号变号漏项'）、选 C（x 没变号）、选 D（漏掉 2）",
                "教学角色": "诊断题——负号去括号一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "去括号：−2(x − 3)。下面哪个是正确的？（　）\nA. −2x − 6（−3 没变号）\nB. −2x + 6（系数乘每一项，−3 变 +3）\nC. 2x + 6（丢了负号）\nD. −2x − 3（只乘了第一项）",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去括号",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "括号前是 −2：既要把 −2 乘每一项（系数），又要变号（负号）",
                "−2(x − 3) = −2 × x + (−2) × (−3) = −2x + 6",
                "选 B"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "负号 + 系数双规则的去括号诊断（'去括号'，'负号变号漏项'×'去括号漏乘'复合）",
                "难度理由": "medium 诊断——负号与系数两规则叠加",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "选 A（−3 没变号——'负号变号漏项'）、选 C（丢负号）、选 D（只乘第一项——'去括号漏乘'）",
                "教学角色": "诊断题——复合规则的错因分类探针"
            }
        },
    ],

    # ===== M-G7-EQ-DENOM 含分母方程（计算向：13 unverifiable + 2 verified） =====
    "M-G7-EQ-DENOM": [
        {
            "slot": "B1-I0",
            "prompt": "解方程：x/2 + 1 = 3（提示：先去分母，两边同时乘 2）",
            "expected_answer": "x = 4（去分母：两边同时乘 2，得 x + 2 = 6；两边同时减 2：x = 4；检验：4/2 + 1 = 2 + 1 = 3 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 2（等式性质 2），x/2 × 2 = x，1 × 2 = 2，3 × 2 = 6",
                "x + 2 = 6，两边同时减 2（等式性质 1）：x = 4",
                "检验：4/2 + 1 = 2 + 1 = 3，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "去分母解方程全流程（'含分母方程'，essence'每一项都乘最小公倍数'取证）",
                "难度理由": "medium 锚点——去分母（×2）→ 同减 → 检验完整流程",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；示范'两边同乘'与检验步）",
                "教学角色": "讲本质用——'分数方程变整数方程'的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "解方程 x/3 + 2 = 5，第一步去分母，应两边同时乘几？（　）\nA. 2\nB. 3（分母是 3，乘 3 才能消去分母）\nC. 5\nD. 6",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去分母",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去分母的目的：消去分母，把分数方程变整数方程",
                "只有 x/3 有分母 3，两边同时乘 3 即可消去",
                "选 B"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别去分母的乘数（'去分母'，分母是几就乘几）",
                "难度理由": "easy——单分母识别",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 A（把常数 2 当分母）、选 C（把右边 5 当分母）、选 D（乱乘）",
                "教学角色": "L1 识别脚手架——去分母第一关"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "解方程 x/2 + x/3 = 5，去分母应两边同时乘几？（　）\nA. 2\nB. 3\nC. 5\nD. 6（2 和 3 的最小公倍数）",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去分母",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "两个分母是 2 和 3，要乘它们的公倍数才能同时消去",
                "最小公倍数：2 和 3 互质，最小公倍数是 2 × 3 = 6",
                "选 D"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "找最简公分母（'去分母'，LCM 识别——'最小公倍数找错'错因的正面探针）",
                "难度理由": "easy——两分母最小公倍数",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 A/B（只取一个分母）、选 C（把常数 5 当公倍数）",
                "教学角色": "L1 识别——公分母识别"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "解方程 (x + 1)/2 = 4，去分母：两边同时乘 2，得 x + 1 = 8。计算：2 × 4",
            "expected_answer": "8",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "去分母",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 2（等式性质 2），分子 (x + 1) 整体保留",
                "左边：(x + 1)/2 × 2 = x + 1；右边：4 × 2 = 8",
                "2 × 4 = 8，所以 x + 1 = 8"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "去分母的乘法环节（'去分母'，分子整体乘——括号保护）",
                "难度理由": "easy 套用——识别'乘 2'后做一步乘法",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "算 4 ÷ 2 = 2（除代替乘）、2 × 4 算错",
                "教学角色": "L2 套用脚手架（sympy 验算同乘环节 verified）"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "解方程：x/3 + 1 = 4（先去分母，再解）",
            "expected_answer": "x = 9（去分母：两边同时乘 3，得 x + 3 = 12；两边同时减 3：x = 9；检验：9/3 + 1 = 3 + 1 = 4 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 3（每一项都乘）：x/3 × 3 = x，1 × 3 = 3，4 × 3 = 12",
                "x + 3 = 12，两边同时减 3：x = 9",
                "检验：9/3 + 1 = 3 + 1 = 4，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "去分母 + 解方程（'含分母方程'）",
                "难度理由": "medium——去分母（×3 不漏常数项）+ 两步解",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "漏乘常数 1（写 x + 1 = 12——'漏乘没有分母的项'）、12 − 3 算错",
                "教学角色": "L2 套用——去分母的标准应用"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "解方程：(x + 1)/2 + 3 = 6（提示：去分母时每一项都要乘 2）",
            "expected_answer": "x = 5（去分母：两边同时乘 2，得 x + 1 + 6 = 12；合并：x + 7 = 12；两边同时减 7：x = 5；检验：(5 + 1)/2 + 3 = 3 + 3 = 6 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 2，分子 (x + 1) 整体乘、常数 3 也要乘 2：x + 1 + 6 = 12",
                "合并：x + 7 = 12，两边同时减 7：x = 5",
                "检验：(5 + 1)/2 + 3 = 3 + 3 = 6，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "分子是多项式的去分母（'含分母方程'，'去分母后括号漏加'错因的直接形态）",
                "难度理由": "medium——(x + 1) 整体乘 + 常数项也要乘（×2 不漏项）",
                "认知阶梯定位": "L3 变式",
                "错因陷阱": "漏乘常数 3（写 x + 1 + 3 = 12——'漏乘没有分母的项'）、x + 7 合并错",
                "教学角色": "变式核心——'每一项都乘'的关键题"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "解方程：x/3 + x/6 = 3（分母不同，先找最小公倍数）",
            "expected_answer": "x = 6（找公分母：2 和 6 的最小公倍数是 6；去分母：两边同时乘 6，得 2x + x = 18；合并：3x = 18；两边同时除以 3：x = 6；检验：6/3 + 6/6 = 2 + 1 = 3 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "找公分母：3 和 6 的最小公倍数是 6",
                "去分母：两边同时乘 6，x/3 × 6 = 2x，x/6 × 6 = x，3 × 6 = 18，得 2x + x = 18",
                "合并：3x = 18，两边同时除以 3：x = 6",
                "检验：6/3 + 6/6 = 2 + 1 = 3，左边 = 右边 ✓"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "异分母方程找公分母 + 去分母（'含分母方程'，'最小公倍数找错'错因的战场）",
                "难度理由": "medium——最小公倍数（3、6）识别 + 每一项乘 6",
                "认知阶梯定位": "L3 变式",
                "错因陷阱": "公分母取 3 漏乘（写 x + x = 18）、2x + x 合并错",
                "教学角色": "变式核心——公分母与不漏项的整合"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "解方程：(x + 1)/2 = (x − 1)/3（提示：先找最小公倍数去分母，分子要加括号）",
            "expected_answer": "x = −5（去分母：两边同时乘 6（2 和 3 的最小公倍数），3(x + 1) = 2(x − 1)；去括号：3x + 3 = 2x − 2；移项：3x − 2x = −2 − 3，x = −5；检验：(−5 + 1)/2 = −2，(−5 − 1)/3 = −2，左边 = 右边 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "找公分母：2 和 3 的最小公倍数是 6，两边同时乘 6",
                "分子是多项式要加括号：3(x + 1) = 2(x − 1)（(x+1)/2 × 6 = 3(x+1)，(x−1)/3 × 6 = 2(x−1)）",
                "去括号：3x + 3 = 2x − 2；移项（要变号）：3x − 2x = −2 − 3，x = −5",
                "检验：(−5 + 1)/2 = −2，(−5 − 1)/3 = −2，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {
                "考点": "去分母 × 去括号 × 分数运算混合（'含分母方程'×分数运算前置）",
                "难度理由": "hard——最小公倍数（2、3）、分子加括号、去括号变号、负解四层",
                "认知阶梯定位": "L4 迁移——分数通分（FRACTION-OPS 前置）× 去分母",
                "错因陷阱": "去分母后分子不加括号（写 2x + 1 = 2x − 1）、去括号变号错、−2 − 3 算错",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——分数的分母处理全链"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "解方程：(x + 1)/0.3 = 10（分母是小数 0.3，去分母两边同时乘 0.3）",
            "expected_answer": "x = 2（去分母：两边同时乘 0.3，得 x + 1 = 10 × 0.3 = 3；两边同时减 1：x = 2；检验：(2 + 1)/0.3 = 3 ÷ 0.3 = 10 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "分母是小数 0.3，去分母就两边同时乘 0.3",
                "左边：(x + 1)/0.3 × 0.3 = x + 1；右边：10 × 0.3 = 3，得 x + 1 = 3",
                "两边同时减 1：x = 2",
                "检验：(2 + 1)/0.3 = 3 ÷ 0.3 = 10，左边 = 右边 ✓"
            ],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "分母是小数方程的转化（'含分母方程'，分母小数与分数小数互化）",
                "难度理由": "hard——小数分母（乘 0.3）与小数除法检验（3 ÷ 0.3）",
                "认知阶梯定位": "L4 迁移——分数与小数互化（FRACTION-OPS 前置）",
                "错因陷阱": "10 × 0.3 算错、3 ÷ 0.3 当 1（小数除法错）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——小数分母处理"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "解方程 (x − 2)/4 = 3，去分母：两边同时乘 4，得 x − 2 = 12。计算：3 × 4",
            "expected_answer": "12",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "去分母",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 4（等式性质 2），分子 (x − 2) 整体保留",
                "左边：(x − 2)/4 × 4 = x − 2；右边：3 × 4 = 12",
                "3 × 4 = 12，所以 x − 2 = 12"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "去分母的乘法检测（'去分母'）",
                "难度理由": "easy 检测——单步同乘计算",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "算 3 ÷ 4（除代替乘）、3 × 4 算错",
                "教学角色": "掌握档快速检测（sympy 验算同乘环节 verified）"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "解方程：x/2 + x/3 = 5（注意：去分母时每一项都要乘 6）",
            "expected_answer": "x = 6（找公分母：2 和 3 的最小公倍数是 6；去分母：两边同时乘 6，得 3x + 2x = 30；合并：5x = 30；两边同时除以 5：x = 6；检验：6/2 + 6/3 = 3 + 2 = 5 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "找公分母：2 和 3 的最小公倍数是 6",
                "去分母：两边同时乘 6（每一项都乘），x/2 × 6 = 3x，x/3 × 6 = 2x，5 × 6 = 30，得 3x + 2x = 30",
                "合并：5x = 30，两边同时除以 5：x = 6",
                "检验：6/2 + 6/3 = 3 + 2 = 5，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "异分母 + 不漏项的去分母检测（'含分母方程'，diagnostic probe'3 道含分母方程'素材）",
                "难度理由": "hard——最小公倍数（2、3）+ 右边常数 5 也要乘 6（漏乘陷阱）",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "漏乘右边 5（写 3x + 2x = 5——'漏乘没有分母的项'）、30 ÷ 5 算错",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "小明解方程 (x + 1)/2 + 3 = 5：\n① 去分母：x + 1 + 3 = 10\n② 合并：x + 4 = 10\n③ 得 x = 6\n他哪一步做错了？（　）\nA. ① 去分母错了：3 没有分母也要乘 2，应为 x + 1 + 6 = 10\nB. ② 合并错了\nC. ③ 系数化 1 错了\nD. 他没做错",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 2，每一项都要乘（包括没有分母的常数 3）",
                "正确：x + 1 + 6 = 10（(x+1)/2 × 2 = x+1，3 × 2 = 6，5 × 2 = 10）",
                "小明漏乘 3（写 x + 1 + 3），所以 ① 错",
                "选 A；正确解为 x + 7 = 10，x = 3"
            ],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "去分母漏乘常数项的错因复测（'含分母方程'，'漏乘没有分母的项'直接形态）",
                "难度理由": "medium 复测——定位去分母步骤的错误",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "选 B/C（被后续步骤带偏）、选 D（接受漏乘结果）",
                "教学角色": "防'会背不会用'复测——漏乘错因定点取证"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "解方程并检验：(x + 1)/2 − (x − 1)/4 = 2",
            "expected_answer": "x = 5（去分母：两边同时乘 4，2(x + 1) − (x − 1) = 8——分子要加括号；去括号：2x + 2 − x + 1 = 8；合并：x + 3 = 8；两边同时减 3：x = 5；检验：(5 + 1)/2 − (5 − 1)/4 = 3 − 1 = 2 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "含分母方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "找公分母：2 和 4 的最小公倍数是 4，两边同时乘 4，分子整体加括号",
                "(x + 1)/2 × 4 = 2(x + 1)，(x − 1)/4 × 4 = (x − 1)，2 × 4 = 8，得 2(x + 1) − (x − 1) = 8",
                "去括号（负号变号）：2x + 2 − x + 1 = 8，合并：x + 3 = 8，x = 5",
                "检验：(5 + 1)/2 − (5 − 1)/4 = 3 − 1 = 2，左边 = 右边 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {
                "考点": "去分母 + 括号保护 + 去括号变号 + 检验综合复测（'含分母方程'，mastery'每一项都乘不漏项'取证）",
                "难度理由": "hard——×4 去分母、2(x + 1) − (x − 1) 的括号与变号、合并、检验五处可错",
                "认知阶梯定位": "L4 复测",
                "错因陷阱": "去分母只乘带分母的项、−(x − 1) 变号漏（写 2x + 2 − x − 1）、检验算错",
                "教学角色": "复测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "解方程 x/2 + 3 = 7，第一步去分母，下面哪个说法正确？（　）\nA. 乘 2 得 x + 3 = 7（3 不用乘）\nB. 乘 2 得 x + 6 = 14（每一项都乘 2）\nC. 乘 3 得 x/2 + 9 = 21\nD. 不用乘，直接移项",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去分母",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 2，每一项都要乘（包括没有分母的 3 和 7）",
                "x/2 × 2 = x，3 × 2 = 6，7 × 2 = 14，得 x + 6 = 14",
                "选 B"
            ],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "去分母'每一项都乘'的诊断（'去分母'，'漏乘没有分母的项'直接探针）",
                "难度理由": "easy 诊断——单步分档",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 A（漏乘常数 3——'漏乘没有分母的项'）、选 C（乘到分子里）、选 D（不去分母）",
                "教学角色": "诊断题——漏乘错因一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "解方程 (x − 1)/3 + 2 = 4，第一步去分母，下面哪个是正确的？（　）\nA. x − 1 + 2 = 12（2 没乘 3）\nB. x − 1 + 6 = 12（每一项都乘 3，分子 (x − 1) 整体保留）\nC. 3x − 3 + 6 = 12（把 3 乘进分子里）\nD. x − 2 + 6 = 12（分子符号处理错）",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "去分母",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "去分母：两边同时乘 3，每一项都乘；分子 (x − 1) 是整体，乘 3 后仍是 (x − 1)",
                "(x − 1)/3 × 3 = x − 1，2 × 3 = 6，4 × 3 = 12，得 x − 1 + 6 = 12",
                "选 B"
            ],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "去分母正确步骤诊断（'去分母'，'去分母后括号漏加'的正面形态）",
                "难度理由": "medium 诊断——分子整体乘 + 常数项不漏乘双规则",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "选 A（漏乘常数 2）、选 C（把 3 乘进分子——括号漏加）、选 D（分子符号处理错）",
                "教学角色": "诊断题——去分母双规则的错因分类探针"
            }
        },
    ],

    # ===== M-G7-EQ-WORD 一元一次方程应用题（综合型：15 unverifiable） =====
    "M-G7-EQ-WORD": [
        {
            "slot": "B1-I0",
            "prompt": "妈妈买苹果和香蕉共花了 40 元，苹果比香蕉贵 10 元。设香蕉 x 元，列方程并求解，并检验你的答案。",
            "expected_answer": "香蕉 15 元，苹果 25 元。设香蕉 x 元，则苹果 (x + 10) 元；等量关系：香蕉的钱 + 苹果的钱 = 40；列方程 x + (x + 10) = 40；解得 2x = 30，x = 15；苹果 15 + 10 = 25（元）。检验：25 + 15 = 40，25 − 15 = 10，符合题意 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设香蕉 x 元，苹果比香蕉贵 10 元，则苹果 (x + 10) 元",
                "找等量关系：香蕉的钱 + 苹果的钱 = 一共的 40 元",
                "列方程：x + (x + 10) = 40，去括号合并：2x + 10 = 40，2x = 30，x = 15",
                "答：香蕉 15 元，苹果 15 + 10 = 25 元；检验：25 + 15 = 40，25 − 15 = 10，符合题意 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "和差模型应用题完整流程：设、列、解、验、答（'和差倍'，essence'设未知数→找等量关系→解方程→检验'取证）",
                "难度理由": "medium 锚点——完整流程示范（设 x → 和差关系 → 解 → 检验 → 答句）",
                "认知阶梯定位": "标准例题（L2 套用基准线）",
                "错因陷阱": "无（锚点题不埋陷阱；答案内嵌设列解答四步示范）",
                "教学角色": "讲本质用——'设列解答'全流程的演示载体"
            }
        },
        {
            "slot": "B1-I1",
            "prompt": "一本书小明第一天看了 x 页，第二天看的页数是第一天的 2 倍，两天一共看了 60 页。下面哪个等量关系是正确的？（　）\nA. 第一天页数 + 第二天页数 = 60，即 x + 2x = 60\nB. 第二天页数 − 第一天页数 = 60\nC. 第一天页数 × 第二天页数 = 60\nD. 第一天页数 = 60",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "审题：'一共看了 60 页'说明两天看的页数相加等于 60",
                "第一天 x 页，第二天是第一天的 2 倍即 2x 页",
                "等量关系：x + 2x = 60，选 A"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别应用题等量关系（'和差倍'，审题流程前置：先找'一共'关系）",
                "难度理由": "easy——等量关系识别，选项覆盖加减乘误用",
                "认知阶梯定位": "L1 识别正宗实现",
                "错因陷阱": "选 B（'一共'想成差）、选 C（倍数误用乘）、选 D（漏第二天）",
                "教学角色": "L1 识别脚手架——等量关系第一关"
            }
        },
        {
            "slot": "B1-I2",
            "prompt": "哥哥有 30 元，比弟弟的 2 倍少 4 元。设弟弟有 x 元，下面哪个方程是正确的？（　）\nA. 2x − 4 = 30（弟弟的 2 倍少 4 就是哥哥的 30 元）\nB. 2x + 4 = 30（把'少 4'读成'多 4'）\nC. 2x = 30（漏掉 4）\nD. x − 4 = 30",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "设弟弟 x 元，弟弟的 2 倍是 2x 元",
                "'比弟弟的 2 倍少 4 元'：哥哥的 30 元 = 2x − 4",
                "列方程：2x − 4 = 30，选 A"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "识别正确方程（设未知数 → 翻译'2 倍少 4'，'和差倍'，'数量关系列反'错因的直接形态）",
                "难度理由": "easy——四选一识别，'少 4'的方向是核心",
                "认知阶梯定位": "L1 识别",
                "错因陷阱": "选 B（'少'读成'多'——数量关系列反）、选 C（漏 4）",
                "教学角色": "L1 识别——倍差关系的翻译探针"
            }
        },
        {
            "slot": "B2-I0",
            "prompt": "学校图书角有 45 本故事书，是科技书的 3 倍。设科技书有 x 本，列方程并求解。",
            "expected_answer": "3x = 45，x = 15。答：科技书有 15 本。检验：15 × 3 = 45 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "设科技书 x 本，故事书是科技书的 3 倍即 3x 本",
                "等量关系：故事书本数 = 45，列方程 3x = 45",
                "两边同时除以 3：x = 15；答：科技书 15 本；检验：15 × 3 = 45 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "直接倍关系列方程并求解（'和差倍'）",
                "难度理由": "easy 套用——单步倍关系列式",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "列 45 = x/3（方向反）、45 ÷ 3 算错",
                "教学角色": "L2 套用脚手架——'谁是谁的几倍'翻译"
            }
        },
        {
            "slot": "B2-I1",
            "prompt": "一件商品打八折后售价 96 元。设原价为 x 元，列方程并求解。",
            "expected_answer": "0.8x = 96，x = 120。答：原价 120 元。检验：120 × 0.8 = 96 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "销售/打折",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "八折 = 原价的 80% = 0.8 倍",
                "设原价 x 元，等量关系：原价 × 0.8 = 售价 96，列方程 0.8x = 96",
                "两边同时除以 0.8：x = 96 ÷ 0.8 = 120；答：原价 120 元；检验：120 × 0.8 = 96 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "折扣百分数模型列方程（'销售/打折'×百分数模型前置）",
                "难度理由": "medium——八折 = 0.8 的转化 + 列方程",
                "认知阶梯定位": "L2 套用",
                "错因陷阱": "八折当 8（列 8x = 96）、96 ÷ 0.8 算错",
                "教学角色": "L2 套用——折扣百分数模型标准应用"
            }
        },
        {
            "slot": "B2-I2",
            "prompt": "把 45 名学生分成甲、乙两组参加植树，甲组人数是乙组的 2 倍少 6 人。设乙组有 x 人，列方程并求解。",
            "expected_answer": "乙组 17 人，甲组 28 人。设乙组 x 人，则甲组 (2x − 6) 人；等量关系：甲组 + 乙组 = 45；列方程 x + (2x − 6) = 45；解得 3x = 51，x = 17；甲组 2 × 17 − 6 = 28（人）。检验：17 + 28 = 45，28 = 2 × 17 − 6 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "配套/调配",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设乙组 x 人，甲组人数是乙组的 2 倍少 6 人，即 (2x − 6) 人",
                "等量关系：甲组 + 乙组 = 45，列方程 x + (2x − 6) = 45",
                "去括号合并：3x − 6 = 45，3x = 51，x = 17；甲组 2 × 17 − 6 = 28（人）",
                "答：乙组 17 人，甲组 28 人；检验：17 + 28 = 45，28 = 2 × 17 − 6 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "调配（分组）模型的倍差关系（'配套/调配'，'数量关系列反'错因的战场）",
                "难度理由": "medium——'2 倍少 6'的翻译 + 总和等量关系",
                "认知阶梯定位": "L3 变式",
                "错因陷阱": "写 x + (2x + 6) = 45（'少 6'列反）、3x − 6 移项错",
                "教学角色": "变式核心——调配模型的标准形态"
            }
        },
        {
            "slot": "B3-I0",
            "prompt": "某车间有 22 名工人生产零件，每人每天可生产甲种零件 1200 个或乙种零件 2000 个。甲、乙两种零件按 1 个甲配 2 个乙的比例配套，设生产甲种零件的工人有 x 人，列方程并求解。",
            "expected_answer": "生产甲种零件 10 人，生产乙种零件 12 人。设生产甲种零件 x 人，则生产乙种零件 (22 − x) 人；每天甲零件 1200x 个，乙零件 2000(22 − x) 个；配套比例 1 甲配 2 乙，即乙的个数 = 2 × 甲的个数；列方程 2000(22 − x) = 2 × 1200x；解得 44000 − 2000x = 2400x，4400x = 44000，x = 10；乙组 22 − 10 = 12（人）。检验：甲 10 × 1200 = 12000 个，乙 12 × 2000 = 24000 个，24000 = 2 × 12000 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "配套/调配",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设生产甲种零件 x 人，则生产乙种零件 (22 − x) 人",
                "每天产量：甲 1200x 个，乙 2000(22 − x) 个",
                "配套 1 甲配 2 乙：乙的个数 = 2 × 甲的个数，列方程 2000(22 − x) = 2 × 1200x",
                "去括号：44000 − 2000x = 2400x，4400x = 44000，x = 10；答：生产甲种零件 10 人、乙种 12 人；检验：12000 与 24000 满足 1:2 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "配套比例模型（1 甲配 2 乙 → 乙数 = 2 × 甲数，'配套/调配'）",
                "难度理由": "medium——设 x 人产甲 + 比例关系的符号化",
                "认知阶梯定位": "L3 变式",
                "错因陷阱": "比例列反（1200x = 2 × 2000(22 − x)）、漏'22 − x'",
                "教学角色": "变式核心——配套模型的比例翻译"
            }
        },
        {
            "slot": "B3-I1",
            "prompt": "甲、乙两地相距 540 千米，一辆客车和一辆货车同时从两地出发相向而行，客车的速度是货车的 2 倍，4 小时后两车相遇。货车每小时行多少千米？（列方程解答并检验）",
            "expected_answer": "货车每小时行 45 千米。设货车每小时行 x 千米，则客车每小时行 2x 千米；等量关系：货车 4 小时的路程 + 客车 4 小时的路程 = 540；列方程 4x + 4 × 2x = 540；解得 12x = 540，x = 45；答：货车每小时行 45 千米，客车每小时行 90 千米。检验：4 × 45 + 4 × 90 = 180 + 360 = 540 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "行程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "设货车每小时行 x 千米，客车速度是货车的 2 倍，即 2x 千米/时",
                "找等量关系：两车 4 小时的路程和 = 540（相向而行相遇）",
                "列方程：4x + 4 × 2x = 540，合并 12x = 540，x = 45；客车 2 × 45 = 90（千米/时）",
                "答：货车每小时行 45 千米；检验：4 × 45 + 4 × 90 = 180 + 360 = 540 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {
                "考点": "行程相遇模型 + 倍数关系的多步建模（'行程'×行程模型前置）",
                "难度理由": "hard——设 x、速度倍数、路程和、含括号方程、检验五步",
                "认知阶梯定位": "L4 迁移——行程模型（MOTION-BASIC 前置）的相遇形态",
                "错因陷阱": "等量关系写错（路程差代替路程和）、4(x + 2x) 展开错、12x = 540 算错",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——行程模型的综合应用"
            }
        },
        {
            "slot": "B3-I2",
            "prompt": "某商品标价 150 元，按标价的八折出售仍可获利 20 元。设进价为 x 元，列方程并求解。",
            "expected_answer": "进价 100 元。设进价为 x 元；先算售价：150 × 0.8 = 120（元）；等量关系：售价 − 进价 = 利润，120 − x = 20；解得 x = 100。答：进价为 100 元。检验：120 − 100 = 20 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "销售/打折",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "设进价为 x 元",
                "先算售价：按标价 150 元打八折，150 × 0.8 = 120（元）",
                "等量关系：售价 − 进价 = 利润，120 − x = 20",
                "解得 x = 100；答：进价为 100 元；检验：120 − 100 = 20 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {
                "考点": "折扣 + 利润模型（'销售/打折'×百分数模型前置）",
                "难度理由": "hard——先算售价（折扣）再列利润关系，两步建模",
                "认知阶梯定位": "L4 迁移——百分数模型（PERCENT-MODEL 前置）的销售形态",
                "错因陷阱": "把利润当售价（列 x = 20）、八折计算错（150 × 0.8 = 120 算错）",
                "教学角色": "判定层 transfer 证据来源（C3 双角色）——折扣利润综合"
            }
        },
        {
            "slot": "B4-I0",
            "prompt": "食堂运来 50 千克大米，吃了 x 千克后还剩 18 千克。列方程并求解。",
            "expected_answer": "x = 32，吃了 32 千克。列方程：50 − x = 18；解得 x = 50 − 18 = 32。答：吃了 32 千克。检验：50 − 32 = 18 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "等量关系：运来的 − 吃了的 = 剩下的，50 − x = 18",
                "移项：x = 50 − 18 = 32",
                "答：吃了 32 千克；检验：50 − 32 = 18 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {
                "考点": "简单差值模型列方程并求解（'和差倍'，mastery'能完整写出设列解答'取证）",
                "难度理由": "easy 检测——单步差关系",
                "认知阶梯定位": "L2 检测",
                "错因陷阱": "列 x − 18 = 50（剩余方向反）、50 − 18 算错",
                "教学角色": "掌握档快速检测——设列解答流程探针"
            }
        },
        {
            "slot": "B4-I1",
            "prompt": "一辆汽车从甲城开往乙城，前 2 小时每小时行 60 千米，后 3 小时每小时行 x 千米，全程共 330 千米。列方程解答并检验。",
            "expected_answer": "后 3 小时每小时行 70 千米。设后 3 小时每小时行 x 千米；等量关系：前段路程 + 后段路程 = 全程，2 × 60 + 3x = 330；解得 120 + 3x = 330，3x = 210，x = 70。答：后 3 小时每小时行 70 千米。检验：2 × 60 + 3 × 70 = 120 + 210 = 330 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "行程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "设后 3 小时每小时行 x 千米",
                "前段路程：2 × 60 = 120（千米）；后段路程：3x（千米）",
                "等量关系：前段 + 后段 = 全程，120 + 3x = 330",
                "3x = 210，x = 70；答：后 3 小时每小时行 70 千米；检验：120 + 210 = 330 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {
                "考点": "行程分段建模 + 检验（'行程'×行程模型前置，diagnostic probe'写设列解答'素材）",
                "难度理由": "hard——前段 + 后段 = 全程的等量关系 + 三步解 + 检验",
                "认知阶梯定位": "L3 检测 hard",
                "错因陷阱": "漏前段（列 3x = 330）、330 − 120 算错、不检验",
                "教学角色": "检测 hard 档，判定层 hard 证据来源"
            }
        },
        {
            "slot": "B4-I2",
            "prompt": "爸爸今年 40 岁，恰好比儿子年龄的 4 倍多 8 岁。儿子今年多少岁？（列方程解答并检验）",
            "expected_answer": "儿子 8 岁。设儿子今年 x 岁；等量关系：儿子年龄的 4 倍多 8 = 爸爸的 40 岁，4x + 8 = 40；解得 4x = 32，x = 8。答：儿子今年 8 岁。检验：4 × 8 + 8 = 40 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设儿子今年 x 岁，儿子的 4 倍是 4x 岁",
                "等量关系：4 倍多 8 = 爸爸年龄，4x + 8 = 40",
                "4x = 32，x = 8；答：儿子今年 8 岁；检验：4 × 8 + 8 = 40 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {
                "考点": "年龄差倍模型的复测（'和差倍'，防'会背不会用'）",
                "难度理由": "medium 复测——'4 倍多 8'的翻译 + 解 + 检验",
                "认知阶梯定位": "L3 复测",
                "错因陷阱": "写 4x − 8 = 40（'多 8'列反）、40 − 8 算错",
                "教学角色": "复测 medium——倍差关系防退化取证"
            }
        },
        {
            "slot": "B5-I0",
            "prompt": "小明从家步行去学校，去时速度是 60 米/分，回家时速度是 40 米/分，来回一共用了 50 分钟。小明家到学校的路程是多少米？（列方程解答并检验）",
            "expected_answer": "家到学校 1200 米。设路程为 x 米；去时时间 x/60 分钟，回时时间 x/40 分钟；等量关系：去时时间 + 回时时间 = 50，x/60 + x/40 = 50；去分母：两边同时乘 120，得 2x + 3x = 6000；5x = 6000，x = 1200。答：家到学校 1200 米。检验：1200 ÷ 60 + 1200 ÷ 40 = 20 + 30 = 50 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "行程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "设路程为 x 米；时间 = 路程 ÷ 速度，去时时间 x/60 分，回时时间 x/40 分",
                "等量关系：去时时间 + 回时时间 = 总时间 50，列方程 x/60 + x/40 = 50",
                "去分母：60 和 40 的最小公倍数是 120，两边乘 120：2x + 3x = 6000，5x = 6000，x = 1200",
                "答：家到学校 1200 米；检验：1200 ÷ 60 + 1200 ÷ 40 = 20 + 30 = 50 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {
                "考点": "往返行程 + 分数方程的综合复测（'行程'×去分母前置，'单位不统一'错因的正面战场）",
                "难度理由": "hard——时间 = 路程 ÷ 速度、去分母（×120）、单位一致性三处可错",
                "认知阶梯定位": "L4 复测",
                "错因陷阱": "把 50 分钟当小时（单位不统一）、x/60 + x/40 去分母漏乘、6000 ÷ 5 算错",
                "教学角色": "复测 hard 档，判定层 hard 证据来源——应用题 + 分数方程综合"
            }
        },
        {
            "slot": "B5-I1",
            "prompt": "解完方程得到 x = 6，题目问的是'苹果有多少千克'。下面哪个答句是对的？（　）\nA. 苹果有 6 千克\nB. 苹果有 6 个\nC. 答：6\nD. 不用答，x = 6 就是答案",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "审题建模",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "应用题最后要把 x 的值翻译回问题里的量，并带上单位",
                "题目问'苹果有多少千克'，单位是千克，所以答'苹果有 6 千克'",
                "选 A"
            ],
            "error_tags": ["modeling_or_reading", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {
                "考点": "答句规范的诊断（'审题建模'，'单位与答句缺失'错因的直接探针）",
                "难度理由": "easy 诊断——答句选择分档",
                "认知阶梯定位": "L1 诊断",
                "错因陷阱": "选 B（单位错——'单位与答句缺失'）、选 C/D（漏单位或漏答句）",
                "教学角色": "诊断题——答句规范一键探针"
            }
        },
        {
            "slot": "B5-I2",
            "prompt": "小刚解应用题：'甲数是乙数的 3 倍多 2，甲数是 20，求乙数。'他设乙数为 x，列的方程是 3x − 2 = 20。他错在哪里？（　）\nA. 等量关系列反了：'乙数的 3 倍多 2'应写成 3x + 2，正确方程是 3x + 2 = 20\nB. 设未知数设错了：应该设甲数为 x\nC. 他没有错，3x − 2 = 20 是对的\nD. 应该列方程 2x + 3 = 20（把'3 倍'和'多 2'写反了）",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和差倍",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设乙数为 x，乙数的 3 倍是 3x，'多 2'要加 2，即 3x + 2",
                "等量关系：乙数的 3 倍多 2 = 甲数 20，正确方程 3x + 2 = 20",
                "小刚写 3x − 2 = 20 把'多 2'列成了'少 2'（数量关系列反）",
                "选 A；正确解：3x = 18，x = 6"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {
                "考点": "等量关系列反的诊断（'和差倍'，'等量关系找错/数量关系列反'错因的直接形态）",
                "难度理由": "medium 诊断——定位方程错误并改正",
                "认知阶梯定位": "L2 诊断",
                "错因陷阱": "选 C（接受错误方程）、选 B（设未知数归因错）、选 D（倍数与加数互换）",
                "教学角色": "诊断题——节点头号错因'等量关系找错'探针"
            }
        },
    ],

    # ===== M-G7-GEO-SOLID-PLANE 立体图形与平面图形（概念向：14 unverifiable + 1 verified 欧拉公式） =====
    # 节点契约：essence="复杂图形可以从点、线、面、体这些基本元素看"；seed=识别立体和平面/展开图/从不同方向看；
    # common_mistakes=展开图想象弱/立体和平面关系不清/看图只凭感觉；diagnostic_probes=3道图形识别、2道展开图判断。
    # authoring 原则（琢玉教训）：L1 真识别（判断图形类别而非直接算）；hard 真难（逆向计数/多语句核验/欧拉公式拓展）；
    # 句式 ≤2；计数题干扰项逐个对应常见错因（漏底面/侧棱数错/顶点误算）；概念题 unverifiable，
    # 唯一 verified 是欧拉公式代入的数值环节（sympy 真验算）。
    "M-G7-GEO-SOLID-PLANE": [
        {
            "slot": "B1-I0",
            "prompt": "把下面这些图形分成两类：长方体、三角形、圆柱、圆、正方体、圆锥。\n立体图形：____\n平面图形：____",
            "expected_answer": "立体图形：长方体、圆柱、正方体、圆锥；平面图形：三角形、圆",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["立体图形：各部分不都在同一平面内（占有空间），如长方体、圆柱、正方体、圆锥", "平面图形：各部分都在同一平面内，如三角形、圆", "所以立体图形 4 个：长方体、圆柱、正方体、圆锥；平面图形 2 个：三角形、圆"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "立体图形与平面图形的分类（按'各部分是否在同一平面内'判断）", "难度理由": "medium 锚点——分类是节点核心子技能，需按定义判断而非凭形状感觉", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'圆是平面图形'易被误当立体，在 B1-I1/B1-I2 单独布点）", "教学角色": "讲本质用——'各部分是否在同一平面内'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下面图形中，是平面图形的是（　）\nA. 球\nB. 圆柱\nC. 五边形\nD. 长方体",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["平面图形：各部分都在同一个平面内", "球、圆柱、长方体都占有空间，是立体图形", "五边形画在平面上，是平面图形，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别平面图形（五边形 vs 常见立体图形）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "把'圆滑的球/圆柱'当平面图形、凭立体感判断（'立体和平面关系不清'）", "教学角色": "概念识别脚手架"},
        },
        {
            "slot": "B1-I2",
            "prompt": "判断：'正方形是平面图形，正方体也是平面图形。'这个说法（　）\nA. 正确\nB. 错误，正方体是立体图形\nC. 错误，正方形是立体图形\nD. 错误，两个都是立体图形",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["正方形只是一个面，是平面图形", "正方体由 6 个正方形面围成，占有空间，是立体图形", "说法错在把正方体当平面图形，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "正方形（平面）与正方体（立体）的区分", "难度理由": "easy（L1 概念判断）", "认知阶梯定位": "L1 识别——判断说法对错，须经概念判断", "错因陷阱": "名字相近混为一谈（'立体和平面关系不清'节点错因）", "教学角色": "概念识别脚手架——破除'名字像就是同类'"},
        },
        {
            "slot": "B2-I0",
            "prompt": "下面这些实物的形状分别是什么立体图形？\n① 篮球　② 粉笔盒　③ 尖顶帐篷（四棱锥形）　④ 生日帽（圆锥形）",
            "expected_answer": "① 球　② 长方体　③ 四棱锥　④ 圆锥",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["从实物中抽象出形状（把实物看成几何体）", "篮球的形状是球，粉笔盒的形状是长方体", "四棱锥形帐篷→四棱锥，圆锥形生日帽→圆锥"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "从实物抽象出立体图形", "难度理由": "easy（L2 直接对应）", "认知阶梯定位": "L2 套用——实物→图形映射", "错因陷阱": "只凭感觉看图、把形状与实物混（'看图只凭感觉'）", "教学角色": "实物抽象套用——衔接小学'认识图形'经验"},
        },
        {
            "slot": "B2-I1",
            "prompt": "一个五棱柱有多少个面？多少条棱？多少个顶点？",
            "expected_answer": "7 个面、15 条棱、10 个顶点",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["五棱柱有 2 个五边形的底面和 5 个长方形的侧面，面数 = 2 + 5 = 7", "棱数：上底 5 条 + 下底 5 条 + 侧棱 5 条 = 15 条", "顶点数：上底 5 个 + 下底 5 个 = 10 个", "一般规律：n 棱柱有 n+2 个面、3n 条棱、2n 个顶点"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "棱柱的面/棱/顶点计数（含规律 n 棱柱 n+2 面、3n 棱、2n 顶点）", "难度理由": "medium——三量计数 + 规律提取，需分上下底与侧面", "认知阶梯定位": "L2 套用", "错因陷阱": "面数漏 2 个底面（把 5 当总面数）、侧棱漏数（'面数棱数数错'）", "教学角色": "棱柱计数标准变式"},
        },
        {
            "slot": "B2-I2",
            "prompt": "一个六棱锥有多少个面？多少条棱？多少个顶点？",
            "expected_answer": "7 个面、12 条棱、7 个顶点",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["六棱锥有 1 个六边形的底面和 6 个三角形的侧面，面数 = 1 + 6 = 7", "棱数：底面 6 条 + 侧棱 6 条 = 12 条", "顶点数：底面 6 个 + 锥顶 1 个 = 7 个", "对比：n 棱柱 n+2 面，n 棱锥 n+1 面——棱锥只有一个底面"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "棱锥的面/棱/顶点计数（与棱柱规律对比）", "难度理由": "medium——换图形换规律（柱→锥），沿用棱柱规律会错", "认知阶梯定位": "L3 变式——同一计数任务换立体类型", "错因陷阱": "按棱柱规律算（把 2 个底面当 2 个面，得 8 面）、顶点漏锥顶（'面数棱数数错'）", "教学角色": "变式核心层——柱锥规律对照"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法正确的是（　）\nA. 圆柱的底面是圆，所以圆柱是平面图形\nB. 球的表面是曲面，所以球不是立体图形\nC. 长方体由 6 个长方形的面围成，这些面都是平面图形\nD. 圆锥的侧面是三角形",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["立体图形的面可以是平面图形：圆柱的底面是圆（平面图形），但圆柱本身是立体图形，A 错", "球由曲面围成，但球占有空间，是立体图形，B 错", "长方体的每个面都是长方形（平面图形），C 对", "圆锥的侧面是曲面，展开才是扇形，不是三角形，D 错"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "立体图形与它的面（平面/曲面）的关系辨析", "难度理由": "medium——每个选项都需区分'图形的面'与'图形本身'", "认知阶梯定位": "L3 变式——从分类到关系辨析", "错因陷阱": "把'有平面图形的面'当成平面图形（'立体和平面关系不清'）", "教学角色": "高辨析度变式题——核心错因集中布点"},
        },
        {
            "slot": "B3-I1",
            "prompt": "做一个圆柱形笔筒（无盖），底面半径是 5 厘米，高是 10 厘米。做这个笔筒需要算哪几个面的面积？其中侧面展开是一个长方形，它的长和宽分别是多少？",
            "expected_answer": "需要算 1 个底面圆的面积和 1 个侧面的面积；侧面展开的长方形长 = 底面周长 = 10π 厘米（约 31.4 厘米），宽 = 高 = 10 厘米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["笔筒无盖：只有 1 个底面（圆）和 1 个侧面，不需要 2 个底面", "圆柱侧面展开是长方形：长 = 底面周长 = 2×π×5 = 10π 厘米", "宽 = 圆柱的高 = 10 厘米", "所以侧面积 = 10π×10 = 100π 平方厘米，总面积 = 25π + 100π = 125π 平方厘米（本题只问面组成与长宽）"],
            "error_tags": ["modeling_or_reading", "visual_spatial"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "立体图形的面组成判断 × 侧面展开图的长宽（迁移前置节点面积/周长公式）", "难度理由": "hard——无盖少一个底面 + 侧面展开长=底面周长两步推理", "认知阶梯定位": "L4 迁移——立体图形认识 × 圆周长公式（GEO-AREA-VOLUME 前置）", "错因陷阱": "无盖忘减底面、侧面展开的长用半径或直径（'展开图想象弱'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "一个多面体有 8 个顶点、12 条棱。欧拉公式 V−E+F=2（V 是顶点数、E 是棱数、F 是面数）可以求出它的面数：F = 2 + E − V。计算：2 + 12 − 8，求出这个多面体的面数。",
            "expected_answer": "6",
            "answer_format": "text",
            "verification_intent": "verified",
            "question_type": "欧拉公式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["把 V = 8、E = 12 代入欧拉公式 V−E+F=2", "由 F = 2 + E − V 得 F = 2 + 12 − 8", "计算：2 + 12 − 8 = 6", "这个多面体有 6 个面（比如一个长方体就有 8 个顶点、12 条棱、6 个面）"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "欧拉公式 V−E+F=2 的应用（拓展），代入后的数值计算环节可机算 verified", "难度理由": "hard——公式本身是拓展内容 + 需正确代入 V、E", "认知阶梯定位": "L4 迁移——计数规律的形式化推广", "错因陷阱": "V、E 代反（8−12）导致负号处理错（'calculation_or_symbol'）", "教学角色": "判定层 hard/verified 证据来源（sympy 验算 verified）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "一个长方体有（　）个面。\nA. 4\nB. 6\nC. 8\nD. 12",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["长方体由 2 个相对的面（上、下）+ 4 个侧面组成", "面数 = 2 + 4 = 6", "容易混：棱有 12 条、顶点有 8 个，但面只有 6 个，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长方体面数的直接检测（面/棱/顶点三量区分）", "难度理由": "easy 检测——单量直接计数", "认知阶梯定位": "L2 检测", "错因陷阱": "把棱数 12 或顶点数 8 当成面数（'面数棱数数错'）", "教学角色": "掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "一个棱柱一共有 18 条棱。这个棱柱的底面是几边形？它有多少个顶点？",
            "expected_answer": "底面是六边形（六棱柱），有 12 个顶点",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["n 棱柱有 3n 条棱（上底 n + 下底 n + 侧棱 n）", "3n = 18，n = 6，所以是六棱柱，底面是六边形", "顶点数 = 2n = 2×6 = 12 个"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "由棱数反推棱柱的底面边数与顶点数（规律逆向）", "难度理由": "hard——先列 3n=18 解 n，再算 2n，两步推理", "认知阶梯定位": "L3 检测——计数规律逆向应用", "错因陷阱": "18÷2=9 当侧面数、棱数与顶点数混淆", "教学角色": "检测 hard 档——判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "下列说法正确的是（　）\nA. 四棱柱有 8 个面\nB. 三棱锥有 6 条棱\nC. 六棱柱有 7 个面\nD. 五棱锥有 10 个顶点",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["四棱柱面数 = 2+4 = 6，A 错", "三棱锥：1 底面 + 3 侧面 = 4 面，棱 = 3+3 = 6，B 对", "六棱柱面数 = 2+6 = 8，C 错", "五棱锥顶点 = 5+1 = 6，D 错"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "柱/锥计数规律的多项核验", "难度理由": "medium——逐项核对 4 个计数断言", "认知阶梯定位": "L3 复测——防'会背不会用'（背了规律但用错 n）", "错因陷阱": "棱柱面数少加 2、棱锥顶点漏锥顶", "教学角色": "复测题——掌握确认真实性"},
        },
        {
            "slot": "B5-I0",
            "prompt": "下列说法错误的是（　）\nA. 五棱柱有 7 个面、15 条棱、10 个顶点\nB. 三棱锥有 4 个面、6 条棱、4 个顶点\nC. 圆柱有 3 个面、0 条棱、0 个顶点\nD. 圆锥有 2 个面、1 条棱、1 个顶点",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["A：五棱柱 n+2=7 面、3n=15 棱、2n=10 顶点，正确", "B：三棱锥 4 面、6 棱、4 顶点，正确", "C：圆柱 2 个圆面 + 1 个曲面 = 3 面，没有棱和顶点，正确", "D：圆锥有 1 个顶点（锥尖），但圆锥没有棱——底面圆周不是棱，D 错", "所以错误的是 D"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "多面体与曲面体（圆柱/圆锥）的面棱顶点综合核验", "难度理由": "hard——4 项 × 3 量共 12 个计数点，还要区分曲面体无棱", "认知阶梯定位": "L4 复测——规律 + 曲面体特殊性综合", "错因陷阱": "把圆锥底面圆周当棱、圆柱算成有顶点", "教学角色": "复测 hard 档——判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "把下面这些图形分成两类：球、圆锥、正方体、三角形、长方形、圆。\n立体图形有：____\n平面图形有：____",
            "expected_answer": "立体图形：球、圆锥、正方体；平面图形：三角形、长方形、圆",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "识别立体和平面",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["立体图形占有空间：球、圆锥、正方体", "平面图形只在一个平面内：三角形、长方形、圆", "注意圆是平面图形（曲线围成），不是立体图形"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "立体/平面图形分类诊断（含'圆是平面图形'的判定）", "难度理由": "easy——诊断 probe'图形识别'的开放分类形态", "认知阶梯定位": "L1 诊断——不经运算、直接概念判断", "错因陷阱": "把圆当立体图形、漏分（'立体和平面关系不清'）", "教学角色": "诊断题——分类能力一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "一个三棱柱有（　）\nA. 5 个面、9 条棱、6 个顶点\nB. 4 个面、9 条棱、6 个顶点\nC. 5 个面、12 条棱、6 个顶点\nD. 5 个面、9 条棱、8 个顶点",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面棱顶点计数",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["三棱柱：2 个三角形底面 + 3 个长方形侧面 = 5 个面", "棱 = 3+3+3 = 9 条", "顶点 = 3+3 = 6 个", "选 A；B 少算底面、C 多算棱（12=4×3 误算）、D 多算顶点"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "三棱柱三量计数的诊断（含干扰项成因分析）", "难度理由": "medium——选择形式 + 3 个干扰项各对应一种常见错误", "认知阶梯定位": "L2 诊断", "错因陷阱": "漏底面（B）、侧棱误算 4×3（C）、顶点误算（D）（'面数棱数数错'）", "教学角色": "诊断题——计数错因探针"},
        },
    ],
    # ===== M-G7-POINT-LINE-PLANE 点线面体（概念向：15 unverifiable） =====
    # 节点契约：essence="体由面围成，面与面相交成线，线与线相交成点"；seed=点动成线/线动成面/面动成体/元素关系；
    # common_mistakes=概念背诵但不会举例/点线面体关系混乱；diagnostic_probes=用生活例子说明点线面体关系；
    # mastery=能举例解释四者关系。authoring 原则（琢玉教训）：L1 真识别（运动/关系判断而非直接算）；
    # hard 真难（旋转体综合辨析/三量反推/多语句核验/开放解释）；旋转题矩形→圆柱、直角三角→圆锥各 1，
    # 平移/旋转辨析在复测单独布点，避免同套路连刷；旋转体想象与'动成什么方向反'错因全覆盖。
    "M-G7-POINT-LINE-PLANE": [
        {
            "slot": "B1-I0",
            "prompt": "一个长方体纸盒有 6 个面、12 条棱、8 个顶点。填空：体由____围成；面与面相交成____；线与线相交成____。",
            "expected_answer": "面；线（棱）；点",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["长方体这个'体'由 6 个面围成", "面与面相交得到棱，棱是线", "棱与棱相交得到顶点，顶点是点", "所以：体由面围成，面与面相交成线，线与线相交成点"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "点线面体的基本关系（体由面围成、面面相交成线、线线相交成点）", "难度理由": "medium 锚点——本质句的填空应用", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；关系混淆在 B3-I0 单独布点）", "教学角色": "讲本质用——节点 essence 的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下列现象中，属于'点动成线'的是（　）\nA. 用笔尖在纸上画一条线\nB. 旋转门转动\nC. 雨刷器刷过车窗\nD. 风扇的叶片转动",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "点动成线",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["笔尖看作一个点，移动画出的痕迹是线：点动成线，A 对", "旋转门：门板（面）绕轴转动扫过空间，是面动成体", "雨刷器：刷条（线）摆动扫过车窗，是线动成面", "风扇叶片：叶片（线）转动扫出圆面，是线动成面"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'点动成线'（运动观点）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "把线动成面（雨刷/风扇）或面动成体（旋转门）误当点动成线（'点线面体关系混乱'）", "教学角色": "概念识别脚手架"},
        },
        {
            "slot": "B1-I2",
            "prompt": "数学书（长方体）的一条棱，是相邻两个面的公共边。这说明（　）\nA. 面与面相交得到线\nB. 线与线相交得到点\nC. 点动成线\nD. 线动成面",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["棱是长方体相邻两个面的公共边", "两个面相交，公共部分是棱（线）", "所以：面与面相交得到线，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "从实物中识别'面面相交成线'（棱的由来）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别——观察实物对应关系", "错因陷阱": "把棱与顶点混淆（线与点）、运动规律套用（'点线面体关系混乱'）", "教学角色": "概念识别脚手架——'棱从哪来'"},
        },
        {
            "slot": "B2-I0",
            "prompt": "一条线段在平面内沿与它垂直的方向平移，扫过的区域形成什么图形？这说明什么运动规律？",
            "expected_answer": "形成长方形（面）；这说明了'线动成面'",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线动成面",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["线段是线，线沿一个方向移动", "移动扫过的区域是一个长方形（面）", "所以：线动成面"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "线动成面的运动观点套用", "难度理由": "easy（L2 直接套用运动规律）", "认知阶梯定位": "L2 套用——运动结果与规律的对应", "错因陷阱": "把扫过区域想成体、规律记反（'动成什么方向反'）", "教学角色": "运动观点脚手架"},
        },
        {
            "slot": "B2-I1",
            "prompt": "把一个长方形纸片绕它的一条长边旋转一周，扫过的空间形成什么立体图形？",
            "expected_answer": "圆柱",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面动成体",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["长边固定不动，作为旋转轴", "另一条边绕轴旋转扫出一个圆面", "整个长方形扫过的空间是圆柱（轴是圆柱的高）"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "面动成体（长方形绕边旋转一周→圆柱）", "难度理由": "medium——旋转体需空间想象（'旋转体想象不出'错因）", "认知阶梯定位": "L2 套用——面动成体的标准形态", "错因陷阱": "认为得到长方体、把旋转当平移（'动成什么方向反'）", "教学角色": "面动成体标准套用——圆柱=矩形旋转的迁移锚点"},
        },
        {
            "slot": "B2-I2",
            "prompt": "把一个直角三角形纸片绕它的一条直角边旋转一周，扫过的空间形成（　）\nA. 圆柱\nB. 圆锥\nC. 三棱锥\nD. 三棱柱",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面动成体",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["直角边固定作轴，另一条直角边绕轴扫出圆面", "斜边扫出圆锥的侧面（曲面）", "所以得到圆锥，选 B；三棱锥是把三角形平移才得到（混淆旋转与平移）"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "面动成体变式（直角三角形绕直角边→圆锥）", "难度理由": "medium——换图形（矩形→三角）换结果（圆柱→圆锥）", "认知阶梯定位": "L3 变式——旋转体类型变化", "错因陷阱": "选三棱锥（把旋转当平移）、沿用矩形结论选圆柱（'动成什么方向反'）", "教学角色": "变式核心层——旋转 vs 平移辨析"},
        },
        {
            "slot": "B3-I0",
            "prompt": "下列说法正确的是（　）\nA. 线动成体\nB. 面与面相交得到点\nC. 点动成面\nD. 面与面相交得到线",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["线动成面（不是体），A 错", "面与面相交得到线（不是点），B 错", "点动成线（不是面），C 错", "面与面相交得到线，D 对"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "点线面体关系正误辨析（运动规律 × 相交规律）", "难度理由": "medium——每个选项都要复核'动/相交'的主宾关系", "认知阶梯定位": "L3 变式——从识别到辨析", "错因陷阱": "把运动规律和相交规律互相串（'点线面体关系混乱'）", "教学角色": "高辨析度变式题——核心错因集中布点"},
        },
        {
            "slot": "B3-I1",
            "prompt": "下列说法正确的是（　）\nA. 直角三角形绕斜边旋转一周得到圆锥\nB. 半圆绕直径旋转一周得到球\nC. 长方形绕对角线旋转一周得到圆柱\nD. 正方形平移扫过得到球",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面动成体",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["直角三角形绕斜边旋转：得到两个底面重合的圆锥（像陀螺），不是单个圆锥，A 错", "半圆绕直径旋转一周：半圆弧扫出球面，得到球，B 对", "长方形绕对角线旋转：得不到规整的圆柱，C 错", "正方形平移扫过得到长方体（四棱柱），不是球，D 错"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "旋转体综合辨析（绕不同轴/不同图形的结果，迁移到立体图形认识）", "难度理由": "hard——4 个旋转/平移情境都需空间想象验证", "认知阶梯定位": "L4 迁移——面动成体 × 立体图形认识（GEO-SOLID-PLANE 前置）", "错因陷阱": "半圆绕直径想成半球、斜边旋转想成单个圆锥（'旋转体想象不出'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "一个几何体由 5 个面围成，相邻的面两两相交得到 9 条棱，棱与棱相交得到 6 个顶点。这个几何体是（　）\nA. 长方体\nB. 三棱柱\nC. 四棱锥\nD. 圆柱",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["'相邻面相交成棱'：5 个面 → 9 条棱（面面相交的公共边）", "三棱柱：2 个三角形底面 + 3 个侧面 = 5 个面，棱 3×3 = 9，顶点 2×3 = 6", "长方体 6 面、四棱锥 5 面 8 棱 5 顶点、圆柱没有棱，均不符合", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "由面/棱/顶点数量反推几何体（元素关系 × 计数，迁移到立体图形认识）", "难度理由": "hard——三量同时约束 + 4 个图形逐一核验", "认知阶梯定位": "L4 迁移——点线面体关系 × 棱柱棱锥计数（前置节点混合）", "错因陷阱": "四棱锥 5 面 8 棱与条件'9 棱'不符被忽略、只对'面数 5'就选（'点线面体关系混乱'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B4-I0",
            "prompt": "判断：'电风扇转动时，叶片扫过的区域近似一个圆面，这是线动成面。'这个说法（　）\nA. 正确\nB. 错误，这是点动成线\nC. 错误，这是面动成体\nD. 错误，这是点动成面",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "线动成面",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["叶片可看作一条线（线段）", "转动时扫过的区域是圆面", "线动成面，说法正确，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "线动成面的情境判断（电风扇扫出圆面）", "难度理由": "easy 检测——判断说法 + 排除干扰规律", "认知阶梯定位": "L2 检测", "错因陷阱": "选 C（把扫过的'区域'当成体）、运动规律串（'动成什么方向反'）", "教学角色": "掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下列说法正确的是（　）\nA. 圆柱的侧面与底面相交得到 2 条圆形的线\nB. 圆柱的侧面是平面\nC. 圆锥的顶点是面与面相交得到的\nD. 正方体的每个面是由棱动成的",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["圆柱上下两个底面（圆面）分别与侧面（曲面）相交，交线是上下两条圆周线，A 对", "圆柱侧面是曲面，不是平面，B 错", "圆锥顶点是侧面（曲面）尖端汇聚的点，不是两个面相交得到，C 错", "面由线动成（线动成面），不是由棱动成，D 错"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "曲面体元素关系的综合核验（面面相交/曲面/顶点由来）", "难度理由": "hard——4 项都需精确的元素关系判断", "认知阶梯定位": "L3 检测——关系判断的深度检测", "错因陷阱": "把圆锥顶点当面面相交、把圆柱侧面当平面（'点线面体关系混乱'）", "教学角色": "检测 hard 档——判定层 hard 证据来源"},
        },
        {
            "slot": "B4-I2",
            "prompt": "下列由'面动成体'得到的立体图形中，正确的是（　）\nA. 一个圆沿垂直于它的方向平移 → 圆柱\nB. 一个三角形沿水平方向平移 → 圆锥\nC. 一个半圆绕直径旋转一周 → 半球\nD. 一个长方形绕一条边旋转一周 → 长方体",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面动成体",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["圆（面）沿垂直方向平移，扫过的空间是圆柱，A 对", "三角形平移扫出三棱柱（不是圆锥），B 错", "半圆绕直径旋转一周得到球（不是半球），C 错", "长方形绕边旋转一周得到圆柱（不是长方体），D 错"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "面动成体的平移/旋转结果复测（防'会背不会用'）", "难度理由": "medium——4 项平移/旋转结果逐一核对", "认知阶梯定位": "L3 复测——背了'面动成体'但结果记错的检验", "错因陷阱": "平移与旋转结果混淆、半圆得半球、矩形得长方体（'动成什么方向反'）", "教学角色": "复测题——掌握确认真实性"},
        },
        {
            "slot": "B5-I0",
            "prompt": "请用自己的话分别解释'点动成线''线动成面''面动成体'，并为每个规律举一个生活中的例子。",
            "expected_answer": "点动成线：点移动留下的痕迹是线，如笔尖画线、雨滴下落；线动成面：线移动扫出的是面，如雨刷刷过车窗、扫帚扫地；面动成体：面移动或旋转扫出的是体，如旋转门转动、长方形纸片绕边旋转成圆柱。（对应正确即可）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["点动成线：一个点沿一定方向运动，留下的痕迹是一条线", "线动成面：一条线运动扫过的区域是一个面", "面动成体：一个面运动（平移或旋转）扫过的空间是一个体", "各举一个生活例子（如笔尖画线、雨刷扫窗、旋转门）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "点线面体运动规律的综合解释与举例（mastery'能举例解释四者关系'取证）", "难度理由": "hard——三条规律 + 六个生活例子对应，开放表达", "认知阶梯定位": "L4 复测——综合表达性复测", "错因陷阱": "只会背句子不会举例、规律与例子错配（'概念背诵但不会举例'）", "教学角色": "复测 hard 档——掌握标准的最终取证"},
        },
        {
            "slot": "B5-I1",
            "prompt": "把下面生活中的事物与几何元素对应起来（填：点 / 线 / 面 / 体）。\n① 地图上的城市位置　② 拉直的棉线　③ 镜子的表面　④ 乒乓球",
            "expected_answer": "① 点　② 线　③ 面　④ 体",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["地图上的城市位置是一个位置，抽象为点", "拉直的棉线是线", "镜子的表面是面", "乒乓球是体"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "从实物抽象出点/线/面/体（diagnostic probe'用生活例子说明点线面体关系'）", "难度理由": "easy——直接对应", "认知阶梯定位": "L1 诊断——抽象能力探针", "错因陷阱": "把'棉线'当体、把'镜子'整体当体（'概念背诵但不会举例'）", "教学角色": "诊断题——抽象-对应能力一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "下列说法错误的是（　）\nA. 圆柱的底面是圆面，侧面是曲面，它们相交得到圆（线）\nB. 长方体有 6 个面、12 条棱、8 个顶点，其中棱是面与面相交得到的\nC. 球是由一个圆面围成的\nD. 圆锥的侧面与底面相交得到一条圆（线）",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "元素关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["A：圆柱底面（圆面）与侧面（曲面）相交得到圆周线，正确", "B：长方体棱是面面相交，正确", "C：球由曲面（球面）围成，不是圆面，C 错", "D：圆锥侧面与底面相交得到一条圆周线，正确", "所以错误的是 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "曲面与平面、面面相交关系的诊断", "难度理由": "medium——需区分曲面体与多面体的围成方式", "认知阶梯定位": "L2 诊断", "错因陷阱": "把球面当圆面（'概念背诵但不会举例'）、圆锥顶点与交线混淆", "教学角色": "诊断题——'体由面围成'理解的探针"},
        },
    ],
    # ===== M-G7-GEO-VIEWS 展开图与视图（概念+空间想象向：15 unverifiable） =====
    # 节点契约：essence="三维图形可以通过展开或从不同方向观察变成二维信息"；seed=正方体展开图/从正面左面上面看/小正方体组合；
    # common_mistakes=11种正方体展开图不熟/左右方向看反/遮挡关系想错；diagnostic_probes=2道展开图、2道三视图。
    # authoring 原则（琢玉教训）：空间想象题文字/ASCII 呈现，选择判断为主；L1 真识别（视图名称/概念）；
    # hard 真难（至少/最多、对面关系空间推理、遮挡、三视图综合）；展开图判断 3 题（二选/四选/选'不能'）句式各异；
    # 视图题覆盖球/圆柱/圆锥/组合体，避免同一图形重复；全部概念/图形题 unverifiable（诚实声明）。
    "M-G7-GEO-VIEWS": [
        {
            "slot": "B1-I0",
            "prompt": "把一个正方体纸盒沿棱剪开、摊平，得到的平面图形叫它的展开图。判断下面两个图形中，哪个能折成正方体？\nA. 一四一型：4 个正方形排成一行，第 2 个的上面和下面各接 1 个（共 6 个正方形）\nB. 十字形：中间 1 个，上下左右各接 1 个（共 5 个正方形）",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["正方体有 6 个面，展开图必须有 6 个正方形", "B 的十字形只有 5 个正方形，面数不够，折不成正方体", "A 的一四一型有 6 个正方形，能折回正方体（4 个围成侧面，上下 2 个作底面）", "选 A"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "正方体展开图的判断（先数面数再想折叠）", "难度理由": "medium 锚点——展开→折叠的空间想象演示", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'11 种展开图不熟'在变式/检测布点）", "教学角色": "讲本质用——'展开与折叠互为逆过程'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "从上面看物体得到的图形，在数学中叫（　）\nA. 主视图\nB. 左视图\nC. 俯视图\nD. 仰视图",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "从正面/左面/上面看",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["从正面看叫主视图（正视图）", "从左面看叫左视图", "从上面看叫俯视图，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "三视图名称的识别（俯视图=从上面看）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "主/左/俯名称互相混（'三视图位置搞混'）", "教学角色": "概念识别脚手架——视图名称锚点"},
        },
        {
            "slot": "B1-I2",
            "prompt": "从不同方向看同一个物体，看到的图形（　）\nA. 一定相同\nB. 一定不同\nC. 可能相同，也可能不同\nD. 与观察方向没有关系",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "从正面/左面/上面看",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["球、正方体从各个方向看都相同", "长方体从正面、侧面、上面看通常不同", "所以可能相同也可能不同，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "视图的基本概念（不同方向视图的关系）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别——概念判断", "错因陷阱": "绝对化判断（一定相同/一定不同）（'看图只凭感觉'）", "教学角色": "概念识别脚手架"},
        },
        {
            "slot": "B2-I0",
            "prompt": "一个圆柱竖直放在桌上。从正面看是什么图形？从上面看是什么图形？",
            "expected_answer": "从正面看是长方形（矩形），从上面看是圆",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "从正面/左面/上面看",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["从正面看：看到圆柱的侧面轮廓，是长方形", "从上面看：看到圆柱的底面，是圆", "所以正面看是长方形，上面看是圆"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "圆柱的三视图套用（正面长方形、上面圆）", "难度理由": "easy（L2 直接套用）", "认知阶梯定位": "L2 套用——视图位置套用", "错因陷阱": "把上面看想成长方形、正面看想成圆（'三视图位置搞混'）", "教学角色": "三视图标准套用"},
        },
        {
            "slot": "B2-I1",
            "prompt": "下面哪个图形能折成正方体？（　）\nA. 二三一型：3 个正方形排成一行，第 2 个的上面接 1 个，第 1、2 个的下面各接 1 个（共 6 个）\nB. 上下各 3 个、上下对齐的长方形（共 6 个）",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["A 的二三一型（上面 1、中间 3、下面 2）是正方体展开图 11 种基本型之一，能折成", "B 是 2×3 的长方形：折起来会有 4 个面挤在一起（出现'田字'重叠），不能折成", "选 A"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "正方体展开图的判断（二三一型 vs 田字形）", "难度理由": "medium——两种 6 格图形需折叠想象区分", "认知阶梯定位": "L2 套用——展开图基本型判断", "错因陷阱": "只看格数不看排列（'11 种正方体展开图不熟'）", "教学角色": "展开图判断标准变式"},
        },
        {
            "slot": "B2-I2",
            "prompt": "用 4 个小正方体搭成一个立体：下面一层摆 3 个（排成一行），第 3 个的上面再放 1 个。从正面看，看到的是什么图形？",
            "expected_answer": "底层 3 个正方形、上层右侧 1 个正方形（共 4 个）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "小正方体组合",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["从正面看，下面一层 3 个都看得到", "第 3 个（最右边）上面的 1 个从正面看得到，在上层右侧", "所以正面看到：下层 3 个、上层右侧 1 个，共 4 个"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "由小正方体组合画出正面视图", "难度理由": "medium——先想立体再投影到正面", "认知阶梯定位": "L3 变式——从'看单个图形'到'看组合体'的变式", "错因陷阱": "上层方块位置放反（左侧）、把'上面放 1 个'看成侧面（'左右方向看反'）", "教学角色": "变式核心层——组合体视图入门"},
        },
        {
            "slot": "B3-I0",
            "prompt": "一个正方体的展开图如下（一四一型，标了字）：\n　　　上\n　前　右　后　左\n　　　下\n折成正方体后，与'前'相对的面是（　）\nA. 后\nB. 右\nC. 下\nD. 上",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["中间一行 4 个（前、右、后、左）折成正方体的侧面一圈", "这一圈里相隔一个的面相对：前与后相对，右与左相对", "上、下两个单格分别作顶面和底面，也相对", "所以与'前'相对的是'后'，选 A"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "由展开图判断相对面（一四一型的对面关系）", "难度理由": "medium——需把平面展开图'折回'立体想对面", "认知阶梯定位": "L3 变式——从'能否折成'到'折成后谁与谁相对'", "错因陷阱": "把相邻当面（前与右相邻）、以为上下与中间相对（'展开图对面关系判断错'）", "教学角色": "变式核心层——对面关系推理"},
        },
        {
            "slot": "B3-I1",
            "prompt": "一个立体图形由若干小正方体搭成：从上面看是 2×2 的正方形（4 个位置都有小正方体），从正面看是 2 层（每层 2 个），从左面看也是 2 层（每层 2 个）。这个立体至少需要几个小正方体？最多需要几个？",
            "expected_answer": "至少 6 个，最多 8 个",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "小正方体组合",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["从上面看 4 个位置都要有小正方体，先放 4 个", "正面、左面都要看到 2 层：每个方向两列都得有 1 个高 2 层的", "至少：在对角两个位置各叠 1 个，使正面、左面的两列都达到 2 层 → 4 + 2 = 6 个", "最多：4 个位置都叠到 2 层 → 4×2 = 8 个"],
            "error_tags": ["visual_spatial", "modeling_or_reading"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "由三视图求小正方体最少/最多个数（空间推理 × 计数策略迁移）", "难度理由": "hard——三个视图约束叠加，'至少'需对角叠放策略", "认知阶梯定位": "L4 迁移——三视图 × 计数逻辑（小学整数运算前置）", "错因陷阱": "只按正面 2 层放满（8 个）当唯一答案、忽略'至少'策略（'遮挡关系想错'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）"},
        },
        {
            "slot": "B3-I2",
            "prompt": "一个正方体的展开图如下（一四一型）：\n　　　E\n　A　B　C　D\n　　　F\n折成正方体后，与 E 相对的面是（　）\nA. F\nB. B\nC. A\nD. C",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["E、F 分别接在 B 的上面和下面，是展开图中仅有的两个'单格'", "中间一行 A、B、C、D 折成侧面一圈，E、F 分别成为顶面和底面", "顶面与底面相对：E 与 F 相对，选 A", "注意：E 与 B 相邻（E 接在 B 上），不相对"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "由展开图判断相对面（含'相邻 vs 相对'辨析，空间推理）", "难度理由": "hard——需要完整的折叠想象，'E 与 B 相邻'是强干扰", "认知阶梯定位": "L4 迁移——对面关系的空间推理（迁移到正方体结构理解）", "错因陷阱": "选 B（把相邻当相对，'展开图对面关系判断错'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——hard 空间推理标杆"},
        },
        {
            "slot": "B4-I0",
            "prompt": "从正面看一个球，看到的是什么图形？从上面看呢？",
            "expected_answer": "都是圆",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "从正面/左面/上面看",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["球是曲面围成的，从任何方向看轮廓都是圆", "正面看是圆，上面看也是圆", "所以两个方向看到的都是圆"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "球的三视图（各方向相同）", "难度理由": "easy 检测——直接视图判断", "认知阶梯定位": "L2 检测", "错因陷阱": "认为从上面看是点、或两个方向图形不一致（'看图只凭感觉'）", "教学角色": "掌握档快速检测——视图基础检查"},
        },
        {
            "slot": "B4-I1",
            "prompt": "用 4 个小正方体搭成立体：前面摆 3 个（排成一行），后面正中间再放 1 个（紧贴前面中间的方块）。从正面看，能看到几个正方形？",
            "expected_answer": "3 个（后面那 1 个被前面中间的方块挡住了）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "小正方体组合",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["从正面看：前面一排 3 个都能看到", "后面正中间那 1 个在前面中间方块的正后方，被完全挡住", "所以从正面只看到 3 个正方形"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "视图中的遮挡关系（被挡住的方块不出现）", "难度理由": "hard——不能数总方块数，要看视线遮挡", "认知阶梯定位": "L3 检测——遮挡关系检测（节点错因'遮挡关系想错'）", "错因陷阱": "数成 4 个（数了全部方块，'遮挡关系想错'）", "教学角色": "检测 hard 档——遮挡关系的硬核检测"},
        },
        {
            "slot": "B4-I2",
            "prompt": "下面哪个图形能折成正方体？（　）\nA. 十字形：中间 1 个，上下左右各 1 个（共 5 个正方形）\nB. 一四一型：4 个排成一行，第 2 个的上面和下面各接 1 个（共 6 个）\nC. 2×3 的长方形（共 6 个正方形）\nD. 3 个排成一行，正下方再对齐排 3 个（共 6 个）",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["A 只有 5 个正方形，面数不够，折不成", "B 的一四一型是展开图基本型，能折成", "C 的 2×3 长方形折起来出现'田字'重叠，折不成", "D 的三三对齐同样折出重叠面，折不成", "选 B"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "正方体展开图的综合判断（4 种图形核验，防'会背不会用'）", "难度理由": "medium——4 个选项逐一折叠判断", "认知阶梯定位": "L3 复测——背了 11 种型但不会判断的检验", "错因陷阱": "只看面数（A 有 5 个面不够）、被 6 格'田字'误导（'11 种正方体展开图不熟'）", "教学角色": "复测题——掌握确认真实性"},
        },
        {
            "slot": "B5-I0",
            "prompt": "一个立体由 4 个小正方体搭成：下面 3 个排成一行，第 1 个的上面再放 1 个。请分别写出从正面、左面、上面看到的图形（每层几个正方形）。",
            "expected_answer": "正面：下层 3 个、上层左端 1 个；左面：2 个上下叠（1 列 2 层）；上面：3 个排成一行",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "小正方体组合",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["正面：看到底层 3 个 + 第 1 个上面的 1 个（上层左端）", "左面：从左边看，只有第 1 列有方块，看到上下叠的 2 个", "上面：俯视看到 3 个位置（上层方块在第 1 个的正上方，不增加位置）", "三个方向分别写出"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "小正方体组合的三视图综合（三个方向都要画对）", "难度理由": "hard——三视图方向转换（左面尤其易反）", "认知阶梯定位": "L4 复测——视图技能的完整复测", "错因陷阱": "左面看成 3 个（'左右方向看反'）、上面数成 4 个（'遮挡关系想错'）", "教学角色": "复测 hard 档——判定层 hard 证据来源"},
        },
        {
            "slot": "B5-I1",
            "prompt": "从正面看一个圆锥，看到的是什么图形？（　）\nA. 圆\nB. 三角形\nC. 扇形\nD. 长方形",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "从正面/左面/上面看",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["从正面看圆锥：看到底面圆的直径（一条线段）和侧面轮廓", "轮廓是等腰三角形，选 B", "扇形是圆锥侧面展开图的形状（不是正面看），圆是从上面看的形状"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "圆锥正面视图的诊断（与侧面展开、俯视图区分）", "难度理由": "easy——直接视图识别", "认知阶梯定位": "L1 诊断", "错因陷阱": "选扇形（把'侧面展开'当'从正面看'）、选圆（俯视图）（'看图只凭感觉'）", "教学角色": "诊断题——视图 vs 展开图概念一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "下面哪个图形不能折成正方体？（　）\nA. 一四一型：4 个排成一行，第 1 个的上面接 1 个、第 3 个的下面接 1 个（共 6 个）\nB. 二三一型：3 个排成一行，第 2 个的上面接 1 个，第 1、2 个的下面各接 1 个（共 6 个）\nC. 二二二型：两两一组，错开排成一行（像楼梯，共 6 个）\nD. 三三对齐：3 个排成一行，正下方再对齐排 3 个（共 6 个）",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "正方体展开图",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["A 一四一型、B 二三一型都是展开图基本型，能折成", "C 二二二型（楼梯形）也是 11 种基本型之一，能折成", "D 三三对齐：折起来相对的面重叠（出现'田字'），不能折成", "选 D"],
            "error_tags": ["visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "正方体展开图的诊断（'不能折成'的识别）", "难度理由": "medium——需逐个核验 4 种展开图型", "认知阶梯定位": "L2 诊断——展开图基本型掌握度探针", "错因陷阱": "把三三对齐当能折、漏判 D（'11 种正方体展开图不熟'）", "教学角色": "诊断题——展开图判断能力探针"},
        },
    ],
    # ===== M-G7-ANGLE 角的概念与表示（概念向：15 unverifiable） =====
    # 节点契约：essence="角由两条有公共端点的射线组成，也可以看作旋转形成"；seed=角的表示/角分类/角的度量；
    # common_mistakes=顶点没放中间/同一图中角表示不唯一/度分秒换算弱；diagnostic_probes=在图中写角的表示、角分类3题；
    # mastery=角表示规范、能从旋转理解角；prereq=M-PRE-ANGLE-BASIC、M-G7-LINE-RAY-SEGMENT；unlock=M-G7-ANGLE-CALC、M-BRIDGE-CLOCK-ANGLE。
    # authoring 原则（琢玉教训）：概念节点全部 unverifiable（诚实声明）；L1 真识别（表示法/分类识别）；
    # hard 真难（时钟角迁移、射线×角定义、分类排序、周角关系换算）；"顶点没放中间"（B1-I1/B4-I0）、
    # "同一图中角表示不唯一"（B3-I0）、"平角当直线"（B5-I1）、"角大小与边长无关"（B5-I2）错因逐一布点；
    # 旋转理解（B2-I2/B4-I2）对应 mastery"能从旋转理解角"。
    "M-G7-ANGLE": [
        {
            "slot": "B1-I0",
            "prompt": "填空：角是由两条有____的射线组成的图形，这个共同的端点叫做角的____，两条射线叫做角的____。",
            "expected_answer": "公共端点；顶点；边",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的定义",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角的两条射线要有一个共同的端点（起点）", "这个共同的端点叫做角的顶点", "两条射线叫做角的边", "所以：角由顶点和两条边（射线）组成"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角的定义三要素（公共端点/顶点/边）", "难度理由": "medium 锚点——本质句填空，作为教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'顶点没放中间'在 B1-I1/B4-I0 单独布点）", "教学角色": "讲本质用——节点 essence'角由两条有公共端点的射线组成'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "角的顶点是 O，一条边经过点 A，另一条边经过点 B。用三个大写字母表示这个角时，顶点字母必须写在中间。下列表示正确的是（　）\nA. ∠OAB\nB. ∠ABO\nC. ∠BAO\nD. ∠AOB",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的表示",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["用三个大写字母表示角，顶点字母必须在中间", "顶点是 O，所以 O 必须在两个字母中间", "∠AOB（或 ∠BOA）正确，选 D；其余选项顶点字母都不在中间"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "三点表示法规范（顶点字母放中间）", "难度理由": "easy——L1 识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断表示法对错（补识别档）", "错因陷阱": "顶点字母没放中间（'顶点没放中间'节点错因）", "教学角色": "L1 识别脚手架——表示法规范的第一道判断"},
        },
        {
            "slot": "B1-I2",
            "prompt": "下列各角中，是钝角的是（　）\nA. 90°\nB. 180°\nC. 95°\nD. 35°",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["锐角小于 90°，直角等于 90°，钝角大于 90° 且小于 180°", "95° 大于 90° 且小于 180°，是钝角，选 C", "90° 是直角、180° 是平角、35° 是锐角"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "角的分类识别（钝角：90°<α<180°）", "难度理由": "easy——分类识别", "认知阶梯定位": "L1 识别——分类标准判断", "错因陷阱": "把 90°（直角）或 180°（平角）当钝角（'角分类边界不清'）", "教学角色": "L1 识别脚手架——分类边界的第一道探针"},
        },
        {
            "slot": "B2-I0",
            "prompt": "一个角，顶点是 O，一条边经过点 A，另一条边经过点 B。这个角用三个大写字母记作____。",
            "expected_answer": "∠AOB（或 ∠BOA，顶点字母 O 在中间）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的表示",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["三个大写字母表示角，顶点字母在中间", "顶点是 O，所以写成 ∠AOB 或 ∠BOA"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "三点表示法的正向书写（顶点居中）", "难度理由": "easy——直接套用书写规则", "认知阶梯定位": "L2 套用——从判断到书写", "错因陷阱": "把 O 写在开头或结尾（'顶点没放中间'）", "教学角色": "表示法书写的标准变式"},
        },
        {
            "slot": "B2-I1",
            "prompt": "把下面的角按类型填空：35° 是____角；90° 是____角；100° 是____角；180° 是____角；360° 是____角。",
            "expected_answer": "锐；直；钝；平；周",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["锐角 < 90°：35° 是锐角", "等于 90° 是直角", "90° < 100° < 180°：100° 是钝角", "等于 180° 是平角", "等于 360° 是周角"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角分类的完整套用（锐/直/钝/平/周）", "难度理由": "medium——五种角逐一归类，含边界辨析（100° 不是直角）", "认知阶梯定位": "L2 套用——分类标准的直接应用", "错因陷阱": "把 100° 当直角、把 180° 当钝角（'角分类边界不清'）", "教学角色": "分类套用标准变式——一次覆盖五类角"},
        },
        {
            "slot": "B2-I2",
            "prompt": "钟表的分针从数字 12 转到数字 3，扫过的角是____角，度数是____°。（提示：钟面一圈是 360°，平均分成 12 大格）",
            "expected_answer": "直；90",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "旋转形成角",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把分针看作一条射线，转动扫过的部分是角（旋转观点）", "从 12 到 3 是 3 大格，每格 360÷12 = 30°", "3 × 30° = 90°", "90° 的角是直角"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "从旋转理解角（分针扫过 90°=直角）", "难度理由": "medium——旋转观点 + 简单换算（每大格 30°）", "认知阶梯定位": "L3 变式——从静态定义到动态旋转（mastery'能从旋转理解角'取证）", "错因陷阱": "把 12 到 3 想成 3° 或 45°（每大格度数错）、把 90° 当锐角", "教学角色": "旋转理解核心变式——动态角的代表题"},
        },
        {
            "slot": "B3-I0",
            "prompt": "从一点 O 出发画 3 条射线 OA、OB、OC（按顺时针顺序排列）。图中共有____个小于平角的角；能不能只用单个字母 ∠O 表示其中某一个角？为什么？",
            "expected_answer": "3 个（∠AOB、∠BOC、∠AOC）；不能——以 O 为顶点的角不止一个，∠O 无法确定是哪一个（表示不唯一），要用三个字母或 ∠1、∠α 等标记",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角计数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["每两条射线组成一个角：OA 与 OB 成 ∠AOB，OB 与 OC 成 ∠BOC", "OA 与 OC 还组成最大的角 ∠AOC（容易漏数）", "共 3 个角", "以 O 为顶点的角有多个，单个字母 ∠O 指代不唯一，不能用（同一图中角表示不唯一）"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "角的计数 + 表示不唯一性（同一图中角表示不唯一）", "难度理由": "medium——计数需不漏大角，且要解释单字母表示为何不行", "认知阶梯定位": "L3 变式——从单个角到图形中多个角的计数与命名", "错因陷阱": "漏数 ∠AOC、误用 ∠O 表示某个角（'同一图中角表示不唯一'节点错因）", "教学角色": "计数+命名综合变式——为后续角的学习打图形基础"},
        },
        {
            "slot": "B3-I1",
            "prompt": "钟面一圈是 360°，平均分成 12 大格。5 点整时，时针和分针所成的较小角是多少度？它是什么角？",
            "expected_answer": "150°；钝角",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的度量",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["钟面一圈 360° 分成 12 大格，每大格 360 ÷ 12 = 30°", "5 点整时，时针指向 5、分针指向 12，两针相距 5 大格", "5 × 30° = 150°", "90° < 150° < 180°，是钝角（这是时钟角计算的最简起步：M-BRIDGE-CLOCK-ANGLE 的预告）"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "用度度量旋转角（读钟面 + 360°÷12 + 分类）", "难度理由": "hard——读时刻、换算每大格 30°、乘 5、再分类，四步推理", "认知阶梯定位": "L4 迁移——角度基础（M-PRE-ANGLE-BASIC 前置）× 角的度量，预告时钟角（M-BRIDGE-CLOCK-ANGLE unlock）", "错因陷阱": "把 5 点整的两针距离数错、每大格度数错、把 150° 当直角（'角的度量换算弱'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）+ 时钟角预告锚点"},
        },
        {
            "slot": "B3-I2",
            "prompt": "下列说法正确的是（　）\nA. 角的两边是线段，所以把边延长，角会变大\nB. 角的两边是射线，角的大小由两边张开的程度决定，与边的长短无关\nC. 角的两边是直线，直线越长角越大\nD. 角的两边是射线，角的大小与边的长短有关，边越长角越大",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的定义",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["角的两边是射线（不是线段、不是直线）：排除 A、C", "射线向一端无限延伸，所以'延长边'无意义，边也不存在长短比较", "角的大小由两条边张开（旋转）的程度决定，与边画多长无关", "B 对（A、C、D 都把大小与边长挂钩）"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "角的两边是射线（前置 LINE-RAY-SEGMENT）× 角的大小与边长无关", "难度理由": "hard——每个选项都要两重判断（边是什么线 + 大小由什么决定）", "认知阶梯定位": "L4 迁移——直线射线线段概念（M-G7-LINE-RAY-SEGMENT 前置）与角定义混合", "错因陷阱": "把角的两边当线段/直线、认为边越长角越大（'角的大小与边长无关'核心迷思）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——概念联结题"},
        },
        {
            "slot": "B4-I0",
            "prompt": "一个角标记为 ∠1，现在要用三个大写字母表示它：顶点是 A，一条边经过点 B，另一条边经过点 C。这个角应记作____。如果写成 ∠BCA，错在哪里？",
            "expected_answer": "∠BAC；错在顶点字母 A 没有写在中间（∠BCA 中 A 在最后）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的表示",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["用三个大写字母表示角，顶点字母在中间", "顶点是 A，所以写成 ∠BAC", "∠BCA 中 A 在最后，顶点没有居中，写法不规范"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三点表示法的掌握检测（含错误写法辨析）", "难度理由": "medium——既写正确写法又要指出错误原因", "认知阶梯定位": "L2 检测——表示法规范的掌握检测", "错因陷阱": "把顶点写错位置（'顶点没放中间'节点错因）", "教学角色": "掌握档检测——表示规范是否真正掌握"},
        },
        {
            "slot": "B4-I1",
            "prompt": "∠A = 35°，∠B = 105°，∠C = 90°，∠D = 180°。把这四个角按从小到大的顺序排列：____。其中 ∠B（105°）是____角，∠C（90°）是____角。",
            "expected_answer": "∠A < ∠C < ∠B < ∠D（35° < 90° < 105° < 180°）；钝；直",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["按度数从小到大：35° < 90° < 105° < 180°", "对应：∠A < ∠C < ∠B < ∠D", "105° 大于 90° 小于 180°，是钝角（不是直角）", "90° 是直角"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "角分类的深度检测（四角排序 + 边界辨析）", "难度理由": "hard——排序要求四角两两比较，且 105° 的钝角归类是常见失分点", "认知阶梯定位": "L3 检测——分类标准的综合运用", "错因陷阱": "把 105° 当直角、排序时把 90° 放错位置（'角分类边界不清'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"},
        },
        {
            "slot": "B4-I2",
            "prompt": "一条射线绕它的端点旋转：当旋转到与原来方向相反、两边成一条直线时，形成的角是____角（____°）；继续旋转，回到原来的位置时，形成的角是____角（____°）。",
            "expected_answer": "平；180；周；360",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "旋转形成角",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["射线旋转半圈（两边方向相反、成一条直线）→ 平角 180°", "旋转一整圈回到原位置 → 周角 360°", "平角、周角都来自旋转观点"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "旋转理解复测（平角/周角的旋转形成）", "难度理由": "medium——需用旋转观点解释平角周角，防'会背不会用'", "认知阶梯定位": "L3 复测——从静态定义到动态生成", "错因陷阱": "把平角说成'直线'、把周角说成 0°（'平角当直线'迷思）", "教学角色": "复测题——掌握确认真实性（旋转观点是否真理解）"},
        },
        {
            "slot": "B5-I0",
            "prompt": "填空并说明理由：1 周角 = ____°；1 周角 = ____ 个平角 = ____ 个直角。",
            "expected_answer": "360；2；4（周角 360° ÷ 平角 180° = 2 个；360° ÷ 直角 90° = 4 个）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的度量",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["周角 = 360°", "平角 = 180°：360 ÷ 180 = 2，所以 1 周角 = 2 个平角", "直角 = 90°：360 ÷ 90 = 4，所以 1 周角 = 4 个直角", "量角关系建立在度数换算上"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "周角/平角/直角的度数关系（含换算与说理）", "难度理由": "hard——两个度数除法换算 + 说明理由，考查对角的度量的整体把握", "认知阶梯定位": "L4 复测——度量与分类的综合复测", "错因陷阱": "把 1 周角当 3 个直角（270°）、平角与直角关系算错", "教学角色": "复测 hard 档——掌握标准的最终取证之一"},
        },
        {
            "slot": "B5-I1",
            "prompt": "判断：'平角就是一条直线'这个说法（　）\nA. 正确，平角的两边在一条直线上\nB. 正确，直线就是 180°\nC. 错误，平角是角，它的两边是两条方向相反的射线\nD. 错误，平角等于 90°",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["平角是角（旋转半圈形成），两边是两条方向相反的射线", "直线是线，不是角，不能说'直线就是 180°'", "平角 = 180°，不是 90°", "选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "平角与直线的辨析（平角是角不是直线）", "难度理由": "easy——L1 概念判断", "认知阶梯定位": "L1 诊断——'平角当直线'迷思的一键探针", "错因陷阱": "把平角当直线（节点 common_mistake 明确列出的迷思）", "教学角色": "诊断题——旋转/静态两种定义是否混淆的探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "把一个角的两条边各延长 3 厘米后，这个角的大小（　）\nA. 变大\nB. 变小\nC. 不变\nD. 无法确定",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的定义",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["角的大小由两条边张开的程度决定，与边的长短无关", "延长边只是把射线画得更长，张开程度没变", "角的大小不变，选 C"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "角的大小与边长无关（本质属性）", "难度理由": "easy——但直击核心迷思，easy 档配高密度陷阱题诊断力强", "认知阶梯定位": "L2 诊断——'角的大小与边长有关'迷思探针", "错因陷阱": "认为边变长角变大（'角的大小与边长无关'迷思）", "教学角色": "诊断题——直接区分'懂角本质'与'凭视觉判断'"},
        },
    ],

    # ===== M-G7-LINE-RAY-SEGMENT 直线、射线、线段（概念向：15 unverifiable） =====
    # 节点契约：essence="直线无端点，射线一个端点，线段两个端点且可度量"；seed=概念辨析/表示方法/线段计数；
    # common_mistakes=端点数量混淆/表示方法不规范/线段数量漏数；diagnostic_probes=概念判断5题、线段计数1题；
    # mastery=能准确说出端点特征、表示方法规范；prereq=M-G7-POINT-LINE-PLANE；unlock=M-G7-SEGMENT-MEASURE、M-G7-ANGLE。
    # authoring 原则（琢玉教训）：概念节点全部 unverifiable（诚实声明）；L1 真识别（实物识别/端点数量）；
    # hard 真难（4 点计数、公理×计数、中点预告、公理+概念深度辨析）；"端点混淆""射线可度量（错）"
    # "直线有长度（错）"错因在 B4-I0/B5-I1 布点；"线段数量漏数"在 B3-I0/B5-I0 布点；
    # 迁移布点：两点定线实用化（B3-I1）、线段中点预告（B3-I2，unlock SEGMENT-MEASURE）。
    "M-G7-LINE-RAY-SEGMENT": [
        {
            "slot": "B1-I0",
            "prompt": "填空：直线____端点，射线有____个端点，线段有____个端点；在这三种图形中，只有____可以量出长度。",
            "expected_answer": "没有（0 个）；1；2；线段",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["直线向两边无限延伸，没有端点", "射线有一个端点，向一个方向无限延伸", "线段有两个端点，长度有限", "可以度量的是线段"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "直线/射线/线段的端点特征与可度量性（本质句填空）", "难度理由": "medium 锚点——本质句填空应用", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；端点混淆在 B5-I1 单独布点）", "教学角色": "讲本质用——节点 essence'直线无端点、射线一个端点、线段两个端点'的演示载体"},
        },
        {
            "slot": "B1-I1",
            "prompt": "下列物体中，可以看作'线段'的是（　）\nA. 手电筒射出的光柱\nB. 笔直直尺的一条边\nC. 夜晚射向远方的灯光\nD. 太阳发出的光线",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["光柱、灯光、光线都从光源发出，有一个端点（光源）向远方延伸，是射线", "直尺的边有确定的两个端点，长度可量，是线段", "选 B"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "从生活实例识别线段（与射线区分）", "难度理由": "easy（L1 识别）", "认知阶梯定位": "L1 识别正宗实现——实物到图形概念", "错因陷阱": "把光源发出的光当线段（'射线/线段端点混淆'）", "教学角色": "概念识别脚手架——线段'有头有尾'的形象锚点"},
        },
        {
            "slot": "B1-I2",
            "prompt": "下面的图形中，只有一个端点的是（　）\nA. 直线 AB\nB. 射线 OA\nC. 线段 AB\nD. 直线 l",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["直线没有端点：A、D 排除", "线段有两个端点：C 排除", "射线有一个端点：选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "按端点数量识别图形类型", "难度理由": "easy——L1 识别", "认知阶梯定位": "L1 识别——端点数量决定图形类型", "错因陷阱": "把线段当 1 个端点、把射线当 0 个端点（'端点数量混淆'）", "教学角色": "概念识别脚手架——'数端点'判定法第一课"},
        },
        {
            "slot": "B2-I0",
            "prompt": "填空：一条线段两个端点是 A 和 B，记作线段____；射线以 O 为端点、经过点 A，记作射线____；过 A、B 两点的直线记作直线____。",
            "expected_answer": "AB（或 BA）；OA；AB（或 BA）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "表示方法",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["线段端点字母顺序可互换：线段 AB 或 BA", "射线端点字母必须在前：射线 OA（不能写成 AO）", "直线可用任意两点命名：直线 AB 或 BA"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "三种图形的表示方法（线段/射线/直线）", "难度理由": "easy——直接套用表示规则", "认知阶梯定位": "L2 套用——表示方法的标准应用", "错因陷阱": "射线端点字母放错位置（'表示方法不规范'节点错因）", "教学角色": "表示方法套用标准变式"},
        },
        {
            "slot": "B2-I1",
            "prompt": "射线 OA 和射线 AO 是同一条射线吗？请说明理由。",
            "expected_answer": "不是。射线 OA 以 O 为端点、向 A 的方向延伸；射线 AO 以 A 为端点、向 O 的方向延伸。端点和方向都不同，不是同一条射线。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["射线的记法：端点字母在前、方向字母在后", "射线 OA：端点 O，方向指向 A", "射线 AO：端点 A，方向指向 O", "端点不同、方向不同 → 不是同一条射线"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "射线的方向性（端点决定射线）", "难度理由": "medium——需解释而非只判断", "认知阶梯定位": "L2 套用——射线概念的说理应用", "错因陷阱": "以为字母相同就是同一条射线（'端点数量混淆'）", "教学角色": "射线本质说理题——'端点+方向'双要素的取证"},
        },
        {
            "slot": "B2-I2",
            "prompt": "经过一点可以画____条直线；经过两点可以画____条直线。这说明：____确定一条直线。",
            "expected_answer": "无数；1；两点",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两点定线",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["过一点可以画任意方向的直线，有无数条", "过两点只有一条直线（都经过这两点的直线唯一）", "两点确定一条直线（公理）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "两点确定一条直线（公理）", "难度理由": "medium——一点/两点对比推理", "认知阶梯定位": "L3 变式——从图形概念到公理归纳", "错因陷阱": "把'过一点无数条'推广到'过两点无数条'", "教学角色": "公理形成变式——从具体到一般"},
        },
        {
            "slot": "B3-I0",
            "prompt": "直线 l 上有 A、B、C 三个点。图中共有____条线段（写出它们：____）；以每个点为端点、向两边延伸，共有____条射线。",
            "expected_answer": "3（AB、BC、AC）；6",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段计数",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["线段：每两个点确定一条 → AB、BC、AC 共 3 条（AC 容易漏）", "射线：每个点向两边各一条 → 3 × 2 = 6 条", "线段数规律：n 个点共 n×(n−1)÷2 条（此处 3×2÷2 = 3）"],
            "error_tags": ["visual_spatial", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "线段计数（不漏不重）+ 射线计数", "难度理由": "medium——计数需有序枚举（'线段数量漏数'节点错因）", "认知阶梯定位": "L3 变式——从单个图形到计数问题", "错因陷阱": "漏数 AC（只数相邻线段）——'线段数量漏数'", "教学角色": "计数标准变式——为后续组合计数打基础"},
        },
        {
            "slot": "B3-I1",
            "prompt": "木工在墙上钉木条，钉 2 颗钉子就能把木条固定住，这是因为____。墙上有 A、B、C、D 四个孔位，任意两个孔位之间都拉一条线，一共能拉____条不同的线。",
            "expected_answer": "两点确定一条直线；6（AB、AC、AD、BC、BD、CD）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段计数",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["2 颗钉子固定木条：过两点的直线唯一（两点确定一条直线）", "4 个点任取 2 个连一条线，有序枚举：AB、AC、AD、BC、BD、CD", "共 3+2+1 = 6 条"],
            "error_tags": ["modeling_or_reading", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "两点确定一条直线 × 组合计数（4 点连线段）", "难度理由": "hard——公理应用 + 有序枚举 6 条不重不漏", "认知阶梯定位": "L4 迁移——公理×计数（把'线段计数'技能迁移到钉木条/拉线新情境）", "错因陷阱": "枚举漏项（只数相邻组合）、把过两点当可画无数条", "教学角色": "判定层 transfer 证据来源（C3 双角色）——公理实用化"},
        },
        {
            "slot": "B3-I2",
            "prompt": "点 C 在线段 AB 上，且 AC = CB，我们说点 C 是线段 AB 的中点（把线段平分）。如果 AC = 3 cm，那么 AB = ____cm。",
            "expected_answer": "6",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "中点概念",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["中点把线段分成相等的两段：AC = CB = 3 cm", "AB = AC + CB = 3 + 3 = 6（cm）", "（这是下一节点'线段比较与计算'的预告）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "线段中点概念的预告（等分→求整体）", "难度理由": "hard——中点是对解锁节点（M-G7-SEGMENT-MEASURE）的新概念预告，需自己建立 AB = 2×AC", "认知阶梯定位": "L4 迁移——线段等分概念预告（unlock SEGMENT-MEASURE 桥梁）", "错因陷阱": "认为中点只是'中间的点'不理解平分（'中点关系只会背'预告）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——解锁节点桥梁"},
        },
        {
            "slot": "B4-I0",
            "prompt": "下列说法正确的是（　）\nA. 直线比射线长\nB. 射线比线段长\nC. 直线和射线都可以量出长度\nD. 线段可以量出长度，直线和射线不能度量",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["直线、射线都无限延伸，不能度量：A、B、C 错", "线段有限长，可以度量：D 对", "直线与射线无法比较长短（都无限）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "可度量性辨析（线段可度量，直线射线不可）", "难度理由": "easy 检测——可度量性是掌握基线", "认知阶梯定位": "L2 检测——端点/延伸性掌握检测", "错因陷阱": "认为直线比射线长、射线可度量（'直线有长度（错）''射线可度量（错）'）", "教学角色": "掌握档快速检测"},
        },
        {
            "slot": "B4-I1",
            "prompt": "下列说法正确的是（　）\nA. 射线 OA 与射线 OB 一定在同一条直线上\nB. 两点之间的所有连线中，线段最短\nC. 直线 AB 可以延长\nD. 直线没有端点，所以可以量出长度",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["射线 OA、OB 只是同一个端点 O 出发的射线，方向不同就不在同一条直线上：A 错", "两点之间线段最短（线段公理）：B 对", "直线本身无限，不能说'延长直线'（延长的是线段/射线）：C 错", "直线无限不可度量：D 错"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "线段公理 + 直线射线概念的深度辨析", "难度理由": "hard——四项都需要精确概念判断（公理/延长/度量/共线）", "认知阶梯定位": "L3 检测——概念掌握的深度检测", "错因陷阱": "以为射线同端点必共线、认为直线可延长、认为直线可度量（'端点数量混淆''直线有长度'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"},
        },
        {
            "slot": "B4-I2",
            "prompt": "直线 l 上有 A、B 两点。以 A 为端点、经过 B 的射线记作射线____；以 A 为端点的射线共有____条（另一条向相反方向延伸）。",
            "expected_answer": "AB；2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "表示方法",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["以 A 为端点、经过 B：射线 AB（端点 A 在前）", "每个点向两边各有一条射线：以 A 为端点的射线共 2 条", "反向那条射线在图中用另一个点命名（如射线 AM，M 在 A 的另一侧）"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "射线表示与射线数量（每个点两条）", "难度理由": "medium——复测表示规范 + 计数", "认知阶梯定位": "L3 复测——防'会背不会用'", "错因陷阱": "漏数反向射线、把射线 AB 写成 BA（'表示方法不规范'）", "教学角色": "复测题——表示方法掌握确认真实性"},
        },
        {
            "slot": "B5-I0",
            "prompt": "直线 m 上有 A、B、C、D 四个点。图中共有____条线段（有序枚举写全：____）；以 B 为端点的射线有____条。",
            "expected_answer": "6（AB、AC、AD、BC、BD、CD）；2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段计数",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["有序枚举线段：从 A 出发 AB、AC、AD；从 B 出发 BC、BD；从 C 出发 CD", "共 3+2+1 = 6 条", "以 B 为端点的射线：向两边各一条，共 2 条"],
            "error_tags": ["visual_spatial", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "4 点线段计数（有序枚举）+ 射线计数", "难度理由": "hard——6 条不重不漏需系统枚举（'线段数量漏数'错因升级版）", "认知阶梯定位": "L4 复测——计数技能的巩固与检验", "错因陷阱": "枚举漏项、重复计数（'线段数量漏数'）", "教学角色": "复测 hard 档——计数能力最终取证"},
        },
        {
            "slot": "B5-I1",
            "prompt": "判断并改正：'射线有 2 个端点，可以量出长度。'这个说法（　）\nA. 正确\nB. 错误，射线有 1 个端点，不能量出长度\nC. 错误，射线没有端点\nD. 错误，射线有 2 个端点，但不能量出长度",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["射线有一个端点（端点 + 无限延伸方向）", "射线无限延伸，不能量出长度", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "射线的端点数量与可度量性诊断", "难度理由": "easy——L1 概念判断", "认知阶梯定位": "L1 诊断——'射线/线段端点混淆''射线可度量'迷思探针", "错因陷阱": "把射线当 2 个端点、认为射线可度量（节点#1 错因）", "教学角色": "诊断题——端点特征一键探针"},
        },
        {
            "slot": "B5-I2",
            "prompt": "小明说：'过一点可以画无数条直线，所以过两点也可以画无数条直线。'这种说法对吗？另外，两条不同的直线最多有几个交点？",
            "expected_answer": "不对。过一点可以画无数条直线，但过两点只能画 1 条直线（两点确定一条直线）。两条不同的直线最多有 1 个交点（交点唯一）。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "概念辨析",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["过一点：方向任意，无数条直线", "过两点：同时经过这两点的直线唯一 → 1 条", "两条不同直线若相交，交点唯一（若平行则没有交点）", "所以最多 1 个交点"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "两点确定一条直线 + 两直线交点唯一（诊断推理）", "难度理由": "medium——要反驳错误推广并回答交点个数", "认知阶梯定位": "L2 诊断——公理理解深度的探针", "错因陷阱": "把'过一点无数条'推广到两点（'两点确定一条直线'不会用）", "教学角色": "诊断题——公理是否真理解（不是背句子）"},
        },
    ],

    # ===== M-G7-SEGMENT-MEASURE 线段比较与计算（概念+微计算向：7 verified + 8 unverifiable） =====
    # 节点契约：essence="线段计算本质是部分与整体的关系"；seed=中点/线段和差/尺规作线段；
    # common_mistakes=中点关系只会背/图上相邻线段关系看错/单位不统一；diagnostic_probes=2道中点、2道线段和差；
    # mastery=能写出 AB=AC+CB 等关系、中点能转化为相等线段；prereq=M-G7-LINE-RAY-SEGMENT、M-PRE-UNIT-CONVERSION；unlock=M-G7-ANGLE-CALC。
    # authoring 原则（琢玉教训）：数值环节用"计算：X op Y"显式声明并 sympy 真验（verified 且真算对）；
    # 概念/图形/建模题诚实 unverifiable；"长度相等≠中点"（B4-I0）、"图上相邻线段关系看错"（B4-I1）、
    # "单位不统一"（B2-I2/B3-I1/B5-I2）错因逐一布点；迁移布点：单位换算前置（B3-I1，UNIT-CONVERSION）、
    # 尺规作图×线段相等/射线（B3-I2）；hard 真难（接头重叠、分类讨论、尺规原理）。
    "M-G7-SEGMENT-MEASURE": [
        {
            "slot": "B1-I0",
            "prompt": "点 C 在线段 AB 上，AC = 3 cm，CB = 4 cm。求 AB 的长。计算：3 + 4，写出 AB 的长（单位 cm）。",
            "expected_answer": "7",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "线段和差",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["点 C 在线段 AB 上，所以 AB = AC + CB（整体 = 部分 + 部分）", "AB = 3 + 4 = 7（cm）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "线段和差的基本关系（整体=部分+部分）", "难度理由": "medium 锚点——数值环节简单，建模（选对 3 和 4 相加）是核心", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'相邻线段关系看错'在 B4-I1 布点）", "教学角色": "讲本质用——essence'线段计算本质是部分与整体的关系'的演示载体（数值环节机算 verified）"},
        },
        {
            "slot": "B1-I1",
            "prompt": "点 C 在线段 AB 上。下列关系式正确的是（　）\nA. AB = AC − CB\nB. AB = AC + CB\nC. AC = AB + CB\nD. CB = AC + AB",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "线段和差",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["点 C 在 AB 上，AB 被分成 AC 和 CB 两部分", "整体 = 部分 + 部分：AB = AC + CB", "选 B（其余都是部分与整体关系倒置）"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别线段和差关系式（整体=部分+部分）", "难度理由": "easy——L1 识别", "认知阶梯定位": "L1 识别正宗实现——关系式判断", "错因陷阱": "部分与整体关系倒置（'图上相邻线段关系看错'）", "教学角色": "概念识别脚手架——关系式第一道判断"},
        },
        {
            "slot": "B1-I2",
            "prompt": "点 C 是线段 AB 的中点。下列结论正确的是（　）\nA. AC = CB\nB. AC = AB\nC. CB = 2AB\nD. AC = 2CB",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "中点",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["中点把线段分成相等的两段：AC = CB", "且 AC = CB = AB ÷ 2（AB 的一半）", "选 A（B、C、D 都是中点关系的错误变形）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "中点定义识别（中点→相等两段）", "难度理由": "easy——L1 识别", "认知阶梯定位": "L1 识别正宗实现——中点关系判断", "错因陷阱": "把中点关系记反（AC = AB、CB = 2AB 等'中点关系只会背'）", "教学角色": "概念识别脚手架——中点定义第一道判断"},
        },
        {
            "slot": "B2-I0",
            "prompt": "点 C 是线段 AB 的中点，AB = 10 cm。求 AC 的长。计算：10 ÷ 2，写出 AC 的长（单位 cm）。",
            "expected_answer": "5",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "中点",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["中点把线段平分：AC = AB ÷ 2", "AC = 10 ÷ 2 = 5（cm）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "中点数值套用（一半 = 整体÷2）", "难度理由": "easy——直接套用中点关系", "认知阶梯定位": "L2 套用——中点关系的直接应用", "错因陷阱": "把 AC 当 AB 的 2 倍（方向记反）", "教学角色": "中点计算标准变式——数值环节机算 verified"},
        },
        {
            "slot": "B2-I1",
            "prompt": "点 C 在线段 AB 上，AB = 9 cm，AC = 5 cm。求 CB 的长。计算：9 − 5，写出 CB 的长（单位 cm）。",
            "expected_answer": "4",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "线段和差",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["AB = AC + CB（整体 = 部分 + 部分）", "CB = AB − AC = 9 − 5 = 4（cm）（部分 = 整体 − 另一部分）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "线段差（部分 = 整体 − 另一部分）", "难度理由": "easy——关系直接可套", "认知阶梯定位": "L2 套用——和差关系的标准应用", "错因陷阱": "用加法（9+5）或方向混淆", "教学角色": "线段和差标准变式——与 B1-I0 互补（求部分）"},
        },
        {
            "slot": "B2-I2",
            "prompt": "线段 AB = 2 cm 3 mm。化成以 mm 为单位：2 cm = 2 × 10 = 20 mm，再加上 3 mm。计算：2 × 10 + 3，线段 AB 的长是____mm。",
            "expected_answer": "23",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "单位换算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["1 cm = 10 mm，2 cm = 20 mm", "20 mm + 3 mm = 23 mm", "所以 AB = 23 mm"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "厘米毫米换算（M-PRE-UNIT-CONVERSION 前置运用）", "难度理由": "medium——换算 + 加法两步", "认知阶梯定位": "L3 变式——线段度量与单位换算结合", "错因陷阱": "把 2 cm 3 mm 当 2.3 mm 或 23 cm（'单位不统一'错因的换算形态）", "教学角色": "变式题——为'单位不统一'诊断做正向铺垫"},
        },
        {
            "slot": "B3-I0",
            "prompt": "点 C 是线段 AB 的中点，CB = 6 cm。求 AB 的长。计算：6 × 2，写出 AB 的长（单位 cm）。",
            "expected_answer": "12",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "中点",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["中点把 AB 分成相等的两段：AC = CB = 6 cm", "AB = AC + CB = 6 + 6 = 12（cm）", "即 AB = CB × 2"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "中点反向应用（知道一半求整体）", "难度理由": "medium——与 B2-I0 方向相反，需自己建立 AB = 2×CB", "认知阶梯定位": "L3 变式——中点关系换向运用", "错因陷阱": "用除法（6÷2）、以为 AB = CB", "教学角色": "变式题——中点关系的双向运用"},
        },
        {
            "slot": "B3-I1",
            "prompt": "线段 AB = 3 dm，点 C 是线段 AB 的中点。求 AC 的长（单位 cm）。计算：30 ÷ 2，写出 AC 的长（单位 cm）。",
            "expected_answer": "15",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "单位换算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先统一单位：1 dm = 10 cm，3 dm = 30 cm", "中点把 AB 平分：AC = AB ÷ 2", "AC = 30 ÷ 2 = 15（cm）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "单位换算 × 中点计算（迁移 M-PRE-UNIT-CONVERSION 前置）", "难度理由": "hard——先换算（dm→cm）再取半，两步建模且答案带单位要求", "认知阶梯定位": "L4 迁移——单位换算前置 × 本节点中点核心（'单位不统一'错因布点）", "错因陷阱": "不统一单位直接 3÷2、把 1 dm 当 10 mm（'单位不统一'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——单位换算迁移"},
        },
        {
            "slot": "B3-I2",
            "prompt": "用尺规作一条线段等于已知线段 a：在射线 OA 上，用圆规截取 OB = a。这里圆规的作用是（　）\nA. 量出 a 的长度并保持这个距离，把等长的线段'搬'到新位置\nB. 把 a 平均分成两份\nC. 画出 90° 的角\nD. 量出 a 的长度并把数字记在图上",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "尺规作线段",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["尺规作图不用刻度，圆规负责'搬'长度：两脚距离固定，等于 a", "把圆规两脚的距离移到射线 OA 上截取，OB = a", "选 A（D 是'量数字'，尺规作图不读数）"],
            "error_tags": ["concept_confusion", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "尺规作线段的原理（圆规搬等长，不依赖刻度）", "难度理由": "hard——理解'不度量、只搬移'的作图逻辑（迁移线段相等×射线概念）", "认知阶梯定位": "L4 迁移——线段相等概念 × 射线（M-G7-LINE-RAY-SEGMENT 前置）到尺规作图", "错因陷阱": "以为尺规作图需要量出数字（D）、把圆规当平分工具（B）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——尺规作图概念"},
        },
        {
            "slot": "B4-I0",
            "prompt": "判断：'如果 AC = CB，那么点 C 一定是线段 AB 的中点。'这个说法（　）\nA. 正确，长度相等就是中点\nB. 错误，还需要点 C 在线段 AB 上\nC. 错误，中点必须满足 AC = 2CB\nD. 错误，点 C 必须在直线外",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "中点",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["中点的定义：点 C 在线段 AB 上，且 AC = CB", "只有 AC = CB 还不够——点 C 还必须在线段 AB 上", "若 C 不在 AB 上，AC = CB 只说明 C 到两端等距（不在线段上就不是中点）", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "中点定义的完整性（长度相等 + 在线段上）", "难度理由": "medium——需要否定'长度相等即中点'的直觉", "认知阶梯定位": "L2 检测——中点定义掌握的检测", "错因陷阱": "以为 AC = CB 就一定是中点（'长度相等≠中点'迷思）", "教学角色": "检测题——中点定义完整性的探针"},
        },
        {
            "slot": "B4-I1",
            "prompt": "两根木条接成一根长木条：第一根长 35 cm，第二根长 4 dm，接头处重叠了 5 cm。接好后整根木条长多少 cm？写出你的思考过程。（提示：先统一单位，再想清楚重叠部分怎么算）",
            "expected_answer": "4 dm = 40 cm。两根木条总长 35 + 40 = 75（cm）；接头重叠的 5 cm 被算了两次，要减去：75 − 5 = 70（cm）。整根长 70 cm。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段和差",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["统一单位：4 dm = 40 cm", "若不重叠，总长 = 35 + 40 = 75（cm）", "接头重叠 5 cm 被算了两次，要减去一次：75 − 5 = 70（cm）", "整根长 70 cm（先想清楚重叠部分怎么算，再列式）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "线段和差的应用（接头重叠：重叠部分被算两次要减去）", "难度理由": "hard——单位换算 + 重叠双计建模，是线段和差应用题的经典难点", "认知阶梯定位": "L3 检测——和差关系的深度检测（'图上相邻线段关系看错'升级形态）", "错因陷阱": "只加不减（75）、忘记换算直接 35+4（'单位不统一''重叠漏减'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"},
        },
        {
            "slot": "B4-I2",
            "prompt": "点 M 是线段 AB 的中点，AM = 7 cm。求 AB 的长。计算：7 + 7，写出 AB 的长（单位 cm）。",
            "expected_answer": "14",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "中点",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["中点把 AB 分成相等的两段：AM = MB = 7 cm", "AB = AM + MB = 7 + 7 = 14（cm）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "中点复测（知道一半求整体，防'会背不会用'）", "难度理由": "medium——与 B3-I0 结构相同换数字，复测定位", "认知阶梯定位": "L3 复测——中点关系掌握确认真实性", "错因陷阱": "把 AB 当 AM（7）、只算一半", "教学角色": "复测题——中点关系防遗忘复测"},
        },
        {
            "slot": "B5-I0",
            "prompt": "点 C 在直线 AB 上，AB = 10 cm，BC = 4 cm。求 AC 的长。（提示：点 C 可能在线段 AB 上，也可能在 B 的外侧）",
            "expected_answer": "点 C 在线段 AB 上时，AC = 10 − 4 = 6（cm）；点 C 在 B 的外侧（延长线上）时，AC = 10 + 4 = 14（cm）。所以 AC = 6 cm 或 14 cm。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段和差",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["题目只说 C 在直线 AB 上，没说在线段 AB 上，要分情况", "情况一：C 在 A、B 之间，AC = AB − BC = 10 − 4 = 6（cm）", "情况二：C 在 B 的外侧，AC = AB + BC = 10 + 4 = 14（cm）", "两种情况都要考虑：AC = 6 cm 或 14 cm"],
            "error_tags": ["modeling_or_reading", "visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "分类讨论（点在线段上 / 在延长线上）", "难度理由": "hard——需主动发现两种情况，是线段计算的思维跃迁", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶复测", "错因陷阱": "只写一种情况（默认 C 在线段上，'图上相邻线段关系看错'升级形态）", "教学角色": "复测 hard 档——判定层 hard 证据来源，分类讨论能力取证"},
        },
        {
            "slot": "B5-I1",
            "prompt": "比较两条线段 AB 与 CD 的长短，有两种方法：度量法（用刻度尺量）和叠合法。关于叠合法，下列说法正确的是（　）\nA. 把两条线段的一端对齐、放在同一条直线上，看另一端谁长谁短\nB. 把两条线段交叉放置比较\nC. 叠合法不需要对齐端点\nD. 叠合法就是用眼睛估计长度",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "线段比较",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["叠合法：一端对齐，另一端在同侧，比较另一端的位置", "落得远的那条更长；重合则相等", "选 A（B、C、D 都不是叠合法的操作）"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "线段比较方法识别（叠合法操作）", "难度理由": "easy——L1 识别", "认知阶梯定位": "L1 诊断——比较方法概念探针", "错因陷阱": "把叠合法当目测/交叉比较（'线段比较方法混淆'）", "教学角色": "诊断题——比较方法概念是否掌握"},
        },
        {
            "slot": "B5-I2",
            "prompt": "小明说：'我量得线段 AB = 15 cm，线段 CD = 1 dm。因为 15 > 1，所以 AB 比 CD 长。'他的判断过程对吗？两条线段谁更长？",
            "expected_answer": "判断过程不对：单位不同不能直接比较 15 和 1。统一单位：1 dm = 10 cm，CD = 10 cm。AB = 15 cm > CD = 10 cm，所以 AB 确实更长（结论碰巧对，但推理错了）。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "单位换算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["比较长度必须先统一单位", "1 dm = 10 cm，所以 CD = 10 cm", "15 cm > 10 cm，AB 更长", "小明的推理（15 > 1）是错的，结论碰巧正确——要指出推理错在单位不统一"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "单位不统一的诊断（比较长度必须统一单位）", "难度理由": "medium——要指出推理错误并重新换算", "认知阶梯定位": "L2 诊断——'单位不统一'错因的直接探针", "错因陷阱": "直接比较 15 和 1（'单位不统一'节点错因）", "教学角色": "诊断题——单位换算意识的一键探针"},
        },
    ],

    # ===== M-G7-ANGLE-CALC 角度计算（计算/几何混合：6 verified + 9 unverifiable） =====
    # 节点契约：essence="角度计算和线段计算一样，抓整体与部分、相等与互补互余关系"；
    # seed=角的和差/余角补角/角平分线/钟表角拓展；common_mistakes=余角补角混淆/角平分线只分一个角/图形关系没标清；
    # diagnostic_probes=2道余补角、2道角平分线、1道综合角度；mastery=能标图列关系、基础角度题正确率≥80%；
    # prereq=M-G7-ANGLE、M-G7-SEGMENT-MEASURE；unlock=M-BRIDGE-CLOCK-ANGLE。
    # authoring 原则（照 SEGMENT-MEASURE 样板）：带"计算：X"纯数值尾的题 verified（答案机算真对），
    # 概念/图形/度分秒题 unverifiable（诚实声明）；L1 真识别（余补规则/角平分线关系）；
    # hard 真难（钟表角半格、对顶角+邻补角、角平分线×补角综合、度分秒借位）；
    # 错因逐一布点："余补混淆"（B1-I1/B2-I0/B2-I1/B4-I1/B5-I1）、"角平分线只分一个角"（B1-I2/B3-I0/B4-I2）、
    # "图形关系没标清"（B4-I0/B5-I0）、"60进制当100"（B2-I2/B5-I0/B5-I2）；
    # 迁移布点：钟表角（B3-I1，unlock BRIDGE-CLOCK-ANGLE 预告）、对顶角（B3-I2，受控拓展）。

    "M-G7-ANGLE-CALC": [
        {
            "slot": "B1-I0",
            "prompt": "射线 OB 在 ∠AOC 的内部，∠AOB = 35 度，∠BOC = 20 度。求 ∠AOC 的度数。计算：35 + 20，∠AOC = ____度。",
            "expected_answer": "55",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角的和差",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["射线 OB 在 ∠AOC 内部，∠AOC 被分成 ∠AOB 和 ∠BOC 两部分", "整体 = 部分 + 部分：∠AOC = ∠AOB + ∠BOC = 35 + 20 = 55（度）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角的和差基本关系（整体 = 部分 + 部分）", "难度理由": "medium 锚点——数值环节简单，建模（选对 35 和 20 相加）是核心", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'图形关系没标清'在 B4-I0/B5-I0 布点）", "教学角色": "讲本质用——essence'角度计算和线段计算一样，抓整体与部分'的演示载体（数值环节机算 verified）"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下列说法正确的是（　）\nA. 和为 180° 的两个角互为余角\nB. 和为 90° 的两个角互为补角\nC. 和为 90° 的两个角互为余角，和为 180° 的两个角互为补角\nD. 两个锐角一定互为余角",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "余角补角",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["互为余角：两个角的和是 90°", "互为补角：两个角的和是 180°", "选 C（A、B 把余角补角的定义说反了；D 中两个锐角的和不一定是 90°）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "余角补角定义识别（90° 互余 / 180° 互补）", "难度理由": "easy——L1 规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现——定义判断（补识别档）", "错因陷阱": "余补混淆（把 90° 当补角、180° 当余角，节点 common_mistake 首条）", "教学角色": "L1 识别脚手架——余补规则的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "射线 OC 平分 ∠AOB。下列关系正确的是（　）\nA. ∠AOC = ∠BOC\nB. ∠AOC = ∠AOB\nC. ∠AOB = ∠BOC\nD. ∠AOC = 2∠AOB",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角平分线",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["角平分线把角分成两个相等的角：∠AOC = ∠BOC", "且每个小角都是 ∠AOB 的一半：∠AOC = ∠BOC = ∠AOB ÷ 2", "选 A（B、C、D 都是角平分线关系的错误变形）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "角平分线定义识别（平分 → 两个相等的小角）", "难度理由": "easy——L1 识别", "认知阶梯定位": "L1 识别正宗实现——平分关系判断", "错因陷阱": "角平分线只分一个角（把一半当整体、×2 方向记反，节点 common_mistake）", "教学角色": "概念识别脚手架——角平分线关系的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "∠A = 35 度。∠A 的补角是多少度？计算：180 − 35，写出答案。",
            "expected_answer": "145",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "余角补角",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["互为补角：两个角的和是 180°", "∠A 的补角 = 180° − 35° = 145°"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "补角数值套用（补角 = 180° − 已知角）", "难度理由": "easy——直接套用补角关系", "认知阶梯定位": "L2 套用——补角关系的直接应用", "错因陷阱": "余补混淆（求成余角 90 − 35 = 55）", "教学角色": "补角计算标准变式——数值环节机算 verified"}
        },
        {
            "slot": "B2-I1",
            "prompt": "∠B = 62 度。∠B 的余角是多少度？计算：90 − 62，写出答案。",
            "expected_answer": "28",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "余角补角",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["互为余角：两个角的和是 90°", "∠B 的余角 = 90° − 62° = 28°"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "余角数值套用（余角 = 90° − 已知角）", "难度理由": "easy——直接套用余角关系", "认知阶梯定位": "L2 套用——余角关系的直接应用", "错因陷阱": "余补混淆（用 180 − 62）", "教学角色": "余角计算标准变式——与 B2-I0 互补（余补各一道套用）"}
        },
        {
            "slot": "B2-I2",
            "prompt": "35 度 20 分加 15 度 50 分，和是多少？（提示：1 度是 60 分，分满 60 要进 1 度）",
            "expected_answer": "51 度 10 分（20 分加 50 分得 70 分，70 分进 1 度剩 10 分；35 度加 15 度再加进位的 1 度得 51 度）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "度分秒换算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先加分数：20′ + 50′ = 70′", "70′ 满 60 要进 1 度：70′ = 1°10′", "度相加：35° + 15° + 1° = 51°", "结果 51°10′（度分秒是 60 进制，不是 100 进制）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "度分秒 60 进制加法（满 60 进位）", "难度理由": "medium——先加分再进位两步，60 进制是核心", "认知阶梯定位": "L3 变式——从整度到度分秒（换度量单位）", "错因陷阱": "60进制当100（把 70′ 当 70 度、写 50°70′ 不进位）", "教学角色": "度分秒换算标准变式——60 进制进位第一道"}
        },
        {
            "slot": "B3-I0",
            "prompt": "OC 是 ∠AOB 的平分线，∠AOC = 36 度。求 ∠AOB 的度数。计算：36 × 2，∠AOB = ____度。",
            "expected_answer": "72",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角平分线",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角平分线把 ∠AOB 分成两个相等的小角：∠AOC = ∠BOC = 36°", "∠AOB = ∠AOC + ∠BOC = 36 + 36 = 72（度），即 ∠AOB = 2 × ∠AOC"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "角平分线反向应用（知道一半求整体）", "难度理由": "medium——与正向（整体求一半）方向相反，需自己建立 ∠AOB = 2×∠AOC", "认知阶梯定位": "L3 变式——角平分线关系换向运用", "错因陷阱": "用除法（36 ÷ 2）、以为 ∠AOB = ∠AOC（角平分线只分一个角）", "教学角色": "变式题——角平分线关系的双向运用"}
        },
        {
            "slot": "B3-I1",
            "prompt": "钟面上 3 点 30 分时，时针和分针的夹角是多少度？提示：钟面一圈 360° 平均分成 12 大格，每大格 30°；3 点 30 分时时针走了 3 个半小时。",
            "expected_answer": "75°（分针指向 6：6 × 30° = 180°；时针从 12 走了 3.5 小时：3.5 × 30° = 105°；夹角 = 180° − 105° = 75°）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "钟表角",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["每大格 360 ÷ 12 = 30°", "3 点 30 分：分针指向 6，位置 6 × 30° = 180°", "时针走了 3.5 小时：3.5 × 30° = 105°（不是 3 × 30° = 90°，30 分时还要再走半格）", "夹角 = 180° − 105° = 75°"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "用度数度量旋转角（钟表角：读时刻 + 每大格 30° + 时针半格）", "难度理由": "hard——时针还要算 30 分的半格（105° 不是 90°），四步推理", "认知阶梯定位": "L4 迁移——角度度量基础（M-G7-ANGLE 前置）× 钟表角，M-BRIDGE-CLOCK-ANGLE unlock 预告", "错因陷阱": "把 3 点半的时针当正好指向 3（漏半格）、每大格度数错", "教学角色": "判定层 transfer 证据来源（C3 双角色）+ 钟表角预告锚点"}
        },
        {
            "slot": "B3-I2",
            "prompt": "两条直线 AB 与 CD 相交于点 O，形成 ∠AOC、∠AOD、∠BOD、∠BOC 四个角。∠AOC = 40 度。与 ∠AOC 相对的是对顶角 ∠BOD，与 ∠AOC 相邻的是邻补角 ∠AOD。求 ∠BOD 和 ∠AOD 的度数，并说出对顶角的大小关系。",
            "expected_answer": "∠BOD = 40°（对顶角相等）；∠AOD = 140°（邻补角互补：180° − 40°）；对顶角相等",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "对顶角",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["两条直线相交成四个角：相对的两个角是对顶角，相邻的两个角是邻补角", "对顶角相等：∠BOD = ∠AOC = 40°", "邻补角互补（和为 180°）：∠AOD = 180° − 40° = 140°", "对顶角的大小关系：相等"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "相交线四角关系迁移（对顶角相等 + 邻补角互补）", "难度理由": "hard——新图形（相交线四角）+ 两种关系（相等/互补）同时用，还要归纳对顶角关系", "认知阶梯定位": "L4 迁移——角的相等与互补关系 × 相交线（受控拓展，为七下相交线埋点）", "错因陷阱": "把邻补角当对顶角（图形关系没标清）、只算出一个角", "教学角色": "判定层 transfer 证据来源（C3 双角色）——相等/互补关系向新图形迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "判断：'如果 ∠AOC = ∠BOC，那么射线 OC 一定是 ∠AOB 的平分线。'这个说法（　）\nA. 正确，两个角相等就是平分线\nB. 错误，还需要射线 OC 在 ∠AOB 的内部\nC. 错误，平分线必须满足 ∠AOC = 2∠BOC\nD. 错误，射线 OC 必须与 OA 重合",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角平分线",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角平分线的定义：从角的顶点出发、在角的内部、把角分成两个相等角的射线", "只有 ∠AOC = ∠BOC 还不够——OC 还必须在 ∠AOB 的内部", "若 OC 在 ∠AOB 外部，∠AOC = ∠BOC 也可能成立，但 OC 不是平分线", "选 B"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角平分线定义的完整性（两角相等 + OC 在角内部）", "难度理由": "medium——需否定'两角相等即平分'的直觉", "认知阶梯定位": "L2 检测——角平分线定义掌握的检测", "错因陷阱": "图形关系没标清（忽略 OC 是否在角内部，节点 common_mistake）", "教学角色": "检测题——角平分线定义完整性的探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "射线 OC 平分 ∠AOB，∠AOC = 35 度。∠AOB 的补角是多少度？计算：180 − 35 × 2，答案是____。",
            "expected_answer": "110",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "余角补角",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["OC 平分 ∠AOB：∠AOB = 2 × ∠AOC = 2 × 35° = 70°", "补角 = 180° − ∠AOB = 180° − 70° = 110°"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "角平分线 × 补角综合（两步建模：先 2 倍再 180° 减）", "难度理由": "hard——角平分线与补角双知识叠加，任何一步方向错即全错", "认知阶梯定位": "L3 检测——综合角度题的检测 hard 档", "错因陷阱": "角平分一半算错（忘 ×2）、余补混淆（求余角 90 − 70 = 20）", "教学角色": "判定层 hard 证据来源（C3 双角色）——综合角度能力取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "已知 OC 平分 ∠AOB，且 ∠AOC = 22 度。∠AOB 的度数是____。计算：22 × 2，写出答案。",
            "expected_answer": "44",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角平分线",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角平分线把角分成两个相等的小角：∠AOC = ∠BOC = 22°", "∠AOB = ∠AOC + ∠BOC = 22 + 22 = 44（度）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "角平分线复测（知道一半求整体，防'会背不会用'）", "难度理由": "medium——与 B3-I0 结构相同换数字，复测定位", "认知阶梯定位": "L3 复测——角平分线掌握确认真实性", "错因陷阱": "把 ∠AOB 当 ∠AOC（只算一半）", "教学角色": "复测题——角平分线关系防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "∠AOB = 90°，射线 OC 在 ∠AOB 的内部，∠AOC = 35°24′。求 ∠BOC 的度数。（提示：先标出图形里的关系，再想 90° 和 35°24′ 怎么减）",
            "expected_answer": "54°36′（∠BOC = ∠AOB − ∠AOC = 90° − 35°24′；90° = 89°60′，89°60′ − 35°24′ = 54°36′）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "综合角度",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["标图列关系：∠AOC + ∠BOC = ∠AOB = 90°（整体 = 部分 + 部分）", "∠BOC = 90° − 35°24′", "向度借 1：90° = 89°60′", "89°60′ − 35°24′ = 54°36′"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "整体部分关系 × 度分秒借位减法综合复测", "难度理由": "hard——60 进制借位（90° → 89°60′）与和差建模双陷阱", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶复测（'图形关系没标清'错因布点）", "错因陷阱": "60进制当100（把 90 − 35.24 当 54.76）、漏借位直接 90 − 35 = 55", "教学角色": "复测 hard 档——判定层 hard 证据来源，综合角度能力取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "∠A = 30°，下列说法正确的是（　）\nA. ∠A 的余角是 60°，补角是 150°\nB. ∠A 的余角是 150°，补角是 60°\nC. ∠A 的余角和补角都是 60°\nD. ∠A 的补角是 120°，余角是 30°",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "余角补角",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["余角 = 90° − 30° = 60°", "补角 = 180° − 30° = 150°", "选 A（B、C、D 都是余补混淆或算错的变形）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "余补角数值诊断（30° 的余角补角）", "难度理由": "easy——但直击余补混淆迷思，easy 档配陷阱题诊断力强", "认知阶梯定位": "L1 诊断——'余补混淆'错因的一键探针", "错因陷阱": "余补混淆（把补角算成 60°）", "教学角色": "诊断题——直接区分'懂余补定义'与'记反定义'"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小华算 2°30′ + 3°40′，他先算 30′ + 40′ = 70′，然后直接写出答案 5°70′。他的答案规范吗？正确的答案是多少？",
            "expected_answer": "不规范——度分秒是 60 进制，70′ 满 60 要进 1 度：70′ = 1°10′，所以 2°30′ + 3°40′ = (2 + 3 + 1)°10′ = 6°10′",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "度分秒换算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["30′ + 40′ = 70′，70′ 超过 60′ 要进位", "70′ = 60′ + 10′ = 1°10′", "度相加：2° + 3° + 1° = 6°", "正确答案 6°10′（5°70′ 写法不规范，70′ 必须进位）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "度分秒 60 进制进位的诊断（70′ 必须进位）", "难度理由": "medium——要指出错误并重新进位计算", "认知阶梯定位": "L2 诊断——'60进制当100'错因的直接探针", "错因陷阱": "把 70′ 当 70 度或直接保留不进位（60进制当100）", "教学角色": "诊断题——60 进制意识的一键探针"}
        },
    ],
    # ===== M-PRE-INTEGER-OPS 整数四则计算（计算向：10 verified + 5 unverifiable） =====
    # 节点契约：essence="整数计算是后面所有代数运算的底层肌肉"；seed=多位数加减乘除/有余数除法验算/简便运算；
    # common_mistakes=进退位错/乘法竖式漏位/余数大于除数/验算习惯差；diagnostic_probes=限时10题口算竖式混合、1道有余数除法验算；
    # mastery=基础计算正确率≥90%、有余数除法能写出验算；prereq=M-PRE-NUMBER-SENSE；
    # unlock=M-G7-RATIONAL-ADD-SUB、M-G7-RATIONAL-MUL-DIV、M-PRE-DECIMAL-OPS、M-PRE-FRACTION-OPS、M-PRE-DISTRIBUTIVE、M-PRE-QUANTITY-RELATION。
    # authoring 原则（照 DECIMAL 样板）：纯"计算：X"题 verified（答案机算真对）；识别/诊断题 unverifiable；
    # L1 真识别（退位适用情形/验算方法）；hard 真难（25×24 简算、48×32、6000−2834 连续借位、(−2)×3 符号预告）；
    # 错因逐一布点："进退位错"（B1-I1/B2-I0/B4-I0/B5-I0/B5-I2）、"乘法竖式漏位"（B2-I1/B4-I1）、
    # "余数大于除数""验算习惯差"（B2-I2/B1-I2）、"0/1 特殊"（B5-I1）；
    # 迁移布点：简便运算（B3-I1，M-PRE-DISTRIBUTIVE 预告）、有理数符号运算（B3-I2，M-G7-RATIONAL-MUL-DIV 预告）。

    "M-PRE-INTEGER-OPS": [
        {
            "slot": "B1-I0",
            "prompt": "计算：47 + 38，写出答案。",
            "expected_answer": "85",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["个位 7 + 8 = 15，写 5 向十位进 1", "十位 4 + 3 + 1 = 8", "结果 85"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "两位数加法进位（个位满十进一）", "难度理由": "medium 锚点——取节点最简流程作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'进退位错'在 B2-I0/B4-I0/B5-I0 布点）", "教学角色": "讲本质用——essence'整数计算是后面所有代数运算的底层肌肉'的演示载体（数值环节机算 verified）"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下列算式中，需要'退位'（向高位借 1）才能计算的是（　）\nA. 35 + 42\nB. 52 − 47\nC. 20 × 3\nD. 100 ÷ 4",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "运算规则识别",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["退位出现在减法：被减数个位不够减时向十位借 1", "52 − 47：个位 2 − 7 不够减，需要退位", "A 是加法不进位、C/D 是乘除，都不涉及退位", "选 B"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "判断'退位'的适用情形（减法个位不够减）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断考点/规则而非直接计算（补识别档）", "错因陷阱": "把不进位加法误判为要退位（进退位错的概念形态）", "教学角色": "L1 识别脚手架——进退位规则的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "要检验除法 56 ÷ 8 = 7 算得对不对，应该用下面哪种方法验算？（　）\nA. 7 + 8\nB. 7 × 8\nC. 56 − 7\nD. 56 ÷ 7",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "验算规则",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["除法各部分关系：被除数 = 商 × 除数 + 余数", "整除时：被除数 = 商 × 除数", "验算：7 × 8 = 56，与被除数一致，说明算对了", "选 B"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "除法验算规则识别（商 × 除数 = 被除数）", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别正宗实现——验算方法判断", "错因陷阱": "验算习惯差（不会选验算方法、用加法/减法验算）", "教学角色": "L1 识别脚手架——验算意识的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：63 − 27，写出答案。",
            "expected_answer": "36",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["个位 3 − 7 不够减，向十位借 1：13 − 7 = 6", "十位 6 被借走 1 剩 5：5 − 2 = 3", "结果 36"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "两位数减法退位（个位不够减向十位借）", "难度理由": "easy——单次退位，直击'进退位错'错因", "认知阶梯定位": "L2 套用——减法退位的直接应用", "错因陷阱": "借位后十位忘减 1（63 − 27 算成 46）", "教学角色": "退位减法标准变式——进退位错错因布点"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：38 × 6，写出答案。",
            "expected_answer": "228",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数乘除",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["个位 8 × 6 = 48，写 8 进 4", "十位 3 × 6 + 4 = 18 + 4 = 22", "结果 228"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "两位数 × 一位数进位乘法", "难度理由": "easy——标准竖式流程", "认知阶梯定位": "L2 套用——乘法竖式的直接应用", "错因陷阱": "乘法竖式漏位（进位 4 忘加、结果写 184）", "教学角色": "乘法竖式标准变式——乘法竖式漏位错因布点"}
        },
        {
            "slot": "B2-I2",
            "prompt": "把 50 平均分成 8 份：商和余数各是多少？再用'商乘除数加余数'验算，写出验算式。",
            "expected_answer": "商 6 余 2；验算：6 × 8 + 2 = 48 + 2 = 50，与被除数一致",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "有余数除法验算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["8 × 6 = 48 < 50，8 × 7 = 56 > 50，所以商 6", "余数 = 50 − 48 = 2（余数 2 < 除数 8）", "验算：商 × 除数 + 余数 = 6 × 8 + 2 = 50，等于被除数"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "有余数除法 + 验算（商 × 除数 + 余数 = 被除数）", "难度理由": "medium——试商 + 验算两步，对应 mastery'有余数除法能写出验算'", "认知阶梯定位": "L3 变式——从整除到有余数（换形式：加验算环节）", "错因陷阱": "余数大于除数（试商偏小）、验算习惯差（不会写验算式）", "教学角色": "有余数除法验算标准变式——验算习惯错因布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：356 + 248，写出答案。",
            "expected_answer": "604",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数加减",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["个位 6 + 8 = 14，写 4 进 1", "十位 5 + 4 + 1 = 10，写 0 进 1", "百位 3 + 2 + 1 = 6", "结果 604"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "三位数加法连续进位（十位满十再进百位）", "难度理由": "medium——两次进位 + 十位写 0", "认知阶梯定位": "L3 变式——从两位数到三位数（加长流程）", "错因陷阱": "进退位错（十位 5 + 4 忘加进位的 1 得 594）", "教学角色": "三位数加法变式——进退位错错因的加长形态"}
        },
        {
            "slot": "B3-I1",
            "prompt": "用简便方法计算：25 × 24，写出答案。",
            "expected_answer": "600",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "简便运算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["25 × 4 = 100，把 24 拆成 4 × 6", "25 × 24 = 25 × 4 × 6 = 100 × 6 = 600", "直接列竖式也能算，但简便方法更快（因数拆分为 M-PRE-DISTRIBUTIVE 前置预告）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "简便运算（凑 25 × 4 = 100 的因数拆分）", "难度理由": "hard——'用简便方法计算'强制策略识别（拆 24 为 4 × 6），看不出公因数则失去简算意义", "认知阶梯定位": "L4 迁移——乘法运算 × 因数拆分，M-PRE-DISTRIBUTIVE unlock 预告", "错因陷阱": "看不出 25 × 4、竖式硬算（策略盲区）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——简算策略迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：(−2) × 3，写出答案。（这是有理数乘法的一点预告：负数乘正数，得负数）",
            "expected_answer": "-6",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "有理数符号预告",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["数字部分按乘法口诀：2 × 3 = 6", "符号规则预告：负数 × 正数 = 负数，所以结果是 −6", "注意：(−2) × 3 = −6（不是 6）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "负号参与乘法的符号规则预告（迁移到有理数乘法）", "难度理由": "hard——新规则（负 × 正 = 负）首次出现，超出小学熟知的整数范围", "认知阶梯定位": "L4 迁移——整数乘法 × 符号规则，M-G7-RATIONAL-MUL-DIV unlock 预告", "错因陷阱": "丢掉负号写 6（符号意识缺）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——有理数符号运算预告"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：503 − 218，写出答案。",
            "expected_answer": "285",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["个位 3 − 8 不够减，十位是 0，先向百位借：百位 5 → 4，十位 10", "十位再借 1 给个位：十位 9，个位 13；13 − 8 = 5", "十位 9 − 1 = 8；百位 4 − 2 = 2", "结果 285"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含 0 的连续退位减法（隔位借位链）", "难度理由": "medium——0 的借位链（向百位借两次）是退位难点", "认知阶梯定位": "L2 检测——退位减法掌握的检测", "错因陷阱": "进退位错（0 借位链断掉）", "教学角色": "检测题——连续退位流程的探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：48 × 32，写出答案。",
            "expected_answer": "1536",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数乘除",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["48 × 32 = 48 × 2 + 48 × 30（分两步乘再相加）", "48 × 2 = 96", "48 × 30 = 1440", "96 + 1440 = 1536"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "两位数 × 两位数竖式（乘两步 + 错位相加）", "难度理由": "hard——第二步 1440 的位值（个位写 0）与进位叠加，任何一步错即全错", "认知阶梯定位": "L3 检测——乘法竖式的深度检测", "错因陷阱": "乘法竖式漏位（1440 的 0 漏写、把 144 当第二步结果）", "教学角色": "检测 hard 档——判定层 hard 证据来源，乘法流程取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：96 ÷ 4，写出答案。",
            "expected_answer": "24",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数乘除",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["十位 9 ÷ 4 = 2 余 1（2 × 4 = 8，9 − 8 = 1）", "余数 1 与个位 6 合成 16", "16 ÷ 4 = 4", "结果 24"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两位数除以一位数（十位有余数并入个位）", "难度理由": "medium——竖式除法'余数落下来'流程", "认知阶梯定位": "L3 复测——除法竖式流程防遗忘复测", "错因陷阱": "把余数丢掉、余数大于除数", "教学角色": "复测题——除法竖式流程的防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：6000 − 2834，写出答案。",
            "expected_answer": "3166",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "多位数加减",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["个位 0 − 4 不够减，隔位连续借：6000 变 5990 再借 → 个位 10", "10 − 4 = 6；十位 9 − 3 = 6；百位 9 − 8 = 1；千位 5 − 2 = 3", "结果 3166"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "含多个 0 的隔位连续退位减法", "难度理由": "hard——连续三个 0 的借位链（6000 → 5990 → 个位 10）是退位减法的极限形态", "认知阶梯定位": "L4 复测——进退位流程的最高阶复测", "错因陷阱": "进退位错（借位链断掉，常见 3834/4834 等）", "教学角色": "复测 hard 档——判定层 hard 证据来源，连续退位流程取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "下列说法正确的是（　）\nA. 0 乘任何数都得 0\nB. 1 乘任何数都得 0\nC. 任何数除以 0 都得 0\nD. 0 除以任何数都得 1",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "0/1 运算规则",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["0 × 任何数 = 0（0 的特殊性质）", "1 × 任何数 = 它本身（不是 0）", "0 不能作除数（除以 0 没有意义）", "0 ÷ 任何非零数 = 0（不是 1）", "选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "0 与 1 在乘除法中的特殊性质识别", "难度理由": "easy——规则判断，无计算", "认知阶梯定位": "L1 诊断——'0/1 特殊'错因的一键探针", "错因陷阱": "0 作除数、1 × n = 0、0 ÷ n = 1（0/1 特殊规则混淆）", "教学角色": "诊断题——0 与 1 特殊性质是否掌握的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小丽做 71 减 35：她说个位 1 减 5 不够减，向十位借 1 变 11，11 减 5 得 6；十位 7 减 3 得 4，所以答案是 46。她错在哪里？正确的答案是多少？",
            "expected_answer": "错在借位后十位没有减 1：十位 7 被借走 1 剩 6，6 减 3 得 3；正确结果 36",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "进退位诊断",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["个位 1 − 5 不够减，向十位借 1：个位 11，11 − 5 = 6", "十位被借走 1：7 − 1 = 6，6 − 3 = 3（小丽漏了'借走 1'）", "正确结果 36"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "退位减法'借 1 忘减'的诊断", "难度理由": "medium——要指出具体错误步骤并重算", "认知阶梯定位": "L2 诊断——'进退位错'错因的直接探针", "错因陷阱": "借位后十位忘减 1（进退位错的核心形态）", "教学角色": "诊断题——进退位流程漏洞的一键探针"}
        },
    ],
    # ===== M-PRE-ORDER-OPS 四则混合运算与括号（计算向：11 verified + 4 unverifiable） =====
    # 节点契约：essence="算式有交通规则：括号优先，先乘除后加减，同级从左到右"；
    # seed=整数混合运算/小数分数混合/含括号运算；common_mistakes=跳步导致顺序错/同级运算不从左到右/括号去掉后符号错；
    # diagnostic_probes=4道混合运算至少含一题括号和一题同级连算；mastery=正确率≥85%、能说出每一步为什么先算它；
    # prereq=M-PRE-NUMBER-SENSE；unlock=M-G7-RATIONAL-MIXED、M-G7-EXPR-VALUE、M-G7-EQ-SOLVE、M-PRE-DISTRIBUTIVE、M-PRE-EQUATION-BASIC、M-PRE-GEO-AREA-VOLUME。
    # authoring 原则（照 DECIMAL 样板）：纯"计算：X"题 verified（答案机算真对）；识别/诊断题 unverifiable；
    # L1 真识别（先算哪一步/括号优先）；hard 真难（2.5×4−3 小数混合、8−3×(−2) 负号、括号+同级双陷阱、三步全程）；
    # 错因逐一布点："同级忘顺序"（B2-I0/B4-I1/B5-I0/B5-I1）、"括号内先算漏"（B1-I2/B2-I2/B3-I0/B4-I2/B5-I0/B5-I2）、
    # "跳步导致顺序错"（B2-I1/B4-I0）、"括号去掉后符号错"（B5-I2）；
    # 迁移布点：小数混合运算（B3-I1，M-PRE-DECIMAL-OPS 前置运用）、有理数符号运算（B3-I2，M-G7-RATIONAL-MIXED 预告）。

    "M-PRE-ORDER-OPS": [
        {
            "slot": "B1-I0",
            "prompt": "计算：3 + 4 × 2，写出答案。",
            "expected_answer": "11",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "先乘除后加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先乘除后加减：先算 4 × 2 = 8", "再算 3 + 8 = 11", "注意：先算 3 + 4 会得 14（错）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "先乘除后加减的运算顺序", "难度理由": "medium 锚点——最简混合式作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'同级忘顺序''括号内先算漏'在后续槽位布点）", "教学角色": "讲本质用——essence'算式有交通规则：先乘除后加减'的演示载体（数值环节机算 verified）"}
        },
        {
            "slot": "B1-I1",
            "prompt": "在算式 24 − 4 × 5 中，应该先算哪一步？（　）\nA. 24 − 4\nB. 4 × 5\nC. 从右往左算\nD. 先算哪步都可以",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "运算顺序规则",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["算式里没有括号", "先乘除后加减：先算乘法 4 × 5 = 20", "再算 24 − 20 = 4", "选 B（A 是先减后乘，顺序错）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "先乘除后加减的规则识别（无括号时先算乘除）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断先算哪一步（补识别档）", "错因陷阱": "先加减后乘除（顺序错）", "教学角色": "L1 识别脚手架——运算顺序规则的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "算式 (12 + 8) ÷ 4 中，应该先算哪一步？（　）\nA. 12 + 8\nB. 8 ÷ 4\nC. 12 ÷ 4\nD. 先算 12 再算除法",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "括号优先",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["括号优先：先算括号里面的 12 + 8 = 20", "再算 20 ÷ 4 = 5", "选 A（B、C 都无视了括号的优先权）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "括号优先的规则识别", "难度理由": "easy——规则识别", "认知阶梯定位": "L1 识别正宗实现——括号优先判断", "错因陷阱": "括号内先算漏（无视括号直接 8 ÷ 4）", "教学角色": "L1 识别脚手架——括号优先规则的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：20 − 8 + 5，写出答案。",
            "expected_answer": "17",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "同级混合运算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["只有加减，同级运算从左到右", "20 − 8 = 12", "12 + 5 = 17（先算 8 + 5 得 20 − 13 = 7 是错的）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "同级加减从左到右", "难度理由": "easy——同级规则直接应用", "认知阶梯定位": "L2 套用——同级顺序的标准应用", "错因陷阱": "同级忘顺序（先算 8 + 5 得 7）", "教学角色": "同级混合标准变式——同级忘顺序错因布点"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：12 ÷ 3 + 5，写出答案。",
            "expected_answer": "9",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "先乘除后加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先乘除后加减：先算 12 ÷ 3 = 4", "再算 4 + 5 = 9（先算 3 + 5 得 12 ÷ 8 是错的）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "除加混合的先除后加", "难度理由": "easy——两级规则直接应用", "认知阶梯定位": "L2 套用——先乘除后加减的标准应用", "错因陷阱": "顺序错（先加后除）", "教学角色": "两级混合标准变式——与 B1-I0 互补（除在加前）"}
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：(18 + 6) ÷ 4，写出答案。",
            "expected_answer": "6",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "含括号运算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["括号优先：18 + 6 = 24", "再算 24 ÷ 4 = 6"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含括号混合（括号优先 + 除法）", "难度理由": "medium——括号优先与除法的两步衔接", "认知阶梯定位": "L3 变式——从无括号到含括号", "错因陷阱": "括号内先算漏（先算 18 ÷ 4 或 6 ÷ 4）", "教学角色": "含括号标准变式——括号优先错因布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：8 × (15 − 9)，写出答案。",
            "expected_answer": "48",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "含括号运算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["括号优先：15 − 9 = 6", "再算 8 × 6 = 48（先算 8 × 15 得 120 − 9 是错的）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "括号在乘法前的混合（括号优先 + 乘法）", "难度理由": "medium——括号内是减法，先算括号再乘", "认知阶梯定位": "L3 变式——括号位置的换向（乘在括号外）", "错因陷阱": "括号内先算漏（先算 8 × 15）", "教学角色": "含括号变式——与 B2-I2 互补（括号内是减法）"}
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：2.5 × 4 − 3，写出答案。",
            "expected_answer": "7",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "小数混合运算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先乘除后加减：先算 2.5 × 4 = 10", "再算 10 − 3 = 7"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "小数参与的两级混合（迁移 M-PRE-DECIMAL-OPS）", "难度理由": "hard——小数乘法（积去尾零 10.0 → 10）× 运算顺序双知识叠加", "认知阶梯定位": "L4 迁移——整数混合 × 小数运算（前后知识点混合）", "错因陷阱": "小数积位数错（2.5 × 4 算 1 或 100）、顺序错（先 4 − 3）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——小数混合迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：8 − 3 × (−2)，写出答案。（这是有理数混合运算的一点预告：先乘除后加减，注意负号）",
            "expected_answer": "14",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "有理数符号预告",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先乘除后加减：先算 3 × (−2) = −6", "再算 8 − (−6) = 8 + 6 = 14（减去负数等于加正数）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "含负号的混合运算顺序（预告 M-G7-RATIONAL-MIXED unlock）", "难度理由": "hard——先乘除后加减 × 负号运算双新元素", "认知阶梯定位": "L4 迁移——混合运算顺序 × 有理数符号，M-G7-RATIONAL-MIXED unlock 预告", "错因陷阱": "先算 8 − 3、减负数不会变加（符号错）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——有理数混合运算预告"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：6 × 7 − 18 ÷ 3，写出答案。",
            "expected_answer": "36",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "两级混合运算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两级混合：先分别算乘和除", "6 × 7 = 42；18 ÷ 3 = 6", "再算 42 − 6 = 36"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "乘除同级的混合（两个乘除项先算完再相减）", "难度理由": "medium——先算两项乘除再算减，两级规则的综合", "认知阶梯定位": "L2 检测——两级运算顺序掌握的检测", "错因陷阱": "顺序错（先算 7 − 18 或 6 × 7 − 18）", "教学角色": "检测题——先乘除后加减的掌握检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：(36 − 12) ÷ 4 × 5，写出答案。",
            "expected_answer": "30",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "含括号运算",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["括号优先：36 − 12 = 24", "同级乘除从左到右：24 ÷ 4 = 6", "6 × 5 = 30（先算 4 × 5 得 24 ÷ 20 是错的）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "括号 + 同级乘除从左到右的双重陷阱", "难度理由": "hard——括号优先之后还要同级从左到右，两步规则叠加", "认知阶梯定位": "L3 检测——运算顺序的综合检测 hard 档", "错因陷阱": "同级忘顺序（先算 4 × 5）、括号内先算漏", "教学角色": "判定层 hard 证据来源（C3 双角色）——混合顺序综合取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：(25 + 15) ÷ 8，写出答案。",
            "expected_answer": "5",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "含括号运算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["括号优先：25 + 15 = 40", "再算 40 ÷ 8 = 5"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含括号混合复测（防'会背不会用'）", "难度理由": "medium——与 B2-I2 结构相同换数字，复测定位", "认知阶梯定位": "L3 复测——括号优先掌握确认真实性", "错因陷阱": "括号内先算漏（先算 15 ÷ 8）", "教学角色": "复测题——括号优先防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：72 ÷ (24 − 16) × 3，写出答案。",
            "expected_answer": "27",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "含括号运算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["括号优先：24 − 16 = 8", "同级乘除从左到右：72 ÷ 8 = 9", "9 × 3 = 27（先算 8 × 3 得 72 ÷ 24 = 3 是错的）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "括号 + 同级从左到右 + 两级规则的全程综合复测", "难度理由": "hard——三步顺序环环相扣，任何一步乱序即错", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶复测", "错因陷阱": "括号内先算漏 + 同级忘顺序双陷阱", "教学角色": "复测 hard 档——判定层 hard 证据来源，混合顺序综合取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "判断：做 18 除以 6 再乘 3 时，先算 6 乘 3 得 18，再算 18 除以 18 得 1。（　）\nA. 对，乘除可以随便先算\nB. 错，同级运算要从左到右，应先做 18 除以 6 得 3，再做 3 乘 3 得 9\nC. 对，先算哪边都可以\nD. 错，应先把 6 乘 3 算出来",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "运算顺序规则",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["18 ÷ 6 × 3 只有乘除，是同级运算", "同级运算从左到右：先算 18 ÷ 6 = 3", "再算 3 × 3 = 9（先算 6 × 3 得 1 是错的）", "选 B"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "同级乘除从左到右的诊断判断", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——'同级忘顺序'错因的一键探针", "错因陷阱": "同级忘顺序（先算右边的乘除）", "教学角色": "诊断题——同级顺序规则是否掌握的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小丽算 24 − (6 + 8)，她写：24 − 6 + 8 = 18 + 8 = 26。她错在哪里？正确的答案是多少？",
            "expected_answer": "错在没先算括号里：应先算 6 + 8 = 14，再算 24 − 14 = 10；小丽把括号丢掉直接 24 − 6 + 8，得 26 是错的",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "括号运算诊断",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["括号优先：先算 6 + 8 = 14", "再算 24 − 14 = 10", "小丽直接 24 − 6 + 8 = 26，相当于把括号丢掉了（括号内先算漏 + 去括号变号问题）", "正确答案 10"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "括号内先算漏的诊断（括号优先被无视）", "难度理由": "medium——要指出具体错误并重算", "认知阶梯定位": "L2 诊断——'括号内先算漏'错因的直接探针", "错因陷阱": "括号内先算漏、去掉括号后符号错（24 − (6 + 8) 当作 24 − 6 + 8）", "教学角色": "诊断题——括号优先意识的一键探针"}
        },
    ],
    # ===== M-PRE-FRACTION-OPS 分数运算（计算向：11 verified + 4 unverifiable） =====
    # 节点契约：essence="分数加减靠通分，分数乘除靠约分和倒数"；
    # seed=通分加减/分数乘法/分数除法/分数混合运算；common_mistakes=通分只改分母不改分子/约分不彻底/
    # 除法忘记乘倒数/带分数处理错；diagnostic_probes=2道加减、2道乘除、2道混合；mastery=正确率≥85%、能说明通分/倒数规则；
    # prereq=M-PRE-FRACTION-MEANING、M-PRE-INTEGER-OPS；unlock=M-G7-RATIONAL-MIXED、M-G7-EQ-DENOM、M-PRE-RATIO-PROP、M-G7-RATIONAL-MUL-DIV。
    # authoring 原则（照 DECIMAL/ORDER 样板）：纯"计算：X"题 verified（答案机算真对）；识别/诊断题 unverifiable；
    # L1 真识别（判断是否要通分/除法第一步）；hard 真难（三项大公分母、括号+通分+倒数、乘除链连续约分、大数除法约分）；
    # 错因逐一布点："通分找错公分母/只改分母不改分子"（B2-I0/B2-I2/B5-I0/B5-I1）、"约分不彻底"（B2-I1/B3-I0/B4-I1）、
    # "除法忘记乘倒数"（B1-I2/B3-I0/B4-I2）、"带分数处理错"（B5-I2 诊断）；
    # 迁移布点：小数与分数互化（B3-I1，M-PRE-DECIMAL-OPS 前置运用）、运算顺序×分数（B3-I2，M-PRE-ORDER-OPS 前置运用）。

    "M-PRE-FRACTION-OPS": [
        {
            "slot": "B1-I0",
            "prompt": "计算：1/5 + 2/5，写出答案。",
            "expected_answer": "3/5",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "通分加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["同分母分数相加：分母不变，分子相加", "1 + 2 = 3，分母还是 5", "1/5 + 2/5 = 3/5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "同分母分数加法（分母不变分子相加）", "难度理由": "锚点题取最简，medium 是教学锚点难度而非认知难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——essence'分数加减靠通分'的起点演示：同分母不需通分，异分母才通分"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪道分数加法需要先通分再计算？（　）\nA. 1/3 + 1/3\nB. 1/3 + 1/6\nC. 2/7 + 3/7\nD. 4/9 + 5/9",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "通分加减",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同分母分数相加不用通分（A、C、D 的分母相同）", "异分母相加要先通分：B 的分母 3 和 6 不同，通分成 6", "选 B"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "判断'通分'规则的适用对象（异分母加减才通分）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断考点/规则而非直接计算", "错因陷阱": "看到分数就以为要通分（同分母也通分）、把通分和约分混淆", "教学角色": "L1 识别脚手架——通分适用对象的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "在算式 2/3 ÷ 4/5 中，正确的第一步是（　）\nA. 2/3 × 4/5\nB. 2/3 × 5/4\nC. 2/3 ÷ 5/4\nD. 分子除分子、分母除分母",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分数除法",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["除以一个数等于乘这个数的倒数，4/5 的倒数是 5/4", "2/3 ÷ 4/5 = 2/3 × 5/4", "选 B（A 忘了取倒数，C 取了倒数但除号没改乘号，D 是错误直除）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'除法改乘倒数'规则识别（倒数取法）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现——'除法忘记乘倒数'错因的第一道判断", "错因陷阱": "忘记取倒数（A）、倒数取对但除号没改（C）、直除（D）", "教学角色": "L1 识别脚手架——倒数规则第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：1/2 + 1/3，写出答案。",
            "expected_answer": "5/6",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "通分加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["异分母相加先通分：2 和 3 的最小公倍数是 6", "1/2 = 3/6，1/3 = 2/6", "3/6 + 2/6 = 5/6"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "异分母分数加法（通分）", "难度理由": "medium——通分一步是核心错因'通分找错公分母/只改分母不改分子'的高发点", "认知阶梯定位": "L2 套用（标准异分母加减）", "错因陷阱": "通分只改分母不改分子（把 1/2 当 1/6）、公分母找错（用 2 或 3）", "教学角色": "通分标准变式——'先统一分母再加减'的取证题"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：2/5 × 3/4，写出答案。",
            "expected_answer": "3/10",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数乘法",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分数乘法：分子乘分子、分母乘分母", "2 × 3 = 6，5 × 4 = 20，得 6/20", "约分：6/20 = 3/10"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "分数乘法（分子×分子、分母×分母 + 约分）", "难度理由": "easy——小数字直接套用，约分一步", "认知阶梯定位": "L2 套用（标准分数乘法）", "错因陷阱": "交叉相乘、约分不彻底（停在 6/20）", "教学角色": "乘法标准变式——'约分不彻底'错因布点"}
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：5/6 − 1/4，写出答案。",
            "expected_answer": "7/12",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "通分加减",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["异分母相减先通分：6 和 4 的最小公倍数是 12", "5/6 = 10/12，1/4 = 3/12", "10/12 − 3/12 = 7/12"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "异分母分数减法（通分 + 分子相减）", "难度理由": "medium——通分与减法两步衔接", "认知阶梯定位": "L3 变式——从加法到减法（换运算）", "错因陷阱": "通分只改分母不改分子（把 5/6 当 5/12）、分子直接相减", "教学角色": "减法变式——通分错因在减法场景的布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：(7/9) ÷ (14/27)，写出答案。",
            "expected_answer": "3/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数除法",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["除以一个数等于乘它的倒数：14/27 的倒数是 27/14", "7/9 × 27/14：7 和 14 约分（÷7），27 和 9 约分（÷9）", "得 1/1 × 3/2 = 3/2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "分数除法（乘倒数 + 连续约分）", "难度理由": "hard——取倒数后有两处可约分，'约分不彻底'或'忘取倒数'都会全错，且结果 3/2 是假分数需判断表达", "认知阶梯定位": "L3 变式——除法换倒数的大数约分变式", "错因陷阱": "忘记乘倒数、约分不彻底（停在 189/126）、倒数取错", "教学角色": "判定层 hard 证据来源（C3 双角色）——乘倒数×约分综合取证"}
        },
        {
            "slot": "B3-I1",
            "prompt": "计算：1/8 + 0.25，用分数表示答案。",
            "expected_answer": "3/8",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "小数与分数互化",
            "variant_level": "L4",
            "difficulty": "medium",
            "purpose_role": "transfer",
            "solution_steps": ["把 0.25 化成分数：0.25 = 25/100 = 1/4", "1/8 + 1/4 = 1/8 + 2/8 = 3/8"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "小数化分数后加法（互化 + 通分）", "难度理由": "medium——0.25→1/4 化分数与通分到 8 两步衔接（照 DECIMAL 互化题诚实标 medium，P1#4 教训）", "认知阶梯定位": "L4 迁移——互化方向与 M-PRE-DECIMAL-OPS 前置知识混合", "错因陷阱": "0.25 误当 25/8、互化后分子忘跟着变", "教学角色": "判定层 transfer 证据来源（C3 双角色）——分数×小数互化迁移；题干注明'用分数表示'消除答案形式歧义"}
        },
        {
            "slot": "B3-I2",
            "prompt": "计算：(2/3 − 1/2) ÷ (1/4)，写出答案。",
            "expected_answer": "2/3",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数混合运算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["括号优先：2/3 − 1/2 通分到 6，得 4/6 − 3/6 = 1/6", "再算 1/6 ÷ 1/4：乘倒数得 1/6 × 4", "4/6 约分 = 2/3"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "括号优先 × 通分 × 除法乘倒数的三步混合", "难度理由": "hard——括号内先通分、括号外乘倒数、结果约分，三步环环相扣，任何一步错即全错", "认知阶梯定位": "L4 迁移——运算顺序（M-PRE-ORDER-OPS 前置）× 分数运算", "错因陷阱": "括号内先算漏（先算 2/3 ÷ 1/4）、通分错、忘取倒数", "教学角色": "判定层 transfer 证据来源（C3 双角色）——运算顺序×分数迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：3/7 + 2/7，写出答案。",
            "expected_answer": "5/7",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "通分加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["同分母分数相加：分母不变，分子相加", "3 + 2 = 5", "3/7 + 2/7 = 5/7"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "同分母分数加法检测（防'会背不会用'）", "难度理由": "easy 检测——同分母加法直接套用", "认知阶梯定位": "L2 检测", "错因陷阱": "分子相加写成分子乘分子（3/7 + 2/7 = 6/49）", "教学角色": "掌握档快速检测——B1-I0 锚点的同型检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：(3/4) × (2/3) ÷ (1/8)，写出答案。",
            "expected_answer": "4",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "分数混合运算",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["同级乘除从左到右：先算 3/4 × 2/3", "3/4 × 2/3 = 6/12 = 1/2（约分）", "1/2 ÷ 1/8 = 1/2 × 8 = 4"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "乘除同级链（从左到右 + 连续约分 + 乘倒数）", "难度理由": "hard——乘除链两步、处处有约分机会，'同级忘顺序''约分不彻底'双陷阱叠加", "认知阶梯定位": "L3 检测 hard——分数乘除综合检测", "错因陷阱": "先算 2/3 ÷ 1/8 再乘（同级忘顺序）、约分不彻底", "教学角色": "判定层 hard 证据来源（C3 双角色）——乘除链综合取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：(2/3) ÷ (4/9)，写出答案。",
            "expected_answer": "3/2",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "分数除法",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["除以一个数等于乘它的倒数：4/9 的倒数是 9/4", "2/3 × 9/4 = 18/12", "约分：18/12 = 3/2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数除法复测（防'会背不会用'）", "难度理由": "medium——取倒数与约分两步", "认知阶梯定位": "L3 复测——除法乘倒数掌握确认真实性", "错因陷阱": "忘记乘倒数（2/3 ÷ 4/9 = 2/3 × 4/9 错）、约分不彻底", "教学角色": "复测题——乘倒数防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：5/6 + 3/4 − 1/2，写出答案。",
            "expected_answer": "13/12",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "通分加减",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["三项通分：6、4、2 的最小公倍数是 12", "5/6 = 10/12，3/4 = 9/12，1/2 = 6/12", "10/12 + 9/12 − 6/12 = 13/12"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "三项加减的通分复测（公分母 12 + 最简判断）", "难度理由": "hard——三项通分到较大公分母 12，'通分找错公分母'即全错，且结果 13/12 是最简假分数需判断", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶通分复测", "错因陷阱": "通分找错公分母（用 6 或 24）、只改分母不改分子", "教学角色": "复测 hard 档——判定层 hard 证据来源，通分综合取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小明算 1/2 + 1/4，他写：1/2 + 1/4 = 1/4 + 1/4 = 2/4 = 1/2。他错在哪里？（　）\nA. 通分时只改了分母，分子没有跟着变：1/2 通分成 2/4，不是 1/4\nB. 结果没化成带分数\nC. 应该先乘倒数\nD. 分母不该通分",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "通分加减",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["正确通分：1/2 = 2/4，1/4 不变", "2/4 + 1/4 = 3/4", "小明把 1/2 当 1/4：分母乘了 2、分子没乘 2，正是'通分只改分母不改分子'", "选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'通分只改分母不改分子'错因的诊断", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——节点 #1 错因的一键探针", "错因陷阱": "通分只改分母不改分子（1/2 → 1/4）", "教学角色": "诊断题——通分规则是否真懂的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小明算 1 又 1/2 + 1 又 1/3，他写：整数加整数得 2，分数加分数 1/2 + 1/3 得 2/5，所以等于 2 又 2/5。他错在哪里？正确的答案是多少？",
            "expected_answer": "错在带分数不能'整数加整数、分数加分数'直接拼：应先把带分数化成假分数，1 又 1/2 = 3/2，1 又 1/3 = 4/3；3/2 + 4/3 = 9/6 + 8/6 = 17/6 = 2 又 5/6。另外 1/2 + 1/3 = 5/6，不是 2/5（分母不能直接相加）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数混合运算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["带分数运算先把带分数化成假分数：1 又 1/2 = 3/2，1 又 1/3 = 4/3", "通分：3/2 = 9/6，4/3 = 8/6", "9/6 + 8/6 = 17/6 = 2 又 5/6", "小明两处错：带分数未化假分数直接拼、1/2 + 1/3 分母直接相加得 2/5"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'带分数处理错'错因的诊断（带分数未化假分数）", "难度理由": "medium——要指出具体错误并重算", "认知阶梯定位": "L2 诊断——'带分数处理错'的直接探针", "错因陷阱": "带分数运算忘化假分数（整数加整数、分数加分数直接拼）、分数分母直接相加（1/2 + 1/3 = 2/5）", "教学角色": "诊断题——带分数运算意识的一键探针"}
        },
    ],
    # ===== M-PRE-QUANTITY-RELATION 等量关系与列式（列式向：15 unverifiable；全图枢纽节点） =====
    # 节点契约：essence="应用题最关键不是算，而是找到两个相等的量"；
    # seed=根据文字找等量关系/线段图/表格整理条件；common_mistakes=只盯数字不看关系/把多少倍关系写反/未知量设错；
    # diagnostic_probes=给3个文字情境只要求写等量关系不求解；mastery=能一句话写出等量关系、能解释每个量代表什么；
    # prereq=M-PRE-INTEGER-OPS；unlock=M-PRE-EQUATION-BASIC、M-G7-EQ-WORD、M-PRE-LETTER-EXPR、M-BRIDGE-* 等下游节点。
    # authoring 原则（照 EQ-WORD 概念向样板）：全部 unverifiable（列式/等量关系题，题干不嵌显式算式）；
    # L1 真识别（判断哪句是相等的量/关系方向）；hard 真难（和倍双关系、差倍双关系、倍少复合、两段借出差）；
    # 错因逐一布点："关系找反"（B1-I2/B2-I2/B3-I2/B4-I1/B5-I0）、"漏总量"（B2-I0/B3-I0/B3-I1/B4-I0）、
    # "倍份关系错"（B2-I1/B3-I0/B4-I1/B5-I0）、"只盯数字不看关系"（B5-I1 诊断）、"未知量设错"（B5-I2 诊断）；
    # 迁移布点：线段图（B3-I1）、表格整理条件（B4-I2）、设未知量预告（B2-I2/B3-I1/B3-I2/B5-I0，M-PRE-EQUATION-BASIC 预告）。

    "M-PRE-QUANTITY-RELATION": [
        {
            "slot": "B1-I0",
            "prompt": "一箱苹果重 20 千克，大苹果 12 千克，小苹果 8 千克。用'总量 = 部分 + 部分'写出等量关系。",
            "expected_answer": "总量 = 大苹果 + 小苹果，即 20 = 12 + 8",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先找到两个相等的量：总量（20 千克）等于各部分之和", "部分有：大苹果 12 千克、小苹果 8 千克", "等量关系：总量 = 部分 + 部分，即 20 = 12 + 8"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'总量 = 部分 + 部分'基本关系（标准例题）", "难度理由": "medium 锚点——最简等量关系作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——essence'找到两个相等的量'的演示载体：总量与部分之和相等"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪句话描述的是两个相等的量？（　）\nA. 小明比小红高 5 厘米\nB. 全班人数 = 男生人数 + 女生人数\nC. 汽车每小时行 60 千米\nD. 一本书有 120 页",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["两个相等的量用等号连接，左右两边表示同一个东西", "B 的左边（全班人数）和右边（男生人数 + 女生人数）相等，是等量关系", "A、C、D 只是一句话描述，没有'两个量相等'", "选 B"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'两个相等的量'（等量关系的基本形态）", "难度理由": "easy——关系识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断哪句是等量关系而非直接算", "错因陷阱": "把'小明比小红高 5 厘米'当等量关系（只盯数字不看关系）", "教学角色": "L1 识别脚手架——等量关系形态的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "果园有桃树 40 棵，梨树比桃树少 10 棵。下面哪个等量关系正确？（　）\nA. 梨树 = 桃树 − 10\nB. 梨树 = 桃树 + 10\nC. 桃树 = 梨树 − 10\nD. 梨树 = 桃树 × 10",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'梨树比桃树少 10 棵'：梨树比桃树少，所以梨树 = 桃树 − 10", "40 − 10 = 30，梨树 30 棵", "选 A（B 把'少'读成'多'，C 方向反了，D 是倍关系）"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'比…少'关系的方向识别", "难度理由": "easy——关系方向判断，无计算", "认知阶梯定位": "L1 识别正宗实现——多/少方向判断", "错因陷阱": "把'少 10'当'多 10'（B）、关系找反（C）——'把多/少/倍关系写反'错因", "教学角色": "L1 识别脚手架——多/少方向的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "妈妈买水果花了 25 元，买菜花了 18 元。用'总量 = 部分 + 部分'写出这次买东西的等量关系。",
            "expected_answer": "总花费 = 买水果的钱 + 买菜的钱，即 总花费 = 25 + 18",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["总量：这次买东西的总花费", "部分一：买水果 25 元；部分二：买菜 18 元", "等量关系：总花费 = 买水果的钱 + 买菜的钱 = 25 + 18"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'总量 = 部分 + 部分'的直接套用（漏总量错因布点）", "难度理由": "easy——套用锚点模型换情境", "认知阶梯定位": "L2 套用——总量关系标准应用", "错因陷阱": "漏掉总量（只写 25 + 18，不说明等于什么）", "教学角色": "套用变式——'漏总量'错因布点"}
        },
        {
            "slot": "B2-I1",
            "prompt": "图书角有故事书 45 本，是科技书的 3 倍。写出等量关系，并列出科技书本数的算式（不用算答案）。",
            "expected_answer": "等量关系：故事书 = 科技书 × 3（45 = 科技书 × 3）；列式：科技书 = 45 ÷ 3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'故事书是科技书的 3 倍'：故事书 = 科技书 × 3", "把 45 代入：45 = 科技书 × 3", "求科技书：科技书 = 45 ÷ 3"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "倍关系的等量关系与除法列式（份数模型）", "难度理由": "medium——倍关系转化 + 求一份的列式两步", "认知阶梯定位": "L2 套用——倍关系标准应用", "错因陷阱": "倍份关系错（写成 科技书 = 45 × 3）、漏总量（45 不放进关系）", "教学角色": "倍关系套用——'倍份关系错'错因布点"}
        },
        {
            "slot": "B2-I2",
            "prompt": "爸爸今年 36 岁，比小明年龄的 2 倍还大 6 岁。设小明 x 岁，下面哪个等量关系正确？（　）\nA. 2x + 6 = 36\nB. 2x − 6 = 36\nC. 2x = 36\nD. x + 6 = 36",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'比小明年龄的 2 倍还大 6 岁'：爸爸的年龄 = 小明年龄的 2 倍 + 6", "小明 x 岁，小明年龄的 2 倍是 2x", "等量关系：2x + 6 = 36，选 A"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'倍 + 多/少'复合关系的方向（设未知量预告）", "难度理由": "medium——倍与多少复合，方向易反", "认知阶梯定位": "L3 变式——倍关系加'还大 6'干扰", "错因陷阱": "把'大 6 岁'读成 −6（B，关系找反）、漏掉 6（C）", "教学角色": "复合关系变式——'把多/少/倍关系写反'错因布点 + x 设未知量预告"}
        },
        {
            "slot": "B3-I0",
            "prompt": "把 48 块糖平均分给 6 个小朋友。下面哪个等量关系正确？（　）\nA. 每人块数 × 6 = 48\nB. 每人块数 + 6 = 48\nC. 每人块数 = 48 − 6\nD. 每人块数 = 48 × 6",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["平均分：每人块数 × 人数 = 总数（每份数 × 份数 = 总数）", "每人块数 × 6 = 48", "选 A（B、C 是加减关系，D 方向反了）"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "份数模型的等量关系（每份数 × 份数 = 总数）", "难度理由": "medium——从加减模型切到乘除份数模型", "认知阶梯定位": "L3 变式——换模型（份数/平均分）", "错因陷阱": "倍份关系错（用加减处理平均分）、漏总数（48 不进关系）", "教学角色": "份数模型变式——'倍份关系错''漏总量'双错因布点"}
        },
        {
            "slot": "B3-I1",
            "prompt": "画线段图理解：乙筐 x 千克，甲筐是乙筐的 2 倍，两筐苹果共 90 千克。写出等量关系并列式。",
            "expected_answer": "等量关系：甲筐 + 乙筐 = 90，且甲筐 = 乙筐 × 2；列式：2x + x = 90（或 90 = 2x + x）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "线段图",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["线段图：乙筐画 1 段（x 千克），甲筐画 2 段（2x 千克）", "两个关系：甲筐 + 乙筐 = 90；甲筐 = 乙筐 × 2", "列式：2x + x = 90（两个部分的量相加等于总量）"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "和倍问题的双关系（总量 + 倍，线段图辅助）", "难度理由": "hard——要同时找到'总量'和'倍'两个关系再合并列式，任缺一个即错", "认知阶梯定位": "L4 迁移——线段图工具 × 倍份关系，M-PRE-EQUATION-BASIC 列方程前置", "错因陷阱": "漏总量（只写 2x）、漏倍关系（只写 x + 90）、把 2 倍当 x + 2", "教学角色": "判定层 transfer 证据来源（C3 双角色）——线段图+和倍综合"}
        },
        {
            "slot": "B3-I2",
            "prompt": "班级图书角原来有 x 本图书，上午借出 15 本，下午又借出 8 本，还剩下 27 本。写出等量关系并列式。",
            "expected_answer": "等量关系：原来的 − 借出的 = 剩下的；列式：x − 15 − 8 = 27（或 x − (15 + 8) = 27）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["关系：原来的本数 − 借出的本数 = 剩下的本数", "借出的本数 = 上午 15 + 下午 8", "列式：x − 15 − 8 = 27"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "减法型（差）等量关系 + 两段借出合并", "难度理由": "hard——减方向易反（关系找反）、两段借出要先合并，是'总量=部分+部分'的逆向变式", "认知阶梯定位": "L4 迁移——差关系 × 部分合并，M-PRE-EQUATION-BASIC 列方程前置", "错因陷阱": "关系找反（写成 15 + 8 − x = 27）、漏掉一段借出", "教学角色": "判定层 transfer 证据来源（C3 双角色）——差关系列式"}
        },
        {
            "slot": "B4-I0",
            "prompt": "小明买一支笔和一块橡皮共花 4 元，笔 2.5 元。下面哪个等量关系正确？（　）\nA. 笔的钱 + 橡皮的钱 = 4\nB. 笔的钱 = 橡皮的钱 + 4\nC. 笔的钱 × 橡皮的钱 = 4\nD. 橡皮的钱 − 笔的钱 = 4",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["共花 4 元：总花费 = 笔的钱 + 橡皮的钱", "等量关系：笔的钱 + 橡皮的钱 = 4", "选 A（B、C、D 把总量位置放错或改成乘/减）"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "总量=部分+部分的检测（含小数情境）", "难度理由": "easy 检测——锚点模型直接辨认", "认知阶梯定位": "L2 检测", "错因陷阱": "漏总量（总量 4 不放关系里）、把部分当总量（B/D）", "教学角色": "掌握档快速检测——'漏总量'错因检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "学校合唱队有男生 12 人，女生人数比男生的 2 倍少 5 人。写出女生人数的等量关系，并列出算式。",
            "expected_answer": "等量关系：女生人数 = 男生人数的 2 倍 − 5；列式：12 × 2 − 5",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["'比男生的 2 倍少 5 人'：女生 = 男生的 2 倍 − 5", "男生 12 人：女生 = 12 × 2 − 5", "算式：12 × 2 − 5"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "'倍 − 少'复合关系的检测（列式）", "难度理由": "hard——倍与少复合、方向与列式都要自己完成", "认知阶梯定位": "L3 检测 hard——复合关系综合检测", "错因陷阱": "把'少 5'当'多 5'（12 × 2 + 5，关系找反）", "教学角色": "判定层 hard 证据来源——复合关系列式取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "一辆汽车 3 小时行驶 240 千米。用表格整理：路程 240 千米、时间 3 小时、速度（　）。根据'路程 = 速度 × 时间'写出等量关系，并列出求速度的算式。",
            "expected_answer": "等量关系：路程 = 速度 × 时间，即 240 = 速度 × 3；列式：速度 = 240 ÷ 3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "表格整理条件",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["表格整理：路程 240 千米、时间 3 小时、速度待求", "基本关系：路程 = 速度 × 时间", "240 = 速度 × 3，求速度：速度 = 240 ÷ 3"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "路程=速度×时间基本关系（表格整理条件）", "难度理由": "medium——换一个基本关系模型（非加和），表格整理辅助", "认知阶梯定位": "L3 复测——防'只会总量=部分+部分'的模型窄化", "错因陷阱": "倍份关系错（速度 = 240 × 3）、把时间当速度", "教学角色": "复测题——基本关系模型迁移复测（表格整理条件 seed）"}
        },
        {
            "slot": "B5-I0",
            "prompt": "桃树比梨树多 24 棵，桃树的棵数是梨树的 3 倍。设梨树 x 棵，写出等量关系并列式。",
            "expected_answer": "等量关系：桃树 − 梨树 = 24，且桃树 = 梨树 × 3；列式：3x − x = 24",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["两个关系：桃树 − 梨树 = 24（差）；桃树 = 梨树 × 3（倍）", "梨树 x 棵，桃树 3x 棵", "列式：3x − x = 24"],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "差倍问题的双关系复测（差 + 倍合并）", "难度理由": "hard——差与倍两个关系都要找对再合并，差方向一错全错", "认知阶梯定位": "L4 复测——和倍/差倍双关系防遗忘复测", "错因陷阱": "关系找反（写 x − 3x）、漏差（只写 3x = 24）", "教学角色": "复测 hard 档——判定层 hard 证据来源，双关系列式复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "题目：'停车场有小汽车 24 辆，货车比小汽车少 6 辆，货车有多少辆？'小刚说：'这题就是 24 − 6。'他这样说漏掉了什么？（　）\nA. 要先说出等量关系'货车 = 小汽车 − 6'，再列式，不能只盯着数字减\nB. 数字不够大\nC. 应该用加法算\nD. 什么都没漏，直接减就是对的",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["列式的依据是等量关系：货车 = 小汽车 − 6", "先写关系再列式，答案才是'会算'而不是'碰对'", "小刚只盯数字 24 − 6，漏掉了'为什么这样列'的关系", "选 A"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'只盯数字不看关系'错因的诊断", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——节点 #1 错因的一键探针", "错因陷阱": "只盯数字不看关系（直接 24 − 6 不写等量关系）", "教学角色": "诊断题——'先写等量关系再列式'习惯的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小红要解决：'一条路长 500 米，已经修了 180 米，还剩多少米没修？'她设 x = 已修的长度，写等量关系 x + 180 = 500。她设对了吗？应该怎么设？",
            "expected_answer": "设错了。要求的是'还剩多少米'，应设 x = 还没修的长度；等量关系：已修 180 + 没修 x = 总长 500，即 x = 500 − 180",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据文字找等量关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["题目问'还剩多少米'，未知量应是没修的长度", "小红设 x = 已修长度，把已知的 180 当未知，设错了", "正确：设 x = 没修的长度，等量关系 180 + x = 500，x = 500 − 180"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'未知量设错'错因的诊断", "难度理由": "medium——要指出设错并重新设", "认知阶梯定位": "L2 诊断——'未知量设错'的直接探针", "错因陷阱": "把已知量当未知量设（设 x = 已修长度）", "教学角色": "诊断题——设未知量意识的一键探针（M-PRE-EQUATION-BASIC 设列前置）"}
        },
    ],
    # ===== M-PRE-EQUATION-BASIC 小学简易方程（解方程向：2 verified + 13 unverifiable） =====
    # 节点契约：essence="方程是用等号把未知数和已知条件连接起来"；
    # seed=一步方程/两步方程/根据等量关系列方程；common_mistakes=等号两边不平衡/移项凭感觉/解完不检验；
    # diagnostic_probes=2道一步、2道两步、1道列方程；mastery=基础方程正确率≥85%、能代回检验；
    # prereq=M-PRE-QUANTITY-RELATION、M-PRE-ORDER-OPS；unlock=M-G7-EQUALITY-PROP、M-G7-EQ-SOLVE、M-G7-EQUATION-CONCEPT。
    # authoring 原则（照 EQ-SOLVE 样板）：题干内嵌"计算：X"的纯数值题 verified（答案机算真对）；
    # 解方程写步骤/识别/诊断题 unverifiable；教学强调等式性质（天平模型），不以移项口诀为先；
    # 错因逐一布点："等号两边不平衡"（B5-I1 诊断）、"移项变号忘/凭感觉"（B5-I2 诊断）、"解完不检验"（B4-I2 检验诊断）；
    # "设列不分/未知量"（B3-I1/B5-I0 列方程应用，QUANTITY-RELATION 前置运用）；
    # 迁移布点：列方程解简单应用（B3-I1/B5-I0）、除法型两步方程（B3-I2）、小数方程（B3-I0，DECIMAL 前置运用）。

    "M-PRE-EQUATION-BASIC": [
        {
            "slot": "B1-I0",
            "prompt": "解方程：x + 5 = 12，写出每一步。（提示：用天平想——要让 x 单独留在一边，两边必须同时做相同的操作）",
            "expected_answer": "x = 7（两边同时减去 5，得 x = 7；检验：7 + 5 = 12 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["目标：把 x 单独留下", "天平两边同时减去 5：x + 5 − 5 = 12 − 5", "x = 7；检验：7 + 5 = 12 ✓"],
            "error_tags": ["process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "一步方程 x + a = b（等式性质 1，天平模型）", "难度理由": "medium 锚点——最简方程作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱）", "教学角色": "讲本质用——essence'用等号把未知数和已知条件连接'的演示载体：两边同操作保持平衡"}
        },
        {
            "slot": "B1-I1",
            "prompt": "解方程 x − 7 = 9，第一步应两边同时做什么？（　）\nA. 同时加 7\nB. 同时减 7\nC. 同时乘 7\nD. 同时除以 7",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["左边是 x − 7，要消去 −7", "两边同时加 7：x − 7 + 7 = 9 + 7", "x = 16；选 A"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "x − a = b 型第一步的规则识别（等式性质 1）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断两边同操作的方向", "错因陷阱": "减 7 就两边减 7（B，把'消去 −7'想反）、乘除乱用（C/D）", "教学角色": "L1 识别脚手架——'两边同操作'方向的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "解方程 4x = 20，要把 x 的系数化为 1，两边应同时做什么？（　）\nA. 同时除以 4\nB. 同时减 4\nC. 同时乘 4\nD. 同时加 4",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["左边是 4 个 x，要变成 1 个 x", "两边同时除以 4：4x ÷ 4 = 20 ÷ 4", "x = 5；选 A"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "ax = b 型系数化为 1 的规则识别（等式性质 2）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现——系数化 1 方向判断", "错因陷阱": "同时减 4（把除法当减法）、乘 4（方向反）", "教学角色": "L1 识别脚手架——'系数化为 1'方向的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "解方程 x + 8 = 20：两边同时减 8。计算：20 − 8",
            "expected_answer": "12",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["两边同时减 8：x + 8 − 8 = 20 − 8", "x = 20 − 8", "x = 12"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "x + a = b 的数值环节（等式性质 1 应用）", "难度理由": "easy——直接减法计算", "认知阶梯定位": "L2 套用——等式性质与计算衔接", "错因陷阱": "减错（20 − 8 = 14 之类）、两边不同操作", "教学角色": "套用变式——等式性质落地为数值的取证题（verified 机算真对）"}
        },
        {
            "slot": "B2-I1",
            "prompt": "解方程：4x = 28，写出步骤并检验。",
            "expected_answer": "x = 7（两边同时除以 4，得 x = 7；检验：4 × 7 = 28 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两边同时除以 4：4x ÷ 4 = 28 ÷ 4", "x = 7", "检验：4 × 7 = 28 ✓"],
            "error_tags": ["process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "ax = b 型解方程（含检验步骤）", "难度理由": "medium——除系数 + 主动检验两步", "认知阶梯定位": "L2 套用——乘系数方程的完整求解", "错因陷阱": "同时减 4（等式性质用错）、解完不检验", "教学角色": "乘系数标准变式——'解完不检验'错因布点"}
        },
        {
            "slot": "B2-I2",
            "prompt": "解方程：2x + 4 = 14（写出两步）",
            "expected_answer": "x = 5（两边同时减 4 得 2x = 10，再两边同时除以 2 得 x = 5；检验：2 × 5 + 4 = 14 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["第一步：两边同时减 4：2x = 10", "第二步：两边同时除以 2：x = 5", "检验：2 × 5 + 4 = 14 ✓"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两步方程 ax + b = c（先消常数再化系数）", "难度理由": "medium——两步顺序是关键：先消常数再化系数", "认知阶梯定位": "L3 变式——从一步到两步", "错因陷阱": "先除后减（顺序错）、只改一边（等号两边不平衡）", "教学角色": "两步方程标准变式——两步顺序错因布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "解方程：x − 2.5 = 4.5（写出步骤）",
            "expected_answer": "x = 7（两边同时加 2.5，x = 4.5 + 2.5 = 7；检验：7 − 2.5 = 4.5 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两边同时加 2.5：x − 2.5 + 2.5 = 4.5 + 2.5", "x = 7", "检验：7 − 2.5 = 4.5 ✓"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "小数方程 x − a = b（迁移小数加减）", "难度理由": "medium——小数加法计算与等式性质衔接", "认知阶梯定位": "L3 变式——换数字形式（小数）", "错因陷阱": "减 2.5 方向错（两边同时减）、小数加减算错", "教学角色": "小数变式——M-PRE-DECIMAL-OPS 前置运用"}
        },
        {
            "slot": "B3-I1",
            "prompt": "妈妈买了 3 盒牛奶和一袋面包，共花 21 元，面包 6 元。设每盒牛奶 x 元，列方程并求解。",
            "expected_answer": "3x + 6 = 21；两边同时减 6 得 3x = 15，再两边同时除以 3 得 x = 5。答：每盒牛奶 5 元。检验：3 × 5 + 6 = 21 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据等量关系列方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["找等量关系：3 盒牛奶的钱 + 面包钱 = 21", "列方程：3x + 6 = 21", "解：两边同时减 6 得 3x = 15，再同时除以 3 得 x = 5", "检验：3 × 5 + 6 = 21 ✓"],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "根据等量关系列方程并求解（设列一体）", "难度理由": "hard——列方程（QUANTITY-RELATION 前置）× 两步求解双知识叠加", "认知阶梯定位": "L4 迁移——等量关系列方程，M-PRE-QUANTITY-RELATION 前置运用", "错因陷阱": "设列不分（设了 x 却不写 3x + 6 = 21）、漏掉牛奶数量 3", "教学角色": "判定层 transfer 证据来源（C3 双角色）——设列一体迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "解方程：x ÷ 2 + 3 = 10（写出两步）",
            "expected_answer": "x = 14（两边同时减 3 得 x ÷ 2 = 7，再两边同时乘 2 得 x = 14；检验：14 ÷ 2 + 3 = 10 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["第一步：两边同时减 3：x ÷ 2 = 7", "第二步：两边同时乘 2：x = 14", "检验：14 ÷ 2 + 3 = 10 ✓"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "除法型两步方程（乘回 x 本身）", "难度理由": "hard——'÷2 用乘 2 消去'方向易反（写成又 ÷2 或 ×2 方向错），且两步叠加", "认知阶梯定位": "L4 迁移——等式性质 2 在除法型方程的运用", "错因陷阱": "最后一步乘/除方向错（x ÷ 2 = 7 后写成 x = 7 ÷ 2）", "教学角色": "判定层 transfer 证据来源——除法型方程迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "解方程 x − 6 = 9：两边同时加 6。计算：9 + 6",
            "expected_answer": "15",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["两边同时加 6：x − 6 + 6 = 9 + 6", "x = 9 + 6", "x = 15"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "x − a = b 的数值环节（等式性质 1 应用）", "难度理由": "easy——直接加法计算", "认知阶梯定位": "L2 检测——减型一步方程数值掌握", "错因陷阱": "加错或方向反（9 − 6）", "教学角色": "检测题——减型方程数值环节取证（verified 机算真对）"}
        },
        {
            "slot": "B4-I1",
            "prompt": "解方程：4x − 6 = 14（写出两步并检验）",
            "expected_answer": "x = 5（两边同时加 6 得 4x = 20，再两边同时除以 4 得 x = 5；检验：4 × 5 − 6 = 14 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "两步方程",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["第一步：两边同时加 6：4x = 20", "第二步：两边同时除以 4：x = 5", "检验：4 × 5 − 6 = 14 ✓"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "两步方程 ax − b = c 的综合检测（乘减型）", "难度理由": "hard——先加后除两步 + 主动检验，'先消常数'顺序一错全错", "认知阶梯定位": "L3 检测 hard——两步方程综合检测", "错因陷阱": "先除后加（顺序错）、只改一边（等号两边不平衡）", "教学角色": "判定层 hard 证据来源——两步方程综合取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "小明解方程 x + 9 = 16 得到 x = 25。请检验他的解是否正确。",
            "expected_answer": "把 x = 25 代入左边：25 + 9 = 34；右边是 16。左边 ≠ 右边，所以 x = 25 不是方程的解。正确的是 x = 7（16 − 9）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["检验方法：把解代入方程两边，看左边是否等于右边", "x = 25：左边 25 + 9 = 34 ≠ 16，解错了", "正确：x = 16 − 9 = 7；检验：7 + 9 = 16 ✓"],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "代回检验技能复测（'解完不检验'错因）", "难度理由": "medium——要代入检验并判断对错", "认知阶梯定位": "L3 复测——检验意识确认真实性", "错因陷阱": "不检验直接信 25、代入时算错", "教学角色": "复测题——代回检验防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "学校合唱队有男生 12 人，比女生的 2 倍少 6 人。设女生 x 人，列方程并求解。",
            "expected_answer": "2x − 6 = 12；两边同时加 6 得 2x = 18，再两边同时除以 2 得 x = 9。答：女生 9 人。检验：2 × 9 − 6 = 12 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "根据等量关系列方程",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["等量关系：女生的 2 倍 − 6 = 男生 12 人", "列方程：2x − 6 = 12", "解：两边同时加 6 得 2x = 18，再同时除以 2 得 x = 9", "检验：2 × 9 − 6 = 12 ✓"],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "倍少复合列方程复测（设列 + 两步解）", "难度理由": "hard——关系方向（−6 还是 +6）× 设列 × 两步求解三处可错", "认知阶梯定位": "L4 复测——列方程最高阶复测，M-PRE-QUANTITY-RELATION 前置运用", "错因陷阱": "把'少 6'列成 +6（关系找反）、设列不分", "教学角色": "复测 hard 档——判定层 hard 证据来源，列方程综合复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小丽解方程 x + 4 = 10，她写：x + 4 − 4 = 10，得 x = 10。她错在哪里？（　）\nA. 只给左边减了 4，右边没有减，等号两边不平衡\nB. 应该两边同时加 4\nC. 她没错\nD. 应该先算 10 − 4 再写",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["等式性质：两边必须同时做相同的操作", "小丽只给左边减 4，右边还是 10", "正确：x + 4 − 4 = 10 − 4，x = 6；选 A"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'等号两边不平衡'错因的诊断（只改一边）", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——节点 #1 错因的一键探针", "错因陷阱": "只给一边做操作（等号两边不平衡）", "教学角色": "诊断题——'两边同操作'意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小明解方程 x − 5 = 9，他直接写：x = 9 − 5，得 x = 4。他这样做错在哪里？正确的是什么？",
            "expected_answer": "错在'移项凭感觉'：−5 移到右边要变成 +5（等价于两边同时加 5）。正确：两边同时加 5，x = 9 + 5 = 14；检验：14 − 5 = 9 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "一步方程",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["左边是 x − 5，要消去 −5 应两边同时加 5（不是把 −5 直接搬过去）", "正确：x − 5 + 5 = 9 + 5，x = 14", "检验：14 − 5 = 9 ✓；小明得 4 是把移项变号忘了"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'移项凭感觉/变号忘'错因的诊断（以等式性质纠正）", "难度理由": "medium——要指出具体错误并用等式性质重做", "认知阶梯定位": "L2 诊断——'移项变号忘'的直接探针", "错因陷阱": "−5 移过去不变号（x = 9 − 5）", "教学角色": "诊断题——以'两边同操作'纠正移项口诀的探针（教学策略：不先讲移项口诀）"}
        },
    ],
    # ===== M-PRE-NUMBER-SENSE 数感与估算（概念+估算向：15 unverifiable；P0 全图源头节点） =====
    # 节点契约：essence="先判断答案大概范围，防止算出离谱结果"；
    # seed=估算乘除结果/判断小数点位置/比较结果大小；common_mistakes=只机械计算不估算/小数点位置离谱也不检查；
    # diagnostic_probes=给3道估算题要求先说范围再计算/给1道明显错误结果判断是否合理；
    # mastery=能在计算前说出结果大致范围/能主动用估算发现小数点或符号错误；
    # prereq=无；unlock=M-PRE-ORDER-OPS、M-PRE-INTEGER-OPS、M-PRE-DECIMAL-OPS、M-PRE-FRACTION-MEANING、
    # M-PRE-ANGLE-BASIC、M-G7-POS-NEG、M-G7-SCI-NOTATION-APPROX 等下游节点。
    # authoring 原则（照 POS-NEG/QUANTITY-RELATION 概念向样板）：全部 unverifiable（估算/判断/比较型题，
    # 题干不以"计算："开头避免 sympy 误提取；纯数值估算与判断均不可机算）；
    # L1 真识别（何时用估算/结果是否离谱/小数点位置是否合理）；hard 真难（小数×面积×单价两步估算、
    # 数量级与单位混合、四项逐一检查小数点）；
    # 错因逐一布点："估算当精确算"（B5-I1 诊断）、"估错数量级"（B5-I2 诊断）、"不合理估计"（B3-I2 数量级）、
    # "小数点位置离谱也不检查"（B1-I2/B4-I1）、"只机械计算不估算"（B1-I1/B5-I1）；
    # 迁移布点：购物与测量应用（B3-I1 小数长宽×面积×单价、B4-I2/B5-I0 购物两步，M-PRE-DECIMAL-OPS 前置运用）、
    # 数量级×单位常识（B3-I2，长度/重量/时间单位）。

    "M-PRE-NUMBER-SENSE": [
        {
            "slot": "B1-I0",
            "prompt": "估算：48 × 21 的结果大约是多少？（先说出估算的方法，再写结果）",
            "expected_answer": "约 1000（把 48 估成 50，21 估成 20，50 × 20 = 1000）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算乘除结果",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["估算先找大约的数：48 接近 50，21 接近 20", "用整十数算：50 × 20 = 1000", "所以 48 × 21 大约等于 1000（实际是 1008，很接近）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两位数乘法的估算（四舍五入到整十再算，'估算乘除结果'）", "难度理由": "medium 锚点——演示'先估范围再算'的本质步骤", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；要求写出估算方法防'碰对'）", "教学角色": "讲本质用——essence'先判断答案大概范围'的演示载体：估整十→算范围→对照精确值"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪种情况适合用估算？（　）\nA. 收银员结账时计算要找多少钱\nB. 小明带 100 元去买 38 元、26 元、19 元的三样东西，判断钱够不够\nC. 数学考试算 25 × 4 的准确答案\nD. 量体温判断有没有发烧",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "合理估计",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["估算的价值是快速判断'够不够/大约多少'", "A、C 需要精确结果，不能估算", "B 只要判断 100 元够不够，用估算（40 + 30 + 20 = 90）就够了，选 B", "D 是测量判断，不是估算"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'什么时候用估算'（估算 vs 精确计算的场景判断）", "难度理由": "easy——场景识别，无计算", "认知阶梯定位": "L1 识别正宗实现——判断考点/场景而非直接算", "错因陷阱": "把'找零/考试算分'当估算场景（不会分辨何时该估）", "教学角色": "L1 识别脚手架——估算适用场景的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "小明算 3.2 × 1.7 得到 54.4。不用笔算，你能看出这个结果有问题吗？下面说法正确的是（　）\nA. 3.2 和 1.7 都不到 4，结果应该比 16 小，54.4 大得离谱\nB. 3.2 × 1.7 大约就是 54.4\nC. 两个小数相乘结果肯定大于 50\nD. 无法判断",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断小数点位置",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先估范围：3.2 和 1.7 都小于 4，乘积一定小于 4 × 4 = 16", "54.4 比 16 大得多，小数点位置明显放错", "正确结果约 5.44，选 A（B/C 是'小数点位置离谱也不检查'）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "用估算发现小数点位置错误（'判断小数点位置'，mastery'主动用估算发现小数点错误'取证）", "难度理由": "easy——先估上限再对照，单步判断", "认知阶梯定位": "L1 识别——'小数点位置离谱也不检查'错因的第一道判断", "错因陷阱": "看到结果就信（B/C——'小数点位置离谱也不检查'）", "教学角色": "L1 识别脚手架——估算校验意识的第一道探针"}
        },
        {
            "slot": "B2-I0",
            "prompt": "估算：398 × 21 的结果大约是多少？",
            "expected_answer": "约 8000（398 估成 400，21 估成 20，400 × 20 = 8000）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算乘除结果",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["398 接近整百数 400", "21 接近整十数 20", "400 × 20 = 8000，所以 398 × 21 ≈ 8000"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "接近整百数乘法的估算（'估算乘除结果'直接套用）", "难度理由": "easy——三位估整百、两位估整十，单层套用", "认知阶梯定位": "L2 套用——锚点模型换数字", "错因陷阱": "估错数量级（把 21 估成 2 得 800——'估错数量级'）", "教学角色": "L2 套用脚手架——'先估整十整百再算'标准应用"}
        },
        {
            "slot": "B2-I1",
            "prompt": "妈妈带 200 元去超市，要买 98 元的大米、67 元的食用油和 45 元的牛奶。估算一下：钱够不够？",
            "expected_answer": "不够。估算：98 ≈ 100，67 ≈ 70，45 ≈ 50，100 + 70 + 50 = 220，220 > 200，所以 200 元不够",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算应用",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["判断'够不够'要往大估（估大）：98 ≈ 100、67 ≈ 70、45 ≈ 50", "100 + 70 + 50 = 220 元", "220 > 200，往大估都不够（实际 98 + 67 + 45 = 210 也不够）→ 200 元不够"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "购物'钱够不够'的估大判断（'估算应用'，往大估保证安全）", "难度理由": "medium——'往大估'策略 + 三项求和判断", "认知阶梯定位": "L2 套用——估算在购物中的应用", "错因陷阱": "往小估（98→90、67→60、45→40，得 190 判断'够'——估错方向导致判断反）、精确算（'估算当精确算'）", "教学角色": "估算应用套用——'估大估小策略'的标准示范"}
        },
        {
            "slot": "B2-I2",
            "prompt": "0.48 × 0.3 的积，小数点应该点在哪里？（　）\nA. 0.144\nB. 1.44\nC. 14.4\nD. 144",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断小数点位置",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先算整数的积：48 × 3 = 144", "0.48 有两位小数、0.3 有一位小数，共三位小数", "144 向左数三位 → 0.144，选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "小数乘法的'数小数位数定小数点'（'判断小数点位置'，小数点移位规则）", "难度理由": "medium——整数积 + 数位计数两步，'小数点位置'错因高发点", "认知阶梯定位": "L3 变式——从'估算校验'到'精确定位规则'", "错因陷阱": "数错小数位（0.48 有一位/0.3 有两位）、积的位数不够忘补 0", "教学角色": "判断小数点位置标准变式——'数位计数'规则取证"}
        },
        {
            "slot": "B3-I0",
            "prompt": "不用算出准确答案，估一估：下面哪个算式的结果最大？（　）\nA. 298 × 5\nB. 305 × 4\nC. 199 × 8\nD. 501 × 3",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "比较结果大小",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["分别估到整百：298≈300、305≈300、199≈200、501≈500", "A ≈ 300 × 5 = 1500，B ≈ 300 × 4 = 1200，C ≈ 200 × 8 = 1600，D ≈ 500 × 3 = 1500", "最大的是 C（约 1600）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用估算比较结果大小（'比较结果大小'，估到整百再比）", "难度理由": "medium——四个式子各自估算再比较，A/D 相近需仔细", "认知阶梯定位": "L3 变式——从'估一个'到'比多个'", "错因陷阱": "精确硬算（'估算当精确算'）、估错整百数（298 估成 200）", "教学角色": "估算比较变式——'基准比较'思维训练"}
        },
        {
            "slot": "B3-I1",
            "prompt": "要给一间长 6.2 米、宽 4.8 米的房间铺地板，每平方米地板约 80 元。估算一下大约需要多少钱？（写出估算过程）",
            "expected_answer": "约 2400 元。估算：6.2 ≈ 6，4.8 ≈ 5，面积约 6 × 5 = 30 平方米；30 × 80 = 2400 元",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算应用",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先估面积：长 6.2 ≈ 6 米，宽 4.8 ≈ 5 米，面积约 6 × 5 = 30 平方米", "再估总价：每平方米约 80 元，30 × 80 = 2400 元", "答：大约需要 2400 元（实际约 6.2 × 4.8 × 80 = 2380.8 元，很接近）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "测量（面积）× 单价的两步估算迁移（'估算应用'×'判断小数点位置'，小数估算）", "难度理由": "hard——先估小数长宽再算面积再乘单价，两步估算环环相扣，任一步数量级错即全错", "认知阶梯定位": "L4 迁移——估算 × 小数（M-PRE-DECIMAL-OPS 前置运用）× 测量面积", "错因陷阱": "面积估成 300 平方米（6 × 5 小数点位置多看一位——'估错数量级'）、漏乘单价", "教学角色": "判定层 transfer 证据来源（C3 双角色）——估算在测量购物中的综合迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "下面哪个说法合理？（　）\nA. 小明身高约 3 米\nB. 一辆小汽车每小时约行 80 千米\nC. 一个鸡蛋约重 500 千克\nD. 一支铅笔长约 2 米",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "合理估计",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["用生活常识判断数量级：3 米比一层楼还高，不是小学生的身高（A 错）", "汽车时速约 60–120 千米，80 千米合理（B 对）", "500 千克是一个人的体重，鸡蛋约 50–60 克（C 错）", "2 米比门还高，铅笔约 15–20 厘米（D 错），选 B"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "数量级与单位的合理估计（'合理估计'，长度/重量单位常识迁移）", "难度理由": "hard——四项逐一用单位常识判断数量级，A/C/D 都是'离谱一个数量级'的经典错误", "认知阶梯定位": "L4 迁移——估算 × 单位常识（测量单位前置知识）", "错因陷阱": "没有数量级感（认为 3 米身高/500 千克鸡蛋合理——'不合理估计'错因）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——数量级感的综合取证"}
        },
        {
            "slot": "B4-I0",
            "prompt": "估算：198 ÷ 5 的结果大约是多少？",
            "expected_answer": "约 40（198 接近 200，200 ÷ 5 = 40）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算乘除结果",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["198 接近整百数 200", "200 ÷ 5 = 40", "所以 198 ÷ 5 ≈ 40（实际 39.6，很接近）"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "除法估算检测（'估算乘除结果'，防'会背不会用'）", "难度理由": "easy 检测——单层估整百再除", "认知阶梯定位": "L2 检测", "错因陷阱": "把 198 估成 100（得 20——'估错数量级'）", "教学角色": "掌握档快速检测——B1-I0 锚点的除法同型检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "下面哪个算式的结果写错了？（　）\nA. 2.5 × 4 = 10\nB. 0.6 × 0.7 = 0.42\nC. 1.2 × 3 = 3.6\nD. 2.5 × 0.4 = 10",
            "expected_answer": "D",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "判断小数点位置",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["用估算检验每一项：2.5 × 4 ≈ 2 × 4 = 8，接近 10，正确（实际 10）", "0.6 × 0.7：6 × 7 = 42，两位小数 → 0.42，正确", "1.2 × 3 = 3.6，正确", "2.5 × 0.4：25 × 4 = 100，两位小数 → 1.00 = 1，不是 10（D 错，小数点位置放错一位）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "四项逐一用估算/数位检查小数点位置（'判断小数点位置'综合检测）", "难度理由": "hard——四项都要检查，D 的 2.5 × 0.4 是'小数点位置离谱'经典陷阱（约 1 却被写成 10）", "认知阶梯定位": "L3 检测 hard——小数点位置综合取证", "错因陷阱": "看到前三项都对就放过 D（'小数点位置离谱也不检查'）", "教学角色": "判定层 hard 证据来源（C3 双角色）——小数点位置检测"}
        },
        {
            "slot": "B4-I2",
            "prompt": "旅游团有 43 人，每人车费约 18 元。估算一下大约需要准备多少元车费？（写出估算过程）",
            "expected_answer": "约 800 元。估算：43 ≈ 40，18 ≈ 20，40 × 20 = 800 元",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算应用",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["43 接近 40，18 接近 20", "40 × 20 = 800", "所以大约需要 800 元（实际 43 × 18 = 774 元，够用）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "购物'准备多少钱'的估大复测（'估算应用'，防'会背不会用'）", "难度理由": "medium 复测——往大估策略 + 乘除估算两步", "认知阶梯定位": "L3 复测——B2-I1 购物估大的同型复测", "错因陷阱": "往小估（43→40、18→10，得 400——'估错方向'钱不够）、精确算", "教学角色": "防'会背不会用'复测——估大策略购物复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "学校要给 286 名学生每人发 2 本练习本，每本约 1.8 元。估算大约要花多少元？下面哪个估算最合理？（　）\nA. 约 600 元\nB. 约 1200 元\nC. 约 3000 元\nD. 约 100 元",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "估算应用",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["第一步估总本数：286 ≈ 300，每人 2 本，约 300 × 2 = 600 本", "第二步估总价：每本约 1.8 元 ≈ 2 元，600 × 2 = 1200 元", "选 B（A 漏乘单价、C 把每本当 5 元、D 数量级离谱）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "两步购物估算的最高阶复测（'估算应用'，总本数 → 总价）", "难度理由": "hard——两步估算（本数 × 单价）环环相扣，A/C/D 是不同环节的数量级错误", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶估算复测", "错因陷阱": "漏乘单价（A）、估错数量级（D）、只估单价不估本数（C）", "教学角色": "复测 hard 档——判定层 hard 证据来源，两步估算综合取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "题目要求'估算 49 × 21'，小明认认真真算出 49 × 21 = 1029 才写答案。老师说这样不对。老师指的应该是（　）\nA. 估算要的是'大约'的结果：先把 49、21 估成整十数得约 1000 就行，不需要精算——把估算当精确算，既慢又没练到估算\nB. 49 × 21 算错了\nC. 数字太大不能估算\nD. 估算只能用加法",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "估算诊断",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["估算的意义是快速得到大约结果：49 ≈ 50、21 ≈ 20、50 × 20 = 1000", "小明精算 1029，虽然答案对，但没按'估算'要求做", "估算当精确算是把估算题做成笔算题——选 A"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'估算当精确算'错因的诊断（节点 #1 错因的一键探针）", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——'估算当精确算'错因的直接探针", "错因陷阱": "把估算题当笔算题（精算到底）", "教学角色": "诊断题——估算意图识别的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小刚估算 46 × 38，他写：46 约等于 40，38 约等于 30，40 × 30 = 1200，所以结果大约是 1200。他这样估有什么问题？（　）\nA. 两个数都往小估了（46 ≈ 50、38 ≈ 40 更接近），结果应大约 2000，1200 偏小很多\nB. 没问题，估算可以随便往小估\nC. 应该先算 46 × 38 的精确值\nD. 估算结果必须比真实值大",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "估算诊断",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["估算要尽量接近真实值：46 更接近 50，38 更接近 40", "50 × 40 = 2000（真实值 1748，很接近）", "小刚把两个数都往小估，1200 与真实值差太多——'估法不合理/估错数量级'，选 A"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'估错数量级/两个数同向低估'的诊断（四舍五入到更接近的整十数）", "难度理由": "medium——要判断估法是否合理并指出更接近的估法", "认知阶梯定位": "L2 诊断——'估错数量级'错因的直接探针", "错因陷阱": "两个数同向低估（46→40、38→30）导致结果严重偏小", "教学角色": "诊断题——估算取数合理性的一键探针"}
        },
    ],
    # ===== M-PRE-FRACTION-MEANING 分数意义与单位1（概念向：15 unverifiable；P0 分数链源头） =====
    # 节点契约：essence="分数不是两个数叠在一起，而是'把单位1平均分后取几份'"；
    # seed=找单位1/分数表示具体量/分率与数量区分；
    # common_mistakes=单位1找错/把分率当具体数量/看到分数就机械乘除；
    # diagnostic_probes=3道找单位1题/2道判断分数表示分率还是数量；
    # mastery=能圈出单位1/能说清'谁是谁的几分之几'；
    # prereq=M-PRE-NUMBER-SENSE；unlock=M-PRE-FRACTION-OPS、M-PRE-PERCENT、M-G7-EQ-WORD、M-PRE-RATIO-PROP、M-BRIDGE-* 等下游节点。
    # authoring 原则（照 QUANTITY-RELATION 概念向样板）：全部 unverifiable（找单位1/意义判断/分率数量区分，
    # 题干不嵌"计算："避免 sympy 误提取）；
    # L1 真识别（哪句是平均分/单位1是谁）；hard 真难（单位1变化下的比较、分率→数量的两步转换）；
    # 错因逐一布点："单位1找错"（B1-I1/B4-I0/B5-I1 诊断）、"部分/整体关系反"（B5-I2 诊断）、
    # "平均分与不平均分混淆"（B1-I2）、"把分率当具体数量/看到分数就机械乘除"（B2-I1/B2-I2/B4-I1/B5-I0）；
    # 迁移布点：单位1变化的线段图推理（B3-I1）、分率→数量→比较（B3-I2，M-PRE-NUMBER-SENSE 前置运用）、
    # 分率×具体量两步（B4-I2，M-PRE-INTEGER-OPS 前置运用）。

    "M-PRE-FRACTION-MEANING": [
        {
            "slot": "B1-I0",
            "prompt": "把一个蛋糕平均分成 4 份，取其中的 1 份，用分数怎样表示？这个分数表示什么？",
            "expected_answer": "用 1/4 表示；表示把 1 个蛋糕（单位 1）平均分成 4 份，取其中的 1 份",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数的意义",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先确定单位 1：1 个蛋糕", "平均分成 4 份：每份是它的 1/4", "取 1 份：就是 1/4——'分母 4 表示平均分成 4 份，分子 1 表示取 1 份'"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分数的意义（把单位 1 平均分后取几份，'分数的意义'）", "难度理由": "medium 锚点——最简意义题作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；要求说出意义防'会写分数不懂意义'）", "教学角色": "讲本质用——essence'把单位1平均分后取几份'的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "在'3/5 米'这个分数中，把谁看作单位 1？（　）\nA. 1 米\nB. 3 米\nC. 5 米\nD. 3/5 本身",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找单位1",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["带单位的分数表示具体量：3/5 米 = 1 米的 3/5", "单位 1 是 1 米：把 1 米平均分成 5 份，取 3 份", "选 A（B/C 是数量不是单位 1，D 是分数本身）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "分数中单位 1 的识别（'找单位1'，'单位 1 找错'错因的第一道判断）", "难度理由": "easy——单点识别", "认知阶梯定位": "L1 识别正宗实现", "错因陷阱": "选 C（把分母 5 当单位 1）、选 D（把分数本身当单位 1）", "教学角色": "L1 识别脚手架——单位 1 的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "下面哪种情况可以用分数 1/2 表示？（　）\nA. 把一个圆随意切成两块，取其中一块\nB. 把一个圆平均分成 2 份，取其中 1 份\nC. 把一个圆分成大小不同的 3 份，取其中 1 份\nD. 把一个圆分成 2 份，取比较大的那份",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "平均分的意义",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分数必须建立在'平均分'上：每一份要一样大", "B 平均分成 2 份、取 1 份 = 1/2", "A/C/D 都不是平均分（份大小不同），不能用 1/2，选 B"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'平均分'是分数的前提（'平均分的意义'，'平均分与不平均分混淆'错因的正面陷阱）", "难度理由": "easy——单点判断", "认知阶梯定位": "L1 识别——平均分前提的判断", "错因陷阱": "选 A/D（'随意切/取大的'不平均分也算 1/2——'平均分与不平均分混淆'）", "教学角色": "L1 识别脚手架——平均分前提的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "把 1 米长的彩带平均分成 5 段，每段长多少米？",
            "expected_answer": "1/5 米（把 1 米平均分成 5 份，每份是 1 米的 1/5）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分数表示具体量",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["单位 1 是 1 米", "平均分成 5 段，每段是 1 米的 1/5", "1 米的 1/5 = 1/5 米"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "分数表示具体量（带单位，'分数表示具体量'）", "难度理由": "easy——单位 1 为 1 的最简套用", "认知阶梯定位": "L2 套用", "错因陷阱": "写 5/1 米（部分/整体反）、忘带单位", "教学角色": "L2 套用脚手架——'1 米的几分之几'标准应用"}
        },
        {
            "slot": "B2-I1",
            "prompt": "把 6 个苹果平均分成 3 份，每份是这些苹果的几分之几？每份有几个苹果？",
            "expected_answer": "每份是这些苹果的 1/3，有 2 个苹果",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["分率：平均分成 3 份取 1 份 → 1/3（不随总数变）", "数量：6 ÷ 3 = 2 个", "区别：1/3 是分率（占整体的份数），2 个是具体数量"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分率与具体数量的区分（'分率与数量区分'，'把分率当具体数量'错因的对照示范）", "难度理由": "medium——同一情境要同时说出分率和数量，两类量对比", "认知阶梯定位": "L2 套用——分率×数量的双输出", "错因陷阱": "只写 1/3（漏数量）、把 1/3 写成 3 个（把分率当具体数量）", "教学角色": "分率与数量区分标准题——'谁是谁的几分之几'vs'有几个'对照"}
        },
        {
            "slot": "B2-I2",
            "prompt": "一袋糖有 12 块，小明吃了这袋糖的 1/4。他吃了多少块？（　）\nA. 3 块（12 ÷ 4）\nB. 1/4 块\nC. 8 块（12 − 4）\nD. 48 块（12 × 4）",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'这袋糖的 1/4'：把 12 块看作单位 1，平均分成 4 份取 1 份", "12 ÷ 4 = 3 块（也就是 12 × 1/4）", "选 A（B 把分率当数量、C 用减法、D 把 1/4 当 4 倍）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求一个数的几分之几（分率 → 数量，'分率与数量区分'，'看到分数就机械乘除'错因布点）", "难度理由": "medium——分率转化为数量的除法/乘法一步", "认知阶梯定位": "L3 变式——从'认识分率'到'用分率求数量'", "错因陷阱": "选 D（把 1/4 当 4 倍——'部分/整体关系反'）、选 C（把 1/4 当'少 4 块'）", "教学角色": "分率→数量变式——机械乘除错因的定点布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "第一堆糖有 20 块，吃了它的 1/2；第二堆糖有 10 块，也吃了它的 1/2。两次吃掉的糖一样多吗？（　）\nA. 一样多，都吃了 1/2\nB. 不一样多：第一堆吃掉 20 ÷ 2 = 10 块，第二堆吃掉 10 ÷ 2 = 5 块\nC. 一样多，都吃了 2 块\nD. 无法比较",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找单位1",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两次的 1/2 对应的单位 1 不同：第一堆是 20 块，第二堆是 10 块", "第一堆：20 的 1/2 = 10 块；第二堆：10 的 1/2 = 5 块", "10 ≠ 5，不一样多，选 B——同一分数在不同单位 1 下数量不同"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "单位 1 不同 → 同一分数对应不同数量（'找单位1'，mastery'能圈出单位1'的辨析形态）", "难度理由": "medium——同一分数跨单位 1 比较，'单位 1 找错'高发点", "认知阶梯定位": "L3 变式——单位 1 的辨析变式", "错因陷阱": "选 A（只比分数不比单位 1——'单位 1 找错'）、选 C（把 1/2 当 2 块）", "教学角色": "单位 1 辨析变式——'同一分数不同量'的教学载体"}
        },
        {
            "slot": "B3-I1",
            "prompt": "一根绳子，第一次用去全长的 1/3，第二次用去剩下部分的 1/2。（可以画线段图想）第二次用去的是全长的几分之几？两次一共用去全长的几分之几？",
            "expected_answer": "第二次的单位 1 是'剩下的'：剩下全长的 2/3，它的 1/2 = 全长的 1/3；两次共用去全长的 1/3 + 1/3 = 2/3",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "找单位1",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["画线段图：全长 1，第一次用去 1/3，剩下 2/3", "第二次的单位 1 变成'剩下的 2/3'：2/3 的 1/2 = 1/3", "两次共：1/3 + 1/3 = 2/3（还剩全长的 1/3）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "单位 1 变化下的'一个数的几分之几'（'找单位1'×'分率与数量区分'，线段图工具迁移）", "难度理由": "hard——单位 1 中途变化（全长 → 剩下），'单位 1 找错'即全错，还要两步合并", "认知阶梯定位": "L4 迁移——单位 1 概念 × 线段图（M-PRE-NUMBER-SENSE 前置运用）", "错因陷阱": "第二次仍把全长当单位 1（写 1/2——'单位 1 找错'）、漏加第一次（只写 1/3）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——单位 1 变化综合迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一瓶饮料有 500 毫升，小明喝了这瓶饮料的 1/4，小红喝了 150 毫升。谁喝得多？（　）\nA. 小明喝得多（500 ÷ 4 = 125 毫升）\nB. 小红喝得多（125 毫升 < 150 毫升）\nC. 一样多\nD. 无法比较",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["把分率换成数量：小明喝了 500 毫升的 1/4 = 500 ÷ 4 = 125 毫升", "小红喝了 150 毫升", "125 < 150，小红喝得多，选 B"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "分率与数量的跨形式比较（'分率与数量区分'，先换单位再比较）", "难度理由": "hard——分率 × 容量单位先转数量、再与具体量比较，'把分率当具体数量'即全错", "认知阶梯定位": "L4 迁移——分率↔数量转换 × 单位（毫升）常识", "错因陷阱": "直接把 1/4 和 150 比（'把分率当具体数量'）、500 × 4 算错（'部分/整体关系反'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——分率数量跨形式比较"}
        },
        {
            "slot": "B4-I0",
            "prompt": "美术组有 24 人，其中女生占 3/8。'3/8'中把谁看作单位 1？",
            "expected_answer": "美术组总人数（24 人）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "找单位1",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'女生占 3/8'：女生人数是总人数的 3/8", "单位 1 是'美术组总人数'（24 人）", "把 24 人平均分成 8 份，女生占 3 份"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'占…的几分之几'中单位 1 的检测（'找单位1'，防'会背不会用'）", "难度理由": "easy 检测——'占'字后面是单位 1", "认知阶梯定位": "L2 检测", "错因陷阱": "把 24 或 3/8 当单位 1（'单位 1 找错'）", "教学角色": "掌握档快速检测——单位 1 识别检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "甲堆有 12 个苹果，吃了甲的 1/2；乙堆有 21 个苹果，吃了乙的 1/3。哪堆吃掉的多？（　）\nA. 甲堆吃得多（12 ÷ 2 = 6 个）\nB. 乙堆吃得多（21 ÷ 3 = 7 个）\nC. 一样多\nD. 无法比较",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["两堆的单位 1 不同，不能直接比 1/2 和 1/3", "先换数量：甲堆 12 × 1/2 = 6 个，乙堆 21 × 1/3 = 7 个", "7 > 6，乙堆吃得多，选 B（A 只算了甲，直接比分数）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "不同单位 1 下分率×数量的比较检测（'分率与数量区分'综合）", "难度理由": "hard——必须把两个分率都换成数量再比，直接比分数即错", "认知阶梯定位": "L3 检测 hard——分率数量转换综合取证", "错因陷阱": "直接比 1/2 和 1/3 选 A（'单位 1 找错'+'把分率当具体数量'）", "教学角色": "判定层 hard 证据来源——分率数量转换检测"}
        },
        {
            "slot": "B4-I2",
            "prompt": "一本书有 80 页，第一天看了全书的 1/4，第二天看了 20 页。两天一共看了全书的几分之几？",
            "expected_answer": "第一天 80 × 1/4 = 20 页；两天共 20 + 20 = 40 页；40 ÷ 80 = 1/2，看了全书的 1/2",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["第一天页数：80 的 1/4 = 80 ÷ 4 = 20 页", "两天共看：20 + 20 = 40 页", "占全书：40 ÷ 80 = 1/2"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分率→数量→分率的来回转换复测（'分率与数量区分'，防'会背不会用'）", "难度理由": "medium 复测——三步转换（分率→数量→合并→分率）", "认知阶梯定位": "L3 复测——B2-I2 的同型升级复测", "错因陷阱": "把 1/4 当 4 页（'部分/整体关系反'）、40 页忘除 80（漏最后一步）", "教学角色": "防'会背不会用'复测——分率数量来回转换"}
        },
        {
            "slot": "B5-I0",
            "prompt": "甲袋有 24 颗糖，取出甲的 1/4；乙袋有 8 颗糖，取出乙的 3/4。取出的糖一样多吗？",
            "expected_answer": "一样多。甲袋取出 24 × 1/4 = 6 颗；乙袋取出 8 × 3/4 = 6 颗；都是 6 颗",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "单位1与分率",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["甲袋：24 的 1/4 = 24 ÷ 4 = 6 颗", "乙袋：8 的 3/4 = 8 ÷ 4 × 3 = 6 颗", "都是 6 颗，一样多——不同分数 × 不同单位 1 也可能得到相同数量"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "单位 1 × 分率 → 数量 的最高阶复测（'单位1与分率'，分数 × 整数的两步）", "难度理由": "hard——两袋各自换算再比较，乙袋 3/4 要两步（先除再乘），'部分/整体关系反'即全错", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶单位 1 复测", "错因陷阱": "把 3/4 当 3 ÷ 4 个（'把分率当具体数量'）、只算一袋就下结论", "教学角色": "复测 hard 档——判定层 hard 证据来源，单位 1×分率综合复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小红说：'小明吃了一个西瓜的 1/2，小刚也吃了一个西瓜的 1/2，两人吃得一样多。'下面说法正确的是（　）\nA. 不一定一样多——如果两个西瓜不一样大，'一个西瓜的 1/2'对应的单位 1 不同，量就不同\nB. 一定一样多，都是 1/2\nC. 应该比谁吃得快\nD. 1/2 个西瓜就是 1/2 个西瓜，肯定一样",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找单位1",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'1/2 个西瓜'的单位 1 是'那一个西瓜'", "两个西瓜大小不同时，各自 1/2 的数量不同", "所以不能说一定一样多——要先看单位 1（哪个西瓜），选 A"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'单位 1 找错'错因的诊断（分数对应量的单位 1 意识）", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'单位 1 找错'错因的一键探针", "错因陷阱": "只比分数不比单位 1（B/D——'单位 1 找错'）", "教学角色": "诊断题——单位 1 意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小红说：'一袋糖有 20 块，吃了这袋糖的 1/4，就是吃了 20 × 4 = 80 块。'她错在哪里？（　）\nA. 把 1/4 当成了 4 倍——1/4 表示平均分成 4 份取 1 份，应是 20 ÷ 4 = 5 块（或 20 × 1/4）\nB. 20 块不是单位 1\nC. 吃的是 20 的 1/4，她没算错\nD. 应该用加法算",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分率与数量区分",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'吃了 1/4'表示：把 20 块平均分成 4 份，吃 1 份", "20 ÷ 4 = 5 块（等价于 20 × 1/4）", "小红用 20 × 4，把'1/4'当成'4 倍'——部分与整体关系反了，选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'部分/整体关系反'错因的诊断（把 1/4 当 4 倍）", "难度理由": "medium——要指出具体错误并重算", "认知阶梯定位": "L2 诊断——'部分/整体关系反'的直接探针", "错因陷阱": "把 1/4 当成 4 倍（乘 4 而非除以 4——'看到分数就机械乘除'）", "教学角色": "诊断题——分率方向意识的一键探针"}
        },
    ],
    # ===== M-PRE-LETTER-EXPR 用字母表示数（概念+列式向：15 unverifiable；P0 算术→代数桥梁） =====
    # 节点契约：essence="字母是会变化的数，用来表达一类情况"；
    # seed=用字母表示数量/代入求值/省略乘号规范；
    # common_mistakes=把字母当固定未知数/数量关系表达反/省略乘号不规范；
    # diagnostic_probes=3道根据文字写代数式/2道代入求值；mastery=能用字母表达简单数量关系/知道2a表示2×a；
    # prereq=M-PRE-QUANTITY-RELATION；unlock=M-G7-ALG-EXPR、M-G7-MONOMIAL。
    # authoring 原则（照 G7-ALG-EXPR 概念向样板）：全部 unverifiable（文字→代数式/代入求值/书写规范，
    # 题干不嵌"计算："避免 sympy 误提取；代入求值含字母不可机算）；
    # L1 真识别（字母表示一类数/规范写法/含义判断）；hard 真难（括号与运算顺序、图形规律、同一式子多值）；
    # 错因逐一布点："书写规范错（a×3 写 a3）"（B1-I2/B4-I1 诊断）、"字母表示的具体含义丢"（B5-I1 诊断）、
    # "数量关系表达反"（B2-I1/B5-I2 诊断）、"把字母当固定未知数"（B1-I1/B5-I0）；
    # 迁移布点：公式迁移（B3-I1 长方形周长，几何前置运用）、图形规律符号化（B3-I2，M-PRE-QUANTITY-RELATION 前置运用）、
    # 同一式子多值（B5-I0，essence'字母是会变化的数'复测）。

    "M-PRE-LETTER-EXPR": [
        {
            "slot": "B1-I0",
            "prompt": "小明有 a 本书，小红有 b 本书，他们一共有多少本书？",
            "expected_answer": "a + b（本）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["a 和 b 分别表示两人书的数量（字母是会变化的数）", "一共 = 小明的 + 小红的 = a + b", "检验：a = 5、b = 3 时 a + b = 8，合理"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "用字母表示和的数量关系（'用字母表示数量'，essence'字母表达一类情况'的演示）", "难度理由": "medium 锚点——最简加法关系作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；要求写字母式并内嵌检验步示范自查）", "教学角色": "讲本质用——'字母是会变化的数'的演示载体：两个字母表示两个量"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个说法正确？（　）\nA. 字母 a 只能表示 1\nB. 字母 a 可以表示任意一个数，比如 2、3.5、100\nC. 字母不能表示数\nD. 字母 a 只能表示整数",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["字母用来表达'一类情况'，可以取不同的值", "a 可以表示 2、3.5、100 等任意数（包括小数）", "选 B（A/C/D 把字母当成固定未知数）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别'字母表示一类数'（'用字母表示数量'，'把字母当固定未知数'错因的正面陷阱）", "难度理由": "easy——概念识别", "认知阶梯定位": "L1 识别正宗实现——节点 #1 错因的第一道判断", "错因陷阱": "选 A/D（把字母当固定值/只限整数——'把字母当固定未知数'）", "教学角色": "L1 识别脚手架——字母可变性的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "把'b × 7'写成规范形式，正确的是（　）\nA. b7\nB. 7b\nC. b × 7\nD. 7 × b",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "省略乘号规范",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["数字与字母相乘：数字写在前面、乘号省略", "b × 7 → 7b", "选 B（A 把字母写前面、C/D 保留乘号都不规范）"],
            "error_tags": ["process_habit", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "数字与字母相乘的规范书写（'省略乘号规范'，'a×3 写 a3'错因的正面陷阱）", "难度理由": "easy——单条规则识别", "认知阶梯定位": "L1 识别正宗实现——书写规范的第一道判断", "错因陷阱": "选 A（b7——'书写规范错'）、选 C/D（保留乘号）", "教学角色": "L1 识别脚手架——'数字在前省乘号'规则探针"}
        },
        {
            "slot": "B2-I0",
            "prompt": "一辆汽车每小时行 v 千米，照这样的速度，3 小时行了多少千米？",
            "expected_answer": "3v（千米）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["速度 × 时间 = 路程：v × 3", "规范书写：数字在前省略乘号 → 3v 千米", "检验：v = 60 时 3 × 60 = 180 千米"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "速度×时间公式的字母表示（'用字母表示数量'，公式迁移）", "难度理由": "easy 套用——单步关系", "认知阶梯定位": "L2 套用", "错因陷阱": "写 v3（乘号省略不规范）、写 v + 3（'数量关系表达反'）", "教学角色": "L2 套用脚手架——字母 × 数规范应用"}
        },
        {
            "slot": "B2-I1",
            "prompt": "小明有 20 元，买了 a 支笔，每支 3 元。他还剩多少元？",
            "expected_answer": "20 − 3a（元）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["买笔花的钱：每支 3 元 × a 支 = 3a 元", "剩下的 = 20 − 3a 元", "检验：a = 4 时 20 − 12 = 8 元，合理"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两步数量关系（先乘后减，'用字母表示数量'，mastery'表达简单数量关系'取证）", "难度理由": "medium——乘法与减法两步、字母系数", "认知阶梯定位": "L2 套用——两步关系标准应用", "错因陷阱": "写 3a − 20（'数量关系表达反'）、写 20 − a × 3（保留乘号书写不规范）", "教学角色": "两步关系套用——'剩下的 = 总数 − 花的钱'结构示范"}
        },
        {
            "slot": "B2-I2",
            "prompt": "一本故事书有 p 页，小红每天读 8 页，读了 d 天后还剩多少页？",
            "expected_answer": "p − 8d（页）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["已读的页数：每天 8 页 × d 天 = 8d 页", "还剩 = p − 8d 页", "检验：p = 100、d = 3 时 100 − 24 = 76 页，合理"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "两个字母的两步关系（'用字母表示数量'，字母系数 × 字母变量）", "难度理由": "medium——两个字母、字母系数 8d，结构比 B2-I1 复杂一层", "认知阶梯定位": "L3 变式——从'数字系数'到'字母×字母'", "错因陷阱": "写 8d − p（'数量关系表达反'）、漏已读部分（只写 p）", "教学角色": "多字母变式——p 与 d 双字母关系处理"}
        },
        {
            "slot": "B3-I0",
            "prompt": "当 x = 8 时，(3x + 4) ÷ 2 的值是多少？",
            "expected_answer": "(3 × 8 + 4) ÷ 2 = (24 + 4) ÷ 2 = 28 ÷ 2 = 14",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "代入求值",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["代入：x = 8 → (3 × 8 + 4) ÷ 2", "先算括号里：3 × 8 = 24，24 + 4 = 28", "28 ÷ 2 = 14"],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "含括号的代入求值（'代入求值'，代入 + 运算顺序）", "难度理由": "medium——代入、括号、乘除三步", "认知阶梯定位": "L3 变式——从'直接代入'到'括号+两步运算'", "错因陷阱": "代入后忘括号（3 × 8 + 4 ÷ 2 = 26——运算顺序错）、除法先算", "教学角色": "代入求值变式——'代入后按运算顺序算'标准示范"}
        },
        {
            "slot": "B3-I1",
            "prompt": "长方形的长是 a 厘米，宽是 b 厘米，它的周长是多少厘米？（写出用字母表示的式子）",
            "expected_answer": "2(a + b) 厘米（或 2a + 2b 厘米）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["周长 = (长 + 宽) × 2（长方形周长公式）", "长 + 宽 = a + b，乘 2 → 2(a + b)", "也可以写成 2a + 2b；检验：a = 5、b = 3 时 2 × 8 = 16 厘米"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "用字母表示图形公式（'用字母表示数量'×几何公式，几何前置迁移）", "难度理由": "hard——要先回忆周长公式、再加括号乘 2，两处易错（漏括号/漏 ×2）", "认知阶梯定位": "L4 迁移——字母 × 长方形周长公式（几何知识混合）", "错因陷阱": "写 a + b（漏 ×2——漏总量）、写 a + b × 2（括号丢失——运算顺序错）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——字母×公式迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "餐厅摆方桌：1 张方桌坐 6 人，2 张方桌拼在一起坐 10 人，3 张拼在一起坐 14 人。照这样，n 张方桌拼在一起能坐多少人？",
            "expected_answer": "4n + 2（人）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["找规律：6、10、14，每多 1 张桌多坐 4 人", "第 n 张 = 6 + 4(n − 1) = 4n + 2", "检验：n = 3 时 4 × 3 + 2 = 14 ✓"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "图形规律 → 字母式（'用字母表示数量'，规律符号化迁移）", "难度理由": "hard——先找规律再符号化，'每次多 4'与初始 6 的关系是隐蔽点", "认知阶梯定位": "L4 迁移——'字母表达一类情况'的本质迁移（M-PRE-QUANTITY-RELATION 前置运用）", "错因陷阱": "写 6n（把'每张 6 人'当不变——规律误读）、写 4n（漏初始的 2 人）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——规律符号化迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "班上有男生 x 人，女生比男生多 5 人。女生有多少人？",
            "expected_answer": "x + 5（人）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'女生比男生多 5 人'：女生 = 男生 + 5", "男生 x 人 → 女生 x + 5 人", "检验：x = 20 时 20 + 5 = 25 人"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "比…多的差关系检测（'用字母表示数量'，防'会背不会用'）", "难度理由": "easy 检测——单步差关系", "认知阶梯定位": "L2 检测", "错因陷阱": "写 x − 5（'多'读成'少'——'数量关系表达反'）", "教学角色": "掌握档快速检测——差关系列式检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "小明把'x 与 5 的和的 2 倍'写成 x + 5 × 2。他错在哪里？正确的写法是什么？",
            "expected_answer": "错在没加括号：'x 与 5 的和'要先算，应写成 (x + 5)，再乘 2 得 2(x + 5)；x + 5 × 2 表示'x 加上 5 乘 2'，含义完全不同",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "省略乘号规范",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["'x 与 5 的和'：先相加，要加括号 → (x + 5)", "'的 2 倍'：× 2 → 2(x + 5)", "x + 5 × 2 按运算顺序先算 5 × 2 = 10，表示 x + 10，与题意不符"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "括号与书写规范的综合（'省略乘号规范'×'数量关系'，'书写规范错'的最高阶检测）", "难度理由": "hard——先加后乘需括号，漏括号改变含义，还要能说清两种写法的区别", "认知阶梯定位": "L3 检测 hard——书写规范与运算顺序综合取证", "错因陷阱": "漏括号写 x + 5 × 2（'书写规范错'）、把 2 只乘一个量", "教学角色": "判定层 hard 证据来源——括号必要性检测"}
        },
        {
            "slot": "B4-I2",
            "prompt": "3x 表示什么？当 x = 4 时，3x 的值是多少？",
            "expected_answer": "3x 表示 3 个 x 相加（x × 3，也就是 x 的 3 倍）；当 x = 4 时，3x = 3 × 4 = 12",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "代入求值",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["含义：3x = x + x + x = x × 3（数字在前省略乘号）", "代入：x = 4 → 3 × 4 = 12", "mastery'知道 2a 表示 2×a'的检测"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "字母式含义 + 代入求值复测（'代入求值'，mastery'知道 2a 表示 2×a'取证）", "难度理由": "medium 复测——含义与求值双输出", "认知阶梯定位": "L3 复测——'会背不会用'的含义复测", "错因陷阱": "把 3x 当 3 + x（含义错——'数量关系表达反'）、代入忘乘", "教学角色": "防'会背不会用'复测——字母式含义确认真实性"}
        },
        {
            "slot": "B5-I0",
            "prompt": "哥哥今年 a 岁，弟弟比哥哥小 4 岁。当 a = 12 时，弟弟多少岁？当 a = 15 时呢？这说明 a 是什么？",
            "expected_answer": "弟弟 a − 4 岁；a = 12 时 8 岁；a = 15 时 11 岁；说明 a 可以取不同值（字母表示一类情况，同一式子对应不同结果）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "代入求值",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["关系：弟弟 = 哥哥 − 4 = a − 4", "a = 12：12 − 4 = 8 岁；a = 15：15 − 4 = 11 岁", "同一个式子 a − 4 在不同 a 下结果不同——a 是会变化的数"],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "同一字母式多个取值的复测（'代入求值'，essence'字母是会变化的数'的最高阶复测）", "难度理由": "hard——同一式子代入两个值并说明字母可变本质，'把字母当固定未知数'即答不出第二问", "认知阶梯定位": "L4 复测——防'会背不会用'的本质复测", "错因陷阱": "只算一个值（把 a 当固定 12——'把字母当固定未知数'）、差关系反（写 a + 4）", "教学角色": "复测 hard 档——判定层 hard 证据来源，字母可变性复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小明说：'n 张桌子，每张坐 4 人，一共坐 4n 人。'小华问：'n = 6 时坐多少人？'小明说：'还是 4n。'小明的问题在于（　）\nA. 没说清 n 表示什么（桌子的张数），也没算具体人数——n = 6 时应是 4 × 6 = 24 人\nB. 4n 表示 4 个人\nC. n 不能等于 6\nD. 他没错，4n 就是答案",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["字母要说明它表示什么：n 表示桌子的张数", "4n 是式子，n 取 6 时代入得 4 × 6 = 24 人", "小明没交代 n 的含义、也没代入求值——'字母表示的具体含义丢'，选 A"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'字母表示的具体含义丢'错因的诊断（字母要说明含义并支持代入）", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'字母含义丢'错因的一键探针", "错因陷阱": "只写式子不说明字母含义、不给具体值（B/D——'字母表示的具体含义丢'）", "教学角色": "诊断题——字母含义意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小华说：'苹果每千克 5 元，买 a 千克要 5 + a 元。'他错在哪里？正确的式子是什么？",
            "expected_answer": "错在把'单价 × 数量'写成加法：总价 = 单价 × 数量 = 5 × a = 5a 元（不是 5 + a）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "用字母表示数量",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["总价关系：单价 × 数量 = 总价", "5 元 × a 千克 → 5 × a，规范写成 5a", "5 + a 是'每千克 5 元加 a 千克'，没有意义——'数量关系表达反'"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'数量关系表达反'错因的诊断（乘写加成）", "难度理由": "medium——要指出具体错误并写正确式子", "认知阶梯定位": "L2 诊断——'数量关系表达反'的直接探针", "错因陷阱": "把'每千克 5 元 × a 千克'写成 5 + a（乘号丢失/关系反写）", "教学角色": "诊断题——单价×数量关系的一键探针"}
        },
    ],
    # ===== M-PRE-DISTRIBUTIVE 运算律与去括号意识（计算+概念向：8 verified + 7 unverifiable） =====
    # 节点契约：essence="运算律不是为了炫技，而是后面整式去括号和合并的前身"；
    # seed=乘法分配律/凑整简算/括号前负号；common_mistakes=乱用简便运算/漏乘括号内每一项/负号分配错误；
    # diagnostic_probes=2道乘法分配律简算、1道括号前负号判断；mastery=能说出为什么能简算、能把a(b+c)类比到数字题；
    # prereq=M-PRE-INTEGER-OPS、M-PRE-ORDER-OPS；unlock=M-G7-PARENTHESIS、M-G7-POLY-ADD-SUB。
    # authoring 原则（照 ORDER-OPS 样板）：纯"计算：X"题 verified（答案机算真对）；识别/辨析/诊断题 unverifiable；
    # L1 真识别（判断哪句是分配律/结合律辨析）；hard 真难（字母分配律、括号前减号去括号、三位数凑整简算）；
    # 错因逐一布点："分配漏项"（B1-I1/B2-I2/B5-I1/B5-I2）、"乘法结合律与分配律混淆"（B1-I2）、
    # "简算不识别可凑整结构"（B2-I2/B3-I0/B4-I0/B4-I1/B5-I0）、"乱用简便运算"（B5-I2 诊断）、"负号分配错误"（B3-I1）；
    # 迁移布点：括号前负号去括号（B3-I1，M-G7-PARENTHESIS unlock 预告）、字母分配律（B3-I2，M-G7-POLY-ADD-SUB unlock 预告）。

    "M-PRE-DISTRIBUTIVE": [
        {
            "slot": "B1-I0",
            "prompt": "计算：4 × (25 + 9)，写出答案。",
            "expected_answer": "136",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["乘法分配律：4 × (25 + 9) = 4 × 25 + 4 × 9", "4 × 25 = 100，4 × 9 = 36", "100 + 36 = 136（先算括号 25 + 9 = 34，再乘 4 也得 136，两种方法殊途同归）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "乘法分配律 a(b+c) = ab + ac（标准例题）", "难度理由": "medium 锚点——25 + 9 可凑整（25 × 4 = 100），既演示分配律又演示凑整价值，作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'分配漏项'在后续槽位布点）", "教学角色": "讲本质用——essence'运算律是后面整式去括号和合并的前身'的演示载体（数值环节机算 verified）"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个算式是'乘法分配律'的用法？（　）\nA. 5 × (20 + 3) = 5 × 20 + 5 × 3\nB. (5 × 20) × 3 = 5 × (20 × 3)\nC. 5 × 20 = 20 × 5\nD. (5 + 20) + 3 = 5 + (20 + 3)",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "乘法分配律",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["乘法分配律：括号外的数分别乘括号里的每一项，再把积相加", "A：5 分别乘 20 和 3 再相加，是分配律 ✓", "B 是结合律（只换括号位置）、C 是交换律、D 是加法结合律", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别乘法分配律的算式形态（分配律 vs 结合律/交换律）", "难度理由": "easy——规则识别，无计算", "认知阶梯定位": "L1 识别正宗实现：判断哪句是分配律而非直接算", "错因陷阱": "选 B（把结合律当分配律——'乘法结合律与分配律混淆'错因的识别形态）", "教学角色": "L1 识别脚手架——分配律形态的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "算式 (6 × 25) × 4 = 6 × (25 × 4) 用的是什么运算律？（　）\nA. 乘法结合律\nB. 乘法分配律\nC. 乘法交换律\nD. 加法结合律",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "运算律辨析",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["结合律：三个数相乘，先乘前两个或先乘后两个，积不变", "(6 × 25) × 4 与 6 × (25 × 4) 只是括号位置变了，是结合律", "分配律是'乘进括号里每一项再相加'，这里没有分配", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "乘法结合律与分配律的辨析（'结合律=换括号位置，分配律=乘进每一项'）", "难度理由": "easy——规则辨析，无计算", "认知阶梯定位": "L1 识别正宗实现——结合/分配双律辨析", "错因陷阱": "选 B（把换括号位置的结合律当分配律——'乘法结合律与分配律混淆'错因）", "教学角色": "L1 识别脚手架——双律边界的定点辨析"}
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：3 × (20 + 5)，写出答案。",
            "expected_answer": "75",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分配律：3 × (20 + 5) = 3 × 20 + 3 × 5", "3 × 20 = 60，3 × 5 = 15", "60 + 15 = 75（先算括号 20 + 5 = 25，25 × 3 = 75 也对）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "乘法分配律正向套用（直接展开）", "难度理由": "easy——单步展开，与锚点同构换数字", "认知阶梯定位": "L2 套用——分配律标准应用", "错因陷阱": "分配漏项（只乘一项得 3 × 20 + 5 = 65）", "教学角色": "套用变式——分配律正向标准形态"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：25 × 4 + 25 × 6，写出答案。",
            "expected_answer": "250",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律逆用",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["分配律反过来用（提取公因数 25）：25 × 4 + 25 × 6 = 25 × (4 + 6)", "4 + 6 = 10", "25 × 10 = 250"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "乘法分配律的逆用（提取公因数简算）", "难度理由": "medium——逆用方向（从展开式回到 a(b+c)）是分配律的常见难点", "认知阶梯定位": "L2 套用——分配律逆用标准应用", "错因陷阱": "看不出公因数 25 直接硬算（简算识别盲区）、只提取一半", "教学角色": "分配律逆用标准变式——'简算不识别可凑整结构'错因布点"}
        },
        {
            "slot": "B2-I2",
            "prompt": "小丽要算 25 × 44，她想用乘法分配律简算。下面哪种方法对？（　）\nA. 25 × 44 = 25 × (40 + 4) = 25 × 40 + 25 × 4\nB. 25 × 44 = 25 × 40 + 44\nC. 25 × 44 = 25 × 4 + 4\nD. 25 × 44 = 20 × 44 + 5",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "凑整简算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["凑整：44 = 40 + 4，25 × 44 = 25 × (40 + 4)", "分配律：25 × 40 + 25 × 4 = 1000 + 100 = 1100", "B、C 只乘了一项（分配漏项）；D 的拆法没有运算律依据", "选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "用分配律把两位数拆成整十+个位凑整简算（识别正确拆法）", "难度理由": "medium——先识别可拆结构（44 = 40 + 4）再套分配律，B/C 是'分配漏项'直击", "认知阶梯定位": "L3 变式——分配律 × 凑整拆分", "错因陷阱": "分配漏项（B：只乘 40；C：只乘 4）、拆分无依据（D）——'分配漏项''简算不识别可凑整结构'双错因", "教学角色": "变式题——凑整拆分的结构识别"}
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：99 × 7 + 7，写出答案。",
            "expected_answer": "700",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律逆用",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["把后面的 7 看成 1 × 7，提取公因数 7：99 × 7 + 7 = 7 × 99 + 7 × 1 = 7 × (99 + 1)", "99 + 1 = 100", "7 × 100 = 700"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分配律逆用（隐藏的 1 × 7，凑 99 + 1 = 100）", "难度理由": "medium——'看不见的公因数'是简算识别的关键跳跃，直接硬算虽可得但失去简算意义", "认知阶梯定位": "L3 变式——分配律逆用的隐蔽结构", "错因陷阱": "看不出 99 × 7 + 7 里有公因数 7（把后面的 7 当普通加数）——'简算不识别可凑整结构'", "教学角色": "逆用变式——隐藏公因数的识别训练"}
        },
        {
            "slot": "B3-I1",
            "prompt": "把 20 − (6 + 9) 去掉括号，正确的是（　）（这是七上整式去括号的数值前身：括号前是减号，去括号时里面每一项都要变号）\nA. 20 − 6 − 9\nB. 20 − 6 + 9\nC. 20 + 6 + 9\nD. 20 + 6 − 9",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "括号前负号",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["括号前是减号，去括号时里面每一项都变号：+6 → −6，+9 → −9", "20 − (6 + 9) = 20 − 6 − 9 = 5", "B、C、D 没有同时变号（负号分配错误）", "选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "括号前减号的去括号变号（每一项都变号）", "难度理由": "hard——'减号去括号每一项变号'是七上整式去括号的数值前身，只变一项是高频错", "认知阶梯定位": "L4 迁移——去括号意识，M-G7-PARENTHESIS unlock 预告", "错因陷阱": "只变第一项不变第二项（B，负号分配错误）、完全不变量（C）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——去括号变号迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "如果用 a、b、c 表示任意数，a × (b + c) 等于（　）（把数字分配律类比到字母，就是七上整式乘法的前身）\nA. a × b + a × c\nB. a × b + c\nC. a + b × c\nD. (a + b) × c + a",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "字母分配律",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["数字版分配律 5 × (20 + 3) = 5 × 20 + 5 × 3 中，把 5、20、3 换成 a、b、c", "a × (b + c) = a × b + a × c（每一项都乘 a）", "B 漏乘 c（分配漏项的字母形态），选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "把 a(b+c) 从数字类比到字母（mastery'能把 a(b+c) 类比到数字题'的正向版）", "难度理由": "hard——从具体数字到一般字母的抽象迁移，B 是'分配漏项'的字母版直击", "认知阶梯定位": "L4 迁移——数字分配律 → 字母分配律，M-G7-POLY-ADD-SUB unlock 预告", "错因陷阱": "漏乘 c（B，分配漏项的字母形态）、混淆加法运算", "教学角色": "判定层 transfer 证据来源（C3 双角色）——整式乘法前身迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：5 × (19 + 1)，写出答案。",
            "expected_answer": "100",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "凑整简算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["先看括号：19 + 1 = 20（凑整）", "5 × 20 = 100", "也可以用分配律：5 × 19 + 5 × 1 = 95 + 5 = 100"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "凑整简算检测（19 + 1 凑 20）", "难度理由": "easy 检测——凑整结构直接可见", "认知阶梯定位": "L2 检测——凑整识别与计算", "错因陷阱": "按顺序硬算 5 × 19（简算识别盲区）", "教学角色": "掌握档快速检测——'简算不识别可凑整结构'错因检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：102 × 45（用简便方法），写出答案。",
            "expected_answer": "4590",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "凑整简算",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["凑整：102 = 100 + 2，102 × 45 = 45 × (100 + 2)", "分配律：45 × 100 + 45 × 2 = 4500 + 90", "4500 + 90 = 4590"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "三位数拆成整百+个位的凑整简算（102 = 100 + 2）", "难度理由": "hard——要先识别 102 = 100 + 2 的拆法再套分配律，直接竖式硬算三位数乘两位数易错", "认知阶梯定位": "L3 检测 hard——凑整拆分结构检测", "错因陷阱": "看不出 102 可拆（简算识别盲区）、分配漏项（45 × 100 + 2）", "教学角色": "判定层 hard 证据来源——凑整简算取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：6 × 13 + 6 × 7，写出答案。",
            "expected_answer": "120",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律逆用",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["提取公因数 6：6 × 13 + 6 × 7 = 6 × (13 + 7)", "13 + 7 = 20", "6 × 20 = 120"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "分配律逆用复测（提取公因数防'会背不会用'）", "难度理由": "medium 复测——与 B2-I1 同构换数字，复测定位", "认知阶梯定位": "L3 复测——逆用掌握确认真实性", "错因陷阱": "看不出公因数直接硬算、漏加一项", "教学角色": "复测题——分配律逆用防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "计算：(40 + 8) × 25（用简便方法），写出答案。",
            "expected_answer": "1200",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "乘法分配律",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["分配律展开：40 × 25 + 8 × 25（40 × 25 和 8 × 25 都能口算）", "40 × 25 = 1000，8 × 25 = 200", "1000 + 200 = 1200（先算括号 48 × 25 = 1200 也对，但展开更简）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分配律展开凑整的全程综合复测（40 × 25、8 × 25 均可口算）", "难度理由": "hard——需识别'拆开后每项都凑整'才值得用分配律，直接 48 × 25 竖式亦可但易错", "认知阶梯定位": "L4 复测——防'会背不会用'的最高阶复测", "错因陷阱": "分配漏项（40 × 25 + 8）、看不出拆分价值", "教学角色": "复测 hard 档——判定层 hard 证据来源，分配律展开综合取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小刚算 6 × (30 + 5)，他写成 6 × 30 + 5 = 185。他错在哪里？（　）\nA. 漏乘了括号里的 5——6 要乘括号里的每一项，应是 6 × 30 + 6 × 5 = 210\nB. 应该先算乘法再算加法\nC. 他说得对\nD. 应该把 6 也丢掉",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "分配漏项诊断",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分配律：6 × (30 + 5) = 6 × 30 + 6 × 5", "小刚只乘了 30 没乘 5（分配漏项）", "正确：180 + 30 = 210，选 A"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'分配漏项'错因的诊断", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——'漏乘括号内每一项'错因的一键探针", "错因陷阱": "只乘括号里第一项（6 × 30 + 5）——'分配漏项'核心形态", "教学角色": "诊断题——'每一项都要乘'意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小刚说：'用简便方法就是随便怎么拆都行，反正结果一样。'于是他算 25 × 48 时写成 25 × 48 = 25 × 40 + 8。他错在哪里？正确的简算应该怎么写？",
            "expected_answer": "错在漏乘：25 × 48 = 25 × (40 + 8)，分配律要求每一项都乘，应是 25 × 40 + 25 × 8 = 1000 + 200 = 1200；简算不是'随便拆'，必须依据运算律（乘法分配律）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "简算依据诊断",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["简算的依据是运算律：25 × 48 = 25 × (40 + 8)（48 拆成整十 + 个位）", "分配律：25 × 40 + 25 × 8 = 1000 + 200 = 1200", "小刚写成 25 × 40 + 8：漏乘了 8（没乘 25），'随便拆'没有运算律依据", "正确结果 1200"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'乱用简便运算'错因的诊断（简算必须有运算律依据，且分配律不漏项）", "难度理由": "medium——要指出具体错误并写出正确简算", "认知阶梯定位": "L2 诊断——'乱用简便运算''分配漏项'双错因的直接探针", "错因陷阱": "把'凑整'当简算本质（无运算律依据）、拆分后漏乘（25 × 40 + 8）", "教学角色": "诊断题——'每一项都要乘/变号'意识的一键探针"}
        },
    ],
    # ===== M-PRE-PERCENT 百分数与增长率（概念+计算向：4 verified + 11 unverifiable） =====
    # 节点契约：essence="百分数本质是以100为标准的分率，关键仍是找单位1"；
    # seed=百分数互化/求百分率/折扣/增长·降低；common_mistakes=单位1找错/增长率和增长量混淆/百分号乱带单位；
    # diagnostic_probes=常用互化5个、求正确率/增长率各1题；mastery=常用互化秒答、能写出比较量÷标准量；
    # prereq=M-PRE-FRACTION-MEANING、M-PRE-DECIMAL-OPS；unlock=M-G7-EQ-WORD、M-BRIDGE-PERCENT-MODEL。
    # authoring 原则（照 QUANTITY-RELATION 概念向样板）：概念/互化/列式题 unverifiable（% 无法进 sympy 表达式，
    # 百分率题目不经'计算：'前缀）；仅把百分率写成小数/分数形态的数值题 verified（答案机算真对）；
    # L1 真识别（找单位1/判断谁除以谁）；hard 真难（三通路互化、连续涨降单位1、连续折扣、增长量vs增长率）；
    # 错因逐一布点："互化错"（B1-I2/B2-I0/B3-I1）、"谁除以谁反"（B2-I2/B5-I1）、"打折价算错"（B2-I1/B4-I1）、
    # "单位1找错"（B1-I1/B3-I2/B5-I2）、"增长率与增长量混淆/百分号乱带单位"（B3-I0/B5-I0）；
    # 迁移布点：互化三通路（B3-I1，分数/小数前置运用）、连续涨降（B3-I2，M-G7-EQ-WORD unlock 预告）。

    "M-PRE-PERCENT": [
        {
            "slot": "B1-I0",
            "prompt": "小红做口算 20 道，做对了 15 道。做对的题数是总题数的百分之几？（先想：谁是比较量，谁是单位 1）",
            "expected_answer": "比较量是做对的 15 道，单位 1（标准量）是总题数 20 道；做对题数 ÷ 总题数 = 15 ÷ 20 = 0.75 = 75%",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求百分率",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["求'一个数是另一个数的百分之几'：比较量 ÷ 标准量", "比较量：做对的 15 道；标准量（单位 1）：总题数 20 道", "15 ÷ 20 = 0.75 = 75%"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求百分率的标准例题（比较量 ÷ 标准量，找单位 1）", "难度理由": "medium 锚点——最简百分率题作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'谁除以谁反'在 B2-I2/B5-I1 布点）", "教学角色": "讲本质用——essence'百分数是以 100 为标准的分率，关键找单位 1'的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "'全班 50 人中有 30 人喜欢数学，喜欢数学的占 60%。'这里的单位 1（标准量）是（　）\nA. 全班人数 50\nB. 喜欢数学的 30 人\nC. 60\nD. 100",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "百分数意义",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'占 60%'是'占全班的 60%'，被比较的总数是全班人数", "单位 1 = 全班人数 50 人（标准量）", "喜欢数学的 30 人是比较量，选 A"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别百分数中的单位 1（'占…的百分之几'的'…'就是标准量）", "难度理由": "easy——单位 1 识别，无计算", "认知阶梯定位": "L1 识别正宗实现——找单位 1 的第一道判断", "错因陷阱": "把比较量 30 或百分数 60 当单位 1（'单位1找错'错因）", "教学角色": "L1 识别脚手架——单位 1 识别第一关"}
        },
        {
            "slot": "B1-I2",
            "prompt": "0.25 化成百分数是（　）\nA. 25%\nB. 2.5%\nC. 0.25%\nD. 250%",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "百分数互化",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["小数化百分数：小数点向右移两位，再加百分号", "0.25 → 25. → 25%", "选 A（B 只移一位，C 没移，D 方向反）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "小数化百分数（小数点右移两位加 %）", "难度理由": "easy——单步互化，但正是'常用互化秒答'的第一关", "认知阶梯定位": "L1 识别/套用——互化基础", "错因陷阱": "移错位数（2.5%、0.25%）、方向反（250%）——'百分数与分数小数互化错'", "教学角色": "互化识别题——常用互化秒答的入门探针"}
        },
        {
            "slot": "B2-I0",
            "prompt": "把 3/5 化成百分数，写出过程。",
            "expected_answer": "3/5 = 0.6 = 60%（先化小数，再把小数点右移两位加 %）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "百分数互化",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["分数化百分数：先化小数，3 ÷ 5 = 0.6", "小数化百分数：0.6 → 60%", "所以 3/5 = 60%"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "分数化百分数（分数 → 小数 → 百分数两步）", "难度理由": "easy——两步互化，方向明确", "认知阶梯定位": "L2 套用——互化标准应用", "错因陷阱": "0.6 直接写成 6%（移错位）、把 3/5 当 35%——'百分数与分数小数互化错'", "教学角色": "套用变式——分数 → 百分数的标准形态"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：200 × 0.85（一件衣服 200 元，打八五折，即按原价的 85% 出售），写出答案。",
            "expected_answer": "170",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "折扣",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["打八五折 = 按原价的 85% 出售，85% = 0.85", "现价 = 原价 × 折扣 = 200 × 0.85", "200 × 0.85 = 170（元）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "折扣计算（现价 = 原价 × 折扣，85% 化小数 0.85）", "难度理由": "medium——折扣率化小数一步 + 乘法，'打折价算错'的核心形态", "认知阶梯定位": "L2 套用——折扣标准应用", "错因陷阱": "把折扣当减法（200 − 85）、85% 化错小数——'打折价算错（原价×折扣）'错因", "教学角色": "折扣标准变式——'原价 × 折扣'模型的定点套用"}
        },
        {
            "slot": "B2-I2",
            "prompt": "'男生 30 人，女生 20 人。'要求'男生占全班的百分之几'，正确的算式是（　）\nA. 30 ÷ (30 + 20)\nB. 20 ÷ (30 + 20)\nC. 30 ÷ 20\nD. (30 + 20) ÷ 30",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求百分率",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["'男生占全班'：男生是比较量，全班人数是单位 1", "全班人数 = 30 + 20 = 50", "比较量 ÷ 标准量 = 30 ÷ 50，选 A（B 求的是女生占全班，C/D 单位 1 找错）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "求百分率的算式选择（谁 ÷ 单位 1）", "难度理由": "medium——需先求出总量再定谁除以谁，B/C/D 覆盖'谁除以谁反''单位1找错'", "认知阶梯定位": "L3 变式——百分率关系式的方向判断", "错因陷阱": "用女生 ÷ 全班（B）、部分 ÷ 部分（C）、总量 ÷ 部分（D）——'求百分之几时谁除以谁反'", "教学角色": "变式题——'比较量 ÷ 标准量'的方向训练"}
        },
        {
            "slot": "B3-I0",
            "prompt": "计算：80 × 1.25（某商品原价 80 元，涨价 25% 后，现价是原价的 125%，125% = 1.25），写出答案。",
            "expected_answer": "100",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "增长/降低",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["涨价 25%：现价 = 原价 × (1 + 25%) = 原价 × 125%", "125% = 1.25", "80 × 1.25 = 100（元）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "增长率应用（现价 = 原价 × (1 + 增长率)）", "难度理由": "medium——(1 + 25%) = 125% = 1.25 的转化是增长题的核心一步", "认知阶梯定位": "L3 变式——从折扣到增长的模型转换", "错因陷阱": "只乘增长率（80 × 25% = 20，把增长量当现价——'增长率和增长量混淆'）、单位 1 找错", "教学角色": "增长率变式——'(1 + 增长率)'模型布点"}
        },
        {
            "slot": "B3-I1",
            "prompt": "0.375、37.5%、3/8 是同一个数吗？分别写出：0.375 化成百分数、37.5% 化成分数、3/8 化成小数的过程。",
            "expected_answer": "是同一个数：0.375 = 37.5%（小数点右移两位加 %）；37.5% = 37.5/100 = 375/1000 = 3/8；3/8 = 0.375（3 ÷ 8）——三者相等，只是表示形式不同",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "百分数互化",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["0.375 化百分数：小数点右移两位 → 37.5%", "37.5% 化分数：37.5/100 = 375/1000，约分 = 3/8", "3/8 化小数：3 ÷ 8 = 0.375，回到起点——三者是同一个数"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "百分数 ↔ 分数 ↔ 小数的三通路互化（0.375 = 37.5% = 3/8）", "难度理由": "hard——37.5% 化分数要先化 375/1000 再约分，三方向互化环环相扣，任何一方向错即全错", "认知阶梯定位": "L4 迁移——分数意义与小数运算（M-PRE-FRACTION-MEANING/M-PRE-DECIMAL-OPS 前置）× 百分数互化", "错因陷阱": "37.5% 写 37.5/100 不会约分、0.375 写 3.75%（移错位）——'百分数与分数小数互化错'", "教学角色": "判定层 transfer 证据来源（C3 双角色）——互化三通路迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一台电脑原价 4000 元，先涨价 10%，再降价 10%，最后的价格比原价高还是低？低的话低多少？（写出过程）",
            "expected_answer": "低。涨价后 4000 × (1 + 10%) = 4400 元；降价 10% 是在 4400 的基础上降：4400 × (1 − 10%) = 3960 元；3960 < 4000，比原价低 40 元",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "增长/降低",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["先涨 10%：4000 × 1.1 = 4400（单位 1 是原价）", "再降 10%：4400 × 0.9 = 3960（单位 1 变成涨价后的 4400）", "3960 < 4000，低 40 元——两次的单位 1 不同，不能直接抵消"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "连续涨降的单位 1 变化（先涨 10% 再降 10% 不是回到原价）", "难度理由": "hard——两个 10% 的单位 1 不同（原价 vs 涨价后），'抵消'直觉是最大陷阱，差 40 元需全程算对", "认知阶梯定位": "L4 迁移——增长率 × 单位 1 变化，M-G7-EQ-WORD 列方程百分数题解锁预告", "错因陷阱": "以为涨跌抵消回原价（'单位1找错'）、第二次用原价算（4400 − 400）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——单位 1 变化迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：20 × 0.25（求 20 的 25% 是多少），写出答案。",
            "expected_answer": "5",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "求一个数的百分之几",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["求一个数的百分之几：一个数 × 百分率", "25% = 0.25", "20 × 0.25 = 5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "求一个数的百分之几检测（一个数 × 百分率）", "难度理由": "easy 检测——单步乘法", "认知阶梯定位": "L2 检测——'一个数 × 百分之几'快速检测", "错因陷阱": "把 25% 当 2.5（互化错）、用除法（20 ÷ 0.25）", "教学角色": "掌握档快速检测——'求一个数的百分之几'错因检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "计算：300 × 0.8 × 0.9（一件外套原价 300 元，先打八折，再在八折的基础上打九折），写出答案。",
            "expected_answer": "216",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "折扣",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["八折 = 0.8：300 × 0.8 = 240", "再打九折 = 0.9：240 × 0.9 = 216", "216 ÷ 300 = 72%——两次折扣合起来相当于原价的 72%（0.8 × 0.9 = 0.72）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "连续折扣计算（八折再九折，第二个折扣的单位 1 是折后价）", "难度理由": "hard——连续折扣第二个折扣基于折后价，需两步口算且易按原价重复打折", "认知阶梯定位": "L3 检测 hard——连续折扣综合检测", "错因陷阱": "两次都按原价（300 × 0.8 + 300 × 0.9）、把折扣相加（0.8 + 0.9）——'打折价算错'", "教学角色": "判定层 hard 证据来源——连续折扣取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "小丽做口算 25 道，做错了 4 道。她的正确率是百分之几？（正确率 = 做对的题数 ÷ 总题数）",
            "expected_answer": "做对 25 − 4 = 21 道；正确率 = 21 ÷ 25 = 0.84 = 84%",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求百分率",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["先求做对的题数：25 − 4 = 21 道", "正确率 = 做对题数 ÷ 总题数 = 21 ÷ 25", "21 ÷ 25 = 0.84 = 84%"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求正确率（diagnostic probe'求正确率 1 题'素材：先求对题数再求百分率）", "难度理由": "medium——先减再除两步，'做对 21 道'是隐藏一步", "认知阶梯定位": "L3 复测——正确率模型防遗忘复测", "错因陷阱": "用做错 4 道当分子（4 ÷ 25 = 16%）、忘了先减", "教学角色": "复测题——正确率 = 对题数 ÷ 总题数的复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "某市去年人口 50 万人，今年比去年增长了 2%。今年增加了多少人？增长率是多少？'增长量'和'增长率'是一回事吗？",
            "expected_answer": "增加 50 × 2% = 1 万人；增长率是 2%；不是一回事——增长量是具体人数（1 万人，带单位），增长率是百分数（2%，不带单位）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "增长/降低",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["增长量 = 单位 1 × 增长率 = 50 万 × 2% = 1 万人", "增长率是题里给的 2%（不带单位）", "增长量带单位（万人）、增长率不带单位（%）——不能混为一谈"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "'增长率和增长量混淆'错因的最高阶复测（增长量带单位、增长率是百分率）", "难度理由": "hard——要同时算增长量、认增长率、并论证两者区别，'百分号乱带单位'是其错误形态", "认知阶梯定位": "L4 复测——防'会背不会用'的本质复测", "错因陷阱": "把增长率当增长量（答'增长 2 万人'）、给增长率带单位——'增长率和增长量混淆''百分号乱带单位'", "教学角色": "复测 hard 档——判定层 hard 证据来源，增长量/增长率辨析"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小华说：'求 40 是 50 的百分之几，列式是 50 ÷ 40。'他错在哪里？（　）\nA. 应是比较量 ÷ 标准量：40 ÷ 50 = 80%（40 是'一个数'，50 是'另一个数'，即单位 1）\nB. 他没错\nC. 应该用 40 + 50\nD. 应该用 40 × 50",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "求百分率",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'40 是 50 的百分之几'：40 是比较量，50 是标准量（单位 1）", "比较量 ÷ 标准量 = 40 ÷ 50 = 0.8 = 80%", "小华写成 50 ÷ 40，谁除以谁反了，选 A"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'求百分之几时谁除以谁反'错因的诊断", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——'谁除以谁反'错因的一键探针", "错因陷阱": "用标准量 ÷ 比较量（50 ÷ 40）——'求百分之几时谁除以谁反'", "教学角色": "诊断题——'比较量 ÷ 标准量'方向的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "一本书有 200 页，第一天看了 30%，第二天看了剩下页数的 40%。小明说：'两天一共看了 70%。'小明错在哪里？两天一共看了全书的百分之几？",
            "expected_answer": "错在第二个 40% 的单位 1 是'剩下的页数'不是全书：第一天看 200 × 30% = 60 页，剩下 140 页；第二天看 140 × 40% = 56 页；一共 60 + 56 = 116 页，116 ÷ 200 = 58%，不是 70%",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "求百分率",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["第一天：200 × 30% = 60 页，剩下 200 − 60 = 140 页", "第二天：剩下页数的 40% = 140 × 40% = 56 页（单位 1 是剩下的 140 页）", "一共 60 + 56 = 116 页；116 ÷ 200 = 58%——小明把两个百分数的单位 1 都当全书了（单位1找错）"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "'单位1找错'错因的诊断（第二个百分率的单位 1 是剩余页数）", "难度理由": "medium——要先指出单位 1 错误再逐步重算，70% 的错误答案很诱人", "认知阶梯定位": "L2 诊断——'单位1找错'的直接探针", "错因陷阱": "把两个百分数都按全书 200 页算（60 + 80 = 140 页 = 70%）、30% + 40% 直接相加——'单位1找错'", "教学角色": "诊断题——单位 1 意识的一键探针"}
        },
    ],
    # ===== M-PRE-RATIO-PROP 比、比例与比例思想（概念+计算向：2 verified + 13 unverifiable） =====
    # 节点契约：essence="比表示两个量的关系，比例表示两个比相等"；
    # seed=化简比/求比值/按比例分配/比例尺；common_mistakes=比和比值混淆/单位不统一/比例尺单位错；
    # diagnostic_probes=1道化简比、1道按比例分配、1道比例尺；mastery=能区分比与比值、比例题能先统一单位；
    # prereq=M-PRE-FRACTION-MEANING、M-PRE-FRACTION-OPS；unlock=M-G7-EQ-WORD、M-BRIDGE-PROPORTION-MODEL。
    # authoring 原则（照 QUANTITY-RELATION 概念向样板）：化简比/比例尺/按比例分配题 unverifiable
    # （冒号与单位换算无法进 sympy 表达式）；仅'求比值 = 前项 ÷ 后项'的数值环节 verified（答案机算真对）；
    # L1 真识别（比的意义/比与比值）；hard 真难（分数比化简、周长×按比例分配、解比例、比例尺单位统一）；
    # 错因逐一布点："比与比值混淆"（B1-I2/B5-I1/B4-I1）、"化简比不彻底"（B2-I0/B2-I1/B4-I1）、
    # "比例内项外项积相等用错"（B3-I1/B5-I2）、"单位不统一/比例尺单位错"（B3-I2）；
    # 迁移布点：解比例（B3-I1，比例基本性质 × 简易方程前置）、比例尺（B3-I2，长度单位换算 × 化简比）。

    "M-PRE-RATIO-PROP": [
        {
            "slot": "B1-I0",
            "prompt": "把 6 与 3 的比写出来，并求出比值。",
            "expected_answer": "比：6:3（6 是前项，3 是后项）；比值：6 ÷ 3 = 2（比值 = 前项 ÷ 后项）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "比的意义",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["两个数相除又叫两个数的比：6 与 3 的比写作 6:3", "前项是 6，后项是 3", "比值 = 前项 ÷ 后项 = 6 ÷ 3 = 2"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "比的意义标准例题（两数相除叫比，比值 = 前项 ÷ 后项）", "难度理由": "medium 锚点——同时产出'比'与'比值'两个概念，作教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'比与比值混淆'在 B1-I2/B5-I1 布点）", "教学角色": "讲本质用——essence'比表示两个量的关系'的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下面哪个说法正确？（　）\nA. 比表示两个数相除的关系\nB. 比就是加法\nC. 比和除法没有关系\nD. 只有整数才能组成比",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "比的意义",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["比 = 两个数相除（前项 ÷ 后项），比值是除得的商", "A 对；B、C 与'比是除法关系'矛盾", "分数、小数都能组成比（如 1/2:3），D 错", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "比的意义识别（比 = 两数相除的关系）", "难度理由": "easy——概念识别，无计算", "认知阶梯定位": "L1 识别正宗实现——比的定义判断", "错因陷阱": "把比当加法/独立于除法（B/C，'比的意义'理解错）", "教学角色": "L1 识别脚手架——比的定义第一关"}
        },
        {
            "slot": "B1-I2",
            "prompt": "'两段路的长度比是 4:3。'这两段路的长度比值是（　）\nA. 4:3\nB. 4/3\nC. 3:4\nD. 3/4",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "比与比值",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["比表示关系（4:3），比值是一个数", "比值 = 前项 ÷ 后项 = 4 ÷ 3 = 4/3", "选 B（A 是比不是比值，C/D 前后项反）"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "比与比值的区分（比是关系 4:3，比值是数 4/3）", "难度理由": "easy——但正是节点 #1 错因'比和比值混淆'的正面直击", "认知阶梯定位": "L1 识别——比/比值属性判断", "错因陷阱": "选 A（把比当比值）、选 D（前后项颠倒）——'比和比值混淆'", "教学角色": "比与比值辨析——核心概念第一关"}
        },
        {
            "slot": "B2-I0",
            "prompt": "化简比：12:18，写出最简比。",
            "expected_answer": "12:18 = 2:3（前项后项同时除以最大公因数 6）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "化简比",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["化简比：前项、后项同时除以它们的最大公因数", "12 和 18 的最大公因数是 6", "12 ÷ 6 = 2，18 ÷ 6 = 3，最简比 2:3"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "化简比标准应用（同除最大公因数）", "难度理由": "easy——单步约分", "认知阶梯定位": "L2 套用——化简比标准形态", "错因陷阱": "只约一次不约彻底（如先得 4:6 就停——'化简比不彻底'）", "教学角色": "化简比套用——'同除公因数'标准形态"}
        },
        {
            "slot": "B2-I1",
            "prompt": "化简比：0.6:1.5，写出最简比。",
            "expected_answer": "0.6:1.5 = 6:15 = 2:5（先同乘 10 化成整数比，再同除最大公因数 3）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "化简比",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["小数比先化成整数比：0.6 和 1.5 同乘 10 → 6:15", "6 和 15 的最大公因数是 3，同除 3 → 2:5", "最简比 2:5"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "小数比化简（先化整数比再约分）", "难度理由": "medium——先同乘 10 再约分两步，且易在 6:15 停住", "认知阶梯定位": "L2 套用——小数比化简", "错因陷阱": "直接写 6:15 不约分（'化简比不彻底'）、小数点移动错", "教学角色": "小数比变式——'先整数化再化简'的训练"}
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：18 ÷ 24（求 18:24 的比值），写出答案。",
            "expected_answer": "3/4",
            "answer_format": "fraction",
            "verification_intent": "verified",
            "question_type": "求比值",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["比值 = 前项 ÷ 后项 = 18 ÷ 24", "18 ÷ 24 = 18/24，约分 = 3/4", "比值是 3/4（一个数，不是比 18:24）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "求比值 = 前项 ÷ 后项（数值环节机算 verified）", "难度理由": "medium——除法 + 约分两步，比值写法（分数）易与比（18:24）混淆", "认知阶梯定位": "L3 变式——从'写比'到'求比值'", "错因陷阱": "把 18:24 当答案（没化简没求商，'比和比值混淆'）、约分错", "教学角色": "求比值变式——'前项 ÷ 后项'的数值落地"}
        },
        {
            "slot": "B3-I0",
            "prompt": "下面哪组比能组成比例？（　）\nA. 2:3 和 4:6\nB. 2:3 和 3:2\nC. 2:3 和 2:4\nD. 2:3 和 6:4",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "比例判断",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["比例 = 两个比相等", "2:3 的比值是 2/3；4:6 的比值也是 2/3，两个比相等 → 能组成比例", "B、C、D 的第二个比比值都不是 2/3", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "比例概念判断（两个比相等才组成比例）", "难度理由": "medium——先求各比值再比较，A 是 2:3 的两倍放大", "认知阶梯定位": "L3 变式——从'一个比'到'两个比相等'", "错因陷阱": "只看数字不看比值（B 前后项相同就当相等）、只放大前项（C）——比例意义理解错", "教学角色": "比例概念变式——'两个比相等'的判断"}
        },
        {
            "slot": "B3-I1",
            "prompt": "在比例 3:4 = x:8 中，根据'内项之积 = 外项之积'求 x，写出过程。",
            "expected_answer": "内项是 4 和 x，外项是 3 和 8；内项之积 = 外项之积：4x = 3 × 8 = 24，x = 24 ÷ 4 = 6（检验：3:4 = 6:8，比值都是 3/4）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "解比例",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["比例中两个外项的积 = 两个内项的积", "外项 3 和 8：3 × 8 = 24；内项 4 和 x：4 × x", "4x = 24，x = 6；检验 3:4 = 6:8 比值相同 ✓"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "用'内项之积 = 外项之积'解比例（比例基本性质运用）", "难度理由": "hard——先定内外项再列积等式再解方程，三步环环相扣，'内外项定错'即全错", "认知阶梯定位": "L4 迁移——比例基本性质 × 简易方程（M-PRE-EQUATION-BASIC 前置），比例思想 unlock 预告", "错因陷阱": "内外项定错（把 4 和 x 当外项）、积等式方向错——'比例内项外项积相等用错'", "教学角色": "判定层 transfer 证据来源（C3 双角色）——比例性质迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一幅地图上，图上 3 厘米表示实际 60 千米。这幅图的比例尺是多少？（比例尺 = 图上距离 : 实际距离，注意单位统一）",
            "expected_answer": "单位统一：60 千米 = 6,000,000 厘米；比例尺 = 3 厘米 : 6,000,000 厘米 = 1 : 2,000,000",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "比例尺",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["比例尺 = 图上距离 : 实际距离，先把单位统一成厘米", "60 千米 = 60 × 100000 = 6,000,000 厘米", "3 : 6,000,000，同除 3 → 1 : 2,000,000"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "比例尺计算（单位统一 + 化简比）", "难度理由": "hard——千米化厘米的单位换算 + 比例尺前后项顺序，任何一步错即全错", "认知阶梯定位": "L4 迁移——长度单位换算（前置）× 化简比，比例尺 unlock 预告", "错因陷阱": "单位不统一直接 3:60（'单位不统一''比例尺单位错'）、前后项颠倒写 2,000,000:1", "教学角色": "判定层 transfer 证据来源（C3 双角色）——比例尺迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：24 ÷ 8（求 24:8 的比值），写出答案。",
            "expected_answer": "3",
            "answer_format": "decimal",
            "verification_intent": "verified",
            "question_type": "求比值",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["比值 = 前项 ÷ 后项 = 24 ÷ 8", "24 ÷ 8 = 3", "24:8 的比值是 3（化简比则是 3:1）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "求比值检测（比值 = 前项 ÷ 后项）", "难度理由": "easy 检测——整商", "认知阶梯定位": "L2 检测——求比值快速检测", "错因陷阱": "把 24:8 直接当答案、前后项颠倒（8 ÷ 24）", "教学角色": "掌握档快速检测——求比值错因检测"}
        },
        {
            "slot": "B4-I1",
            "prompt": "化简比：1/2 : 1/3，写出最简比。",
            "expected_answer": "1/2 : 1/3 = (1/2 × 6) : (1/3 × 6) = 3:2（同乘分母的最小公倍数 6）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "化简比",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["分数比化简：前项、后项同乘分母的最小公倍数", "2 和 3 的最小公倍数是 6", "1/2 × 6 = 3，1/3 × 6 = 2，最简比 3:2"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "分数比化简（同乘最小公倍数）", "难度理由": "hard——分数运算 + 找最小公倍数两步，易写成 3/2（比值冒充比）", "认知阶梯定位": "L3 检测 hard——分数比化简检测", "错因陷阱": "写 3/2（比和比值混淆）、同乘错数（'化简比不彻底'）", "教学角色": "判定层 hard 证据来源——分数比化简取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "把 60 个苹果按 2:3 分给甲、乙两个班，甲班和乙班各分到多少个？写出过程。",
            "expected_answer": "总份数 2 + 3 = 5 份；每份 60 ÷ 5 = 12 个；甲班 12 × 2 = 24 个，乙班 12 × 3 = 36 个（检验：24:36 = 2:3，共 60 个）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按比例分配",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["按比例分配：先算总份数 2 + 3 = 5", "每份 = 总数 ÷ 总份数 = 60 ÷ 5 = 12", "甲班 12 × 2 = 24，乙班 12 × 3 = 36（检验：24 + 36 = 60）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "按比例分配（diagnostic probe'1 道按比例分配'素材）", "难度理由": "medium——总份数 → 每份 → 各部分三步", "认知阶梯定位": "L3 复测——按比例分配模型防遗忘复测", "错因陷阱": "直接用 60 × 2 或 60 × 3（漏总份数）、份数算错", "教学角色": "复测题——'每份数 = 总数 ÷ 总份数'的复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "一个长方形的周长是 40 厘米，长与宽的比是 3:2。长方形的长和宽各是多少厘米？（先想：3:2 是长和宽的比，而 40 是周长）",
            "expected_answer": "周长 = 2 ×（长 + 宽），所以长 + 宽 = 40 ÷ 2 = 20 厘米；按 3:2 分：总份数 5 份，每份 20 ÷ 5 = 4；长 4 × 3 = 12 厘米，宽 4 × 2 = 8 厘米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "按比例分配",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["40 是周长，长 + 宽 = 40 ÷ 2 = 20 厘米（隐藏一步）", "3:2 → 总份数 5 份，每份 20 ÷ 5 = 4", "长 4 × 3 = 12，宽 4 × 2 = 8（检验：周长 2 × 20 = 40 ✓）"],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "按比例分配与周长复合（'先除以 2'的隐藏步骤）", "难度理由": "hard——40 是周长不是长宽和，漏除 2 是最大陷阱；再叠加按比例分配三步", "认知阶梯定位": "L4 复测——按比例分配最高阶复测（几何情境迁移）", "错因陷阱": "把 40 当长 + 宽直接分（每份 8，长 24 宽 16，周长就超了）、漏总份数", "教学角色": "复测 hard 档——判定层 hard 证据来源，按比例分配综合取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小华说：'比值就是比，3:2 和 3/2 是一回事。'他说得对吗？（　）\nA. 不对——3:2 是比（表示两个量的关系），3/2 是比值（一个数），两者不同\nB. 对，一样\nC. 不对——3/2 才是比\nD. 对，但只能写成整数比",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "比与比值",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["比表示两个量之间的关系（3:2），比值是前项除以后项所得的商（3/2，一个数）", "比值可以写成数，比用冒号/分数形式表示关系", "小华把'比'和'比值'混为一谈，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'比和比值混淆'错因的诊断", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'比和比值混淆'错因的一键探针", "错因陷阱": "把比值当比（3/2 与 3:2 混为一谈）——'比和比值混淆'", "教学角色": "诊断题——比/比值区分意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小刚解比例 3:x = 6:8，他写成 3 × 6 = x × 8，解得 x = 9/4。他错在哪里？正确的 x 是多少？",
            "expected_answer": "错在把两个前项相乘当外项积：比例 3:x = 6:8 中，外项是 3 和 8，内项是 x 和 6；正确的是 3 × 8 = x × 6，24 = 6x，x = 4（检验：3:4 = 6:8 ✓）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "比例基本性质",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["确定内外项：3:x = 6:8，外项 3 和 8，内项 x 和 6", "内项之积 = 外项之积：x × 6 = 3 × 8 = 24", "x = 24 ÷ 6 = 4（小刚把两个前项 3 和 6 相乘，用错了内外项）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'比例内项外项积相等用错'错因的诊断", "难度理由": "medium——要先指出内外项定错再重算", "认知阶梯定位": "L2 诊断——'内项外项积相等用错'的直接探针", "错因陷阱": "把两个前项相乘（3 × 6）、把两个后项相乘——'比例内项外项积相等用错'", "教学角色": "诊断题——内外项意识的一键探针"}
        },
    ],

    # ===== M-PRE-ANGLE-BASIC 角度基础（概念+微计算：12 unverifiable + 3 verified） =====
    # 节点契约：essence="角是旋转的大小，一圈360度"；seed=角分类/角度加减/钟面角基础；
    # common_mistakes=周角/平角/直角混淆/角度进位不是十进制/看图误读；diagnostic_probes=角分类2题、角度计算2题；
    # mastery=能说出90/180/360度意义、能进行简单角度加减；prereq=M-PRE-NUMBER-SENSE；
    # unlock=M-G7-ANGLE、M-BRIDGE-CLOCK-ANGLE。
    # authoring 原则（琢玉教训）：概念/看图/单位推理题 unverifiable（诚实声明），纯"计算：X"数值环节 verified（答案机算真对）；
    # L1 真识别（直角识别/度量单位识别）；hard 真难（钟面角两步、射线定义判断、周角纠错）；
    # 错因逐一布点："直角=90°记混"（B1-I1/B4-I0/B5-I1）、"角的两边是射线不是线段"（B1-I0/B3-I2）、
    # "角度大小与边长无关"（B2-I2/B5-I2）、"周角/平角/直角混淆"（B2-I0/B3-I0/B4-I1）、"看图误读"（B4-I2/B5-I0）。
    "M-PRE-ANGLE-BASIC": [
        {
            "slot": "B1-I0",
            "prompt": "填空：角是由一个____和两条____组成的图形；角的两条边都可以无限延长，所以它们都是____（射线/线段/直线）。",
            "expected_answer": "顶点；边；射线",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角的初步认识",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角由一个顶点和两条边组成", "两条边从顶点出发、可以向一端无限延长，所以是射线（不是线段、不是直线）", "填空顺序：顶点；边；射线"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角的组成三要素（顶点/两条边/边是射线）", "难度理由": "medium 锚点——本质句填空，作为教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'边是射线不是线段'在 B3-I2 单独布点）", "教学角色": "讲本质用——essence'角是旋转的大小'的静态定义演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "下列各角中，是直角的是（　）\nA. 45°\nB. 100°\nC. 90°\nD. 180°",
            "expected_answer": "C",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["直角等于 90°", "90° 的角是直角，选 C", "45° 是锐角、100° 是钝角、180° 是平角"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "直角识别（直角 = 90°）", "难度理由": "easy——L1 分类识别，无计算", "认知阶梯定位": "L1 识别正宗实现——分类标准判断", "错因陷阱": "把 100° 或 180° 当直角（'直角=90°记混'节点错因）", "教学角色": "L1 识别脚手架——直角标准的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "测量角的大小，使用的单位是（　）\nA. 米\nB. 度\nC. 千克\nD. 分钟",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的度量单位",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["角的大小用'度'来度量", "1 直角 = 90°，一圈 = 360°，都带着'度'", "米是长度单位、千克是质量单位、分钟是时间单位，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "角的度量单位识别（度）", "难度理由": "easy——L1 单位识别", "认知阶梯定位": "L1 识别——度量单位的判断", "错因陷阱": "把长度/质量/时间单位当角度单位（单位体系混淆）", "教学角色": "L1 识别脚手架——'度'作为角度单位的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "平角是 180 度，直角是 90 度。计算：180 − 90，平角比直角大多少度？",
            "expected_answer": "90",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角度加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["平角 180°，直角 90°", "180 − 90 = 90，平角比直角大 90°"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "平角/直角度数差（180° − 90°）", "难度理由": "easy——一步减法，直击'平角/直角混淆'错因", "认知阶梯定位": "L2 套用——角度数值关系的直接应用", "错因陷阱": "把平角当 360°（周角）或把直角当 180°（'周角/平角/直角混淆'）", "教学角色": "角度数值标准变式——数值环节机算 verified"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：45 + 30，一个角是 45 度，另一个角是 30 度，两个角合起来是多少度？",
            "expected_answer": "75",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角度加减",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["求两个角的和用加法", "45 + 30 = 75（度）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "简单角度加法（45° + 30°）", "难度理由": "medium——对应 mastery'能进行简单角度加减'的标准形态", "认知阶梯定位": "L2 套用——角度加减的直接应用", "错因陷阱": "把 45 + 30 算成 70（进位漏）或 480（进率当 100——'角度进位不是十进制'）", "教学角色": "角度加减标准变式——mastery'简单角度加减'取证"}
        },
        {
            "slot": "B2-I2",
            "prompt": "小华画了一个 60° 的角，为了看得更清楚，他把两条边都画得比原来长 3 倍。现在这个角的度数是（　）\nA. 60°\nB. 180°\nC. 20°\nD. 无法确定",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的大小",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角的大小由两条边张开的程度决定，与边的长短无关", "把边画长只是射线画得更长，张开程度没变", "角的度数仍是 60°，选 A"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角的大小与边长无关（本质属性）", "难度理由": "medium——情境化变式，直击视觉误判", "认知阶梯定位": "L3 变式——从静态判断到情境应用（'角度大小与边长无关'错因布点）", "错因陷阱": "认为边变长 3 倍角变 180°（'角度大小与边长无关'迷思）", "教学角色": "变式题——'角度大小与边长无关'的 L3 形态"}
        },
        {
            "slot": "B3-I0",
            "prompt": "把下面的角按类型填空：45° 是____角；90° 是____角；130° 是____角；180° 是____角。",
            "expected_answer": "锐；直；钝；平",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["锐角 < 90°：45° 是锐角", "等于 90° 是直角", "90° < 130° < 180°：130° 是钝角", "等于 180° 是平角"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "角分类完整套用（锐/直/钝/平）", "难度理由": "medium——四种角逐一归类，含边界辨析（130° 不是直角）", "认知阶梯定位": "L3 变式——分类标准的综合应用", "错因陷阱": "把 130° 当直角、把 180° 当钝角（'周角/平角/直角混淆'）", "教学角色": "分类套用变式——一次覆盖四类角"}
        },
        {
            "slot": "B3-I1",
            "prompt": "钟面上 3 点整时，时针和分针所成的角是什么角？是多少度？（提示：钟面一圈是 360°，平均分成 12 大格）",
            "expected_answer": "直角；90°（3 点整时针指向 3、分针指向 12，相距 3 大格，3 × 30° = 90°）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "钟面角基础",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["钟面一圈 360° 分成 12 大格，每大格 360 ÷ 12 = 30°", "3 点整：时针指向 3，分针指向 12，两针相距 3 大格", "3 × 30° = 90°", "90° 的角是直角"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "用度度量钟面角（读时刻 + 每大格 30° + 分类）", "难度理由": "hard——读时刻、换算每大格 30°、乘 3、再分类，四步推理", "认知阶梯定位": "L4 迁移——角度基础 × 钟面（M-BRIDGE-CLOCK-ANGLE unlock 预告）", "错因陷阱": "把 3 点整两针距离数错、每大格度数错（'看图误读'）、把 90° 当钝角", "教学角色": "判定层 transfer 证据来源（C3 双角色）+ 钟面角预告锚点"}
        },
        {
            "slot": "B3-I2",
            "prompt": "下列说法正确的是（　）\nA. 角的两边是线段，所以角的大小和边的长短有关\nB. 角的两边是射线\nC. 角的两边是直线，所以角等于 180°\nD. 角只有一条边",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的初步认识",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["角的两边是射线（从顶点出发向一端无限延长）", "线段有端点不能延长、直线两端都无限长且没有端点，都不是角的两边", "选 B（A/C/D 都把角的两边说成别的线）"],
            "error_tags": ["concept_confusion", "visual_spatial"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "角的两边是射线（射线/线段/直线三概念辨析）", "难度理由": "hard——每个选项都要判断'边是什么线'，需三概念辨析", "认知阶梯定位": "L4 迁移——角的定义 × 线型概念（'角的两边是射线不是线段'错因布点）", "错因陷阱": "把角的两边当线段或直线（'角的两边是射线不是线段'核心迷思）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——概念联结题"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：90 + 90，两个直角合起来是多少度？",
            "expected_answer": "180",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "角度加减",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["每个直角是 90°", "90 + 90 = 180（度）", "两个直角合起来正好是一个平角"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "直角度数检测（90° + 90° = 180°）", "难度理由": "easy 检测——单步加法，直击'直角=90°记混'", "认知阶梯定位": "L2 检测——直角数值掌握的检测", "错因陷阱": "把直角当 100°（90 + 100）或当 45°（'直角=90°记混'）", "教学角色": "掌握档快速检测——直角数值的探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "小明说：'周角是 100 度，因为一圈就是 100。'他说得对吗？正确的周角是多少度？它等于几个直角？",
            "expected_answer": "不对；周角 = 360°（一圈是 360 度，不是 100 度）；360 ÷ 90 = 4，1 周角 = 4 个直角",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["周角是旋转一整圈形成的角，一圈 = 360°", "小明把 360 说成 100（'角度进位不是十进制'错因）", "360 ÷ 90 = 4，1 周角 = 4 个直角"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "周角度数与直角关系（360° = 4 × 90°）", "难度理由": "hard——先纠错（360 不是 100）再换算（÷90），两步推理", "认知阶梯定位": "L3 检测——周角/直角关系的深度检测", "错因陷阱": "把一圈当 100 度（'角度进位不是十进制'）、周角与平角混淆（'周角/平角/直角混淆'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"}
        },
        {
            "slot": "B4-I2",
            "prompt": "用量角器量角：角的一条边与内圈 0° 刻度线重合，另一条边与内圈 40° 刻度线重合，这个角是____度。小刚读成 140 度，他错在哪里？",
            "expected_answer": "40；错在看了外圈刻度（量角器有内外两圈刻度，内圈 40° 对应外圈 140°，读数要跟 0° 起边同一圈看）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "看图读角",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["量角器上有内外两圈刻度", "0° 起边在内圈，就沿内圈读数：另一条边指内圈 40°", "这个角是 40°", "140° 是外圈读数——内外圈看反（'看图误读'错因）"],
            "error_tags": ["visual_spatial", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "量角器读数（内外圈刻度，看图误读）", "难度理由": "medium——要正确读数并指出读错原因", "认知阶梯定位": "L3 变式——从概念到度量工具的读数应用", "错因陷阱": "内外圈刻度看反（40° 读成 140°——'看图误读'节点错因）", "教学角色": "看图读角变式——'看图误读'错因的直接布点"}
        },
        {
            "slot": "B5-I0",
            "prompt": "钟面上，分针从数字 2 走到数字 7，扫过的角是多少度？它是什么角？（提示：每大格 30°）",
            "expected_answer": "150°；钝角（分针从 2 到 7 走了 5 大格，5 × 30° = 150°，90° < 150° < 180°）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "钟面角基础",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["从 2 到 7 共 5 大格（2→3→4→5→6→7）", "每大格 30°：5 × 30° = 150°", "90° < 150° < 180°，是钝角"],
            "error_tags": ["visual_spatial", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "钟面扫过角的度量（数格 × 30° + 分类）", "难度理由": "hard——数大格（5 格）易数错 + 乘法 + 分类三环节", "认知阶梯定位": "L4 复测——钟面角基础的最高阶复测", "错因陷阱": "数错大格（把 2 到 7 当 4 格）、每大格度数错、把 150° 当直角（'看图误读'）", "教学角色": "复测 hard 档——判定层 hard 证据来源"}
        },
        {
            "slot": "B5-I1",
            "prompt": "判断：'直角等于 90 度'这个说法（　）\nA. 正确\nB. 错误，直角等于 180 度\nC. 错误，直角等于 360 度\nD. 错误，直角等于 100 度",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角分类",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["直角等于 90°（这是直角的定义）", "180° 是平角、360° 是周角", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "直角 = 90° 的掌握诊断", "难度理由": "easy——L1 概念判断", "认知阶梯定位": "L1 诊断——'直角=90°记混'错因的一键探针", "错因陷阱": "把直角当 180°/360°/100°（'直角=90°记混'核心迷思）", "教学角色": "诊断题——直角数值是否真掌握的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小明把角的两条边都画长了一倍，他说：'角的度数会变成原来的两倍。'他（　）\nA. 说得对，边变长角就变大\nB. 说得不对，角的大小与边的长短无关，度数不变\nC. 说得不对，角会变成原来的一半\nD. 说得对，但只有锐角才会这样",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "角的大小",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["角的大小由两条边张开的程度决定", "把边画长不改变张开程度", "角的度数不变，选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'角度大小与边长无关'错因诊断", "难度理由": "medium——要否定'边变长角变大'的说法", "认知阶梯定位": "L2 诊断——'角度大小与边长无关'迷思的直接探针", "错因陷阱": "认为边变长角变大（'角度大小与边长无关'迷思）", "教学角色": "诊断题——角本质理解的一键探针"}
        },
    ],

    # ===== M-PRE-GEO-AREA-VOLUME 面积体积公式理解（概念+计算：8 unverifiable + 7 verified） =====
    # 节点契约：essence="几何公式不是背出来的，是由切拼、转化和底面积×高来的"；seed=平面面积/圆面积周长/长方体圆柱圆锥体积；
    # common_mistakes=周长面积混淆/三角形圆锥忘除以2或乘1/3/半径直径混用；diagnostic_probes=平面面积2题、圆1题、立体体积1题；
    # mastery=能说明公式中每个量是什么、单位写正确；prereq=M-PRE-UNIT-CONVERSION、M-PRE-ORDER-OPS；unlock=M-G7-GEO-SOLID-PLANE。
    # authoring 原则（琢玉教训）：纯"计算：X"数值环节 verified（答案机算真对），公式选择/单位推理/纠错题 unverifiable（诚实声明）；
    # L1 真识别（周长面积语义/面积单位）；hard 真难（单位平方理解、cm³→dm³ 换算、体积公式+单位双纠错、周长面积双结果）；
    # 错因逐一布点："周长面积混淆"（B1-I1/B2-I0/B2-I1/B4-I0/B5-I0）、"面积体积单位混淆"（B1-I2/B2-I2/B3-I1/B4-I1/B5-I1）、
    # "公式记错"（B5-I2）、"单位换算漏"（B3-I2）、"三角形忘除以2"（B4-I2）、"半径直径混用"（B3-I0）。
    "M-PRE-GEO-AREA-VOLUME": [
        {
            "slot": "B1-I0",
            "prompt": "长方形的面积 = 长 × 宽。一块长方形菜地长 6 米、宽 4 米。计算：6 × 4，面积 = ____平方米。",
            "expected_answer": "24",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积公式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["长方形面积 = 长 × 宽", "把菜地看成每行 6 个 1 平方米的小方块、共 4 行（切拼观点）", "6 × 4 = 24（平方米）"],
            "error_tags": ["calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长方形面积公式套用（长 × 宽）", "难度理由": "medium 锚点——公式选择是核心，数值环节最简", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'周长面积混淆'在 B1-I1/B5-I0 布点）", "教学角色": "讲本质用——essence'公式由切拼而来'的演示载体（数值环节机算 verified）"}
        },
        {
            "slot": "B1-I1",
            "prompt": "要求'这块长方形草坪一圈有多长'，应该算的是（　）\nA. 面积\nB. 周长\nC. 体积\nD. 长和宽的和",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "周长与面积",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["'一圈有多长'是把图形的边加起来，是周长", "面积是'占多大地方'，体积是'占多大空间'", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "周长与面积的语义识别（一圈 = 周长）", "难度理由": "easy——L1 语义识别，无计算", "认知阶梯定位": "L1 识别正宗实现——周长/面积概念判断", "错因陷阱": "把'一圈有多长'当面积（'周长面积混淆'节点错因）", "教学角色": "L1 识别脚手架——周长面积的第一道区分"}
        },
        {
            "slot": "B1-I2",
            "prompt": "测量一个操场的占地面积，用下面哪个单位最合适？（　）\nA. 平方米\nB. 米\nC. 立方米\nD. 千克",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面积单位",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["占地面积是面积，用面积单位", "平方米是面积单位", "米是长度单位、立方米是体积单位、千克是质量单位，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "面积单位的识别（平方米 vs 米/立方米）", "难度理由": "easy——L1 单位识别", "认知阶梯定位": "L1 识别——面积单位的判断", "错因陷阱": "把立方米（体积单位）或米（长度单位）当面积单位（'面积体积单位混淆'节点错因）", "教学角色": "L1 识别脚手架——面积单位的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "一块长方形黑板长 5 米、宽 2 米。求面积。计算：5 × 2，面积 = ____平方米。",
            "expected_answer": "10",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积公式",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["长方形面积 = 长 × 宽", "5 × 2 = 10（平方米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长方形面积直接套用（5 × 2）", "难度理由": "easy——直接套用面积公式", "认知阶梯定位": "L2 套用——面积公式的直接应用", "错因陷阱": "把面积算成 5 + 2 = 7 或 (5 + 2) × 2 = 14（'公式记错，周长面积混'）", "教学角色": "面积计算标准变式——数值环节机算 verified"}
        },
        {
            "slot": "B2-I1",
            "prompt": "一个正方形花坛的边长是 4 米。求面积。计算：4 × 4，面积 = ____平方米。",
            "expected_answer": "16",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积公式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["正方形面积 = 边长 × 边长", "4 × 4 = 16（平方米）", "注意：4 × 4 是面积，4 × 2 是周长公式（边长 × 4）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "正方形面积套用（边长 × 边长）", "难度理由": "medium——边长 × 边长与周长公式（边长 × 4）容易混", "认知阶梯定位": "L2 套用——正方形面积与周长公式区分", "错因陷阱": "用 4 × 2 = 8（周长公式）或 4 + 4 = 8（'公式记错，周长面积混'）", "教学角色": "面积计算标准变式——面积/周长公式辨析"}
        },
        {
            "slot": "B2-I2",
            "prompt": "一个正方体魔方的棱长是 6 厘米。求体积。计算：6 × 6 × 6，体积 = ____立方厘米。",
            "expected_answer": "216",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "体积公式",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["正方体体积 = 棱长 × 棱长 × 棱长（长 = 宽 = 高 = 棱长）", "6 × 6 × 6 = 216", "为什么乘三次：长、宽、高三条边都要乘（乘两次是面积，乘三次才是体积）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "正方体体积（棱长³，乘三次的立方理解）", "难度理由": "medium——换图形（正方体）+ 体积'乘三次'的理解", "认知阶梯定位": "L3 变式——从长方体到正方体（换图形）", "错因陷阱": "只乘两次 6 × 6 = 36（那是底面积——'面积体积单位混淆'）", "教学角色": "体积计算变式——'平方/立方'维度理解布点"}
        },
        {
            "slot": "B3-I0",
            "prompt": "一个圆的半径是 3 厘米。求面积（π 取 3.14）。计算：3 × 3 × 3.14，面积 ≈ ____平方厘米。",
            "expected_answer": "28.26",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "圆面积",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["圆的面积 = 半径 × 半径 × π", "3 × 3 × 3.14 = 9 × 3.14 = 28.26", "注意用半径 3，不是直径 6"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "圆面积公式套用（πr²，π 取 3.14）", "难度理由": "medium——公式套用 + 小数乘法，且半径/直径易混", "认知阶梯定位": "L3 变式——从直边图形到曲边图形（圆面积）", "错因陷阱": "把直径 6 当半径代入（6 × 6 × 3.14——'半径直径混用'）", "教学角色": "圆面积标准变式——'半径直径混用'错因布点"}
        },
        {
            "slot": "B3-I1",
            "prompt": "一个正方形的边长是 3 米。小刚说：'面积是 3 × 3 = 9 米。'他说得对吗？正确的面积是多少？单位应该写什么？为什么？",
            "expected_answer": "不对；面积是 9 平方米，不是 9 米；因为面积由两条边相乘得到，米 × 米 = 平方米（面积单位带'平方'，表示'每边 1 米的小方块'）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面积单位",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["3 × 3 = 9 数值对", "但单位错了：两条边都带'米'，米 × 米 = 平方米", "面积单位带'平方'，因为面积是'铺了多少个 1 平方米的小方块'", "正确答案：9 平方米"],
            "error_tags": ["concept_confusion", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "面积单位的'平方'来源（维度理解：米 × 米 = 平方米）", "难度理由": "hard——要解释'为什么单位是平方米'，涉及公式背后的单位平方理解", "认知阶梯定位": "L4 迁移——面积公式 × 单位维度（'面积体积单位混淆'错因的根本解法）", "错因陷阱": "把 9 平方米写成 9 米（'面积体积单位混淆'——单位不写平方）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——单位平方理解迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一个长方体木箱长 50 厘米、宽 40 厘米、高 30 厘米。它的体积是多少立方厘米？合多少立方分米？（提示：1 立方分米 = 1000 立方厘米）",
            "expected_answer": "60000 立方厘米；60 立方分米（50 × 40 × 30 = 60000，60000 ÷ 1000 = 60）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "体积公式",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["长方体体积 = 长 × 宽 × 高 = 50 × 40 × 30", "50 × 40 = 2000，2000 × 30 = 60000（立方厘米）", "1 立方分米 = 1000 立方厘米：60000 ÷ 1000 = 60（立方分米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "长方体体积 + 体积单位换算（cm³ → dm³）", "难度理由": "hard——三步相乘 + 单位换算漏（进率 1000 忘除），任何一步错即全错", "认知阶梯定位": "L4 迁移——体积公式 × 单位换算（M-PRE-UNIT-CONVERSION 前置运用）", "错因陷阱": "只乘两次（底面积 2000）、cm³→dm³ 忘除以 1000（'单位换算漏'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——体积 × 单位换算迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "一块正方形手帕的边长是 30 厘米。绕手帕一圈的布边有多长（周长）？计算：30 × 4，周长 = ____厘米。",
            "expected_answer": "120",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "周长与面积",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["正方形周长 = 边长 × 4（四条边加起来）", "30 × 4 = 120（厘米）", "注意：30 × 30 = 900 是面积，不是周长"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "正方形周长检测（边长 × 4 vs 边长 × 边长）", "难度理由": "easy 检测——单步乘法，直击'周长面积混淆'", "认知阶梯定位": "L2 检测——周长/面积公式区分的检测", "错因陷阱": "用 30 × 30 = 900（面积公式当周长——'周长面积混淆'）", "教学角色": "掌握档快速检测——周长/面积公式辨析探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "一个长方体水槽长 5 分米、宽 4 分米、高 3 分米。小刚算体积：5 × 4 = 20，写'20 平方米'。他错在哪里？正确的体积是多少？",
            "expected_answer": "错在：①只乘了长 × 宽（漏乘高，那是底面积不是体积）；②单位应是'立方分米'不是'平方米'；正确体积 = 5 × 4 × 3 = 60 立方分米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "体积公式",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["体积 = 长 × 宽 × 高（三个量都要乘）", "小刚只乘了 5 × 4（底面积）", "单位：体积用立方分米，不是平方米（'面积体积单位混淆'）", "5 × 4 × 3 = 60（立方分米）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "体积公式与单位双纠错（漏乘高 + 面积单位当体积单位）", "难度理由": "hard——两处错误都要指出并重算", "认知阶梯定位": "L3 检测——体积公式与单位的深度检测", "错因陷阱": "漏乘高（5 × 4 当体积）、单位写平方米（'面积体积单位混淆'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"}
        },
        {
            "slot": "B4-I2",
            "prompt": "一个三角形的底是 8 厘米、高是 5 厘米。求面积。计算：8 × 5 ÷ 2，面积 = ____平方厘米。",
            "expected_answer": "20",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积公式",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["三角形面积 = 底 × 高 ÷ 2（两个三角形可以拼成一个平行四边形）", "8 × 5 = 40，40 ÷ 2 = 20（平方厘米）", "忘除以 2 会得 40，那是拼成的平行四边形的面积"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "三角形面积公式复测（底 × 高 ÷ 2）", "难度理由": "medium——公式含'÷2'，忘除是常见失分点", "认知阶梯定位": "L3 复测——三角形面积'忘除以2'错因的防遗忘复测", "错因陷阱": "忘除以 2 得 40（'三角形忘除以2'节点错因）", "教学角色": "复测题——三角形面积公式掌握的防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "一个长方形的长是 8 米、宽是 5 米。小刚说：'周长是 8 × 5 = 40 米。'他错在哪里？它的周长和面积分别是多少？",
            "expected_answer": "错在把面积当周长（8 × 5 是面积）；周长 = (8 + 5) × 2 = 26 米；面积 = 8 × 5 = 40 平方米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "周长与面积",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["周长 = (长 + 宽) × 2：先求长宽和 8 + 5 = 13，再 × 2 = 26（米）", "面积 = 长 × 宽 = 8 × 5 = 40（平方米）", "小刚的 8 × 5 = 40 算的是面积，单位也应写平方米"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "周长与面积综合复测（公式辨析 + 双结果）", "难度理由": "hard——先指出公式用错，再分别算周长和面积（三个输出）", "认知阶梯定位": "L4 复测——'周长面积混淆'的最高阶复测", "错因陷阱": "把 8 × 5 = 40 当周长（'公式记错，周长面积混'）、单位写错", "教学角色": "复测 hard 档——判定层 hard 证据来源"}
        },
        {
            "slot": "B5-I1",
            "prompt": "判断：'教室地面的面积是 60 立方米'这个说法（　）\nA. 正确，地面很大\nB. 错误，地面的面积应该用平方米\nC. 错误，应该用米\nD. 错误，应该用立方厘米",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "面积单位",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["地面是平面，它的'大小'是面积", "面积用平方米等面积单位", "立方米是体积单位（占空间的大小），选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'面积体积单位混淆'错因诊断", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'面积体积单位混淆'的一键探针", "错因陷阱": "把立方米（体积单位）当面积单位（'面积体积单位混淆'节点错因）", "教学角色": "诊断题——面积/体积单位区分意识的探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小明说：'长方形的面积 = 长 + 宽。'他说得对吗？为什么？正确的公式是什么？",
            "expected_answer": "不对；面积是'铺了多少个面积单位'，应该用乘法：面积 = 长 × 宽（长 + 宽只是两条边长度相加，不是面积）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面积公式",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["面积表示图形'占了多少个 1 平方米的小方块'", "长表示每行几个，宽表示几行，总数 = 长 × 宽", "长 + 宽只是两条边相加，不是面积", "正确公式：面积 = 长 × 宽"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "面积公式理解诊断（为什么是乘不是加）", "难度理由": "medium——要否定错误公式并解释原因", "认知阶梯定位": "L2 诊断——'公式记错'错因的直接探针", "错因陷阱": "把面积记成长 + 宽（'公式记错，周长面积混'）", "教学角色": "诊断题——面积公式是否真理解的探针"}
        },
    ],

    # ===== M-PRE-UNIT-CONVERSION 单位换算（概念+计算：9 unverifiable + 6 verified） =====
    # 节点契约：essence="单位不统一，公式再对也会错"；seed=长度/面积/体积单位、时间单位、人民币单位；
    # common_mistakes=面积进率当10/体积进率当100/时间进率用十进制；diagnostic_probes=长度、面积、体积、时间各1题；
    # mastery=能说出长度/面积/体积相邻进率、应用题会先统一单位；prereq=M-PRE-DECIMAL-OPS；
    # unlock=M-G7-SEGMENT-MEASURE、M-G7-EQ-WORD、M-PRE-GEO-AREA-VOLUME、M-BRIDGE-MOTION-BASIC。
    # authoring 原则（琢玉教训）：纯"计算：X"数值环节 verified（答案机算真对），进率推理/方向判断/纠错题 unverifiable（诚实声明）；
    # L1 真识别（换算方向/时间进率）；hard 真难（维度进率推理、cm²→m² 应用、复名数换算、体积单位综合）；
    # 错因逐一布点："进制记错（长度10、面积100、体积1000）"（B1-I0/B2-I0/B3-I0/B3-I1/B4-I2/B5-I0）、
    # "大化小乘小化大除搞反"（B1-I1/B2-I0/B4-I0/B5-I2）、"时间60进制当100"（B1-I2/B2-I2/B4-I1/B5-I1）、
    # "单位换算漏"（B3-I2/B5-I0）。
    "M-PRE-UNIT-CONVERSION": [
        {
            "slot": "B1-I0",
            "prompt": "填空：1 米 = ____分米 = ____厘米；1 千米 = ____米。",
            "expected_answer": "10；100；1000",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "长度单位换算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["相邻长度单位进率是 10：1 米 = 10 分米", "1 分米 = 10 厘米，所以 1 米 = 10 × 10 = 100 厘米", "1 千米 = 1000 米"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长度单位相邻进率（米/分米/厘米/千米）", "难度理由": "medium 锚点——进率表是单位换算的根基，作为教学基准难度", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；'进制记错'在 B2-I0/B3-I0 布点）", "教学角色": "讲本质用——essence'单位不统一，公式再对也会错'的进率演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "要把 3 米换成厘米（大单位化小单位），应该（　）\nA. 乘 100\nB. 除以 100\nC. 加 100\nD. 减 100",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "单位换算方向",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["大单位化小单位：数字要变大（同样的长度，用更小的单位数更大）", "米 → 厘米要乘进率 100", "3 米 = 3 × 100 = 300 厘米，选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'大化小乘'方向识别（米 → 厘米）", "难度理由": "easy——方向判断，无计算", "认知阶梯定位": "L1 识别正宗实现——换算方向判断", "错因陷阱": "小化大除大化小乘搞反（'大化小乘小化大除搞反'节点错因）", "教学角色": "L1 识别脚手架——换算方向的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "1 小时等于（　）\nA. 60 分钟\nB. 100 分钟\nC. 10 分钟\nD. 360 分钟",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "时间单位换算",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["时间进率是 60（不是 10、不是 100）", "1 小时 = 60 分钟", "1 分钟 = 60 秒", "选 A"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "时间进率识别（1 小时 = 60 分钟）", "难度理由": "easy——L1 进率识别", "认知阶梯定位": "L1 识别——时间 60 进制的判断", "错因陷阱": "把 1 小时当 100 分钟（'时间60进制当100'节点错因）", "教学角色": "L1 识别脚手架——时间进率的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "计算：5 × 100，5 米 = ____厘米。",
            "expected_answer": "500",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "长度单位换算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["米 → 厘米，大化小乘进率 100", "5 × 100 = 500（厘米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长度大化小换算（米 → 厘米，乘 100）", "难度理由": "easy——直接套用进率", "认知阶梯定位": "L2 套用——大化小乘的直接应用", "错因陷阱": "进制记错（把进率当 10，5 × 10 = 50）或乘除搞反（'进制记错'/'大化小乘小化大除搞反'）", "教学角色": "长度换算标准变式——数值环节机算 verified"}
        },
        {
            "slot": "B2-I1",
            "prompt": "计算：2 × 1000，2 吨 = ____千克。",
            "expected_answer": "2000",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "质量单位换算",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["质量相邻进率：1 吨 = 1000 千克，1 千克 = 1000 克", "吨 → 千克，大化小乘 1000", "2 × 1000 = 2000（千克）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "质量单位换算（吨 → 千克，乘 1000）", "难度理由": "medium——质量进率 1000 与长度进率 10 易混", "认知阶梯定位": "L2 套用——质量进率的直接应用", "错因陷阱": "把吨 → 千克进率当 100（2 × 100 = 200）或 10（'进制记错'）", "教学角色": "质量换算标准变式——进率按单位类别区分"}
        },
        {
            "slot": "B2-I2",
            "prompt": "计算：3 × 60，3 小时 = ____分钟。",
            "expected_answer": "180",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "时间单位换算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["1 小时 = 60 分钟（60 进制）", "小时 → 分钟，大化小乘 60", "3 × 60 = 180（分钟）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "时间单位换算（小时 → 分钟，乘 60）", "难度理由": "medium——60 进制是独立进率体系，与十进制度量易混", "认知阶梯定位": "L3 变式——从长度/质量到时间（换单位类别）", "错因陷阱": "把 1 小时当 100 分钟（3 × 100 = 300——'时间60进制当100'）", "教学角色": "时间换算变式——60 进制换算的标准形态"}
        },
        {
            "slot": "B3-I0",
            "prompt": "1 米 = 10 分米。计算：10 × 10，1 平方米 = ____平方分米。",
            "expected_answer": "100",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积单位换算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["面积单位进率 = 长度进率 × 长度进率", "1 米 = 10 分米，所以 1 平方米 = 10 × 10 = 100 平方分米", "面积进率是 100，不是 10"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "面积进率 100（维度解释：10 × 10）", "难度理由": "medium——要用'维度'解释为什么面积进率不是 10", "认知阶梯定位": "L3 变式——从长度进率到面积进率（进率由维度决定）", "错因陷阱": "把面积进率当 10（'面积进率当10'节点错因）", "教学角色": "面积进率变式——'长度10、面积10×10'维度理解"}
        },
        {
            "slot": "B3-I1",
            "prompt": "已知 1 米 = 10 分米。填空并说明理由：1 平方米 = ____平方分米，1 立方米 = ____立方分米。为什么面积进率不是 10？",
            "expected_answer": "100；1000；因为面积是两条边相乘（10 × 10 = 100），体积是三条边相乘（10 × 10 × 10 = 1000）——进率由维度决定：长度 10、面积 100、体积 1000",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面积单位换算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["面积 = 两条边相乘：1 平方米 = 1 米 × 1 米 = 10 分米 × 10 分米 = 100 平方分米", "体积 = 三条边相乘：1 立方米 = 10 × 10 × 10 = 1000 立方分米", "所以进率不是 10，而是由维度决定（长度 10、面积 10²、体积 10³）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "面积/体积进率的维度推理（10² = 100、10³ = 1000）", "难度理由": "hard——双空 + 用维度解释'为什么不是 10'，推理密度高", "认知阶梯定位": "L4 迁移——长度进率 × 维度推理（'面积进率当10、体积进率当100'错因的根本解法）", "错因陷阱": "面积进率当 10、体积进率当 100（'进制记错'节点错因）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——维度进率推理"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一块长方形菜地长 200 厘米、宽 150 厘米。小刚算面积：200 × 150 = 30000（平方厘米）。他还想用平方米表示，应该怎么做？面积是多少平方米？（提示：1 平方米 = 10000 平方厘米）",
            "expected_answer": "30000 平方厘米 ÷ 10000 = 3 平方米（小化大要除以进率）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "面积单位换算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": ["面积 = 200 × 150 = 30000（平方厘米）", "平方厘米 → 平方米：小化大，除以进率 10000", "30000 ÷ 10000 = 3（平方米）", "应用题要先统一单位（essence：单位不统一，公式再对也会错）"],
            "error_tags": ["calculation_or_symbol", "modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "面积换算应用（cm² → m²，÷10000）", "难度理由": "hard——先算面积再换单位，且 10000 进率易漏（'单位换算漏'）", "认知阶梯定位": "L4 迁移——面积公式 × 单位换算（mastery'应用题会先统一单位'取证）", "错因陷阱": "÷10000 忘除或当 ÷100（'单位换算漏'/'面积进率当10'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——换算在应用题中的迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "计算：500 ÷ 100，500 厘米 = ____米。",
            "expected_answer": "5",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "长度单位换算",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["厘米 → 米，小化大除以进率 100", "500 ÷ 100 = 5（米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "长度小化大换算（厘米 → 米，÷100）", "难度理由": "easy 检测——单步除法，直击'大化小乘小化大除搞反'", "认知阶梯定位": "L2 检测——小化大除的检测", "错因陷阱": "乘除搞反（500 × 100 = 50000——'大化小乘小化大除搞反'）", "教学角色": "掌握档快速检测——换算方向探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "90 分钟 = ____小时 ____分钟。",
            "expected_answer": "1；30（90 ÷ 60 = 1 余 30：1 小时 = 60 分钟，90 分钟里有 1 个 60 分钟，还剩 30 分钟）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "时间单位换算",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["1 小时 = 60 分钟（60 进制）", "90 ÷ 60 = 1 余 30", "所以 90 分钟 = 1 小时 30 分钟", "注意：不能把 90 分钟当 1 小时 90 分（不进位）或 0 小时 90 分（'时间60进制当100'）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "时间复名数换算（90 分 = 1 时 30 分）", "难度理由": "hard——除法取商取余 + 60 进制双环节", "认知阶梯定位": "L3 检测——时间 60 进制的深度检测", "错因陷阱": "把 90 分钟写成 1 小时 90 分（不进位）或 0 小时 90 分（'时间60进制当100'）", "教学角色": "检测 hard 档——判定层 hard 证据来源之一"}
        },
        {
            "slot": "B4-I2",
            "prompt": "计算：3 × 100，3 平方米 = ____平方分米。",
            "expected_answer": "300",
            "answer_format": "expression",
            "verification_intent": "verified",
            "question_type": "面积单位换算",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["1 平方米 = 100 平方分米（面积进率 100）", "平方米 → 平方分米，大化小乘 100", "3 × 100 = 300（平方分米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "面积大化小换算复测（平方米 → 平方分米，×100）", "难度理由": "medium——面积进率 100 复测，防'面积进率当10'回潮", "认知阶梯定位": "L3 复测——面积进率的防遗忘复测", "错因陷阱": "把面积进率当 10（3 × 10 = 30——'面积进率当10'）", "教学角色": "复测题——面积进率掌握的防遗忘复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "一个长方体水箱长 20 分米、宽 10 分米、高 5 分米。它的体积是多少立方分米？合多少立方米？（提示：1 立方米 = 1000 立方分米）",
            "expected_answer": "1000 立方分米；1 立方米（20 × 10 × 5 = 1000，1000 ÷ 1000 = 1）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "体积单位换算",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": ["体积 = 长 × 宽 × 高 = 20 × 10 × 5", "20 × 10 = 200，200 × 5 = 1000（立方分米）", "1 立方米 = 1000 立方分米：1000 ÷ 1000 = 1（立方米）"],
            "error_tags": ["calculation_or_symbol", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "体积计算 + 体积单位换算（dm³ → m³，÷1000）", "难度理由": "hard——三步相乘 + 体积进率 1000 应用，任何一步错即全错", "认知阶梯定位": "L4 复测——体积进率的最高阶复测（M-PRE-GEO-AREA-VOLUME 预告）", "错因陷阱": "体积进率当 100（1000 ÷ 100 = 10 立方米——'体积进率当100'）", "教学角色": "复测 hard 档——判定层 hard 证据来源，体积进率取证"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小明说：'0.5 小时就是 50 分钟，因为 0.5 就是 50。'他说得对吗？（　）\nA. 对，0.5 小时 = 50 分钟\nB. 不对，0.5 小时 = 30 分钟，因为 1 小时 = 60 分钟，0.5 小时是 60 的一半\nC. 不对，0.5 小时 = 5 分钟\nD. 不对，0.5 小时 = 半小时 = 50 分钟",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "时间单位换算",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": ["1 小时 = 60 分钟（60 进制，不是 100）", "0.5 小时是半小时：60 ÷ 2 = 30 分钟", "0.5 是'一半'，不是'50'（'时间60进制当100'错因）", "选 B"],
            "error_tags": ["concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'时间60进制当100'错因诊断（0.5 小时 = 30 分钟）", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'时间60进制当100'的一键探针", "错因陷阱": "把 0.5 小时当 50 分钟（0.5 = 50——'时间60进制当100'核心迷思）", "教学角色": "诊断题——时间进率意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小刚把 300 厘米换算成米，他算：300 × 100 = 30000，说'300 厘米 = 30000 米'。他错在哪里？300 厘米 = ____米。",
            "expected_answer": "错在把厘米换米当乘法（大化小才乘，小化大要除）；300 ÷ 100 = 3 米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "单位换算方向",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": ["厘米 → 米是小化大，应该除以进率 100", "小刚用了乘法（大化小的规则）——'大化小乘小化大除搞反'", "300 ÷ 100 = 3（米）"],
            "error_tags": ["concept_confusion", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "'大化小乘小化大除搞反'错因诊断", "难度理由": "medium——要指出方向错误并重算", "认知阶梯定位": "L2 诊断——'大化小乘小化大除搞反'的直接探针", "错因陷阱": "把厘米换米当乘法（'大化小乘小化大除搞反'节点错因）", "教学角色": "诊断题——换算方向意识的一键探针"}
        },
    ],

    # ===== M-BRIDGE-SOLUTION-HABIT 解题步骤与检验习惯（习惯/过程型：15 unverifiable） =====
    # 节点契约：essence="数学不是只要答案，稳定得分靠步骤、单位、符号和检验"；
    # seed=计算过程改错/方程代回检验/应用题设列解答规范/单位与答句检查；
    # common_mistakes=会做但跳步丢分/答案无单位/解方程不代回/符号书写混乱/草稿无法复查；
    # diagnostic_probes=给1道计算错解让孩子找错误/给1道方程要求代回检验/观察草稿是否能复盘；
    # mastery=能保留关键步骤/能主动做代回或估算检验/应用题答句有单位且符合题意；
    # prereq=无；unlock=M-G7-RATIONAL-MIXED、M-G7-EQ-SOLVE、M-G7-EQ-WORD、M-G7-ANGLE-CALC。
    # authoring 原则：全部 unverifiable（习惯/过程/检验类，题干不嵌显式算式）；
    # L1 真识别（识别跳步/单位缺失/检验做法）；hard 真难（两处错因改错、估算×检验复合、完整设列解答+检验）；
    # 错因逐一布点："跳步丢分"（B1-I1/B2-I1）、"答案无单位"（B1-I2）、"解方程不代回"（B2-I0/B2-I2/B4-I0/B4-I2/B5-I1）、
    # "符号书写混乱"（B2-I1/B4-I1）、"草稿无法复查"（B5-I2）；
    # 检验习惯迁移：估算合理性（B3-I1）、应用题全流程（B1-I0/B3-I0/B3-I2/B5-I0）。
    "M-BRIDGE-SOLUTION-HABIT": [
        {
            "slot": "B1-I0",
            "prompt": "一本练习册和一支钢笔一共 15 元，练习册比钢笔便宜 5 元。设钢笔 x 元，按'设、列、解、检验、答'五步写出完整解答，答句要带单位。",
            "expected_answer": "设钢笔 x 元，则练习册 (x − 5) 元；等量关系：钢笔的钱 + 练习册的钱 = 15；列方程 x + (x − 5) = 15；解得 2x = 20，x = 10；练习册 10 − 5 = 5（元）。检验：10 + 5 = 15 ✓，10 − 5 = 5 ✓，符合题意。答：钢笔 10 元，练习册 5 元。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "应用题设列解答规范",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设钢笔 x 元，练习册比钢笔便宜 5 元，则练习册 (x − 5) 元",
                "找等量关系：钢笔的钱 + 练习册的钱 = 一共的 15 元",
                "列方程：x + (x − 5) = 15，合并 2x − 5 = 15，2x = 20，x = 10；练习册 10 − 5 = 5（元）",
                "检验：10 + 5 = 15，10 − 5 = 5，符合题意 ✓；答：钢笔 10 元，练习册 5 元（答句带单位）"
            ],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "应用题'设列解答'全流程规范（含代回检验与带单位答句，essence'稳定得分靠步骤、单位、符号和检验'的演示载体）", "难度理由": "medium 锚点——完整流程示范（设 x → 和差关系 → 解 → 检验 → 答句）", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；答案内嵌检验步示范自查习惯）", "教学角色": "讲本质用——'设列解答+检验+单位'全流程的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "解方程 3x + 4 = 19 时，小明的过程是：3x + 4 = 19 → 3x = 15 → x = 5。他的过程少写了哪一步？（　）\nA. 从 3x = 15 到 x = 5，要写出'两边同时除以 3'这一步（跳步）\nB. 没少，口算出来的不用写\nC. 少了'两边同时加 4'这一步\nD. 少了'把 x = 5 代入'这一步，其他都齐了",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "计算过程改错",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "解方程每一步都要有依据：3x = 15 到 x = 5 是'两边同时除以 3'",
                "小明直接写出结果，跳过了关键步骤（'会做但跳步丢分'错因）",
                "选 A"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别解题过程中的跳步（'计算过程改错'，'会做但跳步丢分'错因的直接形态）", "难度理由": "easy——四选一识别缺失步骤", "认知阶梯定位": "L1 识别正宗实现——判断哪一步不能跳", "错因陷阱": "选 B（接受跳步——'会做但跳步丢分'）、选 C（把'除以 3'当成'加 4'）", "教学角色": "L1 识别脚手架——'保留关键步骤'的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "小明算出菜地的面积是 300，他写的答句是'菜地面积是 300'。最需要补的是什么？（　）\nA. 单位——面积要写'平方米'这样的单位，答句应写'菜地面积是 300 平方米'\nB. 把 300 改成 400\nC. 换一种方法再算一遍\nD. 什么都不用补，300 就是答案",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "单位与答句检查",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "答句要回答题目问的量，并带上正确的单位",
                "面积有单位：平方米/平方分米等，'300'没有单位信息不完整",
                "应写'菜地面积是 300 平方米'，选 A（'答案无单位'错因）"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "答句必须带单位（'单位与答句检查'，'答案无单位'错因的直接形态）", "难度理由": "easy——单位缺失识别", "认知阶梯定位": "L1 识别——单位完整性的判断", "错因陷阱": "选 C（用'重算'代替'补单位'——答句意识缺失）、选 D（接受无单位答案）", "教学角色": "L1 识别脚手架——'答句有单位'的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "用代回检验判断：x = 6 是不是方程 4x − 5 = 19 的解？写出检验过程。",
            "expected_answer": "是。检验：把 x = 6 代入方程左边 4x − 5：4 × 6 − 5 = 24 − 5 = 19，等于方程右边的 19 ✓。所以 x = 6 是方程 4x − 5 = 19 的解。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "方程代回检验",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "代回检验：把 x 的值代入原方程的左边",
                "4 × 6 − 5 = 24 − 5 = 19",
                "左边 19 = 右边 19，两边相等，所以 x = 6 是方程的解 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "方程代回检验的标准做法（'方程代回检验'，'解方程不代回'错因的正面纠正）", "难度理由": "easy 套用——代入求值 + 两边比较", "认知阶梯定位": "L2 套用——检验流程的标准应用", "错因陷阱": "只算一边不比较、代入算错（24 − 5 = 19 计算错）", "教学角色": "L2 套用脚手架——'检验 = 代回 + 比两边'的标准流程"}
        },
        {
            "slot": "B2-I1",
            "prompt": "小刚解方程 2x + 6 = 14，他写：'2x + 6 = 14，所以 2x = 14 + 6 = 20，x = 10。'他错在哪里？（　）\nA. 移项变号错：6 移到右边要变 −6，正确是 2x = 14 − 6 = 8，x = 4\nB. 没错，x = 10 就是答案\nC. 应该先算 2x = 14 × 6\nD. 应该把 2 移到右边变成 x = 14 + 6",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "计算过程改错",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "等式的性质：两边同时减去 6，2x = 14 − 6 = 8（移项要变号）",
                "小刚把 +6 移到右边没变号，得了 2x = 20（符号书写/移项混乱）",
                "x = 8 ÷ 2 = 4，选 A"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "找计算过程中的移项变号错误（'计算过程改错'，'符号书写混乱'错因的战场）", "难度理由": "medium——定位错误 + 正确移项两步", "认知阶梯定位": "L2 套用——过程纠错的直接应用", "错因陷阱": "选 B（接受错误过程——'会做但跳步丢分'）、选 C/D（把移项当乘除）", "教学角色": "过程纠错变式——移项变号规范的标准形态"}
        },
        {
            "slot": "B2-I2",
            "prompt": "小华解应用题：设苹果有 x 千克，列方程 3x + 2 = 20，解得 x = 6。下面哪个检验过程是完整的？（　）\nA. 把 x = 6 代回原方程：3 × 6 + 2 = 20 ✓，并检查 6 千克是否符合题意'苹果的 3 倍多 2 千克'\nB. 只看 x = 6 像正确答案就行\nC. 把 3x + 2 = 20 再抄一遍\nD. 检验就是把方程两边交换位置",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "方程代回检验",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "检验第一步：代回原方程，3 × 6 + 2 = 18 + 2 = 20 ✓",
                "检验第二步：检查答案是否符合题意（6 千克的 3 倍多 2 = 20）",
                "两步都过才算检验完整，选 A"
            ],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "应用题方程的完整检验（代回 + 符合题意，'方程代回检验'×审题前置）", "难度理由": "medium——代回与原题双重检查的识别", "认知阶梯定位": "L3 变式——从纯方程检验升级到应用题检验", "错因陷阱": "选 C（抄题当检验——'解方程不代回'）、选 D（不理解检验含义）", "教学角色": "检验习惯变式——'检验要看是否符合题意'的规范"}
        },
        {
            "slot": "B3-I0",
            "prompt": "把下面 5 个步骤按'设、列、解、检验、答'的正确顺序排列：① 答：科技书 15 本 ② 检验：15 × 3 = 45 ✓ ③ 设科技书有 x 本 ④ 3x = 45，x = 15 ⑤ 列方程 3x = 45（故事书是科技书的 3 倍）。",
            "expected_answer": "③ → ⑤ → ④ → ② → ①，即：设 → 列 → 解 → 检验 → 答",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "应用题设列解答规范",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "解题规范顺序：先设未知数（③），再列方程（⑤）",
                "然后解方程（④），解完代回检验（②）",
                "最后写答句（①）；所以 ③ → ⑤ → ④ → ② → ①"
            ],
            "error_tags": ["process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "应用题五步流程的顺序规范（'应用题设列解答规范'，'会做但跳步丢分'的结构化纠正）", "难度理由": "medium——步骤排序需理解每步的作用", "认知阶梯定位": "L3 变式——从'看懂流程'到'排对流程'", "错因陷阱": "把检验放最前（不懂检验在解之后）、漏答句（'答案无单位/无答句'）", "教学角色": "流程规范变式——五步顺序的结构化训练"}
        },
        {
            "slot": "B3-I1",
            "prompt": "小丽算 29 × 31，得到 890。先做估算检查：30 × 30 = 900，而 29 × 31 应该比 900 小一点。她的答案 890 合理吗？正确的积是多少？（先估算判断，再精确计算）",
            "expected_answer": "890 不合理。估算：29 × 31 ≈ 30 × 30 = 900，且 29 × 31 = (30 − 1) × (30 + 1) = 900 − 1 = 899。890 比 899 少 9，说明算错了。正确积是 899。再检验：30 × 31 = 930，930 − 31 = 899 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "估算合理性检查",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "估算检查：29 × 31 接近 30 × 30 = 900",
                "精确：29 × 31 = (30 − 1) × (30 + 1) = 900 − 1 = 899（平方差）",
                "890 ≠ 899，说明小丽算错了；正确积 899；用 30 × 31 − 31 = 899 复核 ✓"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "用估算检查计算结果的合理性（mastery'能主动做代回或估算检验'取证，估算前置运用）", "难度理由": "hard——估算判断 + 平方差精算 + 复核三步", "认知阶梯定位": "L4 迁移——估算（M-PRE-NUMBER-SENSE）迁移到检验习惯", "错因陷阱": "只看'接近 900'就认为 890 合理（估算只粗不细）、平方差展开错", "教学角色": "判定层 transfer 证据来源（C3 双角色）——估算×检验习惯迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "图书角有故事书和科技书共 90 本，故事书比科技书多 30 本。设科技书 x 本，按'设、列、解、检验、答'完整解答，并说明检验为什么能证明答案正确。",
            "expected_answer": "设科技书 x 本，则故事书 (x + 30) 本；等量关系：科技书 + 故事书 = 90；列方程 x + (x + 30) = 90；解得 2x = 60，x = 30；故事书 30 + 30 = 60（本）。检验：把 x = 30 代回：30 + 60 = 90 ✓，且 60 − 30 = 30 ✓，两个条件（共 90 本、多 30 本）都满足，所以答案正确。答：科技书 30 本，故事书 60 本。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "应用题设列解答规范",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "设科技书 x 本，故事书比科技书多 30 本，则故事书 (x + 30) 本",
                "等量关系：科技书 + 故事书 = 90，列方程 x + (x + 30) = 90",
                "2x = 60，x = 30；故事书 30 + 30 = 60（本）",
                "检验：代回得 30 + 60 = 90 ✓、60 − 30 = 30 ✓，两个已知条件都满足；答：科技书 30 本，故事书 60 本"
            ],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "和差应用题的完整设列解答 + 双重检验（'应用题设列解答规范'×和差模型前置）", "难度理由": "hard——设列解答全流程 + 说明检验依据（两个条件都验）", "认知阶梯定位": "L4 迁移——和差模型（M-PRE-QUANTITY-RELATION）迁移到规范流程", "错因陷阱": "检验只验一个条件（漏'多 30 本'）、答句漏单位", "教学角色": "判定层 transfer 证据来源（C3 双角色）——全流程规范迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "解完方程得到 x = 4，下面哪个做法是'检验'？（　）\nA. 把 x = 4 代回原方程，看左右两边是否相等\nB. 把方程再抄一遍\nC. 看看同桌的答案是不是 4\nD. 直接写答句，不检查",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "方程代回检验",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "检验 = 把解代回原方程，比较两边",
                "两边相等 → 解正确；不相等 → 解错了要重算",
                "选 A"
            ],
            "error_tags": ["process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'检验'动作的识别（'方程代回检验'，'解方程不代回'错因的检测探针）", "难度理由": "easy 检测——动作辨认", "认知阶梯定位": "L2 检测——掌握档快速检测", "错因陷阱": "选 B（抄题当检验）、选 D（不检验——'解方程不代回'）", "教学角色": "掌握档快速检测——检验习惯一键探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "小红的解答有两处问题。题一：4 + 6 × 3，她写'4 + 6 × 3 = 10 × 3 = 30'。题二：解方程 2(x + 1) = 10，她写'x + 1 = 20，x = 19'。请分别指出两处错误并改正。",
            "expected_answer": "题一错：运算顺序错，应先乘后加：4 + 6 × 3 = 4 + 18 = 22，她先算了加法。题二错：等式性质用反，两边应同时除以 2：x + 1 = 5，x = 4，她乘了 2。改正：题一 = 22，题二 x = 4。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "计算过程改错",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "题一：先乘除后加减，4 + 6 × 3 = 4 + 18 = 22，她先加后乘（运算顺序错）",
                "题二：2(x + 1) = 10 两边同时除以 2 → x + 1 = 5 → x = 4，她乘了 2（解方程依据错）",
                "两处都要找出并改正：22 与 x = 4"
            ],
            "error_tags": ["calculation_or_symbol", "process_habit"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "多步过程改错（运算顺序 + 等式性质两处错因，'计算过程改错'检测 hard 档）", "难度理由": "hard——两处独立错误要分别定位改正", "认知阶梯定位": "L3 检测 hard——过程纠错综合检测", "错因陷阱": "只找出一处错误（漏第二处）、把 x + 1 = 20 当对（'符号书写混乱'）", "教学角色": "判定层 hard 证据来源——两处错因的过程纠错取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "分别用代回检验判断：x = 5 和 x = 4 是不是方程 3x − 7 = 8 的解？写出检验过程。",
            "expected_answer": "x = 5：代入左边 3x − 7：3 × 5 − 7 = 15 − 7 = 8，等于右边 8 ✓，是方程的解。x = 4：代入左边：3 × 4 − 7 = 12 − 7 = 5，不等于 8 ✗，不是方程的解。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "方程代回检验",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "检验 x = 5：3 × 5 − 7 = 15 − 7 = 8 = 右边 ✓，是解",
                "检验 x = 4：3 × 4 − 7 = 12 − 7 = 5 ≠ 8 ✗，不是解",
                "代回检验能区分真假解，防止'算出答案就交'"
            ],
            "error_tags": ["process_habit", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "代回检验复测（一真一假解的判别，'方程代回检验'防退化）", "难度理由": "medium 复测——两次代入比较", "认知阶梯定位": "L3 复测——检验习惯的防遗忘复测", "错因陷阱": "只验一个解（漏 x = 4）、15 − 7 算错", "教学角色": "复测 medium——代回检验防退化取证"}
        },
        {
            "slot": "B5-I0",
            "prompt": "果园里桃树的棵数是梨树的 3 倍，桃树比梨树多 40 棵。设梨树 x 棵，完整写出'设、列、解、检验、答'。提示：先估算——40 棵是梨树的 2 倍，梨树大约是 20 棵，用这个估算检验你的答案。",
            "expected_answer": "设梨树 x 棵，则桃树 3x 棵；等量关系：桃树 − 梨树 = 40；列方程 3x − x = 40；解得 2x = 40，x = 20；桃树 3 × 20 = 60（棵）。估算检验：40 是梨树的 2 倍 → 梨树 = 40 ÷ 2 = 20 棵，与结果一致 ✓；再代回：60 − 20 = 40 ✓，60 = 3 × 20 ✓。答：梨树 20 棵，桃树 60 棵。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "应用题设列解答规范",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "设梨树 x 棵，桃树是梨树的 3 倍即 3x 棵",
                "等量关系：桃树 − 梨树 = 40，列方程 3x − x = 40",
                "2x = 40，x = 20；桃树 3 × 20 = 60（棵）",
                "估算检验：40 棵 = 梨树的 2 倍 → 梨树 20 棵，与结果一致；代回：60 − 20 = 40、60 = 3 × 20 ✓；答：梨树 20 棵，桃树 60 棵"
            ],
            "error_tags": ["process_habit", "modeling_or_reading"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "差倍应用题的完整流程 + 估算合理性检验（mastery'代回或估算检验''答句有单位'复合取证）", "难度理由": "hard——设列解答 + 估算检验 + 代回检验三重要求", "认知阶梯定位": "L4 复测——习惯规范的最高阶复测", "错因陷阱": "列 x − 3x（关系反）、只代回不估算（漏提示要求）、答句漏单位", "教学角色": "复测 hard 档——判定层 hard 证据来源，全流程规范复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小刚解完方程从不代回检验，他说：'我算的肯定对，检验浪费时间。'老师为什么坚持要他检验？（　）\nA. 检验能发现移项变号、计算这类自己没发现的错误，是最后一道安全网\nB. 检验能多拿分，跟发现错误没有关系\nC. 只有成绩差的孩子才需要检验\nD. 检验就是把答案抄一遍给老师看",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "方程代回检验",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "解方程时容易在移项变号、计算上出错，而且自己往往发现不了",
                "检验 = 代回原方程比两边，能抓住这些错误（'解方程不代回'错因）",
                "选 A"
            ],
            "error_tags": ["process_habit"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'解方程不代回'错因的诊断（为什么要检验）", "难度理由": "easy——L1 判断，无计算", "认知阶梯定位": "L1 诊断——节点 #3 错因的一键探针", "错因陷阱": "把检验当'形式/抄写'（选 D）、认为检验无意义（'解方程不代回'）", "教学角色": "诊断题——检验习惯的价值探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小华做计算题时草稿很乱：数字东写一个、箭头西画一个，答案写对了。老师让他讲每一步怎么来的，他讲不出来。问题出在哪里？（　）\nA. 草稿乱、关键步骤没保留，答案对也没法复查；错了也找不到出错点\nB. 他不够聪明\nC. 草稿写整齐会算得更慢\nD. 没有问题，答案对就行",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "过程复盘",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "解题要保留关键步骤，草稿才能复查（'草稿无法复查'错因）",
                "答案对但过程不可复盘，错了无法定位、老师也无法判断你真会",
                "选 A"
            ],
            "error_tags": ["process_habit"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'草稿无法复查'错因的诊断（过程可复盘的价值）", "难度理由": "medium——判断'为什么保留步骤'而非只看答案", "认知阶梯定位": "L2 诊断——'草稿无法复查'的直接探针", "错因陷阱": "选 D（只认答案——'会做但跳步丢分'）、把问题归因于聪明程度", "教学角色": "诊断题——'过程可复盘'习惯的一键探针"}
        },
    ],

    # ===== M-BRIDGE-WORD-PROBLEM-READING 应用题审题流程（审题型：15 unverifiable） =====
    # 节点契约：essence="应用题先读关系，再列式；不是看到数字就算"；
    # seed=圈关键词/找已知未知/写等量关系；common_mistakes=漏条件/问题看反/关键词机械套公式；
    # diagnostic_probes=给2道应用题，只要求标已知、未知、等量关系；
    # mastery=能在不计算时说出解题路径/能区分信息和问题；
    # prereq=M-PRE-QUANTITY-RELATION；unlock=M-G7-EQ-WORD、M-BRIDGE-MOTION-CHASE。
    # authoring 原则：全部 unverifiable（审题类，题干不嵌显式算式）；
    # L1 真识别（圈关键词/区分已知与问题/漏条件判断）；hard 真难（表格整理+等量关系+解题路径、
    # 机械套公式诊断、综合审题）；错因逐一布点："漏条件"（B3-I0/B5-I1）、"问题看反"（B3-I2/B5-I2）、
    # "关键词机械套公式"（B3-I2 诊断）、"把无关信息当条件"（B2-I2/B4-I2）、条件充分性（B3-I0/B4-I1/B5-I1）。
    "M-BRIDGE-WORD-PROBLEM-READING": [
        {
            "slot": "B1-I0",
            "prompt": "图书馆上午借出 26 本书，下午又借出 18 本，还剩 56 本。按'圈关键词 → 标已知未知 → 写等量关系'三步审题（不计算），写出：①关键词语句 ②已知条件 ③问题 ④等量关系。",
            "expected_answer": "① 关键词：'借出''还剩'（借出的和剩下的合起来是原来的本数）② 已知：上午借出 26 本、下午借出 18 本、还剩 56 本；未知：原来有多少本 ③ 问题：图书馆原来有多少本书 ④ 等量关系：原来的本数 − 借出的本数 = 剩下的本数，即 原来的 − (26 + 18) = 56",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "写等量关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "圈关键词：'借出''还剩'提示总量与部分的关系（原来的 − 借出的 = 剩下的）",
                "标已知：上午 26、下午 18、还剩 56；未知：原来有多少本（题目问题）",
                "写等量关系：原来的 − (26 + 18) = 56——先读关系再列式，不急着算"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "审题三步流程（圈关键词→标已知未知→写等量关系，essence'先读关系，再列式'的演示载体）", "难度理由": "medium 锚点——完整审题流程示范，不计算", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；答案内嵌三步审题示范）", "教学角色": "讲本质用——'不计算先审题'流程的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "读题：'一辆汽车 3 小时行驶 240 千米，照这样的速度，5 小时能行驶多少千米？'最先该圈出的关系是（　）\nA. '3 小时行驶 240 千米'——用它先求出每小时行多少千米\nB. '5 小时'——直接写 5\nC. '汽车'——跟汽车有关\nD. '行驶'——把数字都圈出来",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "圈关键词",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "圈关键词要找'数量关系'而不是孤立的词",
                "'3 小时行驶 240 千米'是求速度（每小时行多少千米）的关键关系",
                "先求速度再算 5 小时路程，选 A"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "圈出承载数量关系的语句（'圈关键词'，'关键词机械套公式'错因的反向训练）", "难度理由": "easy——关系句识别", "认知阶梯定位": "L1 识别正宗实现——找到'关系'而非'名词'", "错因陷阱": "选 D（把名词数字全圈上——不会找关系）、选 B（只盯问题里的数字）", "教学角色": "L1 识别脚手架——'关键词=数量关系'的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "题目：'果园有苹果树 45 棵，梨树比苹果树多 12 棵，梨树有多少棵？'下面说法正确的是（　）\nA. 已知：苹果树 45 棵、梨树比苹果树多 12 棵；问题：梨树有多少棵\nB. 已知：梨树有多少棵；问题：苹果树 45 棵\nC. 已知：苹果树 45 棵；问题：梨树比苹果树多多少棵\nD. 已知：梨树比苹果树多 12 棵；问题：一共有多少棵",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找已知未知",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "已知 = 题目直接告诉我们的条件：45 棵、多 12 棵",
                "问题 = 题目要我们求的：梨树有多少棵",
                "选 A（B 把已知问题颠倒、C 把问题当'多多少'、D 把问题当'一共'）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "区分已知条件与问题（'找已知未知'，'问题看反'错因的直接形态）", "难度理由": "easy——已知/问题归类", "认知阶梯定位": "L1 识别——信息与问题的区分", "错因陷阱": "选 B（把要求的当已知——'问题看反'）、选 C（问题找错对象）", "教学角色": "L1 识别脚手架——'区分信息和问题'的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "题目：'一根绳子长 80 米，用去 35 米，还剩多少米？'不计算，标出这道题的已知条件、未知量和问题。",
            "expected_answer": "已知条件：绳子总长 80 米、用去 35 米；未知量：还剩多少米（可设还剩 x 米）；问题：还剩多少米",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "找已知未知",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "找已知：绳子总长 80 米、用去 35 米（题目直接给的）",
                "找未知：还剩多少米——这正是问题要求的东西",
                "问题：还剩多少米（未知量 = 问题所求）"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "标已知/未知/问题的直接套用（'找已知未知'标准应用）", "难度理由": "easy——三步标注", "认知阶梯定位": "L2 套用——审题标注的标准应用", "错因陷阱": "漏标一个已知（'漏条件'错因雏形）、把问题当已知", "教学角色": "L2 套用脚手架——信息标注的标准流程"}
        },
        {
            "slot": "B2-I1",
            "prompt": "题目：'哥哥有 36 元，比弟弟的 2 倍少 4 元，弟弟有多少元？'不计算，写出这道题的等量关系。",
            "expected_answer": "弟弟的钱 × 2 − 4 = 哥哥的 36 元（弟弟的 2 倍少 4 元就是哥哥的钱）",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "写等量关系",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "读关系：'比弟弟的 2 倍少 4 元'→ 哥哥的钱 = 弟弟的钱 × 2 − 4",
                "弟弟的钱是未知，先设弟弟 x 元：2x − 4 = 36",
                "等量关系：弟弟的钱 × 2 − 4 = 36"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'倍少'复合关系的等量关系提炼（'写等量关系'，'数量关系提炼不出'错因的正面训练）", "难度理由": "medium——'2 倍少 4'的方向翻译", "认知阶梯定位": "L2 套用——复合关系写等量关系", "错因陷阱": "写成 2x + 4 = 36（'少 4'读反——数量关系方向错）、漏掉 2 倍", "教学角色": "等量关系套用——'比…的几倍少…'的标准翻译"}
        },
        {
            "slot": "B2-I2",
            "prompt": "题目：'小红买铅笔花了 15 元，买笔记本比买铅笔多花 8 元，其中一支铅笔是蓝色的、另一支是红色的。小红买笔记本花了多少钱？'哪个信息是无关的、解题用不到？（　）\nA. 铅笔是蓝色和红色的\nB. 买铅笔花了 15 元\nC. 买笔记本比买铅笔多花 8 元\nD. 小红",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找已知未知",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "审题要区分'有用信息'和'无关信息'（mastery'能区分信息和问题'）",
                "铅笔颜色不影响价格，是无关信息",
                "要用的是 15 元和'多花 8 元'，选 A"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "忽略无关信息（'找已知未知'变式，'把无关信息当条件'错因的正面纠正）", "难度理由": "medium——要在干扰信息里挑出无关项", "认知阶梯定位": "L3 变式——信息筛选", "错因陷阱": "把'蓝色红色'当条件用（'把无关信息当条件'）、漏用关键信息", "教学角色": "信息筛选变式——无关信息识别"}
        },
        {
            "slot": "B3-I0",
            "prompt": "题目：'小明买苹果和香蕉一共花了 30 元，苹果花了多少元？'这道题能解吗？（　）\nA. 不能解：只知道'一共 30 元'，还缺'香蕉花了多少元'（或苹果与香蕉的关系）这个条件\nB. 能解：30 元就是苹果的钱\nC. 能解：30 ÷ 2 = 15 元\nD. 能解：苹果一定比香蕉贵",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "条件充分性判断",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "列式需要'总量 = 部分 + 部分'：苹果 + 香蕉 = 30",
                "只给了总量 30，香蕉的钱（或两者关系）缺失，条件不充分",
                "漏条件时不能硬算，选 A（'漏条件'错因）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "条件充分性判断（'漏条件'错因的直接形态——缺条件时能识别不能硬算）", "难度理由": "medium——判断'能不能解'而非计算", "认知阶梯定位": "L3 变式——条件完整性检查", "错因陷阱": "选 C（30 ÷ 2 瞎猜——'漏条件还硬算'）、选 B（把总量当部分）", "教学角色": "条件检查变式——'漏条件'错因的识别训练"}
        },
        {
            "slot": "B3-I1",
            "prompt": "题目：'学校买来足球和篮球共 45 个，足球比篮球多 15 个，足球有多少个？'先用表格整理已知、未知和关系，再写出等量关系，最后说出解题路径（第一步做什么、第二步做什么）。不计算最终答案。",
            "expected_answer": "表格：已知 足球 + 篮球 = 45（和）、足球 − 篮球 = 15（差）；未知 足球个数。等量关系：足球 + 篮球 = 45，足球 − 篮球 = 15。解题路径：① 这是'和差模型'，先求大数：足球 = (和 + 差) ÷ 2；② 列式 (45 + 15) ÷ 2；③ 检验：算出的足球 + 篮球 = 45 且差 = 15。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "写等量关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "表格整理：两数和 45、两数差 15、未知是大数（足球）",
                "等量关系：足球 + 篮球 = 45；足球 − 篮球 = 15（和差双关系）",
                "解题路径：① 用和差模型：大数 = (和 + 差) ÷ 2 ② 代入 (45 + 15) ÷ 2 ③ 检验两个关系都满足"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "表格整理 + 双等量关系 + 解题路径（mastery'能在不计算时说出解题路径'取证，和差模型前置运用）", "难度理由": "hard——表格化、双关系提炼、路径规划三层次", "认知阶梯定位": "L4 迁移——M-PRE-QUANTITY-RELATION 前置运用 + 和差模型预告", "错因陷阱": "只写一个关系（漏差关系）、路径只有计算没有检验步", "教学角色": "判定层 transfer 证据来源（C3 双角色）——审题全流程迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "小刚看到'一共'就用加法、看到'还剩'就用减法。题目：'一根绳子剪成两段，第一段 24 米，第二段比第一段短 5 米，两段一共多长？'小刚直接算 24 − 5 = 19，说'一共 19 米'。他错在哪里？正确思路是什么？（只审题，说出步骤）",
            "expected_answer": "小刚把'第二段比第一段短 5 米'当成最后一步就停了，漏掉了问题问的是'两段一共多长'。正确思路：① 先求第二段：24 − 5 = 19（米）；② 问题问'一共'，把两段加起来：24 + 19 = 43（米）。'一共'要放在最后一步用，不能看到'比…短'就只算一步。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "圈关键词",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "审题先看问题：问'两段一共多长'，是两步问题",
                "第一步：求第二段 24 − 5 = 19（米）",
                "第二步：'一共' = 24 + 19 = 43（米）；小刚漏了第二步（'关键词机械套公式'错因）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "'关键词机械套公式'错因诊断（看到关键词就停，漏掉问题全貌）", "难度理由": "hard——识别机械套用的错误并补全两步审题", "认知阶梯定位": "L4 迁移——两步关系审题（QUANTITY-RELATION 前置）的套公式诊断", "错因陷阱": "只做 24 − 5（套'比…短'公式漏'一共'）、认为 19 就是答案（'问题看反'）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——机械套公式诊断迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "题目：'一支钢笔 12 元，比一支铅笔贵 9 元，一支铅笔多少元？'这道题的问题是（　）\nA. 一支铅笔多少元\nB. 一支钢笔多少元\nC. 钢笔比铅笔贵多少元\nD. 钢笔和铅笔一共多少元",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找已知未知",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "题目最后一句'一支铅笔多少元'就是问题",
                "已知：钢笔 12 元、钢笔比铅笔贵 9 元",
                "选 A"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "问题识别的快速检测（'找已知未知'掌握档检测）", "难度理由": "easy 检测——问题定位", "认知阶梯定位": "L2 检测——掌握档快速检测", "错因陷阱": "选 C（把已知的'贵 9 元'当问题——'问题看反'）、选 D（编造'一共'问题）", "教学角色": "掌握档快速检测——问题识别一键探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "下面两道题，哪道条件不够、不能直接解？（　）\n甲题：'图书角有故事书 60 本，科技书比故事书少 15 本，科技书有多少本？'\n乙题：'图书角有故事书和科技书共 60 本，科技书有多少本？'\nA. 甲题缺条件，乙题够\nB. 乙题缺条件（只知总数，不知两书的差或倍数关系），甲题够\nC. 两题都够\nD. 两题都缺条件",
            "expected_answer": "B",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "条件充分性判断",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "甲题：故事书 60、科技书比故事书少 15 → 60 − 15，条件够",
                "乙题：只知共 60，不知道科技书与故事书的关系（差/倍）→ 缺条件",
                "选 B（'漏条件'识别）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "条件充分性对比检测（'漏条件'错因的 hard 检测档）", "难度理由": "hard——两题对比判断哪题缺条件", "认知阶梯定位": "L3 检测 hard——条件完整性的判别取证", "错因陷阱": "选 A（把'共 60'当够——'漏条件'）、选 C（两题都硬算）", "教学角色": "检测 hard 档，判定层 hard 证据来源——条件充分性判别"}
        },
        {
            "slot": "B4-I2",
            "prompt": "题目：'一辆公交车上有 42 人，到站后下去 15 人、上来 8 人（其中 3 人带着行李），现在车上有多少人？'不计算，写出：①哪个信息是无关的 ②等量关系。",
            "expected_answer": "① 无关信息：'其中 3 人带着行李'——带不带行李不影响人数 ② 等量关系：原来的 42 人 − 下去的 15 人 + 上来的 8 人 = 现在的人数，即 42 − 15 + 8 = 现在人数",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "写等量关系",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "筛选信息：'3 人带行李'与人数无关，删掉",
                "找关系：车上人数变化 = 下去减少 + 上来增加",
                "等量关系：42 − 15 + 8 = 现在人数（先读关系再列式）"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "无关信息筛选 + 变化型等量关系（'写等量关系'复测，'把无关信息当条件'错因复测）", "难度理由": "medium 复测——筛选 + 两步变化关系", "认知阶梯定位": "L3 复测——信息筛选与关系提炼防退化", "错因陷阱": "把'3 人带行李'写进关系（'把无关信息当条件'）、增减方向写反", "教学角色": "复测 medium——无关信息与变化关系复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "题目：'果园里桃树和梨树共 120 棵，桃树是梨树的 3 倍少 20 棵，梨树有多少棵？'不计算，完成：①圈出关键词 ②标出已知和未知 ③写出等量关系 ④说出解题路径。",
            "expected_answer": "① 关键词：'共 120 棵''3 倍少 20 棵' ② 已知：桃树 + 梨树 = 120、桃树 = 梨树的 3 倍 − 20；未知：梨树棵数（设梨树 x 棵）③ 等量关系：x + (3x − 20) = 120 ④ 解题路径：设梨树 x 棵 → 桃树 3x − 20 棵 → 列方程 x + (3x − 20) = 120 → 4x = 140 → x = 35 → 检验：35 + (3 × 35 − 20) = 120 ✓",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "写等量关系",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "圈关键词：'共''3 倍少 20 棵'提示和与倍差两个关系",
                "标已知未知：和 120、倍差关系；未知梨树 x 棵",
                "等量关系：x + (3x − 20) = 120",
                "解题路径：设 x → 表示桃树 → 列方程 → 求解 → 代回检验（先说出路径再动笔）"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "综合审题四步复测（关键词/已知未知/等量关系/解题路径，mastery 双标准取证）", "难度理由": "hard——复合'3 倍少 20'关系的完整审题", "认知阶梯定位": "L4 复测——审题流程的最高阶复测", "错因陷阱": "漏'少 20'（'漏条件'）、把'共'写成差、只说计算不说路径", "教学角色": "复测 hard 档——判定层 hard 证据来源，综合审题复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小丽做题：'小明买了 3 支铅笔和 1 个笔记本，一共花了多少钱？'她想了想说：'不能算，因为不知道铅笔和笔记本的单价。'小丽的判断（　）\nA. 对：题目漏掉了单价条件，条件不足不能列式\nB. 不对：应该猜一个价格算\nC. 不对：3 + 1 = 4 元\nD. 对：但可以直接写 3x",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "条件充分性判断",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "总价 = 单价 × 数量，单价未知就无法算总价",
                "题目确实漏条件（'漏条件'错因），不能硬算",
                "选 A"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'漏条件'错因的诊断（能识别条件不足）", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'漏条件'的一键探针", "错因陷阱": "选 C（3 + 1 硬算——'漏条件还硬算'）、选 D（设 x 也缺数据）", "教学角色": "诊断题——条件意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "题目：'哥哥有 30 本书，比弟弟多 8 本，弟弟有多少本？'小明列式 30 + 8 = 38，说'弟弟有 38 本'。他错在哪里？（　）\nA. '哥哥比弟弟多 8 本'说明弟弟少，应 30 − 8 = 22 本；他把'多'的方向看反了\nB. 没错，30 + 8 = 38 是对的\nC. 应该用除法：30 ÷ 8\nD. 应该把 30 和 8 相乘",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "找已知未知",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "读关系：'哥哥比弟弟多 8 本'→ 哥哥 = 弟弟 + 8，所以弟弟 = 30 − 8",
                "小明把'多'当成弟弟多（'问题看反'/关系方向错）",
                "弟弟 22 本，选 A"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'问题看反/关系方向反'错因的诊断（多/少方向）", "难度理由": "medium——定位方向错误并改正", "认知阶梯定位": "L2 诊断——'问题看反'的直接探针", "错因陷阱": "选 B（接受错误结果——'数量关系提炼不出'）、选 C/D（乱套运算）", "教学角色": "诊断题——'多/少方向'审题的一键探针"}
        },
    ],

    # ===== M-BRIDGE-SUM-DIFF-MULTIPLE 和差倍模型（建模计算型：15 unverifiable） =====
    # 节点契约：essence="和差倍题本质是把两个量转成同一个'一倍量'"；
    # seed=和差/和倍/差倍/年龄差不变；common_mistakes=倍数关系写反/没有设一倍量/年龄差不变没抓住；
    # diagnostic_probes=和差/和倍/差倍各1题；mastery=能画线段图/能用算术或方程两种方式解释；
    # prereq=M-PRE-QUANTITY-RELATION、M-PRE-FRACTION-MEANING；unlock=M-G7-EQ-WORD。
    # authoring 原则：全部 unverifiable（建模类，题干不嵌显式算式）；
    # L1 真识别（一倍量识别/和差方向/设份数）；hard 真难（年龄差不变、周长×和倍、差倍复合、三量复合）；
    # 错因逐一布点："没有设一倍量"（B1-I1/B5-I1 诊断）、"倍数关系写反"（B1-I2 方向/B5-I2 诊断）、
    # "年龄差不变没抓住"（B3-I0 引入/B3-I1 迁移）；线段图辅助（B1-I0/B3-I2/B4-I2）。
    "M-BRIDGE-SUM-DIFF-MULTIPLE": [
        {
            "slot": "B1-I0",
            "prompt": "甲筐苹果是乙筐的 2 倍，两筐共 90 千克。①画线段图（乙筐 1 段、甲筐 2 段）②把乙筐看作 1 份，用算术方法求两筐各多少千克。",
            "expected_answer": "线段图：乙筐画 1 段，甲筐画 2 段，共 3 段对应 90 千克。乙筐（1 份）：90 ÷ 3 = 30（千克）；甲筐（2 份）：30 × 2 = 60（千克）。检验：30 + 60 = 90 ✓，60 = 30 × 2 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设一倍量：乙筐是 1 份（一倍量），甲筐是 2 份，共 3 份",
                "画线段图：3 段共 90 千克，每段 = 90 ÷ 3 = 30（千克）",
                "乙筐 30 千克，甲筐 30 × 2 = 60 千克；检验：30 + 60 = 90、60 = 2 × 30 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 5,
            "design_rationale": {"考点": "和倍模型标准例题（设一倍量 + 线段图，essence'把两个量转成同一个一倍量'的演示载体）", "难度理由": "medium 锚点——'设 1 份'思想 + 线段图示范", "认知阶梯定位": "标准例题（L2 套用基准线）", "错因陷阱": "无（锚点题不埋陷阱；答案内嵌线段图与检验示范）", "教学角色": "讲本质用——'一倍量 + 线段图'的演示载体"}
        },
        {
            "slot": "B1-I1",
            "prompt": "题目：'甲数是乙数的 3 倍，两数的和是 48。'这里的'一倍量'（1 份）是（　）\nA. 乙数——把乙数看作 1 份，甲数是 3 份\nB. 甲数——把甲数看作 1 份\nC. 两数的和 48\nD. 甲数比乙数多的部分",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "'甲数是乙数的 3 倍'：乙数是被比较的量，作 1 份（一倍量）",
                "甲数 = 乙数 × 3，是 3 份",
                "选 A（'没有设一倍量'错因的反向训练）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "识别一倍量（'和倍'，'没有设一倍量'错因的直接形态）", "难度理由": "easy——倍关系里谁作 1 份", "认知阶梯定位": "L1 识别正宗实现——'谁是一倍量'的判断", "错因陷阱": "选 B（把'甲是乙的 3 倍'当甲作 1 份——'倍数关系写反'）、选 C（把和当份数）", "教学角色": "L1 识别脚手架——一倍量的第一道判断"}
        },
        {
            "slot": "B1-I2",
            "prompt": "题目：'小明和小红一共有 40 元，小明比小红多 6 元。'下面哪个说法正确？（　）\nA. 设小红 x 元，则小明 (x + 6) 元，等量关系：x + (x + 6) = 40\nB. 小明 = 小红 − 6，两人共 40\nC. 40 ÷ 2 = 20，两人各 20 元\nD. 小明比小红多，所以小明 = 小红 − 6",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和差",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "'小明比小红多 6 元'：小明 = 小红 + 6（方向：多的一方要加）",
                "设小红 x 元，小明 (x + 6) 元；共 40：x + (x + 6) = 40",
                "选 A（B/D 把'多'写成减——'和差关系反'）"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "和差模型中'多/少'方向的识别（'和差'，'和差关系反'错因的直接形态）", "难度理由": "easy——和差方向判断", "认知阶梯定位": "L1 识别——'多的一方 = 少的一方 + 差'", "错因陷阱": "选 B/D（'多'写成减——'和差关系反'）、选 C（忽略差）", "教学角色": "L1 识别脚手架——和差方向的第一道判断"}
        },
        {
            "slot": "B2-I0",
            "prompt": "甲数是乙数的 3 倍，两数的和是 48。把乙数看作 1 份，用算术方法求甲、乙两数。",
            "expected_answer": "乙数 1 份、甲数 3 份，共 4 份对应 48。乙数：48 ÷ 4 = 12；甲数：12 × 3 = 36。检验：12 + 36 = 48 ✓，36 = 12 × 3 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "设一倍量：乙数 1 份、甲数 3 份，共 4 份",
                "每份 = 48 ÷ 4 = 12（乙数）",
                "甲数 = 12 × 3 = 36；检验：12 + 36 = 48、36 = 3 × 12 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "和倍模型直接套用（'和倍'，'设一倍量'标准应用）", "难度理由": "easy 套用——单模型份数计算", "认知阶梯定位": "L2 套用——和倍模型标准应用", "错因陷阱": "48 ÷ 3（把'3 倍'当总份数——'没有设一倍量'）、漏检验", "教学角色": "L2 套用脚手架——和倍'份数除法'的标准形态"}
        },
        {
            "slot": "B2-I1",
            "prompt": "桃树是梨树的 3 倍，桃树比梨树多 24 棵。把梨树看作 1 份，用算术方法求梨树和桃树各多少棵。",
            "expected_answer": "梨树 1 份、桃树 3 份，桃树比梨树多 2 份，2 份对应 24 棵。梨树：24 ÷ 2 = 12（棵）；桃树：12 × 3 = 36（棵）。检验：36 − 12 = 24 ✓，36 = 12 × 3 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "差倍",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "设一倍量：梨树 1 份、桃树 3 份，差 2 份",
                "2 份对应 24 棵：每份 = 24 ÷ 2 = 12（梨树）",
                "桃树 = 12 × 3 = 36 棵；检验：36 − 12 = 24、36 = 3 × 12 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "差倍模型标准应用（'差倍'，差对应份数）", "难度理由": "medium——从和倍切到差倍（差对应份数）", "认知阶梯定位": "L2 套用——差倍模型标准应用", "错因陷阱": "24 ÷ 3（把'3 倍'当差份数——'没有设一倍量'）、差方向反", "教学角色": "差倍套用——'差 = 份数差 × 每份'的标准形态"}
        },
        {
            "slot": "B2-I2",
            "prompt": "两筐苹果共 56 千克，甲筐比乙筐多 12 千克。用算术方法（和 + 差）÷ 2 求两筐各多少千克。",
            "expected_answer": "甲筐（大数）：(和 + 差) ÷ 2 = (56 + 12) ÷ 2 = 68 ÷ 2 = 34（千克）；乙筐：56 − 34 = 22（千克），或 (56 − 12) ÷ 2 = 22（千克）。检验：34 + 22 = 56 ✓，34 − 22 = 12 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "和差模型公式：大数 = (和 + 差) ÷ 2",
                "甲筐 = (56 + 12) ÷ 2 = 34（千克）",
                "乙筐 = 56 − 34 = 22（千克）；检验：34 + 22 = 56、34 − 22 = 12 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "和差模型标准应用（'和差'，(和±差)÷2 公式）", "难度理由": "medium——公式理解 + 两步计算", "认知阶梯定位": "L3 变式——从倍关系切换到差关系模型", "错因陷阱": "(56 − 12) ÷ 2 当大数（'和差关系反'）、68 ÷ 2 算错", "教学角色": "和差套用——大数小数的标准求法"}
        },
        {
            "slot": "B3-I0",
            "prompt": "爸爸比小明大 28 岁，爸爸的年龄是小明的 3 倍。小明和爸爸各多少岁？（提示：28 岁对应小明年龄的几倍？）",
            "expected_answer": "小明 1 份、爸爸 3 份，爸爸比小明多 2 份，2 份对应 28 岁。小明：28 ÷ 2 = 14（岁）；爸爸：14 × 3 = 42（岁）。检验：42 − 14 = 28 ✓，42 = 14 × 3 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "差倍",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "年龄问题先抓住：年龄差固定（这里直接用 28 岁）",
                "小明 1 份、爸爸 3 份，多 2 份对应 28 岁：每份 14 岁（小明）",
                "爸爸 14 × 3 = 42 岁；检验：42 − 14 = 28、42 = 3 × 14 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "差倍模型在年龄情境的应用（'差倍'，为'年龄差不变'做铺垫）", "难度理由": "medium——换年龄情境的差倍", "认知阶梯定位": "L3 变式——差倍模型换情境", "错因陷阱": "28 ÷ 3（把 3 倍当差份数——'没有设一倍量'）、年龄差当和用", "教学角色": "情境变式——差倍在年龄问题中的标准形态"}
        },
        {
            "slot": "B3-I1",
            "prompt": "小明今年 8 岁，爸爸今年 36 岁。几年后爸爸的年龄正好是小明的 3 倍？（用方程解，并说明'年龄差不变'是怎么用的）",
            "expected_answer": "年龄差不变：36 − 8 = 28（岁）。设 x 年后爸爸年龄是小明的 3 倍：那时小明 (8 + x) 岁、爸爸 (36 + x) 岁；列方程 36 + x = 3(8 + x)；展开 36 + x = 24 + 3x；移项 2x = 12，x = 6。检验：6 年后小明 14 岁、爸爸 42 岁，42 = 14 × 3 ✓。答：6 年后。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "年龄差不变",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "年龄差不变：无论过几年，爸爸都比小明大 36 − 8 = 28 岁",
                "设 x 年后：小明 (8 + x) 岁、爸爸 (36 + x) 岁",
                "列方程 36 + x = 3(8 + x)：36 + x = 24 + 3x，2x = 12，x = 6",
                "检验：6 年后 14 岁与 42 岁，42 = 3 × 14 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "年龄差不变模型（'年龄差不变'，'年龄差不变没抓住'错因的正面战场，M-G7-EQ-WORD 列方程预告）", "难度理由": "hard——差不变 × 列方程 × 展开求解三处可错", "认知阶梯定位": "L4 迁移——差倍模型迁移到'几年后'的时间问题", "错因陷阱": "把年龄差当可变（直接用 36 − 8 = 3 份）、3(8 + x) 展开漏乘、移项变号错", "教学角色": "判定层 transfer 证据来源（C3 双角色）——年龄差不变迁移"}
        },
        {
            "slot": "B3-I2",
            "prompt": "一块长方形菜地的周长是 48 米，长是宽的 2 倍。先画线段图表示'宽 1 份、长 2 份'，再求这块菜地的长和宽。",
            "expected_answer": "周长 = (长 + 宽) × 2，所以长 + 宽 = 48 ÷ 2 = 24（米）。线段图：宽 1 段、长 2 段，共 3 段对应 24 米。宽：24 ÷ 3 = 8（米）；长：8 × 2 = 16（米）。检验：周长 = (16 + 8) × 2 = 48 ✓，16 = 8 × 2 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "transfer",
            "solution_steps": [
                "先把周长转成'长 + 宽'：48 ÷ 2 = 24（米）",
                "线段图：宽 1 段、长 2 段共 3 段对应 24 米：宽 = 24 ÷ 3 = 8（米）",
                "长 = 8 × 2 = 16（米）；检验：(16 + 8) × 2 = 48、16 = 2 × 8 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 7,
            "design_rationale": {"考点": "周长公式 × 和倍模型（'和倍'，长方形周长前置运用 + 线段图）", "难度理由": "hard——要先做'周长→长宽和'的转化再套和倍", "认知阶梯定位": "L4 迁移——几何周长（M-PRE-GEO-AREA-VOLUME 前置）× 和倍模型", "错因陷阱": "把 48 直接当'长 + 宽'（漏除以 2）、48 ÷ 3（把周长当 3 份）", "教学角色": "判定层 transfer 证据来源（C3 双角色）——周长×和倍迁移"}
        },
        {
            "slot": "B4-I0",
            "prompt": "学校买来篮球和足球共 60 个，篮球是足球的 2 倍。把足球看作 1 份，求足球和篮球各多少个。",
            "expected_answer": "足球 1 份、篮球 2 份，共 3 份对应 60 个。足球：60 ÷ 3 = 20（个）；篮球：20 × 2 = 40（个）。检验：20 + 40 = 60 ✓，40 = 20 × 2 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L2",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "设一倍量：足球 1 份、篮球 2 份，共 3 份",
                "每份 = 60 ÷ 3 = 20（足球）",
                "篮球 = 20 × 2 = 40（个）；检验：20 + 40 = 60、40 = 2 × 20 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 3,
            "design_rationale": {"考点": "和倍模型检测（'和倍'掌握档快速检测）", "难度理由": "easy 检测——和倍标准形态", "认知阶梯定位": "L2 检测——和倍模型防退化检测", "错因陷阱": "60 ÷ 2（把'2 倍'当份数——'没有设一倍量'）、漏检验", "教学角色": "掌握档快速检测——和倍模型一键探针"}
        },
        {
            "slot": "B4-I1",
            "prompt": "甲数比乙数多 25，甲数比乙数的 2 倍多 5。求甲、乙两数。（用方程或算术）",
            "expected_answer": "设乙数为 x，甲数 = 2x + 5；又甲数 − 乙数 = 25，所以 (2x + 5) − x = 25；x + 5 = 25，x = 20；甲数 = 2 × 20 + 5 = 45。检验：45 − 20 = 25 ✓，45 = 2 × 20 + 5 ✓。答：乙数 20，甲数 45。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "差倍",
            "variant_level": "L3",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "设乙数为 x（一倍量），甲数 = 2x + 5（'2 倍多 5'）",
                "差关系：甲 − 乙 = 25 → (2x + 5) − x = 25 → x + 5 = 25 → x = 20",
                "甲数 = 2 × 20 + 5 = 45；检验：45 − 20 = 25、45 = 2 × 20 + 5 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 6,
            "design_rationale": {"考点": "差倍复合模型检测（'差倍' hard 档：'倍多'复合 × 差关系）", "难度理由": "hard——'2 倍多 5'翻译 + 差关系合并解方程", "认知阶梯定位": "L3 检测 hard——差倍复合取证", "错因陷阱": "列 2x − x = 25 漏'多 5'（'漏条件'）、'2 倍多 5'列反成 2x − 5", "教学角色": "检测 hard 档，判定层 hard 证据来源——差倍复合取证"}
        },
        {
            "slot": "B4-I2",
            "prompt": "两堆货物共 70 吨，第一堆比第二堆多 10 吨。画线段图（第二堆 1 段，第一堆 1 段再多 10 吨），求两堆各多少吨。",
            "expected_answer": "线段图：第二堆 1 段、第一堆 1 段再多 10 吨，两段共 70 吨。先从总数去掉多的 10 吨：(70 − 10) ÷ 2 = 30（吨）→ 第二堆；第一堆：30 + 10 = 40（吨）。检验：40 + 30 = 70 ✓，40 − 30 = 10 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和差",
            "variant_level": "L3",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "画线段图：第二堆 1 段，第一堆 1 段 + 10 吨，两段共 70 吨",
                "去掉多的 10 吨：70 − 10 = 60 是第二堆的 2 倍 → 第二堆 60 ÷ 2 = 30（吨）",
                "第一堆 30 + 10 = 40（吨）；检验：40 + 30 = 70、40 − 30 = 10 ✓"
            ],
            "error_tags": ["modeling_or_reading"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "和差模型线段图复测（'和差'，mastery'能画线段图'取证）", "难度理由": "medium 复测——线段图 + 减差 ÷ 2", "认知阶梯定位": "L3 复测——线段图工具防退化", "错因陷阱": "(70 + 10) ÷ 2 当第二堆（大数小数搞反——'和差关系反'）、漏减差", "教学角色": "复测 medium——线段图和差复测"}
        },
        {
            "slot": "B5-I0",
            "prompt": "甲数是乙数的 2 倍，乙数比丙数多 4，三个数的和是 84。求甲、乙、丙三个数。（提示：把丙数看作 1 份）",
            "expected_answer": "设丙数为 x，乙数 = x + 4，甲数 = 2(x + 4)；三数和：x + (x + 4) + 2(x + 4) = 84；合并：x + x + 4 + 2x + 8 = 84；4x + 12 = 84；4x = 72，x = 18。丙 18，乙 22，甲 44。检验：18 + 22 + 44 = 84 ✓，甲 44 = 2 × 22 ✓，乙 − 丙 = 4 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L4",
            "difficulty": "hard",
            "purpose_role": "core",
            "solution_steps": [
                "设一倍量：丙 x，乙 x + 4，甲 2(x + 4)",
                "列和：x + (x + 4) + 2(x + 4) = 84 → 4x + 12 = 84 → x = 18",
                "丙 18、乙 22、甲 44；检验：和 84、甲 = 2 乙、乙 − 丙 = 4 全满足 ✓"
            ],
            "error_tags": ["modeling_or_reading", "calculation_or_symbol"],
            "estimated_minutes": 8,
            "design_rationale": {"考点": "三量和倍复合复测（'和倍'最高阶：三量 × 倍差复合）", "难度理由": "hard——设 1 份 + 两重关系符号化 + 展开求解", "认知阶梯定位": "L4 复测——和倍模型的最高阶复测", "错因陷阱": "设错一倍量（把乙当 1 份——'没有设一倍量'）、2(x + 4) 展开漏乘、4x = 72 算错", "教学角色": "复测 hard 档——判定层 hard 证据来源，三量和倍复测"}
        },
        {
            "slot": "B5-I1",
            "prompt": "小刚算和倍题：'甲是乙的 3 倍，两数和是 48。'他直接写 48 ÷ 3 = 16，说'乙是 16'。他错在哪里？（　）\nA. 没把乙数设成 1 份：乙 1 份 + 甲 3 份 = 4 份对应 48，乙应是 48 ÷ 4 = 12\nB. 没错，48 ÷ 3 = 16 就是乙\nC. 应该 48 × 3\nD. 应该 48 − 3 = 45",
            "expected_answer": "A",
            "answer_format": "choice",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L1",
            "difficulty": "easy",
            "purpose_role": "core",
            "solution_steps": [
                "和倍题先设一倍量：乙 1 份、甲 3 份，共 4 份",
                "小刚用 48 ÷ 3，把'3 倍'当成总份数，漏了乙自己那份（'没有设一倍量'）",
                "正确：48 ÷ 4 = 12（乙），选 A"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 2,
            "design_rationale": {"考点": "'没有设一倍量'错因的诊断（'和倍'头号错因的一键探针）", "难度理由": "easy——L1 判断", "认知阶梯定位": "L1 诊断——'没有设一倍量'的直接探针", "错因陷阱": "选 B（接受 48 ÷ 3——'没有设一倍量'）、选 C/D（乱套运算）", "教学角色": "诊断题——'设一倍量'意识的一键探针"}
        },
        {
            "slot": "B5-I2",
            "prompt": "小丽说：'甲是乙的 3 倍，所以乙 = 甲 × 3。'她这样写对吗？如果不对，正确的关系是什么？（说明并举例验证）",
            "expected_answer": "不对，倍数关系写反了。'甲是乙的 3 倍'表示甲 = 乙 × 3（乙是 1 份、甲是 3 份），所以乙 = 甲 ÷ 3。举例：设乙 = 10，则甲 = 30；验证 甲 ÷ 3 = 30 ÷ 3 = 10 = 乙 ✓。",
            "answer_format": "text",
            "verification_intent": "unverifiable",
            "question_type": "和倍",
            "variant_level": "L2",
            "difficulty": "medium",
            "purpose_role": "core",
            "solution_steps": [
                "'甲是乙的 3 倍'：甲 = 乙 × 3（一倍量是乙）",
                "小丽写成乙 = 甲 × 3，方向反了（'倍数关系写反'错因）",
                "正确：乙 = 甲 ÷ 3；举例验证：乙 = 10 → 甲 = 30 → 30 ÷ 3 = 10 ✓"
            ],
            "error_tags": ["modeling_or_reading", "concept_confusion"],
            "estimated_minutes": 4,
            "design_rationale": {"考点": "'倍数关系写反'错因的诊断（'和倍'，方向与举例验证）", "难度理由": "medium——指出反写并改正、举例验证", "认知阶梯定位": "L2 诊断——'倍数关系写反'的直接探针", "错因陷阱": "认为'对'（接受乙 = 甲 × 3——'倍数关系写反'）、举例验证错", "教学角色": "诊断题——倍关系方向的一键探针"}
        },
    ],


}

# ---------------------------------------------------------------------------
# 节点注册表（从图谱读 56 节点 + 生成顺序）
# ---------------------------------------------------------------------------


def load_graph() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def build_registry(graph: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    """节点注册表：node_id -> {id, name, stage, priority}（从图谱读全部节点）。"""
    graph = graph if graph is not None else load_graph()
    registry: dict[str, dict[str, str]] = {}
    for node in graph.get("nodes", []):
        node_id = str(node.get("id", ""))
        if not node_id:
            continue
        registry[node_id] = {
            "id": node_id,
            "name": str(node.get("name", "")),
            "stage": str(node.get("stage", "")),
            "priority": str(node.get("priority", "")),
        }
    missing = sorted(set(NODE_QUESTIONS) - set(registry))
    if missing:
        raise ValueError(
            f"NODE_QUESTIONS 含图谱外节点: {missing}（author 前请先在图谱注册）"
        )
    return registry


def generation_order(graph: dict[str, Any] | None = None) -> list[str]:
    """生成顺序：七上主线 P0 → 主线其余 → 小学关键前置 → 衔接桥梁。

    设计稿优先级：七上主线先行（P0 优先），小学前置/衔接桥梁殿后；
    阶段内按 priority P0<P1<P2、再按 id 稳定排序（可复现）。
    """
    registry = build_registry(graph)
    stage_rank = {stage: i for i, stage in enumerate(STAGE_ORDER)}
    priority_rank = {priority: i for i, priority in enumerate(PRIORITY_ORDER)}

    def key(node_id: str) -> tuple[int, int, str]:
        info = registry[node_id]
        return (
            stage_rank.get(info["stage"], len(STAGE_ORDER)),
            priority_rank.get(info["priority"], len(PRIORITY_ORDER)),
            node_id,
        )

    return sorted(registry, key=key)


def select_generation_nodes(
    registry: dict[str, dict[str, str]],
    *,
    node_ids: list[str] | None = None,
    stage: str | None = None,
    all_nodes: bool = False,
) -> tuple[list[str], list[str]]:
    """选择本次生成范围（按注册顺序），返回 (ordered_ids, skipped_not_authored)。

    - node_ids 非空：按给定顺序，校验存在；某节点无 author 题目 → 报错
      （显式点名不应静默跳过）。
    - stage 非空：该阶段全部注册节点（registry 顺序）。
    - all_nodes：全部注册节点（registry 顺序）。
    - 全空：已有 author 题目的节点（与 pilot 行为一致）。
    """
    if node_ids:
        unknown = [nid for nid in node_ids if nid not in registry]
        if unknown:
            raise ValueError(f"未知节点: {unknown}（不在图谱 56 节点中）")
        no_questions = [nid for nid in node_ids if nid not in NODE_QUESTIONS]
        if no_questions:
            raise ValueError(
                f"显式指定节点尚无 author 题目: {no_questions}（NODE_QUESTIONS 未收录；"
                "请用 --stage/--all 查看已 author 节点，或先 author 该节点题目）"
            )
        return list(node_ids), []
    if stage:
        if stage not in STAGE_ORDER:
            raise ValueError(f"未知阶段: {stage}（可选 {STAGE_ORDER}）")
        ids = [nid for nid in generation_order() if registry[nid]["stage"] == stage]
        return _split_authored(ids)
    if all_nodes:
        return _split_authored(generation_order())
    return _split_authored([nid for nid in generation_order() if nid in NODE_QUESTIONS])


def _split_authored(ordered_ids: list[str]) -> tuple[list[str], list[str]]:
    authored = [nid for nid in ordered_ids if nid in NODE_QUESTIONS]
    skipped = [nid for nid in ordered_ids if nid not in NODE_QUESTIONS]
    return authored, skipped


# ---------------------------------------------------------------------------
# 生成器（数据驱动：按槽位读 NODE_QUESTIONS）
# ---------------------------------------------------------------------------


def generate_fn(batch_spec: dict) -> list[dict[str, Any]]:
    """按批规格从 NODE_QUESTIONS 返回本批 3 题（槽位序 = item_index 序）。

    raw 返回字段与 pilot 契约一致（prompt/expected_answer/answer_format/
    question_type/difficulty/solution_steps/design_rationale/
    target_error_tags/estimated_minutes/variant_level/purpose_role），
    管线据此覆写矩阵默认；内部字段（slot/verification_intent）剥离不落库。
    """
    node_id = str(batch_spec["node_id"])
    batch_index = int(batch_spec["batch_index"])
    questions = NODE_QUESTIONS.get(node_id)
    if not questions:
        raise KeyError(
            f"NODE_QUESTIONS 无节点题目: {node_id}（该节点尚未 author——①b 分批任务）"
        )
    out: list[dict[str, Any]] = []
    for item_spec in batch_spec["items"]:
        item_index = int(item_spec["item_index"])
        position = (batch_index - 1) * 3 + item_index
        if position >= len(questions):
            raise KeyError(
                f"节点 {node_id} 缺槽位 B{batch_index}-I{item_index}"
                f"（NODE_QUESTIONS 仅 {len(questions)} 题，须 5 批 × 3 题齐整）"
            )
        raw = dict(questions[position])
        expected_slot = f"B{batch_index}-I{item_index}"
        declared_slot = raw.pop("slot", expected_slot)
        if declared_slot != expected_slot:
            raise AssertionError(
                f"{node_id} 槽位序错乱: 声明 {declared_slot} != 期望 {expected_slot}"
            )
        raw["item_index"] = item_index
        # 内部声明字段不落库
        raw.pop("verification_intent", None)
        # 数据结构的 error_tags → 管线字段 target_error_tags
        if "error_tags" in raw:
            raw["target_error_tags"] = raw.pop("error_tags")
        out.append(raw)
    return out


# ---------------------------------------------------------------------------
# sympy 预检（跑管线前逐题验算：声明 verified 必须 verified，声明
# unverifiable 必须 unverifiable——防止题干措辞意外触发半截提取）
# ---------------------------------------------------------------------------


def preflight_verify(node_ids: list[str] | None = None) -> dict[str, Any]:
    """对（范围内）NODE_QUESTIONS 逐题验算，声明意图与实际 sympy 结论一致。

    这是实现者的硬校验：任何一道题不过 preflight 直接抛错，绝不带着
    未验算的答案进库。
    """
    scope = node_ids if node_ids is not None else sorted(NODE_QUESTIONS)
    summary: dict[str, Any] = {"total": 0, "ok": 0, "failures": []}
    for node_id in scope:
        for position, raw in enumerate(NODE_QUESTIONS.get(node_id, [])):
            verdict = verify_expected_answer(
                str(raw["prompt"]), str(raw["expected_answer"])
            )["verdict"]
            expected = str(raw.get("verification_intent", "unverifiable"))
            summary["total"] += 1
            if verdict != expected:
                summary["failures"].append(
                    {
                        "key": [node_id, raw.get("slot", f"pos{position}")],
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
            f"preflight 校验失败 {len(summary['failures'])} 题（声明意图 vs 实际结论）："
            + json.dumps(summary["failures"], ensure_ascii=False, indent=2)
        )
    return summary


# ---------------------------------------------------------------------------
# 审查钩子（--review）：节点级规则审查 + 全库汇总 + 琢玉接入位
# ---------------------------------------------------------------------------


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _row_by_id(rows: list[sqlite3.Row], question_id: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row["id"]) == question_id:
            return _row_dict(row)
    return None


def _contract_matrix_specs(node_id: str) -> dict[tuple[int, int], dict[str, str]]:
    """用 qg 批规格还原矩阵槽位（variant_level/purpose_role 声明一致性基准）。"""
    specs: dict[tuple[int, int], dict[str, str]] = {}
    for batch_spec in qg.node_batch_specs(load_graph(), node_id):
        for item_spec in batch_spec["items"]:
            specs[(int(batch_spec["batch_index"]), int(item_spec["item_index"]))] = {
                "variant_level": str(item_spec["variant_level"]),
                "purpose_role": str(item_spec["purpose_role"]),
                "kind": str(item_spec["kind"]),
            }
    return specs


def check_node_quality(
    node_id: str, build: dict[str, Any], conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """节点级规则审查：pilot 两节点沿用琢玉 P0/P1/P2 断言 + 通用结构断言。

    通用（对所有节点生效）：
    - 契约 valid（≥2 指纹 / ≥1 transfer / 难度分布 / 无 mismatch /
      design_rationale 含考点）；
    - 每题 design_rationale 五要素全齐；
    - trivial 抽检为零（契约 §4.2 难度底线：琐碎题审查打回）；
    - NODE_QUESTIONS 声明 variant_level/purpose_role 与矩阵槽位一致
      （防 authoring 漂移破坏判定层矩阵设计）。

    pilot 节点专属（琢玉报告 P0/P1/P2，见模块常量注释）：
    - P0#1 零槽位概念判断 + POS-NEG 无算术题；
    - P0#2 答案形式明确（DECIMAL B2-I2/B4-I2）；
    - P0#3 除数小数覆盖 + '为什么移动小数点'解释；
    - P1#4 降档题 medium + hard 仅剩标杆；
    - P1#5 POS-NEG transfer 真迁移；
    - P2#8 question_type 标签一致；P2#9 error_tags 贴切；
    - P1#6 '记作'模板压缩（温度×1、收支×1）。

    返回 {"ok": bool, "errors": [str]}。conn 为 None 时按 build["db_path"]
    新开连接（供提交后复查）；构建中传入同一连接以读未提交数据。
    """
    errors: list[str] = []
    close_conn = conn is None
    conn = conn or db.connect(build["db_path"])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select * from question_items where node_id = ?", (node_id,)
        ).fetchall()

        # ---- 通用：契约 valid ----
        contract = (build.get("contracts") or {}).get(node_id) or {}
        if not contract.get("valid"):
            errors.append(f"{node_id} 契约校验未通过: {contract.get('errors')}")

        # ---- 通用：design_rationale 五要素全齐 ----
        for row in rows:
            rationale_raw = str(row["design_rationale_json"] or "")
            try:
                rationale = json.loads(rationale_raw) if rationale_raw else {}
            except ValueError:
                rationale = {}
            missing = [
                key
                for key in ("考点", "难度理由", "认知阶梯定位", "错因陷阱", "教学角色")
                if not str((rationale or {}).get(key) or "").strip()
            ]
            if missing:
                errors.append(f"{row['id']} design_rationale 缺要素 {missing}（五要素必填）")

        # ---- 通用：trivial 抽检为零 ----
        trivial_count = contract.get("trivial_question_count")
        if trivial_count is None:
            errors.append(f"{node_id} 契约报告缺失 trivial_question_count")
        elif trivial_count != 0:
            errors.append(
                f"{node_id} 存在琐碎题抽检警告 {trivial_count} 条"
                f"（{contract.get('trivial_warnings')}）——契约 §4.2 琐碎题打回"
            )

        # ---- 通用：声明与矩阵槽位一致（variant_level/purpose_role） ----
        matrix_specs = _contract_matrix_specs(node_id)
        for position, q in enumerate(NODE_QUESTIONS.get(node_id, [])):
            batch_index = position // 3 + 1
            item_index = position % 3
            expected = matrix_specs.get((batch_index, item_index))
            if expected is None:
                continue
            for field in ("variant_level", "purpose_role"):
                declared = str(q.get(field) or "")
                if declared and declared != expected[field]:
                    errors.append(
                        f"{node_id} {q.get('slot', position)} 声明 {field}={declared}"
                        f" 与矩阵槽位 {expected[field]} 不一致"
                    )

        # ---- pilot 节点专属断言 ----
        if node_id == "M-G7-POS-NEG":
            # P0#1：零槽位概念判断 + 全节点无算术题
            for question_id in ZERO_SLOT_QUESTION_IDS:
                row = _row_by_id(rows, question_id)
                if row is None:
                    errors.append(f"零槽位题缺失: {question_id}")
                    continue
                if row["answer_format"] != "choice":
                    errors.append(
                        f"零槽位 {question_id} 应为概念判断题（choice），"
                        f"实际 {row['answer_format']}"
                    )
                if "计算" in str(row["prompt"]):
                    errors.append(f"零槽位 {question_id} 出现'计算'字样，疑似算术题")
            for row in rows:
                if str(row["answer_format"]) not in {"choice", "text"}:
                    errors.append(
                        f"POS-NEG 出现算术题 {row['id']}（answer_format={row['answer_format']}），"
                        "概念节点不应有算术题（审查 P0#1）"
                    )
            # P1#5：transfer 真迁移（B3-I1 混合有理数分类）
            b3i1 = _row_by_id(rows, "Q-M-G7-POS-NEG-B3-I1")
            if b3i1 is None:
                errors.append("POS-NEG B3-I1 缺失（真迁移题，P1#5）")
            else:
                if b3i1["purpose_role"] != "transfer":
                    errors.append(
                        f"POS-NEG B3-I1 应保持 purpose_role=transfer，实际 {b3i1['purpose_role']}"
                    )
                if not re.search(r"负数有", str(b3i1["prompt"])):
                    errors.append("POS-NEG B3-I1 未体现真迁移（负数识别×分类）")
            # P2#9：error_tags 贴切（温度/收支去 visual_spatial，电梯/数轴保留）
            for question_id, label in ERROR_TAGS_NO_SPATIAL:
                row = _row_by_id(rows, question_id)
                if row is None:
                    errors.append(f"error_tags 检查目标缺失: {question_id}")
                    continue
                tags = json.loads(str(row["error_tags_json"]))
                if "visual_spatial" in tags:
                    errors.append(f"{label} {question_id} 不应含 visual_spatial（P2#9）")
            for question_id, label in ERROR_TAGS_KEEP_SPATIAL:
                row = _row_by_id(rows, question_id)
                if row is None:
                    errors.append(f"error_tags 检查目标缺失: {question_id}")
                    continue
                tags = json.loads(str(row["error_tags_json"]))
                if "visual_spatial" not in tags:
                    errors.append(f"{label} {question_id} 应保留 visual_spatial（P2#9）")
            # P1#6：'记作'模板压缩（温度×1、收支×1）
            prompts = [str(r["prompt"]) for r in rows]
            temperature = [p for p in prompts if "℃" in p and "记作" in p]
            finance = [
                p for p in prompts if ("收入" in p or "支出" in p or "元" in p) and "记作" in p
            ]
            if len(temperature) != 1:
                errors.append(f"温度'记作'模板应压缩为 1 题（P1#6），实际 {len(temperature)}")
            if len(finance) != 1:
                errors.append(f"收支'记作'模板应压缩为 1 题（P1#6），实际 {len(finance)}")

        elif node_id == "M-PRE-DECIMAL-OPS":
            # P0#2：答案形式明确
            b2i2 = _row_by_id(rows, "Q-M-PRE-DECIMAL-OPS-B2-I2")
            b4i2 = _row_by_id(rows, "Q-M-PRE-DECIMAL-OPS-B4-I2")
            if b2i2 is None or "用小数表示" not in str(b2i2["prompt"]):
                errors.append("DECIMAL B2-I2 未注明答案形式'用小数表示'（P0#2）")
            if b4i2 is None or "用分数表示" not in str(b4i2["prompt"]):
                errors.append("DECIMAL B4-I2 未注明答案形式'用分数表示'（P0#2）")
            # P0#3：除数小数覆盖 + 移动小数点解释
            divisor_decimal = [
                r for r in rows if re.search(r"÷\s*0\.", str(r["prompt"]))
            ]
            if not divisor_decimal:
                errors.append("DECIMAL 缺少'除数是小数'覆盖（P0#3，应有 ÷0.x 题）")
            b2i0 = _row_by_id(rows, "Q-M-PRE-DECIMAL-OPS-B2-I0")
            if b2i0 is not None:
                steps = str(b2i0["solution_steps_json"])
                if not re.search(r"同时", steps) or not re.search(r"商不变|扩大", steps):
                    errors.append(
                        "DECIMAL B2-I0 的 solution_steps 缺少'为什么移动小数点'解释"
                        "（同时扩倍/商不变，P0#3）"
                    )
            else:
                errors.append("DECIMAL B2-I0 缺失（标准除数小数题，P0#3）")

        if node_id in PILOT_NODE_IDS:
            # P1#4：降档题 medium + hard 仅剩标杆
            for question_id in DOWNGRADED_QUESTION_IDS:
                if not question_id.startswith(f"Q-{node_id}-"):
                    continue
                row = _row_by_id(rows, question_id)
                if row is None:
                    errors.append(f"降档题缺失: {question_id}")
                elif row["difficulty"] != "medium":
                    errors.append(
                        f"{question_id} 难度应诚实降为 medium（P1#4），实际 {row['difficulty']}"
                    )
            hard_ids = {str(r["id"]) for r in rows if r["difficulty"] == "hard"}
            expected_hard = HARD_BENCHMARK_IDS[node_id]
            if hard_ids != expected_hard:
                errors.append(
                    f"{node_id} hard 题应仅剩审查标杆 {sorted(expected_hard)}，"
                    f"实际 {sorted(hard_ids)}"
                )
            # P2#8：question_type 标签一致（抽查关键槽位）
            for question_id, expected_type in QUESTION_TYPE_EXPECTATIONS.items():
                if not question_id.startswith(f"Q-{node_id}-"):
                    continue
                row = _row_by_id(rows, question_id)
                if row is None:
                    errors.append(f"标签一致性检查目标缺失: {question_id}")
                elif str(row["question_type"]) != expected_type:
                    errors.append(
                        f"{question_id} question_type 应为 {expected_type}，"
                        f"实际 {row['question_type']}"
                    )
    finally:
        if close_conn:
            conn.close()
    return {"ok": not errors, "errors": errors}


# 真实琢玉逐题 LLM 审查接入位（objective ② / ①b）：
# 替换为 fn(build) -> {"ok": bool, "errors": [str]}（整库复查）；
# 管线级逐批审查经 build_bank(reviewer_fn=...) 注入 generate_node_bank 的
# 教研审查门禁。当前 None = 不启用，由规则审查兜底。
PEDAGOGY_REVIEW_HOOK: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def check_full_bank_quality(build: dict[str, Any]) -> dict[str, Any]:
    """全库规则审查：汇总各节点规则审查 + 契约 valid + 琢玉接入位。"""
    errors: list[str] = []
    per_node = build.get("review", {}).get("per_node") or {}
    for node_id, node_review in per_node.items():
        if not node_review.get("ok"):
            errors.append(
                f"{node_id} 节点规则审查未通过: {node_review.get('errors')}"
            )
    for node_id, contract in (build.get("contracts") or {}).items():
        if not contract.get("valid"):
            errors.append(f"{node_id} 契约校验未通过: {contract.get('errors')}")
    if PEDAGOGY_REVIEW_HOOK is not None:
        result = PEDAGOGY_REVIEW_HOOK(build)
        if not result.get("ok"):
            errors.extend(f"琢玉审查: {e}" for e in result.get("errors", []))
    return {"ok": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# 管线串联（build_bank）
# ---------------------------------------------------------------------------


def build_bank(
    db_path: Path | str = BANK_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
    commit: bool = True,
    graph: dict[str, Any] | None = None,
    node_ids: list[str] | None = None,
    review: bool = False,
    review_mark: bool = False,
    reviewer_fn: Callable[[dict, list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """init_schema + seed 图谱 + 逐节点 generate_node_bank（数据驱动题目）
    → 契约校验 → （--review）节点级规则审查 → 全库审查 → 提交。

    红线（提交前 fail-fast，不入库残留）：
    - preflight sympy 校验失败；
    - 契约校验不通过（结构完整性）；
    - review=True 且规则审查不通过（除非 review_mark=True → 只标记，
      失败进 build["review"]，不中止）。

    返回 build: {db_path, scope, results, contracts, review?, errors}。
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    graph = graph if graph is not None else load_graph()
    registry = build_registry(graph)

    if node_ids is None:
        node_ids, _skipped = select_generation_nodes(registry)
    if not node_ids:
        raise ValueError("本次生成范围为空（所选节点均无 author 题目）")
    unknown = [nid for nid in node_ids if nid not in registry]
    if unknown:
        raise ValueError(f"未知节点: {unknown}")
    no_questions = [nid for nid in node_ids if nid not in NODE_QUESTIONS]
    if no_questions:
        raise ValueError(f"所选节点无 author 题目: {no_questions}（NODE_QUESTIONS 未收录）")

    preflight_verify(node_ids)

    conn: sqlite3.Connection = db.connect(db_path)
    try:
        db.init_schema(conn)
        db.seed_from_assets(conn, project_root)
        results: dict[str, Any] = {}
        contracts: dict[str, Any] = {}
        per_node_review: dict[str, Any] = {}
        build = {"db_path": str(db_path.resolve()), "results": results,
                 "contracts": contracts}
        for node_id in node_ids:
            results[node_id] = qg.generate_node_bank(
                conn,
                node_id,
                generate_fn=generate_fn,
                graph=graph,
                commit=False,
                reviewer_fn=reviewer_fn,
            )
            contracts[node_id] = qg.validate_node_bank_contract(conn, node_id)
            if not contracts[node_id]["valid"]:
                raise AssertionError(
                    f"{node_id} 契约校验未通过（提交前 fail-fast）：\n- "
                    + "\n- ".join(contracts[node_id]["errors"])
                )
            if review:
                node_review = check_node_quality(node_id, build, conn=conn)
                per_node_review[node_id] = node_review
                if not node_review["ok"] and not review_mark:
                    raise AssertionError(
                        f"{node_id} 节点规则审查未通过（fail-fast；--review-mark "
                        f"可改为只标记）：\n- " + "\n- ".join(node_review["errors"])
                    )
        build["review"] = {
            "enabled": review,
            "marked": review_mark,
            "per_node": per_node_review,
        }
        if review:
            build["review"]["full_bank"] = check_full_bank_quality(build)
        if commit:
            conn.commit()
        return build
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _summarize(build: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "nodes_generated": len(build["results"]),
        "total_questions": 0,
        "difficulty_totals": {},
        "verified_total": 0,
        "unverifiable_total": 0,
        "mismatch_discarded_total": 0,
        "contract_valid_nodes": 0,
        "trivial_warnings_total": 0,
    }
    for node_id, stats in build["results"].items():
        summary["total_questions"] += int(stats["ingested"])
        summary["verified_total"] += int(stats["verified"])
        summary["unverifiable_total"] += int(stats["unverifiable"])
        summary["mismatch_discarded_total"] += int(stats["mismatch_discarded"])
        contract = (build.get("contracts") or {}).get(node_id) or {}
        if contract.get("valid"):
            summary["contract_valid_nodes"] += 1
        summary["trivial_warnings_total"] += int(contract.get("trivial_question_count") or 0)
        for difficulty, count in (contract.get("difficulty_counts") or {}).items():
            summary["difficulty_totals"][difficulty] = (
                summary["difficulty_totals"].get(difficulty, 0) + int(count)
            )
    return summary


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
        node_review = build.get("review", {}).get("per_node", {}).get(node_id)
        if node_review is not None:
            print(f"  规则审查: ok={node_review['ok']}")
            for error in node_review["errors"]:
                print(f"  REVIEW-ERROR: {error}")
    review = build.get("review") or {}
    if review.get("enabled"):
        full_bank = review.get("full_bank") or {}
        print(f"\n全库规则审查: ok={full_bank.get('ok')}")
        for error in full_bank.get("errors", []):
            print(f"  FULLBANK-ERROR: {error}")
    summary = _summarize(build)
    print("\n全库汇总:")
    print(
        f"  节点数={summary['nodes_generated']} 总题数={summary['total_questions']} "
        f"难度分布={summary['difficulty_totals']}"
    )
    print(
        f"  verified={summary['verified_total']} unverifiable={summary['unverifiable_total']} "
        f"mismatch_discarded={summary['mismatch_discarded_total']} "
        f"契约valid节点={summary['contract_valid_nodes']} "
        f"trivial警告={summary['trivial_warnings_total']}"
    )


def _write_json_report(build: dict[str, Any], path: Path | str) -> None:
    scope_info = build.get("scope") or {}
    payload: dict[str, Any] = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "db_path": build["db_path"],
        "scope": scope_info,
        "nodes": {},
        "summary": _summarize(build),
        "review": build.get("review"),
    }
    for node_id, stats in build["results"].items():
        contract = build["contracts"][node_id]
        node_entry: dict[str, Any] = {"stats": stats, "contract": contract}
        node_review = build.get("review", {}).get("per_node", {}).get(node_id)
        if node_review is not None:
            node_entry["review"] = node_review
        payload["nodes"][node_id] = node_entry
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 迁移一致性检查（--check-migration）：与 pilot 脚本 30 题逐字比对
# ---------------------------------------------------------------------------


def check_migration_against_pilot() -> dict[str, Any]:
    """源级比对：NODE_QUESTIONS 与 pilot._QUESTIONS 内容字段逐字一致。

    比对字段：prompt/expected_answer/answer_format/question_type/
    solution_steps/design_rationale/verification_intent（pilot 作者字段），
    以及 pilot 显式声明的 difficulty/target_error_tags（其余难度/错因标签
    由矩阵/派生决定，库级回归另行验证）。返回 {ok, mismatches}。
    """
    from scripts import pilot_generate_semester_bank as pilot  # noqa: F401

    mismatches: list[str] = []
    for (node_id, batch_index, item_index), pilot_raw in sorted(pilot._QUESTIONS.items()):
        position = (batch_index - 1) * 3 + item_index
        mine = NODE_QUESTIONS[node_id][position]
        slot = f"B{batch_index}-I{item_index}"
        content_fields = (
            "prompt", "expected_answer", "answer_format", "question_type",
            "solution_steps", "design_rationale", "verification_intent",
        )
        for field in content_fields:
            if mine.get(field) != pilot_raw.get(field):
                mismatches.append(
                    f"{node_id} {slot} 字段 {field} 不一致"
                )
        if "difficulty" in pilot_raw and mine.get("difficulty") != pilot_raw["difficulty"]:
            mismatches.append(f"{node_id} {slot} 难度不一致（pilot 显式 {pilot_raw['difficulty']}）")
        if "target_error_tags" in pilot_raw and mine.get("error_tags") != pilot_raw["target_error_tags"]:
            mismatches.append(f"{node_id} {slot} error_tags 不一致（pilot 显式 {pilot_raw['target_error_tags']}）")
    return {"ok": not mismatches, "mismatches": mismatches, "total": len(pilot._QUESTIONS)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="数据驱动全量题库生成框架（objective ①a；56 节点注册表 + NODE_QUESTIONS 题目数据）"
    )
    parser.add_argument("--db", default=str(BANK_PATH), help="目标 sqlite 路径")
    parser.add_argument("--nodes", help="逗号分隔节点 id（按给定顺序；须已 author 题目）")
    parser.add_argument("--stage", choices=STAGE_ORDER, help="按阶段选择（七上主线/小学关键前置/衔接桥梁）")
    parser.add_argument("--all", action="store_true", help="全部注册节点（跳过未 author 节点）")
    parser.add_argument("--review", action="store_true", help="运行规则审查（节点级 + 全库）")
    parser.add_argument("--review-mark", action="store_true",
                        help="审查不通过只标记（进报告），不 fail-fast")
    parser.add_argument("--preflight-only", action="store_true", help="只做 sympy 预检，不入库")
    parser.add_argument("--report", help="额外输出 JSON 报告到该路径")
    parser.add_argument("--check-migration", action="store_true",
                        help="与 pilot 脚本 30 题逐字比对（源级），不生成题库")
    args = parser.parse_args(argv)

    if args.check_migration:
        result = check_migration_against_pilot()
        if result["ok"]:
            print(f"迁移一致性: OK（{result['total']} 题与 pilot 逐字一致）")
            return 0
        print(f"迁移一致性: 失败（{len(result['mismatches'])} 处不一致）", file=sys.stderr)
        for mismatch in result["mismatches"]:
            print(f"  MISMATCH: {mismatch}", file=sys.stderr)
        return 1

    if args.preflight_only:
        scope, _skipped = _resolve_scope_args(args)
        summary = preflight_verify(scope)
        print(f"preflight 通过: {summary['ok']}/{summary['total']} 题与声明门禁意图一致")
        return 0

    graph = load_graph()
    registry = build_registry(graph)
    try:
        node_ids, skipped = _resolve_scope_args(args, registry=registry)
        build = build_bank(
            args.db,
            graph=graph,
            node_ids=node_ids,
            review=args.review,
            review_mark=args.review_mark,
        )
    except (ValueError, AssertionError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    build["scope"] = {
        "nodes": node_ids,
        "skipped_not_authored": skipped,
    }
    _print_report(build)
    if skipped:
        print(
            f"\n跳过未 author 节点 {len(skipped)} 个（NODE_QUESTIONS 未收录，①b 分批 author）："
            f" {', '.join(skipped)}"
        )
    if args.report:
        _write_json_report(build, args.report)
        print(f"\nJSON 报告: {args.report}")

    failed = False
    for contract in build["contracts"].values():
        if not contract["valid"]:
            failed = True
    if args.review and not (build.get("review", {}).get("full_bank") or {}).get("ok"):
        failed = True
    if failed:
        print("\n本次生成存在未通过项（见上方 ERROR/REVIEW-ERROR）！", file=sys.stderr)
        return 1
    print("\n本次生成全部通过。")
    return 0


def _resolve_scope_args(
    args: argparse.Namespace, registry: dict[str, dict[str, str]] | None = None
) -> tuple[list[str], list[str]]:
    registry = registry if registry is not None else build_registry()
    if args.nodes:
        node_ids = [nid.strip() for nid in args.nodes.split(",") if nid.strip()]
        return select_generation_nodes(registry, node_ids=node_ids)
    if args.stage:
        return select_generation_nodes(registry, stage=args.stage)
    if args.all:
        return select_generation_nodes(registry, all_nodes=True)
    return select_generation_nodes(registry)


if __name__ == "__main__":
    sys.exit(main())
