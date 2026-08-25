"""Vercel entrypoint.

Vercel looks for a top-level `handler`, `app`, or `application` in this file.
An alias (`handler = Handler`) was not accepted, so this declares a real class
statement named `handler` -- unambiguous whether the platform inspects the
source or imports the module.

The class is deliberately empty: all behaviour lives in backtester/server.py, so
the deployment serves exactly what `python3 run.py` serves locally.
"""

import sys
from pathlib import Path

# The project root is the parent of api/; the backtester package lives there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester.server import Handler  # noqa: E402


class handler(Handler):  # noqa: N801 - the name is Vercel's contract
    pass
