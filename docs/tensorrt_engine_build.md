# TensorRT Engine Build Procedure

Language: English | [한국어](tensorrt_engine_build.ko.md)

Status: procedure document. This page explains how to create a small local
TensorRT engine on Jetson from the repository's identity ONNX smoke model. It
also records the TensorRT worker identity inference smoke. It does not claim
ONNX Runtime GPU provider validation or multi-task TensorRT scheduling evidence.

## Purpose

This procedure prepares the next TensorRT worker step by creating a tiny,
device-local engine file that can be passed to
[`scripts/smoke_jetson_tensorrt.sh`](../scripts/smoke_jetson_tensorrt.sh).

The goal is narrow:

- create a small ONNX model with the existing smoke helper
- serialize it into a TensorRT engine on Jetson
- keep the generated ONNX, engine, and raw build logs out of git
- confirm that the smoke script can execute the identity engine with the current
  TensorRT worker

This is still setup for backend development, not a benchmark.

## Validated Inference Smoke: 2026-05-06

This procedure was run on the surveyed Jetson Orin Nano target:

| Field | Value |
| --- | --- |
| Device | `nano01` |
| OS / L4T | `Ubuntu 22.04.5 LTS`, `L4T R36.4.7` |
| Kernel | `Linux 5.15.148-tegra aarch64` |
| Python | `3.10.12` from `~/miniconda3/envs/yolo_env/bin/python` |
| TensorRT Python | `10.3.0` |
| `trtexec` | TensorRT `v100300` at `/usr/src/tensorrt/bin/trtexec` |
| ONNX model | `models/identity.onnx`, 104 bytes |
| TensorRT engine | `models/identity_fp16.plan`, 8.2 KiB |
| Inference smoke result | `PASS_TENSORRT_INFERENCE` |

The inference smoke executed one identity-model frame and returned TensorRT
worker metadata:

```text
"output_preview": {
  "output": [
    3.0,
    7.0
  ]
}
```

This validates TensorRT dependency availability, engine creation, config
validation, tensor metadata inspection, host/device buffer allocation, tensor
address binding, TensorRT inference execution, and worker result metadata. It is
not a TensorRT benchmark or multi-task scheduler evidence.

## Artifact Policy

Generated artifacts are local-only:

| Artifact | Example | Git policy |
| --- | --- | --- |
| ONNX smoke model | `models/identity.onnx` | Do not commit. |
| TensorRT engine | `models/identity_fp16.plan` | Do not commit. |
| `trtexec` log | `reports/trtexec_identity_build.log` | Do not commit raw logs. |
| Inference smoke report | `reports/jetson_tensorrt_guard_validation.md` | Do not commit raw reports. |

TensorRT engines are device, TensorRT version, CUDA version, and shape/profile
sensitive. Treat them as rebuildable local artifacts.

## Prerequisites

Run this on the Jetson target. The dependency survey recorded the expected
Jetson paths:

| Dependency | Expected path or check |
| --- | --- |
| Python | `~/miniconda3/envs/yolo_env/bin/python` or another env with `onnx` |
| TensorRT CLI | `/usr/src/tensorrt/bin/trtexec` |
| CUDA compiler evidence | `/usr/local/cuda/bin/nvcc` |
| TensorRT Python import | `python -c "import tensorrt as trt; print(trt.__version__)"` |

If `onnx` is missing from the selected Python environment, install the project
development extra in that environment before creating the model:

```bash
python3 -m pip install -e '.[dev]'
```

Do not make the smoke script install system dependencies silently.

## Step 1: Select Paths

```bash
cd ~/InferEdgeOrchestrator

export PYTHON_BIN="${PYTHON_BIN:-$HOME/miniconda3/envs/yolo_env/bin/python}"
export TRTEXEC_BIN="${TRTEXEC_BIN:-/usr/src/tensorrt/bin/trtexec}"
export MODEL_PATH="${MODEL_PATH:-models/identity.onnx}"
export ENGINE_PATH="${ENGINE_PATH:-models/identity_fp16.plan}"
export BUILD_LOG="${BUILD_LOG:-reports/trtexec_identity_build.log}"

mkdir -p models reports
```

Use a repository checkout on the Jetson. The exact checkout path may differ;
the command above assumes `~/InferEdgeOrchestrator`.

## Step 2: Create The Identity ONNX Model

```bash
"$PYTHON_BIN" scripts/create_identity_onnx.py --output "$MODEL_PATH"
```

Optional sanity check:

```bash
"$PYTHON_BIN" - <<'PY'
import onnx
model = onnx.load("models/identity.onnx")
onnx.checker.check_model(model)
print(model.graph.name)
print([input.name for input in model.graph.input])
print([output.name for output in model.graph.output])
PY
```

Expected model shape:

| Binding | Name | Type | Shape |
| --- | --- | --- | --- |
| Input | `input` | `float32` | `[1, 2]` |
| Output | `output` | `float32` | `[1, 2]` |

## Step 3: Build The TensorRT Engine

Build an FP16 engine with `trtexec`:

```bash
"$TRTEXEC_BIN" \
  --onnx="$MODEL_PATH" \
  --saveEngine="$ENGINE_PATH" \
  --fp16 \
  --skipInference \
  --verbose \
  > "$BUILD_LOG" 2>&1
```

For an FP32-only build, remove `--fp16` and choose a different output name:

```bash
"$TRTEXEC_BIN" \
  --onnx="$MODEL_PATH" \
  --saveEngine="models/identity_fp32.plan" \
  --skipInference \
  --verbose \
  > "reports/trtexec_identity_fp32_build.log" 2>&1
```

On the surveyed Jetson TensorRT 10.3.0 environment, `trtexec` accepts
`--skipInference` for this build-only smoke path. Do not use `--buildOnly` on
that device; it is not recognized by the installed `trtexec`.

## Step 4: Check Build Output

```bash
test -s "$ENGINE_PATH"
ls -lh "$ENGINE_PATH"
tail -40 "$BUILD_LOG"
```

The important result is that a non-empty engine file exists. Do not interpret
`trtexec` timing lines as InferEdgeOrchestrator performance evidence.

## Step 5: Run The Inference Smoke Script

After the engine exists, run the current TensorRT worker inference smoke:

```bash
ENGINE_PATH="$ENGINE_PATH" \
  CONFIG=configs/jetson_tensorrt_smoke.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt.sh
```

Expected current result:

- `reports/jetson_tensorrt_dependency.txt` is written.
- `reports/jetson_tensorrt_guard_validation.md` is written.
- `reports/jetson_tensorrt_runtime_telemetry.json` is written.
- Worker smoke result is `PASS_TENSORRT_INFERENCE`.
- Runtime telemetry result is `PASS_TENSORRT_TELEMETRY`.
- The worker executes one identity-model frame and returns TensorRT backend
  metadata including `output_preview`.
- The runtime telemetry `result_events[].output` contains TensorRT backend
  metadata.

If the script fails before `PASS_TENSORRT_INFERENCE`, inspect the validation
report and dependency inventory first. Common causes are a missing TensorRT
Python binding, missing PyCUDA, wrong `ENGINE_PATH`, or a `trtexec` binary path
that differs from the surveyed Jetson.

## What This Enables Next

This procedure creates and validates the local engine artifact needed for later
multi-task TensorRT work:

1. keep worker result metadata stable without changing scheduler contracts
2. validate scheduler/load-shedding behavior under multi-task TensorRT contention
3. curate a small sample telemetry artifact once the TensorRT telemetry shape is
   stable enough for review

Keep the project framing stable: TensorRT support is backend coverage for
runtime operation control, not a conversion pipeline or benchmark suite.

## Diverse Engine Build Draft

The diversified TensorRT contention milestone uses two generated ONNX source
models rather than external downloads. The build-only helper is:

```bash
scripts/build_jetson_tensorrt_diverse_engines.sh
```

Default outputs:

| Artifact | Path | Git policy |
| --- | --- | --- |
| Detector-like ONNX | `models/generated/detector_tiny.onnx` | Do not commit. |
| Classifier-like ONNX | `models/generated/classifier_tiny.onnx` | Do not commit. |
| Detector-like TensorRT engine | `models/generated/detector_tiny_fp16.plan` | Do not commit. |
| Classifier-like TensorRT engine | `models/generated/classifier_tiny_fp16.plan` | Do not commit. |
| Build note | `reports/jetson_tensorrt_diverse_engine_build.md` | Do not commit raw reports. |

The script writes `PASS_TENSORRT_DIVERSE_ENGINE_BUILD` only after both ONNX
files and both non-empty FP16 TensorRT engines exist. This is still a build
contract for a future contention smoke, not scheduler evidence and not a
TensorRT throughput claim.

## Validated Diverse Engine Build: 2026-05-06

This build-only procedure was run on the surveyed Jetson Orin Nano target:

| Field | Value |
| --- | --- |
| Device | `nano01` |
| Kernel | `Linux 5.15.148-tegra aarch64` |
| Python | `3.10.12` from `~/miniconda3/envs/yolo_env/bin/python` |
| TensorRT Python | `10.3.0` |
| TensorRT CLI | `/usr/src/tensorrt/bin/trtexec` |
| CUDA compiler | `Build cuda_12.6.r12.6/compiler.34714021_0` |
| Detector ONNX | `models/generated/detector_tiny.onnx` |
| Detector engine | `models/generated/detector_tiny_fp16.plan`, 44,428 bytes |
| Classifier ONNX | `models/generated/classifier_tiny.onnx` |
| Classifier engine | `models/generated/classifier_tiny_fp16.plan`, 17,764 bytes |
| Result | `PASS_TENSORRT_DIVERSE_ENGINE_BUILD` |

Raw build logs stayed local:

| Log | Local path | Note |
| --- | --- | --- |
| Detector build log | `reports/trtexec_detector_tiny_fp16_build.log` | Not committed. |
| Classifier build log | `reports/trtexec_classifier_tiny_fp16_build.log` | Not committed. |
| Build validation note | `reports/jetson_tensorrt_diverse_engine_build.md` | Not committed. |

The TensorRT CLI reported successful build-only runs with `--skipInference` for
both generated ONNX models. This confirms that the two planned diverse engines
can be generated on the target Jetson, but it still does not prove worker
execution, scheduler behavior, or throughput.
