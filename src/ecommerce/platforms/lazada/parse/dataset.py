"""Raw Lazada run -> Dataset: parse every product, keep the ones the CURRENT
domain filter keeps, rank them by Lazada's 'Bán chạy' order (search rank)."""
from __future__ import annotations

import logging

from ecommerce.domain.candidate import LazadaCandidate
from ecommerce.domain.dataset import Dataset, Excluded
from ecommerce.domain.product import Product
from ecommerce.domain.profile import DomainProfile
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.lazada.parse.common import BASE, PRODUCT_URL, _d, is_valid_product
from ecommerce.platforms.lazada.parse.product import parse_product
from ecommerce.settings import AppConfig
from ecommerce.transformation.filters import classify

log = logging.getLogger(__name__)


def load_products(store: RunStore, profile: DomainProfile | None = None) -> tuple[list[Product], list[str]]:
    products, broken = [], []
    for raw in store.iter_items():
        cand = raw.get("candidate") or {}
        key = f"{cand.get('seller_id') or '0'}_{cand.get('item_id')}"
        if not is_valid_product(raw):
            broken.append(key)
            continue
        try:
            products.append(parse_product(raw, profile))
        except Exception as exc:        # one odd payload must not sink the file
            log.exception("Could not parse %s: %s", key, exc)
            broken.append(key)
    return products, broken


def restrict_to_candidates(products: list[Product], kept: list[LazadaCandidate] | None,
                           profile: DomainProfile | None = None) -> list[Product]:
    if not kept:
        return products
    current = {c.item_id: c for c in kept}
    out = []
    for p in products:
        cand = current.get(str(p.item_id))
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


def _excluded_url(c: LazadaCandidate) -> str:
    url = _d(c.basic).get("itemUrl")
    if url:
        url = "https:" + url if url.startswith("//") else url
        return url if url.startswith("http") else BASE + url
    return PRODUCT_URL.format(item_id=c.item_id, sku_id=c.sku_id)


def build_dataset(store: RunStore, cfg: AppConfig) -> Dataset:
    profile = cfg.domain
    products, broken = load_products(store, profile)
    cands = read_json(store.candidates_path) if store.candidates_path.exists() else {}
    kept = [LazadaCandidate.coerce(c) for c in cands.get("kept", [])]
    parsed = len(products)
    top = rank(restrict_to_candidates(products, kept, profile), cfg.lazada.target)
    log.info("Parsed %d products, keeping top %d", parsed, len(top))
    if len(top) < cfg.lazada.target:
        log.warning("Only %d/%d products so far - run `ecommerce resume --platform lazada` to continue",
                    len(top), cfg.lazada.target)

    excluded = [Excluded(rank=c.search_rank, source=c.page + 1, name=c.name, product_type=c.product_type,
                         reason=c.reason, url=_excluded_url(c))
                for c in (LazadaCandidate.coerce(x) for x in cands.get("excluded", []))]
    failures = store.load_failures()
    for key in broken:
        failures.setdefault(key, "file raw không có dữ liệu sản phẩm hợp lệ")
    meta = {
        "Sàn": "Lazada Việt Nam (lazada.vn)",
        "Từ khóa": cands.get("keyword") or store.keyword or (cfg.request.keyword if cfg.request else "?"),
        "Ngành hàng (domain profile)": profile.name if profile else "không dùng",
        "Sắp xếp": "Bán chạy (sort={})".format(cands.get("sort_by", "popularity")),
        "Lọc": (profile.report.filter_description + " (xem sheet 'Bị loại')") if profile
               else "Không lọc theo ngành hàng",
        "Quảng cáo": "Tính vào top" if cfg.lazada.include_ads else "Không tính vào top",
        "Mã lần crawl": store.run_id,
        "Số sản phẩm trong file": len(top),
        "Số sản phẩm crawl được": parsed,
        "Số bị loại ở bước lọc": len(excluded),
        "Số lỗi crawl": len(failures),
        "Không có trên Lazada": "Bán 30 ngày, giá sau voucher cá nhân, ngày mở shop (cột bị bỏ). "
                                "'Đã bán' lấy từ trang sản phẩm, nếu không có thì từ thẻ kết quả tìm kiếm ('Đã bán 1,2k' = xấp xỉ)",
        "Đơn vị tiền": "VND; giá niêm yết sau giảm của shop, chưa trừ voucher",
    }
    return Dataset(platform="lazada", run_id=store.run_id, products=top, excluded=excluded,
                   failures=failures, meta=meta)
