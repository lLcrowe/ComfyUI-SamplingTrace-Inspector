from __future__ import annotations

"""Static inventory scanner for installed ComfyUI custom nodes.

The scanner deliberately does not import, execute, compile, or install the
inspected packages. It only reads source/manifests/Git metadata and parses
Python with ``ast``. The generated assessment is heuristic and must be treated
as a starting point for adapter work, not as proof of runtime behaviour.
"""

import argparse
import ast
import configparser
import hashlib
import json
import os
import re
import sys
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


SCHEMA_VERSION = "1.0"
SCANNER_VERSION = "0.3.0"

SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
}

MANIFEST_NAMES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements_dev.txt",
    "package.json",
    "comfyui-node.json",
    "node_list.json",
    "install.py",
    "install.bat",
    "install.sh",
}

DEFAULT_SKIP_DIRS = {
    ".git",
    ".github",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "models",
    "input",
    "output",
    "temp",
    "tmp",
    "dist",
    "build",
    "docs",
    "examples",
    "example",
    "tests",
    "test",
}

OPTIONAL_AUXILIARY_DIR_PATTERN = re.compile(
    r"(?:^|[_-])(?:browser[_-]?tests?|unit[_-]?tests?|tests?|e2e|playwright|"
    r"examples?|samples?|demos?|fixtures?|benchmarks?)(?:$|[_-])",
    re.IGNORECASE,
)

SELF_PACKAGE_NAMES = {
    "comfyui-samplingtrace-inspector",
    "comfyui-trace-inspector",
    "comfyui_trace_inspector",
    "trace-inspector",
}

KNOWN_COMFY_TYPES = {
    "MODEL",
    "CLIP",
    "VAE",
    "CONDITIONING",
    "LATENT",
    "IMAGE",
    "MASK",
    "CONTROL_NET",
    "CONTROLNET",
    "SAMPLER",
    "SIGMAS",
    "GUIDER",
    "NOISE",
    "SEED",
    "CLIP_VISION",
    "CLIP_VISION_OUTPUT",
    "BBOX_DETECTOR",
    "SEGM_DETECTOR",
    "SAM_MODEL",
    "UPSCALE_MODEL",
    "GLIGEN",
    "TAESD",
    "AUDIO",
    "VIDEO",
}

# Patterns are intentionally broad. They are evidence flags, not definitive
# behavioural claims.
FEATURE_PATTERNS: dict[str, tuple[str, ...]] = {
    "uses_model_patcher": (
        r"\bModelPatcher\b",
        r"comfy\.model_patcher",
        r"\.add_patches\s*\(",
        r"\.set_model_patch",
        r"\.set_model_attn",
        r"\.set_model_sampler_",
    ),
    "uses_model_options": (r"\bmodel_options\b",),
    "uses_transformer_options": (r"\btransformer_options\b", r"patches_replace"),
    "uses_wrappers": (
        r"\bWrappersMP\b",
        r"add_wrapper(?:_with_key)?\s*\(",
        r"WrapperExecutor",
    ),
    "uses_callbacks": (
        r"\bCallbacksMP\b",
        r"add_callback(?:_with_key)?\s*\(",
        r"prepare_callback\s*\(",
    ),
    "uses_sampler_api": (
        r"comfy\.samplers",
        r"comfy\.sample",
        r"common_ksampler",
        r"sample_custom",
        r"\bKSampler\b",
        r"sampler_helpers",
        r"calculate_sigmas",
    ),
    "uses_sampler_execution": (
        r"\bcommon_ksampler\b",
        r"\bsample_custom\b",
        r"\bcomfy\.sample\.sample\b",
        r"\bcomfy\.samplers\.KSampler\b",
        r"\bk_?sampler\.sample\b",
    ),
    "uses_apply_model": (r"\.apply_model\s*\(", r"APPLY_MODEL", r"DIFFUSION_MODEL"),
    "uses_controlnet": (
        r"\bControlNet\b",
        r"CONTROL_NET",
        r"controlnet",
        r"control_net",
        r"T2IAdapter",
        r"t2i_adapter",
    ),
    "uses_ipadapter": (r"IPAdapter", r"ip_adapter", r"ipadapter", r"InstantID", r"PuLID"),
    "uses_lora": (r"\bLoRA\b", r"\blora\b", r"LyCORIS", r"LoCon", r"load_lora"),
    "uses_detailer": (r"Detailer", r"detailer", r"FaceDetail", r"SEGSDetailer"),
    "uses_regional": (r"Regional", r"regional", r"attention_couple", r"AreaComposition"),
    "uses_tiled_diffusion": (r"TiledDiffusion", r"tiled_diffusion", r"MultiDiffusion", r"tile.*sampl"),
    "uses_qwen_image": (r"Qwen.?Image", r"qwen_image", r"QwenImage"),
    "uses_server_routes": (
        r"PromptServer\.instance\.routes",
        r"\broutes\.(?:get|post|put|delete)",
        r"aiohttp\.web",
    ),
    "uses_ws_messages": (r"send_sync\s*\(", r"api\.addEventListener\s*\(", r"WebSocket"),
    "frontend_extension": (
        r"app\.registerExtension\s*\(",
        r"registerExtension\s*\(",
        r"bottomPanelTabs",
        r"registerSidebarTab",
    ),
    "network_or_download_code": (
        r"\brequests\.(?:get|post|request)\s*\(",
        r"\bhttpx\.",
        r"urllib\.request",
        r"aiohttp\.ClientSession",
        r"snapshot_download",
        r"hf_hub_download",
        r"wget\b",
        r"curl\b",
    ),
    "subprocess_code": (
        r"subprocess\.(?:run|Popen|call|check_call|check_output)\s*\(",
        r"os\.system\s*\(",
        r"pip\s+install",
        r"git\s+clone",
    ),
}

COMPILED_FEATURE_PATTERNS = {
    key: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for key, patterns in FEATURE_PATTERNS.items()
}

PYTHON_RAW_RISK_FEATURES = {
    "network_or_download_code",
    "subprocess_code",
}
CALL_ONLY_FEATURES = {
    "uses_sampler_execution",
}
PYTHON_SEMANTIC_FEATURES = set(FEATURE_PATTERNS) - PYTHON_RAW_RISK_FEATURES - CALL_ONLY_FEATURES - {
    "frontend_extension",
}
FRONTEND_FEATURES = {
    "uses_ws_messages",
    "frontend_extension",
}
MONKEY_PATCH_ROOTS = {
    "comfy",
    "folder_paths",
    "nodes",
    "server",
    "sys",
    "torch",
}

UTILITY_NAME_PATTERNS = (
    "rgthree",
    "utils",
    "utility",
    "switch",
    "reroute",
    "math",
    "string",
    "workflow",
    "manager",
)

HIGH_PRIORITY_NAME_PATTERNS = (
    "controlnet",
    "ipadapter",
    "ip_adapter",
    "pulid",
    "instantid",
    "lora",
    "lycoris",
    "detailer",
    "regional",
    "tiled",
    "multidiffusion",
    "qwen",
    "sampler",
)


@dataclass(slots=True)
class ScanOptions:
    max_file_bytes: int = 2 * 1024 * 1024
    max_files_per_package: int = 5000
    follow_symlinks: bool = False
    include_tests: bool = False
    include_self: bool = False
    excluded_names: set[str] = field(default_factory=set)


@dataclass(slots=True)
class FileAnalysis:
    relative_path: str
    size: int
    sha256: str
    language: str
    parse_error: str | None = None
    node_mappings: dict[str, str] = field(default_factory=dict)
    display_mappings: dict[str, str] = field(default_factory=dict)
    dynamic_node_mapping: bool = False
    web_directories: list[str] = field(default_factory=list)
    comfy_types: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    function_names: set[str] = field(default_factory=set)
    class_names: set[str] = field(default_factory=set)
    imported_modules: set[str] = field(default_factory=set)
    call_names: set[str] = field(default_factory=set)
    feature_hits: dict[str, int] = field(default_factory=dict)
    monkey_patch_targets: set[str] = field(default_factory=set)


class InventoryError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def safe_read_text(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"stat failed: {exc}"
    if size > max_bytes:
        return None, f"skipped: file exceeds {max_bytes} bytes"
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace"), None
    except OSError as exc:
        return None, f"read failed: {exc}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _count_feature_hits(text: str, feature_names: Iterable[str]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for feature in feature_names:
        patterns = COMPILED_FEATURE_PATTERNS[feature]
        count = sum(len(pattern.findall(text)) for pattern in patterns)
        if count:
            hits[feature] = count
    return hits


def _node_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _node_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _node_name(node.func)
    if isinstance(node, ast.Subscript):
        return _node_name(node.value)
    return ""


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _known_type_reference(node: ast.AST | None) -> str | None:
    value = _literal_string(node)
    if value is not None:
        candidate = value.strip().upper()
        return candidate if candidate in KNOWN_COMFY_TYPES else None
    if isinstance(node, ast.Attribute):
        candidate = node.attr.upper()
        return candidate if candidate in KNOWN_COMFY_TYPES else None
    return None


def _extract_return_types(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    result: set[str] = set()
    for child in ast.walk(node):
        known_type = _known_type_reference(child)
        if known_type:
            result.add(known_type)
    return result


def _resolve_local_node(node: ast.AST | None, bindings: dict[str, ast.AST]) -> ast.AST | None:
    seen: set[str] = set()
    while isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        seen.add(node.id)
        node = bindings[node.id]
    return node


def _extract_input_types(node: ast.AST | None, bindings: dict[str, ast.AST]) -> set[str]:
    node = _resolve_local_node(node, bindings)
    if not isinstance(node, ast.Dict):
        return set()

    result: set[str] = set()
    for section_key, section_value in zip(node.keys, node.values):
        section = _literal_string(section_key)
        if section not in {"required", "optional", "hidden"}:
            continue
        section_value = _resolve_local_node(section_value, bindings)
        if not isinstance(section_value, ast.Dict):
            continue
        for field_spec in section_value.values:
            field_spec = _resolve_local_node(field_spec, bindings)
            if not isinstance(field_spec, (ast.Tuple, ast.List)) or not field_spec.elts:
                continue
            declared_type = _known_type_reference(
                _resolve_local_node(field_spec.elts[0], bindings)
            )
            if declared_type:
                result.add(declared_type)
    return result


def _extract_input_types_from_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    bindings: dict[str, ast.AST] = {}
    for statement in node.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
            continue
        for target in _collect_assignment_targets(statement):
            if isinstance(target, ast.Name):
                bindings[target.id] = statement.value

    result: set[str] = set()
    for statement in ast.walk(node):
        if isinstance(statement, ast.Return):
            result.update(_extract_input_types(statement.value, bindings))
    return result


def _mapping_from_ast(value: ast.AST) -> tuple[dict[str, str], bool]:
    result: dict[str, str] = {}
    dynamic = False
    if not isinstance(value, ast.Dict):
        return result, True
    for key_node, value_node in zip(value.keys, value.values):
        key = _literal_string(key_node)
        if key is None:
            dynamic = True
            continue
        value_name = _node_name(value_node)
        if not value_name:
            literal = _literal_string(value_node)
            value_name = literal or "<dynamic>"
            dynamic = dynamic or value_name == "<dynamic>"
        result[key] = value_name
    return result, dynamic


def _collect_assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    return [node.target]


def _analyse_python(path: Path, relative_path: str, text: str, size: int) -> FileAnalysis:
    analysis = FileAnalysis(
        relative_path=relative_path,
        size=size,
        sha256=sha256_bytes(text.encode("utf-8", errors="replace")),
        language="python",
    )
    analysis.feature_hits.update(_count_feature_hits(text, PYTHON_RAW_RISK_FEATURES))

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        analysis.parse_error = f"{exc.msg} at line {exc.lineno}"
        return analysis

    semantic_symbols: set[str] = set()
    for top in tree.body:
        if isinstance(top, ast.Import):
            for alias in top.names:
                analysis.imported_modules.add(alias.name)
                semantic_symbols.add(alias.name)
                semantic_symbols.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(top, ast.ImportFrom):
            module = top.module or ""
            if module:
                analysis.imported_modules.add(module)
                semantic_symbols.add(module)
            for alias in top.names:
                semantic_symbols.add(alias.name)
                semantic_symbols.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            semantic_symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            name = _node_name(node)
            if name:
                semantic_symbols.add(name)

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if 0 < len(value) <= 160 and (
                value.startswith("ComfyUI/") or value.startswith("image/") or value.startswith("sampling/")
            ):
                analysis.categories.add(value)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            analysis.function_names.add(node.name)
            semantic_symbols.add(node.name)
            if node.name == "INPUT_TYPES":
                analysis.comfy_types.update(_extract_input_types_from_function(node))
        elif isinstance(node, ast.ClassDef):
            analysis.class_names.add(node.name)
            semantic_symbols.add(node.name)
        elif isinstance(node, ast.Call):
            name = _node_name(node.func)
            if name:
                analysis.call_names.add(name)
                semantic_symbols.add(name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            for target in _collect_assignment_targets(node):
                if isinstance(target, ast.Name):
                    if target.id == "NODE_CLASS_MAPPINGS" and value is not None:
                        mapping, dynamic = _mapping_from_ast(value)
                        analysis.node_mappings.update(mapping)
                        analysis.dynamic_node_mapping |= dynamic
                    elif target.id == "NODE_DISPLAY_NAME_MAPPINGS" and value is not None:
                        mapping, dynamic = _mapping_from_ast(value)
                        analysis.display_mappings.update(mapping)
                        analysis.dynamic_node_mapping |= dynamic
                    elif target.id == "WEB_DIRECTORY" and value is not None:
                        web_dir = _literal_string(value)
                        if web_dir:
                            analysis.web_directories.append(web_dir)
                    elif target.id == "RETURN_TYPES":
                        analysis.comfy_types.update(_extract_return_types(value))
                    elif target.id == "INPUT_TYPES":
                        analysis.comfy_types.update(_extract_input_types(value, {}))
                elif isinstance(target, ast.Attribute):
                    target_name = _node_name(target)
                    root = target_name.split(".", 1)[0]
                    if target.attr == "RETURN_TYPES":
                        analysis.comfy_types.update(_extract_return_types(value))
                    elif target.attr == "INPUT_TYPES":
                        analysis.comfy_types.update(_extract_input_types(value, {}))
                    if root in MONKEY_PATCH_ROOTS:
                        analysis.monkey_patch_targets.add(target_name)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
            target_name = _node_name(node.target)
            root = target_name.split(".", 1)[0]
            if root in MONKEY_PATCH_ROOTS:
                analysis.monkey_patch_targets.add(target_name)

    # NODE_CLASS_MAPPINGS.update({...}) and similar patterns.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = _node_name(node.func.value)
        if node.func.attr != "update" or owner not in {"NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"}:
            continue
        if not node.args:
            analysis.dynamic_node_mapping = True
            continue
        mapping, dynamic = _mapping_from_ast(node.args[0])
        if owner == "NODE_CLASS_MAPPINGS":
            analysis.node_mappings.update(mapping)
        else:
            analysis.display_mappings.update(mapping)
        analysis.dynamic_node_mapping |= dynamic

    semantic_text = "\n".join(sorted(semantic_symbols))
    analysis.feature_hits.update(
        _count_feature_hits(semantic_text, PYTHON_SEMANTIC_FEATURES)
    )
    call_text = "\n".join(sorted(analysis.call_names))
    analysis.feature_hits.update(_count_feature_hits(call_text, CALL_ONLY_FEATURES))

    if analysis.monkey_patch_targets:
        analysis.feature_hits["monkey_patch_suspected"] = len(analysis.monkey_patch_targets)
    if analysis.web_directories:
        analysis.feature_hits["frontend_extension"] = max(
            1, analysis.feature_hits.get("frontend_extension", 0)
        )
    return analysis


def _analyse_frontend(relative_path: str, text: str, size: int) -> FileAnalysis:
    analysis = FileAnalysis(
        relative_path=relative_path,
        size=size,
        sha256=sha256_bytes(text.encode("utf-8", errors="replace")),
        language="frontend",
    )
    analysis.feature_hits.update(_count_feature_hits(text, FRONTEND_FEATURES))
    return analysis


def _iter_package_files(package_path: Path, options: ScanOptions) -> Iterator[Path]:
    seen = 0
    for root, dirs, files in os.walk(package_path, followlinks=options.follow_symlinks):
        root_path = Path(root)
        filtered_dirs: list[str] = []
        for directory in dirs:
            lowered = directory.lower()
            optional_auxiliary = bool(OPTIONAL_AUXILIARY_DIR_PATTERN.search(lowered))
            if lowered in DEFAULT_SKIP_DIRS or optional_auxiliary:
                if options.include_tests and optional_auxiliary:
                    filtered_dirs.append(directory)
                continue
            filtered_dirs.append(directory)
        dirs[:] = filtered_dirs

        for filename in files:
            if seen >= options.max_files_per_package:
                return
            path = root_path / filename
            suffix = path.suffix.lower()
            if suffix not in SOURCE_SUFFIXES and path.name.lower() not in MANIFEST_NAMES:
                continue
            if path.is_symlink() and not options.follow_symlinks:
                continue
            seen += 1
            yield path


def _resolve_git_dir(package_path: Path) -> Path | None:
    marker = package_path / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        text, _ = safe_read_text(marker, 64 * 1024)
        if text:
            match = re.match(r"gitdir:\s*(.+)", text.strip(), re.IGNORECASE)
            if match:
                target = Path(match.group(1).strip())
                if not target.is_absolute():
                    target = (package_path / target).resolve()
                if target.exists():
                    return target
    return None


def _read_git_metadata(package_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "is_git_checkout": False,
        "remote_origin": None,
        "commit": None,
        "branch": None,
    }
    git_dir = _resolve_git_dir(package_path)
    if git_dir is None:
        return result
    result["is_git_checkout"] = True

    config_path = git_dir / "config"
    if config_path.exists():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(config_path, encoding="utf-8")
            if parser.has_section('remote "origin"'):
                result["remote_origin"] = parser.get('remote "origin"', "url", fallback=None)
        except (configparser.Error, OSError):
            pass

    head_text, _ = safe_read_text(git_dir / "HEAD", 64 * 1024)
    if head_text:
        head = head_text.strip()
        if head.startswith("ref:"):
            ref_name = head.split(":", 1)[1].strip()
            result["branch"] = ref_name.removeprefix("refs/heads/")
            ref_path = git_dir / ref_name
            ref_text, _ = safe_read_text(ref_path, 64 * 1024)
            if ref_text:
                result["commit"] = ref_text.strip()
            else:
                packed_text, _ = safe_read_text(git_dir / "packed-refs", 4 * 1024 * 1024)
                if packed_text:
                    for line in packed_text.splitlines():
                        if line.startswith("#") or line.startswith("^"):
                            continue
                        parts = line.split(" ", 1)
                        if len(parts) == 2 and parts[1].strip() == ref_name:
                            result["commit"] = parts[0].strip()
                            break
        elif re.fullmatch(r"[0-9a-fA-F]{7,64}", head):
            result["commit"] = head
    return result


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        import tomllib as toml_reader  # Python 3.11+
    except ImportError:
        try:
            import tomli as toml_reader  # type: ignore[import-not-found]
        except ImportError:
            return None
    try:
        with path.open("rb") as handle:
            return toml_reader.load(handle)
    except (OSError, ValueError):
        return None


def _read_package_metadata(package_path: Path, options: ScanOptions) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "declared_name": None,
        "version": None,
        "repository": None,
        "dependencies": [],
        "manifest_files": [],
    }
    dependencies: set[str] = set()

    pyproject = package_path / "pyproject.toml"
    if pyproject.exists():
        metadata["manifest_files"].append("pyproject.toml")
        data = _load_toml(pyproject)
        if data:
            project = data.get("project", {}) if isinstance(data, dict) else {}
            if isinstance(project, dict):
                metadata["declared_name"] = project.get("name") or metadata["declared_name"]
                metadata["version"] = project.get("version") or metadata["version"]
                for dep in project.get("dependencies", []) or []:
                    if isinstance(dep, str):
                        dependencies.add(dep.strip())
                urls = project.get("urls", {})
                if isinstance(urls, dict):
                    metadata["repository"] = (
                        urls.get("Repository")
                        or urls.get("repository")
                        or urls.get("Homepage")
                        or metadata["repository"]
                    )
        else:
            text, _ = safe_read_text(pyproject, options.max_file_bytes)
            if text:
                project_match = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
                block = project_match.group(1) if project_match else text
                name_match = re.search(r"(?m)^name\s*=\s*[\"']([^\"']+)", block)
                version_match = re.search(r"(?m)^version\s*=\s*[\"']([^\"']+)", block)
                if name_match:
                    metadata["declared_name"] = name_match.group(1)
                if version_match:
                    metadata["version"] = version_match.group(1)
                dependency_match = re.search(
                    r"(?ms)^dependencies\s*=\s*\[(.*?)\]", block
                )
                if dependency_match:
                    dependencies.update(
                        match.group(1).strip()
                        for match in re.finditer(
                            r"[\"']([^\"']+)[\"']", dependency_match.group(1)
                        )
                    )
                urls_match = re.search(r"(?ms)^\[project\.urls\]\s*(.*?)(?=^\[|\Z)", text)
                if urls_match:
                    repository_match = re.search(
                        r"(?mi)^(?:Repository|Homepage)\s*=\s*[\"']([^\"']+)",
                        urls_match.group(1),
                    )
                    if repository_match:
                        metadata["repository"] = repository_match.group(1)

    package_json = package_path / "package.json"
    if package_json.exists():
        metadata["manifest_files"].append("package.json")
        text, _ = safe_read_text(package_json, options.max_file_bytes)
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                metadata["declared_name"] = data.get("name") or metadata["declared_name"]
                metadata["version"] = data.get("version") or metadata["version"]
                repo = data.get("repository")
                if isinstance(repo, dict):
                    repo = repo.get("url")
                if isinstance(repo, str):
                    metadata["repository"] = repo
                for section in ("dependencies", "optionalDependencies", "peerDependencies"):
                    values = data.get(section, {})
                    if isinstance(values, dict):
                        dependencies.update(f"{key}{value}" for key, value in values.items())

    comfy_manifest = package_path / "comfyui-node.json"
    if comfy_manifest.exists():
        metadata["manifest_files"].append("comfyui-node.json")
        text, _ = safe_read_text(comfy_manifest, options.max_file_bytes)
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                metadata["declared_name"] = (
                    data.get("name") or data.get("display_name") or metadata["declared_name"]
                )
                metadata["version"] = data.get("version") or metadata["version"]
                metadata["repository"] = (
                    data.get("repository") or data.get("project_url") or metadata["repository"]
                )

    requirement_names = (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_dev.txt",
    )
    for requirement_name in requirement_names:
        requirement_path = package_path / requirement_name
        if not requirement_path.exists():
            continue
        metadata["manifest_files"].append(requirement_name)
        text, _ = safe_read_text(requirement_path, options.max_file_bytes)
        if not text:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            dependencies.add(line)

    if metadata["version"] is None:
        for candidate in (package_path / "__init__.py", package_path / "version.py"):
            if not candidate.exists():
                continue
            text, _ = safe_read_text(candidate, options.max_file_bytes)
            if not text:
                continue
            version_match = re.search(
                r"(?m)^\s*(?:__version__|VERSION)\s*=\s*[\"']([^\"']+)", text
            )
            if version_match:
                metadata["version"] = version_match.group(1)
                break

    metadata["dependencies"] = sorted(dependencies, key=str.lower)
    metadata["manifest_files"] = sorted(set(metadata["manifest_files"]))
    return metadata


def _summarise_feature_hits(files: Sequence[FileAnalysis]) -> dict[str, dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    for feature in FEATURE_PATTERNS:
        count = sum(item.feature_hits.get(feature, 0) for item in files)
        paths = [item.relative_path for item in files if item.feature_hits.get(feature, 0)]
        aggregate[feature] = {
            "detected": count > 0,
            "hit_count": count,
            "files": paths[:20],
        }
    monkey_targets = sorted({target for item in files for target in item.monkey_patch_targets})
    aggregate["monkey_patch_suspected"] = {
        "detected": bool(monkey_targets),
        "hit_count": len(monkey_targets),
        "files": [item.relative_path for item in files if item.monkey_patch_targets][:20],
        "targets": monkey_targets[:50],
    }
    return aggregate


def _feature_detected(features: dict[str, dict[str, Any]], key: str) -> bool:
    return bool(features.get(key, {}).get("detected"))


def _runtime_monkey_patch_detected(features: dict[str, dict[str, Any]]) -> bool:
    targets = features.get("monkey_patch_suspected", {}).get("targets", [])
    for target in targets:
        lowered = str(target).lower()
        if lowered == "comfy" or lowered.startswith("comfy."):
            return True
        if lowered.startswith("nodes.") and any(
            signal in lowered for signal in ("sampl", "model", "cond", "control")
        ):
            return True
    return False


def _assess_package(
    folder_name: str,
    node_count: int,
    comfy_types: set[str],
    features: dict[str, dict[str, Any]],
    has_frontend_files: bool,
    dynamic_node_mapping: bool,
    parse_errors: int,
) -> dict[str, Any]:
    lowered_name = folder_name.lower()
    categories: list[str] = []

    sampler_replacement = _feature_detected(features, "uses_sampler_execution")
    lora_model_patch = _feature_detected(features, "uses_lora") and (
        "MODEL" in comfy_types or "lora" in lowered_name or "lycoris" in lowered_name
    )
    model_patching = (
        "MODEL" in comfy_types
        or _feature_detected(features, "uses_model_patcher")
        or _feature_detected(features, "uses_wrappers")
        or _feature_detected(features, "uses_ipadapter")
        or lora_model_patch
    )
    conditioning = (
        bool(comfy_types & {"CONDITIONING", "CONTROL_NET", "CONTROLNET"})
        or _feature_detected(features, "uses_controlnet")
        or _feature_detected(features, "uses_regional")
    )
    data_transform = bool(comfy_types & {"IMAGE", "LATENT", "MASK", "VAE", "CLIP", "CLIP_VISION"})
    frontend = has_frontend_files or _feature_detected(features, "frontend_extension")

    if data_transform:
        categories.append("Data Transform")
    if conditioning:
        categories.append("Conditioning")
    if model_patching:
        categories.append("Model Patching")
    if sampler_replacement:
        categories.append("Sampler/Pipeline Replacement")
    if frontend:
        categories.append("Frontend/Workflow Utility")
    if not categories:
        categories.append("Unclassified/Package Utility")

    primary_order = (
        "Sampler/Pipeline Replacement",
        "Model Patching",
        "Conditioning",
        "Data Transform",
        "Frontend/Workflow Utility",
        "Unclassified/Package Utility",
    )
    primary = next(category for category in primary_order if category in categories)

    monkey_patch = _feature_detected(features, "monkey_patch_suspected")
    runtime_monkey_patch = _runtime_monkey_patch_detected(features)
    deep_runtime = sampler_replacement or model_patching or conditioning
    control_family = _feature_detected(features, "uses_controlnet")
    ip_family = _feature_detected(features, "uses_ipadapter")
    lora_family = lora_model_patch
    detailer_pipeline = _feature_detected(features, "uses_detailer") and (
        bool(comfy_types & {"MODEL", "CONDITIONING", "LATENT", "SAMPLER", "SIGMAS"})
        or "detailer" in lowered_name
    )
    complex_pipeline = any(
        _feature_detected(features, key)
        for key in ("uses_regional", "uses_tiled_diffusion", "uses_qwen_image")
    ) or detailer_pipeline

    reasons: list[str] = []
    if sampler_replacement:
        reasons.append("Sampler 또는 sampling pipeline 호출이 감지됨")
    if model_patching:
        reasons.append("MODEL/ModelPatcher/transformer patch 관련 신호가 감지됨")
    if conditioning:
        reasons.append("CONDITIONING/ControlNet 계열 신호가 감지됨")
    if monkey_patch:
        reasons.append("외부 런타임 객체 속성 대입이 감지되어 monkey patch 가능성 있음")
    if runtime_monkey_patch:
        reasons.append("ComfyUI sampling/model 경로의 monkey patch 가능성 있음")
    if dynamic_node_mapping:
        reasons.append("NODE_CLASS_MAPPINGS를 완전히 정적으로 해석하지 못함")
    if parse_errors:
        reasons.append(f"Python parse error {parse_errors}개")
    if not reasons:
        reasons.append("범용 실행 이벤트와 입출력 Probe 중심으로 추적 가능")

    if sampler_replacement or runtime_monkey_patch:
        adapter_need = "required"
        difficulty = "high"
    elif control_family or ip_family or lora_family or complex_pipeline or model_patching:
        adapter_need = "recommended"
        difficulty = "medium"
    elif conditioning:
        adapter_need = "recommended"
        difficulty = "medium"
    elif parse_errors or dynamic_node_mapping:
        adapter_need = "manual_review"
        difficulty = "medium"
    else:
        adapter_need = "not_needed"
        difficulty = "low"

    name_priority = any(pattern in lowered_name for pattern in HIGH_PRIORITY_NAME_PATTERNS)
    if sampler_replacement or model_patching or conditioning or complex_pipeline or name_priority:
        priority = "A"
    elif data_transform or bool(comfy_types & {"BBOX_DETECTOR", "SEGM_DETECTOR", "SAM_MODEL", "UPSCALE_MODEL"}):
        priority = "B"
    elif frontend or any(pattern in lowered_name for pattern in UTILITY_NAME_PATTERNS):
        priority = "C"
    else:
        priority = "B" if node_count else "C"

    hook_points: list[str] = ["WebSocket execution events"]
    if data_transform:
        hook_points.append("Generic input/output probe")
    if conditioning:
        hook_points.extend(["Conditioning snapshot", "CALC_COND_BATCH"])
    if control_family:
        hook_points.append("APPLY_MODEL control residual")
    if model_patching:
        hook_points.extend(["ModelPatcher snapshot", "APPLY_MODEL", "DIFFUSION_MODEL"])
    if sampler_replacement:
        hook_points.extend(["OUTER_SAMPLE", "SAMPLER_SAMPLE", "sampling callback"])
    if frontend:
        hook_points.append("Frontend extension events")

    if adapter_need == "required":
        coverage = "generic trace only until a dedicated adapter is validated"
    elif adapter_need == "recommended":
        coverage = "generic trace + standard runtime hooks; semantic adapter recommended"
    elif adapter_need == "manual_review":
        coverage = "partial static result; manual source review required"
    else:
        coverage = "generic trace expected to be sufficient"

    return {
        "categories": categories,
        "primary_category": primary,
        "generic_trace": True,
        "runtime_hook_required": deep_runtime,
        "dedicated_adapter": adapter_need,
        "trace_difficulty": difficulty,
        "priority": priority,
        "current_coverage": coverage,
        "recommended_hook_points": list(dict.fromkeys(hook_points)),
        "reasons": reasons,
    }


def _scan_loose_python_file(path: Path, root: Path, options: ScanOptions) -> dict[str, Any]:
    return _scan_package(path, root, options, is_loose_file=True)


def _scan_package(
    package_path: Path,
    root: Path,
    options: ScanOptions,
    *,
    is_loose_file: bool = False,
) -> dict[str, Any]:
    folder_name = package_path.stem if is_loose_file else package_path.name
    file_analyses: list[FileAnalysis] = []
    skipped_files: list[dict[str, str]] = []

    files: Iterable[Path]
    if is_loose_file:
        files = [package_path]
    else:
        files = _iter_package_files(package_path, options)

    fingerprint = hashlib.sha256()
    source_file_count = 0
    frontend_file_count = 0
    total_source_bytes = 0

    for path in files:
        try:
            relative = path.relative_to(package_path if not is_loose_file else root).as_posix()
        except ValueError:
            relative = path.name
        text, error = safe_read_text(path, options.max_file_bytes)
        if text is None:
            skipped_files.append({"path": relative, "reason": error or "unknown"})
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = len(text.encode("utf-8", errors="replace"))
        fingerprint.update(relative.encode("utf-8", errors="replace"))
        fingerprint.update(b"\0")
        fingerprint.update(text.encode("utf-8", errors="replace"))
        fingerprint.update(b"\0")

        suffix = path.suffix.lower()
        if suffix in {".py", ".pyi"}:
            analysis = _analyse_python(path, relative, text, size)
            source_file_count += 1
        elif suffix in SOURCE_SUFFIXES:
            analysis = _analyse_frontend(relative, text, size)
            source_file_count += 1
            frontend_file_count += 1
        else:
            continue
        total_source_bytes += size
        file_analyses.append(analysis)

    node_mappings: dict[str, str] = {}
    display_mappings: dict[str, str] = {}
    dynamic_node_mapping = False
    web_directories: set[str] = set()
    comfy_types: set[str] = set()
    class_names: set[str] = set()
    function_names: set[str] = set()
    imports: set[str] = set()
    categories: set[str] = set()
    parse_errors: list[dict[str, str]] = []

    for item in file_analyses:
        node_mappings.update(item.node_mappings)
        display_mappings.update(item.display_mappings)
        dynamic_node_mapping |= item.dynamic_node_mapping
        web_directories.update(item.web_directories)
        comfy_types.update(item.comfy_types)
        class_names.update(item.class_names)
        function_names.update(item.function_names)
        imports.update(item.imported_modules)
        categories.update(item.categories)
        if item.parse_error:
            parse_errors.append({"path": item.relative_path, "error": item.parse_error})

    features = _summarise_feature_hits(file_analyses)
    has_frontend_files = frontend_file_count > 0 or bool(web_directories)
    assessment = _assess_package(
        folder_name,
        len(node_mappings),
        comfy_types,
        features,
        has_frontend_files,
        dynamic_node_mapping,
        len(parse_errors),
    )

    metadata = (
        {
            "declared_name": None,
            "version": None,
            "repository": None,
            "dependencies": [],
            "manifest_files": [],
        }
        if is_loose_file
        else _read_package_metadata(package_path, options)
    )
    git = (
        {
            "is_git_checkout": False,
            "remote_origin": None,
            "commit": None,
            "branch": None,
        }
        if is_loose_file
        else _read_git_metadata(package_path)
    )
    repository = git.get("remote_origin") or metadata.get("repository")

    return {
        "package_id": normalise_name(metadata.get("declared_name") or folder_name),
        "folder_name": folder_name,
        "relative_path": package_path.relative_to(root).as_posix(),
        "absolute_path": str(package_path.resolve()),
        "is_loose_python_file": is_loose_file,
        "is_symlink": package_path.is_symlink(),
        "likely_disabled": "disabled" in folder_name.lower(),
        "declared_name": metadata.get("declared_name"),
        "version": metadata.get("version"),
        "repository": repository,
        "git": git,
        "manifest_files": metadata.get("manifest_files", []),
        "dependencies": metadata.get("dependencies", []),
        "node_count_static": len(node_mappings),
        "node_mappings": dict(sorted(node_mappings.items(), key=lambda item: item[0].lower())),
        "display_mappings": dict(sorted(display_mappings.items(), key=lambda item: item[0].lower())),
        "dynamic_node_mapping": dynamic_node_mapping,
        "web_directories": sorted(web_directories),
        "comfy_types": sorted(comfy_types),
        "declared_categories": sorted(categories),
        "class_names": sorted(class_names)[:500],
        "function_names": sorted(function_names)[:500],
        "imported_modules": sorted(imports)[:500],
        "features": features,
        "assessment": assessment,
        "source_file_count": source_file_count,
        "frontend_file_count": frontend_file_count,
        "total_source_bytes": total_source_bytes,
        "source_fingerprint_sha256": fingerprint.hexdigest(),
        "parse_errors": parse_errors,
        "skipped_files": skipped_files,
        "analysed_files": [
            {
                "path": item.relative_path,
                "size": item.size,
                "sha256": item.sha256,
                "language": item.language,
                "parse_error": item.parse_error,
                "feature_hits": item.feature_hits,
            }
            for item in file_analyses
        ],
    }


def resolve_custom_nodes_path(
    *,
    comfy_root: Path | None = None,
    custom_nodes: Path | None = None,
) -> Path:
    if custom_nodes is not None:
        candidate = custom_nodes.expanduser().resolve()
        if not candidate.is_dir():
            raise InventoryError(f"custom_nodes directory not found: {candidate}")
        return candidate

    if comfy_root is None:
        raise InventoryError("either --comfy-root or --custom-nodes is required")

    root = comfy_root.expanduser().resolve()
    candidates = [
        root if root.name.lower() == "custom_nodes" else root / "custom_nodes",
        root / "ComfyUI" / "custom_nodes",
        root / "comfyui" / "custom_nodes",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    formatted = "\n".join(f"- {candidate}" for candidate in candidates)
    raise InventoryError(f"custom_nodes directory not found. Checked:\n{formatted}")


def _previous_packages(previous: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not previous:
        return {}
    packages = previous.get("packages", [])
    if not isinstance(packages, list):
        return {}
    return {
        str(item.get("package_id")): item
        for item in packages
        if isinstance(item, dict) and item.get("package_id")
    }


def _calculate_diff(packages: Sequence[dict[str, Any]], previous: dict[str, Any] | None) -> dict[str, Any]:
    prior = _previous_packages(previous)
    current = {item["package_id"]: item for item in packages}
    added = sorted(set(current) - set(prior))
    removed = sorted(set(prior) - set(current))
    changed: list[str] = []
    unchanged: list[str] = []
    for package_id in sorted(set(current) & set(prior)):
        before = prior[package_id].get("source_fingerprint_sha256")
        after = current[package_id].get("source_fingerprint_sha256")
        if before and after and before == after:
            unchanged.append(package_id)
        else:
            changed.append(package_id)
    return {
        "has_previous": bool(previous),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def scan_custom_nodes(
    custom_nodes_path: Path,
    *,
    options: ScanOptions | None = None,
    previous_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or ScanOptions()
    root = custom_nodes_path.expanduser().resolve()
    if not root.is_dir():
        raise InventoryError(f"custom_nodes directory not found: {root}")

    excluded = {normalise_name(name) for name in options.excluded_names}
    packages: list[dict[str, Any]] = []
    scan_errors: list[dict[str, str]] = []
    skipped_entries: list[dict[str, str]] = []

    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_symlink() and not options.follow_symlinks:
            skipped_entries.append({"path": str(entry), "reason": "symlink skipped; rerun with --follow-symlinks"})
            continue
        normalised = normalise_name(entry.stem if entry.is_file() else entry.name)
        if normalised in excluded:
            continue
        if not options.include_self and normalised in SELF_PACKAGE_NAMES:
            continue
        try:
            if entry.is_dir():
                packages.append(_scan_package(entry, root, options))
            elif entry.is_file() and entry.suffix.lower() == ".py" and entry.name != "__init__.py":
                packages.append(_scan_loose_python_file(entry, root, options))
        except Exception as exc:  # keep one bad package from stopping the inventory
            scan_errors.append({"path": str(entry), "error": f"{type(exc).__name__}: {exc}"})

    priority_counts = Counter(item["assessment"]["priority"] for item in packages)
    category_counts = Counter(item["assessment"]["primary_category"] for item in packages)
    adapter_counts = Counter(item["assessment"]["dedicated_adapter"] for item in packages)
    static_nodes = sum(item["node_count_static"] for item in packages)
    parse_error_count = sum(len(item.get("parse_errors", [])) for item in packages)
    packages_with_parse_errors = sum(bool(item.get("parse_errors")) for item in packages)

    inventory = {
        "schema_version": SCHEMA_VERSION,
        "scanner_version": SCANNER_VERSION,
        "generated_at": utc_now_iso(),
        "scan_mode": "static_only_no_import_no_execution",
        "custom_nodes_path": str(root),
        "safety": {
            "imports_scanned_packages": False,
            "executes_scanned_code": False,
            "installs_dependencies": False,
            "uses_network": False,
            "follows_symlinks": options.follow_symlinks,
            "notes": "Heuristic source analysis only; runtime behaviour must be validated separately.",
        },
        "options": {
            "max_file_bytes": options.max_file_bytes,
            "max_files_per_package": options.max_files_per_package,
            "follow_symlinks": options.follow_symlinks,
            "include_tests": options.include_tests,
            "include_self": options.include_self,
            "excluded_names": sorted(options.excluded_names),
        },
        "summary": {
            "package_count": len(packages),
            "static_node_count": static_nodes,
            "priority_counts": dict(sorted(priority_counts.items())),
            "primary_category_counts": dict(sorted(category_counts.items())),
            "adapter_need_counts": dict(sorted(adapter_counts.items())),
            "scan_error_count": len(scan_errors),
            "parse_error_count": parse_error_count,
            "packages_with_parse_errors": packages_with_parse_errors,
            "skipped_entry_count": len(skipped_entries),
        },
        "diff": _calculate_diff(packages, previous_inventory),
        "packages": packages,
        "scan_errors": scan_errors,
        "skipped_entries": skipped_entries,
    }
    return inventory


def _md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _short_commit(package: dict[str, Any]) -> str:
    commit = package.get("git", {}).get("commit")
    return str(commit)[:10] if commit else "-"


def _risk_flags(package: dict[str, Any]) -> list[str]:
    features = package.get("features", {})
    flags: list[str] = []
    if _feature_detected(features, "monkey_patch_suspected"):
        flags.append("MonkeyPatch?")
    if _feature_detected(features, "network_or_download_code"):
        flags.append("Network/Download")
    if _feature_detected(features, "subprocess_code"):
        flags.append("Subprocess")
    if package.get("parse_errors"):
        flags.append("ParseError")
    if package.get("dynamic_node_mapping"):
        flags.append("DynamicMapping")
    return flags


def render_inventory_markdown(inventory: dict[str, Any]) -> str:
    summary = inventory["summary"]
    lines = [
        "# Custom Node Inventory",
        "",
        f"- Generated: `{inventory['generated_at']}`",
        f"- Scanner: `{inventory['scanner_version']}`",
        f"- Path: `{inventory['custom_nodes_path']}`",
        f"- Packages: **{summary['package_count']}**",
        f"- Statically extracted node mappings: **{summary['static_node_count']}**",
        f"- Scan errors: **{summary['scan_error_count']}**",
        f"- Parse errors: **{summary.get('parse_error_count', 0)}**",
        f"- Skipped entries: **{summary.get('skipped_entry_count', 0)}**",
        "",
        "> Static-only scan: packages were not imported or executed; dependencies were not installed; no network requests were made.",
        "",
    ]

    diff = inventory.get("diff", {})
    if diff.get("has_previous"):
        lines.extend(
            [
                "## Changes Since Previous Inventory",
                "",
                f"- Added: {', '.join(diff['added']) or '-'}",
                f"- Removed: {', '.join(diff['removed']) or '-'}",
                f"- Changed: {', '.join(diff['changed']) or '-'}",
                f"- Unchanged: {len(diff['unchanged'])}",
                "",
            ]
        )

    lines.extend(
        [
            "## Package Summary",
            "",
            "| Package | Nodes | Primary category | Priority | Adapter | Difficulty | Commit | Risk flags |",
            "|---|---:|---|:---:|---|---|---|---|",
        ]
    )
    for package in inventory["packages"]:
        assessment = package["assessment"]
        flags = ", ".join(_risk_flags(package)) or "-"
        lines.append(
            "| {name} | {nodes} | {category} | {priority} | {adapter} | {difficulty} | {commit} | {flags} |".format(
                name=_md_escape(package["folder_name"]),
                nodes=package["node_count_static"],
                category=_md_escape(assessment["primary_category"]),
                priority=assessment["priority"],
                adapter=_md_escape(assessment["dedicated_adapter"]),
                difficulty=_md_escape(assessment["trace_difficulty"]),
                commit=_short_commit(package),
                flags=_md_escape(flags),
            )
        )

    lines.extend(["", "## Package Details", ""])
    for package in inventory["packages"]:
        assessment = package["assessment"]
        lines.extend(
            [
                f"### {package['folder_name']}",
                "",
                f"- Path: `{package['relative_path']}`",
                f"- Declared name/version: `{package.get('declared_name') or '-'} / {package.get('version') or '-'}`",
                f"- Repository: `{package.get('repository') or '-'}`",
                f"- Static nodes: **{package['node_count_static']}**",
                f"- Types: {', '.join(package['comfy_types']) or '-'}",
                f"- Categories: {', '.join(assessment['categories'])}",
                f"- Trace: {assessment['current_coverage']}",
                f"- Recommended hooks: {', '.join(assessment['recommended_hook_points'])}",
                f"- Reasons: {'; '.join(assessment['reasons'])}",
            ]
        )
        if package["node_mappings"]:
            mapping_preview = list(package["node_mappings"].items())[:25]
            lines.append("- Node mappings:")
            for node_name, class_name in mapping_preview:
                lines.append(f"  - `{node_name}` → `{class_name}`")
            remaining = len(package["node_mappings"]) - len(mapping_preview)
            if remaining > 0:
                lines.append(f"  - ... and {remaining} more")
        risk = _risk_flags(package)
        if risk:
            lines.append(f"- Review flags: {', '.join(risk)}")
        lines.append("")

    if inventory.get("scan_errors"):
        lines.extend(["## Scan Errors", ""])
        for item in inventory["scan_errors"]:
            lines.append(f"- `{item['path']}` — {item['error']}")
        lines.append("")

    parse_errors = [
        (f"{package['relative_path']}/{item['path']}", item["error"])
        for package in inventory["packages"]
        for item in package.get("parse_errors", [])
    ]
    if parse_errors:
        lines.extend(["## Parse Errors", ""])
        for path, error in parse_errors:
            lines.append(f"- `{path}` — {error}")
        lines.append("")

    if inventory.get("skipped_entries"):
        lines.extend(["## Skipped Entries", ""])
        for item in inventory["skipped_entries"]:
            lines.append(f"- `{item['path']}` — {item['reason']}")
        lines.append("")

    lines.extend(
        [
            "## Interpretation Boundary",
            "",
            "- A detected symbol means source code contains that signal; it does not prove the path executes in the user's workflow.",
            "- Dynamic mappings, generated code, compiled extensions, and runtime monkey patches require manual or runtime validation.",
            "- Priority A means inspect first because the package can alter conditioning/model/sampling, not that it is unsafe.",
            "",
        ]
    )
    return "\n".join(lines)


def render_compatibility_matrix(inventory: dict[str, Any]) -> str:
    lines = [
        "# Trace Compatibility Matrix",
        "",
        "> This matrix is generated from static evidence. Runtime validation remains mandatory.",
        "",
        "| Package | Generic trace | Runtime hook | Dedicated adapter | Coverage | Recommended hook points |",
        "|---|:---:|:---:|---|---|---|",
    ]
    for package in inventory["packages"]:
        assessment = package["assessment"]
        lines.append(
            "| {name} | {generic} | {runtime} | {adapter} | {coverage} | {hooks} |".format(
                name=_md_escape(package["folder_name"]),
                generic=_yes_no(assessment["generic_trace"]),
                runtime=_yes_no(assessment["runtime_hook_required"]),
                adapter=_md_escape(assessment["dedicated_adapter"]),
                coverage=_md_escape(assessment["current_coverage"]),
                hooks=_md_escape(", ".join(assessment["recommended_hook_points"])),
            )
        )
    lines.extend(
        [
            "",
            "## Status Meanings",
            "",
            "- `not_needed`: generic execution/input-output tracing is expected to be enough.",
            "- `recommended`: standard hooks should observe some behaviour, but a semantic adapter improves interpretation.",
            "- `required`: a custom sampler/pipeline or invasive patch likely bypasses standard assumptions.",
            "- `manual_review`: static extraction was incomplete or source parsing failed.",
            "",
        ]
    )
    return "\n".join(lines)


def render_adapter_priority(inventory: dict[str, Any]) -> str:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for package in inventory["packages"]:
        groups[package["assessment"]["priority"]].append(package)

    lines = [
        "# Adapter Priority",
        "",
        "Priority is based on how directly a package can change Conditioning (생성 조건), MODEL patches, or Sampling (샘플링) rather than package popularity.",
        "",
    ]
    descriptions = {
        "A": "Inspect and validate before full Sampling Trace Inspector rollout.",
        "B": "Generic trace first; add adapters when the workflow needs deeper meaning.",
        "C": "Execution/cache/branch visibility is usually sufficient.",
    }
    for priority in ("A", "B", "C"):
        lines.extend([f"## Priority {priority}", "", descriptions[priority], ""])
        packages = sorted(groups.get(priority, []), key=lambda item: item["folder_name"].lower())
        if not packages:
            lines.extend(["- None", ""])
            continue
        for package in packages:
            assessment = package["assessment"]
            hooks = ", ".join(assessment["recommended_hook_points"])
            lines.extend(
                [
                    f"### {package['folder_name']}",
                    "",
                    f"- Primary: {assessment['primary_category']}",
                    f"- Adapter: `{assessment['dedicated_adapter']}`",
                    f"- Hooks: {hooks}",
                    f"- Why: {'; '.join(assessment['reasons'])}",
                    "- Codex task:",
                    "  1. Confirm which detected code paths execute in an actual workflow.",
                    "  2. Record patch/control/sampler keys without modifying output.",
                    "  3. Add a package-specific adapter only when generic runtime hooks are insufficient.",
                    "  4. Add Trace On/Off identity and performance tests.",
                    "",
                ]
            )
    return "\n".join(lines)


def render_local_adapter_plan(inventory: dict[str, Any]) -> str:
    priority_a = [
        package
        for package in inventory["packages"]
        if package["assessment"]["priority"] == "A"
    ]
    lines = [
        "# Local Adapter Plan",
        "",
        "> Generated skeleton. Codex must confirm actual workflow usage and runtime evidence before implementing adapters.",
        "",
        f"- Inventory generated: `{inventory['generated_at']}`",
        f"- Custom nodes path: `{inventory['custom_nodes_path']}`",
        f"- Priority A packages: **{len(priority_a)}**",
        "",
        "| Package | Installed commit | Static classification | Actual workflow usage | Generic coverage | Missing signal | Adapter task | Test workflow |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for package in sorted(priority_a, key=lambda item: item["folder_name"].lower()):
        assessment = package["assessment"]
        lines.append(
            "| {name} | {commit} | {classification} | TODO | {coverage} | TODO | TODO after runtime check | TODO |".format(
                name=_md_escape(package["folder_name"]),
                commit=_short_commit(package),
                classification=_md_escape(assessment["primary_category"]),
                coverage=_md_escape(assessment["current_coverage"]),
            )
        )
    if not priority_a:
        lines.append("| - | - | No Priority A package detected | TODO | - | - | - | - |")
    lines.extend(
        [
            "",
            "## Review Checklist",
            "",
            "- [ ] Confirm which packages are actually used in the user's active workflows.",
            "- [ ] Confirm installed commit/source fingerprint before runtime testing.",
            "- [ ] Identify standard wrapper signals already visible without a dedicated adapter.",
            "- [ ] Record the exact missing signal for each adapter candidate.",
            "- [ ] Define one minimal workflow per package.",
            "- [ ] Verify Trace On/Off output identity.",
            "- [ ] Measure Basic/Advanced (`persist_tensor_stats` Off/On) overhead.",
            "- [ ] Keep unused Priority A packages on generic fallback instead of implementing speculative adapters.",
            "",
            "## Decision Log",
            "",
            "| Package | Decision | Evidence | Keep / Reject / Defer |",
            "|---|---|---|---|",
            "| | | | |",
            "",
        ]
    )
    return "\n".join(lines)


def write_inventory_reports(inventory: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": output_dir / "CUSTOM_NODE_INVENTORY.json",
        "inventory_markdown": output_dir / "CUSTOM_NODE_INVENTORY.md",
        "compatibility_matrix": output_dir / "TRACE_COMPATIBILITY_MATRIX.md",
        "adapter_priority": output_dir / "ADAPTER_PRIORITY.md",
        "local_adapter_plan": output_dir / "LOCAL_ADAPTER_PLAN.md",
    }
    outputs["json"].write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    outputs["inventory_markdown"].write_text(render_inventory_markdown(inventory), encoding="utf-8")
    outputs["compatibility_matrix"].write_text(render_compatibility_matrix(inventory), encoding="utf-8")
    outputs["adapter_priority"].write_text(render_adapter_priority(inventory), encoding="utf-8")
    outputs["local_adapter_plan"].write_text(render_local_adapter_plan(inventory), encoding="utf-8")
    return {key: str(path) for key, path in outputs.items()}


def load_previous_inventory(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"failed to read previous inventory {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InventoryError("previous inventory must contain a JSON object")
    return data


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Statically inventory installed ComfyUI custom nodes without importing them."
    )
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--comfy-root", type=Path, help="ComfyUI root or portable root")
    location.add_argument("--custom-nodes", type=Path, help="Direct path to custom_nodes")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--previous-json", type=Path)
    parser.add_argument("--exclude", action="append", default=[], help="Folder/package name to exclude")
    parser.add_argument("--include-self", action="store_true")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--follow-symlinks", action="store_true")
    parser.add_argument("--max-file-mib", type=float, default=2.0)
    parser.add_argument("--max-files-per-package", type=int, default=5000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        custom_nodes_path = resolve_custom_nodes_path(
            comfy_root=args.comfy_root,
            custom_nodes=args.custom_nodes,
        )
        previous = load_previous_inventory(args.previous_json)
        options = ScanOptions(
            max_file_bytes=max(1, int(args.max_file_mib * 1024 * 1024)),
            max_files_per_package=max(1, args.max_files_per_package),
            follow_symlinks=args.follow_symlinks,
            include_tests=args.include_tests,
            include_self=args.include_self,
            excluded_names=set(args.exclude),
        )
        inventory = scan_custom_nodes(
            custom_nodes_path,
            options=options,
            previous_inventory=previous,
        )
        outputs = write_inventory_reports(inventory, args.output_dir)
    except InventoryError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"filesystem error: {exc}"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    print(
        json.dumps(
            {
                "ok": True,
                "custom_nodes_path": str(custom_nodes_path),
                "summary": inventory["summary"],
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
