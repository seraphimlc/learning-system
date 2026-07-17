### DESIGN_REVIEW / PASS_WITH_SCOPE - 镜花（agentKey: `jinghua`）- 2026-07-10 18:46 CST

Verdict:
`PASS_WITH_SCOPE`.

Scope:
Focused re-review only of the four findings from
`docs/collaboration/reviews/2026-07-10-jinghua-technical-plan-v3-review.md`.
This passes the revised technical plan/engineering contract for the v3 first
implementation slice. It is not a code review PASS, QA PASS, data/content PASS,
or release readiness claim.

Source artifacts:
- `docs/architecture/technical_plan_v3.md`
- `docs/collaboration/reviews/2026-07-10-jinghua-technical-plan-v3-review.md`
- Targeted PRD cross-check: `docs/product/ai_native_math_learning_prd_v3.md`

Commands:
Read-only shell inspection with `nl -ba`, `sed`, `rg`, and `date`. No code,
server, DB mutation, tests, browser, or model calls were run.

Focused findings:

1. Previous P1 schema graph-lineage gap: resolved.
   Evidence:
   - `docs/architecture/technical_plan_v3.md:498` adds a dedicated
     `Graph lineage and provenance contract`.
   - `docs/architecture/technical_plan_v3.md:505` through
     `docs/architecture/technical_plan_v3.md:516` now covers `daily_flows`,
     `flow_steps`, `review_targets`, `attempts`, `evidence_validations`,
     `mastery_decisions`, `learner_node_status`, `next_step_decisions`,
     `late_evidence_reconciliations`, and `daily_summaries`.
   - `docs/architecture/technical_plan_v3.md:518` through
     `docs/architecture/technical_plan_v3.md:534` makes legacy node status rows
     missing-lineage hints only until recomputed.
   - `docs/architecture/technical_plan_v3.md:875` through
     `docs/architecture/technical_plan_v3.md:880` requires tests proving missing
     lineage cannot drive gate/planner/summary/confirmed report claims.

2. Previous P1 idempotency/index/transaction gap: resolved.
   Evidence:
   - `docs/architecture/technical_plan_v3.md:649` adds the SQLite invariant and
     transaction contract.
   - `docs/architecture/technical_plan_v3.md:651` through
     `docs/architecture/technical_plan_v3.md:660` defines version columns.
   - `docs/architecture/technical_plan_v3.md:662` through
     `docs/architecture/technical_plan_v3.md:675` specifies unique/partial unique
     indexes for active flow, current step, step handle, active attempt,
     idempotent submit, active job, validation version, mastery package, next
     decision, and summary.
   - `docs/architecture/technical_plan_v3.md:677` through
     `docs/architecture/technical_plan_v3.md:696` defines the submit transaction
     boundary, duplicate-key behavior, attempt/job creation, flow revision, and
     file-write recovery.

3. Previous P1 queue/worker lease/recovery and late-evidence gap: resolved.
   Evidence:
   - `docs/architecture/technical_plan_v3.md:254` through
     `docs/architecture/technical_plan_v3.md:265` adds lease/retry/dependency
     queue columns at the architecture-decision layer.
   - `docs/architecture/technical_plan_v3.md:698` through
     `docs/architecture/technical_plan_v3.md:756` defines job statuses, required
     `JobQueue` methods, payload version fields, dependency order, and fail-closed
     constraints.
   - `docs/architecture/technical_plan_v3.md:757` through
     `docs/architecture/technical_plan_v3.md:769` defines late evidence safe
     transition behavior and forbids rewriting the currently visible unanswered
     step.
   - `docs/architecture/technical_plan_v3.md:914` through
     `docs/architecture/technical_plan_v3.md:921` and
     `docs/architecture/technical_plan_v3.md:1089` through
     `docs/architecture/technical_plan_v3.md:1091` add targeted recovery and late
     evidence tests.

4. Previous P2 evidence vocabulary conflict: resolved.
   Evidence:
   - `docs/architecture/technical_plan_v3.md:247` through
     `docs/architecture/technical_plan_v3.md:252` states `usable` is a predicate
     and maps stored `gate_status=passed` to PRD/API `usable` only after
     `EvidenceUsePredicate.is_usable(...)`.
   - `docs/architecture/technical_plan_v3.md:536` through
     `docs/architecture/technical_plan_v3.md:548` gives the storage-to-PRD/API
     vocabulary mapping and says `passed` alone is not sufficient.
   - `docs/architecture/technical_plan_v3.md:771` through
     `docs/architecture/technical_plan_v3.md:796` defines report labels and
     precedence.
   - This now aligns with PRD vocabulary in
     `docs/product/ai_native_math_learning_prd_v3.md:385` through
     `docs/product/ai_native_math_learning_prd_v3.md:404`.

Residual risk:
- This pass is limited to the revised document contract. Implementation may still
  reveal DB/SQLite syntax constraints, race conditions, or integration gaps.
- UX_FLOW_SPEC v3 and DATA_CONTRACT_SPEC v3 remain separate required artifacts
  before final release, as the plan itself states.
- 观止 still needs to derive `TEST_CASE_SPEC` from the actual skeleton before
  non-trivial business logic fill.

Required next action:
Proceed to skeleton implementation/review sequencing under the plan's own stop
conditions. Keep business logic fill gated on SKELETON_PASS review and
TEST_CASE_SPEC unless 若命/user explicitly waives that risk.
