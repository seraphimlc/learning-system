#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_PATH = ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"
GRAPH_PATH = ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
SAMPLE_PATH = ROOT / "data/question_banks/v18/math_v18_sample_60.json"

BANK_VERSION = "2026-07-22.bank.v18.sample-60"
MANIFEST_ID = "math_question_bank_v18_sample_60"
CONTRACT_VERSION = "2026-07-22.question-production.v18.sample"


SAMPLE_SPECS: dict[str, list[dict[str, Any]]] = {
    "M-PRE-DECIMAL-OPS": [
        {
            "family_id": "estimate_direction_and_magnitude",
            "level": "L3",
            "prompt": "49.8×20.4 和 1000 相比，是大一些还是小一些？先用 50×20 作基准说明方向，再给出精算验证。",
            "answer": "比1000大。49.8比50少0.2会少约20×0.2=4，20.4比20多0.4会多约50×0.4=20，合起来约多16；精算49.8×20.4=1015.92。",
            "steps": ["用50×20=1000作基准。", "分别判断两个偏差对乘积的影响方向。", "精算验证1015.92。"],
        },
        {
            "family_id": "structure_based_simplification",
            "level": "L3",
            "prompt": "计算 2.5×3.2×1.25。不要硬算，写出你怎样拆数凑整。",
            "answer": "3.2=4×0.8，2.5×4=10，1.25×0.8=1，所以原式=10。",
            "steps": ["把3.2拆成4×0.8。", "配对2.5×4和1.25×0.8。", "得到10×1=10。"],
        },
        {
            "family_id": "decimal_place_value_ops",
            "level": "L3",
            "prompt": "不用直接竖式，说明 4.8÷0.6 为什么可以变成 48÷6，并算出结果。",
            "answer": "被除数和除数同时扩大10倍，商不变，所以4.8÷0.6=48÷6=8。",
            "steps": ["说明同时扩大10倍。", "商不变。", "计算48÷6=8。"],
        },
        {
            "family_id": "wrong_solution_repair_number",
            "level": "L3",
            "prompt": "同学把 12.5×0.32 算成 40。请找出小数点哪里错了，并给出正确结果。",
            "answer": "12.5×0.32=12.5×32÷100=400÷100=4。错在把小数点少向左移动一位。",
            "steps": ["先算12.5×32=400。", "因为0.32=32÷100，所以除以100。", "正确结果是4。"],
        },
        {
            "family_id": "structure_based_simplification",
            "level": "L4",
            "prompt": "计算 0.25×39.6+0.25×0.4。先观察结构，不要分开硬算。",
            "answer": "提取0.25，原式=0.25×(39.6+0.4)=0.25×40=10。",
            "steps": ["发现相同因数0.25。", "用分配律反向提取。", "39.6+0.4凑成40。"],
        },
        {
            "family_id": "decimal_place_value_ops",
            "level": "L4",
            "prompt": "0.375+3/8 等于多少？请说明你选择把谁转成谁，为什么这样更稳。",
            "answer": "0.375=375/1000=3/8，所以0.375+3/8=3/8+3/8=3/4=0.75。",
            "steps": ["识别0.375等于3/8。", "统一成分数更稳。", "相加得到3/4，也就是0.75。"],
            "extra_rollback": ["M-PRE-FRACTION-MEANING", "M-PRE-FRACTION-OPS"],
        },
    ],
    "M-G7-RATIONAL-ADD-SUB": [
        {
            "family_id": "signed_operation_model",
            "level": "L3",
            "prompt": "计算 -7+3，并说明为什么结果仍然是负数。",
            "answer": "负方向7个单位和正方向3个单位抵消后还剩负方向4个单位，所以-7+3=-4。",
            "steps": ["异号相加先比较绝对值。", "7比3大，符号取负。", "绝对值相减得4。"],
        },
        {
            "family_id": "signed_operation_model",
            "level": "L3",
            "prompt": "计算 4-(-6)。请先把减法改写成加法，再计算。",
            "answer": "减去一个数等于加它的相反数，所以4-(-6)=4+6=10。",
            "steps": ["把-(-6)理解为加6。", "改写成4+6。", "结果是10。"],
        },
        {
            "family_id": "signed_operation_model",
            "level": "L4",
            "prompt": "计算 -2.5+1.8-3.5。请写出一种让符号更不容易错的分组。",
            "answer": "可以把负数合并：(-2.5-3.5)+1.8=-6+1.8=-4.2。",
            "steps": ["先把同为负的项合并。", "得到-6+1.8。", "异号相加得-4.2。"],
        },
        {
            "family_id": "wrong_solution_repair_number",
            "level": "L3",
            "prompt": "错解：-5-2=3。请指出第一处错在哪里，并给出正确结果。",
            "answer": "-5-2表示从-5再向左2个单位，不是抵消，所以结果是-7。错在把减2当成加2。",
            "steps": ["识别减2的方向是向左。", "不能把两个负号随意抵消。", "正确结果-7。"],
        },
        {
            "family_id": "number_line_position_distance",
            "level": "L4",
            "prompt": "温度从 -3℃ 上升 5℃，又下降 8℃。最后是多少？请用一个有理数加减式表示。",
            "answer": "式子是-3+5-8。先得2，再下降8得-6，所以最后是-6℃。",
            "steps": ["上升写加5，下降写减8。", "按顺序计算。", "结果带单位。"],
        },
        {
            "family_id": "solution_trace_repair",
            "level": "L3",
            "prompt": "补全关键步骤：-9+□=-2。请写出□是多少，并说明你怎样检查。",
            "answer": "□=7，因为-9+7=-2。也可以想从-9走到-2，需要向右7个单位。",
            "steps": ["把未知数看成需要补的变化量。", "从-9到-2是向右7。", "代回检查。"],
        },
    ],
    "M-PRE-LETTER-EXPR": [
        {
            "family_id": "verbal_to_expression",
            "level": "L3",
            "prompt": "一本笔记本 a 元，一支笔 b 元。买3本笔记本和2支笔共多少钱？请写代数式，并说明 a、b 分别表示什么。",
            "answer": "代数式是3a+2b。a表示一本笔记本的价格，b表示一支笔的价格。",
            "steps": ["先定义字母含义。", "3本笔记本是3a。", "2支笔是2b，总价相加。"],
        },
        {
            "family_id": "verbal_to_expression",
            "level": "L3",
            "prompt": "长方形长为 x+3，宽为 x。请写出周长的代数式，并尽量化简。",
            "answer": "周长=2[(x+3)+x]=4x+6。",
            "steps": ["周长是长宽和的2倍。", "代入长x+3、宽x。", "化简得4x+6。"],
        },
        {
            "family_id": "verbal_to_expression",
            "level": "L4",
            "prompt": "连续三个奇数，中间一个是 2n+1。请写出另外两个数，并写出它们的和。",
            "answer": "另外两个是2n-1和2n+3，三数和为(2n-1)+(2n+1)+(2n+3)=6n+3。",
            "steps": ["连续奇数相差2。", "从中间数向前后各移2。", "三项相加化简。"],
        },
        {
            "family_id": "expression_value_substitution",
            "level": "L3",
            "prompt": "当 x=-2 时，求 3x+5 的值。注意负数代入时要不要加括号。",
            "answer": "3x+5=3×(-2)+5=-6+5=-1。",
            "steps": ["把x替换成-2。", "负数代入乘法时写括号更清楚。", "计算得到-1。"],
        },
        {
            "family_id": "equivalent_expression_judgement",
            "level": "L4",
            "prompt": "判断 2(n+3) 和 2n+6 是否总相等。请不要只代一个数，要说明理由。",
            "answer": "总相等，因为2(n+3)=2n+6，这是乘法分配律。",
            "steps": ["展开左边。", "得到2n+6。", "与右边一致，所以恒等。"],
        },
        {
            "family_id": "solution_trace_repair",
            "level": "L3",
            "prompt": "错写：比 m 少5的数的3倍写成 3m-5。请改正，并说明错在哪里。",
            "answer": "应写成3(m-5)。错在3倍作用的是整个“比m少5的数”，不是只作用在m上。",
            "steps": ["先把“比m少5的数”写成m-5。", "再整体乘3。", "用括号保护整体。"],
        },
    ],
    "M-G7-POLY-ADD-SUB": [
        {
            "family_id": "parenthesis_and_polynomial_repair",
            "level": "L3",
            "prompt": "化简：(3x-2)-(x+5)。请特别注意减去括号时每一项的符号。",
            "answer": "(3x-2)-(x+5)=3x-2-x-5=2x-7。",
            "steps": ["减去括号内每一项都要变号。", "3x-x=2x。", "-2-5=-7。"],
        },
        {
            "family_id": "parenthesis_and_polynomial_repair",
            "level": "L3",
            "prompt": "化简 2(a-3)+4a，并说明括号里的每一项如何处理。",
            "answer": "2(a-3)+4a=2a-6+4a=6a-6。",
            "steps": ["2同时乘a和-3。", "得到2a-6+4a。", "合并同类项。"],
        },
        {
            "family_id": "parenthesis_and_polynomial_repair",
            "level": "L3",
            "prompt": "错解：5x-(2x-1)=3x-1。请找出错误并改正。",
            "answer": "减去(2x-1)时，-1也要变号，所以5x-(2x-1)=5x-2x+1=3x+1。",
            "steps": ["括号前是减号。", "括号内每项都变号。", "正确结果3x+1。"],
        },
        {
            "family_id": "verbal_to_expression",
            "level": "L4",
            "prompt": "一个长方形长为 3x-1，宽为 x+2。请写出周长并化简。",
            "answer": "周长=2[(3x-1)+(x+2)]=2(4x+1)=8x+2。",
            "steps": ["写出周长关系。", "括号内先合并。", "乘2得到8x+2。"],
        },
        {
            "family_id": "like_terms_boundary",
            "level": "L3",
            "prompt": "化简 2x^2-3x+4x^2+x-5。请先圈出哪些是同类项。",
            "answer": "2x^2和4x^2同类，-3x和x同类，所以结果是6x^2-2x-5。",
            "steps": ["按字母和指数分类。", "分别合并系数。", "常数项保留。"],
        },
        {
            "family_id": "equivalent_expression_judgement",
            "level": "L4",
            "prompt": "判断 (x+2)+(3x-5) 和 4x-3 是否总相等。请给出化简理由。",
            "answer": "相等，因为(x+2)+(3x-5)=x+3x+2-5=4x-3。",
            "steps": ["去括号。", "合并同类项。", "与4x-3比较。"],
        },
    ],
    "M-G7-EQ-SOLVE": [
        {
            "family_id": "linear_equation_solving_flow",
            "level": "L3",
            "prompt": "解方程 3x+5=20，并代回检验。",
            "answer": "3x=15，x=5。代回3×5+5=20，成立。",
            "steps": ["两边减5。", "两边除以3。", "代回检验。"],
        },
        {
            "family_id": "linear_equation_solving_flow",
            "level": "L3",
            "prompt": "解方程 4x-8=2x+10。请写出移项和合并的关键步骤。",
            "answer": "4x-2x=10+8，2x=18，x=9。",
            "steps": ["把含x的项移到一边，常数移到另一边。", "合并得到2x=18。", "系数化为1得x=9。"],
        },
        {
            "family_id": "linear_equation_solving_flow",
            "level": "L3",
            "prompt": "解方程 x/3+2=5。请说明每一步对等式两边做了什么。",
            "answer": "两边先减2，x/3=3；两边再乘3，x=9。",
            "steps": ["两边同减2。", "两边同乘3。", "得到x=9。"],
        },
        {
            "family_id": "wrong_solution_repair_number",
            "level": "L3",
            "prompt": "错解：2x-3=7，所以2x=4，x=2。请指出错误并改正。",
            "answer": "两边应加3，得到2x=10，所以x=5。错在把-3移到右边时方向反了。",
            "steps": ["识别移项或两边同加3。", "得到2x=10。", "x=5并可代回。"],
        },
        {
            "family_id": "equation_transformation_legality",
            "level": "L4",
            "prompt": "判断这步是否合法：由 5x=3x+8 变成 2x=8。请说明依据。",
            "answer": "合法。等式两边同时减去3x，得到5x-3x=8，也就是2x=8。",
            "steps": ["指出两边同减3x。", "等式性质保证合法。", "合并得到2x=8。"],
        },
        {
            "family_id": "linear_equation_solving_flow",
            "level": "L4",
            "prompt": "解方程 0.5x+3=8。你可以先怎样处理小数让计算更稳？",
            "answer": "可两边同乘2，得x+6=16，所以x=10；也可先减3得0.5x=5，再除以0.5。",
            "steps": ["选择消小数或直接解。", "保持等式两边同步。", "得到x=10。"],
        },
    ],
    "M-G7-EQ-WORD": [
        {
            "family_id": "equation_word_modeling",
            "level": "L3",
            "prompt": "学校合唱队买了3盒彩笔和一个5元的文件夹，共花29元。每盒彩笔多少元？请设未知数，列方程并解答。",
            "answer": "设每盒彩笔x元，3x+5=29，3x=24，x=8，所以每盒彩笔8元。",
            "steps": ["设每盒彩笔x元。", "根据总价列方程3x+5=29。", "解得x=8并写答句。"],
        },
        {
            "family_id": "known_unknown_relation_marking",
            "level": "L3",
            "prompt": "甲数比乙数多12，甲数是乙数的3倍。请只写设元和等量关系，不急着求解。",
            "answer": "设乙数为x，则甲数为3x，等量关系是3x-x=12。",
            "steps": ["选择较小的乙数设为x。", "用3x表示甲数。", "用甲乙差列关系。"],
        },
        {
            "family_id": "equation_word_modeling",
            "level": "L4",
            "prompt": "买4本同样的练习本和1支6元的笔共30元。每本练习本多少元？请列方程。",
            "answer": "设每本练习本x元，4x+6=30，x=6。每本6元。",
            "steps": ["设单价为x。", "4本练习本加一支笔共30。", "解方程并写答句。"],
        },
        {
            "family_id": "distractor_condition_filter",
            "level": "L4",
            "prompt": "一件衣服原价 x 元，打八折后是160元。旁边标着“满300减20”但本次不能叠加。请列方程求原价，并说明哪个条件不能用。",
            "answer": "八折是0.8x，方程0.8x=160，x=200。满300减20不能用，因为题目说明本次不能叠加。",
            "steps": ["识别打八折关系。", "排除不能叠加的干扰条件。", "解得原价200元。"],
        },
        {
            "family_id": "solution_trace_repair",
            "level": "L3",
            "prompt": "一支笔 x 元，买4支笔和一本6元练习本共22元，解得 x=4。请写出怎样检查这个答案是否符合题意。",
            "answer": "把x=4代回：4支笔共4×4=16元，再加练习本6元，共22元，符合题意；答句应写每支笔4元。",
            "steps": ["把x=4代回原关系。", "检查总价是否等于22元。", "确认x表示每支笔的价格。"],
        },
        {
            "family_id": "equation_word_modeling",
            "level": "L4",
            "prompt": "一个长方形周长30厘米，长比宽多3厘米。求长和宽。请列方程。",
            "answer": "设宽为x厘米，长为x+3厘米，2[x+(x+3)]=30，解得x=6，所以宽6厘米、长9厘米。",
            "steps": ["设宽为x。", "用x+3表示长。", "按周长公式列方程并求解。"],
        },
    ],
    "M-BRIDGE-WORD-PROBLEM-READING": [
        {
            "family_id": "known_unknown_relation_marking",
            "level": "L2",
            "prompt": "小明有48元，买了3本同价笔记本后还剩12元。请圈出已知量、未知量，并写一句关系式。",
            "answer": "已知总钱48元、剩12元、买3本；未知是每本价格。关系式：3本价格+12=48。",
            "steps": ["找对象和数量。", "确定未知量。", "写出总钱关系。"],
        },
        {
            "family_id": "distractor_condition_filter",
            "level": "L3",
            "prompt": "一辆车从甲地到乙地，已知全程180千米，计划3小时到达，车上有4名乘客。求平均速度。哪个条件不用？",
            "answer": "平均速度=180÷3=60千米/小时。4名乘客与求平均速度无关，不用。",
            "steps": ["识别所求是速度。", "使用路程和时间。", "排除乘客人数。"],
        },
        {
            "family_id": "known_unknown_relation_marking",
            "level": "L3",
            "prompt": "读题后先不计算：学校买篮球和足球共20个，篮球比足球多4个。请写出两个对象和两个关系。",
            "answer": "对象是篮球个数、足球个数。关系一：篮球+足球=20；关系二：篮球-足球=4。",
            "steps": ["确定两个对象。", "把“共”翻译成和。", "把“多4个”翻译成差。"],
        },
        {
            "family_id": "distractor_condition_filter",
            "level": "L4",
            "prompt": "一桶油连桶重18千克，用去一半油后连桶重10千克。求桶重。请先说清哪个量的一半被用掉。",
            "answer": "用去的是油的一半，不是连桶总重的一半。半桶油重18-10=8千克，整桶油16千克，桶重18-16=2千克。",
            "steps": ["明确变化量是半桶油。", "用前后重量差求半桶油。", "求整桶油和桶重。"],
        },
        {
            "family_id": "equation_word_modeling",
            "level": "L4",
            "prompt": "把“一个数的2倍比它多9”翻译成等量关系。请写出设元和方程。",
            "answer": "设这个数为x，2x比x多9，所以2x-x=9。",
            "steps": ["设这个数为x。", "2倍是2x。", "“比它多9”写成2x-x=9。"],
        },
        {
            "family_id": "solution_trace_repair",
            "level": "L3",
            "prompt": "苹果每千克8元，买了a千克，付50元。若问题是“应找回多少钱”，请先写你防止看到数字就算的两步，再列式。",
            "answer": "先确定所求是找回的钱，再找关系：找回=付出-总价，所以列式50-8a。",
            "steps": ["先看问题问的是找回的钱。", "再写关系：找回=付出-总价。", "列式50-8a。"],
        },
    ],
    "M-BRIDGE-WORK-RATE": [
        {
            "family_id": "work_rate_model",
            "level": "L3",
            "prompt": "甲单独做6天完成一项工程，乙单独做9天完成。两人合作每天完成这项工程的几分之几？",
            "answer": "把总工程看作1，甲每天1/6，乙每天1/9，合作每天1/6+1/9=5/18。",
            "steps": ["总量设为1。", "分别求效率。", "合作效率相加。"],
        },
        {
            "family_id": "work_rate_model",
            "level": "L3",
            "prompt": "甲每天完成工程的1/8，乙每天完成1/12。两人合作几天完成？",
            "answer": "合作效率=1/8+1/12=5/24，所以完成时间=1÷5/24=24/5天，即4.8天。",
            "steps": ["效率相加。", "总量1除以合作效率。", "得到24/5天。"],
        },
        {
            "family_id": "solution_trace_repair",
            "level": "L3",
            "prompt": "错解：甲6天完成，乙9天完成，合作时间=(6+9)÷2=7.5天。请指出模型错在哪里。",
            "answer": "不能平均天数，应平均的是每天完成的工作量。合作效率=1/6+1/9=5/18，合作时间=18/5=3.6天。",
            "steps": ["指出天数不能直接平均。", "把总工程设为1。", "用效率相加求时间。"],
        },
        {
            "family_id": "known_unknown_relation_marking",
            "level": "L3",
            "prompt": "一项工程甲独做10天完成。如果甲先单独做2天，剩下的工程量是多少？请只写甲完成了多少和剩余多少。",
            "answer": "总量设为1，甲效率1/10，甲2天完成2/10=1/5，剩余4/5。",
            "steps": ["总量设为1。", "甲效率是1/10。", "2天完成1/5，剩4/5。"],
        },
        {
            "family_id": "work_rate_model",
            "level": "L4",
            "prompt": "甲乙合作4天完成一项工程，甲单独做6天完成。乙单独做几天完成？",
            "answer": "合作效率1/4，甲效率1/6，所以乙效率1/4-1/6=1/12，乙单独12天完成。",
            "steps": ["把完成时间转成效率。", "乙效率=合作效率-甲效率。", "用1除以乙效率。"],
        },
        {
            "family_id": "distractor_condition_filter",
            "level": "L4",
            "prompt": "甲8天完成，乙12天完成。题目还说甲每天工作6小时、乙每天工作5小时，但完成天数已经按各自每天工作量计算。求合作几天完成，哪些条件不用？",
            "answer": "不用每天工作几小时，因为单独完成天数已包含各自效率。合作效率1/8+1/12=5/24，合作时间24/5天。",
            "steps": ["确认完成天数已经定义效率。", "排除小时数干扰。", "用效率相加。"],
        },
    ],
    "M-PRE-GEO-AREA-VOLUME": [
        {
            "family_id": "area_volume_formula_structure",
            "level": "L3",
            "prompt": "一个长方体长5厘米、宽4厘米、高3厘米。请用“底面积×高”解释体积为什么是60立方厘米。",
            "answer": "底面积是5×4=20平方厘米。若按1厘米厚切成一层，每层体积是20立方厘米；高3厘米相当于3层，所以体积20×3=60立方厘米。",
            "steps": ["先求底面积20平方厘米。", "用1厘米厚的一层解释面积到体积。", "3层共60立方厘米。"],
        },
        {
            "family_id": "unit_dimension_conversion",
            "level": "L3",
            "prompt": "1平方米等于多少平方厘米？请说明为什么不是100平方厘米。",
            "answer": "1米=100厘米，1平方米是100厘米×100厘米=10000平方厘米，不是100平方厘米。",
            "steps": ["长度单位先换算。", "面积是两个方向相乘。", "平方单位进率要平方。"],
        },
        {
            "family_id": "area_volume_formula_structure",
            "level": "L4",
            "prompt": "半径为4厘米的圆，面积公式中为什么是 π×4²，而不是 π×8²？",
            "answer": "圆面积公式用半径r，不用直径。半径是4厘米，所以面积是16π平方厘米；8厘米是直径。",
            "steps": ["区分半径和直径。", "面积公式是πr²。", "代入r=4。"],
        },
        {
            "family_id": "area_volume_formula_structure",
            "level": "L4",
            "prompt": "一个长8厘米、宽5厘米的长方形挖去一个边长2厘米的正方形。求剩余面积，并说明单位。",
            "answer": "长方形面积8×5=40平方厘米，挖去正方形面积2×2=4平方厘米，剩余36平方厘米。",
            "steps": ["把组合图形拆成整体和挖去部分。", "分别求面积并写平方厘米。", "相减得到36平方厘米。"],
        },
        {
            "family_id": "unit_dimension_conversion",
            "level": "L3",
            "prompt": "错解：长方体体积单位写成平方厘米。请说明为什么单位错了。",
            "answer": "体积表示三维空间大小，是长×宽×高，单位应是立方厘米；平方厘米是面积单位。",
            "steps": ["区分面积二维、体积三维。", "长宽高三个方向相乘。", "写成立方厘米。"],
        },
        {
            "family_id": "area_volume_formula_structure",
            "level": "L4",
            "prompt": "一个圆柱和一个长方体等底面积、等高。它们体积有什么关系？请解释，不用给具体数字。",
            "answer": "体积相等。因为两者体积都可以看作底面积×高，底面积和高相等，所以体积相等。",
            "steps": ["抓住体积共同结构。", "比较底面积和高。", "得出体积相等。"],
        },
    ],
    "M-G7-GEO-VIEWS": [
        {
            "family_id": "net_and_view_matching",
            "level": "L3",
            "prompt": "正方体展开图中有一排4个正方形，第二个的上方和下方各接1个正方形。折成立方体后，上下两个接出的面是否相对？请说明。",
            "answer": "是相对面。以第二个正方形为中间面，上下两个面折起后分别在立方体相对方向。",
            "steps": ["确定中间面。", "想象上下两个面折起。", "判断它们在相对方向。"],
        },
        {
            "family_id": "net_and_view_matching",
            "level": "L4",
            "prompt": "一个小正方体堆成两层：下层是2×2四个，上层只放在左前角1个。从上面看能看到几个小正方形？从正面看最高有几层？",
            "answer": "从上面看仍是4个位置；从正面看左前位置有2层，所以最高2层。",
            "steps": ["俯视看占地位置。", "正视看高度。", "区分看到的面和实际个数。"],
        },
        {
            "family_id": "net_and_view_matching",
            "level": "L3",
            "prompt": "一个立方体骰子，相对面点数和为7。若上面是1，前面是2，右面是3，则下面是多少？",
            "answer": "下面与上面相对，上面是1，所以下面是6。",
            "steps": ["识别相对面。", "用相对面点数和为7。", "7-1=6。"],
        },
        {
            "family_id": "object_representation_boundary",
            "level": "L3",
            "prompt": "下面哪类信息能决定一个小方块堆叠图的左视图：每个位置的高度，还是每个小方块的颜色？请说明。",
            "answer": "决定左视图主要看各位置高度和遮挡关系，颜色通常不能决定外形轮廓。",
            "steps": ["明确视图看轮廓和高度。", "颜色不是形状结构。", "说明遮挡方向。"],
        },
        {
            "family_id": "net_and_view_matching",
            "level": "L4",
            "prompt": "同学说“展开图只要有6个正方形就一定能折成正方体”。请给出反例思路，说明为什么不对。",
            "answer": "不对。6个正方形如果排成一条直线，就不能折成正方体，因为折起后会重叠或无法围成立体。",
            "steps": ["指出数量够不是充分条件。", "给出一排6个的反例。", "解释折叠后不能围成正方体。"],
        },
        {
            "family_id": "net_and_view_matching",
            "level": "L5",
            "prompt": "一个小方块堆叠体从上面看是一个2×3的完整长方形，从正面看三列高度分别是2、1、2。从左面看两行高度都不超过2。这个堆叠体最少有几个小方块？",
            "answer": "最少8个。上面是完整2×3，说明6个底部位置都至少有1个；正面三列高度2、1、2要求第一列和第三列各至少加高1个，所以最少6+2=8个，且左视图两行高度不超过2可以满足。",
            "steps": ["俯视完整2×3表示6个底部位置都至少有1个。", "正面高度2、1、2要求两列各加高1个。", "因此最少8个，并检查左视图不超过2。"],
        },
    ],
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(*parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"SF18-{digest}"


def _scoring_targets(item: dict[str, Any]) -> list[dict[str, Any]]:
    steps = item.get("solution_steps") or []
    first_step = steps[0] if len(steps) > 0 else "写出本题核心关系"
    second_step = steps[1] if len(steps) > 1 else first_step
    return [
        {
            "key": "final_conclusion",
            "criterion": f"最终结论与本题标准答案数学等价即可：{str(item.get('expected_answer') or '')[:80]}",
            "dimension": "final_answer",
            "required_for_pass": True,
            "reference_component": "expected_answer",
            "points": 4,
        },
        {
            "key": "core_relation",
            "criterion": f"能体现本题核心关系、模型、图形结构或符号来源；本题关键证据：{first_step}",
            "dimension": "model_relation",
            "required_for_pass": True,
            "reference_component": "solution_step_1",
            "points": 3,
        },
        {
            "key": "process_or_check",
            "criterion": f"关键步骤可复盘，并能进行估算、代回、单位或结构检查；本题过程证据：{second_step}",
            "dimension": "procedure",
            "required_for_pass": False,
            "reference_component": "solution_step_2",
            "points": 3,
        },
    ]


def build_sample() -> dict[str, Any]:
    graph = _load(GRAPH_PATH)
    blueprints = _load(BLUEPRINT_PATH)
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    blueprint_by_node = {bp["node_id"]: bp for bp in blueprints["blueprints"]}

    items = []
    for node_id, specs in SAMPLE_SPECS.items():
        node = node_by_id[node_id]
        blueprint = blueprint_by_node[node_id]
        allowed_family_ids = {entry["family_id"] for entry in blueprint["family_plan"]}
        for slot, spec in enumerate(specs, 1):
            family_id = spec["family_id"]
            if family_id not in allowed_family_ids:
                raise ValueError(f"{node_id}/{family_id} is not allowed by blueprint")
            structure = _fingerprint(node_id, family_id, spec["prompt"])
            item_id = f"QB18S-{node_id}-{slot:02d}"
            rollback_nodes = list(
                dict.fromkeys(
                    (node.get("prerequisites") or [])
                    + ((node.get("error_diagnosis") or {}).get("rollback_to") or [])
                    + (spec.get("extra_rollback") or [])
                )
            )[:5]
            item = {
                "id": item_id,
                "item_version": BANK_VERSION,
                "question_bank_version": BANK_VERSION,
                "source_type": "graph_generated",
                "node_id": node_id,
                "secondary_node_ids": [],
                "kind": "v18_sample",
                "question_type": family_id,
                "variant_level": spec["level"],
                "difficulty": spec["level"],
                "prompt": spec["prompt"],
                "answer_format": "写出关键关系、必要过程和结论；表达意图清楚即可。",
                "expected_answer": spec["answer"],
                "standard_answer": spec["answer"],
                "accepted_alternatives": ["等价算式、等价文字说明或合理图示均可。"],
                "rubric": [
                    "结果等价即可。",
                    "核心关系必须正确。",
                    "非关键书写不作为主扣分。",
                ],
                "solution_steps": spec["steps"],
                "required_evidence": spec.get("required_evidence")
                or [
                    f"结论：{spec['answer'][:80]}",
                    f"核心关系：{spec['steps'][0]}",
                    f"关键过程：{spec['steps'][1] if len(spec['steps']) > 1 else spec['steps'][0]}",
                ],
                "key_score_points": [
                    {"key": "final_conclusion", "points": 4, "evidence": f"结论等价于：{spec['answer'][:80]}"},
                    {"key": "core_relation", "points": 3, "evidence": spec["steps"][0]},
                    {"key": "process_or_check", "points": 3, "evidence": spec["steps"][1] if len(spec["steps"]) > 1 else spec["steps"][0]},
                ],
                "target_error_tags": list((node.get("error_diagnosis") or {}).get("likely_error_tags") or [])[:3],
                "rollback_candidates": rollback_nodes,
                "rollback_candidate_node_ids": rollback_nodes,
                "estimated_minutes": 4 if spec["level"] in {"L2", "L3"} else 5,
                "parent_observation": "看孩子是否抓住核心关系；不要把轻微表达差异当成不会。",
                "evidence_goal": family_id,
                "slot_role": family_id,
                "evidence_role": family_id,
                "cognitive_level": spec["level"],
                "problem_family_id": f"PF18-{node_id}-{family_id}",
                "core_stem_id": f"CS18-{node_id}-{slot:02d}",
                "variant_signature": f"VS18-{node_id}-{slot:02d}-{structure}",
                "math_core_signature": structure,
                "node_local_mainline": node.get("priority") != "P2",
                "quality": {
                    "contract_version": CONTRACT_VERSION,
                    "review_status": "draft_generated",
                    "status": "draft_generated",
                    "age_floor": "incoming_grade_7",
                    "requires_reasoning": True,
                    "no_mechanical_drill": True,
                    "has_high_signal_structure": True,
                    "structure_fingerprint": structure,
                    "blueprint_node_id": node_id,
                    "blueprint_family_id": family_id,
                    "activation_eligible": False,
                    "assessment_policy": {
                        "schema_version": "teacher_lightweight_scoring_policy.v18.sample",
                        "score_scale": 10,
                        "partial_credit_rules": [
                            "核心意图正确且最终结论正确时给主要分。",
                            "非关键书写缺失最多扣1分，不判为不会。",
                            "模型关系错但答案碰巧对，不能判完全掌握。",
                        ],
                    },
                },
                "scoring_targets": [],
                "source": {
                    "type": "graph_generated",
                    "generator": "v18_sample_curated_blueprint",
                    "manifest_id": MANIFEST_ID,
                    "question_bank_version": BANK_VERSION,
                    "contract_version": CONTRACT_VERSION,
                    "node_blueprint_schema": blueprints["schema_version"],
                    "status": "draft_generated_not_active",
                    "activation_policy": "sample only; must pass expert QA before staging",
                },
                "node_alignment": {
                    "status": "claimed_for_review",
                    "primary_node_id": node_id,
                    "problem_family_id": f"PF18-{node_id}-{family_id}",
                    "core_stem_id": f"CS18-{node_id}-{slot:02d}",
                    "measured_capability": family_id,
                    "off_node_risk": "review_required",
                },
            }
            item["scoring_targets"] = _scoring_targets(item)
            items.append(item)
    return {
        "schema_version": "2026-07-22.question-bank.v18.sample",
        "manifest_id": MANIFEST_ID,
        "question_bank_version": BANK_VERSION,
        "status": "draft_generated_not_active",
        "source_policy": "Hand-curated from v18 node blueprints; no external question text copied.",
        "activation_policy": "Not eligible for child runtime until expert_reviewed and qa_passed receipts exist.",
        "node_count": len(SAMPLE_SPECS),
        "item_count": len(items),
        "items": items,
    }


def main() -> None:
    sample = build_sample()
    SAMPLE_PATH.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {SAMPLE_PATH}")
    print(f"items: {sample['item_count']}")


if __name__ == "__main__":
    main()
