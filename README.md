# InferEdgeOrchestrator

InferEdgeOrchestrator is a lightweight runtime scheduler for running multiple
edge inference tasks with explicit priority, latency budget, queue, and load
shedding policies.

It is not a Triton or DeepStream replacement. The goal is to show how a
constrained edge device can protect high-priority inference workloads when
latency spikes, queue backlog, and frame drops appear under overload.

## Relationship to InferEdge

InferEdge is the deployment validation pipeline. It handles model conversion,
runtime result collection, analysis, and deployment decisions.

InferEdgeOrchestrator is the runtime operation control layer. It starts after a
model is considered deployable and controls how multiple inference tasks behave
when they run together on a constrained device.

## Phase 1 Scope

Phase 1 proves the scheduler policy without running real models.

- Task config schema
- Dummy frame source
- Bounded per-task queues
- Priority and deadline-aware scheduler
- Dummy worker
- Load shedding policy
- Telemetry JSON export
- Pytest coverage for scheduler, queue, shedding, and telemetry behavior

Phase 1 intentionally does not execute ONNX models. ONNX Runtime support belongs
to Phase 2.

## Phase 2 ONNX Runtime Smoke

Install the ONNX extras in your local environment:

```bash
python3 -m pip install -e '.[onnx,dev]'
```

Create a tiny identity model for smoke testing:

```bash
python3 scripts/create_identity_onnx.py --output models/identity.onnx
```

Run the ONNX Runtime worker demo:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/phase2_onnx_demo.json \
  --output reports/phase2_onnx_demo.json \
  --frames 1
```

The `worker` field selects whether a task runs through the dummy worker or the
ONNX Runtime worker. Image and video inputs can be routed by setting
`run.input_source` to `image` or `video` with `run.input_path`.

## Phase 3 Overload Scenario

Run the overload comparison:

```bash
python3 -m inferedge_orchestrator compare-overload \
  --config configs/phase3_overload.json \
  --output reports/phase3_overload.json \
  --frames 20
```

The comparison writes a no-scheduler FIFO baseline and a scheduled policy run to
the same JSON report. In the baseline, every task is processed in arrival order,
so a low-priority classifier can sit in front of a high-priority detector and
push up detector end-to-end latency. With priority scheduling and load shedding,
classifier drops increase under overload, but detector p95 end-to-end latency is
protected. This project is not a benchmark tool; the point is runtime stability
under competing edge inference work.

## Quickstart

Run the tests:

```bash
python3 -m pytest
```

Run the Phase 1 demo:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/phase1_demo.json \
  --output reports/phase1_demo.json \
  --frames 12
```

Print a telemetry summary:

```bash
python3 -m inferedge_orchestrator report --input reports/phase1_demo.json
```
