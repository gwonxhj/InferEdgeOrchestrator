# Validation Evidence

Language: [English](validation_evidence.md) | 한국어

이 문서는 InferEdgeOrchestrator의 evidence index다. scheduler,
load-shedding policy, ONNX Runtime worker path, Jetson smoke path, InferEdge
file-based handoff가 의도대로 동작했는지 보여주는 runtime validation record를
한곳에 모은다.

이 기록들은 benchmark claim이 아니라 lifecycle evidence다. 목적은 runtime
control path가 실행되는지, overload policy decision이 관찰 가능한지, 생성된
telemetry가 어떤 일이 일어났는지 설명할 수 있는지를 보여주는 것이다.

TensorRT model-diversity 작업은
[`docs/tensorrt_model_diversity.ko.md`](tensorrt_model_diversity.ko.md)에 별도로
기록한다. 현재 diverse-engine 기록은 generated detector/classifier engine에 대한
TensorRT-backed scheduler/load-shedding operation-control evidence로 계산한다.
Throughput benchmark나 production serving claim은 아니다.

## Evidence Summary

| Evidence | What it validates | Status | Tracked artifact |
| --- | --- | --- | --- |
| Jetson dummy smoke | Jetson Orin Nano에서 CLI run, scheduler loop, bounded queue, telemetry JSON, resource snapshot, low-priority drop 검증 | PASS | [`examples/telemetry/jetson_smoke_dummy_sample.json`](../examples/telemetry/jetson_smoke_dummy_sample.json) |
| Jetson ONNX Runtime smoke | Jetson Orin Nano에서 `CPUExecutionProvider` 기반 ONNX Runtime worker path, output metadata, resource snapshot, `tegrastats` capture summary 검증 | PASS | [`examples/telemetry/jetson_onnx_smoke_sample.json`](../examples/telemetry/jetson_onnx_smoke_sample.json) |
| Jetson TensorRT inference smoke | Jetson Orin Nano에서 local identity ONNX를 TensorRT engine으로 생성하고 TensorRT identity frame 1개 실행 검증 | PASS | [`docs/tensorrt_engine_build.ko.md`](tensorrt_engine_build.ko.md) |
| Jetson TensorRT contention smoke | TensorRT task 2개를 scheduler/load-shedding으로 실행하고 low-priority drop 및 TensorRT backend telemetry 검증 | PASS | [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json) |
| Jetson TensorRT diverse engine build | Jetson Orin Nano에서 detector-like/classifier-like ONNX pair를 생성하고 local FP16 TensorRT engine 2개 build 검증 | PASS, build-only | [`docs/tensorrt_engine_build.ko.md`](tensorrt_engine_build.ko.md) |
| Jetson TensorRT diverse engine guard | 생성된 FP16 TensorRT engine 각각을 `TensorRtWorker`로 개별 실행하고 backend metadata 검증 | PASS, worker guard | [`docs/tensorrt_engine_build.ko.md`](tensorrt_engine_build.ko.md) |
| Jetson TensorRT diverse contention smoke | 서로 다른 generated detector/classifier TensorRT engine을 scheduler/load-shedding으로 실행하고 detector drop 보호, classifier shedding, overload event, policy decision, TensorRT backend telemetry 검증 | PASS | [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json) |
| Synthetic overload comparison | controlled overload에서 FIFO baseline과 scheduler/load-shedding policy 비교 | PASS | [`examples/telemetry/phase3_overload_sample.json`](../examples/telemetry/phase3_overload_sample.json) |
| InferEdge result handoff | InferEdge `result.json` latency signal에서 Orchestrator config로 file-based 변환 | PASS | [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json), [`configs/from_inferedge.json`](../configs/from_inferedge.json) |
| CI package/install smoke | Python 3.11 pytest, sample artifact compatibility check, editable package install, 설치된 CLI의 `run`, `report`, `compare-overload` smoke 실행 | PASS | [GitHub Actions CI](https://github.com/gwonxhj/InferEdgeOrchestrator/actions/workflows/ci.yml) |

raw smoke report는 local 또는 Jetson run 중 `reports/` 아래에 생성되며 git에는
의도적으로 포함하지 않는다. `examples/telemetry/` 아래 JSON은 reviewer가 device
workflow를 먼저 실행하지 않아도 evidence shape를 확인할 수 있도록 작게 정리한
versioned sample이다.

## Jetson Dummy Smoke

목적:

- Jetson Orin Nano에서 orchestrator CLI가 실행되는지 검증한다.
- dummy input scheduling, bounded queue, telemetry generation, resource
  snapshot을 검증한다.
- high-priority detector는 유지하면서 low-priority work가 drop되는 것을
  보여준다.

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

tracked sample은 raw device run보다 작게 정리되어 있지만 telemetry shape는
유지한다. task counter, drop event, result event, scheduler decision,
resource snapshot을 포함한다.

## Jetson ONNX Runtime Smoke

목적:

- Jetson Orin Nano에서 `onnxruntime` worker path가 실행되는지 검증한다.
- ONNX output metadata가 telemetry에 기록되는지 확인한다.
- resource snapshot과 optional `tegrastats` capture가 smoke workflow와
  호환되는지 확인한다.

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

이 smoke는 ONNX Runtime worker path 검증이다. TensorRT evidence, GPU execution
evidence, Jetson performance benchmark가 아니다.

## Jetson TensorRT Inference Smoke

목적:

- 작은 identity ONNX model을 Jetson Orin Nano에서 local TensorRT engine으로
  serialize할 수 있는지 검증한다.
- TensorRT Python binding availability, PyCUDA buffer copy support, TensorRT
  worker execution behavior를 검증한다.
- 현재 worker가 identity engine을 실행하고 backend result metadata를 반환하는지
  확인한다.
- end-to-end runtime telemetry가 `result_events[].output`에 TensorRT backend
  metadata를 기록하는지 확인한다.

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

이 결과는 TensorRT setup, single TensorRT worker inference path, runtime telemetry
result event까지 TensorRT backend metadata가 전달되는지를 검증한다. ONNX Runtime GPU
provider validation, TensorRT contention 상황의 scheduler behavior, performance
benchmark는 검증하지 않는다.

## Jetson TensorRT Contention Smoke

목적:

- Jetson Orin Nano에서 TensorRT task 2개를 `OrchestratorRuntime`으로 실행할 수
  있는지 검증한다.
- bounded queue와 load shedding이 low-priority TensorRT task를 제한하는 동안
  high-priority TensorRT task가 실행되는지 검증한다.
- contention 상황에서도 runtime telemetry result event에 TensorRT backend metadata가
  유지되는지 검증한다.

Command:

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  ENGINE_PATH=models/identity_fp16.plan \
  CONFIG=configs/jetson_tensorrt_contention.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt_contention.sh
```

기대 결과:

| Field | Value |
| --- | --- |
| Result | `PASS_TENSORRT_CONTENTION` |
| Telemetry | `reports/jetson_tensorrt_contention_telemetry.json` |
| Validation note | `reports/jetson_tensorrt_contention_validation.md` |
| Detector | `executed=6`, `dropped=0` |
| Classifier | `executed=1`, `dropped=5` |
| Overload events | `5` |
| Result event backends | `tensorrt` |

이 결과는 TensorRT-backed scheduler/load-shedding evidence다. TensorRT throughput
benchmark는 아니다.

Tracked sample:

- [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json)

## Jetson TensorRT Diverse Contention Smoke

목적:

- 서로 다른 generated TensorRT engine 2개가 Jetson Orin Nano의
  `OrchestratorRuntime`에서 실행되는지 검증한다.
- Load shedding이 low-priority classifier task를 제한하는 동안
  high-priority detector task가 drop되지 않도록 보호되는지 검증한다.
- Overload event, policy decision, result event, TensorRT backend metadata가
  telemetry에 남는지 검증한다.

명령:

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt_diverse_contention.sh
```

최신 실기기 기록:

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

이는 서로 다른 engine 기반 TensorRT scheduler/load-shedding evidence다.
정책 동작과 telemetry shape를 검증하며, 안정적인 TensorRT latency나 throughput
benchmark는 아니다.

Tracked sample:

- [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json)

## Synthetic Overload Comparison

목적:

- multi-task overload scenario를 deterministic하게 재현한다.
- FIFO baseline behavior와 scheduler/load-shedding behavior를 비교한다.
- low-priority work를 drop해 high-priority task latency를 보호할 수 있음을
  보여준다.

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

synthetic 수치는 controlled workload에서 policy behavior를 보여주기 위한 것이다.
production latency measurement로 해석하지 않는다.

## InferEdge Result Handoff

목적:

- InferEdge ecosystem boundary를 명확히 유지한다.
- InferEdge `result.json` latency signal을 사용해 Orchestrator task config
  초기값을 생성한다.
- InferEdge repository를 직접 import하지 않는다.

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
- [`docs/inferedge_integration.ko.md`](inferedge_integration.ko.md)

이 evidence가 보여주는 lifecycle boundary는 다음과 같다.

```text
InferEdge = deployment validation pipeline
InferEdgeOrchestrator = runtime operation control layer
```

## Sample Telemetry Artifact Index

| File | Evidence path | Main signals |
| --- | --- | --- |
| [`examples/telemetry/phase3_overload_sample.json`](../examples/telemetry/phase3_overload_sample.json) | synthetic overload comparison | protected task, baseline p95, scheduled p95, low-priority drops, overload events |
| [`examples/telemetry/jetson_smoke_dummy_sample.json`](../examples/telemetry/jetson_smoke_dummy_sample.json) | Jetson dummy smoke | executed/dropped counts, drop events, schedule decisions, result events, resource snapshots |
| [`examples/telemetry/jetson_onnx_smoke_sample.json`](../examples/telemetry/jetson_onnx_smoke_sample.json) | Jetson ONNX Runtime smoke | ONNX worker output metadata, output shapes, result events, resource snapshots |
| [`examples/telemetry/jetson_tensorrt_contention_sample.json`](../examples/telemetry/jetson_tensorrt_contention_sample.json) | Jetson TensorRT contention smoke | protected high-priority task, low-priority shedding, overload events, TensorRT backend metadata |
| [`examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`](../examples/telemetry/jetson_tensorrt_diverse_contention_sample.json) | Jetson TensorRT diverse contention smoke | 서로 다른 generated engine, protected detector-like task, limited classifier-like task, policy decision |

sample-specific schema note는
[`examples/telemetry/README.ko.md`](../examples/telemetry/README.ko.md)를 참고한다.

## Evidence Boundaries

- Smoke validation은 runtime path 실행을 증명하지만 안정적인 device performance를
  주장하지 않는다.
- Synthetic overload comparison은 scheduler policy behavior를 증명하지만
  production benchmark가 아니다.
- Jetson ONNX Runtime smoke는 현재 `CPUExecutionProvider`를 사용한다. TensorRT
  또는 GPU benchmark evidence가 아니다.
- Jetson TensorRT inference smoke는 engine creation, single TensorRT worker identity
  inference path, runtime telemetry metadata propagation을 증명한다. 그 자체만으로는
  multi-task contention evidence가 아니다.
- Jetson TensorRT contention smoke는 작은 shared identity engine으로
  TensorRT-backed scheduler/load-shedding behavior를 증명한다.
- Jetson TensorRT diverse contention smoke는 서로 다른 generated detector/classifier
  engine으로 같은 operation-control telemetry shape를 증명한다. Production model
  throughput 또는 stable device performance를 증명하지 않는다.
- raw generated report는 `reports/` 아래에 남기며 commit하지 않는다.
- versioned sample JSON은 review와 schema inspection을 위한 curated
  documentation artifact다.
- CI package/install smoke는 portable install과 CLI entrypoint 상태를 검증한다.
  Jetson physical-device smoke evidence를 대체하지 않는다.
