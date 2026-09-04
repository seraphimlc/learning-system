# 模块 ↔ 节点映射 Schema 提案

Date: 2026-08-20
Owner: 若命（软件架构）
Status: spec-draft（待评审）
Scope: `data/knowledge_graphs/math/math_knowledge_graph_v2.json` 的 `modules` ↔ `nodes` 关联契约化
对象：单个孩子的 AI 数学学习系统（数学优先，暑假衔接阶段）

> **一句话结论**：不新增任何映射字段，把每个节点**已存在**的 `taxonomy.module_id` 正式化为受校验的第一类 schema 契约（单一真源在节点侧），模块 → 节点列表作为**派生视图**由运行时按需生成（`graph_runtime` 已实现），不做双向存储。

---

## 目录

1. [背景](#1-背景)
2. [方案对比](#2-方案对比)
3. [推荐方案](#3-推荐方案)
4. [Schema](#4-schema)
5. [校验规则](#5-校验规则)
6. [映射表草案（domain → module）](#6-映射表草案domain--module)
7. [迁移步骤（56 节点回填）](#7-迁移步骤56-节点回填)
8. [对自动化消费的影响](#8-对自动化消费的影响)

---

## 1. 背景

### 1.1 问题来源

QA 报告（`docs/qa/knowledge_graph_v2_dependency_chain_qa.md`，修复/确认清单第 1 项）指出：图谱顶层 `modules` 字典（9 个模块，A_FOUNDATION … Z_LEARNING_PROCESS）每个条目只有 `{name, goal}`，属于"纯元数据"，按模块出题 / 诊断 / 计划无法直接消费，建议"节点加 module 字段，或 modules 加 nodes 列表"。

### 1.2 现状核对（关键事实，必须先说清楚）

对 v2 文件逐节点扫描后，**QA 的"节点无模块关联"结论在字面上不成立，但背后的问题真实存在**：

| 事实 | 证据 |
|---|---|
| **56/56 节点都已声明模块归属** | 每个节点都有 `taxonomy.module_id`，且全部命中 9 个模块 key（悬空引用 0） |
| **运行时已经在消费这个关联** | `learning_system/graph_runtime.py` 的 `graph_snapshot()` 由节点 `taxonomy.module_id` 现场派生 `module → nodes` 反向索引；`knowledge_map.py` / `knowledge_cards.py` / `question_bank.py` 均按 `taxonomy.module_id` 分组、选相似题 |
| **顶层 `modules` 字典没有任何代码读取** | 它是纯文档性目录；`graph_runtime` 甚至用节点的 `taxonomy.module_name` 作为模块名，与顶层 `modules[].name` 是**同一文件里的两份拷贝** |
| **缺的不是关联，而是"契约"** | 没有任何校验保证：`module_id` 必须命中 `modules` key、每个节点恰好一个模块、模块非空、`module_name` 与 `modules[].name` 一致。今天正确，纯属数据恰好一致，无人兜底 |

QA 的扫描只看了节点**顶层字段和 `tags`**，没有覆盖嵌套的 `taxonomy` 子对象，因此漏报了已存在的关联；但 QA 提出"显式声明、可消费"的方向是对的——当前状态是**隐性契约**：数据里有关联，schema 里没有约束，任何新增/编辑节点都可能悄悄破坏它。

### 1.3 需求定义

- **自动化可消费**：按模块枚举节点（出题选题）、按模块聚合诊断状态、按模块切片做计划，都应在**不扫描全部节点、不猜测**的前提下获得稳定结果。
- **可演进**：以后每新增一个节点，模块归属是必填且被校验的，回归能被测试拦住。
- **克制**：单孩系统、56 节点，不要版本化 schema 框架、不要引入新存储。

---

## 2. 方案对比

在既定事实（节点侧已有 `taxonomy.module_id`，运行时已按它派生反向索引）下对比三个候选：

| 维度 | A：节点加 `module` 字段 | B：`modules` 加 `nodes` 列表 | C：双向映射 |
|---|---|---|---|
| 自动化消费便利性 | 好：节点侧 O(1) 取模块；但"按模块枚举节点"仍需全扫或另建索引 | 好：模块侧直接枚举；但**只有**模块侧便利，节点侧查模块需反查 | 最好：两侧都 O(1) |
| 向后兼容（56 节点回填） | 差：`taxonomy.module_id` 已存在，再新增顶层 `module` 就是**第二份节点侧拷贝**，新增即引入漂移风险 | 差：`modules[].nodes` 需一次性手工/脚本生成，生成后即与节点侧**双份并存** | 最差：双份之外再翻倍 |
| 维护成本（新增节点改哪里） | 低（若只保留一份） | 高：新增节点要同时改节点和模块列表，漏一处即失同步 | 最高：三处（节点 + 模块列表 + 反向） |
| 与现有 schema 风格一致性 | 不一致：顶层节点字段列表（`node_fields`）没有 `module`，关联本就设计在 `taxonomy` 内 | 不一致：`modules` 条目只有 `{name, goal}`，塞入 `nodes` 列表改变其语义 | 最不一致 |
| 数据冗余 / 失同步风险 | 中（若保留两份节点侧引用） | 高（映射双份存储，手工维护必漂移） | 最高（三份） |
| 结论 | **推荐其变体（见 §3）** | 否 | 否（56 节点 / 单孩系统，明显过度设计） |

**否决 B / C 的核心理由**：映射是**派生数据**，不是**源数据**。模块 → 节点的对应关系唯一由"每个节点属于哪个模块"决定；把它存储成列表，就是在同一文件里维护两份事实，任何一方编辑漏掉另一方都会产生静默漂移——这正是 QA 已指出的 `module_name` 双份拷贝问题的放大版。

**为什么不是 A 的原始形态（新增顶层 `module` 字段）**：节点侧引用已存在于 `taxonomy.module_id`。再加一个顶层 `module` 字段 = 同一节点上两份模块引用，新增即引入漂移风险。正确做法是**把已有字段提升为契约**，而不是再复制一份。

---

## 3. 推荐方案

**推荐：A 的变体（下文称 A-refined）——单一真源在节点侧，反向索引为派生视图。**

三条原则：

1. **单一真源**：节点 ↔ 模块的归属，唯一权威是节点 `taxonomy.module_id`。**不新增任何映射字段**（不动 `nodes` 现有字段，也不给 `modules` 加 `nodes` 列表）。
2. **派生即消费**：`module → nodes` 反向索引由 `graph_runtime.graph_snapshot()` 现场派生（现状已如此，保持不动），若个别消费方需要"数据形态"的模块清单，由同一派生逻辑输出**生成物**（如 `artifacts/` 下），不落入 `data/`。
3. **契约兜底**：把映射关系写进 schema 约束 + 校验规则（§4、§5），任何破坏（悬空、空模块、重复名漂移、新节点漏声明）被一次性校验脚本拦住，并固化为回归测试。

具体动作清单（按依赖顺序）：

| # | 动作 | 类型 | 是否动 data/ |
|---|---|---|---|
| 1 | 现状核对：全量枚举 `taxonomy.module_id`，确认 56/56 有效 | 一次性校验 | 否（只读） |
| 2 | 在 `schema` 中补充 `module_id` 的契约说明（enum 指向 `modules` key） | 文档/契约 | 否（可选：改 schema 说明文字；不改数据） |
| 3 | 新增校验脚本（§5 R1–R6），产出结构化报告 | 脚本 | 否（只读） |
| 4 | 把 R1–R5 固化为回归测试（仿 `tests/test_knowledge_views_v51.py` 的 oracle 测试风格） | 测试 | 否 |
| 5 | （可选）由派生逻辑输出 `modules_with_nodes` 生成物，供后续 agent 直接读取 | 生成物 | 否（写入 `artifacts/` 而非 `data/`） |

---

## 4. Schema

### 4.1 不动的东西

- `nodes[]` 现有字段：**全部保留，不增不减**。
- `modules` 字典：条目保持 `{name, goal}`，**不添加 `nodes` 列表**。
- `schema.node_fields`：`taxonomy` 已在其中，无需改动（本提案只补充对 `taxonomy.module_id` / `module_name` 的**约束说明**，属于文档化既有事实）。

### 4.2 节点侧契约（`taxonomy` 子对象）

对每个节点，`taxonomy` 必须是对象，且满足以下契约（JSON Schema 片段，draft-07 子集）：

```json
{
  "taxonomy": {
    "type": "object",
    "required": ["module_id", "module_name"],
    "properties": {
      "module_id": {
        "type": "string",
        "pattern": "^[A-Z]_[A-Z]+(_[A-Z]+)*$",
        "description": "模块代码，必须命中顶层 modules 字典的 key（枚举以实际 modules keys 为准）"
      },
      "module_name": {
        "type": "string",
        "description": "模块显示名，必须与 modules[module_id].name 完全一致（见 R5）"
      },
      "chapter_anchor": { "type": "string" },
      "concept_type": {
        "type": "string",
        "enum": ["concept", "procedure", "model", "mixed", "process"]
      },
      "grain": { "type": "string", "enum": ["micro_concept"] }
    },
    "additionalProperties": false
  }
}
```

约束要点：

- `module_id`：**必填**、非空字符串、符合模块代码命名规范（§5 R1）、**必须是顶层 `modules` 的 key**（§5 R3）。
- `module_name`：必填、与 `modules[module_id].name` 完全一致（§5 R5）。保留该字段是为了不破坏现有消费者（`graph_runtime`、`knowledge_cards` 直接读它）；消除重复拷贝可留作后续清理，本提案不要求。
- `concept_type` / `grain`：枚举收紧，与现有 56 节点的取值分布一致（concept/procedure/model/mixed/process；grain 全部为 micro_concept）。

**示例节点（摘自现有数据，`M-G7-ABSOLUTE` 的 taxonomy 形态）：**

```json
{
  "id": "M-G7-ABSOLUTE",
  "name": "绝对值",
  "stage": "七上主线",
  "domain": "有理数",
  "priority": "P0",
  "taxonomy": {
    "module_id": "E_RATIONAL_NUMBERS",
    "module_name": "有理数概念与运算",
    "chapter_anchor": "七上第1章 有理数",
    "concept_type": "concept",
    "grain": "micro_concept"
  }
}
```

### 4.3 派生索引契约（`module → nodes`，非存储）

消费方拿到的模块侧视图（`graph_runtime.graph_snapshot()["modules"]` 现在的形态，作为派生契约固定下来）：

```json
{
  "modules": {
    "A_FOUNDATION": {
      "name": "底层计算与数感",
      "nodes": ["M-PRE-DECIMAL-OPS", "M-PRE-INTEGER-OPS", "M-PRE-NUMBER-SENSE", "M-PRE-ORDER-OPS"]
    },
    "E_RATIONAL_NUMBERS": {
      "name": "有理数概念与运算",
      "nodes": ["M-G7-ABSOLUTE", "M-G7-COMPARE", "M-G7-NUMBER-LINE", "M-G7-OPPOSITE", "M-G7-POS-NEG", "M-G7-POWER", "M-G7-RATIONAL-ADD-SUB", "M-G7-RATIONAL-CLASSIFY", "M-G7-RATIONAL-MIXED", "M-G7-RATIONAL-MUL-DIV", "M-G7-SCI-NOTATION-APPROX"]
    }
  }
}
```

规则：

- 该结构**只允许派生，不允许手工编辑**；派生源唯一为各节点 `taxonomy.module_id`。
- 模块集合、模块名以顶层 `modules` 字典为准；`nodes` 列表排序规则固定（按节点 id 字典序，与 `graph_runtime` 现状一致）。
- 若某个模块没有任何节点，派生结果中**不出现**该 key（等价于"空模块即失效"，见 §5 R4），校验报告单独列出。

---

## 5. 校验规则

| 编号 | 规则 | 级别 | 说明 |
|---|---|---|---|
| R1 | **模块代码命名规范** | 硬性 | 模块代码（`modules` 的 key 与节点 `taxonomy.module_id` 共用同一规范）匹配 `^[A-Z]_[A-Z]+(_[A-Z]+)*$`；首字母为单大写字母，当前取值域 A–H（学习顺序）+ Z（学习流程哨兵模块），I–Y 预留；不得为空、不得含小写/数字/中文 |
| R2 | **每个节点恰好属于一个模块** | 硬性 | 每个节点 `taxonomy.module_id` 存在、非空、为字符串；不允许缺失、空串、数组或"多模块"形态 |
| R3 | **无悬空引用** | 硬性 | 所有节点的 `taxonomy.module_id` 必须命中顶层 `modules` 的 key；`modules` 的每个 key 必须被至少一个节点引用（双向闭合，防幽灵模块与孤儿模块） |
| R4 | **模块非空** | 硬性 | 每个 `modules` key 至少关联 1 个节点（当前 9/9 非空：A=4, B=4, C=4, D=8, E=11, F=8, G=6, H=10, Z=1） |
| R5 | **名称一致性（防双份拷贝漂移）** | 硬性 | 每个节点 `taxonomy.module_name` 必须 `== modules[module_id].name`（当前 0 漂移）；顶层 `modules[].name` 是唯一权威，改模块名必须同步改 `modules` 与全部所属节点，校验拦住漏改 |
| R6 | **domain 一致性（软校验）** | 告警 | 节点 `domain` 值必须落在 §6 映射表草案的合法域内；跨模块 domain（数与运算/数与代数/应用建模）允许，但**不阻断**，仅输出告警提醒人工确认（domain 是粗粒度线索，模块归属以 `taxonomy.module_id` 为准） |

校验实现（一次性脚本思路，只读图谱、不写 `data/`）：

```
输入: math_knowledge_graph_v2.json
1. 读 modules keys → 校验 R1（命名规范、集合）
2. 遍历 nodes：
   - 校验 R2（module_id 存在且为字符串）
   - 校验 R3（module_id ∈ modules keys）
   - 校验 R5（module_name == modules[module_id].name）
   - 统计每个 module_id 的节点数 → 校验 R4（非空）
   - 校验 R6（domain 落在默认表内，否则记告警）
3. 输出结构化报告：{valid, errors[], warnings[], module_node_counts{}, missing_module_nodes[]}
4. 退出码：有 R1–R5 错误 → 非 0；仅有 R6 告警 → 0
```

固化为回归测试时，直接扩展现有 oracle 测试风格（`tests/test_knowledge_views_v51.py::test_authoritative_graph_oracle_is_56_nodes_9_modules_95_strict_edges`），新增断言：56 节点全部命中 9 个 modules key、模块计数 = {A:4,B:4,C:4,D:8,E:11,F:8,G:6,H:10,Z:1}、`module_name` 与顶层一致。

---

## 6. 映射表草案（domain → module）

基于现有 13 个 `domain` 取值 → 9 个模块（以节点 `taxonomy.module_id` 的实际分布为准，56 节点全部覆盖）：

| # | domain（现有取值） | 节点数 | 目标模块 | 节点 id 前缀示例 |
|---|---|---|---|---|
| 1 | 数与运算 | 7 | **A_FOUNDATION（4）+ B_FRACTION_RATIO（3）** ⚠️跨模块 | 整数/小数/数感/运算顺序 → A；分数意义/分数运算/百分数 → B |
| 2 | 数与代数 | 4 | **B_FRACTION_RATIO（1）+ C_ALGEBRA_BRIDGE（3）** ⚠️跨模块 | 比和比例 → B；分配律/小学方程/字母表示 → C |
| 3 | 应用建模 | 8 | **C_ALGEBRA_BRIDGE（1）+ D_WORD_MODELS（7）** ⚠️跨模块 | 数量关系 → C；读题/行程/和差倍/百分数模型等 → D |
| 4 | 应用建模/几何 | 1 | D_WORD_MODELS | 钟面角（几何语境的建模题归 D） |
| 5 | 有理数 | 6 | E_RATIONAL_NUMBERS | 正负数/数轴/相反数/绝对值/比较/分类 |
| 6 | 有理数运算 | 5 | E_RATIONAL_NUMBERS | 加减/乘除/混合/乘方/科学记数法 |
| 7 | 代数式与整式 | 4 | F_EXPRESSIONS | 代数式/求值/单项式/多项式 |
| 8 | 整式加减 | 4 | F_EXPRESSIONS | 同类项/合并/去括号/加减 |
| 9 | 一元一次方程 | 6 | G_LINEAR_EQUATION | 方程概念/等式性质/求解/去分母/去括号/应用题 |
| 10 | 几何图形初步 | 7 | H_GEOMETRY_INTRO | 点线面/立体与平面/线段/角/计算/视图 |
| 11 | 图形与几何 | 2 | H_GEOMETRY_INTRO | 角基础/面积体积（小学前置） |
| 12 | 图形与量 | 1 | H_GEOMETRY_INTRO | 单位换算 |
| 13 | 学习流程 | 1 | Z_LEARNING_PROCESS | 解题步骤与检验习惯 |

**使用说明：**

- **`domain` 是粗粒度线索，模块归属永远以 `taxonomy.module_id` 为准。** 本表只解决两件事：① 新增节点时的默认建议（新节点若 `module_id` 缺失，用本表从 `domain` 推导默认值并置为待确认）；② 校验 R6 的告警依据。
- 3 个跨模块 domain（第 1、2、3 行）说明 domain 粒度与模块粒度不对齐——这正是"不能只用 domain 做模块映射"的证据，也是 §2 否决"纯 tags/domain 推断"方案的原因。
- 该表**不是数据文件**，是本文档内的设计约定；若未来 domain 枚举收敛，可逐步消除跨模块行（不属于本次范围）。

---

## 7. 迁移步骤（56 节点回填）

**先说结论**：56 个节点**已经完成归属声明**（`taxonomy.module_id` 全覆盖、0 悬空），本任务不是"从零回填"，而是"把隐性契约变成显性契约"。迁移 = 一次只读核对 + 契约固化 + 派生索引验证，**不修改 `data/` 下任何文件**。

一次性脚本思路（只读，按顺序执行）：

1. **快照核对**：加载图谱，枚举全部 56 节点，断言每个节点 `taxonomy.module_id` 存在且命中 `modules` key；缺失/非法的节点列入 `missing[]`（预期为空）。
2. **权威值对齐**：对每个节点，取 `taxonomy.module_id` 为权威归属；对 `missing[]` 中（若有）的节点，按 §6 表从 `domain` 推导默认模块并**标记为待人工确认**（脚本只输出建议，不写回）。
3. **一致性校验**：执行 §5 R1–R6，输出结构化报告；核对模块节点数 = {A:4,B:4,C:4,D:8,E:11,F:8,G:6,H:10,Z:1}，`module_name` 漂移 = 0。
4. **派生索引验证**：用 `graph_runtime.graph_snapshot()` 生成 `module → nodes` 派生视图，断言与步骤 3 的计数一致（验证派生逻辑与契约同构）。
5. **契约固化**：将 R1–R5 固化为回归测试（见 §5），此后任何新增/编辑节点若破坏映射，CI 或本地测试即失败。
6. **（可选）生成物输出**：把派生模块索引导出到 `artifacts/`（如 `modules_with_nodes.v2.json`，含 lineage），供后续 agent 直接读取；**不落 `data/`**，且标注"生成物、以图谱为准、勿手工编辑"。

验收标准：

| 项 | 通过标准 |
|---|---|
| 节点覆盖 | 56/56 节点有合法 `module_id` |
| 无悬空/无孤儿 | 引用双向闭合（R3） |
| 模块非空 | 9/9 模块节点数 = 上文分布（R4） |
| 名称零漂移 | `module_name` 与 `modules[].name` 全等（R5） |
| 回归防护 | R1–R5 已固化为测试，破坏即红 |

---

## 8. 对自动化消费的影响

契约化之后（数据本身不变，变的只是"有保障"），各自动化链路获得的能力：

| 消费场景 | 现状 | 契约化后 |
|---|---|---|
| **按模块出题** | `question_bank` 已按 `taxonomy.module_id` 做变式相似度隔离（同模块候选优先），但无校验兜底 | 按模块枚举节点 = 直接读派生索引；新节点漏声明会被 R2 拦住，不会出现"模块内选题漏掉某节点" |
| **按模块诊断** | `diagnostic_blueprint.blocks` 是手写的"模块近似"节点分组（如"计算与运算规则""分数百分数与单位1"），与模块无派生关系，可能漂移 | blocks 可改为**由模块派生**（A→计算块、B→分数块、C→代数桥块、D→模型块），决策规则（A/B/C/D 状态 → 回退/推进）按模块聚合；手写分组与模块之间的漂移被消除 |
| **按模块计划** | 计划按节点推进，无模块粒度视图 | `planner` 可按模块切片（某模块薄弱 → 整模块补漏）、按模块汇总覆盖进度与薄弱分布 |
| **知识地图** | `knowledge_map` 已按模块分组展示（mind_map 模块父节点 = `taxonomy.module_id`，且有测试兜底） | 模块集合与顺序的权威来源明确 = 顶层 `modules` 派生，避免"展示用模块"与"教研用模块"两套口径 |
| **图谱演进** | 新增节点可绕过任何模块约束 | 新增节点必须声明合法 `module_id` 才能通过校验，模块生态保持闭合 |

**对后续 agent 的约定**：任何读取图谱的 agent（出题、诊断、规划、知识卡）一律以「节点 `taxonomy.module_id` + 派生模块索引」为唯一事实来源；顶层 `modules` 只提供 `name/goal` 目录语义，不再需要它承载映射。

---

## 附：与 QA 报告的关系

本提案不推翻 QA 的结论，而是**修正其事实前提并落地其意图**：QA 第 1 项"模块 ↔ 节点映射缺失"应更新为"映射存在于 `taxonomy.module_id`（56/56，QA 扫描未覆盖嵌套字段），缺失的是**显式 schema 契约、校验与模块侧可枚举保证**"。建议同步更新 `docs/qa/knowledge_graph_v2_dependency_chain_qa.md` 修复清单第 1 项的状态与表述（该更新属于文档修改，与本提案的 data/ 只读约束不冲突）。
