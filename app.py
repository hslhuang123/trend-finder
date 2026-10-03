"""TrendFinder web app: screen trending stocks, paper-trade them, track P&L."""
from __future__ import annotations

import os
import threading

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from trendfinder import (
    backtest,
    company,
    config,
    decisions,
    evaluate,
    market_data,
    screener,
)

app = Flask(__name__)
decisions.init_db()


def _resolve_outcomes_async() -> None:
    """Backfill forward outcomes in the background so startup is instant."""
    try:
        decisions.resolve_outcomes()
    except Exception as exc:  # noqa: BLE001
        print(f"[app] resolve_outcomes failed: {exc}")


threading.Thread(target=_resolve_outcomes_async, daemon=True).start()

# Chart ranges -> (yfinance period, interval).
CHART_RANGES = {
    "1d": ("1d", "5m"),
    "5d": ("5d", "15m"),
    "1m": ("1mo", "1d"),
    "3m": ("3mo", "1d"),
    "6m": ("6mo", "1d"),
    "1y": ("1y", "1d"),
    "5y": ("5y", "1d"),
    "10y": ("10y", "1d"),
}

# Optional HTTP Basic Auth. Enable by setting AUTH_USER and AUTH_PASS.
# Strongly recommended when exposing the app to the public internet so
# strangers can't burn your OpenRouter/API budget.
AUTH_USER = os.getenv("AUTH_USER", "").strip()
AUTH_PASS = os.getenv("AUTH_PASS", "").strip()


@app.before_request
def _require_auth():
    if not AUTH_USER:
        return None  # auth disabled
    auth = request.authorization
    if auth and auth.username == AUTH_USER and auth.password == AUTH_PASS:
        return None
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="TrendFinder"'},
    )


@app.get("/")
def index():
    # Portfolio/paper-trading was removed; land on the screener.
    return redirect(url_for("screener_page"))


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


@app.get("/evaluate")
def evaluate_page():
    return render_template("evaluate.html")


@app.get("/api/evaluation")
def api_evaluation():
    top_k = request.args.get("top_k")
    try:
        k = int(top_k) if top_k else None
    except (TypeError, ValueError):
        k = None
    return jsonify(evaluate.evaluate(top_k=k))


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


@app.get("/api/chart/<ticker>")
def api_chart(ticker):
    """Return a ticker's price history for the requested range (for the hover chart)."""
    rng = request.args.get("range", "6m")
    period, interval = CHART_RANGES.get(rng, CHART_RANGES["6m"])
    points = market_data.fetch_price_history(ticker, period=period, interval=interval)
    return jsonify({
        "ticker": ticker,
        "range": rng,
        "period": period,
        "interval": interval,
        "points": points,
    })


@app.get("/api/config")
def api_config():
    return jsonify({
        "jev_enabled": config.has_jev(),
        "jev_model": config.JEV_MODEL,
    })


@app.get("/api/screen")
def api_screen():
    use_jev = request.args.get("jev", "1") not in ("0", "false", "no")
    try:
        return jsonify(screener.screen(use_jev=use_jev))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc), "results": []}), 500


@app.get("/api/watchlist")
def get_watchlist():
    return jsonify({"tickers": config.load_watchlist()})


@app.post("/api/watchlist")
def add_ticker():
    data = request.get_json(force=True, silent=True) or {}
    raw = str(data.get("query") or data.get("ticker") or "").strip()
    if not raw:
        return jsonify({"error": "Enter a ticker symbol or a company name"}), 400
    resolved = company.resolve(raw)
    if not resolved:
        return jsonify({"error": f"Couldn't find a ticker for '{raw}'"}), 404
    ticker = resolved["ticker"]
    tickers = config.load_watchlist()
    added = ticker not in tickers
    if added:
        tickers.append(ticker)
    tickers = config.save_watchlist(tickers)
    return jsonify({"tickers": tickers, "resolved": resolved, "added": added})


@app.delete("/api/watchlist/<ticker>")
def remove_ticker(ticker: str):
    tickers = [t for t in config.load_watchlist() if t != ticker.upper()]
    return jsonify({"tickers": config.save_watchlist(tickers)})


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, threaded=True)
