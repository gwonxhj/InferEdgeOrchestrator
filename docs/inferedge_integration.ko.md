# InferEdge File-Based Integration

Language: [English](inferedge_integration.md) | 한국어

InferEdge와 InferEdgeOrchestrator는 의도적으로 분리된 프로젝트다.

- InferEdge는 모델이 배포 가능한지 검증한다.
- InferEdgeOrchestrator는 배포 이후 runtime operation을 제어한다.

두 프로젝트의 integration boundary는 import가 아니라 file이다.
InferEdgeOrchestrator는 InferEdge `result.json` artifact를 읽고, 그 안의
latency signal을 이용해 Orchestrator task config의 초기
`latency_budget_ms`를 추천한다.

## Create Config From InferEdge Result

```bash
python3 -m inferedge_orchestrator from-inferedge \
  --result path/to/result.json \
  --output configs/from_inferedge.json \
  --task-name detector \
  --model-path models/detector.onnx \
  --priority 100 \
  --target-fps 15 \
  --queue-size 4
```

helper는 먼저 `expected_latency_ms`를 찾는다. 해당 field가 없으면
`mean_latency_ms`, `p95_latency_ms`, `latency_ms` 같은 일반적인 latency
field를 fallback으로 사용할 수 있다.

추천 budget 계산식:

```text
ceil(expected_latency_ms * budget_multiplier)
```

기본 `budget_multiplier`는 `1.5`다.

생성 config는 파일로 쓰기 전에 validation을 통과해야 한다. 예약된 TensorRT schema
path를 사용할 때는 `--worker tensorrt`와 `--engine-path`를 함께 전달해야
Orchestrator validation에서 실패하는 config를 만들지 않는다. 이 helper가
TensorRT 실행을 구현하는 것은 아니다.

## Boundary Rule

이 프로젝트에서 InferEdge 내부 모듈을 import하지 않는다. 관계는 artifact
기반으로 유지한다.

```text
InferEdge result.json -> InferEdgeOrchestrator config JSON
```
