from __future__ import annotations

import argparse
import json
from pathlib import Path

from inferedge_orchestrator.config import load_config
from inferedge_orchestrator.inferedge_adapter import write_config_from_inferedge_result
from inferedge_orchestrator.runtime import OrchestratorRuntime
from inferedge_orchestrator.scenarios import write_overload_comparison


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
    inferedge_parser.add_argument("--budget-multiplier", type=float, default=1.5)
    inferedge_parser.set_defaults(func=_from_inferedge)

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
        budget_multiplier=args.budget_multiplier,
    )
    latency_budget = config["tasks"][0]["latency_budget_ms"]
    print(f"wrote config: {args.output}")
    print(f"{args.task_name}: recommended latency_budget_ms={latency_budget}")
    return 0
