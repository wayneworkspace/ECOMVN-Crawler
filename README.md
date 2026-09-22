# Multi-Platform E-Commerce Data Pipeline

A resilient, multi-platform e-commerce data engineering pipeline that crawls product data from Shopee Việt Nam, TikTok Shop Việt Nam, and Lazada Việt Nam for any keyword, keeps raw API responses immutable in a Bronze layer, validates and transforms them into a unified canonical model, and exports formatted Excel reports with embedded product images.

Techstack
Python 3.10+ | Patchright (Playwright) | Pydantic v2 | XlsxWriter | PyYAML | Pytest | Ruff

---

## Overview

**Problem** — Modern e-commerce platforms (Shopee, TikTok Shop, Lazada) constantly change CSS selectors, hash class names, and deploy anti-scraping blocks (captchas, login walls). Extracting structured product data manually or using brittle HTML scrapers leads to high maintenance overhead, lost progress when blocked, and inconsistent data across platforms.

**Solution** — An enterprise data engineering pipeline designed with the philosophy: *"Platform-specific at the edge, unified at the core, independent at consumption."* The tool attaches to real browser sessions (Chrome/Edge), listens directly to XHR/Fetch JSON responses from internal APIs instead of parsing HTML/CSS, stores raw JSON immutably in a Bronze layer (allowing offline replay and zero-re-crawl exports), enforces real-time schema drift contracts, transforms data into a Pydantic canonical domain model, and outputs structured Excel deliverables.

**Data Flow** — CLI Request (`ecommerce crawl`) → Attach Browser (Patchright) → Raw JSON Store (`data/raw/<platform>/<run_id>/`) → Data Contract Guard → Unified Product Model (`src/ecommerce/domain/product.py`) → Domain Filter & Spec Extractor → Formatted Excel Export (`output/<platform>/<filename>.xlsx`).

---

## Architecture

Source → Ingestion → Processing → Storage

- **Source** — The user initiates a crawl or export via the `ecommerce` CLI specifying `--platform`, `--keyword`, `--domain`, and `--max-products`.
- **Ingestion** — Real Chrome/Edge browser in *Attach Mode* navigates search and product pages, intercepted by Patchright network listeners. Raw API payloads (`search_items`, `pdp/get_pc`, `__MODERN_ROUTER_DATA__`, `window.__moduleData__`) are saved immutably as JSON files under `data/raw/<platform>/<run_id>/` (Bronze Layer).
- **Processing** — Raw JSON responses are validated against schema drift contracts (`src/ecommerce/contracts/`). Platform parsers translate raw JSON into a unified Pydantic `Product` canonical model. Domain profiles (`configs/domains/*.yaml`) apply rule-based filtering (keeping relevant products, discarding off-category items) and extract regex specifications (capacity, material, dimensions, features).
- **Storage** — Output Excel reports (`.xlsx`) are generated in `output/` using `XlsxWriter`, featuring multiple sheets (Platform summary, SKU Detail, Checklist, Dropped items, Crawl errors, Run Info), custom styling, and embedded thumbnails.

---

## Project Structure

```text
ecommerce-data-platform/
├── README.md
├── pyproject.toml
├── .env.example
├── configs/
│   ├── app.yaml
│   ├── platforms/
│   │   ├── shopee/config.yaml
│   │   ├── tiktok/config.yaml
│   │   └── lazada/config.yaml
│   ├── domains/
│   │   └── giu_nhiet.yaml
│   └── reports/
│       └── default.yaml
├── docs/
│   └── architecture/
│       ├── dependency_graph.md
│       └── refactoring_proposal.md
├── src/
│   └── ecommerce/
│       ├── cli.py
│       ├── settings.py
│       ├── ingestion/
│       │   ├── browser.py
│       │   ├── raw_store.py
│       │   └── images.py
│       ├── contracts/
│       │   ├── guard.py
│       │   ├── check.py
│       │   ├── rules.py
│       │   ├── shopee.py
│       │   ├── tiktok.py
│       │   └── lazada.py
│       ├── domain/
│       │   ├── product.py
│       │   ├── candidate.py
│       │   ├── dataset.py
│       │   └── profile.py
│       ├── platforms/
│       │   ├── base.py
│       │   ├── common/
│       │   │   └── helpers.py
│       │   ├── shopee/
│       │   ├── tiktok/
│       │   └── lazada/
│       ├── transformation/
│       │   ├── filters.py
│       │   └── specs/
│       └── consumption/
│           └── excel/
├── tests/
└── tools/
```

`cli.py` is the orchestrator: it handles user commands (`crawl`, `export`, `probe`, `status`, `check-schema`) and coordinates `ingestion` → `contracts` → `platforms` → `transformation` → `consumption`.

---

## Quick Start

### Prerequisites

- Python 3.10+
- Google Chrome or Microsoft Edge installed on Windows/Linux/macOS.

### Setup

```bash
git clone <repo-url>
cd ecommerce-data-platform
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[crawler,dev]"
```

### Running Commands

```bash
# 1. Login once (for Shopee or Lazada captcha sessions)
ecommerce login --platform shopee

# 2. Probe run (try 20 products to test session and extraction)
ecommerce probe --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet

# 3. Full crawl (saves raw JSON to data/raw/shopee/<run_id>/)
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet

# 4. Replay Export (generates Excel report offline from Bronze raw files without re-crawling)
ecommerce export --platform shopee --keyword "bình giữ nhiệt"
```

---

## Configuration (`configs/`)

All system settings are organized in YAML files and validated at startup using Pydantic models:

| YAML Path | Description |
|---|---|
| `configs/app.yaml` | Global settings: timeouts, default platform/domain, raw data paths, export sizes. |
| `configs/platforms/<name>/config.yaml` | Platform-specific settings: browser profiles, pacing delay ranges, page limits, SKU stock parameters. |
| `configs/domains/<name>.yaml` | Domain knowledge profile: title filter terms (keep/drop), attribute vocabularies (materials, features), search discovery rules. |
| `configs/reports/default.yaml` | Report presentation layout: sheet order, active columns, per-platform styling, checklist definitions. |

---

## Troubleshooting & Limitations

- **Browser Captcha / Anti-Bot Block** — When a captcha puzzle or security check appears, the tool automatically pauses execution and prints instructions in the console. Solve the puzzle manually in the open Chrome window and press `Enter` to resume crawling seamlessly.
- **Schema Drift Error** — If a platform updates its internal API response format, `guard.py` triggers a circuit breaker after 3 consecutive invalid items to prevent corrupting data. Run `ecommerce check-schema` to inspect missing keys against baselines in `src/ecommerce/contracts/baselines/`.
- **Shopee Variation Rate Limits** — Shopee rate-limits accounts that query too many SKU variation combinations in short intervals. Use split-pass crawling (`ecommerce crawl --pass 1` then `--pass 2`) to separate product detail extraction from per-SKU stock queries.
- **Offline Export Replay** — Since every captured page is stored immutably in `data/raw/`, you can modify report layouts in `configs/reports/default.yaml` or update parser regex rules and re-run `ecommerce export` instantly without hitting web servers again.
