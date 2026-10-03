# Jev Decision-Logging & Evaluation Plan

> **Status:** Phases 1–3 implemented. Data collection is live (entry decisions
> and screen runs are logged on every screener run). Outcome resolution
> (`decisions.resolve_outcomes`) runs at app startup and via CLI; the evaluation
> report is exposed at `/api/evaluation` and the **Evaluate** tab. It stays
> near-empty until ~20 trading days of forward history accumulate.
>
> **Scope:** only the **entry** role is active now. The exit (`review_position`)
> and portfolio (`review_portfolio`) judgments were removed along with the
> paper-trading feature, so the exit/portfolio paths below are historical and not
> currently logged or evaluated.

Goal: make Jev *earn its place* by answering one measurable question —
**do Jev's entry verdicts (`buy_now`/`watch`/`avoid`) improve outcomes over
the rule-only momentum ranking?**

## Core design

Every Jev decision gets **logged with its baseline** at decision time. Later, we
compute the actual **forward outcome**, then compare "Jev-augmented" vs
"rule-only" on the same decisions.

Two things are essential:

1. **Log the baseline at decision time**, not reconstruct it later. For an entry,
   baseline = `momentum_score`; for an exit, baseline = the rule signal from
   `signals.evaluate` (HOLD/SELL). This gives a paired, apples-to-apples comparison.
2. **Compute outcomes from real price history** (yfinance), not from the live
   snapshot.

## New module: `trendfinder/decisions.py`

Owns the logging + outcome resolution. Uses SQLite (`data/decisions.db`).

### Schema

**`jev_decisions`** — one row per Jev call.

```sql
id            INTEGER PRIMARY KEY AUTOINCREMENT
kind          TEXT      -- 'entry' | 'exit' | 'portfolio'
created_at    TEXT
model         TEXT      -- JEV_MODEL used
ticker        TEXT      -- NULL for portfolio
position_id   INTEGER   -- NULL for entry/portfolio
state_json    TEXT      -- full state sent
answers_json  TEXT      -- raw Jev answers
extracted_json TEXT     -- verdict/action/scores (post-_extract_*)
baseline      TEXT      -- 'momentum_score:0.42' or 'rule:HOLD'
baseline_score REAL     -- numeric baseline (momentum score, or 1/0 for rule signal)
--- outcome columns (filled later) ---
forward_5d    REAL      -- % return 5 trading days after decision
forward_10d   REAL
forward_20d   REAL
outcome       REAL      -- primary outcome (see below)
correct       INTEGER   -- did Jev beat baseline? 1/0/NULL
resolved_at   TEXT
```

**`screen_runs`** — recommended; the cleanest way to test whether re-ranking
with Jev picks better names. One row per ticker per screener run.

```sql
id            INTEGER PRIMARY KEY AUTOINCREMENT
run_at        TEXT
ticker        TEXT
momentum_score REAL
final_score   REAL
jev_verdict   TEXT      -- buy_now / watch / avoid / NULL
rank_momentum INTEGER   -- rank within run by momentum_score
rank_final    INTEGER   -- rank within run by final_score
forward_20d   REAL      -- filled later
```

## Logging hooks

- `screener.py` — after each `assess_trend` answer, log the entry decision +
  `momentum_score` baseline. Also append to `screen_runs` for the full ranked list.

All wrapped in `try/except` so a logging failure **never** breaks the screener flow.

## Outcome resolution

A function `decisions.resolve_outcomes()` that:

- Finds unresolved decisions older than the horizon.
- Pulls the price history for each `ticker` (via `market_data`/`yfinance`, from
  decision date forward).
- Computes `forward_5d/10d/20d` and a primary `outcome`:
  - **Entry:** forward return of the ticker over 20 days.
  - **Exit:** if the position is closed, the realized P&L / post-exit return; if
    still open, the return from the decision price to the latest price.
  - **Portfolio:** change in total value after the advice (uses the snapshots table).
- Sets `correct` = whether Jev's call beat the baseline on that outcome.

Run automatically at startup and via a CLI: `.venv/bin/python -m trendfinder.decisions`.

## Evaluation: `trendfinder/evaluate.py`

A CLI + `/api/evaluation` endpoint + a new **"Evaluate"** tab in the UI. Produces
a small report:

- **Entry verdicts (`noul`/`choice`):** mean `forward_20d` for `buy_now`/`true`
  vs `avoid`/`false` decisions. Expectation: `buy_now` > `avoid`.
- **Ranking test (headline):** mean `forward_20d` of top-K picked by `final_score`
  vs top-K picked by `momentum_score`. Directly measures whether Jev's re-rank
  beats the rule baseline.
- **Exit calls:** among positions where rules said HOLD, does `action=exit` /
  `should_exit=true` predict worse forward returns than `action=hold`? i.e. did
  Jev dodge drawdowns?
- **Score calibration:** correlation between `risk_at_entry` / `setup_health`
  scores and forward returns (does a high risk score predict lower returns?).
- **Portfolio advice:** long-run portfolio return after `de_risk`/`rebalance`
  vs `hold`.

Each metric shows **N** and a note that small samples aren't conclusive (no
p-value over-claiming).

## Suggested sequencing

1. **Phase 1:** `decisions.py` schema + logging hooks (start *collecting*
   immediately). Urgent — you can't evaluate what you didn't log.
2. **Phase 2:** `resolve_outcomes()` + CLI to backfill outcomes for already-logged
   decisions.
3. **Phase 3:** `evaluate.py` + `/api/evaluation` + Evaluate tab.
4. **Phase 4:** (optional) extend the backtest to *include* Jev once there's enough
   logged data — but realistically this stays live-logging-only.

## Honest caveats

- **Sample size** will be tiny at first (a handful of runs). The report must show
  N and warn against over-reading.
- **Selection bias:** Jev only sees the top ~25 names, so we're measuring its
  ranking among already-momentum-strong names, not raw stock-picking.
- **Horizon choice matters:** Jev is asked about "next few weeks," so 20-day
  forward return is the primary metric; 5/10/20 give robustness.
- **Portfolio advice** will take many weeks to accumulate meaningfully.

## Open questions before implementing

1. **Storage:** keep the decision log in the existing `portfolio.db`, or a
   separate `data/decisions.db`? (**Decided:** a separate `data/decisions.db`, so
   it's cleanly resettable and not entangled with the account. The former
   `portfolio.db` from the removed paper-trading feature has been deleted.)
2. **Scope:** include the `screen_runs` ranking table, or just individual
   decisions for v1?
3. **UI:** a full **Evaluate** tab, or a CLI report first?
