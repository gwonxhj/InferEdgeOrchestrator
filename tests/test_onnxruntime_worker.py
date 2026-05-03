from __future__ import annotations

import pytest

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.runtime import OrchestratorRuntime

np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")


def _write_identity_model(path) -> None:
    from onnx import TensorProto, helper

    input_tensor = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 2])
    output_tensor = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2])
    node = helper.make_node("Identity", inputs=["input"], outputs=["output"])
    graph = helper.make_graph([node], "identity_graph", [input_tensor], [output_tensor])
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_operatorsetid("", 13)],
        ir_version=10,
    )
    onnx.checker.check_model(model)
    onnx.save(model, path)


def test_onnxruntime_worker_executes_real_onnx_model(tmp_path) -> None:
    model_path = tmp_path / "identity.onnx"
    _write_identity_model(model_path)
    config = OrchestratorConfig.from_dict(
        {
            "run": {"name": "onnx_test"},
            "tasks": [
                {
                    "name": "identity",
                    "model_path": str(model_path),
                    "priority": 100,
                    "target_fps": 5,
                    "latency_budget_ms": 100,
                    "queue_size": 2,
                    "drop_policy": "drop_oldest",
                    "worker": "onnxruntime",
                }
            ],
        }
    )

    report = OrchestratorRuntime(config).run(frames=1)

    assert report["tasks"]["identity"]["executed"] == 1
    assert report["tasks"]["identity"]["mean_latency_ms"] is not None
    assert report["result_events"][0]["output"]["worker"] == "onnxruntime"
    assert report["result_events"][0]["output"]["output_shapes"] == [[1, 2]]


def test_config_can_select_dummy_and_onnxruntime_workers(tmp_path) -> None:
    model_path = tmp_path / "identity.onnx"
    _write_identity_model(model_path)

    config = OrchestratorConfig.from_dict(
        {
            "run": {"name": "mixed_workers", "overload_backlog_threshold": 3},
            "tasks": [
                {
                    "name": "detector",
                    "model_path": "",
                    "priority": 100,
                    "target_fps": 5,
                    "latency_budget_ms": 100,
                    "queue_size": 2,
                    "drop_policy": "drop_oldest",
                    "worker": "dummy",
                    "simulated_latency_ms": 3,
                },
                {
                    "name": "identity",
                    "model_path": str(model_path),
                    "priority": 50,
                    "target_fps": 5,
                    "latency_budget_ms": 100,
                    "queue_size": 2,
                    "drop_policy": "drop_oldest",
                    "worker": "onnxruntime",
                },
            ],
        }
    )

    report = OrchestratorRuntime(config).run(frames=1)

    workers = {event["output"]["worker"] for event in report["result_events"]}
    assert workers == {"dummy", "onnxruntime"}
