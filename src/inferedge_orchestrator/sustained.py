from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig
from inferedge_orchestrator.monitor import ResourceMonitor, parse_tegrastats_line
from inferedge_orchestrator.runtime import OrchestratorRuntime


MULTI_WORKLOAD_SCHEMA = "inferedge-orchestrator-multi-workload-sustained-v1"


def apply_device_local_input_overrides(
    config: OrchestratorConfig,
    *,
    vision_input: str | Path | None = None,
    vision_onnx_model: str | Path | None = None,
    voice_ingress_payload: str | Path | None = None,
    resource_snapshot: str | Path | None = None,
    resource_snapshot_source: str | None = None,
) -> OrchestratorConfig:
    """Return a config that points device-local producers at local inputs.

    The committed config remains the stable starter. These overrides let a local
    run replace the tiny fixtures with user-provided files without changing the
    JSON contract or requiring live service dependencies.
    """

    if (
        vision_input is None
        and vision_onnx_model is None
        and voice_ingress_payload is None
        and resource_snapshot is None
    ):
        return config

    input_source = config.input_source
    input_path = config.input_path
    if vision_input is not None:
        path = Path(vision_input)
        input_source = _vision_input_source(path)
        input_path = str(path)

    tasks = []
    for task in config.tasks:
        options = dict(task.worker_options or {})
        if vision_input is not None and task.agent_type == "vision":
            options["device_local_validation"] = True
            options["producer_stage"] = "device_local_cli_override"
        if vision_onnx_model is not None and task.agent_type == "vision":
            options["device_local_validation"] = True
            options["producer_stage"] = "device_local_cli_override"
            options["vision_inference_backend"] = "onnxruntime"
            options["vision_model_path"] = str(Path(vision_onnx_model))
        if voice_ingress_payload is not None and task.agent_type == "voice":
            options["device_local_validation"] = True
            options["producer_stage"] = "device_local_cli_override"
            options["ingress_payload_path"] = str(Path(voice_ingress_payload))
        if resource_snapshot is not None and task.agent_type == "safety":
            options["device_local_validation"] = True
            options["producer_stage"] = "device_local_cli_override"
            options["resource_snapshot_path"] = str(Path(resource_snapshot))
            if resource_snapshot_source is not None:
                options["resource_snapshot_source"] = resource_snapshot_source
        tasks.append(replace(task, worker_options=options))

    overridden = replace(
        config,
        input_source=input_source,
        input_path=input_path,
        tasks=tuple(tasks),
    )
    overridden.validate()
    return overridden


def write_process_resource_snapshot(path: str | Path) -> Path:
    """Write a small current-process resource snapshot for Safety producer input."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = ResourceMonitor().capture(stage="device_local_process")
    memory_used_mb = snapshot.process_rss_mb or 0.0
    memory_total_mb = _estimated_memory_total_mb(
        memory_used_mb=memory_used_mb,
        memory_percent=snapshot.memory_percent,
    )
    payload = {
        "snapshots": [
            {
                "snapshot_id": "device_local_process_0",
                "source": "process_resource_snapshot",
                "stage": snapshot.stage,
                "platform": snapshot.platform,
                "cpu_percent": snapshot.cpu_percent or 0.0,
                "memory_used_mb": memory_used_mb,
                "memory_total_mb": memory_total_mb,
                "temperature_c": 0.0,
                "queue_depth": 0,
                "fallback_count": 0,
                "deadline_missed_count": 0,
                "dropped_count": 0,
            }
        ]
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


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
    report.setdefault("run", {}).update(_scenario_identity(config))
    report.setdefault("sustained_runtime_summary", {}).update(_scenario_identity(config))
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
        **_scenario_identity(config),
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


def _scenario_identity(config: OrchestratorConfig) -> dict[str, str]:
    labels = {
        "normal": {
            "scenario_label": "normal_scheduler_smoke",
            "scenario_category": "normal",
            "scenario_description": (
                "Nominal priority/deadline scheduler smoke without intentional "
                "sustained overload pressure."
            ),
        },
        "overload": {
            "scenario_label": "overload_scheduler_pressure",
            "scenario_category": "overload",
            "scenario_description": (
                "Intentional backlog pressure scenario for observing drop, "
                "load-shedding, and fallback behavior."
            ),
        },
        "sustained_high_load": {
            "scenario_label": "producer_backed_sustained_high_load",
            "scenario_category": "sustained",
            "scenario_description": (
                "Producer-backed sustained multi-workload smoke with "
                "Vision, Voice, and Safety workload pressure."
            ),
        },
        "device_local": {
            "scenario_label": "device_local_sustained_starter",
            "scenario_category": "device_local",
            "scenario_description": (
                "Device-local sustained starter using local Vision, Voice, "
                "Safety, and optional tegrastats inputs."
            ),
        },
    }
    return labels.get(
        config.scenario_mode,
        {
            "scenario_label": f"{config.scenario_mode}_scenario",
            "scenario_category": "custom",
            "scenario_description": (
                "Custom Orchestrator scenario mode. Verify downstream wording "
                "before portfolio use."
            ),
        },
    )


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
        "vision_inference_backend": options.get("vision_inference_backend"),
        "vision_model_path": options.get("vision_model_path"),
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


def _vision_input_source(path: Path) -> str:
    if path.is_dir():
        return "image_sequence"
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
        return "video"
    return "image"


def _estimated_memory_total_mb(
    *,
    memory_used_mb: float,
    memory_percent: float | None,
) -> float:
    if memory_percent and memory_percent > 0:
        return round(memory_used_mb / (memory_percent / 100.0), 3)
    return max(memory_used_mb, 1.0)


def _local_profile_signals(report: dict[str, Any]) -> dict[str, Any]:
    profiled_events = []
    profile_kinds: list[str] = []
    vision_inference_backends: list[str] = []
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
        vision_backend = output.get("vision_inference_backend")
        if (
            isinstance(vision_backend, str)
            and vision_backend not in vision_inference_backends
        ):
            vision_inference_backends.append(vision_backend)
        elapsed = output.get("profile_elapsed_ms")
        if isinstance(elapsed, int | float):
            elapsed_total += float(elapsed)

    return {
        "local_profile_adapter_count": len(profiled_events),
        "local_profile_elapsed_ms": round(elapsed_total, 3),
        "local_profile_kinds": profile_kinds,
        "vision_inference_backend_count": len(vision_inference_backends),
        "vision_inference_backends": vision_inference_backends,
    }


def _producer_source_signals(report: dict[str, Any]) -> dict[str, Any]:
    producer_events = []
    producer_sources: list[str] = []
    device_local_sources = {
        "image_file",
        "image_sequence_file",
        "video_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
        "process_resource_snapshot",
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
