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
    producer_sources: list[str] = field(default_factory=list)
    producer_event_count: int = 0

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
    def __init__(
        self,
        tasks: tuple[TaskConfig, ...],
        *,
        run_name: str,
        scenario_mode: str = "normal",
        frame_interval_ms: float = 1.0,
        overload_backlog_threshold: int = 0,
    ) -> None:
        self.run_name = run_name
        self.scenario_mode = scenario_mode
        self.frame_interval_ms = frame_interval_ms
        self.overload_backlog_threshold = overload_backlog_threshold
        self._task_config = {task.name: task for task in tasks}
        self.tasks: dict[str, TaskTelemetry] = {
            task.name: TaskTelemetry() for task in tasks
        }
        self.queue_depth_timeline: list[dict[str, Any]] = []
        self.latency_timeline: list[dict[str, Any]] = []
        self.schedule_decisions: list[dict[str, Any]] = []
        self.policy_decisions: list[dict[str, Any]] = []
        self.overload_events: list[dict[str, Any]] = []
        self.drop_events: list[dict[str, Any]] = []
        self.result_events: list[dict[str, Any]] = []
        self.runtime_event_timeline: list[dict[str, Any]] = []
        self.resource_snapshots: list[dict[str, object]] = []

    def record_backlog(
        self,
        backlog: dict[str, int],
        *,
        cycle: int | None = None,
        stage: str = "snapshot",
    ) -> None:
        for task_name, value in backlog.items():
            self.tasks[task_name].max_queue_backlog = max(
                self.tasks[task_name].max_queue_backlog,
                value,
            )
        total_queue_depth = sum(backlog.values())
        self.queue_depth_timeline.append(
            {
                "cycle": cycle,
                "stage": stage,
                "queue_depth": backlog,
                "total_queue_depth": total_queue_depth,
            }
        )
        self._record_runtime_event(
            "queue_snapshot",
            cycle=cycle,
            stage=stage,
            reason=_queue_state_reason(total_queue_depth),
            queue_depth=backlog,
            total_queue_depth=total_queue_depth,
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
        self._record_runtime_event(
            "drop",
            task=drop.task_name,
            **self._agent_event_fields(drop.task_name),
            frame_id=drop.frame_id,
            reason=drop.reason,
        )

    def record_schedule(self, decision: ScheduleDecision) -> None:
        self.schedule_decisions.append(
            {
                "task": decision.task_name,
                **self._agent_event_fields(decision.task_name),
                "reason": decision.reason,
            }
        )
        self._record_runtime_event(
            "schedule",
            task=decision.task_name,
            **self._agent_event_fields(decision.task_name),
            reason=decision.reason,
        )

    def record_execution(
        self,
        result: WorkerResult,
        *,
        frame: FrameEnvelope,
        backlog_after: int,
        execution_cycle: int | None = None,
    ) -> None:
        task = self.tasks[result.task_name]
        task_config = self._task_config[result.task_name]
        deadline_missed = result.latency_ms > task_config.latency_budget_ms
        task.executed += 1
        task.latencies_ms.append(result.latency_ms)
        if deadline_missed:
            task.deadline_missed += 1
        task.max_queue_backlog = max(task.max_queue_backlog, backlog_after)
        producer_context = _producer_context(result.output)
        producer_source = producer_context.get("producer_source")
        if isinstance(producer_source, str) and producer_source:
            task.producer_event_count += 1
            if producer_source not in task.producer_sources:
                task.producer_sources.append(producer_source)
        scheduler_delay_cycles = _scheduler_delay_cycles(frame, execution_cycle)
        queue_wait_ms = (
            _rounded(scheduler_delay_cycles * self.frame_interval_ms)
            if scheduler_delay_cycles is not None
            else None
        )
        execution_event = {
            "task": result.task_name,
            **self._agent_event_fields(result.task_name),
            "frame_id": result.frame_id,
            "latency_ms": _rounded(result.latency_ms),
            "latency_budget_ms": _rounded(task_config.latency_budget_ms),
            "deadline_missed": deadline_missed,
            "queue_wait_ms": queue_wait_ms,
            "scheduler_delay_cycles": scheduler_delay_cycles,
            "fallback_used": False,
            "producer_context": producer_context,
            "output": result.output,
        }
        self.result_events.append(execution_event)
        latency_event = {
            "task": result.task_name,
            **self._agent_event_fields(result.task_name),
            "frame_id": result.frame_id,
            "cycle": _frame_cycle(frame),
            "latency_ms": _rounded(result.latency_ms),
            "latency_budget_ms": _rounded(task_config.latency_budget_ms),
            "deadline_missed": deadline_missed,
            "queue_wait_ms": queue_wait_ms,
            "scheduler_delay_cycles": scheduler_delay_cycles,
            "backlog_after": backlog_after,
        }
        self.latency_timeline.append(latency_event)
        self._record_runtime_event(
            "execution",
            **{
                key: value
                for key, value in execution_event.items()
                if key != "output"
            },
            cycle=_frame_cycle(frame),
            reason=(
                "deadline_missed"
                if deadline_missed
                else "completed_within_latency_budget"
            ),
            worker=result.output.get("worker") if isinstance(result.output, dict) else None,
            backend=result.output.get("backend") if isinstance(result.output, dict) else None,
            queue_depth_after=backlog_after,
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
            "decision_reason": decision.reason,
            "protected_task": decision.protected_task,
            "protected_agent_id": self._agent_id(decision.protected_task),
            "limited_task": decision.limited_task,
            **self._agent_event_fields(decision.limited_task),
            "dropped_frames": decision.dropped_frames,
            "total_backlog_before": decision.total_backlog_before,
            "backlog_threshold": decision.backlog_threshold,
            "queue_depth_snapshot": decision.queue_depth_snapshot,
            "fallback_used": fallback_used,
            "fallback_policy": limited_task.fallback_policy,
        }
        self.policy_decisions.append(event)
        if decision.event == "load_shedding":
            self.overload_events.append(event)
        self._record_runtime_event("policy_decision", **event)

    def record_resource_snapshot(self, snapshot: ResourceSnapshot) -> None:
        snapshot_dict = snapshot.to_dict()
        self.resource_snapshots.append(snapshot_dict)
        self._record_runtime_event(
            "resource_snapshot",
            stage=snapshot_dict.get("stage"),
            reason="resource_health_sample",
            cpu_percent=snapshot_dict.get("cpu_percent"),
            memory_percent=snapshot_dict.get("memory_percent"),
            process_rss_mb=snapshot_dict.get("process_rss_mb"),
        )

    def to_report(self) -> dict[str, Any]:
        agent_totals = self._agent_totals()
        return {
            "schema_version": "inferedge-orchestration-summary-v1",
            "run": {
                "name": self.run_name,
                "scenario_mode": self.scenario_mode,
                "frame_interval_ms": _rounded(self.frame_interval_ms),
            },
            "agent_runtime_summary": {
                "schema_version": "inferedge-orchestration-summary-v1",
                "source_contracts": {
                    "forge_agent_manifest": "inferedge-agent-manifest-v1",
                    "runtime_agent_result": "inferedge-runtime-agent-task-v1",
                },
                "agents": self._agent_summary(),
                "totals": agent_totals,
            },
            "sustained_runtime_summary": self._sustained_runtime_summary(agent_totals),
            "queue_state_summary": self._queue_state_summary(),
            "worker_health_snapshot": self._worker_health_snapshot(),
            "runtime_event_summary": self._runtime_event_summary(),
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
            "queue_depth_timeline": self.queue_depth_timeline,
            "latency_timeline": self.latency_timeline,
            "policy_decisions": self.policy_decisions,
            "policy_decision_log": self.policy_decisions,
            "drop_events": self.drop_events,
            "result_events": self.result_events,
            "runtime_event_timeline": self.runtime_event_timeline,
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

    def _sustained_runtime_summary(self, agent_totals: dict[str, int]) -> dict[str, Any]:
        max_total_queue_depth = 0
        if self.queue_depth_timeline:
            max_total_queue_depth = max(
                int(sample["total_queue_depth"])
                for sample in self.queue_depth_timeline
            )
        return {
            "schema_version": "inferedge-orchestrator-sustained-summary-v1",
            "scenario_mode": self.scenario_mode,
            "queue_depth_sample_count": len(self.queue_depth_timeline),
            "latency_sample_count": len(self.latency_timeline),
            "max_total_queue_depth": max_total_queue_depth,
            "deadline_missed_count": agent_totals["deadline_missed_count"],
            "dropped_count": agent_totals["dropped_count"],
            "fallback_count": agent_totals["fallback_count"],
            "policy_decision_count": agent_totals["policy_decision_count"],
            "overload_event_count": agent_totals["overload_event_count"],
        }

    def _queue_state_summary(self) -> dict[str, Any]:
        final_queue_depth: dict[str, int] = {name: 0 for name in self.tasks}
        max_queue_depth_by_task: dict[str, int] = {name: 0 for name in self.tasks}
        total_depths: list[int] = []

        for sample in self.queue_depth_timeline:
            queue_depth = sample.get("queue_depth")
            if isinstance(queue_depth, dict):
                final_queue_depth = {
                    name: int(value)
                    for name, value in queue_depth.items()
                    if isinstance(value, int)
                }
                for name, value in final_queue_depth.items():
                    max_queue_depth_by_task[name] = max(
                        max_queue_depth_by_task.get(name, 0),
                        value,
                    )
            total_queue_depth = sample.get("total_queue_depth")
            if isinstance(total_queue_depth, int):
                total_depths.append(total_queue_depth)

        max_total_queue_depth = max(total_depths) if total_depths else 0
        average_total_queue_depth = (
            round(sum(total_depths) / len(total_depths), 3) if total_depths else 0.0
        )
        return {
            "schema_version": "inferedge-orchestrator-queue-state-v1",
            "sample_count": len(self.queue_depth_timeline),
            "overload_backlog_threshold": self._overload_backlog_threshold(),
            "max_total_queue_depth": max_total_queue_depth,
            "average_total_queue_depth": average_total_queue_depth,
            "final_queue_depth": final_queue_depth,
            "max_queue_depth_by_task": max_queue_depth_by_task,
            "device_local_task_count": sum(
                1
                for task in self._task_config.values()
                if bool((task.worker_options or {}).get("device_local_validation"))
            ),
            "device_local_tasks": [
                name
                for name, task in self._task_config.items()
                if bool((task.worker_options or {}).get("device_local_validation"))
            ],
            "queue_pressure_state": _queue_pressure_state(
                max_total_queue_depth,
                self._overload_backlog_threshold(),
            ),
        }

    def _worker_health_snapshot(self) -> dict[str, Any]:
        workers = {
            name: self._worker_health_for_task(name, telemetry)
            for name, telemetry in self.tasks.items()
        }
        return {
            "schema_version": "inferedge-orchestrator-worker-health-v1",
            "health_state_counts": _count_by_key(workers.values(), "health_state"),
            "degraded_workers": [
                name
                for name, worker in workers.items()
                if worker.get("health_state") == "degraded"
            ],
            "constrained_workers": [
                name
                for name, worker in workers.items()
                if worker.get("health_state") == "constrained"
            ],
            "workers": workers,
        }

    def _worker_health_for_task(
        self,
        task_name: str,
        telemetry: TaskTelemetry,
    ) -> dict[str, Any]:
        task_config = self._task_config[task_name]
        total_seen = telemetry.executed + telemetry.dropped
        health_state = _worker_health_state(telemetry)
        return {
            "task": task_name,
            **self._agent_event_fields(task_name),
            "worker": task_config.worker,
            "health_state": health_state,
            "health_reasons": _worker_health_reasons(
                telemetry,
                task_config.queue_size,
                health_state,
            ),
            "executed_count": telemetry.executed,
            "dropped_count": telemetry.dropped,
            "deadline_missed_count": telemetry.deadline_missed,
            "fallback_count": telemetry.fallback_used,
            "drop_rate": _ratio(telemetry.dropped, total_seen),
            "deadline_miss_rate": _ratio(telemetry.deadline_missed, telemetry.executed),
            "fallback_rate": _ratio(telemetry.fallback_used, total_seen),
            "mean_latency_ms": _rounded(telemetry.mean_latency_ms()),
            "p95_latency_ms": _rounded(telemetry.p95_latency_ms()),
            "latency_budget_ms": _rounded(task_config.latency_budget_ms),
            "max_queue_backlog": telemetry.max_queue_backlog,
            "queue_size": task_config.queue_size,
            "queue_pressure_ratio": _rounded(
                telemetry.max_queue_backlog / task_config.queue_size
            ),
            "device_local_validation": bool(
                (task_config.worker_options or {}).get("device_local_validation")
            ),
            "producer_stage": (task_config.worker_options or {}).get("producer_stage"),
            "producer_sources": list(telemetry.producer_sources),
            "producer_event_count": telemetry.producer_event_count,
            "workload_type": (task_config.worker_options or {}).get("workload_type"),
            "runtime_loop": (task_config.worker_options or {}).get("runtime_loop"),
            "ingress_profile": (task_config.worker_options or {}).get("ingress_profile"),
        }

    def _runtime_event_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        reason_counts: dict[str, int] = {}
        policy_reason_counts: dict[str, int] = {}
        drop_reason_counts: dict[str, int] = {}
        deadline_missed_count = 0
        fallback_decision_count = 0
        scheduler_delay_event_count = 0
        for event in self.runtime_event_timeline:
            event_type = event.get("event_type")
            if not isinstance(event_type, str):
                continue
            counts[event_type] = counts.get(event_type, 0) + 1
            reason = event.get("reason")
            if isinstance(reason, str):
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if event_type == "policy_decision":
                    policy_reason_counts[reason] = policy_reason_counts.get(reason, 0) + 1
                if event_type == "drop":
                    drop_reason_counts[reason] = drop_reason_counts.get(reason, 0) + 1
            if bool(event.get("deadline_missed")):
                deadline_missed_count += 1
            if bool(event.get("fallback_used")):
                fallback_decision_count += 1
            scheduler_delay_cycles = event.get("scheduler_delay_cycles")
            if isinstance(scheduler_delay_cycles, int) and scheduler_delay_cycles > 0:
                scheduler_delay_event_count += 1
        return {
            "schema_version": "inferedge-orchestrator-runtime-event-summary-v1",
            "event_count": len(self.runtime_event_timeline),
            "event_type_counts": counts,
            "reason_counts": reason_counts,
            "policy_decision_reason_counts": policy_reason_counts,
            "drop_reason_counts": drop_reason_counts,
            "deadline_missed_count": deadline_missed_count,
            "fallback_decision_count": fallback_decision_count,
            "scheduler_delay_event_count": scheduler_delay_event_count,
            "latest_event_index": (
                len(self.runtime_event_timeline) - 1
                if self.runtime_event_timeline
                else None
            ),
        }

    def _overload_backlog_threshold(self) -> int:
        return self.overload_backlog_threshold

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

    def _record_runtime_event(self, event_type: str, **fields: Any) -> None:
        self.runtime_event_timeline.append(
            {
                "event_index": len(self.runtime_event_timeline),
                "event_type": event_type,
                **fields,
            }
        )


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _frame_cycle(frame: FrameEnvelope) -> int | None:
    if isinstance(frame.payload, dict):
        cycle = frame.payload.get("cycle")
        if isinstance(cycle, int):
            return cycle
    return None


def _scheduler_delay_cycles(
    frame: FrameEnvelope,
    execution_cycle: int | None,
) -> int | None:
    created_cycle = _frame_cycle(frame)
    if created_cycle is None or execution_cycle is None:
        return None
    return max(0, execution_cycle - created_cycle)


def _queue_state_reason(total_queue_depth: int) -> str:
    if total_queue_depth <= 0:
        return "queue_empty"
    return "queue_depth_sampled"


def _queue_pressure_state(max_total_queue_depth: int, threshold: int) -> str:
    if threshold <= 0:
        return "unknown"
    if max_total_queue_depth > threshold:
        return "overloaded"
    if max_total_queue_depth >= max(1, math.ceil(threshold * 0.75)):
        return "elevated"
    return "nominal"


def _worker_health_state(telemetry: TaskTelemetry) -> str:
    if telemetry.fallback_used > 0 or telemetry.deadline_missed > 0:
        return "degraded"
    if telemetry.dropped > 0:
        return "constrained"
    if telemetry.executed > 0:
        return "healthy"
    return "idle"


def _worker_health_reasons(
    telemetry: TaskTelemetry,
    queue_size: int,
    health_state: str,
) -> list[str]:
    reasons: list[str] = []
    if telemetry.deadline_missed > 0:
        reasons.append("deadline_missed")
    if telemetry.fallback_used > 0:
        reasons.append("fallback_policy_used")
    if telemetry.dropped > 0:
        reasons.append("frames_dropped")
    if queue_size > 0 and telemetry.max_queue_backlog >= queue_size:
        reasons.append("queue_reached_capacity")
    if telemetry.executed == 0:
        reasons.append("no_worker_executions")
    if not reasons:
        reasons.append(f"{health_state}_without_runtime_risk")
    return reasons


def _count_by_key(
    items: Any,
    key: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if not isinstance(value, str):
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


def _producer_context(output: dict[str, object]) -> dict[str, object]:
    if not isinstance(output, dict):
        return {}
    keys = (
        "producer_source",
        "input_path",
        "ingress_payload_path",
        "resource_snapshot_path",
        "resource_snapshot_id",
        "input_digest",
        "request_digest",
        "resource_digest",
        "contention_signal",
        "profile_kind",
        "runtime_degradation_score",
        "resource_degradation_score",
    )
    return {key: output[key] for key in keys if key in output}
