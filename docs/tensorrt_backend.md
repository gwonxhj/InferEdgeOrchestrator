# TensorRT / GPU Backend Plan

Language: English | [한국어](tensorrt_backend.ko.md)

Status: design and schema plan. This document does not claim that a TensorRT
worker, GPU provider path, or TensorRT engine execution is implemented yet.

InferEdgeOrchestrator already proves the scheduler, bounded queue, load
shedding, telemetry, ONNX Runtime worker path, and Jetson smoke path. The
TensorRT/GPU backend should extend that same operation-control story: it should
show how a GPU-backed worker participates in multi-task scheduling and overload
control on Jetson, not turn the project into a single-model benchmark.

## Purpose

The future backend should answer one question:

> When deployed inference tasks use GPU/TensorRT execution on a constrained
> Jetson device, can the orchestrator still protect high-priority task latency
> through explicit scheduling, bounded queues, load shedding, and telemetry?

This keeps the project aligned with its portfolio position:

- InferEdge validates deployment readiness before operation.
- InferEdgeOrchestrator controls runtime operation after deployment.
- TensorRT/GPU support is backend coverage for the worker layer, not a change to
  the scheduler's purpose.

## Non-Goals

This extension must not become:

- A TensorRT benchmark suite.
- A replacement for Triton or DeepStream.
- A model conversion pipeline. Engine creation can be documented or scripted for
  smoke validation, but Forge remains the conversion/provenance layer in the
  broader InferEdge ecosystem.
- A large-model artifact repository. Generated engines, large ONNX files, raw
  device logs, and temporary Jetson outputs should stay out of git.

## Backend Boundary

The existing worker interface is intentionally stable:

```python
class Worker(Protocol):
    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        ...
```

A TensorRT worker should plug into this interface without changing scheduler,
queue, load-shedding, or telemetry top-level contracts. The scheduler should
continue to choose tasks by priority and deadline. The worker should only be
responsible for loading a backend-specific runtime, executing the selected
task, and returning latency/result metadata.

## Config Schema Plan

The current supported workers are `dummy` and `onnxruntime`. Future TensorRT/GPU
support should be added with backward-compatible optional fields.

Planned task fields:

| Field | Status | Purpose |
| --- | --- | --- |
| `worker` | Existing, extend enum | Add future value `tensorrt` while keeping `dummy` and `onnxruntime` valid. |
| `model_path` | Existing | Keep as the source model/reference path. Do not overload it as a generated TensorRT engine path. |
| `engine_path` | Planned optional field | Device-local TensorRT engine path. Required when `worker` is `tensorrt`. |
| `worker_options` | Planned optional mapping | Backend-specific options that should not become global task-policy fields. |

Planned `worker_options` keys:

| Key | Purpose |
| --- | --- |
| `precision` | Requested precision label such as `fp16` or `fp32`; recorded for telemetry. |
| `warmup_runs` | Number of warmup executions before measured smoke frames. |
| `device_id` | Jetson GPU device id when the backend exposes one. |
| `allow_engine_build` | Explicit opt-in for building an engine from a model path. Default should be `false`. |
| `profile_name` | Optional TensorRT optimization profile label. |
| `input_bindings` | Optional input binding metadata when a smoke model needs explicit names or shapes. |
| `output_bindings` | Optional output binding metadata for result metadata validation. |
| `providers` | Optional ONNX Runtime provider list for GPU-provider experiments, for example `TensorrtExecutionProvider`, `CUDAExecutionProvider`, `CPUExecutionProvider`. |

Design-only example:

```json
{
  "run": {
    "name": "jetson_tensorrt_smoke",
    "input_source": "dummy",
    "overload_backlog_threshold": 6
  },
  "tasks": [
    {
      "name": "detector_trt",
      "model_path": "models/detector.onnx",
      "engine_path": "models/detector.plan",
      "priority": 100,
      "target_fps": 15,
      "latency_budget_ms": 80,
      "queue_size": 4,
      "drop_policy": "drop_oldest",
      "worker": "tensorrt",
      "worker_options": {
        "precision": "fp16",
        "warmup_runs": 5,
        "device_id": 0,
        "allow_engine_build": false
      }
    }
  ]
}
```

This example is not valid against the current implementation. It is the target
schema shape for a later config/schema PR.

## Validation Rules To Add Later

When implementation starts, config validation should enforce:

- `dummy` and `onnxruntime` configs remain backward-compatible.
- `worker="tensorrt"` requires `engine_path`.
- `worker="tensorrt"` should fail clearly when TensorRT Python bindings are not
  installed.
- `allow_engine_build` defaults to `false`; implicit engine generation should
  not happen during normal scheduler tests.
- Fallback from TensorRT/GPU to CPU must be explicit in config and telemetry.
- Generated engine files are local artifacts and should not be committed.

## Telemetry Plan

The current telemetry top-level shape should remain stable. TensorRT/GPU support
should add backend metadata inside worker result events rather than changing
scheduler summaries.

Planned worker metadata:

- `worker`: `tensorrt`
- `backend`: `tensorrt`
- `engine_path`
- `precision`
- `device_id`
- `warmup_runs`
- `engine_loaded`
- `input_shapes`
- `output_shapes`
- `provider` or `providers` when testing ONNX Runtime GPU provider paths

The key evidence is still operational: which task ran, which task was dropped,
which task was protected, and whether overload decisions were recorded.

## Jetson Dependency Survey

Before writing the real worker, capture a small dependency inventory on the
target Jetson:

```bash
trtexec --version
python -c "import tensorrt as trt; print(trt.__version__)"
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
python -c "import pycuda.driver as cuda; print('pycuda ok')"
cat /etc/nv_tegra_release
uname -a
```

`pycuda` may be optional depending on the TensorRT execution approach. Jetson
does not normally use `nvidia-smi`; `tegrastats`, `/etc/nv_tegra_release`, and
the existing telemetry resource snapshots are the preferred smoke evidence.

## Smoke Script Plan

A later script can be added as `scripts/smoke_jetson_tensorrt.sh`.

Planned environment variables:

| Variable | Purpose |
| --- | --- |
| `PYTHON_BIN` | Select the Jetson Python environment. |
| `CONFIG` | TensorRT smoke config path. |
| `OUTPUT` | Telemetry output path, usually under `reports/`. |
| `ENGINE_PATH` | Device-local TensorRT engine path. |
| `CAPTURE_TEGRASTATS` | Optional `tegrastats` capture for smoke evidence. |

The script should create local `reports/` artifacts, not tracked release
artifacts. Curated summaries can be copied into docs or
`examples/telemetry/` only after review.

## Recommended Implementation Sequence

1. Add this backend design document and schema plan.
2. Survey Jetson TensorRT, ONNX Runtime provider, and Python dependency state.
3. Add config schema fields behind tests while preserving existing configs.
4. Add a TensorRT worker stub with optional-import failure messages.
5. Add a Jetson smoke script draft.
6. Run a real TensorRT engine on Jetson over SSH.
7. Record telemetry from a single TensorRT worker smoke.
8. Run a multi-task scenario with TensorRT/GPU execution.
9. Update validation evidence and README positioning with confirmed results.

## Completion Criteria

This extension is complete only when:

- Existing tests still pass.
- Existing `dummy` and `onnxruntime` configs remain valid.
- TensorRT config validation is explicit and documented.
- Jetson smoke output proves TensorRT/GPU worker execution.
- Telemetry records backend metadata without breaking existing schema readers.
- The README continues to describe the project as a lightweight edge scheduler,
  not a benchmark or Triton/DeepStream replacement.
