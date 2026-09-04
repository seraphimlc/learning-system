# 数学知识图谱 v2 前置依赖强弱评审总结（prereq_strength 教研评审）

- 评审角色：教研组长
- 评审对象：`data/knowledge_graphs/math/math_knowledge_graph_v2.json`（56 节点 / 225 边 / 95 条前置依赖边）
- 评审范围：24 个前置节点 = 全部 15 个小学关键前置（M-PRE-*）+ 全部 9 个衔接桥梁（M-BRIDGE-*），占前置节点 100%
- 前置依据：24 节点逐条评审 JSON（每节点含 classification / suggested_strength / rationale / downstream_risk）
- 事实核查：评审中引用的全部前置边、掌握标准、错因回退、priority 均已与图谱 v2 原始数据核对，**无事实性错误**（详见第 4 节）
- 关联文档：`docs/qa/knowledge_graph_v2_dependency_chain_qa.md` 修复清单 #3「待教研：加 prereq_strength；评审 M-G7-EQ-WORD 5 个直接前置的强弱」——本文档即该待办项的教研结论

---

## 1. 结论摘要表

| 项目 | 结果 |
|---|---|
| 评审节点数 | 24（小学关键前置 15 + 衔接桥梁 9） |
| 判定 **strong** | **16**（直接判 strong 7 + mixed→strong 9） |
| 判定 **soft** | **8**（直接判 soft 3 + mixed→soft 5） |
| 保留 mixed | 0（14 个 mixed 全部收敛到二值，但**收敛依据不统一**，见分歧点） |
| 分歧 / 不一致 | 4 类（同链相邻节点反向、边表与语义不对齐、节点级/边级度量混淆、EQ-WORD 五前置两强一弱） |
| 事实核查 | 24 条评审引用边全部与图谱一致，无事实错误 |
| **是否新增 prereq_strength** | **值得加**（QA 待办 #3 落地） |
| **放节点级还是边级** | **边级为主**（`prerequisite_edges` 加字段）+ 节点级派生 `diagnosis_priority` |
| 默认值 | **soft**（未标注 = soft = 不触发回退），同一变更中显式回填全部相关边 |
| 回查优先级 | Tier S 8 节点 / Tier A 4 节点 / Tier B 5 节点 / Tier C 7 节点（见第 5 节） |

### strong 名单（16）
M-PRE-NUMBER-SENSE、M-PRE-INTEGER-OPS、M-PRE-ORDER-OPS、M-PRE-FRACTION-OPS、M-PRE-EQUATION-BASIC、M-PRE-QUANTITY-RELATION、M-PRE-LETTER-EXPR、M-PRE-FRACTION-MEANING、M-PRE-DECIMAL-OPS、M-BRIDGE-SOLUTION-HABIT、M-PRE-DISTRIBUTIVE、M-BRIDGE-WORD-PROBLEM-READING、M-BRIDGE-SUM-DIFF-MULTIPLE、M-BRIDGE-MOTION-BASIC、M-PRE-ANGLE-BASIC、M-PRE-PERCENT

### soft 名单（8）
M-PRE-RATIO-PROP、M-BRIDGE-MOTION-CHASE、M-BRIDGE-PERCENT-MODEL、M-BRIDGE-PROPORTION-MODEL、M-BRIDGE-CLOCK-ANGLE、M-BRIDGE-WORK-RATE、M-PRE-GEO-AREA-VOLUME、M-PRE-UNIT-CONVERSION

### 模式观察
- **strong 节点全部是 P0 / 暑假核心**（16 个 strong 中 13 个 P0+core，3 个 P1：SUM-DIFF-MULTIPLE、MOTION-BASIC、ANGLE-BASIC 均因"特定 G7 题型硬前置"入选）。
- **soft 节点全部是 P1/P2 或 diagnose_only**（8 个 soft 中 6 个 P1、2 个 P2），且全部是"影响面窄（直接解锁 ≤1 个 G7）或可绕行"。
- **唯一的反例**：M-PRE-PERCENT（P1、selective_core）判 strong——因为它对应的销售/折扣分支无替代路径；M-PRE-GEO-AREA-VOLUME（P1、diagnose_only）判 soft——因为其唯一下游 GEO-SOLID-PLANE 是识别向。说明"优先级高低"与"强度"是两个维度。

---

## 2. 逐节点评审建议（24 节点明细）

| # | 节点 | 评审分类 | 建议强度 | 一句话依据 | 回查层级 |
|---|---|---|---|---|---|
| 1 | M-PRE-NUMBER-SENSE | mixed | **strong** | 无前置根节点、权重 3；32 个 G7 可达（全图最大）；近似数即量感应用、离谱错检器 | S |
| 2 | M-PRE-INTEGER-OPS | mixed | **strong** | RATIONAL-ADD-SUB 直接前置边；有理数运算执行本质即整数四则；26 个 G7 可达 | S |
| 3 | M-PRE-ORDER-OPS | strong | **strong** | RATIONAL-MIXED 直接前置（本质=小学运算顺序+符号）；全计算链咽喉 | S |
| 4 | M-PRE-FRACTION-OPS | strong | **strong** | MUL-DIV 与 EQ-DENOM 双直接前置边；约分/倒数/带分数即其内核 | S |
| 5 | M-PRE-QUANTITY-RELATION | strong | **strong** | 11 个直接下游（全图枢纽，QA 报告已点名最高杠杆）；EQ-WORD+ALG-EXPR 双主线 | S |
| 6 | M-PRE-EQUATION-BASIC | strong | **strong** | EQUALITY-PROP 唯一前置；方程链根，薄弱整链瘫痪 | S |
| 7 | M-PRE-LETTER-EXPR | strong | **strong** | ALG-EXPR 唯一小学前置；文字译代数式无替代路径 | S |
| 8 | M-PRE-FRACTION-MEANING | mixed | **strong** | EQ-WORD"单位1"语义强依赖（仅 unlocks 边）；CLASSIFY 侧弱 | S |
| 9 | M-PRE-DECIMAL-OPS | mixed | **strong** | RATIONAL-MIXED"分数小数混合"题型强依赖（仅 unlocks 边）；EQ-DENOM 侧弱 | A |
| 10 | M-BRIDGE-SOLUTION-HABIT | mixed | **strong** | EQ-SOLVE/EQ-WORD 掌握标准直含"代回检验/完整设列"；4 个 G7 直接解锁 | A |
| 11 | M-PRE-DISTRIBUTIVE | strong | **strong** | PARENTHESIS 直接前置；负号分配规则直接映射 | A |
| 12 | M-BRIDGE-WORD-PROBLEM-READING | mixed | **strong** | EQ-WORD 前置首项 + 错因回退首顺位（"回应用题审题流程"） | A |
| 13 | M-BRIDGE-SUM-DIFF-MULTIPLE | mixed | **strong** | EQ-WORD 直接前置；"设一倍量→等量关系"即方程建模入口 | B |
| 14 | M-BRIDGE-MOTION-BASIC | mixed | **strong** | EQ-WORD 行程主干；追及→钟表角→角度计算链路源头 | B |
| 15 | M-PRE-ANGLE-BASIC | mixed | **strong** | ANGLE（P0）直接前置；角度链根，连锁阻塞 ANGLE-CALC | B |
| 16 | M-PRE-PERCENT | strong | **strong** | 百分数建模无替代路径；销售/打折/增长率必卡（但影响面仅 1 个 G7） | B |
| 17 | M-PRE-UNIT-CONVERSION | mixed | **soft** | SEGMENT-MEASURE 边强（直接前置、错因"单位不统一"）、EQ-WORD 侧弱；正确性补丁非概念门槛 | B* |
| 18 | M-BRIDGE-MOTION-CHASE | mixed | **soft** | CLOCK-ANGLE 硬、EQ-WORD 行程子类硬，但主线可绕行；unlocks-only | C |
| 19 | M-BRIDGE-PERCENT-MODEL | mixed | **soft** | 仅销售/打折分支强，且可经 M-PRE-PERCENT 直达 EQ-WORD 绕开 | C |
| 20 | M-PRE-GEO-AREA-VOLUME | mixed | **soft** | GEO-SOLID-PLANE 唯一前置但为识别向；强公式下游是 P2 可选 | C |
| 21 | M-BRIDGE-PROPORTION-MODEL | soft | **soft** | 增强非硬闸；RATIO-PROP 直连旁路可达 | C |
| 22 | M-BRIDGE-WORK-RATE | soft | **soft** | P2 可选；工程仅 EQ-WORD 五题型之一，可由分数意义+数量关系习得 | C |
| 23 | M-BRIDGE-CLOCK-ANGLE | soft | **soft** | P2 受控拓展；ANGLE-CALC 前置不含它（仅 unlocks） | C |
| 24 | M-PRE-RATIO-PROP | mixed | **soft** | 对 PROPORTION-MODEL 硬、对 EQ-WORD 可绕行；P1 诊断二级 | C |

> B*：M-PRE-UNIT-CONVERSION 节点级为 soft（不作全局回退触发），但其 **SEGMENT-MEASURE 一条边**应为 strong——这正是"必须放边级"的典型证据。

---

## 3. 分歧点与评审不一致之处

### 3.1 同链相邻节点强弱方向不一致（判定粒度不统一）
- **M-PRE-PERCENT（strong）↔ M-BRIDGE-PERCENT-MODEL（soft）**：前者判"百分数建模无替代路径、折扣/增长率必卡"，后者判"仅是 EQ-WORD 五前置之一、销售分支可绕行"。同一销售/打折分支被同时判"必卡"与"可绕行"。可调和（概念层无替代、模型桥层可被概念直达覆盖），但口径不统一，容易让诊断 agent 无所适从。
- **M-PRE-RATIO-PROP（soft）↔ M-PRE-PERCENT（strong）**：两节点结构完全对称（均为 P1、selective_core、仅 unlocks EQ-WORD、经桥梁接入），结论却相反。分歧根源是：PERCENT-MODEL 在 EQ-WORD 的 `prerequisites` 边表中（5 前置之一），PROPORTION-MODEL 不在。**说明"强弱"本质由下游 G7 节点的边表地位决定，而非节点自身属性**——这是支持边级建模的最强证据。

### 3.2 EQ-WORD 五个直接前置内部两强一弱（需统一标准）
M-BRIDGE-WORD-PROBLEM-READING（strong）、M-BRIDGE-SUM-DIFF-MULTIPLE（strong）、M-BRIDGE-MOTION-BASIC（strong）、M-BRIDGE-PERCENT-MODEL（soft）同为 EQ-WORD `prerequisites` 列表成员，结构地位完全平等，却评出两强一弱（另一成员 M-G7-EQ-SOLVE 是 G7 节点，不在本评审范围）。评审依据分别是"方程建模入口 / 必考主干 / 仅一分支"——属**主观频率与可替代性判断，无统一量化标准**。建议二轮评审时按统一规则复核（见 6.3 判定规则）。

### 3.3 边表类型与语义强度不对齐（规则无法自动推导）
- **unlocks-only 边判 strong**（4 例）：FRACTION-MEANING→EQ-WORD（单位1）、DECIMAL-OPS→RATIONAL-MIXED（分数小数混合）、SOLUTION-HABIT→EQ-SOLVE/EQ-WORD（掌握标准直含）、NUMBER-SENSE→POS-NEG（七上入口）。
- **prerequisites 边判 soft**（1 例）：GEO-AREA-VOLUME→GEO-SOLID-PLANE（唯一前置但目标识别向）。
- 结论：**不能以"是否存在 prerequisites 边"代替强度判定**；95 条前置边需逐条语义评审。这既是"必须人工教研"的证据，也是 prereq_strength 字段存在的价值。

### 3.4 节点级与边级度量混淆（14 个 mixed 的共同根源）
多处"总体偏 soft"实为"对某些下游强、另一些弱"（UNIT-CONVERSION：SEGMENT-MEASURE 强/EQ-WORD 弱；GEO-AREA-VOLUME：GEO-VIEWS 计算强/识别链弱；MOTION-CHASE：CLOCK-ANGLE 硬/EQ-WORD 行程子类硬/主线可绕）。评审把"是否作全局回退触发"（操作优先级）与"缺它是否卡死某下游"（语义强度）混在一个"节点强弱"字段里。**解决方式：语义强度放边级，节点级只保留派生后的回查优先级。**

---

## 4. 事实核查记录（评审引用边 ↔ 图谱 v2 原始数据）

| 评审断言 | 图谱核实 |
|---|---|
| EQ-WORD 五前置 = 审题/EQ-SOLVE/和差倍/行程/百分数模型 | ✅ `M-G7-EQ-WORD.prerequisites` 完全一致 |
| ANGLE-CALC 前置不含 CLOCK-ANGLE（仅 unlocks） | ✅ 前置为 ANGLE + SEGMENT-MEASURE |
| GEO-SOLID-PLANE 唯一前置 = GEO-AREA-VOLUME | ✅ |
| EQUALITY-PROP 唯一前置 = EQUATION-BASIC | ✅ |
| RATIONAL-MUL-DIV、EQ-DENOM 直接前置含 FRACTION-OPS | ✅ |
| RATIONAL-ADD-SUB 直接前置含 INTEGER-OPS | ✅ |
| PARENTHESIS 直接前置含 DISTRIBUTIVE | ✅ |
| SCI-NOTATION-APPROX 直接前置含 NUMBER-SENSE | ✅ |
| SEGMENT-MEASURE 直接前置含 UNIT-CONVERSION | ✅ |
| ANGLE 直接前置含 ANGLE-BASIC；ALG-EXPR 前置含 LETTER-EXPR + QUANTITY-RELATION | ✅ |
| RATIONAL-CLASSIFY 前置含 FRACTION-MEANING（补救=分数小数互化） | ✅ |
| CLOCK-ANGLE 前置含 ANGLE-BASIC + MOTION-CHASE | ✅ |
| PERCENT-MODEL 前置首位 = PERCENT；PROPORTION-MODEL 前置首位 = RATIO-PROP | ✅ |
| EQ-WORD 补救首项 = "回应用题审题流程" | ✅ |

评审输入**无事实性错误**；全部不一致均属判定口径（第 3 节），非数据错误。

---

## 5. 错因回查优先级 Top 排序（薄弱时最值得先诊断、先补）

排序依据 = ①建议强度（strong 优先）②可达 G7 节点数（传递闭包）③可达 P0 节点数 ④正式前置边数（是否在 G7 节点 prerequisites 中）⑤是否直达 EQ-WORD/RATIONAL-MIXED/ALG-EXPR 主线枢纽。

> 同链规则：七上错题先查"离错题最近且为 strong 的边"；暑假诊断先补"链最底层根节点"（如 NUMBER-SENSE 先于 ORDER-OPS 补）。

| 优先级 | 节点 | 直接解锁G7 | 正式前置边 | 可达G7 | 可达P0 | 关键下游 |
|---|---|---|---|---|---|---|
| **S1** | M-PRE-NUMBER-SENSE | 2 | 2 | 32 | 22 | POS-NEG 入口、SCI-NOTATION-APPROX、EQ-WORD/RM/ALG |
| **S2** | M-PRE-INTEGER-OPS | 2 | 1 | 26 | 16 | RATIONAL-ADD-SUB 直接前置 |
| **S3** | M-PRE-ORDER-OPS | 3 | 1 | 17 | 11 | RATIONAL-MIXED 直接前置（全链咽喉） |
| **S4** | M-PRE-FRACTION-OPS | 3 | 2 | 10 | 7 | MUL-DIV、EQ-DENOM 双直接前置 |
| **S5** | M-PRE-QUANTITY-RELATION | 2 | 1 | 14 | 10 | 11 直接下游枢纽、EQ-WORD+ALG-EXPR |
| **S6** | M-PRE-EQUATION-BASIC | 3 | 2 | 6 | 5 | EQUALITY-PROP 唯一前置，方程链根 |
| **S7** | M-PRE-LETTER-EXPR | 2 | 1 | 13 | 10 | ALG-EXPR 唯一小学前置 |
| **S8** | M-PRE-FRACTION-MEANING | 2 | 1 | 15 | 12 | EQ-WORD 单位1（语义强，unlocks-only） |
| **A9** | M-PRE-DECIMAL-OPS | 2 | 0 | 14 | 8 | RATIONAL-MIXED 分数小数混合（语义强） |
| **A10** | M-BRIDGE-SOLUTION-HABIT | 4 | 0 | 8 | 6 | EQ-SOLVE/EQ-WORD 掌握标准直含检验 |
| **A11** | M-PRE-DISTRIBUTIVE | 2 | 1 | 4 | 4 | PARENTHESIS 直接前置，整式链 |
| **A12** | M-BRIDGE-WORD-PROBLEM-READING | 1 | 1 | 2 | 1 | EQ-WORD 前置首项 + 回退首顺位 |
| **B13** | M-BRIDGE-SUM-DIFF-MULTIPLE | 1 | 1 | 1 | 1 | EQ-WORD 和差倍入口 |
| **B14** | M-BRIDGE-MOTION-BASIC | 1 | 1 | 2 | 1 | EQ-WORD 行程主干 |
| **B15** | M-PRE-ANGLE-BASIC | 1 | 1 | 2 | 1 | ANGLE（P0）直接前置 |
| **B16** | M-PRE-PERCENT | 1 | 0 | 1 | 1 | EQ-WORD 销售/折扣分支（强但窄） |
| **B17** | M-PRE-UNIT-CONVERSION | 2 | 1 | 8 | 3 | SEGMENT-MEASURE 强边（仅该边回查） |
| **C18** | M-BRIDGE-MOTION-CHASE | 1 | 0 | 2 | 1 | 追及子类 + CLOCK-ANGLE |
| **C19** | M-BRIDGE-PERCENT-MODEL | 1 | 1 | 1 | 1 | 销售/打折子类（可绕行） |
| **C20** | M-PRE-GEO-AREA-VOLUME | 1 | 1 | 7 | 2 | GEO-SOLID-PLANE 识别向 |
| **C21** | M-BRIDGE-PROPORTION-MODEL | 1 | 0 | 1 | 1 | 配套/调配子类（旁路可达） |
| **C22** | M-BRIDGE-WORK-RATE | 1 | 0 | 1 | 1 | 工程子类（P2） |
| **C23** | M-BRIDGE-CLOCK-ANGLE | 1 | 0 | 1 | 0 | P2 受控拓展 |
| **C24** | M-PRE-RATIO-PROP | 1 | 0 | 1 | 1 | 比例思想（旁路可达） |

### 使用口径
- **Tier S（S1–S8）**：暑假诊断的首批 8 节点；任一薄弱 → 立即补，且七上任何计算/方程/代数错题都先沿此梯队回查。
- **Tier A（A9–A12）**：错因明确指向（掌握标准、错因回退明写）时的优先回查对象；SOLUTION-HABIT 应在"方程不检验/应用题漏单位"时第一时间查。
- **Tier B（B13–B17）**：仅对应题型出错时回查（和差倍/行程/角度/销售/单位换算）；不作全局回退触发。
- **Tier C（C18–C24）**：选择性诊断；仅当对应子题型（追及、配套调配、工程、钟表角）连续出错时按需补，不占用主线时间。

---

## 6. prereq_strength 字段提案

### 6.1 结论：值得加，放**边级**为主

**是否值得**：值得。依据：①QA 报告待办 #3 已建议；②24 节点中 14 个 mixed，节点级单值信息损失大；③强度本质是"边"的语义（同一节点对不同下游强弱不同）；④无该字段时，EQ-WORD 有 25 个可达前置，回查候选面过宽（QA 报告已指出），诊断 agent 无法排序。

**放节点级还是边级**：**边级**。理由：
1. 14/24 mixed 节点证明同一节点对不同下游强弱不同（UNIT-CONVERSION：SEGMENT-MEASURE 强、EQ-WORD 弱），节点级单值无法表达。
2. 现有 `prerequisite_edges` 表（from/to/type）加字段零破坏、零迁移。
3. 节点级"回查优先级"应作为**派生字段**（脚本从边级聚合），不手维护。

### 6.2 推荐 schema（边级主 + 节点级派生，最小侵入）

```json
{
  "prerequisite_edges": [
    {
      "from": "M-PRE-FRACTION-OPS",
      "to": "M-G7-RATIONAL-MUL-DIV",
      "type": "prerequisite",
      "prereq_strength": "strong",
      "strength_rationale": "分数乘除（约分、倒数、带分数）即有理数乘除的运算内核，缺则必卡"
    },
    {
      "from": "M-PRE-GEO-AREA-VOLUME",
      "to": "M-G7-GEO-SOLID-PLANE",
      "type": "prerequisite",
      "prereq_strength": "soft",
      "strength_rationale": "唯一前置但目标为识别向，缺公式不卡识别与概念主线"
    }
  ],
  "strong_unlock_edges": [
    "M-PRE-FRACTION-MEANING→M-G7-EQ-WORD",
    "M-PRE-DECIMAL-OPS→M-G7-RATIONAL-MIXED",
    "M-BRIDGE-SOLUTION-HABIT→M-G7-EQ-SOLVE",
    "M-BRIDGE-SOLUTION-HABIT→M-G7-EQ-WORD",
    "M-PRE-NUMBER-SENSE→M-G7-POS-NEG"
  ]
}
```

```json
{
  "id": "M-PRE-INTEGER-OPS",
  "diagnosis_priority": 1,
  "diagnosis_priority_rationale": "26 个 G7 可达、RATIONAL-ADD-SUB 直接前置边；派生自出边强度聚合，非手维护"
}
```

字段语义：
- `prereq_strength`：`"strong" | "soft"`。**strong** = 缺该前置必然卡住对应下游（无替代路径，或下游掌握标准/常见错因直接包含该前置产物），错题回查优先；**soft** = 学过更好，不作为回退触发，仅在 strong 全查完后按需查。
- `strength_rationale`：一句话依据，strong 边必填（可审计、可复核）。
- `strong_unlock_edges`：语义强但仅 unlocks 的例外边（本评审共 5 条，对应 3.3 的 4 例加 NUMBER-SENSE→POS-NEG），键格式 `"from→to"`。
- `diagnosis_priority`：节点级派生 `1|2|3`，初始按第 5 节 Tier 回填（S→1、A/B→2、C→3），后续由脚本从边级强度 + 下游关键性自动重算。

> 备选方案 B（不推荐）：`prerequisites` 升级为 `[{id, strength}, "id"]` 混合数组——破坏现有消费方、schema 复杂化。
> 备选方案 C（不推荐）：仅节点级 `prereq_strength` 单值——无法表达 14 个 mixed 节点，信息损失。

### 6.3 回填策略与默认值

**默认值 = `soft`**（保守）。理由：暑假约 50 天、每天约 1 小时，AGENTS.md 要求"只补会影响七上学习的前置节点"。误判 strong 会触发过度诊断/过度补课（false positive 成本高）；漏标 strong 只是把该边放到回查顺序后段（false negative 成本低——"先查 strong 再查 soft"仍会沿链查到，且 D 卡死态会暂停当前节点兜底）。"未标注"本身可被脚本审计清单暴露。

回填三步：
1. **首期（本评审）**：24 节点全部出边显式回填——16 个 strong 节点对应边标 strong（unlocks-only 强边入 `strong_unlock_edges`）；8 个 soft 节点对应边标 soft，其中 **UNIT-CONVERSION→SEGMENT-MEASURE 例外标 strong**。每条 strong 边附一句话 rationale。
2. **二期（规则补全）**：未评审的前置边——G7→G7 主线边（如 ADD-SUB→MUL-DIV、EQ-SOLVE→EQ-PAREN、ALG-EXPR→EXPR-VALUE、EQUATION-CONCEPT→EQ-SOLVE 等）按"主线内缺必卡"标 strong；桥梁→G7 的 unlocks-only 边标 soft；由图谱维护人复核一遍。
3. **三期（机制固化）**：脚本从边级聚合出节点级 `diagnosis_priority`；QA 校验新增：`prereq_strength` 枚举检查、strong 边必须有 `strength_rationale`、strong 边必须能在目标节点 `common_mistakes` / `mastery_criteria` / `remediation_if_failed` 中找到对应证据。

**统一判定规则（消除 3.1/3.2 分歧的复核口径）**：一条边判 strong，当且仅当满足其一——(a) 目标节点 `prerequisites` 边表中存在该边，且目标节点掌握标准/常见错因直接包含该前置产物；(b) 无替代路径（其他前置或 unlocks 旁路无法覆盖该题型分支）；(c) 目标为 P0 主线且该前置是其唯一入口。其余（仅 unlocks 且可绕行、P2 拓展、识别向概念）一律 soft。

---

## 7. 落地建议

1. **首批数据**：以本文档第 2 节 + 第 5 节为唯一数据源，生成首期 `prereq_strength` 回填 patch（建议作为 v2 增量，或并入图谱 v3）。
2. **二轮评审**：按 6.3 判定规则复核 3.2 争议组（EQ-WORD 五前置内部强弱）与 3.1 争议组（PERCENT 概念/模型、RATIO-PROP/PERCENT 对称组），统一口径后定稿。
3. **消费方对接**：诊断/规划 agent 的回退链排序改为"先查 strong 边、再查 soft 边"；`diagnosis_priority` 进入试点脚本（参考 `scripts/activate_three_node_pilot.py` 对 `priority` 的消费方式）。
4. **维护闭环**：新增边时默认 soft + 强制评审，防止"新增即 strong"的隐性漂移。
