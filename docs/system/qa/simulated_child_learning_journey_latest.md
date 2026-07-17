# Child Learning Journey QA Simulation

- Generated: 2026-07-08T09:30:51.324878+00:00
- DB: `/tmp/son-learning-10lessons-qb11-contract-rerun.sqlite`
- Lessons simulated: 10
- Verdict: PASS
- Issues: 0

## Lesson Summary

| Lesson | Session | Tasks | Scenarios | Results | Tags | Follow-up | Submit latency max | Closure | Closure seconds | Jobs | Issues |
|---:|---|---:|---|---|---|---|---:|---|---:|---|---:|
| 1 | `S-cf092bf105f8` | 10 | `{"answer_only": 2, "correct_full": 2, "partial_relation_wrong_final": 2, "photo_correct": 2, "stuck": 2}` | `{"correct": 4, "partial": 4, "wrong": 2}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "process_habit": 2}` | `["rollback", "rollback", "prerequisite_probe", "remediate", "prerequisite_probe", "remediate", "prerequisite_probe", "remediate", "prerequisite_probe", "learn"]` | 0.014s | planned | 8.20s | `{"succeeded": 10}` | 0 |
| 2 | `S-aa2695945521` | 10 | `{"answer_only": 2, "correct_full": 2, "partial_relation_wrong_final": 2, "photo_unclear": 2, "wrong_reason_right_answer": 2}` | `{"correct": 2, "partial": 8}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "modeling_or_reading": 2, "process_habit": 4}` | `["rollback", "rollback", "remediate", "remediate", "remediate", "remediate", "prerequisite_probe", "remediate", "remediate", "learn"]` | 0.019s | planned | 8.03s | `{"succeeded": 10}` | 0 |
| 3 | `S-cbff058049ed` | 10 | `{"correct_full": 10}` | `{"correct": 10}` | `{}` | `["rollback", "rollback", "prerequisite_probe", "remediate", "prerequisite_probe", "retest", "retest", "retest", "retest", "retest"]` | 0.025s | planned | 6.00s | `{"succeeded": 10}` | 0 |
| 4 | `S-046ab5e394eb` | 10 | `{"answer_only": 2, "partial_relation_wrong_final": 2, "photo_correct": 2, "stuck": 2, "wrong_reason_right_answer": 2}` | `{"correct": 2, "partial": 6, "wrong": 2}` | `{"calculation_or_symbol": 2, "concept_confusion": 4, "modeling_or_reading": 2, "process_habit": 2}` | `["rollback", "rollback", "remediate", "remediate", "prerequisite_probe", "remediate", "remediate", "prerequisite_probe", "remediate", "learn"]` | 0.020s | planned | 8.34s | `{"succeeded": 10}` | 0 |
| 5 | `S-8aeeca1962b1` | 10 | `{"answer_only": 2, "blank_or_no_evidence": 2, "correct_full": 2, "partial_relation_wrong_final": 2, "photo_unclear": 2}` | `{"correct": 2, "partial": 6, "wrong": 2}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "process_habit": 4}` | `["rollback", "rollback", "prerequisite_probe", "remediate", "prerequisite_probe", "remediate", "prerequisite_probe", "remediate", "retest", "learn"]` | 0.024s | planned | 8.36s | `{"succeeded": 10}` | 0 |
| 6 | `S-bf9b5cbc9e65` | 10 | `{"correct_full": 4, "partial_relation_wrong_final": 2, "photo_correct": 2, "wrong_reason_right_answer": 2}` | `{"correct": 6, "partial": 4}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "modeling_or_reading": 2}` | `["rollback", "remediate", "remediate", "remediate", "prerequisite_probe", "retest", "retest", "retest", "retest", "learn"]` | 0.029s | planned | 6.34s | `{"succeeded": 10}` | 0 |
| 7 | `S-dfaab637061f` | 10 | `{"answer_only": 2, "correct_full": 4, "photo_unclear": 2, "stuck": 2}` | `{"correct": 4, "partial": 4, "wrong": 2}` | `{"concept_confusion": 2, "process_habit": 4}` | `["rollback", "rollback", "prerequisite_probe", "prerequisite_probe", "remediate", "remediate", "retest", "retest", "retest", "learn"]` | 0.026s | planned | 6.49s | `{"succeeded": 10}` | 0 |
| 8 | `S-133e04b08c85` | 10 | `{"answer_only": 2, "correct_full": 2, "partial_relation_wrong_final": 2, "photo_correct": 2, "wrong_reason_right_answer": 2}` | `{"correct": 4, "partial": 6}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "modeling_or_reading": 2, "process_habit": 2}` | `["rollback", "rollback", "remediate", "prerequisite_probe", "remediate", "remediate", "remediate", "retest", "retest", "learn"]` | 0.033s | planned | 6.53s | `{"succeeded": 10}` | 0 |
| 9 | `S-a954db1418d3` | 10 | `{"answer_only": 2, "correct_full": 4, "partial_relation_wrong_final": 2, "stuck": 2}` | `{"correct": 4, "partial": 4, "wrong": 2}` | `{"calculation_or_symbol": 2, "concept_confusion": 2, "process_habit": 2}` | `["rollback", "rollback", "rollback", "rollback", "remediate", "prerequisite_probe", "prerequisite_probe", "remediate", "learn", "learn"]` | 0.121s | planned | 7.05s | `{"succeeded": 10}` | 0 |
| 10 | `S-04a2b0afe97e` | 10 | `{"blank_or_no_evidence": 2, "correct_full": 2, "partial_relation_wrong_final": 2, "photo_correct": 2, "wrong_reason_right_answer": 2}` | `{"correct": 4, "partial": 4, "wrong": 2}` | `{"calculation_or_symbol": 2, "concept_confusion": 4, "modeling_or_reading": 2}` | `["rollback", "rollback", "rollback", "prerequisite_probe", "remediate", "remediate", "retest", "retest", "retest", "learn"]` | 0.032s | planned | 7.07s | `{"succeeded": 10}` | 0 |

## Attempt Semantic Samples

| Lesson | Task | Scenario | Result | Score | Tags | Blocking | Process gap | Comparison | Photo |
|---:|---:|---|---|---:|---|---|---|---|---|
| 1 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 1 | 2 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 1 | 3 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 1 | 4 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 1 | 5 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 1 | 6 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 1 | 7 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 1 | 8 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 1 | 9 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 1 | 10 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 2 | 1 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 2 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 2 | 3 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 2 | 4 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 2 | 5 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 2 | 6 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 2 | 7 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 2 | 8 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 2 | 9 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 2 | 10 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 3 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 4 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 5 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 6 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 7 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 8 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 9 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 3 | 10 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 4 | 1 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 4 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 4 | 3 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 4 | 4 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 4 | 5 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 4 | 6 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 4 | 7 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 4 | 8 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 4 | 9 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 4 | 10 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 5 | 1 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 5 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 5 | 3 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing,symbols_units:missing,check_or_explanation:missing` | - |
| 5 | 4 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 5 | 5 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 5 | 6 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 5 | 7 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 5 | 8 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing,symbols_units:missing,check_or_explanation:missing` | - |
| 5 | 9 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 5 | 10 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 6 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 6 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 6 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 6 | 4 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 6 | 5 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 6 | 6 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 6 | 7 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 6 | 8 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 6 | 9 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 6 | 10 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 7 | 1 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 7 | 2 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 7 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 7 | 4 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 7 | 5 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 7 | 6 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 7 | 7 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 7 | 8 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 7 | 9 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | unclear |
| 7 | 10 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 8 | 1 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 8 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 8 | 3 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 8 | 4 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 8 | 5 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 8 | 6 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 8 | 7 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 8 | 8 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 8 | 9 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 8 | 10 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 9 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 9 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 9 | 3 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 9 | 4 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 9 | 5 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 9 | 6 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 9 | 7 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 9 | 8 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 9 | 9 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing,model_or_relation:unclear,symbols_units:unclear` | - |
| 9 | 10 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing,final_answer:unclear,symbols_units:missing,check_or_explanation:missing` | - |
| 10 | 1 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 10 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 10 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 10 | 4 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing,symbols_units:missing,check_or_explanation:missing` | - |
| 10 | 5 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |
| 10 | 6 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched,model_or_relation:matched,symbols_units:matched` | usable |
| 10 | 7 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect,symbols_units:unclear,check_or_explanation:missing` | - |
| 10 | 8 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched,symbols_units:matched` | - |
| 10 | 9 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing,symbols_units:missing,check_or_explanation:missing` | - |
| 10 | 10 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect,steps:matched,check_or_explanation:missing` | - |

## Issues

- None

## Notes

- Child submissions are expected to return `being_reviewed` immediately; model review is simulated with 180 ms latency.
- Semantic QA validates correct, wrong, stuck, answer-only, wrong-reason-right-answer, photo, unclear-photo, and partial-relation cases.
- The script verifies persisted result/error tags/process gaps/photo OCR/cause analysis/node status and evidence-linked next plans.
- The simulation uses a temporary DB by default and does not mutate the real learning ledger.
