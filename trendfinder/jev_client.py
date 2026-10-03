"""Jev (TypeSafe System One) client, called through OpenRouter's decisions API.

In TrendFinder, Jev provides the entry-side judgment on a candidate stock:
  * assess_trend - trend quality, entry risk, momentum sustainability,
                   buy candidacy, and an overall verdict (buy_now/watch/avoid).
"""
from __future__ import annotations

import requests

from . import config

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def _ask(state: dict, questions: dict) -> dict | None:
    """Send a state + typed questions to Jev. Returns the answers dict, or None."""
    if not config.has_jev():
        return None

    payload = {"model": config.JEV_MODEL, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
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


def assess_trend(state: dict) -> dict | None:
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
            "instructions": "Is this a reasonable long buy candidate for a momentum approach right now?",
            "criteria": {
                "true": "Shows a clear upward trend with manageable risk",
                "false": "Weak, too risky, or lacks a clear direction",
            },
        },
        "verdict": {
            "type": "choice",
            "instructions": "What is your overall verdict on this stock right now?",
            "criteria": {
                "buy_now": "A good moment to open a long position",
                "watch": "Interesting but not yet a clear buy",
                "avoid": "Unattractive or too risky right now",
            },
        },
    })



