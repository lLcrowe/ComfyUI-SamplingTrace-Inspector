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


def create_previewer(model_patcher: Any) -> Any | None:
    """Use ComfyUI's configured Preview decoder (Latent2RGB or TAESD)."""
    try:
        import latent_preview

        model = getattr(model_patcher, "model", None)
        latent_format = getattr(model, "latent_format", None)
        load_device = getattr(model_patcher, "load_device", None)
        if latent_format is None or load_device is None:
            return None
        previewer = latent_preview.get_previewer(load_device, latent_format)
        if previewer is not None:
            return previewer
        # Trace capture can still use the model's cheap Latent2RGB factors when
        # ComfyUI's normal live preview is disabled.
        factors = getattr(latent_format, "latent_rgb_factors", None)
        if factors is not None:
            return latent_preview.Latent2RGBPreviewer(
                factors,
                getattr(latent_format, "latent_rgb_factors_bias", None),
                getattr(latent_format, "latent_rgb_factors_reshape", None),
            )
        return None
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
