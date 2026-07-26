# Answer Assessment Engineering Contract v5.1

Date: 2026-07-14
Owner: 听云 (`tingyun`)
Status: revised-ready-for-jinghua-rereview
Scope: scoring authority, answer-contract review, question-bank repair routing, runtime transaction/recovery, clarification/regrade, activation, and no-Git rollback

## Objective

Make accepted `attempt_assessments` the only v5.1 scoring authority, preserve the normal one-GPT answer hot path, and prevent any question from activating when its correctness, node binding, evidence role, answer contract, or fingerprint is not independently proven.

## Sources

- `docs/design/specs/2026-07-14-answer-assessment-storage-design.md`
- `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md`
- `docs/qa/test_case_spec_v5_1_assessment_dual_views.md`
- `docs/system/qa/question_bank_grade_level_latest.md`
- 镜花 `DESIGN_REVIEW_NEEDS_FIX` four-part result supplied in the 2026-07-14 repair dispatch
- `docs/collaboration/inbox.md#MSG-20260714-001`
- `AGENTS.md`

## ENGINEERING_SOURCE_READINESS

- verdict: `ENGINEERING_SOURCE_READY`
- product_source_content_ready: yes
- downstream_guessing_risk: none
- assessment_authority_ready: yes
- reviewer_input_output_contract_ready: yes
- question_repair_route_ready: yes
- queue_recovery_contract_ready: yes
- activation_rollback_ready: yes
- codebase_recon_ready: yes
- authorization_ready: documentation only
- validation_targets_ready: yes
- missing_or_low_quality_sources: none blocking this engineering contract
- activation_blockers:
  - two known semantically misbound v11 questions remain active in the current bank;
  - no 1,120-item live independent semantic review receipts exist;
  - no 镜花 rereview PASS exists for this amendment.
- stop condition: no production code before 镜花 independently reviews this contract and returns a non-blocking design verdict.

## Supersession

For v5.1 normal answer processing this contract supersedes any older clause that makes `attempts.score_points`, `attempts.result`, model-emitted totals, or downstream evaluation/planner/teaching model jobs authoritative.

Legacy `evaluation_update`, `planner_decision`, and `teaching_generation` handlers remain compatibility/replay/recovery paths only. New v5.1 normal text/photo answer paths never enqueue them.

## Authoritative Hot Path

```text
submit immutable attempt
-> enqueue one answer_analysis job
-> optional one Doubao OCR call for photo
-> one GPT criterion judgment
-> persist accepted model envelope/result refs
-> one idempotent reducer transaction
-> accepted attempt_assessment
-> exact-assessment EvidenceGate validation
-> mastery and deterministic next action
-> one child feedback/current-state projection
```

Normal text and explicit stuck submissions both enter the answer-analysis model path; explicit stuck is a child action signal, not a grading or planning decision. Photo uses one OCR call plus one answer-analysis model call. No downstream evaluation/planner/teaching model job is enqueued until the answer-analysis evidence is accepted or deliberately held pending.

## Table Ownership

| Table/domain | Owns | Must not own |
|---|---|---|
| `question_items` | immutable question content/version, bound node, evidence role, bank lineage | learner score/mastery; in-place semantic repair |
| `question_review_records` | independent question-design review lineage and active eligibility | answer assessment or silent rebinding |
| `answer_contracts` | versioned reference solution, atomic score points, dimensions, review/fingerprint lineage, inactive/active status | child response or mastery |
| `flow_steps` | exact selected question/contract/graph/bank references | scoring authority |
| `attempts` | immutable raw child text/interaction/photo references and submission idempotency | authoritative score; grading columns are compatibility projections only |
| `attempt_assessments` | criterion judgments, deterministic 10-point score, pass qualification, five feedback fields, assessment version/status/digest | raw-answer mutation or next-action authority |
| `agent_runs` / `background_jobs` | provider envelope, prompt/schema/route evidence, job state, authoritative result refs | score/mastery authority |
| `evidence_validations` | exact accepted assessment trust decision | regrading |
| `mastery_decisions` / `learner_node_status` | accepted-evidence aggregation and current node state | question scoring |
| `next_step_decisions` / `daily_summaries` | deterministic downstream decision and derived report snapshots | evidence creation |

## Authority Matrix

| Component | Authority | Forbidden authority |
|---|---|---|
| question designer | create a new immutable question candidate under a new item/bank version | activate, self-review, silently rebind an existing question |
| independent question reviewer | decide question correctness and graph-node/evidence-role fitness for the candidate | generate the candidate or reuse self-attested metadata as proof |
| answer-contract generator | draft reference solution, atomic criteria, dimensions, and fingerprints for one reviewed immutable question | change question text, expected answer, node binding, evidence role, or bank version |
| answer-contract reviewer | independently solve and judge correctness, node alignment, evidence-role alignment, contract correctness, and descriptors | edit the question, activate it, or rebind it to another node |
| GPT answer judge | judge exact stored criteria semantically and explain grounded gaps | assign points, write mastery, choose next action |
| deterministic scorer | calculate the 10-point score and pass qualification from stored points/statuses | reinterpret child mathematics |
| EvidenceGate | validate exact accepted assessment lineage and trust | change score/mastery |
| mastery/next-step reducers | aggregate accepted evidence and choose deterministic action | regrade the answer |
| reports | present accepted/current/stale/legacy facts | create evidence or conceal activation blockers |

## Question and Contract Review Boundary

### Reviewer Route

- internal agent: `answer_contract_reviewer_agent`
- task route: `answer_contract_review`
- default model: `gpt-5.5`
- environment override: `AI_ANSWER_CONTRACT_REVIEW_MODEL`
- wall timeout per shard call: 120 seconds, override `AI_ANSWER_CONTRACT_REVIEW_TIMEOUT_SECONDS`
- maximum total execution attempts per shard: 3
- retryable classes: HTTP 429/500/502/503/504, timeout, rate limit, temporarily unavailable, malformed/schema-invalid model output
- backoff after failed attempt 1 and 2: 20 seconds, then 60 seconds; honor `Retry-After` up to 180 seconds
- review-call concurrency: exactly 1
- shard size: at most 5 questions

### Reviewer Packet

One shard contains exactly one bound graph node and at most five immutable question/contract drafts.

Required node context:

- graph lineage;
- canonical node id for internal lineage, node name, one-sentence essence;
- node question types, mastery criteria, diagnostic probes, teaching contract;
- `summer_execution.mode` / summer mode;
- strict prerequisite names/essences and rollback policy;
- controlled-extension policy and allowed challenge boundary;
- question-generation/命题 contract relevant to the node.

Required per-item context:

- immutable question id, item version, question digest, candidate bank version/digest;
- prompt, answer format, expected answer, solution steps, interaction schema;
- bound node, kind, evidence role, problem family/core-stem metadata;
- question-design and independent question-review lineage;
- draft answer-contract id/version/digest, reference solution, score points, dimensions, required-for-pass flags;
- draft instance/core-structure descriptors and fingerprint policy version.

Self-attested `node_alignment.reason`, `本题重点`, kind, tags, allowlist membership, or schema validity are context only and never semantic proof.

### Reviewer Output

Per item, schema requires:

```json
{
  "question_id": "...",
  "item_version": "...",
  "question_digest": "...",
  "contract_digest": "...",
  "question_correctness": {
    "verdict": "pass|fail|ambiguous",
    "independent_solution": "...",
    "rationale": "..."
  },
  "question_node_alignment": {
    "verdict": "aligned|misbound|ambiguous",
    "actual_mathematical_core": "...",
    "tested_node_evidence": "...",
    "rationale": "..."
  },
  "evidence_role_alignment": {
    "verdict": "aligned|misaligned|ambiguous",
    "actual_evidence_demand": "...",
    "rationale": "..."
  },
  "answer_contract_review": {
    "verdict": "approved|rejected",
    "reference_solution_correct": true,
    "criteria_atomic_and_observable": true,
    "weights_and_dimensions_valid": true,
    "required_for_pass_valid": true,
    "issues": []
  },
  "normalized_instance_descriptor": {},
  "normalized_core_structure_descriptor": {},
  "confidence": 0.0
}
```

Activation approval requires all of:

- `question_correctness.verdict == pass`;
- `question_node_alignment.verdict == aligned`;
- `evidence_role_alignment.verdict == aligned`;
- `answer_contract_review.verdict == approved`;
- exact question/contract/node/graph/bank/schema/prompt digests;
- accepted `live_model` provider evidence from the configured reviewer route.

Any fail, misbound, misaligned, ambiguous, malformed, missing, digest mismatch, non-live receipt, or low-confidence result leaves the item inactive and blocks global activation.

The contract reviewer may emit repair reasons and advisory candidate nodes. It may not alter the immutable question, change the binding, manufacture a new question version, or turn its own suggestion into activation.

## Sharding, Idempotency, Checkpoint, and Receipts

### Work Partition

- 56 nodes x 20 questions = 1,120 item reviews.
- Each node is split deterministically into four ordered shards of at most five questions.
- Total expected shard count for the current bank is 224.
- Shard ordering uses immutable question id/item version after pinning the candidate bank manifest.
- Global review concurrency is exactly 1.

### Digest Idempotency

The shard idempotency digest canonically includes:

- reviewer schema/prompt versions and digests;
- route task, model alias, timeout/retry policy;
- graph lineage and node-context digest;
- candidate bank version, manifest digest, and item count;
- ordered question id/item version/question digest;
- ordered contract id/version/contract digest;
- kind, evidence role, summer mode, question-generation contract digest;
- fingerprint policy version.

An accepted shard receipt may be reused only when every field and digest matches, provider mode is `live_model`, agent key/phase/task are exact, and the receipt is not stale or superseded. Retry uses the same idempotency digest.

### Checkpoint

Checkpoint root:

```text
data/question_banks/math/.answer_contract_review_v51/<bank-version>/<node-id>/
```

After every terminal shard result, atomically write a sealed checkpoint containing shard assignment, attempts, route evidence, accepted/rejected result, receipt digest, and retry state. Restart reuses valid accepted shards, retries retryable shards within budget, and preserves terminal failures as activation blockers.

### Node Aggregate Receipt

One node receipt is accepted only when:

- all four expected shard receipts exist and match the pinned policy;
- exactly 20 unique immutable questions are covered once;
- every per-item result is activation-approved;
- no missing, duplicate, rejected, ambiguous, stale, non-live, or digest-mismatched item exists;
- the aggregate digest commits to all constituent receipt digests and node context.

### Global Receipt

The global activation receipt requires:

- exactly 56 accepted node receipts;
- exact candidate bank/graph/manifest lineage;
- exactly 1,120 unique approved items;
- one active-ready contract and fingerprint pair per item;
- zero semantic/correctness/evidence-role/contract blockers;
- both known misbinding oracle ids absent from the candidate active manifest or replaced by independently approved new immutable questions.

No partial active contract set or aggregate success receipt is allowed.

## Question-Bank Repair Route

Semantic rejection is not contract repair.

For a wrong, ambiguous, or misbound question:

1. Keep the existing immutable question/version and historical attempts unchanged.
2. Mark the candidate item inactive for v5.1 contract activation and emit a machine-readable repair issue.
3. Route the issue to the question-bank pipeline, not the answer-contract reviewer.
4. The question designer creates a new immutable question id and item version under a new monotonic question-bank version and manifest.
5. An independent question reviewer verifies question correctness, node alignment, evidence-role alignment, age fit, and process-evidence quality.
6. Only an approved new question enters a new candidate bank manifest.
7. Generate a fresh answer-contract draft and run the independent answer-contract reviewer against the new immutable lineage.
8. Re-run node aggregate and global activation audits.

No in-place prompt edit, expected-answer edit, node-id update, silent rebinding, or reuse of the old item digest is permitted.

## Mandatory Red Oracles

The following current v11 rows must fail question-node alignment and block global activation until replaced through the repair route:

| Question | Current binding | Actual core | Required result |
|---|---|---|---|
| `QB11-M-G7-NUMBER-LINE-19` | `M-G7-NUMBER-LINE` | two-dimensional square-layer row/column pattern | `misbound`, inactive, repair required |
| `QB11-M-G7-RATIONAL-ADD-SUB-09` | `M-G7-RATIONAL-ADD-SUB` | one-variable linear-equation price modeling | `misbound`, inactive, repair required |

The activation script must run these deterministic oracle assertions before any live review or activation. A report showing 1,120 generated drafts, zero structural errors, or `PASS_WITH_SCOPE` cannot override them.

## Scoring and Runtime Authority

### Call Budget

- normal text answer: exactly one GPT semantic criterion call;
- explicit `我不会` / `卡住`: zero GPT and zero OCR calls;
- photo answer: exactly one Doubao OCR call plus one GPT semantic criterion call;
- duplicate/restart replay: no second semantic call after an accepted envelope/result reference exists.

### Transaction Boundaries

1. Submission transaction writes one immutable attempt and one idempotent `answer_analysis` job.
2. The worker performs the permitted OCR step, then the single GPT criterion judgment.
3. Persist the accepted model envelope and authoritative result references before reducer replay.
4. One idempotent reducer transaction writes:
   - accepted `attempt_assessment`;
   - derived compatibility fields on `attempts`;
   - exact-assessment `evidence_validation`;
   - mastery decision and rebuilt/current learner status as applicable;
   - deterministic next-step decision;
   - one materialized child state;
   - downstream authoritative ids into the answer job result refs.
5. A crash after envelope persistence resumes the reducer without a second GPT call.
6. A crash before an accepted envelope retries the same job/evidence/contract idempotency key within the bounded execution budget.

Exactly one current accepted assessment may exist per attempt version. Raw answer and attachments remain immutable.

### Queue and Recovery

- New v5.1 hot paths enqueue only `answer_analysis`.
- Job idempotency includes attempt/evidence, ordered clarification evidence, question/contract, prompt/schema, score policy, gate policy, and assessment policy digests.
- Accepted result refs are replay authority after restart.
- Terminal malformed/model failures preserve the attempt and converge to clarification, blocked, cannot-provide, or summary; they never fabricate score/mastery.
- Legacy jobs may finish under pinned legacy policy but may not create a second v5.1 assessment or duplicate reducer output.

## Clarification and Regrade

### Clarification

- A clarification is a new immutable `supporting_only` attempt linked by `clarifies_attempt_id` to the original attempt.
- It receives no independent score/mastery and is not counted as another question.
- Reanalysis creates the next assessment version on the original attempt using the ordered original-plus-supporting evidence digest.
- EvidenceGate/mastery consume only the latest current accepted assessment for the original attempt.
- Duplicate clarification reuses one supporting attempt by idempotency.
- Repeated unclear evidence may close as `cannot_provide` without score or mastery.

### Regrade

- Regrade requires explicit Codex/system-maintenance authorization or correctness quarantine.
- It creates a new assessment version and supersedes the old accepted assessment; it never overwrites raw evidence.
- Dependent validations, mastery decisions, next-step decisions, and summaries become stale by lineage.
- Rebuild learner state deterministically from all current accepted non-stale evidence.
- Replace only open/unconsumed dependent steps; do not rewrite completed historical child steps.
- During reconciliation with no current accepted assessment, show honest correcting/pending state and no superseded score as current.

## Activation and Dry-Run Semantics

`--dry-run` performs no model calls and no activation writes.

For the current 1,120-item v11 bank, dry-run may report:

- `active_manifest_items = 1120`;
- `draft_contracts_generated = 1120` when structurally possible;
- structural invalid/uncovered counts;
- semantic receipts present/missing/stale;
- known oracle blockers;
- `semantic_approved` only from valid accepted live receipts;
- `activation_ready = false` until every semantic gate passes.

It must not unconditionally report `independently_approved = 1120`, `invalid_contracts = 0`, or activation success before live review. With the two known current misbindings unrepaired, global activation must fail closed even when 1,120 drafts were generated.

Activation order:

1. This Phase 0 contract receives independent 镜花 review with no blocking finding.
2. Required red tests exist and fail for missing implementation/known misbindings.
3. Candidate question bank is repaired and independently reviewed where needed.
4. All 224 shard reviews, 56 node receipts, and one global receipt pass for the exact candidate bank.
5. Contracts/fingerprints are activated atomically in one DB transaction.
6. All authoritative readers use accepted assessments and legacy readers are explicit.
7. Browser, restart, duplicate, OCR, clarification, regrade, report, and call-budget gates pass.
8. Set `ANSWER_ASSESSMENT_POLICY=v5.1`, restart, and verify the formal service.

## No-Git Safety and Rollback

Existing pre-v5.1 backups:

- source archive: `data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz`
- SQLite backup: `data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite`
- SQLite integrity verified: `ok`

Before production-code edits, create one SHA-256 receipt covering both exact files and verify both archive readability and SQLite integrity:

```bash
shasum -a 256 \
  data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz \
  data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite \
  > data/backups/v5.1-preimplementation-backups.sha256
shasum -a 256 -c data/backups/v5.1-preimplementation-backups.sha256
tar -tzf data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz >/dev/null
sqlite3 data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite "pragma integrity_check;"
```

Expected: checksum verification succeeds and integrity output is `ok`.

Default rollback:

1. Set `ANSWER_ASSESSMENT_POLICY=off` through `scripts/set_learning_policy.py`.
2. Stop the service and prove port 8765 is not listening.
3. Restore source files from the pre-v5.1 source archive and remove files created only by v5.1 implementation according to the changed-file receipt.
4. Restart under legacy policy and verify `/api/child-bootstrap`.
5. Do not restore or overwrite the live SQLite DB. Additive rows remain inert/auditable.

SQLite restore is exceptional. It requires explicit user authorization, a stopped service, a new incident-time backup of the live DB, integrity checks, and a written statement of learning records that would be lost. Without those conditions, DB restore is forbidden.

## Required Validation

```bash
rg -n "TO[D]O|TB[D]|evaluation_update.*enqueue|planner_decision.*enqueue|teaching_generation.*enqueue" docs/architecture/answer_assessment_engineering_contract_v5_1.md
python3 -m unittest tests.test_answer_assessment_v51 -v
python3 -m unittest tests/test_learning_system.py -v
node scripts/browser_answer_assessment_v51.mjs --scenario all --start-isolated
python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --dry-run
python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --audit
rg -n "ANSWER_ASSESSMENT_POLICY" learning_system
```

Activation evidence must separately report `draft_contracts_generated`, `semantic_approved`, `semantic_rejected`, `semantic_missing`, node receipts, global receipt, and `activation_ready`.

## Risks

| Risk | Control |
|---|---|
| structurally valid contract on the wrong node | independent correctness/node/evidence-role verdicts; fail closed |
| reviewer silently repairs/rebinds | immutable input, verdict-only output, separate question-bank repair pipeline |
| 20-item calls timeout or lose evidence | max five items/shard, concurrency one, 120s timeout, bounded retry, sealed checkpoints |
| aggregate count hides one rejected item | exact per-item receipts, node/global set equality, no partial activation |
| static grade audit false-pass | two mandatory misbinding oracles and live semantic receipts |
| duplicate model calls after restart | accepted envelope/result refs plus digest idempotency |
| rollback erases new learning | flag off + source restore; no default live DB restore |

## ENGINEERING_CONTRACT_COVERAGE

- interfaces_complete: yes
- fields_complete: yes
- call_chain_complete: yes
- async_queue_complete: yes
- storage_scale_complete: yes
- compatibility_complete: yes
- contract_tests_named: yes
- blocking_gaps: none in this document

## ENGINEERING_CONTRACT_QUALITY_GATE

- verdict: `CONTRACT_READY_FOR_INDEPENDENT_REVIEW`
- no_ambiguous_shared_fields: pass
- producers_consumers_complete: pass
- errors_permissions_complete: pass
- old_data_and_compatibility_complete: pass
- failure_retry_recovery_complete: pass
- contract_tests_or_validation_named: pass
- question_node_semantic_gate_complete: pass
- repair_route_complete: pass
- no_git_rollback_complete: pass
- quality_evidence:
  - QA spec supplies exact semantic gates and mandatory misbinding oracles;
  - current DB rows verify both false-pass samples despite a scoped static audit;
  - runtime call/transaction authority matches the approved storage design;
  - backup files exist, source archive is readable, and SQLite backup integrity is `ok`.
- blocking_quality_gaps: independent 镜花 rereview still required before production code

## Stop Gate

Do not begin schema, production-code, or test-code implementation until 镜花 independently rereviews this contract and the later revised implementation blueprint. `CONTRACT_READY_FOR_INDEPENDENT_REVIEW` is not a design-review PASS and not implementation authorization.
