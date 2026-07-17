# Answer Contract v2 Batch Generation Technical Plan

Date: 2026-07-15
Owner: 听云 (`tingyun`)
Status: design-review-ready-after-needs-fix
Scope: Batch A canary generation and Batch B exact full-bank generation only; no answer-contract activation

## Objective

Create one production-authoritative v2 batch-generation path over the existing per-question
`run_contract_repair_loop_v2` engine:

- Batch A plans a fixed 40-question canary, two questions for each of the 20 active kinds,
  performs mandatory full-active-bank deterministic oracle and scoring-policy preflight before any model call,
  and seals a DB-backed canary generation receipt only when all 40 pass.
- Batch B requires that exact canary receipt, plans the exact 1,120 questions from the current
  active bank, reuses the exact approved canary 40 with zero model calls, processes only the
  remaining 1,080, and seals a DB-rebuilt full-generation receipt.

Neither receipt activates contracts or replaces independent answer-contract review, fingerprint,
node, global, or atomic activation authority.

## Entry Lock

- request type: `technical_plan` plus `engineering_contract` review remediation
- maturity: `implementation_ready_after_design_review`
- complexity: `high_risk_change`
- authority: 听云 owns documentation-only remediation in this turn
- source: `MSG-20260714-001`, v5.1 assessment contract, current v1/v2 generation,
  model-router, and activation implementations, plus six 镜花 findings
- project boundary: one child, SQLite, GPT-5.5 text, no mock/recorded semantic PASS,
  no real DB write, no model call, no Git initialization
- write scope: this plan and its companion engineering contract only
- validation target: line-level contract consistency and explicit closure of all six findings
- stop condition: return `DESIGN_REVIEW_READY`; production implementation remains blocked
- test-case source: required for implementation, not for this documentation-only remediation;
  adversarial test contracts are defined in the companion document

## Sources And Reconnaissance

- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/tingyun.md`
- `docs/collaboration/inbox.md#MSG-20260714-001`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/architecture/answer_assessment_engineering_contract_v5_1.md`
- `learning_system/answer_contract_generation.py`
- `learning_system/answer_contract_generation_v2.py`
- `learning_system/model_router.py`
- `learning_system/answer_contract_activation.py`

Verified implementation facts:

1. `answer_contract_generation.py` is the intended public production entry; the v2 module is
   already the internal per-question engine.
2. One question can use three contract versions. Each version permits up to three designer and
   three reviewer semantic adapter invocations.
3. A designer semantic invocation can currently expand through six router candidates
   (two endpoints x three JSON modes); the v2 reviewer route is pinned to one strict lane.
4. Existing v2 `agent_runs` prove prompt/schema/route/input/output lineage, but no batch attempt
   identity currently joins transport, agent run, contract, and batch state.
5. Existing activation planning requires 56 nodes and 224 shards. The v5.1 contract also requires
   node receipts, a global receipt, fingerprints, mandatory misbinding oracles, and one atomic
   activation transaction. Generation receipts cannot replace those gates.
6. Current activation write remains intentionally unimplemented. Batch A/B does not change it.

## ENGINEERING_SOURCE_READINESS

- verdict: `ENGINEERING_SOURCE_READY`
- prd_quality_gate_checked: not_applicable; this is an internal operator pipeline under an
  already-authoritative v5.1 engineering contract
- product_source_content_ready: yes; Batch A/B scope and non-activation boundary are explicit
- downstream_guessing_risk: none after the decisions below
- product_scope_ready: yes
- product_structure_ready: not_applicable; no child UI or product navigation change
- ux_flow_ready: not_applicable
- data_contract_ready: yes; run, item, semantic attempt, provider attempt, receipt, and handoff
  authority are defined in the companion contract
- project_boundary_ready: yes
- codebase_recon_ready: yes; current retry topology and activation gates were traced
- architecture_context_ready: yes
- authorization_ready: documentation only; implementation still requires non-blocking design review
- validation_targets_ready: yes
- blocking source gaps: none for design

## Architecture Decisions

| Decision | Contract |
|---|---|
| owning module | `answer_contract_generation.py` is the only public production orchestration entry. `answer_contract_generation_v2.py` remains the internal per-question engine. |
| execution | One OS process and one SQLite writer connection; deterministic item order; no worker pool. |
| authority | SQLite run/item/attempt/provider-attempt/receipt rows are authoritative. File checkpoints are sealed recovery evidence only. |
| exclusion | One DB-wide canonical flock derived from the resolved main SQLite path, never from caller-controlled `checkpoint_root`. |
| split-brain defense | The flock is paired with a DB CAS claim token and monotonic operation generation. Every state mutation proves the current claim. |
| provider path | Existing v2 designer/reviewer agents and contracts only. Router candidate policy is pinned in the run manifest and every real HTTP attempt is counted. |
| attempt seam | A locally generated `batch_attempt_id` is committed before transport and is bound into request, provider attempts, `agent_run`, design/review receipt, contract lineage, and batch item state. |
| preflight | Batch A scans every authoritative question in the active bank against every registered deterministic oracle and scoring-policy blocker before the first attempt. A blocker anywhere, including outside the selected 40, completes the run blocked with zero model/provider calls and no PASS receipt. |
| evidence role | One versioned `effective_evidence_role` helper implements `evidence_role || evidence_goal || "direct"`, rejects illegal types, and is shared by selection, plan, review, receipt, and activation handoff. |
| canary | Fixed 20 kinds x 2 questions using deterministic maximum node/effective-evidence-role diversity. A passed receipt has canary-generation authority only. |
| full run | Exact 1,120 current active-bank questions. It binds one passed canary receipt and reuses those 40 exact DB-approved contracts. |
| idempotency | Same immutable run identity resumes one canonical DB run. DB eligible authority yields zero model calls. DB/checkpoint disagreement fails closed. |
| receipt no-op | Completion time is fixed in the completion transaction. A valid existing receipt is reconstructed and returned byte-for-byte; it is never re-timestamped or re-digested. |
| activation | Out of scope. Batch B is generation evidence only and cannot set contracts active or bypass the existing review/fingerprint aggregate gates. |
| v1 compatibility | V1 flags remain callable only as `legacy_probe_only`, with `production_authority=false`; v1 rows cannot satisfy Batch A/B. |

## Canonical Run And Plan Identity

The immutable run identity digest includes:

- run schema version and `canary40|full1120` kind;
- exact active ledger id, bank version, manifest digest, graph version, and graph/config receipt lineage;
- ordered question id, item version, node id, kind, normalized effective evidence role,
  effective-evidence-role policy version/digest, review-record id, and question digest;
- plan-selection policy version and, for canary, per-kind diversity availability and selected-pair rank;
- answer-contract v2 generator/compiler policy and all per-kind profile/catalog digests;
- designer/reviewer agent key, phase, prompt version/template digest, schema version/digest;
- route provider/model alias/base-url identity without credentials, exact endpoint/format candidate
  list, timeout, retry/backoff, and Retry-After policy;
- run-level model-call and provider-attempt caps;
- expected item count and deterministic item-order policy;
- for Batch B, exact parent canary run id and receipt digest.

Per-invocation item and wall-time limits are operational limits and do not alter the run identity.
They cannot exceed the persisted run hard limits. The canonical run row and all immutable plan rows
are committed before the first `batch_attempt_id` is reserved.

## Batch A Mandatory Preflight

Preflight is part of Batch A authority, not an optional audit command:

1. Acquire the DB-wide flock and CAS claim.
2. Rebuild the unique active ledger and exact authoritative reviewed-question set.
3. Build the deterministic 40-item plan and persist its immutable rows.
4. Evaluate every registered deterministic v5.1 misbinding oracle over the full active bank, not only
   the selected 40. A known bad immutable row is a blocker until absent or replaced by independently
   reviewed new lineage.
5. Evaluate every registered deterministic v2 scoring-policy blocker for every authoritative active-bank
   question, not only the selected 40, and bind the blocker-registry plus profile/catalog digests used
   for the decision. A non-canary row matching the current v11 clock-verification gate blocks the
   entire run exactly like a selected row.
6. Normalize and validate effective evidence roles for every active-bank row, then validate selected
   question review records, graph bindings, reference inputs,
   and route/prompt/schema availability without invoking a model.
7. Persist the canonical preflight payload/digest and transition either to `running` or, in the
   same transaction, to `completed_blocked`.

`completed_blocked` requires zero semantic attempt rows, zero provider-attempt rows, zero accepted
contracts created by this run, and no canary PASS receipt. It may expose a non-authoritative blocked
summary with local reason codes and repair owners.

### Effective Evidence Role Policy

One repository helper and policy version, `answer_contract_effective_evidence_role.v1`, defines:

```text
effective_evidence_role(question):
  validate evidence_role and evidence_goal: each present value must be a string
  trim surrounding whitespace in both fields
  return normalized evidence_role, else normalized evidence_goal, else "direct"
```

Any present non-string field is rejected even when the other field would otherwise win precedence.
No lowercasing, translation, or caller-provided default is allowed. This preserves the current
activation precedence while removing permissive string coercion. The helper output and policy digest
are the only evidence-role facts used by canary selection, ordered plan/run identity, immutable run
items, designer/reviewer packets, generation receipts, and later activation handoff. Raw
`evidence_role` and `evidence_goal` remain bound inside the authoritative question digest but cannot
be independently reinterpreted by those consumers.

### Deterministic Two-Per-Kind Selection

For each active kind:

1. Canonically sort authoritative candidates by
   `(node_id, effective_evidence_role, question_id, item_version)`.
2. Enumerate every unordered pair.
3. Rank pairs by the descending diversity vector
   `(different_node, different_effective_evidence_role)`, then by the ascending canonical tuple of both rows.
4. Select the unique first pair and persist the candidate-set digest, diversity availability,
   selected pair, and rank-policy version.

Thus a same-node or same-effective-role pair cannot win when a more diverse pair exists. If fewer than two
authoritative candidates exist, selection is ambiguous, or the source set changes during claim,
preflight completes blocked. No caller may nominate the 40 ids.

## V2 Attempt Lifecycle Seam

Every semantic adapter invocation has one stable `batch_attempt_id`:

1. Under `BEGIN IMMEDIATE`, reserve the attempt with exact request, prompt, schema, route,
   question, repair-version, role, claim token, and budget commitments.
2. Commit `provider_calling` and the `batch_attempt_id` before the first HTTP request.
3. Put the id in trusted request context/source refs. It is excluded from untrusted question and
   contract content and cannot be authored by the model.
4. Every router HTTP candidate creates a child provider-attempt row before network I/O.
5. Persist `agent_runs.input_refs_json` with the exact `batch_attempt_id` and request digest.
6. Persist design/review receipts and answer-contract lineage with their exact designer/reviewer
   batch attempt ids.
7. Complete the batch attempt and item projection only after exact DB round-trip validation.

On resume, an orphan `agent_run` is attachable only when exactly one row matches the
`batch_attempt_id`, agent/phase, request digest, prompt/schema/route, canonical output digest, and
expected accepted/rejected local verdict. Zero, multiple, or conflicting matches fail closed or
remain uncertain; no output is inferred from a checkpoint.

`provider_result_unknown` means an HTTP attempt started but no authoritative provider result or
exact agent run can be established. `commit_unknown` means a SQLite commit raised and the caller
cannot know whether the DB mutation committed. A commit-unknown attempt is audited by deterministic
ids before any new provider call; it is never relabeled as provider-result-unknown.

## DB-Wide Lock, Claim, And Takeover

The canonical lock path is derived from `PRAGMA database_list` main DB resolved path:

```text
<db-parent>/.answer-contract-v2-locks/<sha256(resolved-main-db-path)>.lock
```

The lock directory is safely created and the path is independent of `checkpoint_root`. Two callers
using different checkpoint roots against the same DB contend on the same lock.

After flock acquisition, `BEGIN IMMEDIATE` claims the run by CAS:

- increment `operation_generation`;
- create a random `claim_token`;
- bind owner PID, invocation id, claimed time, and heartbeat;
- require the exact token/generation on every later run, item, attempt, and receipt mutation.

Takeover rules:

- fresh `running` or `provider_calling`: no takeover;
- stale `running` with no unresolved attempt: mark the old claim interrupted, then claim generation + 1;
- stale `provider_calling`: first reconcile exact provider-attempt and `agent_run` evidence; attach an
  exact orphan result, otherwise seal `provider_result_unknown` before a new attempt is considered;
- `interrupted`: revalidate run/plan/current DB authority, then claim generation + 1;
- `commit_unknown` or `committed_unverified`: audit deterministic rows first; no takeover or model call
  until resolved;
- lost CAS on any write: stop immediately as `claim_lost` without a receipt.

Heartbeat interval is fixed at 15 seconds. The persisted stale threshold is
`max(300, ceil(max_route_timeout + 120 + 15))` seconds, so it exceeds the pinned maximum single HTTP
timeout, bounded Retry-After, and one heartbeat interval. A live provider call cannot be stolen merely
because it has not returned yet.

## Budget, Time, And Signal Policy

Counters have distinct meanings:

- `model_calls`: semantic adapter invocations reserved in DB, including schema-valid outputs later
  rejected by the compiler/reviewer and provider-result-unknown invocations;
- `provider_attempts`: real HTTP requests started, including every endpoint/format fallback, timeout,
  429/5xx retry, and response later rejected locally;
- local preflight, DB/checkpoint reconciliation, and compilation before transport count as neither.

Current topology produces these ceilings per newly generated item:

- default planning allowance: 3 versions x (1 designer + 1 reviewer) = 6 model calls;
- hard semantic ceiling: 3 versions x 2 roles x 3 attempts = 18 model calls;
- default provider allowance: 3 x ((1 designer x 6 router candidates) +
  (1 reviewer x 1 pinned candidate)) = 21 HTTP attempts;
- hard provider ceiling: 3 x ((3 x 6) + (3 x 1)) = 63 HTTP attempts.

| Run | New items | Default model cap | Hard model cap | Default provider cap | Hard provider cap | Default/hard items per invocation | Default/hard invocation wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| Batch A | 40 | 240 | 720 | 840 | 2,520 | 40 / 40 | 4h / 12h |
| Batch B | 1,080 | 6,480 | 19,440 | 22,680 | 68,040 | 100 / 200 | 8h / 24h |

The full A+B minimum is 2,240 model calls when every designer and reviewer succeeds on the first
semantic call; it is not a capacity bound. Batch B reports its own 1,080-item counters separately
from the parent canary counters.

All caps and counters are cumulative across resume. Before each semantic or HTTP call, the runner
atomically proves remaining run and invocation budget plus wall deadline. The remaining monotonic
wall deadline is passed through the semantic adapter into each router candidate timeout; a six-lane
fallback cannot multiply beyond the enclosing item/run deadline.

SIGTERM/SIGINT sets a stop flag only. The runner starts no new attempt, lets an in-flight bounded
transport reach an exact result or unknown boundary, seals the attempt accordingly, marks the run
`interrupted`, checkpoints the DB projection, and releases flock in `finally`. Resume retains all
counters and begins with the standard authority/claim reconciliation.

## Batch A And Batch B Execution

### Batch A

1. Acquire canonical flock and CAS claim.
2. Create/reuse the exact run and 40 plan rows.
3. Execute mandatory preflight; stop as `completed_blocked` with zero calls on any blocker.
4. Process items in canonical order through the existing v2 repair loop using the attempt seam.
5. Requery all question, contract, agent-run, attempt, provider-attempt, and checkpoint commitments.
6. Complete passed and seal one canary generation receipt only when all 40 are exact v2 eligible.

### Batch B

1. Acquire canonical flock and validate one exact passed Batch A receipt against current DB.
2. Rebuild exact active-bank equality: 56 nodes x 20 questions = 1,120.
3. Re-run the same local full-active-bank oracle/policy/effective-evidence-role/route authority
   preflight over all 1,120 rows; drift or a newly known blocker completes Batch B blocked before any
   Batch B model call.
4. Require the canary 40 as an unchanged subset and create all immutable run-item rows.
5. Requery each canary item from DB and mark `reused_approved` with zero calls.
6. Process only the remaining 1,080 under cumulative budgets and bounded invocations.
7. Requery all 1,120 rows from DB and seal the full-generation receipt from reconstructed facts.

## Deterministic Receipt No-Op

The completion transaction:

1. revalidates the run claim, current ledger, plan equality, item terminal states, exact v2
   eligibility, counters, and checkpoint commitment;
2. obtains `completed_at` once and stores it on the run;
3. constructs the canonical receipt using that stored value;
4. inserts the receipt and transitions the run to `completed_passed` in the same transaction.

For a completed run, every later invocation reconstructs the bound historical receipt using the
stored `completed_at` and exact rows committed by that run. An exact existing receipt is returned
without any DB write, timestamp change, or digest change. Current-ledger drift is reported separately
as `not_current_authority` and prevents reuse, but does not mutate the historical run or receipt.
Missing, duplicate, or different bound receipt evidence returns an integrity-blocked audit result;
it is never silently re-sealed or used for Batch B.

## Authority Handoff To Independent Activation

Batch A receipt authority is `canary_generation_gate_only`. Batch B receipt authority is
`full_generation_evidence_only`. Both set `activation_eligible=false`.

The later activation batch, which is explicitly out of scope here, must independently and in one
`BEGIN IMMEDIATE` transaction revalidate:

- the unique current active question-bank ledger and exact 1,120 question/fingerprint set;
- every v2 contract's current question, designer/reviewer batch-attempt, agent-run, prompt, schema,
  route, output, design receipt, review receipt, scoring-policy lineage, and exact normalized
  effective-evidence-role policy/output;
- the existing 224 live review shard receipts;
- the existing 56 node receipts;
- the global answer-contract review receipt;
- mandatory misbinding oracles and zero routed/rejected/missing items;
- exact fingerprint policy and active-ready contract/fingerprint pair per item.

Only that later transaction may change all contract/fingerprint statuses atomically. Batch A/B does
not modify `answer_contract_activation.py`, does not weaken or replace any existing gate, and does
not create a partial active set.

## Implementation Blueprint

| File | Symbols | Planned change |
|---|---|---|
| `learning_system/db.py` | `init_schema` | Add run, item, semantic-attempt, provider-attempt, receipt, claim, and exact lineage columns/indexes additively. |
| `learning_system/model_router.py` | structured transport observer seam | Persist/count each actual HTTP candidate before network and honor one enclosing deadline; no new route or agent. |
| `learning_system/answer_contract_generation.py` | `effective_evidence_role`, `build_v2_batch_plan`, `preflight_v2_canary`, `create_or_resume_v2_run`, `run_v2_canary`, `run_v2_full`, `audit_v2_run`, `seal_v2_generation_receipt` | Own the shared versioned evidence-role policy and the only public production batch orchestration path. |
| `learning_system/answer_contract_generation_v2.py` | attempt-aware live adapter/repair-loop seam | Accept trusted batch-attempt context and expose exact reconciliation helpers without changing model authority. |
| `scripts/generate_answer_contracts.py` | CLI parser/main | Add v2-only canary/full/audit modes, caps, invocation limits, and explicit v1 legacy output. |
| focused tests | temporary SQLite and fake adapters | Cover full-bank preflight zero-call, normalized role precedence/stable ordering, diversity, attempt lineage, orphan recovery, two-root lock, CAS takeover, budgets, signals, no-op receipts, and activation non-authority. |

## Batch Boundaries

- Batch A may add shared schema, router observation, locking, lifecycle, and receipt primitives needed
  by Batch B, but exposes only canary execution/audit.
- Batch B begins only after Batch A tests and independent review pass.
- Neither batch edits activation policy, knowledge-map policy, active contract statuses, or existing
  224/56/global/fingerprint gate semantics.

## Review Remediation Retrospective

| Finding | Closure |
|---|---|
| mandatory preflight and deterministic canary diversity | Preflight is a zero-call hard gate over every known oracle and scoring-policy blocker across the complete active bank; a non-canary clock blocker cannot be hidden by selection. Pair ranking maximizes node and normalized effective-evidence-role diversity. |
| evidence-role authority | A versioned helper implements `evidence_role || evidence_goal || "direct"`, trims nonempty strings, rejects illegal types, and supplies one shared value/digest to every producer and consumer through activation handoff. |
| v2 lifecycle seam | `batch_attempt_id` is committed before transport and binds HTTP, agent run, receipts, contract, and batch state; orphan and unknown outcomes are explicit. |
| DB-wide lock and CAS | Lock path derives only from the main DB path; claim token/generation and stale-state takeover rules prevent split-brain across checkpoint roots. |
| honest budgets and bounded execution | Default/hard semantic and actual HTTP caps are derived from 3 versions x 3 attempts and six-lane designer fallback; wall, item, signal, and resume policies are fixed. |
| deterministic receipt no-op | `completed_at` is fixed in the completion transaction; exact existing receipts are reconstructed and reused without writes. |
| authority handoff | Full receipt is generation evidence only; existing 224 shard, 56 node, global, fingerprint, oracle, and atomic activation gates remain independent and unchanged. |

## TECHNICAL_PLAN_QUALITY_GATE

- verdict: `TECH_PLAN_READY_FOR_DESIGN_REVIEW`
- product_fit: pass; exact authorized Batch A/B generation scope, no child-flow expansion
- architecture_fit: pass; one public orchestrator over the existing v2 engine, with DB authority
- simplest_sufficient_design: pass; no new agent, queue, service, worker pool, or activation path
- contract_risks_identified: pass; non-canary preflight false-pass, evidence-role interpretation drift,
  split-brain, duplicate provider calls,
  orphan agent runs, commit uncertainty, budget undercount, receipt churn, and authority confusion
  have explicit controls
- failure_resilience_planned: pass; CAS takeover, unknown-outcome audit, SIGTERM, cumulative resume
- testability_planned: pass; deterministic hooks and adversarial contracts are specified
- maintainability_fit: pass; provider accounting is isolated at the router boundary
- security_privacy_checked: pass; credentials are absent from identities, DB evidence, receipts, and stdout
- operability_checked: pass; run/item/attempt/provider-attempt states and bounded invocation controls
- performance_cost_checked: pass; minimum, default, and hard semantic/HTTP bounds are separate
- quality_evidence: current v2 constants (`3` versions, `3` attempts, `180s` item wall), router
  candidate expansion (`6` designer, `1` reviewer), current activation evidence-role precedence,
  and current activation `56/224` gates were traced
- blocking_quality_gaps: independent 镜花 design review remains required before implementation
