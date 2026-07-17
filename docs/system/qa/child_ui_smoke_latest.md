# Child UI Mocked Regression QA

- Generated: 2026-07-07T04:31:38.086452+00:00
- Verdict: MOCKED_REGRESSION_PASS
- Scope: temp DB, mocked evaluator/OCR/question-model paths; this is not live-system acceptance.
- Target base URL: `http://127.0.0.1:49954`
- DB path: `/var/folders/qn/gnt8lwz171ngryk7h224vkqw0000gn/T/tmpcs4sxcp3/ui-smoke.sqlite`
- Model mode: `mocked`
- Patches active: `auto_review._call_openai_evaluator`, `auto_review._review_answer_photo`, `evolution._call_openai_question_candidate`
- Lessons: 10
- Elapsed seconds: 48.347
- Screenshot: `/Users/liuchang/Documents/gitproject/son-ai-learning-system/docs/system/qa/child_ui_smoke_latest.png`

## Lesson Summary

| Lesson | Session | Tasks | Scenarios | Results | Tags | Follow-up | Status | Closure | Seconds | Summary | Jobs |
|---:|---|---:|---|---|---|---|---|---|---:|---|---|
| 1 | `S-2ee333470635` | 4 | `{'answer_only': 1, 'correct_full': 1, 'photo_correct': 1, 'stuck': 1}` | `{'correct': 2, 'partial': 1, 'wrong': 1}` | `{'concept_confusion': 1, 'process_habit': 1}` | `['rollback', 'prerequisite_probe', 'remediate', 'retest', 'retest']` | closed | planned | 4.994 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 2 | `S-a97bd40d743b` | 5 | `{'answer_only': 1, 'correct_full': 1, 'partial_relation_wrong_final': 1, 'photo_unclear': 1, 'wrong_reason_right_answer': 1}` | `{'correct': 1, 'partial': 4}` | `{'calculation_or_symbol': 1, 'concept_confusion': 1, 'modeling_or_reading': 1, 'process_habit': 2}` | `['rollback', 'prerequisite_probe', 'prerequisite_probe', 'remediate']` | closed | planned | 4.901 | `{'submitted': 5, 'graded': 5, 'pending': 0, 'analyzed': 5}` | `{'succeeded': 5}` |
| 3 | `S-27a02b75641a` | 4 | `{'correct_full': 4}` | `{'correct': 4}` | `{}` | `['rollback', 'prerequisite_probe', 'remediate', 'retest']` | closed | planned | 4.685 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 4 | `S-078631a6f396` | 4 | `{'answer_only': 1, 'partial_relation_wrong_final': 1, 'stuck': 1, 'wrong_reason_right_answer': 1}` | `{'partial': 3, 'wrong': 1}` | `{'calculation_or_symbol': 1, 'concept_confusion': 2, 'modeling_or_reading': 1, 'process_habit': 1}` | `['rollback', 'prerequisite_probe', 'remediate', 'remediate']` | closed | planned | 4.741 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 5 | `S-ca9bcc46a5c3` | 4 | `{'blank_or_no_evidence': 1, 'correct_full': 1, 'partial_relation_wrong_final': 1, 'photo_unclear': 1}` | `{'correct': 1, 'partial': 2, 'wrong': 1}` | `{'calculation_or_symbol': 1, 'concept_confusion': 1, 'process_habit': 1}` | `['rollback', 'prerequisite_probe', 'remediate', 'retest']` | closed | planned | 4.872 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 6 | `S-42df064d2f7a` | 4 | `{'correct_full': 2, 'photo_correct': 1, 'wrong_reason_right_answer': 1}` | `{'correct': 3, 'partial': 1}` | `{'concept_confusion': 1, 'modeling_or_reading': 1}` | `['prerequisite_probe', 'remediate', 'retest', 'retest']` | closed | planned | 4.729 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 7 | `S-b21a897b56c0` | 4 | `{'answer_only': 1, 'correct_full': 1, 'photo_unclear': 1, 'stuck': 1}` | `{'correct': 1, 'partial': 2, 'wrong': 1}` | `{'concept_confusion': 1, 'process_habit': 2}` | `['rollback', 'prerequisite_probe', 'remediate', 'retest']` | closed | planned | 4.752 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 8 | `S-56ab1dbae4a8` | 4 | `{'answer_only': 1, 'correct_full': 1, 'partial_relation_wrong_final': 1, 'wrong_reason_right_answer': 1}` | `{'correct': 1, 'partial': 3}` | `{'calculation_or_symbol': 1, 'concept_confusion': 1, 'modeling_or_reading': 1, 'process_habit': 1}` | `['rollback', 'remediate', 'remediate', 'learn']` | closed | planned | 4.825 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 9 | `S-5ab6d4a3964d` | 4 | `{'answer_only': 1, 'correct_full': 2, 'partial_relation_wrong_final': 1}` | `{'correct': 2, 'partial': 2}` | `{'calculation_or_symbol': 1, 'process_habit': 1}` | `['rollback', 'prerequisite_probe', 'prerequisite_probe', 'remediate']` | closed | planned | 4.691 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |
| 10 | `S-4434c65e9e8f` | 4 | `{'blank_or_no_evidence': 1, 'correct_full': 1, 'photo_correct': 1, 'wrong_reason_right_answer': 1}` | `{'correct': 2, 'partial': 1, 'wrong': 1}` | `{'concept_confusion': 2, 'modeling_or_reading': 1}` | `['rollback', 'rollback', 'prerequisite_probe', 'learn']` | closed | planned | 4.746 | `{'submitted': 4, 'graded': 4, 'pending': 0, 'analyzed': 4}` | `{'succeeded': 4}` |

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
