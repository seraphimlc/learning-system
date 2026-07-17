# Math Diagnostic Student Loop Design

Date: 2026-07-05
Owner role: 若命 (`ruoming`)
Status: approved-by-delegation

## Delegated Approval Note

The user explicitly authorized autonomous multi-agent execution and said they would not interfere before reviewing results. This design records the working contract used for the first delivery. It does not expand scope beyond the project blueprint.

## Objective

Build the first usable math diagnostic loop for the private AI learning system:

- a graph-bound diagnostic question set following `diagnostic_blueprint`,
- a simple child-facing/parent-marking HTML page,
- a documented grading and rollback workflow,
- validation that the artifact is traceable to the math knowledge graph.

## Non-Goals

- No generic education product.
- No multi-user account system.
- No database or backend.
- No full fixed weekly plan.
- No private textbook, workbook, or commercial question-bank claims.
- No broad primary-school review outside graph-relevant prerequisites.

## Approach Options Considered

### Option A: Data-first static artifact

Create a versioned JSON diagnostic, a standalone HTML page, and a validator script.

Trade-off: Some duplication between JSON and page unless checked by validation.

### Option B: Tiny app with runtime JSON loading

Create a frontend that fetches the JSON file directly.

Trade-off: Better source-of-truth behavior, but local `file://` usage can fail due browser fetch restrictions and may require a dev server.

### Option C: Backend-backed diagnostic flow

Create APIs and persistence from day one.

Trade-off: Stronger long-term foundation, but too heavy for the first learning loop.

## Decision

Use Option A.

The first loop should work by opening a local HTML file directly. Data remains versioned in JSON, and the HTML embeds the same item ids. A validator checks graph node references, required fields, graph diagnostic blueprint alignment, and HTML/JSON item id consistency.

## Artifacts

- `data/questions/math_diagnostic_v1.json`
- `app/student/math_diagnostic_v1.html`
- `docs/diagnostics/math_diagnostic_v1.md`
- `scripts/validate_math_diagnostic_v1.mjs`

## Data Contract

The diagnostic JSON must include:

- top-level contract: `diagnostic_id`, `schema_version`, `diagnostic_version`, `status`, `graph_ref`, `source_policy`,
- five `blocks` matching `math_knowledge_graph_v2.json` `diagnostic_blueprint`,
- 48 `items` matching the blueprint item count,
- each item: stable id, version, block id, node id, node snapshot, prompt, answer format, expected answer, rubric, solution steps, canonical error tags, rollback candidates, source type,
- result interpretation: how to convert evidence to A/B/C/D node status.

Every `node_id`, `secondary_node_ids`, and `rollback_candidates` entry must exist in `math_knowledge_graph_v2.json`. Untested nodes remain `unknown/not_tested`; A/B/C/D states require direct evidence or an explicit inferred flag.

## Student Page Contract

The page must:

- show one question at a time or in compact sections without exposing complex graph logic first,
- let the child type answers or write on paper and then record locally,
- let the parent mark correct/partial/wrong and choose concrete error tags,
- export a JSON attempt record,
- keep page copy simple and non-judgmental,
- keep advanced node IDs available in parent details.

## UX Principles

- First screen is the actual diagnostic, not a landing page.
- Use calm, restrained colors and clear task focus.
- Avoid gamified pressure, rankings, streaks, or punitive language.
- Parent controls can be visible but visually secondary.
- Mobile must remain usable for reading and marking, though paper work is allowed.

## Validation

Run:

```bash
node scripts/validate_math_diagnostic_v1.mjs
jq empty data/questions/math_diagnostic_v1.json
```

Optional visual verification:

Open `app/student/math_diagnostic_v1.html` in a browser and test:

- mark one question correct,
- mark one question partial with an error tag,
- export result JSON,
- resize to mobile width.

## Residual Risk

- Generated questions need human taste review after first real child use.
- The diagnostic estimates time but cannot guarantee actual pace.
- The first page records local state only; persistence depends on exported JSON.
