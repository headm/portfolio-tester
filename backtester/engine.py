"""Daily portfolio simulation.

Design rules that keep results honest:

* No lookahead. A rebalance triggered on day D executes at day D's close.
* The simulation runs on the intersection of trading days across the portfolio's
  holdings, starting no earlier than the newest holding's inception. When that
  truncates the requested window, the result says so and names the ticker.
* Two series come out: `balance` (real account value, includes deposits) and
  `index` (growth of $1, time-weighted, neutral to deposits). Risk and return
  stats read `index`; XIRR reads the actual cash flows.
"""

import datetime as dt
from collections import OrderedDict

import numpy as np

from . import inflation, metrics, montecarlo, store

REBALANCE_CHOICES = ("none", "monthly", "quarterly", "annual", "threshold")
CADENCE_CHOICES = ("none", "monthly", "quarterly", "annual")


class EngineError(Exception):
    pass


def _to_date(value):
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def load_aligned(symbols, start=None, end=None):
    """Align symbols onto their common trading days.

    Returns (dates, {symbol: np.array(prices)}, notes). Alignment is an
    intersection: a day is only usable if every holding traded that day.
    """
    if not symbols:
        raise EngineError("No holdings given.")

    series = OrderedDict()
    for sym in symbols:
        d, p = store.get_series(sym)
        if not d:
            raise EngineError(f"No price history available for {sym}.")
        series[sym] = dict(zip(d, p))

    common = set.intersection(*(set(s.keys()) for s in series.values()))
    if not common:
        raise EngineError("These holdings share no overlapping trading days.")

    notes = []
    limiter = max(symbols, key=lambda s: min(series[s].keys()))
    natural_start = min(common)

    dates = sorted(common)
    if start:
        start = _to_date(start).isoformat()
        if start < natural_start:
            notes.append(
                f"Start moved to {natural_start} because {limiter} has no data before then."
            )
        dates = [d for d in dates if d >= max(start, natural_start)]
    if end:
        end = _to_date(end).isoformat()
        dates = [d for d in dates if d <= end]

    if len(dates) < 2:
        raise EngineError("Not enough overlapping trading days in that date range.")

    prices = {s: np.array([series[s][d] for d in dates], dtype=float) for s in symbols}
    return [_to_date(d) for d in dates], prices, notes


def _period_key(date, cadence):
    if cadence == "monthly":
        return (date.year, date.month)
    if cadence == "quarterly":
        return (date.year, (date.month - 1) // 3)
    if cadence == "annual":
        return date.year
    return None


def _boundaries(dates, cadence):
    """Indices of the first trading day of each period, excluding index 0."""
    if cadence in (None, "none"):
        return set()
    out = set()
    for i in range(1, len(dates)):
        if _period_key(dates[i], cadence) != _period_key(dates[i - 1], cadence):
            out.add(i)
    return out


def normalize_weights(weights):
    clean = {k.strip().upper(): float(v) for k, v in weights.items() if float(v) != 0}
    if not clean:
        raise EngineError("Portfolio has no holdings with a non-zero weight.")
    if any(v < 0 for v in clean.values()):
        raise EngineError("Negative weights (shorting) are not supported.")
    total = sum(clean.values())
    return {k: v / total for k, v in clean.items()}


def run(spec, settings):
    """Simulate one portfolio.

    spec:     {name, weights{sym:pct}, rebalance, threshold_pct,
               contribution{amount,cadence}, withdrawal{rate_pct,cadence}}
    settings: {start, end, initial, commission, slippage_bps, expense_ratio_pct,
               rf_pct, real}
    """
    weights = normalize_weights(spec.get("weights") or {})
    symbols = list(weights)
    rebalance = spec.get("rebalance", "none")
    if rebalance not in REBALANCE_CHOICES:
        raise EngineError(f"Unknown rebalance mode: {rebalance}")

    contrib = spec.get("contribution") or {}
    contrib_amt = float(contrib.get("amount") or 0)
    contrib_cadence = contrib.get("cadence", "none")
    if contrib_cadence not in CADENCE_CHOICES:
        raise EngineError(f"Unknown contribution cadence: {contrib_cadence}")

    wd = spec.get("withdrawal") or {}
    wd_rate = float(wd.get("rate_pct") or 0) / 100.0
    wd_cadence = wd.get("cadence", "monthly")
    if wd_cadence not in CADENCE_CHOICES:
        raise EngineError(f"Unknown withdrawal cadence: {wd_cadence}")
    if wd_rate < 0:
        raise EngineError("Withdrawal rate cannot be negative.")
    if wd_rate and contrib_amt:
        raise EngineError("A portfolio cannot both contribute and withdraw.")

    initial = float(settings.get("initial", 10000))
    if initial <= 0:
        raise EngineError("Initial investment must be greater than zero.")
    commission = float(settings.get("commission", 0) or 0)
    slippage = float(settings.get("slippage_bps", 0) or 0) / 10000.0
    er_annual = float(settings.get("expense_ratio_pct", 0) or 0) / 100.0
    er_daily = er_annual / metrics.TRADING_DAYS
    threshold = float(spec.get("threshold_pct", 5) or 5) / 100.0

    dates, prices, notes = load_aligned(symbols, settings.get("start"), settings.get("end"))
    n = len(dates)

    # Inflation. `defl` converts nominal dollars at date i into dollars of the
    # start date. It is needed for the withdrawal rule even in nominal mode,
    # because the 4%-rule withdrawal grows with CPI.
    want_real = bool(settings.get("real"))
    defl = inflation.deflator(dates)
    real = want_real and defl is not None
    if want_real and defl is None:
        notes.append("Inflation data unavailable — showing nominal returns.")
    if real:
        # Deflating prices puts the entire simulation in real dollars, so every
        # downstream number (CAGR, drawdown, XIRR) comes out real for free.
        prices = {s: prices[s] * defl for s in symbols}

    shares = {s: 0.0 for s in symbols}
    total_costs = 0.0
    trade_count = 0

    def value_at(i):
        return sum(shares[s] * prices[s][i] for s in symbols)

    def cost_of(notionals):
        """Commission per touched holding plus proportional slippage."""
        c = 0.0
        n = 0
        for amount in notionals:
            if abs(amount) > 1e-9:
                c += commission + abs(amount) * slippage
                n += 1
        return c, n

    def rebalance_to_targets(i, pot):
        """Move the whole portfolio to target weights. Returns the new value."""
        nonlocal total_costs, trade_count
        deltas = [pot * weights[s] - shares[s] * prices[s][i] for s in symbols]
        cost, n = cost_of(deltas)
        net = max(pot - cost, 0.0)
        for s in symbols:
            shares[s] = net * weights[s] / prices[s][i]
        total_costs += cost
        trade_count += n
        return net

    def sell_pro_rata(i, amount, held):
        """Raise `amount` of cash by trimming every holding proportionally.

        Selling pro rata rather than rebalancing keeps a withdrawal from
        secretly doubling as a rebalance on portfolios set to drift.
        """
        nonlocal total_costs, trade_count
        if held <= 0:
            return held
        cost, k = cost_of([amount * (shares[s] * prices[s][i]) / held for s in symbols])
        gross = min(amount + cost, held)
        frac = gross / held
        for s in symbols:
            shares[s] *= (1.0 - frac)
        total_costs += cost
        trade_count += k
        return sum(shares[s] * prices[s][i] for s in symbols)

    def deploy(i, amount, held):
        """Invest new cash at target weights WITHOUT touching existing holdings.

        This is what 'never rebalance' plus contributions has to mean: new money
        goes in at the target mix, and whatever is already there keeps drifting.
        Routing contributions through a full rebalance instead would silently
        turn a drift portfolio into a rebalanced one.
        """
        nonlocal total_costs, trade_count
        cost, n = cost_of([amount * weights[s] for s in symbols])
        net = max(amount - cost, 0.0)
        for s in symbols:
            shares[s] += net * weights[s] / prices[s][i]
        total_costs += cost
        trade_count += n
        return held + net

    # Fractional shares mean the portfolio is always fully invested, so there is
    # no cash balance to track -- costs come straight out of the amount deployed.
    flows = [(dates[0], -initial)]
    contributed = initial

    rebal_days = _boundaries(dates, rebalance) if rebalance != "threshold" else set()
    contrib_days = _boundaries(dates, contrib_cadence) if contrib_amt > 0 else set()
    wd_days = _boundaries(dates, wd_cadence) if wd_rate > 0 else set()

    # The classic safe-withdrawal rule: take `rate` of the STARTING balance in
    # year one, then hold that sum constant in real terms for life. In real mode
    # that is a flat number; in nominal mode it grows with CPI.
    per_year = {"monthly": 12, "quarterly": 4, "annual": 1}.get(wd_cadence, 12)
    wd_base = initial * wd_rate / per_year
    if wd_rate and not real and defl is None:
        notes.append(
            "Inflation data unavailable — withdrawals held flat in nominal dollars."
        )

    def withdrawal_at(i):
        if real or defl is None:
            return wd_base
        return wd_base / defl[i]

    withdrawn = 0.0
    depleted_on = None

    balance = np.empty(n)
    index = np.empty(n)
    balance[0] = rebalance_to_targets(0, initial)
    index[0] = 1.0

    for i in range(1, n):
        # Mark to market, then bleed the expense ratio.
        if er_daily:
            for s in symbols:
                shares[s] *= (1.0 - er_daily)

        held = value_at(i)
        prev = balance[i - 1]

        inflow = 0.0
        if i in contrib_days:
            inflow = contrib_amt * (defl[i] if real and defl is not None else 1.0)
            contributed += inflow
            flows.append((dates[i], -inflow))

        outflow = 0.0
        if i in wd_days and held > 0:
            outflow = min(withdrawal_at(i), held)
            withdrawn += outflow
            flows.append((dates[i], outflow))
            if outflow > 0:
                sold = sell_pro_rata(i, outflow, held)
                held = sold
            if held <= 1e-6 and depleted_on is None:
                depleted_on = dates[i]

        value = held + inflow

        do_rebalance = i in rebal_days
        if rebalance == "threshold" and value > 0:
            drift = max(
                abs((shares[s] * prices[s][i]) / value - weights[s]) for s in symbols
            )
            do_rebalance = drift > threshold

        if do_rebalance:
            value = rebalance_to_targets(i, value)
        elif inflow > 0:
            value = deploy(i, inflow, held)

        balance[i] = value
        # Time-weighted: strip external cash movement out before measuring the
        # day's return, so neither deposits nor withdrawals distort it.
        if prev > 0:
            index[i] = index[i - 1] * ((value - inflow + outflow) / prev)
        else:
            index[i] = index[i - 1]

    flows.append((dates[-1], float(balance[-1])))

    rets = metrics.daily_returns(index)
    rf = float(settings.get("rf_pct", 0) or 0) / 100.0
    dd = metrics.max_drawdown(index, dates)

    adjustments = {s: (store.get_meta(s) or {}).get("adjustment") for s in symbols}
    price_only = [s for s, a in adjustments.items() if a == store.PRICE_ONLY]

    stats = {
        "final_balance": float(balance[-1]),
        "contributed": float(contributed),
        "profit": float(balance[-1] - contributed),
        "total_return": metrics.total_return(index),
        "cagr": metrics.cagr(index, dates[0], dates[-1]),
        "volatility": metrics.volatility(rets),
        "sharpe": metrics.sharpe(rets, rf),
        "sortino": metrics.sortino(rets, rf),
        "max_drawdown": dd["depth"],
        "drawdown_peak": dd["peak"].isoformat() if dd["peak"] else None,
        "drawdown_trough": dd["trough"].isoformat() if dd["trough"] else None,
        "drawdown_recovered": dd["recovered"].isoformat() if dd["recovered"] else None,
        "longest_underwater_days": metrics.longest_underwater(index, dates)["days"],
        "costs_paid": float(total_costs),
        "trades": trade_count,
        "years": metrics.years_between(dates[0], dates[-1]),
    }

    # Forward projection, only when explicitly asked for -- it is speculative and
    # should never appear as a side effect of running a backtest.
    projection = None
    project_years = float(settings.get("project_years") or 0)
    if project_years > 0 and rets.size >= metrics.TRADING_DAYS:
        cadence = wd_cadence if wd_rate > 0 else contrib_cadence
        projection = montecarlo.project(
            rets,
            start_value=float(balance[-1]),
            years=project_years,
            cadence=cadence if cadence in ("monthly", "quarterly", "annual") else "monthly",
            # Carry the most recent actual flow forward. In nominal mode the
            # future inflation path is unknowable, so a withdrawal is held flat
            # in dollars -- which understates the real burden, and is why the UI
            # steers you to real terms for long projections.
            contribution=(contrib_amt * (defl[-1] if real and defl is not None else 1.0)
                          if contrib_amt else 0.0),
            withdrawal_per_period=withdrawal_at(n - 1) if wd_rate > 0 else 0.0,
            paths=int(settings.get("project_paths") or 1000),
            seed=abs(hash((tuple(sorted(weights.items())), rebalance,
                           project_years))) % (2 ** 31),
        )
        if projection:
            projection["real"] = bool(real)
            projection["last_date"] = dates[-1].isoformat()

    years = metrics.calendar_years(index, dates)
    full = [y for y in years if not y["partial"]]
    if full:
        stats["best_year"] = max(full, key=lambda y: y["return"])
        stats["worst_year"] = min(full, key=lambda y: y["return"])
    else:
        stats["best_year"] = stats["worst_year"] = None

    # Money-weighted return only means something once there are real cash flows.
    stats["xirr"] = metrics.xirr(flows) if len(flows) > 2 else None

    stats["real"] = bool(real)
    if wd_rate > 0:
        stats.update({
            "withdrawal_rate": wd_rate,
            "withdrawn": float(withdrawn),
            "survived": depleted_on is None,
            "depleted_on": depleted_on.isoformat() if depleted_on else None,
            # What the withdrawal was worth per year at the start, which is the
            # number people actually care about ("could I live on this?").
            "withdrawal_per_year": float(wd_base * per_year),
        })

    return {
        "name": spec.get("name") or "Portfolio",
        "weights": weights,
        "rebalance": rebalance,
        "dates": [d.isoformat() for d in dates],
        # Rounded: sub-cent precision is noise, and full floats double the payload.
        "balance": [round(float(x), 2) for x in balance],
        "index": [round(float(x), 6) for x in index],
        "drawdown": [round(float(x), 5) for x in metrics.drawdown_series(index)],
        "calendar_years": years,
        "rolling": metrics.rolling_windows(index, dates),
        "projection": projection,
        "stats": stats,
        "notes": notes,
        "price_only_symbols": price_only,
        "_rets": rets,
    }
