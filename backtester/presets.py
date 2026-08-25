"""Starting-point portfolios, so the app is useful before you type anything."""

PRESETS = [
    {
        "key": "sp500",
        "name": "S&P 500",
        "blurb": "The default alternative every strategy should have to beat.",
        "weights": {"SPY": 100},
        "rebalance": "none",
    },
    {
        "key": "sixty_forty",
        "name": "Classic 60/40",
        "blurb": "60% US stocks, 40% US bonds, rebalanced annually.",
        "weights": {"SPY": 60, "AGG": 40},
        "rebalance": "annual",
    },
    {
        "key": "three_fund",
        "name": "Three-Fund",
        "blurb": "Total US + total international + total bond.",
        "weights": {"VTI": 54, "VXUS": 36, "BND": 10},
        "rebalance": "annual",
    },
    {
        "key": "all_weather",
        "name": "All Weather",
        "blurb": "Ray Dalio's risk-balanced mix, heavy on long bonds.",
        "weights": {"VTI": 30, "TLT": 40, "IEI": 15, "GLD": 7.5, "DBC": 7.5},
        "rebalance": "annual",
    },
    {
        "key": "permanent",
        "name": "Permanent Portfolio",
        "blurb": "Equal parts stocks, long bonds, gold, and cash.",
        "weights": {"VTI": 25, "TLT": 25, "GLD": 25, "BIL": 25},
        "rebalance": "annual",
    },
    {
        "key": "megacap_tech",
        "name": "Mega-cap Tech",
        "blurb": "Equal-weight big tech. Survivorship bias: these are today's winners.",
        "weights": {"AAPL": 20, "MSFT": 20, "GOOGL": 20, "AMZN": 20, "NVDA": 20},
        "rebalance": "annual",
    },
]
