from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from trace_inspector.preview_capture import create_previewer


class FakeLatent2RGBPreviewer:
    def __init__(self, *args):
        self.args = args


class FakeTAESD:
    def __init__(self, _encoder, decoder_path, *, latent_channels):
        self.decoder_path = decoder_path
        self.latent_channels = latent_channels
        self.device = None

    def to(self, device):
        self.device = device
        return self


class FakeTAESDPreviewer:
    def __init__(self, taesd):
        self.taesd = taesd


def _model():
    latent_format = SimpleNamespace(
        taesd_decoder_name="taesdxl_decoder",
        latent_channels=4,
        latent_rgb_factors=((1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)),
        latent_rgb_factors_bias=None,
        latent_rgb_factors_reshape=None,
    )
    return SimpleNamespace(model=SimpleNamespace(latent_format=latent_format), load_device="cuda:0")


def _install_fake_modules(monkeypatch, *, decoder_path="D:/models/taesdxl_decoder.safetensors"):
    latent_preview = types.ModuleType("latent_preview")
    latent_preview.VIDEO_TAES = []
    latent_preview.Latent2RGBPreviewer = FakeLatent2RGBPreviewer
    latent_preview.TAESDPreviewerImpl = FakeTAESDPreviewer

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda category: ["taesdxl_decoder.safetensors"]
    folder_paths.get_full_path = lambda category, name: decoder_path if name else None

    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy_taesd = types.ModuleType("comfy.taesd")
    comfy_taesd.__path__ = []
    comfy_taesd_module = types.ModuleType("comfy.taesd.taesd")
    comfy_taesd_module.TAESD = FakeTAESD

    monkeypatch.setitem(sys.modules, "latent_preview", latent_preview)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.taesd", comfy_taesd)
    monkeypatch.setitem(sys.modules, "comfy.taesd.taesd", comfy_taesd_module)


def test_clear_previewer_prefers_model_specific_taesd(monkeypatch):
    _install_fake_modules(monkeypatch)

    previewer = create_previewer(_model(), "clear")

    assert isinstance(previewer, FakeTAESDPreviewer)
    assert previewer.taesd.decoder_path.endswith("taesdxl_decoder.safetensors")
    assert previewer.taesd.device == "cuda:0"


def test_fast_previewer_keeps_latent2rgb(monkeypatch):
    _install_fake_modules(monkeypatch)

    previewer = create_previewer(_model(), "fast")

    assert isinstance(previewer, FakeLatent2RGBPreviewer)


def test_clear_previewer_falls_back_when_taesd_is_missing(monkeypatch):
    _install_fake_modules(monkeypatch, decoder_path=None)

    previewer = create_previewer(_model(), "clear")

    assert isinstance(previewer, FakeLatent2RGBPreviewer)


def test_clear_previewer_falls_back_when_taesd_load_fails(monkeypatch):
    _install_fake_modules(monkeypatch)
    sys.modules["comfy.taesd.taesd"].TAESD = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("bad file"))

    previewer = create_previewer(_model(), "clear")

    assert isinstance(previewer, FakeLatent2RGBPreviewer)
