from __future__ import annotations

from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.frames import build_frame_source
from inferedge_orchestrator.monitor import ResourceMonitor
from inferedge_orchestrator.policy import LoadSheddingPolicy
from inferedge_orchestrator.scheduler import PriorityScheduler
from inferedge_orchestrator.task_queue import BoundedTaskQueues
from inferedge_orchestrator.telemetry import TelemetryCollector
from inferedge_orchestrator.workers import WorkerPool


class OrchestratorRuntime:
    def __init__(self, config: OrchestratorConfig, *, sleep_worker: bool = False) -> None:
        self.config = config
        self.task_map = config.task_map()
        self.queues = BoundedTaskQueues(config.tasks)
        self.source = build_frame_source(config)
        self.scheduler = PriorityScheduler(config.tasks)
        self.policy = LoadSheddingPolicy(
            config.tasks,
            backlog_threshold=config.overload_backlog_threshold,
        )
        self.worker = WorkerPool(sleep_dummy=sleep_worker)
        self.telemetry = TelemetryCollector(
            config.tasks,
            run_name=config.name,
            scenario_mode=config.scenario_mode,
            frame_interval_ms=config.frame_interval_ms,
        )
        self.monitor = ResourceMonitor()

    def run(self, *, frames: int, drain: bool = True) -> dict[str, object]:
        self.telemetry.record_resource_snapshot(self.monitor.capture(stage="start"))
        for cycle in range(frames):
            now_ms = float(cycle) * self.config.frame_interval_ms
            for frame in self.source.frames_for_cycle(
                self.config.tasks,
                cycle=cycle,
                now_ms=now_ms,
            ):
                result = self.queues.enqueue(frame)
                if result.dropped is not None:
                    self.telemetry.record_drop(result.dropped)
            self._record_backlog_and_shed(cycle=cycle, stage="cycle")
            self._execute_one()

        drain_cycle = frames
        if drain:
            while self.queues.total_backlog() > 0:
                self._record_backlog_and_shed(cycle=drain_cycle, stage="drain")
                if not self._execute_one():
                    break
                drain_cycle += 1

        self.telemetry.record_resource_snapshot(self.monitor.capture(stage="end"))
        return self.telemetry.to_report()

    def run_to_file(self, *, frames: int, output: str | Path, drain: bool = True) -> None:
        self.run(frames=frames, drain=drain)
        self.telemetry.write_json(output)

    def _record_backlog_and_shed(self, *, cycle: int, stage: str) -> None:
        self.telemetry.record_backlog(
            self.queues.snapshot_backlog(),
            cycle=cycle,
            stage=f"{stage}_before_policy",
        )
        drops, decisions = self.policy.apply(self.queues)
        for drop in drops:
            self.telemetry.record_drop(drop)
        for decision in decisions:
            self.telemetry.record_policy_decision(decision)
        self.telemetry.record_backlog(
            self.queues.snapshot_backlog(),
            cycle=cycle,
            stage=f"{stage}_after_policy",
        )

    def _execute_one(self) -> bool:
        decision = self.scheduler.choose_next(self.queues)
        if decision is None:
            return False
        self.telemetry.record_schedule(decision)
        frame = self.queues.pop(decision.task_name)
        if frame is None:
            return False
        task = self.task_map[decision.task_name]
        result = self.worker.run(task, frame)
        self.telemetry.record_execution(
            result,
            frame=frame,
            backlog_after=self.queues.backlog(decision.task_name),
        )
        return True
