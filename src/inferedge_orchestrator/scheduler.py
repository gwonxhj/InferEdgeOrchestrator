from __future__ import annotations

from dataclasses import dataclass

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.task_queue import BoundedTaskQueues


@dataclass(frozen=True)
class ScheduleDecision:
    task_name: str
    reason: str


class PriorityScheduler:
    def __init__(self, tasks: tuple[TaskConfig, ...]) -> None:
        self._tasks = {task.name: task for task in tasks}

    def choose_next(self, queues: BoundedTaskQueues) -> ScheduleDecision | None:
        candidates: list[tuple[int, float, float, str]] = []
        for task_name in queues.non_empty_task_names():
            task = self._tasks[task_name]
            frame = queues.peek(task_name)
            if frame is None:
                continue
            candidates.append(
                (
                    -task.priority,
                    frame.deadline_at_ms,
                    frame.created_at_ms,
                    task.name,
                )
            )
        if not candidates:
            return None
        candidates.sort()
        _, _, _, task_name = candidates[0]
        return ScheduleDecision(task_name=task_name, reason="priority_deadline")
