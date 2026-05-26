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


def test_agent_scheduler_delay_sample_records_downstream_signal() -> None:
    sample = _load_sample("agent_scheduler_delay_sample.json")

    assert sample["schema_version"] == (  # type: ignore[index]
        "inferedge-orchestrator-scheduler-delay-sample-v1"
    )
    assert sample["source_config"] == (  # type: ignore[index]
        "configs/agent_3_workload_sustained_high_load.json"
    )
    assert sample["not_a_benchmark"] is True

    event_summary = sample["runtime_event_summary"]  # type: ignore[index]
    assert event_summary["scheduler_delay_event_count"] == 3
    assert event_summary["policy_decision_reason_counts"] == {
        "queue_backlog_threshold_exceeded": 9
    }
    assert event_summary["drop_reason_counts"] == {
        "load_shedding_backlog_threshold_exceeded": 9,
        "queue_overflow_drop_oldest": 12,
    }

    delayed = sample["delayed_execution_sample"]  # type: ignore[index]
    assert delayed["event_type"] == "execution"
    assert delayed["scheduler_delay_cycles"] == 3
    assert delayed["queue_wait_ms"] == 15.0
    assert delayed["deadline_missed"] is True

    downstream = sample["downstream_expectation"]  # type: ignore[index]
    assert downstream["aiguard_evidence_type"] == "scheduler_delay_pattern"
    assert downstream["lab_report_section"] == (
        "AIGuard Orchestrator Operation Evidence"
    )


def test_remote_fallback_recovery_sample_records_starter_boundary() -> None:
    sample = _load_sample("remote_fallback_recovery_sample.json")

    assert sample["schema_version"] == (  # type: ignore[index]
        "inferedge-remote-fallback-recovery-sample-v1"
    )
    assert sample["source_contract"] == "inferedge-remote-dispatch-result-v1"
    assert sample["not_a_benchmark"] is True

    dispatch = sample["dispatch_summary"]  # type: ignore[index]
    assert dispatch["dispatch_status"] == "accepted"
    assert dispatch["selected_worker_id"] == "primary-http-worker"
    assert dispatch["fallback_worker_ids"] == ["fallback-http-worker"]

    remote_execution = sample["remote_execution_result"]  # type: ignore[index]
    assert remote_execution["production_remote_execution"] is False
    assert remote_execution["transport"] == "http"
    assert remote_execution["status"] == "failed"
    assert remote_execution["error_category"] == "connection_error"

    fallback = sample["fallback_execution_result"]  # type: ignore[index]
    assert fallback["schema_version"] == "inferedge-remote-fallback-execution-v1"
    assert fallback["primary_worker_id"] == "primary-http-worker"
    assert fallback["attempted_worker_ids"] == ["fallback-http-worker"]
    assert fallback["final_status"] == "succeeded"
    assert fallback["attempts"][0]["production_remote_execution"] is False

    retry_plan = sample["retry_fallback_plan"]  # type: ignore[index]
    assert retry_plan["fallback_execution_performed"] is True
    assert retry_plan["last_execution_status"] == "succeeded"

    summary = sample["remote_operation_summary"]  # type: ignore[index]
    assert summary["schema_version"] == "inferedge-remote-operation-summary-v1"
    assert summary["remote_error_category"] == "connection_error"
    assert summary["fallback_recovered"] is True
    assert summary["final_status"] == "succeeded"
    assert summary["production_remote_execution"] is False

    event_summary = sample["remote_runtime_event_summary"]  # type: ignore[index]
    assert event_summary["schema_version"] == (  # type: ignore[index]
        "inferedge-remote-runtime-event-summary-v1"
    )
    assert event_summary["runtime_event_count"] == (  # type: ignore[index]
        event_summary["event_count"]  # type: ignore[index]
    )
    assert event_summary["event_type_counts"] == {  # type: ignore[index]
        "remote_dispatch_selected": 1,
        "remote_execution_failed": 1,
        "remote_fallback_execution_completed": 1,
        "remote_operation_summary_recorded": 1,
    }
    assert event_summary["error_category_counts"] == {  # type: ignore[index]
        "connection_error": 1
    }
    assert event_summary["fallback_recovered"] is True  # type: ignore[index]
    assert event_summary["final_status"] == "succeeded"  # type: ignore[index]
    assert event_summary["production_remote_execution"] is False  # type: ignore[index]
    assert event_summary["operation_boundary"] == (  # type: ignore[index]
        "remote dispatch starter evidence only"
    )

    events = sample["runtime_event_sample"]  # type: ignore[index]
    assert [event["event"] for event in events] == [
        "remote_dispatch_selected",
        "remote_execution_failed",
        "remote_fallback_execution_completed",
        "remote_operation_summary_recorded",
    ]

    downstream = sample["downstream_expectation"]  # type: ignore[index]
    assert downstream["aiguard_evidence_type"] == (
        "remote_execution_recovered_by_fallback"
    )
    assert downstream["entrypoint_registry_operation_path"] == (
        "remote_dispatch_with_fallback"
    )
    assert "not production" in downstream["boundary"]


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


def test_jetson_tensorrt_contention_sample_records_policy_and_backend_metadata() -> None:
    sample = _load_sample("jetson_tensorrt_contention_sample.json")

    assert sample["run"]["name"] == "jetson_tensorrt_contention_smoke"  # type: ignore[index]
    assert sample["tasks"]["detector_trt"]["executed"] == 6  # type: ignore[index]
    assert sample["tasks"]["detector_trt"]["dropped"] == 0  # type: ignore[index]
    assert sample["tasks"]["classifier_trt"]["executed"] == 1  # type: ignore[index]
    assert sample["tasks"]["classifier_trt"]["dropped"] == 5  # type: ignore[index]
    assert len(sample["overload_events"]) == 5  # type: ignore[arg-type]
    assert all(  # type: ignore[index]
        event["limited_task"] == "classifier_trt"
        for event in sample["overload_events"]  # type: ignore[index]
    )
    assert len(sample["result_events"]) == 7  # type: ignore[arg-type]
    assert {  # type: ignore[index]
        event["output"]["backend"] for event in sample["result_events"]  # type: ignore[index]
    } == {"tensorrt"}
    first_event = sample["result_events"][0]  # type: ignore[index]
    assert first_event["output"]["worker"] == "tensorrt"
    assert first_event["output"]["output_shapes"] == {"output": [1, 2]}
    assert first_event["output"]["output_preview"] == {"output": [0.0, 0.0]}


def test_jetson_tensorrt_diverse_contention_sample_records_distinct_engines() -> None:
    sample = _load_sample("jetson_tensorrt_diverse_contention_sample.json")

    assert sample["run"]["name"] == "jetson_tensorrt_diverse_contention_smoke"  # type: ignore[index]
    assert sample["tasks"]["detector_trt"]["executed"] == 6  # type: ignore[index]
    assert sample["tasks"]["detector_trt"]["dropped"] == 0  # type: ignore[index]
    assert sample["tasks"]["classifier_trt"]["executed"] == 1  # type: ignore[index]
    assert sample["tasks"]["classifier_trt"]["dropped"] == 5  # type: ignore[index]
    assert len(sample["overload_events"]) == 5  # type: ignore[arg-type]
    assert len(sample["policy_decisions"]) == 5  # type: ignore[arg-type]
    assert len(sample["drop_events"]) == 5  # type: ignore[arg-type]
    assert all(  # type: ignore[index]
        event["limited_task"] == "classifier_trt"
        for event in sample["policy_decisions"]  # type: ignore[index]
    )
    result_events = sample["result_events"]  # type: ignore[index]
    assert len(result_events) == 7
    assert {event["output"]["backend"] for event in result_events} == {"tensorrt"}
    assert {event["output"]["engine_path"] for event in result_events} == {
        "models/generated/detector_tiny_fp16.plan",
        "models/generated/classifier_tiny_fp16.plan",
    }
    detector_event = next(event for event in result_events if event["task"] == "detector_trt")
    classifier_event = next(
        event for event in result_events if event["task"] == "classifier_trt"
    )
    assert detector_event["output"]["output_shapes"] == {"detector_scores": [1, 6]}
    assert classifier_event["output"]["output_shapes"] == {
        "classifier_logits": [1, 4]
    }
