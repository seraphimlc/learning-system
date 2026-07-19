const CHILD_UI_STATES = Object.freeze({
  LOADING: "loading",
  EMPTY: "empty",
  ACTIVE_TASK: "active_task",
  CHOOSE_REVIEW: "choose_review",
  CURRENT_STEP: "current_step",
  ANALYZING: "analyzing",
  READY_FOR_NEW_KNOWLEDGE: "ready_for_new_knowledge",
  TEACHING: "teaching",
  SUMMARY: "summary",
  SAVING: "saving",
  SAVE_ERROR: "save_error",
  CONTINUE_ERROR: "continue_error",
  UPLOAD_ERROR: "upload_error",
  START_REVIEW_ERROR: "start_review_error",
  NEW_KNOWLEDGE_ERROR: "new_knowledge_error",
  FINISH_ERROR: "finish_error",
  ALL_SUBMITTED_REVIEWING: "all_submitted_reviewing",
  REVIEW_READY: "review_ready",
  BLOCKED: "blocked",
  LOAD_ERROR: "load_error",
});

const V5_CANONICAL_CHILD_STATES = Object.freeze({
  START_RESUME: "start_resume",
  CURRENT_STEP: "current_step",
  ANALYZING_PENDING: "analyzing_pending",
  ASSESSMENT_FEEDBACK: "assessment_feedback",
  FEEDBACK_TEACHING: "feedback_teaching",
  CLARIFY_EVIDENCE: "clarify_evidence",
  READY_FOR_NEW_KNOWLEDGE: "ready_for_new_knowledge",
  BLOCKED: "blocked",
  SUMMARY: "summary",
});

const V5_CHILD_STATE_ALIASES = Object.freeze({
  choose_review: V5_CANONICAL_CHILD_STATES.START_RESUME,
  analyzing: V5_CANONICAL_CHILD_STATES.ANALYZING_PENDING,
  preparing_new_knowledge: V5_CANONICAL_CHILD_STATES.ANALYZING_PENDING,
  teaching: V5_CANONICAL_CHILD_STATES.FEEDBACK_TEACHING,
});

const CHILD_DTO_FORBIDDEN_KEYS = Object.freeze([
  "node_id",
  "node_name",
  "graph",
  "question_id",
  "attempt_id",
  "session_id",
  "plan_id",
  "plan_key",
  "model",
  "provider",
  "agent",
  "rubric",
  "ocr_confidence",
  "queue",
  "job_id",
  "planner_blocked",
  "quality_gates",
  "task_count",
  "policy",
  "planner_policy_version",
  "planning_signal_refs",
]);

const state = {
  data: null,
  activeTaskIndex: 0,
  uiState: CHILD_UI_STATES.LOADING,
  childSupportMode: "try",
  learningSession: null,
  closingResult: null,
  completionMessage: null,
  planId: null,
  reviewPollTimer: null,
  skipNextCompletionBrief: false,
  groupCompletionInFlight: false,
  errorPanel: null,
  pendingEvidence: {
    photoDataUrl: "",
    photoName: "",
  },
  v3ClientSubmitKey: "",
  v3SubmitInFlight: false,
  v3Stuck: false,
  v3SelectedStuckText: "",
  v3ContinueStuck: false,
  v3RecoveryInFlight: false,
  v3FinishInFlight: false,
  v3PollFailureCount: 0,
  v3BlockedRecoveryAttempts: 0,
  lastFocusedV3State: "",
  knowledgeProjection: null,
  knowledgeReady: false,
  learningMaterialization: null,
  questionVisualReady: true,
  activeSurface: "learning_step",
};

const V3_BLOCKED_RECOVERY_MAX_ATTEMPTS = 3;
const V3_BLOCKED_RECOVERY_DELAY_MS = 1000;
const CHILD_SAFE_UNAVAILABLE_MESSAGE = "当前步骤还没有准备好，请稍后再试。";

const $ = (id) => document.getElementById(id);
const sessionStorageKey = (planId) => `son-ai-learning-session:${planId || "latest"}`;
const completionDismissedKey = (planId) => `son-ai-learning-completion-dismissed:${planId || "latest"}`;

function fixtureForChildState(uiState) {
  const tasks = Array.from({ length: 10 }, (_, index) => ({
    position: index + 1,
    kind_label: index === 0 ? "新知识" : "小检测",
    display_topic: `示例任务 ${index + 1}`,
    estimated_minutes: 4,
    question: {
      prompt: `这是第 ${index + 1} 题的展示占位，用于截图和状态测试。`,
      answer_format: "关键步骤 + 答案",
    },
    support: {
      essence_or_hint: "先写关系，再写步骤，最后检查。",
    },
  }));
  const submitted = uiState === CHILD_UI_STATES.REVIEW_READY || uiState === CHILD_UI_STATES.ALL_SUBMITTED_REVIEWING
    ? tasks.map((task) => task.position)
    : [];
  const errorPanelByState = {
    [CHILD_UI_STATES.LOAD_ERROR]: errorPanelCopy(CHILD_UI_STATES.LOAD_ERROR),
    [CHILD_UI_STATES.SAVE_ERROR]: errorPanelCopy(CHILD_UI_STATES.SAVE_ERROR),
    [CHILD_UI_STATES.UPLOAD_ERROR]: errorPanelCopy(CHILD_UI_STATES.UPLOAD_ERROR),
  };
  return {
    schema_version: "2.0.0-child-skeleton",
    today_plan: {
      title: "今天先完成这一组",
      display_key: `fixture-${uiState}`,
      tasks,
    },
    learning_group: {
      handle: "current-learning-group",
      state: uiState,
      submitted_task_positions: submitted,
    },
    error_panel: errorPanelByState[uiState] || null,
    completion: uiState === CHILD_UI_STATES.REVIEW_READY ? {
      closure_status: "planned",
      child_message: {
        child_title: "这一组复盘好了",
        child_feedback: "先看每题的关键点，再开始下一组。",
        review_points: tasks.map((task) => ({
          title: `第${task.position}题：示例复盘`,
          text: "这里显示一条孩子能读懂的复盘点。",
        })),
        next_action_label: "开始下一组",
      },
    } : null,
  };
}

const childSupportModes = [
  ["example", "看例子"],
  ["try", "我来试"],
  ["stuck", "卡住了"],
];

const stuckPrompts = [
  ["看不懂题目", "我卡住了：题目意思没看懂。"],
  ["不知道第一步", "我卡住了：不知道第一步该写什么。"],
  ["算到一半卡住", "我卡住了：算到一半接不下去了。"],
];

const taskTypeLabels = {
  learn: "新知识",
  remediate: "再稳一下",
  rollback: "先补一步",
  prerequisite_probe: "准备一下",
  retest: "小检查",
  practice: "练习",
  diagnostic: "小检测",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}

function currentLocalDayKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function normalizeV5TeachingSections(sections) {
  if (!sections || typeof sections !== "object") return [];
  const coreModel = sections.core_model || sections["核心关系"] || sections["核心模型"] || null;
  return [
    ["essence", sections.essence || null],
    ["core_model", coreModel],
    ["worked_example", sections.worked_example || sections["例题"] || null],
    ["why_it_works", sections.why_it_works || sections["为什么成立"] || null],
    ["next_micro_check", sections.next_micro_check || sections["小检查"] || null],
  ].filter(([, section]) => section && typeof section === "object");
}

function renderV5TeachingSectionBody(key, section) {
  if (key === "worked_example") {
    const steps = Array.isArray(section.steps) ? section.steps.filter(Boolean) : [];
    return `
      ${section.problem ? `<p class="teaching-problem">${escapeHtml(section.problem)}</p>` : ""}
      ${steps.length ? `
        <ol class="teaching-steps">
          ${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
        </ol>
      ` : ""}
      ${section.check ? `<p class="teaching-check">${escapeHtml(section.check)}</p>` : ""}
      ${section.body ? `<p>${escapeHtml(section.body)}</p>` : ""}
    `;
  }
  if (key === "next_micro_check") {
    return `
      <p class="row-meta">点继续后再答；这里先看要用哪一步关系。</p>
      <p>${escapeHtml(section.prompt || section.body || section.text || "")}</p>
      <p class="row-meta">填写时照上面的例题：先找基准乘积，再算多出的影响、少掉的影响，最后相减。</p>
    `;
  }
  if (Array.isArray(section.body)) {
    return `<ul class="teaching-points">${section.body.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }
  return `<p>${escapeHtml(section.body || section.text || "")}</p>`;
}

function renderV5TeachingSections(step) {
  const normalized = normalizeV5TeachingSections(step?.teaching_sections);
  if (!normalized.length) return "";
  return `
    <div class="v5-teaching-sections" aria-label="新知识讲解">
      ${normalized.map(([key, section]) => `
        <section class="v5-teaching-section" data-v5-teaching-section="${escapeAttr(key)}">
          <h3>${escapeHtml(section.title || (
            key === "essence" ? "本质"
              : key === "core_model" ? "核心关系"
                : key === "worked_example" ? "例题"
                  : key === "why_it_works" ? "为什么成立"
                    : "小检查"
          ))}</h3>
          ${renderV5TeachingSectionBody(key, section)}
        </section>
      `).join("")}
    </div>
  `;
}

function renderV51AssessmentFeedback(feedback) {
  if (!feedback || typeof feedback !== "object") return "";
  const improvements = Array.isArray(feedback.improvement_direction)
    ? feedback.improvement_direction.filter(Boolean)
    : [];
  return `
    <section class="assessment-feedback" aria-label="本题解析">
      <div class="assessment-score-row">
        <span>本题得分</span>
        <strong>${escapeHtml(feedback.score_label || "--/10")}</strong>
      </div>
      <dl class="assessment-feedback-list">
        <div><dt>标准答案</dt><dd>${escapeHtml(feedback.reference_answer || "暂时没有可展示的标准答案")}</dd></div>
        <div><dt>与标准答案的差距</dt><dd>${escapeHtml(feedback.answer_gap || "没有影响得分的数学差距")}</dd></div>
        <div>
          <dt>改进方向</dt>
          <dd>${improvements.length
            ? `<ul>${improvements.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
            : "这一步已经完成得很稳"}</dd>
        </div>
        <div><dt>表达判定</dt><dd>${escapeHtml(feedback.expression_judgment || "按数学意图判断表达")}</dd></div>
      </dl>
    </section>
  `;
}

function normalizeInteractionSchema(schema) {
  if (!schema || typeof schema !== "object") return null;
  const type = String(schema.type || "short_text");
  if (!["short_text", "fill_blank", "single_choice", "multi_choice", "formula_input"].includes(type)) return null;
  return {
    type,
    title: String(schema.title || ""),
    schema_version: String(schema.schema_version || ""),
    allow_explanation: schema.allow_explanation !== false,
    requires_explanation: schema.requires_explanation === true || schema.explanation_required === true,
    explanation_label: String(schema.explanation_label || "补充说明"),
    answer_placeholder: String(schema.answer_placeholder || schema.placeholder || ""),
    fields: Array.isArray(schema.fields)
      ? schema.fields
        .filter((field) => field && field.id && field.label)
        .slice(0, 8)
        .map((field) => ({
          id: String(field.id),
          label: String(field.label),
          placeholder: String(field.placeholder || ""),
          prefix: String(field.prefix || ""),
          suffix: String(field.suffix || ""),
        }))
      : [],
    choices: Array.isArray(schema.choices)
      ? schema.choices
        .filter((choice) => choice && choice.id && choice.label)
        .slice(0, 8)
        .map((choice) => ({
          id: String(choice.id),
          label: String(choice.label),
        }))
      : [],
    formula_label: String(schema.formula_label || ""),
    placeholder: String(schema.placeholder || ""),
  };
}

function canonicalSegmentsHtml(segments, expectedSource) {
  return window.ChildPromptRenderer?.segmentsHtml(segments, expectedSource) ?? null;
}

function canonicalPromptHtml(step) {
  return window.ChildPromptRenderer?.promptHtml(step) ?? null;
}

function canonicalInlineHtml(rendering, expectedText) {
  return window.ChildPromptRenderer?.inlineHtml(rendering, expectedText) ?? null;
}

function canonicalInteractionRenderingValid(schema, rendering) {
  return window.ChildPromptRenderer?.interactionRenderingValid(schema, rendering) === true;
}

function renderInteractionAnswerControls(schema, rendering = null) {
  const normalized = normalizeInteractionSchema(schema);
  if (!normalized) return "";
  if (normalized.type === "fill_blank") {
    return `
      <fieldset class="interaction-card" data-interaction-kind="fill_blank">
        <legend class="interaction-title">${canonicalInlineHtml(rendering?.title, normalized.title || "填写每一项") ?? escapeHtml(normalized.title || "填写每一项")}</legend>
        <div class="interaction-fields">
          ${normalized.fields.map((field) => `
            <label class="interaction-field">
              <span>${canonicalInlineHtml(rendering?.fields?.find((entry) => entry.id === field.id)?.label, field.label) ?? escapeHtml(field.label)}</span>
              <div class="interaction-input-row">
                ${field.prefix ? `<span>${canonicalInlineHtml(rendering?.fields?.find((entry) => entry.id === field.id)?.prefix, field.prefix) ?? escapeHtml(field.prefix)}</span>` : ""}
                <input type="text" inputmode="text" data-interaction-field="${escapeAttr(field.id)}" placeholder="${escapeAttr(field.placeholder || "")}">
                ${field.suffix ? `<span>${canonicalInlineHtml(rendering?.fields?.find((entry) => entry.id === field.id)?.suffix, field.suffix) ?? escapeHtml(field.suffix)}</span>` : ""}
              </div>
            </label>
          `).join("")}
        </div>
      </fieldset>
    `;
  }
  if (normalized.type === "single_choice" || normalized.type === "multi_choice") {
    const inputType = normalized.type === "single_choice" ? "radio" : "checkbox";
    const name = "interaction-choice-current";
    return `
      <fieldset class="interaction-card" data-interaction-kind="${escapeAttr(normalized.type)}">
        <legend class="interaction-title">${canonicalInlineHtml(rendering?.title, normalized.title || "选择答案") ?? escapeHtml(normalized.title || "选择答案")}</legend>
        <div class="interaction-choices">
          ${normalized.choices.map((choice) => `
            <label class="interaction-choice">
              <input type="${inputType}" name="${escapeAttr(name)}" value="${escapeAttr(choice.id)}" data-interaction-choice="${escapeAttr(choice.id)}">
              <span>${canonicalInlineHtml(rendering?.choices?.find((entry) => entry.id === choice.id)?.label, choice.label) ?? escapeHtml(choice.label)}</span>
            </label>
          `).join("")}
        </div>
      </fieldset>
    `;
  }
  if (normalized.type === "formula_input") {
    return `
      <div class="interaction-card" data-interaction-kind="formula_input">
        <label class="interaction-field">
          <span>${canonicalInlineHtml(rendering?.formula_label || rendering?.title, normalized.formula_label || normalized.title || "算式") ?? escapeHtml(normalized.formula_label || normalized.title || "算式")}</span>
          <input type="text" data-interaction-formula placeholder="${escapeAttr(normalized.placeholder || "写出算式")}">
        </label>
      </div>
    `;
  }
  return "";
}

function interactionTypeLabel(type) {
  return {
    short_text: "简答",
    fill_blank: "填空",
    single_choice: "单选",
    multi_choice: "多选",
    formula_input: "公式输入",
  }[type] || "作答";
}

function collectInteractionAnswer(schema) {
  return interactionResponseToEvidenceText(collectInteractionResponse(schema));
}

function collectInteractionResponse(schema, explanationText = "") {
  const normalized = normalizeInteractionSchema(schema);
  if (!normalized) return null;
  const response = {
    schema_version: normalized.schema_version,
    type: normalized.type,
    values: {},
    selected_choices: [],
    formula: "",
    explanation_text: String(explanationText || "").trim(),
  };
  if (normalized.type === "fill_blank") {
    normalized.fields.forEach((field) => {
      const value = document.querySelector(`[data-interaction-field="${CSS.escape(field.id)}"]`)?.value.trim() || "";
      if (value) response.values[field.id] = value;
    });
  } else if (normalized.type === "single_choice" || normalized.type === "multi_choice") {
    const checked = [...document.querySelectorAll("[data-interaction-choice]:checked")];
    checked.forEach((input) => {
      if (normalized.choices.some((item) => item.id === input.value)) response.selected_choices.push(input.value);
    });
  } else if (normalized.type === "formula_input") {
    response.formula = document.querySelector("[data-interaction-formula]")?.value.trim() || "";
  }
  if (
    !Object.keys(response.values).length
    && !response.selected_choices.length
    && !response.formula
  ) return null;
  return response;
}

function interactionResponseToEvidenceText(response) {
  if (!response) return "";
  const normalized = normalizeInteractionSchema(state.data?.current_step?.interaction_schema);
  const lines = [`结构化作答：${interactionTypeLabel(response.type)}`];
  if (response.type === "fill_blank") {
    (normalized?.fields || []).forEach((field) => {
      const value = response.values?.[field.id];
      if (value) lines.push(`${field.label}：${value}`);
    });
  } else if (response.type === "single_choice" || response.type === "multi_choice") {
    (response.selected_choices || []).forEach((choiceId) => {
      const choice = (normalized?.choices || []).find((item) => item.id === choiceId);
      if (choice) lines.push(`选择：${choice.label}`);
    });
  } else if (response.type === "formula_input" && response.formula) {
    lines.push(`${normalized?.formula_label || "算式"}：${response.formula}`);
  }
  return lines.length > 1 ? lines.join("\n") : "";
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => el.classList.remove("show"), 2800);
}

function childSafeErrorMessage(error) {
  const raw = String(error?.message || "");
  if (raw.includes("Unsupported answer photo") || raw.includes("Invalid answer photo")) {
    return "这张照片没读成功，请换一张清楚的 PNG、JPG 或 WebP";
  }
  if (raw.includes("too large") || raw.includes("8 MB")) {
    return "照片太大了，请换一张 8MB 以内的图片";
  }
  if (raw.includes("already has an active submission")) {
    return "这一步已经保存过了，继续下一步就好";
  }
  if (raw.includes("not accepting submissions") || raw.includes("expired")) {
    return "当前步骤状态变了，请重新连接后继续";
  }
  if (raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
    return "网络刚才断了一下，请再试一次";
  }
  return "没保存成功，请再试一次";
}

function childSafeLoadErrorMessage(error) {
  const raw = String(error?.message || "");
  if (raw.includes(CHILD_SAFE_UNAVAILABLE_MESSAGE)) {
    return CHILD_SAFE_UNAVAILABLE_MESSAGE;
  }
  if (raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
    return "网络刚才断了一下，请重新连接";
  }
  return "页面刚才没有连上，请重新连接";
}

function errorPanelCopy(kind, message = "") {
  if (kind === CHILD_UI_STATES.LOAD_ERROR) {
    const unavailable = message === CHILD_SAFE_UNAVAILABLE_MESSAGE;
    return {
      kind,
      title: unavailable ? "当前步骤还没有准备好" : "页面刚才没有连上",
      body: unavailable ? CHILD_SAFE_UNAVAILABLE_MESSAGE : "请再试一次。已经保存过的答案不会因为刷新而改变。",
      actionLabel: unavailable ? "刷新" : "重新连接",
      unavailable,
    };
  }
  if (kind === CHILD_UI_STATES.UPLOAD_ERROR) {
    return {
      kind,
      title: "照片没有选上",
      body: message || "文字答案还在。可以换一张清楚的 PNG、JPG 或 WebP 照片。",
      actionLabel: "重新选择照片",
    };
  }
  if (kind === CHILD_UI_STATES.CONTINUE_ERROR) {
    return {
      kind,
      title: "这次没有继续上",
      body: message || "请再点一次继续。刚才看的内容还在。",
      actionLabel: "再继续一次",
    };
  }
  if (kind === CHILD_UI_STATES.START_REVIEW_ERROR) {
    return {
      kind,
      title: "这次没有开始上",
      body: message || "请再点一次开始。页面会重新准备今天的第一步。",
      actionLabel: "重新开始今天学习",
    };
  }
  if (kind === CHILD_UI_STATES.NEW_KNOWLEDGE_ERROR) {
    return {
      kind,
      title: "新知识还没有准备上",
      body: message || "请再点一次。准备好后会出现讲解。",
      actionLabel: "重新准备新知识",
    };
  }
  if (kind === CHILD_UI_STATES.FINISH_ERROR) {
    return {
      kind,
      title: "总结没有整理好",
      body: message || "请再点一次今天到这里。已经保存的内容还在。",
      actionLabel: "今天到这里，重新整理总结",
    };
  }
  return {
    kind: CHILD_UI_STATES.SAVE_ERROR,
    title: "这次没有保存上",
    body: message || "你写的内容还在。请再保存一次。",
    actionLabel: "再保存一次",
  };
}

function focusErrorPanel() {
  window.requestAnimationFrame(() => {
    const panel = $("childErrorPanel");
    if (!panel.hidden) panel.focus({ preventScroll: true });
  });
}

function setErrorPanel(kind, message = "", focus = true) {
  state.errorPanel = errorPanelCopy(kind, message);
  renderErrorPanel();
  if (focus) focusErrorPanel();
}

function clearErrorPanel(kind = "") {
  if (kind && state.errorPanel?.kind !== kind) return;
  state.errorPanel = null;
  renderErrorPanel();
}

function renderErrorPanel() {
  const panel = $("childErrorPanel");
  const action = $("childErrorActionBtn");
  const detail = state.errorPanel;
  if (!detail) {
    panel.hidden = true;
    panel.removeAttribute("data-error-kind");
    return;
  }
  $("childErrorTitle").textContent = detail.title;
  $("childErrorBody").textContent = detail.body;
  action.textContent = detail.actionLabel;
  panel.dataset.errorKind = detail.kind;
  panel.hidden = false;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.message || payload.error || "请求失败");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function setPrimarySurface(surface) {
  const showMap = surface === "map_home" && state.knowledgeReady;
  const mapSurface = $("view-knowledge-home");
  const learningSurface = $("view-child");
  if (window.KnowledgeViews && !showMap) window.KnowledgeViews.hide();
  state.activeSurface = showMap ? "map_home" : "learning_step";
  mapSurface.hidden = !showMap;
  mapSurface.classList.toggle("active", showMap);
  if (showMap) mapSurface.removeAttribute("inert");
  else mapSurface.setAttribute("inert", "");
  learningSurface.hidden = showMap;
  learningSurface.classList.toggle("active", !showMap);
  if (showMap) learningSurface.setAttribute("inert", "");
  else learningSurface.removeAttribute("inert");
  if (window.KnowledgeViews && showMap) window.KnowledgeViews.show();
  $("pageTitle").textContent = showMap ? "我的数学知识" : "今天的数学学习";
}

function focusLearningStepEntry() {
  window.requestAnimationFrame(() => {
    const learningSurface = $("view-child");
    const canFocus = (element) => Boolean(
      element?.isConnected &&
      element.getClientRects().length > 0 &&
      !element.closest("[hidden], [inert]")
    );
    const heading = $("childHeading");
    if (canFocus(heading)) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      return;
    }
    const primaryActions = [...learningSurface.querySelectorAll("button.primary:not(:disabled)")]
      .filter(canFocus);
    if (primaryActions.length === 1) primaryActions[0].focus({ preventScroll: true });
  });
}

function validateChildBootstrapPayload(payload) {
  if (!payload || typeof payload !== "object") throw new TypeError("child bootstrap is malformed");
  if (!isV3Payload(payload)) return payload;
  const childState = canonicalV5ChildState(payload.child_state);
  const supported = new Set(Object.values(V5_CANONICAL_CHILD_STATES));
  if (!supported.has(childState)) throw new TypeError("child bootstrap state is invalid");
  if ([
    V5_CANONICAL_CHILD_STATES.CURRENT_STEP,
    V5_CANONICAL_CHILD_STATES.FEEDBACK_TEACHING,
    V5_CANONICAL_CHILD_STATES.CLARIFY_EVIDENCE,
  ].includes(childState)) {
    const step = payload.current_step;
    if (
      !step || typeof step !== "object" ||
      !String(step.topic_label || "").trim() ||
      !String(step.prompt || "").trim()
    ) throw new TypeError("child bootstrap current step is invalid");
  }
  return payload;
}

function validateRenderedLearningSurface(payload) {
  const surface = $("view-child");
  const heading = $("childHeading");
  const headingText = String(heading?.textContent || "").trim();
  if (!surface || !headingText || ["准备中", "当前任务"].includes(headingText)) {
    throw new TypeError("focused learning surface did not render a real state");
  }
  if (!isV3Payload(payload)) return;
  const childState = canonicalV5ChildState(payload.child_state);
  const answer = $("childAnswerRaw");
  const form = $("childAttemptForm");
  if ([
    V5_CANONICAL_CHILD_STATES.CURRENT_STEP,
    V5_CANONICAL_CHILD_STATES.CLARIFY_EVIDENCE,
  ].includes(childState)) {
    const prompt = String(payload.current_step?.prompt || "").trim();
    const renderedPrompt = surface.querySelector("[data-child-prompt]");
    const requiredVisualUnavailable = Boolean(
      payload.current_step?.question_visual && !state.questionVisualReady
    );
    const visualError = surface.querySelector("[data-question-visual-error]");
    if (
      !prompt || !renderedPrompt || form?.hidden ||
      (answer?.disabled && !requiredVisualUnavailable) ||
      (requiredVisualUnavailable && visualError?.hidden !== false)
    ) {
      throw new TypeError("focused answer step is not materialized");
    }
  }
  if (childState === V5_CANONICAL_CHILD_STATES.ANALYZING_PENDING) {
    const enabledAnswerControls = surface.querySelectorAll(
      "#childAttemptForm:not([hidden]) input:not(:disabled), #childAttemptForm:not([hidden]) textarea:not(:disabled), #childAttemptForm:not([hidden]) button:not(:disabled)"
    );
    if (enabledAnswerControls.length) throw new TypeError("analyzing state exposed answer controls");
  }
}

async function materializeLearningSurface() {
  if (state.learningMaterialization) return state.learningMaterialization;
  state.learningMaterialization = (async () => {
    await load();
    validateRenderedLearningSurface(state.data);
    setPrimarySurface("learning_step");
    focusLearningStepEntry();
    return state.data;
  })();
  try {
    return await state.learningMaterialization;
  } finally {
    state.learningMaterialization = null;
  }
}

async function handleKnowledgeTarget(request) {
  const result = await api("/api/knowledge-map/select", {
    method: "POST",
    body: JSON.stringify(request),
  });
  const responseHasKey = Boolean(
    result && Object.prototype.hasOwnProperty.call(result, "client_idempotency_key")
  );
  if (
    responseHasKey &&
    String(result.client_idempotency_key || "") !== request.client_idempotency_key
  ) return result;
  const expectedBehavior = result?.status === "applied"
    ? "enter_now"
    : (result?.status === "waiting_for_safe_boundary" ? "wait_for_safe_boundary" : "");
  if (expectedBehavior && result?.result_behavior !== expectedBehavior) {
    const error = new Error("knowledge target result behavior mismatch");
    error.status = 409;
    error.payload = { state: "conflict" };
    throw error;
  }
  if (result?.status === "applied") {
    await materializeLearningSurface();
  }
  return result;
}

function knowledgeSurfaceStateForError(error) {
  if (error?.status === 404) return "disabled";
  if (error?.payload?.state === "stale" || error?.payload?.state === "conflict") return "stale";
  return "unavailable";
}

function initializeKnowledgeSurface(initialState = "skeleton") {
  state.knowledgeReady = true;
  window.KnowledgeViews.initialize({
    root: $("knowledgeHomeMount"),
    initialState,
    onAction: handleKnowledgeTarget,
    onResume: materializeLearningSurface,
    onRetry: retryKnowledgeHome,
  });
  $("knowledgeHomeBtn").hidden = false;
  setPrimarySurface("map_home");
}

function disableKnowledgeSurface() {
  state.knowledgeProjection = null;
  state.knowledgeReady = false;
  if (window.KnowledgeViews) window.KnowledgeViews.destroy();
  $("knowledgeHomeMount").replaceChildren();
  $("knowledgeHomeBtn").hidden = true;
  setPrimarySurface("learning_step");
}

async function loadKnowledgeHome() {
  initializeKnowledgeSurface("skeleton");
  try {
    const projection = await api("/api/knowledge-map");
    state.knowledgeProjection = projection;
    window.KnowledgeViews.setProjection(projection);
    $("dbStatus").textContent = "准备好了";
    return projection;
  } catch (error) {
    state.knowledgeProjection = null;
    if (error?.status === 404) {
      disableKnowledgeSurface();
      throw error;
    }
    initializeKnowledgeSurface(knowledgeSurfaceStateForError(error));
    throw error;
  }
}

async function retryKnowledgeHome() {
  try {
    await loadKnowledgeHome();
  } catch {
    // The child-safe map state remains visible with the same retry/resume choices.
  }
}

function restoreSessionForPlan(planId) {
  const stored = window.localStorage.getItem(sessionStorageKey(planId));
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    window.localStorage.removeItem(sessionStorageKey(planId));
    return null;
  }
}

function rememberSessionForPlan(planId, session) {
  state.learningSession = session;
  window.localStorage.setItem(sessionStorageKey(planId), JSON.stringify(session));
}

async function load() {
  clearErrorPanel();
  $("dbStatus").textContent = "连接中";
  const payload = validateChildBootstrapPayload(await api("/api/child-bootstrap"));
  state.data = payload;
  state.v3PollFailureCount = 0;
  if (canonicalV5ChildState(state.data?.child_state || "") !== V5_CANONICAL_CHILD_STATES.BLOCKED) {
    state.v3BlockedRecoveryAttempts = 0;
  }
  if (isV3Payload(state.data)) {
    state.uiState = v3UiState(state.data.child_state);
    state.planId = "v3-daily-flow";
    state.closingResult = null;
    state.learningSession = null;
    $("dbStatus").textContent = "准备好了";
    render();
    validateRenderedLearningSurface(state.data);
    return;
  }
  state.uiState = CHILD_UI_STATES.ACTIVE_TASK;
  const planId = state.data?.today_plan?.display_key;
  const planChanged = Boolean(state.planId && state.planId !== planId);
  const completion = state.data?.completion || null;
  if (planChanged) {
    state.activeTaskIndex = 0;
    state.closingResult = null;
    state.learningSession = null;
    clearReviewPoll();
  }
  state.planId = planId;
  if (state.skipNextCompletionBrief && completion?.closure_status === "planned") {
    window.localStorage.setItem(completionDismissedKey(planId), "1");
    state.skipNextCompletionBrief = false;
  }
  const completionDismissed = window.localStorage.getItem(completionDismissedKey(planId)) === "1";
  if (
    completion
    && (
      completion.closure_status !== "planned"
      || (!completionDismissed && !state.closingResult)
    )
  ) {
    state.closingResult = completion;
  }
  state.learningSession = restoreSessionForPlan(planId);
  $("dbStatus").textContent = "准备好了";
  render();
  validateRenderedLearningSurface(state.data);
}

function currentPlanTasks() {
  return state.data?.today_plan?.tasks || [];
}

function isV3Payload(payload = state.data) {
  return String(payload?.schema_version || "").startsWith("3.");
}

function canonicalV5ChildState(childState) {
  const raw = String(childState || "");
  return V5_CHILD_STATE_ALIASES[raw] || raw;
}

function v3UiState(childState) {
  const canonical = canonicalV5ChildState(childState);
  if (canonical === V5_CANONICAL_CHILD_STATES.START_RESUME) return CHILD_UI_STATES.CHOOSE_REVIEW;
  if (canonical === V5_CANONICAL_CHILD_STATES.CURRENT_STEP) return CHILD_UI_STATES.CURRENT_STEP;
  if (canonical === V5_CANONICAL_CHILD_STATES.CLARIFY_EVIDENCE) return CHILD_UI_STATES.CURRENT_STEP;
  if (canonical === V5_CANONICAL_CHILD_STATES.ASSESSMENT_FEEDBACK) return CHILD_UI_STATES.REVIEW_READY;
  if (canonical === V5_CANONICAL_CHILD_STATES.FEEDBACK_TEACHING) return CHILD_UI_STATES.TEACHING;
  if (canonical === V5_CANONICAL_CHILD_STATES.ANALYZING_PENDING) return CHILD_UI_STATES.ANALYZING;
  if (canonical === V5_CANONICAL_CHILD_STATES.READY_FOR_NEW_KNOWLEDGE) return CHILD_UI_STATES.READY_FOR_NEW_KNOWLEDGE;
  if (canonical === V5_CANONICAL_CHILD_STATES.SUMMARY) return CHILD_UI_STATES.SUMMARY;
  if (canonical === V5_CANONICAL_CHILD_STATES.BLOCKED) return CHILD_UI_STATES.BLOCKED;
  return CHILD_UI_STATES.LOADING;
}

function v3Message() {
  return state.data?.message || {};
}

function v3AllowedResponseModes(step, { teachingOnly = false, clarify = false } = {}) {
  const raw = Array.isArray(step?.allowed_response_modes) ? step.allowed_response_modes : [];
  const modes = new Set(raw.map((item) => String(item || "")));
  if (!modes.size) {
    const inputMode = step?.answer_input_mode || "text";
    if (teachingOnly || inputMode === "none") modes.add("continue");
    else if (clarify || inputMode === "clarification") {
      modes.add("text");
      modes.add("photo");
      modes.add("text_photo");
      modes.add("clarification");
    } else if (inputMode === "text_photo") {
      modes.add("text");
      modes.add("photo");
      modes.add("text_photo");
    } else if (inputMode === "photo") {
      modes.add("photo");
    } else {
      modes.add("text");
    }
    if (step?.stuck_enabled !== false) modes.add("stuck");
  }
  return modes;
}

function setV3AttemptFormControls({ showForm, allowText, allowPhoto, submitLabel, placeholder, interactionSchema, interactionRendering }) {
  const form = $("childAttemptForm");
  const answerLabel = document.querySelector('label[for="childAnswerRaw"]');
  const textarea = $("childAnswerRaw");
  const interactionPanel = $("interactionAnswerPanel");
  const photoField = document.querySelector(".photo-field");
  const stuckPanel = $("v3StuckChoicePanel");
  const normalizedInteraction = normalizeInteractionSchema(interactionSchema);
  const isShortText = normalizedInteraction?.type === "short_text";
  const allowExplanationText = normalizedInteraction
    ? (isShortText || normalizedInteraction.allow_explanation)
    : allowText;
  form.hidden = !showForm;
  if (answerLabel) {
    answerLabel.hidden = !allowExplanationText;
    answerLabel.textContent = normalizedInteraction
      ? (isShortText
        ? (normalizedInteraction.title || "我的答案")
        : `${normalizedInteraction.explanation_label}${normalizedInteraction.requires_explanation ? "（必填）" : "（可选）"}`)
      : "我的答案和步骤";
  }
  textarea.hidden = !allowExplanationText;
  const explanationRequired = Boolean(
    normalizedInteraction
    && !isShortText
    && normalizedInteraction.requires_explanation
  );
  textarea.required = explanationRequired;
  textarea.setAttribute("aria-required", explanationRequired ? "true" : "false");
  textarea.setAttribute("aria-invalid", "false");
  textarea.setCustomValidity("");
  const attemptError = $("childAttemptError");
  if (attemptError) {
    attemptError.textContent = "";
    attemptError.hidden = true;
  }
  if (allowExplanationText) {
    textarea.placeholder = normalizedInteraction
      ? (normalizedInteraction.answer_placeholder || (
        isShortText
          ? "按你平时的方式写下答案"
          : normalizedInteraction.requires_explanation
            ? "请写一句理由"
            : "可以补一句理由或检查方法"
      ))
      : (placeholder || "写关键步骤、答案；如果卡住，就写卡在哪一步");
  }
  if (interactionPanel) {
    interactionPanel.innerHTML = normalizedInteraction ? renderInteractionAnswerControls(normalizedInteraction, interactionRendering) : "";
    interactionPanel.hidden = !normalizedInteraction;
  }
  if (photoField) photoField.hidden = !allowPhoto;
  if (!allowPhoto) clearChildPhoto();
  if (stuckPanel && !showForm) {
    stuckPanel.hidden = true;
    stuckPanel.innerHTML = "";
  }
  $("childSubmitBtn").textContent = submitLabel || "保存";
}

function setQuestionVisualAnswerEnabled(enabled) {
  const form = $("childAttemptForm");
  if (!form) return;
  form.querySelectorAll("button, input, textarea, select").forEach((control) => {
    control.disabled = !enabled;
  });
}

function renderQuestionVisualForStep(step) {
  const visual = step?.question_visual || null;
  state.questionVisualReady = !visual;
  if (!visual) return;

  const host = document.querySelector("[data-question-visual-host]");
  const error = document.querySelector("[data-question-visual-error]");
  try {
    if (!host || !window.QuestionVisualRenderer?.render) {
      throw new Error("question visual renderer is unavailable");
    }
    window.QuestionVisualRenderer.render(host, visual);
    state.questionVisualReady = true;
    if (error) error.hidden = true;
    setQuestionVisualAnswerEnabled(true);
  } catch (_error) {
    if (host) host.replaceChildren();
    if (error) error.hidden = false;
    state.questionVisualReady = false;
    setQuestionVisualAnswerEnabled(false);
  }
}

function removeSelectedStuckTextFromAnswer() {
  const selected = state.v3SelectedStuckText;
  if (!selected) return;
  const textarea = $("childAnswerRaw");
  const lines = textarea.value.split("\n");
  const index = lines.findIndex((line) => line.trim() === selected.trim());
  if (index >= 0) {
    lines.splice(index, 1);
    textarea.value = lines.join("\n").trim();
  }
}

function updateV3StuckSelection() {
  document.querySelectorAll("[data-v3-stuck-prompt]").forEach((button) => {
    const pressed = button.dataset.v3StuckPrompt === state.v3SelectedStuckText && state.v3Stuck;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    button.classList.toggle("selected", pressed);
  });
  const cancel = document.querySelector("[data-v3-cancel-stuck]");
  if (cancel) cancel.hidden = !state.v3Stuck;
}

function selectV3StuckPrompt(text) {
  removeSelectedStuckTextFromAnswer();
  state.v3SelectedStuckText = text;
  state.v3Stuck = true;
  const textarea = $("childAnswerRaw");
  textarea.value = textarea.value.trim() ? `${textarea.value.trim()}\n${text}` : text;
  updateV3StuckSelection();
  textarea.focus();
}

function cancelV3StuckPrompt() {
  removeSelectedStuckTextFromAnswer();
  state.v3SelectedStuckText = "";
  state.v3Stuck = false;
  updateV3StuckSelection();
  $("childAnswerRaw").focus();
}

function syncV3StuckSelectionFromAnswerText() {
  if (!state.v3Stuck || !state.v3SelectedStuckText) return;
  const answerText = $("childAnswerRaw").value;
  if (answerText.includes(state.v3SelectedStuckText)) return;
  state.v3SelectedStuckText = "";
  state.v3Stuck = false;
  updateV3StuckSelection();
}

function renderV3StuckChoicePanel({ show, prompts }) {
  const panel = $("v3StuckChoicePanel");
  if (!panel) return;
  if (!show) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  panel.hidden = false;
  panel.innerHTML = `
    <p class="stuck-choice-title">如果真的卡住，也可以这样保存</p>
    <div class="stuck-actions v3-stuck-actions" aria-label="卡住了也可以提交">
      ${prompts.map(([label, text]) => `
        <button type="button" data-v3-stuck-prompt="${escapeAttr(text)}" aria-pressed="false">${escapeHtml(label)}</button>
      `).join("")}
    </div>
    <button class="stuck-cancel" type="button" data-v3-cancel-stuck hidden>取消卡住，改成正常作答</button>
  `;
  updateV3StuckSelection();
}

function focusV3HandoffOnce(childState) {
  if (!childState || state.lastFocusedV3State === childState) return;
  state.lastFocusedV3State = childState;
  window.requestAnimationFrame(() => {
    const panel = $("childHandoffState");
    if (!panel.hidden) panel.focus({ preventScroll: true });
  });
}

function renderV3ShellMessage({ title, typeLabel, body, actionLabel, showAction = true, focusState = "" }) {
  clearReviewPoll();
  $("pageTitle").textContent = "今天的数学学习";
  $("childHeading").textContent = title || "准备中";
  $("childTaskType").textContent = typeLabel || "学习";
  $("childProgressText").textContent = "当前步骤";
  $("childPendingText").textContent = "";
  $("childProgressBar").style.width = "0%";
  $("childHandoffState").hidden = false;
  $("childTaskContent").hidden = true;
  $("childAttemptForm").hidden = true;
  $("childHandoffTitle").textContent = title || "准备中";
  $("childHandoffText").textContent = body || "";
  renderReviewPoints(null);
  renderCoachPoints(null);
  $("startNextRoundBtn").textContent = actionLabel || "继续";
  $("startNextRoundBtn").hidden = !showAction;
  $("v3SecondaryActionBtn").hidden = true;
  renderErrorPanel();
  focusV3HandoffOnce(focusState);
}

function renderV3SummaryState() {
  clearReviewPoll();
  const message = v3Message();
  const summary = state.data?.summary || {};
  const summaryRows = [
    ["已确认", summary.what_went_well || ""],
    ["还要练", summary.keep_working_on || ""],
    ["待判断", summary.pending_note || ""],
    ["暂时不能判断", summary.blocked_note || ""],
  ].filter(([, text]) => String(text || "").trim());
  $("pageTitle").textContent = "今天的数学学习";
  $("childHeading").textContent = summary.title || message.title || "今天先到这里";
  $("childTaskType").textContent = "总结";
  $("childProgressText").textContent = "今日总结";
  $("childPendingText").textContent = "";
  $("childProgressBar").style.width = "100%";
  $("childHandoffState").hidden = false;
  $("childTaskContent").hidden = true;
  $("childAttemptForm").hidden = true;
  $("childHandoffTitle").textContent = summary.title || message.title || "今天先到这里";
  $("childHandoffText").textContent = summary.next_action || message.body || "休息一下。";
  $("childReviewPoints").innerHTML = summaryRows.length ? `
    <div class="review-points-title">今日总结</div>
    ${summaryRows.map(([title, text]) => `
      <div class="review-point">
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(text)}</p>
      </div>
    `).join("")}
  ` : "";
  renderCoachPoints(null);
  $("startNextRoundBtn").textContent = message.action_label || "完成今天学习";
  $("startNextRoundBtn").hidden = true;
  $("v3SecondaryActionBtn").hidden = true;
  renderErrorPanel();
  focusV3HandoffOnce("summary");
}

function renderV3CurrentStep() {
  const step = state.data?.current_step || null;
  if (!step) {
    const message = v3Message();
    renderV3ShellMessage({
      title: message.title || "当前步骤还没有准备好",
      typeLabel: "等待",
      body: message.body || "请稍后再试。",
      actionLabel: message.action_label || "刷新",
    });
    return;
  }
  clearReviewPoll();
  const inputMode = step.answer_input_mode || "text";
  const childState = state.data?.child_state || "";
  const canonical = canonicalV5ChildState(childState);
  const isAssessmentFeedback = canonical === V5_CANONICAL_CHILD_STATES.ASSESSMENT_FEEDBACK || step.kind_label === "本题解析";
  const isTeachingOnly = inputMode === "none" || canonical === V5_CANONICAL_CHILD_STATES.FEEDBACK_TEACHING || isAssessmentFeedback || step.kind_label === "讲解";
  const isClarify = canonical === V5_CANONICAL_CHILD_STATES.CLARIFY_EVIDENCE || step.kind_label === "确认一下" || inputMode === "clarification";
  const interactionSchema = !isTeachingOnly ? normalizeInteractionSchema(step.interaction_schema) : null;
  const promptHtml = canonicalPromptHtml(step);
  if (
    promptHtml === null
    || (!isTeachingOnly && !canonicalInteractionRenderingValid(interactionSchema, step.interaction_rendering))
  ) {
    renderV3ShellMessage({
      title: "当前步骤还没有准备好",
      typeLabel: "等待",
      body: "请稍后再试。",
      actionLabel: "刷新",
    });
    $("childAttemptForm").hidden = true;
    return;
  }
  const allowedModes = v3AllowedResponseModes(step, { teachingOnly: isTeachingOnly, clarify: isClarify });
  const allowText = allowedModes.has("text") || allowedModes.has("text_photo") || allowedModes.has("clarification");
  const allowPhoto = allowedModes.has("photo") || allowedModes.has("text_photo") || allowedModes.has("clarification");
  const allowStuck = (allowedModes.has("stuck") || isClarify) && step.stuck_enabled !== false;
  const allowContinue = allowedModes.has("continue") || isTeachingOnly;
  const promptLabel = isAssessmentFeedback ? "解析" : (isTeachingOnly ? "讲解" : (isClarify ? "请补清楚" : "题目"));
  const continueLabel = step.support?.continue_label || (isAssessmentFeedback ? "看完，继续下一步" : "继续小检查");
  const stuckContinueLabel = step.support?.stuck_label || "还是卡住";
  const teachingSectionsHtml = isTeachingOnly && !isAssessmentFeedback ? renderV5TeachingSections(step) : "";
  const assessmentFeedbackHtml = isTeachingOnly ? renderV51AssessmentFeedback(step.assessment_feedback) : "";
  const activeStuckPrompts = isClarify
    ? [...stuckPrompts, ["无法补充，先记为待判断", "我现在无法补充得更清楚，先记为待判断。"]]
    : stuckPrompts;
  $("pageTitle").textContent = "今天的数学学习";
  $("childHeading").textContent = step.topic_label || "当前步骤";
  $("childTaskType").textContent = step.kind_label || "学习";
  $("childProgressText").textContent = "当前步骤";
  $("childPendingText").textContent = "";
  $("childProgressBar").style.width = "0%";
  $("childHandoffState").hidden = true;
  $("childTaskContent").hidden = false;
  $("childTaskContent").innerHTML = `
    <div class="child-support" aria-label="当前步骤">
      <div class="support-card try-card">
        <p class="support-title">${escapeHtml(step.topic_label || "当前步骤")}</p>
        <div class="question-block">
          <span>${escapeHtml(promptLabel)}</span>
          <div class="child-prompt" data-child-prompt data-projection-sha256="${escapeAttr(step.child_surface_projection_sha256 || "")}">${promptHtml}</div>
        </div>
        ${step.question_visual ? `
          <div data-question-visual-host></div>
          <p class="question-visual-error" data-question-visual-error role="alert" hidden>
            题面图未加载，请刷新页面后再作答。
          </p>
        ` : ""}
        ${step.support?.hint && !isAssessmentFeedback ? `<p class="row-meta">${escapeHtml(step.support.hint)}</p>` : ""}
        ${assessmentFeedbackHtml}
        ${teachingSectionsHtml}
        ${allowContinue ? `
          <div class="form-actions v3-step-actions" aria-label="继续学习">
            <button class="primary" type="button" data-v3-continue-step>${escapeHtml(continueLabel)}</button>
            ${allowStuck ? `<button type="button" data-v3-continue-stuck>${escapeHtml(stuckContinueLabel)}</button>` : ""}
          </div>
        ` : ""}
      </div>
    </div>
  `;
  setV3AttemptFormControls({
    showForm: !allowContinue && (allowText || allowPhoto || allowStuck || Boolean(interactionSchema)),
    allowText,
    allowPhoto,
    submitLabel: isClarify ? "保存补充" : "保存",
    placeholder: isClarify
      ? "把刚才没看清的关键步骤、最后答案补清楚；也可以重新拍一张清楚照片"
      : "写关键步骤、答案；如果卡住，就写卡在哪一步",
    interactionSchema,
    interactionRendering: step.interaction_rendering,
  });
  renderV3StuckChoicePanel({
    show: !allowContinue && allowStuck,
    prompts: activeStuckPrompts,
  });
  $("startNextRoundBtn").hidden = true;
  $("v3SecondaryActionBtn").hidden = true;
  renderReviewPoints(null);
  renderCoachPoints(null);
  renderErrorPanel();
  renderQuestionVisualForStep(step);
  state.lastFocusedV3State = "";
  bindV3CurrentStepControls();
}

function renderV3ChildState() {
  const childState = canonicalV5ChildState(state.data?.child_state || "blocked");
  const message = v3Message();
  if (
    childState === V5_CANONICAL_CHILD_STATES.CURRENT_STEP
    || childState === V5_CANONICAL_CHILD_STATES.ASSESSMENT_FEEDBACK
    || childState === V5_CANONICAL_CHILD_STATES.FEEDBACK_TEACHING
    || childState === V5_CANONICAL_CHILD_STATES.CLARIFY_EVIDENCE
  ) {
    renderV3CurrentStep();
    return;
  }
  if (childState === V5_CANONICAL_CHILD_STATES.ANALYZING_PENDING) {
    renderV3ShellMessage({
      title: message.title || "正在看你的步骤",
      typeLabel: "分析中",
      body: message.body || "答案已经保存。文字通常半分钟左右；有照片可能接近一分钟。不用反复点，页面会自动刷新，结果好了会出现下一步。",
      actionLabel: message.action_label || "刷新看看",
    });
    scheduleV3StatePoll();
    return;
  }
  if (childState === V5_CANONICAL_CHILD_STATES.START_RESUME) {
    renderV3ShellMessage({
      title: message.title || "开始今天学习",
      typeLabel: "学习",
      body: message.body || "先做当前这一步，后面会根据你的情况安排复习或新知识。",
      actionLabel: message.action_label || "开始今天学习",
    });
    return;
  }
  if (childState === V5_CANONICAL_CHILD_STATES.READY_FOR_NEW_KNOWLEDGE) {
    renderV3ShellMessage({
      title: message.title || "可以准备新知识了",
      typeLabel: "新知识",
      body: message.body || "等下一步学习内容准备好后继续。",
      actionLabel: message.action_label || "学一个新知识",
    });
    $("v3SecondaryActionBtn").textContent = "今天到这里";
    $("v3SecondaryActionBtn").hidden = false;
    return;
  }
  if (childState === V5_CANONICAL_CHILD_STATES.SUMMARY) {
    renderV3SummaryState();
    return;
  }
  renderV3ShellMessage({
    title: message.title || "今天的学习暂时不能继续",
    typeLabel: "等待",
    body: message.body || "答案已经保存，但现在还不能安全判断。可以再试一次，或今天到这里并记为待判断。",
    actionLabel: "重新检查",
    focusState: "blocked",
  });
  $("v3SecondaryActionBtn").textContent = "今天到这里";
  $("v3SecondaryActionBtn").hidden = false;
  scheduleV3BlockedRecoveryPoll();
}

function bindV3CurrentStepControls() {
  document.querySelectorAll("[data-v3-stuck-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const text = button.dataset.v3StuckPrompt || "";
      selectV3StuckPrompt(text);
    });
  });
  const cancelStuck = document.querySelector("[data-v3-cancel-stuck]");
  if (cancelStuck) cancelStuck.addEventListener("click", cancelV3StuckPrompt);
  document.querySelectorAll("[data-v3-continue-step]").forEach((button) => {
    button.addEventListener("click", () => continueV3CurrentStep(false));
  });
  document.querySelectorAll("[data-v3-continue-stuck]").forEach((button) => {
    button.addEventListener("click", () => continueV3CurrentStep(true));
  });
}

function submittedQuestionIds() {
  const ids = new Set();
  (state.data?.learning_group?.submitted_task_positions || [])
    .forEach((position) => ids.add(position));
  return ids;
}

function childTaskIndex(startIndex = state.activeTaskIndex) {
  const tasks = currentPlanTasks();
  const submitted = submittedQuestionIds();
  if (!tasks.length) return -1;
  const safeStart = Math.min(Math.max(startIndex, 0), tasks.length - 1);
  for (let index = safeStart; index < tasks.length; index += 1) {
    if (!submitted.has(tasks[index].position)) return index;
  }
  for (let index = 0; index < safeStart; index += 1) {
    if (!submitted.has(tasks[index].position)) return index;
  }
  return -1;
}

function currentChildTask() {
  const index = childTaskIndex();
  if (index === -1) return null;
  state.activeTaskIndex = index;
  return currentPlanTasks()[index];
}

function childProgressInfo() {
  const tasks = currentPlanTasks();
  const submitted = submittedQuestionIds();
  const done = tasks.filter((task) => submitted.has(task.position)).length;
  const currentIndex = childTaskIndex();
  return {
    done,
    total: tasks.length,
    currentNumber: currentIndex === -1 ? tasks.length : currentIndex + 1,
  };
}

function taskQuestion(task) {
  return task?.question || {};
}

function renderSupportTabs() {
  return childSupportModes.map(([mode, label]) => `
    <button class="support-tab ${state.childSupportMode === mode ? "active" : ""}" data-child-support="${mode}" role="tab" aria-selected="${state.childSupportMode === mode ? "true" : "false"}" type="button">${label}</button>
  `).join("");
}

function renderExampleSupport(task) {
  const question = taskQuestion(task);
  const support = task.support || {};
  const essence = support.essence_or_hint || "先说清规则，再做题。";
  const answerFormat = question.answer_format || "关键步骤 + 答案";
  return `
    <div class="support-card example-card">
      <p class="support-title">照这个顺序写</p>
      <ol class="support-steps">
        <li>先写一句规则：${escapeHtml(essence)}</li>
        <li>再按“${escapeHtml(answerFormat)}”把关键步骤写出来。</li>
        <li>最后检查符号、单位、括号或等量关系有没有反。</li>
      </ol>
    </div>
  `;
}

function renderTrySupport(task) {
  const question = taskQuestion(task);
  const answerFormat = question.answer_format || "关键步骤 + 答案";
  const support = task.support || {};
  return `
    <div class="support-card try-card">
      <p class="support-title">${escapeHtml(task.display_topic || "当前任务")}</p>
      <p class="thinking-line"><strong>先想：</strong>${escapeHtml(support.essence_or_hint || "先说清规则，再做题。")}</p>
      <div class="question-block">
        <span>题目</span>
        <p>${escapeHtml(question.prompt || "暂无题目")}</p>
      </div>
      <p class="row-meta">这题写：${escapeHtml(answerFormat)}。</p>
      <p class="row-meta">写出你的想法。答案不只看结果，也看方法是不是站得住。</p>
    </div>
  `;
}

function renderStuckSupport() {
  return `
    <div class="support-card stuck-card">
      <p class="support-title">卡住也可以交</p>
      <p>先点一句最像的卡点，或自己写。系统看的是卡在哪里，不是逼你猜答案。</p>
      <div class="stuck-actions">
        ${stuckPrompts.map(([label, text]) => `<button type="button" data-stuck-prompt="${escapeAttr(text)}">${escapeHtml(label)}</button>`).join("")}
      </div>
    </div>
  `;
}

function renderChildSupport(task) {
  const body = state.childSupportMode === "example"
    ? renderExampleSupport(task)
    : state.childSupportMode === "stuck"
      ? renderStuckSupport()
      : renderTrySupport(task);
  return `
    <div class="child-support" aria-label="作答支持">
      <div class="support-tabs" role="tablist" aria-label="作答模式">
        ${renderSupportTabs()}
      </div>
      ${body}
    </div>
  `;
}

function bindChildSupportControls() {
  document.querySelectorAll("[data-child-support]").forEach((button) => {
    button.addEventListener("click", () => {
      state.childSupportMode = button.dataset.childSupport || "try";
      renderChildTask();
      if (state.childSupportMode === "try") $("childAnswerRaw").focus();
    });
  });
  document.querySelectorAll("[data-stuck-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const text = button.dataset.stuckPrompt || "";
      const textarea = $("childAnswerRaw");
      textarea.value = textarea.value.trim() ? `${textarea.value.trim()}\n${text}` : text;
      textarea.focus();
    });
  });
}

function render() {
  if (!state.data) {
    if (state.uiState === CHILD_UI_STATES.LOAD_ERROR) renderLoadErrorState();
    return;
  }
  renderChildTask();
}

function renderLoadErrorState() {
  clearReviewPoll();
  $("pageTitle").textContent = "今天的数学学习";
  const unavailable = state.errorPanel?.unavailable === true;
  $("dbStatus").textContent = unavailable ? "等待" : "连接失败";
  $("childHeading").textContent = unavailable ? "当前步骤还没有准备好" : "页面刚才没有连上";
  $("childTaskType").textContent = unavailable ? "等待" : "重试";
  $("childProgressText").textContent = unavailable ? "暂时不可用" : "还没连接";
  $("childPendingText").textContent = unavailable ? CHILD_SAFE_UNAVAILABLE_MESSAGE : "请再试一次";
  $("childProgressBar").style.width = "0%";
  $("childHandoffState").hidden = true;
  $("childTaskContent").hidden = true;
  $("childAttemptForm").hidden = true;
  renderReviewPoints(null);
  renderCoachPoints(null);
  $("startNextRoundBtn").hidden = true;
  $("v3SecondaryActionBtn").hidden = true;
  renderErrorPanel();
}

function renderChildTask() {
  if (isV3Payload()) {
    renderV3ChildState();
    return;
  }
  $("v3SecondaryActionBtn").hidden = true;
  const task = currentChildTask();
  const closingStatus = state.closingResult?.closure_status || "";
  const lockedHandoff = ["waiting_ai", "blocked", "planned"].includes(closingStatus)
    || (!task && Boolean(state.closingResult));
  const progress = childProgressInfo();
  const percent = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const showCompletionBrief = Boolean(task && !lockedHandoff && state.completionMessage);
  const completionTaskCount = state.closingResult?.child_message?.next_task_count
    || state.completionMessage?.next_task_count
    || 0;
  if (lockedHandoff && closingStatus === "planned") {
    $("childProgressText").textContent = "上一组已完成";
    $("childPendingText").textContent = completionTaskCount ? `下一组 ${completionTaskCount} 题` : "下一组已准备好";
    $("childProgressBar").style.width = "100%";
  } else if (lockedHandoff && closingStatus === "waiting_ai") {
    $("childProgressText").textContent = "这一组已保存";
    $("childPendingText").textContent = `已保存 ${progress.done}`;
    $("childProgressBar").style.width = "100%";
  } else {
    $("childProgressText").textContent = progress.total
      ? `第 ${Math.min(progress.currentNumber, progress.total)} / ${progress.total} 题`
      : "暂无任务";
    $("childPendingText").textContent = `已保存 ${progress.done}`;
    $("childProgressBar").style.width = `${percent}%`;
  }
  if (!progress.total) {
    state.uiState = CHILD_UI_STATES.EMPTY;
    clearErrorPanel();
    clearReviewPoll();
    $("childHandoffState").hidden = false;
    $("childTaskContent").hidden = true;
    $("childAttemptForm").hidden = true;
    $("childHandoffTitle").textContent = "今天先休息一下";
    $("childHeading").textContent = "今天先休息一下";
    $("childTaskType").textContent = "完成";
    $("childHandoffText").textContent = "暂时没有新的数学任务。";
    renderReviewPoints(null);
    renderCoachPoints(null);
    $("startNextRoundBtn").hidden = true;
    return;
  }

  if (!task && state.groupCompletionInFlight && !closingStatus) {
    state.uiState = CHILD_UI_STATES.ALL_SUBMITTED_REVIEWING;
    clearReviewPoll();
    $("childHandoffState").hidden = false;
    $("childTaskContent").hidden = true;
    $("childAttemptForm").hidden = true;
    $("childHandoffTitle").textContent = "正在整理这一组";
    $("childHeading").textContent = "正在整理这一组";
    $("childTaskType").textContent = "批阅";
    $("childHandoffText").textContent = "最后一题已经保存，系统正在启动批阅和复盘。可以先休息，不用守着页面；好了会自动出现下一步。";
    renderReviewPoints(null);
    renderCoachPoints(null);
    $("startNextRoundBtn").hidden = true;
    return;
  }

  $("childHandoffState").hidden = !showCompletionBrief && Boolean(task) && !lockedHandoff;
  $("childTaskContent").hidden = !task || lockedHandoff;
  $("childAttemptForm").hidden = !task || lockedHandoff;

  if (showCompletionBrief) {
    const message = state.completionMessage || {};
    $("childHandoffTitle").textContent = message.child_title || "上一组复盘";
    $("childHandoffText").textContent = message.child_feedback
      ? `${message.child_feedback} ${message.child_action || ""}`.trim()
      : "上一组已经复盘完成，下一组已经准备好。";
    renderReviewPoints(message);
    renderCoachPoints(message);
    $("startNextRoundBtn").hidden = true;
  }

  if (!task || lockedHandoff) {
    const message = state.closingResult?.child_message || {};
    $("childHandoffTitle").textContent = message.child_title || "这一组完成了";
    $("childHeading").textContent = message.child_title || "这一组完成了";
    $("childTaskType").textContent = "完成";
    renderReviewPoints(message);
    renderCoachPoints(message);
    if (closingStatus === "waiting_ai") {
      state.uiState = CHILD_UI_STATES.ALL_SUBMITTED_REVIEWING;
      $("childHandoffText").textContent = message.pending_message || "答案已经保存，正在看你的步骤和照片。通常半分钟到一分半；好了会出现复盘提示和下一组。";
      $("startNextRoundBtn").textContent = "再看一次结果";
      $("startNextRoundBtn").hidden = false;
      scheduleReviewPoll();
    } else if (closingStatus === "blocked") {
      state.uiState = CHILD_UI_STATES.BLOCKED;
      clearReviewPoll();
      $("childHandoffText").textContent = [message.pending_message, message.child_action].filter(Boolean).join(" ") || "答案已经保存。系统需要恢复后继续看这组答案。可以先休息。";
      $("startNextRoundBtn").textContent = "稍后再看";
      $("startNextRoundBtn").hidden = false;
    } else if (closingStatus === "planned") {
      state.uiState = CHILD_UI_STATES.REVIEW_READY;
      clearReviewPoll();
      $("childHandoffText").textContent = message?.child_feedback
        ? `${message.child_feedback} ${message.child_action || ""}`.trim()
        : "答案已经保存，可以离开。系统复盘已完成，下一组任务也准备好了。休息一下再继续。";
      $("startNextRoundBtn").textContent = message.next_action_label || "看讲解，开始下一组";
      $("startNextRoundBtn").hidden = false;
    } else {
      state.uiState = CHILD_UI_STATES.ALL_SUBMITTED_REVIEWING;
      $("childHandoffText").textContent = "答案已经保存，正在批阅中。页面会自动刷新；结果好了会出现复盘提示和下一组。";
      $("startNextRoundBtn").textContent = "刷新批阅状态";
      $("startNextRoundBtn").hidden = false;
      scheduleReviewPoll();
    }
    return;
  }

  if (![CHILD_UI_STATES.SAVE_ERROR, CHILD_UI_STATES.UPLOAD_ERROR].includes(state.uiState)) {
    state.uiState = CHILD_UI_STATES.ACTIVE_TASK;
    clearErrorPanel();
  }
  $("childHeading").textContent = task.display_topic || "当前任务";
  $("childTaskType").textContent = task.kind_label || taskTypeLabels[task.task_type] || "学习";
  $("childTaskContent").innerHTML = renderChildSupport(task);
  $("childSubmitBtn").textContent = progress.done + 1 >= progress.total ? "保存，完成这一组" : "保存，下一题";
  renderErrorPanel();
  bindChildSupportControls();
}

function renderCoachPoints(message) {
  const points = Array.isArray(message?.coach_points) ? message.coach_points : [];
  $("childCoachPoints").innerHTML = points.map((point) => `
    <div class="coach-point">
      <strong>${escapeHtml(point.title || "提示")}</strong>
      <p>${escapeHtml(point.text || "")}</p>
    </div>
  `).join("");
}

function renderReviewPoints(message) {
  const points = Array.isArray(message?.review_points) ? message.review_points : [];
  $("childReviewPoints").innerHTML = points.length ? `
    <div class="review-points-title">本组逐题复盘</div>
    ${points.map((point) => `
      <div class="review-point">
        <strong>${escapeHtml(point.title || "这一题")}</strong>
        <p>${escapeHtml(point.text || "")}</p>
      </div>
    `).join("")}
  ` : "";
}

async function ensureLearningSession() {
  if (state.learningSession?.handle) return state.learningSession;
  state.learningSession = state.data?.learning_group || { handle: "current-learning-group" };
  rememberSessionForPlan(state.data?.today_plan?.display_key, state.learningSession);
  return state.learningSession;
}

async function maybeCloseLearningSession() {
  const nextTask = currentChildTask();
  if (nextTask) return null;
  state.closingResult = await api("/api/learning-sessions/current-learning-group/complete", {
    method: "POST",
    body: JSON.stringify({}),
  });
  return state.closingResult;
}

async function advanceToNextLearningGroup(message = null) {
  clearReviewPoll();
  state.skipNextCompletionBrief = true;
  state.closingResult = null;
  state.learningSession = null;
  state.activeTaskIndex = 0;
  state.completionMessage = message;
  state.groupCompletionInFlight = false;
  await load();
  renderChildTask();
}

function clearReviewPoll() {
  if (!state.reviewPollTimer) return;
  window.clearTimeout(state.reviewPollTimer);
  state.reviewPollTimer = null;
}

function scheduleReviewPoll() {
  clearReviewPoll();
  state.reviewPollTimer = window.setTimeout(async () => {
    try {
      const result = await api("/api/learning-sessions/current-learning-group/complete", {
        method: "POST",
        body: JSON.stringify({}),
      });
      state.closingResult = result;
      if (result?.closure_status === "planned") {
        renderChildTask();
        toast("批阅完成，先看一下复盘");
      } else if (result?.closure_status === "waiting_ai") {
        renderChildTask();
      } else if (result?.closure_status === "blocked") {
        renderChildTask();
      }
    } catch {
      scheduleReviewPoll();
    }
  }, 3500);
}

function scheduleV3StatePoll() {
  clearReviewPoll();
  state.reviewPollTimer = window.setTimeout(async () => {
    try {
      await load();
    } catch (error) {
      state.v3PollFailureCount += 1;
      if (state.v3PollFailureCount >= 2) {
        enterLoadError(error);
      } else {
        toast("连接刚才断了一下，系统会再试一次");
        scheduleV3StatePoll();
      }
    }
  }, 2500);
}

function scheduleV3BlockedRecoveryPoll() {
  if (state.v3RecoveryInFlight) return;
  if (state.v3BlockedRecoveryAttempts >= V3_BLOCKED_RECOVERY_MAX_ATTEMPTS) return;
  clearReviewPoll();
  state.reviewPollTimer = window.setTimeout(async () => {
    if (canonicalV5ChildState(state.data?.child_state || "") !== V5_CANONICAL_CHILD_STATES.BLOCKED) return;
    state.v3BlockedRecoveryAttempts += 1;
    try {
      await load();
    } catch (error) {
      state.v3PollFailureCount += 1;
      if (state.v3PollFailureCount >= 2) {
        enterLoadError(error);
      } else {
        scheduleV3BlockedRecoveryPoll();
      }
    }
  }, V3_BLOCKED_RECOVERY_DELAY_MS);
}

function acceptedImage(file) {
  return ["image/png", "image/jpeg", "image/webp"].includes(file.type);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(new Error("照片读取失败")));
    reader.readAsDataURL(file);
  });
}

function clearChildPhoto() {
  state.pendingEvidence.photoDataUrl = "";
  state.pendingEvidence.photoName = "";
  $("childAnswerPhoto").value = "";
  $("childPhotoThumb").removeAttribute("src");
  $("childPhotoName").textContent = "";
  $("childPhotoPreview").hidden = true;
}

async function handleChildPhotoChange(event) {
  const file = event.currentTarget.files?.[0];
  if (!file) {
    clearChildPhoto();
    return;
  }
  if (!acceptedImage(file)) {
    state.uiState = CHILD_UI_STATES.UPLOAD_ERROR;
    const message = "只支持 PNG、JPG 或 WebP 照片";
    setErrorPanel(CHILD_UI_STATES.UPLOAD_ERROR, message);
    toast(message);
    clearChildPhoto();
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    state.uiState = CHILD_UI_STATES.UPLOAD_ERROR;
    const message = "照片太大，请换一张 8MB 以内的图片";
    setErrorPanel(CHILD_UI_STATES.UPLOAD_ERROR, message);
    toast(message);
    clearChildPhoto();
    return;
  }
  try {
    const dataUrl = await readFileAsDataUrl(file);
    state.uiState = CHILD_UI_STATES.ACTIVE_TASK;
    clearErrorPanel(CHILD_UI_STATES.UPLOAD_ERROR);
    state.pendingEvidence.photoDataUrl = dataUrl;
    state.pendingEvidence.photoName = file.name || "answer-photo";
    $("childPhotoThumb").src = dataUrl;
    $("childPhotoName").textContent = state.pendingEvidence.photoName;
    $("childPhotoPreview").hidden = false;
  } catch (error) {
    state.uiState = CHILD_UI_STATES.UPLOAD_ERROR;
    const message = childSafeErrorMessage(error);
    setErrorPanel(CHILD_UI_STATES.UPLOAD_ERROR, message);
    toast(message);
    clearChildPhoto();
  }
}

function clearPendingEvidenceAfterSave() {
  state.pendingEvidence.photoDataUrl = "";
  state.pendingEvidence.photoName = "";
  $("childAnswerRaw").value = "";
  clearChildPhoto();
}

$("childAttemptForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isV3Payload()) {
    await submitV3CurrentStep();
    return;
  }
  const task = currentChildTask();
  if (!task) return;
  const progressBeforeSave = childProgressInfo();
  const finishingGroup = Boolean(progressBeforeSave.total && progressBeforeSave.done + 1 >= progressBeforeSave.total);
  const answerRaw = $("childAnswerRaw").value.trim();
  if (!answerRaw && !state.pendingEvidence.photoDataUrl) {
    toast("先写一点步骤，或拍一张纸面答案");
    return;
  }
  const button = $("childSubmitBtn");
  state.completionMessage = null;
  state.groupCompletionInFlight = finishingGroup;
  state.uiState = CHILD_UI_STATES.SAVING;
  clearErrorPanel();
  button.disabled = true;
  button.textContent = "正在保存...";
  try {
    const session = await ensureLearningSession();
    const response = await api("/api/child-submissions", {
      method: "POST",
      body: JSON.stringify({
        session_handle: session.handle,
        session_title: "孩子提交",
        task_position: task.position,
        answer_raw: answerRaw,
        answer_photo_data_url: state.pendingEvidence.photoDataUrl || undefined,
        answer_photo_name: state.pendingEvidence.photoName || undefined,
      }),
    });
    state.activeTaskIndex = Math.min(state.activeTaskIndex + 1, Math.max(currentPlanTasks().length - 1, 0));
    clearPendingEvidenceAfterSave();
    await load();
    const closing = await maybeCloseLearningSession();
    state.groupCompletionInFlight = false;
    if (closing?.closure_status === "planned") {
      renderChildTask();
      toast("这一组完成，先看一下复盘");
    } else if (closing?.closure_status === "waiting_ai") {
      renderChildTask();
      toast("这一组完成，系统会继续批阅");
    } else if (closing?.closure_status === "blocked") {
      renderChildTask();
      toast("答案已保存，可以先休息");
    } else {
      toast(response?.review_state === "reviewed" ? "系统已评估，继续下一题" : "已保存，继续下一题");
    }
  } catch (error) {
    state.groupCompletionInFlight = false;
    state.uiState = CHILD_UI_STATES.SAVE_ERROR;
    const message = childSafeErrorMessage(error);
    setErrorPanel(CHILD_UI_STATES.SAVE_ERROR, message);
    toast(message);
  } finally {
    button.disabled = false;
    renderChildTask();
  }
});

async function submitV3CurrentStep() {
  if (state.v3SubmitInFlight) return;
  const step = state.data?.current_step || null;
  if (!step) {
    toast("当前步骤还没准备好");
    return;
  }
  if (step.question_visual && !state.questionVisualReady) {
    toast("题面图还没有加载好，请刷新页面后再试");
    return;
  }
  const freeText = $("childAnswerRaw").value.trim();
  const answerField = $("childAnswerRaw");
  const attemptError = $("childAttemptError");
  const normalizedInteraction = normalizeInteractionSchema(step.interaction_schema);
  if (
    normalizedInteraction?.requires_explanation
    && !freeText
    && !state.pendingEvidence.photoDataUrl
    && !state.v3Stuck
  ) {
    const message = `请先${normalizedInteraction.explanation_label || "说明理由"}`;
    answerField.required = true;
    answerField.setAttribute("aria-required", "true");
    answerField.setAttribute("aria-invalid", "true");
    answerField.setCustomValidity(message);
    if (attemptError) {
      attemptError.textContent = message;
      attemptError.hidden = false;
    }
    toast(message);
    answerField.focus({ preventScroll: true });
    return;
  }
  answerField.setAttribute("aria-invalid", "false");
  answerField.setCustomValidity("");
  if (attemptError) {
    attemptError.textContent = "";
    attemptError.hidden = true;
  }
  const interactionResponse = collectInteractionResponse(step.interaction_schema, freeText);
  const structuredText = interactionResponseToEvidenceText(interactionResponse);
  const answerText = structuredText
    ? [structuredText, freeText ? `补充说明：${freeText}` : ""].filter(Boolean).join("\n")
    : freeText;
  if (!answerText && !state.pendingEvidence.photoDataUrl && !state.v3Stuck) {
    toast(normalizedInteraction ? "先完成这一步的作答" : "先写一点步骤，或拍一张纸面答案");
    return;
  }
  const button = $("childSubmitBtn");
  state.v3SubmitInFlight = true;
  state.uiState = CHILD_UI_STATES.SAVING;
  clearErrorPanel();
  button.disabled = true;
  button.textContent = "正在保存...";
  try {
    state.v3ClientSubmitKey = state.v3ClientSubmitKey || (
      window.crypto?.randomUUID?.() || `submit-${Date.now()}-${Math.random().toString(16).slice(2)}`
    );
    const result = await api("/api/current-step/submit", {
      method: "POST",
      body: JSON.stringify({
        step_handle: step.step_handle,
        position: step.position,
        client_idempotency_key: state.v3ClientSubmitKey,
        answer_text: answerText,
        interaction_response: interactionResponse || undefined,
        answer_photo_data_url: state.pendingEvidence.photoDataUrl || undefined,
        answer_photo_name: state.pendingEvidence.photoName || undefined,
        stuck: state.v3Stuck,
      }),
    });
    state.v3ClientSubmitKey = "";
    state.v3Stuck = false;
    state.v3SelectedStuckText = "";
    clearPendingEvidenceAfterSave();
    if (result && result.child_state) {
      state.data = result;
      state.uiState = v3UiState(result.child_state);
      renderV3ChildState();
    } else {
      await load();
    }
    toast("已保存");
  } catch (error) {
    state.uiState = CHILD_UI_STATES.SAVE_ERROR;
    const message = childSafeErrorMessage(error);
    setErrorPanel(CHILD_UI_STATES.SAVE_ERROR, message);
    toast(message);
  } finally {
    state.v3SubmitInFlight = false;
    button.disabled = false;
    renderChildTask();
  }
}

async function continueV3CurrentStep(stuck = false) {
  const step = state.data?.current_step || null;
  if (!step) {
    toast("当前步骤还没准备好");
    return;
  }
  state.v3ContinueStuck = Boolean(stuck);
  const buttons = document.querySelectorAll("[data-v3-continue-step], [data-v3-continue-stuck]");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    state.data = await api("/api/current-step/continue", {
      method: "POST",
      body: JSON.stringify({
        step_handle: step.step_handle,
        position: step.position,
        stuck: Boolean(stuck),
      }),
    });
    state.v3ContinueStuck = false;
    state.uiState = v3UiState(state.data?.child_state);
    renderV3ChildState();
    toast(stuck ? "已记录卡住，系统会安全安排下一步" : "继续下一步");
  } catch (error) {
    try {
      await load();
      renderV3ChildState();
      toast("已重新连接到当前进度");
    } catch (reloadError) {
      state.uiState = CHILD_UI_STATES.CONTINUE_ERROR;
      const message = "这次没有继续上，刚才看的内容还在。";
      setErrorPanel(CHILD_UI_STATES.CONTINUE_ERROR, message);
      toast(message);
    }
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

$("childAnswerPhoto").addEventListener("change", handleChildPhotoChange);
$("removeChildPhoto").addEventListener("click", clearChildPhoto);

async function retryLoadFromPanel() {
  state.uiState = CHILD_UI_STATES.LOADING;
  state.data = null;
  clearErrorPanel();
  try {
    await load();
  } catch (error) {
    enterLoadError(error);
  }
}

async function startV3ReviewFlow() {
  try {
    state.data = await api("/api/daily-flow/review/start", {
      method: "POST",
      body: JSON.stringify({ client_day_key: currentLocalDayKey() }),
    });
    state.uiState = v3UiState(state.data?.child_state);
    renderV3ChildState();
  } catch (error) {
    state.uiState = CHILD_UI_STATES.START_REVIEW_ERROR;
    setErrorPanel(CHILD_UI_STATES.START_REVIEW_ERROR);
    toast(childSafeLoadErrorMessage(error));
  }
}

async function startV3NewKnowledge() {
  try {
    state.data = await api("/api/daily-flow/new-knowledge/start", {
      method: "POST",
      body: JSON.stringify({ client_day_key: currentLocalDayKey() }),
    });
    state.uiState = v3UiState(state.data?.child_state);
    renderV3ChildState();
  } catch (error) {
    state.uiState = CHILD_UI_STATES.NEW_KNOWLEDGE_ERROR;
    setErrorPanel(CHILD_UI_STATES.NEW_KNOWLEDGE_ERROR);
    toast(childSafeLoadErrorMessage(error));
  }
}

async function finishV3Flow() {
  if (state.v3FinishInFlight) return;
  const button = $("v3SecondaryActionBtn");
  const previousLabel = button.textContent;
  state.v3FinishInFlight = true;
  clearReviewPoll();
  button.disabled = true;
  button.textContent = "正在整理总结";
  try {
    state.data = await api("/api/daily-flow/finish", {
      method: "POST",
      body: JSON.stringify({ client_day_key: currentLocalDayKey() }),
    });
    state.uiState = v3UiState(state.data?.child_state);
    renderV3ChildState();
  } catch (error) {
    state.uiState = CHILD_UI_STATES.FINISH_ERROR;
    setErrorPanel(CHILD_UI_STATES.FINISH_ERROR);
    toast("总结没有整理好，请再试一次");
  } finally {
    state.v3FinishInFlight = false;
    button.disabled = false;
    button.textContent = previousLabel;
  }
}

function handleErrorActionClick() {
  const kind = state.errorPanel?.kind;
  if (kind === CHILD_UI_STATES.LOAD_ERROR) {
    retryLoadFromPanel();
    return;
  }
  if (kind === CHILD_UI_STATES.SAVE_ERROR) {
    $("childAttemptForm").requestSubmit();
    return;
  }
  if (kind === CHILD_UI_STATES.CONTINUE_ERROR) {
    retryLoadFromPanel();
    return;
  }
  if (kind === CHILD_UI_STATES.START_REVIEW_ERROR) {
    startV3ReviewFlow();
    return;
  }
  if (kind === CHILD_UI_STATES.NEW_KNOWLEDGE_ERROR) {
    startV3NewKnowledge();
    return;
  }
  if (kind === CHILD_UI_STATES.FINISH_ERROR) {
    finishV3Flow();
    return;
  }
  if (kind === CHILD_UI_STATES.UPLOAD_ERROR) {
    $("childAnswerPhoto").click();
  }
}

$("childErrorActionBtn").addEventListener("click", handleErrorActionClick);
$("childAnswerRaw").addEventListener("input", syncV3StuckSelectionFromAnswerText);
$("childAnswerRaw").addEventListener("input", () => {
  const answerField = $("childAnswerRaw");
  const attemptError = $("childAttemptError");
  answerField.setAttribute("aria-invalid", "false");
  answerField.setCustomValidity("");
  if (attemptError) {
    attemptError.textContent = "";
    attemptError.hidden = true;
  }
});

async function enterNextLearningGroup() {
  clearReviewPoll();
  state.skipNextCompletionBrief = true;
  state.closingResult = null;
  state.completionMessage = null;
  state.learningSession = null;
  state.activeTaskIndex = 0;
  state.groupCompletionInFlight = false;
  await load();
  window.localStorage.setItem(completionDismissedKey(state.planId), "1");
  state.closingResult = null;
  state.completionMessage = null;
  state.groupCompletionInFlight = false;
  renderChildTask();
}

async function refreshCompletionResult() {
  clearReviewPoll();
  state.groupCompletionInFlight = true;
  try {
    state.closingResult = await api("/api/learning-sessions/current-learning-group/complete", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.groupCompletionInFlight = false;
    renderChildTask();
  } catch (error) {
    state.groupCompletionInFlight = false;
    toast(childSafeErrorMessage(error));
    renderChildTask();
  }
}

async function handleStartNextRoundClick(event) {
  event?.preventDefault?.();
  if (isV3Payload()) {
    await handleV3PrimaryAction();
    return;
  }
  window.localStorage.setItem("son-ai-learning-last-next-click", String(Date.now()));
  const closureStatus = state.closingResult?.closure_status || "";
  if (closureStatus === "planned") {
    await enterNextLearningGroup();
    return;
  }
  if (closureStatus === "waiting_ai") {
    await refreshCompletionResult();
    return;
  }
  if (closureStatus === "blocked") {
    clearReviewPoll();
    toast("答案已经保存，可以先休息，稍后回来继续");
    return;
  }
  await refreshCompletionResult();
}

async function handleV3PrimaryAction() {
  const childState = state.data?.child_state || "";
  if (childState === "choose_review" || childState === "start_resume") {
    await startV3ReviewFlow();
    return;
  }
  if (childState === "ready_for_new_knowledge") {
    await startV3NewKnowledge();
    return;
  }
  if (childState === "blocked") {
    if (state.v3RecoveryInFlight) return;
    state.v3RecoveryInFlight = true;
    state.v3BlockedRecoveryAttempts = 0;
    clearReviewPoll();
    renderV3ShellMessage({
      title: "正在重新检查",
      typeLabel: "恢复中",
      body: "刚才的答案还在。系统正在重新检查可以从哪里继续，请稍等一下。",
      showAction: false,
      focusState: "recovery",
    });
    try {
      await load();
    } catch (error) {
      enterLoadError(error);
    } finally {
      state.v3RecoveryInFlight = false;
    }
    return;
  }
  const step = state.data?.current_step || null;
  if (step && (step.answer_input_mode === "none" || childState === "teaching")) {
    await continueV3CurrentStep(false);
    return;
  }
  try {
    await load();
  } catch (error) {
    enterLoadError(error);
  }
}

$("startNextRoundBtn").onclick = handleStartNextRoundClick;

$("knowledgeHomeBtn").addEventListener("click", () => {
  if (state.knowledgeReady) setPrimarySurface("map_home");
});

$("v3SecondaryActionBtn").addEventListener("click", async () => {
  if (!isV3Payload()) return;
  const childState = state.data?.child_state || "";
  if (!["ready_for_new_knowledge", "blocked"].includes(childState)) return;
  await finishV3Flow();
});

function enterLoadError(error) {
  state.uiState = CHILD_UI_STATES.LOAD_ERROR;
  state.data = null;
  $("dbStatus").textContent = "连接失败";
  const message = childSafeLoadErrorMessage(error);
  setErrorPanel(CHILD_UI_STATES.LOAD_ERROR, message);
  renderLoadErrorState();
  focusErrorPanel();
  toast(message);
}

function applyFixtureForChildState(uiState) {
  clearReviewPoll();
  state.activeTaskIndex = 0;
  state.childSupportMode = "try";
  state.learningSession = null;
  state.closingResult = null;
  state.completionMessage = null;
  state.groupCompletionInFlight = false;
  state.pendingEvidence.photoDataUrl = "";
  state.pendingEvidence.photoName = "";
  const fixture = fixtureForChildState(uiState);
  state.uiState = uiState;
  if (uiState === CHILD_UI_STATES.LOAD_ERROR) {
    state.data = null;
    state.errorPanel = fixture.error_panel;
    renderLoadErrorState();
    focusErrorPanel();
    return fixture;
  }
  state.data = fixture;
  state.planId = fixture.today_plan.display_key;
  if (uiState === CHILD_UI_STATES.REVIEW_READY || uiState === CHILD_UI_STATES.ALL_SUBMITTED_REVIEWING || uiState === CHILD_UI_STATES.BLOCKED) {
    state.closingResult = fixture.completion || { closure_status: uiState === CHILD_UI_STATES.BLOCKED ? "blocked" : "waiting_ai" };
  }
  if (uiState === CHILD_UI_STATES.SAVE_ERROR || uiState === CHILD_UI_STATES.UPLOAD_ERROR) {
    state.errorPanel = fixture.error_panel;
  } else {
    state.errorPanel = null;
  }
  renderChildTask();
  if (uiState === CHILD_UI_STATES.SAVE_ERROR) {
    $("childAnswerRaw").value = "我已经写了一些步骤，准备再保存一次。";
    focusErrorPanel();
  } else if (uiState === CHILD_UI_STATES.UPLOAD_ERROR) {
    $("childAnswerRaw").value = "文字答案还在，可以重新选择照片。";
    focusErrorPanel();
  }
  return fixture;
}

async function initializeApplication() {
  try {
    await loadKnowledgeHome();
  } catch {
    try {
      await load();
      setPrimarySurface("learning_step");
    } catch (error) {
      setPrimarySurface("learning_step");
      enterLoadError(error);
    }
  }
}

initializeApplication();

window.ChildLearningShell = Object.freeze({
  CHILD_UI_STATES,
  CHILD_DTO_FORBIDDEN_KEYS,
  fixtureForChildState,
  applyFixtureForChildState,
  currentState: () => {
    if ([
      CHILD_UI_STATES.LOAD_ERROR,
      CHILD_UI_STATES.SAVE_ERROR,
      CHILD_UI_STATES.CONTINUE_ERROR,
      CHILD_UI_STATES.UPLOAD_ERROR,
      CHILD_UI_STATES.START_REVIEW_ERROR,
      CHILD_UI_STATES.NEW_KNOWLEDGE_ERROR,
      CHILD_UI_STATES.FINISH_ERROR,
      CHILD_UI_STATES.SAVING,
    ].includes(state.uiState)) {
      return state.uiState;
    }
    if (isV3Payload(state.data)) return canonicalV5ChildState(state.data?.child_state);
    return state.uiState;
  },
});
