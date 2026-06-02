# Operation Control 한국어 Quick Guide

Language: [English](operation_control.md) | 한국어

이 문서는 InferEdgeOrchestrator의 runtime operation control 역할을 빠르게
확인하기 위한 안내서다. Runtime Operation Platform v2 기준에서 문구가
역할 경계를 벗어나지 않는지 검토할 때 사용한다.

## 핵심 정의

InferEdgeOrchestrator는 제한된 edge inference workload를 위한 deployment 이후
runtime operation control layer다. benchmark tool이 아니다. 이미 validation을
거친 inference task들이 queue backlog, latency spike, stale input, overload,
fallback 압력을 만났을 때 함께 어떻게 동작하는지 제어하고 evidence로 남긴다.

```text
validated workload
-> queue / priority / deadline policy
-> runtime telemetry
-> overload / fallback / drop evidence
-> operation report
-> Lab / AIGuard evidence handoff
```

## Orchestrator가 소유하는 evidence

| 영역 | Orchestrator evidence |
| --- | --- |
| Queue control | bounded task queue, max queue depth, queue pressure reason |
| Overload handling | load shedding, low-priority drop, stale input drop |
| Latency budget protection | deadline miss, scheduler delay, high-priority task 보호 context |
| Fallback evidence | fallback decision count, fallback final status, bounded recovery marker |
| Worker health | worker status, runtime event summary, resource pressure context |
| Telemetry evidence | JSON operation summary, compact event rollup, policy decision reason |

## Handoff 경계

Orchestrator는 `edgeenv_runtime_telemetry_feed`를 통해 supplemental operation
context를 export할 수 있다. 이 feed는 EdgeEnv, AIGuard, Lab이
queue/deadline/fallback/resource context를 표시하는 데 도움을 주지만 ownership을
바꾸지 않는다.

- EdgeEnv는 registry, comparability, runtime regression evidence owner로 남는다.
- AIGuard는 deterministic runtime warning evidence를 제공할 수 있다.
- Lab remains the final deployment decision owner.
- Orchestrator는 EdgeEnv comparability를 계산하지 않고 Lab
  `deployment_decision`을 덮어쓰지 않는다.

## Remote Dispatch Starter 경계

Remote dispatch는 현재 file-based starter contract다. worker registry input,
task request input, worker selection, bounded fallback evidence, optional
HTTP/SSH starter evidence를 기록한다.

허용 표현:

- file-based remote dispatch starter
- worker-selection evidence
- bounded fallback starter evidence
- Smoke/Starter operation evidence

피해야 할 표현:

- production remote execution
- production remote worker lifecycle
- secure tunnel operation completed
- cloud control plane
- Kubernetes-style orchestration

## 이것이 아닌 것

InferEdgeOrchestrator는 다음이 아니다.

- Triton replacement
- DeepStream replacement
- Kubernetes replacement
- production inference server
- production observability platform
- general monitoring SaaS
- public benchmark leaderboard
- AI OS 또는 generic AI agent framework

## Jetson 필요 여부

이 문서를 읽거나 README link, committed operation context fixture를 검증하는
작업에는 Jetson 기기가 필요 없다.

새 live device-local evidence를 수집할 때만 Jetson 기기가 필요하다. 예를 들면
live `tegrastats`, ONNX/TensorRT smoke, sustained device-local operation evidence
수집 단계가 여기에 해당한다.
