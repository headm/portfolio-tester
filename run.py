#!/usr/bin/env python3
"""Portfolio backtester.

  python3 run.py                 start the web app
  python3 run.py --port 9000     ... on a different port
  python3 run.py import <path>   load stooq data (fallback source)
"""

import sys
import threading
import webbrowser

from backtester import server


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

    httpd = server.serve(port=port)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Portfolio backtester running at {url}")
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
