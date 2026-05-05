# InferEdgeOrchestrator Portfolio Brief

Language: [English](PORTFOLIO.md) | 한국어

[![CI](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml)

Release: [v0.1.0](https://github.com/gwonxhj/InferEdgeOrchestrator/releases/tag/v0.1.0)

## One-Line Summary

InferEdgeOrchestrator는 제한된 Edge 환경에서 여러 inference task가 동시에
실행될 때 priority/deadline-aware scheduling, bounded queue, adaptive load
shedding, runtime telemetry로 high-priority task의 응답성을 보호하는
lightweight edge inference runtime scheduler다.

## Problem

제한된 Edge 디바이스에서는 detector, OCR, classifier 같은 inference workload가
CPU/GPU/NPU, memory, thermal budget을 공유하며 동시에 실행되는 경우가 많다.
모든 task를 동일하게 처리하면 low-priority work가 queue backlog를 만들고,
stale frame 처리, latency spike, real-time task의 latency budget 위반이
발생할 수 있다.

이 프로젝트는 배포 이후 runtime operation 문제에 집중한다. 즉, overload가
발생했을 때 어떤 task를 먼저 실행하고, 어떤 frame을 drop할 수 있으며, 그
결정을 어떤 telemetry evidence로 남길지를 다룬다.

## Solution

InferEdgeOrchestrator는 edge inference operation을 명시적인 scheduling loop로
모델링한다.

```text
Input Source
-> Frame Router
-> Bounded Task Queues
-> Priority + Deadline-Aware Scheduler
-> Inference Worker
-> Result Aggregator
-> Telemetry Logger
```

각 task는 `priority`, `target_fps`, `latency_budget_ms`, `queue_size`,
`drop_policy`, `worker`로 정의된다. scheduler는 high-priority와
deadline-sensitive work를 우선하고, queue pressure가 커지면 load shedding이
low-priority 또는 stale frame을 drop한다.

## Architecture

| Module | Responsibility |
| --- | --- |
| Config | task policy와 worker selection 정의 |
| Input source | dummy frame 생성 또는 image/video file payload routing |
| Task queue | task별 bounded queue와 overflow drop policy 관리 |
| Scheduler | priority와 deadline pressure로 다음 task 선택 |
| Worker | 공통 interface 뒤에서 `dummy`, `onnxruntime` inference 실행 |
| Policy | low-priority backlog에 load shedding 적용 |
| Monitor | process resource snapshot 기록 및 Jetson `tegrastats` parsing |
| Telemetry | executed/dropped count, latency, backlog, result event, resource snapshot, policy decision export |
| CLI | `run`, `report`, `compare-overload`, `from-inferedge` command 제공 |

## Core Technical Decisions

- unbounded buffering 대신 bounded queue를 사용해 stale frame이 real-time
  behavior를 조용히 망가뜨리지 않게 했다.
- low-priority frame drop을 실패가 아니라 안정성을 위한 의도적 policy로
  다뤘다.
- worker interface를 고정해 scheduler logic이 dummy inference, ONNX Runtime,
  향후 TensorRT-style worker와 분리되도록 했다.
- overload control 주장을 telemetry evidence로 뒷받침하기 위해 policy
  decision을 기록했다.
- InferEdge integration은 `result.json` 기반 file handoff로 유지해 deployment
  validation code와 runtime operation control code가 강하게 결합되지 않게 했다.

## Validation Evidence

| Evidence | Result |
| --- | --- |
| Scheduler/load shedding tests | priority scheduling, deadline ordering, bounded queue, drop policy, telemetry, InferEdge config handoff를 pytest로 검증 |
| Synthetic overload comparison | detector p95 end-to-end latency가 FIFO baseline `782.0ms`에서 scheduler + load shedding `8.0ms`로 개선, low-priority classifier frame 16개 drop |
| Jetson dummy smoke | `nano01`에서 telemetry, resource snapshot, low-priority drop 생성 확인, detector `20/0`, classifier `2/18` executed/dropped |
| Jetson ONNX Runtime smoke | Jetson에서 ONNX Runtime `1.23.2` worker가 `CPUExecutionProvider`로 identity ONNX 실행, output shape `[1, 2]`, `tegrastats` sample 13개 기록 |
| CI | GitHub Actions가 PR과 `main` push에서 Python 3.11 기준 `python -m pytest` 실행 |
| Release | `v0.1.0`으로 첫 portfolio-ready snapshot 고정 |

CLI를 실행하지 않아도 JSON evidence 형태를 확인할 수 있도록
`examples/telemetry/`에 sample telemetry artifact를 제공한다.

## Relationship With InferEdge

InferEdge와 InferEdgeOrchestrator는 서로 다른 lifecycle stage를 담당한다.

| Layer | Project | Role |
| --- | --- | --- |
| Validation | InferEdgeForge | model conversion, build provenance |
| Validation | InferEdge-Runtime | device execution, `result.json` 생성 |
| Validation | InferEdgeLab | result comparison, deployment decision |
| Validation | InferEdgeAIGuard | optional anomaly/risk/recommendation analysis |
| Operation | InferEdgeOrchestrator | 배포 이후 runtime scheduling, queue control, load shedding, telemetry |

경계는 다음과 같다.

```text
InferEdge = deployment validation pipeline
InferEdgeOrchestrator = runtime operation control layer
```

integration은 artifact 기반으로 유지한다.

```text
InferEdge result.json -> recommended Orchestrator task config
```

## What This Is Not

- Triton 또는 DeepStream 대체제가 아니다.
- 평균 latency 경쟁을 위한 benchmark tool이 아니다.
- distributed serving platform이 아니다.
- Kubernetes, cloud deployment, multi-device orchestration 프로젝트가 아니다.
- TensorRT/GPU benchmark evidence가 아니다. 현재 Jetson ONNX smoke는
  `CPUExecutionProvider` 기반 ONNX Runtime worker path 검증이다.

## Interview Talking Points

- deployment validation과 runtime operation control을 분리해 ecosystem의
  lifecycle boundary를 명확히 했다.
- Edge system에서는 중요한 real-time task를 보호하기 위해 덜 중요한 work를
  drop해야 할 수 있으므로 bounded queue와 load shedding을 사용했다.
- 불안정한 device timing을 benchmark claim으로 포장하지 않고 deterministic
  overload scenario로 scheduler behavior를 검증했다.
- 단순히 무엇이 실행됐는지가 아니라 왜 특정 task가 drop/protect 되었는지를
  남기기 위해 telemetry를 중심에 두었다.
- Jetson smoke validation으로 CLI, telemetry path, resource snapshot, ONNX
  Runtime worker path가 실제 Edge hardware에서 동작함을 확인했다.
