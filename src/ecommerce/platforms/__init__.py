"""Platform registry: `--platform <name>` -> adapter.

Adding a platform = a new package `ecommerce/platforms/<name>/` with an
`adapter.py` decorated with `@register_platform(...)`.
"""
from __future__ import annotations

from ecommerce.platforms.base import PlatformAdapter, get_registered_adapters


def _ensure_loaded() -> None:
    """Ensure platform modules are imported so `@register_platform` decorators execute."""
    import ecommerce.platforms.lazada.adapter
    import ecommerce.platforms.shopee.adapter
    import ecommerce.platforms.tiktok.adapter  # noqa: F401


def _registry() -> dict[str, PlatformAdapter]:
    _ensure_loaded()
    return {name: cls() for name, cls in get_registered_adapters().items()}


def platform_names() -> tuple[str, ...]:
    return tuple(_registry())


def get_adapter(name: str) -> PlatformAdapter:
    registry = _registry()
    try:
        return registry[name.lower()]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; known: {', '.join(registry)}") from None


__all__ = ["PlatformAdapter", "get_adapter", "platform_names"]
