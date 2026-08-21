# 掌握判定标准提案（mastery_criteria_proposal）

- Date: 2026-08-20
- Role: `assessment`（权衡），role_version 1.0.0，child_handle 由调度层附加
- Formal result: `mastery_criteria_proposal`（M2.5「判定口径统一」的 P0 前置交付物）
- Status: **approved（2026-08-20 爸爸拍板）**——4 项默认规则全过（升 A 门槛/连续 3 次 C/D 降档/[1,3,7,14,30] 复测间隔/作业错题只触发复测回查不直接改档案）；会审修订版（琢玉/知几交叉审查意见已并入）；M2.5 据此实现
- Scope: 七上数学学期模式数据链路；判定规则只覆盖"状态判定 + 手动证据入档 + LLM 参与边界 + 防过度诊断的判定侧对齐"
- 前置文档：`docs/design/specs/2026-08-20-dataflow-audit-record.md`（核对项 6，差异表已核实）、`docs/design/specs/2026-08-20-child-learning-companion-design.md`（§2/§3.1/§3.2/§5.2/§8.4）、`docs/00_PROJECT_BLUEPRINT.md` §12
- 硬约束：判定逻辑全部**代码可复现**（阈值、规则、证据链可测试、可追溯）；正式结果带"三件套"

> **修订记录（会审：琢玉/知几交叉审查，2026-08-20）**
> - ① §3/§4 M1 计数矛盾：唯一计数器（§2.3）仅统计**系统内判定事件**；M1 走**动作层独立计数**（同阈值 3，只触发回查、不直接降档）；§4 表头改为"状态降级仅由系统判定事件驱动"。
> - ② §3 默认工作流判定惰性：M0 也触发系统内复测（教学动作，产出系统证据后才进判定侧，档案不受 M0 影响）；新增**周信批量确认通道**（周信发出后 10 分钟内对当周错题一次性确认，回溯标记为 M1）。
> - ③ §2.4 复测间隔算法：补 **verdict=B 分支**（深度不变、按当前间隔重排）；显式声明**复测通过 = 窗口级 AGG（历史证据参与，非单题级）**，杜绝"单题级 A → 每日复测死循环"。
> - A1：§4「计数≥2 周信提前提示」由建议升为**硬要求**（"连续 3 次"滞后的可接受性依赖此预警窗口）。
> - A4：§2.4「B 档间隔 1-3 天」补齐算法（depth=0 的 B 按连续 B 判定事件数 1→3 天；depth≥1 的 B 按当前间隔重排）。
> - 各修订处均标注"会审修订"，原判定数值/阈值语义未变。

---

## 0. 三件套（爸爸可直接拍板的版本）

**一句话结论**：状态只认系统内做题证据——A/B/C/D 四档是唯一存储状态，统一按「≥2 条强证据 + 跨两天 + 迁移双角色 + 全链校验」才升 A，**连续 3 次系统内 C/D 判定事件**才降档，手动记的错题只触发复测/回查（M1 动作层独立计数同阈值 3、只触发回查、**不直接降档**）、永不升档，LLM 只做归类且只可收紧不可放宽。

**核心依据**：四套口径已逐实现实测并存（阈值、状态枚举、证据要求、落库路径四列均不一致，见核对项 6 差异表）；其中仅两条落库路径（flow_nodes v2 orchestrator 与 daily_runtime v51）真正写 `learner_node_status`/`mastery_decisions`，统一收口的主战场即此两处。

**备选与代价**：五个备选方案及代价见 §6.2——保留 v51 单一口径（丢 flow_nodes 五维 core 的"过程全对"强度校验）、以 flow_nodes 为单一口径（丢 v51 全链证据门的防污染能力）、存储层加第 5 态（枚举扩展波及全部消费方，YAGNI 否决）、手动证据计入降级计数（自报归属偏差污染档案）、降级阈值取 2（与"连续 3 次"口径分裂）。

---

## 1. 事实基础（实测代码行为）

> 以下均经读代码核实，引用 `文件:行`；与核对项 6 差异表（`2026-08-20-dataflow-audit-record.md:462-469`）一致，本稿直接引用不重述。

| 实现 | 阈值 | 状态枚举 | 证据要求 | 落库路径 |
|---|---|---|---|---|
| 蓝图 §12（文档，`:637-666`） | A≥85% / B 60-85% / C<60%；D=节点错+前置链错 | A/B/C/D | 定性（能讲清/说不清）；无量化 | 不落库 |
| `evolution.py` `_status_from_attempts`（`:662-683`） | 0.85/0.60；blocking→D、高分推理缺口→C 优先 | A/B/C/D | can_explain（exp≥2 且无推理缺口）；A 需样本≥2 | **proposal-only**：只写 `evolution_events`（`:1305/1361`），对 `learner_node_status` 只读（`:1138`） |
| `flow_nodes.py` `_mastery_diagnosis`（`:399-498`） | ratio<0.6→unstable；无 0.85 硬阈值 | **6 态** mastery_state（另有 4 档 overall_status，`:519-528`） | strong=correct+exp≥2+五维 core 全 matched（`:352-361/409-414`）；stable 需 strong≥2+迁移题型（`TRANSFER_CONFIRMATION_KINDS` 8 种，`:69-78`）+题型≥2 种（`:424`） | v2 orchestrator：`learner_node_status`（`orchestrator.py:565-581`）+ `mastery_decisions`（`orchestrator.py:695` → `db.py:643-665`） |
| `daily_runtime.py` v51（`:13533-13605`） | 确定性路径 score<8/10 或 severe_gap→weak（`:7813/7820`）；无百分比阈值 | recommendation 6 枚举（`evaluation_decision.v2.json:39`）→ status A/B/C/D | A 档 = `_evidence_set_supports_stable_mastery`（`:13746-13840`）：≥2 全链校验证据 + ≥2 structure_fingerprint + 双角色 confirmation_core&transfer；B = correct+exp≥2+sound 或 emerging/likely_stable | v5 落库：`mastery_decisions`（`:13637`）+ `learner_node_status`（`:13699-13705`，status_revision 递增） |

其他已核实事实（本提案裁定的输入）：

1. **判定事件粒度现状**：v51 是**逐条作答**产出一次判定（`_record_evaluation_update`，`:13468` 起）；flow_nodes v2 是**会话级按节点聚合**批判定。设计稿 §4.3「概念题连续错 3 次」、§2 闸门 #3「连续 3 次 C/D 判定」按"次"计，天然对应逐条判定。
2. **证据资格链（v51）**：evidence gate 通过（`:13489`）→ 语音识别可证（`_attempt_recognition_allows_mastery`，`:5213`）→ `mastery_update_eligible`（`:13510`，practice 用途不产判定，仅标记复测确认需求）；`question_usage.py:395-434`：diagnostic 用途 weight=1.0、ceiling=A、no_hint；practice 用途 weight=0.25、ceiling=B、requires_confirmation。
3. **A 档门槛的推理质量缺口**：v51 的 A 门（`:13746-13840`）校验用途/版本/hint/assessment/review，但**不含 reasoning_soundness/推理缺口检查**；而 evolution 的 C 优先规则（`_has_high_score_reasoning_gap`，`:686-699`）正是防"答案对但推理缺"的误判机制——统一口径必须补上。
4. **防覆盖语义**：v51 有 `preserve_accumulated_status`（`:13574-13585`，old∈{A,C} 时单条 emerging 不覆盖累积状态）；flow_nodes/orchestrator 无此保护。
5. **手动错题载体**：核对项 4 已裁定**方案③旁挂侧表**（`manual_error_entries` 反链），手动错题**不写 attempts 行**（`2026-08-20-dataflow-audit-record.md:345`）；`attempts.explanation_score` 可空（`db.py:436`）；`answer_source='parent_manual'` 枚举值保留定义、实际落位留 M4。
6. **LLM 现状**：评估 agent 契约 `evaluation_decision.v2.json:39` 定义 6 枚举；确定性路径只产 weak/emerging（`:7813/7820`，记录回放 `:9724` 同）；prompt 纪律"单条强证据不足以证明持久掌握 / stable_for_now 仅限多样化证据"（`prompts/evaluation_decision.v2.md:12/17-23`）；契约置信门槛 minimum_confidence_to_apply=0.8（`evaluation_decision.v2.json:8`）。

---

## 2. 判定口径统一方案

### 2.1 状态枚举裁决：A/B/C/D 四档为唯一存储货币

**裁定**：

1. **存储层只保留 A/B/C/D 四档**——`learner_node_status.status_code` 与 `mastery_decisions.new_status_code` 枚举**不变**（零 schema 变更；周信快照、图谱点亮、planner、闸门消费方全部不动）。
2. **flow_nodes 6 态（mastery_state）与 v51 6 枚举（recommendation）退役为"判定中间量"**：不再作为任何权威状态字段；允许在 `mastery_decisions.decision_payload_json` 中保留为**解释性元数据**（历史行 payload 不动，兼容）。
3. **"中间态"的归宿 = 判定函数内部**：统一判定函数产出 `verdict ∈ {D, C, B, A, NO_CHANGE}`（5 值），其中 **NO_CHANGE 不落库**——"未建档/无有效证据"在存储层表现为**无行/保持原状**，**绝不写成 C**（修正 flow_nodes/orchestrator 把 `insufficient_evidence` 映射为 C 的误判点，`orchestrator.py:530-535`；"没测过 ≠ 薄弱"是防过度诊断的判定侧第一原则）。
4. **明确裁决"4 态 vs 6 态并存"**：设计稿 §3.2 现状清单漏记 flow_nodes 的 blocked/unstable（核对项 6 影响 #3，`audit:487`），以实测 6 态为准；统一后 6 态全部折叠进 verdict 语义（blocked→D、unstable/emerging→B/C、stable/likely_stable→A 候选/B、insufficient_evidence→NO_CHANGE）。

**可复现性**：存储枚举 = `{"A","B","C","D"}`；判定中间量 = `verdict` 5 值；无第 5 存储态。

### 2.2 统一判定函数（阈值与判定规则）

**统一判定函数契约**（实现为单一模块，建议 `learning_system/mastery_rules.py`；两条落库路径共同 import——实现归属 M2.5，本提案只定规则）：

```
mastery_verdict(evidence: AttemptEvidence, window: list[AttemptEvidence]) -> Verdict
  Verdict = {code: 'D'|'C'|'B'|'A'|'NO_CHANGE', decision: str, reason: str,
             is_strong: bool, attrs: {...}}
```

**判定事件粒度**：**单条 eligible 作答 = 一个判定事件**（与 v51 逐条判定、与"连续错 3 次"语义一致；flow_nodes 的会话级聚合批判定退役）。

**eligibility（证据资格，全部满足才产生判定事件）**：
- evidence gate 通过（v51 全链门语义，`:13489`）；
- `mastery_update_eligible=true` 且 `purpose=diagnostic` 且 `hint_policy=no_hint`（`question_usage.py:445-450`）——practice 证据不产判定事件（仅可标记复测确认需求）；
- 语音输入可证（`_attempt_recognition_allows_mastery`，`:5213-5238`）；
- `answer_analysis` 有效且无推理缺口信息缺失；
- **非手动证据**（手动证据见 §3）。

**判定规则 R（单条判定事件，按序裁决，产出 verdict）**：

| # | 条件（全部基于该条证据） | verdict |
|---|---|---|
| R1 | `blocking_evidence=true`（显式无法启动/前置断点证据） | **D** |
| R2 | `result=wrong` 或 `ratio < 0.60`（ratio=score/max_points） | **C** |
| R3 | `result=partial` 或 `explanation_score < 2` 或推理缺口（`reasoning_soundness ∈ {incomplete, unsound, unclear}` 或 `evidence_strength ∈ {weak, insufficient}` 或 `next_evidence_need` 非空——即 evolution `_has_high_score_reasoning_gap` 语义，`:686-699`） | **C** |
| R4 | `result=correct` 且 `ratio ≥ 0.85` 且 `explanation_score ≥ 2` 且 `reasoning_soundness=sound` 且无推理缺口 → **strong 证据** | 聚合 A 资格（§AGG）满足 → **A**；否则 **B** |
| R5 | `result=correct` 且 `0.60 ≤ ratio < 0.85` 且 `explanation_score ≥ 2` 且 `reasoning_soundness=sound` | **B** |
| R6 | 其余（无有效证据 / 证据门未过 / 非 mastery 用途） | **NO_CHANGE**（不写库） |

> 阈值裁决说明：0.85/0.60 继承蓝图 §12 与 evolution（`docs/00_PROJECT_BLUEPRINT.md:641-658`、`evolution.py:677-682`）；`ratio<0.60→C` 优先于 result=correct 的 B 判定（对齐 flow_nodes 0.6 边界与蓝图 <60%=薄弱）；推理缺口→C 优先于高分→B（对齐 evolution 的 C 优先设计，防"答案对过程缺"误判）。解释分<2→C（对齐 v51 与 flow_nodes 的多数派；"答对但讲不清"=薄弱，蓝图"概念说不清→C"）。

**聚合 A 资格 AGG（verdict=A 的升档门，窗口内计算）**：

- 证据窗口 **W = 滚动 90 天**（覆盖学期模式全周期；保证 30 天间隔复测的证据仍在窗口内；降级/计数不设窗口，按判定事件时间序天然有界）。
- **strong 证据** = 满足 R4 前半（correct + ratio≥0.85 + exp≥2 + sound + 无推理缺口）。
- AGG 条件（**全部**满足）：
  - C1：窗口内 strong 证据 **≥2 条**（最小证据量；含本次）；
  - C2：strong 证据的 `structure_fingerprint` 去重 **≥2 个**（题型/结构多样性）；
  - C3：`purpose_role` 覆盖 **confirmation_core 与 confirmation_transfer 双角色**（迁移证据在场；对齐 v51 `:13836-13840` 与 flow_nodes 迁移题型要求 `:423`）；
  - C4：窗口内**最近一次 C/D verdict（若有）之后存在 ≥1 次 strong verdict**（修复/复测确认；且该 strong 之后无新 C/D）——不允许带着未修复的薄弱升 A；
  - C5：strong 证据的 `created_at` 覆盖 **≥2 个自然日**（跨两天采样；"间隔复测确认"的操作化定义之一，防单日运气连对）；
  - C6：窗口 ratio = Σscore/Σmax **≥ 0.85**。
- AGG 满足 → verdict=A；否则单条 strong → verdict=B。

> 本规则把 flow_nodes 的 strong≥2+迁移+多样性（`:443-446`）与 v51 的全链门+双指纹+双角色（`:13746-13840`）**合并为同一门槛**，并补两处缺口：① v51 A 门缺的推理质量检查（C4 + R3 补上）；② 两实现都缺的跨自然日条件（C5，对应设计稿"最小证据量 + 间隔复测确认"§3.2 原则 2 与建档"跨两天采样"，`:139/190`）。

### 2.3 升降级条件（状态迁移 + 防单次波动滞后）

**连续 C/D 计数（唯一计数器，仅系统内判定事件）**：按 `created_at` 时间序扫描该节点**系统内判定事件**（§2.2 eligibility 产出的判定事件），从最新往前数连续 `verdict ∈ {C,D}` 的事件数；遇 `verdict ∈ {A,B}` 即停并清零；NO_CHANGE 事件跳过（不计入、不打断）。**手动 M1 不计入此计数器**（走动作层独立计数，阈值同 3，见 §3/§4）。**计数达到 3 → 触发降级/回查并清零**（同一数字、同一语义，见 §4 对齐）——**状态降级仅由系统判定事件驱动**（会审修订）。

**状态迁移表（对 stored status S）**：

| 当前 S | verdict=A | verdict=B | verdict=C/D（连续计数） | blocking_evidence |
|---|---|---|---|---|
| 未建档 | → A | → B | → C（按需建档即弱，有据） | → D |
| A | 保持 A | **保持 A**（防单条强证据覆盖累积档案，v51 preserve 语义 `:13574-13585`） | 连续计数+1；**连续 3 → C** | → D |
| B | → A | 保持 B | 连续计数+1；**连续 3 → C** | → D |
| C | → A（AGG 全满足，允许修复后直接升 A） | **窗口内 strong≥2 才 → B**，否则保持 C（防单条翻案；v51 likely_stable→B 语义 `:13586-13589`） | 连续计数+1；**连续 3 → 触发回查**；回查结论前置链错 → D | → D |
| D | → B（D 不跳 A） | → B（修复确认；D 是阻断性证据，解除即强信号，v51 D+emerging→B 同） | 保持 D（回查/修复中） | 保持 D |

**降级裁决说明**：
- **降级阈值 = 连续 3 次系统内 C/D 判定事件**（与 §2 闸门 #3、§6.1、§4.3 的"连续 3 次 C/D"同数同义——裁定"进判定规则"，理由见 §4；**仅系统内判定事件计数，手动 M1 不参与降级**，会审修订）；A/B 直接降到 C（判定事件本身携带证据档位，verdict=C 即"薄弱"证据连续成立，不逐级 A→B→C）。
- **升降级不对称是有意为之**：升档保守（跨 2 日 + 双角色 + ≥2 strong），降档敏感（连续 3 次即降）——对学习档案而言，**假阳性掌握（over-claim）的代价远大于假阴性（under-claim）**；且爸爸是最终拍板人，周信在计数≥2 时**必须**提前提示（硬要求，§4 A1），第 3 次才改档案。
- **C→B 需窗口内 ≥2 strong**（不是单条）：C 是"测量过的薄弱状态"，单条 strong 可能是波动（prompt 纪律"单条强证据不足以证明持久掌握"）；D→B 单条 strong 即可（D 的解除本身就是强信号）。此不对称有据，已如实记录供会审。
- NO_CHANGE 永不写库；`mastery_decisions` 只记实际判定事件（append-only），`learner_node_status` 仅在状态变化时更新（status_revision 递增机制保留，`daily_runtime.py:13699-13705`）。

### 2.4 复测间隔算法

```
RETEST_INTERVALS_DAYS = [1, 3, 7, 14, 30]   # 封顶 30 天
depth(node) = 自该节点最近一次 new_status_code='A' 的判定事件以来，产出的 A verdict 判定事件数（cap 4）
next_retest_at(node) = last_A_event_at(node) + RETEST_INTERVALS_DAYS[depth] 天
```

- **复测通过标准（显式声明，会审修订）**：复测通过 = 该次复测产出 **verdict=A**；verdict=A 由 §2.2 **AGG 窗口级聚合**判定（C1-C6 全部满足，**历史 strong 证据参与**），**非单题级**——单条 correct+exp≥2+sound 在 AGG 不满足时最多产出 B（R4/R5）。因此**不存在"单题级 A → 深度+1 → 每日复测死循环"**：深度推进只发生在窗口级 A 通过之后。
- **A 档达成 → 次日复测（1 天）**；每次**窗口级**复测通过（verdict=A）→ 深度 +1 → 3 → 7 → 14 → 30 天；30 天通过后维持 30 天（长期巩固）。
- **复测失败（verdict∈{C,D}）** → 深度归零、间隔重置为 1 天；按 §2.3 降级规则处理。
- **复测产出 B（verdict=B，会审修订补分支）** → 深度不变（不推进、不归零），`next_retest_at` 按当前间隔重排：
  - depth ≥ 1（巩固期波动）：`next_retest_at = now + RETEST_INTERVALS_DAYS[depth]`（保持当前间隔，等待下次复测）；
  - depth = 0（从未 A，如 C→B→A 路径）：间隔 1-3 天，`next_retest_at = now + (b_count ≥ 3 ? 3 : 1) 天`，其中 `b_count` = 自最近一次非 B verdict 以来连续 B verdict 判定事件数（服务 C→B→A 高频推进、防 A 前遗忘）——**A4 补全**：原"B 档间隔 1-3 天（随 B 判定事件推进）"的无算法表述由此算法化。
- **C/D 档**：不排"间隔复测"，由回查/修复流程驱动（同结构或前置探针，属教学层）。
- **可复现性**：`last_A_event_at`、`depth`、`b_count` 均由 `mastery_decisions`（append-only）**可重算推导**，不新增状态列；复测计划由 planner 消费该算法输出（消费实现归 M2.5/规划侧，本提案只定算法）。

### 2.5 旧口径退役清单与收口主战场

**退役（M2.5 实现，判定口径层面不再作为状态来源）**：

| 实现 | 退役内容 | 处置 |
|---|---|---|
| `evolution.py` `_status_from_attempts`（`:662-683`） | "状态判定"职能 | 退役为 **proposal-only 元数据**（现状即不落库）；其 `node_status_update_proposals`（`:1140-1147/1305`）不再被任何消费方当作判定口径；proposal 生成是否保留由 M2.5 定（自演化仍可能需要），但状态结论一律不消费 |
| `flow_nodes.py` `_mastery_diagnosis`（`:399-498`） | 6 态产出 | 状态枚举退役；证据资格逻辑（strong/weak/迁移/多样性计算）**吸收进统一判定函数** |
| `orchestrator.py` `_status_update_from_evaluation`（`:523-555`）/`_mastery_decision_from_status`（`:335-360`） | 6 态→A/B/C/D 映射 | 退役，改为调用统一判定函数；**其中"insufficient_evidence→C"（`:530-535`）为误判点，一并废止** |
| `daily_runtime.py` v51 recommendation→status 映射（`:13561-13605`） | 推荐→状态映射 | 退役，改为调用统一判定函数；LLM recommendation 降级为"证据解读标签"输入（§5） |
| `flow_nodes.py` `overall_status` 4 档（`:519-528`） | 4 档状态 | 降级为 `decision_payload` 解释性元数据 |
| 蓝图 §12 | 文档阈值 | 数值 85/60 已继承进统一规则；M2.5 落地后于蓝图加注"执行口径见 mastery_criteria_proposal"（标注性改动） |

**保留供消费（统一口径的构件）**：

| 构件 | 保留用途 |
|---|---|
| `daily_runtime._evidence_set_supports_stable_mastery`（`:13746-13840`） | 统一 AGG 的**全链证据门**（版本/hint/assessment/review 全链校验）——唯一防污染门 |
| evidence gate + `_attempt_recognition_allows_mastery`（`:5213`） | 判定事件 eligibility |
| `_v51_deterministic_evaluation_output`（`:7776-7836`，8/10 分制 + severe_gap） | **确定性证据标签**（weak/emerging）输入 |
| `build_mastery_evaluation_package`（`flow_nodes.py:501-569`） | 证据打包器（strong/weak/维度/缺口元数据，供统一函数消费与 payload 记录） |
| `mastery_decisions`（`db.py:643-665`）+ `learner_node_status` status_revision 写路径（`:13699-13705`） | 落库机制 |
| `question_usage.py` diagnostic/practice 用途与 weight/ceiling（`:395-434`） | eligibility 与 B 档 ceiling |

**收口主战场**：**daily_runtime v51 `_record_evaluation_update`（`:13468` 起）**——它已具备完整链路（证据门 → 判定 → `mastery_decisions` → `learner_node_status`），统一判定函数**优先在此接入**；第二接入点 = flow_nodes v2 orchestrator 落库路径（`orchestrator.py:680-704`）。**统一判定函数为单一实现**（建议新模块 `learning_system/mastery_rules.py`，两条路径共同 import）——这是"裁定为一套"的代码归宿；evolution.py 是 proposal-only 不落库，不参与收口主战场。

---

## 3. 手动证据入档规则（设计稿 §3.1，`:125-132`）

**前置事实**：核对项 4 已裁定手动错题**不写 attempts 行**（FK 方案③旁挂侧表 `manual_error_entries` 反链，`audit:345`）；`answer_source='parent_manual'` 枚举值保留、实际落位留 M4；`explanation_score` 天然缺失（自我诊断不产出解释分）。另：设计稿 §3.1 录入归属**默认**为"孩子录入 + 爸爸只做周信确认与低置信错因确认、不做逐题确认"（`design:128`）——若 M1 仅能靠逐题确认产生，作业错题录入（学期模式主数据入口）在默认配置下几乎不触发判定侧，构成**录入判定惰性**（"该回查的没回查"）。本版修订以 ① M0 触发系统内复测 + ② 周信批量确认通道 双通道化解（会审修订）。

**裁定（手动证据分级入档）**：

| 级别 | 定义 | 判定侧作用 |
|---|---|---|
| M0 | 孩子自报、未爸爸确认 | ① **触发一次系统内复测**（该节点 1-2 题，同结构或近迁移）——复测是教学动作，其作答是正常系统内证据、按 §2.2 正常产出判定事件（判定侧只消费复测产出的系统证据，不消费 M0 本身）；② **判定侧零作用**：M0 本身不产判定事件、不计数、不降级、不升档，仅证据范围标注（周信"含手动补录"），档案不受 M0 影响（会审修订） |
| M1 | 孩子自报 + **爸爸确认**的错题（确认通道二选一：逐题确认；或**周信批量确认**——周信发出后 10 分钟内对当周错题一次性确认、回溯标记为 M1，见下文通道说明） | ① **触发一次系统内复测**（该节点 1-2 题，同结构或近迁移）；② **计入回查触发计数**（**动作层独立计数**，阈值同 3——3 条 M1 只触发回查、不直接降档；**不计入 §2.3 唯一计数器**，会审修订）；③ **永不升档**（A/B 档依据仅限系统内全链证据）；④ **永不单独产出判定事件**（不直接写 `mastery_decisions`）；⑤ 不计入状态降级计数（档案层仅系统内判定事件） |

**周信批量确认通道（会审修订，新增）**：针对默认工作流的判定惰性（M1 需爸爸确认，而默认配置下爸爸不做逐题确认），新增批量确认入口——**爸爸在周信发出后 10 分钟内对当周错题一次性确认**（对齐"爸爸每周 10 分钟决策时间（周信）"约束，`design:65`；周信即默认工作流的确认现场）→ 当周未逐题确认的手动错题**回溯标记为 M1**（等效逐题确认），统一触发复测 + M1 动作层计数。该通道与周信工作流天然吻合、不新增爸爸负担；载体标记（侧表 `manual_error_entries` 的确认批次/时间戳）归 M4，判定规则不变。

**四条硬规则**：

1. **手动证据永不升 A**：无 `explanation_score`、无过程分析、有自报选择偏差（§3.1 选择偏差处理，`:131`）→ 不满足 strong 定义，A 档门槛（§2.2 AGG）天然拒绝；**不需要额外特判**，规则即证据门槛。
2. **手动证据的"下探" = 动作层**：M1 的作用是**把节点往下探入诊断流程**（触发复测/回查），**不是往下写档案**（不降级、不写状态）。降级仍由**系统内判定事件**驱动（M1 动作层计数不参与降级，会审修订）——"单次波动不得直接改三年档案"原则（§3.2，`:139`）对手动证据同样适用，且手动证据的节点归属是自报的，直接降级有污染风险。
3. **最小证据量如何计**：手动证据**不占判定样本**（min evidence 只统计系统内 eligible 作答）；M1 触发的**系统内复测题计入样本**并正常产出判定事件；回查触发计数中，**1 条 M1 = 动作层独立计数 +1**（等效 1 次 C 的教学动作权重——爸爸确认 = 高信任负信号，足以推动教学动作，但**不足以推动档案写入**，会审修订）。**M1 计数永不直接降档/D**：3 条 M1 → 触发回查并清零；回查产出的**系统内判定事件**（复测题 verdict）才进入 §2.3 唯一计数器，并由此才可能驱动降档/D（§4 表头）。
4. **M0 只推动教学动作、不进判定侧（会审修订）**：M0 触发的系统内复测是教学动作；M0 本身**不计数、不降级、不升档、不产判定事件**——"未确认 ≠ 薄弱"，防自报噪声直接污染档案；复测产出的系统证据按 §2.2 正常判定（可正常升 B/A、可正常计数），与证据来源（M0/M1/系统内）无关。

**边界**："作业全对确认"维持 §3.1/核对项 3 已定语义（载体 = 真新增表 `daily_all_correct_confirmations`，`audit:226`；`evidence_confirmations` 是识别纠正确认、非别名，`audit:205`）：**只作证据范围标注，不进判定样本、不进任何计数**——audit 查询纪律已定"mastery 判定不得读取本表"（`audit:226`）；周信须按三分类标注证据范围（仅系统内 / 含手动补录 / 含全对确认，`:285`）。

**备选与代价**：见 §6.2 方案④（M1 计入降级计数）——收益是爸爸确认的负证据利用率更高，代价是自报节点归属偏差可能污染三年档案。

---

## 4. 防过度诊断联动（设计稿 §2 闸门，`:115-119`）

**裁定：三个闸门阈值不进判定规则本身，但判定规则提供它们消费的"判定事件"语义；其中"连续 3 次 C/D"与判定规则**同数同义**，作为唯一对齐点。**

| 闸门 | 阈值（知几配置） | 与判定规则的对齐（**状态降级仅由系统判定事件驱动**，会审修订） |
|---|---|---|
| #1 单节点单次诊断题量上限 | 默认 5 题，超限转主线 | 判定规则不感知题量：判定事件逐条产生，单次诊断 ≤5 题限制的是诊断流程出题量，不是判定窗口样本量 |
| #2 回查深度上限 | 默认 3 层，超过只查 C/D 节点 | 判定规则只消费回查结论（前置链错 → 该节点 D 的支撑证据），不执行回查；回查产出的判定事件照常落库（M2.5 实现保证链路） |
| #3 回退触发：同节点连续 3 次 C/D 判定 | **连续 3 次** | **进判定规则**（会审修订）：唯一计数器（§2.3）**只统计系统内判定事件**（单条 eligible 作答），**M1 手动错题不计入**——M1 走**动作层独立计数**（同阈值 3，§3）：3 条 M1 只触发②回查/卡住动作、**不改档案**；唯一计数器达到 3 才同时触发：① 状态降级（A/B→C，若尚未降）；② 回查/卡住动作（闸门 #3、§6.1 异常提示、§4.3 认知跳跃信号）；③ 计数清零。**状态降级仅由系统判定事件驱动**；M1 批量确认后回查产出的系统判定事件正常进入唯一计数器 |

**对齐的必然推论（§4.3/§6.1 复核项）**：
- "链上已建档节点全 A" = 链上各节点 stored status 均为 A（未建档节点视为不阻塞，`design:197`）——统一后该信号可复现计算。
- "概念题连续错 3 次" = 概念题判定事件连续 3 次 verdict=C（`design:197`）。
- 周信异常提示（§6.1，"连续 3 次 C/D 判定"）消费同一计数器；**硬要求（会审修订，A1）**：计数≥2 时周信**必须**提前给爸爸"已连续 2 次 C/D，注意"的提示（提示先行、改档滞后，第 3 次才动档案）——**"连续 3 次"滞后的可接受性依赖此预警窗口**：第 3 次改档前爸爸至少已被预警 1 次。此要求属周信呈现层，实现归属 M4（周信生成须含该预警），不改变判定规则。
- **判定侧自带的防过度诊断**：未建档/无有效证据节点**不写状态**（NO_CHANGE，§2.1）——"没测过 ≠ 薄弱"，这是对"不做预防性诊断"（§4.3，`:188-191`）的判定侧落实。

---

## 5. LLM 参与边界裁定（设计稿 §3.2，`:134-150`）

**裁定：评估推荐不是设计稿 §3.2"LLM 只在两处"之外的第三处——它被规约进第 ① 处"错因归类"，作为"证据解读/证据归类"在评估环节的应用；状态判定永远由确定性规则完成。**

理由链（基于实测）：

1. 设计稿定"LLM 只在两处：① 错因归类；② 叙述生成"（`:140`）。现状 v51 评估 agent 已在评估环节用 LLM 产 6 枚举（`evaluation_decision.v2.json:39`）。**要么退役该 LLM 使用点，要么把它规约进"两处"之一**。评估推荐的实质 = "把证据解读成强度归类 + 缺口维度归类"，与错因归类同属"证据解读"——规约进 ①，不新增第三处，保持设计稿语义。
2. **LLM 产出物降级为"证据解读标签"**：recommendation 6 枚举只作为统一判定函数的**软输入**之一（与确定性标签并列），不是状态：`blocked`→提示 D 候选、`weak`→提示 C、`emerging/likely_stable`→提示 B（单条 strong 标签）、`stable_for_now`→提示 A 候选、`no_update`→提示 NO_CHANGE。**最终 verdict 由 §2.2 确定性规则裁决**。
3. **只收紧、不放宽（防 LLM 幻觉升档，硬约束）**：LLM 推荐 `stable_for_now` 但 AGG 不满足 → 不升 A（A 门完全确定性，`_evidence_set_supports_stable_mastery` + AGG）；LLM 推荐 `weak/blocked` 而确定性标签为 emerging → 取 weak/blocked（v51 已有同款兜底：`rec∈{blocked,weak}` 且已判 B → 降 C，`:13602-13605`，统一后保留）。
4. **降级路径（确定性兜底，不中断）**：LLM 不可用 / 低置信（<契约阈值 0.8，`evaluation_decision.v2.json:8`）/ mock / 记录回放 → 走确定性路径（8/10 分制 + severe_gap → weak/emerging 标签，`:7776-7863`），判定照常进行、状态更新不中断。
5. **错因归类信任边界维持**（§3.2，`:146-149`）：归类低置信 → 标注"待爸爸确认"、不计入错因统计；爸爸确认或规则命中才计入分布——与判定规则无关，本提案不触碰。

---

## 6. 三件套

### 6.1 一句话结论 / 核心依据

- **一句话结论**：状态只认系统内做题证据——A/B/C/D 四档为唯一存储状态，统一按「≥2 条强证据 + 跨两天 + 迁移双角色 + 全链校验」才升 A，**连续 3 次系统内 C/D 判定事件**才降档，手动记的错题只触发复测/回查（M1 动作层独立计数同阈值 3、只触发回查、**不直接降档**）、永不升档，LLM 只做归类且只可收紧不可放宽。
- **核心依据**（引用实测代码行为，详见 §1/§2）：
  1. 四套口径并存已实测入表（核对项 6 差异表，`audit:462-469`）；收口主战场 = 两条落库路径（`orchestrator.py:565-581/695` 与 `daily_runtime.py:13637/13699-13705`），evolution 是 proposal-only 不参与（`:1138/1305/1361`）。
  2. A 档门槛三套实现的强条件（flow_nodes strong≥2+迁移+多样性 `:443-446`；v51 ≥2 全链+双指纹+双角色 `:13746-13840`）在统一 AGG 中合并为同一门槛，并补上 v51 A 门缺失的推理质量检查（C4 + R3，来自 evolution `_has_high_score_reasoning_gap` `:686-699`）与两实现都缺的跨自然日条件（C5，对应设计稿"间隔复测确认" `:139`）。
  3. 连续 3 次 C/D 是设计稿 §2/§4.3/§6.1 三处已统一的数字（v0.4 修订 #7），判定规则与之一致（唯一计数器仅统计系统内判定事件，§2.3/§4；M1 走动作层独立计数、不参与降档，会审修订），保证"状态货币"与"教学动作"同义。
  4. 手动证据永不升 A 是规则的自然推论（无解释分/无分析/自报偏差 → 不满足 strong 与 AGG），无需特判（§3）；LLM 只收紧不放宽 + 确定性兜底对齐 v51 现有兜底（`:13602-13605`）。

### 6.2 备选与代价

| # | 备选方案 | 代价 |
|---|---|---|
| ① | **保留 v51 为唯一口径**（flow_nodes v2 判定退役，只留证据打包） | 改动最小；但丢 flow_nodes 五维 core"过程全对"强度校验与迁移/多样性语义，A 档在"答案对但推理缺"上更脆弱——不过统一 AGG 的 R3/C4 已补推理检查，此代价基本被吸收 |
| ② | **以 flow_nodes 为唯一口径**（v51 判定退役） | 丢 v51 全链证据门（版本/hint/assessment/review 全链校验），旧题/改版题/未审题可混入样本，污染风险上升；"preserve_accumulated_status"防覆盖语义（`:13574-13585`）需重写进 flow_nodes |
| ③ | **存储层加第 5 态**（如 untested/insufficient，保留 6 态到库） | `learner_node_status.status_code` 枚举扩展，周信/图谱/planner/闸门全部消费方适配；与"未建档不阻塞"（`design:197`）语义重复；YAGNI 否决——"未测"由无行/保持原状表达（§2.1） |
| ④ | **手动证据（爸爸确认）计入状态降级计数**（M1 也可推降 A/B） | 负证据利用率更高；但自报节点归属有偏差风险，且"单次波动不得直接改三年档案"（`design:139`）对手动证据同样成立——降级是档案写入，风险 > 收益；本提案取"只触发复测 + 计入回查计数（动作层）"（周信批量确认通道扩量 M1 后，复测/回查负载上升属教学动作的正常成本，不改变该权衡，会审修订） |
| ⑤ | **降级阈值取 2**（连续 2 次 C/D 即降，比回查阈值 3 更敏感） | 档案降级与闸门 #3/§6.1/§4.3 的"连续 3 次"数字分裂，两个计数并存、口径漂移风险；且"单次波动不污染档案"原则在 2 阈值下保护不足。本提案取统一 3 + 周信提前提示（计数≥2 提示为**硬要求**、第 3 次改档，§4 A1） |

---

## 7. 可测试性锚点（M2.5 回归测试清单）

判定逻辑代码可复现的验收锚点（每条对应 §2.2-2.4 的规则，M2.5 落地时须有测试断言）：

| # | 场景 | 期望 verdict/状态 |
|---|---|---|
| T1 | 单条 correct+exp≥2+sound，节点无历史 | B（不升 A） |
| T2 | 两条 strong（不同指纹 + 双角色 + 跨 2 自然日 + 窗口无未修复薄弱 + ratio≥0.85） | A |
| T3 | 两条 strong 但同日 | B（C5 不满足） |
| T4 | correct 但推理缺口（soundness=incomplete） | C（R3 优先于 R4） |
| T5 | blocking_evidence=true | D |
| T6 | result=wrong 或 ratio<0.60 | C |
| T7 | 未建档 + 无有效证据（practice/gate-fail） | NO_CHANGE，不写库 |
| T8 | A 节点单次 C verdict | 保持 A（计数 1） |
| T9 | A 节点连续 3 次 C/D verdict | → C（计数清零，触发回查） |
| T10 | C 节点单条 strong | 保持 C（需窗口 ≥2 strong 才升 B） |
| T11 | C 节点窗口 2 strong | → B |
| T12 | D 节点单条 strong | → B（不跳 A） |
| T13 | 手动 M1 错题（含周信批量确认回溯标记） | 无判定事件、不降级、计入动作层回查计数（非唯一计数器）、触发复测 |
| T14 | LLM stable_for_now 但 AGG 缺双角色 | B（LLM 只收紧不放宽） |
| T15 | LLM weak 而确定性标签 emerging | C（收紧生效） |
| T16 | A 达成后 next_retest_at = +1 天；通过后 +3 → +7 → +14 → +30 封顶 | 间隔序列 [1,3,7,14,30] |
| T17 | 复测失败后 depth 归零、间隔重置 1 天 | 重置生效 |
| T18 | `mastery_decisions` 每判定事件一行、append-only；`learner_node_status` 仅状态变化时 status_revision+1 | 落库语义 |
| T19 | 手动 M0 错题 | 触发系统内复测（教学动作）；M0 本身无判定事件、不计数、不降级、不升档 |
| T20 | 3 条 M1 连续（无系统内判定事件介入） | 动作层计数触发回查并清零；状态不变（不降档、不写 D） |
| T21 | 复测产出 B（depth≥1） | depth 不变、按当前间隔重排（next_retest_at = now + RETEST_INTERVALS_DAYS[depth]） |
| T22 | 复测产出 B（depth=0）且连续 B≥3 | 间隔 3 天（b_count<3 → 1 天），depth 仍为 0 |
| T23 | 单题 correct 复测但 AGG 不满足（无历史 strong） | verdict=B、深度不推进——无"单题级 A → 每日复测死循环" |

---

## 8. 挂起项与消费方影响

- **挂起**：
  - `answer_source='parent_manual'` 的实际落位（侧表 `manual_error_entries` 的 `source` 字段 vs `error_cause_log.source='manual_entry'`）——核对项 4 已定留 M4，本提案只定入档规则，不定位载体；**周信批量确认通道的载体标记**（侧表 `manual_error_entries` 的确认批次/时间戳，会审修订）——归 M4；
  - 复测计划的 planner 消费实现（间隔算法输出 → 计划排期）——归规划侧/知几，本提案只定算法（含 B 分支重排与 depth=0 的 B 间隔算法，会审修订）；
  - 三方会审：测量案 → 教研（琢玉）+ 认知（知几）交叉审查（**本版已并入琢玉/知几修订意见**）→ 爸爸拍板（§5.4，`design:259-269`）。
- **消费方影响**（统一后）：
  - 周信快照（A/B/C/D）语义不变但**数值更可信**（收口验收项，`design:360`）；
  - `weekly_summary` 状态快照、图谱点亮、planner 信号（`orchestrator.py:363-396` 的 planner_signal 继续由 payload 元数据驱动）均不受存储枚举变化影响；
  - 防过度诊断闸门 #3 / §4.3 认知跳跃信号 / §6.1 异常提示全部消费统一计数器（**仅系统判定事件**），口径一致；M1 动作层独立计数只驱动回查/预警，不驱动档案（会审修订）。

---

*本提案只读代码/数据，唯一写入为本文档；一切代码改动待 M2.5 落地（听云实现、观止验证、镜花架构复审）。*
