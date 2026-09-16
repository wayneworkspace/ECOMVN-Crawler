"""Test helpers: configuration + the domain profile the expectations assume.

Tests run against the bundled configuration (ECOMMERCE_CONFIG_DIR points at
`src/ecommerce/resources/configs`) and the `giu_nhiet` domain profile, so the
expectations written for the original drinkware crawler still hold.
"""
import os
from pathlib import Path

from ecommerce.settings import BUNDLED_CONFIG_DIR, AppConfig, CrawlRequest, load_config, load_domain  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"
os.environ.setdefault("ECOMMERCE_CONFIG_DIR", str(BUNDLED_CONFIG_DIR))

PROFILE = load_domain("giu_nhiet", BUNDLED_CONFIG_DIR)
PROFILE_OIL = load_domain("dau_nhot_xe_may", BUNDLED_CONFIG_DIR)
KEYWORD = "giữ nhiệt"


def make_cfg(platform: str = "shopee", keyword: str | None = KEYWORD, profile=PROFILE, **sections) -> AppConfig:
    """AppConfig with defaults, the given section overrides, a crawl request and the domain profile.

    `pacing=` / `browser=` shortcuts go to the chosen platform's section.
    """
    data: dict = {"app": sections.pop("app", {})}
    for key in ("timeouts", "export", "contracts"):
        if key in sections:
            data["app"][key] = sections.pop(key)
    for key in ("pacing", "browser"):
        if key in sections:
            sections.setdefault(platform, {})[key] = sections.pop(key)
    data.update(sections)
    cfg = AppConfig.model_validate(data)
    if keyword is None:
        return cfg.model_copy(update={"domain": profile})
    request = CrawlRequest(platform=platform, keyword=keyword, domain=profile.name if profile else None)
    return cfg.with_request(request, profile)

