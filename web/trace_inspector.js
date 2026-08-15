import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION_NAME = "local-rnd.ComfyUI.TraceInspector";
const EVENT_PREFIX = "trace_inspector.";
const EXPANDED_STORAGE_KEY = "comfy-trace-inspector.expanded";
const NOTE_CATEGORIES = ["observation", "hypothesis", "decision", "issue"];

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
      console.warn(`[SamplingTrace Inspector] Failed to persist frontend events for ${runId}`, error);
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
    enqueueEvent("execution_start", event.detail);
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
    closeActiveNode(null);
    await flushEvents(type, detail);
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
    success: "Complete",
    running: "Capturing",
    sampling_complete: "Trace captured",
    error: "Failed",
    interrupted: "Interrupted",
  })[status] || status || "Unknown";
}

function nodeLabel(node) {
  const names = {
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
  return names[node?.classType] || node?.classType || `Node ${node?.id ?? "—"}`;
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

function matchingCanvasNodes(run) {
  const graph = app.graph;
  const capturedNodes = run?.promptAnalysis?.nodes || [];
  if (!capturedNodes.length) return null;
  const liveNodes = capturedNodes.map((captured) => {
    const live = graph?.getNodeById?.(Number(captured.id)) || graph?.getNodeById?.(String(captured.id));
    const liveType = live?.type || live?.constructor?.comfyClass || null;
    return liveType === captured.classType ? live : null;
  });
  return liveNodes.every(Boolean) ? liveNodes : null;
}

function focusCanvasNode(nodeId, expectedClassType = null, run = null) {
  const graph = app.graph;
  const canvas = app.canvas;
  const node = graph?.getNodeById?.(Number(nodeId)) || graph?.getNodeById?.(String(nodeId));
  const actualClassType = node?.type || node?.constructor?.comfyClass || null;
  const liveNodes = matchingCanvasNodes(run);
  if (!node || !canvas || !liveNodes || (expectedClassType && actualClassType !== expectedClassType)) {
    state.canvasNotice = `Node #${nodeId} (${expectedClassType || "unknown type"}) does not match the current canvas. Load this run's workflow before focusing it.`;
    render();
    return;
  }

  if (typeof canvas.select === "function") {
    canvas.selectedItems?.clear?.();
    canvas.select(node);
  } else if (typeof canvas.selectNode === "function") {
    canvas.selectNode(node);
  } else if (typeof canvas.selectItems === "function") {
    canvas.selectItems([node]);
  }
  canvas.centerOnNode?.(node);
  canvas.setDirty?.(true, true);
  state.canvasNotice = `Focused node #${nodeId} on the canvas.`;
  render();
}

function selectCanvasPath(run) {
  const canvas = app.canvas;
  const liveNodes = matchingCanvasNodes(run);
  if (!canvas || !liveNodes) {
    state.canvasNotice = "The captured graph does not match the current canvas. Load this run's workflow before selecting its path.";
    render();
    return;
  }
  if (typeof canvas.selectItems === "function") {
    canvas.selectItems(liveNodes);
  } else if (typeof canvas.selectNodes === "function") {
    canvas.selectNodes(liveNodes);
  } else {
    canvas.deselectAllNodes?.();
    for (const node of liveNodes) canvas.selectNode?.(node, true);
  }
  const traceNode = liveNodes.find((node) => String(node.id) === String(run.nodeId));
  if (traceNode) canvas.centerOnNode?.(traceNode);
  canvas.setDirty?.(true, true);
  state.canvasNotice = `Selected ${liveNodes.length} captured graph nodes on the canvas.`;
  render();
}

function imageUrl(path) {
  return path ? apiUrl(path) : "";
}

function setPanelError(error) {
  console.error("[SamplingTrace Inspector]", error);
  const status = state.root?.querySelector("[data-role='status']");
  if (status) status.textContent = `Error: ${error.message || error}`;
}

function renderLiveStatus(progress = null) {
  const status = state.root?.querySelector("[data-role='status']");
  if (!status) return;
  const parts = [];
  if (state.currentPromptId) parts.push(`Prompt ${state.currentPromptId.slice(0, 8)}`);
  if (state.activeNode) parts.push(`Node ${state.activeNode}`);
  if (progress?.value != null && progress?.max != null) parts.push(`${progress.value}/${progress.max}`);
  status.textContent = parts.join(" · ") || "Idle";
}

function readExpandedPreference() {
  try {
    const stored = window.localStorage.getItem(EXPANDED_STORAGE_KEY);
    return stored == null ? true : stored === "true";
  } catch (_error) {
    return true;
  }
}

function updateExpandedButton() {
  const toggle = state.root?.querySelector("[data-role='expanded-toggle']");
  if (!toggle) return;
  toggle.textContent = state.expanded ? "Back to panel" : "Expand";
  toggle.title = state.expanded
    ? "Return SamplingTrace Inspector to the ComfyUI bottom panel (Esc)"
    : "Open SamplingTrace Inspector in a large workspace";
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
  brand.append(el("strong", "cti-title", "SamplingTrace Inspector"), el("span", "cti-brand-subtitle", "Sampling analyzer"));
  bar.append(
    brand,
    button("Refresh", async () => {
      await refreshRuns();
      if (state.selectedRunId) await loadRun(state.selectedRunId, false);
    }),
    button("Latest", async () => {
      if (state.runs[0]) await loadRun(state.runs[0].runId, true);
    }),
  );
  const status = el("span", "cti-status", "Idle");
  status.dataset.role = "status";
  const expandedToggle = button("Expand", () => setExpanded(!state.expanded));
  expandedToggle.dataset.role = "expanded-toggle";
  bar.append(status, expandedToggle);
  return bar;
}

function renderRunList(container) {
  container.replaceChildren();
  container.append(el("h3", "cti-section-title", `Runs (${state.runs.length})`));
  const list = el("div", "cti-run-list");
  for (const run of state.runs) {
    const row = el("button", `cti-run-row ${run.runId === state.selectedRunId ? "selected" : ""}`);
    row.addEventListener("click", () => loadRun(run.runId, true));
    row.append(
      el("span", "cti-run-label", run.label || run.runId.slice(0, 8)),
      el("span", `cti-badge status-${run.status}`, statusLabel(run.status)),
      el("span", "cti-run-meta", `${run.stepCount || 0} steps · ${formatTime(run.startedAt || run.createdAt)}`),
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
  for (const value of NOTE_CATEGORIES) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = value === selected;
    select.append(option);
  }
  return select;
}

async function performNoteAction(runId, action, successMessage) {
  try {
    await action();
    state.noteNotice = { runId, type: "success", text: successMessage };
    await loadRun(runId, false);
  } catch (error) {
    state.noteNotice = { runId, type: "error", text: `Note error: ${error.message || error}` };
    render();
  }
}

function renderNotes(container, run) {
  const notes = (run.probes || []).filter((probe) => probe?.probeType === "note").reverse();
  const section = el("div", "cti-notes");
  const header = el("div", "cti-notes-header");
  header.append(
    el("strong", "", `Notes (${notes.length})`),
    el("span", "cti-section-kicker", "Saved with this run"),
  );
  section.append(header);

  if (state.noteNotice?.runId === run.runId) {
    section.append(el("div", `cti-note-feedback ${state.noteNotice.type}`, state.noteNotice.text));
  }

  if (!notes.length) {
    section.append(el("div", "cti-empty cti-note-empty", "No notes yet. Add an observation, hypothesis, decision, or issue above."));
    container.append(section);
    return;
  }

  const list = el("div", "cti-note-list");
  for (const note of notes) {
    const card = el("article", "cti-note-card");
    const meta = el("div", "cti-note-meta");
    meta.append(
      el("span", "cti-badge", note.label || "observation"),
      el("span", "cti-note-time", `${note.updatedAt ? "Edited · " : ""}${formatTime(note.updatedAt || note.timestamp)}`),
    );
    const copy = el("p", "cti-note-text", note.summary?.text || "");
    card.append(meta, copy);

    if (note.noteId) {
      const actions = el("div", "cti-note-actions");
      actions.append(
        button("Edit", () => {
          const editor = el("div", "cti-note-editor");
          const textarea = document.createElement("textarea");
          textarea.value = note.summary?.text || "";
          textarea.maxLength = 8000;
          const category = createNoteCategorySelect(note.label || "observation");
          const editorActions = el("div", "cti-note-actions");
          editorActions.append(
            button("Save", async () => {
              const text = textarea.value.trim();
              if (!text) {
                textarea.focus();
                return;
              }
              await performNoteAction(run.runId, () => requestJson(
                `/trace-inspector/runs/${run.runId}/notes/${encodeURIComponent(note.noteId)}`,
                {
                  method: "PATCH",
                  body: JSON.stringify({ text, category: category.value }),
                },
              ), "Note updated.");
            }, "primary"),
            button("Cancel", () => render(), "secondary"),
          );
          editor.append(textarea, category, editorActions);
          card.replaceChildren(meta, editor);
          textarea.focus();
        }, "secondary"),
        button("Delete", async () => {
          if (!window.confirm("Delete this note? This cannot be undone.")) return;
          await performNoteAction(run.runId, () => requestJson(
            `/trace-inspector/runs/${run.runId}/notes/${encodeURIComponent(note.noteId)}`,
            { method: "DELETE" },
          ), "Note deleted.");
        }, "danger"),
      );
      card.append(actions);
    } else {
      card.append(el("div", "cti-inline-notice muted", "Legacy note: saved before note editing was available."));
    }
    list.append(card);
  }
  section.append(list);
  container.append(section);
}

function renderStepViewer(container, run) {
  container.replaceChildren();
  const steps = run?.steps || [];
  const header = el("div", "cti-section-header");
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", "Denoise Preview"),
    el("span", "cti-section-kicker", "Drag or click a frame to inspect how the image formed."),
  );
  header.append(heading);

  if (run?.reportFiles?.html) {
    header.append(button("HTML Report", () => {
      window.open(apiUrl(`/trace-inspector/runs/${run.runId}/report/report.html`), "_blank");
    }));
  }
  if (run?.reportFiles?.markdown) {
    header.append(button("Markdown", () => {
      window.open(apiUrl(`/trace-inspector/runs/${run.runId}/report/report.md`), "_blank");
    }));
  }
  container.append(header);

  if (!steps.length) {
    container.append(el("div", "cti-empty", "No sampling frames were captured. Connect Trace Model immediately before KSampler, then run the workflow."));
    return;
  }

  state.selectedStepIndex = Math.max(0, Math.min(state.selectedStepIndex, steps.length - 1));
  const step = steps[state.selectedStepIndex];
  const visual = el("div", "cti-visual-workspace");
  const imageWrap = el("div", "cti-preview-stage");
  if (step.previewUrl) {
    const img = document.createElement("img");
    img.className = "cti-preview";
    img.src = imageUrl(step.previewUrl);
    img.alt = `Denoise step ${step.step + 1} of ${step.totalSteps}`;
    imageWrap.append(img);
  } else {
    imageWrap.append(el("div", "cti-empty", "This step has no decoded preview."));
  }
  const overlay = el("div", "cti-preview-overlay");
  overlay.append(
    el("strong", "cti-preview-step", `STEP ${step.step + 1} / ${step.totalSteps}`),
    el("span", "cti-preview-meta", `σ ${formatNumber(step.sigma, 3)} · Δ ${formatNumber(step.previewChange, 4)}`),
  );
  imageWrap.append(overlay);

  const insight = el("aside", "cti-step-insight");
  insight.append(el("span", "cti-insight-label", "What changed at this step"));
  const changeValue = step.previewChange;
  const changeText = changeValue == null
    ? "Baseline frame — visual change starts from the next captured step."
    : changeValue >= 0.03
      ? "Large visual movement. Composition and major shapes are still settling."
      : changeValue >= 0.01
        ? "Moderate visual movement. Structure is stabilizing."
        : "Small visual movement. The result is converging into fine detail.";
  insight.append(el("p", "cti-insight-copy", changeText));
  const metrics = el("div", "cti-metrics");
  metrics.append(
    metricCard("Visual change", formatNumber(step.previewChange), "Normalized pixel change from the previous captured preview"),
    metricCard("CFG influence", formatNumber(step.cfg?.deltaMeanAbs), "Mean absolute conditional-unconditional delta"),
    metricCard("Predicted x0", `${formatNumber(step.x0?.mean, 3)} ± ${formatNumber(step.x0?.std, 3)}`),
    metricCard("Control", step.control?.active ? formatNumber(step.control?.weightedMeanAbs) : "Inactive", "Control residual mean absolute value"),
  );
  insight.append(metrics);
  visual.append(imageWrap, insight);
  container.append(visual);

  const filmstrip = el("div", "cti-filmstrip");
  for (let index = 0; index < steps.length; index += 1) {
    const frame = steps[index];
    const frameButton = el("button", `cti-frame ${index === state.selectedStepIndex ? "selected" : ""}`);
    frameButton.type = "button";
    frameButton.title = `Step ${frame.step + 1} · sigma ${formatNumber(frame.sigma, 3)} · change ${formatNumber(frame.previewChange, 4)}`;
    frameButton.addEventListener("click", () => {
      state.selectedStepIndex = index;
      render();
    });
    if (frame.previewUrl) {
      const thumb = document.createElement("img");
      thumb.src = imageUrl(frame.previewUrl);
      thumb.alt = "";
      frameButton.append(thumb);
    }
    frameButton.append(el("span", "cti-frame-index", String(frame.step + 1)));
    filmstrip.append(frameButton);
  }
  container.append(filmstrip);

  const scrubber = el("div", "cti-scrubber");
  const range = document.createElement("input");
  range.type = "range";
  range.min = "0";
  range.max = String(steps.length - 1);
  range.value = String(state.selectedStepIndex);
  range.setAttribute("aria-label", "Denoise step");
  range.addEventListener("input", () => {
    state.selectedStepIndex = Number(range.value);
    render();
  });
  scrubber.append(
    button("Previous", () => { state.selectedStepIndex = Math.max(0, state.selectedStepIndex - 1); render(); }, "secondary"),
    range,
    button("Next", () => { state.selectedStepIndex = Math.min(steps.length - 1, state.selectedStepIndex + 1); render(); }, "secondary"),
  );
  container.append(scrubber);

  const details = document.createElement("details");
  details.className = "cti-details";
  details.append(el("summary", "", "Raw tensors and step metrics"));
  const pre = el("pre", "cti-json");
  pre.textContent = JSON.stringify(step, null, 2);
  details.append(pre);
  container.append(details);
}

function renderRunSummary(container, run) {
  container.replaceChildren();
  if (!run) {
    container.append(el("div", "cti-empty", "Run을 선택합니다."));
    return;
  }
  const header = el("div", "cti-section-header");
  const identity = el("div", "cti-heading-group");
  identity.append(
    el("h3", "cti-section-title", run.label || run.runId),
    el("span", "cti-section-kicker", `${run.stepCount || 0} steps · ${formatTime(run.startedAt || run.createdAt)}`),
  );
  header.append(identity);
  header.append(el("span", `cti-badge status-${run.status}`, statusLabel(run.status)));
  header.append(button("Delete", async () => {
    if (!window.confirm(`Delete trace run ${run.label || run.runId}?`)) return;
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
    metricCard("Mode", run.options?.mode || "—"),
    metricCard("Seed", String(run.generationSettings?.seed ?? run.generationSettings?.noise_seed ?? "—")),
    metricCard("CFG", String(run.generationSettings?.cfg ?? "—")),
    metricCard("Sampler", String(run.generationSettings?.sampler_name ?? run.segments?.[0]?.sampler ?? "—")),
  );
  container.append(grid);

  const noteRow = el("div", "cti-note-row");
  const note = document.createElement("input");
  note.placeholder = "관찰 메모: 예) step 12부터 얼굴 비율 붕괴";
  note.maxLength = 8000;
  const category = createNoteCategorySelect();
  const submitNote = async () => {
    const text = note.value.trim();
    if (!text) {
      note.focus();
      return;
    }
    await performNoteAction(run.runId, () => requestJson(`/trace-inspector/runs/${run.runId}/note`, {
      method: "POST",
      body: JSON.stringify({ text, category: category.value }),
    }), "Note saved.");
  };
  note.addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitNote();
  });
  noteRow.append(note, category, button("Add note", submitNote));
  container.append(noteRow);
  renderNotes(container, run);

  const diagnostics = run.diagnostics || [];
  if (diagnostics.length) {
    const diagnosticWrap = document.createElement("details");
    diagnosticWrap.className = "cti-details cti-diagnostics";
    diagnosticWrap.append(el("summary", "", `Observed signals (${diagnostics.length})`));
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
  settings.append(el("summary", "", "Run settings, model patches, and errors"));
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
  if (Array.isArray(value?.link)) return `← node ${value.link[0]} · output ${value.link[1]}`;
  if (typeof value === "string") return value.length > 90 ? `${value.slice(0, 87)}…` : value;
  if (value == null || typeof value === "number" || typeof value === "boolean") return String(value ?? "—");
  return JSON.stringify(value);
}

function renderNodeTimeline(container, run) {
  container.replaceChildren();
  const header = el("div", "cti-section-header");
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", "Workflow Path"),
    el("span", "cti-section-kicker", "Captured graph order; live execution timing appears only when frontend events are attached."),
  );
  header.append(heading, button("Select path on canvas", () => selectCanvasPath(run), "primary"));
  container.append(header);

  if (!run) {
    container.append(el("div", "cti-empty", "Select a run to inspect its captured workflow path."));
    return;
  }

  const nodes = workflowNodes(run);
  if (!nodes.length) {
    container.append(el("div", "cti-empty", "This run has no captured prompt graph."));
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
      el("span", "cti-node-role", node.semantic?.role || node.group || "workflow"),
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
    el("span", "cti-section-kicker", selected.classType || "Unknown node type"),
  );
  detailHeader.append(detailTitle, button("Focus on canvas", () => focusCanvasNode(selected.id, selected.classType, run), "primary"));
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
    probeSummary.append(el("strong", "", `Captured output · ${probes[0].label || probes[0].probeType}`));
    probeSummary.append(el("span", "", `${probes[0].summary?.shape?.join(" × ") || "shape unknown"} · ${probes[0].summary?.dtype || "dtype unknown"}`));
    nodeDetail.append(probeSummary);
  }
  if (state.canvasNotice) nodeDetail.append(el("div", "cti-inline-notice", state.canvasNotice));
  container.append(nodeDetail);

  const events = run?.frontendEvents || [];
  const rows = events.filter((event) => ["node_start", "node_end", "executing", "execution_cached", "execution_error"].includes(event.type));
  if (!rows.length) {
    const notice = el("div", "cti-inline-notice muted", "Live timing was not attached to this run. The path above comes from the saved prompt graph; exact execution order and duration remain unverified.");
    container.append(notice);
    return;
  }
  const eventDetails = document.createElement("details");
  eventDetails.className = "cti-details";
  eventDetails.append(el("summary", "", `Live execution events (${rows.length})`));
  const table = el("table", "cti-table");
  const head = document.createElement("thead");
  head.innerHTML = "<tr><th>Time</th><th>Event</th><th>Node</th><th>Duration</th></tr>";
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
    option.textContent = `${run.label || run.runId.slice(0, 8)} · ${run.status}`;
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
    host.replaceChildren(diff, el("span", "cti-diff-value", `Mean preview pixel difference · ${formatNumber(mean, 6)}`));
  } catch (error) {
    host.replaceChildren(el("span", "cti-inline-notice", `Preview diff unavailable: ${error.message || error}`));
  }
}

function renderCompare(container) {
  container.replaceChildren();
  const heading = el("div", "cti-heading-group");
  heading.append(
    el("h3", "cti-section-title", "Visual A/B"),
    el("span", "cti-section-kicker", "Align captured denoise frames and inspect their pixel difference."),
  );
  container.append(heading);
  if (state.runs.length < 2) {
    const empty = el("div", "cti-empty cti-compare-empty");
    empty.append(
      el("strong", "", "A second traced run is required."),
      el("span", "", "Use the same model, inputs, seed, sampler, steps, and CFG to unlock visual comparison."),
      el("span", "cti-empty-footnote", "Trace Off output is not stored as a run, so final-output equality is still verified outside this panel."),
    );
    container.append(empty);
    return;
  }
  const controls = el("div", "cti-compare-controls");
  const left = runSelect(state.compare?.left?.runId || state.runs[1]?.runId);
  const right = runSelect(state.compare?.right?.runId || state.runs[0]?.runId);
  controls.append(left, el("span", "", "vs"), right, button("Compare", async () => {
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
      button("A/B Markdown", () => window.open(apiUrl(`${reportBase}${encodeURIComponent(state.compare.reportFiles.markdown)}`), "_blank")),
    );
  } else {
    reportActions.append(button("Build A/B reports", async () => {
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
    el("strong", "", `Workflow ${workflow.hashMatch ? "exact match" : "different"}`),
    el("span", "", `Nodes A ${workflow.leftNodeCount ?? "—"} · B ${workflow.rightNodeCount ?? "—"}`),
    el("span", "", `Prompt A ${state.compare.left?.promptId || "legacy run"}`),
    el("span", "", `Prompt B ${state.compare.right?.promptId || "legacy run"}`),
    el("span", "", `Sampler A ${runtime.left?.requestedSampler || "—"} → ${runtime.left?.actualSampler || "—"}`),
    el("span", "", `Sampler B ${runtime.right?.requestedSampler || "—"} → ${runtime.right?.actualSampler || "—"}`),
    el("span", "cti-empty-footnote", state.compare.disclaimer || "Observed differences are evidence, not causal percentages."),
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
      card.append(el("strong", "", `${side} · step ${(value.step ?? 0) + 1}`));
      if (value.previewUrl) {
        const img = document.createElement("img");
        img.src = imageUrl(value.previewUrl);
        card.append(img);
        previewImages.push(value.previewUrl);
      }
      const compact = el("div", "cti-compare-metrics");
      compact.append(
        el("span", "", `σ ${formatNumber(value.sigma, 3)}`),
        el("span", "", `visual Δ ${formatNumber(value.previewChange, 4)}`),
        el("span", "", `x0 μ ${formatNumber(value.x0?.mean, 4)}`),
        el("span", "", `CFG Δ ${formatNumber(value.cfg?.deltaMeanAbs, 4)}`),
        el("span", "", `Control ${value.control?.active ? formatNumber(value.control?.weightedMeanAbs, 4) : "Inactive"}`),
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
      el("strong", "", "Observed ControlNet residual"),
      el("span", "", `A ${pair.left?.control?.active ? formatNumber(leftControl, 4) : "Inactive"} · B ${pair.right?.control?.active ? formatNumber(rightControl, 4) : "Inactive"}`),
      el("span", "", `x0 mean |A-B| ${formatNumber(x0MeanDifference, 6)}`),
      el(
        "span",
        "cti-empty-footnote",
        leftControl != null && rightControl != null
          ? `Absolute residual difference ${formatNumber(Math.abs(leftControl - rightControl), 4)}. This is an observed signal, not a causal percentage.`
          : "One side has no numeric residual. Use Advanced with persist_tensor_stats enabled for both sides to compare magnitudes.",
      ),
    );
    container.append(controlSummary);
    if (previewImages.length === 2) {
      const diffHost = el("div", "cti-diff-host", "Computing decoded x0 preview difference…");
      container.append(diffHost);
      drawPreviewDiff(previewImages[0], previewImages[1], diffHost);
    }
  }

  const diff = document.createElement("details");
  diff.className = "cti-details";
  diff.open = true;
  diff.append(el("summary", "", "Changed settings"));
  diff.append(el("pre", "cti-json", JSON.stringify(state.compare.settingsDiff || {}, null, 2)));
  container.append(diff);
}

function render() {
  if (!state.root) return;
  const runList = state.root.querySelector("[data-role='runs']");
  const summary = state.root.querySelector("[data-role='summary']");
  const viewer = state.root.querySelector("[data-role='viewer']");
  const timeline = state.root.querySelector("[data-role='timeline']");
  const compare = state.root.querySelector("[data-role='compare']");
  if (runList) renderRunList(runList);
  if (summary) renderRunSummary(summary, state.selectedRun);
  if (viewer) renderStepViewer(viewer, state.selectedRun);
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

  const body = el("div", "cti-body");
  const runList = el("aside", "cti-runs");
  runList.dataset.role = "runs";

  const center = el("main", "cti-center");
  const viewer = el("section", "cti-section cti-viewer-section");
  viewer.dataset.role = "viewer";
  const timeline = el("section", "cti-section cti-path-section");
  timeline.dataset.role = "timeline";
  center.append(viewer, timeline);

  const right = el("aside", "cti-right");
  const summary = el("section", "cti-section");
  summary.dataset.role = "summary";
  const compare = el("section", "cti-section");
  compare.dataset.role = "compare";
  right.append(summary, compare);

  body.append(runList, center, right);
  state.root.append(body);
  container.replaceChildren(state.root);
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
      title: "SamplingTrace Inspector",
      type: "custom",
      targetPanel: "terminal",
      render: createPanel,
      destroy: destroyPanel,
    },
  ],
});
