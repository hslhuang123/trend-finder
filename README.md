# TrendFinder

A stock **screener + backtester** for US and Canadian markets, with optional
**Jev** (TypeSafe System One) judgments layered on top of a momentum ranking.

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
- **Jev's entry judgment** — judges each top candidate's **trend quality**,
  **entry risk**, **momentum sustainability**, **buy candidacy**, and an overall
  **verdict** (buy now / watch / avoid), blended into the final score.
- **Evaluate** — a report that tests whether Jev's judgments actually beat the
  rule-only momentum ranking. Every Jev call is logged with its baseline, then
  measured against the realized forward return once ~20 trading days pass.

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

### Run the Streamlit version

A **Streamlit** front-end (`streamlit_app.py`) reuses the same backend package and
is what you deploy to Streamlit Cloud. Run it locally with:

```sh
source .venv/bin/activate
streamlit run streamlit_app.py
```

Open <http://127.0.0.1:8501>.

The Streamlit screener keeps the same overlays as the Flask version: hover a
**column heading** for its meaning, hover a **ticker** for a price chart popup
(range buttons 1m/3m/6m/1y), and hover the **AI** badge for Jev's full analysis
(Quality / Risk / Buy / Verdict / Final). The price-chart ranges are limited to
daily ranges (1m/3m/6m/1y) since the data is precomputed for the iframe; intraday
(1d/5d) and multi-year (5y/10y) are not included in the Streamlit version.

### Deploy on Streamlit Cloud

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), **New app** → select the repo.
3. Set the **main file path** to `streamlit_app.py`.
4. In **Advanced settings → Secrets**, add `OPENROUTER_API_KEY` (and optionally
   `JEV_MODEL`). Without a key the app still runs, but the Jev layer is off.
5. Deploy. Streamlit installs `requirements.txt` and runs `streamlit run`.

> ⚠️ **Persistence on Streamlit Cloud:** the container filesystem is **ephemeral**.
> `data/` (watchlist, company cache, and the `decisions.db` log behind the
> **Evaluate** tab) is reset on redeploy/restart. The app works fine per session;
> for durable storage you'd need to point `trendfinder/config.py` at a hosted
> database or object store.

### Testing on a phone (same Wi-Fi)

The server binds to `127.0.0.1` by default, so only this computer can reach it.
To open it on your phone, bind to all interfaces and use your Mac's LAN IP:

```sh
HOST=0.0.0.0 python app.py
# then on the phone: http://<your-mac-ip>:5000   (find it with: ipconfig getifaddr en0)
```

The app is responsive: tables scroll horizontally and drop less-important
columns on narrow screens.

**Hover a ticker** (in the Screener) to pop up an interactive price chart with
range buttons — **1d, 5d, 1m, 3m, 6m, 1y, 5y, 10y**. Move your mouse
onto the popup to switch ranges; hover a column heading for the info bubble.
On touch devices there's no hover: tap a ticker to open the chart, tap a range
button to switch, and tap away to close.

**Themes:** use the icon button in the top bar to switch between **Day** ☀️,
**Night** 🌙, and **System** 🌗 (follows your OS setting). Your choice is saved.

### Troubleshooting "This site can't be reached"

1. Is the server actually running? You should see
   `* Running on http://127.0.0.1:5000` in the terminal. If not, the app
   crashed on startup — read the traceback.
2. Use the exact URL `http://127.0.0.1:5000` (not `https`, not a different
   port). If you ran `PORT=5055`, visit `http://127.0.0.1:5055`.
3. Make sure the venv is active (or run `.venv/bin/python app.py`).
4. Don't close the terminal that's running the server.

- **Screener** tab: press **Run screener** (takes ~20–40s; with Jev enabled the
  top ~12 names get a Jev call each). Add or remove tickers from your watchlist,
  and hover any ticker for a price chart.

## Jev's role

| Role | When | Questions (types) |
| --- | --- | --- |
| **Entry** | Screener, top candidates | `trend_quality` (score), `risk_at_entry` (score), `momentum_sustainability` (noul), `is_buy_candidate` (noul), `verdict` (choice: buy_now / watch / avoid) |

Jev is a **stateless decision model** — it returns typed answers with
probabilities/confidence, and the app blends them into its own rules. It never
places trades.

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

The app has a built-in **Help** tab (`/help`) explaining how to read the Screener
and Backtest results — including how to tell whether the strategy is winning or
losing, what the Trades table contains, a metrics glossary, Jev's role, and the
data caveats.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Enables the Jev layer |
| `JEV_MODEL` | `~typesafe/jev-latest` | Jev model id (pin e.g. `typesafe/jev-1.13`) |
| `AUTO_PICK_COUNT` | `2` | How many top names the screener auto-picks |
| `DISCOVER_COUNT` | `2` | How many surprise tickers to discover each run (0 disables) |
| `DISCOVER_MIN_MARKET_CAP` | `2000000000` | Mid-cap floor ($2B) |
| `DISCOVER_MAX_MARKET_CAP` | `10000000000` | Mid-cap ceiling ($10B) |

The watchlist lives in `data/watchlist.json` (default: 8 tickers — `MSFT`,
`GOOGL`, `AMZN`, `NVDA`, `AMD`, `T.TO`, `XYZ`, `CVE.TO`). Add tickers from the
Screener page — you can enter either a ticker symbol or a company name, e.g.
`MSFT`, `Bell`, `Rogers`, or `Netflix`, and the app resolves it to a symbol
(preferring the Canadian `.TO` listing for common Canadian names). Canadian
tickers use the `.TO` suffix (e.g. `CVE.TO`); note Square/Block trades as
`XYZ` (not `SQ`).

> Anthropic and OpenAI are private companies with no tickers, so they cannot be
> added. Public proxies: `MSFT` (OpenAI backer), `AMZN` (Anthropic backer),
> `GOOGL` (Anthropic investor), and `DXYZ` (Destiny Tech100, a listed fund
> holding private AI names).

## Notes / limitations

- Free yfinance data is delayed and can rate-limit; keep the watchlist modest.
- The screener ranking is a **heuristic**, not a prediction. The Jev layer adds
  a structured second opinion (with calibrated probabilities), not a guarantee.
- The screener's auto-picks are advisory; nothing is auto-traded.
