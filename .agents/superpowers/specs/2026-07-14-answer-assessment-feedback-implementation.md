# Answer Assessment and Per-Question Feedback Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace model-invented 2-point grading with versioned answer contracts, one GPT semantic criterion judgment, deterministic 10-point scoring, separate assessment storage, and five-part child feedback after every finalized answer.

**Architecture:** Two new authoritative tables (`answer_contracts`, `attempt_assessments`) separate question rules from raw attempts and derived grading. Contract drafts are reviewed in deterministic shards of at most five questions with concurrency one; each item must independently pass question correctness, question-node alignment, evidence-role alignment, contract correctness, and fingerprint review before any global activation. GPT v3 judges child-answer criteria only, while one deterministic reducer owns score, evidence, mastery, next action, and child feedback.

**Tech Stack:** Python 3.13, SQLite, existing `DailyLearningRuntime`, structured GPT JSON through `semantic_agents`, static HTML/CSS/JavaScript child UI, `unittest`.

**Engineering authority:** `docs/architecture/answer_assessment_engineering_contract_v5_1.md`.

**Test source:** `docs/qa/test_case_spec_v5_1_assessment_dual_views.md`.

**Repository note:** This project directory has no `.git`; use the existing pre-v5.1 source archive and SQLite backup, create and verify one shared SHA-256 receipt before production-code edits, and record changed files explicitly. Do not initialize Git. Default rollback is policy off plus source restore; never restore the live DB without explicit user authorization and an incident-time DB backup.

**Phase 0 stop gate:** Do not edit schema, production code, or test code until 镜花 independently rereviews the engineering contract and this revised blueprint with a non-blocking verdict.

---

## Chunk 1: Assessment Authority and Storage

### File Structure

- Create `docs/architecture/answer_assessment_engineering_contract_v5_1.md`: authoritative hot path, ownership, migration, and activation contract.
- Create `learning_system/assessment_policy.py`: lightweight contract profiles, contract validation, criterion-result validation, and deterministic score calculation.
- Create `learning_system/assessment_store.py`: answer-contract and attempt-assessment persistence only.
- Create `learning_system/answer_contract_review.py`: max-five-item shard orchestration, concurrency-one live review, digest idempotency, sealed checkpoints, node/global receipts, and repair-issue emission.
- Create `learning_system/question_fingerprints.py`: versioned canonical instance/structure fingerprint calculation from reviewed normalized mathematics.
- Create `learning_system/assessment_reconciliation.py`: regrade lineage invalidation and deterministic learner-state rebuild.
- Create `learning_system/agent_contracts/answer_review.v3.json`: criterion-key semantic output schema.
- Create `learning_system/agent_contracts/answer_contract_review.v1.json`: per-item question correctness, question-node alignment, evidence-role alignment, contract verdict, and canonical descriptor schema.
- Create `learning_system/prompts/answer_review.v3.md`: one-question semantic judgment prompt.
- Create `learning_system/prompts/answer_contract_review.v1.md`: independent solve/alignment/contract/fingerprint reviewer prompt; it forbids question edits and rebinding.
- Create `scripts/activate_answer_contracts.py`: dry-run/activate all reviewed active questions and print receipts.
- Create `scripts/set_learning_policy.py`: atomically set/verify local runtime policy flags for activation and rollback.
- Create `scripts/browser_answer_assessment_v51.mjs`: real browser feedback, focus, responsive, and leakage acceptance.
- Create `tests/test_answer_assessment_v51.py`: focused storage, scoring, runtime, migration, semantic-oracle, and child-feedback tests.
- Modify `learning_system/db.py`: additive schema and migration indexes/columns.
- Modify `learning_system/internal_agents.py`: select answer-review contract v3.
- Modify `learning_system/semantic_agents.py`: no new authority; consume v3 contract.
- Modify `learning_system/daily_runtime.py`: accepted-assessment hot path and compatibility projection.
- Modify `learning_system/evidence_gate.py`: validate exact assessment lineage.
- Modify `learning_system/question_bank.py`: expose reviewed kind/evidence metadata needed by contract profiles and structural duplicate keys.
- Modify `learning_system/server.py`: child projection reads accepted assessment feedback.
- Modify `learning_system/reports.py`: accepted-assessment authority, legacy labels, and regrade freshness.
- Create `app/local_learning_system/assessment_feedback.js`: render five child-safe feedback sections.
- Modify `app/local_learning_system/index.html`: load feedback renderer and add no hidden grading UI.
- Modify `app/local_learning_system/app.js`: hand accepted feedback to focused renderer.
- Modify `app/local_learning_system/styles.css`: feedback layout and mobile behavior.

### Task 1: Publish Engineering Authority v5.1

**Files:**
- Create: `docs/architecture/answer_assessment_engineering_contract_v5_1.md`
- Reference: `docs/superpowers/specs/2026-07-14-answer-assessment-storage-design.md`
- Reference: `docs/qa/test_case_spec_v5_1_assessment_dual_views.md`

- [ ] **Step 1: Write the authority matrix and exact live hot path**

  Include this executable sequence:

  ```text
  submit attempt -> enqueue answer_analysis -> one GPT criterion judgment
  -> persist accepted agent envelope -> deterministic reducer transaction
  -> accepted attempt_assessment -> EvidenceGate(assessment version)
  -> mastery/next action -> child feedback projection
  ```

  State that live v5.1 answer paths do not enqueue evaluation/planner/teaching model jobs; legacy handlers are compatibility/replay only.

- [ ] **Step 2: Define authority and compatibility ownership**

  Record that `attempt_assessments` is scoring authority and `attempts.score_points/max_points/result/answer_analysis_json` are derived compatibility projections until all pre-v5.1 flows are terminal.

- [ ] **Step 3: Define review, activation, and rollback gates**

  Require:

  - exact semantic approval for every item in the pinned 1,120-item candidate manifest;
  - independent question correctness, question-node alignment, evidence-role alignment, contract, and fingerprint receipts;
  - all consumers to read accepted assessments or explicitly labeled compatibility projections;
  - `ANSWER_ASSESSMENT_POLICY=v5.1` only after all gates pass;
  - source-archive/DB-backup SHA receipt before production-code edits;
  - default rollback by flag off plus source restore, without live DB restore.

- [ ] **Step 4: Verify the document has no conflicting DAG or unresolved terms**

  Run:

  ```bash
  rg -n "TODO|TBD|evaluation_update.*enqueue|planner_decision.*enqueue" docs/architecture/answer_assessment_engineering_contract_v5_1.md
  ```

  Expected: no TODO/TBD; legacy enqueue wording is explicitly compatibility-only.

- [ ] **Step 5: Record checkpoint**

  Save the command output and changed-file list in the daily engineering report; no Git commit is possible.

- [ ] **Step 6: Stop for independent 镜花 review**

  Dispatch `docs/architecture/answer_assessment_engineering_contract_v5_1.md` and this revised blueprint to 镜花. Do not begin schema, production-code, or test-code work until the review verdict is non-blocking. `CONTRACT_READY_FOR_INDEPENDENT_REVIEW` is not implementation authorization.

- [ ] **Step 7: Verify the no-Git safety receipt before the first production-code edit**

  Use the existing backups:

  ```text
  data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz
  data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite
  ```

  Run:

  ```bash
  shasum -a 256 \
    data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz \
    data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite \
    > data/backups/v5.1-preimplementation-backups.sha256
  shasum -a 256 -c data/backups/v5.1-preimplementation-backups.sha256
  tar -tzf data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz >/dev/null
  sqlite3 data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite "pragma integrity_check;"
  ```

  Expected: both checksums verify, source archive is readable, and SQLite integrity is `ok`. Stop if any check fails.

### Task 2: Add Failing Schema and Store Tests

**Files:**
- Create: `tests/test_answer_assessment_v51.py`
- Modify: `learning_system/db.py`

- [ ] **Step 1: Write failing additive-schema tests**

  Assert `db.init_schema()` creates:

  ```python
  expected_tables = {"answer_contracts", "attempt_assessments"}
  expected_flow_columns = {"answer_contract_id", "answer_contract_version"}
  expected_validation_columns = {"assessment_id", "assessment_version", "assessment_digest_sha256"}
  ```

  Also assert `attempts` has nullable `clarifies_attempt_id` plus `attempt_role`, `daily_flows` has `assessment_policy_version`, contract rows carry independent review run/receipt refs, one-current contract exists per immutable question version, and one-current accepted assessment exists per attempt version.

- [ ] **Step 2: Run tests and verify failure**

  Run:

  ```bash
  python3 -m unittest tests.test_answer_assessment_v51.AnswerAssessmentSchemaTests -v
  ```

  Expected: FAIL because the tables/columns do not exist.

- [ ] **Step 3: Add only the approved additive schema**

  Add `answer_contracts` with stable id, question id/item version, contract version/digest, reference solution JSON, score points JSON, generator/review lineage, status, activation timestamps.

  Add `attempt_assessments` with assessment version/digest, criterion judgments JSON, 10-point score, pass qualification, five feedback fields, trust/provider lineage, status, superseded id, timestamps.

  Add minimal contract refs to `question_review_records`/`flow_steps`, clarification lineage to `attempts`, policy pin to `daily_flows`, and assessment refs to `evidence_validations` using `_ensure_column` for existing databases.

- [ ] **Step 4: Add uniqueness/index rules**

  ```sql
  create unique index ... on answer_contracts(question_id, question_item_version)
    where status = 'active';
  create unique index ... on attempt_assessments(attempt_id, attempt_version)
    where status = 'accepted';
  ```

- [ ] **Step 5: Run schema tests**

  Expected: PASS with existing DB initialization tests still passing.

- [ ] **Step 6: Record checkpoint**

  Record schema diff and test output in the daily engineering report.

### Task 3: Implement Lightweight Contract Profiles

**Files:**
- Create: `learning_system/assessment_policy.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing profile tests for representative kinds**

  Cover at least:

  ```python
  kinds = [
      "standard_example", "variant", "error_spotting", "two_method_compare",
      "model_selection", "representation", "explanation_only", "boundary_case",
  ]
  ```

  Assert every generated contract has a nonempty reference solution, two to four unique atomic keys, positive integer points totaling 10, graph-valid dimensions, and at least one required-for-pass point.

- [ ] **Step 2: Run tests and verify failure**

  Expected: FAIL because `build_answer_contract()` is missing.

- [ ] **Step 3: Implement contract profiles by evidence role**

  Implement focused profiles, for example:

  ```python
  PROFILE_BY_KIND = {
      "standard_example": (("final_conclusion", 5, "final_answer"), ("core_relation", 4, "model_relation"), ("required_expression", 1, "expression_notation")),
      "error_spotting": (("locate_error", 4, "concept"), ("correct_solution", 4, "procedure"), ("verify_correction", 2, "check")),
      "two_method_compare": (("method_one", 3, "procedure"), ("method_two", 3, "procedure"), ("comparison_conclusion", 4, "transfer")),
  }
  ```

  Criterion text refers to the approved reference solution and prompt goal; it does not enumerate child wording or use regex answer rules.

- [ ] **Step 4: Implement strict contract and judgment validation**

  Validate exact criterion-key coverage, no duplicates/unknowns, statuses only `met/not_met/contradicted/unclear`, grounded evidence for `met`, and no final score when any criterion is unclear.

- [ ] **Step 5: Implement deterministic scoring**

  ```python
  score = sum(point["points"] for point in contract["score_points"] if judgments[point["key"]]["status"] == "met")
  passed = all(judgments[p["key"]]["status"] == "met" for p in contract["score_points"] if p["required_for_pass"])
  ```

  Return 10-point score, compatibility 2-point projection, result, dimension evidence, and pass qualification.

- [ ] **Step 6: Run policy tests**

  Expected: PASS for all representative kinds and the number-line regression scores 10/10.

- [ ] **Step 7: Record checkpoint**

  Record profile coverage and uncovered active kinds, which must be zero before activation.

### Task 4: Persist Contracts and Assessments

**Files:**
- Create: `learning_system/assessment_store.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing CRUD/idempotency tests**

  Test contract activation, immutable version reuse by digest, assessment acceptance, retry reuse, supersession, and rejection of two accepted assessments for one attempt version.

- [ ] **Step 2: Run tests and verify failure**

  Expected: FAIL because the store functions are missing.

- [ ] **Step 3: Implement answer-contract store API**

  Required functions:

  ```python
  activate_contract(conn, *, question, review_record_id, contract, generator_version) -> dict
  active_contract_for_question(conn, *, question_id, item_version) -> dict
  bind_contract_to_flow_step(conn, *, flow_step_id, contract) -> None
  ```

- [ ] **Step 4: Implement assessment store API**

  Required functions:

  ```python
  accepted_assessment_for_attempt(conn, attempt_id, attempt_version) -> dict | None
  record_pending_assessment(...)
  accept_assessment(...)
  supersede_assessment(...)
  assessment_feedback_projection(...)
  ```

- [ ] **Step 5: Keep raw attempts immutable**

  The store may write compatibility grading columns only from an accepted assessment in the same transaction; it must never rewrite `answer_raw`, attachment ids, or interaction response.

- [ ] **Step 6: Run store tests**

  Expected: PASS, including retry and supersession tests.

- [ ] **Step 7: Record checkpoint**

  Record the authoritative/compatibility write paths.

### Task 5: Activate Contracts for All Active Questions

**Files:**
- Create: `scripts/activate_answer_contracts.py`
- Create: `learning_system/answer_contract_review.py`
- Create: `learning_system/agent_contracts/answer_contract_review.v1.json`
- Create: `learning_system/prompts/answer_contract_review.v1.md`
- Create: `learning_system/question_fingerprints.py`
- Modify: `learning_system/question_bank.py`
- Modify: `learning_system/db.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write a failing all-bank activation test**

  Load a temporary initialized DB and assert dry-run separates structural draft coverage from semantic approval:

  ```python
  assert report["active_manifest_items"] == 1120
  assert report["draft_contracts_generated"] == 1120
  assert report["semantic_approved"] == 0  # no accepted live receipts yet
  assert report["semantic_missing"] == 1120
  assert report["activation_ready"] is False
  ```

  Dry-run may prove 1,120 drafts; it must never predeclare 1,120 approved items.

  Add permanent red oracles:

  ```python
  known_misbindings = {
      "QB11-M-G7-NUMBER-LINE-19",
      "QB11-M-G7-RATIONAL-ADD-SUB-09",
  }
  ```

  Both must return `question_node_alignment=misbound`, remain inactive, emit repair-required issues, and block global activation.

- [ ] **Step 2: Run test and verify failure**

  Expected: FAIL because no activation script/store integration exists.

- [ ] **Step 3: Implement deterministic draft generation**

  Read only active approved `question_review_records` and generate draft contracts from reviewed question metadata. Draft status is never active before independent review.

- [ ] **Step 4: Define the independent reviewer packet, schema, and prompt**

  Route `answer_contract_reviewer_agent` / task `answer_contract_review` to GPT-5.5. Each shard contains one node and at most five immutable questions.

  Required node packet fields:

  - node name and one-sentence essence;
  - node question types, mastery criteria, diagnostic probes, teaching contract;
  - summer mode (`summer_execution.mode`);
  - strict prerequisite/rollback context and controlled-extension policy;
  - the node's question-generation/命题 contract.

  Required per-item fields:

  - immutable question id/item version/digest and pinned bank manifest;
  - prompt, expected answer, solution steps, interaction schema;
  - bound node, kind, evidence role, problem family/core stem;
  - designer and independent question-review lineage;
  - draft contract id/version/digest, reference solution, score points/dimensions;
  - draft instance/core descriptors and fingerprint-policy version.

  The output schema requires, per item:

  ```text
  question_correctness: pass|fail|ambiguous
  question_node_alignment: aligned|misbound|ambiguous
  evidence_role_alignment: aligned|misaligned|ambiguous
  answer_contract_review: approved|rejected
  normalized_instance_descriptor
  normalized_core_structure_descriptor
  confidence
  exact question/contract digests
  ```

  The prompt requires an independent solution and grounded mathematical-core reasoning. Self-attested `node_alignment.reason`, `本题重点`, kind, tags, allowlists, or schema validity are not proof. The reviewer may report repair reasons or advisory candidate nodes but may not edit the question or rebind it.

- [ ] **Step 5: Implement deterministic max-five sharding and concurrency one**

  For each 20-item node, create four ordered shards of at most five items. Current totals are 224 shards across 56 nodes. Global live review concurrency is exactly one.

  Route policy:

  ```text
  model: gpt-5.5
  timeout: 120 seconds per shard
  max total attempts: 3
  retryable: 429/500/502/503/504, timeout, rate limit, temporarily unavailable, malformed/schema-invalid output
  backoff: 20 seconds, then 60 seconds; honor Retry-After up to 180 seconds
  ```

- [ ] **Step 6: Implement digest idempotency and sealed checkpoints**

  The shard digest commits to reviewer schema/prompt/route policy, graph/node context, summer mode, question-generation contract, bank manifest, ordered question/contract digests, evidence roles, and fingerprint policy.

  Checkpoint root:

  ```text
  data/question_banks/math/.answer_contract_review_v51/<bank-version>/<node-id>/
  ```

  Atomically write a sealed checkpoint after every terminal shard result. Reuse only matching accepted `live_model` receipts with exact agent/task/phase/digests; restart retries only incomplete retryable shards and preserves terminal rejection as a blocker.

- [ ] **Step 7: Implement node aggregate and global receipts**

  A node aggregate receipt requires four matching shard receipts, exactly 20 unique items, and zero failed/ambiguous/stale/non-live results.

  The global receipt requires exactly 56 accepted node receipts and 1,120 unique items where all of these pass:

  ```text
  question_correctness=pass
  question_node_alignment=aligned
  evidence_role_alignment=aligned
  answer_contract_review=approved
  fingerprint pair valid
  exact live receipt lineage valid
  ```

  One failure writes no global active receipt and no partial active contract set.

- [ ] **Step 8: Implement the question-bank repair route**

  A correctness/node/evidence-role rejection creates a machine-readable repair issue and keeps the old item immutable/inactive for v5.1. Repair must:

  1. create a new immutable question id/item version under a new monotonic bank version/manifest;
  2. run the question designer and a separate independent question reviewer;
  3. activate the repaired question in a new candidate bank only after that review passes;
  4. generate a fresh contract and rerun the contract reviewer;
  5. rerun node/global receipts.

  No in-place prompt/answer/node edit, silent rebind, or contract-reviewer-authored replacement is allowed.

- [ ] **Step 9: Add active-use gate**

  Update `db.is_child_schedulable_question()` so a v5.1-pinned flow requires an active independently reviewed contract and reviewed fingerprint pair while legacy policy remains readable.

- [ ] **Step 10: Run draft dry-run on the real DB without semantic claims**

  Run:

  ```bash
  python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --dry-run
  ```

  Expected: 1,120 manifest items and, if structurally possible, 1,120 drafts; no model calls or activation writes. Report semantic approved/missing/rejected separately. With current v11 known misbindings, `activation_ready=false` is mandatory.

- [ ] **Step 11: Run resumable live independent review**

  Run the 224 max-five shards sequentially with checkpoint/resume. The current v11 bank must reject at least the two mandatory oracle rows. Do not treat completion of all calls as approval.

- [ ] **Step 12: Repair rejected bank items through new immutable versions**

  Run designer + independent question reviewer under a new bank version, then regenerate/re-review contracts. Preserve old questions and attempts for audit.

- [ ] **Step 13: Back up and activate only an all-aligned candidate bank**

  After the safety receipt in Task 12 exists, run `--activate` only when the exact candidate manifest has 1,120 accepted live item receipts, 56 node receipts, zero blockers, and one valid contract/fingerprint pair per item. Activation is one transaction; a single failure leaves every draft inert.

  Contract rows remain inert for legacy flows. Child scheduling requires both an active reviewed contract and a flow pinned to `assessment_policy_version='v5.1'`; early contract activation cannot change existing flow behavior.

- [ ] **Step 14: Record checkpoint**

  Save shard/checkpoint/node/global receipt digests, repair issues and replacement lineage, bank/graph/manifest digests, live run ids, semantic approved/rejected/missing counts, contract/fingerprint counts, and per-kind distribution.

---

## Chunk 2: One-Call Runtime, Evidence, and Child Feedback

### Task 6: Add Answer-Review v3 Contract and Prompt

**Files:**
- Create: `learning_system/agent_contracts/answer_review.v3.json`
- Create: `learning_system/prompts/answer_review.v3.md`
- Modify: `learning_system/internal_agents.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing schema tests**

  Assert the v3 schema requires `criteria`, `answer_gap`, `improvement_direction`, `expression_judgment`, `teaching_explanation`, and confidence; it must not allow model-emitted point totals, mastery support, or next-step recommendations.

- [ ] **Step 2: Run tests and verify failure**

  Expected: FAIL while v2 remains selected.

- [ ] **Step 3: Create v3 schema**

  Criterion item fields are exactly:

  ```json
  {"criterion_key":"...","status":"met|not_met|contradicted|unclear","child_evidence":"...","reason":"..."}
  ```

  The output schema contains no `evaluation_support` and no `next_evidence_need`.

- [ ] **Step 4: Create v3 expert prompt**

  Require semantic equivalence, ignore non-scoring presentation preferences, accept alternative valid methods, cite child evidence, and judge only preloaded criteria. Explicitly forbid calculating a total score, recommending mastery, or choosing a next action.

- [ ] **Step 5: Select v3 in `internal_agents.py`**

  Change only `answer_analysis_agent.v5_contract_version_suffix` to `v3`.

- [ ] **Step 6: Run contract and recorded-envelope tests**

  Expected: PASS for valid exact-key output; malformed/missing/duplicate keys fail closed.

- [ ] **Step 7: Record checkpoint**

  Record prompt/schema digests.

### Task 7: Implement the Accepted-Assessment Hot Path

**Files:**
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/evidence_gate.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing runtime tests**

  Cover one GPT call, exact-key validation, deterministic 10-point score, accepted assessment, compatibility projection, deterministic evaluation/next-action derivation from criteria, EvidenceGate assessment refs, no downstream model jobs, and result-ref replay after restart.

- [ ] **Step 2: Run tests and verify failure**

  Expected: FAIL because runtime still trusts model `score_points` and writes attempts directly.

- [ ] **Step 3: Bind the active contract when materializing a question step**

  Capture contract id/version/digest on `flow_steps`; block serving when v5.1 is active and no contract exists.

- [ ] **Step 4: Change `_answer_analysis_request()`**

  Send one selected question, its approved reference solution/atomic score points, child response/OCR evidence, exact versions, and no full bank/history.

- [ ] **Step 5: Change `_handle_answer_analysis_job()`**

  Persist the accepted agent envelope, validate exact criteria, calculate score in `assessment_policy`, accept assessment in `assessment_store`, write compatibility projection, and call EvidenceGate with assessment lineage.

  Compatibility mapping is fixed:

  ```text
  attempts.max_points = 2
  attempts.score_points = assessment.score_out_of_10 / 5
  attempts.result = correct when question_passed; otherwise partial when score > 0; otherwise wrong
  attempts.answer_analysis_json = derived criterion comparison/feedback projection, never a second grading authority
  ```

- [ ] **Step 6: Preserve explicit stuck fast path**

  `我不会/卡住` remains an unscored support request with zero GPT calls and no accepted assessment/mastery evidence.

- [ ] **Step 7: Make reducer replay idempotent**

  Reuse the accepted assessment/result refs after handler commit or worker restart; never recall GPT for the same evidence/contract digest.

- [ ] **Step 8: Run focused runtime tests**

  Expected: PASS and no `evaluation_update/planner_decision/teaching_generation` jobs on live text hot path.

- [ ] **Step 9: Record checkpoint**

  Record model-call count and result lineage.

### Task 8: Implement Clarification as Supporting Evidence

**Files:**
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/assessment_store.py`
- Modify: `learning_system/evidence_gate.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing clarification-lineage tests**

  Cover original unclear attempt, linked `supporting_only` clarification attempt, ordered evidence digest, reanalysis to a new assessment version on the original attempt, duplicate clarification idempotency, and exactly one mastery-eligible attempt.

- [ ] **Step 2: Run tests and verify failure**

  Expected: current clarification path cannot prove the required lineage.

- [ ] **Step 3: Persist clarification linkage**

  Clarification submission creates an immutable attempt with `attempt_role='supporting_only'` and `clarifies_attempt_id=<original>`. It never receives its own score/mastery decision.

- [ ] **Step 4: Rebuild the original assessment input digest**

  Include original attempt evidence plus ordered linked clarification ids/digests and exact contract/policy versions. Reanalysis creates the next assessment version for the original attempt.

- [ ] **Step 5: Gate only the latest accepted original assessment**

  Prevent supporting attempts from entering mastery/reports as independent questions.

- [ ] **Step 6: Run clarification tests**

  Expected: PASS for clear clarification, repeated unclear, cannot-provide, duplicate submit, and text/photo conflict.

- [ ] **Step 7: Record checkpoint**

  Record original/supporting/assessment/validation ids for one test trace.

### Task 9: Rewire Mastery and Duplicate Selection

**Files:**
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/question_bank.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing mastery/selection tests**

  Assert criterion dimensions, not model total prose, drive mastery support. Add permanent regression: `a,c,b / c=a+3=0.5` passes 10/10 and cannot be followed by the same A/B/C number-line instance or a cosmetic rewrite with the same reviewed mathematical core as transfer.

- [ ] **Step 2: Run tests and verify failure**

  Expected: duplicate-core regression or criterion-lineage assertion fails.

- [ ] **Step 3: Feed accepted assessment dimensions to the existing deterministic reducers**

  Keep one-answer mastery conservative. Required criterion failure chooses teaching/probe; a full direct pass may choose real near transfer only when the candidate fingerprint differs.

- [ ] **Step 4: Enforce canonical instance/structure fingerprints**

  Enforce the activated reviewed fingerprint-policy version and receipts from Task 5. Exclude same prompt-instance fingerprints and cosmetic variants with the same core descriptor when transfer is requested. Allow at most one post-teaching same-structure confirmation and never label it transfer.

- [ ] **Step 5: Run mastery and selection tests**

  Expected: PASS, including prerequisite-first and no third same-structure item.

- [ ] **Step 6: Record checkpoint**

  Record the number-line regression trace.

### Task 10: Implement Regrade Reconciliation and Legacy Reporting

**Files:**
- Create: `learning_system/assessment_reconciliation.py`
- Modify: `learning_system/assessment_store.py`
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/reports.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing regrade tests**

  Cover accepted assessment supersession, temporary no-current-assessment `correcting` projection, stale validation/mastery/decision/summary lineage, deterministic `learner_node_status` rebuild, open dependent-step replacement, closed historical-step preservation, and latest report freshness.

- [ ] **Step 2: Run tests and verify failure**

  Expected: supersession leaves stale learner/report state.

- [ ] **Step 3: Implement one reconciliation transaction**

  Supersede the old assessment, mark dependent derived rows stale by lineage, accept the corrected assessment, create a new validation, and rebuild the affected node from all current accepted nonstale evidence in evidence-time order.

- [ ] **Step 4: Replan only open dependent state**

  Supersede an unconsumed current step selected from stale evidence. Do not rewrite completed historical steps.

- [ ] **Step 5: Implement legacy report fallback**

  Rows without accepted v5.1 assessments render as `legacy_unmigrated`, retain original trust labels, and never become new mastery evidence. Update `learning_system/reports.py` and `scripts/generate_daily_report.py` consumers.

- [ ] **Step 6: Run regrade/report tests**

  Expected: one current assessment, rebuilt learner status, fresh report, and honest correcting/legacy projections.

- [ ] **Step 7: Record checkpoint**

  Save before/after lineage ids and rebuilt status trace.

### Task 11: Project and Render Five-Part Feedback

**Files:**
- Create: `app/local_learning_system/assessment_feedback.js`
- Create: `scripts/browser_answer_assessment_v51.mjs`
- Modify: `app/local_learning_system/index.html`
- Modify: `app/local_learning_system/app.js`
- Modify: `app/local_learning_system/styles.css`
- Modify: `learning_system/daily_runtime.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing child-projection tests**

  Assert finalized feedback contains only:

  ```json
  {
    "score_label": "10/10",
    "reference_answer": "...",
    "answer_gap": "...",
    "improvement_direction": ["..."],
    "expression_judgment": "..."
  }
  ```

  plus one runtime-selected action. Assert no contract keys, dimensions, ids, model data, or confidence leak.

- [ ] **Step 2: Write failing browser acceptance before UI code**

  `scripts/browser_answer_assessment_v51.mjs` starts/uses an isolated v5.1 server and asserts semantic section headings, model text inserted with `textContent`/safe DOM creation, polite live region, focus moved to feedback heading, next-action focus order, Escape behavior where applicable, no hidden tabbables, and no overlap at 1280x800 or 390x844.

- [ ] **Step 3: Run tests and verify failure**

  Expected: FAIL because projection has no per-question assessment feedback.

- [ ] **Step 4: Add accepted-assessment feedback projection**

  Show feedback before the next action. `unclear`, stuck, cannot-provide, and blocked paths show no fabricated score.

- [ ] **Step 5: Implement focused renderer**

  `window.AssessmentFeedback.render(feedback)` builds semantic DOM nodes with `createElement` and `textContent`; it never interpolates model text into `innerHTML`. It does not know graph ids, score criteria, or model metadata.

- [ ] **Step 6: Integrate with existing v5 state rendering**

  Keep the current question form hidden while feedback is displayed; provide the runtime action button without assuming it always starts another question.

- [ ] **Step 7: Add responsive styles**

  Use full-width unframed feedback sections or one modest result panel; no nested cards, no oversized headings, no text overlap at 390px.

- [ ] **Step 8: Run child-safe, DOM, and browser tests**

  Run:

  ```bash
  node scripts/browser_answer_assessment_v51.mjs --scenario all --start-isolated
  ```

  Expected: PASS for correct, partial, wrong-reason/right-answer, alternative method, unclear photo, and stuck at both viewports.

- [ ] **Step 9: Record checkpoint**

  Save desktop/mobile screenshots and forbidden-key scan.

### Task 12: Migrate, Activate, Regress, and Measure

**Files:**
- Modify: `tests/test_learning_system.py` only for existing-contract compatibility assertions that cannot live in the focused test file.
- Modify: `scripts/live_child_acceptance.py`
- Modify: `scripts/generate_daily_report.py`
- Modify: `learning_system/reports.py`
- Modify: `.env.local`

- [ ] **Step 1: Run focused tests**

  ```bash
  python3 -m unittest tests.test_answer_assessment_v51 -v
  ```

  Expected: all PASS.

- [ ] **Step 2: Run full system tests**

  ```bash
  python3 -m unittest tests/test_learning_system.py -v
  ```

  Expected: all PASS; legacy recorded fixtures remain explicitly labeled.

- [ ] **Step 3: Run contract activation audit**

  Expected: the pinned candidate manifest contains exactly 1,120 items; all 1,120 have accepted live correctness/node/evidence-role/contract receipts, 56 accepted node aggregate receipts, zero blockers, and one current contract/fingerprint pair per item. Draft count alone is not activation evidence.

- [ ] **Step 4: Start an isolated temporary-DB server and run browser flows**

  Cover correct concise answer, answer-only when reasoning is required, right answer/wrong reasoning, alternative valid method, explicit stuck, readable photo, unclear photo, text/photo conflict, restart, and duplicate submit.

- [ ] **Step 5: Measure latency and calls**

  Record submission-to-feedback duration and assert one GPT call for normal text, zero for explicit stuck, and OCR plus one GPT call for photo.

- [ ] **Step 6: Run the permanent number-line regression**

  Expected: 10/10, expression equivalence accepted, no same-instance next question.

- [ ] **Step 7: Inventory and pin consumers/flows before activation**

  Inventory every read of `attempts.score_points/max_points/result/answer_analysis_json` across `daily_runtime.py`, `reports.py`, `planner.py`, `flow_nodes.py`, `orchestrator.py`, `evolution.py`, and scripts. Migrate authoritative readers to accepted assessments or label explicit compatibility reads. Pin `daily_flows.assessment_policy_version` at creation so open legacy flows cannot mix policies.

  Add tests for `ANSWER_ASSESSMENT_POLICY` values: unset/off/unknown use legacy; `v5.1` enables new flows only. Require `rg -n "ANSWER_ASSESSMENT_POLICY" learning_system` to show the only environment read inside `daily_runtime.answer_assessment_v51_enabled()`.

- [ ] **Step 8: Re-verify the source/DB safety receipt and write the changed-file receipt**

  Before activation, rerun:

  ```bash
  shasum -a 256 -c data/backups/v5.1-preimplementation-backups.sha256
  tar -tzf data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz >/dev/null
  sqlite3 data/backups/local_learning_system.pre-v5.1.20260714-144846.c8b86311-456e-499c-970f-400a8d83d5b1.sqlite "pragma integrity_check;"
  ```

  Write `logs/answer-assessment-v51-changed-files.txt` with all created/modified paths, the safety receipt, contract/bank/graph/shard/node/global digests, tests, provider scope, and results. Expected integrity output: `ok`.

- [ ] **Step 9: Activate v5.1 policy atomically**

  Activate and audit contracts/fingerprints before enabling the runtime policy:

  ```bash
  python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --activate
  python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --audit
  ```

  Only after both commands succeed, implement and use:

  ```bash
  python3 scripts/set_learning_policy.py --answer-assessment v5.1
  ```

  This atomically sets `ANSWER_ASSESSMENT_POLICY=v5.1` in `.env.local`; `daily_runtime.answer_assessment_v51_enabled()` is the only environment-read boundary. Activate contracts/fingerprints, restart service, verify `/api/child-bootstrap`, and preserve pre-v5.1 jobs until terminal.

  Post-activation audit:

  ```bash
  sqlite3 data/local_learning_system.sqlite "pragma integrity_check;"
  python3 scripts/activate_answer_contracts.py --db data/local_learning_system.sqlite --audit
  ```

  Default rollback procedure:

  1. Stop the live service. If it is running in a Codex exec session, send Ctrl-C through `functions.write_stdin` to that exact session and wait for exit. If it is PID-file managed, run:

  ```bash
  python3 scripts/set_learning_policy.py --answer-assessment off
  if [[ -f logs/server-8765.pid ]]; then PID=$(cat logs/server-8765.pid); kill "${PID}"; while kill -0 "${PID}" 2>/dev/null; do sleep 0.2; done; fi
  test -z "$(lsof -tiTCP:8765 -sTCP:LISTEN)"
  ```

  If the final `test` fails, stop and terminate the normal service session before continuing. Do not restore while any process is listening on 8765 or holding the live service session.

  2. Restore source only and leave the live DB in place:

  ```bash
  cd /Users/liuchang/Documents/gitproject/son-ai-learning-system
  shasum -a 256 -c data/backups/v5.1-preimplementation-backups.sha256
  tar -xzf data/backups/son-ai-learning-system.source-before-v5.1.20260714-151700.c0f17514-aea3-46ad-ad9b-6f20c8975e08.tar.gz -C /Users/liuchang/Documents/gitproject/son-ai-learning-system
  python3 scripts/set_learning_policy.py --answer-assessment off
  ```

  Remove files created only by v5.1 according to `logs/answer-assessment-v51-changed-files.txt`. Do not delete or overwrite `data/local_learning_system.sqlite`; additive rows remain inert and auditable under the off policy.

  3. Restart `scripts/run_local_learning_server_8765.sh` in its normal long-running service session. From a second shell/session verify:

  ```bash
  curl -fsS http://127.0.0.1:8765/api/child-bootstrap
  ```

  Expected: source checksum verifies, service starts under legacy policy, and bootstrap returns HTTP 200.

  Live DB restore is forbidden by default. It requires explicit user authorization, a stopped service, a newly captured incident-time backup of the current live DB, integrity checks for both databases, and a written statement of learning records that the restore would lose. Without those conditions, do not run `.restore`.

- [ ] **Step 10: Generate the engineering and parent-readable report**

  Include contract coverage, assessment lineage, live model-call counts, latency percentiles, browser cases, remaining legacy rows, and rollback instructions.

- [ ] **Step 11: Record final checkpoint**

  List every changed file and test command because Git commits are unavailable.

## BLUEPRINT_READINESS_GATE

- verdict: `BLUEPRINT_READY_FOR_INDEPENDENT_REVIEW`
- files_and_symbols_named: yes
- behavior_contract_complete: yes
- producer_consumer_impact_named: yes
- validation_commands_named: yes
- skeleton_plan_ready: yes
- test_design_handoff_clear: yes; source is `docs/qa/test_case_spec_v5_1_assessment_dual_views.md`
- rollback_or_recovery_clear: yes
- engineering_quality_bar_addressed: yes
- semantic_alignment_fail_closed: yes
- question_bank_repair_route_complete: yes
- shard_checkpoint_receipt_policy_complete: yes
- quality_evidence:
  - Phase 0 authority is pinned to `docs/architecture/answer_assessment_engineering_contract_v5_1.md`;
  - Task 5 separates 1,120 drafts from 1,120 live semantic approvals and includes both mandatory misbinding oracles;
  - reviewer packet/schema/prompt, max-five sharding, concurrency one, timeout/retry/idempotency/checkpoints, node/global receipts, and immutable repair routing are explicit;
  - Task 12 uses source/DB backup receipt and flag/source rollback without default live DB restore.
- blocking_gaps: independent 镜花 rereview is required before schema, production-code, or test-code implementation
