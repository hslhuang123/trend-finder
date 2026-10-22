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


# North American exchanges selectable for discovery: label -> Yahoo exchange codes.
# Mexico is omitted: the market-cap band is applied in each listing's own
# currency, so a $2-10B band would mean something very different in MXN.
EXCHANGES: dict[str, tuple[str, ...]] = {
    "Toronto Stock Exchange (TSX)": ("TOR",),
    "TSX Venture Exchange (TSXV)": ("VAN",),
    "NASDAQ": ("NMS", "NGM", "NCM"),
    "NYSE": ("NYQ",),
    "NYSE American": ("ASE",),
}
DEFAULT_EXCHANGE = "Toronto Stock Exchange (TSX)"


def _from_exchange(exchange: str, count: int = 50,
                   min_market_cap: float = 0.0,
                   max_market_cap: float = 0.0) -> list[str]:
    """Top one-day gainers listed on `exchange`, inside the market-cap band."""
    codes = EXCHANGES[exchange]
    clauses = [
        yf.EquityQuery("eq", ["exchange", codes[0]])
        if len(codes) == 1
        else yf.EquityQuery("is-in", ["exchange", *codes])
    ]
    if min_market_cap and max_market_cap:
        clauses.append(yf.EquityQuery("btwn", ["intradaymarketcap", min_market_cap, max_market_cap]))
    elif min_market_cap:
        clauses.append(yf.EquityQuery("gte", ["intradaymarketcap", min_market_cap]))
    elif max_market_cap:
        clauses.append(yf.EquityQuery("lte", ["intradaymarketcap", max_market_cap]))
    try:
        result = yf.screen(
            yf.EquityQuery("and", clauses),
            sortField="percentchange", sortAsc=False, size=count,
        )
    except Exception as exc:  # noqa: BLE001 - discovery must never break the screener
        print(f"[discover] exchange '{exchange}' screen failed: {exc}")
        return []

    quotes = result.get("quotes", []) if isinstance(result, dict) else []
    return [q["symbol"] for q in quotes if _valid(q.get("symbol"), q.get("quoteType"))]


def discover_candidates(limit: int = 8, exclude=None,
                        min_market_cap: float | None = None,
                        max_market_cap: float | None = None,
                        exchange: str | None = None) -> list[str]:
    """Return up to `limit` random mid-cap tickers not in `exclude`.

    With `exchange` (a key of EXCHANGES) candidates are restricted to that
    exchange and there is no cross-exchange fallback; otherwise they come from
    the general market screeners.
    """
    if exchange is not None and exchange not in EXCHANGES:
        raise ValueError(f"Unknown exchange {exchange!r}; choose from {list(EXCHANGES)}")
    if min_market_cap is None:
        min_market_cap = config.DISCOVER_MIN_MARKET_CAP
    if max_market_cap is None:
        max_market_cap = config.DISCOVER_MAX_MARKET_CAP

    excluded = {str(t).upper().strip() for t in (exclude or [])}
    pool: list[str] = []
    seen = set(excluded)

    if exchange is not None:
        for symbol in _from_exchange(
            exchange, min_market_cap=min_market_cap, max_market_cap=max_market_cap
        ):
            if symbol not in seen:
                seen.add(symbol)
                pool.append(symbol)
        random.shuffle(pool)
        return pool[:limit]

    # Always try the return screener first, then shuffle the rest.
    others = [s for s in SCREENERS if s != PRIMARY_SCREENER]
    random.shuffle(others)
    names = [PRIMARY_SCREENER] + others

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
