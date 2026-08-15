from __future__ import annotations

from trace_inspector.prompt_capture import PromptTokenCapture, TracingClipProxy


class FakeLaneTokenizer:
    start_token = 1
    end_token = 2
    pad_token = 2
    inv_vocab = {1: "<start>", 2: "<end>", 10: "cat</w>", 11: "bad</w>"}

    def decode(self, token_ids, skip_special_tokens=False):
        return self.inv_vocab.get(token_ids[0], "")


class FakeTokenizer:
    def __init__(self):
        self.clip_l = FakeLaneTokenizer()


class FakeClip:
    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.last_result = None

    def tokenize(self, text, return_word_ids=False):
        token_id = 11 if "bad" in text else 10
        self.last_result = {"l": [[(1, 1.0, 0), (token_id, 1.1, 1), (2, 1.0, 0)]]}
        return self.last_result

    def clone(self):
        return FakeClip()


class FakeSession:
    def __init__(self):
        self.updates = []

    def update_prompt_tokenization(self, payload):
        self.updates.append(payload)


def prompt_graph():
    return {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["9", 0]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["9", 0]}},
        "3": {
            "class_type": "IllustriousKSamplerPresets",
            "inputs": {"positive": ["4", 0], "negative": ["2", 0]},
        },
        "4": {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["1", 0]}},
        "9": {"class_type": "ComfyTraceClip", "inputs": {}},
    }


def test_tracing_proxy_returns_original_token_object_and_records_actual_call(monkeypatch):
    import trace_inspector.prompt_capture as capture_module

    clip = FakeClip()
    capture = PromptTokenCapture(prompt_graph(), trace_node_id="9")
    proxy = TracingClipProxy(clip, capture)
    monkeypatch.setattr(capture_module, "_current_node_id", lambda: "1")

    result = proxy.tokenize("cat", return_word_ids=True)
    snapshot = capture.snapshot()

    assert result is clip.last_result
    assert snapshot["status"] == "captured"
    assert snapshot["source"] == "traced_clip"
    assert snapshot["prompts"][0]["roles"] == ["positive"]
    call = snapshot["prompts"][0]["calls"][0]
    assert call["sourceField"] == "text"
    assert call["text"] == "cat"
    assert call["encoders"][0]["chunks"][0][1]["tokenId"] == 10
    assert call["encoders"][0]["chunks"][0][1]["weight"] == 1.1


def test_custom_sampler_positive_and_negative_are_both_resolved():
    capture = PromptTokenCapture(prompt_graph())
    clip = FakeClip()
    capture.record(clip, "cat", clip.tokenize("cat", True), node_id="1")
    capture.record(clip, "bad", clip.tokenize("bad", True), node_id="2")

    by_id = {prompt["nodeId"]: prompt for prompt in capture.snapshot()["prompts"]}
    assert by_id["1"]["roles"] == ["positive"]
    assert by_id["2"]["roles"] == ["negative"]


def test_capture_flushes_existing_and_future_calls_to_bound_session():
    capture = PromptTokenCapture(prompt_graph())
    clip = FakeClip()
    capture.record(clip, "cat", clip.tokenize("cat", True), node_id="1")
    session = FakeSession()

    capture.bind(session)
    capture.record(clip, "bad", clip.tokenize("bad", True), node_id="2")

    assert session.updates[0]["callCount"] == 1
    assert session.updates[-1]["callCount"] == 2


def test_proxy_clone_keeps_capture_but_does_not_reuse_original_clip():
    capture = PromptTokenCapture(prompt_graph())
    proxy = TracingClipProxy(FakeClip(), capture)

    cloned = proxy.clone()

    assert isinstance(cloned, TracingClipProxy)
    assert cloned._capture is capture
    assert cloned._clip is not proxy._clip
