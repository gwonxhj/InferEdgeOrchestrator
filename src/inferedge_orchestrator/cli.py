from __future__ import annotations

import argparse
import json
from pathlib import Path

from inferedge_orchestrator.config import load_config
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
