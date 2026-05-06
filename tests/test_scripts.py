from __future__ import annotations

import stat
from pathlib import Path


def test_jetson_tensorrt_smoke_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT smoke script should be executable"
    assert "configs/jetson_tensorrt_smoke.json" in text
    assert "ENGINE_PATH" in text
    assert "DEPENDENCY_PATH" in text
    assert "VALIDATION_PATH" in text
    assert "RUNTIME_TELEMETRY_PATH" in text
    assert "CAPTURE_TEGRASTATS" in text
    assert "/usr/src/tensorrt/bin/trtexec" in text
    assert "/usr/local/cuda/bin/nvcc" in text
    assert "PASS_TENSORRT_INFERENCE" in text
    assert "PASS_TENSORRT_TELEMETRY" in text
    assert "tensorrt_inputs" in text
    assert "output_preview" in text
    assert "result_events" in text
    assert "host/device buffer allocation" in text
    assert "tensor address binding" in text
    assert "TensorRT inference execution" in text


def test_jetson_tensorrt_contention_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt_contention.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT contention script should be executable"
    assert "configs/jetson_tensorrt_contention.json" in text
    assert "ENGINE_PATH" in text
    assert "TELEMETRY_PATH" in text
    assert "VALIDATION_PATH" in text
    assert "CAPTURE_TEGRASTATS" in text
    assert "PASS_TENSORRT_CONTENTION" in text
    assert "detector_trt" in text
    assert "classifier_trt" in text
    assert "overload_events" in text
    assert "limited_task" in text
    assert "backend" in text
