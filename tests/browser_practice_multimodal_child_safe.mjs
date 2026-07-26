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
const failures = [];
const requests = {
  handwriting: [],
  voice: [],
  submissions: [],
};
const privateValues = [
  "provider",
  "openai",
  "gpt-5.5",
  "model_alias",
  "job_id",
  "attempt_id",
  "question_id",
  "flow_id",
  "agent_run_id",
  "mini_group_id",
  "Q-private-42",
  "FLOW-private-42",
  "JOB-private-42",
  "ATT-private-42",
  "AR-private-42",
  "MG-private-42",
  "RH-private-handwriting",
  "RH-private-voice",
];

let activePayload = currentStepPayload();
let handwritingVariant = "clean";
let handwritingDelayMs = 0;
let handwritingFailureMessage = "";
let submissionResponses = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function check(name, callback) {
  try {
    await callback();
    process.stdout.write(`PASS ${name}\n`);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    failures.push(`${name}: ${detail}`);
    process.stdout.write(`FAIL ${name}: ${detail}\n`);
  }
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      probe.close(() => resolve(address.port));
    });
    probe.on("error", reject);
  });
}

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk.toString(); });
    req.on("end", () => {
      try {
        resolve(JSON.parse(raw || "{}"));
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function privateAuditFields() {
  return {
    provider: "openai",
    model_alias: "gpt-5.5",
    question_id: "Q-private-42",
    flow_id: "FLOW-private-42",
    job_id: "JOB-private-42",
    attempt_id: "ATT-private-42",
    agent_run_id: "AR-private-42",
    mini_group_id: "MG-private-42",
  };
}

function currentStepPayload(overrides = {}) {
  const stepOverrides = overrides.current_step || {};
  return {
    schema_version: "3.0.0-daily-flow",
    child_state: "current_step",
    ready_for_new_knowledge: false,
    message: {},
    current_step: {
      step_handle: "child-safe-practice-step",
      position: 1,
      kind_label: "练习",
      topic_label: "有理数",
      prompt: "写出 -3 在数轴上的位置，并说明它在 0 的哪一边。",
      prompt_format: "2026-07-17.child-plain-text.v1",
      prompt_segments: [
        { type: "text", text: "写出 -3 在数轴上的位置，并说明它在 0 的哪一边。" },
      ],
      answer_input_mode: "text",
      allowed_response_modes: ["text", "handwriting", "voice", "stuck"],
      upload_enabled: false,
      stuck_enabled: true,
      state: "selected",
      support: { hint: "先确定负号，再看与 0 的关系。" },
      ...privateAuditFields(),
      ...stepOverrides,
    },
    ...privateAuditFields(),
    ...Object.fromEntries(Object.entries(overrides).filter(([key]) => key !== "current_step")),
  };
}

function analyzingPayload() {
  return {
    schema_version: "3.0.0-daily-flow",
    child_state: "analyzing_pending",
    ready_for_new_knowledge: false,
    message: {
      title: "正在统一看这一组答案",
      body: "这一组答案已经保存，正在统一批阅并安排下一步。",
      action_label: "稍后再看",
    },
    ...privateAuditFields(),
  };
}

function resetRequests() {
  requests.handwriting.length = 0;
  requests.voice.length = 0;
  requests.submissions.length = 0;
  submissionResponses = [];
}

function assertChildSafe(text, label) {
  const lowered = String(text || "").toLowerCase();
  for (const value of privateValues) {
    assert(!lowered.includes(value.toLowerCase()), `${label} leaked ${value}`);
  }
}

async function assertPageChildSafe(page, label) {
  assertChildSafe(await page.locator("body").innerText(), label);
}

async function openScenario(browser, payload, { voiceStubs = false, submitResponses = [] } = {}) {
  activePayload = payload;
  resetRequests();
  submissionResponses = submitResponses.slice();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  if (voiceStubs) await installVoiceStubs(page);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
  await assertPageChildSafe(page, "initial child surface");
  return page;
}

async function installVoiceStubs(page) {
  await page.addInitScript(() => {
    const audioBytes = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0x42, 0x86, 0x81, 0x01]);
    const fakeTrack = { stop() {} };
    const fakeStream = { getTracks: () => [fakeTrack] };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => fakeStream },
    });

    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      constructor(stream, options = {}) {
        this.stream = stream;
        this.mimeType = options.mimeType || "audio/webm";
        this.state = "inactive";
      }
      start() {
        this.state = "recording";
        this.onstart?.();
      }
      stop() {
        if (this.state === "inactive") return;
        this.state = "inactive";
        const data = new Blob([audioBytes], { type: "audio/webm" });
        this.ondataavailable?.({ data });
        this.onstop?.();
      }
    }

    class FakeSpeechRecognition {
      constructor() {
        this.continuous = false;
        this.interimResults = false;
        this.lang = "zh-CN";
      }
      start() {
        this.onstart?.();
        setTimeout(() => {
          const alternative = { transcript: "-3", confidence: 0.96 };
          const result = [alternative];
          result.isFinal = true;
          const results = [result];
          results.item = (index) => results[index];
          this.onresult?.({ resultIndex: 0, results });
          this.onspeechend?.();
          this.onend?.();
        }, 20);
      }
      stop() { this.onend?.(); }
      abort() { this.onend?.(); }
    }

    window.MediaRecorder = FakeMediaRecorder;
    window.SpeechRecognition = FakeSpeechRecognition;
    window.webkitSpeechRecognition = FakeSpeechRecognition;
  });
}

async function modeVisibility(page) {
  return page.evaluate(() => ({
    typed: Boolean(document.querySelector('[data-answer-input-mode="typed"]')?.getClientRects().length),
    handwriting: Boolean(document.querySelector('[data-answer-input-mode="handwriting"]')?.getClientRects().length),
    voice: Boolean(document.querySelector('[data-answer-input-mode="voice"]')?.getClientRects().length),
    textarea: Boolean(document.querySelector("#childAnswerRaw")?.getClientRects().length),
    interaction: Boolean(document.querySelector("#interactionAnswerPanel")?.getClientRects().length),
    photo: Boolean(document.querySelector(".photo-field")?.getClientRects().length),
  }));
}

async function drawHandwriting(page) {
  const box = await page.locator("#handwritingCanvas").boundingBox();
  assert(box, "handwriting canvas must be visible before drawing");
  await page.mouse.move(box.x + 40, box.y + 80);
  await page.mouse.down();
  await page.mouse.move(box.x + 120, box.y + 80, { steps: 8 });
  await page.mouse.move(box.x + 90, box.y + 150, { steps: 8 });
  await page.mouse.up();
}

async function selectMode(page, mode) {
  const button = page.locator(`[data-answer-input-mode="${mode}"]`);
  assert(await button.isVisible(), `${mode} mode must be visible`);
  await button.click();
  assert(await button.getAttribute("aria-pressed") === "true", `${mode} mode must become selected`);
}

async function waitForRecognitionPanel(page) {
  await page.waitForSelector("#recognitionConfirmPanel:not([hidden])", { timeout: 3000 });
  assert(await page.locator("#recognizedAnswerText").isVisible(), "recognized text must be editable");
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, baseUrl);
  try {
    if (url.pathname === "/api/knowledge-map") {
      json(res, 404, { message: "当前先完成学习步骤。" });
      return;
    }
    if (url.pathname === "/api/child-bootstrap") {
      json(res, 200, activePayload);
      return;
    }
    if (url.pathname === "/api/input-recognition/handwriting") {
      requests.handwriting.push(await readJson(req));
      if (handwritingDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, handwritingDelayMs));
      }
      if (handwritingFailureMessage) {
        json(res, 503, { message: handwritingFailureMessage, ...privateAuditFields() });
        return;
      }
      const ambiguous = handwritingVariant === "ambiguous";
      json(res, 200, {
        status: ambiguous ? "needs_review" : "ready",
        recognition_handle: `RH-private-handwriting-${requests.handwriting.length}`,
        recognized_text: ambiguous ? "3" : "-3",
        critical_token_uncertainties: ambiguous
          ? [{ token: "-", location: "答案开头", reason: "负号可能没有识别出来" }]
          : [],
        confirmation_required: true,
        message: "请检查识别结果，确认无误后再保存。",
        ...privateAuditFields(),
      });
      return;
    }
    if (url.pathname === "/api/input-recognition/voice") {
      requests.voice.push(await readJson(req));
      json(res, 200, {
        status: "ready",
        recognition_handle: `RH-private-voice-${requests.voice.length}`,
        recognized_text: "-3",
        critical_token_uncertainties: [],
        confirmation_required: true,
        message: "请检查识别文字，确认无误后再保存。",
        ...privateAuditFields(),
      });
      return;
    }
    if (url.pathname === "/api/current-step/submit") {
      requests.submissions.push(await readJson(req));
      const response = submissionResponses.length
        ? submissionResponses.shift()
        : analyzingPayload();
      activePayload = response;
      json(res, 200, response);
      return;
    }

    const filePath = url.pathname === "/"
      ? path.join(appRoot, "index.html")
      : path.join(appRoot, url.pathname.slice(1));
    if (!filePath.startsWith(appRoot) || !fs.existsSync(filePath)) {
      json(res, 404, { message: "没有找到这个页面。" });
      return;
    }
    const ext = path.extname(filePath);
    const contentType = ext === ".js"
      ? "text/javascript"
      : ext === ".css"
        ? "text/css"
        : "text/html";
    res.writeHead(200, { "content-type": `${contentType}; charset=utf-8` });
    res.end(fs.readFileSync(filePath));
  } catch (error) {
    json(res, 500, { message: "测试服务暂时不可用。", detail: String(error) });
  }
});

await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});

try {
  await check("mode availability follows response type", async () => {
    let page = await openScenario(browser, currentStepPayload());
    let modes = await modeVisibility(page);
    assert(modes.typed && modes.handwriting && modes.voice, `free response modes are wrong: ${JSON.stringify(modes)}`);
    assert(modes.textarea && !modes.photo, `free response surface is wrong: ${JSON.stringify(modes)}`);
    await page.close();

    page = await openScenario(browser, currentStepPayload({
      current_step: {
        answer_input_mode: "interaction",
        allowed_response_modes: ["interaction", "stuck"],
        interaction_schema: {
          schema_version: "2026-07-17.interaction.v1",
          type: "single_choice",
          title: "选择 -3 所在的位置",
          allow_explanation: false,
          requires_explanation: false,
          choices: [
            { id: "left", label: "0 的左边" },
            { id: "right", label: "0 的右边" },
          ],
        },
      },
    }));
    modes = await modeVisibility(page);
    assert(modes.interaction, "choice response must expose its structured control");
    assert(!modes.handwriting && !modes.voice && !modes.textarea, `choice response exposed incompatible modes: ${JSON.stringify(modes)}`);
    await page.close();

    page = await openScenario(browser, currentStepPayload({
      current_step: {
        answer_input_mode: "photo",
        allowed_response_modes: ["photo", "stuck"],
        upload_enabled: true,
      },
    }));
    modes = await modeVisibility(page);
    assert(modes.photo && !modes.textarea, `photo response surface is wrong: ${JSON.stringify(modes)}`);
    assert(!modes.handwriting && !modes.voice, `photo response exposed incompatible recognition modes: ${JSON.stringify(modes)}`);
    await page.close();
  });

  await check("handwriting confirmation is required and edits invalidate it", async () => {
    handwritingVariant = "clean";
    const page = await openScenario(browser, currentStepPayload());
    await selectMode(page, "handwriting");
    assert(await page.locator("#handwritingInputPanel").isVisible(), "handwriting panel must open");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await waitForRecognitionPanel(page);
    assert(requests.handwriting.length === 1, "handwriting recognition must call the formal endpoint once");
    assert((await page.inputValue("#recognizedAnswerText")) === "-3", "recognized handwriting text must be shown");
    assert(!(await page.isChecked("#recognitionConfirmed")), "recognition must start unconfirmed");

    await page.check("#recognitionConfirmed");
    await page.fill("#recognizedAnswerText", "-4");
    assert(!(await page.isChecked("#recognitionConfirmed")), "editing recognized text must invalidate confirmation");
    await page.click("#childSubmitBtn");
    await page.waitForTimeout(150);
    assert(requests.submissions.length === 0, "edited but unconfirmed handwriting must not submit");

    await page.check("#recognitionConfirmed");
    await page.click("#childSubmitBtn");
    await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
    assert(requests.submissions.length === 1, "confirmed handwriting must submit exactly once");
    const submission = requests.submissions[0];
    assert(submission.input_evidence?.input_mode === "handwriting", "submission must preserve handwriting input mode");
    assert(submission.input_evidence?.child_confirmed === true, "submission must freeze child confirmation");
    assert(submission.input_evidence?.child_confirmed_text === "-4", "submission must use the corrected confirmed text");
    assert(String(submission.handwriting_image_data_url || "").startsWith("data:image/"), "submission must bind original handwriting media");
    await assertPageChildSafe(page, "handwriting analyzing surface");
    await page.close();
  });

  await check("unconfirmed recognition cannot be lost by switching modes", async () => {
    handwritingVariant = "clean";
    handwritingDelayMs = 0;
    handwritingFailureMessage = "";
    const page = await openScenario(browser, currentStepPayload());
    await page.fill("#childAnswerRaw", "键盘草稿");
    await selectMode(page, "handwriting");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await waitForRecognitionPanel(page);
    await page.click('[data-answer-input-mode="typed"]');
    assert(await page.locator("#recognitionConfirmPanel").isVisible(), "mode switch must not discard an unconfirmed result");
    assert((await page.inputValue("#recognizedAnswerText")) === "-3", "unconfirmed recognized text must remain visible");
    await page.click("#cancelRecognitionBtn");
    assert(await page.locator("#childAnswerRaw").isVisible(), "explicit cancel must return to keyboard mode");
    assert((await page.inputValue("#childAnswerRaw")) === "键盘草稿", "explicit cancel must restore the prior keyboard draft");
    await page.close();
  });

  await check("handwriting recognition locks the source and hides internal failures", async () => {
    handwritingVariant = "clean";
    handwritingDelayMs = 180;
    handwritingFailureMessage = "";
    let page = await openScenario(browser, currentStepPayload());
    await selectMode(page, "handwriting");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await page.waitForFunction(() => document.querySelector("#handwritingCanvas")?.getAttribute("aria-busy") === "true");
    assert(await page.isDisabled("#undoHandwritingBtn"), "undo must be locked while recognition is running");
    assert(await page.isDisabled("#clearHandwritingBtn"), "clear must be locked while recognition is running");
    assert(await page.isDisabled('[data-answer-input-mode="typed"]'), "mode switching must be locked while recognition is running");
    await waitForRecognitionPanel(page);
    await page.close();

    handwritingDelayMs = 0;
    handwritingFailureMessage = "provider openai model gpt-5.5 job_id JOB-private-42";
    page = await openScenario(browser, currentStepPayload());
    await selectMode(page, "handwriting");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await page.waitForFunction(() => document.querySelector("#handwritingStatus")?.textContent?.includes("手写识别暂时没有完成"));
    const status = await page.locator("#handwritingStatus").innerText();
    assert(!status.includes("provider") && !status.includes("JOB-private-42"), `internal recognition error leaked: ${status}`);
    await assertPageChildSafe(page, "handwriting failure surface");
    await page.close();
    handwritingFailureMessage = "";
  });

  await check("formula input handwriting projects the confirmed correction into structured evidence", async () => {
    handwritingVariant = "clean";
    const page = await openScenario(browser, currentStepPayload({
      current_step: {
        prompt: "用一个算式表示：一个数加 3 等于 0。",
        prompt_segments: [
          { type: "text", text: "用一个算式表示：一个数加 3 等于 0。" },
        ],
        answer_input_mode: "interaction",
        allowed_response_modes: ["interaction", "handwriting", "stuck"],
        interaction_schema: {
          schema_version: "2026-07-17.interaction.v1",
          type: "formula_input",
          title: "写出算式",
          formula_label: "算式",
          placeholder: "例如 x+3=0",
          allow_explanation: false,
          requires_explanation: false,
        },
      },
    }));
    await selectMode(page, "handwriting");
    assert(await page.locator("#handwritingInputPanel").isVisible(), "formula input must expose handwriting mode");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await waitForRecognitionPanel(page);
    assert(requests.handwriting.length === 1, "formula handwriting must call recognition exactly once");

    await page.check("#recognitionConfirmed");
    assert((await page.inputValue("[data-interaction-formula]")) === "-3", "initial confirmation must project into the canonical formula control");
    await page.fill("#recognizedAnswerText", "x=-3");
    assert(!(await page.isChecked("#recognitionConfirmed")), "editing a confirmed formula recognition must invalidate confirmation");
    await page.click("#childSubmitBtn");
    await page.waitForTimeout(150);
    assert(requests.submissions.length === 0, "edited but unconfirmed formula handwriting must not submit");

    await page.check("#recognitionConfirmed");
    assert((await page.inputValue("[data-interaction-formula]")) === "x=-3", "corrected confirmation must replace the canonical formula value");
    await page.click("#childSubmitBtn");
    await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
    assert(requests.submissions.length === 1, "confirmed formula handwriting must submit exactly once");
    const submission = requests.submissions[0];
    const formula = submission.interaction_response?.formula;
    const formulaValue = typeof formula === "string" ? formula : formula?.value;
    assert(formulaValue === "x=-3", `structured formula must use the corrected confirmed value: ${JSON.stringify(formula)}`);
    assert(submission.input_evidence?.input_mode === "handwriting", "formula submission must retain handwriting input mode");
    assert(submission.input_evidence?.recognition_handle === "RH-private-handwriting-1", "formula submission must retain the opaque recognition handle");
    assert(submission.input_evidence?.child_confirmed_text === "x=-3", "formula submission must freeze the corrected confirmed text");
    assert(
      submission.handwriting_image_data_url === requests.handwriting[0].handwriting_image_data_url,
      "formula submission must bind the exact original handwriting media",
    );
    await assertPageChildSafe(page, "formula handwriting analyzing surface");
    await page.close();
  });

  await check("voice recognition requires confirmation with stubbed browser APIs", async () => {
    const page = await openScenario(browser, currentStepPayload(), { voiceStubs: true });
    await selectMode(page, "voice");
    assert(await page.locator("#voiceInputPanel").isVisible(), "voice panel must open");
    await page.click("#voiceRecordBtn");
    await page.waitForTimeout(100);
    if (!(await page.locator("#recognitionConfirmPanel").isVisible())) {
      await page.click("#voiceRecordBtn");
    }
    await waitForRecognitionPanel(page);
    assert(requests.voice.length === 1, "voice recognition must call the formal endpoint once");
    assert((await page.inputValue("#recognizedAnswerText")) === "-3", "recognized voice text must be shown");
    assert(!(await page.isChecked("#recognitionConfirmed")), "voice recognition must start unconfirmed");
    await page.check("#recognitionConfirmed");
    await page.click("#childSubmitBtn");
    await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
    assert(requests.submissions.length === 1, "confirmed voice answer must submit exactly once");
    const submission = requests.submissions[0];
    assert(submission.input_evidence?.input_mode === "voice", "submission must preserve voice input mode");
    assert(submission.input_evidence?.child_confirmed_text === "-3", "submission must freeze confirmed voice text");
    assert(String(submission.voice_audio_data_url || "").startsWith("data:audio/"), "submission must bind recorded voice media");
    await assertPageChildSafe(page, "voice analyzing surface");
    await page.close();
  });

  await check("unresolved critical-symbol ambiguity blocks submit", async () => {
    handwritingVariant = "ambiguous";
    const page = await openScenario(browser, currentStepPayload());
    await selectMode(page, "handwriting");
    await drawHandwriting(page);
    await page.click("#recognizeHandwritingBtn");
    await waitForRecognitionPanel(page);
    const uncertainty = await page.locator("#recognitionUncertainty").innerText();
    assert(uncertainty.includes("负号") || uncertainty.includes("-"), `critical uncertainty must be child-visible: ${uncertainty}`);
    if (await page.locator("#recognitionConfirmed").isEnabled()) {
      await page.check("#recognitionConfirmed");
    }
    await page.click("#childSubmitBtn");
    await page.waitForTimeout(150);
    assert(requests.submissions.length === 0, "unresolved critical-symbol ambiguity must not submit");
    await assertPageChildSafe(page, "ambiguity-blocked child surface");
    await page.close();
  });

  await check("group progress is useful and child-safe", async () => {
    const page = await openScenario(browser, currentStepPayload({
      current_step: {
        group_progress: { current: 2, maximum: 5 },
      },
    }));
    const progress = await page.locator("#childProgressText").innerText();
    assert(progress.includes("2") && progress.includes("5"), `group progress must show current and maximum without internals: ${progress}`);
    await assertPageChildSafe(page, "group progress child surface");
    await page.close();
  });

  await check("first answer advances directly and second answer starts group analysis", async () => {
    const second = currentStepPayload({
      current_step: {
        step_handle: "child-safe-practice-step-2",
        position: 2,
        prompt: "比较 -3 和 -1 的大小，并说明数轴依据。",
        prompt_segments: [
          { type: "text", text: "比较 -3 和 -1 的大小，并说明数轴依据。" },
        ],
        group_progress: { current: 2, maximum: 5 },
      },
    });
    const page = await openScenario(
      browser,
      currentStepPayload({ current_step: { group_progress: { current: 1, maximum: 5 } } }),
      { submitResponses: [second, analyzingPayload()] },
    );
    await page.fill("#childAnswerRaw", "-3 在 0 左边。" );
    await page.click("#childSubmitBtn");
    try {
      await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "current_step");
    } catch (error) {
      const actual = await page.evaluate(() => window.ChildLearningShell?.currentState());
      const body = await page.locator("body").innerText();
      throw new Error(`first transition did not reach current_step; actual=${actual}; body=${body}; cause=${error.message}`);
    }
    assert((await page.locator("#childTaskContent").innerText()).includes("比较 -3 和 -1"), "first answer must advance directly to the second question");
    assert(!(await page.locator("body").innerText()).includes("本题得分"), "no per-question score may interrupt the first transition");
    await page.fill("#childAnswerRaw", "-3<-1，因为 -3 在 -1 左边。" );
    await page.click("#childSubmitBtn");
    try {
      await page.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
    } catch (error) {
      const actual = await page.evaluate(() => window.ChildLearningShell?.currentState());
      const body = await page.locator("body").innerText();
      throw new Error(`second transition did not reach analyzing_pending; actual=${actual}; body=${body}; cause=${error.message}`);
    }
    assert(requests.submissions.length === 2, "two consecutive answers must be saved before group analysis");
    const body = await page.locator("body").innerText();
    assert(body.includes("这一组") || body.includes("整组"), `group analysis copy must describe the group: ${body}`);
    await assertPageChildSafe(page, "group analysis surface");
    await page.close();
  });
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

if (failures.length) {
  throw new Error(`browser practice multimodal contract failed (${failures.length})\n${failures.join("\n")}`);
}

console.log("browser practice multimodal child-safe contract passed");
