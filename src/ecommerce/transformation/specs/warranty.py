"""Warranty period / type (attribute values may come in English: translated)."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

_WARRANTY_RX = re.compile(
    r"bảo hành\s*(?:chính hãng|điện tử|sản phẩm)?\s*[:\-]?\s*(?:lên (?:đến|tới)\s*)?"
    r"(\d{1,3})\s*(tháng|năm|ngày|th\b)")
_LIFETIME_RX = re.compile(r"bảo hành\s*(?:vĩnh viễn|trọn đời)")
_EXCHANGE_RX = re.compile(r"(1\s*đổi\s*1|đổi trả|đổi mới)[^.\n;|]{0,25}?(\d{1,3})\s*(ngày|tháng)")


_WARRANTY_EN = [
    (r"international manufacturer warranty", "Bảo hành quốc tế"),
    (r"manufacturer warranty", "Bảo hành nhà sản xuất"),
    (r"supplier warranty", "Bảo hành nhà cung cấp"),
    (r"no warranty", "Không bảo hành"),
    (r"\bmonths?\b", "tháng"),
    (r"\byears?\b", "năm"),
    (r"\bdays?\b", "ngày"),
]


def _vi_warranty(text: str) -> str:
    """Shopee returns attribute values in the account's UI language."""
    for rx, vi in _WARRANTY_EN:
        text = re.sub(rx, vi, text, flags=re.IGNORECASE)
    return text


def extract_warranty(attrs, title, description) -> Found:
    period = attr_lookup(attrs, "Thời hạn bảo hành", "Bảo hành", "Warranty Duration", "Warranty Period")
    kind = attr_lookup(attrs, "Loại bảo hành", "Warranty Type")
    if period or kind:
        return Found(" - ".join(_vi_warranty(x) for x in (period, kind) if x), "thuộc tính")
    for source, text in (("tiêu đề", title), ("mô tả", description)):
        text = norm(text)
        m = _WARRANTY_RX.search(text)
        if m:
            unit = "tháng" if m.group(2) == "th" else m.group(2)
            return Found(f"{m.group(1)} {unit}", source)
        if _LIFETIME_RX.search(text):
            return Found("Trọn đời", source)
        m = _EXCHANGE_RX.search(text)
        if m:
            return Found(f"Đổi trả {m.group(2)} {m.group(3)}", source)
    return Found()
