from __future__ import annotations

import json
from pathlib import Path

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
    assert task.engine_path is None
    assert task.worker_options is None


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


def test_tensorrt_worker_requires_engine_path() -> None:
    task = {
        "name": "detector_trt",
        "model_path": "models/detector.onnx",
        "priority": 100,
        "target_fps": 15,
        "latency_budget_ms": 80,
        "queue_size": 4,
        "drop_policy": "drop_oldest",
        "worker": "tensorrt",
    }

    with pytest.raises(ValueError, match="requires engine_path"):
        TaskConfig.from_dict(task)


def test_tensorrt_worker_accepts_engine_path_and_worker_options() -> None:
    task = TaskConfig.from_dict(
        {
            "name": "detector_trt",
            "model_path": "models/detector.onnx",
            "engine_path": "models/detector.plan",
            "priority": 100,
            "target_fps": 15,
            "latency_budget_ms": 80,
            "queue_size": 4,
            "drop_policy": "drop_oldest",
            "worker": "tensorrt",
            "worker_options": {
                "precision": "fp16",
                "warmup_runs": 5,
                "device_id": 0,
                "allow_engine_build": False,
                "providers": ["TensorrtExecutionProvider", "CUDAExecutionProvider"],
            },
        }
    )

    assert task.worker == "tensorrt"
    assert task.engine_path == "models/detector.plan"
    assert task.worker_options is not None
    assert task.worker_options["allow_engine_build"] is False
    assert task.worker_options["providers"] == [
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
    ]


def test_worker_options_must_be_mapping() -> None:
    with pytest.raises(ValueError, match="worker_options must be a mapping"):
        TaskConfig.from_dict(
            {
                "name": "detector",
                "model_path": "",
                "priority": 1,
                "target_fps": 1,
                "latency_budget_ms": 1,
                "queue_size": 1,
                "worker_options": ["not", "a", "mapping"],
            }
        )


def test_worker_option_providers_must_be_string_list() -> None:
    with pytest.raises(ValueError, match="providers must be a list of strings"):
        TaskConfig.from_dict(
            {
                "name": "detector",
                "model_path": "",
                "priority": 1,
                "target_fps": 1,
                "latency_budget_ms": 1,
                "queue_size": 1,
                "worker_options": {"providers": ["CPUExecutionProvider", 1]},
            }
        )


def test_worker_option_allow_engine_build_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="allow_engine_build must be a boolean"):
        TaskConfig.from_dict(
            {
                "name": "detector",
                "model_path": "",
                "priority": 1,
                "target_fps": 1,
                "latency_budget_ms": 1,
                "queue_size": 1,
                "worker_options": {"allow_engine_build": "false"},
            }
        )


def test_jetson_tensorrt_smoke_config_matches_reserved_schema() -> None:
    config_path = Path("configs/jetson_tensorrt_smoke.json")
    config = OrchestratorConfig.from_dict(
        json.loads(config_path.read_text(encoding="utf-8"))
    )

    assert config.name == "jetson_tensorrt_guard_smoke"
    assert len(config.tasks) == 1
    task = config.tasks[0]
    assert task.worker == "tensorrt"
    assert task.engine_path == "models/detector.plan"
    assert task.worker_options is not None
    assert task.worker_options["allow_engine_build"] is False
