# Question Bank Grade-Level Content Audit

- Generated: `2026-07-14T07:08:31.020226+00:00`
- Question bank: `2026-07-08.bank.v11`
- Lane: `active_seed_lane`
- Items audited: 1120
- Nodes audited: 56
- Active round picture-level tasks: 2/10 (min 1, max 2)
- Active round node-local mainline tasks: 8/10 (min 7)
- Live DB lineage checked: yes
- Live DB lineage issues: 0
- Verdict: PASS_WITH_SCOPE
- P0/P1/P2 issues: 0/0/0

## Interpretation

- This audit checks hard content-regression signals for an incoming grade-7 learner: graph binding, reviewer gate, reasoning demand, low-age mechanical drill rejection, explicit problem-family/core-stem lineage, node-alignment reasons, per-node 20 item count, type variety, and repeated core-question risk.
- It also checks the child-facing active round: 10 tasks, with a controlled picture-level extension range and a node-local mainline evidence floor.
- When a live DB path is available, it also checks evidence lineage: old bank/evolved attempts and review records must not remain active.
- It does not replace expert human review or live-model semantic grading. A PASS here would still be scoped.
- A node fails content regression when 20 items mostly reuse the same mathematical stem/answer and only change wrapper instructions.

## Weakest Nodes By Core Variety

| Node | Items | Mainline | Picture | Kinds | Question types | Tag patterns | Problem families | Max family repeat | Canonical core stems | Max core repeat |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `M-BRIDGE-CLOCK-ANGLE` | 20 | 20 | 0 | 20 | 20 | 11 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-MOTION-BASIC` | 20 | 20 | 0 | 20 | 20 | 13 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-MOTION-CHASE` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-PERCENT-MODEL` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-PROPORTION-MODEL` | 20 | 20 | 0 | 20 | 20 | 13 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-SUM-DIFF-MULTIPLE` | 20 | 20 | 0 | 20 | 20 | 13 | 17 | 2 | 19 | 2 |
| `M-BRIDGE-WORK-RATE` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-G7-ALG-EXPR` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-G7-ANGLE` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-G7-ANGLE-CALC` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |
| `M-G7-COMBINE-LIKE` | 20 | 20 | 0 | 20 | 20 | 13 | 17 | 2 | 19 | 2 |
| `M-G7-EQ-DENOM` | 20 | 20 | 0 | 20 | 20 | 12 | 17 | 2 | 19 | 2 |

## Legacy Active Round Difficulty Gate


This lane is legacy compatibility evidence only. It is not a v5 PASS definition.

| # | Question | Node | Kind | Evidence role | Picture-level labels | Prompt |
|---:|---|---|---|---|---|---|
| 1 | `QB11-M-BRIDGE-SOLUTION-HABIT-14` | `M-BRIDGE-SOLUTION-HABIT` | `stretch_transfer` | `picture_level_extension` | digit_reverse_place_value | 解题前先标出一个高风险步骤：“没有处理进位导致数位关系不成立”。再完成本题，并按这个风险点检查：设 n 是一个四位数，它的 4 倍恰好等于它的反序数。例如 1234 的反序数是 4321。请设 n=1000a+100b+10c+d，写出数位方程并求 n。 换一个相近条件，说明原来的哪条规则仍然不变。 本题重点：解题步骤与检验习惯。 |
| 2 | `QB11-M-BRIDGE-WORD-PROBLEM-READING-19` | `M-BRIDGE-WORD-PROBLEM-READING` | `model_selection` | `picture_level_extension` | pigeonhole_prefix_sum_proof | 先圈出真正参与解题的条件，排除无关信息“这些自然数是否按大小排序”：这些自然数是否按大小排序并不重要。请证明 k 个自然数中能选出若干个和被 k 整除。 做完后把最容易错的一步圈出来。 本题重点：应用题审题流程。 |
| 3 | `QB11-M-G7-POS-NEG-15` | `M-G7-POS-NEG` | `two_method_compare` | `node_local_mainline` | - | 先圈出题目要求的结果、关键条件和检验方式，再完成：规定向东为正。小车先向西4米，再向东7米；另有海拔-3米。请写出运动的正负数、最后位置，并说明海拔-3米的负号意义。 做完后把最容易错的一步圈出来。 本题重点：正数和负数。 |
| 4 | `QB11-M-G7-NUMBER-LINE-05` | `M-G7-NUMBER-LINE` | `variant` | `node_local_mainline` | - | 把题意转成 数轴移动图：数轴上 A=-2.5，B=1。点 C 在 A 的右边，且 AC=3。求 C 表示的数，并把 A、B、C 从小到大排列。 请写出转换后的关系，再解答。 做完后把最容易错的一步圈出来。 本题重点：数轴。 |
| 5 | `QB11-M-G7-ABSOLUTE-04` | `M-G7-ABSOLUTE` | `error_spotting` | `node_local_mainline` | - | 本题沿用的规则是：绝对值表示到0的距离，结果非负。 变式题：已知 |x|=2.5，x可能是多少？比较 |-2.5| 和 -|2.5|。 请先指出要使用的结构，再解答。 做完后把最容易错的一步圈出来。 本题重点：绝对值。 |
| 6 | `QB11-M-G7-OPPOSITE-06` | `M-G7-OPPOSITE` | `transfer_retest` | `node_local_mainline` | - | 写出 -7、0、2.5 的相反数，并解释为什么 0 的相反数还是 0。再判断 -(-7) 与 -7 是否相同。 如果少看“0到0距离为0”，会得到什么错误判断？请说明必要条件并完成。 换一个相近条件，说明原来的哪条规则仍然不变。 本题重点：相反数。 |
| 7 | `QB11-M-G7-COMPARE-08` | `M-G7-COMPARE` | `missing_condition` | `node_local_mainline` | - | 先估算或判断合理范围，再完成：把 -3、-1.5、0、2/3 从小到大排列。有人说 -3 比 -1.5 大，因为 3 比 1.5 大。请解释错在哪里。 请说明“-1.5 < -3 < 0 < 2/3”为什么不可能。 做完后把最容易错的一步圈出来。 本题重点：有理数大小比较。 |
| 8 | `QB11-M-G7-RATIONAL-ADD-SUB-09` | `M-G7-RATIONAL-ADD-SUB` | `representation` | `node_local_mainline` | - | 判断这个说法是否成立：“差价只需要在总式里加一次”。请用本题数据反驳或修正，并完成：小林买 3 支笔和 2 本本子共 28 元，本子单价比笔贵 5 元。设笔的单价为 x，列方程并解释 2(x+5) 表示什么。 最后用检验、错因或模型说明关键一步为什么成立。 本题重点：有理数加减。 |
| 9 | `QB11-M-G7-RATIONAL-MUL-DIV-16` | `M-G7-RATIONAL-MUL-DIV` | `boundary_case` | `node_local_mainline` | - | 用代入、反向或估算中的一种方法检验：计算 (-6)×4÷(-3)。请先不算数值，只判断符号；再计算，并说明如果再乘一个 -2 符号会怎样变。 请写出你选择的检验方法和检验结果。 做完后把最容易错的一步圈出来。 本题重点：有理数乘除。 |
| 10 | `QB11-M-G7-RATIONAL-MIXED-18` | `M-G7-RATIONAL-MIXED` | `self_correction` | `node_local_mainline` | - | 两位同学争论：甲说“从左往右先算2-(-3)”；乙说“乘法优先，所以先算(-3)×4”。请判断谁更严谨，并完成本题：判断错解：2 - (-3) × 4 = 5 × 4 = 20。请指出错因，写出正确运算顺序和结果。 做完后把最容易错的一步圈出来。 本题重点：有理数混合运算。 |

## Live DB Lineage Gate

- DB path: `data/local_learning_system.sqlite`
- Issue count: `0`
- `active_attempts_on_superseded_bank_questions`: 0
- `superseded_bank_review_records`: 0
- `learner_status_invalid_refs`: 0
- `stale_review_records`: 0
- `active_attempts_on_invalidated_source_questions`: 0
- `superseded_review_records`: 0
- `invalid_evolved_source_attempts`: 0

## Issues

- None

## Required Next Action

- 当前题库已通过核心题干重复度硬门；继续保留该脚本作为题库回归门禁。
- 下一轮仍需补 live-model answer-analysis 抽样，验证真实孩子式答案是否会被正确区分为会、半会、不会、答案对但思路错。
- 仍需人工/教研抽样审阅题干自然度和认知负荷；本报告只能给 `PASS_WITH_SCOPE`。
