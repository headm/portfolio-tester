"""Known-answer tests. Run: python3 tests/test_engine.py"""

import datetime as dt
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester import engine, metrics, store

FAILURES = []


def check(label, got, want, tol=1e-6):
    ok = (got is None and want is None) or (
        got is not None and want is not None and abs(got - want) <= tol
    )
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(label)


def seed(symbol, pairs, adjustment=store.TOTAL_RETURN):
    store.forget(symbol)
    store.save_series(
        symbol,
        [(d, p, p, p, p, p, 0) for d, p in pairs],
        source="test",
        adjustment=adjustment,
    )


def weekdays(start, count):
    out, d = [], dt.date.fromisoformat(start)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_flat_growth():
    """A series compounding at a fixed daily rate must reproduce its own CAGR."""
    print("\ntest_flat_growth")
    days = weekdays("2010-01-01", 2521)
    d0 = dt.date.fromisoformat(days[0])
    # Compound per calendar day, not per trading day: 252 weekdays is roughly a
    # trading year but nowhere near a calendar year, and CAGR is calendar-based.
    def price(d):
        elapsed = (dt.date.fromisoformat(d) - d0).days
        return 100 * 1.10 ** (elapsed / 365.25)
    seed("GROW", [(d, price(d)) for d in days])
    r = engine.run({"name": "g", "weights": {"GROW": 100}}, {"initial": 1000})
    check("CAGR is exactly 10%", r["stats"]["cagr"], 0.10, tol=1e-9)
    check("max drawdown", r["stats"]["max_drawdown"], 0.0)
    check("final balance", r["stats"]["final_balance"],
          1000 * price(days[-1]) / price(days[0]), tol=0.01)


def test_no_rebalance_is_pure_buy_and_hold():
    """Two assets, no rebalancing: final value must equal the sum of the parts."""
    print("\ntest_no_rebalance_is_pure_buy_and_hold")
    days = weekdays("2020-01-01", 200)
    seed("AAA", [(d, 10.0 * (1.001 ** i)) for i, d in enumerate(days)])
    seed("BBB", [(d, 50.0 * (0.999 ** i)) for i, d in enumerate(days)])
    r = engine.run(
        {"name": "hold", "weights": {"AAA": 50, "BBB": 50}, "rebalance": "none"},
        {"initial": 1000},
    )
    expected = 500 * (1.001 ** 199) + 500 * (0.999 ** 199)
    check("final balance", r["stats"]["final_balance"], expected, tol=0.01)


def test_rebalance_hand_computed():
    """Annual rebalance on a two-asset toy, checked against shares worked by hand."""
    print("\ntest_rebalance_hand_computed")
    # Year 1: A doubles, B flat. Year 2: A flat, B doubles.
    seed("AAA", [("2020-01-02", 10.0), ("2020-12-31", 20.0), ("2021-12-31", 20.0)])
    seed("BBB", [("2020-01-02", 10.0), ("2020-12-31", 10.0), ("2021-12-31", 20.0)])
    r = engine.run(
        {"name": "rb", "weights": {"AAA": 50, "BBB": 50}, "rebalance": "annual"},
        {"initial": 1000},
    )
    # Start: $500 each -> 50 shares A, 50 shares B.
    # 2020-12-31: A = 50*20 = 1000, B = 50*10 = 500, total 1500. No boundary yet
    #   (same calendar year), so no trade.
    # 2021-12-31 is a new year -> rebalance happens at that day's close, i.e. AFTER
    #   the year's moves: A = 50*20 = 1000, B = 50*20 = 1000, total 2000.
    check("final balance", r["stats"]["final_balance"], 2000.0, tol=0.01)

    # Without rebalancing the answer is identical here, which is the point of the
    # next assertion: the rebalance must occur on the boundary, not before it.
    r2 = engine.run(
        {"name": "hold", "weights": {"AAA": 50, "BBB": 50}, "rebalance": "none"},
        {"initial": 1000},
    )
    check("no-rebalance final", r2["stats"]["final_balance"], 2000.0, tol=0.01)


def test_contributions_and_xirr():
    """Deposits must not inflate the time-weighted return."""
    print("\ntest_contributions_and_xirr")
    days = weekdays("2020-01-01", 505)  # ~2 years
    seed("FLAT", [(d, 100.0) for d in days])  # zero return, ever
    r = engine.run(
        {
            "name": "dca",
            "weights": {"FLAT": 100},
            "rebalance": "none",
            "contribution": {"amount": 100, "cadence": "monthly"},
        },
        {"initial": 1000},
    )
    s = r["stats"]
    check("time-weighted CAGR stays 0", s["cagr"], 0.0, tol=1e-9)
    check("total return stays 0", s["total_return"], 0.0, tol=1e-9)
    check("final == money in", s["final_balance"], s["contributed"], tol=0.01)
    check("profit is zero", s["profit"], 0.0, tol=0.01)
    check("XIRR of a flat asset", s["xirr"], 0.0, tol=1e-4)


def test_costs_reduce_returns():
    print("\ntest_costs_reduce_returns")
    days = weekdays("2020-01-01", 300)
    seed("AAA", [(d, 10.0 * (1.001 ** i)) for i, d in enumerate(days)])
    seed("BBB", [(d, 10.0 * (1.0005 ** i)) for i, d in enumerate(days)])
    base = {"name": "x", "weights": {"AAA": 50, "BBB": 50}, "rebalance": "monthly"}
    free = engine.run(base, {"initial": 10000})
    costly = engine.run(base, {"initial": 10000, "commission": 5, "slippage_bps": 10})
    ok = costly["stats"]["final_balance"] < free["stats"]["final_balance"]
    print(f"  {'PASS' if ok else 'FAIL'}  costs drag returns: "
          f"{costly['stats']['final_balance']:.2f} < {free['stats']['final_balance']:.2f}")
    if not ok:
        FAILURES.append("costs")
    ok2 = costly["stats"]["costs_paid"] > 0 and costly["stats"]["trades"] > 0
    print(f"  {'PASS' if ok2 else 'FAIL'}  costs recorded: "
          f"{costly['stats']['costs_paid']:.2f} over {costly['stats']['trades']} trades")
    if not ok2:
        FAILURES.append("costs recorded")

    er = engine.run(base, {"initial": 10000, "expense_ratio_pct": 1.0})
    ok3 = er["stats"]["final_balance"] < free["stats"]["final_balance"]
    print(f"  {'PASS' if ok3 else 'FAIL'}  expense ratio drags returns")
    if not ok3:
        FAILURES.append("expense ratio")


def test_entry_costs_counted_once():
    """Regression: day-zero costs were added twice, inflating costs_paid."""
    print("\ntest_entry_costs_counted_once")
    seed("FLAT", [(d, 10.0) for d in weekdays("2020-01-01", 300)])
    r = engine.run(
        {"name": "c", "weights": {"FLAT": 100}, "rebalance": "none"},
        {"initial": 10000, "commission": 5, "slippage_bps": 10},
    )
    # One holding, one entry trade: $5 commission + 10bps of $10,000 = $15.
    check("costs paid", r["stats"]["costs_paid"], 15.0, tol=0.01)
    check("final balance", r["stats"]["final_balance"], 9985.0, tol=0.01)
    check("trade count", float(r["stats"]["trades"]), 1.0)


def test_contributions_do_not_rebalance():
    """Regression: contributions used to rebalance the entire portfolio, which
    silently turned a drift strategy into a rebalanced one."""
    print("\ntest_contributions_do_not_rebalance")
    days = weekdays("2020-01-01", 300)
    seed("UP", [(d, 10 * 1.004 ** i) for i, d in enumerate(days)])
    seed("DOWN", [(d, 10 * 0.996 ** i) for i, d in enumerate(days)])
    contrib = {"amount": 100, "cadence": "monthly"}
    drift = engine.run(
        {"name": "d", "weights": {"UP": 50, "DOWN": 50}, "rebalance": "none", "contribution": contrib},
        {"initial": 10000},
    )
    rebal = engine.run(
        {"name": "r", "weights": {"UP": 50, "DOWN": 50}, "rebalance": "monthly", "contribution": contrib},
        {"initial": 10000},
    )
    a, b = drift["stats"]["final_balance"], rebal["stats"]["final_balance"]
    ok = a > b + 1.0   # letting the winner run must beat trimming it monthly
    print(f"  {'PASS' if ok else 'FAIL'}  drift {a:,.2f} > rebalanced {b:,.2f}")
    if not ok:
        FAILURES.append("contributions rebalance")
    # Both still take in exactly the same money.
    check("same money in", drift["stats"]["contributed"], rebal["stats"]["contributed"], tol=0.01)


def test_withdrawals():
    """A withdrawal must leave the time-weighted return untouched, and must
    deplete a portfolio that cannot support it."""
    print("\ntest_withdrawals")
    days = weekdays("2020-01-01", 1300)   # ~5 years
    seed("FLAT", [(d, 100.0) for d in days])

    # Flat asset, 10%/yr withdrawn: strategy returned 0%, but the money runs out.
    r = engine.run(
        {"name": "w", "weights": {"FLAT": 100},
         "withdrawal": {"rate_pct": 10, "cadence": "monthly"}},
        {"initial": 10000},
    )
    s = r["stats"]
    check("time-weighted CAGR unaffected", s["cagr"], 0.0, tol=1e-9)
    ok = s["withdrawn"] > 0 and s["final_balance"] < 10000
    print(f"  {'PASS' if ok else 'FAIL'}  drew {s['withdrawn']:,.0f}, "
          f"balance fell to {s['final_balance']:,.0f}")
    if not ok:
        FAILURES.append("withdrawal drains")

    # 100%/yr on a flat asset must exhaust it inside two years.
    r2 = engine.run(
        {"name": "w2", "weights": {"FLAT": 100},
         "withdrawal": {"rate_pct": 100, "cadence": "monthly"}},
        {"initial": 10000},
    )
    ok2 = not r2["stats"]["survived"] and r2["stats"]["depleted_on"]
    print(f"  {'PASS' if ok2 else 'FAIL'}  depleted on {r2['stats']['depleted_on']}")
    if not ok2:
        FAILURES.append("withdrawal depletion")

    # Contributing and withdrawing at once is contradictory.
    try:
        engine.run(
            {"name": "x", "weights": {"FLAT": 100},
             "contribution": {"amount": 100, "cadence": "monthly"},
             "withdrawal": {"rate_pct": 4, "cadence": "monthly"}},
            {"initial": 10000},
        )
        print("  FAIL  contribute+withdraw was allowed")
        FAILURES.append("contrib+withdraw")
    except engine.EngineError as exc:
        print(f"  PASS  rejected: {exc}")


def test_real_returns_deflate():
    """Real mode must reduce reported returns by roughly the inflation rate,
    and must be a no-op when the price series is already flat."""
    print("\ntest_real_returns_deflate")
    days = weekdays("2006-01-02", 5000)
    seed("FLAT", [(d, 100.0) for d in days])
    nominal = engine.run({"name": "n", "weights": {"FLAT": 100}}, {"initial": 10000})
    real = engine.run({"name": "r", "weights": {"FLAT": 100}},
                      {"initial": 10000, "real": True})
    check("nominal return on a flat asset", nominal["stats"]["cagr"], 0.0, tol=1e-9)
    ok = real["stats"]["real"] and real["stats"]["cagr"] < -0.005
    print(f"  {'PASS' if ok else 'FAIL'}  a flat asset loses "
          f"{real['stats']['cagr']*100:.2f}%/yr in real terms (inflation)")
    if not ok:
        FAILURES.append("real deflation")


def test_rolling_returns_shape():
    print("\ntest_rolling_returns_shape")
    days = weekdays("2006-01-02", 5000)
    d0 = dt.date.fromisoformat(days[0])
    seed("GROW", [(d, 100 * 1.07 ** ((dt.date.fromisoformat(d) - d0).days / 365.25))
                  for d in days])
    r = engine.run({"name": "g", "weights": {"GROW": 100}}, {"initial": 1000})
    win = {w["years"]: w for w in r["rolling"]}
    ok = 5 in win and 10 in win
    print(f"  {'PASS' if ok else 'FAIL'}  windows produced: {sorted(win)}")
    if not ok:
        FAILURES.append("rolling windows")
        return
    # Constant growth => every window identical.
    check("5y best", win[5]["best"], 0.07, tol=1e-6)
    check("5y worst", win[5]["worst"], 0.07, tol=1e-6)
    check("none negative", win[5]["pct_negative"], 0.0)


def test_projection():
    print("\ntest_projection")
    import numpy as np
    from backtester import montecarlo as mc

    # A history of one constant return has no dispersion to sample, so every
    # simulated path must land on the same place.
    flat = np.full(3000, 0.0003)
    p = mc.project(flat, 10000, years=10, paths=400)
    check("no dispersion from constant history",
          p["final"]["p95"] - p["final"]["p5"], 0.0, tol=0.01)
    check("median matches compounding", p["final"]["p50"],
          10000 * 1.0003 ** 2520, tol=1.0)

    # Percentiles must be ordered, always.
    noisy = np.random.default_rng(7).normal(0.0004, 0.011, 4000)
    q = mc.project(noisy, 10000, years=20, paths=800)
    order = [q["final"][f"p{k}"] for k in (5, 25, 50, 75, 95)]
    ok = all(a <= b for a, b in zip(order, order[1:]))
    print(f"  {'PASS' if ok else 'FAIL'}  percentiles ordered: "
          + " <= ".join(f"{v:,.0f}" for v in order))
    if not ok:
        FAILURES.append("percentile order")

    # Same inputs, same fan -- the RNG is seeded from the inputs.
    a = mc.project(noisy, 10000, years=10, paths=300)
    b = mc.project(noisy, 10000, years=10, paths=300)
    ok = a["final"] == b["final"] and a["bands"] == b["bands"]
    print(f"  {'PASS' if ok else 'FAIL'}  projection is deterministic")
    if not ok:
        FAILURES.append("projection determinism")

    # An unsustainable withdrawal must nearly always fail; a small one must not.
    greedy = mc.project(noisy, 100000, years=30, cadence="monthly",
                        withdrawal_per_period=2000, paths=800)
    modest = mc.project(noisy, 100000, years=30, cadence="monthly",
                        withdrawal_per_period=100, paths=800)
    ok = greedy["prob_ran_out"] > 0.9 and modest["prob_ran_out"] < 0.1
    print(f"  {'PASS' if ok else 'FAIL'}  24%/yr fails {greedy['prob_ran_out']*100:.0f}% "
          f"of the time, 1.2%/yr fails {modest['prob_ran_out']*100:.0f}%")
    if not ok:
        FAILURES.append("withdrawal failure rates")

    # Too little history to sample from.
    ok = mc.project(np.full(50, 0.001), 1000, years=10) is None
    print(f"  {'PASS' if ok else 'FAIL'}  refuses to project from under a year of history")
    if not ok:
        FAILURES.append("short history guard")


def test_projection_is_opt_in():
    """A projection is speculative and must never appear unasked."""
    print("\ntest_projection_is_opt_in")
    seed("FLAT", [(d, 100.0) for d in weekdays("2010-01-01", 2000)])
    off = engine.run({"name": "a", "weights": {"FLAT": 100}}, {"initial": 1000})
    on = engine.run({"name": "a", "weights": {"FLAT": 100}},
                    {"initial": 1000, "project_years": 10})
    ok = off["projection"] is None and on["projection"] is not None
    print(f"  {'PASS' if ok else 'FAIL'}  absent by default, present when requested")
    if not ok:
        FAILURES.append("projection opt-in")


def test_alignment_truncates_and_reports():
    print("\ntest_alignment_truncates_and_reports")
    seed("OLD", [(d, 100.0) for d in weekdays("2000-01-03", 6800)])   # -> ~2026
    seed("NEW", [(d, 100.0) for d in weekdays("2015-01-01", 2500)])   # -> ~2024
    r = engine.run(
        {"name": "mix", "weights": {"OLD": 50, "NEW": 50}},
        {"start": "2000-01-01", "initial": 1000},
    )
    ok = r["dates"][0] >= "2015-01-01" and any("NEW" in n for n in r["notes"])
    print(f"  {'PASS' if ok else 'FAIL'}  start truncated to {r['dates'][0]}; notes={r['notes']}")
    if not ok:
        FAILURES.append("alignment")


def test_price_only_flagged():
    print("\ntest_price_only_flagged")
    seed("NODIV", [(d, 100.0) for d in weekdays("2020-01-01", 300)],
         adjustment=store.PRICE_ONLY)
    r = engine.run({"name": "p", "weights": {"NODIV": 100}}, {"initial": 1000})
    ok = r["price_only_symbols"] == ["NODIV"]
    print(f"  {'PASS' if ok else 'FAIL'}  flagged {r['price_only_symbols']}")
    if not ok:
        FAILURES.append("price_only flag")


def test_determinism():
    print("\ntest_determinism")
    days = weekdays("2020-01-01", 400)
    seed("AAA", [(d, 10.0 * (1.001 ** i)) for i, d in enumerate(days)])
    spec = {"name": "d", "weights": {"AAA": 100}, "rebalance": "quarterly"}
    a = engine.run(spec, {"initial": 5000})
    b = engine.run(spec, {"initial": 5000})
    ok = a["balance"] == b["balance"] and a["stats"] == b["stats"]
    print(f"  {'PASS' if ok else 'FAIL'}  identical inputs -> identical output")
    if not ok:
        FAILURES.append("determinism")


def test_rejects_bad_input():
    print("\ntest_rejects_bad_input")
    for label, spec, settings in [
        ("empty weights", {"weights": {}}, {"initial": 100}),
        ("negative weight", {"weights": {"AAA": -50, "BBB": 150}}, {"initial": 100}),
        ("bad rebalance", {"weights": {"AAA": 100}, "rebalance": "hourly"}, {"initial": 100}),
        ("zero initial", {"weights": {"AAA": 100}}, {"initial": 0}),
    ]:
        try:
            engine.run(spec, settings)
            print(f"  FAIL  {label}: no error raised")
            FAILURES.append(label)
        except engine.EngineError as exc:
            print(f"  PASS  {label}: {exc}")


def cleanup():
    for s in ("GROW", "AAA", "BBB", "FLAT", "OLD", "NEW", "NODIV", "UP", "DOWN"):
        store.forget(s)


if __name__ == "__main__":
    test_flat_growth()
    test_no_rebalance_is_pure_buy_and_hold()
    test_rebalance_hand_computed()
    test_contributions_and_xirr()
    test_costs_reduce_returns()
    test_entry_costs_counted_once()
    test_contributions_do_not_rebalance()
    test_withdrawals()
    test_real_returns_deflate()
    test_rolling_returns_shape()
    test_projection()
    test_projection_is_opt_in()
    test_alignment_truncates_and_reports()
    test_price_only_flagged()
    test_determinism()
    test_rejects_bad_input()
    cleanup()
    print("\n" + ("ALL PASS" if not FAILURES else f"FAILURES: {FAILURES}"))
    sys.exit(1 if FAILURES else 0)
