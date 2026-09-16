"""Data contracts: which fields of Shopee / TikTok JSON this tool depends on.

Read contracts/README.md first. In short:

    shopee.py, tiktok.py   the rule tables  <- edit these when a site changes
    rules.py               how a rule is written (Expect) and checked
    paths.py               "pdp.data.item.models[].price" -> values
    snapshot.py            full structure of the JSON, diff with the baseline
    check.py               check a whole run (command `ecommerce check-schema`)
    guard.py               check while crawling, stop after N broken files in a row
    baselines/*.json       the structure of a known-good crawl

This package only reads raw JSON files. It never talks to the browser and is
not imported by transform/ (the readers), so it can be moved out as its own
package if another scraper ever needs it.
"""
from ecommerce.contracts.check import check_run, format_report, rules_for, save_baseline
from ecommerce.contracts.guard import SchemaGuard
from ecommerce.contracts.rules import CORE, IMPORTANT, OPTIONAL, Expect, FileReport, check_file

__all__ = [
           "CORE",
           "IMPORTANT",
           "OPTIONAL",
           "Expect",
           "FileReport",
           "SchemaGuard",
           "check_file",
           "check_run",
           "format_report",
           "rules_for",
           "save_baseline",
]
