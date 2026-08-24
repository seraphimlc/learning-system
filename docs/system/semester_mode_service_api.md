# 学期模式服务 API 契约（2026-08-20）

- 状态：v2，已交付（objective ② commit 1695843 + objective ③ 目标选择端点）
- 服务：错题录入 / 周信 / 点亮视图 / 双周简报 / **每周自选目标**（server.py 端点，child-safe 硬红线）
- 关联：设计稿 §6.1/§6.3/§3.1、拍板提案 §3（M0/M1）、审计记录核对项 3/4

## 端点总览

| 方法/路径 | 面 | 认证 | 功能 |
|---|---|---|---|
| POST `/api/manual-errors` | 孩子 | 无（single-child） | 错题录入 M0（opaque handle 选节点） |
| GET `/api/lightup` | 孩子 | 无 | 点亮视图（进度/本周点亮/里程碑） |
| GET `/api/goal-candidates` | 孩子 | 无 | 每周自选目标候选（2 个策展候选：薄弱 + 主线） |
| POST `/api/goal-choice` | 孩子 | 无 | 提交本周目标选择（opaque handle，幂等键回显） |
| POST `/api/operator/manual-errors/confirm` | 家长 | Bearer token | M1 确认（manual_entry_id） |
| POST `/api/operator/weekly-summaries` | 家长 | Bearer token | 周信生成（模板降级） |
| POST `/api/operator/weekly-summaries/{id}/acknowledge` | 家长 | Bearer token | 周信确认（触发该周 M0→M1 批量确认通道，幂等） |
| GET `/api/operator/biweekly-brief` | 家长 | Bearer token | 双周教研简报（纯生成，不落盘） |
| GET `/api/operator/goal-choice` | 家长 | Bearer token | 目标选择查看（当前选择 + 历史，可带 `iso_week` 查别周） |

## child-safe 投影（硬红线）

**孩子面响应白名单**：`schema_version / status / message / node_name / error_cause_label / client_idempotency_key` + `summary(progress_line) / stages / this_week.lit_up(name+from_label+to_label) / milestones(name+date+labels)` + 目标选择 `iso_week / candidates(name+reason_label+node_handle) / node_names`。

**孩子面绝不含**（`internal_agents.FORBIDDEN_CHILD_PATTERNS` 语义真源 + 显式 key 断言）：
- 内部 id：`node_id / question_id / attempt_id / manual_entry_id / error_tag / ME-* / GC-* / status_code`
- 内部概念：图谱 / 节点 / 审计 / 内部状态 / 模型路由 / Agent / Codex / provider / audit / graph / mastery_decisions / learner_node_status / trust_status / mode / recheck / parent_confirmed / chosen_by / stage / priority / candidate_kind

**实现机制**：
1. **节点选择用 opaque handle**（复用 knowledge_map `_opaque_handle`，HMAC-SHA256，内嵌 lineage+secret）：孩子从知识页/目标候选投影拿 handle，服务端反解回 node_id，孩子全程不见内部 id；过期/未知 handle → 409
2. **错因用孩子可见 key**（`careless/unclear/misread/habit/visual/other`）→ 服务端映射到 `CANONICAL_ERROR_TAGS`，原始 tag 绝不出现在孩子面
3. **A/B/C/D 转孩子标签**（暂时掌握/学习中/待巩固），不暴露档位码
4. **目标候选只出 名称 + 孩子可读理由 + handle**：`reason_label` 是服务层策展的孩子文案（"这块有点薄弱" / "学过但还不太牢" / "接下来该学这块"），node_id/stage/priority/candidate_kind 只在服务端用于 mint handle 与排序，绝不投影
5. **错误防御**：服务层异常包 409 通用孩子提示，杜绝原始错误（可能含内部字段）透出；未知/空 handle 409、非法选择（数量/重复/非列表）400、非法错因 key 400、未知确认 id 404、家长面非法 `iso_week` 400
6. 家长面（operator，Bearer token）可暴露内部标识——家长是信任方

## 请求/响应示例

### POST /api/manual-errors（孩子，M0）
```json
// 请求
{"handle": "<opaque>", "error_tag_key": "careless", "client_idempotency_key": "k1"}
// 响应（child-safe）
{"status": "recorded", "message": "已经记下来了。接下来会安排一两道类似的题复习一下。",
 "node_name": "去括号", "error_cause_label": "算错或写错", "client_idempotency_key": "k1"}
```

### GET /api/lightup（孩子）
```json
{"schema_version": "1", "summary": {"progress_line": "已掌握 12 / 56 个知识点"},
 "stages": [{"stage": "七上主线", "mastered": 10, "total": 32}],
 "this_week": {"lit_up": [{"name": "绝对值", "from_label": "学习中", "to_label": "暂时掌握"}]},
 "milestones": [{"name": "绝对值", "date": "2026-08-18", "from_label": "待巩固", "to_label": "暂时掌握"}]}
```

### GET /api/goal-candidates（孩子，每周自选目标）
```json
// 响应（child-safe: 每个候选只有 name + reason_label + node_handle）
{"schema_version": "goal-candidates-child.v1", "iso_week": "2026-W35",
 "candidates": [
   {"name": "钟表角问题", "reason_label": "这块有点薄弱", "node_handle": "kn51n.<hmac-hex>"},
   {"name": "正数和负数", "reason_label": "接下来该学这块", "node_handle": "kn51n.<hmac-hex>"}
 ]}
// 候选不足 2 个 → candidates 只含实际数量（不编造）；无候选 → 空数组
```

### POST /api/goal-choice（孩子）
```json
// 请求
{"candidate_handles": ["kn51n.<hmac-hex>", "kn51n.<hmac-hex>"], "client_idempotency_key": "k2"}
// 响应（child-safe）
{"schema_version": "goal-choice-child.v1", "status": "recorded",
 "message": "已选好下周目标。", "node_names": ["钟表角问题", "正数和负数"],
 "client_idempotency_key": "k2"}
// 错误: 未知/过期/空 handle → 409（"目标好像变了，请刷新后再选一次。"）；
// 非法选择（0 或 3+ 个 / 非列表 / 重复）→ 400
```

### POST /api/operator/manual-errors/confirm（家长）
```json
{"manual_entry_id": "ME-...", "confirmed_by": "parent"}
→ {"status": "ok", "mode": "M1", "recheck_count": 2, "recheck_triggered": false}
```

### POST /api/operator/weekly-summaries/{id}/acknowledge（家长）
```json
→ {"status": "ok", "summary_status": "acknowledged", "week_manual_confirmed": 3, "recheck_triggered": 1}
```

### GET /api/operator/biweekly-brief?end_iso_week=2026-W36&period_weeks=2（家长）
```json
{"error_distribution": [{"error_tag": "calculation_or_symbol", "count": 5}],
 "stagnant_nodes": [{"node_id": "M-G7-...", "days": 14}],
 "high_load_nodes": [{"node_id": "M-G7-...", "attempts": 12}],
 "weekly_a1_warnings": [{"iso_week": "2026-W35", "nodes": ["M-G7-..."]}]}
```

### GET /api/operator/goal-choice（家长）
```json
// 无参数 → current=当周选择（无则 null），history=近 20 周倒序；可带 ?iso_week=2026-W34 查别周
{"schema_version": "operator-goal-choice.v1",
 "current": {"id": "GC-...", "iso_week": "2026-W35", "node_ids": ["M-G7-POS-NEG"],
             "chosen_by": "child", "created_at": "...", "updated_at": null,
             "nodes": [{"node_id": "M-G7-POS-NEG", "name": "正数和负数", "stage": "七上主线"}]},
 "history": [ ...同结构... ]}
// 别周: 过去周的选择不会串到当前周（当前周无记录 → current=null）；
// 非法 iso_week → 400
```

## 验证

- 20 个端点测试（`tests/test_semester_mode_api.py`）全绿，每个孩子面测试用 `FORBIDDEN_CHILD_PATTERNS` 扫序列化响应 + 显式 key 断言（node_id/stage/priority/candidate_kind/GC- 不出现）
- 目标选择链路：候选 GET → handle 反解 → 落库（当周唯一，UPSERT）→ 家长面当前+历史可查，全部走真实 HTTP（`start_test_server`）
- 全量相关回归：13 模块全绿
- 未动 app/（visuals 在途）、test_knowledge_views_v51.py（用户在途）、planner.py

## 待办/边界

- 服务端幂等去重：`client_idempotency_key` 目前只回显，去重责任在接线层（服务层按 id 冲突幂等）——如需服务端去重要求加列，超出本任务边界
- handle 反解遍历 56 节点（HMAC 逐算），规模可忽略；节点上千时需反向索引
- `_opaque_handle`/`_secret_bytes` 为私有导入（受"只动 server.py"边界约束），后续可升级为 knowledge_map 公开 resolve 方法
- 目标选择记录与 planner 的联动在服务层已接（`current_goal_choice`），API 侧只负责读写通道
- UI 接线（孩子最小表单前端、目标选择页面、周信网页呈现）待 visuals 重构落定
