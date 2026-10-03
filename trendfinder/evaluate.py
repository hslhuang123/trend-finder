"""Evaluate whether Jev's judgments actually beat the rule-only baseline.

Reads the decision log (`data/decisions.db`, populated by ``decisions.py``) and
produces a small, honest report. Every metric carries its sample size (N) and the
report explicitly warns against over-reading small samples.

The headline question: does re-ranking the screener with Jev's verdicts pick names
with better forward returns than ranking by the rule-only momentum score alone?
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime

from . import config

DECISIONS_DB = config.DATA_DIR / "decisions.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DECISIONS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _mean(vals: list[float | None]) -> float | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


def _count(vals: list[float | None]) -> int:
    return len([v for v in vals if v is not None])


def _corr(xs: list[float | None], ys: list[float | None]) -> float | None:
    """Pearson correlation over paired non-null values (None if <3 pairs)."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx = math.sqrt(sum((p[0] - mx) ** 2 for p in pairs))
    dy = math.sqrt(sum((p[1] - my) ** 2 for p in pairs))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def _extracted(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["extracted_json"]) if row["extracted_json"] else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _entry_metrics() -> dict:
    """Mean forward_20d by Jev's verdict and by the buy-candidate flag."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT extracted_json, forward_20d FROM jev_decisions "
            "WHERE kind='entry' AND forward_20d IS NOT NULL"
        ).fetchall()

    verdict_buckets: dict[str, list[float | None]] = {"buy_now": [], "watch": [], "avoid": []}
    buy_buckets: dict[str, list[float | None]] = {"true": [], "false": []}
    for row in rows:
        extracted = _extracted(row)
        verdict = extracted.get("verdict")
        if verdict in verdict_buckets:
            verdict_buckets[verdict].append(row["forward_20d"])
        buy = extracted.get("is_buy_candidate")
        if isinstance(buy, bool) or buy in (True, False, "true", "false"):
            key = "true" if buy in (True, "true") else "false"
            buy_buckets[key].append(row["forward_20d"])

    verdicts = []
    for label, vals in verdict_buckets.items():
        verdicts.append({
            "label": label,
            "mean_forward_20d": _mean(vals),
            "n": _count(vals),
        })

    buy_candidate = []
    for label, vals in buy_buckets.items():
        buy_candidate.append({
            "label": label,
            "mean_forward_20d": _mean(vals),
            "n": _count(vals),
        })

    return {"verdict": verdicts, "is_buy_candidate": buy_candidate}


def _ranking_metrics(top_k: int) -> dict:
    """Compare top-K by final_score (Jev re-ranked) vs by momentum_score (rule-only)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT run_at, ticker, momentum_score, final_score, forward_20d "
            "FROM screen_runs WHERE forward_20d IS NOT NULL"
        ).fetchall()

    runs: dict[str, list[dict]] = {}
    for row in rows:
        runs.setdefault(row["run_at"], []).append(dict(row))

    per_run: list[dict] = []
    all_final: list[float | None] = []
    all_momentum: list[float | None] = []

    for run_at, items in runs.items():
        k = min(top_k, len(items))
        if k <= 0:
            continue
        by_final = sorted(items, key=lambda r: r["final_score"], reverse=True)[:k]
        by_momentum = sorted(items, key=lambda r: r["momentum_score"], reverse=True)[:k]
        fwd_final = [r["forward_20d"] for r in by_final]
        fwd_momentum = [r["forward_20d"] for r in by_momentum]
        final_mean = _mean(fwd_final)
        momentum_mean = _mean(fwd_momentum)
        all_final.extend(fwd_final)
        all_momentum.extend(fwd_momentum)
        per_run.append({
            "run_at": run_at,
            "k": k,
            "final_mean": final_mean,
            "momentum_mean": momentum_mean,
            "diff": round(final_mean - momentum_mean, 3) if (final_mean is not None and momentum_mean is not None) else None,
        })

    return {
        "runs": per_run,
        "summary": {
            "final_mean": _mean(all_final),
            "momentum_mean": _mean(all_momentum),
            "final_n": _count(all_final),
            "momentum_n": _count(all_momentum),
            "diff": (round(_mean(all_final) - _mean(all_momentum), 3)
                     if _mean(all_final) is not None and _mean(all_momentum) is not None else None),
        },
    }


def _calibration() -> dict:
    """Correlation between Jev's score answers and realized forward returns."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT extracted_json, forward_20d FROM jev_decisions "
            "WHERE kind='entry' AND forward_20d IS NOT NULL"
        ).fetchall()

    fwd: list[float | None] = []
    risk: list[float | None] = []
    quality: list[float | None] = []
    sustainability: list[bool | None] = []
    for row in rows:
        extracted = _extracted(row)
        fwd.append(row["forward_20d"])
        risk.append(extracted.get("risk_at_entry"))
        quality.append(extracted.get("trend_quality"))
        sustainability.append(extracted.get("momentum_sustainability"))

    def bucket(series: list[float | None], name: str) -> dict:
        return {
            "field": name,
            "corr": _corr(series, fwd),
            "n": _count(series),
        }

    return {
        "risk_at_entry": bucket(risk, "risk_at_entry"),
        "trend_quality": bucket(quality, "trend_quality"),
        "momentum_sustainability": bucket(
            [1.0 if v is True else (0.0 if v is False else None) for v in sustainability],
            "momentum_sustainability",
        ),
    }


def evaluate(top_k: int | None = None) -> dict:
    """Produce the evaluation report. Never raises; degrades to empty metrics."""
    top_k = top_k or config.AUTO_PICK_COUNT

    overview: dict = {}
    try:
        with _conn() as conn:
            overview["total_entries"] = conn.execute(
                "SELECT COUNT(*) FROM jev_decisions WHERE kind='entry'"
            ).fetchone()[0]
            overview["resolved_entries"] = conn.execute(
                "SELECT COUNT(*) FROM jev_decisions WHERE kind='entry' AND forward_20d IS NOT NULL"
            ).fetchone()[0]
            overview["total_screen_runs"] = conn.execute(
                "SELECT COUNT(*) FROM screen_runs"
            ).fetchone()[0]
            overview["resolved_screen_runs"] = conn.execute(
                "SELECT COUNT(*) FROM screen_runs WHERE forward_20d IS NOT NULL"
            ).fetchone()[0]
            overview["auto_pick_count"] = config.AUTO_PICK_COUNT
            row = conn.execute(
                "SELECT MIN(created_at), MAX(created_at) FROM jev_decisions"
            ).fetchone()
            overview["first_decision"] = row[0]
            overview["last_decision"] = row[1]
    except Exception as exc:  # noqa: BLE001
        overview = {"error": str(exc)}

    try:
        entry_metrics = _entry_metrics()
    except Exception as exc:  # noqa: BLE001
        entry_metrics = {"verdict": [], "is_buy_candidate": [], "error": str(exc)}

    try:
        ranking = _ranking_metrics(top_k)
    except Exception as exc:  # noqa: BLE001
        ranking = {"runs": [], "summary": {}, "error": str(exc)}

    try:
        calibration = _calibration()
    except Exception as exc:  # noqa: BLE001
        calibration = {"error": str(exc)}

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top_k": top_k,
        "overview": overview,
        "entry_verdicts": entry_metrics,
        "ranking": ranking,
        "calibration": calibration,
        "caveats": [
            "Sample sizes are small and grow slowly — a handful of runs is not "
            "statistically meaningful.",
            "Jev only sees the top ~25 momentum names, so this measures its "
            "ranking among already-strong names, not raw stock-picking.",
            "Forward returns are measured over ~20 trading days; the 5/10/20-day "
            "horizons give robustness but the primary metric is the 20-day return.",
            "Prices are delayed and free; missing data means a decision may stay "
            "unresolved until enough history exists.",
        ],
    }


if __name__ == "__main__":
    import sys
    report = evaluate()
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0)
