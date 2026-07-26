# Collaboration Inbox

Status: current cross-context board
Updated: 2026-07-24

Use this file only for durable coordination that must survive between Codex
contexts or manual agent sessions. It is not chat history.

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
Expected result or next action:
Stop condition:
```

## Open Messages

### MSG-20260724-001 - TASK / KnowledgeCard v2 表达规则

- From: 若命
- To: 若命 / 清秋 / 听云 / 镜花 / 观止
- Status: OPEN
- Related:
  - `docs/design/specs/2026-07-20-knowledge-card-v2-generation-rules.md`
  - `data/knowledge_cards/`
  - `learning_system/knowledge_cards.py`

Objective or result:
为每个知识点建立“教学合同 + 自由表达组件编排”的知识卡规则，不把所有知识点做成统一文字模板。

Scope:
根据数学本质、常见误解、掌握证据和迁移价值选择表达形式。允许图文、交互、动画、拖拽、数轴、天平、线段图、几何标注、表格、拍照作答等组件，但每个组件必须服务于理解或证据采集。

Expected result or next action:
形成可执行的 KnowledgeCard v2 生成规则，并用 3 个代表性知识点做页面预览和评审。

Stop condition:
规则能说明“为什么这个知识点适合这种表达”，并通过孩子可读性、教学有效性、实现稳定性三方检查。

### MSG-20260724-002 - TASK / v18 高质量题库生产

- From: 若命
- To: 听云 / 观止 / 镜花
- Status: OPEN
- Related:
  - `docs/design/specs/2026-07-23-question-bank-production-spec-v18.1.md`
  - `data/question_banks/v18/question_type_taxonomy_v18.json`
  - `data/question_banks/v18/node_question_blueprints_v18.json`
  - `scripts/admin_full_bank_production_runner.py`

Objective or result:
按知识图谱和专家题型架构生成高质量题库。不要凑数量；每题必须有设计意图、标准答案、轻量评分合同和专家评审记录。

Scope:
专家先定义节点覆盖和题型要求，命题 agent 并发生成多个单题 workflow，专家审核不合格则返回重生。staged 写入串行加锁；未通过 gate 的题不能进入孩子端。

Expected result or next action:
从空的 `staged_candidates_v18.json` 开始，按 gap-driven workflow 分批生成、审核、入库，并持续输出 Codex 可查询的生产证据。

Stop condition:
v18 activation gate 明确通过前，题库保持 staged_not_active。
