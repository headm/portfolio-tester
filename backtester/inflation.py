"""Turn monthly CPI into a daily deflator aligned to a run's trading days.

Monthly observations are interpolated linearly rather than held as a step
function: a step produces visible monthly stairs in a daily real equity curve,
which is an artefact of the data's frequency, not of anything that happened.
Dates past the last CPI print carry the final value forward.
"""

import datetime as dt

import numpy as np

from . import store
from .ingest import fred


def _to_ordinal(iso):
    return dt.date.fromisoformat(iso).toordinal()


def deflator(dates):
    """Multipliers converting nominal values to base-date (dates[0]) dollars.

    Returns None when CPI is unavailable, so callers can fall back to nominal.
    """
    if not fred.ensure_cached():
        return None
    cpi_dates, cpi_values = store.get_macro(fred.SERIES)
    if len(cpi_dates) < 2:
        return None

    xs = np.array([_to_ordinal(d) for d in cpi_dates], dtype=float)
    ys = np.array(cpi_values, dtype=float)
    want = np.array([d.toordinal() for d in dates], dtype=float)

    # np.interp clamps outside the known range, which is the flat carry-forward
    # we want at the recent end and the best available guess at the old end.
    level = np.interp(want, xs, ys)
    if level[0] <= 0:
        return None
    return level[0] / level


def coverage():
    """(last CPI date, how stale it is in days) for display."""
    meta = store.macro_meta(fred.SERIES)
    if not meta or not meta.get("last_date"):
        return None, None
    last = dt.date.fromisoformat(meta["last_date"])
    return meta["last_date"], (dt.date.today() - last).days
