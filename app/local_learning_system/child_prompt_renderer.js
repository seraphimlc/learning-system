(function attachChildPromptRenderer(global) {
  "use strict";

  const PROMPT_FORMAT = "2026-07-17.child-plain-text.v1";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
  }

  function segmentsHtml(segments, expectedSource) {
    if (!Array.isArray(segments) || !segments.length) return null;
    let reconstructed = "";
    const html = [];
    for (const segment of segments) {
      if (!segment || typeof segment !== "object") return null;
      if (segment.type === "text" && typeof segment.text === "string") {
        reconstructed += segment.text;
        html.push(escapeHtml(segment.text));
        continue;
      }
      if (
        segment.type === "exponent"
        && typeof segment.source === "string"
        && typeof segment.base === "string"
        && typeof segment.exponent === "string"
        && typeof segment.accessible_label === "string"
        && segment.source === `${segment.base}^${segment.exponent}`
      ) {
        reconstructed += segment.source;
        html.push(
          `<span class="math-power" role="img" aria-label="${escapeAttr(segment.accessible_label)}" data-linear-source="${escapeAttr(segment.source)}">`
          + `<span aria-hidden="true">${escapeHtml(segment.base)}<span class="math-power-caret">^</span><sup>${escapeHtml(segment.exponent)}</sup></span>`
          + "</span>"
        );
        continue;
      }
      return null;
    }
    return reconstructed === String(expectedSource || "") ? html.join("") : null;
  }

  function promptHtml(step) {
    if (step?.prompt_format !== PROMPT_FORMAT) return null;
    return segmentsHtml(step.prompt_segments, step.prompt);
  }

  function inlineHtml(rendering, expectedText) {
    if (!rendering || rendering.text !== String(expectedText || "")) return null;
    return segmentsHtml(rendering.segments, rendering.text);
  }

  function interactionRenderingValid(schema, rendering) {
    if (!schema) return true;
    if (!rendering || inlineHtml(rendering.title, schema.title || "作答") === null) return false;
    if (inlineHtml(rendering.explanation_label, schema.explanation_label || "补充说明") === null) return false;
    if (schema.formula_label && inlineHtml(rendering.formula_label, schema.formula_label) === null) return false;
    for (const field of schema.fields || []) {
      const rendered = rendering.fields?.find((entry) => entry.id === field.id);
      if (!rendered || inlineHtml(rendered.label, field.label) === null) return false;
      if (field.prefix && inlineHtml(rendered.prefix, field.prefix) === null) return false;
      if (field.suffix && inlineHtml(rendered.suffix, field.suffix) === null) return false;
    }
    for (const choice of schema.choices || []) {
      const rendered = rendering.choices?.find((entry) => entry.id === choice.id);
      if (!rendered || inlineHtml(rendered.label, choice.label) === null) return false;
    }
    return true;
  }

  function containingMathPower(node) {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return element?.closest?.(".math-power") || null;
  }

  function rangeContainsMathPower(range) {
    return [...document.querySelectorAll(".math-power")].some((element) => {
      try {
        return range.intersectsNode(element);
      } catch (_error) {
        return false;
      }
    });
  }

  function serializeMathSelection(selection) {
    const parts = [];
    let containsMathPower = false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const sourceRange = selection.getRangeAt(index);
      if (!rangeContainsMathPower(sourceRange)) {
        parts.push(sourceRange.toString());
        continue;
      }
      containsMathPower = true;
      const range = sourceRange.cloneRange();
      const startPower = containingMathPower(range.startContainer);
      const endPower = containingMathPower(range.endContainer);
      if (startPower) range.setStartBefore(startPower);
      if (endPower) range.setEndAfter(endPower);
      const container = document.createElement("div");
      container.append(range.cloneContents());
      for (const power of container.querySelectorAll(".math-power")) {
        power.replaceWith(document.createTextNode(power.dataset.linearSource || power.textContent || ""));
      }
      parts.push(container.textContent || "");
    }
    return containsMathPower ? parts.join("") : null;
  }

  document.addEventListener("copy", (event) => {
    const selection = global.getSelection?.();
    if (!selection || selection.isCollapsed || !event.clipboardData) return;
    const serialized = serializeMathSelection(selection);
    if (serialized === null) return;
    event.clipboardData.setData("text/plain", serialized);
    event.preventDefault();
  });

  global.ChildPromptRenderer = Object.freeze({
    PROMPT_FORMAT,
    segmentsHtml,
    promptHtml,
    inlineHtml,
    interactionRenderingValid,
  });
})(window);
