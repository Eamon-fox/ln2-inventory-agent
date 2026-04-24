"""HTTP lifecycle wrapper for the loopback-only local Open API."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .contracts import LOCAL_OPEN_API_DEFAULT_PORT
from .service import (
    LocalOpenApiRequestError,
    _coerce_int,
    _response_envelope,
)


class _LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class LocalOpenApiService:
    """Lifecycle wrapper around the loopback-only HTTP server."""

    def __init__(self, controller, *, host="127.0.0.1", port=LOCAL_OPEN_API_DEFAULT_PORT):
        self._controller = controller
        self._host = str(host or "127.0.0.1")
        self._requested_port = int(port or LOCAL_OPEN_API_DEFAULT_PORT)
        self._bound_port = 0
        self._server = None
        self._thread = None
        self._lock = threading.Lock()

    @property
    def requested_port(self) -> int:
        return int(self._requested_port or 0)

    @property
    def bound_port(self) -> int:
        return int(self._bound_port or 0)

    def is_running(self) -> bool:
        with self._lock:
            thread = self._thread
            server = self._server
        return bool(server is not None and thread is not None and thread.is_alive())

    def _build_handler(self):
        controller = self._controller

        class _Handler(BaseHTTPRequestHandler):
            server_version = "SnowFoxLocalAPI/1.0"

            def log_message(self, format, *args):  # noqa: A003 - stdlib signature
                return

            def do_GET(self):
                self._handle_request("GET")

            def do_POST(self):
                self._handle_request("POST")

            def _read_payload(self):
                content_length = _coerce_int(
                    self.headers.get("Content-Length"),
                    field_name="Content-Length",
                    default=0,
                    minimum=0,
                )
                if not content_length:
                    return None
                raw = self.rfile.read(content_length)
                if not raw:
                    return None
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    raise LocalOpenApiRequestError(
                        "Request body must be valid JSON.",
                        expected_type="json-object",
                    ) from exc
                if payload is None:
                    return None
                if not isinstance(payload, dict):
                    raise LocalOpenApiRequestError(
                        "Request body must be a JSON object.",
                        expected_type="json-object",
                    )
                return payload

            def _send_json(self, status_code, payload_dict):
                body = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(int(status_code))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle_request(self, method):
                try:
                    parsed = urlsplit(self.path)
                    payload = self._read_payload() if method == "POST" else None
                    status_code, response_payload = controller.handle_request(
                        method,
                        parsed.path,
                        parse_qs(parsed.query, keep_blank_values=True),
                        payload=payload,
                    )
                except LocalOpenApiRequestError as exc:
                    status_code, response_payload = exc.to_response()
                except ValueError as exc:
                    status_code, response_payload = LocalOpenApiRequestError(str(exc)).to_response()
                except Exception as exc:  # pragma: no cover - defensive server guard
                    status_code = 500
                    response_payload = _response_envelope(
                        ok=False,
                        error_code="internal_error",
                        message=str(exc),
                    )
                self._send_json(status_code, response_payload)

        return _Handler

    def start(self, *, port=None):
        desired_port = int(self._requested_port if port is None else port)
        if self.is_running() and desired_port == self.bound_port:
            return {
                "ok": True,
                "running": True,
                "changed": False,
                "port": self.bound_port,
            }
        if self.is_running():
            self.stop()

        server = _LoopbackThreadingHTTPServer((self._host, desired_port), self._build_handler())
        thread = threading.Thread(target=server.serve_forever, name="snowfox-local-open-api", daemon=True)
        with self._lock:
            self._server = server
            self._thread = thread
            self._requested_port = desired_port
            self._bound_port = int(server.server_address[1])
        thread.start()
        return {
            "ok": True,
            "running": True,
            "changed": True,
            "port": self.bound_port,
        }

    def stop(self):
        with self._lock:
            server = self._server
            thread = self._thread
            was_running = bool(server is not None and thread is not None)
            self._server = None
            self._thread = None
            self._bound_port = 0
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        return {
            "ok": True,
            "running": False,
            "changed": was_running,
            "port": 0,
        }

    def configure(self, *, enabled, port):
        desired_port = int(port or LOCAL_OPEN_API_DEFAULT_PORT)
        if not enabled:
            stopped = self.stop()
            stopped["port"] = desired_port
            return stopped
        try:
            return self.start(port=desired_port)
        except Exception as exc:
            return {
                "ok": False,
                "running": False,
                "changed": False,
                "port": desired_port,
                "message": str(exc),
                "error_code": "local_open_api_start_failed",
            }
