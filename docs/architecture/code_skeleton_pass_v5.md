### SKELETON_PASS - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Create the reviewable v5 program skeleton for the true-Agent durable DAG before business logic implementation.

Scope:
- v2 agent contracts/prompts for answer analysis, evaluation, planner next step, and teaching.
- v5 contract registry selection while preserving legacy v1 loaders.
- model envelope/adapter signatures that fail closed and do not call external models.
- queue constants/helpers for v5 job types, retry/backoff, waiting semantics, and terminal-aware idempotency lookup.
- runtime job dispatch shells for `answer_analysis`, `evaluation_update`, `planner_decision`, and `teaching_generation`.
- server v5 worker naming/error-recorder shell.
- v5 report lineage read-model signature.
- child UI canonical-state alias table shell.

Forbidden scope observed:
- No tests changed.
- No QA spec changed.
- No schema migration.
- No DB reset or external model call.
- No mastery/planner/teaching reducer business logic added.
- No hardcoded recorded outputs added.

Files changed:

| File | Skeleton change |
|---|---|
| `learning_system/agent_contracts/answer_review.v2.json` | v5 answer-analysis schema with provider/trust envelope expectations |
| `learning_system/agent_contracts/evaluation_decision.v2.json` | v5 evaluation recommendation schema; no direct mutation authority |
| `learning_system/agent_contracts/planner_next_step.v2.json` | v5 one-action planner schema; no legacy fixed-list contract |
| `learning_system/agent_contracts/teaching_step.v2.json` | v5 child-safe teaching package schema |
| `learning_system/prompts/answer_review.v2.md` | answer-analysis prompt with trusted/untrusted boundary |
| `learning_system/prompts/evaluation_decision.v2.md` | evaluation prompt with usable-evidence boundary |
| `learning_system/prompts/planner_next_step.v2.md` | planner prompt with bounded candidate packet and one next action |
| `learning_system/prompts/teaching_step.v2.md` | child-safe teaching prompt |
| `learning_system/internal_agents.py` | v5 contract selection helpers and planner role wording corrected for one next action |
| `learning_system/semantic_agents.py` | model envelope/request dataclasses and four fail-closed adapter signatures |
| `learning_system/job_queue.py` | v5 constants, retry/backoff helpers, terminal-aware idempotency lookup shell |
| `learning_system/daily_runtime.py` | v5 job dispatch shell and fail-closed handlers for evaluation/planner/teaching jobs |
| `learning_system/server.py` | v5 worker wrapper/error-recorder shell; startup scan excludes waiting jobs |
| `learning_system/reports.py` | read-only v5 stage lineage summary signature |
| `app/local_learning_system/app.js` | canonical v5 child-state alias table shell |

Key symbols:
- `semantic_agents.SemanticAgentRequest`
- `semantic_agents.SemanticAgentEnvelope`
- `semantic_agents.call_answer_analysis_agent`
- `semantic_agents.call_evaluation_agent`
- `semantic_agents.call_planner_agent`
- `semantic_agents.call_teaching_agent`
- `internal_agents.load_v5_contract_for_agent`
- `job_queue.V5_MODEL_JOB_TYPES`
- `job_queue.JobQueue.terminal_stage_for_key`
- `job_queue.JobQueue.v5_retry_after_seconds`
- `DailyLearningRuntime._handle_v5_background_job`
- `DailyLearningRuntime._handle_evaluation_update_job`
- `DailyLearningRuntime._handle_planner_decision_job`
- `DailyLearningRuntime._handle_teaching_generation_job`
- `LearningHandler._start_v5_flow_processing`
- `LearningHandler._background_process_v5_flow`
- `LearningHandler._record_v5_flow_worker_error`
- `reports.v5_stage_lineage_summary`
- `V5_CANONICAL_CHILD_STATES`
- `V5_CHILD_STATE_ALIASES`

Unimplemented fail-closed stubs:
- `semantic_agents.call_*` functions return blocked envelopes.
- `DailyLearningRuntime._handle_evaluation_update_job` blocks safely and writes no mastery.
- `DailyLearningRuntime._handle_planner_decision_job` blocks safely and writes no next step.
- `DailyLearningRuntime._handle_teaching_generation_job` blocks safely and writes no teaching step.

Known deviations:
- Existing `answer_analysis` business path remains from the current first slice; this skeleton does not complete the DAG split.
- Existing legacy deterministic evaluation/planner helpers remain for compatibility and red-test context; they are not claimed as final v5 true-Agent behavior.
- No v5 schema migration was added; terminal-aware idempotency uses existing queue fields.

Validation commands used:

```bash
python3 -m json.tool learning_system/agent_contracts/answer_review.v2.json
python3 -m json.tool learning_system/agent_contracts/evaluation_decision.v2.json
python3 -m json.tool learning_system/agent_contracts/planner_next_step.v2.json
python3 -m json.tool learning_system/agent_contracts/teaching_step.v2.json
python3 -m py_compile learning_system/internal_agents.py learning_system/semantic_agents.py learning_system/job_queue.py learning_system/daily_runtime.py learning_system/server.py learning_system/reports.py
node --check app/local_learning_system/app.js
python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner tests.test_learning_system.LearningSystemTest.test_v5_mock_recorded_live_trust_labels_never_conflate tests.test_learning_system.LearningSystemTest.test_v5_evaluation_job_accepts_true_agent_envelope_and_enqueues_planner tests.test_learning_system.LearningSystemTest.test_v5_planner_job_uses_bounded_candidate_packet_and_rejects_legacy_10_task_plan tests.test_learning_system.LearningSystemTest.test_v5_teaching_generation_only_for_teaching_action_and_records_lineage tests.test_learning_system.LearningSystemTest.test_v5_malformed_agent_output_retries_then_blocks_without_mastery tests.test_learning_system.LearningSystemTest.test_v5_retry_lease_and_terminal_job_reuse_are_exactly_once tests.test_learning_system.LearningSystemTest.test_v5_waiting_jobs_are_child_wait_only_not_generic_worker_runnable tests.test_learning_system.LearningSystemTest.test_v5_wrong_blocking_grade7_evidence_prefers_prerequisite_probe_before_blind_drill tests.test_learning_system.LearningSystemTest.test_v5_summary_report_phase_lineage_includes_mastery_agent_and_job_refs -v
```

SKELETON_READINESS_GATE:
- verdict: SKELETON_READY_FOR_REVIEW
- v2_contracts_present: yes
- v2_prompts_present: yes
- v5_registry_selects_v2: yes
- model_adapter_signatures_present: yes
- runtime_dispatch_shell_present: yes
- queue_v5_helper_shell_present: yes
- worker_shell_present: yes
- report_read_model_shell_present: yes
- child_state_alias_shell_present: yes
- business_logic_filled: no
- external_model_called: no
- tests_modified: no
- blocking_gaps: none for 镜花 skeleton review

Next owner/action:
镜花 skeleton review. Business logic remains forbidden until review passes.

### SKELETON_PASS_REPAIR - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Repair 镜花 P1 finding: v5 child-bootstrap and startup worker wakeup scans must recover all v5 model jobs, not only `answer_analysis`.

Files changed:

| File | Repair change |
|---|---|
| `learning_system/server.py` | Child-bootstrap due-job scan and startup recovery scan now use `job_queue.V5_MODEL_JOB_TYPES`; they wake due `queued`/`retry` jobs and expired `claimed`/`running` leases only. `waiting` and terminal statuses remain non-runnable. |
| `learning_system/job_queue.py` | Added P2 guard comment: retrying a terminal v5 stage with the same idempotency key reuses the terminal row; explicit retry/reconcile must use a new source-phase key or reconciler path. |
| `docs/architecture/code_skeleton_pass_v5.md` | Added this repair evidence. |

Contract notes:
- Legacy session-level background review remains scoped to `answer_analysis`.
- v5 daily-flow recovery now covers `answer_analysis`, `evaluation_update`, `planner_decision`, and `teaching_generation`.
- This repair does not implement business handlers, retry UI, schema migration, prompts, contracts, or tests.

Validation commands:

```bash
python3 -m py_compile learning_system/server.py learning_system/job_queue.py
python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v5_child_bootstrap_wakes_due_retry_job tests.test_learning_system.LearningSystemTest.test_v5_waiting_jobs_are_child_wait_only_not_generic_worker_runnable -v
python3 - <<'PY'
from pathlib import Path
src = Path("learning_system/server.py").read_text()
for token in ("job_queue.V5_MODEL_JOB_TYPES", "status = 'queued'", "status = 'retry'", "lease_expires_at <= ?", "status in ('claimed','running')"):
    assert token in src, token
assert "status = 'waiting'" not in src[src.index("def _child_bootstrap_response"):src.index("def _start_background_session_processing")]
assert "status = 'waiting'" not in src[src.index("def _start_existing_background_work"):src.index("def _start_v3_flow_processing")]
print("server wakeup scans use V5_MODEL_JOB_TYPES and exclude waiting")
PY
```

Validation results observed:
- `py_compile`: pass.
- Repair-focused unittest: pass, 2 tests OK.
- Static scan: pass; `V5_MODEL_JOB_TYPES=answer_analysis,evaluation_update,planner_decision,teaching_generation`, bootstrap/startup scans use v5 type set, due retry, expired claimed/running, and exclude `waiting`.
- Full ten focused skeleton tests from this file: 2 pass (`terminal_job_reuse`, `waiting_jobs`), 8 remain expected red because business DAG handlers/reducers/reports are not implemented; no syntax/import/AttributeError regression from this repair.
- `git diff/status`: not available because this filesystem snapshot has no `.git` repository.

SKELETON_READINESS_GATE_REPAIR:
- verdict: SKELETON_READY_FOR_REVIEW
- p1_worker_wakeup_repaired: yes
- all_v5_model_job_types_scanned: yes
- waiting_non_runnable_preserved: yes
- terminal_same_key_retry_guarded: yes
- business_logic_filled: no
- tests_modified: no

Next owner/action:
镜花 rerun skeleton review for the P1 repair. Business implementation remains stopped.

### IMPLEMENTATION_EVIDENCE - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Implement the v5 durable Agent DAG and MSG-20260711-003 child recovery/cannot-provide exits without reintroducing inline evaluation/planner/teaching in the answer job.

Files changed in this implementation slice:

| File | Implementation change |
|---|---|
| `learning_system/semantic_agents.py` | Added recorded/live-safe semantic envelope path, structured JSON adapter calls, and fail-closed provider modes for answer/evaluation/planner/teaching agents. |
| `learning_system/daily_runtime.py` | Split answer analysis from evaluation/planner/teaching durable stages; added evaluation/planner/teaching handlers, finite retry terminal block, explicit blocked recovery generation jobs, cannot-provide summary closeout, canonical start state, prerequisite rollback before blind drill, and summary phase lineage. |
| `learning_system/prompts/answer_review.v2.md` | Strengthened expert answer-analysis procedure, uncertainty policy, and forbidden behavior. |
| `learning_system/prompts/evaluation_decision.v2.md` | Added explicit concept/model/procedure/calculation/expression/transfer evaluation discipline. |
| `learning_system/prompts/planner_next_step.v2.md` | Added one-action bounded-packet planner procedure and no-10-task limits. |
| `learning_system/prompts/teaching_step.v2.md` | Added teaching mode distinctions and child-safe style requirements. |
| `app/local_learning_system/app.js` | Added v5 `start_resume` alias, clarify cannot-provide action, submit-response projection handling, and terminal summary UI behavior. |

Validation results observed:
- `python3 -m py_compile learning_system/semantic_agents.py learning_system/internal_agents.py learning_system/job_queue.py learning_system/daily_runtime.py learning_system/server.py learning_system/reports.py`: pass.
- `node --check app/local_learning_system/app.js`: pass.
- `python3 -m json.tool learning_system/agent_contracts/*.v2.json`: pass.
- `node tests/browser_smoke_learning_system.mjs`: pass.
- Required focused unittest set: 16/17 pass.
- Remaining focused failure: `test_v5_summary_report_phase_lineage_includes_mastery_agent_and_job_refs` still expects one `process_next_background_job()` call on an `answer_analysis` job to inline later evaluation/planner/summary stages. This contradicts the approved durable DAG and the specific red test `test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner`, which now passes. No production compatibility hack was added.

Implementation notes:
- `answer_analysis` now grades/records evidence and enqueues `evaluation_update` only when the deterministic evidence gate passes.
- `evaluation_update` records a true model-stage `evaluation_agent` run, applies mastery through runtime reducer only, then enqueues `planner_decision`.
- `planner_decision` records a true model-stage `planner_agent` run, enforces bounded candidate packet and one action, and materializes one next state or enqueues `teaching_generation`.
- `teaching_generation` records a true model-stage `teaching_agent` run and materializes child-safe teaching/worked/clarify steps.
- Blocked retry creates a new recovery generation/source-phase key referencing the terminal origin job; same terminal idempotency key still reuses the old result.
- Clarify cannot-provide records stuck evidence and exits to summary without mastery update or another clarify loop.

Next owner/action:
观止/若命 should correct the stale single-call summary-lineage test to drive the durable DAG through answer -> evaluation -> planner -> summary, then rerun QA. 镜花 should review recovery idempotency and child projection boundaries before broader implementation close.
