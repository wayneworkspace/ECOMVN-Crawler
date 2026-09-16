"""Text and media of a Shopee product: title, description, attribute table,
category, images, videos, brand, promotions."""
from __future__ import annotations

from ecommerce.platforms.shopee.parse.common import (
    ShopeeRaw,
    _l,
    _s,
    deep_find,
    dig,
    first,
    image_url,
    to_int,
    to_price,
)
from ecommerce.transformation.specs import attr_lookup

NO_BRAND = ("no brand", "nobrand", "0", "none")


def title(src: ShopeeRaw) -> str:
    return first(_s(src.item.get("title")), _s(src.item.get("name")), _s(src.basic.get("name")),
                 _s(src.candidate.get("name"))) or ""


def attributes(src: ShopeeRaw) -> dict[str, str]:
    """Seller attribute table -> {name: value}. Looks in every known home."""
    data, item = src.data, src.item
    out: dict[str, str] = {}
    candidates = [
        item.get("attributes"),
        dig(data, "product_attributes", "attrs"),
        dig(data, "product_attributes", "attributes"),
        deep_find(data, "attrs"),
    ]
    for block in candidates:
        if not isinstance(block, list):
            continue
        for attr in block:
            if not isinstance(attr, dict):
                continue
            name = _s(first(attr.get("name"), attr.get("display_name"), attr.get("attr_name")))
            value = first(attr.get("value"), attr.get("display_value"), attr.get("values"),
                          dig(attr, "brand_option"), attr.get("attr_value"))
            if isinstance(value, list):
                value = ", ".join(filter(None, (
                    _s(first(v.get("name"), v.get("value"))) if isinstance(v, dict) else _s(v)
                    for v in value)))
            elif isinstance(value, dict):
                value = _s(first(value.get("name"), value.get("value")))
            if name and value not in (None, "") and name not in out:
                out[str(name).strip()] = str(value).strip()
    return out


def description(src: ShopeeRaw) -> str:
    text = first(src.item.get("description"), dig(src.data, "product_description", "description"))
    if isinstance(text, str):
        return text
    paragraphs = _l(first(dig(src.data, "product_description", "paragraph_list"),
                          deep_find(src.data, "paragraph_list")))
    parts = [_s(p.get("text")) for p in paragraphs if isinstance(p, dict) and _s(p.get("text"))]
    return "\n".join(parts)


def category(src: ShopeeRaw) -> str | None:
    cats = _l(first(src.item.get("categories"), src.item.get("fe_categories"), src.basic.get("categories")))
    names = [_s(c.get("display_name")) for c in cats if isinstance(c, dict) and _s(c.get("display_name"))]
    return " > ".join(names) or None


def images(src: ShopeeRaw) -> list[str]:
    refs = _l(first(dig(src.data, "product_images", "images"), src.item.get("images"),
                    src.basic.get("images")))
    main = _s(first(src.item.get("image"), src.basic.get("image")))
    ordered = ([main] if main else []) + [r for r in refs if r != main]
    urls, seen = [], set()
    for ref in ordered:
        url = image_url(_s(ref))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def video_count(src: ShopeeRaw) -> int:
    video = dig(src.data, "product_images", "video")
    count = len(_l(first(src.item.get("video_info_list"), src.basic.get("video_info_list"))))
    return max(count, 1 if video else 0)


def brand(src: ShopeeRaw, attrs: dict[str, str]) -> str | None:
    value = first(_s(src.item.get("brand")), attr_lookup(attrs, "Thương hiệu", "Brand"),
                  _s(src.basic.get("brand")))
    if isinstance(value, str) and value.strip().lower() in NO_BRAND:
        return "No brand"
    return value


def promotions(src: ShopeeRaw, discount: int | None, final_price: int | None,
               price_min: int | None) -> str | None:
    data, item, basic = src.data, src.item, src.basic
    promos: list[str] = []
    if final_price and price_min and final_price < price_min:
        promos.append(f"Giá sau voucher tự áp: {final_price:,.0f}đ".replace(",", "."))
    if discount:
        promos.append(f"Giảm {discount}%")
    flash = first(data.get("flash_sale"), item.get("flash_sale"), basic.get("flash_sale"),
                  data.get("upcoming_flash_sale"))
    if flash:
        promos.append("Flash sale")
    for voucher in _l(data.get("shop_vouchers")):
        if not isinstance(voucher, dict):
            continue
        pct = to_int(first(voucher.get("discount_percentage"), voucher.get("percentage_used")))
        value = to_price(voucher.get("discount_value"))
        spend = to_price(voucher.get("min_spend"))
        what = f"{pct}%" if pct else (f"{value:,.0f}đ" if value else "?")
        cond = f" đơn từ {spend:,.0f}đ" if spend else ""
        promos.append(f"Voucher shop giảm {what}{cond}")
    label = first(dig(basic, "voucher_info", "label"), dig(item, "voucher_info", "label"))
    if label:
        promos.append(f"Voucher: {label}")
    if first(basic.get("show_free_shipping"), dig(data, "product_shipping", "free_shipping"),
             item.get("show_free_shipping")):
        promos.append("Freeship")
    bundle = first(dig(basic, "bundle_deal_info", "bundle_deal_label"),
                   dig(item, "bundle_deal_info", "bundle_deal_label"))
    if bundle:
        promos.append(f"Combo: {bundle}")
    addon = first(dig(basic, "add_on_deal_info", "add_on_deal_label"),
                  dig(item, "add_on_deal_info", "add_on_deal_label"))
    if addon:
        promos.append(f"Mua kèm: {addon}")
    if first(item.get("wholesale_tier_list"), basic.get("can_use_wholesale")):
        promos.append("Mua sỉ giá tốt hơn")
    if basic.get("has_lowest_price_guarantee"):
        promos.append("Cam kết giá tốt nhất")
    # keep order, drop duplicates
    return "; ".join(dict.fromkeys(promos)) or None
