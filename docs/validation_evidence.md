# Validation Evidence

Language: English | [한국어](validation_evidence.ko.md)

This document is the evidence index for InferEdgeOrchestrator. It collects the
runtime validation records that show the scheduler, load-shedding policy, ONNX
Runtime worker path, Jetson smoke path, and InferEdge file-based handoff working
as intended.

These records are lifecycle evidence, not benchmark claims. The goal is to show
that the runtime control paths execute, that overload policy decisions are
observable, and that generated telemetry can explain what happened.

TensorRT model-diversity work is tracked separately in
[`docs/tensorrt_model_diversity.md`](tensorrt_model_diversity.md). The current
diverse-engine record is counted as TensorRT-backed scheduler/load-shedding
operation-control evidence for generated detector/classifier engines; it is not
a throughput benchmark or production serving claim.

## Evidence Summary

| Evidence | What it validates | Status | Tracked artifact |
| --- | --- | --- | --- |
| Jetson dummy smoke | CLI run, scheduler loop, bounded queues, telemetry JSON, resource snapshots, low-priority drops on Jetson Orin Nano | PASS | [`examples/telemetry/jetson_smoke_dummy_sample.json`](../examples/telemetry/jetson_smoke_dummy_sample.json) |
| Jetson ONNX Runtime smoke | ONNX Runtime worker path on Jetson Orin Nano with `CPUExecutionProvider`, output metadata, resource snapshots, `tegrastats` capture summary | PASS | [`examples/telemetry/jetson_onnx_smoke_sample.json`](../examples/telemetry/jetson_onnx_smoke_sample.json) |
| Jetson TensorRT inference smoke | Local identity ONNX to TensorRT engine creation and one TensorRT identity-frame execution on Jetson Orin Nano | PASS | [`docs/tensorrt_engine_build.md`](tensorrt_engine_build.md) |
| Jetson TensorRT contention smoke | Two TensorRT tasks through scheduler/load-shedding with low-priority drops and TensorRT backend telemetry | PASS | [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json) |
| Jetson TensorRT diverse engine build | Generated detector-like/classifier-like ONNX pair and built two local FP16 TensorRT engines on Jetson Orin Nano | PASS, build-only | [`docs/tensorrt_engine_build.md`](tensorrt_engine_build.md) |
| Jetson TensorRT diverse engine guard | Ran each generated FP16 TensorRT engine through `TensorRtWorker` individually and validated backend metadata | PASS, worker guard | [`docs/tensorrt_engine_build.md`](tensorrt_engine_build.md) |
| Jetson TensorRT diverse contention smoke | Distinct generated detector/classifier TensorRT engines through scheduler/load-shedding with protected detector drops, classifier shedding, overload events, policy decisions, and TensorRT backend telemetry | PASS | [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json) |
| Synthetic overload comparison | FIFO baseline vs scheduler/load-shedding policy under controlled overload | PASS | [`examples/telemetry/phase3_overload_sample.json`](../examples/telemetry/phase3_overload_sample.json) |
| InferEdge result handoff | File-based conversion from InferEdge `result.json` latency signal to Orchestrator config | PASS | [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json), [`configs/from_inferedge.json`](../configs/from_inferedge.json) |
| CI tests | Unit tests and sample artifact compatibility checks on Python 3.11 | PASS | [GitHub Actions CI](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml) |

Raw smoke reports are generated under `reports/` during local or Jetson runs and
are intentionally ignored by git. The JSON files under `examples/telemetry/` are
small, versioned samples derived from those validation paths so reviewers can
inspect the evidence shape without running the device workflows first.

## Jetson Dummy Smoke

Purpose:

- Validate that the orchestrator CLI runs on Jetson Orin Nano.
- Validate dummy-input scheduling, bounded queues, telemetry generation, and
  resource snapshots.
- Show low-priority work being dropped while the high-priority detector remains
  active.

Command:

```bash
CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh
```

Latest physical-device record:

| Field | Value |
| --- | --- |
| Device | `nano01` |
| OS / L4T | `Ubuntu 22.04.5 LTS`, `L4T R36.4.7` |
| Python | `3.10.12` |
| Config | `configs/phase4_jetson_smoke.json` |
| Frames | `20` |
| Raw telemetry path | `reports/jetson_smoke_dummy.json` |
| Raw validation note | `reports/jetson_validation.md` |
| Result | `PASS` |

Latest raw telemetry summary:

| Task | Executed | Dropped | Mean latency | P95 latency | Max backlog |
| --- | ---: | ---: | ---: | ---: | ---: |
| `detector` | 20 | 0 | 8.0ms | 8.0ms | 1 |
| `classifier` | 2 | 18 | 32.0ms | 32.0ms | 2 |

Tracked sample:

- [`examples/telemetry/jetson_smoke_dummy_sample.json`](../examples/telemetry/jetson_smoke_dummy_sample.json)

The tracked sample is intentionally smaller than the raw device run but keeps
the same telemetry shape: task counters, drop events, result events, scheduler
decisions, and resource snapshots.

## Jetson ONNX Runtime Smoke

Purpose:

- Validate that the `onnxruntime` worker path runs on Jetson Orin Nano.
- Record ONNX output metadata in telemetry.
- Confirm resource snapshots and optional `tegrastats` capture are compatible
  with the smoke workflow.

Command:

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_onnx.sh
```

Latest physical-device record:

| Field | Value |
| --- | --- |
| Device | `nano01` |
| OS / L4T | `Ubuntu 22.04.5 LTS`, `L4T R36.4.7` |
| Python | `3.10.12` |
| ONNX Runtime | `1.23.2` |
| Provider | `CPUExecutionProvider` |
| Config | `configs/phase2_onnx_demo.json` |
| Model | `models/identity.onnx` |
| Raw telemetry path | `reports/jetson_onnx_smoke.json` |
| Result | `PASS` |

Latest raw telemetry summary:

| Task | Executed | Dropped | Mean latency | P95 latency | Output shape |
| --- | ---: | ---: | ---: | ---: | --- |
| `identity` | 1 | 0 | 202.05ms | 202.05ms | `[1, 2]` |

Tracked sample:

- [`examples/telemetry/jetson_onnx_smoke_sample.json`](../examples/telemetry/jetson_onnx_smoke_sample.json)

This smoke validates the ONNX Runtime worker path. It is not TensorRT evidence,
GPU execution evidence, or a Jetson performance benchmark.

## Jetson TensorRT Inference Smoke

Purpose:

- Validate that a tiny identity ONNX model can be serialized into a local
  TensorRT engine on Jetson Orin Nano.
- Validate TensorRT Python binding availability, PyCUDA buffer copy support, and
  TensorRT worker execution behavior.
- Confirm that the current worker can execute the identity engine and return
  backend result metadata.
- Confirm that end-to-end runtime telemetry records TensorRT backend metadata in
  `result_events[].output`.

Commands:

```bash
"$PYTHON_BIN" scripts/create_identity_onnx.py --output models/identity.onnx
```

```bash
"/usr/src/tensorrt/bin/trtexec" \
  --onnx=models/identity.onnx \
  --saveEngine=models/identity_fp16.plan \
  --fp16 \
  --skipInference \
  --verbose \
  > reports/trtexec_identity_build.log 2>&1
```

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  ENGINE_PATH=models/identity_fp16.plan \
  CONFIG=configs/jetson_tensorrt_smoke.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt.sh
```

Latest physical-device record:

| Field | Value |
| --- | --- |
| Device | `nano01` |
| OS / L4T | `Ubuntu 22.04.5 LTS`, `L4T R36.4.7` |
| Python | `3.10.12` |
| TensorRT Python | `10.3.0` |
| `trtexec` | TensorRT `v100300` |
| ONNX model | `models/identity.onnx`, 104 bytes |
| TensorRT engine | `models/identity_fp16.plan`, 8.2 KiB |
| Raw build log | `reports/trtexec_identity_build.log` |
| Raw validation note | `reports/jetson_tensorrt_guard_validation.md` |
| Raw runtime telemetry | `reports/jetson_tensorrt_runtime_telemetry.json` |
| Worker result | `PASS_TENSORRT_INFERENCE` |
| Runtime telemetry result | `PASS_TENSORRT_TELEMETRY` |

This validates TensorRT setup and a single TensorRT worker inference path. It
also validates that TensorRT backend metadata reaches runtime telemetry result
events. It is not ONNX Runtime GPU provider validation, scheduler behavior under
TensorRT contention, or a performance benchmark.

## Jetson TensorRT Contention Smoke

Purpose:

- Validate that two TensorRT tasks can run through `OrchestratorRuntime` on
  Jetson Orin Nano.
- Validate that bounded queues and load shedding limit the low-priority
  TensorRT task while the high-priority TensorRT task executes.
- Validate that TensorRT backend metadata remains present in runtime telemetry
  result events during contention.

Command:

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  ENGINE_PATH=models/identity_fp16.plan \
  CONFIG=configs/jetson_tensorrt_contention.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt_contention.sh
```

Expected result:

| Field | Value |
| --- | --- |
| Result | `PASS_TENSORRT_CONTENTION` |
| Telemetry | `reports/jetson_tensorrt_contention_telemetry.json` |
| Validation note | `reports/jetson_tensorrt_contention_validation.md` |
| Detector | `executed=6`, `dropped=0` |
| Classifier | `executed=1`, `dropped=5` |
| Overload events | `5` |
| Result event backends | `tensorrt` |

This is TensorRT-backed scheduler/load-shedding evidence. It is not a TensorRT
throughput benchmark.

Tracked sample:

- [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json)

## Jetson TensorRT Diverse Contention Smoke

Purpose:

- Validate that two distinct generated TensorRT engines can run through
  `OrchestratorRuntime` on Jetson Orin Nano.
- Validate that load shedding limits the low-priority classifier task while the
  high-priority detector task is protected from drops.
- Validate that overload events, policy decisions, result events, and TensorRT
  backend metadata remain observable in telemetry.

Command:

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt_diverse_contention.sh
```

Latest physical-device record:

| Field | Value |
| --- | --- |
| Result | `PASS_TENSORRT_DIVERSE_CONTENTION` |
| Device | `nano01` |
| Timestamp | `2026-05-07T03:38:21Z` |
| Python | `3.10.12` |
| TensorRT Python | `10.3.0` |
| Config | `configs/jetson_tensorrt_diverse_contention.json` |
| Frames | `6` |
| Detector engine | `models/generated/detector_tiny_fp16.plan` |
| Classifier engine | `models/generated/classifier_tiny_fp16.plan` |
| Detector | `executed=6`, `dropped=0` |
| Classifier | `executed=1`, `dropped=5` |
| Overload events | `5` |
| Limited tasks | `classifier_trt` |
| Result event backends | `tensorrt` |
| Raw telemetry | `reports/jetson_tensorrt_diverse_contention_telemetry.json` |
| Raw validation note | `reports/jetson_tensorrt_diverse_contention_validation.md` |
| Optional `tegrastats` log | `reports/tegrastats_tensorrt_diverse_contention.log` |

This is distinct-engine TensorRT scheduler/load-shedding evidence. It validates
policy behavior and telemetry shape, not stable TensorRT latency or throughput.

Tracked sample:

- [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json)

## Synthetic Overload Comparison

Purpose:

- Reproduce a multi-task overload scenario in a deterministic way.
- Compare FIFO baseline behavior with scheduler and load-shedding behavior.
- Show that low-priority work can be dropped to protect high-priority task
  latency.

Command:

```bash
python3 -m inferedge_orchestrator compare-overload \
  --config configs/phase3_overload.json \
  --output reports/phase3_overload.json \
  --frames 20
```

Result summary:

| Mode | Detector executed | Detector dropped | Detector p95 end-to-end latency | Classifier executed | Classifier dropped | Overload events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FIFO baseline | 20 | 0 | 782.0ms | 20 | 0 | 0 |
| Scheduler + load shedding | 20 | 0 | 8.0ms | 4 | 16 | 16 |

Tracked sample:

- [`examples/telemetry/phase3_overload_sample.json`](../examples/telemetry/phase3_overload_sample.json)

The synthetic numbers demonstrate policy behavior under a controlled workload.
They should not be read as production latency measurements.

## InferEdge Result Handoff

Purpose:

- Keep the InferEdge ecosystem boundary explicit.
- Use InferEdge `result.json` latency signals to generate an initial
  Orchestrator task config.
- Avoid direct imports from InferEdge repositories.

Command:

```bash
python3 -m inferedge_orchestrator from-inferedge \
  --result examples/inferedge_result_sample.json \
  --output configs/from_inferedge.json \
  --task-name detector \
  --model-path models/detector.onnx \
  --priority 100 \
  --target-fps 15 \
  --queue-size 4
```

Result summary:

| Input signal | Generated config field | Value |
| --- | --- | ---: |
| `expected_latency_ms` | source latency signal | 42.2 |
| `budget_multiplier` | default multiplier | 1.5 |
| `latency_budget_ms` | recommended task budget | 64.0 |

Tracked artifacts:

- [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json)
- [`configs/from_inferedge.json`](../configs/from_inferedge.json)
- [`docs/inferedge_integration.md`](inferedge_integration.md)

This evidence supports the lifecycle boundary:

```text
InferEdge = deployment validation pipeline
InferEdgeOrchestrator = runtime operation control layer
```

## Sample Telemetry Artifact Index

| File | Evidence path | Main signals |
| --- | --- | --- |
| [`examples/telemetry/phase3_overload_sample.json`](../examples/telemetry/phase3_overload_sample.json) | Synthetic overload comparison | protected task, baseline p95, scheduled p95, low-priority drops, overload events |
| [`examples/telemetry/jetson_smoke_dummy_sample.json`](../examples/telemetry/jetson_smoke_dummy_sample.json) | Jetson dummy smoke | executed/dropped counts, drop events, schedule decisions, result events, resource snapshots |
| [`examples/telemetry/jetson_onnx_smoke_sample.json`](../examples/telemetry/jetson_onnx_smoke_sample.json) | Jetson ONNX Runtime smoke | ONNX worker output metadata, output shapes, result events, resource snapshots |
| [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json) | Jetson TensorRT contention smoke | protected high-priority task, low-priority shedding, overload events, TensorRT backend metadata |
| [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json) | Jetson TensorRT diverse contention smoke | distinct generated engines, protected detector-like task, limited classifier-like task, policy decisions |

For sample-specific schema notes, see
[`examples/telemetry/README.md`](../examples/telemetry/README.md).

## Evidence Boundaries

- Smoke validation proves runtime paths execute; it does not claim stable device
  performance.
- Synthetic overload comparison proves scheduler policy behavior; it is not a
  production benchmark.
- Jetson ONNX Runtime smoke currently uses `CPUExecutionProvider`; it is not
  TensorRT or GPU benchmark evidence.
- Jetson TensorRT inference smoke proves engine creation, a single TensorRT
  worker identity inference path, and runtime telemetry metadata propagation; it
  is not multi-task contention evidence by itself.
- Jetson TensorRT contention smoke proves TensorRT-backed
  scheduler/load-shedding behavior with a tiny shared identity engine.
- Jetson TensorRT diverse contention smoke proves the same operation-control
  telemetry shape with distinct generated detector/classifier engines; it does
  not prove production model throughput or stable device performance.
- Raw generated reports stay under `reports/` and are not committed.
- Versioned sample JSON files are curated documentation artifacts for review and
  schema inspection.
