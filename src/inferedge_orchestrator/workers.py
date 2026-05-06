from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope


@dataclass(frozen=True)
class WorkerResult:
    task_name: str
    frame_id: str
    latency_ms: float
    output: dict[str, object]


class Worker(Protocol):
    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        ...


@dataclass(frozen=True)
class TensorRtBuffer:
    name: str
    mode: str
    dtype: str
    shape: tuple[int, ...]
    host: object
    device: object
    nbytes: int


class DummyWorker:
    def __init__(self, *, sleep: bool = False) -> None:
        self._sleep = sleep

    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        started = time.perf_counter()
        if self._sleep and task.simulated_latency_ms > 0:
            time.sleep(task.simulated_latency_ms / 1000.0)
            latency_ms = (time.perf_counter() - started) * 1000.0
        else:
            latency_ms = task.simulated_latency_ms
        return WorkerResult(
            task_name=task.name,
            frame_id=frame.frame_id,
            latency_ms=latency_ms,
            output={"worker": "dummy", "sequence": frame.sequence},
        )


class OnnxRuntimeWorker:
    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}

    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        started = time.perf_counter()
        session = self._session_for(task)
        inputs = session.get_inputs()
        if not inputs:
            raise RuntimeError(f"{task.name}: ONNX model has no inputs")
        feed = self._build_feed(inputs, frame)
        outputs = session.run(None, feed)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return WorkerResult(
            task_name=task.name,
            frame_id=frame.frame_id,
            latency_ms=latency_ms,
            output={
                "worker": "onnxruntime",
                "model_path": task.model_path,
                "output_count": len(outputs),
                "output_shapes": [list(output.shape) for output in outputs],
            },
        )

    def _session_for(self, task: TaskConfig):
        if not task.model_path:
            raise ValueError(f"{task.name}: onnxruntime worker requires model_path")
        model_path = str(Path(task.model_path))
        if model_path not in self._sessions:
            try:
                import onnxruntime as ort
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "onnxruntime worker requires the optional onnxruntime dependency. "
                    "Install inferedge-orchestrator[onnx]."
                ) from exc
            self._sessions[model_path] = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
        return self._sessions[model_path]

    def _build_feed(self, inputs: list[object], frame: FrameEnvelope) -> dict[str, object]:
        try:
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "onnxruntime worker requires numpy. Install inferedge-orchestrator[onnx]."
            ) from exc

        payload = frame.payload if isinstance(frame.payload, dict) else {}
        explicit_inputs = payload.get("onnx_inputs")
        if isinstance(explicit_inputs, dict):
            return {str(name): np.asarray(value) for name, value in explicit_inputs.items()}

        feed: dict[str, object] = {}
        for model_input in inputs:
            shape = _concrete_shape(model_input.shape)
            feed[model_input.name] = np.zeros(shape, dtype=np.float32)
        return feed


class TensorRtWorker:
    def __init__(self) -> None:
        self._engines: dict[str, object] = {}
        self._contexts: dict[str, object] = {}
        self._buffers: dict[str, list[TensorRtBuffer]] = {}
        self._engine_metadata: dict[str, dict[str, object]] = {}

    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        started = time.perf_counter()
        engine_path = self._resolved_engine_path(task)
        context = self._context_for(task)
        buffers = self._buffers_for(task)
        self._execute(task, frame, context, buffers)
        latency_ms = (time.perf_counter() - started) * 1000.0
        metadata = self._engine_metadata[engine_path]
        output_buffers = [buffer for buffer in buffers if buffer.mode == "OUTPUT"]
        input_buffers = [buffer for buffer in buffers if buffer.mode == "INPUT"]
        return WorkerResult(
            task_name=task.name,
            frame_id=frame.frame_id,
            latency_ms=latency_ms,
            output={
                "worker": "tensorrt",
                "backend": "tensorrt",
                "engine_path": engine_path,
                "tensorrt_version": metadata["tensorrt_version"],
                "engine_size_bytes": metadata["engine_size_bytes"],
                "input_shapes": {
                    buffer.name: list(buffer.shape) for buffer in input_buffers
                },
                "output_shapes": {
                    buffer.name: list(buffer.shape) for buffer in output_buffers
                },
                "output_dtypes": {
                    buffer.name: buffer.dtype for buffer in output_buffers
                },
                "output_count": len(output_buffers),
                "output_preview": {
                    buffer.name: _preview_array(buffer.host) for buffer in output_buffers
                },
            },
        )

    def _buffers_for(self, task: TaskConfig) -> list[TensorRtBuffer]:
        engine_path = self._resolved_engine_path(task)
        if engine_path not in self._buffers:
            context = self._context_for(task)
            metadata = self._engine_metadata[engine_path]
            buffers = self._allocate_and_bind_buffers(
                task,
                context,
                metadata["io_tensors"],
            )
            self._buffers[engine_path] = buffers
            metadata["buffers_bound"] = True
            metadata["io_buffers"] = [
                {
                    "name": buffer.name,
                    "mode": buffer.mode,
                    "dtype": buffer.dtype,
                    "shape": list(buffer.shape),
                    "nbytes": buffer.nbytes,
                }
                for buffer in buffers
            ]
        return self._buffers[engine_path]

    def _context_for(self, task: TaskConfig) -> object:
        engine_path = self._resolved_engine_path(task)
        if engine_path not in self._contexts:
            engine = self._engine_for(task)
            context = engine.create_execution_context()
            if context is None:
                raise RuntimeError(
                    f"{task.name}: TensorRT failed to create execution context: "
                    f"{engine_path}"
                )
            self._contexts[engine_path] = context
            self._engine_metadata[engine_path]["execution_context_created"] = True
            self._engine_metadata[engine_path]["io_tensors"] = (
                self._inspect_io_tensors(engine)
            )
        return self._contexts[engine_path]

    def _engine_for(self, task: TaskConfig) -> object:
        resolved_engine_path = self._resolved_engine_path(task)
        if resolved_engine_path not in self._engines:
            trt = self._import_tensorrt()
            self._cuda_driver()
            engine_path = Path(resolved_engine_path)
            engine_bytes = engine_path.read_bytes()
            logger = trt.Logger(getattr(trt.Logger, "WARNING", 1))
            runtime = trt.Runtime(logger)
            engine = runtime.deserialize_cuda_engine(engine_bytes)
            if engine is None:
                raise RuntimeError(
                    f"{task.name}: TensorRT failed to deserialize engine: {engine_path}"
                )
            self._engines[resolved_engine_path] = engine
            self._engine_metadata[resolved_engine_path] = {
                "engine_path": resolved_engine_path,
                "tensorrt_version": trt.__version__,
                "engine_deserialized": True,
                "engine_size_bytes": len(engine_bytes),
                "execution_context_created": False,
                "buffers_bound": False,
            }
        return self._engines[resolved_engine_path]

    def _resolved_engine_path(self, task: TaskConfig) -> str:
        if not task.engine_path:
            raise ValueError(f"{task.name}: tensorrt worker requires engine_path")
        engine_path = Path(task.engine_path)
        if not engine_path.exists():
            raise FileNotFoundError(
                f"{task.name}: TensorRT engine_path does not exist: {engine_path}"
            )
        return str(engine_path)

    def _inspect_io_tensors(self, engine: object) -> list[dict[str, object]]:
        if not hasattr(engine, "num_io_tensors"):
            raise RuntimeError(
                "tensorrt worker requires TensorRT name-based tensor APIs "
                "(num_io_tensors/get_tensor_name)."
            )

        tensor_count = int(engine.num_io_tensors)
        tensors: list[dict[str, object]] = []
        for index in range(tensor_count):
            name = str(engine.get_tensor_name(index))
            mode = engine.get_tensor_mode(name)
            dtype = engine.get_tensor_dtype(name)
            shape = engine.get_tensor_shape(name)
            tensors.append(
                {
                    "index": index,
                    "name": name,
                    "mode": _short_enum_name(mode),
                    "dtype": _short_enum_name(dtype),
                    "shape": [int(dimension) for dimension in shape],
                }
            )

        if not any(tensor["mode"] == "INPUT" for tensor in tensors):
            raise RuntimeError("tensorrt worker found no input tensors in engine")
        if not any(tensor["mode"] == "OUTPUT" for tensor in tensors):
            raise RuntimeError("tensorrt worker found no output tensors in engine")
        return tensors

    def _allocate_and_bind_buffers(
        self,
        task: TaskConfig,
        context: object,
        tensors: object,
    ) -> list[TensorRtBuffer]:
        try:
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "tensorrt worker requires numpy for TensorRT buffer allocation."
            ) from exc

        cuda = self._cuda_driver()

        if not hasattr(context, "set_tensor_address"):
            raise RuntimeError(
                "tensorrt worker requires TensorRT context.set_tensor_address."
            )

        buffers: list[TensorRtBuffer] = []
        for tensor in tensors:
            if not isinstance(tensor, dict):
                raise RuntimeError(f"{task.name}: invalid TensorRT tensor metadata")
            name = str(tensor["name"])
            mode = str(tensor["mode"])
            dtype_label = str(tensor["dtype"])
            shape = tuple(int(dimension) for dimension in tensor["shape"])
            dtype = _numpy_dtype_for(dtype_label, np)
            host = np.zeros(shape, dtype=dtype)
            nbytes = int(host.nbytes)
            device = cuda.mem_alloc(nbytes)
            if not context.set_tensor_address(name, int(device)):
                raise RuntimeError(
                    f"{task.name}: TensorRT failed to bind tensor address: {name}"
                )
            buffers.append(
                TensorRtBuffer(
                    name=name,
                    mode=mode,
                    dtype=dtype_label,
                    shape=shape,
                    host=host,
                    device=device,
                    nbytes=nbytes,
                )
            )
        return buffers

    def _execute(
        self,
        task: TaskConfig,
        frame: FrameEnvelope,
        context: object,
        buffers: list[TensorRtBuffer],
    ) -> None:
        try:
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "tensorrt worker requires numpy for TensorRT inference execution."
            ) from exc

        cuda = self._cuda_driver()
        if not hasattr(context, "execute_async_v3"):
            raise RuntimeError(
                "tensorrt worker requires TensorRT context.execute_async_v3."
            )

        stream = cuda.Stream()
        self._populate_inputs(task, frame, buffers, np)
        for buffer in buffers:
            if buffer.mode == "INPUT":
                cuda.memcpy_htod_async(buffer.device, buffer.host, stream)

        if not context.execute_async_v3(stream.handle):
            raise RuntimeError(f"{task.name}: TensorRT inference execution failed")

        for buffer in buffers:
            if buffer.mode == "OUTPUT":
                cuda.memcpy_dtoh_async(buffer.host, buffer.device, stream)
        stream.synchronize()

    def _populate_inputs(
        self,
        task: TaskConfig,
        frame: FrameEnvelope,
        buffers: list[TensorRtBuffer],
        np: object,
    ) -> None:
        payload = frame.payload if isinstance(frame.payload, dict) else {}
        explicit_inputs = payload.get("tensorrt_inputs")
        explicit_map = explicit_inputs if isinstance(explicit_inputs, dict) else {}
        for buffer in buffers:
            if buffer.mode != "INPUT":
                continue
            if buffer.name in explicit_map:
                value = np.asarray(explicit_map[buffer.name], dtype=buffer.host.dtype)
                if tuple(value.shape) != buffer.shape:
                    raise ValueError(
                        f"{task.name}: TensorRT input {buffer.name} shape mismatch: "
                        f"expected {list(buffer.shape)}, got {list(value.shape)}"
                    )
                buffer.host[...] = value
            else:
                buffer.host.fill(0)

    def _cuda_driver(self) -> object:
        try:
            import pycuda.autoinit  # noqa: F401
            import pycuda.driver as cuda
        except ImportError as exc:
            raise RuntimeError(
                "tensorrt worker requires PyCUDA for TensorRT buffer allocation "
                "and inference execution. Install PyCUDA on the target Jetson or "
                "run with a different worker."
            ) from exc
        return cuda

    def _import_tensorrt(self) -> object:
        try:
            import tensorrt as trt
        except ImportError as exc:
            raise RuntimeError(
                "tensorrt worker requires the optional TensorRT Python bindings. "
                "Install TensorRT on the target Jetson or run with a different worker."
            ) from exc
        return trt


class WorkerPool:
    def __init__(self, *, sleep_dummy: bool = False) -> None:
        self._workers: dict[str, Worker] = {
            "dummy": DummyWorker(sleep=sleep_dummy),
            "onnxruntime": OnnxRuntimeWorker(),
            "tensorrt": TensorRtWorker(),
        }

    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        return self._workers[task.worker].run(task, frame)


def _concrete_shape(shape: list[object]) -> tuple[int, ...]:
    concrete: list[int] = []
    for value in shape:
        if isinstance(value, int) and value > 0:
            concrete.append(value)
        else:
            concrete.append(1)
    return tuple(concrete)


def _short_enum_name(value: object) -> str:
    text = str(value)
    return text.rsplit(".", 1)[-1]


def _numpy_dtype_for(dtype: str, np: object) -> object:
    dtype_map = {
        "FLOAT": np.float32,
        "HALF": np.float16,
        "INT32": np.int32,
        "INT8": np.int8,
        "BOOL": np.bool_,
    }
    try:
        return dtype_map[dtype]
    except KeyError as exc:
        raise RuntimeError(f"unsupported TensorRT tensor dtype: {dtype}") from exc


def _preview_array(value: object, *, limit: int = 8) -> list[object]:
    try:
        flat = value.reshape(-1)
        return flat[:limit].tolist()
    except AttributeError:
        return []
