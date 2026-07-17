# Math Diagnostic Student Loop Implementation Plan

> **For agentic workers:** REQUIRED: Use `multi-agent-collaboration` with 若命 as controller. Use formal role outputs from 听云, 镜花, 观止, 清秋, and 霜弦 as gates or advisory evidence. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static, validated first math diagnostic loop bound to the existing math knowledge graph.

**Architecture:** A versioned JSON file is the teaching/data artifact. A standalone HTML page embeds the diagnostic for local use and exports attempt JSON. A Node validator checks graph-node references and HTML/JSON consistency.

**Tech Stack:** JSON, standalone HTML/CSS/vanilla JS, Node.js validation script, `jq`.

---

## File Structure

- `scripts/validate_math_diagnostic_v1.mjs`: validation entrypoint for graph references, diagnostic schema, and HTML embedded ids.
- `data/questions/math_diagnostic_v1.json`: source diagnostic content.
- `app/student/math_diagnostic_v1.html`: child/parent local diagnostic page.
- `docs/diagnostics/math_diagnostic_v1.md`: parent workflow and interpretation guide.

## Task 1: Validation Script

**Files:**

- Create: `scripts/validate_math_diagnostic_v1.mjs`

- [ ] Write a Node script that loads the graph JSON, diagnostic JSON, and student HTML.
- [ ] Check required metadata fields.
- [ ] Check all sections and questions have stable ids.
- [ ] Check each question has node ids, a primary node, likely error tags, rollback nodes, scoring, and parent observation prompt.
- [ ] Check node ids exist in the math graph.
- [ ] Check the HTML embedded diagnostic ids match the JSON question ids.
- [ ] Run before artifacts exist; expected result is failure on missing diagnostic/page.

## Task 2: Diagnostic Data

**Files:**

- Create: `data/questions/math_diagnostic_v1.json`

- [ ] Create 48 original items for a 60-minute diagnostic, matching `math_knowledge_graph_v2.json` `diagnostic_blueprint`.
- [ ] Cover the five graph blueprint blocks: calculation rules, fractions/unit 1, quantity relations/equations, word-problem models, and Grade 7 entry probes.
- [ ] Bind every item to a graph node id, node snapshot, canonical error tags, rollback candidates, and source provenance.
- [ ] Include expected answer, scoring rubric, solution steps, and parent observation prompt.
- [ ] Avoid private textbook/question-bank references.
- [ ] Run `jq empty data/questions/math_diagnostic_v1.json`.

## Task 3: Student Diagnostic Page

**Files:**

- Create: `app/student/math_diagnostic_v1.html`

- [ ] Build a single-file HTML page, no framework and no external dependencies.
- [ ] Embed the diagnostic data with the same question ids as JSON.
- [ ] Provide section navigation, progress, answer input, parent result marking, error tag selection, and export JSON.
- [ ] Keep child-facing text simple and parent/graph details secondary.
- [ ] Ensure responsive layout and stable button/card dimensions.

## Task 4: Parent Guide

**Files:**

- Create: `docs/diagnostics/math_diagnostic_v1.md`

- [ ] Explain when and how to use the diagnostic.
- [ ] Explain scoring and A/B/C/D interpretation.
- [ ] Explain how to choose error tags and when to rollback.
- [ ] Explain how to save/export attempt JSON for Codex review.

## Task 5: Integration Verification

**Commands:**

```bash
node scripts/validate_math_diagnostic_v1.mjs
jq empty data/questions/math_diagnostic_v1.json
```

- [ ] Run validation fresh.
- [ ] Fix any schema, graph reference, or HTML/JSON mismatch.
- [ ] Collect subagent results and apply necessary fixes.
- [ ] Final response must include touched files, validation commands, and residual risks.
