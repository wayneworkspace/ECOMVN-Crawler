# Raw (bronze) layer layout

```
data/raw/<platform>/<run_id>/
├── run.json             run metadata (added by the platform refactor)
├── candidates.json      discovery result: keyword, kept[], excluded[] with reasons, goal, built_at
├── failures.json        {"<a>_<b>": "reason"} for product pages that could not be captured
├── search/
│   ├── page_00.json     Shopee: {"url", "page", "scraped_at", "request_url", "payload": <search_items JSON>}
│   ├── page_001.json    TikTok: {"slug", "path", "fetched_at", "products": [...], "related": [...]}
│   └── _end.json        marker: the site said there are no more results
└── items/
    └── <a>_<b>.json     Shopee: <shopid>_<itemid>: {"candidate", "pdp", "ratings", "shop", "sku_stock"?, "scraped_at"}
                         TikTok: <seller_id>_<product_id>: {"candidate", "product_info", "route", "scraped_at"}
```

`run_id` is the start date `yyyymmdd`, suffixed `_2`, `_3`… when several runs
start the same day. Runs sort by date then suffix (`20260910_10` after `20260910_9`).

## run.json

```json
{
  "run_id": "20260914",
  "platform": "shopee",
  "created_at": "2026-09-14T03:05:11+00:00",
  "raw_schema_version": 1,
  "package_version": "0.1.0",
  "keyword": "bình giữ nhiệt",
  "domain": "giu_nhiet",
  "target": 200
}
```

Runs created before `run.json` existed are still valid: `RunStore.load_meta()`
recovers the keyword from `candidates.json` and marks the run `"legacy": true`.
`RunStore.latest(platform, keyword=...)` treats such runs as matching any keyword.

## Rules

* Files are written atomically (temp file + rename) and never modified afterwards.
* A product whose file exists is *done*: that is how `resume` works.
* Everything downstream (contracts, parsers, Excel) reads only these files, so
  any transformation bug is fixed by re-running `export`, never by re-crawling.
* `ecommerce check-schema` compares the files of a run with
  `src/ecommerce/contracts/<platform>.py` and the baseline in `contracts/baselines/`.
