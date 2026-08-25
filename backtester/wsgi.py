"""The application, as a WSGI callable.

This is the single implementation of routing and static serving. `run.py`
serves it locally through wsgiref; Vercel serves it through the entrypoint
declared in pyproject.toml. There is no second copy to drift out of sync.

WSGI rather than a BaseHTTPRequestHandler because Vercel's current Python
runtime asks for one entrypoint (`[tool.vercel] entrypoint`), and because it is
the portable interface -- the same object runs under gunicorn, uWSGI or
waitress on any host.
"""

import json
import mimetypes
import traceback
from pathlib import Path
from urllib.parse import parse_qs

from . import api, store

STATIC_ROOT = Path(__file__).resolve().parent.parent / "public"
MAX_BODY = 1 << 20

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _json(start_response, obj, status=200):
    body = json.dumps(obj, default=api.json_safe).encode()
    start_response(f"{status} {'OK' if status == 200 else 'Error'}", [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]


def _static(start_response, rel):
    path = (STATIC_ROOT / rel).resolve()
    # Never serve outside the static root, whatever the request says.
    if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.is_file():
        return _json(start_response, {"error": "Not found"}, 404)
    body = path.read_bytes()
    ctype = MIME.get(path.suffix) or mimetypes.guess_type(str(path))[0] \
        or "application/octet-stream"
    start_response("200 OK", [
        ("Content-Type", ctype),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return {}
    if length <= 0:
        return {}
    if length > MAX_BODY:
        raise api.ApiError("Request too large", 413)
    raw = environ["wsgi.input"].read(length)
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise api.ApiError("Malformed JSON body")


def _route(path, method, environ):
    """Return the JSON body for an /api/ route, or raise ApiError."""
    query = parse_qs(environ.get("QUERY_STRING", ""))

    if path == "/api/status":
        return api.data_status()
    if path == "/api/presets":
        return api.presets()
    if path == "/api/search":
        return api.search(query.get("q", [""])[0])
    if path == "/api/symbols":
        return store.list_symbols()
    if path.startswith("/api/symbol/"):
        return api.symbol_info(path.split("/api/symbol/", 1)[1])
    if path == "/api/backtest" and method == "POST":
        return api.backtest(_read_body(environ))
    if path == "/api/refresh" and method == "POST":
        return api.refresh(_read_body(environ).get("symbols"))
    raise api.ApiError("Not found", 404)


def app(environ, start_response):
    path = environ.get("PATH_INFO") or "/"
    method = environ.get("REQUEST_METHOD", "GET").upper()

    try:
        if path.startswith("/api/"):
            return _json(start_response, _route(path, method, environ))
        # Static. Vercel serves public/ from its CDN, so this normally only
        # runs locally -- but it keeps the app self-contained on any host.
        if path in ("/", "/index.html"):
            return _static(start_response, "index.html")
        return _static(start_response, path.lstrip("/"))
    except api.ApiError as exc:
        return _json(start_response, {"error": str(exc)}, exc.status)
    except Exception as exc:  # noqa: BLE001 - surface it rather than hang the UI
        traceback.print_exc()
        return _json(start_response, {"error": f"{type(exc).__name__}: {exc}"}, 500)


# Some hosts look for `application` rather than `app`.
application = app
