# 现状数据流核对记录（学期数据链路前置 · Chunk 1）

- Date: 2026-08-20
- Owner: 若命（软件架构）——核对执行与裁定记录
- Status: skeleton（骨架）；核对项 1–7 由 Task 2–8 逐项填充后定稿
- Scope: `learning_system/` 数据流现状核对 + 裁定点记录（只读分析）
- 前置文档：`docs/design/specs/2026-08-20-child-learning-companion-design.md`（§8.1 第 0 步核对）、`docs/00_PROJECT_BLUEPRINT.md`
- 实现计划：`.agents/superpowers/specs/2026-08-20-semester-data-link-prereqs.md`（Chunk 1）

> **用途声明：本记录仅供设计决策参考，不改任何代码/数据。** 所有核对均为只读分析；任何"结论"都只影响后续设计裁定，不构成对 `learning_system/`、`data/` 或运行库的修改授权。

> **一句话结论（骨架期占位）**：本记录逐项核对现状数据流，对每个裁定点给出「现状 / 冲突 / 选择 / 影响」，或显式"挂起待 X"；7 项核对齐全后，作为数据模型改动（设计稿 §8.2）与后续计划（阶段数组 / M2.5 判定口径统一 / M4 错题录入）的决策依据。

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

本记录是 Chunk 1 的最终交付物，后续 Task 2–8 会逐项向本文件的对应核对项小节追加核对内容；**骨架期只搭结构与模板，不预填核对结论**。

---

## 2. 核对清单（7 项）

核对清单来自设计稿 §8.1（含第三轮会审扩项与 §3.1/§3.3 必答项），共 7 项：

| # | 核对项 | 来源 | 必答项标记 | 状态 |
|---|---|---|---|---|
| 1 | `attempts` / `learner_node_status` / `mastery_decisions` 表与消费方 | spec §8.1 第 0 步逐表对照 | — | 已完成（Task 2） |
| 2 | `generated_plans` / `daily_flows`（短期计划现状） | spec §8.1 第 0 步逐表对照 | — | 待核对（Task 4） |
| 3 | **已裁定新增表**：`error_cause_log` / `weekly_summary`（A/B/C/D 时间快照 + acknowledged 枚举）/「作业全对」确认载体 → **「新增 vs 别名」裁定** | spec §8.1 必答项**首项**、§3.3 | ✅ 必答 | 待核对（Task 3） |
| 4 | `attempts` FK 三方案影响（`question_id`/`session_id` NOT NULL） | spec §8.1 必答项、§3.1 | ✅ 必答 | 待核对（Task 5） |
| 5 | `phase_strategy` 现状（5 阶段 → 迁移裁定） | spec §8.1 必答项（第三轮会审扩项） | ✅ 必答 | 待核对（Task 6） |
| 6 | 判定口径逐实现（evolution / flow_nodes / daily_runtime / 蓝图） | spec §8.1 必答项、§3.2 | ✅ 必答 | 待核对（Task 7） |
| 7 | `CANONICAL_ERROR_TAGS` 双定义（auto_review.py / question_bank.py） | spec §7 架构取舍、§8.1 | — | 待核对（Task 8） |

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
- 行生命周期：唯一插入点 `db.record_attempt`（insert 于 `db.py:6872`）；全库无 `delete from attempts`（grep 0 命中）；失效走 `evidence_status` 软状态 `{active, invalidated, stale}`（校验于 `db.py:6842`）。列级存在 in-place 富化：`answer_analysis_json` 回填（`db.py:7645`）、`analysis_version + 1`（`daily_runtime.py:4280`）、`cause_analysis_json`（`evolution.py:1279`）、`review_meta_json`（`server.py:2426`）、`evidence_digest_sha256`（`daily_runtime.py:1910`）——行不删，分析列后补。

**`learner_node_status`（`learning_system/db.py:534-549`）**

- 主键 `node_id`（`db.py:535`）→ 每节点一行**当前状态快照**（非日志表）。
- `status_revision integer not null default 1`（`db.py:547`，迁移补列 `db.py:1428`）：语义 = 状态快照的迭代修订号。v5 写路径经 `coalesce((select status_revision + 1 from learner_node_status where node_id = ?), 1)` 递增（`daily_runtime.py:13705`）；v2 写路径（`orchestrator.py:567-571`）不递增（insert or replace 不写该列 → 重置为 1）。前一修订号被抄入 `mastery_decisions.old_status_id`（`daily_runtime.py:13667`）。
- `evidence_attempt_ids_json`（`db.py:539`）= 支撑该状态的作答 id 列表（权威校验仍读它，`db.py:2932` 记为 legacy 语义）；`source_attempt_ids_json`（`db.py:544`）/`source_evidence_validation_ids_json`（`db.py:545`）= v5 写路径的源作答/证据校验 id（`daily_runtime.py:13664-13665`，与 `evidence_attempt_ids_json` 同值写入）。
- 行生命周期：`insert or replace` 覆盖式 upsert（`daily_runtime.py:13699`、`orchestrator.py:567`）；修复函数 `_repair_learner_node_status_invalid_refs` 可 DELETE 失效行（`db.py:2743-2823`，删除点 `db.py:2771/2792/2809/2817`）→ **非 append-only**。

**`mastery_decisions`（`learning_system/db.py:643-665`）**

- append-only 实测确认：全库 `grep "update mastery_decisions\|delete from mastery_decisions"` **0 命中**；唯一写入 = `db.record_mastery_decision` 的 `insert into`（`db.py:1925`，调用方 `orchestrator.py:695`）与 v5 路径的 `insert or ignore into`（`daily_runtime.py:13637`）。
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

- 长期档案由两张表分工承载：`attempts` 行级 append（只 insert、无 delete、`evidence_status` 软失效，分析列 in-place 回填不破坏痕迹）；`mastery_decisions` **严格 append-only**（只 insert、无 update/delete，唯一索引幂等），每次评估决策一条记录，含 `old_status_id`（前一修订号）/`new_status_code`（A/B/C/D）/`decision_version`/`source_evidence_validation_hash`/`applied` → **状态变更留痕完整**。`learner_node_status` 只是"当前状态"派生快照（insert or replace + 修复删除，非 append），其历史完全可由 `mastery_decisions` 重建。设计与实现一致（设计稿 `2026-08-20-child-learning-companion-design.md:153/368` 已声明同一结构，本次核对逐条证实）。
- 挂起项：无。

**影响：**

1. 无需新增表：M2.5 及后续周信如需"当周状态快照"，沿 `mastery_decisions.created_at` 过滤即可（已有 `idx_mastery_decisions_session`，`db.py:1243`）。
2. 查询纪律：任何"历史/某时刻状态"必须走 `mastery_decisions`，不得依赖 `learner_node_status`（其行会被覆盖甚至删除，`db.py:2771/2792/2809/2817`）。
3. 注意偏差：`mastery_decisions.old_status_id` 存的是前一 `status_revision` 编号（`daily_runtime.py:13667`），非行 id，字段命名与语义不符，后续设计引用需注意。
4. `attempts` 的 append-only 是"行级"：`answer_analysis_json`/`cause_analysis_json`/`review_meta_json` 等列会被回填更新——与"档案只增不改"（设计稿 §3.3 第 4 条，`child-learning-companion-design.md:74`）兼容，但口径上"不改"指行不删除、作答痕迹保留。

---

### 核对项 2：短期计划表（generated_plans / daily_flows）

> 对应 Task 4（实现计划 §Task 4）。目标：确认短期计划结构能否承载"阶段数组可重排"。

#### 现状（证据：文件:行）

- `generated_plans`：见 `learning_system/db.py:572` 起（列、与节点/阶段的关系）。
- `daily_flows`：见 `learning_system/db.py:1013` 起。
- `learning_path` 现状：`data/knowledge_graphs/math/math_knowledge_graph_v2.json` 的 `learning_path`（规划配置 dict，非档案）。

（骨架占位：Task 4 填充）

#### 裁定点

- 短期计划现状是否与设计稿 §3.3 兼容（`learning_path` 改阶段数组，先落 2 阶段）？（预期结论：结构兼容，改造留到阶段数组计划）

（骨架占位：Task 4 填充）

#### 结论（或挂起原因）

（骨架占位：Task 4 填充；若存在未决点，标注"挂起待 X"）

---

### 核对项 3：已裁定新增表（新增 vs 别名）

> 对应 Task 3（实现计划 §Task 3）。**spec §8.1 必答项首项**：`error_cause_log` / `weekly_summary` / 「作业全对」确认载体 → 三者「新增 vs 别名」裁定。

#### 现状（证据：文件:行）

- `error_cause_log`：`grep -rn "error_cause\|wrong_cause" learning_system/db.py`（预期：无现成表；`attempts.error_tags_json` 仅存单次错因标签，无跨期聚合语义）。
- `weekly_summary`：确认无现成表；记录设计稿要求——长期档案 append-only、存**当周 A/B/C/D 时间快照**、爸爸确认状态枚举 `acknowledged`/`unacknowledged`（spec §3.3）。
- 「作业全对」确认载体：确认无现成载体；记录设计稿要求——只作证据范围标注、**不进判定样本**（spec §3.1）。

（骨架占位：Task 3 填充）

#### 裁定点

- 三者各是"新增表 / 新增字段 / 现有表别名"？（预期：均为新增；给出最小 schema 草案——列清单，细节留 M4 计划）

（骨架占位：Task 3 填充）

#### 结论（或挂起原因）

（骨架占位：Task 3 填充；若存在未决点，标注"挂起待 X"）

---

### 核对项 4：attempts FK 三方案影响

> 对应 Task 5（实现计划 §Task 5）。**spec §8.1 必答项**：`attempts.question_id`/`session_id` NOT NULL，评估「可空化 / 占位 / 旁挂侧表」三方案联动影响。

#### 现状（证据：文件:行）

- FK 依赖清单：`grep -rn "join question_items\|join attempts\|references question_items\|references learning_sessions" learning_system/ --include="*.py"`（实测 20+ 处：agents.py:60、daily_runtime.py:7635/12506/14623、planner.py:357/382、question_bank.py:4407 等；含 `idx_v3_attempts_one_active_per_step` db.py:1475）——逐条记录 JOIN 语义（INNER JOIN 对 NULL `question_id` 的行为变化）。

（骨架占位：Task 5 填充）

#### 裁定点

- 方案① 可空化 `question_id`/`session_id`：对照依赖清单列受影响 join/索引；
- 方案② 合成占位 question/session：评估对 `question_items` 统计与 `learning_sessions` 的污染；
- 方案③ 旁挂侧表（如 `manual_error_entries`）再反链 `attempts`：评估与现有证据链的一致性；
- 给出**推荐方案 + 影响清单**（此结论直接决定 M4 错题录入的 schema 改动）。

（骨架占位：Task 5 填充）

#### 结论（或挂起原因）

（骨架占位：Task 5 填充；若存在未决点，标注"挂起待 X"）

---

### 核对项 5：phase_strategy 现状与迁移裁定

> 对应 Task 6（实现计划 §Task 6）。**spec §8.1 必答项（第三轮会审扩项）**：现网 `learning_path.phase_strategy` 已是 5 阶段数组，裁定旧阶段去留。

#### 现状（证据：文件:行）

- 现网 5 阶段：`math_knowledge_graph_v2.json` 的 `learning_path.phase_strategy`（第1-3天建档 / 第4-12天快补 / 第13-35天主线 / 第36-44天混合 / 第45-50天收口）。
- 与新设计的冲突：建档（挂下一假期）、快补（§4.3 不做预防性补差）与新执行窗口冲突。

（骨架占位：Task 6 填充）

#### 裁定点

- 旧 5 阶段去留三选项：折叠进「暑假衔接收口」/ 裁剪建档与快补两段 / 保留为历史快照——给出推荐（预期：折叠 + 裁剪，保留主线/混合/收口语义），并标注"最终裁定随阶段数组计划执行"。

（骨架占位：Task 6 填充）

#### 结论（或挂起原因）

（骨架占位：Task 6 填充；若存在未决点，标注"挂起待 X"）

---

### 核对项 6：判定口径逐实现

> 对应 Task 7（实现计划 §Task 7）。**spec §8.1 必答项**：蓝图 / evolution.py / flow_nodes / daily_runtime 判定口径逐实现核对（≥3 套，收口为一套）。

#### 现状（证据：文件:行）

- `evolution.py`：`_status_from_attempts`（0.85/0.60 + can_explain + 最小样本）。
- `flow_nodes.py`：`_mastery_diagnosis`（6 态：blocked / unstable / emerging / stable / likely_stable / insufficient_evidence + 0.6 边界）。
- `daily_runtime.py`：v51 `mastery_recommendation` → A/B/C/D `status_code` 映射。
- 蓝图 §12：`docs/00_PROJECT_BLUEPRINT.md`（A≥85% / B 60-85% / C<60%）。

（骨架占位：Task 7 填充）

#### 裁定点

- 四套口径差异表（阈值 / 状态枚举 / 证据要求）。结论："裁定交给 M2.5（权衡产出 `mastery_criteria_proposal`），本步只录现状"——即本项结论为**挂起待 M2.5**。

（骨架占位：Task 7 填充）

#### 结论（或挂起原因）

（骨架占位：Task 7 填充；预期结论形态：挂起待 `mastery_criteria_proposal`）

---

### 核对项 7：CANONICAL_ERROR_TAGS 双定义

> 对应 Task 8（实现计划 §Task 8）。`auto_review.py` / `question_bank.py` 双定义核对 + 收口建议。

#### 现状（证据：文件:行）

- 双定义：`learning_system/auto_review.py:10` 与 `learning_system/question_bank.py:16` 的 `CANONICAL_ERROR_TAGS`（逐字一致？）。
- 需求背景：spec §7「双 `CANONICAL_ERROR_TAGS` 收口为单一导入源，防三年错因分布漂移」。

（骨架占位：Task 8 填充）

#### 裁定点

- 双定义是否逐字一致；收口为单一导入源的落地建议（列为后续计划项）。

（骨架占位：Task 8 填充）

#### 结论（或挂起原因）

（骨架占位：Task 8 填充；若存在未决点，标注"挂起待 X"）

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
