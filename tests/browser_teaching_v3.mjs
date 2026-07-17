#!/usr/bin/env node
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;
const root = path.resolve(new URL("..", import.meta.url).pathname);
const appRoot = path.join(root, "app", "local_learning_system");
const port = await getFreePort();
const baseUrl = `http://127.0.0.1:${port}`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const freePort = address.port;
      server.close(() => resolve(freePort));
    });
    server.on("error", reject);
  });
}

const teachingPayload = {
  schema_version: "3.0.0-v5-daily-runtime",
  child_state: "teaching",
  current_step: {
    step_handle: "step-v3",
    position: 1,
    kind_label: "讲解",
    topic_label: "含分母方程",
    prompt: "先看一个例题。",
    answer_input_mode: "none",
    allowed_response_modes: ["continue", "stuck"],
    upload_enabled: false,
    stuck_enabled: true,
    support: { continue_label: "继续小检查", stuck_label: "还是卡住" },
    assessment_feedback: {
      score_label: "9/10",
      reference_answer: "C=0.5，A<C<B",
      answer_gap: "核心关系正确，只少写了一步代入。",
      improvement_direction: ["把 C=A+3 和代入过程连起来。"],
      expression_judgment: "a,c,b 与 A<C<B 数学意图一致。",
    },
    teaching_sections: {
      essence: { title: "本质", body: "去分母是在方程两边同时乘同一个非零数。" },
      core_model: { title: "核心关系", body: "每一项都乘最小公倍数，等号两边保持相等。" },
      worked_example: {
        title: "例题",
        problem: "(x-1)/3 + 2 = (x+5)/6",
        steps: ["两边同乘 6。", "得到 2(x-1)+12=x+5。", "解出 x=-5。"],
        check: "代回原式检查。",
      },
      why_it_works: { title: "为什么成立", body: "两边同乘同一个非零数，等式仍然相等。" },
      next_micro_check: { title: "小检查", prompt: "把 (x+2)/4=3 的两边同乘 4 后第一步是什么？" },
    },
  },
  message: { title: "讲解", body: "先看例题", action_label: "继续小检查" },
};

const readyPayload = {
  schema_version: "3.0.0-v5-daily-runtime",
  child_state: "ready_for_new_knowledge",
  ready_for_new_knowledge: true,
  message: {
    title: "旧知识复习暂时告一段落",
    body: "可以开始一个新的知识点。",
    action_label: "学一个新知识",
  },
};

const preparingPayload = {
  schema_version: "3.0.0-v5-daily-runtime",
  child_state: "preparing_new_knowledge",
  ready_for_new_knowledge: false,
  message: {
    title: "正在准备讲解",
    body: "正在准备一个新知识的小讲解和小检查。",
    action_label: "刷新看看",
  },
};

let currentPayload = teachingPayload;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, baseUrl);
  if (url.pathname === "/api/child-bootstrap") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(currentPayload));
    return;
  }
  const filePath = url.pathname === "/" ? path.join(appRoot, "index.html") : path.join(appRoot, url.pathname.slice(1));
  if (!filePath.startsWith(appRoot) || !fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  const ext = path.extname(filePath);
  const contentType = ext === ".js" ? "text/javascript" : ext === ".css" ? "text/css" : "text/html";
  res.writeHead(200, { "content-type": `${contentType}; charset=utf-8` });
  res.end(fs.readFileSync(filePath));
});

await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));

const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
    const page = await browser.newPage({ viewport });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    const keys = await page.$$eval("[data-v5-teaching-section]", (nodes) => nodes.map((node) => node.getAttribute("data-v5-teaching-section")));
    assert(JSON.stringify(keys) === JSON.stringify(["essence", "core_model", "worked_example", "why_it_works", "next_micro_check"]), `teaching sections must render in order at ${viewport.width}`);
    const microCheckText = await page.locator("[data-v5-teaching-section='next_micro_check']").innerText();
    assert(microCheckText.includes("点继续") && microCheckText.includes("再答"), `micro-check preview must not look like an inline fill-in form at ${viewport.width}`);
    const continueBox = await page.locator("[data-v3-continue-step]").boundingBox();
    assert(continueBox && continueBox.height >= 44, `continue button must be at least 44px tall at ${viewport.width}`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert(!overflow, `page must not horizontally overflow at ${viewport.width}`);
    const teachingLiveRegion = await page.locator(
      "#childTaskContent[role='region'][aria-live='polite'][aria-labelledby='childHeading']",
    ).count();
    assert(teachingLiveRegion === 1, "teaching content must announce its own async update");
    const feedbackText = await page.locator(".assessment-feedback").innerText();
    for (const expected of ["9/10", "标准答案", "与标准答案的差距", "改进方向", "表达判定", "A<C<B"]) {
      assert(feedbackText.includes(expected), `assessment feedback must include ${expected} at ${viewport.width}`);
    }
    await page.close();
  }

  currentPayload = readyPayload;
  const ready = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await ready.goto(baseUrl, { waitUntil: "networkidle" });
  assert((await ready.locator("#startNextRoundBtn").textContent()).trim() === "学一个新知识", "ready CTA must be 学一个新知识");
  await ready.close();

  currentPayload = preparingPayload;
  const preparing = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await preparing.goto(baseUrl, { waitUntil: "networkidle" });
  assert((await preparing.locator("#childHandoffTitle").textContent()).includes("准备讲解"), "preparing state must be distinct from answer analyzing");
  await preparing.close();
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
