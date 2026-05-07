# TensorRT Model Diversity Proposal

Language: [English](tensorrt_model_diversity.md) | 한국어

Status: v0.2 proposal. 이 문서는 planning document이며, 확정된 validation
evidence가 아니다.

이 문서는 현재 shared tiny identity engine 기반 TensorRT contention scenario를
서로 다른 detector/classifier-style TensorRT engine으로 확장할 때의 기준을 정의한다.
프로젝트 포지셔닝은 그대로 유지한다. 목표는 single-model throughput benchmark가
아니라 multi-task contention 상황의 runtime operation control이다.

## Decision Boundary

v0.1.x line은 TensorRT contention evidence를 shared tiny identity engine으로
유지한다. Identity engine은 이미 Jetson에서 TensorRT worker path가 scheduler,
load-shedding, telemetry에 참여할 수 있음을 증명한다.

v0.2 proposal은 source model, engine build procedure, artifact policy, evidence
boundary가 명확해진 뒤 diversified TensorRT contention scenario를 추가하는 것이다.

## Goal

v0.2 scenario는 다음 질문에 답해야 한다.

> 서로 다른 TensorRT-backed workload 2개가 같은 Jetson device에서 contention을
> 만들 때, InferEdgeOrchestrator가 high-priority task를 보호하고 lower-priority
> work를 observable scheduling/load-shedding decision으로 제한하는가?

기대 evidence:

- 서로 다른 TensorRT engine 2개 이상을 Jetson에서 local build한다.
- high-priority task가 backlog 상황에서도 보호된다.
- low-priority task는 policy에 따라 drop, delay, 또는 FPS 제한을 받는다.
- telemetry가 task execution, drop, overload event, policy decision, TensorRT
  backend metadata, resource snapshot을 기록한다.
- 문서는 이 결과가 TensorRT benchmark가 아니라 operation-control evidence라고
  명확히 적는다.

## Non-Goals

이 milestone에서 추가하지 않는다.

- InferEdgeOrchestrator 내부 model conversion pipeline.
- TensorRT benchmark table 또는 model leaderboard.
- 큰 ONNX file, TensorRT `.plan`/`.engine` binary, raw device log의 git commit.
- Triton, DeepStream, Kubernetes, distributed serving, multi-device orchestration.
- production throughput 또는 stable device performance claim.

## Candidate Workloads

첫 diversified scenario는 현실적인 대형 모델보다 작고 license가 명확하며 build가 쉬운
모델을 우선한다. 목적은 서로 다른 engine shape와 execution profile을 만들되
재현성을 유지하는 것이다.

선정한 v0.2 candidate pair:

| Role | Candidate source | Planned ONNX path | Planned engine path | Why it fits |
| --- | --- | --- | --- | --- |
| High-priority detector-like task | local script로 생성하는 synthetic tiny CNN | `models/generated/detector_tiny.onnx` | `models/generated/detector_tiny_fp16.plan` | image-shaped input과 convolution/pooling-style operation을 사용하므로 identity smoke보다 latency-sensitive perception work에 가깝다. |
| Low-priority classifier-like task | local script로 생성하는 synthetic tiny MLP 또는 small classifier CNN | `models/generated/classifier_tiny.onnx` | `models/generated/classifier_tiny_fp16.plan` | detector-like task와 다른 graph shape를 가진 droppable enrichment/classification work를 대표한다. |

결정: 첫 v0.2 diversity scenario는 synthetic local model을 사용한다. TensorRT
contention path가 generated model로 안정화되기 전까지 외부 model download는 피한다.

Generator contract:

- Script: `scripts/create_tensorrt_diverse_onnx.py`
- Default output directory: `models/generated`
- Default mode: 두 model 모두 생성
- Detector ONNX: `models/generated/detector_tiny.onnx`
- Classifier ONNX: `models/generated/classifier_tiny.onnx`
- `models/generated/` 아래 생성 ONNX와 향후 TensorRT engine은 git에서 ignore한다.

Jetson build contract:

- Script: `scripts/build_jetson_tensorrt_diverse_engines.sh`
- Build target: Jetson-local FP16 TensorRT engine.
- Detector engine: `models/generated/detector_tiny_fp16.plan`
- Classifier engine: `models/generated/classifier_tiny_fp16.plan`
- Build log: `reports/trtexec_detector_tiny_fp16_build.log`,
  `reports/trtexec_classifier_tiny_fp16_build.log`
- Validation note: `reports/jetson_tensorrt_diverse_engine_build.md`
- Success marker: `PASS_TENSORRT_DIVERSE_ENGINE_BUILD`
- 이 단계는 build-only step이다. Scheduler behavior 또는 TensorRT throughput을
  주장하지 않는다.
- Jetson result: 2026-05-06 `nano01`에서 확인했다. Detector-like FP16 engine은
  44,428 bytes, classifier-like FP16 engine은 17,764 bytes였다.

Jetson guard contract:

- Script: `scripts/smoke_jetson_tensorrt_diverse_engines.sh`
- Detector input/output: `detector_input` -> `detector_scores`
- Classifier input/output: `classifier_input` -> `classifier_logits`
- Result JSON: `reports/jetson_tensorrt_diverse_guard_results.json`
- Validation note: `reports/jetson_tensorrt_diverse_guard_validation.md`
- Success marker: `PASS_TENSORRT_DIVERSE_GUARD`
- 이 단계는 generated engine 각각의 individual TensorRtWorker execution을 검증한다.
  Scheduler/load-shedding contention evidence는 아니다.
- Jetson result: 2026-05-06 `nano01`에서 확인했다. 두 generated engine 모두
  `TensorRtWorker`를 통해 TensorRT backend metadata와 output preview를 반환했다.

Synthetic을 먼저 선택하는 이유:

- License clarity: 생성된 source model은 repository-owned test fixture이므로
  third-party redistribution 문제가 없다.
- Size control: generator가 ONNX file을 작게 유지하고 큰 binary artifact를 피할 수
  있다.
- Jetson practicality: Jetson Orin Nano에서 `trtexec`로 빠르게 build할 수 있다.
- Evidence focus: 서로 다른 graph shape를 만들되 model quality 또는 throughput
  comparison으로 milestone이 흐르지 않는다.

선택 규칙:

- 첫 v0.2 implementation에서는 source model을 script로 local generation해야 한다.
- Engine binary는 Jetson에서 생성하고 git에서 제외한다.
- Build command에는 TensorRT, CUDA, L4T, precision, input shape, profile 정보를
  포함한다.
- Jetson Orin Nano에서 smoke scenario로 실행 가능한 크기여야 한다.
- Generator는 deterministic해야 telemetry와 engine metadata를 run 간 비교하기 쉽다.
- Detector-like model과 classifier-like model은 input shape 또는 operation mix가
  달라야 하지만, output은 단순 metadata tensor여도 된다. 이 scenario는 task accuracy가
  아니라 scheduling behavior를 검증한다.

미룬 대안:

- Public tiny classifier model은 license, size, download provenance를 문서화한 뒤에만
  재검토한다.
- Public tiny detector model은 build flow가 smoke validation에 충분히 작고 benchmark
  positioning을 만들지 않을 때만 재검토한다.
- 실제 production detector/classifier model은 이후 milestone이 evidence boundary를
  명시적으로 바꾸지 않는 한 이 repository 범위 밖에 둔다.

## Artifact Policy

Commit 대상:

- Config template.
- Engine build script 또는 문서화된 command.
- Synthetic model을 쓸 경우 작은 source-model generator script.
- 성공한 Jetson run에서 파생한 curated sample telemetry JSON.
- Evidence를 요약하는 human-readable docs.

Commit하지 않는다:

- TensorRT `.plan` 또는 `.engine` file.
- 큰 ONNX file.
- Raw `reports/` output.
- Raw `tegrastats` log.
- License와 size가 repository에 적합하다고 명시적으로 확인되지 않은 downloaded
  third-party model file.

## Proposed Config Shape

첫 v0.2 scenario에는 기존 schema로 충분해야 한다. Core schema를 바꾸기보다 새 config
file을 추가하는 방향을 우선한다.

```json
{
  "run": {
    "name": "jetson_tensorrt_diverse_contention",
    "input_source": "dummy",
    "overload_backlog_threshold": 6
  },
  "tasks": [
    {
      "name": "detector_trt",
      "model_path": "models/detector_tiny.onnx",
      "engine_path": "models/detector_tiny_fp16.plan",
      "priority": 100,
      "target_fps": 15,
      "latency_budget_ms": 80,
      "queue_size": 4,
      "drop_policy": "drop_oldest",
      "worker": "tensorrt",
      "worker_options": {
        "precision": "fp16",
        "allow_engine_build": false,
        "profile_name": "detector_tiny_fp16"
      }
    },
    {
      "name": "classifier_trt",
      "model_path": "models/classifier_tiny.onnx",
      "engine_path": "models/classifier_tiny_fp16.plan",
      "priority": 10,
      "target_fps": 5,
      "latency_budget_ms": 200,
      "queue_size": 4,
      "drop_policy": "drop_oldest",
      "worker": "tensorrt",
      "worker_options": {
        "precision": "fp16",
        "allow_engine_build": false,
        "profile_name": "classifier_tiny_fp16"
      }
    }
  ]
}
```

## Build Procedure Requirements

Smoke script를 추가하기 전에 Jetson-local build flow를 문서화하거나 script로 고정한다.

1. Device inventory를 기록한다: hostname, Ubuntu, L4T, CUDA, TensorRT, Python,
   `trtexec`, optional `tegrastats` availability.
2. Source ONNX model을 local ignored directory에 생성하거나 가져온다.
3. 각 TensorRT engine을 명시적 `trtexec` command로 build한다.
4. Engine input/output tensor name, shape, dtype을 inspect한다.
5. 각 engine에 대해 worker guard smoke를 독립 실행한다.
6. Multi-task contention smoke를 실행한다.
7. Device run이 통과한 뒤에만 작은 sample telemetry artifact를 curate한다.

## Acceptance Criteria

v0.2 diversified TensorRT scenario는 아래 조건을 모두 만족할 때 완료로 본다.

- 서로 다른 TensorRT engine 2개 이상을 Jetson에서 문서화된 source model로 build한다.
- Engine은 git에 commit하지 않는다.
- Smoke script는 engine이 하나라도 없으면 명확히 실패한다.
- Telemetry에 두 task 모두의 TensorRT backend metadata가 포함된다.
- High-priority task drop은 0이거나 의도적으로 제한된 범위다.
- Low-priority limiting이 drop event, policy decision, overload event로 보인다.
- Validation evidence는 device, runtime version, artifact boundary를 명시한다.
- README wording은 scheduler/load-shedding 중심으로 유지하고 benchmark claim을
  피한다.

## Step Plan

1. Source model을 선택하고 license/size/build constraint를 문서화한다.
2. Jetson-local engine build guide 또는 helper script를 추가한다.
3. `configs/jetson_tensorrt_diverse_contention.json`을 추가한다.
4. `scripts/smoke_jetson_tensorrt_diverse_contention.sh`를 추가한다.
5. Jetson에서 individual engine guard smoke를 실행한다.
6. Jetson에서 diversified contention smoke를 실행한다.
7. Run이 통과하면 curated sample telemetry artifact를 추가한다.
8. 확인된 결과만 validation evidence와 release note에 반영한다.

Current config contract:

- Config: `configs/jetson_tensorrt_diverse_contention.json`
- High-priority task: `detector_trt`
- Low-priority task: `classifier_trt`
- Detector engine: `models/generated/detector_tiny_fp16.plan`
- Classifier engine: `models/generated/classifier_tiny_fp16.plan`
- Smoke script: `scripts/smoke_jetson_tensorrt_diverse_contention.sh`
- Success marker: `PASS_TENSORRT_DIVERSE_CONTENTION`
- Status: Jetson Orin Nano `nano01`에서 `2026-05-07T03:38:21Z` 기준 확인됨.

확인된 Jetson contention 결과:

| Field | Value |
| --- | --- |
| Result | `PASS_TENSORRT_DIVERSE_CONTENTION` |
| Frames | `6` |
| Detector | `executed=6`, `dropped=0` |
| Classifier | `executed=1`, `dropped=5` |
| Overload events | `5` |
| Limited tasks | `classifier_trt` |
| Backends | `tensorrt` |
| Raw telemetry | `reports/jetson_tensorrt_diverse_contention_telemetry.json` |
| Raw validation note | `reports/jetson_tensorrt_diverse_contention_validation.md` |

이는 서로 다른 engine의 scheduler/load-shedding behavior와 telemetry shape를
확인한다. TensorRT throughput 또는 안정적인 latency claim은 하지 않는다.

## Risks

- Model acquisition이 scheduler evidence에서 주의를 분산시킬 수 있다.
- 큰 engine은 이야기를 performance comparison처럼 보이게 만들 수 있다.
- Device-local TensorRT engine은 Jetson software version이 바뀌면 portable하지 않을
  수 있다.
- License 또는 artifact-size 문제가 repository review를 어렵게 만들 수 있다.

완화책: model은 작게 유지하고, engine은 local artifact로 두며, 모든 claim은 telemetry와
연결하고, InferEdgeOrchestrator를 operation-control layer로 유지한다.
