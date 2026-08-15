from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import websockets
from PIL import Image


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
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


def build_graph(*, mode: str, seed: int, output_prefix: str) -> dict[str, Any]:
    graph: dict[str, Any] = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "waiIllustriousSDXL_v170.safetensors"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
    }
    clip_link: list[Any] = ["1", 1]
    model_link: list[Any] = ["1", 0]
    if mode == "on":
        graph["5"] = {
            "class_type": "ComfyTraceClip",
            "inputs": {"clip": ["1", 1]},
        }
        clip_link = ["5", 0]
        graph["6"] = {
            "class_type": "ComfyTraceModel",
            "inputs": {
                "model": ["1", 0],
                "prompt_trace": ["5", 1],
                "mode": "advanced",
                "label": "022-A-1-prompt-capture-live",
                "preview_every": 1,
                "preview_max_side": 512,
                "preview_format": "PNG",
                "preview_quality": 100,
                "preview_decoder": "fast",
                "persist_previews": True,
                "persist_tensor_stats": True,
            },
        }
        model_link = ["6", 0]
    graph["2"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "1girl, solo, red dress, simple background, masterpiece, best quality",
            "clip": clip_link,
        },
    }
    graph["3"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "lowres, blurry, bad anatomy, text, watermark",
            "clip": clip_link,
        },
    }
    graph["7"] = {
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
    graph["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["7", 0], "vae": ["1", 2]},
    }
    graph["9"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0], "filename_prefix": output_prefix},
    }
    return graph


def wait_history(base_url: str, prompt_id: str, timeout: float = 480) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = request_json(base_url, f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            if entry.get("status", {}).get("status_str") != "success":
                raise RuntimeError(f"Prompt failed: {entry.get('status')}")
            return entry
        time.sleep(0.15)
    raise TimeoutError(prompt_id)


def output_path(comfy_root: Path, entry: dict[str, Any]) -> Path:
    for output in entry.get("outputs", {}).values():
        images = output.get("images", []) if isinstance(output, dict) else []
        if images:
            image = images[0]
            return comfy_root / image.get("type", "output") / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("Prompt history has no output image")


def image_hashes(path: Path) -> dict[str, Any]:
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    return {
        "pngSha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "rgbaSha256": hashlib.sha256(rgba.tobytes()).hexdigest().upper(),
        "width": int(rgba.shape[1]),
        "height": int(rgba.shape[0]),
    }


def find_run(base_url: str, prompt_id: str, timeout: float = 15) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = request_json(base_url, "/trace-inspector/runs?limit=300").get("runs", [])
        match = next((run for run in runs if run.get("promptId") == prompt_id), None)
        if match:
            return request_json(base_url, f"/trace-inspector/runs/{match['runId']}")
        time.sleep(0.1)
    return None


async def submit_with_events(
    *,
    base_url: str,
    graph: dict[str, Any],
    prompt_id: str,
    client_id: str,
) -> tuple[dict[str, Any], list[str]]:
    websocket_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    websocket_url = f"{websocket_url.rstrip('/')}/ws?clientId={client_id}"
    events: list[str] = []
    async with websockets.connect(websocket_url, max_size=None) as websocket:
        async def collect() -> None:
            while True:
                message = await websocket.recv()
                if isinstance(message, bytes):
                    events.append("preview_binary")
                    continue
                payload = json.loads(message)
                event_type = str(payload.get("type", ""))
                if event_type == "progress" or event_type.startswith("trace_inspector."):
                    events.append(event_type)

        collector = asyncio.create_task(collect())
        try:
            response = await asyncio.to_thread(
                request_json,
                base_url,
                "/prompt",
                method="POST",
                body={"prompt": graph, "client_id": client_id, "prompt_id": prompt_id},
            )
            if response.get("prompt_id") != prompt_id or response.get("node_errors"):
                raise RuntimeError(f"Prompt rejected: {response}")
            entry = await asyncio.to_thread(wait_history, base_url, prompt_id)
            await asyncio.sleep(0.5)
        finally:
            collector.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await collector
    return entry, events


def callback_summary(events: list[str]) -> dict[str, Any]:
    step_indexes = [index for index, value in enumerate(events) if value == "trace_inspector.step"]
    progress_indexes = [index for index, value in enumerate(events) if value == "progress"]
    preview_indexes = [index for index, value in enumerate(events) if value == "preview_binary"]
    triples: list[bool] = []
    for position, step_index in enumerate(step_indexes):
        boundary = step_indexes[position + 1] if position + 1 < len(step_indexes) else len(events)
        next_progress = next((index for index in progress_indexes if step_index < index < boundary), None)
        next_preview = next(
            (
                index
                for index in preview_indexes
                if next_progress is not None and next_progress < index < boundary
            ),
            None,
        )
        triples.append(next_progress is not None and next_preview is not None)
    return {
        "traceSteps": len(step_indexes),
        "progress": len(progress_indexes),
        "livePreviews": len(preview_indexes),
        "traceProgressPreviewOrderPreserved": bool(triples) and all(triples),
        "sequence": events,
    }


def validate_prompt_capture(run: dict[str, Any]) -> dict[str, Any]:
    capture = run.get("promptTokenization") or {}
    prompts = capture.get("prompts") or []
    roles = {role for prompt in prompts for role in prompt.get("roles", [])}
    visible_calls = [
        call
        for prompt in prompts
        for call in prompt.get("calls", [])
        if not call.get("internal")
    ]
    encoder_lanes = sorted(
        {
            str(encoder.get("name"))
            for call in visible_calls
            for encoder in call.get("encoders", [])
        }
    )
    result = {
        "status": capture.get("status"),
        "source": capture.get("source"),
        "modelFamily": capture.get("modelFamily"),
        "callCount": capture.get("callCount"),
        "promptNodeCount": len(prompts),
        "roles": sorted(roles),
        "visibleCalls": len(visible_calls),
        "encoderLanes": encoder_lanes,
    }
    if capture.get("status") != "captured" or capture.get("source") != "traced_clip":
        raise RuntimeError(f"Prompt capture is incomplete: {result}")
    if not {"positive", "negative"}.issubset(roles):
        raise RuntimeError(f"Prompt roles are incomplete: {result}")
    if len(visible_calls) < 2 or not {"g", "l"}.issubset(encoder_lanes):
        raise RuntimeError(f"Prompt token lanes are incomplete: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Sampling Trace CLIP on a live ComfyUI server.")
    parser.add_argument("--url", default="http://127.0.0.1:8888")
    parser.add_argument("--mode", choices=("off", "on"), required=True)
    parser.add_argument("--seed", type=int, default=2608160221)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()

    assert_queue_empty(args.url)
    prompt_id = str(uuid.uuid4())
    client_id = f"codex-022-a1-{args.mode}-{uuid.uuid4()}"
    graph = build_graph(mode=args.mode, seed=args.seed, output_prefix=args.output_prefix)
    started = time.perf_counter()
    entry, events = asyncio.run(
        submit_with_events(
            base_url=args.url,
            graph=graph,
            prompt_id=prompt_id,
            client_id=client_id,
        )
    )
    comfy_root = Path(__file__).resolve().parents[3]
    path = output_path(comfy_root, entry)
    run = find_run(args.url, prompt_id) if args.mode == "on" else None
    health = request_json(args.url, "/trace-inspector/health")
    run_directory = Path(health["baseDirectory"]) / run["runId"] if run else None
    artifacts = {
        name: bool(run_directory and (run_directory / name).is_file())
        for name in ("run.json", "steps.jsonl", "probes.jsonl", "report.md", "report.html")
    }
    result = {
        "status": "PASS",
        "mode": args.mode,
        "promptId": prompt_id,
        "runId": run.get("runId") if run else None,
        "conditions": {
            "model": "waiIllustriousSDXL_v170.safetensors",
            "size": "512x512",
            "seed": args.seed,
            "sampler": "euler",
            "scheduler": "normal",
            "steps": 8,
            "cfg": 5.0,
        },
        "clientWallMs": round((time.perf_counter() - started) * 1000, 3),
        "output": str(path),
        **image_hashes(path),
        "callbacks": callback_summary(events),
        "artifacts": artifacts,
        "runDirectory": str(run_directory) if run_directory else None,
        "promptCapture": validate_prompt_capture(run) if run else None,
        "runStepCount": run.get("stepCount") if run else None,
        "runErrors": run.get("errors") if run else None,
    }
    if run and (run.get("promptId") != prompt_id or run.get("stepCount") != 8 or run.get("errors")):
        raise RuntimeError("Trace Run linkage, step count, or errors failed validation")
    if run and not all(artifacts[name] for name in ("run.json", "steps.jsonl", "report.md", "report.html")):
        raise RuntimeError(f"Trace artifacts are incomplete: {artifacts}")
    assert_queue_empty(args.url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
