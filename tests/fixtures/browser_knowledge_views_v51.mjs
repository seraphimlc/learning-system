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

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();
const report = {};
const screenshots = {};
let desktopOrphanFocusRefit = false;
let mobileOrphanFocusRefit = false;
let desktopCameraRoundTrip = false;
let mobileSheetBaselinePreserved = false;

async function screenshot(name) {
  const target = path.join(evidenceDir, name);
  await page.screenshot({ path: target, fullPage: false });
  screenshots[name] = target;
}

async function graphFullNodesAreStableAndDisjoint(region) {
  const boxes = await region.locator(".graph-node-button").evaluateAll((buttons) =>
    buttons.map((button) => ({
      left: button.offsetLeft,
      top: button.offsetTop,
      width: button.offsetWidth,
      height: button.offsetHeight,
      slot: [
        button.dataset.graphRank,
        button.dataset.graphLaneHandle,
        button.dataset.graphOrder,
        button.dataset.graphSlot,
      ].join(":"),
    }))
  );
  if (!boxes.length || new Set(boxes.map((box) => box.slot)).size !== boxes.length) return false;
  if (!boxes.every((box) => box.width === 148 && box.height === 48)) return false;
  for (let left = 0; left < boxes.length; left += 1) {
    for (let right = left + 1; right < boxes.length; right += 1) {
      const a = boxes[left];
      const b = boxes[right];
      const overlap = !(
        a.left + a.width <= b.left || b.left + b.width <= a.left ||
        a.top + a.height <= b.top || b.top + b.height <= a.top
      );
      if (overlap) return false;
    }
  }
  return true;
}

async function graphOverviewEvidence(region) {
  return region.evaluate((regionElement) => {
    const markers = [...regionElement.querySelectorAll(".graph-overview-marker")];
    const fullNodes = [...regionElement.querySelectorAll(".graph-node-button")];
    const regionRect = markers[0]?.closest(".knowledge-viewport")?.getBoundingClientRect();
    const boxes = markers.map((marker) => {
      const rect = marker.getBoundingClientRect();
      const visualStyle = getComputedStyle(marker, "::before");
      const visualWidth = Number.parseFloat(visualStyle.width) || rect.width;
      const visualHeight = Number.parseFloat(visualStyle.height) || rect.height;
      return {
        left: rect.left + (rect.width - visualWidth) / 2,
        top: rect.top + (rect.height - visualHeight) / 2,
        right: rect.right - (rect.width - visualWidth) / 2,
        bottom: rect.bottom - (rect.height - visualHeight) / 2,
        width: visualWidth,
        height: visualHeight,
        hitWidth: rect.width,
        hitHeight: rect.height,
        label: marker.getAttribute("aria-label") || "",
        title: marker.getAttribute("title") || "",
        selected: marker.getAttribute("aria-pressed"),
        ariaHidden: marker.getAttribute("aria-hidden"),
        tabIndex: marker.getAttribute("tabindex"),
        role: marker.getAttribute("role"),
        text: (marker.textContent || "").trim(),
        tag: marker.tagName,
      };
    });
    const calloutBoxes = fullNodes.map((button) => {
      const rect = button.getBoundingClientRect();
      return {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
        text: (button.textContent || "").trim(),
        label: button.getAttribute("aria-label") || "",
      };
    });
    let disjoint = true;
    for (let left = 0; left < boxes.length; left += 1) {
      for (let right = left + 1; right < boxes.length; right += 1) {
        const a = boxes[left];
        const b = boxes[right];
        if (!(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)) {
          disjoint = false;
        }
      }
    }
    let calloutsDisjoint = true;
    for (let left = 0; left < calloutBoxes.length; left += 1) {
      for (let right = left + 1; right < calloutBoxes.length; right += 1) {
        const a = calloutBoxes[left];
        const b = calloutBoxes[right];
        if (!(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)) {
          calloutsDisjoint = false;
        }
      }
    }
    return {
      count: boxes.length,
      fullCount: calloutBoxes.length,
      totalCount: boxes.length + calloutBoxes.length,
      disjoint,
      calloutsDisjoint,
      readableCallouts: calloutBoxes.length > 0 &&
        calloutBoxes.every((box) => box.width >= 80 && box.height >= 34 && box.text && box.label),
      readableSize: boxes.every((box) => box.width >= 18 && box.height >= 18 && box.width <= 36 && box.height <= 36),
      hitSize: boxes.every((box) => box.hitWidth >= 44 && box.hitHeight >= 44),
      inside: Boolean(regionRect) && boxes.every((box) =>
        box.left >= regionRect.left - 1 && box.right <= regionRect.right + 1 &&
        box.top >= regionRect.top - 1 && box.bottom <= regionRect.bottom + 1
      ),
      semantics: boxes.every((box) =>
        box.tag === "BUTTON" && box.ariaHidden !== "true" &&
        box.role !== "presentation" && box.label && box.title && box.text === ""
      ),
    };
  });
}

async function selectedNodeIsInside(region, handle) {
  const regionBox = await region.boundingBox();
  const nodeBox = await region.locator(`[data-node-handle="${handle}"]`).boundingBox();
  return Boolean(regionBox && nodeBox) &&
    nodeBox.x >= regionBox.x && nodeBox.y >= regionBox.y &&
    nodeBox.x + nodeBox.width <= regionBox.x + regionBox.width &&
    nodeBox.y + nodeBox.height <= regionBox.y + regionBox.height;
}

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });

  const switcher = page.getByRole("radiogroup", { name: "知识展示方式" });
  const mindMap = page.getByRole("radio", { name: "导图", exact: true });
  const graph = page.getByRole("radio", { name: "图谱", exact: true });
  const mindRegion = page.getByRole("region", { name: "我的数学知识导图" });
  const graphRegion = page.getByRole("region", { name: "我的数学知识图谱" });
  await switcher.waitFor();

  const projection = await page.evaluate(async () => {
    const response = await fetch("/api/knowledge-map");
    if (!response.ok) throw new Error(`knowledge-map status ${response.status}`);
    return response.json();
  });
  const prefix = `son-ai-knowledge-views:v5.1:${projection.projection_version}`;
  const activeViewKey = "son-ai-knowledge-views:v5.1:active-view";

  report.knowledge_projection_sets_connection_ready =
    (await page.locator("#dbStatus").textContent()) === "准备好了";
  report.not_started_hides_resume_learning =
    projection.current_learning?.state === "not_started" &&
    await page.getByRole("button", { name: "继续当前学习", exact: true }).isHidden();
  report.first_visit_mind_map = await mindMap.isChecked();
  report.desktop_1280_no_horizontal_scroll = await page.evaluate(
    () => window.innerWidth === 1280 && document.documentElement.scrollWidth <= window.innerWidth
  );
  const moduleToggles = mindRegion.locator(".mind-module-toggle");
  report.mind_virtual_root_and_nine_modules_collapsed =
    (await mindRegion.locator(".mind-virtual-root").count()) === 1 &&
    (await moduleToggles.count()) === 9 &&
    (await moduleToggles.evaluateAll((items) => items.every((item) => item.getAttribute("aria-expanded") === "false")));
  const virtualRoot = mindRegion.locator(".mind-virtual-root");
  const rootInitial = {
    expanded: await virtualRoot.getAttribute("aria-expanded"),
    label: await virtualRoot.getAttribute("aria-label"),
  };
  await moduleToggles.first().click();
  const rootPartial = {
    expanded: await virtualRoot.getAttribute("aria-expanded"),
    label: await virtualRoot.getAttribute("aria-label"),
    state: await virtualRoot.getAttribute("data-expansion-state"),
  };
  await virtualRoot.click();
  report.mind_root_aria_matches_partial_expansion =
    rootInitial.expanded === "false" && rootInitial.label === "展开全部知识模块" &&
    rootPartial.expanded === "true" && rootPartial.label === "折叠全部知识模块" &&
    rootPartial.state === "partial" &&
    (await moduleToggles.evaluateAll((items) => items.every((item) => item.getAttribute("aria-expanded") === "false")));
  await screenshot("dual-v51-1280-mind-fit.png");

  await graph.check();
  await page.waitForTimeout(220);
  const firstGraphOverview = await graphOverviewEvidence(graphRegion);
  const firstGraphWorldTransform = await graphRegion.locator(".graph-world").evaluate(
    (element) => element.style.transform
  );
  report.graph_overview_markers_readable_selectable =
    firstGraphOverview.totalCount === 56 &&
    firstGraphOverview.fullCount >= 6 &&
    firstGraphOverview.count > 0 &&
    firstGraphOverview.disjoint && firstGraphOverview.calloutsDisjoint &&
    firstGraphOverview.readableCallouts &&
    firstGraphOverview.readableSize && firstGraphOverview.hitSize && firstGraphOverview.semantics;
  report.graph_first_entry_auto_fit =
    firstGraphOverview.inside && /translate\([^)]*\) scale\((?!1\))/.test(firstGraphWorldTransform);
  await mindMap.check();

  await page.evaluate((keyPrefix) => {
    localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "graph");
    localStorage.setItem(`${keyPrefix}:active-view`, "graph");
    localStorage.setItem(`${keyPrefix}:mind_map:viewport`, JSON.stringify({ scale: 1.1, x: 11, y: 12 }));
    localStorage.setItem(`${keyPrefix}:graph:viewport`, JSON.stringify({ scale: 0.9, x: 21, y: 22 }));
  }, prefix);
  await page.reload({ waitUntil: "networkidle" });
  report.valid_preference_restored = await graph.isChecked();
  const beforeViewports = await page.evaluate((keyPrefix) => ({
    mindMap: localStorage.getItem(`${keyPrefix}:mind_map:viewport`),
    graph: localStorage.getItem(`${keyPrefix}:graph:viewport`),
  }), prefix);
  await mindMap.check();
  await graph.check();
  const afterViewports = await page.evaluate((keyPrefix) => ({
    mindMap: localStorage.getItem(`${keyPrefix}:mind_map:viewport`),
    graph: localStorage.getItem(`${keyPrefix}:graph:viewport`),
  }), prefix);
  report.independent_viewports_preserved =
    beforeViewports.mindMap !== beforeViewports.graph &&
    beforeViewports.mindMap === afterViewports.mindMap &&
    beforeViewports.graph === afterViewports.graph;

  await mindMap.check();
  const firstModuleToggle = mindRegion.locator(".mind-module-toggle").first();
  if ((await firstModuleToggle.getAttribute("aria-expanded")) === "false") await firstModuleToggle.click();
  const mindAccessibilitySnapshot = await mindRegion.ariaSnapshot();
  report.mind_accessibility_snapshot_uses_disclosures =
    !mindAccessibilitySnapshot.includes("treeitem") &&
    (await mindRegion.locator("[role='treeitem'], [aria-selected]").count()) === 0 &&
    (await mindRegion.locator(".mind-module-toggle[aria-controls]").count()) === 9 &&
    (await mindRegion.locator(".knowledge-node-button[aria-pressed]").count()) > 0;
  const firstNode = mindRegion.locator(".knowledge-node-button:visible").first();
  const selectedHandle = await firstNode.getAttribute("data-node-handle");
  const selectedNode = projection.nodes.find((node) => node.handle === selectedHandle);
  const selectedName = selectedNode?.name || "";
  assert(selectedName && selectedHandle, "selected node lineage is missing");
  const stateEncoding = await firstNode.evaluate((button) => {
    const style = getComputedStyle(button);
    return {
      stateClass: [...button.classList].some((name) => name.startsWith("state-")),
      icon: Boolean(button.querySelector(".knowledge-state-icon")?.textContent?.trim()),
      text: button.querySelector(".knowledge-node-state")?.textContent?.trim() || "",
      aria: button.getAttribute("aria-label") || "",
      border: style.borderLeftStyle !== "none" && style.borderLeftColor !== "rgba(0, 0, 0, 0)",
      color: style.backgroundColor !== "rgba(0, 0, 0, 0)",
    };
  });
  report.status_text_icon_shape_color =
    stateEncoding.stateClass && stateEncoding.icon && stateEncoding.border && stateEncoding.color &&
    stateEncoding.text === selectedNode.learning_state_label &&
    stateEncoding.aria.includes(selectedNode.name) && stateEncoding.aria.includes(selectedNode.learning_state_label);

  const desktopMindBox = await mindRegion.boundingBox();
  await firstNode.click();
  const desktopDetail = page.locator("[data-knowledge-detail]");
  const desktopDetailBox = await desktopDetail.boundingBox();
  const desktopContentBox = await page.locator("[data-knowledge-content]").boundingBox();
  report.desktop_detail_320_in_flow =
    Boolean(desktopDetailBox && desktopContentBox) &&
    Math.abs(desktopDetailBox.width - 320) <= 2 &&
    desktopContentBox.x + desktopContentBox.width <= desktopDetailBox.x + 1 &&
    (await desktopDetail.getAttribute("role")) === "complementary";
  await page.keyboard.press("Escape");
  report.escape_restores_origin_focus =
    (await page.locator(":focus").getAttribute("data-node-handle")) === selectedHandle;

  const crossLinks = projection.views.mind_map.cross_links;
  assert(crossLinks.length === 57, `expected 57 mind-map cross links, got ${crossLinks.length}`);
  const crossTarget = crossLinks[0].target_handle;
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), crossTarget);
  await page.keyboard.press("Escape");
  const crossDetails = mindRegion.locator(".mind-cross-prerequisites");
  await crossDetails.evaluate((element) => { element.open = false; });
  await crossDetails.locator("summary").click();
  await crossDetails.locator(".mind-cross-path").first().waitFor();
  const crossRows = crossDetails.locator("[data-cross-link]");
  const desktopCrossEvidence = {
    total: Number(await mindRegion.locator(".mind-map-world").getAttribute("data-cross-link-count")),
    rows: await crossRows.count(),
    duplicateButtons: await crossDetails.locator(".knowledge-node-button").count(),
    expanded: await crossDetails.evaluate((element) => element.open),
    ariaExpanded: await crossDetails.locator("summary").getAttribute("aria-expanded"),
    text: await crossRows.first().textContent(),
    border: await crossRows.first().locator(".mind-cross-direction").evaluate(
      (element) => getComputedStyle(element).borderTopStyle
    ),
    paths: await crossDetails.locator(".mind-cross-path").count(),
    dashedPaths: await crossDetails.locator(".mind-cross-path").evaluateAll(
      (paths) => paths.every((item) => getComputedStyle(item).strokeDasharray !== "none" && item.hasAttribute("marker-end"))
    ),
  };
  report.mind_cross_prerequisites_57_directional_no_duplicate_buttons =
    desktopCrossEvidence.total === 57 &&
    desktopCrossEvidence.rows >= 1 &&
    desktopCrossEvidence.duplicateButtons === 0 &&
    desktopCrossEvidence.expanded &&
    desktopCrossEvidence.ariaExpanded === "true" &&
    desktopCrossEvidence.text.includes("严格前置") &&
    desktopCrossEvidence.border === "dashed" &&
    desktopCrossEvidence.paths === desktopCrossEvidence.rows &&
    desktopCrossEvidence.dashedPaths;

  await graph.check();
  const crossTargetName = projection.nodes.find((node) => node.handle === crossTarget)?.name || "";
  await page.waitForTimeout(220);
  const sharedSelection = graphRegion.locator(
    `.graph-node-button[data-node-handle="${crossTarget}"]`
  );
  const selectedViewportStored = await page.evaluate((keyPrefix) => {
    const raw = localStorage.getItem(`${keyPrefix}:graph:viewport`);
    return raw ? JSON.parse(raw) : null;
  }, prefix);
  report.selection_shared_across_views =
    Boolean(crossTargetName) &&
    (await sharedSelection.count()) === 1 &&
    (await sharedSelection.getAttribute("aria-pressed")) === "true";
  report.graph_selected_switch_camera_persisted =
    await selectedNodeIsInside(graphRegion, crossTarget) &&
    Boolean(selectedViewportStored && selectedViewportStored.scale > 0) &&
    await graphRegion.evaluate((element) => element.scrollLeft === 0 && element.scrollTop === 0);
  await page.getByRole("button", { name: "放大", exact: true }).click();
  const graphCameraBeforeRoundTrip = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:graph:viewport`), prefix
  );
  await mindMap.check();
  await page.waitForTimeout(220);
  await page.getByRole("button", { name: "放大", exact: true }).click();
  const mindCameraBeforeRoundTrip = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:mind_map:viewport`), prefix
  );
  await graph.check();
  await page.waitForTimeout(220);
  const graphCameraAfterRoundTrip = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:graph:viewport`), prefix
  );
  await mindMap.check();
  await page.waitForTimeout(220);
  const mindCameraAfterRoundTrip = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:mind_map:viewport`), prefix
  );
  desktopCameraRoundTrip =
    Boolean(graphCameraBeforeRoundTrip && mindCameraBeforeRoundTrip) &&
    graphCameraAfterRoundTrip === graphCameraBeforeRoundTrip &&
    mindCameraAfterRoundTrip === mindCameraBeforeRoundTrip;
  await graph.check();
  const degreeByHandle = new Map();
  const incomingByHandle = new Map();
  const outgoingByHandle = new Map();
  projection.relationships.forEach((relation) => {
    degreeByHandle.set(relation.source_handle, (degreeByHandle.get(relation.source_handle) || 0) + 1);
    degreeByHandle.set(relation.target_handle, (degreeByHandle.get(relation.target_handle) || 0) + 1);
    outgoingByHandle.set(relation.source_handle, (outgoingByHandle.get(relation.source_handle) || 0) + 1);
    incomingByHandle.set(relation.target_handle, (incomingByHandle.get(relation.target_handle) || 0) + 1);
  });
  const graphFocusNode = [...projection.nodes].filter(
    (node) => (incomingByHandle.get(node.handle) || 0) > 0 && (outgoingByHandle.get(node.handle) || 0) > 0
  ).sort(
    (left, right) => (degreeByHandle.get(right.handle) || 0) - (degreeByHandle.get(left.handle) || 0)
  )[0] || [...projection.nodes].sort(
    (left, right) => (degreeByHandle.get(right.handle) || 0) - (degreeByHandle.get(left.handle) || 0)
  )[0];
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), graphFocusNode.handle);
  await page.waitForTimeout(220);
  const desktopGraphBox = await graphRegion.boundingBox();
  report.desktop_1280_both_surfaces_render =
    Boolean(desktopMindBox && desktopMindBox.width > 0 && desktopMindBox.height > 0) &&
    Boolean(desktopGraphBox && desktopGraphBox.width > 0 && desktopGraphBox.height > 0);
  const nodeFocusCount = await graphRegion.locator(".graph-node-button").count();
  const nodeFocusMarkerCount = await graphRegion.locator(".graph-overview-marker").count();
  report.graph_node_focus_is_bounded =
    nodeFocusCount >= 1 && nodeFocusCount < 56 &&
    nodeFocusCount + nodeFocusMarkerCount === 56 &&
    await graphFullNodesAreStableAndDisjoint(graphRegion);
  const edgeGeometry = await graphRegion.locator(".graph-edge.is-incoming, .graph-edge.is-outgoing").first().evaluate((line) => {
    const world = line.closest(".graph-world");
    const target = world?.querySelector(`[data-node-handle="${line.dataset.targetHandle}"]`);
    if (!target) return { boundary: false, marker: false };
    const x2 = Number(line.getAttribute("x2"));
    const y2 = Number(line.getAttribute("y2"));
    const centerX = target.offsetLeft + target.offsetWidth / 2;
    const centerY = target.offsetTop + target.offsetHeight / 2;
    const halfWidth = target.offsetWidth / 2;
    const halfHeight = target.offsetHeight / 2;
    const onVertical = Math.abs(Math.abs(x2 - centerX) - halfWidth) <= 1.5 && Math.abs(y2 - centerY) <= halfHeight + 1.5;
    const onHorizontal = Math.abs(Math.abs(y2 - centerY) - halfHeight) <= 1.5 && Math.abs(x2 - centerX) <= halfWidth + 1.5;
    return {
      boundary: (onVertical || onHorizontal) && Math.hypot(x2 - centerX, y2 - centerY) > 2,
      marker: line.hasAttribute("marker-end"),
    };
  });
  report.graph_edge_boundary_and_direction_classes =
    edgeGeometry.boundary && edgeGeometry.marker &&
    (await graphRegion.locator(".graph-edge.is-incoming").count()) > 0 &&
    (await graphRegion.locator(".graph-edge.is-outgoing").count()) > 0 &&
    (await page.locator(".legend-incoming, .legend-outgoing, .legend-bridge").count()) === 3;
  await screenshot("dual-v51-1280-graph-node.png");
  await page.keyboard.press("Escape");

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(220);
  const desktopRefreshOverview = await graphOverviewEvidence(graphRegion);
  desktopOrphanFocusRefit =
    await graph.isChecked() &&
    desktopRefreshOverview.totalCount === 56 &&
    desktopRefreshOverview.fullCount >= 6;

  await page.getByRole("button", { name: "适合窗口", exact: true }).click();
  await page.waitForTimeout(220);
  const fitOverview = await graphOverviewEvidence(graphRegion);
  const fitEdgeCount = await graphRegion.locator(
    '.graph-edge[data-relation="strict-prerequisite"][marker-end]'
  ).count();
  report.graph_fit_all_readable_controls_zero_collision =
    fitOverview.totalCount === 56 &&
    fitOverview.fullCount >= 6 &&
    fitOverview.count > 0 &&
    fitOverview.disjoint && fitOverview.calloutsDisjoint &&
    fitOverview.readableCallouts && fitOverview.readableSize &&
    fitOverview.hitSize && fitOverview.inside;
  const overviewEdgeGeometry = await graphRegion.locator(".graph-edge").first().evaluate((line) => {
    const world = line.closest(".graph-world");
    const target = world?.querySelector(`[data-node-handle="${line.dataset.targetHandle}"]`);
    if (!world || !target) return { boundary: false, reason: "missing_target" };
    const screenMatrix = line.getScreenCTM();
    if (!screenMatrix) return { boundary: false, reason: "missing_screen_matrix" };
    const endpoint = new DOMPoint(
      Number(line.getAttribute("x2")),
      Number(line.getAttribute("y2"))
    ).matrixTransform(screenMatrix);
    const endX = endpoint.x;
    const endY = endpoint.y;
    const targetRect = target.getBoundingClientRect();
    const visualStyle = getComputedStyle(target, "::before");
    const visualWidth = Number.parseFloat(visualStyle.width) || targetRect.width;
    const visualHeight = Number.parseFloat(visualStyle.height) || targetRect.height;
    const centerX = targetRect.left + targetRect.width / 2;
    const centerY = targetRect.top + targetRect.height / 2;
    const source = world.querySelector(`[data-node-handle="${line.dataset.sourceHandle}"]`);
    const sourceRect = source?.getBoundingClientRect();
    const sourceCenterX = sourceRect ? sourceRect.left + sourceRect.width / 2 : 0;
    const sourceCenterY = sourceRect ? sourceRect.top + sourceRect.height / 2 : 0;
    const dx = sourceCenterX - centerX;
    const dy = sourceCenterY - centerY;
    const denominator = Math.max(
      Math.abs(dx) / (visualWidth / 2),
      Math.abs(dy) / (visualHeight / 2),
      1
    );
    const expectedX = centerX + dx / denominator;
    const expectedY = centerY + dy / denominator;
    const expectedUserPoint = new DOMPoint(expectedX, expectedY).matrixTransform(screenMatrix.inverse());
    const onVertical = Math.abs(Math.abs(endX - centerX) - visualWidth / 2) <= 2 &&
      Math.abs(endY - centerY) <= visualHeight / 2 + 2;
    const onHorizontal = Math.abs(Math.abs(endY - centerY) - visualHeight / 2) <= 2 &&
      Math.abs(endX - centerX) <= visualWidth / 2 + 2;
    return {
      boundary: onVertical || onHorizontal,
      endX,
      endY,
      centerX,
      centerY,
      visualWidth,
      visualHeight,
      sourceCenterX,
      sourceCenterY,
      centerDistance: Math.hypot(dx, dy),
      expectedX,
      expectedY,
      currentUserX: Number(line.getAttribute("x2")),
      currentUserY: Number(line.getAttribute("y2")),
      expectedUserX: expectedUserPoint.x,
      expectedUserY: expectedUserPoint.y,
      screenMatrixA: screenMatrix.a,
      screenMatrixD: screenMatrix.d,
      horizontalDelta: Math.abs(Math.abs(endX - centerX) - visualWidth / 2),
      verticalDelta: Math.abs(Math.abs(endY - centerY) - visualHeight / 2),
    };
  });
  report.graph_overview_edge_geometry = overviewEdgeGeometry;
  report.graph_overview_hit_target_and_screen_boundary =
    fitOverview.hitSize && overviewEdgeGeometry.boundary;
  report.edge_direction_strict_and_bridge_visible =
    fitEdgeCount > 0 && fitEdgeCount <= 56 &&
    (await graphRegion.locator('.graph-edge[data-overview-visible="false"]').count()) === 0 &&
    (await graphRegion.locator(".graph-edge.is-bridge").count()) > 0;
  report.graph_not_nine_module_boxes =
    (await page.locator('[data-graph-module-box], .graph-module-card, .graph-module-grid, .graph-module-summary').count()) === 0;
  await screenshot("dual-v51-1280-graph-fit.png");

  const moduleSelect = page.locator("[data-module-select]");
  const moduleCounts = new Map();
  projection.nodes.forEach((node) => {
    moduleCounts.set(node.module_handle, (moduleCounts.get(node.module_handle) || 0) + 1);
  });
  const focusModule = [...projection.modules].sort(
    (left, right) => (moduleCounts.get(right.handle) || 0) - (moduleCounts.get(left.handle) || 0)
  )[0];
  await moduleSelect.selectOption(focusModule.handle);
  await page.waitForTimeout(220);
  const moduleFocusCount = await graphRegion.locator(".graph-node-button").count();
  const moduleContextCount = await graphRegion.locator(".graph-overview-marker").count();
  report.graph_module_focus_is_bounded =
    moduleFocusCount >= (moduleCounts.get(focusModule.handle) || 0) && moduleFocusCount < 56 &&
    moduleFocusCount + moduleContextCount === 56 && moduleContextCount > 0 &&
    await graphFullNodesAreStableAndDisjoint(graphRegion);

  await mindMap.check();
  await moduleSelect.selectOption("");
  await page.getByRole("button", { name: "适合窗口", exact: true }).click();
  await page.waitForTimeout(220);
  const search = page.getByRole("search").getByRole("searchbox");
  await search.fill("数");
  report.search_results_max_six =
    (await mindRegion.locator(".mind-search-results .knowledge-node-button").count()) <= 6;
  report.search_accessibility_exposes_only_results =
    (await mindRegion.locator(".knowledge-node-button").count()) <= 6 &&
    (await mindRegion.locator('.knowledge-node-button:disabled, .knowledge-node-button[aria-hidden="true"]').count()) === 0;
  await search.fill("没有这个知识点");
  const clearConditions = page.getByRole("button", { name: "清除条件", exact: true });
  await clearConditions.waitFor();
  await clearConditions.click();
  report.empty_result_can_clear = (await search.inputValue()) === "";

  const searchTargetNode = projection.nodes.find((node) => node.handle === crossTarget);
  assert(searchTargetNode, "cross-prerequisite search target is missing");
  await search.fill(searchTargetNode.name);
  const searchTargetButton = mindRegion.locator(
    `.mind-search-results .knowledge-node-button[data-node-handle="${crossTarget}"]`
  );
  await searchTargetButton.click();
  await page.locator("[data-clear-search]").click();
  await page.waitForTimeout(220);
  const restoredTargetBox = await mindRegion.locator(
    `.knowledge-node-button[data-node-handle="${crossTarget}"]`
  ).boundingBox();
  const restoredViewportBox = await mindRegion.boundingBox();
  const restoredCrossDetails = mindRegion.locator(".mind-cross-prerequisites");
  const restoredCrossPath = restoredCrossDetails.locator(".mind-cross-path").first();
  const restoredCrossPathCount = await restoredCrossPath.count();
  const crossPathInsideViewport = restoredCrossPathCount > 0 && await restoredCrossPath.evaluate((pathElement) => {
    const viewport = pathElement.closest(".knowledge-viewport");
    const matrix = pathElement.getScreenCTM();
    if (!viewport || !matrix) return false;
    const viewportRect = viewport.getBoundingClientRect();
    const start = pathElement.getPointAtLength(0).matrixTransform(matrix);
    const end = pathElement.getPointAtLength(pathElement.getTotalLength()).matrixTransform(matrix);
    const inside = (point) =>
      point.x >= viewportRect.left - 2 && point.x <= viewportRect.right + 2 &&
      point.y >= viewportRect.top - 2 && point.y <= viewportRect.bottom + 2;
    return inside(start) && inside(end);
  });
  const targetNearViewportCenter = Boolean(restoredTargetBox && restoredViewportBox) &&
    Math.abs(
      restoredTargetBox.x + restoredTargetBox.width / 2 -
      (restoredViewportBox.x + restoredViewportBox.width / 2)
    ) <= restoredViewportBox.width * 0.4 &&
    Math.abs(
      restoredTargetBox.y + restoredTargetBox.height / 2 -
      (restoredViewportBox.y + restoredViewportBox.height / 2)
    ) <= restoredViewportBox.height * 0.4;
  const restoredTargetInside = await selectedNodeIsInside(mindRegion, crossTarget);
  const restoredDetailsOpen = await restoredCrossDetails.evaluate((element) => element.open);
  const restoredPathCount = await restoredCrossDetails.locator(".mind-cross-path").count();
  report.search_clear_context_geometry = {
    restoredTargetInside,
    targetNearViewportCenter,
    restoredDetailsOpen,
    restoredPathCount,
    crossPathInsideViewport,
    targetBox: restoredTargetBox,
    viewportBox: restoredViewportBox,
  };
  report.search_clear_preserves_selected_spatial_context =
    restoredTargetInside && targetNearViewportCenter && restoredDetailsOpen &&
    restoredPathCount > 0 && crossPathInsideViewport;
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "适合窗口", exact: true }).click();
  await page.waitForTimeout(220);

  const filterSelectionNode = projection.nodes.find((node) => node.learning_state === "untested") || projection.nodes[0];
  const hidingFilter = filterSelectionNode.learning_state === "untested" ? "recorded" : "untested";
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), filterSelectionNode.handle);
  const stateFilter = page.locator("[data-knowledge-filter]");
  await stateFilter.selectOption(hidingFilter);
  await page.waitForTimeout(100);
  const filteredSelectedButton = mindRegion.locator(
    `.knowledge-node-button[data-node-handle="${filterSelectionNode.handle}"]`
  );
  const filterPreservedSelection = await filteredSelectedButton.isVisible().catch(() => false);
  await stateFilter.selectOption("all");
  await page.waitForTimeout(100);
  const selectedModule = projection.modules.find(
    (module) => module.handle === filterSelectionNode.module_handle
  );
  const selectedModuleToggle = mindRegion.locator(".mind-module-toggle", { hasText: selectedModule.name });
  if ((await selectedModuleToggle.getAttribute("aria-expanded")) === "false") {
    await selectedModuleToggle.evaluate((button) => button.click());
  }
  await selectedModuleToggle.evaluate((button) => button.click());
  const collapsePreservedSelection =
    (await selectedModuleToggle.getAttribute("aria-expanded")) === "true" &&
    await filteredSelectedButton.isVisible().catch(() => false);
  if ((await selectedModuleToggle.getAttribute("aria-expanded")) === "false") {
    await selectedModuleToggle.evaluate((button) => button.click());
  }
  await filteredSelectedButton.evaluate((button) => button.setAttribute("inert", ""));
  await page.keyboard.press("Escape");
  const invalidRestoreFocusedHeading = await page.locator("[data-knowledge-heading]").evaluate(
    (heading) => document.activeElement === heading
  );
  await filteredSelectedButton.evaluate((button) => button.removeAttribute("inert"));
  report.selection_filter_collapse_and_focus_recovery =
    filterPreservedSelection && collapsePreservedSelection && invalidRestoreFocusedHeading;

  const childByParent = new Map();
  const placementByHandle = new Map();
  for (const placement of projection.views.mind_map.placements) {
    placementByHandle.set(placement.handle, placement);
    const bucket = childByParent.get(placement.parent_handle) || [];
    bucket.push(placement.handle);
    childByParent.set(placement.parent_handle, bucket);
  }
  const collapsedPlacement = projection.views.mind_map.placements.find(
    (placement) => placement.collapsed_by_default && (childByParent.get(placement.handle) || []).length > 0
  );
  assert(collapsedPlacement, "no node-level collapsed branch fixture exists");
  const collapsedNode = projection.nodes.find((node) => node.handle === collapsedPlacement.handle);
  const collapsedChild = projection.nodes.find(
    (node) => node.handle === childByParent.get(collapsedPlacement.handle)[0]
  );
  const collapsedModule = projection.modules.find((module) => module.handle === collapsedNode.module_handle);
  const collapsedModuleToggle = mindRegion.locator(".mind-module-toggle", { hasText: collapsedModule.name });
  if ((await collapsedModuleToggle.getAttribute("aria-expanded")) === "false") await collapsedModuleToggle.click();
  const ancestors = [];
  let parentPlacement = collapsedPlacement;
  while (parentPlacement?.parent_type === "node") {
    const parentNode = projection.nodes.find((node) => node.handle === parentPlacement.parent_handle);
    if (!parentNode) break;
    ancestors.unshift(parentNode);
    parentPlacement = placementByHandle.get(parentPlacement.parent_handle);
  }
  for (const ancestor of ancestors) {
    const expand = mindRegion.getByRole("button", { name: `展开 ${ancestor.name} 的分支`, exact: true });
    if (await expand.count()) await expand.click();
  }
  const branchToggle = mindRegion.getByRole("button", {
    name: `展开 ${collapsedNode.name} 的分支`,
    exact: true,
  });
  const hiddenChild = mindRegion.locator(
    `.knowledge-node-button[data-node-handle="${collapsedChild.handle}"]`
  );
  report.node_default_collapse_and_hidden_focus =
    (await branchToggle.getAttribute("aria-expanded")) === "false" &&
    !(await hiddenChild.isVisible()) &&
    (await hiddenChild.getAttribute("tabindex")) === "-1" &&
    (await hiddenChild.evaluate((element) => {
      element.focus();
      return document.activeElement !== element;
    }));

  const visibleNodes = mindRegion.locator(".knowledge-node-button:visible");
  const rovingCount = await visibleNodes.evaluateAll(
    (buttons) => buttons.filter((button) => button.tabIndex === 0).length
  );
  const firstRoving = mindRegion.locator('.knowledge-node-button:visible[tabindex="0"]').first();
  await firstRoving.focus();
  const beforeArrowHandle = await firstRoving.getAttribute("data-node-handle");
  await page.keyboard.press("ArrowDown");
  const afterArrowHandle = await page.evaluate(() => document.activeElement?.getAttribute("data-node-handle") || "");
  report.roving_tabindex_and_direction_keys =
    rovingCount === 1 && beforeArrowHandle && afterArrowHandle && beforeArrowHandle !== afterArrowHandle;

  const disabledNode = projection.nodes.find(
    (node) => Array.isArray(node.action_descriptors) &&
      node.action_descriptors.some((descriptor) => descriptor?.enabled === false)
  );
  assert(disabledNode, "no disabled-action node fixture exists");
  const disabledDescriptor = disabledNode.action_descriptors.find(
    (descriptor) => descriptor?.enabled === false
  );
  await graph.check();
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), disabledNode.handle);
  const disabledDetail = page.locator("[data-knowledge-detail]");
  const disabledPrimary = disabledDetail.getByRole("button", {
    name: disabledDescriptor.label,
    exact: true,
  });
  report.disabled_node_has_button_and_specific_reason =
    (await disabledPrimary.count()) === 1 && await disabledPrimary.isDisabled() &&
    (await disabledDetail.locator(".knowledge-action-disabled-reason").textContent()).trim() ===
      disabledDescriptor.disabled_reason;
  await page.keyboard.press("Escape");

  const actionableNodes = projection.nodes.filter(
    (node) => Array.isArray(node.action_descriptors) &&
      node.action_descriptors.some((descriptor) => descriptor?.enabled === true)
  );
  assert(actionableNodes.length >= 2, "two authoritative target action fixtures are required");
  const [actionableNode, secondActionableNode] = actionableNodes;
  const actionableDescriptor = actionableNode.action_descriptors.find(
    (descriptor) => descriptor?.enabled === true
  );
  const secondActionableDescriptor = secondActionableNode.action_descriptors.find(
    (descriptor) => descriptor?.enabled === true
  );
  const actionName = actionableDescriptor.label;
  const secondActionName = secondActionableDescriptor.label;

  let staleRequestCount = 0;
  await page.route("**/api/knowledge-map/select", async (route) => {
    staleRequestCount += 1;
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ state: "stale", message: "projection changed" }),
    });
  });
  await graph.check();
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), actionableNode.handle);
  await page.getByRole("button", { name: actionName, exact: true }).click();
  const stalePanel = page.locator("[data-map-state-panel]");
  await stalePanel.waitFor();
  const stalePending = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:target-action`), prefix
  );
  const staleRetry = stalePanel.getByRole("button", { name: "重新加载", exact: true });
  const staleBeforeReload =
    (await page.locator("[data-knowledge-content]").getAttribute("data-map-state")) === "stale" &&
    stalePending === null && staleRequestCount === 1 && await staleRetry.isVisible();
  await page.unroute("**/api/knowledge-map/select");
  await staleRetry.click();
  await page.waitForFunction(() =>
    document.querySelector("[data-knowledge-content]")?.dataset.mapState === "ready"
  );
  report.target_action_409_stale_clears_and_reloads =
    staleBeforeReload &&
    (await page.locator("[data-knowledge-content]").getAttribute("data-map-state")) === "ready";

  const actionRequests = [];
  let actionCall = 0;
  let releaseDelayedResponse;
  let markDelayedRequestSeen;
  const delayedResponse = new Promise((resolve) => { releaseDelayedResponse = resolve; });
  const delayedRequestSeen = new Promise((resolve) => { markDelayedRequestSeen = resolve; });
  await page.route("**/api/knowledge-map/select", async (route) => {
    const request = JSON.parse(route.request().postData() || "{}");
    actionRequests.push(request);
    actionCall += 1;
    if (actionCall === 1) {
      markDelayedRequestSeen();
      await delayedResponse;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "applied",
          message: "delayed mismatched response",
          client_idempotency_key: "wrong-response-key",
        }),
      });
      return;
    }
    if (actionCall === 2) {
      await route.abort("failed");
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "applied",
        result_behavior: "enter_now",
        message: "applied after exact retry",
      }),
    });
  });
  await graph.check();
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), actionableNode.handle);
  const targetAction = page.getByRole("button", { name: actionName, exact: true });
  await targetAction.click();
  await delayedRequestSeen;
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), secondActionableNode.handle);
  const secondTargetAction = page.getByRole("button", { name: secondActionName, exact: true });
  const secondNodeBlockedDuringFirstRequest = await secondTargetAction.isDisabled();
  releaseDelayedResponse();
  await page.waitForFunction((keyPrefix) => {
    const raw = localStorage.getItem(`${keyPrefix}:target-action`);
    if (!raw) return false;
    const pending = JSON.parse(raw);
    return pending.status === "response_unknown";
  }, prefix);
  const mismatchDidNotSettle = await page.evaluate((keyPrefix) => {
    const raw = localStorage.getItem(`${keyPrefix}:target-action`);
    const pending = raw ? JSON.parse(raw) : null;
    return Boolean(pending?.client_idempotency_key) &&
      document.getElementById("view-child")?.hidden === true;
  }, prefix);
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), actionableNode.handle);
  const retryAction = page.getByRole("button", { name: actionName, exact: true });
  await retryAction.click();
  await page.waitForFunction(() =>
    document.querySelector("[data-knowledge-live]")?.textContent?.includes("连接中断")
  );
  await retryAction.waitFor({ state: "visible" });
  await retryAction.click();
  await page.waitForFunction(() => document.getElementById("view-child")?.hidden === false);
  const oneRequestLineage = actionRequests.length === 3 &&
    actionRequests.every((request) => request.handle === actionableNode.handle) &&
    actionRequests.every(
      (request) => request.client_idempotency_key === actionRequests[0].client_idempotency_key
    );
  report.target_action_global_serialization_and_exact_settlement =
    secondNodeBlockedDuringFirstRequest && mismatchDidNotSettle && oneRequestLineage;
  report.target_action_key_survives_lost_response =
    oneRequestLineage &&
    Object.keys(actionRequests[0]).sort().join(",") ===
      "action,client_idempotency_key,handle,projection_version" &&
    actionRequests[1].client_idempotency_key === actionRequests[2].client_idempotency_key;
  await page.unroute("**/api/knowledge-map/select");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate((keyPrefix) => {
    localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "mind_map");
    localStorage.setItem(`${keyPrefix}:active-view`, "mind_map");
    localStorage.removeItem(`${keyPrefix}:mind_map:collapsed`);
  }, prefix);
  await page.reload({ waitUntil: "networkidle" });
  report.mobile_390_no_horizontal_scroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );
  const segmentBoxes = await Promise.all([mindMap.boundingBox(), graph.boundingBox()]);
  const zoomBoxes = await page.locator(".knowledge-viewport-tools button").evaluateAll((buttons) =>
    buttons.map((button) => button.getBoundingClientRect().height)
  );
  report.mobile_controls_44px =
    segmentBoxes.every((box) => box && box.height >= 44) &&
    zoomBoxes.length === 4 && zoomBoxes.every((height) => height >= 44);
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), crossTarget);
  await page.keyboard.press("Escape");
  const mobileCross = page.getByRole("region", { name: "我的数学知识导图" }).locator(".mind-cross-prerequisites");
  await mobileCross.evaluate((element) => { element.open = false; });
  await mobileCross.locator("summary").click();
  await mobileCross.locator(".mind-cross-path").first().waitFor();
  const mobileCrossBox = await mobileCross.boundingBox();
  const mobileMindViewportBox = await page.getByRole("region", { name: "我的数学知识导图" }).boundingBox();
  report.mind_cross_prerequisites_390_no_overflow =
    Boolean(mobileCrossBox && mobileMindViewportBox) &&
    mobileCrossBox.x >= mobileMindViewportBox.x &&
    mobileCrossBox.x + mobileCrossBox.width <= mobileMindViewportBox.x + mobileMindViewportBox.width + 1 &&
    (await mobileCross.locator(".mind-cross-path").count()) >= 1;
  await screenshot("dual-v51-390-mind-fit.png");

  await mindMap.check();
  const mobileMindRegion = page.getByRole("region", { name: "我的数学知识导图" });
  const mobileModuleToggle = mobileMindRegion.locator(".mind-module-toggle").first();
  if ((await mobileModuleToggle.getAttribute("aria-expanded")) === "false") await mobileModuleToggle.click();
  const mobileNode = mobileMindRegion.locator(".knowledge-node-button:visible").first();
  const mobileHandle = await mobileNode.getAttribute("data-node-handle");
  const mobileCameraBeforeSheet = await mobileMindRegion.locator(".knowledge-world").evaluate(
    (element) => element.style.transform
  );
  const mobileStoredCameraBeforeSheet = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:mind_map:viewport`), prefix
  );
  await mobileNode.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const dialogBox = await dialog.boundingBox();
  const mobileMindBox = await mobileMindRegion.boundingBox();
  const headerPosition = await dialog.locator(".knowledge-detail-head").evaluate(
    (element) => getComputedStyle(element).position
  );
  const actionPosition = await dialog.locator(".knowledge-detail-actions").evaluate(
    (element) => getComputedStyle(element).position
  );
  report.mobile_detail_modal_and_inert =
    (await dialog.getAttribute("aria-modal")) === "true" &&
    (await page.locator('[inert]').count()) >= 1;
  const closeButton = dialog.getByRole("button", { name: "关闭详情", exact: true });
  const lastDialogButton = dialog.locator("button:not(:disabled)").last();
  await closeButton.focus();
  await page.keyboard.press("Shift+Tab");
  const shiftTabWrapped = await lastDialogButton.evaluate((element) => document.activeElement === element);
  await lastDialogButton.focus();
  await page.keyboard.press("Tab");
  const tabWrapped = await closeButton.evaluate((element) => document.activeElement === element);
  const outsideFocusIsInert = await dialog.evaluate((modal) => {
    const candidates = [...document.querySelectorAll(
      'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])'
    )].filter((element) => !modal.contains(element) && element.getClientRects().length > 0);
    return candidates.length > 0 && candidates.every((element) => Boolean(element.closest("[inert]")));
  });
  report.mobile_modal_focus_trap_and_page_inert =
    shiftTabWrapped && tabWrapped && outsideFocusIsInert;
  await dialog.locator("#knowledgeDetailHeading").focus();
  await page.keyboard.press("Shift+Tab");
  const initialHeadingShiftTabWrapped = await lastDialogButton.evaluate(
    (element) => document.activeElement === element
  );
  await dialog.locator("#knowledgeDetailHeading").focus();
  await page.keyboard.press("Tab");
  const initialHeadingTabWrapped = await closeButton.evaluate(
    (element) => document.activeElement === element
  );
  report.mobile_modal_initial_heading_focus_trapped =
    initialHeadingShiftTabWrapped && initialHeadingTabWrapped;
  const mobileStoredCameraWhileSheetOpen = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:mind_map:viewport`), prefix
  );
  report.mobile_sheet_geometry = {
    dialogY: dialogBox?.y || 0,
    viewportY: mobileMindBox?.y || 0,
    visibleMap: (dialogBox?.y || 0) - (mobileMindBox?.y || 0),
    headerPosition,
    actionPosition,
  };
  report.mobile_sheet_keeps_112px_map_and_sticky_actions =
    Boolean(dialogBox && mobileMindBox) && dialogBox.y >= mobileMindBox.y + 112 &&
    headerPosition === "sticky" && actionPosition === "sticky";
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.waitForTimeout(100);
  await page.keyboard.press("Escape");
  const cameraAfterDesktopEscape = await mobileMindRegion.locator(".knowledge-world").evaluate(
    (element) => element.style.transform
  );
  report.mobile_escape_focus_restore =
    (await page.locator(":focus").getAttribute("data-node-handle")) === mobileHandle;
  report.mobile_sheet_resize_escape_restores_camera =
    cameraAfterDesktopEscape === mobileCameraBeforeSheet &&
    (await page.locator("[data-knowledge-detail]").isHidden());
  const mobileStoredCameraAfterSheet = await page.evaluate((keyPrefix) =>
    localStorage.getItem(`${keyPrefix}:mind_map:viewport`), prefix
  );
  mobileSheetBaselinePreserved =
    Boolean(mobileStoredCameraBeforeSheet) &&
    mobileStoredCameraWhileSheetOpen === mobileStoredCameraBeforeSheet &&
    mobileStoredCameraAfterSheet === mobileStoredCameraBeforeSheet;
  report.camera_roundtrip_and_sheet_baseline_preserved =
    desktopCameraRoundTrip && mobileSheetBaselinePreserved;
  await page.setViewportSize({ width: 390, height: 844 });
  await graph.check();
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), mobileHandle);
  await screenshot("dual-v51-390-graph-node-sheet.png");
  await page.keyboard.press("Escape");

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(220);
  const mobileRefreshOverview = await graphOverviewEvidence(graphRegion);
  mobileOrphanFocusRefit =
    await graph.isChecked() &&
    mobileRefreshOverview.totalCount === 56 &&
    mobileRefreshOverview.fullCount >= 1;
  report.graph_refresh_orphan_node_focus_auto_fits =
    desktopOrphanFocusRefit && mobileOrphanFocusRefit;

  await page.route("**/api/knowledge-map/select", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "applied",
        result_behavior: "enter_now",
        message: "mobile applied target",
      }),
    });
  });
  await mindMap.check();
  await page.evaluate((handle) => window.KnowledgeViews.focusNode(handle), actionableNode.handle);
  const mobileAppliedDialog = page.getByRole("dialog");
  await mobileAppliedDialog.waitFor();
  await mobileAppliedDialog.getByRole("button", { name: actionName, exact: true }).click();
  await page.waitForFunction(() => document.getElementById("view-child")?.hidden === false);
  const modalReleasedForLearning = await page.evaluate(() => {
    const learning = document.getElementById("view-child");
    const detail = document.querySelector("[data-knowledge-detail]");
    return document.querySelectorAll('[role="dialog"], [aria-modal="true"]').length === 0 &&
      Boolean(detail?.hidden) && !detail?.hasAttribute("aria-modal") &&
      Boolean(learning) && !learning.closest("[inert]");
  });
  const knowledgeHomeEntryUsable = await page.locator("#knowledgeHomeBtn").evaluate(
    (button) => !button.closest("[inert]")
  );
  await page.locator("#knowledgeHomeBtn").evaluate((button) => button.click());
  await page.waitForFunction(() => document.getElementById("view-knowledge-home")?.hidden === false);
  const knowledgeHomeUsableAgain = knowledgeHomeEntryUsable && await page.evaluate(() => {
    const mind = document.querySelector('input[name="knowledge-view-mode"][value="mind_map"]');
    return Boolean(mind && !mind.closest("[inert]") && !mind.disabled);
  });
  await page.evaluate((payload) => {
    const resumable = structuredClone(payload);
    resumable.current_learning = {
      state: "current_step",
      topic_label: "当前知识点",
      label: "“当前知识点”还可以继续。",
      action_label: "继续当前学习",
      pending_label: "正在打开",
    };
    window.KnowledgeViews.setProjection(resumable);
  }, projection);
  report.resumable_state_shows_resume_learning =
    await page.getByRole("button", { name: "继续当前学习", exact: true }).isVisible();
  const searchAfterReturn = page.locator("#knowledgeSearchInput");
  await searchAfterReturn.focus();
  await page.keyboard.press("Tab");
  const mapTabMovesNormally = await page.evaluate(() => {
    const active = document.activeElement;
    return Boolean(
      active && active !== document.body && active.id !== "knowledgeSearchInput" &&
      active.closest("#view-knowledge-home") && !active.closest("[inert]")
    );
  });
  report.mobile_applied_action_closes_sheet_and_releases_focus =
    modalReleasedForLearning && knowledgeHomeUsableAgain && mapTabMovesNormally;
  await page.unroute("**/api/knowledge-map/select");
  await page.evaluate((keyPrefix) => {
    localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "mind_map");
    localStorage.setItem(`${keyPrefix}:active-view`, "mind_map");
  }, prefix);
  await page.reload({ waitUntil: "networkidle" });

  await mindMap.check();
  const mobileRegionBox = await mobileMindRegion.boundingBox();
  assert(mobileRegionBox, "mobile mind-map viewport is missing");
  const transformBeforeDrag = await mobileMindRegion.locator(".knowledge-world").evaluate(
    (element) => element.style.transform
  );
  const dragX = mobileRegionBox.x + mobileRegionBox.width - 18;
  const dragY = mobileRegionBox.y + mobileRegionBox.height - 18;
  await page.mouse.move(dragX, dragY);
  await page.mouse.down();
  await page.mouse.move(dragX + 4, dragY + 3);
  await page.mouse.up();
  const transformAfterDrag = await mobileMindRegion.locator(".knowledge-world").evaluate(
    (element) => element.style.transform
  );
  await page.getByRole("button", { name: "放大", exact: true }).click();
  const transformAfterZoom = await mobileMindRegion.locator(".knowledge-world").evaluate(
    (element) => element.style.transform
  );
  report.drag_threshold_and_visible_zoom_control =
    transformBeforeDrag === transformAfterDrag && transformAfterZoom !== transformAfterDrag;

  await page.emulateMedia({ reducedMotion: "reduce" });
  report.reduced_motion_disables_camera_transition =
    (await mobileMindRegion.locator(".knowledge-world").evaluate(
      (element) => getComputedStyle(element).transitionDuration
    )) === "0s";

  await graph.check();
  await page.getByRole("button", { name: "适合窗口", exact: true }).click();
  await page.waitForTimeout(220);
  const mobileOverview = await graphOverviewEvidence(
    page.getByRole("region", { name: "我的数学知识图谱" })
  );
  report.graph_mobile_390_markers_zero_collision =
    mobileOverview.totalCount === 56 &&
    mobileOverview.fullCount >= 1 &&
    mobileOverview.disjoint && mobileOverview.readableCallouts &&
    mobileOverview.readableSize && mobileOverview.semantics;
  await screenshot("dual-v51-390-graph-fit.png");

  const forbidden = /M-(?:G7|BRIDGE|PRIMARY)-|question_id|attempt_id|assessment_id|provider|rubric|queue|job_id|HMAC/i;
  const childSurface = await page.locator("body").evaluate((body) => {
    const attributes = [...body.querySelectorAll("*")]
      .flatMap((element) => [...element.attributes].map((attribute) => `${attribute.name}=${attribute.value}`))
      .join("\n");
    return `${body.innerText}\n${attributes}`;
  });
  report.child_safe_dom = !forbidden.test(childSurface);

  report.target_action_production_response_settles_and_unlocks = await page.evaluate(async (payload) => {
    const root = document.getElementById("knowledgeHomeMount");
    const actionable = payload.nodes.filter(
      (node) => Array.isArray(node.action_descriptors) &&
        node.action_descriptors.some((descriptor) => descriptor?.enabled === true)
    );
    if (!root || actionable.length < 2) return false;
    let responseReturned;
    const responseReturnedPromise = new Promise((resolve) => { responseReturned = resolve; });
    window.KnowledgeViews.initialize({
      root,
      projection: payload,
      initialState: "ready",
      onAction: async () => {
        responseReturned();
        return { status: "blocked", message: "production-shaped terminal response" };
      },
    });
    window.KnowledgeViews.focusNode(actionable[0].handle);
    const firstAction = root.querySelector("[data-action-name]");
    if (!firstAction) return false;
    firstAction.click();
    await responseReturnedPromise;
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const pending = localStorage.getItem(
      `son-ai-knowledge-views:v5.1:${payload.projection_version}:target-action`
    );
    window.KnowledgeViews.focusNode(actionable[1].handle);
    const nextAction = root.querySelector("[data-action-name]");
    return pending === null && Boolean(nextAction) && !nextAction.disabled;
  }, projection);

  report.active_view_preference_survives_projection_upgrade = await page.evaluate(async (payload) => {
    const root = document.getElementById("knowledgeHomeMount");
    if (!root) return false;
    const activeKey = "son-ai-knowledge-views:v5.1:active-view";
    const oldPrefix = `son-ai-knowledge-views:v5.1:${payload.projection_version}`;
    localStorage.setItem(activeKey, "graph");
    localStorage.setItem(`${oldPrefix}:active-view`, "mind_map");
    localStorage.setItem(
      `${oldPrefix}:graph:viewport`,
      JSON.stringify({ scale: 1.6, x: -2200, y: -1600 })
    );
    const upgraded = structuredClone(payload);
    upgraded.projection_version = `${payload.projection_version}:upgrade-fixture`;
    window.KnowledgeViews.initialize({ root, projection: upgraded, initialState: "ready" });
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const upgradedPrefix = `son-ai-knowledge-views:v5.1:${upgraded.projection_version}`;
    const upgradedViewport = localStorage.getItem(`${upgradedPrefix}:graph:viewport`);
    return window.KnowledgeViews.currentView() === "graph" &&
      root.querySelector('input[value="graph"]')?.checked === true &&
      localStorage.getItem(activeKey) === "graph" &&
      upgradedViewport !== localStorage.getItem(`${oldPrefix}:graph:viewport`);
  }, projection);

  report.reinitialize_resets_query_filter_controls = await page.evaluate(async (payload) => {
    const root = document.getElementById("knowledgeHomeMount");
    if (!root) return false;
    localStorage.setItem("son-ai-knowledge-views:v5.1:active-view", "mind_map");
    window.KnowledgeViews.initialize({ root, projection: payload, initialState: "ready" });
    const search = root.querySelector("#knowledgeSearchInput");
    const filter = root.querySelector("[data-knowledge-filter]");
    search.value = "不存在的筛选状态";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    filter.value = "recorded";
    filter.dispatchEvent(new Event("change", { bubbles: true }));
    window.KnowledgeViews.initialize({ root, projection: payload, initialState: "ready" });
    await new Promise((resolve) => requestAnimationFrame(resolve));
    return root.querySelector("#knowledgeSearchInput")?.value === "" &&
      root.querySelector("[data-knowledge-filter]")?.value === "all" &&
      root.querySelectorAll(".knowledge-node-button, .graph-overview-marker").length === 56;
  }, projection);

  report.invalid_pending_action_is_discarded = await page.evaluate(async (payload) => {
    const root = document.getElementById("knowledgeHomeMount");
    const actionable = payload.nodes.filter(
      (node) => Array.isArray(node.action_descriptors) &&
        node.action_descriptors.some((descriptor) => descriptor?.enabled === true)
    );
    if (!root || actionable.length < 2) return false;
    const key = `son-ai-knowledge-views:v5.1:${payload.projection_version}:target-action`;
    const base = {
      handle: actionable[0].handle,
      projection_version: payload.projection_version,
      client_idempotency_key: "tampered-pending-fixture",
    };
    const unlockedAfter = async (pending) => {
      localStorage.setItem(key, JSON.stringify(pending));
      window.KnowledgeViews.initialize({ root, projection: payload, initialState: "ready" });
      window.KnowledgeViews.focusNode(actionable[1].handle);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const action = root.querySelector("[data-action-name]");
      return localStorage.getItem(key) === null && Boolean(action) && !action.disabled;
    };
    const invalidActionCleared = await unlockedAfter({
      ...base,
      action: "not_allowed_action",
      status: "response_unknown",
    });
    const terminalStatusCleared = await unlockedAfter({
      ...base,
      action: actionable[0].action_descriptors.find((descriptor) => descriptor.enabled).action,
      status: "applied",
    });
    return invalidActionCleared && terminalStatusCleared;
  }, projection);

  report.child_safe_surface_states = await page.evaluate(() => {
    const root = document.getElementById("knowledgeHomeMount");
    const states = ["skeleton", "unavailable", "empty", "stale", "disabled"];
    return states.every((initialState) => {
      let retries = 0;
      window.KnowledgeViews.initialize({
        root,
        initialState,
        onRetry: () => { retries += 1; },
      });
      const panel = root.querySelector("[data-map-state-panel]");
      const retry = root.querySelector("[data-map-retry]");
      if (["unavailable", "stale"].includes(initialState)) retry.click();
      const copy = `${panel.querySelector("h3")?.textContent || ""} ${panel.querySelector("p")?.textContent || ""}`;
      const safe = copy.trim() && !/exception|traceback|sqlite|digest|lineage|provider|agent/i.test(copy);
      const retryState = ["unavailable", "stale"].includes(initialState)
        ? (!retry.hidden && retries === 1)
        : retry.hidden;
      return safe && retryState &&
        root.querySelector("[data-knowledge-content]")?.dataset.mapState === initialState;
    });
  });

  report.screenshots_written = Object.values(screenshots).every((target) => fs.statSync(target).size > 0);

  for (const [key, value] of Object.entries(report)) {
    if (typeof value === "boolean") assert(value === true, `${key} failed: ${JSON.stringify(report)}`);
  }
  process.stdout.write(JSON.stringify({ ...report, screenshots }));
} finally {
  await browser.close();
}
