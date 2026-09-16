"""Raw TikTok run -> Dataset: parse, keep what the current filter keeps, rank
by cumulative sold count (the web has no 'sort by sales')."""
from __future__ import annotations

import logging

from ecommerce.domain.candidate import TikTokCandidate
from ecommerce.domain.dataset import Dataset, Excluded
from ecommerce.domain.product import Product
from ecommerce.domain.profile import DomainProfile
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.tiktok.parse.common import PRODUCT_URL, is_valid_product
from ecommerce.platforms.tiktok.parse.product import parse_product
from ecommerce.settings import AppConfig, slugify
from ecommerce.transformation.filters import keep_product

log = logging.getLogger(__name__)


def load_products(store: RunStore, profile: DomainProfile | None = None) -> tuple[list[Product], list[str]]:
    products, broken = [], []
    for raw in store.iter_items():
        cand = raw.get("candidate") or {}
        key = f"{cand.get('seller_id')}_{cand.get('product_id')}"
        if not is_valid_product(raw):
            broken.append(key)
            continue
        try:
            products.append(parse_product(raw, profile))
        except Exception as exc:
            log.exception("Could not parse %s: %s", key, exc)
            broken.append(key)
    return products, broken


def keeps(p: Product, profile: DomainProfile | None) -> bool:
    """The CURRENT domain filter (title must match, product noun kept)."""
    return keep_product(p.title, profile, "tiktok")


def rank(products: list[Product], target: int) -> list[Product]:
    products = sorted(products, key=lambda p: (-(p.sales.total or 0), p.pool_rank or 10**9))
    top = products[:target]
    for i, p in enumerate(top, start=1):
        p.final_rank = i
    return top


def build_dataset(store: RunStore, cfg: AppConfig) -> Dataset:
    profile = cfg.domain
    products, broken = load_products(store, profile)
    cands = read_json(store.candidates_path) if store.candidates_path.exists() else {}
    top = rank([p for p in products if keeps(p, profile)], cfg.tiktok.target)
    log.info("Parsed %d products, taking the top %d", len(products), len(top))
    if len(top) < cfg.tiktok.target:
        log.warning("Only %d/%d products so far - run `ecommerce resume --platform tiktok` to add more",
                    len(top), cfg.tiktok.target)
    excluded = [Excluded(rank=c.pool_rank, source=c.source_slug, name=c.name, product_type=c.product_type,
                         reason=c.reason, url=PRODUCT_URL.format(product_id=c.product_id))
                for c in (TikTokCandidate.coerce(x) for x in cands.get("excluded", []))]
    failures = store.load_failures()
    for key in broken:
        failures.setdefault(key, "file raw không có product_info hợp lệ")
    pages = len(list((store.dir / "search").glob("page_*.json"))) if (store.dir / "search").is_dir() else 0
    keyword = cands.get("keyword") or store.keyword or (cfg.request.keyword if cfg.request else "?")
    meta = {
        "Sàn": "TikTok Shop Việt Nam (shop.tiktok.com/vn)",
        "Từ khóa": keyword,
        "Ngành hàng (domain profile)": profile.name if profile else "không dùng",
        "Cách lấy danh sách": f"Web TikTok Shop VN không có ô tìm kiếm. Tool đi {pages} trang từ khoá "
                              f"(/vn/k/{slugify(keyword)} và các trang 'Related Searches' liên quan), "
                              f"gộp {cands.get('pool', '?')} sản phẩm",
        "Sắp xếp": "Web không có 'Bán chạy' -> xếp theo tổng đã bán trên trang sản phẩm, "
                   "giảm dần",
        "Lọc": (profile.report.filter_description + " (xem sheet 'Bị loại')") if profile
               else "Không lọc theo ngành hàng",
        "Mã lần crawl": store.run_id,
        "Số sản phẩm trong file": len(top),
        "Số trang sản phẩm đã lấy": len(products),
        "Số bị loại ở bước lọc": len(excluded),
        "Số lỗi crawl": len(failures),
        "Đơn vị tiền": "VND; giá niêm yết sau giảm của shop, chưa trừ voucher",
    }
    return Dataset(platform="tiktok", run_id=store.run_id, products=top, excluded=excluded,
                   failures=failures, meta=meta)
