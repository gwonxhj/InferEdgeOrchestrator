# TensorRT / GPU Backend Plan

Language: English | [한국어](tensorrt_backend.ko.md)

Status: schema, TensorRT engine deserialization, execution context creation,
and Jetson guard-smoke validation. The config schema, TensorRT worker
deserialization/context path, and `scripts/smoke_jetson_tensorrt.sh` are
present. Jetson guard smoke reached `PASS_GUARD_STUB` with a local
`models/identity_fp16.plan` engine, but this document does not claim that
TensorRT input/output binding, inference execution, GPU provider execution, or
multi-task TensorRT scheduling evidence is implemented yet.

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

## Config Schema Status

The config schema accepts a `tensorrt` worker selection and preserves backward
compatibility for existing `dummy` and `onnxruntime` configs. The worker layer
can deserialize a configured TensorRT engine, create an execution context, and
cache both by engine path, but TensorRT input/output binding and inference
execution are still not implemented.

Task fields:

| Field | Status | Purpose |
| --- | --- | --- |
| `worker` | Existing, enum extended | Accepts `dummy`, `onnxruntime`, and `tensorrt`. |
| `model_path` | Existing | Keep as the source model/reference path. Do not overload it as a generated TensorRT engine path. |
| `engine_path` | Optional field | Device-local TensorRT engine path. Required when `worker` is `tensorrt`. |
| `worker_options` | Optional mapping | Backend-specific options that should not become global task-policy fields. |

Recognized `worker_options` keys:

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

Schema-valid example:

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

This example validates as config schema. Runtime execution with
`worker="tensorrt"` currently checks TensorRT prerequisites, deserializes the
configured engine, creates an execution context, and then raises a clear
not-implemented error until input/output binding and inference execution are
added.

## Current Validation Rules

Config validation currently enforces:

- `dummy` and `onnxruntime` configs remain backward-compatible.
- `worker="tensorrt"` requires `engine_path`.
- `engine_path` must not be empty when provided.
- `worker_options` must be a mapping when provided.
- `worker_options.allow_engine_build` must be a boolean when provided.
- `worker_options.providers` must be a list of non-empty strings when provided.
- Generated engine files are local artifacts and should not be committed.

Worker guard behavior currently enforces:

- `worker="tensorrt"` fails clearly when TensorRT Python bindings are not
  installed.
- `worker="tensorrt"` fails clearly when the configured `engine_path` file does
  not exist.
- `worker="tensorrt"` fails clearly when TensorRT cannot deserialize the
  configured engine.
- `worker="tensorrt"` fails clearly when TensorRT cannot create an execution
  context.
- `worker="tensorrt"` caches deserialized engines and execution contexts by
  engine path.
- `scripts/smoke_jetson_tensorrt.sh` can be run on Jetson to confirm dependency
  inventory capture, config validation, TensorRT engine deserialization,
  execution context creation, and the current expected not-implemented boundary
  for input/output binding and inference execution.

Validation rules still to add with real TensorRT execution:

- Fallback from TensorRT/GPU to CPU must be explicit in config and telemetry.
- Inference execution must report backend metadata in result events.

## Jetson TensorRT Guard Smoke Draft

The guard smoke script is:

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh
```

Useful environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYTHON_BIN` | `~/miniconda3/envs/yolo_env/bin/python`, then `.venv/bin/python`, then `python3` | Python interpreter used for TensorRT import and worker guard checks. |
| `CONFIG` | `configs/jetson_tensorrt_smoke.json` | TensorRT guard smoke config. |
| `ENGINE_PATH` | `models/detector.plan` | Device-local TensorRT engine path passed into the config at runtime. |
| `REPORT_DIR` | `reports` | Ignored output directory for local Jetson artifacts. |
| `VALIDATION_PATH` | `reports/jetson_tensorrt_guard_validation.md` | Human-readable guard-smoke record. |
| `DEPENDENCY_PATH` | `reports/jetson_tensorrt_dependency.txt` | Host, L4T, Python, TensorRT, `trtexec`, `nvcc`, and `tegrastats` inventory. |
| `CAPTURE_TEGRASTATS` | `0` | Set to `1` to capture optional `tegrastats` output. |
| `TEGRSTATS_PATH` | `reports/tegrastats_tensorrt_guard.log` | Optional raw `tegrastats` capture path. |
| `TEGRSTATS_INTERVAL_MS` | `1000` | Optional `tegrastats` capture interval. |
| `TRTEXEC_BIN` | `/usr/src/tensorrt/bin/trtexec` | Explicit Jetson TensorRT CLI path. |
| `NVCC_BIN` | `/usr/local/cuda/bin/nvcc` | Explicit Jetson CUDA compiler path for version evidence. |

Expected current behavior:

- TensorRT Python import must succeed.
- `ENGINE_PATH` must point to a local engine file.
- The worker must reach the current clear not-implemented boundary for
  input/output binding and inference execution after engine deserialization and
  execution context creation succeed.
- The script writes local reports under ignored `reports/`.

This is not TensorRT inference evidence. It proves that the Jetson environment,
engine artifact, deserialization path, and execution context path are ready for
the next implementation step.

To create the small local engine used by this smoke path, see
[`docs/tensorrt_engine_build.md`](tensorrt_engine_build.md).

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

### Survey Result: 2026-05-06

Target device:

| Item | Result |
| --- | --- |
| Host | `nano01` |
| Address | `192.168.45.63` |
| OS | Ubuntu 22.04.5 LTS |
| Kernel | `Linux 5.15.148-tegra aarch64` |
| L4T | `36.4.7` (`R36`, revision `4.7`) |
| Device | Jetson Orin Nano Developer Kit, 25W mode |

Runtime inventory:

| Dependency | Result | Note |
| --- | --- | --- |
| CUDA | `12.6.68` runtime, `12.6.11` SDK metadata | `/usr/local/cuda/version.json` is present. |
| `nvcc` | `12.6.68` | Available at `/usr/local/cuda/bin/nvcc`; not on the non-interactive SSH `PATH`. |
| cuDNN | `9.3.0.75` | `libcudnn9-cuda-12` and dev package installed. |
| TensorRT | `10.3.0.30` packages, Python import reports `10.3.0` | `python3-libnvinfer` is installed. |
| TensorRT ONNX parser | Installed | `libnvonnxparsers10` and dev package installed. |
| `trtexec` | Available at `/usr/src/tensorrt/bin/trtexec` | Not on the non-interactive SSH `PATH`. |
| `tegrastats` | Available at `/usr/bin/tegrastats` | One-line smoke capture succeeded. |
| GPU device nodes | Present | `/dev/nvhost-gpu`, `/dev/nvhost-ctrl-gpu`, and `/dev/nvmap` exist. |
| `jetson_release` | Available | Reports `jetson-stats 4.3.2`; JetPack label is missing, but L4T/libraries are visible. |

Python environment inventory:

| Environment | Python | TensorRT | ONNX Runtime | PyCUDA | Notes |
| --- | --- | --- | --- | --- | --- |
| System Python | `3.10.12` at `/usr/bin/python3` | `10.3.0` import succeeds | Not installed | Not installed | Good for TensorRT import checks, not for current ONNX Runtime provider work. |
| `yolo_env` | `3.10.12` at `/home/risenano01/miniconda3/envs/yolo_env/bin/python` | `10.3.0` import succeeds | `1.23.2`, providers: `AzureExecutionProvider`, `CPUExecutionProvider` | Import succeeds | `onnxruntime-gpu 1.17.0` is also listed by pip, but `ort.get_available_providers()` did not expose CUDA/TensorRT providers in this env. |

Observed ONNX Runtime warning in `yolo_env`:

```text
GPU device discovery failed: ReadFileContents Failed to open file:
"/sys/class/drm/card1/device/vendor"
```

Interpretation:

- Native TensorRT worker development is feasible on this Jetson because
  TensorRT Python bindings, TensorRT libraries, ONNX parser packages, PyCUDA,
  CUDA, cuDNN, and `tegrastats` are present.
- A future smoke script should call `/usr/src/tensorrt/bin/trtexec` explicitly
  or add `/usr/src/tensorrt/bin` to `PATH`.
- A future smoke script should call `/usr/local/cuda/bin/nvcc` explicitly if it
  needs compiler version evidence.
- ONNX Runtime GPU provider validation is not ready from the current
  `yolo_env` because only `AzureExecutionProvider` and `CPUExecutionProvider`
  are exposed at runtime.
- This is dependency inventory only. It does not prove TensorRT engine
  execution, GPU provider execution, or scheduler behavior with TensorRT.

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
