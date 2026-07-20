(function () {
  "use strict";

  const root = document.getElementById("knowledgeCardPreview");

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};
    if (!response.ok) {
      const error = new Error(payload.error || payload.message || "学习卡暂时打不开");
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function componentByPurpose(card, purpose) {
    return (Array.isArray(card.components) ? card.components : [])
      .find((component) => component && component.purpose === purpose) || null;
  }

  function componentByType(card, type) {
    return (Array.isArray(card.components) ? card.components : [])
      .find((component) => component && component.type === type) || null;
  }

  function renderNumberLine(component) {
    if (!component || component.type !== "number_line_visual") return "";
    const range = component.range || {};
    const min = Number.isFinite(Number(range.min)) ? Number(range.min) : -5;
    const max = Number.isFinite(Number(range.max)) ? Number(range.max) : 5;
    const unit = Number.isFinite(Number(range.unit)) && Number(range.unit) > 0 ? Number(range.unit) : 1;
    const span = Math.max(1, max - min);
    const ticks = [];
    for (let value = min; value <= max; value += unit) {
      const left = ((value - min) / span) * 100;
      ticks.push(`<i class="number-tick" style="left:${left}%"><span>${escapeHtml(value)}</span></i>`);
    }
    const points = (Array.isArray(component.focus_points) ? component.focus_points : [])
      .filter((value) => Number.isFinite(Number(value)))
      .map((value) => {
        const numeric = Number(value);
        const left = ((numeric - min) / span) * 100;
        return `<b class="number-point" style="left:${left}%"><span>${escapeHtml(value)}</span></b>`;
      })
      .join("");
    return `
      <div class="number-line-stage">
        <p>${escapeHtml(component.instruction || "先看每个数在数轴上的位置。")}</p>
        <div class="number-line" aria-label="从 ${escapeHtml(min)} 到 ${escapeHtml(max)} 的数轴">
          <div class="number-line-axis"></div>
          ${ticks.join("")}
          ${points}
        </div>
      </div>
    `;
  }

  function renderWorkedExample(component) {
    if (!component || component.type !== "worked_example") return "";
    const steps = Array.isArray(component.steps) ? component.steps.filter(Boolean) : [];
    return `
      <section class="learning-card-panel">
        <h3>看一题</h3>
        <p><strong>${escapeHtml(component.problem || "先看一个标准例题。")}</strong></p>
        ${steps.length ? `
          <ol class="worked-example-steps">
            ${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
          </ol>
        ` : ""}
        ${component.check ? `<p class="common-mistake">${escapeHtml(component.check)}</p>` : ""}
      </section>
    `;
  }

  function renderMicroCheck(component) {
    if (!component || component.type !== "micro_check") return "";
    return `
      <section class="learning-card-check">
        <h3>试一下</h3>
        <div class="micro-check-box">
          <p>${escapeHtml(component.prompt || "用刚才的方法做一个小检查。")}</p>
          <div class="micro-check-actions">
            <button type="button" class="primary" data-preview-action="start-check">开始这一题</button>
            <button type="button" data-preview-action="stuck">我还是没懂</button>
          </div>
        </div>
      </section>
    `;
  }

  function renderCard(card) {
    const essence = componentByPurpose(card, "essence");
    const visual = componentByType(card, "number_line_visual");
    const worked = componentByType(card, "worked_example");
    const check = componentByType(card, "micro_check");
    const mistake = componentByType(card, "common_mistake");
    root.setAttribute("aria-busy", "false");
    root.innerHTML = `
      <section class="learning-card-hero">
        <div>
          <p class="eyebrow">今天先抓住这个模型</p>
          <h2>${escapeHtml(card.title || "学习卡")}</h2>
        </div>
        <p class="one-sentence">${escapeHtml(card.one_sentence || "")}</p>
      </section>

      <div class="learning-card-main">
        <div class="learning-card-panel">
          <h3>${escapeHtml(card.core_model?.title || "怎么想")}</h3>
          <p>${escapeHtml(card.core_model?.body || essence?.body || "")}</p>
          ${renderNumberLine(visual)}
          ${mistake ? `<p class="common-mistake">${escapeHtml(mistake.body || "")}</p>` : ""}
        </div>
        <div>
          ${renderWorkedExample(worked)}
          ${renderMicroCheck(check)}
        </div>
      </div>
    `;
    root.querySelector("[data-preview-action='start-check']")?.addEventListener("click", () => {
      window.location.href = "/";
    });
    root.querySelector("[data-preview-action='stuck']")?.addEventListener("click", () => {
      root.querySelector(".learning-card-hero")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function renderError(error) {
    root.setAttribute("aria-busy", "false");
    root.innerHTML = `
      <section class="card-preview-error">
        <strong>学习卡暂时打不开</strong>
        <p>${escapeHtml(error.message || "请稍后再试。")}</p>
      </section>
    `;
  }

  api("/api/knowledge-cards/number-line")
    .then(renderCard)
    .catch(renderError);
})();
