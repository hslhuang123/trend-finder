"""Jev (TypeSafe System One) client, called through OpenRouter's decisions API.

In TrendFinder, Jev provides the entry-side judgment on a candidate stock:
  * assess_trend - trend quality, entry risk, momentum sustainability,
                   buy candidacy, and an overall verdict (buy_now/watch/avoid).
"""
from __future__ import annotations

import requests

from . import config

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def _ask(state: dict, questions: dict, api_key: str | None = None) -> dict | None:
    """Send a state + typed questions to Jev. Returns the answers dict, or None.

    `api_key` is resolved per call (falling back to the configured environment
    key) so a caller can supply a per-session key without mutating any global.
    """
    key = (api_key or config.OPENROUTER_API_KEY or "").strip()
    if not key:
        return None

    payload = {"model": config.JEV_MODEL, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(DECISIONS_URL, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"[jev] request failed: {exc}")
        return None

    if isinstance(data, dict) and "answers" in data:
        return data["answers"]
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        if "answers" in data["data"]:
            return data["data"]["answers"]
    return data if isinstance(data, dict) else None


def assess_trend(state: dict, api_key: str | None = None) -> dict | None:
    """Entry-side: is this a good stock to buy right now?"""
    return _ask(state, {
        "trend_quality": {
            "type": "score",
            "instructions": "Rate the strength and clarity of the current price trend.",
            "criteria": [
                "Weak: choppy or no clear direction",
                "Moderate: a trend with some concerns",
                "Strong: a clear, sustained trend with momentum",
            ],
        },
        "risk_at_entry": {
            "type": "score",
            "instructions": "Rate the risk of entering a long position at the current price.",
            "criteria": [
                "Low: clean, well-supported setup",
                "Medium: some chop or extension",
                "High: extended, volatile, or poorly supported",
            ],
        },
        "momentum_sustainability": {
            "type": "noul",
            "instructions": "Is the current upward momentum likely to persist over the next few weeks?",
            "criteria": {
                "true": "Trend and volume suggest continuation",
                "false": "Momentum looks tired, extended, or likely to reverse",
            },
        },
        "is_buy_candidate": {
            "type": "noul",
            "instructions": (
                "First decide whether this stock is a valid long buy candidate at "
                "all: answer true if the trend is sound and entry risk is low or "
                "medium; answer false if entry risk is high or the trend is weak. "
                "Your verdict below must agree with this answer."
            ),
            "criteria": {
                "true": "Sound trend and low/medium risk — a valid candidate",
                "false": "High entry risk, or a weak/unclear trend",
            },
        },
        "verdict": {
            "type": "choice",
            "instructions": (
                "Your overall call for this stock right now, and it must agree with "
                "is_buy_candidate: if is_buy_candidate is false, choose 'avoid'; if "
                "it is true, choose 'buy_now' for a good entry now, otherwise 'watch'."
            ),
            "criteria": {
                "buy_now": "A valid candidate and a good moment to open a long position",
                "watch": "A valid candidate, but not yet a clear buy or good entry",
                "avoid": "Not a valid candidate — high risk or weak trend (is_buy_candidate is false)",
            },
        },
    }, api_key=api_key)



