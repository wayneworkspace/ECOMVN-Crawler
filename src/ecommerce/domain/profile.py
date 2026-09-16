"""Domain profile: the product-category knowledge that is NOT part of a platform.

The keyword is a runtime input, so nothing in the code may assume a product
category. Everything that does -- "keep drinkware, drop lunch boxes", the
material and feature vocabularies, the TikTok keyword pages worth walking --
lives in `configs/domains/<name>.yaml` and is loaded into this model.

    ecommerce crawl --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet

Without a domain profile the pipeline is generic: nothing is filtered out and
no attributes are extracted from free text. The profile only ever narrows or
enriches; it never changes how a platform is crawled or parsed.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

Rule = tuple[str, str]           # (regex, label)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _compile_all(rules: list[Rule]) -> list[Rule]:
    for rx, _ in rules:
        try:
            re.compile(rx)
        except re.error as exc:
            raise ValueError(f"bad regex {rx!r}: {exc}") from None
    return rules


class TitleFilter(_Section):
    """Which search results belong to the domain, decided from the title.

    Rule: the FIRST product noun in the title decides. Sellers put the product
    first and the freebies after, so "Bình giữ nhiệt 500ml tặng túi" keeps
    (bình) and "Túi giữ nhiệt đựng bình sữa" drops (túi).
    """
    keep_nouns: list[Rule] = Field(default_factory=list)   # (regex, product type)
    drop_nouns: list[Rule] = Field(default_factory=list)   # (regex, product type)
    # "tặng túi", "kèm 2 ống hút": the gift, not the product. Removed before the rule runs.
    freebie_items: list[str] = Field(default_factory=list)
    freebie_qualifiers: list[str] = Field(default_factory=list)
    # keep a title with no recognised noun when it contains a capacity (ml / L)
    keep_if_capacity: bool = False
    keep_if_capacity_type: str = "Không rõ loại (có dung tích)"   # product type recorded in that case
    keep_reason: str = "đúng ngành hàng"                          # reason recorded for kept products
    # titles must also match this (TikTok keyword pages return unrelated products)
    title_must_match: str | None = None
    title_must_match_platforms: list[str] = Field(default_factory=lambda: ["tiktok"])
    title_must_match_reason: str = "tên không khớp từ khoá"

    @field_validator("keep_nouns", "drop_nouns")
    @classmethod
    def _valid_rules(cls, value: list[Rule]) -> list[Rule]:
        return _compile_all(value)

    @field_validator("title_must_match")
    @classmethod
    def _valid_regex(cls, value):
        if value:
            re.compile(value)
        return value


class TikTokDiscovery(_Section):
    """TikTok Shop web has no search box: the crawler walks SEO keyword pages
    (/vn/k/<slug>) and their "Related Searches". Which pages are worth
    following is domain knowledge."""
    seed_slugs: list[str] = Field(default_factory=list)
    slug_include: str | None = None
    slug_exclude: str | None = None

    @field_validator("slug_include", "slug_exclude")
    @classmethod
    def _valid_regex(cls, value):
        if value:
            re.compile(value)
        return value


class Discovery(_Section):
    tiktok: TikTokDiscovery = Field(default_factory=TikTokDiscovery)


class CapacitySpec(_Section):
    """Values outside [min_ml, max_ml] are model numbers or typos ("3000L")."""
    min_ml: int = 50
    max_ml: int = 6000


class MaterialsSpec(_Section):
    vocabulary: list[Rule] | None = None          # (regex, canonical name); None = built-in list
    attribute_names: list[str] | None = None
    inner_attribute_names: list[str] | None = None
    outer_attribute_names: list[str] | None = None


class FeaturesSpec(_Section):
    flags: list[Rule] | None = None               # (regex, label); None = built-in list -> "features"
    hot_hours: bool = True                        # "giữ nóng 12 giờ" -> "Giữ nóng 12h"
    cold_hours: bool = True
    # Named groups get their own Excel column (`attr_<group>` in the report layout):
    #   groups: {grade: [["\\b10w[- ]?40\\b", "10W-40"], ...], type: [...]}
    groups: dict[str, list[Rule]] = Field(default_factory=dict)
    title_only_groups: list[str] = Field(default_factory=list)   # groups read from the title only
    first_match_groups: list[str] = Field(default_factory=list)  # groups that keep only the first matching label

    @field_validator("groups")
    @classmethod
    def _valid_groups(cls, value: dict[str, list[Rule]]) -> dict[str, list[Rule]]:
        for name, rules in value.items():
            if not re.fullmatch(r"[a-z0-9_]+", name):
                raise ValueError(f"group name {name!r} must be [a-z0-9_]")
            _compile_all(rules)
        return value


SPEC_NAMES = ("capacity", "materials", "colors", "size", "weight", "features", "origin", "warranty")


class Specs(_Section):
    enabled: list[str] = Field(default_factory=lambda: list(SPEC_NAMES))
    capacity: CapacitySpec = Field(default_factory=CapacitySpec)
    materials: MaterialsSpec = Field(default_factory=MaterialsSpec)
    features: FeaturesSpec = Field(default_factory=FeaturesSpec)

    @field_validator("enabled")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(SPEC_NAMES))
        if unknown:
            raise ValueError(f"unknown spec extractors {unknown}; known: {list(SPEC_NAMES)}")
        return value

    def on(self, name: str) -> bool:
        return name in self.enabled


class ReportText(_Section):
    """Domain wording that ends up in the Excel 'Thông tin' sheet."""
    filter_description: str = "Không lọc theo ngành hàng"
    file_prefix: str | None = None                # default: the profile name
    layout: str | None = None                     # configs/reports/<layout>.yaml; default: app.yaml export.layout


class DomainProfile(_Section):
    name: str = Field(..., pattern=r"^[a-z0-9_]+$")
    description: str = ""
    filter: TitleFilter = Field(default_factory=TitleFilter)
    discovery: Discovery = Field(default_factory=Discovery)
    specs: Specs = Field(default_factory=Specs)
    report: ReportText = Field(default_factory=ReportText)

    @property
    def file_prefix(self) -> str:
        return self.report.file_prefix or self.name

    @classmethod
    def from_yaml(cls, path: Path) -> DomainProfile:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        data.setdefault("name", Path(path).stem)
        return cls.model_validate(data)
