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
  const alreadyOpen = await page.getByRole("region", { name: "我的数学知识目录" }).isVisible().catch(() => false);
  if (alreadyOpen) return;
  const toggle = page.getByRole("button", { name: "打开完整知识目录" });
  await toggle.waitFor({ state: "visible" });
  await toggle.click();
  await page.getByRole("region", { name: "我的数学知识目录" }).waitFor();
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
    await page.getByRole("button", { name: "收起完整知识目录" }).isVisible().catch(() => false) &&
    await page.getByRole("region", { name: "我的数学知识目录" }).isVisible().catch(() => false) &&
    await page.getByRole("radiogroup", { name: "知识展示方式" }).count() === 0 &&
    await page.locator('input[value="graph"]').count() === 0;
  report.desktop_1280_no_horizontal_scroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );

  await openKnowledgeMapExplorer();
  const moduleTitles = await page.locator(".mind-module-heading").evaluateAll((items) =>
    items.map((item) => item.childNodes[0]?.textContent?.trim() || "")
  );
  report.flat_directory_shows_eight_modules_with_visible_nodes =
    moduleTitles.length === 8 &&
    await page.locator(".mind-virtual-root").count() === 0 &&
    await page.locator(".mind-node-toggle").count() === 0 &&
    await page.locator(".mind-node-children").count() === 0 &&
    await page.locator(".mind-module-list:not([hidden])").count() === 8 &&
    await page.locator(".mind-module-list .knowledge-node-button:visible").count() === 55;
  report.directory_uses_masonry_columns =
    await page.locator(".mind-module-root-list").evaluate((element) => {
      const style = getComputedStyle(element);
      return style.display === "block" &&
        style.gridTemplateColumns === "none" &&
        style.columnWidth !== "auto" &&
        Number.parseFloat(style.columnWidth) >= 240;
    });
  report.mind_module_order_matches_learning_path =
    JSON.stringify(moduleTitles) === JSON.stringify(expectedModuleOrder);
  report.child_dom_has_no_graph_surface =
    !/图谱/.test(await page.locator("body").innerText()) &&
    await page.locator('[data-knowledge-view="graph"]').count() === 0 &&
    await page.locator(".graph-overview-marker, .graph-node-button").count() === 0;
  report.internal_process_module_hidden_in_dom =
    !/学习流程与错因|解题步骤与检验习惯/.test(await page.locator("body").innerText());

  const firstNode = page.locator(".knowledge-node-button").first();
  await firstNode.click();
  report.node_selection_opens_child_safe_detail =
    await page.locator("[data-knowledge-detail]").isVisible().catch(() => false) &&
    await page.locator("[data-knowledge-detail]").innerText().then((text) =>
      !/node_id|graph_version|provider|rubric|queue|job|agent/i.test(text)
    );
  await page.getByRole("button", { name: "收起完整知识目录" }).click();
  report.collapsed_directory_closes_detail_and_removes_extra_space =
    await page.evaluate(() => {
      const root = document.querySelector("[data-knowledge-home]");
      const detail = document.querySelector("[data-knowledge-detail]");
      const body = document.querySelector("[data-map-explorer-body]");
      const explorer = document.querySelector("[data-knowledge-map-explorer]");
      if (!root || !detail || !body || !explorer) return false;
      const rootRect = root.getBoundingClientRect();
      const explorerRect = explorer.getBoundingClientRect();
      return detail.hidden &&
        body.hidden &&
        !root.matches(":has(.knowledge-detail:not([hidden]))") &&
        Math.abs(rootRect.bottom - explorerRect.bottom) < 24;
    });
  await openKnowledgeMapExplorer();
  report.search_results_max_six = await page.locator("#knowledgeSearchInput").fill("数")
    .then(async () => page.locator(".mind-search-results .knowledge-node-button").count())
    .then((count) => count > 0 && count <= 6);
  report.search_clear_preserves_child_surface = await page.locator("[data-clear-search]").click()
    .then(async () => page.locator(".mind-module-root-list").isVisible());
  report.child_safe_dom = await page.locator("body").innerText().then((text) =>
    !/node_id|graph_version|provider|rubric|queue|job|agent|图谱|学习流程与错因/i.test(text)
  );
  await screenshot("knowledge-v51-child-map-desktop.png");

  await page.setViewportSize({ width: 390, height: 780 });
  await page.waitForTimeout(100);
  report.mobile_390_no_horizontal_scroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );
  report.mobile_directory_stays_single_column =
    await page.locator(".mind-module-root-list").evaluate((element) => {
      const style = getComputedStyle(element);
      return style.columnCount === "1" && style.columnWidth === "auto";
    });
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
