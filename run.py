#!/usr/bin/env python3
"""Wealthmap.

  python3 run.py                 start the web app
  python3 run.py --port 9000     ... on a different port
  python3 run.py import <path>   load stooq data (fallback source)

Serves the same WSGI application that the deployment does, so local and
deployed behaviour cannot diverge.
"""

import sys
import threading
import webbrowser
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from backtester.wsgi import app


class _ThreadingServer(ThreadingMixIn, WSGIServer):
    # The UI fires several requests at once; wsgiref is serial by default.
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            print(f"  {self.command} {self.path}")


def main():
    args = sys.argv[1:]

    if args and args[0] == "import":
        from backtester.ingest import stooq
        if len(args) < 2:
            print("usage: python3 run.py import <path-to-stooq-zip-or-dir>")
            return 1
        return stooq.import_path(args[1], import_all="--all" in args)

    port = 8777
    if "--port" in args:
        port = int(args[args.index("--port") + 1])

    httpd = make_server("127.0.0.1", port, app,
                        server_class=_ThreadingServer,
                        handler_class=_QuietHandler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Wealthmap running at {url}")
    print("  Press Ctrl-C to stop.\n")
    if "--no-browser" not in args:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
