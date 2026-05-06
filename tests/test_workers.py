from __future__ import annotations

import sys
import types

import numpy as np
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


def _frame(payload: dict[str, object] | None = None) -> FrameEnvelope:
    return FrameEnvelope(
        frame_id="detector_trt-1",
        task_name="detector_trt",
        sequence=1,
        created_at_ms=0.0,
        deadline_at_ms=80.0,
        payload=payload,
    )


class _FakeTensorMode:
    INPUT = "TensorIOMode.INPUT"
    OUTPUT = "TensorIOMode.OUTPUT"


class _FakeTensorDType:
    FLOAT = "DataType.FLOAT"


class _FakeTensorContext:
    def __init__(
        self,
        *,
        bind_success: bool = True,
        execute_success: bool = True,
        registry: dict[int, object] | None = None,
    ) -> None:
        self.bind_success = bind_success
        self.execute_success = execute_success
        self.registry = {} if registry is None else registry
        self.addresses: dict[str, int] = {}
        self.executions = 0

    def set_tensor_address(self, name: str, address: int) -> bool:
        self.addresses[name] = address
        return self.bind_success

    def execute_async_v3(self, stream_handle: int) -> bool:
        self.executions += 1
        if not self.execute_success:
            return False
        input_device = self.registry.get(self.addresses.get("input", -1))
        output_device = self.registry.get(self.addresses.get("output", -1))
        if input_device is not None and output_device is not None:
            output_device.data = np.array(input_device.data, copy=True)
        return True


class _FakeTensorEngine:
    def __init__(self, *, context: object | None = None) -> None:
        self.num_io_tensors = 2
        self.context = _FakeTensorContext() if context is None else context
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


def _install_fake_tensorrt(
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: object,
) -> None:
    class FakeLogger:
        WARNING = 1

        def __init__(self, severity: int) -> None:
            self.severity = severity

    class FakeRuntime:
        def __init__(self, logger: FakeLogger) -> None:
            self.logger = logger

        def deserialize_cuda_engine(self, engine_bytes: bytes) -> object:
            assert engine_bytes == b"serialized engine"
            return engine

    monkeypatch.setitem(
        sys.modules,
        "tensorrt",
        types.SimpleNamespace(__version__="10.3.0", Logger=FakeLogger, Runtime=FakeRuntime),
    )


def _install_fake_pycuda(
    monkeypatch: pytest.MonkeyPatch,
    *,
    registry: dict[int, object] | None = None,
) -> list[int]:
    allocations: list[int] = []
    devices = {} if registry is None else registry

    class FakeDeviceAllocation:
        def __init__(self, nbytes: int, address: int) -> None:
            self.nbytes = nbytes
            self.address = address
            self.data = None

        def __int__(self) -> int:
            return self.address

    class FakeStream:
        handle = 123

        def synchronize(self) -> None:
            pass

    pycuda = types.ModuleType("pycuda")
    autoinit = types.ModuleType("pycuda.autoinit")
    driver = types.ModuleType("pycuda.driver")

    def mem_alloc(nbytes: int) -> FakeDeviceAllocation:
        allocations.append(nbytes)
        allocation = FakeDeviceAllocation(nbytes, 1000 + len(allocations))
        devices[int(allocation)] = allocation
        return allocation

    def memcpy_htod_async(device: FakeDeviceAllocation, host: object, stream: FakeStream) -> None:
        device.data = np.array(host, copy=True)

    def memcpy_dtoh_async(host: object, device: FakeDeviceAllocation, stream: FakeStream) -> None:
        if device.data is None:
            host.fill(0)
        else:
            host[...] = device.data

    driver.mem_alloc = mem_alloc  # type: ignore[attr-defined]
    driver.memcpy_htod_async = memcpy_htod_async  # type: ignore[attr-defined]
    driver.memcpy_dtoh_async = memcpy_dtoh_async  # type: ignore[attr-defined]
    driver.Stream = FakeStream  # type: ignore[attr-defined]
    pycuda.autoinit = autoinit  # type: ignore[attr-defined]
    pycuda.driver = driver  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pycuda", pycuda)
    monkeypatch.setitem(sys.modules, "pycuda.autoinit", autoinit)
    monkeypatch.setitem(sys.modules, "pycuda.driver", driver)
    return allocations


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
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine())
    _install_fake_pycuda(monkeypatch)

    result = WorkerPool().run(task, _frame())

    assert result.output["worker"] == "tensorrt"
    assert result.output["output_shapes"] == {"output": [1, 2]}


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
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(RuntimeError, match="failed to deserialize engine"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_caches_deserialized_engines(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    calls = {"deserialize": 0, "context": 0}
    registry: dict[int, object] = {}
    context = _FakeTensorContext(registry=registry)

    class FakeTensorEngine(_FakeTensorEngine):
        def create_execution_context(self) -> object:
            calls["context"] += 1
            return context

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
    allocations = _install_fake_pycuda(monkeypatch, registry=registry)

    worker = TensorRtWorker()
    for _ in range(2):
        worker.run(task, _frame())

    assert calls["deserialize"] == 1
    assert calls["context"] == 1
    assert context.executions == 2
    assert allocations == [8, 8]
    assert context.addresses == {"input": 1001, "output": 1002}


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
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(RuntimeError, match="failed to create execution context"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_records_io_tensor_metadata(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine())
    _install_fake_pycuda(monkeypatch)

    worker = TensorRtWorker()
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
    assert metadata["buffers_bound"] is True
    assert metadata["io_buffers"] == [
        {
            "name": "input",
            "mode": "INPUT",
            "dtype": "FLOAT",
            "shape": [1, 2],
            "nbytes": 8,
        },
        {
            "name": "output",
            "mode": "OUTPUT",
            "dtype": "FLOAT",
            "shape": [1, 2],
            "nbytes": 8,
        },
    ]


def test_tensorrt_worker_executes_and_returns_output_metadata(
    tmp_path, monkeypatch
) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    registry: dict[int, object] = {}
    context = _FakeTensorContext(registry=registry)
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine(context=context))
    _install_fake_pycuda(monkeypatch, registry=registry)

    result = TensorRtWorker().run(
        task,
        _frame(payload={"tensorrt_inputs": {"input": [[3.0, 7.0]]}}),
    )

    assert result.task_name == "detector_trt"
    assert result.frame_id == "detector_trt-1"
    assert result.latency_ms >= 0.0
    assert result.output["worker"] == "tensorrt"
    assert result.output["backend"] == "tensorrt"
    assert result.output["engine_path"] == str(engine_path)
    assert result.output["input_shapes"] == {"input": [1, 2]}
    assert result.output["output_shapes"] == {"output": [1, 2]}
    assert result.output["output_dtypes"] == {"output": "FLOAT"}
    assert result.output["output_count"] == 1
    assert result.output["output_preview"] == {"output": [3.0, 7.0]}
    assert context.executions == 1


def test_tensorrt_worker_reports_input_shape_mismatch(
    tmp_path, monkeypatch
) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine())
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(ValueError, match="shape mismatch"):
        TensorRtWorker().run(
            task,
            _frame(payload={"tensorrt_inputs": {"input": [[1.0, 2.0, 3.0]]}}),
        )


def test_tensorrt_worker_reports_execution_failure(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    context = _FakeTensorContext(execute_success=False)
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine(context=context))
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(RuntimeError, match="inference execution failed"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_reports_missing_pycuda(tmp_path, monkeypatch) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    _install_fake_tensorrt(monkeypatch, engine=_FakeTensorEngine())
    monkeypatch.setitem(sys.modules, "pycuda", None)
    monkeypatch.setitem(sys.modules, "pycuda.autoinit", None)
    monkeypatch.setitem(sys.modules, "pycuda.driver", None)

    with pytest.raises(RuntimeError, match="requires PyCUDA"):
        TensorRtWorker().run(task, _frame())


def test_tensorrt_worker_reports_tensor_address_bind_failure(
    tmp_path, monkeypatch
) -> None:
    engine_path = tmp_path / "detector.plan"
    engine_path.write_bytes(b"serialized engine")
    task = _tensorrt_task(str(engine_path))
    context = _FakeTensorContext(bind_success=False)
    _install_fake_tensorrt(
        monkeypatch,
        engine=_FakeTensorEngine(context=context),
    )
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(RuntimeError, match="failed to bind tensor address: input"):
        TensorRtWorker().run(task, _frame())


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
    _install_fake_pycuda(monkeypatch)

    with pytest.raises(RuntimeError, match="no input tensors"):
        TensorRtWorker().run(task, _frame())
