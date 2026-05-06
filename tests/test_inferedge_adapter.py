from __future__ import annotations

import json

import pytest

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.inferedge_adapter import (
    build_config_from_inferedge_result,
    extract_expected_latency_ms,
    recommend_latency_budget_ms,
    write_config_from_inferedge_result,
)


def test_extract_expected_latency_from_nested_result() -> None:
    result = {
        "runtime": {
            "device": "jetson",
            "summary": {"expected_latency_ms": 42.2},
        }
    }

    assert extract_expected_latency_ms(result) == 42.2


def test_recommend_latency_budget_uses_multiplier_and_ceiling() -> None:
    assert recommend_latency_budget_ms(42.2, multiplier=1.5) == 64.0


def test_build_config_from_inferedge_result_is_valid_orchestrator_config() -> None:
    config = build_config_from_inferedge_result(
        {"expected_latency_ms": 40},
        task_name="detector",
        model_path="models/detector.onnx",
        priority=100,
        target_fps=15,
        queue_size=4,
    )

    parsed = OrchestratorConfig.from_dict(config)
    assert parsed.tasks[0].latency_budget_ms == 60.0
    assert parsed.tasks[0].worker == "onnxruntime"
    assert config["run"]["source"]["type"] == "inferedge_result_json"


def test_build_config_from_inferedge_result_supports_tensorrt_schema() -> None:
    config = build_config_from_inferedge_result(
        {"expected_latency_ms": 40},
        task_name="detector",
        model_path="models/detector.onnx",
        engine_path="models/detector.plan",
        priority=100,
        target_fps=15,
        queue_size=4,
        worker="tensorrt",
        worker_options={"allow_engine_build": False},
    )

    parsed = OrchestratorConfig.from_dict(config)
    assert parsed.tasks[0].worker == "tensorrt"
    assert parsed.tasks[0].engine_path == "models/detector.plan"
    assert config["tasks"][0]["worker_options"] == {"allow_engine_build": False}


def test_build_config_from_inferedge_result_rejects_invalid_tensorrt_schema() -> None:
    with pytest.raises(ValueError, match="requires engine_path"):
        build_config_from_inferedge_result(
            {"expected_latency_ms": 40},
            task_name="detector",
            model_path="models/detector.onnx",
            priority=100,
            target_fps=15,
            queue_size=4,
            worker="tensorrt",
        )


def test_write_config_from_inferedge_result(tmp_path) -> None:
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "orchestrator.json"
    result_path.write_text(
        json.dumps({"analysis": {"p95_latency_ms": 55}}),
        encoding="utf-8",
    )

    write_config_from_inferedge_result(
        result_path,
        output_path,
        task_name="ocr",
        model_path="models/ocr.onnx",
        priority=60,
        target_fps=5,
        queue_size=2,
        budget_multiplier=2.0,
    )

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["tasks"][0]["latency_budget_ms"] == 110.0


def test_missing_latency_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Could not find expected latency"):
        extract_expected_latency_ms({"runtime": {"status": "ok"}})
