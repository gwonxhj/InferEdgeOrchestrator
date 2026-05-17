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
    assert summary["observed_runtime_signals"]["max_total_queue_depth"] > 0
    assert summary["observed_runtime_signals"]["tegrastats_sample_count"] == 1

    profiles = {profile["agent_id"]: profile for profile in summary["workload_profiles"]}
    assert profiles["vision_agent"]["runtime_loop"] == "yolo_detection_loop"
    assert profiles["voice_command_agent"]["runtime_loop"] == "whisper_command_burst"
    assert profiles["voice_command_agent"]["ingress_profile"] == (
        "fastapi_concurrent_request"
    )
    assert report["tegrastats_timeline"]["summary"]["max_gpu_percent"] == 42
    assert report["tegrastats_timeline"]["summary"]["max_temperature_c"] == 45.5


def test_missing_tegrastats_log_is_explicit() -> None:
    timeline = load_tegrastats_timeline(None)

    assert timeline["source"] == "not_provided"
    assert timeline["sample_count"] == 0
    assert timeline["samples"] == []
