import { app } from "../../scripts/app.js";

const EXTENSION_NAME = "llcrowe.SamplingTraceInspector.SlotLocalization";

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

function setSlotDisplayName(slot, displayName, { rename = false } = {}) {
  if (!slot) return;
  if (rename) slot.name = displayName;
  slot.localized_name = displayName;
  slot.label = displayName;
}

function traceNodeClass(node) {
  return node?.comfyClass || node?.type || node?.constructor?.nodeData?.name || "";
}

function applyLocalizedTraceSlotNames(node) {
  const nodeClass = traceNodeClass(node);
  if (nodeClass === "ComfyTraceClip") {
    const clipInput = (node.inputs || []).find((slot) => slot.name === "clip");
    setSlotDisplayName(
      clipInput,
      localeText("① 체크포인트 CLIP", "① Checkpoint CLIP"),
    );

    const outputNames = [
      localeText("② 긍정·부정 Text Encode", "② Positive + Negative Text Encode"),
      localeText("③ 추적 모델 · 프롬프트 추적", "③ Trace Model · Prompt Trace"),
    ];
    for (const [index, output] of (node.outputs || []).entries()) {
      if (outputNames[index]) {
        // ComfyUI serializes output links by index, so the canvas-facing name can
        // follow the locale without changing the workflow connection contract.
        setSlotDisplayName(output, outputNames[index], { rename: true });
      }
    }
    node.setDirtyCanvas?.(true, true);
    return;
  }

  if (nodeClass === "ComfyTraceModel") {
    const inputNames = {
      prompt_trace: localeText("③ CLIP 프롬프트 추적 받기", "③ Receive CLIP Prompt Trace"),
      clip: localeText("이전 방식 · 새 연결 금지", "Legacy · Do Not Use For New Graphs"),
    };
    for (const input of node.inputs || []) {
      if (inputNames[input.name]) setSlotDisplayName(input, inputNames[input.name]);
    }
    node.setDirtyCanvas?.(true, true);
  }
}

function scheduleLocalizedTraceSlotNames(node) {
  applyLocalizedTraceSlotNames(node);
  setTimeout(() => applyLocalizedTraceSlotNames(node), 0);
  setTimeout(() => applyLocalizedTraceSlotNames(node), 100);
}

function scheduleLocalizedTraceGraphSlotNames() {
  for (const node of app?.graph?._nodes || []) {
    scheduleLocalizedTraceSlotNames(node);
  }
}

function installLocalizedTraceSlotLifecycle(nodeType) {
  for (const methodName of ["onAdded", "onConfigure"]) {
    const original = nodeType.prototype[methodName];
    nodeType.prototype[methodName] = function (...args) {
      const result = original?.apply(this, args);
      scheduleLocalizedTraceSlotNames(this);
      return result;
    };
  }
}

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const nodeClass = nodeData?.name || nodeType?.comfyClass || nodeType?.type;
    if (["ComfyTraceClip", "ComfyTraceModel"].includes(nodeClass)) {
      installLocalizedTraceSlotLifecycle(nodeType);
    }
  },
  async nodeCreated(node) {
    scheduleLocalizedTraceSlotNames(node);
  },
  loadedGraphNode(node) {
    scheduleLocalizedTraceSlotNames(node);
  },
  afterConfigureGraph() {
    scheduleLocalizedTraceGraphSlotNames();
  },
  setup() {
    scheduleLocalizedTraceGraphSlotNames();
  },
});
