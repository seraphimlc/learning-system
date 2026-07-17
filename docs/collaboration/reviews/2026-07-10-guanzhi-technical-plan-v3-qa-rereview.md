### QA / PASS_WITH_SCOPE - 观止（agentKey: `guanzhi`）- 2026-07-10 CST

Verdict:
`PASS_WITH_SCOPE`

independence_required:
yes

context_mode:
focused re-review

context_origin:
spawned only for this review; did not author the plan or fixes

diff_pin:
`docs/architecture/technical_plan_v3.md`

Scope:
Focused re-review of whether the five prior 观止 QA plan findings in
`docs/collaboration/reviews/2026-07-10-guanzhi-technical-plan-v3-qa-review.md`
were addressed in the revised `docs/architecture/technical_plan_v3.md`.

Forbidden scope:
No QA execution. No production/test code changes. No QA PASS. No replacement for
镜花 engineering review or 霜弦 data/content review.

Project boundary overlay:
Applied from the existing v3 PRD/project boundary and the prior 观止 review:
flow completion is not enough; QA must preserve chain, semantic, teaching, and
provider-integrity distinctions. Mocked evidence cannot prove live model
intelligence.

Source artifacts:
- `docs/architecture/technical_plan_v3.md`
- `docs/collaboration/reviews/2026-07-10-guanzhi-technical-plan-v3-qa-review.md`

Environment:
Read-only document review. No server, browser, test, DB, or model execution.

Focused findings:

1. Prior finding: 10-20 adaptive-day coverage was not a hard first-slice gate.
   Status: fixed at plan level.
   Evidence: revised contract tests require a browser/API simulation over a v3
   `daily_flow` for 10-20 current steps, with mixed evidence, all-correct
   segment, slow-model branch, skipped mastered nodes, no parent intervention,
   no fixed-list regression, all steps in summary, and evidence-linked next
   decisions (`technical_plan_v3.md` lines 935-939). The TEST_CASE_SPEC handoff
   repeats this as a hard QA gate (`technical_plan_v3.md` lines 1124-1127).

2. Prior finding: async/model-slow recovery matrix was too shallow.
   Status: fixed at plan level.
   Evidence: revised contract tests now cover slow model with independent safe
   target, slow model with no independent target, stale queued/running/error
   jobs, pending attempts without jobs, and completed output not applied
   (`technical_plan_v3.md` lines 914-917). Queue lease/recovery is now specified
   with statuses, claim/start/heartbeat/finish/retry/wait/block/dead-letter/
   recover methods, versioned payload fields, dependency order, and the rule
   that no job may update mastery or confirmed plan from pending/stale/
   invalidated/mock/missing-lineage evidence (`technical_plan_v3.md` lines
   698-755). The handoff also requires retry metadata and no fake mastery
   (`technical_plan_v3.md` lines 1110-1113).

3. Prior finding: no hidden fixed list plus next-step trace was under-specified.
   Status: fixed at plan level.
   Evidence: the current-step contract now requires no `today_plan.tasks` and no
   hidden fixed daily list because every next step must reference a
   `next_step_decision` written after the previous step/evidence state
   (`technical_plan_v3.md` lines 889-892). The next-step decision schema is now
   a required decision ledger with source attempts, evidence validations, mastery
   decisions, review target, candidate packet id/hash, pending evidence, skipped
   nodes, branch policy, provider mode, fallback reason, stale/mock source ids,
   report label, and reason (`technical_plan_v3.md` lines 611-645). The hard
   QA handoff repeats the trace requirement (`technical_plan_v3.md` lines
   1122-1123).

4. Prior finding: semantic scenarios were not tied to downstream consequences.
   Status: fixed at plan level.
   Evidence: contract tests now require answer-only, wrong-reason-right-answer,
   stuck/cannot-start, blank/no usable evidence, partial relation/wrong final,
   symbol/unit issue, readable photo, and unclear photo cases to assert answer
   analysis dimensions, process gap, error tags, OCR usability, confidence
   policy, validation status, mastery behavior, child feedback/repair, planner
   branch, and report label (`technical_plan_v3.md` lines 926-931). The named
   test list adds `test_v3_semantic_cases_assert_analysis_gate_mastery_planner_report`
   (`technical_plan_v3.md` line 1095), and the TEST_CASE_SPEC handoff states
   semantic cases must assert `analysis -> gate -> mastery -> planner -> report`
   consequences, not only model JSON shape (`technical_plan_v3.md` lines
   1117-1118).

5. Prior finding: provider integrity and false-pass harness were not explicit
   enough.
   Status: fixed at plan level.
   Evidence: provider mode is required on `next_step_decisions`, with allowed
   values including deterministic/mock/recorded/live/not_configured
   (`technical_plan_v3.md` line 634), and confirmed next-step decisions cannot
   be driven by mock evidence except when explicitly scoped (`technical_plan_v3.md`
   lines 641-645). Report label precedence now includes `mock_only`,
   `stale`, and `missing_lineage`, and `confirmed` is only possible when source
   rows are current, non-mock, lineage-complete, and predicate-valid
   (`technical_plan_v3.md` lines 771-794). Contract tests require stale `latest`
   and v2 fixed-flow artifacts to be rejected as v3 PASS evidence
   (`technical_plan_v3.md` lines 922-925), and the QA handoff requires base URL,
   DB path, provider mode, version marker, sampled flow/step/attempt ids,
   screenshots/artifacts, report path, real vs isolated ledger, and failure on
   issue-count/verdict/exit-code disagreement (`technical_plan_v3.md` lines
   1132-1135).

False-pass audit:
The prior false-pass risks are addressed for a planning artifact. The revised
plan now makes the five required safeguards hard TEST_CASE_SPEC handoff gates
instead of loose suggestions. It also adds sufficient schema, lineage, invariant,
queue, candidate-packet, decision, report-label, and provider-mode contracts for
观止 to derive a skeleton-specific `TEST_CASE_SPEC` after `SKELETON_PASS`.

Not covered:
This re-review did not execute tests, inspect a v3 skeleton, verify actual DB
indexes, run browser automation, call live/recorded providers, or validate UI
rendering. Therefore this is not `QA_PASS`; it is a plan-level
`PASS_WITH_SCOPE`.

Residual risk:
Implementation can still fail or under-test these requirements. In particular,
the later `TEST_CASE_SPEC` must bind these plan gates to actual file/symbol/API
targets from `SKELETON_PASS`, and mock-only QA must remain scoped for semantic
or model-intelligence claims.

Required next action:
Proceed to v3 `SKELETON_PASS` review path. After skeleton exists, 观止 should
derive the actual `TEST_CASE_SPEC` from concrete symbols/routes/tables and keep
the five fixed findings as non-waivable coverage gates unless 若命/user
explicitly accepts the risk.

Stop condition:
Focused re-review complete for the five prior 观止 findings. No remaining
plan-level false-pass blocker found in those findings.
