"""Helpers for reading Shopee's loosely-typed JSON, and the bundle of raw blocks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ecommerce.platforms.common.helpers import _d, _l, _s, deep_find, dig, first, first_pos, to_float, to_int

PRICE_DIVISOR = 100_000          # Shopee stores VND * 100000
IMAGE_BASE = "https://down-vn.img.susercontent.com/file/"
PRODUCT_URL = "https://shopee.vn/product/{shopid}/{itemid}"
SHOP_URL = "https://shopee.vn/shop/{shopid}"

__all__ = [
    "IMAGE_BASE",
    "PRICE_DIVISOR",
    "PRODUCT_URL",
    "SHOP_URL",
    "ShopeeRaw",
    "_d",
    "_l",
    "_s",
    "deep_find",
    "dig",
    "discount_pct",
    "first",
    "first_pos",
    "image_url",
    "pdp_item",
    "to_float",
    "to_int",
    "to_price",
    "to_seconds",
    "ts_to_date",
]


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
    """The item block of a get_pc payload, or None if Shopee refused us."""
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    item = dig(payload, "data", "item")
    return item if isinstance(item, dict) and item else None


@dataclass
class ShopeeRaw:
    """The blocks of one raw product file, unpacked once."""
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
