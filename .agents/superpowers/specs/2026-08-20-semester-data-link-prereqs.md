# 学期模式数据链路前置：现状数据流核对 + 答案机器校验 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成设计稿 `docs/design/specs/2026-08-20-child-learning-companion-design.md` §8 切片的前置工作——产出《现状数据流核对记录》（裁定数据模型改动依据），并交付答案机器校验服务（sympy，算术/方程题答案可复现验证）。

**Architecture:** 两个独立 chunk：① 现状核对是只读分析，产出决策记录文档（不改任何代码/数据）；② 答案校验是纯函数服务模块 + 批量审计脚本，不接入运行时（避免在 v20 生题与 visuals 重构期间动运行时行为），以单元测试锁定行为。

**Tech Stack:** Python 3.13、sympy 1.13.1（已安装，无需装依赖）、unittest（项目现有测试风格）、sqlite3。

**计划范围与后续计划的关系：**
- 本计划只做切片中**不依赖未决事项**的部分：第 0 步核对（§8.1）+ 答案校验服务（§8.3 P0）。
- **阶段数组改造（learning_path）** → 后续计划：需第 0 步 phase_strategy 裁定结果 + v20 生题结束后（避免 digest 联动 churn）。
- **判定口径统一（M2.5）** → 后续计划：需权衡的 `mastery_criteria_proposal` 交付。
- 周信/错题录入/档案表（M4）、动机层/简报（M5）、测试套件默认绿（M1）→ 各自后续计划。

---

## Chunk 1: 现状数据流核对（只读分析，产出决策记录）

**交付物:** `docs/design/specs/2026-08-20-dataflow-audit-record.md` —— 逐项核对记录 + 裁定点结论（每个裁定点必须给出：现状 / 冲突 / 选择 / 影响，或明确"挂起待 X"）。

### Task 1: 创建核对记录文档骨架

**Files:**
- Create: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 创建文档骨架**（标题 + 核对清单表 + 裁定点模板）。核对清单（来自设计稿 §8.1）：
  1. attempts / learner_node_status / mastery_decisions 表与消费方
  2. generated_plans / daily_flows（短期计划现状）
  3. **已裁定新增表：error_cause_log / weekly_summary（A/B/C/D 时间快照 + acknowledged 枚举）/ "作业全对"确认载体 → "新增 vs 别名"裁定**（spec §8.1 必答项首项）
  4. attempts FK 三方案影响（question_id/session_id NOT NULL）
  5. phase_strategy 现状（5 阶段 → 迁移裁定）
  6. 判定口径逐实现（evolution / flow_nodes / daily_runtime / 蓝图）
  7. CANONICAL_ERROR_TAGS 双定义（auto_review.py / question_bank.py）
- [ ] **Step 2: 记录模板**：每个核对项一节，含"现状（证据：文件:行）/ 裁定点 / 结论（或挂起原因）"。

### Task 2: 核对长期状态表（attempts / learner_node_status / mastery_decisions）

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对 `attempts` 表**（`learning_system/db.py` L418 起）：列、FK（session_id/question_id NOT NULL REFERENCES）、answer_source 枚举（默认 'legacy'）。
- [ ] **Step 2: 核对 `learner_node_status`**（L534 起）：status_revision 语义、evidence_attempt_ids_json/source_attempt_ids_json。
- [ ] **Step 3: 核对 `mastery_decisions`**（L643 起）：确认 append-only（只 insert），old_status_id/new_status_code 字段。
- [ ] **Step 4: 记录消费方**：`grep -rn "mastery_decisions\|learner_node_status" learning_system/ --include="*.py"` 列主要读写方，填入文档"现状"。
- [ ] **Step 5: 裁定记录**：这些表是否满足"长期档案 append-only"需求 → 结论写回文档（预期：满足，无需新建 node_mastery_log）。

### Task 3: 核对已裁定新增表（新增 vs 别名，spec §8.1 必答项）

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对 `error_cause_log`**：`grep -rn "error_cause\|wrong_cause" learning_system/db.py` 确认现有表能否覆盖"错因三年分布"（预期：无现成表，需新增；`attempts.error_tags_json` 仅存单次错因标签，无跨期聚合语义）。
- [ ] **Step 2: 核对 `weekly_summary`**：确认无现成表；记录设计稿要求（append-only、A/B/C/D 时间快照、爸爸确认状态 acknowledged/unacknowledged）。
- [ ] **Step 3: 核对"作业全对"确认载体**：确认无现成载体；记录设计稿要求（只作证据范围标注、不进判定样本）。
- [ ] **Step 4: 裁定记录**：三者的"新增 vs 别名"结论 + 最小 schema 草案（列清单，细节留 M4 计划）写回文档。

### Task 4: 核对短期计划表（generated_plans / daily_flows）

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对 `generated_plans`**（`db.py` L572 起）与 `daily_flows`（L1013 起）：列、与节点/阶段的关系。
- [ ] **Step 2: 核对 `learning_path` 现状**：`data/knowledge_graphs/math/math_knowledge_graph_v2.json` 的 `learning_path`（规划配置 dict，非档案）。
- [ ] **Step 3: 裁定记录**：短期计划是否满足"阶段数组可重排" → 结论写回（预期：结构与设计稿 §3.3 兼容，改造留到阶段数组计划）。

### Task 5: attempts FK 三方案影响评估（第 0 步必答项）

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 枚举 FK 依赖**：`grep -rn "join question_items\|join attempts\|references question_items\|references learning_sessions" learning_system/ --include="*.py"` 列出**全库运行时 JOIN 依赖清单**（实测有 20+ 处，如 agents.py L60、daily_runtime.py L7635/L12506/L14623、planner.py L357/382、question_bank.py L4407）——这是"方案① 可空化联动影响"的核心证据，逐条记录语义（INNER JOIN 对 NULL question_id 的行为变化）。
- [ ] **Step 2: 评估三方案**：
  - 方案① 可空化 question_id/session_id：对照 Step 1 依赖清单，列受影响 join/索引（含 `idx_v3_attempts_one_active_per_step` L1475）；
  - 方案② 合成占位 question/session：评估对 question_items 统计与 learning_sessions 的污染；
  - 方案③ 旁挂侧表（如 `manual_error_entries`）再反链 attempts：评估与现有证据链的一致性。
- [ ] **Step 3: 裁定记录**：给出推荐方案 + 影响清单（此项结论直接决定 M4 错题录入的 schema 改动）。

### Task 6: phase_strategy 现状核对与迁移裁定

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对现网 5 阶段**：`math_knowledge_graph_v2.json` 的 `learning_path.phase_strategy`（第1-3天建档 / 第4-12天快补 / 第13-35天主线 / 第36-44天混合 / 第45-50天收口）。
- [ ] **Step 2: 核对与新设计的冲突**：建档（挂下一假期）、快补（§4.3 不做预防性补差）与新执行窗口冲突。
- [ ] **Step 3: 裁定记录**：旧 5 阶段去留三选项（折叠进"暑假衔接收口" / 裁剪建档与快补两段 / 保留为历史快照）——给出推荐（预期：折叠 + 裁剪，保留主线/混合/收口语义），标注"最终裁定随阶段数组计划执行"。

### Task 7: 判定口径逐实现核对

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对 `evolution.py`**：`_status_from_attempts`（0.85/0.60 + can_explain + 最小样本）。
- [ ] **Step 2: 核对 `flow_nodes.py`**：`_mastery_diagnosis`（6 态：blocked/unstable/emerging/stable/likely_stable/insufficient_evidence + 0.6 边界）。
- [ ] **Step 3: 核对 `daily_runtime.py`**：v51 mastery_recommendation → A/B/C/D status_code 映射。
- [ ] **Step 4: 核对蓝图 §12**：`docs/00_PROJECT_BLUEPRINT.md`（A≥85% / B 60-85% / C<60%）。
- [ ] **Step 5: 裁定记录**：四套口径差异表（阈值/状态枚举/证据要求），结论"裁定交给 M2.5（权衡 mastery_criteria_proposal），本步只录现状"。

### Task 8: CANONICAL_ERROR_TAGS 双定义核对 + 定稿

**Files:**
- Modify: `docs/design/specs/2026-08-20-dataflow-audit-record.md`

- [ ] **Step 1: 核对双定义**：`learning_system/auto_review.py` L10 与 `learning_system/question_bank.py` L16 的 `CANONICAL_ERROR_TAGS`（逐字一致？）。
- [ ] **Step 2: 记录收口建议**：双定义收口为单一导入源（防三年错因分布漂移），列为后续计划项。
- [ ] **Step 3: 定稿自检（可机检）**：`grep -c "结论\|挂起" docs/design/specs/2026-08-20-dataflow-audit-record.md` ≥ 7（每个核对项至少一个"结论/挂起"）；`grep -c "^### " docs/design/specs/2026-08-20-dataflow-audit-record.md` ≥ 7（7 项核对标题齐全）；文档头标注"仅供设计决策参考，不改任何代码/数据"。
- [ ] **Step 4: Commit**
  ```bash
  git add docs/design/specs/2026-08-20-dataflow-audit-record.md
  git commit -m "docs: data-flow audit record (semester data-link prerequisites)"
  ```

**Chunk 1 完成条件**：`2026-08-20-dataflow-audit-record.md` 完整，**7 项核对**（原 6 项 + 新增 vs 别名）齐全，每项含"结论/挂起"，无未决裁定点遗留（除显式标注"挂起待 X"的）。

---

## Chunk 2: 答案机器校验服务（sympy，TDD）

**交付物:** `learning_system/answer_verification.py`（纯函数服务）+ `tests/test_answer_verification.py` + `scripts/audit_question_bank_answers.py`（批量审计脚本）。

### Task 9: 核心原语 is_math_equivalent（TDD）

**Files:**
- Create: `tests/test_answer_verification.py`
- Create: `learning_system/answer_verification.py`

- [ ] **Step 1: 写失败测试**（测试用 `unittest.TestCase`——项目唯一测试风格，`unittest` 不收集裸函数）
  ```python
  import unittest

  from learning_system.answer_verification import is_math_equivalent


  class TestMathEquivalent(unittest.TestCase):
      def test_equivalent_fraction_and_decimal(self):
          self.assertTrue(is_math_equivalent("3/4 + 5/6", "19/12"))  # 3/4+5/6 = 19/12
          self.assertTrue(is_math_equivalent("1.5", "3/2"))
          self.assertTrue(is_math_equivalent("6/4", "1.5"))

      def test_mismatch_returns_false(self):
          self.assertFalse(is_math_equivalent("1/2", "2/3"))
          self.assertFalse(is_math_equivalent("3", "4"))

      def test_invalid_input_returns_false(self):
          self.assertFalse(is_math_equivalent("abc", "1"))
          self.assertFalse(is_math_equivalent("", "1"))


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **Step 2: 运行确认失败**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: 红（unittest ERROR: `ModuleNotFoundError: No module named 'learning_system.answer_verification'`）

- [ ] **Step 3: 最小实现**
  ```python
  # learning_system/answer_verification.py
  """Math answer verification via sympy (calculation-answer底线校验)."""
  from __future__ import annotations

  import sympy as sp

  def is_math_equivalent(a: str, b: str, *, tolerance: float = 1e-9) -> bool:
      """True if two math answer strings are equivalent (3/2 == 1.5 == 6/4).

      注：符号等价（如 is_math_equivalent("x", "x")）也返回 True——超出
      "算术题底线校验"语义但无害；如需收紧，后续计划在调用侧限定数值域。
      """
      try:
          diff = sp.simplify(sp.sympify(a) - sp.sympify(b))
      except (sp.SympifyError, TypeError, ValueError):
          return False
      if diff == 0:
          return True
      try:
          return abs(float(diff)) <= tolerance
      except (TypeError, ValueError):
          return False
  ```

- [ ] **Step 4: 运行确认通过**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: PASS（3 个测试）

- [ ] **Step 5: Commit**
  ```bash
  git add learning_system/answer_verification.py tests/test_answer_verification.py
  git commit -m "feat: add sympy math-equivalence answer primitive"
  ```

### Task 10: 表达式提取（TDD）

**Files:**
- Modify: `learning_system/answer_verification.py`
- Modify: `tests/test_answer_verification.py`

- [ ] **Step 1: 写失败测试**（**追加到 `tests/test_answer_verification.py` 文件末尾、`if __name__ == "__main__"` 之前**，复用文件顶部已有 `import unittest`；不要重写整个文件，否则会删掉前面 Task 的类）
  ```python
  from learning_system.answer_verification import extract_calculation


  class TestExtractCalculation(unittest.TestCase):
      def test_extracts_plain_expression(self):
          self.assertEqual(extract_calculation("计算：3/4 + 5/6 的结果"), "3/4 + 5/6")

      def test_handles_unicode_operators(self):
          self.assertEqual(extract_calculation("计算：2 × 3 ÷ 4"), "2 * 3 / 4")

      def test_no_calculation_returns_none(self):
          self.assertIsNone(extract_calculation("下列说法正确的是（ ）"))

      def test_invalid_expression_returns_none(self):
          self.assertIsNone(extract_calculation("计算：abracadabra"))
  ```

- [ ] **Step 2: 运行确认失败**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: 红（unittest ERROR: `ImportError: cannot import name 'extract_calculation'`）

- [ ] **Step 3: 最小实现**（追加到 `answer_verification.py`；**注意 `import re` 并入文件顶部 import 区**，不要写在函数之间）
  ```python
  import re

  _CALC_PATTERN = re.compile(r"计算[:：]?\s*([0-9+\-*/×÷^().\s]+)")
  _UNICODE_MAP = {"×": "*", "÷": "/", "−": "-", "－": "-"}

  def extract_calculation(prompt: str) -> str | None:
      """Extract a machine-checkable arithmetic expression from a prompt, or None.

      边界（底线校验可接受）："计算下列各题：…"（非冒号）返回 None；
      "计算：1/2 与 1/3 的大小"会误截半表达式——审计报告需据此解读计数。"""
      match = _CALC_PATTERN.search(prompt)
      if not match:
          return None
      candidate = match.group(1).strip()
      for src, dst in _UNICODE_MAP.items():
          candidate = candidate.replace(src, dst)
      try:
          sp.sympify(candidate)
      except (sp.SympifyError, TypeError, ValueError):
          return None
      return candidate
  ```

- [ ] **Step 4: 运行确认通过**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: PASS（7 个测试）

- [ ] **Step 5: Commit**
  ```bash
  git add learning_system/answer_verification.py tests/test_answer_verification.py
  git commit -m "feat: extract machine-checkable calculation expressions from prompts"
  ```

### Task 11: verify_expected_answer（TDD）

**Files:**
- Modify: `learning_system/answer_verification.py`
- Modify: `tests/test_answer_verification.py`

- [ ] **Step 1: 写失败测试**（**追加到 `tests/test_answer_verification.py` 文件末尾、`if __name__ == "__main__"` 之前**，复用文件顶部已有 `import unittest`；不要重写整个文件，否则会删掉前面 Task 的类）
  ```python
  from learning_system.answer_verification import verify_expected_answer


  class TestVerifyExpectedAnswer(unittest.TestCase):
      def test_verified_when_expression_matches(self):
          result = verify_expected_answer("计算：1/2 + 1/3", "5/6")
          self.assertEqual(result["verdict"], "verified")

      def test_mismatch_detected(self):
          result = verify_expected_answer("计算：1/2 + 1/3", "1")
          self.assertEqual(result["verdict"], "mismatch")
          self.assertEqual(result["expected"], "1")

      def test_unverifiable_when_no_expression(self):
          result = verify_expected_answer("判断题：3 是质数", "对")
          self.assertEqual(result["verdict"], "unverifiable")
          self.assertIn("reason", result)
  ```

- [ ] **Step 2: 运行确认失败**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: 红（unittest ERROR: `ImportError: cannot import name 'verify_expected_answer'`）

- [ ] **Step 3: 最小实现**（追加）
  ```python
  def verify_expected_answer(prompt: str, expected_answer: str) -> dict:
      """Verify a calculation item's expected answer. Never raises.

      verdict: verified | mismatch | unverifiable
      """
      expression = extract_calculation(prompt)
      if expression is None:
          return {"verdict": "unverifiable", "reason": "no machine-checkable expression in prompt"}
      if not is_math_equivalent(expression, expected_answer):
          return {"verdict": "mismatch", "expression": expression, "expected": expected_answer}
      return {"verdict": "verified", "expression": expression}
  ```

- [ ] **Step 4: 运行确认通过**
  Run: `python3 -m unittest tests.test_answer_verification -v`
  Expected: PASS（10 个测试）

- [ ] **Step 5: Commit**
  ```bash
  git add learning_system/answer_verification.py tests/test_answer_verification.py
  git commit -m "feat: verify calculation item expected answers"
  ```

### Task 12: 批量审计脚本

**Files:**
- Create: `scripts/audit_question_bank_answers.py`

- [ ] **Step 1: 写脚本**（复用 `verify_expected_answer`，输入 = sqlite question_items 或 JSON 题目列表）
  ```python
  #!/usr/bin/env python3
  """Audit question bank items: verify calculation answers via sympy.

  Usage:
    python3 scripts/audit_question_bank_answers.py --db PATH         # sqlite question_items
    python3 scripts/audit_question_bank_answers.py --json FILE       # [{prompt, expected_answer, ...}]
  """
  from __future__ import annotations

  import argparse
  import json
  import sqlite3
  import sys
  from pathlib import Path

  # scripts/ 下的脚本直接运行时机 sys.path[0] 是 scripts/，需引导到仓库根（照抄现有脚本惯例）
  PROJECT_ROOT = Path(__file__).resolve().parents[1]
  if str(PROJECT_ROOT) not in sys.path:
      sys.path.insert(0, str(PROJECT_ROOT))

  from learning_system.answer_verification import verify_expected_answer  # noqa: E402

  def _items_from_db(path: Path):
      conn = sqlite3.connect(path)
      conn.row_factory = sqlite3.Row
      try:
          rows = conn.execute(
              "select prompt, expected_answer from question_items"
          ).fetchall()
      except sqlite3.OperationalError as exc:
          raise SystemExit(f"db 缺少 question_items 表或列: {exc}") from exc
      finally:
          conn.close()
      return [dict(row) for row in rows]

  def main() -> int:
      parser = argparse.ArgumentParser()
      group = parser.add_mutually_exclusive_group(required=True)
      group.add_argument("--db", type=Path)
      group.add_argument("--json", type=Path, dest="json_path")
      args = parser.parse_args()
      items = _items_from_db(args.db) if args.db else json.loads(args.json_path.read_text(encoding="utf-8"))
      verified = mismatch = unverifiable = 0
      mismatches = []
      for item in items:
          expected = item.get("expected_answer")
          if expected is None or str(expected).strip() == "":
              unverifiable += 1
              continue
          result = verify_expected_answer(str(item.get("prompt", "")), str(expected))
          if result["verdict"] == "verified":
              verified += 1
          elif result["verdict"] == "mismatch":
              mismatch += 1
              mismatches.append((item.get("prompt", "")[:40], result["expected"]))
          else:
              unverifiable += 1
      print(json.dumps({
          "total": len(items), "verified": verified,
          "mismatch": mismatch, "unverifiable": unverifiable,
          "mismatch_samples": mismatches[:20],
      }, ensure_ascii=False, indent=2))
      return 0 if mismatch == 0 else 1

  if __name__ == "__main__":
      sys.exit(main())
  ```

- [ ] **Step 2: 冒烟验证**（用最小 fixture）
  Run: `python3 -c "import json; json.dump([{'prompt':'计算：1/2+1/3','expected_answer':'5/6'},{'prompt':'计算：2+2','expected_answer':'5'}], open('/tmp/qa_audit_fixture.json','w'))" && python3 scripts/audit_question_bank_answers.py --json /tmp/qa_audit_fixture.json; echo "exit=$?"`
  Expected: `total=2 verified=1 mismatch=1 unverifiable=0`，exit=1（有 mismatch）

- [ ] **Step 3: 只读冒烟（真实库，可选）**
  Run: `python3 scripts/audit_question_bank_answers.py --db data/learning.db; echo "exit=$?"`
  Expected: 正常输出计数 JSON（若 question_items 为空则 total=0；若库结构缺表/列则友好报错而非裸 traceback）

- [ ] **Step 4: Commit**
  ```bash
  git add scripts/audit_question_bank_answers.py
  git commit -m "feat: audit question bank answers via sympy verification"
  ```

**Chunk 2 完成条件**：**10 个单元测试**（Task 9 三个 + Task 10 四个 + Task 11 三个）全绿；审计脚本冒烟通过；`python3 -m unittest tests.test_answer_verification -v` 输出 PASS 且测试数 ≥ 10（非 "Ran 0 tests"）。

---

## 收尾

- [ ] **基线确认**：先跑 `python3 -m unittest tests.test_trace_back tests.test_knowledge_graph_contract tests.test_planner_trace_back_integration` 确认基线绿（实测 37 tests OK：18 trace_back + 13 contract + 6 planner），再跑本计划回归。
- [ ] **全量回归**：`python3 -m unittest tests.test_answer_verification tests.test_trace_back tests.test_knowledge_graph_contract tests.test_planner_trace_back_integration` → OK
- [ ] **确认未动 data/**：执行前先 `git status --short data/ > /tmp/data_before.txt`，收尾时对比——只允许执行前已存在的条目，**不得新增** data/ 改动（Chunk 1 只读、Chunk 2 只写代码/脚本）
- [ ] **更新设计稿状态**：在 `docs/design/specs/2026-08-20-child-learning-companion-design.md` 的 §8 标注"第 0 步核对已完成（见 dataflow-audit-record.md）、答案校验已交付"
