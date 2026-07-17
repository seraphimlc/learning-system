### QA_AUDIT_PLAN - 观止（agentKey: `guanzhi`）- 2026-07-11 CST

Objective:

Design the execution audit for v5 single-child AI math learning QA so that a
green script, completed browser flow, mocked model, or generated report cannot
be mistaken for product or semantic PASS.

Acceptance target:

- Child can independently run the loop: open/resume -> one current step ->
  text/photo/stuck answer -> evidence saved -> async AI analysis -> evidence gate
  -> teaching/repair/next step -> summary.
- Semantic judgment distinguishes reasoning quality, not only final answer.
- Photo/OCR evidence is validated before use.
- Pending/blocked/mock/stale/missing-lineage facts are truthful in child state,
  Codex-readable records, and reports.
- Graph rollback, retest, transfer, and safe stop are evidence-driven.

Scope:

- Child browser continuity, current app/API/runtime/DB evidence chain.
- Semantic answer-analysis oracle and recorded/live model evidence policy.
- Photo/OCR, low confidence, text-photo conflict, OCR hallucination.
- Async queue, restart recovery, double submit, model missing/failing.
- Child-safe DOM/API payloads.
- Report truthfulness and Codex progress query evidence.
- 10-lesson real simulation definition and false-pass audit.

Forbidden scope:

- Do not edit production code during QA execution.
- Do not mutate the real local learning ledger or call live providers without
  explicit authorization for that run.
- Do not claim `QA_PASS` from mock-only tests, browser smoke alone, fixture-only
  grading, or report formatting.

Project boundary overlay:

- Single child, math first, summer bridge.
- Every question, answer analysis, teaching action, evaluation, plan, and report
  must bind to graph nodes.
- Grade 7 failure checks prerequisite chains before same-type drill.
- Correct final answer with wrong or missing reasoning is not mastery.
- Child surface must not expose ids, graph/provider/model/queue/rubric/Codex
  internals.

Source artifacts:

| Source | Use |
|---|---|
| `docs/qa/test_case_spec_v5.md` | Baseline coverage, gaps, oracle inventory |
| `docs/product/ai_native_math_learning_prd_v5.md` | Product acceptance and oracle policy |
| `docs/product/ai_native_math_learning_product_structure_v5.md` | States, modules, data objects, trust labels |
| `docs/project-rules/qa-learning-system-addendum.md` | Mandatory false-pass and semantic QA stance |
| `app/local_learning_system/*` | Browser surface and client state targets |
| `learning_system/daily_runtime.py`, `server.py`, `job_queue.py`, `evidence_gate.py`, `db.py` | Runtime, routes, async, gate, DB ledger |
| `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs` | Existing regression entrypoints |
| `scripts/child_learning_scenarios.py`, `scripts/simulate_child_learning_journey.py`, `scripts/live_child_acceptance.py`, `scripts/live_child_ui_10x.py` | Scenario and multi-lesson harnesses |

Environment:

- Local app target: `http://127.0.0.1:8765` when browser/live QA is authorized.
- Current local DB default: `data/local_learning_system.sqlite`.
- Safer simulation DB: temporary DB or `--db-copy-from` copy unless user
  explicitly allows mutation of the real ledger.
- Browser evidence: screenshots, DOM scans, network/API payload captures.
- DB evidence: row snapshots from flow, attempt, job, validation, decision, and
  summary tables.
- Model evidence: every run labeled `live_model`, `recorded_model`, `mock_only`,
  `pending`, or `blocked`.

Test case spec:

- Current spec: `docs/qa/test_case_spec_v5.md`.
- Readiness: scoped baseline ready; full executable spec still
  `TEST_CASE_SOURCE_NEEDS_FIX` until UX flow, engineering contract, skeleton, and
  accepted oracle fixtures exist.

Test case review:

- Existing `tests/test_learning_system.py` is valuable for current regression
  hooks, but many names are v2/v3-era and cannot by themselves prove v5 product
  semantics.
- Existing `tests/browser_smoke_learning_system.mjs` proves child-safe browser
  smoke and error handling, but it patches/disables model paths and cannot prove
  semantic or OCR quality.
- Existing 10-lesson scripts need v5 expansion for photo/text conflict, OCR
  hallucination, all-wrong/all-partial day patterns, repeated photo uncertainty,
  and recorded/live model labeling.

Model/runtime mode:

| Mode | Meaning | PASS boundary |
|---|---|---|
| `live_model` | Real configured provider call in current environment | Can support semantic PASS only with transcripts/scope labels and oracle comparison |
| `recorded_model` | Accepted stored provider input/output replay | Can support deterministic semantic regression for accepted samples |
| `mock_only` | Fake deterministic evaluator/OCR or patched route | Contract/state coverage only; never semantic/model PASS |
| `pending` | Evidence saved but analysis incomplete | No mastery or dependent next step from that evidence |
| `blocked` | Model/OCR/config/runtime cannot decide safely | Honest blocked/safe stop only |

Samples required:

| Fixture set | Minimum contents | Required before |
|---|---|---|
| `semantic_oracle_v5` | correct reasoning, answer-only, wrong-reason-right-answer, alternative method, symbol/unit/procedure error, blank/unclear, stuck, reasoning-bad schema-valid, low confidence | semantic PASS |
| `photo_ocr_oracle_v5` | readable, unclear, photo/text conflict, no usable work, OCR hallucination/guess, invalid/tampered image | photo/OCR PASS |
| `graph_rollback_oracle_v5` | four PRD rollback chains with current/prerequisite status permutations | planner/rollback PASS |
| `day_pattern_oracle_v5` | all wrong, all partial, mixed, correct-only, repeated stuck, repeated photo uncertainty | 10-lesson/day-level PASS |
| `report_truth_oracle_v5` | confirmed/weak/pending/blocked/stale/mock-only/missing-lineage summaries | report/Codex query PASS |

Risk classification:

High risk. Main false-pass modes are semantic overclaim, OCR guesswork, async
staleness, graph-unbound planning, report incompleteness, and mock-only results
being presented as product intelligence.

Test matrix:

| Case | Risk | Technique | Path/artifact | Sample | Oracle/rubric | Expected | Evidence required |
|---|---|---|---|---|---|---|---|
| AUD-CF-01 start/resume one step | worksheet or multi-step leak | state transition + UI/API | `/api/child-bootstrap`, child DOM | active/no active flow | PRD AC-01/02 | one child-safe current action or honest blocked/summary | screenshot, payload, `daily_flows`, `flow_steps` |
| AUD-CF-02 text answer save-before-analysis | lost evidence or fake sync grade | API + DB ordering | `/api/current-step/submit` | text reasoning | AC-03 | attempt exists before model analysis; job queued; child analyzing | timestamps, `attempts`, `background_jobs` |
| AUD-SEM-01 right answer wrong reasoning | answer-match grading | semantic oracle replay | answer-analysis route | SEM-03 | process matters | no stable mastery; targeted repair | `answer_analysis_json`, validation, next decision |
| AUD-SEM-02 alternative valid method | overfitting canonical solution | recorded/live oracle | answer-analysis route | SEM-04 | method validity | accepted if constraints sound | model transcript, comparison fields |
| AUD-SEM-03 answer-only | final-answer overclaim | decision table | answer-analysis/evidence gate | SEM-02 | process gap | partial/unstable; ask method or retest | process_gap, mastery decision |
| AUD-OCR-01 readable photo | photo path bypasses analysis | UI/API + fixture | upload + analysis | OCR-01 | validated OCR | attachment saved; eligible only after validation | screenshot, attachment hash, vision meta |
| AUD-OCR-02 low confidence/conflict/hallucination | OCR guessed mastery | adversarial fixture | upload + gate | OCR-02..OCR-05 | no guessed mastery | clarify/pending/blocked | review_meta, validation label, next step |
| AUD-STUCK-01 stuck and repeated stuck | random drill or shame loop | scenario flow | stuck submit | stuck day | child-safe teaching | micro-teach/probe/safe summary | DOM copy, attempts, decisions |
| AUD-ASY-01 model missing/failing | fake grading | fault injection/config | model route absent | model blocked | evidence policy | pending/blocked; no mastery | child state, jobs, report labels |
| AUD-ASY-02 restart/double submit | duplicate state | interruption + idempotency | queue recovery | pending job | PRD AC-23 | recovered once; no duplicates | before/after DB counts |
| AUD-GR-01 rollback chain | blind same-type drill | graph oracle | planner decision | GR-01..GR-04 | nearest teachable break | prerequisite probe/teach or retest by evidence | `next_step_decisions`, graph chain |
| AUD-QQ-01 question quality | low-age filler | negative prompt review | question bank/quality gate | filler/meta prompts | no filler/meta | rejected before active use | review record/rejection reason |
| AUD-REP-01 mixed summary | last-question-only report | report/source audit | `daily_summaries`, report | mixed day | summary contract | all evidence labels separated | summary source ids, freshness |
| AUD-REP-02 stale/mock/missing-lineage | report truth drift | mutation/replay | report/query | stale/mock/missing | trust labels | not current confirmed truth | version/label comparison |
| AUD-UI-01 child-safe browser | internal leak | DOM/API scan | child page | all visible states | child-safe oracle | no ids/provider/model/rubric/queue/Codex terms | screenshot, serialized payload scan |
| AUD-10X-01 10-lesson real simulation | completed flow but untested semantics | end-to-end + audit | `scripts/live_child_ui_10x.py` | day-pattern suite | day-level oracle | 10 lessons or safe early stop with all labels | report/json/screenshot/DB/model evidence |

False-pass audit:

- Compare command exit code, report verdict, issue count, screenshots, JSON
  artifacts, DB/API facts, and model evidence scope.
- Treat any mismatch as `QA_NEEDS_FIX`, not PASS_WITH_SCOPE.
- Reject PASS when the test only asserts fixture/mock existence or patched
  evaluator output.
- Reject PASS when child flow completes but `attempts`, `background_jobs`,
  `evidence_validations`, `next_step_decisions`, or `daily_summaries` do not
  show the corresponding source evidence.
- Reject PASS when report verdict says PASS but includes pending/blocked/stale
  semantic evidence without scoped labeling.
- Reject PASS when model mode is absent or inconsistent across DB/report/log.

Visual/interaction regression audit:

- Required states: loading, current step, submitting/saving, analyzing/pending,
  feedback/teaching, clarify evidence, ready for new knowledge, blocked,
  summary, load/save/upload error.
- Required viewports: mobile portrait around 390x844 and desktop around
  1280x900.
- Required checks: one current action, no overflow/overlap, keyboard focus,
  error panel focus and retry, draft/photo preservation, child-safe copy, no
  parent/operator/internal surfaces.
- Screenshot-only evidence is insufficient without DOM/API/state checks.

Semantic/product audit:

- Inspect `answer_analysis.comparison`, `process_gap`, `error_tags`,
  `blocking_evidence`, confidence, alternative method handling, and teaching
  seed.
- Inspect `EvidenceGate.validate_attempt` output and confirm trust labels are not
  mixed with mastery labels.
- Inspect planner decisions for graph-node lineage, candidate packet summary,
  source attempts/validations, and reasonability against rollback oracle.
- Inspect teaching for first cognitive break and one small next action.

Model-risk audit:

- Require provider route and mode label for every semantic/OCR claim.
- Require accepted recorded samples or live transcripts for semantic PASS.
- Require low-confidence, incomplete, schema-valid-but-wrong, and hallucinated
  model output cases.
- Require no secrets in reports, screenshots, DB rows, or model logs.

Adversarial/destructive cases:

- Blank text with no photo and no stuck.
- Invalid MIME, corrupt data URL, oversized or tampered image, malicious
  filename/path traversal.
- Text/photo contradiction.
- Model returns full score with contradictory comparison/process gap.
- Report generated, then source evidence changes.
- Duplicate submit, browser refresh during analyzing, restart with claimed or
  running job.
- Graph/question lineage mismatch.

10-lesson real simulation definition:

- Ten lessons are ten browser-driven child session/day cycles, not ten isolated
  API calls.
- Each lesson must start from child page/bootstrap, use real child controls,
  submit evidence, wait or refresh through async analysis, observe teaching or
  next step, and close with summary or safe stop.
- A normal lesson targets 10-20 child interactions. Early stop is acceptable only
  for repeated stuck, repeated unclear photo, blocked model/OCR/config, or
  intensive prerequisite repair.
- Across ten lessons the suite must cover correct-only, all-wrong, all-partial,
  mixed confirmed/weak/pending/blocked, repeated stuck, readable photo, unclear
  photo, photo/text conflict or OCR hallucination, model failure/restart, and one
  graph rollback chain.
- `mock_only` 10-lesson simulation can be a contract regression only.
  `live_model` or accepted `recorded_model` evidence is required for semantic
  claims.

Execution lanes:

| Lane | Command/artifact | Side effect policy | Maximum possible verdict |
|---|---|---|---|
| Source/static audit | read docs/code/specs only | none | source readiness only |
| Unit/API regression | `python -m unittest tests.test_learning_system` or focused v5 cases | local test DB/temp files only | PASS_WITH_SCOPE for contracts |
| Browser smoke | `node tests/browser_smoke_learning_system.mjs` | local server/temp upload artifacts | PASS_WITH_SCOPE for child UI smoke |
| Mock 10-lesson simulation | `python scripts/simulate_child_learning_journey.py --lessons 10` | temp DB or explicit copied DB | PASS_WITH_SCOPE for state/report contracts |
| Live preflight | `python scripts/live_child_acceptance.py` | read-only unless `--write-real-submission` is authorized | NEEDS_FIX if real submission not authorized |
| Live 10x | `python scripts/live_child_ui_10x.py --lessons 10` | mutates local ledger and may call models; requires explicit authorization | can support QA only with full evidence alignment |
| Recorded oracle replay | future fixture harness | fixture files only | semantic regression PASS for accepted samples |

Manual QA handoff:

- 清秋 must own child copy/visual quality expectations before final UI PASS.
- Human review may judge tone and pedagogical clarity, but cannot replace
  oracle/evidence checks.
- 若命 must accept recorded oracle samples and live-vs-recorded policy before
  semantic PASS is claimed.
- 听云 must provide final engineering contract/skeleton before executable final
  test cases are complete.

Audit output requirements:

- QA report must state exact commands, environment, DB path, server URL, model
  mode, samples, artifacts, and not-covered scope.
- QA report must include issue count and verdict consistency check.
- QA report must link or name screenshots/json/reports and source DB/API facts.
- QA report must never use prior reports or green scripts as proof of current v5
  semantic quality without rerun evidence.

Stop condition:

This plan is ready for future QA execution routing. It does not authorize live
ledger mutation, live provider calls, or `QA_PASS`. Execute only after 若命/user
authorizes the selected lane and missing full-spec sources are resolved or the
verdict is explicitly scoped.
