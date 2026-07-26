### TEST_CASE_SPEC - 观止（agentKey: `guanzhi`）- 2026-07-14 15:10 CST

Objective:

为 v5.1 实施建立可执行的前置红测规格，覆盖答案合同、确定性评分、单次语义调用、OCR、澄清/重评、1,120 题合同激活、双知识视图、target intent、恢复、浏览器、泄漏与日报 lineage。

Scope:

- Answer assessment v5.1 的合同、存储、评分、EvidenceGate、mastery/next-action reducer 和五段逐题反馈。
- v11 全部 1,120 道题的独立合同审查、question-node semantic alignment 和全量激活门禁。
- 同一 56 节点知识事实的 `mind_map` / `graph` 双投影、共享 handle/状态/selection/action 与独立 viewport。
- 孩子真实浏览器流程，含 desktop、390x844、ARIA、键盘、触摸、reduced motion、pending/blocked/fallback。
- restart、重复提交、stale graph/config、invalid handle、no assets、preview no mutation、regrade reconciliation。
- API/DOM child-safe 扫描和 Codex-readable 日报 lineage。

Forbidden scope:

- 不修改测试代码或生产代码。
- 不执行 live 模型、OCR、浏览器或真实数据库写入。
- 不以 mock/recorded、结构合法、脚本绿灯或报告生成成功冒充 live semantic PASS。
- 不修改图谱 JSON，不自动重绑语义错绑题，不激活部分合同冒充 1,120 全量激活。

Project boundary overlay:

- 单孩子、数学优先、SQLite local-first；GPT-5.5 文本语义，豆包 OCR。
- 所有教学、题目、评估、计划和报告绑定图谱节点；七上错误先查前置链。
- 普通文本恰好一次 GPT；明确“我不会/卡住”零次；照片为一次 OCR 加一次 GPT。
- mock/recorded 只证明状态机或显式 recorded oracle；真实语义结论需要 live provider 证据。
- 孩子页面简单、child-safe；内部 ids、模型、rubric、queue/job、lineage 不得泄漏。

Source artifacts:

| Source | Used for | Status |
|---|---|---|
| `AGENTS.md` | 项目与学习系统 QA 边界 | current |
| `docs/collaboration/playbooks/qa.md` | readiness、test review、false-pass 与证据标准 | current |
| `docs/collaboration/playbooks/qa-case-library.md` | 可复用用例质量标准 | current |
| `docs/project-rules/qa-learning-system-addendum.md` | 语义、教学、provider、OCR、长期收敛门禁 | mandatory/current |
| `docs/collaboration/inbox.md#MSG-20260714-001` | v5.1 单次语义调用、双视图和 supersession | current |
| `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md` | 双视图产品权威 | `PRD_READY` |
| `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md` | 双视图状态、交互、desktop/390px、ARIA | ready for planning |
| `docs/architecture/dual_knowledge_views_engineering_contract_v5_1.md` | config/API/handle/target-intent/activation 合同 | contract-ready; review still required |
| `docs/design/specs/2026-07-14-answer-assessment-storage-design.md` | 评分权威、存储、热路径、重评、激活 | authoritative amendment |
| `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md` | 答案评估文件/符号/阶段/验证目标 | implementation source |
| `.agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md` | 双视图文件/符号/阶段/验证目标 | implementation source |
| `docs/product/ai_native_math_learning_product_structure_v5.md` | 继承的孩子状态、response mode、证据/报告边界 | inherited/current except superseded hot path |
| `data/knowledge_graphs/math/math_knowledge_graph_v2.json` | 56 节点、9 模块、95 prerequisite 的语义 oracle | source of truth |
| `tests/test_learning_system.py` | 当前 345 项回归基线 | source-count checked; not executed here |
| `docs/qa/test_case_spec_v5.md` | 旧 v5 覆盖与历史红测 | partially stale after v5.1 supersession |
| `docs/system/qa/question_bank_grade_level_latest.md` | 静态 audit false-pass 证据 | report says PASS_WITH_SCOPE but misses semantic misbinding |
| `scripts/audit_question_bank_grade_level.py` | false-pass 根因：检查自报 alignment/结构，不证明真实题目语义 | insufficient as activation oracle |
| 用户补充审查证据 | 两个已确认语义错绑样本与正式 gate 决策 | latest authority |

TEST_CASE_SOURCE_READINESS:

- verdict: `TEST_CASE_SOURCE_READY`
- prd_quality_gate_checked: yes
- source_content_quality_ready: yes
- downstream_guessing_risk: none for implementation-stage red tests
- prd_quality_ready: yes
- product_structure_ready: yes; v5 base structure plus v5.1 amendment
- ux_flow_ready: yes for test design; rendered UX remains later gate
- data_rule_sources_ready: yes
- technical_plan_ready: yes
- engineering_contract_ready: yes for test design; answer-assessment Phase 0 contract publication remains a pre-code gate
- blueprint_ready: yes through the two implementation plans
- skeleton_ready: not_applicable for pre-implementation red-test design; rerun review after `SKELETON_PASS`
- code_runtime_targets_clear: yes; planned files, symbols, APIs, tables and scripts are named
- project_boundary_ready: yes
- missing_or_low_quality_sources: none blocking this test specification
- impact_on_test_case_quality: none; latest user decision supplies the previously missing semantic-alignment activation rule
- route_back_to_ruoming: none before red-test authoring; later implementation deviations return through 若命
- allowed_scoped_output: this TEST_CASE_SPEC only

Source supersession notes:

- `MSG-20260711-002/004` 和旧 `docs/qa/test_case_spec_v5.md` 中普通作答依次 enqueue `evaluation_update/planner_decision/teaching_generation` 的假设，对 v5.1 normal answer hot path 已失效。
- 这些 handlers 只保留 legacy/replay/recovery 范围；相关旧测试必须显式 pin legacy policy，不能作为 v5.1 期望。
- `MSG-20260711-003` 的恢复、clarify、cannot-provide、幂等与 child-safe 约束继续有效。

Test basis:

| Source | Used for | Missing/stale handling |
|---|---|---|
| Answer assessment design | 评分/存储/调用次数/clarification/regrade/activation | authoritative |
| Dual-view PRD + UX | 两投影、共享状态、浏览器与 accessibility | authoritative |
| Dual-view engineering contract | config、API、handle、intent、flag、rollback | review gate still required before implementation |
| Graph JSON | node semantic alignment、拓扑与计数 | authoritative |
| Current 345 tests | legacy regression and reusable fixtures | no v5.1 completeness claim |
| Grade-level audit/report | false-pass regression | cannot satisfy semantic activation gate |

Skeleton pass:

Not applicable for this pre-implementation red-test specification. After skeleton creation, 观止 must rerun `TEST_CASE_REVIEW` against actual symbols and update stale targets before QA execution.

Risk classification:

P1/high risk: wrong scoring, wrong question-node binding, false mastery, evidence loss, duplicate assessment/intent, stale projection mutation, child internal-data leakage, inaccessible mobile flow, or partial activation presented as complete.

Formal activation gates:

1. `AA-CONTRACT-AUTHORITY-GATE`: v5.1 engineering amendment exists and no conflicting scoring/DAG authority remains.
2. `QB-NODE-SEMANTIC-ALIGNMENT-GATE`: every one of 1,120 items has an independent accepted review proving the mathematical task actually measures the bound graph node.
3. `QB-GLOBAL-ACTIVATION-GATE`: one semantic misbinding, ambiguous binding, missing live receipt, digest mismatch, invalid contract or invalid fingerprint blocks the entire 1,120 activation transaction.
4. `AA-RUNTIME-GATE`: exact model-call counts, deterministic score, accepted assessment lineage, feedback and recovery pass.
5. `DUAL-VIEW-CONFIG-GATE`: 56/9/95 exact sets, unique mind-map tree plus complete cross-links, directed graph ranks and no nine-box layout contract pass.
6. `CHILD-BROWSER-GATE`: desktop/390px, ARIA, keyboard, reduced motion, pending/blocked/fallback and leakage checks pass with rendered evidence.
7. `ATOMIC-ACTIVATION-GATE`: assessment policy precedes map policy; backups, receipts, audits and rollback evidence exist.

Question-node semantic alignment oracle:

- Reviewer input must include the immutable question, answer/steps, kind/evidence role, bound node, node name/essence/question types/mastery criteria/diagnostic probes/teaching contract, and relevant prerequisite/controlled-extension policy.
- Reviewer must independently solve the problem and return `aligned|misbound|ambiguous`, grounded rationale, actual mathematical core/evidence demand, and whether the bound node is truly tested.
- Contract correctness and semantic alignment are separate decisions. A correct answer contract for the wrong node is rejected.
- Self-attested `node_alignment.reason`, `本题重点` copy, allowlist membership, kind, tags, problem-family ids, or schema validity are not semantic proof.
- Reviewer may suggest candidate repair nodes, but activation must not silently rebind. The item routes to question-bank repair and independent re-review.
- All 1,120 current item/version/digest rows require accepted independent receipts. Counts alone or per-node batch completion without per-item verdicts are insufficient.

Known mandatory regression samples:

| Case | Current binding | Actual mathematical core | Required verdict |
|---|---|---|---|
| `QB11-M-G7-NUMBER-LINE-19` | `M-G7-NUMBER-LINE` | 二维数表平方层/行列规律，第12行第15列 | `misbound`; blocks global activation; route question repair |
| `QB11-M-G7-RATIONAL-ADD-SUB-09` | `M-G7-RATIONAL-ADD-SUB` | 笔和本子单价的一元一次方程建模 | `misbound`; blocks global activation; route question repair |
| genuine number-line item | `M-G7-NUMBER-LINE` | 数轴表示、移动、位置比较 | `aligned` when node evidence is genuinely tested |
| genuine rational add/sub item | `M-G7-RATIONAL-ADD-SUB` | 同/异号加法、减法转加法、符号规则 | `aligned` when node evidence is genuinely tested |

Coverage matrix:

| Area | Required coverage | Cases |
|---|---|---|
| Authority/schema | new tables, minimal columns/indexes, policy pin, compatibility projections | AA-SCH-01..05 |
| Contract activation | 1,120 coverage, independent receipts, semantic alignment, fingerprints, all-or-nothing | QB-01..10 |
| Semantic scoring | 10-point deterministic score, alternatives/equivalence, answer-only, wrong reasoning, unclear | SC-01..10 |
| Call budget/provider | text 1 GPT, stuck 0, photo OCR+1 GPT, mock/live separation | CALL-01..07 |
| Clarification/regrade | supporting attempt, cannot-provide, duplicate, supersession, rebuild | CR-01..08 |
| Dual projection | same 56 nodes/handles/state/actions, mind-map tree/cross-links, directed topology | KV-01..12 |
| Browser/accessibility | first use, local preference, selection, viewport, 390px, ARIA, reduced motion | UI-01..14 |
| Intent/recovery | restart, double action, stale/invalid handle, pending/blocked, no assets, preview | INT-01..12 |
| Leakage/report | API/DOM forbidden fields and assessment/config/intent/report lineage | LR-01..08 |
| Cross-feature E2E | assessment feedback to map return/selection and atomic activation | E2E-01..12 |

Depth expansion:

| Risk | Normal | Boundary | Adversarial | Recovery | Evidence target |
|---|---|---|---|---|---|
| Semantic binding | genuine node-local item | valid controlled transfer | correct contract on wrong node | repair then re-review | per-item live receipt + graph oracle |
| Scoring | concise correct reasoning | alternative notation/method | correct answer with wrong reasoning | clarification/regrade | criteria, score recomputation, assessment lineage |
| Provider calls | text answer | photo answer | duplicate/restart tries second call | result-ref replay | provider logs + job/assessment ids |
| Views | shared node selection | collapsed/filtered node | divergent handles/state | fallback/reload | API payload + DOM + screenshot |
| Intent | immediate safe apply | analyzing wait | stale/tampered/reused key | restart reconciliation | target-intent transitions + assessment preservation |
| Child safety | normal projection | pending/blocked/error | ids/model/rubric in attributes/live region | safe fallback | recursive API/DOM scan |

Method/unit cases:

| Case | Target | Input/state | Expected |
|---|---|---|---|
| AA-SCH-01 | `db.init_schema()` | empty/current DB | creates only approved assessment tables/lineage columns/indexes additively |
| AA-SCH-02 | assessment uniqueness | duplicate accepted assessment | exactly one current accepted assessment per attempt version |
| AA-SCH-03 | contract uniqueness | two active contracts for one immutable question version | rejected atomically |
| AA-SCH-04 | raw attempt immutability | retry/regrade | raw response/attachments unchanged |
| AA-SCH-05 | policy pin | legacy and v5.1 open flows | no mixed assessment authority inside one flow |
| QB-01 | contract reviewer | known number-line misbinding | `misbound`; no active contract/receipt |
| QB-02 | contract reviewer | known rational-add-sub misbinding | `misbound`; no active contract/receipt |
| QB-03 | reviewer robustness | forged `node_alignment.reason` and `本题重点` label | still rejected when mathematical core mismatches |
| QB-04 | reviewer robustness | structurally valid answer/criteria for wrong node | contract correctness cannot override semantic rejection |
| QB-05 | global audit | 1,119 aligned + 1 rejected | activation exits nonzero, writes no global active receipt/partial active set |
| QB-06 | global audit | exactly 1,120 aligned live receipts | count, ids, versions, digests and node bindings all exact |
| QB-07 | controlled extension | advanced item allowed by label but unrelated to node evidence | rejected; allowlist alone is not proof |
| QB-08 | receipt replay | question/contract/node/graph digest changed | old receipt stale; re-review required |
| QB-09 | repair route | semantic rejection | machine-readable issue contains item, bound node, grounded mismatch and repair-required status; no silent rebind |
| QB-10 | false-pass report | current static audit says zero issues | semantic gate independently catches known samples and prevents PASS-like activation claim |
| SC-01 | scorer | all criteria `met`, total contract points 10 | visible score 10/10 and `question_passed` |
| SC-02 | judge/scorer | alternative valid method | supported criteria receive full points |
| SC-03 | judge/scorer | `a,c,b / c=a+3=0.5` | expression equivalence accepted; 10/10 |
| SC-04 | judge/scorer | correct final answer, explicitly wrong reasoning | unsupported required reasoning points denied; no reasoning mastery |
| SC-05 | judge/scorer | answer only where relation/reasoning is required | final-answer criterion only; not full pass/mastery |
| SC-06 | judge/scorer | answer only where final answer is the sole target | no invented explanation penalty |
| SC-07 | schema validator | missing/duplicate/unknown criterion key | no finalized assessment/score |
| SC-08 | schema validator | any `unclear` criterion | clarification/pending; no score/mastery |
| SC-09 | scorer | model emits total/next action/mastery | rejected/ignored; runtime remains authority |
| SC-10 | feedback projection | finalized assessment | exactly five child sections plus one runtime action, no internals |
| CALL-01 | text hot path | normal text answer | exactly one GPT semantic call; no downstream model jobs |
| CALL-02 | stuck path | explicit 我不会/卡住 | zero GPT and zero OCR calls; unscored support path |
| CALL-03 | photo path | readable image | exactly one Doubao OCR call plus one GPT semantic call |
| CALL-04 | photo path | unreadable/low-confidence/conflict | no fabricated score/mastery; clarification path |
| CALL-05 | duplicate submit | same idempotency key | one attempt, one semantic call, one accepted assessment |
| CALL-06 | restart replay | accepted envelope persisted before reducer completion | reuse result refs; no second GPT call |
| CALL-07 | provider scope | mock/recorded/live | labels never conflate; mock cannot satisfy semantic activation gate |
| CR-01 | clarification | unclear original + clear supplement | supporting-only attempt; new assessment version on original |
| CR-02 | clarification | duplicate supplement | one supporting attempt through idempotency |
| CR-03 | clarification | repeated unclear/cannot-provide | safe unscored close; no mastery or clarify loop |
| CR-04 | regrade | explicit corrected contract | new accepted assessment supersedes old; old raw attempt preserved |
| CR-05 | regrade reconciliation | old evidence had mastery/decision/summary | dependent lineage stale and learner state deterministically rebuilt |
| CR-06 | regrade projection | no current accepted assessment during correction | honest correcting/pending state, no fallback to superseded score |
| CR-07 | legacy | no exact v5.1 assessment lineage | `legacy_unmigrated`, never new mastery authority |
| CR-08 | fingerprint selection | post-pass same core cosmetic rewrite | rejected as transfer; bounded confirmation exception only after teaching |
| KV-01 | config validator | current graph/config | exact 56 nodes, 9 modules, 95 strict edges |
| KV-02 | mind map | all nodes | each real node exactly once in primary tree |
| KV-03 | mind map | multi-prerequisite nodes | represented parent plus cross-links equals all 95 prerequisites |
| KV-04 | graph | rank/lane/order | every prerequisite points lower rank to higher rank |
| KV-05 | graph | unlock-only 35 candidates | absent from initial child projection |
| KV-06 | shared handles | one canonical node | identical opaque handle in common nodes, both views, edges and selection |
| KV-07 | shared state | assessment/mastery update | both projections expose the same current child-safe state/action |
| KV-08 | local preference | active mode/viewport/collapse | remains local presentation state; absent from API/SQLite/report evidence |
| KV-09 | config digest | stale/mismatched config | map mutation blocked, current learning preserved |
| KV-10 | graph truth | view config attempts new/removed prerequisite | validation fails; graph JSON unchanged |
| KV-11 | preview | reviewed preview | no flow/intent/activity/attempt/assessment/mastery mutation |
| KV-12 | no assets | missing approved contract/teaching chain | mutating action disabled/blocked with child-safe reason |

API/service contract cases:

| Case | Interface | Expected |
|---|---|---|
| API-01 | `GET /api/knowledge-map` | exact allowlisted top-level shape; 56 common nodes, 9 modules, 95 relationships, two views, <250 KB target |
| API-02 | `GET /api/knowledge-map` policy/dependency errors | 404 off; 409 assessment/config not ready; 503 invalid config; current learning preserved |
| API-03 | `POST /api/knowledge-map/select` | accepts only handle, projection_version, action, idempotency key; no view/viewport/rank fields |
| API-04 | select stale/tampered handle | no target intent, child-safe conflict/reload response |
| API-05 | select idempotency | same payload reuses one intent; same key/different payload rejected |
| API-06 | `GET /api/knowledge-map/preview` | read-only content and zero persistence mutations |
| API-07 | `/api/child-bootstrap` composition | remains focused-state source; map endpoint remains projection source |
| API-08 | assessment feedback projection | accepted assessment is scoring authority; compatibility attempt fields cannot override it |

UI/flow cases:

| Case | Flow | Expected evidence |
|---|---|---|
| UI-01 | first visit | `导图` active, 56 nodes/9 modules, no automatic learning start |
| UI-02 | returning visit | valid local mode restored; invalid value falls back to `导图` |
| UI-03 | switch views | selected node/detail/search/filter preserved; destination viewport independently restored |
| UI-04 | mind-map tree | one virtual root, nine branches, 56 unique node buttons, accessible collapse/cross-links |
| UI-05 | graph topology | arrows, depth, convergence and bridge visible; no nine dominant closed boxes/card grids |
| UI-06 | shared detail | same state/progress/mastery/actions in both views |
| UI-07 | desktop detail | labeled complementary region; Escape and focus restoration work |
| UI-08 | 390px detail | modal bottom sheet, inert background, safe-area, no overlap, 44px controls |
| UI-09 | keyboard/ARIA | radiogroup, unique node names, aria-selected/expanded/live, hidden surfaces not tabbable |
| UI-10 | reduced motion | switch/recenter/sheet become immediate; no information depends on animation |
| UI-11 | analysis cold reload | map home says saved/pending honestly and exposes resume/progress action |
| UI-12 | blocked state | real retry/summary only; generic refresh cannot masquerade as recovery |
| UI-13 | fallback list | same nodes/detail/actions; spatial and fallback controls are not both tabbable |
| UI-14 | feedback renderer | model text inserted safely; no HTML/script injection or hidden grading internals |

State/async/recovery cases:

| Case | Trigger | Expected transition |
|---|---|---|
| INT-01 | select with no flow | one pending/applied target intent |
| INT-02 | unanswered current step switch | explicit continue-or-switch choice; only unconsumed step superseded |
| INT-03 | select during submit/analysis/reducer | waiting target; assessment finishes first |
| INT-04 | reducer safe boundary | newest valid target applied before normal next step, exactly once |
| INT-05 | clarification switch | unresolved evidence preserved; switch uses stable boundary |
| INT-06 | restart with waiting intent | revalidate graph/config/assets/assessment policy, then apply or block/stale |
| INT-07 | older pending target | atomically cancelled when a new valid target is created |
| INT-08 | blocked/no assets | no intent application and no dead-end learning step |
| INT-09 | duplicate answer submit | one attempt/assessment/decision/visible result |
| INT-10 | stale graph/config | no mutation; local preference/selection restored only when valid |
| INT-11 | terminal summary repeat | idempotent no-op, no new answer/next controls |
| INT-12 | waiting retry budget exhausted | leaves analyzing for honest blocked/summary/clarify; saved evidence retained |

Data/artifact cases:

| Case | Artifact/data | Expected |
|---|---|---|
| DA-01 | 1,120 contract activation receipt | exact active bank/graph/manifest/item counts and per-item review refs |
| DA-02 | semantic rejection report | known misbindings listed as blocking issues; issue count/verdict/exit code agree |
| DA-03 | assessment lineage | question/contract/attempt/agent run/assessment/validation/mastery/decision exact refs |
| DA-04 | regrade report | superseded/stale/current lineage and corrected history represented honestly |
| DA-05 | knowledge config receipt | exact graph lineage/config digest/56/9/95 counts |
| DA-06 | daily report | child target, recommendation, prerequisite detour, applied node and assessment/config lineage separated |
| DA-07 | leakage scan | API, rendered text, accessible names, attributes, URLs and localStorage contain no forbidden internals |
| DA-08 | backup/rollback receipt | backup integrity, changed files, flags, rollback result and no Git initialization recorded |

Scenario/e2e cases:

| Scenario | Provider lane | Expected |
|---|---|---|
| E2E-01 concise correct text | live GPT | one call, deterministic 10/10, five-part feedback, valid next action |
| E2E-02 alternative valid method | live GPT | semantically accepted without wording penalty |
| E2E-03 right answer/wrong reasoning | live + recorded oracle | partial/failed required criteria; no false mastery |
| E2E-04 answer-only | live + recorded oracle | outcome follows question-specific criteria, not universal penalty |
| E2E-05 explicit stuck | live + recorded oracle | submission records the child stuck signal, queues answer analysis, and creates no teaching/probe/safe-stop decision before model evidence |
| E2E-06 readable photo | live Doubao + GPT | OCR provenance plus one semantic call; score only after safe judgment |
| E2E-07 unclear/conflicting photo | live/accepted oracle | clarify, no score/mastery, cannot-provide exits safely |
| E2E-08 duplicate/restart | isolated DB | one authoritative result and no duplicate provider call |
| E2E-09 regrade | isolated DB | current assessment/state/report rebuilt from accepted evidence |
| E2E-10 dual-view node choice | browser | same handle/selection/state, independent viewports, focused learning entry |
| E2E-11 switch during analysis | browser + isolated DB | target waits, submitted assessment persists, target applies once |
| E2E-12 full activation audit | live receipts + isolated browser then formal service | assessment first, dual view second; any semantic misbinding blocks activation |

Negative/adversarial cases:

- Correct contract and reference answer attached to a mathematically unrelated node.
- Reviewer receipt with valid schema but rationale copied from `本题重点` or self-attested node metadata.
- One rejected item hidden by aggregate `1120 generated` count.
- PASS_WITH_SCOPE report with zero issue count despite known semantic misbinding.
- Model emits all criteria `met` while cited child evidence contradicts the response.
- OCR invents a sign/symbol or conflicts with typed text.
- Duplicate submit or restart causes a second GPT call or second accepted assessment.
- View switch adds `view` to target-intent digest or changes target semantics.
- Hidden view/fallback retains tabbable descendants.
- Graph visually becomes nine module boxes despite valid rank/lane data.
- Internal ids leak through `data-*`, test ids, ARIA descriptions, errors, URLs or localStorage.

Fixtures / samples required:

| Fixture | Minimum content | Evidence lane |
|---|---|---|
| `question_node_alignment_oracle_v51` | two known misbindings, genuine aligned controls, forged labels/reasons, controlled-extension boundary | recorded oracle + live reviewer |
| `answer_semantic_oracle_v51` | concise correct, alternative method, answer-only, wrong reason/right answer, partial symbol/unit, unclear | recorded + live GPT |
| `photo_ocr_oracle_v51` | readable, blurred, cropped, hallucinated sign, text-photo conflict | recorded + live Doubao |
| `regrade_lineage_fixture_v51` | accepted assessment with downstream mastery/decision/summary then corrected contract | deterministic |
| `dual_view_fixture_v51` | 56/9/95, 35 multi-prerequisite nodes, bridge/convergence samples | deterministic graph source |
| `child_safe_forbidden_terms_v51` | ids, provider/model, rubric, prompt, confidence, queue/job, paths/config | deterministic scan |

Test files authorized:

| File/path | Purpose | Allowed change now |
|---|---|---|
| `docs/qa/test_case_spec_v5_1_assessment_dual_views.md` | durable v5.1 test specification | create/update |
| `tests/test_answer_assessment_v51.py` | future focused assessment red tests | no |
| `tests/test_knowledge_views_v51.py` | future focused dual-view red tests | no |
| `scripts/browser_answer_assessment_v51.mjs` | future assessment browser acceptance | no |
| `scripts/browser_dual_knowledge_views_v51.mjs` | future dual-view browser acceptance | no |
| `tests/test_learning_system.py` | current 345-test regression baseline/cross-feature assertions | no |

Current 345-test baseline review:

- Source scan found 345 test methods; tests were not executed in this dispatch.
- Existing coverage is useful for current-step, async, stuck, OCR, evidence, planning, reports and child-safe regressions.
- It does not contain the v5.1 tables/contracts/full 1,120 semantic receipts or dual-view config/API/browser contracts.
- Existing semantic mismatch coverage samples only narrow handcrafted cases and does not prove all active questions align to their nodes.
- Existing old-DAG tests that require evaluation/planner/teaching jobs must be retained only under explicit legacy/replay policy expectations.
- `test_v5_live_answer_analysis_advances_without_downstream_model_jobs` is a reusable v5.1 direction check, but it does not prove the new assessment authority or deterministic scoring alone.

Automation plan:

1. Phase 0 red tests: authority docs, schema, exact call counts, semantic-alignment gate, all-or-nothing activation, config invariants.
2. Phase 1 focused unit/API tests in `tests/test_answer_assessment_v51.py` and `tests/test_knowledge_views_v51.py`.
3. Full 345-test regression with legacy-policy assertions updated but not deleted.
4. Recorded semantic/OCR oracle replay, explicitly labeled non-live.
5. Live GPT/Doubao sample gate with provider receipts and human semantic spot-check.
6. Isolated desktop/390px browser acceptance, screenshots, accessibility and leakage scan.
7. Activation audit verifies report verdict, issue count, exit code, receipts, DB facts and API behavior agree.

Manual QA handoff:

- Human/教研 must inspect semantic alignment and child readability; static labels and model self-assertion are insufficient.
- 清秋 performs rendered UX review; 镜花 reviews architecture/state/authority; 观止 retains independent QA gate.
- Formal live runs require explicit model/OCR and local-ledger authorization plus isolated data where possible.

False-pass risks:

- 合同结构、答案和 criteria 都合法，但题目实际属于另一个知识节点。
- `node_alignment.reason`、kind、allowlist 或“本题重点”与绑定节点一致，真实数学核心却不一致。
- 1,119 项通过、1 项失败，却生成部分 active rows 或 aggregate success receipt。
- 静态 audit 报 `PASS_WITH_SCOPE`、0 issues，但人工抽样已发现错绑。
- mock/recorded 输出被标记为 live semantic evidence。
- 浏览器只验证 56 个按钮，不验证两视图同 handle/同状态、图谱方向和导图 cross-links。
- 报告生成成功但遗漏 pending/blocked/stale/regrade/intent lineage。

Coverage gaps:

- 实现和 skeleton 尚未创建；实际符号出现后必须复审测试目标。
- 1,120 live independent review receipts、live GPT/Doubao、真实浏览器截图和性能数据尚未执行。
- 视觉层级和孩子可读性仍需人工最终判断。

TEST_CASE_REVIEW:

- source_artifacts_checked: all sources listed above, including `MSG-20260714-001` and the false-pass report/script.
- existing_cases_checked: current 345-test source inventory and prior v5 TEST_CASE_SPEC.
- stale_or_missing_cases: v5.1 assessment authority, full-bank semantic alignment, dual views, exact call counts, regrade, activation, 390px/reduced-motion/leakage.
- updates_made: created this source-traced v5.1 specification and superseded old normal-hot-path DAG expectations.
- updates_not_made_reason: write ownership excludes test and production files.
- authorized_test_files_changed: this document only.
- ready_for_execution: no; ready for implementation-stage red-test authoring after dispatch.

TEST_CASE_QUALITY_GATE:

- verdict: `TEST_CASE_READY`
- product_acceptance_coverage: pass
- technical_contract_coverage: pass for pre-implementation red-test design
- code_runtime_targets_verified: pass against named planned targets and current baseline
- coverage_matrix_complete: pass
- depth_expansion_sufficient: pass
- negative_adversarial_cases_present: pass
- false_pass_risks_identified: pass
- evidence_standard_defined: pass
- coverage_gaps_explicit: pass
- blocking_quality_gaps: none for red-test authoring

Stop condition:

This specification authorizes no implementation or QA verdict. Next, 听云 may consume it for red-test/implementation work. After `SKELETON_PASS`, 观止 must rerun source and test-case review before any QA execution. Any question-node semantic rejection blocks the entire 1,120 contract activation and routes the item to question-bank repair and independent re-review.
