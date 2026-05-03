from __future__ import annotations

from inferedge_orchestrator.config import load_config
from inferedge_orchestrator.monitor import ResourceMonitor, parse_tegrastats_line
from inferedge_orchestrator.runtime import OrchestratorRuntime


def test_parse_tegrastats_line_extracts_resource_fields() -> None:
    line = (
        "RAM 2048/7771MB (lfb 128x4MB) SWAP 0/3885MB "
        "CPU [12%@1510,off,3%@1510] GR3D_FREQ 42% "
        "cpu@45.5C gpu@44.0C"
    )

    parsed = parse_tegrastats_line(line)

    assert parsed["ram_used_mb"] == 2048
    assert parsed["ram_total_mb"] == 7771
    assert parsed["swap_used_mb"] == 0
    assert parsed["gpu_percent"] == 42
    assert parsed["temperatures_c"]["cpu"] == 45.5
    assert parsed["temperatures_c"]["gpu"] == 44.0


def test_resource_monitor_returns_snapshot() -> None:
    snapshot = ResourceMonitor().capture(stage="test")

    assert snapshot.stage == "test"
    assert snapshot.platform


def test_runtime_telemetry_includes_resource_snapshots() -> None:
    config = load_config("configs/phase4_jetson_smoke.json")

    report = OrchestratorRuntime(config).run(frames=1)

    stages = [snapshot["stage"] for snapshot in report["resource_snapshots"]]
    assert stages == ["start", "end"]
