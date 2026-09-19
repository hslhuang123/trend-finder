"""Rule-based buy/sell signals for open positions.

P&L is computed in the base currency (USD) when base prices are supplied;
the trailing stop is evaluated on the native price.
"""
from __future__ import annotations


def evaluate(position: dict, current_price: float,
             entry_price_base: float | None = None,
             current_price_base: float | None = None) -> dict:
    entry_native = float(position["entry_price"])
    shares = float(position["shares"])

    entry = float(entry_price_base) if entry_price_base is not None else entry_native
    now = float(current_price_base) if current_price_base is not None else current_price

    peak = float(position.get("peak_price") or max(entry_native, current_price))
    ret_pct = (now - entry) / entry * 100 if entry else 0.0
    market_value = now * shares
    unrealized = (now - entry) * shares

    reasons: list[str] = []
    stop_loss = position.get("stop_loss_pct")
    take_profit = position.get("take_profit_pct")
    trailing = position.get("trailing_stop_pct")

    if stop_loss and ret_pct <= -abs(stop_loss):
        reasons.append(f"Stop-loss hit ({ret_pct:.1f}% \u2264 -{abs(stop_loss):.1f}%)")
    if take_profit and ret_pct >= abs(take_profit):
        reasons.append(f"Take-profit hit ({ret_pct:.1f}% \u2265 {abs(take_profit):.1f}%)")
    if trailing and peak > 0:
        drawdown = (current_price - peak) / peak * 100
        if drawdown <= -abs(trailing):
            reasons.append(f"Trailing stop hit ({drawdown:.1f}% from peak {peak:.2f})")

    return {
        "signal": "SELL" if reasons else "HOLD",
        "reasons": reasons,
        "return_pct": round(ret_pct, 2),
        "market_value": round(market_value, 2),
        "unrealized_pnl": round(unrealized, 2),
        "peak_price": round(peak, 2),
    }
