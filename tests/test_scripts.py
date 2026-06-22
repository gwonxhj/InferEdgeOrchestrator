from __future__ import annotations

import json
import stat
from pathlib import Path

from inferedge_orchestrator.config import load_config
from inferedge_orchestrator.sustained import write_multi_workload_sustained
from scripts.check_edgeenv_runtime_feed_contract import main as feed_contract_main
from scripts.create_tensorrt_diverse_onnx import write_models


def test_jetson_tensorrt_smoke_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT smoke script should be executable"
    assert "configs/jetson_tensorrt_smoke.json" in text
    assert "ENGINE_PATH" in text
    assert "DEPENDENCY_PATH" in text
    assert "VALIDATION_PATH" in text
    assert "RUNTIME_TELEMETRY_PATH" in text
    assert "CAPTURE_TEGRASTATS" in text
    assert "/usr/src/tensorrt/bin/trtexec" in text
    assert "/usr/local/cuda/bin/nvcc" in text
    assert "PASS_TENSORRT_INFERENCE" in text
    assert "PASS_TENSORRT_TELEMETRY" in text
    assert "tensorrt_inputs" in text
    assert "output_preview" in text
    assert "result_events" in text
    assert "host/device buffer allocation" in text
    assert "tensor address binding" in text
    assert "TensorRT inference execution" in text


def test_edgeenv_runtime_feed_contract_checker_passes_device_local_feed(
    tmp_path,
    capsys,
) -> None:
    config = load_config(
        "configs/agent_multi_workload_sustained_device_local.json"
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    feed_path = tmp_path / "edgeenv_runtime_telemetry_feed.json"
    feed_path.write_text(
        json.dumps(
            report["edgeenv_runtime_telemetry_feed"],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = feed_contract_main(
        [
            "--feed",
            str(feed_path),
            "--require-device-local-producer",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "EdgeEnv runtime telemetry feed contract passed" in out
    assert "operation_summary: mode=device_local;" in out
    assert "max_queue=" in out
    assert "queue_pressure=" in out
    assert "deadline_missed=" in out
    assert "fallback=" in out
    assert "dropped=" in out
    assert (
        "producer_lineage_evidence_type: "
        "edgeenv_orchestrator_producer_lineage"
    ) in out
    assert (
        "operation_evidence_candidates: runtime_queue_overload, "
        "runtime_thermal_instability, "
        "edgeenv_orchestrator_worker_health_trend"
    ) in out
    assert "device_local_producer_sources" in out
    assert "producer_stage_by_task" in out
    assert "producer_event_count" in out
    assert "latency_budget_protection:" in out
    assert "protected=safety_monitor_agent" in out
    assert "operation_timeline:" in out
    assert "review_hints=" in out
    assert "scheduler_delay=" in out
    assert "stale_drop=" in out
    assert "stale_drop_tasks=" in out
    assert "max_queue_wait_ms=" in out
    assert "pressure_window:" in out
    assert "first_read=review_sustained_pressure_window" in out
    assert "protected=safety_monitor_agent" in out
    assert "policy_pressure:" in out
    assert "decisions=" in out
    assert "limited=" in out
    assert "markers=" in out
    assert "scheduler_fairness:" in out
    assert "starvation_risk=" in out
    assert "degraded=" in out


def test_edgeenv_runtime_feed_contract_checker_fails_bad_guard_alignment(
    tmp_path,
    capsys,
) -> None:
    config = load_config(
        "configs/agent_multi_workload_sustained_device_local.json"
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    feed = report["edgeenv_runtime_telemetry_feed"]
    feed["downstream_guard_alignment"][
        "producer_lineage_evidence_type"
    ] = "runtime_queue_overload"
    feed_path = tmp_path / "edgeenv_runtime_telemetry_feed.json"
    feed_path.write_text(
        json.dumps(feed, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    result = feed_contract_main(
        [
            "--feed",
            str(feed_path),
            "--require-device-local-producer",
        ]
    )

    assert result == 2
    assert (
        "producer_lineage_evidence_type must be "
        "edgeenv_orchestrator_producer_lineage"
    ) in capsys.readouterr().out


def test_edgeenv_runtime_feed_contract_checker_fails_missing_producer(
    tmp_path,
    capsys,
) -> None:
    config = load_config(
        "configs/agent_multi_workload_sustained_device_local.json"
    )
    report = write_multi_workload_sustained(
        config,
        output=tmp_path / "report.json",
        frames=4,
    )
    feed = report["edgeenv_runtime_telemetry_feed"]
    feed["candidate_context"].pop("producer")
    feed_path = tmp_path / "edgeenv_runtime_telemetry_feed.json"
    feed_path.write_text(
        json.dumps(feed, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    result = feed_contract_main(
        [
            "--feed",
            str(feed_path),
            "--require-device-local-producer",
        ]
    )

    assert result == 2
    assert "candidate_context.producer is required" in capsys.readouterr().out


def test_jetson_tensorrt_contention_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt_contention.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT contention script should be executable"
    assert "configs/jetson_tensorrt_contention.json" in text
    assert "ENGINE_PATH" in text
    assert "TELEMETRY_PATH" in text
    assert "VALIDATION_PATH" in text
    assert "CAPTURE_TEGRASTATS" in text
    assert "PASS_TENSORRT_CONTENTION" in text
    assert "detector_trt" in text
    assert "classifier_trt" in text
    assert "overload_events" in text
    assert "limited_task" in text
    assert "backend" in text


def test_jetson_tensorrt_diverse_engine_build_script_contract() -> None:
    script = Path("scripts/build_jetson_tensorrt_diverse_engines.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT diverse build script should be executable"
    assert "scripts/create_tensorrt_diverse_onnx.py" in text
    assert "models/generated" in text
    assert "detector_tiny.onnx" in text
    assert "classifier_tiny.onnx" in text
    assert "detector_tiny_fp16.plan" in text
    assert "classifier_tiny_fp16.plan" in text
    assert "/usr/src/tensorrt/bin/trtexec" in text
    assert "--skipInference" in text
    assert "PASS_TENSORRT_DIVERSE_ENGINE_BUILD" in text
    assert "does not claim scheduler behavior or TensorRT throughput" in text


def test_jetson_tensorrt_diverse_guard_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt_diverse_engines.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT diverse guard script should be executable"
    assert "detector_tiny_fp16.plan" in text
    assert "classifier_tiny_fp16.plan" in text
    assert "detector_input" in text
    assert "detector_scores" in text
    assert "classifier_input" in text
    assert "classifier_logits" in text
    assert "TensorRtWorker" in text
    assert "PASS_TENSORRT_DIVERSE_GUARD" in text
    assert "not scheduler/load-shedding contention" in text


def test_jetson_tensorrt_diverse_contention_script_contract() -> None:
    script = Path("scripts/smoke_jetson_tensorrt_diverse_contention.sh")
    text = script.read_text(encoding="utf-8")
    mode = script.stat().st_mode

    assert mode & stat.S_IXUSR, "TensorRT diverse contention script should be executable"
    assert "configs/jetson_tensorrt_diverse_contention.json" in text
    assert "PASS_TENSORRT_DIVERSE_CONTENTION" in text
    assert "detector_tiny_fp16.plan" in text
    assert "classifier_tiny_fp16.plan" in text
    assert "OrchestratorRuntime" in text
    assert "detector_trt" in text
    assert "classifier_trt" in text
    assert "overload_events" in text
    assert "limited_task" in text
    assert "both distinct TensorRT engines did not execute" in text
    assert "not a throughput" in text


def test_tensorrt_diverse_onnx_generator_contract(tmp_path) -> None:
    output_dir = tmp_path / "generated"

    written = write_models(output_dir, "all")

    assert [path.name for path in written] == [
        "detector_tiny.onnx",
        "classifier_tiny.onnx",
    ]
    assert all(path.exists() for path in written)

    import onnx

    detector = onnx.load(output_dir / "detector_tiny.onnx")
    classifier = onnx.load(output_dir / "classifier_tiny.onnx")

    assert detector.graph.name == "synthetic_detector_tiny"
    assert classifier.graph.name == "synthetic_classifier_tiny"
    assert detector.graph.input[0].name == "detector_input"
    assert detector.graph.output[0].name == "detector_scores"
    assert classifier.graph.input[0].name == "classifier_input"
    assert classifier.graph.output[0].name == "classifier_logits"
