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
        "execution_requested": False,
        "registry_path": "examples/remote_worker_registry.json",
        "request_path": "examples/remote_task_request.json",
    }
    assert result["remote_execution_result"] == {
        "schema_version": "inferedge-remote-execution-result-v1",
        "execution_requested": False,
        "execution_performed": False,
        "production_remote_execution": False,
        "status": "skipped",
        "transport": "file_contract",
        "selected_worker_id": "jetson-nano-01",
        "task_id": "task_vision_001",
        "agent_id": "vision_agent",
        "error_category": "execution_not_requested",
    }
    assert result["runtime_events"][0]["event"] == "remote_dispatch_selected"
    assert (
        result["worker_health_snapshot"]["workers"]["jetson-nano-01"]["health_state"]
        == "healthy"
    )
    assert result["remote_execution_plan"]["mode"] == "plan_only"
    assert result["remote_execution_plan"]["network_execution_performed"] is False
    assert result["worker_selection"]["schema_version"] == (
        "inferedge-remote-worker-selection-v1"
    )
    assert result["worker_selection"]["selected_worker_id"] == "jetson-nano-01"
    assert result["retry_fallback_plan"]["schema_version"] == (
        "inferedge-remote-retry-fallback-plan-v1"
    )
    assert result["retry_fallback_plan"]["execution_performed"] is False


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
    assert result["remote_execution_plan"]["mode"] == "no_worker_selected"
    assert result["worker_selection"]["candidate_worker_ids"] == []


def test_remote_dispatch_records_fallback_candidates_and_retry_policy(
    tmp_path: Path,
) -> None:
    registry = {
        "schema_version": "inferedge-remote-worker-registry-v1",
        "workers": [
            {
                "worker_id": "jetson-primary",
                "status": "online",
                "endpoint_type": "ssh_command",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["jetson"],
                    "priority_capacity": 10,
                },
                "health": {"state": "healthy"},
            },
            {
                "worker_id": "jetson-fallback",
                "status": "online",
                "endpoint_type": "http_request",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["jetson"],
                    "priority_capacity": 5,
                },
                "health": {"state": "constrained"},
            },
        ],
    }
    request = {
        "schema_version": "inferedge-remote-task-request-v1",
        "task_id": "task_vision_002",
        "agent_id": "vision_agent",
        "required_backend": "onnxruntime",
        "device_target": "jetson",
        "retry_policy": {
            "max_attempts": 3,
            "fallback_on": ["timeout", "worker_unhealthy"],
        },
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

    assert result["selected_worker_id"] == "jetson-primary"
    assert result["worker_selection"]["candidate_worker_ids"] == [
        "jetson-primary",
        "jetson-fallback",
    ]
    assert result["worker_selection"]["fallback_worker_ids"] == ["jetson-fallback"]
    assert result["remote_execution_plan"]["transport"] == "ssh"
    assert result["retry_fallback_plan"] == {
        "schema_version": "inferedge-remote-retry-fallback-plan-v1",
        "max_attempts": 3,
        "fallback_on": ["timeout", "worker_unhealthy"],
        "primary_worker_id": "jetson-primary",
        "fallback_worker_ids": ["jetson-fallback"],
        "execution_performed": False,
        "fallback_execution_performed": False,
        "last_execution_status": "skipped",
    }


def test_remote_dispatch_execute_plan_posts_to_http_starter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            payload = received["payload"]
            assert isinstance(payload, dict)
            return json.dumps(
                {
                    "status": "ok",
                    "task_id": payload["task_request"]["task_id"],
                    "worker_id": payload["worker_id"],
                }
            ).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        received["timeout"] = timeout
        received["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(
        "inferedge_orchestrator.remote_dispatch.urllib.request.urlopen",
        fake_urlopen,
    )
    registry = {
        "schema_version": "inferedge-remote-worker-registry-v1",
        "workers": [
            {
                "worker_id": "http-worker",
                "status": "online",
                "endpoint_type": "http_request",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["jetson"],
                },
                "health": {"state": "healthy"},
                "metadata": {"endpoint_url": "http://worker.local/execute"},
            }
        ],
    }
    request = {
        "schema_version": "inferedge-remote-task-request-v1",
        "task_id": "task_http_001",
        "agent_id": "vision_agent",
        "required_backend": "onnxruntime",
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
        execute_plan=True,
        timeout_sec=2.0,
    )

    assert received["payload"]["schema_version"] == "inferedge-remote-http-task-v1"
    assert received["timeout"] == 2.0
    assert result["remote_execution"]["execution_requested"] is True
    assert result["remote_execution_plan"]["mode"] == "starter_execute"
    assert result["remote_execution_plan"]["network_execution_performed"] is True
    assert result["remote_execution_result"]["execution_performed"] is True
    assert result["remote_execution_result"]["transport"] == "http"
    assert result["remote_execution_result"]["status"] == "succeeded"
    assert result["remote_execution_result"]["http_status"] == 200
    assert result["remote_execution_result"]["response_json"] == {
        "status": "ok",
        "task_id": "task_http_001",
        "worker_id": "http-worker",
    }
    assert result["runtime_events"][-1]["event"] == "remote_execution_completed"


def test_remote_dispatch_execute_plan_classifies_missing_ssh_contract(
    tmp_path: Path,
) -> None:
    registry = {
        "schema_version": "inferedge-remote-worker-registry-v1",
        "workers": [
            {
                "worker_id": "ssh-worker",
                "status": "online",
                "endpoint_type": "ssh_command",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["jetson"],
                },
                "health": {"state": "healthy"},
            }
        ],
    }
    request = {
        "schema_version": "inferedge-remote-task-request-v1",
        "task_id": "task_ssh_001",
        "agent_id": "vision_agent",
        "required_backend": "onnxruntime",
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
        execute_plan=True,
    )

    assert result["remote_execution_plan"]["mode"] == "starter_execute"
    assert result["remote_execution_plan"]["network_execution_performed"] is False
    assert result["remote_execution_result"]["status"] == "failed"
    assert result["remote_execution_result"]["transport"] == "ssh"
    assert result["remote_execution_result"]["execution_performed"] is False
    assert result["remote_execution_result"]["error_category"] == "missing_ssh_contract"


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
