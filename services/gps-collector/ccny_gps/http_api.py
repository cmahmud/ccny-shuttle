"""Local-only GPS status HTTP API. No public deployment or authentication yet."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

from .status import get_status
from .storage import ObservationStore


def respond(path: str, store: ObservationStore) -> tuple[int, dict]:
    """Pure route logic used by the HTTP server and unit tests."""
    # Query strings must not change which data is disclosed.
    if path == "/health":
        return 200, {"ok": True, "service": "ccny-gps-prototype"}
    if path == "/v1/vehicles":
        return 200, get_status(store)
    return 404, {"error": "not_found"}


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8766) -> None:
    # A fresh connection is opened per request; no multi-thread shared SQLite connection.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                code, data = 200, {"ok": True, "service": "ccny-gps-prototype"}
            else:
                with_store = ObservationStore(db_path)
                try:
                    code, data = respond(self.path, with_store)
                finally:
                    with_store.close()
            body = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return  # No logging of raw HTTP requests

    if host != "127.0.0.1" and host != "::1":
        raise ValueError("Prototype status API is restricted to loopback")
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
