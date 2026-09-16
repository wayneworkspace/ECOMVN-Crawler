"""Prices: list price after the shop's discount, the price before it, and the
price after auto-applied vouchers.

item.price_min/max = list price after the shop's discount, the same for every
buyer. product_price.price is the price AFTER auto-applied vouchers (differs
per account) and uses -1 for "not a range" -- kept separately as final_price.
"""
from __future__ import annotations

from ecommerce.domain.product import Price, Variant
from ecommerce.platforms.shopee.parse.common import ShopeeRaw, _d, dig, discount_pct, first, first_pos, to_price


def _bound(product_level: int | None, sku_prices: list[int], take_min: bool) -> int | None:
    """Price bound covering BOTH sources: the product-level field and the per-SKU prices.

    Shopee often reports price_min = price_max = the price of ONE variation that
    is on promotion. Measured on 40 products: 13 had `item.price_max` below the
    highest SKU price (e.g. 420.000 while a SKU sells for 880.000), and NO product
    had a product-level field wider than the SKU range. So merging both sources
    and taking min/max only widens, never narrows -- the main sheet always covers
    the Detail sheet (decisions.md #19).
    """
    prices = [p for p in (product_level, *sku_prices) if p]
    if not prices:
        return None
    return min(prices) if take_min else max(prices)


def _list_price(src: ShopeeRaw, variants: list[Variant]) -> tuple[int | None, int | None]:
    item, basic = src.item, src.basic
    prices = [v.price for v in variants if v.price]
    low = to_price(first_pos(item.get("price_min"), item.get("price"), basic.get("price_min"), basic.get("price")))
    high = to_price(first_pos(item.get("price_max"), item.get("price"), basic.get("price_max"), basic.get("price")))
    return _bound(low, prices, True), _bound(high, prices, False)


def _before_discount(src: ShopeeRaw, variants: list[Variant]) -> tuple[int | None, int | None]:
    item, basic = src.item, src.basic
    before = [v.price_before_discount for v in variants if v.price_before_discount]
    low = to_price(first_pos(item.get("price_min_before_discount"), item.get("price_before_discount"),
                             basic.get("price_min_before_discount"), basic.get("price_before_discount")))
    high = to_price(first_pos(item.get("price_max_before_discount"), item.get("price_before_discount"),
                              basic.get("price_max_before_discount"), basic.get("price_before_discount")))
    return _bound(low, before, True), _bound(high, before, False)


def _discount(src: ShopeeRaw, price_min: int | None, before_min: int | None) -> int | None:
    if before_min and price_min and before_min > price_min:
        return round(100 * (1 - price_min / before_min))
    return discount_pct(first(src.item.get("raw_discount"), src.basic.get("raw_discount"),
                              src.basic.get("discount")))


def parse_price(src: ShopeeRaw, variants: list[Variant]) -> Price:
    price_min, price_max = _list_price(src, variants)
    before_min, before_max = _before_discount(src, variants)
    discount = _discount(src, price_min, before_min)
    pp = _d(src.data.get("product_price"))
    final_price = None
    if pp.get("has_final_price") or pp.get("show_final_price_indicator"):
        final_price = to_price(first_pos(dig(pp, "price", "single_value"), dig(pp, "price", "range_min")))
    elif pp:
        # no voucher price: product_price is the list price itself (fallback)
        price_min = price_min or to_price(first_pos(dig(pp, "price", "range_min"), dig(pp, "price", "single_value")))
        price_max = price_max or to_price(first_pos(dig(pp, "price", "range_max"), dig(pp, "price", "single_value")))
    return Price(min=price_min, max=price_max, before_min=before_min, before_max=before_max,
                 discount_pct=discount, final_price=final_price)
