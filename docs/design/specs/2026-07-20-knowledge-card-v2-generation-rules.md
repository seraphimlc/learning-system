# KnowledgeCard v2 Generation Rules

Date: 2026-07-20
Owner: 若命
Status: draft for implementation planning

## 1. Core Principle

Knowledge cards are not fixed UI templates. A card is a graph-bound teaching design package.

For every knowledge point, the system must choose the expression form that best helps the child build the correct mathematical mental model and leaves usable learning evidence. Text, diagrams, animation, dragging, number lines, balance models, relation graphs, geometry canvases, tables, voice, and photo answers are all allowed when they serve the teaching goal. Decorative interaction is not allowed.

## 2. Generation Pipeline

Every card must be generated in this order:

1. **Node reading**
   Read graph node, prerequisites, unlocks, essence, common mistakes, mastery criteria, question generation rules, and error diagnosis rules.

2. **Design brief**
   Decide the cognitive object, best expression family, target misconceptions, child actions, evidence plan, repair paths, and exit rules.

3. **Component storyboard**
   Choose a short sequence of components. Components are not page sections; they are teaching moves with evidence.

4. **Child-facing card**
   Produce the actual safe content and interaction specs.

5. **Internal card**
   Produce runtime rules, evidence interpretation, repair triggers, and next-step hints.

6. **Review gate**
   Reject cards that are only text templates, decorative demos, over-engineered for a low-value point, or unable to produce evidence.

## 3. Required Design Brief

Each KnowledgeCard v2 must include:

```json
{
  "design_brief": {
    "cognitive_object": "",
    "core_mental_model": "",
    "primary_misconceptions": [],
    "best_expression_family": [],
    "why_this_expression": "",
    "child_actions_for_evidence": [],
    "repair_expression_switches": [],
    "near_transfer_direction": [],
    "exit_rule": ""
  }
}
```

The design brief is mandatory. The model must not jump directly from graph node to UI content.

## 4. Cognitive Object Taxonomy

### 4.1 Position / Direction / Distance

Use when the essence is about location, ordering, movement, symmetry, or distance.

Best components:
- `interactive_number_line`
- `drag_point_to_value`
- `directed_move`
- `order_points`
- `distance_to_zero`
- `mirror_point`

Evidence:
- places values correctly
- distinguishes left/right and increase/decrease
- compares by position
- explains distance without sign confusion

Examples:
- 数轴
- 相反数
- 绝对值
- 有理数大小比较
- 有理数加减

### 4.2 Structure / Classification

Use when the essence is recognizing object type, components, or membership rules.

Best components:
- `sort_cards`
- `drag_grouping`
- `attribute_toggle`
- `counterexample_choice`
- `definition_boundary_check`

Evidence:
- identifies defining attributes
- rejects look-alikes
- classifies mixed cases
- explains why an item belongs or does not belong

Examples:
- 有理数分类
- 单项式
- 多项式
- 同类项
- 方程与一元一次方程概念
- 直线、射线、线段

### 4.3 Symbol Transformation / Procedure

Use when the essence is a sequence of legal transformations or symbolic rules.

Best components:
- `step_animation`
- `symbol_transform`
- `color_term_tracking`
- `operation_order_trace`
- `error_spotting`
- `fill_missing_step`

Evidence:
- applies the rule to every relevant part
- preserves equivalent value or relation
- finds illegal transformations
- can complete the next step without rote copying

Examples:
- 四则混合运算与括号
- 分数运算
- 运算律与去括号意识
- 合并同类项
- 去括号
- 整式加减
- 解一元一次方程基础
- 含括号方程
- 含分母方程

### 4.4 Quantity Relation / Modeling

Use when the essence is reading a situation and representing relationships.

Best components:
- `condition_cards`
- `relation_diagram`
- `segment_diagram`
- `table_builder`
- `equation_builder`
- `known_unknown_mapper`

Evidence:
- separates quantities, units, and question target
- builds a relation before computing
- maps words to equation or diagram
- detects missing or extra conditions

Examples:
- 等量关系与列式
- 应用题审题流程
- 方程应用题
- 行程基础模型
- 追及与相遇模型
- 百分数应用模型
- 比例应用与对应量表
- 和差倍模型
- 工程问题

### 4.5 Balance / Equivalence

Use when the essence is equality, inverse operations, or preserving relation.

Best components:
- `balance_model`
- `two_side_operation`
- `equivalence_transform`
- `solve_path_compare`
- `substitution_check`

Evidence:
- performs same operation on both sides
- understands equation as relation, not a command to calculate
- checks solution by substitution
- chooses an efficient transformation

Examples:
- 小学简易方程
- 等式性质
- 解一元一次方程基础
- 含括号方程
- 含分母方程

### 4.6 Spatial / Geometric Object

Use when the essence is shape, part-whole, angle, line, surface, solid, or view transformation.

Best components:
- `geometry_canvas`
- `label_point_line_angle`
- `drag_measure`
- `angle_sweep`
- `fold_unfold`
- `view_rotation`
- `part_whole_highlight`

Evidence:
- marks the correct geometric object
- distinguishes similar geometric terms
- relates parts to whole
- transfers between view, net, and solid

Examples:
- 角的概念与表示
- 角度基础
- 角度计算
- 线段比较与计算
- 点线面体
- 立体图形与平面图形
- 展开图与视图
- 面积体积公式理解

### 4.7 Estimation / Reasonableness

Use when the essence is judging scale, approximate range, or sanity checking.

Best components:
- `range_slider_estimate`
- `benchmark_compare`
- `reasonableness_meter`
- `rough_compute_then_refine`
- `choose_plausible_answer`

Evidence:
- predicts range before exact calculation
- rejects absurd results
- uses benchmark numbers
- explains approximation error direction

Examples:
- 数感与估算
- 科学记数法与近似数
- 小数运算
- 百分数与增长率

### 4.8 Process / Metacognitive Habit

Use when the essence is solution discipline, checking, expression, or repair habit.

Best components:
- `solution_audit_checklist`
- `mark_key_relation`
- `find_faulty_work`
- `rewrite_solution`
- `photo_answer_prompt`
- `self_explanation_prompt`

Evidence:
- writes key relation
- checks answer against question
- identifies the error type
- can rewrite a thin solution into a scorable solution

Examples:
- 解题步骤与检验习惯
- 应用题审题流程
- 单位换算

## 5. Component Selection Rules

1. Use the fewest components that can establish the mental model and evidence.
2. Prefer interaction when the concept is spatial, directional, relational, or procedural.
3. Prefer text-only only when the knowledge point is definitional and a counterexample check is enough.
4. Use animation only when the change over time is the concept: movement, transformation, folding, balancing, or sign reversal.
5. Every component must declare:
   - `purpose`
   - `target_evidence`
   - `misconception_target`
   - `child_action`
   - `success_signal`
   - `fallback_if_failed`
6. A card must contain at least one evidence-producing action unless it is a short transitional explanation invoked inside a larger runtime step.
7. No component may exist only because it looks engaging.

## 6. Evidence Strength Rules

Evidence strength should be interpreted by action type:

- **Strong evidence**
  Child performs a meaningful action and explains the reason: drag + reason, equation + explanation, diagram + relation, or photo + process.

- **Medium evidence**
  Child performs the action correctly but gives little explanation. Use one near-transfer or explanation micro-check.

- **Weak evidence**
  Child watches, clicks continue, chooses without explanation, or gives an answer-only response. Do not mark mastery stable.

- **Insufficient evidence**
  Low-confidence photo, unclear interaction, contradiction between text/photo, or component completion without mathematical intent.

## 7. Repair Rules

Repair should switch representation when possible:

- Direction error on number line -> movement-only interaction before calculation.
- Negative comparison error -> number line order before absolute value rule.
- Symbol sign error -> color term tracking and error spotting.
- Equation transformation error -> balance model before algebra steps.
- Modeling error -> condition cards and relation diagram before computation.
- Geometry object confusion -> direct labeling and counterexample comparison.
- Unit/dimension error -> unit ladder or area/volume dimension visual.

Do not repair by repeating the same explanation with different words unless the original failure was only wording comprehension.

## 8. Exit Rules

A card should stop or move on when:

- the child completes core evidence plus one near-transfer check;
- the node is simple and downstream nodes will reuse it;
- repeated same-structure checks have reached the card limit;
- the child is blocked on a prerequisite, in which case runtime should move to the prerequisite card;
- evidence is insufficient because of UI/photo clarity, in which case ask for clarification instead of teaching more.

## 9. Initial Node-to-Expression Mapping

| Node | Primary Expression Family | Notes |
| --- | --- | --- |
| 解题步骤与检验习惯 | process / metacognitive habit | solution audit, error spotting, photo answer |
| 小数运算 | estimation + procedure | place-value movement, rough compute, decimal point trace |
| 整数四则计算 | procedure | only if weak; use error spotting and operation-order trace, not low-level drills |
| 数感与估算 | estimation | benchmark, range, reasonableness meter |
| 四则混合运算与括号 | symbol transformation | operation-order trace |
| 分数意义与单位1 | structure + quantity model | area/segment representation, unit-1 selection |
| 分数运算 | procedure | denominator alignment, fraction bar model |
| 百分数与增长率 | estimation + quantity relation | unit-1 and change model |
| 比、比例与比例思想 | quantity relation | corresponding quantity table |
| 运算律与去括号意识 | symbol transformation | color distribution and term tracking |
| 小学简易方程 | balance / equivalence | balance model |
| 用字母表示数 | structure / abstraction | variable-as-changing-number examples |
| 等量关系与列式 | quantity relation | relation diagram, known/unknown mapping |
| 应用题审题流程 | process + modeling | condition cards |
| 行程基础模型 | quantity relation | speed-time-distance table and line diagram |
| 追及与相遇模型 | quantity relation + movement | dynamic distance closing/opening |
| 百分数应用模型 | quantity relation | standard amount/change amount diagram |
| 比例应用与对应量表 | quantity relation | correspondence table |
| 和差倍模型 | quantity relation | segment diagram |
| 钟表角问题 | spatial + movement | clock angle sweep |
| 工程问题 | quantity relation | work-rate table, total-as-1 model |
| 绝对值 | position / distance | distance-to-zero number line |
| 有理数大小比较 | position / classification | order points and negative counterexamples |
| 数轴 | position / direction / distance | interactive number line |
| 相反数 | position / symmetry | mirror point around zero |
| 正数和负数 | structure + context | opposite-meaning context cards |
| 有理数加减 | position / movement | directed move number line |
| 有理数分类 | structure / classification | sort cards with boundary cases |
| 有理数混合运算 | procedure | sign + order trace |
| 有理数乘除 | procedure + sign rule | sign decision then absolute calculation |
| 乘方 | structure + procedure | base/exponent highlighting and counterexamples |
| 科学记数法与近似数 | estimation + notation | magnitude slider, decimal-shift animation |
| 代数式 | quantity relation + abstraction | expression builder |
| 合并同类项 | structure + procedure | drag grouping, coefficient merge |
| 代数式求值 | procedure | substitution trace |
| 同类项 | structure / classification | attribute matching |
| 去括号 | symbol transformation | sign-flip animation and error spotting |
| 整式加减 | symbol transformation | bracket removal + like-term grouping |
| 单项式 | structure / classification | object boundary check |
| 多项式 | structure / classification | term decomposition |
| 含括号方程 | balance + symbol transformation | balance plus bracket handling |
| 解一元一次方程基础 | balance / equivalence | two-side operation |
| 一元一次方程应用题 | modeling + balance | relation diagram to equation |
| 等式性质 | balance / equivalence | balance model |
| 方程与一元一次方程概念 | structure / classification | equation vs expression boundary |
| 含分母方程 | balance + procedure | common multiplier applied to every term |
| 角的概念与表示 | spatial / geometric object | angle labeling and sweep |
| 直线、射线、线段 | spatial / classification | endpoint/extension comparison |
| 角度计算 | spatial + procedure | part-whole angle highlight |
| 立体图形与平面图形 | spatial transformation | solid-to-plane view |
| 点线面体 | spatial / hierarchy | object hierarchy visual |
| 线段比较与计算 | spatial + procedure | segment part-whole |
| 展开图与视图 | spatial transformation | fold/unfold and view rotation |
| 角度基础 | spatial / movement | angle sweep |
| 面积体积公式理解 | spatial + quantity relation | cut-and-recompose, base-area-times-height |
| 单位换算 | process + dimension | unit ladder and dimension-aware conversion |

## 10. KnowledgeCard v2 Shape

```json
{
  "schema_version": "knowledge-card.v2",
  "node_id": "",
  "card_version": "",
  "design_brief": {},
  "teaching_contract": {
    "essence": "",
    "core_model": "",
    "minimum_child_takeaway": "",
    "must_not_teach_as": []
  },
  "component_storyboard": [
    {
      "component_id": "",
      "type": "",
      "purpose": "",
      "child_action": "",
      "target_evidence": [],
      "misconception_target": [],
      "success_signal": "",
      "fallback_if_failed": ""
    }
  ],
  "evidence_plan": {
    "core_evidence": [],
    "near_transfer_evidence": [],
    "insufficient_evidence_cases": []
  },
  "repair_paths": [],
  "exit_rules": {},
  "child_card": {},
  "internal_card": {}
}
```

## 11. Review Gate

Reject a generated card if any condition is true:

- design brief is missing or generic;
- all nodes use the same component sequence;
- card is mostly prose when the concept is spatial, relational, or procedural;
- component does not generate evidence;
- visual or animation has no stated misconception or evidence target;
- child action is merely "read" or "continue" for a non-transitional card;
- repair path repeats the same explanation instead of switching representation;
- exit rule encourages repeated same-structure practice after sufficient evidence;
- child-facing content leaks graph ids, agent terms, internal dimensions, rubric, queue, model, or runtime policy.

## 12. Implementation Notes

- Keep graph, cards, question bank, answer contracts, and learning records separate.
- The current `M-G7-NUMBER-LINE.v1.json` remains a first slice, not the final v2 standard.
- Runtime should select card components based on state, not render the whole card every time.
- AI can propose design briefs and storyboards, but programmatic gates must validate component types, evidence fields, child-safe projection, and graph binding.
