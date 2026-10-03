"""Company name + short description, fetched from yfinance and cached to disk."""
from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# Resolve a ticker symbol OR a company name to a ticker symbol.
#
# The user can type either "MSFT" or "Microsoft" / "Bell" / "Rogers" and we
# figure out the symbol. Common Canadian names are mapped explicitly (the app
# prefers the .TO listing for those); everything else is resolved via Yahoo's
# search, with a small scoring heuristic to pick the primary listing over CDRs,
# preferred shares, and other wrappers.
# ---------------------------------------------------------------------------

# company name (lowercased) -> (ticker, display name)
_NAME_ALIASES: dict[str, tuple[str, str]] = {
    "bell": ("BCE.TO", "BCE Inc. (Bell Canada)"),
    "bell canada": ("BCE.TO", "BCE Inc. (Bell Canada)"),
    "rogers": ("RCI-B.TO", "Rogers Communications Inc."),
    "rogers communications": ("RCI-B.TO", "Rogers Communications Inc."),
    "telus": ("T.TO", "TELUS Corporation"),
    "shopify": ("SHOP.TO", "Shopify Inc."),
    "rbc": ("RY.TO", "Royal Bank of Canada"),
    "royal bank": ("RY.TO", "Royal Bank of Canada"),
    "td bank": ("TD.TO", "Toronto-Dominion Bank"),
    "toronto-dominion": ("TD.TO", "Toronto-Dominion Bank"),
    "scotiabank": ("BNS.TO", "Bank of Nova Scotia"),
    "bank of montreal": ("BMO.TO", "Bank of Montreal"),
    "enbridge": ("ENB.TO", "Enbridge Inc."),
    "suncor": ("SU.TO", "Suncor Energy Inc."),
    "manulife": ("MFC.TO", "Manulife Financial Corporation"),
    "cn rail": ("CNR.TO", "Canadian National Railway"),
    "canadian national railway": ("CNR.TO", "Canadian National Railway"),
    "brookfield": ("BN.TO", "Brookfield Corporation"),
}

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,7}$")

# Strings in a quote's name that mark a wrapper/derivative listing we want to
# de-prioritise (CDRs, depositary receipts, preferred shares, leveraged ETFs...).
_WRAPPER_NAMES = ("CDR", "DEPOSITORY", "HEDGED", "PREFERRED", "PREF SHARES",
                  "WARRANT", "OPTION INCOME", "BULL", "BEAR")


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def _match_score(query: str, name: str, symbol: str, exch: str | None) -> int:
    """Score how well a search result matches a (lowercased) query."""
    nl = _norm(name)
    score = 0
    # An exact ticker match always wins over CDRs / DRs / preferred shares.
    if symbol.upper() == query.upper():
        score += 1000
    if nl == query:
        score += 100
    elif query in nl:
        score += 40
        if nl.startswith(query):
            score += 10
    elif any(query in _norm(w) for w in nl.split()):
        score += 20

    exch_s = str(exch or "").lower()
    # Prefer the company's home exchange (Toronto for Canadian names).
    if "toronto" in exch_s or "tsx" in exch_s:
        score += 15
    if symbol.endswith(".TO"):
        score += 10
    if exch_s in ("nyse", "nasdaq", "toronto"):
        score += 5

    # Penalise wrapper/derivative listings.
    name_upper = str(name or "").upper()
    for bad in _WRAPPER_NAMES:
        if bad in name_upper:
            score -= 30
            break
    # Penalise odd symbols (preferred classes, etc.) unless it's a .TO primary.
    if re.search(r"[-.]", symbol) and not symbol.endswith(".TO"):
        score -= 8
    return score


def _search_ticker(query: str) -> dict | None:
    """Search Yahoo for `query` and return the best EQUITY match."""
    try:
        result = yf.Search(query, max_results=15)
        quotes = result.quotes or []
    except Exception:  # noqa: BLE001 - search failures are non-fatal
        return None

    equities = [q for q in quotes if (q.get("quoteType") or "") == "EQUITY"]
    pool = equities or [q for q in quotes if q.get("symbol")]
    if not pool:
        return None

    ql = _norm(query)
    best: dict | None = None
    best_score = -1
    for q in pool:
        sym = q.get("symbol") or ""
        name = q.get("shortname") or q.get("longname") or ""
        score = _match_score(ql, name, sym, q.get("exchDisp"))
        if score > best_score:
            best_score = score
            best = q
    if best is None:
        return None
    return {
        "ticker": best["symbol"],
        "name": best.get("shortname") or best.get("longname") or "",
        "source": "search",
    }


def resolve(query: str) -> dict:
    """Resolve a ticker symbol or company name to a ticker symbol.

    Returns ``{"ticker", "name", "source"}`` where ``source`` is one of
    ``"alias"``, ``"ticker"``, or ``"search"``; or ``{}`` if nothing matches.
    """
    q = (query or "").strip()
    if not q:
        return {}

    # 1. Curated company-name aliases (case-insensitive).
    alias = _NAME_ALIASES.get(q.lower())
    if alias:
        return {"ticker": alias[0], "name": alias[1], "source": "alias"}

    # 2. If it looks like a ticker symbol, confirm it exists before using it.
    up = q.upper()
    if _SYMBOL_RE.match(up):
        found = _search_ticker(up)
        if found and found["ticker"].upper() == up:
            found["source"] = "ticker"
            return found

    # 3. Otherwise treat it as a company name and search.
    return _search_ticker(q) or {}
