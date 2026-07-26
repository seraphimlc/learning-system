#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
TAXONOMY_PATH = ROOT / "data/question_banks/v18/question_type_taxonomy_v18.json"
BLUEPRINT_PATH = ROOT / "data/question_banks/v18/node_question_blueprints_v18.json"

SCHEMA_VERSION = "2026-07-22.node-question-blueprints.v18"
TAXONOMY_SCHEMA_VERSION = "2026-07-22.question-type-taxonomy.v18"


FAMILY_DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "number_ops": [
        {
            "family_id": "estimate_direction_and_magnitude",
            "family_name": "估算方向与数量级",
            "measures": ["model_relation", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["要求先判断范围、方向或数量级", "允许精算验证"],
            "forbidden_surface_features": ["只要求竖式计算", "只换数字"],
            "scoring_basis": ["估算基准", "误差方向", "精算或合理校验"],
            "typical_error_mapping": ["数量级失控", "小数点位置错误", "不做估算"],
        },
        {
            "family_id": "structure_based_simplification",
            "family_name": "结构化简算",
            "measures": ["model_relation", "procedure", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["存在凑整、拆分、等价转化或运算律结构"],
            "forbidden_surface_features": ["只考口算速度", "没有结构选择空间"],
            "scoring_basis": ["识别结构", "正确拆分重组", "结果正确"],
            "typical_error_mapping": ["只会硬算", "看不出运算律", "重组后漏项"],
        },
        {
            "family_id": "integer_structure_arithmetic",
            "family_name": "整数结构运算",
            "measures": ["calculation", "model_relation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含拆数、凑整、验算或整数关系表达"],
            "forbidden_surface_features": ["低龄竖式训练", "只考单步口算"],
            "scoring_basis": ["结构识别", "运算律使用", "验算或反向检查"],
            "typical_error_mapping": ["进退位错", "漏位", "验算缺失", "结构表达弱"],
        },
        {
            "family_id": "decimal_place_value_ops",
            "family_name": "小数位值与等价转化",
            "measures": ["calculation", "representation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含小数点位置、除数转整数或小数倍数关系"],
            "forbidden_surface_features": ["只按整数套算不检查小数点", "纯整数题"],
            "scoring_basis": ["位值判断", "等价扩大/缩小", "估算检验"],
            "typical_error_mapping": ["小数点错位", "除数转整数时只移动一边", "结果范围离谱"],
        },
        {
            "family_id": "wrong_solution_repair_number",
            "family_name": "数与运算错解修复",
            "measures": ["concept", "procedure", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["给出明确错解", "要求指出错因和修正"],
            "forbidden_surface_features": ["没有错解却要求找错", "错因和例子不属于同一数学任务"],
            "scoring_basis": ["定位首错", "解释错因", "给出修正"],
            "typical_error_mapping": ["运算顺序错误", "符号错误", "小数点错误", "通分或倒数错误"],
        },
        {
            "family_id": "signed_operation_model",
            "family_name": "有理数符号运算模型",
            "measures": ["concept", "model_relation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含有理数加减乘除动作", "要求解释符号来源"],
            "forbidden_surface_features": ["只比较有理数大小", "只在数轴上找位置"],
            "scoring_basis": ["运算类型", "符号规则", "绝对值计算", "结论"],
            "typical_error_mapping": ["减法未转加法", "同号异号规则混淆", "乘除符号判断错"],
        },
        {
            "family_id": "operation_order_control",
            "family_name": "运算顺序与括号控制",
            "measures": ["procedure", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["含括号、乘除同级、乘方或多步顺序判断"],
            "forbidden_surface_features": ["一步口算", "顺序不影响结果的伪混合运算"],
            "scoring_basis": ["优先级判断", "同级顺序", "关键步骤保留"],
            "typical_error_mapping": ["先后顺序错", "同级不从左到右", "括号作用看错"],
        },
        {
            "family_id": "fraction_unit_and_equivalence",
            "family_name": "分数意义与等价表示",
            "measures": ["concept", "representation", "model_relation"],
            "difficulty_range": ["L2", "L3", "L4"],
            "required_surface_features": ["要求找单位1、分率或等价分数含义"],
            "forbidden_surface_features": ["只有通分计算", "单位1不明确"],
            "scoring_basis": ["单位1", "分率/数量区分", "等价表示"],
            "typical_error_mapping": ["单位1找错", "把分率当具体数量", "约分扩分无意义"],
        },
        {
            "family_id": "fraction_operation_structure",
            "family_name": "分数运算结构",
            "measures": ["procedure", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["含通分、约分、倒数或分数混合运算的选择"],
            "forbidden_surface_features": ["只做整数计算", "不需要分数规则也能完成"],
            "scoring_basis": ["通分或倒数规则", "约分", "结果范围"],
            "typical_error_mapping": ["只改分母", "除法忘倒数", "约分不彻底"],
        },
        {
            "family_id": "percent_rate_change",
            "family_name": "百分率与变化量",
            "measures": ["concept", "model_relation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["区分标准量、比较量、变化量或变化率"],
            "forbidden_surface_features": ["只做百分数小数互化", "没有单位1"],
            "scoring_basis": ["单位1", "比较量/标准量", "增长量/增长率区分"],
            "typical_error_mapping": ["单位1错", "增长率和增长量混淆", "百分号乱用"],
        },
        {
            "family_id": "ratio_proportion_structure",
            "family_name": "比和比例结构",
            "measures": ["model_relation", "representation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含对应量、比值、比例尺或按比例分配"],
            "forbidden_surface_features": ["只化简数字比", "对应关系不清"],
            "scoring_basis": ["对应量", "比值意义", "比例式或份数结构"],
            "typical_error_mapping": ["对应量错位", "把比值当具体量", "比例尺方向反了"],
        },
        {
            "family_id": "number_classification_boundary",
            "family_name": "数的分类与边界",
            "measures": ["concept", "representation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求按正负零、整数分数或有理数边界分类"],
            "forbidden_surface_features": ["只比较大小", "只做计算"],
            "scoring_basis": ["分类标准", "边界样例", "反例判断"],
            "typical_error_mapping": ["0归类错误", "有限小数和分数关系不清", "负分数漏掉"],
        },
        {
            "family_id": "number_line_position_distance",
            "family_name": "数轴位置与距离",
            "measures": ["representation", "concept", "model_relation"],
            "difficulty_range": ["L2", "L3", "L4"],
            "required_surface_features": ["包含方向、位置、距离或中点关系"],
            "forbidden_surface_features": ["只有加减运算没有数轴意义"],
            "scoring_basis": ["方向", "距离", "位置关系"],
            "typical_error_mapping": ["左右方向反", "距离和坐标混淆", "负数大小判断错"],
        },
        {
            "family_id": "opposite_absolute_value_model",
            "family_name": "相反数与绝对值模型",
            "measures": ["concept", "representation", "calculation"],
            "difficulty_range": ["L2", "L3", "L4"],
            "required_surface_features": ["要求区分符号、相反数、到0距离或多重负号"],
            "forbidden_surface_features": ["只做两个数大小比较"],
            "scoring_basis": ["到0距离", "符号处理", "对称关系"],
            "typical_error_mapping": ["绝对值当去负号", "相反数和倒数混淆", "多重负号错"],
        },
        {
            "family_id": "power_base_sign",
            "family_name": "乘方底数与符号",
            "measures": ["concept", "procedure", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含负底数、括号底数或指数意义"],
            "forbidden_surface_features": ["只做正整数幂口算"],
            "scoring_basis": ["底数识别", "指数意义", "符号判断"],
            "typical_error_mapping": ["-2^2与(-2)^2混淆", "指数当乘数", "偶奇次符号错"],
        },
        {
            "family_id": "scientific_notation_precision",
            "family_name": "科学记数法与近似精度",
            "measures": ["representation", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含a×10^n规范、还原或精确度判断"],
            "forbidden_surface_features": ["只移动小数点但不判断规范范围"],
            "scoring_basis": ["a的范围", "指数", "精确到哪一位"],
            "typical_error_mapping": ["指数方向反", "a不在1到10之间", "精确度误判"],
        },
    ],
    "algebra": [
        {
            "family_id": "verbal_to_expression",
            "family_name": "文字关系转代数式",
            "measures": ["model_relation", "representation", "expression_notation"],
            "difficulty_range": ["L2", "L3", "L4"],
            "required_surface_features": ["给出真实数量关系", "要求写代数式或解释字母含义"],
            "forbidden_surface_features": ["只给裸代数式求值"],
            "scoring_basis": ["对象定义", "关系表达", "书写规范"],
            "typical_error_mapping": ["字母意义不清", "数量关系反了", "省略乘号不规范"],
        },
        {
            "family_id": "like_terms_boundary",
            "family_name": "同类项边界辨析",
            "measures": ["concept", "model_relation", "expression_notation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含可混淆的字母或指数", "要求说明能否合并"],
            "forbidden_surface_features": ["只合并显然同类项"],
            "scoring_basis": ["字母相同", "指数相同", "只合并系数"],
            "typical_error_mapping": ["看系数判断同类项", "指数看错", "合并字母部分"],
        },
        {
            "family_id": "parenthesis_and_polynomial_repair",
            "family_name": "去括号与整式错解修复",
            "measures": ["procedure", "calculation", "expression_notation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含括号、负号或整式加减错解"],
            "forbidden_surface_features": ["没有字母结构", "只做整数分配律"],
            "scoring_basis": ["括号前符号/系数", "每项处理", "同类项合并"],
            "typical_error_mapping": ["负号只变第一项", "漏乘括号内某项", "不同类项误合并"],
        },
        {
            "family_id": "expression_value_substitution",
            "family_name": "代数式求值与代入边界",
            "measures": ["procedure", "calculation", "expression_notation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["含负数、分数或先化简再代入的选择"],
            "forbidden_surface_features": ["纯数字运算", "代入值不影响核心难点"],
            "scoring_basis": ["代入括号", "先化简策略", "符号计算"],
            "typical_error_mapping": ["负数代入漏括号", "先代入导致复杂错误", "分数计算错"],
        },
        {
            "family_id": "monomial_polynomial_structure",
            "family_name": "单项式多项式结构",
            "measures": ["concept", "representation", "expression_notation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求识别项、系数、次数、常数项或几次几项式"],
            "forbidden_surface_features": ["只做合并同类项"],
            "scoring_basis": ["项的切分", "系数", "次数"],
            "typical_error_mapping": ["把减号丢掉", "次数相加错误", "常数项漏判"],
        },
        {
            "family_id": "equivalent_expression_judgement",
            "family_name": "等价表达判断",
            "measures": ["concept", "model_relation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["要求判断两个表达式是否恒等或给反例"],
            "forbidden_surface_features": ["只代一个特殊值就绝对下结论"],
            "scoring_basis": ["化简比较", "反例", "变量范围"],
            "typical_error_mapping": ["特例当通解", "括号符号错", "结构不等价"],
        },
        {
            "family_id": "distributive_structure_bridge",
            "family_name": "分配律到去括号桥梁",
            "measures": ["model_relation", "procedure", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["连接乘法分配律、括号前系数或负号"],
            "forbidden_surface_features": ["只做低龄凑整简算"],
            "scoring_basis": ["分配对象", "每项处理", "反向提取结构"],
            "typical_error_mapping": ["漏乘项", "负号分配错", "只会数字简算"],
        },
    ],
    "equation": [
        {
            "family_id": "equation_concept_boundary",
            "family_name": "方程概念边界",
            "measures": ["concept", "representation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求判断方程、一元一次方程或方程的解"],
            "forbidden_surface_features": ["直接求解复杂方程", "只有算式没有未知数"],
            "scoring_basis": ["未知数", "等式", "一次", "解的代回"],
            "typical_error_mapping": ["表达式当方程", "含未知数就当一元一次", "解的意义不清"],
        },
        {
            "family_id": "equation_transformation_legality",
            "family_name": "等式变形合法性",
            "measures": ["concept", "procedure", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["要求判断两边同做的变形是否合法"],
            "forbidden_surface_features": ["只做移项口号", "不体现等式两边同步"],
            "scoring_basis": ["等式性质", "非零除数", "每项同乘"],
            "typical_error_mapping": ["只改一边", "除以可能为0的量", "去分母漏项"],
        },
        {
            "family_id": "equation_word_modeling",
            "family_name": "方程应用建模",
            "measures": ["model_relation", "representation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["真实情境", "设未知数", "写等量关系"],
            "forbidden_surface_features": ["裸方程", "只算术不建模"],
            "scoring_basis": ["设元", "等量关系", "解与题意检验"],
            "typical_error_mapping": ["未知数含义不清", "等量关系错", "答案不合题意"],
        },
        {
            "family_id": "linear_equation_solving_flow",
            "family_name": "一元一次方程求解流程",
            "measures": ["procedure", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含移项、合并、系数化1或代回检验"],
            "forbidden_surface_features": ["只判断概念", "只有口算一步"],
            "scoring_basis": ["移项变号", "合并同类项", "系数化1", "代回"],
            "typical_error_mapping": ["移项不变号", "系数化1错", "不代回"],
        },
        {
            "family_id": "parenthesis_equation_flow",
            "family_name": "含括号方程求解",
            "measures": ["procedure", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["方程中含括号前系数或负号"],
            "forbidden_surface_features": ["只做整式去括号不解方程"],
            "scoring_basis": ["去括号", "移项", "合并", "检验"],
            "typical_error_mapping": ["括号内漏乘", "负号漏分配", "移项错"],
        },
        {
            "family_id": "denominator_equation_flow",
            "family_name": "含分母方程求解",
            "measures": ["procedure", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["含分母或分数系数，要求说明最小公倍数同乘"],
            "forbidden_surface_features": ["去分母不涉及每一项", "只是分数运算"],
            "scoring_basis": ["找公分母", "每一项同乘", "后续求解", "检验"],
            "typical_error_mapping": ["漏乘常数项", "分子括号丢失", "公分母错误"],
        },
    ],
    "application_modeling": [
        {
            "family_id": "known_unknown_relation_marking",
            "family_name": "已知未知与关系标注",
            "measures": ["model_relation", "representation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求标注对象、已知、未知和关系"],
            "forbidden_surface_features": ["看到数字直接算", "没有真实关系"],
            "scoring_basis": ["对象", "已知未知", "关系句"],
            "typical_error_mapping": ["问题读错", "对象混淆", "关系缺失"],
        },
        {
            "family_id": "motion_basic_model",
            "family_name": "行程基础模型",
            "measures": ["model_relation", "calculation", "unit"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["路程、速度、时间三量关系和单位一致性"],
            "forbidden_surface_features": ["无单位纯乘法", "追及相遇结构却当普通行程"],
            "scoring_basis": ["s=vt关系", "单位统一", "所求量"],
            "typical_error_mapping": ["单位不统一", "速度时间混淆", "公式套反"],
        },
        {
            "family_id": "motion_chase_meet_model",
            "family_name": "追及相遇模型",
            "measures": ["model_relation", "representation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["体现相向速度和或同向速度差"],
            "forbidden_surface_features": ["普通速度×时间", "没有初始距离"],
            "scoring_basis": ["相对速度", "初始距离", "时间关系"],
            "typical_error_mapping": ["速度和差用反", "先走时间漏算", "单位错"],
        },
        {
            "family_id": "work_rate_model",
            "family_name": "工程效率模型",
            "measures": ["model_relation", "representation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["工作总量设为1，单独效率与合作效率"],
            "forbidden_surface_features": ["速度×时间路程题", "只问单人完成不用效率"],
            "scoring_basis": ["总量1", "效率", "合作或先后时间"],
            "typical_error_mapping": ["把天数相加", "效率和天数混淆", "合作效率漏加"],
        },
        {
            "family_id": "percent_application_model",
            "family_name": "百分数应用模型",
            "measures": ["model_relation", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["折扣、增长率、正确率或利润率中的单位1明确"],
            "forbidden_surface_features": ["只做互化", "没有比较基准"],
            "scoring_basis": ["单位1", "比较量", "变化后数量"],
            "typical_error_mapping": ["基准错", "折扣和降价率混淆", "利润率分母错"],
        },
        {
            "family_id": "proportion_table_model",
            "family_name": "比例对应量表",
            "measures": ["model_relation", "representation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["要求用表格或对应量建立比例关系"],
            "forbidden_surface_features": ["只化简比", "对应方向不明"],
            "scoring_basis": ["对应表", "比例式", "单位或比例尺方向"],
            "typical_error_mapping": ["对应项错位", "比例尺方向反", "正比例误判"],
        },
        {
            "family_id": "sum_difference_multiple_model",
            "family_name": "和差倍模型",
            "measures": ["model_relation", "representation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["含和、差、倍数或年龄差不变结构"],
            "forbidden_surface_features": ["普通四则题", "没有两个对象关系"],
            "scoring_basis": ["基准量", "和差倍关系", "答案检验"],
            "typical_error_mapping": ["倍数对象反了", "差不变没抓住", "单位不一致"],
        },
        {
            "family_id": "clock_angle_model",
            "family_name": "钟表角模型",
            "measures": ["model_relation", "geometry_relation", "calculation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含时针分针速度差或夹角两解"],
            "forbidden_surface_features": ["普通角度加减", "没有钟表运动关系"],
            "scoring_basis": ["初始角", "相对角速度", "夹角取小角"],
            "typical_error_mapping": ["忽略时针移动", "只给一个夹角", "速度差用错"],
        },
        {
            "family_id": "distractor_condition_filter",
            "family_name": "干扰条件筛选",
            "measures": ["model_relation", "reading", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含至少一个无关或易误用条件"],
            "forbidden_surface_features": ["所有数字都必须用的机械题"],
            "scoring_basis": ["目标识别", "必要条件", "舍弃理由"],
            "typical_error_mapping": ["看见数字就用", "问题目标读错", "关系缺证据"],
        },
    ],
    "geometry": [
        {
            "family_id": "object_representation_boundary",
            "family_name": "几何对象与表示边界",
            "measures": ["concept", "representation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求辨析点线面体、直线射线线段或角的表示"],
            "forbidden_surface_features": ["只做角度计算", "对象没有边界差异"],
            "scoring_basis": ["对象特征", "表示方法", "反例"],
            "typical_error_mapping": ["符号表示错", "有限无限混淆", "对象维度混淆"],
        },
        {
            "family_id": "segment_angle_part_whole",
            "family_name": "线段/角整体部分关系",
            "measures": ["geometry_relation", "calculation", "representation"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含中点、角平分线、和差或余角补角关系"],
            "forbidden_surface_features": ["只有数字加减没有图形关系"],
            "scoring_basis": ["整体部分关系", "几何语言翻译", "计算"],
            "typical_error_mapping": ["中点/平分线定义错", "余角补角混淆", "图形关系漏写"],
        },
        {
            "family_id": "net_and_view_matching",
            "family_name": "展开图与三视图匹配",
            "measures": ["visual_spatial", "representation", "check"],
            "difficulty_range": ["L3", "L4", "L5"],
            "required_surface_features": ["包含展开图相对面、三视图或小正方体组合"],
            "forbidden_surface_features": ["角平分线题", "没有图形结构的纯文字题"],
            "scoring_basis": ["空间对应", "可折叠性", "视图方向"],
            "typical_error_mapping": ["相对面判断错", "视图方向混淆", "隐藏方块漏算"],
        },
        {
            "family_id": "area_volume_formula_structure",
            "family_name": "面积体积公式结构理解",
            "measures": ["model_relation", "geometry_relation", "unit"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["要求解释公式来源、单位维度或组合图形"],
            "forbidden_surface_features": ["角度题", "只套公式无结构"],
            "scoring_basis": ["底/高/半径等量", "公式结构", "单位维度"],
            "typical_error_mapping": ["面积体积单位混淆", "半径直径混淆", "组合图形拆分错"],
        },
        {
            "family_id": "line_ray_segment_representation",
            "family_name": "直线射线线段表示",
            "measures": ["concept", "representation", "check"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["比较直线、射线、线段的端点、延伸和表示"],
            "forbidden_surface_features": ["线段长度计算为主"],
            "scoring_basis": ["端点个数", "延伸方向", "表示符号"],
            "typical_error_mapping": ["射线方向错", "直线可测量误判", "表示顺序混淆"],
        },
        {
            "family_id": "angle_representation_measure",
            "family_name": "角的表示与度量",
            "measures": ["concept", "representation", "geometry_relation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求表示角、分类角或读量角器"],
            "forbidden_surface_features": ["角度和差计算为主"],
            "scoring_basis": ["顶点", "边", "表示法", "度量"],
            "typical_error_mapping": ["顶点字母不居中", "内外圈读错", "角分类边界错"],
        },
        {
            "family_id": "point_line_plane_generation",
            "family_name": "点线面体生成关系",
            "measures": ["concept", "visual_spatial", "representation"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求解释点动成线、线动成面、面动成体或元素关系"],
            "forbidden_surface_features": ["体积公式计算"],
            "scoring_basis": ["维度变化", "元素关系", "实例匹配"],
            "typical_error_mapping": ["维度混淆", "元素和整体混淆", "生活例子不对应"],
        },
        {
            "family_id": "unit_dimension_conversion",
            "family_name": "单位维度换算",
            "measures": ["unit", "calculation", "check"],
            "difficulty_range": ["L3", "L4"],
            "required_surface_features": ["包含长度、面积、体积、时间或人民币单位的维度差异"],
            "forbidden_surface_features": ["只移动小数点不说明维度", "面积体积公式成为主考点"],
            "scoring_basis": ["单位维度", "进率", "方向"],
            "typical_error_mapping": ["平方/立方进率错", "大单位小单位方向反", "复合单位漏换"],
        },
    ],
    "learning_process": [
        {
            "family_id": "solution_trace_repair",
            "family_name": "过程复盘与补证据",
            "support_only": True,
            "measures": ["process", "check", "expression"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求补关键步骤、检验、单位或答句"],
            "forbidden_surface_features": ["把非关键书写当主扣分", "只看标准答案字面一致"],
            "scoring_basis": ["关键证据", "检验", "表达足够清楚"],
            "typical_error_mapping": ["答案-only", "跳关键步骤", "检验缺失"],
        },
        {
            "family_id": "answer_check_habit",
            "family_name": "答案检验习惯",
            "support_only": True,
            "measures": ["process", "check", "metacognition"],
            "difficulty_range": ["L2", "L3"],
            "required_surface_features": ["要求选择合适检验方法或判断答案是否合理"],
            "forbidden_surface_features": ["繁琐格式要求", "无数学意义的抄写"],
            "scoring_basis": ["检验方法", "发现异常", "修正方向"],
            "typical_error_mapping": ["不验算", "单位错不检查", "离谱结果照写"],
        },
    ],
}


NODE_FAMILIES: dict[str, list[str]] = {
    "M-BRIDGE-SOLUTION-HABIT": ["solution_trace_repair", "answer_check_habit", "wrong_solution_repair_number", "equation_transformation_legality"],
    "M-PRE-DECIMAL-OPS": ["estimate_direction_and_magnitude", "decimal_place_value_ops", "structure_based_simplification", "wrong_solution_repair_number"],
    "M-PRE-INTEGER-OPS": ["integer_structure_arithmetic", "structure_based_simplification", "answer_check_habit", "wrong_solution_repair_number"],
    "M-PRE-NUMBER-SENSE": ["estimate_direction_and_magnitude", "number_line_position_distance", "answer_check_habit", "wrong_solution_repair_number"],
    "M-PRE-ORDER-OPS": ["operation_order_control", "wrong_solution_repair_number", "structure_based_simplification", "solution_trace_repair"],
    "M-PRE-FRACTION-MEANING": ["fraction_unit_and_equivalence", "known_unknown_relation_marking", "number_classification_boundary", "solution_trace_repair"],
    "M-PRE-FRACTION-OPS": ["fraction_operation_structure", "fraction_unit_and_equivalence", "operation_order_control", "wrong_solution_repair_number"],
    "M-PRE-PERCENT": ["percent_rate_change", "fraction_unit_and_equivalence", "estimate_direction_and_magnitude", "wrong_solution_repair_number"],
    "M-PRE-RATIO-PROP": ["ratio_proportion_structure", "proportion_table_model", "known_unknown_relation_marking", "distractor_condition_filter"],
    "M-PRE-DISTRIBUTIVE": ["distributive_structure_bridge", "structure_based_simplification", "parenthesis_and_polynomial_repair", "wrong_solution_repair_number"],
    "M-PRE-EQUATION-BASIC": ["linear_equation_solving_flow", "equation_transformation_legality", "equation_word_modeling", "solution_trace_repair"],
    "M-PRE-LETTER-EXPR": ["verbal_to_expression", "expression_value_substitution", "equivalent_expression_judgement", "solution_trace_repair"],
    "M-PRE-QUANTITY-RELATION": ["known_unknown_relation_marking", "distractor_condition_filter", "equation_word_modeling", "sum_difference_multiple_model"],
    "M-BRIDGE-WORD-PROBLEM-READING": ["known_unknown_relation_marking", "distractor_condition_filter", "equation_word_modeling", "solution_trace_repair"],
    "M-BRIDGE-MOTION-BASIC": ["motion_basic_model", "known_unknown_relation_marking", "distractor_condition_filter", "solution_trace_repair"],
    "M-BRIDGE-MOTION-CHASE": ["motion_chase_meet_model", "motion_basic_model", "known_unknown_relation_marking", "distractor_condition_filter"],
    "M-BRIDGE-PERCENT-MODEL": ["percent_application_model", "percent_rate_change", "known_unknown_relation_marking", "distractor_condition_filter"],
    "M-BRIDGE-PROPORTION-MODEL": ["proportion_table_model", "ratio_proportion_structure", "known_unknown_relation_marking", "distractor_condition_filter"],
    "M-BRIDGE-SUM-DIFF-MULTIPLE": ["sum_difference_multiple_model", "known_unknown_relation_marking", "equation_word_modeling", "distractor_condition_filter"],
    "M-BRIDGE-CLOCK-ANGLE": ["clock_angle_model", "segment_angle_part_whole", "known_unknown_relation_marking", "distractor_condition_filter"],
    "M-BRIDGE-WORK-RATE": ["work_rate_model", "known_unknown_relation_marking", "distractor_condition_filter", "solution_trace_repair"],
    "M-G7-ABSOLUTE": ["opposite_absolute_value_model", "number_line_position_distance", "equation_concept_boundary", "wrong_solution_repair_number"],
    "M-G7-COMPARE": ["number_line_position_distance", "number_classification_boundary", "opposite_absolute_value_model", "wrong_solution_repair_number"],
    "M-G7-NUMBER-LINE": ["number_line_position_distance", "opposite_absolute_value_model", "estimate_direction_and_magnitude", "solution_trace_repair"],
    "M-G7-OPPOSITE": ["opposite_absolute_value_model", "number_line_position_distance", "equivalent_expression_judgement", "wrong_solution_repair_number"],
    "M-G7-POS-NEG": ["number_classification_boundary", "number_line_position_distance", "opposite_absolute_value_model", "known_unknown_relation_marking"],
    "M-G7-RATIONAL-ADD-SUB": ["signed_operation_model", "number_line_position_distance", "wrong_solution_repair_number", "solution_trace_repair"],
    "M-G7-RATIONAL-CLASSIFY": ["number_classification_boundary", "fraction_unit_and_equivalence", "opposite_absolute_value_model", "solution_trace_repair"],
    "M-G7-RATIONAL-MIXED": ["operation_order_control", "signed_operation_model", "fraction_operation_structure", "wrong_solution_repair_number"],
    "M-G7-RATIONAL-MUL-DIV": ["signed_operation_model", "fraction_operation_structure", "wrong_solution_repair_number", "estimate_direction_and_magnitude"],
    "M-G7-POWER": ["power_base_sign", "operation_order_control", "wrong_solution_repair_number", "estimate_direction_and_magnitude"],
    "M-G7-SCI-NOTATION-APPROX": ["scientific_notation_precision", "estimate_direction_and_magnitude", "number_classification_boundary", "solution_trace_repair"],
    "M-G7-ALG-EXPR": ["verbal_to_expression", "equivalent_expression_judgement", "expression_value_substitution", "solution_trace_repair"],
    "M-G7-COMBINE-LIKE": ["like_terms_boundary", "parenthesis_and_polynomial_repair", "equivalent_expression_judgement", "solution_trace_repair"],
    "M-G7-EXPR-VALUE": ["expression_value_substitution", "verbal_to_expression", "equivalent_expression_judgement", "wrong_solution_repair_number"],
    "M-G7-LIKE-TERMS": ["like_terms_boundary", "monomial_polynomial_structure", "equivalent_expression_judgement", "solution_trace_repair"],
    "M-G7-PARENTHESIS": ["parenthesis_and_polynomial_repair", "distributive_structure_bridge", "equivalent_expression_judgement", "wrong_solution_repair_number"],
    "M-G7-POLY-ADD-SUB": ["parenthesis_and_polynomial_repair", "like_terms_boundary", "equivalent_expression_judgement", "verbal_to_expression"],
    "M-G7-MONOMIAL": ["monomial_polynomial_structure", "verbal_to_expression", "expression_value_substitution", "like_terms_boundary"],
    "M-G7-POLYNOMIAL": ["monomial_polynomial_structure", "like_terms_boundary", "equivalent_expression_judgement", "parenthesis_and_polynomial_repair"],
    "M-G7-EQ-PAREN": ["parenthesis_equation_flow", "linear_equation_solving_flow", "equation_transformation_legality", "solution_trace_repair"],
    "M-G7-EQ-SOLVE": ["linear_equation_solving_flow", "equation_transformation_legality", "solution_trace_repair", "wrong_solution_repair_number"],
    "M-G7-EQ-WORD": ["equation_word_modeling", "known_unknown_relation_marking", "distractor_condition_filter", "solution_trace_repair"],
    "M-G7-EQUALITY-PROP": ["equation_transformation_legality", "equation_concept_boundary", "solution_trace_repair", "wrong_solution_repair_number"],
    "M-G7-EQUATION-CONCEPT": ["equation_concept_boundary", "equation_transformation_legality", "equivalent_expression_judgement", "solution_trace_repair"],
    "M-G7-EQ-DENOM": ["denominator_equation_flow", "equation_transformation_legality", "linear_equation_solving_flow", "solution_trace_repair"],
    "M-G7-ANGLE": ["angle_representation_measure", "object_representation_boundary", "segment_angle_part_whole", "solution_trace_repair"],
    "M-G7-LINE-RAY-SEGMENT": ["line_ray_segment_representation", "object_representation_boundary", "segment_angle_part_whole", "solution_trace_repair"],
    "M-G7-ANGLE-CALC": ["segment_angle_part_whole", "angle_representation_measure", "clock_angle_model", "solution_trace_repair"],
    "M-G7-GEO-SOLID-PLANE": ["object_representation_boundary", "net_and_view_matching", "point_line_plane_generation", "area_volume_formula_structure"],
    "M-G7-POINT-LINE-PLANE": ["point_line_plane_generation", "object_representation_boundary", "net_and_view_matching", "solution_trace_repair"],
    "M-G7-SEGMENT-MEASURE": ["segment_angle_part_whole", "line_ray_segment_representation", "object_representation_boundary", "solution_trace_repair"],
    "M-G7-GEO-VIEWS": ["net_and_view_matching", "object_representation_boundary", "point_line_plane_generation", "solution_trace_repair"],
    "M-PRE-ANGLE-BASIC": ["angle_representation_measure", "segment_angle_part_whole", "object_representation_boundary", "solution_trace_repair"],
    "M-PRE-GEO-AREA-VOLUME": ["area_volume_formula_structure", "unit_dimension_conversion", "object_representation_boundary", "distractor_condition_filter"],
    "M-PRE-UNIT-CONVERSION": ["unit_dimension_conversion", "estimate_direction_and_magnitude", "area_volume_formula_structure", "wrong_solution_repair_number"],
}


FAMILY_CLUSTER: dict[str, str] = {}
for _cluster, _families in FAMILY_DEFINITIONS.items():
    for _family in _families:
        FAMILY_CLUSTER[_family["family_id"]] = _cluster


NODE_SPECIFIC_REJECTS: dict[str, list[str]] = {
    "M-BRIDGE-WORK-RATE": ["出成速度×时间路程题", "只把天数相加或平均", "没有工作总量=1和效率证据"],
    "M-G7-GEO-VIEWS": ["出成角平分线或角度计算", "没有展开图、视图或小正方体结构", "只用文字描述但无法产生空间证据"],
    "M-PRE-GEO-AREA-VOLUME": ["出成角度题", "只套公式不问公式结构或单位维度", "面积、体积、长度单位混用"],
    "M-G7-RATIONAL-ADD-SUB": ["只比较大小", "只在数轴上标点没有加减动作", "没有符号来源或减法转加法证据"],
    "M-PRE-INTEGER-OPS": ["把有余数除法当成主线反复刷", "把非关键书写缺失判成不会", "只给低龄机械竖式"],
    "M-G7-NUMBER-LINE": ["下一题仍重复同一个左右移动壳", "只有机械读点", "没有方向、距离或相对位置证据"],
}


GENERIC_REJECTS: dict[str, list[str]] = {
    "number_ops": ["低龄机械口算或竖式刷题", "只换数字没有新结构", "标准答案把非关键书写当主扣分"],
    "algebra": ["把代数节点出成纯整数计算或机械凑整", "只有答案没有表达结构证据", "用过难参数题冒充基础诊断"],
    "equation": ["把概念节点出成复杂求解或机械移项", "把应用题出成裸方程", "去分母或移项题没有关键变形证据"],
    "application_modeling": ["没有真实数量关系的伪应用题", "所有数字都必须用的机械题", "只算结果不暴露建模关系"],
    "geometry": ["几何节点出成纯数值机械计算", "空间题没有图形/结构证据", "单位换算和公式计算混成无重点题"],
    "learning_process": ["繁琐格式要求压过数学理解", "把书写不完整直接判定为不会", "只要求机械抄标准步骤"],
}


SEED_OVERRIDES: dict[str, list[str]] = {
    "M-PRE-DECIMAL-OPS": ["49.8×20.4 与 1000 比较", "2.5×3.2×1.25", "4.8÷0.6 与 48÷6", "12.5×0.32 的小数点位置"],
    "M-PRE-INTEGER-OPS": ["125×32×25", "999×37 的结构检查", "48×75+52×75", "连续三个整数用中间数表示"],
    "M-G7-RATIONAL-ADD-SUB": ["-7+3 的符号来源", "4-(-6) 为什么变成 4+6", "-2.5+1.8-3.5 的分组", "错解：-5-2=3"],
    "M-BRIDGE-WORK-RATE": ["甲6天完成、乙9天完成，合作效率是多少", "先甲做2天再乙接做的剩余量", "错解：合作天数=(6+9)÷2", "同一工程总量设为1的方程表达"],
    "M-G7-GEO-VIEWS": ["正方体展开图相对面判断", "根据三视图判断小正方体个数范围", "给出小方块堆叠图，判断左视图", "错误展开图为什么折不成正方体"],
    "M-PRE-GEO-AREA-VOLUME": ["长方体体积公式为什么是底面积×高", "圆柱体积和长方体体积结构比较", "组合图形先拆再求面积", "面积单位和体积单位的维度检查"],
}


CLUSTER_BY_MODULE = {
    "A_FOUNDATION": "number_ops",
    "B_FRACTION_RATIO": "number_ops",
    "C_ALGEBRA_BRIDGE": "algebra",
    "D_WORD_MODELS": "application_modeling",
    "E_RATIONAL_NUMBERS": "number_ops",
    "F_EXPRESSIONS": "algebra",
    "G_LINEAR_EQUATION": "equation",
    "H_GEOMETRY_INTRO": "geometry",
    "Z_LEARNING_PROCESS": "learning_process",
}


def _family(fid: str) -> dict[str, Any]:
    cluster = FAMILY_CLUSTER[fid]
    for item in FAMILY_DEFINITIONS[cluster]:
        if item["family_id"] == fid:
            return item
    raise KeyError(fid)


def _build_taxonomy() -> dict[str, Any]:
    clusters = []
    for cluster_id, families in FAMILY_DEFINITIONS.items():
        normalized_families = []
        for family in families:
            item = dict(family)
            item["cluster_id"] = cluster_id
            item.setdefault("support_only", False)
            normalized_families.append(item)
        clusters.append(
            {
                "cluster_id": cluster_id,
                "name": {
                    "number_ops": "数与运算",
                    "algebra": "代数式与整式",
                    "equation": "方程",
                    "application_modeling": "应用建模",
                    "geometry": "几何图形初步",
                    "learning_process": "学习流程与表达",
                }[cluster_id],
                "families": normalized_families,
            }
        )
    return {
        "schema_version": TAXONOMY_SCHEMA_VERSION,
        "status": "v18_blueprint_ready",
        "purpose": "Define reusable question families for v18 question-bank production. Families describe mathematical task structure, not surface format.",
        "clusters": clusters,
    }


def _budget(priority: str, concept_type: str) -> dict[str, int]:
    if priority == "P0":
        if concept_type == "concept":
            return {"min": 10, "target": 14, "max": 18}
        if concept_type == "process":
            return {"min": 8, "target": 12, "max": 16}
        return {"min": 14, "target": 18, "max": 22}
    if priority == "P1":
        return {"min": 8, "target": 12, "max": 16}
    return {"min": 5, "target": 8, "max": 10}


def _difficulty(priority: str, concept_type: str, index: int) -> list[str]:
    if priority == "P2":
        return ["L3", "L4"] if index < 2 else ["L4", "L5"]
    if concept_type in {"concept", "process"} and index == 0:
        return ["L2", "L3"]
    return ["L3", "L4"] if index < 3 else ["L4"]


def _family_plan(node_id: str, node_name: str, node_cluster: str, priority: str, concept_type: str) -> list[dict[str, Any]]:
    families = NODE_FAMILIES[node_id]
    budget = _budget(priority, concept_type)
    target = budget["target"]
    base = max(2, target // len(families))
    counts = [base for _ in families]
    remainder = target - sum(counts)
    i = 0
    while remainder > 0:
        counts[i % len(counts)] += 1
        remainder -= 1
        i += 1
    while remainder < 0:
        j = len(counts) - 1
        while remainder < 0 and j >= 0:
            if counts[j] > 1:
                counts[j] -= 1
                remainder += 1
            j -= 1
    plan = []
    for i, fid in enumerate(families):
        item = {
            "family_id": fid,
            "target_count": counts[i],
            "difficulty": _difficulty(priority, concept_type, i),
            "evidence_focus": _family(fid)["measures"],
            "required_evidence": _required_evidence_for_family(node_name, fid),
        }
        family_cluster = FAMILY_CLUSTER[fid]
        if family_cluster != node_cluster:
            item["adaptation_note"] = _adaptation_note(node_name, fid, family_cluster, node_cluster)
        plan.append(item)
    return plan


def _adaptation_note(node_name: str, family_id: str, family_cluster: str, node_cluster: str) -> str:
    if family_id in {"solution_trace_repair", "answer_check_habit"}:
        return f"support-only：用于补足{node_name}的过程证据，不计入真实数学题型家族数量。"
    return f"跨簇借用：{family_cluster}家族服务{node_cluster}节点的具体数学任务，生成题必须显式绑定{node_name}的scope_in。"


def _required_evidence_for_family(node_name: str, family_id: str) -> list[str]:
    defaults = {
        "concept": f"能说清{node_name}的概念边界或反例",
        "model_relation": f"能写出{node_name}对应的核心关系",
        "procedure": "关键步骤可复盘，不要求照抄固定格式",
        "calculation": "结果正确且能用估算、代回或结构关系检查",
        "representation": "能在文字、式子、图形或数轴之间转换",
        "expression_notation": "代数表达意图清楚，非关键书写不作主扣分",
        "geometry_relation": "能把图形语言翻译成整体-部分或相等关系",
        "visual_spatial": "能说明空间对应、视角或展开折叠关系",
        "unit": "单位维度和换算方向正确",
        "check": "能主动检验答案是否符合题意",
        "reading": "能区分必要条件和干扰条件",
        "process": "能补齐影响判断的关键证据",
        "metacognition": "能说明自己用什么方式检查答案",
        "expression": "表达足以让老师判断思路，不因轻微写法扣大分",
    }
    return [defaults.get(measure, f"能提供{measure}证据") for measure in _family(family_id)["measures"]]


def _node_capability(node: dict[str, Any]) -> str:
    qtypes = "、".join(node.get("question_types") or [])
    essence = str(node.get("essence_for_child") or "").rstrip("。")
    return f"{node['name']}：{essence}；命题必须围绕{qtypes}产生可观察证据。"


def _scope_in(node: dict[str, Any]) -> list[str]:
    items = []
    items.extend(node.get("question_types") or [])
    criteria = [str(x).replace("正确率≥85%", "稳定正确").replace("≥90%", "稳定") for x in node.get("mastery_criteria") or []]
    items.extend(criteria[:2])
    items.extend(node.get("diagnostic_probes") or [])
    return list(dict.fromkeys(x for x in items if x))[:8]


def _scope_out(node: dict[str, Any], cluster: str) -> list[str]:
    node_id = node["id"]
    out = list(GENERIC_REJECTS[cluster])
    out.extend(NODE_SPECIFIC_REJECTS.get(node_id, []))
    if cluster != "geometry":
        out.append("把本节点出成角平分线、视图或面积体积题")
    if cluster != "application_modeling" and node_id != "M-G7-EQ-WORD":
        out.append("把本节点出成无关应用题情境")
    if node_id != "M-BRIDGE-WORK-RATE":
        out.append("把本节点出成工程效率题")
    return list(dict.fromkeys(out))[:9]


def _seeds(node: dict[str, Any]) -> list[str]:
    node_id = node["id"]
    if node_id in SEED_OVERRIDES:
        return SEED_OVERRIDES[node_id]
    qtypes = node.get("question_types") or ["核心结构"]
    mistakes = node.get("common_mistakes") or ["缺少关键证据"]
    name = node["name"]
    seeds = [
        f"{name}：{qtypes[0]}的标准诊断题，要求说明关键关系",
        f"{name}：围绕“{mistakes[0]}”设计错解修复题",
        f"{name}：把{qtypes[min(1, len(qtypes)-1)]}换成近似结构复测",
        f"{name}：L4迁移题，混入一个干扰条件但不增加低效计算量",
    ]
    return seeds


def _build_blueprints(graph: dict[str, Any]) -> dict[str, Any]:
    blueprints = []
    for node in graph["nodes"]:
        node_id = node["id"]
        module = (node.get("taxonomy") or {}).get("module_id")
        concept_type = (node.get("taxonomy") or {}).get("concept_type") or "mixed"
        priority = node.get("priority") or "P1"
        cluster = CLUSTER_BY_MODULE[module]
        if node_id in {"M-PRE-QUANTITY-RELATION"}:
            cluster = "application_modeling"
        if node_id in {"M-PRE-EQUATION-BASIC"}:
            cluster = "equation"
        if node_id == "M-PRE-UNIT-CONVERSION":
            cluster = "geometry"
        budget = _budget(priority, concept_type)
        blueprints.append(
            {
                "node_id": node_id,
                "node_name": node["name"],
                "cluster": cluster,
                "priority": priority,
                "stage": node.get("stage"),
                "module_id": module,
                "node_capability": _node_capability(node),
                "scope_in": _scope_in(node),
                "scope_out": _scope_out(node, cluster),
                "candidate_budget": budget,
                "family_plan": _family_plan(node_id, node["name"], cluster, priority, concept_type),
                "typical_error_tags": list((node.get("error_diagnosis") or {}).get("likely_error_tags") or [])[:4],
                "rollback_nodes": list(dict.fromkeys((node.get("prerequisites") or []) + ((node.get("error_diagnosis") or {}).get("rollback_to") or [])))[:5],
                "review_must_reject": _scope_out(node, cluster),
                "sample_seed_ideas": _seeds(node),
                "generation_policy": {
                    "must_bind_primary_node": node_id,
                    "must_include_solution_contract": True,
                    "must_include_mastery_dimension_mapping": True,
                    "non_key_expression_gap_max_penalty": 1,
                    "avoid_rotemechanical_drill": True,
                    "simple_node_fast_pass": concept_type in {"concept", "process"},
                },
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blueprint_ready_for_60_item_sample",
        "source_graph": str(GRAPH_PATH.relative_to(ROOT)),
        "purpose": "Full node-level v18 production blueprints. These are the required gate before generating any v18 sample or full question bank.",
        "blueprints": blueprints,
    }


def main() -> None:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    TAXONOMY_PATH.write_text(json.dumps(_build_taxonomy(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BLUEPRINT_PATH.write_text(json.dumps(_build_blueprints(graph), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {TAXONOMY_PATH}")
    print(f"WROTE {BLUEPRINT_PATH}")


if __name__ == "__main__":
    main()
