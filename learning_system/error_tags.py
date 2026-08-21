"""Single source of truth for canonical error tags (M4-1 Task 1 收口).

Consolidates the two previously inline definitions (audit record 核对项 7,
docs/design/specs/2026-08-20-dataflow-audit-record.md): `learning_system/auto_review.py`
and `learning_system/question_bank.py` each carried a byte-identical 6-tag set
literal with no drift guard. This module is now the **唯一导入源**:

- batch-grading normalization (auto_review) and question-bank filtering
  (question_bank) share the same object;
- `error_cause_log.error_tag` (M4-1 Task 2, three-year error-cause distribution)
  anchors on this enum, so the distribution can never drift from grading/output
  sides.

Tag semantics:
- calculation_or_symbol — 计算/符号错误（含单位、符号混用）
- concept_confusion — 概念混淆、关系不清
- modeling_or_reading — 建模或读题错误
- process_habit — 过程习惯（步骤、检查、书写、复盘）
- visual_spatial — 视觉/空间（看图、几何位置、图形关系）
- general — 兜底标签（无法归入以上五类时）
"""

CANONICAL_ERROR_TAGS = {
    "calculation_or_symbol",
    "concept_confusion",
    "modeling_or_reading",
    "process_habit",
    "visual_spatial",
    "general",
}
