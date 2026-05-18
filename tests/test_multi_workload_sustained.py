from __future__ import annotations

import json
from pathlib import Path

from inferedge_orchestrator.config import OrchestratorConfig
from inferedge_orchestrator.sustained import (
    MULTI_WORKLOAD_SCHEMA,
    load_tegrastats_timeline,
    write_multi_workload_sustained,
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


def test_missing_tegrastats_log_is_explicit() -> None:
    timeline = load_tegrastats_timeline(None)

    assert timeline["source"] == "not_provided"
    assert timeline["sample_count"] == 0
    assert timeline["samples"] == []
