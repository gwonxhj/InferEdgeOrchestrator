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
        self._engine_metadata: dict[str, dict[str, object]] = {}

    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        self._engine_for(task)
        raise NotImplementedError(
            "tensorrt worker deserialized the configured engine, but inference "
            "execution is not implemented yet"
        )

    def _engine_for(self, task: TaskConfig) -> object:
        if not task.engine_path:
            raise ValueError(f"{task.name}: tensorrt worker requires engine_path")
        engine_path = Path(task.engine_path)
        if not engine_path.exists():
            raise FileNotFoundError(
                f"{task.name}: TensorRT engine_path does not exist: {engine_path}"
            )
        resolved_engine_path = str(engine_path)
        if resolved_engine_path not in self._engines:
            trt = self._import_tensorrt()
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
            }
        return self._engines[resolved_engine_path]

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
