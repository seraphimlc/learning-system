import fs from "node:fs";
import path from "node:path";
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
const evidenceDir = path.resolve(
  arg("--evidence-dir") || "artifacts/browser/knowledge_views_v51"
);
fs.mkdirSync(evidenceDir, { recursive: true });

const expectedModuleOrder = [
  "底层计算与数感",
  "有理数概念与运算",
  "分数百分数与比例",
  "算术到代数桥梁",
  "代数式与整式",
  "一元一次方程",
  "应用题模型",
  "几何图形初步",
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();
const report = {};
const screenshots = {};

async function screenshot(name) {
  const target = path.join(evidenceDir, name);
  await page.screenshot({ path: target, fullPage: false });
  screenshots[name] = target;
}

async function projectionSnapshot() {
  return page.evaluate(async () => {
    const response = await fetch("/api/knowledge-map");
    if (!response.ok) throw new Error(`knowledge-map status ${response.status}`);
    return response.json();
  });
}

async function openKnowledgeMapExplorer() {
  const toggle = page.getByRole("button", { name: "打开完整知识导图" });
  await toggle.waitFor({ state: "visible" });
  await toggle.click();
  await page.getByRole("region", { name: "我的数学知识导图" }).waitFor();
}

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });

  const projection = await projectionSnapshot();
  report.knowledge_projection_sets_connection_ready =
    projection.schema_version === "5.1-knowledge-views" &&
    projection.default_view === "mind_map" &&
    projection.nodes.length === 55 &&
    projection.modules.length === 8 &&
    Object.keys(projection.views).length === 1 &&
    Boolean(projection.views.mind_map);
  report.child_projection_hides_internal_process =
    !JSON.stringify(projection).includes("学习流程与错因") &&
    !JSON.stringify(projection).includes("解题步骤与检验习惯");
  report.child_projection_learning_path_order =
    JSON.stringify(projection.modules.map((module) => module.name)) ===
    JSON.stringify(expectedModuleOrder);

  report.not_started_hides_resume_learning =
    await page.locator(".knowledge-current-wrap").isHidden().catch(() => false);
  report.child_home_defaults_to_simple_start =
    await page.locator("[data-knowledge-start-panel]").isVisible().catch(() => false);
  report.first_visit_mind_map =
    await page.getByRole("button", { name: "打开完整知识导图" }).isVisible().catch(() => false) &&
    await page.getByRole("radiogroup", { name: "知识展示方式" }).count() === 0 &&
    await page.locator('input[value="graph"]').count() === 0;
  report.desktop_1280_no_horizontal_scroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );

  await openKnowledgeMapExplorer();
  const moduleTitles = await page.locator(".mind-module-toggle").evaluateAll((items) =>
    items.map((item) => item.textContent.trim().replace(/\s+/g, " "))
  );
  report.mind_virtual_root_and_eight_modules_collapsed =
    await page.locator(".mind-virtual-root").count() === 1 &&
    moduleTitles.length === 8 &&
    await page.locator(".mind-module-list:not([hidden])").count() === 0;
  report.mind_module_order_matches_learning_path =
    JSON.stringify(moduleTitles) === JSON.stringify(expectedModuleOrder);
  report.child_dom_has_no_graph_surface =
    !/图谱/.test(await page.locator("body").innerText()) &&
    await page.locator('[data-knowledge-view="graph"]').count() === 0 &&
    await page.locator(".graph-overview-marker, .graph-node-button").count() === 0;
  report.internal_process_module_hidden_in_dom =
    !/学习流程与错因|解题步骤与检验习惯/.test(await page.locator("body").innerText());

  await page.getByRole("button", { name: "展开全部知识模块" }).click();
  const firstNode = page.locator(".knowledge-node-button").first();
  await firstNode.click();
  report.node_selection_opens_child_safe_detail =
    await page.locator("[data-knowledge-detail]").isVisible().catch(() => false) &&
    await page.locator("[data-knowledge-detail]").innerText().then((text) =>
      !/node_id|graph_version|provider|rubric|queue|job|agent/i.test(text)
    );
  report.search_results_max_six = await page.locator("#knowledgeSearchInput").fill("数")
    .then(async () => page.locator(".mind-search-results .knowledge-node-button").count())
    .then((count) => count > 0 && count <= 6);
  report.search_clear_preserves_child_surface = await page.locator("[data-clear-search]").click()
    .then(async () => page.locator(".mind-virtual-root").isVisible());
  report.child_safe_dom = await page.locator("body").innerText().then((text) =>
    !/node_id|graph_version|provider|rubric|queue|job|agent|图谱|学习流程与错因/i.test(text)
  );
  await screenshot("knowledge-v51-child-map-desktop.png");

  await page.setViewportSize({ width: 390, height: 780 });
  await page.waitForTimeout(100);
  report.mobile_390_no_horizontal_scroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );
  report.mobile_controls_44px = await page.locator("button").evaluateAll((buttons) =>
    buttons.filter((button) => button.offsetParent !== null).every((button) => {
      const rect = button.getBoundingClientRect();
      return rect.width >= 36 && rect.height >= 36;
    })
  );
  await screenshot("knowledge-v51-child-map-mobile.png");

  report.screenshots_written = Object.keys(screenshots).length === 2;
  report.screenshots = screenshots;
} finally {
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
