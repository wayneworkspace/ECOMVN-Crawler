"""Lazada VN page data: where it lives and helpers to read it.

Search page   https://www.lazada.vn/catalog/?q=<kw>&sort=popularity&page=N
    With `&ajax=true` the same URL answers JSON:
        mods.listItems[]      itemId, skuId, sellerId, name, priceShow, price,
                              originalPrice, discount, ratingScore, review,
                              itemSoldCntShow ("Đã bán 1.2k"), location, sellerName,
                              brandName, image, itemUrl, inStock, sponsored flags
        mainInfo.totalResults

Product page  https://www.lazada.vn/products/<slug>-i<itemId>-s<skuId>.html
    The server-rendered HTML carries `window.__moduleData__ = {...}` whose
    `data.root.fields` holds everything the page shows:
        product           title, brandName, desc (HTML), highlights, itemId
        primaryKey        itemId, skuId
        skuInfos{skuId}   price.salePrice.value, price.originalPrice.value, stock, image
        productOption     skuBase.properties[] (name, values[] {vid, name, image}),
                          skuBase.skus[] {skuId, propPath "pid:vid;pid:vid"}
        review            ratings.average, ratings.rateCount, ratings.scores[]
        seller            name, sellerId, url; sellerInfo.* (positive rating, ship on time)
        specifications    [{features: {key: value}}]
        tracking          pdt_* (sold count when published)

The exact key names vary between Lazada releases; every reader below tries a
list of candidate paths in order (see contracts/lazada.py) so a rename shows up
in `ecommerce check-schema` instead of as blank cells.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

BASE = "https://www.lazada.vn"
SEARCH_PATH = "/catalog/?q={kw}&sort={sort}&page={page}&ajax=true"
PRODUCT_URL = BASE + "/products/i{item_id}-s{sku_id}.html"
PRODUCT_PATH = "/products/i{item_id}-s{sku_id}.html"
PAGE_SIZE = 40


def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    return v if isinstance(v, list) else []


def dig(obj: Any, *keys: str) -> Any:
    """dig(d, "a", "b") -> d["a"]["b"] or None; list indices as "0"."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return None
    return cur


def first(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def to_int(v: Any) -> int | None:
    """'1.234.000 ₫' -> 1234000; 1234.0 -> 1234; 'abc' -> None."""
    if v is None or v == "" or isinstance(v, bool):      # note: 0 == False, so test `is`
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace("\xa0", " ").strip()
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    # "1.234.000" / "1,234,000" are thousands separators; "4.5" is a decimal
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s.split(" ")[0]):
        return int(digits)
    m = _NUM.search(s)
    try:
        return int(float(m.group(0).replace(",", "."))) if m else None
    except ValueError:
        return None


def to_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = _NUM.search(str(v))
    try:
        return float(m.group(0).replace(",", ".")) if m else None
    except ValueError:
        return None


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
