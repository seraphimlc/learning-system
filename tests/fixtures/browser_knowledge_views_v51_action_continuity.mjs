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

const baseUrl = arg("--base-url");
const targetNodeName = arg("--target-node-name");
const targetAction = arg("--target-action");
if (!baseUrl) throw new Error("--base-url is required");
if (!targetNodeName) throw new Error("--target-node-name is required");
if (!targetAction) throw new Error("--target-action is required");

const evidenceDir = path.resolve(
  arg("--evidence-dir") || "tests/evidence/knowledge_views_v51_action_continuity"
);
fs.mkdirSync(evidenceDir, { recursive: true });
const screenshotPath = path.join(evidenceDir, "knowledge-v51-action-target-continuity.png");

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();
let selectExchange = null;
const postSelectBootstraps = [];
let report = { pass: false };

try {
  await page.route(/\/api\/knowledge-map\/select(?:\?.*)?$/, async (route) => {
    const request = route.request();
    let requestPayload = null;
    try {
      requestPayload = request.postDataJSON();
    } catch {
      requestPayload = { raw: request.postData() || "" };
    }
    const response = await route.fetch();
    const responsePayload = await response.json();
    selectExchange = {
      request: requestPayload,
      httpStatus: response.status(),
      response: responsePayload,
    };
    await route.fulfill({
      response,
      contentType: "application/json",
      body: JSON.stringify(responsePayload),
    });
  });

  await page.route(/\/api\/child-bootstrap(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    const responsePayload = await response.json();
    if (selectExchange) postSelectBootstraps.push(responsePayload);
    await route.fulfill({
      response,
      contentType: "application/json",
      body: JSON.stringify(responsePayload),
    });
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });

  const projection = await page.evaluate(() =>
    fetch("/api/knowledge-map").then((response) => response.json())
  );
  const targetNode = projection.nodes.find((node) => node.name === targetNodeName);
  const descriptor = targetNode?.action_descriptors?.find(
    (item) => item.action === targetAction && item.enabled &&
      item.result_behavior === "enter_now"
  );
  if (!targetNode) throw new Error(`target node not found: ${targetNodeName}`);
  if (!descriptor) {
    throw new Error(`enabled enter_now action not found: ${targetNodeName}/${targetAction}`);
  }

  const explorerToggle = page.locator("[data-map-explorer-toggle]");
  await explorerToggle.waitFor({ state: "visible" });
  if (await explorerToggle.isVisible() && await explorerToggle.getAttribute("aria-expanded") === "false") {
    await explorerToggle.click();
  }
  await page.getByRole("radiogroup", { name: "知识展示方式" }).waitFor();
  await page.getByRole("radio", { name: "导图", exact: true }).check();
  const mindRegion = page.getByRole("region", { name: "我的数学知识导图" });
  const search = page.getByRole("search").getByRole("searchbox");
  await search.fill(targetNodeName);
  const visibleTarget = mindRegion.locator(
    `.mind-search-results .knowledge-node-button[data-node-handle="${targetNode.handle}"]`
  );
  await visibleTarget.waitFor({ state: "visible" });
  const clickedNodeLabel = (
    await visibleTarget.locator(".knowledge-node-label").textContent()
  )?.trim() || "";
  await visibleTarget.click();

  const detailHeading = page.locator("#knowledgeDetailHeading");
  await detailHeading.waitFor({ state: "visible" });
  const openedDetailHeading = (await detailHeading.textContent())?.trim() || "";
  const actionButton = page.locator(
    `[data-knowledge-detail] [data-action-name="${descriptor.action}"]`
  );
  await actionButton.waitFor({ state: "visible" });
  const clickedActionLabel = (await actionButton.textContent())?.trim() || "";

  const selectResponseSeen = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/knowledge-map/select" &&
      response.request().method() === "POST";
  });
  const bootstrapResponseSeen = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/child-bootstrap";
  });
  await actionButton.click();
  await selectResponseSeen;
  await bootstrapResponseSeen;
  await page.waitForFunction(() => {
    const surface = document.getElementById("view-child");
    const heading = document.getElementById("childHeading");
    return Boolean(surface && !surface.hidden && heading?.textContent?.trim());
  });
  await settleFrames(page, 6);

  const bootstrap = postSelectBootstraps.at(-1) || null;
  const finalHeading = (
    await page.locator("#childHeading").textContent()
  )?.trim() || "";
  const postTopicLabel = String(
    selectExchange?.response?.current_learning?.topic_label || ""
  ).trim();
  const bootstrapTopicLabel = String(
    bootstrap?.current_step?.topic_label || ""
  ).trim();

  report = {
    pass:
      clickedNodeLabel === targetNodeName &&
      openedDetailHeading === targetNodeName &&
      selectExchange?.request?.handle === targetNode.handle &&
      selectExchange?.request?.action === descriptor.action &&
      selectExchange?.httpStatus === 200 &&
      selectExchange?.response?.status === "applied" &&
      selectExchange?.response?.result_behavior === "enter_now" &&
      postTopicLabel === targetNodeName &&
      bootstrap?.child_state === "current_step" &&
      bootstrapTopicLabel === targetNodeName &&
      finalHeading === targetNodeName,
    targetNodeName,
    targetNodeHandle: targetNode.handle,
    clickedNodeLabel,
    openedDetailHeading,
    clickedAction: {
      action: descriptor.action,
      label: clickedActionLabel,
      resultBehavior: descriptor.result_behavior,
    },
    post: {
      requestHandle: selectExchange?.request?.handle || "",
      requestAction: selectExchange?.request?.action || "",
      httpStatus: selectExchange?.httpStatus || 0,
      status: selectExchange?.response?.status || "",
      resultBehavior: selectExchange?.response?.result_behavior || "",
      topicLabel: postTopicLabel,
    },
    bootstrap: {
      requestCountAfterPost: postSelectBootstraps.length,
      childState: bootstrap?.child_state || "",
      topicLabel: bootstrapTopicLabel,
    },
    finalHeading,
    continuity: [
      clickedNodeLabel,
      postTopicLabel,
      bootstrapTopicLabel,
      finalHeading,
    ],
  };
} catch (error) {
  report = {
    pass: false,
    infrastructureError: String(error?.stack || error),
    selectExchange,
    postSelectBootstrapCount: postSelectBootstraps.length,
  };
} finally {
  await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => {});
  await context.close();
  await browser.close();
}

process.stdout.write(JSON.stringify({ report, screenshot: screenshotPath }, null, 2));
