### DESIGN_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-08 11:20 CST

Verdict:
DESIGN_REVIEW_NEEDS_FIX

independence_required:
yes

context_mode:
fresh

context_origin:
no prior implementation/planning in this child context

diff_pin:
Reviewed the four source artifact files only for the design package: `docs/product/ai_native_math_learning_prd_v2.md`, `docs/product/child_ux_flow_spec_v2.md`, `docs/architecture/data_contract_spec_v2.md`, and `docs/architecture/technical_plan_v2.md`. No production code diff was reviewed.

Scope:
Independent design review of PRD-first restart package before project skeleton/test-case work proceeds. Focused on architecture coherence, state machine, async recovery, model adapter boundary, evidence lineage, child/operator separation, internal agent boundaries, and skeleton/test gate ordering.

Project boundary overlay:
Applied `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`: single child, incoming Grade 7 summer bridge, graph-bound teaching/evidence, 10-task async round, AI-first reasoning-aware grading, no parent dashboard, child-safe API boundary, no fake/pending evidence driving mastery/planning/evolution/reports, self-evolution only from real active graded analyzed evidence. Also applied `docs/project-rules/system-architecture-learning-addendum.md`.

Source artifacts:
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/architecture/technical_plan_v2.md`

Inputs reviewed:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/jinghua.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/inbox.md`
- `docs/domain-index/math-learning.md`
- `docs/system/local_learning_system.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- Targeted code reads for side-effect classification only: `scripts/init_learning_system_db.py`, `scripts/generate_daily_report.py`, `learning_system/db.py`, `learning_system/reports.py`

Commands:
- `ruby -ryaml -rjson -e '...'` to validate `jinghua` role YAML header against `docs/collaboration/agent-registry.json`
- `sed` / `nl -ba` / `rg` read-only inspection commands over the listed artifacts and fact sources
- Targeted read-only inspections of validation command side effects

Evidence:
- Identity validation passed: `jinghua` role header matches registry.
- The PRD/product structure is grounded in the project boundary and names the required PRD -> product structure -> UX/data -> technical plan/contract/blueprint -> skeleton -> review -> TEST_CASE_SPEC -> implementation -> QA order.
- UX spec covers child-visible states, all-10 submitted behavior, review summary, mobile/accessibility, and internal-term leakage checks.
- Data contract covers graph binding, reviewer-record active gate, attempt usability predicate, pending/malformed/invalidated/stale/fake evidence exclusion, model audit metadata, invalidation propagation, and report labels.
- Technical package largely preserves these constraints in architecture, engineering contract, implementation blueprint, and project skeleton definition.

Implementation fidelity:
No implementation was reviewed or changed. This is a pre-skeleton design review only.

Findings:
1. [P1] Child bootstrap contract still exposes graph-shaped fields inside the child API
   File: `docs/architecture/technical_plan_v2.md`
   Lines: 186
   Trigger: The child bootstrap response contract includes `today_plan{title, plan_key, tasks[position, kind_label, node_name, estimated_minutes, question{prompt, answer_format}, essence]}`.
   Impact: This contradicts the same technical package's child-safe rule that child state must never expose graph ids/internals, model/provider names, agent names, rubrics, OCR confidence, queue internals, or operator actions (`docs/architecture/technical_plan_v2.md:88-91`, `docs/architecture/technical_plan_v2.md:408-409`) and the UX/data boundary that the child surface consumes positions, kind labels, prompts/support, and review projections without backend graph concepts (`docs/product/child_ux_flow_spec_v2.md:18-22`, `docs/architecture/data_contract_spec_v2.md:168-177`). `node_name` is a graph-derived internal concept unless it is explicitly transformed into a child-safe learning label; `plan_key` is also not defined as child-safe or necessary for the child task flow. If the skeleton copies this DTO, it creates a child-safe API leakage before tests exist.
   Required fix: Before SKELETON_PASS work, revise the child bootstrap contract so the child DTO contains only child-safe presentation fields, for example `task_label`, `concept_support`, `prompt`, `answer_format`, `position`, progress, and the `current-learning-group` handle. Remove `node_name` and `plan_key`, or explicitly redefine them as opaque/child-safe fields with forbidden-value tests. Keep graph node ids/names and plan ids/keys on operator/Codex DTOs only.
   Validation: Add skeleton/API contract checks that `/api/child-bootstrap` has no raw ids and no graph-shaped field names or values (`node`, `node_id`, graph ids, internal plan ids/keys), while operator APIs still expose audit-rich ids.

2. [P2] Validation section labels mutating commands as read-only/pre-skeleton
   File: `docs/architecture/technical_plan_v2.md`
   Lines: 132-140
   Trigger: The technical plan lists `python3 scripts/init_learning_system_db.py` and `python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite` under "Read-only/pre-skeleton validation commands".
   Impact: Targeted code reads show `init_learning_system_db.py` opens `data/local_learning_system.sqlite`, initializes schema, seeds assets, retires sessions, repairs lineage, and can delete obsolete unattempted question/review rows through `cleanup_obsolete_question_bank`; `generate_daily_report.py` writes dated and `latest.md` report files. These may be valid implementation/QA commands, but they are not read-only. Mislabeling them can lead a later skeleton/test gate to mutate real local evidence or generated report artifacts without the backup/test-DB boundary required by the PRD and data contract.
   Required fix: Reclassify validation commands into read-only checks, test-DB setup, and mutating local artifact generation. For mutating commands, require an explicit test DB path or backup/real-evidence guard before running on `data/local_learning_system.sqlite`.
   Validation: The later SKELETON_PASS / TEST_CASE_SPEC should state which commands are safe read-only and which are permitted mutating commands, with test DB or backup evidence when the command touches local evidence.

Not covered:
- No rendered UI, screenshots, browser behavior, or visual taste review.
- No live model calls or semantic output quality audit.
- No DB/API/runtime execution of the future v2 skeleton.
- No production code review.
- No QA PASS or TEST_CASE_SPEC review.

Residual risk:
The package is otherwise coherent and well grounded for a high-risk local single-child learning system, but it remains a design artifact. Actual PASS will depend on skeleton evidence showing the child/operator separation, explicit state machine, background recovery, model adapter isolation, shared evidence usability predicate, and false-pass-resistant tests in code.

Required next action:
听云/若命 should fix the child DTO leakage and validation-command classification in the technical package before proceeding to SKELETON_PASS planning. After fixes, rerun 镜花 design review or provide a scoped addendum showing the corrected lines.
