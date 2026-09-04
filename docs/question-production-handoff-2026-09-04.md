# 数学题生产系统交接文档

更新时间：2026-09-04

本文用于下一个会话继续开发和生产。数据库中的失败 Run 是审计证据，不等于可用题目。

## 1. 项目定位

这是给单个孩子定制的 AI 原生学习系统。当前优先建设数学题库，用于小学关键漏洞补齐和人教版七年级上册预学。

目标不是题海，而是用少量题暴露认知断点、错误机制和迁移能力。所有题目、诊断和学习计划都必须绑定知识图谱 Node。

核心原则：

- 模型负责命题内容和语义判断。
- Python 负责 Schema、身份、血缘、状态、租约、重试、审计和持久化。
- QF、Slot、Brief 数量由模型决定，不写死默认数量。
- 单选、多选、填空题使用固定答案，由程序判定。
- 简答题使用 rubric 和 solution_steps，由模型进行语义评分。
- Reviewer 拒绝后记录根因和建议，不自动回退上游层。
- 每一层有限重试，不允许无限生成。

## 2. 五层对象

```
Node -> QF -> Slot -> Brief -> Candidate
```

### Node

知识图谱中的知识节点，是生产输入事实。定义知识范围、核心概念、前置依赖、错误类型、教学边界和生产提示。

来源：

```
data/knowledge_graphs/math/math_knowledge_graph_v2.json
```

当前图谱共有 56 个 Node。

### QF

Question Family，Node 下稳定的题目家族，回答“这个 Node 要测哪一种独立能力”。

字段：

```
qf_id, node_id, name, task_type, measurement_intent,
independent_reason, allowed_response_modes, scope,
required_evidence, reject_if
```

QF 不是一道题，不能包含具体数字、完整题干、具体选项、答案或单个 Slot 的实例步骤。

### Slot

QF 下的具体测量槽位，回答“必须用什么结构证明哪一个能力”。

字段：

```
slot_id, node_id, qf_id, task_type, response_mode,
structure, measurement_target, conditions, error_targets,
minimum_quality, reject_if
```

Slot 不能写本次题目的具体数字、完整题干、选项或最终答案。

### Brief

针对一个 Slot 的一次具体命题计划，回答“这一次 Candidate 应如何构造”。当前正式使用 `brief-design.v2`。

顶层字段：

```
schema_version, brief_id, node_id, qf_id, slot_id, task,
mechanism, parameter_model, evidence_plan, answer_plan,
instance_acceptance
```

`mechanism` 包含唯一 `type`、`purpose`、有序 `steps`、`completion_condition`。每个 step 包含 `id`、`purpose`、`input`、`student_action`、`output`、`success_condition`。

`parameter_model` 包含 `variables`、`constraints`、`construction_steps`。每个变量包含 `name`、`role`、`type`、`domain`。

`evidence_plan.items` 每项包含 `evidence_id`、`student_action`、`observable_evidence`、`capture_mode`、`required`。

`answer_plan` 包含 `encoding`、`response_field_count`、`reference_answer_count`、`field_mapping`、`answer_evidence`、`solution_structure`。

编码映射：

```
single_choice -> choice_text
multi_choice  -> choice_text
fill_blank    -> field_text
short_answer  -> response_text
```

`instance_acceptance` 包含 `must_hold`、`uniqueness_check`、`reject_if`，必须能在 Candidate 生成后执行。

Brief 禁止写本次 Candidate 的具体数字、具体选项、具体答案、完整题干或控件配置。

### Candidate

Candidate 是孩子最终看到的一道题。模型只输出 `question-content.v1`：

```json
{
  "schema_version": "question-content.v1",
  "task_type": "calculation|reasoning|application",
  "response_mode": "single_choice|multi_choice|fill_blank|short_answer",
  "prompt": "孩子看到的完整题面",
  "choices": [],
  "answer": [],
  "rubric": [],
  "solution_steps": []
}
```

固定答案题的 `rubric`、`solution_steps` 为空，由程序判定。简答题的 `rubric`、`solution_steps` 非空，`answer` 是参考答案数组。

## 3. Brief v2 共享合同

代码：`learning_system/question_production_skills.py`

常量：`BRIEF_V2_AUTHORING_CONTRACT`

Generator 和 Reviewer 共用同一份合同，但职责不同：

```
Generator：按合同构造，并在输出前自检
Reviewer：独立按合同审查，不信任 Generator 的自检声明
```

共享合同要求：

1. 先确定唯一 `task_variant`，不能把多个变体留给 Candidate 临时决定。
2. 每个变量的 `type` 和 `domain` 必须一致，关系、精度、范围和排除条件必须可生成、可复核。
3. required evidence 必须由当前 `response_mode` 直接采集。short_answer 只能采集学生写出的内容，single_choice 只能采集选择结果，fill_blank 只能采集各空答案。
4. Brief 只能描述可变参数、关系和推导规则，不能写死本次实例。
5. 不得增加 Slot 未要求的数量、字段、第二个机制或固定实例。
6. `instance_acceptance.must_hold` 必须覆盖 Slot 最低难度、必需动作、答案字段和真实决策点。
7. `answer_plan`、`task.response_mode`、`evidence_plan.capture_mode`、字段数量和答案数量必须闭合。

程序侧已经加入：

- 缺少 `task_variant` 直接拒绝。
- required evidence 的 `capture_mode` 与 `task.response_mode` 不一致直接拒绝。
- `answer_plan.encoding` 与 `response_mode` 不一致直接拒绝。
- Brief 身份、机制、参数、答案和实例验收字段由 Validator 检查。

仍需要 Reviewer 判断：

- 自然语言参数是否真的可实例化。
- 参数关系是否数学可行。
- 难度是否达到 Slot 下限。
- 是否存在答案一眼可见的捷径。
- Brief 是否偷偷写入具体实例。
- 证据是否真的测量目标能力。

## 4. Reviewer 和编排器

四层使用独立 Reviewer：

```
QF        -> qf_reviewer_agent
Slot      -> slot_reviewer_agent
Brief     -> brief_reviewer_agent
Candidate -> candidate_reviewer_agent
```

Reviewer 输出 `semantic-review.v1`，包含：

```
decision, score, issues, repair_instructions,
root_cause_stage, recovery_action, recovery_stage, confidence
```

阶段之间串行：

```
QF 完成 -> Slot
Slot 完成 -> Brief
Brief 完成 -> Candidate
```

同一层独立分支并行：

- 多个 QF 的 Slot 可以并行。
- 多个 Slot 的 Brief 可以并行。
- 多个 Brief 的 Candidate 可以并行。

每个对象动作链：

```
Generator -> Schema Validator -> Semantic Reviewer
          -> Reviewer Validator -> Persistence
```

每个动作的输入、输出、错误和 digest 写入 `production_audit_events`。

默认每个 stage item 最多 3 次尝试。达到上限后停止，不自动回退上游。

## 5. CLI

入口：`scripts/run_question_production.py`

新 Node：

```bash
python scripts/run_question_production.py --action start --node NODE_ID --until candidate_generation
```

完成 paused Run：

```bash
python scripts/run_question_production.py --action resume --run-id RUN_ID
```

同一 Run 的有限重试：

```bash
python scripts/run_question_production.py --action retry --run-id RUN_ID
```

来源 Run 已耗尽尝试次数时，创建新 Run：

```bash
python scripts/run_question_production.py \
  --action rerun \
  --node NODE_ID \
  --source-run-id SOURCE_RUN_ID
```

`rerun` 保存 `rerun_context.source_run_id`，不修改来源 Run。

Promotion：

```bash
python scripts/run_question_production.py \
  --action promote \
  --run-id RUN_ID \
  --question-bank-version BANK_VERSION \
  --graph-version GRAPH_VERSION \
  --manifest-id MANIFEST_ID
```

Promotion 默认写入 staged，不自动激活。

## 6. 持久化与 Promotion

主要表：

```
production_runs
production_stages
production_artifacts
production_audit_events
question_bank_version_ledger
question_items
question_review_records
question_usage_policies
```

Promotion 路径：

```
Candidate artifact
  -> Candidate accepted 检查
  -> question_item 转换
  -> child interaction_schema 封装
  -> runtime reviewer evidence 封装
  -> question_items staged
  -> question_review_records
  -> question_bank_version_ledger staged
```

已修复：

- Promotion 创建运行时 `question_review_records`。
- 创建可追溯的 `question_reviewer_agent` accepted 凭证。
- 固定答案题不再被强制要求书面解题步骤。
- 题目 ID 加入题库版本 digest，避免跨版本 ID 冲突。

## 7. 当前数据库真实状态

数据库：`data/local_learning_system.sqlite`

当前题目总数：24 道。

| 版本 | 数量 | 状态 |
|---|---:|---|
| `2026-09-02.math-absolute-fraction.v1` | 11 | staged |
| `2026-09-03.math-pos-neg.v1` | 4 | staged |
| `2026-09-04.math-pos-neg.v2` | 4 | active |
| `2026-09-04.math-rational-classify.v1` | 5 | staged |

唯一 active 版本：`2026-09-04.math-pos-neg.v2`，active 题目 4 道。其余 20 道 staged，不是当前孩子可用题目。

当前 production Run：22 个。

- completed：3
- failed：19

累计流水线产物：

```
QF：61
Slot：113
Brief：70
Candidate：43
Audit event：1982
```

累计产物不等于可用题目数量。

## 8. 已完成批次

### M-G7-POS-NEG

Run：`PR-40c8c77ab199`

```
QF：2
Slot：4
Brief：4
Candidate：4
```

4 道 Candidate 通过语义 Reviewer，已完成浏览器展示验证、运行时可调度检查和 Promotion，最终版本 `2026-09-04.math-pos-neg.v2` active。

### M-G7-RATIONAL-CLASSIFY

Run：`PR-33aba53f8444`

```
QF：3
Slot：5
Brief：5
Candidate：5
```

5 道 Candidate 通过 Reviewer，评分约 9.5-9.7，已 Promotion 为 `2026-09-04.math-rational-classify.v1` staged。尚未做新的真实浏览器 Gate，也没有激活。

## 9. 最近失败批次

### M-G7-NUMBER-LINE

Run：`PR-8ed3c89406f4`

```
QF：3
Slot：4
Brief：1 通过，3 拒绝
Candidate：0
```

问题：任务变体没有固定；evidence 声称 short_answer 能证明学生没有做某些动作；难度下限没有形成可执行验收。

### 三 Node 并发批次

首次并发：

```
M-PRE-NUMBER-SENSE      PR-6aa992c9683b
M-PRE-ORDER-OPS         PR-982676684d66
M-PRE-FRACTION-MEANING  PR-8a08e3454958
```

随后用 `rerun` 创建：

```
M-PRE-NUMBER-SENSE      PR-4bfcac01b79c
M-PRE-ORDER-OPS         PR-c2672285023e
M-PRE-FRACTION-MEANING  PR-033606ab80ef
```

重跑结果：

| Node | QF | Slot | Brief 通过 | Brief 拒绝 | Candidate |
|---|---:|---:|---:|---:|---:|
| `M-PRE-NUMBER-SENSE` | 3 | 6 | 2 | 4 | 0 |
| `M-PRE-ORDER-OPS` | 4 | 7 | 3 | 4 | 0 |
| `M-PRE-FRACTION-MEANING` | 3 | 6 | 2 | 4 | 0 |

两批并发均无 SQLite 锁冲突或数据串线。失败共性：参数关系无法实例化、答案合同不闭合、证据超出控件能力、Brief 增加 Slot 没要求的目标、精度/舍入/字段解析规则不明确。

## 10. 代码索引

```
learning_system/question_production_skills.py
learning_system/question_production_orchestrator.py
learning_system/question_production_persistence.py
learning_system/question_production_audit.py
learning_system/question_production_promotion.py
learning_system/question_bank.py
learning_system/db.py
scripts/run_question_production.py
```

关键入口：

- Prompt：`build_qf_prompt`、`build_slot_prompt`、`build_brief_v2_prompt`、`build_candidate_prompt`
- Reviewer Prompt：`build_semantic_review_prompt`
- Validator：`validate_qf`、`validate_slot`、`validate_brief`、`validate_candidate`
- Live Skills：`build_live_question_production_skills`
- Orchestrator：`run`、`run_until`、`resume`、`retry`、`rerun`、`recover`、`revise_structure`
- Promotion：`promote_run`

## 11. 测试

生产相关：

```bash
python -m unittest \
  tests.test_question_production_prompts \
  tests.test_question_production_skills \
  tests.test_question_production_orchestrator \
  tests.test_question_production_review_pipeline \
  tests.test_question_production_promotion \
  tests.test_run_question_production
```

展示和运行时：

```bash
python -m unittest \
  tests.test_child_prompt_v6 \
  tests.test_question_artifact \
  tests.test_question_bank_runtime_authority
```

最近验证：

```
98 tests passed
Python compile check passed
git diff --check passed
```

真实浏览器 Gate 在 `M-G7-POS-NEG` 上通过。Playwright Chromium 已安装。

## 12. 下一会话建议

不要继续无修改地重跑失败 Node。建议：

1. 先读取本文、`AGENTS.md` 和数据库现状，不删除历史 Run 或失败产物。
2. 将 Brief v2 参数模型升级为结构化的类型、范围、关系、派生值、展示精度和舍入合同。
3. 给 evidence item 增加来源边界，区分 `question_surface`、`student_response`、`choice_selection`、`fill_blank_fields`。
4. 增加 Slot 到 Brief 的逐条约束追踪。
5. 增加 Candidate 可执行性 preflight，在进入语义 Reviewer 前检查答案数量、字段数量、题型映射、变体数量和实例闭合。
6. 评估分支级继续：通过的 Brief 继续 Candidate，失败 Brief 停止，不阻断兄弟分支。
7. 对 `2026-09-04.math-rational-classify.v1` 做真实浏览器展示验证后，再决定是否激活。
8. 批量生产使用 `rerun` 创建新 Run，不重置旧 Run 的尝试次数。

最重要的原则：

```
不要为某一道题追加特殊规则。
把失败抽象为通用的合同、类型、证据来源或状态机问题。
```

