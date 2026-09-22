"""TikTok Shop VN page data: where it lives and helpers to read it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ecommerce.platforms.common.helpers import _d, _l, _s, deep_find, dig, first, first_pos, to_float, to_int

BASE = "https://shop.tiktok.com/vn"
PRODUCT_URL = BASE + "/pdp/{product_id}"
KEYWORD_PATH = "/vn/k/{slug}"
PRODUCT_PATH = "/vn/pdp/{product_id}"

__all__ = [
    "BASE",
    "KEYWORD_PATH",
    "PRODUCT_PATH",
    "PRODUCT_URL",
    "TikTokRaw",
    "_d",
    "_l",
    "_s",
    "component",
    "deep_find",
    "dig",
    "first",
    "first_pos",
    "first_url",
    "is_valid_product",
    "product_model",
    "to_float",
    "to_int",
]


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
