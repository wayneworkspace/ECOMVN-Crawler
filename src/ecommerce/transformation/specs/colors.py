"""Colours: a 'Màu...' variation group first, then options that name a colour."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

_COLOR_WORDS = (
    "đen", "trắng", "hồng", "xanh", "đỏ", "vàng", "tím", "xám", "ghi", "bạc", "kem",
    "nâu", "cam", "be", "rêu", "pastel", "gold", "black", "white", "pink", "blue",
    "green", "red", "grey", "gray", "silver", "purple", "cream", "navy", "mint",
)
# lookaheads keep "cam kết", "ghi chú", "can be used" from reading as colours
_COLOR_RX = re.compile(r"(?<![a-zà-ỹ])(" + "|".join(_COLOR_WORDS) + r")(?![a-zà-ỹ])"
                       r"(?<!cam(?= kết))(?<!ghi(?= chú))(?<!be(?= [a-z]))")


def is_color_tier(tier_name: str | None) -> bool:
    return bool(re.search(r"màu|mầu|colou?r|họa tiết|hoạ tiết|mẫu", norm(tier_name)))


def looks_like_color(option: str) -> bool:
    return bool(_COLOR_RX.search(norm(option)))


def extract_colors(tiers: list[dict], attrs, title) -> Found:
    """Colours from a tier named 'Màu...', else options that name a colour."""
    for tier in tiers:
        if is_color_tier(tier.get("name")):
            options = [o for o in tier.get("options") or [] if o]
            if options:
                return Found(", ".join(options), "phân loại")
    guessed: list[str] = []
    for tier in tiers:
        for option in tier.get("options") or []:
            if option and looks_like_color(option) and option not in guessed:
                guessed.append(option)
    if guessed:
        return Found(", ".join(guessed), "phân loại")
    value = attr_lookup(attrs, "Màu sắc", "Màu", "Color")
    if value:
        return Found(value, "thuộc tính")
    words = []
    for w in _COLOR_RX.findall(norm(title)):
        if w not in words:
            words.append(w)
    return Found(", ".join(words), "tiêu đề") if words else Found()
