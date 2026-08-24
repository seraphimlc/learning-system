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
