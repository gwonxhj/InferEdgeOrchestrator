from __future__ import annotations

import json
from pathlib import Path


SAMPLE_DIR = Path("examples/telemetry")


def _load_sample(name: str) -> dict[str, object]:
    path = SAMPLE_DIR / name
    assert path.exists(), f"missing sample artifact: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase3_overload_sample_captures_policy_effect() -> None:
    sample = _load_sample("phase3_overload_sample.json")

    assert sample["scenario"]["protected_task"] == "detector"  # type: ignore[index]
    assert sample["effect"]["p95_end_to_end_improvement_ms"] == 774.0  # type: ignore[index]
    assert sample["effect"]["low_priority_drops"] == 16  # type: ignore[index]
    assert sample["scheduled"]["overload_events"]  # type: ignore[index]


def test_jetson_dummy_sample_matches_runtime_telemetry_schema() -> None:
    sample = _load_sample("jetson_smoke_dummy_sample.json")

    assert sample["run"]["name"] == "phase4_jetson_smoke"  # type: ignore[index]
    assert sample["tasks"]["detector"]["executed"] == 5  # type: ignore[index]
    assert sample["tasks"]["classifier"]["dropped"] == 3  # type: ignore[index]
    assert len(sample["drop_events"]) == 3  # type: ignore[arg-type]
    assert len(sample["result_events"]) == 7  # type: ignore[arg-type]
    assert {snapshot["stage"] for snapshot in sample["resource_snapshots"]} == {  # type: ignore[index]
        "start",
        "end",
    }


def test_jetson_onnx_sample_records_worker_output_metadata() -> None:
    sample = _load_sample("jetson_onnx_smoke_sample.json")

    assert sample["run"]["name"] == "phase2_onnx_demo"  # type: ignore[index]
    assert sample["tasks"]["identity"]["executed"] == 1  # type: ignore[index]
    assert sample["tasks"]["identity"]["dropped"] == 0  # type: ignore[index]
    event = sample["result_events"][0]  # type: ignore[index]
    assert event["output"]["worker"] == "onnxruntime"
    assert event["output"]["output_shapes"] == [[1, 2]]
    assert {snapshot["stage"] for snapshot in sample["resource_snapshots"]} == {  # type: ignore[index]
        "start",
        "end",
    }
