# M1 测试套件环境失败清单（2026-08-20 核查）

- 状态：**已核查分类，代码级优雅处理待 visuals 落定**（不碰用户 visuals 重构在途文件）
- 依据：干净 HEAD worktree 复现 + 工作树实测
- 关联：设计稿 §9.2「测试套件默认不绿」、M1 里程碑（测试套件默认绿）

## 失败分类（三类，全部与 M2.5/M4/M5 工作无关）

### A 类：visuals 重构中间态（9 个 error）— KnowledgeTargetRuntimeIntegrationTests

**现象**：`tests.test_knowledge_views_v51.py` 的 `KnowledgeTargetRuntimeIntegrationTests` 9 个测试 error。

**根因（实测）**：visuals 重构处于"代码新 + 资产旧/缺失"中间态——
- `learning_system/question_visuals.py` 已被重构（新代码要求 manifest 精确覆盖 inventory）；
- 工作树中 `data/question_visuals/` 的两个资产文件（manifest/inventory）**已被删除**（visuals 重构在途删除，未提交）；
- 干净 HEAD worktree 复现：即使 manifest 存在（旧版），新代码仍抛 `ValueError: question visual manifest does not exactly cover required inventory`。

**结论**：非环境缺装、非本工作引入；**visuals 重构完成后（新资产生成匹配新代码）自动解决**。

**优雅处理**（visuals 落定后执行，不提前）：① 重构完成时重新生成 manifest/inventory 资产（scripts/activate_question_visuals.py 路径）；② 如需在缺资产时优雅 skip，可在该测试类的 setUpClass 加 `FileNotFoundError → skipTest` 守卫——**test_knowledge_views_v51.py 是用户 visuals 在途文件，本次不修改**。

### B 类：Playwright 未安装（2 个 failure）— DualViewBrowserContractTests

**根因**：`Executable doesn't exist at .../ms-playwright/chromium_headless_shell-1234/...`（浏览器未装）。

**解决**：`npx playwright install chromium`（或项目文档化 bootstrap 后执行）。

**优雅处理**：浏览器契约测试在无 Playwright 环境应 skip（标准做法），落点时同样需改 test_knowledge_views_v51.py（用户文件）→ 一并待 visuals 落定。

### C 类：已废弃 v20 题库资产缺失（~54 个 error）— test_three_node_pilot_activation 等

**根因**：`data/question_banks/math/math_three_node_pilot_2026-07-28.v3.json` 等资产缺失（v20 生题已停、题库可弃重建）。

**结论**：随 v20 弃用自然失效；重建题库或移除对应测试后解决。与 visuals 无直接关系，但测试文件可能同为在途状态。

## 解决路径汇总

| 类 | 前置条件 | 动作 | 谁 |
|---|---|---|---|
| A | visuals 重构完成 | 重生成 visuals 资产；可选加 setUpClass skip 守卫 | visuals 会话 + 听云 |
| B | Playwright 安装 | `npx playwright install chromium` + 可选 skip | 环境 |
| C | v20 题库重建/弃用收尾 | 重建资产或移除旧 pilot 测试 | 后续 |

## 结论

M1 的"默认绿"目标**当前不可达**——不是缺测试修复，而是 visuals 重构的中间态（A 类）必须等重构完成。本清单是本工作不越界（不碰用户在途文件）的最大进展；落点时按上表执行。M2.5/M4/M5 引入的所有新测试与既有相关回归（438+ tests）不受这些环境失败影响。
