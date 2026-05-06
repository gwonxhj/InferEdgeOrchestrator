# TensorRT / GPU Backend Plan

Language: [English](tensorrt_backend.md) | 한국어

상태: schema, worker guard, Jetson guard-smoke 초안 문서다. config schema,
TensorRT worker stub, `scripts/smoke_jetson_tensorrt.sh`는 존재하지만,
TensorRT engine deserialization, inference execution, GPU provider execution,
multi-task TensorRT scheduling evidence가 구현되었다고 주장하지 않는다.

InferEdgeOrchestrator는 이미 scheduler, bounded queue, load shedding,
telemetry, ONNX Runtime worker path, Jetson smoke path를 검증했다. 향후
TensorRT/GPU backend는 같은 operation-control 흐름을 확장해야 한다. 즉,
단일 모델 benchmark가 아니라 Jetson에서 GPU-backed worker가 multi-task
scheduling과 overload control에 어떻게 참여하는지를 보여주는 방향이어야 한다.

## Purpose

향후 backend가 답해야 하는 질문은 하나다.

> 제한된 Jetson 장치에서 deployment 이후 inference task가 GPU/TensorRT로
> 실행될 때도 orchestrator가 scheduling, bounded queue, load shedding,
> telemetry를 통해 high-priority task latency를 보호할 수 있는가?

이렇게 정의하면 프로젝트 포지션이 유지된다.

- InferEdge는 운영 이전 deployment readiness를 검증한다.
- InferEdgeOrchestrator는 deployment 이후 runtime operation을 제어한다.
- TensorRT/GPU 지원은 worker layer의 backend coverage이며 scheduler 목적을
  바꾸는 작업이 아니다.

## Non-Goals

이 확장은 다음으로 흐르면 안 된다.

- TensorRT benchmark suite.
- Triton 또는 DeepStream 대체제.
- model conversion pipeline. Engine 생성은 smoke validation을 위해 문서화하거나
  script화할 수 있지만, 더 큰 InferEdge ecosystem에서는 Forge가
  conversion/provenance layer다.
- 대형 model artifact repository. 생성된 engine, 큰 ONNX file, raw device log,
  임시 Jetson output은 git에 넣지 않는다.

## Backend Boundary

기존 worker interface는 의도적으로 안정적으로 유지한다.

```python
class Worker(Protocol):
    def run(self, task: TaskConfig, frame: FrameEnvelope) -> WorkerResult:
        ...
```

TensorRT worker는 scheduler, queue, load-shedding, telemetry top-level
contract를 바꾸지 않고 이 interface에 연결되어야 한다. scheduler는 계속
priority와 deadline 기준으로 task를 선택한다. worker는 backend-specific runtime을
load하고 선택된 task를 실행한 뒤 latency/result metadata를 반환하는 책임만 가진다.

## Config Schema Status

config schema는 `tensorrt` worker 선택을 허용하며, 기존 `dummy`, `onnxruntime`
config와의 backward compatibility를 유지한다. worker layer에는 초기 TensorRT
guard stub도 존재하지만, TensorRT engine deserialization과 inference execution은
아직 구현되지 않았다.

task field는 다음과 같다.

| Field | Status | Purpose |
| --- | --- | --- |
| `worker` | 기존 field, enum 확장 완료 | `dummy`, `onnxruntime`, `tensorrt`를 허용한다. |
| `model_path` | 기존 field | source model/reference path로 유지한다. 생성된 TensorRT engine path로 의미를 덮어쓰지 않는다. |
| `engine_path` | optional field | device-local TensorRT engine path다. `worker`가 `tensorrt`이면 required로 검증한다. |
| `worker_options` | optional mapping | global task-policy field로 올릴 필요가 없는 backend-specific option을 담는다. |

인식하는 `worker_options` key는 다음과 같다.

| Key | Purpose |
| --- | --- |
| `precision` | `fp16`, `fp32` 같은 requested precision label. telemetry에 기록한다. |
| `warmup_runs` | 측정 smoke frame 이전 warmup execution 횟수. |
| `device_id` | backend가 노출하는 Jetson GPU device id. |
| `allow_engine_build` | model path에서 engine 생성을 허용하는 명시적 opt-in. 기본값은 `false`로 둔다. |
| `profile_name` | optional TensorRT optimization profile label. |
| `input_bindings` | smoke model이 명시적 name/shape를 요구할 때 사용할 optional input binding metadata. |
| `output_bindings` | result metadata validation을 위한 optional output binding metadata. |
| `providers` | ONNX Runtime GPU-provider 실험용 optional provider list. 예: `TensorrtExecutionProvider`, `CUDAExecutionProvider`, `CPUExecutionProvider`. |

schema-valid 예시는 다음과 같다.

```json
{
  "run": {
    "name": "jetson_tensorrt_smoke",
    "input_source": "dummy",
    "overload_backlog_threshold": 6
  },
  "tasks": [
    {
      "name": "detector_trt",
      "model_path": "models/detector.onnx",
      "engine_path": "models/detector.plan",
      "priority": 100,
      "target_fps": 15,
      "latency_budget_ms": 80,
      "queue_size": 4,
      "drop_policy": "drop_oldest",
      "worker": "tensorrt",
      "worker_options": {
        "precision": "fp16",
        "warmup_runs": 5,
        "device_id": 0,
        "allow_engine_build": false
      }
    }
  ]
}
```

이 예시는 config schema로 유효하다. 단, `worker="tensorrt"` runtime execution은
현재 TensorRT prerequisite을 확인한 뒤, engine deserialization과 inference
execution이 추가되기 전까지 명확한 not-implemented 오류로 실패한다.

## Current Validation Rules

현재 config validation은 다음을 강제한다.

- `dummy`, `onnxruntime` config는 backward-compatible하게 유지한다.
- `worker="tensorrt"`는 `engine_path`를 요구한다.
- `engine_path`는 제공되면 빈 문자열일 수 없다.
- `worker_options`는 제공되면 mapping이어야 한다.
- `worker_options.allow_engine_build`는 제공되면 boolean이어야 한다.
- `worker_options.providers`는 제공되면 비어 있지 않은 string list여야 한다.
- 생성된 engine file은 local artifact이며 commit하지 않는다.

현재 worker guard behavior는 다음을 강제한다.

- `worker="tensorrt"`는 TensorRT Python binding이 없을 때 명확한 오류로
  실패해야 한다.
- `worker="tensorrt"`는 설정된 `engine_path` file이 없을 때 명확한 오류로
  실패해야 한다.
- `scripts/smoke_jetson_tensorrt.sh`는 Jetson에서 dependency inventory capture,
  config validation, TensorRT import 및 engine-file guard 통과 후 현재 기대하는
  not-implemented boundary 도달 여부를 확인할 수 있다.

실제 TensorRT execution 추가 시 더해야 할 validation rule:

- TensorRT/GPU에서 CPU로 fallback할 경우 config와 telemetry에 명시되어야 한다.
- Engine deserialization과 inference execution은 result event에 backend metadata를
  기록해야 한다.

## Jetson TensorRT Guard Smoke Draft

guard smoke script는 다음과 같다.

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh
```

주요 environment variable은 다음과 같다.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYTHON_BIN` | `~/miniconda3/envs/yolo_env/bin/python`, 이후 `.venv/bin/python`, 이후 `python3` | TensorRT import와 worker guard check에 사용할 Python interpreter. |
| `CONFIG` | `configs/jetson_tensorrt_smoke.json` | TensorRT guard smoke config. |
| `ENGINE_PATH` | `models/detector.plan` | runtime에 config로 주입할 device-local TensorRT engine path. |
| `REPORT_DIR` | `reports` | local Jetson artifact를 기록할 ignored output directory. |
| `VALIDATION_PATH` | `reports/jetson_tensorrt_guard_validation.md` | 사람이 읽을 guard-smoke record. |
| `DEPENDENCY_PATH` | `reports/jetson_tensorrt_dependency.txt` | host, L4T, Python, TensorRT, `trtexec`, `nvcc`, `tegrastats` inventory. |
| `CAPTURE_TEGRASTATS` | `0` | `1`로 설정하면 optional `tegrastats` output을 capture한다. |
| `TEGRSTATS_PATH` | `reports/tegrastats_tensorrt_guard.log` | optional raw `tegrastats` capture path. |
| `TEGRSTATS_INTERVAL_MS` | `1000` | optional `tegrastats` capture interval. |
| `TRTEXEC_BIN` | `/usr/src/tensorrt/bin/trtexec` | 명시적 Jetson TensorRT CLI path. |
| `NVCC_BIN` | `/usr/local/cuda/bin/nvcc` | version evidence용 명시적 Jetson CUDA compiler path. |

현재 기대 동작은 다음과 같다.

- TensorRT Python import가 성공해야 한다.
- `ENGINE_PATH`는 local engine file을 가리켜야 한다.
- worker는 engine deserialization 및 inference execution에 대한 현재의 명확한
  not-implemented boundary에 도달해야 한다.
- script는 ignored `reports/` 아래에 local report를 작성한다.

이 결과는 TensorRT inference evidence가 아니다. Jetson 환경과 worker guard path가
다음 구현 단계로 넘어갈 준비가 되었는지만 증명한다.

이 smoke path에 사용할 작은 local engine 생성 절차는
[`docs/tensorrt_engine_build.ko.md`](tensorrt_engine_build.ko.md)에 기록한다.

## Telemetry Plan

현재 telemetry top-level shape는 유지한다. TensorRT/GPU 지원은 scheduler summary를
바꾸기보다 worker result event 내부에 backend metadata를 추가하는 방식으로 간다.

계획 중인 worker metadata:

- `worker`: `tensorrt`
- `backend`: `tensorrt`
- `engine_path`
- `precision`
- `device_id`
- `warmup_runs`
- `engine_loaded`
- `input_shapes`
- `output_shapes`
- ONNX Runtime GPU provider path를 검증할 경우 `provider` 또는 `providers`

핵심 evidence는 여전히 operation control이다. 어떤 task가 실행되었고, 어떤 task가
drop되었고, 어떤 task가 보호되었으며, overload decision이 telemetry에 남았는지가
중요하다.

## Jetson Dependency Survey

실제 worker를 작성하기 전에 target Jetson에서 작은 dependency inventory를
수집한다.

```bash
trtexec --version
python -c "import tensorrt as trt; print(trt.__version__)"
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
python -c "import pycuda.driver as cuda; print('pycuda ok')"
cat /etc/nv_tegra_release
uname -a
```

`pycuda`는 TensorRT 실행 방식에 따라 optional일 수 있다. Jetson은 일반적으로
`nvidia-smi`를 사용하지 않는다. smoke evidence에는 `tegrastats`,
`/etc/nv_tegra_release`, 기존 telemetry resource snapshot을 우선 사용한다.

### Survey Result: 2026-05-06

대상 장치:

| Item | Result |
| --- | --- |
| Host | `nano01` |
| Address | `192.168.45.63` |
| OS | Ubuntu 22.04.5 LTS |
| Kernel | `Linux 5.15.148-tegra aarch64` |
| L4T | `36.4.7` (`R36`, revision `4.7`) |
| Device | Jetson Orin Nano Developer Kit, 25W mode |

runtime inventory:

| Dependency | Result | Note |
| --- | --- | --- |
| CUDA | `12.6.68` runtime, `12.6.11` SDK metadata | `/usr/local/cuda/version.json` 존재. |
| `nvcc` | `12.6.68` | `/usr/local/cuda/bin/nvcc`에서 사용 가능. non-interactive SSH `PATH`에는 없음. |
| cuDNN | `9.3.0.75` | `libcudnn9-cuda-12` 및 dev package 설치됨. |
| TensorRT | `10.3.0.30` package, Python import는 `10.3.0` 보고 | `python3-libnvinfer` 설치됨. |
| TensorRT ONNX parser | 설치됨 | `libnvonnxparsers10` 및 dev package 설치됨. |
| `trtexec` | `/usr/src/tensorrt/bin/trtexec`에서 사용 가능 | non-interactive SSH `PATH`에는 없음. |
| `tegrastats` | `/usr/bin/tegrastats`에서 사용 가능 | one-line smoke capture 성공. |
| GPU device node | 존재 | `/dev/nvhost-gpu`, `/dev/nvhost-ctrl-gpu`, `/dev/nvmap` 확인. |
| `jetson_release` | 사용 가능 | `jetson-stats 4.3.2` 보고. JetPack label은 missing이지만 L4T/library 정보는 확인 가능. |

Python environment inventory:

| Environment | Python | TensorRT | ONNX Runtime | PyCUDA | Notes |
| --- | --- | --- | --- | --- | --- |
| System Python | `/usr/bin/python3`, `3.10.12` | `10.3.0` import 성공 | 설치 안 됨 | 설치 안 됨 | TensorRT import 확인에는 충분하지만 현재 ONNX Runtime provider 작업에는 부족함. |
| `yolo_env` | `/home/risenano01/miniconda3/envs/yolo_env/bin/python`, `3.10.12` | `10.3.0` import 성공 | `1.23.2`, providers: `AzureExecutionProvider`, `CPUExecutionProvider` | import 성공 | pip 목록에는 `onnxruntime-gpu 1.17.0`도 있으나 runtime provider에는 CUDA/TensorRT provider가 노출되지 않음. |

`yolo_env`에서 관찰된 ONNX Runtime warning:

```text
GPU device discovery failed: ReadFileContents Failed to open file:
"/sys/class/drm/card1/device/vendor"
```

해석:

- TensorRT Python binding, TensorRT library, ONNX parser package, PyCUDA, CUDA,
  cuDNN, `tegrastats`가 있으므로 native TensorRT worker 개발은 가능한 상태다.
- 향후 smoke script는 `/usr/src/tensorrt/bin/trtexec`를 명시적으로 호출하거나
  `/usr/src/tensorrt/bin`을 `PATH`에 추가해야 한다.
- compiler version evidence가 필요하면 `/usr/local/cuda/bin/nvcc`를 명시적으로
  호출해야 한다.
- 현재 `yolo_env`의 ONNX Runtime은 runtime에서 `AzureExecutionProvider`,
  `CPUExecutionProvider`만 노출하므로 ONNX Runtime GPU provider 검증은 바로
  완료된 상태가 아니다.
- 이 결과는 dependency inventory일 뿐이다. TensorRT engine 실행, GPU provider
  실행, TensorRT 기반 scheduler behavior를 증명하지 않는다.

## Smoke Script Plan

향후 script는 `scripts/smoke_jetson_tensorrt.sh`로 추가할 수 있다.

계획 중인 environment variable:

| Variable | Purpose |
| --- | --- |
| `PYTHON_BIN` | Jetson Python environment 선택. |
| `CONFIG` | TensorRT smoke config path. |
| `OUTPUT` | 보통 `reports/` 아래에 생성되는 telemetry output path. |
| `ENGINE_PATH` | device-local TensorRT engine path. |
| `CAPTURE_TEGRASTATS` | smoke evidence용 optional `tegrastats` capture. |

script는 local `reports/` artifact를 생성해야 하며 tracked release artifact를
직접 만들면 안 된다. curated summary는 검토 후 docs 또는 `examples/telemetry/`에
반영한다.

## Recommended Implementation Sequence

1. 이 backend design document와 schema plan을 추가한다.
2. Jetson TensorRT, ONNX Runtime provider, Python dependency 상태를 조사한다.
3. 기존 config 호환성을 유지하면서 config schema field를 test와 함께 추가한다.
4. optional import 실패 메시지를 포함한 TensorRT worker stub을 추가한다.
5. Jetson smoke script draft를 추가한다.
6. Jetson SSH에서 실제 TensorRT engine을 실행한다.
7. 단일 TensorRT worker smoke telemetry를 기록한다.
8. TensorRT/GPU execution으로 multi-task scenario를 실행한다.
9. 확인된 결과로 validation evidence와 README positioning을 갱신한다.

## Completion Criteria

이 확장은 다음 조건을 만족할 때 완료된다.

- 기존 tests가 계속 통과한다.
- 기존 `dummy`, `onnxruntime` config가 계속 유효하다.
- TensorRT config validation이 명시적이고 문서화되어 있다.
- Jetson smoke output이 TensorRT/GPU worker 실행을 증명한다.
- telemetry가 기존 schema reader를 깨지 않고 backend metadata를 기록한다.
- README는 계속 이 프로젝트를 benchmark나 Triton/DeepStream 대체제가 아니라
  lightweight edge scheduler로 설명한다.
