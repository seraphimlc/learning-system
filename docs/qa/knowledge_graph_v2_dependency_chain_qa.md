# 数学知识图谱 v2 依赖链完整性 QA 报告

- 检查对象：`data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- 检查日期：2026-07（Goal 演示，第 1-2 轮产出）
- 检查方式：脚本全量扫描 + 人工复核原始结构
- 检查维度：结构完整性（悬空引用/孤立节点/环）→ 引用一致性（learning_path/modules）→ 教学合理性观察

## 结论摘要

| 维度 | 结果 |
|---|---|
| 结构性缺陷（悬空引用/孤立节点/环） | **0 项**，图谱结构健康 |
| 引用一致性（learning_path / modules） | **0 项真实缺陷**（初扫有 13 项疑似，人工复核后确认均为脚本误报） |
| 待确认项（设计层） | 2 项均已查实：1 项为 QA 误报（模块映射实际存在于 `taxonomy.module_id`），1 项确认无缺陷 |
| 教学合理性观察 | ✅ 已评审（24 节点强弱评审完成，见 `knowledge_graph_prereq_strength_review.md`） |

## 详细发现

### 1. 结构完整性：全部通过 ✅

- 节点总数：56；`prerequisites` / `unlocks` 悬空引用：0
- `edges` / `prerequisite_edges` 边表悬空引用：0
- 完全孤立节点（无前置、无解锁、无边）：0
- 32 个七上（G7）节点全部可回溯到无前置的根节点，无环、无断链

### 2. 引用一致性：初扫误报已排除 ✅

- `learning_path` 实际是 dict（`daily_time_minutes` / `math_priority` / `phase_strategy` / `session_template`），是**顶层规划配置**，不是节点引用列表——初扫将其当 list 遍历导致的 13 项"疑似悬空"全部为误报。
- `modules` 是 dict（9 个模块代码 → `{name, goal}`），本身不含节点映射，无引用问题。

### 3. 待确认项（设计层，需产品确认，非缺陷）

1. **`modules` 与节点的映射不在 v2 文件内**：9 个模块（A_FOUNDATION … Z_LEARNING_PROCESS）只有 name/goal，没有 `nodes` 字段。若模块→节点对应关系依赖 `tags`/`domain` 字段或外部文档，建议在文件中显式声明，否则后续自动化（如按模块出题、按模块诊断）无法直接消费。
2. **`learning_path` 的 `phase_strategy` 提到"只补 P0 薄弱前置"**，但节点上的 `priority` 字段是否与诊断状态（A/B/C/D）联动、由哪个 agent 写入，v2 文件内未体现——建议与 `diagnosis_state_model` 的对接文档核对。

### 4. 教学合理性观察（第 2 轮修正 + 深入）

> 第 1 轮曾报告"前置图接近全连通（35 个根）"，第 2 轮复核确认该结论**不准确**：那是脚本传递闭包重复计数导致的假象。直接边密度实际很健康（95 条前置边，平均 1.7/节点，中位 2，最大 5）。

**修正后的真实测量：**

- **直接前置边密度健康**：无节点前置数超过 5（`M-G7-EQ-WORD` 为最大，5 个）。
- **但"回查范围"（传递闭包去重后可达前置数）对顶层节点偏宽**：
  - `M-G7-EQ-WORD`：25 个可达前置
  - `M-G7-EQ-PAREN`：20、`M-G7-POLY-ADD-SUB`/`M-G7-EQ-DENOM`：18、`M-G7-EXPR-VALUE`/`M-G7-EQ-SOLVE`：17
  - 含义：这些节点错题时，理论上的错因回查候选面很大（虽非全连通，但覆盖面宽）。若回退时不排序，诊断 agent 会在宽候选面上低效试探。
- **关键枢纽节点**：`M-PRE-QUANTITY-RELATION`（数量关系）仅依赖 `M-PRE-INTEGER-OPS`（整数四则计算），却**解锁 11 个下游节点**（含 6 个衔接桥梁模型 + `M-G7-EQ-WORD` + `M-G7-ALG-EXPR`）。它是全图影响面最大的节点——与 AGENTS.md"只补会影响七上学习的前置节点"直接相关，应作为**最高杠杆诊断节点**优先建档。

**建议（教学合理性待议，非缺陷）：**

1. 节点上加 `prereq_strength: strong|soft`（或在边表标注）：`strong` = 缺它必然卡住，回查优先；`soft` = 学过更好，不作为回退触发。
2. 对 `M-G7-EQ-WORD` 的 5 个直接前置做一次教研评审：其中 3 个是 P1 衔接模型（和差倍/行程/百分数），确认它们是否都是"强前置"——这决定回退链的优先级排序。
3. 将 `M-PRE-QUANTITY-RELATION` 列为试点诊断的首选节点（其下游 11 节点全部受益）。

### 5. 第 2 轮新增确认（原待确认项已查实）

1. **`modules` ↔ 节点映射：第 2 轮误报，第 3 轮核实已纠正**。56/56 节点均带 `taxonomy.module_id` 且全部命中 9 个模块 key（0 悬空），`learning_system/graph_runtime.py` 已按它派生 module→nodes 反向索引，`knowledge_map.py` / `question_bank.py` / `knowledge_cards.py` / `knowledge_card_generation.py` / `knowledge_view_config.py` 共 6 处消费。第 2 轮只扫顶层字段和 `tags`、漏掉嵌套 `taxonomy` 导致误报。**真正剩余缺口**：顶层 `modules` 字典无 schema 契约与校验（`module_name` 与 `modules[].name` 是同文件双份拷贝，今天 0 漂移但无人兜底）。→ 修复提案见 `docs/design/specs/module_node_mapping_proposal.md`（推荐：不动数据，把 `taxonomy.module_id` 固化为受校验的 schema 契约 + 6 条校验规则 + 回归测试）。
2. **`priority` 与诊断联动：确认无缺陷**。`priority` 已被 `scripts/activate_three_node_pilot.py` 消费（节点试点选择）；`diagnosis_state_model` 定义 A/B/C/D 状态与回退规则（C 回退前置、D 暂停七上补最早断点），与 `priority` 无冲突、无缺口。

## 修复 / 确认清单（第 4 轮更新：两项已落地）

| # | 类型 | 状态 | 动作 | 责任人建议 |
|---|---|---|---|---|
| 1 | 契约固化 | ✅ **已落地** | 校验器 `learning_system/graph_contract.py`（R1–R6，`python3 -m learning_system.graph_contract` 独立运行）+ 回归测试 `tests/test_knowledge_graph_contract.py`（13 例全绿）；`taxonomy.module_id` 契约（56/56、双向闭合、零漂移）有兜底 | 图谱维护 |
| 2 | 设计确认 | ✅ 已确认无缺陷 | `priority` 由试点脚本消费，与诊断状态模型无冲突 | — |
| 3 | 教学评审 | ✅ **已落地（首期回填）** | 评审结论见 `knowledge_graph_prereq_strength_review.md`；55 条 phase-1 出边已完成标记（49 strong / 6 soft，含 UNIT-CONVERSION→SEGMENT-MEASURE 强例外），`strong_unlock_edges` 4 条；校验器新增 R7 守卫；图谱 `graph_lineage` 变更已同步到视图配置 v5.1 的版本戳。一次性回填脚本已清理 | 教研（二轮评审仍待排期） |
| 4 | 产品建议 | ✅ 已被评审采纳 | `M-PRE-QUANTITY-RELATION` 确认为全图枢纽，评审列为回查 Tier S 首位 | 产品/agent |

> 本报告第 1 轮：结构完整性全量扫描（0 缺陷）。第 2 轮：修正密度误判、确认 priority 消费链路、识别枢纽节点。第 3 轮：纠正"模块映射缺失"误报（映射实际存在于 `taxonomy.module_id`），前置强弱评审完成。第 4 轮：校验器 + 回归测试落地（清单 #1）、prereq_strength 首期回填落地（清单 #3）。
