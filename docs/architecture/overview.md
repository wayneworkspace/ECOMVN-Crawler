# System Architecture Overview (15-Minute Technical Review)

This platform implements a multi-platform e-commerce data pipeline designed for long-term maintainability, offline replayability, and anti-scraping resilience.

> **Design Core**: *"Platform-specific at the edge, unified at the core, independent at consumption."*

---

## 1. Core Architecture Layers

| Layer | Responsibility | Key Files |
|---|---|---|
| **User Input / CLI** | CLI orchestrator (`crawl`, `export`, `probe`, `status`, `check-schema`) and typed Pydantic configuration. | `src/ecommerce/cli.py`<br>`src/ecommerce/settings.py` |
| **Ingestion (Bronze)** | Controls Chrome/Edge in attach mode via Patchright; intercepts raw API JSON payloads; stores immutable responses in `data/raw/`. | `src/ecommerce/ingestion/browser.py`<br>`src/ecommerce/ingestion/raw_store.py` |
| **Data Quality / Contracts** | Real-time circuit breaker (`SchemaGuard`) that halts crawling if API drift is detected; baseline schema regression checkers. | `src/ecommerce/contracts/guard.py`<br>`src/ecommerce/contracts/check.py` |
| **Platform Edge (Adapters)** | Sits behind `PlatformAdapter` ABC. Implements platform-specific crawling and raw JSON parsers (Shopee, TikTok, Lazada). | `src/ecommerce/platforms/base.py`<br>`src/ecommerce/platforms/<platform>/` |
| **Canonical Domain (Silver)** | Platform-agnostic `Product` model, rule-based domain category filters, and regex specification extractors. | `src/ecommerce/domain/product.py`<br>`src/ecommerce/transformation/` |
| **Consumption (Gold)** | Report generation engine reading layout YAMLs (`configs/reports/`) and outputting Excel workbooks with embedded thumbnails. | `src/ecommerce/consumption/excel/excel.py` |

---

## 2. End-to-End Data Pipeline Flow

```
[CLI Request]
      │
      ▼
[Ingestion Layer] ──► Intercept XHR JSON ──► Store Raw File (Bronze: data/raw/<platform>/<run>/)
      │                                                │
      ▼                                                │ (Immutable Replay)
[Data Contract Guard] ◄────────────────────────────────┘
      │
      ▼
[Platform Adapter & Parsers] ──► Parse Raw JSON ──► Unified Product Model (Pydantic)
      │                                                       │
      ▼                                                       ▼
[Transformation] ──► Domain Category Filters + Regex Specification Extractor
      │                                                       │
      ▼                                                       ▼
[Consumption Layer] ──► Excel Layout Engine (YAML) ──► Output Workbooks (.xlsx)
```

---

## 3. Key Design Decisions & Guiding Principles

1. **No Brittle CSS Scraping**: The pipeline attaches to real browsers and intercepts background XHR/Fetch API calls directly (`search_items`, `get_pc`, `__MODERN_ROUTER_DATA__`, `__moduleData__`).
2. **Immutable Raw Data First**: Every raw payload is stored verbatim in `data/raw/`. This acts as a checkpoint and enables instant offline exports without re-crawling.
3. **Circuit Breaker Schema Drift Guard**: If a platform modifies its internal API, the runner pauses automatically to prevent corrupting downstream data.
