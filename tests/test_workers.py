from __future__ import annotations

import sys
import types

import pytest

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.workers import TensorRtWorker, WorkerPool


def _tensorrt_task(engine_path: str) -> TaskConfig:
    return TaskConfig.from_dict(
        {
            "name": "detector_trt",
            "model_path": "models/detector.onnx",
            "engine_path": engine_path,
            "priority": 100,
            "target_fps": 15,
            "latency_budget_ms": 80,
            "queue_size": 4,
            "worker": "tensorrt",
        }
    )


def _frame() -> FrameEnvelope:
    return FrameEnvelope(
        frame_id="detector_trt-1",
        task_name="detector_trt",
        sequence=1,
        created_at_ms=0.0,
        deadline_at_ms=80.0,
    )


def test_tensorrt_worker_checks_engine_path_exists(tmp_path) -> None:
    missing_engine = tmp_path / "missing.plan"
    task = _tensorrt_task(str(missing_engine))

    with pytest.raises(FileNotFoundError, match="engine_path does not exist"):
        WorkerPool().run(task, _frame())


def test_tensorrt_worker_reports_missing_python_bindings(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"not a real engine yet")
    task = _tensorrt_task(str(engine_path))
    monkeypatch.setitem(sys.modules, "tensorrt", None)

    with pytest.raises(RuntimeError, match="TensorRT Python bindings"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_stub_fails_after_import_guard(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"not a real engine yet")
    task = _tensorrt_task(str(engine_path))
    monkeypatch.setitem(sys.modules, "tensorrt", types.SimpleNamespace(__version__="10.3.0"))

    with pytest.raises(NotImplementedError, match="engine deserialization"):
        WorkerPool().run(task, _frame())
