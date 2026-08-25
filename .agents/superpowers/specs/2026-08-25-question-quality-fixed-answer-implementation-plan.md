# Question Quality and Fixed-Answer Assessment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace low-information active questions with graph-bound, reviewer-derived E1-E4 questions, add deterministic choice/fill-in assessment and child fill-in cards, and activate a new versioned math bank without changing historical lineage.

**Architecture:** Keep the existing SQLite runtime, question generation pipeline, answer-contract pipeline, and child-safe projection as the authoritative boundaries. Add focused deterministic modules for question-quality derivation and fixed-answer parsing, store their versioned receipts on question/contract/assessment rows, and make activation plus mastery reduction enforce the contracts transactionally. The old `2026-08-20.v1` bank remains readable for historical attempts but is never rewritten or rebound.

**Tech Stack:** Python 3, SQLite, existing `learning_system` modules, JSON schema-style validators already used by the repository, exact rational parsing, existing browser fixtures and Node tests, `unittest`.

**Source Spec:** `/Users/liuchang/Documents/gitproject/son-ai-learning-system/docs/superpowers/specs/2026-08-25-question-quality-and-fixed-answer-design.md`

---

## File Map

Create:

- `learning_system/question_quality.py` - canonical `review_packet.v1`, `discovery_derivation.v1`, E0-E4 derivation, node evidence normalization, low-information and coverage gates.
- `learning_system/fixed_answer_assessment.py` - closed response envelopes, duplicate-key JSON parsing, exact numeric/fraction/algebraic/text grading, field-level aggregation, and assessment receipts.
- `scripts/review_question_quality.py` - run independent `question_reviewer_agent` review, persist `review_packet.v1` and reviewer receipts, and emit an auditable quality manifest.
- `scripts/activate_semester_bank_v2.py` - concrete staged/audit/activate/rollback entry point for the replacement semester bank.
- `tests/test_question_quality.py` - canonicalization, derivation, adversarial quality, fingerprint, scheduling, and evidence-contract tests.
- `tests/test_fixed_answer_assessment.py` - response schema, parser grammar, deterministic grading, malformed input, idempotency, and mastery-ceiling tests.
- `tests/fixtures/question_quality_review_packets.json` - small canonical review-packet fixtures for E0-E4 and invalid dependency cases.
- `tests/test_semester_bank_v2_activation.py` - isolated bank generation, cutover, rollback, and historical-lineage tests.

Modify:

- `learning_system/db.py` - additive columns/tables/indexes and transaction helpers for question quality receipts, fixed assessments, reducer effects, and cutover fencing.
- `learning_system/question_fingerprints.py` - `question_fingerprint.v2` exact-instance and family projections with structural derivation digest support.
- `learning_system/question_generation_service.py` - replace fixed easy/medium/hard matrix acceptance with quality-contract candidate production and no-padding behavior.
- `learning_system/question_bank.py` - enforce active-bank quality, family quotas, evidence alignment, and versioned activation manifests.
- `learning_system/answer_contract_generation_v2.py` - emit authoritative fixed-answer and evidence-profile contracts alongside short-answer contracts.
- `learning_system/answer_contract_activation.py` - activate only contracts whose quality/evidence digests and independent receipts match.
- `learning_system/child_prompt.py` - normalize and project `fill_blank` cards with stable field ids and child-safe states.
- `learning_system/daily_runtime.py` - route fixed answers locally, retain short-answer model routing, and apply fixed-assessment reducer effects.
- `learning_system/planner.py` - enforce E1 foundation signals, selective-core evidence intersection, extension quotas, and `no_eligible_candidate` outcomes.
- `scripts/generate_semester_bank.py` - generate a new bank version from the revised matrix without editing the old SQLite bank.
- `scripts/activate_answer_contracts.py` - preserve answer-contract activation compatibility while the new bank entry point supplies its pinned version.
- `scripts/activate_three_node_pilot.py` - preserve shared ledger/receipt helpers and update only common cutover behavior used by the new entry point.
- `tests/test_question_generation_service.py` - migrate existing matrix assertions to quality-level and no-fixed-quota assertions.
- `tests/test_question_bank_runtime_authority.py` - add new-version pinning, stale-version, and activation authority coverage.
- `tests/test_answer_assessment_v51.py` - preserve short-answer behavior and add runtime separation assertions where the existing suite owns them.
- `tests/test_local_learning_child_answer_contract.py` - add child-safe fill-in projection coverage.
- `tests/browser_interaction_schema_v1.mjs` and `tests/browser_smoke_learning_system.mjs` - exercise fill-in rendering, field submission, invalid/incomplete/submitted states, and no model call for fixed answers.
- `tests/test_three_node_pilot_activation.py` - extend cutover, rollback, active-job, and lease-fencing coverage.
- `tests/test_planner_retest_scheduling.py` - extend planner quality predicates.
- `tests/test_planner_trace_back_integration.py` - extend no-candidate and prerequisite recovery coverage.

Do not modify:

- `data/question_banks/math/semester_bank_v1.sqlite` (`2026-08-20.v1`) except to read it as historical input.
- Existing user changes unrelated to this feature.

## Chunk 1: Canonical Contracts and Storage

### Task 1: Add quality and evidence contract primitives

**Files:**
- Create: `learning_system/question_quality.py`
- Create: `learning_system/fixed_answer_assessment.py`
- Test: `tests/test_question_quality.py`
- Test: `tests/test_fixed_answer_assessment.py`

- [ ] **Step 1: Write failing canonicalization tests.**
  Cover UTF-8 canonical JSON, lexicographic object keys, semantic-array order preservation, set-array sorting, NFKC/operator normalization, prompt span token offsets, and SHA-256 output. Assert duplicate object keys are rejected rather than silently overwritten.

- [ ] **Step 2: Run the focused tests and verify failure.**
  Run: `python3 -m unittest tests.test_question_quality tests.test_fixed_answer_assessment -v`
  Expected: FAIL because the new modules and versioned contract functions do not exist.

- [ ] **Step 3: Implement the smallest versioned primitives.**
  Define constants `REVIEW_PACKET_SCHEMA_VERSION`, `DISCOVERY_DERIVATION_SCHEMA_VERSION`, `QUESTION_FINGERPRINT_POLICY_VERSION`, `FIXED_RESPONSE_SCHEMA_VERSION`, and `GRAPH_EVIDENCE_CONTRACT_VERSION`. Implement strict object validation that rejects unknown keys, duplicate ids, null envelopes, oversized payloads, and invalid enum values. Keep model calls out of these modules.

- [ ] **Step 4: Add failing graph-evidence tests.**
  Assert the explicit current mapping `结果正确 -> answer_correctness`, `过程可复盘 -> process_explanation`, `能口头解释 -> verbal_explanation`, `能做一道小变式 -> transfer`; assert unmapped values block activation; assert `requires_for_mastery`, `selective_core_evidence_keys`, fixed-answer policy, and ceiling are graph-authoritative.

- [ ] **Step 5: Implement graph evidence normalization and ceiling derivation.**
  Return a digestible `graph_evidence_contract.v1` object. Derive fixed-answer ceiling `B` whenever process, verbal-explanation, or transfer evidence is required. Default to `observation_only`/`B`; permit `confirmation_eligible` only from an explicit graph policy.

- [ ] **Step 6: Run the focused tests again.**
  Run: `python3 -m unittest tests.test_question_quality tests.test_fixed_answer_assessment -v`
  Expected: PASS for canonical and evidence-contract primitives; derivation/grading behavior remains pending in later tasks.

### Task 2: Add additive database storage and effect idempotency

**Files:**
- Modify: `learning_system/db.py`
- Test: `tests/test_answer_assessment_v51.py`
- Test: `tests/test_question_bank_runtime_authority.py`

- [ ] **Step 1: Write schema tests.**
  Verify a fresh database and an existing database both expose question quality columns: `discovery_depth`, `execution_steps`, `key_insight`, `graph_mode`, `evidence_profile_json`, `review_packet_sha256`, `node_contract_sha256`, `prompt_sha256`, `interaction_schema_sha256`, `discovery_derivation_sha256`, `structural_derivation_digest_sha256`, `exact_instance_fingerprint`, `family_fingerprint`, `fingerprint_policy_version`, `quality_receipt_json`, and `quality_receipt_sha256`. Verify `flow_steps` and `background_jobs` persist immutable `question_bank_version` plus `contract_digest_sha256` and source flow/step identifiers. Verify `fixed_assessment_effects` has a unique effect key and stores result/profile/ceiling.

- [ ] **Step 2: Run schema tests and verify failure.**
  Run: `python3 -m unittest tests.test_answer_assessment_v51.AnswerAssessmentSchemaTests tests.test_question_bank_runtime_authority -v`
  Expected: FAIL on missing columns/table/indexes.

- [ ] **Step 3: Implement additive migrations.**
  Use the existing `_ensure_column` and `conn.executescript` migration style. Add the listed quality receipt columns to `question_items` (the complete canonical receipt is stored in `quality_receipt_json` and verified by `quality_receipt_sha256`); add `fixed_assessment_effects` with unique `effect_key`; add receipt/profile fields to the relevant answer-contract tables; add `contract_digest_sha256` to `background_jobs` and ensure `flow_steps` retains its existing digest column; add indexed exact/family fingerprint staging fields. Do not backfill guessed metadata onto old question rows.

- [ ] **Step 4: Add guarded effect helpers.**
  Implement insert-or-reuse by `fixed_assessment:{attempt_id}:{attempt_version}:{contract_digest}`. Same key and same digest returns the committed result; same key with another digest raises a conflict without a second mastery transition.

- [ ] **Step 5: Verify fresh and migrated databases.**
  Run: `python3 -m unittest tests.test_answer_assessment_v51.AnswerAssessmentSchemaTests tests.test_question_bank_runtime_authority -v`
  Expected: PASS with no changes to the historical bank or existing unrelated rows.

## Chunk 2: Question Quality and Generation

### Task 3: Implement reviewer-derived discovery and fingerprints

**Files:**
- Modify: `learning_system/question_quality.py`
- Modify: `learning_system/question_fingerprints.py`
- Test: `tests/test_question_quality.py`
- Fixture: `tests/fixtures/question_quality_review_packets.json`

- [ ] **Step 1: Add failing `review_packet.v1` tests.**
  Cover the complete packet envelope, token-span bounds, instance/structural span hash consistency, acyclic step inputs, graph-declared cross-node relations, `input_evidence_keys`, reviewer-packet digest binding, and rejection of generator-only dependency/route claims.

- [ ] **Step 2: Add failing E0-E4 derivation tests.**
  Assert direct `2^4`, `-8 + 3`, `-7 ○ -3`, and isolated `4 + 6` derive E0/low-information. Assert explicit model plus an unresolved sign-scope or representation decision derives E2. Assert dependent decisions, genuine route choice, or a used prerequisite edge derive E3. Assert exploratory construction/counterexample/invariant derives E4. Assert execution bounds are enforced but cannot raise discovery depth.

- [ ] **Step 3: Implement `review_packet.v1` and `discovery_derivation.v1`.**
  The generator proposal remains untrusted. Build authoritative decisions/families only from the independent review packet and immutable graph contract. Recompute `depends_on`, verify step/span references, require graph relation and target-step evidence agreement, and reject a candidate when the proposed level differs from the derived level.

- [ ] **Step 4: Implement `question_fingerprint.v2`.**
  Produce `exact_instance_fingerprint` that retains concrete values and a `family_fingerprint` that replaces typed instance values while retaining structural interaction schema, structural span hashes, decision taxonomy, solution actions, and evidence keys. Keep semantic array ordering rules explicit and compute `sha256(UTF-8(canonical_json(payload)))`.

- [ ] **Step 5: Add adversarial fingerprint tests.**
  Reject exact duplicates; treat changed numbers and surface stories as the same family; treat changed mathematical grammar, evidence pattern, misconception mapping, or decision structure as a new family. Assert a family appears at most twice per node only when the second item has distinct evidence and misconception mappings.

- [ ] **Step 6: Run the quality test suite.**
  Run: `python3 -m unittest tests.test_question_quality -v`
  Expected: PASS with deterministic receipts and no model dependency.

### Task 4: Replace fixed-count generation with quality-gated production

**Files:**
- Modify: `learning_system/question_generation_service.py`
- Modify: `learning_system/question_bank.py`
- Modify: `learning_system/question_fingerprints.py`
- Test: `tests/test_question_generation_service.py`
- Test: `tests/test_question_quality.py`

- [ ] **Step 1: Write failing generation tests.**
  Assert batch specs carry graph mode, evidence profile, review-packet inputs, and quality purpose. Assert E0 candidates, disconnected arithmetic fragments, false E2 self-declarations, unknown decision taxonomies, and node-evidence mismatches are rejected before ingestion. Assert a node may finish below the old 15/20 quota with an explicit coverage report. Add a concurrent staging test where two transactions attempt the same node family quota and exactly one succeeds.

- [ ] **Step 2: Run the existing generation tests to capture compatibility failures.**
  Run: `python3 -m unittest tests.test_question_generation_service -v`
  Expected: existing fixed-matrix assertions identify the exact compatibility surface that must be migrated; no old bank data is rewritten.

- [ ] **Step 3: Implement quality-aware batch construction.**
  Keep teaching examples available, but remove E0 from active scheduling. Generate E1 only for an explicit foundation signal; require at least two distinct E2 evidence patterns when the node contract calls for them; enforce per-node exact/family fingerprints atomically in staging; and return a structured `no_eligible_candidate` result instead of padding or lowering the level.

- [ ] **Step 4: Implement independent review receipt binding.**
  Store the derivation digest, both fingerprints, evidence-profile digest, reviewer run id, and graph/node contract digest. Activation rejects any candidate whose receipt does not match the immutable prompt, interaction schema, review packet, and node contract.

- [ ] **Step 5: Migrate tests from quantity to coverage.**
  Replace assertions on `QUESTIONS_PER_GRAPH_NODE` and easy/medium/hard distribution with E1/E2 evidence coverage, family quotas, no-E0 active rows, and “fewer items is valid when quality replacement is unavailable.” Retain compatibility tests for historical read paths only.

- [ ] **Step 6: Run focused generation and authority tests.**
  Run: `python3 -m unittest tests.test_question_generation_service tests.test_question_quality tests.test_question_bank_runtime_authority -v`
  Expected: PASS with legacy bank rows readable and new candidates quality-gated.

### Task 4b: Run independent question-quality review

**Files:**
- Create: `scripts/review_question_quality.py`
- Modify: `learning_system/question_generation_service.py`
- Modify: `learning_system/model_router.py` only where the existing reviewer route needs a versioned quality-review route
- Test: `tests/test_question_quality.py`
- Test: `tests/test_question_generation_service.py`

- [ ] **Step 1: Write the runner contract test.**
  Given a staged bank and graph snapshot, assert the runner builds one bounded review packet per candidate, calls the existing `question_reviewer_agent` route with trusted graph/contract context and untrusted candidate data, records a distinct reviewer run id, persists the packet/receipt digests, and fails closed on malformed or missing reviewer output.

- [ ] **Step 2: Implement the deterministic runner shell.**
  Add CLI arguments `--db`, `--bank-version`, `--graph`, `--output`, and `--recorded-review-fixture`. Build `review_packet.v1`, call the existing structured reviewer adapter when live review is enabled, support recorded fixtures for tests, and write only approved receipts to the staged manifest. The runner must never mark a candidate approved from its generator self-declaration.

- [ ] **Step 3: Run the runner tests.**
  Run: `python3 -m unittest tests.test_question_quality tests.test_question_generation_service -v`
  Expected: PASS for recorded review packets, independent reviewer lineage, digest persistence, and rejection of missing/invalid receipts.

## Chunk 3: Deterministic Answers and Child Card

### Task 5: Implement closed choice and fill-in assessment

**Files:**
- Modify: `learning_system/fixed_answer_assessment.py`
- Modify: `learning_system/answer_contract_generation_v2.py`
- Modify: `learning_system/answer_contract_activation.py`
- Test: `tests/test_fixed_answer_assessment.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing response-envelope tests.**
  Cover single-choice, multi-choice, and fill-in payloads; reject unknown keys, duplicate JSON keys, nulls, wrong envelope types, mode-incompatible fields, duplicate choices/field ids, more than 8 fields/choices, values over 128 Unicode characters, and payloads over 16 KiB. Server-side expected answers and scores must override client claims. Add a retry with the same client idempotency key but a different input digest and assert `blocked` plus a conflict record.

- [ ] **Step 2: Implement duplicate-key parser and closed envelope validation.**
  Parse JSON with an object-pairs hook that rejects duplicate keys. Enforce the versioned envelope and authoritative interaction schema before grading. Return `invalid_input`, `incomplete`, `wrong`, or `correct` with field-level details and no mastery write for malformed data.

- [ ] **Step 3: Write failing equivalence tests.**
  Cover exact rational numeric parsing, fraction equivalence, per-field decimal policy, Unicode signs/whitespace, restricted algebraic grammar, precedence, one leading unary sign, non-negative integer powers, undeclared variables, implicit multiplication, functions, assignments, division by zero, exponent overflow, and text normalization/unit policy.

- [ ] **Step 4: Implement deterministic field graders.**
  Keep numeric parsing exact; reject malformed/domain-invalid expressions rather than guessing. Aggregate fields by the specified precedence: invalid input, incomplete required fields, required mismatch, then correct; optional-field penalties apply only when the contract explicitly enables them.

- [ ] **Step 5: Add contract-generation routing tests.**
  Assert fixed-answer contracts contain interaction schema, expected answer rules, evidence profile, and deterministic assessment version. Assert choice/fill submissions never enqueue `answer_analysis`; assert `short_text` still uses the existing model contract and evidence gates.

- [ ] **Step 6: Run the deterministic assessment suite.**
  Run: `python3 -m unittest tests.test_fixed_answer_assessment tests.test_answer_assessment_v51 -v`
  Expected: PASS, including legacy short-answer tests.

### Task 6: Add field-level mastery evidence and reducer ceiling

**Files:**
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/db.py`
- Modify: `learning_system/question_usage.py`
- Test: `tests/test_fixed_answer_assessment.py`
- Test: `tests/test_answer_assessment_v51.py`

- [ ] **Step 1: Write failing reducer tests.**
  Assert a correct single choice/single-answer fill-in writes evidence with `observation_only` and does not change `learner_node_status`. Assert a permitted multi-field fill-in can request `confirmation_eligible` only when every required field maps to a distinct graph evidence key and all required fields are correct. Assert process-required nodes cannot reach A from fixed evidence.

- [ ] **Step 2: Implement effective-profile derivation.**
  Intersect question `supports` with the normalized graph evidence catalog; reject unknown keys, conflicting ceilings, or a question-declared ceiling above the graph ceiling. Derive `D < C < B < A` clamping in one reducer transaction.

- [ ] **Step 3: Implement idempotent reducer effect application.**
  Use `fixed_assessment:{attempt_id}:{attempt_version}:{contract_digest}` as the effect key. Replays return the original result and do not append a second mastery decision; conflicting input digests create an auditable blocked/conflict record.

- [ ] **Step 4: Run reducer and regression tests.**
  Run: `python3 -m unittest tests.test_fixed_answer_assessment tests.test_answer_assessment_v51 tests.test_local_learning_child_answer_contract -v`
  Expected: PASS with no regression to short-answer process evidence.

### Task 7: Render and submit fill-in cards

**Files:**
- Modify: `learning_system/child_prompt.py`
- Modify: `learning_system/daily_runtime.py`
- Modify: `tests/browser_interaction_schema_v1.mjs`
- Modify: `tests/browser_smoke_learning_system.mjs`
- Modify: `tests/test_local_learning_child_answer_contract.py`

- [ ] **Step 1: Write failing child projection tests.**
  Assert a fill-in card exposes only stable field ids, child-safe labels, prefix/suffix text, math rendering data, required/optional state, and empty/invalid/submitted states. Assert internal answer rules, expected answers, evidence keys, and reviewer metadata never reach the child payload.

- [ ] **Step 2: Implement child-safe fill-in projection.**
  Extend `normalize_interaction_schema`, `_interaction_rendering`, `project_child_surface`, and runtime response parsing without changing existing choice/short-text behavior. Preserve stable dimensions for one or multiple blanks and field-level error mapping.

- [ ] **Step 3: Add browser interactions.**
  Submit a valid multi-field payload, a missing required field, an unknown field, and a malformed value. Assert the UI displays the correct state and the network/runtime path returns deterministic grading without a model job.

- [ ] **Step 4: Run browser and child-contract checks.**
  Run: `python3 -m unittest tests.test_local_learning_child_answer_contract -v`
  Run: `node tests/browser_interaction_schema_v1.mjs`
  Run: `node tests/browser_smoke_learning_system.mjs`
  Expected: PASS with existing child-safe assertions intact.

## Chunk 4: Scheduling, Cutover, and New Bank

### Task 8: Enforce quality-aware planner selection

**Files:**
- Modify: `learning_system/planner.py`
- Modify: `learning_system/question_usage.py`
- Test: `tests/test_planner_retest_scheduling.py`
- Test: `tests/test_planner_trace_back_integration.py`
- Test: `tests/test_question_quality.py`

- [ ] **Step 1: Write failing scheduling tests.**
  Assert E1 requires `foundation_check`; normal active minimum is E2; `core` never schedules E3; `selective_core` requires non-empty intersection with `selective_core_evidence_keys`; E3 requires transfer/prerequisite-coordination action; E4 requires controlled-extension action and never fills a daily minimum; diagnose-only receipts are never mastery-eligible.

- [ ] **Step 2: Implement candidate predicates and no-candidate decision.**
  Add a single predicate function used by planner and activation tests. When no candidate matches, materialize `no_eligible_candidate` with a graph-bound recovery or blocked/summary step; never downgrade to E0, exceed extension quota, or fabricate a candidate.

- [ ] **Step 3: Run planner tests.**
  Run: `python3 -m unittest tests.test_planner_retest_scheduling tests.test_planner_trace_back_integration tests.test_question_quality -v`
  Expected: PASS with existing prerequisite trace-back behavior preserved.

### Task 9: Complete versioned cutover and recovery fencing

**Files:**
- Modify: `learning_system/db.py`
- Modify: `learning_system/answer_contract_activation.py`
- Modify: `learning_system/daily_runtime.py`
- Modify: `tests/test_question_bank_runtime_authority.py`
- Modify: `tests/test_three_node_pilot_activation.py`

- [ ] **Step 1: Write failing cutover tests.**
  Cover `staged -> active -> superseded`, `active -> rolled_back` restoring the recorded predecessor, immediate-transaction rechecks, open-flow/job pins, stale submissions, unknown contracts, duplicate fixed assessments, and post-rollback flow behavior: already-pinned new-version steps may finish, subsequent step creation is blocked, and the flow materializes an auditable blocked/summary state. Assert `flow_steps` and `background_jobs` retain their contract digest and source lineage.

- [ ] **Step 2: Implement ledger transaction checks.**
  Recheck active uniqueness, manifest digest, node/item counts, open-flow pins, queued-job pins, active jobs, and contract-digest presence inside one SQLite `BEGIN IMMEDIATE` transaction. New flows use the new version only after the ledger changes. After rollback, allow already-pinned steps to finish but reject creation of a later new-version step and persist a blocked/summary transition.

- [ ] **Step 3: Implement lease owner/generation fencing.**
  Require `(lease_owner, claim_generation)` in guarded completion/retry writes. Expired claims return to retryable exactly once; an old worker cannot complete a newer claim. Validate bank/contract pins before every write.

- [ ] **Step 4: Run cutover and full authority tests.**
  Run: `python3 -m unittest tests.test_question_bank_runtime_authority tests.test_three_node_pilot_activation -v`
  Expected: PASS, with unrelated dirty-worktree files untouched.

### Task 10: Generate, audit, and activate the new math bank

**Files:**
- Modify: `scripts/generate_semester_bank.py`
- Create: `scripts/activate_semester_bank_v2.py`
- Create: `data/question_banks/math/semester_bank_v2.manifest.json` during staged generation
- Create: `tests/test_semester_bank_v2_activation.py`
- Test: `tests/test_question_bank_runtime_authority.py`
- Test: `tests/test_three_node_pilot_activation.py`

- [ ] **Step 1: Add a dry-run manifest test.**
  Assert the new version has a distinct version id, graph lineage, contract digests, quality receipts, exact/family fingerprints, no active E0 items, and no fixed 15/20-item padding requirement. Assert the old `2026-08-20.v1` file is not modified.

- [ ] **Step 2: Implement staged generation.**
  Generate into `data/question_banks/math/semester_bank_v2.sqlite` with bank version `2026-08-25.math-quality.v2` by running `python3 scripts/generate_semester_bank.py --db data/question_banks/math/semester_bank_v2.sqlite --all --review --report data/question_banks/math/semester_bank_v2.build.json`; the revised generator must write that version into each staged row. Run deterministic answer audits, then invoke `python3 scripts/review_question_quality.py --db data/question_banks/math/semester_bank_v2.sqlite --bank-version 2026-08-25.math-quality.v2 --graph data/knowledge_graphs/math/math_knowledge_graph_v2.json --output data/question_banks/math/semester_bank_v2.manifest.json`. Stop before activation when any node lacks required E1/E2 evidence or any family quota/routing/contract check fails.

- [ ] **Step 3: Add isolated activation and rollback commands.**
  Implement `scripts/activate_semester_bank_v2.py` with explicit `--db`, `--bank data/question_banks/math/semester_bank_v2.sqlite`, and `--manifest data/question_banks/math/semester_bank_v2.manifest.json` arguments. Require staged manifest digest and active-ledger preconditions. Keep historical rows readable, pin open flows, and record activation/rollback receipts.

- [ ] **Step 4: Run the complete verification matrix.**
  Run: `python3 -m unittest tests.test_semester_bank_v2_activation -v`
  Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`
  Run: `node tests/browser_interaction_schema_v1.mjs`
  Run: `node tests/browser_smoke_learning_system.mjs`
  Run: `python3 scripts/audit_question_bank_answers.py --db data/question_banks/math/semester_bank_v2.sqlite`
  Expected: all relevant tests pass; the staged manifest is activation-ready; no historical bank or unrelated worktree change is included.

## Implementation Rules

- Work in the task order above. Do not generate or activate a replacement bank before deterministic contracts and isolated tests pass.
- Commit each completed task or coherent pair of tasks with focused messages; never stage unrelated existing changes.
- Keep fixed-answer grading entirely local and deterministic. A model call is allowed only for short-answer/process analysis or independent question review, never for choice/fill correctness.
- Preserve old question lineage. Historical contracts may be read, but guessed discovery/evidence metadata must not be backfilled onto old active rows.
- Treat fewer high-quality active items as valid. Do not add padding items to satisfy the old per-node count.
- Add a concurrent staging test where two transactions attempt to consume the same node family quota; exactly one may succeed. Add an idempotency test where the same client key is retried with a different input digest; the result must be `blocked` with a conflict record and no second reducer effect.
- Run `git diff --check` before every commit and inspect `git diff --cached --stat` to confirm the staged file set.
