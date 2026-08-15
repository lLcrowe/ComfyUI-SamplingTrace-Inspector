from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import torch

from trace_inspector.runtime_hooks import install_runtime_hooks


class FakeWrappersMP:
    OUTER_SAMPLE = "outer_sample"
    APPLY_MODEL = "apply_model"


class FakeModelPatcher:
    def __init__(self):
        self.wrappers = {}
        self.pre_cfg = []
        self.model = SimpleNamespace(latent_format=None)
        self.load_device = "cpu"

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers[(wrapper_type, key)] = wrapper

    def set_model_sampler_pre_cfg_function(self, fn):
        self.pre_cfg.append(fn)


class FakeSession:
    def __init__(self):
        self.run_id = "run"
        self.options = SimpleNamespace(mode="advanced")
        self.calls = []

    def begin_sampling(self, **kwargs): self.calls.append(("begin", kwargs))
    def capture_step(self, **kwargs): self.calls.append(("step", kwargs))
    def end_sampling(self, **kwargs): self.calls.append(("end", kwargs))
    def record_control(self, **kwargs): self.calls.append(("control", kwargs))
    def record_cfg(self, args): self.calls.append(("cfg", args))
    def record_error(self, stage, error): self.calls.append(("error", stage, str(error)))


def test_outer_wrapper_preserves_original_callback(monkeypatch):
    comfy = types.ModuleType("comfy")
    patcher_extension = types.ModuleType("comfy.patcher_extension")
    patcher_extension.WrappersMP = FakeWrappersMP
    comfy.patcher_extension = patcher_extension
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.patcher_extension", patcher_extension)

    model = FakeModelPatcher()
    session = FakeSession()
    install_runtime_hooks(model, session)

    outer = next(wrapper for (kind, _key), wrapper in model.wrappers.items() if kind == "outer_sample")
    original_calls = []

    def original_callback(step, x0, x, total):
        original_calls.append((step, total))

    def executor(*args, **kwargs):
        callback = args[5] if len(args) > 5 else kwargs["callback"]
        callback(0, torch.zeros(1, 4, 2, 2), torch.ones(1, 4, 2, 2), 1)
        return "result"

    result = outer(
        executor,
        torch.ones(1, 4, 2, 2),
        torch.zeros(1, 4, 2, 2),
        object(),
        torch.tensor([1.0, 0.0]),
        None,
        original_callback,
        False,
        42,
    )
    assert result == "result"
    assert original_calls == [(0, 1)]
    assert [call[0] for call in session.calls] == ["begin", "step", "end"]


def test_trace_begin_failure_does_not_block_sampler(monkeypatch):
    comfy = types.ModuleType("comfy")
    patcher_extension = types.ModuleType("comfy.patcher_extension")
    patcher_extension.WrappersMP = FakeWrappersMP
    comfy.patcher_extension = patcher_extension
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.patcher_extension", patcher_extension)

    class BeginFailureSession(FakeSession):
        def begin_sampling(self, **kwargs):
            self.calls.append(("begin", kwargs))
            raise OSError("trace disk unavailable")

    model = FakeModelPatcher()
    session = BeginFailureSession()
    install_runtime_hooks(model, session)
    outer = next(wrapper for (kind, _key), wrapper in model.wrappers.items() if kind == "outer_sample")
    original_calls = []

    def original_callback(step, x0, x, total):
        original_calls.append((step, total))

    def executor(*args, **kwargs):
        callback = args[5] if len(args) > 5 else kwargs["callback"]
        callback(0, torch.zeros(1, 4, 2, 2), torch.ones(1, 4, 2, 2), 1)
        return "generated"

    result = outer(
        executor,
        torch.ones(1, 4, 2, 2),
        torch.zeros(1, 4, 2, 2),
        object(),
        torch.tensor([1.0, 0.0]),
        None,
        original_callback,
        False,
        42,
    )
    assert result == "generated"
    assert original_calls == [(0, 1)]
    assert not any(call[0] == "step" for call in session.calls)
    assert any(call[0] == "error" and call[1] == "begin_sampling" for call in session.calls)
