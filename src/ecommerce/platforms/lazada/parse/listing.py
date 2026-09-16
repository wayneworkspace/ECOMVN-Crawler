"""Search result pages (JSON, `ajax=true`) -> ordered candidates."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ecommerce.domain.candidate import LazadaCandidate
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.lazada.parse.common import _d, _l, dig, first, to_int
from ecommerce.transformation.filters import classify


@dataclass
class SearchHit:
    item_id: str
    sku_id: str
    seller_id: str
    name: str
    is_ad: bool
    basic: dict


def search_items(payload: dict) -> list[dict]:
    payload = _d(payload)
    return _l(first(dig(payload, "mods", "listItems"), payload.get("listItems"), dig(payload, "data", "listItems")))


def total_results(payload: dict) -> int | None:
    return to_int(first(dig(payload, "mainInfo", "totalResults"), dig(payload, "mainInfo", "total")))


def _is_ad(item: dict) -> bool:
    """Sponsored card. Confirmed 14/09 on real pages: organic cards carry
    isSponsored=false, adFlag="0", utLogMap.src="organic"; every card has a
    clickTrace, so that key must NOT be used."""
    if item.get("isSponsored") in (True, 1, "1", "true"):
        return True
    if str(item.get("adFlag") or "0") not in ("0", "", "false", "False"):
        return True
    src = str(_d(item.get("utLogMap")).get("src") or _d(item.get("utLogMap")).get("trafficType") or "").lower()
    return src in ("ad", "ads", "sponsored", "p4p")


def parse_search_page(payload: dict) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for entry in search_items(payload):
        if not isinstance(entry, dict):
            continue
        item_id = first(entry.get("itemId"), entry.get("nid"), entry.get("item_id"))
        if not item_id:
            continue
        hits.append(SearchHit(
            item_id=str(item_id),
            sku_id=str(first(entry.get("skuId"), entry.get("sku"), "") or ""),
            seller_id=str(first(entry.get("sellerId"), entry.get("seller_id"), "") or ""),
            name=str(first(entry.get("name"), entry.get("title"), "") or ""),
            is_ad=_is_ad(entry),
            basic=entry,
        ))
    return hits


def select_candidates(pages: Iterable[tuple[int, dict]], target: int, include_ads: bool,
                      profile: DomainProfile | None = None) -> tuple[list[LazadaCandidate], list[LazadaCandidate]]:
    """Walk search pages in order -> (kept, excluded). `search_rank` = position
    among organic results in Lazada's 'Bán chạy' order, counted BEFORE the
    domain filter (gaps in the rank show what the filter removed)."""
    kept: list[LazadaCandidate] = []
    excluded: list[LazadaCandidate] = []
    seen: set[str] = set()
    rank = 0
    for page_no, payload in sorted(pages, key=lambda p: p[0]):
        for hit in parse_search_page(payload):
            if hit.item_id in seen:
                continue
            seen.add(hit.item_id)
            row = {"item_id": hit.item_id, "sku_id": hit.sku_id, "seller_id": hit.seller_id, "name": hit.name,
                   "page": page_no, "is_ad": hit.is_ad, "basic": hit.basic}
            if hit.is_ad and not include_ads:
                excluded.append(LazadaCandidate(**row, search_rank=None, reason="quảng cáo", product_type=None))
                continue
            rank += 1
            verdict = classify(hit.name, profile)
            cand = LazadaCandidate(**row, search_rank=rank, product_type=verdict.product_type or None,
                                   reason=verdict.reason)
            (kept if verdict.keep else excluded).append(cand)
            if len(kept) >= target:
                return kept, excluded
    return kept, excluded
