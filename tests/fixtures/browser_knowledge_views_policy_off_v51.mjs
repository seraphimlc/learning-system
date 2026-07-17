import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const index = process.argv.indexOf("--base-url");
const baseUrl = index >= 0 ? process.argv[index + 1] : "";
if (!baseUrl) throw new Error("--base-url is required");

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const result = await page.evaluate(() => ({
    knowledgeButtonHidden: document.getElementById("knowledgeHomeBtn")?.hidden === true,
    knowledgeMountEmpty: document.getElementById("knowledgeHomeMount")?.childElementCount === 0,
    mapSurfaceHidden: document.getElementById("view-knowledge-home")?.hidden === true,
    learningSurfaceVisible: document.getElementById("view-child")?.hidden === false,
    mapRadioCount: document.querySelectorAll('input[name="knowledge-view-mode"]').length,
  }));
  if (!Object.values(result).every((value) => value === true || value === 0)) {
    throw new Error(`policy-off map surface remained available: ${JSON.stringify(result)}`);
  }
  process.stdout.write(JSON.stringify(result));
} finally {
  await browser.close();
}
