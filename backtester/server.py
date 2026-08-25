"""Local-only HTTP server. Standard library only -- no framework to install."""

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api, store

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

    def _route(self):
        """The request path, normalised.

        Behind a platform rewrite the path can arrive carrying the rewrite's
        own destination prefix (e.g. /web/app.js when everything is rewritten
        into a static folder). Strip that so one router works both when this is
        run directly and when it is deployed behind a rewrite.
        """
        route = urlparse(self.path).path
        for prefix in ("/web/", "/api/index"):
            if route == prefix.rstrip("/"):
                return "/"
            if prefix.endswith("/") and route.startswith(prefix):
                return route[len(prefix) - 1:]
        return route

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
        route = self._route()
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
                return self._send_json(store.list_symbols())
            if route == "/api/_debug":
                # What the platform actually handed us, for diagnosing routing.
                return self._send_json({
                    "raw_path": self.path,
                    "normalised_route": route,
                    "web_root": str(WEB_ROOT),
                    "web_root_exists": WEB_ROOT.is_dir(),
                    "web_files": sorted(p.name for p in WEB_ROOT.iterdir())[:12]
                                 if WEB_ROOT.is_dir() else [],
                    "db_path": str(store.DB_PATH),
                })
            if not route.startswith("/api/"):
                if (WEB_ROOT / route.lstrip("/")).is_file():
                    return self._send_file(route.lstrip("/"))
                # Unknown non-API path: serve the app shell. A single-page app
                # should not 404 on a path the client router understands.
                return self._send_file("index.html")
            self._error("Not found", 404)
        except api.ApiError as exc:
            self._error(str(exc), exc.status)
        except Exception as exc:  # noqa: BLE001 - surface it rather than hang the UI
            traceback.print_exc()
            self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self):
        route = self._route()
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
