"""TrendFinder web app: screen trending stocks, paper-trade them, track P&L."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from flask import Flask, jsonify, redirect, render_template, request, url_for

from trendfinder import (
    backtest,
    company,
    config,
    jev_client,
    market_data,
    metrics,
    portfolio,
    screener,
    signals,
)

app = Flask(__name__)
portfolio.init_db()

BASE_CURRENCY = "USD"


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


@app.get("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.svg"))


@app.get("/screener")
def screener_page():
    return render_template("screener.html")


@app.get("/backtest")
def backtest_page():
    return render_template("backtest.html")


@app.get("/help")
def help_page():
    return render_template("help.html")


@app.get("/api/backtest")
def api_backtest():
    params = {
        "years": request.args.get("years"),
        "top_k": request.args.get("top_k"),
        "rebalance_days": request.args.get("rebalance_days"),
        "stop_loss_pct": request.args.get("stop_loss_pct"),
        "take_profit_pct": request.args.get("take_profit_pct"),
        "trailing_stop_pct": request.args.get("trailing_stop_pct"),
        "commission_bps": request.args.get("commission_bps"),
        "slippage_bps": request.args.get("slippage_bps"),
    }
    params = {k: v for k, v in params.items() if v not in (None, "")}
    try:
        return jsonify(backtest.run(config.load_watchlist(), params))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/config")
def api_config():
    return jsonify({
        "jev_enabled": config.has_jev(),
        "jev_model": config.JEV_MODEL,
        "initial_cash": config.INITIAL_CASH,
        "base_currency": BASE_CURRENCY,
    })


def _position_state(pos: dict, trend: dict | None) -> dict:
    entry = pos["entry_price"]
    peak = pos.get("peak_price") or pos["current_price"]
    state = {
        "ticker": pos["ticker"],
        "currency": pos.get("currency") or BASE_CURRENCY,
        "entry_price": entry,
        "current_price": pos["current_price"],
        "return_pct": pos["return_pct"],
        "peak_price": peak,
        "drawdown_from_peak_pct": round((pos["current_price"] - peak) / peak * 100, 2) if peak else 0.0,
        "rule_signals": pos.get("reasons") or [],
    }
    if trend:
        for key in ("change_5d_pct", "above_ma20_pct", "above_ma50_pct", "atr_pct", "volume_ratio", "rsi"):
            state[key] = trend.get(key)
    return state


def _extract_exit(answers: dict) -> dict:
    return {
        "setup_health": (answers.get("setup_health") or {}).get("score"),
        "should_exit": (answers.get("should_exit") or {}).get("noul"),
        "action": (answers.get("action") or {}).get("choice"),
        "risk_level": (answers.get("risk_level") or {}).get("score"),
    }


def _extract_portfolio(answers: dict) -> dict:
    return {
        "overall_risk": (answers.get("overall_risk") or {}).get("score"),
        "diversification": (answers.get("diversification") or {}).get("noul"),
        "advice": (answers.get("advice") or {}).get("choice"),
    }


def _apply_jev_exit(pos: dict) -> None:
    """Blend Jev's exit view into the rule-based signal."""
    jev = pos.get("jev") or {}
    action = jev.get("action")
    p_exit = jev.get("should_exit")
    reasons = list(pos.get("reasons") or [])
    if pos.get("signal") != "SELL":
        if action == "exit" or (p_exit is not None and p_exit >= 0.65):
            pos["signal"] = "SELL"
            reasons.append(f"Jev: exit advised (p_exit={p_exit})")
        elif action == "trim" or (p_exit is not None and p_exit >= 0.4):
            pos["signal"] = "REVIEW"
            reasons.append(f"Jev: consider trimming (p_exit={p_exit})")
    pos["reasons"] = reasons


@app.get("/api/portfolio")
def api_portfolio():
    positions = portfolio.get_open_positions()
    prices = market_data.fetch_latest_prices([p["ticker"] for p in positions])

    enriched: list[dict] = []
    market_value = 0.0
    unrealized = 0.0
    for pos in positions:
        native_price = prices.get(pos["ticker"], pos["entry_price"])
        currency = (pos.get("currency") or BASE_CURRENCY).upper()
        entry_fx = float(pos.get("entry_fx") or 1.0)
        fx_now = market_data.fetch_fx_rate(currency, BASE_CURRENCY)

        portfolio.update_peak(pos["id"], native_price)
        pos = portfolio.get_position(pos["id"]) or pos

        entry_base = float(pos["entry_price"]) * entry_fx
        current_base = native_price * fx_now
        info = signals.evaluate(
            pos, native_price,
            entry_price_base=entry_base,
            current_price_base=current_base,
        )
        enriched.append({
            **pos,
            "currency": currency,
            "current_price": native_price,       # native price, for display
            "current_price_base": round(current_base, 4),
            "entry_price_base": round(entry_base, 4),
            "entry_fx": entry_fx,
            "fx_now": fx_now,
            **info,
        })
        market_value += info["market_value"]
        unrealized += info["unrealized_pnl"]

    cash = portfolio.get_cash()
    total_value = cash + market_value
    closed = portfolio.get_closed_positions()
    realized = sum(
        (p["exit_price"] * (p.get("exit_fx") or 1.0)
         - p["entry_price"] * (p.get("entry_fx") or 1.0)) * p["shares"]
        for p in closed
        if p["exit_price"] is not None
    )

    # Jev exit review for open positions, plus a portfolio-level review.
    portfolio_review = None
    trend_map: dict[str, dict] = {}
    if enriched and config.has_jev():
        trend_df = market_data.fetch_trend_data([p["ticker"] for p in enriched])
        trend_map = {row["ticker"]: row.to_dict() for _, row in trend_df.iterrows()}

        states = [_position_state(p, trend_map.get(p["ticker"])) for p in enriched]
        with ThreadPoolExecutor(max_workers=6) as pool:
            exit_answers = list(pool.map(jev_client.review_position, states))
        for pos, answer in zip(enriched, exit_answers):
            if answer:
                pos["jev"] = _extract_exit(answer)
                _apply_jev_exit(pos)

        answer = jev_client.review_portfolio({
            "base_currency": BASE_CURRENCY,
            "positions": [
                {
                    "ticker": p["ticker"],
                    "currency": p["currency"],
                    "return_pct": p["return_pct"],
                    "weight_pct": round(p["market_value"] / market_value * 100, 1) if market_value else 0.0,
                    "atr_pct": (trend_map.get(p["ticker"]) or {}).get("atr_pct"),
                    "risk_level": (p.get("jev") or {}).get("risk_level"),
                }
                for p in enriched
            ],
            "cash": round(cash, 2),
            "total_value": round(total_value, 2),
        })
        portfolio_review = _extract_portfolio(answer) if answer else None

    # Attach company profiles for the ticker hover bubbles.
    try:
        profiles = company.enrich(
            [p["ticker"] for p in enriched] + [p["ticker"] for p in closed]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[company] enrichment failed: {exc}")
        profiles = {}
    for position in enriched:
        position["company"] = profiles.get(position["ticker"], {})
    for position in closed:
        position["company"] = profiles.get(position["ticker"], {})

    # Record today's equity snapshot (idempotent per day).
    portfolio.upsert_snapshot(
        date.today().isoformat(),
        round(cash, 2), round(market_value, 2), round(total_value, 2),
        round(unrealized, 2), round(realized, 2),
    )

    return jsonify({
        "base_currency": BASE_CURRENCY,
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_value": round(total_value, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "open_positions": enriched,
        "closed_positions": closed,
        "portfolio_review": portfolio_review,
    })


@app.get("/api/performance")
def api_performance():
    snaps = portfolio.get_snapshots()
    dates = [s["date"] for s in snaps]
    values = [float(s["total_value"]) for s in snaps]

    result = metrics.summarize(dates, values)
    result["base_currency"] = BASE_CURRENCY
    result["series"] = [{"date": d, "value": v} for d, v in zip(dates, values)]
    result["benchmark"] = None
    if len(dates) >= 2:
        result["benchmark"] = metrics.benchmark(dates[0], dates[-1], values[0], symbol="SPY")
    return jsonify(result)


@app.get("/api/screen")
def api_screen():
    use_jev = request.args.get("jev", "1") not in ("0", "false", "no")
    try:
        return jsonify(screener.screen(use_jev=use_jev))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc), "results": []}), 500


@app.post("/api/buy")
def api_buy():
    data = request.get_json(force=True, silent=True) or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    try:
        shares = float(data.get("shares", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "shares must be a number"}), 400

    price = market_data.fetch_latest_prices([ticker]).get(ticker)
    if price is None:
        return jsonify({"error": f"could not fetch a price for {ticker}"}), 400

    profile = company.enrich([ticker]).get(ticker, {})
    currency = (profile.get("currency") or BASE_CURRENCY).upper()
    fx = market_data.fetch_fx_rate(currency, BASE_CURRENCY)

    try:
        position_id = portfolio.buy(
            ticker, price, shares, currency=currency, entry_fx=fx,
            stop_loss_pct=_opt_float(data.get("stop_loss_pct")),
            take_profit_pct=_opt_float(data.get("take_profit_pct")),
            trailing_stop_pct=_opt_float(data.get("trailing_stop_pct")),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "ok": True,
        "position_id": position_id,
        "entry_price": price,
        "currency": currency,
        "fx": round(fx, 4),
        "cost_usd": round(price * shares * fx, 2),
    })


@app.post("/api/sell")
def api_sell():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("position_id") is None:
        return jsonify({"error": "position_id is required"}), 400

    pos = portfolio.get_position(int(data["position_id"]))
    if not pos:
        return jsonify({"error": "position not found"}), 404

    price = market_data.fetch_latest_prices([pos["ticker"]]).get(pos["ticker"])
    if price is None:
        return jsonify({"error": f"could not fetch a price for {pos['ticker']}"}), 400

    currency = (pos.get("currency") or BASE_CURRENCY).upper()
    fx = market_data.fetch_fx_rate(currency, BASE_CURRENCY)
    try:
        proceeds = portfolio.sell(int(data["position_id"]), price, exit_fx=fx)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "ok": True,
        "exit_price": price,
        "currency": currency,
        "proceeds_usd": round(proceeds, 2),
    })


@app.get("/api/watchlist")
def get_watchlist():
    return jsonify({"tickers": config.load_watchlist()})


@app.post("/api/watchlist")
def add_ticker():
    data = request.get_json(force=True, silent=True) or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    tickers = config.load_watchlist()
    if ticker not in tickers:
        tickers.append(ticker)
    return jsonify({"tickers": config.save_watchlist(tickers)})


@app.delete("/api/watchlist/<ticker>")
def remove_ticker(ticker: str):
    tickers = [t for t in config.load_watchlist() if t != ticker.upper()]
    return jsonify({"tickers": config.save_watchlist(tickers)})


def _opt_float(value) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, threaded=True)
