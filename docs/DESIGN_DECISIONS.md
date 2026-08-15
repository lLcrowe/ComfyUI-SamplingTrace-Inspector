# Design Decisions

## D1. KSampler replacement을 만들지 않는다

### 선택
`Trace Model`이 ModelPatcher wrapper를 등록합니다.

### 이유
- 기존 workflow 유지
- custom sampler 공통 대응 가능성
- upstream 변화 범위 축소

---

## D2. Preview가 중심이고 수치는 보조다

### 선택
UI의 가장 큰 영역은 Step Preview입니다.

### 이유
사용자의 실제 목적은 수치를 최적화하는 것이 아니라 이미지가 언제 어떻게 변하는지 파악하는 것입니다.

---

## D3. Tensor 원본을 저장하지 않는다

### 선택
shape/dtype/device와 bounded sample 통계만 저장합니다.

### 이유
- VRAM/CPU transfer
- 디스크 폭증
- 개인정보/모델 내부 데이터 노출

---

## D4. Generic Trace와 Semantic Adapter를 분리한다

### 선택
모든 노드는 기본 실행 추적, 주요 노드만 Adapter 해석을 제공합니다.

### 이유
모든 custom node를 자동 이해하려는 목표는 유지보수 불가능합니다.

---

## D5. 인과 판단을 자동 확정하지 않는다

### 선택
Observation/Metric/Hypothesis/A-B 실험 흐름을 사용합니다.

### 이유
CFG/Control residual 크기는 품질과 직접 일치하지 않습니다.

---

## D6. Trace Model은 매 queue마다 새 run을 만든다

### 선택
`IS_CHANGED = NaN`을 사용합니다.

### 비용
Downstream cache를 무효화할 수 있습니다.

### 이유
서로 다른 실행의 event와 artifact가 섞이면 분석 도구로서 신뢰할 수 없습니다.
