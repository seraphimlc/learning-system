### CODE_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-10 19:20 CST

Verdict:
CODE_REVIEW_NEEDS_FIX. The v3 skeleton is directionally aligned with `technical_plan_v3.md` and correctly stays in skeleton/fail-closed mode for the child review path, but two P1 defects break core skeleton safety: queue lease recovery can requeue a live claimed job before the lease expires, and the current-step child projection trusts prompt package text without a child-safe validation gate.

independence_required:
yes

context_mode:
fresh

context_origin:
spawned only for skeleton review; did not implement

diff_pin:
no git; file list in SKELETON_PASS

Scope:
Changed skeleton files only: `learning_system/db.py`, `learning_system/graph_runtime.py`, `learning_system/evidence_gate.py`, `learning_system/job_queue.py`, `learning_system/daily_runtime.py`, `learning_system/model_router.py`, `learning_system/question_bank.py`, `learning_system/server.py`, `app/local_learning_system/app.js`, `tests/test_learning_system.py`, `docs/architecture/code_skeleton_pass_v3.md`, and project/domain index updates.

Project boundary overlay:
Applied `AGENTS.md`, PRD v3, `docs/domain-index/math-learning.md`, `docs/architecture/daily_learning_runtime_contract_v1.md`, and `docs/architecture/technical_plan_v3.md`. Mandatory system architecture addendum was applied, with focus on state machine, additive schema, partial indexes, queue lease, child-safe route boundary, feature flag, and old v2 compatibility.

Source artifacts:
- `docs/collaboration.md`
- `docs/collaboration/roles/jinghua.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/collaboration/agent-registry.json`
- `AGENTS.md`
- `docs/product/ai_native_math_learning_prd_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `docs/architecture/technical_plan_v3.md`
- `docs/architecture/code_skeleton_pass_v3.md`
- listed code/test/index files

Inputs reviewed:
Role identity/header, registry entry, inbox, project/domain indexes, PRD v3, runtime contract, technical plan v3, skeleton pass v3, v3 runtime modules, child routes, UI branch, and focused skeleton tests.

Commands:
- Identity header validation: `identity header matches registry for jinghua`
- Static parse: `ast parse ok: 9 files`
- Focused unittest: four v3 skeleton tests passed.
- In-memory `JobQueue` lease probe: a 60-second claimed lease was recovered after 30 seconds and returned to `queued`.
- In-memory current-step projection probe: a displayed step with prompt text containing `graph_version`, `model provider`, and `question_id` was returned in the child `current_step` payload.

Evidence:
- Focused command passed:
  `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v3_skeleton_schema_additive_and_indexes_exist tests.test_learning_system.LearningSystemTest.test_v3_skeleton_modules_expose_fail_closed_contracts tests.test_learning_system.LearningSystemTest.test_v3_child_route_shell_returns_child_safe_payload_when_enabled tests.test_learning_system.LearningSystemTest.test_v3_feature_flag_disabled_keeps_legacy_child_bootstrap -v`
- Lease probe output:
  `{'claimed': 1, 'lease_expires_at': '2026-07-10T12:00:00+00:00+60s', 'recover_30s': {'expired_leases_retried': 1, 'due_retries_requeued': 1, 'missing_attempt_jobs_created': 0}, 'status_after_30s': 'queued'}`
- Projection probe output:
  `current_step {'step_handle': 'step-safe', 'position': 1, 'kind_label': '小检测', 'topic_label': 'graph_version should not show', 'prompt': 'Use model provider and question_id Q-internal', ...}`

Implementation fidelity:
The skeleton preserves legacy v2 child bootstrap behind `V3_DAILY_RUNTIME_ENABLED=0`, adds additive v3 schema/tables/index names, creates deterministic graph/runtime/gate/router seams, excludes missing-lineage v2 bank rows from candidate packets, and blocks start-review at the target-selection seam instead of faking a question. It does not yet satisfy the queue lease/recovery safety contract or the child-safe current-step projection contract.

Findings:
1. [P1] Queue lease timestamps are not real expiry times, so recovery can requeue a live job before its lease expires.
   File: `learning_system/job_queue.py`
   Lines: 116-147, 153-164, 195-219, 221-240
   Trigger: `JobQueue.claim(..., now='2026-07-10T12:00:00+00:00', lease_seconds=60)` stores `lease_expires_at='2026-07-10T12:00:00+00:00+60s'`; `recover('2026-07-10T12:00:30+00:00')` treats it as expired by lexical comparison.
   Impact: a claimed/running answer-analysis job can become `retry`/`queued` while the original worker still owns it, allowing duplicate claim/run/apply once business logic is filled. This violates the v3 queue lease, restart/retry, and “async review cannot double-grade” safety bar. The same module also returns success from owner/status transitions without checking `rowcount`, so wrong-owner or wrong-state transitions can look successful.
   Required fix: store actual ISO expiry timestamps using real datetime arithmetic, compare consistent timestamps, clear/update lease metadata on terminal transitions as needed, and make `start`/`heartbeat`/owner-guarded transitions report failure when no row changed.
   Validation: add tests proving no recovery before lease expiry, recovery after expiry, duplicate workers cannot claim the same active job, wrong owner cannot start/heartbeat, and active idempotency still returns the existing job.

2. [P1] Current-step child projection can leak internal graph/model/question text from `prompt_package_json`.
   File: `learning_system/daily_runtime.py`
   Lines: 340-353
   Related UI sink: `app/local_learning_system/app.js` lines 360-393
   Trigger: any `flow_steps` row with status `selected`, `displayed`, or `analyzing` and a prompt package containing internal terms or values is projected directly as `topic_label`, `prompt`, and `support.hint`.
   Impact: when the skeleton starts projecting real current steps, the child API can expose graph/version words, model/provider names, question ids, agent/rubric wording, or other operator internals. HTML escaping in the UI prevents markup injection but does not enforce the child-safe boundary required by PRD v3 and the runtime contract.
   Required fix: add a child-safe projection validator/whitelist before returning `current_step`; reject or block projection when package keys/text contain forbidden internals or missing child-safe fields, and record operator-visible evidence for the rejected step.
   Validation: add a focused test that inserts a visible v3 `flow_step` with forbidden prompt/package text and asserts `/api/child-bootstrap` returns a child-safe blocked payload with no leaked internals; add a positive test for a clean current-step package.

3. [P2] v3 `attempts.grading_status='blocked'` is in the contract but the shared attempt validator still rejects it.
   File: `learning_system/db.py`
   Lines: 239-267
   Trigger: PRD/technical plan allow `pending_review`, `graded`, and `blocked` for attempt grading status, and model route failure may leave an attempt pending/blocked. `_validate_attempt_values()` still accepts only `pending_review` and `graded`.
   Impact: the next slice cannot use existing DB helpers to represent model-not-configured/operator-attention attempt state without bypassing validation or overloading `pending_review`, which weakens report/evidence labels.
   Required fix: either extend the shared validator/helper to support the v3 `blocked` status with no mastery-usable score, or add a v3-specific helper that writes blocked attempts consistently with review metadata and evidence-gate semantics.
   Validation: add tests for blocked attempts being non-usable in `EvidenceUsePredicate`, visible as blocked/pending child-safe status, and never planner/mastery usable.

4. [P2] Focused v3 skeleton tests check several invariant names but do not exercise most invariant behavior.
   File: `tests/test_learning_system.py`
   Lines: 572-644, 648-695
   Trigger: `test_v3_skeleton_schema_additive_and_indexes_exist` verifies table/column/index names and duplicate active daily flow only. It does not try duplicate current steps, duplicate active attempts, duplicate submit idempotency, active background-job idempotency, evidence-validation version uniqueness, next-decision uniqueness, summary uniqueness, or queue lease transitions.
   Impact: the focused tests passed while the queue lease bug above was still present. That creates a false-pass risk for exactly the state-machine/partial-index/lease claims that v3 skeleton review is meant to protect.
   Required fix: add behavior-level duplicate-write and queue lifecycle tests for each required skeleton invariant, not only schema existence.
   Validation: tests must fail if an invariant/index is missing or non-enforcing, and must include the early-recovery lease probe from finding 1.

Not covered:
- No live model calls.
- No real DB/server run.
- No browser visual QA.
- No final business logic judgment for target building, answer analysis worker chain, evaluation, planner decisions, late evidence application, summaries, or new-knowledge teaching.
- No UX/DATA/QA gate substitution.

Residual risk:
The skeleton is still intentionally incomplete. After the P1 fixes, it should receive TEST_CASE_SPEC coverage before any business-chain fill. UX_FLOW_SPEC v3 and DATA_CONTRACT_SPEC v3 remain required before final release claims.

Required next action:
Fix the two P1s before treating this SKELETON_PASS as approved. Then rerun focused v3 tests plus new queue/projection invariant tests, and route 观止 to derive/expand TEST_CASE_SPEC from the corrected skeleton.
