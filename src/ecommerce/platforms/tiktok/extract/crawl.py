"""TikTok Shop VN crawl: keyword pages (discovery) then product pages.

Step 1 - discovery. The VN web storefront has no search box and no "sort by
sales". It does have SEO keyword pages (/vn/k/giu-nhiet, ~55 products each),
and each one links to related keyword pages. The tool walks that graph from a
few seeds (breadth-first, only slugs about drinkware), saving every page, then
merges all products. 40 pages already gave 990 products / 782 drink vessels.

Step 2 - product pages for the best-selling candidates (by the sold count
shown on the keyword pages), with exact per-SKU stock and prices.

Both steps save raw JSON first and skip what is already saved, so the run can
be stopped and resumed at any time.
"""
from __future__ import annotations

import logging
import random
import re
import time

from ecommerce.contracts.guard import SchemaGuard
from ecommerce.domain.candidate import TikTokCandidate
from ecommerce.ingestion.browser import human_pause
from ecommerce.ingestion.raw_store import RunStore, read_json, utc_now_iso, write_json
from ecommerce.platforms.tiktok.extract.fetch import Fetcher, PageMissing, TikTokWall
from ecommerce.platforms.tiktok.parse.common import KEYWORD_PATH, PRODUCT_PATH, component, is_valid_product
from ecommerce.platforms.tiktok.parse.listing import parse_keyword_page, select_candidates
from ecommerce.settings import AppConfig, slugify

log = logging.getLogger(__name__)


def _pause(fetcher: Fetcher, lo: float, hi: float, why: str = "") -> None:
    seconds = random.uniform(lo, hi)
    if why:
        log.info("Pausing %.0fs %s", seconds, why)
    try:
        fetcher.page.wait_for_timeout(int(seconds * 1000))
    except Exception:
        time.sleep(seconds)


def slug_allowed(slug: str, include: str, exclude: str) -> bool:
    return bool(re.search(include, slug)) and not re.search(exclude, slug)


def iter_pages(store: RunStore):
    folder = store.dir / "search"
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("page_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        yield int(path.stem.split("_")[1]), read_json(path)


def discovery_plan(cfg: AppConfig) -> tuple[list[str], str, str]:
    """(seed slugs, include regex, exclude regex) for the keyword-page walk.

    A domain profile can list the slugs worth following. Without one the walk
    starts from the keyword's own slug and only follows pages containing it.
    """
    disc = cfg.domain.discovery.tiktok if cfg.domain else None
    seed = slugify(cfg.keyword)
    seeds = list(disc.seed_slugs) if disc and disc.seed_slugs else [seed]
    include = (disc.slug_include if disc and disc.slug_include else None) or re.escape(seed)
    exclude = (disc.slug_exclude if disc and disc.slug_exclude else None) or r"(?!x)x"   # matches nothing
    return seeds, include, exclude


def crawl_keyword_pages(fetcher: Fetcher, store: RunStore, cfg: AppConfig) -> None:
    tk = cfg.tiktok
    seeds, include, exclude = discovery_plan(cfg)
    max_pages = tk.max_keyword_pages
    lo, hi = tk.pacing.delay_min_s, tk.pacing.delay_max_s

    # Rebuild the walk from what is on disk (resume).
    visited: list[str] = []
    queue: list[str] = list(seeds)
    for _, page in iter_pages(store):
        visited.append(page["slug"])
        queue.extend(s for s in page.get("related") or [] if slug_allowed(s, include, exclude))
    seen = set(visited)
    queue = [s for s in dict.fromkeys(queue) if s not in seen]
    page_no = len(visited)
    if page_no:
        log.info("Resuming: %d keyword pages already saved, %d left in the queue", page_no, len(queue))

    guard = SchemaGuard("tiktok", "search", limit=cfg.contracts.guard_streak)
    while queue and page_no < max_pages:
        slug = queue.pop(0)
        if slug in seen:
            continue
        seen.add(slug)
        path = KEYWORD_PATH.format(slug=slug)
        try:
            data = fetcher.get(path)
        except PageMissing as exc:
            log.info("Skipping page %s: %s", slug, exc)
            continue
        parsed = parse_keyword_page(data.components)
        page_no += 1
        page = {"slug": slug, "path": path, "fetched_at": utc_now_iso(), **parsed}
        write_json(store.dir / "search" / f"page_{page_no:03d}.json", page)
        guard.observe(page, f"/k/{slug}")
        if guard.tripped:
            human_pause(guard.message())
            guard.reset()
        new = [s for s in parsed["related"] if s not in seen and slug_allowed(s, include, exclude)]
        queue.extend(s for s in new if s not in queue)
        log.info("[%d/%d] /k/%s: %d products, +%d related pages (queue %d)",
                 page_no, max_pages, slug, len(parsed["products"]), len(new), len(queue))
        _pause(fetcher, lo, hi)
    write_json(store.dir / "search" / "_end.json",
               {"pages": page_no, "queue_left": len(queue), "at": utc_now_iso()})


def build_candidates(store: RunStore, cfg: AppConfig) -> dict:
    keep = round(cfg.tiktok.target * (1 + cfg.tiktok.buffer_ratio))
    result = select_candidates(iter_pages(store), keep, cfg.domain)
    result.update(keyword=cfg.keyword, domain=cfg.domain.name if cfg.domain else None,
                  ranked_by="số đã bán (trang sản phẩm)", at=utc_now_iso())
    write_json(store.candidates_path, {**result, "kept": [c.dump() for c in result["kept"]],
                                       "excluded": [c.dump() for c in result["excluded"]]})
    log.info("Merged %d products from the keyword pages: %d in the domain, taking the %d best sellers "
             "for the product pages", result["pool"], result["kept_total"], len(result["kept"]))
    return result


def crawl_products(fetcher: Fetcher, store: RunStore, cfg: AppConfig,
                   candidates: list[TikTokCandidate | dict], limit: int | None = None) -> None:
    pacing = cfg.tiktok.pacing
    lo, hi = pacing.delay_min_s, pacing.delay_max_s
    every = pacing.long_break_every
    blo, bhi = pacing.long_break_min_s, pacing.long_break_max_s
    candidates = [TikTokCandidate.coerce(c) for c in candidates]
    todo = [c for c in candidates if not store.has_item(c.seller_id, c.product_id)]
    if limit is not None:
        todo = todo[:max(0, limit - (len(candidates) - len(todo)))]
    log.info("Product pages: %d already saved, %d to fetch", len(candidates) - len(todo), len(todo))
    guard = SchemaGuard("tiktok", "item", limit=cfg.contracts.guard_streak)
    for n, cand in enumerate(todo, start=1):
        key = cand.key
        try:
            data = fetcher.get(PRODUCT_PATH.format(product_id=cand.product_id))
            info = component(data.components, "product_info").get("component_data")
            raw = {"candidate": cand.dump(), "product_info": info, "route": data.route, "scraped_at": utc_now_iso()}
            if not info or not is_valid_product(raw):
                raise PageMissing(f"trang không có product_info hợp lệ "
                                  f"(error_code={(info or {}).get('error_code')})")
            write_json(store.item_path(cand.seller_id, cand.product_id), raw)
            store.clear_failure(key)
            guard.observe(raw, key)
            log.info("[%d/%d] %s | sold %s", n, len(todo), cand.name[:60],
                     raw["product_info"]["product_info"]["product_model"].get("sold_count"))
        except PageMissing as exc:
            store.record_failure(key, str(exc))
            log.warning("[%d/%d] Failed %s: %s", n, len(todo), key, exc)
        except TikTokWall:
            raise
        if guard.tripped:                   # saved but unreadable: TikTok changed its JSON
            human_pause(guard.message())
            guard.reset()
        if n % every == 0 and n < len(todo):
            _pause(fetcher, blo, bhi, f"after {n} products")
        else:
            _pause(fetcher, lo, hi)


def crawl(context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
    fetcher = Fetcher(context, timeout_ms=cfg.timeouts.page_load_ms)
    fetcher.open("/vn/k/" + discovery_plan(cfg)[0][0])
    crawl_keyword_pages(fetcher, store, cfg)
    cands = build_candidates(store, cfg)
    crawl_products(fetcher, store, cfg, cands["kept"], limit=limit)
