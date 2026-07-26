# Batch Production Workflow

Status: `BATCH_COMPLETED_WITH_FAILURES`

Batch ID: `BATCH-b4ead1aff92d`

Created At: 2026-07-25T08:32:42.140465+00:00

Requested Plans: 9

Executed Slots: 9

Staged Slots: 0

Failed Slots: 9

Skipped Slots: 0

Blocked Reason: ``

Activation Implication: `does_not_authorize_activation`

Blocking Code Counts: `{"blocked_model_error": 8, "child_surface_invalid_interaction_schema": 1, "child_surface_required_explanation_missing_writing_space": 2, "child_surface_writing_burden_understates_deliverables": 2, "machine_check_blocks_loop": 2}`

## Slot Workflows

| Workflow | Status | Attempts | Seconds | Item | Blocking Codes | Report |
|---|---|---:|---:|---|---|---|
| WF-93f6aba211ab | BLOCKED_MODEL_ERROR | 2 | 88.392 | CAND-331b880cdc6f | blocked_model_error, child_surface_required_explanation_missing_writing_space, child_surface_writing_burden_understates_deliverables, machine_check_blocks_loop | data/admin/workflows/WF-93f6aba211ab.json |
| WF-b038ecf4f8d9 | BLOCKED_MODEL_ERROR | 1 | 45.035 |  | blocked_model_error | data/admin/workflows/WF-b038ecf4f8d9.json |
| WF-11e0a7cacd81 | BLOCKED_MODEL_ERROR | 1 | 45.146 |  | blocked_model_error | data/admin/workflows/WF-11e0a7cacd81.json |
| WF-d9deb4fcc0ab | BLOCKED_MODEL_ERROR | 1 | 45.133 |  | blocked_model_error | data/admin/workflows/WF-d9deb4fcc0ab.json |
| WF-ab996e825fef | BLOCKED_MODEL_ERROR | 1 | 45.118 |  | blocked_model_error | data/admin/workflows/WF-ab996e825fef.json |
| WF-cee73d0920fc | BLOCKED_MODEL_ERROR | 1 | 45.118 |  | blocked_model_error | data/admin/workflows/WF-cee73d0920fc.json |
| WF-fc5e87006edd | BLOCKED_MODEL_ERROR | 1 | 45.117 |  | blocked_model_error | data/admin/workflows/WF-fc5e87006edd.json |
| WF-70fa1acd098e | BLOCKED_MODEL_ERROR | 1 | 45.059 |  | blocked_model_error | data/admin/workflows/WF-70fa1acd098e.json |
| WF-12ed6b259763 | LOOP_BLOCKED_MAX_ATTEMPTS | 3 | 119.495 | CAND-c315aa0d3642 | child_surface_invalid_interaction_schema, child_surface_required_explanation_missing_writing_space, child_surface_writing_burden_understates_deliverables, machine_check_blocks_loop | data/admin/workflows/WF-12ed6b259763.json |
