import path from "node:path";
import { fileURLToPath } from "node:url";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const defaultVisual = {
  scene_type: "number_line",
  alt_text: "一条只标出负一、零和一，等待补出中间刻度的数轴。",
  long_description: "相邻已知数之间还各缺一个等距刻度。请在纸上补完整，并拍照提交。",
  scene: {
    axis: { min: -1, max: 1, step: 0.5, origin: 0, direction: "right" },
    ticks: [
      { value: -1, label: "-1" },
      { value: 0, label: "0" },
      { value: 1, label: "1" },
    ],
    points: [],
  },
  interaction_contract: {
    operation: "complete_missing_ticks",
    required_interaction_capabilities: ["construction_interaction"],
    response_capture: "paper_photo",
    visible_entity_ids_for_visual: ["tick:-1", "tick:0", "tick:1"],
    required_child_produced_entity_ids: ["tick:-0.5", "tick:0.5"],
    answer_hidden: true,
  },
};
assert(process.argv.length === 2 || process.argv.length === 4, "expected zero or two arguments");
const selfContained = process.argv.length === 2;
const rendererPath = process.argv[2]
  || path.join(root, "app", "local_learning_system", "question_visual_renderer.js");
const visual = selfContained ? defaultVisual : JSON.parse(process.argv[3]);

const contract = visual.interaction_contract;
assert(contract.operation === "complete_missing_ticks", "operation contract changed");
assert(contract.answer_hidden === true, "construction answer must be hidden initially");
assert(
  contract.response_capture === "paper_photo",
  "missing-tick construction must bind paper photo capture",
);
assert(
  contract.required_interaction_capabilities.length === 1
    && contract.required_interaction_capabilities[0] === "construction_interaction",
  "missing-tick construction must bind one construction interaction schema",
);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });

try {
  await page.setContent('<main id="host"></main>');
  await page.addScriptTag({ path: rendererPath });
  const renderedTickEntityIds = await page.evaluate((payload) => {
    const host = document.getElementById("host");
    window.QuestionVisualRenderer.render(host, payload);
    return [...host.querySelectorAll("[data-qv-tick-value]")].map(
      (tick) => `tick:${tick.getAttribute("data-qv-tick-value")}`,
    );
  }, visual);

  assert(
    JSON.stringify(renderedTickEntityIds)
      === JSON.stringify(contract.visible_entity_ids_for_visual),
    "renderer changed the exact initially visible tick set",
  );
  const required = new Set(contract.required_child_produced_entity_ids);
  const precompletedEntityIds = renderedTickEntityIds.filter((id) => required.has(id));
  assert(
    precompletedEntityIds.length === 0,
    `renderer precompleted child-produced ticks: ${precompletedEntityIds.join(",")}`,
  );

  const result = {
    operation: contract.operation,
    rendered_tick_entity_ids: renderedTickEntityIds,
    required_child_produced_entity_ids: contract.required_child_produced_entity_ids,
    precompleted_entity_ids: precompletedEntityIds,
    answer_hidden: contract.answer_hidden,
    construction_interaction_required: true,
  };
  if (selfContained) result.status = "PASS";
  process.stdout.write(JSON.stringify(result));
} finally {
  await browser.close();
}
