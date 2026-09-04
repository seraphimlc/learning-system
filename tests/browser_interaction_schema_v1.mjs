#!/usr/bin/env node
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appRoot = path.join(root, "app", "local_learning_system");
const missingTickVisual = {
  scene_type: "number_line",
  alt_text: "一条只标出负一、零和一，等待补出中间刻度的数轴。",
  long_description: "相邻已知数之间还各缺一个等距刻度。请在纸上补完整，并拍照提交。",
  scene: {
    axis: { min: -1, max: 1, step: 0.5, origin: 0, direction: "right" },
    ticks: [
      { value: -1, label: "-1" },
      { value: 0, label: "0" },
      { value: 1, label: "1" },
    ],
    points: [],
  },
  interaction_contract: {
    operation: "complete_missing_ticks",
    required_interaction_capabilities: ["construction_interaction"],
    response_capture: "paper_photo",
    visible_entity_ids_for_visual: ["tick:-1", "tick:0", "tick:1"],
    required_child_produced_entity_ids: ["tick:-0.5", "tick:0.5"],
    answer_hidden: true,
  },
};
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

function textSegment(text) {
  return { type: "text", text: String(text || "") };
}

function inlineRendering(text) {
  const value = String(text || "");
  return { text: value, segments: [textSegment(value)] };
}

function interactionRendering(schema) {
  return {
    title: inlineRendering(schema.title || "作答"),
    explanation_label: inlineRendering(schema.explanation_label || "补充说明"),
    formula_label: inlineRendering(schema.formula_label || ""),
    fields: (schema.fields || []).map((field) => ({
      id: String(field.id),
      label: inlineRendering(field.label),
      prefix: inlineRendering(field.prefix || ""),
      suffix: inlineRendering(field.suffix || ""),
    })),
    choices: (schema.choices || []).map((choice) => ({
      id: String(choice.id),
      label: inlineRendering(choice.label),
    })),
  };
}

function currentStep(interactionSchema, prompt = "完成这一小步。") {
  return {
    schema_version: "3.0.0-daily-flow",
    child_state: "current_step",
    ready_for_new_knowledge: false,
    message: {},
    current_step: {
      step_handle: `step-${interactionSchema.type}`,
      position: 1,
      kind_label: "小互动",
      topic_label: "数感与估算",
      prompt,
      answer_input_mode: "interaction",
      allowed_response_modes: ["interaction", "text", "stuck"],
      upload_enabled: false,
      stuck_enabled: true,
      state: "selected",
      support: interactionSchema.requires_explanation
        ? { hint: "按题目要求完成，再写一句理由。" }
        : {},
      prompt_format: "2026-07-17.child-plain-text.v1",
      prompt_segments: [textSegment(prompt)],
      interaction_schema: interactionSchema,
      interaction_rendering: interactionRendering(interactionSchema),
    },
  };
}

let payload = currentStep({
  schema_version: "2026-07-13.interaction.v1",
  type: "fill_blank",
  title: "补完整关键量",
  fields: [
    { id: "increase", label: "多出的影响", placeholder: "如 20" },
    { id: "decrease", label: "少掉的影响", placeholder: "如 4" },
    { id: "net", label: "净变化", placeholder: "如 16" },
  ],
  allow_explanation: true,
  requires_explanation: true,
  explanation_label: "为什么这样填",
});
const submitBodies = [];

const server = http.createServer((req, res) => {
  const url = new URL(req.url, baseUrl);
  if (url.pathname === "/api/child-bootstrap") {
    json(res, 200, payload);
    return;
  }
  if (url.pathname === "/api/current-step/submit") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk.toString(); });
    req.on("end", () => {
      submitBodies.push(JSON.parse(raw || "{}"));
      json(res, 200, {
        schema_version: "3.0.0-daily-flow",
        child_state: "analyzing",
        ready_for_new_knowledge: false,
        message: { title: "正在看你的步骤", body: "答案已经保存。" },
      });
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

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));

const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});

try {
  const fillPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await fillPage.goto(baseUrl, { waitUntil: "networkidle" });
  await fillPage.waitForSelector("[data-interaction-kind='fill_blank']");
  await fillPage.fill("[data-interaction-field='increase']", "20");
  await fillPage.fill("[data-interaction-field='decrease']", "4");
  await fillPage.fill("[data-interaction-field='net']", "16");
  await fillPage.fill("#childAnswerRaw", "20-4=16，所以比1000大约大16。");
  await fillPage.click("#childSubmitBtn");
  await fillPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  const fillAnswer = submitBodies.at(-1)?.answer_text || "";
  const fillResponse = submitBodies.at(-1)?.interaction_response || {};
  assert(fillAnswer.includes("结构化作答：填空"), "Fill blank submit must identify the interaction type");
  assert(fillAnswer.includes("多出的影响：20"), "Fill blank submit must include the first field");
  assert(fillAnswer.includes("少掉的影响：4"), "Fill blank submit must include the second field");
  assert(fillAnswer.includes("净变化：16"), "Fill blank submit must include the net field");
  assert(fillAnswer.includes("补充说明：20-4=16"), "Fill blank submit must preserve explanation text");
  assert(fillResponse.type === "fill_blank", "Fill blank submit must include structured response type");
  assert(fillResponse.values?.increase === "20", "Fill blank structured response must include first field by id");
  assert(fillResponse.values?.decrease === "4", "Fill blank structured response must include second field by id");
  assert(fillResponse.values?.net === "16", "Fill blank structured response must include net field by id");
  assert(fillResponse.explanation_text === "20-4=16，所以比1000大约大16。", "Fill blank structured response must preserve explanation separately");
  await fillPage.close();

  payload = currentStep({
    schema_version: "2026-07-13.interaction.v1",
    type: "single_choice",
    title: "选更稳的方法",
    choices: [
      { id: "a", label: "只四舍五入后当成精确值" },
      { id: "b", label: "以基准乘积为起点，再看误差方向" },
    ],
    allow_explanation: true,
    requires_explanation: true,
  }, "哪种估算方法更稳？");
  const choicePage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await choicePage.goto(baseUrl, { waitUntil: "networkidle" });
  await choicePage.waitForSelector("[data-interaction-kind='single_choice']");
  await choicePage.click("[data-interaction-choice='b']");
  await choicePage.fill("#childAnswerRaw", "因为它保留了偏差方向。");
  await choicePage.click("#childSubmitBtn");
  await choicePage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  const choiceAnswer = submitBodies.at(-1)?.answer_text || "";
  const choiceResponse = submitBodies.at(-1)?.interaction_response || {};
  assert(choiceAnswer.includes("结构化作答：单选"), "Choice submit must identify the interaction type");
  assert(choiceAnswer.includes("选择：以基准乘积为起点，再看误差方向"), "Choice submit must include selected label");
  assert(choiceAnswer.includes("补充说明：因为它保留了偏差方向。"), "Choice submit must preserve explanation");
  assert(choiceResponse.type === "single_choice", "Choice submit must include structured response type");
  assert(choiceResponse.selected_choices?.[0] === "b", "Choice structured response must include selected choice id");
  await choicePage.close();

  payload = currentStep({
    schema_version: "2026-07-13.interaction.v1",
    type: "formula_input",
    title: "写出第一步算式",
    formula_label: "第一步算式",
    placeholder: "如 50×0.4-0.2×20",
    allow_explanation: false,
  }, "写出估算净变化的算式。");
  const formulaPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await formulaPage.goto(baseUrl, { waitUntil: "networkidle" });
  await formulaPage.waitForSelector("[data-interaction-kind='formula_input']");
  await formulaPage.fill("[data-interaction-formula]", "50×0.4-0.2×20");
  await formulaPage.click("#childSubmitBtn");
  await formulaPage.waitForFunction(() => window.ChildLearningShell?.currentState() === "analyzing_pending");
  const formulaAnswer = submitBodies.at(-1)?.answer_text || "";
  const formulaResponse = submitBodies.at(-1)?.interaction_response || {};
  assert(formulaAnswer.includes("结构化作答：公式输入"), "Formula submit must identify the interaction type");
  assert(formulaAnswer.includes("第一步算式：50×0.4-0.2×20"), "Formula submit must include the formula");
  assert(formulaResponse.type === "formula_input", "Formula submit must include structured response type");
  assert(formulaResponse.formula === "50×0.4-0.2×20", "Formula structured response must include raw formula");
  await formulaPage.close();

  payload = currentStep({
    schema_version: "2026-07-13.interaction.v1",
    type: "formula_input",
    title: "写出结果",
    formula_label: "答案",
    placeholder: "写下答案",
    allow_explanation: true,
    requires_explanation: false,
  }, "计算 38+47。");
  const answerOnlyPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await answerOnlyPage.goto(baseUrl, { waitUntil: "networkidle" });
  await answerOnlyPage.waitForSelector("[data-interaction-kind='formula_input']");
  const answerOnlyUi = await answerOnlyPage.evaluate(() => ({
    formulaVisible: Boolean(document.querySelector("[data-interaction-formula]")?.offsetParent),
    explanationHidden: document.querySelector("#childAnswerRaw")?.hidden,
    explanationLabelHidden: document.querySelector('label[for="childAnswerRaw"]')?.hidden,
    optionalExplanationVisible: document.body.innerText.includes("补充说明（可选）")
      || document.body.innerText.includes("可以补一句理由或检查方法"),
  }));
  assert(answerOnlyUi.formulaVisible, "Answer-only formula input must remain visible");
  assert(answerOnlyUi.explanationHidden, "Answer-only formula input must hide supplemental explanation textarea");
  assert(answerOnlyUi.explanationLabelHidden, "Answer-only formula input must hide supplemental explanation label");
  assert(!answerOnlyUi.optionalExplanationVisible, "Answer-only formula input must not induce optional explanation");
  await answerOnlyPage.close();

  payload = currentStep({
    schema_version: "2026-07-13.interaction.v1",
    type: "short_text",
    title: "纸面作答",
    allow_explanation: true,
    requires_explanation: false,
  }, "请在纸上完成构造并拍照提交。");
  payload.current_step.answer_input_mode = "photo";
  payload.current_step.allowed_response_modes = ["photo", "stuck"];
  payload.current_step.upload_enabled = true;
  payload.current_step.question_visual = missingTickVisual;
  const photoPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await photoPage.goto(baseUrl, { waitUntil: "networkidle" });
  await photoPage.waitForSelector("#childAttemptForm:not([hidden])");
  const photoUi = await photoPage.evaluate(() => ({
    label: document.querySelector("#childAnswerPhotoLabel")?.textContent?.trim(),
    hint: document.querySelector("#childAnswerPhotoHint")?.textContent?.trim(),
    required: document.querySelector("#childAnswerPhoto")?.required,
    ariaRequired: document.querySelector("#childAnswerPhoto")?.getAttribute("aria-required"),
    textHidden: document.querySelector("#childAnswerRaw")?.hidden,
    modePanelHidden: document.querySelector("#answerInputModePanel")?.hidden,
  }));
  assert(photoUi.label === "拍纸面答案（必答）", "Photo-primary answer must be labeled required");
  assert(photoUi.hint.startsWith("必答："), "Photo-primary hint must not call the photo optional");
  assert(photoUi.required && photoUi.ariaRequired === "true", "Photo-primary file input must expose required semantics");
  assert(photoUi.textHidden && photoUi.modePanelHidden, "Photo-primary answer must hide text and alternate input modes");
  const submitCountBeforePhoto = submitBodies.length;
  await photoPage.click("#childSubmitBtn");
  await photoPage.waitForSelector("#childAttemptError:not([hidden])");
  const photoError = await photoPage.locator("#childAttemptError").innerText();
  assert(photoError.includes("请先拍下这道题"), "Photo-primary empty submit must show a child-facing required error");
  assert(submitBodies.length === submitCountBeforePhoto, "Photo-primary empty submit must not reach the API");
  const renderedTickIds = await photoPage.locator("[data-qv-tick-value]").evaluateAll(
    (ticks) => ticks.map((tick) => `tick:${tick.getAttribute("data-qv-tick-value")}`),
  );
  assert(
    JSON.stringify(renderedTickIds)
      === JSON.stringify(missingTickVisual.interaction_contract.visible_entity_ids_for_visual),
    "Missing-tick page must render exactly the signed initial tick set",
  );
  const requiredTickIds = new Set(
    missingTickVisual.interaction_contract.required_child_produced_entity_ids,
  );
  assert(
    renderedTickIds.every((entityId) => !requiredTickIds.has(entityId)),
    "Missing-tick page precompleted a child-produced tick",
  );
  await photoPage.setInputFiles("#childAnswerPhoto", {
    name: "number-line-answer.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlX8f8AAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await photoPage.waitForSelector("#childPhotoPreview:not([hidden])");
  const uploadedPhotoUi = await photoPage.evaluate(() => ({
    errorHidden: document.querySelector("#childAttemptError")?.hidden,
    previewSrc: document.querySelector("#childPhotoThumb")?.getAttribute("src") || "",
    photoName: document.querySelector("#childPhotoName")?.textContent?.trim() || "",
    ariaInvalid: document.querySelector("#childAnswerPhoto")?.getAttribute("aria-invalid"),
    noOverflow: document.documentElement.scrollWidth <= window.innerWidth,
  }));
  assert(uploadedPhotoUi.errorHidden, "Valid photo must clear the required-answer error");
  assert(uploadedPhotoUi.previewSrc.startsWith("data:image/png;base64,"), "Valid photo must show a preview");
  assert(uploadedPhotoUi.photoName === "number-line-answer.png", "Valid photo name must remain visible");
  assert(uploadedPhotoUi.ariaInvalid === "false", "Valid photo must clear aria-invalid");
  assert(uploadedPhotoUi.noOverflow, "Missing-tick photo flow must fit a 390px viewport");
  await photoPage.click("#childSubmitBtn");
  await photoPage.waitForFunction(
    () => window.ChildLearningShell?.currentState() === "analyzing_pending",
  );
  const photoSubmit = submitBodies.at(-1) || {};
  assert(
    photoSubmit.answer_photo_data_url?.startsWith("data:image/png;base64,"),
    "Valid photo must reach the submit API",
  );
  assert(
    photoSubmit.answer_photo_name === "number-line-answer.png",
    "Submitted photo must retain its file name",
  );
  await photoPage.close();

  payload = currentStep({
    schema_version: "2026-07-13.interaction.v1",
    type: "short_text",
    title: "我的答案",
    allow_explanation: true,
    requires_explanation: false,
  }, "写出答案；需要时可以补拍纸面过程。");
  payload.current_step.answer_input_mode = "text_photo";
  payload.current_step.allowed_response_modes = ["text", "photo", "text_photo", "stuck"];
  payload.current_step.upload_enabled = true;
  const optionalPhotoPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await optionalPhotoPage.goto(baseUrl, { waitUntil: "networkidle" });
  await optionalPhotoPage.waitForSelector("#childAttemptForm:not([hidden])");
  const optionalPhotoUi = await optionalPhotoPage.evaluate(() => ({
    label: document.querySelector("#childAnswerPhotoLabel")?.textContent?.trim(),
    hint: document.querySelector("#childAnswerPhotoHint")?.textContent?.trim(),
    required: document.querySelector("#childAnswerPhoto")?.required,
    ariaRequired: document.querySelector("#childAnswerPhoto")?.getAttribute("aria-required"),
    textHidden: document.querySelector("#childAnswerRaw")?.hidden,
  }));
  assert(optionalPhotoUi.label === "需要时拍纸面答案", "Optional photo must use natural supporting copy");
  assert(optionalPhotoUi.hint.startsWith("可选："), "Optional photo must remain explicitly optional");
  assert(!optionalPhotoUi.required && optionalPhotoUi.ariaRequired === "false", "Optional photo must not expose required semantics");
  assert(!optionalPhotoUi.textHidden, "Optional photo flow must keep the primary text answer visible");
  await optionalPhotoPage.close();

  process.stdout.write(JSON.stringify({
    status: "PASS",
    viewport_width_px: 390,
    missing_tick_visible_entity_ids: renderedTickIds,
    missing_tick_required_child_produced_entity_ids: [
      ...missingTickVisual.interaction_contract.required_child_produced_entity_ids,
    ],
    valid_photo_preview: uploadedPhotoUi.previewSrc.startsWith("data:image/png;base64,"),
    valid_photo_reached_api: photoSubmit.answer_photo_name === "number-line-answer.png",
    required_error_recovered: uploadedPhotoUi.errorHidden,
    no_horizontal_overflow: uploadedPhotoUi.noOverflow,
  }));
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
