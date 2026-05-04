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

Recommended one-command smoke:

```bash
scripts/smoke_jetson_dummy.sh
```

The script performs:

- package import check
- dummy-input CLI run
- telemetry JSON creation
- telemetry summary print
- `resource_snapshots` validation
- validation note generation

Manual equivalent:

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
- `reports/jetson_validation.md` is created.

## Optional tegrastats Capture

Option A, let the smoke script capture it:

```bash
CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh
```

Option B, capture in a second terminal on Jetson:

```bash
tegrastats --interval 1000 | tee reports/tegrastats_smoke.log
```

The parser in `inferedge_orchestrator.monitor.parse_tegrastats_line` can extract
RAM, SWAP, CPU, GPU, and temperature fields from typical tegrastats lines.

## Artifact Rules

Canonical smoke artifacts:

- Required telemetry: `reports/jetson_smoke_dummy.json`
- Required validation note: `reports/jetson_validation.md`
- Optional resource log: `reports/tegrastats_smoke.log`

Artifact policy:

- Raw smoke artifacts are generated under `reports/`.
- Raw JSON/log/validation artifacts are ignored by git by default.
- After the physical Jetson run, summarize the relevant result in README or this
  document instead of committing large raw logs.
- Keep the run clearly labeled as smoke validation, not benchmark evidence.

## Device Validation Record

Current repository validation:

- Local CLI smoke: ready and covered by tests.
- Jetson Orin Nano hardware execution: pending physical-device run.
- Required artifact after device run: `reports/jetson_smoke_dummy.json`.
- Required validation note after device run: `reports/jetson_validation.md`.
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
