"""Primary price source: stockanalysis.com's public JSON endpoints.

No API key, full history, and a genuinely dividend-adjusted close (field 'a'),
which is what makes 20-year backtests come out right.

Two things this module is careful about:

1. It always asks for range=Max. The endpoint accepts '20Y'/'30Y' without
   complaint but silently returns only ~250 days, which would quietly cap every
   long backtest at one year. Max is the only range value that means what it says.
2. It is an undocumented internal endpoint, so failures are expected and treated
   as normal: everything is cached on first fetch, so an outage degrades to
   "can't add new tickers" rather than "nothing works".
"""

import time

import requests

from .. import store

BASE = "https://stockanalysis.com/api"
UA = "personal-portfolio-backtester/1.0 (single-user local research tool)"
TIMEOUT = 30
RETRIES = 3
DELAY = 0.4  # polite spacing between sequential fetches

SOURCE = "stockanalysis.com"


class NotFound(Exception):
    pass


class SourceUnavailable(Exception):
    pass


_session = None


def _get(url, params=None):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    last = None
    for attempt in range(RETRIES):
        try:
            resp = _session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last = exc
            time.sleep(DELAY * (attempt + 1))
            continue
        if resp.status_code == 404:
            raise NotFound(url)
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            last = SourceUnavailable("rate limited")
            continue
        if resp.status_code >= 500:
            last = SourceUnavailable(f"HTTP {resp.status_code}")
            time.sleep(DELAY * (attempt + 1))
            continue
        if resp.status_code != 200:
            raise SourceUnavailable(f"HTTP {resp.status_code} for {url}")
        try:
            return resp.json()
        except ValueError:
            # A JS challenge page or HTML error means the endpoint changed shape.
            raise SourceUnavailable(f"non-JSON response from {url}")
    raise SourceUnavailable(str(last))


def fetch_history(symbol):
    """Full daily history. Returns (rows, name) with rows ascending by date."""
    symbol = symbol.strip().upper()
    payload = _get(
        f"{BASE}/symbol/s/{symbol.lower()}/history",
        {"range": "Max", "period": "Daily"},
    )
    if payload.get("status") == 404:
        raise NotFound(symbol)
    data = payload.get("data")
    if not data:
        raise NotFound(symbol)

    rows = []
    for r in data:
        adj = r.get("a")
        close = r.get("c")
        if adj is None:
            adj = close
        if adj is None:
            continue
        rows.append((r["t"], r.get("o"), r.get("h"), r.get("l"), close, adj, r.get("v")))

    rows.sort(key=lambda x: x[0])  # API returns newest-first
    if not rows:
        raise NotFound(symbol)
    return rows, None


def search(query, limit=10):
    """Ticker lookup by name or symbol. Returns [] rather than raising."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        payload = _get(f"{BASE}/search", {"q": query, "limit": limit})
    except (NotFound, SourceUnavailable):
        return []
    out = []
    for item in (payload.get("data") or [])[:limit]:
        out.append({
            "symbol": item.get("s") or item.get("id"),
            "name": item.get("n"),
            "kind": "etf" if item.get("t") == "e" else "stock",
        })
    return out


def ensure_cached(symbol, refresh=False):
    """Fetch and cache a symbol if we don't already have it.

    Returns the store metadata dict. Raises NotFound for bad tickers. If the
    source is down but we already hold the symbol, the cached copy is used.
    """
    symbol = symbol.strip().upper()
    meta = store.get_meta(symbol)
    if meta and not refresh:
        return meta

    try:
        rows, name = fetch_history(symbol)
    except SourceUnavailable:
        if meta:
            return meta  # stale but usable
        raise

    store.save_series(
        symbol, rows, name=name, source=SOURCE, adjustment=store.TOTAL_RETURN
    )
    time.sleep(DELAY)
    return store.get_meta(symbol)
