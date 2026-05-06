from __future__ import annotations

import pytest

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.workers import WorkerPool


def test_unimplemented_tensorrt_worker_fails_clearly() -> None:
    task = TaskConfig.from_dict(
        {
            "name": "detector_trt",
            "model_path": "models/detector.onnx",
            "engine_path": "models/detector.plan",
            "priority": 100,
            "target_fps": 15,
            "latency_budget_ms": 80,
            "queue_size": 4,
            "worker": "tensorrt",
        }
    )
    frame = FrameEnvelope(
        frame_id="detector_trt-1",
        task_name="detector_trt",
        sequence=1,
        created_at_ms=0.0,
        deadline_at_ms=80.0,
    )

    with pytest.raises(NotImplementedError, match="not implemented yet"):
        WorkerPool().run(task, frame)
