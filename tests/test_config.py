from __future__ import annotations

from trace_inspector.config import PREVIEW_DECODERS, TRACE_MODES, TraceOptions


def _from_node(
    mode: str,
    *,
    persist_tensor_stats: bool = True,
    preview_decoder: str = "clear",
) -> TraceOptions:
    return TraceOptions.from_node_inputs(
        mode=mode,
        label="mode-contract",
        preview_every=1,
        preview_max_side=768,
        preview_format="JPEG",
        preview_quality=85,
        persist_previews=True,
        persist_tensor_stats=persist_tensor_stats,
        preview_decoder=preview_decoder,
    )


def test_public_modes_are_basic_and_advanced_only():
    assert TRACE_MODES == ("basic", "advanced")


def test_public_preview_decoders_are_clear_and_fast():
    assert PREVIEW_DECODERS == ("clear", "fast")
    assert _from_node("basic").preview_decoder == "clear"
    assert _from_node("basic", preview_decoder="fast").preview_decoder == "fast"


def test_invalid_preview_decoder_falls_back_to_clear():
    assert _from_node("basic", preview_decoder="unknown").preview_decoder == "clear"


def test_legacy_deep_mode_is_folded_into_advanced():
    options = _from_node("deep")

    assert options.mode == "advanced"
    assert options.captures_statistics is True
    assert options.captures_cfg is True
    assert options.captures_control_residuals is True


def test_advanced_can_disable_high_cost_tensor_statistics():
    options = _from_node("advanced", persist_tensor_stats=False)

    assert options.captures_statistics is False
    assert options.captures_cfg is True
    assert options.captures_control_residuals is False


def test_direct_legacy_deep_options_are_normalized_too():
    assert TraceOptions(mode="deep").mode == "advanced"
