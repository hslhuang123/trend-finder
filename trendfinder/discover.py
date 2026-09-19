"""Discover 'surprise' tickers from the wider market.

Candidates come from return-oriented market screeners, are filtered to
mid-cap companies (by market cap band), and the screener keeps the
highest-returning of them. These are never written to data/watchlist.json.
"""
from __future__ import annotations

import random
import re

import yfinance as yf

from . import config

# Screeners that actually contain mid-cap names. day_gainers (highest returns)
# is always queried first so the pool is return-rich.
PRIMARY_SCREENER = "day_gainers"
SCREENERS = [
    "day_gainers",
    "most_actives",
    "growth_technology_stocks",
    "undervalued_growth_stocks",
]

# Mid-cap names used only if the market screeners are unavailable.
FALLBACK = [
    "TTD", "AAL", "MTCH", "GAP", "ONON", "DLO", "PLUG", "M", "AEO", "PINS",
    "ETSY", "ROKU", "SNAP", "LYFT", "AVT", "FORM",
]

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def _valid(symbol, quote_type) -> bool:
    if not symbol or not isinstance(symbol, str) or not _SYMBOL_RE.match(symbol):
        return False
    # Keep ordinary equities; drop ETFs, indices, crypto, funds.
    return quote_type in (None, "EQUITY")


def _from_screener(name: str, count: int = 50,
                   min_market_cap: float = 0.0,
                   max_market_cap: float = 0.0) -> list[str]:
    try:
        result = yf.screen(name, count=count)
    except Exception as exc:  # noqa: BLE001 - discovery must never break the screener
        print(f"[discover] screener '{name}' failed: {exc}")
        return []

    quotes = result.get("quotes", []) if isinstance(result, dict) else []
    out: list[str] = []
    for quote in quotes:
        symbol = quote.get("symbol")
        if not _valid(symbol, quote.get("quoteType")):
            continue
        market_cap = quote.get("marketCap")
        if min_market_cap and (market_cap is None or market_cap < min_market_cap):
            continue
        if max_market_cap and (market_cap is None or market_cap > max_market_cap):
            continue
        out.append(symbol)
    return out


def discover_candidates(limit: int = 8, exclude=None,
                        min_market_cap: float | None = None,
                        max_market_cap: float | None = None) -> list[str]:
    """Return up to `limit` random mid-cap tickers not in `exclude`."""
    if min_market_cap is None:
        min_market_cap = config.DISCOVER_MIN_MARKET_CAP
    if max_market_cap is None:
        max_market_cap = config.DISCOVER_MAX_MARKET_CAP

    excluded = {str(t).upper().strip() for t in (exclude or [])}
    # Always try the return screener first, then shuffle the rest.
    others = [s for s in SCREENERS if s != PRIMARY_SCREENER]
    random.shuffle(others)
    names = [PRIMARY_SCREENER] + others

    pool: list[str] = []
    seen = set(excluded)
    for name in names:
        for symbol in _from_screener(
            name, min_market_cap=min_market_cap, max_market_cap=max_market_cap
        ):
            if symbol in seen:
                continue
            seen.add(symbol)
            pool.append(symbol)
        if len(pool) >= limit * 2:
            break

    if not pool:
        pool = [s for s in FALLBACK if s not in excluded]

    random.shuffle(pool)
    return pool[:limit]
