# TrendFinder

A stock **screener + paper-trading simulator** for US and Canadian markets,
with optional **Jev** (TypeSafe System One) judgments layered on top of a
momentum ranking.

> ⚠️ Educational only. Prices come from free, delayed data (yfinance). Nothing
> here is investment advice and no signal guarantees a profit.

## What it does

- **Screener** — fetches recent daily prices for your watchlist, computes a
  momentum score (5-day return, distance from the 20/50-day MA, volume, RSI,
  ATR penalty), and ranks the names.
- **Auto-pick** — automatically selects the best `AUTO_PICK_COUNT` names
  (default **2**) from the watchlist by final score and highlights them with a
  ★.
- **Surprise discovery** — on every screener run it also pulls a pool of
  **mid-cap** tickers from return-oriented market screeners and surfaces **two
  with high recent returns** (5-day), randomly sampled from the top performers
  so it varies each run, marked with a 🔍. They exist for that run only and are
  **never** written to the watchlist.
- **Jev's three roles** — judges **entries** (trend quality, entry risk,
  momentum sustainability, buy candidate, overall verdict), reviews **open
  positions** (setup health, exit probability, recommended action, downside
  risk), and reviews the **portfolio** as a whole (overall risk,
  diversification, advice).
- **Paper trading** — buy/sell simulated positions with starting cash.
- **Portfolio** — live P&L, realized/unrealized, and per-position **sell
  signals** that combine rule-based stops (stop-loss, take-profit, trailing)
  with Jev's exit review.

## Setup

```sh
cd ~/jev/trend-finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Jev needs an OpenRouter key. If you already export `OPENROUTER_API_KEY`
(e.g. via `~/.config/openrouter/env`), you're done. Otherwise:

```sh
cp .env.example .env
# edit .env and paste your key
```

Without a key the app still runs — it just skips the Jev step.

## Run

```sh
source .venv/bin/activate
python app.py
```

Open <http://127.0.0.1:5000>. Leave the terminal open — the server
must keep running. Press Ctrl+C to stop it.

If port 5000 is busy (macOS AirPlay Receiver uses it), pick another port:

```sh
PORT=5055 python app.py
```

### Testing on a phone (same Wi-Fi)

The server binds to `127.0.0.1` by default, so only this computer can reach it.
To open it on your phone, bind to all interfaces and use your Mac's LAN IP:

```sh
HOST=0.0.0.0 python app.py
# then on the phone: http://<your-mac-ip>:5000   (find it with: ipconfig getifaddr en0)
```

The app is responsive: tables scroll horizontally and drop less-important
columns on narrow screens, and tapping a ticker or column heading shows the
info bubble (hover doesn't exist on touch).

### Troubleshooting "This site can't be reached"

1. Is the server actually running? You should see
   `* Running on http://127.0.0.1:5000` in the terminal. If not, the app
   crashed on startup — read the traceback.
2. Use the exact URL `http://127.0.0.1:5000` (not `https`, not a different
   port). If you ran `PORT=5055`, visit `http://127.0.0.1:5055`.
3. Make sure the venv is active (or run `.venv/bin/python app.py`).
4. Don't close the terminal that's running the server.

- **Portfolio** tab: summary cards, open positions with live P&L and sell
  signals, closed positions.
- **Screener** tab: press **Run screener** (takes ~20–40s; with Jev enabled the
  top ~12 names get a Jev call each), then **Buy** on any row.

## Jev's three roles

| Role | When | Questions (types) |
| --- | --- | --- |
| **Entry** | Screener, top candidates | `trend_quality` (score), `risk_at_entry` (score), `momentum_sustainability` (noul), `is_buy_candidate` (noul), `verdict` (choice: buy_now / watch / avoid) |
| **Exit** | Portfolio, each open position | `setup_health` (score), `should_exit` (noul), `action` (choice: hold / trim / exit), `risk_level` (score) |
| **Portfolio** | Portfolio, all holdings together | `overall_risk` (score), `diversification` (noul), `advice` (choice: hold / rebalance / de_risk) |

Jev is a **stateless decision model** — it returns typed answers with
probabilities/confidence, and the app blends them into its own rules. It never
places trades.

## Performance & FX

- **Base currency:** all cash and P&L are tracked in **USD**. Canadian (`.TO`)
  positions are converted with a live USD/CAD rate (`CADUSD=X`), stored at entry
  and re-applied at valuation and exit, so mixed US/CAD portfolios stay correct.
  Prices in the table show the native currency (`C$` for CAD).
- **Equity snapshots:** each Portfolio load records that day's total value in a
  `snapshots` table (idempotent per day).
- **Metrics:** the Portfolio page shows total return, CAGR, annualized
  volatility, Sharpe, Sortino, max drawdown, and a buy-and-hold comparison
  against **SPY** over the same window, plus an equity sparkline.

Metrics appear once there are at least two daily snapshots (a couple of days of
use). Existing databases auto-migrate: new columns and the `snapshots` table are
added on startup.

## Backtest

The **Backtest** tab replays the momentum strategy over daily history with
trading costs and compares it against a buy-and-hold benchmark (**SPY**).

- **Inputs:** years, top-K, rebalance frequency (days), stop-loss %, take-profit
  %, trailing-stop %, and commission + slippage in basis points.
- **Outputs:** final value, total return, CAGR, Sharpe, max drawdown, an equity
  curve vs SPY, and the full trade log.
- **Rule-based only** — Jev is *not* replayed, since we have no historical
  decision data for it. The backtest uses the same momentum score as the live
  screener.

Run it from the CLI as well:

```sh
.venv/bin/python -m trendfinder.backtest
```

## Help

The app has a built-in **Help** tab (`/help`) explaining how to read the Screener,
Portfolio, and Backtest results — including how to tell whether the strategy is
winning or losing, what the Trades table contains, a metrics glossary, Jev's
roles, and the data caveats.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Enables the Jev layer |
| `JEV_MODEL` | `~typesafe/jev-latest` | Jev model id (pin e.g. `typesafe/jev-1.13`) |
| `INITIAL_CASH` | `100000` | Starting paper cash |
| `AUTO_PICK_COUNT` | `2` | How many top names the screener auto-picks |
| `DISCOVER_COUNT` | `2` | How many surprise tickers to discover each run (0 disables) |
| `DISCOVER_MIN_MARKET_CAP` | `2000000000` | Mid-cap floor ($2B) |
| `DISCOVER_MAX_MARKET_CAP` | `10000000000` | Mid-cap ceiling ($10B) |

The watchlist lives in `data/watchlist.json` (default: 8 tickers — `MSFT`,
`GOOGL`, `AMZN`, `NVDA`, `AMD`, `T.TO`, `XYZ`, `CVE.TO`). Add tickers from the
Screener page. Canadian tickers use the `.TO` suffix (e.g. `CVE.TO`); note
Square/Block trades as `XYZ` (not `SQ`).

> Anthropic and OpenAI are private companies with no tickers, so they cannot be
> added. Public proxies: `MSFT` (OpenAI backer), `AMZN` (Anthropic backer),
> `GOOGL` (Anthropic investor), and `DXYZ` (Destiny Tech100, a listed fund
> holding private AI names).

## Notes / limitations

- Free yfinance data is delayed and can rate-limit; keep the watchlist modest.
- The screener ranking is a **heuristic**, not a prediction. The Jev layer adds
  a structured second opinion (with calibrated probabilities), not a guarantee.
- Signals are advisory rules; the simulator does not auto-trade.
