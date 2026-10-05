"""Screener: rank the watchlist by momentum, enrich with Jev, auto-pick the best N,
and surface a couple of freshly-discovered 'surprise' tickers from the market.
"""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd

from . import company, config, decisions, discover, jev_client, market_data

# Jev's overall verdict shifts the final score the most.
VERDICT_BONUS = {"buy_now": 0.35, "watch": 0.0, "avoid": -0.45}


def compute_momentum_score(row: pd.Series) -> float:
    """A 0-centered composite of recent return, trend position, volume and RSI."""

    def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    score = 0.0
    score += clamp(row["change_5d_pct"] / 10.0) * 0.30
    score += clamp(row["above_ma20_pct"] / 5.0) * 0.25
    score += clamp((row["volume_ratio"] - 1.0) / 2.0) * 0.20
    score += clamp((row["rsi"] - 50.0) / 25.0) * 0.15
    score -= clamp(row["atr_pct"] / 10.0, 0.0, 1.0) * 0.10
    return round(score, 3)


def build_state(row: dict) -> dict:
    return {
        "ticker": row["ticker"],
        "price": row["price"],
        "change_1d_pct": row["change_1d_pct"],
        "change_5d_pct": row["change_5d_pct"],
        "above_ma20_pct": row["above_ma20_pct"],
        "above_ma50_pct": row["above_ma50_pct"],
        "atr_pct": row["atr_pct"],
        "volume_ratio": row["volume_ratio"],
        "rsi": row["rsi"],
    }


def _extract_entry(answers: dict) -> dict:
    return {
        "trend_quality": (answers.get("trend_quality") or {}).get("score"),
        "risk_at_entry": (answers.get("risk_at_entry") or {}).get("score"),
        "is_buy_candidate": (answers.get("is_buy_candidate") or {}).get("noul"),
        "verdict": (answers.get("verdict") or {}).get("choice"),
        "momentum_sustainability": (answers.get("momentum_sustainability") or {}).get("noul"),
    }


def _reconcile_answers(extracted: dict) -> dict:
    """Make `is_buy_candidate` and `verdict` agree with the quality/risk ratings.

    The model sometimes contradicts itself (e.g. 'buy candidate: yes' on a weak
    trend). This derives a single, consistent story from the actual ratings so the
    displayed Buy and Verdict can never conflict, and the score matches.
    """
    quality = extracted.get("trend_quality")
    risk = extracted.get("risk_at_entry")
    weak_trend = quality is not None and quality < 0.5
    high_risk = risk is not None and risk >= 1.5
    if weak_trend or high_risk:
        # Not a valid candidate: no candidate -> avoid.
        extracted["is_buy_candidate"] = False
        if extracted.get("verdict") in ("buy_now", "watch"):
            extracted["verdict"] = "avoid"
    else:
        # Sound trend, low/medium risk: it IS a candidate.
        extracted["is_buy_candidate"] = True
        if extracted.get("verdict") == "avoid":
            extracted["verdict"] = "watch"
    return extracted


def _final_score(momentum: float, jev: dict) -> float:
    return round(
        momentum
        + 0.15 * (jev["trend_quality"] or 0)
        - 0.15 * (jev["risk_at_entry"] or 0)
        + 0.25 * (jev["is_buy_candidate"] or 0)
        + 0.20 * (jev["momentum_sustainability"] or 0)
        + VERDICT_BONUS.get(jev["verdict"], 0.0),
        3,
    )


def screen(use_jev: bool = True, top_n: int = 25, jev_top: int = 25,
           discover_count: int | None = None,
           watchlist: list[str] | None = None,
           discover_buy_only: bool = False,
           api_key: str | None = None,
           consistent_questions: bool = False,
           reconcile_answers: bool = False) -> dict:
    if discover_count is None:
        discover_count = config.DISCOVER_COUNT

    # Resolve the OpenRouter key for this run. A caller (e.g. the Streamlit app)
    # can pass a per-session key; otherwise fall back to the environment key.
    effective_key = (api_key or config.OPENROUTER_API_KEY or "").strip()

    # Screen only the tickers we're asked about (a single typed ticker/name in
    # the Streamlit UI), or the persisted watchlist when none is supplied.
    if watchlist is None:
        watchlist = config.load_watchlist()
    else:
        watchlist = [str(t).upper().strip() for t in watchlist if str(t).strip()]

    # Discover a pool of 'surprise' candidates (never persisted).
    pool: list[str] = []
    if discover_count > 0:
        try:
            pool = discover.discover_candidates(
                limit=max(discover_count * 5, 12), exclude=watchlist
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[discover] failed: {exc}")
            pool = []

    tickers = watchlist + [t for t in pool if t not in watchlist]
    df = market_data.fetch_trend_data(tickers)

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "watchlist_size": len(watchlist),
        "scanned": 0,
        "jev_enabled": bool(use_jev and effective_key),
        "auto_pick_count": config.AUTO_PICK_COUNT,
        "discover_count": discover_count,
    }
    if df.empty:
        return {**meta, "picks": [], "discovered": [], "results": []}

    df["momentum_score"] = df.apply(compute_momentum_score, axis=1)
    df = df.sort_values("momentum_score", ascending=False).reset_index(drop=True)
    meta["scanned"] = len(df)

    # Ask Jev about the strongest candidates, concurrently.
    jev_by_ticker: dict[str, dict] = {}
    if meta["jev_enabled"]:
        states = [(r["ticker"], build_state(r), float(r["momentum_score"]))
                  for _, r in df.head(jev_top).iterrows()]
        with ThreadPoolExecutor(max_workers=6) as pool_exec:
            answers = list(pool_exec.map(
                lambda item: jev_client.assess_trend(
                    item[1], api_key=effective_key,
                    consistent=consistent_questions,
                ), states
            ))
        for (ticker, state, momentum), answer in zip(states, answers):
            if answer:
                extracted = _extract_entry(answer)
                if reconcile_answers:
                    extracted = _reconcile_answers(extracted)
                jev_by_ticker[ticker] = extracted
                decisions.log_entry(state, answer, extracted, ticker, momentum)

    results: list[dict] = []
    for _, row in df.head(top_n).iterrows():
        item = row.to_dict()
        item["momentum_score"] = round(float(item["momentum_score"]), 3)
        jev = jev_by_ticker.get(item["ticker"])
        item["jev"] = jev
        item["final_score"] = (
            _final_score(item["momentum_score"], jev) if jev else item["momentum_score"]
        )
        results.append(item)

    results.sort(key=lambda x: x["final_score"], reverse=True)

    # Surface the discovered candidates with the HIGHEST RETURNS, but pick
    # randomly from the top few so the surprises vary between runs. When
    # discover_buy_only is set, keep only names Jev rated "buy now".
    pool_set = set(pool)
    pool_results = [r for r in results if r["ticker"] in pool_set]
    if discover_buy_only:
        pool_results = [
            r for r in pool_results if (r.get("jev") or {}).get("verdict") == "buy_now"
        ]
    pool_results.sort(key=lambda r: r["change_5d_pct"], reverse=True)
    top_returns = pool_results[: max(discover_count * 3, 6)]
    random.shuffle(top_returns)
    discovered = [r["ticker"] for r in top_returns[:discover_count]]
    disc_set = set(discovered)
    results = [r for r in results if r["ticker"] not in pool_set or r["ticker"] in disc_set]
    for item in results:
        item["discovered"] = item["ticker"] in disc_set

    # Auto-pick the best names from the watchlist (never the surprise ones).
    watch_results = [r for r in results if not r["discovered"]]
    pick_count = max(0, min(config.AUTO_PICK_COUNT, len(watch_results)))
    picks = [r["ticker"] for r in watch_results[:pick_count]]
    for item in results:
        item["pick"] = item["ticker"] in picks

    # Attach company name + short description for the hover bubble.
    try:
        profiles = company.enrich([r["ticker"] for r in results])
    except Exception as exc:  # noqa: BLE001
        print(f"[company] enrichment failed: {exc}")
        profiles = {}
    for item in results:
        item["company"] = profiles.get(item["ticker"], {})

    # Log the full ranked output so we can later compare Jev re-ranking vs the
    # rule-only momentum ranking on the same names.
    try:
        run_at = meta["generated_at"]
        mom_rank = {
            idx: i + 1
            for i, (idx, _) in enumerate(
                sorted(enumerate(results), key=lambda x: x[1]["momentum_score"], reverse=True)
            )
        }
        for idx, item in enumerate(results):
            decisions.log_screen_run(
                run_at=run_at,
                ticker=item["ticker"],
                momentum_score=item["momentum_score"],
                final_score=item["final_score"],
                jev_verdict=(item.get("jev") or {}).get("verdict"),
                jev_enabled=meta["jev_enabled"],
                rank_momentum=mom_rank.get(idx),
                rank_final=idx + 1,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[decisions] screen_runs log failed: {exc}")

    return {**meta, "picks": picks, "discovered": discovered, "results": results}
