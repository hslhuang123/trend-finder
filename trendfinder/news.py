"""Recent company headlines from Google News RSS (no API key).

Used to give Jev the last week of news alongside the price indicators. Headlines
only (no article bodies), newest first. Yahoo's own news endpoints returned
nothing for the tickers we tried, so this is the free source that works for TSX
and US names alike.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

RSS_URL = "https://news.google.com/rss/search"
CACHE_TTL_SECONDS = 1800.0
MAX_TITLE = 160

_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}

# Quote / landing pages that Google lists as "news" but carry no information.
_NOISE = re.compile(
    r"stock price,|price: live|live chart|stock forecast|stock analysis\b|"
    r"quote (and|&) news|quote & history|options chain",
    re.IGNORECASE,
)
_CANADIAN_SUFFIXES = (".TO", ".V", ".NE", ".CN")


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:60]


def fetch(company_name: str, ticker: str, days: int = 7, limit: int = 10) -> list[dict] | None:
    """Headlines about a company from the last `days` days, newest first.

    Returns a list of ``{title, source, date, link}`` (empty when there is no news),
    or ``None`` when the lookup failed, so callers can tell "no news" from "unknown".
    """
    cache_key = (ticker.upper(), days)
    hit = _CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1][:limit]

    base = ticker.split(".")[0]
    name = " ".join((company_name or "").split())
    query = f'"{name}" {base}' if name else f'"{ticker}"'
    canadian = ticker.upper().endswith(_CANADIAN_SUFFIXES)
    params = {
        "q": f"{query} when:{days}d",
        "hl": "en-CA" if canadian else "en-US",
        "gl": "CA" if canadian else "US",
        "ceid": "CA:en" if canadian else "US:en",
    }
    try:
        resp = requests.get(
            RSS_URL + "?" + urllib.parse.urlencode(params),
            timeout=10, headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"[news] {ticker} lookup failed: {exc}")
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[dict] = []
    seen: set[str] = set()
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        source = (node.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if not title or published < cutoff or _NOISE.search(title):
            continue
        key = _key(title)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title[:MAX_TITLE],
            "source": source,
            "date": published.astimezone(timezone.utc).strftime("%Y-%m-%d"),
            "link": (node.findtext("link") or "").strip(),
            "_ts": published,
        })

    items.sort(key=lambda i: i["_ts"], reverse=True)
    result = [{k: v for k, v in i.items() if k != "_ts"} for i in items[:limit]]
    _CACHE[cache_key] = (time.monotonic(), result)
    return result


def as_lines(items: list[dict]) -> list[str]:
    """Compact ``date | source | title`` lines for the Jev state."""
    return [f"{i['date']} | {i['source']} | {i['title']}" for i in items]
