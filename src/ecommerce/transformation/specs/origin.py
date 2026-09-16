"""Country of origin."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

# Whole country names only: bare "nhật" / "hàn" / "mỹ" / "đức" also live inside
# ordinary words ("cập nhật", "cửa hàng", "thẩm mỹ", "đức tính").
_COUNTRIES: list[tuple[str, str]] = [
    (r"việt nam|viet nam|vietnam|\bvn\b", "Việt Nam"),
    (r"trung quốc|\bchina\b|\btq\b|quảng châu", "Trung Quốc"),
    (r"nhật bản|\bjapan\b", "Nhật Bản"),
    (r"hàn quốc|\bkorea\b", "Hàn Quốc"),
    (r"thái lan|thailand", "Thái Lan"),
    (r"đài loan|taiwan", "Đài Loan"),
    (r"(?<!thẩm )\bmỹ\b|hoa kỳ|\busa?\b|america", "Mỹ"),
    (r"\bđức\b(?! tính)|germany", "Đức"),
    (r"malaysia", "Malaysia"),
    (r"indonesia", "Indonesia"),
    (r"ấn độ|india", "Ấn Độ"),
]
_ORIGIN_CTX = re.compile(
    r"(?:xuất xứ|sản xuất tại|made in|nước sản xuất|nguồn gốc|nhập khẩu từ|hàng nhập)\s*[:\-]?\s*([^\n.;|,]{2,30})")


def _country(text: str) -> str | None:
    for rx, name in _COUNTRIES:
        if re.search(rx, text):
            return name
    return None


def extract_origin(attrs, title, description) -> Found:
    value = attr_lookup(attrs, "Xuất xứ", "Nơi sản xuất", "Country of Origin", "Quốc gia xuất xứ",
                        "Xuất xứ thương hiệu")
    if value:
        return Found(_country(norm(value)) or value, "thuộc tính")
    for source, text in (("tiêu đề", title), ("mô tả", description)):
        for m in _ORIGIN_CTX.finditer(norm(text)):
            country = _country(m.group(1))
            if country:
                return Found(country, source)
    return Found()
