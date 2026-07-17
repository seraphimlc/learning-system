(function () {
  "use strict";

  const SCENE_TYPES = Object.freeze([
    "number_line",
    "cube_net",
    "orthographic_view",
    "simple_geometry",
  ]);
  const SVG_NS = ["http:", "", "www.w3.org", "2000", "svg"].join("/");

  function svgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    return element;
  }

  function svgText(value, attributes = {}) {
    const text = svgElement("text", attributes);
    text.textContent = String(value);
    return text;
  }

  function visualRoot(visual, viewBox) {
    const root = document.createElement("figure");
    root.className = `question-visual question-visual-${visual.scene_type}`;
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", visual.alt_text);
    const description = document.createElement("figcaption");
    description.className = "question-visual-description";
    description.id = `questionVisualDescription-${visual.scene_type}`;
    description.textContent = visual.long_description;
    root.setAttribute("aria-describedby", description.id);
    const svg = svgElement("svg", {
      viewBox,
      preserveAspectRatio: "xMidYMid meet",
      focusable: "false",
      "aria-hidden": "true",
    });
    root.append(svg, description);
    return { root, svg };
  }

  function numberLine(visual) {
    const { root, svg } = visualRoot(visual, "0 0 720 220");
    const { axis, ticks, points } = visual.scene;
    const left = 60;
    const right = 660;
    const y = 108;
    const span = axis.max - axis.min;
    const xFor = (value) => left + ((value - axis.min) / span) * (right - left);
    svg.append(svgElement("line", { x1: left, y1: y, x2: right, y2: y, class: "qv-axis" }));
    const arrowX = axis.direction === "right" ? right : left;
    const arrow = axis.direction === "right"
      ? `${right - 14},${y - 8} ${right},${y} ${right - 14},${y + 8}`
      : `${left + 14},${y - 8} ${left},${y} ${left + 14},${y + 8}`;
    svg.append(svgElement("polyline", { points: arrow, class: "qv-axis-arrow" }));
    for (const tick of ticks) {
      const x = xFor(tick.value);
      svg.append(svgElement("line", { x1: x, y1: y - 9, x2: x, y2: y + 9, class: "qv-tick" }));
      svg.append(svgText(tick.label, { x, y: y + 34, class: "qv-label", "text-anchor": "middle" }));
    }
    for (const point of points) {
      const x = xFor(point.value);
      svg.append(svgElement("circle", { cx: x, cy: y, r: 9, class: "qv-point" }));
      svg.append(svgText(point.label, { x, y: y - 22, class: "qv-point-label", "text-anchor": "middle" }));
    }
    return root;
  }

  function cubeNet(visual) {
    const { root, svg } = visualRoot(visual, "0 0 520 360");
    const cells = visual.scene.cells;
    const minimumX = Math.min(...cells.map((cell) => cell.x));
    const maximumX = Math.max(...cells.map((cell) => cell.x));
    const minimumY = Math.min(...cells.map((cell) => cell.y));
    const maximumY = Math.max(...cells.map((cell) => cell.y));
    const columns = maximumX - minimumX + 1;
    const rows = maximumY - minimumY + 1;
    const size = Math.min(82, 400 / columns, 250 / rows);
    const offsetX = (520 - columns * size) / 2;
    const offsetY = (360 - rows * size) / 2;
    for (const cell of cells) {
      const x = offsetX + (cell.x - minimumX) * size;
      const y = offsetY + (cell.y - minimumY) * size;
      svg.append(svgElement("rect", { x, y, width: size, height: size, class: "qv-cell" }));
      svg.append(svgText(cell.label, {
        x: x + size / 2,
        y: y + size / 2 + 7,
        class: "qv-cell-label",
        "text-anchor": "middle",
      }));
    }
    return root;
  }

  function orthographicView(visual) {
    const { root, svg } = visualRoot(visual, "0 0 720 300");
    const views = visual.scene.views;
    const panelWidth = 220;
    const panelGap = 20;
    views.forEach((view, index) => {
      const originX = 10 + index * (panelWidth + panelGap);
      const cellSize = Math.min(48, 180 / view.width, 180 / view.height);
      const gridWidth = view.width * cellSize;
      const gridHeight = view.height * cellSize;
      const gridX = originX + (panelWidth - gridWidth) / 2;
      const gridY = 58 + (190 - gridHeight) / 2;
      svg.append(svgText(view.label, {
        x: originX + panelWidth / 2,
        y: 34,
        class: "qv-view-label",
        "text-anchor": "middle",
      }));
      for (let x = 0; x <= view.width; x += 1) {
        svg.append(svgElement("line", {
          x1: gridX + x * cellSize,
          y1: gridY,
          x2: gridX + x * cellSize,
          y2: gridY + gridHeight,
          class: "qv-grid-line",
        }));
      }
      for (let y = 0; y <= view.height; y += 1) {
        svg.append(svgElement("line", {
          x1: gridX,
          y1: gridY + y * cellSize,
          x2: gridX + gridWidth,
          y2: gridY + y * cellSize,
          class: "qv-grid-line",
        }));
      }
      for (const [cellX, cellY] of view.filled_cells) {
        svg.append(svgElement("rect", {
          x: gridX + cellX * cellSize + 2,
          y: gridY + cellY * cellSize + 2,
          width: Math.max(1, cellSize - 4),
          height: Math.max(1, cellSize - 4),
          class: "qv-filled-cell",
        }));
      }
    });
    return root;
  }

  function simpleGeometry(visual) {
    const { root, svg } = visualRoot(visual, "0 0 600 440");
    const points = new Map();
    for (const point of visual.scene.points) {
      points.set(point.key, { x: 60 + point.x * 4.8, y: 35 + point.y * 4.2, label: point.label });
    }
    for (const segment of visual.scene.segments) {
      const start = points.get(segment.from);
      const end = points.get(segment.to);
      svg.append(svgElement("line", {
        x1: start.x,
        y1: start.y,
        x2: end.x,
        y2: end.y,
        class: "qv-segment",
      }));
    }
    for (const marker of visual.scene.markers) {
      const at = points.get(marker.at);
      const first = points.get(marker.arms[0]);
      const second = points.get(marker.arms[1]);
      const unit = (target) => {
        const dx = target.x - at.x;
        const dy = target.y - at.y;
        const length = Math.max(1, Math.hypot(dx, dy));
        return { x: dx / length, y: dy / length };
      };
      const one = unit(first);
      const two = unit(second);
      const size = 18;
      const cornerOne = { x: at.x + one.x * size, y: at.y + one.y * size };
      const cornerTwo = { x: at.x + two.x * size, y: at.y + two.y * size };
      const outer = { x: cornerOne.x + two.x * size, y: cornerOne.y + two.y * size };
      svg.append(svgElement("polyline", {
        points: `${cornerOne.x},${cornerOne.y} ${outer.x},${outer.y} ${cornerTwo.x},${cornerTwo.y}`,
        class: "qv-marker",
      }));
    }
    for (const point of points.values()) {
      svg.append(svgElement("circle", { cx: point.x, cy: point.y, r: 6, class: "qv-geometry-point" }));
      svg.append(svgText(point.label, {
        x: point.x + 11,
        y: point.y - 10,
        class: "qv-label",
      }));
    }
    return root;
  }

  function render(host, visual) {
    if (!(host instanceof HTMLElement)) throw new TypeError("question visual host is required");
    if (!visual || !SCENE_TYPES.includes(visual.scene_type)) {
      throw new TypeError("question visual scene type is unsupported");
    }
    clear(host);
    const renderers = {
      number_line: numberLine,
      cube_net: cubeNet,
      orthographic_view: orthographicView,
      simple_geometry: simpleGeometry,
    };
    const root = renderers[visual.scene_type](visual);
    host.append(root);
    return root;
  }

  function clear(host) {
    if (!(host instanceof HTMLElement)) throw new TypeError("question visual host is required");
    host.replaceChildren();
  }

  function supportedSceneTypes() {
    return [...SCENE_TYPES];
  }

  window.QuestionVisualRenderer = Object.freeze({
    render,
    clear,
    supportedSceneTypes,
  });
})();
