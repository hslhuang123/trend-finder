"""Decision logging for Jev.

Every Jev call is captured *with its rule-only baseline* at decision time, so we
can later measure whether Jev's judgments actually beat the baseline. Data is kept
in a separate SQLite DB (data/decisions.db) so it can be reset independently of
the paper-trading account.

Logging is intentionally best-effort: any failure is swallowed and reported to
stderr so it never breaks the screener flow.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config, market_data

DECISIONS_DB = config.DATA_DIR / "decisions.db"

_db_ready = False


@contextmanager
def _conn():
    conn = sqlite3.connect(DECISIONS_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the decision tables if they don't exist (idempotent)."""
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jev_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                model TEXT,
                ticker TEXT,
                position_id INTEGER,
                state_json TEXT,
                answers_json TEXT,
                extracted_json TEXT,
                baseline TEXT,
                baseline_score REAL,
                forward_5d REAL,
                forward_10d REAL,
                forward_20d REAL,
                outcome REAL,
                correct INTEGER,
                resolved_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS screen_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                momentum_score REAL,
                final_score REAL,
                jev_verdict TEXT,
                jev_enabled INTEGER,
                rank_momentum INTEGER,
                rank_final INTEGER,
                forward_20d REAL
            )"""
        )


def _ensure_db() -> None:
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _insert_decision(conn, *, kind: str, ticker: str | None = None,
                     position_id: int | None = None, state: dict | None = None,
                     answers: dict | None = None, extracted: dict | None = None,
                     baseline: str | None = None,
                     baseline_score: float | None = None) -> None:
    conn.execute(
        """INSERT INTO jev_decisions
           (kind, created_at, model, ticker, position_id, state_json,
            answers_json, extracted_json, baseline, baseline_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            kind, _now(), config.JEV_MODEL, ticker, position_id,
            json.dumps(state) if state is not None else None,
            json.dumps(answers) if answers is not None else None,
            json.dumps(extracted) if extracted is not None else None,
            baseline, baseline_score,
        ),
    )


def log_entry(state: dict, answers: dict, extracted: dict, ticker: str,
              momentum_score: float) -> None:
    """Log an entry-side decision (assess_trend)."""
    try:
        _ensure_db()
        with _conn() as conn:
            _insert_decision(
                conn, kind="entry", ticker=ticker, state=state,
                answers=answers, extracted=extracted,
                baseline=f"momentum_score:{momentum_score}",
                baseline_score=float(momentum_score),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[decisions] log_entry failed: {exc}")


def log_screen_run(run_at: str, ticker: str, momentum_score: float,
                   final_score: float, jev_verdict: str | None,
                   jev_enabled: bool, rank_momentum: int,
                   rank_final: int) -> None:
    """Log one row of the full ranked screener output for a run."""
    try:
        _ensure_db()
        with _conn() as conn:
            conn.execute(
                """INSERT INTO screen_runs
                   (run_at, ticker, momentum_score, final_score, jev_verdict,
                    jev_enabled, rank_momentum, rank_final)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_at, ticker, momentum_score, final_score, jev_verdict,
                 1 if jev_enabled else 0, rank_momentum, rank_final),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[decisions] log_screen_run failed: {exc}")


# ---------------------------------------------------------------------------
# Outcome resolution (Phase 2)
# ---------------------------------------------------------------------------

# Minimum age (calendar days) before a decision can have a 20-trading-day
# forward return. 20 trading days ~= 28 calendar days.
MIN_AGE_DAYS = 28


def _period_for(age_days: int) -> str:
    """Pick a yfinance period that covers `age_days` back plus ~20 trading days."""
    days = age_days + 45
    if days <= 60:
        return "3mo"
    if days <= 180:
        return "6mo"
    if days <= 365:
        return "1y"
    return "2y"


def _forward_returns(ticker: str, created_at: str) -> dict | None:
    """Return {forward_5d, forward_10d, forward_20d} % returns from the decision
    date, or None when the series can't be resolved (e.g. not enough history).

    The reference price is the close on the first trading day at/after the
    decision timestamp; each forward return is that day's close relative to it.
    """
    decision_date = (created_at or "")[:10]
    if not decision_date or not ticker:
        return None

    try:
        age_days = (datetime.now() - datetime.fromisoformat(created_at)).days
    except (ValueError, TypeError):
        age_days = 0
    # Too fresh to have any forward returns yet — skip without hitting yfinance.
    if age_days < MIN_AGE_DAYS:
        return None
    period = _period_for(max(age_days, 0))

    points = market_data.fetch_price_history(ticker, period=period, interval="1d")
    if not points:
        return None

    dates = [p["date"][:10] for p in points]
    prices = [p["price"] for p in points]
    ref_idx = next((i for i, d in enumerate(dates) if d >= decision_date), None)
    if ref_idx is None:
        return None
    ref_price = prices[ref_idx]
    if not ref_price:
        return None

    out: dict = {}
    for days in (5, 10, 20):
        j = ref_idx + days
        if j < len(prices) and prices[j]:
            out[f"forward_{days}d"] = round((prices[j] / ref_price - 1) * 100, 3)
        else:
            out[f"forward_{days}d"] = None
    return out


def _entry_correct(extracted: dict | None, fwd20: float) -> int | None:
    """Did Jev's verdict direction match the realized 20-day return?

    buy_now -> expected positive; avoid -> expected negative; watch is neutral
    (None, since it's an explicit non-commitment).
    """
    verdict = (extracted or {}).get("verdict")
    if verdict == "buy_now":
        return 1 if fwd20 > 0 else 0
    if verdict == "avoid":
        return 1 if fwd20 < 0 else 0
    return None


def resolve_outcomes() -> dict:
    """Backfill forward-return outcomes for unresolved entry decisions and screen
    runs. Best-effort: failures are counted and never raised.

    Returns a summary dict for the caller / CLI.
    """
    summary = {"entries_resolved": 0, "screen_runs_resolved": 0,
               "skipped": 0, "errors": 0}
    try:
        _ensure_db()
    except Exception as exc:  # noqa: BLE001
        print(f"[decisions] resolve_outcomes: {exc}")
        return summary

    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, created_at, extracted_json FROM jev_decisions "
            "WHERE kind='entry' AND forward_20d IS NULL"
        ).fetchall()
        for row in rows:
            if not row["ticker"]:
                summary["skipped"] += 1
                continue
            try:
                fr = _forward_returns(row["ticker"], row["created_at"])
            except Exception as exc:  # noqa: BLE001
                print(f"[decisions] resolve {row['ticker']} failed: {exc}")
                summary["errors"] += 1
                continue
            if not fr or fr["forward_20d"] is None:
                summary["skipped"] += 1
                continue

            try:
                extracted = json.loads(row["extracted_json"]) if row["extracted_json"] else {}
            except (TypeError, json.JSONDecodeError):
                extracted = {}
            correct = _entry_correct(extracted, fr["forward_20d"])
            conn.execute(
                """UPDATE jev_decisions
                   SET forward_5d=?, forward_10d=?, forward_20d=?, outcome=?,
                       correct=?, resolved_at=?
                   WHERE id=?""",
                (fr["forward_5d"], fr["forward_10d"], fr["forward_20d"],
                 fr["forward_20d"], correct, _now(), row["id"]),
            )
            summary["entries_resolved"] += 1

        srows = conn.execute(
            "SELECT id, ticker, run_at FROM screen_runs WHERE forward_20d IS NULL"
        ).fetchall()
        for row in srows:
            if not row["ticker"]:
                summary["skipped"] += 1
                continue
            try:
                fr = _forward_returns(row["ticker"], row["run_at"])
            except Exception as exc:  # noqa: BLE001
                print(f"[decisions] resolve screen {row['ticker']} failed: {exc}")
                summary["errors"] += 1
                continue
            if not fr or fr["forward_20d"] is None:
                summary["skipped"] += 1
                continue
            conn.execute(
                "UPDATE screen_runs SET forward_20d=? WHERE id=?",
                (fr["forward_20d"], row["id"]),
            )
            summary["screen_runs_resolved"] += 1

    return summary


if __name__ == "__main__":
    init_db()
    print(f"Initialized decision log at {DECISIONS_DB}")
    summary = resolve_outcomes()
    print("Outcome resolution:", summary)
