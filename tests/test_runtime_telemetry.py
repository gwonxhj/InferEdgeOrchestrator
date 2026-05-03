from __future__ import annotations

import json

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
