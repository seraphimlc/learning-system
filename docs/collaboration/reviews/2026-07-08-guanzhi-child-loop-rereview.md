### QA / PASS_WITH_SCOPE - 观止（agentKey: `guanzhi`）- 2026-07-08 15:33 CST

Verdict:
`QA_PASS_WITH_SCOPE`.

independence_required:
yes

context_mode:
fresh targeted rerun and false-pass audit

context_origin:
User/若命 request: rerun targeted QA for child-side 10-question / multi-round learning loop. Production code changes forbidden. Live data mutation forbidden.

diff_pin:
not_applicable; current workspace is not a git repository (`git status --short` returned `fatal: not a git repository`). This QA added only this evidence file.

Scope:
- Targeted QA rerun for child-side 10-question round and multi-lesson learning loop.
- False-pass audit for browser smoke, 10-lesson simulation, and unit/report/verdict/issue/exit-code alignment.
- Evidence audit for required child-learning scenario classes: correct reasoning, answer-only, stuck/cannot-start, blank/no usable evidence, correct answer with wrong reasoning, partial relation with wrong final/symbol issue, readable photo, unclear photo, weak-evidence follow-up, and correct-only round.

Forbidden scope:
- No production implementation edits.
- No mutation of `data/local_learning_system.sqlite`.
- No live provider/model/OCR call claim.
- No full product PASS claim.

Project boundary overlay:
Applied `AGENTS.md`, `docs/domain-index/math-learning.md`, `docs/product/ai_native_math_learning_prd_v2.md`, `docs/product/child_ux_flow_spec_v2.md`, `docs/architecture/data_contract_spec_v2.md`, and `docs/project-rules/qa-learning-system-addendum.md`: one child math learning page, active round target 10 tasks, graph-bound evidence/planning, reasoning-aware grading, answer photos as untrusted OCR evidence, no parent intervention in normal flow, pending/malformed/fake/stale/invalidated evidence cannot drive mastery/planning/evolution/report claims.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/agent-registry.json`
- `docs/project-rules/qa-learning-system-addendum.md`
- `docs/collaboration/inbox.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/qa/test_case_spec_v2.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`
- `scripts/child_learning_scenarios.py`
- `docs/system/qa/simulated_child_learning_journey_latest.md`

Environment:
- Workspace: `/Users/liuchang/Documents/gitproject/son-ai-learning-system`
- Date: 2026-07-08 CST
- Browser smoke: bundled Node at `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`; temp SQLite/temp upload/temp port from script.
- Simulation rerun DB/report: `/tmp/guanzhi-child-loop-10lessons-rerun.sqlite`, `/tmp/guanzhi-child-loop-10lessons-rerun.md`.
- Live DB `data/local_learning_system.sqlite` not used by rerun commands; file mtime after rerun remained `Jul 8 00:35`.

Test case spec:
Existing `docs/qa/test_case_spec_v2.md`; request-specific matrix below.

Samples:
- Deterministic semantic scenarios from `scripts/child_learning_scenarios.py`: `correct_full`, `answer_only`, `stuck`, `wrong_reason_right_answer`, `photo_correct`, `photo_unclear`, `partial_relation_wrong_final`, `blank_or_no_evidence`.
- Browser smoke includes rendered child flow, upload/save/load error panels, photo preview, pending guard, manual/API grading of pending attempts, 10 review points, XSS probe, and child-safe projection scan.

Test matrix:
| Case | Risk | Evidence | Judgment |
|---|---|---|---|
| 10-task child round | Stopping early or fake completion | Browser smoke submits 10 tasks; simulation has 10 sessions x 10 attempts | Covered in temp/mocked mode |
| Submit without waiting for grading | Child stuck after each submit | Browser smoke advances to `2 / 10`; unit `test_child_submission_returns_before_async_ai_review_finishes`; simulation requires `being_reviewed` | Covered |
| End-of-round false wait | "All submitted" never reaches actionable state | Browser smoke requires child handoff, later planned closure, 10 review points; unit covers no-model blocked state | Covered for temp/mocked/manual processing |
| Required semantic classes | Missing edge scenarios | Simulation report contains all eight scenario keys and a correct-only lesson | Covered |
| Weak evidence drives follow-up | Arbitrary next plan | `validate_session_semantics` checks weak attempts/nodes against `planning_signal.evidence_attempt_ids`, `source_node_ids`, and rollback candidates | Covered in temp/mocked mode |
| Correct-only round | Fabricated weakness or stuck remediation | Lesson 3 has `{"correct_full": 10}` and closes planned | Covered with scope note: prior weak history may still affect later planner mix |
| Photo readable/unclear | Photo presence over-trusted | `photo_correct` and `photo_unclear` scenarios validate attachment, OCR status/confidence, transcript/math objects, and comparison/process gap | Covered with fake OCR, not live Doubao |
| Answer-only/right-answer-wrong-reason | Final-answer false mastery | Unit tests and scenario validator require partial/wrong with process gap/comparison | Covered in guardrail/mocked mode |
| Verdict/issue/exit consistency | Report says PASS despite issues | Simulation output `PASS`, report `Verdict: PASS`, `Issues: 0`, command exit 0; script code raises `SystemExit(1)` on failures | Covered |

Evidence:
1. `python3 -m unittest tests/test_learning_system.py -v`
   - Result: exit 0; `Ran 134 tests in 139.990s` / `OK`.
   - Relevant coverage observed in test names/output: async submission, no-model recoverable state, pending/malformed analysis exclusion, answer-only downgrade, wrong-reason-right-answer downgrade, photo OCR low-confidence handling, group completion/background review/retry/recovery, 10 review points, question quality gates, planner/evolution/report evidence predicates.

2. `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs`
   - Result: exit 0; `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.
   - False-pass-specific assertions inspected in code: first submit must advance to `2 / 10`; after 10 submissions form is hidden and handoff visible; pending attempt cannot drive `/api/evolve`; child completion after analysis must include 10 review points; child projection must not expose model/agent/evolution internals.

3. `python3 scripts/simulate_child_learning_journey.py --lessons 10 --keep-db /tmp/guanzhi-child-loop-10lessons-rerun.sqlite --report /tmp/guanzhi-child-loop-10lessons-rerun.md`
   - Result: exit 0; output `{"verdict": "PASS", "lessons": 10}`.
   - Report facts: `Lessons simulated: 10`, `Verdict: PASS`, `Issues: 0`, `## Issues` -> `None`.
   - Temp DB facts: 10 child sessions; 10 closed/planned; 100 attempts; 100 graded; 0 pending; 100 analyzed; 100 background jobs succeeded.
   - Result distribution: 42 correct, 46 partial, 12 wrong.
   - Scenario coverage in rerun report: `correct_full`, `answer_only`, `stuck`, `blank_or_no_evidence`, `wrong_reason_right_answer`, `partial_relation_wrong_final`, `photo_correct`, `photo_unclear`; correct-only lesson detected.

False-pass audit:
- Browser smoke is not a pure "page opened" smoke. It asserts child-only boundary, durable error panels, save retry, post-submit advancement, pending no-evolution guard, completion handoff after 10 tasks, manual/API processing of remaining pending attempts, planned closure, 10 review markers, and child-safe response projection.
- Browser smoke still has scope: because model routes are disabled, it proves pending guard plus operator/API analyzed completion, not live AI autonomy.
- Simulation output/report/exit are aligned: script writes report from the same `failures` list that determines `SystemExit(1)`; rerun produced PASS/0 issues/exit 0. Temp DB counts independently match 10 lessons x 10 analyzed attempts.
- Unit command has no separate issue-count report, but unittest summary and exit code aligned: 134/134 OK and exit 0.
- No evidence command touched live DB. Rerun paths used `/tmp`; browser smoke uses temp DB and removes it in `finally`.

Visual/interaction regression audit:
- Browser smoke programmatically covers rendered load/save/upload error panels, focus to error panel, photo preview, submit retry, child-only text scans, progress advance, completion handoff, and review markers.
- Not a full visual PASS: no durable screenshot/a11y artifact was produced by this rerun, and human taste/copy review remains outside this evidence.

Semantic/product audit:
- The 10-lesson simulation is meaningfully semantic for a mocked harness: it validates `answer_analysis.comparison`, `process_gap`, error tags, blocking evidence, node status, photo OCR metadata, cause analysis, and next-plan evidence links.
- Required addendum scenario classes are covered.
- The harness is deterministic and internally consistent; it does not prove a live model will make the same judgments.

Model-risk audit:
- No live GPT/DeepSeek/Doubao evidence in this rerun.
- Evidence level for answer analysis/OCR is `mocked_provider_contract + local_guardrail + DB/API/browser integration`.
- Therefore full model-intelligence quality remains not covered. Per addendum, PASS must be scoped.

Adversarial/destructive cases:
- Covered by inspected/rerun unit/browser evidence: internal id rejection, child-safe DTO/text scan, duplicate submission rejection, pending no-evolution guard, XSS probe, no-model blocked/recoverable state, malformed analysis stays pending, low-confidence photo pending, stale/old question rejection.
- Destructive/live data cases intentionally not run.

Long-run behavior:
- Covered as a 10-lesson deterministic temp-DB simulation with 100 attempts and evidence-linked next plans.
- Not covered as authentic real-child, real-model, multi-day convergence.

Failures:
- None in the rerun scope.

Defect severity:
- No P0/P1/P2 defects found in the checked scope.

Not covered:
- Live GPT-compatible answer-analysis quality on all semantic classes.
- Live Doubao-compatible OCR on real readable/unclear child photos.
- Mutating acceptance against `data/local_learning_system.sqlite`.
- Full `scripts/live_child_ui_10x.py` against current live DB; it mutates the learning ledger and was outside the user-approved side-effect boundary.
- Durable screenshot/accessibility artifact for all child states from this rerun.
- Human final review for child tone, taste, and teaching naturalness.
- Clean-new-learner correct-only long-run progression with no prior weak history.

Residual risk:
- A live model may over-accept answer-only or wrong-reasoning answers despite local guardrails catching deterministic cases.
- Fake OCR can validate contract plumbing while live OCR may misread real handwriting or photo quality.
- Planner convergence is evidence-linked in the simulation, but real child answers may reveal new misconception patterns or graph granularity gaps.
- Browser smoke prevents the main "submit then wait forever" false-pass class, but does not replace a live UI 10x run with real provider latency and screenshots.

Required next action:
- Current rerun supports `QA_PASS_WITH_SCOPE` for temp/mocked child-loop regression.
- Before full product PASS, run an explicitly authorized live/provider QA slice or adapt `live_child_ui_10x.py` to a temp-server mocked-provider mode that produces durable screenshots/a11y artifacts without mutating `data/local_learning_system.sqlite`.
