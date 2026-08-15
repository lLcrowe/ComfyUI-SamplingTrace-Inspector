# Codex Start Here

1. 이 폴더를 사용자의 실제 ComfyUI `custom_nodes` 아래에 둡니다.
2. **Plugin을 먼저 실행하지 말고**, `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md`부터 수행합니다.
3. `scripts/scan_custom_nodes.py`로 설치된 custom node를 비실행 정적 조사합니다.
4. 생성된 `CUSTOM_NODE_INVENTORY.*`, `TRACE_COMPATIBILITY_MATRIX.md`, `ADAPTER_PRIORITY.md`, `LOCAL_ADAPTER_PLAN.md`를 검토합니다.
5. Priority A 실제 사용 노드 기준으로 `docs/LOCAL_ADAPTER_PLAN.md` 골격을 채웁니다.
6. 그 뒤 `docs/CODEX_PROMPT.md` 전체를 다음 작업 요청으로 사용합니다.
7. 실제 환경 결과는 `docs/LOCAL_VALIDATION.md`에 기록합니다.
8. ComfyUI core, 기존 workflow, 다른 custom node는 사용자 승인 없이 수정하지 않습니다.

핵심 완료 게이트:

```text
Static Custom Node Inventory
→ Local Adapter Plan
→ Plugin import
→ Bottom panel
→ Minimal KSampler
→ Trace On/Off output identity
→ ControlNet
→ Installed LoRA/IPAdapter/Detailer/etc.
→ Compare/Report
→ Performance benchmark
```
