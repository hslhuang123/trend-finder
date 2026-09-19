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

function ccySymbol(ccy) {
  if (ccy === "CAD") return "C$";
  if (ccy && ccy !== "USD") return ccy + " ";
  return "$";
}

function moneyCcy(n, ccy) {
  return (
    ccySymbol(ccy) +
    Math.abs(Number(n)).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

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

function signalPill(p) {
  const title = (p.reasons || []).join("; ");
  if (p.signal === "SELL") return `<span class="pill sell" title="${title}">SELL</span>`;
  if (p.signal === "REVIEW") return `<span class="pill review" title="${title}">REVIEW</span>`;
  return `<span class="pill hold" title="${title}">HOLD</span>`;
}

function jevExitCell(p) {
  const j = p.jev || {};
  if (!j.action) return "—";
  const pctTxt = j.should_exit != null ? ` ${Math.round(j.should_exit * 100)}%` : "";
  return `${j.action.replace("_", " ")}${pctTxt}`;
}

function renderPortfolioReview(pr) {
  const el = $("#portfolio-review");
  if (!el) return;
  el.replaceChildren();
  if (!pr) return;
  const card = document.createElement("div");
  card.className = "card review";
  const label = document.createElement("div");
  label.className = "label";
  label.textContent = "Jev portfolio review";
  const body = document.createElement("div");
  body.className = "review-body";
  const div = pr.diversification != null ? `${Math.round(pr.diversification * 100)}%` : "—";
  body.textContent = `Advice: ${pr.advice || "—"} · Overall risk: ${pr.overall_risk ?? "—"}/2 · Diversified: ${div}`;
  card.append(label, body);
  el.appendChild(card);
}

function fmtPctCell(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + Number(v).toFixed(digits) + "%";
}

function sparkline(values) {
  const width = 260, height = 56, pad = 4;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "sparkline");
  if (!values || values.length < 2) return svg;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = pad + i * step;
      const y = height - pad - ((v - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  poly.setAttribute("points", points);
  poly.setAttribute("fill", "none");
  poly.setAttribute("stroke", values[values.length - 1] >= values[0] ? "#3fb950" : "#f85149");
  poly.setAttribute("stroke-width", "2");
  svg.appendChild(poly);
  return svg;
}

function renderPerformance(d) {
  const el = $("#performance");
  if (!el) return;
  el.replaceChildren();
  const bc = d.base_currency || "USD";
  const points = d.points || 0;

  if (points < 2) {
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = "Not enough history yet — metrics appear after a couple of daily snapshots.";
    el.appendChild(p);
    return;
  }

  const cells = [
    ["Total return", fmtPctCell(d.total_return_pct)],
    ["CAGR", fmtPctCell(d.cagr_pct)],
    ["Sharpe", d.sharpe ?? "—"],
    ["Sortino", d.sortino ?? "—"],
    ["Volatility", fmtPctCell(d.volatility_pct)],
    ["Max drawdown", fmtPctCell(d.max_drawdown_pct)],
  ];
  for (const [label, value] of cells) {
    const card = document.createElement("div");
    card.className = "card";
    const l = document.createElement("div");
    l.className = "label";
    l.textContent = label;
    const v = document.createElement("div");
    v.className = "value";
    v.textContent = value;
    card.append(l, v);
    el.appendChild(card);
  }

  const chart = document.createElement("div");
  chart.className = "card perf-chart";
  const cl = document.createElement("div");
  cl.className = "label";
  cl.textContent = `Equity curve (${bc})`;
  chart.appendChild(cl);
  chart.appendChild(sparkline((d.series || []).map((p) => p.value)));
  el.appendChild(chart);

  if (d.benchmark) {
    const card = document.createElement("div");
    card.className = "card";
    const l = document.createElement("div");
    l.className = "label";
    l.textContent = `${d.benchmark.symbol} buy & hold`;
    const v = document.createElement("div");
    v.className = "value";
    v.textContent = fmtPctCell(d.benchmark.total_return_pct);
    const sub = document.createElement("div");
    sub.className = "muted";
    sub.style.fontSize = "12px";
    const diff = (d.total_return_pct ?? 0) - (d.benchmark.total_return_pct ?? 0);
    sub.textContent = `Portfolio ${fmtPctCell(d.total_return_pct)} · ${diff >= 0 ? "ahead" : "behind"} by ${Math.abs(diff).toFixed(2)}%`;
    card.append(l, v, sub);
    el.appendChild(card);
  }
}

async function loadPerformance() {
  try {
    const d = await api("/api/performance");
    renderPerformance(d);
  } catch (e) {
    /* ignore */
  }
}

async function loadPortfolio() {
  setStatus("Loading portfolio…");
  try {
    const data = await api("/api/portfolio");

    const bc = data.base_currency || "USD";
    $("#summary").innerHTML = `
      <div class="card"><div class="label">Total value (${bc})</div><div class="value">${money(data.total_value)}</div></div>
      <div class="card"><div class="label">Cash (${bc})</div><div class="value">${money(data.cash)}</div></div>
      <div class="card"><div class="label">Market value (${bc})</div><div class="value">${money(data.market_value)}</div></div>
      <div class="card"><div class="label">Unrealized P&amp;L (${bc})</div><div class="value ${cls(data.unrealized_pnl)}">${money(data.unrealized_pnl)}</div></div>
      <div class="card"><div class="label">Realized P&amp;L (${bc})</div><div class="value ${cls(data.realized_pnl)}">${money(data.realized_pnl)}</div></div>
    `;

    const openBody = $("#open-table tbody");
    openBody.innerHTML = "";
    for (const p of data.open_positions) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="ticker-cell"></td>
        <td>${p.shares}</td>
        <td>${moneyCcy(p.entry_price, p.currency)}</td>
        <td>${moneyCcy(p.current_price, p.currency)}</td>
        <td class="${cls(p.return_pct)}">${pct(p.return_pct)}</td>
        <td class="${cls(p.unrealized_pnl)}">${money(p.unrealized_pnl)}</td>
        <td class="jev-cell">${jevExitCell(p)}</td>
        <td>${signalPill(p)}</td>
        <td><button class="sell" data-id="${p.id}" data-ticker="${p.ticker}">Sell</button></td>`;
      tr.querySelector(".ticker-cell").appendChild(makeTickerSpan(p.ticker, p.company || {}));
      openBody.appendChild(tr);
    }
    if (!data.open_positions.length) {
      openBody.innerHTML = `<tr><td colspan="9" class="muted">No open positions. Buy something from the Screener.</td></tr>`;
    }

    const closedBody = $("#closed-table tbody");
    closedBody.innerHTML = "";
    for (const p of data.closed_positions) {
      const entryBase = p.entry_price * (p.entry_fx || 1);
      const exitBase = p.exit_price * (p.exit_fx || 1);
      const pnl = (exitBase - entryBase) * p.shares;
      const ret = entryBase ? ((exitBase - entryBase) / entryBase) * 100 : 0;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="ticker-cell"></td>
        <td>${p.shares}</td>
        <td>${moneyCcy(p.entry_price, p.currency)}</td>
        <td>${moneyCcy(p.exit_price, p.currency)}</td>
        <td class="${cls(pnl)}">${money(pnl)} (${pct(ret)})</td>
        <td class="muted">${(p.exit_date || "").replace("T", " ")}</td>`;
      tr.querySelector(".ticker-cell").appendChild(makeTickerSpan(p.ticker, p.company || {}));
      closedBody.appendChild(tr);
    }
    if (!data.closed_positions.length) {
      closedBody.innerHTML = `<tr><td colspan="6" class="muted">No closed positions yet.</td></tr>`;
    }

    renderPortfolioReview(data.portfolio_review);
    setStatus(`Updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    setStatus("Portfolio failed: " + e.message);
  }
}

async function sell(id, ticker) {
  if (!confirm(`Sell ${ticker} at the latest price?`)) return;
  setStatus(`Selling ${ticker}…`);
  try {
    const res = await api("/api/sell", {
      method: "POST",
      body: JSON.stringify({ position_id: id }),
    });
    setStatus(`Sold ${ticker} at ${money(res.exit_price)}`);
    loadPortfolio().then(loadPerformance);
  } catch (e) {
    alert(e.message);
    setStatus("Sell failed");
  }
}

async function runScreener() {
  const useJev = $("#jev-toggle")?.checked ?? true;
  setStatus(useJev ? "Screening with Jev… (can take ~30s)" : "Screening…");
  $("#run-btn").disabled = true;
  try {
    const data = await api(`/api/screen?jev=${useJev ? 1 : 0}`);
    renderScreen(data);
    setStatus(`Scanned ${data.scanned} tickers at ${data.generated_at}`);
  } catch (e) {
    setStatus("Screener failed: " + e.message);
  } finally {
    $("#run-btn").disabled = false;
  }
}

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
      <td><button class="buy" data-ticker="${r.ticker}">Buy</button></td>`;
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
  const name = (company && company.name) || "";
  const desc = (company && company.description) || "";
  if (name || desc) {
    span.dataset.name = name || ticker;
    span.dataset.desc = desc || "No description available.";
    span.dataset.tip = "1";
  }
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

document.addEventListener("mouseover", (e) => {
  if (isTouchDevice) return;
  const target = e.target.closest && e.target.closest("[data-tip]");
  if (target) showTooltip(target, e.clientX, e.clientY);
});
document.addEventListener("mouseout", (e) => {
  if (isTouchDevice) return;
  if (e.target.closest && e.target.closest("[data-tip]")) hideTooltip();
});
document.addEventListener("mousemove", (e) => {
  if (!isTouchDevice && _tipTarget) positionTooltip(e.clientX, e.clientY);
});
// Touch devices have no hover: tap a ticker/heading to show the bubble, tap away to hide.
document.addEventListener("click", (e) => {
  if (!isTouchDevice) return;
  const target = e.target.closest && e.target.closest("[data-tip]");
  if (!target) {
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
window.addEventListener("scroll", hideTooltip, true);

async function buy(ticker) {
  const sharesStr = prompt(`How many shares of ${ticker}?`, "10");
  if (sharesStr === null) return;
  const shares = Number(sharesStr);
  if (!shares || shares <= 0) {
    alert("Enter a positive number of shares.");
    return;
  }
  const stop = prompt("Stop-loss % (optional, blank to skip)", "10");
  const take = prompt("Take-profit % (optional, blank to skip)", "25");
  const trail = prompt("Trailing stop % from peak (optional, blank to skip)", "");

  setStatus(`Buying ${shares} ${ticker}…`);
  try {
    const res = await api("/api/buy", {
      method: "POST",
      body: JSON.stringify({
        ticker,
        shares,
        stop_loss_pct: stop || null,
        take_profit_pct: take || null,
        trailing_stop_pct: trail || null,
      }),
    });
    setStatus(`Bought ${shares} ${ticker} at ${money(res.entry_price)}`);
  } catch (e) {
    alert(e.message);
    setStatus("Buy failed");
  }
}

async function addTicker() {
  const input = $("#ticker-input");
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  try {
    const data = await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    });
    input.value = "";
    $("#watchlist-count").textContent = `${data.tickers.length} tickers in watchlist`;
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
  const sellBtn = e.target.closest("button.sell");
  if (sellBtn) sell(sellBtn.dataset.id, sellBtn.dataset.ticker);
  const buyBtn = e.target.closest("button.buy");
  if (buyBtn) buy(buyBtn.dataset.ticker);
});

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  if (window.PAGE === "dashboard") {
    const refresh = () => loadPortfolio().then(loadPerformance);
    $("#refresh-btn")?.addEventListener("click", refresh);
    refresh();
  }
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
});
