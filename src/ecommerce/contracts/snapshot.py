"""Structure snapshot: every path in the raw JSON and its type, then a diff
against a baseline saved from a good crawl.

The rule tables only know the fields the tool reads. The snapshot sees
everything, so when a field we read disappears it can point at the field that
appeared in its place ("price -> price_v2: possibly renamed").

    pdp.data.item.models[].price     one path for every element of the list
    ...skus_price.*.sale_price       dict keys that are ids collapse into '*'
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel

from ecommerce.contracts.paths import is_present
from ecommerce.contracts.rules import kind_of

MAX_DEPTH = 9
MAX_LIST_ITEMS = 40          # enough to see every shape, bounded cost on long lists
KEEP_SHARE = 0.3             # paths rarer than this are not stored in the baseline
GONE_BEFORE, GONE_AFTER = 0.8, 0.2    # was in >=80% of files, now in <=20%
_ID_KEY = re.compile(r"^\d+$|^[0-9a-f]{16,}$")


def _key(k: str) -> str:
    return "*" if _ID_KEY.match(str(k)) else str(k)


def paths_of(obj: Any) -> dict[str, set[str]]:
    """{path: {type, ...}} for one JSON document (present values only)."""
    out: dict[str, set[str]] = {}

    def walk(node: Any, path: str, depth: int) -> None:
        if not is_present(node):
            return
        if path:
            out.setdefault(path, set()).add(kind_of(node))
        if depth >= MAX_DEPTH:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{_key(k)}" if path else _key(k), depth + 1)
        elif isinstance(node, list):
            for v in node[:MAX_LIST_ITEMS]:
                walk(v, f"{path}[]", depth + 1)

    walk(obj, "", 0)
    return out


def structure(docs: Iterable[Any]) -> tuple[int, dict[str, dict]]:
    """Across many files: (n_files, {path: {"share": 0..1, "types": [...]}})."""
    seen: dict[str, int] = {}
    types: dict[str, set[str]] = {}
    n = 0
    for doc in docs:
        n += 1
        for path, kinds in paths_of(doc).items():
            seen[path] = seen.get(path, 0) + 1
            types.setdefault(path, set()).update(kinds)
    return n, {p: {"share": round(c / n, 3), "types": sorted(types[p])} for p, c in sorted(seen.items())}


class Change(BaseModel):
    kind: Literal["gone", "new", "type"]
    path: str
    before: str = ""
    after: str = ""
    hints: list[str] = []          # for 'gone': paths that may be its new name


def _parent(path: str) -> str:
    return path.rsplit(".", 1)[0] if "." in path else ""


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("[]", "")


def _topmost(paths: list[str]) -> list[str]:
    """Drop children of a path already in the list (report 'item' gone, not its 200 fields)."""
    keep: list[str] = []
    for p in sorted(paths):
        if not any(p.startswith(k + ".") or p.startswith(k + "[]") for k in keep):
            keep.append(p)
    return keep


def compare(baseline: dict[str, dict], now: dict[str, dict], n_now: int) -> list[Change]:
    def share(table: dict, path: str) -> float:
        return table.get(path, {}).get("share", 0.0)

    gone = _topmost([p for p, v in baseline.items()
                     if v["share"] >= GONE_BEFORE and share(now, p) <= GONE_AFTER])
    new = _topmost([p for p, v in now.items()
                    if v["share"] >= GONE_BEFORE and share(baseline, p) <= GONE_AFTER]) if n_now >= 3 else []
    changes: list[Change] = []
    for p in gone:
        changes.append(Change(kind="gone", path=p, before=f"{share(baseline, p):.0%}",
                              after=f"{share(now, p):.0%}", hints=rename_hints(p, new)))
    changes += [Change(kind="new", path=p, before=f"{share(baseline, p):.0%}", after=f"{share(now, p):.0%}")
                for p in new]
    for p, v in now.items():
        old = baseline.get(p)
        if old and old["share"] >= 0.5 and v["share"] >= 0.5:
            added = set(v["types"]) - set(old["types"])
            if added:
                changes.append(Change(kind="type", path=p, before="/".join(old["types"]),
                                      after="/".join(v["types"])))
    return changes


def rename_hints(gone_path: str, new_paths: list[str], limit: int = 2) -> list[str]:
    """New paths next to the gone one (same parent) or with a similar name."""
    parent, leaf = _parent(gone_path), _leaf(gone_path)
    scored = []
    for p in new_paths:
        similarity = difflib.SequenceMatcher(None, leaf, _leaf(p)).ratio()
        if _parent(p) == parent:
            similarity += 1                      # same place beats a similar name elsewhere
        if similarity >= 0.6:
            scored.append((similarity, p))
    return [p for _, p in sorted(scored, reverse=True)[:limit]]


def structure_form(source: str) -> str | None:
    """A rule source written as a snapshot path ('rating_count.0' -> 'rating_count[]').
    None for '**' sources (their place is not fixed)."""
    if "**" in source:
        return None
    return re.sub(r"\.(\d+)(?=\.|$)", "[]", source)
