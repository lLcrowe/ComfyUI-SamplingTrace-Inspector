from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import NodeSemanticAdapter


class TokenAdapter(NodeSemanticAdapter):
    tokens: tuple[str, ...] = ()
    role: str = "unknown"
    runtime_behavior: str = "unknown"
    parameter_keys: tuple[str, ...] = ()

    def matches(self, class_type: str) -> bool:
        lowered = class_type.lower().replace("_", " ")
        return any(token in lowered for token in self.tokens)

    def summarize(self, node: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "role": self.role,
            "runtimeBehavior": self.runtime_behavior,
            "parameters": self.selected_inputs(node, self.parameter_keys),
        }


class KSamplerAdapter(TokenAdapter):
    adapter_id = "ksampler"
    priority = 100
    tokens = ("ksampler", "sampler custom", "samplercustom")
    role = "sampling_controller"
    runtime_behavior = "Runs the iterative denoising loop; the Trace Model OUTER_SAMPLE wrapper observes it."
    parameter_keys = (
        "seed",
        "noise_seed",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "denoise",
        "start_at_step",
        "end_at_step",
        "add_noise",
        "return_with_leftover_noise",
    )


class ControlNetAdapter(TokenAdapter):
    adapter_id = "controlnet"
    priority = 100
    tokens = ("controlnet", "control net", "t2i adapter", "t2iadapter")
    role = "conditioning_patch"
    runtime_behavior = (
        "The graph node attaches control data to CONDITIONING; get_control is evaluated during sampling, "
        "then residual features are passed into apply_model."
    )
    parameter_keys = (
        "strength",
        "start_percent",
        "end_percent",
        "control_after_generate",
        "preprocessor",
        "resolution",
    )


class LoRAAdapter(TokenAdapter):
    adapter_id = "lora"
    priority = 90
    tokens = ("lora", "lycoris", "locon")
    role = "weight_patch"
    runtime_behavior = (
        "Registers weight/Hook patches on MODEL or CLIP before sampling. The effect is present whenever "
        "the patched model layers execute; it is not a separate image-producing step."
    )
    parameter_keys = (
        "lora_name",
        "model_strength",
        "clip_strength",
        "strength_model",
        "strength_clip",
        "strength",
    )


class IPAdapterAdapter(TokenAdapter):
    adapter_id = "ipadapter"
    priority = 95
    tokens = ("ipadapter", "ip adapter", "pulid", "instantid")
    role = "attention_patch"
    runtime_behavior = (
        "Registers attention/model patches from reference-image features. The graph node prepares the patch; "
        "its actual influence occurs inside model attention during sampling."
    )
    parameter_keys = (
        "weight",
        "weight_type",
        "combine_embeds",
        "start_at",
        "end_at",
        "embeds_scaling",
        "provider",
    )


class VAEAdapter(TokenAdapter):
    adapter_id = "vae"
    priority = 50
    tokens = ("vae encode", "vaeencode", "vae decode", "vaedecode")
    role = "pixel_latent_converter"
    runtime_behavior = "Converts between IMAGE pixels and Latent (잠재 표현); it is outside the denoising loop."
    parameter_keys = ("tile_size", "overlap", "temporal_size", "temporal_overlap")


class CLIPTextAdapter(TokenAdapter):
    adapter_id = "clip_text"
    priority = 50
    tokens = ("clip text", "cliptext", "text encode", "textencode")
    role = "text_condition_encoder"
    runtime_behavior = "Converts prompt text into CONDITIONING before sampling."
    parameter_keys = ("text", "width", "height", "crop_w", "crop_h", "target_width", "target_height")


BUILTIN_ADAPTERS = (
    KSamplerAdapter(),
    ControlNetAdapter(),
    IPAdapterAdapter(),
    LoRAAdapter(),
    VAEAdapter(),
    CLIPTextAdapter(),
)
