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


class _FakeTensorMode:
    INPUT = "TensorIOMode.INPUT"
    OUTPUT = "TensorIOMode.OUTPUT"


class _FakeTensorDType:
    FLOAT = "DataType.FLOAT"


class _FakeTensorEngine:
    def __init__(self, *, context: object | None = None) -> None:
        self.num_io_tensors = 2
        self.context = object() if context is None else context
        self.tensors = {
            "input": (_FakeTensorMode.INPUT, _FakeTensorDType.FLOAT, (1, 2)),
            "output": (_FakeTensorMode.OUTPUT, _FakeTensorDType.FLOAT, (1, 2)),
        }

    def create_execution_context(self) -> object:
        return self.context

    def get_tensor_name(self, index: int) -> str:
        return ["input", "output"][index]

    def get_tensor_mode(self, name: str) -> str:
        return self.tensors[name][0]

    def get_tensor_dtype(self, name: str) -> str:
        return self.tensors[name][1]

    def get_tensor_shape(self, name: str) -> tuple[int, int]:
        return self.tensors[name][2]


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
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            assert engine_bytes == b"serialized engine"
            return _FakeTensorEngine()

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    with pytest.raises(NotImplementedError, match="tensor metadata.*buffer binding"):
        WorkerPool().run(task, _frame())


def test_tensorrt_worker_reports_deserialization_failure(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"invalid engine")
    task = _tensorrt_task(str(engine_path))

    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> None:
            assert engine_bytes == b"invalid engine"
            return None

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    with pytest.raises(RuntimeError, match="failed to deserialize engine"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_caches_deserialized_engines(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    calls = {"deserialize": 0, "context": 0}

    class FakeTensorEngine(_FakeTensorEngine):
        def create_execution_context(self) -> object:
            calls["context"] += 1
            return object()

    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            calls["deserialize"] += 1
            return FakeTensorEngine()

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    worker = TensorRtWorker()
    for _ in range(2):
        with pytest.raises(NotImplementedError, match="inference execution"):
            worker.run(task, _frame())

    assert calls["deserialize"] == 1
    assert calls["context"] == 1


def test_tensorrt_worker_reports_context_creation_failure(
    tmp_path, monkeypatch
) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))

    class FakeEngine:
        def create_execution_context(self) -> None:
            return None

    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            return FakeEngine()

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    with pytest.raises(RuntimeError, match="failed to create execution context"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_records_io_tensor_metadata(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))

    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            return _FakeTensorEngine()

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    worker = TensorRtWorker()
    with pytest.raises(NotImplementedError, match="buffer binding"):
        worker.run(task, _frame())

    metadata = worker._engine_metadata[str(engine_path)]
    assert metadata["io_tensors"] == [
        {
            "index": 0,
            "name": "input",
            "mode": "INPUT",
            "dtype": "FLOAT",
            "shape": [1, 2],
        },
        {
            "index": 1,
            "name": "output",
            "mode": "OUTPUT",
            "dtype": "FLOAT",
            "shape": [1, 2],
        },
    ]


def test_tensorrt_worker_requires_input_and_output_tensors(
    tmp_path, monkeypatch
) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))

    class OutputOnlyEngine(_FakeTensorEngine):
        def __init__(self) -> None:
            self.num_io_tensors = 1
            self.context = object()
            self.tensors = {
                "output": (_FakeTensorMode.OUTPUT, _FakeTensorDType.FLOAT, (1, 2)),
            }

        def get_tensor_name(self, index: int) -> str:
            return "output"

    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            return OutputOnlyEngine()

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )

    with pytest.raises(RuntimeError, match="no input tensors"):
        TensorRtWorker().run(task, _frame())
