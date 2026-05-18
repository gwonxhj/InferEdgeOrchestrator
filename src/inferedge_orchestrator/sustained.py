from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig
from inferedge_orchestrator.monitor import parse_tegrastats_line
from inferedge_orchestrator.runtime import OrchestratorRuntime


MULTI_WORKLOAD_SCHEMA = "inferedge-orchestrator-multi-workload-sustained-v1"


def run_multi_workload_sustained(
    config: OrchestratorConfig,
    *,
    frames: int,
    tegrastats_log: str | Path | None = None,
    sleep_worker: bool = False,
) -> dict[str, Any]:
    """Run the sustained scenario and attach workload-profile evidence.

    This is intentionally an Orchestrator-level wrapper. It preserves the
    existing orchestration summary contract and adds a separate summary block
    for the first lightweight sustained multi-workload demo.
    """

    report = OrchestratorRuntime(config, sleep_worker=sleep_worker).run(frames=frames)
    tegrastats = load_tegrastats_timeline(tegrastats_log)
    report["tegrastats_timeline"] = tegrastats
    report["multi_workload_sustained_summary"] = _multi_workload_summary(
        config,
        report,
        tegrastats,
    )
    return report


def write_multi_workload_sustained(
    config: OrchestratorConfig,
    *,
    output: str | Path,
    frames: int,
    tegrastats_log: str | Path | None = None,
    sleep_worker: bool = False,
) -> dict[str, Any]:
    report = run_multi_workload_sustained(
        config,
        frames=frames,
        tegrastats_log=tegrastats_log,
        sleep_worker=sleep_worker,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def load_tegrastats_timeline(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "source": "not_provided",
            "sample_count": 0,
            "samples": [],
            "summary": {},
        }

    log_path = Path(path)
    samples = []
    for index, line in enumerate(log_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        samples.append({"sample_index": index, **parse_tegrastats_line(line)})

    return {
        "source": str(log_path),
        "sample_count": len(samples),
        "samples": samples,
        "summary": _tegrastats_summary(samples),
    }


def _multi_workload_summary(
    config: OrchestratorConfig,
    report: dict[str, Any],
    tegrastats: dict[str, Any],
) -> dict[str, Any]:
    sustained = report.get("sustained_runtime_summary", {})
    totals = report.get("agent_runtime_summary", {}).get("totals", {})
    reasons = _policy_decision_reasons(report)
    return {
        "schema_version": MULTI_WORKLOAD_SCHEMA,
        "scenario_mode": config.scenario_mode,
        "evidence_scope": _evidence_scope(config),
        "workload_profiles": [_workload_profile(task, report) for task in config.tasks],
        "observed_runtime_signals": {
            "max_total_queue_depth": sustained.get("max_total_queue_depth", 0),
            "executed_count": totals.get("executed_count", 0),
            "dropped_count": totals.get("dropped_count", 0),
            "deadline_missed_count": totals.get("deadline_missed_count", 0),
            "fallback_count": totals.get("fallback_count", 0),
            "policy_decision_count": totals.get("policy_decision_count", 0),
            "policy_decision_reasons": reasons,
            "tegrastats_sample_count": tegrastats.get("sample_count", 0),
            **_local_profile_signals(report),
            **_producer_source_signals(report),
        },
        "next_validation_step": _next_validation_step(config),
    }


def _workload_profile(task: TaskConfig, report: dict[str, Any]) -> dict[str, Any]:
    options = task.worker_options or {}
    task_report = report.get("tasks", {}).get(task.name, {})
    return {
        "task": task.name,
        "agent_id": task.agent_id,
        "agent_type": task.agent_type,
        "workload_type": str(options.get("workload_type", _default_workload_type(task))),
        "runtime_loop": str(options.get("runtime_loop", _default_runtime_loop(task))),
        "ingress_profile": str(options.get("ingress_profile", _default_ingress(task))),
        "implementation": str(options.get("implementation", "synthetic_adapter")),
        "producer_stage": options.get("producer_stage"),
        "device_local_validation": bool(options.get("device_local_validation", False)),
        "profile_work_units": options.get("profile_work_units"),
        "expected_runtime_mode": str(
            options.get("expected_runtime_mode", "sustained")
        ),
        "preferred_device": options.get("preferred_device"),
        "executed": task_report.get("executed", 0),
        "dropped": task_report.get("dropped", 0),
        "deadline_missed": task_report.get("deadline_missed", 0),
        "fallback_used": task_report.get("fallback_used", 0),
        "mean_latency_ms": task_report.get("mean_latency_ms"),
        "p95_latency_ms": task_report.get("p95_latency_ms"),
        "max_queue_backlog": task_report.get("max_queue_backlog", 0),
    }


def _default_workload_type(task: TaskConfig) -> str:
    if task.agent_type == "vision":
        return "realtime_vision"
    if task.agent_type == "voice":
        return "voice_command"
    if task.agent_type == "safety":
        return "telemetry_monitor"
    return "utility"


def _default_runtime_loop(task: TaskConfig) -> str:
    if task.agent_type == "vision":
        return "yolo_detection_loop"
    if task.agent_type == "voice":
        return "whisper_command_burst"
    if task.agent_type == "safety":
        return "safety_monitor_loop"
    return "utility_loop"


def _default_ingress(task: TaskConfig) -> str:
    if task.agent_type == "vision":
        return "frame_queue"
    if task.agent_type == "voice":
        return "fastapi_concurrent_request"
    if task.agent_type == "safety":
        return "periodic_monitor"
    return "scheduled_task"


def _evidence_scope(config: OrchestratorConfig) -> str:
    if config.scenario_mode == "device_local":
        return (
            "device-local sustained validation starter using committed local "
            "image, FastAPI-style request, and resource snapshot producers; "
            "live device producers remain optional follow-up integrations"
        )
    return (
        "local sustained workload profiles with lightweight CPU profile "
        "adapters; external YOLO/Whisper/FastAPI integrations remain optional"
    )


def _next_validation_step(config: OrchestratorConfig) -> str:
    if config.scenario_mode == "device_local":
        return (
            "replace committed producer fixtures with live device-local YOLO/ONNX, "
            "FastAPI ingress, or tegrastats producers one at a time"
        )
    return (
        "replace local CPU profile adapters with device-local lightweight YOLO, "
        "Whisper, FastAPI ingress, or tegrastats producers one at a time"
    )


def _local_profile_signals(report: dict[str, Any]) -> dict[str, Any]:
    profiled_events = []
    profile_kinds: list[str] = []
    elapsed_total = 0.0
    for event in report.get("result_events", []):
        if not isinstance(event, dict):
            continue
        output = event.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("implementation") != "local_profile_adapter":
            continue
        profiled_events.append(output)
        kind = output.get("profile_kind")
        if isinstance(kind, str) and kind not in profile_kinds:
            profile_kinds.append(kind)
        elapsed = output.get("profile_elapsed_ms")
        if isinstance(elapsed, int | float):
            elapsed_total += float(elapsed)

    return {
        "local_profile_adapter_count": len(profiled_events),
        "local_profile_elapsed_ms": round(elapsed_total, 3),
        "local_profile_kinds": profile_kinds,
    }


def _producer_source_signals(report: dict[str, Any]) -> dict[str, Any]:
    producer_events = []
    producer_sources: list[str] = []
    device_local_sources = {
        "image_file",
        "video_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    for event in report.get("result_events", []):
        if not isinstance(event, dict):
            continue
        output = event.get("output")
        if not isinstance(output, dict):
            continue
        source = output.get("producer_source")
        if not isinstance(source, str) or not source:
            continue
        producer_events.append(output)
        if source not in producer_sources:
            producer_sources.append(source)

    return {
        "producer_source_count": len(producer_events),
        "producer_sources": producer_sources,
        "device_local_producer_count": sum(
            1
            for output in producer_events
            if output.get("producer_source") in device_local_sources
        ),
    }


def _policy_decision_reasons(report: dict[str, Any]) -> list[str]:
    reasons = []
    for decision in report.get("policy_decision_log", []):
        if not isinstance(decision, dict):
            continue
        reason = decision.get("decision_reason") or decision.get("reason")
        if isinstance(reason, str) and reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _tegrastats_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    gpu_values = [
        value
        for sample in samples
        if isinstance((value := sample.get("gpu_percent")), int | float)
    ]
    ram_values = [
        value
        for sample in samples
        if isinstance((value := sample.get("ram_used_mb")), int | float)
    ]
    temperatures: list[float] = []
    for sample in samples:
        raw_temperatures = sample.get("temperatures_c")
        if isinstance(raw_temperatures, dict):
            temperatures.extend(
                float(value)
                for value in raw_temperatures.values()
                if isinstance(value, int | float)
            )

    summary: dict[str, Any] = {}
    if gpu_values:
        summary["max_gpu_percent"] = max(gpu_values)
    if ram_values:
        summary["max_ram_used_mb"] = max(ram_values)
    if temperatures:
        summary["max_temperature_c"] = round(max(temperatures), 3)
    return summary
