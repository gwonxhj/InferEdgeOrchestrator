from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = "inferedge-remote-worker-registry-v1"
REQUEST_SCHEMA_VERSION = "inferedge-remote-task-request-v1"
RESULT_SCHEMA_VERSION = "inferedge-remote-dispatch-result-v1"


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
    runtime_event = {
        "event": "remote_dispatch_selected" if selected else "remote_dispatch_rejected",
        "task_id": request.get("task_id"),
        "agent_id": request.get("agent_id"),
        "selected_worker_id": selected.worker_id if selected else None,
        "reason": reason,
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "dispatch_status": status,
        "selected_worker_id": selected.worker_id if selected else None,
        "decision_reason": reason,
        "remote_execution": {
            "mode": "file_contract_starter",
            "production_remote_execution": False,
            "registry_path": registry_path,
            "request_path": request_path,
        },
        "remote_execution_plan": _build_remote_execution_plan(selected, request),
        "worker_selection": worker_selection,
        "retry_fallback_plan": _build_retry_fallback_plan(request, worker_selection),
        "task_request": request,
        "worker_health_snapshot": {
            "schema_version": "inferedge-remote-worker-health-v1",
            "workers": worker_snapshot,
        },
        "runtime_events": [runtime_event],
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
) -> dict[str, Any]:
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
    return {
        "schema_version": "inferedge-remote-retry-fallback-plan-v1",
        "max_attempts": max_attempts,
        "fallback_on": [str(item) for item in fallback_on],
        "primary_worker_id": worker_selection.get("selected_worker_id"),
        "fallback_worker_ids": worker_selection.get("fallback_worker_ids", []),
        "execution_performed": False,
    }


def _build_remote_execution_plan(
    selected: RemoteWorker | None,
    request: dict[str, Any],
) -> dict[str, Any]:
    if selected is None:
        return {
            "schema_version": "inferedge-remote-execution-plan-v1",
            "mode": "no_worker_selected",
            "network_execution_performed": False,
        }
    transport = _transport_from_endpoint_type(selected.endpoint_type)
    return {
        "schema_version": "inferedge-remote-execution-plan-v1",
        "mode": "plan_only",
        "network_execution_performed": False,
        "transport": transport,
        "endpoint_type": selected.endpoint_type,
        "selected_worker_id": selected.worker_id,
        "task_id": request.get("task_id"),
        "agent_id": request.get("agent_id"),
        "note": (
            "This is a remote execution starter plan. It does not open SSH/HTTP "
            "connections or run production remote workers."
        ),
    }


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


def _transport_from_endpoint_type(endpoint_type: str) -> str:
    if endpoint_type.startswith("ssh"):
        return "ssh"
    if endpoint_type.startswith("http"):
        return "http"
    return "file_contract"
