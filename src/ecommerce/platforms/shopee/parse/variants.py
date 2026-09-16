"""SKUs (Shopee 'models') and their variation groups ('tier_variations')."""
from __future__ import annotations

from typing import Any

from ecommerce.domain.product import Variant
from ecommerce.platforms.shopee.parse.common import (
    ShopeeRaw,
    _d,
    _l,
    _s,
    dig,
    first,
    first_pos,
    image_url,
    to_int,
    to_price,
)
from ecommerce.transformation.specs import capacities_ml, is_color_tier, looks_like_color


def parse_tiers(src: ShopeeRaw) -> list[dict]:
    """[{"name": "Màu Sắc", "options": [...], "images": [...]}]"""
    tiers = []
    for tier in _l(first(src.item.get("tier_variations"), src.basic.get("tier_variations"))):
        if isinstance(tier, dict):
            tiers.append({"name": _s(tier.get("name")),
                          "options": [_s(o) or "" for o in _l(tier.get("options"))],
                          "images": _l(tier.get("images"))})
    return tiers


def _options(model: dict, tiers: list[dict]) -> tuple[list[Any], list[str]]:
    tier_index = _l(first(model.get("tier_index"), dig(model, "extinfo", "tier_index")))
    options = []
    for pos, idx in enumerate(tier_index):
        opts = dig(tiers, pos, "options") or []
        if isinstance(idx, int) and 0 <= idx < len(opts):
            options.append(opts[idx])
    return tier_index, options


def _color_and_capacity(options: list[str], tiers: list[dict], name: str | None):
    color = capacity = None
    for pos, option in enumerate(options):
        if is_color_tier(dig(tiers, pos, "name")) or (color is None and looks_like_color(option)):
            color = color or option
        caps = capacities_ml(option)
        if caps and capacity is None:
            capacity = f"{caps[0]}ml"
    if capacity is None:
        caps = capacities_ml(name)
        capacity = f"{caps[0]}ml" if caps else None
    return color, capacity


def _stock_status(model: dict) -> str | None:
    """Shopee hides counts but still flags sold-out models."""
    if model.get("has_stock") is None and model.get("is_grayout") is None:
        return None
    return "Hết hàng" if (model.get("has_stock") is False or model.get("is_grayout")) else "Còn hàng"


def parse_variant(model: dict, tiers: list[dict]) -> Variant:
    tier_index, options = _options(model, tiers)
    name = first(_s(model.get("name")), ", ".join(o for o in options if o))
    color, capacity = _color_and_capacity(options, tiers, name)
    image = None
    if tier_index and isinstance(tier_index[0], int):
        image = image_url(_s(dig(tiers, 0, "images", tier_index[0])))
    price_info = _d(model.get("price_info"))
    return Variant(
        model_id=to_int(model.get("model_id")),
        # the shop's own variation groups, verbatim: ("Màu Sắc", "Xanh bầu trời")
        tiers=[(dig(tiers, pos, "name") or f"Nhóm {pos + 1}", opt) for pos, opt in enumerate(options)],
        name=name,
        color=color,
        capacity=capacity,
        price=to_price(first_pos(model.get("price"), price_info.get("price"))),
        price_before_discount=to_price(first_pos(model.get("price_before_discount"),
                                                 price_info.get("price_before_discount"))),
        stock=to_int(first(model.get("stock"), model.get("normal_stock"),
                           dig(model, "stock_info", "normal_stock"))),
        stock_status=_stock_status(model),
        sold=to_int(model.get("sold")),
        image=image,
    )


def merge_sku_stock(variants: list[Variant], sku_stock: Any) -> None:
    """Counts read off the page ('N pieces available') override the JSON."""
    by_model = _d(_d(sku_stock).get("by_model"))
    for v in variants:
        seen = _d(by_model.get(str(v.model_id)))
        if seen.get("available") is not None:
            v.stock = to_int(seen["available"])
        if seen.get("status"):
            v.stock_status = seen["status"]
        if seen.get("final_price"):
            v.final_price = to_int(seen["final_price"])


def parse_variants(src: ShopeeRaw) -> tuple[list[Variant], list[dict]]:
    tiers = parse_tiers(src)
    models = _l(first(src.item.get("models"), src.basic.get("models")))
    variants = [parse_variant(m, tiers) for m in models if isinstance(m, dict)]
    merge_sku_stock(variants, src.raw.get("sku_stock"))
    return variants, tiers
