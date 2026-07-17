# PRD v5 Clean-Slate Multi-Role Review

Status: PASS_FOR_PRODUCT_STRUCTURE; NOT_ENGINEERING_SOURCE_READY
Owner: 若命 (`ruoming`)
Date: 2026-07-11 CST

Scope:

- `docs/product/ai_native_math_learning_prd_v5.md`

Source policy:

- Clean-slate review.
- Prior PRDs, prior product structures, prior technical plans, and prior review
  reports are not sources for this review.
- Reviewers used only PRD v5 plus current project boundary files and role
  playbooks.

## Review Summary

| Role | Initial verdict | Final verdict | Result |
|---|---|---|---|
| 清秋 (`qingqiu`) | `UX_INPUT_NEEDS_FIX` | acceptable for PRD stage | PRD correctly routes final UX details to `PRODUCT_STRUCTURE_SPEC v5` and `UX_FLOW_SPEC v5`; missing step taxonomy, response matrix, visible action boundaries, and summary fields must be defined next. |
| 听云 (`tingyun`) | `ENGINEERING_INPUT_READY` | `ENGINEERING_SOURCE_NEEDS_FIX` | Prior wording used a non-standard gate label and was too broad. PRD v5 is sufficient only for 若命 to write `PRODUCT_STRUCTURE_SPEC v5`; it is not sufficient for a full `TECHNICAL_PLAN v5` until product structure, UX flow, data contract, codebase reconnaissance, architecture context, validation targets, and explicit technical-plan authorization exist. |
| 镜花 (`jinghua`) | `ARCHITECTURE_INPUT_READY` | `ARCHITECTURE_INPUT_READY` | Runtime boundary, internal-agent boundary, evidence chain, child-safe projection, recovery, and trust labels are coherent enough for downstream architecture planning. |
| 观止 (`guanzhi`) | `TEST_INPUT_NEEDS_FIX` | `TEST_INPUT_READY` | 若命 added semantic oracle, graph rollback, photo/OCR, day-level, and live/recorded/mock evidence policy sections. `TEST_CASE_SPEC v5` can now be written without inventing acceptance paths after downstream structure/UX/technical targets exist. |

## Fixes Applied During Review

Updated `docs/product/ai_native_math_learning_prd_v5.md`:

- Added `Minimum Semantic Oracle Fixtures`.
- Added `Required Graph Rollback Fixtures`.
- Added `Required Photo / OCR Fixtures`.
- Added `Day-Level Outcome Oracle`.
- Added `Live / Recorded / Mock Evidence Policy`.

Updated routing metadata:

- `docs/project-index.md` now points current product baseline to PRD v5.
- `docs/domain-index/math-learning.md` marks PRD v5 as current and PRD v2/v3/v4
  as historical, not current product sources.
- PRD v4 and Product Structure v4 are marked historical archives.

## Engineering Readiness Correction

The initial 听云 verdict used `ENGINEERING_INPUT_READY` too loosely. Under
`docs/collaboration/roles/tingyun.md` and
`docs/collaboration/playbooks/engineering-execution.md`, a full
`ENGINEERING_SOURCE_READINESS` gate for `TECHNICAL_PLAN v5` is currently:

- verdict: `ENGINEERING_SOURCE_NEEDS_FIX`
- allowed scoped output: readiness review, blocker/question list, or authorized
  codebase reconnaissance / `TECHNICAL_REVERSE_SPEC`
- not allowed: full `TECHNICAL_PLAN`, `ENGINEERING_CONTRACT`,
  `IMPLEMENTATION_BLUEPRINT`, `SKELETON_PASS`, tests, implementation, or
  `DONE_CLAIMED`

| Field | Current status | Evidence / reason |
|---|---|---|
| product_scope_ready | yes | PRD v5 defines users, scope, non-goals, acceptance, failure/recovery, and model/content quality bar. |
| product_structure_ready | no | `PRODUCT_STRUCTURE_SPEC v5` does not exist yet; modules, flows, states, permissions, data-object relationships, and acceptance paths are not executable enough. |
| ux_flow_ready | no | `UX_FLOW_SPEC v5` does not exist yet; child-visible flow, copy tone, state behavior, photo/stuck/waiting UX, and responsive/accessibility rules are not fixed. |
| data_contract_ready | no | PRD names domain objects but does not define field contracts, producers/consumers, old-data/null handling, side effects, or storage/report split. |
| project_boundary_ready | yes | The product boundary is clear: one child, math first, graph-bound teaching, no parent dashboard, no fixed worksheet, no automatic mutating self-evolution. |
| codebase_recon_ready | no | 听云 has not yet produced current code/runtime reconnaissance for v5 planning. |
| architecture_context_ready | no | Existing routes, APIs, DB schema, queues/jobs, model adapters, config, tests, and recovery behavior still need verification. |
| authorization_ready | no | Current routing authorizes product structure next, not full technical planning or implementation. |
| validation_targets_ready | no | QA oracle seeds exist in PRD, but executable test targets require product structure, UX flow, engineering contract, skeleton/code targets, and fixture policy. |

Correct routed output:

- Allowed now: 若命 writes `PRODUCT_STRUCTURE_SPEC v5`; 清秋 can prepare `UX_FLOW_SPEC v5` after product structure; 听云 may produce a scoped `TECHNICAL_REVERSE_SPEC` or reconnaissance notes.
- Not allowed now: full `TECHNICAL_PLAN v5`, `ENGINEERING_CONTRACT`, `IMPLEMENTATION_BLUEPRINT`, `SKELETON_PASS`, implementation, or `DONE_CLAIMED`.
- Retry condition for 听云 technical planning: `PRODUCT_STRUCTURE_SPEC v5` and required `UX_FLOW_SPEC v5` exist, project/data/model boundaries are explicit, codebase reconnaissance is complete, validation targets are named, and 若命 authorizes technical planning.

## Subagent Rereview After User Challenge

听云 strict rereview:

- PRD v5 alone is not sufficient for a complete `TECHNICAL_PLAN v5`.
- Formal gate result: `ENGINEERING_SOURCE_NEEDS_FIX`.
- Missing sources: `PRODUCT_STRUCTURE_SPEC v5`, `UX_FLOW_SPEC v5`, data
  contract, codebase reconnaissance, architecture context, validation target
  map, and explicit authorization to write the technical plan.

镜花 independent review:

- `ENGINEERING_INPUT_READY` was not a legal 听云 gate label and created
  false-pass risk.
- The review content was scoped cautiously, but the label could be misread as
  `ENGINEERING_SOURCE_READY`.
- This report now treats the earlier label as superseded by the stricter
  formal gate above.

## Validation

Commands:

```bash
python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/validate_collaboration.py --project . --profile full
rg -n "ai_native_math_learning_prd_v[234]|technical_plan_v3|product_structure_v4|prd_v4|Review log|Supersedes" docs/product/ai_native_math_learning_prd_v5.md
```

Results:

- Collaboration validation: PASS after the readiness correction and runtime
  bootstrap marker patch.
- PRD v5 contains no old PRD / old product structure / old technical plan path
  references.
- Repository note: this directory is not a git repository, so `git status` is
  unavailable here.

## Next Required Artifact

若命 must write `PRODUCT_STRUCTURE_SPEC v5` next. It must define the missing
product-structure details that PRD intentionally routes downstream:

- step taxonomy
- response-mode matrix
- child-visible state/action boundaries
- data-object relationships
- summary field split between child-safe and Codex-readable output
- acceptance paths mapped from PRD v5
