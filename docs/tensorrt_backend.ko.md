# TensorRT / GPU Backend Status

Language: [English](tensorrt_backend.md) | 한국어

상태: config schema, TensorRT engine deserialization, execution context
creation, tensor metadata inspection, host/device buffer allocation, tensor
address binding, TensorRT inference execution, Jetson inference smoke, Jetson
TensorRT-backed contention evidence가 구현되어 있다. schema, TensorRT worker
execution path, `scripts/smoke_jetson_tensorrt.sh`,
`scripts/smoke_jetson_tensorrt_contention.sh`,
`scripts/smoke_jetson_tensorrt_diverse_contention.sh`가 존재한다.

InferEdgeOrchestrator는 이미 scheduler, bounded queue, load shedding,
telemetry, ONNX Runtime worker path, Jetson smoke path를 검증했다. TensorRT
지원은 같은 runtime operation-control 흐름을 확장한다. 즉, 단일 모델 throughput
benchmark가 아니라 Jetson에서 TensorRT-backed worker가 multi-task scheduling과
overload control에 어떻게 참여하는지를 보여준다.

## Purpose

TensorRT-backed path가 답하는 질문은 하나다.

> 제한된 Jetson 장치에서 deployment 이후 inference task가 TensorRT-backed
> execution으로 실행될 때도 orchestrator가 scheduling, bounded queue,
> load shedding, telemetry를 통해 overload behavior를 제어 가능한 상태로
> 유지할 수 있는가?

이렇게 정의하면 프로젝트 포지션이 유지된다.

- InferEdge는 운영 이전 deployment readiness를 검증한다.
- InferEdgeOrchestrator는 deployment 이후 runtime operation을 제어한다.
- TensorRT 지원은 worker layer의 backend coverage이며 runtime operation-control
  목적을 바꾸는 작업이 아니다.

## Non-Goals

이 backend path는 다음으로 흐르면 안 된다.

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

TensorRT worker는 scheduler, queue, load-shedding, telemetry top-level contract를
바꾸지 않고 이 interface에 연결된다. scheduler는 계속 priority와 deadline 기준으로
task를 선택한다. worker는 backend-specific runtime을 load하고 선택된 task를 실행한
뒤 latency/result metadata를 반환하는 책임만 가진다.

## Config Schema Status

config schema는 `tensorrt` worker 선택을 허용하며, 기존 `dummy`, `onnxruntime`
config와의 backward compatibility를 유지한다. worker layer는 설정된 TensorRT
engine을 deserialize하고 execution context를 생성하며 name-based input/output
tensor metadata를 기록하고 input/output buffer를 할당 및 bind하며 runtime object를
engine path 기준으로 cache할 수 있다. 또한 TensorRT `execute_async_v3`로 실행하고
device output을 host buffer로 복사한 뒤 backend result metadata를 반환한다.

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

이 예시는 config schema로 유효하다. `worker="tensorrt"` runtime execution은
TensorRT prerequisite을 확인하고 설정된 engine을 deserialize하고 execution context를
생성하고 input/output tensor metadata를 기록한 뒤, host/device buffer를 할당하고
tensor address를 bind한다. 이후 선택된 frame을 TensorRT로 실행한다.

## Current Validation Rules

현재 config validation은 다음을 강제한다.

- `dummy`, `onnxruntime` config는 backward-compatible하게 유지한다.
- `worker="tensorrt"`는 `engine_path`를 요구한다.
- `engine_path`는 제공되면 빈 문자열일 수 없다.
- `worker_options`는 제공되면 mapping이어야 한다.
- `worker_options.allow_engine_build`는 제공되면 boolean이어야 한다.
- `worker_options.providers`는 제공되면 비어 있지 않은 string list여야 한다.
- 생성된 engine file은 local artifact이며 commit하지 않는다.

현재 worker behavior는 다음을 강제한다.

- `worker="tensorrt"`는 TensorRT Python binding이 없을 때 명확한 오류로
  실패해야 한다.
- `worker="tensorrt"`는 설정된 `engine_path` file이 없을 때 명확한 오류로
  실패해야 한다.
- `worker="tensorrt"`는 TensorRT가 설정된 engine을 deserialize하지 못하면
  명확한 오류로 실패해야 한다.
- `worker="tensorrt"`는 TensorRT가 execution context를 생성하지 못하면 명확한
  오류로 실패해야 한다.
- `worker="tensorrt"`는 engine이 TensorRT name-based tensor API로 input 또는 output
  tensor를 노출하지 않으면 명확한 오류로 실패해야 한다.
- `worker="tensorrt"`는 TensorRT host/device buffer allocation에 필요한 PyCUDA가
  없으면 명확한 오류로 실패해야 한다.
- `worker="tensorrt"`는 TensorRT execution resource가 같은 CUDA context를 사용하도록
  TensorRT engine deserialization 전에 PyCUDA CUDA context를 초기화한다.
- `worker="tensorrt"`는 `context.set_tensor_address`로 tensor address를 bind하지
  못하면 명확한 오류로 실패해야 한다.
- `worker="tensorrt"`는 `context.execute_async_v3`가 없거나 실패를 반환하면
  명확한 오류로 실패해야 한다.
- `worker="tensorrt"`는 optional `frame.payload["tensorrt_inputs"]` 값을 받아
  host-to-device copy 전에 shape를 검증한다.
- `worker="tensorrt"`는 deserialized engine, execution context, bound buffer를
  engine path 기준으로 cache한다.
- `worker="tensorrt"`는 engine path, TensorRT version, input/output shape,
  output dtype, output count, 작은 output preview를 포함한 backend result metadata를
  반환한다.
- `scripts/smoke_jetson_tensorrt.sh`는 Jetson에서 dependency inventory capture,
  config validation, TensorRT engine deserialization, execution context creation,
  tensor metadata inspection, host/device buffer allocation, tensor address
  binding, TensorRT inference execution, worker result metadata 출력을 확인할 수
  있다.
- 같은 script는 `OrchestratorRuntime`을 1 frame 실행해 `result_events[].output`에
  TensorRT backend metadata가 남는지도 검증한다.

남아 있는 validation guardrail:

- TensorRT/GPU에서 CPU로 fallback할 경우 config와 telemetry에 명시되어야 한다.
- 향후 더 넓은 TensorRT scenario도 model throughput 우위를 주장하지 말고
  operation-control behavior를 증명해야 한다.

## Jetson TensorRT Inference Smoke

inference smoke script는 다음과 같다.

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt.sh
```

주요 environment variable은 다음과 같다.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYTHON_BIN` | `~/miniconda3/envs/yolo_env/bin/python`, 이후 `.venv/bin/python`, 이후 `python3` | TensorRT import와 worker smoke check에 사용할 Python interpreter. |
| `CONFIG` | `configs/jetson_tensorrt_smoke.json` | TensorRT inference smoke config. |
| `ENGINE_PATH` | `models/detector.plan` | runtime에 config로 주입할 device-local TensorRT engine path. |
| `REPORT_DIR` | `reports` | local Jetson artifact를 기록할 ignored output directory. |
| `VALIDATION_PATH` | `reports/jetson_tensorrt_guard_validation.md` | 사람이 읽을 TensorRT smoke record. |
| `RUNTIME_TELEMETRY_PATH` | `reports/jetson_tensorrt_runtime_telemetry.json` | `result_events[].output` backend metadata를 검증하는 runtime telemetry JSON. |
| `DEPENDENCY_PATH` | `reports/jetson_tensorrt_dependency.txt` | host, L4T, Python, TensorRT, `trtexec`, `nvcc`, `tegrastats` inventory. |
| `CAPTURE_TEGRASTATS` | `0` | `1`로 설정하면 optional `tegrastats` output을 capture한다. |
| `TEGRSTATS_PATH` | `reports/tegrastats_tensorrt_guard.log` | optional raw `tegrastats` capture path. |
| `TEGRSTATS_INTERVAL_MS` | `1000` | optional `tegrastats` capture interval. |
| `TRTEXEC_BIN` | `/usr/src/tensorrt/bin/trtexec` | 명시적 Jetson TensorRT CLI path. |
| `NVCC_BIN` | `/usr/local/cuda/bin/nvcc` | version evidence용 명시적 Jetson CUDA compiler path. |

현재 기대 동작은 다음과 같다.

- TensorRT Python import가 성공해야 한다.
- `ENGINE_PATH`는 local engine file을 가리켜야 한다.
- worker는 identity-model frame 1개를 실행하고 TensorRT backend result metadata를
  반환해야 한다.
- runtime telemetry는 `result_events[].output` 아래 TensorRT backend metadata를
  포함해야 한다.
- script는 ignored `reports/` 아래에 local report를 작성한다.

이 결과는 작은 identity model에 대한 TensorRT worker execution evidence다. 다만
throughput benchmark가 아니다. Multi-task TensorRT-backed scheduler/load-shedding
evidence는 아래 contention smoke 섹션에서 별도로 기록한다.

이 smoke path에 사용할 작은 local engine 생성 절차는
[`docs/tensorrt_engine_build.ko.md`](tensorrt_engine_build.ko.md)에 기록한다.

## Jetson TensorRT Contention Smoke

contention smoke script는 다음과 같다.

```bash
ENGINE_PATH=models/detector.plan scripts/smoke_jetson_tensorrt_contention.sh
```

이 script는 `OrchestratorRuntime`에서 두 TensorRT task를 실행한다.

| Task | Priority | Expected role |
| --- | --- | --- |
| `detector_trt` | 100 | 보호해야 할 high-priority task |
| `classifier_trt` | 10 | load shedding으로 제한되는 low-priority task |

검증 항목:

- 모든 runtime result event에 TensorRT backend metadata가 남는다.
- `overload_events`가 기록된다.
- policy decision에 `limited_task="classifier_trt"`가 포함된다.
- `classifier_trt` frame이 drop되는 동안 `detector_trt`는 실행된다.

이 결과는 TensorRT-backed scheduler/load-shedding evidence다. Throughput benchmark가
아니며, 현재는 artifact를 작고 재현 가능하게 유지하기 위해 두 task 모두 같은 작은
identity engine을 사용한다.

## Model Diversity Status

초기 TensorRT contention smoke는 첫 Jetson evidence를 작고 local이며 재현 가능하게
유지하기 위해 두 task 모두 같은 tiny identity engine을 사용했다. 현재 repository에는
서로 다른 generated detector/classifier engine path도 포함되어 있다.

- `scripts/create_tiny_onnx_models.py`
- `scripts/build_jetson_tensorrt_diverse_engines.sh`
- `scripts/smoke_jetson_tensorrt_individual_engines.sh`
- `scripts/smoke_jetson_tensorrt_diverse_contention.sh`
- `configs/jetson_tensorrt_diverse_contention.json`
- `examples/telemetry/jetson_tensorrt_diverse_contention_sample.json`

diversified contention evidence는 서로 다른 generated detector-like 및
classifier-like TensorRT engine이 같은 scheduler/load-shedding telemetry shape에
참여할 수 있음을 확인한다. 이는 여전히 runtime operation-control evidence이며,
TensorRT throughput benchmark나 production serving claim이 아니다.

향후 model diversity 작업은 다음 boundary를 유지할 때만 확장한다.

- source model license와 generation path를 문서화한다.
- TensorRT engine binary와 큰 model file은 git에 넣지 않는다.
- telemetry는 high-priority protection과 low-priority limiting을 증명한다.
- 문서는 결과가 operation-control evidence이며 model-quality 또는 throughput
  comparison이 아님을 명시한다.

model-diversity proposal과 현재 evidence record는
[`docs/tensorrt_model_diversity.ko.md`](tensorrt_model_diversity.ko.md)에 기록한다.

## Telemetry Contract

현재 telemetry top-level shape는 유지한다. TensorRT/GPU 지원은 scheduler summary를
바꾸기보다 worker result event 내부에 backend metadata를 추가하는 방식으로 간다.

worker metadata에는 다음 항목이 포함되거나 포함될 수 있다.

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

TensorRT worker path는 target Jetson의 작은 dependency inventory를 먼저 수집한 뒤
진행했다.

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
- smoke script는 `/usr/src/tensorrt/bin/trtexec`를 명시적으로 호출하거나
  `/usr/src/tensorrt/bin`을 `PATH`에 추가해야 한다.
- compiler version evidence가 필요하면 smoke script는 `/usr/local/cuda/bin/nvcc`를
  명시적으로 호출해야 한다.
- 현재 `yolo_env`의 ONNX Runtime은 runtime에서 `AzureExecutionProvider`,
  `CPUExecutionProvider`만 노출하므로 ONNX Runtime GPU provider 검증은 바로
  완료된 상태가 아니다.
- 이 survey는 dependency inventory일 뿐이다. 이후 Jetson smoke record가 TensorRT
  engine execution과 TensorRT-backed scheduler/load-shedding evidence를 제공한다.
  ONNX Runtime GPU provider validation은 별도 범위다.

## Smoke Script Status

TensorRT smoke script들은 존재하며 ignored `reports/` path 아래 local report artifact를
작성한다.

공통 environment variable:

| Variable | Purpose |
| --- | --- |
| `PYTHON_BIN` | Jetson Python environment 선택. |
| `CONFIG` | TensorRT smoke config path. |
| `OUTPUT` | 보통 `reports/` 아래에 생성되는 telemetry output path. |
| `ENGINE_PATH` | device-local TensorRT engine path. |
| `CAPTURE_TEGRASTATS` | smoke evidence용 optional `tegrastats` capture. |

script는 local `reports/` artifact를 생성하며 tracked release artifact를 직접 만들지
않는다. curated summary는 검토 후 docs 또는 `examples/telemetry/`에 반영한다.

## Completed Implementation Sequence

1. 이 backend design document와 schema plan을 추가한다.
2. Jetson TensorRT, ONNX Runtime provider, Python dependency 상태를 조사한다.
3. 기존 config 호환성을 유지하면서 config schema field를 test와 함께 추가한다.
4. optional import 실패 메시지를 포함한 TensorRT worker stub을 추가한다.
5. Jetson smoke script draft를 추가한다.
6. Jetson SSH에서 실제 TensorRT engine을 실행한다.
7. 단일 TensorRT worker smoke telemetry를 기록한다.
8. TensorRT-backed execution으로 multi-task scenario를 실행한다.
9. 서로 다른 generated detector/classifier TensorRT contention evidence를 추가한다.
10. 확인된 결과로 validation evidence와 README positioning을 갱신한다.

## Completion Criteria

이 backend validation path는 다음 조건을 만족할 때 완료된다.

- 기존 tests가 계속 통과한다.
- 기존 `dummy`, `onnxruntime` config가 계속 유효하다.
- TensorRT config validation이 명시적이고 문서화되어 있다.
- Jetson smoke output이 TensorRT worker 실행을 증명한다.
- Jetson contention smoke output이 TensorRT-backed scheduler/load-shedding behavior를
  증명한다.
- telemetry가 기존 schema reader를 깨지 않고 backend metadata를 기록한다.
- README는 계속 이 프로젝트를 benchmark나 Triton/DeepStream 대체제가 아니라
  runtime operation-control layer로 설명한다.
