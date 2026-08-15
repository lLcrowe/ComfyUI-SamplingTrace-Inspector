from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from trace_inspector.workflow_usage import iter_node_types, read_png_metadata, scan_workflow_usage, write_usage_reports


def _png_text(path: Path, entries: dict[str, object]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = bytearray(b"\x89PNG\r\n\x1a\n")
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    for key, value in entries.items():
        payload += chunk(b"tEXt", key.encode("latin-1") + b"\0" + json.dumps(value).encode("utf-8"))
    payload += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _inventory() -> dict[str, object]:
    return {
        "scanner_version": "0.3.0",
        "packages": [
            {
                "package_id": "sample-pack",
                "folder_name": "SamplePack",
                "node_mappings": {"SampleNode": "SampleNode"},
                "class_names": ["SampleNode"],
                "dynamic_node_mapping": False,
                "assessment": {"priority": "A", "dedicated_adapter": "required"},
            },
            {
                "package_id": "unseen-pack",
                "folder_name": "UnseenPack",
                "node_mappings": {"Unseen": "Unseen"},
                "class_names": ["Unseen"],
                "dynamic_node_mapping": False,
                "assessment": {"priority": "A", "dedicated_adapter": "required"},
            },
        ],
    }


def test_iter_node_types_supports_prompt_workflow_and_subgraph() -> None:
    payload = {
        "prompt": {"1": {"class_type": "SampleNode", "inputs": {}}},
        "nodes": [{"id": 2, "type": "OtherNode", "inputs": []}],
        "definitions": {"subgraphs": [{"nodes": [{"id": 3, "type": "NestedNode", "inputs": []}]}]},
    }
    assert list(iter_node_types(payload)) == ["SampleNode", "OtherNode", "NestedNode"]


def test_reads_png_text_without_decoding_pixels(tmp_path: Path) -> None:
    path = tmp_path / "sample.png"
    _png_text(path, {"prompt": {"1": {"class_type": "SampleNode", "inputs": {}}}})
    metadata = read_png_metadata(path)
    assert metadata["prompt"]["1"]["class_type"] == "SampleNode"


def test_scan_classifies_recent_output_and_unknown_unseen(tmp_path: Path) -> None:
    comfy = tmp_path / "ComfyUI"
    workflow = comfy / "user" / "default" / "workflows" / "saved.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(json.dumps({"nodes": [{"id": 1, "type": "SampleNode", "inputs": []}]}), encoding="utf-8")
    _png_text(comfy / "output" / "run.png", {"prompt": {"1": {"class_type": "SampleNode", "inputs": {}}}})

    result = scan_workflow_usage(comfy, _inventory())
    sample = next(item for item in result["packages"] if item["package_id"] == "sample-pack")
    unseen = next(item for item in result["packages"] if item["package_id"] == "unseen-pack")
    assert sample["usage_state"] == "ACTIVE"
    assert sample["trace_priority"] == "P1_ACTIVE"
    assert unseen["usage_state"] == "UNKNOWN"
    assert unseen["trace_priority"] == "P5_UNKNOWN"

    outputs = write_usage_reports(result, tmp_path / "reports")
    assert all(Path(path).exists() for path in outputs.values())
