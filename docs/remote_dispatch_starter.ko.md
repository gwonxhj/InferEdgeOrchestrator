# Remote Dispatch Starter

Language: [English](remote_dispatch_starter.md) | 한국어

InferEdgeOrchestrator는 Runtime Operation Platform 로드맵을 위한 작은
file-based remote dispatch starter를 포함한다. 목적은 production remote
execution을 주장하는 것이 아니라, remote edge worker handoff contract를 먼저
고정하는 것이다.

## 범위

이 starter가 답하는 질문은 하나다.

> remote worker registry와 task request가 있을 때, 어떤 edge worker에 task를
> 보내야 하며 그 이유는 무엇인가?

현재 단계에서는 network socket, SSH 실행, Cloudflare tunnel, long-lived
production worker 관리를 수행하지 않는다. 해당 항목은 future hardening이다.

## 입력

Worker registry:

- schema: `inferedge-remote-worker-registry-v1`
- 예시: [`examples/remote_worker_registry.json`](../examples/remote_worker_registry.json)

Task request:

- schema: `inferedge-remote-task-request-v1`
- 예시: [`examples/remote_task_request.json`](../examples/remote_task_request.json)

starter는 다음 항목을 기준으로 worker를 선택한다.

- worker online/offline 상태
- health state: `healthy` 또는 `constrained`
- required backend 또는 worker type
- target device

## 실행

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json
```

예상 출력:

```json
{
  "schema_version": "inferedge-remote-dispatch-result-v1",
  "dispatch_status": "accepted",
  "selected_worker_id": "jetson-nano-01",
  "remote_execution": {
    "mode": "file_contract_starter",
    "production_remote_execution": false
  }
}
```

## 출력 Contract

결과에는 다음이 보존된다.

- dispatch status
- selected worker id
- decision reason
- 원본 task request
- worker health snapshot
- selected 또는 rejected dispatch를 나타내는 runtime event

이 출력은 remote execution path가 starter contract를 넘어 확장될 때 AIGuard와
Lab report의 입력으로 연결될 수 있다.

## Boundary

정확한 표현을 유지한다.

- 허용: "file-based remote dispatch starter"
- 허용: "remote worker selection contract"
- 피할 표현: "production remote execution"
- 피할 표현: "distributed scheduler"
- 피할 표현: "cloud orchestration"
