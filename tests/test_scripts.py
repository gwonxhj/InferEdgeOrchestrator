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
    assert "CAPTURE_TEGRASTATS" in text
    assert "/usr/src/tensorrt/bin/trtexec" in text
    assert "/usr/local/cuda/bin/nvcc" in text
    assert "engine deserialization and inference execution are not implemented yet" in text
