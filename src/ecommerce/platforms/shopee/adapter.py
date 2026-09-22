"""Shopee Vietnam adapter: search pages sorted by sales -> product pages
(JSON the page itself loads) -> optional per-SKU stock by clicking variations."""
from __future__ import annotations

import contextlib
import sys

from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.domain.dataset import Dataset
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.base import PlatformAdapter, register_platform
from ecommerce.settings import AppConfig

NOT_LOGGED_IN = ("The tool's browser profile is NOT logged in to Shopee.\n"
                 "Run:  ecommerce login --platform shopee   then run this command again.")


@register_platform("shopee")
class ShopeeAdapter(PlatformAdapter):
    name = "shopee"
    label = "Shopee"
    needs_login = True
    login_url = "https://shopee.vn/buyer/login"

    def crawl(self, context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
        from ecommerce.platforms.shopee.extract.detail import crawl_details
        from ecommerce.platforms.shopee.extract.listing import crawl_listing
        self.check_session(context)
        candidates = crawl_listing(context, store, cfg)
        crawl_details(context, store, cfg, candidates, limit=limit)

    def check_session(self, context) -> None:
        """Refuse to crawl as a guest: every page would bounce to the login wall."""
        import logging

        from ecommerce.platforms.shopee.extract.session import shopee_login_state
        state = shopee_login_state(context)
        if state is False:
            sys.exit(NOT_LOGGED_IN)
        logging.info("Login state: %s", {True: "logged in", None: "unknown"}[state])

    def build_dataset(self, store: RunStore, cfg: AppConfig) -> Dataset:
        from ecommerce.platforms.shopee.parse.dataset import build_dataset
        return build_dataset(store, cfg)

    def candidate_model(self):
        return ShopeeCandidate

    def status_extra(self, store: RunStore, saved: list) -> str:
        with_sku = 0
        for c in saved:
            with contextlib.suppress(Exception):
                with_sku += read_json(store.item_path(c.shopid, c.itemid)).get("sku_stock") is not None
        return f", per-SKU stock={with_sku} (pass 2 left {len(saved) - with_sku})"
