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
let rendererRequestSeen = false;
let submitRequestSeen = false;

try {
  await page.route("**/question_visual_renderer.js", async (route) => {
    rendererRequestSeen = true;
    await route.abort("failed");
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/current-step/submit")) submitRequestSeen = true;
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  assert(rendererRequestSeen, "child page did not request the required visual renderer");
  const error = page.getByRole("alert").filter({ hasText: /图|题面|显示|加载/ });
  await error.waitFor();
  const submit = page.getByRole("button", { name: /保存|提交|完成/ }).first();
  assert(await submit.isDisabled(), "submit stayed enabled after required visual failure");
  assert(!submitRequestSeen, "visual failure emitted a submit request");
  process.stdout.write(JSON.stringify({ renderer_failure_blocked_submit: true }));
} finally {
  await browser.close();
}
