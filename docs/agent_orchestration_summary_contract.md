# Agent Orchestration Summary Contract

Language: English | [한국어](agent_orchestration_summary_contract.ko.md)

InferEdgeOrchestrator records scheduler and policy evidence for the reliable edge agent runtime path.

This contract connects Forge `agent_manifest.json` and Runtime `result.agent` metadata to an `orchestration_summary.json` file that AIGuard and Lab can consume later.

## Scope

The summary is operation-control evidence. It does not replace Runtime inference results, AIGuard diagnosis, or Lab deployment decisions.

Responsibilities:

- preserve `agent_id`, `task_id`, priority, latency budget, and fallback policy context
- record scheduling decisions
- record queue/drop/deadline/fallback telemetry
- expose a `policy_decision_log` for downstream diagnosis/reporting

Out of scope:

- production queue infrastructure
- cloud orchestration
- final deployment decision ownership
- LLM/voice framework execution

## Inputs

The demo config can reference:

| Input | Contract |
|---|---|
| Forge agent manifest | `inferedge-agent-manifest-v1` |
| Runtime agent result | `inferedge-runtime-agent-task-v1` |

Example config:

```json
{
  "name": "vision_agent",
  "agent_manifest_path": "examples/agent_runtime/vision_agent_manifest.json",
  "runtime_result_path": "examples/agent_runtime/vision_runtime_result.json",
  "target_fps": 30,
  "queue_size": 2,
  "worker": "dummy"
}
```

## Output

Top-level summary:

```json
{
  "schema_version": "inferedge-orchestration-summary-v1",
  "agent_runtime_summary": {
    "schema_version": "inferedge-orchestration-summary-v1",
    "source_contracts": {
      "forge_agent_manifest": "inferedge-agent-manifest-v1",
      "runtime_agent_result": "inferedge-runtime-agent-task-v1"
    },
    "agents": {},
    "totals": {
      "executed_count": 0,
      "dropped_count": 0,
      "deadline_missed_count": 0,
      "fallback_count": 0,
      "policy_decision_count": 0,
      "overload_event_count": 0
    }
  },
  "sustained_runtime_summary": {
    "schema_version": "inferedge-orchestrator-sustained-summary-v1",
    "scenario_mode": "sustained_high_load",
    "queue_depth_sample_count": 0,
    "latency_sample_count": 0,
    "max_total_queue_depth": 0
  },
  "queue_state_summary": {
    "schema_version": "inferedge-orchestrator-queue-state-v1",
    "queue_pressure_state": "nominal"
  },
  "worker_health_snapshot": {
    "schema_version": "inferedge-orchestrator-worker-health-v1",
    "workers": {}
  },
  "runtime_event_summary": {
    "schema_version": "inferedge-orchestrator-runtime-event-summary-v1",
    "event_count": 0,
    "event_type_counts": {}
  },
  "queue_depth_timeline": [],
  "latency_timeline": [],
  "runtime_event_timeline": [],
  "policy_decision_log": []
}
```

Existing telemetry fields remain available:

- `tasks`
- `overload_events`
- `queue_depth_timeline`
- `latency_timeline`
- `policy_decisions`
- `drop_events`
- `result_events`
- `runtime_event_timeline`
- `resource_snapshots`
- `schedule_decisions`

Additive operation-health fields:

- `queue_state_summary`: summarizes queue pressure, maximum total backlog,
  final queue depth, per-task maximum queue depth, and the overload threshold.
- `worker_health_snapshot`: summarizes per-task worker health as `healthy`,
  `constrained`, `degraded`, or `idle` using executed/drop/deadline/fallback
  evidence. Each worker also records additive `health_reasons`,
  `drop_rate`, `deadline_miss_rate`, and `fallback_rate` fields.
- `runtime_event_summary`: counts runtime event types and additive reason
  counts for policy decisions, drops, deadline misses, fallback decisions, and
  scheduler-delay events.
- `runtime_event_timeline`: ordered event log for queue snapshots, drops,
  scheduler selections, executions, policy decisions, and resource snapshots.
  Execution events include additive `scheduler_delay_cycles` and
  `queue_wait_ms` fields for backlog/delay inspection.

## 3-Agent Demo

Config:

- [`configs/agent_3_workload_demo.json`](../configs/agent_3_workload_demo.json)

Agents:

| Agent | Role | Priority | Latency Budget | Policy Context |
|---|---|---:|---:|---|
| `safety_monitor_agent` | safety/monitor | 100 | 20 ms | protect |
| `vision_agent` | vision | 90 | 33 ms | drop stale |
| `voice_command_agent` | voice/command | 50 | 120 ms | defer |

Run:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/agent_3_workload_demo.json \
  --output reports/agent_orchestration_summary.json \
  --frames 8
```

The generated summary shows which agent tasks were scheduled, dropped, protected, or limited under synthetic backlog.

## Sustained Scenario Starter

The first sustained-demo step separates the 3-agent scenario into explicit
modes:

- [`configs/agent_3_workload_normal.json`](../configs/agent_3_workload_normal.json)
- [`configs/agent_3_workload_overload.json`](../configs/agent_3_workload_overload.json)
- [`configs/agent_3_workload_sustained_high_load.json`](../configs/agent_3_workload_sustained_high_load.json)

Run the high-load mode:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/agent_3_workload_sustained_high_load.json \
  --output reports/agent_sustained_high_load.json \
  --frames 16
```

The generated summary includes `queue_depth_timeline`, `latency_timeline`,
`sustained_runtime_summary`, and policy decisions with explicit
`decision_reason`, `total_backlog_before`, `backlog_threshold`, and
`queue_depth_snapshot` fields. Worker health also includes `health_reasons`
and per-worker drop/deadline/fallback rates, while runtime event summaries
count policy/drop reasons and scheduler-delay events. This keeps Runtime as the
task execution/result layer while Orchestrator owns scheduling, drop/fallback,
and policy evidence.
For a small curated scheduler-delay evidence excerpt from this path, see
[`examples/telemetry/agent_scheduler_delay_sample.json`](../examples/telemetry/agent_scheduler_delay_sample.json).
It is the deterministic smoke marker that downstream AIGuard can turn into
`scheduler_delay_pattern` and Lab can display under `AIGuard Orchestrator
Operation Evidence`.
This starter remains profiled local workload evidence rather than full external
YOLO/Whisper/FastAPI integration. Device-specific sustained validation remains a
separate next step.

## Multi-Workload Sustained Starter

The next starter command keeps the existing orchestration summary intact and
adds `multi_workload_sustained_summary` plus optional `tegrastats_timeline`:

```bash
python3 -m inferedge_orchestrator run-multi-workload-sustained \
  --config configs/agent_multi_workload_sustained_local.json \
  --output reports/agent_multi_workload_sustained.json \
  --frames 16
```

The committed config names the intended lightweight workload profiles:

- YOLO-like vision loop through a frame queue
- Whisper-like command burst through FastAPI-style concurrent request ingress
- Safety/monitor loop with optional tegrastats timeline evidence

The sustained output preserves the raw `scenario_mode` and also adds
human-readable scenario identity fields in `run`, `sustained_runtime_summary`,
and `multi_workload_sustained_summary`:

| scenario_mode | scenario_label | scenario_category |
|---|---|---|
| `normal` | `normal_scheduler_smoke` | `normal` |
| `overload` | `overload_scheduler_pressure` | `overload` |
| `sustained_high_load` | `producer_backed_sustained_high_load` | `sustained` |
| `device_local` | `device_local_sustained_starter` | `device_local` |

These labels make repeated run registries easier to scan while keeping
`scenario_mode` backward-compatible as the machine-readable mode.

Default execution now uses lightweight local CPU profile adapters so the
contract can exercise workload pressure without requiring model downloads,
FastAPI servers, or Jetson-only telemetry. The first Vision producer step is
[`configs/agent_multi_workload_sustained_vision_file.json`](../configs/agent_multi_workload_sustained_vision_file.json),
which routes a tiny local image fixture into the Vision workload and records
`producer_source=image_file`, input digest, and sampled byte statistics. The
first Voice ingress producer step is
[`configs/agent_multi_workload_sustained_voice_ingress.json`](../configs/agent_multi_workload_sustained_voice_ingress.json),
which routes a small FastAPI-style request fixture into the Voice workload and
records selected routes, request digest, and burst evidence. The first Safety
monitor producer step is
[`configs/agent_multi_workload_sustained_safety_resource.json`](../configs/agent_multi_workload_sustained_safety_resource.json),
which routes a small resource snapshot fixture into the Safety workload and
records CPU, memory, temperature, fallback, deadline, and degradation evidence.
The explicit device-local starter is
[`configs/agent_multi_workload_sustained_device_local.json`](../configs/agent_multi_workload_sustained_device_local.json),
which runs the committed Vision image, Voice request, and Safety resource
producers in `scenario_mode=device_local` and records `producer_sources` plus
`device_local_producer_count` in `multi_workload_sustained_summary`. External
YOLO, Whisper, FastAPI, live monitor, and Jetson producers remain incremental
integrations, not required dependencies.

The CLI can override the committed device-local producer fixtures at run time
with `--vision-input`, `--voice-ingress-payload`, and `--resource-snapshot`.
`--vision-input` accepts a single image/video file or a directory of image
frames. Directories are recorded as `image_sequence_file` producer evidence and
cycled deterministically during sustained validation.
For a minimal local process signal, `--capture-process-resource-snapshot` writes
a small process resource snapshot next to the output report and routes it into
the Safety workload with `producer_source=process_resource_snapshot`.

## Compatibility Rules

- `schema_version` is `inferedge-orchestration-summary-v1`.
- `policy_decision_log` mirrors `policy_decisions` for downstream readers that expect an explicit log name.
- Agent fields are additive; existing task telemetry remains readable.
- Sustained telemetry fields are additive and do not replace the existing
  `tasks`, `result_events`, or `policy_decision_log` fields.
- Orchestrator provides scheduling evidence only. Lab remains the final deployment decision owner.
