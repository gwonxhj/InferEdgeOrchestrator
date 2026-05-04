#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

CONFIG="${CONFIG:-configs/phase4_jetson_smoke.json}"
FRAMES="${FRAMES:-20}"
REPORT_DIR="${REPORT_DIR:-reports}"
TELEMETRY_PATH="${TELEMETRY_PATH:-${REPORT_DIR}/jetson_smoke_dummy.json}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_validation.md}"
TEGRSTATS_PATH="${TEGRSTATS_PATH:-${REPORT_DIR}/tegrastats_smoke.log}"
CAPTURE_TEGRASTATS="${CAPTURE_TEGRASTATS:-0}"
TEGRSTATS_INTERVAL_MS="${TEGRSTATS_INTERVAL_MS:-1000}"

mkdir -p "$REPORT_DIR"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[smoke] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[smoke] config: ${CONFIG}"
echo "[smoke] telemetry: ${TELEMETRY_PATH}"

"$PYTHON_BIN" -c "import inferedge_orchestrator; print('[smoke] import: ok')"

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
    echo "[smoke] tegrastats: capturing to ${TEGRSTATS_PATH}"
    tegrastats --interval "$TEGRSTATS_INTERVAL_MS" >"$TEGRSTATS_PATH" &
    TEGRSTATS_PID="$!"
  else
    echo "[smoke] tegrastats: not found, skipping optional capture"
  fi
fi

"$PYTHON_BIN" -m inferedge_orchestrator run \
  --config "$CONFIG" \
  --output "$TELEMETRY_PATH" \
  --frames "$FRAMES"

"$PYTHON_BIN" -m inferedge_orchestrator report --input "$TELEMETRY_PATH"

"$PYTHON_BIN" - "$TELEMETRY_PATH" <<'PY'
import json
import sys
from pathlib import Path

telemetry_path = Path(sys.argv[1])
data = json.loads(telemetry_path.read_text(encoding="utf-8"))
tasks = data.get("tasks", {})
snapshots = data.get("resource_snapshots", [])

if not tasks:
    raise SystemExit("[smoke] telemetry validation failed: no tasks")
if {snapshot.get("stage") for snapshot in snapshots} != {"start", "end"}:
    raise SystemExit("[smoke] telemetry validation failed: missing start/end resource snapshots")

print("[smoke] telemetry validation: ok")
PY

DEVICE="$(uname -a)"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

cat >"$VALIDATION_PATH" <<EOF
# Jetson Smoke Validation

- Timestamp UTC: ${TIMESTAMP_UTC}
- Device: ${DEVICE}
- Python: ${PYTHON_VERSION}
- Config: ${CONFIG}
- Frames: ${FRAMES}
- Telemetry: ${TELEMETRY_PATH}
- Optional tegrastats: ${TEGRSTATS_PATH}
- Result: PASS

## Notes

- This is a smoke test, not a benchmark.
- Commit README/docs summaries after reviewing the generated artifacts.
EOF

echo "[smoke] validation record: ${VALIDATION_PATH}"
echo "[smoke] done"
