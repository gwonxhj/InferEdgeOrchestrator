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

MODEL_DIR="${MODEL_DIR:-models/generated}"
REPORT_DIR="${REPORT_DIR:-reports}"
DETECTOR_ENGINE="${DETECTOR_ENGINE:-${MODEL_DIR}/detector_tiny_fp16.plan}"
CLASSIFIER_ENGINE="${CLASSIFIER_ENGINE:-${MODEL_DIR}/classifier_tiny_fp16.plan}"
VALIDATION_PATH="${VALIDATION_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_guard_validation.md}"
RESULT_PATH="${RESULT_PATH:-${REPORT_DIR}/jetson_tensorrt_diverse_guard_results.json}"

mkdir -p "$REPORT_DIR"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[trt-diverse-guard] python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
echo "[trt-diverse-guard] detector engine: ${DETECTOR_ENGINE}"
echo "[trt-diverse-guard] classifier engine: ${CLASSIFIER_ENGINE}"
echo "[trt-diverse-guard] validation: ${VALIDATION_PATH}"
echo "[trt-diverse-guard] result json: ${RESULT_PATH}"

test -s "$DETECTOR_ENGINE"
test -s "$CLASSIFIER_ENGINE"

"$PYTHON_BIN" - "$DETECTOR_ENGINE" "$CLASSIFIER_ENGINE" "$RESULT_PATH" <<'PY'
import json
import sys
from pathlib import Path

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.workers import WorkerPool

detector_engine = Path(sys.argv[1])
classifier_engine = Path(sys.argv[2])
result_path = Path(sys.argv[3])


def make_task(name: str, engine_path: Path, priority: int) -> TaskConfig:
    return TaskConfig.from_dict(
        {
            "name": name,
            "model_path": str(engine_path.with_suffix(".onnx")),
            "engine_path": str(engine_path),
            "priority": priority,
            "target_fps": 5,
            "latency_budget_ms": 200,
            "queue_size": 2,
            "drop_policy": "drop_oldest",
            "worker": "tensorrt",
            "worker_options": {
                "precision": "fp16",
                "allow_engine_build": False,
            },
        }
    )


def make_frame(task_name: str, input_name: str, value: object) -> FrameEnvelope:
    return FrameEnvelope(
        frame_id=f"{task_name}-guard-1",
        task_name=task_name,
        sequence=1,
        created_at_ms=0.0,
        deadline_at_ms=200.0,
        payload={
            "source": "tensorrt_diverse_guard_smoke",
            "tensorrt_inputs": {input_name: value},
        },
    )


pool = WorkerPool()
checks = [
    (
        make_task("detector_trt", detector_engine, 100),
        make_frame(
            "detector_trt",
            "detector_input",
            [[[[0.25 for _ in range(16)] for _ in range(16)] for _ in range(3)]],
        ),
        "detector_input",
        "detector_scores",
        [1, 3, 16, 16],
        [1, 6],
    ),
    (
        make_task("classifier_trt", classifier_engine, 10),
        make_frame("classifier_trt", "classifier_input", [[float(i) / 16.0 for i in range(16)]]),
        "classifier_input",
        "classifier_logits",
        [1, 16],
        [1, 4],
    ),
]

results = []
for task, frame, input_name, output_name, input_shape, output_shape in checks:
    result = pool.run(task, frame)
    output = result.output
    if output.get("worker") != "tensorrt" or output.get("backend") != "tensorrt":
        raise SystemExit(f"{task.name}: missing TensorRT backend metadata")
    if output.get("input_shapes", {}).get(input_name) != input_shape:
        raise SystemExit(f"{task.name}: unexpected input shape metadata")
    if output.get("output_shapes", {}).get(output_name) != output_shape:
        raise SystemExit(f"{task.name}: unexpected output shape metadata")
    if output.get("output_count") != 1:
        raise SystemExit(f"{task.name}: expected one output tensor")
    if output_name not in output.get("output_preview", {}):
        raise SystemExit(f"{task.name}: missing output preview")
    results.append(
        {
            "task_name": result.task_name,
            "frame_id": result.frame_id,
            "latency_ms": result.latency_ms,
            "output": output,
        }
    )

result_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps({"result_path": str(result_path), "result_count": len(results)}, sort_keys=True))
PY

TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
TRT_VERSION="$("$PYTHON_BIN" -c 'import tensorrt as trt; print(trt.__version__)')"
DEVICE="$(uname -a)"

cat >"$VALIDATION_PATH" <<EOF
# Jetson TensorRT Diverse Engine Guard Smoke

- Timestamp UTC: ${TIMESTAMP_UTC}
- Device: ${DEVICE}
- Python: ${PYTHON_VERSION}
- TensorRT Python: ${TRT_VERSION}
- Detector engine: ${DETECTOR_ENGINE}
- Classifier engine: ${CLASSIFIER_ENGINE}
- Result JSON: ${RESULT_PATH}
- Result: PASS_TENSORRT_DIVERSE_GUARD

## Notes

- This smoke runs the generated detector-like and classifier-like TensorRT
  engines through TensorRtWorker individually.
- Passing this script means each engine deserialized, created an execution
  context, exposed TensorRT tensor metadata, allocated and bound host/device
  buffers, executed TensorRT inference, and returned backend metadata.
- This is worker guard evidence. It is not scheduler/load-shedding contention
  evidence and not TensorRT throughput evidence.
- Do not commit generated engines, raw result JSON, or raw validation reports.
EOF

echo "[trt-diverse-guard] validation: ${VALIDATION_PATH}"
echo "PASS_TENSORRT_DIVERSE_GUARD"
