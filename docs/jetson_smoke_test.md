# Jetson Orin Nano Smoke Test

This smoke test verifies that InferEdgeOrchestrator can run on a Jetson Orin
Nano and produce telemetry JSON. It is not a benchmark run.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

For ONNX Runtime smoke on Jetson, install the platform-appropriate ONNX Runtime
package separately, then use the Phase 2 demo config.

## Dummy Input Smoke

```bash
python3 -m inferedge_orchestrator run \
  --config configs/phase4_jetson_smoke.json \
  --output reports/jetson_smoke_dummy.json \
  --frames 20

python3 -m inferedge_orchestrator report \
  --input reports/jetson_smoke_dummy.json
```

Expected minimum result:

- CLI exits with code 0.
- `reports/jetson_smoke_dummy.json` is created.
- telemetry contains task execution/drop counts.
- telemetry contains `resource_snapshots` with `start` and `end` entries.

## Optional tegrastats Capture

In a second terminal on Jetson:

```bash
tegrastats --interval 1000 | tee reports/tegrastats_smoke.log
```

The parser in `inferedge_orchestrator.monitor.parse_tegrastats_line` can extract
RAM, SWAP, CPU, GPU, and temperature fields from typical tegrastats lines.

## Device Validation Record

Current repository validation:

- Local CLI smoke: ready and covered by tests.
- Jetson Orin Nano hardware execution: pending physical-device run.
- Required artifact after device run: `reports/jetson_smoke_dummy.json`.
- Optional artifact after device run: `reports/tegrastats_smoke.log`.

Fill this section after the physical device run:

```text
Device:
JetPack:
Python:
Command:
Telemetry path:
Result:
Notes:
```
