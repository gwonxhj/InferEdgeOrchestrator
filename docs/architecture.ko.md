# InferEdgeOrchestrator Architecture

Language: [English](architecture.md) | 한국어

InferEdgeOrchestrator는 제한된 Edge 디바이스를 위한 lightweight runtime
operation-control layer다. 모델이 배포 가능한지 판단하지 않고, 배포 이후
여러 inference task가 제한된 runtime capacity를 공유할 때 priority
scheduling, bounded queue, load shedding, worker abstraction, telemetry로
운영을 제어한다.

## Architecture Summary

현재 구현은 작고 명시적인 구조를 유지한다.

- `config.py`는 task와 run의 runtime contract를 정의한다.
- `runtime.py`는 input, queue, scheduler, policy, worker, monitor, telemetry를
  하나의 실행 loop로 연결한다.
- `task_queue.py`, `scheduler.py`, `policy.py`는 overload-control 동작을
  구현한다.
- `workers.py`는 dummy worker와 ONNX Runtime worker를 같은 interface 뒤에
  분리한다.
- `telemetry.py`는 scheduler decision을 설명하기 위한 operational evidence를
  기록한다.

즉, 이 프로젝트는 범용 inference server가 아니라 edge inference를 위한 runtime
operation-control layer다.

## Runtime Flow

```text
Input Source
-> Frame Router
-> Bounded Task Queues
-> Priority + Deadline-Aware Scheduler
-> Inference Worker
-> Result Aggregator
-> Telemetry Logger
```

코드 기준으로 `OrchestratorRuntime.run()`은 다음 흐름을 수행한다.

1. 시작 resource snapshot을 기록한다.
2. 설정된 input source에서 각 task용 frame envelope를 생성한다.
3. frame을 task별 bounded queue에 넣는다.
4. queue overflow drop, backlog, load-shedding decision을 기록한다.
5. `PriorityScheduler`로 실행할 queued task 하나를 선택한다.
6. 선택된 task를 `WorkerPool`로 실행한다.
7. execution latency, result metadata, backlog, drop, policy event를 기록한다.
8. 필요하면 남은 backlog를 drain한다.
9. 종료 resource snapshot을 기록하고 telemetry JSON을 export한다.

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `config.py` | JSON/YAML config를 읽고 `priority`, `target_fps`, `latency_budget_ms`, `queue_size`, `drop_policy`, `worker` 같은 task policy field를 검증한다. |
| `frames.py` | `dummy`, `image`, `video` source 설정에서 deterministic frame envelope를 만든다. 현재 image/video input은 scheduler 내부에서 frame decoding을 하지 않고 file metadata를 worker로 전달한다. |
| `task_queue.py` | task별 bounded queue를 유지하고 `drop_oldest`, `drop_newest` queue-overflow drop을 기록한다. |
| `scheduler.py` | 비어 있지 않은 queue 중 priority, frame deadline, frame creation time 순서로 다음 task를 선택한다. |
| `policy.py` | backlog threshold를 초과하면 가장 높은 priority의 backlogged task를 보호하면서 low-priority queued frame을 drop한다. |
| `workers.py` | 안정적인 `Worker.run(task, frame)` interface 뒤에 `DummyWorker`, `OnnxRuntimeWorker`, `WorkerPool`을 제공한다. |
| `telemetry.py` | executed/dropped count, mean/p95 latency, queue backlog, schedule decision, policy decision, overload event, result event, resource snapshot을 집계한다. |
| `monitor.py` | 가능하면 `psutil`로 process resource snapshot을 기록하고, 없으면 `resource`로 fallback한다. Jetson smoke artifact용 `tegrastats` line parser도 제공한다. |
| `runtime.py` | end-to-end runtime loop를 조율하고 telemetry report를 쓴다. |
| `scenarios.py` | FIFO baseline과 scheduler/load-shedding 동작을 비교하는 synthetic overload scenario를 실행한다. |
| `inferedge_adapter.py` | InferEdge 내부를 import하지 않고 `result.json` latency signal을 Orchestrator task config 초기값으로 변환한다. |
| `cli.py` | `run`, `report`, `compare-overload`, `from-inferedge` command를 제공한다. |

## Scheduler Policy

`PriorityScheduler.choose_next()`는 queued frame이 있는 task만 후보로 본다.
정렬 기준은 다음과 같다.

1. 더 높은 `priority`.
2. 더 이른 `deadline_at_ms`.
3. 더 이른 `created_at_ms`.
4. 안정적인 tie-breaker로 task name.

scheduler는 의도적으로 단순하다. 다음에 실행할 task를 선택하고, 어떤 work를
제거할지는 bounded queue와 load shedding policy가 담당한다.

## Queue And Drop Policy

각 task는 `queue_size`로 제한되는 별도 bounded queue를 가진다.

queue가 가득 찼을 때:

- `drop_oldest`는 가장 오래된 queued frame을 제거하고 새 frame을 받는다.
- `drop_newest`는 들어오는 frame을 거부한다.
- `drop_low_priority`는 config contract에는 포함되어 있지만, 현재 queue
  overflow에서는 newest-frame rejection으로 처리된다. low-priority shedding은
  `LoadSheddingPolicy`가 담당한다.

drop은 조용히 사라지지 않는다. queue overflow나 policy-driven drop은 모두
task, frame id, reason을 가진 `drop_events` telemetry로 남아 run 이후에도
overload behavior를 설명할 수 있게 한다.

## Load Shedding Policy

`LoadSheddingPolicy.apply()`는 total backlog가
`overload_backlog_threshold`를 초과할 때 실행된다.

현재 동작:

- backlog가 있는 task 중 가장 priority가 높은 task를 protected task로 정한다.
- task를 low priority에서 high priority 순서로 순회한다.
- protected task를 제외한 low-priority queue에서 oldest frame을 하나씩 drop해
  backlog를 threshold 아래로 낮춘다.
- shedding action마다 policy decision과 overload event를 기록한다.

이 방식은 overload 상황에서 어떤 work를 포기했고 어떤 task를 보호했는지
telemetry로 설명할 수 있게 만든다.

## Worker Interface

worker는 같은 contract를 구현한다.

```python
class Worker(Protocol):
    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        ...
```

지원 worker:

- `dummy`: deterministic simulated latency와 result metadata를 반환한다.
  scheduler test와 overload-policy validation에 사용한다.
- `onnxruntime`: ONNX model을 lazy loading하고 `CPUExecutionProvider`로 실행한
  뒤 output count와 output shape를 기록한다.
- `tensorrt`: `engine_path`를 검증하고, TensorRT를 lazy import하며, 설정된 engine을
  deserialize하고 execution context를 생성한 뒤 둘 다 engine path 기준으로 cache한다.
  또한 TensorRT name-based input/output tensor metadata를 기록하고, host/device
  buffer를 할당하며, TensorRT tensor address를 bind한 뒤 buffer를 engine path
  기준으로 cache한다. TensorRT `execute_async_v3`로 실행하고 device output을 host
  buffer로 복사한 뒤 backend result metadata를 반환한다.

고정된 worker interface 덕분에 TensorRT path를 확장하더라도 scheduler, queue,
telemetry contract를 바꾸지 않아도 된다.

TensorRT/GPU backend 방향과 현재 binding/execution boundary는
[`docs/tensorrt_backend.ko.md`](tensorrt_backend.ko.md)에 기록한다.

## Telemetry Schema Overview

telemetry JSON은 runtime behavior를 설명하는 핵심 evidence artifact다.

top-level field:

- `run`: configured run name 같은 run metadata.
- `tasks`: task별 `executed`, `dropped`, `mean_latency_ms`,
  `p95_latency_ms`, `max_queue_backlog`.
- `overload_events`: policy decision에서 파생된 load-shedding event.
- `policy_decisions`: 어떤 task를 제한했고 어떤 task를 보호했는지에 대한 기록.
- `drop_events`: task, frame id, reason을 가진 queue/policy drop 기록.
- `result_events`: latency와 output summary를 포함한 worker result metadata.
- `resource_snapshots`: start/end process resource snapshot.
- `schedule_decisions`: 각 execution에서 선택된 task와 scheduling reason.

versioned sample telemetry artifact는
[`examples/telemetry/`](../examples/telemetry/README.ko.md)에 있다.

## Resource Monitor And Jetson Smoke Boundary

`ResourceMonitor`는 의도적으로 lightweight하게 유지한다. `psutil`이 설치되어
있으면 process-level memory와 optional CPU/memory percentage를 기록하고,
없으면 `resource.getrusage()`로 fallback한다.

Jetson-specific `tegrastats` 연동은 smoke-test evidence로 다룬다.

- `monitor.parse_tegrastats_line()`은 capture된 `tegrastats` line을 parsing한다.
- `scripts/smoke_jetson_dummy.sh`는 Jetson에서 scheduler telemetry 생성을
  검증한다.
- `scripts/smoke_jetson_onnx.sh`는 Jetson에서 ONNX Runtime worker path를
  검증한다.

현재 Jetson 기록은 smoke validation과 TensorRT-backed scheduler/load-shedding
evidence이지 GPU나 TensorRT throughput benchmark가 아니다.

## InferEdge Integration Boundary

InferEdge와 InferEdgeOrchestrator는 서로 다른 lifecycle stage를 담당한다.

- InferEdge는 Forge, Runtime, Lab, optional AIGuard analysis로 deployment
  readiness를 검증한다.
- InferEdgeOrchestrator는 deployment 이후 runtime behavior를 제어한다.

integration boundary는 file-based다. `inferedge_adapter.py`는 InferEdge
`result.json`을 읽고 `expected_latency_ms` 같은 latency signal을 추출해
Orchestrator task config의 초기 `latency_budget_ms`를 추천한다.

InferEdge repository를 직접 import하지 않는다. validation과 operation control은
artifact로 연결하되 repository separation을 유지한다.

## Non-Goals

InferEdgeOrchestrator는 다음을 목표로 하지 않는다.

- 평균 latency 측정 자체가 목적인 benchmark tool.
- Triton 또는 DeepStream 대체제.
- distributed serving platform.
- Kubernetes 또는 cloud deployment orchestrator.
- multi-device scheduler.
- TensorRT throughput/performance benchmark.

프로젝트의 목표는 maximum-throughput serving이 아니다. 제한된 edge inference
workload에서 inference behavior를 제어 가능하게 만들기 위해 명시적이고 테스트
가능한 scheduling, load shedding, telemetry를 보여주는 것이다.
