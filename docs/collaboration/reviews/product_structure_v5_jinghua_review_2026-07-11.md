# Product Structure v5 Architecture Readiness Review

Reviewer: 镜花 (`jinghua`)
Date: 2026-07-11 CST
Scope: PRD v5 + Product Structure v5 readiness for UX flow, technical reverse, and technical planning source challenge.
Mode: design/architecture review only; no code changes or implementation review.

## Sources Read

- `AGENTS.md`
- `docs/product/ai_native_math_learning_prd_v5.md`
- `docs/product/ai_native_math_learning_product_structure_v5.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/collaboration/playbooks/engineering-execution.md`
- Current code structure hotspots, read-only:
  - `learning_system/daily_runtime.py`
  - `learning_system/job_queue.py`
  - `learning_system/evidence_gate.py`
  - `learning_system/question_bank.py`
  - `learning_system/model_router.py`
  - `learning_system/server.py`
  - `tests/test_learning_system.py`
  - `tests/browser_smoke_learning_system.mjs`

## Verdict

`PRODUCT_STRUCTURE_INPUT_READY_FOR_UX_AND_TECHNICAL_REVERSE`

PRD v5 plus Product Structure v5 are coherent enough for:

- 清秋 to write `UX_FLOW_SPEC v5`.
- 听云 to write `TECHNICAL_REVERSE_SPEC` / codebase reconnaissance.
- 听云 to run strict `ENGINEERING_SOURCE_READINESS` for `TECHNICAL_PLAN v5`.

They do **not** by themselves authorize implementation, `SKELETON_PASS`, QA PASS, or a full technical plan that skips UX/reverse/source-readiness gates.

No product-structure blocker needs to be routed back to 若命 before UX or technical reverse. The remaining risks are technical-plan and contract decisions, not product ambiguity blockers.

## Gate Rationale

Product Structure v5 preserves the product boundary: one child Web surface, parent via Codex only, graph-bound math review/new learning, adaptive one-step loop, text/photo/stuck/clarification evidence, and child-safe projection plus Codex-readable records (`docs/product/ai_native_math_learning_product_structure_v5.md:16-23`).

It defines the critical product structure that PRD v5 intentionally deferred: actor permissions (`...product_structure_v5.md:53-61`), modules (`...product_structure_v5.md:63-76`), features (`...product_structure_v5.md:78-92`), step taxonomy (`...product_structure_v5.md:94-105`), child-visible states (`...product_structure_v5.md:107-120`), flow contracts (`...product_structure_v5.md:122-130`), authoritative data objects (`...product_structure_v5.md:132-145`), response modes (`...product_structure_v5.md:147-156`), planner actions (`...product_structure_v5.md:158-171`), trust labels (`...product_structure_v5.md:173-193`), candidate rules (`...product_structure_v5.md:195-208`), summary split (`...product_structure_v5.md:210-231`), side effects (`...product_structure_v5.md:233-247`), and acceptance paths (`...product_structure_v5.md:249-264`).

The document also names the correct downstream route: UX first, technical reverse before planning, then technical plan/contract/blueprint/test artifacts (`...product_structure_v5.md:266-272`). Its quality gate explicitly says downstream guessing risk is reduced but not eliminated, and that UX/engineering must run their own readiness challenges (`...product_structure_v5.md:274-286`). This matches PRD v5, which says PRD alone is not engineering-source-ready and requires product structure, UX, codebase reconnaissance, architecture context, validation targets, and technical-plan authorization before full technical planning (`docs/product/ai_native_math_learning_prd_v5.md:648-672`).

## Prioritized Findings

### P0 - Gate Misuse Risk: Product-Structure Ready Must Not Become Technical-Plan Ready

This is the main process risk, not a product blocker.

Evidence:

- Product Structure status is `PRODUCT_STRUCTURE_READY_FOR_UX_AND_ENGINEERING_SOURCE_CHALLENGE`, not `ENGINEERING_SOURCE_READY` (`docs/product/ai_native_math_learning_product_structure_v5.md:1-3`).
- Product Structure stop condition authorizes 清秋 `UX_FLOW_SPEC v5` and 听云 `TECHNICAL_REVERSE_SPEC` / source-readiness challenge, not implementation (`...product_structure_v5.md:288-292`).
- Artifact contracts require source readiness and codebase inspection before a full `TECHNICAL_PLAN`; if readiness is not ready, 听云 must return scoped output instead of filling the full plan shape (`docs/collaboration/playbooks/artifact-contracts.md:459-468`).
- Engineering execution says readiness fails if 听云 would still invent module, flow, state, data object, side effect, rollback/recovery, failure mode, validation target, or owner (`docs/collaboration/playbooks/engineering-execution.md:113-131`).

Required handling:

- 若命 may route to UX and technical reverse now.
- 听云 must not claim `ENGINEERING_SOURCE_READY` until `UX_FLOW_SPEC v5`, codebase reconnaissance, data/project boundary checks, validation targets, and plan authorization are explicitly checked.
- A full `TECHNICAL_PLAN v5` should be accepted only after that source-readiness gate passes.

### P1 - State Machine: Product Structure Is Ready, Technical Plan Must Canonicalize Cross-Object Transitions

Product Structure defines child-visible step types and states well enough for UX and technical reverse (`...product_structure_v5.md:94-120`). It also states that Runtime owns authoritative transitions and internal agents only suggest (`...product_structure_v5.md:41-44`, `...product_structure_v5.md:57-60`).

Remaining technical-plan risk:

- UX states, product step types, persistent `daily_flow` / `flow_step` / `attempt` / `job` statuses, and planner actions still need a canonical transition table.
- The plan must decide how pending analysis, clarify, blocked, repeated stuck, new-knowledge readiness, and summary terminal states map across DB/API/child projection.
- Existing code is still v3 skeleton: `daily_runtime.py` defines v3 statuses (`learning_system/daily_runtime.py:19-22`), submits an attempt and marks the step analyzing (`learning_system/daily_runtime.py:238-371`), has summary as a blocked stub (`learning_system/daily_runtime.py:373-374`), and currently selects the first active review question using a temporary deterministic selector (`learning_system/daily_runtime.py:495-582`).

Must decide in technical plan:

- Canonical state/action enum and ownership.
- Allowed transitions, idempotent transition command names, terminal states, and stale-step behavior.
- How one visible child action is preserved across refresh, retry, restart, and late model results.

### P1 - Async Queue / Recovery: Product Acceptance Is Clear, Runtime Handler Is the Failure Hotspot

Product Structure gives the right acceptance target: save attempt before model call, queue analysis, show pending safely, and recover restart/double-submit without duplicates (`...product_structure_v5.md:253-264`). PRD v5 also requires that pending evidence cannot drive mastery and restart recovers pending/running/completed-unapplied work (`docs/product/ai_native_math_learning_prd_v5.md:564-574`).

Remaining technical-plan risk:

- Existing `job_queue.py` has useful idempotency, lineage, dependency, lease, retry, wait/block/dead-letter primitives (`learning_system/job_queue.py:45-128`, `learning_system/job_queue.py:130-251`).
- Current v3 submission enqueues `answer_analysis` with `provider_mode: not_configured` (`learning_system/daily_runtime.py:337-355`).
- Existing legacy background worker skips sessions that are not `child_learning_group` (`learning_system/server.py:1820-1823`), so v5 must not assume legacy processing closes v5 daily-flow jobs.
- `recover()` currently reports `missing_attempt_jobs_created: 0`, so completed-unapplied and missing-job reconciliation need explicit design (`learning_system/job_queue.py:227-251`).

Must decide in technical plan:

- Worker ownership and job handlers for answer analysis, OCR, validation, evaluation, teaching, planner, summary.
- Retry/backoff/dead-letter policy, completed-unapplied reconciliation, missing-job creation, and duplicate submit semantics.
- How child projection behaves when dependent evidence is pending versus when an independent safe step can be chosen.

### P1 - Evidence Chain: Product Structure Is Strong, Consumers Must Be Forced Through Gate

Product Structure cleanly separates trust labels from mastery labels (`...product_structure_v5.md:173-193`) and defines summary fields that carry source evidence, versions, applied/rejected evaluation updates, decision reasons, and freshness (`...product_structure_v5.md:210-231`). PRD v5 requires reports to separate confirmed, weak, pending, blocked, stale, mock-only, and missing-lineage evidence (`docs/product/ai_native_math_learning_prd_v5.md:388-399`, `docs/product/ai_native_math_learning_prd_v5.md:466-505`).

Remaining technical-plan risk:

- Existing `EvidenceUsePredicate` is fail-closed for active/graded/valid analysis, provider mode, graph/question-bank version, step/question/review lineage, and gate status (`learning_system/evidence_gate.py:44-113`).
- `EvidenceGate.validate_attempt` records validation results and predicate details (`learning_system/evidence_gate.py:130-202`).
- The dangerous gap is not the gate primitive; it is ensuring every evaluation, planner, report, summary, and self-evolution proposal consumes only gate-approved evidence.

Must decide in technical plan:

- The authoritative lineage chain: step -> attempt -> attachment/OCR -> model run -> answer_analysis -> evidence_validation -> evaluation_update -> next_step_decision -> summary.
- Freshness/version rules for reports and Codex queries.
- Rejection semantics for pending, blocked, stale, mock-only, and missing-lineage evidence.

### P1 - Model Adapter: Product Boundary Is Clear, Result Envelope Must Be Contracted

Product Structure isolates provider/model differences in a Model Router module (`...product_structure_v5.md:76`) and says configured model API calls must go through model adapter (`...product_structure_v5.md:233-240`). PRD v5 defines live/recorded/mock/pending/blocked policy and forbids mock-only semantic PASS (`docs/product/ai_native_math_learning_prd_v5.md:491-505`).

Remaining technical-plan risk:

- Existing `model_router.py` has separate routes for answer analysis, question design, evaluation, planner, teaching, and vision/OCR (`learning_system/model_router.py:119-176`) plus structured JSON fallback handling (`learning_system/model_router.py:305-345`).
- v5 still needs a normalized output envelope so model failures, JSON parse errors, low confidence, unsupported response formats, and provider metadata do not leak into business logic or child payloads.

Must decide in technical plan:

- Route-level timeout/retry/fallback policy.
- `live_model` / `recorded_model` / `mock_only` / `not_configured` / `blocked` labels and where they are stored.
- Model input/output snapshot policy, secret redaction, and replay fixture rules.
- Child-safe redaction of provider/model names and route errors.

### P1 - Child-Safe Boundary: Product Spec Is Sufficient, Implementation Must Use Allowlists

Product Structure is explicit that the son cannot see graph ids, question ids, attempts, provider/model, rubrics, queue/job state, or parent/operator controls (`...product_structure_v5.md:55-61`). It repeats that the child page must be free of internal ids, provider names, queue states, and Codex instructions (`...product_structure_v5.md:37-44`) and has an acceptance path requiring API/DOM scans (`...product_structure_v5.md:263`).

Remaining technical-plan risk:

- Existing v3 projection uses forbidden-term stripping/assertion (`learning_system/daily_runtime.py:30-51`) and projects child state from runtime rows (`learning_system/daily_runtime.py:402-460`).
- String filtering is not enough for v5 because model-generated prompt packages, teaching text, error messages, and route metadata can leak internals without containing an exact forbidden term.

Must decide in technical plan:

- Child API allowlist schema and per-state payload shape.
- Separate Codex/operator evidence endpoint from child endpoint.
- Automated DOM/API scans tied to PRD AC-24.
- Safe copy behavior for blocked/model/OCR failure states.

### P1 - Question Bank / Graph: Product Direction Is Ready, Target Selection Needs Engineering Ownership

Product Structure prevents full-bank model feeding and requires deterministic graph target prefiltering, bounded candidate packets, review lineage, age floor, evidence goal, and rejection summaries (`...product_structure_v5.md:195-208`). PRD v5 requires prerequisite rollback instead of blind same-type drill (`docs/product/ai_native_math_learning_prd_v5.md:427-449`) and names graph-bound semantic fixtures (`docs/product/ai_native_math_learning_prd_v5.md:401-426`).

Remaining technical-plan risk:

- Existing `QuestionBankService.candidate_packet_for_node` is a useful bounded-packet basis with lineage, exclusion, and hash fields (`learning_system/question_bank.py:167-272`).
- Current v3 daily runtime still selects the first eligible question, not a target pool from untested/weak/failed/due/prerequisite/new-learning nodes (`learning_system/daily_runtime.py:495-582`).

Must decide in technical plan:

- Source of learner node state and target pool construction.
- Initial seed nodes / 7-day path ownership. PRD keeps exact seed set open (`docs/product/ai_native_math_learning_prd_v5.md:597-603`), so 若命/听云 should keep it as a configurable product/engineering decision, not hard-code it silently.
- Candidate packet schema, hashing, lineage rejection, recent-use exclusion, and planner input limits.
- When same-structure retest, near-transfer, prerequisite probe, micro-teach, stretch, or summary wins.

### P1 - Test Architecture: Enough for Test Planning, Not Enough for QA PASS

PRD v5 provides semantic oracle fixtures, graph rollback fixtures, photo/OCR fixtures, day-level outcome oracle, and live/recorded/mock evidence policy (`docs/product/ai_native_math_learning_prd_v5.md:401-505`). Product Structure adds acceptance paths with evidence requirements (`docs/product/ai_native_math_learning_product_structure_v5.md:249-264`).

Remaining technical-plan risk:

- Existing tests include v3 skeleton coverage for schema, current-step submission, queue, evidence gate, child projection, model router, and browser smoke checks (`tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`), but they are not automatically v5 acceptance coverage.
- Addendum requires end-to-end traces for child submission, review pipeline, session close, model adapter, evidence lineage, and restart/retry (`docs/project-rules/system-architecture-learning-addendum.md:11-20`). It also says high-risk PASS needs at least two evidence types, such as tests plus DB/API/browser/code-path proof (`docs/project-rules/system-architecture-learning-addendum.md:34-44`).

Must decide in technical plan / test-source readiness:

- A v5 test matrix mapped to PRD AC-01 through AC-26.
- Same sample session traced across DB rows, API payloads, browser state, and report output.
- Separate test labels for state-machine mock tests versus recorded/live semantic oracle tests.
- Restart/retry/double-submit tests that prove no duplicate attempts, jobs, decisions, mastery updates, or summaries.

## Architecture Trace Checklist

| Addendum trace | Product readiness | Technical reverse / plan must verify |
|---|---|---|
| Child submission | Product path defined: current step -> attempt/attachment -> queued analysis -> pending child state (`...product_structure_v5.md:253-255`) | API route, DB write order, idempotency, upload cleanup, child projection |
| Review pipeline | Analysis/gate/evaluation objects and response modes defined (`...product_structure_v5.md:132-156`) | Worker handlers, normalized model output, `agent_run` audit, job finish/retry |
| Session close | Summary contract and day-level oracle defined (`...product_structure_v5.md:210-231`; `docs/product/ai_native_math_learning_prd_v5.md:466-489`) | Summary producer, freshness version, late evidence handling, no pending-as-mastery |
| Model adapter | Model Router module and model evidence labels defined (`...product_structure_v5.md:76`; `docs/product/ai_native_math_learning_prd_v5.md:491-505`) | Provider envelope, fallback, snapshot/redaction, failure label propagation |
| Evidence lineage | Trust/mastery split and data objects defined (`...product_structure_v5.md:173-193`, `...product_structure_v5.md:132-145`) | Gate forced at every consumer; stale/mock/missing lineage rejection |
| Restart/retry | Acceptance path defined (`...product_structure_v5.md:264`) | Lease recovery, missing-job reconciliation, completed-unapplied results, duplicate submit |

## Product Spec Fixes Required Before Next Stage

None.

There is one non-blocking improvement 若命 may choose later: add an explicit "Page / Surface Map" table to mirror the artifact contract. The current Product Structure already states one child Web surface, Codex query only, entry surfaces, and child-visible state model (`...product_structure_v5.md:16-23`, `...product_structure_v5.md:78-120`), so UX does not need to guess the surface boundary.

## Technical Plan Must-Decide List

1. Canonical persistent state machine: `daily_flow`, `flow_step`, `attempt`, `job`, `evidence_validation`, `next_step_decision`, `summary`.
2. Async queue lifecycle: job types, dependencies, idempotency, lease expiry, retries, dead letters, missing-job recovery, completed-unapplied reconciliation.
3. Model adapter contract: routes, provider modes, structured JSON fallback, confidence, blocked/pending semantics, recorded/live/mock labels, audit snapshot/redaction.
4. Evidence lineage contract: source ids, version/hash fields, stale detection, trust labels, and mandatory gate usage before evaluation/planning/reporting.
5. Child-safe projection contract: allowlist payloads, per-state schemas, operator/child route separation, API/DOM leak scans.
6. Question/graph selection: target pool, candidate packet, prerequisite rollback, recent-use exclusion, mastery threshold inputs, initial seed-set handling.
7. Report/query contract: child-safe summary vs Codex-readable evidence, freshness/versioning, stale report invalidation.
8. Test architecture: PRD AC mapping, semantic oracle fixtures, recorded/live model policy, DB/API/browser/restart evidence for the same session.

## Final Recommendation

Proceed with:

1. 清秋: `UX_FLOW_SPEC v5`.
2. 听云: `TECHNICAL_REVERSE_SPEC` / current architecture reconnaissance.
3. 听云: strict `ENGINEERING_SOURCE_READINESS` after UX/reverse inputs are present.
4. Only then: full `TECHNICAL_PLAN v5`, followed by `ENGINEERING_CONTRACT`, `IMPLEMENTATION_BLUEPRINT`, skeleton gate, test-case source readiness, and staged implementation.

Do not route this as an implementation-ready PASS. The product inputs are ready; the runtime architecture still has to prove recoverability.
