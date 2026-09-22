"""Used by the crawlers: check each file right after it is saved.

One broken product can be a strange listing. Several in a row almost always
means the site changed its JSON -- and carrying on would spend hours
crawling data the tool can no longer read. So after `limit` broken files in a
row the crawler stops and asks a person (the files are still saved: after the
reader is fixed, `export` works without crawling again).

    guard = SchemaGuard("shopee", "item", limit=cfg.contracts.guard_streak)
    guard.observe(raw, key)
    if guard.tripped:
        human_pause(guard.message())
        guard.reset()
"""
from __future__ import annotations

import logging

from ecommerce.contracts.check import rules_for
from ecommerce.contracts.rules import FileReport, check_file

log = logging.getLogger(__name__)


class SchemaGuard:
    """Runtime circuit breaker monitoring raw API response compliance against schema contracts.

    Attributes:
        platform: Target platform name (e.g., 'shopee', 'tiktok', 'lazada').
        kind: Response payload type ('item' for product detail, 'search' for search page).
        limit: Threshold of consecutive broken files before tripping the breaker.
    """

    def __init__(self, platform: str, kind: str = "item", limit: int = 3):
        self.platform = platform
        self.kind = kind
        self.limit = limit
        self.rules = rules_for(platform, kind)
        self.broken: list[FileReport] = []      # Track consecutive broken file reports

    def observe(self, raw: dict, label: str) -> FileReport | None:
        """Inspects a newly fetched raw JSON file against platform schema rules.

        If missing core contract fields, increments consecutive broken counter.
        If valid, resets the broken file streak to zero.
        """
        if self.limit <= 0:                     # Disabled via configuration
            return None

        report = check_file(raw, self.rules, label)
        if report.broken:
            self.broken.append(report)
            log.warning("   ⚠ data missing against the contract: %s", report.summary())
        else:
            self.broken.clear()                 # Reset streak on valid file

        return report

    @property
    def tripped(self) -> bool:
        """Returns True if broken file streak reaches or exceeds limit threshold."""
        return self.limit > 0 and len(self.broken) >= self.limit

    def reset(self) -> None:
        """Resets the broken file streak list."""
        self.broken.clear()

    def message(self) -> str:
        """Generates clear, actionable instructions for the operator when tripped."""
        what = "products" if self.kind == "item" else "search pages"
        lines = [
            f"{len(self.broken)} {what} in a row are missing core data "
            f"- most likely {self.platform} changed its JSON structure (đổi cấu trúc JSON):"
        ]
        lines += [f"  {r.label}: {r.summary()}" for r in self.broken[-self.limit:]]
        lines += [
            "The data is still saved. Open another window and run:",
            f"  ecommerce check-schema --platform {self.platform}",
            "to see which fields are gone and suggested new names.",
            "Press Enter to keep crawling, or Ctrl+C to stop and fix first.",
        ]
        return "\n".join(lines)
