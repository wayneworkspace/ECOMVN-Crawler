"""Shop block: name, location (province), response rate / time, rating..."""
from __future__ import annotations

from ecommerce.domain.product import Shop
from ecommerce.platforms.shopee.parse.common import (
    SHOP_URL,
    ShopeeRaw,
    _l,
    _s,
    dig,
    first,
    to_float,
    to_int,
    ts_to_date,
)


def response_time_text(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 3600:
        return f"trong vài phút ({seconds // 60} phút)"
    if seconds < 86400:
        return f"trong vài giờ ({seconds // 3600} giờ)"
    return f"trong vài ngày ({seconds // 86400} ngày)"


def _sources(src: ShopeeRaw) -> list[dict]:
    """get_pc shop blocks first, then any shop endpoint the page loaded."""
    sources = [src.data.get("shop_detailed"), src.data.get("shop_info")]
    for payload in _l(src.raw.get("shop")):
        sources.extend([dig(payload, "data"), dig(payload, "data", "shop_info"),
                        dig(payload, "data", "shop_detailed")])
    return [s for s in sources if isinstance(s, dict)]


def parse_shop(src: ShopeeRaw) -> Shop:
    sources = _sources(src)

    def pick(*keys):
        for block in sources:
            for key in keys:
                if first(block.get(key)) is not None:
                    return block[key]
        return None

    item, basic, shopid = src.item, src.basic, src.shopid
    return Shop(
        id=shopid,
        name=_s(first(pick("name", "shop_name"), basic.get("shop_name"))),
        username=pick("username", "account_username"),
        url=SHOP_URL.format(shopid=shopid),
        location=_s(first(pick("shop_location", "place"), item.get("shop_location"), basic.get("shop_location"))),
        response_rate=to_int(pick("response_rate")),
        response_time=response_time_text(to_int(pick("response_time"))),
        rating=to_float(pick("rating_star", "shop_rating")),
        followers=to_int(pick("follower_count")),
        products=to_int(pick("item_count", "product_count")),
        joined=ts_to_date(pick("ctime")),
        is_mall=first(pick("is_official_shop", "is_mall"), basic.get("is_official_shop")),
        is_preferred=first(pick("is_shopee_verified", "is_preferred_plus_seller"), basic.get("shopee_verified")),
    )
