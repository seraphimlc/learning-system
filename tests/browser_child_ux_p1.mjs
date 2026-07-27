#!/usr/bin/env node
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const root = path.resolve(new URL("..", import.meta.url).pathname);
const appRoot = path.join(root, "app", "local_learning_system");
const port = await getFreePort();
const baseUrl = `http://127.0.0.1:${port}`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
    server.on("error", reject);
  });
}

async function waitUntil(predicate, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(message);
}

const currentStepPayload = {
  schema_version: "3.0.0-daily-flow",
  child_state: "current_step",
  ready_for_new_knowledge: false,
  message: {},
  current_step: {
    step_handle: "transport-step-secret-123",
    position: 7,
    kind_label: "小检测",
    topic_label: "含分母方程",
    prompt: "解方程：(x-1)/3+2=(x+5)/6。写出第一步去分母。",
    prompt_format: "2026-07-17.child-plain-text.v1",
    prompt_segments: [
      { type: "text", text: "解方程：(x-1)/3+2=(x+5)/6。写出第一步去分母。" },
    ],
    answer_input_mode: "text_photo",
    allowed_response_modes: ["text", "photo", "text_photo", "stuck"],
    upload_enabled: true,
    stuck_enabled: true,
    state: "selected",
    support: { hint: "先写两边同乘几。" },
    provider: "gpt",
    rubric: { secret: "not-for-child" },
    queue: { job_id: "BJ-secret" },
    attempt_id: "A-secret",
  },
};

const serverState = {
  bootstrapPayload: {
    schema_version: "3.0.0-daily-flow",
    child_state: "start_resume",
    ready_for_new_knowledge: false,
    message: { title: "开始今天学习", body: "先做当前这一步。", action_label: "开始今天学习" },
  },
  bootstrapCalls: 0,
  startCalls: 0,
  submitCalls: 0,
  continueCalls: 0,
  finishCalls: 0,
  submitBodies: [],
  continueBodies: [],
};

function resetServerState(payload) {
  serverState.bootstrapPayload = payload;
  serverState.bootstrapCalls = 0;
  serverState.startCalls = 0;
  serverState.submitCalls = 0;
  serverState.continueCalls = 0;
  serverState.finishCalls = 0;
  serverState.submitBodies = [];
  serverState.continueBodies = [];
}

function json(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, baseUrl);
  if (url.pathname === "/api/child-bootstrap") {
    serverState.bootstrapCalls += 1;
    if (serverState.bootstrapPayload === "poll-fail" && serverState.bootstrapCalls > 1) {
      json(res, 503, { error: "temporary poll break" });
      return;
    }
    json(res, 200, serverState.bootstrapPayload === "poll-fail" ? {
      schema_version: "3.0.0-daily-flow",
      child_state: "analyzing",
      ready_for_new_knowledge: false,
      message: { title: "正在看你的步骤", body: "答案已经保存。系统正在分析。" },
    } : serverState.bootstrapPayload);
    return;
  }
  if (url.pathname === "/api/daily-flow/review/start") {
    serverState.startCalls += 1;
    if (serverState.startCalls === 1) {
      json(res, 503, { error: "start review temporarily failed" });
      return;
    }
    json(res, 200, currentStepPayload);
    return;
  }
  if (url.pathname === "/api/current-step/submit") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk.toString(); });
    req.on("end", () => {
      serverState.submitCalls += 1;
      serverState.submitBodies.push(JSON.parse(raw || "{}"));
      if (serverState.submitCalls === 1 && serverState.failFirstSubmit) {
        json(res, 503, { error: "submit temporarily failed" });
        return;
      }
      json(res, 200, {
        schema_version: "3.0.0-daily-flow",
        child_state: "analyzing",
        ready_for_new_knowledge: false,
        message: { title: "正在看你的步骤", body: "答案已经保存。" },
      });
    });
    return;
  }
  if (url.pathname === "/api/current-step/continue") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk.toString(); });
    req.on("end", () => {
      serverState.continueCalls += 1;
      serverState.continueBodies.push(JSON.parse(raw || "{}"));
      if (serverState.continueCalls === 1) {
        json(res, 503, { error: "continue temporarily failed" });
        return;
      }
      json(res, 200, currentStepPayload);
    });
    return;
  }
  if (url.pathname === "/api/daily-flow/finish") {
    serverState.finishCalls += 1;
    if (serverState.finishCalls === 1) {
      json(res, 503, { error: "finish temporarily failed" });
      return;
    }
    json(res, 200, {
      schema_version: "3.0.0-daily-flow",
      child_state: "summary",
      ready_for_new_knowledge: false,
      message: {},
      summary: { title: "今天先到这里", next_action: "休息一下。" },
    });
    return;
  }
  const filePath = url.pathname === "/" ? path.join(appRoot, "index.html") : path.join(appRoot, url.pathname.slice(1));
  if (!filePath.startsWith(appRoot) || !fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  const ext = path.extname(filePath);
  const contentType = ext === ".js" ? "text/javascript" : ext === ".css" ? "text/css" : "text/html";
  res.writeHead(200, { "content-type": `${contentType}; charset=utf-8` });
  res.end(fs.readFileSync(filePath));
});

await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));

const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});

try {
  const startPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState({
    schema_version: "3.0.0-daily-flow",
    child_state: "start_resume",
    ready_for_new_knowledge: false,
    message: { title: "开始今天学习", body: "先做当前这一步。", action_label: "开始今天学习" },
  });
  await startPage.goto(baseUrl, { waitUntil: "networkidle" });
  await startPage.click("#startNextRoundBtn");
  await startPage.waitForSelector("#childErrorPanel:not([hidden])");
  const startError = await startPage.evaluate(() => ({
    kind: document.querySelector("#childErrorPanel")?.dataset.errorKind,
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
  }));
  assert(startError.kind === "start_review_error", "Start-review failure must record a distinct retry operation");
  assert(startError.action.includes("开始"), "Start-review retry copy must retry starting today's learning");
  await startPage.click("#childErrorActionBtn");
  await startPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  assert(serverState.startCalls === 2, "Start-review retry must call the start endpoint again");
  await startPage.close();

  const currentPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState(currentStepPayload);
  await currentPage.goto(baseUrl, { waitUntil: "networkidle" });
  await currentPage.waitForSelector("#childAttemptForm:not([hidden])");
  const initialControls = await currentPage.evaluate(() => {
    const answer = document.querySelector("#childAttemptForm")?.getBoundingClientRect();
    const stuck = document.querySelector(".v3-stuck-actions")?.getBoundingClientRect();
    const visibleText = document.body.textContent || "";
    return {
      answerTop: answer?.top || 0,
      stuckTop: stuck?.top || 0,
      hasStepHandleText: visibleText.includes("transport-step-secret-123"),
      hasPositionText: visibleText.includes("position"),
      hasForbidden: /attempt_id|provider|rubric|queue|job_id|A-secret|gpt/.test(visibleText),
    };
  });
  assert(initialControls.answerTop > 0 && initialControls.stuckTop > 0, "Answer and stuck controls must both be visible");
  assert(initialControls.answerTop < initialControls.stuckTop, "Answer evidence controls must appear before stuck/cannot-provide controls");
  assert(!initialControls.hasStepHandleText && !initialControls.hasPositionText, "step_handle/position must stay non-visible transport tokens");
  assert(!initialControls.hasForbidden, "Forbidden provider/rubric/queue/attempt internals must not render");
  const overflow390 = await currentPage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  assert(!overflow390, "390px layout must not horizontally overflow");

  await currentPage.click("[data-v3-stuck-prompt]");
  await currentPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  assert(serverState.submitCalls === 1, "A stuck reason must submit immediately without requiring a second save action");
  assert(serverState.submitBodies.at(-1)?.stuck === true, "Direct stuck action must preserve explicit stuck evidence");
  assert(serverState.submitBodies.at(-1)?.step_handle === "transport-step-secret-123", "Submit must preserve opaque step_handle transport token");
  assert(serverState.submitBodies.at(-1)?.position === 7, "Submit must preserve opaque position transport token");
  await currentPage.close();

  const voicePermissionPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await voicePermissionPage.addInitScript(() => {
    class PendingRecognition {
      start() {}
      stop() {}
    }
    window.webkitSpeechRecognition = window.webkitSpeechRecognition || PendingRecognition;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: () => new Promise(() => {}),
      },
    });
  });
  resetServerState(currentStepPayload);
  await voicePermissionPage.goto(baseUrl, { waitUntil: "networkidle" });
  await voicePermissionPage.click('[data-answer-input-mode="voice"]');
  await voicePermissionPage.click("#voiceRecordBtn");
  const voicePermissionState = await voicePermissionPage.evaluate(() => ({
    status: document.querySelector("#voiceStatus")?.textContent || "",
    disabled: Boolean(document.querySelector("#voiceRecordBtn")?.disabled),
  }));
  assert(voicePermissionState.status.includes("正在请求麦克风权限"), "Voice capture must show permission progress before the browser resolves getUserMedia");
  assert(voicePermissionState.disabled === true, "Voice record action must not be repeatedly clickable while permission is pending");
  await voicePermissionPage.close();

  const stuckRetryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState(currentStepPayload);
  serverState.failFirstSubmit = true;
  await stuckRetryPage.goto(baseUrl, { waitUntil: "networkidle" });
  await stuckRetryPage.click("[data-v3-stuck-prompt]");
  await stuckRetryPage.waitForSelector("#childErrorPanel[data-error-kind='save_error']:not([hidden])");
  const retryableStuckButton = stuckRetryPage.locator("[data-v3-stuck-prompt]").first();
  assert(await retryableStuckButton.isEnabled(), "A failed direct stuck submission must restore the stuck action for retry");
  await retryableStuckButton.click();
  await stuckRetryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  assert(serverState.submitCalls === 2, "Retrying the same stuck action must make exactly one additional request");
  assert(serverState.submitBodies.every((body) => body.stuck === true), "A direct stuck retry must preserve stuck semantics");
  serverState.failFirstSubmit = false;
  await stuckRetryPage.close();

  const saveRetryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState(currentStepPayload);
  serverState.failFirstSubmit = true;
  await saveRetryPage.goto(baseUrl, { waitUntil: "networkidle" });
  await saveRetryPage.fill("#childAnswerRaw", "先写关系，再计算。");
  await saveRetryPage.click("#childSubmitBtn");
  await saveRetryPage.waitForSelector("#childErrorPanel[data-error-kind='save_error']:not([hidden])");
  await saveRetryPage.click("#childErrorActionBtn");
  await saveRetryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  assert(serverState.submitCalls === 2, "Save retry action must resubmit the exact failed save operation");
  serverState.failFirstSubmit = false;
  await saveRetryPage.close();

  const continueRetryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState({
    ...currentStepPayload,
    child_state: "teaching",
    current_step: {
      ...currentStepPayload.current_step,
      answer_input_mode: "none",
      allowed_response_modes: ["continue", "stuck"],
      support: { continue_label: "继续小检查", stuck_label: "还是卡住" },
    },
  });
  await continueRetryPage.goto(baseUrl, { waitUntil: "networkidle" });
  await continueRetryPage.click("[data-v3-continue-stuck]");
  await continueRetryPage.waitForSelector("#childErrorPanel[data-error-kind='continue_error']:not([hidden])");
  const continueErrorBody = await continueRetryPage.locator("#childErrorBody").innerText();
  assert(!/保存/.test(continueErrorBody), "Continue failure copy must describe continuing, not saving");
  await continueRetryPage.click("#childErrorActionBtn");
  await waitUntil(() => serverState.continueCalls === 2, "Continue retry did not reach the server");
  assert(serverState.continueBodies[0].stuck === true && serverState.continueBodies[1].stuck === true, "Continue retry must retry the exact stuck continue operation");
  const retryToast = await continueRetryPage.locator("#toast").textContent();
  assert(!retryToast.includes("小结"), "Stuck continue toast must not promise a summary outcome");
  await continueRetryPage.close();

  const finishRetryPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState({
    schema_version: "3.0.0-daily-flow",
    child_state: "ready_for_new_knowledge",
    ready_for_new_knowledge: true,
    message: { title: "旧知识复习暂时告一段落", body: "可以学一个新知识。", action_label: "学一个新知识" },
  });
  await finishRetryPage.goto(baseUrl, { waitUntil: "networkidle" });
  await finishRetryPage.click("#v3SecondaryActionBtn");
  await finishRetryPage.waitForSelector("#childErrorPanel:not([hidden])");
  const finishError = await finishRetryPage.evaluate(() => ({
    kind: document.querySelector("#childErrorPanel")?.dataset.errorKind,
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
  }));
  assert(finishError.kind === "finish_error", "Finish failure must record a distinct retry operation");
  assert(finishError.action.includes("今天到这里") || finishError.action.includes("整理总结"), "Finish retry copy must retry finishing");
  await finishRetryPage.click("#childErrorActionBtn");
  await finishRetryPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "summary");
  assert(serverState.finishCalls === 2, "Finish retry action must call finish endpoint again");
  await finishRetryPage.close();

  const pollPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  resetServerState("poll-fail");
  await pollPage.goto(baseUrl, { waitUntil: "networkidle" });
  await pollPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "load_error", null, { timeout: 8000 });
  const pollFailure = await pollPage.evaluate(() => ({
    kind: document.querySelector("#childErrorPanel")?.dataset.errorKind,
    action: document.querySelector("#childErrorActionBtn")?.textContent || "",
    body: document.body.textContent || "",
    formVisible: Boolean(document.querySelector("#childAttemptForm")?.offsetParent),
  }));
  assert(pollFailure.kind === "load_error", "Repeated poll/bootstrap failure must converge to a persistent manual retry state");
  assert(pollFailure.action.includes("重新连接"), "Persistent poll failure must expose manual retry");
  assert(!/连接中/.test(pollFailure.body), "Persistent poll failure must not stay in infinite connecting copy");
  assert(!/没保存成功/.test(pollFailure.body), "Persistent poll failure must not contradict previously saved evidence");
  assert(pollFailure.formVisible === false, "Persistent poll failure must not reopen answer form");
  await pollPage.close();
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
