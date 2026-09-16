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
    def __init__(self, platform: str, kind: str = "item", limit: int = 3):
        self.platform, self.kind, self.limit = platform, kind, limit
        self.rules = rules_for(platform, kind)
        self.broken: list[FileReport] = []      # the current run of consecutive broken files

    def observe(self, raw: dict, label: str) -> FileReport | None:
        if self.limit <= 0:                     # switched off in config
            return None
        report = check_file(raw, self.rules, label)
        if report.broken:
            self.broken.append(report)
            log.warning("   ⚠ data missing against the contract: %s", report.summary())
        else:
            self.broken.clear()
        return report

    @property
    def tripped(self) -> bool:
        return self.limit > 0 and len(self.broken) >= self.limit

    def reset(self) -> None:
        self.broken.clear()

    def message(self) -> str:
        what = "products" if self.kind == "item" else "search pages"
        # "đổi cấu trúc JSON" (= changed its JSON structure) is asserted by tests/test_contracts.py
        lines = [f"{len(self.broken)} {what} in a row are missing core data "
                 f"- most likely {self.platform} changed its JSON structure (đổi cấu trúc JSON):"]
        lines += [f"  {r.label}: {r.summary()}" for r in self.broken[-self.limit:]]
        lines += [
            "The data is still saved. Open another window and run:",
            f"  ecommerce check-schema --platform {self.platform}",
            "to see which fields are gone and suggested new names.",
            "Press Enter to keep crawling, or Ctrl+C to stop and fix first.",
        ]
        return "\n".join(lines)
