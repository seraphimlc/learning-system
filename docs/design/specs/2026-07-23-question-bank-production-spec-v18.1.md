# QUESTION_BANK_PRODUCTION_SPEC v18.1

状态：`PRODUCT_SPEC_READY_FOR_TECHNICAL_DESIGN`

日期：2026-07-23

负责人：若命

适用范围：数学题库生产、审题、专家评审、QA、入库和激活前门禁。

## 结论

题库生产不能以“生成 1000 道题”为目标。1000 只是候选池规模，不是产品成功标准。

v18.1 的目标是建立一个可持续、可审查、可追责的教研生产系统：

```text
图谱节点
-> 节点蓝图
-> 题型家族
-> 单题生成
-> 题目级答案与评分合同
-> 机器校验
-> AI 审题
-> 多专家评审
-> 小样本真实验证
-> staged
-> active
```

任何题目不能因为 JSON 字段齐全就进入孩子端。`active` 只能由审查证据推导，不能由题目自报。

## 用户和价值

### 孩子

孩子只需要看到适合当前水平的少量题，并获得明确反馈。孩子不应该感知候选池、题库版本、agent、图谱 ID 或审查流程。

### 家长 / Codex

家长通过 Codex 查看题库质量、学习证据、系统问题和下一步计划。家长需要知道题为什么被选、错因是否可靠、下一步是否合理。

### 系统

系统需要一个稳定题库候选池，让 runtime 可以小批量、自适应选题：

- 会了就跳过或拔高；
- 不稳就近似结构复测；
- 不会就回退前置和讲解；
- 简单节点不刷题；
- 复杂节点不靠一题断言完全掌握。

## 非目标

- 不复制商业教材、教辅、题库。
- 不把公开资料题目改数字后入库。
- 不把奥数题作为主线题库。
- 不追求每个节点固定 20 道。
- 不把选择题、填空题、简答题当成题型体系本身。
- 不允许通用模板覆盖所有节点。
- 不允许模型直接拿“全题库上下文”来选题或生成题。
- 不允许样本题库直接激活给孩子端。

## 事实源

### 知识图谱

事实源：

- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`

题目必须绑定图谱节点。题目错因、回退、掌握维度也必须能落到图谱节点或前置节点。

### 节点蓝图

事实源：

- `data/question_banks/v18/node_question_blueprints_v18.json`

没有节点蓝图，不允许生成题。

每个蓝图必须包含：

- `node_id`
- `node_name`
- `cluster`
- `priority`
- `node_capability`
- `scope_in`
- `scope_out`
- `candidate_budget`
- `family_plan`
- `typical_error_tags`
- `rollback_nodes`
- `review_must_reject`
- `sample_seed_ideas`
- `generation_policy`

### 题型家族

事实源：

- `data/question_banks/v18/question_type_taxonomy_v18.json`

题型家族描述数学任务结构，不描述表面作答形式。

正确例子：

- 估算方向与数量级
- 小数位值与等价转化
- 有理数符号运算模型
- 同类项边界辨析
- 含分母方程求解
- 工程效率模型
- 展开图与三视图匹配
- 单位维度换算

错误例子：

- 选择题
- 填空题
- 解答题
- 简单题
- 难题

## 生产模式

### 批量生产

用途：补齐候选池。

输入：

- 单个节点蓝图
- 单个题型家族
- 目标难度
- 已有结构指纹摘要
- 本轮生成数量，建议 3-5 道

输出：

- draft 题目
- 标准答案
- 题目级评分合同
- 结构指纹
- 审查自检结果

限制：

- 不能一次生成全节点或全题库。
- 不能把所有题库内容喂给模型。
- 不能让模型自由选择节点边界。

### 课后定向生产

用途：孩子真实学习后暴露某个弱点，补 1-3 道精准复测题。

输入：

- 最近 attempts
- 题目级评分结果
- answer_analysis
- mastery_update
- weak dimension
- 当前节点蓝图
- 前置链候选节点

输出三选一：

- same-structure confirmation
- near-transfer retest
- prerequisite probe

限制：

- 不因为一题错就无限刷同类题。
- 七上题错了，优先沿前置链探查。
- 不允许拔高题反向否定基础掌握。

### 拔高生产

用途：孩子对节点稳定掌握后，进行受控迁移。

输入：

- 已掌握节点
- 可组合节点
- L4/L5 family
- 本次学习目标

输出：

- 迁移题
- 边界题
- 小竞赛味题

限制：

- P2/拔高节点不能进入默认主线。
- L5 只在孩子已经稳定掌握后出现。
- 拔高失败只说明迁移不稳，不推翻基础掌握。

## 单题合同

每道题必须包含以下产品字段：

- `id`
- `item_version`
- `node_id`
- `question_family_id`
- `difficulty`
- `prompt`
- `answer_format`
- `standard_answer`
- `accepted_alternatives`
- `required_evidence`
- `key_score_points`
- `non_scoring_expression_requirements`
- `typical_errors`
- `mastery_dimension_mapping`
- `rollback_candidates`
- `structure_fingerprint`
- `review_status`
- `activation_eligible`

### 标准答案

标准答案必须直接回答题目，不能包含后台话术。

禁止：

- “本题重点是……”
- “命题 Agent 认为……”
- “图谱节点……”
- “Missing the requested……”
- “Add one sentence……”

### 评分合同

评分合同必须是题目级，不允许 60 题共用同一套泛模板。

默认 10 分制可作为起点：

- 4 分：最终结论
- 3 分：核心关系 / 模型 / 符号来源 / 图形结构
- 2 分：关键过程
- 1 分：检查 / 单位 / 表达

但分值必须允许按题型调整。

评分原则：

- 结果正确、核心意图正确，轻微表达差异不能大扣分。
- 非关键书写要求最多作为改进建议。
- 答案碰巧正确但模型关系错误，不能判完全掌握。
- 模型正确但计算错，应回退计算或符号，不回退概念。
- 空白、我不会、乱写，应进入讲解/回退，不走重模型长链。

## 难度定义

难度不由数字大小决定，而由认知动作决定。

### L2

入口识别。用于判断孩子是否知道基本概念或规则。

不能单独证明完全掌握。

### L3

标准掌握。要求有结果和核心过程证据。

这是主诊断难度。

### L4

近迁移。加入结构变化、干扰条件、反例边界或一题两解。

用于判断是否稳。

### L5

受控拔高。只用于已掌握后的挑战或专家样本。

不能进入默认主线诊断。

## 评审流程

### 机器校验

机器校验负责 fail-closed。

必须检查：

- graph node 覆盖和引用合法；
- family 全局唯一且引用合法；
- family 与 node cluster 一致，跨簇必须有说明；
- P2 预算不进入默认主线；
- prompt、id、structure fingerprint 去重；
- 每题有题目级 `required_evidence` 和 `key_score_points`；
- scoring targets 不是全题库同一模板；
- 题目没有后台话术；
- draft/sample 不能 active；
- manifest digest 一致。

已存在门：

- `scripts/validate_question_bank_v18_blueprints.py`
- `scripts/validate_question_bank_v18_sample.py`
- `scripts/question_bank_v18_activation_gate.py`

### AI 审题 Agent

审题 Agent 只审题，不追求题量。

输入：

- 单题
- 节点蓝图
- 题型家族定义
- scope_in/scope_out
- 历史负例

输出：

- `review_status`
- P0/P1/P2 问题
- 是否节点错配
- 是否低龄机械
- 是否泛模板
- 是否答案和题面不匹配
- 是否评分证据不足

任何 P0，单题废弃。

### 专家评审

至少包含五类视角：

- 课程标准专家：范围和年龄适配。
- 一线数学教师：孩子是否看得懂，题面是否自然。
- 认知诊断专家：能否暴露断点。
- 评分合同专家：评分是否灵活准确。
- 拔高教练：L4/L5 是否真有迁移价值。

专家评审可以抽样，但抽样必须覆盖：

- 每个簇；
- P0/P1/P2；
- 每类题型家族；
- 历史高风险节点。

历史高风险节点至少包括：

- `M-BRIDGE-WORK-RATE`
- `M-G7-GEO-VIEWS`
- `M-PRE-GEO-AREA-VOLUME`
- `M-G7-RATIONAL-ADD-SUB`

### 观止 QA

观止必须做 false-pass audit。

不能只看：

- 测试退出码；
- JSON 字段齐全；
- 题目数量达标；
- prompt 不重复。

必须检查：

- 工程题是否跑成行程题；
- 视图题是否跑成角度题；
- 面积体积是否跑成角平分线；
- 有理数加减是否退化成比较大小；
- 评分合同是否泛模板；
- 题目是否真的能支撑下一步规划；
- 浏览器中孩子是否能自然作答。

## 入库状态机

题目状态：

```text
draft_generated
-> self_checked
-> ai_reviewed
-> expert_reviewed
-> qa_passed
-> staged
-> active
-> retired/rejected
```

规则：

- `draft_generated` 不能被 runtime 选择。
- `sample_static_qa_passed_scope_limited` 只能证明样本完整，不允许激活。
- `active` 只能由 gate receipt、expert review receipt、QA receipt、answer contract 和 ledger 状态共同推导。
- 题目 JSON 里的 `activation_eligible` 不能单独作为激活依据。
- 任一输入文件 digest 变化，旧 manifest 立即失效。

## 分阶段推进

### Phase A：蓝图门

目标：

- 56 节点蓝图完整。
- 题型家族完整。
- 每个 family_plan 有节点内 required_evidence。

验收：

```bash
python3 scripts/validate_question_bank_v18_blueprints.py
```

### Phase B：60 题样本门

目标：

- 10 个代表节点。
- 每节点 6 道。
- 覆盖数运算、代数、方程、应用建模、几何。
- 每题有题目级答案和评分合同。

验收：

```bash
python3 scripts/generate_question_bank_v18_sample.py
python3 scripts/validate_question_bank_v18_sample.py data/question_banks/v18/math_v18_sample_60.json data/question_banks/v18/node_question_blueprints_v18.json
python3 scripts/question_bank_v18_activation_gate.py --mode sample-integrity
```

必须确认：

```bash
python3 scripts/question_bank_v18_activation_gate.py --mode activation-readiness
```

当前样本阶段必须 fail-closed。

### Phase C：真实批阅验证

目标：

- 用真实 GPT 模型批阅样本作答。
- 覆盖正确、错误、半对、答案-only、表达不完整、我不会、照片不清。
- 验证评分是否符合题目级合同。

通过条件：

- 评分不因非关键书写大扣分；
- 正确答案但错误理由不能判完全掌握；
- “我不会”不走长链；
- 输出没有英文混入孩子反馈；
- 规划能基于评分选择讲解、回退、变式或拔高。

### Phase D：浏览器学习流程验证

目标：

- 孩子端真实操作。
- 小批量题组或逐题交互都能闭环。
- pending、失败、重试、刷新、重复提交都有明确状态。

通过条件：

- 不泄漏内部 ID、agent、provider、rubric。
- 等待态诚实，不掩盖失败。
- 一组题完成后能看到合理总结和下一步。
- 图谱/目录选择不会绕过题库状态门。

### Phase E：全量候选池生成

前置：

- Phase A-D 全部通过。
- sample manifest 的 taxonomy/blueprint/generator/reviewer digest 没变化。
- 如果任一 digest 变化，回到 Phase B。

目标规模：

- P0：每节点 12-18 道。
- P1：每节点 8-12 道。
- P2：每节点 5-8 道。

注意：

- 这是候选池，不是孩子实际题量。
- 简单节点可以候选少，靠后续综合题复现。
- 复杂节点需要变式覆盖，但不允许题海。

## 失败处理

### 单题失败

单题废弃或回到 draft，不影响整库。

触发：

- 节点错配；
- 标准答案错误；
- 评分合同缺失；
- 题面低龄机械；
- 题目无法支撑掌握证据。

### 节点失败

整节点重做。

触发：

- 同一节点 2 个 P1；
- 任意 P0；
- family 分布明显偏；
- 题目同质化严重。

### 样本失败

回到蓝图或题型家族。

触发：

- 多节点出现同类错配；
- scoring targets 泛模板；
- 专家认为样本无法代表生产策略；
- 观止发现机器校验假通过。

### 全量失败

不得 staging。

触发：

- digest 不一致；
- manifest 缺 receipt；
- candidate packet 字段丢失；
- answer contract 不完整；
- 浏览器或模型验证失败。

## 验收标准

v18.1 题库生产系统达到可进入全量生成，必须同时满足：

- 蓝图覆盖 56 节点。
- taxonomy family 全局唯一。
- 每题绑定一个主节点和一个题型家族。
- 每题有题目级 `required_evidence`、`key_score_points`、`scoring_targets`。
- 每题有结构指纹且不重复。
- 机器校验 PASS。
- AI 审题无 P0。
- 专家抽审无 P0。
- 观止 QA 至少 `PASS_WITH_SCOPE`，且 scope 不包含“不能证明语义质量”的关键缺口。
- 样本 manifest digest 一致。
- activation gate 对样本 fail-closed。
- 全量题库入 staged 前，有完整 receipt。

## 当前状态

已完成：

- 56 节点 v18 蓝图。
- 48 个题型家族。
- 60 题样本。
- 样本题目级证据和评分合同。
- 样本 integrity gate。
- 样本 activation-readiness fail-closed gate。

未完成：

- 真实模型批阅验证。
- 浏览器真实学习流程验证。
- v18 全量导入/激活脚本。
- candidate packet 映射测试。
- 全量候选池生成。

## 下一步

听云应基于本规格设计 v18 导入/激活技术方案，重点实现：

- full-bank manifest schema；
- receipt 存储；
- active 状态 fail-closed；
- candidate packet 映射测试；
- live model grading regression；
- browser child-flow regression。

在这些完成前，v18 样本只能作为审查材料，不能进入孩子端。
