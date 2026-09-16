"""Listed price per SKU after the shop's discount (no voucher price on the web)."""
from __future__ import annotations

from ecommerce.domain.product import Price, Variant
from ecommerce.platforms.tiktok.parse.common import TikTokRaw, _d, to_float, to_int


def parse_price(src: TikTokRaw, variants: list[Variant]) -> Price:
    sale = [v.price for v in variants if v.price]
    before = [v.price_before_discount for v in variants if v.price_before_discount]
    min_price = _d(_d(_d(src.info.get("promotion_model")).get("promotion_product_price")).get("min_price"))
    price_min = min(sale) if sale else to_int(min_price.get("sale_price_decimal"))
    price_max = max(sale) if sale else price_min
    before_min = min(before) if before else to_int(min_price.get("origin_price_decimal"))
    before_max = max(before) if before else before_min
    discount = None
    if before_min and price_min and before_min > price_min:
        discount = round(100 * (1 - price_min / before_min))
    elif min_price.get("discount_decimal"):
        discount = round(100 * (to_float(min_price["discount_decimal"]) or 0)) or None
    return Price(min=price_min, max=price_max, before_min=before_min, before_max=before_max,
                 discount_pct=discount)
