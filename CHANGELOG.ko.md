# Changelog

Language: [English](CHANGELOG.md) | 한국어

이 changelog는 InferEdgeOrchestrator의 release 단위 변경 사항을 기록한다.
구현된 behavior, validation evidence, reviewer가 프로젝트 상태를 이해하는 데
필요한 문서 변경을 중심으로 정리한다.

## Unreleased

### Added

- TensorRT/GPU backend 설계 및 config schema 계획 문서를 추가했다.
  - `docs/tensorrt_backend.md`
  - `docs/tensorrt_backend.ko.md`
- 계획 중인 TensorRT/GPU backend path를 위한 2026-05-06 Jetson dependency
  survey 결과를 기록했다.
- 예약된 TensorRT field에 대한 config schema 지원을 추가했다.
  - `worker="tensorrt"`
  - `engine_path`
  - `worker_options`
- InferEdge handoff 생성 config를 파일로 쓰기 전에 validation하도록 하고,
  예약된 TensorRT schema 출력을 위해 `--engine-path`를 추가했다.
- TensorRT Python binding과 설정된 engine file 존재 여부를 확인하는 초기 TensorRT
  worker guard path를 추가했다.
- Jetson TensorRT guard smoke 초안을 추가했다.
  - `configs/jetson_tensorrt_smoke.json`
  - `scripts/smoke_jetson_tensorrt.sh`
- Jetson에서 작은 ONNX model을 TensorRT engine으로 생성하는 절차 문서를 추가했다.
  - `docs/tensorrt_engine_build.md`
  - `docs/tensorrt_engine_build.ko.md`
- Jetson TensorRT smoke evidence를 기록했다. local identity ONNX에서 FP16 engine을
  생성하고 worker validation을 확인했다.
- `TensorRtWorker`에 TensorRT engine deserialization 및 engine-path cache를
  구현했다.
- `TensorRtWorker`에 TensorRT execution context creation 및 engine-path context
  cache를 구현했다.
- `TensorRtWorker`에 TensorRT name-based input/output tensor metadata inspection을
  추가했다.
- `TensorRtWorker`에 TensorRT host/device buffer allocation과 name-based tensor
  address binding을 추가했다.
- `TensorRtWorker`에 `execute_async_v3` 기반 TensorRT inference execution,
  host/device copy, optional `frame.payload["tensorrt_inputs"]`, backend result
  metadata 반환을 추가했다.
- Jetson TensorRT runtime telemetry smoke validation을 추가해
  `result_events[].output`에 TensorRT backend metadata가 남는지 확인한다.
- high/low priority TensorRT task로 TensorRT-backed scheduler/load-shedding
  behavior를 검증하는 Jetson TensorRT contention smoke config와 script를 추가했다.
- curated TensorRT contention sample telemetry artifact를 추가했다:
  `examples/telemetry/jetson_tensorrt_contention_sample.json`.
- v0.1.x TensorRT model-diversity 결정을 문서화했다. Contention evidence는 shared
  identity engine으로 유지하고, 별도 detector/classifier engine은 이후 milestone로
  미룬다.
- 서로 다른 detector/classifier-style engine 선택, build requirement, artifact
  policy, acceptance criteria를 다루는 v0.2 TensorRT model-diversity proposal을
  추가했다.
- v0.2 TensorRT diversity scenario의 source-model 후보로 repository script가
  생성하는 detector-like tiny CNN과 classifier-like tiny MLP/CNN을 선정했다.
- 향후 Jetson TensorRT diversity smoke run을 위한 deterministic detector-like 및
  classifier-like ONNX source model 생성 script
  `scripts/create_tensorrt_diverse_onnx.py`를 추가했다.
- 생성된 ONNX pair를 Jetson에서 local FP16 TensorRT engine으로 build하는
  `scripts/build_jetson_tensorrt_diverse_engines.sh`를 추가했다.
- 생성된 TensorRT diversity engine pair에 대한 Jetson build-only evidence를
  기록했다.
- 생성된 TensorRT diversity engine 각각을 individual TensorRtWorker execution으로
  검증하는 `scripts/smoke_jetson_tensorrt_diverse_engines.sh`를 추가했다.
- 생성된 TensorRT diversity engine pair에 대한 Jetson worker-guard evidence를
  기록했다.
- 서로 다른 generated TensorRT engine을 scheduler/load-shedding contention으로 실행하기
  위한 reserved config `configs/jetson_tensorrt_diverse_contention.json`을 추가했다.
- Jetson에서 distinct-engine TensorRT scheduler/load-shedding behavior를 검증하는
  `scripts/smoke_jetson_tensorrt_diverse_contention.sh`를 추가했다.
- 서로 다른 generated detector/classifier TensorRT engine에 대한 Jetson
  `PASS_TENSORRT_DIVERSE_CONTENTION` evidence를 기록했다: detector `6/0`,
  classifier `1/5` executed/dropped, overload event `5`, TensorRT backend
  telemetry.

### Changed

- `README.md`의 문서 진입 link를 영어 문서가 main entry가 되도록 정리했다.
  한국어 mirror는 각 문서의 language selector에서 선택하는 흐름으로 유지한다.
- survey된 Jetson TensorRT 10.3.0 환경에 맞춰 TensorRT engine build 절차를
  `trtexec --skipInference` 사용으로 갱신했다.
- TensorRT smoke 기대값과 문서를 갱신해 `PASS_GUARD_STUB`가 engine
  deserialization 성공 후 inference execution만 남은 boundary를 의미하게 했다.
- TensorRT smoke 기대값과 문서를 갱신해 `PASS_GUARD_STUB`가 engine
  deserialization 및 execution context creation 성공 후 input/output binding과
  inference execution만 남은 boundary를 의미하게 했다.
- TensorRT smoke 기대값과 문서를 갱신해 `PASS_GUARD_STUB`가 tensor metadata
  inspection까지 성공했고 input/output buffer binding과 inference execution만 남은
  boundary를 의미하게 했다.
- TensorRT smoke 기대값과 문서를 갱신해 `PASS_GUARD_STUB`가 input/output buffer
  allocation과 tensor address binding까지 성공했고 TensorRT inference execution만
  남은 boundary를 의미하게 했다.
- TensorRT smoke 기대값과 문서를 갱신해 Jetson identity engine이 실제 TensorRT
  worker 실행 1회 후 `PASS_TENSORRT_INFERENCE`를 보고하도록 했다.
- TensorRT smoke 기대값과 문서를 갱신해 end-to-end runtime telemetry check 후
  `PASS_TENSORRT_TELEMETRY`도 보고하도록 했다.

## v0.1.1 - 2026-05-06

documentation 및 validation evidence patch release다. 이 release는 runtime
scheduler behavior를 변경하지 않는다.

### Added

- portfolio brief 문서 추가:
  - `PORTFOLIO.md`
  - `PORTFOLIO.ko.md`
- `examples/telemetry/` 아래 versioned sample telemetry artifact 추가.
- sample telemetry artifact compatibility를 검증하는 pytest 추가.
- architecture 문서 추가:
  - `docs/architecture.md`
  - `docs/architecture.ko.md`
- 영어/한국어 changelog 추가.
- validation evidence index 문서 추가:
  - `docs/validation_evidence.md`
  - `docs/validation_evidence.ko.md`
- 문서 link 및 language-pair pytest coverage 추가.
- InferEdge handoff config sample 추적 추가:
  - `configs/from_inferedge.json`
- config guide 문서 추가:
  - `configs/README.md`
  - `configs/README.ko.md`

### Notes

- 위 항목은 `v0.1.0` runtime behavior 위에 더해진 문서 및 evidence packaging
  개선이다.
- sample telemetry와 Jetson 기록은 benchmark claim이 아니라 validation
  evidence다.
- tag, release, project version이 일치하도록 package metadata를 `0.1.1`로
  갱신했다.

## v0.1.0 - 2026-05-05

lightweight edge inference runtime scheduler의 첫 portfolio-ready release다.

### Added

- Scheduler core MVP:
  - config 기반 task 등록
  - `priority`, `target_fps`, `latency_budget_ms`, `queue_size`,
    `drop_policy`, `worker` task policy field
  - deterministic dummy frame source
  - task별 bounded queue
  - priority/deadline-aware scheduler
  - dummy worker
  - load-shedding policy
  - telemetry JSON export
- ONNX Runtime worker:
  - config로 선택 가능한 `onnxruntime` worker
  - lazy ONNX session loading
  - `CPUExecutionProvider` smoke path
  - output count와 output shape result metadata
- Overload scenario tooling:
  - FIFO baseline과 scheduler/load-shedding 비교
  - high-priority protected task summary
  - low-priority drop count와 overload event reporting
- Jetson smoke support:
  - Jetson dummy scheduler smoke script
  - Jetson ONNX Runtime smoke script
  - captured smoke telemetry용 `tegrastats` parser
  - telemetry report의 resource snapshot
- InferEdge handoff helper:
  - file-based `result.json` latency extraction
  - recommended `latency_budget_ms` 생성
  - InferEdge repository 직접 import 없음
- CLI command:
  - `run`
  - `report`
  - `compare-overload`
  - `from-inferedge`
- pytest용 GitHub Actions CI.
- README와 supporting docs의 영어 main 문서 및 한국어 mirror.

### Validation Evidence

- release baseline에서 local 및 GitHub Actions pytest validation 통과.
- Jetson Orin Nano dummy scheduler smoke로 CLI 실행, telemetry 생성, resource
  snapshot, low-priority drop을 검증.
- Jetson Orin Nano ONNX Runtime smoke로 `CPUExecutionProvider` 기반 ONNX worker
  path 검증.
- synthetic overload comparison으로 low-priority queued work를 drop해
  high-priority task latency를 보호하는 scheduler/load-shedding behavior 확인.

### Boundaries

- InferEdgeOrchestrator는 deployment 이후 runtime operation-control layer다.
- InferEdge는 deployment validation pipeline으로 유지된다.
- InferEdge와의 integration은 `result.json` 기반 file boundary로 제한된다.
- 이 프로젝트는 Triton이나 DeepStream 대체제가 아니다.
- 이 프로젝트는 benchmark tool이 아니다. latency와 telemetry는 scheduler
  decision과 overload behavior를 설명하기 위한 evidence로 사용한다.
