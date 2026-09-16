"""Excel layout declared in YAML (`configs/reports/<name>.yaml`).

The consumption layer is intentionally isolated: sheet list, sheet order,
column selection and per-platform styling are configuration, so going from 5
sheets to 10 sheets does not touch the scraper or the parsers.

What stays in Python is HOW a column value is computed (`columns.py` keeps the
registry key -> header / width / kind, and the record keys come from
`Product.to_row()`), and the checklist requirements, which need code to measure
coverage. YAML picks and orders; Python computes.

    name: default
    filename: "{prefix}_{platform}_top{count}_{run_id}_{stamp}.xlsx"
    sheets:
      - type: products          # one row per product
        columns: [final_rank, image_1, title, ...]      # registry keys; omit = all
      - type: sku_detail        # one row per SKU
      - type: checklist         # requirement coverage
      - type: excluded
      - type: failures
      - type: info
    platforms:
      shopee: {label: Shopee, head_color: "#EE4D2D"}
      tiktok: {label: TikTok Shop, head_color: "#161823", drop_columns: [final_price, ...]}
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ecommerce.consumption.excel.columns import COLUMNS, SKU_COLUMNS, Col, SkuCol

SheetType = Literal["products", "sku_detail", "checklist", "excluded", "failures", "info"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnOverride(_Section):
    key: str
    header: str | None = None
    width: float | None = None


ColumnRef = str | ColumnOverride


class SheetSpec(_Section):
    type: SheetType
    name: str | None = None            # default: platform label for `products`, a fixed name otherwise
    enabled: bool = True
    columns: list[ColumnRef] | None = None    # registry keys in display order; None = every column
    freeze_columns: int | None = None         # `products` only


class PlatformStyle(_Section):
    label: str
    head_color: str = "#EE4D2D"
    drop_columns: list[str] = Field(default_factory=list)      # fields the platform never publishes
    excluded_headers: tuple[str, str] = ("Hạng trên sàn", "Trang")


DEFAULT_SHEET_NAMES = {"sku_detail": "Detail", "checklist": "Checklist đề bài", "excluded": "Bị loại",
                       "failures": "Lỗi crawl", "info": "Thông tin"}


class ReportLayout(_Section):
    name: str = "default"
    filename: str = "{prefix}_{platform}_top{count}_{run_id}_{stamp}.xlsx"
    sheets: list[SheetSpec]
    platforms: dict[str, PlatformStyle]

    @field_validator("sheets")
    @classmethod
    def _at_least_one(cls, value: list[SheetSpec]) -> list[SheetSpec]:
        if not [s for s in value if s.enabled]:
            raise ValueError("a report needs at least one enabled sheet")
        return value

    # ---- lookups --------------------------------------------------------
    def style(self, platform: str) -> PlatformStyle:
        try:
            return self.platforms[platform]
        except KeyError:
            raise KeyError(f"report layout {self.name!r} has no style for platform {platform!r}") from None

    def enabled_sheets(self) -> list[SheetSpec]:
        return [s for s in self.sheets if s.enabled]

    def sheet_name(self, sheet: SheetSpec, platform: str) -> str:
        if sheet.name:
            return sheet.name.format(platform=self.style(platform).label)
        return self.style(platform).label if sheet.type == "products" else DEFAULT_SHEET_NAMES[sheet.type]

    def product_columns(self, sheet: SheetSpec, platform: str) -> list[Col]:
        """Registry columns in YAML order, minus the platform's dropped fields."""
        return [c for c in _pick(COLUMNS, sheet.columns, "column") if c.key not in self.style(platform).drop_columns]

    def sku_columns(self, sheet: SheetSpec, platform: str) -> list[SkuCol]:
        return [c for c in _pick(SKU_COLUMNS, sheet.columns, "SKU column")
                if c.key not in self.style(platform).drop_columns]

    @classmethod
    def from_yaml(cls, path: Path) -> ReportLayout:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        data.setdefault("name", Path(path).stem)
        return cls.model_validate(data)


def _pick(registry, refs: list[ColumnRef] | None, what: str):
    if refs is None:
        return list(registry)
    by_key = {c.key: c for c in registry}
    out = []
    for ref in refs:
        key = ref if isinstance(ref, str) else ref.key
        if key not in by_key:
            if key.startswith("attr_") and registry is COLUMNS:
                # named attribute group from the domain profile (features.groups)
                by_key[key] = Col(key, key[5:].replace("_", " ").capitalize(), 16)
            else:
                raise KeyError(f"unknown {what} {key!r}; known: {', '.join(by_key)}")
        col = by_key[key]
        if isinstance(ref, ColumnOverride):
            col = col.with_overrides(header=ref.header, width=ref.width)
        out.append(col)
    return out
