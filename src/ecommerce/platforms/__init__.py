"""Platform registry: `--platform <name>` -> adapter.

Adding a platform = a new package `ecommerce/platforms/<name>/` with an
`adapter.py`, a settings class in `settings.py`, a config file under
`configs/platforms/<name>/` and one entry below. The pipeline does not change.
"""
from __future__ import annotations

from ecommerce.platforms.base import PlatformAdapter


def _registry() -> dict[str, PlatformAdapter]:
    from ecommerce.platforms.lazada.adapter import LazadaAdapter
    from ecommerce.platforms.shopee.adapter import ShopeeAdapter
    from ecommerce.platforms.tiktok.adapter import TikTokAdapter
    return {a.name: a for a in (ShopeeAdapter(), TikTokAdapter(), LazadaAdapter())}


def platform_names() -> tuple[str, ...]:
    return tuple(_registry())


def get_adapter(name: str) -> PlatformAdapter:
    try:
        return _registry()[name]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; known: {', '.join(_registry())}") from None


__all__ = ["PlatformAdapter", "get_adapter", "platform_names"]
