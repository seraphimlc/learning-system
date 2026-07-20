(function () {
  "use strict";

  const VIEW_NAMES = new Set(["mind_map", "graph"]);
  const FILTERS = new Set(["all", "recorded", "reinforce", "untested"]);
  const RECOVERABLE_ACTION_STATUSES = new Set([
    "submitting",
    "response_unknown",
    "waiting_for_safe_boundary",
  ]);
  const ACTIVE_VIEW_STORAGE_KEY = "son-ai-knowledge-views:v5.1:active-view";
  const state = {
    root: null,
    projection: null,
    nodeByHandle: new Map(),
    moduleByHandle: new Map(),
    relations: [],
    activeView: "mind_map",
    selectedHandle: "",
    query: "",
    filter: "all",
    collapsed: {},
    selectedModuleHandle: "",
    graphFocusMode: "fit_all",
    graphViewportStored: false,
    graphHasEntered: false,
    graphEdgeFrame: 0,
    rovingHandle: "",
    pendingAction: null,
    actionInFlight: null,
    actionFeedback: null,
    resumeInFlight: false,
    resumeAuthorityKnown: true,
    detailViewportBeforeOpen: null,
    sheetCameraAdjusted: false,
    modalInertRecords: [],
    viewports: {
      mind_map: { scale: 1, x: 0, y: 0 },
      graph: { scale: 1, x: 0, y: 0 },
    },
    onAction: null,
    onResume: null,
    onRetry: null,
    surfaceState: "skeleton",
    projectionStale: false,
    visible: false,
    originButton: null,
    media: null,
    mediaListener: null,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function storagePrefix() {
    return `son-ai-knowledge-views:v5.1:${state.projection?.projection_version || "pending"}`;
  }

  function storageKey(suffix) {
    return `${storagePrefix()}:${suffix}`;
  }

  function actionDescriptorsForNode(node) {
    const descriptors = Array.isArray(node?.action_descriptors)
      ? node.action_descriptors
      : [];
    const allowed = new Set(Array.isArray(node?.allowed_actions) ? node.allowed_actions : []);
    const valid = descriptors.every((item) =>
      item && typeof item === "object" &&
      typeof item.action === "string" && item.action &&
      typeof item.label === "string" && item.label.trim() &&
      ["primary", "secondary"].includes(item.role) &&
      typeof item.enabled === "boolean" &&
      typeof item.pending_label === "string" && item.pending_label.trim() &&
      ["enter_now", "wait_for_safe_boundary", "preview"].includes(item.result_behavior) &&
      (item.enabled || (typeof item.disabled_reason === "string" && item.disabled_reason.trim()))
    );
    if (!valid) return [];
    if (descriptors.filter((item) => item.role === "primary").length > 1) return [];
    if (descriptors.filter((item) => item.role === "secondary" && item.enabled).length > 1) return [];
    if (descriptors.some((item) => item.enabled && !allowed.has(item.action))) return [];
    return descriptors;
  }

  function actionDescriptor(node, action) {
    return actionDescriptorsForNode(node).find((item) => item.action === action) || null;
  }

  function minimumScaleFor(view) {
    if (view === "graph") return isMobile() ? 0.6 : 0.14;
    return isMobile() ? 0.28 : 0.35;
  }

  function clampViewport(value, view) {
    const candidate = value && typeof value === "object" ? value : {};
    const scale = Number(candidate.scale);
    const x = Number(candidate.x);
    const y = Number(candidate.y);
    const minimumScale = minimumScaleFor(view);
    return {
      scale: Number.isFinite(scale) ? Math.min(1.6, Math.max(minimumScale, scale)) : 1,
      x: Number.isFinite(x) ? Math.min(2400, Math.max(-2400, x)) : 0,
      y: Number.isFinite(y) ? Math.min(1800, Math.max(-1800, y)) : 0,
    };
  }

  function loadJsonPreference(key, fallback) {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  function loadPreferences() {
    const legacyStoredView = window.localStorage.getItem(storageKey("active-view"));
    const storedView = window.localStorage.getItem(ACTIVE_VIEW_STORAGE_KEY) || legacyStoredView;
    state.activeView = VIEW_NAMES.has(storedView) ? storedView : state.projection.default_view;
    if (VIEW_NAMES.has(storedView)) {
      window.localStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, storedView);
    }
    state.viewports.mind_map = clampViewport(
      loadJsonPreference(storageKey("mind_map:viewport"), { scale: 1, x: 0, y: 0 }),
      "mind_map"
    );
    const graphViewportKey = storageKey("graph:viewport");
    const storedGraphFocusMode = window.localStorage.getItem(storageKey("graph:focus-mode"));
    const normalizedGraphFocusMode = ["fit_all", "node_focus", "module_focus"].includes(storedGraphFocusMode)
      ? storedGraphFocusMode
      : "fit_all";
    const graphFocusContextValid =
      normalizedGraphFocusMode === "fit_all" ||
      (normalizedGraphFocusMode === "node_focus" && state.nodeByHandle.has(state.selectedHandle)) ||
      (normalizedGraphFocusMode === "module_focus" && state.moduleByHandle.has(state.selectedModuleHandle));
    state.graphFocusMode = graphFocusContextValid ? normalizedGraphFocusMode : "fit_all";
    state.graphViewportStored = Boolean(window.localStorage.getItem(graphViewportKey)) && graphFocusContextValid;
    state.viewports.graph = state.graphViewportStored
      ? clampViewport(loadJsonPreference(graphViewportKey, { scale: 1, x: 0, y: 0 }), "graph")
      : clampViewport({ scale: 1, x: 0, y: 0 }, "graph");
    if (!graphFocusContextValid) {
      window.localStorage.removeItem(graphViewportKey);
      window.localStorage.removeItem(storageKey("graph:focus-mode"));
    }
    const collapsed = loadJsonPreference(storageKey("mind_map:collapsed"), {});
    state.collapsed = collapsed && typeof collapsed === "object" ? collapsed : {};
    const pendingAction = loadJsonPreference(storageKey("target-action"), null);
    const pendingNode = state.nodeByHandle.get(pendingAction?.handle);
    state.pendingAction = (
      pendingAction &&
      typeof pendingAction === "object" &&
      pendingAction.projection_version === state.projection.projection_version &&
      pendingNode &&
      typeof pendingAction.action === "string" &&
      Boolean(actionDescriptor(pendingNode, pendingAction.action)?.enabled) &&
      RECOVERABLE_ACTION_STATUSES.has(pendingAction.status) &&
      typeof pendingAction.client_idempotency_key === "string" &&
      pendingAction.client_idempotency_key
    ) ? pendingAction : null;
    if (!state.pendingAction) window.localStorage.removeItem(storageKey("target-action"));
  }

  function saveActiveView() {
    window.localStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, state.activeView);
  }

  function saveViewport(view) {
    window.localStorage.setItem(storageKey(`${view}:viewport`), JSON.stringify(state.viewports[view]));
    if (view === "graph") {
      state.graphViewportStored = true;
      window.localStorage.setItem(storageKey("graph:focus-mode"), state.graphFocusMode);
    }
  }

  function saveCollapsed() {
    window.localStorage.setItem(storageKey("mind_map:collapsed"), JSON.stringify(state.collapsed));
  }

  function savePendingAction() {
    if (state.pendingAction) {
      window.localStorage.setItem(storageKey("target-action"), JSON.stringify(state.pendingAction));
    } else {
      window.localStorage.removeItem(storageKey("target-action"));
    }
  }

  function stableActionRequest(node, action) {
    if (state.actionInFlight) return null;
    if (
      state.pendingAction &&
      state.pendingAction.handle === node.handle &&
      state.pendingAction.action === action &&
      state.pendingAction.projection_version === state.projection.projection_version
    ) {
      return {
        handle: state.pendingAction.handle,
        projection_version: state.pendingAction.projection_version,
        action: state.pendingAction.action,
        client_idempotency_key: state.pendingAction.client_idempotency_key,
      };
    }
    if (state.pendingAction) return null;
    const key = window.crypto?.randomUUID?.() || `kv51-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    state.pendingAction = {
      handle: node.handle,
      projection_version: state.projection.projection_version,
      action,
      client_idempotency_key: key,
      status: "submitting",
    };
    savePendingAction();
    return {
      handle: state.pendingAction.handle,
      projection_version: state.pendingAction.projection_version,
      action: state.pendingAction.action,
      client_idempotency_key: state.pendingAction.client_idempotency_key,
    };
  }

  function settlePendingAction(result, request) {
    const requestKey = String(request?.client_idempotency_key || "");
    const responseHasKey = Boolean(
      result && Object.prototype.hasOwnProperty.call(result, "client_idempotency_key")
    );
    const responseKey = responseHasKey ? String(result.client_idempotency_key || "") : "";
    if (
      !state.pendingAction ||
      !requestKey ||
      state.actionInFlight !== request ||
      state.actionInFlight.client_idempotency_key !== requestKey ||
      (responseHasKey && responseKey !== requestKey) ||
      state.pendingAction.client_idempotency_key !== requestKey ||
      state.pendingAction.handle !== request.handle ||
      state.pendingAction.action !== request.action ||
      state.pendingAction.projection_version !== request.projection_version
    ) {
      if (state.pendingAction) state.pendingAction.status = "response_unknown";
      savePendingAction();
      return false;
    }
    const status = String(result?.status || "");
    if (["applied", "blocked"].includes(status)) state.pendingAction = null;
    else if (state.pendingAction) state.pendingAction.status = status || "waiting_for_safe_boundary";
    savePendingAction();
    return true;
  }

  function actionCanRun(node, action) {
    const descriptor = actionDescriptor(node, action);
    if (!descriptor?.enabled || !state.resumeAuthorityKnown) return false;
    if (state.actionInFlight || state.projectionStale) return false;
    if (!state.pendingAction) return true;
    return state.pendingAction.handle === node.handle &&
      state.pendingAction.action === action &&
      state.pendingAction.projection_version === state.projection?.projection_version;
  }

  function syncActionControls() {
    const node = state.nodeByHandle.get(state.selectedHandle);
    const status = state.root?.querySelector("[data-knowledge-action-status]");
    state.root?.querySelectorAll("[data-action-name]").forEach((button) => {
      const descriptor = node && actionDescriptor(node, button.dataset.actionName);
      const allowed = descriptor && actionCanRun(node, button.dataset.actionName);
      button.disabled = !allowed;
      button.textContent = (
        state.actionInFlight?.handle === node?.handle &&
        state.actionInFlight?.action === button.dataset.actionName
      ) ? descriptor.pending_label : (descriptor?.label || button.textContent);
      if (status && !status.hidden) button.setAttribute("aria-describedby", status.id);
      else button.removeAttribute("aria-describedby");
      if (!allowed && state.pendingAction) {
        button.title = state.actionInFlight
          ? "正在确认刚才的学习目标"
          : "请先完成刚才保留的学习目标";
      } else {
        const disabledReason = !descriptor?.enabled
          ? descriptor?.disabled_reason
          : (!state.resumeAuthorityKnown ? "请先重新确认当前学习状态" : "");
        if (disabledReason) button.title = disabledReason;
        else button.removeAttribute("title");
      }
    });
  }

  function setActionFeedback(kind, message, handle = state.selectedHandle) {
    state.actionFeedback = {
      kind: String(kind || "info"),
      message: String(message || ""),
      handle: String(handle || ""),
    };
    syncActionFeedback();
  }

  function syncActionFeedback() {
    const status = state.root?.querySelector("[data-knowledge-action-status]");
    if (!status) return;
    let feedback = state.actionFeedback;
    if (feedback && feedback.handle !== state.selectedHandle) {
      feedback = state.pendingAction
        ? {
            kind: "pending",
            message: "正在准备刚才选择的学习目标，请稍等。",
          }
        : null;
    }
    status.hidden = !feedback?.message;
    status.textContent = feedback?.message || "";
    status.dataset.feedbackKind = feedback?.kind || "";
    syncActionControls();
  }

  function isMobile() {
    return Boolean(state.media?.matches);
  }

  function shellHtml() {
    return `
      <div class="knowledge-home" data-knowledge-home>
        <header class="knowledge-home-header">
          <div>
            <p class="knowledge-kicker">我的数学知识</p>
            <h2 tabindex="-1" data-knowledge-heading>从一张图里找到下一步</h2>
          </div>
          <div class="knowledge-current-wrap">
            <p class="knowledge-current" data-current-learning></p>
            <button type="button" data-resume-learning>继续当前学习</button>
            <div class="knowledge-resume-error" data-resume-error hidden tabindex="-1">
              <p>当前学习暂时没有打开，刚才的内容还在。可以再试一次。</p>
              <button type="button" data-resume-retry>再试一次</button>
            </div>
          </div>
        </header>
        <div class="knowledge-home-content" data-knowledge-content>
          <section class="knowledge-state-panel" data-map-state-panel aria-live="polite">
            <h3 data-map-state-title>正在准备知识首页</h3>
            <p data-map-state-body>正在核对知识关系和学习记录。</p>
            <button type="button" data-map-retry hidden>重新加载</button>
          </section>
          <div class="knowledge-toolbar">
            <div class="knowledge-view-switch" role="radiogroup" aria-label="知识展示方式">
              <label>
                <input type="radio" name="knowledge-view-mode" value="mind_map">
                <span>导图</span>
              </label>
              <label>
                <input type="radio" name="knowledge-view-mode" value="graph">
                <span>图谱</span>
              </label>
            </div>
            <form class="knowledge-search" role="search">
              <label for="knowledgeSearchInput">查找知识</label>
              <div>
                <input id="knowledgeSearchInput" type="search" autocomplete="off" placeholder="输入知识名称">
                <button type="button" aria-label="清除搜索" data-clear-search>×</button>
              </div>
            </form>
            <label class="knowledge-filter">
              <span>学习状态</span>
              <select data-knowledge-filter>
                <option value="all">全部</option>
                <option value="recorded">有学习记录</option>
                <option value="reinforce">待巩固</option>
                <option value="untested">未测试</option>
              </select>
            </label>
            <label class="knowledge-module-filter">
              <span>知识模块</span>
              <select data-module-select>
                <option value="">选择知识模块</option>
              </select>
            </label>
            <div class="knowledge-viewport-tools" role="toolbar" aria-label="视图大小">
              <button type="button" aria-label="缩小" data-viewport-action="zoom-out">−</button>
              <button type="button" aria-label="适合窗口" data-viewport-action="fit">□</button>
              <button type="button" aria-label="放大" data-viewport-action="zoom-in">＋</button>
              <button type="button" aria-label="聚焦已选知识" data-viewport-action="focus-selected">◎</button>
            </div>
          </div>
          <div class="knowledge-legend" aria-label="图例">
            <span><i class="legend-state" aria-hidden="true">●</i>状态由文字、图标、形状和颜色共同表示</span>
            <span class="legend-incoming"><i class="legend-edge" aria-hidden="true">→</i>先会：进入所选知识</span>
            <span class="legend-outgoing"><i class="legend-outgoing-icon" aria-hidden="true">→</i>后面会用：离开所选知识</span>
            <span class="legend-bridge"><i aria-hidden="true">⇢</i>跨模块桥梁</span>
          </div>
          <div class="knowledge-result-summary" role="status" aria-live="polite" data-result-summary></div>
          <div class="knowledge-workspace">
            <section class="knowledge-viewport" role="region" aria-label="我的数学知识导图" tabindex="0" data-knowledge-view="mind_map">
              <div class="knowledge-world mind-map-world" data-knowledge-world="mind_map"></div>
            </section>
            <section class="knowledge-viewport" role="region" aria-label="我的数学知识图谱" tabindex="0" data-knowledge-view="graph" hidden>
              <div class="knowledge-world graph-world" data-knowledge-world="graph"></div>
            </section>
          </div>
        </div>
        <aside class="knowledge-detail" data-knowledge-detail hidden></aside>
        <div class="knowledge-live-region" role="status" aria-live="polite" aria-atomic="true" data-knowledge-live></div>
      </div>
    `;
  }

  function initialize(options = {}) {
    destroy();
    if (!(options.root instanceof HTMLElement)) throw new TypeError("KnowledgeViews root is required");
    state.root = options.root;
    state.onAction = typeof options.onAction === "function" ? options.onAction : null;
    state.onResume = typeof options.onResume === "function" ? options.onResume : null;
    state.onRetry = typeof options.onRetry === "function" ? options.onRetry : null;
    state.root.innerHTML = shellHtml();
    state.media = window.matchMedia("(max-width: 700px)");
    state.mediaListener = () => syncDetailMode();
    state.media.addEventListener("change", state.mediaListener);
    bindShell();
    setSurfaceState(options.initialState || "skeleton");
    if (options.projection) setProjection(options.projection);
    show();
    return window.KnowledgeViews;
  }

  function bindShell() {
    state.root.querySelectorAll('input[name="knowledge-view-mode"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        if (!radio.checked || !VIEW_NAMES.has(radio.value)) return;
        state.activeView = radio.value;
        const enteringGraph = radio.value === "graph";
        const firstGraphEntry = enteringGraph && !state.graphHasEntered;
        if (enteringGraph) state.graphHasEntered = true;
        saveActiveView();
        renderActiveView();
        window.requestAnimationFrame(() => {
          if (state.selectedHandle && !selectedNodeIsInsideViewport(state.activeView)) {
            centerSelectedNodeInView(state.activeView);
          } else if (enteringGraph && firstGraphEntry && !state.graphViewportStored) {
            fitAndPersistViewport("graph");
          }
        });
        announce(
          radio.value === "mind_map"
            ? "已打开知识导图"
            : "已打开知识图谱。可以搜索或选择知识模块查看知识点。"
        );
      });
    });
    const search = state.root.querySelector("#knowledgeSearchInput");
    search.addEventListener("input", () => {
      const hadQuery = Boolean(state.query);
      state.query = search.value.trim();
      if (hadQuery && !state.query && state.selectedHandle && state.activeView === "mind_map") {
        restoreSelectedMindContext();
      } else {
        renderActiveView();
      }
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && search.value) {
        search.value = "";
        state.query = "";
        if (state.selectedHandle && state.activeView === "mind_map") restoreSelectedMindContext();
        else renderActiveView();
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const exact = [...state.nodeByHandle.values()].find(
          (node) => node.name.localeCompare(state.query, "zh-CN", { sensitivity: "base" }) === 0
        );
        if (exact) focusNode(exact.handle);
      }
    });
    state.root.querySelector("[data-clear-search]").addEventListener("click", () => {
      search.value = "";
      state.query = "";
      if (state.selectedHandle && state.activeView === "mind_map") restoreSelectedMindContext();
      else renderActiveView();
      search.focus();
    });
    state.root.querySelector("[data-knowledge-filter]").addEventListener("change", (event) => {
      state.filter = FILTERS.has(event.target.value) ? event.target.value : "all";
      renderWithSelectionGuard();
    });
    state.root.querySelector("[data-module-select]").addEventListener("change", (event) => {
      state.selectedModuleHandle = state.moduleByHandle.has(event.target.value) ? event.target.value : "";
      state.graphFocusMode = state.selectedModuleHandle ? "module_focus" : "fit_all";
      renderWithSelectionGuard();
      if (state.activeView === "graph" && state.selectedModuleHandle) fitReadableGraphNodes();
    });
    state.root.querySelectorAll("[data-viewport-action]").forEach((button) => {
      button.addEventListener("click", () => updateViewport(button.dataset.viewportAction));
    });
    state.root.querySelector("[data-resume-learning]").addEventListener("click", requestResume);
    state.root.querySelector("[data-resume-retry]").addEventListener("click", requestResume);
    state.root.querySelector("[data-map-retry]").addEventListener("click", () => {
      if (state.onRetry) state.onRetry();
    });
    state.root.querySelectorAll(".knowledge-viewport").forEach(bindViewportGestures);
    const graphWorld = state.root.querySelector('[data-knowledge-world="graph"]');
    const finishGraphCamera = (event) => {
      if (event.propertyName === "transform") {
        updateGraphEdgeGeometry();
        positionGraphOverviewAnchors();
      }
    };
    graphWorld.addEventListener("transitionend", finishGraphCamera);
    graphWorld.addEventListener("transitioncancel", finishGraphCamera);
  }

  function bindViewportGestures(region) {
    const view = region.dataset.knowledgeView;
    const pointers = new Map();
    let drag = null;
    let pinch = null;
    const distance = () => {
      const values = [...pointers.values()];
      if (values.length < 2) return 0;
      return Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y);
    };
    region.addEventListener("pointerdown", (event) => {
      if (
        (event.pointerType === "mouse" && event.button !== 0) ||
        event.target.closest("button, input, select, textarea, summary, a, [role='button']")
      ) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      region.setPointerCapture(event.pointerId);
      if (pointers.size === 1) {
        drag = {
          x: event.clientX,
          y: event.clientY,
          originX: state.viewports[view].x,
          originY: state.viewports[view].y,
          active: false,
        };
      } else if (pointers.size === 2) {
        pinch = { distance: distance(), scale: state.viewports[view].scale };
        drag = null;
      }
    });
    region.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size >= 2 && pinch) {
        const nextDistance = distance();
        if (pinch.distance > 0 && nextDistance > 0) {
          const minimumScale = minimumScaleFor(view);
          state.viewports[view].scale = Math.min(
            1.6,
            Math.max(minimumScale, pinch.scale * nextDistance / pinch.distance)
          );
          applyViewport(view);
        }
        return;
      }
      if (!drag) return;
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (!drag.active && Math.hypot(dx, dy) < 8) return;
      drag.active = true;
      event.preventDefault();
      state.viewports[view].x = drag.originX + dx;
      state.viewports[view].y = drag.originY + dy;
      applyViewport(view);
    });
    const finish = (event) => {
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 1) {
        const remaining = [...pointers.values()][0];
        drag = {
          x: remaining.x,
          y: remaining.y,
          originX: state.viewports[view].x,
          originY: state.viewports[view].y,
          active: false,
        };
      } else if (!pointers.size) {
        drag = null;
      }
      saveViewport(view);
    };
    region.addEventListener("pointerup", finish);
    region.addEventListener("pointercancel", finish);
    region.addEventListener("wheel", (event) => {
      if (document.activeElement !== region && !event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const viewport = state.viewports[view];
      const minimumScale = minimumScaleFor(view);
      viewport.scale = Math.min(1.6, Math.max(minimumScale, viewport.scale + (event.deltaY < 0 ? 0.08 : -0.08)));
      saveViewport(view);
      applyViewport(view);
    }, { passive: false });
  }

  function setProjection(projection) {
    if (!projection || projection.schema_version !== "5.1-knowledge-views") {
      throw new TypeError("KnowledgeViews projection is invalid");
    }
    state.projection = projection;
    state.nodeByHandle = new Map(projection.nodes.map((node) => [node.handle, node]));
    state.moduleByHandle = new Map(projection.modules.map((module) => [module.handle, module]));
    state.relations = Array.isArray(projection.relationships) ? projection.relationships : [];
    const selectionInvalid = Boolean(
      state.selectedHandle && !state.nodeByHandle.has(state.selectedHandle)
    );
    if (selectionInvalid) {
      const detail = state.root.querySelector("[data-knowledge-detail]");
      if (detail && !detail.hidden) closeDetail(false);
      state.selectedHandle = "";
      state.rovingHandle = "";
      state.originButton = null;
      state.graphFocusMode = "fit_all";
    }
    state.projectionStale = false;
    state.resumeAuthorityKnown = true;
    state.resumeInFlight = false;
    setSurfaceState(projection.nodes.length ? "ready" : "empty");
    loadPreferences();
    state.graphHasEntered = state.activeView === "graph";
    const moduleSelect = state.root.querySelector("[data-module-select]");
    moduleSelect.replaceChildren(new Option("选择知识模块", ""));
    [...state.moduleByHandle.values()]
      .sort((a, b) => a.order - b.order)
      .forEach((module) => moduleSelect.add(new Option(module.name, module.handle)));
    const current = state.root.querySelector("[data-current-learning]");
    current.textContent = projection.current_learning?.label || "先从熟悉的地方看起";
    const resume = state.root.querySelector("[data-resume-learning]");
    const currentWrap = state.root.querySelector(".knowledge-current-wrap");
    const notStarted = projection.current_learning?.state === "not_started";
    currentWrap.hidden = notStarted;
    resume.hidden = notStarted;
    resume.textContent = projection.current_learning?.action_label || "继续当前学习";
    resume.disabled = false;
    currentWrap.setAttribute("aria-busy", "false");
    state.root.querySelector("[data-resume-error]").hidden = true;
    renderActiveView();
    if (selectionInvalid) window.requestAnimationFrame(focusCurrentViewHeading);
    if (state.activeView === "graph" && !state.graphViewportStored) {
      window.requestAnimationFrame(() => fitAndPersistViewport("graph"));
    }
  }

  async function requestResume() {
    if (!state.onResume || state.resumeInFlight) return;
    const wrap = state.root?.querySelector(".knowledge-current-wrap");
    const action = state.root?.querySelector("[data-resume-learning]");
    const error = state.root?.querySelector("[data-resume-error]");
    const retry = state.root?.querySelector("[data-resume-retry]");
    state.resumeInFlight = true;
    state.resumeAuthorityKnown = true;
    if (error) error.hidden = true;
    if (wrap) wrap.setAttribute("aria-busy", "true");
    if (action) {
      action.disabled = true;
      action.textContent = state.projection?.current_learning?.pending_label || "正在打开";
    }
    if (retry) retry.disabled = true;
    try {
      await state.onResume();
    } catch {
      state.resumeAuthorityKnown = false;
      if (error) {
        error.hidden = false;
        error.focus({ preventScroll: true });
      }
      announce("当前学习暂时没有打开，刚才的内容还在。可以再试一次。");
    } finally {
      state.resumeInFlight = false;
      if (wrap) wrap.setAttribute("aria-busy", "false");
      if (action) {
        action.disabled = false;
        action.textContent = state.projection?.current_learning?.action_label || "继续当前学习";
      }
      if (retry) retry.disabled = false;
      syncActionControls();
    }
  }

  function setSurfaceState(nextState) {
    if (!state.root) return;
    const allowed = new Set(["skeleton", "ready", "unavailable", "empty", "stale", "disabled"]);
    state.surfaceState = allowed.has(nextState) ? nextState : "unavailable";
    const panel = state.root.querySelector("[data-map-state-panel]");
    const content = state.root.querySelector("[data-knowledge-content]");
    const toolbar = state.root.querySelector(".knowledge-toolbar");
    const workspace = state.root.querySelector(".knowledge-workspace");
    const retry = panel.querySelector("[data-map-retry]");
    const copy = {
      skeleton: ["正在准备知识首页", "正在核对知识关系和学习记录。"],
      unavailable: ["知识首页暂时不可用", "当前学习仍然保留，可以稍后重新加载。"],
      empty: ["暂时没有可显示的知识点", "可以清除筛选，或继续当前学习。"],
      stale: ["知识首页已经更新", "请重新加载后再选择学习目标。"],
      disabled: ["知识首页暂未开启", "请继续当前学习。"],
    };
    const ready = state.surfaceState === "ready";
    panel.hidden = ready;
    toolbar.hidden = !ready;
    workspace.hidden = !ready;
    retry.hidden = !["unavailable", "stale"].includes(state.surfaceState);
    if (!ready) {
      const [title, body] = copy[state.surfaceState] || copy.unavailable;
      panel.querySelector("[data-map-state-title]").textContent = title;
      panel.querySelector("[data-map-state-body]").textContent = body;
    }
    content.dataset.mapState = state.surfaceState;
  }

  function matchesFilter(node) {
    if (state.filter === "recorded") return node.learning_state !== "untested";
    if (state.filter === "reinforce") return ["developing", "needs_support", "needs_prerequisite"].includes(node.learning_state);
    if (state.filter === "untested") return node.learning_state === "untested";
    return true;
  }

  function matchingNodes() {
    const query = state.query.toLocaleLowerCase("zh-CN");
    return [...state.nodeByHandle.values()].filter((node) => {
      const moduleName = state.moduleByHandle.get(node.module_handle)?.name || "";
      const queryMatch = !query || `${node.name} ${moduleName}`.toLocaleLowerCase("zh-CN").includes(query);
      return queryMatch && matchesFilter(node);
    });
  }

  function visibleNodes() {
    const matches = matchingNodes();
    return state.query ? matches.slice(0, 6) : matches;
  }

  function elementCanReceiveFocus(element) {
    return Boolean(
      element?.isConnected &&
      !element.disabled &&
      !element.closest("[hidden], [inert]") &&
      element.getClientRects().length > 0
    );
  }

  function focusCurrentViewHeading() {
    const heading = state.root?.querySelector("[data-knowledge-heading]");
    if (elementCanReceiveFocus(heading)) heading.focus({ preventScroll: true });
  }

  function selectedNodeIsInsideViewport(view) {
    const region = state.root?.querySelector(`[data-knowledge-view="${view}"]`);
    const selected = region?.querySelector(`[data-node-handle="${state.selectedHandle}"]`);
    if (!region || !elementCanReceiveFocus(selected)) return false;
    const regionRect = region.getBoundingClientRect();
    const selectedRect = selected.getBoundingClientRect();
    return selectedRect.left >= regionRect.left && selectedRect.top >= regionRect.top &&
      selectedRect.right <= regionRect.right && selectedRect.bottom <= regionRect.bottom;
  }

  function centerSelectedNodeInView(view) {
    if (!state.selectedHandle) return;
    if (view === "graph") {
      state.graphFocusMode = "node_focus";
      renderActiveView();
      fitReadableGraphNodes();
      return;
    }
    const region = state.root?.querySelector('[data-knowledge-view="mind_map"]');
    const selected = region?.querySelector(`[data-node-handle="${state.selectedHandle}"]`);
    if (!region || !elementCanReceiveFocus(selected)) return;
    const regionRect = region.getBoundingClientRect();
    const selectedRect = selected.getBoundingClientRect();
    const viewport = state.viewports.mind_map;
    viewport.x += regionRect.left + regionRect.width / 2 - (selectedRect.left + selectedRect.width / 2);
    viewport.y += regionRect.top + regionRect.height / 2 - (selectedRect.top + selectedRect.height / 2);
    state.viewports.mind_map = clampViewport(viewport, "mind_map");
    saveViewport("mind_map");
    applyViewport("mind_map");
  }

  function clearSelectionAndDetail() {
    const detail = state.root?.querySelector("[data-knowledge-detail]");
    if (detail && !detail.hidden) closeDetail(false);
    state.selectedHandle = "";
    state.rovingHandle = "";
    state.originButton = null;
    state.graphFocusMode = state.selectedModuleHandle ? "module_focus" : "fit_all";
    renderActiveView();
    window.requestAnimationFrame(focusCurrentViewHeading);
  }

  function renderWithSelectionGuard() {
    if (state.selectedHandle && state.activeView === "mind_map") {
      expandMindAncestors(state.selectedHandle);
    }
    renderActiveView();
    if (!state.selectedHandle) return;
    window.requestAnimationFrame(() => {
      const selected = state.root?.querySelector(
        `[data-knowledge-view="${state.activeView}"] [data-node-handle="${state.selectedHandle}"]`
      );
      if (!elementCanReceiveFocus(selected)) clearSelectionAndDetail();
    });
  }

  function renderActiveView() {
    if (!state.root || !state.projection) return;
    state.root.querySelectorAll('input[name="knowledge-view-mode"]').forEach((radio) => {
      radio.checked = radio.value === state.activeView;
    });
    state.root.querySelectorAll("[data-knowledge-view]").forEach((region) => {
      region.hidden = region.dataset.knowledgeView !== state.activeView;
    });
    const matches = matchingNodes();
    let nodes = state.query ? matches.slice(0, 6) : matches;
    if (state.activeView === "mind_map" && state.selectedModuleHandle) {
      nodes = nodes.filter((node) => node.module_handle === state.selectedModuleHandle);
    }
    if (!state.query && state.selectedHandle && state.nodeByHandle.has(state.selectedHandle)) {
      const selected = state.nodeByHandle.get(state.selectedHandle);
      if (!nodes.some((node) => node.handle === selected.handle)) nodes.push(selected);
    }
    const summary = state.root.querySelector("[data-result-summary]");
    summary.replaceChildren();
    if (nodes.length) {
      summary.textContent = state.query && matches.length > 6
        ? `显示前 6 个结果，共找到 ${matches.length} 个知识点`
        : `找到 ${nodes.length} 个知识点`;
    } else {
      summary.append("没有符合条件的知识点。");
      const clear = document.createElement("button");
      clear.type = "button";
      clear.textContent = "清除条件";
      clear.addEventListener("click", clearSearchAndFilters);
      summary.append(clear);
    }
    if (state.activeView === "mind_map") renderMindMap(nodes);
    else renderGraph(nodes);
    applyViewport(state.activeView);
    if (state.selectedHandle) renderDetail();
    syncRovingTabindex();
  }

  function clearSearchAndFilters() {
    state.query = "";
    state.filter = "all";
    state.selectedModuleHandle = "";
    state.root.querySelector("#knowledgeSearchInput").value = "";
    state.root.querySelector("[data-knowledge-filter]").value = "all";
    state.root.querySelector("[data-module-select]").value = "";
    if (state.selectedHandle && state.activeView === "mind_map") restoreSelectedMindContext();
    else renderActiveView();
  }

  function nodeButton(node) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `knowledge-node-button state-${node.learning_state || "untested"}`;
    button.dataset.nodeHandle = node.handle;
    button.dataset.learningState = node.learning_state || "untested";
    button.tabIndex = -1;
    const stateIcons = {
      stable: "✓",
      developing: "↗",
      needs_support: "!",
      needs_prerequisite: "↶",
      untested: "◇",
    };
    const icon = document.createElement("span");
    icon.className = "knowledge-state-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = stateIcons[node.learning_state] || "◇";
    const label = document.createElement("span");
    label.className = "knowledge-node-label";
    label.textContent = node.name;
    button.append(icon, label);
    const stateLabel = document.createElement("span");
    stateLabel.className = "knowledge-node-state";
    stateLabel.textContent = node.learning_state_label || "还没有留下学习记录";
    button.append(stateLabel);
    button.setAttribute(
      "aria-label",
      `${node.name}，状态：${node.learning_state_label || "还没有留下学习记录"}`
    );
    button.setAttribute("aria-pressed", String(node.handle === state.selectedHandle));
    if (node.handle === state.selectedHandle) button.classList.add("is-selected");
    if (node.recommended) button.classList.add("is-recommended");
    button.addEventListener("click", () => selectNode(node.handle, button));
    button.addEventListener("keydown", handleNodeKeydown);
    return button;
  }

  function focusableNodeButtons() {
    return [...state.root.querySelectorAll(".knowledge-node-button, .graph-overview-marker")].filter(
      (button) => !button.disabled && !button.closest("[hidden]") && button.getClientRects().length > 0
    );
  }

  function syncRovingTabindex() {
    const allButtons = [...state.root.querySelectorAll(".knowledge-node-button, .graph-overview-marker")];
    allButtons.forEach((button) => { button.tabIndex = -1; });
    const buttons = focusableNodeButtons();
    if (!buttons.length) {
      state.rovingHandle = "";
      return;
    }
    const active = buttons.find((button) => button.dataset.nodeHandle === state.rovingHandle)
      || buttons.find((button) => button.dataset.nodeHandle === state.selectedHandle)
      || buttons[0];
    active.tabIndex = 0;
    state.rovingHandle = active.dataset.nodeHandle || "";
  }

  function handleNodeKeydown(event) {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const buttons = focusableNodeButtons();
    const current = buttons.indexOf(event.currentTarget);
    if (current < 0 || !buttons.length) return;
    event.preventDefault();
    if (state.activeView === "mind_map") {
      const item = event.currentTarget.closest(".mind-node-item");
      const toggle = item?.querySelector(":scope > .mind-node-row > .mind-node-toggle");
      if (event.key === "ArrowRight") {
        if (toggle?.getAttribute("aria-expanded") === "false") {
          toggle.click();
          event.currentTarget.focus({ preventScroll: false });
          return;
        }
        const child = item?.querySelector(":scope > .mind-node-children .knowledge-node-button");
        if (child) {
          buttons.forEach((button) => { button.tabIndex = -1; });
          child.tabIndex = 0;
          state.rovingHandle = child.dataset.nodeHandle || "";
          child.focus({ preventScroll: false });
          return;
        }
      }
      if (event.key === "ArrowLeft") {
        if (toggle?.getAttribute("aria-expanded") === "true") {
          toggle.click();
          event.currentTarget.focus({ preventScroll: false });
          return;
        }
        const parentItem = item?.parentElement?.closest(".mind-node-item");
        const parent = parentItem?.querySelector(":scope > .mind-node-row > .knowledge-node-button");
        if (parent) {
          buttons.forEach((button) => { button.tabIndex = -1; });
          parent.tabIndex = 0;
          state.rovingHandle = parent.dataset.nodeHandle || "";
          parent.focus({ preventScroll: false });
          return;
        }
      }
    }
    let next = current;
    if (state.activeView === "graph" && event.key.startsWith("Arrow")) {
      const currentRect = event.currentTarget.getBoundingClientRect();
      const currentX = currentRect.left + currentRect.width / 2;
      const currentY = currentRect.top + currentRect.height / 2;
      const candidates = buttons
        .map((button, index) => {
          const rect = button.getBoundingClientRect();
          const dx = rect.left + rect.width / 2 - currentX;
          const dy = rect.top + rect.height / 2 - currentY;
          const eligible = (
            (event.key === "ArrowRight" && dx > 0) ||
            (event.key === "ArrowLeft" && dx < 0) ||
            (event.key === "ArrowDown" && dy > 0) ||
            (event.key === "ArrowUp" && dy < 0)
          );
          return { index, dx, dy, eligible };
        })
        .filter((item) => item.eligible)
        .sort((a, b) => Math.hypot(a.dx, a.dy) - Math.hypot(b.dx, b.dy));
      if (candidates.length) next = candidates[0].index;
    } else {
      if (["ArrowDown", "ArrowRight"].includes(event.key)) next = (current + 1) % buttons.length;
      if (["ArrowUp", "ArrowLeft"].includes(event.key)) next = (current - 1 + buttons.length) % buttons.length;
    }
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    buttons.forEach((button, index) => { button.tabIndex = index === next ? 0 : -1; });
    state.rovingHandle = buttons[next].dataset.nodeHandle || "";
    buttons[next].focus({ preventScroll: false });
  }

  function renderMindMap(nodes) {
    const world = state.root.querySelector('[data-knowledge-world="mind_map"]');
    world.replaceChildren();
    const crossLinks = (state.projection.views.mind_map.cross_links || []).filter(
      (link) => state.nodeByHandle.has(link.source_handle) && state.nodeByHandle.has(link.target_handle)
    );
    world.dataset.crossLinkCount = String(crossLinks.length);
    const visible = new Set(nodes.map((node) => node.handle));
    const placements = new Map(
      state.projection.views.mind_map.placements.map((placement) => [placement.handle, placement])
    );
    const children = new Map();
    for (const placement of placements.values()) {
      const bucket = children.get(placement.parent_handle) || [];
      bucket.push(placement);
      children.set(placement.parent_handle, bucket);
    }
    for (const bucket of children.values()) bucket.sort((a, b) => a.order - b.order);
    const rendered = new Set(visible);
    if (state.query || state.selectedHandle) {
      const ancestryHandles = state.query ? [...visible] : [state.selectedHandle];
      for (const handle of ancestryHandles) {
        let current = placements.get(handle);
        while (current?.parent_type === "node") {
          rendered.add(current.parent_handle);
          current = placements.get(current.parent_handle);
        }
      }
    }

    const disclosureId = (kind, handle) =>
      `knowledge-${kind}-${String(handle).replace(/[^A-Za-z0-9_-]/g, "_")}`;

    const appendNode = (placement, list, trail = new Set()) => {
      if (!rendered.has(placement.handle) || trail.has(placement.handle)) return;
      const node = state.nodeByHandle.get(placement.handle);
      if (!node) return;
      const item = document.createElement("li");
      item.className = "mind-node-item";
      const row = document.createElement("div");
      row.className = "mind-node-row";
      row.append(nodeButton(node));
      const descendants = (children.get(placement.handle) || []).filter((child) => rendered.has(child.handle));
      if (descendants.length) {
        const collapsed = state.collapsed[placement.handle] ?? Boolean(placement.collapsed_by_default);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "mind-node-toggle";
        toggle.setAttribute("aria-expanded", String(!collapsed));
        toggle.setAttribute("aria-label", `${collapsed ? "展开" : "折叠"} ${node.name} 的分支`);
        toggle.textContent = collapsed ? "+" : "−";
        const nested = document.createElement("ul");
        nested.className = "mind-node-children";
        nested.id = disclosureId("branch", placement.handle);
        nested.hidden = collapsed;
        toggle.setAttribute("aria-controls", nested.id);
        const nextTrail = new Set(trail); nextTrail.add(placement.handle);
        descendants.forEach((child) => appendNode(child, nested, nextTrail));
        toggle.addEventListener("click", () => {
          const nextCollapsed = !nested.hidden;
          if (
            nextCollapsed &&
            state.selectedHandle &&
            nested.querySelector(`[data-node-handle="${state.selectedHandle}"]`)
          ) {
            state.collapsed[placement.handle] = false;
            announce("已保留当前知识点所在的分支");
            return;
          }
          state.collapsed[placement.handle] = nextCollapsed;
          nested.hidden = nextCollapsed;
          toggle.textContent = nextCollapsed ? "+" : "−";
          toggle.setAttribute("aria-expanded", String(!nextCollapsed));
          toggle.setAttribute("aria-label", `${nextCollapsed ? "展开" : "折叠"} ${node.name} 的分支`);
          saveCollapsed();
          syncRovingTabindex();
        });
        row.append(toggle);
        if (nested.childElementCount) item.append(row, nested);
        else item.append(row);
      } else {
        item.append(row);
      }
      list.append(item);
    };

    if (state.query) {
      const results = document.createElement("ul");
      results.className = "mind-search-results";
      nodes.forEach((node) => {
        const item = document.createElement("li");
        item.append(nodeButton(node));
        results.append(item);
      });
      world.append(results);
      return;
    }

    const root = document.createElement("button");
    root.type = "button";
    root.className = "mind-virtual-root";
    root.textContent = state.projection.views.mind_map.root_label || "我的数学知识体系";
    const modules = [...state.moduleByHandle.values()].sort((a, b) => a.order - b.order);
    root.setAttribute(
      "aria-controls",
      modules.map((module) => disclosureId("module", module.handle)).join(" ")
    );
    const moduleCollapsed = (module) => (
      state.collapsed[module.handle] ?? Boolean(module.collapsed_by_default)
    );
    const syncRootExpansion = () => {
      const expandedCount = modules.filter((module) => !moduleCollapsed(module)).length;
      root.setAttribute("aria-expanded", String(expandedCount > 0));
      root.dataset.expansionState = expandedCount === 0
        ? "collapsed"
        : (expandedCount === modules.length ? "expanded" : "partial");
      root.setAttribute(
        "aria-label",
        expandedCount > 0 ? "折叠全部知识模块" : "展开全部知识模块"
      );
    };
    syncRootExpansion();
    root.addEventListener("click", () => {
      const expand = modules.every((module) => moduleCollapsed(module));
      modules.forEach((module) => { state.collapsed[module.handle] = !expand; });
      if (state.selectedHandle && !expand) expandMindAncestors(state.selectedHandle);
      else saveCollapsed();
      renderActiveView();
    });
    world.append(root);

    const selectedCrossPrerequisites = crossLinks.filter(
      (link) => link.target_handle === state.selectedHandle
    );
    if (selectedCrossPrerequisites.length) {
      const details = document.createElement("details");
      details.className = "mind-cross-prerequisites";
      details.dataset.crossPrerequisiteCount = String(selectedCrossPrerequisites.length);
      const summary = document.createElement("summary");
      summary.textContent = `查看其他严格前置关系（${selectedCrossPrerequisites.length}）`;
      summary.setAttribute("aria-expanded", "false");
      const list = document.createElement("div");
      list.className = "mind-cross-prerequisite-list";
      selectedCrossPrerequisites.forEach((link) => {
        const source = state.nodeByHandle.get(link.source_handle);
        const target = state.nodeByHandle.get(link.target_handle);
        const row = document.createElement("p");
        row.className = "mind-cross-prerequisite";
        row.dataset.crossLink = `${link.source_handle}:${link.target_handle}`;
        const sourceName = document.createElement("span");
        sourceName.textContent = source.name;
        const direction = document.createElement("span");
        direction.className = "mind-cross-direction";
        direction.textContent = "严格前置 →";
        const targetName = document.createElement("span");
        targetName.textContent = target.name;
        row.append(sourceName, direction, targetName);
        list.append(row);
      });
      details.append(summary, list);
      details.addEventListener("toggle", () => {
        summary.setAttribute("aria-expanded", String(details.open));
        if (details.open) {
          window.requestAnimationFrame(() => renderMindCrossPaths(details, selectedCrossPrerequisites));
        } else {
          details.querySelector(".mind-cross-overlay")?.remove();
        }
      });
      world.append(details);
    }

    const moduleList = document.createElement("ul");
    moduleList.className = "mind-module-root-list";
    for (const module of modules) {
      const roots = (children.get(module.handle) || []).filter((placement) => rendered.has(placement.handle));
      if (!roots.length && nodes.length !== state.nodeByHandle.size) continue;
      const branch = document.createElement("li");
      branch.className = "mind-module-branch";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mind-module-toggle";
      const collapsed = moduleCollapsed(module);
      toggle.textContent = module.name;
      toggle.setAttribute("aria-expanded", String(!collapsed));
      const list = document.createElement("ul");
      list.className = "mind-module-list";
      list.id = disclosureId("module", module.handle);
      list.hidden = collapsed;
      toggle.setAttribute("aria-controls", list.id);
      roots.forEach((placement) => appendNode(placement, list));
      toggle.addEventListener("click", () => {
        const nextHidden = !list.hidden;
        if (
          nextHidden &&
          state.selectedHandle &&
          list.querySelector(`[data-node-handle="${state.selectedHandle}"]`)
        ) {
          state.collapsed[module.handle] = false;
          announce("已保留当前知识点所在的模块");
          return;
        }
        state.collapsed[module.handle] = nextHidden;
        list.hidden = nextHidden;
        toggle.setAttribute("aria-expanded", String(!list.hidden));
        saveCollapsed();
        syncRootExpansion();
        syncRovingTabindex();
      });
      branch.append(toggle, list);
      moduleList.append(branch);
    }
    world.append(moduleList);
  }

  function renderMindCrossPaths(details, links) {
    details.querySelector(".mind-cross-overlay")?.remove();
    if (!details.open || !links.length) return;
    const target = state.root.querySelector(
      `[data-knowledge-view="mind_map"] .knowledge-node-button[data-node-handle="${state.selectedHandle}"]`
    );
    if (!target || !target.getClientRects().length) return;
    const baseRect = details.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const scale = state.viewports.mind_map.scale || 1;
    const width = Math.max(
      details.offsetWidth,
      (targetRect.right - baseRect.left) / scale + 24
    );
    const height = Math.max(
      details.offsetHeight,
      (targetRect.bottom - baseRect.top) / scale + 24
    );
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "mind-cross-overlay");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = '<defs><marker id="kv51-mind-cross-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>';
    const targetX = (targetRect.left - baseRect.left) / scale;
    const targetY = (targetRect.top + targetRect.height / 2 - baseRect.top) / scale;
    const rows = [...details.querySelectorAll("[data-cross-link]")];
    rows.forEach((row, index) => {
      const rowRect = row.getBoundingClientRect();
      const startX = (rowRect.right - baseRect.left) / scale;
      const startY = (rowRect.top + rowRect.height / 2 - baseRect.top) / scale;
      const bend = Math.max(24, Math.abs(targetX - startX) * 0.45);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute(
        "d",
        `M ${startX} ${startY} C ${startX + bend} ${startY}, ${targetX - bend} ${targetY}, ${targetX} ${targetY}`
      );
      path.setAttribute("marker-end", "url(#kv51-mind-cross-arrow)");
      path.setAttribute("class", "mind-cross-path");
      path.dataset.crossPath = String(index + 1);
      svg.append(path);
    });
    details.prepend(svg);
  }

  function expandMindAncestors(handle) {
    const placements = new Map(
      state.projection.views.mind_map.placements.map((placement) => [placement.handle, placement])
    );
    let placement = placements.get(handle);
    while (placement) {
      state.collapsed[placement.handle] = false;
      if (placement.parent_type === "module") {
        state.collapsed[placement.parent_handle] = false;
        break;
      }
      placement = placements.get(placement.parent_handle);
    }
    saveCollapsed();
  }

  function fitSelectedMindContext(details, target) {
    const region = state.root?.querySelector('[data-knowledge-view="mind_map"]');
    const world = state.root?.querySelector('[data-knowledge-world="mind_map"]');
    if (!region || !world || !target?.getClientRects().length) return;
    // Focus navigation may scroll the viewport element. Normalize that transient
    // browser scroll so the persisted camera transform remains authoritative.
    region.scrollLeft = 0;
    region.scrollTop = 0;
    const elements = [target];
    if (details?.open && details.getClientRects().length) elements.push(details);
    const localRects = elements.map((element) => layoutRectWithin(element, world));
    if (localRects.some((rect) => !rect)) return;
    const left = Math.min(...localRects.map((rect) => rect.left));
    const top = Math.min(...localRects.map((rect) => rect.top));
    const right = Math.max(...localRects.map((rect) => rect.right));
    const bottom = Math.max(...localRects.map((rect) => rect.bottom));
    const availableWidth = Math.max(1, region.clientWidth - 48);
    const availableHeight = Math.max(1, region.clientHeight - 48);
    const scale = Math.min(
      1.25,
      Math.max(
        minimumScaleFor("mind_map"),
        Math.min(
          availableWidth / Math.max(1, right - left),
          availableHeight / Math.max(1, bottom - top)
        )
      )
    );
    state.viewports.mind_map = clampViewport({
      scale,
      x: region.clientWidth / 2 - ((left + right) / 2) * scale,
      y: region.clientHeight / 2 - ((top + bottom) / 2) * scale,
    }, "mind_map");
    saveViewport("mind_map");
    const priorTransition = world.style.transition;
    world.style.transition = "none";
    applyViewport("mind_map");
    void world.offsetWidth;
    window.requestAnimationFrame(() => {
      if (world.isConnected) world.style.transition = priorTransition;
    });
  }

  function layoutRectWithin(element, ancestor) {
    let left = 0;
    let top = 0;
    let current = element;
    while (current && current !== ancestor) {
      left += current.offsetLeft;
      top += current.offsetTop;
      current = current.offsetParent;
    }
    if (current !== ancestor) return null;
    return {
      left,
      top,
      right: left + element.offsetWidth,
      bottom: top + element.offsetHeight,
    };
  }

  function positionMindLocateDetails(details, target) {
    const world = state.root?.querySelector('[data-knowledge-world="mind_map"]');
    if (!world || !details || !target?.getClientRects().length) return;
    const targetRect = layoutRectWithin(target, world);
    if (!targetRect) return;
    const targetCenterX = (targetRect.left + targetRect.right) / 2;
    const targetTop = targetRect.top;
    const width = details.offsetWidth;
    const height = details.offsetHeight;
    const maximumLeft = Math.max(24, world.offsetWidth - width - 24);
    const left = Math.min(maximumLeft, Math.max(24, targetCenterX - width / 2));
    const top = Math.max(58, targetTop - height - 20);
    details.style.left = `${left}px`;
    details.style.top = `${top}px`;
  }

  function restoreSelectedMindContext() {
    if (!state.selectedHandle || state.activeView !== "mind_map") {
      renderActiveView();
      return;
    }
    expandMindAncestors(state.selectedHandle);
    renderActiveView();
    window.requestAnimationFrame(() => {
      const region = state.root?.querySelector('[data-knowledge-view="mind_map"]');
      const target = region?.querySelector(
        `.knowledge-node-button[data-node-handle="${state.selectedHandle}"]`
      );
      const details = region?.querySelector(".mind-cross-prerequisites");
      const selectedLinks = (state.projection.views.mind_map.cross_links || []).filter(
        (link) => link.target_handle === state.selectedHandle
      );
      if (details && selectedLinks.length) {
        details.classList.add("is-locate-context");
        details.open = true;
        details.querySelector("summary")?.setAttribute("aria-expanded", "true");
        window.requestAnimationFrame(() => {
          positionMindLocateDetails(details, target);
          renderMindCrossPaths(details, selectedLinks);
          fitSelectedMindContext(details, target);
        });
        return;
      }
      fitSelectedMindContext(details, target);
    });
  }

  function graphVisualScreenRect(element) {
    const rect = element.getBoundingClientRect();
    if (!element.classList.contains("graph-overview-marker")) return rect;
    const visualStyle = getComputedStyle(element, "::before");
    const width = Number.parseFloat(visualStyle.width) || rect.width;
    const height = Number.parseFloat(visualStyle.height) || rect.height;
    return {
      left: rect.left + (rect.width - width) / 2,
      top: rect.top + (rect.height - height) / 2,
      right: rect.right - (rect.width - width) / 2,
      bottom: rect.bottom - (rect.height - height) / 2,
      width,
      height,
    };
  }

  function graphBoundaryScreenPoint(rect, toward) {
    const center = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
    const dx = toward.x - center.x;
    const dy = toward.y - center.y;
    const halfWidth = Math.max(1, rect.width / 2);
    const halfHeight = Math.max(1, rect.height / 2);
    const denominator = Math.max(Math.abs(dx) / halfWidth, Math.abs(dy) / halfHeight, 1);
    return { x: center.x + dx / denominator, y: center.y + dy / denominator };
  }

  function updateGraphEdgeGeometry() {
    const world = state.root?.querySelector('[data-knowledge-world="graph"]');
    if (!world) return;
    const svg = world.querySelector(".graph-relationships");
    const screenMatrix = svg?.getScreenCTM();
    if (!screenMatrix) return;
    const inverseScreenMatrix = screenMatrix.inverse();
    const toWorldPoint = (point) =>
      new DOMPoint(point.x, point.y).matrixTransform(inverseScreenMatrix);
    world.querySelectorAll(".graph-edge").forEach((line) => {
      const sourceElement = world.querySelector(`[data-node-handle="${line.dataset.sourceHandle}"]`);
      const targetElement = world.querySelector(`[data-node-handle="${line.dataset.targetHandle}"]`);
      if (!sourceElement || !targetElement) return;
      const sourceRect = graphVisualScreenRect(sourceElement);
      const targetRect = graphVisualScreenRect(targetElement);
      const sourceCenter = {
        x: sourceRect.left + sourceRect.width / 2,
        y: sourceRect.top + sourceRect.height / 2,
      };
      const targetCenter = {
        x: targetRect.left + targetRect.width / 2,
        y: targetRect.top + targetRect.height / 2,
      };
      const start = toWorldPoint(graphBoundaryScreenPoint(sourceRect, targetCenter));
      const end = toWorldPoint(graphBoundaryScreenPoint(targetRect, sourceCenter));
      line.setAttribute("x1", String(start.x));
      line.setAttribute("y1", String(start.y));
      line.setAttribute("x2", String(end.x));
      line.setAttribute("y2", String(end.y));
    });
  }

  function renderGraph(nodes) {
    const world = state.root.querySelector('[data-knowledge-world="graph"]');
    const region = world.closest('[data-knowledge-view="graph"]');
    region?.querySelector(":scope > .graph-overview-anchor-layer")?.remove();
    world.replaceChildren();
    const allNodes = [...state.nodeByHandle.values()];
    const matchedHandles = new Set(nodes.map((node) => node.handle));
    const selectedNeighbors = new Set([state.selectedHandle]);
    if (state.selectedHandle) {
      state.relations.forEach((relation) => {
        if (relation.source_handle === state.selectedHandle) selectedNeighbors.add(relation.target_handle);
        if (relation.target_handle === state.selectedHandle) selectedNeighbors.add(relation.source_handle);
      });
    }
    const selectedTwoHop = new Set(selectedNeighbors);
    if (state.selectedHandle) {
      state.relations.forEach((relation) => {
        if (selectedNeighbors.has(relation.source_handle)) selectedTwoHop.add(relation.target_handle);
        if (selectedNeighbors.has(relation.target_handle)) selectedTwoHop.add(relation.source_handle);
      });
    }
    let graphNodes = nodes;
    if (!state.query && state.graphFocusMode === "node_focus" && state.selectedHandle) {
      graphNodes = allNodes.filter(
        (node) => selectedNeighbors.has(node.handle) && (matchesFilter(node) || node.handle === state.selectedHandle)
      );
    } else if (!state.query && state.graphFocusMode === "module_focus" && state.selectedModuleHandle) {
      const moduleNodes = new Set(
        allNodes
          .filter((node) => node.module_handle === state.selectedModuleHandle)
          .map((node) => node.handle)
      );
      const bridgeNodes = new Set(moduleNodes);
      state.relations.forEach((relation) => {
        if (moduleNodes.has(relation.source_handle)) bridgeNodes.add(relation.target_handle);
        if (moduleNodes.has(relation.target_handle)) bridgeNodes.add(relation.source_handle);
      });
      graphNodes = allNodes.filter(
        (node) => bridgeNodes.has(node.handle) && matchesFilter(node)
      );
    }
    if (
      !state.query &&
      state.selectedHandle &&
      state.nodeByHandle.has(state.selectedHandle) &&
      !graphNodes.some((node) => node.handle === state.selectedHandle)
    ) {
      graphNodes = [...graphNodes, state.nodeByHandle.get(state.selectedHandle)];
    }
    const fitAll = !state.query && state.graphFocusMode === "fit_all";
    const reviewedAnchors = fitAll ? graphOverviewAnchors() : [];
    const placements = new Map(
      state.projection.views.graph.placements.map((placement) => [placement.handle, placement])
    );
    const lanes = [...state.projection.views.graph.lanes].sort((a, b) => a.order - b.order);
    const laneIndex = new Map(lanes.map((lane, index) => [lane.handle, index]));
    const fullHandles = fitAll
      ? graphOverviewReadableHandles(matchedHandles, reviewedAnchors, laneIndex)
      : new Set(graphNodes.map((node) => node.handle));
    const maxRank = Math.max(0, ...state.projection.views.graph.placements.map((item) => item.rank));
    const nodeWidth = 148;
    const nodeHeight = 48;
    const rankGap = 210;
    const slotGap = 20;
    const maximumBucketSize = Math.max(
      1,
      ...state.projection.views.graph.placements.map((placement) =>
        state.projection.views.graph.placements.filter(
          (candidate) => candidate.rank === placement.rank && candidate.lane_handle === placement.lane_handle
        ).length
      )
    );
    const laneBandHeight = maximumBucketSize * (nodeHeight + slotGap) + 44;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "graph-relationships");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = `
      <defs>
        <marker id="kv51-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
        <marker id="kv51-arrow-incoming" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
        <marker id="kv51-arrow-outgoing" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
        <marker id="kv51-arrow-bridge" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
      </defs>`;
    world.append(svg);
    const positions = new Map();
    const buckets = new Map();
    state.projection.views.graph.placements.forEach((placement) => {
      const key = `${placement.rank}:${placement.lane_handle}`;
      const bucket = buckets.get(key) || [];
      bucket.push(placement);
      buckets.set(key, bucket);
    });
    for (const bucket of buckets.values()) {
      bucket.sort((a, b) => a.order - b.order || a.handle.localeCompare(b.handle));
    }
    const overviewCoordinates = new Map();
    const desktopOverview = fitAll && !isMobile();
    const overviewWidth = desktopOverview ? 1680 : 620;
    const overviewRankGap = desktopOverview ? 140 : 50;
    if (fitAll) {
      const usedMarkers = [];
      const usedReadable = [];
      const markerOffsets = [];
      const readableOffsets = [];
      for (let dx = -4; dx <= 4; dx += 1) {
        for (let dy = -4; dy <= 4; dy += 1) markerOffsets.push({ dx: dx * 42, dy: dy * 42 });
      }
      for (let dx = -5; dx <= 5; dx += 1) {
        for (let dy = -4; dy <= 4; dy += 1) readableOffsets.push({ dx: dx * 120, dy: dy * 92 });
      }
      markerOffsets.sort((left, right) =>
        Math.hypot(left.dx, left.dy) - Math.hypot(right.dx, right.dy) ||
        Math.abs(left.dy) - Math.abs(right.dy) || left.dx - right.dx || left.dy - right.dy
      );
      readableOffsets.sort((left, right) =>
        Math.hypot(left.dx, left.dy) - Math.hypot(right.dx, right.dy) ||
        Math.abs(left.dy) - Math.abs(right.dy) || left.dx - right.dx || left.dy - right.dy
      );
      const orderedPlacements = [...state.projection.views.graph.placements].sort((left, right) =>
        left.rank - right.rank ||
        (laneIndex.get(left.lane_handle) || 0) - (laneIndex.get(right.lane_handle) || 0) ||
        left.order - right.order || left.handle.localeCompare(right.handle)
      );
      for (const placement of orderedPlacements) {
        const readable = fullHandles.has(placement.handle);
        const visualWidth = readable ? (desktopOverview ? 248 : 156) : 34;
        const visualHeight = readable ? (desktopOverview ? 86 : 58) : 34;
        const baseX = (desktopOverview ? 168 : 46) + placement.rank * overviewRankGap;
        const baseY = 34 + (laneIndex.get(placement.lane_handle) || 0) * 91;
        const offsets = readable ? readableOffsets : markerOffsets;
        const coordinate = offsets
          .map((offset) => ({ x: baseX + offset.dx, y: baseY + offset.dy }))
          .find((candidate) =>
            candidate.x >= visualWidth / 2 && candidate.x <= overviewWidth - visualWidth / 2 &&
            candidate.y >= visualHeight / 2 && candidate.y <= 800 - visualHeight / 2 &&
            usedMarkers.every((point) => Math.hypot(candidate.x - point.x, candidate.y - point.y) >= 34) &&
            (!readable || usedReadable.every((rect) =>
              candidate.x + visualWidth / 2 + 12 <= rect.left ||
              rect.right + 12 <= candidate.x - visualWidth / 2 ||
              candidate.y + visualHeight / 2 + 8 <= rect.top ||
              rect.bottom + 8 <= candidate.y - visualHeight / 2
            ))
          ) || { x: baseX, y: baseY };
        usedMarkers.push(coordinate);
        if (readable) {
          usedReadable.push({
            left: coordinate.x - visualWidth / 2,
            right: coordinate.x + visualWidth / 2,
            top: coordinate.y - visualHeight / 2,
            bottom: coordinate.y + visualHeight / 2,
          });
        }
        overviewCoordinates.set(placement.handle, coordinate);
      }
    }
    if (fitAll) {
      world.style.width = `${overviewWidth}px`;
      world.style.height = "800px";
    } else {
      world.style.width = `${Math.max(980, 150 + (maxRank + 1) * rankGap + nodeWidth)}px`;
      world.style.height = `${Math.max(620, 32 + lanes.length * laneBandHeight)}px`;
    }
    for (const node of allNodes) {
      const placement = placements.get(node.handle);
      if (!placement) continue;
      const index = laneIndex.get(placement.lane_handle) || 0;
      const bucket = buckets.get(`${placement.rank}:${placement.lane_handle}`) || [];
      const slot = Math.max(0, bucket.findIndex((candidate) => candidate.handle === node.handle));
      const overviewCoordinate = overviewCoordinates.get(node.handle);
      const x = fitAll
        ? overviewCoordinate.x
        : 150 + placement.rank * rankGap;
      const y = fitAll
        ? overviewCoordinate.y
        : 34 + index * laneBandHeight + slot * (nodeHeight + slotGap);
      positions.set(node.handle, {
        x,
        y,
        centerX: fitAll ? x : x + nodeWidth / 2,
        centerY: fitAll ? y : y + nodeHeight / 2,
        rank: placement.rank,
        laneHandle: placement.lane_handle,
        order: placement.order,
        slot,
      });
    }
    if (!fitAll && state.graphFocusMode === "node_focus" && state.selectedHandle) {
      const activePlacements = [...fullHandles]
        .map((handle) => placements.get(handle))
        .filter(Boolean);
      const activeRanks = [...new Set(activePlacements.map((placement) => placement.rank))]
        .sort((left, right) => left - right);
      const activeRankIndex = new Map(activeRanks.map((rank, index) => [rank, index]));
      const activeBuckets = new Map();
      for (const placement of activePlacements) {
        const bucket = activeBuckets.get(placement.rank) || [];
        bucket.push(placement);
        activeBuckets.set(placement.rank, bucket);
      }
      for (const bucket of activeBuckets.values()) {
        bucket.sort((left, right) =>
          (laneIndex.get(left.lane_handle) || 0) - (laneIndex.get(right.lane_handle) || 0) ||
          left.order - right.order || left.handle.localeCompare(right.handle)
        );
      }
      for (const placement of activePlacements) {
        const bucket = activeBuckets.get(placement.rank) || [];
        const slot = bucket.findIndex((candidate) => candidate.handle === placement.handle);
        const x = 70 + (activeRankIndex.get(placement.rank) || 0) * 160;
        const y = 54 + Math.max(0, slot) * 64;
        positions.set(placement.handle, {
          x,
          y,
          centerX: x + nodeWidth / 2,
          centerY: y + nodeHeight / 2,
          rank: placement.rank,
          laneHandle: placement.lane_handle,
          order: placement.order,
          slot: Math.max(0, slot),
        });
      }
    }
    if (!fitAll && isMobile()) {
      const readableNodes = [...fullHandles]
        .map((handle) => ({ handle, placement: placements.get(handle) }))
        .filter((item) => item.placement && matchedHandles.has(item.handle))
        .sort((left, right) => {
          const leftNode = state.nodeByHandle.get(left.handle);
          const rightNode = state.nodeByHandle.get(right.handle);
          const leftModulePriority = leftNode?.module_handle === state.selectedModuleHandle ? 0 : 1;
          const rightModulePriority = rightNode?.module_handle === state.selectedModuleHandle ? 0 : 1;
          return leftModulePriority - rightModulePriority ||
            left.placement.rank - right.placement.rank ||
            (laneIndex.get(left.placement.lane_handle) || 0) -
              (laneIndex.get(right.placement.lane_handle) || 0) ||
            left.placement.order - right.placement.order ||
            left.handle.localeCompare(right.handle);
        });
      readableNodes.forEach((item, index) => {
        const x = 20 + (index % 2) * 178;
        const y = 28 + Math.floor(index / 2) * 64;
        positions.set(item.handle, {
          x,
          y,
          centerX: x + nodeWidth / 2,
          centerY: y + nodeHeight / 2,
          rank: item.placement.rank,
          laneHandle: item.placement.lane_handle,
          order: item.placement.order,
          slot: index,
        });
      });
      world.style.width = "382px";
      world.style.height = `${Math.max(520, 92 + Math.ceil(readableNodes.length / 2) * 64)}px`;
    }
    lanes.forEach((lane, index) => {
      const label = document.createElement("span");
      label.className = "graph-lane-label";
      label.style.top = fitAll
        ? `${24 + index * 91}px`
        : `${34 + index * laneBandHeight}px`;
      label.textContent = lane.name;
      world.append(label);
    });
    for (const node of allNodes) {
      const position = positions.get(node.handle);
      if (!position) continue;
      let representation;
      if (fullHandles.has(node.handle) && matchedHandles.has(node.handle)) {
        representation = nodeButton(node);
        representation.classList.add("graph-node-button");
        if (fitAll) representation.classList.add("graph-overview-callout");
        representation.style.left = fitAll
          ? `${position.centerX - nodeWidth / 2}px`
          : `${position.x}px`;
        representation.style.top = fitAll
          ? `${position.centerY - nodeHeight / 2}px`
          : `${position.y}px`;
      } else {
        representation = document.createElement("button");
        representation.type = "button";
        representation.className = `graph-overview-marker state-${node.learning_state || "untested"}`;
        representation.tabIndex = -1;
        representation.dataset.label = node.name;
        representation.title = node.name;
        representation.setAttribute(
          "aria-label",
          `${node.name}，状态：${node.learning_state_label || "还没有留下学习记录"}`
        );
        representation.setAttribute("aria-pressed", String(node.handle === state.selectedHandle));
        representation.addEventListener("click", () => selectNode(node.handle, representation));
        representation.addEventListener("keydown", handleNodeKeydown);
        representation.style.left = `${position.centerX - 22}px`;
        representation.style.top = `${position.centerY - 22}px`;
        if (node.handle === state.selectedHandle) representation.classList.add("is-selected", "is-callout");
        if (node.recommended) representation.classList.add("is-recommended");
        if (!matchedHandles.has(node.handle)) representation.classList.add("is-filtered");
      }
      representation.dataset.nodeHandle = node.handle;
      representation.dataset.graphRank = String(position.rank);
      representation.dataset.graphLaneHandle = position.laneHandle;
      representation.dataset.graphOrder = String(position.order);
      representation.dataset.graphSlot = String(position.slot);
      world.append(representation);
    }
    if (fitAll && !fullHandles.size) {
      const fallback = document.createElement("p");
      fallback.className = "graph-overview-fallback";
      fallback.textContent = "选择一个知识模块查看知识点。";
      world.append(fallback);
    }
    const overviewBackbone = new Set();
    if (fitAll) {
      const candidatesByTarget = new Map();
      for (const relation of state.projection.views.graph.edge_visibility) {
        if (!relation.overview_visible) continue;
        const bucket = candidatesByTarget.get(relation.target_handle) || [];
        bucket.push(relation);
        candidatesByTarget.set(relation.target_handle, bucket);
      }
      for (const candidates of candidatesByTarget.values()) {
        candidates.sort((left, right) => {
          const leftSource = state.nodeByHandle.get(left.source_handle);
          const leftTarget = state.nodeByHandle.get(left.target_handle);
          const rightSource = state.nodeByHandle.get(right.source_handle);
          const rightTarget = state.nodeByHandle.get(right.target_handle);
          const leftBridge = leftSource?.module_handle !== leftTarget?.module_handle ? 1 : 0;
          const rightBridge = rightSource?.module_handle !== rightTarget?.module_handle ? 1 : 0;
          const leftRank = placements.get(left.source_handle)?.rank ?? -1;
          const rightRank = placements.get(right.source_handle)?.rank ?? -1;
          return rightBridge - leftBridge || rightRank - leftRank ||
            left.source_handle.localeCompare(right.source_handle);
        });
        const relation = candidates[0];
        overviewBackbone.add(`${relation.source_handle}:${relation.target_handle}`);
      }
    }
    for (const relation of state.projection.views.graph.edge_visibility) {
      const sourceNode = state.nodeByHandle.get(relation.source_handle);
      const targetNode = state.nodeByHandle.get(relation.target_handle);
      const bridge = sourceNode?.module_handle !== targetNode?.module_handle;
      const showEdge = fitAll
        ? overviewBackbone.has(`${relation.source_handle}:${relation.target_handle}`)
        : (fullHandles.has(relation.source_handle) && fullHandles.has(relation.target_handle));
      if (!showEdge) continue;
      const source = positions.get(relation.source_handle);
      const target = positions.get(relation.target_handle);
      if (!source || !target) continue;
      const sourceElement = world.querySelector(`[data-node-handle="${relation.source_handle}"]`);
      const targetElement = world.querySelector(`[data-node-handle="${relation.target_handle}"]`);
      if (!sourceElement || !targetElement) continue;
      const sourceRect = graphVisualScreenRect(sourceElement);
      const targetRect = graphVisualScreenRect(targetElement);
      const sourceCenter = {
        x: sourceRect.left + sourceRect.width / 2,
        y: sourceRect.top + sourceRect.height / 2,
      };
      const targetCenter = {
        x: targetRect.left + targetRect.width / 2,
        y: targetRect.top + targetRect.height / 2,
      };
      const screenMatrix = svg.getScreenCTM();
      if (!screenMatrix) continue;
      const inverseScreenMatrix = screenMatrix.inverse();
      const toWorldPoint = (point) =>
        new DOMPoint(point.x, point.y).matrixTransform(inverseScreenMatrix);
      const start = toWorldPoint(graphBoundaryScreenPoint(sourceRect, targetCenter));
      const end = toWorldPoint(graphBoundaryScreenPoint(targetRect, sourceCenter));
      const incoming = relation.target_handle === state.selectedHandle;
      const outgoing = relation.source_handle === state.selectedHandle;
      const marker = incoming
        ? "kv51-arrow-incoming"
        : (outgoing ? "kv51-arrow-outgoing" : (bridge ? "kv51-arrow-bridge" : "kv51-arrow"));
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(start.x));
      line.setAttribute("y1", String(start.y));
      line.setAttribute("x2", String(end.x));
      line.setAttribute("y2", String(end.y));
      line.setAttribute("marker-end", `url(#${marker})`);
      line.classList.add("graph-edge");
      line.dataset.relation = "strict-prerequisite";
      line.dataset.sourceHandle = relation.source_handle;
      line.dataset.targetHandle = relation.target_handle;
      line.dataset.overviewVisible = String(Boolean(relation.overview_visible));
      if (fitAll) line.classList.add("is-overview");
      if (bridge) line.classList.add("is-bridge");
      if (incoming) line.classList.add("is-incoming");
      if (outgoing) line.classList.add("is-outgoing");
      if (state.selectedHandle && selectedTwoHop.has(relation.source_handle) && selectedTwoHop.has(relation.target_handle)) {
        line.classList.add("is-related");
      }
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = `${sourceNode?.name || "前置知识"} 严格前置于 ${targetNode?.name || "后续知识"}${line.classList.contains("is-bridge") ? "，跨模块桥梁" : ""}`;
      line.append(title);
      svg.append(line);
    }
    updateGraphEdgeGeometry();
    positionGraphOverviewAnchors();
  }

  function positionGraphOverviewAnchors() {
    const region = state.root?.querySelector('[data-knowledge-view="graph"]');
    const world = state.root?.querySelector('[data-knowledge-world="graph"]');
    const layer = region?.querySelector(":scope > .graph-overview-anchor-layer");
    if (!region || !world || !layer || region.hidden) return;
    const regionRect = region.getBoundingClientRect();
    const occupied = [];
    const labels = [...layer.querySelectorAll(".graph-overview-anchor")].sort(
      (left, right) => Number(left.dataset.anchorPriority) - Number(right.dataset.anchorPriority)
    );
    labels.forEach((label) => {
      const marker = world.querySelector(
        `.graph-overview-marker[data-node-handle="${label.dataset.anchorHandle}"]`
      );
      if (!marker) {
        label.hidden = true;
        return;
      }
      label.hidden = false;
      label.style.visibility = "hidden";
      label.style.left = "0px";
      label.style.top = "0px";
      const markerRect = graphVisualScreenRect(marker);
      const markerCenterX = markerRect.left + markerRect.width / 2;
      const markerCenterY = markerRect.top + markerRect.height / 2;
      const labelWidth = label.offsetWidth;
      const labelHeight = label.offsetHeight;
      const facesLeft = markerCenterX > regionRect.left + regionRect.width / 2;
      label.classList.toggle("is-left", facesLeft);
      label.classList.toggle("is-right", !facesLeft);
      const desiredLeft = facesLeft
        ? markerCenterX - regionRect.left - 14 - labelWidth
        : markerCenterX - regionRect.left + 14;
      const left = Math.min(
        region.clientWidth - labelWidth - 8,
        Math.max(8, desiredLeft)
      );
      const minimumTop = 8;
      const maximumTop = Math.max(minimumTop, region.clientHeight - labelHeight - 8);
      const baseTop = Math.min(
        maximumTop,
        Math.max(minimumTop, markerCenterY - regionRect.top - labelHeight / 2)
      );
      const candidateTops = [baseTop];
      for (let candidate = minimumTop; candidate <= maximumTop; candidate += labelHeight + 6) {
        candidateTops.push(candidate);
      }
      candidateTops.sort((leftTop, rightTop) =>
        Math.abs(leftTop - baseTop) - Math.abs(rightTop - baseTop) || leftTop - rightTop
      );
      const top = candidateTops
        .find((candidate) => occupied.every((rect) =>
          left + labelWidth + 4 <= rect.left || rect.right + 4 <= left ||
          candidate + labelHeight + 4 <= rect.top || rect.bottom + 4 <= candidate
        )) ?? baseTop;
      label.style.left = `${left}px`;
      label.style.top = `${top}px`;
      label.style.visibility = "visible";
      occupied.push({ left, top, right: left + labelWidth, bottom: top + labelHeight });
    });
  }

  function graphOverviewAnchors() {
    const placements = Array.isArray(state.projection?.views?.graph?.placements)
      ? state.projection.views.graph.placements
      : [];
    const candidates = placements
      .filter((placement) => Object.prototype.hasOwnProperty.call(placement, "overview_label_priority"))
      .map((placement) => ({
        handle: placement.handle,
        priority: placement.overview_label_priority,
        name: state.nodeByHandle.get(placement.handle)?.name || "",
      }));
    const priorities = new Set(candidates.map((item) => item.priority));
    const valid = candidates.length >= 3 && candidates.length <= 6 &&
      priorities.size === candidates.length &&
      candidates.every((item) =>
        state.nodeByHandle.has(item.handle) && item.name &&
        Number.isInteger(item.priority) && item.priority >= 1 && item.priority <= 6
      );
    return valid
      ? candidates.sort((left, right) => left.priority - right.priority)
      : [];
  }

  function graphOverviewReadableHandles(matchedHandles, reviewedAnchors, laneIndex) {
    const handles = new Set();
    const add = (handle) => {
      if (handle && state.nodeByHandle.has(handle) && matchedHandles.has(handle)) handles.add(handle);
    };
    add(state.selectedHandle);
    reviewedAnchors.forEach((anchor) => add(anchor.handle));
    [...state.nodeByHandle.values()]
      .filter((node) => node.recommended)
      .sort((left, right) => left.name.localeCompare(right.name, "zh-CN"))
      .forEach((node) => add(node.handle));
    const firstByLane = new Map();
    for (const placement of [...state.projection.views.graph.placements].sort((left, right) =>
      left.rank - right.rank ||
      left.order - right.order ||
      left.handle.localeCompare(right.handle)
    )) {
      if (!matchedHandles.has(placement.handle) || firstByLane.has(placement.lane_handle)) continue;
      firstByLane.set(placement.lane_handle, placement.handle);
    }
    [...firstByLane.entries()]
      .sort((left, right) => (laneIndex.get(left[0]) || 0) - (laneIndex.get(right[0]) || 0))
      .forEach(([, handle]) => add(handle));
    return new Set([...handles].slice(0, isMobile() ? 3 : 18));
  }

  function selectNode(handle, originButton) {
    if (!state.nodeByHandle.has(handle)) return;
    state.selectedHandle = handle;
    state.rovingHandle = handle;
    state.graphFocusMode = "node_focus";
    state.originButton = originButton || state.originButton;
    renderActiveView();
    if (state.activeView === "graph") fitReadableGraphNodes();
    openDetail();
  }

  function relationNames(handle) {
    const incoming = [];
    const outgoing = [];
    for (const relation of state.relations) {
      if (relation.target_handle === handle) {
        const source = state.nodeByHandle.get(relation.source_handle);
        if (source) incoming.push(source.name);
      }
      if (relation.source_handle === handle) {
        const target = state.nodeByHandle.get(relation.target_handle);
        if (target) outgoing.push(target.name);
      }
    }
    return { incoming, outgoing };
  }

  function renderDetail() {
    const detail = state.root.querySelector("[data-knowledge-detail]");
    const node = state.nodeByHandle.get(state.selectedHandle);
    if (!node) {
      closeDetail(false);
      return;
    }
    const relations = relationNames(node.handle);
    const descriptors = actionDescriptorsForNode(node);
    const activityCompleted = Math.max(0, Math.min(4, Number(node.activity?.completed) || 0));
    const activityTotal = Number(node.activity?.total) === 4 ? 4 : 4;
    const readiness = node.action_readiness && typeof node.action_readiness === "object"
      ? node.action_readiness
      : null;
    const readinessVisible = readiness?.code && readiness.code !== "ready";
    const disabledReason = descriptors.find((item) => !item.enabled)?.disabled_reason || "";
    detail.innerHTML = `
      <div class="knowledge-detail-head">
        <div>
          <p>${escapeHtml(state.moduleByHandle.get(node.module_handle)?.name || "数学知识")}</p>
          <h3 id="knowledgeDetailHeading" tabindex="-1">${escapeHtml(node.name)}</h3>
        </div>
        <button type="button" class="knowledge-detail-close" aria-label="关闭详情">×</button>
      </div>
      <p class="knowledge-state-label">${escapeHtml(node.evidence_state?.label || node.learning_state_label)}</p>
      ${readinessVisible ? `
        <section class="knowledge-readiness" aria-label="开始准备情况">
          <strong>${escapeHtml(readiness.label)}</strong>
          <p>${escapeHtml(readiness.reason || "")}</p>
        </section>
      ` : ""}
      <p class="knowledge-essence">${escapeHtml(node.essence || "先看清关系，再用一道小题确认。")}</p>
      <section class="knowledge-activity" aria-label="${escapeHtml(node.activity?.label || `学习历程，完成 ${activityCompleted}/${activityTotal}`)}">
        <div class="knowledge-detail-section-head"><h4>学习历程</h4><span>${activityCompleted}/${activityTotal}</span></div>
        <div class="knowledge-activity-segments" aria-hidden="true">
          ${Array.from({ length: 4 }, (_, index) => `<i class="${index < activityCompleted ? "is-complete" : ""}"></i>`).join("")}
        </div>
      </section>
      <section class="knowledge-mastery">
        <h4>掌握情况</h4>
        <p>${escapeHtml(node.mastery_summary || "还没有留下学习记录")}</p>
      </section>
      <div class="knowledge-relations">
        <section><h4>需要先会</h4><p>${escapeHtml(relations.incoming.join("、") || "这是一个可以直接开始看的基础点")}</p></section>
        <section><h4>后面会用到</h4><p>${escapeHtml(relations.outgoing.join("、") || "学稳后会在更多题目里用到")}</p></section>
      </div>
      <div class="knowledge-detail-actions">
        <p id="knowledgeActionStatus" class="knowledge-action-status" data-knowledge-action-status hidden></p>
        ${disabledReason ? `<p class="knowledge-action-disabled-reason">${escapeHtml(disabledReason)}</p>` : ""}
        ${descriptors.length
          ? descriptors.map((descriptor) => `<button type="button" class="${descriptor.role === "primary" ? "primary" : ""}" ${descriptor.enabled ? `data-action-name="${escapeHtml(descriptor.action)}"` : `data-disabled-action-name="${escapeHtml(descriptor.action)}"`} data-result-behavior="${escapeHtml(descriptor.result_behavior)}"${descriptor.enabled ? "" : " disabled"}>${escapeHtml(descriptor.label)}</button>`).join("")
          : `<button type="button" class="primary" disabled>暂不能开始学习</button>
             <p class="knowledge-action-disabled-reason">这个知识点的开始方式暂时不能确认，请刷新后再试。</p>`}
      </div>
    `;
    detail.querySelector(".knowledge-detail-close").addEventListener("click", () => closeDetail(true));
    detail.querySelectorAll("[data-action-name]").forEach((button) => {
      const action = button.dataset.actionName;
      button.addEventListener("click", async () => {
        if (!state.onAction || !actionCanRun(node, action)) return;
        const request = stableActionRequest(node, action);
        if (!request) return;
        const descriptor = actionDescriptor(node, action);
        state.actionInFlight = request;
        const pendingMessage = descriptor?.pending_label || "正在准备这个学习目标，请稍等。";
        setActionFeedback("pending", pendingMessage, request.handle);
        announce(pendingMessage);
        syncActionControls();
        try {
          const result = await state.onAction(request);
          if (settlePendingAction(result, request)) {
            const resultMessage = result?.message || (
              result?.status === "applied"
                ? "学习目标已经准备好"
                : "学习目标已经保留，会在安全边界继续准备。"
            );
            setActionFeedback(
              result?.status === "applied" ? "success" : "waiting",
              resultMessage,
              request.handle
            );
            announce(resultMessage);
          } else {
            const mismatchMessage = "刚才的回复没有匹配这个学习目标，请再次点击安全重试。";
            setActionFeedback("recovery", mismatchMessage, request.handle);
            announce(mismatchMessage);
          }
        } catch (error) {
          const stale = error?.status === 409 || ["stale", "conflict"].includes(error?.payload?.state);
          if (stale) {
            state.pendingAction = null;
            state.actionFeedback = null;
            state.projectionStale = true;
            savePendingAction();
            closeDetail(false);
            setSurfaceState("stale");
            announce("知识首页已经更新，请重新加载后再选择。");
          } else {
            if (state.pendingAction) state.pendingAction.status = "response_unknown";
            savePendingAction();
            const recoveryMessage = "连接中断了，学习目标已经保留；再次点击会安全重试。";
            setActionFeedback("recovery", recoveryMessage, request.handle);
            announce(recoveryMessage);
          }
        } finally {
          if (state.actionInFlight?.client_idempotency_key === request.client_idempotency_key) {
            state.actionInFlight = null;
          }
          syncActionControls();
        }
      });
    });
    syncActionFeedback();
    syncActionControls();
    syncDetailMode();
  }

  function openDetail() {
    const detail = state.root.querySelector("[data-knowledge-detail]");
    if (detail.hidden) {
      state.detailViewportBeforeOpen = {
        view: state.activeView,
        viewport: { ...state.viewports[state.activeView] },
      };
      state.sheetCameraAdjusted = false;
    }
    detail.hidden = false;
    syncDetailMode();
    if (!isMobile() && state.activeView === "graph") fitReadableGraphNodes();
    window.requestAnimationFrame(() => detail.querySelector("h3")?.focus({ preventScroll: true }));
  }

  function syncDetailMode() {
    if (!state.root) return;
    const detail = state.root.querySelector("[data-knowledge-detail]");
    const content = state.root.querySelector("[data-knowledge-content]");
    if (detail.hidden) {
      releaseModalIsolation();
      detail.removeAttribute("role");
      detail.removeAttribute("aria-modal");
      detail.removeAttribute("aria-labelledby");
      detail.style.removeProperty("max-height");
      return;
    }
    detail.setAttribute("aria-labelledby", "knowledgeDetailHeading");
    if (isMobile()) {
      detail.setAttribute("role", "dialog");
      detail.setAttribute("aria-modal", "true");
      applyModalIsolation(detail);
      const activeViewport = state.root.querySelector("[data-knowledge-view]:not([hidden])");
      const viewportTop = activeViewport?.getBoundingClientRect().top || 0;
      const minimumSheetTop = Math.min(window.innerHeight - 168, viewportTop + 112);
      detail.style.maxHeight = `${Math.max(168, window.innerHeight - minimumSheetTop)}px`;
      const selectedButton = activeViewport?.querySelector(
        `.knowledge-node-button[data-node-handle="${state.selectedHandle}"]`
      );
      if (selectedButton && !state.sheetCameraAdjusted) {
        const view = activeViewport.dataset.knowledgeView;
        const viewport = state.viewports[view];
        const visibleStrip = Math.max(112, minimumSheetTop - viewportTop);
        viewport.x = activeViewport.clientWidth / 2 -
          (selectedButton.offsetLeft + selectedButton.offsetWidth / 2) * viewport.scale;
        viewport.y = visibleStrip / 2 -
          (selectedButton.offsetTop + selectedButton.offsetHeight / 2) * viewport.scale;
        applyViewport(view);
        state.sheetCameraAdjusted = true;
      }
    } else {
      detail.setAttribute("role", "complementary");
      detail.removeAttribute("aria-modal");
      releaseModalIsolation();
      detail.style.removeProperty("max-height");
    }
  }

  function applyModalIsolation(detail) {
    releaseModalIsolation();
    let branch = detail;
    while (branch?.parentElement) {
      const parent = branch.parentElement;
      for (const sibling of parent.children) {
        if (sibling === branch || !(sibling instanceof HTMLElement) || sibling.hasAttribute("inert")) continue;
        sibling.setAttribute("inert", "");
        state.modalInertRecords.push(sibling);
      }
      branch = parent;
      if (branch === document.body) break;
    }
  }

  function releaseModalIsolation() {
    state.modalInertRecords.forEach((element) => element.removeAttribute("inert"));
    state.modalInertRecords = [];
  }

  function focusableDialogControls(detail) {
    return [...detail.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'
    )].filter((element) => element.getClientRects().length > 0 && !element.closest("[inert]"));
  }

  function closeDetail(restoreFocus) {
    if (!state.root) return;
    const detail = state.root.querySelector("[data-knowledge-detail]");
    detail.hidden = true;
    detail.innerHTML = "";
    detail.removeAttribute("role");
    detail.removeAttribute("aria-modal");
    detail.removeAttribute("aria-labelledby");
    detail.style.removeProperty("max-height");
    releaseModalIsolation();
    const priorViewport = state.detailViewportBeforeOpen;
    state.detailViewportBeforeOpen = null;
    if (state.sheetCameraAdjusted && priorViewport && VIEW_NAMES.has(priorViewport.view)) {
      state.viewports[priorViewport.view] = clampViewport(
        priorViewport.viewport,
        priorViewport.view
      );
      saveViewport(priorViewport.view);
      applyViewport(priorViewport.view);
    }
    state.sheetCameraAdjusted = false;
    if (restoreFocus) {
      const fallback = [...state.root.querySelectorAll(".knowledge-node-button")].find(
        (button) =>
          button.dataset.nodeHandle === state.selectedHandle &&
          elementCanReceiveFocus(button)
      );
      const target = elementCanReceiveFocus(state.originButton) ? state.originButton : fallback;
      if (target) target.focus({ preventScroll: true });
      else focusCurrentViewHeading();
    }
  }

  function updateViewport(action) {
    const viewport = state.viewports[state.activeView];
    const minimumScale = minimumScaleFor(state.activeView);
    if (action === "zoom-in") viewport.scale = Math.min(1.6, viewport.scale + 0.15);
    if (action === "zoom-out") viewport.scale = Math.max(minimumScale, viewport.scale - 0.15);
    if (action === "fit") {
      if (state.activeView === "graph") state.graphFocusMode = "fit_all";
      renderActiveView();
      fitViewport(state.activeView);
    }
    if (action === "focus-selected" && state.selectedHandle) {
      if (state.activeView === "graph") state.graphFocusMode = "node_focus";
      renderActiveView();
      if (state.activeView === "graph") fitReadableGraphNodes();
      const button = [...state.root.querySelectorAll(".knowledge-node-button")].find(
        (candidate) =>
          candidate.dataset.nodeHandle === state.selectedHandle &&
          candidate.getClientRects().length > 0
      );
      button?.focus({ preventScroll: true });
    }
    saveViewport(state.activeView);
    applyViewport(state.activeView);
  }

  function applyViewport(view) {
    if (!state.root) return;
    const world = state.root.querySelector(`[data-knowledge-world="${view}"]`);
    if (!world) return;
    const viewport = state.viewports[view];
    world.style.setProperty("--kv-inverse-scale", String(1 / viewport.scale));
    world.style.setProperty("--kv-cross-scale", String(Math.min(1, 1 / viewport.scale)));
    if (view === "graph") {
      world.querySelectorAll(".graph-node-button").forEach((button) => {
        if (button.classList.contains("graph-overview-callout")) {
          button.style.width = "";
          button.style.height = "";
          button.style.minHeight = "";
          button.querySelector(".knowledge-node-label")?.style.setProperty("font-size", "");
          return;
        }
        const inverseScale = isMobile() ? 1 / viewport.scale : 1;
        button.style.width = isMobile() ? `${148 * inverseScale}px` : "";
        button.style.height = isMobile() ? `${48 * inverseScale}px` : "";
        button.style.minHeight = isMobile() ? `${48 * inverseScale}px` : "";
        button.querySelector(".knowledge-node-label")?.style.setProperty(
          "font-size",
          isMobile() ? `${15 * inverseScale}px` : ""
        );
      });
      world.querySelectorAll(".graph-lane-label").forEach((label) => {
        const inverseScale = 1 / viewport.scale;
        label.style.fontSize = `${12 * inverseScale}px`;
        label.style.maxWidth = `${120 * inverseScale}px`;
        label.style.lineHeight = "1.2";
      });
    }
    world.style.transform = `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`;
    if (view === "graph") {
      updateGraphEdgeGeometry();
      if (state.graphEdgeFrame) window.cancelAnimationFrame(state.graphEdgeFrame);
      state.graphEdgeFrame = window.requestAnimationFrame(() => {
        state.graphEdgeFrame = 0;
        updateGraphEdgeGeometry();
        positionGraphOverviewAnchors();
      });
      positionGraphOverviewAnchors();
    }
  }

  function fitViewport(view) {
    const region = state.root?.querySelector(`[data-knowledge-view="${view}"]`);
    const world = state.root?.querySelector(`[data-knowledge-world="${view}"]`);
    if (!region || !world) return;
    const minimumScale = minimumScaleFor(view);
    const availableWidth = Math.max(1, region.clientWidth - 48);
    const availableHeight = Math.max(1, region.clientHeight - 48);
    const scale = Math.min(
      1.6,
      Math.max(
        minimumScale,
        Math.min(availableWidth / world.offsetWidth, availableHeight / world.offsetHeight)
      )
    );
    state.viewports[view] = {
      scale,
      x: Math.max(12, (region.clientWidth - world.offsetWidth * scale) / 2),
      y: Math.max(12, (region.clientHeight - world.offsetHeight * scale) / 2),
    };
  }

  function fitAndPersistViewport(view) {
    fitViewport(view);
    saveViewport(view);
    applyViewport(view);
    if (view === "graph") state.graphViewportStored = true;
  }

  function fitReadableGraphNodes() {
    const region = state.root?.querySelector('[data-knowledge-view="graph"]');
    const world = state.root?.querySelector('[data-knowledge-world="graph"]');
    const buttons = [...(world?.querySelectorAll(".graph-node-button:not(.is-context)") || [])];
    if (!region || !world || !buttons.length) return;
    const left = Math.min(...buttons.map((button) => button.offsetLeft));
    const top = Math.min(...buttons.map((button) => button.offsetTop));
    const right = Math.max(...buttons.map((button) => button.offsetLeft + button.offsetWidth));
    const bottom = Math.max(...buttons.map((button) => button.offsetTop + button.offsetHeight));
    const minimumScale = minimumScaleFor("graph");
    const scale = Math.min(
      1.25,
      Math.max(
        minimumScale,
        Math.min(
          Math.max(1, region.clientWidth - 64) / Math.max(1, right - left),
          Math.max(1, region.clientHeight - 64) / Math.max(1, bottom - top)
        )
      )
    );
    state.viewports.graph = {
      scale,
      x: region.clientWidth / 2 - ((left + right) / 2) * scale,
      y: region.clientHeight / 2 - ((top + bottom) / 2) * scale,
    };
    saveViewport("graph");
    applyViewport("graph");
  }

  function focusNode(handle) {
    if (!state.nodeByHandle.has(handle)) return false;
    state.selectedHandle = handle;
    state.rovingHandle = handle;
    state.graphFocusMode = "node_focus";
    expandMindAncestors(handle);
    renderActiveView();
    if (state.activeView === "graph") fitReadableGraphNodes();
    const button = state.root.querySelector(
      `[data-knowledge-view="${state.activeView}"] [data-node-handle="${handle}"]`
    );
    if (button) {
      state.originButton = button;
      button.focus({ preventScroll: true });
    }
    openDetail();
    return true;
  }

  function announce(message) {
    const live = state.root?.querySelector("[data-knowledge-live]");
    if (live) live.textContent = String(message || "");
  }

  function show() {
    if (!state.root) return;
    state.visible = true;
    state.root.hidden = false;
    state.root.removeAttribute("inert");
  }

  function hide() {
    if (!state.root) return;
    const detail = state.root.querySelector("[data-knowledge-detail]");
    if (detail && !detail.hidden) closeDetail(false);
    else releaseModalIsolation();
    state.visible = false;
    state.root.hidden = true;
    state.root.setAttribute("inert", "");
  }

  function currentView() {
    return state.activeView;
  }

  function destroy() {
    if (state.graphEdgeFrame) window.cancelAnimationFrame(state.graphEdgeFrame);
    if (state.media && state.mediaListener) state.media.removeEventListener("change", state.mediaListener);
    if (state.root) state.root.innerHTML = "";
    state.root = null;
    state.projection = null;
    state.nodeByHandle = new Map();
    state.moduleByHandle = new Map();
    state.relations = [];
    state.onAction = null;
    state.onResume = null;
    state.onRetry = null;
    state.surfaceState = "skeleton";
    state.activeView = "mind_map";
    state.selectedHandle = "";
    state.query = "";
    state.filter = "all";
    state.collapsed = {};
    state.selectedModuleHandle = "";
    state.graphFocusMode = "fit_all";
    state.graphViewportStored = false;
    state.graphHasEntered = false;
    state.graphEdgeFrame = 0;
    state.rovingHandle = "";
    state.pendingAction = null;
    state.actionInFlight = null;
    state.actionFeedback = null;
    state.projectionStale = false;
    state.detailViewportBeforeOpen = null;
    state.sheetCameraAdjusted = false;
    state.viewports = {
      mind_map: { scale: 1, x: 0, y: 0 },
      graph: { scale: 1, x: 0, y: 0 },
    };
    releaseModalIsolation();
    state.originButton = null;
    state.visible = false;
    state.media = null;
    state.mediaListener = null;
  }

  window.addEventListener("keydown", (event) => {
    const detail = state.root?.querySelector("[data-knowledge-detail]");
    if (!detail || detail.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDetail(true);
      return;
    }
    if (event.key === "Tab" && detail.getAttribute("role") === "dialog") {
      const controls = focusableDialogControls(detail);
      if (!controls.length) {
        event.preventDefault();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      const activeIsControl = controls.includes(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !activeIsControl)) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && (document.activeElement === last || !activeIsControl)) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    }
  });

  window.KnowledgeViews = Object.freeze({
    initialize,
    setProjection,
    show,
    hide,
    focusNode,
    currentView,
    destroy,
  });
})();
