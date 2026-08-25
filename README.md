# Wealthmap

A local web app for testing how a bundle of stocks or ETFs would have performed,
and for comparing portfolio strategies side by side over horizons up to 20+ years.

Everything runs on your machine. No account, no API key, no data leaves the box
except the price fetches themselves.

```bash
python3 run.py
```

Then open http://127.0.0.1:8777 (it opens automatically).

## What it does

- **Build portfolios** — any mix of tickers and weights, with presets to start from
  (S&P 500, 60/40, Three-Fund, All Weather, Permanent Portfolio).
- **Compare up to 6 side by side** — duplicate a portfolio and change one variable
  to isolate its effect.
- **Rebalancing** — never (let it drift), monthly, quarterly, annually, or when
  drift exceeds a band.
- **Recurring contributions** — model actually adding money every month, not just
  a lump sum sitting there.
- **Costs** — per-trade commission, slippage in basis points, annual expense ratio.
- **Withdrawals** — test a safe-withdrawal rate: take 4% of the starting balance
  each year, raised with inflation, and see whether the money lasted.
- **Real terms** — one toggle restates everything in start-date dollars.
- **Rolling returns** — the return of *every* holding period of a given length,
  not just the one starting on your chosen date.
- **Projection** — a Monte Carlo fan of possible futures, including the odds of
  running out of money at a given withdrawal rate. Off by default.
- **Metrics** — CAGR, XIRR, volatility, Sharpe, Sortino, max drawdown with dates,
  longest time underwater, best/worst year, beta and correlation to a benchmark.
- **It remembers** — your portfolios persist across reloads, and "Copy link"
  produces a URL that restores the whole setup (state travels in the fragment,
  so it never reaches a server).

## Data

Prices come from stockanalysis.com — no key, full history (SPY back to its 1993
inception, KO to 1968), and critically a **dividend-adjusted** close.

That last part matters more than it sounds. Most free price feeds adjust for
splits but not dividends. Over 20 years that understates a total return by
roughly a third, because reinvested dividends are a large share of long-run
equity returns. This app computes everything from an adjusted close and tags
every series with how it was adjusted:

- `total_return` — dividends reinvested. Correct.
- `price_only` — dividends dropped. The UI shows a warning banner naming the
  affected tickers whenever a backtest depends on one.

Each symbol is fetched once and cached in `data/vault.sqlite`, so repeat
backtests are instant and work offline. **Update prices** re-fetches everything;
the status line tells you how current the cache is.

That update is a full re-fetch rather than an append of recent days, deliberately:
a dividend-adjusted close is revised *backwards* every time a dividend is paid,
so appending would leave the whole history carrying stale adjustment factors
while looking perfectly up to date.

Inflation data is CPI-U (`CPIAUCSL`) from FRED, also keyless. Monthly
observations are interpolated to daily — a step function would put visible
monthly stairs in a daily real-terms chart, which is an artefact of the data's
frequency rather than anything that happened. Note that FRED's edge silently
black-holes unfamiliar `User-Agent` strings: a descriptive one hangs until
timeout while the default sails through, which is why that request sends no
custom agent.

### If the data source ever breaks

It's an undocumented endpoint, so it may change. The cache means existing
backtests keep working regardless — you'd only lose the ability to add new
tickers. As a fallback you can import price files you downloaded yourself:

```bash
python3 run.py import ~/Downloads/d_us_txt.zip
```

This accepts a stooq bulk `.zip`, an unpacked directory, or loose CSV/TXT files,
and auto-detects the layout (both stooq's web-CSV and bulk-ASCII headers, and
`YYYY-MM-DD` / `YYYYMMDD` dates). Stooq data is split-adjusted only, so anything
imported this way is tagged `price_only` and warned about. Add `--all` to import
more than the first 50 tickers.

## How the numbers are computed

The details that separate a correct backtester from a plausible-looking one:

- **No lookahead.** A rebalance triggered on day D executes at day D's close.
- **Common window.** All portfolios in a comparison run over the same date range,
  starting no earlier than the newest holding's inception — otherwise a strategy
  could look better purely for starting later. The app tells you when it moves
  your start date and which ticker forced it.
- **Two different returns, because they answer different questions.**
  - *CAGR* is time-weighted: growth of a dollar, neutral to deposits. This is
    what measures the strategy.
  - *XIRR* is money-weighted: what the money you actually put in earned. With
    monthly contributions these diverge sharply — over 2006–2026 a 60/40 with
    $500/month shows 8.3% CAGR but 9.2% XIRR, because the deposits kept buying
    through 2008. Reporting only one of these is a common and misleading bug.
  - Risk stats (volatility, Sharpe, drawdown, calendar years) all come from the
    time-weighted series, so a year of big deposits can't masquerade as a year of
    big returns.
- **Fractional shares** assumed; cash residual tracked explicitly.
- **Withdrawals never double as a rebalance.** Raising cash sells every holding
  pro rata, so drawing an income from a drift portfolio leaves it drifting.
- **Real terms deflate the price series itself**, so CAGR, drawdown and XIRR all
  come out real without a second code path. A contribution of "$500/month" is
  nominal and shrinks in real terms; a withdrawal is the reverse, because the
  safe-withdrawal rule is defined as a constant *real* income.
- **Rolling returns use calendar windows**, not a fixed trading-day count, so a
  "10 year" period is genuinely ten years.

## About the projection

Off unless you ask for it, because it is speculative and should never appear as a
side effect of running a backtest.

**It is not a forecast.** It answers a narrower question: if the future resembles
a reshuffling of the past this portfolio actually lived through, what spread of
outcomes does that imply? Every number it produces is conditional on that "if".
If the coming decades differ in kind rather than merely in order — a different
inflation regime, a different starting valuation — none of it applies.

Two deliberate method choices:

- **Block bootstrap, not independent daily draws.** Resampling single days
  destroys the serial structure of returns — volatility clustering, but also mean
  reversion. Crashes stop lasting months and recoveries stop taking years, and
  that structure is what drives sequence-of-returns risk for anyone drawing an
  income. Sampling quarter-long blocks keeps it. Note this cuts both ways: on US
  60/40 history the block version reports a *lower* 4%-rule failure rate than
  independent draws, because preserving post-crash recoveries matters more here
  than preserving the crashes. The aim is fidelity to real sequences, not a more
  conservative answer.
- **No normal distribution.** Real returns have far fatter tails than a Gaussian,
  and fitting one would understate exactly the disasters the exercise exists to
  measure. Resampling real history keeps the real tails.

Run it in real terms. A 30-year nominal projection mostly measures the dollar
shrinking, and a withdrawal held flat in nominal dollars understates its real
burden.

Seeded from its inputs, so the same portfolio always produces the same fan.

Sanity check — a $1M 60/40 over 30 years, real terms, by withdrawal rate:

| Rate | Survives |
|---|---|
| 3% | 100% |
| 4% | 99.9% |
| 5% | 81% |
| 6% | 0.4% |
| 7% | 0% |

The cliff between 5% and 6%, and ~99% survival at 4%, are what the retirement
literature reports for this period and asset mix.

## Deploying it

The app is a **WSGI callable** in `backtester/wsgi.py`. That one object is
everything: routing, the API, and static files.

- Locally, `run.py` serves it through `wsgiref`.
- On Vercel, `pyproject.toml` names it: `[tool.vercel] entrypoint =
  "api.app:app"`. Vercel's current Python runtime wants exactly one entrypoint
  declared this way; per-file handlers under `api/` are not what it looks for.
- On any other host, `gunicorn backtester.wsgi:app` works, because WSGI is the
  portable interface.

There is one implementation, so local and deployed cannot drift.
`tests/test_endpoints.py` asserts the declared entrypoint resolves, that it is
the same object `run.py` serves, and that every route the frontend calls
answers — including that CSS comes back as CSS, which is how a previous
deployment silently lost its stylesheet.

Read the rest of this section before deploying, though, because the
architecture and the platform still disagree on storage.

The app is built around a price vault on local disk. A serverless deployment has
no such thing: the bundle is read-only, only the temp directory is writable, and
that directory belongs to one instance and disappears when the instance is
recycled. So every cold start begins with an empty vault and refetches from
scratch — about 2s for a two-ticker portfolio, versus 0.04s once warm. It works,
it is just paying that toll repeatedly rather than once.

There is a second consideration. Locally, this is one person making a handful of
requests to stockanalysis.com. Deployed publicly it becomes a shared server
calling an undocumented third-party endpoint on behalf of every visitor, with no
persistent cache to blunt it. That is a good way to get an IP blocked, and it is
a different bargain than the one the local tool strikes.

If you want it hosted, the architecture fits a container host with a persistent
volume — Fly.io, Railway, Render — far better than it fits serverless. Point
`BACKTESTER_DB` at the mounted volume and the vault behaves exactly as it does
locally:

```bash
BACKTESTER_DB=/data/vault.sqlite python3 run.py
```

To stay on Vercel with a durable vault, `store.py` is the only module that
touches SQL — swapping it for Postgres is contained to that one file.

## Known limitations

- **Survivorship bias is yours to avoid.** Backtesting today's winners (the
  Mega-cap Tech preset is deliberately labeled this way) tells you what you'd
  have made if you had picked them in advance, which you would not have.
- No taxes on rebalancing or dividends.
- No shorting, leverage, or options.
- The projection resamples one portfolio's own past. It cannot know about
  regimes that history did not contain.
- Delisted tickers are generally not available, which biases any hand-picked
  basket upward.
- US listings only.

## Testing

```bash
python3 tests/test_engine.py
python3 tests/test_endpoints.py
```

Known-answer tests: a series compounding at exactly 10%/yr must report 10.000%
CAGR; annual rebalancing is checked against hand-computed share counts; a flat
asset with monthly deposits must report exactly 0% time-weighted return and 0%
XIRR; costs must reduce returns; date alignment must truncate and say so.

Projection tests assert that a constant-return history yields zero dispersion,
that percentiles come out ordered, that the fan is reproducible, that an
unsustainable withdrawal fails ~100% of the time while a trivial one fails ~0%,
and that under a year of history refuses to project at all.

Newer cases cover withdrawals (a 100%/yr draw must exhaust a flat asset, and no
withdrawal may move the time-weighted return), real terms (a flat asset must lose
roughly the inflation rate each year), and rolling returns (constant growth must
produce an identical figure for every window).

The strongest check is external, though: SPY buy-and-hold reproduces 2008 at
−36.8% and 2013 at +32.3%, and puts the GFC drawdown at −55.2% between
2007-10-09 and 2009-03-09. Those match the historical record.

## Layout

```
run.py                      entry point
backtester/
  store.py                  SQLite vault -- the only module that knows SQL
  ingest/stockanalysis.py   primary price source
  ingest/fred.py            CPI, for real-terms returns
  ingest/stooq.py           fallback importer
  inflation.py              monthly CPI -> daily deflator
  engine.py                 daily simulation
  metrics.py                CAGR, drawdown, Sharpe, XIRR, rolling returns
  montecarlo.py             block-bootstrap forward projection
  api.py                    request handling
  wsgi.py                   the WSGI app: routing + static, one implementation
public/                     single-page UI, no build step
api/app.py                  the entrypoint Vercel is pointed at
tests/
```

Dependencies: `pandas`, `numpy`, `requests`. The server is standard library only.

---

**This is a historical simulation, not financial advice.** Past performance does
not predict future results, and a backtest cannot capture the discipline required
to actually hold a strategy through the drawdowns it shows. I'm not a licensed
financial adviser.
