# Active Math Question Bank Quality Audit

## QA_AUDIT_PLAN

### Objective

Audit the active graph-generated math question bank for semantic usefulness across all 56 graph nodes. A count of 20 active items per node is treated only as an inventory precondition, never as semantic acceptance.

### Authorization And Safety

- Role: 观止 (`agentKey=guanzhi`).
- Authorized write: this report only.
- Database access: SQLite URI `mode=ro` or `sqlite3 -readonly` only.
- No production, question-data, test, fixture, or database edits.
- No external model calls and no real learner/session mutation.
- No mock result is used as semantic PASS evidence.

### Oracles

- `AGENTS.md`: one incoming Grade-7 child; graph-bound teaching; prerequisite rollback; no mechanical drill; controlled extension only.
- `docs/00_PROJECT_BLUEPRINT.md`: 56 nodes, L1-L4 meanings, questions serve diagnosis rather than volume, only three `controlled_extension` nodes.
- `docs/product/ai_native_math_learning_prd_v5.md`: text/photo/stuck are normal evidence modes; reference answers are rubric context rather than string-match truth; planner consumes a bounded candidate packet.
- `docs/qa/test_case_spec_v5.md`: semantic uniqueness, near transfer, prerequisite probing, alternative valid methods, child-safe wording, photo evidence, and candidate-packet risks.
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`: node identity, stage, prerequisites, and summer mode.
- `learning_system/question_bank.py`: active-use checks, semantic identity fields, and `candidate_packet_for_node()` behavior.

### Method

1. Pin the source artifacts and database snapshot by SHA-256.
2. Query all current graph-generated questions, active review rows, graph nodes, and reviewer runs.
3. Verify current-version and active-eligible inventory for every node.
4. Normalize child prompts only by removing the trailing `本题重点：<节点名>` decoration, then detect exact cross-node prompt/answer reuse.
5. Inspect semantic-family reuse independently of generated `problem_family_id` and `core_stem_id` values.
6. Semantically inspect five fixed roles on every node: slots `01`, `05`, `13`, `14`, and `19` (standard, representation/variant, prerequisite, stretch, model-selection surfaces), for 280/1,120 items.
7. Audit difficulty, evidence-role fit, answer/rubric tolerance, geometry/media suitability, controlled stretch, and child-facing wording.
8. Replay the current candidate-packet service read-only for every node, then calculate the deterministic first-eight composition that would result if the missing lineage field alone were repaired.
9. Define a release gate requiring regeneration, independent semantic review, and repeat all-node audit.

## QA Result

### QA / NEEDS_FIX - 观止（agentKey: `guanzhi`）- 2026-07-11 16:37 CST

**Verdict:** `QA_NEEDS_FIX`

**independence_required:** true; this audit made no production or bank changes  
**context_mode:** full requested artifact context plus read-only database evidence  
**context_origin:** user boundary overlay, repository sources, SQLite snapshot  
**diff_pin:** no Git worktree metadata exists at the project root; artifact hashes below pin the audit  
**Scope:** active math bank `2026-07-08.bank.v11`, all 56 graph nodes, review lineage, and planner packet exposure  
**Project boundary overlay:** one incoming Grade-7 child; concept/model/procedure/transfer evidence; controlled extension; no private-textbook claim; no count-only PASS  
**Environment:** local macOS workspace; SQLite opened read-only  
**Test case spec:** `docs/qa/test_case_spec_v5.md`, especially QQ-05/QQ-06 and planner/near-transfer oracles  
**Test case review:** sufficient for this content audit; no test changes authorized or needed  
**Samples:** 1,120/1,120 current graph-generated items via structured analysis; 280 fixed-role semantic samples covering 5/20 items on every node  
**Allowed side effects:** creation of this report only  
**False-pass audit:** failed; active approvals prove manifest conformance, not per-item semantic review  
**Visual/interaction regression audit:** UI rendering out of scope; geometry/media suitability audited from question payloads  
**Semantic/product audit:** failed  
**Model-risk audit:** no model was called; live grading tolerance remains unproved and is not claimed  
**Adversarial/destructive cases:** topic-label stripping, cross-node duplicate grouping, evidence-role mismatch, and packet-lineage replay  
**Long-run behavior:** no learner simulation authorized; deterministic packet ordering was analyzed statically after exact read-only replay

## Snapshot

| Artifact | Pin |
|---|---|
| SQLite database | SHA-256 `6c5278a1a94ab9a864481b7efb0462281b41a999402af8dafd8c8a19f997eb8e`; 41,246,720 bytes; mtime `2026-07-11 14:43:26 CST` |
| Graph | version `2026-07-04.v2`; SHA-256 `1067b9c318efb116f6463fb7dd3db1a3888b440b6d33384c81313f79711a2971` |
| Active bank | `2026-07-08.bank.v11` |
| `learning_system/question_bank.py` | SHA-256 `4cf222c641497987ab862a5524e69e15255daa2181223566aadf1e3a139d4354` |
| PRD v5 | SHA-256 `299088bf1dfd6e58f132eac68bc18e94a730a2e9daf1c37a8f7642bee0c6fe1f` |
| Test-case spec v5 | SHA-256 `c4006192e54cfc0ead7ccfa77d0e48d09ee7d5afca6a5026c149b6279e58de47` |

## Quantitative Findings

### Inventory Is Complete Only Mechanically

- 56/56 graph nodes have exactly 20 current graph-generated rows and one active approval per row: 1,120 total.
- All 1,120 active review records pass the current review-record authorization function.
- Metadata is identically distributed on every node: 2 L1, 8 L2, 8 L3, 2 L4; and exactly one item for each of 20 blueprint `kind` values.
- No active item contains empirical difficulty, calibration, age-fit evidence, or a structured `difficulty_vector`; L1-L4 is generator metadata only.

### Exact Semantic Reuse Is Widespread

- Raw prompt strings are formally unique because each ends with a different node label.
- After removing only that trailing label, there are 559 distinct prompts rather than 1,120.
- 593/1,120 items (52.9%) participate in 32 exact normalized-prompt and exact-answer groups spanning more than one node; 38/56 nodes are affected.
- 533 items across 30 nodes repeat the exact answer core `3x+2(x+5)=28` for the pen/notebook problem.
- Including its numeric restatement `3x+4(x+6)=45`, 563/1,120 items (50.3%) belong to the same stationery word-problem family.
- The same exact core is labeled across all difficulty bands: 60 L1, 211 L2, 206 L3, and 56 L4 items.
- Generated identity values hide this reuse: 966 global `problem_family_id` values and 1,065 global `core_stem_id` values exist; zero core IDs are shared across nodes. Per node, the bank reports 17-18 families and 19-20 cores despite the content duplication.

### All-Node Semantic Sample Fails

- Fixed-role sample: 280 items (`01`, `05`, `13`, `14`, `19` on every node).
- 113/280 sampled items (40.4%), across 30 nodes, are the same stationery family.
- Every one of the 30 affected nodes has the stationery family in slot `05` and slot `13`; 26 also have it in slots `14` and `19`.
- Manual role-to-prompt coding of eight high-risk roles found only 16/448 aligned instances (3.6%):

| Declared role | Semantically aligned / 56 | Main mismatch |
|---|---:|---|
| `prerequisite_probe` | 1 | Prompt usually asks for symbol/unit/bracket checking, not prior-node evidence |
| `representation` | 1 | Prompt usually refutes a claim, rather than converting representations |
| `model_selection` | 0 | Prompt removes irrelevant prose, rather than selecting between plausible models |
| `boundary_case` | 0 | Prompt asks for a verification method, not an edge/exception case |
| `symbol_unit_audit` | 8 | Prompt usually presents a numeric/context variant |
| `variant` | 0 | Prompt usually converts to a table/diagram, which is representation work |
| `stretch_transfer` | 6 | Most are the base stem with added instructions or an off-node challenge |
| `two_method_compare` | 0 | Prompt identifies conditions/checks but does not compare two methods |

This means the bank cannot infer evidence type from `kind`; the label is not a semantic contract.

### Difficulty And Grade Fit Are Not Credible

- Global metadata spread is L1 112, L2 448, L3 448, L4 112, identically copied to every node.
- The repeated stationery core alone occupies all four bands, so additional prose is being counted as difficulty progression even when the mathematical evidence is unchanged.
- All 56 nodes contain a `stretch_transfer` item, although the graph design has only three `controlled_extension` nodes.
- 26 items across 13 nodes are marked `picture_level` challenge extensions; none belongs to the three `controlled_extension` nodes.
- Examples include a four-digit reversal proof, pigeonhole/prefix-sum proof, telescoping sum/product, and custom operation. These may be valid enrichment material, but their current placement in core nodes is not a safe mainline for a weak incoming Grade-7 learner.

### Answers And Rubrics Do Not Encode Tolerance

- All 1,120 items have one free-text `expected_answer` string.
- Zero items provide structured accepted alternatives, equivalent forms, valid method variants, or answer-normalization rules.
- All 1,120 items share exactly one generic three-level rubric.
- Fifty-six prompts explicitly ask for two methods or two representations, but the payload still has no structured alternatives.
- PRD v5 says reference answers are rubric context, not string-match grading. With no live semantic grading call authorized, this audit cannot prove that equivalent reasoning or alternative solutions would be accepted.

### Geometry And Photo Suitability Are Insufficient

- Ten geometry/angle/visual nodes contribute 200 items; 133/200 (66.5%) belong to the stationery family.
- Only four of those 200 prompt bodies actually request or refer to a drawing/diagram after the trailing topic label is removed.
- Zero of 1,120 items, including all geometry items, contains a structured image, diagram, media, attachment, or visual-asset field.
- `QB11-M-G7-SEGMENT-MEASURE-01` refers to “同一张图” without supplying an image payload.
- `QB11-M-G7-GEO-VIEWS-01` is node-aligned but only asks for general conditions; the other 19 active items on that node are the stationery family. The node therefore cannot provide a credible visual/net/view evidence packet.
- Photo is a supported child answer mode, but no question-specific rubric describes how a photographed construction, diagram, or alternate visual proof should be judged.

### Child-Facing Copy Is Template-Dominated

- 1,120/1,120 prompts contain `本题重点：...`.
- 448 contain `做完后把最容易错的一步圈出来`.
- 448 contain `最后用检验、错因或模型说明关键一步为什么成立`.
- 56 reveal a “正确结论” and ask the child to reverse-engineer evidence.
- 56 require the same stock bundle: `关系、过程、结论和检验`.
- Explicit internal terms (`agent`, `Codex`, graph ID, rubric, generator) and private-textbook claims were not found. That limited check passes, but repetitive generator-style decoration and answer-leading language do not.

### Review Lineage Is A Semantic False Pass

- There are 2,240 review rows for 1,120 questions: exactly two per item.
- 1,120 inactive rows are `approved` but have no reviewer run.
- All 1,120 active approvals point to one run: `AR-4a86f95b3eb4`.
- The run is deterministic, phase `curated_seed_question_review`, with empty model provider/name. Its output records manifest flags only; it contains no per-item semantic judgment, defect reason, or sampled evidence.
- Active rejections: zero.
- The authorization function therefore proves current manifest/hash lineage, not question quality. It must not be presented as independent semantic review.

### Planner Candidate Packets Are Currently Empty

- Exact read-only replay of `QuestionBankService.candidate_packet_for_node()` returns `candidate_count=0` for all 56 nodes.
- Aggregate replay: 1,168 rows seen and 1,168 excluded as `missing_lineage`; no other exclusion counter increments.
- All 1,120 v11 raw/source payloads omit `graph_version`, which the packet lineage check requires. The additional 48 scanned rows are legacy `diagnostic` items with no active review lineage.
- This is a release-blocking hot-path failure even before semantic quality is considered.

If only the missing graph-version field were repaired, deterministic ID ordering would expose a second failure:

- 56 packets x 8 = 448 candidates.
- Per node: 1 L1, 2 L2, 4 L3, and 1 L4; the same eight `kind` slots on every node.
- No prerequisite probe appears; slot `13` is outside the first eight.
- One L4 transfer item appears for every node without learner-readiness or summer-mode gating.
- 181/448 candidates (40.4%) contain the exact pen/notebook equation core; 211/448 (47.1%) belong to its stationery family, across 30 nodes.
- `excluded_duplicate` would remain zero before all packets fill because generated core IDs are distinct even when content is identical.

## Test Matrix

| Case | Risk | Technique | Oracle/Rubric | Expected | Actual | Evidence | Verdict |
|---|---|---|---|---|---|---|---|
| QB-INV-01 all-node active inventory | Count-only false confidence | Full SQL scan | 56 nodes; >=20 current eligible each | Inventory present but not treated as semantic PASS | Exactly 20 each | 1,120 rows and approvals | PASS_WITH_SCOPE |
| QB-DUP-01 semantic-core uniqueness | Decorated copies dominate | Topic-label normalization + exact answer grouping | Distinct useful evidence, not cosmetic variation | Cross-node reuse limited and intentional | 593 exact duplicates; 563 stationery-family items | IDs/groups above and appendix | FAIL |
| QB-DIFF-01 actual difficulty | Wrong challenge for child | Distribution and content comparison | L1-L4 reflect mathematical/cognitive change | Calibrated node-fit progression | Uniform metadata; same core in all bands | Level/core counts | FAIL |
| QB-ROLE-01 evidence-role fit | Wrong mastery evidence | 5 fixed roles x 56 plus 8-role coding | Kind matches requested evidence | Prerequisite/model/transfer roles are real | 16/448 aligned in high-risk role set | Role table | FAIL |
| QB-ANS-01 alternative solution tolerance | Valid work rejected or misread | Payload/rubric scan | Reference is flexible rubric context | Accepted variants/method criteria exist | One expected string; zero alternative fields; one rubric | Full 1,120 scan | FAIL |
| QB-VIS-01 geometry/photo suitability | Visual concept cannot be evidenced | Geometry subset scan | Concrete visual tasks and photo-aware rubric | Media/diagram evidence available where needed | 0 media fields; 133/200 stationery-family items | Geometry metrics and IDs | FAIL |
| QB-COPY-01 child prompt clarity | Template/meta burden | Phrase frequency scan | Clear direct child question | Minimal, node-specific instructions | 100% topic banner; repeated stock instructions | Phrase counts | FAIL |
| QB-REV-01 independent semantic review | False active approval | Review/run lineage audit | Per-item semantic approval/rejection evidence | Review records contain meaningful judgments | One deterministic manifest run; zero active rejects | `AR-4a86f95b3eb4` | FAIL |
| QB-PKT-01 current planner packet | No question can be planned | Exact read-only service replay | 5-8 current safe candidates per node | Nonempty bounded packets | 0/8 on every node | 56 packet replays | FAIL |
| QB-PKT-02 latent packet quality | Bad items surface after lineage patch | Deterministic first-eight simulation | Deduped, learner-gated, evidence-driven packet | No off-node duplicate/L4 leak | 47.1% stationery family; one L4 each; no prerequisite | 448-row calculation | FAIL |

## Failures And Severity

### P0 - Candidate packet outage

`candidate_packet_for_node()` returns no candidates for any node because the active v11 item payload lacks required graph-version lineage. The current bank is not planner-usable.

### P1 - Cross-node semantic contamination

More than half the bank participates in exact cross-node prompt/answer groups after only the node-label decoration is removed. Geometry, percent, motion, scientific notation, unit conversion, and several equation subtypes can receive the same stationery equation instead of evidence for their own node.

### P1 - Review status overstates semantic assurance

The single deterministic manifest run authorizes every active item and rejects none. The database says “approved,” but no independent per-item semantic review evidence exists. This is a false-pass risk for every downstream planner/mastery claim.

### P1 - Latent planner exposure after a metadata-only fix

Repairing `graph_version` alone would produce technically nonempty packets that still include 211 stationery-family candidates, force one L4 item per node, omit prerequisite probes, and record zero duplicate exclusions.

### P2 - Evidence-role labels, difficulty, and stretch are not trustworthy

Eight critical blueprint roles are largely bound to another prompt pattern. Difficulty is uniform metadata rather than content calibration, and hard extension material is placed outside designated controlled-extension nodes.

### P2 - Answer, geometry, and child-copy contracts are under-specified

One generic rubric and one reference string do not encode alternative methods. Geometry lacks structured visuals/photo-aware criteria. Repeated instructions obscure the actual question and sometimes lead with the correct conclusion.

## Representative Evidence

| Question ID | Finding |
|---|---|
| `QB11-M-G7-GEO-VIEWS-02` | Pen/notebook equation labeled as 展开图与视图. |
| `QB11-M-G7-LINE-RAY-SEGMENT-02` | Same equation labeled as 直线、射线、线段. |
| `QB11-M-PRE-PERCENT-05` | Same equation/table conversion labeled as 百分数与增长率. |
| `QB11-M-BRIDGE-MOTION-CHASE-05` | Same equation/table conversion labeled as 追及与相遇. |
| `QB11-M-G7-EQ-DENOM-01` | Solves `3x+5=20`; no denominator equation is present. |
| `QB11-M-G7-EQ-DENOM-06` | L4 transfer is still the same stationery equation, with extra prose. |
| `QB11-M-G7-ABSOLUTE-13` | Declared prerequisite probe asks for symbol/unit/bracket checking. |
| `QB11-M-G7-ABSOLUTE-19` | Declared model selection asks the child to discard irrelevant wording. |
| `QB11-M-BRIDGE-WORD-PROBLEM-READING-14` | Pigeonhole/prefix-sum proof is inserted into a core reading-flow node as stretch. |
| `QB11-M-G7-SEGMENT-MEASURE-01` | Refers to “同一张图” with no structured diagram/media. |
| `QB11-M-G7-GEO-VIEWS-01` | The only clearly node-local item on its node; the remaining 19 are the stationery family. |

## Required Remediation

1. **Do not activate or use v11 for child planning.** Treat current packets and approvals as release-blocking evidence, not as a usable bank.
2. **Regenerate/re-curate all 56 nodes under a new bank version.** Thirty nodes need direct semantic decontamination; all 56 need corrected evidence-role binding, difficulty, child copy, and independent review.
3. **Use content-derived semantic identity.** Normalize mathematical objects, quantities, relationships, and demanded evidence; do not include node ID or blueprint decoration in the uniqueness signature. Similar stems may remain only when they deliberately test a different representation, misconception, or transfer and the distinction is reviewable.
4. **Produce a per-node evidence matrix.** Every node must cover concept/essence, model or representation, procedure, misconception, prerequisite where applicable, near transfer, and controlled stretch only when allowed. A label without matching prompt/answer/rubric content does not count.
5. **Calibrate difficulty from mathematical demand.** L4 must add genuine cross-node transfer or abstraction and must be gated by learner readiness and `summer_mode`; added prose alone is not a level change.
6. **Add answer-tolerance evidence.** Record equivalent answers/forms, valid alternative methods, essential reasoning points, unacceptable shortcuts, and photo/diagram review criteria where applicable.
7. **Rebuild geometry coverage.** Supply concrete diagrams/assets or fully specified constructions and ensure photographed work can be evaluated without inventing visual evidence.
8. **Replace manifest-only approval with independent semantic review.** Each item needs a reviewable decision and reason; the process must be capable of rejection. Review samples must include all high-risk duplicate families and every node.
9. **Repair candidate lineage and packet selection together.** A packet must contain 5-8 current, node-aligned, semantically distinct candidates; enforce cooldown/semantic dedup, readiness/difficulty gates, prerequisite availability, and safe fallback when fewer than five pass.

## Release Gate

The bank is not usable until all conditions below are met on a new version:

- 56/56 nodes retain at least 20 active candidates **after** content-derived semantic deduplication and semantic review.
- Every active item is node-aligned or explicitly declares a justified secondary/controlled-extension role; no topic label is used to disguise an off-node stem.
- The per-node evidence matrix demonstrates concept/model/procedure/transfer coverage and real prerequisite/misconception probes where applicable.
- No uncontrolled extension enters the mainline; the three `controlled_extension` nodes have usable on-node extension material, and core/diagnose-only nodes are readiness-gated.
- Reference/rubric data supports equivalent answers and alternative methods; geometry includes concrete visual/photo criteria.
- An independent review run records per-item judgments, includes actual rejections or documented zero-rejection justification, and is not merely a manifest/hash authorization.
- Read-only replay returns 5-8 candidates for all 56 nodes with zero missing-lineage exclusions.
- Packet audit shows no off-node item, no content-semantic duplicate, no inappropriate L4 item for a weak/unknown learner state, and a reachable prerequisite probe when rollback evidence calls for one.
- A repeat all-node structured scan and 56-node semantic sample returns `QA_PASS_WITH_SCOPE` or better. Live model grading, OCR, and long-run learner semantics remain separate QA scopes.

## Source Gap Routed To 若命

The sources define the required evidence categories but do not set a numeric minimum per category for each node or a formal threshold for when two variants count as distinct evidence. 若命 must approve the per-node evidence matrix and semantic-distinctness rubric before regeneration acceptance. This source gap does not reduce the severity of the direct off-node duplication, empty packet, or manifest-review failures.

## All-Node Appendix

`跨节点同答案` counts items whose exact expected-answer string occurs on more than one node. `文具模板族` includes the exact pen/notebook core and its numeric variant. `抽样模板/5` covers slots `01/05/13/14/19`. `picture-ext` is the payload's challenge marker, not an image asset. `当前 packet` is the exact read-only service result.

| Node | 名称 | 阶段 | 夏季模式 | active | 跨节点同答案 | 文具模板族 | 抽样模板/5 | picture-ext | 当前 packet |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| `M-BRIDGE-CLOCK-ANGLE` | 钟表角问题 | 衔接桥梁 | controlled_extension | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-BRIDGE-MOTION-BASIC` | 行程基础模型 | 衔接桥梁 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-BRIDGE-MOTION-CHASE` | 追及与相遇模型 | 衔接桥梁 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-BRIDGE-PERCENT-MODEL` | 百分数应用模型 | 衔接桥梁 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-BRIDGE-PROPORTION-MODEL` | 比例应用与对应量表 | 衔接桥梁 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-BRIDGE-SOLUTION-HABIT` | 解题步骤与检验习惯 | 衔接桥梁 | core | 20 | 19 | 17 | 2 | 2 | 0/8 |
| `M-BRIDGE-SUM-DIFF-MULTIPLE` | 和差倍模型 | 衔接桥梁 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-BRIDGE-WORD-PROBLEM-READING` | 应用题审题流程 | 衔接桥梁 | core | 20 | 19 | 18 | 3 | 2 | 0/8 |
| `M-BRIDGE-WORK-RATE` | 工程问题 | 衔接桥梁 | controlled_extension | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-ABSOLUTE` | 绝对值 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-ALG-EXPR` | 代数式 | 七上主线 | core | 20 | 1 | 0 | 0 | 0 | 0/8 |
| `M-G7-ANGLE` | 角的概念与表示 | 七上主线 | core | 20 | 1 | 0 | 0 | 0 | 0/8 |
| `M-G7-ANGLE-CALC` | 角度计算 | 七上主线 | selective_core | 20 | 1 | 0 | 0 | 0 | 0/8 |
| `M-G7-COMBINE-LIKE` | 合并同类项 | 七上主线 | core | 20 | 1 | 0 | 0 | 0 | 0/8 |
| `M-G7-COMPARE` | 有理数大小比较 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-EQ-DENOM` | 含分母方程 | 七上主线 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-EQ-PAREN` | 含括号方程 | 七上主线 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-EQ-SOLVE` | 解一元一次方程基础 | 七上主线 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-EQ-WORD` | 一元一次方程应用题 | 七上主线 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-EQUALITY-PROP` | 等式性质 | 七上主线 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-EQUATION-CONCEPT` | 方程与一元一次方程概念 | 七上主线 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-EXPR-VALUE` | 代数式求值 | 七上主线 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-GEO-SOLID-PLANE` | 立体图形与平面图形 | 七上主线 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-GEO-VIEWS` | 展开图与视图 | 七上主线 | controlled_extension | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-LIKE-TERMS` | 同类项 | 七上主线 | core | 20 | 1 | 0 | 0 | 0 | 0/8 |
| `M-G7-LINE-RAY-SEGMENT` | 直线、射线、线段 | 七上主线 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-G7-MONOMIAL` | 单项式 | 七上主线 | selective_core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-NUMBER-LINE` | 数轴 | 七上主线 | core | 20 | 2 | 0 | 0 | 2 | 0/8 |
| `M-G7-OPPOSITE` | 相反数 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-PARENTHESIS` | 去括号 | 七上主线 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-POINT-LINE-PLANE` | 点线面体 | 七上主线 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-POLY-ADD-SUB` | 整式加减 | 七上主线 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-POLYNOMIAL` | 多项式 | 七上主线 | selective_core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-POS-NEG` | 正数和负数 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-POWER` | 乘方 | 七上主线 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-RATIONAL-ADD-SUB` | 有理数加减 | 七上主线 | core | 20 | 17 | 17 | 2 | 2 | 0/8 |
| `M-G7-RATIONAL-CLASSIFY` | 有理数分类 | 七上主线 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-G7-RATIONAL-MIXED` | 有理数混合运算 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-RATIONAL-MUL-DIV` | 有理数乘除 | 七上主线 | core | 20 | 0 | 0 | 0 | 2 | 0/8 |
| `M-G7-SCI-NOTATION-APPROX` | 科学记数法与近似数 | 七上主线 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-G7-SEGMENT-MEASURE` | 线段比较与计算 | 七上主线 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-ANGLE-BASIC` | 角度基础 | 小学关键前置 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-DECIMAL-OPS` | 小数运算 | 小学关键前置 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-PRE-DISTRIBUTIVE` | 运算律与去括号意识 | 小学关键前置 | core | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-PRE-EQUATION-BASIC` | 小学简易方程 | 小学关键前置 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-FRACTION-MEANING` | 分数意义与单位1 | 小学关键前置 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-PRE-FRACTION-OPS` | 分数运算 | 小学关键前置 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-PRE-GEO-AREA-VOLUME` | 面积体积公式理解 | 小学关键前置 | diagnose_only | 20 | 19 | 19 | 4 | 0 | 0/8 |
| `M-PRE-INTEGER-OPS` | 整数四则计算 | 小学关键前置 | core | 20 | 2 | 0 | 0 | 2 | 0/8 |
| `M-PRE-LETTER-EXPR` | 用字母表示数 | 小学关键前置 | core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-NUMBER-SENSE` | 数感与估算 | 小学关键前置 | core | 20 | 2 | 0 | 0 | 2 | 0/8 |
| `M-PRE-ORDER-OPS` | 四则混合运算与括号 | 小学关键前置 | core | 20 | 0 | 0 | 0 | 0 | 0/8 |
| `M-PRE-PERCENT` | 百分数与增长率 | 小学关键前置 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-QUANTITY-RELATION` | 等量关系与列式 | 小学关键前置 | core | 20 | 19 | 17 | 2 | 2 | 0/8 |
| `M-PRE-RATIO-PROP` | 比、比例与比例思想 | 小学关键前置 | selective_core | 20 | 20 | 19 | 4 | 0 | 0/8 |
| `M-PRE-UNIT-CONVERSION` | 单位换算 | 小学关键前置 | selective_core | 20 | 19 | 19 | 4 | 0 | 0/8 |

## Final Disposition

`QA_NEEDS_FIX`: count and hash lineage pass only as mechanical inventory checks. The active v11 bank is not planner-usable and is not semantically safe for child learning or mastery evidence. Regeneration and independent semantic re-review are required before release.
