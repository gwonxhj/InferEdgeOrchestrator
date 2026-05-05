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
| `jetson_smoke_dummy_sample.json` | Jetson dummy smoke path의 telemetry schema. task count, drop event, result event, scheduler decision, resource snapshot을 보여준다. |
| `jetson_onnx_smoke_sample.json` | ONNX Runtime worker smoke path의 telemetry schema. result event metadata, output shape `[1, 2]`, resource snapshot을 보여준다. |

## Schema Signals

sample은 다음 telemetry signal을 포함한다.

- task별 `executed`, `dropped` count
- mean/p95 latency
- maximum queue backlog
- drop events
- overload 또는 policy decisions
- result events
- resource snapshots

실제 physical-device validation summary는 `docs/jetson_smoke_test.md`에 있다.
