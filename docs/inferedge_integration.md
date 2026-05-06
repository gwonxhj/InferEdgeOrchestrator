# InferEdge File-Based Integration

Language: English | [한국어](inferedge_integration.ko.md)

InferEdge and InferEdgeOrchestrator intentionally stay separate.

- InferEdge validates whether a model is deployable.
- InferEdgeOrchestrator controls runtime operation after deployment.

The integration boundary is a file, not an import. InferEdgeOrchestrator reads an
InferEdge `result.json` artifact and uses the latency signal to recommend an
initial `latency_budget_ms` for an Orchestrator task config.

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

The helper searches for `expected_latency_ms` first. If that exact field is not
present, it can fall back to common latency fields such as `mean_latency_ms`,
`p95_latency_ms`, or `latency_ms`.

The recommended budget is:

```text
ceil(expected_latency_ms * budget_multiplier)
```

The default `budget_multiplier` is `1.5`.

The generated config is validated before it is written. When using the reserved
TensorRT schema path, pass `--worker tensorrt` together with `--engine-path` so
the helper does not emit a config that would fail Orchestrator validation.
TensorRT execution is still not implemented by this helper.

## Boundary Rule

Do not import InferEdge internals from this project. Keep the relationship
artifact-based:

```text
InferEdge result.json -> InferEdgeOrchestrator config JSON
```
