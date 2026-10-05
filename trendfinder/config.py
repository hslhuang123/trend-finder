"""Configuration and small shared helpers for TrendFinder."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

JEV_MODEL = os.getenv("JEV_MODEL", "~typesafe/jev-latest")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
INITIAL_CASH = float(os.getenv("INITIAL_CASH", "100000"))
AUTO_PICK_COUNT = int(os.getenv("AUTO_PICK_COUNT", "2"))
DISCOVER_COUNT = int(os.getenv("DISCOVER_COUNT", "2"))
DISCOVER_MIN_MARKET_CAP = float(os.getenv("DISCOVER_MIN_MARKET_CAP", "2000000000"))
DISCOVER_MAX_MARKET_CAP = float(os.getenv("DISCOVER_MAX_MARKET_CAP", "10000000000"))


def has_jev() -> bool:
    """True when an OpenRouter key is available so Jev calls can be made."""
    return bool(OPENROUTER_API_KEY)


def set_openrouter_api_key(key: str | None) -> None:
    """Override the OpenRouter key at runtime (e.g. a key typed into the UI).

    Pass an empty/None value to fall back to whatever the environment provided.
    The key is only held in memory for the current process.
    """
    global OPENROUTER_API_KEY
    OPENROUTER_API_KEY = (key or "").strip()


def load_watchlist() -> list[str]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_PATH.read_text())
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("tickers", [])
    return [str(t).upper().strip() for t in data if str(t).strip()]


def save_watchlist(tickers: list[str]) -> list[str]:
    clean = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
    WATCHLIST_PATH.write_text(json.dumps({"tickers": clean}, indent=2) + "\n")
    return clean
