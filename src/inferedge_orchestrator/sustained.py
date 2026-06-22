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
    "edgeenv_orchestrator_worker_health_trend",
]
EDGEENV_PRODUCER_LINEAGE_AIGUARD_EVIDENCE_TYPE = (
    "edgeenv_orchestrator_producer_lineage"
)
LATENCY_BUDGET_PROTECTION_SCHEMA = (
    "inferedge-orchestrator-latency-budget-protection-v1"
)
OPERATION_TIMELINE_SUMMARY_SCHEMA = (
    "inferedge-orchestrator-operation-timeline-summary-v1"
)
STALE_DROP_SUMMARY_SCHEMA = "inferedge-orchestrator-stale-drop-summary-v1"
STALE_DROP_REASON_CLASSES = {
    "queue_overflow_drop_oldest": "stale_queue_overflow",
    "load_shedding_backlog_threshold_exceeded": "load_shedding_stale_backlog",
}
WORKER_HEALTH_TREND_SCHEMA = "inferedge-orchestrator-worker-health-trend-v1"
SCHEDULER_FAIRNESS_SUMMARY_SCHEMA = (
    "inferedge-orchestrator-scheduler-fairness-summary-v1"
)
POLICY_PRESSURE_SUMMARY_SCHEMA = (
    "inferedge-orchestrator-policy-pressure-summary-v1"
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
    operation_risk_rollup = report.get("operation_risk_rollup", {})
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
        "operation_timeline_summary": _operation_timeline_summary(report, config),
        "operation_risk_rollup": operation_risk_rollup,
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
    max_total_queue_depth = queue_summary.get(
        "max_total_queue_depth",
        sustained.get("max_total_queue_depth", 0),
    )
    operation = {
        "queue_depth": max_total_queue_depth,
        "max_total_queue_depth": max_total_queue_depth,
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
        "stale_drop_summary": _stale_drop_summary(report),
        "runtime_event_counts": runtime_event_summary.get("event_type_counts", {}),
        "runtime_event_reason_counts": runtime_event_summary.get("reason_counts", {}),
        "runtime_task_event_summary": runtime_event_summary.get(
            "task_event_summary",
            {},
        ),
        "operation_risk_rollup": report.get("operation_risk_rollup", {}),
        "scheduler_fairness_summary": _scheduler_fairness_summary(config, report),
        "tasks_with_deadline_miss": runtime_event_summary.get(
            "tasks_with_deadline_miss",
            [],
        ),
        "tasks_with_fallback": runtime_event_summary.get("tasks_with_fallback", []),
        "tasks_with_scheduler_delay": runtime_event_summary.get(
            "tasks_with_scheduler_delay",
            [],
        ),
        "operation_timeline_summary": _operation_timeline_summary(report, config),
    }
    operation["policy_pressure_summary"] = operation[
        "operation_timeline_summary"
    ]["policy_pressure"]
    operation["latency_budget_protection"] = _latency_budget_protection_context(
        config,
        report,
    )
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
    latency_budget_protection = candidate_context["operation"].get(
        "latency_budget_protection"
    )
    if latency_budget_protection is not None:
        if not isinstance(latency_budget_protection, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "latency_budget_protection must be an object"
            )
        _validate_latency_budget_protection(latency_budget_protection)
    operation_timeline_summary = candidate_context["operation"].get(
        "operation_timeline_summary"
    )
    if operation_timeline_summary is not None:
        if not isinstance(operation_timeline_summary, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary must be an object"
        )
        _validate_operation_timeline_summary(operation_timeline_summary)
    policy_pressure_summary = candidate_context["operation"].get(
        "policy_pressure_summary"
    )
    if policy_pressure_summary is not None:
        if not isinstance(policy_pressure_summary, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "policy_pressure_summary must be an object"
            )
        _validate_policy_pressure_summary(policy_pressure_summary)
    stale_drop_summary = candidate_context["operation"].get("stale_drop_summary")
    if stale_drop_summary is not None:
        if not isinstance(stale_drop_summary, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "stale_drop_summary must be an object"
            )
        _validate_stale_drop_summary(stale_drop_summary)
    scheduler_fairness_summary = candidate_context["operation"].get(
        "scheduler_fairness_summary"
    )
    if scheduler_fairness_summary is not None:
        if not isinstance(scheduler_fairness_summary, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "scheduler_fairness_summary must be an object"
            )
        _validate_scheduler_fairness_summary(scheduler_fairness_summary)
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


def _validate_latency_budget_protection(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != LATENCY_BUDGET_PROTECTION_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.schema_version must be "
            f"{LATENCY_BUDGET_PROTECTION_SCHEMA}"
        )
    if payload.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.operation_context_role must be supplemental"
        )
    if payload.get("scheduler_owner") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.scheduler_owner must be orchestrator"
        )
    if payload.get("decision_owner") != "lab":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.decision_owner must be lab"
        )
    if payload.get("regression_owner") != "edgeenv":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.regression_owner must be edgeenv"
        )
    if payload.get("not_a_deployment_decision") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.not_a_deployment_decision must be true"
        )
    task_budget_context = payload.get("task_budget_context")
    if not isinstance(task_budget_context, dict) or not task_budget_context:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "latency_budget_protection.task_budget_context must be a non-empty "
            "object"
        )
    for field in (
        "protected_task_candidates",
        "tasks_with_latency_budget_risk",
        "risk_reasons",
    ):
        value = payload.get(field)
        if not isinstance(value, list):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"latency_budget_protection.{field} must be a list"
            )


def _validate_operation_timeline_summary(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != OPERATION_TIMELINE_SUMMARY_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.schema_version must be "
            f"{OPERATION_TIMELINE_SUMMARY_SCHEMA}"
        )
    for field in ("sample_counts", "queue", "latency", "policy", "affected_tasks"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"operation_timeline_summary.{field} must be an object"
            )
    review_hints = payload.get("review_hints")
    if (
        not isinstance(review_hints, list)
        or not review_hints
        or not all(isinstance(item, str) and item for item in review_hints)
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.review_hints must be a non-empty "
            "string list"
        )
    stale_drop = payload.get("stale_drop")
    if stale_drop is not None:
        if not isinstance(stale_drop, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary.stale_drop must be an object"
            )
        _validate_stale_drop_summary(stale_drop)
    policy_pressure = payload.get("policy_pressure")
    if policy_pressure is not None:
        if not isinstance(policy_pressure, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary.policy_pressure must be an object"
            )
        _validate_policy_pressure_summary(policy_pressure)
    scheduler_fairness = payload.get("scheduler_fairness")
    if scheduler_fairness is not None:
        if not isinstance(scheduler_fairness, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary.scheduler_fairness must be an object"
            )
        _validate_scheduler_fairness_summary(scheduler_fairness)
    worker_health_trend = payload.get("worker_health_trend")
    if worker_health_trend is not None:
        if not isinstance(worker_health_trend, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary.worker_health_trend must be an object"
            )
        _validate_worker_health_trend(worker_health_trend)


def _validate_worker_health_trend(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != WORKER_HEALTH_TREND_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.worker_health_trend.schema_version must be "
            f"{WORKER_HEALTH_TREND_SCHEMA}"
        )
    if payload.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.worker_health_trend."
            "operation_context_role must be supplemental"
        )
    if payload.get("scheduler_owner") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.worker_health_trend.scheduler_owner "
            "must be orchestrator"
        )
    if payload.get("decision_owner") != "lab":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.worker_health_trend.decision_owner "
            "must be lab"
        )
    if payload.get("not_a_deployment_decision") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "operation_timeline_summary.worker_health_trend."
            "not_a_deployment_decision must be true"
        )
    for field in (
        "health_state_counts",
        "tasks_by_health_state",
        "task_health_context",
    ):
        if not isinstance(payload.get(field), dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "operation_timeline_summary.worker_health_trend."
                f"{field} must be an object"
            )


def _validate_policy_pressure_summary(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != POLICY_PRESSURE_SUMMARY_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.schema_version must be "
            f"{POLICY_PRESSURE_SUMMARY_SCHEMA}"
        )
    if payload.get("role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.role must be supplemental"
        )
    if payload.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.operation_context_role must be supplemental"
        )
    if payload.get("scheduler_owner") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.scheduler_owner must be orchestrator"
        )
    if payload.get("decision_owner") != "lab":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.decision_owner must be lab"
        )
    if payload.get("not_a_deployment_decision") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.not_a_deployment_decision must be true"
        )
    for field in (
        "decision_count",
        "fallback_decision_count",
        "max_total_backlog_before",
        "max_backlog_over_threshold",
    ):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"policy_pressure_summary.{field} must be a non-negative integer"
            )
    if not isinstance(payload.get("decision_reason_counts"), dict):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.decision_reason_counts must be an object"
        )
    for field in (
        "limited_tasks",
        "protected_tasks",
        "fallback_tasks",
        "pressure_markers",
    ):
        value = payload.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"policy_pressure_summary.{field} must be a string list"
            )
    thresholds = payload.get("backlog_thresholds")
    if not isinstance(thresholds, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0
        for item in thresholds
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "policy_pressure_summary.backlog_thresholds must be a "
            "non-negative integer list"
        )


def _validate_stale_drop_summary(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != STALE_DROP_SUMMARY_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.schema_version must be "
            f"{STALE_DROP_SUMMARY_SCHEMA}"
        )
    if payload.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.operation_context_role must be supplemental"
        )
    if payload.get("scheduler_owner") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.scheduler_owner must be orchestrator"
        )
    if payload.get("decision_owner") != "lab":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.decision_owner must be lab"
        )
    if payload.get("not_a_deployment_decision") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.not_a_deployment_decision must be true"
        )
    for field in ("stale_drop_count", "total_drop_count"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"stale_drop_summary.{field} must be a non-negative integer"
            )
    for field in ("stale_drop_reasons", "task_counts"):
        value = payload.get(field)
        if not isinstance(value, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"stale_drop_summary.{field} must be an object"
            )
    tasks = payload.get("tasks_with_stale_drop")
    if not isinstance(tasks, list) or not all(
        isinstance(item, str) and item for item in tasks
    ):
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "stale_drop_summary.tasks_with_stale_drop must be a string list"
        )


def _validate_scheduler_fairness_summary(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEDULER_FAIRNESS_SUMMARY_SCHEMA:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.schema_version must be "
            f"{SCHEDULER_FAIRNESS_SUMMARY_SCHEMA}"
        )
    if payload.get("operation_context_role") != "supplemental":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.operation_context_role must be supplemental"
        )
    if payload.get("scheduler_owner") != "orchestrator":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.scheduler_owner must be orchestrator"
        )
    if payload.get("decision_owner") != "lab":
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.decision_owner must be lab"
        )
    if payload.get("not_a_deployment_decision") is not True:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.not_a_deployment_decision must be true"
        )
    for field in (
        "protected_high_priority_tasks",
        "tasks_with_starvation_risk",
        "tasks_with_scheduler_delay",
        "tasks_with_degradation",
    ):
        value = payload.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                f"scheduler_fairness_summary.{field} must be a string list"
            )
    task_fairness = payload.get("task_fairness")
    if not isinstance(task_fairness, dict) or not task_fairness:
        raise ValueError(
            "edgeenv_runtime_telemetry_feed.candidate_context.operation."
            "scheduler_fairness_summary.task_fairness must be a non-empty object"
        )
    for task_name, task_context in task_fairness.items():
        if not isinstance(task_name, str) or not task_name:
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "scheduler_fairness_summary.task_fairness keys must be strings"
            )
        if not isinstance(task_context, dict):
            raise ValueError(
                "edgeenv_runtime_telemetry_feed.candidate_context.operation."
                "scheduler_fairness_summary.task_fairness values must be objects"
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


def _latency_budget_protection_context(
    config: OrchestratorConfig,
    report: dict[str, Any],
) -> dict[str, Any]:
    runtime_event_summary = report.get("runtime_event_summary", {})
    queue_summary = report.get("queue_state_summary", {})
    workers = report.get("worker_health_snapshot", {}).get("workers", {})
    task_event_summary = runtime_event_summary.get("task_event_summary", {})
    if not isinstance(runtime_event_summary, dict):
        runtime_event_summary = {}
    if not isinstance(queue_summary, dict):
        queue_summary = {}
    if not isinstance(workers, dict):
        workers = {}
    if not isinstance(task_event_summary, dict):
        task_event_summary = {}

    task_budget_context: dict[str, Any] = {}
    for task in config.tasks:
        worker = workers.get(task.name, {})
        if not isinstance(worker, dict):
            worker = {}
        task_events = task_event_summary.get(task.name, {})
        if not isinstance(task_events, dict):
            task_events = {}
        task_budget_context[task.name] = {
            "agent_id": task.agent_id,
            "agent_type": task.agent_type,
            "priority": task.priority,
            "latency_budget_ms": task.latency_budget_ms,
            "executed_count": worker.get("executed_count", 0),
            "deadline_missed_count": worker.get("deadline_missed_count", 0),
            "fallback_count": worker.get("fallback_count", 0),
            "dropped_count": worker.get("dropped_count", 0),
            "scheduler_delay_event_count": task_events.get(
                "scheduler_delay_event_count",
                0,
            ),
            "max_scheduler_delay_cycles": task_events.get(
                "max_scheduler_delay_cycles",
                0,
            ),
            "max_queue_wait_ms": task_events.get("max_queue_wait_ms", 0.0),
            "health_state": worker.get("health_state"),
            "operation_risk_summary": worker.get("operation_risk_summary"),
            "queue_pressure_state": worker.get("queue_pressure_state"),
        }

    tasks_with_latency_budget_risk = _tasks_with_latency_budget_risk(
        task_budget_context
    )
    return {
        "schema_version": LATENCY_BUDGET_PROTECTION_SCHEMA,
        "operation_context_role": "supplemental",
        "scheduler_owner": "orchestrator",
        "decision_owner": "lab",
        "regression_owner": "edgeenv",
        "not_a_deployment_decision": True,
        "source": "runtime_event_summary+worker_health_snapshot+queue_state_summary",
        "protected_task_candidates": _protected_task_candidates(
            config,
            task_budget_context,
        ),
        "tasks_with_latency_budget_risk": tasks_with_latency_budget_risk,
        "risk_reasons": _latency_budget_risk_reasons(
            runtime_event_summary,
            queue_summary,
            task_budget_context,
        ),
        "first_read": (
            "review_latency_budget_context"
            if tasks_with_latency_budget_risk
            else "latency_budget_context_preserved"
        ),
        "task_budget_context": task_budget_context,
    }


def _protected_task_candidates(
    config: OrchestratorConfig,
    task_budget_context: dict[str, Any],
) -> list[str]:
    if not config.tasks:
        return []
    highest_priority = max(task.priority for task in config.tasks)
    candidates: list[str] = []
    for task in config.tasks:
        context = task_budget_context.get(task.name, {})
        if not isinstance(context, dict):
            continue
        if task.priority == highest_priority and _positive_int(
            context.get("executed_count")
        ):
            candidates.append(task.name)
    return candidates


def _tasks_with_latency_budget_risk(task_budget_context: dict[str, Any]) -> list[str]:
    risky: list[str] = []
    for task_name, context in task_budget_context.items():
        if not isinstance(context, dict):
            continue
        if (
            _positive_int(context.get("deadline_missed_count"))
            or _positive_int(context.get("fallback_count"))
            or _positive_int(context.get("scheduler_delay_event_count"))
        ):
            risky.append(task_name)
    return risky


def _latency_budget_risk_reasons(
    runtime_event_summary: dict[str, Any],
    queue_summary: dict[str, Any],
    task_budget_context: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if _positive_int(runtime_event_summary.get("deadline_missed_count")):
        reasons.append("deadline_miss_present")
    if _positive_int(runtime_event_summary.get("scheduler_delay_event_count")):
        reasons.append("scheduler_delay_present")
    if _positive_int(runtime_event_summary.get("fallback_decision_count")):
        reasons.append("fallback_used")
    if queue_summary.get("queue_pressure_state") == "overloaded":
        reasons.append("queue_pressure_overloaded")
    if _positive_int(queue_summary.get("overload_event_count")):
        reasons.append("load_shedding_applied")
    if not reasons and any(
        _positive_int(context.get("dropped_count"))
        for context in task_budget_context.values()
        if isinstance(context, dict)
    ):
        reasons.append("drop_pressure_present")
    return reasons


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_negative_int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


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


def _operation_timeline_summary(
    report: dict[str, Any],
    config: OrchestratorConfig | None = None,
) -> dict[str, Any]:
    queue_summary = _dict_value(report.get("queue_state_summary"))
    runtime_event_summary = _dict_value(report.get("runtime_event_summary"))
    worker_health = _dict_value(report.get("worker_health_snapshot"))
    workers = _dict_value(worker_health.get("workers"))
    stale_drop = _stale_drop_summary(report)
    return {
        "schema_version": OPERATION_TIMELINE_SUMMARY_SCHEMA,
        "source": (
            "queue_depth_timeline+latency_timeline+policy_decision_log+"
            "runtime_event_summary"
        ),
        "sample_counts": {
            "queue_depth": len(_dict_list(report.get("queue_depth_timeline"))),
            "latency": len(_dict_list(report.get("latency_timeline"))),
            "policy_decision": len(_dict_list(report.get("policy_decision_log"))),
            "runtime_event": runtime_event_summary.get("event_count", 0),
        },
        "queue": {
            "max_total_queue_depth": queue_summary.get("max_total_queue_depth", 0),
            "average_total_queue_depth": queue_summary.get(
                "average_total_queue_depth",
                0.0,
            ),
            "overload_backlog_threshold": queue_summary.get(
                "overload_backlog_threshold",
                0,
            ),
            "pressure_state": queue_summary.get("queue_pressure_state"),
            "pressure_reason": queue_summary.get("queue_pressure_reason"),
            "max_pressure_task": queue_summary.get("max_pressure_task"),
            "max_queue_depth_by_task": queue_summary.get("max_queue_depth_by_task", {}),
        },
        "latency": _latency_timeline_summary(report),
        "policy": _policy_timeline_summary(report),
        "policy_pressure": _policy_pressure_summary(report),
        "stale_drop": stale_drop,
        "scheduler_fairness": _scheduler_fairness_summary(config, report),
        "worker_health_trend": _worker_health_trend_summary(report),
        "affected_tasks": {
            "deadline_missed": _string_list(
                runtime_event_summary.get("tasks_with_deadline_miss")
            ),
            "fallback": _string_list(runtime_event_summary.get("tasks_with_fallback")),
            "scheduler_delay": _string_list(
                runtime_event_summary.get("tasks_with_scheduler_delay")
            ),
            "stale_drop": stale_drop["tasks_with_stale_drop"],
            "degraded": _worker_names_with_health_state(workers, "degraded"),
            "constrained": _worker_names_with_health_state(workers, "constrained"),
        },
        "review_hints": _operation_timeline_review_hints(
            queue_summary,
            runtime_event_summary,
            stale_drop,
        ),
    }


def _latency_timeline_summary(report: dict[str, Any]) -> dict[str, Any]:
    events = _dict_list(report.get("latency_timeline"))
    max_latency_ms = 0.0
    max_queue_wait_ms = 0.0
    max_queue_wait_ms_by_task: dict[str, float] = {}
    tasks_with_deadline_miss: list[str] = []
    for event in events:
        task = event.get("task")
        latency_ms = _number_value(event.get("latency_ms"))
        queue_wait_ms = _number_value(event.get("queue_wait_ms"))
        if latency_ms is not None:
            max_latency_ms = max(max_latency_ms, latency_ms)
        if queue_wait_ms is not None:
            max_queue_wait_ms = max(max_queue_wait_ms, queue_wait_ms)
            if isinstance(task, str) and task:
                max_queue_wait_ms_by_task[task] = max(
                    max_queue_wait_ms_by_task.get(task, 0.0),
                    queue_wait_ms,
                )
        if bool(event.get("deadline_missed")) and isinstance(task, str) and task:
            if task not in tasks_with_deadline_miss:
                tasks_with_deadline_miss.append(task)
    return {
        "sample_count": len(events),
        "max_latency_ms": round(max_latency_ms, 3),
        "max_queue_wait_ms": round(max_queue_wait_ms, 3),
        "max_queue_wait_ms_by_task": {
            task: round(value, 3)
            for task, value in max_queue_wait_ms_by_task.items()
        },
        "tasks_with_deadline_miss": tasks_with_deadline_miss,
    }


def _worker_health_trend_summary(report: dict[str, Any]) -> dict[str, Any]:
    worker_health = _dict_value(report.get("worker_health_snapshot"))
    workers = _dict_value(worker_health.get("workers"))
    runtime_event_summary = _dict_value(report.get("runtime_event_summary"))
    task_event_summary = _dict_value(runtime_event_summary.get("task_event_summary"))
    health_state_counts = _dict_value(worker_health.get("health_state_counts"))
    tasks_by_health_state: dict[str, list[str]] = {}
    task_health_context: dict[str, dict[str, Any]] = {}

    for task_name, worker in sorted(workers.items()):
        if not isinstance(task_name, str) or not isinstance(worker, dict):
            continue
        health_state = str(worker.get("health_state", "unknown"))
        tasks_by_health_state.setdefault(health_state, []).append(task_name)
        task_events = _dict_value(task_event_summary.get(task_name))
        task_health_context[task_name] = {
            "health_state": health_state,
            "primary_health_reason": worker.get("primary_health_reason"),
            "health_reasons": _string_list(worker.get("health_reasons")),
            "executed_count": _non_negative_int_value(worker.get("executed_count")),
            "dropped_count": _non_negative_int_value(worker.get("dropped_count")),
            "deadline_missed_count": _non_negative_int_value(
                worker.get("deadline_missed_count")
            ),
            "fallback_count": _non_negative_int_value(worker.get("fallback_count")),
            "drop_rate": _number_value(worker.get("drop_rate")) or 0.0,
            "deadline_miss_rate": _number_value(worker.get("deadline_miss_rate"))
            or 0.0,
            "fallback_rate": _number_value(worker.get("fallback_rate")) or 0.0,
            "scheduler_delay_event_count": _non_negative_int_value(
                task_events.get("scheduler_delay_event_count")
            ),
            "resource_degraded_event_count": _non_negative_int_value(
                task_events.get("resource_degraded_event_count")
            ),
        }

    return {
        "schema_version": WORKER_HEALTH_TREND_SCHEMA,
        "operation_context_role": "supplemental",
        "scheduler_owner": "orchestrator",
        "decision_owner": "lab",
        "not_a_deployment_decision": True,
        "source": "worker_health_snapshot+runtime_event_summary",
        "health_state_counts": health_state_counts,
        "tasks_by_health_state": tasks_by_health_state,
        "task_health_context": task_health_context,
        "degraded_workers": _string_list(worker_health.get("degraded_workers")),
        "constrained_workers": _string_list(worker_health.get("constrained_workers")),
        "review_hints": _worker_health_trend_review_hints(
            tasks_by_health_state,
            task_health_context,
        ),
        "interpretation": (
            "Worker health trend is supplemental operation evidence. "
            "Lab remains the final deployment decision owner."
        ),
    }


def _worker_health_trend_review_hints(
    tasks_by_health_state: dict[str, list[str]],
    task_health_context: dict[str, dict[str, Any]],
) -> list[str]:
    hints: list[str] = []
    if tasks_by_health_state.get("degraded"):
        hints.append("review_degraded_workers")
    if tasks_by_health_state.get("constrained"):
        hints.append("review_constrained_workers")
    if any(
        context.get("scheduler_delay_event_count", 0) > 0
        for context in task_health_context.values()
    ):
        hints.append("review_worker_scheduler_delay")
    if any(
        context.get("fallback_count", 0) > 0
        for context in task_health_context.values()
    ):
        hints.append("review_worker_fallback")
    return hints or ["worker_health_nominal"]


def _policy_timeline_summary(report: dict[str, Any]) -> dict[str, Any]:
    decisions = _dict_list(report.get("policy_decision_log"))
    return {
        "decision_count": len(decisions),
        "decision_reasons": _policy_decision_reasons(report),
        "first_decision": (
            _compact_policy_decision(decisions[0]) if decisions else None
        ),
        "latest_decision": (
            _compact_policy_decision(decisions[-1]) if decisions else None
        ),
    }


def _policy_pressure_summary(report: dict[str, Any]) -> dict[str, Any]:
    decisions = _dict_list(report.get("policy_decision_log"))
    runtime_event_summary = _dict_value(report.get("runtime_event_summary"))
    limited_tasks: list[str] = []
    protected_tasks: list[str] = []
    fallback_tasks: list[str] = []
    reason_counts: dict[str, int] = {}
    max_total_backlog_before = 0
    max_backlog_over_threshold = 0
    backlog_thresholds: list[int] = []

    for decision in decisions:
        limited_task = decision.get("limited_task")
        if isinstance(limited_task, str) and limited_task:
            if limited_task not in limited_tasks:
                limited_tasks.append(limited_task)
            if (
                bool(decision.get("fallback_used"))
                and limited_task not in fallback_tasks
            ):
                fallback_tasks.append(limited_task)
        protected_task = decision.get("protected_task")
        if isinstance(protected_task, str) and protected_task not in protected_tasks:
            protected_tasks.append(protected_task)
        reason = decision.get("decision_reason") or decision.get("reason")
        if isinstance(reason, str) and reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        total_backlog = _non_negative_int_value(
            decision.get("total_backlog_before")
        )
        threshold = _non_negative_int_value(decision.get("backlog_threshold"))
        max_total_backlog_before = max(max_total_backlog_before, total_backlog)
        if threshold:
            if threshold not in backlog_thresholds:
                backlog_thresholds.append(threshold)
            max_backlog_over_threshold = max(
                max_backlog_over_threshold,
                max(total_backlog - threshold, 0),
            )

    pressure_markers = _policy_pressure_markers(
        decision_count=len(decisions),
        fallback_tasks=fallback_tasks,
        limited_tasks=limited_tasks,
        max_backlog_over_threshold=max_backlog_over_threshold,
        runtime_event_summary=runtime_event_summary,
    )
    return {
        "schema_version": POLICY_PRESSURE_SUMMARY_SCHEMA,
        "role": "supplemental",
        "operation_context_role": "supplemental",
        "scheduler_owner": "orchestrator",
        "decision_owner": "lab",
        "not_a_deployment_decision": True,
        "source": "policy_decision_log+runtime_event_summary",
        "first_read": (
            "review_policy_pressure_context"
            if pressure_markers
            else "policy_pressure_nominal"
        ),
        "decision_count": len(decisions),
        "decision_reason_counts": reason_counts,
        "limited_tasks": limited_tasks,
        "protected_tasks": protected_tasks,
        "fallback_tasks": fallback_tasks,
        "fallback_decision_count": _non_negative_int_value(
            runtime_event_summary.get("fallback_decision_count")
        ),
        "backlog_thresholds": backlog_thresholds,
        "max_total_backlog_before": max_total_backlog_before,
        "max_backlog_over_threshold": max_backlog_over_threshold,
        "pressure_markers": pressure_markers,
        "interpretation": (
            "Policy pressure is supplemental evidence showing which scheduler "
            "decisions limited or protected work under backlog pressure; Lab "
            "remains the final deployment decision owner."
        ),
    }


def _policy_pressure_markers(
    *,
    decision_count: int,
    fallback_tasks: list[str],
    limited_tasks: list[str],
    max_backlog_over_threshold: int,
    runtime_event_summary: dict[str, Any],
) -> list[str]:
    markers: list[str] = []
    if decision_count:
        markers.append("policy_decision_present")
    if max_backlog_over_threshold > 0:
        markers.append("backlog_exceeded_threshold")
    if fallback_tasks:
        markers.append("fallback_policy_used")
    if limited_tasks:
        markers.append("workload_limited_by_policy")
    if _positive_int(runtime_event_summary.get("scheduler_delay_event_count")):
        markers.append("scheduler_delay_present")
    return markers


def _stale_drop_summary(report: dict[str, Any]) -> dict[str, Any]:
    events = _dict_list(report.get("drop_events"))
    stale_reason_counts: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    reason_classes: list[str] = []
    latest_event: dict[str, Any] | None = None

    for event in events:
        reason = event.get("reason")
        task = event.get("task")
        if not isinstance(reason, str) or reason not in STALE_DROP_REASON_CLASSES:
            continue
        if not isinstance(task, str) or not task:
            continue
        stale_reason_counts[reason] = stale_reason_counts.get(reason, 0) + 1
        task_counts[task] = task_counts.get(task, 0) + 1
        reason_class = STALE_DROP_REASON_CLASSES[reason]
        if reason_class not in reason_classes:
            reason_classes.append(reason_class)
        latest_event = {
            key: event.get(key)
            for key in (
                "task",
                "agent_id",
                "agent_type",
                "frame_id",
                "reason",
            )
            if key in event
        }
        latest_event["stale_drop_class"] = reason_class

    stale_drop_count = sum(stale_reason_counts.values())
    total_drop_count = len(events)
    return {
        "schema_version": STALE_DROP_SUMMARY_SCHEMA,
        "operation_context_role": "supplemental",
        "scheduler_owner": "orchestrator",
        "decision_owner": "lab",
        "not_a_deployment_decision": True,
        "source": "drop_events",
        "first_read": (
            "review_stale_drop_context"
            if stale_drop_count
            else "stale_drop_context_nominal"
        ),
        "stale_drop_count": stale_drop_count,
        "total_drop_count": total_drop_count,
        "stale_drop_rate": (
            round(stale_drop_count / total_drop_count, 3)
            if total_drop_count
            else 0.0
        ),
        "stale_drop_reasons": stale_reason_counts,
        "stale_drop_reason_classes": reason_classes,
        "tasks_with_stale_drop": list(task_counts),
        "task_counts": task_counts,
        "latest_stale_drop_event": latest_event,
        "interpretation": (
            "Queued stale/backlog work was dropped as scheduler evidence only; "
            "Lab remains the final deployment decision owner."
        ),
    }


def _compact_policy_decision(decision: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: decision.get(key)
        for key in (
            "event",
            "decision_reason",
            "protected_task",
            "protected_agent_id",
            "limited_task",
            "agent_id",
            "agent_type",
            "dropped_frames",
            "total_backlog_before",
            "backlog_threshold",
            "fallback_used",
        )
        if key in decision
    }
    queue_depth = decision.get("queue_depth_snapshot")
    if isinstance(queue_depth, dict):
        compact["queue_depth_snapshot"] = dict(queue_depth)
    return compact


def _operation_timeline_review_hints(
    queue_summary: dict[str, Any],
    runtime_event_summary: dict[str, Any],
    stale_drop_summary: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    if queue_summary.get("queue_pressure_state") == "overloaded":
        hints.append("review_queue_pressure")
    if _positive_int(runtime_event_summary.get("scheduler_delay_event_count")):
        hints.append("review_scheduler_delay")
    if _positive_int(runtime_event_summary.get("deadline_missed_count")):
        hints.append("review_deadline_miss")
    if _positive_int(runtime_event_summary.get("fallback_decision_count")):
        hints.append("review_fallback_use")
    if _positive_int(queue_summary.get("overload_event_count")):
        hints.append("review_load_shedding")
    if _positive_int(stale_drop_summary.get("stale_drop_count")):
        hints.append("review_stale_drop")
    return hints or ["operation_timeline_nominal"]


def _scheduler_fairness_summary(
    config: OrchestratorConfig | None,
    report: dict[str, Any],
) -> dict[str, Any]:
    runtime_event_summary = _dict_value(report.get("runtime_event_summary"))
    task_event_summary = _dict_value(runtime_event_summary.get("task_event_summary"))
    worker_health = _dict_value(report.get("worker_health_snapshot"))
    workers = _dict_value(worker_health.get("workers"))
    task_names = _configured_task_names(config, workers, task_event_summary)
    task_fairness: dict[str, Any] = {}
    tasks_with_starvation_risk: list[str] = []
    tasks_with_scheduler_delay: list[str] = []
    tasks_with_degradation: list[str] = []

    for task_name in task_names:
        worker = _dict_value(workers.get(task_name))
        task_events = _dict_value(task_event_summary.get(task_name))
        task_config = _task_config_by_name(config, task_name)
        context = _task_fairness_context(task_name, task_config, worker, task_events)
        task_fairness[task_name] = context
        if context["starvation_risk"]:
            tasks_with_starvation_risk.append(task_name)
        if _positive_int(context.get("scheduler_delay_event_count")):
            tasks_with_scheduler_delay.append(task_name)
        if context.get("health_state") in {"constrained", "degraded"}:
            tasks_with_degradation.append(task_name)

    return {
        "schema_version": SCHEDULER_FAIRNESS_SUMMARY_SCHEMA,
        "operation_context_role": "supplemental",
        "scheduler_owner": "orchestrator",
        "decision_owner": "lab",
        "not_a_deployment_decision": True,
        "source": "task_config+worker_health_snapshot+runtime_event_summary",
        "protected_high_priority_tasks": _protected_high_priority_tasks(
            config,
            task_fairness,
        ),
        "tasks_with_starvation_risk": tasks_with_starvation_risk,
        "tasks_with_scheduler_delay": tasks_with_scheduler_delay,
        "tasks_with_degradation": tasks_with_degradation,
        "first_read": (
            "review_scheduler_fairness_context"
            if tasks_with_starvation_risk or tasks_with_scheduler_delay
            else "scheduler_fairness_nominal"
        ),
        "task_fairness": task_fairness,
        "interpretation": (
            "Scheduler fairness is supplemental operation evidence for "
            "reviewing protected, delayed, degraded, or starved workloads; "
            "Lab remains the final deployment decision owner."
        ),
    }


def _configured_task_names(
    config: OrchestratorConfig | None,
    workers: dict[str, Any],
    task_event_summary: dict[str, Any],
) -> list[str]:
    names: list[str] = []
    if config is not None:
        for task in config.tasks:
            if task.name not in names:
                names.append(task.name)
    for source in (workers, task_event_summary):
        for task_name in source:
            if isinstance(task_name, str) and task_name and task_name not in names:
                names.append(task_name)
    return names


def _task_config_by_name(
    config: OrchestratorConfig | None,
    task_name: str,
) -> TaskConfig | None:
    if config is None:
        return None
    for task in config.tasks:
        if task.name == task_name:
            return task
    return None


def _task_fairness_context(
    task_name: str,
    task: TaskConfig | None,
    worker: dict[str, Any],
    task_events: dict[str, Any],
) -> dict[str, Any]:
    executed_count = _non_negative_int_value(worker.get("executed_count"))
    dropped_count = _non_negative_int_value(worker.get("dropped_count"))
    fallback_count = _non_negative_int_value(worker.get("fallback_count"))
    scheduler_delay_count = _non_negative_int_value(
        task_events.get("scheduler_delay_event_count")
    )
    max_delay_cycles = _non_negative_int_value(
        task_events.get("max_scheduler_delay_cycles")
    )
    starvation_reasons = _starvation_reasons(
        executed_count=executed_count,
        dropped_count=dropped_count,
        fallback_count=fallback_count,
        scheduler_delay_count=scheduler_delay_count,
        max_delay_cycles=max_delay_cycles,
        health_state=worker.get("health_state"),
    )
    context = {
        "agent_id": task.agent_id if task else worker.get("agent_id"),
        "agent_type": task.agent_type if task else worker.get("agent_type"),
        "priority": task.priority if task else worker.get("priority"),
        "latency_budget_ms": task.latency_budget_ms if task else None,
        "executed_count": executed_count,
        "dropped_count": dropped_count,
        "fallback_count": fallback_count,
        "scheduler_delay_event_count": scheduler_delay_count,
        "max_scheduler_delay_cycles": max_delay_cycles,
        "health_state": worker.get("health_state"),
        "operation_risk_summary": worker.get("operation_risk_summary"),
        "starvation_risk": bool(starvation_reasons),
        "starvation_reasons": starvation_reasons,
    }
    if task is None:
        context["task_name"] = task_name
    return context


def _starvation_reasons(
    *,
    executed_count: int,
    dropped_count: int,
    fallback_count: int,
    scheduler_delay_count: int,
    max_delay_cycles: int,
    health_state: Any,
) -> list[str]:
    reasons: list[str] = []
    if executed_count == 0 and dropped_count > 0:
        reasons.append("dropped_without_execution")
    if scheduler_delay_count > 0:
        reasons.append("scheduler_delay_present")
    if max_delay_cycles >= 3:
        reasons.append("multi_cycle_scheduler_delay")
    if fallback_count > 0:
        reasons.append("fallback_policy_used")
    if health_state == "degraded":
        reasons.append("worker_degraded")
    return reasons


def _protected_high_priority_tasks(
    config: OrchestratorConfig | None,
    task_fairness: dict[str, Any],
) -> list[str]:
    if config is None or not config.tasks:
        return []
    highest_priority = max(task.priority for task in config.tasks)
    protected: list[str] = []
    for task in config.tasks:
        context = task_fairness.get(task.name, {})
        if not isinstance(context, dict):
            continue
        if task.priority == highest_priority and _positive_int(
            context.get("executed_count")
        ):
            protected.append(task.name)
    return protected


def _worker_names_with_health_state(
    workers: dict[str, Any],
    health_state: str,
) -> list[str]:
    names: list[str] = []
    for name, worker in workers.items():
        if isinstance(name, str) and isinstance(worker, dict):
            if worker.get("health_state") == health_state:
                names.append(name)
    return names


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


def _number_value(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


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
