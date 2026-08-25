"""Forward projection by bootstrapping the portfolio's own history.

This is NOT a forecast. It answers a narrower question: if the future resembles
a reshuffling of the past this portfolio actually lived through, what spread of
outcomes does that imply? Everything it produces is conditional on that "if",
which is why the UI states it and why the output is a fan rather than a number.

Two deliberate choices:

* **Block bootstrap, not IID draws.** Resampling individual days independently
  destroys the serial structure of returns: volatility clustering, but also mean
  reversion. Crashes stop lasting months and recoveries stop taking years, and
  that structure is exactly what governs sequence-of-returns risk for anyone
  drawing an income. Note this cuts both ways -- on US 60/40 history the block
  version reports a *lower* 4%-rule failure rate than IID, because preserving
  post-crash recoveries matters more here than preserving the crashes. The point
  is fidelity to the real sequence, not a more conservative answer.
* **No normal distribution.** Real return distributions have far fatter tails
  than a Gaussian, and fitting one understates precisely the disasters the
  exercise exists to measure. Sampling real history keeps the real tails.

Deterministic by construction: the RNG is seeded from the inputs, so the same
portfolio always yields the same fan.
"""

import numpy as np

PERCENTILES = (5, 25, 50, 75, 95)
MAX_PATHS = 5000
MAX_YEARS = 40
TRADING_DAYS = 252


def _flow_steps(n_days, cadence):
    """Trading-day counts at which a monthly/quarterly/annual flow lands.

    Every cadence is a whole number of monthly segments (1, 3 or 12), so flows
    always coincide with a segment boundary in the loop below.
    """
    months = {"monthly": 1, "quarterly": 3, "annual": 12}.get(cadence, 1)
    every = max(int(round(TRADING_DAYS / 12)), 1) * months
    return set(range(every, n_days + 1, every))


def project(returns, start_value, years, cadence="monthly", contribution=0.0,
            withdrawal_per_period=0.0, paths=1000, block_days=63, seed=12345):
    """Bootstrap `paths` futures of `years` length.

    returns:      historical daily returns of the portfolio (1-D array)
    start_value:  where the backtest ended -- the projection continues from there
    block_days:   ~63 trading days (a quarter) keeps slumps and rallies intact
    """
    hist = np.asarray(returns, dtype=float)
    hist = hist[np.isfinite(hist)]
    if hist.size < TRADING_DAYS:
        return None                      # under a year of history proves nothing

    paths = int(min(max(paths, 100), MAX_PATHS))
    years = float(min(max(years, 1), MAX_YEARS))
    n_days = int(round(years * TRADING_DAYS))
    block = int(min(max(block_days, 5), max(hist.size // 2, 5)))
    n_blocks = int(np.ceil(n_days / block))

    rng = np.random.default_rng(seed)
    # One random start per block per path; wrapped so every block is full length.
    starts = rng.integers(0, hist.size, size=(paths, n_blocks))

    contrib_steps = _flow_steps(n_days, cadence) if contribution else set()
    wd_steps = _flow_steps(n_days, cadence) if withdrawal_per_period else set()

    values = np.full(paths, float(start_value))
    alive = np.ones(paths, dtype=bool)
    depleted_step = np.full(paths, -1, dtype=np.int32)

    # Step a month at a time rather than a day at a time. Between cash flows the
    # balance only needs the product of that stretch's returns, so the whole
    # segment collapses into one vectorised multiply -- ~20x fewer Python-level
    # iterations, with identical results. Sampling the fan monthly is also all
    # the resolution a 30-year chart can show.
    sample_every = max(int(round(TRADING_DAYS / 12)), 1)
    bands, band_steps = [], []

    t = 0
    while t < n_days:
        seg = min(sample_every, n_days - t)
        ts = np.arange(t, t + seg)
        src = (starts[:, ts // block] + (ts % block)) % hist.size   # (paths, seg)
        growth = np.prod(1.0 + hist[src], axis=1)
        values = np.where(alive, values * growth, values)
        t += seg

        if t in contrib_steps:
            values = np.where(alive, values + contribution, values)
        if t in wd_steps:
            take = np.minimum(withdrawal_per_period, np.maximum(values, 0.0))
            values = np.where(alive, values - take, values)
            just_died = alive & (values <= 1e-6)
            if just_died.any():
                depleted_step = np.where(just_died, t, depleted_step)
                alive = alive & ~just_died
                values = np.where(just_died, 0.0, values)

        values = np.maximum(values, 0.0)
        bands.append(np.percentile(values, PERCENTILES))
        band_steps.append(t)

    bands = np.array(bands)
    final = values
    ran_out = depleted_step >= 0

    out = {
        "years": years,
        "paths": paths,
        "block_days": block,
        "start_value": float(start_value),
        "steps": band_steps,
        "percentiles": list(PERCENTILES),
        "bands": [[round(float(v), 2) for v in row] for row in bands],
        "final": {f"p{p}": float(np.percentile(final, p)) for p in PERCENTILES},
        "mean_final": float(np.mean(final)),
        "prob_below_start": float(np.mean(final < start_value)),
    }
    if withdrawal_per_period:
        out["prob_ran_out"] = float(np.mean(ran_out))
        if ran_out.any():
            out["median_years_to_depletion"] = float(
                np.median(depleted_step[ran_out]) / TRADING_DAYS
            )
    return out
