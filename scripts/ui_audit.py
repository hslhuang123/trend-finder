#!/usr/bin/env python3
"""Programmatic UI audit of TrendFinder with Playwright (installed Chrome).

Runs the Portfolio, Screener and Backtest pages on desktop and mobile, checks
layout/visibility/console errors, exercises the click-through flows, and saves
screenshots to /tmp/tf_shots.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
SHOTS = Path("/tmp/tf_shots")
SHOTS.mkdir(parents=True, exist_ok=True)

DESKTOP = {"width": 1280, "height": 900}
MOBILE = {"width": 390, "height": 844}

report: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    report.append(msg)


def check(label: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def overflow(page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )


def visible_headers(page) -> list[str]:
    rows = page.eval_on_selector_all(
        "#screen-table thead th",
        "els => els.map(e => [e.textContent.trim(), getComputedStyle(e).display])",
    )
    return [t for t, d in rows if d != "none"]


def run_portfolio(page, label: str) -> None:
    log(f"\n== Portfolio ({label}) ==")
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.screenshot(path=str(SHOTS / f"portfolio_{label}.png"), full_page=True)
    cards = page.locator("#summary .card").count()
    check("summary cards present", cards >= 5, f"{cards} cards")
    perf = page.locator("#performance").inner_text().strip()
    check("performance section rendered", len(perf) > 0, perf[:60].replace("\n", " "))
    check("no horizontal overflow", not overflow(page))


def run_screener(page, label: str) -> None:
    log(f"\n== Screener ({label}) ==")
    page.goto(f"{BASE}/screener", wait_until="networkidle")
    page.click("#run-btn")
    page.wait_for_selector("#screen-table tbody tr .ticker", timeout=180_000)
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / f"screener_{label}.png"), full_page=True)

    rows = page.locator("#screen-table tbody tr").count()
    stars = page.locator(".pick-star").count()
    bolds = page.locator(".pick-bold").count()
    ai = page.locator(".ai-badge").count()
    disc = page.locator(".discover-mark").count()
    headers = visible_headers(page)

    check("table has rows", rows > 0, f"{rows} rows")
    check("auto-pick star+bold match", stars == bolds and stars > 0, f"stars={stars} bold={bolds}")
    check("AI badges present", ai > 0, f"{ai}")
    log(f"  discovered marks: {disc}")
    log(f"  visible columns: {', '.join(headers)}")

    if label == "desktop":
        page.locator(".ai-badge").first.hover()
        page.wait_for_timeout(400)
        tip = page.locator(".tooltip.show")
        visible = tip.is_visible()
        text = tip.inner_text().replace("\n", " | ") if visible else ""
        check("AI hover popup shows", visible and "Quality" in text, text[:90])
        page.screenshot(path=str(SHOTS / "screener_tooltip_desktop.png"))

    check("no horizontal overflow", not overflow(page))


def run_backtest(page, label: str) -> None:
    log(f"\n== Backtest ({label}) ==")
    page.goto(f"{BASE}/backtest", wait_until="networkidle")
    page.click("#bt-run")
    page.wait_for_selector("#bt-chart svg.chart", timeout=180_000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / f"backtest_{label}.png"), full_page=True)

    cards = page.locator("#bt-compare .card").count()
    lines = page.locator("#bt-chart svg.chart polyline").count()
    trades = page.locator("#bt-trades tbody tr").count()
    check("comparison cards present", cards >= 5, f"{cards} cards")
    check("equity chart rendered", page.locator("#bt-chart svg.chart").count() == 1)
    check("strategy + benchmark lines", lines >= 2, f"{lines} lines")
    check("trades table populated", trades > 0, f"{trades} rows")
    if label == "desktop":
        page.locator("#bt-form span[data-tip]").first.hover()
        page.wait_for_timeout(350)
        tip = page.locator(".tooltip.show")
        t = tip.inner_text().replace("\n", " | ") if tip.is_visible() else ""
        check("form label tooltip", tip.is_visible() and "history" in t, t[:70])
        page.locator("#bt-compare .card .label[data-tip]").first.hover()
        page.wait_for_timeout(350)
        tip = page.locator(".tooltip.show")
        t = tip.inner_text().replace("\n", " | ") if tip.is_visible() else ""
        check("metric card tooltip", tip.is_visible(), t[:70])
        reason_th = page.locator("#bt-trades thead th[data-tip]").nth(3)
        reason_th.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        box = reason_th.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(350)
        tip = page.locator(".tooltip.show")
        t = tip.inner_text().replace("\n", " | ") if tip.is_visible() else ""
        check("trades header tooltip", tip.is_visible() and "trade" in t.lower(), t[:80])

        legend_item = page.locator("#bt-legend .legend-item[data-tip]").first
        legend_item.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        lb = legend_item.bounding_box()
        page.mouse.move(lb["x"] + lb["width"] / 2, lb["y"] + lb["height"] / 2)
        page.wait_for_timeout(350)
        tip = page.locator(".tooltip.show")
        t = tip.inner_text().replace("\n", " | ") if tip.is_visible() else ""
        check("chart legend tooltip", tip.is_visible() and "momentum strategy" in t.lower(), t[:80])

        note = page.locator("#bt-trades-note").inner_text()
        check("trades note explains rows", "single buy or sell" in note.lower(), note[:90])
        page.screenshot(path=str(SHOTS / "backtest_tooltip_desktop.png"))
    check("no horizontal overflow", not overflow(page))


def run_help(page, label: str) -> None:
    log(f"\n== Help ({label}) ==")
    page.goto(f"{BASE}/help", wait_until="networkidle")
    page.screenshot(path=str(SHOTS / f"help_{label}.png"), full_page=True)
    text = page.locator("main").inner_text()
    low = text.lower()
    check("help page has content", len(text) > 500, f"{len(text)} chars")
    check("explains winning vs losing", "winner" in low and "loser" in low)
    check("explains the trades table", "single buy or sell" in low)
    check("notes data may differ", "different numbers" in low)
    check("has metrics glossary", "sharpe" in low and "max drawdown" in low)
    check("lists backtest settings", "top k" in low and "stop-loss" in low and "slippage" in low)
    check("explains SPY", "spy" in low and "s&p 500" in low)
    check("no horizontal overflow", not overflow(page))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        log("############ DESKTOP (1280x900) ############")
        page = browser.new_page(viewport=DESKTOP)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}")
                if r.status >= 400 and "favicon" not in r.url else None)
        run_portfolio(page, "desktop")
        run_screener(page, "desktop")
        run_backtest(page, "desktop")
        run_help(page, "desktop")
        log("\n== Console/network errors (desktop) ==")
        check("no console or 4xx errors", not errors, "; ".join(errors[:5]))
        page.close()

        log("\n############ MOBILE (390x844) ############")
        page = browser.new_page(viewport=MOBILE, device_scale_factor=3,
                                is_mobile=True, has_touch=True)
        merrors: list[str] = []
        page.on("console", lambda m: merrors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: merrors.append(str(e)))
        run_portfolio(page, "mobile")
        run_screener(page, "mobile")
        run_backtest(page, "mobile")
        run_help(page, "mobile")
        log("\n== Console errors (mobile) ==")
        check("no console errors", not merrors, "; ".join(merrors[:5]))
        page.close()

        browser.close()

    log(f"\nScreenshots -> {SHOTS}")
    Path("/tmp/tf_audit.txt").write_text("\n".join(report))
    print("\nreport written to /tmp/tf_audit.txt")


if __name__ == "__main__":
    sys.exit(main())
