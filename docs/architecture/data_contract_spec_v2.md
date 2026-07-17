### DATA_CONTRACT_SPEC - 霜弦（agentKey: `shuangxian`）- 2026-07-08 05:00 CST

Objective:
Define the planned data/content/evidence contract for the next implementation cycle of the single-child AI-native math learning system. The contract covers graph-bound teaching data, question specs/bank, child attempts, answer analysis, background jobs, model outputs, planner/evaluation evidence, self-evolution, and Codex-facing reports. It is concrete enough for 听云 to design schema/service/async/model contracts and for 观止 to derive data/artifact tests, while staying out of implementation architecture choices.

Source product structure:
- `docs/product/ai_native_math_learning_prd_v2.md`: `PROJECT_BOUNDARY_OVERLAY`, `PRD_SPEC`, and `PRODUCT_STRUCTURE_SPEC`.
- `AGENTS.md`: graph-bound teaching rule, prerequisite rollback rule, no private/commercial question content, no destructive real-evidence deletion.
- `docs/domain-index/math-learning.md`: current domain contract and graph/evidence invariants.
- `docs/system/local_learning_system.md`: current local system v1.6 data and evidence behavior.
- `docs/system/qa/question_bank_grade_level_latest.md`: current question bank grade-level audit, PASS_WITH_SCOPE, `QB11` / `2026-07-08.bank.v11`, 1120 active test/audit items, 56 nodes, active round 2/10 controlled picture-level tasks and 8/10 node-local mainline tasks.
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`: 56 graph nodes, prerequisites/unlocks, diagnosis/teaching/question/error contracts.
- Current code facts from `learning_system/db.py`, `learning_system/question_bank.py`, `learning_system/auto_review.py`, `learning_system/model_router.py`, `learning_system/orchestrator.py`, `learning_system/planner.py`, and `learning_system/evolution.py`.

Scope:
- Planned data meaning, source-of-truth rules, field/rule contracts, lineage, sample/oracle requirements, overwrite/invalidation boundaries, and engineering/QA handoff.
- Graph-bound teaching content, question production/review, learner evidence, async review work, model audit outputs, planner/evaluation evidence, self-evolution audit, and reports.
- Requirement to migrate standards, question families, rubrics, quality criteria, and forbidden patterns out of Python-only content where feasible, staged behind reviewable data specs/loaders.

Forbidden scope:
- Do not edit production implementation code.
- Do not choose storage architecture, queue architecture, API shape, or service design beyond data meaning and evidence constraints.
- Do not import, copy, or authorize private/commercial textbook, workbook, or question-bank content.
- Do not authorize destructive deletion of real attempts, uploads, model outputs, question rows, review records, or evolution/report evidence.
- Do not treat photo samples as content sources. They are calibration only.

Project boundary overlay:
- Single-child private math learning system for summer bridge: primary prerequisite gaps plus Grade 7 preview.
- Every teaching, diagnosis, question, attempt, answer analysis, evaluation, plan, self-evolution event, and report claim must bind to known math graph node ids.
- Active round size target is 10 tasks.
- Each graph node target is 20 active high-quality question slots, not historical rows or metadata-only approval.
- Each graph node must preserve a node-local mainline evidence floor. Picture-level / competition-style tasks are controlled stretch probes, not coverage filler.
- Target level is incoming Grade 7. Valid tasks require observable reasoning such as model, relation, step, check, counterexample, proof, representation, or error diagnosis.
- Low-age mechanical drills are forbidden unless recent valid evidence shows a narrow repair need.
- Pending, malformed, low-confidence, simulated, stale, invalidated, or fake-model evidence cannot drive mastery, planning, self-evolution, question activation, or reports.
- Reference answers and rubrics are context for AI-first reasoning-aware evaluation, not exact-answer truth.
- A correct final answer with missing, lucky, circular, or wrong reasoning is not full mastery.
- Reviewer records and active-use gates matter. Generated question metadata alone cannot prove approval.
- External content sources remain unauthorized unless the user explicitly provides or approves them.
- Codex is only an operator/query surface. Generated teaching, grading, planning, evolution, review, and report outputs must be persisted to SQLite rows or report artifacts before Codex summarizes them; separate Codex sessions/threads are not valid result storage.

Data objects:
| Object/artifact | User/business meaning | Source of truth | Owner | Protected/manual? |
|---|---|---|---|---|
| Knowledge graph node | Teachable math capability and dependency anchor | `math_knowledge_graph_v2.json` plus seeded `graph_nodes`/`graph_edges` | Graph/data owner, reviewed by 霜弦 | Protected domain scaffold; graph changes invalidate dependent evidence by policy |
| Graph edge/prerequisite chain | Rollback and unlock path for weak evidence | `prerequisites`, `unlocks`, `edges`, `prerequisite_edges` | Graph/data owner | Protected teaching logic |
| Teaching contract per node | Node-level essence, model, lesson flow, output expectation | Graph `teaching_contract`, `diagnosis_contract`, `question_generation`, `error_diagnosis` | Graph/data owner | Protected content rule |
| Question standard/family/spec | Reusable pattern for high-signal Grade 7 task generation | Planned external data spec; currently partly in graph and Python constants | 霜弦 contract, 听云 implementation | Protected content; no private/commercial copying |
| Question item | Concrete child task candidate or released item | Versioned question bank row/data item plus `question_review_records` | Question designer/reviewer workflow | Protected; child sees sanitized prompt only |
| Question review record | Durable approval/rejection evidence for active use | Reviewer record recomputed from quality rules | `question_reviewer_agent` gate | Protected audit; cannot be forged by item metadata |
| Learning plan / plan task | Next 10-task child group selected from evidence | Planner output using current active questions and valid evidence | `planner_agent` | Protected internal plan; child sees positions/prompts only |
| Learning session | One child learning group and closure state | Session record with expected question ids and closure result | `session_orchestrator_agent` | Protected evidence container |
| Attempt | Child answer evidence for one task | Child/operator submission persisted as attempt | Child submission path plus answer analysis workflow | Protected child evidence; may include uploads |
| Attempt attachment | Answer photo evidence and local file metadata | Attachment row plus local answer upload file | Child submission path | Protected local child data |
| Answer analysis | Structured reasoning-aware judgment | `answer_analysis_agent` output validated locally | Answer analysis workflow | Protected evidence; not child raw backend text |
| Background job | Durable async review/recovery work item | Job ledger for answer review | Async worker/orchestrator | Operational evidence |
| Model route/output audit | Provider/model/schema/prompt/confidence audit for model calls | `agent_runs`, review meta, route resolver metadata | Model-routed agents | Protected; no secrets |
| Learner node status | Derived mastery summary by graph node | Valid current graded attempts with valid answer analysis | `evaluation_agent` / reducer | Derived evidence, never manual truth |
| Mastery decision | Session-level applied or unapplied decision | Evaluation package and `mastery_decisions` | `evaluation_agent` | Derived audit |
| Evolution event/audit | Evidence-driven change in status, profiles, or questions | Valid processed attempts plus `evolution_events`/`evolution_audits` | `self_evolution_agent` | Protected audit, append/versioned |
| Agent run/handoff/session step | Internal evidence chain for hidden teaching agents | Agent audit tables / packages | Internal agents | Protected operator evidence |
| Daily/progress report | Codex-readable parent progress surface | DB/API/report script evidence | Codex/report workflow | Report must label confirmed, pending, inferred, stale |
| Codex query result | Parent asks Codex for progress or issues | Derived from DB/API/report artifacts at query time | Codex/operator workflow | Not protected source evidence; must not replace persisted rows/reports |

Field / rule contracts:
| Field/rule | Source | Type/allowed values | Required/default | Null/old-data handling | Priority/conflict rule | Consumers |
|---|---|---|---|---|---|---|
| `node_id` on teaching/question/attempt/plan/evidence/report item | AGENTS, PRD, graph JSON | Known graph node id | Required for all teaching/evidence artifacts | Unknown node blocks active use and report mastery claims | Graph source wins over generated payload | Question bank, attempts, planner, reports |
| `prerequisites` / rollback candidates | Graph JSON, domain index | List of known node ids with relation meaning | Required for Grade 7 weakness rollback | Empty allowed only for root/process nodes | Grade 7 wrong answer checks prerequisite chain before same-topic drilling | Planner/evaluation |
| Graph version/hash | Local system doc, seeded assets | Hash/version string | Required on seeded evidence batches | Missing hash marks lineage incomplete | New graph version must not silently reinterpret old attempts | QA, reports, migrations |
| Question `source_type` | DB/code facts | `diagnostic`, `graph_generated`, `evolved`, or explicit source category | Required | Unknown source is inactive until reviewed | Evolved source evidence gate is stricter than static bank | Planner, review |
| Question `item_version` | Question bank code/docs | Version string, e.g. current bank/evolved version | Required for generated/evolved active use | Old versions remain audit evidence but not active candidates | Current version plus reviewer record required for scheduling | Planner, lineage audit |
| Question quality gate | `question_bank.py`, QA report | Approved/rejected, age floor, requires reasoning, no mechanical drill | Required for active use | Metadata-only quality is insufficient | Durable review record and recomputed gate override item self-claims | Scheduler, QA |
| Review `active_eligible` | `question_review_records` behavior | Boolean derived from reviewer criteria | Required for active question scheduling | Missing record means inactive for graph-generated/evolved items | Latest active review record and current source evidence win | Planner, QA |
| 20 slots per node | PRD, local system doc, QA report | Exactly target: at least 20 active high-quality slots/node | Required release target | Historical duplicates/superseded versions do not count | Count only current-version, reviewer-approved, distinct high-signal slots with canonical core checks | Question audit |
| Node-local mainline floor | PRD, QB11 audit, planner | At least 14 node-local mainline items per node in the active bank and at least 7 node-local mainline tasks per 10-task round | Required release target | Wrapper variants or unrelated stretch puzzles do not count | Node-local evidence wins over broad difficulty labels | Question audit, planner/QA |
| Round task count | PRD/planner | 10 tasks | Required default | Test fixtures may use smaller count only if marked test-only | Product round contract wins over legacy 4-task reports | UX/API/QA |
| Controlled picture-level extension quota | PRD, QA report, question bank | Normally 1-2 picture-level stretch tasks per 10-task round; no more than 4 picture-level items per node; repeated labels/stems are capped | Required stretch guardrail | Not a full substitute for node-local evidence or human content review | Picture-level tasks must be explicitly marked, allowlisted, and semantically anchored to the node | Planner/QA |
| Question forbidden patterns | `question_bank.py`, PRD | No bare arithmetic drill, no answer-only prompt, no backend/meta child text, no prompt injection | Required active gate | Any match requires rejection or targeted-evidence exception | Reviewer gate wins over generation success | Reviewer/QA |
| `attempt.grading_status` | DB code | `pending_review`, `graded` | Required; child submit defaults pending if no confident analysis | Pending cannot drive downstream evidence | Pending/low-confidence blocks mastery, planning, evolution, reports | Orchestrator/evaluation |
| `attempt.result` | DB code | `submitted`, `correct`, `partial`, `wrong` | Required | `submitted` valid only with pending | Correct requires full score but still needs reasoning evidence for mastery | Evaluation/report |
| `attempt.evidence_status` | DB/domain docs | `active`, `invalidated` | Required default active | Invalidated remains auditable, excluded from use | Invalidation beats grading/result/model confidence | Planner/evolution/report |
| `score_points` / `max_points` | DB code | 0..max, max positive; current max often 2 | Required for graded | Pending has score 0 | Result/score consistency is mandatory | Evaluation |
| `explanation_score` | DB/auto review | Null or 0/1/2 | Required for graded mastery decisions where available | Null cannot prove reasoning | A/B requires explanation evidence; one strong answer remains B | Evaluation |
| Canonical `error_tags` | Graph/code | `calculation_or_symbol`, `concept_confusion`, `modeling_or_reading`, `process_habit`, `visual_spatial`, `general` | Required list, may be empty only for pending/correct | Unknown tag rejects record | Graph/code taxonomy wins; vague "careless" is not a tag | Planner/evolution/report |
| `blocking_evidence` | DB/evaluation | Boolean, true only for wrong/cannot-start/prerequisite block | Default false | Pending cannot be blocking | D status requires explicit blocking or verified prerequisite-chain failure | Evaluation/planner |
| `answer_analysis.agent_key` | DB validation | Must be `answer_analysis_agent` | Required for valid analysis | Missing/malformed blocks downstream use | Local schema validation wins over model text | Evaluation/planner/evolution |
| `answer_analysis.comparison` | DB/auto review | Non-empty list over dimensions `final_answer`, `model_or_relation`, `steps`, `symbols_units`, `check_or_explanation`, `other`; statuses `matched`, `missing`, `incorrect`, `unclear`, `alternative_valid` | Required | Empty/malformed blocks downstream use | Process dimensions are evidence, not decoration | Evaluation/teaching |
| `answer_analysis.process_gap` | DB/auto review | Specific teachable gap string | Required string; may be empty only when no meaningful gap exists | Vague/missing gap cannot drive weak-evidence evolution | Exact gap beats generic error tag | Teaching/evolution/planner |
| Photo OCR evidence | PRD/auto review | Status, confidence, transcript, math objects, notes | Required when photo is used | Low-confidence/no usable OCR keeps attempt pending unless written answer suffices | OCR is untrusted input, not ground truth | Answer analysis |
| Model route metadata | Model router/local docs | provider, model, alias, params, prompt/schema ids/hashes, confidence, validation errors | Required for model-backed outputs | Missing route metadata scopes or blocks live-model evidence claim | No API keys in output; local validation wins | QA/report/audit |
| Background job status | DB/local docs | `queued`, `running`, `succeeded`, `waiting`, `error` | Required for async review | Stale running jobs require recovery evidence | Active pending jobs prevent closure/evolution | Orchestrator/QA |
| Session closure status | Orchestrator | `not_started`, `waiting_ai`, `blocked`, `evolving`, `planned`/closed result as implemented | Required | Legacy closure without full chain is lineage incomplete | Missing attempts, pending review, or missing analysis blocks closure | Child UI/report |
| Learner status | Graph diagnosis model/code | A/B/C/D with evidence-backed reason | Derived only | Delete/recompute derived status if no valid source evidence remains; do not delete attempts | Valid current attempts with analysis override stored stale status | Planner/report |
| Evolution status | Evolution code/docs | `no_action`, `state_updated`, `question_review_rejected`, `evolved`, plus audit-specific invalidated/stale states | Required for events | No analyzed evidence records no_action | Created questions need valid source evidence and reviewer gate | Planner/report |
| Report evidence label | PRD/domain/report docs | confirmed, pending, inferred, stale/legacy/incomplete, blocked | Required for claims | Unknown is preserved, not filled in | Report cannot overstate from mocks/temp DB/sample-only facts | Parent/Codex |

Lineage / flow:
| Source | Producer | Transform | Destination/consumer | Fallback | Verification sample |
|---|---|---|---|---|---|
| Graph JSON node/contracts | Asset seeding/graph loader | Seed `graph_nodes`/`graph_edges`; preserve raw node contract | Planner, question generation, evaluation, reports | Block unknown node refs; keep old evidence auditable under old graph hash | `jq '.nodes | length'` is 56; node has prerequisites/unlocks/contracts |
| Graph node + question family/spec | Question designer or seeded bank | Create candidate with node, kind, target evidence, rubric, rollback candidates | Reviewer gate | Reject if unknown node, low signal, private source, forbidden pattern, low confidence | Per-node 20 approved current slots with distinct high-signal signatures |
| Candidate question | Question reviewer | Recompute quality; write review record | Active scheduler | Reject, keep audit, do not schedule | Review record has active_eligible=true only when approved and Grade 7 reasoning gate passes |
| Active question + plan signal | Planner | Select 10 tasks using current active bank, weak evidence, prerequisite chain, recent avoidance | Child learning group | Regenerate plan if stale/superseded/duplicate/missing evidence | Plan has 10 unique current approved question ids, at least 7 node-local mainline tasks, and 1-2 controlled picture-level stretch tasks when available |
| Child typed/photo answer | Child submission | Store attempt pending/graded; store attachment metadata; queue job | Background review/orchestrator | Pending with reason if no model, low confidence, bad photo, malformed model output | Attempt pending does not change learner status or evolution |
| Pending attempt + background job | Async reviewer | Run OCR if photo, model answer analysis, local validation | Graded attempt with answer_analysis or pending/error job | Retry transient errors; waiting/error remains auditable | Job status and attempt review_meta explain pending reason |
| Graded attempt + valid answer_analysis | Orchestrator/flow nodes | Build evidence package, answer package, graph binding package | Evaluation, teaching, planner | Block closure if missing attempts, pending review, or missing analysis | Session steps contain evidence_package, answer_analysis_package, graph_binding |
| Valid analyzed attempts | Evaluation reducer | Derive status, mastery decision, cause analysis | Learner status, planner, reports | no_action or blocked if evidence invalid/malformed | A needs repeated strong evidence; one strong correct remains B |
| Weak analyzed evidence | Self-evolution | Propose profile/rule/status changes and evolved retest candidate | Question reviewer and planner | no_action if pending/missing; fallback candidate only through reviewer gate | Evolution audit links attempts, before/after, created question ids, review record ids |
| Invalidated attempt | Operator/Codex authorized path | Mark evidence invalidated; invalidate dependent evolved questions; recompute derived status | Planner/report/lineage audit | Never destructive-delete real evidence | Lineage audit has zero active attempts on invalidated-source questions |
| Agent run/model output | Internal agents/model router | Record prompt/schema/model/output digest/validation/confidence | QA/report/debug | Scoped claim if deterministic/fake/no route | Agent run has provider/model only when real route enabled; no secrets |
| DB/API evidence | Report generator/Codex | Summarize progress, pending jobs, weak nodes, next plan, system issues | Parent via Codex | Mark stale/unknown instead of inventing | Report distinguishes complete lineage vs missing phases/pending |

Templates / imports / exports:
- No external textbook, workbook, or commercial question import is authorized.
- User-provided photo samples are difficulty calibration only and must not be copied as prompts, expected answers, or hidden solutions.
- Move standards/families/rubrics/forbidden patterns out of Python-only content where feasible:
  - Stage 1, proposed not implemented here: define reviewable data specs for question families, process-evidence requirements, forbidden surface patterns, rubric dimensions, age-floor criteria, picture-level challenge labels, and per-node slot targets.
  - Stage 2: implement a loader/validator that produces the same runtime semantics while preserving current active gates.
  - Stage 3: retire duplicated Python-only constants only after tests prove parity and reviewer records/active-use gates still work.
- Any migration must preserve current versions and keep old attempted items as audit evidence. It must not silently rewrite real attempts or existing reports.
- Generated reports are Codex/operator artifacts; child-facing exports must contain only child-safe fields.
- Codex query responses are derived views over stored evidence. They are allowed to explain or summarize but must not become the only place where generated results live.

External platform rules:
- Not applicable for publishing/importing to external education platforms in this cycle.
- External model calls are allowed only through configured model routes and compatibility adapters.
- API keys and secrets must remain in environment or ignored local config and must never be written into docs, reports, agent runs, or model audit output.

Overwrite / manual boundaries:
- Real evidence is append/version/invalidate, not destructive-delete.
- Attempts, attachments, agent runs, question review records, evolution events, evolution audits, and reports are protected audit evidence.
- `evidence_status=invalidated` is the approved boundary for wrong or superseded evidence; invalidated attempts remain inspectable and cannot drive learner status, planner, evolution, active evolved questions, or reports.
- Superseded current bank/evolved versions remain historical evidence, but active scheduling must use current version and reviewer-approved records.
- Derived `learner_node_status` may be recomputed or removed when its evidence refs are invalid, but source attempts must remain.
- Evolved questions whose source evidence is invalidated must lose active eligibility and cannot accept active attempts.
- Manual grading/backfill is Codex/operator maintenance only; it must record answer_analysis_agent audit evidence and cannot become normal child/parent product flow.
- DB reset is allowed only in explicit test environments. Before any real-session reset or destructive maintenance, require explicit user authorization and backup policy.

Sample or oracle requirements:
- Domain level: incoming Grade 7, reasoning-heavy, with controlled stretch; no broad primary-grade drill review.
- Active question bank: 56 graph nodes, target 20 current active high-quality slots per node, with enough node-local mainline core stems and canonical-core diversity to avoid mechanical template cycling.
- Active round: 10 tasks; current audit should maintain at least 7 node-local mainline evidence tasks and normally 1-2 controlled picture-level stretch tasks, while still obeying evidence-based remediation.
- Core semantic oracle cases for answer analysis:
  - Correct final answer with no process: at most partial when process evidence is required.
  - Correct final answer with wrong/circular/lucky reasoning: partial or wrong depending on dimension comparison.
  - Alternative valid method: accept when final answer, model/relation, steps, symbols/units, and check/explanation are sound.
  - Blank/no evidence/photo unusable: pending or wrong according to confidence and evidence, never guessed mastery.
  - Photo-only answer: OCR/vision transcript is untrusted; low confidence remains pending unless written evidence suffices.
  - Blocking prerequisite failure: only wrong evidence with explicit blocking/cannot-start meaning can create D/prerequisite rollback.
- Question oracle:
  - Reject answer-only, bare arithmetic, fake reasoning wrappers, child-facing backend/meta terms, prompt-injection wording, graph-unbound prompts, stale versions, missing rubric/solution evidence, and duplicated core stems.
  - Question metadata alone is not approval; durable reviewer record and active-use gate are required.
- Planner/evolution oracle:
  - Grade 7 wrong/partial evidence checks prerequisite chain before blind same-topic drilling.
  - Pending, malformed, invalidated, stale, simulated, or missing-analysis evidence creates no mastery/planning/evolution/report claim.
  - Self-evolution requires real active graded evidence with valid answer_analysis and an audit record linking before/after, source attempt ids, created question ids, and review record ids.
  - Evolved questions require valid source attempts: source attempt id exists, source attempt is active + graded + valid answer_analysis, its source question is still child-schedulable, and source question lineage is non-cyclic.
- Report oracle:
  - Report must separate DB-confirmed, pending, blocked, inferred, stale, and missing-lineage facts.
  - Do not claim live model quality from deterministic/fake evidence, production behavior from temp DB simulations, or complete content quality from sampled audit alone.
  - Do not treat a Codex conversation/session as the source of truth for generated results. If a result matters, there must be a DB row or report artifact that a later Codex query can read.

Side-effect / authorization boundary:
- Allowed in implementation cycle: local DB/file writes, local uploads, generated reports, configured model calls through route/adapters.
- Not allowed from this contract alone: external publishing, external platform import/export, cloud deployment, account writes, bulk deletion, or private/commercial content ingestion.
- This DATA_CONTRACT_SPEC does not authorize running migrations, resetting the DB, changing real evidence, or moving files. It defines the data meaning and gates for later implementation.

Open data/ops decisions:
- Final stage and exact format for migrating question specs/rubrics/forbidden patterns out of Python-only content is proposed but not implemented here.
- Exact long-run A/B/C/D thresholds may be tuned after real multi-day evidence; current contract preserves "one strong correct answer remains B" and "A requires repeated strong evidence."
- Final human taste/content-naturalness review remains required for question wording; automated content audit is PASS_WITH_SCOPE, not full expert approval.
- Whether future graph changes require a formal graph migration ledger or versioned compatibility adapter is an engineering decision for 听云, but the data rule is fixed: graph changes must not silently reinterpret old attempts.

Engineering / QA handoff:
- 听云 should design schemas/services/async/model contracts so every downstream consumer can test these gates without guessing:
  - graph id existence and graph version/hash on seeded content/evidence batches;
  - question active eligibility requiring current version plus durable reviewer record;
  - attempt usability predicate: active + graded + valid answer_analysis + current active question;
  - pending/malformed/invalidated evidence exclusion from mastery, planner, evolution, and reports;
  - invalidation and source-attempt validity propagation from source attempt to evolved questions, review records, active attempts, learner status, and reports;
  - model audit metadata with no secrets and local validation of structured JSON;
  - background job recovery and explicit pending/error reasons;
  - child-safe projection that hides internal ids, rubrics, graph/debug/model/agent internals.
- 观止 should derive tests/artifact checks for:
  - graph reference integrity and prerequisite rollback;
  - per-node 20-slot active question coverage, node-local mainline floor, controlled picture-level caps, and 10-task round selection;
  - reviewer-record active gate vs metadata-only claims;
  - answer-only/right-answer-wrong-reason/photo-low-confidence semantic samples;
  - async pending/retry/recovery and no fake grading when model route is disabled;
  - self-evolution no_action for pending/malformed evidence and audit-linked evolution for valid weak evidence;
  - reports that label pending/stale/missing lineage and do not overstate mocks or sampled audits;
  - migration parity if question standards/families/rubrics/forbidden patterns move out of Python-only content.
- 镜花 review should later verify that implementation does not turn this data contract into storage-only validation while bypassing state-machine, recovery, model adapter, or child-safe boundaries.

Stop condition:
This DATA_CONTRACT_SPEC is complete when downstream roles can implement and test graph-bound content/evidence behavior without inventing data meaning: active questions require graph binding, current version, reviewer records, and quality gates; attempts become usable only when active, graded, and structurally analyzed; pending/malformed/invalidated/stale/fake evidence cannot drive mastery, planning, evolution, or reports; invalidation is non-destructive and propagates through derived artifacts; reports and QA can trace every claim back to graph nodes and source evidence.
