"""Capacity in ml from the attribute table, variant names, title or description."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

_CAPACITY = re.compile(
    r"(?<![\d.,])(\d{1,5}(?:[.,]\d{1,3})?)\s*(ml|mililit|l|lít|lit|litre|liter|oz)(?![a-zà-ỹ])",
    re.IGNORECASE,
)


DEFAULT_MIN_ML, DEFAULT_MAX_ML = 50, 6000


def _to_ml(number: str, unit: str, min_ml: int = DEFAULT_MIN_ML, max_ml: int = DEFAULT_MAX_ML) -> int | None:
    try:
        value = float(number.replace(",", "."))
    except ValueError:
        return None
    unit = unit.lower()
    if unit in ("l", "lít", "lit", "litre", "liter"):
        value *= 1000
    elif unit == "oz":
        value *= 29.5735
    ml = round(value)
    # Drinkware lives between a shot glass and a 5L jug; outside that range the
    # match is a model number or a typo ("3000L"). The range is per domain.
    return ml if min_ml <= ml <= max_ml else None


def capacities_ml(text: str | None, min_ml: int = DEFAULT_MIN_ML, max_ml: int = DEFAULT_MAX_ML) -> list[int]:
    found: list[int] = []
    for number, unit in _CAPACITY.findall(norm(text)):
        ml = _to_ml(number, unit, min_ml, max_ml)
        if ml and ml not in found:
            found.append(ml)
    return found


def extract_capacity(attrs, variant_names, title, description,
                     min_ml: int = DEFAULT_MIN_ML, max_ml: int = DEFAULT_MAX_ML) -> Found:
    """Attribute table and variant names are both structured, so they are
    merged (a table saying '500ml' next to 500/750ml variants means both
    exist). Title and description are fallbacks only."""
    structured: list[int] = []
    used: list[str] = []
    for source, text in (
        ("thuộc tính", attr_lookup(attrs, "Dung tích", "Dung tích (ml)", "Capacity", "Thể tích",
                                   "Volume Capacity", "Volume", "Capacity (ml)")),
        ("phân loại", " | ".join(variant_names)),
    ):
        values = capacities_ml(text, min_ml, max_ml)
        if values:
            used.append(source)
            structured.extend(v for v in values if v not in structured)
    if structured:
        return _capacity_found(structured, " + ".join(used))
    for source, text in (("tiêu đề", title), ("mô tả", description)):
        values = capacities_ml(text, min_ml, max_ml)
        if values:
            return _capacity_found(values, source)
    return Found()


def _capacity_found(values: list[int], source: str) -> Found:
    values = sorted(values)
    return Found(", ".join(f"{v}ml" for v in values), source,
                 {"min_ml": values[0], "max_ml": values[-1]})
