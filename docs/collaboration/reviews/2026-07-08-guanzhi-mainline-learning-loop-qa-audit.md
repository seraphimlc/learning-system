### QA / PASS_WITH_SCOPE - 观止（agentKey: `guanzhi`）- 2026-07-08 15:14 CST

Verdict:
`QA_PASS_WITH_SCOPE`.

independence_required:
yes

context_mode:
fresh

context_origin:
new mainline audit after REG-05 closed

diff_pin:
not_applicable; current workspace is not a git repository (`git status --short` returned `fatal: not a git repository`)

Scope:
Audited current QA coverage for the main child learning loop across `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `scripts/live_child_ui_10x.py`, `scripts/child_learning_scenarios.py`, `scripts/live_child_acceptance.py`, `app/local_learning_system/*`, and the learning-system server/auto-review/orchestrator/planner interfaces. Executed non-destructive checks using temp DB/temp server or read-only live probe only.

Forbidden scope honored:
- No production code edits.
- No test implementation edits.
- No external model calls.
- No destructive reset of `data/local_learning_system.sqlite`.
- Did not stop or mutate the existing 8765 service.
- Did not claim full product PASS.

Project boundary overlay:
Applied `AGENTS.md`, `docs/product/ai_native_math_learning_prd_v2.md`, `docs/domain-index/math-learning.md`, and `docs/project-rules/qa-learning-system-addendum.md`: one child Web端, no parent intervention in normal learning, graph-bound teaching/evidence/planning, reasoning-aware semantic grading, untrusted photo/OCR evidence, evidence-linked next plan, no deterministic fake model evidence upgraded into live intelligence.

Source artifacts read:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/agent-registry.json`
- `docs/project-rules/qa-learning-system-addendum.md`
- `docs/collaboration/inbox.md`
- `docs/qa/test_case_spec_v2.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/domain-index/math-learning.md`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/live_child_ui_10x.py`
- `scripts/child_learning_scenarios.py`
- `scripts/live_child_acceptance.py`
- selected `learning_system/*.py`
- `app/local_learning_system/*`

Environment:
- Local macOS workspace.
- Python: `python3`.
- Browser smoke used bundled runtime Node and Playwright dependency path in `tests/browser_smoke_learning_system.mjs`.
- Existing 8765 service observed read-only only: PID `44963`, command `python -m learning_system.server --db data/local_learning_system.sqlite --port 8765`.

## Coverage Matrix

| Acceptance target | Current automated evidence | Coverage judgment |
|---|---|---|
| Real child can complete a 10-question round | `tests/browser_smoke_learning_system.mjs` submits through rendered child UI to 10/10; one-off temp API journey completed 5 lessons x 10 tasks. | Covered with temp DB and mocked/manual review evidence; not live child/live model. |
| Submissions advance without waiting for each AI call | `test_child_submission_returns_before_async_ai_review_finishes`; browser smoke advances to `2 / 10`; one-off API journey max submit latency `0.013s`. | Covered. |
| Completion waits only for remaining review/summary | `test_group_completion_background_processes_pending_answers_when_model_available`, `test_group_completion_poll_does_not_lock_database_during_model_call`, browser smoke pending guard and later close. | Covered with mocked model/manual completion. |
| Per-question analysis | `test_child_completion_message_includes_each_attempt_review_point`; browser smoke asserts 10 review markers; one-off API journey had `analyzed=10` every lesson. | Covered. |
| Round conclusion | Browser smoke and one-off API journey reached `closure_status=planned`; unit tests cover `waiting_ai`, `blocked`, and `planned`. | Covered. |
| Evidence-linked next plan | `child_learning_scenarios.validate_session_semantics` checks weak evidence links; one-off API journey returned rollback/remediate/prerequisite/retest task types linked to weak attempts/nodes. | Covered in mocked/temp mode. |
| Correct reasoning | `correct_full` scenario in scenario matrix and one-off lessons. | Covered. |
| Answer-only | `test_child_text_submission_caps_overconfident_answer_only_full_credit`; `answer_only` scenario. | Covered. |
| Stuck/cannot start | `stuck` scenario; evolution rollback tests including cannot-start repair. | Covered. |
| Blank/no usable evidence | `blank_or_no_evidence` scenario in one-off lesson 5; low-confidence no-evidence wrong test. | Covered. |
| Wrong reasoning with correct final answer | `test_child_text_submission_downgrades_correct_answer_with_unsound_reasoning`; `wrong_reason_right_answer` scenario. | Covered. |
| Partial relation / wrong final or symbol/unit issue | `partial_relation_wrong_final` scenario and symbol/unit comparison checks. | Covered. |
| Readable photo | `test_photo_answer_uses_doubao_ocr_as_untrusted_answer_analysis_evidence`; `photo_correct` scenario. | Covered with mocked/recorded provider behavior, not live Doubao. |
| Unclear photo | `test_photo_only_submission_stays_pending_when_doubao_ocr_is_low_confidence`; `photo_unclear` scenario. | Covered with mocked/recorded provider behavior. |
| Remediation/rollback/retest | Wrong-answer completion test plus one-off journey next-plan task types include rollback/remediate/prerequisite/retest. | Covered. |
| Correct-only advance/retest without fabricated weakness | `test_evolution_updates_mastery_from_correct_only_evidence`, `test_evolution_recovers_from_blocking_status_after_later_correct_evidence`; one-off lesson 3 had 10/10 `correct_full`. | Covered with scope note: next plan still may contain prior weak-history tasks, so this is not a pure isolated brand-new learner proof. |

## Commands / Evidence

1. Identity validation:
   - `node - <<'NODE' ...`
   - Result: `IDENTITY_VALIDATED guanzhi header matches registry`

2. Unit/API regression:
   - `python3 -m unittest tests/test_learning_system.py -v`
   - Result: `Ran 133 tests in 134.014s` / `OK`
   - Coverage observed: evidence gates, semantic grading guardrails, child-safe DTOs, async review, background recovery, session completion, per-question review points, planner/evolution/report evidence predicates, photo attachment/OCR paths, remediation, rollback, correct-only evolution, lineage repair.

3. Browser smoke with temp DB/temp upload/temp port:
   - `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs`
   - Result: `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`
   - Coverage observed: child-only page, load/save/upload durable error panels, photo preview, post-submit advance to `2 / 10`, pending evidence does not evolve, 10-question UI submission path, manual/API completion of remaining pending reviews, 10 review points, child-safe completion projection, XSS guard.

4. Next-most-valuable temp API journey, created as a one-off non-persistent check:
   - Temp SQLite + temp upload root + `server.start_test_server`.
   - Patched `auto_review._call_openai_evaluator`, `auto_review._review_answer_photo`, and evolution question model to deterministic local fakes from `scripts/child_learning_scenarios.py`.
   - Result: `PASS`, `issues=[]`.
   - Completed 5 lessons x 10 tasks. Max child submission latency per lesson: `0.012s`, `0.013s`, `0.013s`, `0.013s`, `0.012s`.
   - Every lesson: `task_count=10`, `closure_status=planned`, `summary.pending=0`, `summary.analyzed=10`, background jobs `succeeded=10`.
   - Scenario coverage included `correct_full`, `answer_only`, `stuck`, `wrong_reason_right_answer`, `photo_correct`, `photo_unclear`, `partial_relation_wrong_final`, `blank_or_no_evidence`, plus a correct-only lesson.

5. Read-only live acceptance fake-pass probe:
   - `python3 scripts/live_child_acceptance.py --report /tmp/guanzhi-live-child-acceptance-readonly.md --timeout-seconds 20`
   - Result: exit code `1`, report verdict `LIVE_ACCEPTANCE_NEEDS_FIX`.
   - Only issue: real child-submission acceptance was not run because `--write-real-submission` was intentionally omitted.
   - Read-only facts: existing 8765 serves 10 child tasks, live DB has 56 current nodes, 1120 current practice questions, 20 per node, no active pending attempts/background jobs/lineage issues.

## False-Pass Audit

- Command exit codes and verdicts agreed: unit and browser smoke exited `0` with PASS/OK; read-only live acceptance exited `1` with a scoped `NEEDS_FIX` because it refused to fake a live write acceptance.
- No external model call evidence was used as semantic proof. All AI judgment coverage is mocked/recorded/local guardrail coverage.
- Browser smoke proves rendered happy/error paths and a 10-question UI submission path, but its post-submit completion depends on operator/API grading for pending attempts; this is valid chain evidence, not live AI autonomy evidence.
- The one-off 5-lesson API journey is stronger semantic-loop regression evidence, but it is not rendered UI evidence and uses local fakes.
- Existing 8765 read-only probe proves service shape and DB health only; it does not prove a real child can complete a fresh live round today.

## Not Covered

- Live GPT-compatible answer-analysis quality across the semantic matrix.
- Live Doubao-compatible OCR quality on real readable/unclear child photos.
- A mutating live 8765 acceptance round against `data/local_learning_system.sqlite`.
- Full browser multi-lesson semantic journey using `scripts/live_child_ui_10x.py` against current live DB; not run because it mutates the real ledger.
- Human final visual/taste review for child page age fit and tone.
- Long-run real-child convergence over multiple days with authentic answers.

## Residual Risk

- Mocked semantic scenarios may be internally consistent while a live model over-accepts answer-only or wrong-reasoning answers.
- Correct-only progression is covered in the presence of accumulated prior weak history, but a clean-new-learner correct-only long-run path remains worth isolating before a full product PASS.
- Browser smoke lacks saved screenshot/a11y artifact in this run; it checks DOM/focus/error panels programmatically but does not produce a durable visual artifact for this QA report.
- `live_child_ui_10x.py` is a stronger live-browser semantic harness, but its default target is current 8765/real DB and should be run only with explicit mutation approval or adapted to start its own temp mocked server.

## Required Next Action

Current automated regression coverage for the main child learning loop is strong enough for `PASS_WITH_SCOPE`.

Before any full product PASS, run either:
- an explicitly authorized mutating live acceptance on current 8765 with real model/OCR routes, or
- a temp-server version of `live_child_ui_10x.py`/equivalent browser harness that patches model/OCR locally and writes artifacts outside production paths.

For live quality release, add real provider sample evidence for the semantic matrix and a durable screenshot/accessibility artifact for the child page states.
