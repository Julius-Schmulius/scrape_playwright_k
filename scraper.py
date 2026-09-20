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


def go(page, url):
    for attempt in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(4000)


def show_all(page):
    last = -1
    for _ in range(30):
        count = page.locator(TILE).count()
        if count == last:
            break
        last = count
        for button in page.get_by_text("Weitere Angebote anzeigen").all():
            try:
                if button.is_visible():
                    button.scroll_into_view_if_needed(timeout=2000)
                    button.click(timeout=3000)
                    page.wait_for_timeout(400)
            except Exception:
                pass
        page.wait_for_timeout(1000)


def prices_in(text):
    return [float(p) for p in price_re.findall(text)]


def percent_of(text, price, old_price):
    found = percent_re.search(text)
    if found:
        return int(found.group(1))
    if old_price:
        return round((1 - price / old_price) * 100)
    return 0


def read_tile(tile):
    text = re.sub(r"\([^)]*\)", " ", " ".join(tile["text"].split()))
    name = " ".join(f"{tile['title']} {tile['subtitle']} {tile['unit']}".split())
    if not name:
        return None

    if CARD and CARD in text:
        normal, with_card = text.split(CARD, 1)
    else:
        normal, with_card = text, ""

    normal_prices = prices_in(normal)
    card_prices = prices_in(with_card)
    if not normal_prices and not card_prices:
        return None

    card_only = not normal_prices
    prices = card_prices if card_only else normal_prices
    section = with_card if card_only else normal

    price = prices[0]
    old_price = prices[1] if len(prices) > 1 and prices[1] > price else None
    offer = {
        "name": name,
        "price": price,
        "old_price": old_price,
        "percent": percent_of(section, price, old_price),
        "card_only": card_only,
        "card_price": None,
        "card_percent": None,
    }

    if card_prices and not card_only:
        card_price = card_prices[0]
        card_old = card_prices[1] if len(card_prices) > 1 and card_prices[1] > card_price else None
        offer["card_price"] = card_price
        offer["card_percent"] = percent_of(with_card, card_price, card_old)

    return offer


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    version = browser.version.split(".")[0]
    context = browser.new_context(
        user_agent=f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        locale="de-DE",
        timezone_id="Europe/Berlin",
        viewport={"width": 1366, "height": 900},
    )
    page = context.new_page()

    go(page, "https://www.google.com")
    accept_cookies(page)
    go(page, STORE_URL)
    accept_cookies(page)
    page.wait_for_timeout(4000)
    go(page, OFFERS_URL)
    accept_cookies(page)
    try:
        page.wait_for_selector(TILE, timeout=30000)
    except Exception:
        pass

    show_all(page)

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
        raise SystemExit("Keine Angebote gefunden, siehe debug.html")
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
