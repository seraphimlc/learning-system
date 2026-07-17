### IMPLEMENTATION_BLUEPRINT - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Provide the file/symbol-level implementation path for converting the current first-slice runtime into the v5 hybrid durable true-Agent pipeline defined by `technical_plan_v5.md` and `engineering_contract_v5.md`.

Complexity:
high_risk_change

Scope:
- Production implementation later across runtime, queue, server worker, model adapters, agent contracts/prompts, reports, UI, and tests.
- This dispatch only updates docs; no production/test code is edited now.

Non-goals:
No DB reset, no external model call during default tests, no parent Web UI, no active self-evolution, no new service/database, no fixed worksheet planner.

Authoritative implementation direction:
- Implement the durable DAG `answer_analysis -> evaluation_update -> planner_decision -> optional teaching_generation`.
- Keep `evidence_validation` deterministic and immediate after accepted answer analysis.
- Enqueue `planner_decision` only after an accepted `evaluation_agent` run and accepted runtime evaluation reducer output; terminal evaluation failure materializes child-safe blocked/summary directly and does not enqueue planner.
- Runtime alone writes mastery, flow state, next step, summary, and child projection.
- True model Agent calls must be independently retryable/auditable.
- Stage idempotency must be terminal-aware: the same v5 idempotency/source-phase key reuses valid `succeeded`, `blocked`, `dead_letter`, or non-runnable `waiting` outcomes instead of checking only active queue rows.
- Legacy v3/v10-task planner remains compatibility/history only.

Change map:

| Stage | File/path | Symbol/route | Required change | Validation |
|---|---|---|---|---|
| 0 red tests | `tests/test_learning_system.py` | new v5 DAG tests | Add failing tests for stage jobs, terminal-aware idempotency, trust labels, malformed outputs, graph rollback, UX P0 projections | focused unittest |
| 0 browser red tests | `tests/browser_smoke_learning_system.mjs` | v5 runtime scenarios | Add real runtime state coverage for analyzing, clarify cannot-provide, blocked retry, teaching, summary, forbidden leakage | node smoke |
| 1 agent contracts | `learning_system/agent_contracts/*.v2.json` | `answer_review`, `evaluation_decision`, `planner_next_step`, `teaching_step` | Add v5 schemas; planner schema returns one action, not 10 tasks | schema/static tests |
| 1 prompts | `learning_system/prompts/*.v2.md` | v5 prompt templates | Add v5 prompt copies with trusted/untrusted sections, child-safe constraints, bounded context | rg scan for no 10-task v5 |
| 1 registry | `learning_system/internal_agents.py` | `INTERNAL_AGENT_ROLES` | Point v5 runtime to v2 contracts; keep legacy contract readable but not hot-path | unit/static |
| 2 model adapters | `learning_system/auto_review.py`, new/extended adapter module if needed | answer/evaluation/planner/teaching call helpers | Wrap `model_router.call_structured_json`; return model envelope and parsed output; support recorded fixtures | model adapter tests |
| 3 queue | `learning_system/job_queue.py` | `V3_JOB_TYPES`, `enqueue`, `retry`, `recover`, helpers | Add v5 naming constants/aliases, max retry/backoff helper, dependency/status semantics, terminal-aware stage lookup; do not make `waiting` runnable | queue tests |
| 4 runtime DAG | `learning_system/daily_runtime.py` | `process_next_background_job` | Dispatch handlers by job type: answer/eval/planner/teaching; unsupported jobs block safely | DAG tests |
| 4 answer handler | `learning_system/daily_runtime.py` | `_handle_answer_analysis_job` | Only answer model + deterministic EvidenceGate; enqueue eval or clarify/block/summary | answer/evidence tests |
| 4 evaluation handler | `learning_system/daily_runtime.py` | new `_handle_evaluation_update_job` | Call true evaluation agent; validate; runtime applies mastery; enqueue planner only after accepted evaluation; terminal failure blocks/summarizes without planner | evaluation tests |
| 4 planner handler | `learning_system/daily_runtime.py` | new `_handle_planner_decision_job` | Build bounded candidate packet; call true planner; validate one action; enqueue teaching or materialize | planner tests |
| 4 teaching handler | `learning_system/daily_runtime.py` | new `_handle_teaching_generation_job` | Call true teaching agent; validate child-safe package; materialize teaching/worked/clarify/micro support | teaching tests |
| 4 reducers | `learning_system/daily_runtime.py` | `_record_evaluation_update`, `_advance_after_analysis`, `_record_next_step_decision`, `_create_teaching_repair_step` | Split model call from runtime reducer; deterministic reducers labeled `deterministic_runtime` | lineage tests |
| 5 candidate packet | `learning_system/question_bank.py`, `learning_system/graph_runtime.py` | `candidate_packet_for_node`, rollback helpers | Reuse packet cap 8; ensure v5 packet fields and no solution-bank leakage | packet tests |
| 6 server worker | `learning_system/server.py` | `_start_existing_background_work`, `_start_v3_flow_processing`, worker loop | Introduce v5 aliases/names, wake queued/retry only, record worker errors, no silent swallow | worker tests |
| 7 projection/UI | `learning_system/daily_runtime.py`, `app/local_learning_system/app.js`, `index.html`, `styles.css` | `project_child_state`, renderers | Emit canonical v5 states; implement real retry, bounded analyzing outcome, clarify cannot-provide, terminal summary | browser smoke |
| 8 reports | `learning_system/reports.py`, `scripts/generate_daily_report.py` | v5 report readers | Include job DAG lineage, trust labels, stale/mock/pending separation, worker errors | report tests |
| 9 harness | `tests/test_learning_system.py` or approved fixture file | v5 10-lesson harness | Simulate 10 consecutive lessons with recorded/patchable envelopes, no mock-as-live | harness test |
| 10 full validation | commands below | all | Run focused, full unittest, browser smoke, rg/static checks | evidence for DONE later |

SKELETON_PASS delta before business logic:

| Skeleton | File/path | Must exist before business logic |
|---|---|---|
| Job dispatch shell | `learning_system/daily_runtime.py` | handler stubs for `answer_analysis`, `evaluation_update`, `planner_decision`, `teaching_generation`; evidence gate helper remains deterministic |
| Model adapter shells | `learning_system/auto_review.py` or new local module | `call_answer_analysis_agent`, `call_evaluation_agent`, `call_planner_agent`, `call_teaching_agent` returning validated envelope shape |
| Prompt/schema shells | `learning_system/agent_contracts/*v2.json`, `learning_system/prompts/*v2.md` | v5 schemas/prompts with version ids and no 10-task planner |
| Queue shell | `learning_system/job_queue.py` | v5 constants/aliases, max-retry/backoff function, waiting semantics |
| Worker shell | `learning_system/server.py` | v5 worker naming/loop/error recorder, compatibility wrappers for old `_v3` names |
| Runtime reducers | `learning_system/daily_runtime.py` | reducer functions separated from model calls: apply evaluation, apply planner decision, materialize teaching/question/summary |
| Projection shell | `learning_system/daily_runtime.py`, `app/local_learning_system/app.js` | canonical state map and child-safe blocked/clarify/summary controls |
| Report shell | `learning_system/reports.py` | phase lineage/trust label read model |
| Test shell | `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs` | failing tests named below |

Red-test stage:
- `test_v5_submit_enqueues_answer_analysis_only`
- `test_v5_answer_analysis_success_records_evidence_gate_and_enqueues_evaluation`
- `test_v5_evaluation_agent_success_applies_mastery_and_enqueues_planner`
- `test_v5_terminal_evaluation_failure_blocks_or_summarizes_without_planner_job`
- `test_v5_planner_agent_receives_bounded_packet_and_selects_one_action`
- `test_v5_planner_rejects_legacy_10_task_output`
- `test_v5_teaching_generation_is_only_enqueued_for_teaching_actions`
- `test_v5_mock_recorded_live_trust_labels_never_conflate`
- `test_v5_malformed_agent_output_retries_then_blocks_without_mastery`
- `test_v5_retry_recovery_does_not_duplicate_stage_rows`
- `test_v5_terminal_stage_idempotency_reuses_succeeded_and_blocked_outputs`
- `test_v5_waiting_jobs_are_not_woken_without_reconciler`
- `test_v5_wrong_answer_rolls_back_to_prerequisite_before_blind_drill`
- `test_v5_child_projection_bounded_analyzing_blocked_retry_clarify_cannot_provide_summary`
- `test_v5_report_contains_phase_lineage_and_worker_errors`
- `test_v5_ten_lesson_harness_uses_recorded_not_live_labels`

Agent contracts/prompts v2:
- `learning_system/agent_contracts/answer_review.v2.json`: keep answer/process/evidence schema; add provider/trust envelope and stricter validation errors.
- `learning_system/agent_contracts/evaluation_decision.v2.json`: recommendation only; required source validation ids; no direct DB status mutation.
- `learning_system/agent_contracts/planner_next_step.v2.json`: one action, optional selected candidate id, target node, branch policy, pending/block reason, confidence; no `round_size`, no `tasks[]` length 10.
- `learning_system/agent_contracts/teaching_step.v2.json`: child-safe text/package, allowed response mode, micro-check support, source diagnosis, graph node id.
- Prompt v2 files must include trusted context, untrusted child/model data block, no internal leakage, no full bank, and output-only JSON.

Model invocation adapters:
- Use `model_router.answer_analysis_route`, `evaluation_route`, `planner_route`, `teaching_route`, `answer_photo_vision_route`.
- Centralize structured JSON call/result normalization so each job receives:
  - parsed output,
  - raw provider metadata hash,
  - prompt/schema version and sha256,
  - provider mode,
  - confidence,
  - retryability classification.
- Tests patch adapters at the envelope level, not runtime reducers, so trust labels remain realistic.

Queue handlers:
- `answer_analysis`: validates attempt still active/pending; calls answer adapter; writes validation; enqueues eval or materializes clarify/block.
- `evaluation_update`: validates evidence validation still passed; calls eval adapter; runtime applies/rejects mastery; enqueues planner only after accepted evaluation; terminal evaluation failure materializes blocked/summary without planner.
- `planner_decision`: builds candidate packet and compact summaries; calls planner adapter; validates one action; enqueues teaching or materializes.
- `teaching_generation`: validates planner decision still current; calls teaching adapter; materializes child-safe teaching/worked/clarify step.

Runtime materialization:
- Selected question: create one `flow_step` bound to selected candidate and `next_step_decision`.
- Teaching repair/worked example: create step with `answer_input_mode=none`, continue/stuck controls, then micro-check.
- Clarify evidence: allow text/photo/text+photo/stuck/cannot-provide; cannot-provide must not update mastery.
- Blocked: child-safe retry/finish when possible; operator-visible reason stored.
- Summary: terminal child action; labels confirmed/weak/pending/blocked/mock/stale/missing-lineage separately.

Server worker:
- Rename new code paths to v5 while leaving `_v3` wrappers if tests/routes still call them.
- Startup wakes due `queued`/`retry` v5 jobs only.
- Worker loop records exceptions in job and operator-readable audit; no silent `except: return`.
- Flow-scoped concurrency remains one in-process worker per flow.
- No child endpoint exposes job ids, provider names, or queue internals.

Reports/UI:
- Reports must read latest v5 `daily_flows`, jobs, agent runs, validations, decisions, summaries.
- UI must render canonical v5 states while tolerating legacy aliases during transition.
- Browser smoke must drive real API/runtime projections, with fixtures only for visual edge cases explicitly labeled.

v5 10-lesson harness:
- Purpose: acceptance-style runtime convergence check over 10 lessons, not a 10-question planner.
- Uses recorded/patchable model envelopes for answer/eval/planner/teaching.
- Verifies no mock/recorded fixture is labeled `live_model`.
- Exercises mixed correct, wrong-reason-right-answer, partial, stuck, low-confidence photo, malformed model output, retry recovery, prerequisite rollback, teaching, and summary.
- Produces local test evidence only; live semantic PASS requires explicit external-model authorization later.

Implementation order:
1. Add red tests and browser smoke expectations.
2. Add v5 agent contract/prompt/schema shells and registry routing.
3. Add model envelope adapters with recorded/mock/live trust labeling.
4. Harden queue retry/backoff/status semantics.
5. Add terminal-aware stage lookup/reuse for v5 idempotency/source-phase keys before active enqueue/claim behavior.
6. Split runtime job dispatch and implement answer handler with deterministic EvidenceGate.
7. Implement evaluation true-agent job and runtime mastery reducer, including no-planner terminal failure path.
8. Implement planner true-agent job, bounded packet builder usage, one-action validator.
9. Implement conditional teaching true-agent job and child-safe materializer.
10. Harden server v5 worker lifecycle/error recording.
11. Align projection/UI states and UX P0 controls.
12. Update reports and 10-lesson harness.
13. Run validation and stop for review/QA gates before DONE.

Validation commands:

```bash
python3 - <<'PY'
from pathlib import Path
for path in [
    "docs/architecture/technical_plan_v5.md",
    "docs/architecture/engineering_contract_v5.md",
    "docs/architecture/implementation_blueprint_v5.md",
]:
    text = Path(path).read_text()
    assert "TECHNICAL_PLAN" in text or "ENGINEERING_CONTRACT" in text or "IMPLEMENTATION_BLUEPRINT" in text
print("docs-present")
PY

python3 - <<'PY'
from pathlib import Path
contract = Path("docs/architecture/engineering_contract_v5.md").read_text()
for needle in ["accepted evaluation or safe pending/block context"]:
    assert needle not in contract, f"contract still contains contradiction: {needle}"
blueprint_prose = Path("docs/architecture/implementation_blueprint_v5.md").read_text().split("Validation commands:", 1)[0]
for needle in ["root durable job remains", "reserved for later split", "round_size.*10", "下一轮10题"]:
    assert needle not in blueprint_prose, f"blueprint prose still contains contradiction: {needle}"
print("v5-doc-contradiction-check-ok")
PY

python3 -m unittest tests/test_learning_system.py -v

/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
```

For this docs-only update, run only the markdown/static checks unless implementation is authorized.

Review gates:
- Required next gate: 镜花 DESIGN_REVIEW of the three updated architecture docs.
- After design review: SKELETON_PASS with handler/prompt/schema/worker shells before business logic.
- Before implementation DONE: 观止 TEST_CASE_SPEC/QA and 清秋 rendered UX review for changed child states.
- Live model/lesson validation requires explicit authorization and must label live/recorded/mock evidence correctly.

Rollback/recovery:
- Docs update rollback is normal git/file revert by user authorization only.
- Future production rollback: disable v5 entry via compatibility flag or project blocked projection; preserve rows and audit.
- No destructive data rollback. Supersede/invalidated/blocked labels preserve lineage.

BLUEPRINT_READINESS_GATE:
- verdict: BLUEPRINT_READY_FOR_DESIGN_REVIEW
- files_and_symbols_named: yes
- durable_job_dag_named: yes
- skeleton_pass_delta_explicit: yes
- true_model_agents_independently_retryable: yes
- deterministic_gate_not_oversplit: yes
- ux_p0_routed: yes
- qa_p0_routed: yes
- validation_commands_named: yes
- rollback_or_recovery_clear: yes
- blocking_gaps: none for 镜花 DESIGN_REVIEW; production implementation not authorized yet

Stop condition:
Stop after updating the three architecture docs and static self-review. Next owner is 镜花 for DESIGN_REVIEW.
