"""The contract every platform adapter fulfils.

"Platform-specific at the edge": a platform owns its configuration, its
extraction (how pages are fetched and captured), its parsers (raw JSON ->
Product) and its dataset builder (which products make the final, ranked
dataset). The CLI and every layer below the edge only talk to this interface,
so adding a platform is adding one package under `ecommerce/platforms/` and one
line in the registry -- the pipeline does not change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeVar

from ecommerce.domain.dataset import Dataset
from ecommerce.ingestion.raw_store import RunStore
from ecommerce.settings import AppConfig, BrowserSettings

TAdapter = TypeVar("TAdapter", bound=type["PlatformAdapter"])
_REGISTRY: dict[str, type[PlatformAdapter]] = {}


def register_platform(name: str | None = None) -> Callable[[TAdapter], TAdapter]:
    """Decorator to register a PlatformAdapter subclass in the global registry."""
    def decorator(cls: TAdapter) -> TAdapter:
        key = (name or getattr(cls, "name", cls.__name__)).lower()
        _REGISTRY[key] = cls
        return cls
    return decorator


def get_registered_adapters() -> dict[str, type[PlatformAdapter]]:
    """Returns copy of registered platform adapter classes."""
    return dict(_REGISTRY)


class PlatformAdapter(ABC):
    """One per platform. Stateless: everything it needs arrives as arguments."""

    name: str                       # registry key and `--platform` value
    label: str                      # human name ("Shopee", "TikTok Shop")
    needs_login: bool = False       # `login` command: a session must exist before crawling
    login_url: str = ""             # page opened by `login` (login form or a page whose captcha must be solved)

    # ---- configuration --------------------------------------------------
    def settings(self, cfg: AppConfig):
        return cfg.for_platform(self.name)

    def browser(self, cfg: AppConfig) -> BrowserSettings:
        return self.settings(cfg).browser

    def headless(self, cfg: AppConfig) -> bool:
        return self.browser(cfg).headless

    # ---- ingestion ------------------------------------------------------
    @abstractmethod
    def crawl(self, context, store: RunStore, cfg: AppConfig, limit: int | None = None) -> None:
        """Discovery + product pages, writing raw JSON into `store`. Resumable:
        pages already on disk are never fetched again."""

    def check_session(self, context) -> None:
        """Raise SystemExit with instructions when the browser session cannot crawl."""
        return None

    # ---- transformation -------------------------------------------------
    @abstractmethod
    def build_dataset(self, store: RunStore, cfg: AppConfig) -> Dataset:
        """Raw run -> ranked platform dataset (pure, no browser)."""

    # ---- operations -----------------------------------------------------
    @abstractmethod
    def candidate_model(self):
        """The candidate model used in candidates.json (for `status`)."""

    def status_extra(self, store: RunStore, saved: list) -> str:
        return ""

    def item_key(self, key: str) -> tuple[str, str]:
        """'<a>_<b>' -> the two ids `RunStore.item_path` expects."""
        a, _, b = key.partition("_")
        return a, b

    # ---- description ----------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "needs_login": self.needs_login}
