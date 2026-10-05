"""TrendFinder — Streamlit edition.

A Streamlit front-end that reuses the same `trendfinder` backend package
(screener, backtester, Jev evaluation) so the app can be deployed on
**Streamlit Cloud**.

Run locally:

    streamlit run streamlit_app.py

Deploy: push to a repo, then on Streamlit Cloud point the main file at
`streamlit_app.py`. No secret is required — users paste their own OpenRouter
API key into the sidebar to enable Jev (the key is kept only for the session).
"""
from __future__ import annotations

import html as _html
import json

import pandas as pd
import streamlit as st

from trendfinder import (
    backtest,
    company,
    config,
    decisions,
    evaluate,
    market_data,
    screener,
)

st.set_page_config(page_title="TrendFinder", layout="wide", page_icon="📈")

# Remember any key supplied through the environment (e.g. Streamlit secrets) so
# an empty OpenRouter box in the UI can fall back to it.
_ENV_OPENROUTER_KEY = config.OPENROUTER_API_KEY

# Make sure the decision-log tables exist (used by the screener + Evaluate tab).
decisions.init_db()

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


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _fmt_money(v: float | None) -> str:
    return "—" if v is None else f"${v:,.2f}"


def _fmt_market_cap(v: float | None, currency: str = "USD") -> str:
    if v is None:
        return "—"
    sym = "C$" if currency == "CAD" else "$"
    for size, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(v) >= size:
            return f"{sym}{v / size:.1f}{suffix}"
    return f"{sym}{v:,.0f}"


def _fmt_num(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


# --------------------------------------------------------------------------- #
# Screener table as a custom HTML component (keeps the Jev hover overlay).
# Embeds the exact same static/style.css as the Flask app so the table looks
# identical; only the hover tooltip is kept (no price-chart popup).
# --------------------------------------------------------------------------- #
# Theme toggle (System / Light / Dark) for both the Streamlit UI and the table.
# --------------------------------------------------------------------------- #
_DARK_CSS = """
:root { color-scheme: dark; }
html, body, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"] { background-color: #0e1116 !important; color: #e6edf3 !important; }
[data-testid="stSidebar"] { background-color: #161b22 !important; color: #e6edf3 !important; }
[data-testid="stHeader"] { background-color: #0e1116 !important; color: #e6edf3 !important; }
h1,h2,h3,h4,h5,h6,p,span,label,div,strong,em,li { color: #e6edf3 !important; }
a { color: #58a6ff !important; }
[data-testid="stMetric"], [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { background-color: #161b22 !important; color: #e6edf3 !important; }
[data-testid="stDataFrame"] { background-color: #161b22 !important; }
.stButton button, [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"] { background-color: #1c232c !important; color: #e6edf3 !important; border-color: #2a323d !important; }
[data-testid="stExpander"] details, [data-testid="stExpander"] summary { background-color: #161b22 !important; }
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stSelectbox"], [data-testid="stMultiSelect"] { background-color: #1c232c !important; color: #e6edf3 !important; border-color: #2a323d !important; }
[data-testid="stAlert"], [data-testid="stNotification"] { background-color: #1c232c !important; color: #e6edf3 !important; }
[data-testid="stSidebar"] .stRadio label, [data-testid="stSidebar"] .stRadio p { color: #e6edf3 !important; }
"""

_LIGHT_RESET = """:root { color-scheme: light; }"""


def _theme_css(mode: str) -> str:
    if mode == "dark":
        return _DARK_CSS
    if mode == "system":
        return f"@media (prefers-color-scheme: dark) {{\n{_DARK_CSS}\n}}"
    return _LIGHT_RESET


def _inject_theme_css(mode: str) -> None:
    try:
        st.markdown(f"<style>{_theme_css(mode)}</style>", unsafe_allow_html=True)
    except Exception:  # noqa: BLE001 - theme CSS must never break the app
        pass


def _streamlit_theme() -> str:
    """Return 'light', 'dark', or '' (follow OS) for the embedded screener table."""
    mode = st.session_state.get("theme_mode", "system")
    return mode if mode in ("light", "dark") else ""


_STATIC_CSS_CACHE: str | None = None


def _load_static_css() -> str:
    global _STATIC_CSS_CACHE
    if _STATIC_CSS_CACHE is None:
        path = config.ROOT / "static" / "style.css"
        try:
            _STATIC_CSS_CACHE = path.read_text()
        except OSError:
            _STATIC_CSS_CACHE = ""
    return _STATIC_CSS_CACHE


_SCREENER_JS = """
const TF = window.TF_DATA || {};
const CHART_RANGES = ['1m', '3m', '6m', '1y'];
const SVG_NS = 'http://www.w3.org/2000/svg';
const tooltip = document.getElementById('tf-tip');
let tipTarget = null;
let chartPopup = null, chartTicker = null, chartRange = '6m', hideChartTimer = null;
const isTouch = window.matchMedia && window.matchMedia('(hover: none)').matches;

function svgEl(tag, attrs) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function svgPolyline(points, color) {
  return svgEl('polyline', {
    points: points.map(([x, y]) => x.toFixed(1) + ',' + y.toFixed(1)).join(' '),
    fill: 'none', stroke: color, 'stroke-width': '2'
  });
}
function fmtPrice(v) {
  if (v >= 1000) return Math.round(v).toLocaleString();
  if (v >= 10) return v.toFixed(0);
  return v.toFixed(2);
}
function shortDate(s) { return String(s).length > 10 ? String(s).slice(5, 10) : String(s); }

// ---- tooltip (column headers, AI badge, cp-ticker) ----
function positionTip(x, y) {
  const pad = 14, r = tooltip.getBoundingClientRect();
  let left = x + pad, top = y + pad;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - pad;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - pad;
  tooltip.style.left = Math.max(8, left) + 'px';
  tooltip.style.top = Math.max(8, top) + 'px';
}
function showTip(el, x, y) {
  tooltip.querySelector('.tip-title').textContent = el.dataset.name || '';
  tooltip.querySelector('.tip-desc').textContent = el.dataset.desc || '';
  tooltip.classList.add('show');
  tipTarget = el;
  positionTip(x, y);
}
function hideTip() { tooltip.classList.remove('show'); tipTarget = null; }

// ---- chart popup (hover a ticker) ----
function getChartPopup() {
  if (!chartPopup) {
    chartPopup = document.createElement('div');
    chartPopup.className = 'chart-popup';
    const head = document.createElement('div'); head.className = 'cp-head';
    const tick = document.createElement('span'); tick.className = 'cp-ticker';
    const close = document.createElement('button'); close.type = 'button'; close.className = 'cp-close'; close.textContent = '✕'; close.title = 'Close';
    close.addEventListener('click', hideChartPopup);
    head.append(tick, close);
    const name = document.createElement('div'); name.className = 'cp-name';
    const ranges = document.createElement('div'); ranges.className = 'cp-ranges';
    CHART_RANGES.forEach((r) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'cp-range'; b.textContent = r; b.dataset.range = r;
      b.addEventListener('click', () => { chartRange = r; setActiveRange(); loadChart(); });
      ranges.appendChild(b);
    });
    const chart = document.createElement('div'); chart.className = 'cp-chart';
    const status = document.createElement('div'); status.className = 'cp-status';
    chartPopup.append(head, name, ranges, chart, status);
    document.body.appendChild(chartPopup);
  }
  return chartPopup;
}
function setActiveRange() {
  getChartPopup().querySelectorAll('.cp-range').forEach((b) => b.classList.toggle('active', b.dataset.range === chartRange));
}
function positionChartPopup(x, y) {
  const popup = getChartPopup(); const r = popup.getBoundingClientRect(); const pad = 14;
  let left = x + pad, top = y + pad;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - pad;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - pad;
  popup.style.left = Math.max(8, left) + 'px'; popup.style.top = Math.max(8, top) + 'px';
}
function showChartPopup(ticker, name, desc, x, y) {
  const popup = getChartPopup(); chartTicker = ticker;
  const tick = popup.querySelector('.cp-ticker');
  tick.textContent = ticker;
  tick.dataset.name = name || ticker;
  tick.dataset.desc = String(desc || '').slice(0, 220);
  tick.dataset.tip = '1';
  popup.querySelector('.cp-name').textContent = name || '';
  setActiveRange();
  popup.classList.add('show');
  positionChartPopup(x, y);
  loadChart();
}
function hideChartPopup() { clearTimeout(hideChartTimer); if (chartPopup) chartPopup.classList.remove('show'); chartTicker = null; }
function scheduleHideChartPopup() { clearTimeout(hideChartTimer); hideChartTimer = setTimeout(hideChartPopup, 250); }
function cancelHideChartPopup() { clearTimeout(hideChartTimer); }

function sliceRange(all, range) {
  const N = { '1m': 22, '3m': 66, '6m': 132, '1y': 252 }[range] || all.length;
  return all.slice(-N);
}
function loadChart() {
  if (!chartTicker) return;
  const popup = getChartPopup();
  const chartEl = popup.querySelector('.cp-chart');
  const statusEl = popup.querySelector('.cp-status');
  const all = (TF.charts && TF.charts[chartTicker]) || [];
  const pts = sliceRange(all, chartRange);
  if (statusEl) statusEl.textContent = pts.length ? pts.length + ' points' : 'No data';
  renderChartPopup(chartEl, pts);
}
function renderChartPopup(chartEl, raw) {
  chartEl.replaceChildren();
  if (raw.length < 2) {
    const p = document.createElement('div'); p.className = 'cp-empty'; p.textContent = 'No price data available.';
    chartEl.appendChild(p); return;
  }
  const points = raw.map(([d, price]) => ({ date: d, price }));
  const W = 316, H = 120, padL = 46, padR = 6, padT = 8, padB = 18;
  const prices = points.map((p) => p.price);
  const min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
  const span = max - min || 1, n = points.length;
  const x = (i) => padL + (i * (W - padL - padR)) / (n - 1);
  const y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart cp-svg' });
  for (let g = 0; g <= 3; g++) {
    const val = min + (span * g) / 3; const gy = y(val);
    svg.appendChild(svgEl('line', { x1: padL, y1: gy, x2: W - padR, y2: gy, class: 'grid' }));
    const label = svgEl('text', { x: padL - 4, y: gy + 3, class: 'axis', 'text-anchor': 'end' });
    label.textContent = fmtPrice(val); svg.appendChild(label);
  }
  const pts = points.map((p, i) => [x(i), y(p.price)]);
  const color = prices[n - 1] >= prices[0] ? '#3fb950' : '#f85149';
  svg.appendChild(svgPolyline(pts, color));
  const start = svgEl('text', { x: padL, y: H - 4, class: 'axis', 'text-anchor': 'start' });
  start.textContent = shortDate(points[0].date); svg.appendChild(start);
  const end = svgEl('text', { x: W - padR, y: H - 4, class: 'axis', 'text-anchor': 'end' });
  end.textContent = shortDate(points[n - 1].date); svg.appendChild(end);
  chartEl.appendChild(svg);
}

// ---- hover handling ----
document.addEventListener('mouseover', (e) => {
  if (isTouch) return;
  const tickerEl = e.target.closest && e.target.closest('.ticker');
  if (tickerEl) {
    cancelHideChartPopup();
    const t = tickerEl.dataset.ticker;
    if (chartTicker !== t) showChartPopup(t, tickerEl.dataset.name, tickerEl.dataset.desc, e.clientX, e.clientY);
    else positionChartPopup(e.clientX, e.clientY);
    return;
  }
  if (chartPopup && chartPopup.contains(e.target)) {
    cancelHideChartPopup();
    const tt = e.target.closest && e.target.closest('[data-tip]');
    if (tt) showTip(tt, e.clientX, e.clientY);
    return;
  }
  const target = e.target.closest && e.target.closest('[data-tip]');
  if (target) showTip(target, e.clientX, e.clientY);
});
document.addEventListener('mouseout', (e) => {
  if (isTouch) return;
  if (e.target.closest && e.target.closest('.ticker')) scheduleHideChartPopup();
  if (chartPopup && chartPopup.contains(e.target)) scheduleHideChartPopup();
  if (e.target.closest && e.target.closest('[data-tip]')) hideTip();
});
document.addEventListener('mousemove', (e) => { if (!isTouch && tipTarget) positionTip(e.clientX, e.clientY); });
document.addEventListener('click', (e) => {
  if (!isTouch) return;
  const tickerEl = e.target.closest && e.target.closest('.ticker');
  if (tickerEl) {
    const t = tickerEl.dataset.ticker;
    if (chartTicker === t && chartPopup && chartPopup.classList.contains('show')) hideChartPopup();
    else showChartPopup(t, tickerEl.dataset.name, tickerEl.dataset.desc, e.clientX || window.innerWidth / 2, e.clientY || 80);
    return;
  }
  const target = e.target.closest && e.target.closest('[data-tip]');
  if (!target) { hideChartPopup(); hideTip(); return; }
  if (tipTarget === target && tooltip.classList.contains('show')) hideTip();
  else showTip(target, e.clientX || window.innerWidth / 2, e.clientY || 80);
});
window.addEventListener('scroll', () => { hideTip(); hideChartPopup(); }, true);
"""


def _precompute_chart_data(results: list[dict]) -> dict:
    """Fetch daily price history for each displayed ticker (for the hover chart)."""
    charts: dict = {}
    tickers = [r["ticker"] for r in results]
    if not tickers:
        return charts
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        pairs = list(ex.map(
            lambda t: (t, market_data.fetch_price_history(t, period="1y", interval="1d")),
            tickers,
        ))
    for ticker, points in pairs:
        if points:
            charts[ticker] = [[p["date"], p["price"]] for p in points]
    return charts


def _screener_table_html(results: list[dict], charts: dict | None = None) -> str:
    """Render the screener as the Flask table, with header tips + ticker chart popup."""
    charts = charts or {}

    def esc(v) -> str:
        return _html.escape(str(v))

    def badge_cls(verdict):
        return {"buy_now": "buy-now", "watch": "watch", "avoid": "avoid"}.get(verdict, "")

    def pct_cls(v):
        if v is None:
            return ""
        return "pos" if v > 0 else ("neg" if v < 0 else "")

    rows = []
    for i, r in enumerate(results, start=1):
        j = r.get("jev") or {}
        co = r.get("company") or {}
        verdict = j.get("verdict")
        verdict_label = (verdict or "—").replace("_", " ")
        q = _fmt_num(j.get("trend_quality"), 1) if j.get("trend_quality") is not None else "—"
        rk = _fmt_num(j.get("risk_at_entry"), 1) if j.get("risk_at_entry") is not None else "—"
        buy = "—"
        if j.get("is_buy_candidate") is not None:
            buy = f"{100 if j['is_buy_candidate'] else 0}%"
        final = _fmt_num(r.get("final_score"), 3)
        tip = f"Quality: {q} / 2\nRisk: {rk} / 2\nBuy: {buy}\nVerdict: {verdict_label}\nFinal: {final}"

        marks = ""
        if r.get("pick"):
            marks += "<span class=\"pick-star\">★</span>"
        if r.get("discovered"):
            marks += "<span class=\"discover-mark\">🔍</span>"
        name = co.get("name") or r["ticker"]
        desc = co.get("description") or "No description available."
        ticker_cls = "ticker" + (" pick-bold" if r.get("pick") else "")
        ticker_cell = (
            f"<td class=\"ticker-cell\">{marks}"
            f"<span class=\"{ticker_cls}\" data-tip=\"1\" data-ticker=\"{esc(r['ticker'])}\" "
            f"data-name=\"{esc(name)}\" data-desc=\"{esc(desc)}\">{esc(r['ticker'])}</span></td>"
        )
        ai_cell = (
            f"<td class=\"ai-cell\"><span class=\"ai-badge {badge_cls(verdict)}\" "
            f"data-tip=\"1\" data-name=\"Jev Analysis\" data-desc=\"{esc(tip)}\">"
            f"{esc(verdict_label)}</span></td>"
        )
        row_cls = "row-discovered" if r.get("discovered") else ""
        rows.append(
            f"<tr class=\"{row_cls}\">"
            f"<td>{i}</td>"
            f"{ticker_cell}"
            f"<td>{_fmt_money(r.get('price'))}</td>"
            f"<td>{_fmt_market_cap(co.get('market_cap'), co.get('currency'))}</td>"
            f"<td class=\"{pct_cls(r.get('change_1d_pct'))}\">{_fmt_pct(r.get('change_1d_pct'))}</td>"
            f"<td class=\"{pct_cls(r.get('change_5d_pct'))}\">{_fmt_pct(r.get('change_5d_pct'))}</td>"
            f"<td>{_fmt_num(r.get('rsi'), 0)}</td>"
            f"<td>{_fmt_num(r.get('volume_ratio'))}</td>"
            f"<td>{_fmt_num(r.get('atr_pct'))}</td>"
            f"<td>{_fmt_num(r.get('momentum_score'), 3)}</td>"
            f"{ai_cell}"
            "<td class=\"row-actions\"></td>"
            "</tr>"
        )

    theme_attr = f" data-theme=\"{_streamlit_theme()}\"" if _streamlit_theme() else ""
    tf_data = json.dumps({"charts": charts})
    headers = (
        "<thead><tr>"
        "<th data-tip=\"1\" data-name=\"#\" data-desc=\"Rank by Final score, best first.\">#</th>"
        "<th data-tip=\"1\" data-name=\"Ticker\" data-desc=\"Stock symbol. Hover the ticker itself for the company name and description.\">Ticker</th>"
        "<th data-tip=\"1\" data-name=\"Price\" data-desc=\"Latest delayed closing price.\">Price</th>"
        "<th data-tip=\"1\" data-name=\"Market cap\" data-desc=\"Market capitalization: total value of the company's shares (latest available). C$ means Canadian dollars.\">Market cap</th>"
        "<th data-tip=\"1\" data-name=\"1d %\" data-desc=\"Percent change from the previous close.\">1d %</th>"
        "<th data-tip=\"1\" data-name=\"5d %\" data-desc=\"Percent change over the last 5 trading days.\">5d %</th>"
        "<th data-tip=\"1\" data-name=\"RSI\" data-desc=\"14-day Relative Strength Index, 0-100. Above 70 is overbought, below 30 is oversold, around 50 is neutral.\">RSI</th>"
        "<th data-tip=\"1\" data-name=\"Vol×\" data-desc=\"Volume ratio: 5-day average volume divided by the 20-day average. Above 1 means busier than usual.\">Vol×</th>"
        "<th data-tip=\"1\" data-name=\"ATR %\" data-desc=\"Average True Range as a percent of price, a volatility measure. Higher means bigger swings.\">ATR %</th>"
        "<th data-tip=\"1\" data-name=\"Momentum\" data-desc=\"The app's technical score from 5-day return, distance above the 20-day average, volume and RSI, minus an ATR penalty. Roughly -1 to +1.\">Momentum</th>"
        "<th data-tip=\"1\" data-name=\"AI\" data-desc=\"Jev's analysis. Hover (or tap) a row's AI badge to see Quality, Risk, Buy, Verdict and Final.\">AI</th>"
        "<th></th>"
        "</tr></thead>"
    )
    return (
        "<!doctype html><html" + theme_attr + "><head><meta charset=\"utf-8\">"
        f"<style>{_load_static_css()}</style></head><body>"
        + "<div class=\"table-wrap\"><table id=\"screen-table\">" + headers
        + "<tbody>" + "".join(rows) + "</tbody></table></div>"
        + "<div class=\"tooltip\" id=\"tf-tip\"><div class=\"tip-title\"></div><div class=\"tip-desc\"></div></div>"
        + f"<script>window.TF_DATA = {tf_data};</script>"
        + f"<script>{_SCREENER_JS}</script></body></html>"
    )


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
if "watchlist" not in st.session_state:
    st.session_state.watchlist = config.load_watchlist()
if "screen_results" not in st.session_state:
    st.session_state.screen_results = None
if "screen_charts" not in st.session_state:
    st.session_state.screen_charts = {}
if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = None
if "eval_results" not in st.session_state:
    st.session_state.eval_results = None


def _persist_watchlist() -> None:
    config.save_watchlist(st.session_state.watchlist)


# --------------------------------------------------------------------------- #
# Screener tab
# --------------------------------------------------------------------------- #
def _render_screener_chart(results: list[dict]) -> None:
    """A range selectbox + line chart for a chosen ticker (replaces the hover popup)."""
    tickers = [r["ticker"] for r in results]
    col1, col2 = st.columns([2, 1])
    with col1:
        ticker = st.selectbox("Chart ticker", tickers, key="screen_chart_ticker")
    with col2:
        rng = st.selectbox("Range", list(CHART_RANGES.keys()), index=4, key="screen_chart_range")
    period, interval = CHART_RANGES[rng]
    points = market_data.fetch_price_history(ticker, period=period, interval=interval)
    if not points:
        st.info(f"No price history for {ticker}.")
        return
    df = pd.DataFrame(points)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    st.line_chart(df["price"], height=280)


def _render_screener() -> None:
    st.title("Trending stocks")
    st.caption("Screener — checks the stock you enter plus two freshly discovered "
               "names, ranks them by momentum, and enriches them with Jev's judgment.")

    # --- What to screen (a single ticker or company name) ---
    query = st.text_input(
        "Screen a ticker or company name",
        placeholder="e.g. AAPL, Bell, Rogers",
        key="screen_query",
    )
    use_jev = config.has_jev()
    if use_jev:
        st.caption("Jev is on — it will judge the entrants.")
    else:
        st.caption("Jev is off — add your OpenRouter API key in the sidebar to enable it.")

    if st.button("Run screener", type="primary"):
        resolved = company.resolve(query.strip()) if query.strip() else {}
        if not resolved:
            st.warning(
                f"Couldn't find a ticker for '{query}'. "
                "Try a symbol like AAPL or a company name like Rogers."
            )
        else:
            ticker = resolved["ticker"]
            label = f"{ticker} ({resolved['name']})" if resolved.get("name") else ticker
            with st.spinner(f"Screening {label} + 2 discovered… (Jev calls can take ~30s)"):
                st.session_state.screen_results = screener.screen(
                    use_jev=use_jev, watchlist=[ticker]
                )
            # Precompute price history so the hover chart popup works (no API in the
            # iframe). Stored in session_state so it's not refetched on every rerun.
            with st.spinner("Preparing charts…"):
                st.session_state.screen_charts = _precompute_chart_data(
                    (st.session_state.screen_results or {}).get("results", [])
                )
            st.session_state["screen_label"] = label

    # --- Watchlist management (used by the Backtest tab) ---
    with st.expander("Watchlist (used by Backtest)", expanded=False):
        col_add, col_rm = st.columns([2, 2])
        with col_add:
            add_query = st.text_input("Add ticker or company name", placeholder="e.g. AAPL, Bell, Rogers")
            if st.button("Add to watchlist"):
                if add_query.strip():
                    resolved = company.resolve(add_query.strip())
                    if not resolved:
                        st.warning(f"Couldn't find a ticker for '{add_query}'.")
                    else:
                        ticker = resolved["ticker"]
                        if ticker not in st.session_state.watchlist:
                            st.session_state.watchlist.append(ticker)
                            _persist_watchlist()
                        st.success(f"Added {ticker}" + (f" ({resolved['name']})" if resolved.get("name") else ""))
        with col_rm:
            if st.session_state.watchlist:
                remove = st.multiselect("Remove tickers", st.session_state.watchlist, key="rm_tickers")
                if st.button("Remove selected") and remove:
                    st.session_state.watchlist = [t for t in st.session_state.watchlist if t not in remove]
                    _persist_watchlist()
        st.caption("Current: " + (", ".join(st.session_state.watchlist) or "empty"))

    results = st.session_state.screen_results
    if results is None:
        st.info("Enter a ticker or company name above and press **Run screener**.")
        return

    meta = results
    label = st.session_state.get("screen_label", "")
    st.success(f"Scanned {meta.get('scanned', 0)} tickers at {meta.get('generated_at')} "
               f"· Jev {'on' if meta.get('jev_enabled') else 'off'}"
               + (f" · {label}" if label else ""))

    picks = meta.get("picks", [])
    discovered = meta.get("discovered", [])
    if picks:
        st.markdown("**Today's picks:** " + ", ".join(f"★ {p}" for p in picks))
    if discovered:
        st.markdown("**Discovered:** " + ", ".join(f"🔍 {d}" for d in discovered))

    rows = meta.get("results", [])
    if not rows:
        st.warning("No results — add tickers and run again.")
        return

    # --- Table (with the Jev hover overlay + ticker chart popup + header tips) ---
    height = min(150 + 42 * len(rows), 720)
    st.iframe(
        _screener_table_html(rows, st.session_state.get("screen_charts") or {}),
        height=height,
    )
    st.caption("Hover the **AI** badge for Jev's analysis · hover a **ticker** for its chart · hover a **column heading** for what it means.")

    # --- Chart ---
    st.subheader("Price chart")
    _render_screener_chart(rows)


# --------------------------------------------------------------------------- #
# Backtest tab
# --------------------------------------------------------------------------- #
def _render_backtest() -> None:
    st.title("Backtest")
    st.caption("Replays the momentum strategy over daily history with trading "
               "costs, compared against buy-and-hold SPY. Rule-based only — Jev is "
               "not replayed.")

    if not st.session_state.watchlist:
        st.warning("Watchlist is empty. Add tickers on the Screener tab first.")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        years = st.number_input("Years", min_value=0.5, max_value=15.0, value=5.0, step=0.5)
        top_k = st.number_input("Top K", min_value=1, max_value=10, value=2, step=1)
    with c2:
        rebalance = st.number_input("Rebalance (days)", min_value=1, max_value=60, value=5, step=1)
        stop_loss = st.number_input("Stop-loss %", value=10.0, step=0.5)
    with c3:
        take_profit = st.number_input("Take-profit %", value=25.0, step=0.5)
        trailing = st.number_input("Trailing % (0=off)", value=0.0, step=0.5)
    with c4:
        commission = st.number_input("Commission bps", value=5.0, step=0.5)
        slippage = st.number_input("Slippage bps", value=5.0, step=0.5)

    if st.button("Run backtest", type="primary"):
        params = {
            "years": years,
            "top_k": int(top_k),
            "rebalance_days": int(rebalance),
            "stop_loss_pct": stop_loss,
            "take_profit_pct": take_profit,
            "trailing_stop_pct": trailing if trailing else None,
            "commission_bps": commission,
            "slippage_bps": slippage,
        }
        with st.spinner("Running backtest… (downloads history, can take ~30s)"):
            st.session_state.backtest_results = backtest.run(st.session_state.watchlist, params)

    result = st.session_state.backtest_results
    if result is None:
        st.info("Press **Run backtest** to test the strategy.")
        return
    if "error" in result:
        st.error(result["error"])
        return

    # --- Summary cards ---
    m = result.get("metrics") or {}
    b = result.get("benchmark") or {}
    cols = st.columns(6)
    cols[0].metric("Final value", _fmt_money(result.get("final_value")))
    cols[1].metric("Total return", _fmt_pct(m.get("total_return_pct")))
    cols[2].metric("CAGR", _fmt_pct(m.get("cagr_pct")))
    cols[3].metric("Sharpe", _fmt_num(m.get("sharpe")))
    cols[4].metric("Max drawdown", _fmt_pct(m.get("max_drawdown_pct")))
    cols[5].metric("Trades", result.get("trades_count", 0))

    st.markdown(f"**Benchmark** ({result.get('benchmark', {}).get('symbol', 'SPY')}): "
                f"total return {_fmt_pct(b.get('total_return_pct'))} · "
                f"CAGR {_fmt_pct(b.get('cagr_pct'))} · "
                f"max drawdown {_fmt_pct(b.get('max_drawdown_pct'))}")

    # --- Equity curve ---
    series = result.get("series", [])
    bench_series = result.get("benchmark_series", [])
    strategy = pd.Series({p["date"]: p["value"] for p in series}, name="strategy")
    bench = pd.Series({p["date"]: p["value"] for p in bench_series}, name="benchmark")
    curve = pd.concat([strategy, bench], axis=1)
    curve.index = pd.to_datetime(curve.index)
    st.subheader("Equity curve vs benchmark")
    st.line_chart(curve, height=340)

    # --- Trades table ---
    st.subheader("Trades")
    trades = result.get("trades", [])
    if trades:
        tdf = pd.DataFrame(trades)[["date", "ticker", "side", "reason", "price", "shares", "value", "pnl"]]
        tdf["pnl"] = tdf["pnl"].apply(lambda v: _fmt_money(v))
        st.dataframe(tdf, use_container_width=True, hide_index=True)
    else:
        st.info("No trades were generated.")


# --------------------------------------------------------------------------- #
# Evaluate tab
# --------------------------------------------------------------------------- #
def _render_evaluate() -> None:
    st.title("Evaluate Jev")
    st.caption("Measures whether Jev's judgments beat the rule-only momentum "
               "ranking. Needs logged decisions with forward returns — stays nearly "
               "empty until ~20 trading days pass after a screener run.")

    top_k = st.number_input("Top K for ranking test", min_value=1, max_value=10,
                            value=config.AUTO_PICK_COUNT, step=1)
    if st.button("Refresh report", type="primary"):
        with st.spinner("Building evaluation report…"):
            st.session_state.eval_results = evaluate.evaluate(top_k=int(top_k))

    report = st.session_state.eval_results
    if report is None:
        st.info("Press **Refresh report** to load the evaluation.")
        return

    ov = report.get("overview") or {}
    cols = st.columns(6)
    cols[0].metric("Total decisions", ov.get("total_entries", "—"))
    cols[1].metric("Resolved", ov.get("resolved_entries", "—"))
    cols[2].metric("Screen runs", ov.get("total_screen_runs", "—"))
    cols[3].metric("Resolved runs", ov.get("resolved_screen_runs", "—"))
    cols[4].metric("Auto-pick K", ov.get("auto_pick_count", "—"))
    first = (ov.get("first_decision") or "")[:10]
    last = (ov.get("last_decision") or "")[:10]
    cols[5].metric("Data window", f"{first} → {last}" if first and last else "—")

    # Entry verdicts
    st.subheader("Entry verdicts")
    verdicts = (report.get("entry_verdicts") or {}).get("verdict") or []
    if verdicts:
        vdf = pd.DataFrame(verdicts).rename(columns={
            "label": "Verdict", "mean_forward_20d": "Mean 20d return", "n": "N"})
        vdf["Mean 20d return"] = vdf["Mean 20d return"].apply(_fmt_pct)
        st.dataframe(vdf, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved entry decisions yet.")

    # Buy candidate
    st.subheader("Buy candidate")
    buys = (report.get("entry_verdicts") or {}).get("is_buy_candidate") or []
    if buys:
        bdf = pd.DataFrame(buys).rename(columns={
            "label": "Buy candidate", "mean_forward_20d": "Mean 20d return", "n": "N"})
        bdf["Mean 20d return"] = bdf["Mean 20d return"].apply(_fmt_pct)
        st.dataframe(bdf, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved buy-candidate decisions yet.")

    # Ranking test
    st.subheader("Ranking test")
    rs = (report.get("ranking") or {}).get("summary") or {}
    cols = st.columns(3)
    cols[0].metric("Final-score avg", _fmt_pct(rs.get("final_mean")))
    cols[1].metric("Momentum avg", _fmt_pct(rs.get("momentum_mean")))
    cols[2].metric("Diff (Final − Momentum)", _fmt_pct(rs.get("diff")))
    runs = (report.get("ranking") or {}).get("runs") or []
    if runs:
        rdf = pd.DataFrame(runs)
        rdf["final_mean"] = rdf["final_mean"].apply(_fmt_pct)
        rdf["momentum_mean"] = rdf["momentum_mean"].apply(_fmt_pct)
        rdf["diff"] = rdf["diff"].apply(_fmt_pct)
        rdf = rdf.rename(columns={
            "run_at": "Run", "k": "K", "final_mean": "Final avg",
            "momentum_mean": "Momentum avg", "diff": "Diff"})
        st.dataframe(rdf, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved screen runs yet.")

    # Calibration
    st.subheader("Score calibration")
    calib = report.get("calibration") or {}
    rows = []
    for key in ("risk_at_entry", "trend_quality", "momentum_sustainability"):
        c = calib.get(key) or {}
        rows.append({
            "Score": c.get("field", key),
            "Correlation": _fmt_num(c.get("corr"), 2),
            "N": c.get("n", "—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Caveats
    st.subheader("Caveats")
    for caveat in report.get("caveats") or []:
        st.markdown(f"- {caveat}")


# --------------------------------------------------------------------------- #
# Help tab
# --------------------------------------------------------------------------- #
def _render_help() -> None:
    st.title("Help")
    st.markdown(
        """
        TrendFinder checks a list of stocks, ranks them by momentum, and lets you
        test a trading plan against history. Prices arrive late, and none of this
        is real advice.

        **Screener** — enter a ticker or company name; it checks that stock plus a
        couple of **discovered** names (🔍) from the wider market, ranks them by
        momentum, and enriches them with **Jev's** judgment (trend quality, entry
        risk, buy candidacy, and a verdict). Discovered names aren't saved.

        **Jev** — to enable Jev's judgments, paste an OpenRouter API key in the
        sidebar. The key is kept only for your session; leave it blank to use the
        server's key, if one is configured.

        **Backtest** — replays the momentum strategy over history with trading
        costs and compares it against buying SPY and doing nothing.

        **Evaluate** — tests whether Jev's judgments actually improve on the plain
        momentum ranking. It needs ~20 trading days of forward history, so it
        starts nearly empty.

        **Jev** — an AI judgment layer that runs on **OpenRouter**. To enable it,
        paste your own OpenRouter API key in the sidebar (get one at
        [openrouter.ai/keys](https://openrouter.ai/keys)); it is kept only for your
        session. When enabled it rates trend quality, entry risk, momentum
        sustainability, and buy candidacy, then gives a verdict. It never buys or
        sells for you.

        **Caveats:** prices are delayed and free (yfinance); results are a heuristic,
        not a prediction; nothing here is investment advice.
        """
    )


# --------------------------------------------------------------------------- #
# Sidebar + dispatch
# --------------------------------------------------------------------------- #
def main() -> None:
    with st.sidebar:
        st.header("📈 TrendFinder")
        page = st.radio("Navigation", ["Screener", "Backtest", "Evaluate", "Help"])
        theme_choice = st.radio("Theme", ["System", "Light", "Dark"], index=0, key="theme_choice")
        st.session_state["theme_mode"] = theme_choice.lower()

        st.divider()
        st.subheader("Jev")
        st.caption("Jev runs on **OpenRouter**. Paste your own OpenRouter API key "
                   "below to enable it for this session.")
        st.text_input(
            "OpenRouter API key",
            type="password",
            key="openrouter_key",
            placeholder="sk-or-v1-… (OpenRouter key)",
            help="OpenRouter API key — the credential Jev uses to run. "
                 "It is kept only for this browser session and never written to disk.",
        )
        st.caption("Get an OpenRouter key at [openrouter.ai/keys](https://openrouter.ai/keys)")
        # Whatever is typed wins; otherwise fall back to the environment key.
        config.set_openrouter_api_key(
            st.session_state.get("openrouter_key", "").strip() or _ENV_OPENROUTER_KEY
        )
        jev = "on" if config.has_jev() else "off — add your OpenRouter key above"
        st.caption(f"Jev: {jev}")
        st.caption(f"Model: `{config.JEV_MODEL}`")

    _inject_theme_css(st.session_state.get("theme_mode", "system"))

    if page == "Screener":
        _render_screener()
    elif page == "Backtest":
        _render_backtest()
    elif page == "Evaluate":
        _render_evaluate()
    else:
        _render_help()

    st.caption("Educational only. Not investment advice.")


if __name__ == "__main__":
    main()
