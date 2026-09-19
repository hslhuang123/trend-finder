"""Performance metrics from a daily equity curve, plus a buy-and-hold benchmark."""
from __future__ import annotations

import math
from datetime import datetime

import yfinance as yf


def _daily_returns(values: list[float]) -> list[float]:
    returns = []
    for prev, cur in zip(values, values[1:]):
        if prev:
            returns.append(cur / prev - 1)
    return returns


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return worst


def _cagr(values: list[float], days: int) -> float | None:
    if len(values) < 2 or values[0] <= 0 or days <= 0:
        return None
    years = days / 365.25
    if years <= 0:
        return None
    return (values[-1] / values[0]) ** (1 / years) - 1


def summarize(dates: list[str], values: list[float]) -> dict:
    """Compute risk/return statistics for an equity curve."""
    n = len(values)
    empty = {
        "points": n, "total_return_pct": None, "cagr_pct": None, "volatility_pct": None,
        "sharpe": None, "sortino": None, "max_drawdown_pct": None,
        "best_day_pct": None, "worst_day_pct": None,
    }
    if n < 2:
        return empty

    returns = _daily_returns(values)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((r - mean) ** 2 for r in returns) / len(returns) if returns else 0.0
    vol_daily = math.sqrt(variance)

    downside = [r for r in returns if r < 0]
    down_var = sum(r * r for r in downside) / len(downside) if downside else 0.0
    down_daily = math.sqrt(down_var)

    try:
        days = (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days
    except Exception:  # noqa: BLE001
        days = n - 1

    def pct(x: float | None) -> float | None:
        return None if x is None else round(x * 100, 2)

    annual = math.sqrt(252)
    return {
        "points": n,
        "start": dates[0],
        "end": dates[-1],
        "total_return_pct": pct(values[-1] / values[0] - 1),
        "cagr_pct": pct(_cagr(values, days)),
        "volatility_pct": pct(vol_daily * annual),
        "sharpe": round(mean / vol_daily * annual, 2) if vol_daily else None,
        "sortino": round(mean / down_daily * annual, 2) if down_daily else None,
        "max_drawdown_pct": pct(_max_drawdown(values)),
        "best_day_pct": pct(max(returns)) if returns else None,
        "worst_day_pct": pct(min(returns)) if returns else None,
    }


def benchmark(start_date: str, end_date: str, start_value: float,
              symbol: str = "SPY") -> dict | None:
    """Buy-and-hold return of `symbol` over the same window, same starting value."""
    try:
        data = yf.download(symbol, start=start_date, end=end_date, interval="1d",
                           progress=False, auto_adjust=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[benchmark] {symbol} failed: {exc}")
        return None
    if data is None or data.empty:
        return None

    close = data["Close"]
    if hasattr(close, "columns"):  # MultiIndex columns
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < 2:
        return None

    values = [float(c) / float(close.iloc[0]) * start_value for c in close]
    dates = [d.date().isoformat() for d in close.index]
    result = summarize(dates, values)
    result["symbol"] = symbol
    return result
