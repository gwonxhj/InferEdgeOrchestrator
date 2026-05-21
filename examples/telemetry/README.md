# Telemetry Samples

Language: English | [한국어](README.ko.md)

These JSON files are small, versioned examples of InferEdgeOrchestrator runtime
evidence. They are intended for schema review and portfolio reading without
running the CLI first.

They are not benchmark artifacts. Raw runtime reports remain ignored under
`reports/`, while these samples are curated documentation artifacts under
`examples/telemetry/`.

## Samples

| File | What it shows |
| --- | --- |
| `phase3_overload_sample.json` | Synthetic FIFO baseline vs scheduler/load-shedding comparison. The detector p95 end-to-end latency improves from `782.0ms` to `8.0ms`, while low-priority classifier work is dropped. |
| `agent_scheduler_delay_sample.json` | Curated excerpt from the 3-agent sustained high-load config showing `scheduler_delay_event_count`, a delayed execution event, policy/drop reason counts, and the downstream AIGuard/Lab signal names. |
| `jetson_smoke_dummy_sample.json` | Telemetry schema from the Jetson dummy smoke path: task counts, drop events, result events, scheduler decisions, and resource snapshots. |
| `jetson_onnx_smoke_sample.json` | Telemetry schema from the ONNX Runtime worker smoke path: result event metadata, output shape `[1, 2]`, and resource snapshots. |
| `jetson_tensorrt_contention_sample.json` | TensorRT-backed scheduler/load-shedding evidence from Jetson: `detector_trt` is protected, `classifier_trt` is shed, and result events keep TensorRT backend metadata. |
| `jetson_tensorrt_diverse_contention_sample.json` | Distinct-engine TensorRT contention evidence from Jetson: generated detector/classifier engines both appear in result events while the low-priority classifier is shed. |

## Schema Signals

The samples cover these telemetry signals:

- task-level `executed` and `dropped` counts
- mean and p95 latency
- maximum queue backlog
- drop events
- overload or policy decisions
- scheduler delay event counts and queue wait evidence
- result events
- resource snapshots

For the complete validation evidence index, see
[`docs/validation_evidence.md`](../../docs/validation_evidence.md).

Physical-device validation details live in
[`docs/jetson_smoke_test.md`](../../docs/jetson_smoke_test.md).
