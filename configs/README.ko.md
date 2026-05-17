# Config Guide

Language: [English](README.md) | 한국어

이 config들은 InferEdgeOrchestrator의 주요 validation path를 실행하기 위한 작고
versioned된 entry point다. JSON field를 모두 먼저 읽지 않아도 각 phase가 무엇을
보여주는지 빠르게 이해할 수 있게 정리한다.

runtime output은 일반적으로 git에서 ignore되는 `reports/` 아래에 생성된다.
추적 가능한 evidence sample은
[`examples/telemetry/`](../examples/telemetry/README.ko.md)에 있다.

## Config Index

| Config | Purpose | Related phase | Command | Expected output | Note |
| --- | --- | --- | --- | --- | --- |
| [`phase1_demo.json`](phase1_demo.json) | dummy detector/classifier task로 scheduler core를 실행한다. | Phase 1: Scheduler Core MVP | `python3 -m inferedge_orchestrator run --config configs/phase1_demo.json --output reports/phase1_demo.json --frames 12` | task execution/drop count와 scheduler decision을 담은 `reports/phase1_demo.json` telemetry. | `dummy` worker를 사용하므로 실제 model file이 필요 없다. |
| [`phase2_onnx_demo.json`](phase2_onnx_demo.json) | identity ONNX model 1개를 ONNX Runtime worker로 실행한다. | Phase 2: ONNX Runtime Worker | `python3 -m inferedge_orchestrator run --config configs/phase2_onnx_demo.json --output reports/phase2_onnx_demo.json --frames 1` | ONNX output metadata를 담은 `reports/phase2_onnx_demo.json` telemetry. | ONNX extras와 `models/identity.onnx`가 필요하며, 보통 `python3 scripts/create_identity_onnx.py --output models/identity.onnx`로 생성한다. |
| [`phase3_overload.json`](phase3_overload.json) | synthetic overload에서 FIFO baseline과 scheduler/load-shedding behavior를 비교한다. | Phase 3: Overload Scenario | `python3 -m inferedge_orchestrator compare-overload --config configs/phase3_overload.json --output reports/phase3_overload.json --frames 20` | protected-task latency와 low-priority drop을 담은 `reports/phase3_overload.json` comparison. | controlled synthetic scenario의 policy evidence이며 production benchmark가 아니다. |
| [`agent_3_workload_demo.json`](agent_3_workload_demo.json) | Forge agent manifest와 Runtime `result.agent` contract 참조를 사용해 Vision / Voice-Command / Safety-Monitor dummy agent를 실행한다. | Reliable Edge Agent Runtime: Orchestration Summary Contract | `python3 -m inferedge_orchestrator run --config configs/agent_3_workload_demo.json --output reports/agent_orchestration_summary.json --frames 8` | `inferedge-orchestration-summary-v1`, agent totals, policy decision log를 담은 `reports/agent_orchestration_summary.json`. | `dummy` worker를 사용하며 production agent 실행이 아니라 scheduling evidence를 검증한다. |
| [`agent_3_workload_normal.json`](agent_3_workload_normal.json), [`agent_3_workload_overload.json`](agent_3_workload_overload.json), [`agent_3_workload_sustained_high_load.json`](agent_3_workload_sustained_high_load.json) | 3-agent scenario를 normal / overload / sustained-high-load mode로 분리해 실행한다. | Reliable Edge Agent Runtime: Sustained Multi-Workload Demo | `python3 -m inferedge_orchestrator run --config configs/agent_3_workload_sustained_high_load.json --output reports/agent_sustained_high_load.json --frames 16` | queue-depth timeline, latency timeline, policy decision reason, sustained runtime summary를 담은 `reports/agent_sustained_high_load.json`. | device-specific sustained validation 전에 lightweight dummy workload로 scheduler behavior와 runtime reliability signal을 노출한다. |
| [`agent_multi_workload_sustained_local.json`](agent_multi_workload_sustained_local.json) | YOLO-like vision loop, Whisper-like command burst, FastAPI-style request ingress, optional tegrastats timeline을 포함한 첫 profiled sustained local scenario를 실행한다. | Reliable Edge Agent Runtime: Lightweight Sustained Workload Starter | `python3 -m inferedge_orchestrator run-multi-workload-sustained --config configs/agent_multi_workload_sustained_local.json --output reports/agent_multi_workload_sustained.json --frames 16` | `multi_workload_sustained_summary`, workload profile, queue/deadline/drop/fallback evidence, optional `tegrastats_timeline`을 담은 `reports/agent_multi_workload_sustained.json`. | 기본값은 lightweight local CPU profile adapter이며, 외부 YOLO/Whisper/FastAPI producer는 다음 단계 integration이다. |
| [`agent_multi_workload_sustained_vision_file.json`](agent_multi_workload_sustained_vision_file.json) | 같은 sustained profile에서 local image file을 Vision workload producer로 전달한다. | Reliable Edge Agent Runtime: Vision Producer Starter | `python3 -m inferedge_orchestrator run-multi-workload-sustained --config configs/agent_multi_workload_sustained_vision_file.json --output reports/agent_multi_workload_sustained_vision_file.json --frames 16` | Vision `producer_source=image_file`, input digest, sampled bytes, workload pressure evidence를 담은 `reports/agent_multi_workload_sustained_vision_file.json`. | `examples/inputs/` 아래 작은 PPM fixture를 사용하며, ONNX/YOLO integration 전 device-local producer 단계다. |
| [`phase4_jetson_smoke.json`](phase4_jetson_smoke.json) | Jetson Orin Nano에서 dummy scheduler smoke path를 실행한다. | Phase 4: Jetson Smoke Test | `CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh` | `reports/jetson_smoke_dummy.json` 및 `reports/jetson_validation.md`. | `dummy` worker를 사용한다. 자세한 내용은 [`docs/jetson_smoke_test.ko.md`](../docs/jetson_smoke_test.ko.md)를 참고한다. |
| [`from_inferedge.json`](from_inferedge.json) | InferEdge `result.json` latency signal에서 생성한 tracked sample output이다. | Phase 5: InferEdge Handoff | `python3 -m inferedge_orchestrator from-inferedge --result examples/inferedge_result_sample.json --output configs/from_inferedge.json --task-name detector --model-path models/detector.onnx --priority 100 --target-fps 15 --queue-size 4` | recommended `latency_budget_ms=64.0`을 포함한 `configs/from_inferedge.json`. | hand-authored policy가 아니라 생성 산출물이다. InferEdge boundary를 file-based로 유지한다. |
| [`jetson_tensorrt_smoke.json`](jetson_tensorrt_smoke.json) | Jetson에서 TensorRT worker inference와 runtime telemetry smoke를 실행한다. | TensorRT/GPU backend smoke | `ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh` | `reports/jetson_tensorrt_guard_validation.md`, `reports/jetson_tensorrt_runtime_telemetry.json`, `reports/` 아래 dependency inventory. | TensorRT Python binding, PyCUDA, device-local engine file이 필요하다. Single-worker identity inference evidence이며 multi-task TensorRT scheduling evidence는 아니다. |
| [`jetson_tensorrt_contention.json`](jetson_tensorrt_contention.json) | Jetson에서 TensorRT task 2개를 scheduler/load-shedding contention으로 실행한다. | TensorRT/GPU contention smoke | `ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt_contention.sh` | `reports/jetson_tensorrt_contention_telemetry.json` 및 `reports/jetson_tensorrt_contention_validation.md`. | TensorRT Python binding, PyCUDA, device-local engine file이 필요하다. TensorRT-backed scheduler/load-shedding operation-control behavior 검증이며 throughput 검증은 아니다. |
| [`jetson_tensorrt_diverse_contention.json`](jetson_tensorrt_diverse_contention.json) | 서로 다른 detector-like 및 classifier-like TensorRT engine을 Jetson scheduler/load-shedding contention으로 실행한다. | TensorRT/GPU diverse contention smoke | `scripts/smoke_jetson_tensorrt_diverse_contention.sh` | `reports/jetson_tensorrt_diverse_contention_telemetry.json` 및 `reports/jetson_tensorrt_diverse_contention_validation.md`. | `scripts/build_jetson_tensorrt_diverse_engines.sh`가 생성한 local engine이 필요하다. 서로 다른 engine의 TensorRT-backed scheduler/load-shedding operation-control behavior 검증이며 throughput 검증은 아니다. |

## Notes

- `dummy` worker config는 model file을 load하지 않고 scheduler, queue, policy,
  telemetry path를 검증한다.
- `onnxruntime` worker config는 optional ONNX dependency와 model file이 필요하다.
- TensorRT/GPU backend smoke는 Jetson의 local TensorRT engine과 PyCUDA가 필요하다.
  smoke script는 worker inference를 검증하고 TensorRT backend metadata가 ignored
  `reports/` 아래 runtime telemetry에 남는지 확인한다. 자세한 내용은
  [`docs/tensorrt_backend.ko.md`](../docs/tensorrt_backend.ko.md)에 기록한다.
- `jetson_tensorrt_diverse_contention.json`은 `models/generated/` 아래 서로 다른
  generated engine 2개를 사용한다. 해당 ONNX와 TensorRT engine file은 local artifact이며
  commit하지 않는다.
- `reports/` output은 의도적으로 ignore한다. reviewer-facing evidence가 필요하면
  curated sample을 `examples/telemetry/` 아래에 commit한다.
- `from_inferedge.json`은
  [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json)에서
  `from-inferedge` CLI command로 재생성할 수 있다.
- `agent_3_workload_demo.json`은 현재 agent scheduling contract의 entry point다.
  자세한 내용은
  [`docs/agent_orchestration_summary_contract.ko.md`](../docs/agent_orchestration_summary_contract.ko.md)를 참고한다.
- 분리된 `agent_3_workload_*` scenario config는 첫 sustained demo 단계다.
  Runtime은 task execution/result layer로 유지하고, queue/scheduling/drop/fallback과
  policy-decision telemetry는 Orchestrator가 담당한다.
- `agent_multi_workload_sustained_local.json`은 lightweight local CPU adapter를 사용하는 첫
  `run-multi-workload-sustained` profile이다. YOLO/Whisper/FastAPI-style
  workload role을 명시하지만, 기본 CI에 해당 외부 dependency를 강제하지 않는다.
- `agent_multi_workload_sustained_vision_file.json`은 첫 Vision producer 단계다.
  작은 local image fixture를 읽고 bounded input statistics를 기록하면서 workload loop는
  dependency-free로 유지한다.
