# Remote Dispatch Starter

Language: English | [한국어](remote_dispatch_starter.ko.md)

InferEdgeOrchestrator includes a small file-based remote dispatch starter for
the Runtime Operation Platform roadmap. It is designed to prove the handoff
contract for remote edge workers without claiming production remote execution.
By default it remains plan-only. When `--execute-plan` is explicitly enabled,
it can attempt a small HTTP/SSH starter call and record the result as structured
evidence.

## Scope

This starter answers one narrow question:

> Given a remote worker registry and a task request, which edge worker should
> receive the task, and why?

Without `--execute-plan`, it does not open network sockets or run SSH commands.
With `--execute-plan`, it may perform a single starter HTTP POST or SSH command
declared by the selected worker. If that starter execution fails with an error
listed in the task request `retry_policy.fallback_on`, it can make one bounded
starter attempt against an eligible fallback worker when `max_attempts` allows
it. It still does not manage Cloudflare tunnels, auth, heartbeat, long-lived
production workers, or production retry orchestration. Those remain future
hardening steps.

## Inputs

Worker registry:

- schema: `inferedge-remote-worker-registry-v1`
- example: [`examples/remote_worker_registry.json`](../examples/remote_worker_registry.json)

Task request:

- schema: `inferedge-remote-task-request-v1`
- example: [`examples/remote_task_request.json`](../examples/remote_task_request.json)
- local HTTP example:
  [`examples/remote_task_request_http_local.json`](../examples/remote_task_request_http_local.json)

The starter matches:

- worker online/offline status
- health state: `healthy` or `constrained`
- required backend or worker type
- target device
- optional retry policy fields in the task request

Fallback starter execution is intentionally narrow:

- the primary worker is selected first from eligible workers
- `max_attempts` controls whether a fallback starter attempt is allowed
- `fallback_on` controls which primary error categories trigger fallback
- fallback attempts are recorded in `fallback_execution_result`
- fallback execution is evidence collection, not production-grade retry control

## Run

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json
```

Explicit starter execution:

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json \
  --execute-plan \
  --timeout-sec 5
```

Local HTTP worker starter:

```bash
python3 scripts/remote_http_worker.py --host 127.0.0.1 --port 8765
```

In another terminal:

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry_http_local.json \
  --request examples/remote_task_request_http_local.json \
  --output reports/remote_dispatch_http_local.json \
  --execute-plan \
  --timeout-sec 2
```

This path is intentionally small: it proves that an HTTP worker endpoint can
receive a structured task request and return a structured starter response. It
does not provide heartbeat, auth, retry execution against fallback workers, or a
long-lived production worker process.

Expected output:

```json
{
  "schema_version": "inferedge-remote-dispatch-result-v1",
  "dispatch_status": "accepted",
  "selected_worker_id": "jetson-nano-01",
  "remote_execution": {
    "mode": "file_contract_starter",
    "production_remote_execution": false,
    "execution_requested": false
  }
}
```

## Output Contract

The result preserves:

- dispatch status
- selected worker id
- decision reason
- original task request
- worker health snapshot
- runtime event showing selected or rejected dispatch
- worker selection evidence with eligible/rejected worker reasons
- retry/fallback plan with primary and fallback worker ids
- remote execution plan in `plan_only` mode
- remote execution result showing skipped/succeeded/failed starter execution

This output is intended to become an input to AIGuard and Lab reports once the
remote execution path grows beyond the starter contract.

The starter intentionally records execution planning without opening network
connections by default. If a selected worker declares `endpoint_type` such as
`ssh_command` or `http_request`, the output records the planned transport as
`ssh` or `http`, but `network_execution_performed` remains `false` until
`--execute-plan` is explicitly enabled.

When execution is requested:

- `http_request` posts the task request to `metadata.endpoint_url`.
- `ssh_command` runs `metadata.ssh_command` on `metadata.ssh_host`.
- `scripts/remote_http_worker.py` provides a local HTTP starter endpoint for
  repeatable success-path smoke validation.
- timeout, connection failure, HTTP error, and command failure are recorded in
  `remote_execution_result` instead of raising an unstructured crash.
- if the primary starter fails and the retry policy allows fallback,
  `fallback_execution_result` records the attempted fallback worker, status,
  transport, and final starter outcome.
- fallback execution remains bounded to starter evidence. Production-grade
  retry, heartbeat, failover state, and worker lifecycle management remain
  future hardening.

A small curated sample of this recovery path is available at
[`examples/telemetry/remote_fallback_recovery_sample.json`](../examples/telemetry/remote_fallback_recovery_sample.json).
It records a primary HTTP starter `connection_error`, a successful fallback
starter attempt, the retry/fallback plan fields, and the downstream
`remote_execution_recovered_by_fallback` signal expected by AIGuard/Lab. The
sample is documentation evidence only, not a benchmark or production retry
claim.

## Boundary

Use precise wording:

- Allowed: "file-based remote dispatch starter"
- Allowed: "remote worker selection contract"
- Allowed: "remote execution plan-only starter"
- Allowed: "explicit HTTP/SSH remote execution starter"
- Avoid: "production remote execution"
- Avoid: "distributed scheduler"
- Avoid: "cloud orchestration"
