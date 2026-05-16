from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import TaskConfig
from inferedge_orchestrator.frames import FrameEnvelope
from inferedge_orchestrator.monitor import ResourceSnapshot
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
    deadline_missed: int = 0
    fallback_used: int = 0

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
        self._task_config = {task.name: task for task in tasks}
        self.tasks: dict[str, TaskTelemetry] = {
            task.name: TaskTelemetry() for task in tasks
        }
        self.schedule_decisions: list[dict[str, Any]] = []
        self.policy_decisions: list[dict[str, Any]] = []
        self.overload_events: list[dict[str, Any]] = []
        self.drop_events: list[dict[str, Any]] = []
        self.result_events: list[dict[str, Any]] = []
        self.resource_snapshots: list[dict[str, object]] = []

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
                **self._agent_event_fields(drop.task_name),
                "frame_id": drop.frame_id,
                "reason": drop.reason,
            }
        )

    def record_schedule(self, decision: ScheduleDecision) -> None:
        self.schedule_decisions.append(
            {
                "task": decision.task_name,
                **self._agent_event_fields(decision.task_name),
                "reason": decision.reason,
            }
        )

    def record_execution(
        self,
        result: WorkerResult,
        *,
        frame: FrameEnvelope,
        backlog_after: int,
    ) -> None:
        task = self.tasks[result.task_name]
        task_config = self._task_config[result.task_name]
        deadline_missed = result.latency_ms > task_config.latency_budget_ms
        task.executed += 1
        task.latencies_ms.append(result.latency_ms)
        if deadline_missed:
            task.deadline_missed += 1
        task.max_queue_backlog = max(task.max_queue_backlog, backlog_after)
        self.result_events.append(
            {
                "task": result.task_name,
                **self._agent_event_fields(result.task_name),
                "frame_id": result.frame_id,
                "latency_ms": _rounded(result.latency_ms),
                "latency_budget_ms": _rounded(task_config.latency_budget_ms),
                "deadline_missed": deadline_missed,
                "queue_wait_ms": _rounded(max(0.0, frame.created_at_ms - frame.created_at_ms)),
                "fallback_used": False,
                "output": result.output,
            }
        )

    def record_policy_decision(self, decision: PolicyDecision) -> None:
        limited_task = self._task_config[decision.limited_task]
        fallback_used = decision.event == "load_shedding" and bool(
            limited_task.fallback_policy
        )
        if fallback_used:
            self.tasks[decision.limited_task].fallback_used += 1
        event = {
            "event": decision.event,
            "reason": decision.reason,
            "protected_task": decision.protected_task,
            "protected_agent_id": self._agent_id(decision.protected_task),
            "limited_task": decision.limited_task,
            **self._agent_event_fields(decision.limited_task),
            "dropped_frames": decision.dropped_frames,
            "fallback_used": fallback_used,
            "fallback_policy": limited_task.fallback_policy,
        }
        self.policy_decisions.append(event)
        if decision.event == "load_shedding":
            self.overload_events.append(event)

    def record_resource_snapshot(self, snapshot: ResourceSnapshot) -> None:
        self.resource_snapshots.append(snapshot.to_dict())

    def to_report(self) -> dict[str, Any]:
        agent_totals = self._agent_totals()
        return {
            "schema_version": "inferedge-orchestration-summary-v1",
            "run": {"name": self.run_name},
            "agent_runtime_summary": {
                "schema_version": "inferedge-orchestration-summary-v1",
                "source_contracts": {
                    "forge_agent_manifest": "inferedge-agent-manifest-v1",
                    "runtime_agent_result": "inferedge-runtime-agent-task-v1",
                },
                "agents": self._agent_summary(),
                "totals": agent_totals,
            },
            "tasks": {
                name: {
                    "agent": self._agent_task_summary(name),
                    "executed": task.executed,
                    "dropped": task.dropped,
                    "deadline_missed": task.deadline_missed,
                    "fallback_used": task.fallback_used,
                    "mean_latency_ms": _rounded(task.mean_latency_ms()),
                    "p95_latency_ms": _rounded(task.p95_latency_ms()),
                    "max_queue_backlog": task.max_queue_backlog,
                }
                for name, task in self.tasks.items()
            },
            "overload_events": self.overload_events,
            "policy_decisions": self.policy_decisions,
            "policy_decision_log": self.policy_decisions,
            "drop_events": self.drop_events,
            "result_events": self.result_events,
            "resource_snapshots": self.resource_snapshots,
            "schedule_decisions": self.schedule_decisions,
        }

    def write_json(self, path: str | Path) -> None:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(self.to_report(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _agent_task_summary(self, task_name: str) -> dict[str, object] | None:
        task = self._task_config[task_name]
        if task.agent_id is None:
            return None
        return {
            "agent_id": task.agent_id,
            "task_id": task.agent_task_id,
            "agent_type": task.agent_type,
            "priority": task.priority,
            "latency_budget_ms": _rounded(task.latency_budget_ms),
            "fallback_policy": task.fallback_policy,
            "agent_manifest_path": task.agent_manifest_path,
            "runtime_result_path": task.runtime_result_path,
            "telemetry_contract_version": task.telemetry_contract_version,
        }

    def _agent_summary(self) -> dict[str, dict[str, object]]:
        return {
            name: summary
            for name in self.tasks
            if (summary := self._agent_task_summary(name)) is not None
        }

    def _agent_totals(self) -> dict[str, int]:
        return {
            "executed_count": sum(task.executed for task in self.tasks.values()),
            "dropped_count": sum(task.dropped for task in self.tasks.values()),
            "deadline_missed_count": sum(
                task.deadline_missed for task in self.tasks.values()
            ),
            "fallback_count": sum(task.fallback_used for task in self.tasks.values()),
            "policy_decision_count": len(self.policy_decisions),
            "overload_event_count": len(self.overload_events),
        }

    def _agent_event_fields(self, task_name: str) -> dict[str, object]:
        task = self._task_config[task_name]
        return {
            "agent_id": task.agent_id,
            "task_id": task.agent_task_id,
            "agent_type": task.agent_type,
            "scheduled_priority": task.priority,
            "latency_budget_ms": _rounded(task.latency_budget_ms),
        }

    def _agent_id(self, task_name: str | None) -> str | None:
        if task_name is None:
            return None
        return self._task_config[task_name].agent_id


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)
