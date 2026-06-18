from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inferedge_orchestrator.sustained import validate_edgeenv_runtime_telemetry_feed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"feed not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"feed is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("feed must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Orchestrator's EdgeEnv runtime telemetry feed contract."
        )
    )
    parser.add_argument("--feed", required=True, help="EdgeEnv telemetry feed JSON")
    parser.add_argument(
        "--require-device-local-producer",
        action="store_true",
        help="Require candidate_context.producer lineage for device-local runs",
    )
    args = parser.parse_args(argv)

    try:
        feed = _load_json(Path(args.feed))
        validate_edgeenv_runtime_telemetry_feed(
            feed,
            require_device_local_producer=args.require_device_local_producer,
        )
    except ValueError as exc:
        print(f"EdgeEnv runtime telemetry feed contract failed: {exc}")
        return 2

    candidate_context = feed.get("candidate_context") or {}
    producer = candidate_context.get("producer") or {}
    device_local_sources = producer.get("device_local_producer_sources") or []
    producer_stage_by_task = producer.get("producer_stage_by_task") or {}
    producer_event_count = producer.get("producer_event_count")
    device_local_event_count = producer.get("device_local_event_count")
    operation = candidate_context.get("operation") or {}
    latency_budget_protection = operation.get("latency_budget_protection") or {}
    operation_timeline_summary = operation.get("operation_timeline_summary") or {}
    policy_pressure_summary = operation.get("policy_pressure_summary") or {}
    guard_alignment = feed.get("downstream_guard_alignment") or {}
    print("EdgeEnv runtime telemetry feed contract passed.")
    print(
        "operation_summary: "
        f"mode={feed.get('scenario_mode') or 'unknown'}; "
        f"max_queue={operation.get('max_total_queue_depth', operation.get('queue_depth', 'unknown'))}; "
        f"queue_pressure={operation.get('queue_pressure_state') or 'unknown'}; "
        f"deadline_missed={operation.get('deadline_missed_count', 0)}; "
        f"fallback={operation.get('fallback_count', 0)}; "
        f"dropped={operation.get('dropped_count', 0)}"
    )
    if guard_alignment:
        print(
            "producer_lineage_evidence_type: "
            f"{guard_alignment.get('producer_lineage_evidence_type')}"
        )
        print(
            "operation_evidence_candidates: "
            + ", ".join(
                str(item)
                for item in guard_alignment.get("operation_evidence_candidates", [])
            )
        )
    if device_local_sources:
        print(
            "device_local_producer_sources: "
            + ", ".join(str(item) for item in device_local_sources)
        )
    if producer_stage_by_task:
        stage_pairs = [
            f"{task}:{stage}"
            for task, stage in sorted(producer_stage_by_task.items())
        ]
        print("producer_stage_by_task: " + ", ".join(stage_pairs))
    if producer_event_count is not None and device_local_event_count is not None:
        print(
            "producer_event_count: "
            f"{producer_event_count}; device_local_event_count: "
            f"{device_local_event_count}"
        )
    if latency_budget_protection:
        protected = latency_budget_protection.get("protected_task_candidates") or []
        risky = latency_budget_protection.get("tasks_with_latency_budget_risk") or []
        reasons = latency_budget_protection.get("risk_reasons") or []
        print(
            "latency_budget_protection: "
            f"protected={','.join(str(item) for item in protected) or 'none'}; "
            f"risk={','.join(str(item) for item in risky) or 'none'}; "
            f"reasons={','.join(str(item) for item in reasons) or 'none'}"
        )
    if operation_timeline_summary:
        latency = operation_timeline_summary.get("latency") or {}
        affected = operation_timeline_summary.get("affected_tasks") or {}
        review_hints = operation_timeline_summary.get("review_hints") or []
        stale_drop = operation_timeline_summary.get("stale_drop") or {}
        policy_pressure = (
            policy_pressure_summary
            or operation_timeline_summary.get("policy_pressure")
            or {}
        )
        scheduler_fairness = operation_timeline_summary.get(
            "scheduler_fairness"
        ) or {}
        print(
            "operation_timeline: "
            f"review_hints={_format_list(review_hints)}; "
            f"scheduler_delay={_format_list(affected.get('scheduler_delay'))}; "
            f"fallback={_format_list(affected.get('fallback'))}; "
            f"deadline_missed={_format_list(affected.get('deadline_missed'))}; "
            f"stale_drop={stale_drop.get('stale_drop_count', 0)}; "
            f"stale_drop_tasks={_format_list(affected.get('stale_drop'))}; "
            f"max_queue_wait_ms={latency.get('max_queue_wait_ms', 0)}"
        )
        if policy_pressure:
            print(
                "policy_pressure: "
                f"decisions={policy_pressure.get('decision_count', 0)}; "
                "limited="
                f"{_format_list(policy_pressure.get('limited_tasks'))}; "
                "protected="
                f"{_format_list(policy_pressure.get('protected_tasks'))}; "
                "fallback="
                f"{_format_list(policy_pressure.get('fallback_tasks'))}; "
                "markers="
                f"{_format_list(policy_pressure.get('pressure_markers'))}"
            )
        if scheduler_fairness:
            print(
                "scheduler_fairness: "
                "protected="
                f"{_format_list(scheduler_fairness.get('protected_high_priority_tasks'))}; "
                "starvation_risk="
                f"{_format_list(scheduler_fairness.get('tasks_with_starvation_risk'))}; "
                "degraded="
                f"{_format_list(scheduler_fairness.get('tasks_with_degradation'))}"
            )
    return 0


def _format_list(value: Any) -> str:
    if not isinstance(value, list):
        return "none"
    items = [str(item) for item in value if isinstance(item, str) and item]
    return ",".join(items) if items else "none"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
