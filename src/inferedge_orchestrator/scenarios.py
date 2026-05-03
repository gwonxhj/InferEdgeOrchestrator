from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig, sorted_tasks_by_priority
from inferedge_orchestrator.frames import DummyFrameSource, FrameEnvelope
from inferedge_orchestrator.policy import LoadSheddingPolicy, PolicyDecision
from inferedge_orchestrator.scheduler import PriorityScheduler
from inferedge_orchestrator.task_queue import BoundedTaskQueues, DropRecord


@dataclass(frozen=True)
class ExecutionRecord:
    task_name: str
    frame_id: str
    worker_latency_ms: float
    end_to_end_latency_ms: float


def run_overload_comparison(
    config: OrchestratorConfig,
    *,
    frames: int,
    frame_interval_ms: float = 10.0,
) -> dict[str, Any]:
    baseline_records = _run_fifo_baseline(
        config.tasks,
        frames=frames,
        frame_interval_ms=frame_interval_ms,
    )
    scheduled_records, scheduled_drops, policy_decisions = _run_scheduled_policy(
        config,
        frames=frames,
        frame_interval_ms=frame_interval_ms,
    )
    protected_task = sorted_tasks_by_priority(config.tasks)[0].name
    baseline_summary = _summarize(config.tasks, baseline_records, [])
    scheduled_summary = _summarize(config.tasks, scheduled_records, scheduled_drops)
    baseline_p95 = baseline_summary["tasks"][protected_task]["p95_end_to_end_latency_ms"]
    scheduled_p95 = scheduled_summary["tasks"][protected_task]["p95_end_to_end_latency_ms"]
    improvement = None
    if baseline_p95 is not None and scheduled_p95 is not None:
        improvement = round(baseline_p95 - scheduled_p95, 3)

    return {
        "scenario": {
            "name": config.name,
            "frames": frames,
            "frame_interval_ms": frame_interval_ms,
            "protected_task": protected_task,
        },
        "baseline": baseline_summary,
        "scheduled": {
            **scheduled_summary,
            "overload_events": [_policy_to_dict(decision) for decision in policy_decisions],
        },
        "effect": {
            "protected_task": protected_task,
            "baseline_p95_end_to_end_latency_ms": baseline_p95,
            "scheduled_p95_end_to_end_latency_ms": scheduled_p95,
            "p95_end_to_end_improvement_ms": improvement,
            "low_priority_drops": sum(
                task["dropped"] for name, task in scheduled_summary["tasks"].items()
                if name != protected_task
            ),
        },
    }


def write_overload_comparison(
    config: OrchestratorConfig,
    *,
    output: str | Path,
    frames: int,
    frame_interval_ms: float = 10.0,
) -> dict[str, Any]:
    report = run_overload_comparison(
        config,
        frames=frames,
        frame_interval_ms=frame_interval_ms,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _run_fifo_baseline(
    tasks: tuple[TaskConfig, ...],
    *,
    frames: int,
    frame_interval_ms: float,
) -> list[ExecutionRecord]:
    source = DummyFrameSource()
    arrivals: list[FrameEnvelope] = []
    for cycle in range(frames):
        now_ms = cycle * frame_interval_ms
        arrivals.extend(source.frames_for_cycle(tasks, cycle=cycle, now_ms=now_ms))

    records: list[ExecutionRecord] = []
    worker_available_ms = 0.0
    task_map = {task.name: task for task in tasks}
    for frame in arrivals:
        task = task_map[frame.task_name]
        started_ms = max(worker_available_ms, frame.created_at_ms)
        finished_ms = started_ms + task.simulated_latency_ms
        worker_available_ms = finished_ms
        records.append(
            ExecutionRecord(
                task_name=task.name,
                frame_id=frame.frame_id,
                worker_latency_ms=task.simulated_latency_ms,
                end_to_end_latency_ms=finished_ms - frame.created_at_ms,
            )
        )
    return records


def _run_scheduled_policy(
    config: OrchestratorConfig,
    *,
    frames: int,
    frame_interval_ms: float,
) -> tuple[list[ExecutionRecord], list[DropRecord], list[PolicyDecision]]:
    source = DummyFrameSource()
    queues = BoundedTaskQueues(config.tasks)
    scheduler = PriorityScheduler(config.tasks)
    policy = LoadSheddingPolicy(
        config.tasks,
        backlog_threshold=config.overload_backlog_threshold,
    )
    drops: list[DropRecord] = []
    policy_decisions: list[PolicyDecision] = []
    for cycle in range(frames):
        now_ms = cycle * frame_interval_ms
        for frame in source.frames_for_cycle(config.tasks, cycle=cycle, now_ms=now_ms):
            enqueue_result = queues.enqueue(frame)
            if enqueue_result.dropped is not None:
                drops.append(enqueue_result.dropped)
        policy_drops, decisions = policy.apply(queues)
        drops.extend(policy_drops)
        policy_decisions.extend(decisions)

    records: list[ExecutionRecord] = []
    worker_available_ms = 0.0
    task_map = config.task_map()
    while queues.total_backlog() > 0:
        decision = scheduler.choose_next(queues)
        if decision is None:
            break
        frame = queues.pop(decision.task_name)
        if frame is None:
            break
        task = task_map[decision.task_name]
        started_ms = max(worker_available_ms, frame.created_at_ms)
        finished_ms = started_ms + task.simulated_latency_ms
        worker_available_ms = finished_ms
        records.append(
            ExecutionRecord(
                task_name=task.name,
                frame_id=frame.frame_id,
                worker_latency_ms=task.simulated_latency_ms,
                end_to_end_latency_ms=finished_ms - frame.created_at_ms,
            )
        )
    return records, drops, policy_decisions


def _summarize(
    tasks: tuple[TaskConfig, ...],
    records: list[ExecutionRecord],
    drops: list[DropRecord],
) -> dict[str, Any]:
    task_records = {task.name: [] for task in tasks}
    task_drops = {task.name: 0 for task in tasks}
    for record in records:
        task_records[record.task_name].append(record)
    for drop in drops:
        task_drops[drop.task_name] += 1

    return {
        "tasks": {
            task.name: {
                "executed": len(task_records[task.name]),
                "dropped": task_drops[task.name],
                "mean_worker_latency_ms": _mean(
                    [record.worker_latency_ms for record in task_records[task.name]]
                ),
                "p95_end_to_end_latency_ms": _p95(
                    [record.end_to_end_latency_ms for record in task_records[task.name]]
                ),
            }
            for task in tasks
        }
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 3)


def _policy_to_dict(decision: PolicyDecision) -> dict[str, object]:
    return {
        "event": decision.event,
        "reason": decision.reason,
        "protected_task": decision.protected_task,
        "limited_task": decision.limited_task,
        "dropped_frames": decision.dropped_frames,
    }
