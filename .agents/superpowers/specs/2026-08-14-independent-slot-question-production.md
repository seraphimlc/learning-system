# Independent Slot Question Production Implementation Plan (Superseded)

> This document is retained as historical design context only. It is superseded by [Question Bank Production Flow v3](./2026-08-26-question-production-flow-v3.md). Do not execute this plan: its fixed capacity language and state model are no longer authoritative.

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan after approval. Do not start production before the plan is approved.

**Goal:** 将题库生产改造成“图谱驱动、约 1,000 个题位、主模型负责产出与整合、风险触发式批评、单题入库、失败隔离”的稳定任务队列，并保留完整质量证据。

**Architecture:** 题位设计、主模型命题、针对性批评、题库写入和孩子端激活分成边界。主模型负责理解 slot brief、生成候选和整合批评；专家只在架构、组合覆盖、高风险或不确定项上介入。程序只负责 schema、哈希、状态、数量、并发、幂等和写入，不替模型做数学或教育语义判断。

**Tech Stack:** Python 3、新建的 `learning_system.admin` v20 模块、SQLite/JSON 存储、ThreadPoolExecutor、现有通用模型路由和 v20 receipt 存储。

**Authorization:** `PLAN_ONLY`. Do not implement, call models, generate slot briefs, create candidates or alter the question bank until the user reviews this plan and explicitly says to start.

---

## 0. Mandatory Phase 0: Define, Review and Freeze the Slot Capacity

This phase is a hard prerequisite for all question generation. It is not a warm-up batch and it does not generate concrete questions. The target capacity is approximately 1,000 slots, with an allowed range of 900-1,100. The exact count is determined by the approved graph architecture and quality review; it must not be inflated to hit a number.

Until the final manifest is `FROZEN`, no concrete question-generation worker, candidate record or item-review call may be started. Planning/review calls for the architecture and slot briefs are allowed only after the user explicitly authorizes execution; this plan review itself makes no model calls.

### Task 0.1: Define the graph-bound question architecture

**Files:**

- Create: `data/question_banks/v20/slot_architecture_v20.json`
- Create: `learning_system/admin/slot_architecture.py`
- Create: `tests/test_v20_slot_architecture.py`

- [ ] Read the current graph as the only node source and define question families per node/cluster.
- [ ] Define the educational purpose, evidence target, difficulty range and modality boundary for each family.
- [ ] Define the target capacity range (`900 <= planned_slot_count <= 1100`) and the exact planned count selected by the architecture.
- [ ] Define inventory totals and collision groups without using quota-only slots.
- [ ] Define the child-facing language and content-source policy; external material must carry a provenance receipt and must not be fabricated.
- [ ] Validate the architecture schema and graph bindings.

#### Design requirements

Define the question architecture from the current math knowledge graph before assigning individual slots. The architecture must specify, per graph node or node cluster:

- which question families are educationally useful;
- the purpose of each family: explanation/diagnostic, guided practice, independent practice or controlled challenge;
- expected evidence of understanding;
- allowed difficulty and representation modes;
- how many slots are appropriate and why;
- what counts as a meaningful variation and what is forbidden as repetition;
- visual interaction requirements and the boundary between visual and text-only slots.

The architecture must preserve the project rule of few, purposeful questions. A slot is not justified by reaching a quota; it must have a distinct measurement or practice purpose.

**Output:** `data/question_banks/v20/slot_architecture_v20.json`

### Task 0.1A: Review and freeze the architecture distribution

**Files:**

- Create: `data/question_banks/v20/slot_architecture_review_policy_v20.json`
- Create: `data/question_banks/v20/slot_architecture_receipts/`
- Create: `learning_system/admin/slot_architecture_review.py`
- Create: `tests/test_v20_slot_architecture_review.py`

- [ ] Have the math-education, assessment and child-learning experts independently review the architecture before any brief is authored.
- [ ] Freeze numeric totals by graph node, question family, purpose, difficulty, production mode and response modality for the selected planned count.
- [ ] Review the proposed distribution for educational value, progression and over-concentration of easy or repetitive items.
- [ ] Reject any quota inherited from v18/v19 without a new evidence-backed decision.
- [ ] Require all three architecture reviews to pass before Task 0.2 starts.

The architecture review is a portfolio decision, not a majority vote. A failed review returns the architecture to Task 0.1; it is not patched in the slot inventory.

**Output:** reviewed architecture receipts and an approved distribution matrix embedded in `slot_architecture_v20.json`.

### Task 0.2: Define the independent slot briefs

**Files:**

- Create: `data/question_banks/v20/slot_briefs_v20.json`
- Create: `data/question_banks/v20/slot_brief_generation_contract_v20.json`
- Create: `learning_system/admin/slot_brief_generation.py`
- Create: `learning_system/admin/slot_brief_inventory.py`
- Create: `tests/test_v20_slot_brief_inventory.py`

- [ ] Produce exactly `planned_slot_count` brief records from the approved architecture, where `planned_slot_count` is between 900 and 1,100.
- [ ] Version the brief-generation prompt/contract and record the source architecture hash for every brief.
- [ ] Validate unique slot ids, graph bindings, distribution totals and operation keys.
- [ ] Validate each brief has an independent purpose and collision group.
- [ ] Reject any brief that contains a finished question instead of a production requirement.

#### Brief requirements

Create exactly `planned_slot_count` independent slot briefs from the approved architecture. A slot brief describes the task to be produced later; it is not a question and must not contain a concrete instance that could be mistaken for a finished item.

Every brief must include:

- stable `slot_id` and `operation_key`;
- graph node binding and prerequisite context;
- question family and learning purpose;
- difficulty, mode and response modality;
- required reasoning/evidence target;
- permitted variation space;
- forbidden surface structures and collision group;
- expected answer-contract shape;
- visual renderer/resource authority when applicable;
- generation and review policy version.

The inventory must meet the approved architecture totals exactly. The program may validate counts and bindings, but it may not decide educational adequacy through string matching or regular expressions.

**Output:** `data/question_banks/v20/slot_briefs_v20.json`

### Task 0.3: Review slot briefs with the lead model and targeted critics

**Files:**

- Create: `data/question_banks/v20/slot_review_policy_v20.json`
- Create: `learning_system/admin/slot_brief_review.py`
- Create: `data/question_banks/v20/slot_review_receipts/`
- Create: `tests/test_v20_slot_brief_review.py`

- [ ] Run the math-education, assessment and child-learning reviews independently for every slot.
- [ ] Persist brief hash, policy hash, invocation id, raw response hash, verdict, confidence and findings.
- [ ] Route rejected briefs back to Task 0.2 as new brief versions.
- [ ] Prove that no concrete question generation call occurs in this task.

#### Review requirements

Review the slot inventory before freeze. The lead model owns the first-pass synthesis. Targeted critics are used according to risk:

1. `math_education_architect`: mathematical purpose and prerequisite coherence;
2. `assessment_architect`: evidence target, scorable contract and collision value;
3. `child_learning_reviewer`: age appropriateness and child-facing burden.

The three lenses are mandatory for architecture and portfolio review, but are not three full model calls for every ordinary slot. Individual slot briefs receive a lead-model consistency check; targeted critics review all high-risk slots and a risk-based sample of ordinary slots. A slot is escalated when the lead model marks uncertainty, the brief is challenge/visual/external-resource, or portfolio review finds a collision or coverage concern.

Reviewers must judge the slot brief, not a generated question. Each receipt stores the brief hash, architecture hash, reviewer invocation id, raw response hash, verdict, confidence and actionable findings. A failed brief returns to 0.2 for redesign; it is never silently patched after approval.

**Output:** one lead consistency receipt per slot, plus targeted critic receipts for escalated slots, under `data/question_banks/v20/slot_review_receipts/` and a review summary.

### Task 0.3A: Review the planned slot portfolio as a whole

**Files:**

- Create: `data/question_banks/v20/slot_portfolio_review_receipts/`
- Create: `learning_system/admin/slot_portfolio_review.py`
- Create: `tests/test_v20_slot_portfolio_review.py`

- [ ] Check coverage against the frozen architecture and graph prerequisite paths.
- [ ] Check cross-slot semantic and structural collision groups, including different nodes with the same task pattern.
- [ ] Check that guided, practice and challenge items have a purposeful progression rather than a quantity-first distribution.
- [ ] Check that difficulty and response modalities are appropriate for the target child and available renderers.
- [ ] Require the portfolio review to pass before Task 0.4 can freeze the manifest.

This review may use summary packets for efficiency, but the decision must cite the exact `planned_slot_count` slot hashes and the reviewed architecture hash. A failed portfolio review sends affected briefs back to Task 0.2; it does not permit freezing a known-bad inventory.

### Task 0.4: Freeze the reviewed slot manifest

**Files:**

- Create: `data/question_banks/v20/slot_manifest_v20.json`
- Create: `data/question_banks/v20/slot_manifest_v20.sha256`
- Create: `learning_system/admin/slot_manifest.py`
- Create: `tests/test_v20_slot_review_freeze.py`

- [ ] Verify exactly `planned_slot_count` unique briefs, with required lead checks and risk-based critic receipts.
- [ ] Bind graph, architecture, brief inventory and review-policy hashes.
- [ ] Transition only `DRAFT -> REVIEWED -> FROZEN`.
- [ ] Add a pre-generation guard that rejects queue creation without this frozen manifest.
- [ ] Make any changed brief create a new manifest version and invalidate only affected slots.

#### Freeze requirements

After all `planned_slot_count` briefs have passed review, create a versioned manifest containing the graph hash, architecture hash, brief inventory hash, review policy hash, per-slot hashes and the exact approved distribution. The manifest transitions through `DRAFT -> REVIEWED -> FROZEN` only when all completeness and review invariants pass.

The `FROZEN` manifest is the only source from which the production queue may be populated. Any change to the graph, architecture, brief, renderer authority or review policy creates a new manifest version and invalidates only affected slots; it cannot silently reuse old receipts.

**Output:**

- `data/question_banks/v20/slot_manifest_v20.json`
- `data/question_banks/v20/slot_manifest_v20.sha256`

### Phase 0 exit gate

Phase 0 passes only if all of the following are true:

- `planned_slot_count` is between 900 and 1,100;
- exactly `planned_slot_count` unique slot ids exist;
- every slot binds to an existing graph node and approved question family;
- every slot has the required lead check, and every escalated slot has the required critic receipts;
- all distribution totals match the architecture;
- every receipt references the correct brief and policy hashes;
- the manifest is `FROZEN` and its hash is recorded;
- a pre-generation guard rejects every queue-start attempt without this frozen manifest.

The first production task is therefore not queue implementation. It is completing and freezing this manifest.

## 1. Scope and Decisions

### 1.1 Retain

- 900-1,100 个冻结 slot brief 作为生产事实源，具体数量由冻结 manifest 的 `planned_slot_count` 确定。
- 每道题单题生成，不把多道题塞进一次生成 prompt。
- 主模型负责产出和整合；普通题按风险调用少量针对性 critic，高风险题才调用多视角 critic。
- 语义重复检查和完整原始评审证据。
- adjudicator 只在风险规则触发且 critic 无法解决分歧时触发。
- 通过题目独立写入 staged bank。

### 1.2 Remove from the active path

- “一批题全部完成后才能入库”的 atomic batch gate。
- 普通题默认调用完整专家委员会。
- 普通题默认调用独立语义 QA 和 child-surface leakage review。
- 页面级 child-surface 检查阻塞题目入库。
- 为了重跑一批而重新执行已经成功的题位。

### 1.3 Replacement and cleanup

旧的 batch atomic 生产逻辑、批次波次重试逻辑和重型默认审查编排不再保留兼容分支。实现时直接删除主动调用路径、旧状态转换和只服务于旧路径的代码与测试。

旧题目、候选题、staged bank、生成/评审/碰撞回执、旧运行记录和历史管理端报告全部视为废弃资产并删除。新系统从空题库开始，不迁移旧题目、不复用旧 review receipt、不读取旧运行记录。

## 2. Target Runtime Flow

```text
frozen slot brief
  -> queued job
  -> route preflight
  -> lease slot
  -> lead model generates one candidate and self-check
  -> contract validation
  -> risk-tier selection
  -> targeted critic(s) only when required
  -> lead model synthesis when criticism exists
  -> targeted collision review
  -> individual v20 staged commit
```

每个阶段都写入 checkpoint。阶段失败只回到该阶段；内容改变后从 generation version 重新开始，并使旧 critic、synthesis、collision 和 commit receipt 失效。

## 3. State Model

### 3.1 Job states

```text
PENDING
LEASED
GENERATING
CONTRACT_CHECK
LEAD_SELF_CHECK
RISK_TIERED_REVIEW
CRITIC_REVIEW
LEAD_SYNTHESIS
ADJUDICATION_REQUIRED
COLLISION_CHECK
READY_FOR_COMMIT
COMMITTING
STAGED
RETRYABLE_MODEL_ERROR
SEMANTIC_REJECT
ROUTE_BLOCKED
LEASE_RECOVERABLE
PERMANENTLY_BLOCKED
PAUSED
DRAINING
COMPLETED
FAILED
```

### 3.2 State rules

- `STAGED` 只表示该 slot 有完整生成、评审、碰撞和入库证据。
- `READY_FOR_COMMIT` 不依赖其它 slot 的状态。
- `SEMANTIC_REJECT` 只消耗当前 slot 的语义版本预算。
- Lead self-check is not treated as independent evidence; risk-tiered critic evidence is required before commit.
- `RETRYABLE_MODEL_ERROR` 不计入语义失败，不改变题位质量统计。
- `ROUTE_BLOCKED` 是 worker 基础设施状态，不逐题重复调用。
- `PAUSED`、`DRAINING`、`COMPLETED` 和 `FAILED` 描述运行控制状态，不覆盖 slot 的最后阶段证据。
- 过期 lease 由恢复器回收，不允许人工删除锁文件作为正常恢复手段。

## 4. Review Policy v2

### 4.1 Lead model responsibility

The lead model receives one frozen slot brief and one compact generation packet. It returns exactly one candidate, its answer contract, a concise self-check and an uncertainty/risk declaration. The self-check may expose likely weaknesses, but it is not counted as independent review.

### 4.2 Risk-tiered targeted criticism

The program assigns a review tier from frozen slot metadata and explicit risk rules; it does not infer educational quality with regex or keyword matching:

- `R1 ordinary`: one independent critic selected for the slot's primary risk;
- `R2 elevated`: two independent critics covering different risk lenses;
- `R3 high-risk`: math, assessment and child lenses, plus adjudication when they disagree.

R2/R3 applies to challenge items, visual/interactive items, external-resource items, new question families, lead-model uncertainty, collision concerns and any prior repair. The critic lenses are `math_education`, `assessment`, and `child_learning`. Each critic uses a separate invocation and saves the candidate, packet and brief hashes.

The policy must classify each review as `PASS`, `REVISE` or `BLOCKED` and require structured reasons. A question is not accepted merely because its arithmetic answer is correct. Critics must check graph binding, age appropriateness, educational purpose, solvability, answer-contract completeness, meaningful difficulty and collision value. A shallow mechanical drill, fake reasoning wrapper, ambiguous condition, unsupported modality, wrong node, mathematically invalid answer contract or semantically redundant item is `REVISE` or `BLOCKED`.

The lead model may synthesize critic findings, but it cannot erase a hard blocker. Minor non-scoring writing preferences may be recorded without rejection; missing core evidence, incorrect mathematics or loss of the intended learning signal requires revision.

### 4.3 Conditional adjudication

只有以下情况才启动 `adjudicator`：

- R3 critics 的 verdict 不一致；
- 任意 critic 报告 P0/P1 但其它证据未报告；
- lead synthesis 无法解决冲突；
- 相似题是否具有独立教育价值无法达成一致。

`expert_board` 不再作为每题默认阶段。

### 4.4 Moved checks

- schema、哈希、题位绑定、评分点总和等确定性检查由程序执行。
- 题目数学意义、教学价值、语义相似度仍由模型判断。
- child-surface leakage 迁移到浏览器/页面 QA，不进入普通题生产 gate。
- `staging_decision` 由程序检查完整 PASS receipts 后执行，不调用模型。

## 5. Data Boundaries

### 5.1 Slot definition

`slot_briefs_v20.json` and the frozen manifest must define the following fields; there is no legacy manifest to extend:

- `slot_id`
- `measurement_intent_id`
- `slot_brief_version`
- `slot_brief_sha256`
- `node_id`
- `question_family_id`
- `difficulty`
- `production_mode`
- `required_evidence`
- `allowed_variations`
- `forbidden_variations`
- `collision_group_id`
- `operation_key`

The production queue may read only `slot_manifest_v20.json` with status `FROZEN`. It must not infer slots from question-bank rows, retired run records or graph nodes at runtime.

### 5.2 Question candidate

candidate 不可变。重新生成必须创建 `candidate_version + 1`，不能覆盖旧内容。

candidate 必须绑定：

- slot operation key；
- generation invocation evidence；
- candidate content hash；
- generation prompt packet hash；
- current review policy version。

### 5.3 Review receipt

v20 critic receipt is an append-only record independent of the legacy single-review runtime table. The v20 source of truth must support multiple critics per candidate:

- reviewer role；
- invocation id；
- input packet hash；
- candidate hash；
- verdict；
- confidence；
- findings；
- raw response hash；
- created timestamp。

The existing `question_review_records` table may receive a compatibility projection for child scheduling, but it cannot be the only storage for v20 critic evidence. Candidate revisions must invalidate all prior v20 critic, synthesis, collision and commit receipts through candidate hash/version binding.

### 5.4 Commit receipt

单题 commit receipt 保存：

- slot id；
- candidate id/version；
- all required receipt hashes；
- collision receipt；
- staged bank before/after hash；
- idempotency key；
- commit result。

### 5.5 Child runtime contract

The generated question and answer contract are separate from the slot brief and from production receipts. The child runtime receives only a safe projection containing:

- child-facing prompt and supported response mode;
- standard answer and accepted semantic equivalents;
- scoring points and non-scoring writing expectations;
- teaching explanation and improvement direction;
- graph node display label and runtime action handle.

Production ids, reviewer roles, prompts, provider/model names, operation keys and internal graph structure remain in the internal evidence store.

### 5.6 Visual authority

Every visual slot must bind to a versioned renderer/resource authority and an answer-capture contract. A missing renderer, asset, geometry receipt or browser evidence leaves the slot blocked; it cannot be silently changed into a text-only item.

### 5.7 Run manifest and report

Every production run has a run id and binds to exactly one frozen slot-manifest hash. The run record includes per-slot status, current stage, candidate version, retry counters, receipt references, error category and timestamps. Reports are queryable by Codex in JSON/Markdown and never contain credentials or child-private data.

### 5.8 Identity and activation invariants

- Every v20 slot, job, candidate, critic receipt, synthesis receipt, collision receipt and commit receipt binds `manifest_sha256`, `slot_id`, `operation_key`, `candidate_version` and the relevant content hash.
- Activation validates the frozen manifest's one-to-one slot set, not only item count and node count.
- The internal evaluator contract is never the child payload. The child receives a separate allowlisted DTO without standard answers, scoring rubric, slot/candidate/attempt ids, provider/model data or internal graph structure.
- Legacy v17/v12/batch paths are not allowed to become v20 fallbacks. Existing runtime compatibility is an explicit adapter with a v20 test, not an import or data-source shortcut.

## 6. Queue and Concurrency

### 6.1 Queue unit

队列元素是一个 slot job，不是一个 batch：

```json
{
  "job_id": "JOB-...",
  "slot_id": "...",
  "operation_key": "...",
  "candidate_version": 1,
  "stage": "GENERATING",
  "attempt": 1,
  "status": "PENDING"
}
```

### 6.2 Worker rules

- 生产阶段默认并发 2，可由路由能力配置上限。
- reviewer 调用也受同一个全局模型调用 semaphore 限制。
- 单题正式写库使用独占 v20 staged-bank 锁。
- 队列调度不把同一 `collision_group_id` 同时提交；生成可以并行，碰撞检查和 commit 必须重新读取最新索引。
- 任何 job 都使用稳定 idempotency key，重复恢复不得重复生成或重复入库。

### 6.3 Route preflight

worker 启动前只做一次：

- base URL 格式检查；
- DNS/TLS 连通性；
- 鉴权；
- 所需模型可用性；
- 请求大小预算。

预检失败时整个投递器进入 `ROUTE_BLOCKED`，不启动新的 slot，不让每个 slot 单独撞同一个错误。

## 7. Recovery Rules

- 传输错误、限流、临时超时：只重试当前阶段，最多 2 次。
- 语义拒绝：新建 candidate version，最多 3 个版本。
- critic 或 synthesis 已成功但后续阶段失败：从 checkpoint 恢复，不重复成功调用。
- commit 前崩溃：通过 commit idempotency key 重放，不重新生成题目。
- 发现 candidate 内容变化：旧 critic、synthesis、collision、commit receipt 全部失效。
- 同一 slot 连续两轮因同一原因失败：暂停该 slot，要求重新评审 slot brief。

## 7.1 Stop, retry and promotion gates

### Immediate stop: architecture or data invariant

The run must stop immediately when any of these occurs:

- a successful slot cannot commit independently;
- a successful candidate or commit is written twice;
- slot, candidate, review or commit evidence is bound to the wrong hash;
- a slot invokes more critic calls than its frozen risk tier permits without a declared escalation trigger;
- route preflight fails but new per-slot model calls continue;
- progress cannot distinguish staged, reviewing, retryable and blocked jobs;
- the obsolete batch atomic path is invoked;
- a semantically rejected or collided candidate enters the bank.

合法的阶段重试不属于重复调用。只有同一成功 operation 在没有 retry 依据时被重复执行，或产生重复 commit，才属于硬性停止。

### Local recovery: current slot or stage only

The following conditions must not stop unrelated jobs:

- transient network error, rate limit or model timeout;
- malformed reviewer response;
- expired lease;
- semantic review rejection;
- collision rejection;
- single-item write conflict.

The worker retries or parks only the affected stage/slot and continues other queue work.

### Promotion gates: do not scale until evidence passes

Promotion gates are not failures of the whole system. They prevent moving to the next scale:

1. one synthetic slot completes the full path;
2. two concurrent slots prove one success and one isolated failure;
3. a risk-based canary of 6-10 representative slots covers ordinary, challenge, semantic rejection, retry and multiple nodes;
4. only then may full-bank production begin.

The canary size is not a product or storage constraint. It can change with risk coverage, but the scenarios above are mandatory.

## 8. Plan Integrity Gate Before User Review

This is a planning-only gate. It runs without source-code implementation, concrete question generation or model calls.

- [ ] Every product requirement maps to a task, an output artifact and a focused test.
- [ ] The capacity rule is expressed once as `900 <= planned_slot_count <= 1100`; no task silently requires exactly 1,000.
- [ ] Architecture review, slot-brief review, candidate review, portfolio review, child-runtime bridge and activation each have distinct evidence.
- [ ] Lead-model work is separated from targeted criticism; no ordinary slot defaults to a full committee.
- [ ] Every task has an explicit predecessor, failure behavior and recovery boundary.
- [ ] Every generated artifact has a version/hash/lineage rule and every mutable operation has an idempotency rule.
- [ ] No concrete generation call can occur before a user-approved frozen manifest.
- [ ] The plan contains no active reference to retired v18/v19 production modules, batch-atomic paths or historical question data.
- [ ] The final acceptance path proves planned-count coverage, child-runtime consumption, activation and rollback.

The plan status after this gate is `PLAN_READY_FOR_USER_REVIEW`. It must not become executable merely because the document passes its own checks. Only the user's explicit instruction to start changes the authorization state.

## 9. File-Level Implementation Plan

Implementation is deliberately split into small vertical slices. No later task may start until the previous slice has a focused test, a written output artifact, and a clean state transition. The active code path must not contain a compatibility switch back to batch atomic production.

### Task 1: Define the new empty-bank and slot-job contracts

**Files:**

- Create: `data/question_banks/v20/question_bank_manifest_v20.json`
- Create: `learning_system/admin/slot_production_queue.py`
- Create: `learning_system/admin/v20_bank_namespace.py`
- Create: `learning_system/admin/v20_receipts.py`
- Create: `scripts/reset_question_bank_v20.py`
- Create: `tests/test_v20_slot_contracts.py`
- Create: `tests/test_v20_bank_namespace.py`
- Create: `tests/test_v20_receipt_identity.py`

- [ ] Define the empty bank schema, slot job schema, stage names and terminal statuses.
- [ ] Require a `FROZEN` `slot_manifest_v20.json` before any queue job can be created.
- [ ] Establish the v20 question-bank namespace and explicitly remove retired question-bank artifacts from the active runtime path.
- [ ] Preserve or delete learning attempts only according to an explicit data-scope rule; never delete them as an accidental side effect of bank reset.
- [ ] Define the stable operation key formula and candidate version rules.
- [ ] Define canonical JSON serialization and hash rules shared by manifests, candidates, receipts and reports.
- [ ] Define append-only v20 critic/commit receipt persistence instead of overloading the legacy one-review table.
- [ ] Test that an empty install contains zero questions and no historical run binding.
- [ ] Test that invalid state transitions fail closed.

### Task 2: Implement queue claim, lease and checkpoint persistence

**Files:**

- Modify: `learning_system/admin/slot_production_queue.py`
- Create: `learning_system/admin/slot_job_state.py`
- Create: `tests/test_v20_slot_queue_lease.py`

- [ ] Implement one-slot claim and acknowledgement.
- [ ] Implement lease expiry recovery without deleting state.
- [ ] Implement stage checkpoint persistence and idempotent replay.
- [ ] Test duplicate delivery, expired lease and process interruption.

### Task 3: Define the compact generation packet

**Files:**

- Create: `learning_system/admin/question_generation_packet.py`
- Create: `data/question_banks/v20/question_generation_contract_v20.json`
- Create: `learning_system/prompts/question_generation_v20.md`
- Create: `tests/test_v20_generation_packet.py`

- [ ] Build a packet from one frozen slot brief, relevant graph summary, answer contract and collision group.
- [ ] Reject packets that exceed the request-size budget before a model call.
- [ ] Bind the packet hash to the candidate and all later review receipts.
- [ ] Test that unrelated historical run data is never included in a packet.
- [ ] Enforce one slot and one concrete question per generation invocation; no hidden multi-question batch path.

### Task 4: Implement one-slot generation only

**Files:**

- Create: `learning_system/admin/independent_slot_production.py`
- Create: `tests/test_v20_single_slot_generation.py`

- [ ] Generate exactly one candidate for one slot and one candidate version.
- [ ] Persist raw model invocation evidence and candidate hash.
- [ ] Retry transport failures only at the generation stage.
- [ ] Test semantic rejection creates a new candidate version and never mutates the old candidate.

### Task 5: Implement risk-tiered targeted criticism

**Files:**

- Create: `data/question_banks/v20/question_authority_review_policy_v20.json`
- Create: `data/question_banks/v20/question_reviewer_contracts_v20.json`
- Create: `learning_system/prompts/question_review_v20.md`
- Create: `learning_system/admin/standard_question_review.py`
- Create: `learning_system/admin/question_critic_receipts.py`
- Create: `tests/test_v20_standard_review.py`

- [ ] Make lead self-check plus risk-tiered criticism the required default path.
- [ ] Define the math, assessment and child-learning critic contracts.
- [ ] Run only the critic calls required by the frozen risk tier, with separate invocation ids.
- [ ] Persist each raw response, verdict, confidence and findings.
- [ ] Persist multiple critic receipts per candidate without overwriting or collapsing reviewer identity.
- [ ] Test R1, R2 and R3 items, including that an ordinary R1 item does not invoke a full committee.

The review policy must define the structured verdict schema, confidence handling, hard-reject conditions, and the exact evidence required for `PASS`. Reviewers may judge semantic and educational facts; program code may only enforce schema, hash and receipt invariants.

### Task 6: Add conditional adjudication only

**Files:**

- Create: `learning_system/admin/question_review_adjudication.py`
- Create: `tests/test_v20_conditional_adjudication.py`

- [ ] Define explicit disagreement, uncertainty and high-risk triggers.
- [ ] Call the adjudicator only when a trigger is present.
- [ ] Require the adjudicator to cite the conflicting receipts.
- [ ] Test no-adjudication, targeted-criticism and adjudication-required paths.

### Task 7: Add collision review and index update

**Files:**

- Create: `learning_system/admin/question_collision_index.py`
- Create: `tests/test_v20_question_collision.py`

- [ ] Check exact hash and structural fingerprint before model comparison.
- [ ] Retrieve same-node, related-node and in-flight collision candidates only.
- [ ] Use a model for the final semantic duplicate decision.
- [ ] Update the index only after a successful single-item commit.
- [ ] Test concurrent candidates, exact duplicates and legitimate variants.

### Task 8: Implement single-item commit

**Files:**

- Create: `learning_system/admin/individual_question_commit.py`
- Create: `tests/test_v20_individual_question_commit.py`

- [ ] Make the new individual commit function the only active write path.
- [ ] Enforce candidate/slot/review/collision hash binding before the bank write.
- [ ] Enforce frozen-manifest one-to-one slot binding before the bank write.
- [ ] Make commit idempotent by slot and candidate version.
- [ ] Ensure one failed slot cannot roll back a previously committed slot.
- [ ] Update the collision index and job status in the same commit boundary.
- [ ] Test one success plus one failure, repeated delivery and write interruption.

### Task 9: Implement the worker pool and route preflight

**Files:**

- Create: `learning_system/admin/slot_worker_pool.py`
- Create: `learning_system/admin/model_route_preflight.py`
- Create: `tests/test_v20_worker_pool.py`

- [ ] Dispatch independent slot jobs with the global concurrency limit.
- [ ] Run route preflight before creating model work.
- [ ] Refill workers immediately after a slot completes or is parked for retry.
- [ ] Keep model concurrency and file-write locking separate.
- [ ] Test two concurrent jobs where one fails and the other commits.

Route and audit rules must keep provider/model names, credentials, internal prompts and reviewer traces out of the child-facing projection. Model failures must be classified as retryable, route-blocked or semantic failure without changing business decisions in provider-specific code.

### Task 10: Replace the runner and delete obsolete orchestration

**Files:**

- Create: `scripts/run_question_slot_production.py`
- Modify: `docs/project-rules/question-production-cleanup-manifest.md`
- Create: `tests/test_v20_obsolete_path_absence.py`

- [ ] Verify that `atomic_batch_staging`, `atomic_batch_target_count` and `WAITING_FOR_ATOMIC_BATCH` are absent from the active path.
- [ ] Verify that no batch-wave retry or cohort re-dispatch path exists.
- [ ] Remove stale imports from `learning_system/admin/__init__.py`; do not restore deleted production modules to satisfy imports.
- [ ] Verify v20 code does not use v17/v12 bank constants or legacy batch/answer-contract generation as a fallback.
- [ ] Keep the cleanup manifest as a record of retired modules, flags, states and artifact types; do not restore them for compatibility.
- [ ] Verify the new runner starts from an empty question bank and empty production artifact directories.

### Task 11: Add progress and hard stop gates

**Files:**

- Create: `learning_system/admin/production_progress.py`
- Create: `tests/test_v20_progress_and_stop_gates.py`

- [ ] Report only staged, reviewing, retryable, route-blocked and permanently-blocked counts.
- [ ] Persist per-slot current stage and last error category.
- [ ] Stop the run when a red-line invariant fails; do not continue to consume model calls.
- [ ] Test progress after success, semantic rejection, route block and restart.

### Task 12: Run vertical and risk-based acceptance before scale

**Files:**

- Create: `tests/test_v20_independent_production_acceptance.py`
- Create: `docs/project-rules/question-production-acceptance-v20.md`

- [ ] Run one synthetic slot end to end.
- [ ] Complete the first child-runtime vertical slice with one active text-only question and its real submit/async feedback path.
- [ ] Run two slots concurrently with one forced failure.
- [ ] Run a 6-10 slot risk-based canary covering ordinary, challenge, semantic rejection, retry and multiple nodes.
- [ ] Do not start full-bank production until all red-line tests pass.
- [ ] Run the focused v20 tests, then the remaining relevant suite.

This task validates the producer only. It does not authorize child-facing activation; activation requires Tasks 13-17.

### Task 13: Define the question and answer-contract bridge to the child runtime

**Files:**

- Create: `data/question_banks/v20/question_candidate_contract_v20.json`
- Create: `data/question_banks/v20/answer_contract_v20.json`
- Create: `learning_system/admin/question_candidate_contract.py`
- Create: `tests/test_v20_child_runtime_bridge.py`
- Create: `data/question_banks/v20/child_question_dto_v20.json`
- Create: `data/question_banks/v20/evaluator_contract_v20.json`

- [ ] Define the internal evaluator fields: standard answer, accepted equivalent answers, scoring points, non-scoring writing details and evidence target.
- [ ] Define a separate allowlisted child DTO: prompt, supported input mode, display explanation and child-safe action handle only.
- [ ] Map the v20 item to the existing `question_items`, review records, usage policy and answer-contract consumers without leaking internal production metadata.
- [ ] Support the declared response modes explicitly: text, choice/fill where applicable, photo, voice and handwriting; unsupported modes block the slot instead of silently degrading.
- [ ] Verify the child-safe projection contains no slot id, candidate id, attempt id, provider, reviewer prompt or internal graph structure.
- [ ] Test the first vertical slice with one active text-only question; do not block the first slice on every future modality.
- [ ] Test that each later production-mode slot is either selected/rendered by a real consumer or remains explicitly blocked.

### Task 14: Implement visual and interactive question authority

**Files:**

- Create: `data/question_banks/v20/visual_slot_registry_v20.json`
- Create: `learning_system/admin/visual_question_authority.py`
- Create: `tests/test_v20_visual_question_authority.py`
- Create: `tests/browser_v20_question_rendering.mjs`

- [ ] Register the renderer, asset authority, interaction contract and answer-capture contract for every visual slot.
- [ ] Verify visual geometry, labels, hit areas and captured values against the slot brief.
- [ ] Block any slot whose renderer or resource authority is not available; never convert it to a text question automatically.
- [ ] Run representative desktop and 390px browser checks for visual, interactive and non-visual items.

### Task 15: Stage, activate and roll back the v20 bank safely

**Files:**

- Create: `learning_system/admin/question_bank_v20_activation.py`
- Create: `scripts/activate_question_bank_v20.py`
- Create: `tests/test_v20_question_bank_activation.py`

- [ ] Build an activation manifest from the frozen slot manifest, staged item receipts, answer contracts and visual authority receipts.
- [ ] Require exactly `planned_slot_count` eligible items, one item per frozen slot, zero unresolved blockers and matching graph/manifest hashes.
- [ ] Validate the frozen manifest's exact slot set and one-to-one item mapping; item count alone is insufficient.
- [ ] Generate and validate the child runtime usage policy for purpose, node, evidence role and cooldown selection.
- [ ] Stage first, back up the production database, then activate in one transaction using the existing question-bank ledger boundary.
- [ ] Verify the child runtime reads the new active version and does not see staged, rejected, retired or internal evaluator fields.
- [ ] Test failed activation, restart during activation and explicit rollback to the previous active version.

Activation is a separate transaction from generation. A completed production queue does not automatically change what the child sees.

### Task 16: Add Codex-queryable production reports and run control

**Files:**

- Create: `learning_system/admin/question_production_report.py`
- Create: `learning_system/admin/question_production_run.py`
- Create: `scripts/query_question_production.py`
- Create: `tests/test_v20_production_reports.py`
- Create: `docs/project-rules/question-production-runbook-v20.md`

- [ ] Persist run id, frozen manifest hash, per-slot stage, candidate version, retry count, reviewer receipt summary, collision result and last error.
- [ ] Support pause, resume, drain and safe shutdown without cancelling successful slots.
- [ ] Expose JSON and Markdown reports for Codex queries; do not build a management Web UI.
- [ ] Distinguish `staged`, `reviewing`, `retryable`, `blocked`, `failed`, `activated` and `retired` counts.
- [ ] Record model-call count, elapsed time, retry count and provider-neutral cost metadata when available.
- [ ] Redact credentials, internal prompts and child data from reports while retaining hashes and evidence references.

### Task 17: Full-bank portfolio QA, repair and final acceptance

**Files:**

- Create: `learning_system/admin/full_bank_v20_acceptance.py`
- Create: `tests/test_v20_full_bank_acceptance.py`
- Create: `docs/project-rules/question-production-acceptance-v20.md`

- [ ] Verify exactly `planned_slot_count` staged items, exact one-to-one slot coverage, zero missing answer contracts and zero unresolved review/collision receipts.
- [ ] Verify every candidate has one internal evaluator contract and one valid child DTO, with no cross-surface field leakage.
- [ ] Run cross-node semantic collision, difficulty distribution, modality, graph-lineage and child-surface audits over the complete bank.
- [ ] Route failed items through a repair manifest that invalidates only the affected slot and its downstream receipts.
- [ ] Repeat the affected audits after repair; no item may be marked complete merely because a run ended.
- [ ] Produce a final acceptance report with command results, database facts, receipt hashes and child-runtime evidence.
- [ ] Only after this report passes may Task 15 activate the bank.

## 10. Acceptance Criteria

The implementation is accepted only when:

- The architecture itself has three independent expert approvals with an explicit numeric distribution matrix.
- The slot inventory contains exactly `planned_slot_count` briefs, where `planned_slot_count` is 900-1,100, and passes both per-slot review and whole-portfolio review.
- A `FROZEN` slot manifest is required before queue creation or concrete question-generation calls.
- A successful slot is staged without waiting for any other slot.
- A failed slot can be retried without rerunning successful slots.
- Ordinary items use the critic count required by their frozen risk tier, with no default full committee.
- Fourth-party adjudication is conditional and evidence-backed.
- No candidate enters the bank without complete receipts and collision clearance.
- No duplicate or semantically redundant candidate enters the bank.
- Restart and duplicate delivery are idempotent.
- Run progress distinguishes staged, reviewing, retryable, route-blocked, blocked, failed and completed.
- Every staged item has a valid child-runtime question/answer contract and, when visual, valid renderer authority.
- Every staged item has separate internal evaluator and child DTO contracts with an allowlisted boundary.
- Activation is separate from production, validates the complete bank, backs up the database and supports rollback.
- The final bank contains exactly `planned_slot_count` eligible items, one per frozen slot, with no missing or unresolved receipts.
- The new bank starts empty and contains no references to deleted v18/v19 question data.

## 11. Execution Order After Approval

1. Complete Tasks 0.1 and 0.1A: architecture, expert review and the numeric distribution matrix.
2. Complete Tasks 0.2, 0.3 and 0.3A: `planned_slot_count` slot briefs, lead/risk-tiered reviews and whole-portfolio review.
3. Complete Task 0.4 and verify the Phase 0 exit gate. Before this point, model calls for concrete question generation are forbidden.
4. Implement Tasks 1-3, including the clean v20 namespace, queue contracts and packet contracts.
5. Implement Tasks 4-8 and pass the single-slot vertical slice.
6. Implement Tasks 9-11 and pass the two-slot failure-isolation slice.
7. Execute Task 12 and review its evidence. This still does not activate the child runtime.
8. Implement Tasks 13-16 and prove the producer-to-child-runtime bridge, visual authority, activation mechanics and Codex reports.
9. Task 12's 6-10 slot risk-based canary is the only promotion canary. After Tasks 13-16 pass, begin full production against the same frozen manifest; do not run a second ad-hoc canary path.
10. Run Task 17 after full production. Repair only affected slots, repeat the relevant audits, and require the final `planned_slot_count` acceptance report.
11. Only after Task 17 passes, execute the separate Task 15 activation transaction.
