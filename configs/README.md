# Config Guide

Language: English | [한국어](README.ko.md)

These configs are small, versioned entry points for the main InferEdgeOrchestrator
validation paths. They are meant to show what each phase demonstrates without
requiring a reader to inspect every JSON field first.

Runtime outputs are normally written under `reports/`, which is ignored by git.
Tracked evidence samples live under
[`examples/telemetry/`](../examples/telemetry/README.md).

## Config Index

| Config | Purpose | Related phase | Command | Expected output | Note |
| --- | --- | --- | --- | --- | --- |
| [`phase1_demo.json`](phase1_demo.json) | Run the scheduler core with dummy detector/classifier tasks. | Phase 1: Scheduler Core MVP | `python3 -m inferedge_orchestrator run --config configs/phase1_demo.json --output reports/phase1_demo.json --frames 12` | `reports/phase1_demo.json` telemetry with task execution/drop counts and scheduler decisions. | Uses `dummy` workers; no real model file is required. |
| [`phase2_onnx_demo.json`](phase2_onnx_demo.json) | Run a single identity ONNX model through the ONNX Runtime worker. | Phase 2: ONNX Runtime Worker | `python3 -m inferedge_orchestrator run --config configs/phase2_onnx_demo.json --output reports/phase2_onnx_demo.json --frames 1` | `reports/phase2_onnx_demo.json` telemetry with ONNX output metadata. | Requires ONNX extras and `models/identity.onnx`, usually created with `python3 scripts/create_identity_onnx.py --output models/identity.onnx`. |
| [`phase3_overload.json`](phase3_overload.json) | Compare FIFO baseline with scheduler/load-shedding behavior under synthetic overload. | Phase 3: Overload Scenario | `python3 -m inferedge_orchestrator compare-overload --config configs/phase3_overload.json --output reports/phase3_overload.json --frames 20` | `reports/phase3_overload.json` comparison with protected-task latency and low-priority drops. | This is policy evidence from a controlled synthetic scenario, not a production benchmark. |
| [`phase4_jetson_smoke.json`](phase4_jetson_smoke.json) | Run the dummy scheduler smoke path on Jetson Orin Nano. | Phase 4: Jetson Smoke Test | `CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh` | `reports/jetson_smoke_dummy.json` plus `reports/jetson_validation.md`. | Uses `dummy` workers; see [`docs/jetson_smoke_test.md`](../docs/jetson_smoke_test.md). |
| [`from_inferedge.json`](from_inferedge.json) | Tracked sample output generated from an InferEdge `result.json` latency signal. | Phase 5: InferEdge Handoff | `python3 -m inferedge_orchestrator from-inferedge --result examples/inferedge_result_sample.json --output configs/from_inferedge.json --task-name detector --model-path models/detector.onnx --priority 100 --target-fps 15 --queue-size 4` | `configs/from_inferedge.json` with recommended `latency_budget_ms=64.0`. | Generated artifact, not hand-authored policy. It keeps the InferEdge boundary file-based. |
| [`jetson_tensorrt_smoke.json`](jetson_tensorrt_smoke.json) | Run the TensorRT worker inference and runtime telemetry smoke on Jetson. | TensorRT/GPU backend smoke | `ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh` | `reports/jetson_tensorrt_guard_validation.md`, `reports/jetson_tensorrt_runtime_telemetry.json`, and dependency inventory under `reports/`. | Requires TensorRT Python bindings, PyCUDA, and a device-local engine file. This is single-worker identity inference evidence, not multi-task TensorRT scheduling evidence. |
| [`jetson_tensorrt_contention.json`](jetson_tensorrt_contention.json) | Run two TensorRT tasks through scheduler/load-shedding contention on Jetson. | TensorRT/GPU contention smoke | `ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt_contention.sh` | `reports/jetson_tensorrt_contention_telemetry.json` and `reports/jetson_tensorrt_contention_validation.md`. | Requires TensorRT Python bindings, PyCUDA, and a device-local engine file. This validates TensorRT-backed scheduling behavior, not throughput. |

## Notes

- `dummy` worker configs validate scheduler, queue, policy, and telemetry paths
  without loading model files.
- `onnxruntime` worker configs require optional ONNX dependencies and a model
  file.
- TensorRT/GPU backend smoke requires a local TensorRT engine and PyCUDA on
  Jetson. The smoke script validates worker inference and confirms TensorRT
  backend metadata reaches runtime telemetry under ignored `reports/`. See
  [`docs/tensorrt_backend.md`](../docs/tensorrt_backend.md).
- `reports/` outputs are intentionally ignored. Commit curated samples under
  `examples/telemetry/` when reviewer-facing evidence is needed.
- `from_inferedge.json` can be regenerated from
  [`examples/inferedge_result_sample.json`](../examples/inferedge_result_sample.json)
  using the `from-inferedge` CLI command.
