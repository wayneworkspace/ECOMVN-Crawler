"""Raw Shopee run -> Dataset for the report: parse every product, keep the ones
the CURRENT filter keeps, rank them by Shopee's 'Bán chạy' order."""
from __future__ import annotations

import logging

from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.domain.dataset import Dataset, Excluded
from ecommerce.domain.product import Product
from ecommerce.domain.profile import DomainProfile
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.shopee.parse.common import PRODUCT_URL, pdp_item
from ecommerce.platforms.shopee.parse.product import parse_product
from ecommerce.settings import AppConfig
from ecommerce.transformation.filters import classify

log = logging.getLogger(__name__)


def load_products(store: RunStore, profile: DomainProfile | None = None) -> tuple[list[Product], list[str]]:
    products, broken = [], []
    for raw in store.iter_items():
        cand = raw.get("candidate") or {}
        key = f"{cand.get('shopid')}_{cand.get('itemid')}"
        if pdp_item(raw.get("pdp")) is None:
            broken.append(key)
            continue
        try:
            products.append(parse_product(raw, profile))
        except Exception as exc:        # one odd payload must not sink the file
            log.exception("Could not parse %s: %s", key, exc)
            broken.append(key)
    return products, broken


def restrict_to_candidates(products: list[Product], kept: list[ShopeeCandidate] | None,
                           profile: DomainProfile | None = None) -> list[Product]:
    """Keep only products the CURRENT filter keeps, with the current rank.

    A raw file from an earlier crawl may belong to a product the (since
    improved) filter now drops, and its stored rank may be stale.
    """
    if not kept:
        return products
    current = {(c.shopid, c.itemid): c for c in kept}
    out = []
    for p in products:
        cand = current.get((p.shop.id, p.item_id))
        if cand is not None and (not p.title or classify(p.title, profile).keep):
            p.search_rank = cand.search_rank
            p.product_type = cand.product_type or p.product_type
            out.append(p)
    return out


def rank(products: list[Product], target: int) -> list[Product]:
    products = sorted(products, key=lambda p: (p.search_rank is None, p.search_rank or 0))
    top = products[:target]
    for i, p in enumerate(top, start=1):
        p.final_rank = i
    return top


def build_dataset(store: RunStore, cfg: AppConfig) -> Dataset:
    profile = cfg.domain
    products, broken = load_products(store, profile)
    cands = read_json(store.candidates_path) if store.candidates_path.exists() else {}
    kept = [ShopeeCandidate.coerce(c) for c in cands.get("kept", [])]
    parsed = len(products)
    top = rank(restrict_to_candidates(products, kept, profile), cfg.shopee.target)
    log.info("Parsed %d products, taking the top %d", parsed, len(top))
    if len(top) < cfg.shopee.target:
        log.warning("Only %d/%d products so far - run `ecommerce resume --platform shopee` to add more",
                    len(top), cfg.shopee.target)

    excluded = [Excluded(rank=c.search_rank, source=c.page + 1, name=c.name, product_type=c.product_type,
                         reason=c.reason, url=PRODUCT_URL.format(shopid=c.shopid, itemid=c.itemid))
                for c in (ShopeeCandidate.coerce(x) for x in cands.get("excluded", []))]
    failures = store.load_failures()
    for key in broken:
        failures.setdefault(key, "file raw không có pdp hợp lệ")
    meta = {
        "Sàn": "Shopee Việt Nam (shopee.vn)",
        "Từ khóa": cands.get("keyword") or store.keyword or (cfg.request.keyword if cfg.request else "?"),
        "Ngành hàng (domain profile)": profile.name if profile else "không dùng",
        "Sắp xếp": "Bán chạy (sortBy={})".format(cands.get("sort_by", "sales")),
        "Lọc": (profile.report.filter_description + " (xem sheet 'Bị loại')") if profile
               else "Không lọc theo ngành hàng",
        "Quảng cáo": "Tính vào top" if cfg.shopee.include_ads else "Không tính vào top",
        "Mã lần crawl": store.run_id,
        "Số sản phẩm trong file": len(top),
        "Số sản phẩm crawl được": parsed,
        "Số bị loại ở bước lọc": len(excluded),
        "Số lỗi crawl": len(failures),
        "Đơn vị tiền": "VND; giá là giá niêm yết sau giảm, chưa trừ voucher cá nhân",
    }
    return Dataset(platform="shopee", run_id=store.run_id, products=top, excluded=excluded,
                   failures=failures, meta=meta)
