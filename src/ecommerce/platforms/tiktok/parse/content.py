"""Text of a TikTok product: description blocks, attribute table, category,
images, brand, promotions."""
from __future__ import annotations

import json
from typing import Any

from ecommerce.platforms.tiktok.parse.common import TikTokRaw, _d, _l, first_url
from ecommerce.transformation.specs import attr_lookup, norm

NO_BRAND = {"không có", "no brand", "nobrand", "none", "0", "khác", "other", "oem", "không thương hiệu"}


def description_text(raw_desc: Any) -> str:
    """Description is a JSON list of blocks: text / ul (bullets) / image."""
    if not raw_desc:
        return ""
    try:
        blocks = json.loads(raw_desc) if isinstance(raw_desc, str) else raw_desc
    except (TypeError, ValueError):
        return str(raw_desc)
    if not isinstance(blocks, list):
        return str(raw_desc)
    lines: list[str] = []
    for b in blocks:
        b = _d(b)
        if b.get("type") == "text" and b.get("text"):
            lines.append(str(b["text"]).strip())
        elif b.get("type") in ("ul", "ol"):
            lines.extend(f"- {str(item).strip()}" for item in _l(b.get("content")) if item)
    return "\n".join(line for line in lines if line)


def properties(pm: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for prop in _l(pm.get("product_properties")):
        prop = _d(prop)
        name = prop.get("property_name")
        values = [str(_d(v).get("property_value_name")).strip() for v in _l(prop.get("property_values"))
                  if _d(v).get("property_value_name")]
        if name and values:
            out[str(name).strip()] = ", ".join(values)
    return out


def title(src: TikTokRaw) -> str:
    return str(src.pm.get("name") or src.candidate.get("name") or "").strip()


def brand(src: TikTokRaw, attrs: dict[str, str]) -> str | None:
    value = src.candidate.get("brand") or attr_lookup(attrs, "Thương hiệu", "Brand")
    if isinstance(value, str) and norm(value).strip() in NO_BRAND:
        return "No brand"
    return value


def category(src: TikTokRaw) -> str | None:
    return " > ".join(str(_d(c).get("category_name")) for c in _l(src.comp.get("categories"))
                      if _d(c).get("category_name")) or None


def images(src: TikTokRaw) -> list[str]:
    return [u for u in (first_url(i) for i in _l(src.pm.get("images"))) if u]


def promotions(src: TikTokRaw, discount: int | None) -> str | None:
    out: list[str] = []
    if discount:
        out.append(f"Giảm {discount}%")
    for labels in _d(_d(src.comp.get("promotion_tag")).get("placement_labels")).values():
        for label in _l(labels):
            text = _d(label).get("text")
            if text and text not in out:
                out.append(str(text))
    for lg in _l(_d(src.info.get("promotion_model")).get("promotion_logistic_list")):
        lg = _d(lg)
        for view in _l(_d(lg.get("logisticText")).get("discountViews")):
            text = _d(view).get("discountDescText")
            if text and f"Voucher ship: {text}" not in out:
                out.append(f"Voucher ship: {text}")
        if lg.get("freeShipping") and "Miễn phí vận chuyển" not in out:
            out.append("Miễn phí vận chuyển")
    return "; ".join(out) or None
