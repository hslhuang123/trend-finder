const $ = (sel, root = document) => root.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const money = (n) =>
  (n < 0 ? "-$" : "$") +
  Math.abs(Number(n)).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const pct = (n) => (n > 0 ? "+" : "") + Number(n).toFixed(2) + "%";
const cls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
const num = (v, digits = 2) =>
  v === null || v === undefined ? "—" : Number(v).toFixed(digits);

function formatMarketCap(value, currency) {
  if (value === null || value === undefined || isNaN(value)) return "—";
  const sym = currency === "CAD" ? "C$" : currency && currency !== "USD" ? currency + " " : "$";
  const units = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [size, suffix] of units) {
    if (Math.abs(value) >= size) {
      const scaled = value / size;
      return `${sym}${scaled.toFixed(scaled >= 100 ? 0 : 1)}${suffix}`;
    }
  }
  return `${sym}${Number(value).toFixed(0)}`;
}

function setStatus(msg) {
  const el = $("#status");
  if (el) el.textContent = msg;
}

// ---- Theme (day / night / system) -----------------------------------------
const THEMES = ["system", "light", "dark"];
const THEME_ICONS = { system: "🌗", light: "☀️", dark: "🌙" };
const THEME_LABELS = { system: "System", light: "Day", dark: "Night" };

function getTheme() {
  return localStorage.getItem("theme") || "system";
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  try {
    localStorage.setItem("theme", theme);
  } catch {
    /* ignore (e.g. private mode) */
  }
  updateThemeBtn();
}

function updateThemeBtn() {
  const btn = $("#theme-btn");
  if (!btn) return;
  const theme = getTheme();
  btn.textContent = THEME_ICONS[theme] || THEME_ICONS.system;
  btn.title = `Theme: ${THEME_LABELS[theme] || "System"}`;
}

function initTheme() {
  applyTheme(getTheme());
}

function cycleTheme() {
  const idx = THEMES.indexOf(getTheme());
  applyTheme(THEMES[(idx + 1) % THEMES.length]);
}

async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    const badge = $("#jev-badge");
    badge.textContent = cfg.jev_enabled
      ? `Jev: ${cfg.jev_model}`
      : "Jev: off (no API key)";
    badge.classList.toggle("off", !cfg.jev_enabled);
  } catch {
    /* ignore */
  }
}

function fmtPctCell(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + Number(v).toFixed(digits) + "%";
}

async function runScreener() {
  const useJev = $("#jev-toggle")?.checked ?? true;
  const spinner = $("#spinner");
  setStatus(useJev ? "Screening with Jev… (can take ~30s)" : "Screening…");
  if (spinner) spinner.hidden = false;
  $("#run-btn").disabled = true;
  try {
    const data = await api(`/api/screen?jev=${useJev ? 1 : 0}`);
    renderScreen(data);
    setStatus(`Scanned ${data.scanned} tickers at ${data.generated_at}`);
  } catch (e) {
    setStatus("Screener failed: " + e.message);
  } finally {
    if (spinner) spinner.hidden = true;
    $("#run-btn").disabled = false;
  }
}

// Feather-style icon for the screener row delete action.
const ICON_DELETE =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>';

function renderScreen(data) {
  const body = $("#screen-table tbody");
  body.innerHTML = "";
  (data.results || []).forEach((r, i) => {
    const j = r.jev || {};
    const co = r.company || {};
    const tr = document.createElement("tr");
    if (r.discovered) tr.classList.add("row-discovered");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td class="ticker-cell"></td>
      <td>${money(r.price)}</td>
      <td>${formatMarketCap(co.market_cap, co.currency)}</td>
      <td class="${cls(r.change_1d_pct)}">${pct(r.change_1d_pct)}</td>
      <td class="${cls(r.change_5d_pct)}">${pct(r.change_5d_pct)}</td>
      <td>${num(r.rsi, 0)}</td>
      <td>${num(r.volume_ratio)}</td>
      <td>${num(r.atr_pct)}</td>
      <td>${num(r.momentum_score, 3)}</td>
      <td class="ai-cell"></td>
      <td class="row-actions">
        ${r.discovered ? "" : `<button class="delete" data-ticker="${r.ticker}" title="Remove ${r.ticker} from watchlist" aria-label="Remove ${r.ticker}">${ICON_DELETE}</button>`}
      </td>`;
    const tickerCell = tr.querySelector(".ticker-cell");
    const tickerSpan = makeTickerSpan(r.ticker, co);
    if (r.pick) {
      tickerSpan.classList.add("pick-bold");
      const star = document.createElement("span");
      star.className = "pick-star";
      star.textContent = "★";
      star.title = "Today's pick";
      tickerCell.appendChild(star);
    }
    if (r.discovered) {
      const mark = document.createElement("span");
      mark.className = "discover-mark";
      mark.textContent = "🔍";
      mark.title = "Auto-discovered just now (not in your watchlist)";
      tickerCell.appendChild(mark);
    }
    tickerCell.appendChild(tickerSpan);
    tr.querySelector(".ai-cell").appendChild(makeAiBadge(r, j));
    body.appendChild(tr);
  });
  if (!(data.results || []).length) {
    body.innerHTML = `<tr><td colspan="12" class="muted">No results. Add tickers and run again.</td></tr>`;
  }
}

function makeTickerSpan(ticker, company) {
  const span = document.createElement("span");
  span.className = "ticker";
  span.textContent = ticker;
  span.dataset.ticker = ticker;
  const name = (company && company.name) || "";
  const desc = (company && company.description) || "";
  span.dataset.name = name || ticker;
  span.dataset.desc = desc || "No description available.";
  span.dataset.tip = "1";
  return span;
}

function fmt1(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(1);
}

function makeAiBadge(r, j) {
  const span = document.createElement("span");
  span.className = "ai-badge";
  const verdict = j && j.verdict ? j.verdict : null;
  span.textContent = verdict ? verdict.replace("_", " ") : "—";
  if (verdict === "buy_now") span.classList.add("buy-now");
  else if (verdict === "watch") span.classList.add("watch");
  else if (verdict === "avoid") span.classList.add("avoid");

  const buyText =
    j && j.is_buy_candidate != null ? Math.round(j.is_buy_candidate * 100) + "%" : "—";
  const lines = [
    `Quality: ${fmt1(j && j.trend_quality)} / 2`,
    `Risk: ${fmt1(j && j.risk_at_entry)} / 2`,
    `Buy: ${buyText}`,
    `Verdict: ${verdict ? verdict.replace("_", " ") : "—"}`,
    `Final: ${r.final_score != null ? Number(r.final_score).toFixed(3) : "—"}`,
  ];
  span.dataset.tip = "1";
  span.dataset.name = "Jev Analysis";
  span.dataset.desc = lines.join("\n");
  return span;
}

let _tooltip = null;
let _tipTarget = null;

function getTooltip() {
  if (!_tooltip) {
    _tooltip = document.createElement("div");
    _tooltip.className = "tooltip";
    document.body.appendChild(_tooltip);
  }
  return _tooltip;
}

function positionTooltip(x, y) {
  const tip = getTooltip();
  const pad = 14;
  const rect = tip.getBoundingClientRect();
  let left = x + pad;
  let top = y + pad;
  if (left + rect.width > window.innerWidth - 8) left = x - rect.width - pad;
  if (top + rect.height > window.innerHeight - 8) top = y - rect.height - pad;
  tip.style.left = Math.max(8, left) + "px";
  tip.style.top = Math.max(8, top) + "px";
}

function showTooltip(target, x, y) {
  const tip = getTooltip();
  const title = document.createElement("div");
  title.className = "tip-title";
  title.textContent = target.dataset.name || "";
  const desc = document.createElement("div");
  desc.className = "tip-desc";
  desc.textContent = target.dataset.desc || "No description available.";
  tip.replaceChildren(title, desc);
  tip.classList.add("show");
  _tipTarget = target;
  positionTooltip(x, y);
}

function hideTooltip() {
  if (_tooltip) _tooltip.classList.remove("show");
  _tipTarget = null;
}

const isTouchDevice = !!(window.matchMedia && window.matchMedia("(hover: none)").matches);

// ---- Chart popup (hover a ticker) ------------------------------------------
const CHART_RANGES = ["1d", "5d", "1m", "3m", "6m", "1y", "5y", "10y"];
let _chartPopup = null;
let _chartTicker = null;
let _chartRange = "6m";
let _chartReq = 0;
let _hideChartTimer = null;

function getChartPopup() {
  if (!_chartPopup) {
    _chartPopup = document.createElement("div");
    _chartPopup.className = "chart-popup";

    const head = document.createElement("div");
    head.className = "cp-head";
    const tickerEl = document.createElement("span");
    tickerEl.className = "cp-ticker";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cp-close";
    close.textContent = "✕";
    close.title = "Close";
    close.addEventListener("click", hideChartPopup);
    head.append(tickerEl, close);

    const name = document.createElement("div");
    name.className = "cp-name";

    const ranges = document.createElement("div");
    ranges.className = "cp-ranges";
    for (const r of CHART_RANGES) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cp-range";
      btn.textContent = r;
      btn.dataset.range = r;
      btn.addEventListener("click", () => {
        _chartRange = r;
        setActiveRange();
        loadChart(_chartTicker, r);
      });
      ranges.appendChild(btn);
    }

    const chart = document.createElement("div");
    chart.className = "cp-chart";

    const status = document.createElement("div");
    status.className = "cp-status";

    _chartPopup.append(head, name, ranges, chart, status);
    document.body.appendChild(_chartPopup);
  }
  return _chartPopup;
}

function setActiveRange() {
  const popup = getChartPopup();
  popup.querySelectorAll(".cp-range").forEach((b) => {
    b.classList.toggle("active", b.dataset.range === _chartRange);
  });
}

function positionChartPopup(x, y) {
  const popup = getChartPopup();
  const rect = popup.getBoundingClientRect();
  const pad = 14;
  let left = x + pad;
  let top = y + pad;
  if (left + rect.width > window.innerWidth - 8) left = x - rect.width - pad;
  if (top + rect.height > window.innerHeight - 8) top = y - rect.height - pad;
  popup.style.left = Math.max(8, left) + "px";
  popup.style.top = Math.max(8, top) + "px";
}

function shortDesc(desc) {
  const s = String(desc || "").trim();
  if (!s) return "";
  return s.length > 220 ? s.slice(0, 220).replace(/\s+\S*$/, "") + "…" : s;
}

function showChartPopup(ticker, name, desc, x, y) {
  const popup = getChartPopup();
  _chartTicker = ticker;
  const tickerEl = popup.querySelector(".cp-ticker");
  tickerEl.textContent = ticker;
  tickerEl.dataset.name = name || ticker;
  tickerEl.dataset.desc = shortDesc(desc);
  tickerEl.dataset.tip = "1";
  popup.querySelector(".cp-name").textContent = name || "";
  setActiveRange();
  popup.classList.add("show");
  positionChartPopup(x, y);
  loadChart(ticker, _chartRange);
}

function hideChartPopup() {
  clearTimeout(_hideChartTimer);
  if (_chartPopup) _chartPopup.classList.remove("show");
  _chartTicker = null;
}

function scheduleHideChartPopup() {
  clearTimeout(_hideChartTimer);
  _hideChartTimer = setTimeout(hideChartPopup, 250);
}

function cancelHideChartPopup() {
  clearTimeout(_hideChartTimer);
}

async function loadChart(ticker, range) {
  const req = ++_chartReq;
  const popup = getChartPopup();
  const chartEl = popup.querySelector(".cp-chart");
  const statusEl = popup.querySelector(".cp-status");
  if (statusEl) statusEl.textContent = "Loading…";
  try {
    const data = await api(`/api/chart/${encodeURIComponent(ticker)}?range=${range}`);
    if (req !== _chartReq) return; // stale response
    renderChartPopup(chartEl, data.points || []);
    if (statusEl) {
      const n = (data.points || []).length;
      statusEl.textContent = n ? `${n} points` : "No data";
    }
  } catch (err) {
    if (req !== _chartReq) return;
    chartEl.replaceChildren();
    if (statusEl) statusEl.textContent = "Failed: " + err.message;
  }
}

function fmtPrice(v) {
  if (v >= 1000) return Math.round(v).toLocaleString();
  if (v >= 10) return v.toFixed(0);
  return v.toFixed(2);
}

function shortDate(s) {
  const d = String(s || "");
  return d.length > 10 ? d.slice(5, 10) : d;
}

function renderChartPopup(chartEl, points) {
  chartEl.replaceChildren();
  if (!points || points.length < 2) {
    const p = document.createElement("div");
    p.className = "cp-empty";
    p.textContent = "No price data available.";
    chartEl.appendChild(p);
    return;
  }
  const W = 316, H = 120, padL = 46, padR = 6, padT = 8, padB = 18;
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const n = points.length;
  const x = (i) => padL + (i * (W - padL - padR)) / (n - 1);
  const y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart cp-svg" });

  // horizontal grid lines + price labels
  for (let g = 0; g <= 3; g++) {
    const val = min + (span * g) / 3;
    const gy = y(val);
    svg.appendChild(svgEl("line", { x1: padL, y1: gy, x2: W - padR, y2: gy, class: "grid" }));
    const label = svgEl("text", { x: padL - 4, y: gy + 3, class: "axis", "text-anchor": "end" });
    label.textContent = fmtPrice(val);
    svg.appendChild(label);
  }

  // price line
  const pts = points.map((p, i) => [x(i), y(p.price)]);
  const color = prices[n - 1] >= prices[0] ? "#3fb950" : "#f85149";
  svg.appendChild(svgPolyline(pts, color));

  // first/last date labels
  const start = svgEl("text", { x: padL, y: H - 4, class: "axis", "text-anchor": "start" });
  start.textContent = shortDate(points[0].date);
  svg.appendChild(start);
  const end = svgEl("text", { x: W - padR, y: H - 4, class: "axis", "text-anchor": "end" });
  end.textContent = shortDate(points[n - 1].date);
  svg.appendChild(end);

  chartEl.appendChild(svg);
}

// ---- Tooltip / chart-popup hover handling ---------------------------------
document.addEventListener("mouseover", (e) => {
  if (isTouchDevice) return;
  const tickerEl = e.target.closest && e.target.closest(".ticker");
  if (tickerEl) {
    cancelHideChartPopup();
    const t = tickerEl.dataset.ticker;
    if (_chartTicker !== t) {
      showChartPopup(t, tickerEl.dataset.name, tickerEl.dataset.desc, e.clientX, e.clientY);
    } else {
      positionChartPopup(e.clientX, e.clientY);
    }
    return;
  }
  if (_chartPopup && _chartPopup.contains(e.target)) {
    cancelHideChartPopup();
    const tipTarget = e.target.closest && e.target.closest("[data-tip]");
    if (tipTarget) showTooltip(tipTarget, e.clientX, e.clientY);
    return;
  }
  const target = e.target.closest && e.target.closest("[data-tip]");
  if (target) showTooltip(target, e.clientX, e.clientY);
});
document.addEventListener("mouseout", (e) => {
  if (isTouchDevice) return;
  if (e.target.closest && e.target.closest(".ticker")) {
    scheduleHideChartPopup();
  }
  if (_chartPopup && _chartPopup.contains(e.target)) {
    scheduleHideChartPopup();
  }
  if (e.target.closest && e.target.closest("[data-tip]")) hideTooltip();
});
document.addEventListener("mousemove", (e) => {
  if (!isTouchDevice && _tipTarget) positionTooltip(e.clientX, e.clientY);
});
// Touch devices have no hover: tap a ticker/heading to show the bubble, tap away to hide.
document.addEventListener("click", (e) => {
  if (!isTouchDevice) return;
  if (_chartPopup && _chartPopup.contains(e.target)) {
    // Tap the ticker name to see its description; let range buttons work.
    const tipEl = e.target.closest && e.target.closest("[data-tip]");
    if (tipEl && tipEl.classList.contains("cp-ticker")) {
      const x = e.clientX || window.innerWidth / 2;
      const y = e.clientY || 80;
      if (_tipTarget === tipEl && _tooltip && _tooltip.classList.contains("show")) {
        hideTooltip();
      } else {
        showTooltip(tipEl, x, y);
      }
    }
    return;
  }
  const tickerEl = e.target.closest && e.target.closest(".ticker");
  if (tickerEl) {
    const t = tickerEl.dataset.ticker;
    const x = e.clientX || window.innerWidth / 2;
    const y = e.clientY || 80;
    if (_chartTicker === t && _chartPopup && _chartPopup.classList.contains("show")) {
      hideChartPopup();
    } else {
      showChartPopup(t, tickerEl.dataset.name, tickerEl.dataset.desc, x, y);
    }
    return;
  }
  const target = e.target.closest && e.target.closest("[data-tip]");
  if (!target) {
    hideChartPopup();
    hideTooltip();
    return;
  }
  const x = e.clientX || window.innerWidth / 2;
  const y = e.clientY || 80;
  if (_tipTarget === target && _tooltip && _tooltip.classList.contains("show")) {
    hideTooltip();
  } else {
    showTooltip(target, x, y);
  }
});
window.addEventListener("scroll", () => {
  hideTooltip();
  hideChartPopup();
}, true);

async function addTicker() {
  const input = $("#ticker-input");
  const raw = input.value.trim();
  if (!raw) return;
  try {
    const data = await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ query: raw }),
    });
    input.value = "";
    const r = data.resolved || {};
    const ticker = r.ticker || raw;
    const name = r.name && r.name !== ticker ? ` (${r.name})` : "";
    setStatus(data.added ? `Added ${ticker}${name}` : `${ticker} is already in the watchlist`);
    $("#watchlist-count").textContent = `${data.tickers.length} tickers in watchlist`;
  } catch (e) {
    alert(e.message);
  }
}

async function removeTicker(ticker) {
  if (!confirm(`Remove ${ticker} from the watchlist?`)) return;
  try {
    const data = await api(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
    setStatus(`Removed ${ticker} from watchlist`);
    $("#watchlist-count").textContent = `${data.tickers.length} tickers in watchlist`;
    // Remove the row from the table without a full re-run.
    const btn = document.querySelector(`button.delete[data-ticker="${CSS.escape(ticker)}"]`);
    const row = btn && btn.closest("tr");
    if (row) row.remove();
  } catch (e) {
    alert(e.message);
  }
}

async function loadWatchlistCount() {
  try {
    const data = await api("/api/watchlist");
    $("#watchlist-count").textContent = `${data.tickers.length} tickers in watchlist`;
  } catch {
    /* ignore */
  }
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function svgPolyline(points, color, dashed = false) {
  const poly = svgEl("polyline", {
    points: points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
    fill: "none",
    stroke: color,
    "stroke-width": "2",
  });
  if (dashed) poly.setAttribute("stroke-dasharray", "5 4");
  return poly;
}

function renderBacktestChart(port, bench, initial) {
  const el = $("#bt-chart");
  if (!el) return;
  el.replaceChildren();
  if (!port || port.length < 2) {
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = "No data to chart.";
    el.appendChild(p);
    return;
  }
  const W = 820, H = 280, padL = 56, padR = 16, padT = 14, padB = 28;
  const benchMap = new Map((bench || []).map((b) => [b.date, b.value]));
  const pv = port.map((p) => p.value);
  const bv = port.map((p) => benchMap.get(p.date)).filter((v) => v !== undefined);
  const all = pv.concat(bv).concat([initial]);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const n = port.length;
  const x = (i) => padL + (i * (W - padL - padR)) / Math.max(1, n - 1);
  const y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart" });
  for (let g = 0; g <= 4; g++) {
    const val = min + (span * g) / 4;
    const gy = y(val);
    svg.appendChild(svgEl("line", { x1: padL, y1: gy, x2: W - padR, y2: gy, class: "grid" }));
    const label = svgEl("text", { x: padL - 8, y: gy + 4, class: "axis", "text-anchor": "end" });
    label.textContent = "$" + Math.round(val / 1000) + "k";
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("line", { x1: padL, y1: y(initial), x2: W - padR, y2: y(initial), class: "baseline" }));

  const benchPts = [];
  port.forEach((p, i) => {
    const b = benchMap.get(p.date);
    if (b !== undefined) benchPts.push([x(i), y(b)]);
  });
  if (benchPts.length > 1) svg.appendChild(svgPolyline(benchPts, "#8b949e", true));
  svg.appendChild(svgPolyline(port.map((p, i) => [x(i), y(p.value)]), "#58a6ff"));

  const startLabel = svgEl("text", { x: padL, y: H - 6, class: "axis", "text-anchor": "start" });
  startLabel.textContent = port[0].date;
  svg.appendChild(startLabel);
  const endLabel = svgEl("text", { x: W - padR, y: H - 6, class: "axis", "text-anchor": "end" });
  endLabel.textContent = port[n - 1].date;
  svg.appendChild(endLabel);

  el.appendChild(svg);
}

function renderBacktest(data) {
  const compare = $("#bt-compare");
  compare.replaceChildren();
  const m = data.metrics || {};
  const b = data.benchmark || {};
  const cells = [
    ["Final value", money(data.final_value), "How much your pretend account is worth at the end."],
    ["Total return", fmtPctCell(m.total_return_pct), "How much you made or lost in total, as a percentage."],
    ["CAGR", fmtPctCell(m.cagr_pct), "The average growth per year."],
    ["Sharpe", m.sharpe ?? "—", "How much you earned for the risk you took. Around 1 or more is good; below 0 means you lost money."],
    ["Max drawdown", fmtPctCell(m.max_drawdown_pct), "The biggest drop from a high point - how bad the worst dip got."],
    [b.symbol ? `${b.symbol} buy & hold` : "Benchmark", fmtPctCell(b.total_return_pct), `What you would have if you just bought ${b.symbol || "the benchmark"} on day one and did nothing.`],
    ["Trades", data.trades_count ?? "—", "Total number of buys and sells the plan made."],
  ];
  for (const [label, value, desc] of cells) {
    const card = document.createElement("div");
    card.className = "card";
    const l = document.createElement("div");
    l.className = "label";
    l.textContent = label;
    l.dataset.tip = "1";
    l.dataset.name = label;
    l.dataset.desc = desc;
    const v = document.createElement("div");
    v.className = "value";
    v.textContent = value;
    card.append(l, v);
    compare.appendChild(card);
  }

  renderBacktestChart(data.series || [], data.benchmark_series || [], data.initial_cash || 100000);

  const legend = $("#bt-legend");
  if (legend) {
    legend.replaceChildren();
    const item = (color, text, dashed, desc) => {
      const span = document.createElement("span");
      span.className = "legend-item";
      if (desc) {
        span.dataset.tip = "1";
        span.dataset.name = text;
        span.dataset.desc = desc;
      }
      const sw = document.createElement("span");
      sw.className = "swatch";
      if (dashed) {
        sw.style.background = "none";
        sw.style.borderTop = `2px dashed ${color}`;
        sw.style.height = "0";
      } else {
        sw.style.background = color;
      }
      span.append(sw, document.createTextNode(text));
      return span;
    };
    const benchName = b.symbol || "Benchmark";
    legend.appendChild(item(
      "#58a6ff", "Strategy", false,
      "The momentum strategy: each time it re-ranks, it holds the top few names from your watchlist, and sells when one hits a stop-loss, a take-profit, a trailing stop, or drops off the list."
    ));
    legend.appendChild(item(
      "#8b949e", benchName, true,
      `What would have happened if you put the same money into ${benchName} on day one and did nothing.`
    ));
  }

  const body = $("#bt-trades tbody");
  body.innerHTML = "";
  const allTrades = data.trades || [];
  const trades = allTrades.slice().reverse().slice(0, 200);
  const note = $("#bt-trades-note");
  if (note) {
    const total = data.trades_count ?? allTrades.length;
    note.textContent =
      `Each row is one single buy or sell — not a different stock. ` +
      `Showing the most recent ${trades.length} of ${total} trades. ` +
      `Top K caps how many you hold at once, not how many the plan trades over time, ` +
      `so the same few companies repeat.`;
  }
  for (const t of trades) {
    const tr = document.createElement("tr");
    const pnl = t.pnl === null || t.pnl === undefined ? "—" : money(t.pnl);
    tr.innerHTML = `
      <td class="muted">${t.date}</td>
      <td>${t.ticker}</td>
      <td>${t.side}</td>
      <td class="muted">${t.reason}</td>
      <td>${money(t.price)}</td>
      <td>${t.shares}</td>
      <td>${money(t.value)}</td>
      <td class="${cls(t.pnl || 0)}">${pnl}</td>`;
    body.appendChild(tr);
  }
  if (!trades.length) {
    body.innerHTML = `<tr><td colspan="8" class="muted">No trades.</td></tr>`;
  }
}

async function runBacktest(event) {
  event.preventDefault();
  const form = $("#bt-form");
  const params = new URLSearchParams();
  for (const field of form.elements) {
    if (field.name && field.value !== "") params.set(field.name, field.value);
  }
  setStatus("Running backtest… (downloading history)");
  $("#bt-run").disabled = true;
  try {
    const data = await api(`/api/backtest?${params.toString()}`);
    if (data.error) throw new Error(data.error);
    renderBacktest(data);
    setStatus(`Done — ${(data.series || []).length} days, ${data.trades_count} trades`);
  } catch (e) {
    setStatus("Backtest failed: " + e.message);
  } finally {
    $("#bt-run").disabled = false;
  }
}

document.addEventListener("click", (e) => {
  const delBtn = e.target.closest("button.delete");
  if (delBtn) removeTicker(delBtn.dataset.ticker);
});

function card(label, value, tip, valueCls) {
  const c = document.createElement("div");
  c.className = "card";
  const l = document.createElement("div");
  l.className = "label";
  l.textContent = label;
  if (tip) {
    l.dataset.tip = "1";
    l.dataset.name = label;
    l.dataset.desc = tip;
  }
  const v = document.createElement("div");
  v.className = "value";
  v.textContent = value;
  if (valueCls) v.classList.add(valueCls);
  c.appendChild(l);
  c.appendChild(v);
  return c;
}

function fillRow(tbody, cells) {
  const tr = document.createElement("tr");
  tr.innerHTML = cells
    .map((c) => `<td class="${c.cls || ""}">${c.text}</td>`)
    .join("");
  tbody.appendChild(tr);
}

function emptyRow(tbody, cols, msg) {
  tbody.innerHTML = `<tr><td colspan="${cols}" class="muted">${msg}</td></tr>`;
}

function renderEvaluation(d) {
  const ov = d.overview || {};
  const ovEl = $("#ev-overview");
  ovEl.innerHTML = "";
  ovEl.appendChild(card("Total decisions", ov.total_entries ?? "—"));
  ovEl.appendChild(card("Resolved", ov.resolved_entries ?? "—"));
  ovEl.appendChild(card("Screen runs", ov.total_screen_runs ?? "—"));
  ovEl.appendChild(card("Resolved runs", ov.resolved_screen_runs ?? "—"));
  ovEl.appendChild(card("Auto-pick K", ov.auto_pick_count ?? "—"));
  const win =
    ov.first_decision && ov.last_decision
      ? `${String(ov.first_decision).slice(0, 10)} → ${String(ov.last_decision).slice(0, 10)}`
      : "—";
  ovEl.appendChild(card("Data window", win));

  const vb = $("#ev-verdicts tbody");
  vb.innerHTML = "";
  const verdicts = (d.entry_verdicts || {}).verdict || [];
  verdicts.forEach((v) => {
    fillRow(vb, [
      { text: v.label },
      { text: fmtPctCell(v.mean_forward_20d), cls: cls(v.mean_forward_20d) },
      { text: v.n ?? "—" },
    ]);
  });
  if (!verdicts.length) emptyRow(vb, 3, "No resolved entry decisions yet.");

  const bb = $("#ev-buy tbody");
  bb.innerHTML = "";
  const buys = (d.entry_verdicts || {}).is_buy_candidate || [];
  buys.forEach((v) => {
    fillRow(bb, [
      { text: v.label },
      { text: fmtPctCell(v.mean_forward_20d), cls: cls(v.mean_forward_20d) },
      { text: v.n ?? "—" },
    ]);
  });
  if (!buys.length) emptyRow(bb, 3, "No resolved buy-candidate decisions yet.");

  $("#ev-k").textContent = `K=${d.top_k ?? "?"}`;

  const rc = $("#ev-rank-cards");
  rc.innerHTML = "";
  const rs = (d.ranking || {}).summary || {};
  rc.appendChild(card("Final-score avg",
    rs.final_mean === null || rs.final_mean === undefined ? "—" : fmtPctCell(rs.final_mean),
    "Mean 20-day forward return of the top-K by Final score.", cls(rs.final_mean)));
  rc.appendChild(card("Momentum avg",
    rs.momentum_mean === null || rs.momentum_mean === undefined ? "—" : fmtPctCell(rs.momentum_mean),
    "Mean 20-day forward return of the top-K by Momentum.", cls(rs.momentum_mean)));
  rc.appendChild(card("Diff",
    rs.diff === null || rs.diff === undefined ? "—" : fmtPctCell(rs.diff),
    "Final avg minus Momentum avg. Positive means Jev's re-rank did better.", cls(rs.diff)));

  const rb = $("#ev-rank tbody");
  rb.innerHTML = "";
  const runs = (d.ranking || {}).runs || [];
  runs.forEach((r) => {
    fillRow(rb, [
      { text: r.run_at },
      { text: r.k },
      { text: fmtPctCell(r.final_mean), cls: cls(r.final_mean) },
      { text: fmtPctCell(r.momentum_mean), cls: cls(r.momentum_mean) },
      { text: r.diff === null || r.diff === undefined ? "—" : fmtPctCell(r.diff), cls: cls(r.diff) },
    ]);
  });
  if (!runs.length) emptyRow(rb, 5, "No resolved screen runs yet.");

  const cb = $("#ev-calib tbody");
  cb.innerHTML = "";
  const calib = d.calibration || {};
  ["risk_at_entry", "trend_quality", "momentum_sustainability"].forEach((k) => {
    const c = calib[k] || {};
    fillRow(cb, [
      { text: c.field || k },
      { text: c.corr === null || c.corr === undefined ? "—" : num(c.corr, 2) },
      { text: c.n ?? "—" },
    ]);
  });

  const caves = $("#ev-caveats");
  caves.innerHTML = "";
  (d.caveats || []).forEach((t) => {
    const li = document.createElement("li");
    li.textContent = t;
    caves.appendChild(li);
  });
}

async function runEvaluation() {
  setStatus("Loading evaluation…");
  $("#ev-run").disabled = true;
  try {
    const d = await api("/api/evaluation");
    renderEvaluation(d);
    setStatus(`Report generated at ${d.generated_at}`);
  } catch (e) {
    setStatus("Evaluation failed: " + e.message);
  } finally {
    $("#ev-run").disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  if (window.PAGE === "screener") {
    $("#run-btn")?.addEventListener("click", runScreener);
    $("#add-ticker-btn")?.addEventListener("click", addTicker);
    $("#ticker-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addTicker();
    });
    loadWatchlistCount();
  }
  if (window.PAGE === "backtest") {
    $("#bt-form")?.addEventListener("submit", runBacktest);
  }
  if (window.PAGE === "evaluate") {
    $("#ev-run")?.addEventListener("click", runEvaluation);
    runEvaluation();
  }

  initTheme();
  $("#theme-btn")?.addEventListener("click", cycleTheme);
});
