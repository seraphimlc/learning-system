import fs from "node:fs";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function arg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const indexPath = arg("--index");
const appPath = arg("--app");
const rendererPath = arg("--renderer");
const stylePath = arg("--style");
const fixturePath = arg("--fixture");
assert(indexPath && appPath && rendererPath && stylePath && fixturePath, "index, app, renderer, style and fixture are required");

const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const indexHtml = fs.readFileSync(indexPath, "utf8")
  .replace(/<script[^>]*src="[^"]+"[^>]*><\/script>/g, "")
  .replace(/<link[^>]*rel="stylesheet"[^>]*>/g, "")
  .replace("<head>", '<head><base href="http://child.test/">');
const browser = await chromium.launch({ headless: true });
const report = { cases: {}, group_progress: {}, required_recovery: {}, unavailable: {}, no_network: true, unexpected_network: [] };

async function mountCase(payload, viewport, { zoom = 1, unavailable = false } = {}) {
  const page = await browser.newPage({ viewport });
  let submitPosts = 0;
  const unexpectedRequests = [];
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error?.stack || error)));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/knowledge-map") {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ message: "not enabled" }) });
      return;
    }
    if (url.pathname === "/api/child-bootstrap") {
      await route.fulfill({
        status: unavailable ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(unavailable ? fixture.invalid_runtime_response : payload),
      });
      return;
    }
    if (url.pathname === "/api/current-step/submit") {
      submitPosts += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ child_state: "analyzing_pending" }) });
      return;
    }
    unexpectedRequests.push(route.request().url());
    await route.abort();
  });
  await page.setContent(indexHtml, { waitUntil: "domcontentloaded" });
  await page.addStyleTag({ path: stylePath });
  await page.addScriptTag({ content: `window.KnowledgeViews={initialize(){},destroy(){},hide(){},show(){},setProjection(){}};` });
  await page.addScriptTag({ path: rendererPath });
  await page.addScriptTag({ path: appPath });
  if (zoom !== 1) await page.evaluate((value) => { document.documentElement.style.zoom = String(value); }, zoom);
  try {
    await page.waitForFunction((isUnavailable) => {
      if (isUnavailable) return !document.getElementById("childErrorPanel").hidden;
      return document.getElementById("dbStatus")?.textContent === "准备好了";
    }, unavailable);
  } catch (error) {
    const state = await page.evaluate(() => ({
      dbStatus: document.getElementById("dbStatus")?.textContent || "",
      heading: document.getElementById("childHeading")?.textContent || "",
      errorBody: document.getElementById("childErrorBody")?.textContent || "",
    }));
    throw new Error(`${error.message}\npageErrors=${JSON.stringify(pageErrors)}\nstate=${JSON.stringify(state)}`);
  }
  return { page, submitPosts: () => submitPosts, unexpectedRequests };
}

try {
  for (const testCase of fixture.valid_cases) {
    report.cases[testCase.name] = {};
    for (const target of [
      { key: "1280", viewport: { width: 1280, height: 800 }, zoom: 1 },
      { key: "390", viewport: { width: 390, height: 844 }, zoom: 1 },
      { key: "200pct", viewport: { width: 640, height: 844 }, zoom: 2 },
    ]) {
      const mounted = await mountCase(testCase.bootstrap, target.viewport, { zoom: target.zoom });
      const result = await mounted.page.evaluate(({ expected, sourcePrompt }) => {
        const prompt = document.querySelector("[data-child-prompt]");
        const interaction = document.getElementById("interactionAnswerPanel");
        const answer = document.getElementById("childAnswerRaw");
        const powers = [...document.querySelectorAll(".math-power")];
        const primary = interaction.querySelector("input");
        function copyRange(range) {
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          const captured = { fired: false, prevented: false, text: "" };
          document.addEventListener("copy", (event) => {
            captured.fired = true;
            captured.prevented = event.defaultPrevented;
            captured.text = event.clipboardData?.getData("text/plain") || "";
          }, { once: true });
          const selectionText = selection.toString();
          const commandResult = document.execCommand("copy");
          selection.removeAllRanges();
          return { ...captured, selectionText, commandResult };
        }
        const powerCopies = powers.map((element) => {
          const range = document.createRange();
          range.selectNodeContents(element);
          return {
            source: element.dataset.linearSource || "",
            ...copyRange(range),
          };
        });
        const promptRange = document.createRange();
        promptRange.selectNodeContents(prompt);
        const promptCopy = copyRange(promptRange);
        const walker = document.createTreeWalker(prompt, NodeFilter.SHOW_TEXT);
        let plainNode = null;
        while (walker.nextNode()) {
          if (walker.currentNode.parentElement?.closest(".math-power")) continue;
          if (!walker.currentNode.nodeValue?.trim()) continue;
          plainNode = walker.currentNode;
          break;
        }
        let plainCopy = null;
        if (plainNode) {
          const plainRange = document.createRange();
          plainRange.setStart(plainNode, 0);
          plainRange.setEnd(plainNode, Math.min(2, plainNode.nodeValue.length));
          plainCopy = copyRange(plainRange);
        }
        return {
          prompt_text: prompt?.textContent || "",
          source_prompt: sourcePrompt,
          prompt_power_count: prompt?.querySelectorAll(".math-power").length || 0,
          prompt_lines: (prompt?.textContent || "").split("\n").filter((line) => line.trim()),
          white_space: prompt ? getComputedStyle(prompt).whiteSpace : "",
          powers: powers.map((element) => ({
            label: element.getAttribute("aria-label"),
            source: element.getAttribute("data-linear-source"),
            text: element.textContent,
            display: getComputedStyle(element).display,
            base_display: getComputedStyle(element.querySelector(":scope > span")).display,
          })),
          power_copies: powerCopies,
          prompt_copy: promptCopy,
          plain_copy: plainCopy,
          fieldset_count: interaction.querySelectorAll("fieldset").length,
          legend_texts: [...interaction.querySelectorAll("legend")].map((element) => element.textContent.trim()),
          primary_before_explanation: !primary || Boolean(primary.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING),
          primary_top: primary?.getBoundingClientRect().top ?? 0,
          explanation_top: answer.hidden ? null : answer.getBoundingClientRect().top,
          no_horizontal_scroll: document.documentElement.scrollWidth <= window.innerWidth,
          raw_duplicates: expected.absent_text.filter((text) => (prompt?.textContent || "").includes(text)),
          control_kind: interaction.querySelector("[data-interaction-kind]")?.dataset.interactionKind || "short_text",
          answer_visible: !answer.hidden,
        };
      }, {
        expected: testCase.expect,
        sourcePrompt: testCase.bootstrap.current_step.prompt,
      });
      assert(result.white_space === "pre-line", `${testCase.name}/${target.key}: prompt white-space`);
      assert(result.no_horizontal_scroll, `${testCase.name}/${target.key}: horizontal overflow`);
      assert(result.primary_before_explanation, `${testCase.name}/${target.key}: DOM focus order`);
      assert(!result.answer_visible || !result.primary_top || result.primary_top <= result.explanation_top, `${testCase.name}/${target.key}: visual control order`);
      const expectsTextAnswer = testCase.expect.control_kind === "short_text"
        || Boolean(testCase.expect.required_message);
      assert(result.answer_visible === expectsTextAnswer, `${testCase.name}/${target.key}: explanation visibility contract`);
      assert(result.raw_duplicates.length === 0, `${testCase.name}/${target.key}: duplicated option source`);
      assert(testCase.expect.required_lines.every((line) => result.prompt_lines.includes(line)), `${testCase.name}/${target.key}: line grouping`);
      assert(result.powers.every((power) => power.label && power.source), `${testCase.name}/${target.key}: exponent semantics`);
      assert(result.powers.every((power) => power.display === "inline" && power.base_display === "inline"), `${testCase.name}/${target.key}: exponent must remain inline inside question copy`);
      assert(result.power_copies.every((copy) => copy.fired && copy.prevented && copy.commandResult && copy.text === copy.source), `${testCase.name}/${target.key}: exponent clipboard caret source`);
      if (result.prompt_power_count) {
        assert(result.prompt_copy.fired && result.prompt_copy.prevented && result.prompt_copy.commandResult && result.prompt_copy.text === result.source_prompt, `${testCase.name}/${target.key}: prompt clipboard serialization`);
      } else {
        assert(result.prompt_copy.fired && !result.prompt_copy.prevented, `${testCase.name}/${target.key}: non-math prompt copy was intercepted`);
      }
      assert(!result.plain_copy || (result.plain_copy.fired && !result.plain_copy.prevented), `${testCase.name}/${target.key}: plain selection copy was intercepted`);
      if (["single_choice", "multi_choice", "fill_blank"].includes(testCase.expect.control_kind)) {
        assert(result.fieldset_count === 1 && result.legend_texts[0], `${testCase.name}/${target.key}: named control group`);
      }
      assert(result.control_kind === testCase.expect.control_kind, `${testCase.name}/${target.key}: control kind`);
      report.cases[testCase.name][target.key] = result;
      report.no_network = report.no_network && mounted.unexpectedRequests.length === 0;
      report.unexpected_network.push(...mounted.unexpectedRequests);
      await mounted.page.close();
    }
  }

  const required = fixture.valid_cases.find((item) => item.name === fixture.required_explanation_case);
  const oneQuestionGroup = structuredClone(required.bootstrap);
  oneQuestionGroup.current_step.group_progress = { current: 1, maximum: 1 };
  const mountedOneQuestionGroup = await mountCase(oneQuestionGroup, { width: 390, height: 844 });
  report.group_progress = await mountedOneQuestionGroup.page.evaluate(() => ({
    progress: document.getElementById("childProgressText").textContent,
    pending: document.getElementById("childPendingText").textContent,
  }));
  assert(report.group_progress.progress === "第 1 题 · 最多 1 题", "one-question group progress copy is wrong");
  assert(report.group_progress.pending === "这题做完就看解析", "one-question group pending copy is contradictory");
  await mountedOneQuestionGroup.page.close();

  const boundedTwoQuestionGroup = structuredClone(required.bootstrap);
  boundedTwoQuestionGroup.current_step.group_progress = { current: 1, maximum: 2 };
  const mountedBoundedTwoQuestionGroup = await mountCase(boundedTwoQuestionGroup, { width: 390, height: 844 });
  report.group_progress.bounded_pending = await mountedBoundedTwoQuestionGroup.page.evaluate(
    () => document.getElementById("childPendingText").textContent,
  );
  assert(
    report.group_progress.bounded_pending === "做完这题，再决定继续还是看解析",
    "bounded group copy must not promise a question that may not exist",
  );
  await mountedBoundedTwoQuestionGroup.page.close();

  const mountedRequired = await mountCase(required.bootstrap, { width: 390, height: 844 });
  await mountedRequired.page.locator("[data-interaction-choice]").first().check();
  await mountedRequired.page.locator("#childSubmitBtn").click();
  report.required_recovery = await mountedRequired.page.evaluate(() => ({
    focused: document.activeElement?.id || "",
    required: document.getElementById("childAnswerRaw").required,
    aria_required: document.getElementById("childAnswerRaw").getAttribute("aria-required"),
    aria_invalid: document.getElementById("childAnswerRaw").getAttribute("aria-invalid"),
    message: document.getElementById("childAttemptError").textContent,
    alert_hidden: document.getElementById("childAttemptError").hidden,
  }));
  report.required_recovery.submit_posts = mountedRequired.submitPosts();
  assert(report.required_recovery.submit_posts === 0, "required explanation issued POST");
  assert(report.required_recovery.focused === "childAnswerRaw", "required explanation did not focus textarea");
  assert(report.required_recovery.required && report.required_recovery.aria_required === "true", "required semantics missing");
  assert(report.required_recovery.aria_invalid === "true", "invalid semantics missing");
  assert(report.required_recovery.message === required.expect.required_message && !report.required_recovery.alert_hidden, "exact recovery announcement missing");
  await mountedRequired.page.close();

  const mountedUnavailable = await mountCase(null, { width: 390, height: 844 }, { unavailable: true });
  report.unavailable = await mountedUnavailable.page.evaluate(() => ({
    heading: document.getElementById("childHeading").textContent,
    body: document.getElementById("childErrorBody").textContent,
    pending: document.getElementById("childPendingText").textContent,
    form_hidden: document.getElementById("childAttemptForm").hidden,
    task_hidden: document.getElementById("childTaskContent").hidden,
    raw_source_visible: document.body.textContent.includes("|---| INTERNAL RAW SOURCE"),
  }));
  assert(report.unavailable.body === fixture.invalid_runtime_response.message, "canonical unavailable copy replaced");
  assert(report.unavailable.pending === fixture.invalid_runtime_response.message, "canonical unavailable progress copy replaced");
  assert(report.unavailable.form_hidden && report.unavailable.task_hidden, "unavailable state exposed answer surface");
  assert(!report.unavailable.raw_source_visible, "unavailable state exposed raw source");
  report.no_network = report.no_network && mountedUnavailable.unexpectedRequests.length === 0;
  report.unexpected_network.push(...mountedUnavailable.unexpectedRequests);
  await mountedUnavailable.page.close();

  assert(report.no_network, `browser gate made an unexpected network request: ${report.unexpected_network.join(", ")}`);
  process.stdout.write(JSON.stringify(report));
} finally {
  await browser.close();
}
