# Collaboration Inbox

Status: current cross-context board
Updated: 2026-07-17

Use this file only when a task, blocker, result, or handoff must persist across runtime contexts or manual sessions. Do not use it as chat history.

## Message Shape

```text
### MSG-YYYYMMDD-NNN - TASK|RESULT|STATUS|BLOCKED|CLOSED / <topic>

- From:
- To:
- Status: OPEN|ACKED|DONE|PASS|NEEDS_FIX|BLOCKED|CLOSED
- Related: <paths/message IDs or none>

Objective or result:
Scope:
Inputs or evidence:
Allowed changes:
Expected result or next action:
Stop condition:
```

Use only fields that matter. Link evidence instead of pasting long content.

## Read Rule

Search active messages by current `agentKey`, display name, `ALL`, or `全员`. Read only relevant `OPEN`, `ACKED`, `NEEDS_FIX`, or `BLOCKED` messages.

## Write Rule

Write only when durable coordination is needed. Prefer direct runtime dispatch/reply for transient work.

## Open Messages

### MSG-20260717-001 - REQUEST / v12 教学质量门与完整交付续作

- From: 若命（agentKey: `ruoming`）
- To: 听云、观止、镜花、清秋
- Status: OPEN
- Related:
  - `learning_system/child_prompt.py`
  - `learning_system/question_bank.py`
  - `scripts/build_math_question_bank_v12.py`
  - `learning_system/agent_contracts/math_question_bank_v12_node_set_global_finalizer.v6.json`
  - `docs/product/child_prompt_representation_rendering_repair_contract_v5_1.md`

Objective:
先关闭 v12 题库教学质量假通过和孩子题面失真风险，再修复问题题位、续跑到 56 个节点 / 1,120 道题，完成全库审查、答案合同、激活和真实课程验收。

Current state:
- Git 主线已建立并推送到 `seraphimlc/learning-system`，当前基线提交 `317abea`。
- v12 已完成 43/56 节点、860 道封存题；`M-G7-EQ-PAREN` 为 15/20，因此检查点中共有 875 道题。
- live 生成继续暂停，直到 v6 质量门通过独立 review、QA 和 UX browser gate。
- v6 child-surface、global finalizer、runtime/frontend 接线已有部分实现，但尚未获得最终交付证据。

Authority and order:
1. 听云是生产代码单一写入者，完成 v6 合同、兼容、原子 force 操作和工程自测。
2. 镜花独立审查 runtime/model 权威、证据绑定、旧 review 复用、检查点原子性和防自声明假绿。
3. 观止执行确定性负例、教学语义 oracle、检查点零写入、live model 和最终 10 节浏览器课程 QA；mock 不能证明 semantic PASS。
4. 清秋执行 1280/390/200% 的真实题面、换行、指数、选择/填空/解释控件、键盘和 child-safe 失败态 UX gate。
5. 若命负责题位返修授权、阶段门、激活、提交推送和最终交付判断。

Hard boundaries:
- 普通文本评分最多一次 GPT；明确“我不会/卡住”零模型调用；照片为豆包 OCR 加一次 GPT。
- 不用正则或字符串匹配判断数学正确性；程序只拥有格式、身份、哈希、枚举、覆盖、状态和分数 reducer。
- 低质量题位修复前不得恢复全库生成；v12 未完成并激活前不得生成正式 1,120 份答案合同。
- 不重置真实 SQLite，不提交密钥、数据库、孩子上传、日志或备份，不把 recorded/mock 冒充 live PASS。

Expected result:
v6 gate 全绿；问题题位返修并重审；题库 56/56、1120/1120；全库 activation-ready；答案合同生成审计并激活；8765 服务完成桌面/移动端和 10 节真实课程验收；每日与最终报告可由 Codex 查询。

Stop condition:
四个正式角色均给出与其职责一致的通过证据，生产检查点和数据库迁移可追溯且可恢复，孩子可以在无家长介入下连续完成复习和新知识课程，若命才可关闭本消息。

### MSG-20260716-001 - TASK / 知识首页连接与继续学习状态 UX 复审

- From: 听云（agentKey: `tingyun`）
- To: 清秋（agentKey: `qingqiu`）
- Status: OPEN
- Related:
  - `app/local_learning_system/app.js`
  - `app/local_learning_system/knowledge_views.js`
  - `tests/fixtures/browser_knowledge_views_v51.mjs`
  - `tests/test_knowledge_views_v51.py`

Objective or result:
复审两个已实现的最小状态修复：知识投影加载成功后连接状态显示“准备好了”；`current_learning.state=not_started` 时隐藏“继续当前学习”，切换到可继续状态后按钮恢复显示。

Inputs or evidence:
听云工程自检：新增三项浏览器状态断言通过；focused 浏览器契约 `1/1 PASS`；知识视图全模块 `27/27 PASS`。未触碰真实数据库或 live 模型。

Allowed changes:
本轮先独立 UX 复审；发现明确问题时返回最小修复建议，不直接扩展产品状态或学习流程。

Expected result or next action:
清秋返回独立 UX review 结论，重点核对初始无学习任务时的动作可见性、连接状态文案和状态切换后的可恢复性。

Stop condition:
给出 `PASS_WITH_SCOPE` 或 `UX_REVIEW_NEEDS_FIX`，并列明证据范围。

### MSG-20260714-001 - REQUEST / v5.1 确定性评分与双视图知识首页交付

- From: 若命（agentKey: `ruoming`）
- To: 听云、观止、镜花、清秋
- Status: OPEN
- Related:
  - `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
  - `docs/design/specs/2026-07-14-answer-assessment-storage-design.md`
  - `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md`
  - `docs/design/specs/2026-07-14-child-knowledge-map-home-design.md`
  - `.agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md`

Objective:
先完成 1,120 道 v11 题的版本化答案合同、单次 GPT 判据判断、程序确定性 10 分制评分与逐题反馈，再把同一 56 节点知识图谱投影为可手动切换的导图和有向关系图谱首页。

Current authority:
- 普通文本作答热路径只允许一次 GPT 语义判据调用；明确卡住/我不会零模型调用；照片为豆包 OCR 加一次 GPT。
- `attempt_assessments` 是评分权威，模型不得直接给分、写 mastery 或决定下一步。
- 导图和图谱共用同一图谱事实、节点状态、选择和学习入口；底层 graph JSON 不改。
- 首次默认导图并记忆本地 UI 偏好；图谱废弃九个封闭大框，采用带箭头的主干拓扑。
- 答案合同激活是知识节点正式诊断/学习动作的硬前置。

Project boundary overlay:
单孩子子端；SQLite；GPT-5.5 文本；豆包 OCR；不新增家长 Web；不重置真实数据；不初始化 Git；不把 mock/recorded 冒充 live semantic PASS；所有页面/API child-safe；AGENTS.md 的图谱、题库、前置回退和 QA/架构附加规则继续有效。

Role routing:
- 清秋：双视图 `UX_FLOW_SPEC` 与最终真实页面 UX review。
- 听云：工程来源挑战、工程合同/蓝图修订、单一生产代码写入、测试和 `DONE_CLAIMED`。
- 镜花：工程合同/蓝图、评分权威、状态机、双视图投影和代码独立 review。
- 观止：测试来源挑战、红测、语义/OCR/恢复/浏览器/泄漏 QA。
- 若命：产品权威、阶段门控、数据备份、结果整合、激活与最终交付判断。

Supersession:
`MSG-20260711-002/004` 中普通作答必须依次调用 evaluation/planner/teaching 模型的旧热路径假设，被本消息的单次语义判断加确定性 reducer 取代；其证据安全、新知识教学、真实浏览器和 live semantic 要求仍有效。`MSG-20260711-003` 的恢复、澄清、幂等和 child-safe 约束继续有效。

Stop condition:
合同覆盖、代码 review、UX review、QA、真实模型语义、桌面/390px 浏览器、数据库迁移/回滚和正式 8765 服务验证全部有可核验证据后，若命才能关闭本消息。

### MSG-20260711-004 - REQUEST / v5 语义协作与新知识主链补全

- From: 若命（agentKey: `ruoming`）
- To: 听云、观止、镜花、清秋
- Status: OPEN
- Related:
  - `docs/product/ai_native_math_learning_product_structure_v5.md`
  - `docs/product/child_ux_flow_spec_v5.md`
  - `docs/architecture/technical_plan_v5.md`
  - `docs/architecture/implementation_blueprint_v5.md`
  - `docs/qa/test_case_spec_v5.md`

Objective:
把当前已经可执行的 v5 durable DAG 从“任务顺序串通”提升为“语义证据真正串通”，并补全孩子独立完成的新知识教学主链。

Scope:
评估 Agent 的当前节点历史证据包和掌握聚合；评估输出到规划 Agent 的真实输入；10-20 题预算与安全提前结束闸门；动态 active question-bank version；按图谱选择新知识节点；讲解 Agent 的图谱知识、题目、答案分析和规划原因输入；`本质 -> 核心模型 -> worked example -> micro-check -> 标准题 -> 变式`；对应 DB lineage、报告和测试。

Forbidden scope:
不新增家长 Web 端，不让模型直接写 mastery/选择题库外问题，不把全图谱或全题库喂给模型，不从单题直接确认稳定掌握，不用 recorded/mock 冒充 live semantic PASS，不激活未通过节点级审题的 v12。

Evidence:
- 镜花对 v12 最终代码返回 `CODE_REVIEW_NEEDS_FIX`：发现 generator/seed manifest digest canonicalization 不一致、completed checkpoint 可被重新铸造 live receipt、per-item active seed 未严格校验 designer/reviewer agent+phase 三个 P1；这些关闭前 v12 只能生成审查证据，不能激活。
- node-set model probe: `gpt-5.5` remained semantically strong but repeatedly hit gateway `504`; `gpt-5.4-mini` completed in `39.54s` but missed prerequisite/context risks; `gpt-5.4` completed the formal four-shard expert review in `63.87s` and caught duplicate cores, literal escapes, slot-role concentration, and the false prerequisite probe. Project routing decision: designer/item reviewer stay on `gpt-5.5`; node-set review uses task-specific `gpt-5.4`, concurrency 1.
- v12 node-set live probe: one 5-slot GPT shard succeeded in `70.51s` and another in `27.35s`, correctly rejecting known duplicate groups; 4-concurrent and 2-concurrent heavy review calls both produced gateway `504`. Current project runbook therefore requires a separate node-review concurrency of 1 with checkpoint/resume, while single-slot designer/item-review concurrency may remain 4.
- 清秋已返回 `UX_REVIEW_NEEDS_FIX`：新知识入口绕过 teaching package，micro-check 不保证核心模型递进，单一长 `prompt` payload 不能稳定承载“本质/模型/例题/下一步”。
- 镜花已返回 `CODE_REVIEW_NEEDS_FIX`：确认 answer-analysis provenance mismatch、单次证据覆盖 mastery、planner 看不到 evaluation/budget、active-bank 常量散落、新知识绕过 teaching_generation 五个 P1。
- v5 live answer analysis still calls the inline `auto_review._review_prompt()` / `_response_schema()`, while its `agent_runs` provenance is recorded from the separate `answer_review.v2` contract/prompt; actual model prompt/schema and recorded contract can diverge, and the intended trusted-question/untrusted-answer boundary is not enforced by the recorded artifact.
- `DailyLearningRuntime._handle_evaluation_update_job()` 当前只向评估 Agent 提供单次 `answer_analysis`，没有近期有效历史、图谱 mastery criteria 或当前状态。
- `_record_evaluation_update()` 以当前单次 attempt 覆盖节点状态，未累积 varied evidence，且不能形成稳定掌握闭环。
- planner job payload 虽保存 evaluation，但 `SemanticAgentRequest.trusted_context` 未传入 evaluation 结论，Agent 间只有 lineage 串联，没有语义输入串联。
- live planner 缺少已完成题数、预算和安全提前结束约束，runtime 未阻止过早 summary。
- `start_new_knowledge_from_checkpoint()` 当前把普通题目和参考答案直接包装成 worked example，未调用真实 teaching Agent，也未按图谱挑选新知识节点。
- `test_v5_ready_checkpoint_can_start_new_knowledge_worked_example` 只验证页面壳和下一步，不验证教学内容、图谱选点、Agent 调用或学习结果。

Required next action:
听云在 v12 节点审题执行修复后提交工程实现；镜花给出状态/证据/active-bank 架构审查；观止先写会失败的语义与浏览器用例并执行真实模型 gate；清秋明确新知识页面状态、交互和文案验收。若命在四方结果闭环前不授权 v12 激活或最终交付。

### MSG-20260711-003 - PRODUCT_STRUCTURE_SPEC / v5 阻塞恢复与无法补充证据收口

- From: 若命（agentKey: `ruoming`）
- To: 听云、观止、镜花、清秋
- Status: OPEN
- Related:
  - `docs/collaboration/inbox.md#msg-20260711-002---request--v5-runtime-完整化与真实验收`
  - `docs/product/ai_native_math_learning_product_structure_v5.md`
  - `docs/product/child_ux_flow_spec_v5.md`
  - `docs/architecture/engineering_contract_v5.md`
  - `docs/qa/test_case_spec_v5.md`

Objective:
消除 v5 `blocked` 和 `clarify_evidence` 的两个实现歧义，使孩子无需家长介入也能得到真实、有限且可审计的出口。

Product decisions:
- `blocked` 主操作不是普通刷新。孩子触发“再试一次”或 bootstrap/resume 时，runtime 必须检查最近一次可恢复的 terminal model job；只有原 attempt/step 仍有效、没有已接受的下游结果、对应模型路由已经恢复时，才创建显式 recovery job。
- recovery job 必须引用原 job，并使用新的 recovery generation/source-phase idempotency key；同一个 terminal key 仍复用旧结果，不能静默复制或空转。恢复后只能进入 `analyzing_pending`，随后有限地收敛到 current step、clarify、blocked 或 summary。
- 自动模型重试最多 3 次执行尝试；耗尽后必须保留已保存答案，终止 analyzing，并投影为 child-safe blocked 或 summary。pending/mock/stale/missing-lineage 不得更新掌握或驱动依赖型下一步。
- `clarify_evidence` 必须提供稳定的“仍无法补充”动作。该动作记录一条 `cannot_provide`/stuck 证据，保留来源关系，但不重新判原答案、不更新掌握、不再创建新的 active clarify step。
- 本阶段的稳定收口策略是直接生成带 pending/blocked 标签的 summary；以后若要继续到无依赖的新节点，必须另开产品规则，不得在当前实现中猜测。
- terminal summary 的完成操作是幂等 no-op；重复点击或刷新仍返回同一 summary，不再出现答题或下一题动作。

Scope:
Runtime recovery/reconciliation、job idempotency generation、child projection、clarify submission、summary idempotency、前端动作与对应测试/报告 lineage。

Forbidden scope:
不重置真实数据，不把 GET/刷新伪装成成功，不从无效证据更新掌握，不恢复家长介入，不引入新的用户端或自动自进化。

Evidence:
观止 `TEST_CASE_REVIEW` 的 4 个红测：blocked recovery、bounded analyzing、clarify cannot-provide、terminal finish；清秋 `UX_REVIEW_NEEDS_FIX` 的同类 P0/P1 结论。

Required next action:
听云按本决策实现；清秋把稳定文案/动作补入 UX_FLOW_SPEC；镜花审查恢复幂等与状态机；观止按红测和浏览器行为验收。

### MSG-20260711-002 - REQUEST / v5 runtime 完整化与真实验收

- From: 若命（agentKey: `ruoming`）
- To: 听云、观止、镜花、清秋
- Status: OPEN
- Related:
  - `docs/product/ai_native_math_learning_prd_v5.md`
  - `docs/product/ai_native_math_learning_product_structure_v5.md`
  - `docs/product/child_ux_flow_spec_v5.md`
  - `docs/architecture/technical_plan_v5.md`
  - `docs/architecture/engineering_contract_v5.md`
  - `docs/architecture/implementation_blueprint_v5.md`
  - `docs/qa/test_case_spec_v5.md`

Objective:
把当前可运行但仍为 first-slice 的 `DailyLearningRuntime` 收束为程序框架主导、语义 Agent 严格分工、可持久化恢复、可真实验收的 v5 主链路，并完成独立工程 review、UX review、QA 和 live 课程验证。

Scope:
当前步骤状态机、答案保存/照片/卡住、模型路由、答案分析、证据门、评估、讲解、规划、下一题、队列重试恢复、child-safe 投影、日报和对应测试。SQLite 继续作为本地存储；GPT 负责文本语义，豆包负责图片识别。

Forbidden scope:
不新增家长 Web 端，不恢复自动自进化，不引入多用户体系，不重置或破坏真实学习数据，不把整份题库或图谱喂给模型，不用 mock 结果冒充 live semantic PASS。

Evidence:
当前代码已存在 v5 current-step 主链路和 236 项回归，但真实库仍无完整 live attempt 证据；`process_next_background_job()` 只消费 `answer_analysis`，后续评估/讲解/规划主要在单任务内串行执行，最终交付仍缺持久化节点边界和最新 10 节课真实验收。

Required next action:
听云完成工程来源挑战与修复蓝图；镜花审查状态机/异步/Agent 边界；观止补齐 source readiness 与测试缺口；清秋核对孩子端等待、讲解、澄清、结束的交互约束。若命收敛后授权单写入者实施并依次关闭 review/QA gate。

### MSG-20260710-001 - STATUS / 学习过程记录与回放设计 TODO

- From: 若命（agentKey: `ruoming`）
- To: 若命（agentKey: `ruoming`）
- Status: OPEN
- Related:
  - `docs/system/qa/latest.md`

Objective:
记录后续需要设计“学习过程记录与回放”机制：每一轮课的目标、出题原因、孩子答案、AI 批阅、讲解反馈、下一题决策、本轮总结和下轮建议都要可追溯保存，供后续 Codex 查询、复盘、规划下一课和系统调试使用。

Scope:
仅保留架构 TODO。后续再决定运行必需事实、审计日志、模型输入输出快照、Markdown 报告分别放 SQLite、JSONL/log 文件还是分层保存。

Forbidden scope:
本条不启动数据库 schema 设计，不实现日志系统，不引入复杂 memory/vector database，不改变当前 v3 runtime。

Evidence:
用户确认“不做记忆系统，但要完整记录每次会话事实；后续用历史 summary 决定本次课学什么”。

Required next action:
在下一轮产品/技术方案收束时，把该 TODO 纳入 simplified learning loop：`选题 -> 答题 -> AI判断 -> 讲解/纠错 -> 决定下一题 -> 汇总报告` 的记录设计。

### MSG-20260711-001 - STATUS / 下一题决策规则专题 TODO

- From: 若命（agentKey: `ruoming`）
- To: 若命（agentKey: `ruoming`）
- Status: OPEN
- Related:
  - `docs/collaboration/inbox.md#msg-20260710-001---status--学习过程记录与回放设计-todo`

Objective:
后续单独讨论“下一题决策规则”：什么情况下同类再测、micro-teach、前置回退、拔高、继续或结束本轮。先由模型协助生成一版规则初稿，再由用户和若命讨论校准。

Scope:
仅保留产品/规则 TODO。规则应服务 simplified learning loop，而不是重新扩大成复杂 agent 编排；AI 批阅可以给 `next_action` 建议，但 runtime 必须结合本轮进度、近期表现、知识点状态和题库可用性做最终决策。

Forbidden scope:
本条不立即设计完整规则、不实现 planner、不改题库、不新增模型调用。

Evidence:
用户确认这块后面专门讨论，并希望先由模型协助生成一版规则。

Required next action:
进入该专题时，先让模型产出一版简洁可执行的 next-question decision rule draft，再评审是否符合“简单做题系统 + AI 判断闭环”的产品边界。

### MSG-20260708-002 - REQUEST / REG-05 durable child error panels

- From: 若命（agentKey: `ruoming`）
- To: 听云（agentKey: `tingyun`）
- Status: CLOSED
- Related:
  - `docs/qa/test_case_spec_v2.md`
  - `docs/product/child_ux_flow_spec_v2.md`
  - `docs/collaboration/reviews/2026-07-08-qingqiu-code-skeleton-ux-review-v2.md`
  - `docs/collaboration/reviews/2026-07-08-qingqiu-reg05-error-panel-ux-rereview.md`
  - `docs/collaboration/reviews/2026-07-08-guanzhi-reg05-error-panel-qa-rerun.md`

Objective:
Implement durable child-facing error panels for `load_error`, `save_error`, and `upload_error` so these states are inspectable by browser screenshots, keyboard focus, and accessibility checks.

Scope:
`app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`, and focused browser/test updates.

Forbidden scope:
No backend evidence/model/question/planner changes, no DB/upload reset, no external model calls, no parent dashboard, no QA PASS claim.

Evidence:
听云 returned `DONE_CLAIMED`; changed child page DOM/JS/CSS and browser smoke for durable error panel checks. 若命 fixed the `load_error` toast copy mismatch so initial page-load failure no longer says save failed. 清秋 targeted UX rereview returned `PASS_WITH_SCOPE`; 观止 focused REG-05 QA rerun returned `PASS_WITH_SCOPE`.

Required next action:
REG-05 is closed for the scoped durable error-panel fix. Broader child-flow release QA still needs screenshot/accessibility/keyboard coverage and live semantic/model checks.

### MSG-20260708-001 - REQUEST / v2 code SKELETON_PASS

- From: 若命（agentKey: `ruoming`）
- To: 听云（agentKey: `tingyun`）
- Status: DONE_CLAIMED
- Related:
  - `docs/product/ai_native_math_learning_prd_v2.md`
  - `docs/product/child_ux_flow_spec_v2.md`
  - `docs/architecture/data_contract_spec_v2.md`
  - `docs/architecture/technical_plan_v2.md`
  - `docs/architecture/project_skeleton_v2.md`
  - `docs/qa/test_case_spec_v2.md`

Objective:
Create the actual code `SKELETON_PASS` for v2 child-only learning architecture, exposing page/API/service/worker/model/evidence/question/report/test seams before business logic fill.

Scope:
Skeleton/contract normalization in `learning_system/`, `app/local_learning_system/`, selected tests/scripts, and `docs/architecture/code_skeleton_pass_v2.md`.

Forbidden scope:
No parent dashboard, no destructive DB reset, no external model calls, no non-trivial business logic fill, no review/QA PASS claims.

Evidence:
听云 returned `SKELETON_PASS`; durable evidence written to `docs/architecture/code_skeleton_pass_v2.md`. Gate review still pending.

Required next action:
After `SKELETON_PASS`, route skeleton review to 镜花、清秋, then route 观止 to refine `TEST_CASE_SPEC` against actual file/symbol targets.

### MSG-YYYYMMDD-001 - REQUEST / EXAMPLE

- From: 若命（agentKey: `ruoming`）
- To: 听云（agentKey: `tingyun`）
- Status: CLOSED
- Related:
  - `docs/collaboration.md`

Objective:
Replace this example with a real task.

Scope:
Example only.

Forbidden scope:
Do not execute.

Evidence:
N/A.

Required next action:
Delete or archive this example when real collaboration starts.
