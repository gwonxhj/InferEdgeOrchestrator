# TensorRT Engine Build Procedure

Language: English | [한국어](tensorrt_engine_build.ko.md)

Status: procedure document. This page explains how to create a small local
TensorRT engine on Jetson from the repository's identity ONNX smoke model. It
does not claim TensorRT inference execution, GPU provider validation, or
multi-task TensorRT scheduling evidence.

## Purpose

This procedure prepares the next TensorRT worker step by creating a tiny,
device-local engine file that can be passed to
[`scripts/smoke_jetson_tensorrt.sh`](../scripts/smoke_jetson_tensorrt.sh).

The goal is narrow:

- create a small ONNX model with the existing smoke helper
- serialize it into a TensorRT engine on Jetson
- keep the generated ONNX, engine, and raw build logs out of git
- confirm that the guard smoke script can reach the current TensorRT worker
  not-implemented boundary with a real engine file present

This is still setup for backend development, not a benchmark.

## Artifact Policy

Generated artifacts are local-only:

| Artifact | Example | Git policy |
| --- | --- | --- |
| ONNX smoke model | `models/identity.onnx` | Do not commit. |
| TensorRT engine | `models/identity_fp16.plan` | Do not commit. |
| `trtexec` log | `reports/trtexec_identity_build.log` | Do not commit raw logs. |
| Guard smoke report | `reports/jetson_tensorrt_guard_validation.md` | Do not commit raw reports. |

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
  --buildOnly \
  --verbose \
  > "$BUILD_LOG" 2>&1
```

For an FP32-only build, remove `--fp16` and choose a different output name:

```bash
"$TRTEXEC_BIN" \
  --onnx="$MODEL_PATH" \
  --saveEngine="models/identity_fp32.plan" \
  --buildOnly \
  --verbose \
  > "reports/trtexec_identity_fp32_build.log" 2>&1
```

## Step 4: Check Build Output

```bash
test -s "$ENGINE_PATH"
ls -lh "$ENGINE_PATH"
tail -40 "$BUILD_LOG"
```

The important result is that a non-empty engine file exists. Do not interpret
`trtexec` timing lines as InferEdgeOrchestrator performance evidence.

## Step 5: Run The Guard Smoke Script

After the engine exists, run the current TensorRT worker guard smoke:

```bash
ENGINE_PATH="$ENGINE_PATH" \
  CONFIG=configs/jetson_tensorrt_smoke.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt.sh
```

Expected current result:

- `reports/jetson_tensorrt_dependency.txt` is written.
- `reports/jetson_tensorrt_guard_validation.md` is written.
- Worker guard result is `PASS_GUARD_STUB`.
- The worker still stops at the intentional not-implemented boundary for engine
  deserialization and inference execution.

If the script fails before `PASS_GUARD_STUB`, inspect the validation report and
dependency inventory first. Common causes are a missing TensorRT Python binding,
wrong `ENGINE_PATH`, or a `trtexec` binary path that differs from the surveyed
Jetson.

## What This Enables Next

This procedure creates the local engine artifact needed for the next code step:

1. implement TensorRT engine deserialization behind `TensorRtWorker`
2. create an execution context
3. bind the identity model input/output buffers
4. return worker result metadata without changing scheduler contracts
5. run the same smoke path again and record actual Jetson execution evidence

Keep the project framing stable: TensorRT support is backend coverage for
runtime operation control, not a conversion pipeline or benchmark suite.
