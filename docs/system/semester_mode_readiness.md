# 学期模式就绪状态（2026-08-20）

- 状态：**后端全链路就绪**（判定/数据/服务/调度/API 全部交付并验证）；UI 前端接线待 visuals 重构落定
- 验证：550 tests 全绿（含端到端集成链路）
- 关联：设计稿 `2026-08-20-child-learning-companion-design.md`、拍板提案 `2026-08-20-mastery-criteria-proposal.md`、API 契约 `semester_mode_service_api.md`

## 一图概览

```
孩子面                                   家长面
┌───────────────────────┐  ┌──────────────────────────┐
│ 错题录入(M0) → 复测信号 │  │ M1 确认(含周信批量确认通道) │
│ 点亮视图(进度/里程碑)    │  │ 周信生成(A1 预警) → 确认    │
│ 每周自选目标(2 候选)     │  │ 双周教研简报(错因/停滞/耗时)  │
│    ↓ 目标进下周计划      │  │ 目标选择/历史查看            │
└──────────┬────────────┘  └────────────┬─────────────┘
           │ child-safe 投影             │ Bearer token
           └──────────┬─────────────────┘
                      ▼
              server.py 8 端点（API 契约）
                      ▼
        ┌───────────────────────────────┐
        │ 服务层                         │
        │ manual_entry / weekly_report  │
        │ lightup / biweekly_brief      │
        │ goal_choice                   │
        ├───────────────────────────────┤
        │ 调度层：planner（复测到期门控 + │
        │         目标节点进计划）        │
        ├───────────────────────────────┤
        │ 判定层：mastery_rules（统一判定/ │
        │   迁移/复测/M0-M1/闸门/LLM收紧）│
        │   → 已接入 v51+v2 双运行时      │
        ├───────────────────────────────┤
        │ 数据层：4 张新表 + error_tags  │
        │   单一源 + 既有 append-only 史 │
        └───────────────────────────────┘
```

## 交付清单与验证

| 层 | 交付物 | 验证 |
|---|---|---|
| 判定 | `mastery_rules.py`（decide_verdict/状态迁移/唯一计数器/复测间隔/M0-M1/闸门/LLM 收紧）+ `mastery_bridge.py`（适配）+ v51/v2 adapter | T1-T23 锚点测试；daily_runtime v51 + flow_nodes v2 已接入，旧口径已退役 |
| 数据 | `error_tags.py` 单一源；4 张新表（manual_error_entries/error_cause_log/weekly_summary/daily_all_correct_confirmations） | schema 契约测试（唯一索引/append-only） |
| 服务 | `manual_entry_service`（M0/M1/信任边界/批量确认）、`weekly_report_service`（A1 预警/证据范围/模板降级）、`lightup_service`、`biweekly_brief_service`、`goal_choice_service`（策展候选） | 各自单测 + E2E 联动 |
| 调度 | planner：复测到期门控（next_retest_at）+ 当周目标节点进计划 | planner 相关测试 |
| API | 8 端点（孩子面 4：manual-errors/lightup/goal-candidates/goal-choice；家长面 4：confirm/weekly-summaries×2/biweekly-brief） | child-safe 真源断言（FORBIDDEN_CHILD_PATTERNS） |
| 集成 | `tests/test_semester_mode_e2e.py`：一周完整链路（判定→M0→M1→周信→点亮→目标→计划→简报） | E2E 通过 + 550 tests 全绿 |

## 端到端链路（E2E 实测内容）

1. 系统内做题 → `judge_v51_evaluation` 真实判定 → 连续 2 次 C → 落库可回放
2. 作业错题 M0 录入 → 复测信号（判定侧零作用）
3. M1 手动确认 → 动作层独立计数（3 次触发回查，永不直接降档）
4. 周信生成 → 状态快照 + **A1 预警**（连续 2 次 C/D 必进周信）
5. 周信确认 → 该周未确认 M0 批量升级 M1
6. 点亮视图 → 进度与 learner_node_status 一致
7. 目标候选（薄弱+主线策展）→ 孩子选择
8. planner 下周计划 → **目标节点进计划**（选了不白选）
9. 双周简报 → 错因分布 + 停滞清单一致

## 待 visuals 落定项（当前刻意未动）

1. **UI 前端接线**：孩子最小表单（错题录入/目标选择）、周信网页呈现——API 已全部就绪，前端直接调；默认决策已定（孩子最小表单、网页页面）
2. **M1 环境失败**：visuals 中间态 9 个 error（新 question_visuals.py + 旧/缺 manifest）——visuals 完成时重生成资产即绿；清单见 `docs/qa/m1_test_suite_environment_inventory.md`
3. （可选）**服务端幂等去重**：`client_idempotency_key` 目前只回显，需加列才可服务端去重

## 使用入口

- 服务函数：`learning_system/manual_entry_service.py` / `weekly_report_service.py` / `lightup_service.py` / `biweekly_brief_service.py` / `goal_choice_service.py`
- API：见 `docs/system/semester_mode_service_api.md`（请求/响应示例、child-safe 白名单/黑名单）
- 判定规则：见 `docs/design/specs/2026-08-20-mastery-criteria-proposal.md`（T1-T23 锚点）
