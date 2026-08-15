# ComfyUI SamplingTrace Inspector — 용어집

영문 원어를 유지하면서 처음 보는 사람이 대략적인 역할을 알 수 있도록 정리했습니다.

| Term | 한국어 설명 | 이 도구에서 보는 것 |
|---|---|---|
| **Preview** | 중간 미리보기 | 현재 x0를 빠르게 이미지로 변환한 화면 |
| **Latent** | 잠재 표현 / 압축된 이미지 정보 | 모델이 직접 수정하는 내부 이미지 데이터 |
| **Tensor** | 다차원 숫자 배열 | shape, dtype, device, 통계 |
| **x** | 현재 noisy latent | 현재 sampling 상태 |
| **x0** | 현재 예상 clean latent | 이 step에서 모델이 예상한 완성 방향 |
| **Noise** | 노이즈 | 초기 생성 재료 또는 현재 불확실성 |
| **Sigma** | 현재 노이즈 강도 | step별 noise schedule 위치 |
| **Sampler** | 노이즈를 단계적으로 제거하는 알고리즘 | 모델 예측을 사용해 다음 latent를 계산 |
| **Scheduler** | 노이즈 단계 배치 방식 | 어떤 Sigma 순서를 지날지 결정 |
| **Denoise** | 원본 보존 대비 재생성 강도 | img2img에서 변경 범위에 영향 |
| **Conditioning** | 생성 조건 정보 | Prompt, ControlNet 등 모델에 전달되는 조건 |
| **Conditional** | 조건이 있는 모델 예측 | Positive 조건을 반영한 방향 |
| **Unconditional** | 기준/Negative 쪽 모델 예측 | CFG 기준점 |
| **CFG** | 조건 반영 강도 | Conditional과 Unconditional 차이를 증폭 |
| **CFG delta** | 조건부·비조건부 예측 차이 | 조건이 현재 step을 얼마나 다른 방향으로 미는지 보는 상대 신호 |
| **ControlNet** | 구조 제어 모델 | Pose/Depth/Edge 등을 이용한 residual 생성 |
| **Control hint** | 제어 입력 힌트 | Skeleton, Depth map, Canny 등 |
| **Residual** | 기존 특징에 더하는 보정값 | ControlNet 내부 영향량의 상대 비교 |
| **Feature Map** | 모델 내부 특징 정보 | 픽셀이 아니라 형태·구조 특징이 담긴 Tensor |
| **LoRA** | 저용량 미세조정 가중치 | MODEL/CLIP weight patch |
| **IPAdapter** | 참조 이미지 특징 주입 | Attention/model patch와 적용 구간 |
| **Attention** | 정보 간 관계 계산 | Text/image reference가 내부 특징에 개입하는 지점 |
| **ModelPatcher** | 모델 변경사항 관리자 | LoRA, Hook, wrapper, object patch 관리 |
| **Wrapper** | 기존 함수 실행을 감싸는 구조 | Sampling/model 호출 전후 관찰 |
| **Hook** | 실행 중 특정 지점에 추가하는 함수 | CFG 또는 MODEL 내부 계측 |
| **Callback** | 진행 중 호출되는 함수 | Step, x0, x, total_steps 수집 |
| **OUTER_SAMPLE** | Sampling 전체 실행 wrapper 지점 | Segment 시작/종료와 callback 교체 |
| **APPLY_MODEL** | 확산 모델 적용 wrapper 지점 | Control residual과 transformer patch 관찰 |
| **Graph Trace** | 워크플로 실행 추적 | 어떤 노드가 언제 실행됐는지 |
| **Runtime Trace** | 샘플링 내부 추적 | 실제 step에서 무엇이 개입했는지 |
| **Probe** | 데이터를 바꾸지 않는 관찰 노드 | IMAGE/LATENT/CONDITIONING 전후 통계 |
| **Adapter** | 노드별 의미 해석기 | 역할, 주요 파라미터, 실제 영향 시점 |
| **Run** | workflow 한 번의 실행 기록 | 설정, Timeline, Step, 보고서 |
| **Segment** | 한 Run 안의 Sampling 구간 | 1차/2차 KSampler 등을 분리 |
| **JSONL** | 한 줄에 JSON 하나를 기록하는 형식 | 중단돼도 앞 step 기록 보존 |
| **A/B Compare** | 두 실행 비교 | 한 파라미터 변경 전후 비교 |
