"""Market data fetching and technical indicators via yfinance."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import yfinance as yf

_FX_CACHE: dict[tuple[str, str], tuple[float, float]] = {}
_FX_TTL_SECONDS = 600.0

TREND_COLUMNS = [
    "ticker", "price", "change_1d_pct", "change_5d_pct",
    "ma20", "ma50", "above_ma20_pct", "above_ma50_pct",
    "atr_pct", "volume_ratio", "rsi",
]


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift()
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=window, min_periods=1).mean()


def _slice(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Return the per-ticker frame from a yfinance download (single or multi)."""
    if data is None or data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        if ticker not in data.columns.get_level_values(0):
            return None
        return data[ticker]
    return data


def fetch_trend_data(tickers: list[str], period: str = "6mo") -> pd.DataFrame:
    """Return one row of trend indicators per ticker. Bad tickers are skipped."""
    tickers = [t for t in tickers if t]
    if not tickers:
        return pd.DataFrame(columns=TREND_COLUMNS)

    data = yf.download(
        tickers, period=period, interval="1d", group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )

    rows: list[dict] = []
    for t in tickers:
        df = _slice(data, t)
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["Close"])
        if len(df) < 21:
            continue

        close = df["Close"]
        latest = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        if prev == 0 or latest == 0:
            continue

        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50_series = close.rolling(50).mean().iloc[-1]
        ma50 = float(ma50_series) if not np.isnan(ma50_series) else float(close.mean())

        change_1d = (latest - prev) / prev * 100
        change_5d = (
            (latest - float(close.iloc[-6])) / float(close.iloc[-6]) * 100
            if len(close) >= 6 else float("nan")
        )

        atr = float(_atr(df).iloc[-1])
        volume = df["Volume"].astype(float)
        vol_long = float(volume.iloc[-20:].mean())
        vol_ratio = float(volume.iloc[-5:].mean()) / vol_long if vol_long else float("nan")
        rsi = float(_rsi(close).iloc[-1])

        rows.append({
            "ticker": t,
            "price": round(latest, 2),
            "change_1d_pct": round(change_1d, 2),
            "change_5d_pct": round(change_5d, 2) if not np.isnan(change_5d) else 0.0,
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "above_ma20_pct": round((latest - ma20) / ma20 * 100, 2) if ma20 else 0.0,
            "above_ma50_pct": round((latest - ma50) / ma50 * 100, 2) if ma50 else 0.0,
            "atr_pct": round(atr / latest * 100, 2) if latest else 0.0,
            "volume_ratio": round(vol_ratio, 2) if not np.isnan(vol_ratio) else 1.0,
            "rsi": round(rsi, 1) if not np.isnan(rsi) else 50.0,
        })

    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: last_close} for as many tickers as resolve."""
    if not tickers:
        return {}

    data = yf.download(
        tickers, period="5d", interval="1d", group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )

    prices: dict[str, float] = {}
    for t in tickers:
        df = _slice(data, t)
        if df is None or df.empty:
            continue
        close = df["Close"].dropna()
        if not close.empty:
            prices[t] = round(float(close.iloc[-1]), 2)
    return prices


def _close_series(symbol: str, period: str = "5d") -> float | None:
    try:
        data = yf.download(symbol, period=period, interval="1d",
                           progress=False, auto_adjust=True, threads=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[fx] download {symbol} failed: {exc}")
        return None
    if data is None or data.empty:
        return None
    close = data["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    return float(close.iloc[-1]) if not close.empty else None


def fetch_fx_rate(from_ccy: str, to_ccy: str = "USD") -> float:
    """Return the multiplier converting `from_ccy` into `to_ccy` (cached)."""
    from_ccy = (from_ccy or "USD").upper()
    to_ccy = (to_ccy or "USD").upper()
    if from_ccy == to_ccy:
        return 1.0

    key = (from_ccy, to_ccy)
    now = time.time()
    cached = _FX_CACHE.get(key)
    if cached and now - cached[0] < _FX_TTL_SECONDS:
        return cached[1]

    rate = _close_series(f"{from_ccy}{to_ccy}=X")
    if rate is None or rate <= 0:
        inverse = _close_series(f"{to_ccy}{from_ccy}=X")
        rate = 1.0 / inverse if inverse and inverse > 0 else None

    if rate is None or rate <= 0:
        print(f"[fx] no rate for {from_ccy}->{to_ccy}, defaulting to 1.0")
        return 1.0

    _FX_CACHE[key] = (now, rate)
    return rate
