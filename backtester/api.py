"""Request handling shared by the HTTP server -- kept separate so it can be
called directly from tests and scripts without a socket."""

import datetime as dt

import numpy as np

from . import engine, inflation, metrics, store
from .ingest import fred, stockanalysis
from .presets import PRESETS


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def json_safe(obj):
    """numpy scalars and dates are not JSON-serializable on their own."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    raise TypeError(f"not JSON serializable: {type(obj)}")


def resolve_symbols(symbols):
    """Cache every symbol we're about to use. Returns (ok, problems)."""
    problems = {}
    ok = []
    for sym in symbols:
        try:
            stockanalysis.ensure_cached(sym)
            ok.append(sym)
        except stockanalysis.NotFound:
            problems[sym] = "not found"
        except stockanalysis.SourceUnavailable as exc:
            problems[sym] = f"data source unavailable ({exc})"
    return ok, problems


def search(query, limit=10):
    return stockanalysis.search(query, limit)


def symbol_info(symbol):
    stockanalysis.ensure_cached(symbol)
    meta = store.get_meta(symbol)
    if not meta:
        raise ApiError(f"{symbol}: no data", 404)
    return meta


def backtest(payload):
    portfolios = payload.get("portfolios") or []
    if not portfolios:
        raise ApiError("Add at least one portfolio.")

    settings = dict(payload.get("settings") or {})
    benchmark = (payload.get("benchmark") or "").strip().upper() or None

    wanted = set()
    for p in portfolios:
        for sym in (p.get("weights") or {}):
            if float(p["weights"][sym]) != 0:
                wanted.add(sym.strip().upper())
    if benchmark:
        wanted.add(benchmark)
    if not wanted:
        raise ApiError("No holdings with a non-zero weight.")

    _, problems = resolve_symbols(sorted(wanted))
    if problems:
        detail = "; ".join(f"{k}: {v}" for k, v in problems.items())
        raise ApiError(f"Could not load {detail}", 404)

    warnings = []

    # Every portfolio must run over the same window, or comparing final balances
    # is meaningless -- a strategy would look better purely for starting later.
    firsts = {s: store.get_meta(s)["first_date"] for s in wanted}
    common_start = max(firsts.values())
    requested = settings.get("start")
    if requested and str(requested)[:10] > common_start:
        effective_start = str(requested)[:10]
    else:
        effective_start = common_start
        if requested and str(requested)[:10] < common_start:
            latest = max(firsts, key=lambda s: firsts[s])
            warnings.append(
                f"All portfolios start {effective_start}, the earliest date every "
                f"holding has data for ({latest} is the constraint)."
            )
    settings["start"] = effective_start

    results = []
    for spec in portfolios:
        try:
            results.append(engine.run(spec, settings))
        except engine.EngineError as exc:
            raise ApiError(f"{spec.get('name') or 'Portfolio'}: {exc}")

    bench = None
    if benchmark:
        bench = engine.run(
            {"name": f"{benchmark} (benchmark)", "weights": {benchmark: 100},
             "rebalance": "none",
             "contribution": portfolios[0].get("contribution")},
            settings,
        )
        for r in results:
            r["stats"].update(metrics.beta_alpha_corr(r["_rets"], bench["_rets"]))
        bench["stats"]["correlation"] = 1.0
        bench["stats"]["beta"] = 1.0

    price_only = sorted({s for r in results for s in r["price_only_symbols"]})
    if price_only:
        warnings.append(
            "Dividends are NOT included for " + ", ".join(price_only) +
            " -- long-run returns for these are understated by roughly 2%/yr."
        )
    for r in results:
        warnings.extend(r["notes"])

    for r in results + ([bench] if bench else []):
        r.pop("_rets", None)
        r.pop("notes", None)
        r.pop("price_only_symbols", None)

    return {
        "portfolios": results,
        "benchmark": bench,
        "warnings": list(dict.fromkeys(warnings)),
        "settings": {**settings, "start": effective_start},
    }


def data_status():
    """What the local vault holds and how current it is."""
    syms = store.list_symbols()
    last = max((s["last_date"] for s in syms if s["last_date"]), default=None)
    stale_days = None
    if last:
        stale_days = (dt.date.today() - dt.date.fromisoformat(last)).days
    cpi_last, cpi_stale = inflation.coverage()
    return {
        "symbols": len(syms),
        "last_price_date": last,
        "days_stale": stale_days,
        # Markets are shut at weekends, so a couple of days behind is normal.
        "stale": stale_days is not None and stale_days > 4,
        "updated_at": max((s["updated_at"] for s in syms), default=None),
        "cpi_last_date": cpi_last,
        "cpi_available": cpi_last is not None,
    }


def refresh(symbols=None):
    """Re-fetch cached price history, plus CPI.

    Deliberately a full re-fetch rather than appending only the new days: a
    dividend-adjusted close is revised backwards every time a dividend is paid,
    so appending would leave the entire history carrying stale adjustment
    factors while looking perfectly up to date.
    """
    targets = [s.strip().upper() for s in symbols] if symbols else [
        s["symbol"] for s in store.list_symbols() if s["source"] == stockanalysis.SOURCE
    ]
    done, failed = [], {}
    for sym in targets:
        try:
            stockanalysis.ensure_cached(sym, refresh=True)
            done.append(sym)
        except stockanalysis.NotFound:
            failed[sym] = "not found"
        except stockanalysis.SourceUnavailable as exc:
            failed[sym] = f"unavailable ({exc})"

    cpi_ok = fred.ensure_cached(refresh=True)
    return {
        "refreshed": done,
        "failed": failed,
        "cpi_refreshed": bool(cpi_ok),
        "status": data_status(),
    }


def presets():
    return PRESETS
