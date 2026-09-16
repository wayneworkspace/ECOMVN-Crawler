"""Check a whole crawl run against the rule tables and the baseline.

Used by `ecommerce check-schema`. Reads only files on disk: sends
nothing to Shopee / TikTok, safe to run while a crawl is going.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ecommerce.contracts import lazada, shopee, tiktok
from ecommerce.contracts.rules import CORE, IMPORTANT, Expect, check_file
from ecommerce.contracts.snapshot import KEEP_SHARE, Change, compare, structure, structure_form
from ecommerce.ingestion.raw_store import RunStore, read_json

Kind = Literal["item", "search"]
Verdict = Literal["ok", "warn", "fail"]
KINDS: tuple[Kind, ...] = ("item", "search")
BASELINE_DIR = Path(__file__).parent / "baselines"

RULES: dict[tuple[str, str], list[Expect]] = {
    ("shopee", "item"): shopee.ITEM_RULES,
    ("shopee", "search"): shopee.SEARCH_RULES,
    ("tiktok", "item"): tiktok.ITEM_RULES,
    ("tiktok", "search"): tiktok.SEARCH_RULES,
    ("lazada", "item"): lazada.ITEM_RULES,
    ("lazada", "search"): lazada.SEARCH_RULES,
}
TITLES = {"item": "Product pages", "search": "Search / keyword pages"}


def rules_for(platform: str, kind: str) -> list[Expect]:
    return RULES[(platform, kind)]


def iter_files(store: RunStore, kind: Kind) -> Iterator[tuple[str, dict]]:
    """(label, raw) for every saved file of one kind in a run."""
    folder = store.dir / ("items" if kind == "item" else "search")
    if folder.is_dir():
        for path in sorted(folder.glob("*.json" if kind == "item" else "page_*.json")):
            yield path.stem, read_json(path)


# ---- baseline -------------------------------------------------------------------
def baseline_path(platform: str, kind: str) -> Path:
    return BASELINE_DIR / f"{platform}_{kind}.json"


def load_baseline(platform: str, kind: str) -> dict | None:
    path = baseline_path(platform, kind)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def make_baseline(files: list[tuple[str, dict]], platform: str, kind: str, source: str) -> dict:
    stats = rule_stats([raw for _, raw in files], rules_for(platform, kind))
    n, paths = structure(raw for _, raw in files)
    return {
        "platform": platform, "kind": kind, "made_from": source,
        "made_at": datetime.now().isoformat(timespec="seconds"), "files": n,
        "rules": {name: {"coverage": s.coverage, "primary": s.primary} for name, s in stats.items()},
        "structure": {p: v for p, v in paths.items() if v["share"] >= KEEP_SHARE},
    }


def save_baseline(store: RunStore) -> list[Path]:
    BASELINE_DIR.mkdir(exist_ok=True)
    written = []
    for kind in KINDS:
        files = list(iter_files(store, kind))
        if not files:
            continue
        data = make_baseline(files, store.platform, kind, f"{store.platform}/{store.run_id}")
        path = baseline_path(store.platform, kind)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(path)
    return written


# ---- run report -----------------------------------------------------------------
@dataclass
class RuleStat:
    """How one rule did across the files of a run."""
    files: int = 0
    ok: int = 0
    ok_primary: int = 0
    wrong: int = 0
    missing: list[str] = field(default_factory=list)     # labels of files without it
    wrong_example: str = ""

    @property
    def coverage(self) -> float:
        return round(self.ok / self.files, 3) if self.files else 0.0

    @property
    def primary(self) -> float:
        """Share of the files that have it where the preferred (first) source served."""
        return round(self.ok_primary / self.ok, 3) if self.ok else 0.0


def rule_stats(raws: list[dict], rules: list[Expect], labels: list[str] | None = None) -> dict[str, RuleStat]:
    labels = labels or [str(i) for i in range(len(raws))]
    stats = {r.name: RuleStat(files=len(raws)) for r in rules}
    for label, raw in zip(labels, raws, strict=True):
        for res in check_file(raw, rules).results:
            s = stats[res.name]
            if res.status == "ok":
                s.ok += 1
                s.ok_primary += res.primary
            elif res.status == "wrong_type":
                s.wrong += 1
                s.wrong_example = s.wrong_example or f"{label}: {res.detail}"
            else:
                s.missing.append(label)
    return stats


class RuleVerdict(BaseModel):
    name: str
    level: str
    coverage: float
    base_coverage: float | None
    verdict: Verdict
    reason: str = ""
    sources: list[str]


class SectionReport(BaseModel):
    platform: str
    kind: str
    files: int
    baseline_from: str | None
    rules: list[RuleVerdict]
    changes: list[Change]

    @property
    def failed(self) -> bool:
        return any(r.verdict == "fail" for r in self.rules)


def judge(rule: Expect, s: RuleStat, base: dict | None, drop: float) -> tuple[Verdict, str]:
    """(verdict, reason) for one rule across the run."""
    if rule.level == CORE and s.missing:
        shown = ", ".join(s.missing[:3]) + (" ..." if len(s.missing) > 3 else "")
        # "N file thiếu" (= N files missing it) is asserted by tests/test_contracts.py
        return "fail", f"{len(s.missing)} file thiếu (missing): {shown}"
    lost = (base["coverage"] - s.coverage) if base is not None else 0.0
    dropped = base is not None and base["coverage"] >= 0.5 and lost >= drop
    if s.wrong:
        serious = rule.level == CORE or (rule.level == IMPORTANT and dropped)
        return ("fail" if serious else "warn"), f"{s.wrong} files with wrong type ({s.wrong_example})"
    if base is not None:
        if dropped:
            verdict: Verdict = "fail" if rule.level in (CORE, IMPORTANT) else "warn"
            return verdict, f"dropped from {base['coverage']:.0%} to {s.coverage:.0%}"
        if base["primary"] - s.primary >= drop and s.ok:
            return "warn", (f"primary source serves {s.primary:.0%} (baseline {base['primary']:.0%}): "
                            f"falling back to secondary sources")
    elif rule.level == IMPORTANT and s.coverage < 0.5:
        return "warn", f"only {s.coverage:.0%} of files have it (no baseline to compare)"
    return "ok", ""


def check_section(files: list[tuple[str, dict]], platform: str, kind: str,
                  baseline: dict | None, drop: float = 0.2) -> SectionReport:
    rules = rules_for(platform, kind)
    labels, raws = [f for f, _ in files], [r for _, r in files]
    stats = rule_stats(raws, rules, labels)
    verdicts = []
    for rule in rules:
        base = (baseline or {}).get("rules", {}).get(rule.name)
        verdict, reason = judge(rule, stats[rule.name], base, drop)
        verdicts.append(RuleVerdict(name=rule.name, level=rule.level, coverage=stats[rule.name].coverage,
                                    base_coverage=base["coverage"] if base else None,
                                    verdict=verdict, reason=reason, sources=rule.sources))
    changes: list[Change] = []
    if baseline:
        n, now = structure(raws)
        changes = compare(baseline["structure"], now, n)
    return SectionReport(platform=platform, kind=kind, files=len(files),
                         baseline_from=(baseline or {}).get("made_from"), rules=verdicts, changes=changes)


def check_run(store: RunStore, drop: float = 0.2) -> list[SectionReport]:
    reports = []
    for kind in KINDS:
        files = list(iter_files(store, kind))
        if files:
            reports.append(check_section(files, store.platform, kind,
                                         load_baseline(store.platform, kind), drop))
    return reports


# ---- printing -------------------------------------------------------------------
ICON = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
LEVEL = {"core": "core", "important": "important", "optional": "optional"}


def _relevant(change: Change, report: SectionReport) -> bool:
    """Does the change touch a path some rule reads?"""
    used = [structure_form(s) for r in report.rules for s in r.sources]
    return any(u and (u == change.path or u.startswith(change.path + ".") or u.startswith(change.path + "["))
               for u in used)


def format_report(reports: list[SectionReport], max_other: int = 10) -> str:
    lines: list[str] = []
    for rep in reports:
        base = f"vs baseline {rep.baseline_from}" if rep.baseline_from else "no baseline to compare"
        lines.append(f"\n== {rep.platform} · {TITLES[rep.kind]}: {rep.files} file ({base})")
        for r in rep.rules:
            was = f" (baseline {r.base_coverage:.0%})" if r.base_coverage is not None else ""
            lines.append(f"{ICON[r.verdict]} {r.name:<30} {LEVEL[r.level]:<10} present in {r.coverage:>4.0%}{was}"
                         + (f"  ← {r.reason}" if r.reason else ""))
        mine = [c for c in rep.changes if _relevant(c, rep)]
        hinted = {h for c in mine for h in c.hints}
        other = [c for c in rep.changes if not _relevant(c, rep) and c.path not in hinted]
        if mine:
            lines.append("  Structure changes where the tool reads:")
            for c in mine:
                lines.append("   " + _change_text(c))
        if other:
            lines.append(f"  Other changes ({len(other)}, fields the tool does not read):")
            lines += ["   " + _change_text(c) for c in other[:max_other]]
            if len(other) > max_other:
                lines.append(f"   ... and {len(other) - max_other} more")
    failed = [r for r in reports if r.failed]
    lines.append("")
    if failed:
        lines.append("❌ Some fields need fixing. Open src/ecommerce/contracts/<platform>.py and find the rule: "
                     "its `note` names the reader in transform/. Fix the reader + the rule, then re-run "
                     "`export` - no need to crawl again.")
    else:
        lines.append("✅ The data structure still matches what the tool reads.")
    return "\n".join(lines)


def _change_text(c: Change) -> str:
    if c.kind == "gone":
        hint = f"  → possibly renamed to: {', '.join(c.hints)}" if c.hints else ""
        return f"- gone  {c.path} (present in {c.before} → {c.after}){hint}"
    if c.kind == "new":
        return f"+ new   {c.path} (present in {c.after})"
    return f"~ type  {c.path}: {c.before} → {c.after}"
