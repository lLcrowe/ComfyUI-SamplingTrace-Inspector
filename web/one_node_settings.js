import { app } from "../../scripts/app.js";

const EXTENSION_NAME = "llcrowe.SamplingTraceInspector.OneNodeSettings";
const NODE_CLASS = "ComfyTraceOneNode";
const PRESET_WIDGET = "trace_preset";
const SETTINGS_BUTTON = "trace_settings_button";
const STYLE_ID = "comfy-trace-inspector-style";
const VALID_PRESETS = new Set(["basic", "advanced"]);

let activePopup = null;

function currentLanguage() {
  const language = app?.ui?.settings?.getSettingValue?.("Comfy.Locale")
    || document.documentElement.lang
    || navigator.language
    || "en";
  return String(language).toLowerCase();
}

function localeText(korean, english) {
  return currentLanguage().startsWith("ko") ? korean : english;
}

function injectStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = new URL("./trace_inspector.css", import.meta.url).href;
  document.head.appendChild(link);
}

function normalizePreset(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return VALID_PRESETS.has(normalized) ? normalized : "basic";
}

function presetLabel(value) {
  return normalizePreset(value) === "advanced"
    ? localeText("고급", "Advanced")
    : localeText("기본", "Basic");
}

function findPresetWidget(node) {
  return (node?.widgets || []).find((widget) => widget.name === PRESET_WIDGET) || null;
}

function hidePresetWidget(widget) {
  if (!widget || widget.__ctiPresetHidden) return;
  widget.__ctiPresetHidden = true;
  widget.__ctiOriginalType = widget.type;
  widget.type = "hidden";
  widget.hidden = true;
  widget.computeSize = () => [0, -4];
  widget.draw = () => {};
  if (widget.element) widget.element.style.display = "none";
}

function buttonLabel(node) {
  const preset = normalizePreset(findPresetWidget(node)?.value);
  return localeText(
    `⚙ 추적 설정 · ${presetLabel(preset)}`,
    `⚙ Trace settings · ${presetLabel(preset)}`,
  );
}

function updateSettingsButton(node) {
  const button = (node?.widgets || []).find((widget) => widget.__ctiSettingsButton);
  if (!button) return;
  button.name = buttonLabel(node);
  node.setDirtyCanvas?.(true, true);
}

function markWorkflowChanged(node) {
  node?.graph?.change?.();
  app?.graph?.change?.();
  node?.setDirtyCanvas?.(true, true);
}

function applyPreset(node, value) {
  const widget = findPresetWidget(node);
  if (!widget) return;
  const preset = normalizePreset(value);
  widget.value = preset;
  node.properties ||= {};
  node.properties.ctiTracePreset = preset;
  widget.callback?.(preset);
  updateSettingsButton(node);
  markWorkflowChanged(node);
}

function closePopup() {
  if (!activePopup) return;
  document.removeEventListener("keydown", activePopup.onKeyDown, true);
  activePopup.overlay.remove();
  activePopup = null;
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function presetCard(node, preset, title, description, detail) {
  const card = createElement("button", "cti-one-node-preset");
  card.type = "button";
  card.dataset.preset = preset;
  card.setAttribute("aria-pressed", String(normalizePreset(findPresetWidget(node)?.value) === preset));

  const heading = createElement("span", "cti-one-node-preset-title", title);
  const summary = createElement("span", "cti-one-node-preset-description", description);
  const meta = createElement("span", "cti-one-node-preset-detail", detail);
  card.append(heading, summary, meta);
  card.addEventListener("click", () => {
    applyPreset(node, preset);
    closePopup();
  });
  return card;
}

function openSettingsPopup(node) {
  const widget = findPresetWidget(node);
  if (!widget) return;
  closePopup();
  injectStyles();

  const overlay = createElement("div", "cti-one-node-settings-overlay");
  const dialog = createElement("section", "cti-one-node-settings");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "cti-one-node-settings-title");

  const header = createElement("header", "cti-one-node-settings-header");
  const headingGroup = createElement("div", "cti-one-node-settings-heading");
  const title = createElement(
    "h2",
    "cti-one-node-settings-title",
    localeText("추적 수집 수준", "Trace capture level"),
  );
  title.id = "cti-one-node-settings-title";
  const subtitle = createElement(
    "p",
    "cti-one-node-settings-subtitle",
    localeText(
      "배선은 그대로 두고 다음 실행부터 수집 깊이만 바꿉니다.",
      "Keep the wiring unchanged and choose how much the next run captures.",
    ),
  );
  headingGroup.append(title, subtitle);

  const closeButton = createElement("button", "cti-one-node-settings-close", "×");
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", localeText("닫기", "Close"));
  closeButton.addEventListener("click", closePopup);
  header.append(headingGroup, closeButton);

  const options = createElement("div", "cti-one-node-settings-options");
  options.append(
    presetCard(
      node,
      "basic",
      localeText("기본 · 권장", "Basic · Recommended"),
      localeText(
        "스텝, 중간 미리보기, 형태·자료형·장치, 노드 타임라인을 기록합니다.",
        "Captures steps, previews, shape, dtype, device, and the node timeline.",
      ),
      localeText("낮은 수집 비용 · 평소 추적", "Lower capture cost · everyday tracing"),
    ),
    presetCard(
      node,
      "advanced",
      localeText("고급", "Advanced"),
      localeText(
        "기본 기록에 x/x0, CFG, ControlNet 잔차와 단계별 프롬프트 단어 주의를 더합니다.",
        "Adds x/x0, CFG, ControlNet residuals, and step-level prompt-word attention.",
      ),
      localeText("중간~높은 수집 비용 · 원인 분석", "Medium-to-high capture cost · deep diagnosis"),
    ),
  );

  const batchInfo = createElement("section", "cti-one-node-batch-info");
  batchInfo.append(
    createElement(
      "strong",
      "cti-one-node-batch-title",
      localeText("배치별 추적 · 자동", "Per-item batch trace · Automatic"),
    ),
    createElement(
      "span",
      "cti-one-node-batch-description",
      localeText(
        "배치가 여러 장이면 다음 실행부터 각 장의 중간 미리보기와 잠재값을 따로 기록합니다. 추적 패널의 1/N 선택기로 전환할 수 있습니다.",
        "When a batch contains multiple images, the next run stores each item's previews and latents separately. Switch between them with the 1/N selector in the trace panel.",
      ),
    ),
  );

  const footer = createElement(
    "p",
    "cti-one-node-settings-footer",
    localeText(
      "선택값은 워크플로에 저장되며 다음 큐 실행부터 적용됩니다.",
      "The choice is saved with the workflow and applies from the next queued run.",
    ),
  );

  dialog.append(header, options, batchInfo, footer);
  overlay.append(dialog);
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) closePopup();
  });

  const onKeyDown = (event) => {
    if (event.key === "Escape") closePopup();
  };
  activePopup = { overlay, onKeyDown };
  document.addEventListener("keydown", onKeyDown, true);
  document.body.appendChild(overlay);
  closeButton.focus();
}

function ensureOneNodeSettings(node) {
  const widget = findPresetWidget(node);
  if (!widget) return;
  widget.value = normalizePreset(widget.value || node?.properties?.ctiTracePreset);
  hidePresetWidget(widget);

  let button = (node.widgets || []).find((candidate) => candidate.__ctiSettingsButton);
  if (!button) {
    button = node.addWidget(
      "button",
      buttonLabel(node),
      null,
      () => openSettingsPopup(node),
      { serialize: false },
    );
    button.__ctiSettingsButton = SETTINGS_BUTTON;
    button.serialize = false;
  }
  updateSettingsButton(node);
}

function scheduleOneNodeSettings(node) {
  ensureOneNodeSettings(node);
  setTimeout(() => ensureOneNodeSettings(node), 0);
  setTimeout(() => ensureOneNodeSettings(node), 100);
}

function installOneNodeSettingsLifecycle(nodeType) {
  for (const methodName of ["onAdded", "onConfigure"]) {
    const original = nodeType.prototype[methodName];
    nodeType.prototype[methodName] = function (...args) {
      const result = original?.apply(this, args);
      scheduleOneNodeSettings(this);
      return result;
    };
  }
}

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name === NODE_CLASS) installOneNodeSettingsLifecycle(nodeType);
  },
  async nodeCreated(node) {
    if (node?.comfyClass === NODE_CLASS) scheduleOneNodeSettings(node);
  },
  loadedGraphNode(node) {
    if (node?.comfyClass === NODE_CLASS) scheduleOneNodeSettings(node);
  },
  afterConfigureGraph() {
    for (const node of app?.graph?._nodes || []) {
      if (node?.comfyClass === NODE_CLASS) scheduleOneNodeSettings(node);
    }
  },
  setup() {
    injectStyles();
  },
});
