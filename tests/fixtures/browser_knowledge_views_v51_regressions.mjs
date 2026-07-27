import fs from "node:fs";
import path from "node:path";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function arg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

async function settleFrames(page, count = 4) {
  await page.evaluate(async (frameCount) => {
    for (let index = 0; index < frameCount; index += 1) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }, count);
}

async function openKnowledgeMap(page) {
  const learningVisible = await page.locator("#view-child").isVisible().catch(() => false);
  if (learningVisible) await page.locator("#knowledgeHomeBtn").click();
  await page.getByRole("region", { name: "我的数学知识目录" }).waitFor();
}

const baseUrl = arg("--base-url");
if (!baseUrl) throw new Error("--base-url is required");
const stableNodeName = arg("--stable-node-name");
const prerequisiteNodeName = arg("--prerequisite-node-name");
const currentNodeName = arg("--current-node-name");
if (!stableNodeName || !prerequisiteNodeName || !currentNodeName) {
  throw new Error("state-oracle node names are required");
}
const evidenceDir = path.resolve(
  arg("--evidence-dir") || "tests/evidence/knowledge_views_v51_regressions"
);
fs.mkdirSync(evidenceDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const report = {};
const screenshots = {};

async function screenshot(page, name) {
  const target = path.join(evidenceDir, name);
  await page.screenshot({ path: target, fullPage: false });
  screenshots[name] = target;
}

async function freshPage(viewport, { openMap = true } = {}) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  if (openMap) {
    await openKnowledgeMap(page);
  }
  return { context, page };
}

async function projection() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    return await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
  } finally {
    await context.close();
  }
}

async function mobileSheetModalCleanupOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    const node = page.locator(".knowledge-node-button:visible").first();
    const handle = await node.getAttribute("data-node-handle");
    const baselineInertCount = await page.locator("[inert]").count();
    await node.click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    const openState = await page.evaluate(() => {
      const detail = document.querySelector("[data-knowledge-detail]");
      return {
        modal: detail?.getAttribute("aria-modal") === "true",
        labelled: detail?.getAttribute("aria-labelledby") === "knowledgeDetailHeading",
        inertCount: document.querySelectorAll("[inert]").length,
      };
    });
    await page.keyboard.press("Escape");
    await settleFrames(page);
    const closedState = await page.evaluate((selectedHandle) => {
      const detail = document.querySelector("[data-knowledge-detail]");
      return {
        hidden: Boolean(detail?.hidden),
        empty: (detail?.innerHTML || "").trim() === "",
        focusRestored: document.activeElement?.getAttribute("data-node-handle") === selectedHandle,
        inertCount: document.querySelectorAll("[inert]").length,
      };
    }, handle);
    await screenshot(page, "knowledge-v51-regression-mobile-sheet-cleanup.png");
    return {
      pass:
        openState.modal && openState.labelled && openState.inertCount > 0 &&
        closedState.hidden && closedState.empty && closedState.focusRestored &&
        closedState.inertCount === baselineInertCount,
      baselineInertCount,
      openState,
      closedState,
    };
  } finally {
    await context.close();
  }
}

async function graphPreferenceIsIgnoredOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const payload = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const prefix = `son-ai-knowledge-views:v5.1:${payload.projection_version}`;
    await page.evaluate((scopedPrefix) => {
      localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "graph");
      localStorage.setItem(`${scopedPrefix}:active-view`, "graph");
      localStorage.setItem(`${scopedPrefix}:graph:viewport`, JSON.stringify({ scale: 1.2, x: 999, y: 777 }));
    }, prefix);
    await page.reload({ waitUntil: "networkidle" });
    await openKnowledgeMap(page);
    const state = await page.evaluate(() => ({
      hasGraphText: /图谱/.test(document.body.textContent || ""),
      graphRegionCount: document.querySelectorAll('[data-knowledge-view="graph"]').length,
      graphRadioCount: document.querySelectorAll('input[value="graph"]').length,
      activeView: window.KnowledgeViews?.currentView?.(),
    }));
    await screenshot(page, "knowledge-v51-regression-graph-cache-ignored.png");
    return {
      pass:
        !state.hasGraphText && state.graphRegionCount === 0 &&
        state.graphRadioCount === 0 && state.activeView === "mind_map",
      state,
    };
  } finally {
    await context.close();
  }
}

async function searchSelectionRestoreOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const payload = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const target = payload.nodes.find((node) => node.name === prerequisiteNodeName) || payload.nodes[0];
    const search = page.getByRole("search").getByRole("searchbox");
    await search.fill(target.name);
    const result = page.locator(`.mind-search-results .knowledge-node-button[data-node-handle="${target.handle}"]`);
    await result.waitFor({ state: "visible" });
    await result.click();
    await page.getByRole("complementary").waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "清除搜索", exact: true }).click();
    await settleFrames(page);
    const restored = await page.evaluate((handle) => {
      const selected = document.querySelector(`.knowledge-node-button[data-node-handle="${handle}"]`);
      return {
        selectedVisible: Boolean(selected?.getClientRects().length),
        selectedPressed: selected?.getAttribute("aria-pressed") === "true",
        directoryVisible: Boolean(document.querySelector(".mind-module-root-list")?.getClientRects().length),
      };
    }, target.handle);
    await screenshot(page, "knowledge-v51-regression-search-selection-restore.png");
    return {
      pass: restored.selectedVisible && restored.selectedPressed && restored.directoryVisible,
      target: target.name,
      restored,
    };
  } finally {
    await context.close();
  }
}

async function hideShowPreservesChildSurfaceOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    await page.getByRole("search").getByRole("searchbox").fill("数");
    await page.locator("[data-knowledge-filter]").selectOption("untested");
    await page.evaluate(() => window.KnowledgeViews.hide());
    await page.evaluate(() => window.KnowledgeViews.show());
    const state = await page.evaluate(() => ({
      query: document.querySelector("#knowledgeSearchInput")?.value || "",
      filter: document.querySelector("[data-knowledge-filter]")?.value || "",
      graphText: /图谱/.test(document.body.textContent || ""),
    }));
    await screenshot(page, "knowledge-v51-regression-hide-show-child-surface.png");
    return {
      pass: state.query === "数" && state.filter === "untested" && !state.graphText,
      state,
    };
  } finally {
    await context.close();
  }
}

async function stateAppropriateActionDescriptorsOracle(payload) {
  const stable = payload.nodes.find((node) => node.name === stableNodeName);
  const prerequisite = payload.nodes.find((node) => node.name === prerequisiteNodeName);
  const current = payload.nodes.find((node) => node.name === currentNodeName);
  return {
    pass:
      stable?.action_descriptors?.some((item) => item.action === "challenge" && item.enabled) &&
      stable?.action_descriptors?.some((item) => item.action === "review" && item.enabled) &&
      prerequisite?.action_readiness?.code === "needs_prerequisite" &&
      prerequisite?.action_descriptors?.some((item) =>
        item.action === "learn" && item.enabled && item.label === "先补准备知识"
      ) &&
      current?.action_descriptors?.length > 0,
    stable: stable?.action_descriptors,
    prerequisite: prerequisite?.action_descriptors,
    current: current?.action_descriptors,
  };
}

async function resumeRequiresFreshBootstrapOracle() {
  const { context, page } = await freshPage(
    { width: 1280, height: 800 },
    { openMap: false },
  );
  try {
    const mapWasDefault = await page.locator("#view-knowledge-home:not([hidden])").isVisible();
    let mapRequestCount = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/knowledge-map") mapRequestCount += 1;
    });
    await page.evaluate(() => {
      sessionStorage.setItem("son-ai-learning:primary-surface:v5.1", "learning_step");
    });
    await page.reload({ waitUntil: "networkidle" });
    await page.locator("#view-child:not([hidden])").waitFor();
    const heading = await page.locator("#childHeading").textContent().catch(() => "");
    await page.locator("#knowledgeHomeBtn").click();
    await page.getByRole("region", { name: "我的数学知识目录" }).waitFor();
    return {
      pass: mapWasDefault && heading.includes(currentNodeName) && mapRequestCount >= 1,
      mapWasDefault,
      heading,
      mapRequestCount,
    };
  } finally {
    await context.close();
  }
}

try {
  const payload = await projection();
  report.child_map_only_projection = {
    pass:
      payload.nodes.length === 55 &&
      payload.modules.length === 8 &&
      Object.keys(payload.views).length === 1 &&
      Boolean(payload.views.mind_map) &&
      !JSON.stringify(payload).includes("学习流程与错因"),
    moduleNames: payload.modules.map((module) => module.name),
  };
  report.state_appropriate_action_descriptors = await stateAppropriateActionDescriptorsOracle(payload);
  report.mobile_sheet_modal_cleanup = await mobileSheetModalCleanupOracle();
  report.graph_preference_is_ignored = await graphPreferenceIsIgnoredOracle();
  report.search_selection_restores_context = await searchSelectionRestoreOracle();
  report.hide_show_preserves_child_surface = await hideShowPreservesChildSurfaceOracle();
  report.resume_requires_fresh_bootstrap_current_step = await resumeRequiresFreshBootstrapOracle();
} finally {
  await browser.close();
}

console.log(JSON.stringify({ report, screenshots }, null, 2));
