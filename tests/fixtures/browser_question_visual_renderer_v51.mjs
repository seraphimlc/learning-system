import fs from "node:fs";
import playwright from "/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";

const { chromium } = playwright;

function arg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function expectedLabels(visual) {
  if (visual.scene_type === "number_line") {
    return [...visual.scene.ticks, ...visual.scene.points].map((entry) => String(entry.label));
  }
  if (visual.scene_type === "cube_net") {
    return visual.scene.cells.map((entry) => String(entry.label));
  }
  if (visual.scene_type === "orthographic_view") {
    return visual.scene.views.map((entry) => String(entry.label));
  }
  return visual.scene.points.map((entry) => String(entry.label));
}

function expectedGraphicCount(visual) {
  if (visual.scene_type === "number_line") {
    return 1 + visual.scene.ticks.length + visual.scene.points.length;
  }
  if (visual.scene_type === "cube_net") return visual.scene.cells.length;
  if (visual.scene_type === "orthographic_view") {
    return visual.scene.views.reduce((count, view) => count + view.filled_cells.length, 0);
  }
  return visual.scene.points.length + visual.scene.segments.length;
}

const rendererPath = arg("--renderer");
const stylePath = arg("--style");
const scenesPath = arg("--scenes");
assert(rendererPath && stylePath && scenesPath, "renderer, style and scenes paths are required");

const fixture = JSON.parse(fs.readFileSync(scenesPath, "utf8"));
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const cdp = await page.context().newCDPSession(page);
const browserRequests = [];
page.on("request", (request) => browserRequests.push(request.url()));

try {
  await page.setContent(`
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; }
      #page-shell { padding: 20px; }
      #child-panel { max-width: 960px; margin: 0 auto; padding: 22px; border: 1px solid transparent; }
      #task-content { padding: 16px; border: 1px solid transparent; }
      @media (max-width: 620px) {
        #page-shell { padding: 12px; }
        #child-panel { padding: 14px; }
      }
    </style>
    <main id="page-shell">
      <article id="child-panel">
        <section id="task-content"><div id="visual-host"></div></section>
      </article>
    </main>
  `);
  await page.evaluate(() => {
    window.__questionVisualNetworkCalls = [];
    const blocked = (kind, detail = "") => {
      window.__questionVisualNetworkCalls.push({ kind, detail: String(detail || "") });
      throw new Error(`question visual renderer attempted ${kind}`);
    };
    window.fetch = (...args) => blocked("fetch", args[0]);
    window.XMLHttpRequest = class BlockedXMLHttpRequest {
      open(method, url) { blocked("XMLHttpRequest", `${method} ${url}`); }
    };
    window.WebSocket = class BlockedWebSocket {
      constructor(url) { blocked("WebSocket", url); }
    };
    window.EventSource = class BlockedEventSource {
      constructor(url) { blocked("EventSource", url); }
    };
    Object.defineProperty(window.navigator, "sendBeacon", {
      configurable: true,
      value: (url) => blocked("sendBeacon", url),
    });
  });
  await page.addStyleTag({ path: stylePath });
  await page.addScriptTag({ path: rendererPath });

  const report = {
    deterministic_scene_types: [],
    alt_and_long_descriptions: true,
    viewport_1280_no_overflow: true,
    viewport_390_no_overflow: true,
    viewport_200pct_no_overflow: true,
    cdp_200pct_readable: true,
    print_monochrome: true,
    no_forbidden_dom: true,
    runtime_network_calls: [],
    browser_network_requests: [],
    scene_reports: {},
  };

  for (const entry of fixture.scenes) {
    const sceneReport = { viewports: {}, print: {} };
    for (const viewport of [
      { key: "1280", width: 1280, height: 800 },
      // A 1280px desktop viewport at 200% browser zoom exposes about 640 CSS px.
      { key: "200pct", width: 640, height: 400 },
      { key: "390", width: 390, height: 844 },
    ]) {
      await page.emulateMedia({ media: "screen" });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      const result = await page.evaluate(
        ({ visual, labels, minimumGraphics }) => {
          const host = document.getElementById("visual-host");
          window.QuestionVisualRenderer.clear(host);
          window.QuestionVisualRenderer.render(host, visual);
          const first = host.innerHTML;
          window.QuestionVisualRenderer.clear(host);
          window.QuestionVisualRenderer.render(host, visual);
          const second = host.innerHTML;
          const image = host.querySelector('[role="img"]');
          const svg = host.querySelector("svg");
          const describedBy = image?.getAttribute("aria-describedby") || "";
          const description = describedBy ? document.getElementById(describedBy) : null;
          const forbiddenElement = host.querySelector(
            "script, iframe, object, embed, foreignObject, image, img, link, template"
          );
          const dangerousAttributes = [];
          for (const element of host.querySelectorAll("*")) {
            for (const attribute of element.attributes) {
              const name = attribute.name.toLowerCase();
              const value = String(attribute.value || "");
              if (
                name.startsWith("on")
                || ["src", "href", "xlink:href"].includes(name)
                || /javascript:|data:image|https?:|url\s*\(/i.test(value)
              ) {
                dangerousAttributes.push(`${element.tagName}.${name}=${value}`);
              }
            }
          }
          const viewBox = String(svg?.getAttribute("viewBox") || "")
            .trim()
            .split(/\s+/)
            .map(Number);
          const validViewBox =
            viewBox.length === 4
            && viewBox.every(Number.isFinite)
            && viewBox[2] > 0
            && viewBox[3] > 0;
          const rootRect = image?.getBoundingClientRect();
          const svgRect = svg?.getBoundingClientRect();
          const graphics = [
            ...host.querySelectorAll("svg line, svg path, svg rect, svg circle, svg polyline, svg polygon"),
          ];
          const geometryInside = graphics.every((element) => {
            const rect = element.getBoundingClientRect();
            if (!svgRect) return false;
            return Number.isFinite(rect.x)
              && Number.isFinite(rect.y)
              && rect.left >= svgRect.left - 2
              && rect.right <= svgRect.right + 2
              && rect.top >= svgRect.top - 2
              && rect.bottom <= svgRect.bottom + 2;
          });
          const text = host.textContent || "";
          const missingLabels = labels.filter((label) => label && !text.includes(label));
          const hostNoOverflow =
            host.scrollWidth <= host.clientWidth
            && document.documentElement.scrollWidth <= window.innerWidth;
          const textRects = [...host.querySelectorAll("svg text")]
            .map((element) => element.getBoundingClientRect())
            .filter((rect) => rect.width > 0 && rect.height > 0);
          const pointRects = [...host.querySelectorAll("svg .qv-point")]
            .map((element) => element.getBoundingClientRect())
            .filter((rect) => rect.width > 0 && rect.height > 0);
          const overlapCount = (rects, gap = 0) => {
            let count = 0;
            for (let left = 0; left < rects.length; left += 1) {
              for (let right = left + 1; right < rects.length; right += 1) {
                const one = rects[left];
                const two = rects[right];
                if (
                  one.left < two.right + gap
                  && one.right + gap > two.left
                  && one.top < two.bottom + gap
                  && one.bottom + gap > two.top
                ) count += 1;
              }
            }
            return count;
          };
          return {
            deterministic: first === second,
            accessible:
              Boolean(image)
              && image.getAttribute("aria-label") === visual.alt_text
              && Boolean(description)
              && description.textContent.trim() === visual.long_description,
            forbidden: Boolean(forbiddenElement) || dangerousAttributes.length > 0,
            dangerous_attributes: dangerousAttributes,
            valid_view_box: validViewBox,
            view_box: viewBox,
            root_width: rootRect?.width || 0,
            root_height: rootRect?.height || 0,
            svg_width: svgRect?.width || 0,
            svg_height: svgRect?.height || 0,
            graphic_count: graphics.length,
            minimum_graphics: minimumGraphics,
            geometry_inside: geometryInside,
            missing_labels: missingLabels,
            no_overflow: hostNoOverflow,
            minimum_text_height: textRects.length
              ? Math.min(...textRects.map((rect) => rect.height))
              : 0,
            minimum_point_diameter: pointRects.length
              ? Math.min(...pointRects.map((rect) => Math.min(rect.width, rect.height)))
              : null,
            text_collision_count: overlapCount(textRects, 1),
            point_collision_count: overlapCount(pointRects, 1),
            svg_figure_height_ratio:
              rootRect && rootRect.height > 0 && svgRect
                ? svgRect.height / rootRect.height
                : 0,
          };
        },
        {
          visual: entry,
          labels: expectedLabels(entry),
          minimumGraphics: expectedGraphicCount(entry),
        },
      );
      assert(result.deterministic, `${entry.scene_type} output is nondeterministic at ${viewport.key}`);
      assert(result.accessible, `${entry.scene_type} accessibility failed at ${viewport.key}`);
      assert(!result.forbidden, `${entry.scene_type} dangerous DOM: ${result.dangerous_attributes.join(",")}`);
      assert(result.valid_view_box, `${entry.scene_type} has invalid SVG viewBox at ${viewport.key}`);
      assert(result.root_width > 40 && result.root_height > 40, `${entry.scene_type} is blank at ${viewport.key}`);
      assert(result.svg_width > 40 && result.svg_height > 40, `${entry.scene_type} SVG is blank at ${viewport.key}`);
      assert(
        result.graphic_count >= result.minimum_graphics,
        `${entry.scene_type} omitted typed geometry at ${viewport.key}`,
      );
      assert(result.geometry_inside, `${entry.scene_type} geometry escapes SVG at ${viewport.key}`);
      assert(result.missing_labels.length === 0, `${entry.scene_type} missing labels: ${result.missing_labels.join(",")}`);
      assert(result.no_overflow, `${entry.scene_type} overflow at ${viewport.key}`);
      assert(result.text_collision_count === 0, `${entry.scene_type} text collision at ${viewport.key}`);
      assert(result.point_collision_count === 0, `${entry.scene_type} point collision at ${viewport.key}`);
      assert(
        result.svg_figure_height_ratio >= 0.72,
        `${entry.scene_type} wastes vertical space at ${viewport.key}`,
      );
      if (entry.scene_type === "number_line") {
        assert(
          result.minimum_text_height >= 14,
          `number_line text is too small at ${viewport.key}: ${result.minimum_text_height}`,
        );
        assert(
          result.minimum_point_diameter >= 12,
          `number_line point is too small at ${viewport.key}: ${result.minimum_point_diameter}`,
        );
      }
      sceneReport.viewports[viewport.key] = result;
      report.alt_and_long_descriptions &&= result.accessible;
      report.no_forbidden_dom &&= !result.forbidden;
      if (viewport.key === "1280") report.viewport_1280_no_overflow &&= result.no_overflow;
      if (viewport.key === "200pct") report.viewport_200pct_no_overflow &&= result.no_overflow;
      if (viewport.key === "390") report.viewport_390_no_overflow &&= result.no_overflow;
    }

    if (entry.scene_type === "number_line") {
      await page.emulateMedia({ media: "screen" });
      await page.setViewportSize({ width: 1280, height: 800 });
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 2 });
      const zoomResult = await page.evaluate((visual) => {
        const host = document.getElementById("visual-host");
        window.QuestionVisualRenderer.clear(host);
        window.QuestionVisualRenderer.render(host, visual);
        const textHeights = [...host.querySelectorAll("svg text")]
          .map((element) => element.getBoundingClientRect().height)
          .filter((height) => height > 0);
        const scale = window.visualViewport?.scale || 1;
        return {
          scale,
          physical_minimum_text_height: Math.min(...textHeights) * scale,
          no_horizontal_overflow:
            document.documentElement.scrollWidth
            <= document.documentElement.clientWidth,
        };
      }, entry);
      assert(zoomResult.scale >= 1.9, "CDP 200% zoom did not activate");
      assert(
        zoomResult.physical_minimum_text_height >= 28,
        "number_line text did not remain readable at real 200% zoom",
      );
      assert(
        zoomResult.no_horizontal_overflow,
        "number_line overflows at real 200% zoom",
      );
      sceneReport.cdp_200pct = zoomResult;
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });

      const leftDirection = await page.evaluate((visual) => {
        const host = document.getElementById("visual-host");
        const reversed = structuredClone(visual);
        reversed.scene.axis.direction = "left";
        window.QuestionVisualRenderer.clear(host);
        window.QuestionVisualRenderer.render(host, reversed);
        const minimum = host.querySelector(
          `[data-qv-tick-value="${reversed.scene.axis.min}"]`,
        );
        const maximum = host.querySelector(
          `[data-qv-tick-value="${reversed.scene.axis.max}"]`,
        );
        const arrow = host.querySelector(".qv-axis-arrow");
        const arrowXs = String(arrow?.getAttribute("points") || "")
          .trim()
          .split(/\s+/)
          .map((pair) => Number(pair.split(",")[0]));
        return {
          minimum_x: Number(minimum?.getAttribute("x1")),
          maximum_x: Number(maximum?.getAttribute("x1")),
          arrow_tip_x: arrowXs[1],
        };
      }, entry);
      assert(
        leftDirection.minimum_x > leftDirection.maximum_x,
        "left-direction number line did not reverse value positions",
      );
      assert(
        leftDirection.arrow_tip_x === leftDirection.maximum_x,
        "left-direction number line arrow does not point left",
      );
      sceneReport.left_direction = leftDirection;
    }

    await page.emulateMedia({ media: "print" });
    await page.setViewportSize({ width: 1280, height: 800 });
    sceneReport.print = await page.evaluate((visual) => {
      const host = document.getElementById("visual-host");
      window.QuestionVisualRenderer.clear(host);
      window.QuestionVisualRenderer.render(host, visual);
      const parseRgb = (value) => {
        const match = String(value).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        return match ? match.slice(1, 4).map(Number) : null;
      };
      const values = [];
      for (const element of document.querySelectorAll("#visual-host, #visual-host *")) {
        const style = getComputedStyle(element);
        values.push(style.color, style.borderColor, style.fill, style.stroke, style.backgroundColor);
      }
      const monochrome = values.every((value) => {
        if (!value || value === "none" || value === "transparent") return true;
        const rgb = parseRgb(value);
        return !rgb || (rgb[0] === rgb[1] && rgb[1] === rgb[2]);
      });
      const image = host.querySelector('[role="img"]');
      const svg = host.querySelector("svg");
      const rect = image?.getBoundingClientRect();
      return {
        monochrome,
        visible: Boolean(rect && rect.width > 40 && rect.height > 40),
        view_box: String(svg?.getAttribute("viewBox") || ""),
        no_overflow:
          host.scrollWidth <= host.clientWidth
          && document.documentElement.scrollWidth <= window.innerWidth,
      };
    }, entry);
    assert(sceneReport.print.monochrome, `${entry.scene_type} print output is not monochrome`);
    assert(sceneReport.print.visible, `${entry.scene_type} print output is blank`);
    assert(sceneReport.print.view_box, `${entry.scene_type} print output lost its viewBox`);
    assert(sceneReport.print.no_overflow, `${entry.scene_type} print output overflows`);
    report.print_monochrome &&= sceneReport.print.monochrome;
    report.scene_reports[entry.scene_type] = sceneReport;
    report.deterministic_scene_types.push(entry.scene_type);
  }

  report.runtime_network_calls = await page.evaluate(() => window.__questionVisualNetworkCalls || []);
  report.browser_network_requests = browserRequests.filter((url) => /^https?:/i.test(url));
  assert(report.runtime_network_calls.length === 0, "renderer attempted a runtime network API");
  assert(report.browser_network_requests.length === 0, "renderer caused a browser network request");
  for (const [key, value] of Object.entries(report)) {
    if (["deterministic_scene_types", "runtime_network_calls", "browser_network_requests", "scene_reports"].includes(key)) continue;
    assert(value === true, `${key} failed`);
  }
  process.stdout.write(JSON.stringify(report));
} finally {
  await browser.close();
}
