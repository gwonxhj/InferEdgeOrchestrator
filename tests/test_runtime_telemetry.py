from __future__ import annotations

import json
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.runtime import OrchestratorRuntime


def _config() -> OrchestratorConfig:
    return OrchestratorConfig.from_dict(
        {
            "run": {"name": "test", "overload_backlog_threshold": 2},
            "tasks": [
                {
                    "name": "detector",
                    "model_path": "",
                    "priority": 100,
                    "target_fps": 15,
                    "latency_budget_ms": 80,
                    "queue_size": 3,
                    "drop_policy": "drop_oldest",
                    "worker": "dummy",
                    "simulated_latency_ms": 10,
                },
                {
                    "name": "classifier",
                    "model_path": "",
                    "priority": 10,
                    "target_fps": 5,
                    "latency_budget_ms": 250,
                    "queue_size": 2,
                    "drop_policy": "drop_newest",
                    "worker": "dummy",
                    "simulated_latency_ms": 40,
                },
            ],
        }
    )


def test_runtime_records_execution_drop_latency_and_overload() -> None:
    report = OrchestratorRuntime(_config()).run(frames=5)

    assert report["tasks"]["detector"]["executed"] > 0
    assert report["tasks"]["classifier"]["dropped"] > 0
    assert report["tasks"]["detector"]["mean_latency_ms"] == 10.0
    assert report["overload_events"]


def test_runtime_writes_telemetry_json(tmp_path) -> None:
    output = tmp_path / "telemetry.json"

    OrchestratorRuntime(_config()).run_to_file(frames=3, output=output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["run"]["name"] == "test"
    assert set(data["tasks"]) == {"detector", "classifier"}
    assert "policy_decisions" in data
    assert data["queue_state_summary"]["schema_version"] == (
        "inferedge-orchestrator-queue-state-v1"
    )
    assert data["queue_state_summary"]["overload_backlog_threshold"] == 2
    assert data["worker_health_snapshot"]["schema_version"] == (
        "inferedge-orchestrator-worker-health-v1"
    )
    assert set(data["worker_health_snapshot"]["workers"]) == {"detector", "classifier"}
    assert data["worker_health_snapshot"]["health_state_counts"]
    assert data["runtime_event_summary"]["schema_version"] == (
        "inferedge-orchestrator-runtime-event-summary-v1"
    )
    assert data["runtime_event_timeline"]


def test_runtime_writes_agent_orchestration_summary_contract(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(Path("configs/agent_3_workload_demo.json").read_text(encoding="utf-8"))
    )
    output = tmp_path / "agent_orchestration_summary.json"

    OrchestratorRuntime(config).run_to_file(frames=8, output=output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "inferedge-orchestration-summary-v1"
    summary = data["agent_runtime_summary"]
    assert summary["source_contracts"]["forge_agent_manifest"] == (
        "inferedge-agent-manifest-v1"
    )
    assert summary["source_contracts"]["runtime_agent_result"] == (
        "inferedge-runtime-agent-task-v1"
    )
    assert set(summary["agents"]) == {
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    }
    assert summary["agents"]["vision_agent"]["agent_id"] == "vision_agent"
    assert summary["agents"]["vision_agent"]["runtime_result_path"] == (
        "examples/agent_runtime/vision_runtime_result.json"
    )
    assert summary["totals"]["executed_count"] > 0
    assert summary["totals"]["dropped_count"] > 0
    assert summary["totals"]["policy_decision_count"] > 0
    assert data["policy_decision_log"] == data["policy_decisions"]
    first_schedule = data["schedule_decisions"][0]
    assert first_schedule["agent_id"] == "safety_monitor_agent"
    assert first_schedule["scheduled_priority"] == 100


def test_sustained_high_load_records_timeline_and_policy_reasons(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_3_workload_sustained_high_load.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "sustained_summary.json"

    OrchestratorRuntime(config).run_to_file(frames=16, output=output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["run"]["scenario_mode"] == "sustained_high_load"
    assert data["run"]["frame_interval_ms"] == 5

    sustained = data["sustained_runtime_summary"]
    assert sustained["schema_version"] == (
        "inferedge-orchestrator-sustained-summary-v1"
    )
    assert sustained["queue_depth_sample_count"] == len(data["queue_depth_timeline"])
    assert sustained["latency_sample_count"] == len(data["latency_timeline"])
    assert sustained["max_total_queue_depth"] > 0
    assert sustained["policy_decision_count"] > 0

    first_policy = data["policy_decision_log"][0]
    assert first_policy["decision_reason"] == "queue_backlog_threshold_exceeded"
    assert first_policy["total_backlog_before"] > first_policy["backlog_threshold"]
    assert isinstance(first_policy["queue_depth_snapshot"], dict)

    first_queue_sample = data["queue_depth_timeline"][0]
    assert set(first_queue_sample) == {
        "cycle",
        "stage",
        "queue_depth",
        "total_queue_depth",
    }
    assert data["latency_timeline"]

    queue_summary = data["queue_state_summary"]
    assert queue_summary["queue_pressure_state"] == "overloaded"
    assert queue_summary["queue_pressure_reason"] == (
        "max_total_queue_depth_exceeded_overload_threshold"
    )
    assert queue_summary["max_total_queue_depth"] == sustained["max_total_queue_depth"]
    assert queue_summary["final_queue_depth"]
    assert queue_summary["max_queue_depth_by_task"]
    assert queue_summary["max_pressure_task"] in {
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    }
    assert queue_summary["overload_event_count"] > 0
    assert queue_summary["policy_decision_reasons"] == [
        "queue_backlog_threshold_exceeded"
    ]
    assert queue_summary["drop_reason_counts"]

    worker_health = data["worker_health_snapshot"]["workers"]
    assert worker_health["voice_command_agent"]["health_state"] in {
        "constrained",
        "degraded",
    }
    assert worker_health["voice_command_agent"]["worker"] == "dummy"
    assert worker_health["voice_command_agent"]["queue_pressure_ratio"] is not None
    assert worker_health["voice_command_agent"]["health_reasons"]
    assert worker_health["voice_command_agent"]["primary_health_reason"] in {
        "deadline_missed",
        "fallback_policy_used",
        "frames_dropped",
    }
    assert worker_health["voice_command_agent"]["operation_risk_summary"] in {
        "latency_or_fallback_risk",
        "drop_or_queue_pressure_risk",
    }
    assert worker_health["voice_command_agent"]["queue_pressure_state"] in {
        "at_capacity",
        "elevated",
        "nominal",
    }
    assert worker_health["voice_command_agent"]["drop_rate"] > 0
    assert worker_health["voice_command_agent"]["fallback_rate"] > 0

    event_summary = data["runtime_event_summary"]
    assert event_summary["event_type_counts"]["queue_snapshot"] > 0
    assert event_summary["event_type_counts"]["policy_decision"] > 0
    assert event_summary["event_type_counts"]["drop"] > 0
    assert event_summary["event_type_counts"]["execution"] > 0
    assert event_summary["policy_decision_reason_counts"][
        "queue_backlog_threshold_exceeded"
    ] > 0
    assert event_summary["drop_reason_counts"]
    assert event_summary["queue_pressure_reason_counts"][
        "queue_backlog_threshold_exceeded"
    ] > 0
    assert event_summary["fallback_decision_count"] > 0
    assert event_summary["scheduler_delay_event_count"] > 0
    assert event_summary["latest_event_index"] == len(data["runtime_event_timeline"]) - 1
    assert event_summary["latest_event_type"] in {
        "queue_snapshot",
        "execution",
        "policy_decision",
        "drop",
        "schedule",
        "resource_snapshot",
    }

    runtime_events = data["runtime_event_timeline"]
    assert any(
        event["event_type"] == "queue_snapshot"
        and event["queue_pressure_state"] == "overloaded"
        for event in runtime_events
    )
    assert any(event["event_type"] == "policy_decision" for event in runtime_events)
    assert any(event["event_type"] == "drop" for event in runtime_events)
    assert any(
        event["event_type"] == "execution"
        and event["reason"] in {"completed_within_latency_budget", "deadline_missed"}
        for event in runtime_events
    )
    assert any(
        event["event_type"] == "execution"
        and event.get("scheduler_delay_cycles", 0) > 0
        for event in runtime_events
    )
