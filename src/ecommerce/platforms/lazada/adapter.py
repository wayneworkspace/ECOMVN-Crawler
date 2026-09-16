"""Lazada Việt Nam adapter: search sorted by 'Bán chạy' -> product pages read
from the JSON embedded in the HTML (window.__moduleData__), fetched by XHR from
one real browser tab."""
from __future__ import annotations

import logging

from ecommerce.domain.candidate import LazadaCandidate
from ecommerce.domain.dataset import Dataset
from ecommerce.ingestion.raw_store import RunStore
from ecommerce.platforms.base import PlatformAdapter
from ecommerce.settings import AppConfig

log = logging.getLogger(__name__)


class LazadaAdapter(PlatformAdapter):
    name = "lazada"
    label = "Lazada"
    needs_login = False          # works as a guest; logging in reduces captchas
    login_url = "https://member.lazada.vn/user/login"

    def headless(self, cfg: AppConfig) -> bool:
        return False             # the slider captcha must be solvable by a person

    def crawl(self, context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
        from ecommerce.platforms.lazada.extract.crawl import crawl
        self.check_session(context)
        crawl(context, store, cfg, limit=limit)

    def check_session(self, context) -> None:
        from ecommerce.platforms.lazada.extract.session import lazada_login_state
        state = lazada_login_state(context)
        log.info("Lazada login state: %s", {True: "logged in", False: "guest", None: "unknown"}[state])

    def build_dataset(self, store: RunStore, cfg: AppConfig) -> Dataset:
        from ecommerce.platforms.lazada.parse.dataset import build_dataset
        return build_dataset(store, cfg)

    def candidate_model(self):
        return LazadaCandidate
