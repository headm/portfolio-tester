"""CSV shape detection for imported price files.

Stooq ships at least two layouts and two date formats, and broker exports add
more, so the importer sniffs the header rather than assuming one.
"""

import csv
import io

# Canonical field -> the header spellings seen in the wild.
ALIASES = {
    "date": {"date", "<date>", "datetime", "time", "day"},
    "open": {"open", "<open>", "o"},
    "high": {"high", "<high>", "h"},
    "low": {"low", "<low>", "l"},
    "close": {"close", "<close>", "c", "close/last", "closing price"},
    "adj_close": {"adj close", "adj_close", "adjclose", "adjusted close",
                  "adjusted_close", "a"},
    "volume": {"volume", "<vol>", "vol", "v"},
    "ticker": {"ticker", "<ticker>", "symbol", "<per>"},
}
_LOOKUP = {spelling: field for field, sp in ALIASES.items() for spelling in sp}


class UnknownFormat(Exception):
    pass


def _clean(cell):
    return cell.strip().strip('"').lower()


def sniff(text):
    """Return {canonical_field: column_index} for the file's header row."""
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","

    first = next(csv.reader(io.StringIO(sample), delimiter=delim), None)
    if not first:
        raise UnknownFormat("file is empty")

    mapping = {}
    for i, cell in enumerate(first):
        field = _LOOKUP.get(_clean(cell))
        if field and field not in mapping:
            mapping[field] = i

    if "date" not in mapping or "close" not in mapping:
        raise UnknownFormat(
            "could not find date and close columns in header: " + ",".join(first)
        )
    return mapping, delim


def parse_date(raw):
    """Accept YYYY-MM-DD, YYYYMMDD, YYYY/MM/DD and MM/DD/YYYY."""
    s = raw.strip().strip('"')
    if not s:
        raise ValueError("empty date")
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    s = s.replace("/", "-")
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError(f"unrecognised date: {raw}")
    if len(parts[0]) == 4:
        y, m, d = parts
    else:
        m, d, y = parts
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def parse_number(raw):
    if raw is None:
        return None
    s = str(raw).strip().strip('"').replace("$", "").replace(",", "")
    if s in ("", "-", "N/A", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
