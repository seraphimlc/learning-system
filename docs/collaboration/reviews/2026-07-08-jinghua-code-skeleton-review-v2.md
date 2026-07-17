### CODE_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-08 11:56 CST

Verdict:
`CODE_REVIEW_NEEDS_FIX`. The v2 code skeleton exposes many required seams and passes the checked compile/targeted tests, but it is not ready for business-logic implementation because the shared v2 evidence gate is not wired through all critical consumers. This is a P1 architecture readiness issue under `docs/project-rules/system-architecture-learning-addendum.md`: session close/evaluation and self-evolution can still reason from evidence that is only "current-version + structurally analyzed", rather than the stricter `active + graded + valid answer_analysis + current reviewer-approved active question` predicate.

independence_required:
Yes. This review was performed independently in a fresh 镜花 context after 听云 `SKELETON_PASS`; I did not participate in implementation and did not edit production code.

context_mode:
fresh

context_origin:
independent review context spawned after 听云 DONE_CLAIMED / `SKELETON_PASS`

diff_pin:
no git diff available; reviewed current files listed in `docs/architecture/code_skeleton_pass_v2.md` plus source artifacts.

Scope:
Code skeleton/design review only. Checked child/operator boundary, state machine, async/background recovery, model adapter compatibility, evidence predicates, API contracts, test hooks, and fidelity to PRD/technical plan/project skeleton. Did not run external model calls, reset DB/uploads, or produce QA PASS.

Project boundary overlay:
Applied `AGENTS.md` and `docs/product/ai_native_math_learning_prd_v2.md`: one child Web端 only; parent via Codex; child flow without parent intervention; 10-task round; child-safe DTOs; AI analysis reasoning-aware; photo OCR untrusted; only active+graded+valid answer_analysis+current active reviewer-approved question evidence feeds evaluation/planning/evolution; model providers only via `model_router`.

Source artifacts:
`AGENTS.md`; `docs/collaboration.md`; `docs/collaboration/agent-registry.json`; `docs/collaboration/roles/jinghua.md`; `docs/project-rules/system-architecture-learning-addendum.md`; `docs/collaboration/playbooks/artifact-contracts.md`; `docs/product/ai_native_math_learning_prd_v2.md`; `docs/product/child_ux_flow_spec_v2.md`; `docs/architecture/data_contract_spec_v2.md`; `docs/architecture/technical_plan_v2.md`; `docs/architecture/project_skeleton_v2.md`; `docs/architecture/code_skeleton_pass_v2.md`; `docs/qa/test_case_spec_v2.md`; `docs/00_PROJECT_BLUEPRINT.md`; `docs/system/local_learning_system.md`; current code in `learning_system/`, `app/local_learning_system/`, and `tests/`.

Evidence:
- Identity YAML validated against `docs/collaboration/agent-registry.json`: `IDENTITY_YAML_VALID jinghua`.
- `python3 -m compileall learning_system` passed.
- `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe tests.test_learning_system.LearningSystemTest.test_child_submission_background_review_recovers_after_server_restart -v` passed: 2 tests.
- Code-path proof: child routes call `ChildAPIProjection` in `learning_system/server.py`; browser shell exposes `ChildLearningShell`; planner uses `db.is_child_schedulable_question` for plan candidates; model calls are routed through `learning_system/model_router.py`; background jobs have DB-backed queued/running/waiting/error/succeeded state and restart recovery tests.

Implementation fidelity:
- Satisfied with scope: child/operator projection shells exist; child API uses handle/position for normal child submission/complete; child DTO tests scan forbidden internals; child UI state enum/fixtures exist; model route status is secret-free; question-spec loader is disabled with Python gate authoritative; background recovery is represented and tested.
- Not satisfied: the skeleton exposes `EvidenceUsePolicy` / `is_evolution_source_valid`, but high-risk consumers are still allowed to bypass the shared predicate. That makes the skeleton unsafe as a contract for business-logic fill.

Findings:

1. P1 - Session close/evaluation can consume analyzed evidence without the shared usable-evidence predicate.
   - file and line: `learning_system/db.py:2254-2277`, `learning_system/orchestrator.py:715-837`, `learning_system/flow_nodes.py:279-337`
   - trigger condition: a session contains an active graded attempt with structurally valid `answer_analysis_json`, but the question is no longer child-schedulable because its durable review record is missing/retired/inactive, or the session was created before a review-record/active-use change. `session_completion_summary()` classifies it as `analyzed` based only on `grading_status == "graded"` and `is_valid_answer_analysis()`, and `close_learning_session()` then builds answer/evaluation packages from those analyzed ids.
   - impact: evaluation/teaching/planning can proceed from evidence that fails the PRD/data-contract active-use gate. This violates the project boundary that only active+graded+valid-analysis+current active reviewer-approved question evidence feeds evaluation/planning/evolution.
   - required fix boundary: route session-close readiness through the same shared predicate. Either make `session_completion_summary()` distinguish `usable_attempt_ids` from `missing_or_unusable_evidence_attempt_ids`, or have `close_learning_session()` block before `build_answer_analysis_package()` / `build_mastery_evaluation_package()` unless every submitted graded attempt used for closure passes `db.EvidenceUsePolicy.is_usable_attempt()` / `db.is_current_usable_attempt_evidence()`. Also update `stale_active_question_ids()` / `assert_current_active_question_ids()` to use `is_child_schedulable_question()` where child sessions depend on active eligibility, not only `is_current_active_question()`.
   - validation expectation: add a test that removes or deactivates the `question_review_records` row for a current-version graph-generated/evolved question after an attempt is graded with valid analysis, then verifies child/operator session close returns `blocked` (or a named unusable-evidence status), records audit evidence, and does not run evaluation, evolution, next-plan generation, or child review-ready projection from that attempt.

2. P1 - Self-evolution exposes `is_evolution_source_valid` but does not use it in the actual candidate path.
   - file and line: `learning_system/evolution.py:40-41`, `learning_system/evolution.py:474-518`, `learning_system/db.py:2007-2035`
   - trigger condition: `run_evolution()` calls `_candidate_attempts()`, whose manual filter checks active/graded/non-empty-analysis/current-version-ish state and `_attempt_question_source_invalidated()`. It does not call `db.is_evolution_source_valid()` or `db.EvidenceUsePolicy.is_usable_attempt()`, so it can accept evidence attached to a graph-generated/evolved question that has current metadata but lacks a durable active eligible review record.
   - impact: self-evolution may update learner status/profile or create/review evolved questions from evidence that the shared v2 policy would reject. This is directly blocking under the architecture addendum: self-evolution must not revise profiles or create questions without real active graded analyzed evidence.
   - required fix boundary: make `_candidate_attempts()` filter candidates through `db.is_evolution_source_valid(conn, attempt)` as the final authority, and use the same predicate for session-scoped and maintenance evolution. Keep `missing_analysis_count` scoped to current child-schedulable question evidence so reports do not mix stale/rejected-lineage rows with active blockers.
   - validation expectation: add a test with a valid graded analyzed attempt whose question metadata appears current but whose `question_review_records.active_eligible` is absent or `0`; `db.is_evolution_source_valid()` must be false, `evolution.run_evolution()` must return `no_action` with an auditable reason, must not revise profiles, and must not create or schedule evolved questions.

Residual risk:
- Background worker skeleton is mostly a naming/idempotency shell over existing handler methods rather than a fully extracted worker class. Current tests cover restart recovery and job reuse, so this is not the blocking issue, but later implementation should either use `BackgroundReviewWorker` as the actual worker facade or keep tests tied to the handler methods explicitly.
- `report_claim_label()` is still a coarse report-label seam; later implementation must prove claim-by-claim labels rather than one summary-level label.
- Rendered UX/mobile/focus/taste and live GPT/Doubao semantic/OCR quality remain outside this code review and require 清秋/观止/user evidence.

Required next action:
听云 must fix the P1 evidence-gate wiring before non-trivial business logic implementation. After fixes, rerun compile plus targeted tests for session close, evolution source validity, child-safe bootstrap, and background recovery, then return a revised skeleton evidence note for 镜花 re-review. 观止 should not treat the current skeleton as test-spec-final until these actual symbol/consumer mappings are corrected.
