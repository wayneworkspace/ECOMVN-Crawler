"""SKUs with their exact price and stock (TikTok publishes both per SKU)."""
from __future__ import annotations

from ecommerce.domain.product import Variant
from ecommerce.platforms.tiktok.parse.common import TikTokRaw, _d, _l, first_url, to_int
from ecommerce.transformation.specs import capacities_ml


def _value_images(pm: dict) -> dict[str, str]:
    """property_value_id -> picture of that option (colour swatch / SKU photo)."""
    images: dict[str, str] = {}
    for vid, image in _d(pm.get("sku_property_image_map")).items():
        url = first_url(image)
        if url:
            images[str(vid)] = url
    for prop in _l(pm.get("sale_properties")):
        for v in _l(_d(prop).get("property_values")):
            v = _d(v)
            url = first_url(v.get("image"))
            if url and v.get("property_value_id"):
                images.setdefault(str(v["property_value_id"]), url)
    return images


def parse_tiers(src: TikTokRaw) -> list[dict]:
    return [{"name": _d(p).get("property_name"),
             "options": [_d(v).get("property_value_name") for v in _l(_d(p).get("property_values"))]}
            for p in _l(src.pm.get("sale_properties"))]


def parse_variant(sku: dict, prices: dict, images: dict[str, str]) -> Variant:
    pairs = [(_d(p).get("sku_property_name"), _d(p).get("sku_property_value_name"))
             for p in _l(sku.get("property_pairs"))]
    pairs = [(str(k or "Phân loại"), str(v)) for k, v in pairs if v]
    value_ids = [str(_d(p).get("sku_property_value_id")) for p in _l(sku.get("property_pairs"))]
    price = _d(prices.get(str(sku.get("sku_id"))))
    stock = to_int(_d(sku.get("sku_quantity")).get("available_quantity"))
    status = to_int(sku.get("sku_stock_status"))
    name = " / ".join(v for _, v in pairs) or sku.get("sku_name")
    caps = capacities_ml(name)
    return Variant(
        model_id=str(sku.get("sku_id")),
        name=name,
        tiers=pairs,
        capacity=f"{caps[0]}ml" if caps else None,
        price=to_int(price.get("sale_price_decimal")),
        price_before_discount=to_int(price.get("origin_price_decimal")),
        stock=stock,
        # sku_stock_status: 1 = in stock, 2 = sold out (matches quantity 0)
        stock_status=(("Hết hàng" if (stock == 0 or status == 2) else "Còn hàng")
                      if (stock is not None or status) else None),
        image=next((images[v] for v in value_ids if v in images), None),
    )


def parse_variants(src: TikTokRaw) -> tuple[list[Variant], list[dict]]:
    prices = _d(_d(_d(src.info.get("promotion_model")).get("promotion_product_price")).get("skus_price"))
    images = _value_images(src.pm)
    variants = [parse_variant(_d(sku), prices, images) for sku in _l(src.pm.get("skus"))]
    return variants, parse_tiers(src)
