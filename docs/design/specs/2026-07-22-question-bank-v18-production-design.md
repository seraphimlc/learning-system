# v18 题库生产设计包

状态：`PRODUCT_SPEC_DRAFT_READY_FOR_REVIEW`

日期：2026-07-22

负责人视角：若命 / 产品与教研结构；后续由命题 Agent、审题 Agent、观止 QA、镜花架构审查共同执行。

## 结论

v18 不以“凑够 1000 题”为目标。1000 只是候选池规模上限，真实目标是：

1. 每道题能绑定一个明确图谱节点。
2. 每道题能说明它在测什么证据。
3. 每道题的数学任务和节点能力一致。
4. 每个节点先有题型家族，再有题目。
5. 简单节点少而准，复杂节点有足够变式。
6. 审题 Agent 能用明确规则拦截错配、低龄、换皮、答案-only、伪过程题。

v18 题库生产顺序必须是：

`知识图谱节点 -> 节点能力边界 -> 题型家族 -> 难度梯度 -> 评分合同 -> 题目生成 -> 审题 -> 抽样教研审查 -> 入库`

不能再走：

`目标数量 -> 通用模板 -> 题面换皮 -> 去重通过 -> 入库`

## 非目标

- 不追求每个节点固定 20 道。
- 不让孩子刷 1000 道。
- 不把奥数拔高题作为主线。
- 不使用统一模板覆盖所有节点。
- 不用“写出条件/比较两种方法”这类外壳伪装成题型多样性。
- 不把后台分析话术写进孩子题面或标准答案主体。

## 题库分层

### 候选池

候选池可以有 800-1000 道，但只是 runtime 选题来源。

候选池规模建议：

- P0 核心节点：每节点 16-22 道。
- P1 选择性核心：每节点 10-16 道。
- P2 受控拓展：每节点 6-10 道。

### 每次学习实际出题

每天或每轮不按候选池数量推进。Runtime 只选小批量：

- 初次诊断：3-5 道。
- 不稳定复测：2-4 道。
- 讲解后确认：1-3 道。
- 拔高迁移：1-2 道。

简单节点如果 2-3 道足以证明掌握，应进入迁移或跳过，不继续重复。

## 节点簇

v18 命题 Agent 必须先判断节点属于哪个命题簇。不同簇使用不同题型家族和审题规则。

### A. 数与运算簇

节点例子：

- 数感与估算
- 整数四则计算
- 小数运算
- 分数意义与单位1
- 分数运算
- 百分数
- 有理数加减乘除与混合运算

核心目标：

- 结果范围判断
- 运算结构选择
- 符号和小数点控制
- 运算顺序
- 计算后检验

禁止：

- 低龄机械竖式题
- 只换数字的口算题
- 明知孩子会还反复要求解释低龄规则

适合题型家族：

- 估算方向题
- 错解定位题
- 凑整结构题
- 符号/小数点/数量级审查题
- 逆向检查题
- 混合运算陷阱题
- 迁移到代数或方程的前置题

### B. 代数簇

节点例子：

- 用字母表示数
- 代数式
- 代数式求值
- 同类项
- 去括号
- 合并同类项
- 整式加减
- 单项式、多项式

核心目标：

- 把文字关系转成代数表达
- 符号规则稳定
- 字母部分与系数分离
- 去括号与合并同类项
- 化简和求值的顺序选择

禁止：

- 把代数节点出成纯整数计算
- 只要求算结果，不要求表达结构
- 用过难参数题替代基础概念诊断

适合题型家族：

- 表达式翻译题
- 同类项辨析题
- 错解修复题
- 先化简再求值题
- 等价表达判断题
- 反例边界题
- 代数式实际意义题

### C. 方程簇

节点例子：

- 小学简易方程
- 等式性质
- 方程与一元一次方程概念
- 解一元一次方程基础
- 含括号方程
- 含分母方程
- 一元一次方程应用题

核心目标：

- 方程概念和解的意义
- 等式性质
- 解方程步骤稳定
- 去括号/去分母边界
- 设未知数和等量关系
- 解后检验

禁止：

- 把“判断方程”节点出成普通解方程题
- 把应用题节点出成裸方程计算
- 去分母题缺少每一项同乘的证据

适合题型家族：

- 概念判断题
- 等式变形合法性题
- 解方程标准流程题
- 错解修复题
- 代回检验题
- 设未知数建模题
- 去括号/去分母条件题

### D. 应用建模簇

节点例子：

- 等量关系与列式
- 应用题审题流程
- 行程基础
- 追及相遇
- 工程问题
- 百分数应用
- 比例应用
- 和差倍模型

核心目标：

- 读题找对象
- 找已知/未知
- 找关系而不是看到数字就算
- 区分速度和速度差、工作总量和效率、单位1和比较量
- 让方程或算式服务模型

禁止：

- 工程题出成速度×时间
- 追及相遇出成普通路程题
- 百分数应用只做百分数互化
- 没有真实情境的“伪应用题”

适合题型家族：

- 已知未知标注题
- 关系式选择题
- 模型分类题
- 干扰条件剔除题
- 错误列式修复题
- 一题两解比较题
- 情境变式题

### E. 几何簇

节点例子：

- 直线、射线、线段
- 角的概念与表示
- 角度计算
- 点线面体
- 线段比较与计算
- 立体图形与平面图形
- 展开图与视图
- 面积体积公式理解
- 单位换算

核心目标：

- 几何对象识别
- 图形关系翻译为数量关系
- 空间想象
- 角/线段整体与部分
- 展开图、视图、面积体积公式的结构理解

禁止：

- 展开图与视图出成角平分线题
- 面积体积节点出成角度题
- 只有文字没有图形结构的视图题
- 单位换算和几何公式混成一个无重点计算题

适合题型家族：

- 图形对象辨析题
- 表示法判断题
- 关系图转算式题
- 线段/角整体部分题
- 展开图可行性判断题
- 三视图匹配题
- 面积体积公式来源题
- 单位维度审查题

### F. 学习流程与表达簇

节点例子：

- 解题步骤与检验习惯

核心目标：

- 过程可复盘
- 主动检验
- 单位和答句
- 错因表达
- 正确答案但过程缺失时如何补证据

禁止：

- 把所有节点都变成“写步骤习惯”题
- 用流程题代替数学概念诊断

适合题型家族：

- 错解复盘题
- 缺步骤补全题
- 单位/答句审查题
- 代回检验题
- 错因分类题

## 题型家族定义

每个题型家族必须有这些字段：

```json
{
  "family_id": "string",
  "family_name": "string",
  "cluster": "number_ops|algebra|equation|application_modeling|geometry|learning_process",
  "measures": ["concept", "model", "procedure", "calculation", "expression", "transfer"],
  "best_for": ["initial_diagnostic", "repair", "retest", "new_knowledge", "stretch"],
  "not_for": ["string"],
  "difficulty_range": ["L2", "L3", "L4"],
  "required_surface_features": ["string"],
  "forbidden_surface_features": ["string"],
  "scoring_basis": ["string"],
  "typical_error_mapping": ["string"]
}
```

## 难度定义

### L2 基础确认

用途：确认孩子能进入当前节点。

特点：

- 单关系
- 无复杂干扰
- 结果可直接验证
- 不用于证明完全掌握

### L3 主诊断

用途：判断孩子是否理解节点核心模型。

特点：

- 有明确过程证据
- 包含一个常见误区或边界
- 能区分会做、会算但不理解、答案碰巧对

### L4 迁移确认

用途：判断掌握是否稳定。

特点：

- 条件变化
- 表示变化
- 有干扰条件
- 要解释为什么仍然用同一模型或为什么不能用原模型

### L5 受控拔高

用途：只在基础稳定后拓展。

特点：

- 综合多个节点
- 有一定竞赛味道
- 不反向否定基础掌握
- 不进入主线诊断默认池

## 单题必填合同

每道题必须带这些字段。

### 基础字段

- `question_id`
- `node_id`
- `cluster`
- `family_id`
- `difficulty`
- `question_type`
- `prompt`
- `answer_format`
- `expected_answer`
- `solution_steps`

### 教研字段

- `scope_in`
- `scope_out`
- `measured_capabilities`
- `required_evidence`
- `typical_errors`
- `rollback_candidates`
- `transfer_target`

### 评分字段

- `standard_answer`
- `acceptable_methods`
- `key_score_points`
- `non_scoring_expression_notes`
- `partial_credit_policy`
- `mastery_dimension_mapping`

### 去重字段

- `problem_family_id`
- `core_stem_id`
- `structure_fingerprint`
- `surface_fingerprint`
- `semantic_duplicate_group`

## 节点蓝图必填项

每个图谱节点在生成题目前必须先有蓝图。

```json
{
  "node_id": "M-G7-RATIONAL-ADD-SUB",
  "cluster": "number_ops",
  "node_capability": "有理数加减：加减本质是在数轴上移动；减法转化为加相反数。",
  "scope_in": [
    "同号相加",
    "异号相加",
    "减法转加法",
    "多项加减",
    "符号和绝对值分离"
  ],
  "scope_out": [
    "只比较大小",
    "只读数轴位置",
    "有理数乘除",
    "复杂混合运算"
  ],
  "family_plan": [
    {
      "family_id": "signed_add_same_sign",
      "target_count": 2,
      "difficulty": ["L2", "L3"],
      "evidence": ["符号判断", "绝对值相加", "结果解释"]
    },
    {
      "family_id": "signed_add_different_sign",
      "target_count": 3,
      "difficulty": ["L3"],
      "evidence": ["绝对值比较", "符号归属", "差值计算"]
    },
    {
      "family_id": "subtraction_to_opposite",
      "target_count": 3,
      "difficulty": ["L3", "L4"],
      "evidence": ["减法转加法", "相反数", "符号控制"]
    }
  ],
  "review_must_reject": [
    "题目只是在比较两个有理数大小",
    "题目只要求在数轴上找位置",
    "题目没有加减运算动作"
  ]
}
```

## 命题 Agent 输入

命题 Agent 每次只能拿到一个 bounded packet：

```json
{
  "node_blueprint": {},
  "family_blueprint": {},
  "difficulty": "L3",
  "evidence_goal": "model_relation",
  "recent_structure_fingerprints": [],
  "forbidden_patterns": [],
  "learner_profile_note": "incoming grade 7; avoid low-age drills"
}
```

命题 Agent 不能拿全题库自由联想。

## 命题 Agent 输出

```json
{
  "question": {},
  "self_check": {
    "node_match": "pass|fail",
    "family_match": "pass|fail",
    "difficulty_match": "pass|fail",
    "not_mechanical": "pass|fail",
    "child_surface_clean": "pass|fail",
    "scoring_ready": "pass|fail",
    "duplicate_risk": "low|medium|high"
  }
}
```

任何 `fail` 都不能进入审题，只能重写。

## 审题 Agent 必须拦截

### P0 拦截

- 节点错配。
- 题型标签和题面动作不一致。
- 标准答案不对应题目。
- 题面有后台话术。
- 题目无法支撑评分。
- 应用题没有真实数量关系。
- 几何视图题没有图形结构。

### P1 拦截

- 同一例子换多个外壳。
- 同一题型家族过度重复。
- 题面过长但数学任务很薄。
- 难度与节点阶段不匹配。
- 非关键书写要求被设计成主要得分点。

## 专家抽样规则

每次生成一个候选版本后，必须抽样：

- 10 个节点。
- 每节点 5 道。
- 覆盖至少 5 个簇。
- 覆盖 L2/L3/L4/L5。
- 覆盖基础、错解、迁移、应用、几何。

判定：

- 任意 P0：整版不通过。
- 同一节点出现 2 个 P1：该节点重做。
- 10 个节点中 3 个节点重做：整版生成策略重做。

## v18 生产阶段

### Phase 1：蓝图

产物：

- `question_type_taxonomy_v18.json`
- `node_question_blueprints_v18.json`
- `difficulty_rubric_v18.md`

验收：

- 56 个节点都有蓝图。
- 每个节点都有 scope_in/scope_out。
- 每个节点至少 4 个真实题型家族。
- P0/P1/P2 节点有不同候选数量预算。

### Phase 2：小样本生成

产物：

- 每簇 2 个节点。
- 每节点 6 道。
- 总计约 60 道。

验收：

- 专家审查通过。
- 观止 QA 不发现节点错配。
- 镜花确认字段能支撑 runtime 和评分。

### Phase 3：全量生成

产物：

- v18 候选题库。
- 目标 800-1000 道。

验收：

- 所有题通过审题 Agent。
- 去重门通过。
- 评分合同可生成。
- 专家抽样通过。
- 不激活为正式题库，直到浏览器真实流程抽样通过。

### Phase 4：激活

前提：

- DB 临时库 rebuild 通过。
- candidate packet 能按节点选出正确题型。
- 页面真实完成一轮题，不出现旧题或错配题。

## v18 与 v17 的关系

v17 保留工程结构，不保留题目内容。

可复用：

- asset schema
- SQLite 入库链路
- answer contract 激活链路
- candidate packet 机制
- 去重字段

不可复用：

- 当前 v17 题面
- 当前通用模板生成策略
- 当前节点到 category 的粗暴映射
