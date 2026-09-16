"""Per-SKU stock: select each variation combination and read "N pieces available".

The product JSON has `stock: null` for every model, but the page shows the
count once a complete variation is selected. Reading the number off the page
works whatever endpoint (or client-side state) it comes from, so this does
not depend on reverse-engineering Shopee's API.

Two sources per SKU, the API one preferred:
    * api/v4/pdp/cart_panel/select_variation_pc -- the page calls it on every
      selection; data.stock is the selected SKU's stock and
      data.product_price.final_price_info.model_id names the SKU (found with
      to_delete/shopee_probe_stock_tool.py on shopee.vn). It also carries the SKU's price
      after auto-applied vouchers.
    * the "N pieces available" text on the page (fallback)

Cost: roughly one click + ~1s per SKU. A cap per product keeps a 90-SKU
listing from turning into 90 clicks; SKUs beyond the cap stay "unknown".

Button behaviour mirrored from shopee.vn:
    * clicking a selected option DESELECTS it -> we track the selection and
      only click options that change
    * sold-out options (or combinations) are disabled -> recorded as 0
"""
from __future__ import annotations

import itertools
import logging
import random
import re
import time

from ecommerce.settings import TimeoutSettings

log = logging.getLogger(__name__)

SELECT_API = "/pdp/cart_panel/select_variation"
PRICE_DIVISOR = 100_000

AVAILABLE_RX = re.compile(r"(\d[\d.,]*)\s*(?:pieces available|piece available|sản phẩm có sẵn)", re.I)


def read_available(page) -> int | None:
    """The 'N pieces available' number currently on screen (None if absent)."""
    try:
        node = page.get_by_text(AVAILABLE_RX).first
        if node.count() == 0:
            return None
        m = AVAILABLE_RX.search(node.inner_text(timeout=2_000))
        return int(re.sub(r"[.,]", "", m.group(1))) if m else None
    except Exception:
        return None


def option_button(page, text: str):
    """The variation button whose accessible name / text is exactly `text`."""
    for locator in (page.get_by_role("button", name=text, exact=True),
                    page.locator("button", has_text=text)):
        try:
            for i in range(min(locator.count(), 5)):
                candidate = locator.nth(i)
                if candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


def is_disabled(button) -> bool:
    try:
        return bool(button.is_disabled() or button.get_attribute("aria-disabled") == "true")
    except Exception:
        return False


def _model_index(item: dict, n_tiers: int) -> dict[tuple, dict]:
    index = {}
    for model in item.get("models") or []:
        idx = model.get("tier_index") or (model.get("extinfo") or {}).get("tier_index") or []
        if isinstance(idx, list) and len(idx) == n_tiers:
            index[tuple(idx)] = model
    return index


def _select_info(response) -> dict | None:
    """(model_id, stock, price after voucher) from a select_variation response."""
    try:
        body = response.json()
    except Exception:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    price = data.get("product_price") if isinstance(data.get("product_price"), dict) else {}
    info = price.get("final_price_info") if isinstance(price.get("final_price_info"), dict) else {}
    single = (price.get("price") or {}).get("single_value") if isinstance(price.get("price"), dict) else None
    stock = data.get("stock")
    return {
        "model_id": info.get("model_id") or data.get("model_id"),
        "stock": stock if isinstance(stock, int) and not isinstance(stock, bool) else None,
        "final_price": round(single / PRICE_DIVISOR) if isinstance(single, (int, float)) and single > 0 else None,
    }


def _settle(page, previous: int | None, settle_ms: int, tap=None, since: int = 0) -> int | None:
    """Read the count once the page had time to update it after a click.

    Returns early as soon as the select_variation response for this click has
    arrived (then the DOM number is only a cross-check)."""
    deadline = time.monotonic() + settle_ms / 1000
    page.wait_for_timeout(300)
    value = read_available(page)
    while time.monotonic() < deadline:
        if tap is not None and tap.matching(SELECT_API)[since:]:
            page.wait_for_timeout(150)          # let the page paint the same number
            return read_available(page)
        if tap is None and value != previous:
            break
        page.wait_for_timeout(150)
        value = read_available(page)
    return value


def collect_sku_stock(page, item: dict, max_clicks: int = 80, settle_ms: int = 1000, tap=None,
                      timeouts: TimeoutSettings = TimeoutSettings()) -> dict:
    """Return {"by_model": {model_id: {"available", "status"}}, "clicks", "complete", ...}."""
    tiers = [t for t in item.get("tier_variations") or [] if t.get("options")]
    result = {"by_model": {}, "clicks": 0, "complete": False,
              "baseline": read_available(page), "notes": []}
    index = _model_index(item, len(tiers))
    if not tiers or not index:
        result["complete"] = True       # nothing to select: the baseline IS the stock
        return result

    cache: dict[tuple[int, int], object] = {}

    def button(t: int, o: int):
        if (t, o) not in cache:
            cache[(t, o)] = option_button(page, str(tiers[t]["options"][o]))
        return cache[(t, o)]

    current: dict[int, int] = {}
    previous = result["baseline"]

    def click(t: int, o: int) -> bool:
        if result["clicks"] >= max_clicks:
            result["notes"].append(f"dừng ở giới hạn {max_clicks} lần bấm")
            return False
        try:
            button(t, o).click(timeout=5_000)
        except Exception as exc:
            result["notes"].append(f"không bấm được '{tiers[t]['options'][o]}': {exc}")
            return False
        result["clicks"] += 1
        # slow, uneven clicking: each click is one select_variation request
        page.wait_for_timeout(random.randint(timeouts.click_pause_min_ms, timeouts.click_pause_max_ms))
        return True

    combos = [c for c in itertools.product(*[range(len(t["options"])) for t in tiers]) if c in index]
    for combo in combos:
        model_id = index[combo].get("model_id")
        state = "ok"
        since = len(tap.matching(SELECT_API)) if tap is not None else 0
        for t, o in enumerate(combo):
            if current.get(t) == o:
                continue
            if button(t, o) is None:
                state = "missing"
                break
            if is_disabled(button(t, o)):
                # The lock may come from a LATER group still holding the previous
                # SKU's choice (e.g. 750ml selected, Xanh+750ml sold out). Clear
                # those -- clicking a selected option deselects it -- and re-check.
                for later in sorted(k for k in current if k > t):
                    if not click(later, current[later]):
                        return result
                    del current[later]
                if is_disabled(button(t, o)):
                    state = "sold_out"          # sold out with the groups fixed so far
                    break
            if not click(t, o):
                return result
            current[t] = o
        if state == "missing":
            result["notes"].append(f"không tìm thấy nút cho SKU {model_id}")
            continue
        if state == "sold_out":
            result["by_model"][str(model_id)] = {"available": 0, "status": "Hết hàng"}
            continue
        shown = _settle(page, previous, settle_ms, tap, since)
        previous = shown
        api = None
        if tap is not None:
            for response in reversed(tap.matching(SELECT_API)[since:]):
                api = _select_info(response)
                if api and api["model_id"] in (None, model_id) and api["stock"] is not None:
                    break
                api = None
        value = api["stock"] if api else shown
        entry = {
            "available": value,
            "status": None if value is None else ("Hết hàng" if value == 0 else "Còn hàng"),
            "source": "api" if api else ("màn hình" if shown is not None else None),
            "shown": shown,
        }
        if api and api.get("final_price"):
            entry["final_price"] = api["final_price"]
        if api and shown is not None and shown != api["stock"]:
            result["notes"].append(f"SKU {model_id}: API {api['stock']} ≠ màn hình {shown}")
        result["by_model"][str(model_id)] = entry
    result["complete"] = True
    return result
