from __future__ import annotations

import pytest

from inferedge_orchestrator.config import OrchestratorConfig, TaskConfig


def test_task_config_validates_required_policy_values() -> None:
    task = TaskConfig.from_dict(
        {
            "name": "detector",
            "model_path": "models/detector.onnx",
            "priority": 100,
            "target_fps": 15,
            "latency_budget_ms": 80,
            "queue_size": 4,
            "drop_policy": "drop_oldest",
            "worker": "dummy",
        }
    )

    assert task.name == "detector"
    assert task.priority == 100


def test_orchestrator_config_rejects_duplicate_task_names() -> None:
    task = {
        "name": "detector",
        "model_path": "",
        "priority": 1,
        "target_fps": 1,
        "latency_budget_ms": 1,
        "queue_size": 1,
    }

    with pytest.raises(ValueError, match="unique"):
        OrchestratorConfig.from_dict({"tasks": [task, task]})
