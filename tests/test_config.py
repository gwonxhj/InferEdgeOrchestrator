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
    assert task.emit_every_cycles == 1
    assert task.engine_path is None
    assert task.worker_options is None


def test_task_config_loads_agent_manifest_and_runtime_agent_defaults() -> None:
    task = TaskConfig.from_dict(
        {
            "name": "vision_agent",
            "agent_manifest_path": "examples/agent_runtime/vision_agent_manifest.json",
            "runtime_result_path": "examples/agent_runtime/vision_runtime_result.json",
            "target_fps": 30,
            "queue_size": 2,
            "worker": "dummy",
        }
    )

    assert task.agent_id == "vision_agent"
    assert task.agent_task_id == "task_vision_agent"
    assert task.agent_type == "vision"
    assert task.priority == 90
    assert task.latency_budget_ms == 33
    assert task.model_path == "models/vision_agent.onnx"
    assert task.fallback_policy == "drop_stale"


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


def test_task_config_rejects_invalid_emit_every_cycles() -> None:
    with pytest.raises(ValueError, match="emit_every_cycles must be > 0"):
        TaskConfig.from_dict(
            {
                "name": "detector",
                "model_path": "",
                "priority": 1,
                "target_fps": 1,
                "latency_budget_ms": 1,
                "queue_size": 1,
                "emit_every_cycles": 0,
            }
        )


def test_orchestrator_config_accepts_sustained_scenario_metadata() -> None:
    config = OrchestratorConfig.from_dict(
        {
            "run": {
                "name": "sustained",
                "scenario_mode": "sustained_high_load",
                "frame_interval_ms": 5,
            },
            "tasks": [
                {
                    "name": "detector",
                    "model_path": "",
                    "priority": 1,
                    "target_fps": 1,
                    "latency_budget_ms": 1,
                    "queue_size": 1,
                }
            ],
        }
    )

    assert config.scenario_mode == "sustained_high_load"
    assert config.frame_interval_ms == 5


def test_orchestrator_config_rejects_unknown_scenario_mode() -> None:
    task = {
        "name": "detector",
        "model_path": "",
        "priority": 1,
        "target_fps": 1,
        "latency_budget_ms": 1,
        "queue_size": 1,
    }

    with pytest.raises(ValueError, match="unsupported scenario_mode"):
        OrchestratorConfig.from_dict(
            {"run": {"scenario_mode": "ai_os"}, "tasks": [task]}
        )


def test_jetson_tensorrt_smoke_config_matches_reserved_schema() -> None:
    config_path = Path("configs/jetson_tensorrt_smoke.json")
    config = OrchestratorConfig.from_dict(
        json.loads(config_path.read_text(encoding="utf-8"))
    )

    assert config.name == "jetson_tensorrt_inference_smoke"
    assert len(config.tasks) == 1
    task = config.tasks[0]
    assert task.worker == "tensorrt"
    assert task.engine_path == "models/detector.plan"
    assert task.worker_options is not None
    assert task.worker_options["allow_engine_build"] is False


def test_jetson_tensorrt_contention_config_matches_reserved_schema() -> None:
    config_path = Path("configs/jetson_tensorrt_contention.json")
    config = OrchestratorConfig.from_dict(
        json.loads(config_path.read_text(encoding="utf-8"))
    )

    assert config.name == "jetson_tensorrt_contention_smoke"
    assert config.overload_backlog_threshold == 2
    assert [task.name for task in config.tasks] == ["detector_trt", "classifier_trt"]
    assert [task.worker for task in config.tasks] == ["tensorrt", "tensorrt"]
    assert [task.priority for task in config.tasks] == [100, 10]
    assert all(task.engine_path == "models/detector.plan" for task in config.tasks)


def test_jetson_tensorrt_diverse_contention_config_matches_reserved_schema() -> None:
    config_path = Path("configs/jetson_tensorrt_diverse_contention.json")
    config = OrchestratorConfig.from_dict(
        json.loads(config_path.read_text(encoding="utf-8"))
    )

    assert config.name == "jetson_tensorrt_diverse_contention_smoke"
    assert config.overload_backlog_threshold == 2
    assert [task.name for task in config.tasks] == ["detector_trt", "classifier_trt"]
    assert [task.worker for task in config.tasks] == ["tensorrt", "tensorrt"]
    assert [task.priority for task in config.tasks] == [100, 10]
    assert [task.engine_path for task in config.tasks] == [
        "models/generated/detector_tiny_fp16.plan",
        "models/generated/classifier_tiny_fp16.plan",
    ]
    assert [task.model_path for task in config.tasks] == [
        "models/generated/detector_tiny.onnx",
        "models/generated/classifier_tiny.onnx",
    ]
    assert config.tasks[0].worker_options is not None
    assert config.tasks[1].worker_options is not None
    assert config.tasks[0].worker_options["profile_name"] == "detector_tiny_fp16"
    assert config.tasks[1].worker_options["profile_name"] == "classifier_tiny_fp16"
    assert config.tasks[0].worker_options["input_bindings"] == {
        "detector_input": [1, 3, 16, 16]
    }
    assert config.tasks[1].worker_options["output_bindings"] == {
        "classifier_logits": [1, 4]
    }


def test_agent_3_workload_demo_matches_agent_contract_inputs() -> None:
    config_path = Path("configs/agent_3_workload_demo.json")
    config = OrchestratorConfig.from_dict(
        json.loads(config_path.read_text(encoding="utf-8"))
    )

    assert config.name == "agent_3_workload_demo"
    assert [task.agent_id for task in config.tasks] == [
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    ]
    assert [task.priority for task in config.tasks] == [100, 90, 50]
    assert [task.latency_budget_ms for task in config.tasks] == [20, 33, 120]
    assert config.tasks[1].runtime_result_path == (
        "examples/agent_runtime/vision_runtime_result.json"
    )


def test_agent_3_workload_scenario_configs_are_separated() -> None:
    expected = {
        "configs/agent_3_workload_normal.json": "normal",
        "configs/agent_3_workload_overload.json": "overload",
        "configs/agent_3_workload_sustained_high_load.json": "sustained_high_load",
        "configs/agent_multi_workload_sustained_device_local.json": "device_local",
    }

    for path, scenario_mode in expected.items():
        config = OrchestratorConfig.from_dict(
            json.loads(Path(path).read_text(encoding="utf-8"))
        )
        assert config.scenario_mode == scenario_mode
        assert [task.agent_id for task in config.tasks] == [
            "safety_monitor_agent",
            "vision_agent",
            "voice_command_agent",
        ]
        assert all(task.emit_every_cycles >= 1 for task in config.tasks)
