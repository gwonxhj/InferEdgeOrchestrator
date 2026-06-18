# Operation Control Guide

Language: English | [한국어](operation_control.ko.md)

This guide summarizes InferEdgeOrchestrator's runtime operation-control role.
It is intentionally short: use it when reviewing whether new wording still
matches the Runtime Operation Platform v2 boundary.

## Core Definition

InferEdgeOrchestrator is a post-deployment runtime operation control layer for
constrained edge inference workloads. It is not a benchmark tool. It controls
how already-validated inference tasks behave together when queue backlog,
latency spikes, stale input, overload, or fallback pressure appears.

```text
validated workload
-> queue / priority / deadline policy
-> runtime telemetry
-> overload / fallback / drop evidence
-> operation report
-> Lab / AIGuard evidence handoff
```

## What Orchestrator Owns

| Area | Orchestrator evidence |
| --- | --- |
| Queue control | bounded task queues, max queue depth, queue pressure reason |
| Overload handling | load shedding, low-priority drop, stale input drop |
| Latency budget protection | deadline miss, scheduler delay, protected high-priority task context |
| Fallback evidence | fallback decision count, fallback final status, bounded recovery marker |
| Worker health | worker status, runtime event summary, resource pressure context |
| Telemetry evidence | JSON operation summary, compact event rollup, policy decision reason |
| Policy pressure | limited/protected task summary, fallback policy use, backlog-over-threshold markers |

## Handoff Boundaries

Orchestrator can export supplemental operation context through
`edgeenv_runtime_telemetry_feed`. That feed can help EdgeEnv, AIGuard, and Lab
show queue/deadline/fallback/resource context without changing ownership.
The operation timeline may include a policy pressure summary so downstream
reports can show which tasks were limited or protected under backlog pressure.

- EdgeEnv remains the registry, comparability, and runtime regression evidence
  owner.
- AIGuard may provide deterministic runtime warning evidence.
- Lab remains the final deployment decision owner.
- Orchestrator does not calculate EdgeEnv comparability or overwrite Lab
  `deployment_decision`.

## Remote Dispatch Starter Boundary

Remote dispatch is currently a file-based starter contract. It records worker
registry input, task request input, worker selection, bounded fallback evidence,
and optional explicit HTTP/SSH starter evidence.

Allowed wording:

- file-based remote dispatch starter
- worker-selection evidence
- bounded fallback starter evidence
- Smoke/Starter operation evidence

Avoid wording:

- production remote execution
- production remote worker lifecycle
- secure tunnel operation completed
- cloud control plane
- Kubernetes-style orchestration

## What This Is Not

InferEdgeOrchestrator is not:

- Triton replacement
- DeepStream replacement
- Kubernetes replacement
- production inference server
- production observability platform
- general monitoring SaaS
- public benchmark leaderboard
- AI OS or generic AI agent framework

## Jetson Need

Reading this guide, checking README links, or validating committed operation
context fixtures does not require a Jetson device.

A Jetson device is required only when collecting new live device-local evidence,
such as live `tegrastats`, ONNX/TensorRT smoke, or sustained device-local
operation evidence.
