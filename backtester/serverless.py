"""Base handler for Vercel's file-based function routing.

Each file under api/ becomes its own endpoint at its own path, so nothing has
to rewrite a URL and nothing can mangle one. That removes the entire class of
problem that a catch-all rewrite introduced.

Local development still runs backtester/server.py, which routes the same
endpoints in-process -- the two share backtester/api.py, so behaviour cannot
drift between them.
"""

import json
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import api

MAX_BODY = 1 << 20


class JsonHandler(BaseHTTPRequestHandler):
    """Subclass and implement `respond`."""

    def respond(self, payload, query):
        raise NotImplementedError

    # -- plumbing --------------------------------------------------------
    def _send(self, obj, status=200):
        body = json.dumps(obj, default=api.json_safe).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, payload=None):
        query = parse_qs(urlparse(self.path).query)
        try:
            self._send(self.respond(payload or {}, query))
        except api.ApiError as exc:
            self._send({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001 - surface it, don't hang the UI
            traceback.print_exc()
            self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send({"error": "Request too large"}, 413)
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "Malformed JSON body"}, 400)
        self._dispatch(body)

    def log_message(self, fmt, *args):
        pass
