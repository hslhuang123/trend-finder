"""Historical backtester for the momentum strategy.

Replays the same momentum ranking the live screener uses over daily history,
applies entry/exit rules + trading costs, and produces an equity curve with
metrics vs a buy-and-hold benchmark.

Note: this is rule-based only — Jev is *not* replayed (we have no historical
decision data for it).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from . import config, market_data, metrics, screener

DEFAULT_PARAMS = {
    "years": 5,
    "top_k": 2,
    "rebalance_days": 5,
    "stop_loss_pct": 10.0,
    "take_profit_pct": 25.0,
    "trailing_stop_pct": None,
    "commission_bps": 5.0,
    "slippage_bps": 5.0,
    "benchmark": "SPY",
}


def _num(value, default=None):
    if value in (None, "", "null", "None"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev = close.shift()
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(window=window, min_periods=1).mean()


def _indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    out = pd.DataFrame(index=df.index)
    out["close"] = close
    ma20 = close.rolling(20).mean()
    mom_input = pd.DataFrame({
        "change_5d_pct": close.pct_change(5) * 100,
        "above_ma20_pct": (close / ma20 - 1) * 100,
        "volume_ratio": volume.rolling(5).mean() / volume.rolling(20).mean(),
        "rsi": _rsi(close),
        "atr_pct": _atr(high, low, close) / close * 100,
    })
    out["momentum"] = mom_input.apply(screener.compute_momentum_score, axis=1)
    return out


def _download(tickers: list[str], benchmark: str, start: date, end: date) -> dict[str, pd.DataFrame]:
    symbols = list(dict.fromkeys(list(tickers) + [benchmark]))
    data = yf.download(
        symbols, start=start.isoformat(), end=end.isoformat(), interval="1d",
        group_by="ticker", auto_adjust=True, progress=False, threads=True,
    )
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        df = market_data._slice(data, symbol)
        if df is None or df.empty:
            continue
        try:
            frames[symbol] = _indicator_frame(df)
        except Exception as exc:  # noqa: BLE001
            print(f"[backtest] indicators for {symbol} failed: {exc}")
    return frames


def run(tickers: list[str], params: dict | None = None) -> dict:
    raw = {**DEFAULT_PARAMS, **(params or {})}
    years = max(0.5, float(_num(raw["years"], 5)))
    top_k = max(1, int(_num(raw["top_k"], config.AUTO_PICK_COUNT)))
    rebalance_days = max(1, int(_num(raw["rebalance_days"], 5)))
    stop_loss_pct = _num(raw["stop_loss_pct"], 10.0)
    take_profit_pct = _num(raw["take_profit_pct"], 25.0)
    trailing_stop_pct = _num(raw["trailing_stop_pct"], None)
    commission_bps = float(_num(raw["commission_bps"], 5.0))
    slippage_bps = float(_num(raw["slippage_bps"], 5.0))
    benchmark = str(raw.get("benchmark") or "SPY").upper()
    cost_rate = (commission_bps + slippage_bps) / 10000.0
    initial_cash = config.INITIAL_CASH

    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers:
        return {"error": "no tickers in watchlist"}

    end = date.today()
    start = end - timedelta(days=int(years * 365) + 7)
    frames = _download(tickers, benchmark, start, end)

    tradable = [t for t in tickers if t in frames]
    if not tradable:
        return {"error": "no historical data for the watchlist"}

    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    for symbol in frames:
        frames[symbol] = frames[symbol].reindex(all_dates).ffill()

    close_lu = {t: frames[t]["close"].to_dict() for t in tradable}
    mom_lu = {t: frames[t]["momentum"].to_dict() for t in tradable}
    bench_lu = frames[benchmark]["close"].to_dict() if benchmark in frames else {}

    cash = initial_cash
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    series: list[dict] = []

    def price(ticker: str, day) -> float | None:
        value = close_lu.get(ticker, {}).get(day)
        return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)

    def holdings_value(day) -> float:
        total = 0.0
        for ticker, pos in positions.items():
            px = price(ticker, day)
            if px is not None:
                total += pos["shares"] * px
        return total

    def close_position(ticker: str, px: float, reason: str, day) -> None:
        nonlocal cash
        pos = positions.pop(ticker)
        proceeds = pos["shares"] * px * (1 - cost_rate)
        cash += proceeds
        trades.append({
            "date": day.isoformat(), "ticker": ticker, "side": "sell", "reason": reason,
            "price": round(px, 2), "shares": round(pos["shares"], 4),
            "value": round(proceeds, 2),
            "pnl": round((px * (1 - cost_rate) - pos["entry_price"] * (1 + cost_rate)) * pos["shares"], 2),
        })

    for i, day in enumerate(all_dates):
        # 1) daily stop / target checks
        for ticker in list(positions):
            px = price(ticker, day)
            if px is None:
                continue
            pos = positions[ticker]
            pos["peak"] = max(pos["peak"], px)
            ret = (px - pos["entry_price"]) / pos["entry_price"] * 100
            reason = None
            if stop_loss_pct and ret <= -abs(stop_loss_pct):
                reason = "stop-loss"
            elif take_profit_pct and ret >= abs(take_profit_pct):
                reason = "take-profit"
            elif trailing_stop_pct:
                drawdown = (px - pos["peak"]) / pos["peak"] * 100
                if drawdown <= -abs(trailing_stop_pct):
                    reason = "trailing-stop"
            if reason:
                close_position(ticker, px, reason, day)

        # 2) rebalance
        if i % rebalance_days == 0:
            scores = {}
            for ticker in tradable:
                m = mom_lu[ticker].get(day)
                if m is not None and not (isinstance(m, float) and math.isnan(m)):
                    scores[ticker] = float(m)
            top = sorted(scores, key=scores.get, reverse=True)[:top_k]

            for ticker in list(positions):
                if ticker not in top:
                    px = price(ticker, day)
                    if px is not None:
                        close_position(ticker, px, "rebalance", day)

            equity = cash + holdings_value(day)
            target = equity / top_k if top_k else 0.0
            for ticker in top:
                if ticker in positions:
                    continue
                px = price(ticker, day)
                if px is None or px <= 0:
                    continue
                budget = min(target, cash)
                shares = budget / (px * (1 + cost_rate))
                if shares <= 0:
                    continue
                cost = shares * px
                fee = cost * cost_rate
                if cost + fee > cash:
                    continue
                cash -= cost + fee
                positions[ticker] = {
                    "shares": shares, "entry_price": px, "entry_date": day, "peak": px,
                }
                trades.append({
                    "date": day.isoformat(), "ticker": ticker, "side": "buy", "reason": "entry",
                    "price": round(px, 2), "shares": round(shares, 4),
                    "value": round(cost + fee, 2), "pnl": None,
                })

        hv = holdings_value(day)
        series.append({
            "date": day.isoformat(),
            "value": round(cash + hv, 2),
            "cash": round(cash, 2),
            "holdings": round(hv, 2),
        })

    for row in series:
        row["date"] = row["date"].split("T")[0]
    values = [p["value"] for p in series]
    dates_iso = [p["date"] for p in series]
    summary = metrics.summarize(dates_iso, values)

    benchmark_series: list[dict] = []
    if bench_lu:
        first = None
        for day in all_dates:
            raw_px = bench_lu.get(day)
            if raw_px is None or (isinstance(raw_px, float) and math.isnan(raw_px)):
                continue
            if first is None:
                first = float(raw_px)
            benchmark_series.append({"date": day.isoformat(), "value": round(initial_cash * float(raw_px) / first, 2)})
    for row in benchmark_series:
        row["date"] = row["date"].split("T")[0]
    benchmark_metrics = None
    if len(benchmark_series) >= 2:
        benchmark_metrics = metrics.summarize(
            [b["date"] for b in benchmark_series], [b["value"] for b in benchmark_series]
        )
        benchmark_metrics["symbol"] = benchmark

    for row in trades:
        row["date"] = row["date"].split("T")[0]

    return {
        "params": {
            "years": years, "top_k": top_k, "rebalance_days": rebalance_days,
            "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct,
            "trailing_stop_pct": trailing_stop_pct, "commission_bps": commission_bps,
            "slippage_bps": slippage_bps, "benchmark": benchmark,
        },
        "start": dates_iso[0] if dates_iso else None,
        "end": dates_iso[-1] if dates_iso else None,
        "final_value": values[-1] if values else initial_cash,
        "metrics": summary,
        "benchmark": benchmark_metrics,
        "series": series,
        "benchmark_series": benchmark_series,
        "trades": trades,
        "trades_count": len(trades),
        "tickers": tradable,
        "initial_cash": initial_cash,
    }


if __name__ == "__main__":
    import json

    result = run(config.load_watchlist(), {"years": 5})
    printable = {k: v for k, v in result.items() if k not in ("series", "benchmark_series", "trades")}
    print(json.dumps(printable, indent=2, default=str))
