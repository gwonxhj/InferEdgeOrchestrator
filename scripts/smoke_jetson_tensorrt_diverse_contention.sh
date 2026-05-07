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

CONFIG="${CONFIG:-configs/jetson_tensorrt_diverse_contention.json}"
FRAMES="${FRAMES:-6}"
REPORT_DIR="${REPORT_DIR:-reports}"
TELEMETRY_PATH="${TELEMETRY_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_contention_telemetry.json}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_contention_validation.md}"
DEPENDENCY_PATH="${DEPENDENCY_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_contention_dependency.txt}"
TEGRSTATS_PATH="${TEGRSTATS_PATH:-${REPORT_DIR}/tegrastats_tensorrt_diverse_contention.log}"
CAPTURE_TEGRASTATS="${CAPTURE_TEGRASTATS:-0}"
TEGRSTATS_INTERVAL_MS="${TEGRSTATS_INTERVAL_MS:-1000}"

mkdir -p "$REPORT_DIR"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[trt-diverse-contention] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[trt-diverse-contention] config: ${CONFIG}"
echo "[trt-diverse-contention] frames: ${FRAMES}"
echo "[trt-diverse-contention] telemetry: ${TELEMETRY_PATH}"
echo "[trt-diverse-contention] validation: ${VALIDATION_PATH}"

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
    echo "[trt-diverse-contention] tegrastats: capturing to ${TEGRSTATS_PATH}"
    tegrastats --interval "$TEGRSTATS_INTERVAL_MS" >"$TEGRSTATS_PATH" &
    TEGRSTATS_PID="$!"
  else
    echo "[trt-diverse-contention] tegrastats: not found, skipping optional capture"
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
  echo "## tegrastats"
  command -v tegrastats || true
} >"$DEPENDENCY_PATH"

set +e
VALIDATION_OUTPUT="$("$PYTHON_BIN" - "$CONFIG" "$FRAMES" "$TELEMETRY_PATH" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.runtime import OrchestratorRuntime

config_path = Path(sys.argv[1])
frames = int(sys.argv[2])
telemetry_path = Path(sys.argv[3])
data = json.loads(config_path.read_text(encoding="utf-8"))
config = OrchestratorConfig.from_dict(data)
for task in config.tasks:
    if task.worker == "tensorrt" and task.engine_path is not None:
        engine_path = Path(task.engine_path)
        if not engine_path.exists():
            raise SystemExit(
                f"[trt-diverse-contention] missing engine for {task.name}: {engine_path}"
            )

runtime = OrchestratorRuntime(config)
report = runtime.run(frames=frames, drain=True)
telemetry_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

tasks = report["tasks"]
detector = tasks["detector_trt"]
classifier = tasks["classifier_trt"]
events = report.get("result_events", [])
policy_decisions = report.get("policy_decisions", [])
overload_events = report.get("overload_events", [])
engine_paths = {
    event.get("output", {}).get("engine_path")
    for event in events
    if event.get("output", {}).get("backend") == "tensorrt"
}
expected_engines = {
    "models/generated/detector_tiny_fp16.plan",
    "models/generated/classifier_tiny_fp16.plan",
}

if detector["executed"] <= 0:
    raise SystemExit("[trt-diverse-contention] validation failed: detector_trt did not execute")
if detector["dropped"] != 0:
    raise SystemExit("[trt-diverse-contention] validation failed: detector_trt was dropped")
if classifier["executed"] <= 0:
    raise SystemExit("[trt-diverse-contention] validation failed: classifier_trt did not execute")
if classifier["dropped"] <= 0:
    raise SystemExit("[trt-diverse-contention] validation failed: classifier_trt was not shed")
if not overload_events:
    raise SystemExit("[trt-diverse-contention] validation failed: no overload_events")
if not any(decision.get("limited_task") == "classifier_trt" for decision in policy_decisions):
    raise SystemExit("[trt-diverse-contention] validation failed: classifier_trt was not limited")
if not events:
    raise SystemExit("[trt-diverse-contention] validation failed: no result_events")
if not all(event.get("output", {}).get("backend") == "tensorrt" for event in events):
    raise SystemExit("[trt-diverse-contention] validation failed: missing TensorRT backend metadata")
if not expected_engines.issubset(engine_paths):
    raise SystemExit(
        "[trt-diverse-contention] validation failed: both distinct TensorRT engines did not execute"
    )

print(
    json.dumps(
        {
            "telemetry_path": str(telemetry_path),
            "frames": frames,
            "detector_executed": detector["executed"],
            "detector_dropped": detector["dropped"],
            "classifier_executed": classifier["executed"],
            "classifier_dropped": classifier["dropped"],
            "result_event_count": len(events),
            "overload_event_count": len(overload_events),
            "limited_tasks": sorted(
                {
                    decision.get("limited_task")
                    for decision in policy_decisions
                    if decision.get("event") == "load_shedding"
                }
            ),
            "engine_paths": sorted(path for path in engine_paths if path),
            "backend": "tensorrt",
        },
        indent=2,
        sort_keys=True,
    )
)
PY
)"
VALIDATION_STATUS=$?
set -e

RESULT="FAIL_UNEXPECTED"
if [[ "$VALIDATION_STATUS" -eq 0 ]] && grep -q '"backend": "tensorrt"' <<<"$VALIDATION_OUTPUT" && grep -q '"classifier_trt"' <<<"$VALIDATION_OUTPUT"; then
  RESULT="PASS_TENSORRT_DIVERSE_CONTENTION"
fi

TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
TRT_VERSION="$("$PYTHON_BIN" -c 'import tensorrt as trt; print(trt.__version__)')"
DEVICE="$(uname -a)"

cat >"$VALIDATION_PATH" <<EOF
# Jetson TensorRT Diverse Contention Smoke

- Timestamp UTC: ${TIMESTAMP_UTC}
- Device: ${DEVICE}
- Python: ${PYTHON_VERSION}
- TensorRT Python: ${TRT_VERSION}
- Config: ${CONFIG}
- Frames: ${FRAMES}
- Telemetry: ${TELEMETRY_PATH}
- Dependency inventory: ${DEPENDENCY_PATH}
- Optional tegrastats: ${TEGRSTATS_PATH}
- Result: ${RESULT}

## Notes

- This smoke runs distinct detector-like and classifier-like TensorRT engines
  through OrchestratorRuntime.
- The expected policy behavior is high-priority detector execution with
  low-priority classifier load shedding under bounded queue pressure.
- This is TensorRT-backed scheduler/load-shedding evidence, not a throughput
  benchmark.
- Do not commit raw reports or TensorRT engine binaries.

## Validation Output

\`\`\`text
${VALIDATION_OUTPUT}
\`\`\`
EOF

echo "[trt-diverse-contention] dependency inventory: ${DEPENDENCY_PATH}"
echo "[trt-diverse-contention] validation record: ${VALIDATION_PATH}"

if [[ "$RESULT" != "PASS_TENSORRT_DIVERSE_CONTENTION" ]]; then
  echo "[trt-diverse-contention] unexpected contention result"
  echo "$VALIDATION_OUTPUT"
  exit 1
fi

echo "[trt-diverse-contention] done"
