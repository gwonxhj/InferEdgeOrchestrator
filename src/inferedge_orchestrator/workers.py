from __future__ import annotations

import time
from dataclasses import dataclass

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope


@dataclass(frozen=True)
class WorkerResult:
    task_name: str
    frame_id: str
    latency_ms: float
    output: dict[str, object]


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
