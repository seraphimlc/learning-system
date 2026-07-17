### UX_REVIEW / PASS_WITH_SCOPE - 清秋（agentKey: `qingqiu`）- 2026-07-08 00:00 CST

Verdict:
`UX_REVIEW_PASS_WITH_SCOPE`.

The technical package is UX-ready enough to proceed to skeleton and test-case design for the child-only page. It correctly treats `docs/product/child_ux_flow_spec_v2.md` as a binding source, carries the required child-visible state model into the route-shell plan, includes the answer/photo/save-and-advance path, covers the 10/10 reviewing and all-question review states, and keeps the child/operator boundary explicit.

This is not a rendered visual pass. Final visual taste, exact child copy, layout polish, mobile behavior, focus behavior, and all screenshot-based claims remain open until the later SKELETON_PASS/rendered review.

independence_required:
`no`

context_mode:
`fresh`

context_origin:
Prior UX spec exists as source artifact. This review only checks technical consumption of that UX spec in planning artifacts.

diff_pin:
Reviewed `docs/architecture/technical_plan_v2.md` against `docs/product/child_ux_flow_spec_v2.md`.

Scope:
- Planning artifacts only.
- No rendered implementation review.
- No production code or implementation files edited.
- Fact sources under `app/local_learning_system/*` were not needed because the question was whether the technical plan/skeleton definition consumes the UX spec.

Project boundary overlay:
Source: `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`.

Applied rules:
- Single child, math-only, local/private learning system.
- Child uses one Web child端; parent uses Codex, not a parent dashboard.
- Normal learning must not require parent intervention.
- Child page must support open written answers and photo upload.
- Save must advance without waiting for model grading.
- End-of-round waiting must be safe/retryable.
- Review must show all relevant per-question feedback, not only the last question.
- Child-facing copy must not expose graph/model/agent/rubric/operator internals.
- Final visual taste and exact child copy are explicitly still open.

User task:
The child can independently know the current task, answer openly, upload a paper-work photo, save and advance through a 10-task round, wait/retry safely after all tasks are submitted, read all-question feedback, and see a next action without parent intervention.

UX risk:
High. The surface is small, but the interaction is stateful, async, child-facing, photo-enabled, model-dependent, and easy to falsely pass if only the happy path is tested.

Design read:
The UX spec defines the child page as a focused single-task learning workspace with calm editorial clarity, medium density, minimal purposeful motion, simple child-safe state language, and no dashboard/landing-page/mascot treatment.

The technical plan does not restate the full design read line by line, but it correctly references the UX spec as consumed, keeps the page as one focused child learning surface, requires deterministic fixture states and screenshots, and names visual taste as provisional. That is sufficient for this planning gate as long as the later skeleton review continues to use the UX spec itself as the binding design-read source.

Visual / interaction quality bar:
The UX spec requires quick task orientation, stable layout, one primary CTA per state, complete loading/empty/error/success coverage, child-safe copy, responsive/mobile behavior, and accessibility coverage.

The technical plan/skeleton definition consumes the interaction quality bar adequately for skeleton design:
- route-shell states include `loading`, `empty`, `active_task`, `saving`, `all_submitted_reviewing`, `review_ready`, `blocked`, `load_error`, and `save_error`;
- page prototype plan adds `upload_error`, photo preview, review points, pending/blocked completion, desktop/mobile screenshots, text overflow checks, and keyboard/focus checks;
- project skeleton definition requires a state enum, fixture renderer, photo picker/preview/remove, primary CTA, all-question review list, blocked/retry state, and no internal leakage;
- later validation explicitly calls for visual/state browser tests and rendered desktop/mobile screenshots.

Evidence:
- `docs/product/child_ux_flow_spec_v2.md` defines the required child flow, states, answer/photo/save-and-advance behavior, all-10 reviewing, all-question review, accessibility/responsive expectations, and child-copy boundaries.
- `docs/architecture/technical_plan_v2.md` section `UX flow spec` names the UX spec and mirrors the child-visible state model.
- `docs/architecture/technical_plan_v2.md` interface contracts define child bootstrap/submission/complete endpoints with handle/position inputs, photo data, child-safe responses, and no raw ids.
- `docs/architecture/technical_plan_v2.md` page prototype / route shell plan defines the `/` child page states and fixture DTOs for 10 tasks, photo preview, review points, pending/blocked completion, desktop/mobile screenshots, text overflow, and keyboard/focus.
- `docs/architecture/technical_plan_v2.md` project skeleton definition requires the child frontend shell to expose the state enum, fixture renderer, photo picker/preview/remove, primary CTA, all-question review list, blocked/retry state, and no internal leakage.
- `docs/product/ai_native_math_learning_prd_v2.md` confirms the project boundary overlay and UX/product constraints.

States inspected:
- `loading`
- `empty` / no active group
- `active_task`
- answer draft
- photo selected / upload error
- `saving`
- save error
- saved and advance
- all 10 submitted
- `all_submitted_reviewing`
- review pending / retry
- `review_ready`
- all-question review list
- next action
- blocked / wait later
- load error

Findings:
1. PASS - Required child states are represented in the technical plan and skeleton definition.
   Impact: 听云 can build a route shell without inventing the state model.
   Evidence: UX spec state list is mirrored in the technical plan's `UX flow spec`, page prototype plan, and skeleton definition.
   Recommendation: In SKELETON_PASS, expose deterministic fixtures for every listed state before business logic fill.

2. PASS - Answer/photo/save-and-advance behavior is consumed correctly at planning level.
   Impact: The page skeleton can support typed reasoning, optional photo evidence, validation errors, immediate advancement after save, and async review.
   Evidence: Child submission contract uses `session_handle=current-learning-group`, `task_position`, optional `answer_raw`, optional `answer_photo_data_url`, and child-safe errors; route shell includes photo preview and upload error.
   Recommendation: Later tests must prove save advances before grading and preserves draft/photo on recoverable save failures where technically feasible.

3. PASS - All-10-submitted reviewing and all-question review are included.
   Impact: The child should not be stranded after task 10 and should eventually see review across relevant questions, not only the last item.
   Evidence: Complete endpoint includes `waiting_ai|blocked|planned`; page prototype includes `all_submitted_reviewing` and `review_ready`; skeleton requires all-question review list and blocked/retry state.
   Recommendation: Later QA should false-pass check 10 submitted + pending review, blocked/model-disabled review, and review-ready with 10 review points.

4. PASS_WITH_SCOPE - Design read and visual quality bar are consumed by reference, not fully duplicated in the technical skeleton table.
   Impact: This is acceptable for planning, but only if downstream skeleton work keeps `child_ux_flow_spec_v2.md` open as the binding design source.
   Evidence: The plan names UX spec consumption and requires screenshots/visual state tests, but the project skeleton definition itself is briefer on exact layout rhythm, one-panel focus, live regions, 44px targets, reduced motion, and child-copy tone.
   Recommendation: The later SKELETON_PASS should cite the UX spec directly and demonstrate semantic headings, labels, live regions, keyboard/focus order, mobile layout, and no internal-copy leakage in fixture states.

5. PASS_WITH_SCOPE - Mobile/accessibility are planned, not proven.
   Impact: The technical package is sufficient to design skeleton/test cases, but no visual/accessibility pass can be claimed yet.
   Evidence: Plan calls for desktop/mobile screenshots, text overflow checks, keyboard/focus validation, semantic child layout, responsive styles, and focus/error/review states.
   Recommendation: Rendered review must inspect desktop and mobile screenshots for active, photo-preview, saving/error, reviewing, review-ready, blocked, and no-group states.

6. PASS - Child-safe copy boundary is preserved at plan level.
   Impact: The child page should avoid graph/model/agent/rubric/operator leakage.
   Evidence: Technical plan explicitly blocks graph ids, question ids, attempt ids, session ids, model/provider names, agent names, rubrics, OCR confidence, queue internals, and operator actions from child state; child API projection rejects raw ids.
   Recommendation: Add forbidden-term scans or DOM assertions in later browser tests.

Not covered:
- Rendered visual polish.
- Final aesthetic taste.
- Exact child-facing copy.
- Actual browser/mobile screenshots.
- Actual keyboard/focus traversal.
- Actual contrast calculation.
- Real API behavior or DB state.
- Implementation fidelity.

Residual risk:
- If implementers read only the compact project skeleton table and skip the full UX spec, subtle UX requirements could be missed: one primary CTA per state, calm child-safe wording, live regions, reduced motion, 44px touch targets, and focus movement after save/review-ready.
- Fixture states can falsely pass if they show the right state names but not the real child comprehension path.
- Copy still needs human taste review with real prompts/review points; this gate cannot judge whether the final tone feels age-respectful and motivating.

Required next action:
Proceed to SKELETON_PASS and TEST_CASE_SPEC design, with `docs/product/child_ux_flow_spec_v2.md` treated as a binding source for the child route shell. The skeleton must provide deterministic fixture states and rendered evidence later before any visual PASS or final child-copy acceptance is claimed.
