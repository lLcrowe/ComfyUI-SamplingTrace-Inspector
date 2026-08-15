# Adapter SDK

## 1. 왜 Adapter가 필요한가

모든 ComfyUI 노드는 실행 이벤트를 남길 수 있지만, 노드 이름만 보고 실제 의미를 완전히 알 수는 없습니다.

```text
Generic Trace
- class type
- inputs
- execution timing

Semantic Adapter
- 역할
- 중요한 파라미터
- 실제 영향 시점
- 해석 방법
```

---

## 2. 기본 Adapter

위치:

```text
trace_inspector/adapters/
├─ base.py
├─ registry.py
└─ builtins.py
```

포함:
- KSampler
- ControlNet
- LoRA
- IPAdapter / PuLID / InstantID
- VAE
- CLIP Text Encode

---

## 3. 가장 작은 Adapter

```python
from trace_inspector.adapters import NodeSemanticAdapter, register_adapter


class MyNodeAdapter(NodeSemanticAdapter):
    adapter_id = "my_node"
    priority = 100

    def matches(self, class_type: str) -> bool:
        return "mynode" in class_type.lower()

    def summarize(self, node):
        inputs = node.get("inputs", {})
        return {
            "adapterId": self.adapter_id,
            "role": "model_patch",
            "runtimeBehavior": "Registers a custom patch used during sampling.",
            "parameters": {
                "strength": inputs.get("strength"),
                "start": inputs.get("start"),
                "end": inputs.get("end"),
            },
        }


register_adapter(MyNodeAdapter())
```

---

## 4. 역할 분류 권장

```text
image_transform
latent_transform
conditioning_builder
conditioning_patch
weight_patch
attention_patch
sampling_controller
pixel_latent_converter
output_sink
```

---

## 5. Runtime behavior 문구

노드가 언제 실제 영향을 주는지 명시합니다.

### 즉시 변환형

```text
Transforms IMAGE into a depth map when the node executes.
```

### CONDITIONING 등록형

```text
Attaches control data to CONDITIONING; actual residuals are computed during sampling.
```

### MODEL patch형

```text
Registers a patch when this graph node executes; actual influence occurs inside model layers during sampling.
```

---

## 6. Runtime 전용 계측

Semantic Adapter만으로 부족하면 ModelPatcher wrapper를 추가합니다.

권장 우선순위:

1. 기존 OUTER_SAMPLE / APPLY_MODEL 데이터 사용
2. transformer_options의 patch key 사용
3. custom node가 제공하는 callback 사용
4. 작은 전용 wrapper
5. custom node 소스 수정은 마지막

---

## 7. Adapter 테스트

```python
def test_my_adapter():
    summary = ADAPTER_REGISTRY.summarize({
        "classType": "MyNodeAdvanced",
        "inputs": {"strength": 0.8},
    })
    assert summary["adapterId"] == "my_node"
    assert summary["parameters"]["strength"] == 0.8
```

---

## 8. 완료 조건

좋은 Adapter는 다음 질문에 답합니다.

- 이 노드는 무엇을 입력받고 무엇을 변경하는가?
- 그래프 실행 시 바로 결과를 만드는가?
- 나중 Sampling 중에 적용할 patch를 등록하는가?
- 사용자가 어떤 파라미터를 먼저 비교해야 하는가?
- 숫자를 절대값으로 봐도 되는가, 상대 비교만 해야 하는가?

---

## Inventory-driven Adapter Selection

전용 Adapter는 설치 목록 전체에 대해 미리 만들지 않습니다.

```text
CUSTOM_NODE_INVENTORY.json
  ↓
TRACE_COMPATIBILITY_MATRIX.md
  ↓
ADAPTER_PRIORITY.md
  ↓
LOCAL_ADAPTER_PLAN.md
  ↓
실제 Runtime evidence
  ↓
Adapter 구현
```

Adapter를 추가하기 전 다음을 확인합니다.

1. 사용자가 실제 workflow에서 해당 package를 사용하는가
2. Generic node event와 표준 Runtime wrapper가 이미 필요한 신호를 제공하는가
3. 어떤 signal이 정확히 빠져 있는가
4. 다른 custom node source 수정 없이 Inspector 내부에서 대응 가능한가
5. Trace On/Off 결과 불변성 테스트를 만들 수 있는가

`source_fingerprint_sha256` 또는 Git commit이 달라지면 기존 Adapter 검증 상태를 재확인합니다.
