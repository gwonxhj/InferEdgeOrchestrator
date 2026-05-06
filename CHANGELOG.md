# Changelog

Language: English | [한국어](CHANGELOG.ko.md)

This changelog records release-level changes for InferEdgeOrchestrator. It is
focused on implemented behavior, validation evidence, and documentation that
helps reviewers understand the project state.

## Unreleased

### Added

- Added TensorRT/GPU backend design and config schema planning documents:
  - `docs/tensorrt_backend.md`
  - `docs/tensorrt_backend.ko.md`
- Recorded the 2026-05-06 Jetson dependency survey for the planned
  TensorRT/GPU backend path.
- Added config schema support for reserved TensorRT fields:
  - `worker="tensorrt"`
  - `engine_path`
  - `worker_options`
- Validated InferEdge handoff generated configs before writing and added
  `--engine-path` for reserved TensorRT schema output.
- Added a TensorRT worker guard stub that checks TensorRT Python bindings and
  configured engine file existence before failing with a clear not-implemented
  message for engine deserialization/inference.
- Added a Jetson TensorRT guard smoke draft:
  - `configs/jetson_tensorrt_smoke.json`
  - `scripts/smoke_jetson_tensorrt.sh`
- Added a small ONNX to TensorRT engine build procedure for Jetson:
  - `docs/tensorrt_engine_build.md`
  - `docs/tensorrt_engine_build.ko.md`
- Recorded Jetson TensorRT guard-smoke evidence for local identity ONNX to FP16
  engine creation and `PASS_GUARD_STUB` worker-boundary validation.

### Changed

- Updated `README.md` document entry links so English documentation is the
  primary entry point; Korean mirrors remain available from each document's
  language selector.
- Updated the TensorRT engine build procedure to use `trtexec --skipInference`
  on the surveyed Jetson TensorRT 10.3.0 environment.

## v0.1.1 - 2026-05-06

Documentation and validation evidence patch release. This release does not
change runtime scheduler behavior.

### Added

- Added portfolio brief documents:
  - `PORTFOLIO.md`
  - `PORTFOLIO.ko.md`
- Added versioned sample telemetry artifacts under `examples/telemetry/`.
- Added pytest coverage for sample telemetry artifact compatibility.
- Added architecture documents:
  - `docs/architecture.md`
  - `docs/architecture.ko.md`
- Added this changelog in English and Korean.
- Added validation evidence index documents:
  - `docs/validation_evidence.md`
  - `docs/validation_evidence.ko.md`
- Added document link and language-pair pytest coverage.
- Added tracked InferEdge handoff config sample:
  - `configs/from_inferedge.json`
- Added config guide documents:
  - `configs/README.md`
  - `configs/README.ko.md`

### Notes

- These are documentation and evidence-packaging improvements on top of the
  `v0.1.0` runtime behavior.
- Sample telemetry and Jetson records are validation evidence, not benchmark
  claims.
- Package metadata was updated to `0.1.1` so the tag, release, and project
  version stay aligned.

## v0.1.0 - 2026-05-05

Initial portfolio-ready release for the lightweight edge inference runtime
scheduler.

### Added

- Scheduler core MVP:
  - config-driven task registration
  - task policy fields for `priority`, `target_fps`, `latency_budget_ms`,
    `queue_size`, `drop_policy`, and `worker`
  - deterministic dummy frame source
  - per-task bounded queues
  - priority and deadline-aware scheduler
  - dummy worker
  - load-shedding policy
  - telemetry JSON export
- ONNX Runtime worker:
  - config-selectable `onnxruntime` worker
  - lazy ONNX session loading
  - `CPUExecutionProvider` smoke path
  - result metadata for output count and output shapes
- Overload scenario tooling:
  - FIFO baseline vs scheduler/load-shedding comparison
  - high-priority protected task summary
  - low-priority drop count and overload event reporting
- Jetson smoke support:
  - Jetson dummy scheduler smoke script
  - Jetson ONNX Runtime smoke script
  - `tegrastats` parser for captured smoke telemetry
  - resource snapshots in telemetry reports
- InferEdge handoff helper:
  - file-based `result.json` latency extraction
  - recommended `latency_budget_ms` generation
  - no direct imports from InferEdge repositories
- CLI commands:
  - `run`
  - `report`
  - `compare-overload`
  - `from-inferedge`
- GitHub Actions CI for pytest.
- English main documentation with Korean mirrors for README and supporting docs.

### Validation Evidence

- Local and GitHub Actions pytest validation passed for the release baseline.
- Jetson Orin Nano dummy scheduler smoke validated CLI execution, telemetry
  generation, resource snapshots, and low-priority drops.
- Jetson Orin Nano ONNX Runtime smoke validated the ONNX worker path with
  `CPUExecutionProvider`.
- Synthetic overload comparison showed scheduler/load-shedding behavior
  protecting high-priority task latency by dropping low-priority queued work.

### Boundaries

- InferEdgeOrchestrator is the runtime operation-control layer after deployment.
- InferEdge remains the deployment validation pipeline.
- Integration with InferEdge is file-based through `result.json`.
- This project is not a Triton or DeepStream replacement.
- This project is not a benchmark tool; latency and telemetry are used to
  explain scheduler decisions and overload behavior.
