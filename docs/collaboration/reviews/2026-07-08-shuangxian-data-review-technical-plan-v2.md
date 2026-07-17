### DATA_REVIEW / PASS_WITH_SCOPE - 霜弦（agentKey: `shuangxian`）- 2026-07-08 11:20 CST

Verdict:
`DATA_REVIEW_PASS_WITH_SCOPE`. `docs/architecture/technical_plan_v2.md` correctly consumes `docs/architecture/data_contract_spec_v2.md` for the v2 architecture/package level and can proceed to skeleton/test design. Scope is limited to document and project-skeleton review; no implementation skeleton exists yet, and live model/content quality remains outside this gate.

independence_required:
yes

context_mode:
fresh

context_origin:
Prior data spec exists as source artifact, but this child context did not author it.

diff_pin:
Reviewed `docs/architecture/technical_plan_v2.md` against `docs/architecture/data_contract_spec_v2.md`.

Scope:
- DATA_REVIEW of technical plan and project skeleton definition only.
- Checked graph binding, question active-use gate, Python-only question spec migration staging, pending/invalidated/malformed evidence exclusion, photo/OCR evidence handling, self-evolution evidence boundary, report labels, and QA handoff.

Project boundary overlay:
- Applied `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`.
- Applied AGENTS.md boundary: graph-bound teaching, prerequisite rollback before same-topic drilling, no external/private content assumption, no destructive real-evidence deletion.
- Applied role-specific addendum `docs/collaboration/playbooks/data-learning-system-addendum.md`.

Data ops risk:
high. The plan covers child learning evidence, graph-bound question scheduling, model-backed answer analysis, photo/OCR evidence, async jobs, self-evolution, reports, and question-spec migration.

Fact sources:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/shuangxian.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/playbooks/data-learning-system-addendum.md`
- `docs/domain-index/math-learning.md`
- `docs/system/local_learning_system.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/system/qa/question_bank_grade_level_latest.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- Read-only key search in `learning_system/db.py`, `learning_system/question_bank.py`, `learning_system/auto_review.py`, `learning_system/model_router.py`, `learning_system/orchestrator.py`, `learning_system/planner.py`, and `learning_system/evolution.py`.

Lineage checked:

| Contract area | DATA_CONTRACT_SPEC requirement | Technical plan consumption | Review result |
|---|---|---|---|
| Graph binding | All teaching/question/attempt/evaluation/plan/evolution/report claims bind to known graph node ids; graph changes must not silently reinterpret old evidence. | Plan declares graph-bound question/attempt/evaluation/planning/evolution/report contracts, field-level `node_id` required/known, graph/hash/version fields in skeleton, prerequisite rollback in planner, and graph binding failure blocks closure. | Pass for plan/skeleton. Read-only graph check found 56 nodes with no missing prerequisite/unlock references. |
| Question active-use gate | Active questions need graph binding, current version, reviewer record, recomputed quality, Grade 7 reasoning, no metadata-only approval. | Plan states active eligibility requires graph binding, current version, recomputed reviewer approval, durable `question_review_records`; field contract treats missing `active_eligible` as inactive; contract tests require reviewer-record gate to override forged metadata. | Pass. This protects against metadata-only approval at plan level. |
| 20 slots/node and 10-task round | 56 nodes, 20 current high-quality active slots/node; active round is 10 tasks with Grade 7 reasoning-heavy challenge. | Plan carries 10-task round, 56*20 expected volume, current active question gate, picture-level quota in graph/evaluation/planner skeleton, and audit command. | Pass with scope. The source QA report is already `PASS_WITH_SCOPE`; final human/content-naturalness review remains required. |
| Python-only question spec migration | Migrate standards/families/rubrics/forbidden patterns only in staged review/parity path; Python gates must remain authoritative until parity. | Plan defines Stage 1 data files/loaders retaining Python gates, Stage 2 parity-load, Stage 3 retire constants only after tests/reviewer records; skeleton uses `QuestionSpecLoader` seam with Python quality gate as source of truth until parity approved. | Pass. Final migration format/stage remains an open decision and is not blocking because the plan preserves staging and parity. |
| Pending/malformed/invalidated/stale/fake evidence exclusion | Such evidence cannot drive mastery, planning, self-evolution, question activation, or reports. | Plan repeats exclusion in boundary, field contracts, call chain, compatibility, contract tests, behavior contract, skeleton modules, acceptance checklist, and rollback notes. It names `db.is_current_usable_attempt_evidence` as shared hard gate for evaluation/planner/evolution/report. | Pass for plan. Skeleton review must prove all consumers call the same predicate. |
| Photo/OCR evidence | Photo/OCR is untrusted; low confidence/no usable OCR remains pending unless written answer suffices; attachment evidence must be traceable. | Plan includes Doubao-compatible vision default through router, attachment file/metadata validation, photo OCR outside child request path, pending on low-confidence/malformed/no-route, and photo low-confidence semantic tests. | Pass. |
| Answer analysis lineage | Valid analysis requires structured `answer_analysis_agent` output, comparison/process gap, local validation, route metadata, no exact-answer-only mastery. | Plan requires `answer_analysis_json` before downstream claims, schema adapter/local validation, no-route/malformed pending, process-evidence guard, semantic tests for right-answer-wrong-reason and alternative valid methods. | Pass. |
| Self-evolution boundary | Evolution consumes only real active graded evidence with valid analysis and audit links; pending/malformed/invalidated evidence creates no action. | Plan specifies `evolution.run_evolution` consumes only usable analyzed evidence, no_action without valid evidence, audit-linked changes only, reviewer-gated evolved questions, invalidated-source exclusion, and evolution/invalidation tests. | Pass. |
| Report labels | Reports must separate confirmed, pending, inferred, stale/legacy/incomplete, blocked/missing; no overstatement from mocks/temp/samples. | Plan defines daily report labels `confirmed`, `pending`, `inferred`, `stale`, `blocked`, `missing`; call chain says reports label stale/pending/missing and never invent; tests include report labels. | Pass. |
| QA handoff | 观止 must derive tests for graph integrity, question gate, semantic model risk, async pending/recovery, self-evolution boundary, report labels, migration parity. | Plan marks TEST_CASE_SPEC required and lists API, state-machine, evidence usability matrix, router, semantic answer-analysis, question migration parity, browser, and report tests. | Pass. |

Samples/artifacts:
- Graph JSON read-only check: `.nodes | length` returned `56`.
- Graph JSON read-only check found `missingPrereq=[]` and `missingUnlock=[]`.
- Question bank audit source reports `1120` items, `56` nodes, `9/10` active-round picture-level tasks, live DB lineage issue count `0`, verdict `PASS_WITH_SCOPE`.
- Code fact search found existing symbols/tables/predicates aligned with the technical plan, including `question_review_records.active_eligible`, `attempts.evidence_status`, `answer_analysis_json`, `attempt_attachments`, `background_jobs`, `evolution_audits`, `is_current_usable_attempt_evidence`, invalidated-lineage repair, and active-question stale checks.

Findings:
- No P0/P1 data/content blockers found in `docs/architecture/technical_plan_v2.md`.
- No evidence that the plan bypasses `DATA_CONTRACT_SPEC`; it imports the central usability predicate and carries it through interface, field, call-chain, test, blueprint, skeleton, and gate handoff sections.
- No evidence that the plan bypasses staged question-spec migration; it keeps Python gates authoritative until loader parity and reviewer-record evidence are proven.
- No evidence that the plan treats generated question metadata as approval; durable reviewer records remain required.

Not covered:
- This review did not run implementation tests or browser tests.
- This review did not inspect rendered UI, live model output, OCR quality, or actual skeleton code.
- This review did not perform human教研 wording/taste review of all active questions.
- This review did not decide storage architecture or final question-spec file format.

Residual risk:
- When skeleton code is created, the main risk is accidental divergence: planner/evaluation/evolution/report may each implement their own partial evidence filters instead of calling one shared usability predicate.
- Question-spec loader work can silently weaken active-use gates if parity tests do not compare reviewer records, forbidden patterns, age floor, reasoning requirements, and old-attempt compatibility.
- Live model answer analysis still needs real/representative samples; deterministic tests cannot prove semantic grading quality.
- Report labels must be validated against real pending, stale, invalidated, and missing-analysis states, not only happy-path generated reports.

Required next action:
Proceed to skeleton/test design. At SKELETON_PASS, require another 霜弦 data/content review focused on executable skeleton fidelity: shared evidence predicate, graph/hash fields, reviewer-record gate, `QuestionSpecLoader` parity seam, photo/OCR pending path, invalidation propagation hooks, evolution audit links, and report evidence labels. Then 观止 should write TEST_CASE_SPEC from the skeleton before business logic fill.
