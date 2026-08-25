"""SQLite price vault.

Every read and write of persisted market data goes through this module. It is the
only place that knows about SQL, so swapping in Postgres/Supabase later means
rewriting this file and nothing else.
"""

import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


def _db_path():
    """Where the price vault lives.

    Locally that is data/vault.sqlite next to the code. On a serverless host the
    deployment filesystem is read-only and only the temp directory is writable --
    and that temp directory is per-instance and discarded when the instance is
    recycled, so the vault there is a short-lived scratch copy rather than a
    cache that survives. Set BACKTESTER_DB to point at a durable volume.
    """
    override = os.environ.get("BACKTESTER_DB")
    if override:
        return Path(override)
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path(tempfile.gettempdir()) / "wealthmap" / "vault.sqlite"
    return Path(__file__).resolve().parent.parent / "data" / "vault.sqlite"


DB_PATH = _db_path()

# How a series was adjusted. The engine always reads adj_close; this records what
# that column actually means so the UI can warn when dividends are missing.
TOTAL_RETURN = "total_return"  # dividends reinvested + splits handled
PRICE_ONLY = "price_only"      # splits handled, dividends dropped

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    source      TEXT NOT NULL,
    adjustment  TEXT NOT NULL,
    first_date  TEXT,
    last_date   TEXT,
    updated_at  TEXT NOT NULL
);

-- Non-price reference series (currently just CPI). Kept apart from `prices`
-- so it never shows up as something you could put in a portfolio.
CREATE TABLE IF NOT EXISTS macro (
    series TEXT NOT NULL,
    date   TEXT NOT NULL,
    value  REAL NOT NULL,
    PRIMARY KEY (series, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS macro_meta (
    series     TEXT PRIMARY KEY,
    last_date  TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    symbol    TEXT NOT NULL,
    date      TEXT NOT NULL,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    adj_close REAL NOT NULL,
    volume    REAL,
    PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
"""

_local = threading.local()


def connect():
    """One connection per thread; http.server handles requests on many threads."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        _local.conn = conn
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_series(symbol, rows, name=None, source="unknown", adjustment=TOTAL_RETURN):
    """Upsert price rows.

    rows: iterable of (date, open, high, low, close, adj_close, volume) with date
    as an ISO 'YYYY-MM-DD' string. Idempotent -- re-importing overlapping data
    replaces those days rather than duplicating them.
    """
    symbol = symbol.upper()
    rows = [r for r in rows if r[5] is not None and r[5] > 0]
    if not rows:
        raise ValueError(f"{symbol}: no usable rows (adjusted close missing or <= 0)")

    conn = connect()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(symbol, date, open, high, low, close, adj_close, volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(symbol, r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows],
        )
        span = conn.execute(
            "SELECT MIN(date) lo, MAX(date) hi FROM prices WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.execute(
            "INSERT INTO symbols (symbol, name, source, adjustment, first_date, last_date, updated_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "  name=COALESCE(excluded.name, symbols.name), "
            "  source=excluded.source, adjustment=excluded.adjustment, "
            "  first_date=excluded.first_date, last_date=excluded.last_date, "
            "  updated_at=excluded.updated_at",
            (symbol, name, source, adjustment, span["lo"], span["hi"], _now()),
        )
    return len(rows)


def get_meta(symbol):
    row = connect().execute(
        "SELECT * FROM symbols WHERE symbol=?", (symbol.upper(),)
    ).fetchone()
    return dict(row) if row else None


def has_symbol(symbol):
    return get_meta(symbol) is not None


def list_symbols():
    return [dict(r) for r in connect().execute(
        "SELECT * FROM symbols ORDER BY symbol"
    )]


def get_series(symbol, start=None, end=None):
    """Return ([dates], [adj_close]) ascending by date."""
    sql = "SELECT date, adj_close FROM prices WHERE symbol=?"
    args = [symbol.upper()]
    if start:
        sql += " AND date >= ?"
        args.append(start)
    if end:
        sql += " AND date <= ?"
        args.append(end)
    sql += " ORDER BY date"
    rows = connect().execute(sql, args).fetchall()
    return [r["date"] for r in rows], [r["adj_close"] for r in rows]


def last_date(symbol):
    meta = get_meta(symbol)
    return meta["last_date"] if meta else None


# ---------------------------------------------------------------- macro data

def save_macro(series, rows):
    """rows: iterable of (date_iso, value)."""
    rows = [(d, float(v)) for d, v in rows if v is not None]
    if not rows:
        raise ValueError(f"{series}: no usable observations")
    conn = connect()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO macro (series, date, value) VALUES (?,?,?)",
            [(series, d, v) for d, v in rows],
        )
        conn.execute(
            "INSERT INTO macro_meta (series, last_date, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(series) DO UPDATE SET "
            "  last_date=excluded.last_date, updated_at=excluded.updated_at",
            (series, max(d for d, _ in rows), _now()),
        )
    return len(rows)


def get_macro(series):
    rows = connect().execute(
        "SELECT date, value FROM macro WHERE series=? ORDER BY date", (series,)
    ).fetchall()
    return [r["date"] for r in rows], [r["value"] for r in rows]


def macro_meta(series):
    row = connect().execute(
        "SELECT * FROM macro_meta WHERE series=?", (series,)
    ).fetchone()
    return dict(row) if row else None


def forget(symbol):
    """Drop a cached symbol entirely (used by tests and manual cache repair)."""
    symbol = symbol.upper()
    conn = connect()
    with conn:
        conn.execute("DELETE FROM prices WHERE symbol=?", (symbol,))
        conn.execute("DELETE FROM symbols WHERE symbol=?", (symbol,))
