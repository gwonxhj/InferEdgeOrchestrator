# Telemetry Samples

Language: [English](README.md) | 한국어

이 JSON 파일들은 InferEdgeOrchestrator runtime evidence를 작게 정리한
versioned example이다. CLI를 먼저 실행하지 않아도 telemetry schema와
portfolio evidence를 확인할 수 있도록 제공한다.

이 파일들은 benchmark artifact가 아니다. raw runtime report는 계속
`reports/` 아래에서 ignore하고, 이 sample들은 `examples/telemetry/` 아래에
두는 문서용 artifact다.

## Samples

| File | What it shows |
| --- | --- |
| `phase3_overload_sample.json` | synthetic FIFO baseline과 scheduler/load-shedding 비교. detector p95 end-to-end latency가 `782.0ms`에서 `8.0ms`로 개선되고 low-priority classifier work가 drop된다. |
| `agent_scheduler_delay_sample.json` | 3-agent sustained high-load config에서 추출한 curated excerpt. `scheduler_delay_event_count`, 지연된 execution event, policy/drop reason count, downstream AIGuard/Lab signal name을 보여준다. |
| `remote_fallback_recovery_sample.json` | remote dispatch starter에서 primary HTTP starter `connection_error`, 제한된 fallback worker recovery, retry/fallback plan field, downstream AIGuard/Lab signal name을 보여주는 curated excerpt. |
| `jetson_smoke_dummy_sample.json` | Jetson dummy smoke path의 telemetry schema. task count, drop event, result event, scheduler decision, resource snapshot을 보여준다. |
| `jetson_onnx_smoke_sample.json` | ONNX Runtime worker smoke path의 telemetry schema. result event metadata, output shape `[1, 2]`, resource snapshot을 보여준다. |
| `jetson_tensorrt_contention_sample.json` | Jetson의 TensorRT-backed scheduler/load-shedding evidence. `detector_trt`는 보호되고 `classifier_trt`는 제한되며 result event에 TensorRT backend metadata가 유지된다. |
| `jetson_tensorrt_diverse_contention_sample.json` | Jetson의 distinct-engine TensorRT contention evidence. generated detector/classifier engine이 result event에 모두 남고 low-priority classifier가 제한된다. |

## Schema Signals

sample은 다음 telemetry signal을 포함한다.

- task별 `executed`, `dropped` count
- mean/p95 latency
- maximum queue backlog
- drop events
- overload 또는 policy decisions
- scheduler delay event count와 queue wait evidence
- remote dispatch starter failure/fallback recovery evidence
- result events
- resource snapshots

전체 validation evidence index는
[`docs/validation_evidence.ko.md`](../../docs/validation_evidence.ko.md)에 있다.

실제 physical-device validation detail은
[`docs/jetson_smoke_test.ko.md`](../../docs/jetson_smoke_test.ko.md)에 있다.
