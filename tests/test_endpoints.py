"""Endpoint contract tests.

Two things get checked, because both have broken a deployment already:

1. Every file under api/ declares a top-level class literally named `handler`.
   An alias (`handler = Handler`) was rejected by Vercel with "does not export
   a top-level app, application, or handler variable".
2. The local server and the serverless handlers answer the same routes. They
   are separate entrypoints over one shared backtester/api.py, and the failure
   mode if they drift is that the deployed app behaves unlike the local one.

Run: python3 tests/test_endpoints.py
"""

import ast
import importlib.util
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []
# Endpoint -> whether it needs the network to answer.
ENDPOINTS = {"status": False, "presets": False, "search": True,
             "backtest": True, "refresh": True}


def ok(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


def test_handler_is_a_class():
    print("\ntest_handler_is_a_class")
    for name in ENDPOINTS:
        path = ROOT / "api" / f"{name}.py"
        classes = [n.name for n in ast.parse(path.read_text()).body
                   if isinstance(n, ast.ClassDef)]
        ok(f"api/{name}.py declares class handler", "handler" in classes, str(classes))


def test_handlers_import_and_subclass():
    print("\ntest_handlers_import_and_subclass")
    for name in ENDPOINTS:
        spec = importlib.util.spec_from_file_location(f"_ep_{name}", ROOT / "api" / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        ok(f"api/{name}.py handler is a BaseHTTPRequestHandler",
           issubclass(m.handler, BaseHTTPRequestHandler))


def test_local_server_routes_match():
    print("\ntest_local_server_routes_match")
    from backtester import server
    src = (ROOT / "backtester" / "server.py").read_text()
    for name in ENDPOINTS:
        ok(f"local server also routes /api/{name}", f'"/api/{name}"' in src)
    ok("local server serves the same static root as Vercel publishes",
       server.WEB_ROOT.name == "public", str(server.WEB_ROOT))
    ok("static root contains the app shell", (server.WEB_ROOT / "index.html").is_file())


def test_offline_endpoints_answer():
    print("\ntest_offline_endpoints_answer")
    for name, needs_net in ENDPOINTS.items():
        if needs_net:
            continue
        spec = importlib.util.spec_from_file_location(f"_run_{name}", ROOT / "api" / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        inst = m.handler.__new__(m.handler)   # no socket needed for respond()
        inst.path = f"/api/{name}"
        out = inst.respond({}, {})
        ok(f"/api/{name} returns data", out is not None and len(out) > 0)


if __name__ == "__main__":
    test_handler_is_a_class()
    test_handlers_import_and_subclass()
    test_local_server_routes_match()
    test_offline_endpoints_answer()
    print("\n" + ("ALL PASS" if not FAILURES else f"FAILURES: {FAILURES}"))
    sys.exit(1 if FAILURES else 0)
