import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function arg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const baseUrl = arg("--base-url");
assert(baseUrl, "--base-url is required");

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
let rendererRequestCount = 0;
let failFirstRendererRequest = true;
let submitRequestCount = 0;

try {
  await page.route("**/question_visual_renderer.js", async (route) => {
    rendererRequestCount += 1;
    if (failFirstRendererRequest) {
      failFirstRendererRequest = false;
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/current-step/submit")) submitRequestCount += 1;
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const visualError = page.getByRole("alert").filter({ hasText: /题面图未加载|当前步骤还没有准备好/ });
  try {
    await visualError.waitFor({ timeout: 10000 });
  } catch (waitError) {
    throw new Error(`${waitError.message}\nBODY:\n${await page.locator("body").innerText()}`);
  }
  const submit = page.getByRole("button", { name: /保存|提交|完成/ }).first();
  assert(await submit.isDisabled(), "required visual failure did not disable submit");
  assert(submitRequestCount === 0, "failed visual phase emitted a submit request");

  await page.reload({ waitUntil: "networkidle" });
  const visual = page.locator('#childTaskContent [role="img"]').first();
  await visual.waitFor({ timeout: 10000 });
  const beforeReloadMarkup = await visual.evaluate((element) => element.outerHTML);
  assert(beforeReloadMarkup.includes("aria-label"), "recovered visual lacks an accessible label");
  const visualPresentBeforeReload = await visual.isVisible();

  await page.reload({ waitUntil: "networkidle" });
  const reloadedVisual = page.locator('#childTaskContent [role="img"]').first();
  await reloadedVisual.waitFor({ timeout: 10000 });
  const afterReloadMarkup = await reloadedVisual.evaluate((element) => element.outerHTML);
  assert(beforeReloadMarkup === afterReloadMarkup, "visual changed after reload");
  const visualPresentAfterReload = await reloadedVisual.isVisible();

  const choice = page.locator('[data-interaction-choice="B"]');
  if (await choice.count()) await choice.check();
  const answer = page.locator("#childAnswerRaw");
  if (await answer.isVisible()) await answer.fill("乙明确使用了原点、正方向和单位长度来比较位置。");

  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/current-step/submit"),
    { timeout: 15000 },
  );
  await submit.click({ clickCount: 2, delay: 5 });
  const response = await responsePromise;
  assert(response.ok(), `submit failed with HTTP ${response.status()}`);
  await page.waitForTimeout(300);
  assert(submitRequestCount === 1, `expected one submit request, got ${submitRequestCount}`);

  process.stdout.write(JSON.stringify({
    renderer_request_count: rendererRequestCount,
    visual_present_before_reload: visualPresentBeforeReload,
    visual_present_after_reload: visualPresentAfterReload,
    submit_request_count: submitRequestCount,
  }));
} finally {
  await browser.close();
}
