from __future__ import annotations

import argparse
import json
from pathlib import Path

from inferedge_orchestrator.config import load_config
from inferedge_orchestrator.inferedge_adapter import write_config_from_inferedge_result
from inferedge_orchestrator.remote_dispatch import dispatch_remote_task
from inferedge_orchestrator.runtime import OrchestratorRuntime
from inferedge_orchestrator.scenarios import write_overload_comparison
from inferedge_orchestrator.sustained import (
    apply_device_local_input_overrides,
    write_edgeenv_runtime_telemetry_feed,
    write_multi_workload_sustained,
    write_process_resource_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inferedge-orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the orchestrator")
    run_parser.add_argument("--config", required=True, help="path to JSON config")
    run_parser.add_argument("--output", required=True, help="telemetry JSON output path")
    run_parser.add_argument("--frames", type=int, default=10, help="dummy frame cycles")
    run_parser.add_argument(
        "--sleep-worker",
        action="store_true",
        help="sleep for simulated dummy latency",
    )
    run_parser.set_defaults(func=_run)

    sustained_parser = subparsers.add_parser(
        "run-multi-workload-sustained",
        help="run the sustained multi-workload profile demo",
    )
    sustained_parser.add_argument("--config", required=True, help="path to JSON config")
    sustained_parser.add_argument("--output", required=True, help="telemetry JSON output path")
    sustained_parser.add_argument(
        "--edgeenv-feed-output",
        help=(
            "optional standalone EdgeEnv telemetry feed JSON output path for "
            "edgeenv runs telemetry export-history --orchestrator-feed"
        ),
    )
    sustained_parser.add_argument("--frames", type=int, default=16, help="frame cycles")
    sustained_parser.add_argument(
        "--tegrastats-log",
        help="optional tegrastats log to parse into the sustained timeline",
    )
    sustained_parser.add_argument(
        "--vision-input",
        help=(
            "optional local image, video, or image-sequence directory to use "
            "for the Vision producer"
        ),
    )
    sustained_parser.add_argument(
        "--vision-onnx-model",
        help=(
            "optional ONNX model path for the Vision producer probe; requires "
            "optional onnxruntime dependencies"
        ),
    )
    sustained_parser.add_argument(
        "--voice-ingress-payload",
        help="optional local JSON request payload path for the Voice producer",
    )
    sustained_parser.add_argument(
        "--resource-snapshot",
        help="optional local JSON resource snapshot path for the Safety producer",
    )
    sustained_parser.add_argument(
        "--capture-process-resource-snapshot",
        action="store_true",
        help=(
            "capture the current process resource snapshot next to --output and "
            "use it for the Safety producer"
        ),
    )
    sustained_parser.add_argument(
        "--sleep-worker",
        action="store_true",
        help="sleep for simulated dummy latency",
    )
    sustained_parser.set_defaults(func=_run_multi_workload_sustained)

    report_parser = subparsers.add_parser("report", help="summarize telemetry JSON")
    report_parser.add_argument("--input", required=True, help="telemetry JSON input path")
    report_parser.set_defaults(func=_report)

    compare_parser = subparsers.add_parser(
        "compare-overload",
        help="compare FIFO baseline with scheduled load shedding",
    )
    compare_parser.add_argument("--config", required=True, help="path to JSON config")
    compare_parser.add_argument("--output", required=True, help="comparison JSON output path")
    compare_parser.add_argument("--frames", type=int, default=20, help="dummy frame cycles")
    compare_parser.add_argument(
        "--frame-interval-ms",
        type=float,
        default=10.0,
        help="interval between generated dummy frame cycles",
    )
    compare_parser.set_defaults(func=_compare_overload)

    inferedge_parser = subparsers.add_parser(
        "from-inferedge",
        help="create orchestrator config from an InferEdge result.json file",
    )
    inferedge_parser.add_argument("--result", required=True, help="InferEdge result.json path")
    inferedge_parser.add_argument("--output", required=True, help="output orchestrator config path")
    inferedge_parser.add_argument("--task-name", required=True)
    inferedge_parser.add_argument("--model-path", required=True)
    inferedge_parser.add_argument("--priority", type=int, required=True)
    inferedge_parser.add_argument("--target-fps", type=float, required=True)
    inferedge_parser.add_argument("--queue-size", type=int, default=2)
    inferedge_parser.add_argument("--drop-policy", default="drop_oldest")
    inferedge_parser.add_argument("--worker", default="onnxruntime")
    inferedge_parser.add_argument("--engine-path")
    inferedge_parser.add_argument("--budget-multiplier", type=float, default=1.5)
    inferedge_parser.set_defaults(func=_from_inferedge)

    remote_parser = subparsers.add_parser(
        "remote-dispatch",
        help="select a remote edge worker through a file-based starter contract",
    )
    remote_parser.add_argument(
        "--registry",
        required=True,
        help="remote worker registry JSON path",
    )
    remote_parser.add_argument(
        "--request",
        required=True,
        help="remote task request JSON path",
    )
    remote_parser.add_argument(
        "--output",
        required=True,
        help="remote dispatch result JSON output path",
    )
    remote_parser.add_argument(
        "--execute-plan",
        action="store_true",
        help=(
            "explicitly execute the selected HTTP/SSH starter endpoint; default "
            "is plan-only"
        ),
    )
    remote_parser.add_argument(
        "--timeout-sec",
        type=float,
        default=5.0,
        help="timeout for explicit HTTP/SSH starter execution",
    )
    remote_parser.set_defaults(func=_remote_dispatch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runtime = OrchestratorRuntime(config, sleep_worker=args.sleep_worker)
    runtime.run_to_file(frames=args.frames, output=args.output)
    print(f"wrote telemetry: {args.output}")
    return 0


def _run_multi_workload_sustained(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.resource_snapshot and args.capture_process_resource_snapshot:
        raise ValueError(
            "use either --resource-snapshot or --capture-process-resource-snapshot"
        )
    resource_snapshot = args.resource_snapshot
    resource_snapshot_source = None
    if args.capture_process_resource_snapshot:
        resource_snapshot = str(
            write_process_resource_snapshot(
                Path(args.output).with_suffix(".process_resource_snapshot.json")
            )
        )
        resource_snapshot_source = "process_resource_snapshot"
    config = apply_device_local_input_overrides(
        config,
        vision_input=args.vision_input,
        vision_onnx_model=args.vision_onnx_model,
        voice_ingress_payload=args.voice_ingress_payload,
        resource_snapshot=resource_snapshot,
        resource_snapshot_source=resource_snapshot_source,
    )
    report = write_multi_workload_sustained(
        config,
        output=args.output,
        frames=args.frames,
        tegrastats_log=args.tegrastats_log,
        sleep_worker=args.sleep_worker,
    )
    if args.edgeenv_feed_output:
        write_edgeenv_runtime_telemetry_feed(report, args.edgeenv_feed_output)
    summary = report["multi_workload_sustained_summary"]
    signals = summary["observed_runtime_signals"]
    queue_summary = report.get("queue_state_summary", {})
    print(f"wrote sustained telemetry: {args.output}")
    if args.edgeenv_feed_output:
        print(f"wrote EdgeEnv telemetry feed: {args.edgeenv_feed_output}")
    print(
        "multi-workload sustained: "
        f"mode={summary['scenario_mode']} "
        f"max_queue={signals['max_total_queue_depth']} "
        f"dropped={signals['dropped_count']} "
        f"deadline_missed={signals['deadline_missed_count']} "
        f"fallback={signals['fallback_count']} "
        f"queue_pressure={queue_summary.get('queue_pressure_state', 'unknown')} "
        f"tegrastats_samples={signals['tegrastats_sample_count']}"
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(f"run: {data['run']['name']}")
    for task_name, task in data["tasks"].items():
        print(
            f"{task_name}: executed={task['executed']} "
            f"dropped={task['dropped']} "
            f"mean_latency_ms={task['mean_latency_ms']} "
            f"p95_latency_ms={task['p95_latency_ms']} "
            f"max_queue_backlog={task['max_queue_backlog']}"
        )
    print(f"overload_events={len(data.get('overload_events', []))}")
    return 0


def _compare_overload(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    report = write_overload_comparison(
        config,
        output=args.output,
        frames=args.frames,
        frame_interval_ms=args.frame_interval_ms,
    )
    effect = report["effect"]
    print(f"wrote comparison: {args.output}")
    print(
        f"{effect['protected_task']}: "
        f"baseline_p95={effect['baseline_p95_end_to_end_latency_ms']}ms "
        f"scheduled_p95={effect['scheduled_p95_end_to_end_latency_ms']}ms "
        f"improvement={effect['p95_end_to_end_improvement_ms']}ms "
        f"low_priority_drops={effect['low_priority_drops']}"
    )
    return 0


def _from_inferedge(args: argparse.Namespace) -> int:
    config = write_config_from_inferedge_result(
        args.result,
        args.output,
        task_name=args.task_name,
        model_path=args.model_path,
        priority=args.priority,
        target_fps=args.target_fps,
        queue_size=args.queue_size,
        drop_policy=args.drop_policy,
        worker=args.worker,
        engine_path=args.engine_path,
        budget_multiplier=args.budget_multiplier,
    )
    latency_budget = config["tasks"][0]["latency_budget_ms"]
    print(f"wrote config: {args.output}")
    print(f"{args.task_name}: recommended latency_budget_ms={latency_budget}")
    return 0


def _remote_dispatch(args: argparse.Namespace) -> int:
    result = dispatch_remote_task(
        registry_path=args.registry,
        request_path=args.request,
        output_path=args.output,
        execute_plan=args.execute_plan,
        timeout_sec=args.timeout_sec,
    )
    print(f"wrote remote dispatch: {args.output}")
    print(
        f"dispatch_status={result['dispatch_status']} "
        f"selected_worker_id={result['selected_worker_id']} "
        f"reason={result['decision_reason']}"
    )
    return 0
