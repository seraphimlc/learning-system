# Child Learning Journey QA Simulation

- Generated: 2026-07-06T09:20:03.057612+00:00
- DB: `/var/folders/qn/gnt8lwz171ngryk7h224vkqw0000gn/T/tmp0kfmbceh/simulation.sqlite`
- Lessons simulated: 10
- Verdict: PASS
- Issues: 0

## Lesson Summary

| Lesson | Session | Tasks | Scenarios | Results | Tags | Follow-up | Submit latency max | Closure | Closure seconds | Jobs | Issues |
|---:|---|---:|---|---|---|---|---:|---|---:|---|---:|
| 1 | `S-4984b03bc51f` | 4 | `{"answer_only": 1, "correct_full": 1, "photo_correct": 1, "stuck": 1}` | `{"correct": 2, "partial": 1, "wrong": 1}` | `{"concept_confusion": 1, "process_habit": 1}` | `["rollback", "prerequisite_probe", "remediate", "retest", "retest"]` | 0.213s | planned | 2.52s | `{"succeeded": 4}` | 0 |
| 2 | `S-3a5c3f12fcff` | 5 | `{"answer_only": 1, "correct_full": 1, "partial_relation_wrong_final": 1, "photo_unclear": 1, "wrong_reason_right_answer": 1}` | `{"correct": 1, "partial": 4}` | `{"calculation_or_symbol": 1, "concept_confusion": 1, "modeling_or_reading": 1, "process_habit": 2}` | `["rollback", "prerequisite_probe", "prerequisite_probe", "remediate"]` | 0.210s | planned | 2.50s | `{"succeeded": 5}` | 0 |
| 3 | `S-30ec56529544` | 4 | `{"correct_full": 4}` | `{"correct": 4}` | `{}` | `["rollback", "prerequisite_probe", "remediate", "retest"]` | 0.217s | planned | 2.36s | `{"succeeded": 4}` | 0 |
| 4 | `S-29246384b026` | 4 | `{"answer_only": 1, "partial_relation_wrong_final": 1, "stuck": 1, "wrong_reason_right_answer": 1}` | `{"partial": 3, "wrong": 1}` | `{"calculation_or_symbol": 1, "concept_confusion": 2, "modeling_or_reading": 1, "process_habit": 1}` | `["rollback", "prerequisite_probe", "remediate", "remediate"]` | 0.209s | planned | 2.47s | `{"succeeded": 4}` | 0 |
| 5 | `S-6f5af6c28f5a` | 4 | `{"blank_or_no_evidence": 1, "correct_full": 1, "partial_relation_wrong_final": 1, "photo_unclear": 1}` | `{"correct": 1, "partial": 2, "wrong": 1}` | `{"calculation_or_symbol": 1, "concept_confusion": 1, "process_habit": 1}` | `["rollback", "prerequisite_probe", "remediate", "retest"]` | 0.266s | planned | 2.39s | `{"succeeded": 4}` | 0 |
| 6 | `S-45baead26d64` | 4 | `{"correct_full": 2, "photo_correct": 1, "wrong_reason_right_answer": 1}` | `{"correct": 3, "partial": 1}` | `{"concept_confusion": 1, "modeling_or_reading": 1}` | `["prerequisite_probe", "remediate", "retest", "retest"]` | 0.223s | planned | 2.48s | `{"succeeded": 4}` | 0 |
| 7 | `S-58b0bb903b57` | 4 | `{"answer_only": 1, "correct_full": 1, "photo_unclear": 1, "stuck": 1}` | `{"correct": 1, "partial": 2, "wrong": 1}` | `{"concept_confusion": 1, "process_habit": 2}` | `["rollback", "prerequisite_probe", "remediate", "retest"]` | 0.220s | planned | 2.46s | `{"succeeded": 4}` | 0 |
| 8 | `S-2d5ee46d2693` | 4 | `{"answer_only": 1, "correct_full": 1, "partial_relation_wrong_final": 1, "wrong_reason_right_answer": 1}` | `{"correct": 1, "partial": 3}` | `{"calculation_or_symbol": 1, "concept_confusion": 1, "modeling_or_reading": 1, "process_habit": 1}` | `["rollback", "remediate", "remediate", "learn"]` | 0.219s | planned | 2.40s | `{"succeeded": 4}` | 0 |
| 9 | `S-577b24b6f719` | 4 | `{"answer_only": 1, "correct_full": 2, "partial_relation_wrong_final": 1}` | `{"correct": 2, "partial": 2}` | `{"calculation_or_symbol": 1, "process_habit": 1}` | `["rollback", "prerequisite_probe", "prerequisite_probe", "remediate"]` | 0.220s | planned | 2.39s | `{"succeeded": 4}` | 0 |
| 10 | `S-89ca4cd3e33c` | 4 | `{"blank_or_no_evidence": 1, "correct_full": 1, "photo_correct": 1, "wrong_reason_right_answer": 1}` | `{"correct": 2, "partial": 1, "wrong": 1}` | `{"concept_confusion": 2, "modeling_or_reading": 1}` | `["rollback", "rollback", "prerequisite_probe", "learn"]` | 0.263s | planned | 2.41s | `{"succeeded": 4}` | 0 |

## Attempt Semantic Samples

| Lesson | Task | Scenario | Result | Score | Tags | Blocking | Process gap | Comparison | Photo |
|---:|---:|---|---|---:|---|---|---|---|---|
| 1 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 1 | 2 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 1 | 3 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing` | - |
| 1 | 4 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched` | usable |
| 2 | 1 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect` | - |
| 2 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 2 | 3 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 2 | 4 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect` | - |
| 2 | 5 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing` | unclear |
| 3 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 3 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 3 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 3 | 4 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 4 | 1 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing` | - |
| 4 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect` | - |
| 4 | 3 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect` | - |
| 4 | 4 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 5 | 1 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing` | unclear |
| 5 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 5 | 3 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing` | - |
| 5 | 4 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect` | - |
| 6 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 6 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect` | - |
| 6 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 6 | 4 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched` | usable |
| 7 | 1 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 7 | 2 | `stuck` | wrong | 0.0 | `concept_confusion` | True | 卡在第一步，没有把题意转成可用关系。 | `model_or_relation:missing,steps:missing` | - |
| 7 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 7 | 4 | `photo_unclear` | partial | 1.0 | `process_habit` | False | 照片和文字证据不足，不能确认步骤和检验。 | `final_answer:unclear,steps:unclear,check_or_explanation:missing` | unclear |
| 8 | 1 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect` | - |
| 8 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect` | - |
| 8 | 3 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 8 | 4 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 9 | 1 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 9 | 2 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 9 | 3 | `partial_relation_wrong_final` | partial | 1.0 | `calculation_or_symbol` | False | 关系启动了，但符号或计算落点错误。 | `model_or_relation:matched,final_answer:incorrect,symbols_units:incorrect` | - |
| 9 | 4 | `answer_only` | partial | 1.0 | `process_habit` | False | 只写答案，缺少可复盘步骤和检验。 | `final_answer:matched,steps:missing,check_or_explanation:missing` | - |
| 10 | 1 | `photo_correct` | correct | 2.0 | `` | False |  | `final_answer:matched,steps:matched,check_or_explanation:matched` | usable |
| 10 | 2 | `wrong_reason_right_answer` | partial | 1.0 | `concept_confusion,modeling_or_reading` | False | 答案对但关系错误，结果不能证明方法可靠。 | `final_answer:matched,model_or_relation:incorrect,steps:incorrect` | - |
| 10 | 3 | `correct_full` | correct | 2.0 | `` | False |  | `final_answer:matched,model_or_relation:matched,steps:matched,check_or_explanation:matched` | - |
| 10 | 4 | `blank_or_no_evidence` | wrong | 0.0 | `concept_confusion` | True | 没有可用作答证据，无法启动第一步。 | `final_answer:unclear,model_or_relation:missing,steps:missing` | - |

## Issues

- None

## Notes

- Child submissions are expected to return `being_reviewed` immediately; model review is simulated with 180 ms latency.
- Semantic QA validates correct, wrong, stuck, answer-only, wrong-reason-right-answer, photo, unclear-photo, and partial-relation cases.
- The script verifies persisted result/error tags/process gaps/photo OCR/cause analysis/node status and evidence-linked next plans.
- The simulation uses a temporary DB by default and does not mutate the real learning ledger.
