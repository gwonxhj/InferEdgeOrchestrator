from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = "inferedge-remote-worker-registry-v1"
REQUEST_SCHEMA_VERSION = "inferedge-remote-task-request-v1"
RESULT_SCHEMA_VERSION = "inferedge-remote-dispatch-result-v1"
EXECUTION_RESULT_SCHEMA_VERSION = "inferedge-remote-execution-result-v1"


@dataclass(frozen=True)
class RemoteWorker:
    worker_id: str
    status: str
    endpoint_type: str
    capabilities: dict[str, Any]
    health: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RemoteWorker":
        worker_id = str(value.get("worker_id", ""))
        if not worker_id:
            raise ValueError("remote worker requires worker_id")
        status = str(value.get("status", "unknown"))
        endpoint_type = str(value.get("endpoint_type", "file_contract"))
        capabilities = value.get("capabilities", {})
        health = value.get("health", {})
        metadata = value.get("metadata", {})
        if not isinstance(capabilities, dict):
            raise ValueError(f"{worker_id}: capabilities must be a mapping")
        if not isinstance(health, dict):
            raise ValueError(f"{worker_id}: health must be a mapping")
        if not isinstance(metadata, dict):
            raise ValueError(f"{worker_id}: metadata must be a mapping")
        return cls(
            worker_id=worker_id,
            status=status,
            endpoint_type=endpoint_type,
            capabilities=capabilities,
            health=health,
            metadata=metadata,
        )

    @property
    def health_state(self) -> str:
        return str(self.health.get("state", "unknown"))

    def supports(self, request: dict[str, Any]) -> bool:
        backend = _optional_string(
            request.get("required_backend", request.get("worker"))
        )
        device = _optional_string(request.get("device_target"))
        workers = _string_set(self.capabilities.get("workers"))
        backends = _string_set(self.capabilities.get("backends"))
        devices = _string_set(self.capabilities.get("devices"))
        if backend and backend not in workers and backend not in backends:
            return False
        if device and device not in devices:
            return False
        return True


def dispatch_remote_task(
    *,
    registry_path: str | Path,
    request_path: str | Path,
    output_path: str | Path,
    execute_plan: bool = False,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    registry = _load_json(Path(registry_path))
    request = _load_json(Path(request_path))
    _validate_registry(registry)
    _validate_request(request)
    workers = [RemoteWorker.from_dict(item) for item in registry.get("workers", [])]
    selected, reason, worker_selection = _select_worker(workers, request)
    result = _build_result(
        request=request,
        workers=workers,
        selected=selected,
        reason=reason,
        worker_selection=worker_selection,
        registry_path=str(registry_path),
        request_path=str(request_path),
        execute_plan=execute_plan,
        timeout_sec=timeout_sec,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _select_worker(
    workers: list[RemoteWorker],
    request: dict[str, Any],
) -> tuple[RemoteWorker | None, str, dict[str, Any]]:
    evaluations = [_evaluate_worker(worker, request) for worker in workers]
    candidates = [
        item["worker"]
        for item in evaluations
        if item["eligible"]
    ]
    if not candidates:
        return (
            None,
            "no online worker matched backend/device health requirements",
            _build_worker_selection(None, [], evaluations),
        )
    candidates.sort(
        key=lambda worker: (
            _health_rank(worker.health_state),
            -float(worker.capabilities.get("priority_capacity", 0)),
            worker.worker_id,
        )
    )
    selected = candidates[0]
    return (
        selected,
        "selected online worker matching backend/device requirements",
        _build_worker_selection(selected, candidates, evaluations),
    )


def _build_result(
    *,
    request: dict[str, Any],
    workers: list[RemoteWorker],
    selected: RemoteWorker | None,
    reason: str,
    worker_selection: dict[str, Any],
    registry_path: str,
    request_path: str,
    execute_plan: bool,
    timeout_sec: float,
) -> dict[str, Any]:
    status = "accepted" if selected is not None else "rejected"
    worker_snapshot = {
        worker.worker_id: {
            "status": worker.status,
            "health_state": worker.health_state,
            "endpoint_type": worker.endpoint_type,
            "capabilities": worker.capabilities,
            "metadata": worker.metadata,
        }
        for worker in workers
    }
    remote_execution_result = _execute_remote_plan(
        selected=selected,
        request=request,
        execute_plan=execute_plan,
        timeout_sec=timeout_sec,
    )
    fallback_execution_result = _execute_fallback_plan(
        workers=workers,
        request=request,
        worker_selection=worker_selection,
        primary_execution_result=remote_execution_result,
        execute_plan=execute_plan,
        timeout_sec=timeout_sec,
    )
    remote_execution_plan = _build_remote_execution_plan(
        selected,
        request,
        execution_result=remote_execution_result,
    )
    retry_fallback_plan = _build_retry_fallback_plan(
        request,
        worker_selection,
        execution_result=remote_execution_result,
        fallback_execution_result=fallback_execution_result,
    )
    runtime_events = [
        {
            "event": (
                "remote_dispatch_selected" if selected else "remote_dispatch_rejected"
            ),
            "task_id": request.get("task_id"),
            "agent_id": request.get("agent_id"),
            "selected_worker_id": selected.worker_id if selected else None,
            "reason": reason,
        }
    ]
    if remote_execution_result["execution_requested"]:
        runtime_events.append(
            {
                "event": "remote_execution_completed"
                if remote_execution_result["status"] == "succeeded"
                else "remote_execution_failed",
                "task_id": request.get("task_id"),
                "agent_id": request.get("agent_id"),
                "selected_worker_id": selected.worker_id if selected else None,
                "transport": remote_execution_result["transport"],
                "status": remote_execution_result["status"],
                "error_category": remote_execution_result.get("error_category"),
            }
        )
    if fallback_execution_result:
        for attempt in fallback_execution_result["attempts"]:
            runtime_events.append(
                {
                    "event": "remote_fallback_execution_completed"
                    if attempt["status"] == "succeeded"
                    else "remote_fallback_execution_failed",
                    "task_id": request.get("task_id"),
                    "agent_id": request.get("agent_id"),
                    "selected_worker_id": attempt.get("selected_worker_id"),
                    "primary_worker_id": fallback_execution_result["primary_worker_id"],
                    "transport": attempt.get("transport"),
                    "status": attempt["status"],
                    "error_category": attempt.get("error_category"),
                    "fallback_attempt": attempt["fallback_attempt"],
                }
            )
    remote_operation_summary = _build_remote_operation_summary(
        dispatch_status=status,
        selected_worker=selected,
        decision_reason=reason,
        worker_selection=worker_selection,
        workers=workers,
        remote_execution_result=remote_execution_result,
        fallback_execution_result=fallback_execution_result,
    )
    runtime_events.append(
        {
            "event": "remote_operation_summary_recorded",
            "task_id": request.get("task_id"),
            "agent_id": request.get("agent_id"),
            "selected_worker_id": selected.worker_id if selected else None,
            "final_status": remote_operation_summary["final_status"],
            "fallback_final_status": remote_operation_summary["fallback_final_status"],
        }
    )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "dispatch_status": status,
        "selected_worker_id": selected.worker_id if selected else None,
        "decision_reason": reason,
        "remote_execution": {
            "mode": "file_contract_starter",
            "production_remote_execution": False,
            "execution_requested": execute_plan,
            "registry_path": registry_path,
            "request_path": request_path,
        },
        "remote_execution_plan": remote_execution_plan,
        "remote_execution_result": remote_execution_result,
        "worker_selection": worker_selection,
        "retry_fallback_plan": retry_fallback_plan,
        "task_request": request,
        "worker_health_snapshot": {
            "schema_version": "inferedge-remote-worker-health-v1",
            "workers": worker_snapshot,
        },
        "remote_operation_summary": remote_operation_summary,
        "runtime_events": runtime_events,
    }
    if fallback_execution_result:
        result["fallback_execution_result"] = fallback_execution_result
    return result


def _build_remote_operation_summary(
    *,
    dispatch_status: str,
    selected_worker: RemoteWorker | None,
    decision_reason: str,
    worker_selection: dict[str, Any],
    workers: list[RemoteWorker],
    remote_execution_result: dict[str, Any],
    fallback_execution_result: dict[str, Any] | None,
) -> dict[str, Any]:
    evaluations = worker_selection.get("evaluations", [])
    if not isinstance(evaluations, list):
        evaluations = []
    eligible_count = sum(
        1 for item in evaluations if isinstance(item, dict) and item.get("eligible")
    )
    health_counts: dict[str, int] = {}
    for worker in workers:
        health_counts[worker.health_state] = (
            health_counts.get(worker.health_state, 0) + 1
        )

    fallback_attempts = (
        fallback_execution_result.get("attempts", [])
        if isinstance(fallback_execution_result, dict)
        else []
    )
    fallback_final_status = (
        str(fallback_execution_result.get("final_status"))
        if isinstance(fallback_execution_result, dict)
        and fallback_execution_result.get("final_status") is not None
        else "not_attempted"
    )
    remote_status = str(remote_execution_result.get("status", "unknown"))
    final_status = (
        fallback_final_status
        if fallback_final_status != "not_attempted"
        else remote_status
    )
    fallback_performed = any(
        bool(attempt.get("execution_performed"))
        for attempt in fallback_attempts
        if isinstance(attempt, dict)
    )
    return {
        "schema_version": "inferedge-remote-operation-summary-v1",
        "dispatch_status": dispatch_status,
        "selected_worker_id": selected_worker.worker_id if selected_worker else None,
        "selected_worker_health_state": (
            selected_worker.health_state if selected_worker else None
        ),
        "decision_reason": decision_reason,
        "worker_count": len(workers),
        "eligible_worker_count": eligible_count,
        "rejected_worker_count": max(len(workers) - eligible_count, 0),
        "health_state_counts": health_counts,
        "execution_requested": bool(remote_execution_result.get("execution_requested")),
        "execution_performed": bool(remote_execution_result.get("execution_performed")),
        "remote_execution_status": remote_status,
        "remote_error_category": remote_execution_result.get("error_category"),
        "fallback_requested": bool(
            isinstance(fallback_execution_result, dict)
            and fallback_execution_result.get("fallback_requested")
        ),
        "fallback_execution_performed": fallback_performed,
        "fallback_attempt_count": len(fallback_attempts),
        "fallback_final_status": fallback_final_status,
        "fallback_recovered": fallback_final_status == "succeeded",
        "final_status": final_status,
        "production_remote_execution": False,
        "evidence_role": "remote_worker_selection_and_starter_execution_evidence",
    }


def _evaluate_worker(worker: RemoteWorker, request: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if worker.status != "online":
        reasons.append(f"worker status is {worker.status}")
    if worker.health_state not in {"healthy", "constrained"}:
        reasons.append(f"worker health is {worker.health_state}")
    if not worker.supports(request):
        reasons.append("worker capabilities do not match backend/device request")
    return {
        "worker": worker,
        "worker_id": worker.worker_id,
        "eligible": not reasons,
        "status": worker.status,
        "health_state": worker.health_state,
        "endpoint_type": worker.endpoint_type,
        "decision_reason": "eligible" if not reasons else "; ".join(reasons),
    }


def _build_worker_selection(
    selected: RemoteWorker | None,
    candidates: list[RemoteWorker],
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_worker_id = selected.worker_id if selected else None
    fallback_candidates = [
        worker.worker_id
        for worker in candidates
        if worker.worker_id != selected_worker_id
    ]
    return {
        "schema_version": "inferedge-remote-worker-selection-v1",
        "selected_worker_id": selected_worker_id,
        "candidate_worker_ids": [worker.worker_id for worker in candidates],
        "fallback_worker_ids": fallback_candidates,
        "evaluations": [
            {
                "worker_id": item["worker_id"],
                "eligible": item["eligible"],
                "status": item["status"],
                "health_state": item["health_state"],
                "endpoint_type": item["endpoint_type"],
                "decision_reason": item["decision_reason"],
            }
            for item in evaluations
        ],
    }


def _build_retry_fallback_plan(
    request: dict[str, Any],
    worker_selection: dict[str, Any],
    execution_result: dict[str, Any],
    fallback_execution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    max_attempts, fallback_on = _normalized_retry_policy(request)
    plan = {
        "schema_version": "inferedge-remote-retry-fallback-plan-v1",
        "max_attempts": max_attempts,
        "fallback_on": fallback_on,
        "primary_worker_id": worker_selection.get("selected_worker_id"),
        "fallback_worker_ids": worker_selection.get("fallback_worker_ids", []),
        "execution_performed": execution_result["execution_performed"],
        "last_execution_status": execution_result["status"],
    }
    if fallback_execution_result:
        plan.update(
            {
                "fallback_execution_performed": any(
                    attempt["execution_performed"]
                    for attempt in fallback_execution_result["attempts"]
                ),
                "fallback_attempted_worker_ids": fallback_execution_result[
                    "attempted_worker_ids"
                ],
                "fallback_final_status": fallback_execution_result["final_status"],
                "last_execution_status": fallback_execution_result["final_status"],
            }
        )
    else:
        plan["fallback_execution_performed"] = False
    return plan


def _build_remote_execution_plan(
    selected: RemoteWorker | None,
    request: dict[str, Any],
    *,
    execution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if selected is None:
        return {
            "schema_version": "inferedge-remote-execution-plan-v1",
            "mode": "no_worker_selected",
            "network_execution_performed": False,
        }
    transport = _transport_from_endpoint_type(selected.endpoint_type)
    execution_requested = bool(
        execution_result and execution_result["execution_requested"]
    )
    return {
        "schema_version": "inferedge-remote-execution-plan-v1",
        "mode": "starter_execute" if execution_requested else "plan_only",
        "network_execution_performed": bool(
            execution_result
            and execution_result["execution_performed"]
            and transport in {"http", "ssh"}
        ),
        "transport": transport,
        "endpoint_type": selected.endpoint_type,
        "selected_worker_id": selected.worker_id,
        "task_id": request.get("task_id"),
        "agent_id": request.get("agent_id"),
        "note": (
            "This is a remote execution starter plan. It does not open SSH/HTTP "
            "connections unless execute_plan is explicitly enabled, and it does "
            "not run production remote workers."
        ),
    }


def _execute_remote_plan(
    *,
    selected: RemoteWorker | None,
    request: dict[str, Any],
    execute_plan: bool,
    timeout_sec: float,
) -> dict[str, Any]:
    if selected is None:
        return _execution_result(
            request=request,
            selected=None,
            execute_plan=execute_plan,
            status="skipped",
            execution_performed=False,
            error_category="no_worker_selected",
        )
    transport = _transport_from_endpoint_type(selected.endpoint_type)
    if not execute_plan:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=False,
            status="skipped",
            execution_performed=False,
            transport=transport,
            error_category="execution_not_requested",
        )
    started = time.monotonic()
    if transport == "http":
        result = _execute_http_request(selected, request, timeout_sec)
    elif transport == "ssh":
        result = _execute_ssh_command(selected, request, timeout_sec)
    else:
        result = _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="skipped",
            execution_performed=False,
            transport=transport,
            error_category="unsupported_starter_transport",
            error_message="file_contract workers are selection-only in this starter",
        )
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result


def _execute_fallback_plan(
    *,
    workers: list[RemoteWorker],
    request: dict[str, Any],
    worker_selection: dict[str, Any],
    primary_execution_result: dict[str, Any],
    execute_plan: bool,
    timeout_sec: float,
) -> dict[str, Any] | None:
    if not _should_try_fallback(
        request=request,
        worker_selection=worker_selection,
        primary_execution_result=primary_execution_result,
        execute_plan=execute_plan,
    ):
        return None

    max_attempts, _fallback_on = _normalized_retry_policy(request)
    fallback_limit = max_attempts - 1
    worker_by_id = {worker.worker_id: worker for worker in workers}
    attempts: list[dict[str, Any]] = []
    for fallback_worker_id in worker_selection.get("fallback_worker_ids", []):
        if len(attempts) >= fallback_limit:
            break
        fallback_worker = worker_by_id.get(fallback_worker_id)
        if fallback_worker is None:
            continue
        attempt = _execute_remote_plan(
            selected=fallback_worker,
            request=request,
            execute_plan=True,
            timeout_sec=timeout_sec,
        )
        attempt["fallback_attempt"] = len(attempts) + 1
        attempt["fallback_for_worker_id"] = primary_execution_result.get(
            "selected_worker_id"
        )
        attempts.append(attempt)
        if attempt["status"] == "succeeded":
            break

    if not attempts:
        return None

    return {
        "schema_version": "inferedge-remote-fallback-execution-v1",
        "fallback_requested": True,
        "fallback_reason": primary_execution_result.get("error_category")
        or primary_execution_result["status"],
        "primary_worker_id": primary_execution_result.get("selected_worker_id"),
        "attempted_worker_ids": [
            str(attempt.get("selected_worker_id")) for attempt in attempts
        ],
        "final_status": attempts[-1]["status"],
        "attempts": attempts,
        "production_remote_execution": False,
    }


def _should_try_fallback(
    *,
    request: dict[str, Any],
    worker_selection: dict[str, Any],
    primary_execution_result: dict[str, Any],
    execute_plan: bool,
) -> bool:
    if not execute_plan:
        return False
    if primary_execution_result["status"] == "succeeded":
        return False
    if not worker_selection.get("fallback_worker_ids"):
        return False
    max_attempts, fallback_on = _normalized_retry_policy(request)
    if max_attempts <= 1:
        return False
    error_category = primary_execution_result.get("error_category")
    if error_category:
        return str(error_category) in fallback_on
    return primary_execution_result["status"] in fallback_on


def _execute_http_request(
    selected: RemoteWorker,
    request: dict[str, Any],
    timeout_sec: float,
) -> dict[str, Any]:
    endpoint_url = _optional_string(
        selected.metadata.get("endpoint_url", request.get("endpoint_url"))
    )
    if not endpoint_url:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=False,
            transport="http",
            error_category="missing_endpoint_url",
            error_message="http_request worker requires metadata.endpoint_url",
        )
    payload = {
        "schema_version": "inferedge-remote-http-task-v1",
        "worker_id": selected.worker_id,
        "task_request": request,
    }
    body = json.dumps(payload).encode("utf-8")
    http_request = urllib.request.Request(
        endpoint_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_sec) as response:
            response_body = response.read().decode("utf-8")
            response_json = _maybe_json(response_body)
            return _execution_result(
                request=request,
                selected=selected,
                execute_plan=True,
                status="succeeded",
                execution_performed=True,
                transport="http",
                http_status=int(response.status),
                response_json=response_json,
                response_body=response_body if response_json is None else None,
            )
    except TimeoutError as exc:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=True,
            transport="http",
            error_category="timeout",
            error_message=str(exc),
        )
    except urllib.error.HTTPError as exc:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=True,
            transport="http",
            http_status=int(exc.code),
            error_category="http_error",
            error_message=str(exc),
        )
    except urllib.error.URLError as exc:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=True,
            transport="http",
            error_category="connection_error",
            error_message=str(exc.reason),
        )


def _execute_ssh_command(
    selected: RemoteWorker,
    request: dict[str, Any],
    timeout_sec: float,
) -> dict[str, Any]:
    ssh_host = _optional_string(selected.metadata.get("ssh_host", request.get("ssh_host")))
    command = _optional_string(
        selected.metadata.get("ssh_command", request.get("remote_command"))
    )
    if not ssh_host or not command:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=False,
            transport="ssh",
            error_category="missing_ssh_contract",
            error_message="ssh_command worker requires metadata.ssh_host and metadata.ssh_command",
        )
    try:
        completed = subprocess.run(
            ["ssh", ssh_host, command],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return _execution_result(
            request=request,
            selected=selected,
            execute_plan=True,
            status="failed",
            execution_performed=True,
            transport="ssh",
            error_category="timeout",
            error_message=str(exc),
        )
    status = "succeeded" if completed.returncode == 0 else "failed"
    return _execution_result(
        request=request,
        selected=selected,
        execute_plan=True,
        status=status,
        execution_performed=True,
        transport="ssh",
        exit_code=completed.returncode,
        stdout=completed.stdout[-2000:] if completed.stdout else "",
        stderr=completed.stderr[-2000:] if completed.stderr else "",
        error_category=None if status == "succeeded" else "remote_command_failed",
    )


def _execution_result(
    *,
    request: dict[str, Any],
    selected: RemoteWorker | None,
    execute_plan: bool,
    status: str,
    execution_performed: bool,
    transport: str | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
    http_status: int | None = None,
    response_json: dict[str, Any] | list[Any] | None = None,
    response_body: str | None = None,
    exit_code: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": EXECUTION_RESULT_SCHEMA_VERSION,
        "execution_requested": execute_plan,
        "execution_performed": execution_performed,
        "production_remote_execution": False,
        "status": status,
        "transport": transport,
        "selected_worker_id": selected.worker_id if selected else None,
        "task_id": request.get("task_id"),
        "agent_id": request.get("agent_id"),
    }
    optional_values = {
        "error_category": error_category,
        "error_message": error_message,
        "http_status": http_status,
        "response_json": response_json,
        "response_body": response_body,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    result.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    return result


def _maybe_json(value: str) -> dict[str, Any] | list[Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported remote worker registry schema_version")
    workers = registry.get("workers")
    if not isinstance(workers, list) or not workers:
        raise ValueError("remote worker registry requires a non-empty workers list")


def _validate_request(request: dict[str, Any]) -> None:
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError("unsupported remote task request schema_version")
    if not request.get("task_id"):
        raise ValueError("remote task request requires task_id")
    if not request.get("agent_id"):
        raise ValueError("remote task request requires agent_id")


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return data


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _health_rank(state: str) -> int:
    return {"healthy": 0, "constrained": 1}.get(state, 99)


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalized_retry_policy(request: dict[str, Any]) -> tuple[int, list[str]]:
    retry_policy = request.get("retry_policy", {})
    if not isinstance(retry_policy, dict):
        retry_policy = {}
    max_attempts = _positive_int(retry_policy.get("max_attempts"), default=1)
    fallback_on = retry_policy.get(
        "fallback_on",
        ["timeout", "worker_unhealthy", "runtime_error"],
    )
    if not isinstance(fallback_on, list):
        fallback_on = ["timeout", "worker_unhealthy", "runtime_error"]
    return max_attempts, [str(item) for item in fallback_on]


def _transport_from_endpoint_type(endpoint_type: str) -> str:
    if endpoint_type.startswith("ssh"):
        return "ssh"
    if endpoint_type.startswith("http"):
        return "http"
    return "file_contract"
