# TensorRT / GPU Backend Status

Language: English | [한국어](tensorrt_backend.ko.md)

Status: config schema, TensorRT engine deserialization, execution context
creation, tensor metadata inspection, host/device buffer allocation, tensor
address binding, TensorRT inference execution, Jetson inference smoke, and
Jetson TensorRT-backed contention evidence are implemented. The schema,
TensorRT worker execution path, `scripts/smoke_jetson_tensorrt.sh`,
`scripts/smoke_jetson_tensorrt_contention.sh`, and
`scripts/smoke_jetson_tensorrt_diverse_contention.sh` are present.

InferEdgeOrchestrator already proves the scheduler, bounded queue, load
shedding, telemetry, ONNX Runtime worker path, and Jetson smoke path. TensorRT
support extends that same runtime operation-control story: it shows how a
TensorRT-backed worker participates in multi-task scheduling and overload
control on Jetson without turning the project into a single-model throughput
benchmark.

## Purpose

The TensorRT-backed path answers one question:

> When deployed inference tasks use TensorRT-backed execution on a constrained
> Jetson device, can the orchestrator keep overload behavior controllable
> through explicit scheduling, bounded queues, load shedding, and telemetry?

This keeps the project aligned with its portfolio position:

- InferEdge validates deployment readiness before operation.
- InferEdgeOrchestrator controls runtime operation after deployment.
- TensorRT support is backend coverage for the worker layer, not a change to the
  runtime operation-control purpose.

## Non-Goals

This backend path must not become:

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

A TensorRT worker plugs into this interface without changing scheduler, queue,
load-shedding, or telemetry top-level contracts. The scheduler continues to
choose tasks by priority and deadline. The worker is responsible for loading a
backend-specific runtime, executing the selected task, and returning
latency/result metadata.

## Config Schema Status

The config schema accepts a `tensorrt` worker selection and preserves backward
compatibility for existing `dummy` and `onnxruntime` configs. The worker layer
can deserialize a configured TensorRT engine, create an execution context,
record name-based input/output tensor metadata, allocate and bind input/output
buffers, execute TensorRT with `execute_async_v3`, copy device outputs back to
host buffers, return backend result metadata, and cache runtime objects by
engine path.

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
configured engine, creates an execution context, records input/output tensor
metadata, allocates host/device buffers, binds tensor addresses, and executes
the selected frame through TensorRT.

## Current Validation Rules

Config validation currently enforces:

- `dummy` and `onnxruntime` configs remain backward-compatible.
- `worker="tensorrt"` requires `engine_path`.
- `engine_path` must not be empty when provided.
- `worker_options` must be a mapping when provided.
- `worker_options.allow_engine_build` must be a boolean when provided.
- `worker_options.providers` must be a list of non-empty strings when provided.
- Generated engine files are local artifacts and should not be committed.

Worker behavior currently enforces:

- `worker="tensorrt"` fails clearly when TensorRT Python bindings are not
  installed.
- `worker="tensorrt"` fails clearly when the configured `engine_path` file does
  not exist.
- `worker="tensorrt"` fails clearly when TensorRT cannot deserialize the
  configured engine.
- `worker="tensorrt"` fails clearly when TensorRT cannot create an execution
  context.
- `worker="tensorrt"` fails clearly when the engine exposes no input or output
  tensors through TensorRT name-based tensor APIs.
- `worker="tensorrt"` fails clearly when PyCUDA is unavailable for TensorRT
  host/device buffer allocation.
- `worker="tensorrt"` initializes the PyCUDA CUDA context before TensorRT engine
  deserialization to keep TensorRT execution resources on the same CUDA context.
- `worker="tensorrt"` fails clearly when TensorRT cannot bind tensor addresses
  through `context.set_tensor_address`.
- `worker="tensorrt"` fails clearly when `context.execute_async_v3` is missing
  or returns failure.
- `worker="tensorrt"` accepts optional `frame.payload["tensorrt_inputs"]` values
  and validates their shapes before host-to-device copy.
- `worker="tensorrt"` caches deserialized engines, execution contexts, and bound
  buffers by engine path.
- `worker="tensorrt"` returns backend result metadata including engine path,
  TensorRT version, input/output shapes, output dtypes, output count, and a
  small output preview.
- `scripts/smoke_jetson_tensorrt.sh` can be run on Jetson to confirm dependency
  inventory capture, config validation, TensorRT engine deserialization,
  execution context creation, tensor metadata inspection, host/device buffer
  allocation, tensor address binding, TensorRT inference execution, and worker
  result metadata output.
- The same script also runs `OrchestratorRuntime` for one frame and validates
  that `result_events[].output` contains TensorRT backend metadata.

Remaining validation guardrails:

- Fallback from TensorRT/GPU to CPU must be explicit in config and telemetry.
- Any future broader TensorRT scenario must continue to prove operation-control
  behavior, not model throughput leadership.

## Jetson TensorRT Inference Smoke

The inference smoke script is:

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh
```

Useful environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYTHON_BIN` | `~/miniconda3/envs/yolo_env/bin/python`, then `.venv/bin/python`, then `python3` | Python interpreter used for TensorRT import and worker smoke checks. |
| `CONFIG` | `configs/jetson_tensorrt_smoke.json` | TensorRT inference smoke config. |
| `ENGINE_PATH` | `models/detector.plan` | Device-local TensorRT engine path passed into the config at runtime. |
| `REPORT_DIR` | `reports` | Ignored output directory for local Jetson artifacts. |
| `VALIDATION_PATH` | `reports/jetson_tensorrt_guard_validation.md` | Human-readable TensorRT smoke record. |
| `RUNTIME_TELEMETRY_PATH` | `reports/jetson_tensorrt_runtime_telemetry.json` | Runtime telemetry JSON used to validate `result_events[].output` backend metadata. |
| `DEPENDENCY_PATH` | `reports/jetson_tensorrt_dependency.txt` | Host, L4T, Python, TensorRT, `trtexec`, `nvcc`, and `tegrastats` inventory. |
| `CAPTURE_TEGRASTATS` | `0` | Set to `1` to capture optional `tegrastats` output. |
| `TEGRSTATS_PATH` | `reports/tegrastats_tensorrt_guard.log` | Optional raw `tegrastats` capture path. |
| `TEGRSTATS_INTERVAL_MS` | `1000` | Optional `tegrastats` capture interval. |
| `TRTEXEC_BIN` | `/usr/src/tensorrt/bin/trtexec` | Explicit Jetson TensorRT CLI path. |
| `NVCC_BIN` | `/usr/local/cuda/bin/nvcc` | Explicit Jetson CUDA compiler path for version evidence. |

Expected current behavior:

- TensorRT Python import must succeed.
- `ENGINE_PATH` must point to a local engine file.
- The worker must execute one identity-model frame and return TensorRT backend
  result metadata.
- Runtime telemetry must include TensorRT backend metadata under
  `result_events[].output`.
- The script writes local reports under ignored `reports/`.

This is TensorRT worker execution evidence for a tiny identity model. It is not
a throughput benchmark. Multi-task TensorRT-backed scheduler/load-shedding
evidence is tracked separately in the contention smoke sections below.

To create the small local engine used by this smoke path, see
[`docs/tensorrt_engine_build.md`](tensorrt_engine_build.md).

## Jetson TensorRT Contention Smoke

The contention smoke script is:

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt_contention.sh
```

It runs two TensorRT tasks through `OrchestratorRuntime`:

| Task | Priority | Expected role |
| --- | --- | --- |
| `detector_trt` | 100 | protected high-priority task |
| `classifier_trt` | 10 | low-priority task limited by load shedding |

The smoke validates:

- TensorRT backend metadata appears in all runtime result events.
- `overload_events` are recorded.
- policy decisions include `limited_task="classifier_trt"`.
- `classifier_trt` drops frames while `detector_trt` still executes.

This is TensorRT-backed scheduler/load-shedding evidence. It is intentionally
not a throughput benchmark and it currently uses the same tiny identity engine
for both tasks to keep the artifact local, small, and reproducible.

## Model Diversity Status

The initial TensorRT contention smoke used the same tiny identity engine for
both tasks to keep the first Jetson evidence local, small, and reproducible.
The current repository also includes a distinct generated detector/classifier
engine path:

- `scripts/create_tiny_onnx_models.py`
- `scripts/build_jetson_tensorrt_diverse_engines.sh`
- `scripts/smoke_jetson_tensorrt_individual_engines.sh`
- `scripts/smoke_jetson_tensorrt_diverse_contention.sh`
- `configs/jetson_tensorrt_diverse_contention.json`
- `examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`

The diversified contention evidence confirms that distinct generated
detector-like and classifier-like TensorRT engines can participate in the same
scheduler/load-shedding telemetry shape. It remains runtime operation-control
evidence, not a TensorRT throughput benchmark or production serving claim.

Future model diversity work should only expand from this point if it keeps the
same boundaries:

- source model license and generation path are documented
- TensorRT engine binaries and large model files stay out of git
- telemetry proves high-priority protection and low-priority limiting
- documentation states that the result is operation-control evidence, not a
  model-quality or throughput comparison

The model-diversity proposal and current evidence record are tracked in
[`docs/tensorrt_model_diversity.md`](tensorrt_model_diversity.md).

## Telemetry Contract

The current telemetry top-level shape should remain stable. TensorRT/GPU support
should add backend metadata inside worker result events rather than changing
scheduler summaries.

Worker metadata includes or may include:

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

The TensorRT worker path was preceded by a small dependency inventory on the
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
- Smoke scripts should call `/usr/src/tensorrt/bin/trtexec` explicitly or add
  `/usr/src/tensorrt/bin` to `PATH`.
- Smoke scripts should call `/usr/local/cuda/bin/nvcc` explicitly if they need
  compiler version evidence.
- ONNX Runtime GPU provider validation is not ready from the current
  `yolo_env` because only `AzureExecutionProvider` and `CPUExecutionProvider`
  are exposed at runtime.
- This survey is dependency inventory only. Later Jetson smoke records provide
  TensorRT engine execution and TensorRT-backed scheduler/load-shedding
  evidence. ONNX Runtime GPU provider validation remains separate.

## Smoke Script Status

The TensorRT smoke scripts are present and write local report artifacts under
ignored `reports/` paths.

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `PYTHON_BIN` | Select the Jetson Python environment. |
| `CONFIG` | TensorRT smoke config path. |
| `OUTPUT` | Telemetry output path, usually under `reports/`. |
| `ENGINE_PATH` | Device-local TensorRT engine path. |
| `CAPTURE_TEGRASTATS` | Optional `tegrastats` capture for smoke evidence. |

The scripts create local `reports/` artifacts, not tracked release artifacts.
Curated summaries are copied into docs or `examples/telemetry/` only after
review.

## Completed Implementation Sequence

1. Add this backend design document and schema plan.
2. Survey Jetson TensorRT, ONNX Runtime provider, and Python dependency state.
3. Add config schema fields behind tests while preserving existing configs.
4. Add a TensorRT worker stub with optional-import failure messages.
5. Add a Jetson smoke script draft.
6. Run a real TensorRT engine on Jetson over SSH.
7. Record telemetry from a single TensorRT worker smoke.
8. Run a multi-task scenario with TensorRT-backed execution.
9. Add distinct generated detector/classifier TensorRT contention evidence.
10. Update validation evidence and README positioning with confirmed results.

## Completion Criteria

This backend validation path is complete when:

- Existing tests still pass.
- Existing `dummy` and `onnxruntime` configs remain valid.
- TensorRT config validation is explicit and documented.
- Jetson smoke output proves TensorRT worker execution.
- Jetson contention smoke output proves TensorRT-backed scheduler/load-shedding
  behavior.
- Telemetry records backend metadata without breaking existing schema readers.
- The README continues to describe the project as a runtime operation-control
  layer, not a benchmark or Triton/DeepStream replacement.
