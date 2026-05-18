from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DROP_POLICIES = {"drop_oldest", "drop_newest", "drop_low_priority"}
INPUT_SOURCES = {"dummy", "image", "video"}
SCENARIO_MODES = {"normal", "overload", "sustained_high_load", "device_local"}
WORKERS = {"dummy", "onnxruntime", "tensorrt"}


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
    emit_every_cycles: int = 1
    engine_path: str | None = None
    worker_options: dict[str, Any] | None = None
    agent_manifest_path: str | None = None
    runtime_result_path: str | None = None
    agent_id: str | None = None
    agent_task_id: str | None = None
    agent_type: str | None = None
    agent_input_type: str | None = None
    agent_output_type: str | None = None
    fallback_policy: str | None = None
    telemetry_contract_version: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskConfig":
        worker_options = value.get("worker_options")
        if worker_options is not None and not isinstance(worker_options, dict):
            raise ValueError("worker_options must be a mapping when provided")
        agent_defaults = _agent_defaults_from_task(value)
        name = str(value.get("name", agent_defaults.get("name", "")))
        model_path = str(value.get("model_path", agent_defaults.get("model_path", "")))
        task = cls(
            name=name,
            model_path=model_path,
            priority=int(value.get("priority", agent_defaults.get("priority", 0))),
            target_fps=float(value["target_fps"]),
            latency_budget_ms=float(
                value.get("latency_budget_ms", agent_defaults.get("latency_budget_ms", 0))
            ),
            queue_size=int(value["queue_size"]),
            drop_policy=str(value.get("drop_policy", "drop_oldest")),
            worker=str(value.get("worker", "dummy")),
            simulated_latency_ms=float(value.get("simulated_latency_ms", 1.0)),
            emit_every_cycles=int(value.get("emit_every_cycles", 1)),
            engine_path=(
                None
                if value.get("engine_path") is None
                else str(value.get("engine_path"))
            ),
            worker_options=worker_options,
            agent_manifest_path=_optional_string(value.get("agent_manifest_path")),
            runtime_result_path=_optional_string(value.get("runtime_result_path")),
            agent_id=_optional_string(value.get("agent_id", agent_defaults.get("agent_id"))),
            agent_task_id=_optional_string(
                value.get("agent_task_id", agent_defaults.get("agent_task_id"))
            ),
            agent_type=_optional_string(
                value.get("agent_type", agent_defaults.get("agent_type"))
            ),
            agent_input_type=_optional_string(
                value.get("agent_input_type", agent_defaults.get("agent_input_type"))
            ),
            agent_output_type=_optional_string(
                value.get("agent_output_type", agent_defaults.get("agent_output_type"))
            ),
            fallback_policy=_optional_string(
                value.get("fallback_policy", agent_defaults.get("fallback_policy"))
            ),
            telemetry_contract_version=_optional_string(
                value.get(
                    "telemetry_contract_version",
                    agent_defaults.get("telemetry_contract_version"),
                )
            ),
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
        if self.emit_every_cycles <= 0:
            raise ValueError(f"{self.name}: emit_every_cycles must be > 0")
        if self.engine_path is not None and not self.engine_path:
            raise ValueError(f"{self.name}: engine_path must not be empty when provided")
        if self.agent_id is not None and not self.agent_id:
            raise ValueError(f"{self.name}: agent_id must not be empty when provided")
        if self.agent_task_id is not None and not self.agent_task_id:
            raise ValueError(f"{self.name}: agent_task_id must not be empty when provided")
        if self.agent_manifest_path is not None and not self.agent_manifest_path:
            raise ValueError(
                f"{self.name}: agent_manifest_path must not be empty when provided"
            )
        if self.runtime_result_path is not None and not self.runtime_result_path:
            raise ValueError(
                f"{self.name}: runtime_result_path must not be empty when provided"
            )
        if self.worker == "tensorrt" and not self.engine_path:
            raise ValueError(f"{self.name}: tensorrt worker requires engine_path")
        options = self.worker_options or {}
        allow_engine_build = options.get("allow_engine_build")
        if allow_engine_build is not None and not isinstance(allow_engine_build, bool):
            raise ValueError(
                f"{self.name}: worker_options.allow_engine_build must be a boolean"
            )
        providers = options.get("providers")
        if providers is not None:
            if not isinstance(providers, list) or not all(
                isinstance(provider, str) and provider for provider in providers
            ):
                raise ValueError(
                    f"{self.name}: worker_options.providers must be a list of strings"
                )


@dataclass(frozen=True)
class OrchestratorConfig:
    tasks: tuple[TaskConfig, ...]
    name: str = "default"
    scenario_mode: str = "normal"
    overload_backlog_threshold: int = 8
    frame_interval_ms: float = 1.0
    input_source: str = "dummy"
    input_path: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OrchestratorConfig":
        run = value.get("run", {})
        tasks = tuple(TaskConfig.from_dict(task) for task in value["tasks"])
        config = cls(
            tasks=tasks,
            name=str(run.get("name", "default")),
            scenario_mode=str(run.get("scenario_mode", "normal")),
            overload_backlog_threshold=int(run.get("overload_backlog_threshold", 8)),
            frame_interval_ms=float(run.get("frame_interval_ms", 1.0)),
            input_source=str(run.get("input_source", "dummy")),
            input_path=run.get("input_path"),
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
        if self.scenario_mode not in SCENARIO_MODES:
            raise ValueError(f"unsupported scenario_mode {self.scenario_mode!r}")
        if self.frame_interval_ms <= 0:
            raise ValueError("frame_interval_ms must be > 0")
        if self.input_source not in INPUT_SOURCES:
            raise ValueError(f"unsupported input_source {self.input_source!r}")
        if self.input_source in {"image", "video"} and not self.input_path:
            raise ValueError(f"{self.input_source} input_source requires input_path")

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


def _agent_defaults_from_task(value: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    agent_manifest_path = value.get("agent_manifest_path")
    runtime_result_path = value.get("runtime_result_path")
    if agent_manifest_path is not None:
        defaults.update(_defaults_from_agent_manifest(Path(str(agent_manifest_path))))
    if runtime_result_path is not None:
        defaults.update(_defaults_from_runtime_result(Path(str(runtime_result_path))))
    return defaults


def _defaults_from_agent_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_mapping(path)
    fallback_policy = manifest.get("fallback_policy")
    if fallback_policy is not None and not isinstance(fallback_policy, dict):
        raise ValueError(f"{path}: fallback_policy must be a mapping when provided")

    schema_version = str(manifest.get("schema_version", ""))
    if schema_version != "inferedge-agent-manifest-v1":
        raise ValueError(f"{path}: unsupported agent manifest schema_version")

    agent_id = str(manifest.get("agent_id", ""))
    if not agent_id:
        raise ValueError(f"{path}: agent_id is required")

    return {
        "name": agent_id,
        "model_path": manifest.get("runtime_artifact_path", ""),
        "priority": manifest.get("priority", 0),
        "latency_budget_ms": manifest.get("latency_budget_ms", 0),
        "agent_id": agent_id,
        "agent_task_id": f"task_{agent_id}",
        "agent_type": manifest.get("agent_type"),
        "agent_input_type": manifest.get("input_type"),
        "agent_output_type": manifest.get("output_type"),
        "fallback_policy": (
            fallback_policy.get("mode") if isinstance(fallback_policy, dict) else None
        ),
        "telemetry_contract_version": manifest.get("telemetry_contract_version"),
    }


def _defaults_from_runtime_result(path: Path) -> dict[str, Any]:
    result = _load_mapping(path)
    agent = result.get("agent")
    if not isinstance(agent, dict):
        raise ValueError(f"{path}: Runtime result is missing object field: agent")
    schema_version = str(agent.get("schema_version", ""))
    if schema_version != "inferedge-runtime-agent-task-v1":
        raise ValueError(f"{path}: unsupported Runtime agent task schema_version")
    return {
        "agent_id": agent.get("agent_id"),
        "agent_task_id": agent.get("task_id"),
        "agent_type": agent.get("agent_type"),
        "agent_input_type": agent.get("input_type"),
        "agent_output_type": agent.get("output_type"),
        "priority": agent.get("scheduled_priority", 0),
        "latency_budget_ms": agent.get("latency_budget_ms", 0),
        "model_path": agent.get("runtime_artifact_path", ""),
        "fallback_policy": _runtime_fallback_policy(agent),
        "telemetry_contract_version": agent.get("telemetry_contract_version"),
    }


def _runtime_fallback_policy(agent: dict[str, Any]) -> str | None:
    fallback = agent.get("fallback_policy")
    if isinstance(fallback, dict):
        mode = fallback.get("mode")
        return None if mode is None else str(mode)
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
