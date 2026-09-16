"""What the transform step hands to the report step for one platform."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ecommerce.domain.product import Platform, Product


class Excluded(BaseModel):
    """A search result the filter dropped (sheet 'Bị loại')."""
    rank: int | None = None        # Shopee: search rank; TikTok: rank in the merged pool
    source: str | int | None = None  # Shopee: search page (1-based); TikTok: keyword page slug
    name: str | None = None
    product_type: str | None = None
    reason: str | None = None
    url: str | None = None


class Dataset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    platform: Platform
    run_id: str
    products: list[Product]                        # ranked, top N
    excluded: list[Excluded] = Field(default_factory=list)
    failures: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)   # sheet 'Thông tin'
