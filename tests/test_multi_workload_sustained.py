from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.cli import main
from inferedge_orchestrator.sustained import (
    EDGEENV_AIGUARD_EVIDENCE_CANDIDATES,
    EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS,
    EDGEENV_CANDIDATE_CONTEXT_PATH,
    EDGEENV_HISTORY_COVERAGE_PATH,
    EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE,
    EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT,
    EDGEENV_TELEMETRY_FEED_SCHEMA,
    EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY,
    LATENCY_BUDGET_PROTECTION_SCHEMA,
    MULTI_WORKLOAD_SCHEMA,
    OPERATION_TIMELINE_SUMMARY_SCHEMA,
    STALE_DROP_SUMMARY_SCHEMA,
    apply_device_local_input_overrides,
    load_tegrastats_timeline,
    validate_edgeenv_runtime_telemetry_feed,
    write_edgeenv_runtime_telemetry_feed,
    write_multi_workload_sustained,
    write_process_resource_snapshot,
)


def test_multi_workload_sustained_config_loads_profiles() -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )

    assert config.name == "agent_multi_workload_sustained_local"
    assert [task.agent_id for task in config.tasks] == [
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    ]
    assert [task.worker_options["runtime_loop"] for task in config.tasks if task.worker_options] == [
        "safety_monitor_loop",
        "yolo_detection_loop",
        "whisper_command_burst",
    ]
    assert config.tasks[2].worker_options is not None
    assert all(
        task.worker_options and task.worker_options["implementation"] == "local_profile_adapter"
        for task in config.tasks
    )
    assert config.tasks[2].worker_options["ingress_profile"] == (
        "fastapi_concurrent_request"
    )


def test_run_multi_workload_sustained_writes_profile_summary(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained.json"
    tegrastats = tmp_path / "tegrastats.log"
    tegrastats.write_text(
        "RAM 2048/7771MB SWAP 0/3885MB CPU [12%@1510] "
        "GR3D_FREQ 42% cpu@45.5C gpu@44.0C\n",
        encoding="utf-8",
    )

    report = write_multi_workload_sustained(
        config,
        output=output,
        frames=8,
        tegrastats_log=tegrastats,
    )

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == report
    summary = report["multi_workload_sustained_summary"]
    assert summary["schema_version"] == MULTI_WORKLOAD_SCHEMA
    assert summary["scenario_mode"] == "sustained_high_load"
    assert summary["scenario_label"] == "producer_backed_sustained_high_load"
    assert summary["scenario_category"] == "sustained"
    assert "Producer-backed sustained" in summary["scenario_description"]
    assert report["run"]["scenario_label"] == "producer_backed_sustained_high_load"
    assert report["sustained_runtime_summary"]["scenario_category"] == "sustained"
    signals = summary["observed_runtime_signals"]
    assert signals["max_total_queue_depth"] > 0
    assert signals["tegrastats_sample_count"] == 1
    assert signals["local_profile_adapter_count"] > 0
    assert signals["local_profile_elapsed_ms"] > 0
    assert set(signals["local_profile_kinds"]) == {
        "safety_monitor_loop",
        "vision_frame_loop",
        "voice_command_burst",
    }
    timeline = summary["operation_timeline_summary"]
    assert timeline["schema_version"] == OPERATION_TIMELINE_SUMMARY_SCHEMA
    assert timeline["sample_counts"] == {
        "queue_depth": len(report["queue_depth_timeline"]),
        "latency": len(report["latency_timeline"]),
        "policy_decision": len(report["policy_decision_log"]),
        "runtime_event": report["runtime_event_summary"]["event_count"],
    }
    assert timeline["queue"]["max_total_queue_depth"] == (
        report["queue_state_summary"]["max_total_queue_depth"]
    )
    assert timeline["queue"]["pressure_state"] == (
        report["queue_state_summary"]["queue_pressure_state"]
    )
    assert timeline["queue"]["pressure_reason"] == (
        report["queue_state_summary"]["queue_pressure_reason"]
    )
    assert timeline["latency"]["sample_count"] == len(report["latency_timeline"])
    assert timeline["latency"]["max_latency_ms"] >= 0
    assert timeline["latency"]["max_queue_wait_ms"] > 0
    assert timeline["policy"]["decision_count"] == len(report["policy_decision_log"])
    assert timeline["policy"]["decision_reasons"] == [
        "queue_backlog_threshold_exceeded"
    ]
    assert timeline["policy"]["first_decision"]["decision_reason"] == (
        "queue_backlog_threshold_exceeded"
    )
    assert timeline["policy"]["first_decision"]["queue_depth_snapshot"]
    stale_drop = timeline["stale_drop"]
    assert stale_drop["schema_version"] == STALE_DROP_SUMMARY_SCHEMA
    assert stale_drop["operation_context_role"] == "supplemental"
    assert stale_drop["scheduler_owner"] == "orchestrator"
    assert stale_drop["decision_owner"] == "lab"
    assert stale_drop["not_a_deployment_decision"] is True
    assert stale_drop["first_read"] == "review_stale_drop_context"
    assert stale_drop["stale_drop_count"] > 0
    assert stale_drop["total_drop_count"] == signals["dropped_count"]
    assert stale_drop["stale_drop_rate"] > 0
    assert stale_drop["stale_drop_reasons"]
    assert stale_drop["tasks_with_stale_drop"]
    assert stale_drop["task_counts"]
    assert stale_drop["latest_stale_drop_event"]["reason"] in {
        "queue_overflow_drop_oldest",
        "load_shedding_backlog_threshold_exceeded",
    }
    assert "Lab remains the final deployment decision owner" in (
        stale_drop["interpretation"]
    )
    assert "voice_command_agent" in timeline["affected_tasks"]["scheduler_delay"]
    assert "voice_command_agent" in timeline["affected_tasks"]["fallback"]
    assert "voice_command_agent" in timeline["affected_tasks"]["degraded"]
    assert timeline["affected_tasks"]["stale_drop"] == (
        stale_drop["tasks_with_stale_drop"]
    )
    assert "review_queue_pressure" in timeline["review_hints"]
    assert "review_scheduler_delay" in timeline["review_hints"]
    assert "review_stale_drop" in timeline["review_hints"]
    risk_rollup = report["operation_risk_rollup"]
    assert risk_rollup["schema_version"] == (
        "inferedge-orchestrator-operation-risk-rollup-v1"
    )
    assert risk_rollup["operation_context_role"] == "supplemental"
    assert risk_rollup["scheduler_owner"] == "orchestrator"
    assert risk_rollup["decision_owner"] == "lab"
    assert risk_rollup["not_a_deployment_decision"] is True
    assert risk_rollup["risk_level"] == "review"
    assert risk_rollup["first_read"] == "review_operation_risk_context"
    assert "queue_pressure_overloaded" in risk_rollup["primary_reasons"]
    assert "scheduler_delay_present" in risk_rollup["primary_reasons"]
    assert "fallback_used" in risk_rollup["primary_reasons"]
    assert "voice_command_agent" in risk_rollup["affected_tasks"]["scheduler_delay"]
    assert "voice_command_agent" in risk_rollup["affected_tasks"]["fallback"]
    assert "voice_command_agent" in risk_rollup["affected_tasks"]["degraded"]
    assert report["sustained_runtime_summary"]["operation_risk_rollup"] == (
        risk_rollup
    )
    assert summary["operation_risk_rollup"] == risk_rollup

    profiles = {profile["agent_id"]: profile for profile in summary["workload_profiles"]}
    assert profiles["vision_agent"]["runtime_loop"] == "yolo_detection_loop"
    assert profiles["vision_agent"]["implementation"] == "local_profile_adapter"
    assert profiles["vision_agent"]["profile_work_units"] == 24000
    assert profiles["voice_command_agent"]["runtime_loop"] == "whisper_command_burst"
    assert profiles["voice_command_agent"]["ingress_profile"] == (
        "fastapi_concurrent_request"
    )
    outputs = [event["output"] for event in report["result_events"]]
    assert any(output.get("profile_kind") == "vision_frame_loop" for output in outputs)
    assert any(output.get("profile_kind") == "voice_command_burst" for output in outputs)
    assert any(output.get("profile_kind") == "safety_monitor_loop" for output in outputs)
    assert report["tegrastats_timeline"]["summary"]["max_gpu_percent"] == 42
    assert report["tegrastats_timeline"]["summary"]["max_temperature_c"] == 45.5
    feed = report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["role"] == "orchestrator_operation_context_for_edgeenv"
    assert feed["source_repository"] == EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY
    assert feed["artifact_role"] == EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE
    assert feed["producer_contract"] == EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT
    assert feed["not_a_regression_judgement"] is True
    assert feed["not_a_comparability_gate"] is True
    assert feed["decision_owner"] == "lab"
    assert feed["regression_owner"] == "edgeenv"
    candidate = feed["candidate_context"]
    assert candidate["telemetry_source"] == (
        "inferedge_orchestrator_operation_summary"
    )
    assert candidate["queue_depth"] == signals["max_total_queue_depth"]
    assert candidate["operation"]["max_total_queue_depth"] == (
        signals["max_total_queue_depth"]
    )
    assert candidate["operation"]["deadline_missed_count"] == (
        report["agent_runtime_summary"]["totals"]["deadline_missed_count"]
    )
    assert candidate["operation"]["fallback_count"] == (
        report["agent_runtime_summary"]["totals"]["fallback_count"]
    )
    assert candidate["operation"]["policy_decision_reasons"] == (
        report["queue_state_summary"]["policy_decision_reasons"]
    )
    assert candidate["operation"]["runtime_task_event_summary"] == (
        report["runtime_event_summary"]["task_event_summary"]
    )
    assert candidate["operation"]["tasks_with_scheduler_delay"] == (
        report["runtime_event_summary"]["tasks_with_scheduler_delay"]
    )
    assert candidate["operation"]["tasks_with_fallback"] == (
        report["runtime_event_summary"]["tasks_with_fallback"]
    )
    assert candidate["operation"]["operation_timeline_summary"] == timeline
    assert candidate["operation"]["stale_drop_summary"] == stale_drop
    assert candidate["operation"]["operation_risk_rollup"] == risk_rollup
    protection = candidate["operation"]["latency_budget_protection"]
    assert protection["schema_version"] == LATENCY_BUDGET_PROTECTION_SCHEMA
    assert protection["operation_context_role"] == "supplemental"
    assert protection["scheduler_owner"] == "orchestrator"
    assert protection["decision_owner"] == "lab"
    assert protection["regression_owner"] == "edgeenv"
    assert protection["not_a_deployment_decision"] is True
    assert protection["first_read"] == "review_latency_budget_context"
    assert protection["protected_task_candidates"] == ["safety_monitor_agent"]
    assert set(protection["tasks_with_latency_budget_risk"]) >= {
        "vision_agent",
        "voice_command_agent",
    }
    assert "scheduler_delay_present" in protection["risk_reasons"]
    assert "load_shedding_applied" in protection["risk_reasons"]
    voice_budget = protection["task_budget_context"]["voice_command_agent"]
    assert voice_budget["priority"] == 50
    assert voice_budget["latency_budget_ms"] == 120.0
    assert voice_budget["max_scheduler_delay_cycles"] == (
        report["runtime_event_summary"]["task_event_summary"][
            "voice_command_agent"
        ]["max_scheduler_delay_cycles"]
    )
    assert candidate["resource"]["source"] == "tegrastats_timeline"
    assert candidate["resource"]["gpu_temperature"] == 44.0
    assert candidate["resource"]["cpu_temperature"] == 45.5
    assert candidate["resource"]["gpu_percent"] == 42
    assert feed["edgeenv_mapping_hint"]["copy_candidate_context_to"] == (
        EDGEENV_CANDIDATE_CONTEXT_PATH
    )
    assert feed["edgeenv_mapping_hint"]["operation_context_role"] == "supplemental"
    assert feed["edgeenv_mapping_hint"]["coverage_summary_owner"] == "edgeenv"
    assert feed["edgeenv_mapping_hint"]["coverage_summary_path"] == (
        EDGEENV_HISTORY_COVERAGE_PATH
    )
    assert feed["edgeenv_mapping_hint"]["candidate_context_required_fields"] == (
        EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS
    )
    assert feed["edgeenv_mapping_hint"]["aiguard_evidence_candidates"] == (
        EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
    )


def test_write_edgeenv_runtime_telemetry_feed_exports_standalone_artifact(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_device_local.json"
    feed_output = tmp_path / "edgeenv_runtime_telemetry_feed.json"

    report = write_multi_workload_sustained(
        config,
        output=output,
        frames=8,
        edgeenv_feed_output=feed_output,
    )

    feed = json.loads(feed_output.read_text(encoding="utf-8"))
    assert feed == report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["role"] == "orchestrator_operation_context_for_edgeenv"
    assert feed["source_repository"] == EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY
    assert feed["artifact_role"] == EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE
    assert feed["producer_contract"] == EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT
    assert feed["source"] == "orchestration_summary"
    assert feed["not_a_regression_judgement"] is True
    assert feed["not_a_comparability_gate"] is True
    assert feed["decision_owner"] == "lab"
    assert feed["regression_owner"] == "edgeenv"
    assert feed["candidate_context"]["run_id"] == report["run"]["name"]
    assert feed["candidate_context"]["operation"]["queue_depth"] == (
        report["queue_state_summary"]["max_total_queue_depth"]
    )
    assert feed["candidate_context"]["operation"]["max_total_queue_depth"] == (
        report["queue_state_summary"]["max_total_queue_depth"]
    )
    assert feed["edgeenv_mapping_hint"]["copy_candidate_context_to"] == (
        EDGEENV_CANDIDATE_CONTEXT_PATH
    )
    assert feed["edgeenv_mapping_hint"]["coverage_summary_owner"] == "edgeenv"
    assert feed["edgeenv_mapping_hint"]["coverage_summary_path"] == (
        EDGEENV_HISTORY_COVERAGE_PATH
    )
    assert feed["edgeenv_mapping_hint"]["candidate_context_required_fields"] == (
        EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS
    )
    assert feed["edgeenv_mapping_hint"]["aiguard_evidence_candidates"] == (
        EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
    )
    producer = feed["candidate_context"]["producer"]
    assert producer["operation_context_role"] == "supplemental"
    assert producer["device_local_producer_sources"] == [
        "resource_snapshot_fixture",
        "image_file",
        "fastapi_request_fixture",
    ]
    assert producer["producer_sources_by_task"] == {
        "safety_monitor_agent": ["resource_snapshot_fixture"],
        "vision_agent": ["image_file"],
        "voice_command_agent": ["fastapi_request_fixture"],
    }
    assert producer["producer_stage_by_task"] == {
        "safety_monitor_agent": "device_local_starter",
        "vision_agent": "device_local_starter",
        "voice_command_agent": "device_local_starter",
    }
    assert producer["producer_event_count"] > 0
    assert producer["device_local_event_count"] > 0
    assert producer["device_local_task_count"] == 3
    validate_edgeenv_runtime_telemetry_feed(
        feed,
        require_device_local_producer=True,
    )


def test_write_edgeenv_runtime_telemetry_feed_requires_feed_block(tmp_path) -> None:
    with pytest.raises(
        ValueError,
        match="missing edgeenv_runtime_telemetry_feed",
    ):
        write_edgeenv_runtime_telemetry_feed({}, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_mapping_contract(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["edgeenv_mapping_hint"][
        "coverage_summary_owner"
    ] = "orchestrator"

    with pytest.raises(
        ValueError,
        match="coverage_summary_owner must be edgeenv",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_producer_markers(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["artifact_role"] = (
        "lab-owned-deployment-risk-report"
    )

    with pytest.raises(
        ValueError,
        match="artifact_role must be orchestrator-supplemental-operation-context",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_mapping_required_fields(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["edgeenv_mapping_hint"][
        "candidate_context_required_fields"
    ] = ["run_id", "operation", "resource"]

    with pytest.raises(
        ValueError,
        match="candidate_context_required_fields missing",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_aiguard_evidence_candidates(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["edgeenv_mapping_hint"][
        "aiguard_evidence_candidates"
    ] = ["runtime_queue_overload"]

    with pytest.raises(
        ValueError,
        match="aiguard_evidence_candidates missing",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_candidate_operation_context(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["candidate_context"].pop("operation")

    with pytest.raises(
        ValueError,
        match="candidate_context must include operation",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_latency_budget_marker(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["candidate_context"]["operation"][
        "latency_budget_protection"
    ]["decision_owner"] = "orchestrator"

    with pytest.raises(
        ValueError,
        match="latency_budget_protection.decision_owner must be lab",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_operation_timeline_schema(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["candidate_context"]["operation"][
        "operation_timeline_summary"
    ]["schema_version"] = "wrong"

    with pytest.raises(
        ValueError,
        match="operation_timeline_summary.schema_version must be",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_write_edgeenv_runtime_telemetry_feed_requires_stale_drop_schema(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    report["edgeenv_runtime_telemetry_feed"]["candidate_context"]["operation"][
        "stale_drop_summary"
    ]["scheduler_owner"] = "lab"

    with pytest.raises(
        ValueError,
        match="stale_drop_summary.scheduler_owner must be orchestrator",
    ):
        write_edgeenv_runtime_telemetry_feed(report, tmp_path / "feed.json")


def test_validate_edgeenv_runtime_telemetry_feed_requires_device_local_producer(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    feed = report["edgeenv_runtime_telemetry_feed"]
    feed["candidate_context"].pop("producer")

    with pytest.raises(
        ValueError,
        match="candidate_context.producer is required",
    ):
        validate_edgeenv_runtime_telemetry_feed(
            feed,
            require_device_local_producer=True,
        )


def test_validate_edgeenv_runtime_telemetry_feed_rejects_incomplete_producer(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    producer = report["edgeenv_runtime_telemetry_feed"]["candidate_context"][
        "producer"
    ]
    producer["device_local_producer_sources"] = []

    with pytest.raises(
        ValueError,
        match="device_local_producer_sources must be a non-empty string list",
    ):
        validate_edgeenv_runtime_telemetry_feed(
            report["edgeenv_runtime_telemetry_feed"],
            require_device_local_producer=True,
        )


def test_validate_edgeenv_runtime_telemetry_feed_rejects_unmapped_device_local_source(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    producer = report["edgeenv_runtime_telemetry_feed"]["candidate_context"][
        "producer"
    ]
    producer["producer_sources_by_task"] = {
        "vision_agent": ["image_file"],
    }

    with pytest.raises(
        ValueError,
        match="device_local_producer_sources must also appear",
    ):
        validate_edgeenv_runtime_telemetry_feed(
            report["edgeenv_runtime_telemetry_feed"],
            require_device_local_producer=True,
        )


def test_validate_edgeenv_runtime_telemetry_feed_rejects_bad_producer_stage_map(
    tmp_path,
) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    producer = report["edgeenv_runtime_telemetry_feed"]["candidate_context"][
        "producer"
    ]
    producer["producer_stage_by_task"] = {"vision_agent": ""}

    with pytest.raises(
        ValueError,
        match="producer_stage_by_task values must be non-empty strings",
    ):
        validate_edgeenv_runtime_telemetry_feed(
            report["edgeenv_runtime_telemetry_feed"],
            require_device_local_producer=True,
        )


def test_cli_run_multi_workload_sustained_writes_edgeenv_feed_output(
    tmp_path,
    capsys,
) -> None:
    output = tmp_path / "multi_workload_sustained_device_local.json"
    feed_output = tmp_path / "edgeenv_runtime_telemetry_feed.json"

    exit_code = main(
        [
            "run-multi-workload-sustained",
            "--config",
            "configs/agent_multi_workload_sustained_device_local.json",
            "--output",
            str(output),
            "--edgeenv-feed-output",
            str(feed_output),
            "--frames",
            "8",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "wrote EdgeEnv telemetry feed" in captured.out
    assert "multi-workload sustained: mode=device_local" in captured.out
    assert "deadline_missed=" in captured.out
    assert "queue_pressure=" in captured.out
    assert "operation-timeline: review_hints=" in captured.out
    assert "scheduler_delay=" in captured.out
    assert "stale_drop=" in captured.out
    assert "stale_drop_tasks=" in captured.out
    assert "max_queue_wait_ms=" in captured.out
    report = json.loads(output.read_text(encoding="utf-8"))
    feed = json.loads(feed_output.read_text(encoding="utf-8"))
    assert feed == report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA


def test_run_multi_workload_sustained_profiles_local_image_input(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_vision_file.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_vision_file.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert config.input_source == "image"
    assert config.input_path == "examples/inputs/vision_frame.ppm"
    assert output.exists()
    summary = report["multi_workload_sustained_summary"]
    signals = summary["observed_runtime_signals"]
    assert "vision_frame_loop" in signals["local_profile_kinds"]

    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
        and event["output"].get("profile_kind") == "vision_frame_loop"
    ]
    assert vision_outputs
    first_output = vision_outputs[0]
    assert first_output["producer_source"] == "image_file"
    assert first_output["frame_source"] == "image"
    assert first_output["input_path"] == "examples/inputs/vision_frame.ppm"
    assert first_output["input_bytes"] > 0
    assert first_output["sampled_bytes"] > 0
    assert first_output["input_digest"]
    assert first_output["contention_signal"] == "vision_file_cpu_profile"


def test_run_multi_workload_sustained_profiles_voice_ingress_fixture(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_voice_ingress.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_voice_ingress.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    voice_task = next(
        task for task in config.tasks if task.name == "voice_command_agent"
    )
    assert voice_task.worker_options is not None
    assert voice_task.worker_options["ingress_payload_path"] == (
        "examples/inputs/voice_ingress_requests.json"
    )

    voice_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "voice_command_agent"
        and event["output"].get("profile_kind") == "voice_command_burst"
    ]
    assert voice_outputs
    first_output = voice_outputs[0]
    assert first_output["producer_source"] == "fastapi_request_fixture"
    assert first_output["ingress_payload_path"] == (
        "examples/inputs/voice_ingress_requests.json"
    )
    assert first_output["available_request_count"] == 3
    assert first_output["ingress_request_count"] == 2
    assert first_output["selected_request_ids"]
    assert first_output["selected_routes"] == ["/agent/command", "/agent/command"]
    assert first_output["selected_methods"] == ["POST", "POST"]
    assert first_output["request_digest"]
    assert first_output["command_char_count"] > 0
    assert first_output["contention_signal"] == "fastapi_request_cpu_profile"


def test_run_multi_workload_sustained_profiles_safety_resource_fixture(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_safety_resource.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_safety_resource.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    safety_task = next(
        task for task in config.tasks if task.name == "safety_monitor_agent"
    )
    assert safety_task.worker_options is not None
    assert safety_task.worker_options["resource_snapshot_path"] == (
        "examples/inputs/safety_resource_snapshots.json"
    )

    safety_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "safety_monitor_agent"
        and event["output"].get("profile_kind") == "safety_monitor_loop"
    ]
    assert safety_outputs
    first_output = safety_outputs[0]
    assert first_output["producer_source"] == "resource_snapshot_fixture"
    assert first_output["resource_snapshot_path"] == (
        "examples/inputs/safety_resource_snapshots.json"
    )
    assert first_output["resource_snapshot_id"]
    assert first_output["cpu_percent"] >= 0
    assert first_output["memory_used_ratio"] >= 0
    assert first_output["temperature_c"] >= 0
    assert first_output["resource_degradation_score"] >= 0
    assert first_output["resource_digest"]
    assert first_output["contention_signal"] == "resource_monitor_profile"
    assert "cpu_percent" in first_output["sampled_metrics"]
    assert "fallback_signal" in first_output["sampled_metrics"]


def test_run_multi_workload_sustained_device_local_starter(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_device_local.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    assert config.name == "agent_multi_workload_sustained_device_local"
    assert config.scenario_mode == "device_local"
    summary = report["multi_workload_sustained_summary"]
    assert summary["scenario_mode"] == "device_local"
    assert summary["scenario_label"] == "device_local_sustained_starter"
    assert summary["scenario_category"] == "device_local"
    assert "Device-local sustained starter" in summary["scenario_description"]
    assert "device-local sustained validation starter" in summary["evidence_scope"]
    assert "live device-local" in summary["next_validation_step"]

    signals = summary["observed_runtime_signals"]
    assert set(signals["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert signals["producer_source_count"] > 0
    assert signals["device_local_producer_count"] == signals["producer_source_count"]

    profiles = {profile["agent_id"]: profile for profile in summary["workload_profiles"]}
    assert profiles["vision_agent"]["device_local_validation"] is True
    assert profiles["voice_command_agent"]["producer_stage"] == "device_local_starter"
    assert profiles["safety_monitor_agent"]["producer_stage"] == "device_local_starter"
    queue_summary = report["queue_state_summary"]
    assert queue_summary["device_local_task_count"] == 3
    assert set(queue_summary["device_local_tasks"]) == {
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    }
    assert set(queue_summary["device_local_producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert queue_summary["queue_pressure_reason"] != (
        "overload_threshold_not_configured"
    )
    assert queue_summary["producer_sources_by_task"]["vision_agent"] == ["image_file"]
    workers = report["worker_health_snapshot"]["workers"]
    assert workers["vision_agent"]["device_local_validation"] is True
    assert workers["vision_agent"]["producer_stage"] == "device_local_starter"
    assert "image_file" in workers["vision_agent"]["producer_sources"]
    assert workers["vision_agent"]["producer_context_summary"] == {
        "device_local_validation": True,
        "producer_stage": "device_local_starter",
        "producer_sources": ["image_file"],
        "producer_event_count": workers["vision_agent"]["producer_event_count"],
    }
    assert workers["voice_command_agent"]["producer_sources"] == [
        "fastapi_request_fixture"
    ]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "resource_snapshot_fixture"
    ]
    execution_events = [
        event
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    ]
    assert any(
        event["producer_context"].get("producer_source") == "image_file"
        for event in execution_events
    )
    assert any(
        event["producer_context"].get("producer_source") == "fastapi_request_fixture"
        for event in execution_events
    )
    assert any(
        event["producer_context"].get("producer_source") == "resource_snapshot_fixture"
        for event in execution_events
    )
    event_summary = report["runtime_event_summary"]
    assert set(event_summary["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert event_summary["producer_event_count"] == len(execution_events)
    assert event_summary["device_local_event_count"] > 0
    feed = report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["scenario_mode"] == "device_local"
    assert "producer" in feed["candidate_context"]["available_sections"]
    assert set(feed["candidate_context"]["producer"]["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert set(
        feed["candidate_context"]["producer"]["device_local_producer_sources"]
    ) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert feed["candidate_context"]["producer"]["producer_stage_by_task"] == {
        "safety_monitor_agent": "device_local_starter",
        "vision_agent": "device_local_starter",
        "voice_command_agent": "device_local_starter",
    }
    assert feed["candidate_context"]["producer"]["operation_context_role"] == (
        "supplemental"
    )
    assert feed["candidate_context"]["operation"]["queue_pressure_state"] == (
        queue_summary["queue_pressure_state"]
    )
    assert feed["candidate_context"]["operation"]["queue_depth"] == (
        queue_summary["max_total_queue_depth"]
    )
    risk_rollup = feed["candidate_context"]["operation"]["operation_risk_rollup"]
    assert risk_rollup == report["operation_risk_rollup"]
    assert risk_rollup["decision_owner"] == "lab"
    assert risk_rollup["not_a_deployment_decision"] is True
    assert risk_rollup["risk_level"] == "review"
    assert "queue_pressure_overloaded" in risk_rollup["primary_reasons"]
    protection = feed["candidate_context"]["operation"]["latency_budget_protection"]
    assert protection["schema_version"] == LATENCY_BUDGET_PROTECTION_SCHEMA
    assert protection["operation_context_role"] == "supplemental"
    assert protection["decision_owner"] == "lab"
    assert protection["scheduler_owner"] == "orchestrator"
    assert protection["regression_owner"] == "edgeenv"
    assert protection["not_a_deployment_decision"] is True
    assert "safety_monitor_agent" in protection["protected_task_candidates"]
    assert "voice_command_agent" in protection["task_budget_context"]
    assert protection["task_budget_context"]["voice_command_agent"][
        "latency_budget_ms"
    ] == 120.0
    assert feed["candidate_context"]["resource"]["source"] == (
        "result_events_resource_snapshot"
    )
    assert feed["candidate_context"]["resource"]["temperature_c"] == 69.2
    assert feed["candidate_context"]["resource"]["ram_used_mb"] == 6144.0
    assert "runtime_queue_overload" in feed["edgeenv_mapping_hint"][
        "aiguard_evidence_candidates"
    ]
    assert "runtime_thermal_instability" in feed["edgeenv_mapping_hint"][
        "aiguard_evidence_candidates"
    ]
    assert feed["edgeenv_mapping_hint"]["coverage_summary_owner"] == "edgeenv"
    assert feed["edgeenv_mapping_hint"]["coverage_summary_path"] == (
        EDGEENV_HISTORY_COVERAGE_PATH
    )
    assert feed["edgeenv_mapping_hint"]["candidate_context_required_fields"] == (
        EDGEENV_CANDIDATE_CONTEXT_REQUIRED_FIELDS
    )


def test_device_local_input_overrides_use_local_paths(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    image = tmp_path / "frame.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    requests = tmp_path / "requests.json"
    requests.write_text(
        json.dumps(
            [
                {
                    "request_id": "local-command-1",
                    "method": "POST",
                    "path": "/agent/command",
                    "command": "inspect local backlog",
                }
            ]
        ),
        encoding="utf-8",
    )
    resources = tmp_path / "resources.json"
    resources.write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "snapshot_id": "local-process-1",
                        "cpu_percent": 37.5,
                        "memory_used_mb": 256,
                        "memory_total_mb": 1024,
                        "temperature_c": 42.0,
                        "queue_depth": 4,
                        "fallback_count": 1,
                        "deadline_missed_count": 1,
                        "dropped_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    overridden = apply_device_local_input_overrides(
        config,
        vision_input=image,
        voice_ingress_payload=requests,
        resource_snapshot=resources,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_overrides.json",
        frames=4,
    )

    assert overridden.input_source == "image"
    assert overridden.input_path == str(image)
    outputs = [event["output"] for event in report["result_events"]]
    assert any(output.get("input_path") == str(image) for output in outputs)
    assert any(
        output.get("ingress_payload_path") == str(requests) for output in outputs
    )
    assert any(
        output.get("resource_snapshot_path") == str(resources) for output in outputs
    )
    summary = report["multi_workload_sustained_summary"]
    signals = summary["observed_runtime_signals"]
    assert set(signals["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    workers = report["worker_health_snapshot"]["workers"]
    assert "image_file" in workers["vision_agent"]["producer_sources"]
    assert workers["vision_agent"]["producer_stage"] == "device_local_cli_override"
    assert workers["vision_agent"]["primary_health_reason"]
    assert workers["vision_agent"]["operation_risk_summary"]
    assert workers["vision_agent"]["producer_context_summary"][
        "producer_stage"
    ] == "device_local_cli_override"
    assert workers["voice_command_agent"]["producer_sources"] == [
        "fastapi_request_fixture"
    ]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "resource_snapshot_fixture"
    ]
    queue_summary = report["queue_state_summary"]
    assert set(queue_summary["device_local_producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert queue_summary["producer_sources_by_task"]["voice_command_agent"] == [
        "fastapi_request_fixture"
    ]
    event_summary = report["runtime_event_summary"]
    assert set(event_summary["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert event_summary["device_local_event_count"] > 0
    assert any(
        event["producer_context"].get("input_path") == str(image)
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    )
    feed = report["edgeenv_runtime_telemetry_feed"]
    producer_context = feed["candidate_context"]["producer"]
    assert producer_context["producer_stage_by_task"] == {
        "safety_monitor_agent": "device_local_cli_override",
        "vision_agent": "device_local_cli_override",
        "voice_command_agent": "device_local_cli_override",
    }
    assert producer_context["producer_sources_by_task"]["vision_agent"] == [
        "image_file"
    ]
    assert producer_context["device_local_event_count"] > 0


def test_cli_device_local_overrides_write_edgeenv_feed_output(
    tmp_path,
    capsys,
) -> None:
    output = tmp_path / "device_local_cli_override.json"
    feed_output = tmp_path / "edgeenv_runtime_telemetry_feed.json"
    image = tmp_path / "frame.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    requests = tmp_path / "requests.json"
    requests.write_text(
        json.dumps(
            [
                {
                    "request_id": "local-command-1",
                    "method": "POST",
                    "path": "/agent/command",
                    "command": "inspect local backlog",
                }
            ]
        ),
        encoding="utf-8",
    )
    resources = tmp_path / "resources.json"
    resources.write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "snapshot_id": "local-process-1",
                        "cpu_percent": 37.5,
                        "memory_used_mb": 256,
                        "memory_total_mb": 1024,
                        "temperature_c": 42.0,
                        "queue_depth": 4,
                        "fallback_count": 1,
                        "deadline_missed_count": 1,
                        "dropped_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "run-multi-workload-sustained",
            "--config",
            "configs/agent_multi_workload_sustained_device_local.json",
            "--output",
            str(output),
            "--edgeenv-feed-output",
            str(feed_output),
            "--frames",
            "4",
            "--vision-input",
            str(image),
            "--voice-ingress-payload",
            str(requests),
            "--resource-snapshot",
            str(resources),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "wrote EdgeEnv telemetry feed" in captured.out
    assert "multi-workload sustained: mode=device_local" in captured.out
    assert "deadline_missed=" in captured.out
    assert "queue_pressure=" in captured.out
    assert "operation-timeline: review_hints=" in captured.out
    assert "scheduler_delay=" in captured.out
    assert "stale_drop=" in captured.out
    assert "stale_drop_tasks=" in captured.out
    assert "max_queue_wait_ms=" in captured.out
    report = json.loads(output.read_text(encoding="utf-8"))
    feed = json.loads(feed_output.read_text(encoding="utf-8"))
    assert feed == report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["source_repository"] == EDGEENV_TELEMETRY_FEED_SOURCE_REPOSITORY
    assert feed["artifact_role"] == EDGEENV_TELEMETRY_FEED_ARTIFACT_ROLE
    assert feed["producer_contract"] == EDGEENV_TELEMETRY_FEED_PRODUCER_CONTRACT
    assert feed["not_a_regression_judgement"] is True
    assert feed["not_a_comparability_gate"] is True
    assert feed["decision_owner"] == "lab"
    assert feed["regression_owner"] == "edgeenv"
    candidate = feed["candidate_context"]
    assert candidate["telemetry_source"] == (
        "inferedge_orchestrator_operation_summary"
    )
    assert "producer" in candidate["available_sections"]
    assert candidate["producer"]["producer_stage_by_task"] == {
        "safety_monitor_agent": "device_local_cli_override",
        "vision_agent": "device_local_cli_override",
        "voice_command_agent": "device_local_cli_override",
    }
    assert set(candidate["producer"]["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert candidate["producer"]["operation_context_role"] == "supplemental"
    assert candidate["operation"]["queue_depth"] == (
        report["queue_state_summary"]["max_total_queue_depth"]
    )
    assert candidate["operation"]["max_total_queue_depth"] == (
        report["queue_state_summary"]["max_total_queue_depth"]
    )
    protection = candidate["operation"]["latency_budget_protection"]
    assert protection["schema_version"] == LATENCY_BUDGET_PROTECTION_SCHEMA
    assert protection["not_a_deployment_decision"] is True
    assert protection["task_budget_context"]["voice_command_agent"][
        "max_queue_wait_ms"
    ] >= 0
    assert candidate["resource"]["temperature_c"] == 42.0
    assert feed["edgeenv_mapping_hint"]["coverage_summary_owner"] == "edgeenv"
    assert feed["edgeenv_mapping_hint"]["coverage_summary_path"] == (
        EDGEENV_HISTORY_COVERAGE_PATH
    )
    assert feed["edgeenv_mapping_hint"]["aiguard_evidence_candidates"] == (
        EDGEENV_AIGUARD_EVIDENCE_CANDIDATES
    )


def test_device_local_vision_input_can_use_image_sequence_directory(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    sequence_dir = tmp_path / "frames"
    sequence_dir.mkdir()
    first = sequence_dir / "frame_001.ppm"
    second = sequence_dir / "frame_002.ppm"
    first.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    second.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")

    overridden = apply_device_local_input_overrides(
        config,
        vision_input=sequence_dir,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_image_sequence.json",
        frames=4,
    )

    assert overridden.input_source == "image_sequence"
    assert overridden.input_path == str(sequence_dir)
    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
    ]
    assert vision_outputs
    assert {output["producer_source"] for output in vision_outputs} == {
        "image_sequence_file"
    }
    observed_paths = {output["input_path"] for output in vision_outputs}
    assert str(first) in observed_paths
    assert str(second) in observed_paths
    assert {output["sequence_root"] for output in vision_outputs} == {
        str(sequence_dir)
    }
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert "image_sequence_file" in signals["producer_sources"]
    assert signals["device_local_producer_count"] == signals["producer_source_count"]


def test_device_local_vision_can_run_optional_onnx_probe(
    tmp_path,
    monkeypatch,
) -> None:
    np = pytest.importorskip("numpy")

    class FakeInput:
        name = "images"
        shape = [1, 3, 2, 2]

    class FakeSession:
        def __init__(self, model_path, providers):
            self.model_path = model_path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def get_providers(self):
            return self.providers

        def run(self, output_names, feed):
            assert output_names is None
            assert list(feed) == ["images"]
            assert feed["images"].shape == (1, 3, 2, 2)
            return [np.ones((1, 1, 6), dtype=np.float32)]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=FakeSession),
    )

    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    image = tmp_path / "frame.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    model = tmp_path / "vision_probe.onnx"
    model.write_bytes(b"fake onnx model for mocked session")
    overridden = apply_device_local_input_overrides(
        config,
        vision_input=image,
        vision_onnx_model=model,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_vision_onnx_probe.json",
        frames=4,
    )

    vision_profile = next(
        profile
        for profile in report["multi_workload_sustained_summary"]["workload_profiles"]
        if profile["agent_id"] == "vision_agent"
    )
    assert vision_profile["vision_inference_backend"] == "onnxruntime"
    assert vision_profile["vision_model_path"] == str(model)
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert signals["vision_inference_backend_count"] == 1
    assert signals["vision_inference_backends"] == ["onnxruntime"]

    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
    ]
    assert vision_outputs
    first_output = vision_outputs[0]
    assert first_output["producer_source"] == "image_file"
    assert first_output["contention_signal"] == "vision_onnxruntime_probe"
    assert first_output["vision_inference_backend"] == "onnxruntime"
    assert first_output["vision_inference_mode"] == "probe"
    assert first_output["vision_model_path"] == str(model)
    assert first_output["vision_provider"] == "CPUExecutionProvider"
    assert first_output["vision_input_shapes"] == {"images": [1, 3, 2, 2]}
    assert first_output["vision_output_shapes"] == [[1, 1, 6]]
    assert first_output["vision_output_count"] == 1
    assert first_output["vision_probe_elapsed_ms"] >= 0


def test_process_resource_snapshot_can_feed_device_local_safety(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    snapshot = write_process_resource_snapshot(tmp_path / "process_snapshot.json")
    overridden = apply_device_local_input_overrides(
        config,
        resource_snapshot=snapshot,
        resource_snapshot_source="process_resource_snapshot",
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_process_snapshot.json",
        frames=4,
    )

    safety_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "safety_monitor_agent"
    ]
    assert safety_outputs
    assert safety_outputs[0]["producer_source"] == "process_resource_snapshot"
    assert safety_outputs[0]["resource_snapshot_path"] == str(snapshot)
    assert safety_outputs[0]["resource_snapshot_id"] == "device_local_process_0"
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert "process_resource_snapshot" in signals["producer_sources"]
    workers = report["worker_health_snapshot"]["workers"]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "process_resource_snapshot"
    ]
    assert any(
        event["producer_context"].get("producer_source") == "process_resource_snapshot"
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    )


def test_missing_tegrastats_log_is_explicit() -> None:
    timeline = load_tegrastats_timeline(None)

    assert timeline["source"] == "not_provided"
    assert timeline["sample_count"] == 0
    assert timeline["samples"] == []
