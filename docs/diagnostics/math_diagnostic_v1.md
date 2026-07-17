# Math Diagnostic v1

Status: released  
Version: 2026-07-05.v2  
Time limit: 60 minutes  
Question source: original graph-generated diagnostic probes from `data/knowledge_graphs/math/math_knowledge_graph_v2.json`

## Purpose

This is the first math diagnostic loop for the private AI learning system. It is not a school-style score test.

Use it to locate graph-node breakpoints before summer bridging work begins:

- 小学关键前置是否稳定
- 七上有理数、代数式入口是否能启动
- 错因是概念、计算符号、读题建模、步骤习惯还是图形空间关系
- 七上题错时，应回退到哪一个前置节点

## How To Use

- Hard stop at 60 minutes.
- Do not give method hints during the first attempt unless the child cannot understand the wording.
- Ask the child to write key steps, not only final answers.
- After a question, ask gently: “你为什么这样做？” Record whether the explanation is clear.
- Do not calculate a public percentage grade for the child.
- Open the student page: `app/student/math_diagnostic_v1.html`.
- Export the attempt JSON after marking; feed that file back to Codex for node-state analysis.

## Data Contract

- Source diagnostic JSON: `data/questions/math_diagnostic_v1.json`
- Graph version: `2026-07-04.v2`
- Every item has a graph `node_id`, canonical error tags, rollback candidates, answer key, rubric, and source provenance.
- Version `2026-07-05.v2` also carries `quality.review_status=approved`,
  `age_floor=incoming_grade_7`, and reasoning-signal metadata. The validator
  rejects answer-only arithmetic, child-facing generator/meta language, and items
  without observable process evidence.
- Untested nodes remain `unknown/not_tested`; A/B/C/D requires direct evidence.
- Answer-only records are exported as `grading_status: "ungraded"` and do not create node status.
- A normal wrong answer becomes C unless there is explicit blocking evidence. D is reserved for clear cannot-start/skip evidence or verified prerequisite-chain failure.
- Rollback candidates include relation labels: `self_retest`, `secondary_node`, `prerequisite_chain`, or `followup_probe`.
- Released question content should not be overwritten after a real attempt. Create a new version or superseding item instead.

## Question Map

| ID | Block | Node | Question type |
|---|---|---|---|
| MD1-B1-Q01 | B1 | `M-PRE-INTEGER-OPS` | 整数四则与验算 |
| MD1-B1-Q02 | B1 | `M-PRE-INTEGER-OPS` | 整数乘除与数感 |
| MD1-B1-Q03 | B1 | `M-PRE-INTEGER-OPS` | 整数混合运算 |
| MD1-B1-Q04 | B1 | `M-PRE-DECIMAL-OPS` | 小数乘法估算 |
| MD1-B1-Q05 | B1 | `M-PRE-DECIMAL-OPS` | 小数除法转化 |
| MD1-B1-Q06 | B1 | `M-PRE-DECIMAL-OPS` | 小数分数互化 |
| MD1-B1-Q07 | B1 | `M-PRE-FRACTION-OPS` | 异分母加减 |
| MD1-B1-Q08 | B1 | `M-PRE-FRACTION-OPS` | 分数乘除 |
| MD1-B1-Q09 | B1 | `M-PRE-FRACTION-OPS` | 分数小数混合 |
| MD1-B1-Q10 | B1 | `M-PRE-ORDER-OPS` | 括号与运算顺序 |
| MD1-B1-Q11 | B1 | `M-PRE-ORDER-OPS` | 括号前负号意识 |
| MD1-B1-Q12 | B1 | `M-PRE-ORDER-OPS` | 过程改错 |
| MD1-B2-Q01 | B2 | `M-PRE-FRACTION-MEANING` | 找单位1 |
| MD1-B2-Q02 | B2 | `M-PRE-FRACTION-MEANING` | 已知分率求整体 |
| MD1-B2-Q03 | B2 | `M-PRE-FRACTION-MEANING` | 分率与数量区分 |
| MD1-B2-Q04 | B2 | `M-PRE-PERCENT` | 百分率 |
| MD1-B2-Q05 | B2 | `M-PRE-PERCENT` | 百分数阈值 |
| MD1-B2-Q06 | B2 | `M-PRE-RATIO-PROP` | 化简比与比值 |
| MD1-B2-Q07 | B2 | `M-PRE-RATIO-PROP` | 按比例分配 |
| MD1-B2-Q08 | B2 | `M-PRE-RATIO-PROP` | 比例尺 |
| MD1-B3-Q01 | B3 | `M-PRE-QUANTITY-RELATION` | 只写等量关系 |
| MD1-B3-Q02 | B3 | `M-PRE-QUANTITY-RELATION` | 多/少关系辨析 |
| MD1-B3-Q03 | B3 | `M-PRE-QUANTITY-RELATION` | 列方程不求解 |
| MD1-B3-Q04 | B3 | `M-PRE-EQUATION-BASIC` | 一步方程 |
| MD1-B3-Q05 | B3 | `M-PRE-EQUATION-BASIC` | 两步方程 |
| MD1-B3-Q06 | B3 | `M-PRE-LETTER-EXPR` | 用字母表示数量 |
| MD1-B3-Q07 | B3 | `M-PRE-LETTER-EXPR` | 代入求值 |
| MD1-B3-Q08 | B3 | `M-PRE-LETTER-EXPR` | 表达式与方程辨析 |
| MD1-B4-Q01 | B4 | `M-BRIDGE-WORD-PROBLEM-READING` | 审题标注 |
| MD1-B4-Q02 | B4 | `M-BRIDGE-WORD-PROBLEM-READING` | 信息与问题辨析 |
| MD1-B4-Q03 | B4 | `M-BRIDGE-SUM-DIFF-MULTIPLE` | 和倍关系 |
| MD1-B4-Q04 | B4 | `M-BRIDGE-SUM-DIFF-MULTIPLE` | 年龄差不变 |
| MD1-B4-Q05 | B4 | `M-BRIDGE-MOTION-BASIC` | 行程三量 |
| MD1-B4-Q06 | B4 | `M-BRIDGE-MOTION-BASIC` | 行程单位换算 |
| MD1-B4-Q07 | B4 | `M-BRIDGE-MOTION-CHASE` | 同向追及 |
| MD1-B4-Q08 | B4 | `M-BRIDGE-MOTION-CHASE` | 相遇模型 |
| MD1-B5-Q01 | B5 | `M-G7-POS-NEG` | 相反意义量 |
| MD1-B5-Q02 | B5 | `M-G7-POS-NEG` | 正负变化 |
| MD1-B5-Q03 | B5 | `M-G7-NUMBER-LINE` | 数轴表示 |
| MD1-B5-Q04 | B5 | `M-G7-NUMBER-LINE` | 数轴比较 |
| MD1-B5-Q05 | B5 | `M-G7-ABSOLUTE` | 绝对值意义 |
| MD1-B5-Q06 | B5 | `M-G7-ABSOLUTE` | 绝对值和前置负号 |
| MD1-B5-Q07 | B5 | `M-G7-RATIONAL-ADD-SUB` | 有理数加法 |
| MD1-B5-Q08 | B5 | `M-G7-RATIONAL-ADD-SUB` | 减法转加法 |
| MD1-B5-Q09 | B5 | `M-G7-ALG-EXPR` | 文字转代数式 |
| MD1-B5-Q10 | B5 | `M-G7-ALG-EXPR` | 代数式实际意义 |
| MD1-B5-Q11 | B5 | `M-G7-LIKE-TERMS` | 同类项识别 |
| MD1-B5-Q12 | B5 | `M-G7-LIKE-TERMS` | 去括号与同类项 |

## Node Status Rules

| Status | Meaning | Next action |
|---|---|---|
| A | Correct, steps visible, can explain method, direct evidence score >=85% | Pass; interval retest only |
| B | Mostly correct but slow, prompted, explanation weak, or unstable | Micro-explain + small variation + next-day retest |
| C | Wrong, skipped, or concept/model unclear | Remediate the node before moving on |
| D | Current node and prerequisite chain both fail, or child cannot start | Roll back to earliest weak prerequisite |
| unknown | No direct evidence | Do not infer mastery or weakness |

Important: if a Grade 7 node is wrong and its prerequisite node is also wrong, do not drill more same-type Grade 7 questions first. Roll back along the prerequisite chain.

## Review Checklist

- Does every wrong/partial item have a concrete error tag or `general` plus a parent note?
- Did the child show steps that can be reviewed?
- Did the child explain the method independently, with prompting, or not at all?
- Are units and answer sentences present for word problems?
- Are any rollback candidates outside the first diagnostic set? If yes, mark them as needs follow-up probe rather than weak by assumption.

## Validation

```bash
node scripts/validate_math_diagnostic_v1.mjs
jq empty data/questions/math_diagnostic_v1.json
```
