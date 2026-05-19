# Remote Dispatch Starter

Language: English | [한국어](remote_dispatch_starter.ko.md)

InferEdgeOrchestrator includes a small file-based remote dispatch starter for
the Runtime Operation Platform roadmap. It is designed to prove the handoff
contract for remote edge workers without claiming production remote execution.

## Scope

This starter answers one narrow question:

> Given a remote worker registry and a task request, which edge worker should
> receive the task, and why?

It does not open network sockets, run SSH commands, manage Cloudflare tunnels,
or keep long-lived production workers alive. Those remain future hardening
steps.

## Inputs

Worker registry:

- schema: `inferedge-remote-worker-registry-v1`
- example: [`examples/remote_worker_registry.json`](../examples/remote_worker_registry.json)

Task request:

- schema: `inferedge-remote-task-request-v1`
- example: [`examples/remote_task_request.json`](../examples/remote_task_request.json)

The starter matches:

- worker online/offline status
- health state: `healthy` or `constrained`
- required backend or worker type
- target device

## Run

```bash
python3 -m inferedge_orchestrator remote-dispatch \
  --registry examples/remote_worker_registry.json \
  --request examples/remote_task_request.json \
  --output reports/remote_dispatch_result.json
```

Expected output:

```json
{
  "schema_version": "inferedge-remote-dispatch-result-v1",
  "dispatch_status": "accepted",
  "selected_worker_id": "jetson-nano-01",
  "remote_execution": {
    "mode": "file_contract_starter",
    "production_remote_execution": false
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

This output is intended to become an input to AIGuard and Lab reports once the
remote execution path grows beyond the starter contract.

## Boundary

Use precise wording:

- Allowed: "file-based remote dispatch starter"
- Allowed: "remote worker selection contract"
- Avoid: "production remote execution"
- Avoid: "distributed scheduler"
- Avoid: "cloud orchestration"
