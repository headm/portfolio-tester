"""Endpoint contract tests.

The deployment has failed three times on entrypoint shape, so these assert the
things that actually broke:

* pyproject.toml names an entrypoint that resolves to a real WSGI callable.
* That callable answers every route the frontend calls.
* Local and deployed serve the same object, so they cannot drift.

Run: python3 tests/test_endpoints.py
"""

import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def ok(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


def call(app, path, method="GET", body=None, query=""):
    """Invoke a WSGI app the way a server would."""
    raw = json.dumps(body or {}).encode() if body is not None else b""
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    chunks = app(environ, start_response)
    return captured["status"], captured["headers"], b"".join(chunks)


def test_entrypoint_resolves():
    print("\ntest_entrypoint_resolves")
    text = (ROOT / "pyproject.toml").read_text()
    ok("pyproject.toml declares [tool.vercel]", "[tool.vercel]" in text)

    line = next((l for l in text.splitlines() if l.strip().startswith("entrypoint")), "")
    target = line.split("=", 1)[1].strip().strip('"').strip("'") if "=" in line else ""
    ok("entrypoint is declared", bool(target), target)

    module_path, _, attr = target.partition(":")
    import importlib
    mod = importlib.import_module(module_path)
    obj = getattr(mod, attr, None)
    ok(f"{target} resolves", obj is not None)
    ok(f"{target} is callable (a WSGI app)", callable(obj))


def test_every_frontend_route_answers():
    print("\ntest_every_frontend_route_answers")
    from backtester.wsgi import app

    # Exactly the calls public/app.js makes.
    status, _, body = call(app, "/api/status")
    ok("GET /api/status", status == 200 and b"last_price_date" in body)

    status, _, body = call(app, "/api/presets")
    ok("GET /api/presets", status == 200 and len(json.loads(body)) > 0)

    status, _, body = call(app, "/api/search", query="q=vanguard+total")
    ok("GET /api/search", status == 200 and isinstance(json.loads(body), list))

    payload = {"settings": {"initial": 10000, "start": "2022-01-01"},
               "portfolios": [{"name": "t", "weights": {"SPY": 100}}]}
    status, _, body = call(app, "/api/backtest", "POST", payload)
    ok("POST /api/backtest", status == 200 and b"portfolios" in body)

    status, _, _ = call(app, "/api/does-not-exist")
    ok("unknown API route returns 404", status == 404)


def test_static_is_served():
    print("\ntest_static_is_served")
    from backtester.wsgi import app, STATIC_ROOT

    ok("static root is public/", STATIC_ROOT.name == "public", str(STATIC_ROOT))
    for path, expect in [("/", "text/html"), ("/app.js", "text/javascript"),
                         ("/style.css", "text/css"),
                         ("/vendor/uPlot.iife.min.js", "text/javascript")]:
        status, headers, body = call(app, path)
        good = status == 200 and expect in headers.get("Content-Type", "") and len(body) > 0
        ok(f"GET {path}", good, f"{status} {headers.get('Content-Type','')}")

    # A styled page depends on CSS arriving as CSS. Serving the app shell with a
    # 200 instead is how the deployment silently lost its stylesheet.
    _, headers, _ = call(app, "/style.css")
    ok("CSS is not served as HTML", "text/html" not in headers.get("Content-Type", ""))

    status, _, _ = call(app, "/../backtester/store.py")
    ok("path traversal is refused", status == 404)


def test_local_and_deployed_share_one_app():
    print("\ntest_local_and_deployed_share_one_app")
    import importlib
    from backtester.wsgi import app as core
    entry = importlib.import_module("api.app")
    ok("api.app:app is the same object run.py serves", entry.app is core)
    run_src = (ROOT / "run.py").read_text()
    ok("run.py serves it too", "from backtester.wsgi import app" in run_src)


if __name__ == "__main__":
    test_entrypoint_resolves()
    test_every_frontend_route_answers()
    test_static_is_served()
    test_local_and_deployed_share_one_app()
    print("\n" + ("ALL PASS" if not FAILURES else f"FAILURES: {FAILURES}"))
    sys.exit(1 if FAILURES else 0)
