import fs from "node:fs";
import path from "node:path";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function arg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function storagePrefix(projectionVersion) {
  return `son-ai-knowledge-views:v5.1:${projectionVersion}`;
}

function projectionVariant(projection, suffix) {
  const variant = structuredClone(projection);
  variant.projection_version = `${projection.projection_version}:${suffix}`;
  return variant;
}

async function settleFrames(page, count = 4) {
  await page.evaluate(async (frameCount) => {
    for (let index = 0; index < frameCount; index += 1) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }, count);
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

async function freshPage(viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await openKnowledgeMapExplorer(page);
  return { context, page };
}

async function screenshot(page, name) {
  const target = path.join(evidenceDir, name);
  await page.screenshot({ path: target, fullPage: false });
  screenshots[name] = target;
}

async function openKnowledgeMapExplorer(page) {
  const toggle = page.locator("[data-map-explorer-toggle]");
  await toggle.waitFor({ state: "visible" });
  if (await toggle.isVisible() && await toggle.getAttribute("aria-expanded") === "false") {
    await toggle.click();
  }
  await page.getByRole("radiogroup", { name: "知识展示方式" }).waitFor();
}

async function mobileSheetCleanupOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    const mindMap = page.getByRole("radio", { name: "导图", exact: true });
    const mindRegion = page.getByRole("region", { name: "我的数学知识导图" });
    await mindMap.check();
    const moduleToggle = mindRegion.locator(".mind-module-toggle").first();
    if ((await moduleToggle.getAttribute("aria-expanded")) === "false") {
      await moduleToggle.click();
    }
    const node = mindRegion.locator(".knowledge-node-button:visible").first();
    const handle = await node.getAttribute("data-node-handle");
    const baselineInertCount = await page.locator("[inert]").count();
    const transformBefore = await mindRegion.locator(".knowledge-world").evaluate(
      (element) => element.style.transform
    );
    await node.click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    const openState = await page.evaluate(() => {
      const detail = document.querySelector("[data-knowledge-detail]");
      return {
        modal: detail?.getAttribute("aria-modal") === "true",
        labelled: detail?.getAttribute("aria-labelledby") === "knowledgeDetailHeading",
        maxHeight: detail?.style.maxHeight || "",
        inertCount: document.querySelectorAll("[inert]").length,
      };
    });
    await page.keyboard.press("Escape");
    await settleFrames(page);
    const closedState = await page.evaluate((selectedHandle) => {
      const detail = document.querySelector("[data-knowledge-detail]");
      const focusHandle = document.activeElement?.getAttribute("data-node-handle") || "";
      return {
        hidden: Boolean(detail?.hidden),
        empty: (detail?.innerHTML || "").trim() === "",
        role: detail?.getAttribute("role"),
        ariaModal: detail?.getAttribute("aria-modal"),
        ariaLabelledby: detail?.getAttribute("aria-labelledby"),
        maxHeight: detail?.style.maxHeight || "",
        inertCount: document.querySelectorAll("[inert]").length,
        focusRestored: focusHandle === selectedHandle,
      };
    }, handle);
    const transformAfter = await mindRegion.locator(".knowledge-world").evaluate(
      (element) => element.style.transform
    );
    await screenshot(page, "dual-v51-regression-mobile-sheet-cleanup.png");
    return {
      pass:
        openState.modal && openState.labelled && Boolean(openState.maxHeight) && openState.inertCount > 0 &&
        closedState.hidden && closedState.empty && closedState.role === null &&
        closedState.ariaModal === null && closedState.ariaLabelledby === null &&
        closedState.maxHeight === "" && closedState.inertCount === baselineInertCount &&
        closedState.focusRestored && transformAfter === transformBefore,
      baselineInertCount,
      openState,
      closedState,
      transformRestored: transformAfter === transformBefore,
    };
  } finally {
    await context.close();
  }
}

async function invalidNodeFocusRecoversToFitAllOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const prefix = storagePrefix(projection.projection_version);
    const illegalViewport = { scale: 1.37, x: 937, y: 711 };
    await page.evaluate(({ scopedPrefix, viewport }) => {
      localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "graph");
      localStorage.setItem(`${scopedPrefix}:graph:focus-mode`, "node_focus");
      localStorage.setItem(`${scopedPrefix}:graph:viewport`, JSON.stringify(viewport));
    }, { scopedPrefix: prefix, viewport: illegalViewport });
    await page.reload({ waitUntil: "networkidle" });
    await openKnowledgeMapExplorer(page);
    await settleFrames(page, 6);
    const graph = page.getByRole("radio", { name: "图谱", exact: true });
    const graphRegion = page.getByRole("region", { name: "我的数学知识图谱" });
    const geometry = await graphRegion.evaluate((regionElement) => {
      const markers = [...regionElement.querySelectorAll(".graph-overview-marker")];
      const fullNodes = [...regionElement.querySelectorAll(".graph-node-button")];
      const region = regionElement.getBoundingClientRect();
      const markerBoxes = markers.map((element) => {
        const rect = element.getBoundingClientRect();
        const visualStyle = getComputedStyle(element, "::before");
        const width = Number.parseFloat(visualStyle.width) || rect.width;
        const height = Number.parseFloat(visualStyle.height) || rect.height;
        return {
          left: rect.left + (rect.width - width) / 2,
          top: rect.top + (rect.height - height) / 2,
          right: rect.right - (rect.width - width) / 2,
          bottom: rect.bottom - (rect.height - height) / 2,
        };
      });
      const boxes = [...markers, ...fullNodes].map((element) => element.getBoundingClientRect());
      const outside = markerBoxes.filter((box) =>
        box.left < region.left - 1 || box.right > region.right + 1 ||
        box.top < region.top - 1 || box.bottom > region.bottom + 1
      ).slice(0, 5);
      return {
        markerCount: markers.length,
        fullNodeCount: fullNodes.length,
        totalCount: boxes.length,
        markersInside: Boolean(region) && markerBoxes.every((box) =>
          box.left >= region.left - 1 && box.right <= region.right + 1 &&
          box.top >= region.top - 1 && box.bottom <= region.bottom + 1
        ),
        region: { left: region.left, top: region.top, right: region.right, bottom: region.bottom },
        outside,
      };
    });
    const stored = await page.evaluate((scopedPrefix) => ({
      focusMode: localStorage.getItem(`${scopedPrefix}:graph:focus-mode`),
      viewport: JSON.parse(localStorage.getItem(`${scopedPrefix}:graph:viewport`) || "null"),
    }), prefix);
    const fullNodeCount = await graphRegion.locator(".graph-node-button").count();
    const transform = await graphRegion.locator(".graph-world").evaluate((element) => element.style.transform);
    await screenshot(page, "dual-v51-regression-invalid-node-focus-fit-all.png");
    return {
      pass:
        await graph.isChecked() && geometry.totalCount === 56 && fullNodeCount >= 1 &&
        stored.focusMode === "fit_all" && JSON.stringify(stored.viewport) !== JSON.stringify(illegalViewport) &&
        !transform.includes("937px") && !transform.includes("711px"),
      geometry,
      fullNodeCount,
      stored,
      transform,
    };
  } finally {
    await context.close();
  }
}

async function searchSelectionRestoreOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const mindMap = page.getByRole("radio", { name: "导图", exact: true });
    await mindMap.check();
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const target = await page.evaluate((payload) => {
      const placements = new Map(payload.views.mind_map.placements.map((placement) => [placement.handle, placement]));
      const incoming = new Map();
      for (const link of payload.views.mind_map.cross_links) {
        const bucket = incoming.get(link.target_handle) || [];
        bucket.push(link);
        incoming.set(link.target_handle, bucket);
      }
      const candidates = payload.nodes.filter((node) => incoming.has(node.handle)).map((node) => {
        const ancestors = [];
        let placement = placements.get(node.handle);
        while (placement?.parent_type === "node") {
          ancestors.unshift(placement.parent_handle);
          placement = placements.get(placement.parent_handle);
        }
        return {
          handle: node.handle,
          name: node.name,
          moduleHandle: placement?.parent_handle || node.module_handle,
          ancestorHandles: ancestors,
          crossCount: incoming.get(node.handle).length,
        };
      });
      return candidates.sort((left, right) =>
        right.ancestorHandles.length - left.ancestorHandles.length || right.crossCount - left.crossCount
      )[0];
    }, projection);
    if (!target) return { pass: false, error: "no cross-link target fixture" };
    const mindRegion = page.getByRole("region", { name: "我的数学知识导图" });
    const search = page.getByRole("search").getByRole("searchbox");
    await search.fill(target.name);
    const result = mindRegion.locator(
      `.mind-search-results .knowledge-node-button[data-node-handle="${target.handle}"]`
    );
    await result.click();
    await page.getByRole("complementary").waitFor();
    await page.keyboard.press("Escape");
    const transformBeforeClear = await mindRegion.locator(".knowledge-world").evaluate(
      (element) => element.style.transform
    );
    await page.getByRole("button", { name: "清除搜索", exact: true }).click();
    await settleFrames(page, 8);
    const restored = await page.evaluate((fixture) => {
      const region = document.querySelector('[data-knowledge-view="mind_map"]');
      const selected = region?.querySelector(
        `.knowledge-node-button[data-node-handle="${fixture.handle}"]`
      );
      const details = region?.querySelector(".mind-cross-prerequisites");
      const module = document.querySelector(
        `.mind-module-toggle[aria-controls="knowledge-module-${String(fixture.moduleHandle).replace(/[^A-Za-z0-9_-]/g, "_")}"]`
      );
      const ancestorStates = fixture.ancestorHandles.map((handle) => {
        const button = region?.querySelector(`.knowledge-node-button[data-node-handle="${handle}"]`);
        const toggle = button?.closest(".mind-node-row")?.querySelector(".mind-node-toggle");
        return {
          handle,
          visible: Boolean(button?.getClientRects().length),
          expanded: !toggle || toggle.getAttribute("aria-expanded") === "true",
        };
      });
      const regionRect = region?.getBoundingClientRect();
      const selectedRect = selected?.getBoundingClientRect();
      const detailsRect = details?.getBoundingClientRect();
      const combined = selectedRect && detailsRect ? {
        left: Math.min(selectedRect.left, detailsRect.left),
        top: Math.min(selectedRect.top, detailsRect.top),
        right: Math.max(selectedRect.right, detailsRect.right),
        bottom: Math.max(selectedRect.bottom, detailsRect.bottom),
      } : null;
      const centerDeltaX = regionRect && combined
        ? Math.abs((combined.left + combined.right) / 2 - (regionRect.left + regionRect.right) / 2)
        : null;
      const centerDeltaY = regionRect && combined
        ? Math.abs((combined.top + combined.bottom) / 2 - (regionRect.top + regionRect.bottom) / 2)
        : null;
      const centered = centerDeltaX !== null && centerDeltaY !== null &&
        centerDeltaX <= 48 && centerDeltaY <= 48;
      return {
        selectedVisible: Boolean(selectedRect?.width && selectedRect?.height),
        selectedPressed: selected?.getAttribute("aria-pressed") === "true",
        moduleExpanded: module?.getAttribute("aria-expanded") === "true",
        ancestorStates,
        crossOpen: Boolean(details?.open),
        crossRows: details?.querySelectorAll("[data-cross-link]").length || 0,
        crossPaths: details?.querySelectorAll(".mind-cross-path[marker-end]").length || 0,
        selectedAndCrossInside: Boolean(regionRect && selectedRect && detailsRect) &&
          selectedRect.left >= regionRect.left && selectedRect.right <= regionRect.right &&
          selectedRect.top >= regionRect.top && selectedRect.bottom <= regionRect.bottom &&
          detailsRect.left >= regionRect.left && detailsRect.right <= regionRect.right &&
          detailsRect.top >= regionRect.top && detailsRect.bottom <= regionRect.bottom,
        centered,
        centerDeltaX,
        centerDeltaY,
      };
    }, target);
    const transformAfterClear = await mindRegion.locator(".knowledge-world").evaluate(
      (element) => element.style.transform
    );
    await screenshot(page, "dual-v51-regression-search-selection-restore.png");
    return {
      pass:
        restored.selectedVisible && restored.selectedPressed && restored.moduleExpanded &&
        restored.ancestorStates.every((item) => item.visible && item.expanded) &&
        restored.crossOpen && restored.crossRows === target.crossCount &&
        restored.crossPaths === target.crossCount && restored.selectedAndCrossInside &&
        restored.centered && transformAfterClear !== transformBeforeClear,
      target,
      restored,
      transformChanged: transformAfterClear !== transformBeforeClear,
    };
  } finally {
    await context.close();
  }
}

async function projectionPreferenceIsolationOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const nextProjection = projectionVariant(projection, "next-projection-fixture");
    const v1Prefix = storagePrefix(projection.projection_version);
    const v2Prefix = storagePrefix(nextProjection.projection_version);
    const graph = page.getByRole("radio", { name: "图谱", exact: true });
    const mindMap = page.getByRole("radio", { name: "导图", exact: true });
    const firstModule = page.locator(".mind-module-toggle").first();
    const moduleHandle = projection.modules[0].handle;
    const defaultExpanded = (await firstModule.getAttribute("aria-expanded")) === "true";
    await graph.check();
    const v1Viewport = { scale: 1.37, x: 321, y: -222 };
    const v1Collapsed = { [moduleHandle]: defaultExpanded };
    await page.evaluate(({ prefix, viewport, collapsed }) => {
      localStorage.setItem(`${prefix}:graph:focus-mode`, "fit_all");
      localStorage.setItem(`${prefix}:graph:viewport`, JSON.stringify(viewport));
      localStorage.setItem(`${prefix}:mind_map:collapsed`, JSON.stringify(collapsed));
    }, { prefix: v1Prefix, viewport: v1Viewport, collapsed: v1Collapsed });
    await page.evaluate((payload) => {
      window.KnowledgeViews.initialize({
        root: document.getElementById("knowledgeHomeMount"),
        projection: payload,
        initialState: "ready",
      });
    }, projection);
    await settleFrames(page);
    const v1View = await page.evaluate(() => window.KnowledgeViews.currentView());
    const v1Transform = await page.locator('[data-knowledge-view="graph"] .graph-world').evaluate(
      (element) => element.style.transform
    );
    await page.evaluate((payload) => {
      window.KnowledgeViews.initialize({
        root: document.getElementById("knowledgeHomeMount"),
        projection: payload,
        initialState: "ready",
      });
    }, nextProjection);
    await settleFrames(page, 8);
    const v2View = await page.evaluate(() => window.KnowledgeViews.currentView());
    const v2Stored = await page.evaluate(({ first, second }) => ({
      activeView: localStorage.getItem("son-ai-knowledge-views:v5.1:active-view"),
      v1Viewport: localStorage.getItem(`${first}:graph:viewport`),
      v1Collapsed: localStorage.getItem(`${first}:mind_map:collapsed`),
      v2Viewport: localStorage.getItem(`${second}:graph:viewport`),
      v2Collapsed: localStorage.getItem(`${second}:mind_map:collapsed`),
    }), { first: v1Prefix, second: v2Prefix });
    await openKnowledgeMapExplorer(page);
    await mindMap.check();
    const v2Expanded = (await page.locator(".mind-module-toggle").first().getAttribute("aria-expanded")) === "true";
    await screenshot(page, "dual-v51-regression-projection-preference-isolation.png");
    return {
      pass:
        v1View === "graph" && v2View === "graph" && v2Stored.activeView === "graph" &&
        v1Transform.includes("321px") && v1Transform.includes("-222px") &&
        v2Stored.v1Viewport === JSON.stringify(v1Viewport) &&
        v2Stored.v1Collapsed === JSON.stringify(v1Collapsed) &&
        v2Stored.v2Viewport !== JSON.stringify(v1Viewport) && v2Stored.v2Collapsed === null &&
        v2Expanded === defaultExpanded,
      v1View,
      v2View,
      defaultExpanded,
      v2Expanded,
      v1Transform,
      stored: v2Stored,
    };
  } finally {
    await context.close();
  }
}

async function reinitializeClearsTransientQueryAndFilterOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const search = page.getByRole("search").getByRole("searchbox");
    const filter = page.locator("[data-knowledge-filter]");
    const untestedNode = projection.nodes.find((node) => node.learning_state === "untested");
    await search.fill(untestedNode?.name || projection.nodes[0].name);
    await filter.selectOption("untested");
    const before = {
      query: await search.inputValue(),
      filter: await filter.inputValue(),
      searchResultCount: await page.locator(".mind-search-results .knowledge-node-button").count(),
    };
    await page.evaluate((payload) => {
      window.KnowledgeViews.initialize({
        root: document.getElementById("knowledgeHomeMount"),
        projection: payload,
        initialState: "ready",
      });
    }, projection);
    await settleFrames(page);
    await openKnowledgeMapExplorer(page);
    const after = {
      query: await page.getByRole("search").getByRole("searchbox").inputValue(),
      filter: await page.locator("[data-knowledge-filter]").inputValue(),
      module: await page.locator("[data-module-select]").inputValue(),
      summary: await page.locator("[data-result-summary]").textContent(),
      searchResultCount: await page.locator(".mind-search-results").count(),
      virtualRootCount: await page.locator(".mind-virtual-root").count(),
      moduleCount: await page.locator(".mind-module-toggle").count(),
    };
    await screenshot(page, "dual-v51-regression-reinitialize-clears-transient-state.png");
    return {
      pass:
        Boolean(before.query) && before.filter !== "all" && before.searchResultCount >= 1 &&
        after.query === "" && after.filter === "all" && after.module === "" &&
        after.summary?.includes("56 个知识点") && after.searchResultCount === 0 &&
        after.virtualRootCount === 1 && after.moduleCount === 9,
      before,
      after,
    };
  } finally {
    await context.close();
  }
}

async function allowedActionsChangeInvalidatesPendingOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const actionable = projection.nodes.filter(
      (node) => Array.isArray(node.allowed_actions) && node.allowed_actions.length > 0
    );
    if (actionable.length < 2) return { pass: false, error: "two actionable nodes are required" };
    const staleNode = actionable[0];
    const nextNode = actionable[1];
    const pending = {
      handle: staleNode.handle,
      projection_version: projection.projection_version,
      action: staleNode.allowed_actions[0],
      client_idempotency_key: "kv51-stale-allowed-action-pending",
      status: "response_unknown",
    };
    const updated = structuredClone(projection);
    const updatedNode = updated.nodes.find((node) => node.handle === staleNode.handle);
    updatedNode.allowed_actions = [];
    updatedNode.action_disabled_reason = "当前动作资格已经更新。";
    const prefix = storagePrefix(projection.projection_version);
    await page.evaluate(({ scopedPrefix, oldPending, payload }) => {
      localStorage.setItem(`${scopedPrefix}:target-action`, JSON.stringify(oldPending));
      window.KnowledgeViews.initialize({
        root: document.getElementById("knowledgeHomeMount"),
        projection: payload,
        initialState: "ready",
        onAction: async () => ({ status: "blocked" }),
      });
    }, { scopedPrefix: prefix, oldPending: pending, payload: updated });
    await settleFrames(page);
    const pendingAfter = await page.evaluate(
      (scopedPrefix) => localStorage.getItem(`${scopedPrefix}:target-action`),
      prefix
    );
    await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), nextNode.handle);
    const nextAction = page.locator("[data-knowledge-detail] [data-action-name]").first();
    const nextEnabled = (await nextAction.count()) === 1 && !(await nextAction.isDisabled());
    await page.keyboard.press("Escape");
    await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), staleNode.handle);
    const staleDisabled =
      (await page.getByRole("button", { name: "暂不能开始学习", exact: true }).count()) === 1 &&
      await page.getByRole("button", { name: "暂不能开始学习", exact: true }).isDisabled();
    await screenshot(page, "dual-v51-regression-allowed-actions-invalidates-pending.png");
    return {
      pass: pendingAfter === null && nextEnabled && staleDisabled,
      pending,
      pendingAfter,
      nextEnabled,
      staleDisabled,
    };
  } finally {
    await context.close();
  }
}

async function selectedHiddenStateAndEscapeFocusOracle() {
  async function filterScenario() {
    const { context, page } = await freshPage({ width: 1280, height: 800 });
    try {
      const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
      const target = projection.nodes[0];
      const hidingFilter = target.learning_state === "untested" ? "recorded" : "untested";
      await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), target.handle);
      await page.locator("[data-knowledge-filter]").selectOption(hidingFilter);
      await settleFrames(page);
      const visibleBeforeEscape = await page.locator(
        `.knowledge-node-button[data-node-handle="${target.handle}"]:visible`
      ).count();
      await page.keyboard.press("Escape");
      await settleFrames(page);
      return {
        target: target.handle,
        hidingFilter,
        visibleBeforeEscape,
        visibleAfterEscape: await page.locator(
          `.knowledge-node-button[data-node-handle="${target.handle}"]:visible`
        ).count(),
        focusedHandle: await page.evaluate(
          () => document.activeElement?.getAttribute("data-node-handle") || ""
        ),
      };
    } finally {
      await context.close();
    }
  }

  async function collapseScenario() {
    const { context, page } = await freshPage({ width: 1280, height: 800 });
    try {
      const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
      const placement = projection.views.mind_map.placements.find((item) => item.parent_type === "node");
      if (!placement) return { error: "no nested placement" };
      await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), placement.handle);
      const parentButton = page.locator(
        `.knowledge-node-button[data-node-handle="${placement.parent_handle}"]`
      );
      const parentToggle = parentButton.locator("xpath=ancestor::div[contains(@class,'mind-node-row')][1]").locator(
        ".mind-node-toggle"
      );
      await parentToggle.click();
      await settleFrames(page);
      const visibleBeforeEscape = await page.locator(
        `.knowledge-node-button[data-node-handle="${placement.handle}"]:visible`
      ).count();
      await page.keyboard.press("Escape");
      await settleFrames(page);
      await screenshot(page, "dual-v51-regression-selected-collapse-escape-focus.png");
      return {
        target: placement.handle,
        parent: placement.parent_handle,
        visibleBeforeEscape,
        visibleAfterEscape: await page.locator(
          `.knowledge-node-button[data-node-handle="${placement.handle}"]:visible`
        ).count(),
        focusedHandle: await page.evaluate(
          () => document.activeElement?.getAttribute("data-node-handle") || ""
        ),
      };
    } finally {
      await context.close();
    }
  }

  const filtered = await filterScenario();
  const collapsed = await collapseScenario();
  return {
    pass:
      filtered.visibleAfterEscape === 1 && filtered.focusedHandle === filtered.target &&
      collapsed.visibleAfterEscape === 1 && collapsed.focusedHandle === collapsed.target,
    filtered,
    collapsed,
  };
}

async function destinationCameraIsPreservedExactlyOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const prefix = storagePrefix(projection.projection_version);
    const selected = projection.nodes[0];
    const graph = page.getByRole("radio", { name: "图谱", exact: true });
    const mindMap = page.getByRole("radio", { name: "导图", exact: true });
    await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), selected.handle);
    await page.keyboard.press("Escape");
    await graph.check();
    await settleFrames(page, 6);
    await page.getByRole("button", { name: "放大", exact: true }).click();
    const graphBefore = await page.evaluate((scopedPrefix) =>
      JSON.parse(localStorage.getItem(`${scopedPrefix}:graph:viewport`) || "null"), prefix
    );
    await mindMap.check();
    await page.getByRole("button", { name: "缩小", exact: true }).click();
    const mindBefore = await page.evaluate((scopedPrefix) =>
      JSON.parse(localStorage.getItem(`${scopedPrefix}:mind_map:viewport`) || "null"), prefix
    );
    await graph.check();
    await settleFrames(page, 6);
    const graphAfter = await page.evaluate((scopedPrefix) =>
      JSON.parse(localStorage.getItem(`${scopedPrefix}:graph:viewport`) || "null"), prefix
    );
    const graphTransform = await page.locator('[data-knowledge-view="graph"] .graph-world').evaluate(
      (element) => element.style.transform
    );
    await mindMap.check();
    await settleFrames(page);
    const mindAfter = await page.evaluate((scopedPrefix) =>
      JSON.parse(localStorage.getItem(`${scopedPrefix}:mind_map:viewport`) || "null"), prefix
    );
    const mindTransform = await page.locator('[data-knowledge-view="mind_map"] .knowledge-world').evaluate(
      (element) => element.style.transform
    );
    const validCamera = (camera) => camera && [camera.scale, camera.x, camera.y].every(Number.isFinite);
    const renderedCameraMatches = (camera, transform) => {
      const match = /^translate\(([-0-9.]+)px, ([-0-9.]+)px\) scale\(([-0-9.]+)\)$/.exec(transform);
      if (!match) return false;
      return Math.abs(Number(match[1]) - camera.x) <= 0.001 &&
        Math.abs(Number(match[2]) - camera.y) <= 0.001 &&
        Math.abs(Number(match[3]) - camera.scale) <= 0.000001;
    };
    await screenshot(page, "dual-v51-regression-destination-camera-exact.png");
    return {
      pass:
        validCamera(graphBefore) && validCamera(mindBefore) &&
        JSON.stringify(graphAfter) === JSON.stringify(graphBefore) &&
        JSON.stringify(mindAfter) === JSON.stringify(mindBefore) &&
        renderedCameraMatches(graphAfter, graphTransform) &&
        renderedCameraMatches(mindAfter, mindTransform),
      graphBefore,
      graphAfter,
      graphTransform,
      mindBefore,
      mindAfter,
      mindTransform,
    };
  } finally {
    await context.close();
  }
}

async function appliedFocusEntersLearningStepOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const actionable = projection.nodes.find(
      (node) => Array.isArray(node.allowed_actions) && node.allowed_actions.length > 0
    );
    if (!actionable) return { pass: false, error: "no actionable node fixture" };
    await page.route("**/api/knowledge-map/select", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "applied",
          result_behavior: "enter_now",
          message: "学习任务已经准备好",
        }),
      });
    });
    await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), actionable.handle);
    const action = page.locator("[data-knowledge-detail] [data-action-name]").first();
    await action.click();
    await page.waitForFunction(() => document.getElementById("view-child")?.hidden === false);
    await settleFrames(page);
    const focus = await page.evaluate(() => {
      const learning = document.getElementById("view-child");
      const map = document.getElementById("view-knowledge-home");
      const active = document.activeElement;
      const heading = document.getElementById("childHeading");
      const visiblePrimary = [...learning.querySelectorAll("button.primary:not(:disabled)")].filter(
        (element) => element.getClientRects().length > 0 && !element.closest("[inert]")
      );
      const headingCanReceiveFocus = heading.matches("[tabindex]");
      return {
        activeTag: active?.tagName || "",
        activeId: active?.id || "",
        activeText: active?.textContent?.trim() || "",
        activeInsideLearning: Boolean(active && learning.contains(active)),
        activeVisible: Boolean(active?.getClientRects().length),
        activeInert: Boolean(active?.closest("[inert]")),
        headingCanReceiveFocus,
        headingFocused: active === heading,
        visiblePrimaryCount: visiblePrimary.length,
        uniquePrimaryFocused: visiblePrimary.length === 1 && active === visiblePrimary[0],
        learningVisible: !learning.hidden && learning.getClientRects().length > 0,
        learningInert: learning.hasAttribute("inert"),
        mapHidden: map.hidden,
        mapInert: map.hasAttribute("inert"),
      };
    });
    await screenshot(page, "dual-v51-regression-applied-focus-learning-step.png");
    await page.unroute("**/api/knowledge-map/select");
    return {
      pass:
        focus.learningVisible && !focus.learningInert && focus.mapHidden && focus.mapInert &&
        focus.activeInsideLearning && focus.activeVisible && !focus.activeInert &&
        (focus.headingFocused || (!focus.headingCanReceiveFocus && focus.uniquePrimaryFocused)),
      focus,
    };
  } finally {
    await context.close();
  }
}

async function mobileActionFeedbackLifecycleOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    const projection = await page.evaluate(() => fetch("/api/knowledge-map").then((response) => response.json()));
    const actionable = projection.nodes.find(
      (node) => Array.isArray(node.allowed_actions) && node.allowed_actions.length > 0
    );
    if (!actionable) return { pass: false, error: "no actionable node fixture" };
    const prefix = storagePrefix(projection.projection_version);

    async function runOutcome(kind) {
      await page.evaluate(({ payload, handle }) => {
        window.KnowledgeViews.initialize({
          root: document.getElementById("knowledgeHomeMount"),
          projection: payload,
          initialState: "ready",
          onAction: () => new Promise((resolve, reject) => {
            window.__kv51ActionResolve = resolve;
            window.__kv51ActionReject = reject;
          }),
        });
        window.KnowledgeViews.focusNode(handle);
      }, { payload: projection, handle: actionable.handle });
      await page.getByRole("dialog").waitFor();
      const pending = await page.evaluate(async () => {
        const detail = document.querySelector("[data-knowledge-detail]");
        const live = document.querySelector("[data-knowledge-live]");
        const button = detail.querySelector("[data-action-name]");
        const beforeDetail = detail.innerText;
        const beforeLive = live.textContent || "";
        const startedAt = performance.now();
        button.click();
        while (performance.now() - startedAt <= 100) {
          await new Promise((resolve) => setTimeout(resolve, 5));
          const detailText = detail.innerText;
          const liveText = live.textContent || "";
          const visiblePending = detailText !== beforeDetail && /正在|提交|确认|准备|处理中/.test(detailText);
          const announcedPending = liveText !== beforeLive && /正在|提交|确认|准备|处理中/.test(liveText);
          if (visiblePending && announcedPending) {
            return {
              observed: true,
              elapsedMs: performance.now() - startedAt,
              detailText,
              liveText,
            };
          }
        }
        return {
          observed: false,
          elapsedMs: performance.now() - startedAt,
          detailText: detail.innerText,
          liveText: live.textContent || "",
        };
      });
      const message = kind === "success"
        ? "学习目标已经开始"
        : (kind === "waiting" ? "会在安全边界开始" : "连接中断，请安全重试");
      await page.evaluate(({ outcome, resultMessage }) => {
        if (outcome === "failure") {
          window.__kv51ActionReject(new Error(resultMessage));
          return;
        }
        window.__kv51ActionResolve({
          status: outcome === "success" ? "applied" : "waiting_for_safe_boundary",
          message: resultMessage,
        });
      }, { outcome: kind, resultMessage: message });
      await settleFrames(page);
      const settled = await page.evaluate(({ scopedPrefix, expectedMessage, pendingDetail }) => {
        const detail = document.querySelector("[data-knowledge-detail]");
        const live = document.querySelector("[data-knowledge-live]");
        const stored = JSON.parse(localStorage.getItem(`${scopedPrefix}:target-action`) || "null");
        const detailText = detail?.innerText || "";
        const liveText = live?.textContent || "";
        return {
          detailText,
          liveText,
          stored,
          visibleReplacement: detailText.includes(expectedMessage) && detailText !== pendingDetail,
          liveReplacement: liveText.includes(expectedMessage),
        };
      }, { scopedPrefix: prefix, expectedMessage: message, pendingDetail: pending.detailText });
      if (kind === "success") {
        settled.stateCorrect = settled.stored === null;
      } else if (kind === "waiting") {
        settled.stateCorrect = settled.stored?.status === "waiting_for_safe_boundary";
      } else {
        settled.stateCorrect = settled.stored?.status === "response_unknown";
        settled.visibleReplacement = /连接中断|安全重试/.test(settled.detailText) &&
          settled.detailText !== pending.detailText;
        settled.liveReplacement = /连接中断|安全重试/.test(settled.liveText);
      }
      return {
        pass:
          pending.observed && pending.elapsedMs <= 100 &&
          settled.visibleReplacement && settled.liveReplacement && settled.stateCorrect,
        pending,
        settled,
      };
    }

    const outcomes = {
      success: await runOutcome("success"),
      waiting: await runOutcome("waiting"),
      failure: await runOutcome("failure"),
    };
    await screenshot(page, "dual-v51-regression-mobile-action-feedback.png");
    return {
      pass: Object.values(outcomes).every((outcome) => outcome.pass),
      outcomes,
    };
  } finally {
    await context.close();
  }
}

async function resumeRequiresFreshBootstrapCurrentStepOracle() {
  const realResponse = await fetch(`${baseUrl}/api/child-bootstrap`);
  const realBootstrap = await realResponse.json();
  const expectedStep = realBootstrap?.current_step || null;
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  let bootstrapRequests = 0;
  let browserBootstrapPayload = null;
  let signalBootstrapRequest;
  const bootstrapRequestSeen = new Promise((resolve) => { signalBootstrapRequest = resolve; });
  let releaseBootstrapResponse;
  const bootstrapResponseReleased = new Promise((resolve) => { releaseBootstrapResponse = resolve; });
  try {
    await page.route(/\/api\/child-bootstrap(?:\?.*)?$/, async (route) => {
      bootstrapRequests += 1;
      const response = await route.fetch();
      browserBootstrapPayload = await response.json();
      signalBootstrapRequest();
      await bootstrapResponseReleased;
      await route.fulfill({
        response,
        contentType: "application/json",
        body: JSON.stringify(browserBootstrapPayload),
      });
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const resume = page.getByRole("button", { name: "继续当前学习", exact: true });
    const resumeVisible = await resume.isVisible();
    const clickPromise = resumeVisible ? resume.click() : Promise.resolve();
    const bootstrapRequestObserved = await Promise.race([
      bootstrapRequestSeen.then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(false), 1000)),
    ]);
    const pendingState = await page.evaluate(() => {
      const mapSurface = document.getElementById("view-knowledge-home");
      const learningSurface = document.getElementById("view-child");
      const answer = document.getElementById("childAnswerRaw");
      const save = document.getElementById("childSubmitBtn");
      const photo = document.getElementById("childAnswerPhoto");
      return {
        mapVisible: Boolean(mapSurface && !mapSurface.hidden && !mapSurface.closest("[inert]")),
        learningHidden: Boolean(learningSurface?.hidden),
        learningInert: Boolean(learningSurface?.closest("[inert]")),
        answerVisible: Boolean(answer && answer.getClientRects().length > 0),
        saveVisible: Boolean(save && save.getClientRects().length > 0),
        photoVisible: Boolean(photo && photo.getClientRects().length > 0),
      };
    });
    releaseBootstrapResponse();
    await clickPromise;
    if (bootstrapRequestObserved) {
      await page.waitForFunction(
        (prompt) => {
          const surface = document.getElementById("view-child");
          const answer = document.getElementById("childAnswerRaw");
          return Boolean(
            surface && !surface.hidden && answer && !answer.disabled &&
            document.body.innerText.includes(prompt)
          );
        },
        expectedStep?.prompt || "",
        { timeout: 3000 }
      ).catch(() => {});
    }
    const recovered = await page.evaluate((expectedPrompt) => {
      const surface = document.getElementById("view-child");
      const answer = document.getElementById("childAnswerRaw");
      return {
        learningSurfaceVisible: Boolean(surface && !surface.hidden && !surface.closest("[inert]")),
        answerVisible: Boolean(answer && answer.getClientRects().length > 0),
        answerEnabled: Boolean(answer && !answer.disabled),
        promptVisible: Boolean(expectedPrompt && document.body.innerText.includes(expectedPrompt)),
      };
    }, expectedStep?.prompt || "");
    return {
      pass:
        Boolean(expectedStep?.prompt) && resumeVisible && bootstrapRequestObserved &&
        bootstrapRequests === 1 && pendingState.mapVisible &&
        pendingState.learningHidden && pendingState.learningInert &&
        !pendingState.answerVisible && !pendingState.saveVisible && !pendingState.photoVisible &&
        browserBootstrapPayload?.child_state === "current_step" &&
        browserBootstrapPayload?.current_step?.prompt === expectedStep.prompt &&
        recovered.learningSurfaceVisible && recovered.answerVisible &&
        recovered.answerEnabled && recovered.promptVisible,
      expectedCurrentStep: {
        topic: expectedStep?.topic_label || "",
        prompt: expectedStep?.prompt || "",
      },
      resumeVisible,
      bootstrapRequests,
      bootstrapRequestObserved,
      pendingState,
      returnedChildState: browserBootstrapPayload?.child_state || "",
      returnedPrompt: browserBootstrapPayload?.current_step?.prompt || "",
      recovered,
    };
  } finally {
    releaseBootstrapResponse();
    await context.close();
  }
}

function actionDescriptors(node) {
  const descriptors = node?.action_descriptors;
  return Array.isArray(descriptors) &&
    descriptors.every((item) => item && typeof item === "object")
    ? descriptors
    : [];
}

function descriptorContract(descriptors) {
  return descriptors.length > 0 && descriptors.every((descriptor) =>
    typeof descriptor.action === "string" &&
    typeof descriptor.label === "string" && descriptor.label.trim().length > 0 &&
    ["primary", "secondary"].includes(descriptor.role) &&
    typeof descriptor.enabled === "boolean" &&
    typeof descriptor.pending_label === "string" && descriptor.pending_label.trim().length > 0 &&
    ["enter_now", "wait_for_safe_boundary", "preview"].includes(descriptor.result_behavior) &&
    (descriptor.enabled || (
      typeof descriptor.disabled_reason === "string" &&
      descriptor.disabled_reason.trim().length > 0
    ))
  ) &&
    descriptors.filter((descriptor) => descriptor.role === "primary").length <= 1 &&
    descriptors.filter((descriptor) => descriptor.role === "secondary" && descriptor.enabled).length <= 1;
}

async function renderedActionEvidence(page, node) {
  if (!node?.handle) return { labels: [], disabled: [], primaryLabels: [], reason: "" };
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), node.handle);
  const detail = page.locator("[data-knowledge-detail]");
  await detail.waitFor({ state: "visible" });
  const evidence = await detail.locator(".knowledge-detail-actions").evaluate((actions) => ({
    labels: [...actions.querySelectorAll("button")].map((button) => (button.textContent || "").trim()),
    disabled: [...actions.querySelectorAll("button")].map((button) => Boolean(button.disabled)),
    primaryLabels: [...actions.querySelectorAll("button.primary")].map(
      (button) => (button.textContent || "").trim()
    ),
    reason: actions.querySelector(".knowledge-action-disabled-reason")?.textContent?.trim() || "",
  }));
  await page.keyboard.press("Escape");
  return evidence;
}

async function stateAppropriateActionDescriptorsOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  try {
    const projection = await page.evaluate(() =>
      fetch("/api/knowledge-map").then((response) => response.json())
    );
    const stableNode = projection.nodes.find((node) => node.name === stableNodeName);
    const prerequisiteNode = projection.nodes.find((node) => node.name === prerequisiteNodeName);
    const stableDescriptors = actionDescriptors(stableNode);
    const prerequisiteDescriptors = actionDescriptors(prerequisiteNode);
    const stableLabels = stableDescriptors.map((item) => item.label);
    const prerequisiteLabels = prerequisiteDescriptors.map((item) => item.label);
    const stableRendered = await renderedActionEvidence(page, stableNode);
    const prerequisiteRendered = await renderedActionEvidence(page, prerequisiteNode);
    const stableMatches =
      stableNode?.evidence_state?.code === "stable" &&
      stableNode?.evidence_state?.label === "暂时掌握" &&
      stableNode?.action_readiness?.code === "ready" &&
      stableDescriptors[0]?.action === "challenge" &&
      stableDescriptors[0]?.label === "挑战一下" &&
      stableLabels.includes("复习这个点");
    const prerequisiteMatches =
      ["untested", "developing", "needs_support", "stable"].includes(
        prerequisiteNode?.evidence_state?.code
      ) &&
      prerequisiteNode?.evidence_state?.label !== "需要先准备" &&
      prerequisiteNode?.action_readiness?.code === "needs_prerequisite" &&
      String(prerequisiteNode?.action_readiness?.label || "").includes("需要先准备") &&
      String(prerequisiteNode?.action_readiness?.reason || "").trim().length > 0 &&
      prerequisiteDescriptors[0]?.action === "learn" &&
      prerequisiteDescriptors[0]?.label === "先补准备知识" &&
      (!prerequisiteLabels.includes("先看看这个知识点") ||
        prerequisiteDescriptors.some((item) => item.action === "preview"));
    const renderedMatches =
      stableRendered.labels.join("|") === stableLabels.join("|") &&
      stableRendered.primaryLabels.join("|") ===
        stableDescriptors.filter((item) => item.role === "primary").map((item) => item.label).join("|") &&
      prerequisiteRendered.labels.join("|") === prerequisiteLabels.join("|") &&
      prerequisiteRendered.primaryLabels.join("|") ===
        prerequisiteDescriptors.filter((item) => item.role === "primary").map((item) => item.label).join("|") &&
      !prerequisiteRendered.labels.some((label) =>
        ["做个小检测", "开始学习", "再复习一次"].includes(label)
      );
    return {
      pass:
        descriptorContract(stableDescriptors) &&
        descriptorContract(prerequisiteDescriptors) &&
        stableMatches && prerequisiteMatches && renderedMatches,
      stable: {
        name: stableNode?.name || "",
        evidenceState: stableNode?.evidence_state || null,
        readiness: stableNode?.action_readiness || null,
        legacyAllowedActions: stableNode?.allowed_actions || [],
        descriptors: stableDescriptors,
        rendered: stableRendered,
        stateMatchesActions: stableMatches,
      },
      prerequisite: {
        name: prerequisiteNode?.name || "",
        evidenceState: prerequisiteNode?.evidence_state || null,
        readiness: prerequisiteNode?.action_readiness || null,
        legacyAllowedActions: prerequisiteNode?.allowed_actions || [],
        descriptors: prerequisiteDescriptors,
        rendered: prerequisiteRendered,
        stateMatchesActions: prerequisiteMatches,
      },
      renderedMatches,
    };
  } finally {
    await context.close();
  }
}

async function resumeFailureMobileHeaderOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    await page.route(/\/api\/child-bootstrap(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ message: "fixture bootstrap failure" }),
      });
    });
    const resume = page.getByRole("button", { name: "继续当前学习", exact: true });
    await resume.click();
    const retry = page.getByRole("button", { name: "再试一次", exact: true });
    await retry.waitFor({ state: "visible" });
    return await page.evaluate(() => {
      const header = document.querySelector(".knowledge-home-header");
      const heading = header?.querySelector("h2");
      const currentWrap = header?.querySelector(".knowledge-current-wrap");
      const error = header?.querySelector(".knowledge-resume-error:not([hidden])");
      const map = document.getElementById("view-knowledge-home");
      const learning = document.getElementById("view-child");
      const action = header?.querySelector("[data-resume-learning]");
      const headerRect = header?.getBoundingClientRect();
      const headingRect = heading?.getBoundingClientRect();
      const wrapRect = currentWrap?.getBoundingClientRect();
      const errorRect = error?.getBoundingClientRect();
      const pass = Boolean(
        headerRect && headingRect && wrapRect && errorRect &&
        headingRect.width >= 220 && headingRect.height > 0 &&
        wrapRect.top >= headingRect.bottom - 1 &&
        errorRect.left >= headerRect.left - 1 && errorRect.right <= headerRect.right + 1 &&
        errorRect.width >= headerRect.width - 2 &&
        map && !map.hidden && !map.closest("[inert]") &&
        learning?.hidden && learning?.hasAttribute("inert") &&
        action && !action.disabled &&
        document.documentElement.scrollWidth <= window.innerWidth
      );
      return {
        pass,
        heading: heading?.textContent?.trim() || "",
        headingWidth: headingRect?.width || 0,
        headerWidth: headerRect?.width || 0,
        wrapTop: wrapRect?.top || 0,
        headingBottom: headingRect?.bottom || 0,
        errorWidth: errorRect?.width || 0,
        mapVisible: Boolean(map && !map.hidden && !map.closest("[inert]")),
        learningHidden: Boolean(learning?.hidden),
        learningInert: Boolean(learning?.hasAttribute("inert")),
      };
    });
  } finally {
    await context.close();
  }
}

async function mobileGraphVisibleNameOpensTargetNodeOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    const graph = page.getByRole("radio", { name: "图谱", exact: true });
    const graphRegion = page.getByRole("region", { name: "我的数学知识图谱" });
    await graph.check();
    await settleFrames(page);
    const projection = await page.evaluate(() =>
      fetch("/api/knowledge-map").then((response) => response.json())
    );
    const targetNode = projection.nodes.find((node) => node.name === currentNodeName);
    const reviewedAnchorNames = [
      "数感与估算",
      "等量关系与列式",
      "有理数加减",
      "合并同类项",
      "解一元一次方程基础",
      "一元一次方程应用题",
    ];
    const visibleAnchorEvidence = await graphRegion.evaluate((region, anchorNames) => {
      const regionRect = region.getBoundingClientRect();
      const candidates = [...region.querySelectorAll("*")].filter((element) => {
        const text = (element.textContent || "").trim();
        if (!anchorNames.includes(text)) return false;
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      });
      return candidates.map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          text: (element.textContent || "").trim(),
          fontSize: Number.parseFloat(getComputedStyle(element).fontSize) || 0,
          lineHeight: getComputedStyle(element).lineHeight,
          handle: element.closest("[data-node-handle]")?.getAttribute("data-node-handle") || "",
          fullyVisible:
            rect.left >= regionRect.left + 7 && rect.right <= regionRect.right - 7 &&
            rect.top >= regionRect.top + 7 && rect.bottom <= regionRect.bottom - 7,
        };
      });
    }, reviewedAnchorNames);
    const laneLabelEvidence = await graphRegion.locator(".graph-lane-label").evaluateAll(
      (labels) => labels.map((label) => {
        const rect = label.getBoundingClientRect();
        const fontSize = Number.parseFloat(getComputedStyle(label).fontSize) || 0;
        const scale = label.offsetHeight > 0 ? rect.height / label.offsetHeight : 0;
        return {
          text: (label.textContent || "").trim(),
          actualFontSize: fontSize * scale,
        };
      })
    );
    const ordinaryMarkers = await graphRegion.locator(".graph-overview-marker").evaluateAll(
      (markers) => markers.map((marker) => ({
        tag: marker.tagName,
        ariaHidden: marker.getAttribute("aria-hidden"),
        tabIndex: marker.getAttribute("tabindex"),
        role: marker.getAttribute("role"),
        text: (marker.textContent || "").trim(),
      }))
    );
    const moduleSelect = page.locator("[data-module-select]");
    const emptyModuleLabel = await moduleSelect.locator('option[value=""]').textContent();
    await moduleSelect.selectOption(targetNode?.module_handle || "");
    await settleFrames(page);
    const moduleNode = graphRegion.getByRole("button", {
      name: new RegExp(`^${currentNodeName}，状态：`),
    }).first();
    const moduleNodeEvidence = await moduleNode.evaluate((button) => {
      const rect = button.getBoundingClientRect();
      const label = button.querySelector(".knowledge-node-name") || button;
      return {
        visible: rect.width > 0 && rect.height > 0,
        width: rect.width,
        height: rect.height,
        fontSize: Number.parseFloat(getComputedStyle(label).fontSize) || 0,
        text: (label.textContent || "").trim(),
      };
    }).catch(() => ({ visible: false, width: 0, height: 0, fontSize: 0, text: "" }));
    if (moduleNodeEvidence.visible) await moduleNode.click();
    const detailOpenedByModule = await page.getByRole("heading", {
      name: currentNodeName,
      exact: true,
    }).isVisible().catch(() => false);
    if (detailOpenedByModule) await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "适合窗口", exact: true }).click();
    await settleFrames(page);
    const search = page.locator('#knowledgeSearchInput[placeholder="输入知识名称"]');
    await search.fill(currentNodeName);
    await settleFrames(page);
    const searchResult = graphRegion.getByRole("button", {
      name: new RegExp(`^${currentNodeName}，状态：`),
    }).first();
    const searchResultVisible = await searchResult.isVisible().catch(() => false);
    if (searchResultVisible) await searchResult.click();
    const detailOpenedBySearch = await page.getByRole("heading", {
      name: currentNodeName,
      exact: true,
    }).isVisible().catch(() => false);
    await screenshot(page, "dual-v51-regression-mobile-visible-node-name.png");
    return {
      pass:
        visibleAnchorEvidence.length >= 1 &&
        visibleAnchorEvidence.some((item) => item.text === currentNodeName && item.fontSize >= 13 && item.fullyVisible) &&
        laneLabelEvidence.length > 0 &&
        laneLabelEvidence.every((item) => item.actualFontSize >= 11.9) &&
        ordinaryMarkers.length > 0 && ordinaryMarkers.every((item) =>
          item.tag === "BUTTON" && item.ariaHidden !== "true" &&
          ["-1", "0"].includes(item.tabIndex) && item.role !== "presentation" && item.text === ""
        ) &&
        emptyModuleLabel?.trim() === "选择知识模块" &&
        moduleNodeEvidence.visible && moduleNodeEvidence.fontSize >= 15 &&
        moduleNodeEvidence.width >= 44 && moduleNodeEvidence.height >= 44 &&
        detailOpenedByModule && searchResultVisible && detailOpenedBySearch,
      targetName: currentNodeName,
      reviewedAnchorNames,
      visibleAnchorEvidence,
      laneLabelEvidence,
      ordinaryMarkerSample: ordinaryMarkers.slice(0, 3),
      ordinaryMarkerContract: ordinaryMarkers.length > 0 && ordinaryMarkers.every((item) =>
        item.tag === "BUTTON" && item.ariaHidden !== "true" &&
        ["-1", "0"].includes(item.tabIndex) && item.role !== "presentation" && item.text === ""
      ),
      emptyModuleLabel: emptyModuleLabel?.trim() || "",
      moduleNodeEvidence,
      detailOpenedByModule,
      searchResultVisible,
      detailOpenedBySearch,
      overviewMarkerCount: await graphRegion.locator(".graph-overview-marker").count(),
      fullNodeControlCount: await graphRegion.locator(".graph-node-button").count(),
    };
  } finally {
    await context.close();
  }
}

async function mobileGraphAnchorAndModuleScreenGeometryOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    const graph = page.getByRole("radio", { name: "图谱", exact: true });
    const graphRegion = page.getByRole("region", { name: "我的数学知识图谱" });
    await graph.check();
    await settleFrames(page);
    const geometry = await graphRegion.evaluate((region) => {
      const viewport = region.getBoundingClientRect();
      const world = region.querySelector(".graph-world");
      const matrix = new DOMMatrix(getComputedStyle(world).transform);
      const screenScale = Math.hypot(matrix.a, matrix.b);
      const callouts = [...region.querySelectorAll(".graph-node-button")].map((button) => {
        const rect = button.getBoundingClientRect();
        return {
          text: (button.textContent || "").trim(),
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
          inside:
            rect.left >= viewport.left - 1 && rect.right <= viewport.right + 1 &&
            rect.top >= viewport.top - 1 && rect.bottom <= viewport.bottom + 1,
        };
      });
      const moduleLabels = [...region.querySelectorAll(".graph-lane-label")].map((label) => ({
        text: (label.textContent || "").trim(),
        cssFontSize: Number.parseFloat(getComputedStyle(label).fontSize) || 0,
        actualScreenFontSize:
          (Number.parseFloat(getComputedStyle(label).fontSize) || 0) * screenScale,
        width: label.getBoundingClientRect().width,
        height: label.getBoundingClientRect().height,
      }));
      const calloutsDisjoint = callouts.every((callout, index) =>
        callouts.slice(index + 1).every((other) =>
          callout.right + 3 <= other.left || other.right + 3 <= callout.left ||
          callout.bottom + 3 <= other.top || other.bottom + 3 <= callout.top
        )
      );
      return {
        viewport: {
          left: viewport.left,
          right: viewport.right,
          top: viewport.top,
          bottom: viewport.bottom,
          width: viewport.width,
          height: viewport.height,
        },
        screenScale,
        callouts,
        calloutsDisjoint,
        moduleLabels,
      };
    });
    await screenshot(page, "dual-v51-regression-mobile-graph-geometry.png");
    return {
      pass:
        geometry.callouts.length >= 1 && geometry.callouts.some((item) => item.inside) &&
        geometry.moduleLabels.length > 0 &&
        geometry.moduleLabels.every((item) => item.actualScreenFontSize >= 12),
      ...geometry,
      clippedCallouts: geometry.callouts.filter((item) => !item.inside).map((item) => item.text),
      undersizedModuleLabels: geometry.moduleLabels.filter(
        (item) => item.actualScreenFontSize < 12
      ),
    };
  } finally {
    await context.close();
  }
}

async function resumeFailureLayoutIsReadableOracle() {
  const { context, page } = await freshPage({ width: 390, height: 844 });
  try {
    await page.route(/\/api\/child-bootstrap(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "injected resume failure" }),
      });
    });
    const resume = page.getByRole("button", { name: "继续当前学习", exact: true });
    await resume.click();
    const error = page.locator("[data-resume-error]");
    await error.waitFor({ state: "visible" });
    const layout = await page.locator(".knowledge-home-header").evaluate((header) => {
      const heading = header.querySelector("[data-knowledge-heading]");
      const current = header.querySelector("[data-current-learning]");
      const action = header.querySelector("[data-resume-learning]");
      const errorBlock = header.querySelector("[data-resume-error]");
      const errorText = errorBlock.querySelector("p");
      const retry = errorBlock.querySelector("[data-resume-retry]");
      const rect = (element) => {
        const value = element.getBoundingClientRect();
        return {
          left: value.left,
          right: value.right,
          top: value.top,
          bottom: value.bottom,
          width: value.width,
          height: value.height,
        };
      };
      const headerRect = rect(header);
      const headingRect = rect(heading);
      const currentRect = rect(current);
      const actionRect = rect(action);
      const errorRect = rect(errorBlock);
      const errorTextRect = rect(errorText);
      const retryRect = rect(retry);
      const headingLineHeight = Number.parseFloat(getComputedStyle(heading).lineHeight) || 1;
      return {
        header: headerRect,
        heading: {
          ...headingRect,
          text: (heading.textContent || "").trim(),
          lineCount: headingRect.height / headingLineHeight,
        },
        current: {...currentRect, text: (current.textContent || "").trim()},
        action: actionRect,
        error: errorRect,
        errorText: {...errorTextRect, text: (errorText.textContent || "").trim()},
        retry: retryRect,
        errorOwnRow:
          errorRect.left <= headerRect.left + 2 &&
          errorRect.right >= headerRect.right - 2 &&
          errorRect.top >= Math.max(headingRect.bottom, actionRect.bottom) + 4,
        documentFits: document.documentElement.scrollWidth <= window.innerWidth,
      };
    });
    await screenshot(page, "dual-v51-regression-resume-failure-layout.png");
    return {
      pass:
        layout.heading.width >= 160 && layout.heading.lineCount <= 3 &&
        layout.current.width >= 100 &&
        layout.error.width >= layout.header.width * 0.9 &&
        layout.errorText.width >= layout.error.width - 40 &&
        layout.retry.width >= layout.error.width - 40 &&
        layout.errorOwnRow && layout.documentFits,
      layout,
      errorFocused: await error.evaluate((element) => document.activeElement === element),
      retryVisible: await error.getByRole("button", { name: "再试一次", exact: true }).isVisible(),
    };
  } finally {
    await context.close();
  }
}

async function appliedTargetContinuityOracle() {
  const { context, page } = await freshPage({ width: 1280, height: 800 });
  let selectResult = null;
  let selectRequest = null;
  try {
    page.on("request", (request) => {
      if (request.url().includes("/api/knowledge-map/select")) {
        selectRequest = request.postDataJSON();
      }
    });
    page.on("response", async (response) => {
      if (response.url().includes("/api/knowledge-map/select")) {
        selectResult = await response.json().catch(() => null);
      }
    });
    const projection = await page.evaluate(() =>
      fetch("/api/knowledge-map").then((response) => response.json())
    );
    const target = projection.nodes.find((node) => node.name === stableNodeName);
    const descriptor = target?.action_descriptors?.find((item) => item.enabled);
    if (!target || !descriptor) {
      return { pass: false, error: "continuity target has no enabled descriptor" };
    }
    await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), target.handle);
    await page.getByRole("button", { name: descriptor.label, exact: true }).click();
    await page.waitForFunction(
      (topic) => document.getElementById("childHeading")?.textContent?.trim() === topic &&
        document.getElementById("view-child")?.hidden === false,
      target.name,
      { timeout: 5000 }
    );
    const bootstrap = await page.evaluate(() =>
      fetch("/api/child-bootstrap").then((response) => response.json())
    );
    const pageState = await page.evaluate(() => ({
      heading: document.getElementById("childHeading")?.textContent?.trim() || "",
      learningVisible: document.getElementById("view-child")?.hidden === false,
      mapHidden: document.getElementById("view-knowledge-home")?.hidden === true,
    }));
    await screenshot(page, "dual-v51-regression-applied-target-continuity.png");
    return {
      pass:
        selectRequest?.handle === target.handle &&
        selectRequest?.action === descriptor.action &&
        selectResult?.status === "applied" &&
        selectResult?.result_behavior === "enter_now" &&
        bootstrap?.child_state === "current_step" &&
        bootstrap?.current_step?.topic_label === target.name &&
        pageState.heading === target.name &&
        pageState.learningVisible && pageState.mapHidden,
      target: { name: target.name, handle: target.handle, action: descriptor.action },
      selectRequest,
      selectResult,
      bootstrapTopic: bootstrap?.current_step?.topic_label || "",
      pageState,
    };
  } finally {
    await context.close();
  }
}

try {
  for (const [name, oracle] of [
    ["mobile_sheet_modal_cleanup", mobileSheetCleanupOracle],
    ["invalid_node_focus_recovers_to_fit_all", invalidNodeFocusRecoversToFitAllOracle],
    ["search_selection_restores_context", searchSelectionRestoreOracle],
    ["projection_preference_isolation", projectionPreferenceIsolationOracle],
    ["reinitialize_clears_transient_query_and_filter", reinitializeClearsTransientQueryAndFilterOracle],
    ["allowed_actions_change_invalidates_pending", allowedActionsChangeInvalidatesPendingOracle],
    ["selected_hidden_state_and_escape_focus", selectedHiddenStateAndEscapeFocusOracle],
    ["destination_camera_is_preserved_exactly", destinationCameraIsPreservedExactlyOracle],
    ["applied_focus_enters_learning_step", appliedFocusEntersLearningStepOracle],
    ["mobile_action_feedback_lifecycle", mobileActionFeedbackLifecycleOracle],
    ["resume_requires_fresh_bootstrap_current_step", resumeRequiresFreshBootstrapCurrentStepOracle],
    ["state_appropriate_action_descriptors", stateAppropriateActionDescriptorsOracle],
    ["resume_failure_mobile_header_preserved", resumeFailureMobileHeaderOracle],
    ["mobile_graph_visible_name_opens_target_node", mobileGraphVisibleNameOpensTargetNodeOracle],
    ["mobile_graph_anchor_and_module_screen_geometry", mobileGraphAnchorAndModuleScreenGeometryOracle],
    ["resume_failure_layout_is_readable", resumeFailureLayoutIsReadableOracle],
    ["applied_target_continuity", appliedTargetContinuityOracle],
  ]) {
    try {
      report[name] = await oracle();
    } catch (error) {
      report[name] = { pass: false, error: error?.stack || String(error) };
    }
  }
  process.stdout.write(JSON.stringify({ report, screenshots }));
} finally {
  await browser.close();
}
