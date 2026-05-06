# TensorRT Engine Build Procedure

Language: [English](tensorrt_engine_build.md) | 한국어

상태: 절차 문서다. 이 문서는 repository의 identity ONNX smoke model에서 Jetson
local TensorRT engine을 생성하는 방법을 설명한다. TensorRT inference execution,
GPU provider validation, multi-task TensorRT scheduling evidence가 완료되었다고
주장하지 않는다.

## Purpose

이 절차는
[`scripts/smoke_jetson_tensorrt.sh`](../scripts/smoke_jetson_tensorrt.sh)에
전달할 수 있는 작은 device-local engine file을 만들어 다음 TensorRT worker 단계로
넘어가기 위한 준비 작업이다.

목표는 좁게 유지한다.

- 기존 smoke helper로 작은 ONNX model을 생성한다.
- Jetson에서 TensorRT engine으로 serialize한다.
- 생성된 ONNX, engine, raw build log를 git에 넣지 않는다.
- 실제 engine file이 있는 상태에서 guard smoke script가 현재 TensorRT worker의
  not-implemented boundary까지 도달하는지 확인한다.

이 단계도 benchmark가 아니라 backend 개발 준비 절차다.

## Validated Guard Smoke: 2026-05-06

이 절차는 survey된 Jetson Orin Nano target에서 실행되었다.

| Field | Value |
| --- | --- |
| Device | `nano01` |
| OS / L4T | `Ubuntu 22.04.5 LTS`, `L4T R36.4.7` |
| Kernel | `Linux 5.15.148-tegra aarch64` |
| Python | `~/miniconda3/envs/yolo_env/bin/python`의 `3.10.12` |
| TensorRT Python | `10.3.0` |
| `trtexec` | `/usr/src/tensorrt/bin/trtexec`의 TensorRT `v100300` |
| ONNX model | `models/identity.onnx`, 104 bytes |
| TensorRT engine | `models/identity_fp16.plan`, 8.2 KiB |
| Guard smoke result | `PASS_GUARD_STUB` |

guard smoke는 현재 기대하는 worker boundary에 도달했다.

```text
NotImplementedError: tensorrt worker created an execution context, but
input/output binding and inference execution are not implemented yet
```

이 결과는 TensorRT dependency availability, engine creation, config validation,
worker guard path를 검증한다. TensorRT inference evidence는 아니다.

## Artifact Policy

생성 artifact는 local-only다.

| Artifact | Example | Git policy |
| --- | --- | --- |
| ONNX smoke model | `models/identity.onnx` | commit하지 않는다. |
| TensorRT engine | `models/identity_fp16.plan` | commit하지 않는다. |
| `trtexec` log | `reports/trtexec_identity_build.log` | raw log를 commit하지 않는다. |
| Guard smoke report | `reports/jetson_tensorrt_guard_validation.md` | raw report를 commit하지 않는다. |

TensorRT engine은 device, TensorRT version, CUDA version, shape/profile에
민감하다. 재생성 가능한 local artifact로 취급한다.

## Prerequisites

Jetson target에서 실행한다. dependency survey에서 확인한 예상 경로는 다음과 같다.

| Dependency | Expected path or check |
| --- | --- |
| Python | `~/miniconda3/envs/yolo_env/bin/python` 또는 `onnx`가 설치된 다른 env |
| TensorRT CLI | `/usr/src/tensorrt/bin/trtexec` |
| CUDA compiler evidence | `/usr/local/cuda/bin/nvcc` |
| TensorRT Python import | `python -c "import tensorrt as trt; print(trt.__version__)"` |

선택한 Python 환경에 `onnx`가 없다면 model 생성 전에 해당 환경에서 project
development extra를 설치한다.

```bash
python3 -m pip install -e '.[dev]'
```

smoke script가 system dependency를 조용히 설치하게 만들지 않는다.

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

Jetson의 repository checkout에서 실행한다. 위 예시는 `~/InferEdgeOrchestrator`를
가정하지만 실제 경로는 달라질 수 있다.

## Step 2: Create The Identity ONNX Model

```bash
"$PYTHON_BIN" scripts/create_identity_onnx.py --output "$MODEL_PATH"
```

optional sanity check:

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

예상 model shape:

| Binding | Name | Type | Shape |
| --- | --- | --- | --- |
| Input | `input` | `float32` | `[1, 2]` |
| Output | `output` | `float32` | `[1, 2]` |

## Step 3: Build The TensorRT Engine

`trtexec`로 FP16 engine을 생성한다.

```bash
"$TRTEXEC_BIN" \
  --onnx="$MODEL_PATH" \
  --saveEngine="$ENGINE_PATH" \
  --fp16 \
  --skipInference \
  --verbose \
  > "$BUILD_LOG" 2>&1
```

FP32-only build가 필요하면 `--fp16`을 제거하고 output name을 분리한다.

```bash
"$TRTEXEC_BIN" \
  --onnx="$MODEL_PATH" \
  --saveEngine="models/identity_fp32.plan" \
  --skipInference \
  --verbose \
  > "reports/trtexec_identity_fp32_build.log" 2>&1
```

survey된 Jetson TensorRT 10.3.0 환경의 `trtexec`는 이 build-only smoke path에
`--skipInference`를 사용한다. 해당 장치에서는 `--buildOnly`가 인식되지 않으므로
사용하지 않는다.

## Step 4: Check Build Output

```bash
test -s "$ENGINE_PATH"
ls -lh "$ENGINE_PATH"
tail -40 "$BUILD_LOG"
```

중요한 결과는 non-empty engine file이 존재한다는 점이다. `trtexec` timing line을
InferEdgeOrchestrator performance evidence로 해석하지 않는다.

## Step 5: Run The Guard Smoke Script

engine이 생성된 뒤 현재 TensorRT worker guard smoke를 실행한다.

```bash
ENGINE_PATH="$ENGINE_PATH" \
  CONFIG=configs/jetson_tensorrt_smoke.json \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_tensorrt.sh
```

현재 기대 결과:

- `reports/jetson_tensorrt_dependency.txt`가 생성된다.
- `reports/jetson_tensorrt_guard_validation.md`가 생성된다.
- worker guard result는 `PASS_GUARD_STUB`이다.
- worker는 engine deserialization과 execution context creation 성공 후
  input/output binding 및 inference execution에 대한 의도적인 not-implemented
  boundary에서 멈춘다.

script가 `PASS_GUARD_STUB` 이전에 실패하면 validation report와 dependency
inventory를 먼저 확인한다. 흔한 원인은 TensorRT Python binding 누락, 잘못된
`ENGINE_PATH`, survey된 Jetson과 다른 `trtexec` binary path다.

## What This Enables Next

이 절차는 다음 code step에 필요한 local engine artifact를 만든다.

1. identity engine binding/tensor metadata 확인
2. identity model input/output buffer binding
3. scheduler contract를 바꾸지 않고 worker result metadata 반환
4. 같은 smoke path를 다시 실행해 실제 Jetson execution evidence 기록

프로젝트 framing은 유지한다. TensorRT 지원은 runtime operation control을 위한
backend coverage이며 conversion pipeline이나 benchmark suite가 아니다.
