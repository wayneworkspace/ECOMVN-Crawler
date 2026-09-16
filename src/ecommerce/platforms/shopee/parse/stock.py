"""Stock: exact when every SKU was counted (pass 2 / 'pieces available'),
otherwise what Shopee lets through (it hides the number: 'IN STOCK')."""
from __future__ import annotations

import re
from typing import Any

from ecommerce.domain.product import Stock, Variant
from ecommerce.platforms.shopee.parse.common import ShopeeRaw, _s, first, to_int


def stock_from_display(text: Any) -> tuple[int | None, str | None]:
    """item.stock_display: 'IN STOCK' when Shopee hides the count, the number
    itself when stock runs low (e.g. '84')."""
    text = _s(text)
    if text is None:
        return None, None
    digits = re.sub(r"[^\d]", "", text)
    if digits and digits == re.sub(r"[.,\s]", "", text):
        return int(digits), None
    upper = text.upper()
    if "OUT" in upper or "HẾT" in upper or "SOLD" in upper:
        return 0, "Hết hàng"
    return None, "Còn hàng"


def parse_stock(src: ShopeeRaw, variants: list[Variant]) -> Stock:
    item, basic = src.item, src.basic
    display_count, display_status = stock_from_display(item.get("stock_display"))
    with_status = [v for v in variants if v.stock_status]
    in_stock = sum(1 for v in with_status if v.stock_status == "Còn hàng")
    counted = [v for v in variants if v.stock is not None]
    partial_sum = None
    if counted and len(counted) == len(variants):
        total = sum(v.stock for v in counted)                  # every SKU read -> exact total
    else:
        total = to_int(first(item.get("stock"), item.get("normal_stock"), display_count, basic.get("stock")))
        if counted:
            partial_sum = sum(v.stock for v in counted)        # lower bound only
    # "Tồn kho" (a number) and "Tình trạng" (words) are separate columns
    value = total if total is not None else partial_sum
    state = []
    if with_status:
        state.append(f"{'Còn hàng' if in_stock else 'Hết hàng'} ({in_stock}/{len(with_status)} SKU còn hàng)")
    elif display_status:
        state.append(display_status)
    if total is None and partial_sum is not None:
        state.append(f"tồn kho tối thiểu: đếm được {len(counted)}/{len(variants)} SKU")
    elif value is None and display_status:
        state.append("sàn ẩn số lượng")
    return Stock(total=total, value=value, state="; ".join(state) or None)
