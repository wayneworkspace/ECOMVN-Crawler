"""A product seen on a search / keyword page, before its product page is opened.

Saved in candidates.json and copied into every raw product file, so the field
names are the ones already on disk (keeps old runs resumable). Extra keys are
allowed for the same reason: a raw file from an older version must still load.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    product_type: str | None = None
    reason: str | None = None                   # why the filter kept / dropped it

    @classmethod
    def coerce(cls, value: dict | _Candidate):
        return value if isinstance(value, cls) else cls.model_validate(value)

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ShopeeCandidate(_Candidate):
    itemid: int
    shopid: int
    page: int = 0
    is_ad: bool = False
    search_rank: int | None = None              # None for ads (not counted in the ranking)
    basic: dict[str, Any] = Field(default_factory=dict)   # the search card: 30-day sold, price...

    @property
    def key(self) -> str:
        return f"{self.shopid}_{self.itemid}"


class LazadaCandidate(_Candidate):
    """A card from the Lazada search results (mods.listItems[])."""
    item_id: str
    sku_id: str = ""
    seller_id: str = ""
    page: int = 0
    is_ad: bool = False
    search_rank: int | None = None              # None for ads
    basic: dict[str, Any] = Field(default_factory=dict)   # the card: priceShow, itemSoldCntShow, ratingScore...

    @property
    def key(self) -> str:
        return f"{self.seller_id or '0'}_{self.item_id}"


class TikTokCandidate(_Candidate):
    product_id: str
    seller_id: str = ""
    listing_sold: int = 0
    listing_price: int | None = None
    brand: str | None = None
    shop_name: str | None = None
    rating: float | None = None
    image: str | None = None
    source_slug: str | None = None
    source_page: int | None = None
    source_pos: int | None = None
    seen_on: int = 1
    pool_rank: int | None = None

    @property
    def key(self) -> str:
        return f"{self.seller_id}_{self.product_id}"
