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
