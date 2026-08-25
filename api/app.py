"""Vercel entrypoint, named in pyproject.toml as `api.app:app`.

All behaviour lives in backtester/wsgi.py; this only makes it importable at the
path Vercel expects.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester.wsgi import app, application  # noqa: E402,F401
