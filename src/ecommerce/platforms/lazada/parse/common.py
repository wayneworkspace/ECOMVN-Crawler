"""Lazada VN page data: where it lives and helpers to read it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ecommerce.platforms.common.helpers import _d, _l, _s, deep_find, dig, first, first_pos, to_float, to_int

BASE = "https://www.lazada.vn"
SEARCH_PATH = "/catalog/?q={kw}&sort={sort}&page={page}&ajax=true"
PRODUCT_URL = BASE + "/products/i{item_id}-s{sku_id}.html"
PRODUCT_PATH = "/products/i{item_id}-s{sku_id}.html"
PAGE_SIZE = 40

__all__ = [
    "BASE",
    "PAGE_SIZE",
    "PRODUCT_PATH",
    "PRODUCT_URL",
    "SEARCH_PATH",
    "LazadaRaw",
    "_d",
    "_l",
    "_s",
    "deep_find",
    "dig",
    "first",
    "first_pos",
    "is_valid_product",
    "sold_count",
    "strip_html",
    "to_float",
    "to_int",
]


def sold_count(text: Any) -> int | None:
    """'Đã bán 1,2k' / '3.4K sold' / '856 đã bán' -> int (k = thousand)."""
    if text in (None, ""):
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text)
    s = str(text).lower().replace("\xa0", " ")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|nghìn|ngàn|tr|triệu|m)?", s)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    if unit in ("k", "nghìn", "ngàn"):
        value *= 1000
    elif unit in ("tr", "triệu", "m"):
        value *= 1_000_000
    return int(value)


def strip_html(html: Any) -> str:
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", str(html), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


@dataclass
class LazadaRaw:
    """The blocks of one raw product file, unpacked once."""
    raw: dict
    candidate: dict = field(default_factory=dict)
    module: dict = field(default_factory=dict)     # window.__moduleData__
    fields: dict = field(default_factory=dict)     # module.data.root.fields
    tracking: dict = field(default_factory=dict)   # window.pdpTrackingData (when present)

    @classmethod
    def from_raw(cls, raw: dict) -> LazadaRaw:
        module = _d(raw.get("module_data"))
        fields = _d(first(dig(module, "data", "root", "fields"), dig(module, "root", "fields"), module.get("fields")))
        return cls(raw=raw, candidate=_d(raw.get("candidate")), module=module, fields=fields,
                   tracking=_d(raw.get("tracking_data")))

    @property
    def product(self) -> dict:
        return _d(self.fields.get("product"))

    @property
    def item_id(self) -> str:
        return str(first(dig(self.fields, "primaryKey", "itemId"), self.product.get("itemId"),
                         self.candidate.get("item_id"), self.tracking.get("pdt_item_id")))

    @property
    def sku_id(self) -> str:
        return str(first(dig(self.fields, "primaryKey", "skuId"), self.candidate.get("sku_id"),
                         self.tracking.get("pdt_sku_id")) or "")


def is_valid_product(raw: dict) -> bool:
    src = LazadaRaw.from_raw(raw)
    return bool(src.fields) and bool(first(src.product.get("title"), src.candidate.get("name")))
