#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


RESPONSE_SCHEMA_VERSION = "inferedge-remote-http-worker-response-v1"


def make_handler(worker_id: str) -> type[BaseHTTPRequestHandler]:
    class RemoteHttpWorkerHandler(BaseHTTPRequestHandler):
        server_version = "InferEdgeRemoteHttpWorker/0.1"

        def do_GET(self) -> None:
            if self.path != "/health":
                self._write_json(
                    404,
                    {
                        "schema_version": RESPONSE_SCHEMA_VERSION,
                        "status": "not_found",
                        "worker_id": worker_id,
                    },
                )
                return
            self._write_json(
                200,
                {
                    "schema_version": RESPONSE_SCHEMA_VERSION,
                    "status": "healthy",
                    "worker_id": worker_id,
                    "production_remote_execution": False,
                },
            )

        def do_POST(self) -> None:
            if self.path not in {"/", "/execute"}:
                self._write_json(
                    404,
                    {
                        "schema_version": RESPONSE_SCHEMA_VERSION,
                        "status": "not_found",
                        "worker_id": worker_id,
                    },
                )
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            raw_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw_body) if raw_body else {}
            except json.JSONDecodeError as exc:
                self._write_json(
                    400,
                    {
                        "schema_version": RESPONSE_SCHEMA_VERSION,
                        "status": "invalid_json",
                        "worker_id": worker_id,
                        "error": str(exc),
                    },
                )
                return

            task_request = payload.get("task_request", {})
            if not isinstance(task_request, dict):
                self._write_json(
                    400,
                    {
                        "schema_version": RESPONSE_SCHEMA_VERSION,
                        "status": "invalid_task_request",
                        "worker_id": worker_id,
                    },
                )
                return

            self._write_json(
                200,
                {
                    "schema_version": RESPONSE_SCHEMA_VERSION,
                    "status": "accepted",
                    "execution_status": "simulated_completed",
                    "worker_id": payload.get("worker_id", worker_id),
                    "task_id": task_request.get("task_id"),
                    "agent_id": task_request.get("agent_id"),
                    "required_backend": task_request.get("required_backend"),
                    "device_target": task_request.get("device_target"),
                    "production_remote_execution": False,
                    "note": (
                        "Local HTTP remote worker starter response only; not a "
                        "long-lived production worker."
                    ),
                },
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RemoteHttpWorkerHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a local HTTP remote worker starter for InferEdgeOrchestrator."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker-id", default="local-http-worker")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.worker_id))
    print(f"remote_http_worker listening on http://{args.host}:{args.port}/execute")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
