# Help

TrendFinder checks a list of stocks, ranks them by momentum, and lets you
test a trading plan against history. Prices arrive late, and none of this
is real advice.

**Screener** — enter one or more tickers or company names (separate them with
commas); it checks those plus at least five **discovered** names (🔍) from the
**exchange you pick** in the *Discover from exchange* dropdown (TSX by default;
also TSXV, NASDAQ, NYSE, NYSE American) and ranks that exchange's mid-caps (\$2B–\$10B)
and large-caps (over \$10B) separately by their
return over the period in *Best performers over* (1 day, 5 days, 1 month by default,
or 3 months). With *Skip overextended stocks* ticked (the default) it first drops
names that have already run too far (RSI above 65, over 8% above the 20-day
average, or below the 20/50-day averages), since Jev rates those as high
entry risk. It then ranks everything by momentum. AI judgments (**Jev**) are
not run automatically — pick the tickers to analyze under *AI analysis*.
Discovered names aren't saved.

**Backtest** — runs the momentum strategy over the past daily prices of the
stock you screened, including trading costs, and compares the result with
simply buying and holding SPY (the S&P 500). It uses only the rule-based
momentum signal, not the AI analysis.

**Jev and the AI explanation** — optional AI steps that run only when you ask, to
save tokens and cost. Paste your own OpenRouter API key in the sidebar (get one at
[openrouter.ai/keys](https://openrouter.ai/keys)); it is kept only for your
session, and leaving it blank uses the server's key, if one is configured. Then
pick tickers under *AI analysis*, press **Run AI analysis**, and press **Explain
with AI** for a plain-English reason. The **AI Guide** page explains how both
steps work, what Quality, Risk, Buy, Verdict, Final and News mean, and how the
Final score is calculated. Neither step ever buys or sells for you.

**Evaluate** — tests whether Jev actually helps. Every AI analysis and screener run
is saved in a local decision log (`data/decisions.db`). About 20 trading days later the
app looks up what each stock did and this page compares Jev's verdicts, Buy answers and
scores with those results. It starts empty and needs dozens of results before the
averages mean anything; the page says how many it has. Press **Update outcomes now** to
fill in results sooner than the automatic background update at startup. On a hosted
app the log is wiped when the app restarts, so this page is most useful when you run
the app on your own computer.

**Screener table columns** (hover a column heading in the table for a short tip):

- **#** — rank, best Final score first.
- **Ticker** — the stock symbol. Hover it for the company name and a price chart.
  The pill beside it shows its size: **Large** (market cap over \$10B), **Mid**
  (\$2B–\$10B) or **Small** (under \$2B), in the listing's own currency.
- **Price** — latest (delayed) closing price.
- **Market cap** — total value of the company = share price × shares outstanding.
- **1d %** — (price ÷ previous close − 1) × 100.
- **5d %** — (price ÷ price 5 trading days ago − 1) × 100.
- **RSI** — 14-day Relative Strength Index, 0–100: RSI = 100 − 100 ÷ (1 + RS),
  where RS = average gain ÷ average loss over 14 days (≥ 70 overbought,
  ≤ 30 oversold, ~50 neutral).
- **Vol×** — volume ratio = 5-day average volume ÷ 20-day average volume; above
  1 means busier than usual.
- **ATR %** — 14-day Average True Range as a % of price = ATR(14) ÷ price × 100;
  a volatility measure (higher = bigger swings).
- **Momentum** — the app's technical score (roughly −1…+0.9). Each factor is
  clamped to −1…+1, then combined: **0.30 × (5d return ÷ 10) + 0.25 × (% above
  the 20-day average ÷ 5) + 0.20 × ((volume ratio − 1) ÷ 2) + 0.15 × ((RSI − 50)
  ÷ 25) − 0.10 × (ATR% ÷ 10, floored at 0)**.
- **AI** — the AI's judgment, filled in only for tickers you analyze on demand.
  Hover the badge for Quality, Risk, Buy, Verdict and Final (see the **AI Guide**
  page).

**Backtest summary**

- **Final value** — ending portfolio value = cash + shares × price.
- **Total return** — (final value ÷ starting value − 1) × 100 (starting value = \$100,000).
- **CAGR** — compound annual growth rate = (final ÷ starting)^(1 ÷ years) − 1,
  where years = calendar days ÷ 365.25.
- **Sharpe** — return per unit of risk = mean daily return ÷ daily volatility × √252
  (252 ≈ trading days per year); ~1 is decent, higher is better.
- **Max drawdown** — worst peak-to-trough drop = the lowest value of
  (value − running peak) ÷ running peak, × 100.
- **Trades** — number of fills (buys + sells).
- **Benchmark (SPY)** — the same window if you had simply bought and held SPY,
  starting from \$100,000.

**Backtest trades table**

- **date** — the trading day of the fill.
- **ticker** — the symbol traded.
- **side** — buy or sell.
- **reason** — entry, take-profit, stop-loss, trailing-stop, or rebalance.
- **price** — execution price (that day's close).
- **shares** — number of shares traded.
- **value** — trade amount: buy = shares × price + fees; sell = shares × price − costs.
- **pnl** — realized profit/loss on a sell = (exit price × (1 − cost) − entry price ×
  (1 + cost)) × shares, where cost = (commission + slippage) ÷ 10,000; shows — on buys.

**Caveats:** prices are delayed and free (yfinance); results are a heuristic,
not a prediction; nothing here is investment advice.
