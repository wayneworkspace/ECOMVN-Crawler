"""Step 1: walk the 'Bán chạy' search pages until we have enough candidates."""
from __future__ import annotations

import logging
import math
from urllib.parse import quote

from ecommerce.contracts.guard import SchemaGuard
from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.ingestion.browser import (
    BlockedError,
    BrowserClosed,
    ResponseTap,
    block_kind,
    context_closed,
    human_pause,
    is_closed_error,
    jitter_sleep,
    read_json_body,
    save_debug,
    wall_help,
)
from ecommerce.ingestion.raw_store import RunStore, utc_now_iso, write_json
from ecommerce.platforms.shopee.parse.listing import search_items, select_candidates
from ecommerce.settings import AppConfig, TimeoutSettings, debug_dir

log = logging.getLogger(__name__)

SEARCH_API = "/api/v4/search/search_items"
SEARCH_URL = "https://shopee.vn/search?keyword={kw}&page={page}&sortBy={sort}"
PAGE_SIZE = 60


def candidate_goal(cfg: AppConfig) -> int:
    """target x (1 + buffer): spare candidates for products that fail later."""
    return math.ceil(cfg.shopee.target * (1 + cfg.shopee.buffer_ratio))


class SearchTab:
    """The tab used for search pages; reopened if the person closes it."""

    def __init__(self, context):
        self.context = context
        self.page = None
        self.tap = None

    def get(self):
        if self.page is None or self.page.is_closed():
            if context_closed(self.context):
                raise BrowserClosed()
            self.page = self.context.new_page()
            self.tap = ResponseTap(self.page, (SEARCH_API,))
        return self.page, self.tap

    def close(self):
        if self.page is not None and not self.page.is_closed():
            self.page.close()


def fetch_search_page(tab: SearchTab, keyword: str, page_no: int, sort_by: str,
                      timeouts: TimeoutSettings = TimeoutSettings()) -> dict:
    """Open one search page and return the search_items JSON it loads."""
    url = SEARCH_URL.format(kw=quote(keyword), page=page_no, sort=sort_by)
    expected = f"newest={page_no * PAGE_SIZE}"
    while True:
        page, tap = tab.get()
        try:
            tap.hits.clear()
            log.info("Opening search page %d: %s", page_no + 1, url)
            page.goto(url, wait_until="domcontentloaded", timeout=timeouts.page_load_ms)
            # Only accept the request for THIS page: saved pages are the
            # checkpoint, so a widget's search_items saved by mistake would
            # never be fetched again.
            response = tap.wait_for(SEARCH_API, timeout_ms=timeouts.api_wait_ms,
                                    predicate=lambda u: expected in u)
            if response is None and tap.matching(SEARCH_API):
                # Shopee may rename the paging parameter; take the navigation's
                # own request but leave a trace so the page can be audited.
                response = tap.matching(SEARCH_API)[0]
                log.warning("'%s' not found in the search_items URL, using the first request: %s",
                            expected, response.url[:160])
            if response is None:
                save_debug(page, debug_dir(), f"search_p{page_no:02d}")
                raise RuntimeError(f"Did not capture {SEARCH_API} on page {page_no + 1}")
            payload = read_json_body(response)
            if payload is None:
                # Body gone = the page navigated away right after the API call,
                # almost always to a wall. Give the redirect a moment to land.
                page.wait_for_timeout(1500)
                kind = block_kind(page.url)
                if kind:
                    raise BlockedError(kind, page.url)
                log.warning("Could not read the JSON of page %d, retrying", page_no + 1)
                page.wait_for_timeout(3000)
                continue
            if payload.get("error"):
                save_debug(page, debug_dir(), f"search_p{page_no:02d}")
                human_pause(f"Shopee returned an error on the search page: error={payload.get('error')!r}. "
                            "Check the Chrome tab (captcha? not logged in?).")
                continue
            return {"url": url, "page": page_no, "scraped_at": utc_now_iso(),
                    "request_url": response.url, "payload": payload}
        except BlockedError as exc:
            page.bring_to_front()
            human_pause(wall_help(exc.kind))
        except Exception as exc:
            if not is_closed_error(exc):
                raise
            if context_closed(tab.context):
                raise BrowserClosed() from exc
            log.warning("Search tab was closed, opening a new one.")


def crawl_listing(context, store: RunStore, cfg: AppConfig) -> list[ShopeeCandidate]:
    """Fetch search pages (skipping ones already on disk) and save candidates."""
    keyword = cfg.keyword
    sort_by = cfg.shopee.sort_by
    max_pages = cfg.shopee.max_pages
    include_ads = cfg.shopee.include_ads
    goal = candidate_goal(cfg)

    # one bad search page is enough to stop: every candidate comes from these pages
    guard = SchemaGuard("shopee", "search", limit=min(cfg.contracts.guard_streak, 1))
    tab = SearchTab(context)
    try:
        for page_no in range(max_pages):
            pages = [(n, doc["payload"]) for n, doc in store.iter_search_pages()]
            kept, excluded = select_candidates(pages, goal, include_ads, cfg.domain)
            if len(kept) >= goal:
                break
            if store.search_path(page_no).exists():
                continue
            if store.search_end_path.exists():
                break
            if page_no > 0:
                jitter_sleep(tab.get()[0], 5, 10, "before the next search page")
            doc = fetch_search_page(tab, keyword, page_no, sort_by, cfg.timeouts)
            write_json(store.search_path(page_no), doc)
            n_items = len(search_items(doc["payload"]))
            log.info("Page %d: %d products", page_no + 1, n_items)
            if page_no == 0 or n_items:         # an empty LAST page is just the end of results
                guard.observe(doc, f"page {page_no + 1}")
                if guard.tripped:
                    human_pause(guard.message())
                    guard.reset()
            if n_items == 0 or doc["payload"].get("nomore"):
                log.info("Shopee reports no more results.")
                write_json(store.search_end_path, {"after_page": page_no})
                break
    finally:
        tab.close()

    pages = [(n, doc["payload"]) for n, doc in store.iter_search_pages()]
    kept, excluded = select_candidates(pages, goal, include_ads, cfg.domain)
    write_json(store.candidates_path, {
        "keyword": keyword, "sort_by": sort_by, "goal": goal, "domain": cfg.domain.name if cfg.domain else None,
        "kept": [c.dump() for c in kept], "excluded": [c.dump() for c in excluded],
        "built_at": utc_now_iso(),
    })
    log.info("Candidates: %d kept, %d excluded (goal %d)", len(kept), len(excluded), goal)
    if len(kept) < goal:
        log.warning("Not enough candidates: raise shopee.max_pages in configs/platforms/shopee/config.yaml")
    return kept
