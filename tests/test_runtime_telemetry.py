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
