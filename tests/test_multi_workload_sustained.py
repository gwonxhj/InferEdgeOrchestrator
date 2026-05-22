from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.sustained import (
    EDGEENV_TELEMETRY_FEED_SCHEMA,
    MULTI_WORKLOAD_SCHEMA,
    apply_device_local_input_overrides,
    load_tegrastats_timeline,
    write_multi_workload_sustained,
    write_process_resource_snapshot,
)


def test_multi_workload_sustained_config_loads_profiles() -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )

    assert config.name == "agent_multi_workload_sustained_local"
    assert [task.agent_id for task in config.tasks] == [
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    ]
    assert [task.worker_options["runtime_loop"] for task in config.tasks if task.worker_options] == [
        "safety_monitor_loop",
        "yolo_detection_loop",
        "whisper_command_burst",
    ]
    assert config.tasks[2].worker_options is not None
    assert all(
        task.worker_options and task.worker_options["implementation"] == "local_profile_adapter"
        for task in config.tasks
    )
    assert config.tasks[2].worker_options["ingress_profile"] == (
        "fastapi_concurrent_request"
    )


def test_run_multi_workload_sustained_writes_profile_summary(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained.json"
    tegrastats = tmp_path / "tegrastats.log"
    tegrastats.write_text(
        "RAM 2048/7771MB SWAP 0/3885MB CPU [12%@1510] "
        "GR3D_FREQ 42% cpu@45.5C gpu@44.0C\n",
        encoding="utf-8",
    )

    report = write_multi_workload_sustained(
        config,
        output=output,
        frames=8,
        tegrastats_log=tegrastats,
    )

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == report
    summary = report["multi_workload_sustained_summary"]
    assert summary["schema_version"] == MULTI_WORKLOAD_SCHEMA
    assert summary["scenario_mode"] == "sustained_high_load"
    assert summary["scenario_label"] == "producer_backed_sustained_high_load"
    assert summary["scenario_category"] == "sustained"
    assert "Producer-backed sustained" in summary["scenario_description"]
    assert report["run"]["scenario_label"] == "producer_backed_sustained_high_load"
    assert report["sustained_runtime_summary"]["scenario_category"] == "sustained"
    signals = summary["observed_runtime_signals"]
    assert signals["max_total_queue_depth"] > 0
    assert signals["tegrastats_sample_count"] == 1
    assert signals["local_profile_adapter_count"] > 0
    assert signals["local_profile_elapsed_ms"] > 0
    assert set(signals["local_profile_kinds"]) == {
        "safety_monitor_loop",
        "vision_frame_loop",
        "voice_command_burst",
    }

    profiles = {profile["agent_id"]: profile for profile in summary["workload_profiles"]}
    assert profiles["vision_agent"]["runtime_loop"] == "yolo_detection_loop"
    assert profiles["vision_agent"]["implementation"] == "local_profile_adapter"
    assert profiles["vision_agent"]["profile_work_units"] == 24000
    assert profiles["voice_command_agent"]["runtime_loop"] == "whisper_command_burst"
    assert profiles["voice_command_agent"]["ingress_profile"] == (
        "fastapi_concurrent_request"
    )
    outputs = [event["output"] for event in report["result_events"]]
    assert any(output.get("profile_kind") == "vision_frame_loop" for output in outputs)
    assert any(output.get("profile_kind") == "voice_command_burst" for output in outputs)
    assert any(output.get("profile_kind") == "safety_monitor_loop" for output in outputs)
    assert report["tegrastats_timeline"]["summary"]["max_gpu_percent"] == 42
    assert report["tegrastats_timeline"]["summary"]["max_temperature_c"] == 45.5
    feed = report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["role"] == "orchestrator_operation_context_for_edgeenv"
    assert feed["not_a_regression_judgement"] is True
    assert feed["not_a_comparability_gate"] is True
    assert feed["decision_owner"] == "lab"
    assert feed["regression_owner"] == "edgeenv"
    candidate = feed["candidate_context"]
    assert candidate["telemetry_source"] == (
        "inferedge_orchestrator_operation_summary"
    )
    assert candidate["queue_depth"] == signals["max_total_queue_depth"]
    assert candidate["operation"]["deadline_missed_count"] == (
        report["agent_runtime_summary"]["totals"]["deadline_missed_count"]
    )
    assert candidate["operation"]["fallback_count"] == (
        report["agent_runtime_summary"]["totals"]["fallback_count"]
    )
    assert candidate["operation"]["policy_decision_reasons"] == (
        report["queue_state_summary"]["policy_decision_reasons"]
    )
    assert candidate["resource"]["source"] == "tegrastats_timeline"
    assert candidate["resource"]["gpu_temperature"] == 44.0
    assert candidate["resource"]["cpu_temperature"] == 45.5
    assert candidate["resource"]["gpu_percent"] == 42
    assert feed["edgeenv_mapping_hint"]["copy_candidate_context_to"] == (
        "runtime_telemetry_context.candidate"
    )


def test_run_multi_workload_sustained_profiles_local_image_input(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_vision_file.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_vision_file.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert config.input_source == "image"
    assert config.input_path == "examples/inputs/vision_frame.ppm"
    assert output.exists()
    summary = report["multi_workload_sustained_summary"]
    signals = summary["observed_runtime_signals"]
    assert "vision_frame_loop" in signals["local_profile_kinds"]

    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
        and event["output"].get("profile_kind") == "vision_frame_loop"
    ]
    assert vision_outputs
    first_output = vision_outputs[0]
    assert first_output["producer_source"] == "image_file"
    assert first_output["frame_source"] == "image"
    assert first_output["input_path"] == "examples/inputs/vision_frame.ppm"
    assert first_output["input_bytes"] > 0
    assert first_output["sampled_bytes"] > 0
    assert first_output["input_digest"]
    assert first_output["contention_signal"] == "vision_file_cpu_profile"


def test_run_multi_workload_sustained_profiles_voice_ingress_fixture(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_voice_ingress.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_voice_ingress.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    voice_task = next(
        task for task in config.tasks if task.name == "voice_command_agent"
    )
    assert voice_task.worker_options is not None
    assert voice_task.worker_options["ingress_payload_path"] == (
        "examples/inputs/voice_ingress_requests.json"
    )

    voice_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "voice_command_agent"
        and event["output"].get("profile_kind") == "voice_command_burst"
    ]
    assert voice_outputs
    first_output = voice_outputs[0]
    assert first_output["producer_source"] == "fastapi_request_fixture"
    assert first_output["ingress_payload_path"] == (
        "examples/inputs/voice_ingress_requests.json"
    )
    assert first_output["available_request_count"] == 3
    assert first_output["ingress_request_count"] == 2
    assert first_output["selected_request_ids"]
    assert first_output["selected_routes"] == ["/agent/command", "/agent/command"]
    assert first_output["selected_methods"] == ["POST", "POST"]
    assert first_output["request_digest"]
    assert first_output["command_char_count"] > 0
    assert first_output["contention_signal"] == "fastapi_request_cpu_profile"


def test_run_multi_workload_sustained_profiles_safety_resource_fixture(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_safety_resource.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_safety_resource.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    safety_task = next(
        task for task in config.tasks if task.name == "safety_monitor_agent"
    )
    assert safety_task.worker_options is not None
    assert safety_task.worker_options["resource_snapshot_path"] == (
        "examples/inputs/safety_resource_snapshots.json"
    )

    safety_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "safety_monitor_agent"
        and event["output"].get("profile_kind") == "safety_monitor_loop"
    ]
    assert safety_outputs
    first_output = safety_outputs[0]
    assert first_output["producer_source"] == "resource_snapshot_fixture"
    assert first_output["resource_snapshot_path"] == (
        "examples/inputs/safety_resource_snapshots.json"
    )
    assert first_output["resource_snapshot_id"]
    assert first_output["cpu_percent"] >= 0
    assert first_output["memory_used_ratio"] >= 0
    assert first_output["temperature_c"] >= 0
    assert first_output["resource_degradation_score"] >= 0
    assert first_output["resource_digest"]
    assert first_output["contention_signal"] == "resource_monitor_profile"
    assert "cpu_percent" in first_output["sampled_metrics"]
    assert "fallback_signal" in first_output["sampled_metrics"]


def test_run_multi_workload_sustained_device_local_starter(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    output = tmp_path / "multi_workload_sustained_device_local.json"

    report = write_multi_workload_sustained(config, output=output, frames=8)

    assert output.exists()
    assert config.name == "agent_multi_workload_sustained_device_local"
    assert config.scenario_mode == "device_local"
    summary = report["multi_workload_sustained_summary"]
    assert summary["scenario_mode"] == "device_local"
    assert summary["scenario_label"] == "device_local_sustained_starter"
    assert summary["scenario_category"] == "device_local"
    assert "Device-local sustained starter" in summary["scenario_description"]
    assert "device-local sustained validation starter" in summary["evidence_scope"]
    assert "live device-local" in summary["next_validation_step"]

    signals = summary["observed_runtime_signals"]
    assert set(signals["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert signals["producer_source_count"] > 0
    assert signals["device_local_producer_count"] == signals["producer_source_count"]

    profiles = {profile["agent_id"]: profile for profile in summary["workload_profiles"]}
    assert profiles["vision_agent"]["device_local_validation"] is True
    assert profiles["voice_command_agent"]["producer_stage"] == "device_local_starter"
    assert profiles["safety_monitor_agent"]["producer_stage"] == "device_local_starter"
    queue_summary = report["queue_state_summary"]
    assert queue_summary["device_local_task_count"] == 3
    assert set(queue_summary["device_local_tasks"]) == {
        "safety_monitor_agent",
        "vision_agent",
        "voice_command_agent",
    }
    assert set(queue_summary["device_local_producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert queue_summary["queue_pressure_reason"] != (
        "overload_threshold_not_configured"
    )
    assert queue_summary["producer_sources_by_task"]["vision_agent"] == ["image_file"]
    workers = report["worker_health_snapshot"]["workers"]
    assert workers["vision_agent"]["device_local_validation"] is True
    assert workers["vision_agent"]["producer_stage"] == "device_local_starter"
    assert "image_file" in workers["vision_agent"]["producer_sources"]
    assert workers["vision_agent"]["producer_context_summary"] == {
        "device_local_validation": True,
        "producer_stage": "device_local_starter",
        "producer_sources": ["image_file"],
        "producer_event_count": workers["vision_agent"]["producer_event_count"],
    }
    assert workers["voice_command_agent"]["producer_sources"] == [
        "fastapi_request_fixture"
    ]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "resource_snapshot_fixture"
    ]
    execution_events = [
        event
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    ]
    assert any(
        event["producer_context"].get("producer_source") == "image_file"
        for event in execution_events
    )
    assert any(
        event["producer_context"].get("producer_source") == "fastapi_request_fixture"
        for event in execution_events
    )
    assert any(
        event["producer_context"].get("producer_source") == "resource_snapshot_fixture"
        for event in execution_events
    )
    event_summary = report["runtime_event_summary"]
    assert set(event_summary["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert event_summary["producer_event_count"] == len(execution_events)
    assert event_summary["device_local_event_count"] > 0
    feed = report["edgeenv_runtime_telemetry_feed"]
    assert feed["schema_version"] == EDGEENV_TELEMETRY_FEED_SCHEMA
    assert feed["scenario_mode"] == "device_local"
    assert feed["candidate_context"]["operation"]["queue_pressure_state"] == (
        queue_summary["queue_pressure_state"]
    )
    assert feed["candidate_context"]["operation"]["queue_depth"] == (
        queue_summary["max_total_queue_depth"]
    )
    assert feed["candidate_context"]["resource"]["source"] == (
        "result_events_resource_snapshot"
    )
    assert feed["candidate_context"]["resource"]["temperature_c"] == 69.2
    assert feed["candidate_context"]["resource"]["ram_used_mb"] == 6144.0
    assert "runtime_queue_overload" in feed["edgeenv_mapping_hint"][
        "aiguard_evidence_candidates"
    ]


def test_device_local_input_overrides_use_local_paths(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    image = tmp_path / "frame.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    requests = tmp_path / "requests.json"
    requests.write_text(
        json.dumps(
            [
                {
                    "request_id": "local-command-1",
                    "method": "POST",
                    "path": "/agent/command",
                    "command": "inspect local backlog",
                }
            ]
        ),
        encoding="utf-8",
    )
    resources = tmp_path / "resources.json"
    resources.write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "snapshot_id": "local-process-1",
                        "cpu_percent": 37.5,
                        "memory_used_mb": 256,
                        "memory_total_mb": 1024,
                        "temperature_c": 42.0,
                        "queue_depth": 4,
                        "fallback_count": 1,
                        "deadline_missed_count": 1,
                        "dropped_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    overridden = apply_device_local_input_overrides(
        config,
        vision_input=image,
        voice_ingress_payload=requests,
        resource_snapshot=resources,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_overrides.json",
        frames=4,
    )

    assert overridden.input_source == "image"
    assert overridden.input_path == str(image)
    outputs = [event["output"] for event in report["result_events"]]
    assert any(output.get("input_path") == str(image) for output in outputs)
    assert any(
        output.get("ingress_payload_path") == str(requests) for output in outputs
    )
    assert any(
        output.get("resource_snapshot_path") == str(resources) for output in outputs
    )
    summary = report["multi_workload_sustained_summary"]
    signals = summary["observed_runtime_signals"]
    assert set(signals["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    workers = report["worker_health_snapshot"]["workers"]
    assert "image_file" in workers["vision_agent"]["producer_sources"]
    assert workers["vision_agent"]["producer_stage"] == "device_local_cli_override"
    assert workers["vision_agent"]["primary_health_reason"]
    assert workers["vision_agent"]["operation_risk_summary"]
    assert workers["vision_agent"]["producer_context_summary"][
        "producer_stage"
    ] == "device_local_cli_override"
    assert workers["voice_command_agent"]["producer_sources"] == [
        "fastapi_request_fixture"
    ]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "resource_snapshot_fixture"
    ]
    queue_summary = report["queue_state_summary"]
    assert set(queue_summary["device_local_producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert queue_summary["producer_sources_by_task"]["voice_command_agent"] == [
        "fastapi_request_fixture"
    ]
    event_summary = report["runtime_event_summary"]
    assert set(event_summary["producer_sources"]) == {
        "image_file",
        "fastapi_request_fixture",
        "resource_snapshot_fixture",
    }
    assert event_summary["device_local_event_count"] > 0
    assert any(
        event["producer_context"].get("input_path") == str(image)
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    )


def test_device_local_vision_input_can_use_image_sequence_directory(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    sequence_dir = tmp_path / "frames"
    sequence_dir.mkdir()
    first = sequence_dir / "frame_001.ppm"
    second = sequence_dir / "frame_002.ppm"
    first.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    second.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")

    overridden = apply_device_local_input_overrides(
        config,
        vision_input=sequence_dir,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_image_sequence.json",
        frames=4,
    )

    assert overridden.input_source == "image_sequence"
    assert overridden.input_path == str(sequence_dir)
    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
    ]
    assert vision_outputs
    assert {output["producer_source"] for output in vision_outputs} == {
        "image_sequence_file"
    }
    observed_paths = {output["input_path"] for output in vision_outputs}
    assert str(first) in observed_paths
    assert str(second) in observed_paths
    assert {output["sequence_root"] for output in vision_outputs} == {
        str(sequence_dir)
    }
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert "image_sequence_file" in signals["producer_sources"]
    assert signals["device_local_producer_count"] == signals["producer_source_count"]


def test_device_local_vision_can_run_optional_onnx_probe(
    tmp_path,
    monkeypatch,
) -> None:
    np = pytest.importorskip("numpy")

    class FakeInput:
        name = "images"
        shape = [1, 3, 2, 2]

    class FakeSession:
        def __init__(self, model_path, providers):
            self.model_path = model_path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def get_providers(self):
            return self.providers

        def run(self, output_names, feed):
            assert output_names is None
            assert list(feed) == ["images"]
            assert feed["images"].shape == (1, 3, 2, 2)
            return [np.ones((1, 1, 6), dtype=np.float32)]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=FakeSession),
    )

    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    image = tmp_path / "frame.ppm"
    image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    model = tmp_path / "vision_probe.onnx"
    model.write_bytes(b"fake onnx model for mocked session")
    overridden = apply_device_local_input_overrides(
        config,
        vision_input=image,
        vision_onnx_model=model,
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_vision_onnx_probe.json",
        frames=4,
    )

    vision_profile = next(
        profile
        for profile in report["multi_workload_sustained_summary"]["workload_profiles"]
        if profile["agent_id"] == "vision_agent"
    )
    assert vision_profile["vision_inference_backend"] == "onnxruntime"
    assert vision_profile["vision_model_path"] == str(model)
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert signals["vision_inference_backend_count"] == 1
    assert signals["vision_inference_backends"] == ["onnxruntime"]

    vision_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "vision_agent"
    ]
    assert vision_outputs
    first_output = vision_outputs[0]
    assert first_output["producer_source"] == "image_file"
    assert first_output["contention_signal"] == "vision_onnxruntime_probe"
    assert first_output["vision_inference_backend"] == "onnxruntime"
    assert first_output["vision_inference_mode"] == "probe"
    assert first_output["vision_model_path"] == str(model)
    assert first_output["vision_provider"] == "CPUExecutionProvider"
    assert first_output["vision_input_shapes"] == {"images": [1, 3, 2, 2]}
    assert first_output["vision_output_shapes"] == [[1, 1, 6]]
    assert first_output["vision_output_count"] == 1
    assert first_output["vision_probe_elapsed_ms"] >= 0


def test_process_resource_snapshot_can_feed_device_local_safety(tmp_path) -> None:
    config = OrchestratorConfig.from_dict(
        json.loads(
            Path("configs/agent_multi_workload_sustained_device_local.json").read_text(
                encoding="utf-8"
            )
        )
    )
    snapshot = write_process_resource_snapshot(tmp_path / "process_snapshot.json")
    overridden = apply_device_local_input_overrides(
        config,
        resource_snapshot=snapshot,
        resource_snapshot_source="process_resource_snapshot",
    )
    report = write_multi_workload_sustained(
        overridden,
        output=tmp_path / "device_local_process_snapshot.json",
        frames=4,
    )

    safety_outputs = [
        event["output"]
        for event in report["result_events"]
        if event["task"] == "safety_monitor_agent"
    ]
    assert safety_outputs
    assert safety_outputs[0]["producer_source"] == "process_resource_snapshot"
    assert safety_outputs[0]["resource_snapshot_path"] == str(snapshot)
    assert safety_outputs[0]["resource_snapshot_id"] == "device_local_process_0"
    signals = report["multi_workload_sustained_summary"]["observed_runtime_signals"]
    assert "process_resource_snapshot" in signals["producer_sources"]
    workers = report["worker_health_snapshot"]["workers"]
    assert workers["safety_monitor_agent"]["producer_sources"] == [
        "process_resource_snapshot"
    ]
    assert any(
        event["producer_context"].get("producer_source") == "process_resource_snapshot"
        for event in report["runtime_event_timeline"]
        if event["event_type"] == "execution"
    )


def test_missing_tegrastats_log_is_explicit() -> None:
    timeline = load_tegrastats_timeline(None)

    assert timeline["source"] == "not_provided"
    assert timeline["sample_count"] == 0
    assert timeline["samples"] == []
