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

CONFIG="${CONFIG:-configs/jetson_tensorrt_smoke.json}"
ENGINE_PATH="${ENGINE_PATH:-models/detector.plan}"
REPORT_DIR="${REPORT_DIR:-reports}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_tensorrt_guard_validation.md}"
DEPENDENCY_PATH="${DEPENDENCY_PATH:-${REPORT_DIR}/jetson_tensorrt_dependency.txt}"
TEGRSTATS_PATH="${TEGRSTATS_PATH:-${REPORT_DIR}/tegrastats_tensorrt_guard.log}"
CAPTURE_TEGRASTATS="${CAPTURE_TEGRASTATS:-0}"
TEGRSTATS_INTERVAL_MS="${TEGRSTATS_INTERVAL_MS:-1000}"
TRTEXEC_BIN="${TRTEXEC_BIN:-/usr/src/tensorrt/bin/trtexec}"
NVCC_BIN="${NVCC_BIN:-/usr/local/cuda/bin/nvcc}"

mkdir -p "$REPORT_DIR"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[trt-smoke] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[trt-smoke] config: ${CONFIG}"
echo "[trt-smoke] engine: ${ENGINE_PATH}"
echo "[trt-smoke] validation: ${VALIDATION_PATH}"

TEGRSTATS_PID=""
cleanup() {
  if [[ -n "$TEGRSTATS_PID" ]]; then
    kill "$TEGRSTATS_PID" >/dev/null 2>&1 || true
    wait "$TEGRSTATS_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$CAPTURE_TEGRASTATS" == "1" ]]; then
  if command -v tegrastats >/dev/null 2>&1; then
    echo "[trt-smoke] tegrastats: capturing to ${TEGRSTATS_PATH}"
    tegrastats --interval "$TEGRSTATS_INTERVAL_MS" >"$TEGRSTATS_PATH" &
    TEGRSTATS_PID="$!"
  else
    echo "[trt-smoke] tegrastats: not found, skipping optional capture"
  fi
fi

{
  echo "## host"
  hostname || true
  hostname -I || true
  echo "## kernel"
  uname -a || true
  echo "## l4t"
  if [[ -f /etc/nv_tegra_release ]]; then
    cat /etc/nv_tegra_release
  else
    echo "missing /etc/nv_tegra_release"
  fi
  echo "## python"
  "$PYTHON_BIN" --version
  echo "## tensorrt python"
  "$PYTHON_BIN" -c 'import tensorrt as trt; print(trt.__version__)'
  echo "## trtexec"
  if [[ -x "$TRTEXEC_BIN" ]]; then
    "$TRTEXEC_BIN" --version 2>&1 | sed -n '1,12p' || true
  else
    echo "missing or non-executable TRTEXEC_BIN=${TRTEXEC_BIN}"
  fi
  echo "## nvcc"
  if [[ -x "$NVCC_BIN" ]]; then
    "$NVCC_BIN" --version 2>&1 | tail -5 || true
  else
    echo "missing or non-executable NVCC_BIN=${NVCC_BIN}"
  fi
  echo "## tegrastats"
  command -v tegrastats || true
} >"$DEPENDENCY_PATH"

"$PYTHON_BIN" - "$CONFIG" "$ENGINE_PATH" <<'PY'
import json
import sys
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig

config_path = Path(sys.argv[1])
engine_path = sys.argv[2]
data = json.loads(config_path.read_text(encoding="utf-8"))
for task in data.get("tasks", []):
    if task.get("worker") == "tensorrt":
        task["engine_path"] = engine_path
config = OrchestratorConfig.from_dict(data)
if not any(task.worker == "tensorrt" for task in config.tasks):
    raise SystemExit("[trt-smoke] config validation failed: no tensorrt task")
print("[trt-smoke] config validation: ok")
PY

set +e
WORKER_OUTPUT="$("$PYTHON_BIN" - "$CONFIG" "$ENGINE_PATH" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.workers import WorkerPool

config_path = Path(sys.argv[1])
engine_path = sys.argv[2]
data = json.loads(config_path.read_text(encoding="utf-8"))
for task in data.get("tasks", []):
    if task.get("worker") == "tensorrt":
        task["engine_path"] = engine_path
config = OrchestratorConfig.from_dict(data)
task = next(task for task in config.tasks if task.worker == "tensorrt")
frame = FrameEnvelope(
    frame_id=f"{task.name}-guard-1",
    task_name=task.name,
    sequence=1,
    created_at_ms=0.0,
    deadline_at_ms=task.latency_budget_ms,
    payload={"source": "tensorrt_guard_smoke"},
)
WorkerPool().run(task, frame)
PY
)"
WORKER_STATUS=$?
set -e

EXPECTED_RESULT="FAIL_UNEXPECTED"
if [[ "$WORKER_STATUS" -ne 0 ]] && grep -q "created an execution context, but input/output binding and inference execution are not implemented yet" <<<"$WORKER_OUTPUT"; then
  EXPECTED_RESULT="PASS_GUARD_STUB"
fi

TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
TRT_VERSION="$("$PYTHON_BIN" -c 'import tensorrt as trt; print(trt.__version__)')"
DEVICE="$(uname -a)"

cat >"$VALIDATION_PATH" <<EOF
# Jetson TensorRT Guard Smoke

- Timestamp UTC: ${TIMESTAMP_UTC}
- Device: ${DEVICE}
- Python: ${PYTHON_VERSION}
- TensorRT Python: ${TRT_VERSION}
- Config: ${CONFIG}
- Engine: ${ENGINE_PATH}
- Dependency inventory: ${DEPENDENCY_PATH}
- Optional tegrastats: ${TEGRSTATS_PATH}
- Worker guard result: ${EXPECTED_RESULT}

## Notes

- This is a TensorRT worker guard smoke draft, not a TensorRT inference run.
- The current worker checks TensorRT Python bindings, engine file existence,
  TensorRT engine deserialization, and execution context creation.
- Passing this script means the guard path reached the expected
  not-implemented boundary for input/output binding and inference execution.
- Do not commit raw reports or TensorRT engine binaries.

## Worker Output

\`\`\`text
${WORKER_OUTPUT}
\`\`\`
EOF

echo "[trt-smoke] dependency inventory: ${DEPENDENCY_PATH}"
echo "[trt-smoke] validation record: ${VALIDATION_PATH}"

if [[ "$EXPECTED_RESULT" != "PASS_GUARD_STUB" ]]; then
  echo "[trt-smoke] unexpected worker guard result"
  echo "$WORKER_OUTPUT"
  exit 1
fi

echo "[trt-smoke] done"
