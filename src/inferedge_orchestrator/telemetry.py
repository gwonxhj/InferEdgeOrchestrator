from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.policy import PolicyDecision
from inferedge_orchestrator.scheduler import ScheduleDecision
from inferedge_orchestrator.task_queue import DropRecord
from inferedge_orchestrator.workers import WorkerResult


@dataclass
class TaskTelemetry:
    executed: int = 0
    dropped: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    max_queue_backlog: int = 0

    def mean_latency_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        return sum(self.latencies_ms) / len(self.latencies_ms)

    def p95_latency_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index]


class TelemetryCollector:
    def __init__(self, tasks: tuple[TaskConfig, ...], *, run_name: str) -> None:
        self.run_name = run_name
        self.tasks: dict[str, TaskTelemetry] = {
            task.name: TaskTelemetry() for task in tasks
        }
        self.schedule_decisions: list[dict[str, Any]] = []
        self.policy_decisions: list[dict[str, Any]] = []
        self.overload_events: list[dict[str, Any]] = []
        self.drop_events: list[dict[str, Any]] = []

    def record_backlog(self, backlog: dict[str, int]) -> None:
        for task_name, value in backlog.items():
            self.tasks[task_name].max_queue_backlog = max(
                self.tasks[task_name].max_queue_backlog,
                value,
            )

    def record_drop(self, drop: DropRecord) -> None:
        self.tasks[drop.task_name].dropped += 1
        self.drop_events.append(
            {
                "task": drop.task_name,
                "frame_id": drop.frame_id,
                "reason": drop.reason,
            }
        )

    def record_schedule(self, decision: ScheduleDecision) -> None:
        self.schedule_decisions.append(
            {"task": decision.task_name, "reason": decision.reason}
        )

    def record_execution(self, result: WorkerResult, *, backlog_after: int) -> None:
        task = self.tasks[result.task_name]
        task.executed += 1
        task.latencies_ms.append(result.latency_ms)
        task.max_queue_backlog = max(task.max_queue_backlog, backlog_after)

    def record_policy_decision(self, decision: PolicyDecision) -> None:
        event = {
            "event": decision.event,
            "reason": decision.reason,
            "protected_task": decision.protected_task,
            "limited_task": decision.limited_task,
            "dropped_frames": decision.dropped_frames,
        }
        self.policy_decisions.append(event)
        if decision.event == "load_shedding":
            self.overload_events.append(event)

    def to_report(self) -> dict[str, Any]:
        return {
            "run": {"name": self.run_name},
            "tasks": {
                name: {
                    "executed": task.executed,
                    "dropped": task.dropped,
                    "mean_latency_ms": _rounded(task.mean_latency_ms()),
                    "p95_latency_ms": _rounded(task.p95_latency_ms()),
                    "max_queue_backlog": task.max_queue_backlog,
                }
                for name, task in self.tasks.items()
            },
            "overload_events": self.overload_events,
            "policy_decisions": self.policy_decisions,
            "drop_events": self.drop_events,
            "schedule_decisions": self.schedule_decisions,
        }

    def write_json(self, path: str | Path) -> None:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(self.to_report(), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)
