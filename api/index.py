"""Vercel entrypoint.

Vercel's Python runtime scans for a lowercase `handler` (a BaseHTTPRequestHandler
subclass) or an `app`. Ours is `Handler` in backtester/server.py, which is why
the build reported "No python entrypoint found ... (variable: Handler)".

This file is the whole adapter: same request handler, same routes, same static
files as `python3 run.py` serves locally.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester.server import Handler  # noqa: E402

handler = Handler
