"""Lazada VN crawl: search pages sorted by 'Bán chạy' (discovery) then product pages.

Both are fetched from inside one real browser tab (see fetch.py). Raw files:

    data/raw/lazada/<run>/search/page_00.json   {"url", "page", "scraped_at", "payload": <ajax JSON>}
    data/raw/lazada/<run>/items/<seller>_<item>.json
        {"candidate", "module_data": window.__moduleData__, "tracking_data": window.pdpTrackingData,
         "title", "scraped_at"}
"""
from __future__ import annotations

import logging
import math
import random
import time
from urllib.parse import quote

from ecommerce.contracts.guard import SchemaGuard
from ecommerce.domain.candidate import LazadaCandidate
from ecommerce.ingestion.browser import BrowserClosed, context_closed, human_pause, save_debug
from ecommerce.ingestion.raw_store import RunStore, utc_now_iso, write_json
from ecommerce.platforms.lazada.extract.fetch import Fetcher, LazadaWall, PageMissing
from ecommerce.platforms.lazada.parse.common import PRODUCT_PATH, SEARCH_PATH, _d
from ecommerce.platforms.lazada.parse.listing import search_items, select_candidates, total_results
from ecommerce.settings import AppConfig, debug_dir

log = logging.getLogger(__name__)


def candidate_goal(cfg: AppConfig) -> int:
    return math.ceil(cfg.lazada.target * (1 + cfg.lazada.buffer_ratio))


def _pause(fetcher: Fetcher, lo: float, hi: float, why: str = "") -> None:
    seconds = random.uniform(lo, hi)
    if why:
        log.info("Pausing %.0fs %s", seconds, why)
    try:
        fetcher.page.wait_for_timeout(int(seconds * 1000))
    except Exception:
        time.sleep(seconds)


def search_path(keyword: str, sort_by: str, page_no: int) -> str:
    return SEARCH_PATH.format(kw=quote(keyword), sort=sort_by, page=page_no + 1)


def crawl_listing(fetcher: Fetcher, store: RunStore, cfg: AppConfig) -> list[LazadaCandidate]:
    """Fetch search pages (skipping ones already on disk) and save candidates."""
    lz = cfg.lazada
    keyword, sort_by, goal = cfg.keyword, lz.sort_by, candidate_goal(cfg)
    guard = SchemaGuard("lazada", "search", limit=min(cfg.contracts.guard_streak, 1))
    for page_no in range(lz.max_pages):
        pages = [(n, doc["payload"]) for n, doc in store.iter_search_pages()]
        kept, _ = select_candidates(pages, goal, lz.include_ads, cfg.domain)
        if len(kept) >= goal:
            break
        if store.search_path(page_no).exists():
            continue
        if store.search_end_path.exists():
            break
        if page_no > 0:
            _pause(fetcher, lz.pacing.delay_min_s, lz.pacing.delay_max_s, "before the next search page")
        path = search_path(keyword, sort_by, page_no)
        log.info("Search page %d: %s", page_no + 1, path)
        data = fetcher.get(path, want_json=True)
        doc = {"url": path, "page": page_no, "scraped_at": utc_now_iso(), "payload": data.json}
        write_json(store.search_path(page_no), doc)
        items = search_items(data.json)
        log.info("Page %d: %d products (total reported: %s)", page_no + 1, len(items), total_results(data.json))
        if page_no == 0 or items:
            guard.observe(doc, f"page {page_no + 1}")
            if guard.tripped:
                save_debug(fetcher.page, debug_dir(), f"lazada_search_p{page_no:02d}")
                human_pause(guard.message())
                guard.reset()
        if not items:
            log.info("Lazada reports no more results.")
            write_json(store.search_end_path, {"after_page": page_no})
            break

    pages = [(n, doc["payload"]) for n, doc in store.iter_search_pages()]
    kept, excluded = select_candidates(pages, goal, lz.include_ads, cfg.domain)
    write_json(store.candidates_path, {
        "keyword": keyword, "sort_by": sort_by, "goal": goal, "domain": cfg.domain.name if cfg.domain else None,
        "kept": [c.dump() for c in kept], "excluded": [c.dump() for c in excluded], "built_at": utc_now_iso(),
    })
    log.info("Candidates: %d kept, %d excluded (goal %d)", len(kept), len(excluded), goal)
    if len(kept) < goal:
        log.warning("Not enough candidates: raise max_pages in configs/platforms/lazada/config.yaml")
    return kept


def _product_path(cand: LazadaCandidate) -> str:
    url = _d(cand.basic).get("itemUrl")
    if url:
        url = "https:" + url if str(url).startswith("//") else str(url)
        return url.split("?")[0] if url.startswith("http") else url
    return PRODUCT_PATH.format(item_id=cand.item_id, sku_id=cand.sku_id)


def crawl_products(fetcher: Fetcher, store: RunStore, cfg: AppConfig,
                   candidates: list[LazadaCandidate | dict], limit: int | None = None) -> None:
    pacing = cfg.lazada.pacing
    candidates = [LazadaCandidate.coerce(c) for c in candidates]
    todo = [c for c in candidates if not store.has_item(c.seller_id or "0", c.item_id)]
    if limit is not None:
        todo = todo[:max(0, limit - (len(candidates) - len(todo)))]
    log.info("Product pages: %d already saved, %d to fetch", len(candidates) - len(todo), len(todo))
    guard = SchemaGuard("lazada", "item", limit=cfg.contracts.guard_streak)
    for n, cand in enumerate(todo, start=1):
        key = cand.key
        attempt = 0
        while attempt < pacing.max_attempts:
            attempt += 1
            try:
                data = fetcher.get(_product_path(cand))
                raw = {"candidate": cand.dump(), "module_data": data.module, "tracking_data": data.tracking,
                       "title": data.title, "scraped_at": utc_now_iso()}
                write_json(store.item_path(cand.seller_id or "0", cand.item_id), raw)
                store.clear_failure(key)
                guard.observe(raw, key)
                log.info("[%d/%d] rank %s - %s", n, len(todo), cand.search_rank, cand.name[:70])
                break
            except PageMissing as exc:
                store.record_failure(key, str(exc))
                log.warning("[%d/%d] Failed %s: %s", n, len(todo), key, exc)
                break
            except LazadaWall:
                raise
            except Exception as exc:
                if context_closed(fetcher.context):
                    raise BrowserClosed() from exc
                log.warning("[%d/%d] Error on %s (attempt %d): %s", n, len(todo), key, attempt, exc)
                if attempt >= pacing.max_attempts:
                    store.record_failure(key, f"{type(exc).__name__}: {exc}"[:300])
                _pause(fetcher, 5, 10)
        if guard.tripped:                   # saved but unreadable: Lazada changed its JSON
            save_debug(fetcher.page, debug_dir(), f"lazada_pdp_{cand.item_id}")
            human_pause(guard.message())
            guard.reset()
        if pacing.long_break_every and n % pacing.long_break_every == 0 and n < len(todo):
            _pause(fetcher, pacing.long_break_min_s, pacing.long_break_max_s, f"after {n} products")
        elif n < len(todo):
            _pause(fetcher, pacing.delay_min_s, pacing.delay_max_s)


def crawl(context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
    fetcher = Fetcher(context, timeout_ms=cfg.timeouts.page_load_ms)
    fetcher.open(search_path(cfg.keyword, cfg.lazada.sort_by, 0).replace("&ajax=true", ""))
    candidates = crawl_listing(fetcher, store, cfg)
    crawl_products(fetcher, store, cfg, candidates, limit=limit)
