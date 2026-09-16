"""The product record every layer agrees on (transform -> report).

Parsers of each platform return a `Product`; the Excel writer only knows
`Product`. Adding a platform means writing a parser that fills this model --
nothing in report/ changes.

Rules the model enforces:
    * a number is a number (a price that arrives as "abc" fails right here,
      naming the product and the field, instead of leaving a blank cell);
    * missing data is None, never 0 ("sold 0" would be a false statement);
    * prices and counts are >= 0, a discount is 0..100, a rating is 0..5.

`to_row()` flattens it into the column keys used by report/columns.py.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["shopee", "tiktok", "lazada"]
Id = int | str                      # Shopee ids are numbers, TikTok ids 19-digit strings
Money = int | None                  # whole VND
Count = int | None


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Variant(_Model):
    """One SKU; `tiers` are the shop's own option groups verbatim, e.g.
    [("Màu Sắc", "Xanh bầu trời"), ("Dung tích", "500ml")]."""
    model_id: Id | None = None
    name: str | None = None
    tiers: list[tuple[str, str]] = Field(default_factory=list)
    color: str | None = None
    capacity: str | None = None
    price: Money = Field(None, ge=0)
    price_before_discount: Money = Field(None, ge=0)
    final_price: Money = Field(None, ge=0)          # after auto-applied voucher (Shopee)
    stock: Count = Field(None, ge=0)
    stock_status: Literal["Còn hàng", "Hết hàng"] | None = None
    sold: Count = Field(None, ge=0)
    image: str | None = None


class Price(_Model):
    min: Money = Field(None, ge=0)
    max: Money = Field(None, ge=0)
    before_min: Money = Field(None, ge=0)          # list price before the shop's discount
    before_max: Money = Field(None, ge=0)
    discount_pct: int | None = Field(None, ge=0, le=100)
    final_price: Money = Field(None, ge=0)          # after voucher; per account (Shopee only)
    currency: str = "VND"


class Sales(_Model):
    total: Count = Field(None, ge=0)                # cumulative sold shown on the product page
    last_30d: Count = Field(None, ge=0)             # Shopee search card; TikTok does not publish it
    listing_sold: Count = Field(None, ge=0)         # TikTok keyword page
    revenue_30d_est: Money = Field(None, ge=0)
    listed_date: str | None = None
    age_months: float | None = Field(None, ge=0)
    per_month_lifetime: Count = Field(None, ge=0)
    liked_count: Count = Field(None, ge=0)


class Stock(_Model):
    total: Count = Field(None, ge=0)                # exact: every SKU counted
    value: Count = Field(None, ge=0)                # total, or a lower bound when some SKUs are unknown
    state: str | None = None                     # "Còn hàng (39/54 SKU còn hàng)"


class Rating(_Model):
    star: float | None = Field(None, ge=0, le=5)
    total: Count = Field(None, ge=0)
    five: Count = Field(None, ge=0)
    four: Count = Field(None, ge=0)
    three: Count = Field(None, ge=0)
    two: Count = Field(None, ge=0)
    one: Count = Field(None, ge=0)
    with_comment: Count = Field(None, ge=0)
    with_media: Count = Field(None, ge=0)


class Specs(_Model):
    """Regex results (transform/specs); *_source says where each value came from."""
    capacity: str | None = None
    capacity_min_ml: Count = None
    capacity_max_ml: Count = None
    capacity_source: str | None = None
    material_inner: str | None = None
    material_outer: str | None = None
    material_all: str | None = None
    material_source: str | None = None
    colors: str | None = None
    size: str | None = None
    weight: str | None = None
    features: str | None = None
    origin: str | None = None
    origin_source: str | None = None
    warranty: str | None = None
    warranty_source: str | None = None
    # Named attribute groups declared by the domain profile (features.groups),
    # e.g. {"grade": "10W-40", "type": "Bán tổng hợp"}; exported as attr_<group> columns.
    attributes: dict[str, str] = Field(default_factory=dict)


class Shop(_Model):
    id: Id | None = None
    name: str | None = None
    username: str | None = None
    url: str | None = None
    location: str | None = None
    response_rate: int | None = Field(None, ge=0, le=100)
    response_time: str | None = None
    rating: float | None = Field(None, ge=0, le=5)
    followers: Count = Field(None, ge=0)
    products: Count = Field(None, ge=0)
    sold: Count = Field(None, ge=0)
    joined: str | None = None
    is_mall: bool | None = None
    is_preferred: bool | None = None
    ship_48h: int | None = Field(None, ge=0, le=100)   # TikTok: % orders shipped in 48h


class Product(_Model):
    platform: Platform
    item_id: Id
    url: str
    title: str
    product_type: str | None = None
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    attributes_raw: str | None = None
    promotions: str | None = None
    images: list[str] = Field(default_factory=list)
    video_count: int = Field(0, ge=0)
    tier_names: str | None = None
    variants: list[Variant] = Field(default_factory=list)

    price: Price = Field(default_factory=Price)
    sales: Sales = Field(default_factory=Sales)
    stock: Stock = Field(default_factory=Stock)
    rating: Rating = Field(default_factory=Rating)
    specs: Specs = Field(default_factory=Specs)
    shop: Shop = Field(default_factory=Shop)

    # where it came from / where it ends up
    search_rank: int | None = None        # Shopee: position in 'Bán chạy' (ads excluded)
    search_page: int | None = None
    pool_rank: int | None = None          # TikTok: rank by listing sold in the merged pool
    source_slug: str | None = None        # TikTok keyword page it was found on
    is_ad: bool | None = None
    final_rank: int | None = None         # rank in the Excel file
    scraped_at: str | None = None

    def to_row(self) -> dict[str, Any]:
        """Flat dict keyed like report/columns.py (and like the old records)."""
        p, s, st, r, sp, sh = self.price, self.sales, self.stock, self.rating, self.specs, self.shop
        return {
            "platform": self.platform, "final_rank": self.final_rank,
            "search_rank": self.search_rank, "search_page": self.search_page,
            "pool_rank": self.pool_rank, "source_slug": self.source_slug, "is_ad": self.is_ad,
            "item_id": self.item_id, "shop_id": sh.id, "url": self.url, "title": self.title,
            "product_type": self.product_type, "brand": self.brand, "category": self.category,
            # price
            "price_min": p.min, "price_max": p.max, "price_before_min": p.before_min,
            "price_before_max": p.before_max, "discount_pct": p.discount_pct,
            "final_price": p.final_price, "currency": p.currency,
            # sales
            "sold_total": s.total, "sold_30d": s.last_30d, "listing_sold": s.listing_sold,
            "revenue_30d_est": s.revenue_30d_est, "listed_date": s.listed_date,
            "age_months": s.age_months, "sold_per_month_lifetime": s.per_month_lifetime,
            "liked_count": s.liked_count,
            # stock
            "stock_total": st.total, "stock_value": st.value, "stock_state": st.state,
            # rating
            "rating_star": r.star, "rating_total": r.total, "rating_5": r.five, "rating_4": r.four,
            "rating_3": r.three, "rating_2": r.two, "rating_1": r.one,
            "rating_with_comment": r.with_comment, "rating_with_media": r.with_media,
            # specs (+ one attr_<group> key per named attribute group)
            **sp.model_dump(exclude={"attributes"}),
            **{f"attr_{k}": v for k, v in sp.attributes.items()},
            # content
            "attributes_raw": self.attributes_raw, "description": self.description,
            "promotions": self.promotions, "images": list(self.images),
            "image_count": len(self.images), "video_count": self.video_count,
            "variant_count": len(self.variants), "tier_names": self.tier_names,
            "variants": [v.model_dump() for v in self.variants],
            # shop
            "shop_name": sh.name, "shop_username": sh.username, "shop_url": sh.url,
            "shop_location": sh.location, "shop_response_rate": sh.response_rate,
            "shop_response_time": sh.response_time, "shop_rating": sh.rating,
            "shop_followers": sh.followers, "shop_products": sh.products, "shop_sold": sh.sold,
            "shop_joined": sh.joined, "shop_is_mall": sh.is_mall,
            "shop_is_preferred": sh.is_preferred, "shop_ship_48h": sh.ship_48h,
            "scraped_at": self.scraped_at,
        }
