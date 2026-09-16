"""Raw TikTok product file -> Product (same model as Shopee)."""
from __future__ import annotations

from ecommerce.domain.product import Product, Sales
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.tiktok.parse import content
from ecommerce.platforms.tiktok.parse.common import PRODUCT_URL, TikTokRaw, _l, to_int
from ecommerce.platforms.tiktok.parse.price import parse_price
from ecommerce.platforms.tiktok.parse.rating import parse_rating
from ecommerce.platforms.tiktok.parse.shop import parse_shop
from ecommerce.platforms.tiktok.parse.stock import parse_stock
from ecommerce.platforms.tiktok.parse.variants import parse_variants
from ecommerce.transformation.filters import classify
from ecommerce.transformation.specs import attributes_text, extract_specs


def parse_product(raw: dict, profile: DomainProfile | None = None) -> Product:
    src = TikTokRaw.from_raw(raw)
    title = content.title(src)
    description = content.description_text(src.pm.get("description"))
    attrs = content.properties(src.pm)
    variants, tiers = parse_variants(src)
    price = parse_price(src, variants)
    return Product(
        platform="tiktok",
        item_id=src.product_id,
        url=PRODUCT_URL.format(product_id=src.product_id),
        title=title,
        product_type=classify(title, profile).product_type or None,
        brand=content.brand(src, attrs),
        category=content.category(src),
        description=description or None,
        attributes_raw=attributes_text(attrs) or None,
        promotions=content.promotions(src, price.discount_pct),
        images=content.images(src),
        video_count=len(_l(src.pm.get("videos"))),
        tier_names=" / ".join(str(t["name"]) for t in tiers if t.get("name")) or None,
        variants=variants,
        price=price,
        sales=Sales(total=to_int(src.pm.get("sold_count")), listing_sold=src.candidate.get("listing_sold")),
        stock=parse_stock(variants),
        rating=parse_rating(src),
        specs=extract_specs(attrs, [v.name for v in variants if v.name], tiers, title, description, profile),
        shop=parse_shop(src, attrs),
        pool_rank=src.candidate.get("pool_rank"),
        source_slug=src.candidate.get("source_slug"),
        scraped_at=raw.get("scraped_at"),
    )
