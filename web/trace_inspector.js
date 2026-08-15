import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION_NAME = "local-rnd.ComfyUI.TraceInspector";
const EVENT_PREFIX = "trace_inspector.";
const EXPANDED_STORAGE_KEY = "comfy-trace-inspector.expanded";
const RIGHT_PANEL_WIDTH_STORAGE_KEY = "comfy-trace-inspector.right-panel-width";
const RIGHT_PANEL_DEFAULT_WIDTH = 360;
const RIGHT_PANEL_MIN_WIDTH = 280;
const RIGHT_PANEL_MAX_WIDTH = 720;
const CENTER_PANEL_MIN_WIDTH = 480;

function isKoreanLocale() {
  const language = app?.ui?.settings?.getSettingValue?.("Comfy.Locale")
    || document.documentElement.lang
    || navigator.language
    || "en";
  return /^ko(?:-|$)/i.test(language);
}

function localeText(korean, english) {
  return isKoreanLocale() ? korean : english;
}

const NOTE_CATEGORIES = [
  { value: "observation", ko: "관찰", en: "Observation" },
  { value: "hypothesis", ko: "가설", en: "Hypothesis" },
  { value: "decision", ko: "결정", en: "Decision" },
  { value: "issue", ko: "문제", en: "Issue" },
];

const state = {
  runs: [],
  selectedRunId: null,
  selectedRun: null,
  selectedStepIndex: 0,
  currentPromptId: null,
  currentRunId: null,
  currentRunIds: new Set(),
  pendingEvents: [],
  activeNode: null,
  activeNodeStartedAt: null,
  root: null,
  refreshTimer: null,
  compare: null,
  compareStepIndex: 0,
  selectedNodeId: null,
  canvasNotice: null,
  panelContainer: null,
  expanded: false,
  keydownHandler: null,
  noteNotice: null,
  currentWorkflowName: null,
  rightPanelWidth: RIGHT_PANEL_DEFAULT_WIDTH,
  resizeHandler: null,
  executionNotice: null,
  liveEventsExpanded: false,
  selectedPromptNodeId: null,
  selectedPromptCallIndex: 0,
  selectedTokenKey: null,
};

function apiUrl(path) {
  return api.apiURL(path);
}

async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`${response.status} ${message}`);
  }
  return await response.json();
}

function injectStyles() {
  const id = "comfy-trace-inspector-style";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = new URL("./trace_inspector.css", import.meta.url).href;
  document.head.appendChild(link);
}

function nowIso() {
  return new Date().toISOString();
}

function activeWorkflowName() {
  const workflow = app.extensionManager?.workflow?.activeWorkflow;
  const value = workflow?.filename || workflow?.path || "";
  const name = String(value).replaceAll("\\", "/").split("/").pop().trim();
  return name || null;
}

function runIdentity(run) {
  return run.workflowName || run.label || run.runId?.slice(0, 8) || localeText("실행", "Run");
}

function noteCategoryLabel(value) {
  const category = NOTE_CATEGORIES.find((item) => item.value === value);
  return category ? localeText(category.ko, category.en) : value || localeText("관찰", "Observation");
}

function compactDetail(detail) {
  if (detail == null) return null;
  try {
    return JSON.parse(JSON.stringify(detail, (_key, value) => {
      if (typeof value === "string" && value.length > 2000) return `${value.slice(0, 1997)}...`;
      return value;
    }));
  } catch (_error) {
    return { value: String(detail) };
  }
}

function enqueueEvent(type, detail = null) {
  state.pendingEvents.push({
    type,
    timestamp: nowIso(),
    promptId: state.currentPromptId,
    detail: compactDetail(detail),
  });
  if (state.pendingEvents.length > 5000) {
    state.pendingEvents.splice(0, state.pendingEvents.length - 5000);
  }
}

async function flushEvents(completionType = null, completionDetail = null) {
  if (completionType) enqueueEvent(completionType, completionDetail);
  const runIds = [...state.currentRunIds];
  if (!runIds.length && state.currentRunId) runIds.push(state.currentRunId);
  if (!runIds.length || state.pendingEvents.length === 0) return;
  const events = state.pendingEvents.splice(0, state.pendingEvents.length);
  let failures = 0;
  for (const runId of runIds) {
    try {
      await requestJson(`/trace-inspector/runs/${runId}/frontend-events`, {
        method: "POST",
        body: JSON.stringify({ events }),
      });
    } catch (error) {
      failures += 1;
      console.warn(`[Sampling Trace Inspector] Failed to persist frontend events for ${runId}`, error);
    }
  }
  if (failures === runIds.length) state.pendingEvents.unshift(...events.slice(-1000));
}

function closeActiveNode(nextNode = null) {
  if (state.activeNode == null || state.activeNodeStartedAt == null) return;
  enqueueEvent("node_end", {
    node: state.activeNode,
    nextNode,
    durationMs: performance.now() - state.activeNodeStartedAt,
  });
  state.activeNode = null;
  state.activeNodeStartedAt = null;
}

function installEventListeners() {
  api.addEventListener("execution_start", (event) => {
    state.currentPromptId = event.detail?.prompt_id || null;
    state.currentRunId = null;
    state.currentRunIds.clear();
    state.pendingEvents = [];
    state.activeNode = null;
    state.activeNodeStartedAt = null;
    state.executionNotice = null;
    state.currentWorkflowName = activeWorkflowName();
    enqueueEvent("execution_start", event.detail);
    if (state.currentWorkflowName) {
      enqueueEvent("workflow_identity", { workflowName: state.currentWorkflowName });
    }
    render();
  });

  api.addEventListener("execution_cached", (event) => {
    enqueueEvent("execution_cached", event.detail);
  });

  api.addEventListener("executing", (event) => {
    const node = event.detail?.node ?? null;
    closeActiveNode(node);
    enqueueEvent("executing", event.detail);
    if (node != null) {
      state.activeNode = String(node);
      state.activeNodeStartedAt = performance.now();
      enqueueEvent("node_start", { node: state.activeNode });
    }
    renderLiveStatus();
  });

  api.addEventListener("progress", (event) => {
    enqueueEvent("progress", event.detail);
    renderLiveStatus(event.detail);
  });

  api.addEventListener("executed", (event) => {
    enqueueEvent("executed", event.detail);
  });

  const complete = async (type, detail) => {
    const promptId = state.currentPromptId;
    const createdTraceRun = state.currentRunIds.size > 0 || Boolean(state.currentRunId);
    closeActiveNode(null);
    await flushEvents(type, detail);
    if (type === "execution_success" && !createdTraceRun) {
      state.executionNotice = await missingTraceRunNotice(promptId);
    }
    scheduleRefresh(true);
  };

  api.addEventListener("execution_success", (event) => complete("execution_success", event.detail));
  api.addEventListener("execution_error", (event) => complete("execution_error", event.detail));
  api.addEventListener("execution_interrupted", (event) => complete("execution_interrupted", event.detail));

  api.addEventListener(`${EVENT_PREFIX}session_ready`, (event) => {
    state.currentRunId = event.detail?.runId || null;
    if (state.currentRunId) {
      state.currentRunIds.add(state.currentRunId);
      state.selectedRunId = state.currentRunId;
      state.executionNotice = null;
      enqueueEvent("trace_session_ready", event.detail);
    }
    scheduleRefresh(true);
  });

  api.addEventListener(`${EVENT_PREFIX}run_started`, (event) => {
    state.currentRunId = event.detail?.runId || state.currentRunId;
    if (state.currentRunId) state.currentRunIds.add(state.currentRunId);
    state.selectedRunId = state.currentRunId || state.selectedRunId;
    enqueueEvent("trace_run_started", event.detail);
    scheduleRefresh(true);
  });

  api.addEventListener(`${EVENT_PREFIX}step`, (event) => {
    if (event.detail?.runId) {
      state.currentRunId = event.detail.runId;
      state.currentRunIds.add(event.detail.runId);
      state.selectedRunId = event.detail.runId;
    }
    scheduleRefresh(false);
  });

  api.addEventListener(`${EVENT_PREFIX}segment_finished`, (_event) => scheduleRefresh(true));
  api.addEventListener(`${EVENT_PREFIX}run_finished`, (_event) => scheduleRefresh(true));
  api.addEventListener(`${EVENT_PREFIX}probe`, (_event) => scheduleRefresh(false));
}

async function missingTraceRunNotice(promptId) {
  if (!promptId) {
    return localeText(
      "새 추적 실행이 기록되지 않았습니다. 최종 MODEL → 샘플링 추적 모델 → 샘플러 연결을 확인하세요.",
      "No new trace run was recorded. Check the final MODEL → Sampling Trace Model → sampler connection.",
    );
  }
  try {
    const history = await requestJson(`/history/${encodeURIComponent(promptId)}`);
    const graph = history?.[promptId]?.prompt?.[2] || {};
    const hasTraceModel = Object.values(graph).some((node) => node?.class_type === "ComfyTraceModel");
    if (!hasTraceModel) {
      return localeText(
        "이번 실행에는 샘플링 추적 모델이 없어 기록되지 않았습니다. 최종 MODEL과 샘플러 사이에 추적 노드를 연결하세요.",
        "This execution was not recorded because it had no Sampling Trace Model. Connect the trace node between the final MODEL and sampler.",
      );
    }
    return localeText(
      "샘플링 추적 모델이 실행 그래프에는 있지만 새 실행 기록을 만들지 못했습니다. 노드 우회·캐시 상태와 MODEL 연결을 확인하세요.",
      "Sampling Trace Model is present in the execution graph, but it did not create a new run. Check node bypass/cache state and the MODEL connection.",
    );
  } catch (_error) {
    return localeText(
      "새 추적 실행이 기록되지 않았습니다. 샘플링 추적 모델 연결 또는 실행 상태를 확인하세요.",
      "No new trace run was recorded. Check the Sampling Trace Model connection or execution state.",
    );
  }
}

function scheduleRefresh(immediate = false) {
  if (state.refreshTimer) clearTimeout(state.refreshTimer);
  state.refreshTimer = setTimeout(async () => {
    state.refreshTimer = null;
    await refreshRuns();
    if (state.selectedRunId) await loadRun(state.selectedRunId, false);
  }, immediate ? 0 : 250);
}

async function refreshRuns() {
  try {
    const data = await requestJson("/trace-inspector/runs?limit=200");
    state.runs = data.runs || [];
    if (!state.selectedRunId && state.runs.length) state.selectedRunId = state.runs[0].runId;
    render();
  } catch (error) {
    setPanelError(error);
  }
}

async function loadRun(runId, resetStep = true) {
  if (!runId) return;
  try {
    if (state.selectedRunId && state.selectedRunId !== runId) state.noteNotice = null;
    state.selectedRun = await requestJson(`/trace-inspector/runs/${runId}`);
    state.selectedRunId = runId;
    if (resetStep || !state.selectedNodeId) {
      state.selectedNodeId = String(state.selectedRun.nodeId || "");
    }
    state.canvasNotice = null;
    if (resetStep) {
      state.selectedStepIndex = Math.max(0, (state.selectedRun.steps?.length || 1) - 1);
      state.selectedPromptNodeId = null;
      state.selectedPromptCallIndex = 0;
      state.selectedTokenKey = null;
    } else {
      state.selectedStepIndex = Math.min(
        state.selectedStepIndex,
        Math.max(0, (state.selectedRun.steps?.length || 1) - 1),
      );
      if (runId === state.currentRunId) {
        state.selectedStepIndex = Math.max(0, (state.selectedRun.steps?.length || 1) - 1);
      }
    }
    render();
  } catch (error) {
    setPanelError(error);
  }
}

function el(tag, className = "", text = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function button(text, onClick, className = "") {
  const result = el("button", `cti-button ${className}`, text);
  result.addEventListener("click", onClick);
  return result;
}

function formatNumber(value, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function formatTime(value) {
  if (!value) return "—";
  try { return new Date(value).toLocaleString(); } catch (_error) { return String(value); }
}

function statusLabel(status) {
  return ({
    success: localeText("완료", "Complete"),
    running: localeText("기록 중", "Capturing"),
    sampling_complete: localeText("추적 기록됨", "Trace captured"),
    error: localeText("실패", "Failed"),
    interrupted: localeText("중단됨", "Interrupted"),
  })[status] || status || localeText("알 수 없음", "Unknown");
}

function modeLabel(mode) {
  return ({
    basic: localeText("기본", "Basic"),
    advanced: localeText("고급", "Advanced"),
  })[mode] || mode || "—";
}

function semanticRoleLabel(role) {
  if (!isKoreanLocale()) return role || "workflow";
  return ({
    sampler: "샘플러",
    sampling_controller: "샘플링 제어",
    text_condition_encoder: "텍스트 조건 인코더",
    pixel_latent_converter: "픽셀·잠재값 변환",
    preview: "미리보기",
    output: "출력",
    probe: "검사",
    trace: "추적",
    other: "기타",
    workflow: "워크플로",
  })[role] || role || "워크플로";
}

function previewStepIndexes(steps) {
  return steps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => Boolean(step.previewUrl))
    .map(({ index }) => index);
}

function nearestPreviewStepIndex(indexes, selectedIndex) {
  return indexes.reduce((nearest, index) => (
    Math.abs(index - selectedIndex) < Math.abs(nearest - selectedIndex) ? index : nearest
  ), indexes[0]);
}

function nodeLabel(node) {
  const names = isKoreanLocale() ? {
    CheckpointLoaderSimple: "체크포인트",
    CLIPTextEncode: "프롬프트",
    EmptyLatentImage: "잠재값",
    KSampler: "KSampler",
    VAEDecode: "VAE 디코드",
    SaveImage: "이미지 저장",
    ComfyTraceModel: "샘플링 추적 모델",
    ComfyTraceLatent: "잠재값 검사",
    ComfyTraceExport: "추적 내보내기",
  } : {
    CheckpointLoaderSimple: "Checkpoint",
    CLIPTextEncode: "Prompt",
    EmptyLatentImage: "Latent",
    KSampler: "KSampler",
    VAEDecode: "VAE Decode",
    SaveImage: "Save Image",
    ComfyTraceModel: "Trace Model",
    ComfyTraceLatent: "Latent Probe",
    ComfyTraceExport: "Export",
  };
  return names[node?.classType] || node?.classType || `${localeText("노드", "Node")} ${node?.id ?? "—"}`;
}

function nodeKind(node) {
  const type = node?.classType || "";
  if (type === "KSampler") return "sampler";
  if (type.startsWith("ComfyTrace")) return "trace";
  if (type.includes("Save") || type.includes("Preview")) return "output";
  if (type.includes("Decode") || type.includes("Encode")) return "transform";
  return "source";
}

function workflowNodes(run) {
  const nodes = [...(run?.promptAnalysis?.nodes || [])];
  const byId = new Map(nodes.map((node) => [String(node.id), node]));
  const outgoing = new Map(nodes.map((node) => [String(node.id), []]));
  const indegree = new Map(nodes.map((node) => [String(node.id), 0]));

  for (const node of nodes) {
    for (const input of Object.values(node.inputs || {})) {
      const sourceId = Array.isArray(input?.link) ? String(input.link[0]) : null;
      if (!sourceId || !byId.has(sourceId)) continue;
      outgoing.get(sourceId).push(String(node.id));
      indegree.set(String(node.id), (indegree.get(String(node.id)) || 0) + 1);
    }
  }

  const numericSort = (left, right) => Number(left) - Number(right) || left.localeCompare(right);
  const ready = [...indegree.entries()].filter(([, count]) => count === 0).map(([id]) => id).sort(numericSort);
  const ordered = [];
  while (ready.length) {
    const id = ready.shift();
    ordered.push(byId.get(id));
    for (const target of outgoing.get(id) || []) {
      indegree.set(target, indegree.get(target) - 1);
      if (indegree.get(target) === 0) {
        ready.push(target);
        ready.sort(numericSort);
      }
    }
  }
  return ordered.length === nodes.length ? ordered : nodes;
}

function samplingPathNodes(run) {
  const nodes = run?.promptAnalysis?.nodes || [];
  const rootId = String(run?.nodeId ?? "");
  const byId = new Map(nodes.map((node) => [String(node.id), node]));
  if (!rootId || !byId.has(rootId)) return [];

  const incoming = new Map(nodes.map((node) => [String(node.id), []]));
  const outgoing = new Map(nodes.map((node) => [String(node.id), []]));
  for (const node of nodes) {
    const targetId = String(node.id);
    for (const input of Object.values(node.inputs || {})) {
      const sourceId = Array.isArray(input?.link) ? String(input.link[0]) : null;
      if (!sourceId || !byId.has(sourceId)) continue;
      incoming.get(targetId).push(sourceId);
      outgoing.get(sourceId).push(targetId);
    }
  }

  const downstream = new Set([rootId]);
  const forward = [rootId];
  while (forward.length) {
    const current = forward.pop();
    for (const next of outgoing.get(current) || []) {
      if (downstream.has(next)) continue;
      downstream.add(next);
      forward.push(next);
    }
  }

  const pathIds = new Set(downstream);
  const backward = [...downstream];
  while (backward.length) {
    const current = backward.pop();
    for (const previous of incoming.get(current) || []) {
      if (pathIds.has(previous)) continue;
      pathIds.add(previous);
      backward.push(previous);
    }
  }
  return nodes.filter((node) => pathIds.has(String(node.id)));
}

function matchingCanvasNodes(run, capturedNodes = null) {
  const graph = app.graph;
  const targets = capturedNodes || run?.promptAnalysis?.nodes || [];
  if (!targets.length) return null;
  const liveNodes = targets.map((captured) => {
    const live = graph?.getNodeById?.(Number(captured.id)) || graph?.getNodeById?.(String(captured.id));
    const liveType = live?.type || live?.constructor?.comfyClass || null;
    return liveType === captured.classType ? live : null;
  });
  return liveNodes.every(Boolean) ? liveNodes : null;
}

function clearCanvasSelection(canvas) {
  if (!canvas) return;
  if (typeof canvas.deselectAll === "function") {
    canvas.deselectAll();
  } else if (typeof canvas.deselectAllNodes === "function") {
    canvas.deselectAllNodes();
  } else {
    canvas.selectedItems?.clear?.();
  }
  canvas.setDirty?.(true, true);
}

function replaceCanvasSelection(canvas, items) {
  clearCanvasSelection(canvas);
  if (!canvas || !items?.length) return;
  if (items.length === 1 && typeof canvas.select === "function") {
    canvas.select(items[0]);
  } else if (typeof canvas.selectItems === "function") {
    canvas.selectItems(items);
  } else if (items.length === 1 && typeof canvas.selectNode === "function") {
    canvas.selectNode(items[0], false);
  } else if (typeof canvas.selectNodes === "function") {
    canvas.selectNodes(items);
  } else {
    for (const node of items) canvas.selectNode?.(node, true);
  }
  canvas.setDirty?.(true, true);
}

function focusCanvasNode(nodeId, expectedClassType = null, run = null) {
  const graph = app.graph;
  const canvas = app.canvas;
  const node = graph?.getNodeById?.(Number(nodeId)) || graph?.getNodeById?.(String(nodeId));
  const actualClassType = node?.type || node?.constructor?.comfyClass || null;
  const capturedNode = (run?.promptAnalysis?.nodes || [])
    .find((item) => String(item.id) === String(nodeId));
  const liveNodes = capturedNode ? matchingCanvasNodes(run, [capturedNode]) : null;
  if (!node || !canvas || !liveNodes || (expectedClassType && actualClassType !== expectedClassType)) {
    state.canvasNotice = isKoreanLocale()
      ? `노드 #${nodeId}(${expectedClassType || "알 수 없는 유형"})가 현재 캔버스와 일치하지 않습니다. 이 실행의 워크플로를 불러온 뒤 위치를 찾으세요.`
      : `Node #${nodeId} (${expectedClassType || "unknown type"}) does not match the current canvas. Load this run's workflow before focusing it.`;
    render();
    return;
  }

  replaceCanvasSelection(canvas, [node]);
  canvas.centerOnNode?.(node);
  state.canvasNotice = localeText(`캔버스에서 노드 #${nodeId} 위치를 찾았습니다.`, `Focused node #${nodeId} on the canvas.`);
  render();
}

function selectCanvasPath(run) {
  const canvas = app.canvas;
  const capturedPath = samplingPathNodes(run);
  const liveNodes = matchingCanvasNodes(run, capturedPath);
  if (!canvas || !liveNodes) {
    state.canvasNotice = localeText(
      "기록된 샘플링 경로가 현재 캔버스와 일치하지 않습니다. 이 실행의 워크플로를 불러온 뒤 다시 선택하세요.",
      "The captured sampling path does not match the current canvas. Load this run's workflow and try again.",
    );
    render();
    return;
  }
  replaceCanvasSelection(canvas, liveNodes);
  const traceNode = liveNodes.find((node) => String(node.id) === String(run.nodeId));
  if (traceNode) canvas.centerOnNode?.(traceNode);
  state.canvasNotice = localeText(
    `Trace Model과 연결된 샘플링 경로 노드 ${liveNodes.length}개를 선택했습니다.`,
    `Selected ${liveNodes.length} sampling-path nodes connected to the Trace Model.`,
  );
  render();
}

function imageUrl(path) {
  return path ? apiUrl(path) : "";
}

function setPanelError(error) {
  console.error("[Sampling Trace Inspector]", error);
  const status = state.root?.querySelector("[data-role='status']");
  if (status) status.textContent = `${localeText("오류", "Error")}: ${error.message || error}`;
}

function renderLiveStatus(progress = null) {
  const status = state.root?.querySelector("[data-role='status']");
  if (!status) return;
  const parts = [];
  if (state.currentPromptId) parts.push(`${localeText("프롬프트", "Prompt")} ${state.currentPromptId.slice(0, 8)}`);
  if (state.activeNode) parts.push(`${localeText("노드", "Node")} ${state.activeNode}`);
  if (progress?.value != null && progress?.max != null) parts.push(`${progress.value}/${progress.max}`);
  status.textContent = parts.join(" · ") || localeText("대기", "Idle");
}

function readExpandedPreference() {
  try {
    const stored = window.localStorage.getItem(EXPANDED_STORAGE_KEY);
    return stored == null ? true : stored === "true";
  } catch (_error) {
    return true;
  }
}

function readRightPanelWidthPreference() {
  try {
    const stored = window.localStorage.getItem(RIGHT_PANEL_WIDTH_STORAGE_KEY);
    if (stored == null) return RIGHT_PANEL_DEFAULT_WIDTH;
    const value = Number(stored);
    return Number.isFinite(value) ? value : RIGHT_PANEL_DEFAULT_WIDTH;
  } catch (_error) {
    return RIGHT_PANEL_DEFAULT_WIDTH;
  }
}

function rightPanelWidthBounds() {
  const body = state.root?.querySelector(".cti-body");
  const runs = state.root?.querySelector(".cti-runs");
  const splitter = state.root?.querySelector(".cti-right-splitter");
  if (!body || !runs || !splitter || body.clientWidth <= 0) {
    return { min: RIGHT_PANEL_MIN_WIDTH, max: RIGHT_PANEL_MAX_WIDTH };
  }
  const available = body.clientWidth - runs.getBoundingClientRect().width - splitter.offsetWidth - CENTER_PANEL_MIN_WIDTH;
  return {
    min: RIGHT_PANEL_MIN_WIDTH,
    max: Math.max(RIGHT_PANEL_MIN_WIDTH, Math.min(RIGHT_PANEL_MAX_WIDTH, available)),
  };
}

function applyRightPanelWidth(width, persist = false) {
  if (!state.root) return;
  const bounds = rightPanelWidthBounds();
  const next = Math.round(Math.min(bounds.max, Math.max(bounds.min, Number(width) || RIGHT_PANEL_DEFAULT_WIDTH)));
  state.rightPanelWidth = next;
  state.root.style.setProperty("--cti-right-width", `${next}px`);
  const splitter = state.root.querySelector(".cti-right-splitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(bounds.min));
    splitter.setAttribute("aria-valuemax", String(bounds.max));
    splitter.setAttribute("aria-valuenow", String(next));
  }
  if (persist) {
    try {
      window.localStorage.setItem(RIGHT_PANEL_WIDTH_STORAGE_KEY, String(next));
    } catch (_error) {
      // Storage can be unavailable in hardened browser profiles; the current view still works.
    }
  }
}

function createRightPanelSplitter() {
  const splitter = el("div", "cti-right-splitter");
  splitter.tabIndex = 0;
  splitter.setAttribute("role", "separator");
  splitter.setAttribute("aria-label", localeText("선택 실행 및 비교 패널 너비 조절", "Resize selected run and comparison panel"));
  splitter.setAttribute("aria-orientation", "vertical");
  splitter.title = localeText(
    "드래그하여 오른쪽 패널 너비를 조절합니다. 두 번 클릭하면 기본값으로 돌아갑니다.",
    "Drag to resize the right panel. Double-click to reset.",
  );

  splitter.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const right = state.root?.querySelector(".cti-right");
    if (!right) return;
    const startX = event.clientX;
    const startWidth = right.getBoundingClientRect().width;
    splitter.setPointerCapture(event.pointerId);
    state.root.classList.add("is-resizing-right");

    const move = (moveEvent) => applyRightPanelWidth(startWidth + startX - moveEvent.clientX);
    const finish = () => {
      splitter.removeEventListener("pointermove", move);
      splitter.removeEventListener("pointerup", finish);
      splitter.removeEventListener("pointercancel", finish);
      state.root?.classList.remove("is-resizing-right");
      applyRightPanelWidth(state.rightPanelWidth, true);
    };
    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("pointerup", finish);
    splitter.addEventListener("pointercancel", finish);
  });
  splitter.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    applyRightPanelWidth(state.rightPanelWidth + (event.key === "ArrowLeft" ? 24 : -24), true);
  });
  splitter.addEventListener("dblclick", () => applyRightPanelWidth(RIGHT_PANEL_DEFAULT_WIDTH, true));
  return splitter;
}

function updateExpandedButton() {
  const toggle = state.root?.querySelector("[data-role='expanded-toggle']");
  if (!toggle) return;
  toggle.textContent = state.expanded ? localeText("패널로 돌아가기", "Back to panel") : localeText("크게 보기", "Expand");
  toggle.title = state.expanded
    ? localeText("샘플링 추적 분석기를 ComfyUI 하단 패널로 되돌립니다(Esc).", "Return Sampling Trace Inspector to the ComfyUI bottom panel (Esc)")
    : localeText("샘플링 추적 분석기를 큰 작업 공간으로 엽니다.", "Open Sampling Trace Inspector in a large workspace");
  toggle.setAttribute("aria-pressed", String(state.expanded));
}

function setExpanded(expanded, persist = true) {
  if (!state.root || !state.panelContainer) return;
  state.expanded = Boolean(expanded);
  state.root.classList.toggle("is-expanded", state.expanded);

  if (state.expanded) {
    if (state.root.parentElement !== document.body) document.body.append(state.root);
  } else if (state.root.parentElement !== state.panelContainer) {
    state.panelContainer.replaceChildren(state.root);
  }

  updateExpandedButton();
  requestAnimationFrame(() => applyRightPanelWidth(state.rightPanelWidth));
  if (persist) {
    try {
      window.localStorage.setItem(EXPANDED_STORAGE_KEY, String(state.expanded));
    } catch (_error) {
      // Storage can be unavailable in hardened browser profiles; the current view still works.
    }
  }
}

function createToolbar() {
  const bar = el("div", "cti-toolbar");
  const brand = el("div", "cti-brand");
  const refreshButton = button(localeText("새로고침", "Refresh"), async () => {
    await refreshRuns();
    if (state.selectedRunId) await loadRun(state.selectedRunId, false);
  });
  const latestButton = button(localeText("최신 실행", "Latest"), async () => {
    if (state.runs[0]) await loadRun(state.runs[0].runId, true);
  });
  latestButton.title = localeText(
    "가장 최근에 생성된 실행 기록을 엽니다.",
    "Open the most recently created run.",
  );
  brand.append(
    el("strong", "cti-title", localeText("샘플링 추적 분석기", "Sampling Trace Inspector")),
    el("span", "cti-brand-subtitle", localeText("샘플링 분석", "Sampling analyzer")),
  );
  bar.append(
    brand,
    refreshButton,
    latestButton,
  );
  const status = el("span", "cti-status", localeText("대기", "Idle"));
  status.dataset.role = "status";
  const expandedToggle = button(localeText("크게 보기", "Expand"), () => setExpanded(!state.expanded));
  expandedToggle.dataset.role = "expanded-toggle";
  bar.append(status, expandedToggle);
  return bar;
}

function renderRunList(container) {
  container.replaceChildren();
  container.append(el("h3", "cti-section-title", `${localeText("실행 기록", "Runs")} (${state.runs.length})`));
  const list = el("div", "cti-run-list");
  for (const run of state.runs) {
    const row = el("button", `cti-run-row ${run.runId === state.selectedRunId ? "selected" : ""}`);
    row.addEventListener("click", () => loadRun(run.runId, true));
    row.append(
      el("span", "cti-run-label", runIdentity(run)),
      el("span", `cti-badge status-${run.status}`, statusLabel(run.status)),
      el(
        "span",
        "cti-run-meta",
        `${run.workflowName && run.label ? `${run.label} · ` : ""}${run.stepCount || 0}${localeText("스텝", " steps")} · ${formatTime(run.startedAt || run.createdAt)}`,
      ),
    );
    list.append(row);
  }
  container.append(list);
}

function metricCard(label, value, hint = "") {
  const card = el("div", "cti-metric-card");
  card.append(el("span", "cti-metric-label", label), el("strong", "cti-metric-value", value));
  if (hint) card.title = hint;
  return card;
}

function createNoteCategorySelect(selected = "observation") {
  const select = document.createElement("select");
  select.className = "cti-select";
  for (const category of NOTE_CATEGORIES) {
    const option = document.createElement("option");
    option.value = category.value;
    option.textContent = localeText(category.ko, category.en);
    option.selected = category.value === selected;
    select.append(option);
  }
  return select;
}

function stepSegmentIndex(step) {
  return Number.isInteger(step?.segmentIndex) && step.segmentIndex >= 0
    ? step.segmentIndex
    : 0;
}

function noteStepLabel(step, segmentIndex = null, run = null) {
  if (!Number.isInteger(step) || step < 0) {
    return localeText("실행 전체", "Whole run");
  }
  const segmentCount = new Set((run?.steps || []).map(stepSegmentIndex)).size;
  if (segmentCount > 1) {
    if (Number.isInteger(segmentIndex) && segmentIndex >= 0) {
      return localeText(
        `구간 ${segmentIndex + 1} · 스텝 ${step + 1}`,
        `Segment ${segmentIndex + 1} · Step ${step + 1}`,
      );
    }
    return localeText(
      `구간 미지정 · 스텝 ${step + 1}`,
      `Unspecified segment · Step ${step + 1}`,
    );
  }
  return `${localeText("스텝", "Step")} ${step + 1}`;
}

function displayedStepTarget(run) {
  const steps = run?.steps || [];
  if (!steps.length) return null;
  const selected = steps[state.selectedStepIndex];
  if (selected?.previewUrl) {
    return { step: selected.step, segmentIndex: stepSegmentIndex(selected) };
  }
  const indexes = previewStepIndexes(steps);
  const nearest = indexes.length
    ? steps[nearestPreviewStepIndex(indexes, state.selectedStepIndex)]
    : selected;
  return Number.isInteger(nearest?.step)
    ? { step: nearest.step, segmentIndex: stepSegmentIndex(nearest) }
    : null;
}

function createNoteStepSelect(run, selectedTarget = null) {
  const select = document.createElement("select");
  select.className = "cti-select cti-note-step-select";
  const wholeRun = document.createElement("option");
  wholeRun.value = "";
  wholeRun.textContent = localeText("실행 전체", "Whole run");
  wholeRun.selected = !Number.isInteger(selectedTarget?.step);
  select.append(wholeRun);

  let targetMatched = false;
  for (const [index, item] of (run?.steps || []).entries()) {
    if (!Number.isInteger(item?.step) || item.step < 0) continue;
    const segmentIndex = stepSegmentIndex(item);
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = noteStepLabel(item.step, segmentIndex, run);
    const stepMatches = item.step === selectedTarget?.step;
    const segmentMatches = Number.isInteger(selectedTarget?.segmentIndex)
      ? segmentIndex === selectedTarget.segmentIndex
      : stepMatches && !targetMatched;
    option.selected = stepMatches && segmentMatches && !targetMatched;
    if (option.selected) targetMatched = true;
    select.append(option);
  }
  return select;
}

function selectedNoteTarget(select, run) {
  if (select.value === "") return { step: null, segmentIndex: null };
  const item = run?.steps?.[Number(select.value)];
  return Number.isInteger(item?.step)
    ? { step: item.step, segmentIndex: stepSegmentIndex(item) }
    : { step: null, segmentIndex: null };
}

function setupNoteTextarea(textarea, submit) {
  const resize = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  };
  textarea.rows = 3;
  textarea.title = localeText(
    "Enter: 줄바꿈 · Ctrl+Enter: 저장",
    "Enter: new line · Ctrl+Enter: save",
  );
  textarea.addEventListener("input", resize);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  });
  requestAnimationFrame(resize);
}

function focusNoteStep(run, step, segmentIndex = null) {
  const candidates = (run?.steps || [])
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item?.step === step);
  const target = Number.isInteger(segmentIndex)
    ? candidates.find(({ item }) => stepSegmentIndex(item) === segmentIndex)
    : candidates.length === 1 ? candidates[0] : null;
  if (!target || !target.item?.previewUrl) {
    state.noteNotice = {
      runId: run.runId,
      type: "error",
      text: localeText(
        candidates.length > 1 && !Number.isInteger(segmentIndex)
          ? "이전 메모에 샘플러 구간 정보가 없습니다. 메모를 수정해 스텝을 다시 선택하세요."
          : "이 스텝에는 저장된 미리보기가 없어 이동할 수 없습니다.",
        candidates.length > 1 && !Number.isInteger(segmentIndex)
          ? "This legacy note has no sampler segment. Edit it and select the step again."
          : "This step has no saved preview to focus.",
      ),
    };
    render();
    return;
  }

  state.selectedStepIndex = target.index;
  render();
}

async function performNoteAction(runId, action, successMessage) {
  try {
    await action();
    state.noteNotice = { runId, type: "success", text: successMessage };
    await loadRun(runId, false);
  } catch (error) {
    state.noteNotice = { runId, type: "error", text: `${localeText("메모 처리 오류", "Note error")}: ${error.message || error}` };
    render();
  }
}

function renderNotes(container, run) {
  const notes = (run.probes || []).filter((probe) => probe?.probeType === "note").reverse();
  const section = el("div", "cti-notes");
  const header = el("div", "cti-notes-header");
  header.append(
    el("strong", "", `${localeText("메모", "Notes")} (${notes.length})`),
    el("span", "cti-section-kicker", localeText("이 실행에 저장됨", "Saved with this run")),
  );
  section.append(header);

  if (state.noteNotice?.runId === run.runId) {
    section.append(el("div", `cti-note-feedback ${state.noteNotice.type}`, state.noteNotice.text));
  }

  if (!notes.length) {
    section.append(el("div", "cti-empty cti-note-empty", localeText(
      "저장된 메모가 없습니다. 위에서 관찰, 가설, 결정 또는 문제를 추가하세요.",
      "No notes yet. Add an observation, hypothesis, decision, or issue above.",
    )));
    container.append(section);
    return;
  }

  const list = el("div", "cti-note-list");
  for (const note of notes) {
    const card = el("article", "cti-note-card");
    const meta = el("div", "cti-note-meta");
    meta.append(
      el("span", "cti-badge", noteCategoryLabel(note.label)),
      el("span", "cti-badge cti-note-step", noteStepLabel(note.step, note.segmentIndex, run)),
      el("span", "cti-note-time", `${note.updatedAt ? `${localeText("수정됨", "Edited")} · ` : ""}${formatTime(note.updatedAt || note.timestamp)}`),
    );
    const copy = el("p", "cti-note-text", note.summary?.text || "");
    card.append(meta, copy);

    if (note.noteId) {
      const actions = el("div", "cti-note-actions");
      if (Number.isInteger(note.step)) {
        const focusButton = button(localeText("스텝 보기", "View step"), () => {
          focusNoteStep(run, note.step, note.segmentIndex);
        }, "secondary");
        focusButton.title = localeText(
          `${noteStepLabel(note.step, note.segmentIndex, run)} 미리보기로 이동`,
          `Focus the ${noteStepLabel(note.step, note.segmentIndex, run)} preview`,
        );
        actions.append(focusButton);
      }
      actions.append(
        button(localeText("수정", "Edit"), () => {
          const editor = el("div", "cti-note-editor");
          const textarea = document.createElement("textarea");
          textarea.value = note.summary?.text || "";
          textarea.maxLength = 8000;
          const category = createNoteCategorySelect(note.label || "observation");
          const step = createNoteStepSelect(run, Number.isInteger(note.step)
            ? { step: note.step, segmentIndex: note.segmentIndex }
            : null);
          const editorActions = el("div", "cti-note-actions");
          const saveNote = async () => {
            const text = textarea.value.trim();
            if (!text) {
              textarea.focus();
              return;
            }
            await performNoteAction(run.runId, () => requestJson(
              `/trace-inspector/runs/${run.runId}/notes/${encodeURIComponent(note.noteId)}`,
              {
                method: "PATCH",
                body: JSON.stringify({ text, category: category.value, ...selectedNoteTarget(step, run) }),
              },
            ), localeText("메모를 수정했습니다.", "Note updated."));
          };
          editorActions.append(
            button(localeText("저장", "Save"), saveNote, "primary"),
            button(localeText("취소", "Cancel"), () => render(), "secondary"),
          );
          editor.append(textarea, category, step, editorActions);
          card.replaceChildren(meta, editor);
          setupNoteTextarea(textarea, saveNote);
          textarea.focus();
        }, "secondary"),
        button(localeText("삭제", "Delete"), async () => {
          if (!window.confirm(localeText(
            "이 메모를 삭제할까요? 삭제 후에는 되돌릴 수 없습니다.",
            "Delete this note? This action cannot be undone.",
          ))) return;
          await performNoteAction(run.runId, () => requestJson(
            `/trace-inspector/runs/${run.runId}/notes/${encodeURIComponent(note.noteId)}`,
            { method: "DELETE" },
          ), localeText("메모를 삭제했습니다.", "Note deleted."));
        }, "danger"),
      );
      card.append(actions);
    } else {
      card.append(el("div", "cti-inline-notice muted", localeText(
        "이전 형식의 메모라 내용을 수정할 수 없습니다.",
        "This legacy note cannot be edited.",
      )));
    }
    list.append(card);
  }
  section.append(list);
  container.append(section);
}

function renderStepViewer(container, run) {
  container.replaceChildren();
  const steps = run?.steps || [];
  const previewIndexes = previewStepIndexes(steps);
  const header = el("div", "cti-section-header");
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", localeText("노이즈 제거 미리보기", "Denoise Preview")),
    el("span", "cti-section-kicker", localeText("프레임을 드래그하거나 클릭하여 이미지가 만들어지는 과정을 살펴봅니다.", "Drag or click a frame to inspect how the image formed.")),
  );
  header.append(heading);

  if (run?.reportFiles?.html) {
    header.append(button(localeText("HTML 보고서", "HTML Report"), () => {
      window.open(apiUrl(`/trace-inspector/runs/${run.runId}/report/report.html`), "_blank");
    }));
  }
  if (run?.reportFiles?.markdown) {
    header.append(button(localeText("마크다운", "Markdown"), () => {
      window.open(apiUrl(`/trace-inspector/runs/${run.runId}/report/report.md`), "_blank");
    }));
  }
  container.append(header);

  if (!steps.length) {
    container.append(el("div", "cti-empty", localeText("기록된 샘플링 프레임이 없습니다. KSampler 바로 앞에 샘플링 추적 모델을 연결한 뒤 워크플로를 실행하세요.", "No sampling frames were captured. Connect Trace Model immediately before KSampler, then run the workflow.")));
    return;
  }

  if (!previewIndexes.length) {
    container.append(el("div", "cti-empty", localeText(
      "저장된 미리보기가 없습니다. 샘플링 추적 모델에서 미리보기 저장을 켠 뒤 실행하세요.",
      "No decoded previews were saved. Enable preview persistence on Sampling Trace Model, then run the workflow.",
    )));
    return;
  }

  state.selectedStepIndex = Math.max(0, Math.min(state.selectedStepIndex, steps.length - 1));
  if (!steps[state.selectedStepIndex]?.previewUrl) {
    state.selectedStepIndex = nearestPreviewStepIndex(previewIndexes, state.selectedStepIndex);
  }
  const step = steps[state.selectedStepIndex];
  const visual = el("div", "cti-visual-workspace");
  const imageWrap = el("div", "cti-preview-stage");
  if (step.previewUrl) {
    const img = document.createElement("img");
    img.className = "cti-preview";
    img.src = imageUrl(step.previewUrl);
    img.alt = localeText(`노이즈 제거 ${step.totalSteps}스텝 중 ${step.step + 1}스텝`, `Denoise step ${step.step + 1} of ${step.totalSteps}`);
    imageWrap.append(img);
  } else {
    imageWrap.append(el("div", "cti-empty", localeText("이 스텝은 미리보기를 저장하지 않았습니다.", "This step has no decoded preview.")));
  }
  const overlay = el("div", "cti-preview-overlay");
  overlay.append(
    el("strong", "cti-preview-step", `${localeText("스텝", "STEP")} ${step.step + 1} / ${step.totalSteps}`),
    el("span", "cti-preview-meta", `σ ${formatNumber(step.sigma, 3)} · Δ ${formatNumber(step.previewChange, 4)}`),
  );
  imageWrap.append(overlay);

  const insight = el("aside", "cti-step-insight");
  insight.append(el("span", "cti-insight-label", localeText("이 스텝에서 달라진 점", "What changed at this step")));
  const changeValue = step.previewChange;
  const changeText = changeValue == null
    ? localeText("기준 프레임입니다. 시각 변화량은 다음으로 기록된 스텝부터 계산됩니다.", "Baseline frame — visual change starts from the next captured step.")
    : changeValue >= 0.03
      ? localeText("시각 변화가 큽니다. 구도와 주요 형태가 아직 자리 잡는 중입니다.", "Large visual movement. Composition and major shapes are still settling.")
      : changeValue >= 0.01
        ? localeText("시각 변화가 보통입니다. 구조가 안정되는 중입니다.", "Moderate visual movement. Structure is stabilizing.")
        : localeText("시각 변화가 작습니다. 결과가 세부 표현으로 수렴하고 있습니다.", "Small visual movement. The result is converging into fine detail.");
  insight.append(el("p", "cti-insight-copy", changeText));
  const metrics = el("div", "cti-metrics");
  metrics.append(
    metricCard(localeText("시각 변화", "Visual change"), formatNumber(step.previewChange), localeText("이전 기록 미리보기 대비 정규화된 픽셀 변화", "Normalized pixel change from the previous captured preview")),
    metricCard(localeText("CFG 영향", "CFG influence"), formatNumber(step.cfg?.deltaMeanAbs), localeText("조건부·무조건부 예측 차이의 절댓값 평균", "Mean absolute conditional-unconditional delta")),
    metricCard(localeText("예측 x0", "Predicted x0"), `${formatNumber(step.x0?.mean, 3)} ± ${formatNumber(step.x0?.std, 3)}`),
    metricCard(localeText("제어 신호", "Control"), step.control?.active ? formatNumber(step.control?.weightedMeanAbs) : localeText("비활성", "Inactive"), localeText("ControlNet 잔차 절댓값 평균", "Control residual mean absolute value")),
  );
  insight.append(metrics);
  visual.append(imageWrap, insight);
  container.append(visual);

  const filmstrip = el("div", "cti-filmstrip");
  for (const index of previewIndexes) {
    const frame = steps[index];
    const frameButton = el("button", `cti-frame ${index === state.selectedStepIndex ? "selected" : ""}`);
    frameButton.type = "button";
    frameButton.title = localeText(`스텝 ${frame.step + 1} · Sigma ${formatNumber(frame.sigma, 3)} · 변화 ${formatNumber(frame.previewChange, 4)}`, `Step ${frame.step + 1} · sigma ${formatNumber(frame.sigma, 3)} · change ${formatNumber(frame.previewChange, 4)}`);
    frameButton.addEventListener("click", () => {
      state.selectedStepIndex = index;
      render();
    });
    const thumb = document.createElement("img");
    thumb.src = imageUrl(frame.previewUrl);
    thumb.alt = "";
    frameButton.append(thumb);
    frameButton.append(el("span", "cti-frame-index", String(frame.step + 1)));
    filmstrip.append(frameButton);
  }
  container.append(filmstrip);

  const scrubber = el("div", "cti-scrubber");
  const range = document.createElement("input");
  range.type = "range";
  range.min = "0";
  range.max = String(previewIndexes.length - 1);
  range.value = String(previewIndexes.indexOf(state.selectedStepIndex));
  range.setAttribute("aria-label", localeText("노이즈 제거 스텝", "Denoise step"));
  range.addEventListener("input", () => {
    state.selectedStepIndex = previewIndexes[Number(range.value)];
    render();
  });
  const previewPosition = previewIndexes.indexOf(state.selectedStepIndex);
  scrubber.append(
    button(localeText("이전", "Previous"), () => {
      state.selectedStepIndex = previewIndexes[Math.max(0, previewPosition - 1)];
      render();
    }, "secondary"),
    range,
    button(localeText("다음", "Next"), () => {
      state.selectedStepIndex = previewIndexes[Math.min(previewIndexes.length - 1, previewPosition + 1)];
      render();
    }, "secondary"),
  );
  container.append(scrubber);

  const details = document.createElement("details");
  details.className = "cti-details";
  details.append(el("summary", "", localeText("원시 텐서와 스텝 수치", "Raw tensors and step metrics")));
  const pre = el("pre", "cti-json");
  pre.textContent = JSON.stringify(step, null, 2);
  details.append(pre);
  container.append(details);
}

function renderRunSummary(container, run) {
  container.replaceChildren();
  container.append(el("div", "cti-zone-label", localeText("선택한 실행", "Selected Run")));
  if (!run) {
    container.append(el("div", "cti-empty", localeText("실행 기록을 선택하세요.", "Select a run.")));
    return;
  }
  const header = el("div", "cti-section-header");
  const identity = el("div", "cti-heading-group");
  identity.append(
    el("h3", "cti-section-title", runIdentity(run)),
    el(
      "span",
      "cti-section-kicker",
      `${run.workflowName && run.label ? `${run.label} · ` : ""}${run.stepCount || 0}${localeText("스텝", " steps")} · ${formatTime(run.startedAt || run.createdAt)}`,
    ),
  );
  header.append(identity);
  header.append(el("span", `cti-badge status-${run.status}`, statusLabel(run.status)));
  header.append(button(localeText("삭제", "Delete"), async () => {
    if (!window.confirm(localeText(`추적 실행 '${runIdentity(run)}'을 삭제할까요?`, `Delete trace run ${runIdentity(run)}?`))) return;
    await requestJson("/trace-inspector/runs/delete", {
      method: "POST",
      body: JSON.stringify({ runIds: [run.runId] }),
    });
    state.selectedRun = null;
    state.selectedRunId = null;
    await refreshRuns();
    if (state.selectedRunId) await loadRun(state.selectedRunId, true);
  }, "danger"));
  container.append(header);

  const grid = el("div", "cti-summary-strip");
  grid.append(
    metricCard(localeText("모드", "Mode"), modeLabel(run.options?.mode)),
    metricCard(localeText("시드", "Seed"), String(run.generationSettings?.seed ?? run.generationSettings?.noise_seed ?? "—")),
    metricCard("CFG", String(run.generationSettings?.cfg ?? "—")),
    metricCard(localeText("샘플러", "Sampler"), String(run.generationSettings?.sampler_name ?? run.segments?.[0]?.sampler ?? "—")),
  );
  container.append(grid);

  const noteRow = el("div", "cti-note-row");
  const note = document.createElement("textarea");
  note.placeholder = localeText("관찰 메모: 예) 12스텝부터 얼굴 비율 붕괴", "Observation note: e.g. face proportions break after step 12");
  note.maxLength = 8000;
  const category = createNoteCategorySelect();
  const step = createNoteStepSelect(run, displayedStepTarget(run));
  const submitNote = async () => {
    const text = note.value.trim();
    if (!text) {
      note.focus();
      return;
    }
    await performNoteAction(run.runId, () => requestJson(`/trace-inspector/runs/${run.runId}/note`, {
      method: "POST",
      body: JSON.stringify({ text, category: category.value, ...selectedNoteTarget(step, run) }),
    }), localeText("메모를 저장했습니다.", "Note saved."));
  };
  setupNoteTextarea(note, submitNote);
  const noteControls = el("div", "cti-note-controls");
  noteControls.append(category, step, button(localeText("메모 추가", "Add note"), submitNote));
  noteRow.append(note, noteControls);
  container.append(noteRow);
  renderNotes(container, run);

  const diagnostics = run.diagnostics || [];
  if (diagnostics.length) {
    const diagnosticWrap = document.createElement("details");
    diagnosticWrap.className = "cti-details cti-diagnostics";
    diagnosticWrap.append(el("summary", "", `${localeText("관측 신호", "Observed signals")} (${diagnostics.length})`));
    for (const item of diagnostics) {
      const card = el("div", `cti-diagnostic severity-${item.severity || "info"}`);
      card.append(
        el("strong", "", item.observation || item.id),
        el("p", "", item.hypothesis || ""),
      );
      if (item.experiments?.length) {
        const list = document.createElement("ul");
        for (const experiment of item.experiments) list.append(el("li", "", experiment));
        card.append(list);
      }
      diagnosticWrap.append(card);
    }
    container.append(diagnosticWrap);
  }

  const settings = document.createElement("details");
  settings.className = "cti-details";
  settings.append(el("summary", "", localeText("실행 설정, 모델 패치 및 오류", "Run settings, model patches, and errors")));
  const pre = el("pre", "cti-json");
  pre.textContent = JSON.stringify({
    generationSettings: run.generationSettings,
    modelSnapshot: run.modelSnapshot,
    errors: run.errors,
  }, null, 2);
  settings.append(pre);
  container.append(settings);
}

function displayInputValue(value) {
  if (Array.isArray(value?.link)) return `← ${localeText("노드", "node")} ${value.link[0]} · ${localeText("출력", "output")} ${value.link[1]}`;
  if (typeof value === "string") return value.length > 90 ? `${value.slice(0, 87)}…` : value;
  if (value == null || typeof value === "number" || typeof value === "boolean") return String(value ?? "—");
  return JSON.stringify(value);
}

function renderNodeTimeline(container, run) {
  container.replaceChildren();
  const header = el("div", "cti-section-header");
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", localeText("워크플로 경로", "Workflow Path")),
    el("span", "cti-section-kicker", localeText("저장된 그래프 순서입니다. 프런트엔드 이벤트가 연결된 실행만 실제 실행 시간이 표시됩니다.", "Captured graph order; live execution timing appears only when frontend events are attached.")),
  );
  const pathButton = button(
    localeText("캔버스에서 샘플링 경로 선택", "Select sampling path on canvas"),
    () => selectCanvasPath(run),
    "primary",
  );
  const capturedPath = samplingPathNodes(run);
  pathButton.disabled = !run || !capturedPath.length;
  pathButton.title = capturedPath.length
    ? localeText(
      `Trace Model의 입력과 출력에 연결된 노드 ${capturedPath.length}개를 선택합니다.`,
      `Select ${capturedPath.length} nodes connected to the Trace Model inputs and outputs.`,
    )
    : localeText(
      "이 실행에는 선택할 Trace Model 경로가 없습니다.",
      "This run has no Trace Model path to select.",
    );
  header.append(heading, pathButton);
  container.append(header);

  if (!run) {
    container.append(el("div", "cti-empty", localeText("기록된 워크플로 경로를 보려면 실행을 선택하세요.", "Select a run to inspect its captured workflow path.")));
    return;
  }

  const nodes = workflowNodes(run);
  if (!nodes.length) {
    container.append(el("div", "cti-empty", localeText("이 실행에는 저장된 프롬프트 그래프가 없습니다.", "This run has no captured prompt graph.")));
    return;
  }

  const path = el("div", "cti-node-path");
  for (const node of nodes) {
    const nodeId = String(node.id);
    const nodeButton = el("button", `cti-node cti-node-${nodeKind(node)} ${nodeId === state.selectedNodeId ? "selected" : ""}`);
    nodeButton.type = "button";
    nodeButton.addEventListener("click", () => {
      state.selectedNodeId = nodeId;
      state.canvasNotice = null;
      render();
    });
    nodeButton.append(
      el("span", "cti-node-id", `#${nodeId}`),
      el("strong", "cti-node-label", nodeLabel(node)),
      el("span", "cti-node-role", semanticRoleLabel(node.semantic?.role || node.group)),
    );
    path.append(nodeButton);
  }
  container.append(path);

  const selected = nodes.find((node) => String(node.id) === state.selectedNodeId) || nodes[0];
  state.selectedNodeId = String(selected.id);
  const nodeDetail = el("div", "cti-node-detail");
  const detailHeader = el("div", "cti-section-header");
  const detailTitle = el("div", "cti-heading-group");
  detailTitle.append(
    el("strong", "cti-node-detail-title", `${nodeLabel(selected)} · #${selected.id}`),
    el("span", "cti-section-kicker", selected.classType || localeText("알 수 없는 노드 유형", "Unknown node type")),
  );
  detailHeader.append(detailTitle, button(localeText("캔버스에서 위치 찾기", "Focus on canvas"), () => focusCanvasNode(selected.id, selected.classType, run), "primary"));
  nodeDetail.append(detailHeader);

  if (selected.semantic?.runtimeBehavior) {
    nodeDetail.append(el("p", "cti-node-behavior", selected.semantic.runtimeBehavior));
  }
  const inputs = Object.entries(selected.inputs || {});
  if (inputs.length) {
    const inputList = el("dl", "cti-node-inputs");
    for (const [name, value] of inputs) {
      inputList.append(el("dt", "", name), el("dd", "", displayInputValue(value)));
    }
    nodeDetail.append(inputList);
  }
  const probes = (run.probes || []).filter((probe) => String(probe.nodeId) === String(selected.id));
  if (probes.length) {
    const probeSummary = el("div", "cti-probe-summary");
    probeSummary.append(el("strong", "", `${localeText("기록된 출력", "Captured output")} · ${probes[0].label || probes[0].probeType}`));
    probeSummary.append(el("span", "", `${probes[0].summary?.shape?.join(" × ") || localeText("형태 알 수 없음", "shape unknown")} · ${probes[0].summary?.dtype || localeText("자료형 알 수 없음", "dtype unknown")}`));
    nodeDetail.append(probeSummary);
  }
  if (state.canvasNotice) nodeDetail.append(el("div", "cti-inline-notice", state.canvasNotice));
  container.append(nodeDetail);

  const events = run?.frontendEvents || [];
  const rows = events.filter((event) => ["node_start", "node_end", "executing", "execution_cached", "execution_error"].includes(event.type));
  if (!rows.length) {
    const notice = el("div", "cti-inline-notice muted", localeText("이 실행에는 실시간 실행 시간이 연결되지 않았습니다. 위 경로는 저장된 프롬프트 그래프 기준이며 정확한 실행 순서와 소요 시간은 아직 검증되지 않았습니다.", "Live timing was not attached to this run. The path above comes from the saved prompt graph; exact execution order and duration remain unverified."));
    container.append(notice);
    return;
  }
  const eventDetails = document.createElement("details");
  eventDetails.className = "cti-details";
  eventDetails.open = state.liveEventsExpanded;
  eventDetails.addEventListener("toggle", () => {
    state.liveEventsExpanded = eventDetails.open;
  });
  eventDetails.append(el("summary", "", `${localeText("실시간 실행 이벤트", "Live execution events")} (${rows.length})`));
  const table = el("table", "cti-table");
  const head = document.createElement("thead");
  head.innerHTML = isKoreanLocale()
    ? "<tr><th>시간</th><th>이벤트</th><th>노드</th><th>소요 시간</th></tr>"
    : "<tr><th>Time</th><th>Event</th><th>Node</th><th>Duration</th></tr>";
  table.append(head);
  const body = document.createElement("tbody");
  for (const event of rows.slice(-500)) {
    const tr = document.createElement("tr");
    const detail = event.detail || {};
    const node = detail.node ?? detail.nextNode ?? "—";
    const duration = typeof detail.durationMs === "number" ? `${detail.durationMs.toFixed(2)} ms` : "—";
    for (const value of [formatTime(event.timestamp), event.type, String(node), duration]) {
      tr.append(el("td", "", value));
    }
    body.append(tr);
  }
  table.append(body);
  eventDetails.append(table);
  container.append(eventDetails);
}

function runSelect(selectedId) {
  const select = document.createElement("select");
  select.className = "cti-select";
  for (const run of state.runs) {
    const option = document.createElement("option");
    option.value = run.runId;
    option.textContent = `${runIdentity(run)} · ${statusLabel(run.status)}`;
    option.selected = run.runId === selectedId;
    select.append(option);
  }
  return select;
}

async function drawPreviewDiff(leftUrl, rightUrl, host) {
  const load = (url) => new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = imageUrl(url);
  });
  try {
    const [left, right] = await Promise.all([load(leftUrl), load(rightUrl)]);
    if (!host.isConnected) return;
    const width = Math.max(left.naturalWidth, right.naturalWidth);
    const height = Math.max(left.naturalHeight, right.naturalHeight);
    const source = document.createElement("canvas");
    const target = document.createElement("canvas");
    const diff = document.createElement("canvas");
    for (const canvas of [source, target, diff]) {
      canvas.width = width;
      canvas.height = height;
    }
    source.getContext("2d").drawImage(left, 0, 0, width, height);
    target.getContext("2d").drawImage(right, 0, 0, width, height);
    const leftPixels = source.getContext("2d").getImageData(0, 0, width, height);
    const rightPixels = target.getContext("2d").getImageData(0, 0, width, height);
    const output = diff.getContext("2d").createImageData(width, height);
    let total = 0;
    for (let index = 0; index < output.data.length; index += 4) {
      const red = Math.abs(leftPixels.data[index] - rightPixels.data[index]);
      const green = Math.abs(leftPixels.data[index + 1] - rightPixels.data[index + 1]);
      const blue = Math.abs(leftPixels.data[index + 2] - rightPixels.data[index + 2]);
      const magnitude = Math.min(255, Math.max(red, green, blue) * 4);
      output.data[index] = magnitude;
      output.data[index + 1] = Math.round(magnitude * 0.42);
      output.data[index + 2] = Math.round(magnitude * 0.12);
      output.data[index + 3] = 255;
      total += red + green + blue;
    }
    diff.getContext("2d").putImageData(output, 0, 0);
    diff.className = "cti-diff-canvas";
    const mean = total / (width * height * 3 * 255);
    host.replaceChildren(diff, el("span", "cti-diff-value", `${localeText("미리보기 평균 픽셀 차이", "Mean preview pixel difference")} · ${formatNumber(mean, 6)}`));
  } catch (error) {
    host.replaceChildren(el("span", "cti-inline-notice", `${localeText("미리보기 차이를 계산할 수 없음", "Preview diff unavailable")}: ${error.message || error}`));
  }
}

function renderCompare(container) {
  container.replaceChildren();
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", localeText("실행 비교", "Compare Runs")),
    el("span", "cti-section-kicker", localeText("시각 A/B · 기록된 노이즈 제거 프레임을 맞춰 픽셀 차이를 확인합니다.", "Visual A/B · align captured denoise frames and inspect their pixel difference.")),
  );
  container.append(heading);
  if (state.runs.length < 2) {
    const empty = el("div", "cti-empty cti-compare-empty");
    empty.append(
      el("strong", "", localeText("두 번째 추적 실행이 필요합니다.", "A second traced run is required.")),
      el("span", "", localeText("같은 모델·입력·시드·샘플러·스텝·CFG로 실행하면 시각 비교를 사용할 수 있습니다.", "Use the same model, inputs, seed, sampler, steps, and CFG to unlock visual comparison.")),
      el("span", "cti-empty-footnote", localeText("추적 끄기 출력은 Run으로 저장되지 않으므로 최종 출력 동일성은 이 패널 밖에서 별도로 검증합니다.", "Trace Off output is not stored as a run, so final-output equality is still verified outside this panel.")),
    );
    container.append(empty);
    return;
  }
  const controls = el("div", "cti-compare-controls");
  const left = runSelect(state.compare?.left?.runId || state.runs[1]?.runId);
  const right = runSelect(state.compare?.right?.runId || state.runs[0]?.runId);
  controls.append(left, el("span", "", localeText("대", "vs")), right, button(localeText("비교", "Compare"), async () => {
    state.compare = await requestJson(`/trace-inspector/compare?left=${encodeURIComponent(left.value)}&right=${encodeURIComponent(right.value)}`);
    state.compareStepIndex = 0;
    render();
  }));
  container.append(controls);

  if (!state.compare) return;
  const reportActions = el("div", "cti-compare-controls");
  if (state.compare.reportFiles) {
    const reportBase = `/trace-inspector/runs/${encodeURIComponent(state.compare.left.runId)}/report/`;
    reportActions.append(
      button("A/B HTML", () => window.open(apiUrl(`${reportBase}${encodeURIComponent(state.compare.reportFiles.html)}`), "_blank")),
      button(localeText("A/B 마크다운", "A/B Markdown"), () => window.open(apiUrl(`${reportBase}${encodeURIComponent(state.compare.reportFiles.markdown)}`), "_blank")),
    );
  } else {
    reportActions.append(button(localeText("A/B 보고서 만들기", "Build A/B reports"), async () => {
      const result = await requestJson("/trace-inspector/compare/report", {
        method: "POST",
        body: JSON.stringify({ left: state.compare.left.runId, right: state.compare.right.runId }),
      });
      state.compare = { ...(result.comparison || state.compare), reportFiles: result.reportFiles };
      render();
    }));
  }
  container.append(reportActions);

  const workflow = state.compare.workflow || {};
  const runtime = state.compare.runtime || {};
  const relation = el("div", "cti-control-compare");
  relation.append(
    el("strong", "", `${localeText("워크플로", "Workflow")} ${workflow.hashMatch ? localeText("완전 일치", "exact match") : localeText("다름", "different")}`),
    el("span", "", `${localeText("노드", "Nodes")} A ${workflow.leftNodeCount ?? "—"} · B ${workflow.rightNodeCount ?? "—"}`),
    el("span", "", `${localeText("프롬프트", "Prompt")} A ${state.compare.left?.promptId || localeText("이전 형식 실행", "legacy run")}`),
    el("span", "", `${localeText("프롬프트", "Prompt")} B ${state.compare.right?.promptId || localeText("이전 형식 실행", "legacy run")}`),
    el("span", "", `${localeText("샘플러", "Sampler")} A ${runtime.left?.requestedSampler || "—"} → ${runtime.left?.actualSampler || "—"}`),
    el("span", "", `${localeText("샘플러", "Sampler")} B ${runtime.right?.requestedSampler || "—"} → ${runtime.right?.actualSampler || "—"}`),
    el("span", "cti-empty-footnote", state.compare.disclaimer || localeText("관측된 차이는 근거이며 인과 비율이 아닙니다.", "Observed differences are evidence, not causal percentages.")),
  );
  container.append(relation);

  const pairs = state.compare.stepPairs || [];
  if (pairs.length) {
    state.compareStepIndex = Math.min(state.compareStepIndex, pairs.length - 1);
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = String(pairs.length - 1);
    slider.value = String(state.compareStepIndex);
    slider.addEventListener("input", () => { state.compareStepIndex = Number(slider.value); render(); });
    container.append(slider);
    const pair = pairs[state.compareStepIndex];
    const images = el("div", "cti-compare-images");
    const previewImages = [];
    for (const [side, value] of [["A", pair.left], ["B", pair.right]]) {
      const card = el("div", "cti-compare-card");
      card.append(el("strong", "", `${side} · ${localeText("스텝", "step")} ${(value.step ?? 0) + 1}`));
      if (value.previewUrl) {
        const img = document.createElement("img");
        img.src = imageUrl(value.previewUrl);
        card.append(img);
        previewImages.push(value.previewUrl);
      }
      const compact = el("div", "cti-compare-metrics");
      compact.append(
        el("span", "", `σ ${formatNumber(value.sigma, 3)}`),
        el("span", "", `${localeText("시각", "visual")} Δ ${formatNumber(value.previewChange, 4)}`),
        el("span", "", `x0 μ ${formatNumber(value.x0?.mean, 4)}`),
        el("span", "", `CFG Δ ${formatNumber(value.cfg?.deltaMeanAbs, 4)}`),
        el("span", "", `${localeText("제어", "Control")} ${value.control?.active ? formatNumber(value.control?.weightedMeanAbs, 4) : localeText("비활성", "Inactive")}`),
      );
      card.append(compact);
      images.append(card);
    }
    container.append(images);
    const leftControlRaw = pair.left?.control?.weightedMeanAbs;
    const rightControlRaw = pair.right?.control?.weightedMeanAbs;
    const leftControl = pair.left?.control?.active && typeof leftControlRaw === "number" && Number.isFinite(leftControlRaw)
      ? leftControlRaw
      : null;
    const rightControl = pair.right?.control?.active && typeof rightControlRaw === "number" && Number.isFinite(rightControlRaw)
      ? rightControlRaw
      : null;
    const controlSummary = el("div", "cti-control-compare");
    const x0MeanDifference = pair.difference?.x0MeanAbsolute;
    controlSummary.append(
      el("strong", "", localeText("관측된 ControlNet 잔차", "Observed ControlNet residual")),
      el("span", "", `A ${pair.left?.control?.active ? formatNumber(leftControl, 4) : localeText("비활성", "Inactive")} · B ${pair.right?.control?.active ? formatNumber(rightControl, 4) : localeText("비활성", "Inactive")}`),
      el("span", "", `x0 ${localeText("평균", "mean")} |A-B| ${formatNumber(x0MeanDifference, 6)}`),
      el(
        "span",
        "cti-empty-footnote",
        leftControl != null && rightControl != null
          ? localeText(`잔차 절댓값 차이는 ${formatNumber(Math.abs(leftControl - rightControl), 4)}입니다. 이는 관측 신호이며 인과 비율이 아닙니다.`, `Absolute residual difference ${formatNumber(Math.abs(leftControl - rightControl), 4)}. This is an observed signal, not a causal percentage.`)
          : localeText("한쪽에 수치 잔차가 없습니다. 양쪽 모두 advanced 모드와 텐서 통계 저장을 켜고 실행해야 크기를 비교할 수 있습니다.", "One side has no numeric residual. Use Advanced with persist_tensor_stats enabled for both sides to compare magnitudes."),
      ),
    );
    container.append(controlSummary);
    if (previewImages.length === 2) {
      const diffHost = el("div", "cti-diff-host", localeText("디코딩된 x0 미리보기 차이를 계산하는 중…", "Computing decoded x0 preview difference…"));
      container.append(diffHost);
      drawPreviewDiff(previewImages[0], previewImages[1], diffHost);
    }
  }

  const diff = document.createElement("details");
  diff.className = "cti-details";
  diff.open = true;
  diff.append(el("summary", "", localeText("변경된 설정", "Changed settings")));
  diff.append(el("pre", "cti-json", JSON.stringify(state.compare.settingsDiff || {}, null, 2)));
  container.append(diff);
}

function promptRoleLabel(role) {
  return ({
    positive: localeText("긍정", "Positive"),
    negative: localeText("부정", "Negative"),
    unknown: localeText("역할 미확인", "Role unknown"),
  })[role] || role;
}

function encoderLabel(name) {
  return ({
    l: "CLIP-L",
    g: "CLIP-G",
    clip: "CLIP",
  })[name] || String(name || "CLIP").toUpperCase();
}

function tokenKey(callIndex, lane, chunkIndex, tokenIndex) {
  return `${callIndex}:${lane}:${chunkIndex}:${tokenIndex}`;
}

function tokenChipLabel(token) {
  if (token.special === "start") return "BOS";
  if (token.special === "end") return "EOS";
  if (token.special === "padding") return "PAD";
  if (token.special === "embedding") return localeText("임베딩", "Embedding");
  const decoded = String(token.decoded || "").replaceAll("\n", "↵").replaceAll("\t", "⇥");
  if (decoded) return decoded.replace(/^ +/, (spaces) => "␠".repeat(spaces.length));
  return String(token.piece || token.tokenId || "?");
}

function renderPromptTokens(container, run) {
  container.replaceChildren();
  const header = el("div", "cti-section-header");
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", localeText("텍스트 프롬프트와 토큰", "Text Prompt & Tokens")),
    el(
      "span",
      "cti-section-kicker",
      localeText(
        "원문이 실제 텍스트 인코더 토큰으로 나뉜 결과",
        "How the original text was split by the actual text encoder",
      ),
    ),
  );
  header.append(heading);
  container.append(header);

  if (!run) {
    container.append(el("div", "cti-empty", localeText("실행을 선택하면 프롬프트 토큰을 볼 수 있습니다.", "Select a run to inspect prompt tokens.")));
    return;
  }

  const capture = run.promptTokenization;
  if (!capture) {
    const empty = el("div", "cti-empty");
    empty.append(
      el("strong", "", localeText("이 실행에는 토큰 기록이 없습니다.", "This run has no token capture.")),
      el("span", "", localeText("기능 추가 전에 저장된 실행입니다. 새 실행에서 기록할 수 있습니다.", "It was saved before token capture was added. A new run can record it.")),
    );
    container.append(empty);
    return;
  }

  const prompts = capture.prompts || [];
  if (!prompts.length) {
    const empty = el("div", "cti-empty");
    if (capture.source === "traced_clip") {
      empty.append(
        el("strong", "", localeText("아직 실제 CLIP 호출이 기록되지 않았습니다.", "No actual CLIP call has been captured yet.")),
        el("span", "", localeText("Sampling Trace CLIP의 CLIP 출력을 긍정·부정 Text Encode에 연결하고 prompt_trace를 Sampling Trace Model에 연결한 뒤 실행하세요.", "Connect Sampling Trace CLIP to both Positive and Negative Text Encode nodes, connect prompt_trace to Sampling Trace Model, then run the workflow.")),
      );
    } else {
      empty.append(
        el("strong", "", localeText("지원하는 표준 프롬프트 노드를 찾지 못했습니다.", "No supported standard prompt node was found.")),
        el("span", "", localeText("Sampling Trace CLIP 통과 방식은 실제 tokenize 호출을 기준으로 커스텀 Text Encode도 기록할 수 있습니다.", "The Sampling Trace CLIP pass-through can capture custom Text Encode nodes from their actual tokenize calls.")),
      );
    }
    container.append(empty);
    return;
  }

  if (capture.status === "clip_not_connected") {
    container.append(el(
      "div",
      "cti-inline-notice",
      localeText(
        "원문만 찾았습니다. Checkpoint CLIP → Sampling Trace CLIP → 긍정·부정 Text Encode로 연결하고 prompt_trace를 Sampling Trace Model에 연결하면 실제 호출을 기록합니다.",
        "Prompt text was found, but actual calls were not captured. Connect Checkpoint CLIP → Sampling Trace CLIP → both Positive and Negative Text Encode nodes, then connect prompt_trace to Sampling Trace Model.",
      ),
    ));
  } else if (capture.status === "partial" || capture.status === "error") {
    container.append(el("div", "cti-inline-notice", localeText("일부 프롬프트의 토큰화에 실패했습니다. 아래 오류와 원문은 보존했습니다.", "Some prompts failed to tokenize. Their errors and source text are preserved below.")));
  }

  let selected = prompts.find((prompt) => String(prompt.nodeId) === String(state.selectedPromptNodeId));
  if (!selected) {
    selected = prompts[0];
    state.selectedPromptNodeId = String(selected.nodeId);
    state.selectedPromptCallIndex = 0;
    state.selectedTokenKey = null;
  }

  const tabs = el("div", "cti-prompt-tabs");
  for (const prompt of prompts) {
      const roles = (prompt.roles || []).map(promptRoleLabel).join("·");
      const firstCall = (prompt.calls || []).find((call) => !call.internal);
      const sourceText = firstCall?.text || Object.values(prompt.texts || {})[0] || "";
      const preview = String(sourceText).replaceAll("\n", " ").slice(0, 70) || localeText("(빈 프롬프트)", "(empty prompt)");
      const tab = button("", () => {
        state.selectedPromptNodeId = String(prompt.nodeId);
        state.selectedPromptCallIndex = 0;
        state.selectedTokenKey = null;
        render();
      }, `cti-prompt-tab ${String(prompt.nodeId) === String(selected.nodeId) ? "selected" : ""}`);
      tab.append(el("strong", "", `${roles} · #${prompt.nodeId}`), el("span", "", preview));
      tab.title = prompt.classType || "";
      tabs.append(tab);
  }
  container.append(tabs);

  const promptHead = el("div", "cti-prompt-head");
  const roles = el("div", "cti-prompt-roles");
  for (const role of selected.roles || ["unknown"]) roles.append(el("span", `cti-badge prompt-${role}`, promptRoleLabel(role)));
  promptHead.append(
    el("strong", "", `#${selected.nodeId} ${selected.classType}`),
    roles,
  );
  container.append(promptHead);

  const actualCalls = (selected.calls || []).filter((call) => !call.internal);
  let selectedCall = actualCalls.find((call) => Number(call.callIndex) === Number(state.selectedPromptCallIndex));
  if (!selectedCall && actualCalls.length) {
    selectedCall = actualCalls[0];
    state.selectedPromptCallIndex = Number(selectedCall.callIndex || 0);
    state.selectedTokenKey = null;
  }
  if (actualCalls.length > 1) {
    const callTabs = el("div", "cti-prompt-call-tabs");
    for (const call of actualCalls) {
      const callButton = button(
        call.sourceField || `${localeText("호출", "Call")} ${Number(call.callIndex || 0) + 1}`,
        () => {
          state.selectedPromptCallIndex = Number(call.callIndex || 0);
          state.selectedTokenKey = null;
          render();
        },
        `cti-prompt-call ${Number(call.callIndex) === Number(selectedCall?.callIndex) ? "selected" : ""}`,
      );
      callTabs.append(callButton);
    }
    container.append(callTabs);
  }

  const copies = el("div", "cti-prompt-copies");
  const displayTexts = selectedCall
    ? [[selectedCall.sourceField || "tokenize", selectedCall.text]]
    : Object.entries(selected.texts || {});
  for (const [source, text] of displayTexts) {
    const copy = el("div", "cti-prompt-copy");
    const label = source === "default" || source === "text"
      ? localeText("실제 프롬프트 원문", "Actual prompt source")
      : `${source} ${localeText("실제 원문", "actual source")}`;
    copy.append(el("span", "cti-zone-label", label), el("pre", "", text || localeText("(빈 프롬프트)", "(empty prompt)")));
    copies.append(copy);
  }
  container.append(copies);

  if (selected.error) container.append(el("div", "cti-inline-notice", selected.error));
  let encoders = selectedCall?.encoders || selected.encoders || [];
  if (selectedCall?.usedEncoders?.length) {
    encoders = encoders.filter((encoder) => selectedCall.usedEncoders.includes(String(encoder.name)));
  }
  if (!encoders.length) return;

  const lanes = el("div", "cti-token-lanes");
  const allTokens = [];
  for (const encoder of encoders) {
    const lane = el("article", "cti-token-lane");
    const laneHead = el("div", "cti-token-lane-head");
    laneHead.append(
      el("strong", "", encoderLabel(encoder.name)),
      el("span", "cti-section-kicker", localeText(
        `${encoder.chunkCount || 0}청크 · 내용 ${encoder.contentTokenCount || 0} · 패딩 ${encoder.paddingTokenCount || 0}`,
        `${encoder.chunkCount || 0} chunks · ${encoder.contentTokenCount || 0} content · ${encoder.paddingTokenCount || 0} padding`,
      )),
    );
    lane.append(laneHead);
    const contentTokens = el("div", "cti-token-chips");
    (encoder.chunks || []).forEach((chunk, chunkIndex) => {
      chunk.forEach((token) => {
        const key = tokenKey(selectedCall?.callIndex || 0, encoder.name, chunkIndex, token.index);
        const item = { encoder: encoder.name, chunkIndex, token, key };
        allTokens.push(item);
        if (["start", "end", "padding"].includes(token.special)) return;
        const chip = button(tokenChipLabel(token), () => {
          state.selectedTokenKey = key;
          render();
        }, `cti-token-chip ${state.selectedTokenKey === key ? "selected" : ""}`);
        chip.title = localeText(
          `토큰 ${token.tokenId ?? "임베딩"} · 가중치 ${formatNumber(token.weight, 3)} · 단어 ${token.wordId ?? "—"}`,
          `Token ${token.tokenId ?? "embedding"} · weight ${formatNumber(token.weight, 3)} · word ${token.wordId ?? "—"}`,
        );
        contentTokens.append(chip);
      });
    });
    if (!contentTokens.childElementCount) contentTokens.append(el("span", "cti-empty-footnote", localeText("내용 토큰이 없습니다.", "No content tokens.")));
    lane.append(contentTokens);
    lanes.append(lane);
  }
  container.append(lanes);

  let selectedToken = allTokens.find((item) => item.key === state.selectedTokenKey && !["start", "end", "padding"].includes(item.token.special));
  if (!selectedToken) {
    selectedToken = allTokens.find((item) => !["start", "end", "padding"].includes(item.token.special));
    state.selectedTokenKey = selectedToken?.key || null;
  }
  if (selectedToken) {
    const token = selectedToken.token;
    const detail = el("div", "cti-token-detail");
    detail.append(
      el("strong", "", localeText("선택 토큰", "Selected token")),
      el("span", "", `${encoderLabel(selectedToken.encoder)} · ${localeText("청크", "chunk")} ${selectedToken.chunkIndex + 1} · #${token.index + 1}`),
      el("span", "", `ID ${token.tokenId ?? localeText("임베딩", "embedding")} · ${localeText("가중치", "weight")} ${formatNumber(token.weight, 4)} · ${localeText("단어 묶음", "word group")} ${token.wordId ?? "—"}`),
      el("code", "", `${tokenChipLabel(token)}  ${token.piece || ""}`.trim()),
    );
    container.append(detail);
  }

  const raw = document.createElement("details");
  raw.className = "cti-details";
  raw.append(
    el("summary", "", localeText("특수·패딩 포함 원시 토큰", "Raw tokens including special and padding")),
    el("pre", "cti-json", JSON.stringify(selected.calls || encoders, null, 2)),
  );
  container.append(raw);
  container.append(el(
    "p",
    "cti-empty-footnote cti-prompt-boundary",
    localeText(
      "표시값은 토큰 분할과 입력 가중치입니다. 관심도, 품질 기여율 또는 인과 비율을 뜻하지 않습니다.",
      "These values show token splitting and input weights, not attention, quality contribution, or causal percentages.",
    ),
  ));
}

function render() {
  if (!state.root) return;
  const executionNotice = state.root.querySelector("[data-role='execution-notice']");
  const runList = state.root.querySelector("[data-role='runs']");
  const summary = state.root.querySelector("[data-role='summary']");
  const viewer = state.root.querySelector("[data-role='viewer']");
  const promptTokens = state.root.querySelector("[data-role='prompt-tokens']");
  const timeline = state.root.querySelector("[data-role='timeline']");
  const compare = state.root.querySelector("[data-role='compare']");
  if (executionNotice) {
    executionNotice.replaceChildren();
    if (state.executionNotice) executionNotice.append(el("span", "", state.executionNotice));
  }
  if (runList) renderRunList(runList);
  if (summary) renderRunSummary(summary, state.selectedRun);
  if (viewer) renderStepViewer(viewer, state.selectedRun);
  if (promptTokens) renderPromptTokens(promptTokens, state.selectedRun);
  if (timeline) renderNodeTimeline(timeline, state.selectedRun);
  if (compare) renderCompare(compare);
  renderLiveStatus();
}

function createPanel(container) {
  injectStyles();
  state.panelContainer = container;
  container.classList.add("cti-panel-host");
  state.root = el("div", "cti-root");
  state.root.append(createToolbar());
  const executionNotice = el("div", "cti-execution-notice");
  executionNotice.dataset.role = "execution-notice";
  state.root.append(executionNotice);

  const body = el("div", "cti-body");
  const runList = el("aside", "cti-runs");
  runList.dataset.role = "runs";

  const center = el("main", "cti-center");
  const viewer = el("section", "cti-section cti-viewer-section");
  viewer.dataset.role = "viewer";
  const promptTokens = el("section", "cti-section cti-prompt-section");
  promptTokens.dataset.role = "prompt-tokens";
  const timeline = el("section", "cti-section cti-path-section");
  timeline.dataset.role = "timeline";
  center.append(viewer, promptTokens, timeline);

  const right = el("aside", "cti-right");
  const summary = el("section", "cti-section");
  summary.dataset.role = "summary";
  const compare = el("section", "cti-section");
  compare.dataset.role = "compare";
  right.append(summary, compare);

  const rightSplitter = createRightPanelSplitter();
  body.append(runList, center, rightSplitter, right);
  state.root.append(body);
  container.replaceChildren(state.root);
  state.rightPanelWidth = readRightPanelWidthPreference();
  applyRightPanelWidth(state.rightPanelWidth);
  state.resizeHandler = () => applyRightPanelWidth(state.rightPanelWidth);
  window.addEventListener("resize", state.resizeHandler);
  state.keydownHandler = (event) => {
    if (event.key === "Escape" && state.expanded) setExpanded(false);
  };
  document.addEventListener("keydown", state.keydownHandler);
  setExpanded(readExpandedPreference(), false);
  refreshRuns().then(() => {
    if (state.selectedRunId) loadRun(state.selectedRunId, true);
  });

}

function destroyPanel() {
  if (state.refreshTimer) {
    clearTimeout(state.refreshTimer);
    state.refreshTimer = null;
  }
  if (state.keydownHandler) {
    document.removeEventListener("keydown", state.keydownHandler);
    state.keydownHandler = null;
  }
  if (state.resizeHandler) {
    window.removeEventListener("resize", state.resizeHandler);
    state.resizeHandler = null;
  }
  state.root?.remove();
  state.panelContainer?.classList.remove("cti-panel-host");
  state.root = null;
  state.panelContainer = null;
  state.expanded = false;
}

app.registerExtension({
  name: EXTENSION_NAME,
  setup() {
    injectStyles();
    installEventListeners();
  },
  bottomPanelTabs: [
    {
      id: "comfy-trace-inspector",
      title: localeText("샘플링 추적 분석기", "Sampling Trace Inspector"),
      type: "custom",
      targetPanel: "terminal",
      render: createPanel,
      destroy: destroyPanel,
    },
  ],
});
