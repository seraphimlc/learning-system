# 现状数据流核对记录（学期数据链路前置 · Chunk 1）

- Date: 2026-08-20
- Owner: 若命（软件架构）——核对执行与裁定记录
- Status: 完成（2026-08-20 定稿）；核对项 1–7 全部填写，含裁定结论与显式挂起项
- Scope: `learning_system/` 数据流现状核对 + 裁定点记录（只读分析）
- 前置文档：`docs/design/specs/2026-08-20-child-learning-companion-design.md`（§8.1 第 0 步核对）、`docs/00_PROJECT_BLUEPRINT.md`
- 实现计划：`.agents/superpowers/specs/2026-08-20-semester-data-link-prereqs.md`（Chunk 1）

> **用途声明：本记录仅供设计决策参考，不改任何代码/数据。** 所有核对均为只读分析；任何"结论"都只影响后续设计裁定，不构成对 `learning_system/`、`data/` 或运行库的修改授权。

> **一句话结论**：本记录逐项核对现状数据流，对每个裁定点给出「现状 / 冲突 / 选择 / 影响」，或显式"挂起待 X"；7 项核对齐全后，作为数据模型改动（设计稿 §8.2）与后续计划（阶段数组 / M2.5 判定口径统一 / M4 错题录入）的决策依据。

---

## 目录

1. [背景与用途](#1-背景与用途)
2. [核对清单（7 项）](#2-核对清单7-项)
3. [裁定点模板](#3-裁定点模板)
4. [核对项记录](#4-核对项记录)
   - [核对项 1：长期状态表与消费方](#核对项-1长期状态表与消费方attempts--learner_node_status--mastery_decisions)
   - [核对项 2：短期计划表](#核对项-2短期计划表generated_plans--daily_flows)
   - [核对项 3：已裁定新增表（新增 vs 别名）](#核对项-3已裁定新增表新增-vs-别名)
   - [核对项 4：attempts FK 三方案影响](#核对项-4attempts-fk-三方案影响)
   - [核对项 5：phase_strategy 现状与迁移裁定](#核对项-5phase_strategy-现状与迁移裁定)
   - [核对项 6：判定口径逐实现](#核对项-6判定口径逐实现)
   - [核对项 7：CANONICAL_ERROR_TAGS 双定义](#核对项-7canonical_error_tags-双定义)
5. [完成条件与后续](#5-完成条件与后续)

---

## 1. 背景与用途

设计稿 §8.1 将「现状数据流核对」列为切片第 0 步（先于编码）：逐表对照现状与需求，裁定数据模型改动依据。本记录即该步的交付物——**逐项核对记录 + 裁定点结论**，每个裁定点必须给出「现状 / 冲突 / 选择 / 影响」，或明确"挂起待 X"。

本记录是 Chunk 1 的最终交付物；核对项 1–7 已由 Task 2–8 逐项填写完成（骨架期只搭结构与模板，不预填核对结论）。

---

## 2. 核对清单（7 项）

核对清单来自设计稿 §8.1（含第三轮会审扩项与 §3.1/§3.3 必答项），共 7 项：

| # | 核对项 | 来源 | 必答项标记 | 状态 |
|---|---|---|---|---|
| 1 | `attempts` / `learner_node_status` / `mastery_decisions` 表与消费方 | spec §8.1 第 0 步逐表对照 | — | 已完成（Task 2） |
| 2 | `generated_plans` / `daily_flows`（短期计划现状） | spec §8.1 第 0 步逐表对照 | — | 已完成（Task 4） |
| 3 | **已裁定新增表**：`error_cause_log` / `weekly_summary`（A/B/C/D 时间快照 + acknowledged 枚举）/「作业全对」确认载体 → **「新增 vs 别名」裁定** | spec §8.1 必答项**首项**、§3.3 | ✅ 必答 | 已完成（Task 3） |
| 4 | `attempts` FK 三方案影响（`question_id`/`session_id` NOT NULL） | spec §8.1 必答项、§3.1 | ✅ 必答 | 已核对（Task 5）：推荐方案③ 旁挂侧表再反链 |
| 5 | `phase_strategy` 现状（5 阶段 → 迁移裁定） | spec §8.1 必答项（第三轮会审扩项） | ✅ 必答 | 已核对（Task 6）：推荐折叠+裁剪，保留主线/混合/收口语义 |
| 6 | 判定口径逐实现（evolution / flow_nodes / daily_runtime / 蓝图） | spec §8.1 必答项、§3.2 | ✅ 必答 | 已完成（Task 7） |
| 7 | `CANONICAL_ERROR_TAGS` 双定义（auto_review.py / question_bank.py） | spec §7 架构取舍、§8.1 | — | 已完成（Task 8） |

**约定**：核对项 1–7 与下文「核对项记录」各节一一对应；每项完成后将"状态"改为「已核对」并回填结论；存在未决裁定点的，必须在"结论（或挂起原因）"中显式标注"挂起待 X"，不允许留空。

---

## 3. 裁定点模板

本记录的每个核对项都按同一模板记录，**每个裁定点必须给出「现状 / 冲突 / 选择 / 影响」四项，或明确"挂起待 X"**（对齐实现计划 Chunk 1 交付物定义）：

| 字段 | 必填 | 说明 |
|---|---|---|
| **现状（证据：文件:行）** | ✅ | 客观事实，必须带可复核的证据（文件路径 + 行号或 grep 命令）；只描述现状，不掺结论 |
| **裁定点** | ✅ | 本次必须回答的问题（一个或多个），注明来源（spec 章节 / 计划 Task） |
| **结论（或挂起原因）** | ✅ | 裁定结果：推荐方案 + 选择理由 + 影响清单；无法裁定的，写明"挂起待 X"及阻塞原因（X = 前置交付物 / 后续计划 / 等待会审等） |

**填写纪律**（骨架期即生效，后续 Task 填充时遵守）：

1. 现状只记录**已核实**事实；未核实的先 grep/读文件核实，不得凭印象填写。
2. 证据格式统一为 `文件路径:行号`（如 `learning_system/db.py:418`）；grep 类证据写明命令与命中数。
3. 结论必须是"选择 + 影响"二元结构；仅描述现状不算结论。
4. 所有"挂起待 X"的 X 必须具体（命名前置交付物或后续计划），禁止泛化"待讨论"。
5. 本记录只读：任何结论不得引发对代码/数据的修改（修改走对应实现计划）。

---

## 4. 核对项记录

### 核对项 1：长期状态表与消费方（attempts / learner_node_status / mastery_decisions）

> 对应 Task 2（实现计划 §Task 2）。目标：确认三张长期状态表能否满足「长期档案 append-only」需求。

#### 现状（证据：文件:行）

**`attempts`（`learning_system/db.py:418-452`）**

- 列（33 列，CREATE 列定义 `db.py:419-451`；另迁移补列 `clarifies_attempt_id`（`db.py:1310`）/`attempt_role`（`db.py:1311`），实测 live DB 35 列。**枚举不含迁移补列**）：`id`/`session_id`/`question_id`/`node_id`/`result`/`grading_status`/`evidence_status`/`score_points`/`max_points`/`error_tags_json`/`answer_raw`/`parent_note`/`evidence_note`/`answer_analysis_json`/`review_meta_json`/`cause_analysis_json`/`interaction_response_json`/`explanation_score`/`blocking_evidence`/`processed_evolution_event_id`/`flow_step_id`/`graph_version`/`question_bank_version`/`attempt_version`/`analysis_version`/`analysis_status`/`client_idempotency_key`/`answer_source`/`submission_request_digest_sha256`/`evidence_digest_sha256`/`attachment_ids_json`/`review_record_id`/`created_at`。
- FK 均 NOT NULL REFERENCES：`session_id` → `learning_sessions(id)`（`db.py:420`）、`question_id` → `question_items(id)`（`db.py:421`）、`node_id` → `graph_nodes(id)`（`db.py:422`）。
- `answer_source`：`text not null default 'legacy'`（`db.py:446`，迁移补列 `db.py:1305`）。无 DB 级 CHECK 约束，为应用层枚举：v3 流程在 `daily_runtime.py:1663-1670` 赋 `v3_stuck`/`v3_handwriting_confirmed`/`v3_voice_confirmed`/`v3_interaction`/`v3_photo`/`v3_text`；insert 后经 `update attempts set ... answer_source = ?` 补写（`daily_runtime.py:1858-1893`）。旧路径（`db.record_attempt`，`db.py:6809`）不传该列 → 留默认 `'legacy'`。
- 行生命周期：唯一插入点 `db.record_attempt`（insert 于 `db.py:6872`）；全库无 `delete from attempts`（`grep -rn "delete from attempts" learning_system/ --include="*.py"` 0 命中）；失效走 `evidence_status` 软状态 `{active, invalidated, stale}`（校验于 `db.py:6842`）。列级存在 in-place 富化：`answer_analysis_json` 回填（`db.py:7645`）、`analysis_version + 1`（`daily_runtime.py:4280`）、`cause_analysis_json`（`evolution.py:1279`）、`review_meta_json`（`server.py:2426`）、`evidence_digest_sha256`（`daily_runtime.py:1910`）——行不删，分析列后补。

**`learner_node_status`（`learning_system/db.py:534-549`）**

- 主键 `node_id`（`db.py:535`）→ 每节点一行**当前状态快照**（非日志表）。
- `status_revision integer not null default 1`（`db.py:547`，迁移补列 `db.py:1428`）：语义 = 状态快照的迭代修订号。v5 写路径经 `coalesce((select status_revision + 1 from learner_node_status where node_id = ?), 1)` 递增（`daily_runtime.py:13705`）；v2 写路径（`orchestrator.py:567-571`）不递增（insert or replace 不写该列 → 重置为 1）。前一修订号被抄入 `mastery_decisions.old_status_id`（`daily_runtime.py:13667`）。
- `evidence_attempt_ids_json`（`db.py:539`）= 支撑该状态的作答 id 列表（权威校验仍读它，`db.py:2932` 记为 legacy 语义）；`source_attempt_ids_json`（`db.py:544`）/`source_evidence_validation_ids_json`（`db.py:545`）= v5 写路径的源作答/证据校验 id（`daily_runtime.py:13664-13665`，与 `evidence_attempt_ids_json` 同值写入）。
- 行生命周期：`insert or replace` 覆盖式 upsert（`daily_runtime.py:13699`、`orchestrator.py:567`）；修复函数 `_repair_learner_node_status_invalid_refs` 可 DELETE 失效行（`db.py:2743-2823`，删除点 `db.py:2771/2792/2809/2817`）→ **非 append-only**。

**`mastery_decisions`（`learning_system/db.py:643-665`）**

- append-only 实测确认：全库 `grep -rn "update mastery_decisions\|delete from mastery_decisions" learning_system/ --include="*.py"` **0 命中**；唯一写入 = `db.record_mastery_decision` 的 `insert into`（`db.py:1925`，调用方 `orchestrator.py:695`）与 v5 路径的 `insert or ignore into`（`daily_runtime.py:13637`）。
- 幂等保障：唯一部分索引 `idx_v3_mastery_decisions_evidence_package` on `(node_id, graph_version, source_evidence_validation_hash, decision_version)`（`db.py:1490-1492`）。
- 关键字段：`old_status_id text`（`db.py:660`，实存前一 `status_revision` 编号的字符串，`daily_runtime.py:13667`——字段名易误读为外键）；`new_status_code text not null default ''`（`db.py:661`，值为 A/B/C/D，映射逻辑 `daily_runtime.py:13562-13599`）；`decision_version`（`db.py:659`，默认 1）；`applied`（`db.py:651`，插入时定值，v5 路径恒 1）；`source_evidence_validation_hash`（`db.py:663`）。
- 权威读路径：`authoritative_learner_node_status_rows`（`db.py:2876-2922`）join `learner_node_status` + `mastery_decisions` + `agent_runs`，校验 `md.applied = 1`、`md.new_status_code = s.status_code`、`evaluation_agent_run_id = updated_by_agent_run_id` 等一致性后才视为权威。

**消费方（`grep -rn "mastery_decisions\|learner_node_status" learning_system/ --include="*.py"`，74 处命中）**

- 写入方：`learner_node_status` → `orchestrator.py:567`（v2 insert or replace）、`daily_runtime.py:13699`（v5 insert or replace + 修订递增）、`db.py:2743-2823`（修复删除）；`mastery_decisions` → `db.py:1907/1925`（`record_mastery_decision`，调用 `orchestrator.py:695`）、`daily_runtime.py:13637`（insert or ignore）。
- 读取方（主要）：`db.py:2826`（`current_learner_node_status_rows`）、`db.py:2876`（`authoritative_learner_node_status_rows`）、`db.py:3067`（`current_learner_node_status_counts`）；`daily_runtime.py:335/891/1254`（authoritative 行）、`9560/11931/14576/14599`（状态读取）、`3827/5564/8835/12019/15113`（`mastery_decisions` 查询）；`planner.py:282/344/991/1042/1192/1309`（规划信号，`planner.py:344` 读 `evidence_attempt_ids_json` 取证据作答）；`evolution.py:1138/1290`（取前序状态）；`reports.py:155`（会话报告按 `session_id` 读 `mastery_decisions`）；`agents.py:348`、`knowledge_map.py:1061`、`server.py:463`（状态计数/图谱/面板）。

#### 裁定点

- 三张表是否满足"长期档案 append-only"需求（设计稿 §3.3：档案只增不改，状态变更留痕）？是否需新建 `node_mastery_log`？（对应实现计划 Task 2 Step 5）

#### 结论（或挂起原因）

**选择：满足，无需新建 `node_mastery_log`。**

- 长期档案由两张表分工承载：`attempts` 行级 append（只 insert、无 delete、`evidence_status` 软失效，分析列 in-place 回填不破坏痕迹）；`mastery_decisions` **严格 append-only**（只 insert、无 update/delete，唯一索引幂等），每次评估决策一条记录，含 `old_status_id`（前一修订号）/`new_status_code`（A/B/C/D）/`decision_version`/`source_evidence_validation_hash`/`applied` → **状态变更留痕（限定：v5 路径为结构化留痕；v2 路径可经自由文本字段 `decision`/`decision_payload_json` 重建，`db.py:646/653`）**。`learner_node_status` 只是"当前状态"派生快照（insert or replace + 修复删除，非 append），其历史在 v5 路径可由 `mastery_decisions` 结构化重建（`new_status_code`/`old_status_id`/`source_evidence_validation_hash`）、v2 路径可经自由文本字段（`decision`/`decision_payload_json`）重建。设计与实现一致（设计稿 `2026-08-20-child-learning-companion-design.md:153/368` 已声明同一结构，本次核对逐条证实）。
- 挂起项：无。

**影响：**

1. 无需新增表：M2.5 及后续周信如需"当周状态快照"，沿 `mastery_decisions.created_at` 过滤即可（按 session_id 先行定位：`idx_mastery_decisions_session` 仅 session_id 单列索引，`db.py:1243`，created_at 过滤仍需会话内扫描）。
2. 查询纪律：任何"历史/某时刻状态"必须走 `mastery_decisions`，不得依赖 `learner_node_status`（其行会被覆盖甚至删除，`db.py:2771/2792/2809/2817`）。
3. 注意偏差：`mastery_decisions.old_status_id` 存的是前一 `status_revision` 编号（`daily_runtime.py:13667`），非行 id，字段命名与语义不符，后续设计引用需注意。
4. `attempts` 的 append-only 是"行级"：`answer_analysis_json`/`cause_analysis_json`/`review_meta_json` 等列会被回填更新——与"档案只增不改"（设计稿 §3.3 第 4 条，`child-learning-companion-design.md:74`）兼容，但口径上"不改"指行不删除、作答痕迹保留。

---

### 核对项 2：短期计划表（generated_plans / daily_flows）

> 对应 Task 4（实现计划 §Task 4）。目标：确认短期计划结构能否承载"阶段数组可重排"。

#### 现状（证据：文件:行）

**`generated_plans`（`learning_system/db.py:572-579`）**

- 列（6 列）：`id` text PK、`title`、`tasks_json`（计划任务数组，JSON）、`planner_policy_version`（迁移补列 `db.py:1457`）、`plan_meta_json`（迁移补列 `db.py:1458`）、`created_at`。**无节点/阶段外键**——与节点的关系在 `tasks_json` 内容内部（每条 task 含 `node_id`/`question_id`/`task_type`/`planning_signal` 等，计划 dict 组装于 `planner.py:1461-1494`，每轮固定 10 个任务 `LEARNING_ROUND_TASK_COUNT=10`，`planner.py:15`）；**阶段概念不落表**（`planner.py` 全文无 `phase` 引用；表无 phase 列）。
- 写入：唯一写点 `planner.generate_next_plan` 的 `insert into`（`planner.py:1477-1497`，SQL 语句自 1477 行起）；`grep -rn "update generated_plans\|delete from generated_plans" learning_system/ scripts/` **0 命中** → **append-only 计划日志**，"推翻重来" = 生成新计划行。
- 读取：取"最新计划"用 `order by created_at desc, rowid desc limit 1`（`planner.py:1504`、`agents.py:14-37`，后者拼 `_latest_generated_plan_report` 供 agent 上下文）；`server.py:594-617`（按 id / 最新，面板展示）；`scripts/live_child_ui_10x.py:78`。`planner_policy_version` 不一致或题库版本过期 → 判为不可用（`agents.py:33-36`、`server.py:587-590`）。
- 与 `daily_flows` 的关系：`daily_flows.source_plan_id`（`db.py:1030`）声明关联，但 v3 创建路径**硬编码 null**（`daily_runtime.py:779`）；`grep -rn "source_plan_id" learning_system/ --include="*.py"` 仅 2 处（列定义 + insert null），无 join 读取 → **计划→日流程在 v3 运行时不经表关联**（经 planner 信号 → `next_step_decisions` → `flow_steps` 决策链）。

**`daily_flows`（`learning_system/db.py:1013-1035`）**

- 每日一行：`id` PK、`child_key`（默认 `'single-child'`）、`local_date`、`mode`（默认 `'not_selected'`）、`status`（默认 `'new'`；终态 `("completed", "superseded")`，`daily_runtime.py:42`）、`budget_min/max`、`current_step_id`、`graph_version`、`planned_graph_node_ids_json`（v3 插入恒 `'[]'`，`daily_runtime.py:779`，生产仅定义+写入、无读取）、题库版本三列（`question_bank_version`/`question_bank_ledger_id`/`question_bank_manifest_sha256`，后两列迁移补列 `db.py:1313-1314`）、`legacy_session_id` FK → `learning_sessions(id)`、`flow_revision`（行修订，状态迁移时 +1，`daily_runtime.py:725`）、`created_by_runtime_version`、`source_plan_id`（见上）、`blocked_reason`、`summary_id`、`created_at/updated_at`；迁移补列 `assessment_policy_version`（`db.py:1312`）。**无 phase 列**（阶段不落表）。
- 约束/索引：**部分唯一索引** `idx_v3_daily_flows_one_active_per_child_day` on `(child_key, local_date)` **带 WHERE 子句**（`db.py:1461-1465`：`where status in ('new','reviewing','ready_for_new_knowledge','learning_new','paused','blocked')`）→ 活跃状态每孩子每日至多一行；completed/superseded 终态行不占唯一位、可同日并存；`idx_v3_daily_flows_local_date_status`（`db.py:1464-1465`）。
- 写入/读取：创建 `_create_daily_flow`（`daily_runtime.py:755-799`）+ 状态机 in-place `update`（`daily_runtime.py:719/1115/2152/2242/2277/2355/2416/2482/2649/3402` 等，`flow_revision` 递增防并发覆盖）；读取 `daily_runtime.py:4680/4854/4888/4899`、`reports._latest_daily_flows`（`reports.py:107-111`）、`knowledge_map.py:315/381`、`assessment_store.py:394`、`server.py`。
- 日内步骤序列 = `flow_steps`（`db.py:1037-1062`）：`flow_id` FK（on delete cascade）、`position` 整数（`db.py:1041`）、`step_handle`/`step_type`/`status`、`node_id`/`question_id`、`step_revision`、`superseded_by_step_id`（`db.py:1059`，步骤可被取代）；生产代码（`learning_system/` + `scripts/`）范围内 `insert into flow_steps` 仅 `daily_runtime.py:13055/14283` 两处（运行时按 next_step_decisions/教学修复选步落库），**不从 `generated_plans.tasks_json` 物化** → 日内顺序由 `position` 承载、可演进替换（`superseded_by_step_id` + `flow_revision`）。

**`learning_path` 现状（`data/knowledge_graphs/math/math_knowledge_graph_v2.json` 顶层 key，规划配置 dict 非档案）**

- 结构（实测 json 解析）：dict，含 `daily_time_minutes`（60）、`math_priority`（文本）、`phase_strategy`（**5 元素数组**：第1-3天建档 / 第4-12天快补 / 第13-35天主线 / 第36-44天混合 / 第45-50天收口，每元素 `name`/`goal`/`phase`，其中 `phase` 是"第X-Y天"日期段标签）、`session_template`（每日 5 活动模板：旧错题复测 5min / 讲知识点本质模型 15min / 3-5 道变式 25min / 错因归类回退 10min / 记明天复测点 5min）。
- **零代码消费**：`grep -rn "phase_strategy\|learning_path\|session_template" learning_system/ scripts/ --include="*.py"` **0 命中**；图谱唯一装载方 `seed_from_assets`（`db.py:3308 起`）只读 `metadata`/`nodes`/`edges` 等，不读 `learning_path`（测试中 `learning_path_order` 指 view config 的 `module_order`，`knowledge_map.py:100`，与 JSON `learning_path` 无关）→ **纯规划配置文档，改结构零运行时耦合**。

#### 裁定点

- 短期计划现状是否满足"阶段数组可重排"（设计稿 §3.3 第 4 条"计划可重排"，`child-learning-companion-design.md:74/161`）？`learning_path` 现状与阶段数组改造（先落 2 阶段：暑假衔接收口 + 开学首月）的关系？（对应实现计划 Task 4 Step 3；预期结论：结构兼容，改造留到阶段数组计划）

#### 结论（或挂起原因）

**选择：结构兼容——阶段是配置层概念、不落执行表；`learning_path` 零代码消费，阶段数组改造只动 JSON 配置，留到阶段数组计划执行；`generated_plans`/`daily_flows`/`flow_steps` 三表无需改动。**

- "计划可重排"已由现有结构承载：`generated_plans` 是 append-only 计划日志，最新计划按 `created_at desc, rowid desc limit 1` 重取（`planner.py:1504`），"推翻重来" = 生成新计划行（`planner.py:1477`），无对既有计划的 in-place 重排更新路径（生产 grep 0 命中）；日内步骤顺序由 `flow_steps.position`（`db.py:1041`）+ `superseded_by_step_id`/`flow_revision`（`db.py:1059`）承载，可演进替换。
- 阶段不落表：`generated_plans`/`daily_flows`/`flow_steps` 均无 phase 列（db.py 中 `phase` 仅出现在 `agent_runs`/`agent_handoffs`/`session_steps`，`db.py:587/620/636`，是 LLM agent 执行阶段，非学习阶段）；`learning_path.phase_strategy` 已是数组（5 元素，元素顺序即阶段顺序），重排 = 改配置数组顺序 → 与设计稿 §3.3「`learning_path` 改阶段数组、先落 2 阶段」（`child-learning-companion-design.md:161`）**结构兼容**。
- 零耦合依据：`learning_path` 无任何 Python 消费方（grep 0 命中，见现状）→ 阶段数组改造（替换/裁剪元素、`phase` 字段从"第X-Y天"日期段标签改为阶段标识）无运行时联动，与实现计划「阶段数组改造 → 后续计划，避免 digest 联动 churn」的前提一致（`2026-08-20-semester-data-link-prereqs.md:12-13`）。

**影响：**

1. 阶段数组计划（后续计划）只改 `math_knowledge_graph_v2.json` 的 `learning_path`，不动 `db.py` 三表 schema；旧 5 阶段去留（建档/快补与新窗口冲突）属核对项 5（Task 6）裁定，本项不重复裁定。
2. 注意偏差：`daily_flows.source_plan_id` 是**声明未用的死链接**（生产恒 null、无 join 读取）；阶段数组计划若需"计划→日流程"表关联，须另行设计——v3 现经 planner 信号 → `next_step_decisions` → `flow_steps` 决策链，不经 `generated_plans`。
3. 阶段数组若要驱动执行（如"阶段 → daily_runtime mode"映射），须在阶段数组计划中显式定义——现 `learning_path` 不被 `daily_runtime` 消费，阶段不驱动任何运行时行为。
4. 挂起项：无——本核对项只录现状与兼容性裁定；实际改造执行 = 后续「阶段数组计划」（`2026-08-20-semester-data-link-prereqs.md:12-13`）。

---

### 核对项 3：已裁定新增表（新增 vs 别名）

> 对应 Task 3（实现计划 §Task 3）。**spec §8.1 必答项首项**：`error_cause_log` / `weekly_summary` / 「作业全对」确认载体 → 三者「新增 vs 别名」裁定。

#### 现状（证据：文件:行）

**`error_cause_log`（错因三年分布）**

- 无现成表/列：`grep -rn "error_cause\|wrong_cause" learning_system/db.py` **0 命中**，全 `learning_system/`（`--include="*.py"`，含 learning_system/ 内其余 py 文件）亦 0 命中；db.py 模式脚本（`db.py:295` 起 `conn.executescript`，共 **43 张** `create table if not exists`）无相关表。实测 `data/learning.db` 为空库（0 表），现状以 db.py 模式脚本为准。
- 现有错因载体均为**单次作答粒度，无跨期聚合语义**：
  - `attempts.error_tags_json`（`db.py:428`）：单次作答的规范化错因标签数组——批改路径规范化写入（`daily_runtime.py:9251-9276` `_canonical_error_tags_for_answer_output`：限 `CANONICAL_ERROR_TAGS`、≤4 个、正确→空、兜底 `general`）；两处写入：insert（`db.py:6874`）与批改 update（`db.py:7535`）→ **会被 in-place 回填，非不可变归档**。
  - `attempts.cause_analysis_json`（`db.py:434`，迁移补列 `db.py:1294`）：单次作答的 LLM 错因分析文本，唯一写点 `evolution.py:1279`。
  - 现有标签聚合仅限**诊断窗口内**：`evolution.py:878/1128` 在单节点诊断上下文中按 node 聚合 `error_tags`；全库无跨期（周/月/三年）错因分布表或物化聚合。
- 信任边界缺口：批改侧只有**整体** confidence（`auto_review.py:96/115/132`，`MIN_CONFIDENCE_TO_GRADE=0.68`，低置信 → `status="low_confidence"` 保留为待分析证据）；`attempts` 无「标签级置信 / 待爸爸确认 / 规则命中」状态 → 设计稿 §3.2 信任边界（低置信不计入分布、爸爸确认或规则命中才计入，`child-learning-companion-design.md:146-149`）**现有载体无法表达**。
- 消费方：设计稿 §3.2（信任边界 → 错因分布 → 周信/简报/教学决策）、§6.1 周信错因模式一句话（`child-learning-companion-design.md:283`）、§6.2 学期报告错因分布（`child-learning-companion-design.md:295`）——设计已裁定**硬依赖、非可选**（`child-learning-companion-design.md:157`）；代码消费方（周信/简报生成）属 M4/M5 未实现，无现有表可服务该语义。

**`weekly_summary`（周信存档）**

- 无现成表：`grep -rn "weekly" learning_system/ --include="*.py"` **0 命中**（`weekly_summary` 仅出现在设计稿/实现计划/本记录等文档）；43 张表清单无周粒度表。
- 最近似现有存档 = `daily_summaries`（`db.py:1182-1201`）：**按 `daily_flows` 行**的运行时内部 digest——`flow_id + flow_revision + summary_version` 唯一索引（`db.py:1495-1496`），`_ensure_daily_summary` 自动生成（`daily_runtime.py:15086`），存 `touched_node_ids_json`/`source_attempt_ids_json` 等源引用集合 + `report_label_json`/`child_summary_json`/`operator_summary_json`（`db.py:1188-1199`）；读方 `reports.py:161`（日报告）、`daily_runtime.py:4689`。**粒度 = 单 flow（日级）、内容 = 源 id 引用集合**：无当周 A/B/C/D 时间快照、无爸爸确认状态枚举、无周粒度 → 不构成周信存档别名。
- 设计要求（设计稿 §3.3，`child-learning-companion-design.md:158`）：长期档案 **append-only**、存**当周 A/B/C/D 时间快照**、爸爸确认状态枚举 `acknowledged`/`unacknowledged`；§6.1 降级路径依赖 `weekly_summary.status='unacknowledged'`（`child-learning-companion-design.md:290`：未确认 → 存档不丢、可补看）。
- 消费方：§6.1 周信生成（P1，M4）——素材可聚合自 `daily_summaries`/`attempts`/`mastery_decisions`，但「当周快照 + 确认状态 + 存档」语义无现成表承载。

**「作业全对」确认载体**

- 无现成载体：`grep -rni "全对\|all_correct\|homework\|daily_confirm" learning_system/ --include="*.py"` **0 命中**；43 张表无相关表/列。
- 最近似候选 = `evidence_confirmations`（`db.py:496-507`）：**媒体识别确认**——`attempt_id` + `recognition_run_id` + `confirmed_text` + `confirmation_digest_sha256`，唯一 `(attempt_id, confirmation_version)`（`db.py:506`）。语义是「手写/拍照识别文本的人工纠正确认」，非「作业全对」每日一按的证据范围标注（后者不绑定 recognition_run、不进判定样本）→ **非别名**。
- 设计要求（设计稿 §3.1，`child-learning-companion-design.md:131`）：每日一键，**只作证据范围标注、不进判定样本**；周信/双周简报**必须标注证据范围**——仅系统内 / 含手动补录 / 含全对确认，三分类与 §6.1（`child-learning-companion-design.md:283`）一致。
- 消费方：周信/双周简报的证据范围标注（P1/P2，M4/M5）；**mastery 判定不消费**（不进判定样本）。

#### 裁定点

- 三者各是「新增表 / 新增字段 / 现有表别名」？（对应实现计划 Task 3 Step 4；spec §8.1 必答项首项）
- 若为新增：给出最小 schema 草案（列清单，细节留 M4 计划）。

#### 结论（或挂起原因）

**选择：三者均为「真新增」，非现有表别名**——逐项裁定：

1. **`error_cause_log` = 真新增**：`attempts.error_tags_json`/`cause_analysis_json` 是单次作答粒度、会被 in-place 回填（`db.py:7535`）、无跨期聚合语义、无信任边界状态（§3.2 低置信不计入分布），不能别名覆盖「三年错因分布」；消费方（§3.2/§6.1/§6.2）已硬依赖（`child-learning-companion-design.md:157`）。~~挂起一项~~：`attempt_id` 关联方式已由核对项 4（Task 5）裁定——系统内作答走 `attempt_id` 直接 FK `attempts(id)`；手动错题经新增侧表 `manual_error_entries` 反链（`error_cause_log` 增加可空 `manual_entry_id`），见核对项 4 结论影响清单第 3 条。此项只影响关联列设计，不改变「真新增」裁定。
2. **`weekly_summary` = 真新增**：`daily_summaries` 是日级 flow 运行时 digest（`db.py:1182`），无周粒度 / 当周快照 / 确认状态，不能别名；§6.1 降级路径 `status='unacknowledged'`（`child-learning-companion-design.md:290`）无现成列承载。
3. **「作业全对」确认载体 = 真新增**：`evidence_confirmations` 是识别纠正确认（`db.py:496`），语义不符；需轻量证据范围标注载体（不进判定样本）。

**最小 schema 草案（列清单，细节留 M4 计划）：**

- **`error_cause_log`**（错因三年分布，append-only）：`id` text PK；`attempt_id` text（系统内作答 → FK `attempts(id)`，仅系统内源非空）；`manual_entry_id` text NULL（手动错题 → 引用侧表 `manual_error_entries`，经核对项 4 裁定；系统内/手动二选一）；`node_id` text REFERENCES `graph_nodes(id)`；`error_tag` text（枚举 `CANONICAL_ERROR_TAGS`，**一行一标签**，利于 group by 分布）；`source` text（`system_auto`/`manual_entry`）；`confidence` real（模型自评）；`trust_status` text（`counted`/`pending_parent`/`rule_hit`，§3.2 信任边界三态，低置信不计入分布）；`parent_confirmed_at` text NULL；`graph_version` text；`created_at` text。约束：只 insert；唯一索引 (source 引用, error_tag) 幂等（source 引用列名细节留 M4 明确）；分布索引 (error_tag, created_at)。
- **`weekly_summary`**（周信存档，append-only）：`id` text PK；`iso_week` text（如 `2026-W34`，周唯一）；`status` text（`acknowledged`/`unacknowledged`，§6.1 降级依赖；行内容 append-only，确认状态变更允许 in-place 更新或另建确认留痕表——细节留 M4）；`node_status_snapshot_json` text（当周 A/B/C/D 时间快照）；`coverage_json` text（本周覆盖节点/素材引用，聚合自 `daily_summaries`/`attempts`）；`error_distribution_json` text（错因模式素材，聚合自 `error_cause_log`）；`evidence_scope` text（`system_only`/`with_manual`/`with_all_correct`，§6.1 三分类）；`narrative_json` text（LLM 叙述或降级模板标记）；`generated_at` text；`acknowledged_at` text NULL。约束：`iso_week` 唯一索引，每周一条。
- **「作业全对」确认载体**（建议命名 `daily_all_correct_confirmations`，最轻量）：`id` text PK；`confirm_date` text（每日一键，日唯一）；`confirmed_by` text（归属人设计稿未定：孩子或爸爸 → **挂起待爸爸拍板**，时限 M4 启动前，对齐设计稿 §10 #1 时限）；`evidence_scope_mark` text（标记本日证据范围分类）；`source_refs_json` text（当日作业关联引用，可空）；`created_at` text。约束：`confirm_date` 唯一；只 insert；**mastery 判定不得读取本表**（不进判定样本）。

**影响：**

1. M4 数据模型改动清单确定：需新建 3 张表（设计稿 §8.2 第 3 条「已裁定新增表」落地，`child-learning-companion-design.md:334`），与 §7「做（数据模型）④」一致（`child-learning-companion-design.md:309`）。
2. 别名裁定依据可复核：本结论的「无现成表」均经 grep/读代码实测（见现状证据），防止把既有表误判为新增；`daily_summaries`/`evidence_confirmations` 已显式排除为别名并记录理由。
3. 两个挂起项显式化且不阻塞裁定：`error_cause_log.attempt_id` 关联方式 → 已由 Task 5 裁定（见核对项 4）；全对确认归属人 → 挂起待爸爸拍板（M4 启动前）。
4. 错因标签枚举随 Task 8 收口演进：`error_cause_log.error_tag` 依赖单一 `CANONICAL_ERROR_TAGS` 导入源（Task 8 收口为后续计划项），防三年错因分布漂移。
5. 查询纪律：周信/简报素材可聚合 `daily_summaries` 等现有表，但「当周快照 / 确认状态 / 证据范围」语义只能读三张新表；全对确认表仅供证据范围标注，不得进入判定口径。

---

### 核对项 4：attempts FK 三方案影响

> 对应 Task 5（实现计划 §Task 5）。**spec §8.1 必答项**：`attempts.question_id`/`session_id` NOT NULL，评估「可空化 / 占位 / 旁挂侧表」三方案联动影响。

#### 现状（证据：文件:行）

**FK 定义与唯一写入点**

- `attempts.session_id`/`question_id`/`node_id` 均 NOT NULL REFERENCES（`learning_system/db.py:420-422`）；全库唯一插入点 `db.record_attempt`（`db.py:6809`，insert 于 `db.py:6870-6902`）**强制 question/session 语义**：`question = get_question(conn, question_id)` 且校验 `question.node_id == node_id`（`db.py:6844-6846`）、`child_learning_group` 会话校验题归属（`db.py:6851-6855`）、active 证据要求题为"评审通过可调度"（`db.py:6856-6866`）——手动错题（无题库题）走该入口必然被拒。

**FK 依赖清单（grep 实测）**

`grep -rn "join question_items\|join attempts\|references question_items\|references learning_sessions" learning_system/ --include="*.py"` → **48 命中** = **9 处 schema FK 定义**（`db.py:351/420/421/472/701/743/846/959/1027`）+ **39 处运行时 JOIN 行**；另补充 grep（`join learning_sessions`）发现 **1 处** `db.py:1740`；另有 **5 处非 SQL 直接解引用** `get_question(conn, attempt["question_id"])`（`db.py:6459`、`server.py:2366`、`flow_nodes.py:113`、`evolution.py:763/820`）。逐条语义分组如下（**方案① 可空化后 INNER JOIN 遇 NULL `question_id`/`session_id` 时行被静默过滤，或直接解引用崩溃**）：

**A 组：`attempts.question_id` INNER JOIN `question_items`（13 处）——可空化后手动错题行全部被静默过滤**

| 位置 | 语义 | 可空化影响 |
|---|---|---|
| `agents.py:60` | `_active_current_attempt_count`：按当前版本过滤统计 active 作答数（`CURRENT_ATTEMPT_VERSION_FILTER`，`agents.py:40-46`） | 手动错题不计入（碰巧符合"不进判定样本"，但属隐式过滤） |
| `planner.py:357/382` | `_latest_planning_signal`：取 `evidence_attempt_ids_json` 证据作答与按节点兜底作答（版本过滤同上） | 手动错题不进规划信号 |
| `db.py:2335` | `_valid_status_attempts_for_ids`：learner_node_status 权威证据校验 | 手动错题不会成为状态证据 |
| `db.py:2461/2499/2712/3164` | 修复扫描：超版本题作答 / 节点不匹配 / 失效源题作答 | 手动错题不被扫描（不被误修，也不被保护） |
| `db.py:6539` | `current_attempts` 读取 | 手动错题不出现 |
| `db.py:7658/7685` | `pending_attempts`/`recent_attempts`：join `q.prompt/expected_answer` 取题面 | 手动错题无题面可 join，静默消失（批改队列/最近作答看不到） |
| `daily_runtime.py:7636/14623` | 强项画像 / core 证据检查：join `q.kind/raw_json` | 手动错题被过滤 |

**B 组：`attempts.session_id` INNER JOIN `learning_sessions`（1 处，补充 grep）**

| 位置 | 语义 | 可空化影响 |
|---|---|---|
| `db.py:1740` | `pending_background_session_ids`：查 `pending_review` 且 `mode='child_learning_group'` 未关闭会话 | NULL `session_id` 被过滤 → 手动错题永远不触发会话级待批处理（隐式安全但脆弱） |

**C 组：`attempts.id` 驱动（6 处）——不受可空化直接影响，但依赖"attempt 必有真实题"才能走评估链**

| 位置 | 语义 |
|---|---|
| `daily_runtime.py:7635` | `flow_steps → attempts`：取当前 flow 步骤作答（配 A 组 7636 取题面） |
| `daily_runtime.py:9487/13766`、`db.py:2993` | `evidence_validations → attempts`：评估证据链读取（手动错题无 evidence_validations） |
| `server.py:1226` | `background_jobs → attempts`：stuck 中断任务回查 flow_step |
| `question_bank.py:4407` | 定向支持路由收据校验：要求 `attempt.question_id = assessment.question_id`（`question_bank.py:4422`） |

**D 组：LEFT JOIN（3 处）——NULL 安全，是"可空化后其余查询应改成的形态"**

| 位置 | 语义 |
|---|---|
| `reports.py:129` | 报告按 flow 取作答 + 题面（`question_prompt` 可空）——全库唯一现成的"attempts 题面 LEFT JOIN"范例 |
| `db.py:2643` | `question_items LEFT JOIN attempts`（反方向，evolved 题源作答归一化） |
| `daily_runtime.py:9488` | `evidence_validations LEFT JOIN question_items on ev.question_id` |

**E 组：非 attempts 的 `question_items` join（14 处）——证明"题面-契约-评估"管线全链 NOT NULL，不直接受 attempts 可空化影响**

| 位置 | 语义 |
|---|---|
| `daily_runtime.py:12506/12547/12667` | `flow_steps.question_id → question_items`：flow 步骤题面读取 |
| `daily_runtime.py:13768` | `evidence_validations.question_id`（评估链） |
| `daily_runtime.py:14379` | `question_usage_policies → question_items`（支持策略题） |
| `assessment_store.py:164/214`、`knowledge_map.py:491/701` | `answer_contracts → question_items`（答案契约必须绑定真实题，`answer_contracts.question_id NOT NULL` `db.py:743`） |
| `db.py:2367/2575/3145`、`agents.py:686`、`answer_contract_batch_v2.py:1191` | `question_review_records → question_items`（评审记录） |

**F 组：非 SQL 直接解引用（5 处）——NULL 时抛 KeyError 或判失效**

| 位置 | 语义 |
|---|---|
| `db.py:6459` | `is_current_attempt_question`：`get_question` KeyError → False（手动错题恒"非当前题"） |
| `server.py:2366` | pending_review 批改 job 入队：`get_question` **无 try 保护** → NULL `question_id` 直接崩溃 |
| `flow_nodes.py:113` | mastery 诊断取题面（`_question_for_attempt`，**无 try 保护** → NULL `question_id` 崩溃） |
| `evolution.py:763` | `_attempt_question_source_invalidated`：`get_question` KeyError → True 判失效 |
| `evolution.py:820` | `_base_question` 取题面：**无 try 保护** → NULL `question_id` 崩溃 |

- **排除声明（不计入上述分组）**：另有 3 处 `question_items` LEFT JOIN 由 `graph_nodes`（`node_id`）驱动，与 `attempts` FK 无关、不受可空化影响、不计入 A–F 分组——`server.py:480`、`agents.py:210`、`reports.py:338`（均为 `from graph_nodes n left join question_items q on q.node_id = n.id` 形态）。

**联动索引（`db.py:1475-1480`）**

- `idx_v3_attempts_one_active_per_step` on `attempts(flow_step_id) where flow_step_id is not null and evidence_status = 'active'`（`db.py:1475-1477`）与 `idx_v3_attempts_submit_idempotency` on `(flow_step_id, client_idempotency_key) where flow_step_id is not null`（`db.py:1478-1480`）**均挂在 `flow_step_id` 上、与 `question_id` 无关** → 可空化 `question_id` 不破坏这两个索引本身；但手动错题**无 flow_step_id** → 不进入这两个唯一索引 → "一步一活跃作答 / 提交幂等"的唯一性约束对手动错题全部失效，需另设去重/幂等键（如 `(node_id, error_tag, confirm_date)`），否则重复录入无任何约束。
- 迁移成本：SQLite `ALTER TABLE` 无法去除 NOT NULL 约束；现有迁移脚手架 `_ensure_column`（`db.py:3302`，用法 `db.py:1278-1330`）只支持加列 → 方案① 需新增**全表重建**迁移（12 步 create-copy-drop-rename），且须与 `create table if not exists` 模式脚本（`db.py:295` 起）保持同步，43 张表里凡引用 `attempts` 的消费侧均受影响。

#### 裁定点

- 方案① 可空化 `question_id`/`session_id`：对照依赖清单列受影响 join/索引（含 `idx_v3_attempts_one_active_per_step` `db.py:1475`）；
- 方案② 合成占位 question/session：评估对 `question_items` 统计与 `learning_sessions` 的污染；
- 方案③ 旁挂侧表（如 `manual_error_entries`）再反链 `attempts`：评估与现有证据链的一致性；
- 给出**推荐方案 + 影响清单**（此结论直接决定 M4 错题录入的 schema 改动，并解除核对项 3 的挂起项 1）。

#### 结论（或挂起原因）

**选择：方案③（旁挂侧表再反链 attempts）为推荐方案。** 三方案评估：

**方案①（可空化 `question_id`/`session_id`）——否决。** 理由：

1. **消费链断裂**：判定/评估管线全链 NOT NULL——`attempt_assessments.question_id`（`db.py:959`）、`answer_contracts.question_id`（`db.py:743`）、`evidence_validations` 链均要求真实题。可空化后手动错题行"插得进、消费不了"：A 组 13 处 + B 组 1 处 INNER JOIN 静默过滤（批改队列 `db.py:7658`、最近作答 `db.py:7685`、报告视图 `reports.py:129` 形态之外全部看不到），F 组 5 处直接解引用中 **3 处无保护会崩溃**（`server.py:2366`、`flow_nodes.py:113`、`evolution.py:820`）、**2 处判失效**（`db.py:6459`、`evolution.py:763`：KeyError → False/True）。"复用 attempts"字面成立，但没有任何消费方读得到它。
2. **改造面 = 全部 A/B/F 组（14 处 INNER JOIN + 5 处直接调用）**：需逐条改为 LEFT JOIN/条件过滤（现仅 D 组 3 处 LEFT，`reports.py:129` 是唯一范例），回归面大、风险高。
3. **迁移成本高**：SQLite 无法 ALTER 去 NOT NULL，需全表重建迁移（见现状索引段）。
4. **信任边界错位**：§3.2 要求手动/低置信证据**不计入判定样本**（`child-learning-companion-design.md:146-149`）；可空化把手动错题放进 `attempts`，目前靠 INNER JOIN 偶发过滤，语义脆弱——任何一处改成 LEFT JOIN 或按 `node_id` 聚合（如 `reports.py:129` 形态）都会让手动错题混入统计。
5. **索引联动**：两个 attempts 唯一索引（`db.py:1475-1480`）挂在 `flow_step_id` 上，手动错题无 `flow_step_id` → 无唯一性/幂等保护（见现状索引段）。

**方案②（合成占位 question/session）——否决。** 理由：

1. **判定污染**（比统计污染更严重）：占位题若 `source_type` 用 `'graph_generated'/'evolved'` 之外的值，虽可绕过 ledger 的 `item_count` 对账（`daily_runtime.py:177-214` 只数 `graph_generated`），但 `CURRENT_ATTEMPT_VERSION_FILTER`（`agents.py:40-46`）对 `source_type not in ('graph_generated','evolved')` **恒真** → 占位题"永不超版本" → 手动 attempts 会被 `_active_current_attempt_count`（`agents.py:49`）、`planner.py:357/382`、`_valid_status_attempts_for_ids`（`db.py:2327-2355`）当成**当前有效证据计入判定样本与规划信号**，直接绕过 §3.2 信任边界。
2. **`question_items` 统计污染**：占位题混入题面库，任何按 `question_items` 的计数/对账/展示（ledger `item_count` 对账 `daily_runtime.py:177-214`、`knowledge_map.py:491/701` 激活集合校验 `item_count` 一致性）都需要排除逻辑。
3. **`learning_sessions` 污染**：占位会话混入会话列表（`server.py:686/704/729/747`）与 `pending_background_session_ids`（`db.py:1731-1748`）等按会话查询。
4. **假数据永久化**：`attempts.question_id` 引用**无 on delete cascade**（`db.py:421`）→ 占位题一旦被引用即无法删除；`question_usage_policies` 等 cascade 链（`db.py:351`）扩大残留面；且占位题仍需 `answer_contracts`（`db.py:743`）等契约表支撑才能走评估——为一条假数据伪造整条生产管线。

**方案③（旁挂侧表再反链 attempts）——推荐。** 理由：

1. **证据链零改动**：`attempts` 表结构（`db.py:418-452`）与判定证据链（`attempts → attempt_assessments → evidence_validations → learner_node_status/mastery_decisions`）**完全不动**——A/B/C/E 组全部 34 处运行时 join 语义不变，无 NULL、无占位、无迁移。
2. **手动错题权威载体 = 新建侧表 `manual_error_entries`**：`node_id` FK、`error_tag`（枚举对齐 `CANONICAL_ERROR_TAGS`）、孩子自报对错、爸爸确认、`trust_status`（§3.2 三态：`counted`/`pending_parent`/`rule_hit`）、附件引用、`created_at`——字段与核对项 3 已裁定的 `error_cause_log` 草案同构；`attempts`（`db.py:418-452`）无信任状态列可复用，侧表正好补上 §3.2 信任边界。
3. **"再反链 attempts"**：侧表加可空列 `review_attempt_id text references attempts(id)`（方向：侧表 → 回查题 attempts 行；attempts 侧可选加反向可空列 `manual_error_entry_id`，留 M4 定）。手动错题被选为"回查 2-3 道针对性题"（§3.1）的来源后，回查作答是**正常 attempts 行**（真实 `question_id`/`session_id`，正常进判定管线），反链保证"错题 → 回查 → 判定"证据链完整可追溯。
4. **设计修正（本项裁定对设计稿 §3.1 字面意图的修正）**：「手动录入复用 `attempts`（`answer_source='parent_manual'`）」改为「手动错题**不写 attempts 行**，`attempts` 语义保持『系统内真实作答』」——理由 = FK 现实（无题库题/无会话）+ §3.2 信任边界（手动/低置信证据不进判定样本）+ 消费链断裂（方案①②均不可行，见上）。`answer_source='parent_manual'` 枚举值保留定义，实际落位（侧表 `source` 或 `error_cause_log.source='manual_entry'`）留 M4。
5. **解除核对项 3 挂起项 1**：`error_cause_log.attempt_id` 关联方式裁定为——系统内作答 → 直接 FK `attempts(id)`；手动错题 → `error_cause_log` 增加可空 `manual_entry_id` 引用 `manual_error_entries`（错因分布仍一行一标签，`source` 区分 `system_auto`/`manual_entry`）。

**影响清单（M4 错题录入 schema 改动，直接由本项结论决定）：**

1. 新建 `manual_error_entries` 侧表（列清单见方案③评估，细节留 M4）；`attempts` 表结构**不动**（NOT NULL 保留、无迁移、20+ 处 join 零改动）。
2. 可选反链列：`manual_error_entries.review_attempt_id`（侧表反链回查 attempts）或 `attempts.manual_error_entry_id`（`_ensure_column` 可加）——留 M4 定。
3. `error_cause_log`（核对项 3 已裁定新增）增加可空 `manual_entry_id` 引用侧表；系统内作答仍走 `attempt_id` FK。
4. 错题录入 UI 写侧表（**不走 `record_attempt`**，`db.py:6809` 校验链对手动录入不适用）；回查题出题/作答仍走现有 attempts 链路。
5. 查询纪律：手动错题进 `error_cause_log` 分布与 `weekly_summary` 证据范围标注（含手动补录/全对确认三分类，§6.1），**不得**进 mastery 判定样本；attempts 相关 20+ 处 join 全部维持现状。

**挂起项（不阻塞本裁定）：**

1. 手动证据入档规则（手动错题如何触发 C/D 下探与复测、`explanation_score` 缺失时如何入档、是否计入样本）→ **挂起待 `mastery_criteria_proposal`**（设计稿 §3.1/§8.1 已标注归 M2.5，`child-learning-companion-design.md:130/144/327`）——侧表先行，规则后落。
2. 错题录入归属人（默认孩子最小表单）→ **挂起待爸爸拍板**（M4 启动前，§3.1/§10 #1，`child-learning-companion-design.md:128/389`）。

---

### 核对项 5：phase_strategy 现状与迁移裁定

> 对应 Task 6（实现计划 §Task 6）。**spec §8.1 必答项（第三轮会审扩项）**：现网 `learning_path.phase_strategy` 已是 5 阶段数组，裁定旧阶段去留。

#### 现状（证据：文件:行）

**现网 5 阶段原文（`data/knowledge_graphs/math/math_knowledge_graph_v2.json:8632-8658`，`learning_path.phase_strategy` 数组，5 元素逐字记录）**

| # | `name` | `goal` | `phase`（日期段标签） | JSON 行 |
|---|---|---|---|---|
| 1 | 数学诊断与建档 | 完成图谱诊断，给节点打A/B/C/D状态。 | 第1-3天 | 8633-8637 |
| 2 | 小学前置快补 | 只补P0薄弱前置：分数、小数、混合运算、等量关系、方程、应用题审题。 | 第4-12天 | 8638-8642 |
| 3 | 七上主线预学 | 有理数→代数式→整式→方程，几何穿插。 | 第13-35天 | 8643-8647 |
| 4 | 混合迁移 | 七上主线混合题 + 方程应用题 + 易错回炉。 | 第36-44天 | 8648-8652 |
| 5 | 开学前收口 | 两次综合检测，形成开学首月跟踪清单。 | 第45-50天 | 8653-8657 |

- 元素结构：每元素含 `name`/`goal`/`phase` 三字段，其中 `phase` 是"第X-Y天"**日历段标签**（非语义阶段标识）；5 段合计覆盖第 1–50 天，数组元素顺序即执行顺序（核对项 2 已记录）。
- **零代码消费（引用核对项 2 / Task 4 结论，不重复实测）**：`grep -rn "phase_strategy\|learning_path\|session_template" learning_system/ scripts/ --include="*.py"` **0 命中**（见核对项 2 现状）；图谱唯一装载方 `seed_from_assets`（`learning_system/db.py:3308 起`）不读 `learning_path` → 纯规划配置，改结构零运行时耦合。
- **与新设计冲突（Step 2 核对）**：
  - **建档（第1-3天）** vs 执行窗口：设计稿本稿日期 2026-08-20、距 2026-08-24 开学仅 4 天，假期活动（诊断建档、Tier 二轮复核）"挂下一假期或压缩执行"（`2026-08-20-child-learning-companion-design.md:77`）；Tier S 建档依赖 Tier 二轮复核前置、当前窗口无法执行（`:192/328`）；且建档在设计中是"假期头 1-3 天**单独时段**（不占日模板）"的子活动（`:109/190`），非独立阶段 → 与"第1-3天建档"作为独立阶段的配置冲突。
  - **快补（第4-12天）** vs §4.3：80 分孩子**不做预防性补差**（`:188`）——只做 Tier S 前置建档，其余小学前置"不做预防性诊断，等七上错题回查时按需触发"（`:190-191`）；小学前置+桥梁 24 节点整体重定义为**回查用前置层**："不再主动教，只在七上错题回查时按需诊断"（§4.2，`:182`）→ 与"第4-12天小学前置快补"预防性补差阶段直接冲突。
  - **整体 50 天窗口** vs 新执行窗口：5 段合计第 1–50 天日历锚定，距开学仅 4 天 → 整条日期段标签失效；主线/混合/收口（第 13–50 天）无法按原日历执行，时序冲突按 §8.1 处理（`:77/325`）。

#### 裁定点

- 旧 5 阶段去留三选项：**折叠进「暑假衔接收口」** / **裁剪建档与快补两段** / **保留为历史快照**——逐一评估代价并给出推荐（spec §8.1 第三轮会审扩项，`2026-08-20-child-learning-companion-design.md:325`；对应实现计划 Task 6 Step 3，预期推荐：折叠 + 裁剪，保留主线/混合/收口语义）；并标注"最终裁定随阶段数组计划执行"（本核对项是裁定建议，不是落地）。

#### 结论（或挂起原因）

**选择：组合裁定——「折叠 + 裁剪」：建档折叠进「暑假衔接收口」、快补按 §4.3 裁剪，两段均不再作为独立阶段；保留主线/混合/收口三段语义（重组进新阶段数组）。三选项逐一评估：**

1. **选项① 折叠进「暑假衔接收口」——采纳（对建档段）**。理由：建档本就不是独立阶段——设计稿定义其为"假期头 1-3 天单独时段（不占日模板）"的子活动（`:109/190`），且执行挂下一假期（`:77/192/328`）；折叠后语义不丢失，只在「暑假衔接收口」阶段配置内显式表达"建档子活动（执行状态：挂起，待下一假期）"。代价：阶段配置需新增"子活动/单独时段"表达位，否则丢失"建档不占日模板"语义（对齐 §2 假期模式日模板，`:109`）。
2. **选项② 裁剪建档与快补两段——采纳（对快补段；对建档段须与选项①组合）**。理由：快补 = 预防性补差，被 §4.3 显式否决（`:188-191`），其"只补P0薄弱前置"目标被"回查用前置层：不再主动教，只在七上错题回查时按需诊断"取代（§4.2，`:182`）→ 独立阶段无存在必要，直接裁剪；建档则不是"不做"而是"挂下一假期做"，单独裁剪会丢失该配置表达，须与选项①组合（折叠）。
3. **选项③ 保留为历史快照——否决**。理由：Task 4 已实测 `learning_path` 零代码消费（grep 0 命中，见核对项 2 现状）→ 保留无人读取、纯文档冗余；且 50 天日历锚定与新执行窗口（距开学 4 天）矛盾，保留反而误导未来读者；历史追溯由 git 历史承载（本 JSON 已是版本化资产），无需在数组内留死配置。若强行保留的代价：同一 JSON 并存"当前生效规划"与"过期快照"两套数组 → 结构二义性，与设计稿 §8.2「`learning_path` 改为阶段数组、先落 2 阶段」冲突（`:333`）。
4. **保留语义的落位**：主线/混合/收口三段语义保留——「七上主线预学」（第13-35天）→ §4.2 七上主线身份升级（`:181`）；「混合迁移」（第36-44天）→ 主线内混合题/易错回炉语义；「开学前收口」（第45-50天，两次综合检测 + 开学首月跟踪清单，`math_knowledge_graph_v2.json:8653-8657`）→ 与「暑假衔接收口」阶段命名同源，即该阶段的收口动作。日期段标签（第X-Y天）不保留——新执行窗口下日历锚定失效，`phase` 字段改为语义阶段标识（核对项 2 已记录该改造方向）。

**影响：**

1. 阶段数组计划（后续计划）的改造范围明确：`phase_strategy` 5 元素（`math_knowledge_graph_v2.json:8632-8658`）→ 收敛为先落 2 阶段「暑假衔接收口 + 开学首月」（设计稿 §8.2，`2026-08-20-child-learning-companion-design.md:333`）；建档子活动（挂下一假期）、收口动作等语义在阶段配置内显式表达，`phase` 字段从"第X-Y天"标签改为阶段标识。
2. 零运行时耦合（Task 4 实测 grep 0 命中）→ 改造只动 JSON 配置、不动代码/数据；阶段数组若要驱动执行（如阶段 → daily_runtime mode 映射），须在阶段数组计划中显式定义（核对项 2 影响清单第 3 条）。
3. 建档执行时序不受本裁定改变：挂下一假期（文档头执行窗口/§8.4，`2026-08-20-child-learning-companion-design.md:77/356`）；开学首月收口验收（错题录入可用、周信出首期、判定口径统一后状态可信）不等建档（`:356`）。
4. **最终裁定随阶段数组计划执行**：本核对项只产出裁定建议（推荐 = 折叠 + 裁剪），不落地任何改动；阶段数组实际改写随后续「阶段数组计划」执行（设计稿 §8.2，`:333`；实现计划已声明阶段数组改造需本裁定结果 + v20 生题结束后，避免 digest 联动 churn，`2026-08-20-semester-data-link-prereqs.md:13`）。
5. 挂起项：无独立挂起——"建档子活动在「暑假衔接收口」阶段配置内的具体表达（字段/子结构）"属执行细节，随阶段数组计划落地时裁定，不阻塞本裁定建议。

---

### 核对项 6：判定口径逐实现

> 对应 Task 7（实现计划 §Task 7）。**spec §8.1 必答项**：蓝图 / evolution.py / flow_nodes / daily_runtime 判定口径逐实现核对（≥3 套，收口为一套）。

#### 现状（证据：文件:行）

四套判定口径逐实现实测（阈值 / 状态枚举 / 证据要求），证据均经读代码核实：

**① `evolution.py`：`_status_from_attempts`（`learning_system/evolution.py:662-683`）**

- 输入：单节点作答行集，`ratio = score/max_points`（`:663-665`）。
- 判定链（按序）：任一 `blocking_evidence` → **D**（`:668-669`）；任一"高分推理缺口"（`_has_high_score_reasoning_gap`，`:686-699`：result=correct 或 ratio≥0.85，且 `reasoning_soundness ∈ {incomplete, unsound, unclear}` 或 `evidence_strength ∈ {weak, insufficient}` 或 `next_evidence_need` 非空）→ **C** 且 can_explain=False（`:670-676`）；`ratio ≥ 0.85 and can_explain and len(rows) >= 2` → **A**（`:677-678`）；`ratio ≥ 0.85 and can_explain` → **B**（单条强证据，`:679-680`）；`ratio ≥ 0.60` → **B**（`:681-682`）；其余 → **C**（`:683`）。
- 证据要求：**can_explain** = 任一作答 `explanation_score ≥ 2` 且无推理缺口（`:666`）；**最小样本** = A 需 `len(rows) ≥ 2`（`:677`），B/C/D 允许单条；**无题型多样性/迁移证据要求**（函数全文不读 question.kind）。
- 落位：**proposal-only，不直接落库**——结果写入 evolution 事件 `after.node_status_update_proposals`（`:1140-1147`、`:1305`）；evolution.py 对 `learner_node_status` 只读不写（`:1138/1290`，写入目标为 `evolution_events`，`:1361`）。

**② `flow_nodes.py`：`_mastery_diagnosis`（`learning_system/flow_nodes.py:399-498`）**

- 状态枚举：**6 态** `mastery_state` = `blocked / unstable / emerging / stable / likely_stable / insufficient_evidence`（`:439-450`）——**设计稿 §3.2 现状清单只列 4 态是低估**（`2026-08-20-child-learning-companion-design.md:142` 漏 blocked/unstable；§8.1 已改记 6 态，`:326`），实测以代码为准。
- 判定链（按序）：`has_blocking` → **blocked**（`:439-440`）；`weak_result`（任一 result∈{wrong,partial}）或 `ratio < 0.6` 或存在 weak_attempts → **unstable**（ratio<0.6 或 weak_result 时）否则 **emerging**（`:441-442`）；`len(strong_attempts) ≥ 2` 且 has_transfer_evidence 且 has_form_diversity → **stable**（`:443-444`）；`len(strong_attempts) ≥ 2` → **likely_stable**（`:445-446`）；有 strong_attempts（≥1）→ **emerging**（`:447-448`）；否则 → **insufficient_evidence**（`:449-450`）。
- **0.6 边界**：`ratio < 0.6` → unstable（`:441-442`）；无 0.85 硬阈值——"强证据"由 strong 定义替代（见下）。
- 证据要求：
  - **strong_attempts** = result=correct 且 `explanation_score ≥ 2` 且 `_has_strong_core_analysis`（`:409-414`；`:352-361`：comparison 五维 final_answer/model_or_relation/steps/symbols_units/check_or_explanation 全部 status ∈ {matched, alternative_valid}，`STRONG_ANALYSIS_STATUSES` `:80`）；
  - **weak_attempts** = result∈{wrong,partial} 或 explanation_score<2 或 core 分析不完整（`:415-420`）；
  - **迁移证据** = 任一题型 kind ∈ `TRANSFER_CONFIRMATION_KINDS`（8 种：transfer_retest/stretch_transfer/two_method_compare/representation/model_selection/reverse_reasoning/boundary_case/missing_condition，`:69-78/423`）；
  - **题型多样性** = `len(question_kinds) ≥ 2`（`:424`，`_question_kinds_for_attempts` `:364-374` 按题 kind 去重）；
  - 确认类型 `confirmation_type`：no_retest_needed / prerequisite_probe / near_transfer_retest / same_structure_retest（`:457-466`）。
- 落位：经 v2 orchestrator 落 `learner_node_status`——`_mastery_decision_from_status`（`orchestrator.py:335-360`）映射 decision/closure_result；`_status_update_from_evaluation`（`orchestrator.py:523-555`）映射 A/B/C/D：blocked→**D**；insufficient_evidence 或无 strong 的 unstable/weak→**C**；stable 且 can_advance→**A**；其余→**B**；insert or replace 写入（`orchestrator.py:565-581`）。
- 另：`build_mastery_evaluation_package` 还产出 4 档 `overall_status`（blocked/stretch_ready/basic/weak，`flow_nodes.py:519-528`）与分维状态 concept/model/calculation/expression/transfer（`_status_from_comparison` `:318-332`）——设计稿"4 态"若指 overall_status，则与 mastery_state 6 态并存，差异表中须区分。

**③ `daily_runtime.py`：v51 `mastery_recommendation` → A/B/C/D 映射（`learning_system/daily_runtime.py:13533-13605`）**

- 推荐枚举（评估 agent 契约）：`["no_update", "blocked", "weak", "emerging", "likely_stable", "stable_for_now"]`（`learning_system/agent_contracts/evaluation_decision.v2.json:39`）；prompt 纪律"单条强证据不足以证明持久掌握 / stable_for_now 仅限多样化证据"（`learning_system/prompts/evaluation_decision.v2.md:12/17-23`）。
- 映射（按序，`daily_runtime.py:13561-13605`）：
  - `blocking_evidence` 或 recommendation=blocked → **D**（prerequisite_blocked，`:13561-13564`）；
  - recommendation=stable_for_now 且 `_evidence_set_supports_stable_mastery(source_validation_ids)` → **A**（`:13565-13568`）；
  - recommendation=weak → **C**（`:13569-13572`）；
  - recommendation=emerging：old_status∈{A,C} → 保留旧档（preserve_accumulated_status，`:13574-13577`）；否则 → **B**（basic_understanding，`:13578-13581`）；
  - old_status∈{A,C} 且 recommendation="" → 保留旧档（`:13582-13585`）；
  - recommendation=likely_stable → **B**（`:13586-13589`）；
  - result=correct 且 explanation_score≥2 且 reasoning_soundness=sound → **B**（`:13590-13593`）；
  - result=partial → **C**（`:13594-13597`）；其余 → **C**（`:13598-13601`）；
  - 兜底修正：recommendation∈{blocked,weak} 且已判 B → 降 **C**（`:13602-13605`）。
- 证据要求（A 档门槛 = `_evidence_set_supports_stable_mastery`，`:13746-13840`）：≥2 条 validation id（`:13747-13749`），每条经全链校验（`:13797-13833`：purpose=diagnostic、hint_policy=no_hint、mastery_update_eligible、无 hint 暴露、evidence active/graded/valid、assessment accepted 且 question_passed、review approved、图谱/题库/题版本全当前），且 **≥2 个不同 structure_fingerprint** + diagnostic_roles 同时含 **confirmation_core 与 confirmation_transfer**（`:13834-13840`）。
- v51 确定性评估（`_v51_deterministic_evaluation_output` `:7776-7836`）：`score_out_of_10 < 8` 或 severe_gap → weak，否则 emerging（`:7813/7820`）；severe_gap = required_for_pass 得分点在 concept/model_relation/procedure/calculation/final_answer/transfer 六维 status∈{contradicted, not_met}（`:7838-7863`）→ **确定性路径只产 weak/emerging 两档**，blocked/likely_stable/stable_for_now 来自 LLM 评估 agent（记录回放 `_default_recorded_evaluation_output` `:9708-9741` 也只产 weak/emerging，`:9724`）。
- 落位：insert or ignore 写 `mastery_decisions`（`:13637`）+ insert or replace 写 `learner_node_status` 且 status_revision 递增（`:13699-13705`）。版本标识：v51 开关 `answer_assessment_v51_enabled`（`:521`）、assessment_policy_version='v5.1'（`:734/791`）。

**④ 蓝图 §12（`docs/00_PROJECT_BLUEPRINT.md:637-666`）**

- 状态枚举：A 已掌握 / B 不稳定 / C 薄弱 / D 卡死（`:639`）。
- 阈值（正确率）：A = **≥ 85%**（且"能讲清方法、能做一道小变式"，`:641-646`）；B = **60%-85%**（或需提醒才能做，`:648-652`）；C = **< 60%**（或概念说不清，`:654-658`）；D = 当前节点错 + 前置链条也错（`:660-665`）。
- 证据要求：**定性描述**（能讲清方法 / 概念说不清），无最小样本数、无 explanation_score、无题型多样性/迁移证据的量化要求。
- 落位：设计文档非代码——对应 §7.2 诊断 agent"给节点打 A/B/C/D 状态"（`:231`）。

**四套口径差异表（阈值 × 状态枚举 × 证据要求 × 落库路径）：**

| 实现 | 阈值 | 状态枚举 | 证据要求 | 落库路径 |
|---|---|---|---|---|
| 蓝图 §12（文档，`:637-666`） | 正确率 A≥85% / B 60-85% / C<60%；D=节点错+前置链错 | A/B/C/D（语义档） | 定性（能讲清方法/概念说不清）；无最小样本、无解释分、无迁移/多样性量化 | 不落库（设计文档，非代码） |
| `evolution.py` `_status_from_attempts`（`:662-683`） | ratio 0.85/0.60；blocking→D、高分推理缺口→C 优先 | A/B/C/D | can_explain（explanation_score≥2 且无推理缺口）；A 需样本≥2；无迁移/多样性要求；**proposal-only（状态不入 learner_node_status/mastery_decisions）** | 不落库——仅写 `evolution_events`（`:1361`） |
| `flow_nodes.py` `_mastery_diagnosis`（`:399-498`） | ratio<0.6→unstable（0.6 边界）；无 0.85 硬阈值（strong 定义替代） | **6 态** mastery_state：blocked/unstable/emerging/stable/likely_stable/insufficient_evidence（另有 4 档 overall_status） | strong=correct+解释分≥2+五维 core 全 matched/alternative_valid；stable 需 strong≥2+迁移题型+题型≥2 种 | v2 orchestrator 落库：`learner_node_status`（`orchestrator.py:565-581`）+ `mastery_decisions`（`orchestrator.py:695` → `db.py:1925`） |
| `daily_runtime.py` v51（`:13533-13605`） | 无百分比阈值；确定性路径 score<8/10 或 severe_gap→weak（`:7813/7820`） | recommendation 6 枚举（no_update/blocked/weak/emerging/likely_stable/stable_for_now，`evaluation_decision.v2.json:39`）→ status_code A/B/C/D | A 档需≥2 条全链校验证据+≥2 structure+confirmation_core&transfer 双角色（`:13746-13840`）；B 需 correct+解释分≥2+sound 或 emerging/likely_stable；解释分<2 或 partial→C | v5 落库：`mastery_decisions`（`:13637`）+ `learner_node_status`（`:13699-13705`） |

#### 裁定点

- 四套口径差异（阈值 / 状态枚举 / 证据要求）逐实现核实并录表（Step 1-4）；确认 flow_nodes 实际 **6 态** vs 设计稿 §3.2"4 态"记录偏差（Step 2 实测，`2026-08-20-child-learning-companion-design.md:142` 漏 blocked/unstable）。
- 结论形态：**只录现状，不裁定**——具体判定规则（阈值、最小证据量、时间窗口、升降级、复测间隔算法）归 M2.5 权衡产出 `mastery_criteria_proposal` 后统一为一套（spec §3.2 归属与 §8.4 M2.5，`2026-08-20-child-learning-companion-design.md:144/352`）。

#### 结论（或挂起原因）

**选择：只录现状（差异表已核实入表），不裁定——四套口径并存事实确认，统一裁定挂起待 `mastery_criteria_proposal`（属 M2.5）。**

- 现状确认（对应 Step 1-4 实测）：四套判定口径**确实并存且互不一致**——阈值（蓝图 85/60 百分比 vs evolution 0.85/0.60 vs flow_nodes 仅 0.6 边界 vs v51 8/10 分制无百分比）、状态枚举（A/B/C/D vs A/B/C/D vs 6 态 mastery_state vs recommendation 6 枚举）、证据要求（定性 vs can_explain+最小样本 vs 迁移+题型多样性 vs 全链校验+双角色）三列均存在实质差异；`mastery_recommendation` → A/B/C/D 的映射只存在于 daily_runtime v51 一处（`daily_runtime.py:13533-13605`），其余实现自建判定。
- **挂起项：判定口径统一 → 挂起待 `mastery_criteria_proposal`（属 M2.5）**——本核对项只录现状；具体规则（阈值、最小证据量、时间窗口、升降级、复测间隔算法）由权衡产出 `mastery_criteria_proposal`（P0 前置交付物，三方会审+爸爸拍板），落地为 M2.5 统一实现（`2026-08-20-child-learning-companion-design.md:144/327/352`）。

**影响（供 M2.5 裁定输入，本步不执行）：**

1. 差异收口主战场 = 两条**落库路径**：flow_nodes（v2 orchestrator，`orchestrator.py:565-581`）与 daily_runtime v51（v5，`daily_runtime.py:13699-13705`）；evolution.py 口径是 proposal-only（状态不入 `learner_node_status`/`mastery_decisions`，仅写 `evolution_events`，`evolution.py:1305/1361`），统一时优先对齐两条落库路径。
2. A 档门槛差异显著（85%+能讲清 → ≥2 样本+can_explain → 2 条 strong+迁移+多样性 → 2 条全链校验+双角色），"最小证据量+复测确认"（§3.2 第 2 条，`2026-08-20-child-learning-companion-design.md:139`）在各实现的落地强度不同——`mastery_criteria_proposal` 需统一最小样本与确认条件。
3. flow_nodes 6 态 vs 设计稿 §3.2"4 态"记录偏差已如实入表（§8.1 已改记 6 态，`:326`）；M2.5 统一时以实测 6 态为准。
4. v51 确定性路径只产 weak/emerging，LLM 评估 agent 才产全 6 枚举（评估 agent 契约键 = `evaluation_decision` v2，`internal_agents.py:68-69`；recommendation 6 枚举定义 `agent_contracts/evaluation_decision.v2.json:39`）——LLM 参与边界（§3.2 第 3 条：LLM 只在错因归类与叙述，`:140`）需在 `mastery_criteria_proposal` 中明确评估环节 LLM 的角色与降级路径。
5. 与核对项 4 挂起项呼应：手动错题（explanation_score 缺失）在 evolution/flow_nodes 口径下无法进 A 档——手动证据入档规则属 `mastery_criteria_proposal` 裁定（§3.1，`:130`；核对项 4 结论挂起项 1）。

---

### 核对项 7：CANONICAL_ERROR_TAGS 双定义

> 对应 Task 8（实现计划 §Task 8）。`auto_review.py` / `question_bank.py` 双定义核对 + 收口建议。

#### 现状（证据：文件:行）

**双定义（`diff` 逐字比对实测）**

- `learning_system/auto_review.py:10-17` 与 `learning_system/question_bank.py:16-23` 的 `CANONICAL_ERROR_TAGS` **逐字一致**：`diff <(sed -n '10,17p' learning_system/auto_review.py) <(sed -n '16,23p' learning_system/question_bank.py)` 输出为空；两段均为 8 行 set 字面量、无注释/空白差异。
- **6 个 tag**：`calculation_or_symbol` / `concept_confusion` / `modeling_or_reading` / `process_habit` / `visual_spatial` / `general`。
- `auto_review.py` 另派生 `DIMENSION_GAP_ERROR_TAGS`（`auto_review.py:22-28`，五维 → tag 映射），取值均在上述 6 tag 内。

**消费方不对称（`grep -rn "CANONICAL_ERROR_TAGS" learning_system/ tests/ --include="*.py"`，21 命中，其中 2 处为定义）**

- `question_bank.CANONICAL_ERROR_TAGS` 是**事实共享源**：外部消费者 4 个模块 8 处引用——`db.py:263/6106`（落库标签校验）、`daily_runtime.py:9263/9268`（批改规范化 `_canonical_error_tags_for_answer_output`，`daily_runtime.py:9251-9276`）、`evolution.py:174/284/356`（LLM 契约枚举/演化标签）、`tests/test_learning_system.py:5636`；另 `question_bank.py` 内部 8 处使用（题面过滤 `4270/5327/5958/9723/9751` 等）。
- `auto_review.CANONICAL_ERROR_TAGS` **仅自用**（`auto_review.py:366/840/892`，批改 JSON schema 枚举与结果过滤），无外部导入者。
- **无防漂移机制**：两定义各自独立维护；全库无测试断言两定义相等（`tests/test_learning_system.py:5636` 只断言 `grade["error_tags"] ⊆ question_bank.CANONICAL_ERROR_TAGS`，未比较 `auto_review` 版本）→ 任一侧增删 tag 不报错，三年错因分布（`error_cause_log.error_tag` 枚举，见核对项 3 结论影响清单第 4 条）将随消费方导入源不同而口径漂移。

- 需求背景：spec §7「双 `CANONICAL_ERROR_TAGS` 收口为单一导入源，防三年错因分布漂移」（`2026-08-20-semester-data-link-prereqs.md:106` §Task 8 步骤 2）。

#### 裁定点

- 双定义是否逐字一致（Task 8 Step 1）；收口为单一导入源的落点建议（Task 8 Step 2，列为后续计划项）。

#### 结论（或挂起原因）

**选择：双定义现状逐字一致（6 tag 全同）、无紧急修复必要；收口为单一导入源（推荐 + 最小方案，均含落点），列为后续计划项，本核对不落地任何代码改动。**

- 逐字一致性实测：`diff` 输出为空（见现状）——**现状无漂移**；但**漂移风险真实存在**：双定义独立演进、无测试护栏，任一侧增删 tag 即造成 `error_cause_log`（三年错因分布，核对项 3 已裁定新增）与批改/出题两侧的枚举口径分裂。
- **收口建议（落点）**：
  - **推荐方案**：新建 `learning_system/error_tags.py` 为**唯一定义源**（导出 `CANONICAL_ERROR_TAGS`，顺带托管 6 tag 语义注释）；`auto_review.py` 与 `question_bank.py` 均改为 `from .error_tags import CANONICAL_ERROR_TAGS`；既有外部消费者（`db.py`/`daily_runtime.py`/`evolution.py`/`tests`）继续经 `question_bank` 再导出，或逐步迁移到 `error_tags`。理由：中性落点、不引入模块方向依赖（避免 `auto_review → question_bank` 把 9836 行大模块拉进批改热路径 import 面）、为 `error_cause_log.error_tag` 提供唯一枚举锚点。
  - **最小方案（不加新模块）**：`auto_review.py` 删定义、改 `from .question_bank import CANONICAL_ERROR_TAGS`——`question_bank` 已是事实共享源（4 个外部模块，见现状），改动面仅 2 行。
  - **防漂移护栏（任选方案都应补）**：收口后加一条单元测试断言单一源唯一（或收口前断言双定义相等），防止未来重新分叉。
- **列为后续计划项**：收口是代码改动（新增/修改模块 + import），超出本核对只读范围（本记录 §3 填写纪律第 5 条：结论不得引发对代码/数据的修改）→ 执行列入后续计划（可与核对项 3 的 `error_cause_log` schema、M4 错题录入同批，或作为独立小改动先行）。
- 挂起项：无独立挂起——收口执行 = 后续计划项，不阻塞本核对项与 Chunk 1 完成。

**影响：**

1. 三年错因分布可信度前置：`error_cause_log.error_tag`（核对项 3 已裁定一行一标签、枚举对齐 `CANONICAL_ERROR_TAGS`）与批改/出题两侧同源后，分布统计口径唯一；收口前靠人工比对防漂移。
2. 改动面评估：推荐方案 = 新增 1 模块 + 2 文件 import 替换 + 消费者可逐步迁移，集合内容不变、无行为变化；最小方案 = 仅 `auto_review.py` 2 行。
3. 与设计稿 §7 一致：§7 已裁定收口为单一导入源（`2026-08-20-semester-data-link-prereqs.md:106`），本核对项为其提供现状证据（双定义逐字一致 + 消费方不对称）与落点建议。
4. 后续计划承接：在阶段数组 / M2.5 / M4 之外新增"`CANONICAL_ERROR_TAGS` 收口"小计划项，执行时在推荐与最小方案间二选一。

---

## 5. 完成条件与后续

**Chunk 1 完成条件**（对齐实现计划）：

1. 7 项核对（原 6 项 + 新增 vs 别名）齐全，每项含"结论/挂起"；
2. 无未决裁定点遗留（除显式标注"挂起待 X"的）；
3. 可机检自检：`grep -c "结论\|挂起" docs/design/specs/2026-08-20-dataflow-audit-record.md` ≥ 7；`grep -c "^### " docs/design/specs/2026-08-20-dataflow-audit-record.md` ≥ 7（7 项核对标题齐全）；
4. 文档头标注"仅供设计决策参考，不改任何代码/数据"（见文首用途声明）。

**后续关联**：

- 本记录裁定结果 → 阶段数组改造计划（`learning_path`）、M2.5 判定口径统一、M4 错题录入与已裁定新增表落地（spec §8.2/§8.4）。
- 本记录只读：**不修改任何代码/数据**；一切改动走对应实现计划。
