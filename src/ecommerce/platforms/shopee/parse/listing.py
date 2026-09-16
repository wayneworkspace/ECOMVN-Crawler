"""Search result pages -> ordered candidates (which product pages to open)."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.shopee.parse.common import _d, _l, dig, first, to_int
from ecommerce.transformation.filters import classify


@dataclass
class SearchHit:
    itemid: int
    shopid: int
    name: str
    is_ad: bool
    basic: dict


def search_items(payload: dict) -> list[dict]:
    payload = _d(payload)
    return _l(first(payload.get("items"), dig(payload, "data", "items")))


def parse_search_page(payload: dict) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for entry in search_items(payload):
        if not isinstance(entry, dict):
            continue
        basic = _d(first(_d(entry.get("item_basic")), _d(entry.get("item_data")), entry))
        itemid = to_int(first(basic.get("itemid"), entry.get("itemid"), basic.get("item_id")))
        shopid = to_int(first(basic.get("shopid"), entry.get("shopid"), basic.get("shop_id")))
        if not itemid or not shopid:
            continue
        name = first(basic.get("name"), dig(entry, "item_card_displayed_asset", "name"), "")
        is_ad = bool(first(entry.get("adsid"), basic.get("adsid"), entry.get("campaignid")))
        hits.append(SearchHit(itemid, shopid, str(name), is_ad, basic))
    return hits


def select_candidates(pages: Iterable[tuple[int, dict]], target: int, include_ads: bool,
                      profile: DomainProfile | None = None) -> tuple[list[ShopeeCandidate], list[ShopeeCandidate]]:
    """Walk search pages in order -> (kept, excluded).

    `search_rank` is the position among organic results in Shopee's own
    'Bán chạy' order, counted BEFORE our filter -- so the Excel shows where
    Shopee put the item, and gaps in the rank show what the filter removed.
    """
    kept: list[ShopeeCandidate] = []
    excluded: list[ShopeeCandidate] = []
    seen: set[tuple[int, int]] = set()
    rank = 0
    for page_no, payload in sorted(pages, key=lambda p: p[0]):
        for hit in parse_search_page(payload):
            key = (hit.shopid, hit.itemid)
            if key in seen:
                continue
            seen.add(key)
            row = {"itemid": hit.itemid, "shopid": hit.shopid, "name": hit.name, "page": page_no,
                       "is_ad": hit.is_ad, "basic": hit.basic}
            if hit.is_ad and not include_ads:
                excluded.append(ShopeeCandidate(**row, search_rank=None, reason="quảng cáo (adsid)",
                                                product_type=None))
                continue
            rank += 1
            verdict = classify(hit.name, profile)
            cand = ShopeeCandidate(**row, search_rank=rank, product_type=verdict.product_type,
                                   reason=verdict.reason)
            (kept if verdict.keep else excluded).append(cand)
            if len(kept) >= target:
                return kept, excluded
    return kept, excluded
