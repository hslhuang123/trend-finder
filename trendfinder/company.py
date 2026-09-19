"""Company name + short description, fetched from yfinance and cached to disk."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

from . import config

CACHE_PATH = config.DATA_DIR / "companies.json"
DESCRIPTION_LIMIT = 240


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _shorten(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _fetch_one(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:  # noqa: BLE001 - network/parse failures are non-fatal
        info = {}

    name = info.get("longName") or info.get("shortName") or ""
    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    description = info.get("longBusinessSummary") or ""

    if not description:
        parts = [p for p in (sector, industry) if p]
        description = " · ".join(parts)

    return {
        "name": name,
        "description": _shorten(description),
        "sector": sector,
        "market_cap": info.get("marketCap"),
        "currency": info.get("currency") or "",
    }


def enrich(tickers: list[str]) -> dict[str, dict]:
    """Return {ticker: {name, description, sector}} filling the on-disk cache."""
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return {}

    cache = _load_cache()
    # Refetch entries that predate a newly added field (e.g. market_cap).
    missing = [t for t in tickers if t not in cache or "market_cap" not in cache[t]]

    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = list(pool.map(_fetch_one, missing))
        for ticker, profile in zip(missing, fetched):
            cache[ticker] = profile
        _save_cache(cache)

    return {
        t: cache.get(t, {"name": "", "description": "", "sector": "", "market_cap": None, "currency": ""})
        for t in tickers
    }
