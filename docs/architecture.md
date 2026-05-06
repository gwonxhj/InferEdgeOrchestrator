# InferEdgeOrchestrator Architecture

Language: English | [한국어](architecture.ko.md)

InferEdgeOrchestrator is a lightweight runtime operation-control layer for
constrained edge devices. It does not decide whether a model is deployable.
Instead, it controls how multiple deployed inference tasks share limited runtime
capacity through priority scheduling, bounded queues, load shedding, worker
abstraction, and telemetry.

## Architecture Summary

The current implementation is intentionally small and explicit:

- `config.py` defines the runtime contract for tasks and runs.
- `runtime.py` wires input, queues, scheduling, policy, workers, monitoring, and
  telemetry into one execution loop.
- `task_queue.py`, `scheduler.py`, and `policy.py` implement the overload-control
  behavior.
- `workers.py` isolates dummy and ONNX Runtime execution behind the same worker
  interface.
- `telemetry.py` records the operational evidence needed to explain scheduler
  decisions.

This makes the project a scheduler-focused edge runtime, not a general inference
server.

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

In code, `OrchestratorRuntime.run()` performs this flow:

1. Capture a start resource snapshot.
2. Generate frame envelopes for each task from the configured input source.
3. Enqueue frames into per-task bounded queues.
4. Record queue overflow drops, backlog, and load-shedding decisions.
5. Select one queued task with `PriorityScheduler`.
6. Execute the selected task with `WorkerPool`.
7. Record execution latency, result metadata, backlog, drops, and policy events.
8. Optionally drain remaining backlog.
9. Capture an end resource snapshot and export telemetry JSON.

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `config.py` | Loads JSON/YAML config and validates task policy fields such as `priority`, `target_fps`, `latency_budget_ms`, `queue_size`, `drop_policy`, and `worker`. |
| `frames.py` | Builds deterministic frame envelopes from `dummy`, `image`, or `video` source settings. Image/video inputs currently route file metadata to workers rather than decoding frames inside the scheduler. |
| `task_queue.py` | Maintains per-task bounded queues and records queue-overflow drops with `drop_oldest` or `drop_newest` behavior. |
| `scheduler.py` | Chooses the next task from non-empty queues using priority first, then frame deadline, then frame creation time. |
| `policy.py` | Applies backlog-threshold load shedding by dropping low-priority queued frames while protecting the highest-priority backlogged task. |
| `workers.py` | Provides `DummyWorker`, `OnnxRuntimeWorker`, and `WorkerPool` behind a stable `Worker.run(task, frame)` interface. |
| `telemetry.py` | Aggregates executed/dropped counts, mean and p95 latency, queue backlog, schedule decisions, policy decisions, overload events, result events, and resource snapshots. |
| `monitor.py` | Captures process resource snapshots with `psutil` when available, falls back to `resource`, and parses Jetson `tegrastats` lines for smoke-test artifacts. |
| `runtime.py` | Coordinates the end-to-end runtime loop and writes telemetry reports. |
| `scenarios.py` | Runs the synthetic overload comparison between FIFO baseline and scheduler/load-shedding behavior. |
| `inferedge_adapter.py` | Converts InferEdge `result.json` latency signals into an initial Orchestrator task config without importing InferEdge internals. |
| `cli.py` | Exposes `run`, `report`, `compare-overload`, and `from-inferedge` commands. |

## Scheduler Policy

`PriorityScheduler.choose_next()` considers only tasks with queued frames. It
sorts candidates by:

1. Higher `priority`.
2. Earlier `deadline_at_ms`.
3. Earlier `created_at_ms`.
4. Task name as a stable tie-breaker.

The scheduler is deliberately simple: it selects the next task to run, while
queue bounding and load shedding decide which work is removed under pressure.

## Queue And Drop Policy

Each task has its own bounded queue sized by `queue_size`.

When a queue is full:

- `drop_oldest` removes the oldest queued frame and accepts the new frame.
- `drop_newest` rejects the incoming frame.
- `drop_low_priority` is accepted by the config contract, but current queue
  overflow behavior falls through to newest-frame rejection; low-priority
  shedding is handled by `LoadSheddingPolicy`.

Drops are not silent. Every queue overflow or policy-driven drop becomes a
`drop_events` telemetry entry with task, frame id, and reason.

## Load Shedding Policy

`LoadSheddingPolicy.apply()` runs when total backlog exceeds
`overload_backlog_threshold`.

Current behavior:

- Identify the highest-priority task that still has backlog as the protected
  task.
- Iterate queued tasks from low priority to high priority.
- Drop one oldest frame at a time from lower-priority queues until backlog is
  back under the threshold or no eligible frames remain.
- Record a policy decision and overload event for each shedding action.

This makes overload behavior explicit: low-priority work may be sacrificed to
protect latency for high-priority work.

## Worker Interface

Workers implement the same contract:

```python
class Worker(Protocol):
    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        ...
```

Supported workers:

- `dummy`: returns deterministic simulated latency and result metadata. It is
  used for scheduler tests and overload-policy validation.
- `onnxruntime`: loads ONNX models lazily, runs them with
  `CPUExecutionProvider`, and records output count and output shapes.

The fixed worker interface leaves room for a future TensorRT worker without
changing the scheduler, queue, or telemetry contracts.

The TensorRT/GPU backend direction is documented as a design and schema plan in
[`docs/tensorrt_backend.md`](tensorrt_backend.md). That document is intentionally
separate from the implemented worker list until Jetson execution is validated.

## Telemetry Schema Overview

Telemetry JSON is the main evidence artifact for runtime behavior.

Top-level fields:

- `run`: run metadata such as the configured run name.
- `tasks`: per-task summary with `executed`, `dropped`, `mean_latency_ms`,
  `p95_latency_ms`, and `max_queue_backlog`.
- `overload_events`: load-shedding events derived from policy decisions.
- `policy_decisions`: explicit records of why a task was limited and which task
  was protected.
- `drop_events`: queue or policy drops with task, frame id, and reason.
- `result_events`: worker result metadata including latency and output summary.
- `resource_snapshots`: start/end process resource snapshots.
- `schedule_decisions`: selected task and scheduling reason for each execution.

Versioned sample telemetry artifacts are available in
[`examples/telemetry/`](../examples/telemetry/README.md).

## Resource Monitor And Jetson Smoke Boundary

`ResourceMonitor` is intentionally lightweight. It records process-level memory
and optional CPU/memory percentages through `psutil` when installed. Without
`psutil`, it falls back to `resource.getrusage()`.

Jetson-specific `tegrastats` integration is handled as smoke-test evidence:

- `monitor.parse_tegrastats_line()` parses captured `tegrastats` lines.
- `scripts/smoke_jetson_dummy.sh` validates scheduler telemetry generation on
  Jetson.
- `scripts/smoke_jetson_onnx.sh` validates the ONNX Runtime worker path on
  Jetson.

Current Jetson records are smoke validations, not GPU or TensorRT benchmarks.

## InferEdge Integration Boundary

InferEdge and InferEdgeOrchestrator occupy different lifecycle stages:

- InferEdge validates deployment readiness through Forge, Runtime, Lab, and
  optional AIGuard analysis.
- InferEdgeOrchestrator controls runtime behavior after deployment.

The integration boundary is file-based. `inferedge_adapter.py` reads an
InferEdge `result.json`, extracts latency signals such as
`expected_latency_ms`, and recommends an initial `latency_budget_ms` for an
Orchestrator task config.

There are no direct imports from InferEdge repositories. This keeps validation
and operation control connected by artifacts while preserving repository
separation.

## Non-Goals

InferEdgeOrchestrator is not:

- A benchmark tool whose main purpose is average latency measurement.
- A Triton or DeepStream replacement.
- A distributed serving platform.
- A Kubernetes or cloud deployment orchestrator.
- A multi-device scheduler.
- A TensorRT performance benchmark.

The project goal is to show explicit, testable scheduling and overload-control
behavior for constrained edge inference workloads.
