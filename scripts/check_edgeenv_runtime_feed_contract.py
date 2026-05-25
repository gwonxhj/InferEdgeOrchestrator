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
    print("EdgeEnv runtime telemetry feed contract passed.")
    if device_local_sources:
        print(
            "device_local_producer_sources: "
            + ", ".join(str(item) for item in device_local_sources)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
