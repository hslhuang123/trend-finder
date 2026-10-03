"""Verify the ticker-hover chart popup works in a real browser."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5000/"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})

    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(URL, wait_until="networkidle")

    # Wait for the open-positions table to render a ticker (CVE.TO).
    ticker = page.locator(".ticker").first
    ticker.wait_for(state="visible", timeout=30_000)
    print("Ticker text:", ticker.text_content())

    # Scroll into view first so hover() doesn't fire a scroll event (which
    # intentionally hides the popup), then move the mouse away and back.
    ticker.scroll_into_view_if_needed()
    page.mouse.move(10, 10)
    page.wait_for_timeout(100)

    # Hover it and wait for the chart popup.
    ticker.hover()
    popup = page.locator(".chart-popup.show")
    popup.wait_for(state="visible", timeout=20_000)
    print("Popup ticker:", popup.locator(".cp-ticker").text_content())
    print("Popup name:", popup.locator(".cp-name").text_content())

    ranges = popup.locator(".cp-range")
    print("Range buttons:", ranges.all_text_contents())

    # Wait for the default chart (6m) to load.
    page.wait_for_function(
        "() => document.querySelector('.chart-popup .cp-svg') !== null",
        timeout=30_000,
    )
    print("SVG chart rendered:", popup.locator(".cp-svg").count(), "polyline(s)")

    # Click a different range and confirm the chart updates.
    ranges.filter(has_text="1y").click()
    page.wait_for_function(
        "() => document.querySelector('.cp-range.active')?.textContent === '1y'",
        timeout=5_000,
    )
    print("Active range after click:", popup.locator(".cp-range.active").text_content())

    page.screenshot(path="/tmp/chart_popup.png", full_page=False)
    browser.close()

    print("Console/page errors:", errors if errors else "none")
