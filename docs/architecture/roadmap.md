# Roadmap — layers not yet built

Decision taken at migration time: **only what already existed in the source is
implemented; missing layers are documented, not scaffolded.** This page fixes the
direction chosen for each, so later work slots into the current layout without
re-deciding.

Phase numbering follows [`SYSTEM_SPEC.md`](SYSTEM_SPEC.md) §20.

## Phase 1 — Foundation ✅ (this release)

Package, `pyproject.toml`, CLI, modular architecture, Shopee + TikTok adapters,
keyword-based crawl, platform-specific schema (contracts), raw JSON storage with
run metadata, basic validation, existing Excel export driven by YAML.

## Phase 2 — Data platform

Chosen direction: **lightweight local first, same interfaces later on a server.**

| Item | Direction | Where it plugs in |
|---|---|---|
| Operational DB (crawl runs, errors, latest snapshot) | SQLite via SQLAlchemy, swappable to PostgreSQL by connection string. Tables: `crawl_runs`, `crawl_errors`, `products_latest`, `skus_latest`. | New package `src/ecommerce/storage/`. `RunStore.write_meta` / `record_failure` gain a second sink; `build_dataset` result is upserted after export. |
| Analytical store / history | Parquet files under `data/processed/<platform>/<yyyy>/<mm>/<dd>/` (products, skus, prices, inventory, ratings) queried with DuckDB. One file per run = the snapshot history the spec asks for (price / stock timelines). | `consumption/parquet.py` reading `Dataset`; `Product.to_row()` already yields flat records. |
| Bronze/Silver/Gold separation | Bronze = `data/raw/` (exists). Silver = Parquet platform datasets. Gold = DuckDB views / marts (`price_history`, `inventory_history`, `market_metrics`). | `db/schemas/{bronze,silver,gold}.sql` for the DuckDB views. |
| Data quality metrics | Persist per run: completeness per field, validity failures, dedup count, block rate. Anomaly rules (price +500 %, negative stock) as a `quality/` module producing a report row. | Hook after `build_dataset`; store in `crawl_runs`. |
| Idempotency / dedup | Already file-based per run. A Bloom filter / Redis set only matters for continuous crawling; defer until a scheduler exists. | `ingestion/dedup/` |

## Phase 3 — Production pipeline

Chosen direction: **Prefect** (runs locally without a server, Windows-friendly,
DAG = Python). Airflow remains possible later because every step is already a
pure function of `(store, cfg)`.

| Item | Direction |
|---|---|
| Flow | `flows/crawl_flow.py`: `discover → crawl_detail → crawl_sku → validate(check-schema) → transform → load_silver → build_gold → quality_check → publish(excel)`. Each task calls the same functions the CLI calls. |
| Scheduling | Prefect deployments (daily per platform × keyword). n8n only as an external trigger calling the CLI / a webhook. |
| Monitoring | Prefect run states + a `metrics` table; alerts (email/Slack) from a Prefect notification on failure, high block rate (`failures / crawled`), schema drift (`check-schema` non-zero exit), stale data. |
| Backfill / re-run | `export` and `build_dataset` are already replayable from raw; a `replay` task re-processes a date range of runs. |
| Docker | `docker/docker-compose.yml` for Prefect server + PostgreSQL + MinIO. The **crawler itself stays on a desktop with a real browser** (attach mode needs a GUI Chrome and a logged-in profile); only storage/orchestration move into containers. |
| Schema drift detection | Exists as `contracts/`; wire `check-schema --save-baseline` into the flow after a verified-good run. |

## Phase 4 — Multi-platform

Lazada (and others): follow "Adding a platform" in the README. The canonical
model becomes worthwhile once a third platform exists: keep `Product` as the
platform dataset shape and add `domain/canonical.py` (`CanonicalProduct`,
`CanonicalSku`, `CanonicalPrice`) with an explicit, optional mapping per platform.
Never bend a platform parser to the canonical shape.

## Phase 5 — Intelligence

| Item | Direction |
|---|---|
| Data API | FastAPI over the Gold layer (DuckDB/SQLite): `/products`, `/prices/{id}/history`, `/runs`, `POST /crawl` (enqueues a Prefect run). |
| Web UI | Minimal internal page on the same FastAPI app: trigger a crawl, watch `status`, download the Excel. |
| Business metrics | Computed upstream in Gold (market share by shop, price bands, sales velocity from cumulative sold deltas between runs) so Excel, BI and the API read the same numbers. |
| BI | Power BI / Looker on Parquet or PostgreSQL. |
| AI agent | Microsoft Agent Framework (Python) + Claude, tools = read-only queries on Gold (`query_products`, `price_history`, `top_movers`); Discord/Slack front-end per the maf-discord-agent template. |
| ML | Demand forecasting / price optimisation notebooks on the Parquet history; not before ≥ 30 daily snapshots exist. |

## Non-goals for now

* Headless / cloud crawling of Shopee — blocked by captcha rendering (decisions #2, #21).
* Review text extraction — the page only serves featured reviews (decision log).
