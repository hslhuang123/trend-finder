# Jev States & Questions

This document explains how the app talks to **Jev** (the AI judgment layer). For each
decision, the app sends Jev two things:

1. **The state** — the facts about the stock.
2. **The questions** — what we want Jev's opinion on.

Jev returns structured answers, and the app blends them into its own scoring as a
**second opinion** (it never places trades by itself).

---

## Plain-English overview

The app asks Jev in one situation:

1. **Should I buy this stock?** — the app sends the stock's current facts
   (price, momentum, volatility, etc.) and asks whether it's a good buy.

In short: Jev gets a **snapshot of the stock** plus a small set of
multiple-choice / rating questions, and its answers nudge the screener's ranking
on top of the app's own momentum rules.

---

## Entry judgment — `assess_trend`

**State** built in `trendfinder/screener.py:33` (`build_state`):

```python
{
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
```

**Questions** defined in `trendfinder/jev_client.py:43` (`assess_trend`):

| Question | Type | Criteria |
|---|---|---|
| `trend_quality` | score | Weak: choppy/no direction · Moderate: trend w/ concerns · Strong: clear sustained trend w/ momentum |
| `risk_at_entry` | score | Low: clean supported setup · Medium: chop/extension · High: extended/volatile/poorly supported |
| `momentum_sustainability` | noul | true: trend+volume suggest continuation · false: momentum tired/extended/likely to reverse |
| `is_buy_candidate` | noul | true: sound trend + low/medium risk · false: high risk or weak trend |
| `verdict` | choice | `buy_now` / `watch` / `avoid` |

**Consistency rule (Streamlit app only):** when the screener is called with
`consistent_questions=True` **and** `reconcile_answers=True` (the Streamlit app
does both), `is_buy_candidate` and `verdict` are cross-checked and then reconciled
from the Quality/Risk ratings so they cannot contradict. Jev first decides whether
the stock is a valid candidate (trend sound, risk low/medium). Then: if it is
**not** a candidate, the verdict is `avoid`; if it **is**, the verdict is `buy_now`
(good entry now) or `watch` (candidate, but not a clear buy yet). If Jev answers
inconsistently (e.g. "buy candidate: yes" on a weak trend), the app overrides it
to match the Quality/Risk ratings. The default (used by the Flask app) keeps the
original, independent questions and raw answers, so the Flask behaviour is
unchanged.

## News (Streamlit app, on demand)

When *Include news from the past 7 days* is ticked in the **AI analysis** section,
`screener.analyze_rows` first fetches headlines with `trendfinder/news.py`
(Google News RSS, no key; up to 10 from the last 7 days, newest first, quote and
options-chain pages dropped, cached ~30 min) and adds them to the state:

```python
state["news"] = ["2026-10-22 | Seeking Alpha | Thomson Reuters climbs 7%, ...", ...]
```

An empty list means "looked, found none". If the lookup fails the `news` key is
left out entirely, so Jev is asked the normal five questions and the UI shows
*unavailable* instead of claiming there was no news.

With `news` present, three questions are added and the `verdict` instructions also
tell Jev to weigh the headlines:

| Question | Type | Criteria |
|---|---|---|
| `news_sentiment` | score | Negative: mostly bad news · Neutral/mixed: little or offsetting · Positive: mostly good news |
| `news_catalyst` | choice | `none` / `positive` / `negative` (a specific event such as earnings, downgrade, lawsuit, contract) |
| `news_explains_move` | noul | true: a headline plausibly explains the recent move · false: unexplained or no headlines |

The headlines are third-party text, so the `news_sentiment` instructions tell Jev to
treat them as information only and ignore any instructions inside them.

**Scoring:** `news_sentiment` (0-2, 1 = neutral) adds `0.15 × (sentiment − 1)` to
`final_score` (±0.15). In `_reconcile_answers`, a `negative` catalyst turns a
`buy_now` verdict into `watch`. Decision-log rows record `news_used` and
`news_count` so Evaluate can separate news-aware calls from earlier ones. The
Flask app's automatic path never sends news.

---

## Summary

- **1 role** — entry judgment, with its own state shape and question set (plus optional news questions).
- **Question types used:** `score` (rating), `noul` (boolean), `choice` (enum).
- All requests go through the single `_ask()` helper (`trendfinder/jev_client.py:16`)
  → POST to `https://openrouter.ai/api/alpha/decisions` with `{model, state, questions}`.
- Entry answers are blended into `final_score` (`_final_score`, `screener.py:57`),
  and every call is logged to `data/decisions.db` so the **Evaluate** tab can later
  measure whether Jev's judgments beat the rule-only momentum ranking.
