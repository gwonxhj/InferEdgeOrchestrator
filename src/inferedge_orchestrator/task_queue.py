from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope


@dataclass(frozen=True)
class DropRecord:
    task_name: str
    frame_id: str
    reason: str


@dataclass(frozen=True)
class EnqueueResult:
    accepted: bool
    dropped: DropRecord | None = None


class BoundedTaskQueues:
    def __init__(self, tasks: tuple[TaskConfig, ...]) -> None:
        self._tasks = {task.name: task for task in tasks}
        self._queues: dict[str, deque[FrameEnvelope]] = {
            task.name: deque() for task in tasks
        }

    def enqueue(self, frame: FrameEnvelope) -> EnqueueResult:
        task = self._tasks[frame.task_name]
        queue = self._queues[frame.task_name]
        if len(queue) < task.queue_size:
            queue.append(frame)
            return EnqueueResult(accepted=True)

        if task.drop_policy == "drop_oldest":
            dropped = queue.popleft()
            queue.append(frame)
            return EnqueueResult(
                accepted=True,
                dropped=DropRecord(
                    task_name=task.name,
                    frame_id=dropped.frame_id,
                    reason="queue_overflow_drop_oldest",
                ),
            )

        return EnqueueResult(
            accepted=False,
            dropped=DropRecord(
                task_name=task.name,
                frame_id=frame.frame_id,
                reason="queue_overflow_drop_newest",
            ),
        )

    def pop(self, task_name: str) -> FrameEnvelope | None:
        queue = self._queues[task_name]
        if not queue:
            return None
        return queue.popleft()

    def drop_oldest(self, task_name: str, reason: str) -> DropRecord | None:
        queue = self._queues[task_name]
        if not queue:
            return None
        dropped = queue.popleft()
        return DropRecord(task_name=task_name, frame_id=dropped.frame_id, reason=reason)

    def peek(self, task_name: str) -> FrameEnvelope | None:
        queue = self._queues[task_name]
        if not queue:
            return None
        return queue[0]

    def backlog(self, task_name: str) -> int:
        return len(self._queues[task_name])

    def total_backlog(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    def non_empty_task_names(self) -> list[str]:
        return [name for name, queue in self._queues.items() if queue]

    def snapshot_backlog(self) -> dict[str, int]:
        return {name: len(queue) for name, queue in self._queues.items()}
