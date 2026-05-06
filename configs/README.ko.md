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
| [`phase4_jetson_smoke.json`](phase4_jetson_smoke.json) | Jetson Orin Nano에서 dummy scheduler smoke path를 실행한다. | Phase 4: Jetson Smoke Test | `CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh` | `reports/jetson_smoke_dummy.json` 및 `reports/jetson_validation.md`. | `dummy` worker를 사용한다. 자세한 내용은 [`docs/jetson_smoke_test.ko.md`](../docs/jetson_smoke_test.ko.md)를 참고한다. |
| [`from_inferedge.json`](from_inferedge.json) | InferEdge `result.json` latency signal에서 생성한 tracked sample output이다. | Phase 5: InferEdge Handoff | `python3 -m inferedge_orchestrator from-inferedge --result examples/inferedge_result_sample.json --output configs/from_inferedge.json --task-name detector --model-path models/detector.onnx --priority 100 --target-fps 15 --queue-size 4` | recommended `latency_budget_ms=64.0`을 포함한 `configs/from_inferedge.json`. | hand-authored policy가 아니라 생성 산출물이다. InferEdge boundary를 file-based로 유지한다. |
| [`jetson_tensorrt_smoke.json`](jetson_tensorrt_smoke.json) | Jetson에서 TensorRT worker inference와 runtime telemetry smoke를 실행한다. | TensorRT/GPU backend smoke | `ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh` | `reports/jetson_tensorrt_guard_validation.md`, `reports/jetson_tensorrt_runtime_telemetry.json`, `reports/` 아래 dependency inventory. | TensorRT Python binding, PyCUDA, device-local engine file이 필요하다. Single-worker identity inference evidence이며 multi-task TensorRT scheduling evidence는 아니다. |

## Notes

- `dummy` worker config는 model file을 load하지 않고 scheduler, queue, policy,
  telemetry path를 검증한다.
- `onnxruntime` worker config는 optional ONNX dependency와 model file이 필요하다.
- TensorRT/GPU backend smoke는 Jetson의 local TensorRT engine과 PyCUDA가 필요하다.
  smoke script는 worker inference를 검증하고 TensorRT backend metadata가 ignored
  `reports/` 아래 runtime telemetry에 남는지 확인한다. 자세한 내용은
  [`docs/tensorrt_backend.ko.md`](../docs/tensorrt_backend.ko.md)에 기록한다.
- `reports/` output은 의도적으로 ignore한다. reviewer-facing evidence가 필요하면
  curated sample을 `examples/telemetry/` 아래에 commit한다.
- `from_inferedge.json`은
  [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json)에서
  `from-inferedge` CLI command로 재생성할 수 있다.
