"""Project paths + the typed, validated view of every YAML the platform reads.

Configuration is split the way the architecture is split:

    configs/app.yaml                     shared: timeouts, export, contracts, paths
    configs/platforms/<name>/config.yaml one file per platform: browser profile,
                                         pacing, search / crawl parameters
    configs/domains/<name>.yaml          optional domain profile (product filter,
                                         attribute vocabularies) -- see domain/profile.py
    configs/reports/<name>.yaml          Excel layout -- see consumption/excel/layout.py

The crawl keyword is NOT configuration. It is a runtime input (`--keyword`)
carried by `CrawlRequest`, together with the other per-run parameters.

Every value the code reads from YAML is declared here once, with its type, its
allowed range and its default. Loading fails AT START-UP with a message that
names the bad key, instead of silently falling back to a default hours into a
crawl:

    shopee.taget
      Extra inputs are not permitted          <- typo in a key
    pacing.delay_min_s
      Input should be a valid number          <- wrong type

Code reads `cfg.shopee.target` (autocompleted, typed) instead of
`scope.get("shopee.target", 200)` scattered over many modules.

Where files live
----------------
`ECOMMERCE_HOME` (default: the current working directory) is the project home:
`configs/`, `data/`, `output/` and the browser profiles are resolved under it.
When `<home>/configs` does not exist the defaults bundled inside the package
(`ecommerce/resources/configs`) are used, so an installed wheel works out of the
box; `ecommerce init` copies them out for editing.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecommerce.domain.profile import DomainProfile

PACKAGE_DIR = Path(__file__).resolve().parent
BUNDLED_CONFIG_DIR = PACKAGE_DIR / "resources" / "configs"

PLATFORMS: tuple[str, ...] = ("shopee", "tiktok", "lazada")
BrowserName = Literal["chrome", "edge"]


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
def project_home() -> Path:
    """`ECOMMERCE_HOME`, else the current working directory."""
    return Path(os.environ.get("ECOMMERCE_HOME") or Path.cwd()).resolve()


def config_dir() -> Path:
    """`ECOMMERCE_CONFIG_DIR`, else `<home>/configs`, else the bundled defaults."""
    override = os.environ.get("ECOMMERCE_CONFIG_DIR")
    if override:
        return Path(override).resolve()
    local = project_home() / "configs"
    return local if local.is_dir() else BUNDLED_CONFIG_DIR


def debug_dir() -> Path:
    """Where page dumps go when a capture fails (`<home>/data/debug`)."""
    return project_home() / "data" / "debug"


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else project_home() / p


def _check_range(low: float, high: float, name: str) -> None:
    if low > high:
        raise ValueError(f"{name}_min ({low}) must be <= {name}_max ({high})")


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class _Section(BaseModel):
    """Unknown keys are an error: a typo must not silently become a default."""
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# app.yaml
# --------------------------------------------------------------------------
class PathSettings(_Section):
    """Relative paths are resolved under the project home."""
    data_dir: str = "data"
    output_dir: str = "output"

    @property
    def data(self) -> Path:
        return _resolve(self.data_dir)

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def image_cache(self) -> Path:
        return self.data / "image_cache"

    @property
    def debug(self) -> Path:
        return self.data / "debug"

    @property
    def output(self) -> Path:
        return _resolve(self.output_dir)


class TimeoutSettings(_Section):
    page_load_ms: int = Field(90_000, ge=1_000)
    api_wait_ms: int = Field(60_000, ge=1_000)
    sku_settle_ms: int = Field(2_000, ge=0)
    click_pause_min_ms: int = Field(5_000, ge=0)
    click_pause_max_ms: int = Field(10_000, ge=0)

    @model_validator(mode="after")
    def _ranges(self):
        _check_range(self.click_pause_min_ms, self.click_pause_max_ms, "click_pause")
        return self


class ExportSettings(_Section):
    layout: str = "default"                      # configs/reports/<layout>.yaml
    embedded_images: int = Field(3, ge=0, le=10)
    thumbnail_px: int = Field(110, ge=20, le=600)
    sku_thumbnail_px: int = Field(70, ge=20, le=600)


class ContractSettings(_Section):
    """Checks against contracts/ (the fields the tool reads)."""
    guard_streak: int = Field(3, ge=0, description="pause after N consecutive files missing core fields; 0 = off")
    coverage_drop: float = Field(0.2, gt=0, le=1, description="check-schema: fail when coverage drops by more")


class AppSettings(_Section):
    default_platform: str = "shopee"
    default_domain: str | None = None            # domain profile applied when --domain is not given
    paths: PathSettings = Field(default_factory=PathSettings)
    timeouts: TimeoutSettings = Field(default_factory=TimeoutSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    contracts: ContractSettings = Field(default_factory=ContractSettings)


# --------------------------------------------------------------------------
# platforms/<name>/config.yaml
# --------------------------------------------------------------------------
class BrowserSettings(_Section):
    name: BrowserName = "chrome"
    profile_dir: str = ".browser_profile/default"
    headless: bool = False
    mode: Literal["attach", "launch"] = "attach"

    @property
    def profile_path(self) -> Path:
        return _resolve(self.profile_dir)


class PacingSettings(_Section):
    delay_min_s: float = Field(20, ge=0)
    delay_max_s: float = Field(45, ge=0)
    long_break_every: int = Field(8, ge=0, description="0 = off")
    long_break_min_s: float = Field(240, ge=0)
    long_break_max_s: float = Field(480, ge=0)
    cooldown_every: int = Field(16, ge=0, description="0 = off")
    cooldown_min_s: float = Field(1200, ge=0)
    cooldown_max_s: float = Field(1800, ge=0)
    block_cooldown_min: float = Field(60, gt=0)
    max_block_cooldowns: int = Field(4, ge=0)
    max_attempts: int = Field(2, ge=1)

    @model_validator(mode="after")
    def _ranges(self):
        _check_range(self.delay_min_s, self.delay_max_s, "delay")
        _check_range(self.long_break_min_s, self.long_break_max_s, "long_break")
        _check_range(self.cooldown_min_s, self.cooldown_max_s, "cooldown")
        return self


class _PlatformSettings(_Section):
    platform: str
    target: int = Field(200, gt=0, description="products in the final dataset")
    buffer_ratio: float = Field(0.15, ge=0, le=5, description="extra candidates to cover failures / drops")
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    pacing: PacingSettings = Field(default_factory=PacingSettings)

    @property
    def profile_path(self) -> Path:
        return self.browser.profile_path


class ShopeeSettings(_PlatformSettings):
    platform: Literal["shopee"] = "shopee"
    sort_by: Literal["sales", "relevancy", "ctime", "price"] = "sales"
    max_pages: int = Field(10, ge=1, le=100)
    include_ads: bool = False
    sku_stock: bool = True
    sku_stock_max_clicks: int = Field(40, ge=1)


class TikTokSettings(_PlatformSettings):
    platform: Literal["tiktok"] = "tiktok"
    buffer_ratio: float = Field(0.6, ge=0, le=5)
    max_keyword_pages: int = Field(120, ge=1)
    browser: BrowserSettings = Field(default_factory=lambda: BrowserSettings(profile_dir=".browser_profile/tiktok"))
    pacing: PacingSettings = Field(default_factory=lambda: PacingSettings(
        delay_min_s=3, delay_max_s=7, long_break_every=40, long_break_min_s=60, long_break_max_s=150))


class LazadaSettings(_PlatformSettings):
    platform: Literal["lazada"] = "lazada"
    sort_by: Literal["popularity", "priceasc", "pricedesc", "ratingdesc"] = "popularity"
    max_pages: int = Field(8, ge=1, le=100)          # ~40 products per page
    include_ads: bool = False
    browser: BrowserSettings = Field(default_factory=lambda: BrowserSettings(
        name="edge", profile_dir=".browser_profile/lazada_edge"))
    pacing: PacingSettings = Field(default_factory=lambda: PacingSettings(
        delay_min_s=8, delay_max_s=20, long_break_every=15, long_break_min_s=90, long_break_max_s=180,
        cooldown_every=0))


PLATFORM_SETTINGS: dict[str, type[_PlatformSettings]] = {
    "shopee": ShopeeSettings, "tiktok": TikTokSettings, "lazada": LazadaSettings,
}


# --------------------------------------------------------------------------
# runtime input
# --------------------------------------------------------------------------
def slugify(text: str) -> str:
    """'Bình giữ nhiệt' -> 'binh-giu-nhiet' (ASCII, for URLs and file names)."""
    import unicodedata
    text = unicodedata.normalize("NFD", text or "").replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text)).strip("-")


class CrawlRequest(_Section):
    """What the user asks for at run time. Never stored in YAML."""
    platform: str
    keyword: str = Field(..., min_length=1)
    domain: str | None = None                    # domain profile name, e.g. "giu_nhiet"
    max_products: int | None = Field(None, gt=0) # overrides <platform>.target

    @field_validator("platform")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in PLATFORM_SETTINGS:
            raise ValueError(f"unknown platform {value!r}; known: {', '.join(PLATFORM_SETTINGS)}")
        return value

    @property
    def keyword_slug(self) -> str:
        return slugify(self.keyword)


# --------------------------------------------------------------------------
# the whole thing
# --------------------------------------------------------------------------
class AppConfig(_Section):
    """Everything a command needs: shared settings, every platform's settings,
    the runtime request and the (optional) domain profile."""
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    app: AppSettings = Field(default_factory=AppSettings)
    shopee: ShopeeSettings = Field(default_factory=ShopeeSettings)
    tiktok: TikTokSettings = Field(default_factory=TikTokSettings)
    lazada: LazadaSettings = Field(default_factory=LazadaSettings)
    request: CrawlRequest | None = None
    domain: DomainProfile | None = None

    # --- shortcuts kept from the single-file config era ---------------------
    @property
    def timeouts(self) -> TimeoutSettings:
        return self.app.timeouts

    @property
    def export(self) -> ExportSettings:
        return self.app.export

    @property
    def contracts(self) -> ContractSettings:
        return self.app.contracts

    @property
    def paths(self) -> PathSettings:
        return self.app.paths

    @property
    def keyword(self) -> str:
        if self.request is None:
            raise RuntimeError("no crawl request attached (use --keyword)")
        return self.request.keyword

    @property
    def platform(self) -> str:
        return self.request.platform if self.request else self.app.default_platform

    def for_platform(self, name: str | None = None) -> _PlatformSettings:
        return getattr(self, name or self.platform)

    def with_updates(self, **sections: dict) -> AppConfig:
        """Copy with some fields of some sections changed, re-validated.
        e.g. cfg.with_updates(shopee={"sku_stock": False})"""
        data = self.model_dump(exclude={"domain"})
        for name, values in sections.items():
            data[name] = {**data[name], **values}
        return AppConfig.model_validate({**data, "domain": self.domain})

    def with_request(self, request: CrawlRequest, domain: DomainProfile | None = None) -> AppConfig:
        """Attach the runtime request; `max_products` overrides the platform target."""
        cfg = self.with_updates() if domain is None else self.model_copy(update={"domain": domain})
        updates: dict = {}
        if request.max_products:
            updates[request.platform] = {"target": request.max_products}
        data = cfg.model_dump(exclude={"domain"})
        for name, values in updates.items():
            data[name] = {**data[name], **values}
        return AppConfig.model_validate({**data, "request": request, "domain": domain or self.domain})


def domain_path(name: str, root: Path | None = None) -> Path:
    return (Path(root) if root else config_dir()) / "domains" / f"{name}.yaml"


def load_domain(name: str | None, root: Path | None = None) -> DomainProfile | None:
    """`configs/domains/<name>.yaml` -> DomainProfile; None when no name is given."""
    if not name:
        return None
    path = domain_path(name, root)
    if not path.exists():
        known = sorted(p.stem for p in path.parent.glob("*.yaml")) if path.parent.is_dir() else []
        raise FileNotFoundError(f"domain profile {name!r} not found at {path}"
                                + (f"; available: {', '.join(known)}" if known else ""))
    return DomainProfile.from_yaml(path)


def load_config(root: Path | None = None) -> AppConfig:
    """Read app.yaml + every platforms/<name>/config.yaml under `root`
    (default: `config_dir()`). A missing platform file means defaults."""
    root = Path(root) if root else config_dir()
    app_path = root / "app.yaml"
    data: dict = {"app": _read_yaml(app_path) if app_path.exists() else {}}
    for name in PLATFORM_SETTINGS:
        path = root / "platforms" / name / "config.yaml"
        section = _read_yaml(path) if path.exists() else {}
        section.setdefault("platform", name)
        data[name] = section
    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def package_version() -> str:
    try:
        from importlib.metadata import version
        return version("ecommerce-data-platform")
    except Exception:            # not installed (running from a checkout)
        return "0.0.0"
