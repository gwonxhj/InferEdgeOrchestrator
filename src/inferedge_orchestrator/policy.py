from __future__ import annotations

from dataclasses import dataclass

from inferedge_orchestrator.config import TaskConfig, sorted_tasks_by_priority
from inferedge_orchestrator.task_queue import BoundedTaskQueues, DropRecord


@dataclass(frozen=True)
class PolicyDecision:
    event: str
    reason: str
    protected_task: str | None
    limited_task: str
    dropped_frames: int


class LoadSheddingPolicy:
    def __init__(self, tasks: tuple[TaskConfig, ...], *, backlog_threshold: int) -> None:
        self._tasks = {task.name: task for task in tasks}
        self._tasks_low_first = sorted(tasks, key=lambda task: (task.priority, task.name))
        self._tasks_high_first = sorted_tasks_by_priority(tasks)
        self._backlog_threshold = backlog_threshold

    def apply(self, queues: BoundedTaskQueues) -> tuple[list[DropRecord], list[PolicyDecision]]:
        if queues.total_backlog() <= self._backlog_threshold:
            return [], []

        protected_task = self._highest_priority_backlogged_task(queues)
        drops: list[DropRecord] = []
        decisions: list[PolicyDecision] = []

        for task in self._tasks_low_first:
            if queues.total_backlog() <= self._backlog_threshold:
                break
            if protected_task is not None and task.name == protected_task:
                continue
            dropped = queues.drop_oldest(
                task.name,
                reason="load_shedding_backlog_threshold_exceeded",
            )
            if dropped is None:
                continue
            drops.append(dropped)
            decisions.append(
                PolicyDecision(
                    event="load_shedding",
                    reason="queue_backlog_threshold_exceeded",
                    protected_task=protected_task,
                    limited_task=task.name,
                    dropped_frames=1,
                )
            )

        return drops, decisions

    def _highest_priority_backlogged_task(self, queues: BoundedTaskQueues) -> str | None:
        for task in self._tasks_high_first:
            if queues.backlog(task.name) > 0:
                return task.name
        return None
