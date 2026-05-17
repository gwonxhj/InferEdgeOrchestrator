# Agent Orchestration Summary Contract

Language: [English](agent_orchestration_summary_contract.md) | 한국어

InferEdgeOrchestrator는 reliable edge agent runtime 경로에서 scheduler와 policy evidence를 기록합니다.

이 contract는 Forge `agent_manifest.json`과 Runtime `result.agent` metadata를 `orchestration_summary.json`으로 연결하며, 이후 AIGuard와 Lab이 해석할 수 있는 scheduling evidence를 제공합니다.

## 범위

이 summary는 operation-control evidence입니다. Runtime inference result, AIGuard diagnosis, Lab deployment decision을 대체하지 않습니다.

책임:

- `agent_id`, `task_id`, priority, latency budget, fallback policy context 보존
- scheduling decision 기록
- queue/drop/deadline/fallback telemetry 기록
- downstream diagnosis/reporting을 위한 `policy_decision_log` 제공

범위 밖:

- production queue infrastructure
- cloud orchestration
- final deployment decision ownership
- LLM/voice framework execution

## 입력

demo config는 다음 contract를 참조할 수 있습니다.

| Input | Contract |
|---|---|
| Forge agent manifest | `inferedge-agent-manifest-v1` |
| Runtime agent result | `inferedge-runtime-agent-task-v1` |

예시 config:

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

## 출력

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

기존 telemetry field는 그대로 유지됩니다.

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

실행:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/agent_3_workload_demo.json \
  --output reports/agent_orchestration_summary.json \
  --frames 8
```

생성된 summary는 synthetic backlog 상황에서 어떤 agent task가 실행, drop, 보호, 제한되었는지 보여줍니다.

## Sustained Scenario Starter

첫 sustained-demo 단계에서는 3-agent scenario를 명시적인 mode로 분리합니다.

- [`configs/agent_3_workload_normal.json`](../configs/agent_3_workload_normal.json)
- [`configs/agent_3_workload_overload.json`](../configs/agent_3_workload_overload.json)
- [`configs/agent_3_workload_sustained_high_load.json`](../configs/agent_3_workload_sustained_high_load.json)

high-load mode 실행:

```bash
python3 -m inferedge_orchestrator run \
  --config configs/agent_3_workload_sustained_high_load.json \
  --output reports/agent_sustained_high_load.json \
  --frames 16
```

생성된 summary에는 `queue_depth_timeline`, `latency_timeline`,
`sustained_runtime_summary`, 그리고 `decision_reason`,
`total_backlog_before`, `backlog_threshold`, `queue_depth_snapshot`을 포함한
policy decision이 들어갑니다. Runtime은 task execution/result layer로
유지하고, scheduling/drop/fallback과 policy evidence는 Orchestrator가
소유합니다.
이 starter는 full external YOLO/Whisper/FastAPI integration이 아니라
profiled local workload evidence입니다. device-specific sustained validation은
별도 다음 단계입니다.

## Multi-Workload Sustained Starter

다음 starter command는 기존 orchestration summary를 유지하면서
`multi_workload_sustained_summary`와 optional `tegrastats_timeline`을
추가합니다.

```bash
python3 -m inferedge_orchestrator run-multi-workload-sustained \
  --config configs/agent_multi_workload_sustained_local.json \
  --output reports/agent_multi_workload_sustained.json \
  --frames 16
```

커밋된 config는 의도한 lightweight workload profile을 명시합니다.

- frame queue 기반 YOLO-like vision loop
- FastAPI-style concurrent request ingress 기반 Whisper-like command burst
- optional tegrastats timeline evidence를 포함할 수 있는 safety/monitor loop

기본 실행은 lightweight local CPU profile adapter를 사용하므로 model
download, FastAPI server, Jetson-only telemetry 없이도 workload pressure를
테스트할 수 있습니다. 첫 Vision producer 단계는
[`configs/agent_multi_workload_sustained_vision_file.json`](../configs/agent_multi_workload_sustained_vision_file.json)이며,
작은 local image fixture를 Vision workload로 전달하고 `producer_source=image_file`,
input digest, sampled byte statistics를 기록합니다. 외부 YOLO, Whisper, FastAPI,
Jetson producer는 선택적 후속 integration입니다.

## Compatibility Rules

- `schema_version`은 `inferedge-orchestration-summary-v1`입니다.
- `policy_decision_log`는 downstream reader를 위해 `policy_decisions`와 같은 내용을 명시적으로 제공합니다.
- Agent field는 additive이며 기존 task telemetry는 계속 읽을 수 있습니다.
- Sustained telemetry field도 additive이며 기존 `tasks`, `result_events`,
  `policy_decision_log`를 대체하지 않습니다.
- Orchestrator는 scheduling evidence provider입니다. 최종 deployment decision owner는 Lab입니다.
