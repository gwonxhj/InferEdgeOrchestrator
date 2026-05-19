from __future__ import annotations

import json
from pathlib import Path

import pytest

from inferedge_orchestrator.cli import main
from inferedge_orchestrator.remote_dispatch import dispatch_remote_task


def test_remote_dispatch_selects_matching_healthy_worker(tmp_path: Path) -> None:
    output = tmp_path / "remote_dispatch.json"

    result = dispatch_remote_task(
        registry_path="examples/remote_worker_registry.json",
        request_path="examples/remote_task_request.json",
        output_path=output,
    )

    assert output.exists()
    assert result["schema_version"] == "inferedge-remote-dispatch-result-v1"
    assert result["dispatch_status"] == "accepted"
    assert result["selected_worker_id"] == "jetson-nano-01"
    assert result["remote_execution"] == {
        "mode": "file_contract_starter",
        "production_remote_execution": False,
        "registry_path": "examples/remote_worker_registry.json",
        "request_path": "examples/remote_task_request.json",
    }
    assert result["runtime_events"][0]["event"] == "remote_dispatch_selected"
    assert (
        result["worker_health_snapshot"]["workers"]["jetson-nano-01"]["health_state"]
        == "healthy"
    )


def test_remote_dispatch_rejects_when_no_worker_matches(tmp_path: Path) -> None:
    registry = {
        "schema_version": "inferedge-remote-worker-registry-v1",
        "workers": [
            {
                "worker_id": "cpu-only",
                "status": "online",
                "endpoint_type": "file_contract",
                "capabilities": {"workers": ["onnxruntime"], "devices": ["cpu"]},
                "health": {"state": "healthy"},
            }
        ],
    }
    request = {
        "schema_version": "inferedge-remote-task-request-v1",
        "task_id": "task_vision_001",
        "agent_id": "vision_agent",
        "required_backend": "tensorrt",
        "device_target": "jetson",
    }
    registry_path = tmp_path / "registry.json"
    request_path = tmp_path / "request.json"
    output = tmp_path / "remote_dispatch.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    request_path.write_text(json.dumps(request), encoding="utf-8")

    result = dispatch_remote_task(
        registry_path=registry_path,
        request_path=request_path,
        output_path=output,
    )

    assert result["dispatch_status"] == "rejected"
    assert result["selected_worker_id"] is None
    assert result["runtime_events"][0]["event"] == "remote_dispatch_rejected"


def test_remote_dispatch_cli_writes_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "remote_dispatch.json"

    exit_code = main(
        [
            "remote-dispatch",
            "--registry",
            "examples/remote_worker_registry.json",
            "--request",
            "examples/remote_task_request.json",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "dispatch_status=accepted" in captured.out
    assert json.loads(output.read_text(encoding="utf-8"))["selected_worker_id"] == (
        "jetson-nano-01"
    )
