from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat


def unwrap_latent(value: Any) -> Any:
    if getattr(value, "is_nested", False):
        tensors = getattr(value, "tensors", None)
        if tensors:
            return tensors[0]
    return value


def _latent2rgb_previewer(latent_preview: Any, latent_format: Any) -> Any | None:
    factors = getattr(latent_format, "latent_rgb_factors", None)
    if factors is None:
        return None
    return latent_preview.Latent2RGBPreviewer(
        factors,
        getattr(latent_format, "latent_rgb_factors_bias", None),
        getattr(latent_format, "latent_rgb_factors_reshape", None),
    )


def _taesd_previewer(latent_preview: Any, latent_format: Any, load_device: Any) -> Any | None:
    import folder_paths

    decoder_name = getattr(latent_format, "taesd_decoder_name", None)
    if not decoder_name:
        return None
    decoder_file = next(
        (name for name in folder_paths.get_filename_list("vae_approx") if name.startswith(decoder_name)),
        "",
    )
    decoder_path = folder_paths.get_full_path("vae_approx", decoder_file)
    if not decoder_path:
        return None

    if decoder_name in getattr(latent_preview, "VIDEO_TAES", ()):
        import comfy.utils
        from comfy.sd import VAE

        taesd = VAE(comfy.utils.load_torch_file(decoder_path))
        taesd.first_stage_model.show_progress_bar = False
        return latent_preview.TAEHVPreviewerImpl(taesd)

    from comfy.taesd.taesd import TAESD

    taesd = TAESD(
        None,
        decoder_path,
        latent_channels=getattr(latent_format, "latent_channels", 4),
    ).to(load_device)
    return latent_preview.TAESDPreviewerImpl(taesd)


def create_previewer(model_patcher: Any, decoder: str = "clear") -> Any | None:
    """Create a Trace-only previewer without changing ComfyUI's live preview setting.

    Clear prefers the installed model-specific TAESD decoder. Fast keeps the
    inexpensive latent-space RGB projection used by ComfyUI's Auto mode.
    """
    try:
        import latent_preview

        model = getattr(model_patcher, "model", None)
        latent_format = getattr(model, "latent_format", None)
        load_device = getattr(model_patcher, "load_device", None)
        if latent_format is None or load_device is None:
            return None
        if str(decoder).lower() == "clear":
            try:
                previewer = _taesd_previewer(latent_preview, latent_format, load_device)
            except Exception:
                previewer = None
            if previewer is not None:
                return previewer
        return _latent2rgb_previewer(latent_preview, latent_format)
    except Exception:
        return None


def decode_preview(previewer: Any, x0: Any, max_side: int) -> Image.Image | None:
    if previewer is None:
        return None
    try:
        x0 = unwrap_latent(x0)
        image = previewer.decode_latent_to_preview(x0)
        if not isinstance(image, Image.Image):
            return None
        image = image.convert("RGB")
        longest = max(image.size)
        if longest > max_side:
            scale = max_side / longest
            target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(target, Image.Resampling.LANCZOS)
        return image
    except Exception:
        return None


def save_preview(
    image: Image.Image,
    path: Path,
    *,
    image_format: str,
    quality: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if image_format == "PNG":
        image.save(path, format="PNG", optimize=False)
    else:
        image.save(path, format="JPEG", quality=quality, optimize=False)


def preview_thumbnail(image: Image.Image, side: int = 128) -> Image.Image:
    thumb = image.convert("RGB").copy()
    thumb.thumbnail((side, side), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (side, side), (0, 0, 0))
    x = (side - thumb.width) // 2
    y = (side - thumb.height) // 2
    canvas.paste(thumb, (x, y))
    return canvas


def preview_difference(previous: Image.Image | None, current: Image.Image) -> float | None:
    """Cheap normalized pixel-change score for locating visual transition points."""
    if previous is None:
        return None
    try:
        current_thumb = preview_thumbnail(current, previous.width)
        diff = ImageChops.difference(previous.convert("RGB"), current_thumb)
        means = ImageStat.Stat(diff).mean
        return float(sum(means) / (len(means) * 255.0))
    except Exception:
        return None
