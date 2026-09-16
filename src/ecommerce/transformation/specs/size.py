"""Dimensions and weight."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

_NUM = r"\d{1,3}(?:[.,]\d{1,2})?"
_DIMS_RX = re.compile(rf"({_NUM})\s*[x×*]\s*({_NUM})(?:\s*[x×*]\s*({_NUM}))?\s*(cm|mm)")
_NAMED_DIM_RX = re.compile(rf"(chiều cao|cao|đường kính|miệng|đáy|rộng|dài)\s*(?:bình|ly|cốc)?\s*[:\-]?\s*({_NUM})\s*(cm|mm)")
_WEIGHT_RX = re.compile(r"(?:trọng lượng|khối lượng|cân nặng|nặng)\s*(?:tịnh|bình)?\s*[:\-]?\s*(\d{2,4}(?:[.,]\d)?)\s*(g|gr|gram|kg)\b")


def extract_size(attrs, title, description) -> Found:
    value = attr_lookup(attrs, "Kích thước", "Kích thước (Dài x Rộng x Cao)", "Dimensions", "Kích cỡ",
                        "Size", "Product Size", "Product Dimensions")
    if value:
        return Found(value, "thuộc tính")
    for source, text in (("tiêu đề", title), ("mô tả", description)):
        text = norm(text)
        m = _DIMS_RX.search(text)
        if m:
            dims = " x ".join(g for g in m.groups()[:3] if g)
            return Found(f"{dims} {m.group(4)}", source)
        named = []
        for label, number, unit in _NAMED_DIM_RX.findall(text):
            item = f"{label} {number}{unit}"
            if item not in named:
                named.append(item)
        if named:
            return Found("; ".join(named[:4]), source)
    return Found()


def extract_weight(attrs, description) -> Found:
    value = attr_lookup(attrs, "Trọng lượng", "Khối lượng", "Cân nặng", "Weight", "Product Weight")
    if value:
        return Found(value, "thuộc tính")
    m = _WEIGHT_RX.search(norm(description))
    if m:
        return Found(f"{m.group(1)}{m.group(2)}", "mô tả")
    return Found()
