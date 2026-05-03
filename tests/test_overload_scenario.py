from __future__ import annotations

from inferedge_orchestrator.config import load_config
from inferedge_orchestrator.scenarios import run_overload_comparison


def test_overload_comparison_protects_high_priority_latency() -> None:
    config = load_config("configs/phase3_overload.json")

    report = run_overload_comparison(config, frames=20, frame_interval_ms=10.0)

    effect = report["effect"]
    assert effect["protected_task"] == "detector"
    assert effect["p95_end_to_end_improvement_ms"] > 0
    assert effect["low_priority_drops"] > 0
    assert report["scheduled"]["overload_events"]


def test_overload_comparison_keeps_low_priority_drop_visible() -> None:
    config = load_config("configs/phase3_overload.json")

    report = run_overload_comparison(config, frames=20, frame_interval_ms=10.0)

    baseline_detector = report["baseline"]["tasks"]["detector"]
    scheduled_detector = report["scheduled"]["tasks"]["detector"]
    scheduled_classifier = report["scheduled"]["tasks"]["classifier"]
    assert scheduled_detector["p95_end_to_end_latency_ms"] < baseline_detector[
        "p95_end_to_end_latency_ms"
    ]
    assert scheduled_classifier["dropped"] > 0
