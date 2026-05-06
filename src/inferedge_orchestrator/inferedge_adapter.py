from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from inferedge_orchestrator.config import OrchestratorConfig


LATENCY_KEYS = (
    "expected_latency_ms",
    "mean_latency_ms",
    "p95_latency_ms",
    "latency_ms",
)


def load_inferedge_result(path: str | Path) -> dict[str, Any]:
    result_path = Path(path)
    loaded = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("InferEdge result root must be a JSON object")
    return loaded


def extract_expected_latency_ms(result: dict[str, Any]) -> float:
    found = _find_numeric_latency(result)
    if found is None:
        raise ValueError(
            "Could not find expected latency. Expected one of: "
            + ", ".join(LATENCY_KEYS)
        )
    return found


def recommend_latency_budget_ms(
    expected_latency_ms: float,
    *,
    multiplier: float = 1.5,
    minimum_budget_ms: float = 1.0,
) -> float:
    if expected_latency_ms <= 0:
        raise ValueError("expected_latency_ms must be > 0")
    if multiplier < 1.0:
        raise ValueError("multiplier must be >= 1.0")
    budget = max(expected_latency_ms * multiplier, minimum_budget_ms)
    return float(math.ceil(budget))


def build_config_from_inferedge_result(
    result: dict[str, Any],
    *,
    task_name: str,
    model_path: str,
    priority: int,
    target_fps: float,
    queue_size: int,
    drop_policy: str = "drop_oldest",
    worker: str = "onnxruntime",
    engine_path: str | None = None,
    worker_options: dict[str, Any] | None = None,
    budget_multiplier: float = 1.5,
) -> dict[str, Any]:
    expected_latency_ms = extract_expected_latency_ms(result)
    latency_budget_ms = recommend_latency_budget_ms(
        expected_latency_ms,
        multiplier=budget_multiplier,
    )
    task: dict[str, Any] = {
        "name": task_name,
        "model_path": model_path,
        "priority": priority,
        "target_fps": target_fps,
        "latency_budget_ms": latency_budget_ms,
        "queue_size": queue_size,
        "drop_policy": drop_policy,
        "worker": worker,
    }
    if engine_path is not None:
        task["engine_path"] = engine_path
    if worker_options is not None:
        task["worker_options"] = worker_options

    config = {
        "run": {
            "name": "from_inferedge_result",
            "input_source": "dummy",
            "overload_backlog_threshold": max(2, queue_size),
            "source": {
                "type": "inferedge_result_json",
                "relationship": (
                    "InferEdge validates deployment readiness; "
                    "InferEdgeOrchestrator controls runtime operation after deployment."
                ),
            },
        },
        "tasks": [task],
    }
    OrchestratorConfig.from_dict(config)
    return config


def write_config_from_inferedge_result(
    result_path: str | Path,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    result = load_inferedge_result(result_path)
    config = build_config_from_inferedge_result(result, **kwargs)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    return config


def _find_numeric_latency(value: object) -> float | None:
    if isinstance(value, dict):
        for key in LATENCY_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, int | float):
                return float(candidate)
        for nested in value.values():
            found = _find_numeric_latency(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_numeric_latency(nested)
            if found is not None:
                return found
    return None
