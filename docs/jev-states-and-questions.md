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
`consistent_questions=True` (the Streamlit app does this), `is_buy_candidate` and
`verdict` are cross-checked so they cannot contradict. Jev first decides whether
the stock is a valid candidate (trend sound, risk low/medium). Then: if it is
**not** a candidate, the verdict must be `avoid`; if it **is**, the verdict is
`buy_now` (good entry now) or `watch` (candidate, but not a clear buy yet). The
default (used by the Flask app) keeps the original, independent questions, so the
Flask behaviour is unchanged.

---

## Summary

- **1 role** — entry judgment, with its own state shape and question set.
- **Question types used:** `score` (rating), `noul` (boolean), `choice` (enum).
- All requests go through the single `_ask()` helper (`trendfinder/jev_client.py:16`)
  → POST to `https://openrouter.ai/api/alpha/decisions` with `{model, state, questions}`.
- Entry answers are blended into `final_score` (`_final_score`, `screener.py:57`),
  and every call is logged to `data/decisions.db` so the **Evaluate** tab can later
  measure whether Jev's judgments beat the rule-only momentum ranking.
