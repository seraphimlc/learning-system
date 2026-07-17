# Learning System Architecture Review Addendum

Primary role: 镜花 (`jinghua`).

This project-local addendum is mandatory when reviewing architecture, implementation, or tests for the child learning flow, async review pipeline, internal agents, model adapters, database schema, self-evolution, planning, or reporting.

## Review Objective

镜花 must decide whether the system is technically coherent and recoverable as a whole. Do not limit review to local code style or a narrow diff when lifecycle, data, model, or agent contracts cross boundaries.

## Required Architecture Traces

For high-risk changes, trace these lifecycles end to end:

- child submission: UI task position -> child-safe API -> attempt row -> attachment row -> background job -> child projection
- review pipeline: pending attempt -> model/OCR route -> normalized review -> grade_attempt -> agent_run audit -> background job finish
- session close: expected questions -> pending/analyzed summary -> answer-analysis package -> graph binding -> evaluation -> self-evolution -> next plan -> child-safe handoff
- model adapter: provider/model config -> structured JSON support -> fallback/plain JSON -> low-confidence/pending behavior -> audit metadata
- evidence lineage: active vs invalidated, pending vs graded, analyzed vs missing analysis, real vs simulated, source attempt vs evolved question
- restart/retry: queued jobs after server restart, transient model errors, idempotent close, duplicate submit, repeated polling

## Blocking Findings

Return `DESIGN_REVIEW_NEEDS_FIX` or `CODE_REVIEW_NEEDS_FIX` when:

- normal child progress depends on parent/Codex intervention
- async review can lose or double-grade an attempt
- session close can plan from pending, invalidated, stale, or missing-analysis evidence
- model provider differences leak into business logic instead of being isolated by adapters
- child-safe API can expose internal IDs, agent names, graph internals, model/provider names, or parent workflow
- self-evolution can revise profiles or create questions without real active graded analyzed evidence
- tests can falsely pass because report verdict, exit code, DB facts, or assertions disagree

## Evidence Bar

For PASS on high-risk system work, require at least two evidence types:

- command output from unit/integration tests
- DB facts tied to sample sessions/attempts/jobs/events
- API response tied to the same sample
- browser/page evidence for child-facing flows
- code-path proof covering producer and consumer

Use `PASS_WITH_SCOPE` when only local code paths were inspected and the lifecycle was not exercised.
