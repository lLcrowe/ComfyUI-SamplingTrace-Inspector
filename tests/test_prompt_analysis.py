from __future__ import annotations

from trace_inspector.prompt_analysis import analyze_prompt, extract_generation_settings


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
