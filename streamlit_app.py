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
from datetime import date
import json
import re
from string import Template

import pandas as pd
import streamlit as st

from trendfinder import (
    backtest,
    company,
    config,
    decisions,
    discover,
    market_data,
    screener,
)

st.set_page_config(page_title="TrendFinder", layout="wide", page_icon="📈")

# Remember any key supplied through the environment (e.g. Streamlit secrets) so
# an empty OpenRouter box in the UI can fall back to it.
_ENV_OPENROUTER_KEY = config.OPENROUTER_API_KEY

# How many freshly discovered names each screener run aims to surface.
DISCOVER_COUNT = 5


def _session_api_key() -> str:
    """The OpenRouter key for the current browser session.

    The key lives only in Streamlit's per-session state (never in a shared module
    global), so one user's key can never leak into another user's requests.
    Falls back to the server's environment key when the box is left blank.
    """
    return (st.session_state.get("openrouter_key") or "").strip() or _ENV_OPENROUTER_KEY

# Make sure the decision-log tables exist (used by the screener).
decisions.init_db()


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _fmt_money(v: float | None) -> str:
    if v is None or v != v:  # None or NaN
        return "—"
    return f"${v:,.2f}"


def _fmt_market_cap(v: float | None, currency: str = "USD") -> str:
    if v is None:
        return "—"
    sym = "C$" if currency == "CAD" else "$"
    for size, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(v) >= size:
            return f"{sym}{v / size:.1f}{suffix}"
    return f"{sym}{v:,.0f}"


# Market-cap class pill shown next to each ticker in the screener tables. It sits in
# the ticker cell (not its own column) so the shared mobile CSS, which hides columns
# by position, keeps working.
_CAP_TAG_CSS = """
.cap-tag { display: inline-block; margin-left: 6px; padding: 0 6px; border: 1px solid; border-radius: 9px;
  font-size: 10px; font-weight: 600; line-height: 16px; text-transform: uppercase; letter-spacing: .03em; vertical-align: middle; }
.cap-large { color: #2f81f7; }
.cap-mid { color: #a371f7; }
.cap-small { color: var(--muted, #8b949e); }
/* The shared mobile CSS hides column 5 (1d %) below 760px; keep it visible next to 5d %. */
@media (max-width: 760px) { #screen-table th:nth-child(5), #screen-table td:nth-child(5) { display: table-cell !important; } }
"""


def _cap_tag(market_cap: float | None, band: str | None = None) -> str:
    """HTML pill: Large (>= the mid-cap ceiling), Mid, or Small cap.

    Classified from the listing-currency market cap against the discovery bands
    (config.DISCOVER_MIN/MAX_MARKET_CAP); falls back to the discovery band when the
    market cap is unknown. Empty when neither is known.
    """
    if market_cap:
        if market_cap >= config.DISCOVER_MAX_MARKET_CAP:
            key = "large"
        elif market_cap >= config.DISCOVER_MIN_MARKET_CAP:
            key = "mid"
        else:
            key = "small"
    elif band:
        key = band.split("-")[0]
    else:
        return ""
    return f'<span class="cap-tag cap-{key}" title="{key.title()}-cap company">{key.title()}</span>'


def _cell(v) -> str:
    """HTML-safe table cell text. `$` is entity-encoded so markdown never reads
    two prices in one table as a LaTeX span."""
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return _html.escape(str(v)).replace("$", "&#36;")


def _html_table(df: pd.DataFrame, numeric: tuple[str, ...] = ()) -> str:
    """Render a DataFrame as a themed HTML table (st.dataframe draws on a canvas
    with Streamlit's own colours, which cannot follow the Day/Night toggle)."""
    head = "".join(f"<th>{_cell(c)}</th>" for c in df.columns)
    body = "".join(
        "<tr>" + "".join(
            f'<td class="num">{_cell(v)}</td>' if c in numeric else f"<td>{_cell(v)}</td>"
            for c, v in row.items()
        ) + "</tr>"
        for row in df.to_dict("records")
    )
    return (f'<div class="tf-table-wrap"><table class="tf-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


_EQUITY_COLORS = {"strategy": "#2f81f7", "benchmark": "#d29922"}


def _equity_svg(series: dict[str, list[dict]], width: int = 800, height: int = 320) -> str:
    """Inline-SVG line chart of {name: [{date, value}]}. Text, grid and axes take
    their colours from CSS (st.line_chart renders on a fixed white background)."""
    pts = {
        name: [(pd.Timestamp(p["date"]).toordinal(), float(p["value"])) for p in rows]
        for name, rows in series.items() if rows
    }
    if not pts:
        return ""
    xs = [x for rows in pts.values() for x, _ in rows]
    ys = [y for rows in pts.values() for _, y in rows]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_y = (y1 - y0) * 0.05 or 1.0
    y0, y1 = y0 - pad_y, y1 + pad_y
    left, right, top, bottom = 70, 12, 30, 28

    def sx(x: float) -> float:
        return left + (x - x0) / ((x1 - x0) or 1) * (width - left - right)

    def sy(y: float) -> float:
        return top + (1 - (y - y0) / (y1 - y0)) * (height - top - bottom)

    def money(v: float) -> str:
        return f"${v / 1000:,.0f}k" if abs(v) >= 1000 else f"${v:,.0f}"

    parts = []
    for i in range(5):  # y grid + labels
        v = y0 + (y1 - y0) * i / 4
        y = sy(v)
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{money(v)}</text>')
    for i in range(5):  # x labels
        d = round(x0 + (x1 - x0) * i / 4)
        anchor = "start" if i == 0 else "end" if i == 4 else "middle"
        parts.append(f'<text x="{sx(d):.1f}" y="{height - 6}" text-anchor="{anchor}">'
                     f"{date.fromordinal(d).strftime('%Y-%m')}</text>")
    for n, (name, rows) in enumerate(pts.items()):
        color = _EQUITY_COLORS.get(name, "#8b949e")
        points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in rows)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{points}"/>')
        lx = left + 8 + n * 110
        parts.append(f'<rect x="{lx}" y="8" width="14" height="3" fill="{color}"/>'
                     f'<text x="{lx + 20}" y="13">{_cell(name)}</text>')
    return (f'<div class="tf-chart"><svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="Equity curve vs benchmark">{"".join(parts)}</svg></div>')


def _md_escape(text: str) -> str:
    """Escape markdown/LaTeX specials in third-party text (headlines)."""
    for ch in ("\\", "[", "]", "$", "*", "_", "`"):
        text = text.replace(ch, "\\" + ch)
    return text


def _news_word(score: float | None) -> str:
    """Plain-English label for Jev's 0-2 news-tone score (1 = neutral)."""
    if score is None:
        return ""
    if score >= 1.5:
        return "positive"
    if score >= 0.5:
        return "neutral"
    return "negative"


def _fmt_num(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _quality_word(score: float | None) -> str:
    """Plain-English label for Jev's 0-2 trend-quality score."""
    if score is None:
        return ""
    if score >= 1.5:
        return "strong"
    if score >= 0.5:
        return "moderate"
    return "weak"


def _risk_word(score: float | None) -> str:
    """Plain-English label for Jev's 0-2 entry-risk score (higher = riskier)."""
    if score is None:
        return ""
    if score >= 1.5:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _verdict_reason(verdict, quality, risk) -> str:
    """A concise reason for Jev's verdict, derived from the quality/risk ratings."""
    if verdict == "buy_now":
        return "good trend, low/medium risk, clear entry"
    if verdict == "watch":
        if risk is not None and risk >= 1.5:
            return "interesting, but entry risk is high"
        if quality is not None and quality < 0.5:
            return "trend is weak"
        return "qualifies, but not a clear entry yet"
    if verdict == "avoid":
        if risk is not None and risk >= 1.5:
            return "entry risk too high"
        if quality is not None and quality < 0.5:
            return "trend is weak"
        return "not a good candidate"
    return ""


def _why_verdict(r: dict) -> str:
    """Plain-English explanation of Jev's verdict for a screened row: its ratings,
    what looks stretched in the stock's own numbers, and what the news added."""
    j = r.get("jev") or {}
    verdict, quality, risk = j.get("verdict"), j.get("trend_quality"), j.get("risk_at_entry")
    if not verdict or quality is None or risk is None:
        return ""
    trend = ("strong" if quality >= 1.5 else "decent" if quality >= 0.5 else "weak and choppy")
    risk_word = "low" if risk < 0.5 else "moderate" if risk < 1.5 else "high"

    stretched = []
    rsi, ma20, d5, atr = r.get("rsi"), r.get("above_ma20_pct"), r.get("change_5d_pct"), r.get("atr_pct")
    if d5 is not None and d5 >= 10:
        stretched.append(f"it is already up {d5:.0f}% in 5 days")
    if ma20 is not None and ma20 >= 10:
        stretched.append(f"its price is {ma20:.0f}% above its 20-day average")
    if rsi is not None and rsi >= 70:
        stretched.append(f"it looks overbought (RSI {rsi:.0f})")
    if atr is not None and atr >= 5:
        stretched.append(f"it swings a lot (about {atr:.0f}% a day)")
    because = ("That's because " + ", ".join(stretched[:-1]) + (" and " if len(stretched) > 1 else "")
               + stretched[-1] + ".") if stretched else ""

    negative_news = j.get("news_catalyst") == "negative"
    if verdict == "buy_now":
        parts = [f"The trend is {trend} and the risk of buying now is {risk_word} "
                 f"({risk:.1f} out of 2), so this looks like a good moment to buy."]
    elif verdict == "watch":
        if negative_news:
            parts = [f"The trend is {trend} and the risk is {risk_word}, but recent news "
                     "shows a negative event, so it was held at watch instead of buy now."]
        else:
            parts = [f"The trend is {trend} and the risk is {risk_word} ({risk:.1f} out of 2), "
                     "but it isn't a clear buy yet.",
                     because,
                     "Jev would wait for a better entry or more confirmation."]
    elif risk >= 1.5:
        parts = [f"The trend is {trend}, but buying now looks risky ({risk:.1f} out of 2).",
                 because or "The setup looks stretched or poorly supported.",
                 "Stocks in this spot often pull back, so Jev would stay out for now."]
    elif quality < 0.5:
        parts = ["The trend is weak or choppy, so there is no clear direction to follow."]
    else:
        parts = ["Jev doesn't see a good setup right now."]

    tone = j.get("news_sentiment")
    already_said = negative_news and verdict == "watch"
    if tone is not None and not already_said:
        word = _news_word(tone)
        catalyst = j.get("news_catalyst")
        if catalyst in ("positive", "negative"):
            clash = (catalyst == "negative" and word != "negative") or (catalyst == "positive" and word == "negative")
            parts.append(f"Recent news is {word} overall, {'but' if clash else 'and'} "
                         f"a specific {catalyst} event stands out.")
        else:
            parts.append(f"Recent news is {word}.")
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Screener table as a custom HTML component (keeps the Jev hover overlay).
# Embeds the exact same static/style.css as the Flask app so the table looks
# identical; only the hover tooltip is kept (no price-chart popup).
# --------------------------------------------------------------------------- #
# Theme toggle (System / Light / Dark) for both the Streamlit UI and the table.
# --------------------------------------------------------------------------- #
# Streamlit's own widgets are themed natively (and ignore our Day/Night toggle), so
# every surface the app uses is restyled explicitly from one palette per mode.
_PALETTES = {
    "dark": {"scheme": "dark", "bg": "#0e1116", "panel": "#161b22", "surface": "#1c232c",
             "border": "#2a323d", "hover": "#2a323d", "text": "#e6edf3", "muted": "#8b949e",
             "link": "#58a6ff"},
    "light": {"scheme": "light", "bg": "#ffffff", "panel": "#f0f2f6", "surface": "#f0f2f6",
              "border": "#d0d7de", "hover": "#dfe3ea", "text": "#1f2328", "muted": "#656d76",
              "link": "#0969da"},
}

_SURFACE_CSS = Template("""
:root { color-scheme: $scheme; }
html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"], [data-testid="stHeader"] { background-color: $bg !important; }
[data-testid="stSidebar"] { background-color: $panel !important; }
[data-testid="stMetric"] { background-color: $panel !important; }
[data-testid="stAlert"], [data-testid="stNotification"], [data-testid="stExpander"] details, [data-testid="stExpander"] summary { background-color: $surface !important; }
/* Inputs: text, number, select, multiselect (control surface, text, placeholder, focus). */
[data-testid="stTextInputRootElement"], [data-testid="stTextInputRootElement"] > div, [data-testid="stNumberInputContainer"], [data-testid="stSelectbox"] div[data-rac], [data-testid="stMultiSelect"] div[role="group"], [data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"] { background-color: $surface !important; border-color: $border !important; }
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"], [data-testid="stTextInputRootElement"] button { background-color: transparent !important; color: $text !important; }
input, textarea { background-color: transparent !important; color: $text !important; -webkit-text-fill-color: $text !important; caret-color: $text !important; }
input::placeholder, textarea::placeholder { color: $muted !important; -webkit-text-fill-color: $muted !important; opacity: 1 !important; }
/* Chrome's autofill / history-preview paints a light-blue fill and its own text colour; repaint it with the surface colour so our text stays legible. */
input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus, input:-webkit-autofill:active { -webkit-text-fill-color: $text !important; caret-color: $text !important; box-shadow: 0 0 0 1000px $surface inset !important; transition: background-color 9999s ease-out 0s; }
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stNumberInputContainer"]:focus-within, [data-testid="stMultiSelect"] div[role="group"]:focus-within, [data-testid="stSelectbox"] div[data-rac]:focus-within { border-color: $link !important; }
[data-testid="stSelectbox"] svg, [data-testid="stMultiSelect"] svg, [data-testid="stNumberInput"] svg, [data-testid="stTooltipIcon"] svg, [data-testid="stTooltipIcon"] button { color: $muted !important; }
/* Filled chevrons/clear icons need fill; the help icon is stroke-only (fill="none"). */
[data-testid="stSelectbox"] svg:not([fill="none"]), [data-testid="stMultiSelect"] svg:not([fill="none"]), [data-testid="stNumberInput"] svg:not([fill="none"]) { fill: $muted !important; }
[data-testid="stMultiSelect"] [data-tag] svg, [data-testid="stMultiSelect"] [data-tag] button { color: #ffffff !important; fill: none !important; }
/* Dropdown lists (portals): select, multiselect, and the older baseweb popovers. */
[data-testid$$="Dropdown"], [data-baseweb="popover"] > div, [data-baseweb="menu"], ul[role="listbox"] { background-color: $surface !important; border: 1px solid $border !important; }
[role="option"], [role="option"] *, [data-baseweb="popover"] li, [data-baseweb="popover"] li * { background-color: transparent !important; color: $text !important; }
[role="option"]:hover, [role="option"][data-focused="true"], [role="option"][data-selected="true"], [role="option"][aria-selected="true"], [data-baseweb="popover"] li:hover { background-color: $hover !important; }
/* Tooltips and help bubbles. */
[data-baseweb="tooltip"], [role="tooltip"], [data-testid="stTooltipContent"], [data-testid="stTooltipErrorContent"] { background-color: $surface !important; color: $text !important; }
[data-baseweb="tooltip"] *, [role="tooltip"] *, [data-testid="stTooltipContent"] *, [data-testid="stTooltipErrorContent"] * { color: $text !important; }
/* Buttons: secondary follows the palette; primary keeps the accent. */
[data-testid="stBaseButton-secondary"] { background-color: $surface !important; color: $text !important; border-color: $border !important; }
[data-testid="stBaseButton-secondary"] * { color: $text !important; }
[data-testid="stBaseButton-primary"] { background-color: #0969da !important; border-color: #0969da !important; }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] * { color: #ffffff !important; }
/* App-rendered HTML table and equity chart (see _html_table / _equity_svg). */
.tf-table-wrap { overflow: auto; max-height: 420px; border: 1px solid $border; border-radius: 8px; }
.tf-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.tf-table th, .tf-table td { padding: 6px 10px; border-bottom: 1px solid $border; text-align: left; white-space: nowrap; color: $text; }
.tf-table th { position: sticky; top: 0; background: $panel; color: $muted; font-weight: 600; }
.tf-table td.num { text-align: right; }
.tf-chart { color: $text; }
.tf-chart text { fill: $muted; font-size: 14px; }
.tf-chart .grid { stroke: $border; stroke-width: 1; }
""")

# Forcing every text node to the palette colour is only needed in dark mode; in
# light mode Streamlit's own text colours already read correctly.
_DARK_TEXT_CSS = Template("""
h1,h2,h3,h4,h5,h6,p,span,label,div,strong,em,li { color: $text !important; }
a { color: $link !important; }
[data-testid="stMetric"], [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color: $text !important; }
[data-testid="stSidebar"] .stRadio label, [data-testid="stSidebar"] .stRadio p { color: $text !important; }
""")

# Layout tweaks applied in every theme (not just dark). Streamlit's default
# metric value is 36px, which is oversized for a row of six summary cards.
_LAYOUT_CSS = """
[data-testid="stMetricValue"] { font-size: 1.5rem !important; line-height: 1.25 !important; }
"""


def _mode_css(name: str) -> str:
    p = _PALETTES[name]
    css = _SURFACE_CSS.substitute(p)
    return css + _DARK_TEXT_CSS.substitute(p) if name == "dark" else css


def _theme_css(mode: str) -> str:
    if mode == "dark":
        return _mode_css("dark") + _LAYOUT_CSS
    if mode == "system":
        return _mode_css("light") + f"@media (prefers-color-scheme: dark) {{\n{_mode_css('dark')}\n}}" + _LAYOUT_CSS
    return _mode_css("light") + _LAYOUT_CSS


def _inject_theme_css(mode: str) -> None:
    try:
        st.markdown(f"<style>{_theme_css(mode)}</style>", unsafe_allow_html=True)
    except Exception as exc:  # noqa: BLE001 - theme CSS must never break the app
        print(f"[theme] could not apply {mode!r} theme CSS: {exc!r}")


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
const CHART_RANGES = ['1d', '5d', '1m', '3m', '6m', '1y'];
const SVG_NS = 'http://www.w3.org/2000/svg';
const tooltip = document.getElementById('tf-tip');
let tipTarget = null;
let chartPopup = null, chartTicker = null, chartRange = '6m', hideChartTimer = null, chartPinned = false;
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
function shortDate(s) {
  s = String(s);
  if (s.length <= 10) return s;
  return chartRange === '1d' ? s.slice(11, 16) : s.slice(5, 10);
}

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
function hideChartPopup() { clearTimeout(hideChartTimer); if (chartPopup) chartPopup.classList.remove('show'); chartTicker = null; chartPinned = false; }
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
  const entry = (TF.charts && TF.charts[chartTicker]) || {};
  const pts = (chartRange === '1d' || chartRange === '5d')
    ? (entry[chartRange] || [])
    : sliceRange(entry.daily || [], chartRange);
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

  // Crosshair: vertical dashed line + price/date label following the pointer.
  const guide = svgEl('line', { y1: padT, y2: H - padB, stroke: '#8b949e', 'stroke-width': 1, 'stroke-dasharray': '3 3', visibility: 'hidden', 'pointer-events': 'none' });
  const dot = svgEl('circle', { r: 3, fill: color, stroke: '#0d1117', 'stroke-width': 1, visibility: 'hidden', 'pointer-events': 'none' });
  const lblBg = svgEl('rect', { rx: 3, height: 15, fill: '#0d1117', stroke: '#30363d', visibility: 'hidden', 'pointer-events': 'none' });
  const lbl = svgEl('text', { y: padT + 10, fill: '#e6edf3', 'font-size': 9, visibility: 'hidden', 'pointer-events': 'none' });
  svg.append(guide, dot, lblBg, lbl);
  const hide = () => [guide, dot, lblBg, lbl].forEach((el) => el.setAttribute('visibility', 'hidden'));
  svg.addEventListener('mouseleave', hide);
  svg.addEventListener('mousemove', (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    let i = Math.round(((vx - padL) / (W - padL - padR)) * (n - 1));
    i = Math.max(0, Math.min(n - 1, i));
    const px = x(i), py = y(points[i].price);
    guide.setAttribute('x1', px); guide.setAttribute('x2', px);
    dot.setAttribute('cx', px); dot.setAttribute('cy', py);
    const d = String(points[i].date);
    const when = d.length > 10 ? (chartRange === '1d' ? d.slice(11, 16) : d.slice(5, 16)) : d;
    lbl.textContent = points[i].price.toFixed(2) + '  ' + when;
    const w = lbl.getComputedTextLength() + 8;
    const lx = Math.max(padL, Math.min(W - padR - w, px - w / 2));
    lblBg.setAttribute('x', lx); lblBg.setAttribute('y', padT - 3); lblBg.setAttribute('width', w);
    lbl.setAttribute('x', lx + 4);
    [guide, dot, lblBg, lbl].forEach((el) => el.setAttribute('visibility', 'visible'));
  });
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
    chartPinned = true;
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
  // A popup the pointer has entered is pinned: leaving it does not close it.
  if (!chartPinned && e.target.closest && e.target.closest('.ticker')) scheduleHideChartPopup();
  if (e.target.closest && e.target.closest('[data-tip]')) hideTip();
});
document.addEventListener('mousemove', (e) => { if (!isTouch && tipTarget) positionTip(e.clientX, e.clientY); });
document.addEventListener('click', (e) => {
  // Clicks inside the popup (range buttons, chart) never close it; only its X does.
  if (chartPopup && chartPopup.contains(e.target)) { if (chartPopup.classList.contains('show')) chartPinned = true; return; }
  const tickerEl = e.target.closest && e.target.closest('.ticker');
  if (tickerEl) {
    const t = tickerEl.dataset.ticker;
    const open = chartTicker === t && chartPopup && chartPopup.classList.contains('show');
    if (isTouch && open) { hideChartPopup(); return; }
    if (!open) showChartPopup(t, tickerEl.dataset.name, tickerEl.dataset.desc, e.clientX || window.innerWidth / 2, e.clientY || 80);
    chartPinned = true;
    return;
  }
  // Click outside the popup closes it.
  hideChartPopup();
  if (!isTouch) return;
  const target = e.target.closest && e.target.closest('[data-tip]');
  if (!target) { hideTip(); return; }
  if (tipTarget === target && tooltip.classList.contains('show')) hideTip();
  else showTip(target, e.clientX || window.innerWidth / 2, e.clientY || 80);
});
// Clicking outside the iframe (rest of the Streamlit page) blurs this window.
window.addEventListener('blur', hideChartPopup);
window.addEventListener('scroll', () => { hideTip(); if (!chartPinned) hideChartPopup(); }, true);
"""


def _precompute_chart_data(results: list[dict]) -> dict:
    """Fetch daily price history for each displayed ticker (for the hover chart)."""
    charts: dict = {}
    tickers = [r["ticker"] for r in results]
    if not tickers:
        return charts
    from concurrent.futures import ThreadPoolExecutor
    specs = {"daily": ("1y", "1d"), "1d": ("1d", "5m"), "5d": ("5d", "15m")}

    def fetch(t):
        return t, {
            k: [[p["date"], p["price"]]
                for p in market_data.fetch_price_history(t, period=per, interval=iv)]
            for k, (per, iv) in specs.items()
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        pairs = list(ex.map(fetch, tickers))
    for ticker, entry in pairs:
        if any(entry.values()):
            charts[ticker] = entry
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
        q_raw = j.get("trend_quality")
        rk_raw = j.get("risk_at_entry")
        q = _fmt_num(q_raw, 1) if q_raw is not None else "—"
        rk = _fmt_num(rk_raw, 1) if rk_raw is not None else "—"
        q_word = _quality_word(q_raw)
        rk_word = _risk_word(rk_raw)
        q_disp = f"{q} / 2" + (f" ({q_word})" if q_word else "")
        rk_disp = f"{rk} / 2" + (f" ({rk_word})" if rk_word else "")
        q_note = "0 = weak, 2 = strong" if q_word else "how strong/clear the trend is"
        rk_note = "0 = low, 2 = high (lower is safer)" if rk_word else "risk of buying now (lower is safer)"
        buy = "—"
        if j.get("is_buy_candidate") is not None:
            buy = "yes" if j["is_buy_candidate"] else "no"
        final = _fmt_num(r.get("final_score"), 3)
        verdict_note = _verdict_reason(verdict, q_raw, rk_raw) or "overall call: buy now / watch / avoid"
        why = _why_verdict(r)
        why_line = f"Why: {why}\n" if why else ""
        if j:
            tip = (
                f"Quality: {q_disp} — {q_note}\n"
                f"Risk: {rk_disp} — {rk_note}\n"
                f"Buy: {buy} — qualifies as a buy candidate? (no if risk is high or trend is weak)\n"
                f"Verdict: {verdict_label} — {verdict_note}\n"
                f"{why_line}"
                f"Final: {final} — overall ranking score (momentum + AI; higher is better)"
            )
            tip_title = "AI Analysis"
        else:
            if _session_api_key():
                note = "Not analyzed yet — pick this ticker under AI analysis below to run Jev on it."
            else:
                note = "Not analyzed — add an OpenRouter key in the sidebar to enable the AI analysis."
            tip = (
                f"{note}\n"
                f"Final: {final} — ranking score (= momentum until analyzed)"
            )
            tip_title = "No AI analysis"

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
            f"data-name=\"{esc(name)}\" data-desc=\"{esc(desc)}\">{esc(r['ticker'])}</span>"
            f"{_cap_tag(co.get('market_cap'), r.get('cap_band'))}</td>"
        )
        ai_cell = (
            f"<td class=\"ai-cell\"><span class=\"ai-badge {badge_cls(verdict)}\" "
            f"data-tip=\"1\" data-name=\"{tip_title}\" data-desc=\"{esc(tip)}\">"
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
        "<th data-tip=\"1\" data-name=\"Ticker\" data-desc=\"Stock symbol, with a Large / Mid / Small market-cap tag. Hover the ticker itself for the company name and description.\">Ticker</th>"
        "<th data-tip=\"1\" data-name=\"Price\" data-desc=\"Latest delayed closing price.\">Price</th>"
        "<th data-tip=\"1\" data-name=\"Market cap\" data-desc=\"Market capitalization: total value of the company's shares (latest available). C$ means Canadian dollars.\">Market cap</th>"
        "<th data-tip=\"1\" data-name=\"1d %\" data-desc=\"Percent change from the previous close.\">1d %</th>"
        "<th data-tip=\"1\" data-name=\"5d %\" data-desc=\"Percent change over the last 5 trading days.\">5d %</th>"
        "<th data-tip=\"1\" data-name=\"RSI\" data-desc=\"14-day Relative Strength Index, 0-100. Above 70 is overbought, below 30 is oversold, around 50 is neutral.\">RSI</th>"
        "<th data-tip=\"1\" data-name=\"Vol×\" data-desc=\"Volume ratio: 5-day average volume divided by the 20-day average. Above 1 means busier than usual.\">Vol×</th>"
        "<th data-tip=\"1\" data-name=\"ATR %\" data-desc=\"Average True Range as a percent of price, a volatility measure. Higher means bigger swings.\">ATR %</th>"
        "<th data-tip=\"1\" data-name=\"Momentum\" data-desc=\"The app's technical score from 5-day return, distance above the 20-day average, volume and RSI, minus an ATR penalty. Roughly -1 to +1.\">Momentum</th>"
        "<th data-tip=\"1\" data-name=\"AI\" data-desc=\"AI analysis, filled in only for tickers you analyze on demand (see AI analysis below the tables). Hover a row's AI badge to see Quality, Risk, Buy, Verdict and Final.\">AI</th>"
        "<th></th>"
        "</tr></thead>"
    )
    return (
        "<!doctype html><html" + theme_attr + "><head><meta charset=\"utf-8\">"
        f"<style>{_load_static_css()}{_CAP_TAG_CSS}</style></head><body>"
        + "<div class=\"table-wrap\"><table id=\"screen-table\">" + headers
        + "<tbody>" + "".join(rows) + "</tbody></table></div>"
        + "<div class=\"tooltip\" id=\"tf-tip\"><div class=\"tip-title\"></div><div class=\"tip-desc\"></div></div>"
        + f"<script>window.TF_DATA = {tf_data};</script>"
        + f"<script>{_SCREENER_JS}</script></body></html>"
    )


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
if "screen_results" not in st.session_state:
    st.session_state.screen_results = None
if "screen_charts" not in st.session_state:
    st.session_state.screen_charts = {}
if "screened_tickers" not in st.session_state:
    st.session_state.screened_tickers = None
if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = None


# --------------------------------------------------------------------------- #
# Screener tab
# --------------------------------------------------------------------------- #
def _render_screener() -> None:
    st.title("Trending stocks")
    st.caption("Screener — checks the stocks you enter plus at least five freshly discovered "
               "names, ranks them by momentum, and enriches them with Jev's judgment.")

    # --- What to screen (one or more tickers / company names) ---
    query = st.text_input(
        "Screen one or more tickers or company names",
        placeholder="e.g. AAPL, CVE.TO, Rogers  (separate with commas)",
        key="screen_query",
        autocomplete="off",  # no browser history dropdown / autofill preview in the box
        help="Enter one or more tickers or company names, separated by commas "
             "(e.g. \"AAPL, CVE.TO, Rogers\"). The screener matches each one and "
             "then adds at least five freshly discovered names.",
    )
    col_exchange, col_window = st.columns(2)
    exchange = col_exchange.selectbox(
        "Discover from exchange",
        list(discover.EXCHANGES),
        index=list(discover.EXCHANGES).index(discover.DEFAULT_EXCHANGE),
        key="discover_exchange",
        help="Discovered names come from this exchange (North America only): a mix of "
             "mid-caps ($2B–$10B market cap) and large-caps (over $10B), in the "
             "listing's own currency.",
    )
    window = col_window.selectbox(
        "Best performers over",
        list(discover.PERFORMANCE_WINDOWS),
        index=list(discover.PERFORMANCE_WINDOWS).index(discover.DEFAULT_WINDOW),
        key="discover_window",
        help="Discovery ranks the exchange's names by their return over this period, "
             "separately for mid-caps and large-caps. Longer periods look at the "
             "250 most-traded names in each group and take several seconds more.",
    )
    skip_extended = st.checkbox(
        "Skip overextended stocks",
        value=True,
        key="discover_skip_extended",
        help=f"Drops discovered names that have already run too far: RSI above "
             f"{discover.MAX_RSI:.0f}, more than {discover.MAX_ABOVE_MA20_PCT:.0f}% above "
             "the 20-day average, or below the 20- or 50-day average. Jev usually rates "
             "those as high entry risk. Untick to see the raw top performers.",
    )
    use_jev = bool(_session_api_key())
    if use_jev:
        st.caption("AI analysis is on demand — after screening, pick one or more tickers under *AI analysis* to run Jev on them.")
    else:
        st.caption("Add your OpenRouter API key in the sidebar to enable the on-demand AI analysis.")

    if st.button("Run screener", type="primary"):
        tokens = [t.strip() for t in re.split(r"[,\n;]+", query) if t.strip()]
        tickers: list[str] = []
        missing: list[str] = []
        for token in tokens:
            resolved = company.resolve(token)
            tk = resolved.get("ticker")
            if tk and tk not in tickers:
                tickers.append(tk)
            elif not tk:
                missing.append(token)
        if tokens and not tickers:
            st.warning(
                f"Couldn't find a ticker for: {', '.join(missing) or query}. "
                "Try symbols like AAPL, CVE.TO, or names like Rogers."
            )
        else:
            if missing:
                st.warning("Skipped (not found): " + ", ".join(missing))
            # With nothing typed, run discovery alone.
            label = ", ".join(tickers) or "discovery only"
            spinner = (
                f"Screening {label} + {DISCOVER_COUNT} discovered from {exchange}…"
                if tickers else
                f"Discovering from {exchange}…"
            )
            with st.spinner(spinner):
                # use_jev=False: no automatic AI calls; analysis is on demand below.
                st.session_state.screen_results = screener.screen(
                    use_jev=False, watchlist=tickers, discover_count=DISCOVER_COUNT,
                    top_n=50,  # keep every discovered candidate
                    discover_exchange=exchange, discover_window=window,
                    discover_skip_extended=skip_extended,
                )
            # Precompute price history so the hover chart popup works (no API in the
            # iframe). Stored in session_state so it's not refetched on every rerun.
            with st.spinner("Preparing charts…"):
                st.session_state.screen_charts = _precompute_chart_data(
                    (st.session_state.screen_results or {}).get("results", [])
                )
            st.session_state["screen_label"] = label
            # The Backtest tab reuses these stocks (no persisted watchlist); in a
            # discovery-only run that is the discovered name.
            st.session_state["screened_tickers"] = (
                tickers or (st.session_state.screen_results or {}).get("discovered") or []
            )
            st.session_state["backtest_results"] = None
            st.session_state["ai_tickers"] = []  # previous picks may not be in the new results

    results = st.session_state.screen_results
    if results is None:
        st.info("Enter tickers or company names above (optional) and press **Run screener**. "
                "Leave the box empty to run discovery only.")
        return

    meta = results
    label = st.session_state.get("screen_label", "")
    st.success(f"Scanned {meta.get('scanned', 0)} tickers at {meta.get('generated_at')}"
               + (f" · {label}" if label else ""))

    picks = meta.get("picks", [])
    if picks:
        st.markdown("**Today's picks:** " + ", ".join(f"★ {p}" for p in picks))

    rows = meta.get("results", [])
    if not rows:
        st.warning("No results — try another exchange or period, or enter tickers.")
        return

    charts = st.session_state.get("screen_charts") or {}
    main_rows = [r for r in rows if not r.get("discovered")]
    disc_rows = [r for r in rows if r.get("discovered")]

    # --- Table (with the Jev hover overlay + ticker chart popup + header tips) ---
    if main_rows:
        height = min(150 + 42 * len(main_rows), 720)
        st.iframe(_screener_table_html(main_rows, charts), height=height)
        st.caption("Hover the **AI** badge for the AI analysis · hover a **ticker** for its chart · hover a **column heading** for what it means.")

    # --- Discovered table (freshly-found names; 'buy now' only when Jev is on) ---
    st.subheader("Discovered")
    if disc_rows:
        disc_height = min(150 + 42 * len(disc_rows), 720)
        st.iframe(_screener_table_html(disc_rows, charts), height=disc_height)
        n = len(disc_rows)
        n_mid = sum(1 for r in disc_rows if r.get("cap_band") == "mid-cap")
        n_large = sum(1 for r in disc_rows if r.get("cap_band") == "large-cap")
        st.caption(f"{n} freshly discovered top performer{'s' if n != 1 else ''} "
                   f"({n_mid} mid-cap, {n_large} large-cap). "
                   "Shown for this run only, never saved.")
        if n < DISCOVER_COUNT:
            st.info(f"Only {n} candidate{'s' if n != 1 else ''} found on this exchange for this period — "
                    "try another exchange or period.")
    else:
        st.info("No discovered candidate this run — try another exchange or period.")

    # --- On-demand AI analysis (no automatic Jev calls) ---
    st.subheader("AI analysis")
    by_ticker = {r["ticker"]: r for r in rows}
    selected = st.multiselect(
        "Tickers to analyze",
        list(by_ticker),
        key="ai_tickers",
        help="Jev is only called for the tickers you pick here, when you press the button "
             "(one call per ticker), so you control the AI cost.",
    )
    chosen = [by_ticker[t] for t in selected if t in by_ticker]
    use_news = st.checkbox(
        "Include news from the past 7 days",
        value=True,
        key="ai_news",
        help="Sends up to 10 recent headlines (Google News) to Jev along with the price "
             "indicators, so it can weigh catalysts like earnings or downgrades. "
             "Adds a little to each call's size.",
    )
    if not use_jev:
        st.info("Add your OpenRouter API key in the sidebar to run the AI analysis.")
    elif chosen:
        redo = sum(1 for r in chosen if r.get("jev"))
        st.caption(f"{len(chosen)} Jev call{'s' if len(chosen) != 1 else ''}"
                   + (f" — {redo} already analyzed, will be re-run" if redo else ""))
        if st.button(f"Run AI analysis ({len(chosen)})", key="ai_run"):
            with st.spinner(f"Asking Jev about {', '.join(r['ticker'] for r in chosen)}…"):
                answers = screener.analyze_rows(chosen, api_key=_session_api_key(), use_news=use_news)
            done = {t: j for t, j in answers.items() if j}
            if done:
                screener.apply_analyses(meta, done)
                st.session_state["ai_failed"] = [t for t, j in answers.items() if not j]
                st.rerun()
            else:
                st.error("Jev didn't return an answer — check your API key and try again.")
    failed = st.session_state.pop("ai_failed", None)
    if failed:
        st.warning("No answer from Jev for: " + ", ".join(failed) + ". Try again.")
    if chosen:
        table = []
        any_news = any(
            "news_sentiment" in (r.get("jev") or {}) or (r.get("jev") or {}).get("news_unavailable")
            for r in chosen
        )
        for r in chosen:
            j = r.get("jev") or {}
            q_raw, rk_raw, verdict = j.get("trend_quality"), j.get("risk_at_entry"), j.get("verdict")
            row = {
                "Ticker": r["ticker"],
                "Quality": f"{_fmt_num(q_raw, 1)} / 2" if j else "—",
                "Risk": f"{_fmt_num(rk_raw, 1)} / 2" if j else "—",
                "Buy candidate": ("yes" if j.get("is_buy_candidate") else "no") if j else "—",
                "Verdict": (verdict or "—").replace("_", " ") if j else "not analyzed",
            }
            if any_news:
                if j.get("news_unavailable"):
                    row["News"], row["Catalyst"] = "unavailable", "—"
                elif j.get("news_sentiment") is not None:
                    row["News"] = f"{_news_word(j['news_sentiment'])} ({j['news_sentiment']:.1f})"
                    row["Catalyst"] = j.get("news_catalyst") or "—"
                else:
                    row["News"], row["Catalyst"] = "—", "—"
            row["Final score"] = _fmt_num(r.get("final_score"), 3)
            row["Why"] = (_verdict_reason(verdict, q_raw, rk_raw) or "") if j else ""
            table.append(row)
        st.markdown(_html_table(pd.DataFrame(table), numeric=("Final score",)), unsafe_allow_html=True)
        for r in chosen:
            headlines = (r.get("jev") or {}).get("headlines")
            if headlines is None:
                continue
            with st.expander(f"{r['ticker']} — {len(headlines)} headline{'s' if len(headlines) != 1 else ''} from the past 7 days"):
                if not headlines:
                    st.caption("No headlines found.")
                for h in headlines:
                    text = _md_escape(h["title"])
                    link = f"[{text}]({h['link']})" if h.get("link") else text
                    st.markdown(f"- {h['date']} · {_md_escape(h['source'])} — {link}")


# --------------------------------------------------------------------------- #
# Backtest tab
# --------------------------------------------------------------------------- #
def _render_backtest() -> None:
    st.title("Backtest")
    st.caption("Runs the momentum strategy over the past daily prices of the stock "
               "you screened, including trading costs, and compares the result with "
               "simply buying and holding SPY (the S&P 500). It uses only the "
               "rule-based momentum signal — not the AI analysis.")

    tickers = st.session_state.get("screened_tickers")
    if not tickers:
        st.warning("Screen one or more stocks on the Screener tab first, then come back to backtest them.")
        return
    st.markdown(f"Backtesting **{', '.join(tickers)}** — the stock(s) you screened on the Screener tab.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        years = st.number_input("Years", min_value=0.5, max_value=15.0, value=5.0, step=0.5, width=120,
                                help="How many years of daily history to replay (0.5–15).")
        top_k = st.number_input("Top K", min_value=1, max_value=10, value=2, step=1, width=120,
                                help="How many of the best-ranked stocks to hold at once. "
                                     "Position size = equity ÷ Top K; any unused slots stay in cash.")
    with c2:
        rebalance = st.number_input("Rebalance (days)", min_value=1, max_value=60, value=5, step=1, width=120,
                                    help="How often, in trading days, the strategy re-ranks and rotates holdings.")
        stop_loss = st.number_input("Stop-loss %", value=10.0, step=0.5, width=120,
                                    help="Sell a position if it falls this far below its entry price.")
    with c3:
        take_profit = st.number_input("Take-profit %", value=25.0, step=0.5, width=120,
                                      help="Sell a position once it gains this far above its entry price.")
        trailing = st.number_input("Trailing % (0=off)", value=0.0, step=0.5, width=120,
                                   help="Sell if price drops this far from its peak since entry. 0 disables it.")
    with c4:
        commission = st.number_input("Commission bps", value=5.0, step=0.5, width=120,
                                     help="Commission per trade in basis points. 1 bp = 0.01%, so 5 bps = 0.05%.")
        slippage = st.number_input("Slippage bps", value=5.0, step=0.5, width=120,
                                   help="Assumed price slippage per trade in basis points. 1 bp = 0.01%.")

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
            st.session_state.backtest_results = backtest.run(tickers, params)

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
    st.subheader("Equity curve vs benchmark")
    st.markdown(
        _equity_svg({"strategy": result.get("series", []),
                     "benchmark": result.get("benchmark_series", [])}),
        unsafe_allow_html=True,
    )

    # --- Trades table ---
    st.subheader("Trades")
    trades = result.get("trades", [])
    if trades:
        tdf = pd.DataFrame(trades)[["date", "ticker", "side", "reason", "price", "shares", "value", "pnl"]]
        tdf["price"] = tdf["price"].map(lambda v: f"{v:,.2f}")
        tdf["shares"] = tdf["shares"].map(lambda v: f"{v:,.4f}")
        tdf["value"] = tdf["value"].map(lambda v: f"{v:,.2f}")
        tdf["pnl"] = tdf["pnl"].apply(lambda v: _fmt_money(v))
        st.markdown(_html_table(tdf, numeric=("price", "shares", "value", "pnl")), unsafe_allow_html=True)
    else:
        st.info("No trades were generated.")


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

        **Screener** — enter one or more tickers or company names (separate them with
        commas); it checks those plus at least five **discovered** names (🔍) from the
        **exchange you pick** in the *Discover from exchange* dropdown (TSX by default;
        also TSXV, NASDAQ, NYSE, NYSE American) and ranks that exchange's mid-caps ($2B–$10B)
        and large-caps (over $10B) separately by their
        return over the period in *Best performers over* (1 day, 5 days, 1 month by default,
        or 3 months). With *Skip overextended stocks* ticked (the default) it first drops
        names that have already run too far (RSI above 65, over 8% above the 20-day
        average, or below the 20/50-day averages), since Jev rates those as high
        entry risk. It then ranks everything by momentum. AI judgments (**Jev**) are
        not run automatically — pick the tickers to analyze under *AI analysis*.
        Discovered names aren't saved.

        **Jev** — to enable the on-demand AI analysis, paste an OpenRouter API key in the
        sidebar. The key is kept only for your session; leave it blank to use the
        server's key, if one is configured.

        **Backtest** — runs the momentum strategy over the past daily prices of the
        stock you screened, including trading costs, and compares the result with
        simply buying and holding SPY (the S&P 500). It uses only the rule-based
        momentum signal, not the AI analysis.

        **Jev** — an AI judgment layer that runs on **OpenRouter**. To enable it,
        paste your own OpenRouter API key in the sidebar (get one at
        [openrouter.ai/keys](https://openrouter.ai/keys)); it is kept only for your
        session. The screener never calls it automatically, to save tokens and cost:
        pick one or more tickers under *AI analysis* and press **Run AI analysis**. It then rates trend quality, entry risk, momentum
        sustainability, and buy candidacy, then gives a verdict. It never buys or
        sells for you.

        **How to read the AI analysis** (select one or more tickers under *AI analysis* below the
        tables and press **Run AI analysis**; hover its **AI** badge afterwards — its
        **Why** line explains the verdict in plain English):

        - **Quality (0–2)** — how clear and sustained the uptrend is. **2 = strong**,
          1 = moderate, 0 = weak/choppy. Higher is better.
        - **Risk (0–2)** — the risk of buying at the current price. **0 = low**,
          1 = medium, 2 = high (extended/volatile). **Lower is safer.**
          (Jev can land between levels, e.g. 1.4, so you'll see decimals.)
        - **Buy (yes/no)** — whether the stock qualifies as a buy candidate. **yes** = it
          does; **no** = it doesn't (high risk or weak trend). It is cross-checked with
          the Verdict so they can't contradict: **no** → **avoid**; **yes** → **buy now**
          or **watch**.
        - **Verdict** — the overall call: **buy now** → watch → avoid. It is
          cross-checked with **Buy** so they can't contradict: no candidate →
          **avoid**; otherwise **buy now** or **watch**.
          If Jev answers inconsistently (e.g. "buy candidate: yes" on a weak trend),
          the app reconciles Buy and Verdict from the Quality/Risk ratings so they
          always agree.
        - **Final** — the app's overall ranking score, used to sort the table; higher
          ranks first. **Not** a probability or a predicted return. It is the technical
          **momentum** score (roughly −1…+0.9) plus the AI adjustments: **Quality
          +0.15 × value** (up to +0.30), **Risk −0.15 × value** (down to −0.30),
          **Buy candidate +0.25**, **momentum sustainability +0.20**, **news tone
          ±0.15** (only when news was included: 0 for neutral, +0.15 positive, −0.15
          negative) and **Verdict** (+0.35 buy now / 0 watch / −0.45 avoid). The
          theoretical range is **−1.8…+2.15** (the ceiling is +2.15, and +0.9
          without Jev).
        - **News** — when *Include news from the past 7 days* is ticked, up to 10
          recent headlines (Google News: date, source, title; no article text) are
          sent to Jev with the price indicators. It rates their **tone**
          (negative / neutral / positive) and whether a specific **catalyst** (positive
          or negative event such as an earnings beat, downgrade or lawsuit) shows up.
          A clear negative catalyst caps the Verdict at *watch*. The headlines are
          listed under the table so you can check what Jev saw. If the news lookup
          fails, Jev is asked without news and the News column says *unavailable*.

        Roughly: a strong setup is *Quality 2, Risk 0–1, Buy yes, Verdict buy now*;
        a weak one is *Quality 0–1, Risk 2, Buy no, Verdict avoid*. These are
        opinions, not probabilities, and never place trades.

        **Screener table columns** (hover a column heading in the table for a short tip):

        - **#** — rank, best Final score first.
        - **Ticker** — the stock symbol. Hover it for the company name and a price chart.
          The pill beside it shows its size: **Large** (market cap over $10B), **Mid**
          ($2B–$10B) or **Small** (under $2B), in the listing's own currency.
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
          Hover the badge for Quality, Risk, Buy, Verdict and Final (see "How to read
          the AI analysis" above).

        **Backtest summary**

        - **Final value** — ending portfolio value = cash + shares × price.
        - **Total return** — (final value ÷ starting value − 1) × 100 (starting value = $100,000).
        - **CAGR** — compound annual growth rate = (final ÷ starting)^(1 ÷ years) − 1,
          where years = calendar days ÷ 365.25.
        - **Sharpe** — return per unit of risk = mean daily return ÷ daily volatility × √252
          (252 ≈ trading days per year); ~1 is decent, higher is better.
        - **Max drawdown** — worst peak-to-trough drop = the lowest value of
          (value − running peak) ÷ running peak, × 100.
        - **Trades** — number of fills (buys + sells).
        - **Benchmark (SPY)** — the same window if you had simply bought and held SPY,
          starting from $100,000.

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
        """
    )


# --------------------------------------------------------------------------- #
# Sidebar + dispatch
# --------------------------------------------------------------------------- #
def main() -> None:
    with st.sidebar:
        st.header("📈 TrendFinder")
        page = st.radio("Navigation", ["Screener", "Backtest", "Help"])
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
        # Set the OpenRouter key for this session. Assign the module attribute
        # directly (rather than via a helper) so a stale cached copy of the
        # config module can never break app startup.
        # Use the current session's key only — never write it to a shared global.
        jev = "on" if _session_api_key() else "off — add your OpenRouter key above"
        st.caption(f"Jev: {jev}")
        st.caption(f"Model: `{config.JEV_MODEL}`")

    _inject_theme_css(st.session_state.get("theme_mode", "system"))

    if page == "Screener":
        _render_screener()
    elif page == "Backtest":
        _render_backtest()
    else:
        _render_help()

    st.caption("Educational only. Not investment advice.")


if __name__ == "__main__":
    main()
