"""Raw Shopee product file -> Product. Only assembles; each block is parsed
by its own small function (content / variants / price / sales / stock /
rating / shop) and the specs by transform/specs."""
from __future__ import annotations

from ecommerce.domain.product import Product
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.shopee.parse import content
from ecommerce.platforms.shopee.parse.common import PRODUCT_URL, ShopeeRaw
from ecommerce.platforms.shopee.parse.price import parse_price
from ecommerce.platforms.shopee.parse.rating import parse_rating, rating_summary
from ecommerce.platforms.shopee.parse.sales import parse_sales
from ecommerce.platforms.shopee.parse.shop import parse_shop
from ecommerce.platforms.shopee.parse.stock import parse_stock
from ecommerce.platforms.shopee.parse.variants import parse_variants
from ecommerce.transformation.filters import classify
from ecommerce.transformation.specs import attributes_text, extract_specs


def parse_product(raw: dict, profile: DomainProfile | None = None) -> Product:
    src = ShopeeRaw.from_raw(raw)
    title = content.title(src)
    description = content.description(src)
    attrs = content.attributes(src)
    variants, tiers = parse_variants(src)
    variant_names = [v.name for v in variants if v.name]
    for tier in tiers:
        variant_names.extend(o for o in tier["options"] if o)

    price = parse_price(src, variants)
    summary = rating_summary(raw)
    return Product(
        platform="shopee",
        item_id=src.itemid,
        url=PRODUCT_URL.format(shopid=src.shopid, itemid=src.itemid),
        title=title,
        product_type=classify(title, profile).product_type or None,
        brand=content.brand(src, attrs),
        category=content.category(src),
        description=description or None,
        attributes_raw=attributes_text(attrs) or None,
        promotions=content.promotions(src, price.discount_pct, price.final_price, price.min),
        images=content.images(src),
        video_count=content.video_count(src),
        tier_names=" / ".join(t["name"] for t in tiers if t["name"]) or None,
        variants=variants,
        price=price,
        sales=parse_sales(src, price.min),
        stock=parse_stock(src, variants),
        rating=parse_rating(src, summary),
        specs=extract_specs(attrs, variant_names, tiers, title, description, profile),
        shop=parse_shop(src),
        search_rank=src.candidate.get("search_rank"),
        search_page=src.candidate.get("page"),
        is_ad=src.candidate.get("is_ad"),
        scraped_at=raw.get("scraped_at"),
    )
