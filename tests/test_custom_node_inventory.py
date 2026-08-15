from __future__ import annotations

import json
import warnings
from pathlib import Path

from trace_inspector.custom_node_inventory import (
    ScanOptions,
    resolve_custom_nodes_path,
    scan_custom_nodes,
    write_inventory_reports,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_static_scan_does_not_import_or_execute_packages(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
    package = custom_nodes / "unsafe_if_imported"
    marker = tmp_path / "executed.txt"
    _write(
        package / "__init__.py",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "class DemoNode:\n"
        "    RETURN_TYPES = ('IMAGE',)\n"
        "NODE_CLASS_MAPPINGS = {'Demo Node': DemoNode}\n",
    )

    inventory = scan_custom_nodes(custom_nodes)

    assert not marker.exists()
    assert inventory["summary"]["package_count"] == 1
    scanned = inventory["packages"][0]
    assert scanned["node_mappings"] == {"Demo Node": "DemoNode"}
    assert scanned["assessment"]["primary_category"] == "Data Transform"
    assert inventory["safety"]["imports_scanned_packages"] is False


def test_detects_sampler_model_patch_control_and_frontend_signals(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "ComfyUI-ComplexPipeline"
    _write(
        package / "nodes.py",
        "import comfy.samplers\n"
        "import comfy.model_patcher\n"
        "from server import PromptServer\n"
        "class ComplexNode:\n"
        "    RETURN_TYPES = ('MODEL', 'CONDITIONING', 'CONTROL_NET')\n"
        "    def run(self, model):\n"
        "        cloned = model.clone()\n"
        "        cloned.add_wrapper_with_key('outer_sample', 'x', lambda *a: None)\n"
        "        common_ksampler()\n"
        "        return cloned\n"
        "NODE_CLASS_MAPPINGS = {'Complex Sampler': ComplexNode}\n"
        "routes = PromptServer.instance.routes\n"
        "@routes.get('/complex')\n"
        "async def route(request): return None\n",
    )
    _write(
        package / "web" / "index.js",
        "app.registerExtension({ name: 'complex' });\n"
        "api.addEventListener('complex.trace', () => {});\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]
    assessment = scanned["assessment"]

    assert "Sampler/Pipeline Replacement" in assessment["categories"]
    assert "Model Patching" in assessment["categories"]
    assert "Conditioning" in assessment["categories"]
    assert "Frontend/Workflow Utility" in assessment["categories"]
    assert assessment["priority"] == "A"
    assert assessment["runtime_hook_required"] is True
    assert assessment["dedicated_adapter"] == "required"
    assert scanned["features"]["uses_server_routes"]["detected"] is True
    assert scanned["features"]["uses_ws_messages"]["detected"] is True


def test_generates_inventory_and_matrix_reports(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    _write(
        custom_nodes / "simple" / "__init__.py",
        "class Simple:\n"
        "    RETURN_TYPES = ('MASK',)\n"
        "NODE_CLASS_MAPPINGS = {'Simple': Simple}\n",
    )
    inventory = scan_custom_nodes(custom_nodes)
    output_dir = tmp_path / "reports"
    outputs = write_inventory_reports(inventory, output_dir)

    assert Path(outputs["json"]).exists()
    assert Path(outputs["inventory_markdown"]).exists()
    assert Path(outputs["compatibility_matrix"]).exists()
    assert Path(outputs["adapter_priority"]).exists()
    assert Path(outputs["local_adapter_plan"]).exists()

    payload = json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert "Static-only scan" in Path(outputs["inventory_markdown"]).read_text(encoding="utf-8")
    assert "Generic trace" in Path(outputs["compatibility_matrix"]).read_text(encoding="utf-8")


def test_resolves_portable_and_direct_custom_nodes_paths(tmp_path: Path) -> None:
    portable = tmp_path / "ComfyUI_windows_portable"
    custom_nodes = portable / "ComfyUI" / "custom_nodes"
    custom_nodes.mkdir(parents=True)

    assert resolve_custom_nodes_path(comfy_root=portable) == custom_nodes.resolve()
    assert resolve_custom_nodes_path(custom_nodes=custom_nodes) == custom_nodes.resolve()


def test_previous_inventory_diff_uses_source_fingerprint(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    source = custom_nodes / "simple" / "__init__.py"
    _write(source, "NODE_CLASS_MAPPINGS = {}\n")
    previous = scan_custom_nodes(custom_nodes)

    _write(source, "class A: pass\nNODE_CLASS_MAPPINGS = {'A': A}\n")
    current = scan_custom_nodes(custom_nodes, previous_inventory=previous)

    assert current["diff"]["changed"] == ["simple"]
    assert current["diff"]["added"] == []
    assert current["diff"]["removed"] == []


def test_excludes_trace_inspector_itself_by_default(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    _write(custom_nodes / "ComfyUI-SamplingTrace-Inspector" / "__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
    _write(custom_nodes / "Other" / "__init__.py", "NODE_CLASS_MAPPINGS = {}\n")

    default_inventory = scan_custom_nodes(custom_nodes)
    included_inventory = scan_custom_nodes(custom_nodes, options=ScanOptions(include_self=True))

    assert [item["folder_name"] for item in default_inventory["packages"]] == ["Other"]
    assert {item["folder_name"] for item in included_inventory["packages"]} == {
        "ComfyUI-SamplingTrace-Inspector",
        "Other",
    }


def test_reads_git_manifest_version_and_dependencies_without_git_command(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "VersionedNode"
    _write(
        package / "pyproject.toml",
        "[project]\n"
        "name = 'versioned-node'\n"
        "version = '1.2.3'\n"
        "dependencies = ['torch>=2', 'numpy']\n"
        "[project.urls]\n"
        "Repository = 'https://example.invalid/versioned-node'\n",
    )
    _write(package / "__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
    _write(
        package / ".git" / "config",
        '[remote "origin"]\n    url = https://github.com/example/versioned-node.git\n',
    )
    _write(package / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(package / ".git" / "refs" / "heads" / "main", "a" * 40 + "\n")

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["declared_name"] == "versioned-node"
    assert scanned["version"] == "1.2.3"
    assert scanned["dependencies"] == ["numpy", "torch>=2"]
    assert scanned["repository"] == "https://github.com/example/versioned-node.git"
    assert scanned["git"]["branch"] == "main"
    assert scanned["git"]["commit"] == "a" * 40


def test_flags_dynamic_mapping_download_subprocess_and_attribute_mutation(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "DynamicPipeline"
    _write(
        package / "__init__.py",
        "import comfy.samplers\n"
        "import requests\n"
        "import subprocess\n"
        "NODE_CLASS_MAPPINGS = build_nodes()\n"
        "comfy.samplers.custom_flag = True\n"
        "def setup():\n"
        "    requests.get('https://example.invalid')\n"
        "    subprocess.run(['echo', 'x'])\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["dynamic_node_mapping"] is True
    assert scanned["features"]["network_or_download_code"]["detected"] is True
    assert scanned["features"]["subprocess_code"]["detected"] is True
    assert scanned["features"]["monkey_patch_suspected"]["detected"] is True
    assert scanned["assessment"]["dedicated_adapter"] == "required"


def test_runtime_classification_ignores_labels_comments_and_frontend_names(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "FrontendUtility"
    _write(
        package / "__init__.py",
        "class UtilityNode:\n"
        "    CATEGORY = 'MODEL'\n"
        "    RETURN_TYPES = ('STRING',)\n"
        "    @classmethod\n"
        "    def INPUT_TYPES(cls):\n"
        "        return {'required': {'label': (['MODEL', 'LORA', 'KSAMPLER'],)}}\n"
        "NODE_CLASS_MAPPINGS = {'Utility': UtilityNode}\n",
    )
    _write(
        package / "web" / "index.js",
        "// UI labels only: KSampler ControlNet IPAdapter LoRA Detailer\n"
        "app.registerExtension({ name: 'frontend.utility' });\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["comfy_types"] == []
    assert scanned["features"]["uses_sampler_api"]["detected"] is False
    assert scanned["features"]["uses_controlnet"]["detected"] is False
    assert scanned["features"]["uses_ipadapter"]["detected"] is False
    assert scanned["features"]["uses_lora"]["detected"] is False
    assert scanned["assessment"]["primary_category"] == "Frontend/Workflow Utility"
    assert scanned["assessment"]["priority"] == "C"


def test_browser_test_directories_are_skipped_unless_tests_are_included(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "AgentPanel"
    _write(package / "__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
    _write(
        package / "browser_tests" / "test_pipeline.py",
        "import comfy.samplers\n"
        "def test_pipeline():\n"
        "    return common_ksampler()\n",
    )

    default_inventory = scan_custom_nodes(custom_nodes)
    included_inventory = scan_custom_nodes(custom_nodes, options=ScanOptions(include_tests=True))

    default_package = default_inventory["packages"][0]
    included_package = included_inventory["packages"][0]
    assert default_package["features"]["uses_sampler_api"]["detected"] is False
    assert included_package["features"]["uses_sampler_api"]["detected"] is True


def test_utf8_bom_python_files_parse_without_error(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    source = custom_nodes / "BomNode" / "__init__.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(
        b"\xef\xbb\xbf"
        + b"class BomNode:\n    RETURN_TYPES = ('IMAGE',)\n"
        + b"NODE_CLASS_MAPPINGS = {'BOM': BomNode}\n"
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["node_mappings"] == {"BOM": "BomNode"}
    assert scanned["parse_errors"] == []
    assert inventory["summary"]["parse_error_count"] == 0


def test_third_party_invalid_escape_syntax_warnings_are_suppressed(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    _write(
        custom_nodes / "LegacyNode" / "__init__.py",
        "PATTERN = '\\('"
        "\nNODE_CLASS_MAPPINGS = {}\n",
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        inventory = scan_custom_nodes(custom_nodes)

    assert inventory["summary"]["scan_error_count"] == 0
    assert not any(issubclass(item.category, SyntaxWarning) for item in captured)


def test_non_comfy_monkey_patches_are_risks_not_adapter_requirements(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "ImageUtility"
    _write(
        package / "__init__.py",
        "import sys\n"
        "import torch\n"
        "sys.stdout = sys.stderr\n"
        "torch.load = safe_load\n"
        "class ImageUtility:\n"
        "    RETURN_TYPES = ('IMAGE',)\n"
        "NODE_CLASS_MAPPINGS = {'Image Utility': ImageUtility}\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["features"]["monkey_patch_suspected"]["detected"] is True
    assert scanned["assessment"]["primary_category"] == "Data Transform"
    assert scanned["assessment"]["dedicated_adapter"] == "not_needed"
    assert scanned["assessment"]["priority"] == "B"


def test_parse_error_count_is_exposed_in_summary_and_markdown(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    _write(custom_nodes / "BrokenNode" / "broken.py", "def broken(:\n")

    inventory = scan_custom_nodes(custom_nodes)
    outputs = write_inventory_reports(inventory, tmp_path / "reports")
    markdown = Path(outputs["inventory_markdown"]).read_text(encoding="utf-8")

    assert inventory["summary"]["scan_error_count"] == 0
    assert inventory["summary"]["parse_error_count"] == 1
    assert "Parse errors: **1**" in markdown
    assert "BrokenNode/broken.py" in markdown


def test_sampler_configuration_is_not_sampler_execution(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "SamplerConfigUtility"
    _write(
        package / "__init__.py",
        "import comfy.samplers\n"
        "class SamplerConfig:\n"
        "    @classmethod\n"
        "    def INPUT_TYPES(cls):\n"
        "        return {'required': {'sampler': (comfy.samplers.KSampler.SAMPLERS,)}}\n"
        "    RETURN_TYPES = ('STRING',)\n"
        "NODE_CLASS_MAPPINGS = {'Sampler Config': SamplerConfig}\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["features"]["uses_sampler_api"]["detected"] is True
    assert scanned["features"]["uses_sampler_execution"]["detected"] is False
    assert "Sampler/Pipeline Replacement" not in scanned["assessment"]["categories"]
    assert scanned["assessment"]["dedicated_adapter"] == "not_needed"


def test_unrelated_model_option_and_lora_symbols_do_not_imply_comfy_model_patch(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "AudioSuite"
    _write(
        package / "__init__.py",
        "import comfy.model_management\n"
        "def load_lora_weights(model_options):\n"
        "    return model_options\n"
        "class AudioNode:\n"
        "    RETURN_TYPES = ('AUDIO',)\n"
        "NODE_CLASS_MAPPINGS = {'Audio': AudioNode}\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["features"]["uses_model_options"]["detected"] is True
    assert scanned["features"]["uses_lora"]["detected"] is True
    assert "Model Patching" not in scanned["assessment"]["categories"]
    assert scanned["assessment"]["priority"] == "B"
    assert scanned["assessment"]["dedicated_adapter"] == "not_needed"


def test_impact_name_alone_does_not_force_priority_a(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    package = custom_nodes / "comfyui-impact-subpack"
    _write(
        package / "__init__.py",
        "class Detector:\n"
        "    RETURN_TYPES = ('BBOX_DETECTOR',)\n"
        "    def detect(self, detailer_hook=None):\n"
        "        return detailer_hook\n"
        "NODE_CLASS_MAPPINGS = {'Detector': Detector}\n",
    )

    inventory = scan_custom_nodes(custom_nodes)
    scanned = inventory["packages"][0]

    assert scanned["features"]["uses_detailer"]["detected"] is True
    assert scanned["assessment"]["priority"] == "B"
    assert scanned["assessment"]["dedicated_adapter"] == "not_needed"
