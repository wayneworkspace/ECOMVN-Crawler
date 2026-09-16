"""Rating score, star distribution and (optionally) review texts."""
from __future__ import annotations

from ecommerce.domain.product import Rating
from ecommerce.platforms.shopee.parse.common import ShopeeRaw, _d, _l, dig, first, to_float, to_int


def rating_summary(raw: dict) -> dict:
    """The star summary block of the get_ratings pages (reviews with photos, with text...).

    Only the summary is taken: individual review texts are used nowhere (see
    decisions.md #6: the product page only loads featured reviews, 148/148 were
    5 stars, so they are not representative).
    """
    summary: dict = {}
    for payload in _l(raw.get("ratings")):
        data = _d(dig(payload, "data"))
        summary = _d(first(_d(data.get("item_rating_summary")), summary))
    return summary


def parse_rating(src: ShopeeRaw, summary: dict) -> Rating:
    """rating_count = [total, 1*, 2*, 3*, 4*, 5*] (index = number of stars)."""
    item, basic, review = src.item, src.basic, src.review_block
    counts = _l(first(review.get("rating_count"), dig(item, "item_rating", "rating_count"),
                      dig(basic, "item_rating", "rating_count")))
    counts = counts or _l(summary.get("rating_count"))
    star = to_float(first(review.get("rating_star"), dig(item, "item_rating", "rating_star"),
                          dig(basic, "item_rating", "rating_star")))
    return Rating(
        star=round(star, 2) if star is not None else None,
        total=to_int(first(review.get("total_rating_count"), dig(counts, 0),
                           summary.get("rating_total"), basic.get("cmt_count"))),
        five=to_int(dig(counts, 5)), four=to_int(dig(counts, 4)), three=to_int(dig(counts, 3)),
        two=to_int(dig(counts, 2)), one=to_int(dig(counts, 1)),
        with_comment=to_int(summary.get("rcount_with_context")),
        with_media=to_int(first(summary.get("rcount_with_media"), summary.get("rcount_with_image"))),
    )
