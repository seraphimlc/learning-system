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
| 1 | `attempts` / `learner_node_status` / `mastery_decisions` 表与消费方 | spec §8.1 第 0 步逐表对照 | — | 待核对（Task 2） |
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

- `attempts`：见 `learning_system/db.py:418` 起（列、FK `session_id`/`question_id` NOT NULL REFERENCES、`answer_source` 枚举默认 `'legacy'`）。
- `learner_node_status`：见 `learning_system/db.py:534` 起（`status_revision` 语义、`evidence_attempt_ids_json`/`source_attempt_ids_json`）。
- `mastery_decisions`：见 `learning_system/db.py:643` 起（append-only 确认：是否只 insert；`old_status_id`/`new_status_code` 字段）。
- 消费方清单：`grep -rn "mastery_decisions\|learner_node_status" learning_system/ --include="*.py"`（待 Task 2 执行并回填主要读写方）。

（骨架占位：Task 2 填充）

#### 裁定点

- 三张表是否满足"长期档案 append-only"需求？（预期结论：满足，无需新建 `node_mastery_log`，待核实）

（骨架占位：Task 2 填充）

#### 结论（或挂起原因）

（骨架占位：Task 2 填充；若存在未决点，标注"挂起待 X"）

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
