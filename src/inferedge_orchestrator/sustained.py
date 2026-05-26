from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig
from inferedge_orchestrator.monitor import ResourceMonitor, parse_tegrastats_line
from inferedge_orchestrator.runtime import OrchestratorRuntime


MULTI_WORKLOAD_SCHEMA = "inferedge-orchestrator-multi-workload-sustained-v1"
EDGEENV_TELEMETRY_FEED_SCHEMA = (
    "inferedge-orchestrator-edgeenv-runtime-telemetry-feed-v1"
)
EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY = "InferEdgeOrchestrator"
EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE = "orchestrator-supplemental-operation-context"
EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT = EDGEENV_TELEMETRY_FEED_SCHEMA
EDGEENV_HISTORY_COVERAGE_PATH = "runtime_telemetry_context.history.telemetry_coverage"
EDGEENV_CANDIDATE_CONTEXT_PATH = "runtime_telemetry_context.candidate"
EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS = [
    "run_id",
    "telemetry_source",
    "operation",
    "resource",
]
EDGEENV_AIGUARD_EVIDENCE_CANDIDATES = [
    "runtime_queue_overload",
    "runtime_thermal_instability",
]
EDGEENV_PRODUCER_LINEAGE_AIGUARD_EVIDENCE_TYPE = (
    "edgeenv_orchestrator_producer_lineage"
)


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
    report["edgeenv_runtime_telemetry_feed"] = _edgeenv_runtime_telemetry_feed(
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
    edgeenv_feed_output: str | Path | None = None,
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
    if edgeenv_feed_output is not None:
        write_edgeenv_runtime_telemetry_feed(report, edgeenv_feed_output)
    return report


def write_edgeenv_runtime_telemetry_feed(
    report: dict[str, Any],
    output: str | Path,
) -> dict[str, Any]:
    feed = report.get("edgeenv_runtime_telemetry_feed")
    if not isinstance(feed, dict):
        raise ValueError("sustained report is missing edgeenv_runtime_telemetry_feed")
    validate_edgeenv_runtime_telemetry_feed(feed)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(feed, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return feed


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


def _edgeenv_runtime_telemetry_feed(
    config: OrchestratorConfig,
    report: dict[str, Any],
    tegrastats: dict[str, Any],
) -> dict[str, Any]:
    run = report.get("run", {})
    sustained = report.get("sustained_runtime_summary", {})
    queue_summary = report.get("queue_state_summary", {})
    runtime_event_summary = report.get("runtime_event_summary", {})
    totals = report.get("agent_runtime_summary", {}).get("totals", {})
    resource = _edgeenv_resource_context(report, tegrastats)
    operation = {
        "queue_depth": queue_summary.get(
            "max_total_queue_depth",
            sustained.get("max_total_queue_depth", 0),
        ),
        "deadline_missed_count": totals.get(
            "deadline_missed_count",
            sustained.get("deadline_missed_count", 0),
        ),
        "fallback_count": totals.get(
            "fallback_count",
            sustained.get("fallback_count", 0),
        ),
        "dropped_count": totals.get(
            "dropped_count",
            sustained.get("dropped_count", 0),
        ),
        "policy_decision_count": totals.get(
            "policy_decision_count",
            sustained.get("policy_decision_count", 0),
        ),
        "queue_pressure_state": queue_summary.get("queue_pressure_state"),
        "queue_pressure_reason": queue_summary.get("queue_pressure_reason"),
        "policy_decision_reasons": queue_summary.get("policy_decision_reasons", []),
        "drop_reason_counts": queue_summary.get("drop_reason_counts", {}),
        "runtime_event_counts": runtime_event_summary.get("event_type_counts", {}),
        "runtime_event_reason_counts": runtime_event_summary.get("reason_counts", {}),
    }
    producer = _edgeenv_producer_context(report)
    available_sections = [
        "operation",
        "resource",
        "queue_state_summary",
        "runtime_event_summary",
    ]
    if producer:
        available_sections.append("producer")
    candidate_context = {
        "run_id": run.get("name", config.name),
        "result_telemetry_present": True,
        "history_entry_present": True,
        "telemetry_source": "inferedge_orchestrator_operation_summary",
        "available_sections": available_sections,
        "queue_depth": operation["queue_depth"],
        "operation": operation,
        "resource": resource,
    }
    if producer:
        candidate_context["producer"] = producer
    if resource.get("gpu_temperature") is not None:
        candidate_context["gpu_temperature"] = resource["gpu_temperature"]
    if resource.get("cpu_temperature") is not None:
        candidate_context["cpu_temperature"] = resource["cpu_temperature"]
    if resource.get("ram_used_mb") is not None:
        candidate_context["ram_used_mb"] = resource["ram_used_mb"]

    return {
        "schema_version": EDGEENV_TELEMETRY_FEED_SCHEMA,
        "role": "orchestrator_operation_context_for_edgeenv",
        "source_repository": EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY,
        "artifact_role": EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE,
        "producer_contract": EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT,
        "source": "orchestration_summary",
        "run_id": run.get("name", config.name),
        "scenario_mode": config.scenario_mode,
        "scenario_label": run.get("scenario_label"),
        "not_a_regression_judgement": True,
        "not_a_comparability_gate": True,
        "decision_owner": "lab",
        "regression_owner": "edgeenv",
        "candidate_context": candidate_context,
        "edgeenv_mapping_hint": {
            "runtime_telemetry_context_role": "candidate",
            "copy_candidate_context_to": EDGEENV_CANDIDATE_CONTEXT_PATH,
            "operation_context_role": "supplemental",
            "coverage_summary_owner": "edgeenv",
            "coverage_summary_path": EDGEENV_HISTORY_COVERAGE_PATH,
            "candidate_context_required_fields": list(
                EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS
            ),
            "aiguard_evidence_candidates": list(
                EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
            ),
        },
        "downstream_guard_alignment": {
            "declared_by": "orchestrator",
            "producer_lineage_evidence_type": (
                EDGEENV_PRODUCER_LINEAGE_AIGUARD_EVIDENCE_TYPE
            ),
            "operation_evidence_candidates": list(
                EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
            ),
            "validated_by": [
                "edgeenv runs telemetry inspect-history",
                "inferedge-aiguard reason-edgeenv-regression",
                "inferedgelab runtime-intelligence bundle manifest gate",
            ],
            "orchestrator_is_final_decision_owner": False,
            "lab_is_final_decision_owner": True,
        },
    }


def validate_edgeenv_runtime_telemetry_feed(
    feed: dict[str, Any],
    *,
    require_device_local_producer: bool = False,
) -> None:
    if feed.get("schema_version") != EDGEENV_TELEMETRY_FEED_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.schema_version must be "
            f"{EDGEENV_TELEMETRY_FEED_SCHEMA}"
        )
    if feed.get("role") != "orchestrator_operation_context_for_edgeenv":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.role must be "
            "orchestrator_operation_context_for_edgeenv"
        )
    if feed.get("source_repository") != EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.source_repository must be "
            f"{EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY}"
        )
    if feed.get("artifact_role") != EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.artifact_role must be "
            f"{EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE}"
        )
    if feed.get("producer_contract") != EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.producer_contract must be "
            f"{EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT}"
        )
    if feed.get("not_a_regression_judgement") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.not_a_regression_judgement must be true"
        )
    if feed.get("not_a_comparability_gate") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.not_a_comparability_gate must be true"
        )
    if feed.get("decision_owner") != "lab":
        raise ValueError("edgeenv_runtime_telemetry_feed.decision_owner must be lab")
    if feed.get("regression_owner") != "edgeenv":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.regression_owner must be edgeenv"
        )
    if not isinstance(feed.get("candidate_context"), dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context must be an object"
        )
    candidate_context = feed["candidate_context"]
    for field in EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS:
        if field not in candidate_context:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context must include "
                f"{field}"
            )
    if not isinstance(candidate_context.get("operation"), dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation must be "
            "an object"
        )
    if not isinstance(candidate_context.get("resource"), dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.resource must be "
            "an object"
        )
    mapping_hint = feed.get("edgeenv_mapping_hint")
    if not isinstance(mapping_hint, dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint must be an object"
        )
    if mapping_hint.get("copy_candidate_context_to") != EDGEENV_CANDIDATE_CONTEXT_PATH:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            f"copy_candidate_context_to must be {EDGEENV_CANDIDATE_CONTEXT_PATH}"
        )
    if mapping_hint.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "operation_context_role must be supplemental"
        )
    if mapping_hint.get("coverage_summary_owner") != "edgeenv":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "coverage_summary_owner must be edgeenv"
        )
    if mapping_hint.get("coverage_summary_path") != EDGEENV_HISTORY_COVERAGE_PATH:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            f"coverage_summary_path must be {EDGEENV_HISTORY_COVERAGE_PATH}"
        )
    required_fields = mapping_hint.get("candidate_context_required_fields")
    if not isinstance(required_fields, list):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "candidate_context_required_fields must be a list"
        )
    missing_required_fields = [
        field
        for field in EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS
        if field not in required_fields
    ]
    if missing_required_fields:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "candidate_context_required_fields missing "
            f"{missing_required_fields}"
        )
    evidence_candidates = mapping_hint.get("aiguard_evidence_candidates")
    if not isinstance(evidence_candidates, list):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "aiguard_evidence_candidates must be a list"
        )
    missing_evidence_candidates = [
        candidate
        for candidate in EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
        if candidate not in evidence_candidates
    ]
    if missing_evidence_candidates:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.edgeenv_mapping_hint."
            "aiguard_evidence_candidates missing "
            f"{missing_evidence_candidates}"
        )
    guard_alignment = feed.get("downstream_guard_alignment")
    if not isinstance(guard_alignment, dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment must be "
            "an object"
        )
    if guard_alignment.get("declared_by") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "declared_by must be orchestrator"
        )
    if (
        guard_alignment.get("producer_lineage_evidence_type")
        != EDGEENV_PRODUCER_LINEAGE_AIGUARD_EVIDENCE_TYPE
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "producer_lineage_evidence_type must be "
            f"{EDGEENV_PRODUCER_LINEAGE_AIGUARD_EVIDENCE_TYPE}"
        )
    operation_evidence_candidates = guard_alignment.get("operation_evidence_candidates")
    if not isinstance(operation_evidence_candidates, list):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "operation_evidence_candidates must be a list"
        )
    missing_operation_candidates = [
        candidate
        for candidate in EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
        if candidate not in operation_evidence_candidates
    ]
    if missing_operation_candidates:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "operation_evidence_candidates missing "
            f"{missing_operation_candidates}"
        )
    if guard_alignment.get("orchestrator_is_final_decision_owner") is not False:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "orchestrator_is_final_decision_owner must be false"
        )
    if guard_alignment.get("lab_is_final_decision_owner") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.downstream_guard_alignment."
            "lab_is_final_decision_owner must be true"
        )
    producer = candidate_context.get("producer")
    if producer is not None:
        if not isinstance(producer, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer must "
                "be an object"
            )
        _validate_edgeenv_producer_context(producer)
    if require_device_local_producer and producer is None:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer is "
            "required for device-local feed validation"
        )


def _validate_edgeenv_producer_context(producer: dict[str, Any]) -> None:
    if producer.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "operation_context_role must be supplemental"
        )
    producer_sources = producer.get("producer_sources")
    if (
        not isinstance(producer_sources, list)
        or not producer_sources
        or not all(
            isinstance(item, str) and item for item in producer_sources
        )
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "producer_sources must be a non-empty string list"
        )
    device_local_sources = producer.get("device_local_producer_sources")
    if (
        not isinstance(device_local_sources, list)
        or not device_local_sources
        or not all(
            isinstance(item, str) and item for item in device_local_sources
        )
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "device_local_producer_sources must be a non-empty string list"
        )
    producer_sources_by_task = producer.get("producer_sources_by_task")
    if not isinstance(producer_sources_by_task, dict) or not producer_sources_by_task:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "producer_sources_by_task must be a non-empty object"
        )
    for task_name, sources in producer_sources_by_task.items():
        if not isinstance(task_name, str) or not task_name:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer."
                "producer_sources_by_task keys must be non-empty strings"
            )
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) and item for item in sources)
        ):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer."
                "producer_sources_by_task values must be non-empty string lists"
            )
    mapped_sources = {
        source
        for sources in producer_sources_by_task.values()
        for source in sources
    }
    missing_device_local_sources = [
        source
        for source in device_local_sources
        if source not in producer_sources or source not in mapped_sources
    ]
    if missing_device_local_sources:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "device_local_producer_sources must also appear in producer_sources "
            "and producer_sources_by_task"
        )
    producer_stage_by_task = producer.get("producer_stage_by_task")
    if not isinstance(producer_stage_by_task, dict) or not producer_stage_by_task:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.producer."
            "producer_stage_by_task must be a non-empty object"
        )
    for task_name, stage in producer_stage_by_task.items():
        if not isinstance(task_name, str) or not task_name:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer."
                "producer_stage_by_task keys must be non-empty strings"
            )
        if not isinstance(stage, str) or not stage:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer."
                "producer_stage_by_task values must be non-empty strings"
            )
    for field in (
        "producer_event_count",
        "device_local_event_count",
        "device_local_task_count",
    ):
        value = producer.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.producer."
                f"{field} must be a positive integer"
            )


def _edgeenv_resource_context(
    report: dict[str, Any],
    tegrastats: dict[str, Any],
) -> dict[str, Any]:
    summary = tegrastats.get("summary", {})
    samples = tegrastats.get("samples", [])
    gpu_temperature = _max_named_temperature(samples, {"gpu", "gpu0"})
    cpu_temperature = _max_named_temperature(samples, {"cpu", "cpu0"})
    max_temperature = _first_number(
        summary.get("max_temperature_c"),
        _max_result_output_number(report, "temperature_c"),
    )
    return {
        "source": _resource_context_source(report, tegrastats),
        "resource_evidence_available": bool(
            tegrastats.get("sample_count", 0)
            or _result_output_values(report, "temperature_c")
            or _result_output_values(report, "memory_used_mb")
        ),
        "gpu_temperature": gpu_temperature,
        "cpu_temperature": cpu_temperature,
        "temperature_c": max_temperature,
        "ram_used_mb": _first_number(
            summary.get("max_ram_used_mb"),
            _max_result_output_number(report, "memory_used_mb"),
        ),
        "gpu_percent": summary.get("max_gpu_percent"),
    }


def _edgeenv_producer_context(report: dict[str, Any]) -> dict[str, Any]:
    queue_summary = report.get("queue_state_summary", {})
    runtime_event_summary = report.get("runtime_event_summary", {})
    worker_snapshot = report.get("worker_health_snapshot", {}).get("workers", {})
    if not isinstance(queue_summary, dict) or not isinstance(
        runtime_event_summary, dict
    ):
        return {}
    producer_sources = runtime_event_summary.get("producer_sources")
    device_local_sources = queue_summary.get("device_local_producer_sources")
    producer_sources_by_task = queue_summary.get("producer_sources_by_task")
    if not any([producer_sources, device_local_sources, producer_sources_by_task]):
        return {}

    producer_stage_by_task: dict[str, Any] = {}
    if isinstance(worker_snapshot, dict):
        for task_name, worker in worker_snapshot.items():
            if not isinstance(worker, dict):
                continue
            stage = worker.get("producer_stage")
            if stage:
                producer_stage_by_task[str(task_name)] = stage

    return {
        "producer_sources": list(producer_sources or []),
        "device_local_producer_sources": list(device_local_sources or []),
        "producer_sources_by_task": dict(producer_sources_by_task or {}),
        "producer_stage_by_task": producer_stage_by_task,
        "producer_event_count": runtime_event_summary.get("producer_event_count", 0),
        "device_local_event_count": runtime_event_summary.get(
            "device_local_event_count",
            0,
        ),
        "device_local_task_count": queue_summary.get("device_local_task_count", 0),
        "operation_context_role": "supplemental",
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


def _resource_context_source(
    report: dict[str, Any],
    tegrastats: dict[str, Any],
) -> str:
    if tegrastats.get("sample_count", 0):
        return "tegrastats_timeline"
    if _result_output_values(report, "temperature_c") or _result_output_values(
        report,
        "memory_used_mb",
    ):
        return "result_events_resource_snapshot"
    return "not_available"


def _max_named_temperature(
    samples: Any,
    names: set[str],
) -> float | None:
    values: list[float] = []
    if not isinstance(samples, list):
        return None
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        temperatures = sample.get("temperatures_c")
        if not isinstance(temperatures, dict):
            continue
        for name, value in temperatures.items():
            if (
                str(name).lower() in names
                and isinstance(value, int | float)
                and not isinstance(value, bool)
            ):
                values.append(float(value))
    return round(max(values), 3) if values else None


def _max_result_output_number(
    report: dict[str, Any],
    field: str,
) -> float | None:
    values = _result_output_values(report, field)
    return round(max(values), 3) if values else None


def _result_output_values(
    report: dict[str, Any],
    field: str,
) -> list[float]:
    values: list[float] = []
    for event in report.get("result_events", []):
        if not isinstance(event, dict):
            continue
        output = event.get("output")
        if not isinstance(output, dict):
            continue
        value = output.get(field)
        if isinstance(value, int | float) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return round(float(value), 3)
    return None


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
