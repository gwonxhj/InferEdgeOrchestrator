# Jetson Orin Nano Smoke Test

Language: [English](jetson_smoke_test.md) | 한국어

이 smoke test는 InferEdgeOrchestrator가 Jetson Orin Nano에서 실행되고
telemetry JSON을 생성할 수 있는지 확인한다. 이 결과는 benchmark가 아니다.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

Jetson에서 ONNX Runtime smoke를 실행하려면 platform에 맞는 ONNX Runtime
package를 별도로 설치한 뒤 Phase 2 demo config를 사용한다.

`nano01`에서는 기존 `yolo_env` 환경을 ONNX Runtime smoke validation에
사용했다.

```bash
PYTHON_BIN=$HOME/miniconda3/envs/yolo_env/bin/python \
  CAPTURE_TEGRASTATS=1 \
  scripts/smoke_jetson_onnx.sh
```

## Dummy Input Smoke

권장 one-command smoke:

```bash
scripts/smoke_jetson_dummy.sh
```

script가 수행하는 작업:

- package import check
- dummy-input CLI run
- telemetry JSON 생성
- telemetry summary 출력
- `resource_snapshots` validation
- validation note 생성

수동 실행 equivalent:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/phase4_jetson_smoke.json \
  --output reports/jetson_smoke_dummy.json \
  --frames 20

python3 -m inferedge_orchestrator report \
  --input reports/jetson_smoke_dummy.json
```

최소 기대 결과:

- CLI가 exit code 0으로 종료된다.
- `reports/jetson_smoke_dummy.json`이 생성된다.
- telemetry에 task execution/drop count가 포함된다.
- telemetry에 `start`, `end` `resource_snapshots`가 포함된다.
- `reports/jetson_validation.md`가 생성된다.

## Optional tegrastats Capture

Option A, smoke script가 직접 capture:

```bash
CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh
```

Option B, Jetson의 두 번째 terminal에서 capture:

```bash
tegrastats --interval 1000 | tee reports/tegrastats_smoke.log
```

`inferedge_orchestrator.monitor.parse_tegrastats_line` parser는 일반적인
tegrastats line에서 RAM, SWAP, CPU, GPU, temperature field를 추출할 수 있다.

## Artifact Rules

Canonical smoke artifacts:

- Required telemetry: `reports/jetson_smoke_dummy.json`
- Required validation note: `reports/jetson_validation.md`
- Optional resource log: `reports/tegrastats_smoke.log`
- ONNX telemetry: `reports/jetson_onnx_smoke.json`
- ONNX validation note: `reports/jetson_onnx_validation.md`
- ONNX optional resource log: `reports/tegrastats_onnx_smoke.log`

Artifact policy:

- raw smoke artifact는 `reports/` 아래에 생성된다.
- raw JSON/log/validation artifact는 기본적으로 git에서 ignore한다.
- physical Jetson run 이후에는 큰 raw log를 commit하지 않고 README 또는 이
  문서에 핵심 결과를 요약한다.
- run은 benchmark evidence가 아니라 smoke validation으로 명확히 표시한다.

## Device Validation Record

Current repository validation:

- Local CLI smoke: ready and covered by tests.
- Jetson Orin Nano hardware execution: `nano01`에서 validated.
- device run 이후 required artifact: `reports/jetson_smoke_dummy.json`.
- device run 이후 required validation note: `reports/jetson_validation.md`.
- device run 이후 optional artifact: `reports/tegrastats_smoke.log`.

Latest physical-device validation:

```text
Timestamp UTC: 2026-05-04T12:44:02Z
Device: Linux nano01 5.15.148-tegra aarch64
OS: Ubuntu 22.04.5 LTS
L4T: R36.4.7
Python: 3.10.12
Command: CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_dummy.sh
Config: configs/phase4_jetson_smoke.json
Frames: 20
Telemetry path: reports/jetson_smoke_dummy.json
Validation note: reports/jetson_validation.md
Optional tegrastats log: reports/tegrastats_smoke.log
Result: PASS
```

Telemetry summary:

```text
detector: executed=20 dropped=0 mean_latency_ms=8.0 p95_latency_ms=8.0 max_queue_backlog=1
classifier: executed=2 dropped=18 mean_latency_ms=32.0 p95_latency_ms=32.0 max_queue_backlog=2
drop_events=18
overload_events=0
resource_snapshots=start,end
process_rss_mb=13.09
```

Optional `tegrastats` validation:

```text
Samples captured: 2
First parsed sample:
RAM 855/7620MB
SWAP 0/3810MB
CPU [0%@729,0%@729,1%@729,0%@729,0%@729,0%@729]
GR3D_FREQ 0%
cpu@35.343C
gpu@36.312C
```

Notes:

- Jetson hardware에서 CLI 실행과 telemetry 생성을 검증한다.
- 이 결과는 여전히 smoke validation이며 benchmark 결과가 아니다.
- raw generated artifact는 `reports/` 아래에 남고 git에서는 ignore된다.

## ONNX Runtime Worker Smoke

Current ONNX Runtime worker validation:

- Jetson Orin Nano hardware execution: `nano01`에서 validated.
- Python environment: `$HOME/miniconda3/envs/yolo_env/bin/python`.
- device run 이후 required artifact: `reports/jetson_onnx_smoke.json`.
- device run 이후 required validation note: `reports/jetson_onnx_validation.md`.
- device run 이후 optional artifact: `reports/tegrastats_onnx_smoke.log`.

Latest ONNX Runtime physical-device validation:

```text
Timestamp UTC: 2026-05-04T13:09:45Z
Device: Linux nano01 5.15.148-tegra aarch64
OS: Ubuntu 22.04.5 LTS
L4T: R36.4.7
Python: 3.10.12
ONNX Runtime: 1.23.2
Command: CAPTURE_TEGRASTATS=1 scripts/smoke_jetson_onnx.sh
Config: configs/phase2_onnx_demo.json
Model: models/identity.onnx
Telemetry path: reports/jetson_onnx_smoke.json
Optional tegrastats log: reports/tegrastats_onnx_smoke.log
Result: PASS
```

Telemetry summary:

```text
identity: executed=1 dropped=0 mean_latency_ms=202.05 p95_latency_ms=202.05 max_queue_backlog=1
worker=onnxruntime
output_shapes=[[1, 2]]
drop_events=0
overload_events=0
resource_snapshots=start,end
process_rss_mb=13.465 -> 54.043
```

Optional `tegrastats` validation:

```text
Samples captured: 13
First parsed sample:
RAM 901/7620MB
SWAP 0/3810MB
CPU [0%@1344,100%@1344,0%@1344,0%@1344,0%@729,0%@729]
GR3D_FREQ 0%
cpu@34.781C
gpu@35.812C
```

Notes:

- Jetson hardware에서 ONNX Runtime worker path를 검증한다.
- 현재 worker는 `CPUExecutionProvider`를 사용한다.
- smoke 중 ONNX Runtime이 GPU discovery warning을 출력했지만, GPU execution이
  이 worker path의 필수 조건이 아니기 때문에 run은 통과로 본다.
- 이 결과는 TensorRT 또는 GPU benchmark evidence가 아니다.

## Device-Local Sustained Starter Smoke

현재 device-local sustained starter 검증:

- Jetson Orin Nano hardware execution: `nano01`에서 validated.
- Python environment: `$HOME/miniconda3/envs/yolo_env/bin/python`.
- Config: `configs/agent_multi_workload_sustained_device_local.json`.
- Vision producer: `examples/inputs/vision_frame.ppm`와
  `models/generated/detector_tiny.onnx`.
- Voice producer: `examples/inputs/voice_ingress_requests.json`.
- Safety producer: `--capture-process-resource-snapshot`.
- Live telemetry: sustained run 동안 `tegrastats` capture.
- EdgeEnv feed contract:
  `scripts/check_edgeenv_runtime_feed_contract.py --require-device-local-producer`
  로 검증.

Latest device-local physical-device validation:

```text
Timestamp UTC: 2026-05-29T03:27:34Z
Device: Linux nano01 5.15.148-tegra aarch64
Python: 3.10.12
ONNX Runtime: 1.23.2
Command: run-multi-workload-sustained with device-local input overrides,
         detector_tiny ONNX probe, live tegrastats, and EdgeEnv feed export
Frames: 32
Output directory: reports/jetson_device_local_20260529T032734Z
Orchestration summary: orchestration_summary.json
EdgeEnv feed: edgeenv_runtime_telemetry_feed.json
Result: PASS
```

Observed operation evidence:

```text
max_total_queue_depth=6
dropped_count=29
fallback_count=29
deadline_missed_count=1
policy_decision_reason=queue_backlog_threshold_exceeded
queue_pressure_reason=max_total_queue_depth_exceeded_overload_threshold
producer_sources=process_resource_snapshot,image_file,fastapi_request_fixture
device_local_producer_count=35
device_local_event_count=99
tegrastats_samples=2
EdgeEnv feed schema=inferedge-orchestrator-edgeenv-runtime-telemetry-feed-v1
```

Workload summary:

```text
safety_monitor_agent: executed=16 dropped=0 fallback=0 mean=2.882ms p95=3.549ms
vision_agent: executed=18 dropped=14 fallback=14 mean=40.987ms p95=329.488ms
voice_command_agent: executed=1 dropped=15 fallback=15 mean=46.955ms p95=46.955ms
```

Vision ONNX probe evidence:

```text
backend=onnxruntime
provider=CPUExecutionProvider
input_shape=[1, 3, 16, 16]
output_shape=[1, 6]
probe_elapsed_ms=5.05
```

Notes:

- Jetson hardware에서 device-local producer override, ONNX probe, live
  `tegrastats` handoff, runtime event summary, standalone EdgeEnv feed contract를
  검증한다.
- ONNX Runtime은 ONNX worker smoke와 같은 GPU discovery warning을 출력했지만,
  이 경로는 의도적으로 `CPUExecutionProvider` probe evidence를 기록한다.
- 이 결과는 아직 starter smoke다. decoded YOLO accuracy validation, live camera
  operation, production scheduler, thermal endurance benchmark가 아니다.
