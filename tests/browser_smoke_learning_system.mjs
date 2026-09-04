#!/usr/bin/env node
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

const root = path.resolve(new URL("..", import.meta.url).pathname);
const dbPath = path.join(os.tmpdir(), `learning-system-v5-smoke-${process.pid}.sqlite`);
const uploadRoot = path.join(os.tmpdir(), `learning-system-v5-smoke-uploads-${process.pid}`);
const uploadPath = path.join(os.tmpdir(), `learning-system-answer-${process.pid}.png`);
const invalidUploadPath = path.join(os.tmpdir(), `learning-system-answer-${process.pid}.txt`);
const v5HarnessContractPath = path.join(root, "tests", "fixtures", "v5_10_lesson_harness_contract.json");
const v5HarnessContract = JSON.parse(fs.readFileSync(v5HarnessContractPath, "utf8"));
const operatorToken = "browser-smoke-operator-token";
const port = await getFreePort();
const baseUrl = `http://127.0.0.1:${port}`;

const seed = spawnSync("python3", [
  "-c",
  [
    "from pathlib import Path",
    "from learning_system import db",
    "from learning_system import test_support",
    "from scripts import activate_lightweight_answer_contracts",
    `path = Path(${JSON.stringify(dbPath)})`,
    "path.parent.mkdir(parents=True, exist_ok=True)",
    "conn = db.connect(path)",
    "db.init_schema(conn)",
    "db.seed_from_assets(conn, Path.cwd())",
    "test_support.seed_runtime_test_question_bank(conn, Path.cwd())",
    "conn.close()",
    "activate_lightweight_answer_contracts.activate(path, project_root=Path.cwd())",
  ].join("; "),
], { cwd: root, encoding: "utf8" });
if (seed.status !== 0) {
  throw new Error(`Failed to prepare v5.1 smoke DB: ${seed.stderr || seed.stdout}`);
}

const forbiddenChildTexts = [
  "Codex",
  "家长报告",
  "复制给 Codex",
  "待 Codex",
  "Agent",
  "图谱",
  "节点",
  "自进化",
  "expected_answer",
  "rubric",
  "solution_steps",
  "OPENAI_API_KEY",
  "API_KEY",
  "provider",
  "model",
  "queue",
  "job_id",
  "attempt_id",
  "question_id",
  "flow_id",
  "answer_micro_check",
  "micro_check",
  "continue_new_knowledge",
  "near_transfer_retest",
  "same_structure_retest",
  "prerequisite_probe",
];

const canonicalV5ChildStates = [
  "start_resume",
  "current_step",
  "analyzing_pending",
  "feedback_teaching",
  "clarify_evidence",
  "ready_for_new_knowledge",
  "blocked",
  "summary",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertChildSafe(serialized, label) {
  for (const forbidden of forbiddenChildTexts) {
    assert(!serialized.includes(forbidden), `${label} should not expose ${forbidden}`);
  }
}

function assertNoLegacyV5Payload(payload, label) {
  const serialized = JSON.stringify(payload).toLowerCase();
  const forbidden = [
    '"today_plan"',
    '"learning_group"',
    '"generated_plans"',
    '"tasks"',
    '"task_count"',
    '"total_tasks"',
    '"plan_id"',
    '"plan_key"',
    '"group_index"',
    '"group_size"',
    "保存，下一题",
    "继续下一组",
    "今天先完成这一组",
  ];
  for (const fragment of forbidden) {
    assert(!serialized.includes(fragment), `${label} should not expose legacy fixed-group payload fragment ${fragment}`);
  }
}

function assertV5HarnessContract() {
  assert(v5HarnessContract.schema_version === "2026-07-11.v5.10-lesson-harness-contract.v2", "v5 10-lesson harness contract schema should be current");
  assert(v5HarnessContract.route_family.includes("/api/current-step/submit"), "v5 harness must use current-step submit");
  assert(v5HarnessContract.model_contract.default_mode === "recorded_model", "v5 harness must default to recorded_model");
  assert(v5HarnessContract.model_contract.patched_outputs_may_be_labeled_live === false, "patched harness output must not be labeled live_model");
  assert(v5HarnessContract.execution_contract.lesson_count === 10, "v5 harness must define ten lessons");
  assert(v5HarnessContract.lessons.length === 10, "v5 harness must provide ten independent lesson contracts");
  assert(new Set(v5HarnessContract.lessons.map((lesson) => lesson.local_date)).size === 10, "v5 harness lesson dates must be independent");
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      const selected = typeof address === "object" && address ? address.port : 0;
      probe.close(() => resolve(selected));
    });
    probe.on("error", reject);
  });
}

async function waitForServer() {
  const deadline = Date.now() + 10000;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/bootstrap`, {
        headers: { Authorization: `Bearer ${operatorToken}` },
      });
      if (response.ok) return await response.json();
      lastError = `${response.status} ${await response.text()}`;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Server did not become ready: ${lastError}`);
}

async function waitForCondition(predicate, label, timeoutMs = 7000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

const server = spawn("python3", [
  "-m",
  "learning_system.server",
  "--db",
  dbPath,
  "--port",
  String(port),
  "--upload-root",
  uploadRoot,
], {
  cwd: root,
  env: {
    ...process.env,
    V3_DAILY_RUNTIME_ENABLED: "1",
    ANSWER_ASSESSMENT_POLICY: "v5.1",
    KNOWLEDGE_MAP_HOME_POLICY: "v5.1",
    OPENAI_API_KEY: "",
    AI_EVALUATOR_API_KEY: "",
    AI_ANSWER_ANALYSIS_AGENT_API_KEY: "",
    AI_ANSWER_REVIEW_API_KEY: "",
    SON_AI_OPERATOR_TOKEN: operatorToken,
    AI_ANSWER_ANALYSIS_AGENT_ANSWER_REVIEW_API_KEY: "",
    AI_ANSWER_ANALYSIS_AGENT_VISION_OCR_API_KEY: "",
    AI_VISION_OCR_API_KEY: "",
    AI_QUESTION_DESIGNER_AGENT_API_KEY: "",
    AI_QUESTION_CANDIDATE_API_KEY: "",
  },
  stdio: ["ignore", "pipe", "pipe"],
});

let stderr = "";
server.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

try {
  assertV5HarnessContract();
  const bootstrap = await waitForServer();
  assert(bootstrap.readiness.graph_nodes === 56, "graph node count should be 56");
  assert(bootstrap.readiness.practice_questions >= 224, "practice bank should be seeded");

  const browser = await chromium.launch({
    headless: true,
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });

  const loadErrorPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await loadErrorPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: "temporary bootstrap break" }),
  }));
  await loadErrorPage.goto(baseUrl);
  await loadErrorPage.waitForSelector("#childErrorPanel:not([hidden])");
  await loadErrorPage.waitForFunction(() => document.activeElement?.id === "childErrorPanel");
  const loadErrorPanel = await loadErrorPage.evaluate(() => ({
    state: window.ChildLearningShell?.currentState(),
    kind: document.querySelector("#childErrorPanel")?.dataset.errorKind,
    title: document.querySelector("#childErrorTitle")?.textContent || "",
    body: document.querySelector("#childErrorBody")?.textContent || "",
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
    formHidden: document.querySelector("#childAttemptForm")?.hidden,
    role: document.querySelector("#childErrorPanel")?.getAttribute("role"),
    live: document.querySelector("#childErrorPanel")?.getAttribute("aria-live"),
  }));
  assert(loadErrorPanel.state === "load_error", "Bootstrap failure should enter load_error");
  assert(loadErrorPanel.kind === "load_error", "Load error should expose durable panel kind");
  assert(loadErrorPanel.title.includes("重新连接"), "Load error title should explain automatic recovery");
  assert(loadErrorPanel.action.includes("重新连接"), "Load error action should retry loading");
  assert(loadErrorPanel.formHidden === true, "Load error should not show a fake task form");
  assert(loadErrorPanel.role === "status" && loadErrorPanel.live === "polite", "Load error panel should be polite live status");
  await loadErrorPage.close();

  const teachingPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const teachingPayload = {
    schema_version: "3.0.0-daily-flow",
    child_state: "teaching",
    ready_for_new_knowledge: false,
    message: {},
    current_step: {
      step_handle: "teaching-step-smoke",
      position: 2,
      kind_label: "讲解",
      topic_label: "一次函数前置小修",
      prompt: "刚才的关键断点：没有把等量关系写出来。先看：设未知数前，先把题目里的两个量如何变化写清楚。",
      answer_input_mode: "none",
      allowed_response_modes: ["continue", "stuck"],
      upload_enabled: false,
      stuck_enabled: true,
      state: "selected",
      support: {
        hint: "看完后点继续，系统会给一题小检查。",
        continue_label: "继续小检查",
        stuck_label: "还是卡住",
      },
    },
  };
  await teachingPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(teachingPayload),
  }));
  let continueRequest = null;
  await teachingPage.route("**/api/current-step/continue", async (route) => {
    continueRequest = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "3.0.0-daily-flow",
        child_state: "current_step",
        ready_for_new_knowledge: false,
        message: {},
        current_step: {
          step_handle: "micro-check-smoke",
          position: 3,
          kind_label: "小互动",
          topic_label: "一次函数前置小修",
          prompt: "只写第一步关系：如果甲比乙多 8，设乙为 x，甲怎么表示？",
          answer_input_mode: "text",
          allowed_response_modes: ["text", "stuck"],
          upload_enabled: false,
          stuck_enabled: true,
          state: "selected",
          support: { hint: "只写关系，不用完整解题。" },
        },
      }),
    });
  });
  await teachingPage.goto(baseUrl);
  await teachingPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "feedback_teaching");
  const teachingView = await teachingPage.evaluate(() => ({
    continueVisible: Boolean(document.querySelector("[data-v3-continue-step]")?.offsetParent),
    stuckVisible: Boolean(document.querySelector("[data-v3-continue-stuck]")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    handoffHidden: document.querySelector("#childHandoffState")?.hidden,
    visibleText: document.body.textContent || "",
  }));
  assert(teachingView.continueVisible === true, "Teaching step should expose a visible continue action");
  assert(teachingView.stuckVisible === true, "Teaching step should expose a visible still-stuck action");
  assert(teachingView.formVisible === false, "Teaching step should not show answer form");
  assert(teachingView.handoffHidden === true, "Teaching step should not rely on hidden handoff container");
  assertChildSafe(teachingView.visibleText, "teaching page");
  await teachingPage.click("[data-v3-continue-step]");
  await teachingPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  assert(continueRequest?.step_handle === "teaching-step-smoke", "Teaching continue should send the current step handle");
  assert(continueRequest?.position === 2, "Teaching continue should send current position");
  assert(continueRequest?.stuck === false, "Teaching normal continue should not mark stuck");
  const microCheckView = await teachingPage.evaluate(() => ({
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    photoHidden: document.querySelector(".photo-field")?.hidden,
    label: document.querySelector(".question-block-label")?.textContent || "",
  }));
  assert(microCheckView.formVisible === true, "Micro-check after teaching should show answer form");
  assert(microCheckView.photoHidden === true, "Text-only micro-check should hide photo upload");
  assert(microCheckView.label.includes("题目"), "Micro-check should render as a current task");
  await teachingPage.close();

  const clarifyPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let clarifyCannotProvideRequest = null;
  let clarifyCannotProvideRequestCount = 0;
  await clarifyPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      schema_version: "3.0.0-daily-flow",
      child_state: "clarify_evidence",
      ready_for_new_knowledge: false,
      message: {},
      current_step: {
        step_handle: "clarify-step-smoke",
        position: 2,
        kind_label: "确认一下",
        topic_label: "分数应用题",
        prompt: "刚才的答案或照片不够清楚，系统还不能安全判断。请补一段关键步骤和最后答案，或重新拍一张清楚的纸面过程。",
        answer_input_mode: "clarification",
        allowed_response_modes: ["text", "photo", "text_photo", "clarification", "stuck"],
        upload_enabled: true,
        stuck_enabled: true,
        state: "selected",
        support: { hint: "补充证据后再保存。" },
      },
    }),
  }));
  await clarifyPage.route("**/api/current-step/submit", async (route) => {
    clarifyCannotProvideRequestCount += 1;
    clarifyCannotProvideRequest = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "3.0.0-daily-flow",
        child_state: "summary",
        ready_for_new_knowledge: false,
        message: {},
        summary: {
          title: "今天先到这里",
          what_went_well: "刚才的作答和补充状态都已经保存。",
          keep_working_on: "下次从这一步重新说明关键关系。",
          pending_note: "这条证据仍然不够清楚，没有用于判断掌握情况。",
          blocked_note: "今天先安全停下。",
          next_action: "完成今天的学习。",
        },
      }),
    });
  });
  await clarifyPage.goto(baseUrl);
  await clarifyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "clarify_evidence");
  const clarifyView = await clarifyPage.evaluate(() => ({
    label: document.querySelector(".question-block-label")?.textContent || "",
    submit: document.querySelector("#childSubmitBtn")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    photoHidden: document.querySelector(".photo-field")?.hidden,
    placeholder: document.querySelector("#childAnswerRaw")?.placeholder || "",
    cannotProvideVisible: Boolean(document.querySelector("[data-v3-stuck-prompt]")?.offsetParent),
    cannotProvideText: [...document.querySelectorAll("[data-v3-stuck-prompt]")].map((button) => button.textContent || "").join(" "),
    visibleText: document.body.textContent || "",
  }));
  assert(clarifyView.label.includes("请补清楚"), "Clarify evidence should not render as a generic question");
  assert(clarifyView.submit.includes("保存补充"), "Clarify evidence should use add-evidence submit copy");
  assert(clarifyView.formVisible === true, "Clarify evidence should show response form");
  assert(clarifyView.photoHidden === false, "Clarify evidence should allow clearer photo");
  assert(clarifyView.placeholder.includes("关键步骤"), "Clarify placeholder should ask for missing evidence");
  assert(clarifyView.cannotProvideVisible === true, "Clarify evidence should expose a child-safe cannot-provide/stuck path");
  assert(
    /无法补充|不能补充|还是不清楚|仍然不清楚/.test(clarifyView.cannotProvideText),
    "Clarify evidence should name a distinct cannot-provide/still-unclear action instead of only generic stuck reasons",
  );
  assertChildSafe(clarifyView.visibleText, "clarify page");
  await clarifyPage.evaluate(() => {
    const button = [...document.querySelectorAll("[data-v3-stuck-prompt]")]
      .find((candidate) => /无法补充|不能补充|还是不清楚|仍然不清楚/.test(candidate.textContent || ""));
    button?.click();
  });
  await clarifyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "summary");
  assert(clarifyCannotProvideRequestCount === 1, "Cannot-provide clarification should submit exactly one request");
  assert(
    typeof clarifyCannotProvideRequest?.client_idempotency_key === "string"
      && clarifyCannotProvideRequest.client_idempotency_key.length > 0,
    "Cannot-provide clarification should carry one client idempotency key",
  );
  assert(clarifyCannotProvideRequest?.stuck === true, "Cannot-provide clarification should submit an explicit stuck/cannot-provide signal");
  assert(
    /无法补充|不能补充|还是不清楚|仍然不清楚/.test(clarifyCannotProvideRequest?.answer_text || ""),
    "Cannot-provide clarification should preserve the child's explicit still-unclear evidence",
  );
  const clarifyExit = await clarifyPage.evaluate(() => ({
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    primaryVisible: Boolean(document.querySelector("#startNextRoundBtn")?.offsetParent),
    primaryLabel: document.querySelector("#startNextRoundBtn")?.textContent || "",
  }));
  assert(clarifyExit.formVisible === false, "Cannot-provide clarification should exit without another answer form loop");
  assert(clarifyExit.primaryVisible === true, "Cannot-provide clarification summary should allow returning to the knowledge directory");
  assert(clarifyExit.primaryLabel.includes("知识目录"), "Cannot-provide clarification must not start another answer loop");
  await clarifyPage.close();

  const readyPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const readyCheckpointPayload = {
    schema_version: "3.0.0-daily-flow",
    child_state: "ready_for_new_knowledge",
    ready_for_new_knowledge: true,
    message: {
      title: "旧知识复习暂时告一段落",
      body: "如果还有精神，可以学一个新知识；也可以今天到这里。",
      action_label: "学习新知识",
    },
  };
  const structuredTeachingPayload = {
    schema_version: "3.0.0-daily-flow",
    child_state: "teaching",
    ready_for_new_knowledge: false,
    message: {},
    current_step: {
      step_handle: "worked-example-smoke",
      position: 4,
      kind_label: "例题",
      topic_label: "有理数加法",
      prompt: "请按本质、核心模型和例题三个部分学习。",
      answer_input_mode: "none",
      allowed_response_modes: ["continue", "stuck"],
      upload_enabled: false,
      stuck_enabled: true,
      state: "selected",
      teaching_sections: {
        essence: {
          title: "本质",
          body: "有理数加法是在数轴上合并方向和距离。",
        },
        core_model: {
          title: "核心模型",
          body: "先判断方向，再比较绝对值，最后确定符号和大小。",
        },
        worked_example: {
          title: "例题",
          problem: "-3+5 怎么算？",
          steps: ["从 -3 出发", "向右移动 5 个单位", "到达 2"],
          check: "2-5=-3，所以结果与原关系一致。",
        },
      },
      support: { hint: "看懂再继续。", continue_label: "继续小检查", stuck_label: "这里没看懂" },
    },
  };
  let startNewKnowledgeCalled = false;
  await readyPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(startNewKnowledgeCalled ? structuredTeachingPayload : readyCheckpointPayload),
  }));
  await readyPage.route("**/api/daily-flow/new-knowledge/start", async (route) => {
    startNewKnowledgeCalled = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "3.0.0-daily-flow",
        child_state: "analyzing",
        ready_for_new_knowledge: false,
        message: {
          title: "正在准备新知识讲解",
          body: "讲解正在生成，还没有可展示的例题。准备好后会自动出现下一步。",
        },
      }),
    });
  });
  await readyPage.goto(baseUrl);
  await readyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "ready_for_new_knowledge");
  const readyView = await readyPage.evaluate(() => ({
    primary: document.querySelector("#startNextRoundBtn")?.textContent || "",
    primaryVisible: Boolean(document.querySelector("#startNextRoundBtn")?.offsetParent),
    secondary: document.querySelector("#v3SecondaryActionBtn")?.textContent || "",
    secondaryVisible: Boolean(document.querySelector("#v3SecondaryActionBtn")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    visibleText: document.body.textContent || "",
  }));
  assert(readyView.primaryVisible === true && readyView.primary.includes("学习新知识"), "Ready checkpoint should expose learn-new primary action");
  assert(readyView.secondaryVisible === true && readyView.secondary.includes("今天到这里"), "Ready checkpoint should expose finish action");
  assert(readyView.formVisible === false, "Ready checkpoint should not show answer form");
  assertChildSafe(readyView.visibleText, "ready checkpoint page");
  await readyPage.click("#startNextRoundBtn");
  await readyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  assert(startNewKnowledgeCalled === true, "Ready primary action should call new-knowledge endpoint");
  const pendingTeachingView = await readyPage.evaluate(() => ({
    body: document.body.textContent || "",
    continueVisible: Boolean(document.querySelector("[data-v3-continue-step]")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
  }));
  assert(pendingTeachingView.body.includes("正在准备新知识讲解"), "New knowledge must show an honest teaching-pending conclusion");
  assert(pendingTeachingView.body.includes("还没有可展示的例题"), "Pending teaching must not imply an accepted worked example already exists");
  assert(pendingTeachingView.continueVisible === false, "Pending teaching must not expose continue before accepted teaching output");
  assert(pendingTeachingView.formVisible === false, "Pending teaching must not expose an answer form");
  await readyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "feedback_teaching");
  const workedExampleView = await readyPage.evaluate(() => ({
    type: document.querySelector("#childTaskType")?.textContent || "",
    continueVisible: Boolean(document.querySelector("[data-v3-continue-step]")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    sectionKeys: [...document.querySelectorAll("[data-v5-teaching-section]")]
      .map((element) => element.getAttribute("data-v5-teaching-section")),
    sectionText: [...document.querySelectorAll("[data-v5-teaching-section]")]
      .map((element) => element.textContent || "").join("\n"),
  }));
  assert(workedExampleView.type.includes("例题"), "Accepted new knowledge should render a worked example");
  assert(
    JSON.stringify(workedExampleView.sectionKeys) === JSON.stringify(["essence", "core_model", "worked_example"]),
    "Teaching UI must render structured essence, core-model, and worked-example sections in order",
  );
  assert(workedExampleView.sectionText.includes("有理数加法是在数轴上"), "Teaching essence must be visible");
  assert(workedExampleView.sectionText.includes("先判断方向"), "Teaching core model must be visible");
  assert(workedExampleView.sectionText.includes("2-5=-3"), "Worked example must expose its check, not only an '例题' label");
  assert(workedExampleView.continueVisible === true, "Worked example should expose visible continue");
  assert(workedExampleView.formVisible === false, "Worked example should not ask for an answer before continue");
  await readyPage.close();

  const summaryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await summaryPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      schema_version: "3.0.0-daily-flow",
      child_state: "summary",
      ready_for_new_knowledge: false,
      message: { action_label: "刷新" },
      summary: {
        title: "今天先到这里",
        what_went_well: "今天有 2 条作答证据已经确认。",
        keep_working_on: "还有 1 处步骤不够稳，下次先修这里。",
        pending_note: "还有 1 条证据需要补充清楚后再判断。",
        blocked_note: "其中有步骤暂时不能安全判断。",
        next_action: "休息一下；下次从最需要巩固的地方继续。",
        labels: { confirmed: 2, pending: 1, blocked: 1 },
      },
    }),
  }));
  await summaryPage.goto(baseUrl);
  await summaryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "summary");
  const summaryView = await summaryPage.evaluate(() => ({
    heading: document.querySelector("#childHeading")?.textContent || "",
    progress: document.querySelector("#childProgressText")?.textContent || "",
    body: document.querySelector("#childHandoffText")?.textContent || "",
    reviewText: document.querySelector("#childReviewPoints")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    primaryVisible: Boolean(document.querySelector("#startNextRoundBtn")?.offsetParent),
    primaryLabel: document.querySelector("#startNextRoundBtn")?.textContent || "",
    secondaryVisible: Boolean(document.querySelector("#v3SecondaryActionBtn")?.offsetParent),
    visibleActions: [...document.querySelectorAll("button")]
      .filter((button) => Boolean(button.offsetParent))
      .map((button) => button.textContent || ""),
    visibleText: document.body.textContent || "",
  }));
  assert(summaryView.heading.includes("今天先到这里"), "Summary should use summary title");
  assert(summaryView.progress.includes("今日总结"), "Summary should not look like a worksheet");
  assert(summaryView.reviewText.includes("已确认"), "Summary should show confirmed section");
  assert(summaryView.reviewText.includes("还要练"), "Summary should show weak section");
  assert(summaryView.reviewText.includes("待判断"), "Summary should show pending section");
  assert(summaryView.reviewText.includes("暂时不能判断"), "Summary should show blocked section");
  assert(summaryView.body.includes("下次"), "Summary should show next action");
  assert(summaryView.formVisible === false, "Summary should not show answer form");
  assert(summaryView.primaryVisible === true, "Summary must offer a clear route back to the knowledge directory");
  assert(summaryView.primaryLabel.includes("知识目录"), "Summary primary action should name the knowledge directory");
  assert(summaryView.secondaryVisible === false, "Terminal summary should not expose a second continuation action");
  assert(
    !summaryView.visibleActions.some((label) => /保存|提交|下一题|继续下一步|再试/.test(label)),
    "Terminal summary should have a finish/no-op contract, not an answer, retry, or next-question command",
  );
  await summaryPage.locator("#startNextRoundBtn").click();
  await summaryPage.waitForFunction(() => Boolean(document.querySelector("#view-knowledge-home")?.offsetParent));
  const summaryExitView = await summaryPage.evaluate(() => ({
    heading: document.querySelector("[data-knowledge-heading]")?.textContent || "",
  }));
  assert(summaryExitView.heading.includes("今天从这里开始"), "Summary exit should open the knowledge home");
  assertChildSafe(summaryView.visibleText, "summary page");
  await summaryPage.close();

  const analyzingCopyPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await analyzingCopyPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      schema_version: "3.0.0-daily-flow",
      child_state: "analyzing",
      ready_for_new_knowledge: false,
      message: {},
    }),
  }));
  await analyzingCopyPage.goto(baseUrl);
  await analyzingCopyPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  const analyzingCopy = await analyzingCopyPage.evaluate(() => ({
    body: document.querySelector("#childHandoffText")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
  }));
  assert(analyzingCopy.body.includes("答案已经保存"), "Analyzing fallback must say the answer is already saved");
  assert(analyzingCopy.formVisible === false, "Analyzing fallback must not reopen the answer form");
  await analyzingCopyPage.close();

  const blockedAutoRecoveryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  let blockedAutoRecoveryBootstrapCount = 0;
  await blockedAutoRecoveryPage.route("**/api/child-bootstrap", (route) => {
    blockedAutoRecoveryBootstrapCount += 1;
    const payload = blockedAutoRecoveryBootstrapCount <= 2
      ? {
          schema_version: "3.0.0-daily-flow",
          child_state: "blocked",
          ready_for_new_knowledge: false,
          message: {
            title: "今天的学习暂时不能继续",
            body: "作答已经保存，系统暂时不能安全判断这一步。",
            action_label: "稍后再试",
          },
        }
      : {
          schema_version: "3.0.0-daily-flow",
          child_state: "current_step",
          ready_for_new_knowledge: false,
          message: {},
          current_step: {
            step_handle: "auto-recovered-step-smoke",
            position: 3,
            kind_label: "小检测",
            topic_label: "自动恢复后的当前步骤",
            prompt: "自动恢复后只做这一小步：写出关键关系。",
            answer_input_mode: "text",
            allowed_response_modes: ["text", "stuck"],
            upload_enabled: false,
            stuck_enabled: true,
            state: "selected",
            support: { hint: "先写关系。" },
          },
        };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  await blockedAutoRecoveryPage.goto(baseUrl);
  await blockedAutoRecoveryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "blocked");
  const blockedAutoInitial = await blockedAutoRecoveryPage.evaluate(() => ({
    action: document.querySelector("#startNextRoundBtn")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    visibleText: document.body.textContent || "",
  }));
  assert(blockedAutoInitial.action.includes("重新检查"), "Blocked vague retry action should be child-clear");
  assert(blockedAutoInitial.formVisible === false, "Blocked auto-recovery should not reopen the answer form before recovery");
  assertChildSafe(blockedAutoInitial.visibleText, "blocked auto-recovery initial page");
  await blockedAutoRecoveryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  const blockedAutoView = await blockedAutoRecoveryPage.evaluate(() => ({
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    prompt: document.querySelector("#childTaskContent")?.textContent || "",
    visibleText: document.body.textContent || "",
  }));
  assert(blockedAutoRecoveryBootstrapCount === 3, "Blocked auto-recovery should keep polling when the first recovery check is still blocked");
  assert(blockedAutoView.formVisible === true, "Auto-recovered blocked state should restore a real current step");
  assert(blockedAutoView.prompt.includes("自动恢复后"), "Auto-recovered blocked state should render the recovered step");
  assertChildSafe(blockedAutoView.visibleText, "blocked auto-recovery recovered page");
  await new Promise((resolve) => setTimeout(resolve, 1300));
  assert(blockedAutoRecoveryBootstrapCount === 3, "Blocked auto-recovery should stop polling after current_step is rendered");
  await blockedAutoRecoveryPage.close();

  const blockedRetryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  let blockedRetryBootstrapCount = 0;
  await blockedRetryPage.route("**/api/child-bootstrap", (route) => {
    blockedRetryBootstrapCount += 1;
    const payload = blockedRetryBootstrapCount === 1
      ? {
          schema_version: "3.0.0-daily-flow",
          child_state: "blocked",
          ready_for_new_knowledge: false,
          message: {
            title: "今天的学习暂时不能继续",
            body: "作答已经保存，系统暂时不能安全判断这一步。",
            action_label: "再试一次",
          },
        }
      : {
          schema_version: "3.0.0-daily-flow",
          child_state: "current_step",
          ready_for_new_knowledge: false,
          message: {},
          current_step: {
            step_handle: "recovered-step-smoke",
            position: 3,
            kind_label: "小检测",
            topic_label: "恢复后的当前步骤",
            prompt: "恢复后只做这一小步：写出关键关系。",
            answer_input_mode: "text",
            allowed_response_modes: ["text", "stuck"],
            upload_enabled: false,
            stuck_enabled: true,
            state: "selected",
            support: { hint: "先写关系。" },
          },
        };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  await blockedRetryPage.goto(baseUrl);
  await blockedRetryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "blocked");
  await blockedRetryPage.click("#startNextRoundBtn");
  await blockedRetryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  const blockedRetryView = await blockedRetryPage.evaluate(() => ({
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    prompt: document.querySelector("#childTaskContent")?.textContent || "",
  }));
  assert(blockedRetryBootstrapCount === 2, "Blocked primary retry should perform one bounded recovery request");
  assert(blockedRetryView.formVisible === true, "Recovered blocked retry should restore a real current step");
  assert(blockedRetryView.prompt.includes("恢复后"), "Recovered blocked retry should render the recovered step, not generic refresh copy");
  await blockedRetryPage.close();

  const blockedExhaustionPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  let blockedExhaustionBootstrapCount = 0;
  await blockedExhaustionPage.route("**/api/child-bootstrap", (route) => {
    blockedExhaustionBootstrapCount += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "3.0.0-daily-flow",
        child_state: "blocked",
        ready_for_new_knowledge: false,
        message: {
          title: "今天的学习暂时不能继续",
          body: "答案已经保存，但系统暂时不能安全判断这一步。",
          action_label: "稍后再试",
        },
      }),
    });
  });
  await blockedExhaustionPage.goto(baseUrl);
  await blockedExhaustionPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "blocked");
  await waitForCondition(() => blockedExhaustionBootstrapCount >= 4, "blocked recovery exhaustion");
  assert(blockedExhaustionBootstrapCount === 4, "Blocked auto-recovery should stop after the initial bootstrap plus three recovery checks");
  await new Promise((resolve) => setTimeout(resolve, 1300));
  assert(blockedExhaustionBootstrapCount === 4, "Exhausted blocked auto-recovery must not keep polling forever");
  const blockedExhaustionView = await blockedExhaustionPage.evaluate(() => ({
    primary: document.querySelector("#startNextRoundBtn")?.textContent || "",
    primaryVisible: Boolean(document.querySelector("#startNextRoundBtn")?.offsetParent),
    secondary: document.querySelector("#v3SecondaryActionBtn")?.textContent || "",
    secondaryVisible: Boolean(document.querySelector("#v3SecondaryActionBtn")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    visibleText: document.body.textContent || "",
  }));
  assert(blockedExhaustionView.primaryVisible === true && blockedExhaustionView.primary.includes("重新检查"), "Exhausted blocked state should keep a clear manual recovery action");
  assert(blockedExhaustionView.secondaryVisible === true && blockedExhaustionView.secondary.includes("今天到这里"), "Exhausted blocked state should keep the safe finish action");
  assert(blockedExhaustionView.formVisible === false, "Exhausted blocked state should not reopen the answer form");
  assert(blockedExhaustionView.visibleText.includes("答案已经保存"), "Exhausted blocked state should still explain saved evidence");
  assertChildSafe(blockedExhaustionView.visibleText, "blocked recovery exhaustion page");
  await blockedExhaustionPage.close();

  const blockedPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await blockedPage.route("**/api/child-bootstrap", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      schema_version: "3.0.0-daily-flow",
      child_state: "blocked",
      ready_for_new_knowledge: false,
      message: {
        title: "今天的学习暂时不能继续",
        action_label: "再试一次",
      },
    }),
  }));
  let blockedFinishRequestCount = 0;
  let releaseBlockedFinish;
  const blockedFinishGate = new Promise((resolve) => { releaseBlockedFinish = resolve; });
  await blockedPage.route("**/api/daily-flow/finish", async (route) => {
    blockedFinishRequestCount += 1;
    await blockedFinishGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "3.0.0-daily-flow",
        child_state: "summary",
        ready_for_new_knowledge: false,
        message: {},
        summary: {
          title: "今天先到这里",
          what_went_well: "今天的作答已经保存。",
          keep_working_on: "下一次继续把关键关系写清楚。",
          pending_note: "还有证据需要等系统恢复后再判断。",
          blocked_note: "有一步暂时不能安全判断。",
          next_action: "先休息。",
        },
      }),
    });
  });
  await blockedPage.goto(baseUrl);
  await blockedPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "blocked");
  const blockedView = await blockedPage.evaluate(() => ({
    primary: document.querySelector("#startNextRoundBtn")?.textContent || "",
    primaryVisible: Boolean(document.querySelector("#startNextRoundBtn")?.offsetParent),
    secondary: document.querySelector("#v3SecondaryActionBtn")?.textContent || "",
    secondaryVisible: Boolean(document.querySelector("#v3SecondaryActionBtn")?.offsetParent),
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    visibleText: document.body.textContent || "",
    body: document.querySelector("#childHandoffText")?.textContent || "",
  }));
  assert(blockedView.primaryVisible === true && blockedView.primary.includes("重新检查"), "Blocked should expose a clear recovery action");
  assert(blockedView.secondaryVisible === true && blockedView.secondary.includes("今天到这里"), "Blocked should expose safe finish");
  assert(blockedView.body.includes("答案已经保存"), "Blocked fallback without backend body must say saved evidence is retained");
  assert(blockedView.body.includes("再试一次") && blockedView.body.includes("今天到这里"), "Blocked fallback must explain retry and finish outcomes");
  assert(blockedView.formVisible === false, "Blocked should not show answer form");
  assertChildSafe(blockedView.visibleText, "blocked page");
  const blockedFinishRequest = blockedPage.waitForRequest("**/api/daily-flow/finish");
  await blockedPage.evaluate(() => {
    const button = document.querySelector("#v3SecondaryActionBtn");
    button.click();
    button.click();
  });
  await blockedFinishRequest;
  const finishInFlight = await blockedPage.evaluate(() => ({
    disabled: document.querySelector("#v3SecondaryActionBtn")?.disabled,
    label: document.querySelector("#v3SecondaryActionBtn")?.textContent || "",
  }));
  assert(finishInFlight.disabled === true, "Finish button must be disabled while the finish request is in flight");
  assert(finishInFlight.label.includes("正在整理总结"), "Finish button must expose an honest in-flight label");
  assert(blockedFinishRequestCount === 1, "Double-clicking finish must send exactly one request while in flight");
  releaseBlockedFinish();
  await blockedPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "summary");
  assert(blockedFinishRequestCount === 1, "Blocked finish must remain idempotent after the summary response");
  await blockedPage.close();

  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const browserErrors = [];
  const expectedConsoleErrorFragments = [
    "Failed to load resource: the server responded with a status of 503",
  ];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && !expectedConsoleErrorFragments.some((fragment) => text.includes(fragment))) {
      browserErrors.push(text);
    }
  });

  await page.goto(baseUrl);
  await page.waitForFunction(() => document.querySelector("#dbStatus")?.textContent.includes("准备好了"));
  await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "start_resume");

  const initialChildBootstrap = await fetch(`${baseUrl}/api/child-bootstrap`).then((response) => response.json());
  assert(initialChildBootstrap.schema_version === "3.0.0-daily-flow", "Child bootstrap should use v5 daily-flow projection");
  assert(canonicalV5ChildStates.includes(initialChildBootstrap.child_state), `Child state must be canonical v5, got ${initialChildBootstrap.child_state}`);
  assert(initialChildBootstrap.child_state === "start_resume", "Child should start from canonical start_resume state");
  assert(!("today_plan" in initialChildBootstrap), "v5 child bootstrap must not expose a fixed worksheet");
  assertNoLegacyV5Payload(initialChildBootstrap, "initial child bootstrap");
  assertChildSafe(JSON.stringify(initialChildBootstrap), "initial child bootstrap");

  const initialPage = await page.evaluate(() => ({
    title: document.querySelector("#pageTitle")?.textContent || "",
    action: document.querySelector("#startNextRoundBtn")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
    visibleText: document.body.textContent || "",
  }));
  assert(initialPage.title === "今天的数学学习", "v5 initial view should be daily math learning");
  assert(initialPage.action.includes("开始今天学习"), "Initial action should start today's adaptive learning flow");
  assert(initialPage.formVisible === false, "Choose-review state should not show an answer form");
  assertChildSafe(initialPage.visibleText, "initial page");

  await page.click("#startNextRoundBtn");
  await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  await page.waitForSelector("#childAttemptForm:not([hidden])");
  const currentStepView = await page.evaluate(() => ({
    heading: document.querySelector("#childHeading")?.textContent || "",
    type: document.querySelector("#childTaskType")?.textContent || "",
    content: document.querySelector("#childTaskContent")?.textContent || "",
    submit: document.querySelector("#childSubmitBtn")?.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
  }));
  assert(currentStepView.heading, "Current step should have a topic heading");
  assert(currentStepView.type.includes("小检测") || currentStepView.type.includes("学习"), "Current step should show a child-safe step type");
  assert(currentStepView.content.includes("题目"), "Child should see one concrete current question");
  assert(currentStepView.submit.includes("保存"), "Current step should save an answer");
  assert(currentStepView.formVisible === true, "Current step should show answer form");
  const currentStepPayload = await fetch(`${baseUrl}/api/child-bootstrap`).then((response) => response.json());
  assertNoLegacyV5Payload(currentStepPayload, "current-step payload");
  assertChildSafe(JSON.stringify(currentStepPayload), "current-step payload");
  assertChildSafe(currentStepView.content, "current-step content");

  await page.fill("#childAnswerRaw", "我不知道第一步，但先写下目前能确定的关系。");

  fs.writeFileSync(invalidUploadPath, "not an image");
  await page.setInputFiles("#childAnswerPhoto", invalidUploadPath);
  await page.waitForSelector("#childErrorPanel[data-error-kind='upload_error']:not([hidden])");
  const uploadErrorPanel = await page.evaluate(() => ({
    state: window.ChildLearningShell?.currentState(),
    title: document.querySelector("#childErrorTitle")?.textContent || "",
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
    draft: document.querySelector("#childAnswerRaw")?.value || "",
    previewHidden: document.querySelector("#childPhotoPreview")?.hidden,
  }));
  assert(uploadErrorPanel.state === "upload_error", "Invalid photo should enter upload_error");
  assert(uploadErrorPanel.title.includes("照片"), "Upload error panel should name the photo issue");
  assert(uploadErrorPanel.action.includes("重新选择"), "Upload error panel should offer reselect");
  assert(uploadErrorPanel.draft.includes("不知道第一步"), "Upload error should keep the typed draft");
  assert(uploadErrorPanel.previewHidden === true, "Invalid photo should not leave a stale preview");

  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
    "base64",
  );
  fs.writeFileSync(uploadPath, onePixelPng);
  await page.setInputFiles("#childAnswerPhoto", uploadPath);
  await page.waitForSelector("#childPhotoPreview:not([hidden])");
  await page.waitForFunction(() => document.querySelector("#childPhotoThumb")?.naturalWidth > 0);

  await page.fill("#childAnswerRaw", "我先写能确定的关系：先找基准量，再写出比较和检验。");
  let failNextSubmission = true;
  const submissionRoute = async (route) => {
    if (failNextSubmission) {
      failNextSubmission = false;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "temporary save break" }),
      });
      return;
    }
    await route.continue();
  };
  await page.route("**/api/current-step/submit", submissionRoute);
  await page.click("#childAttemptForm button[type='submit']");
  await page.waitForSelector("#childErrorPanel[data-error-kind='save_error']:not([hidden])");
  const saveErrorPanel = await page.evaluate(() => ({
    state: window.ChildLearningShell?.currentState(),
    title: document.querySelector("#childErrorTitle")?.textContent || "",
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
    draft: document.querySelector("#childAnswerRaw")?.value || "",
    photoVisible: Boolean(document.querySelector("#childPhotoPreview")?.offsetParent),
  }));
  assert(saveErrorPanel.state === "save_error", "Failed current-step submission should enter save_error");
  assert(saveErrorPanel.title.includes("保存"), "Save error panel should name the save issue");
  assert(saveErrorPanel.action.includes("保存"), "Save error panel should expose retry");
  assert(saveErrorPanel.draft.includes("基准量"), "Save error should keep typed work");
  assert(saveErrorPanel.photoVisible === true, "Save error should keep selected photo preview");

  await page.unroute("**/api/current-step/submit", submissionRoute);
  await page.click("#childErrorActionBtn");
  await page.waitForFunction(() => ["analyzing_pending", "blocked"].includes(window.ChildLearningShell?.currentState()));
  await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "blocked", null, { timeout: 15000 });
  const blockedState = await page.evaluate(() => ({
    state: window.ChildLearningShell?.currentState(),
    visibleText: document.body.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
  }));
  assert(blockedState.state === "blocked", "Missing model config should become honest blocked state");
  assert(blockedState.visibleText.includes("暂时不可用") || blockedState.visibleText.includes("安全停下"), "Blocked state should honestly explain the wait");
  assert(blockedState.formVisible === false, "Blocked state should not leave a stale answer form");
  assertChildSafe(blockedState.visibleText, "blocked page");

  const finalChildBootstrap = await fetch(`${baseUrl}/api/child-bootstrap`).then((response) => response.json());
  assert(finalChildBootstrap.schema_version === "3.0.0-daily-flow", "Blocked child bootstrap should still be v5");
  assert(canonicalV5ChildStates.includes(finalChildBootstrap.child_state), `Blocked bootstrap state must be canonical v5, got ${finalChildBootstrap.child_state}`);
  assert(finalChildBootstrap.child_state === "blocked", "Blocked state should persist through bootstrap");
  assertNoLegacyV5Payload(finalChildBootstrap, "blocked child bootstrap");
  assertChildSafe(JSON.stringify(finalChildBootstrap), "blocked child bootstrap");

  const operatorFlow = await fetch(`${baseUrl}/api/operator/daily-flow/today`, {
    headers: { Authorization: `Bearer ${operatorToken}` },
  }).then((response) => response.json());
  assert(operatorFlow.feature_enabled === true, "Operator evidence should know v5 runtime is enabled");
  assert(operatorFlow.flows.length === 1, "Smoke should create one v5 daily flow");
  assert(operatorFlow.attempts.length === 1, "Smoke should save exactly one attempt");
  assert(operatorFlow.jobs.some((job) => job.status === "blocked"), "Missing model config should create a blocked job");
  assert(
    !operatorFlow.evidence_validations.some((item) =>
      ["accepted", "passed", "usable"].includes(item.gate_status) || item.report_label === "confirmed"
    ),
    "Blocked model analysis must not create usable evidence",
  );
  assert(
    !operatorFlow.mastery_decisions?.some((item) => item.applied),
    "Blocked model analysis must not update mastery",
  );

  await browser.close();
  assert(browserErrors.length === 0, `browser errors: ${browserErrors.join("; ")}`);
  console.log("PASS browser smoke: v5 current-step child flow -> save/photo/stuck -> async blocked evidence");
} finally {
  server.kill("SIGTERM");
  if (fs.existsSync(dbPath)) fs.unlinkSync(dbPath);
  if (fs.existsSync(uploadPath)) fs.unlinkSync(uploadPath);
  if (fs.existsSync(invalidUploadPath)) fs.unlinkSync(invalidUploadPath);
  fs.rmSync(uploadRoot, { recursive: true, force: true });
  if (stderr.trim()) process.stderr.write(stderr);
}
