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

# Look-back windows (label -> trading days) for ranking an exchange's gainers.
PERFORMANCE_WINDOWS: dict[str, int] = {
    "1 day": 1,
    "5 days": 5,
    "1 month": 21,
    "3 months": 63,
}
DEFAULT_WINDOW = "1 month"

# Yahoo's screener can only sort by the 1-day change, so for longer windows we
# take the most-traded names in the band and rank them by their own price history.
_UNIVERSE_SIZE = 250  # Yahoo's per-request maximum

# "Overextended" filter: of each band's best performers, keep only names still in
# an orderly uptrend. Jev rates names far above their averages as high entry risk,
# so without this nearly every discovered name came back "avoid".
MAX_RSI = 65.0              # not overbought
MAX_ABOVE_MA20_PCT = 8.0    # at most this far above the 20-day average
_FILTER_DEPTH = 40          # top-ranked names per band examined for the filter


def _drop_extended(symbols: list[str]) -> list[str]:
    """Keep the symbols that are still above their 20- and 50-day averages (an
    intact uptrend) but not overbought: RSI <= MAX_RSI and no more than
    MAX_ABOVE_MA20_PCT above the 20-day average. Rank order is preserved."""
    if not symbols:
        return []
    from .market_data import fetch_trend_data  # local import: market_data is heavy

    df = fetch_trend_data(symbols)
    ok = df[
        (df["rsi"] <= MAX_RSI)
        & (df["above_ma20_pct"] > 0) & (df["above_ma20_pct"] <= MAX_ABOVE_MA20_PCT)
        & (df["above_ma50_pct"] > 0)
    ]
    keep = set(ok["ticker"])
    return [s for s in symbols if s in keep]


def _window_returns(symbols: list[str], window_days: int) -> dict[str, float]:
    """Total return over the last `window_days` trading days, per symbol."""
    from .market_data import _close_series_for  # local import: market_data is heavy

    data = yf.download(
        symbols, period="6mo", interval="1d", group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )
    out: dict[str, float] = {}
    for symbol in symbols:
        close = _close_series_for(data, symbol)
        if close is None or len(close) <= window_days:
            continue
        start = float(close.iloc[-(window_days + 1)])
        if start > 0:
            out[symbol] = float(close.iloc[-1]) / start - 1.0
    return out


def _from_exchange(exchange: str, window_days: int = 1,
                   min_market_cap: float = 0.0,
                   max_market_cap: float = 0.0) -> list[str]:
    """Best performers over `window_days` listed on `exchange`, best first.

    Candidates are restricted to the market-cap band. A 1-day window uses
    Yahoo's own sort; longer windows rank the most-traded names by price history.
    """
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

    one_day = window_days <= 1
    try:
        result = yf.screen(
            yf.EquityQuery("and", clauses),
            sortField="percentchange" if one_day else "avgdailyvol3m",
            sortAsc=False,
            size=50 if one_day else _UNIVERSE_SIZE,
        )
        quotes = result.get("quotes", []) if isinstance(result, dict) else []
        symbols = [q["symbol"] for q in quotes if _valid(q.get("symbol"), q.get("quoteType"))]
        if one_day or not symbols:
            return symbols
        returns = _window_returns(symbols, window_days)
    except Exception as exc:  # noqa: BLE001 - discovery must never break the screener
        print(f"[discover] exchange '{exchange}' screen failed: {exc}")
        return []
    return sorted(returns, key=returns.get, reverse=True)


def cap_bands() -> dict[str, tuple[float, float]]:
    """Market-cap bands (min, max; 0 = unbounded) used for exchange discovery.

    Mid-cap is the configured band; large-cap is everything above its ceiling.
    """
    mid_min, mid_max = config.DISCOVER_MIN_MARKET_CAP, config.DISCOVER_MAX_MARKET_CAP
    return {"mid-cap": (mid_min, mid_max), "large-cap": (mid_max, 0.0)}


def discover_by_band(exchange: str, window: str = DEFAULT_WINDOW, exclude=None,
                     per_band: int = 5, skip_extended: bool = True) -> dict[str, list[str]]:
    """Best performers on `exchange` over `window`, ranked best-first per cap band.

    Returns {band: [tickers]} with up to `per_band` names each (bands from
    `cap_bands`), never repeating a name and skipping `exclude`. With
    `skip_extended`, names that have already run too far are dropped first (see
    `_drop_extended`). There is no cross-exchange fallback; a band the exchange
    has no (remaining) names for comes back empty.
    """
    if exchange not in EXCHANGES:
        raise ValueError(f"Unknown exchange {exchange!r}; choose from {list(EXCHANGES)}")
    if window not in PERFORMANCE_WINDOWS:
        raise ValueError(f"Unknown window {window!r}; choose from {list(PERFORMANCE_WINDOWS)}")

    taken = {str(t).upper().strip() for t in (exclude or [])}
    out: dict[str, list[str]] = {}
    for band, (lo, hi) in cap_bands().items():
        ranked = [
            s for s in _from_exchange(
                exchange, window_days=PERFORMANCE_WINDOWS[window],
                min_market_cap=lo, max_market_cap=hi,
            ) if s not in taken
        ]
        if skip_extended:
            ranked = _drop_extended(ranked[:_FILTER_DEPTH])
        out[band] = ranked[:per_band]
        taken.update(out[band])
    return out


def discover_candidates(limit: int = 8, exclude=None,
                        min_market_cap: float | None = None,
                        max_market_cap: float | None = None) -> list[str]:
    """Return up to `limit` random mid-cap tickers not in `exclude`, from the
    general market screeners (no exchange restriction)."""
    if min_market_cap is None:
        min_market_cap = config.DISCOVER_MIN_MARKET_CAP
    if max_market_cap is None:
        max_market_cap = config.DISCOVER_MAX_MARKET_CAP

    excluded = {str(t).upper().strip() for t in (exclude or [])}
    pool: list[str] = []
    seen = set(excluded)

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
