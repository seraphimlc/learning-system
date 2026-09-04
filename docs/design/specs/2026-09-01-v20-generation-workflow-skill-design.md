# v20 生题工作流 + Skill 设计（2026-09-01）

## 背景与目标

生题流程目前依赖"提示词 + 模型自由发挥"，整体不可控：难易不均、格式漂移、
风格不统一、答案可能出错。目标：把生题改造成**确定性骨架 + skill 约束的模型
环节**，通过多 agent workflow 编排，让每道题的产生路径可复现、可校验、可回滚。

## 分层框架（v20，已从 git 历史恢复）

```
node（知识图谱节点）
  └─ slot_architecture：为节点分配 slot 桶
       └─ slot_brief_generation：逐 slot 生成 brief（计划，不含题目内容）
            └─ slot_brief_inventory：校验 brief 契约
                 └─ single_slot_production：模型产出 candidate（题干/选项/答案）
                      └─ slot_manifest：汇总题库
```

设计哲学（原模块注释）：**"语义决策全部归模型，Python 只强制身份、schema、
血缘、状态、租约、不可变写入"**。

## Skill 设计：按 slot role 分（21 个）

每个 slot role 一个出题 skill，定义该角色的：
- **认知动作**（这个槽位要考察什么：概念边界/模型本质/变式/迁移…）
- **题干模板**（固定句式 + 填空位，防止风格漂移）
- **答案校验规则**（sympy 可机检 / 概念题答案等价判定）
- **难度与认知阶梯定位**
- **禁项**（防超纲、防一眼答案、防机械题）

| # | slot role | 认知动作示例 |
|---|---|---|
| 1 | concept_boundary | 概念边界判断（"绝对值可以是负数吗"） |
| 2 | essence_model | 本质模型复述与应用 |
| 3 | standard_model | 标准模型运用 |
| 4 | standard_example | 标准例题 |
| 5 | representation_translation | 表征转换（数轴↔式子↔文字） |
| 6 | wrong_solution_repair | 找错并修复 |
| 7 | necessary_condition | 必要条件判断 |
| 8 | same_structure_confirmation | 同构确认 |
| 9 | near_transfer | 近迁移 |
| 10 | alternative_method | 换方法 |
| 11 | inverse_check | 逆检验 |
| 12 | expression_notation | 表达式/符号规范 |
| 13 | prerequisite_probe | 前置探测 |
| 14 | integrated_transfer | 综合迁移 |
| 15 | calculation_symbol_precision | 计算与符号精确性 |
| 16 | model_selection | 模型选择 |
| 17 | misconception_boundary | 常见错误边界 |
| 18 | multi_representation | 多重表征 |
| 19 | stretch_readiness_check | 拓展就绪检查 |
| 20 | summary_transfer_check | 总结迁移检查 |
| 21 | root_readiness_probe | 根就绪探测 |

## Workflow 编排（多 agent）

```
phase 1 分配骨架（Python 确定性）
  node → slots（按 allocation_formula 分配桶）

phase 2 brief 计划（Python 确定性）
  逐 slot 生成 brief → slot_brief_inventory 校验

phase 3 逐 slot 产出 candidate（多 agent workflow）
  ┌─ 出题 agent（skill: 该 slot role）
  │    输入: node + slot + brief + skill 定义
  │    输出: 题干/选项/答案/设计意图（受 skill 模板约束）
  ├─ 校验 agent（skill: 答案验证）
  │    sympy 可机检 → 必验；概念题 → 答案等价判定
  │    失败 → 打回出题 agent 重出（≤2 次）
  ├─ 琢玉审查 agent（skill: 难度/认知/风格审查清单）
  │    不过 → 打回重出；仍不过 → 丢弃并记录
  └─ 通过的 candidate 落盘 staged_candidates/

phase 4 汇总（Python 确定性）
  staged_candidates → slot_manifest → 题库
```

## 与现有资产的关系

- **恢复**：`learning_system/admin/` 的 v20 框架（architecture/brief/inventory/
  manifest/v20_receipts）从 git 历史恢复到代码库
- **保留**：`scripts/generate_semester_bank.py`（840 题数据作为回归基准/题库真源）
- **复用**：现有 `question_generation_service` 的三闸门（sympy 验证、契约校验、
  琢玉审查）作为 phase 3 校验环节的确定性底座

## 验收标准

1. 同一 node + slot 重复生成，题目结构/风格一致（仅参数变化）
2. 所有 candidate 通过 sympy 答案验证（0 mismatch）
3. 无超纲、无一眼答案、无机械题（琢玉审查全过）
4. 输出格式 100% 符合契约（不再依赖模型自报 JSON）
5. 失败可重试、可打回、可记录（不静默丢题）

## 落地步骤

1. 从 git 历史恢复 v20 框架代码 + 单元测试
2. 设计 slot-role skill 规范（21 个 skill 的定义文件）
3. 实现 workflow 编排脚本（phase 1-4）
4. 用 2-3 个 slot role 试点跑通（standard_example / concept_boundary / near_transfer）
5. 全量验证 + 与现有 840 题基准对比
