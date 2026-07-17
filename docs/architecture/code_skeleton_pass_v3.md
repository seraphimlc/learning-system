# SKELETON_PASS - 听云（agentKey: `tingyun`）- 2026-07-10 CST

Objective:

Create the v3 first-slice program skeleton only, based on
`docs/architecture/technical_plan_v3.md`: additive schema, v3 runtime/service
modules, child-safe route shells, minimal UI support, focused skeleton tests, and
fail-closed behavior. This is not full adaptive teaching/planning
implementation.

Engineering contract:

- Source: `docs/architecture/technical_plan_v3.md` `ENGINEERING_CONTRACT`.
- Runtime/service/gate own state, idempotency, recovery, projection, and
  evidence predicates.
- Agents remain semantic only and must call models through `model_router`.
- Child payloads must not expose graph ids, question ids, attempt ids, session
  ids, model/provider names, agent names, rubrics, OCR confidence, or queue/job
  internals.
- v3 rows that can affect planning/reporting carry graph/question/evidence
  lineage fields. Missing, stale, pending, mock-only, or missing-lineage evidence
  fails closed.

Implementation blueprint:

- Source: `docs/architecture/technical_plan_v3.md` `IMPLEMENTATION_BLUEPRINT`.
- Authorized first slice stops after schema/module/route/UI/test shells.
- Deferred: real target building, candidate backfill, planner decisions, answer
  analysis worker chain, evaluation/mastery updates, late evidence application,
  full new-knowledge teaching, browser QA, live model validation.

Page prototype / route shells:

| Surface/route | File/path | Shell state | UI states represented | Notes |
|---|---|---|---|---|
| `/api/child-bootstrap` | `learning_system/server.py`, `learning_system/daily_runtime.py` | v3 projection behind `V3_DAILY_RUNTIME_ENABLED=1`; legacy v2 otherwise | `choose_review`, `blocked`, reserved `current_step`, `teaching`, `summary`, `ready_for_new_knowledge` | v3 payload has no `today_plan.tasks` and no child-visible internals |
| `/api/daily-flow/review/start` | `learning_system/server.py`, `learning_system/daily_runtime.py` | creates/resumes daily flow and selects one real active-eligible current question | `current_step`, `blocked` | temporary deterministic selector; final planner-backed target selection remains deferred |
| `/api/current-step/submit` | `learning_system/server.py`, `learning_system/daily_runtime.py` | validates handle/idempotency/evidence, writes one pending attempt, and enqueues answer analysis | `analyzing`, child-safe blocked/error payload | no grading/mastery/planner mutation filled |
| `/api/operator/daily-flow/today` | `learning_system/server.py`, `learning_system/daily_runtime.py` | id-rich inspect shell | operator only | exposes flow/step/job/evidence/decision rows for review |
| Child page `/` | `app/local_learning_system/app.js` | thin v3 payload branch | `choose_review`, `current_step`, `teaching`, `analyzing`, `blocked`, `ready_for_new_knowledge`, `summary` | no visual polish; legacy UI remains when v3 flag disabled |

Skeleton created:

| File/path | Module/type/interface/class/function/route/handler | Status | Notes |
|---|---|---|---|
| `learning_system/db.py` | v3 tables/columns/indexes in `init_schema` | created | additive only; old rows preserved |
| `learning_system/graph_runtime.py` | `GraphRuntimeService`, `GraphVersion` | created | deterministic graph hash and lookup authority |
| `learning_system/evidence_gate.py` | `EvidenceUsePredicate`, `EvidenceGate`, result dataclasses | created | missing/stale/mock/pending evidence cannot become usable |
| `learning_system/job_queue.py` | `JobQueue`, `JobQueueResult` | created | SQLite queue wrapper with lease/idempotency skeleton |
| `learning_system/daily_runtime.py` | `DailyLearningRuntime`, `CurrentStepSubmission`, feature flag helpers | created | choose-review/blocked/current-step projection shell |
| `learning_system/model_router.py` | `evaluation_route`, `planner_route`, `teaching_route` | created | no live calls added |
| `learning_system/question_bank.py` | `QuestionBankService.candidate_packet_for_node` | created | metadata-only packet; v2 rows without lineage excluded |
| `learning_system/server.py` | v3 child/operator routes | created | feature-flagged child bootstrap |
| `app/local_learning_system/app.js` | v3 state branch and submit/start helpers | created | minimal shell visibility only |
| `tests/test_learning_system.py` | focused v3 skeleton tests | created | active tests, not xfail |
| `docs/project-index.md` | v3 route/module/artifact index entries | updated | routing aid only |
| `docs/domain-index/math-learning.md` | v3 route/module/table search hints | updated | routing aid only |

Program framework:

| File/path | Class/function/method/API/task/test shell | Signature/contract | Stub behavior |
|---|---|---|---|
| `learning_system/graph_runtime.py` | `GraphRuntimeService.current_graph_version()` | returns `metadata.version+sha256:<hash>` | deterministic local graph file only |
| `learning_system/evidence_gate.py` | `EvidenceUsePredicate.evaluate(...)` | attempt + current lineage + gate/provider mode | returns unusable unless all required predicates pass |
| `learning_system/evidence_gate.py` | `EvidenceGate.validate_attempt(...)` | attempt id + analysis version/provider mode | writes validation row when attempt exists; no mastery/planner mutation |
| `learning_system/job_queue.py` | `enqueue/claim/start/heartbeat/finish/retry/wait/block/dead_letter/recover` | v3 background job wrapper | requires lineage payload; no worker business chain |
| `learning_system/daily_runtime.py` | `load_or_create_daily_flow/start_review_mode/project_child_state` | daily flow state/projector shell | creates flow; start review projects one real current step or a child-safe block |
| `learning_system/daily_runtime.py` | `persist_child_response` | current-step command | records pending attempt, optional photo metadata/file, and answer-analysis job; duplicate submits reuse the active attempt |
| `learning_system/daily_runtime.py` | `reconcile_answer_uploads` | upload recovery helper | removes unreferenced v3 answer files and stale temp files; service startup runs it only for the guarded real project DB path |
| `learning_system/question_bank.py` | `QuestionBankService.candidate_packet_for_node` | target node + graph/bank version + limits | returns exact packet shape; excludes missing-lineage rows |
| `learning_system/server.py` | v3 route handlers | stdlib HTTP JSON routes | child-safe errors; operator inspect id-rich |
| `tests/test_learning_system.py` | `test_v3_*` | schema/module/route/legacy checks | proves skeleton compiles and routes are gated |

Compile/static check:

```bash
python3 -m py_compile learning_system/db.py learning_system/server.py learning_system/model_router.py learning_system/question_bank.py learning_system/daily_runtime.py learning_system/graph_runtime.py learning_system/evidence_gate.py learning_system/job_queue.py tests/test_learning_system.py
```

Result: passed.

Focused unittest:

```bash
python3 -m unittest \
  tests.test_learning_system.LearningSystemTest.test_v3_skeleton_schema_additive_and_indexes_exist \
  tests.test_learning_system.LearningSystemTest.test_v3_skeleton_modules_expose_fail_closed_contracts \
  tests.test_learning_system.LearningSystemTest.test_v3_child_route_shell_returns_child_safe_payload_when_enabled \
  tests.test_learning_system.LearningSystemTest.test_v3_feature_flag_disabled_keeps_legacy_child_bootstrap -v
```

Result: passed, 4 tests.

Gate fix addendum - 2026-07-10 CST:

- Fixed `learning_system/job_queue.py` lease timestamps so claims write a real
  ISO `lease_expires_at` instead of a string suffix; recovery now leaves
  unexpired claimed/running jobs alone and requeues only expired leases.
- Hardened queue ownership: start/heartbeat/finish/retry/wait/block/dead-letter
  transitions now require the active lease owner and an unexpired lease; stale
  workers return `applied=false`.
- Completed the first-slice queue contract fields in `learning_system/db.py`:
  `available_at`, `dead_letter_reason`, `depends_on_job_id`, and
  `route_meta_json`; added `teaching_generation` and kept `answer_review` as a
  legacy alias.
- Added dependency gating for queued jobs: a job with `depends_on_job_id` cannot
  be claimed until the parent job has succeeded.
- Hardened `learning_system/evidence_gate.py` so usable evidence requires actual
  `flow_steps`, `question_items`, and active `question_review_records` lineage.
  Missing lineage stays `missing_lineage`; pending analysis stays `pending` and
  is not misclassified by the derived `gate_status`.
- Tightened v3 evidence lineage: usable evidence now also requires the attempt's
  `question_id`, `review_record_id`, graph version, question-bank version, and
  question item version to match the child-visible `flow_steps` row; a valid
  status without non-empty schema-valid `answer_analysis_json` is rejected.
- Reused the question active-use gate for v3 evidence: the linked review record
  must match the question item version/source type, be approved and active, carry
  reviewer authorization, and match the current candidate digest.
- Fixed the exact-review-record lineage hole found by 观止: v3 evidence now
  validates the attempt/flow-step bound `review_record_id` itself against the
  active-use candidate digest and reviewer-run authorization, so a valid sibling
  review record for the same question cannot mask a forged/stale bound record.
- Applied the same exact active-use rule before evidence exists: the temporary
  first-question selector and planner candidate packet now skip forged/stale
  active review records instead of letting them reach the child step or planner
  metadata and relying on the later evidence gate to reject them.
- Closed the follow-up data-lineage hardening note from 霜弦: v3 evidence now
  also requires `flow_steps.attempt_id` to point back to the same attempt, so the
  attempt-to-step binding is bidirectional before evidence can be usable.
- Expanded QA false-pass coverage after 观止 review: v3 photo submit now exercises
  the real child-submit attachment branch; invalid submit cases assert no
  attempt/job/upload side effects; duplicate submits assert both attempt and job
  counts; mock/not-configured/stale evidence cannot become confirmed; forged
  bound review-record lineage is rejected even when a valid sibling exists;
  first-question selection and candidate-packet selection reject forged active
  review records; step-attempt back-reference mismatches are rejected; and
  stale-owner queue retry/wait/block/dead-letter transitions are covered.
- Updated `learning_system/reports.py` to expose the v3 seven-label report
  vocabulary with precedence:
  `blocked > stale > missing_lineage > mock_only > pending > inferred > confirmed`.
- Hardened `learning_system/daily_runtime.py` current-step projection so
  child-visible payloads strip/assert against graph/question/model/provider/
  agent/rubric/OCR/queue/job internals and expose a stuck affordance flag.
- Added child UI support in `app/local_learning_system/app.js` for an explicit
  `analyzing` state and "stuck" submission path.
- Fixed the UX skeleton gap: `start_review_mode()` now selects a real current
  graph-generated, active-eligible question from the current question bank
  instead of blocking immediately. This is a temporary deterministic selector,
  not the final planner/target-selection policy.
- `persist_child_response()` now writes a v3 pending attempt, binds it to the
  flow step, persists optional answer-photo attachment metadata/file, enqueues
  an `answer_analysis` job, and projects `analyzing` without fabricating a grade
  or mastery decision.
- Completed terminal-flow projection so a completed daily flow can return
  `summary` instead of creating a new flow for the same day.
- Fixed `analyzing` UX honesty: the child page now schedules v3 state polling
  while an answer is being analyzed, so the message that the page will refresh
  automatically is backed by implementation.
- Added a stuck-only submission regression test so the "卡住了" path is not
  merely a front-end affordance.
- Fixed child-safe start-review errors: when no active question is available,
  `/api/daily-flow/review/start` returns a v3 child-safe blocked payload rather
  than leaking a raw server error.
- Hardened concurrent submit recovery: if the unique active-attempt constraint
  wins a race before the runtime sees it, the runtime recovers the canonical
  active attempt and projects `analyzing` instead of returning a 500.
- Added v3 answer-upload reconciliation: unreferenced final files and stale
  `.tmp` files are removed by an explicit helper, with service-start execution
  guarded to the exact real project `data/local_learning_system.sqlite` and the
  default `data/uploads/answers` directory so scratch DBs and custom upload roots
  cannot clean the shared project upload directory.

Gate fix verification:

```bash
python3 -m py_compile learning_system/db.py learning_system/server.py learning_system/model_router.py learning_system/auto_review.py learning_system/planner.py learning_system/question_bank.py learning_system/daily_runtime.py learning_system/graph_runtime.py learning_system/evidence_gate.py learning_system/job_queue.py
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check app/local_learning_system/app.js
python3 - <<'PY'
import re, subprocess, sys
from pathlib import Path
text = Path("tests/test_learning_system.py").read_text()
names = [
    "tests.test_learning_system.LearningSystemTest." + name
    for name in re.findall(r"def (test_v3_[^(]+)\(", text)
]
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", *names, "-v"]))
PY
```

Result: passed, 30 v3 tests plus compile/static checks; 31 focused tests when the v2 feature-flag smoke is included.

Legacy smoke:

```bash
python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe -v
```

Result: passed.

Stub safety:

- `V3_DAILY_RUNTIME_ENABLED=0` keeps legacy v2 child bootstrap.
- v3 bootstrap exposes `choose_review` and does not include fixed
  `today_plan.tasks`.
- start-review writes auditable v3 rows and returns one current real question
  step from active current question-bank lineage.
- current-step submit writes one pending attempt per step/idempotency key,
  queues answer analysis, and projects `analyzing`; missing/non-visible steps
  still fail closed with child-safe payload.
- queued jobs are protected by active idempotency, real leases, owner-gated
  transitions, dependency gating, retry recovery, and explicit result refs.
- v3 photo evidence has a recovery path for unreferenced upload files; it does
  not make unreferenced files usable evidence.
- candidate packet excludes current v2 bank rows as `missing_lineage` until a
  deterministic lineage backfill exists.
- evidence gate treats missing flow step, missing graph/bank version, missing
  analysis, mock/not-configured provider mode, and non-passed gate status as not
  usable.
- no live model calls were added or run.
- no real DB/reports were deleted or reset; answer-photo uploads are only
  persisted when the child submits a v3 current step.

Business logic status: minimal_safe_stub_only

Test hooks/shells:

- Focused tests in `tests/test_learning_system.py` cover schema/index existence,
  module fail-closed contracts, v3 child-safe route projection when enabled, and
  legacy child bootstrap when disabled.
- Full v3 TEST_CASE_SPEC remains required before business logic fill.

Deferred implementation:

- Build review target pool from graph/node status.
- Replace temporary deterministic first-question selector with planner-backed
  target selection from graph/node status, weak evidence, and review budget.
- Deterministic candidate lineage backfill and active-use packet population.
- Real planner/evaluation/teaching route payloads and gate validation.
- Worker chain:
  `answer_analysis -> evidence_validation -> evaluation_update -> planner_decision`.
- Late evidence reconciliation and safe-transition application.
- Daily summary/report label generation.
- Browser smoke and 10-20 step adaptive-day QA simulation.

Deviations from blueprint:

- `planner.py`, `auto_review.py`, browser smoke, and simulation
  files were not touched because this authorized task requested
  SKELETON_PASS-only shells, not business-chain fill.
- v3 `background_jobs` active idempotency unique index excludes empty legacy
  `idempotency_key` rows to keep additive migration safe.
- v3 first review selection is deterministic and active-lineage-safe, but not
  yet pedagogically adaptive. It must be replaced before this can be called a
  complete review planner.

Ready for review/test design:

Yes, for skeleton review only.

Next gate: CODE_REVIEW + DATA_REVIEW + UX_REVIEW + TEST_CASE_SPEC
