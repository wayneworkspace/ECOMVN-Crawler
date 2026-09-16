"""Stock: exact per SKU on TikTok."""
from __future__ import annotations

from ecommerce.domain.product import Stock, Variant


def parse_stock(variants: list[Variant]) -> Stock:
    counted = [v for v in variants if v.stock is not None]
    total = sum(v.stock for v in counted) if counted and len(counted) == len(variants) else None
    in_stock = sum(1 for v in variants if v.stock_status == "Còn hàng")
    state = (f"{'Còn hàng' if in_stock else 'Hết hàng'} ({in_stock}/{len(variants)} SKU còn hàng)"
             if variants else None)
    value = total if total is not None else (sum(v.stock for v in counted) if counted else None)
    return Stock(total=total, value=value, state=state)
