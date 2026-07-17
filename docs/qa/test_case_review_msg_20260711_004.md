# TEST_CASE_REVIEW - MSG-20260711-004

- Role: 观止 (`guanzhi`)
- Date: 2026-07-11 CST
- Scope: v5 semantic collaboration, active-bank snapshots, and new-knowledge teaching DAG
- Runtime mode: temporary SQLite plus explicit `recorded_model` envelopes only
- Forbidden work respected: no production edits, real DB mutation, or live model calls

## Authorized Changes

- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `tests/fixtures/v5_msg004_recorded_contracts.json`

## Added Or Corrected Contracts

| Area | Test contract | Current red evidence |
|---|---|---|
| Answer route/provenance | `test_v5_answer_job_uses_semantic_agent_and_records_actual_prompt_schema_hashes` | Worker calls `auto_review._call_openai_evaluator` once and semantic answer Agent zero times; later assertions bind stored rendered-prompt and response-schema hashes to the captured call. |
| Prompt injection boundary | `test_v5_answer_worker_keeps_question_trusted_and_child_text_ocr_untrusted` | Worker bypasses the semantic trusted/untrusted request boundary. |
| Evaluation packet | `test_v5_evaluation_trusted_packet_contains_mastery_criteria_and_only_bounded_usable_varied_history` | `node_mastery_criteria` and bounded usable history are absent. |
| Mastery accumulation | `test_v5_evaluation_reducer_preserves_accumulated_stable_and_weak_state_from_one_narrow_success` | Existing A and C states are both overwritten to B by one narrow success. |
| Stable evidence | `test_v5_evaluation_reducer_advances_only_after_distinct_core_direct_and_near_transfer_evidence` | Three distinct-core direct/direct/near-transfer successes still end at B and do not retain accumulated ids. |
| Planner collaboration | `test_v5_planner_trusted_context_contains_evaluation_budget_pending_and_recent_steps` | Accepted evaluation, interaction budget, pending summary, and recent steps are absent from trusted context. |
| Early stop guard | `test_v5_planner_rejects_unjustified_early_summary_before_minimum` | Ordinary one-answer summary is accepted before `budget_min`. |
| Explicit safe stop | `test_v5_planner_allows_only_explicit_safe_stop_before_minimum` | `blocked_reason` is not retained in durable branch-policy evidence. |
| Maximum budget | `test_v5_planner_enforces_maximum_interaction_budget` | A next question is materialized after `budget_max`; runtime does not force deterministic summary. |
| Active bank ledger | `test_v5_active_bank_ledger_survives_restart_and_snapshots_activation_and_rollback` | Durable stage/activate/rollback/current-version APIs and ledger are absent. Deeper assertions cover restart cleanup, old/new flow snapshots, future-only rollback, and attempt/job lineage. |
| New knowledge start | `test_v5_ready_checkpoint_waits_for_accepted_teaching_agent_before_worked_example` | Start returns a synchronous deterministic worked example instead of teaching pending plus a durable teaching job. |
| New knowledge sequence | `test_v5_new_knowledge_sequence_is_example_micro_check_standard_variant_or_repair` | Stops at the same synchronous worked-example gap; downstream assertions require structured teaching, micro-check, standard, variant, and child-safe repair/stop. |
| Browser contract | `tests/browser_smoke_learning_system.mjs` | Honest pending renders, then smoke fails because structured essence/model/example DOM sections are absent. |

## Commands And Results

- `python3 -m py_compile tests/test_learning_system.py`: PASS.
- `node --check tests/browser_smoke_learning_system.mjs`: PASS.
- Focused 12-test MSG-004 suite: 12 tests ran, 15 expected assertion failures, 0 errors.
- Adjacent existing v5 regression suite: 5 tests ran, all PASS.
- `node tests/browser_smoke_learning_system.mjs`: expected RED at structured teaching-section assertion.

## Gate

TEST_CASE_REVIEW:

- source_artifacts_checked: `MSG-20260711-004`, v5 product/UX/engineering contracts, current runtime, semantic adapters, current tests
- stale_or_missing_cases: all seven requested groups were missing or materially shallow
- updates_made: focused red tests, explicit recorded contract fixture, browser pending/structured-teaching checks
- authorized_test_files_changed: yes
- ready_for_execution: yes, as an implementation red gate only
- QA_PASS: no
- live semantic claim: no

Stop condition: production work may begin against these red contracts; QA must rerun the focused suite, full v5 suite, browser smoke, and separately authorized live semantic/OCR gates before any PASS claim.

## Test Infrastructure Correction - 2026-07-11

- Corrected `tests/test_learning_system.py::_v5_msg004_teaching_output` to replace fixture placeholders recursively across JSON objects, arrays, and string values.
- The helper no longer substitutes unescaped question text into serialized JSON; quoted prompts remain structured string values.
- Product and semantic assertions were not removed, weakened, or changed.

Focused verification:

- `python3 -m py_compile tests/test_learning_system.py`: PASS.
- The two new-knowledge cases ran to completion with `0 errors`; the prior `JSONDecodeError` is closed.
- `test_v5_ready_checkpoint_waits_for_accepted_teaching_agent_before_worked_example`: RED at the unchanged v3-internal scan because canonical v5 field `core_model` contains the substring `model`.
- `test_v5_new_knowledge_sequence_is_example_micro_check_standard_variant_or_repair`: RED at the unchanged child-safe stop oracle because the terminal summary does not contain the required saved-evidence copy `保存`.
- Focused command verdict: `2 tests`, `2 failures`, `0 errors`; no production code was changed.

## Structured Child-Safe Oracle Correction - 2026-07-11

- Replaced the whole-payload substring scan in `tests/test_learning_system.py::_assert_no_v3_child_internals` with recursive JSON structure inspection.
- Exact internal keys remain forbidden, including graph/flow/step/attempt/question/session/node ids, `model`, `model_name`, `model_provider`, `provider`, `provider_mode`, `agent_key`, job/queue fields, OCR confidence, API/base URL fields, and response-schema metadata.
- Leaf values are still checked for provider/model modes, configured secrets and secret-shaped values, internal schema identifiers, Agent/provider/queue/job wording, and model/provider names.
- Public root `schema_version=3.0.0-daily-flow` remains allowed; nested or non-public schema versions fail.
- Product-contract key `teaching_sections.core_model` and pedagogical model wording are explicitly allowed.
- Added `test_v3_child_internal_oracle_allows_core_model_but_rejects_real_model_metadata`, with negative fixtures for nested `model_name`, nested `provider`, provider-mode text, secret text, and internal schema text.
- The new-knowledge terminal-summary assertion requiring `保存` was not changed.

Verification:

- `python3 -m py_compile tests/test_learning_system.py`: PASS.
- Six focused child-safe tests, including the new adversarial fixture: `6/6 PASS`.
- The first combined run imported `daily_runtime.py` during a concurrent production-file write and the two new-knowledge cases stopped on transient `NameError: _child_safe_teaching_sections`; the child-safe tests had already passed.
- Stable rerun after that production definition was present: both new-knowledge cases PASS (`2 tests in 3.360s`).
- The unchanged `summary` saved-evidence assertion executed and passed against the current production state.

## Focused Full-Suite Migration - 2026-07-12 00:30 CST

TEST_CASE_REVIEW:

- scope: three representative v5 full-suite tests only; no production, live network, or real DB work
- changed_files:
  - `tests/test_learning_system.py`
  - `docs/qa/test_case_review_msg_20260711_004.md`
- migrated_tests:
  - `test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner`
  - `test_v5_current_step_submit_starts_background_worker`
  - `test_v5_retryable_model_error_keeps_flow_pending_for_retry`
- migration:
  - success paths now patch `semantic_agents.call_answer_analysis_agent` with an `answer_review.v2` recorded envelope validated against the strict contract before acceptance
  - retry path now patches `model_router.call_structured_json` with a deterministic `HTTP 504` error
  - the server-worker summary fixture explicitly sets `budget_min=1`; the runtime early-summary guard remains exercised
  - unittest setup rejects any unmocked `urllib.request.urlopen` call immediately
- command: `python3 -m unittest -v tests.test_learning_system.LearningSystemTest.test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner tests.test_learning_system.LearningSystemTest.test_v5_current_step_submit_starts_background_worker tests.test_learning_system.LearningSystemTest.test_v5_retryable_model_error_keeps_flow_pending_for_retry`
- result: `Ran 3 tests in 5.031s - OK`
- false_pass_audit: target test bodies contain no `auto_review` patch; success cases patch the semantic boundary and the retry case patches the structured-model boundary
- live_http_result: no live HTTP attempt and no `401`
- cascade_result: no `KeyError` or missing downstream result-ref cascade
- production_fix_required_from_this_scope: none observed
- not_covered: the remaining 13 previously identified migration candidates and the full 292-test suite
