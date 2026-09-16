"""Helpers for reading Shopee's loosely-typed JSON, and the bundle of raw blocks.

Shopee changes its payload shape without notice, so every field is read from
several places in priority order (`first(...)`), and missing data is None --
never 0. A 0 would be a lie in a sales report ("sold 0") while None honestly
says "Shopee did not tell us".

Sources, in the order they are trusted:
    pdp     = api/v4/pdp/get_pc           (product page, the richest payload)
    ratings = api/v2/item/get_ratings     (review list + review summary)
    shop    = shop endpoints loaded by the product page (fallback for shop fields)
    search  = api/v4/search/search_items card (has the 30-day sold count)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PRICE_DIVISOR = 100_000          # Shopee stores VND * 100000
IMAGE_BASE = "https://down-vn.img.susercontent.com/file/"
PRODUCT_URL = "https://shopee.vn/product/{shopid}/{itemid}"
SHOP_URL = "https://shopee.vn/shop/{shopid}"


def dig(obj: Any, *path: Any, default: Any = None) -> Any:
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int) and -len(obj) <= key < len(obj):
            obj = obj[key]
        else:
            return default
        if obj is None:
            return default
    return obj


def _d(value: Any) -> dict:
    """Value if it is a dict, else {} -- payload blocks sometimes arrive as [] or null."""
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int)) and value != "":
        return [value]          # a lone value where a list was expected
    return []


def _s(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def first_pos(*values: Any) -> Any:
    """First value that is a positive number. Shopee writes -1 for 'not set'
    (e.g. range_min when the price is a single value) and 0 for 'no discount'."""
    for value in values:
        number = to_float(value)
        if number is not None and number > 0:
            return value
    return None


def first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "" and value != [] and value != {}:
            return value
    return None


def deep_find(obj: Any, key: str, max_depth: int = 6) -> Any:
    """First non-empty value stored under `key` anywhere in `obj` (breadth-first)."""
    frontier = [obj]
    for _ in range(max_depth):
        nxt = []
        for node in frontier:
            if isinstance(node, dict):
                if first(node.get(key)) is not None:
                    return node[key]
                nxt.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                nxt.extend(v for v in node if isinstance(v, (dict, list)))
        frontier = nxt
    return None


def to_price(raw: Any) -> float | None:
    """Shopee price units -> VND. -1 / negative means 'hidden'."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
        if value < 0 or value != value or value == float("inf"):
            return None
        return round(value / PRICE_DIVISOR)
    except (TypeError, ValueError, OverflowError):
        return None


def to_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def to_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def image_url(ref: Any) -> str | None:
    if not ref or not isinstance(ref, str):
        return None
    return ref if ref.startswith("http") else IMAGE_BASE + ref


def ts_to_date(ts: Any) -> str | None:
    ts = to_seconds(ts)
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def to_seconds(ts: Any) -> int | None:
    """Unix time in seconds; accepts milliseconds too (some endpoints use them)."""
    ts = to_int(ts)
    if not ts or ts <= 0:
        return None
    return ts // 1000 if ts > 100_000_000_000 else ts


def discount_pct(raw: Any) -> int | None:
    """'-25%' / '25%' / 25 -> 25."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return round(raw) if 0 < raw < 100 else None
    m = re.search(r"\d+(?:[.,]\d+)?", str(raw))
    if not m:
        return None
    value = float(m.group(0).replace(",", "."))
    return round(value) if 0 < value < 100 else None


def pdp_item(payload: Any) -> dict | None:
    """The item block of a get_pc payload, or None if Shopee refused us.

    Shopee answers blocks with HTTP 200 + {"error": 1, "data": null}; that must
    count as a failure, not as an empty product.
    """
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    item = dig(payload, "data", "item")
    return item if isinstance(item, dict) and item else None


@dataclass
class ShopeeRaw:
    """The blocks of one raw product file, unpacked once and passed to every
    parse_* function (instead of each re-reading raw["pdp"]["data"]...)."""
    raw: dict
    candidate: dict = field(default_factory=dict)
    basic: dict = field(default_factory=dict)      # the search card
    payload: dict = field(default_factory=dict)    # get_pc response
    data: dict = field(default_factory=dict)       # get_pc["data"]
    item: dict = field(default_factory=dict)       # get_pc["data"]["item"]
    itemid: int | None = None
    shopid: int | None = None

    @classmethod
    def from_raw(cls, raw: dict) -> ShopeeRaw:
        candidate = _d(raw.get("candidate"))
        basic = _d(candidate.get("basic"))
        payload = _d(raw.get("pdp"))
        item = pdp_item(payload) or {}
        return cls(
            raw=raw, candidate=candidate, basic=basic, payload=payload,
            data=_d(dig(payload, "data")), item=item,
            itemid=to_int(first(item.get("item_id"), item.get("itemid"), candidate.get("itemid"))),
            shopid=to_int(first(item.get("shop_id"), item.get("shopid"), candidate.get("shopid"))),
        )

    @property
    def review_block(self) -> dict:
        return _d(self.data.get("product_review"))
