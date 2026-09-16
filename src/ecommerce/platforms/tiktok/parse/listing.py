"""Keyword pages -> merged, filtered, ordered candidates."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ecommerce.domain.candidate import TikTokCandidate
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.tiktok.parse.common import _d, _l, component, first_url, to_float, to_int
from ecommerce.transformation.filters import classify, title_matches


def slug_of(link: str) -> str | None:
    m = re.search(r"/k/([^/?#]+)", link or "")
    return m.group(1) if m else None


def parse_keyword_page(components: Any) -> dict:
    feed = _d(component(components, "feed_list_search_word").get("component_data"))
    words = _d(component(components, "related_link_search_words").get("component_data"))
    cats = _d(component(components, "related_link_categories").get("component_data"))
    return {
        "products": [p for p in _l(feed.get("products")) if isinstance(p, dict) and p.get("product_id")],
        "related": [s for s in (slug_of(_d(link).get("link")) for link in _l(words.get("related_links"))) if s],
        "related_categories": [_d(link).get("link") for link in _l(cats.get("related_links"))],
    }


def listing_hit(product: dict) -> dict:
    """The few listing fields kept per product (full object stays in the raw page)."""
    price = _d(product.get("product_price_info"))
    return {
        "product_id": str(product.get("product_id")),
        "seller_id": str(_d(product.get("seller_info")).get("seller_id") or ""),
        "name": product.get("title"),
        "listing_sold": to_int(_d(product.get("sold_info")).get("sold_count")) or 0,
        "listing_price": to_int(price.get("sale_price_decimal")),
        "brand": _d(product.get("brand_info")).get("brand_name"),
        "shop_name": _d(product.get("seller_info")).get("shop_name"),
        "rating": to_float(_d(product.get("rate_info")).get("score")),
        "image": first_url(product.get("image")),
    }


def select_candidates(pages: Iterable[tuple[int, dict]], keep: int,
                      profile: DomainProfile | None = None) -> dict:
    """Union of every keyword page -> filter -> order by listing sold count.

    Returns {"kept": [...top `keep`], "kept_total", "excluded": [...dropped by the
    filter], "pool": n}. `kept` is only the crawl list; the final order uses the
    sold count on the product page.
    """
    seen: dict[str, dict] = {}
    for page_no, page in pages:
        for pos, product in enumerate(page.get("products") or []):
            hit = listing_hit(product)
            pid = hit["product_id"]
            if pid in seen:
                seen[pid]["listing_sold"] = max(seen[pid]["listing_sold"], hit["listing_sold"])
                seen[pid]["seen_on"] += 1
                continue
            hit.update(source_slug=page.get("slug"), source_page=page_no, source_pos=pos + 1, seen_on=1)
            seen[pid] = hit
    ordered = sorted(seen.values(), key=lambda h: (-h["listing_sold"], h["source_page"], h["source_pos"]))
    kept: list[TikTokCandidate] = []
    excluded: list[TikTokCandidate] = []
    for rank, hit in enumerate(ordered, start=1):
        verdict = classify(hit["name"], profile)
        cand = TikTokCandidate(**{**hit, "name": hit["name"] or ""}, pool_rank=rank,
                               product_type=verdict.product_type or None)
        if not title_matches(hit["name"], profile, "tiktok"):
            cand.reason = profile.filter.title_must_match_reason
        elif not verdict.keep:
            cand.reason = verdict.reason
        else:
            kept.append(cand)
            continue
        excluded.append(cand)
    return {"kept": kept[:keep], "kept_total": len(kept), "excluded": excluded, "pool": len(ordered)}
