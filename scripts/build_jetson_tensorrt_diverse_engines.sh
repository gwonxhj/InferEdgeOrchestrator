#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$HOME/miniconda3/envs/yolo_env/bin/python" ]]; then
    PYTHON_BIN="$HOME/miniconda3/envs/yolo_env/bin/python"
  elif [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

TRTEXEC_BIN="${TRTEXEC_BIN:-/usr/src/tensorrt/bin/trtexec}"
NVCC_BIN="${NVCC_BIN:-/usr/local/cuda/bin/nvcc}"
MODEL_DIR="${MODEL_DIR:-models/generated}"
REPORT_DIR="${REPORT_DIR:-reports}"
DETECTOR_ONNX="${DETECTOR_ONNX:-${MODEL_DIR}/detector_tiny.onnx}"
CLASSIFIER_ONNX="${CLASSIFIER_ONNX:-${MODEL_DIR}/classifier_tiny.onnx}"
DETECTOR_ENGINE="${DETECTOR_ENGINE:-${MODEL_DIR}/detector_tiny_fp16.plan}"
CLASSIFIER_ENGINE="${CLASSIFIER_ENGINE:-${MODEL_DIR}/classifier_tiny_fp16.plan}"
DETECTOR_BUILD_LOG="${DETECTOR_BUILD_LOG:-${REPORT_DIR}/trtexec_detector_tiny_fp16_build.log}"
CLASSIFIER_BUILD_LOG="${CLASSIFIER_BUILD_LOG:-${REPORT_DIR}/trtexec_classifier_tiny_fp16_build.log}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_engine_build.md}"

mkdir -p "$MODEL_DIR" "$REPORT_DIR"

echo "[trt-diverse-build] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[trt-diverse-build] trtexec: ${TRTEXEC_BIN}"
echo "[trt-diverse-build] model dir: ${MODEL_DIR}"
echo "[trt-diverse-build] validation: ${VALIDATION_PATH}"

if [[ ! -x "$TRTEXEC_BIN" ]]; then
  echo "[trt-diverse-build] missing executable TRTEXEC_BIN=${TRTEXEC_BIN}" >&2
  exit 1
fi

"$PYTHON_BIN" scripts/create_tensorrt_diverse_onnx.py --output-dir "$MODEL_DIR"

test -s "$DETECTOR_ONNX"
test -s "$CLASSIFIER_ONNX"

"$TRTEXEC_BIN" \
  --onnx="$DETECTOR_ONNX" \
  --saveEngine="$DETECTOR_ENGINE" \
  --fp16 \
  --skipInference \
  --verbose \
  >"$DETECTOR_BUILD_LOG" 2>&1

"$TRTEXEC_BIN" \
  --onnx="$CLASSIFIER_ONNX" \
  --saveEngine="$CLASSIFIER_ENGINE" \
  --fp16 \
  --skipInference \
  --verbose \
  >"$CLASSIFIER_BUILD_LOG" 2>&1

test -s "$DETECTOR_ENGINE"
test -s "$CLASSIFIER_ENGINE"

TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
TRT_VERSION="$("$PYTHON_BIN" -c 'import tensorrt as trt; print(trt.__version__)')"
DEVICE="$(uname -a)"
DETECTOR_ENGINE_SIZE="$(wc -c <"$DETECTOR_ENGINE" | tr -d ' ')"
CLASSIFIER_ENGINE_SIZE="$(wc -c <"$CLASSIFIER_ENGINE" | tr -d ' ')"

{
  echo "# Jetson TensorRT Diverse Engine Build"
  echo
  echo "- Timestamp UTC: ${TIMESTAMP_UTC}"
  echo "- Device: ${DEVICE}"
  echo "- Python: ${PYTHON_VERSION}"
  echo "- TensorRT Python: ${TRT_VERSION}"
  echo "- TensorRT CLI: ${TRTEXEC_BIN}"
  if [[ -x "$NVCC_BIN" ]]; then
    echo "- CUDA compiler: $("$NVCC_BIN" --version 2>&1 | tail -1)"
  else
    echo "- CUDA compiler: missing or non-executable ${NVCC_BIN}"
  fi
  echo "- Detector ONNX: ${DETECTOR_ONNX}"
  echo "- Detector engine: ${DETECTOR_ENGINE} (${DETECTOR_ENGINE_SIZE} bytes)"
  echo "- Detector build log: ${DETECTOR_BUILD_LOG}"
  echo "- Classifier ONNX: ${CLASSIFIER_ONNX}"
  echo "- Classifier engine: ${CLASSIFIER_ENGINE} (${CLASSIFIER_ENGINE_SIZE} bytes)"
  echo "- Classifier build log: ${CLASSIFIER_BUILD_LOG}"
  echo "- Result: PASS_TENSORRT_DIVERSE_ENGINE_BUILD"
  echo
  echo "## Notes"
  echo
  echo "- This is a build-only smoke step for future diversified TensorRT contention."
  echo "- It does not claim scheduler behavior or TensorRT throughput."
  echo "- Generated ONNX files, TensorRT engines, and raw build logs are local artifacts."
  echo "- Do not commit generated models, engines, or raw reports."
} >"$VALIDATION_PATH"

echo "[trt-diverse-build] detector engine: ${DETECTOR_ENGINE}"
echo "[trt-diverse-build] classifier engine: ${CLASSIFIER_ENGINE}"
echo "[trt-diverse-build] validation: ${VALIDATION_PATH}"
echo "PASS_TENSORRT_DIVERSE_ENGINE_BUILD"
