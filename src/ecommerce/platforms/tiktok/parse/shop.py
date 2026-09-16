"""Shop block: shop address and shop link."""
from __future__ import annotations

import re

from ecommerce.domain.product import Shop
from ecommerce.platforms.tiktok.parse.common import TikTokRaw, _d, _l, to_float, to_int
from ecommerce.transformation.specs import attr_lookup, norm

_ADDRESS_HINT = re.compile(r"\d|,|tp\.?|thành phố|quận|huyện|phường|xã|tỉnh|đường|hà nội|hồ chí minh|"
                           r"đà nẵng|hải phòng|cần thơ|số nhà|kcn|khu công nghiệp")


# TikTok provides a single shop link, and it does NOT open on the desktop web
# (tried 13/09: 404; switching to www.tiktok.com/shop is not a 404 but a blank
# page). On the product page the shop name is a <span>, not an <a> tag -- the
# TikTok Shop web has no shop page. Keep the value the site provides, do not
# build another link; the column title says it is an app link (decisions.md #20).


def shop_address(attrs: dict[str, str]) -> str | None:
    """The only address is the legally required 'organisation responsible for
    the goods'. Kept only when it looks like an address (many shops type 'TQ'
    or the brand name)."""
    value = attr_lookup(attrs, "Địa chỉ tổ chức chịu trách nhiệm hàng hóa",
                        "Địa chỉ tổ chức chịu trách nhiệm hàng hoá")
    if value and len(value) >= 8 and _ADDRESS_HINT.search(norm(value)):
        return value
    return None


def _sub_score(shop: dict, kind: int) -> int | None:
    for score in _l(shop.get("store_sub_score")):
        if to_int(_d(score).get("type")) == kind:
            return to_int(_d(score).get("score_percentage"))
    return None


def response_rate(shop: dict) -> int | None:
    """store_sub_score type 1 = '% replies in 24h' (the desc text confirms it)."""
    value = _sub_score(shop, 1)
    if value is not None:
        return value
    m = re.search(r"(\d{1,3})%\s*replies", str(shop.get("desc") or ""))
    return int(m.group(1)) if m else None


def parse_shop(src: TikTokRaw, attrs: dict[str, str]) -> Shop:
    shop = _d(src.comp.get("shop_info"))
    return Shop(
        id=str(src.pm.get("seller_id") or src.candidate.get("seller_id") or ""),
        name=shop.get("shop_name") or src.candidate.get("shop_name"),
        url=shop.get("shop_link"),
        location=shop_address(attrs),
        response_rate=response_rate(shop),
        ship_48h=_sub_score(shop, 2),                  # type 2 = % shipped in 48h
        rating=to_float(shop.get("shop_rating")),
        sold=to_int(shop.get("sold_count")),
        followers=to_int(shop.get("followers_count")),
    )
