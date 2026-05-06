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
- TensorRT Python binding과 설정된 engine file 존재 여부를 확인한 뒤 engine
  deserialization/inference 미구현 메시지로 명확히 실패하는 TensorRT worker guard
  stub을 추가했다.
- Jetson TensorRT guard smoke 초안을 추가했다.
  - `configs/jetson_tensorrt_smoke.json`
  - `scripts/smoke_jetson_tensorrt.sh`
- Jetson에서 작은 ONNX model을 TensorRT engine으로 생성하는 절차 문서를 추가했다.
  - `docs/tensorrt_engine_build.md`
  - `docs/tensorrt_engine_build.ko.md`
- Jetson TensorRT guard-smoke evidence를 기록했다. local identity ONNX에서 FP16
  engine을 생성하고 `PASS_GUARD_STUB` worker-boundary validation을 확인했다.

### Changed

- `README.md`의 문서 진입 link를 영어 문서가 main entry가 되도록 정리했다.
  한국어 mirror는 각 문서의 language selector에서 선택하는 흐름으로 유지한다.
- survey된 Jetson TensorRT 10.3.0 환경에 맞춰 TensorRT engine build 절차를
  `trtexec --skipInference` 사용으로 갱신했다.

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
