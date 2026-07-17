# Son AI Learning System

这是一个给孩子定制的 AI 原生学习系统工程。

当前阶段只服务一个真实对象：即将升入初一的孩子。系统目标不是做通用教育产品，也不是做传统刷题软件，而是用 AI 教研闭环帮助孩子在暑假内补齐小学关键漏洞，并预学人教版七年级上册数学与英语。

## 当前状态

- 项目阶段：本地可运行 v1.4，并已加入内部 agent 合同层与会话编排审计路径
- 当前重点：数学优先
- 已完成资产：数学知识图谱 v2、首诊题、图谱绑定练习题、本地学习闭环页面
- 本地系统：孩子端做题/拍照提交；孩子页面只调用 child-safe 接口；系统自动进行 AI 答案分析、错因判断、讲解、巩固、拔高、下一轮规划和证据驱动自进化
- 家长交互：家长只通过 Codex 查看学习进展、讨论系统改造和复盘证据；不做网页端人工批改、不复制给 Codex、不手动推动孩子学习流程
- 内置 agent：会话编排、图谱、命题、审题、答案分析、评估、讲解、规划、自进化是系统内部角色；答案分析和命题候选可以接模型，但模型输出必须经过合同、业务校验、审题门和 Orchestrator 状态机，不直接改掌握状态
- 当前题库：56 个图谱节点、1120 道最新版 `QB9` 图谱生成练习题（每节点 20 道）、48 道带质量门禁的首诊题；
  本地 DB 若保留旧尝试，会额外保留旧版题目行作为历史证据，但调度优先最新版题目

题库不是题海。每道新版练习题都必须绑定图谱节点，带命题意图、六升七年龄底线、认知层级、过程证据要求和审题通过记录。裸算术、只看最终答案、孩子端元话术、低龄侮辱式题目不能进入主动调度；如果计算薄弱，只用估算、错解辨析、规则解释、检验或迁移变式做结构性治理。孩子端每轮学习任务固定为 10 题，组卷时混合模型选择、错解辨析、两法比较、近/远迁移、条件完整性和受控拔高，不用低龄机械题凑数。

## 下一版架构共识

- 只保留一个儿子端 Web 页面。
- 儿子完成一组题后，系统自动完成：答案分析 → 知识点/错因判断 → 针对性讲解 → 巩固题 → 拔高题 → 本轮收口。
- 学新知识时，系统按“本质解释 → 核心模型 → 标准例题 → 变式 → 检测 → 错因回退”推进。
- 内部 agent 的提示词是面向模型的工程合同，不是展示给孩子或家长看的文案。
- Orchestrator 是唯一有权推进 session 状态、关闭一轮学习、更新节点掌握状态的运行时单元；其它模型 agent 只产出候选判断、候选题、候选讲解或候选规划。
- 自进化必须来自真实已处理证据：有 attempt、有结构化 `answer_analysis`、有 `evolution_audits`、有题目/规则/计划变化，不能只是为了测试增加一条记录。单次做对只算强证据，不直接标成完全掌握。
- 当前实现已落地内部 agent contract/prompt 文件、child-safe 校验、child/operator bootstrap 拆分、agent run 审计表、question review 审计表、mastery decision 审计表、evolution audit 审计表，以及 server 侧 session close 的 Orchestrator 入口。
- 当前实现已接入共享模型路由：答案分析、命题候选、照片 OCR 分别可配置模型；同一公司中转站 base URL 可复用，命题候选默认走 `deepseek-v4-pro-260425`，照片 OCR 默认走 `doubao-seed-2-0-pro-260215`，但 OCR 只作为非可信转写证据，最终判断仍由答案分析 Agent 完成。
- 当前实现已接入模型命题候选链路：弱证据触发时先请求 `question_designer_agent` 模型候选，再由代码重算 `question_reviewer_agent` 质量门；模型 504、低置信、格式错、引用不存在图谱节点、含注入式指令或出低级机械题时不落库，记录拒绝并生成确定性 fallback，后台 AI 批阅也会做有限重试。
- 当前实现已把九个正式内部 agent 串入同一轮学习闭环：孩子整组提交后，同一 `session_id` 下会留下答案分析、图谱绑定、评估、自进化、命题、审题、规划、讲解和会话编排的运行/审计证据；`agent_handoffs` 与 `session_steps` 用来追溯后台流程，孩子端只接收 child-safe 完成提示。
- 当前孩子端 session complete 接口只返回 child-safe 收口信息；Codex/operator 需要完整 agent 链、evolution、plan 证据时走 operator API。

## 关键文件

- 完整设计文档：`docs/00_PROJECT_BLUEPRINT.md`
- 数学知识图谱 JSON：`data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- 数学知识图谱说明：`data/knowledge_graphs/math/math_knowledge_graph_v2.md`
- 本地系统说明：`docs/system/local_learning_system.md`
- 儿子端教学会话架构：`docs/design/specs/2026-07-05-child-only-teaching-session-architecture-design.md`
- 内部 agent 模型/提示词合同：`docs/design/specs/2026-07-05-internal-agent-model-prompt-contract-design.md`
- 明日复盘报告：`docs/system/tomorrow_review_2026-07-05.md`
- 本地系统入口：`app/local_learning_system/`
- 后端/API：`learning_system/`
- 测试：`tests/test_learning_system.py`、`tests/browser_smoke_learning_system.mjs`

## 本地运行

```bash
python3 scripts/init_learning_system_db.py
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

如果 8765 被占用，换一个端口，例如：

```bash
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8766
```

打开 `http://127.0.0.1:8765` 或对应端口。

## 继续开发时请先读

新会话或新 agent 接手时，必须先阅读：

1. `docs/00_PROJECT_BLUEPRINT.md`
2. `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
3. `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
4. `docs/system/local_learning_system.md`
5. `docs/design/specs/2026-07-05-child-only-teaching-session-architecture-design.md`
6. `docs/design/specs/2026-07-05-internal-agent-model-prompt-contract-design.md`

## 验证

```bash
python3 -m unittest tests/test_learning_system.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
node scripts/validate_math_diagnostic_v1.mjs
node scripts/verify_math_diagnostic_page_export.mjs
```
