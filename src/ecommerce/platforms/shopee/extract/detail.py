"""Step 2: open each candidate's product page and keep every JSON it loads.

Per product we save one raw file holding:
    pdp      -- api/v4/pdp/get_pc (required; without it the product failed)
    ratings  -- every api/v2/item/get_ratings page we triggered (best effort)
    shop     -- shop endpoints the page happened to load (best effort)
    candidate -- the search-result row (rank, 30-day sold, ad flag)

Only `pdp` is mandatory. Reviews and shop blocks are lazy-loaded when scrolled
into view; if they do not show up we still keep the product rather than burn
retries (and account reputation) on a secondary field.
"""
from __future__ import annotations

import contextlib
import logging
import random
import time

from ecommerce.contracts.guard import SchemaGuard
from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.ingestion.browser import (
    BlockedError,
    BrowserClosed,
    ResponseTap,
    block_kind,
    context_closed,
    human_pause,
    human_scroll,
    is_closed_error,
    jitter_sleep,
    read_json_body,
    save_debug,
    wall_help,
)
from ecommerce.ingestion.raw_store import RunStore, read_json, utc_now_iso, write_json
from ecommerce.platforms.shopee.extract.sku_stock import SELECT_API, collect_sku_stock
from ecommerce.platforms.shopee.parse.common import PRODUCT_URL, pdp_item
from ecommerce.settings import AppConfig, TimeoutSettings, debug_dir

log = logging.getLogger(__name__)

PDP_API = "/api/v4/pdp/get_pc"
RATINGS_API = "/item/get_ratings"
SHOP_APIS = ("/shop/get_shop_base", "/shop/get_shop_detail", "/product/get_shop_info",
             "/shop/get_shop_tab", "/pdp/get_shop")


class ProductFailed(Exception):
    pass


def _collect_json(tap: ResponseTap, fragment: str) -> list[dict]:
    out = []
    for response in tap.matching(fragment):
        body = read_json_body(response)
        if body is not None:
            out.append(body)
    return out


def _load_side_blocks(page, tap: ResponseTap) -> None:
    """Scroll to the ratings block so Shopee loads the lazy parts: star summary and shop block.

    Scroll only, never page through the reviews: the tool uses only the summary
    (reviews with photos / with text), not the individual reviews -- decisions.md #6.
    """
    for _ in range(14):
        if tap.matching(RATINGS_API):
            return
        human_scroll(page, steps=1, step_px=1000)


MAX_WALL_ROUNDS = 5           # captcha / login walls solved per product before giving up
SOFT_BLOCK_STREAK = 3         # consecutive failures that smell like a silent block


class TrafficBlocked(Exception):
    """Shopee's /verify/traffic wall: a rate limit, not a puzzle a person can
    solve (the page just spins). The cure is to stop sending requests for a
    while, so the crawler cools down on its own instead of waiting for Enter."""


# get_pc {"error": 90309999} = anti-bot risk control (real run 11/09: first product
# of a fresh run, followed by a captcha). Treated like the traffic wall: cool down.
RISK_CONTROL_ERRORS = {90309999}


class SoftBlocked(ProductFailed):
    """HTTP 200 with {"error": <code>, "data": null}: Shopee refusing quietly."""


def _open_product(page, tap: ResponseTap, url: str, itemid, timeouts: TimeoutSettings) -> object:
    """Navigate and return the get_pc response; solve walls IN THIS TAB.

    The wall must be handled while the tab that shows it is still open --
    pausing after the tab is closed leaves the person staring at nothing.
    """
    for _ in range(MAX_WALL_ROUNDS):
        tap.hits.clear()
        page.goto(url, wait_until="domcontentloaded", timeout=timeouts.page_load_ms)
        try:
            return tap.wait_for(
                PDP_API, timeout_ms=timeouts.api_wait_ms,
                # match on item_id too: other widgets on the page call get_pc-like
                # APIs for OTHER products (recommendations, "shop's other items").
                predicate=lambda u: f"item_id={itemid}" in u or f"itemid={itemid}" in u,
            )
        except BlockedError as exc:
            if exc.kind == "traffic_wall":
                # sometimes the spinner turns into a real captcha; give it a moment
                for _ in range(20):
                    page.wait_for_timeout(1000)
                    if block_kind(page.url) != "traffic_wall":
                        break
                kind = block_kind(page.url)
                if kind == "traffic_wall":
                    raise TrafficBlocked(page.url) from exc
                if kind is None:
                    continue                    # the wall cleared itself: reload the product
                exc = BlockedError(kind, page.url)
            page.bring_to_front()
            human_pause(wall_help(exc.kind))
    raise ProductFailed(f"vẫn bị chặn sau {MAX_WALL_ROUNDS} lần giải captcha")


def fetch_product(context, candidate: ShopeeCandidate | dict,
                  sku_stock: bool = False, sku_max_clicks: int = 80,
                  timeouts: TimeoutSettings = TimeoutSettings()) -> dict:
    candidate = ShopeeCandidate.coerce(candidate)
    itemid, shopid = candidate.itemid, candidate.shopid
    url = PRODUCT_URL.format(shopid=shopid, itemid=itemid)
    page = context.new_page()
    try:
        tap = ResponseTap(page, (PDP_API, RATINGS_API, SELECT_API, *SHOP_APIS))
        response = _open_product(page, tap, url, itemid, timeouts)
        if response is None:
            save_debug(page, debug_dir(), f"pdp_{shopid}_{itemid}")
            raise ProductFailed(f"không bắt được pdp/get_pc trong {timeouts.api_wait_ms // 1000}s")
        payload = read_json_body(response)
        item = pdp_item(payload)
        if item is None:
            save_debug(page, debug_dir(), f"pdp_{shopid}_{itemid}")
            error = payload.get("error") if isinstance(payload, dict) else None
            if error in RISK_CONTROL_ERRORS:
                # account/IP flagged: retrying at once only raises the score
                raise TrafficBlocked(f"get_pc error={error} (Shopee blocked us as a suspected bot)")
            if error:
                raise SoftBlocked(f"get_pc trả lỗi error={error!r} "
                                  f"msg={payload.get('error_msg')!r}")
            raise ProductFailed("get_pc không có khối item")
        got_id = item.get("item_id") or item.get("itemid")
        if got_id is not None and str(got_id) != str(itemid):
            raise ProductFailed(f"bắt nhầm response của item {got_id}")

        stock = None
        if sku_stock:
            # before scrolling away: the variation buttons sit next to the price
            page.wait_for_timeout(1200)
            stock = collect_sku_stock(page, item, max_clicks=sku_max_clicks, tap=tap,
                                      settle_ms=timeouts.sku_settle_ms, timeouts=timeouts)
            known = sum(1 for v in stock["by_model"].values() if v.get("available") is not None)
            from_api = sum(1 for v in stock["by_model"].values() if v.get("source") == "api")
            log.info("   SKU stock: %d/%d SKUs with a number (%d from API), %d clicks%s", known,
                     len(item.get("models") or []), from_api, stock["clicks"],
                     "" if stock["complete"] else " (incomplete: " + "; ".join(stock["notes"][:2]) + ")")

        _load_side_blocks(page, tap)

        return {
            "sku_stock": stock,
            "platform": "shopee",
            "url": url,
            "scraped_at": utc_now_iso(),
            "candidate": candidate.dump(),
            "pdp": payload,
            "ratings": _collect_json(tap, RATINGS_API),
            "shop": [body for frag in SHOP_APIS for body in _collect_json(tap, frag)],
        }
    finally:
        with contextlib.suppress(Exception):
            page.close()


def needs_crawl(store: RunStore, candidate: ShopeeCandidate | dict, sku_stock: bool) -> bool:
    """Not crawled yet -- or crawled before per-SKU stock was switched on."""
    c = ShopeeCandidate.coerce(candidate)
    if not store.has_item(c.shopid, c.itemid):
        return True
    if not sku_stock:
        return False
    try:
        raw = read_json(store.item_path(c.shopid, c.itemid))
    except Exception:
        return True
    # attempted once is enough: a 90-SKU listing that hit the click cap must
    # not be re-opened on every run
    return raw.get("sku_stock") is None


def crawl_details(context, store: RunStore, cfg: AppConfig, candidates: list[ShopeeCandidate | dict],
                  limit: int | None = None) -> None:
    pacing = cfg.shopee.pacing
    sku_stock = cfg.shopee.sku_stock
    sku_max_clicks = cfg.shopee.sku_stock_max_clicks
    max_attempts = pacing.max_attempts
    candidates = [ShopeeCandidate.coerce(c) for c in candidates]
    todo = [c for c in candidates if needs_crawl(store, c, sku_stock)]
    log.info("Details: %d already saved, %d to crawl", len(candidates) - len(todo), len(todo))
    if limit is not None:
        todo = todo[:limit]

    def pause(lo: float, hi: float, reason: str = "") -> None:
        """Wait between products on any open tab; survive the tab going away.

        Nothing is being captured while we wait, so if no tab is usable a
        plain sleep is fine (the event-dispatch caveat only matters while
        waiting for a response)."""
        if context_closed(context):
            raise BrowserClosed()
        open_pages = [p for p in context.pages if not p.is_closed()]
        try:
            if not open_pages:
                raise RuntimeError("no open tab")
            jitter_sleep(open_pages[0], lo, hi, reason)
        except Exception as exc:
            if not is_closed_error(exc):
                raise
            if context_closed(context):
                raise BrowserClosed() from exc
            time.sleep(random.uniform(lo, hi))
    streak = 0            # consecutive failed products
    guard = SchemaGuard("shopee", "item", limit=cfg.contracts.guard_streak)   # consecutive unreadable products
    cooldowns = 0         # traffic walls since the last success
    max_cooldowns = pacing.max_block_cooldowns

    def cooldown(round_no: int) -> None:
        minutes = pacing.block_cooldown_min * round_no   # 60, 120, 180 min
        until = time.strftime("%H:%M", time.localtime(time.time() + minutes * 60))
        log.warning("Shopee blocked us (traffic / suspected bot). Cooling down %.0f min (until about %s), "
                    "then retrying. Safe to leave running; Ctrl+C to stop for good.", minutes, until)
        remaining = minutes * 60
        while remaining > 0:                    # count down in chunks (not wall clock:
            chunk = min(300, remaining)         # keeps it testable and sleep-proof)
            time.sleep(chunk)
            remaining -= chunk
            if remaining > 0:
                log.info("   ...%.0f min left", remaining / 60)
    for n, candidate in enumerate(todo, start=1):
        key = candidate.key
        if n > 1:
            if pacing.long_break_every and (n - 1) % pacing.long_break_every == 0:
                pause(pacing.long_break_min_s, pacing.long_break_max_s, "(long break)")
            if pacing.cooldown_every and (n - 1) % pacing.cooldown_every == 0:
                # proactive: Shopee's traffic wall showed up after ~25 products
                # in ~15 min, so pause well before that
                seconds = random.uniform(pacing.cooldown_min_s, pacing.cooldown_max_s)
                log.info("Pausing %.0f min after %d products to avoid the traffic wall", seconds / 60, n - 1)
                time.sleep(seconds)
            else:
                pause(pacing.delay_min_s, pacing.delay_max_s)
        log.info("[%d/%d] rank %s - %s", n, len(todo), candidate.search_rank, candidate.name[:70])
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                raw = fetch_product(context, candidate, sku_stock, sku_max_clicks,
                                    timeouts=cfg.timeouts)
                write_json(store.item_path(candidate.shopid, candidate.itemid), raw)
                store.clear_failure(key)
                guard.observe(raw, key)
                streak = 0
                cooldowns = 0
                log.info("   ok: %d ratings pages, %d shop blocks",
                         len(raw["ratings"]), len(raw["shop"]))
                break
            except TrafficBlocked:
                cooldowns += 1
                if cooldowns > max_cooldowns:
                    log.error("Shopee still blocks traffic after %d cooldowns. Stopping - run again in a few "
                              "hours (the tool resumes from this product).", max_cooldowns)
                    return
                attempt -= 1                    # not this product's fault: retry it after the cooldown
                cooldown(cooldowns)
            except Exception as exc:
                if is_closed_error(exc) and context_closed(context):
                    raise BrowserClosed() from exc
                log.warning("   attempt %d/%d failed: %s", attempt, max_attempts, exc)
                if attempt == max_attempts:
                    store.record_failure(key, f"{type(exc).__name__}: {exc}")
                    streak += 1
                else:
                    pause(8, 15, "before retrying")
        # Circuit breaker: a silent block fails EVERY product the same way.
        # Carrying on would burn the whole list and the account's reputation.
        if streak >= SOFT_BLOCK_STREAK:
            human_pause(f"{streak} products failed in a row - most likely a silent block by Shopee. "
                        "Open shopee.vn in the Chrome window and check for a captcha / warning. "
                        "If blocked: Ctrl+C, wait a few hours and run again (the tool resumes).")
            streak = 0
        # Saved but unreadable: Shopee changed its JSON (see contracts/).
        if guard.tripped:
            human_pause(guard.message())
            guard.reset()
