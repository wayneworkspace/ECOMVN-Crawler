"""Rating score and star distribution (review_info.review_ratings)."""
from __future__ import annotations

from ecommerce.domain.product import Rating
from ecommerce.platforms.tiktok.parse.common import TikTokRaw, _d, to_float, to_int


def parse_rating(src: TikTokRaw) -> Rating:
    ratings = _d(_d(src.comp.get("review_info")).get("review_ratings"))
    dist = _d(ratings.get("rating_result"))
    star = to_float(ratings.get("overall_score")) or src.candidate.get("rating")
    return Rating(
        star=round(star, 2) if star is not None else None,
        total=to_int(ratings.get("review_count") or _d(src.comp.get("review_info")).get("total_reviews")),
        five=to_int(dist.get("5")), four=to_int(dist.get("4")), three=to_int(dist.get("3")),
        two=to_int(dist.get("2")), one=to_int(dist.get("1")),
    )
