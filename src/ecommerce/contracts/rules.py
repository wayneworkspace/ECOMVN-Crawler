"""The small language the rule tables (shopee.py, tiktok.py) are written in.

One `Expect` = one thing the Excel file needs, and every place in the raw JSON
the parser may take it from, in the parser's order of preference:

    Expect("Giá bán", level=CORE, kind=NUMBER, feeds=["price_min"],
           sources=["pdp.data.item.price_min", "pdp.data.item.models[].price", ...])

`check_file()` answers, for one raw file: is it there, which source served it,
and does it still have the expected type?
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ecommerce.contracts.paths import values_at

# How bad it is when a field is missing:
Level = Literal["core", "important", "optional"]
CORE: Level = "core"            # every product must have it -> the product counts as broken
IMPORTANT: Level = "important"  # most products have it -> alarm when coverage drops across the run
OPTIONAL: Level = "optional"    # often missing by nature -> only compared with the baseline

# Expected type of the value (what the parser can still read):
Kind = Literal["text", "number", "list", "dict", "bool", "any"]
TEXT: Kind = "text"
NUMBER: Kind = "number"
LIST: Kind = "list"
DICT: Kind = "dict"
BOOL: Kind = "bool"
ANY: Kind = "any"

_NUMERIC_TEXT = re.compile(r"^-?\d+(\.\d+)?$")   # TikTok sends "21951" as text; the parser accepts it


def kind_of(value: Any) -> str:
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, (int, float)):
        return NUMBER
    if isinstance(value, str):
        return NUMBER if _NUMERIC_TEXT.match(value.strip()) else TEXT
    if isinstance(value, list):
        return LIST
    if isinstance(value, dict):
        return DICT
    return type(value).__name__


def matches(value: Any, kind: str) -> bool:
    actual = kind_of(value)
    if kind == ANY or actual == kind:
        return True
    return kind == TEXT and actual == NUMBER     # a name like "2024" is still text


class Expect(BaseModel):
    """One rule. Keep `sources` in the SAME order as the parser reads them."""
    model_config = ConfigDict(frozen=True)
    name: str                                   # shown in reports, e.g. "Giá bán"
    sources: list[str] = Field(min_length=1)
    level: Level
    kind: Kind = ANY
    feeds: list[str] = Field(default_factory=list)   # keys of Product.to_row() this rule fills
    positive: bool = False      # numbers <= 0 mean "not set" (Shopee writes -1), like first_pos()
    also: str = ""              # a source that is not a path (e.g. a row of the attribute table)
    note: str = ""              # why / special cases, for the next reader


class RuleResult(BaseModel):
    name: str
    level: Level
    status: Literal["ok", "missing", "wrong_type"]
    source: str | None = None                   # which source the parser would use
    primary: bool = False                       # was it the first (preferred) source?
    detail: str = ""


class FileReport(BaseModel):
    label: str                                  # file name / product key, for messages
    results: list[RuleResult]

    def problems(self, *levels: str) -> list[RuleResult]:
        levels = levels or (CORE, IMPORTANT, OPTIONAL)
        return [r for r in self.results if r.status != "ok" and r.level in levels]

    @property
    def broken(self) -> bool:
        """A core field is missing or unreadable: this product is unusable."""
        return bool(self.problems(CORE))

    def summary(self) -> str:
        # "(thiếu)" (= missing) is asserted by tests/test_contracts.py
        return ", ".join(f"{r.name} ({'thiếu' if r.status == 'missing' else r.detail})"
                         for r in self.problems(CORE)) or "ok"


def check_rule(raw: Any, rule: Expect) -> RuleResult:
    for index, source in enumerate(rule.sources):
        values = values_at(raw, source)
        if rule.positive:
            values = [v for v in values if kind_of(v) != NUMBER or float(v) > 0]
        if not values:
            continue
        # the parser stops at the first source that has something: judge that one
        wrong = [v for v in values if not matches(v, rule.kind)]
        if wrong:
            return RuleResult(name=rule.name, level=rule.level, status="wrong_type", source=source,
                              primary=index == 0,
                              detail=f"expected {rule.kind}, got {kind_of(wrong[0])}: {str(wrong[0])[:40]!r}")
        return RuleResult(name=rule.name, level=rule.level, status="ok", source=source, primary=index == 0)
    return RuleResult(name=rule.name, level=rule.level, status="missing")


def check_file(raw: Any, rules: list[Expect], label: str = "") -> FileReport:
    return FileReport(label=label, results=[check_rule(raw, rule) for rule in rules])


def under(prefixes: list[str], *suffixes: str) -> list[str]:
    """Same field under several parents, in order:
    under(["a", "b"], "x", "y") -> ["a.x", "a.y", "b.x", "b.y"]"""
    return [f"{p}.{s}" for p in prefixes for s in suffixes]
