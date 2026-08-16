from __future__ import annotations

import logging
from typing import Any

from .preview_capture import create_previewer
from .session import TraceSession

LOGGER = logging.getLogger("comfy.trace_inspector")


def _argument(args: tuple[Any, ...], kwargs: dict[str, Any], index: int, name: str, default: Any = None) -> Any:
    if len(args) > index:
        return args[index]
    return kwargs.get(name, default)


def _replace_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    index: int,
    name: str,
    value: Any,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    mutable = list(args)
    copied_kwargs = dict(kwargs)
    if len(mutable) > index:
        mutable[index] = value
    else:
        copied_kwargs[name] = value
    return tuple(mutable), copied_kwargs


def install_runtime_hooks(model_patcher: Any, session: TraceSession) -> Any:
    """Install trace wrappers on a cloned ComfyUI ModelPatcher.

    This preserves the user's existing KSampler and custom nodes. Any sampler
    that follows ComfyUI's standard CFGGuider/ModelPatcher wrapper path becomes
    observable without replacing the sampler node.
    """
    from comfy.patcher_extension import WrappersMP

    wrapper_key = f"comfy_trace_inspector:{session.run_id}"

    def outer_sample_wrapper(executor: Any, *args: Any, **kwargs: Any) -> Any:
        noise = _argument(args, kwargs, 0, "noise")
        latent_image = _argument(args, kwargs, 1, "latent_image")
        sampler = _argument(args, kwargs, 2, "sampler")
        sigmas = _argument(args, kwargs, 3, "sigmas")
        original_callback = _argument(args, kwargs, 5, "callback")
        seed = _argument(args, kwargs, 7, "seed")
        previewer = create_previewer(
            model_patcher,
            getattr(session.options, "preview_decoder", "clear"),
        )

        trace_active = False
        try:
            session.begin_sampling(
                noise=noise,
                latent_image=latent_image,
                sampler=sampler,
                sigmas=sigmas,
                seed=seed,
            )
            trace_active = True
        except Exception as exc:
            session.record_error("begin_sampling", exc)
            try:
                session.end_sampling(status="error", error=exc)
            except Exception as cleanup_exc:
                session.record_error("begin_sampling_cleanup", cleanup_exc)

        def traced_callback(step: int, x0: Any, x: Any, total_steps: int) -> Any:
            if trace_active:
                try:
                    session.capture_step(
                        step=step,
                        x0=x0,
                        x=x,
                        total_steps=total_steps,
                        previewer=previewer,
                    )
                except Exception as exc:
                    session.record_error("step_callback", exc)
            if original_callback is not None:
                return original_callback(step, x0, x, total_steps)
            return None

        traced_args, traced_kwargs = _replace_argument(
            args,
            kwargs,
            5,
            "callback",
            traced_callback,
        )
        try:
            result = executor(*traced_args, **traced_kwargs)
        except Exception as exc:
            if trace_active:
                try:
                    session.end_sampling(status="error", error=exc)
                except Exception as trace_exc:
                    session.record_error("end_sampling_error", trace_exc)
            raise
        else:
            if trace_active:
                try:
                    session.end_sampling(status="success")
                except Exception as exc:
                    # Trace persistence/report failure must not change the generated sample.
                    session.record_error("end_sampling_success", exc)
            return result

    model_patcher.add_wrapper_with_key(
        WrappersMP.OUTER_SAMPLE,
        wrapper_key,
        outer_sample_wrapper,
    )

    if session.options.mode == "advanced":
        if session.options.captures_statistics:
            transformer_options = model_patcher.model_options.setdefault("transformer_options", {})
            previous_attention_override = transformer_options.get("optimized_attention_override")

            def attention_observer(original: Any, q: Any, k: Any, v: Any, heads: Any, *args: Any, **kwargs: Any) -> Any:
                try:
                    session.record_prompt_attention(
                        q=q,
                        k=k,
                        heads=heads,
                        transformer_options=kwargs.get("transformer_options", {}),
                        scale=kwargs.get("scale"),
                    )
                except Exception as exc:
                    session.record_error("prompt_attention", exc)
                if previous_attention_override is not None:
                    return previous_attention_override(original, q, k, v, heads, *args, **kwargs)
                return original(q, k, v, heads, *args, **kwargs)

            transformer_options["optimized_attention_override"] = attention_observer

        def apply_model_wrapper(executor: Any, *args: Any, **kwargs: Any) -> Any:
            timestep = _argument(args, kwargs, 1, "t")
            control = _argument(args, kwargs, 4, "control")
            transformer_options = _argument(args, kwargs, 5, "transformer_options", {})
            try:
                session.record_control(
                    timestep=timestep,
                    control=control,
                    transformer_options=transformer_options,
                )
            except Exception as exc:
                session.record_error("apply_model_wrapper", exc)
            return executor(*args, **kwargs)

        model_patcher.add_wrapper_with_key(
            WrappersMP.APPLY_MODEL,
            wrapper_key,
            apply_model_wrapper,
        )

        def pre_cfg_hook(args: dict[str, Any]) -> Any:
            try:
                session.record_cfg(args)
            except Exception as exc:
                session.record_error("pre_cfg_hook", exc)
            return args.get("conds_out")

        model_patcher.set_model_sampler_pre_cfg_function(pre_cfg_hook)

    return model_patcher
