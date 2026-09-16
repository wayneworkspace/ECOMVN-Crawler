"""TikTok Shop VN page data: where it lives and helpers to read it.

    Every page is server-rendered with its data in
    <script id="__MODERN_ROUTER_DATA__">: loaderData[<route>].page_config.components_map

    keyword page  /vn/k/<slug>
        feed_list_search_word.component_data.products[]      <= 55 products, no paging
        related_link_search_words.component_data.related_links[]  other keyword pages
    product page  /vn/pdp/<id>
        product_info.component_data:
            product_info.product_model   name, sold_count, description (JSON blocks),
                                         images, sale_properties, product_properties,
                                         skus[].sku_quantity.available_quantity  <- exact stock
            product_info.promotion_model promotion_product_price.skus_price{sku_id: price}
                                         promotion_logistic_list (shipping vouchers)
            review_info.review_ratings   overall_score, review_count, rating_result{1..5}
            shop_info                    shop_name, store_sub_score (type 1 = replies in 24h)
            promotion_tag                flash sale labels
            categories                   category path

The web storefront has no "sort by sales" and no 30-day sales: products are
ranked by the cumulative sold count shown on the product page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BASE = "https://shop.tiktok.com/vn"
PRODUCT_URL = BASE + "/pdp/{product_id}"
KEYWORD_PATH = "/vn/k/{slug}"
PRODUCT_PATH = "/vn/pdp/{product_id}"



def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    return v if isinstance(v, list) else []


def to_int(v: Any) -> int | None:
    try:
        return int(float(str(v).replace(",", ""))) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def to_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def first_url(image: Any) -> str | None:
    urls = _l(_d(image).get("url_list"))
    return urls[0] if urls and isinstance(urls[0], str) else None


def component(components: Any, name: str) -> dict:
    for c in _l(components):
        if isinstance(c, dict) and c.get("component_name") == name:
            return c
    return {}


def product_model(raw: dict) -> dict:
    return _d(_d(_d(raw.get("product_info")).get("product_info")).get("product_model"))


def is_valid_product(raw: dict) -> bool:
    pi = _d(raw.get("product_info"))
    return to_int(pi.get("error_code")) in (0, None) and bool(product_model(raw).get("product_id"))


@dataclass
class TikTokRaw:
    """The blocks of one raw product file, unpacked once."""
    raw: dict
    candidate: dict = field(default_factory=dict)
    comp: dict = field(default_factory=dict)     # product_info component_data
    info: dict = field(default_factory=dict)     # comp["product_info"]
    pm: dict = field(default_factory=dict)       # info["product_model"]

    @classmethod
    def from_raw(cls, raw: dict) -> TikTokRaw:
        comp = _d(raw.get("product_info"))
        info = _d(comp.get("product_info"))
        return cls(raw=raw, candidate=_d(raw.get("candidate")), comp=comp, info=info,
                   pm=_d(info.get("product_model")))

    @property
    def product_id(self) -> str:
        return str(self.pm.get("product_id") or self.candidate.get("product_id"))
