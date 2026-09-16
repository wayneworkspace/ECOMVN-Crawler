"""Raw Lazada product file -> Product (same model as Shopee / TikTok).

Every reader tries several candidate paths (Lazada renames keys between
releases); contracts/lazada.py lists the same paths so `check-schema` reports
which one currently serves the value.
"""
from __future__ import annotations

import re

from ecommerce.domain.product import Price, Product, Rating, Sales, Shop, Stock, Variant
from ecommerce.domain.profile import DomainProfile
from ecommerce.platforms.lazada.parse.common import (
    BASE,
    PRODUCT_URL,
    LazadaRaw,
    _d,
    _l,
    dig,
    first,
    sold_count,
    strip_html,
    to_float,
    to_int,
)
from ecommerce.transformation.filters import classify
from ecommerce.transformation.specs import attributes_text, capacities_ml, extract_specs

NO_BRAND = {"no brand", "không có thương hiệu", "oem", "none", ""}


# ---- content ---------------------------------------------------------------
def title(src: LazadaRaw) -> str:
    return str(first(src.product.get("title"), src.product.get("name"), src.candidate.get("name"), "") or "")


def description(src: LazadaRaw) -> str:
    p = src.product
    parts = [strip_html(first(p.get("highlights"), "")), strip_html(first(p.get("desc"), p.get("description"), ""))]
    return "\n".join(x for x in parts if x).strip()


def attributes(src: LazadaRaw) -> dict[str, str]:
    """The 'Thông số kỹ thuật' table: specifications[].features {key: value}."""
    attrs: dict[str, str] = {}
    for block in _l(src.fields.get("specifications")):
        feats = _d(_d(block).get("features"))
        for k, v in feats.items():
            if v not in (None, ""):
                attrs[str(k)] = str(v)
    for k, v in _d(src.fields.get("specifications")).items():      # dict form in some releases
        if isinstance(v, (str, int, float)):
            attrs.setdefault(str(k), str(v))
    return attrs


def brand(src: LazadaRaw, attrs: dict[str, str]) -> str | None:
    value = first(src.product.get("brandName"), dig(src.product, "brand", "name"), attrs.get("Thương hiệu"),
                  attrs.get("Brand"), _d(src.candidate.get("basic")).get("brandName"))
    return None if not value or str(value).strip().lower() in NO_BRAND else str(value).strip()


def category(src: LazadaRaw) -> str | None:
    crumbs = [str(_d(c).get("title") or _d(c).get("name") or "") for c in _l(src.fields.get("breadcrumb"))]
    crumbs = [c for c in crumbs if c]
    return " > ".join(crumbs) or None


def images(src: LazadaRaw) -> list[str]:
    urls: list[str] = []
    for gallery in (src.fields.get("skuGalleries"), src.fields.get("gallery"), src.product.get("images")):
        items = gallery if isinstance(gallery, list) else [v for vs in _d(gallery).values() for v in _l(vs)]
        for g in items:
            url = g if isinstance(g, str) else first(_d(g).get("src"), _d(g).get("url"), _d(g).get("image"))
            if url and url not in urls:
                urls.append(_abs(url))
    if not urls:
        card = _d(src.candidate.get("basic")).get("image")
        if card:
            urls.append(_abs(card))
    return urls


def _abs(url: str) -> str:
    return "https:" + url if str(url).startswith("//") else str(url)


# ---- variants ----------------------------------------------------------------
def parse_tiers(src: LazadaRaw) -> tuple[list[dict], dict[str, tuple[str, str, str | None]]]:
    """Variation groups + vid -> (group name, option name, option image)."""
    tiers: list[dict] = []
    by_vid: dict[str, tuple[str, str, str | None]] = {}
    for prop in _l(dig(src.fields, "productOption", "skuBase", "properties")):
        prop = _d(prop)
        name = str(first(prop.get("name"), prop.get("propName"), "Phân loại"))
        options = []
        for v in _l(prop.get("values")):
            v = _d(v)
            label = str(first(v.get("name"), v.get("valueName"), ""))
            options.append(label)
            if v.get("vid") is not None:
                by_vid[str(v["vid"])] = (name, label, _abs(v["image"]) if v.get("image") else None)
        tiers.append({"name": name, "options": options})
    return tiers, by_vid


def parse_variants(src: LazadaRaw) -> tuple[list[Variant], list[dict]]:
    tiers, by_vid = parse_tiers(src)
    infos = _d(src.fields.get("skuInfos"))
    skus = _l(dig(src.fields, "productOption", "skuBase", "skus"))
    if not skus:                           # single-SKU product: skuInfos still has the price / stock
        skus = [{"skuId": sid, "propPath": ""} for sid in infos if sid != "0"] or [{"skuId": src.sku_id, "propPath": ""}]
    variants: list[Variant] = []
    for sku in skus:
        sku = _d(sku)
        sid = str(first(sku.get("skuId"), sku.get("innerSkuId"), ""))
        info = _d(infos.get(sid)) or _d(infos.get("0"))
        pairs, image = [], None
        for pv in str(sku.get("propPath") or "").split(";"):
            vid = pv.split(":")[-1]
            if vid in by_vid:
                g, o, img = by_vid[vid]
                pairs.append((g, o))
                image = image or img
        name = " / ".join(o for _, o in pairs) or None
        stock = to_int(first(info.get("stock"), dig(info, "stock", "value")))
        price = _d(info.get("price"))
        sale = to_int(first(dig(price, "salePrice", "value"), price.get("salePrice"), info.get("salePrice")))
        original = to_int(first(dig(price, "originalPrice", "value"), price.get("originalPrice"), info.get("originalPrice")))
        caps = capacities_ml(name)
        variants.append(Variant(
            model_id=sid or None, name=name, tiers=pairs,
            capacity=f"{caps[0]}ml" if caps else None,
            price=sale, price_before_discount=original if original and sale and original > sale else None,
            stock=stock,
            stock_status=None if stock is None else ("Hết hàng" if stock == 0 else "Còn hàng"),
            image=image or (_abs(info["image"]) if info.get("image") else None),
        ))
    return variants, tiers


# ---- numbers -------------------------------------------------------------------
def parse_price(src: LazadaRaw, variants: list[Variant]) -> Price:
    sale = [v.price for v in variants if v.price]
    before = [v.price_before_discount for v in variants if v.price_before_discount]
    card = _d(src.candidate.get("basic"))
    price_min = min(sale) if sale else to_int(first(card.get("price"), card.get("priceShow")))
    price_max = max(sale) if sale else price_min
    before_min = min(before) if before else to_int(card.get("originalPrice"))
    before_max = max(before) if before else before_min
    discount = None
    if before_min and price_min and before_min > price_min:
        discount = round(100 * (1 - price_min / before_min))
    elif card.get("discount"):
        discount = to_int(card.get("discount"))
    return Price(min=price_min, max=price_max, before_min=before_min, before_max=before_max, discount_pct=discount)


def parse_sales(src: LazadaRaw) -> Sales:
    total = first(sold_count(dig(src.fields, "product", "soldCount")), sold_count(src.tracking.get("pdt_sold")),
                  sold_count(src.tracking.get("pdt_sold_count")), sold_count(dig(src.fields, "review", "ratings", "soldCount")),
                  sold_count(_d(src.candidate.get("basic")).get("itemSoldCntShow")))
    return Sales(total=total, listing_sold=sold_count(_d(src.candidate.get("basic")).get("itemSoldCntShow")))


def parse_stock(variants: list[Variant]) -> Stock:
    counted = [v for v in variants if v.stock is not None]
    total = sum(v.stock for v in counted) if counted and len(counted) == len(variants) else None
    in_stock = sum(1 for v in variants if v.stock_status == "Còn hàng")
    state = (f"{'Còn hàng' if in_stock else 'Hết hàng'} ({in_stock}/{len(variants)} SKU còn hàng)"
             if variants and any(v.stock_status for v in variants) else None)
    value = total if total is not None else (sum(v.stock for v in counted) if counted else None)
    return Stock(total=total, value=value, state=state)


def parse_rating(src: LazadaRaw) -> Rating:
    r = _d(dig(src.fields, "review", "ratings"))
    card = _d(src.candidate.get("basic"))
    scores = _l(r.get("scores"))            # Lazada lists 5 -> 1 or 1 -> 5; a dict form also exists
    by_star: dict[int, int] = {}
    if isinstance(r.get("scores"), dict):
        by_star = {int(k): to_int(v) or 0 for k, v in r["scores"].items() if str(k).isdigit()}
    elif len(scores) == 5:
        first_is_five = to_int(_d(scores[0]).get("star") if isinstance(scores[0], dict) else None) == 5
        vals = [to_int(_d(s).get("count") if isinstance(s, dict) else s) or 0 for s in scores]
        stars = [5, 4, 3, 2, 1] if first_is_five or not isinstance(scores[0], dict) else [1, 2, 3, 4, 5]
        by_star = dict(zip(stars, vals, strict=True))
    return Rating(
        star=to_float(first(r.get("average"), r.get("averageScore"), card.get("ratingScore"))),
        total=to_int(first(r.get("rateCount"), r.get("count"), card.get("review"))),
        five=by_star.get(5), four=by_star.get(4), three=by_star.get(3), two=by_star.get(2), one=by_star.get(1),
    )


def parse_shop(src: LazadaRaw) -> Shop:
    seller = _d(src.fields.get("seller"))
    info = _d(src.fields.get("sellerInfo"))
    card = _d(src.candidate.get("basic"))
    url = first(seller.get("url"), seller.get("shopUrl"))
    positive = to_int(first(info.get("positiveRating"), info.get("positiveSellerRatings"), info.get("sellerRating")))
    return Shop(
        id=first(seller.get("sellerId"), seller.get("id"), src.candidate.get("seller_id") or None),
        name=first(seller.get("name"), card.get("sellerName")),
        url=_abs(url) if url else None,
        location=first(card.get("location"), info.get("location")),
        response_rate=to_int(first(info.get("chatResponseRate"), info.get("responseRate"))),
        rating=(positive / 20) if positive is not None and positive <= 100 else None,   # % positive -> /5
        ship_48h=to_int(first(info.get("shipOnTime"), info.get("shipOnTimeRate"))),
        is_mall=bool(first(seller.get("isLazMall"), seller.get("lazMall"), card.get("lazMall"), False)) or None,
    )


def promotions(src: LazadaRaw, discount: int | None) -> str | None:
    parts: list[str] = []
    if discount:
        parts.append(f"Giảm {discount}%")
    for v in _l(src.fields.get("voucher")) + _l(dig(src.fields, "promotion", "vouchers")):
        text = first(_d(v).get("title"), _d(v).get("text"), _d(v).get("desc"))
        if text:
            parts.append(re.sub(r"\s+", " ", str(text)))
    for t in _l(_d(src.candidate.get("basic")).get("icons")) + _l(_d(src.candidate.get("basic")).get("tags")):
        text = first(_d(t).get("text"), _d(t).get("title"), t if isinstance(t, str) else None)
        if text and text not in parts:
            parts.append(str(text))
    return "; ".join(parts) or None


def product_url(src: LazadaRaw) -> str:
    url = first(_d(src.candidate.get("basic")).get("itemUrl"), src.product.get("link"))
    if url:
        url = _abs(url)
        return url if url.startswith("http") else BASE + url
    return PRODUCT_URL.format(item_id=src.item_id, sku_id=src.sku_id)


# ---- assembly ---------------------------------------------------------------------
def parse_product(raw: dict, profile: DomainProfile | None = None) -> Product:
    src = LazadaRaw.from_raw(raw)
    name = title(src)
    desc = description(src)
    attrs = attributes(src)
    variants, tiers = parse_variants(src)
    variant_names = [v.name for v in variants if v.name]
    for tier in tiers:
        variant_names.extend(o for o in tier["options"] if o)
    price = parse_price(src, variants)
    return Product(
        platform="lazada",
        item_id=src.item_id,
        url=product_url(src),
        title=name,
        product_type=classify(name, profile).product_type or None,
        brand=brand(src, attrs),
        category=category(src),
        description=desc or None,
        attributes_raw=attributes_text(attrs) or None,
        promotions=promotions(src, price.discount_pct),
        images=images(src),
        tier_names=" / ".join(t["name"] for t in tiers if t["name"]) or None,
        variants=variants,
        price=price,
        sales=parse_sales(src),
        stock=parse_stock(variants),
        rating=parse_rating(src),
        specs=extract_specs(attrs, variant_names, tiers, name, desc, profile),
        shop=parse_shop(src),
        search_rank=src.candidate.get("search_rank"),
        search_page=src.candidate.get("page"),
        is_ad=src.candidate.get("is_ad"),
        scraped_at=raw.get("scraped_at"),
    )
