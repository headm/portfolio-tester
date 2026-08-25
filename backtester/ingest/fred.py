"""CPI from FRED, for reporting returns in real (inflation-adjusted) terms.

fredgraph.csv needs no API key. CPIAUCSL is the monthly CPI-U index for all
urban consumers, published with roughly a one-month lag -- the deflator carries
the last observation forward to cover the gap.
"""

import csv
import io
import time

import requests

from .. import store

SERIES = "CPIAUCSL"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TIMEOUT = 20
RETRIES = 3

# Deliberately no custom User-Agent header. FRED's edge silently black-holes
# unfamiliar agent strings -- a descriptive one hangs until timeout while the
# requests default sails through. Verified against both.


class Unavailable(Exception):
    pass


def fetch():
    last = None
    resp = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(URL, params={"id": SERIES}, timeout=TIMEOUT)
            break
        except requests.RequestException as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    if resp is None:
        raise Unavailable(str(last))
    if resp.status_code != 200 or not resp.text.lstrip().lower().startswith("observation"):
        raise Unavailable(f"unexpected response from FRED (HTTP {resp.status_code})")

    reader = csv.reader(io.StringIO(resp.text))
    next(reader, None)
    rows = []
    for line in reader:
        if len(line) < 2 or line[1] in (".", ""):
            continue
        try:
            rows.append((line[0][:10], float(line[1])))
        except ValueError:
            continue
    if not rows:
        raise Unavailable("FRED returned no usable observations")
    return rows


def ensure_cached(refresh=False):
    """Returns True if CPI data is available (cached or freshly fetched)."""
    meta = store.macro_meta(SERIES)
    if meta and not refresh:
        return True
    try:
        store.save_macro(SERIES, fetch())
        return True
    except Unavailable:
        return bool(meta)   # stale is better than nothing
