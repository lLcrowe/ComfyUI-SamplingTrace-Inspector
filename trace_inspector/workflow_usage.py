from __future__ import annotations

"""Read-only ComfyUI workflow usage inventory.

Only structural metadata is inspected. Prompt text, image pixels, custom-node
imports, and custom-node execution are outside this module's scope.
"""

import json
import struct
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA_VERSION = "1.0"
SCANNER_VERSION = "0.1.0"
PNG_TEXT_KEYS = {"prompt", "workflow", "extra_pnginfo"}
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PNG_TEXT_BYTES = 32 * 1024 * 1024


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat(timespec="seconds")


def _normalise_node_type(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _workflow_name(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("name", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        extra = payload.get("extra")
        if isinstance(extra, dict):
            for key in ("name", "title", "workflow_name"):
                value = extra.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return fallback


def iter_node_types(payload: Any) -> Iterator[str]:
    """Yield node types from API prompts, UI workflows, and nested subgraphs."""

    seen: set[int] = set()

    def walk(value: Any, parent_key: str | None = None) -> Iterator[str]:
        if isinstance(value, (dict, list)):
            marker = id(value)
            if marker in seen:
                return
            seen.add(marker)

        if isinstance(value, dict):
            class_type = value.get("class_type")
            if isinstance(class_type, str) and class_type.strip():
                yield class_type.strip()

            ui_type = value.get("type")
            is_ui_node = (
                isinstance(ui_type, str)
                and ui_type.strip()
                and "id" in value
                and any(key in value for key in ("inputs", "widgets_values", "properties", "outputs", "pos"))
            )
            if is_ui_node:
                yield ui_type.strip()

            for key, child in value.items():
                if isinstance(child, str) and key in PNG_TEXT_KEYS and child.lstrip().startswith(("{", "[")):
                    try:
                        child = json.loads(child)
                    except (json.JSONDecodeError, ValueError):
                        continue
                yield from walk(child, str(key))
        elif isinstance(value, list):
            for child in value:
                yield from walk(child, parent_key)

    yield from walk(payload)


def _decode_png_text(kind: bytes, data: bytes) -> tuple[str, str] | None:
    try:
        if kind == b"tEXt":
            keyword, text = data.split(b"\0", 1)
            return keyword.decode("latin-1"), text.decode("utf-8", errors="replace")
        if kind == b"zTXt":
            keyword, rest = data.split(b"\0", 1)
            if not rest or rest[0] != 0:
                return None
            return keyword.decode("latin-1"), zlib.decompress(rest[1:]).decode("utf-8", errors="replace")
        if kind == b"iTXt":
            keyword, rest = data.split(b"\0", 1)
            if len(rest) < 2:
                return None
            compressed = rest[0] == 1
            rest = rest[2:]
            _, rest = rest.split(b"\0", 1)  # language tag
            _, text = rest.split(b"\0", 1)  # translated keyword
            if compressed:
                text = zlib.decompress(text)
            return keyword.decode("latin-1"), text.decode("utf-8", errors="replace")
    except (ValueError, zlib.error, UnicodeError):
        return None
    return None


def read_png_metadata(path: Path) -> dict[str, Any]:
    """Read only PNG text chunks; IDAT image data is skipped."""

    metadata: dict[str, Any] = {}
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            return metadata
        while True:
            header = stream.read(8)
            if len(header) != 8:
                break
            size, kind = struct.unpack(">I4s", header)
            if kind in {b"tEXt", b"zTXt", b"iTXt"} and size <= MAX_PNG_TEXT_BYTES:
                data = stream.read(size)
                decoded = _decode_png_text(kind, data)
                if decoded and decoded[0] in PNG_TEXT_KEYS:
                    key, text = decoded
                    try:
                        metadata[key] = json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        metadata[key] = None
            else:
                stream.seek(size, 1)
            stream.seek(4, 1)  # CRC
            if kind == b"IEND":
                break
    return metadata


def _mapping_index(inventory: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    direct: dict[str, list[dict[str, Any]]] = defaultdict(list)
    indirect: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for package in inventory.get("packages", []):
        summary = {
            "package_id": package.get("package_id"),
            "folder_name": package.get("folder_name"),
            "static_priority": package.get("assessment", {}).get("priority", "C"),
            "adapter_need": package.get("assessment", {}).get("dedicated_adapter", "not_needed"),
            "dynamic_node_mapping": bool(package.get("dynamic_node_mapping")),
        }
        for node_type in package.get("node_mappings", {}):
            direct[_normalise_node_type(node_type)].append(summary)
        if package.get("dynamic_node_mapping"):
            for class_name in package.get("class_names", []):
                indirect[_normalise_node_type(class_name)].append(summary)
    return direct, indirect


def _classify_package(package: dict[str, Any], observations: list[dict[str, Any]], now: datetime, recent_days: int) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=recent_days)
    recent_output = False
    direct_observed = False
    saved_only = False
    for item in observations:
        direct_observed = direct_observed or not item["indirect_possible"]
        if item["is_output"] and item["evidence_type"] in {"output_prompt_metadata", "comfyui_history_api"}:
            try:
                recent_output = recent_output or datetime.fromisoformat(item["last_observed"]) >= recent_cutoff
            except (TypeError, ValueError):
                pass
        saved_only = saved_only or item["is_saved_workflow"]

    adapter_need = package.get("assessment", {}).get("dedicated_adapter", "not_needed")
    if observations and not direct_observed:
        usage_state = "INDIRECT"
        candidates = ["ACTIVE", "HISTORICAL"]
        reason = "동적 매핑의 클래스명과만 일치해 간접 증거로 유지"
    elif recent_output:
        usage_state = "ACTIVE"
        candidates = ["ACTIVE"]
        reason = f"최근 {recent_days}일 내 output/history prompt 증거"
    elif observations and saved_only:
        usage_state = "UNKNOWN"
        candidates = ["ACTIVE", "HISTORICAL"]
        reason = "저장 워크플로 증거만으로 현재 사용 여부를 확정할 수 없음"
    elif observations:
        usage_state = "UNKNOWN"
        candidates = ["HISTORICAL", "ACTIVE"]
        reason = "관찰 증거는 있으나 최근 실행 증거가 없음"
    else:
        usage_state = "UNKNOWN"
        candidates = []
        reason = "지정된 증거원에서 관찰되지 않음; 미사용으로 판정하지 않음"

    if recent_output and adapter_need in {"required", "recommended", "manual_review"}:
        trace_priority = "P1_ACTIVE"
    elif observations and saved_only and adapter_need in {"required", "recommended", "manual_review"}:
        trace_priority = "P2_NEAR_TERM"
    elif observations and adapter_need == "not_needed":
        trace_priority = "P3_GENERIC"
    elif observations:
        trace_priority = "P2_NEAR_TERM"
    else:
        trace_priority = "P5_UNKNOWN"

    return {
        "package_id": package.get("package_id"),
        "folder_name": package.get("folder_name"),
        "usage_state": usage_state,
        "candidate_states": candidates,
        "state_reason": reason,
        "trace_priority": trace_priority,
        "static_priority": package.get("assessment", {}).get("priority"),
        "adapter_need": adapter_need,
        "observed_record_count": len(observations),
        "observed_count": sum(item["observed_count"] for item in observations),
        "node_types": sorted({item["node_type"] for item in observations}, key=str.casefold),
    }


def scan_workflow_usage(
    comfy_root: Path,
    inventory: dict[str, Any],
    *,
    history_url: str | None = None,
    recent_days: int = 30,
) -> dict[str, Any]:
    comfy_root = comfy_root.resolve()
    direct, indirect = _mapping_index(inventory)
    records: dict[tuple[str, str, str, str, str, bool], dict[str, Any]] = {}
    unmatched = Counter()
    scan_errors: list[dict[str, str]] = []
    source_counts = Counter()

    def add_payload(payload: Any, evidence_type: str, source_path: str, timestamp: str, *, saved: bool, output: bool, name: str) -> None:
        counts = Counter(iter_node_types(payload))
        if not counts:
            return
        source_counts[evidence_type] += 1
        for node_type, count in counts.items():
            norm = _normalise_node_type(node_type)
            matches = direct.get(norm, [])
            is_indirect = False
            if not matches:
                matches = indirect.get(norm, [])
                is_indirect = bool(matches)
            if not matches:
                unmatched[node_type] += count
                continue
            ambiguous = len(matches) > 1
            for package in matches:
                key = (package["package_id"], node_type, evidence_type, source_path, name, is_indirect)
                item = records.get(key)
                if item is None:
                    item = {
                        "package": package["package_id"],
                        "node_type": node_type,
                        "evidence_type": evidence_type,
                        "source_path": source_path,
                        "workflow_name": name,
                        "observed_count": 0,
                        "first_observed": timestamp,
                        "last_observed": timestamp,
                        "is_saved_workflow": saved,
                        "is_output": output,
                        "indirect_possible": is_indirect,
                        "mapping_ambiguous": ambiguous,
                    }
                    records[key] = item
                item["observed_count"] += count
                item["first_observed"] = min(item["first_observed"], timestamp)
                item["last_observed"] = max(item["last_observed"], timestamp)

    for root_name in ("user", "output"):
        root = comfy_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            suffix = path.suffix.casefold()
            relative = path.relative_to(comfy_root).as_posix()
            timestamp = _iso_timestamp(path.stat().st_mtime)
            saved = "workflows" in {part.casefold() for part in path.parts}
            output = root_name == "output"
            try:
                if suffix == ".json" and path.stat().st_size <= MAX_JSON_BYTES:
                    payload = json.loads(path.read_text(encoding="utf-8-sig"))
                    node_count = sum(1 for _ in iter_node_types(payload))
                    if node_count:
                        evidence = "saved_workflow_json" if saved else "embedded_workflow_json"
                        add_payload(payload, evidence, relative, timestamp, saved=saved, output=output, name=_workflow_name(payload, path.stem))
                elif suffix == ".png":
                    metadata = read_png_metadata(path)
                    if metadata.get("prompt") is not None:
                        evidence = "output_prompt_metadata" if output else "user_prompt_metadata"
                        add_payload(metadata["prompt"], evidence, relative, timestamp, saved=saved, output=output, name=path.stem)
                    if metadata.get("workflow") is not None:
                        evidence = "png_workflow_metadata"
                        add_payload(metadata["workflow"], evidence, relative, timestamp, saved=saved, output=output, name=_workflow_name(metadata["workflow"], path.stem))
                    if metadata.get("extra_pnginfo") is not None:
                        add_payload(metadata["extra_pnginfo"], "embedded_workflow_metadata", relative, timestamp, saved=saved, output=output, name=path.stem)
            except (OSError, ValueError, json.JSONDecodeError, struct.error) as exc:
                scan_errors.append({"source_path": relative, "error": f"{type(exc).__name__}: {exc}"})

    if history_url:
        parsed = urllib.parse.urlparse(history_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("history_url must point to localhost")
        try:
            with urllib.request.urlopen(history_url, timeout=10) as response:
                history = json.loads(response.read().decode("utf-8"))
            for prompt_id, entry in history.items():
                timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                prompt = entry.get("prompt") if isinstance(entry, dict) else None
                if isinstance(prompt, list) and len(prompt) > 3:
                    meta = prompt[3] if isinstance(prompt[3], dict) else {}
                    created = meta.get("create_time")
                    if isinstance(created, (int, float)):
                        timestamp = _iso_timestamp(created / 1000)
                    add_payload(prompt[2], "comfyui_history_api", f"history:/{prompt_id}", timestamp, saved=False, output=True, name=str(prompt_id))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            scan_errors.append({"source_path": history_url, "error": f"{type(exc).__name__}: {exc}"})

    observations = sorted(records.values(), key=lambda x: (x["package"], x["node_type"].casefold(), x["source_path"], x["evidence_type"]))
    by_package: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        by_package[item["package"]].append(item)
    now = datetime.now(timezone.utc).astimezone()
    packages = [_classify_package(package, by_package.get(package.get("package_id"), []), now, recent_days) for package in inventory.get("packages", [])]
    priority_counts = Counter(item["trace_priority"] for item in packages)
    state_counts = Counter(item["usage_state"] for item in packages)
    return {
        "schema_version": SCHEMA_VERSION,
        "scanner_version": SCANNER_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "scan_mode": "read_only_structural_metadata_no_import_no_execution",
        "comfyui_root": str(comfy_root),
        "inventory_scanner_version": inventory.get("scanner_version"),
        "recent_window_days": recent_days,
        "safety": {
            "imports_custom_nodes": False,
            "executes_custom_nodes": False,
            "reads_image_pixels": False,
            "stores_prompt_text": False,
            "uses_external_network": False,
            "history_url": history_url,
        },
        "summary": {
            "package_count": len(packages),
            "observed_package_count": sum(item["observed_record_count"] > 0 for item in packages),
            "observation_record_count": len(observations),
            "observation_count": sum(item["observed_count"] for item in observations),
            "source_counts": dict(sorted(source_counts.items())),
            "usage_state_counts": dict(sorted(state_counts.items())),
            "trace_priority_counts": dict(sorted(priority_counts.items())),
            "unmatched_node_type_count": len(unmatched),
            "scan_error_count": len(scan_errors),
        },
        "usage_states": ["ACTIVE", "HISTORICAL", "PLANNED", "BLOCKED", "EXPERIMENTAL", "INDIRECT", "UNKNOWN", "RETIRED"],
        "trace_priorities": ["P0_CORE", "P1_ACTIVE", "P2_NEAR_TERM", "P3_GENERIC", "P4_DEFERRED", "P5_UNKNOWN"],
        "packages": packages,
        "observations": observations,
        "unmatched_node_types": [{"node_type": key, "observed_count": value} for key, value in unmatched.most_common()],
        "scan_errors": scan_errors,
    }


def _markdown_table(rows: Iterable[Iterable[Any]], headers: list[str]) -> list[str]:
    output = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in row) + " |")
    return output


def write_usage_reports(result: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "WORKFLOW_USAGE_INVENTORY.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    packages = result["packages"]
    observed = [item for item in packages if item["observed_record_count"]]
    lines = [
        "# Workflow Usage Inventory",
        "",
        "> 한줄 요약: 저장 워크플로·PNG 구조 메타데이터·로컬 ComfyUI history에서 관찰된 custom node 사용 증거이며, 미관찰은 미사용이 아니라 `UNKNOWN`입니다.",
        "",
        "## 맥락",
        "",
        "정적 설치 인벤토리의 기술 위험도와 실제 사용 상태를 분리하기 위해 생성했습니다. 프롬프트 원문과 이미지 픽셀은 읽거나 저장하지 않았습니다.",
        "",
        "## 요약",
        "",
    ]
    lines += _markdown_table([
        ("패키지", result["summary"]["package_count"]),
        ("관찰 패키지", result["summary"]["observed_package_count"]),
        ("증거 레코드", result["summary"]["observation_record_count"]),
        ("스캔 오류", result["summary"]["scan_error_count"]),
    ], ["항목", "값"])
    lines += ["", "## 패키지 사용 상태와 추적 우선순위", ""]
    lines += _markdown_table((
        (item["package_id"], item["usage_state"], ", ".join(item["candidate_states"]) or "-", item["trace_priority"], item["observed_count"], ", ".join(item["node_types"]) or "-")
        for item in packages
    ), ["패키지", "사용 상태", "후보", "추적 우선순위", "관찰 수", "노드 형식"])
    lines += [
        "",
        "## 판정 규칙",
        "",
        "- 최근 output/history prompt는 `ACTIVE` 후보로 자동 분류합니다.",
        "- 저장 워크플로만 있는 패키지는 `UNKNOWN`을 유지하고 `ACTIVE, HISTORICAL` 후보만 남깁니다.",
        "- `PLANNED`, `BLOCKED`, `EXPERIMENTAL`, `RETIRED`는 사용자 결정 없이는 자동 지정하지 않습니다.",
        "- 미관찰 패키지는 `UNKNOWN`이며 미사용으로 해석하지 않습니다.",
        "",
        "## 관찰 증거",
        "",
    ]
    lines += _markdown_table((
        (item["package"], item["node_type"], item["evidence_type"], item["source_path"], item["workflow_name"], item["observed_count"], item["first_observed"], item["last_observed"], item["is_saved_workflow"], item["is_output"], item["indirect_possible"])
        for item in result["observations"]
    ), ["패키지", "노드 형식", "증거", "상대 경로", "워크플로", "수", "최초", "최종", "저장", "출력", "간접"])
    lines += ["", "## 참조", "", "- `docs/CUSTOM_NODE_INVENTORY.json`", "- `docs/LOCAL_ADAPTER_PLAN_FROM_USAGE.md`", "- `docs/USER_DECISION_QUEUE.md`", ""]
    md_path = output_dir / "WORKFLOW_USAGE_INVENTORY.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    plan = [
        "# Local Adapter Plan From Usage",
        "",
        "> 한줄 요약: 실제 관찰 증거와 정적 기술 위험도를 분리해 전용 Adapter 조사 순서를 정합니다.",
        "",
        "## 맥락",
        "",
        "`CUSTOM_NODE_INVENTORY`의 Priority A는 기술 위험 후보일 뿐 실제 사용 증명이 아니므로, 사용 상태와 결합해 최소 검증 대상을 고릅니다.",
        "",
        "## 우선순위",
        "",
    ]
    plan += _markdown_table((
        (item["trace_priority"], item["package_id"], item["usage_state"], item["adapter_need"], ", ".join(item["node_types"]) or "-", item["state_reason"])
        for item in sorted(packages, key=lambda x: (x["trace_priority"], x["package_id"]))
    ), ["추적 우선순위", "패키지", "사용 상태", "Adapter", "관찰 노드", "근거"])
    plan += [
        "",
        "## 실행 규칙",
        "",
        "1. `P1_ACTIVE`: 실제 최근 실행 증거가 있고 전용 관찰 가능성 검토가 필요한 패키지만 최소 Runtime workflow를 만듭니다.",
        "2. `P2_NEAR_TERM`: 저장 workflow 증거는 있으나 현재 실행 여부가 불명확하므로 source review와 사용자 확인을 먼저 합니다.",
        "3. `P3_GENERIC`: 범용 execution timeline으로 충분한지 표준 workflow에서만 확인합니다.",
        "4. `P5_UNKNOWN`: 미관찰을 미사용으로 단정하지 않고 Adapter 구현을 연기합니다.",
        "5. 사용자 승인 없이 노드 삭제·비활성화·requirements 설치·모델 다운로드를 하지 않습니다.",
        "",
        "## 참조",
        "",
        "- `docs/WORKFLOW_USAGE_INVENTORY.json`",
        "- `docs/CUSTOM_NODE_RUNTIME_PATHS.md`",
        "",
    ]
    plan_path = output_dir / "LOCAL_ADAPTER_PLAN_FROM_USAGE.md"
    plan_path.write_text("\n".join(plan), encoding="utf-8")

    queue = [
        "# User Decision Queue",
        "",
        "> 한줄 요약: 자동으로 확정할 수 없는 사용 상태만 사용자 판단 대기열로 분리합니다.",
        "",
        "## 맥락",
        "",
        "`PLANNED`, `BLOCKED`, `EXPERIMENTAL`, `RETIRED`는 파일 관찰만으로 판정하지 않습니다. 현재 자동 스캔은 이 상태를 한 건도 확정하지 않았습니다.",
        "",
        "## 확인 후보",
        "",
    ]
    candidates = [item for item in observed if item["usage_state"] in {"UNKNOWN", "INDIRECT"}]
    queue += _markdown_table((
        (item["package_id"], item["usage_state"], ", ".join(item["candidate_states"]) or "-", "지금 계속 쓰는 패키지인가요, 과거 보존용인가요?" if item["usage_state"] == "UNKNOWN" else "동적 노드 매핑을 Runtime에서 확인해도 될까요?")
        for item in candidates
    ), ["패키지", "현재 판정", "후보", "최소 질문"])
    queue += [
        "",
        "## 상태 선택 기준",
        "",
        "- `PLANNED`: 아직 workflow 실행 전이지만 가까운 시일 내 사용할 예정",
        "- `BLOCKED`: 사용 의도는 있으나 모델·의존성·호환성 문제로 막힘",
        "- `EXPERIMENTAL`: 시험 중이며 기준 workflow에 포함되지 않음",
        "- `RETIRED`: 과거 기록은 남기되 앞으로 사용하지 않음",
        "",
        "## 참조",
        "",
        "- `docs/WORKFLOW_USAGE_INVENTORY.md`",
        "",
    ]
    queue_path = output_dir / "USER_DECISION_QUEUE.md"
    queue_path.write_text("\n".join(queue), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "adapter_plan": str(plan_path), "decision_queue": str(queue_path)}
