"""Local-only HTTP server. Standard library only -- no framework to install."""

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}
MAX_BODY = 1 << 20


class Handler(BaseHTTPRequestHandler):
    server_version = "backtester"

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            print(f"  {self.command} {self.path}")

    # -- helpers ---------------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=api.json_safe).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, status=400):
        self._send_json({"error": message}, status)

    def _send_file(self, rel):
        path = (WEB_ROOT / rel).resolve()
        if not str(path).startswith(str(WEB_ROOT.resolve())) or not path.is_file():
            self._error("Not found", 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        route = url.path
        try:
            if route in ("/", "/index.html"):
                return self._send_file("index.html")
            if route == "/api/status":
                return self._send_json(api.data_status())
            if route == "/api/presets":
                return self._send_json(api.presets())
            if route == "/api/search":
                q = parse_qs(url.query).get("q", [""])[0]
                return self._send_json(api.search(q))
            if route.startswith("/api/symbol/"):
                return self._send_json(api.symbol_info(route.split("/api/symbol/", 1)[1]))
            if route == "/api/symbols":
                from . import store
                return self._send_json(store.list_symbols())
            if not route.startswith("/api/"):
                return self._send_file(route.lstrip("/"))
            self._error("Not found", 404)
        except api.ApiError as exc:
            self._error(str(exc), exc.status)
        except Exception as exc:  # noqa: BLE001 - surface it rather than hang the UI
            traceback.print_exc()
            self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._error("Request too large", 413)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if route == "/api/backtest":
                return self._send_json(api.backtest(payload))
            if route == "/api/refresh":
                return self._send_json(api.refresh(payload.get("symbols")))
            self._error("Not found", 404)
        except json.JSONDecodeError:
            self._error("Malformed JSON body")
        except api.ApiError as exc:
            self._error(str(exc), exc.status)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(f"{type(exc).__name__}: {exc}", 500)


def serve(host="127.0.0.1", port=8777):
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd
