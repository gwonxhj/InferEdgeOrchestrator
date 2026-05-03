from __future__ import annotations

from dataclasses import dataclass

from inferedge_orchestrator.config import TaskConfig


@dataclass(frozen=True)
class FrameEnvelope:
    frame_id: str
    task_name: str
    sequence: int
    created_at_ms: float
    deadline_at_ms: float
    payload: object | None = None


class DummyFrameSource:
    """Generates deterministic frame envelopes for scheduler tests and demos."""

    def __init__(self) -> None:
        self._sequence = 0

    def frames_for_cycle(
        self,
        tasks: tuple[TaskConfig, ...],
        *,
        cycle: int,
        now_ms: float,
    ) -> list[FrameEnvelope]:
        frames: list[FrameEnvelope] = []
        for task in tasks:
            self._sequence += 1
            frames.append(
                FrameEnvelope(
                    frame_id=f"{task.name}-{cycle}-{self._sequence}",
                    task_name=task.name,
                    sequence=self._sequence,
                    created_at_ms=now_ms,
                    deadline_at_ms=now_ms + task.latency_budget_ms,
                    payload={"source": "dummy", "cycle": cycle},
                )
            )
        return frames
