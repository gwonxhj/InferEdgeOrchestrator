from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
        options = task.worker_options or {}
        if options.get("implementation") == "local_profile_adapter":
            return self._run_local_profile(task, frame, options)

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

    def _run_local_profile(
        self,
        task: TaskConfig,
        frame: FrameEnvelope,
        options: dict[str, object],
    ) -> WorkerResult:
        started = time.perf_counter()
        workload_type = str(options.get("workload_type", "utility"))
        work_units = _profile_work_units(options, workload_type)
        digest, profile = _profile_workload(
            workload_type=workload_type,
            task=task,
            frame=frame,
            work_units=work_units,
            options=options,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        return WorkerResult(
            task_name=task.name,
            frame_id=frame.frame_id,
            latency_ms=latency_ms,
            output={
                "worker": "dummy",
                "implementation": "local_profile_adapter",
                "profile_adapter": "local_cpu_profile",
                "workload_type": workload_type,
                "runtime_loop": options.get("runtime_loop"),
                "ingress_profile": options.get("ingress_profile"),
                "preferred_device": options.get("preferred_device"),
                "profile_work_units": work_units,
                "profile_elapsed_ms": round(latency_ms, 3),
                "profile_digest": digest,
                **profile,
            },
        )


def _profile_work_units(options: dict[str, object], workload_type: str) -> int:
    raw_value = options.get("profile_work_units")
    if raw_value is not None:
        return max(1, int(raw_value))
    defaults = {
        "realtime_vision": 18_000,
        "voice_command": 12_000,
        "telemetry_monitor": 4_000,
    }
    return defaults.get(workload_type, 6_000)


def _profile_workload(
    *,
    workload_type: str,
    task: TaskConfig,
    frame: FrameEnvelope,
    work_units: int,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    if workload_type == "realtime_vision":
        return _profile_vision(task, frame, work_units, options)
    if workload_type == "voice_command":
        return _profile_voice(task, frame, work_units, options)
    if workload_type == "telemetry_monitor":
        return _profile_safety_monitor(task, frame, work_units, options)
    return _profile_utility(task, frame, work_units, options)


def _profile_vision(
    task: TaskConfig,
    frame: FrameEnvelope,
    work_units: int,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    file_profile, sample = _vision_file_sample(frame, options)
    accumulator = frame.sequence + len(task.name) + sum(sample[:128])
    bright_pixels = 0
    edge_votes = 0
    sample_size = len(sample)
    for index in range(work_units):
        if sample_size:
            pixel = sample[index % sample_size]
            neighbor = sample[(index + 1) % sample_size]
        else:
            pixel = (index * 37 + frame.sequence * 17 + accumulator) & 0xFF
            neighbor = ((index + 1) * 29 + frame.sequence * 11) & 0xFF
        bright_pixels += 1 if pixel > 180 else 0
        edge_votes += 1 if abs(pixel - neighbor) > 48 else 0
        accumulator = ((accumulator << 5) ^ pixel ^ neighbor ^ index) & 0xFFFFFFFF
    detections = max(1, (edge_votes // max(1, work_units // 16)) % 24)
    digest_seed = file_profile.get("input_digest", "synthetic")
    digest = hashlib.sha1(
        f"vision:{digest_seed}:{accumulator}:{edge_votes}".encode()
    ).hexdigest()[:12]
    return digest, {
        "profile_kind": "vision_frame_loop",
        "frame_source": _payload_value(frame, "source", "dummy"),
        "estimated_detections": detections,
        "bright_pixel_ratio": round(bright_pixels / work_units, 4),
        "edge_vote_ratio": round(edge_votes / work_units, 4),
        "stale_frame_policy": task.drop_policy,
        "contention_signal": (
            "vision_file_cpu_profile" if file_profile else "frame_queue_cpu_profile"
        ),
        **file_profile,
    }


def _vision_file_sample(
    frame: FrameEnvelope,
    options: dict[str, object],
) -> tuple[dict[str, object], bytes]:
    source = _payload_value(frame, "source", "dummy")
    path_value = _payload_value(frame, "path", None)
    if source not in {"image", "video"} or path_value is None:
        return {}, b""

    path = Path(str(path_value))
    if not path.exists():
        raise FileNotFoundError(f"vision input path does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"vision input path is not a file: {path}")

    sample_limit = _positive_int(options.get("profile_sample_bytes"), default=4096)
    with path.open("rb") as handle:
        sample = handle.read(sample_limit)

    size = path.stat().st_size
    digest = hashlib.sha1(sample).hexdigest()[:12] if sample else "empty"
    return {
        "producer_source": f"{source}_file",
        "input_path": str(path),
        "input_bytes": size,
        "sampled_bytes": len(sample),
        "input_digest": digest,
        "byte_mean": _byte_mean(sample),
        "byte_stddev": _byte_stddev(sample),
    }, sample


def _positive_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    return max(1, int(value))


def _byte_mean(sample: bytes) -> float:
    if not sample:
        return 0.0
    return round(sum(sample) / len(sample), 3)


def _byte_stddev(sample: bytes) -> float:
    if not sample:
        return 0.0
    mean = sum(sample) / len(sample)
    variance = sum((value - mean) ** 2 for value in sample) / len(sample)
    return round(variance**0.5, 3)


def _profile_voice(
    task: TaskConfig,
    frame: FrameEnvelope,
    work_units: int,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    command, ingress_profile = _voice_ingress_profile(frame, options)
    tokens = command.split()
    digest_seed = ingress_profile.get("request_digest", command)
    digest_bytes = f"{task.name}:{frame.sequence}:{digest_seed}".encode()
    for index in range(work_units):
        digest_bytes = hashlib.blake2b(
            digest_bytes + str(index % max(1, len(tokens))).encode(),
            digest_size=16,
        ).digest()
    digest = digest_bytes.hex()[:12]
    return digest, {
        "profile_kind": "voice_command_burst",
        "token_count": len(tokens),
        "request_count": int(ingress_profile.get("ingress_request_count", 1)),
        "burst_profile": options.get("expected_runtime_mode", "burst"),
        "contention_signal": (
            "fastapi_request_cpu_profile"
            if ingress_profile
            else "cpu_text_command_profile"
        ),
        **ingress_profile,
    }


def _voice_ingress_profile(
    frame: FrameEnvelope,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    path_value = options.get("ingress_payload_path") or options.get(
        "request_payload_path"
    )
    if path_value is None:
        command = str(
            options.get("sample_command", "inspect queue backlog and summarize status")
        )
        return command, {}

    path = Path(str(path_value))
    if not path.exists():
        raise FileNotFoundError(f"voice ingress payload path does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"voice ingress payload path is not a file: {path}")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not loaded:
        raise ValueError("voice ingress payload must be a non-empty list")
    if not all(isinstance(request, dict) for request in loaded):
        raise ValueError("voice ingress payload entries must be objects")

    request_count = min(
        len(loaded),
        _positive_int(options.get("profile_request_count"), default=1),
    )
    start = frame.sequence % len(loaded)
    selected = [loaded[(start + offset) % len(loaded)] for offset in range(request_count)]
    commands = [_request_command(request) for request in selected]
    command = " ".join(commands)
    serialized = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(serialized.encode()).hexdigest()[:12]
    return command, {
        "producer_source": "fastapi_request_fixture",
        "ingress_payload_path": str(path),
        "available_request_count": len(loaded),
        "ingress_request_count": len(selected),
        "selected_request_ids": [
            str(request.get("request_id", "")) for request in selected
        ],
        "selected_routes": [
            str(request.get("path", "/agent/command")) for request in selected
        ],
        "selected_methods": [
            str(request.get("method", "POST")) for request in selected
        ],
        "command_char_count": len(command),
        "request_digest": digest,
    }


def _request_command(request: dict[str, object]) -> str:
    for key in ("command", "text", "prompt"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(request, sort_keys=True)


def _profile_safety_monitor(
    task: TaskConfig,
    frame: FrameEnvelope,
    work_units: int,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    risk_score = 0
    for index in range(work_units):
        risk_score = (risk_score + ((index * 13 + frame.sequence * 7) % 97)) % 10_000
    normalized = risk_score / 10_000
    digest = hashlib.sha1(f"monitor:{task.name}:{frame.sequence}:{risk_score}".encode()).hexdigest()[:12]
    return digest, {
        "profile_kind": "safety_monitor_loop",
        "sampled_metrics": ["queue_depth", "deadline_miss", "fallback_count"],
        "runtime_degradation_score": round(normalized, 4),
        "fallback_watch_enabled": bool(task.fallback_policy),
        "contention_signal": "telemetry_monitor_profile",
    }


def _profile_utility(
    task: TaskConfig,
    frame: FrameEnvelope,
    work_units: int,
    options: dict[str, object],
) -> tuple[str, dict[str, object]]:
    accumulator = 0
    for index in range(work_units):
        accumulator ^= (index + frame.sequence + len(task.name)) & 0xFFFF
    digest = hashlib.sha1(f"utility:{accumulator}".encode()).hexdigest()[:12]
    return digest, {
        "profile_kind": "utility_loop",
        "contention_signal": "generic_local_profile",
    }


def _payload_value(frame: FrameEnvelope, key: str, default: object) -> object:
    if isinstance(frame.payload, dict):
        return frame.payload.get(key, default)
    return default


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
