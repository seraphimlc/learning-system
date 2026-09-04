# Question Bank Production Flow v3

> **For agentic workers:** The frozen manifest remains the queue boundary. Do not call a generation model or alter the question bank without a release manifest and the bounded termination policy below.

**Status:** `APPROVED_IMPLEMENTATION_BASELINE`

**Goal:** Build a small, graph-bound, evidence-oriented math question bank for the private Grade 7 bridge system, with independent production, deterministic grading for fixed-answer items, model assessment only for short-answer/process evidence, and reversible staged activation.

**Architecture:** The pipeline is separated into five immutable evidence layers: graph/node contract, slot brief, candidate question, answer/assessment contract, and review/publish receipts. Briefs describe what a question must measure, not a finished question. Each slot is produced independently, reviewed according to risk, committed to a staged bank independently, and admitted to child scheduling only after portfolio-level acceptance.

**Tech Stack:** Existing Python/SQLite learning runtime, versioned JSON contracts, existing model router, append-only receipts, and the current math knowledge graph snapshot.

---

## 1. Decisions That Must Not Drift

### 1.1 The old bank is history

- The 840 old questions remain in the archived bank `semester_bank_v1.archived-20260826-135650.sqlite`.
- The archived bank is readable for audit only. It is not a source for briefs, candidates, quotas, prompts, or review receipts.
- The new bank starts from an empty namespace and receives a new bank version and graph lineage.
- No guessed quality metadata is backfilled onto old questions.

### 1.2 No global question-count target

The new bank does not target 840, 1,000, or any other fixed total. The number of slots is derived from graph evidence coverage:

1. Identify the evidence patterns that each schedulable node requires.
2. Design the smallest set of distinct slot purposes that can expose those patterns.
3. Remove slots that only repeat numbers, wording, or a known procedure.
4. Freeze the resulting manifest even when its count is lower than the old bank.

`planned_slot_count` is a report of the approved architecture, not an acceptance criterion. A missing evidence pattern blocks activation; a lower total does not.

### 1.3 Difficulty is discovery, not arithmetic size

Every slot and candidate records:

- `discovery_depth`: what the child must notice, choose, transform, or construct before routine execution;
- `execution_steps`: meaningful steps after the entry point is found;
- `key_insight`: the specific relation or decision being measured;
- `misconception_target`: the plausible wrong path the item distinguishes.

Levels:

- `E0 mechanical`: one explicit operation or an isolated intermediate operation. Examples: `-8 + 3`, `2^4`, `-7 ○ -3`, or `4 + 6` after the prompt already supplies the reasoning. Teaching examples may use E0; active scheduling may not.
- `E1 familiar_model`: the child identifies and applies a known model. Use only for an explicit foundation check or when the node contract requires a baseline signal.
- `E2 single_insight`: the child must discover one non-obvious relation, representation change, sign/scope decision, or error distinction. This is the normal active level.
- `E3 composed_insight`: two dependent decisions, prerequisite coordination, or a genuine choice between plausible routes. Use selectively for transfer.
- `E4 exploratory`: construction, counterexample, invariant, classification, or another open strategy. Controlled extension only; never a filler or daily minimum.

Larger numbers, longer text, more parentheses, or extra arithmetic do not raise `discovery_depth`. A review must be able to name the entry point and the misconception target; otherwise the candidate is low-information and rejected or redesigned.

### 1.4 Response modes are first-class

The active bank supports exactly these production modes:

- `single_choice`: one option id;
- `multi_choice`: a canonical set of option ids;
- `fill_blank`: one or more named fields with explicit answer rules;
- `short_answer`: child text or work that requires process/semantic interpretation.

Choice and fill-in items may be authored by a model, but correctness is always determined locally from the activated answer contract. They never enqueue model answer analysis. `short_answer` uses model assessment only when the response contract requires semantic or process evidence.

“Fixed answer” describes grading, not educational value. A fixed-answer item can still be weak and must pass the same graph, insight, difficulty, and collision review.

---

## 2. Evidence Layers and Boundaries

```text
graph snapshot + node contract
        |
        v
evidence architecture
        |
        v
slot brief (requirement, no finished question)
        |
        v
one-slot candidate
        |
        +--> deterministic answer-contract compilation
        +--> independent quality review
        +--> collision review
        v
staged item + append-only receipts
        |
        v
portfolio acceptance --> canary --> active scheduling
```

### 2.1 Graph/node contract

The graph is the authority for node identity, prerequisite edges, evidence keys, allowed modes, and any mastery ceiling. A question cannot introduce a new node, prerequisite, or evidence key by self-declaration.

Before brief creation, produce a graph snapshot receipt containing:

- graph version and SHA-256;
- selected node and prerequisite closure;
- node evidence contracts;
- excluded nodes and the reason they are not in this release;
- external-material provenance policy.

### 2.2 Evidence architecture

The architecture maps node evidence needs to purposeful question families. Each family states:

- measurement intent;
- evidence pattern and misconception target;
- allowed response modes;
- permitted difficulty range;
- meaningful variation space;
- forbidden repetition;
- renderer and answer-capture requirements;
- reason the family is needed.

The architecture review is a portfolio decision. It must reject inherited quotas and any family justified only by “we need more questions”.

### 2.3 Slot brief

A brief is a production requirement, not a partially written question. It must not contain a concrete expression, story, number set, answer, option set, or finished wording that can be copied into a candidate.

Each brief contains:

- stable `slot_id` and `operation_key`;
- `measurement_intent_id` and `node_id`;
- prerequisite context and required graph evidence keys;
- `question_family_id`, `discovery_depth`, and `production_mode`;
- `key_insight` shape and misconception target;
- allowed and forbidden variation space;
- collision group and cross-node collision scope;
- expected answer-contract shape;
- child-facing burden and renderer authority;
- brief, architecture, graph, and policy hashes.

The brief may specify an abstract grammar such as “compare two representations after a sign-sensitive transformation”, but it may not instantiate that grammar.

### 2.4 Candidate

One generation invocation produces exactly one candidate for one slot and one candidate version. Candidates are immutable. A repair creates a new candidate version; it never overwrites the rejected candidate or its receipts.

The candidate is untrusted until the deterministic contract checks and independent review pass. Generator self-check is useful diagnostic evidence, but never an approval receipt.

Collision checking uses the versioned `question_fingerprint.v2` policy. An
exact-instance fingerprint is always unique. A family fingerprint treats
changed numbers, names, and cosmetic stories as the same structure; it may
appear at most twice for one node, and the second item is allowed only when it
has both a distinct evidence key and a distinct misconception mapping. Related
nodes use the same structural check and a targeted semantic review. These
version and allowance rules are part of the manifest and cannot be changed by
the worker at runtime.

### 2.5 Answer and assessment contract

The answer contract is compiled before staging:

- Choice: unique option ids, single/multiple mode, canonical expected set, and no client-supplied score authority.
- Fill-in: stable field ids, required/optional status, input mode, exact numeric/rational or explicitly constrained grammar, normalization rules, and accepted alternatives.
- Short answer: scoring dimensions, required reasoning/evidence, key steps, partial-credit rules, and model-assessment schema.

Contract compilation must fail closed on ambiguity, missing accepted alternatives, undeclared fields, invalid numeric grammar, or a mismatch between the item and its response mode. The candidate cannot silently switch from fixed grading to model grading.

### 2.6 Review receipt

Receipts are append-only and bind:

- graph, architecture, manifest, brief, candidate, answer-contract, and review-policy hashes;
- invocation id and model route metadata;
- reviewer role, verdict, confidence, findings, and raw-response hash;
- timestamp, retry number, and cost/latency metadata where available.

No receipt is valid after the hash of its input changes.

### 2.7 Normative contract dependencies

This flow does not redefine lower-level answer and difficulty semantics. The
following existing contracts are normative and must be implemented or reused
without a weaker compatibility interpretation:

- `review_packet.v1` and `discovery_derivation.v1` in
  `docs/superpowers/specs/2026-08-25-question-quality-and-fixed-answer-design.md`;
- `graph_evidence_contract.v1`, including the explicit evidence mapping and
  mastery ceiling in that same design;
- `2026-08-25.fixed-answer-response.v1` for child choice/fill-in responses;
- `fixed_assessment:{attempt_id}:{attempt_version}:{contract_digest}` as the
  fixed-assessment reducer effect key;
- the existing flow/job contract digests and lease-generation fencing rules.

If an implementation needs to change one of these contracts, it must publish a
new version and reopen manifest review. It may not silently reinterpret an old
digest.

### 2.8 Per-item provenance

Every candidate carries a provenance envelope, even when it uses no external
material:

```json
{
  "basis": [{"kind": "graph_contract", "id": "<node_id>", "sha256": "<digest>"}],
  "authoring": {"kind": "model_generated", "invocation_id": "<id>"},
  "external_references": []
}
```

An external reference additionally requires a stable locator, content digest,
retrieval timestamp, authorization/license decision, and the prompt spans that
actually used it. A user-provided source uses the same receipt shape with its
provided-material identifier. Missing, fabricated, unauthorized, or unused
source declarations fail staging. Graph-derived mathematical content must be
labelled as graph-derived; it must not be presented as private textbook or
question-bank content.

---

## 3. Optimized End-to-End Flow

### Phase 0: Snapshot and scope

**Purpose:** Make the release inputs explicit before any design or model work.

**Outputs:** graph snapshot receipt, release scope, empty-bank namespace, policy versions.

**Gates:** graph hash is stable; old bank is archive-only; selected node closure is explicit; no active runtime flow is silently repinned.

### Phase 1: Design evidence coverage

**Purpose:** Define the smallest useful question portfolio from evidence needs, not from a count.

**Steps:**

1. Group related graph nodes only when they share a real measurement structure; do not hide node ownership in a broad topic label.
2. Map each required evidence key to one or more candidate families.
3. Mark foundation, core practice, diagnostic, transfer, and controlled-extension purposes.
4. Eliminate E0-only families and cosmetic variations.
5. Review the distribution across nodes, evidence, difficulty, response modes, and child burden.

**Gate:** architecture review passes for mathematical coherence, assessment value, child appropriateness, renderer availability, and provenance. The review freezes no item count beyond the evidence-derived plan.

### Phase 2: Generate and review slot briefs

**Purpose:** Decouple “what must be measured” from “how one question is worded”.

**Steps:**

1. Generate briefs from the approved architecture.
2. Run deterministic inventory checks for ids, hashes, graph bindings, mode schemas, and distribution accounting.
3. Run a lead brief-consistency review.
4. Escalate high-risk briefs to independent math, assessment, and child-learning reviewers.
5. Run a whole-portfolio review for coverage, progression, and cross-node collisions.
6. Repair rejected briefs by creating new brief versions.

**Gate:** every included brief has a distinct measurement intent and review evidence; the portfolio covers required evidence patterns; no brief contains a finished question. Freeze `slot_manifest` only after this gate.

### Phase 3: Freeze the manifest

The frozen manifest is the sole queue input. It contains:

- exact graph/architecture/brief/policy digests;
- the slot set and per-slot hashes;
- evidence coverage matrix;
- permitted risk tier and reviewer lenses;
- release policy and renderer versions;
- the answer-contract policy/schema digest and each slot's expected response
  mode/contract shape.

Manifest transitions are `DRAFT -> REVIEWED -> FROZEN`. Any graph, architecture, brief, contract, renderer, or policy change creates a new manifest version and invalidates only affected downstream work.

No candidate generation, candidate review, or bank write may occur before an approved frozen manifest. The user approval of this document is not the same as freezing the manifest; the manifest is a later execution gate.

The manifest binds the contract policy and expected shape, not a
candidate-specific final answer digest that does not exist yet. After a
candidate is generated, its final contract digest is stored in the candidate,
review, commit, and item receipts. A contract content change that stays within
the frozen shape creates a new candidate version; a mode, evidence, grammar,
or policy change that leaves the frozen shape requires a new manifest.

### Phase 4: Produce one slot at a time

For each frozen slot:

1. Create a job with `slot_id`, `manifest_sha256`, `candidate_version`, and idempotency key.
2. Run route preflight once per worker run, not once per slot.
3. Lease the slot with `lease_owner` and monotonic `claim_generation`.
4. Build a compact generation packet from the brief, graph summary, answer-contract shape, and collision context.
5. Generate exactly one candidate.
6. Run schema, graph binding, deterministic difficulty derivation, provenance,
   and answer-contract compilation checks.
7. Route risk-tiered independent review.
8. Apply only the permitted repair/retry policy.
9. Run exact and family collision checks, including in-flight and related-node candidates.
10. Commit one accepted item to the staged bank in an idempotent transaction.

Generation can run concurrently. Collision index updates and staged commits must re-read the current index under a write transaction so two workers cannot consume the same family allowance or commit a duplicate.

### Phase 5: Accept the portfolio and release gradually

After all slots reach a terminal outcome, create a portfolio acceptance
receipt. A slot may be terminally `STAGED`, `UNAVAILABLE`, or `BLOCKED`; it may
not disappear from the manifest. It must report:

- required versus covered evidence keys per node;
- active-level distribution by evidence purpose, not just counts;
- E0 rows excluded from scheduling;
- exact and family collision results;
- deterministic answer-contract audit results;
- fixed-answer versus short-answer routing audit;
- blocked slots and explicit reasons;
- provenance and renderer coverage;
- all receipt lineage and hash checks.

Portfolio acceptance separates hard gates from quality scoring and coverage debt.
Graph binding,
answer-contract integrity, renderer validity, provenance, duplicate collisions,
and the per-item quality threshold are hard gates. Difficulty derivation,
reviewer verdict, and review findings are evidence used by the score, not
separate pass/fail gates. A non-empty
`required_evidence_keys - covered_evidence_keys` is recorded as
`coverage_debt`; it does not block a quality-approved item from canary, but it
does block full activation until explicitly resolved or re-scoped in a new
manifest. A slot that exhausts its bounded retries creates
`needs_manual_review` with its node, evidence key, family, and cause; it does
not lower the difficulty, substitute E0, or get removed to make the report
look complete.

The default item policy is one initial candidate, at most two semantic repair
attempts, and at most one explicit coverage-repair pass. There is no automatic
generation loop. After the limit, the slot is terminal and must be handled by
brief revision or manual review.

Then release in two separate operations:

1. `staged -> canary`: a representative set covering every response mode, risk tier, renderer path, and important evidence pattern is made available in observation/diagnostic mode.
2. `canary -> active`: only after deterministic grading, child rendering, short-answer assessment, prerequisite traceback, and rollback checks pass.

Activation never changes existing open flows or jobs. They keep their pinned bank, manifest, contract, and evidence policy. New flows see the new version only after the activation ledger commits.

---

## 4. Review and Grading Policy

### 4.1 Independent review tiers

Self-check does not count as independent review.

- `R1 ordinary`: one independent critic for the slot's primary risk.
- `R2 elevated`: two independent critics with different risk lenses.
- `R3 high-risk`: math, assessment, and child-learning critics; adjudication is conditional on disagreement or a hard blocker.

Escalate to R2/R3 for E3/E4, new families, visual/interactive items, external resources, lead uncertainty, prior repair, ambiguous answer contracts, or collision concerns. Independence means a separate invocation and receipt; the policy should prefer a distinct model route for R3 when available, but must not pretend that two prompts to the same call are independent.

Every critic returns `PASS`, `REVISE`, or `BLOCKED` with structured findings. Hard blockers include wrong mathematics, wrong node/evidence, shallow mechanical disguise, unsolvable or ambiguous wording, incomplete fixed-answer contract, unsupported renderer, and semantic duplicate.

The generator invocation and reviewer invocation must have different
`invocation_id` values and separate evidence records. A reviewer receipt that
copies the generator's self-check without independent findings is invalid.

### 4.2 Fixed-answer grading

The server owns the answer contract and expected answers. The child payload contains only the response, not the expected answer or score.

- Choice grading compares canonical option identity or set identity.
- Fill-in grading parses each field using the contracted deterministic grammar and accepted equivalents.
- Invalid input and incomplete required fields produce no mastery transition.
- Correct fixed evidence is recorded with its evidence ceiling; it does not automatically prove process mastery.
- Choice/fill submissions never enqueue `answer_analysis`.

The fixed grader must have adversarial tests for Unicode signs/spacing, equivalent fractions, decimal policy, duplicate fields, unknown ids, malformed expressions, undeclared variables, and conflicting idempotency digests.

The normative behavior is the closed-envelope parser and exact field grading
from `fixed-answer-response.v1`: reject unknown keys and duplicate JSON keys;
distinguish `invalid_input`, `incomplete`, `wrong`, and `correct`; apply the
server contract rather than client claims; and aggregate fields in that order.
The reducer writes the result and effective evidence profile once. A replay
with the same effect key and input digest returns the stored result. The same
effect key with a different input or contract digest writes an auditable
conflict and applies no second mastery effect.

### 4.3 Short-answer assessment

Only `short_answer` enters model assessment. The model receives the child response, the activated rubric, required key steps, graph evidence contract, and safe context. It must return structured evidence, missing steps, misconception classification, confidence, and a bounded recommendation.

The reducer, not the model, applies mastery ceilings, prerequisite fallback, and idempotent effects. A malformed or unsupported assessment is `BLOCKED`; it cannot be converted into correct/incorrect by a fallback model call.

### 4.4 Deterministic difficulty derivation

The candidate may propose an entry point, but the authoritative level comes
from `review_packet.v1` and the versioned `discovery_derivation.v1` compiler.
The compiler is bounded to the existing packet limits: at most 8 solution
steps, 8 prompt spans, 4 decision points, 3 solution families, and 4
cross-node relations. It rejects cycles, unreferenced steps, unknown evidence
keys, and generator-only prerequisite claims.

The derivation precedence is fixed:

1. malformed or unsupported structure: `BLOCKED`;
2. construction/counterexample/invariant/exploratory strategy: `E4`;
3. two dependent decisions, a genuine route choice, or a graph-valid
   prerequisite coordination relation: `E3`;
4. one non-obvious relation, representation change, sign/scope decision, or
   misconception distinction: `E2`;
5. familiar model application: `E1`;
6. one explicit direct operation or isolated intermediate calculation: `E0`.

`execution_steps` is derived from referenced ordered solution steps and is
bounded by the versioned derivation schema. It can refine scheduling within a
level but can never raise the level. The derivation receipt stores the packet
digest, graph/node-contract digest, prompt/interaction digests, output level,
decision points, and evidence keys. Activation rejects a self-declared level
that differs from this receipt.

---

## 5. State, Retry, and Recovery

Do not mix production execution state with educational outcome. Persist these separately:

### 5.1 Job execution state

```text
PENDING -> LEASED -> RUNNING -> CHECKPOINTED -> READY_TO_STAGE -> STAGING -> STAGED
                         |            |
                         |            +--> RETRYABLE
                         +-----------------> BLOCKED
```

`candidate_version`, `stage`, `attempt`, `lease_owner`, `claim_generation`, and `last_error_category` are immutable facts of the job history. A current job projection may be updated, but stage history and receipts are append-only.

Every stage completion is guarded by the tuple
`(job_id, manifest_sha256, slot_id, candidate_version, stage, lease_owner,
claim_generation)`. The transaction requires the job still to be in the
claimed stage and the lease to be unexpired. If the update affects zero rows,
the worker is stale and may not write a success, retry, or receipt. Recovery
increments `claim_generation` and the old worker is fenced. This is the exact
write rule, not merely metadata retained for diagnostics.

Each side-effecting stage also has an idempotency key and canonical input
digest. Same key plus same digest returns the existing terminal result; same
key plus a different digest creates `IDEMPOTENCY_CONFLICT` and blocks the
stage. The conflict is never resolved by choosing the latest payload.

### 5.2 Candidate and release state

```text
CANDIDATE_DRAFT -> REVIEW_REQUIRED -> REVISE_REQUIRED -> ACCEPTED -> STAGED
                                                        |             |
                                                        +----------> REJECTED

STAGED -> CANARY -> ACTIVE -> SUPERSEDED
                     |
                     +------> ROLLED_BACK
```

The release ledger stores the predecessor version, activation receipt, rollback reason, and pinned flow/job references.

The release transaction is executable and testable:

1. `BEGIN IMMEDIATE` and re-read the active ledger, candidate manifest digest,
   item/contract counts, and open-flow/job pins.
2. For activation, require the staged manifest and portfolio receipt to pass,
   then write exactly one new active ledger row and mark the predecessor
   `SUPERSEDED`.
3. For rollback, require the active version's recorded predecessor, change the
   active version to `ROLLED_BACK`, restore that predecessor to `ACTIVE`, and
   write one rollback receipt with reason and operator/run id.
4. Commit only if the guarded writes affect the expected rows; otherwise roll
   back the transaction and emit no partial release.

Old-version flows continue. Already-pinned steps of a rolled-back new-version
flow may finish with their pinned contract; creation of a later new-version
step is blocked and materializes a child-safe summary/recovery state. New flows
cannot select the rolled-back version. Queued jobs for that version are
paused or dead-lettered according to their stage, never silently repinned.

### 5.3 Retry boundaries

- Transport, rate-limit, and temporary timeout: retry the current stage only, bounded by policy.
- Malformed model output: retry the current generation/review stage once; repeated failure parks the slot for manual review.
- Semantic `REVISE`: create a new candidate version; prior receipts remain historical and cannot approve the new version.
- Collision: do not keep changing numbers until the hash changes; repair the brief within the same bounded budget or mark the slot unavailable.
- Lease expiry: recovery reclaims the job once using fencing; the old worker cannot complete the newer claim.
- Commit crash: replay the idempotency key; never regenerate an already accepted candidate.
- Repeated same-cause failure: pause the slot and send the brief back to brief review. Do not keep spending model calls.
- Quality score below threshold after the final permitted repair: terminate the slot as `needs_manual_review`.
- Coverage debt alone: record and continue to canary review; never launch an automatic repair loop.

### 5.4 Immediate stop conditions

Stop the run when:

- a candidate or commit is written twice;
- evidence is bound to the wrong graph/manifest/candidate hash;
- fixed-answer grading attempts to route to a model;
- a known duplicate or blocked candidate enters the bank;
- a stale worker can complete a newer lease;
- the queue starts without a frozen manifest;
- the obsolete batch-atomic path is invoked.

Park only the affected slot for ordinary model, collision, or lease failures. Unrelated slots continue.

---

## 6. What Happens After Release

Production quality is not proven by schema validity or one successful canary. After each release, record:

- fixed-answer invalid/incomplete/correct rates by field and contract version;
- short-answer assessment disagreement and low-confidence rates;
- prerequisite trace-back frequency and recurring misconception mappings;
- collision discoveries and brief-family repair rate;
- child render/interaction failures;
- items never selected or repeatedly abandoned.

These observations inform the next architecture revision. They do not silently rewrite active questions, lower difficulty, or auto-promote a weak item. Any change to graph contract, evidence mapping, brief, answer contract, or review policy creates new versions and goes through the same manifest gate.

The first real child-facing evaluation should therefore be a small diagnostic/observation release, not a full-bank assumption of quality.

---

## 7. Execution Plan After Approval

Execution begins only after the user explicitly approves this flow.

1. **Contract slice:** deliver/reuse `learning_system/question_quality.py`,
   `learning_system/fixed_answer_assessment.py`, and their isolated tests for
   canonical hashes, `review_packet.v1`, `discovery_derivation.v1`, fixed
   response parsing, and reducer idempotency. Exit only when malformed,
   conflicting, and self-declared-invalid cases fail closed.
2. **Storage and queue slice:** deliver versioned receipt tables, the frozen
   manifest guard, one-slot leases, claim-generation fencing, checkpoints,
   and replay tests. Exit only when a stale worker cannot write and a duplicate
   delivery causes no duplicate side effect.
3. **Architecture/brief slice:** produce the graph snapshot, evidence
   architecture, abstract briefs, per-brief receipts, portfolio report, and
   frozen manifest. Exit only when every required evidence key is covered or
   has an explicit `no_eligible_candidate` blocker; no candidate exists yet.
4. **Synthetic production slice:** run one recorded slot through generation
   fixture, deterministic contract checks, independent review fixture,
   provenance validation, collision check, staged commit, and rollback test.
5. **Risk canary:** produce a representative set covering all response modes,
   high-risk review tiers, renderer paths, and important evidence patterns.
   The set size is determined by coverage, not a product quota. Exit only when
   child rendering, fixed local grading, short-answer model routing, and
   rollback behavior pass.
6. **Full staged production:** generate each frozen slot independently. Every
   slot ends as `STAGED`, `UNAVAILABLE`, or `BLOCKED`; no slot is silently
   deleted and no E0 padding is introduced.
7. **Portfolio acceptance and activation:** run the fail-closed evidence,
   provenance, answer-routing, collision, and lineage audits, then activate
   through `staged -> canary -> active`.
8. **Post-release review:** inspect real learning evidence before changing the
   next architecture or manifest.

## 8. Plan Integrity Checklist

- [x] Brief generation is decoupled from concrete question generation.
- [x] No global total or per-node padding quota controls acceptance.
- [x] E0 mechanical items are excluded from active scheduling.
- [x] Choice and fill-in grading is deterministic and local.
- [x] Short-answer assessment is the only child-answer path that uses a model.
- [x] Generator self-check is not independent approval.
- [x] Per-slot staging is separate from portfolio acceptance and activation.
- [x] Manifest, candidate, receipt, lease, and commit lineage is hash-bound.
- [x] Retry, lease fencing, idempotency, collision, and rollback boundaries are explicit.
- [x] The archived 840-question bank is not reused as production input.
- [ ] User review and explicit authorization to execute.
