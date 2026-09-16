"""Bronze / raw layer on disk: one JSON file per captured page, written atomically.

The raw files ARE the checkpoint. A product whose file exists is done, so a run
killed by a captcha or a closed laptop resumes where it stopped, and a mapping
bug in the parser is fixed by re-running `export` -- never by crawling again.
Raw files are immutable: nothing downstream ever rewrites them.

Layout (one folder per run, named by the day it started):

    data/raw/shopee/20260910/run.json                  run metadata (keyword, domain, versions)
    data/raw/shopee/20260910/search/page_00.json       search / keyword pages
    data/raw/shopee/20260910/items/<shopid>_<itemid>.json
    data/raw/shopee/20260910/candidates.json
    data/raw/shopee/20260910/failures.json

`run.json` was added by the platform refactor. Runs made before it have no
`run.json` and are still readable: their keyword comes from candidates.json (or
from the command line at export time).
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ecommerce.settings import package_version, project_home

RAW_SCHEMA_VERSION = 1


def default_raw_dir() -> Path:
    return project_home() / "data" / "raw"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj: Any) -> None:
    """Write via a temp file + rename so a crash never leaves half a JSON file.

    A truncated file would otherwise count as "done" for the resume logic and
    then blow up in the parser.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_sort_key(name: str) -> tuple[str, int]:
    """'20260910_10' must sort after '20260910_9' (plain string sort gets it wrong)."""
    day, _, suffix = name.partition("_")
    return day, int(suffix) if suffix.isdigit() else 1


class RunStore:
    """Paths and helpers for one crawl run of one platform."""

    def __init__(self, platform: str, run_id: str, root: Path | None = None):
        self.platform = platform
        self.run_id = run_id
        self.root = root or default_raw_dir()
        self.dir = self.root / platform / run_id

    # ---- run selection -------------------------------------------------
    @classmethod
    def list_runs(cls, platform: str, root: Path | None = None) -> list[RunStore]:
        """Every run of a platform, oldest first."""
        root = root or default_raw_dir()
        base = root / platform
        if not base.is_dir():
            return []
        names = sorted((p.name for p in base.iterdir() if p.is_dir()), key=_run_sort_key)
        return [cls(platform, name, root) for name in names]

    @classmethod
    def latest(cls, platform: str, root: Path | None = None, keyword: str | None = None) -> RunStore | None:
        """The newest run; with `keyword`, the newest run made for that keyword.
        Runs without run.json (made before the refactor) match any keyword."""
        runs = cls.list_runs(platform, root)
        if keyword:
            runs = [r for r in runs if r.keyword in (None, keyword)]
        return runs[-1] if runs else None

    @classmethod
    def new(cls, platform: str, root: Path | None = None, keyword: str | None = None,
            domain: str | None = None, extra: dict[str, Any] | None = None) -> RunStore:
        run_id = datetime.now().strftime("%Y%m%d")
        store = cls(platform, run_id, root)
        suffix = 1
        while store.dir.exists() and any(store.dir.iterdir()):
            suffix += 1
            store = cls(platform, f"{run_id}_{suffix}", root)
        store.dir.mkdir(parents=True, exist_ok=True)
        store.write_meta(keyword=keyword, domain=domain, **(extra or {}))
        return store

    # ---- run metadata --------------------------------------------------
    @property
    def meta_path(self) -> Path:
        return self.dir / "run.json"

    def write_meta(self, **fields: Any) -> dict[str, Any]:
        meta = {
            "run_id": self.run_id, "platform": self.platform,
            "created_at": utc_now_iso(), "raw_schema_version": RAW_SCHEMA_VERSION,
            "package_version": package_version(),
            **{k: v for k, v in fields.items() if v is not None},
        }
        write_json(self.meta_path, meta)
        return meta

    def load_meta(self) -> dict[str, Any]:
        """run.json, or what can be recovered from candidates.json for old runs."""
        if self.meta_path.exists():
            return read_json(self.meta_path)
        meta: dict[str, Any] = {"run_id": self.run_id, "platform": self.platform, "legacy": True}
        if self.candidates_path.exists():
            cands = read_json(self.candidates_path)
            if cands.get("keyword"):
                meta["keyword"] = cands["keyword"]
        return meta

    @property
    def keyword(self) -> str | None:
        return self.load_meta().get("keyword")

    @property
    def domain(self) -> str | None:
        return self.load_meta().get("domain")

    # ---- search pages --------------------------------------------------
    def search_path(self, page: int) -> Path:
        return self.dir / "search" / f"page_{page:02d}.json"

    @property
    def search_end_path(self) -> Path:
        """Marker: Shopee said there are no more results after the last page."""
        return self.dir / "search" / "_end.json"

    def iter_search_pages(self) -> Iterator[tuple[int, dict]]:
        folder = self.dir / "search"
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("page_*.json")):
            yield int(path.stem.split("_")[1]), read_json(path)

    # ---- product pages -------------------------------------------------
    def item_path(self, shopid: int | str, itemid: int | str) -> Path:
        return self.dir / "items" / f"{shopid}_{itemid}.json"

    def has_item(self, shopid, itemid) -> bool:
        return self.item_path(shopid, itemid).exists()

    def iter_items(self) -> Iterator[dict]:
        folder = self.dir / "items"
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.json")):
            yield read_json(path)

    # ---- bookkeeping ---------------------------------------------------
    @property
    def candidates_path(self) -> Path:
        return self.dir / "candidates.json"

    @property
    def failures_path(self) -> Path:
        return self.dir / "failures.json"

    def load_failures(self) -> dict[str, str]:
        return read_json(self.failures_path) if self.failures_path.exists() else {}

    def record_failure(self, key: str, reason: str) -> None:
        failures = self.load_failures()
        failures[key] = reason
        write_json(self.failures_path, failures)

    def clear_failure(self, key: str) -> None:
        failures = self.load_failures()
        if failures.pop(key, None) is not None:
            write_json(self.failures_path, failures)
