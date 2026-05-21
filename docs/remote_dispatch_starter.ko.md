# Remote Dispatch Starter

Language: [English](remote_dispatch_starter.md) | 한국어

InferEdgeOrchestrator는 Runtime Operation Platform 로드맵을 위한 작은
file-based remote dispatch starter를 포함한다. 목적은 production remote
execution을 주장하는 것이 아니라, remote edge worker handoff contract를 먼저
고정하는 것이다. 기본값은 계속 plan-only이며, `--execute-plan`을 명시했을 때만
작은 HTTP/SSH starter 호출을 시도하고 결과를 structured evidence로 기록한다.

## 범위

이 starter가 답하는 질문은 하나다.

> remote worker registry와 task request가 있을 때, 어떤 edge worker에 task를
> 보내야 하며 그 이유는 무엇인가?

`--execute-plan`을 사용하지 않으면 network socket이나 SSH 실행을 수행하지
않는다. `--execute-plan`을 명시하면 선택된 worker가 선언한 단일 HTTP POST 또는
SSH command starter를 실행할 수 있다. 이 starter 실행이 task request의
`retry_policy.fallback_on`에 포함된 오류로 실패하고 `max_attempts`가 허용하면,
eligible fallback worker에 대해 제한된 starter attempt를 한 번 수행할 수 있다.
Cloudflare tunnel, auth, heartbeat, long-lived production worker, production retry
orchestration 관리는 여전히 future hardening이다.

## 입력

Worker registry:

- schema: `inferedge-remote-worker-registry-v1`
- 예시: [`examples/remote_worker_registry.json`](../examples/remote_worker_registry.json)

Task request:

- schema: `inferedge-remote-task-request-v1`
- 예시: [`examples/remote_task_request.json`](../examples/remote_task_request.json)
- local HTTP 예시:
  [`examples/remote_task_request_http_local.json`](../examples/remote_task_request_http_local.json)

starter는 다음 항목을 기준으로 worker를 선택한다.

- worker online/offline 상태
- health state: `healthy` 또는 `constrained`
- required backend 또는 worker type
- target device
- task request의 optional retry policy

Fallback starter execution은 의도적으로 좁게 유지한다.

- primary worker를 eligible worker 중 먼저 선택한다.
- `max_attempts`가 fallback starter attempt 허용 여부를 결정한다.
- `fallback_on`이 어떤 primary error category에서 fallback을 시도할지 결정한다.
- fallback attempt는 `fallback_execution_result`에 기록된다.
- fallback execution은 evidence collection이며 production-grade retry control이 아니다.

## 실행

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json
```

명시적 starter 실행:

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json \
  --execute-plan \
  --timeout-sec 5
```

Local HTTP worker starter:

```bash
python3 scripts/remote_http_worker.py --host 127.0.0.1 --port 8765
```

다른 터미널에서:

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry_http_local.json \
  --request examples/remote_task_request_http_local.json \
  --output reports/remote_dispatch_http_local.json \
  --execute-plan \
  --timeout-sec 2
```

이 경로는 의도적으로 작게 유지한다. HTTP worker endpoint가 structured task
request를 받고 structured starter response를 반환할 수 있음을 검증하지만,
heartbeat, auth, fallback worker에 대한 retry execution, long-lived production
worker process를 제공하지 않는다.

예상 출력:

```json
{
  "schema_version": "inferedge-remote-dispatch-result-v1",
  "dispatch_status": "accepted",
  "selected_worker_id": "jetson-nano-01",
  "remote_execution": {
    "mode": "file_contract_starter",
    "production_remote_execution": false,
    "execution_requested": false
  },
  "remote_operation_summary": {
    "schema_version": "inferedge-remote-operation-summary-v1",
    "dispatch_status": "accepted",
    "final_status": "skipped",
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
- eligible/rejected worker 이유를 포함한 worker selection evidence
- primary/fallback worker id를 포함한 retry/fallback plan
- `plan_only` mode의 remote execution plan
- skipped/succeeded/failed starter execution을 나타내는 remote execution result
- dispatch, execution, fallback, final starter status evidence를 압축한
  remote operation summary

이 출력은 remote execution path가 starter contract를 넘어 확장될 때 AIGuard와
Lab report의 입력으로 연결될 수 있다.

starter는 기본적으로 execution planning만 기록하고 network connection은 열지
않는다. 선택된 worker가 `ssh_command` 또는 `http_request` 같은
`endpoint_type`을 선언하면 출력에는 planned transport가 `ssh` 또는 `http`로
기록되지만, `--execute-plan`을 명시하기 전까지 `network_execution_performed`는
계속 `false`다.

실행이 요청되면 다음처럼 동작한다.

- `http_request`는 task request를 `metadata.endpoint_url`로 POST한다.
- `ssh_command`는 `metadata.ssh_host`에서 `metadata.ssh_command`를 실행한다.
- `scripts/remote_http_worker.py`는 repeatable success-path smoke validation을
  위한 local HTTP starter endpoint를 제공한다.
- timeout, connection failure, HTTP error, command failure는 unstructured crash가
  아니라 `remote_execution_result`에 기록된다.
- primary starter가 실패하고 retry policy가 허용하면 `fallback_execution_result`에
  attempted fallback worker, status, transport, final starter outcome을 기록한다.
- `remote_operation_summary`는 dispatch status, selected worker health state,
  eligible/rejected worker count, primary execution status, fallback recovery
  status, `final_status`를 downstream registry/report ingestion에 필요한 compact
  operation evidence로 기록한다.
- fallback execution은 starter evidence로만 제한한다. production-grade retry,
  heartbeat, failover state, worker lifecycle management는 future hardening이다.

이 recovery path의 작은 curated sample은
[`examples/telemetry/remote_fallback_recovery_sample.json`](../examples/telemetry/remote_fallback_recovery_sample.json)에
있다. 이 sample은 primary HTTP starter `connection_error`, 성공한 fallback
starter attempt, retry/fallback plan field, AIGuard/Lab이 기대하는 downstream
`remote_execution_recovered_by_fallback` signal을 기록한다. 이 sample은 문서용
evidence이며 benchmark나 production retry claim이 아니다.

## Boundary

정확한 표현을 유지한다.

- 허용: "file-based remote dispatch starter"
- 허용: "remote worker selection contract"
- 허용: "remote execution plan-only starter"
- 허용: "explicit HTTP/SSH remote execution starter"
- 피할 표현: "production remote execution"
- 피할 표현: "distributed scheduler"
- 피할 표현: "cloud orchestration"
