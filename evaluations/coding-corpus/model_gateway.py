#!/usr/bin/env python3
"""Bounded credential-isolating gateway for the local coding corpus.

The candidate can select neither the upstream nor the credential. Production
Compose configuration pins both outside the candidate container; tests may
provide a loopback upstream directly to ``GatewayServer``.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import re
import socket
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8080
HEALTHCHECK_HOST = "127.0.0.1"
UPSTREAM_PATH = "/v1/chat/completions"
ALLOWED_MODEL = "qwen3.6-35b-a3b"
SECRET_FILE = Path("/run/secrets/dgx_api_key")
METRICS_FILE = Path("/tmp/gateway/metrics.json")

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOKENS = 4_096
# This is an admission ceiling paired with the evaluator's ReAct turn_limit=8.
# It is not a claim that one agent turn corresponds to exactly one model call.
MAX_REQUESTS = 8
MAX_TOTAL_TOKENS = 32_000
MAX_CONCURRENCY = 1
CLIENT_READ_TIMEOUT_SECONDS = 10.0
UPSTREAM_CONNECT_TIMEOUT_SECONDS = 5.0
UPSTREAM_READ_TIMEOUT_SECONDS = 185.0

_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_FORBIDDEN_ROUTING_FIELDS = frozenset(
    {
        "api_base",
        "api_key",
        "auth",
        "authorization",
        "base_url",
        "credential",
        "endpoint",
        "host",
        "port",
        "token",
        "upstream",
        "url",
    }
)


class GatewayConfigError(ValueError):
    """The operator-supplied gateway configuration is invalid."""


class RequestRejected(Exception):
    """A candidate request failed the closed gateway contract."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class GatewayResponse:
    status: int
    body: bytes
    usage: dict[str, int]
    upstream_failed: bool = False
    error_code: str | None = None


def validate_upstream_host(raw: str) -> str:
    """Accept a plain IP address or DNS name, never a URL or host:port."""
    if not raw or len(raw) > 253 or raw != raw.strip():
        raise GatewayConfigError("upstream host must be a bounded plain host")
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        pass
    labels = raw.removesuffix(".").split(".")
    if not labels or any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        raise GatewayConfigError("upstream host must be a plain IP address or DNS name")
    return raw


def validate_upstream_port(raw: str) -> int:
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise GatewayConfigError("upstream port must be a decimal integer")
    port = int(raw)
    if not 1 <= port <= 65_535:
        raise GatewayConfigError("upstream port must be from 1 through 65535")
    return port


def read_secret(path: Path) -> str:
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GatewayConfigError("gateway secret file is unavailable") from exc
    if not secret or len(secret) > 4_096 or "\n" in secret or "\r" in secret:
        raise GatewayConfigError("gateway secret file is malformed")
    return secret


def production_upstream(environment: Mapping[str, str]) -> tuple[str, int]:
    try:
        raw_host = environment["MODEL_GATEWAY_UPSTREAM_HOST"]
        raw_port = environment["MODEL_GATEWAY_UPSTREAM_PORT"]
    except KeyError as exc:
        raise GatewayConfigError("gateway upstream is not configured") from exc
    return validate_upstream_host(raw_host), validate_upstream_port(raw_port)


class GatewayMetrics:
    """Small bounded observation projection; never stores prompts or credentials."""

    def __init__(
        self,
        path: Path,
        max_requests: int = MAX_REQUESTS,
        max_total_tokens: int = MAX_TOTAL_TOKENS,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if max_total_tokens < 1:
            raise ValueError("max_total_tokens must be positive")
        self.path = path
        self.max_requests = max_requests
        self.max_total_tokens = max_total_tokens
        self._lock = threading.Lock()
        self._data: dict[str, object] = {
            "schema_version": "model-gateway-metrics/v1",
            "requests_seen": 0,
            "requests_admitted": 0,
            "requests_completed": 0,
            "requests_rejected": 0,
            "requests_in_flight": 0,
            "peak_concurrency": 0,
            "upstream_requests": 0,
            "upstream_failures": 0,
            "request_bytes": 0,
            "response_bytes": 0,
            "status_counts": {},
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "token_budget_overshoot": 0,
            "last_error_code": None,
            "limits": {
                "max_body_bytes": MAX_BODY_BYTES,
                "max_response_bytes": MAX_RESPONSE_BYTES,
                "max_tokens_per_request": MAX_TOKENS,
                "max_requests": max_requests,
                "request_budget_basis": "react_turn_limit_ceiling_not_call_equivalence",
                "max_total_tokens": max_total_tokens,
                "max_concurrency": MAX_CONCURRENCY,
            },
        }
        with self._lock:
            self._persist_locked()

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        encoded = json.dumps(
            self._data, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.write("\n")
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        os.replace(temporary, self.path)

    def _increment_status_locked(self, status: int) -> None:
        statuses = self._data["status_counts"]
        assert isinstance(statuses, dict)
        key = str(status)
        statuses[key] = int(statuses.get(key, 0)) + 1

    def reject_method(self, status: int, code: str) -> None:
        with self._lock:
            self._data["requests_seen"] = int(self._data["requests_seen"]) + 1
            self._data["requests_rejected"] = int(self._data["requests_rejected"]) + 1
            self._data["last_error_code"] = code
            self._increment_status_locked(status)
            self._persist_locked()

    def admit(self) -> tuple[bool, str | None]:
        with self._lock:
            seen = int(self._data["requests_seen"]) + 1
            self._data["requests_seen"] = seen
            totals = self._data["usage"]
            assert isinstance(totals, dict)
            if int(totals["total_tokens"]) >= self.max_total_tokens:
                self._data["requests_rejected"] = int(self._data["requests_rejected"]) + 1
                self._data["last_error_code"] = "total_token_budget_exhausted"
                self._increment_status_locked(429)
                self._persist_locked()
                return False, "total_token_budget_exhausted"
            if seen > self.max_requests:
                self._data["requests_rejected"] = int(self._data["requests_rejected"]) + 1
                self._data["last_error_code"] = "request_budget_exhausted"
                self._increment_status_locked(429)
                self._persist_locked()
                return False, "request_budget_exhausted"
            in_flight = int(self._data["requests_in_flight"])
            if in_flight >= MAX_CONCURRENCY:
                self._data["requests_rejected"] = int(self._data["requests_rejected"]) + 1
                self._data["last_error_code"] = "concurrency_limit"
                self._increment_status_locked(429)
                self._persist_locked()
                return False, "concurrency_limit"
            in_flight += 1
            self._data["requests_in_flight"] = in_flight
            self._data["requests_admitted"] = int(self._data["requests_admitted"]) + 1
            self._data["peak_concurrency"] = max(
                int(self._data["peak_concurrency"]), in_flight
            )
            self._persist_locked()
            return True, None

    def would_cross_total_token_budget(self, usage: Mapping[str, int]) -> bool:
        value = usage.get("total_tokens")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return True
        with self._lock:
            totals = self._data["usage"]
            assert isinstance(totals, dict)
            return int(totals["total_tokens"]) + value > self.max_total_tokens

    def finish(
        self,
        *,
        status: int,
        rejected: bool,
        upstream_started: bool,
        upstream_failed: bool,
        request_bytes: int,
        response_bytes: int,
        usage: Mapping[str, int],
        error_code: str | None,
    ) -> None:
        with self._lock:
            in_flight = int(self._data["requests_in_flight"])
            if in_flight < 1:
                raise RuntimeError("gateway metrics lost an admitted request")
            self._data["requests_in_flight"] = in_flight - 1
            self._data["requests_completed"] = int(self._data["requests_completed"]) + 1
            if rejected:
                self._data["requests_rejected"] = int(self._data["requests_rejected"]) + 1
            if upstream_started:
                self._data["upstream_requests"] = int(self._data["upstream_requests"]) + 1
            if upstream_failed:
                self._data["upstream_failures"] = int(self._data["upstream_failures"]) + 1
            self._data["request_bytes"] = int(self._data["request_bytes"]) + request_bytes
            self._data["response_bytes"] = int(self._data["response_bytes"]) + response_bytes
            totals = self._data["usage"]
            assert isinstance(totals, dict)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key, 0)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    totals[key] = int(totals[key]) + value
            self._data["token_budget_overshoot"] = max(
                0, int(totals["total_tokens"]) - self.max_total_tokens
            )
            self._data["last_error_code"] = error_code
            self._increment_status_locked(status)
            self._persist_locked()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return json.loads(json.dumps(self._data))


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        secret: str,
        metrics: GatewayMetrics,
        upstream_host: str,
        upstream_port: int,
        max_body_bytes: int = MAX_BODY_BYTES,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_tokens: int = MAX_TOKENS,
        client_read_timeout: float = CLIENT_READ_TIMEOUT_SECONDS,
        upstream_connect_timeout: float = UPSTREAM_CONNECT_TIMEOUT_SECONDS,
        upstream_read_timeout: float = UPSTREAM_READ_TIMEOUT_SECONDS,
    ) -> None:
        self.secret = secret
        self.metrics = metrics
        self.upstream_host = validate_upstream_host(upstream_host)
        if not 1 <= upstream_port <= 65_535:
            raise GatewayConfigError("upstream port must be from 1 through 65535")
        self.upstream_port = upstream_port
        self.max_body_bytes = max_body_bytes
        self.max_response_bytes = max_response_bytes
        self.max_tokens = max_tokens
        self.client_read_timeout = client_read_timeout
        self.upstream_connect_timeout = upstream_connect_timeout
        self.upstream_read_timeout = upstream_read_timeout
        super().__init__(server_address, GatewayHandler)

    def handle_error(self, request: object, client_address: object) -> None:
        del request, client_address
        # Candidate-controlled input must not cause headers or bodies to be logged.


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "flrh-model-gateway/1"
    sys_version = ""

    @property
    def gateway(self) -> GatewayServer:
        assert isinstance(self.server, GatewayServer)
        return self.server

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.gateway.client_read_timeout)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send_json_bytes(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass

    def _problem_body(self, code: str) -> bytes:
        return json.dumps(
            {"error": {"type": "gateway_rejection", "code": code}},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _reject_unadmitted(self, status: int, code: str) -> None:
        self.gateway.metrics.reject_method(status, code)
        self._send_json_bytes(status, self._problem_body(code))

    def _reject_admitted(
        self, status: int, code: str, *, request_bytes: int = 0
    ) -> None:
        body = self._problem_body(code)
        self.gateway.metrics.finish(
            status=status,
            rejected=True,
            upstream_started=False,
            upstream_failed=False,
            request_bytes=request_bytes,
            response_bytes=len(body),
            usage={},
            error_code=code,
        )
        self._send_json_bytes(status, body)

    def _read_validated_payload(self) -> tuple[bytes, int]:
        if self.path != UPSTREAM_PATH:
            raise RequestRejected(404, "path_not_allowed")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestRejected(415, "content_type_not_allowed")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestRejected(411, "content_length_required")
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise RequestRejected(400, "content_length_invalid")
        length = int(raw_length)
        if length < 1:
            raise RequestRejected(400, "body_empty")
        if length > self.gateway.max_body_bytes:
            raise RequestRejected(413, "body_too_large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestRejected(400, "body_incomplete")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestRejected(400, "body_not_json") from exc
        if not isinstance(payload, dict):
            raise RequestRejected(400, "body_not_object")
        if _FORBIDDEN_ROUTING_FIELDS.intersection(payload):
            raise RequestRejected(400, "routing_field_not_allowed")
        if payload.get("model") != ALLOWED_MODEL:
            raise RequestRejected(400, "model_not_allowed")
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise RequestRejected(400, "messages_invalid")
        if payload.get("stream", False) is not False:
            raise RequestRejected(400, "stream_not_allowed")
        payload["stream"] = False
        if "temperature" in payload:
            temperature = payload["temperature"]
            if (
                not isinstance(temperature, (int, float))
                or isinstance(temperature, bool)
                or temperature != 0
            ):
                raise RequestRejected(400, "temperature_not_allowed")
        payload["temperature"] = 0
        token_fields = [
            key for key in ("max_tokens", "max_completion_tokens") if key in payload
        ]
        if len(token_fields) > 1:
            raise RequestRejected(400, "max_tokens_ambiguous")
        if token_fields:
            value = payload[token_fields[0]]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= self.gateway.max_tokens
            ):
                raise RequestRejected(400, "max_tokens_invalid")
        else:
            payload["max_tokens"] = self.gateway.max_tokens
        if "n" in payload and (
            not isinstance(payload["n"], int)
            or isinstance(payload["n"], bool)
            or payload["n"] != 1
        ):
            raise RequestRejected(400, "choice_count_invalid")
        payload["n"] = 1
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        return encoded, length

    def _forward(self, body: bytes) -> GatewayResponse:
        connection = http.client.HTTPConnection(
            self.gateway.upstream_host,
            self.gateway.upstream_port,
            timeout=self.gateway.upstream_connect_timeout,
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise OSError("upstream socket unavailable")
            connection.sock.settimeout(self.gateway.upstream_read_timeout)
            connection.request(
                "POST",
                UPSTREAM_PATH,
                body=body,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.gateway.secret}",
                    "Content-Type": "application/json",
                    "User-Agent": "flrh-model-gateway/1",
                },
            )
            response = connection.getresponse()
            response_body = response.read(self.gateway.max_response_bytes + 1)
        except socket.timeout:
            return GatewayResponse(
                504,
                self._problem_body("upstream_timeout"),
                {},
                upstream_failed=True,
                error_code="upstream_timeout",
            )
        except (OSError, http.client.HTTPException):
            return GatewayResponse(
                502,
                self._problem_body("upstream_unavailable"),
                {},
                upstream_failed=True,
                error_code="upstream_unavailable",
            )
        finally:
            connection.close()
        if len(response_body) > self.gateway.max_response_bytes:
            return GatewayResponse(
                502,
                self._problem_body("upstream_response_too_large"),
                {},
                upstream_failed=True,
                error_code="upstream_response_too_large",
            )
        if not 200 <= response.status < 300:
            return GatewayResponse(
                502,
                self._problem_body("upstream_rejected"),
                {},
                upstream_failed=True,
                error_code="upstream_rejected",
            )
        if self.gateway.secret.encode("utf-8") in response_body:
            return GatewayResponse(
                502,
                self._problem_body("upstream_secret_reflection"),
                {},
                upstream_failed=True,
                error_code="upstream_secret_reflection",
            )
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return GatewayResponse(
                502,
                self._problem_body("upstream_response_not_json"),
                {},
                upstream_failed=True,
                error_code="upstream_response_not_json",
            )
        usage: dict[str, int] = {}
        if isinstance(decoded, dict) and isinstance(decoded.get("usage"), dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = decoded["usage"].get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] = value
        return GatewayResponse(200, response_body, usage)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        admitted, reason = self.gateway.metrics.admit()
        if not admitted:
            self._send_json_bytes(429, self._problem_body(reason or "request_rejected"))
            return
        try:
            payload, request_bytes = self._read_validated_payload()
        except RequestRejected as exc:
            self._reject_admitted(exc.status, exc.code)
            return
        except socket.timeout:
            self._reject_admitted(408, "client_body_timeout")
            return
        except (ConnectionError, OSError):
            self._reject_admitted(400, "client_body_unavailable")
            return
        response = self._forward(payload)
        rejected = False
        if response.status == 200:
            total_tokens = response.usage.get("total_tokens")
            if (
                not isinstance(total_tokens, int)
                or isinstance(total_tokens, bool)
                or total_tokens < 0
            ):
                response = GatewayResponse(
                    502,
                    self._problem_body("upstream_usage_invalid"),
                    response.usage,
                    upstream_failed=True,
                    error_code="upstream_usage_invalid",
                )
            elif self.gateway.metrics.would_cross_total_token_budget(response.usage):
                response = GatewayResponse(
                    429,
                    self._problem_body("total_token_budget_exhausted"),
                    response.usage,
                    error_code="total_token_budget_exhausted",
                )
                rejected = True
        self.gateway.metrics.finish(
            status=response.status,
            rejected=rejected,
            upstream_started=True,
            upstream_failed=response.upstream_failed,
            request_bytes=request_bytes,
            response_bytes=len(response.body),
            usage=response.usage,
            error_code=response.error_code,
        )
        self._send_json_bytes(response.status, response.body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._reject_unadmitted(405, "method_not_allowed")

    do_CONNECT = do_GET
    do_DELETE = do_GET
    do_HEAD = do_GET
    do_OPTIONS = do_GET
    do_PATCH = do_GET
    do_PUT = do_GET
    do_TRACE = do_GET


def serve() -> int:
    upstream_host, upstream_port = production_upstream(os.environ)
    secret = read_secret(SECRET_FILE)
    metrics = GatewayMetrics(METRICS_FILE)
    server = GatewayServer(
        (LISTEN_HOST, LISTEN_PORT),
        secret=secret,
        metrics=metrics,
        upstream_host=upstream_host,
        upstream_port=upstream_port,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def healthcheck() -> int:
    try:
        with socket.create_connection((HEALTHCHECK_HOST, LISTEN_PORT), timeout=1.0):
            return 0
    except OSError:
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bounded local-model gateway")
    parser.add_argument("command", choices=("serve", "healthcheck"))
    args = parser.parse_args(argv)
    if args.command == "healthcheck":
        return healthcheck()
    os.umask(0o077)
    try:
        return serve()
    except GatewayConfigError as exc:
        print(f"model gateway refused to start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
