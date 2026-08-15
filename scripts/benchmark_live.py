from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import statistics
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


class NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class MemorySampler:
    def __init__(self, interval: float = 0.05) -> None:
        self.interval = interval
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._nvml = ctypes.WinDLL("nvml.dll")
        if self._nvml.nvmlInit_v2() != 0:
            raise RuntimeError("NVML initialization failed")
        self._handle = ctypes.c_void_p()
        if self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self._handle)) != 0:
            raise RuntimeError("NVML device 0 was not found")

    def read(self) -> int:
        memory = NvmlMemory()
        result = self._nvml.nvmlDeviceGetMemoryInfo(self._handle, ctypes.byref(memory))
        if result != 0:
            raise RuntimeError(f"NVML memory query failed: {result}")
        return int(memory.used)

    def start(self) -> int:
        baseline = self.read()
        self.samples = [baseline]
        self._stop.clear()

        def sample() -> None:
            while not self._stop.wait(self.interval):
                try:
                    self.samples.append(self.read())
                except Exception:
                    pass

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return baseline

    def finish(self) -> tuple[int, int]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.samples.append(self.read())
        return min(self.samples), max(self.samples)


def request_json(base_url: str, path: str, *, method: str = "GET", body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def assert_queue_empty(base_url: str) -> None:
    queue = request_json(base_url, "/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not empty")


def build_graph(
    *,
    mode: str,
    run_index: int,
    seed: int,
    output_prefix: str,
) -> dict[str, Any]:
    trace_id = str(1000 + run_index)
    sampler_id = str(2000 + run_index)
    decode_id = str(3000 + run_index)
    save_id = str(4000 + run_index)
    graph: dict[str, Any] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "waiIllustriousSDXL_v170.safetensors"}},
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "1girl, solo, simple background, masterpiece, best quality",
                "clip": ["1", 1],
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "lowres, blurry, bad anatomy, text, watermark", "clip": ["1", 1]},
        },
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    }
    model_link: list[Any] = ["1", 0]
    if mode != "off":
        advanced = mode.startswith("advanced")
        graph[trace_id] = {
            "class_type": "ComfyTraceModel",
            "inputs": {
                "model": ["1", 0],
                "mode": "advanced" if advanced else "basic",
                "label": f"022-10-{mode}-{run_index}",
                "preview_every": 1,
                "preview_max_side": 512,
                "preview_format": "PNG",
                "preview_quality": 100,
                "persist_previews": True,
                "persist_tensor_stats": mode == "advanced_influence",
            },
        }
        model_link = [trace_id, 0]
    graph[sampler_id] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_link,
            "seed": seed,
            "steps": 8,
            "cfg": 5.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
            "denoise": 1.0,
        },
    }
    graph[decode_id] = {"class_type": "VAEDecode", "inputs": {"samples": [sampler_id, 0], "vae": ["1", 2]}}
    graph[save_id] = {
        "class_type": "SaveImage",
        "inputs": {"images": [decode_id, 0], "filename_prefix": output_prefix},
    }
    return graph


def wait_history(base_url: str, prompt_id: str, timeout: float = 480) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = request_json(base_url, f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            if entry.get("status", {}).get("status_str") != "success":
                raise RuntimeError(f"Prompt {prompt_id} failed: {entry.get('status')}")
            return entry
        time.sleep(0.15)
    raise TimeoutError(prompt_id)


def history_duration_ms(entry: dict[str, Any]) -> int | None:
    timestamps: dict[str, int] = {}
    for message in entry.get("status", {}).get("messages", []):
        if not isinstance(message, list) or len(message) != 2 or not isinstance(message[1], dict):
            continue
        if "timestamp" in message[1]:
            timestamps[str(message[0])] = int(message[1]["timestamp"])
    start = timestamps.get("execution_start")
    end = timestamps.get("execution_success")
    return end - start if start is not None and end is not None else None


def output_path(comfy_root: Path, entry: dict[str, Any], output_root: Path | None = None) -> Path:
    for output in entry.get("outputs", {}).values():
        images = output.get("images", []) if isinstance(output, dict) else []
        if not images:
            continue
        image = images[0]
        image_type = image.get("type", "output")
        root = output_root if image_type == "output" and output_root is not None else comfy_root / image_type
        return root / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("Prompt history has no output image")


def image_hashes(path: Path) -> dict[str, Any]:
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    return {
        "pngSha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "rgbaSha256": hashlib.sha256(rgba.tobytes()).hexdigest().upper(),
        "width": int(rgba.shape[1]),
        "height": int(rgba.shape[0]),
    }


def find_run(base_url: str, prompt_id: str, timeout: float = 10) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = request_json(base_url, "/trace-inspector/runs?limit=300").get("runs", [])
        match = next((run for run in runs if run.get("promptId") == prompt_id), None)
        if match is not None:
            return request_json(base_url, f"/trace-inspector/runs/{match['runId']}")
        time.sleep(0.1)
    return None


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run_one(
    *,
    base_url: str,
    comfy_root: Path,
    output_root: Path | None,
    trace_root: Path,
    memory: MemorySampler,
    mode: str,
    run_index: int,
    seed: int,
    measured: bool,
) -> dict[str, Any]:
    assert_queue_empty(base_url)
    prompt_id = str(uuid.uuid4())
    prefix = f"TraceInspectorValidation/022_10_{mode}_{run_index}"
    graph = build_graph(mode=mode, run_index=run_index, seed=seed, output_prefix=prefix)
    baseline = memory.start()
    started = time.perf_counter()
    response = request_json(
        base_url,
        "/prompt",
        method="POST",
        body={"prompt": graph, "client_id": "codex-02210-benchmark", "prompt_id": prompt_id},
    )
    if response.get("prompt_id") != prompt_id or response.get("node_errors"):
        raise RuntimeError(f"Prompt rejected: {response}")
    entry = wait_history(base_url, prompt_id)
    client_wall_ms = (time.perf_counter() - started) * 1000
    _minimum, peak = memory.finish()
    path = output_path(comfy_root, entry, output_root)
    hashes = image_hashes(path)
    run = find_run(base_url, prompt_id) if mode != "off" else None
    run_dir = trace_root / run["runId"] if run else None
    result = {
        "mode": mode,
        "runIndex": run_index,
        "promptId": prompt_id,
        "runId": run.get("runId") if run else None,
        "measured": measured,
        "historyWallMs": history_duration_ms(entry),
        "clientWallMs": round(client_wall_ms, 3),
        "vramBaselineMiB": round(baseline / 1048576, 3),
        "vramPeakMiB": round(peak / 1048576, 3),
        "vramPeakDeltaMiB": round((peak - baseline) / 1048576, 3),
        "traceDiskBytes": directory_bytes(run_dir) if run_dir else 0,
        "output": str(path),
        **hashes,
    }
    assert_queue_empty(base_url)
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in ("off", "basic", "advanced_standard", "advanced_influence"):
        rows = [row for row in results if row["measured"] and row["mode"] == mode]
        if not rows:
            continue
        summary[mode] = {
            "n": len(rows),
            "historyWallMsMean": round(sum(row["historyWallMs"] for row in rows) / len(rows), 3),
            "historyWallMsMin": min(row["historyWallMs"] for row in rows),
            "historyWallMsMax": max(row["historyWallMs"] for row in rows),
            "vramPeakMiBMax": max(row["vramPeakMiB"] for row in rows),
            "vramPeakDeltaMiBMax": max(row["vramPeakDeltaMiB"] for row in rows),
            "traceDiskBytesMean": round(sum(row["traceDiskBytes"] for row in rows) / len(rows), 3),
            "rgbaSha256": sorted({row["rgbaSha256"] for row in rows}),
        }
    off_by_repetition = {
        row["repetition"]: row
        for row in results
        if row.get("measured") and row.get("mode") == "off" and row.get("repetition")
    }
    for mode in ("basic", "advanced_standard", "advanced_influence"):
        deltas: list[float] = []
        percentages: list[float] = []
        for row in results:
            baseline = off_by_repetition.get(row.get("repetition"))
            if not baseline or row.get("mode") != mode:
                continue
            delta = float(row["historyWallMs"] - baseline["historyWallMs"])
            deltas.append(delta)
            percentages.append(delta / baseline["historyWallMs"] * 100)
        if mode in summary and deltas:
            summary[mode]["pairedWallMsMedianDeltaVsOff"] = round(statistics.median(deltas), 3)
            summary[mode]["pairedWallPercentMedianVsOff"] = round(statistics.median(percentages), 3)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark live ComfyUI Trace Inspector modes.")
    parser.add_argument("--url", default="http://127.0.0.1:8888")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    comfy_root = Path(__file__).resolve().parents[3]
    trace_root = Path(request_json(args.url, "/trace-inspector/health")["baseDirectory"])
    memory = MemorySampler()
    seed_base = 2608151000
    results: list[dict[str, Any]] = []
    status = "PASS"
    error: str | None = None
    try:
        warmup = run_one(
                base_url=args.url,
                comfy_root=comfy_root,
                output_root=args.output_root,
                trace_root=trace_root,
                memory=memory,
                mode="off",
                run_index=900,
                seed=seed_base,
                measured=False,
            )
        warmup["repetition"] = 0
        results.append(warmup)
        run_index = 0
        for repetition in range(args.repeats):
            seed = seed_base + repetition + 1
            reference_hash: str | None = None
            for mode in ("off", "basic", "advanced_standard", "advanced_influence"):
                run_index += 1
                row = run_one(
                    base_url=args.url,
                    comfy_root=comfy_root,
                    output_root=args.output_root,
                    trace_root=trace_root,
                    memory=memory,
                    mode=mode,
                    run_index=run_index,
                    seed=seed,
                    measured=True,
                )
                row["repetition"] = repetition + 1
                results.append(row)
                if reference_hash is None:
                    reference_hash = row["rgbaSha256"]
                elif row["rgbaSha256"] != reference_hash:
                    raise RuntimeError(
                        f"Decoded pixel mismatch at {mode} repetition {repetition + 1}: "
                        f"{row['rgbaSha256']} != {reference_hash}"
                    )
    except Exception as exc:
        status = "FAIL"
        error = str(exc)
    payload = {
        "status": status,
        "error": error,
        "conditions": {
            "model": "waiIllustriousSDXL_v170.safetensors",
            "size": "512x512",
            "seedBase": seed_base,
            "measuredSeeds": [seed_base + index + 1 for index in range(args.repeats)],
            "sampler": "euler",
            "scheduler": "normal",
            "steps": 8,
            "cfg": 5.0,
            "warmup": 1,
            "repeats": args.repeats,
        },
        "summary": summarize(results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
