# QA Incident Review - Review Stuck Recovery

Generated CST: `2026-07-07 12:33`

## Verdict

- Runtime incident: resolved.
- Latest real child session: `S-0f6a2338dcde` is now `closed/planned`.
- Real background jobs: no active `queued/running/waiting/error` jobs remain; all 14 historical jobs are `succeeded`.
- Child page after reload: shows the completion review panel and the button `看讲解，开始下一组`.

## Symptom

The child finished 4 questions and the page stayed around the review state instead of moving to the next learning group.

## Evidence

- `/api/child-bootstrap` returned `learning_group.state = needs_system_recovery`.
- Latest session `S-0f6a2338dcde` had `closure_status = blocked`, `blocked_reason = ai_review_unavailable`.
- All 4 latest attempts were `pending_review` with `review_meta.status = not_configured`.
- All 4 background jobs were `queued` with `run_count = 0`.
- The running 8765 process had no configured answer-review model key in its environment.

## Root Cause

The 8765 server had been started without model runtime configuration. The backend correctly refused to fake grading, but the child experience looked like review was simply slow. One local helper script also did not load `.env.local`, and direct `python3 -m learning_system.server` did not load it either.

## Recovery Performed

- Restarted the real 8765 server with GPT answer-review configuration and Doubao OCR route configuration.
- Existing queued jobs were picked up automatically on startup.
- The 4 jobs for `S-0f6a2338dcde` moved `queued -> running -> succeeded`.
- The 4 attempts were graded by `gpt-5.5` and received structured `answer_analysis_json`.
- Internal chain completed: answer analysis, graph binding, self-evolution, question design/review, evaluation, planning, teaching, and session closure.
- Session `S-0f6a2338dcde` closed as `planned` and generated next plan `P-5b4fa9447488`.

## Hardening Changes

- `learning_system/server.py` now loads gitignored `.env.local` on real startup.
- Startup logs print AI route status without printing API key values.
- `scripts/run_local_learning_server_8765.sh` now loads `.env.local` and writes logs to `logs/server-8765.log`.
- `.env.local` exists locally and is already covered by `.gitignore`.
- `docs/system/local_learning_system.md` documents `.env.local` as the preferred local runtime configuration path.

## Verification

- `python3 -m py_compile learning_system/server.py tests/test_learning_system.py`: pass.
- Focused recovery tests: 3 tests pass.
- Full unit suite: `Ran 115 tests ... OK`.
- Browser UI mocked regression: `scripts/smoke_child_ui.py --lessons 10` -> `MOCKED_REGRESSION_PASS`.
- Real 8765 check: latest child bootstrap returns `completion.closure_status = planned`.
- Real DB check: latest child sessions are `closed/planned`; background jobs only show `succeeded`.
- In-app browser check after reload: review panel is visible with `看讲解，开始下一组`.

## Scope Notes

- The 10-lesson smoke is a mocked regression, not live model acceptance.
- The recovery of `S-0f6a2338dcde` used the real 8765 DB and real model route.
- No parent/manual grading intervention was used to close the session.

## Residual Watch

- Next real child run should be watched for end-to-end timing and child-facing copy quality.
- Current technical blocker is cleared.
