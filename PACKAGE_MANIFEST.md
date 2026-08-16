# Package Manifest

## 바로 사용할 파일

- `CODEX_START_HERE.md` — Codex 인계 시작점
- `README.md` — 영어 설치·연결·사용·보안 가이드
- `README.ko.md` — 동일 범위의 한국어 가이드
- `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md` — 설치된 노드 선행 조사 프롬프트
- `docs/CODEX_PROMPT.md` — Inventory 이후 실제 장착·검증 프롬프트
- `docs/CODEX_HANDOFF.md` — 실제 설치본 통합 기준
- `docs/BUILD_VALIDATION.md` — 현재 검증 결과
- `docs/IMPLEMENTATION_STATUS.md` — Phase별 상태

## 코드

- `__init__.py`
- `nodes.py`
- `trace_inspector/`
- `web/`

## 테스트/도구

- `tests/`
- `scripts/static_check.py`
- `scripts/comfy_integration_smoke.py`
- `scripts/scan_custom_nodes.py` — import 없는 custom node 정적 스캐너
- `scripts/scan_custom_nodes.ps1` / `.cmd` — Windows 실행 래퍼
- `scripts/scan_workflow_usage.py` — workflow/PNG/history read-only 사용 증거 스캐너
- `scripts/benchmark_live.py` — queue·cache·wall time·NVML·disk·decoded pixel identity를 확인하는 실제 서버 벤치마크

## 로컬에서만 생성되는 인벤토리 — 공개 패키지 제외

- `docs/CUSTOM_NODE_INVENTORY.json` / `.md`
- `docs/TRACE_COMPATIBILITY_MATRIX.md`
- `docs/ADAPTER_PRIORITY.md`
- `docs/LOCAL_ADAPTER_PLAN.md`
- `docs/WORKFLOW_USAGE_INVENTORY.json` / `.md`
- `docs/LOCAL_ADAPTER_PLAN_FROM_USAGE.md`
- `docs/CUSTOM_NODE_RUNTIME_PATHS.md`
- `docs/USER_DECISION_QUEUE.md`

위 파일은 실제 설치본을 조사한 로컬 증거이며 workflow 이름·출력 경로·repository metadata를 포함할 수 있습니다. `.gitignore` 대상이고 공개 패키지·`SHA256SUMS.txt`에서 제외합니다. `custom_nodes`가 바뀌면 로컬에서 다시 생성합니다.

## 설계/운영 문서

- `docs/CUSTOM_NODE_SCAN_GUIDE.md`
- `docs/CUSTOM_NODE_INVENTORY_SCHEMA.md`
- `docs/PRODUCT_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/PHASES.md`
- `docs/TEST_PLAN.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/ADAPTER_SDK.md`
- `docs/OPERATING_GUIDE.md`
- `docs/GLOSSARY_KO.md`
- `docs/DESIGN_DECISIONS.md`
- `docs/RESEARCH_NOTES_2026-08-12.md`
