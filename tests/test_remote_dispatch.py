from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    assert result["runtime_events"][-1]["event"] == "remote_operation_summary_recorded"
    event_summary = result["remote_runtime_event_summary"]
    assert event_summary["schema_version"] == (
        "inferedge-remote-runtime-event-summary-v1"
    )
    assert event_summary["event_count"] == len(result["runtime_events"])
    assert event_summary["event_type_counts"] == {
        "remote_dispatch_selected": 1,
        "remote_operation_summary_recorded": 1,
    }
    assert event_summary["status_counts"] == {}
    assert event_summary["error_category_counts"] == {}
    assert event_summary["fallback_worker_ids"] == []
    assert event_summary["fallback_event_count"] == 0
    assert event_summary["fallback_recovered"] is False
    assert event_summary["final_status"] == "skipped"
    assert event_summary["production_remote_execution"] is False
    assert event_summary["evidence_role"] == (
        "remote_dispatch_runtime_event_compact_summary"
    )
    assert event_summary["latest_event"] == "remote_operation_summary_recorded"
    summary = result["remote_operation_summary"]
    assert summary["schema_version"] == "inferedge-remote-operation-summary-v1"
    assert summary["dispatch_status"] == "accepted"
    assert summary["selected_worker_id"] == "jetson-nano-01"
    assert summary["selected_worker_health_state"] == "healthy"
    assert summary["worker_count"] == 2
    assert summary["eligible_worker_count"] == 1
    assert summary["rejected_worker_count"] == 1
    assert summary["health_state_counts"] == {"healthy": 1, "constrained": 1}
    assert summary["execution_requested"] is False
    assert summary["execution_performed"] is False
    assert summary["remote_execution_status"] == "skipped"
    assert summary["fallback_final_status"] == "not_attempted"
    assert summary["final_status"] == "skipped"
    assert summary["production_remote_execution"] is False
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
    assert result["remote_operation_summary"]["dispatch_status"] == "rejected"
    assert result["remote_operation_summary"]["eligible_worker_count"] == 0
    assert result["remote_operation_summary"]["rejected_worker_count"] == 1
    assert result["remote_operation_summary"]["final_status"] == "skipped"
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
    assert [event["event"] for event in result["runtime_events"]] == [
        "remote_dispatch_selected",
        "remote_execution_completed",
        "remote_operation_summary_recorded",
    ]
    summary = result["remote_operation_summary"]
    assert summary["execution_requested"] is True
    assert summary["execution_performed"] is True
    assert summary["remote_execution_status"] == "succeeded"
    assert summary["final_status"] == "succeeded"


def test_remote_dispatch_execute_plan_falls_back_after_primary_connection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            payload = calls[-1]["payload"]
            assert isinstance(payload, dict)
            return json.dumps(
                {
                    "status": "ok",
                    "task_id": payload["task_request"]["task_id"],
                    "worker_id": payload["worker_id"],
                }
            ).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        calls.append({"url": request.full_url, "payload": payload, "timeout": timeout})
        if payload["worker_id"] == "primary-http-worker":
            raise urllib.error.URLError("primary refused")
        return FakeResponse()

    monkeypatch.setattr(
        "inferedge_orchestrator.remote_dispatch.urllib.request.urlopen",
        fake_urlopen,
    )
    registry = {
        "schema_version": "inferedge-remote-worker-registry-v1",
        "workers": [
            {
                "worker_id": "primary-http-worker",
                "status": "online",
                "endpoint_type": "http_request",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["cpu"],
                    "priority_capacity": 10,
                },
                "health": {"state": "healthy"},
                "metadata": {"endpoint_url": "http://primary.local/execute"},
            },
            {
                "worker_id": "fallback-http-worker",
                "status": "online",
                "endpoint_type": "http_request",
                "capabilities": {
                    "workers": ["onnxruntime"],
                    "backends": ["onnxruntime"],
                    "devices": ["cpu"],
                    "priority_capacity": 5,
                },
                "health": {"state": "healthy"},
                "metadata": {"endpoint_url": "http://fallback.local/execute"},
            },
        ],
    }
    request = {
        "schema_version": "inferedge-remote-task-request-v1",
        "task_id": "task_http_fallback_001",
        "agent_id": "vision_agent",
        "required_backend": "onnxruntime",
        "device_target": "cpu",
        "retry_policy": {
            "max_attempts": 2,
            "fallback_on": ["connection_error", "timeout"],
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
        execute_plan=True,
        timeout_sec=2.0,
    )

    assert [call["payload"]["worker_id"] for call in calls] == [
        "primary-http-worker",
        "fallback-http-worker",
    ]
    assert result["remote_execution_result"]["status"] == "failed"
    assert result["remote_execution_result"]["error_category"] == "connection_error"
    fallback = result["fallback_execution_result"]
    assert fallback["schema_version"] == "inferedge-remote-fallback-execution-v1"
    assert fallback["primary_worker_id"] == "primary-http-worker"
    assert fallback["attempted_worker_ids"] == ["fallback-http-worker"]
    assert fallback["final_status"] == "succeeded"
    assert fallback["attempts"][0]["status"] == "succeeded"
    assert fallback["attempts"][0]["fallback_attempt"] == 1
    assert result["retry_fallback_plan"]["fallback_execution_performed"] is True
    assert result["retry_fallback_plan"]["fallback_attempted_worker_ids"] == [
        "fallback-http-worker"
    ]
    assert result["retry_fallback_plan"]["last_execution_status"] == "succeeded"
    assert [event["event"] for event in result["runtime_events"]] == [
        "remote_dispatch_selected",
        "remote_execution_failed",
        "remote_fallback_execution_completed",
        "remote_operation_summary_recorded",
    ]
    event_summary = result["remote_runtime_event_summary"]
    assert event_summary["schema_version"] == (
        "inferedge-remote-runtime-event-summary-v1"
    )
    assert event_summary["event_count"] == 4
    assert event_summary["event_type_counts"] == {
        "remote_dispatch_selected": 1,
        "remote_execution_failed": 1,
        "remote_fallback_execution_completed": 1,
        "remote_operation_summary_recorded": 1,
    }
    assert event_summary["status_counts"] == {
        "failed": 1,
        "succeeded": 1,
    }
    assert event_summary["error_category_counts"] == {"connection_error": 1}
    assert event_summary["selected_worker_id"] == "primary-http-worker"
    assert event_summary["fallback_worker_ids"] == ["fallback-http-worker"]
    assert event_summary["fallback_event_count"] == 1
    assert event_summary["fallback_recovered"] is True
    assert event_summary["final_status"] == "succeeded"
    assert event_summary["production_remote_execution"] is False
    summary = result["remote_operation_summary"]
    assert summary["remote_execution_status"] == "failed"
    assert summary["remote_error_category"] == "connection_error"
    assert summary["fallback_requested"] is True
    assert summary["fallback_execution_performed"] is True
    assert summary["fallback_attempt_count"] == 1
    assert summary["fallback_final_status"] == "succeeded"
    assert summary["fallback_recovered"] is True
    assert summary["final_status"] == "succeeded"
    assert result["runtime_events"][-1]["event"] == "remote_operation_summary_recorded"


def test_remote_dispatch_execute_plan_against_local_http_worker(
    tmp_path: Path,
) -> None:
    port = _free_tcp_port()
    endpoint_url = f"http://127.0.0.1:{port}/execute"
    worker = subprocess.Popen(
        [
            sys.executable,
            "scripts/remote_http_worker.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_http_worker(port)
        registry = {
            "schema_version": "inferedge-remote-worker-registry-v1",
            "workers": [
                {
                    "worker_id": "local-http-worker",
                    "status": "online",
                    "endpoint_type": "http_request",
                    "capabilities": {
                        "workers": ["onnxruntime"],
                        "backends": ["onnxruntime"],
                        "devices": ["cpu"],
                    },
                    "health": {"state": "healthy"},
                    "metadata": {"endpoint_url": endpoint_url},
                }
            ],
        }
        request = {
            "schema_version": "inferedge-remote-task-request-v1",
            "task_id": "task_http_local_001",
            "agent_id": "vision_agent",
            "required_backend": "onnxruntime",
            "device_target": "cpu",
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

        execution = result["remote_execution_result"]
        assert execution["status"] == "succeeded"
        assert execution["execution_performed"] is True
        assert execution["transport"] == "http"
        assert execution["http_status"] == 200
        assert execution["response_json"]["schema_version"] == (
            "inferedge-remote-http-worker-response-v1"
        )
        assert execution["response_json"]["execution_status"] == "simulated_completed"
        assert execution["response_json"]["production_remote_execution"] is False
        assert [event["event"] for event in result["runtime_events"]] == [
            "remote_dispatch_selected",
            "remote_execution_completed",
            "remote_operation_summary_recorded",
        ]
        assert result["remote_operation_summary"]["final_status"] == "succeeded"
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=2)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=2)


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
    assert result["remote_operation_summary"]["remote_error_category"] == (
        "missing_ssh_contract"
    )
    assert result["remote_operation_summary"]["final_status"] == "failed"


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


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"local socket bind is not available in this environment: {exc}")
        return int(sock.getsockname()[1])


def _wait_for_http_worker(port: int) -> None:
    deadline = time.monotonic() + 4.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health",
                timeout=0.2,
            ) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"local HTTP worker did not become ready: {last_error}")
