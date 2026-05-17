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
  "queue_depth_timeline": [],
  "latency_timeline": [],
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
- `resource_snapshots`
- `schedule_decisions`

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
`queue_depth_snapshot` fields. This keeps Runtime as the task execution/result
layer while Orchestrator owns scheduling, drop/fallback, and policy evidence.
This starter remains synthetic/dummy workload evidence; real lightweight
workload contention and device-specific sustained validation are separate next
steps.

## Compatibility Rules

- `schema_version` is `inferedge-orchestration-summary-v1`.
- `policy_decision_log` mirrors `policy_decisions` for downstream readers that expect an explicit log name.
- Agent fields are additive; existing task telemetry remains readable.
- Sustained telemetry fields are additive and do not replace the existing
  `tasks`, `result_events`, or `policy_decision_log` fields.
- Orchestrator provides scheduling evidence only. Lab remains the final deployment decision owner.
