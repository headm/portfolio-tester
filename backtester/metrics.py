"""Performance statistics.

A note on which series feeds what, because getting this wrong is the classic
backtester bug: everything risk/return related (CAGR, volatility, Sharpe,
drawdown, calendar years) is computed from the *time-weighted return index* --
the growth of one dollar, neutral to deposits. If you computed those from the
raw account balance, a year of large contributions would masquerade as a year of
large returns.

XIRR is the exception and is deliberately money-weighted: it answers "what did
the money I actually put in earn", which is the question that matters when you
are dollar-cost-averaging.
"""

import math

import numpy as np

TRADING_DAYS = 252


def daily_returns(index):
    a = np.asarray(index, dtype=float)
    if a.size < 2:
        return np.array([])
    return a[1:] / a[:-1] - 1.0


def years_between(start_date, end_date):
    """Actual calendar span in years; day-count, not trading days."""
    return max((end_date - start_date).days / 365.25, 1e-9)


def total_return(index):
    if len(index) < 2:
        return 0.0
    return index[-1] / index[0] - 1.0


def cagr(index, start_date, end_date):
    if len(index) < 2 or index[0] <= 0:
        return 0.0
    yrs = years_between(start_date, end_date)
    return (index[-1] / index[0]) ** (1.0 / yrs) - 1.0


def volatility(rets):
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets, ddof=1) * math.sqrt(TRADING_DAYS))


def sharpe(rets, rf_annual=0.0):
    if len(rets) < 2:
        return 0.0
    rf_daily = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    excess = np.asarray(rets) - rf_daily
    sd = np.std(excess, ddof=1)
    if sd == 0:
        return 0.0
    return float(np.mean(excess) / sd * math.sqrt(TRADING_DAYS))


def sortino(rets, rf_annual=0.0):
    if len(rets) < 2:
        return 0.0
    rf_daily = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    excess = np.asarray(rets) - rf_daily
    downside = excess[excess < 0]
    if downside.size == 0:
        return float("inf")
    dd = math.sqrt(float(np.mean(downside ** 2)))
    if dd == 0:
        return 0.0
    return float(np.mean(excess) / dd * math.sqrt(TRADING_DAYS))


def drawdown_series(index):
    a = np.asarray(index, dtype=float)
    peaks = np.maximum.accumulate(a)
    return a / peaks - 1.0


def max_drawdown(index, dates):
    """Worst peak-to-trough decline, with the dates it happened between."""
    dd = drawdown_series(index)
    if dd.size == 0:
        return {"depth": 0.0, "peak": None, "trough": None, "recovered": None}
    i = int(np.argmin(dd))
    depth = float(dd[i])
    peak_i = int(np.argmax(np.asarray(index, dtype=float)[: i + 1])) if i > 0 else 0
    recovered = None
    a = np.asarray(index, dtype=float)
    for j in range(i, a.size):
        if a[j] >= a[peak_i]:
            recovered = dates[j]
            break
    return {
        "depth": depth,
        "peak": dates[peak_i],
        "trough": dates[i],
        "recovered": recovered,
    }


def longest_underwater(index, dates):
    """Longest stretch (in calendar days) spent below a previous high."""
    a = np.asarray(index, dtype=float)
    if a.size == 0:
        return {"days": 0, "from": None, "to": None}
    best = {"days": 0, "from": None, "to": None}
    peak = a[0]
    peak_i = 0
    for i in range(1, a.size):
        if a[i] >= peak:
            span = (dates[i] - dates[peak_i]).days
            if span > best["days"]:
                best = {"days": span, "from": dates[peak_i], "to": dates[i]}
            peak = a[i]
            peak_i = i
    # Still underwater at the end.
    span = (dates[-1] - dates[peak_i]).days
    if a[-1] < peak and span > best["days"]:
        best = {"days": span, "from": dates[peak_i], "to": None}
    return best


def calendar_years(index, dates):
    """Per-calendar-year time-weighted return.

    The first and last years are usually partial; they are marked so the UI can
    say so instead of implying a stub year was a full one.
    """
    if not dates:
        return []
    out = []
    year_start_i = 0
    for i in range(1, len(dates) + 1):
        at_end = i == len(dates)
        if at_end or dates[i].year != dates[i - 1].year:
            y = dates[year_start_i].year
            base = index[year_start_i - 1] if year_start_i > 0 else index[year_start_i]
            ret = index[i - 1] / base - 1.0 if base > 0 else 0.0
            partial = (year_start_i == 0 and dates[0].timetuple().tm_yday > 5) or (
                at_end and dates[-1].timetuple().tm_yday < 360
            )
            out.append({"year": y, "return": float(ret), "partial": bool(partial)})
            year_start_i = i
    return out


def rolling_returns(index, dates, years, stride=5):
    """Annualized return of every overlapping holding period of `years` length.

    This is the antidote to start-date luck. A single backtest reports what one
    arbitrary entry date produced; this reports what every entry date produced,
    which is the number you should actually plan against.

    `stride` thins the returned series for plotting -- rolling returns move
    slowly, so every 5th trading day is visually identical to all of them at a
    fraction of the payload. Summary stats always use the full set.
    """
    if len(dates) < 2:
        return None
    ords = np.array([d.toordinal() for d in dates])
    span = int(round(years * 365.25))

    # For each start, the first bar at least `years` later.
    ends = np.searchsorted(ords, ords + span, side="left")
    ok = ends < len(ords)
    if not ok.any():
        return None

    starts = np.nonzero(ok)[0]
    finish = ends[starts]
    a = np.asarray(index, dtype=float)
    held = (ords[finish] - ords[starts]) / 365.25
    good = (held > 0) & (a[starts] > 0)
    starts, finish, held = starts[good], finish[good], held[good]
    if starts.size == 0:
        return None

    rets = (a[finish] / a[starts]) ** (1.0 / held) - 1.0
    keep = starts[::stride]
    keep_r = rets[::stride]

    return {
        "years": years,
        "count": int(rets.size),
        "best": float(np.max(rets)),
        "worst": float(np.min(rets)),
        "median": float(np.median(rets)),
        "mean": float(np.mean(rets)),
        "pct_negative": float(np.mean(rets < 0)),
        "dates": [dates[i].isoformat() for i in keep],
        "values": [round(float(v), 5) for v in keep_r],
    }


def rolling_windows(index, dates, candidates=(1, 3, 5, 10, 15, 20)):
    """Every window the data is long enough to support."""
    out = []
    for y in candidates:
        r = rolling_returns(index, dates, y)
        if r and r["count"] > 1:
            out.append(r)
    return out


def beta_alpha_corr(rets, bench_rets):
    """Correlation and beta of the portfolio against a benchmark."""
    a = np.asarray(rets, dtype=float)
    b = np.asarray(bench_rets, dtype=float)
    n = min(a.size, b.size)
    if n < 3:
        return {"correlation": None, "beta": None}
    a, b = a[-n:], b[-n:]
    var = np.var(b, ddof=1)
    beta = float(np.cov(a, b, ddof=1)[0][1] / var) if var > 0 else None
    sa, sb = np.std(a, ddof=1), np.std(b, ddof=1)
    corr = float(np.corrcoef(a, b)[0][1]) if sa > 0 and sb > 0 else None
    return {"correlation": corr, "beta": beta}


def xirr(flows, guess=0.1):
    """Money-weighted annualized return.

    flows: [(date, amount)] with deposits negative and the final value positive.
    Newton first, bisection as the fallback -- Newton alone diverges on the kind
    of irregular contribution schedules this app makes easy to create.
    """
    if len(flows) < 2:
        return None
    flows = sorted(flows, key=lambda f: f[0])
    t0 = flows[0][0]
    times = [(d - t0).days / 365.25 for d, _ in flows]
    amounts = [a for _, a in flows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        return None

    def npv(rate):
        if rate <= -0.999999:
            return float("inf")
        return sum(a / (1.0 + rate) ** t for a, t in zip(amounts, times))

    rate = guess
    for _ in range(80):
        f = npv(rate)
        if not math.isfinite(f):
            break
        step = 1e-6
        d = (npv(rate + step) - f) / step
        if d == 0 or not math.isfinite(d):
            break
        nxt = rate - f / d
        if not math.isfinite(nxt) or nxt <= -0.9999:
            break
        if abs(nxt - rate) < 1e-10:
            return float(nxt)
        rate = nxt
    else:
        return float(rate)

    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return float(mid)
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return float((lo + hi) / 2)
