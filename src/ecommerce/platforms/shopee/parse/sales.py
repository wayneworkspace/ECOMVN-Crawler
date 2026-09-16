"""Sold counts and listing age (cumulative sold is only fair relative to age)."""
from __future__ import annotations

from datetime import datetime, timezone

from ecommerce.domain.product import Sales
from ecommerce.platforms.shopee.parse.common import ShopeeRaw, dig, first, to_int, to_seconds, ts_to_date


def parse_sales(src: ShopeeRaw, price_min: int | None, now: datetime | None = None) -> Sales:
    item, basic, review = src.item, src.basic, src.review_block
    total = to_int(first(review.get("historical_sold"), item.get("historical_sold"),
                         basic.get("historical_sold"),
                         dig(basic, "item_card_display_sold_count", "historical_sold_count")))
    last_30d = to_int(first(dig(basic, "item_card_display_sold_count", "monthly_sold_count"),
                            basic.get("sold"), item.get("sold")))
    ctime = to_seconds(first(item.get("ctime"), basic.get("ctime")))
    age_months = None
    if ctime:
        now = now or datetime.now(timezone.utc)
        age_months = round(max((now.timestamp() - ctime) / 86400 / 30.44, 0.1), 1)
    return Sales(
        total=total,
        last_30d=last_30d,
        revenue_30d_est=(price_min * last_30d) if (price_min and last_30d is not None) else None,
        listed_date=ts_to_date(ctime),
        age_months=age_months,
        per_month_lifetime=round(total / age_months) if total is not None and age_months else None,
        liked_count=to_int(first(item.get("liked_count"), basic.get("liked_count"))),
    )
