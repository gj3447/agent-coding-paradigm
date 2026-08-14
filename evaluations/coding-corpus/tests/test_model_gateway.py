from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from model_gateway import (  # noqa: E402
    ALLOWED_MODEL,
    GatewayConfigError,
    GatewayMetrics,
    GatewayServer,
    production_upstream,
    validate_upstream_host,
)


class StubUpstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), StubHandler)
        self.records: list[dict[str, object]] = []
        self.entered = threading.Event()
        self.release: threading.Event | None = None
        self.status = 200
        self.body = json.dumps(
            {
                "id": "local-test",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")


class StubHandler(BaseHTTPRequestHandler):
    server: StubUpstream

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.records.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        self.server.entered.set()
        if self.server.release is not None:
            self.server.release.wait(timeout=3)
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def running_server(server: ThreadingHTTPServer) -> Iterator[ThreadingHTTPServer]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def valid_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": ALLOWED_MODEL,
        "messages": [{"role": "user", "content": "fix private bug"}],
        "max_tokens": 128,
        "stream": False,
    }
    payload.update(updates)
    return payload


def post_json(
    port: int,
    payload: dict[str, object] | bytes,
    *,
    path: str = "/v1/chat/completions",
) -> tuple[int, bytes]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Authorization": "Bearer candidate-value",
                "Content-Type": "application/json",
                "X-Upstream-Host": "attacker.invalid:4444",
            },
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class ModelGatewayTests(unittest.TestCase):
    def _gateway(
        self,
        temporary: str,
        upstream: StubUpstream,
        *,
        secret: str = "real-gateway-secret",
        max_requests: int = 8,
        max_total_tokens: int = 32_000,
        max_body_bytes: int = 2 * 1024 * 1024,
        client_read_timeout: float = 1.0,
        upstream_read_timeout: float = 1.0,
    ) -> tuple[GatewayServer, Path]:
        metrics_path = Path(temporary) / "metrics.json"
        metrics = GatewayMetrics(
            metrics_path,
            max_requests=max_requests,
            max_total_tokens=max_total_tokens,
        )
        gateway = GatewayServer(
            ("127.0.0.1", 0),
            secret=secret,
            metrics=metrics,
            upstream_host="127.0.0.1",
            upstream_port=upstream.server_port,
            max_body_bytes=max_body_bytes,
            client_read_timeout=client_read_timeout,
            upstream_connect_timeout=1.0,
            upstream_read_timeout=upstream_read_timeout,
        )
        return gateway, metrics_path

    def test_forwards_only_fixed_contract_and_rewrites_authorization(self) -> None:
        secret = "real-gateway-secret"
        upstream = StubUpstream()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, metrics_path = self._gateway(temporary, upstream, secret=secret)
            with running_server(upstream), running_server(gateway):
                status, body = post_json(gateway.server_port, valid_payload())

            self.assertEqual(200, status)
            self.assertEqual("ok", json.loads(body)["choices"][0]["message"]["content"])
            self.assertEqual(1, len(upstream.records))
            record = upstream.records[0]
            self.assertEqual("/v1/chat/completions", record["path"])
            headers = record["headers"]
            self.assertIsInstance(headers, dict)
            self.assertEqual(f"Bearer {secret}", headers["authorization"])
            self.assertNotIn("x-upstream-host", headers)
            forwarded = json.loads(record["body"])
            self.assertEqual(ALLOWED_MODEL, forwarded["model"])
            self.assertIs(False, forwarded["stream"])
            self.assertEqual(0, forwarded["temperature"])
            self.assertEqual(1, forwarded["n"])

            serialized_metrics = metrics_path.read_text(encoding="utf-8")
            metrics = json.loads(serialized_metrics)
            self.assertEqual(1, metrics["upstream_requests"])
            self.assertEqual(18, metrics["usage"]["total_tokens"])
            self.assertNotIn(secret, serialized_metrics)
            self.assertNotIn("candidate-value", serialized_metrics)
            self.assertNotIn("fix private bug", serialized_metrics)

    def test_invalid_surface_fails_before_upstream(self) -> None:
        cases = (
            ("/v1/models", valid_payload(), 404),
            ("/v1/chat/completions", valid_payload(model="other"), 400),
            ("/v1/chat/completions", valid_payload(stream=True), 400),
            ("/v1/chat/completions", valid_payload(temperature=0.1), 400),
            ("/v1/chat/completions", valid_payload(max_tokens=4_097), 400),
            ("/v1/chat/completions", valid_payload(n=2), 400),
            (
                "/v1/chat/completions",
                valid_payload(base_url="http://attacker.invalid"),
                400,
            ),
        )
        for path, payload, expected in cases:
            with self.subTest(path=path, payload=payload):
                upstream = StubUpstream()
                with tempfile.TemporaryDirectory() as temporary:
                    gateway, _ = self._gateway(temporary, upstream)
                    with running_server(upstream), running_server(gateway):
                        status, _ = post_json(gateway.server_port, payload, path=path)
                self.assertEqual(expected, status)
                self.assertEqual([], upstream.records)

        upstream = StubUpstream()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, _ = self._gateway(temporary, upstream, max_body_bytes=64)
            with running_server(upstream), running_server(gateway):
                status, _ = post_json(gateway.server_port, b"x" * 65)
        self.assertEqual(413, status)
        self.assertEqual([], upstream.records)

    def test_request_and_concurrency_budgets_fail_closed(self) -> None:
        upstream = StubUpstream()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, _ = self._gateway(temporary, upstream, max_requests=1)
            with running_server(upstream), running_server(gateway):
                first_status, _ = post_json(gateway.server_port, valid_payload())
                second_status, _ = post_json(gateway.server_port, valid_payload())
        self.assertEqual(200, first_status)
        self.assertEqual(429, second_status)
        self.assertEqual(1, len(upstream.records))

        blocking_upstream = StubUpstream()
        blocking_upstream.release = threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, _ = self._gateway(temporary, blocking_upstream)
            first: dict[str, int] = {}

            def first_request() -> None:
                first["status"] = post_json(gateway.server_port, valid_payload())[0]

            with running_server(blocking_upstream), running_server(gateway):
                thread = threading.Thread(target=first_request)
                thread.start()
                self.assertTrue(blocking_upstream.entered.wait(timeout=2))
                concurrent_status, _ = post_json(gateway.server_port, valid_payload())
                blocking_upstream.release.set()
                thread.join(timeout=3)
            self.assertEqual(429, concurrent_status)
            self.assertEqual(200, first.get("status"))

    def test_cumulative_token_budget_records_overshoot_and_fails_closed(self) -> None:
        upstream = StubUpstream()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, metrics_path = self._gateway(
                temporary,
                upstream,
                max_total_tokens=20,
            )
            with running_server(upstream), running_server(gateway):
                first_status, _ = post_json(gateway.server_port, valid_payload())
                crossing_status, crossing_body = post_json(
                    gateway.server_port, valid_payload()
                )
                exhausted_status, _ = post_json(gateway.server_port, valid_payload())
            serialized_metrics = metrics_path.read_text(encoding="utf-8")

        self.assertEqual(200, first_status)
        self.assertEqual(429, crossing_status)
        self.assertIn(b"total_token_budget_exhausted", crossing_body)
        self.assertEqual(429, exhausted_status)
        self.assertEqual(2, len(upstream.records))
        metrics = json.loads(serialized_metrics)
        self.assertEqual(36, metrics["usage"]["total_tokens"])
        self.assertEqual(16, metrics["token_budget_overshoot"])
        self.assertEqual(20, metrics["limits"]["max_total_tokens"])

    def test_client_body_timeout_releases_the_concurrency_slot(self) -> None:
        upstream = StubUpstream()
        with tempfile.TemporaryDirectory() as temporary:
            gateway, _ = self._gateway(
                temporary,
                upstream,
                client_read_timeout=0.05,
            )
            with running_server(upstream), running_server(gateway):
                connection = socket.create_connection(
                    ("127.0.0.1", gateway.server_port), timeout=2
                )
                try:
                    connection.sendall(
                        b"POST /v1/chat/completions HTTP/1.1\r\n"
                        b"Host: model-gateway\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: 10\r\n\r\n"
                    )
                    timeout_response = connection.recv(4_096)
                finally:
                    connection.close()
                following_status, _ = post_json(
                    gateway.server_port, valid_payload()
                )

        self.assertIn(b" 408 ", timeout_response.split(b"\r\n", 1)[0])
        self.assertEqual(200, following_status)

    def test_secret_reflection_is_not_returned(self) -> None:
        secret = "never-return-this-secret"
        upstream = StubUpstream()
        upstream.body = json.dumps({"value": secret}).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            gateway, _ = self._gateway(temporary, upstream, secret=secret)
            with running_server(upstream), running_server(gateway):
                status, body = post_json(gateway.server_port, valid_payload())
        self.assertEqual(502, status)
        self.assertNotIn(secret.encode("utf-8"), body)

    def test_operator_upstream_is_plain_host_and_numeric_port(self) -> None:
        self.assertEqual(
            ("192.168.0.23", 18_000),
            production_upstream(
                {
                    "MODEL_GATEWAY_UPSTREAM_HOST": "192.168.0.23",
                    "MODEL_GATEWAY_UPSTREAM_PORT": "18000",
                }
            ),
        )
        self.assertEqual("dgx-stub", validate_upstream_host("dgx-stub"))
        for host in ("http://192.168.0.23", "192.168.0.23:18000", " bad", "a/b"):
            with self.subTest(host=host):
                with self.assertRaises(GatewayConfigError):
                    validate_upstream_host(host)
        with self.assertRaises(GatewayConfigError):
            production_upstream(
                {
                    "MODEL_GATEWAY_UPSTREAM_HOST": "192.168.0.23",
                    "MODEL_GATEWAY_UPSTREAM_PORT": "18000/path",
                }
            )


if __name__ == "__main__":
    unittest.main()
