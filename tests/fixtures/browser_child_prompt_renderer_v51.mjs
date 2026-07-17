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

const rendererPath = arg("--renderer");
const stylePath = arg("--style");
const fixturePath = arg("--fixture");
assert(rendererPath && stylePath && fixturePath, "renderer, style and fixture are required");

const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const browser = await chromium.launch({ headless: true });
const report = { viewports: {}, invalid_rejected: false, no_network: true };

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.setContent('<main><div id="host"></div></main>');
  await page.addStyleTag({ path: stylePath });
  await page.addScriptTag({ path: rendererPath });

  for (const viewport of [
    { key: "1280", width: 1280, height: 800 },
    { key: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const result = await page.evaluate((payload) => {
      const host = document.getElementById("host");
      const promptHtml = window.ChildPromptRenderer.promptHtml(payload);
      const titleHtml = window.ChildPromptRenderer.inlineHtml(
        payload.interaction_rendering.title,
        payload.interaction_schema.title,
      );
      host.innerHTML = `<div class="child-prompt">${promptHtml}</div><div class="schema-label">${titleHtml}</div>`;
      const prompt = host.querySelector(".child-prompt");
      const powers = [...host.querySelectorAll(".math-power")];
      return {
        prompt_text: prompt.textContent,
        white_space: getComputedStyle(prompt).whiteSpace,
        powers: powers.map((element) => ({
          label: element.getAttribute("aria-label"),
          source: element.getAttribute("data-linear-source"),
          sup: element.querySelector("sup")?.textContent || "",
        })),
        no_script: !host.querySelector("script, iframe, object, embed"),
        no_horizontal_scroll: document.documentElement.scrollWidth <= window.innerWidth,
      };
    }, fixture.valid);
    assert(result.white_space === "pre-line", `${viewport.key}: prompt white-space is not pre-line`);
    assert(result.powers.length >= 2, `${viewport.key}: prompt/schema exponent markup missing`);
    assert(result.powers.every((entry) => entry.label && entry.source && entry.sup), `${viewport.key}: exponent semantics incomplete`);
    assert(result.no_script, `${viewport.key}: escaped source injected active DOM`);
    assert(result.no_horizontal_scroll, `${viewport.key}: horizontal document overflow`);
    report.viewports[viewport.key] = result;
  }

  report.invalid_rejected = await page.evaluate((payload) => (
    window.ChildPromptRenderer.promptHtml(payload) === null
  ), fixture.invalid);
  assert(report.invalid_rejected, "invalid canonical segments were accepted");
  report.no_network = requests.length === 0;
  assert(report.no_network, "renderer made network requests");
  process.stdout.write(JSON.stringify(report));
} finally {
  await browser.close();
}
