from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .expert_review import EXPERT_PROFILES
from .inventory import (
    AdminPaths,
    _blueprints_by_node,
    _families_by_id,
    _graph_nodes_by_id,
    _load_assets,
    _load_json,
    _question_bank_path,
)


PROFILE_DESIGN_ANGLES = {
    "frontline_math_teacher": {
        "principle": "题目要让六升七孩子觉得值得做：少机械计算，多让他说明结构、比较方法、验证结论。",
        "idea_focus": "课堂可教、表达自然、题面尊重孩子。",
    },
    "bridge_diagnosis_teacher": {
        "principle": "题目要能暴露第一个断点：是前置不会、模型没建好、步骤不稳，还是迁移不稳。",
        "idea_focus": "前置探针、近迁移复测、错因回退。",
    },
    "stretch_competition_teacher": {
        "principle": "拔高不是堆数字，而是改变表示、条件、方向或边界，让孩子迁移同一个本质。",
        "idea_focus": "边界、反例、构造、逆向、迁移。",
    },
    "assessment_expert": {
        "principle": "每类题必须预先定义可观察证据和评分点，允许等价表达，不把非关键书写当不会。",
        "idea_focus": "证据目标、得分点、误判防线。",
    },
    "source_compliance_reviewer": {
        "principle": "题型可以参考公开范围和结构，题干、数据、图形和解析必须原创或有明确许可。",
        "idea_focus": "来源边界、原创约束、结构指纹。",
    },
}


def _requirement_id(*, node_id: str, family_id: str, slot_order: int, design_brief_seed: str) -> str:
    seed = "|".join([node_id, family_id, str(slot_order), design_brief_seed])
    return "REQ-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _pick_difficulty(allowed: list[Any], slot_index: int) -> str:
    values = [str(value) for value in allowed if value]
    if not values:
        return "L3"
    if len(values) == 1:
        return values[0]
    return values[min(slot_index, len(values) - 1)]


def _coverage_role(slot_index: int, difficulty: str) -> str:
    if slot_index == 0:
        return "entry_probe"
    if difficulty in {"L4", "L5"}:
        return "transfer_or_stretch"
    return "confirmation_or_variant"


def _difficulty_sequence(family: dict[str, Any]) -> list[str]:
    target_count = int(family.get("target_count") or 0)
    distribution = family.get("difficulty_distribution")
    if isinstance(distribution, dict):
        unknown = sorted(set(distribution) - {"L2", "L3", "L4", "L5"})
        if unknown:
            raise ValueError(
                f"ADMIN_UNKNOWN_DIFFICULTY_LEVEL: {family.get('family_id')} {unknown}"
            )
        sequence: list[str] = []
        for level in ("L2", "L3", "L4", "L5"):
            count = distribution.get(level, 0)
            if not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"ADMIN_INVALID_DIFFICULTY_DISTRIBUTION: {family.get('family_id')}"
                )
            sequence.extend([level] * count)
        if len(sequence) != target_count:
            raise ValueError(
                f"ADMIN_DIFFICULTY_DISTRIBUTION_COUNT_MISMATCH: "
                f"{family.get('family_id')} expected={target_count} actual={len(sequence)}"
            )
        return sequence
    allowed = list(family.get("difficulty") or [])
    return [_pick_difficulty(allowed, index) for index in range(target_count)]


def _family_execution_contract(
    family: dict[str, Any], family_meta: dict[str, Any]
) -> dict[str, Any]:
    support_only = bool(
        family.get("support_only", family_meta.get("support_only", False))
    )
    not_for_activation = bool(
        family.get(
            "not_for_activation", family_meta.get("not_for_activation", False)
        )
    )
    exclude_from_coverage = bool(
        family.get(
            "exclude_from_coverage",
            family_meta.get("exclude_from_coverage", False),
        )
    )
    secondary_nodes = family.get(
        "secondary_nodes", family_meta.get("secondary_nodes", [])
    )
    if not isinstance(secondary_nodes, list) or any(
        not isinstance(node_id, str) or not node_id.strip()
        for node_id in secondary_nodes
    ):
        raise ValueError(
            f"ADMIN_INVALID_SECONDARY_NODES: {family.get('family_id')}"
        )
    if support_only and (not not_for_activation or not exclude_from_coverage):
        raise ValueError(
            f"ADMIN_UNSAFE_SUPPORT_FAMILY_CONTRACT: {family.get('family_id')}"
        )
    return {
        "support_only": support_only,
        "not_for_activation": not_for_activation,
        "exclude_from_coverage": exclude_from_coverage,
        "secondary_nodes": list(dict.fromkeys(secondary_nodes)),
    }


FAMILY_DESIGN_KERNELS = {
    "number_sense_range_benchmark": {
        "core_scenario": "先选择贴近原数且便于心算的基准，再给出能排除离谱答案的上下界、区间或数量级。",
        "variation_logic": ["给乘积选择上下界", "给商确定有判别力的上下界区间", "比较两个估算基准的范围紧致性"],
        "evidence_goal": ["能选合理估算基准", "能给出有判别力的结果范围", "能解释范围为何覆盖真实结果"],
        "stretch_angle": "比较多个基准形成的估值区间，选择更紧且仍容易计算的一种。",
        "common_traps": ["先精算再反填估算", "上下界方向颠倒", "范围过宽失去检查作用"],
    },
    "number_sense_bias_direction": {
        "core_scenario": "观察近似替换相对原数的增减，判断估计结果偏大、偏小或是否无法仅凭方向确定。",
        "variation_logic": ["单个量向上或向下取整", "两个量同向偏差", "两个量反向偏差并判断是否抵消"],
        "evidence_goal": ["能指出偏差来源", "能判断偏差方向", "能处理两个偏差的叠加或抵消"],
        "stretch_angle": "给一增一减的近似替换，让孩子判断现有信息是否足以确定总偏差方向。",
        "common_traps": ["只看一个量的偏差", "把因数变化对积的影响判断反", "认为一增一减必然完全抵消"],
    },
    "number_sense_magnitude_reasonableness": {
        "core_scenario": "不用完整精算，借数量级、小数点、位数、单位和现实范围判断候选结果是否合理。",
        "variation_logic": ["排除错位小数点", "判断单位量级", "在多个近邻结果中筛选合理值"],
        "evidence_goal": ["能确定合理数量级", "能定位小数点或位数异常", "能用单位或范围解释判断"],
        "stretch_angle": "让多个候选结果都表面接近，要求用两条独立量级证据筛选。",
        "common_traps": ["小数点错一位仍接受", "忽略单位导致量级错误", "只看末位数字不看整体大小"],
    },
    "number_sense_strategy_selection": {
        "core_scenario": "根据粗估、范围判断或精度需求，在多个估算策略间比较计算成本和误差范围。",
        "variation_logic": ["比较两个取整基准", "按用途选择粗估或精估", "判断已有精度是否足够"],
        "evidence_goal": ["能选择匹配任务的策略", "能比较误差与计算成本", "能说明所选精度为何足够"],
        "stretch_angle": "在速度与误差要求冲突时作选择，但不要求最优算法证明。",
        "common_traps": ["无论用途都用同一估法", "把步骤多误认为更准确", "为了估算仍完整精算"],
    },
    "number_line_reference_frame": {
        "core_scenario": "判断、修复或构造包含原点、正方向和统一单位长度的有效数轴。",
        "variation_logic": ["从内嵌的简短数轴中辨认原点", "只判断或修正数轴的正方向", "根据相邻刻度数值确定单位长度"],
        "evidence_goal": ["能明确原点", "能明确正方向", "能保持单位长度一致"],
        "stretch_angle": "同时修复方向、刻度间距和标签冲突，不靠增加点数制造难度。",
        "common_traps": ["漏原点", "正方向反或未标", "刻度间距或每格数量不一致"],
    },
    "number_line_coordinate_location": {
        "core_scenario": "在有效数轴上完成数到点、点到数以及局部位置顺序的双向转换。",
        "variation_logic": ["定位整数和负数", "定位分数小数", "读取非单位刻度或不完整标签"],
        "evidence_goal": ["能读懂每格数量", "能准确完成坐标定位", "能用左右位置解释顺序"],
        "stretch_angle": "改变表示和刻度信息，不把相反数、绝对值或有理数运算作为主要得分点。",
        "common_traps": ["负方向刻度读反", "分数小数按表面数字猜位置", "忽略每格代表的数量"],
    },
    "number_line_distance_relation": {
        "core_scenario": "用统一刻度区分带方向的位置和不带方向的距离，并由位置、距离反推可能点。",
        "variation_logic": ["由两点求刻度距离", "由一点和距离反推位置", "判断可能位置是否唯一"],
        "evidence_goal": ["能区分位置与距离", "能正确计算刻度间隔", "能构造所有可能位置"],
        "stretch_angle": "出现多解构造，但不提前使用绝对值方程或复杂有理数运算。",
        "common_traps": ["距离写成负数", "把坐标值直接当距离", "反推位置时漏掉另一方向"],
    },
    "number_line_local_scale_construction": {
        "core_scenario": "只给两个已知点、部分标签或局部刻度，恢复单位长度并补出可检验的最小数轴片段。",
        "variation_logic": ["由两个标签恢复每格数量", "补跨零刻度", "构造能表示目标分数或小数的局部数轴"],
        "evidence_goal": ["能恢复局部单位长度", "能保持刻度连续一致", "能反向检验目标点位置"],
        "stretch_angle": "处理跨零、分数单位或部分标签缺失，不扩展到坐标系和函数图像。",
        "common_traps": ["局部刻度间隔不等", "标签与单位长度不匹配", "为放下目标数临时改变单位长度"],
    },
    "equality_add_subtract_invariance": {
        "core_scenario": "从已成立等式出发，对两边同加或同减同一个量，并说明等式为何保持。",
        "variation_logic": ["判断同加减是否合法", "补齐另一边对应项", "解释移项表象背后的同加减"],
        "evidence_goal": ["能识别两边同量", "能保持同加减操作一致", "能解释等式保持"],
        "stretch_angle": "允许含式子的同加减和多种等价写法，但不进入完整解方程。",
        "common_traps": ["只改一边", "两边加减不同的量", "把移项变号当作无依据的新规则"],
    },
    "equality_multiply_divide_invariance": {
        "core_scenario": "从已成立等式出发，对两边同乘同一个量或同除以同一个非零量，并观察适用边界。",
        "variation_logic": ["判断同乘是否合法", "补齐同除对应项", "比较含0风险的操作说法"],
        "evidence_goal": ["能识别两边同乘除", "能主动说明除数非零", "能解释等式保持"],
        "stretch_angle": "研究非零条件和含式子操作，不进入去分母流程或分式方程。",
        "common_traps": ["只给一边乘除", "两边乘除不同的量", "认为可以同除以0"],
    },
    "equality_illegal_operation_counterexample": {
        "core_scenario": "对只改一边、两边操作不同或除以0的非法操作，用具体反例说明其不能保证等式保持。",
        "variation_logic": ["判断非法操作", "代入相等数验证失败", "自行构造最小反例并合法修正"],
        "evidence_goal": ["能定位违反的等式性质", "能构造反例", "能给出合法修正"],
        "stretch_angle": "区分碰巧成立与恒能保持，但不进入形式逻辑或高阶代数证明。",
        "common_traps": ["结果碰巧相等就认为恒合法", "只说错了但不给依据", "忽略除以0无意义"],
    },
    "equality_operation_reconstruction": {
        "core_scenario": "根据变形前后的等式或缺项等式，还原两边共同操作并用反向操作验证。",
        "variation_logic": ["还原共同加减", "还原共同乘除", "比较多个候选操作并判断是否唯一"],
        "evidence_goal": ["能还原共同操作", "能保持两边对应", "能反向验证前后等式"],
        "stretch_angle": "处理含式子的单步对应或不唯一判断，不串联成完整求解流程。",
        "common_traps": ["只观察一边猜操作", "补项时符号或倍数不对应", "把等价变形误认为任意改写"],
    },
    "number_line_position_distance": {
        "core_scenario": "用有方向的移动、两点距离、原点两侧位置关系来检验“数是位置，不是孤立符号”。",
        "variation_logic": ["给起点和移动方向", "给两个点反推距离", "用不画完整数轴的局部刻度判断顺序", "让孩子解释为什么向左不是加大"],
        "evidence_goal": ["能把数对应到位置", "能区分方向和距离", "能用数轴语言解释大小关系"],
        "stretch_angle": "给一个未知点和距离条件，让孩子构造所有可能位置或判断是否唯一。",
        "common_traps": ["把向左移动当加法", "把距离带符号", "只看数字大小不看位置"],
    },
    "opposite_absolute_value_model": {
        "core_scenario": "把相反数和绝对值都落到“到原点的距离”和“原点两侧对称位置”。",
        "variation_logic": ["给距离和方向反推数", "判断关于0对称的位置", "比较两个数的绝对值和本身大小", "让孩子判断一个说法的反例", "把文字条件翻成数轴位置"],
        "evidence_goal": ["能说明相反数是关于0对称", "能处理 0 的特殊性", "能说明绝对值是距离", "能区分相反数和倒数"],
        "stretch_angle": "给 |a|=|b| 且 a 与 b 的关系条件，让孩子判断 a,b 的可能值结构。",
        "common_traps": ["认为绝对值一定让数变大", "漏掉 0", "把相反数理解成负数"],
    },
    "estimate_direction_and_magnitude": {
        "core_scenario": "用一个易算基准判断方向和量级，再用精算或边界检验确认。",
        "variation_logic": ["选不同基准", "比较两个近似乘积", "先估方向再精算", "让孩子指出一个估算错因"],
        "evidence_goal": ["能选合理基准", "能判断偏差方向", "能用精算或边界检查"],
        "stretch_angle": "不给精确计算空间，要求比较两个表达式谁更大并说明偏差抵消关系。",
        "common_traps": ["只算不估", "小数点量级失控", "只看一个因数偏差"],
    },
    "solution_trace_repair": {
        "core_scenario": "给一段接近正确但缺关键证据的解法，让孩子补证据或定位最危险一步。",
        "variation_logic": ["补缺失步骤", "判断错解哪一步开始错", "给两个解法选更稳的", "要求写一句检验"],
        "evidence_goal": ["能复盘步骤", "能定位关键错误", "能主动检验结论"],
        "stretch_angle": "给一个结果正确但理由不充分的解法，让孩子判定是否可以得满分并修复。",
        "common_traps": ["只说粗心", "只改结果不改理由", "把书写完整误当数学正确"],
    },
    "answer_check_habit": {
        "core_scenario": "把检验答案设计成正常解题的一部分，让孩子用代回、估算、单位、范围或逆运算确认结果。",
        "variation_logic": ["给答案让孩子选合适检验方法", "让孩子发现结果数量级不合理", "代回原条件检验方程解", "比较两个验算方式哪个更快更稳"],
        "evidence_goal": ["能选择检验方法", "能说明检验依据", "能发现结果与题意冲突"],
        "stretch_angle": "给一个过程看似正确但答案不合理的解法，让孩子用两种检验方式定位问题。",
        "common_traps": ["做完不验算", "只重复原计算当验算", "检验不回到原题条件"],
    },
    "decimal_place_value_ops": {
        "core_scenario": "围绕小数位值、单位换算、乘除 10/100/1000 和小数点位置来源建立稳定解释。",
        "variation_logic": ["同一数在元/角/分或米/厘米中改单位", "判断小数点移动是否合理", "用估算发现位值错误", "把小数乘除转成整数结构再还原"],
        "evidence_goal": ["能解释小数点位置来源", "能用单位或位值检验", "能发现数量级错误"],
        "stretch_angle": "给一个结果和数量级都可疑的计算，让孩子用两种方法判断小数点应放哪。",
        "common_traps": ["机械数小数位数", "单位变了但数值关系没变", "乘除 10 方向反了"],
    },
    "structure_based_simplification": {
        "core_scenario": "让孩子先识别凑整、拆分、分配律或结合律结构，再决定是否值得简算。",
        "variation_logic": ["给两种算法比较", "隐藏一个可凑整结构", "要求解释为什么这样拆不漏项", "给一个错误简算让孩子修复"],
        "evidence_goal": ["能识别结构", "能保持等价", "能检查漏项或重复计算"],
        "stretch_angle": "让孩子自己选择一个基准拆分，并说明为什么比硬算更稳。",
        "common_traps": ["为了简算乱拆", "分配律漏项", "只会套 25×4、125×8"],
    },
    "wrong_solution_repair_number": {
        "core_scenario": "把错解设计成接近真实孩子会犯的错误，让孩子说明错因并修复，而不是只改答案。",
        "variation_logic": ["小数点错位", "估算方向错", "运算律漏项", "单位/数量级不合理", "结果正确但理由错"],
        "evidence_goal": ["能识别错因", "能给出修复后的等价步骤", "能用检查证明修复有效"],
        "stretch_angle": "给两个看似都对的修复方案，让孩子比较哪个更可靠。",
        "common_traps": ["只写正确答案", "把错因归为粗心", "没有验证修复后的结果"],
    },
    "integer_structure_arithmetic": {
        "core_scenario": "用拆分、补整、乘除关系和余数结构检验整数运算的结构感，而不是重复大数硬算。",
        "variation_logic": ["把一个数拆成接近整十整百的和差", "用乘除互逆或余数关系验算", "比较两种计算路径的稳定性", "给一个看似正确的整数运算让孩子用结构检验"],
        "evidence_goal": ["能选择合适拆分", "能用互逆关系验算", "能解释余数或数量级是否合理"],
        "stretch_angle": "让孩子在不完整运算中反推出缺失数，并说明唯一性或不唯一性。",
        "common_traps": ["只堆竖式不看结构", "余数大于或等于除数仍认为正确", "拆分后漏项"],
    },
    "signed_operation_model": {
        "core_scenario": "把有理数加减乘除落到方向变化、相反量抵消和符号规则的来源。",
        "variation_logic": ["用温度或收支解释加减", "用数轴移动解释符号变化", "比较两个带符号表达式", "修复负号漏写或括号错误"],
        "evidence_goal": ["能说明符号来源", "能区分运算符号和数的符号", "能用模型检验结果正负"],
        "stretch_angle": "给含多个负号的表达式，让孩子先判断符号方向，再决定是否需要精算。",
        "common_traps": ["见负号就取相反数", "减负数时方向混乱", "乘除符号规则只背不检验"],
    },
    "operation_order_control": {
        "core_scenario": "围绕先后顺序、括号控制和等价变形，让孩子说明为什么这一步可以先算。",
        "variation_logic": ["给同一串数插入不同括号", "判断两种计算顺序是否等价", "修复先算加减导致的错解", "让孩子设计一个能凑整的括号"],
        "evidence_goal": ["能遵守运算顺序", "能解释括号改变的对象", "能检查改顺序是否保持等价"],
        "stretch_angle": "给目标结果，让孩子添加一组括号或运算顺序说明，使表达式成立。",
        "common_traps": ["从左到右机械乱算", "为了简算擅自换顺序", "括号只管相邻一个数"],
    },
    "fraction_unit_and_equivalence": {
        "core_scenario": "把分数看成单位量、份数和等价比例，检验孩子是否知道分母分子的角色。",
        "variation_logic": ["换单位量后判断同一个分数是否变了", "用图形或数量说明等值分数", "比较两个分数的基准是否相同", "找一个错误通分或约分的原因"],
        "evidence_goal": ["能说清单位量", "能构造等值分数", "能发现基准不同导致不能直接比较"],
        "stretch_angle": "给两个看似相同的分数描述，让孩子判断它们是否表示同一数量并给反例。",
        "common_traps": ["只看分子大小", "单位量变了还直接比较", "约分改变了数量含义"],
    },
    "fraction_operation_structure": {
        "core_scenario": "用单位分数、通分意义和乘除互逆解释分数运算，不把算法当口诀。",
        "variation_logic": ["先估结果范围再计算", "用面积或份数模型解释乘法", "用包含关系解释除法", "修复通分、约分或倒数使用错误"],
        "evidence_goal": ["能解释通分目的", "能说明乘除法模型", "能用估算检查结果范围"],
        "stretch_angle": "给一个分数运算结果，让孩子判断是否可能并说明范围依据。",
        "common_traps": ["分数加法分子分母分别相加", "除以分数时倒错对象", "结果范围明显不合理仍接受"],
    },
    "percent_rate_change": {
        "core_scenario": "把百分数还原成基准量、变化量和变化率三者关系。",
        "variation_logic": ["判断百分数对应的是谁的几分之几", "从变化前后反推变化率", "比较上涨和下降的非对称性", "修复把百分点和百分比混用的说法"],
        "evidence_goal": ["能锁定基准量", "能区分变化量和变化率", "能检验百分数结果是否合理"],
        "stretch_angle": "给连续涨跌或折扣，让孩子说明为什么不能直接把百分数相加减。",
        "common_traps": ["找错单位1", "把百分数当具体数量", "上涨后再下降同百分比误认为回到原值"],
    },
    "ratio_proportion_structure": {
        "core_scenario": "用对应量、比值不变和成比例关系建立比例结构。",
        "variation_logic": ["补全比例表", "判断两个量是否成比例", "从一组对应量反推未知", "指出只看差不看比的错误"],
        "evidence_goal": ["能找到对应量", "能保持同一比值", "能区分比和差"],
        "stretch_angle": "给混合条件，让孩子判断应该用比例、差量还是总量模型。",
        "common_traps": ["对应关系错位", "把差相等当比例相等", "比例尺或单位未统一"],
    },
    "number_classification_boundary": {
        "core_scenario": "用整数、分数、小数、有理数等集合边界检验分类依据，而不是背名称。",
        "variation_logic": ["把一个数放入多个集合", "判断一个分类说法是否总成立", "给反例区分自然数、整数、有理数", "处理 0、负数、小数和分数的边界"],
        "evidence_goal": ["能说明分类依据", "能处理边界数", "能用反例排除错误说法"],
        "stretch_angle": "给一个集合包含关系图，让孩子填数并解释不能放入的位置。",
        "common_traps": ["认为小数不是分数", "漏掉 0", "把负数排除在有理数外"],
    },
    "power_base_sign": {
        "core_scenario": "把乘方看作相同因数连乘，重点区分底数、指数和括号控制的负号范围。",
        "variation_logic": ["比较 -a^2 与 (-a)^2", "把乘方写成连乘", "判断底数是否包含负号", "修复指数作用对象错误"],
        "evidence_goal": ["能指出底数", "能展开连乘", "能解释结果符号"],
        "stretch_angle": "给若干含负号乘方表达式，让孩子先分类再计算。",
        "common_traps": ["把 -3^2 算成 9", "指数作用到整个前缀", "乘方和乘法顺序混乱"],
    },
    "scientific_notation_precision": {
        "core_scenario": "用数量级、有效数字和近似精度解释科学记数法，不只移动小数点。",
        "variation_logic": ["把大数小数写成科学记数法", "根据近似精度判断保留位数", "比较两个科学记数法数量级", "修复指数正负方向错误"],
        "evidence_goal": ["能确定 1 到 10 的有效数", "能解释 10 的指数含义", "能处理近似精度"],
        "stretch_angle": "给测量场景，让孩子选择合适精度并说明会损失什么信息。",
        "common_traps": ["有效数不在 1 到 10", "指数方向反了", "近似和精确混在一起"],
    },
    "verbal_to_expression": {
        "core_scenario": "把文字中的数量、关系词和未知量翻译成代数式，并说明每一项代表什么。",
        "variation_logic": ["给文字关系写式子", "给式子反写文字含义", "比较两个表达式是否对应同一语义", "修复括号或倍数关系漏写"],
        "evidence_goal": ["能定义未知量", "能把关系词转成运算", "能解释式子中每一部分含义"],
        "stretch_angle": "给多层关系，让孩子先画关系链再写代数式。",
        "common_traps": ["关键词直译导致顺序错", "倍数和多几混淆", "缺括号改变语义"],
    },
    "like_terms_boundary": {
        "core_scenario": "用字母部分完全相同来判断同类项，分清系数、字母和指数。",
        "variation_logic": ["从一组项中选同类项", "解释为什么不能合并", "合并后检查字母部分不变", "修复把不同指数合并的错解"],
        "evidence_goal": ["能识别字母部分", "能保持指数不变", "能区分系数合并和字母合并"],
        "stretch_angle": "给参数项，让孩子判断在什么条件下可能成为同类项。",
        "common_traps": ["只看字母种类不看指数", "合并时把指数相加", "把常数项和含字母项合并"],
    },
    "parenthesis_and_polynomial_repair": {
        "core_scenario": "围绕去括号、添括号和整式加减的等价性，要求孩子追踪符号分配到每一项。",
        "variation_logic": ["去带负号的括号", "比较两个整式是否等价", "修复漏分配或符号错", "把多项式按项重新组织"],
        "evidence_goal": ["能说明符号作用范围", "能逐项分配", "能用代入或还原检验等价"],
        "stretch_angle": "给一个目标整式，让孩子设计添括号方式并证明等价。",
        "common_traps": ["负号只改第一项", "漏乘括号内某一项", "合并同类项前改变项的符号"],
    },
    "expression_value_substitution": {
        "core_scenario": "把代入看作用具体数替换字母整体，重点处理括号、负数和运算顺序。",
        "variation_logic": ["代入负数求值", "比较先化简再代入和直接代入", "判断漏括号导致的错误", "用特殊值检验等价表达"],
        "evidence_goal": ["能完整替换字母", "能给负数加必要括号", "能按运算顺序求值"],
        "stretch_angle": "给两个代数式，让孩子用代入判断是否一定等价或找反例。",
        "common_traps": ["负数代入不加括号", "只替换一处字母", "先算指数或乘法对象错"],
    },
    "monomial_polynomial_structure": {
        "core_scenario": "用项、系数、次数和常数项建立单项式/多项式结构边界。",
        "variation_logic": ["指出一个式子的项和次数", "判断是否为单项式或多项式", "比较系数和次数的含义", "修复把加减拆项错误"],
        "evidence_goal": ["能按加减分项", "能识别系数和次数", "能处理常数项和零系数边界"],
        "stretch_angle": "给含参数的式子，让孩子判断结构会不会随参数取值改变。",
        "common_traps": ["把指数当系数", "把乘积拆成多项", "忽略常数项次数"],
    },
    "equivalent_expression_judgement": {
        "core_scenario": "通过变形依据、代入检验和反例构造判断两个表达式是否等价。",
        "variation_logic": ["让孩子判断一组表达式是否恒等", "用代入找反例", "说明某一步变形依据", "修复看起来像但不等价的式子"],
        "evidence_goal": ["能说出等价变形依据", "能用代入检验", "能构造反例排除假等价"],
        "stretch_angle": "给一个含参数条件的等价判断，让孩子说明在什么条件下成立。",
        "common_traps": ["只看形式相似", "用一个特殊值就证明恒等", "分配律或符号处理错误"],
    },
    "distributive_structure_bridge": {
        "core_scenario": "把小学分配律迁移到含字母表达式和去括号，强调每一项都被同一个因子作用。",
        "variation_logic": ["从数的简算过渡到字母分配", "判断一个去括号是否漏项", "用面积模型解释 a(b+c)", "反向提取公因式"],
        "evidence_goal": ["能保持等价", "能逐项分配", "能识别公因式"],
        "stretch_angle": "给含数字和字母的混合式，让孩子选择展开或保留结构并说明理由。",
        "common_traps": ["只乘第一项", "负号随括号丢失", "把分配律用于非乘法结构"],
    },
    "equation_concept_boundary": {
        "core_scenario": "用含未知数的等式、解和使等式成立的值来划清方程与代数式/恒等式的边界。",
        "variation_logic": ["判断哪些式子是方程", "检验某个数是不是解", "把文字条件写成方程", "找一个不是方程的反例"],
        "evidence_goal": ["能识别未知数和等号", "能说明解的含义", "能代入检验成立"],
        "stretch_angle": "给含参数的等式，让孩子判断是否总是方程或什么时候有特定解。",
        "common_traps": ["有字母就叫方程", "没有等号也当方程", "把解当作变形过程"],
    },
    "equation_transformation_legality": {
        "core_scenario": "围绕等式两边同做同一合法操作，判断移项、去括号、去分母为什么成立。",
        "variation_logic": ["判断一步变形是否合法", "修复只改一边的变形", "说明移项本质是两边同加减", "比较两个解法哪一步更稳"],
        "evidence_goal": ["能说明两边同操作", "能保持解集不变", "能检验变形后的方程"],
        "stretch_angle": "给一个会引入限制的变形场景，让孩子说明为什么当前七上范围应避开或补检验。",
        "common_traps": ["移项只换符号不知依据", "等式一边乘除另一边没变", "去分母漏乘常数项"],
    },
    "equation_word_modeling": {
        "core_scenario": "从应用题中定义未知量、找等量关系、列方程，并解释方程两边代表同一数量。",
        "variation_logic": ["用线段图或表格找等量关系", "比较两个设未知量方案", "判断方程是否对应题意", "修复漏条件或重复条件"],
        "evidence_goal": ["能定义未知量单位", "能找到等量关系", "能解释方程两边含义"],
        "stretch_angle": "给同一问题两种设法，让孩子比较哪个方程更简洁并求解。",
        "common_traps": ["只列式不设未知量", "等量关系左右不是同一对象", "把无关条件塞进方程"],
    },
    "linear_equation_solving_flow": {
        "core_scenario": "把一元一次方程求解拆成去括号、移项、合并、系数化一和验算的可追踪流程。",
        "variation_logic": ["补全缺失步骤", "判断某一步从哪里来", "选择更稳的解法顺序", "用代入验算发现错误"],
        "evidence_goal": ["能保持等式合法", "能整理同类项", "能代入验算解"],
        "stretch_angle": "给含同类项和常数分散的方程，让孩子先规划步骤再计算。",
        "common_traps": ["移项符号错", "合并项错", "最后除以系数对象错"],
    },
    "parenthesis_equation_flow": {
        "core_scenario": "专门检验含括号方程中去括号和后续移项的稳定性。",
        "variation_logic": ["去正系数括号", "去负系数括号", "比较先去括号和先合并的路径", "修复括号内漏乘问题"],
        "evidence_goal": ["能正确去括号", "能追踪符号", "能完成后续求解并验算"],
        "stretch_angle": "给两层括号或括号两边都有项的方程，让孩子判断最稳第一步。",
        "common_traps": ["括号只乘第一项", "负号分配错误", "去括号后同类项合并错"],
    },
    "denominator_equation_flow": {
        "core_scenario": "处理含分母方程的去分母流程，重点是公分母、每一项同乘和验算。",
        "variation_logic": ["找最小公分母", "判断去分母是否每项都乘", "修复漏乘整项", "去分母后继续求解"],
        "evidence_goal": ["能选择公分母", "能每项同乘", "能验算原方程"],
        "stretch_angle": "给两个去分母方案，让孩子比较哪一个更少出错并解释。",
        "common_traps": ["只给分式项乘公分母", "整常数项漏乘", "去分母后括号丢失"],
    },
    "known_unknown_relation_marking": {
        "core_scenario": "让孩子先标已知、未知和关系，再决定用算术、方程、比例还是图示。",
        "variation_logic": ["从短题干中标量和关系", "删掉干扰条件后列关系", "比较两个未知量设法", "补一条缺失关系让问题可解"],
        "evidence_goal": ["能标出已知未知", "能说出关键关系", "能判断信息是否足够"],
        "stretch_angle": "给一个条件不足或条件多余的问题，让孩子判断能不能解并说明原因。",
        "common_traps": ["看到数字就计算", "未知量没有单位", "把无关条件当关键关系"],
    },
    "motion_basic_model": {
        "core_scenario": "用路程、速度、时间三量关系和单位一致性建立基础行程模型。",
        "variation_logic": ["补全 s=vt 表格", "根据单位判断该乘还是除", "比较平均速度和单段速度", "修复单位不一致的列式"],
        "evidence_goal": ["能识别三量关系", "能统一单位", "能解释列式含义"],
        "stretch_angle": "给分段行程，让孩子判断是否能直接用总路程除总时间。",
        "common_traps": ["单位没统一", "速度和时间关系倒置", "平均速度误用单段速度"],
    },
    "motion_chase_meet_model": {
        "core_scenario": "用相对速度、距离差和同时性分析追及相遇问题。",
        "variation_logic": ["画线段图表示距离差", "判断用速度和还是速度差", "从相遇时间反推距离", "修复出发时间不同导致的错解"],
        "evidence_goal": ["能识别相对运动", "能表示距离差", "能处理同时出发或延迟出发"],
        "stretch_angle": "给同向追及和相向相遇混合表述，让孩子先分类再建模。",
        "common_traps": ["速度和差用反", "忽略先出发时间", "把相遇点当中点"],
    },
    "work_rate_model": {
        "core_scenario": "用工作总量、效率和时间关系，常把总量设为 1 来组织工程问题。",
        "variation_logic": ["补效率表", "判断合作效率是否相加", "从完成部分反推时间", "修复把时间直接相加的错误"],
        "evidence_goal": ["能设定工作总量", "能写出效率", "能用部分量检查进度"],
        "stretch_angle": "给中途加入或退出的合作场景，让孩子按时间段拆解。",
        "common_traps": ["把各自时间相加", "效率单位混乱", "合作段和单独段不分"],
    },
    "percent_application_model": {
        "core_scenario": "把折扣、增长、浓度等场景统一到基准量、百分率和结果量。",
        "variation_logic": ["找单位1", "从结果反推原量", "处理连续变化", "判断百分数条件是否对应同一基准"],
        "evidence_goal": ["能锁定基准量", "能建立百分数方程或算式", "能检验结果量方向"],
        "stretch_angle": "给先降后升或混合浓度，让孩子拆成连续步骤。",
        "common_traps": ["单位1找错", "百分数相加代替连续变化", "浓度和溶质量混淆"],
    },
    "proportion_table_model": {
        "core_scenario": "用比例表保持同类量横纵对应，避免比例关系错位。",
        "variation_logic": ["填比例表", "检查对应列是否同类", "用表格反推未知", "修复交叉相乘前对应关系错误"],
        "evidence_goal": ["能建立对应表", "能保持单位一致", "能说明每一列的比值"],
        "stretch_angle": "给三组量的复合比例，让孩子先选择两列建立关系。",
        "common_traps": ["横纵对应错位", "单位混列", "只会交叉相乘不知含义"],
    },
    "sum_difference_multiple_model": {
        "core_scenario": "用线段图或份数模型表达和、差、倍关系。",
        "variation_logic": ["从关系句画线段图", "先求一份量", "比较方程法和份数法", "修复把倍数对象弄反的错误"],
        "evidence_goal": ["能识别一份量", "能表示和差倍关系", "能解释每一步对应哪段"],
        "stretch_angle": "给多对象和差倍关系，让孩子选择主量并建立方程或线段图。",
        "common_traps": ["倍数对象反了", "差量当总量", "线段图与列式不一致"],
    },
    "clock_angle_model": {
        "core_scenario": "把钟表角转成时针、分针速度差和角度位置关系。",
        "variation_logic": ["计算整点附近夹角", "处理经过若干分钟后的角度", "判断锐角/钝角取哪一个", "修复时针不动的错误"],
        "evidence_goal": ["能知道分针和时针速度", "能建立相对角度", "能选择题目要求的角"],
        "stretch_angle": "给目标夹角反推时间，要求说明可能有几个解。",
        "common_traps": ["把时针看成不动", "只算大角或小角", "分钟造成的时针移动漏掉"],
    },
    "distractor_condition_filter": {
        "core_scenario": "给含多余或干扰信息的题干，让孩子先判定哪些条件真正参与关系。",
        "variation_logic": ["圈出必要条件", "判断某个条件是否多余", "删去干扰信息后建模", "补充最少条件使问题可解"],
        "evidence_goal": ["能识别目标问题", "能筛掉无关条件", "能说明条件如何进入模型"],
        "stretch_angle": "给一题多问或信息过量场景，让孩子为不同问题选择不同条件集合。",
        "common_traps": ["所有数字都用上", "忽略问题问的对象", "条件之间关系没建立"],
    },
    "object_representation_boundary": {
        "core_scenario": "区分点、线、面、体、角等几何对象和它们的符号、图形表示。",
        "variation_logic": ["判断图中对象是什么", "把文字对象转成符号表示", "说明表示方式的边界", "找出把图形外观当定义的错误"],
        "evidence_goal": ["能识别几何对象", "能使用正确表示", "能说明对象和图示不完全等同"],
        "stretch_angle": "给一个不标准示意图，让孩子判断哪些结论不能仅凭图看出来。",
        "common_traps": ["把画得长短当定义", "符号表示缺端点或顶点", "把线段射线直线混用"],
    },
    "segment_angle_part_whole": {
        "core_scenario": "用整体-部分关系表达线段长度和角度，建立相加、相减和中点/角平分线结构。",
        "variation_logic": ["从图中写部分和整体关系", "用中点或角平分线建立等量", "反推某一段或某一角", "修复把图形看成等分的错误"],
        "evidence_goal": ["能写出整体部分关系", "能使用中点或角平分线定义", "能说明计算依据"],
        "stretch_angle": "给含未知量的线段或角关系，让孩子列式并判断是否条件足够。",
        "common_traps": ["凭图目测相等", "整体部分关系写反", "中点/平分线条件误用"],
    },
    "net_and_view_matching": {
        "core_scenario": "通过空间想象和面之间邻接关系匹配展开图、三视图和立体结构。",
        "variation_logic": ["判断展开图能否折成立体", "根据三视图选择立体", "标记相对面或相邻面", "修复只数面不看邻接的错误"],
        "evidence_goal": ["能追踪面邻接", "能从不同视角对应形状", "能排除不可能结构"],
        "stretch_angle": "给带标记的展开图，让孩子判断折叠后两个标记面的关系。",
        "common_traps": ["只数面数", "相对面和相邻面混淆", "三视图方向对应错"],
    },
    "area_volume_formula_structure": {
        "core_scenario": "把面积体积公式还原成维度、底高关系和单位，而不是套公式。",
        "variation_logic": ["判断公式中每个量的意义", "单位换算后再计算", "比较等底等高关系", "修复面积体积单位混用"],
        "evidence_goal": ["能解释公式结构", "能处理单位维度", "能检查结果量纲"],
        "stretch_angle": "给组合图形或变形图形，让孩子拆分或等积转换。",
        "common_traps": ["长度单位直接当面积单位", "底和高不对应", "表面积和体积混淆"],
    },
    "line_ray_segment_representation": {
        "core_scenario": "区分直线、射线、线段的端点数量、延伸方向和符号表示。",
        "variation_logic": ["从图中命名对象", "判断两个表示是否同一对象", "补充端点或方向信息", "修复把射线反向等同的错误"],
        "evidence_goal": ["能区分端点和延伸", "能正确命名", "能判断表示是否唯一"],
        "stretch_angle": "给多个共线点，让孩子列出可确定的线段或射线并说明重复项。",
        "common_traps": ["射线 AB 和 BA 混同", "线段和直线表示混用", "忽略端点顺序"],
    },
    "angle_representation_measure": {
        "core_scenario": "围绕角的顶点、两边、表示和度量，强调角不是弧线标记本身。",
        "variation_logic": ["用三字母表示角", "判断角的顶点", "读量角器或估角", "修复角名顶点写错"],
        "evidence_goal": ["能识别顶点和边", "能正确表示角", "能解释度量结果"],
        "stretch_angle": "给多个角共顶点图，让孩子判断哪些角容易混淆并命名。",
        "common_traps": ["三字母角名顶点不居中", "把图上弧线当角", "量角器内外圈读反"],
    },
    "point_line_plane_generation": {
        "core_scenario": "用点动成线、线动成面、面动成体建立几何生成关系和空间想象。",
        "variation_logic": ["判断运动轨迹形成什么对象", "从截面或旋转想象立体", "比较生成过程和静态对象", "修复把边界当整体的错误"],
        "evidence_goal": ["能说明生成关系", "能进行简单空间想象", "能区分边界和整体"],
        "stretch_angle": "给一个平面图形旋转或平移，判断形成的立体或区域。",
        "common_traps": ["把线的移动轨迹只看成线", "边界和面积体积混淆", "旋转轴影响忽略"],
    },
    "unit_dimension_conversion": {
        "core_scenario": "用一维长度、二维面积、三维体积的单位维度解释换算倍数。",
        "variation_logic": ["长度单位换算", "面积单位换算", "体积单位换算", "用数量级检查换算方向"],
        "evidence_goal": ["能识别维度", "能选择正确换算倍数", "能用实际大小检验"],
        "stretch_angle": "给复合单位或几何公式场景，让孩子先统一单位再计算。",
        "common_traps": ["面积体积仍按长度倍数换", "大单位小单位方向反", "单位未统一就代公式"],
    },
}


def missing_family_design_kernels(family_ids: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    return sorted(
        {
            str(family_id)
            for family_id in family_ids
            if family_id and str(family_id) not in FAMILY_DESIGN_KERNELS
        }
    )


def _requirement_policy_overrides(
    *,
    node_id: str,
    family_id: str,
    coverage_role: str,
    evidence_goal: str,
    question_direction: str,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "evidence_goal": evidence_goal,
        "question_direction": question_direction,
        "must_include": [],
        "must_not_include": [],
    }
    if node_id == "M-G7-OPPOSITE" and family_id == "opposite_absolute_value_model" and coverage_role == "entry_probe":
        overrides["evidence_goal"] = "能说明相反数是在数轴上关于0对称，且0的相反数仍是0"
        overrides["question_direction"] = (
            "给距离和方向反推数；入口题只诊断相反数、关于0对称和0的特殊性，"
            "不把绝对值比较命题作为主要得分点"
        )
        overrides["must_include"] = [
            "必须围绕相反数和0的相反数建立主要得分点",
            "如出现绝对值，只能作为辅助背景，不能替代相反数诊断",
        ]
        overrides["must_not_include"] = [
            "未标 secondary node 时不要把绝对值作为主要得分点",
            "不要在相反数入口题中要求比较绝对值与原数大小",
        ]
    if family_id == "linear_equation_solving_flow":
        overrides["must_include"].append("每一次等式变形都要说明两边同做同一运算")
        if "补全缺失步骤" in question_direction:
            overrides["question_direction"] = f"{question_direction}；要求分别说明每个等式变形为什么合法"
            overrides["must_not_include"].append("只解释第一步合法性而不解释系数化一")
    return overrides


def _ordered_question_requirements(
    *,
    node: dict[str, Any],
    family_plan: list[dict[str, Any]],
    families: dict[str, dict[str, Any]],
    profile_contributions: dict[str, dict[str, Any]],
    design_brief_seed: str,
    max_attempts: int = 3,
) -> list[dict[str, Any]]:
    suggestions_by_family: dict[str, list[dict[str, Any]]] = {}
    for profile in profile_contributions.values():
        for suggestion in profile.get("suggestions") or []:
            family_id = str(suggestion.get("family_id") or "")
            if family_id:
                suggestions_by_family.setdefault(family_id, []).append(suggestion)

    slots: list[dict[str, Any]] = []
    slot_order = 1
    node_id = str(node.get("id") or "")
    node_name = str(node.get("name") or node_id)
    for family in family_plan:
        family_id = str(family.get("family_id") or "")
        target_count = int(family.get("target_count") or 0)
        family_meta = families.get(family_id) or {}
        execution_contract = _family_execution_contract(family, family_meta)
        difficulty_sequence = _difficulty_sequence(family)
        kernel = FAMILY_DESIGN_KERNELS.get(family_id, {})
        variations = list(kernel.get("variation_logic") or [])
        common_traps = list(kernel.get("common_traps") or [])
        family_suggestions = suggestions_by_family.get(family_id) or []
        expert_profiles = sorted({str(s.get("profile") or "") for s in family_suggestions if s.get("profile")})
        evidence_candidates: list[str] = []
        for suggestion in family_suggestions:
            evidence_candidates.extend(str(value) for value in suggestion.get("evidence_goal") or [])
        evidence_candidates.extend(str(value) for value in family.get("required_evidence") or [])
        evidence_candidates = list(dict.fromkeys(value for value in evidence_candidates if value))
        reject_patterns: list[str] = []
        for suggestion in family_suggestions:
            reject_patterns.extend(str(value) for value in suggestion.get("reject_patterns") or [])
        reject_patterns = list(dict.fromkeys(value for value in reject_patterns if value))

        for offset in range(target_count):
            difficulty = difficulty_sequence[offset]
            coverage_role = (
                "support_only"
                if execution_contract["support_only"]
                else _coverage_role(offset, difficulty)
            )
            evidence_goal = evidence_candidates[offset % len(evidence_candidates)] if evidence_candidates else f"能围绕{node_name}给出可观察数学证据"
            direction = variations[offset % len(variations)] if variations else f"围绕“{node_name}”设计一个有明确条件、可检查结论和过程证据的题。"
            policy = _requirement_policy_overrides(
                node_id=node_id,
                family_id=family_id,
                coverage_role=coverage_role,
                evidence_goal=evidence_goal,
                question_direction=direction,
            )
            evidence_goal = str(policy["evidence_goal"])
            direction = str(policy["question_direction"])
            family_evidence = [
                str(value)
                for value in family.get("required_evidence") or []
                if str(value).strip()
            ]
            primary_evidence = (
                family_evidence[offset % len(family_evidence)]
                if family_evidence
                else evidence_goal
            )
            must_include = list(
                dict.fromkeys(
                    [
                        evidence_goal,
                        primary_evidence,
                        f"题面和得分点必须落实当前方向：{direction}",
                        "只要求支撑当前证据目标的最少数学证据，不得附带同题型其他 slot 的诊断任务",
                        *list(policy["must_include"]),
                    ]
                )
            )
            target_misconceptions = (
                [str(common_traps[offset % len(common_traps)])]
                if common_traps
                else []
            )
            slot_id = f"{node_id}:{family_id}:{offset + 1:02d}"
            slots.append(
                {
                    "slot_id": slot_id,
                    "question_requirement_id": _requirement_id(
                        node_id=node_id,
                        family_id=family_id,
                        slot_order=slot_order,
                        design_brief_seed=design_brief_seed,
                    ),
                    "slot_order": slot_order,
                    "node_id": node_id,
                    "node_name": node_name,
                    "family_id": family_id,
                    "difficulty": difficulty,
                    "coverage_role": coverage_role,
                    "evidence_goal": evidence_goal,
                    "question_direction": direction,
                    "must_include": must_include,
                    "must_not_include": list(dict.fromkeys(list(policy["must_not_include"]) + reject_patterns))[:8],
                    "target_misconceptions": target_misconceptions,
                    "max_attempts": max_attempts,
                    "expert_basis_profiles": expert_profiles,
                    **execution_contract,
                    "status": "requirement_ready",
                }
            )
            slot_order += 1
    return slots


def _items_for_node(items: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("node_id") == node_id]


def _family_counts(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("question_type") or "") for item in items)


def _family_name(families: dict[str, dict[str, Any]], family_id: str) -> str:
    return str((families.get(family_id) or {}).get("family_name") or family_id)


def _profile_family_idea(
    *,
    profile_id: str,
    node: dict[str, Any],
    family: dict[str, Any],
    family_meta: dict[str, Any],
    existing_count: int,
) -> dict[str, Any]:
    family_id = str(family.get("family_id") or "")
    difficulty = list(family.get("difficulty") or family_meta.get("difficulty_range") or [])
    evidence_focus = list(family.get("evidence_focus") or family_meta.get("measures") or [])
    required_evidence = list(family.get("required_evidence") or [])
    target_count = int(family.get("target_count") or 0)
    missing = max(0, target_count - existing_count)
    angle = PROFILE_DESIGN_ANGLES[profile_id]
    kernel = FAMILY_DESIGN_KERNELS.get(family_id, {})
    execution_contract = _family_execution_contract(family, family_meta)
    core_scenario = family.get("question_direction") or kernel.get("core_scenario") or f"围绕“{node.get('name')}”的核心关系设计具体、有条件、有判断目标的任务。"
    variation_logic = list(kernel.get("variation_logic") or ["改变表示方式", "改变条件方向", "加入检验或错因辨析"])
    kernel_evidence = list(family.get("observable_evidence") or kernel.get("evidence_goal") or required_evidence or evidence_focus)
    stretch_angle = family.get("stretch_boundary") or kernel.get("stretch_angle") or "通过边界、反例、逆向或迁移改变思考方向，而不是增加计算量。"
    common_traps = list(family.get("typical_misconceptions") or kernel.get("common_traps") or ["只写答案", "缺少关键关系", "无法检验结论"])

    if profile_id == "frontline_math_teacher":
        design = f"{core_scenario} 题面应像真实课堂追问：先让孩子作判断，再用一句话说明依据。"
        reject = ["只换数字的低龄练习", "只要求最终答案", "题干像后台任务说明"]
    elif profile_id == "bridge_diagnosis_teacher":
        design = f"用“{variation_logic[0]}”和“{variation_logic[min(1, len(variation_logic)-1)]}”做成诊断探针；错了以后能区分本节点断点、前置断点和表达不完整。"
        reject = ["错了只能继续刷同类题", "无法判断是概念错还是计算错", "没有回退候选"]
    elif profile_id == "stretch_competition_teacher":
        design = stretch_angle
        reject = ["数字变大造成的伪难", "超出主线过远的竞赛技巧", "失败后反向否定基础掌握"]
    elif profile_id == "assessment_expert":
        design = f"评分合同要围绕这些证据：{'、'.join(kernel_evidence[:4])}。允许等价表达，但必须能区分“会但写少了”和“模型没懂”。"
        reject = ["泛化评分模板", "缺少 accepted alternatives", "把非关键书写作为主扣分项"]
    else:
        design = f"可参考外部资料的范围或结构，如“{core_scenario}”，但题干、数值、图形、解析和结构指纹必须重新原创。"
        reject = ["复制商业题干", "改数字洗题", "保存未经许可的图形或解析"]

    return {
        "profile": profile_id,
        "profile_display": EXPERT_PROFILES[profile_id]["display"],
        "family_id": family_id,
        "family_name": _family_name({family_id: family_meta}, family_id),
        "target_count": target_count,
        "existing_count": existing_count,
        "missing_to_target": missing,
        "difficulty": difficulty,
        "difficulty_distribution": dict(family.get("difficulty_distribution") or {}),
        "evidence_focus": evidence_focus,
        "required_evidence": required_evidence,
        "design_idea": design,
        "core_scenario": core_scenario,
        "variation_logic": variation_logic,
        "evidence_goal": kernel_evidence,
        "target_misconceptions": common_traps,
        "why": angle["principle"],
        "reject_patterns": reject,
        **execution_contract,
    }


def build_expert_design_ideas(
    *,
    root: Path,
    node_id: str,
    version: str = "v18",
    subject: str = "math",
) -> dict[str, Any]:
    paths = AdminPaths(root=root)
    graph, _sample, blueprints_json, taxonomy = _load_assets(paths)
    bank_path = _question_bank_path(paths, version)
    bank = _load_json(bank_path)
    graph_nodes = _graph_nodes_by_id(graph)
    blueprints = _blueprints_by_node(blueprints_json)
    families = _families_by_id(taxonomy)
    if node_id not in graph_nodes:
        raise ValueError(f"ADMIN_UNKNOWN_GRAPH_NODE: {node_id}")
    if node_id not in blueprints:
        raise ValueError(f"ADMIN_MISSING_NODE_BLUEPRINT: {node_id}")

    node = graph_nodes[node_id]
    blueprint = blueprints[node_id]
    node_items = _items_for_node(list(bank.get("items") or []), node_id)
    counts = _family_counts(node_items)

    family_plan = list(blueprint.get("family_plan") or [])
    profile_contributions: dict[str, dict[str, Any]] = {}
    all_ideas: list[dict[str, Any]] = []
    for profile_id in EXPERT_PROFILES:
        suggestions = []
        for family in family_plan:
            family_id = str(family.get("family_id") or "")
            family_meta = families.get(family_id) or {}
            existing_count = counts.get(family_id, 0)
            idea = _profile_family_idea(
                profile_id=profile_id,
                node=node,
                family=family,
                family_meta=family_meta,
                existing_count=existing_count,
            )
            suggestions.append(idea)
            all_ideas.append(idea)
        profile_contributions[profile_id] = {
            "display": EXPERT_PROFILES[profile_id]["display"],
            "design_principle": PROFILE_DESIGN_ANGLES[profile_id]["principle"],
            "idea_focus": PROFILE_DESIGN_ANGLES[profile_id]["idea_focus"],
            "suggestions": suggestions,
        }

    missing_families = [
        str(family.get("family_id"))
        for family in family_plan
        if counts.get(str(family.get("family_id") or ""), 0) < int(family.get("target_count") or 0)
    ]
    report_id_input = "|".join([node_id, str(bank.get("question_bank_version") or version), json.dumps(counts, sort_keys=True)])
    report_id = "EXPERT-IDEAS-" + hashlib.sha256(report_id_input.encode("utf-8")).hexdigest()[:12]
    question_requirements = _ordered_question_requirements(
        node=node,
        family_plan=family_plan,
        families=families,
        profile_contributions=profile_contributions,
        design_brief_seed=report_id,
    )
    return {
        "schema_version": "2026-07-23.codex-admin.expert-design-ideas.v1",
        "report_id": report_id,
        "subject": subject,
        "node_id": node_id,
        "node_name": node.get("name"),
        "node_essence": node.get("essence_for_child"),
        "question_bank_version": str(bank.get("question_bank_version") or version),
        "question_bank_status": str(bank.get("status") or "unknown"),
        "current_item_count": len(node_items),
        "counts_by_family": dict(sorted(counts.items())),
        "candidate_budget": blueprint.get("candidate_budget"),
        "missing_or_underfilled_families": missing_families,
        "profile_contributions": profile_contributions,
        "idea_count": len(all_ideas),
        "requirement_count": len(question_requirements),
        "question_requirements": question_requirements,
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["use_requirements_as_generation_slots", "human_review_design_ideas", "do_not_activate_directly"],
    }


def render_expert_design_ideas_markdown(report: dict[str, Any]) -> str:
    profile_sections = []
    for profile_id, profile in report["profile_contributions"].items():
        rows = []
        for idea in profile["suggestions"]:
            rows.append(
                f"| {idea['family_id']} | {idea['missing_to_target']} | "
                f"{'、'.join(idea['evidence_goal'][:3])} | {idea['design_idea']} |"
            )
        if not rows:
            rows.append("| | | | |")
        profile_sections.append(
            f"""### {profile['display']} (`{profile_id}`)

Design principle: {profile['design_principle']}

Idea focus: {profile['idea_focus']}

| Family | Missing To Target | Evidence Focus | Design Idea |
|---|---:|---|---|
{chr(10).join(rows)}
"""
        )
    return f"""# Expert Question-Type Design Ideas

Status: `IDEAS_READY`

Created At: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

Subject: {report['subject']}

Node: {report['node_id']} {report['node_name']}

Node Essence: {report['node_essence']}

Question Bank: {report['question_bank_version']}

Current Item Count: {report['current_item_count']}

Activation Implication: `{report['activation_implication']}`

## Current Coverage

```json
{json.dumps(report['counts_by_family'], ensure_ascii=False, indent=2, sort_keys=True)}
```

Missing or underfilled families:

```json
{json.dumps(report['missing_or_underfilled_families'], ensure_ascii=False, indent=2, sort_keys=True)}
```

## Ordered Question Requirements

| # | Slot | Family | Difficulty | Coverage Role | Evidence Goal | Direction |
|---:|---|---|---|---|---|---|
{chr(10).join([
    f"| {slot['slot_order']} | {slot['slot_id']} | {slot['family_id']} | {slot['difficulty']} | {slot['coverage_role']} | {slot['evidence_goal']} | {slot['question_direction']} |"
    for slot in report.get('question_requirements') or []
]) or "| | | | | | | |"}

## Expert Contributions

{chr(10).join(profile_sections)}

## Next Actions

- Use the ordered requirements as one-question generation slots for 命题 Agent.
- Human/Codex review should decide which ideas become generation tasks.
- This document does not authorize activation or child runtime use.
"""


def write_expert_design_ideas(report: dict[str, Any], *, root: Path, apply: bool = False) -> dict[str, Any]:
    markdown_rel = Path("docs/system/admin_reports/design_ideas") / f"{datetime.now(timezone.utc).date()}-{report['report_id']}.md"
    json_rel = Path("data/admin/design_ideas") / f"{report['report_id']}.json"
    result = {
        **report,
        "design_markdown_path": str(markdown_rel),
        "design_json_path": str(json_rel),
        "write_applied": bool(apply),
    }
    if not apply:
        return result
    markdown = render_expert_design_ideas_markdown(report)
    markdown_path = root / markdown_rel
    json_path = root / json_rel
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    result["design_markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["design_json_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    return result
