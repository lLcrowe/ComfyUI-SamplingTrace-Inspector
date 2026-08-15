from __future__ import annotations

from trace_inspector.prompt_analysis import (
    analyze_prompt,
    extract_generation_settings,
    extract_standard_prompt_tokenization,
)


class FakeLaneTokenizer:
    def __init__(self, *, pad_token: int):
        self.start_token = 1
        self.end_token = 2
        self.pad_token = pad_token
        self.inv_vocab = {1: "<start>", 2: "<end>", 10: "cat</w>", 11: "dog</w>", 0: "<pad>"}

    def decode(self, token_ids, skip_special_tokens=False):
        return self.inv_vocab.get(token_ids[0], "")


class FakeTokenizer:
    def __init__(self):
        self.clip_l = FakeLaneTokenizer(pad_token=2)
        self.clip_g = FakeLaneTokenizer(pad_token=0)


class FakeClip:
    def __init__(self):
        self.tokenizer = FakeTokenizer()

    def tokenize(self, text, return_word_ids=False):
        token_id = 11 if "dog" in text else 10
        return {
            "g": [[(1, 1.0, 0), (token_id, 1.25, 1), (2, 1.0, 0), (0, 1.0, 0)]],
            "l": [[(1, 1.0, 0), (token_id, 1.25, 1), (2, 1.0, 0), (2, 1.0, 0)]],
        }


def sample_prompt():
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42,
                "steps": 30,
                "cfg": 6.5,
                "sampler_name": "euler",
                "model": ["2", 0],
            },
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {"lora_name": "character.safetensors", "strength_model": 0.8},
        },
        "3": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {"strength": 0.75, "start_percent": 0.0, "end_percent": 0.7},
        },
    }


def test_prompt_classification_and_settings():
    analysis = analyze_prompt(sample_prompt())
    settings = extract_generation_settings(analysis)
    assert analysis["nodeCount"] == 3
    assert settings["seed"] == 42
    assert settings["cfg"] == 6.5
    assert settings["lora"][0]["classType"] == "LoraLoader"
    assert settings["controlnet"][0]["inputs"]["end_percent"] == 0.7


def test_workflow_hash_is_stable_for_key_order():
    a = analyze_prompt(sample_prompt())["workflowHash"]
    prompt = sample_prompt()
    b = analyze_prompt(dict(reversed(list(prompt.items()))))["workflowHash"]
    assert a == b


def standard_prompt_graph():
    return {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "(cat:1.25)", "clip": ["8", 1]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "dog", "clip": ["8", 1]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"positive": ["4", 0], "negative": ["2", 0], "model": ["7", 0]},
        },
        "4": {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["1", 0]}},
    }


def test_standard_prompt_capture_uses_connected_clip_and_sampler_roles():
    result = extract_standard_prompt_tokenization(standard_prompt_graph(), FakeClip())

    assert result["status"] == "captured"
    assert result["modelFamily"] == "sdxl"
    assert result["prompts"][0]["roles"] == ["positive"]
    assert result["prompts"][1]["roles"] == ["negative"]
    local = result["prompts"][0]["encoders"][1]
    assert local["name"] == "l"
    assert local["contentTokenCount"] == 1
    assert local["paddingTokenCount"] == 1
    assert local["chunks"][0][1]["tokenId"] == 10
    assert local["chunks"][0][1]["weight"] == 1.25
    assert local["chunks"][0][1]["wordId"] == 1


def test_standard_prompt_capture_without_clip_keeps_text_and_explains_next_action():
    result = extract_standard_prompt_tokenization(standard_prompt_graph())

    assert result["status"] == "clip_not_connected"
    assert result["prompts"][0]["texts"]["default"] == "(cat:1.25)"
    assert result["prompts"][0]["encoders"] == []
    assert "Connect" in result["messages"][0]


def test_sdxl_prompt_uses_separate_global_and_local_text():
    graph = {
        "1": {
            "class_type": "CLIPTextEncodeSDXL",
            "inputs": {"text_g": "cat", "text_l": "dog"},
        },
        "2": {"class_type": "KSampler", "inputs": {"positive": ["1", 0]}},
    }
    result = extract_standard_prompt_tokenization(graph, FakeClip())
    prompt = result["prompts"][0]

    global_token = prompt["encoders"][0]["chunks"][0][1]["tokenId"]
    local_token = prompt["encoders"][1]["chunks"][0][1]["tokenId"]
    assert prompt["texts"] == {"g": "cat", "l": "dog"}
    assert global_token == 10
    assert local_token == 11
