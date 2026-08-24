# 新学期题目库契约（question_bank_contract v1.1）

- Date: 2026-08-20（v1.1：+design_rationale_json 列、+难度底线规则、+教研审查门禁；objective ① 题目质量门禁升级）
- Status: spec（方案 A：显式 difficulty 轴，用户拍板）
- 关联：拍板提案 `2026-08-20-mastery-criteria-proposal.md`（判定层证据需求）、图谱 v2（每节点 question_generation 契约）、`semester_mode_readiness.md`（学期模式后端）
- 规模目标：56 节点 × 每节点 12-20 题 ≈ **800-1100 题**（孩子每轮仍只精选 10 道，少而精在挑选、量在库）

## 1. 设计原则

1. **量在库、精在挑**：题库按"题型 × 难度"矩阵铺满，planner 每轮精选 10 道——题库丰富 ≠ 孩子刷题海
2. **判定层对齐**：题目必须能让判定层产生 A 档所需证据（≥2 个结构指纹 + core/transfer 双角色 + 跨 2 自然日 + 强证据含解释分与推理质量）——题目形状是判定质量的输入
3. **质量门禁优先于数量**：sympy 答案验算逐题过，答案错不进库（答案错全链错）；**每题必须自带设计理由（design_rationale）**，讲不清"为什么这么出"的题不进库
4. **难度底线**：题目不要太简单——琐碎题（一眼答案、无真实推理、纯记忆无运用）审查打回
5. **分层为教学服务**：薄弱节点先给简单题搭脚手架，复测用困难变式防"会背不会用"，强节点给迁移综合

## 2. question_items 字段扩展（方案 A）

新增 4 列（db.py 加列迁移，风格对齐 `_ensure_column`）：

| 列 | 类型/约束 | 语义 |
|---|---|---|
| `difficulty` | text NOT NULL default 'medium' | `easy`/`medium`/`hard`——**planner 挑选用**（给孩子调难度），与 variant_level（认知阶梯 L1-L4，教研用）正交 |
| `purpose_role` | text NOT NULL default 'core' | `core`（直接考察本节点）/ `transfer`（与前后知识混合，考察迁移）——**A 档判定 C3 依赖**（≥1 条 core + ≥1 条 transfer 才能升 A） |
| `answer_verification` | text NOT NULL default 'pending' | `verified`/`mismatch`/`unverifiable`/`pending`——**sympy 校验门禁状态**，mismatch 不入库 |
| `design_rationale_json` | text NOT NULL default '{}' | **生成逻辑五要素**（见下）——objective ① 质量门禁：每道题有背后生成逻辑 |

**design_rationale 五要素**（生成逻辑，每题必填；缺省由管线按批规格派生最小 rationale：考点=seed_question_type、教学角色=批规格）：

| 要素 | 内容 |
|---|---|
| 考点 | 考哪个子技能（seed_question_type / 具体考点） |
| 难度理由 | 为什么这个难度（运算步数、干扰设计、与薄弱/强节点的匹配） |
| 认知阶梯定位 | L1-L4 哪一级（识别→套用→变式→迁移），对应什么心智操作 |
| 错因陷阱 | 埋什么常见错误，对应哪个 `CANONICAL_ERROR_TAGS` 标签 |
| 教学角色 | 标准例题/变式/检测/复测/诊断/迁移中扮演什么教学功能 |

**structure_fingerprint（不新增列，派生）**：`f(kind, question_type)`——同一节点内不同 question_type 族 = 不同指纹。契约要求**每节点 ≥2 个不同 question_type 族**（判定 C2：≥2 指纹才能升 A）。

## 3. 每节点题目矩阵（题型 × 难度）

图谱 `question_generation` 契约（56 节点全有）：`minimum_daily_set: 1 标准 + 2 变式 + 1 复测`、`variant_ladder: L1识别→L2套用→L3变式→L4迁移`、`seed_question_types`（3-5 个）、`diagnostic_probes`。

**每节点题集（目标 12-20 题）**：

| 题型 | 数量 | 难度 | purpose_role | 用途 |
|---|---|---|---|---|
| 标准例题 | 1 | medium | core | 讲本质用（教学锚点） |
| 变式 L1（识别） | 1-2 | easy | core | 概念识别，搭脚手架 |
| 变式 L2（套用） | 2 | easy-medium | core | 直接计算/列式 |
| 变式 L3（换语境/干扰） | 2 | medium | core | 变式核心层 |
| 变式 L4 / 迁移题 | 2 | hard | **transfer** | 与前后知识混合（A 档双角色来源） |
| 检测题 | 2 | easy + hard | core | 判掌握（档位区分） |
| 复测题 | 2 | medium + hard | core | 确认真掌握（防"会背不会用"） |
| 诊断题 | 1-2 | easy-medium | core | 区分 A/B/C/D 档（来自 diagnostic_probes 素材） |

**难度配比**：约 30% easy / 40% medium / 30% hard（薄弱节点可调成 40/40/20 先搭脚手架）。

**判定层证据保证**（每节点必须满足）：
- ≥2 个不同 question_type 族（C2 指纹）
- ≥1 条 transfer 题（C3 双角色）
- 计算/套用类题型支持 `expected_answer` 机器验算（sympy 门禁可过）

## 4. 答案校验门禁与难度底线（质量红线）

### 4.1 答案校验门禁

- 计算/套用类（answer_format 可机检）：入库前 `answer_verification` 必须 = `verified`（用 `learning_system/answer_verification.py` + `scripts/audit_question_bank_answers.py`）
- `mismatch` → **不入库**，回生成器重出
- `unverifiable`（无表达式可提取）→ 允许入库但标记，后续人工/教研复核
- 概念/诊断类（不可机检）→ 走既有 review 制 + 教研审查（琢玉）

### 4.2 难度底线规则（v1.1，objective ①）

- **琐碎题打回**：一眼答案、无真实推理、纯记忆无运用的题，教研审查**打回**（重出或丢弃）
- **难度标定须与题型/角色一致**：识别题可以 easy 但不得琐碎；套用/变式题不得无脑（要有真实运算或推理步）；easy ≠ 送分题
- **启发式抽检（警告，非硬拒）**：`validate_node_bank_contract` 用 `trivial_question_heuristic` 抽检——题干去空白后极短（< 15 字符）且（无数字运算 **或** 无推理动词）→ 标 `trivial` **warning**。警告不使契约失效，**去留由教研审查门禁（reviewer_fn）决定**——启发式可能误伤/漏判，语义边界以代码 docstring 为准
- **硬检查**：每题 `design_rationale` 非空且含考点（`design_rationale_ok`），缺失 → 契约校验不通过

## 5. 元数据派生（入库时）

- `error_tags_json`：从 `CANONICAL_ERROR_TAGS`（error_tags.py 单一源）按题型选 1-2 个常见错因
- `rollback_candidate_node_ids_json` / `rollback_candidate_relations_json`：从图谱 `prerequisite_edges`（strong 优先）派生——每题标注错因回退候选
- `secondary_node_ids_json`：迁移题标注涉及的前后知识节点
- `estimated_minutes`：按题型/难度给 1-8 分钟
- `design_rationale_json`：raw 提供 dict 且含非空考点 → 原样写入；缺省 → 从批规格派生最小 rationale（考点=seed_question_type、教学角色=matrix_label/kind，其余要素按难度/阶梯/错因标签填）

## 6. 生成管线（顺序小批量，非异步流水线）

```
按节点序（图谱主线序）逐节点：
  1. 读节点 question_generation 契约 + seed_question_types + diagnostic_probes
  2. 生成器按矩阵产题（LLM 顺序小批：每批 3-5 题，带难度/purpose_role/题型要求）
  3. sympy 校验（计算类）→ mismatch 重出（≤2 次）
  4. 教研审查门禁（v1.1，reviewer_fn 注入，objective ①）：
     - reviewer_fn(batch, questions) -> {approved, issues:[{question_index, severity, issue}]}
     - 不通过 → 整批重出一次（批规格带 review_feedback 回生成器）
     - 仍不通过 → 该批丢弃并计数（review_discarded）
     - reviewer_fn=None → 跳过（向后兼容；真实琢玉 LLM 审查在 objective ② 接入）
  5. 元数据派生（error_tags/rollback/secondary/estimated_minutes/design_rationale）
  6. 入库 question_items（answer_verification 状态 + design_rationale_json 写入）
  7. 批间校验：节点指纹数 ≥2、双角色齐、难度分布达标、design_rationale 全含考点、
     琐碎题抽检（trivial_warnings，警告）
试点：先 2 个节点（一个计算向 + 一个概念向）全流程跑通 + E2E 用真实题目验证，再全量
```

## 7. 验收

| 项 | 标准 |
|---|---|
| 规模 | 56 节点 × 12-20 题 = 800-1100 |
| 难度分布 | 全库 ~30/40/30（薄弱节点可调） |
| 判定对齐 | 每节点 ≥2 指纹 + ≥1 transfer（可升 A） |
| 答案校验 | 计算类 100% verified 才入库 |
| 设计理由 | 每题 design_rationale 非空且含考点（硬检查） |
| 难度底线 | 琐碎题审查打回；启发式 trivial 警告可见于契约校验报告 |
| 教研审查 | 管线支持 reviewer_fn 注入门禁（重出一次/丢弃计数），真实审查接入后生效 |
| 运行验证 | E2E 用真实题目跑通（判定/复测/计划） |
| 契约测试 | schema 扩展测试 + 校验门禁测试 |
