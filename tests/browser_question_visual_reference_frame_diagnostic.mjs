import path from "node:path";
import { fileURLToPath } from "node:url";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const rendererPath = process.argv[2]
  || path.join(root, "app", "local_learning_system", "question_visual_renderer.js");
const stylePath = process.argv[3]
  || path.join(root, "app", "local_learning_system", "question_visual_renderer.css");
assert(process.argv.length === 2 || process.argv.length === 4, "expected zero or two file arguments");

const diagnostic = {
  scene_type: "number_line_reference_frame_diagnostic",
  alt_text: "一条用于检查数轴参照要素的刻度线。",
  long_description: "图中显示四个连续刻度，用于判断原点、正方向和单位长度是否完整。",
  scene: {
    direction_marker_visible: true,
    origin_tick_id: "tick-zero",
    origin_label_visible: true,
    visible_fault_ids: ["inconsistent_unit_length"],
    ticks: [
      { id: "tick-neg-one", scale_index: -1, position: 8, value_label: "-1", point_label: "A" },
      { id: "tick-zero", scale_index: 0, position: 30, value_label: "0", point_label: "" },
      { id: "tick-one", scale_index: 1, position: 67, value_label: "1", point_label: "B" },
      { id: "tick-two", scale_index: 2, position: 92, value_label: "2", point_label: "C" },
    ],
  },
};

const ordinary = {
  scene_type: "number_line",
  alt_text: "一条普通数轴。",
  long_description: "数轴向右为正方向，原点和每个单位刻度都完整显示。",
  scene: {
    axis: { min: -1, max: 1, step: 1, origin: 0, direction: "right" },
    ticks: [
      { value: -1, label: "-1" },
      { value: 0, label: "0" },
      { value: 1, label: "1" },
    ],
    points: [],
  },
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });

try {
  await page.setContent(`
    <style>* { box-sizing: border-box; } body { margin: 0; } #host { width: 100%; padding: 12px; }</style>
    <main id="host"></main>
  `);
  await page.addStyleTag({ path: stylePath });
  await page.addScriptTag({ path: rendererPath });

  const supported = await page.evaluate(() => window.QuestionVisualRenderer.supportedSceneTypes());
  assert(
    supported.includes("number_line_reference_frame_diagnostic"),
    "diagnostic scene type is not advertised",
  );

  const full = await page.evaluate((visual) => {
    const host = document.getElementById("host");
    window.QuestionVisualRenderer.render(host, visual);
    const ticks = [...host.querySelectorAll("[data-qv-tick-id]")].map((tick) => ({
      id: tick.getAttribute("data-qv-tick-id"),
      scaleIndex: tick.getAttribute("data-qv-scale-index"),
      position: tick.getAttribute("data-qv-position"),
      x: Number(tick.getAttribute("x1")),
    }));
    const root = host.querySelector('[role="img"]');
    const svg = host.querySelector("svg");
    const allowedTags = new Set(["figure", "figcaption", "svg", "line", "polyline", "text"]);
    return {
      rootSceneType: root?.getAttribute("data-qv-scene-type"),
      ticks,
      arrowCount: host.querySelectorAll(".qv-axis-arrow").length,
      originLabelCount: host.querySelectorAll('[data-qv-origin-label="true"]').length,
      originText: host.querySelector('[data-qv-origin-label="true"]')?.textContent || "",
      pointLabels: [...host.querySelectorAll("[data-qv-point-label-for]")].map(
        (label) => label.textContent,
      ),
      forbiddenElementCount: host.querySelectorAll(
        "canvas, img, image, path, rect, circle, polygon, foreignObject",
      ).length,
      unexpectedTags: [...host.querySelectorAll("*")]
        .filter((element) => !allowedTags.has(element.tagName.toLowerCase()))
        .map((element) => element.tagName),
      hasSvg: Boolean(svg),
      noOverflow:
        host.scrollWidth <= host.clientWidth
        && document.documentElement.scrollWidth <= window.innerWidth,
    };
  }, diagnostic);

  assert(full.rootSceneType === diagnostic.scene_type, "scene type DOM attribute is missing");
  assert(full.hasSvg, "diagnostic renderer fell back to text");
  assert(full.arrowCount === 1, "visible direction marker was omitted");
  assert(full.originLabelCount === 1 && full.originText === "0", "visible origin label was omitted");
  assert(full.pointLabels.join(",") === "A,B,C", "point labels were not rendered from ticks");
  assert(full.forbiddenElementCount === 0, "renderer emitted a forbidden or arbitrary shape");
  assert(full.unexpectedTags.length === 0, `renderer emitted unexpected tags: ${full.unexpectedTags}`);
  assert(full.noOverflow, "diagnostic renderer overflows a 390px viewport");
  assert(
    full.ticks.map((tick) => `${tick.id}:${tick.scaleIndex}:${tick.position}`).join("|")
      === "tick-neg-one:-1:8|tick-zero:0:30|tick-one:1:67|tick-two:2:92",
    "mobile-safe tick attributes do not preserve the scene contract",
  );
  const renderedGaps = full.ticks.slice(1).map((tick, index) => tick.x - full.ticks[index].x);
  assert(new Set(renderedGaps.map((gap) => gap.toFixed(6))).size === 3, "nonuniform positions were normalized");

  const omissions = await page.evaluate((visual) => {
    const host = document.getElementById("host");
    const hidden = structuredClone(visual);
    hidden.scene.direction_marker_visible = false;
    hidden.scene.origin_label_visible = false;
    hidden.scene.visible_fault_ids = [
      "missing_origin",
      "missing_positive_direction",
      "inconsistent_unit_length",
    ];
    window.QuestionVisualRenderer.render(host, hidden);
    return {
      arrowCount: host.querySelectorAll(".qv-axis-arrow").length,
      originLabelCount: host.querySelectorAll('[data-qv-origin-label="true"]').length,
      zeroTextCount: [...host.querySelectorAll("svg text")]
        .filter((element) => element.textContent === "0").length,
      tickCount: host.querySelectorAll("[data-qv-tick-id]").length,
    };
  }, diagnostic);
  assert(omissions.arrowCount === 0, "hidden direction marker was rendered");
  assert(omissions.originLabelCount === 0 && omissions.zeroTextCount === 0, "hidden origin label was rendered");
  assert(omissions.tickCount === diagnostic.scene.ticks.length, "origin omission removed the tick itself");

  const ordinaryResult = await page.evaluate((visual) => {
    const host = document.getElementById("host");
    window.QuestionVisualRenderer.render(host, visual);
    return {
      arrowCount: host.querySelectorAll(".qv-axis-arrow").length,
      zeroTextCount: [...host.querySelectorAll("svg text")]
        .filter((element) => element.textContent === "0").length,
      diagnosticTickCount: host.querySelectorAll("[data-qv-tick-id]").length,
      ordinaryTickCount: host.querySelectorAll("[data-qv-tick-value]").length,
    };
  }, ordinary);
  assert(ordinaryResult.arrowCount === 1, "ordinary number_line lost its arrow");
  assert(ordinaryResult.zeroTextCount === 1, "ordinary number_line lost its origin label");
  assert(ordinaryResult.diagnosticTickCount === 0, "ordinary number_line used the diagnostic DOM contract");
  assert(ordinaryResult.ordinaryTickCount === 3, "ordinary number_line tick rendering changed");

  process.stdout.write(JSON.stringify({ status: "PASS", full, omissions, ordinaryResult }));
} finally {
  await browser.close();
}
