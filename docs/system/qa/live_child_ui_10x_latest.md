# Live Child UI 10x QA

- Generated: 2026-07-07T05:39:28.776504+00:00
- Verdict: `LIVE_CHILD_UI_10X_PASS`
- Scope: real browser operations against current 8765 and current local SQLite DB; mutates the test-stage learning ledger.
- Base URL: `http://127.0.0.1:8765`
- DB path: `/Users/liuchang/Documents/gitproject/son-ai-learning-system/data/local_learning_system.sqlite`
- Lessons requested: 10
- Lessons completed: 10
- Elapsed seconds: 674.275
- Screenshot: `docs/system/qa/live_child_ui_10x_latest.png`
- JSON evidence: `docs/system/qa/live_child_ui_10x_latest.json`

## Issues

- None

## Lesson Summary

| Lesson | Session | Tasks | Scenarios | Results | Tags | Conclusion Visible | Refresh Clicked | Closure | Jobs | Next Tasks | Seconds |
|---:|---|---:|---|---|---|---|---|---|---|---|---:|
| 1 | `S-a873cc300c28` | 4 | `{'correct_full': 1, 'answer_only': 1, 'stuck': 1, 'photo_correct': 1}` | `{'correct': 2, 'partial': 1, 'wrong': 1}` | `{'process_habit': 2, 'modeling_or_reading': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:解题步骤与检验习惯', 'rollback:整数四则计算', 'rollback:等量关系与列式', 'learn:应用题审题流程']` | 79.346 |
| 2 | `S-b6a842f2876b` | 4 | `{'wrong_reason_right_answer': 1, 'correct_full': 1, 'answer_only': 1, 'partial_relation_wrong_final': 1}` | `{'partial': 3, 'wrong': 1}` | `{'modeling_or_reading': 2, 'process_habit': 4, 'general': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'rollback:等量关系与列式', 'prerequisite_probe:解题步骤与检验习惯', 'prerequisite_probe:数感与估算']` | 53.017 |
| 3 | `S-cb25af50ffa9` | 4 | `{'correct_full': 4}` | `{'partial': 1, 'correct': 3}` | `{'process_habit': 1, 'general': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'rollback:等量关系与列式', 'prerequisite_probe:数感与估算', 'retest:解题步骤与检验习惯']` | 57.926 |
| 4 | `S-bcf99f371114` | 4 | `{'stuck': 1, 'wrong_reason_right_answer': 1, 'partial_relation_wrong_final': 1, 'answer_only': 1}` | `{'wrong': 2, 'partial': 2}` | `{'process_habit': 4, 'general': 1, 'modeling_or_reading': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:数感与估算', 'rollback:整数四则计算', 'rollback:等量关系与列式', 'learn:解题步骤与检验习惯']` | 49.163 |
| 5 | `S-d03537d68e1d` | 4 | `{'photo_unclear': 1, 'correct_full': 1, 'blank_or_no_evidence': 1, 'partial_relation_wrong_final': 1}` | `{'wrong': 3, 'partial': 1}` | `{'process_habit': 4}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'rollback:等量关系与列式', 'prerequisite_probe:解题步骤与检验习惯', 'learn:应用题审题流程']` | 62.923 |
| 6 | `S-7fb53bb833a5` | 4 | `{'correct_full': 2, 'wrong_reason_right_answer': 1, 'photo_correct': 1}` | `{'partial': 3, 'correct': 1}` | `{'process_habit': 3}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'prerequisite_probe:数感与估算', 'remediate:等量关系与列式', 'learn:解题步骤与检验习惯']` | 97.378 |
| 7 | `S-bac3f1612cfa` | 4 | `{'answer_only': 1, 'stuck': 1, 'correct_full': 1, 'photo_unclear': 1}` | `{'partial': 1, 'wrong': 2, 'correct': 1}` | `{'process_habit': 3, 'general': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:解题步骤与检验习惯', 'rollback:数感与估算', 'rollback:整数四则计算', 'learn:应用题审题流程']` | 66.881 |
| 8 | `S-9397ac10fe30` | 4 | `{'partial_relation_wrong_final': 1, 'wrong_reason_right_answer': 1, 'answer_only': 1, 'correct_full': 1}` | `{'partial': 4}` | `{'process_habit': 4, 'general': 1, 'modeling_or_reading': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'prerequisite_probe:解题步骤与检验习惯', 'prerequisite_probe:数感与估算', 'learn:应用题审题流程']` | 57.858 |
| 9 | `S-936344f8b885` | 4 | `{'correct_full': 2, 'partial_relation_wrong_final': 1, 'answer_only': 1}` | `{'partial': 2, 'correct': 1, 'wrong': 1}` | `{'process_habit': 3, 'general': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:数感与估算', 'rollback:整数四则计算', 'prerequisite_probe:等量关系与列式', 'remediate:应用题审题流程']` | 49.398 |
| 10 | `S-c5f34f3c2f5f` | 4 | `{'photo_correct': 1, 'wrong_reason_right_answer': 1, 'correct_full': 1, 'blank_or_no_evidence': 1}` | `{'partial': 2, 'correct': 1, 'wrong': 1}` | `{'process_habit': 3, 'modeling_or_reading': 1, 'general': 1}` | True | False | planned | `{'succeeded': 4}` | `['rollback:整数四则计算', 'rollback:等量关系与列式', 'prerequisite_probe:数感与估算', 'learn:解题步骤与检验习惯']` | 97.276 |

## Per-Lesson Evidence

### Lesson 1 - `S-a873cc300c28`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `correct_full` | 整数四则计算 | correct | 2.0 | `[]` |  | 请你补写一句具体估算：为什么99×37应该接近3700，但要比3700少37而不是少1？ |
| 2 | `answer_only` | 等量关系与列式 | partial | 1.0 | `['process_habit']` | 会写出方程，但没有把文字条件转化为数量关系并用语言说明、检验。 | 请补写一句：为什么本子价是x+6而不是x-6？再用代入法检查方程是否符合总价45元。 |
| 3 | `stuck` | 解题步骤与检验习惯 | wrong | 0.0 | `['modeling_or_reading', 'process_habit']` | 不能从题干中优先提取两个核心关系：本子单价=笔单价+5，以及各类物品总价=单价×数量。 | 先填这个表：笔的单价是x、数量3、总价____；本子的单价是____、数量2、总价____，然后两个总价相加等于多少？ |
| 4 | `photo_correct` | 数感与估算 | correct | 2.0 | `[]` |  | 请你不用完全精算，再说一句：为什么398×51不可能接近2000或200000？ |

### Lesson 2 - `S-b6a842f2876b`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `wrong_reason_right_answer` | 解题步骤与检验习惯 | partial | 1.0 | `['modeling_or_reading', 'process_habit']` | 最小缺口是：能复述标准框架，但还不能从题意中独立拆出任务并说明“规则—步骤—检验”之间的因果关系。 | 请不用参考答案，用自己的话补一句：为什么“只写答案、不写规则和检验”不能证明方法可靠？ |
| 2 | `correct_full` | 整数四则计算 | partial | 1.0 | `['process_habit', 'general']` | 缺少用边界/反例解释“余数必须小于除数”的因果理由。 | 请补写一个“余数等于8或大于8”的反例，并说明为什么这时商还可以再增加。 |
| 3 | `answer_only` | 等量关系与列式 | partial | 1.0 | `['process_habit']` | 没有把“男生比女生多8人”转化为等量关系并用该关系反推较少量。 | 请补写一句等量关系，并用它列式求出女生有多少人。 |
| 4 | `partial_relation_wrong_final` | 应用题审题流程 | wrong | 0.0 | `['modeling_or_reading', 'process_habit']` | 没有把“找关系”的想法具体化为已知未知和总价等量关系，导致无法解释3x+2(x+5)=28中每一部分的实际意义。 | 请先补一句：设____为x元，则____为x+5元；3x表示____，2(x+5)表示____，所以它们相加等于____。 |

### Lesson 3 - `S-cb25af50ffa9`

- Visible conclusion: `先修最关键的一步` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。缺少对“余数小于除数”的关系解释：余数若≥除数，还能继续分一组，商就应增加。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `correct_full` | 整数四则计算 | partial | 1.0 | `['process_habit', 'general']` | 缺少对“余数小于除数”的模型解释：余数若≥除数，还能继续分一组，商就应增加。 | 请补充一句：如果余数大于或等于8，会发生什么？商为什么就不是123了？ |
| 2 | `correct_full` | 等量关系与列式 | correct | 2.0 | `[]` |  | 请你把检验写具体：女生18人时，18+8等于多少，是否正好等于男生26人？ |
| 3 | `correct_full` | 解题步骤与检验习惯 | correct | 2.0 | `[]` |  | 请你把开头改写成一句完整的话：这题要我做哪三件事？ |
| 4 | `correct_full` | 数感与估算 | correct | 2.0 | `[]` |  | 如果用精算检验，398×51等于多少？它离20000差多少？ |

### Lesson 4 - `S-bcf99f371114`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `stuck` | 整数四则计算 | wrong | 0.0 | `['process_habit', 'general']` | 缺少把有余数除法题目转化为固定验算模型“被除数=除数×商+余数，余数<除数”的第一步。 | 看到“987÷8=123余3”时，请先把它套进“被除数=除数×商+余数”：你能写出对应的算式吗？ |
| 2 | `wrong_reason_right_answer` | 等量关系与列式 | partial | 1.0 | `['process_habit']` | 没有稳定使用“较少量+差量=较多量”的题意建模，而是凭数字硬凑关系。 | 请你不看原答案，只回答：这题里谁是较多量、谁是较少量，应该用“谁+8=谁”来表示？ |
| 3 | `partial_relation_wrong_final` | 数感与估算 | wrong | 0.0 | `['process_habit']` | 没有把题目中的两个数转化为近似数并计算近似乘积，导致无法完成数量级判断。 | 请你补一句：398≈多少，51≈多少，所以398×51≈多少？ |
| 4 | `answer_only` | 解题步骤与检验习惯 | partial | 1.0 | `['process_habit', 'modeling_or_reading']` | 会写方程，但没有把每个代数式的实际意义、单位和括号整体相乘关系说清，也缺少代入检验。 | 请补写一句：4(x+6)表示什么，为什么必须加括号，并用x=3代入原方程检验一次。 |

### Lesson 5 - `S-d03537d68e1d`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `photo_unclear` | 数感与估算 | wrong | 0.0 | `['process_habit']` | 没有提交清晰可读的答题证据，无法判断是否掌握用估算检查小数乘法小数点位置。 | 请重新写：6.2≈几、48≈几，所以乘积大约是多少？再用这句话判断29.76合理吗。 |
| 2 | `correct_full` | 整数四则计算 | partial | 1.0 | `['process_habit']` | 缺少对“余数小于除数”的原因解释：没有说明余数≥除数时商还可以继续增加。 | 请补一句：如果余数是8或比8大，商应该怎样变化？为什么这说明余数必须小于除数？ |
| 3 | `blank_or_no_evidence` | 等量关系与列式 | wrong | 0.0 | `['process_habit']` | 不能把“男生比女生多8人”转化为“较少量+差量=较多量”的等量关系。 | 请先填空：男生比女生多8人，说明“____人数 + 8 = ____人数”。 |
| 4 | `partial_relation_wrong_final` | 解题步骤与检验习惯 | wrong | 0.0 | `['process_habit']` | 最小缺口是没有把“本子比笔贵5元”转化为本子单价x+5，并进一步放入总价等量关系。 | 请你先补一句：设笔的单价为x元，那么本子的单价是多少元？为什么？ |

### Lesson 6 - `S-7fb53bb833a5`

- Visible conclusion: `先修最关键的一步` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。缺少对余数范围条件的概念性解释，以及未按题目要求明确写出漏看条件会导致的错误。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `correct_full` | 整数四则计算 | partial | 1.0 | `['process_habit']` | 缺少对余数范围条件的概念性解释，以及未按题目要求明确写出漏看条件会导致的错误。 | 请补写一句：如果余数是9而除数是8，为什么商还可以再加1？ |
| 2 | `wrong_reason_right_answer` | 等量关系与列式 | partial | 1.0 | `['process_habit']` | 不能稳定根据“男生比女生多8人”判断男生是较多量、女生是较少量，并由此主动建立“女生+8=男生”的数量关系。 | 请你不看原答案，用一句话先说清楚：男生和女生谁是较多量？如果女生是□人，男生应该怎样表示？ |
| 3 | `correct_full` | 解题步骤与检验习惯 | correct | 2.0 | `[]` |  | 如果把题目改成 4a-2b-(-a-5b)+3，你能先写出去括号这一步再合并吗？ |
| 4 | `photo_correct` | 应用题审题流程 | partial | 1.0 | `['process_habit']` | 缺少把正确方程继续解出数值，并用具体代入或估算说明检查合理性的步骤。 | 请把3x+2(x+5)=28继续解出x，并用“3×笔单价+2×本子单价”代回检验一次。 |

### Lesson 7 - `S-bac3f1612cfa`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `answer_only` | 整数四则计算 | partial | 1.0 | `['process_habit']` | 会背验算关系，但没有把关系式用于具体题目完成代入检验、余数规则检查和迁移复盘。 | 请把“除数×商+余数=被除数”代入本题写成算式，并再写一句“余数3和除数8比，是否合格，为什么？” |
| 2 | `stuck` | 数感与估算 | wrong | 0.0 | `['process_habit']` | 不会把乘法估算题的第一步转化为‘两个因数分别取近似数，再用近似积判断数量级’。 | 先把398和51分别看成哪个最接近、最好算的整百数或整十数？ |
| 3 | `correct_full` | 等量关系与列式 | correct | 2.0 | `[]` |  | 请你用一句话检验：女生18人时，男生是不是比女生多8人？ |
| 4 | `photo_unclear` | 解题步骤与检验习惯 | wrong | 0.0 | `['process_habit', 'general']` | 最小可教差距是没有形成“解方程步骤必须可读写出，并把求得的x代回原方程检验”的作答习惯。 | 请重新写一遍：3(x-2)+5=20去括号后是什么？每一步等式两边分别做了什么同样的运算？最后把x代回原方程检验。 |

### Lesson 8 - `S-9397ac10fe30`

- Visible conclusion: `先修最关键的一步` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。能意识到要找关系和检验，但没有把题目要求拆解成完整答题框架并逐项回应。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `partial_relation_wrong_final` | 解题步骤与检验习惯 | partial | 1.0 | `['process_habit', 'general']` | 能意识到要找关系和检验，但没有把题目要求拆解成完整答题框架并逐项回应。 | 请你按这四栏补一句完整答案：①三件事 ②小明的问题 ③规则+关键步骤+检验 ④为什么关键一步成立。 |
| 2 | `wrong_reason_right_answer` | 数感与估算 | partial | 1.0 | `['process_habit']` | 不能稳定说明估算结果如何用来判断乘积数量级和小数点位置。 | 不看原答案，请你用一句话解释：为什么6.2×48的结果应该接近300，而不是接近30？ |
| 3 | `answer_only` | 整数四则计算 | partial | 1.0 | `['modeling_or_reading', 'process_habit']` | 能说出错因，但没有把“因数少1”转化为“少1组37”的分配律算式并完成计算。 | 请把99写成100-1，补完整这个算式：99×37=(100-1)×37=100×37-____，并算出结果。 |
| 4 | `correct_full` | 应用题审题流程 | partial | 1.0 | `['process_habit']` | 缺少把题目关键词转成数量关系的独立解释，尤其没有具体说明“2本本子”为什么要乘整个本子单价x+5。 | 请你补写一个三列表：笔和本子的“单价、数量、总价”分别是什么，并用一句话说明为什么2要乘整个(x+5)。 |

### Lesson 9 - `S-936344f8b885`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `correct_full` | 整数四则计算 | partial | 1.0 | `['process_habit']` | 缺少用“余数若≥除数则还能继续分组，商应增加”来解释余数小于除数的意义。 | 请补一句：如果余数是8或比8大，商应该怎样变化？为什么这说明余数必须小于除数？ |
| 2 | `correct_full` | 解题步骤与检验习惯 | correct | 2.0 | `[]` |  | 如果改成4a-2b-2(a-5b)+3，你会怎样先去括号？ |
| 3 | `partial_relation_wrong_final` | 数感与估算 | wrong | 0.0 | `['process_habit']` | 没有把两个因数取近似数并用近似乘积判断数量级。 | 把398看成400、51看成50后，先算400×50等于多少，再从三个选项里选一个。 |
| 4 | `answer_only` | 应用题审题流程 | partial | 1.0 | `['process_habit', 'general']` | 最小缺口是没有把“本子单价比笔贵5元”转化为x+5，并据此写出总价方程和检验。 | 请你补写一句：为什么本子的单价是x+5，并用代入法写出3×3.6+2×8.6是否等于28。 |

### Lesson 10 - `S-c5f34f3c2f5f`

- Visible conclusion: `先补一块前置` / `看讲解，开始下一组`
- Child feedback: 这一组已经复盘完成。这一组显示有一块准备知识不够稳，下一组先补这一小步。 先看下面的复盘提示；准备好了点“看讲解，开始下一组”。

| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |
|---:|---|---|---|---:|---|---|---|
| 1 | `photo_correct` | 数感与估算 | partial | 1.0 | `['process_habit']` | 缺少完整写出“正确结果297.6接近估算300，因此小数点位置合理”的最终检验句。 | 请补上最后一句：297.6接近估算的300吗？这能说明小数点位置怎样？ |
| 2 | `wrong_reason_right_answer` | 整数四则计算 | partial | 1.0 | `['modeling_or_reading', 'process_habit']` | 没有稳定建立“有余数除法判断必须同时满足还原被除数和余数小于除数”这两个条件，而是凭数字相近硬凑算式。 | 不看原答案，请你按顺序说一遍：判断“a÷b=q余r”是否正确时，必须检查哪两个条件？ |
| 3 | `correct_full` | 等量关系与列式 | correct | 2.0 | `[]` |  | 如果把女生18人代回“女生+8=男生”，你能写出检验算式并说明为什么符合题意吗？ |
| 4 | `blank_or_no_evidence` | 应用题审题流程 | wrong | 0.0 | `['process_habit', 'general']` | 不能从文字题中提取“数量×单价=总价”并把“本子比笔贵5元”转化为 x+5。 | 先只完成第一步：请你把题目中的4个已知量写出来，并写出笔单价设为 x 元后，本子单价应该是多少元？ |
