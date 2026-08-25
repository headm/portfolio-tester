"""Fallback ingest: load price files you downloaded yourself.

Handles a stooq bulk .zip, an unpacked directory tree, or loose CSV/TXT files.
Stooq data is split-adjusted but NOT dividend-adjusted, so everything imported
here is tagged price_only and the UI warns when a backtest depends on it.
"""

import csv
import io
import zipfile
from pathlib import Path

from .. import store
from . import detect

SOURCE = "stooq-import"
PRICE_SUFFIXES = {".csv", ".txt"}


def _symbol_from_name(filename):
    stem = Path(filename).stem.lower()
    for suffix in (".us", ".uk", ".de", ".pl", ".jp"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.upper()


def parse_rows(text, fallback_symbol):
    mapping, delim = detect.sniff(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    next(reader, None)  # header

    out = []
    symbol = fallback_symbol
    for line in reader:
        if not line or len(line) <= mapping["close"]:
            continue
        try:
            date = detect.parse_date(line[mapping["date"]])
        except ValueError:
            continue
        close = detect.parse_number(line[mapping["close"]])
        if close is None or close <= 0:
            continue
        adj = detect.parse_number(line[mapping["adj_close"]]) if "adj_close" in mapping else None
        if adj is None or adj <= 0:
            adj = close
        g = lambda k: detect.parse_number(line[mapping[k]]) if k in mapping else None
        out.append((date, g("open"), g("high"), g("low"), close, adj, g("volume")))

    has_adj = "adj_close" in mapping
    return out, symbol, has_adj


def _ingest_text(text, filename, verbose=True):
    symbol = _symbol_from_name(filename)
    rows, symbol, has_adj = parse_rows(text, symbol)
    if not rows:
        return 0
    adjustment = store.TOTAL_RETURN if has_adj else store.PRICE_ONLY
    n = store.save_series(symbol, rows, source=SOURCE, adjustment=adjustment)
    if verbose:
        flag = "" if has_adj else "  [price-only: no dividends]"
        print(f"  {symbol:<10} {n:>6} rows  {rows[0][0]} -> {rows[-1][0]}{flag}")
    return n


def import_path(path, import_all=False):
    """Import a zip, directory, or single file. Returns a process exit code."""
    p = Path(path).expanduser()
    if not p.exists():
        print(f"error: {p} does not exist")
        return 1

    total_files = 0
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            members = [
                m for m in zf.namelist()
                if Path(m).suffix.lower() in PRICE_SUFFIXES and not m.endswith("/")
            ]
            if not members:
                print("error: no .csv/.txt price files inside the archive")
                return 1
            print(f"  {len(members)} price files found in {p.name}")
            if not import_all and len(members) > 50:
                print("  Importing the first 50. Re-run with --all to load everything")
                print("  (a full US bundle is ~10k tickers and takes a while).")
                members = sorted(members)[:50]
            for m in members:
                try:
                    text = zf.read(m).decode("utf-8", "replace")
                    total_files += 1 if _ingest_text(text, m) else 0
                except Exception as exc:  # noqa: BLE001
                    print(f"  skipped {m}: {exc}")
    elif p.is_dir():
        files = [f for f in p.rglob("*") if f.suffix.lower() in PRICE_SUFFIXES]
        if not files:
            print(f"error: no .csv/.txt files under {p}")
            return 1
        if not import_all and len(files) > 50:
            print(f"  {len(files)} files found; importing the first 50 (--all for everything)")
            files = sorted(files)[:50]
        for f in files:
            try:
                total_files += 1 if _ingest_text(f.read_text("utf-8", "replace"), f.name) else 0
            except Exception as exc:  # noqa: BLE001
                print(f"  skipped {f.name}: {exc}")
    else:
        total_files += 1 if _ingest_text(p.read_text("utf-8", "replace"), p.name) else 0

    print(f"\n  Imported {total_files} symbols into {store.DB_PATH}")
    return 0
