import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

STORE_URL = os.environ["STORE_URL"]
OFFERS_URL = os.environ["OFFERS_URL"]
TILE = os.environ["TILE_SELECTOR"]
CARD = os.environ.get("CARD_MARKER", "")
OUT = Path(__file__).parent / "docs" / "offers.json"

price_re = re.compile(r"(?<![\d,.])\d+\.\d{2}(?!\d)")
percent_re = re.compile(r"-(\d+)\s*%")


def accept_cookies(page):
    for sel in ("#onetrust-accept-btn-handler", "button:has-text('Alle akzeptieren')"):
        try:
            page.click(sel, timeout=3000)
            return
        except Exception:
            pass


def read_tile(tile):
    text = re.sub(r"\([^)]*\)", " ", " ".join(tile["text"].split()))
    normal = text.split(CARD)[0] if CARD else text

    prices = [float(p) for p in price_re.findall(normal)] or [float(p) for p in price_re.findall(text)]
    name = " ".join(f"{tile['title']} {tile['subtitle']} {tile['unit']}".split())
    if not prices or not name:
        return None

    price = prices[0]
    old_price = prices[1] if len(prices) > 1 and prices[1] > price else None

    found = percent_re.search(normal) or percent_re.search(text)
    if found:
        percent = int(found.group(1))
    elif old_price:
        percent = round((1 - price / old_price) * 100)
    else:
        percent = 0

    return {"name": name, "price": price, "old_price": old_price, "percent": percent}


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    page.goto("https://www.google.com")
    accept_cookies(page)
    page.goto(STORE_URL)
    accept_cookies(page)
    page.goto(OFFERS_URL)
    page.wait_for_timeout(3000)

    for _ in range(10):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(500)

    tiles = page.eval_on_selector_all(
        TILE,
        """(els, sel) => els.map(e => {
            const get = name => (e.querySelector(sel + '__' + name)?.innerText || '').trim();
            return {title: get('title'), subtitle: get('subtitle'), unit: get('unit-price'), text: e.innerText};
        })""",
        TILE,
    )
    if not tiles:
        Path("debug.html").write_text(page.content(), encoding="utf-8")
        raise SystemExit("Keine Angebote gefunden. (debug.html)")
    browser.close()

offers = {}
for tile in tiles:
    offer = read_tile(tile)
    if offer:
        offers[(offer["name"], offer["price"])] = offer

OUT.parent.mkdir(exist_ok=True)
data = {
    "updated": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="minutes"),
    "offers": list(offers.values()),
}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(offers), "Angebote gespeichert")
