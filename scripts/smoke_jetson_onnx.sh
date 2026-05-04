#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  elif [[ -x "$HOME/miniconda3/envs/yolo_env/bin/python" ]]; then
    PYTHON_BIN="$HOME/miniconda3/envs/yolo_env/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

CONFIG="${CONFIG:-configs/phase2_onnx_demo.json}"
MODEL_PATH="${MODEL_PATH:-models/identity.onnx}"
REPORT_DIR="${REPORT_DIR:-reports}"
TELEMETRY_PATH="${TELEMETRY_PATH:-${REPORT_DIR}/jetson_onnx_smoke.json}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_onnx_validation.md}"
TEGRSTATS_PATH="${TEGRSTATS_PATH:-${REPORT_DIR}/tegrastats_onnx_smoke.log}"
CAPTURE_TEGRASTATS="${CAPTURE_TEGRASTATS:-1}"
TEGRSTATS_INTERVAL_MS="${TEGRSTATS_INTERVAL_MS:-100}"

mkdir -p "$REPORT_DIR" "$(dirname "$MODEL_PATH")"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[onnx-smoke] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[onnx-smoke] config: ${CONFIG}"
echo "[onnx-smoke] model: ${MODEL_PATH}"
echo "[onnx-smoke] telemetry: ${TELEMETRY_PATH}"

"$PYTHON_BIN" - <<'PY'
for name in ["numpy", "onnx", "onnxruntime"]:
    try:
        mod = __import__(name)
        print(f"[onnx-smoke] {name}: {getattr(mod, '__version__', 'unknown')}")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            f"[onnx-smoke] missing dependency: {name}. "
            "Use a Python environment with numpy, onnx, and onnxruntime installed."
        ) from exc
PY

"$PYTHON_BIN" scripts/create_identity_onnx.py --output "$MODEL_PATH"

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
    echo "[onnx-smoke] tegrastats: capturing to ${TEGRSTATS_PATH}"
    tegrastats --interval "$TEGRSTATS_INTERVAL_MS" >"$TEGRSTATS_PATH" &
    TEGRSTATS_PID="$!"
  else
    echo "[onnx-smoke] tegrastats: not found, skipping optional capture"
  fi
fi

"$PYTHON_BIN" -m inferedge_orchestrator run \
  --config "$CONFIG" \
  --output "$TELEMETRY_PATH" \
  --frames 1

sleep 1
cleanup
TEGRSTATS_PID=""

"$PYTHON_BIN" -m inferedge_orchestrator report --input "$TELEMETRY_PATH"

"$PYTHON_BIN" - "$TELEMETRY_PATH" <<'PY'
import json
import sys
from pathlib import Path

telemetry_path = Path(sys.argv[1])
data = json.loads(telemetry_path.read_text(encoding="utf-8"))
identity = data.get("tasks", {}).get("identity")
events = data.get("result_events", [])
snapshots = data.get("resource_snapshots", [])

if identity is None or identity.get("executed") != 1:
    raise SystemExit("[onnx-smoke] telemetry validation failed: identity task did not execute once")
if identity.get("dropped") != 0:
    raise SystemExit("[onnx-smoke] telemetry validation failed: identity task dropped frames")
if not events or events[0].get("output", {}).get("worker") != "onnxruntime":
    raise SystemExit("[onnx-smoke] telemetry validation failed: onnxruntime result event missing")
if events[0].get("output", {}).get("output_shapes") != [[1, 2]]:
    raise SystemExit("[onnx-smoke] telemetry validation failed: unexpected output shape")
if {snapshot.get("stage") for snapshot in snapshots} != {"start", "end"}:
    raise SystemExit("[onnx-smoke] telemetry validation failed: missing start/end resource snapshots")

print("[onnx-smoke] telemetry validation: ok")
PY

DEVICE="$(uname -a)"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
ORT_VERSION="$("$PYTHON_BIN" -c 'import onnxruntime as ort; print(ort.__version__)')"
TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

cat >"$VALIDATION_PATH" <<EOF
# Jetson ONNX Runtime Smoke Validation

- Timestamp UTC: ${TIMESTAMP_UTC}
- Device: ${DEVICE}
- Python: ${PYTHON_VERSION}
- ONNX Runtime: ${ORT_VERSION}
- Config: ${CONFIG}
- Model: ${MODEL_PATH}
- Telemetry: ${TELEMETRY_PATH}
- Optional tegrastats: ${TEGRSTATS_PATH}
- Result: PASS

## Notes

- This validates the ONNX Runtime worker path with an identity ONNX model.
- The current worker uses CPUExecutionProvider; this is not a TensorRT/GPU benchmark.
- Commit README/docs summaries after reviewing the generated artifacts.
EOF

echo "[onnx-smoke] validation record: ${VALIDATION_PATH}"
echo "[onnx-smoke] done"
