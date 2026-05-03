from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DROP_POLICIES = {"drop_oldest", "drop_newest", "drop_low_priority"}
WORKERS = {"dummy"}


@dataclass(frozen=True)
class TaskConfig:
    name: str
    model_path: str
    priority: int
    target_fps: float
    latency_budget_ms: float
    queue_size: int
    drop_policy: str = "drop_oldest"
    worker: str = "dummy"
    simulated_latency_ms: float = 1.0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskConfig":
        task = cls(
            name=str(value["name"]),
            model_path=str(value.get("model_path", "")),
            priority=int(value["priority"]),
            target_fps=float(value["target_fps"]),
            latency_budget_ms=float(value["latency_budget_ms"]),
            queue_size=int(value["queue_size"]),
            drop_policy=str(value.get("drop_policy", "drop_oldest")),
            worker=str(value.get("worker", "dummy")),
            simulated_latency_ms=float(value.get("simulated_latency_ms", 1.0)),
        )
        task.validate()
        return task

    def validate(self) -> None:
        if not self.name:
            raise ValueError("task name must not be empty")
        if self.priority < 0:
            raise ValueError(f"{self.name}: priority must be >= 0")
        if self.target_fps <= 0:
            raise ValueError(f"{self.name}: target_fps must be > 0")
        if self.latency_budget_ms <= 0:
            raise ValueError(f"{self.name}: latency_budget_ms must be > 0")
        if self.queue_size <= 0:
            raise ValueError(f"{self.name}: queue_size must be > 0")
        if self.drop_policy not in DROP_POLICIES:
            raise ValueError(f"{self.name}: unsupported drop_policy {self.drop_policy!r}")
        if self.worker not in WORKERS:
            raise ValueError(f"{self.name}: unsupported worker {self.worker!r}")
        if self.simulated_latency_ms < 0:
            raise ValueError(f"{self.name}: simulated_latency_ms must be >= 0")


@dataclass(frozen=True)
class OrchestratorConfig:
    tasks: tuple[TaskConfig, ...]
    name: str = "default"
    overload_backlog_threshold: int = 8

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OrchestratorConfig":
        run = value.get("run", {})
        tasks = tuple(TaskConfig.from_dict(task) for task in value["tasks"])
        config = cls(
            tasks=tasks,
            name=str(run.get("name", "default")),
            overload_backlog_threshold=int(run.get("overload_backlog_threshold", 8)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.tasks:
            raise ValueError("at least one task is required")
        names = [task.name for task in self.tasks]
        if len(names) != len(set(names)):
            raise ValueError("task names must be unique")
        if self.overload_backlog_threshold <= 0:
            raise ValueError("overload_backlog_threshold must be > 0")

    def task_map(self) -> dict[str, TaskConfig]:
        return {task.name: task for task in self.tasks}


def load_config(path: str | Path) -> OrchestratorConfig:
    config_path = Path(path)
    value = _load_mapping(config_path)
    return OrchestratorConfig.from_dict(value)


def _load_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "YAML configs require the optional PyYAML dependency. "
                "Use JSON or install inferedge-orchestrator[yaml]."
            ) from exc
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: config root must be a mapping")
        return loaded
    raise ValueError(f"unsupported config format: {path.suffix}")


def sorted_tasks_by_priority(tasks: Iterable[TaskConfig]) -> list[TaskConfig]:
    return sorted(tasks, key=lambda task: (-task.priority, task.name))
