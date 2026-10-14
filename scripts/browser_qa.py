from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def inspect(page, url: str, name: str, width: int, height: int) -> dict:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    response = page.goto(url, wait_until="networkidle")
    try:
        page.screenshot(path=OUT / f"{name}.png", full_page=True)
    except PlaywrightError:
        # Very tall pages can exceed a browser/GPU capture limit. The viewport
        # shot still verifies the rendered layout while DOM checks cover the
        # complete document.
        page.screenshot(path=OUT / f"{name}.png")
    return {
        "name": name,
        "status": response.status if response else None,
        "title": page.title(),
        "h1": page.locator("h1").first.inner_text(),
        "horizontalOverflow": page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"),
        "viewport": [width, height],
        "pageErrors": errors,
    }


def inspect_robot_arena(page, base_url: str) -> dict:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    response = page.goto(base_url + "/robot-arena", wait_until="networkidle")
    for _ in range(50):
        if page.locator("html").get_attribute("data-robot-arena") == "ready":
            break
        time.sleep(.1)
    else:
        status = page.locator("#render-state").inner_text()
        raise RuntimeError(f"Robot arena did not initialize WebGL: {status}; errors={errors}")
    for _ in range(50):
        if float(page.locator("#metric-time").inner_text().split()[0]) > 2:
            break
        time.sleep(.1)
    else:
        raise RuntimeError("Robot arena simulation clock did not advance")
    state = page.evaluate("window.__robotArena.getState()")
    page.screenshot(path=OUT / "robot-arena-desktop.png", full_page=True)
    return {
        "name": "robot-arena-desktop",
        "status": response.status if response else None,
        "title": page.title(),
        "h1": page.locator("h1").inner_text(),
        "horizontalOverflow": page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"),
        "viewport": [1440, 1000],
        "pageErrors": errors,
        "simulation": state,
    }


def main() -> None:
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8063"
    OUT.mkdir(exist_ok=True)
    results: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for name, width, height, path in (
            ("dashboard-desktop", 1440, 1000, "/"),
            ("dashboard-mobile", 390, 844, "/"),
            ("method-desktop", 1440, 1000, "/method"),
        ):
            page = browser.new_page(viewport={"width": width, "height": height})
            results.append(inspect(page, base_url + path, name, width, height))
            page.close()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        results.append(inspect_robot_arena(page, base_url))
        page.close()
        browser.close()
    print(json.dumps(results, indent=2))
    arena = next(r for r in results if r["name"] == "robot-arena-desktop")
    simulation_failed = arena["simulation"]["replans"] <= 0 or arena["simulation"]["alive"] != 6
    if any(r["status"] != 200 or r["horizontalOverflow"] or r["pageErrors"] for r in results) or simulation_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
