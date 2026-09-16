"""TikTok Shop Vietnam adapter: keyword pages (/vn/k/<slug>, walked through
"Related Searches") -> product pages read from the JSON embedded in the HTML."""
from __future__ import annotations

from ecommerce.domain.candidate import TikTokCandidate
from ecommerce.domain.dataset import Dataset
from ecommerce.ingestion.raw_store import RunStore
from ecommerce.platforms.base import PlatformAdapter
from ecommerce.settings import AppConfig


class TikTokAdapter(PlatformAdapter):
    name = "tiktok"
    label = "TikTok Shop"
    needs_login = False
    login_url = "https://shop.tiktok.com/vn"      # open any keyword page there and solve the security check once

    def headless(self, cfg: AppConfig) -> bool:
        return False        # the security check must be solvable by a person

    def crawl(self, context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
        from ecommerce.platforms.tiktok.extract.crawl import crawl
        crawl(context, store, cfg, limit=limit)

    def build_dataset(self, store: RunStore, cfg: AppConfig) -> Dataset:
        from ecommerce.platforms.tiktok.parse.dataset import build_dataset
        return build_dataset(store, cfg)

    def candidate_model(self):
        return TikTokCandidate
