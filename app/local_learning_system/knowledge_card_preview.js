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

  const COMPONENT_LABELS = {
    text_explanation: "先抓本质",
    solution_audit_checklist: "检查过程",
    mark_key_relation: "找关键关系",
    find_faulty_work: "找错因",
    rewrite_solution: "改写过程",
    operation_order_trace: "标下一步",
    error_spotting: "找错误",
    fill_missing_step: "补关键一步",
    symbol_transform: "判断变形",
    range_slider_estimate: "先估范围",
    benchmark_compare: "找基准",
    reasonableness_meter: "判断合理性",
    rough_compute_then_refine: "估算再精算",
    choose_plausible_answer: "排除离谱答案",
    micro_check: "试一下"
  };

  function componentLabel(component) {
    return component?.title || COMPONENT_LABELS[component?.type] || "学习一步";
  }

  function renderInteraction(interaction) {
    if (!interaction || typeof interaction !== "object") return "";
    const prompt = interaction.prompt || interaction.problem || interaction.expression || "";
    const options = Array.isArray(interaction.options) ? interaction.options : [];
    const ranges = Array.isArray(interaction.ranges) ? interaction.ranges : [];
    const checks = Array.isArray(interaction.check_items) ? interaction.check_items : [];
    return `
      <div class="preview-interaction">
        ${prompt ? `<p>${escapeHtml(prompt)}</p>` : ""}
        ${options.length || ranges.length ? `
          <div class="preview-options">
            ${(options.length ? options : ranges).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          </div>
        ` : ""}
        ${checks.length ? `
          <ul>
            ${checks.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>
        ` : ""}
        ${interaction.benchmark ? `<p class="preview-benchmark">基准：${escapeHtml(interaction.benchmark)}</p>` : ""}
        ${interaction.expected_check ? `<p class="preview-benchmark">${escapeHtml(interaction.expected_check)}</p>` : ""}
      </div>
    `;
  }

  function renderGenericComponent(component, index) {
    const hasInteractionPrompt = Boolean(component?.interaction?.prompt);
    const body = component.body || (hasInteractionPrompt ? "" : (component.prompt || ""));
    const interaction = renderInteraction(component.interaction);
    return `
      <section class="learning-card-panel preview-step-card">
        <span class="preview-step-index">${index + 1}</span>
        <h3>${escapeHtml(componentLabel(component))}</h3>
        ${body ? `<p>${escapeHtml(body)}</p>` : ""}
        ${interaction}
      </section>
    `;
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
    const isDraftV2 = String(card.schema_version || "") === "knowledge-card-child-draft.v2";
    const title = card.title || "学习卡";
    const titleNode = document.querySelector("[data-card-preview-title]");
    if (titleNode) titleNode.textContent = title;
    document.title = `${title}学习卡`;
    root.setAttribute("aria-busy", "false");
    if (isDraftV2) {
      const components = Array.isArray(card.components) ? card.components : [];
      root.innerHTML = `
        <section class="learning-card-hero">
          <div>
            <p class="eyebrow">草稿预览</p>
            <h2>${escapeHtml(title)}</h2>
          </div>
          <p class="one-sentence">${escapeHtml(card.one_sentence || "")}</p>
          <p class="draft-preview-note">这是草稿卡片的孩子端预览，用来检查讲法和交互方向；正式启用前还要经过审核和激活。</p>
        </section>

        <div class="learning-card-main is-draft">
          <div class="learning-card-panel">
            <h3>${escapeHtml(card.core_model?.title || "怎么想")}</h3>
            <p>${escapeHtml(card.core_model?.body || "")}</p>
          </div>
          <div class="preview-step-list">
            ${components.map(renderGenericComponent).join("")}
          </div>
        </div>
      `;
      return;
    }
    root.innerHTML = `
      <section class="learning-card-hero">
        <div>
          <p class="eyebrow">今天先抓住这个模型</p>
          <h2>${escapeHtml(title)}</h2>
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

  const query = new URLSearchParams(window.location.search);
  const nodeId = query.get("node_id") || "M-G7-NUMBER-LINE";
  const draft = query.get("draft") || "";
  api(`/api/knowledge-cards/preview?node_id=${encodeURIComponent(nodeId)}${draft ? `&draft=${encodeURIComponent(draft)}` : ""}`)
    .then(renderCard)
    .catch(renderError);
})();
