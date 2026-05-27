# InferEdgeOrchestrator Portfolio Brief

Language: English | [한국어](PORTFOLIO.ko.md)

[![CI](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml)

Release: [v0.1.2](https://github.com/gwonxhj/InferEdgeOrchestrator/releases/tag/v0.1.2)

## One-Line Summary

InferEdgeOrchestrator is a post-deployment runtime operation-control layer for
edge inference. It keeps high-priority tasks responsive under multi-task
overload using priority/deadline-aware scheduling, bounded queues, adaptive load
shedding, and runtime telemetry.

## Problem

On constrained edge devices, multiple inference workloads often run together:
for example, a detector, OCR task, and classifier sharing CPU/GPU/NPU, memory,
and thermal budget. If every task is treated equally, low-priority work can
create queue backlog, stale frame processing, latency spikes, and budget
violations for real-time tasks.

The project focuses on the runtime operation problem after deployment: deciding
which task should run, which frames can be dropped, which workload is being
protected, and what evidence should be recorded when overload appears.

## Solution

InferEdgeOrchestrator models edge inference operation as an explicit scheduling
loop:

```text
Input Source
-> Frame Router
-> Bounded Task Queues
-> Priority + Deadline-Aware Scheduler
-> Inference Worker
-> Result Aggregator
-> Telemetry Logger
```

Each task is configured with `priority`, `target_fps`, `latency_budget_ms`,
`queue_size`, `drop_policy`, and `worker`. The scheduler prefers high-priority
and deadline-sensitive work, while load shedding drops low-priority or stale
frames when queue pressure grows.

## Architecture

| Module | Responsibility |
| --- | --- |
| Config | Defines task policy and worker selection |
| Input source | Generates dummy frames or routes image/video file payloads |
| Task queue | Maintains bounded per-task queues and overflow drop policy |
| Scheduler | Chooses the next task using priority and deadline pressure |
| Worker | Runs `dummy`, `onnxruntime`, or TensorRT-backed inference behind a shared interface |
| Policy | Applies load shedding to low-priority backlog |
| Monitor | Captures process resource snapshots and parses Jetson `tegrastats` |
| Telemetry | Exports executed/dropped counts, latency, backlog, result events, resource snapshots, and policy decisions |
| CLI | Provides `run`, `report`, `compare-overload`, and `from-inferedge` commands |

## Core Technical Decisions

- Use bounded queues instead of unbounded buffering so stale frames do not
  silently destroy real-time behavior.
- Treat dropping low-priority frames as a deliberate stability policy, not as a
  failure condition.
- Do not silently drop work; record overload decisions and scheduling behavior
  as structured telemetry evidence.
- Keep the worker interface stable so scheduler logic stays independent from
  dummy inference, ONNX Runtime, or TensorRT-backed workers.
- Record policy decisions in telemetry so claims about overload control are
  backed by execution evidence.
- Keep InferEdge integration file-based through `result.json` to avoid coupling
  deployment validation code with runtime operation control.

## Validation Evidence

| Evidence | Result |
| --- | --- |
| Scheduler/load shedding tests | Pytest covers priority scheduling, deadline ordering, bounded queue behavior, drop policy, telemetry, and InferEdge config handoff |
| Synthetic overload comparison | Detector p95 end-to-end latency improved from `782.0ms` FIFO baseline to `8.0ms` with scheduler + load shedding; low-priority classifier dropped `16` frames |
| Jetson dummy smoke | `nano01` generated telemetry, resource snapshots, and low-priority drops with detector `20/0` and classifier `2/18` executed/dropped |
| Jetson ONNX Runtime smoke | ONNX Runtime `1.23.2` worker executed identity ONNX on Jetson with `CPUExecutionProvider`, output shape `[1, 2]`, and 13 `tegrastats` samples |
| Jetson TensorRT inference smoke | Local identity ONNX was built into a TensorRT engine and executed through the TensorRT worker, with backend metadata recorded in runtime telemetry |
| Jetson TensorRT contention smoke | TensorRT-backed high/low-priority tasks ran through scheduler/load shedding on Jetson; low-priority work was shed while TensorRT backend metadata remained visible |
| Jetson TensorRT diverse contention smoke | Distinct generated detector/classifier TensorRT engines produced scheduler/load-shedding evidence: detector `6/0`, classifier `1/5` executed/dropped, `5` overload events |
| Remote dispatch starter | File-based worker registry and task request contract produce worker-selection, bounded fallback, compact event-summary, and Lab/AIGuard-facing starter evidence without claiming production remote execution |
| CI | GitHub Actions runs Python 3.11 pytest plus installed-package CLI smoke for `run`, `report`, and `compare-overload` |
| Release | `v0.1.2` captures the TensorRT evidence and portfolio wording patch snapshot |

Sample telemetry artifacts are available in `examples/telemetry/` for reviewers
who want to inspect the JSON evidence shape without running the CLI.

## Relationship With InferEdge

InferEdge and InferEdgeOrchestrator cover different lifecycle stages.

| Layer | Project | Role |
| --- | --- | --- |
| Validation | InferEdgeForge | Model conversion and build provenance |
| Validation | InferEdge-Runtime | Device execution and `result.json` creation |
| Validation | InferEdgeLab | Result comparison and deployment decision |
| Validation | InferEdgeAIGuard | Optional anomaly/risk/recommendation analysis |
| Comparability | InferEdgeEnv | v0.1.5 v1-complete run evidence registry and comparability judgement |
| Operation | InferEdgeOrchestrator | Runtime scheduling, queue control, load shedding, and telemetry after deployment |

The boundary is:

```text
InferEdge = deployment validation pipeline
InferEdgeEnv = benchmark evidence comparability layer
InferEdgeOrchestrator = runtime operation control layer
```

The integration remains artifact-based:

```text
InferEdge result.json -> recommended Orchestrator task config
```

Remote dispatch remains a starter boundary. Orchestrator owns worker-selection
and runtime operation evidence; AIGuard can add deterministic warning context
when that evidence is passed downstream; Lab owns the final deployment
decision.

## What This Is Not

- Not a Triton or DeepStream replacement.
- Not a benchmark tool focused on average latency competition.
- Not a distributed serving platform.
- Not Kubernetes, cloud deployment, or multi-device orchestration.
- Not TensorRT/GPU throughput benchmark evidence. TensorRT work here validates
  worker integration, scheduler/load-shedding behavior, and telemetry under
  Jetson contention.

## Interview Talking Points

- I separated deployment validation from runtime operation control so the
  ecosystem has a clear lifecycle boundary.
- I used bounded queues and load shedding because edge systems must sometimes
  drop less important work to protect real-time tasks.
- I validated scheduler behavior with deterministic overload scenarios rather
  than presenting unstable device timings as benchmark claims.
- I kept telemetry central because the interesting engineering question is not
  just what ran, but why the scheduler dropped or protected a task.
- I added Jetson smoke validation to prove the CLI, telemetry path, resource
  snapshots, ONNX Runtime path, and TensorRT-backed contention path run on
  physical edge hardware.
