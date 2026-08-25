import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester import api  # noqa: E402
from backtester.serverless import JsonHandler  # noqa: E402


class handler(JsonHandler):  # noqa: N801
    def respond(self, payload, query):
        return api.backtest(payload)
