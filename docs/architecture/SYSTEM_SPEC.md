# E-commerce Data Engineering System — System Specification

## 1. Purpose

Build a multi-platform E-commerce Data Engineering System that can collect data from multiple e-commerce platforms, preserve platform-specific raw data and schemas, validate and transform the data, store historical datasets, and expose the resulting data to business and AI consumers.

The system must be:

- **Platform-specific at the edge**
- **Platform-agnostic at the core**
- **Configurable by crawl keyword without changing source code**
- **Extensible to new platforms**
- **Resilient to network/source failures**
- **Data-quality aware**
- **Historically traceable**
- **Installable as a Python package**
- **Consumable through Excel, API, BI, ML and AI agents**

---

## 2. Core Design Principles

### 2.1 Platform-specific at the edge

Each platform owns its own:

- crawl configuration
- schema
- extraction rules
- parser
- validation rules
- pagination behavior
- platform-specific business fields

Example:

```text
Shopee
├── shopee.yaml
├── schema.yaml
├── extractor.py
├── parser.py
└── validator.py

TikTok
├── tiktok.yaml
├── schema.yaml
├── extractor.py
├── parser.py
└── validator.py
```

A change in Shopee's response structure must not require changes to TikTok or Lazada.

### 2.2 Keyword is runtime input

The normal user workflow is:

```bash
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt"
```

Changing the keyword must not require changing Python source code or platform schema.

### 2.3 Schema belongs to the platform

The user does **not** select arbitrary fields for every crawl.

Instead:

```text
User
  └── platform + keyword + crawl parameters

Platform
  └── owns schema + extraction + validation
```

This keeps crawl configuration simple and protects platform-specific data contracts.

### 2.4 Raw data is immutable

The original response must be retained in the Bronze/Raw layer whenever configured.

Raw data is never overwritten by transformation.

### 2.5 Consumption is independent

Excel layout, number of sheets, columns, formatting and report structure belong to the Consumption Layer.

Changing Excel output must not require changing ingestion or storage logic.

---

# 3. High-Level Architecture

```text
                         E-COMMERCE DATA ENGINEERING SYSTEM

 User / Scheduler
       |
       | platform + keyword + crawl parameters
       v
+-----------------------+
| PLATFORM EDGE         |
|-----------------------|
| Shopee                |
| TikTok Shop           |
| Lazada                |
| Other Platforms       |
|                       |
| config + schema       |
| extractor + parser   |
| validator             |
+-----------+-----------+
            |
            v
+-----------------------+
| INGESTION             |
|-----------------------|
| Browser / API         |
| Rate Limiter          |
| Retry / Backoff       |
| Block Detector        |
| Idempotency           |
| Dedup / Bloom Filter  |
+-----------+-----------+
            |
            v
+-----------------------+
| BRONZE / RAW          |
|-----------------------|
| Raw response          |
| Request metadata      |
| Crawl run             |
| Timestamp             |
| Source metadata       |
+-----------+-----------+
            |
            v
+-----------------------+
| DATA QUALITY          |
|-----------------------|
| Schema validation     |
| Deduplication         |
| Completeness          |
| Validity              |
| Anomaly detection     |
| Schema drift          |
+-----------+-----------+
            |
            v
+-----------------------+
| SILVER / TRANSFORM    |
|-----------------------|
| Parse                 |
| Normalize             |
| Enrich                |
| Platform dataset      |
+-----------+-----------+
            |
            +--------------------+
            |                    |
            v                    v
+-----------------------+   +-----------------------+
| PLATFORM DATASET      |   | CANONICAL MODEL       |
| Platform-specific     |   | Optional cross-       |
| analytical data       |   | platform mapping      |
+-----------+-----------+   +-----------+-----------+
            |                           |
            +-------------+-------------+
                          v
                +-----------------------+
                | GOLD / STORAGE        |
                |-----------------------|
                | PostgreSQL            |
                | S3 / MinIO / Parquet  |
                | Analytics DB          |
                +-----------+-----------+
                            |
                            v
                +-----------------------+
                | CONSUMPTION           |
                |-----------------------|
                | Excel                 |
                | Dashboard             |
                | BI                    |
                | REST API              |
                | ML / Analytics        |
                | AI Agents             |
                | Alerts                |
                +-----------------------+

Cross-cutting:
- Orchestration & Scheduling
- Observability & Monitoring
- Data Governance
- Security & Configuration
```

---

# 4. Layer Specifications

## 4.1 User Input Layer

### Responsibilities

Accept runtime crawl parameters.

### Required parameters

```yaml
platform: shopee
keyword: "bình giữ nhiệt"
```

### Optional parameters

```yaml
max_products: 1000
max_pages: 20
sort: sales
schedule: daily
output: excel
```

### Interfaces

CLI:

```bash
ecommerce crawl \
  --platform shopee \
  --keyword "bình giữ nhiệt" \
  --max-products 1000
```

Future interfaces:

- Web UI
- REST API
- Airflow/Prefect job
- n8n workflow

---

# 5. Platform Edge

## 5.1 Platform Registry

A registry maps platform names to platform adapters.

Conceptual interface:

```python
class PlatformAdapter:
    platform: str

    def search(self, keyword, params): ...
    def extract(self, response): ...
    def parse(self, raw): ...
    def validate(self, data): ...
```

Example:

```text
platform = shopee
        |
        v
ShopeeAdapter
```

Adding a new platform should not require rewriting the orchestration pipeline.

---

## 5.2 Platform Configuration

Each platform has its own configuration.

Example:

```text
configs/platforms/shopee/
├── config.yaml
├── schema.yaml
└── rules.yaml
```

Configuration may contain:

- endpoints
- pagination
- sorting
- request behavior
- field mappings
- required fields
- data types
- platform rules
- extraction selectors

Example:

```yaml
platform: shopee

search:
  sort: sales
  max_pages: 20

fields:
  product_id:
    source: item.itemid
    type: integer
    required: true

  title:
    source: item.name
    type: string
    required: true

  price:
    source: item.price
    type: decimal
    required: true
```

Complex extraction logic must remain in Python rather than being forced into YAML.

---

# 6. Ingestion Layer

## Responsibilities

- Fetch source data
- Browser/API interaction
- Rate limiting
- Retry
- Backoff
- Block/CAPTCHA detection
- Request metadata capture
- Idempotency
- Deduplication
- Raw data handoff

### Recommended components

```text
ingestion/
├── browser/
├── sources/
├── resilience/
└── dedup/
```

### Reliability rules

| Error | Action |
|---|---|
| Timeout | Retry |
| Temporary network error | Retry |
| HTTP transient failure | Retry with backoff |
| Block detected | Cooldown |
| CAPTCHA | Stop/pause according to policy |
| Schema drift | Quarantine / alert |
| Invalid data | Quarantine |
| Storage failure | Retry |
| Permanent parse failure | Record error |

---

# 7. Bronze / Raw Layer

## Purpose

Preserve source truth and enable pipeline replay.

Recommended storage:

```text
data/raw/
└── shopee/
    └── 2026/
        └── 09/
            └── 14/
                ├── search/
                └── product/
```

Each raw record should have associated metadata:

```text
crawl_run_id
platform
keyword
endpoint
request timestamp
response timestamp
request parameters
source URL
HTTP metadata where permitted
schema version
```

Raw data should be immutable.

---

# 8. Data Quality Layer

## 8.1 Schema Validation

Validate raw response against the platform's schema.

## 8.2 Deduplication

Deduplicate using stable identifiers such as:

```text
platform + product_id
platform + shop_id
platform + sku_id
```

## 8.3 Completeness

Measure fields such as:

```text
price completeness
stock completeness
rating completeness
shop completeness
```

## 8.4 Validity

Examples:

```text
price >= 0
rating between 0 and 5
stock >= 0
review_count >= 0
```

## 8.5 Anomaly Detection

Detect suspicious changes:

```text
price suddenly increases 500%
stock suddenly becomes negative
sales drops unexpectedly
```

## 8.6 Schema Drift

Detect source changes such as:

```text
item.price
      ↓
item.price_info.current_price
```

Schema drift should generate an alert and preserve the failing raw payload for investigation.

---

# 9. Silver / Transformation Layer

## Responsibilities

- Parse platform-specific data
- Normalize types
- Standardize units/formats
- Enrich data
- Apply business rules
- Produce platform datasets

Example:

```text
Shopee raw
   ↓
Shopee parser
   ↓
Shopee normalized dataset
```

The transformation layer may produce:

```text
products
sku
shops
categories
prices
inventory
ratings
sales
```

---

# 10. Canonical Data Model

The canonical model is **optional**, not mandatory for every use case.

Its purpose is cross-platform analytics.

Example:

```text
Canonical Product
├── product_id
├── platform
├── title
├── category_id
├── shop_id
└── ...

Canonical SKU
├── sku_id
├── product_id
├── name
└── ...

Canonical Price
├── sku_id
├── timestamp
├── original_price
└── selling_price
```

Important rule:

```text
Platform Schema
      |
      v
Platform Dataset
      |
      | optional mapping
      v
Canonical Dataset
```

Never force the platform schema to look like the canonical model.

---

# 11. Gold / Storage Layer

## PostgreSQL

Use for:

- operational metadata
- crawl runs
- crawl errors
- latest structured snapshots
- relational entities
- API serving

## S3 / MinIO + Parquet

Use for:

- historical datasets
- large analytical datasets
- replay
- archival
- ML/analytics workloads

## Analytics Database

Optional.

Candidates:

- ClickHouse
- BigQuery
- Redshift

Use when analytical query volume justifies it.

---

# 12. Historical Data

Do not store only the current state.

Create snapshots.

Example:

```text
product_id | timestamp  | price  | stock
-----------|------------|--------|------
123        | 2026-09-14 | 199000 | 83
123        | 2026-09-15 | 189000 | 71
123        | 2026-09-16 | 179000 | 42
```

This enables:

- price history
- inventory history
- sales velocity
- trend analysis
- promotion detection
- competitor monitoring

---

# 13. Consumption Layer

Consumption is intentionally isolated.

## Excel

Excel specification can change independently.

Example:

```yaml
workbook: ecommerce_report.xlsx

sheets:
  - name: Executive Summary
    source: market_metrics

  - name: Products
    source: products

  - name: Pricing
    source: price_history

  - name: Inventory
    source: inventory
```

Changing:

```text
5 sheets → 10 sheets
```

must not require changes to the scraper.

Excel is responsible for:

- sheet layout
- columns
- formatting
- formulas
- charts
- hyperlinks
- conditional formatting

Business metrics should be calculated upstream.

## Other consumers

```text
Dashboard
BI
REST API
ML
AI Agents
Alerts
```

---

# 14. Orchestration

The pipeline should eventually be executable as a DAG.

Example:

```text
discover
   ↓
crawl_pdp
   ↓
crawl_sku
   ↓
save_raw
   ↓
validate
   ↓
transform
   ↓
load_silver
   ↓
build_gold
   ↓
quality_check
   ↓
publish
```

Supported orchestration options:

- Airflow
- Prefect
- n8n for external workflow automation

The first MVP can run without Airflow.

---

# 15. Observability

Track at least:

```text
crawl_runs
success_count
failure_count
duration
throughput
latency
block_rate
error_rate
data_freshness
data_quality
```

Example run:

```text
RUN 20260914_001

platform: shopee
keyword: bình giữ nhiệt

discovered: 1842
crawled: 400
failed: 19
blocked: 2
duration: 27m
```

Alerts:

- pipeline failure
- high block rate
- schema drift
- stale data
- abnormal price distribution
- high data loss

---

# 16. Data Governance

Track:

- data catalog
- schema version
- data lineage
- source metadata
- retention policy
- ownership
- access control

Example lineage:

```text
Shopee API
  ↓
raw/shopee/2026/09/14
  ↓
silver/shopee/products
  ↓
gold/pricing_mart
  ↓
Excel / Dashboard / AI API
```

---

# 17. Security

Secrets must not be stored in source code.

Use:

```text
.env
secret manager
environment variables
```

Protect:

- API keys
- database credentials
- proxy credentials
- authentication secrets

Audit sensitive operations.

---

# 18. Python Package

The repository must be installable as a Python package.

Expected workflow:

```bash
pip install -e .
```

Build:

```bash
python -m build
```

Output:

```text
dist/
├── ecommerce_data_platform-0.1.0-py3-none-any.whl
└── ecommerce_data_platform-0.1.0.tar.gz
```

CLI entry point:

```bash
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt"
```

---

# 19. Target Repository Structure

```text
ecommerce-data-platform/
│
├── README.md
├── LICENSE
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
│
├── configs/
│   ├── app.yaml
│   ├── logging.yaml
│   │
│   ├── platforms/
│   │   ├── shopee/
│   │   │   ├── config.yaml
│   │   │   ├── schema.yaml
│   │   │   └── rules.yaml
│   │   ├── tiktok/
│   │   │   ├── config.yaml
│   │   │   ├── schema.yaml
│   │   │   └── rules.yaml
│   │   └── lazada/
│   │       ├── config.yaml
│   │       ├── schema.yaml
│   │       └── rules.yaml
│   │
│   └── jobs/
│       └── crawl.yaml
│
├── src/
│   └── ecommerce/
│       ├── api/
│       ├── domain/
│       ├── ingestion/
│       ├── raw/
│       ├── quality/
│       ├── transformation/
│       ├── storage/
│       ├── analytics/
│       ├── orchestration/
│       ├── observability/
│       ├── security/
│       └── consumption/
│           ├── excel/
│           ├── dashboard/
│           ├── bi/
│           └── alerts/
│
├── dags/
│
├── db/
│   ├── migrations/
│   ├── seeds/
│   └── schemas/
│       ├── bronze.sql
│       ├── silver.sql
│       └── gold.sql
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── marts/
│
├── exports/
│   ├── excel/
│   ├── csv/
│   └── reports/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── scripts/
│   ├── build.py
│   ├── clean.py
│   ├── bootstrap.py
│   ├── run_crawler.py
│   └── validate_data.py
│
└── docs/
    ├── architecture/
    ├── data/
    └── decisions/
```

---

# 20. MVP Scope

Do not implement everything at once.

## Phase 1 — Foundation

- [ ] Python package
- [ ] `pyproject.toml`
- [ ] CLI
- [ ] Modular architecture
- [ ] Shopee adapter
- [ ] Keyword-based crawl
- [ ] Platform-specific schema
- [ ] Raw JSON storage
- [ ] Basic validation
- [ ] Existing Excel export

## Phase 2 — Data Platform

- [ ] PostgreSQL
- [ ] Bronze/Silver/Gold separation
- [ ] Historical snapshots
- [ ] Crawl run tracking
- [ ] Data quality metrics
- [ ] Parquet
- [ ] Redis
- [ ] Idempotency
- [ ] Bloom filter

## Phase 3 — Production Pipeline

- [ ] Airflow/Prefect
- [ ] DAGs
- [ ] Monitoring
- [ ] Alerts
- [ ] Data lineage
- [ ] Schema drift detection
- [ ] Backfill/re-run
- [ ] Docker

## Phase 4 — Multi-platform

- [ ] TikTok adapter
- [ ] Lazada adapter
- [ ] Platform-specific schemas
- [ ] Platform-specific datasets
- [ ] Optional canonical model
- [ ] Cross-platform analytics

## Phase 5 — Intelligence

- [ ] REST Data API
- [ ] Business metrics
- [ ] Dashboard
- [ ] ML analytics
- [ ] AI Agent
- [ ] n8n integration

---

# 21. Definition of Done

The system is considered a successful E-commerce Data Engineering Platform when:

1. A new crawl can be started by changing the keyword/config, not Python source.
2. Each platform maintains its own schema and extraction logic.
3. A platform schema change does not break unrelated platforms.
4. Raw responses can be replayed without crawling again.
5. Data quality failures are detectable and traceable.
6. Historical product/price/inventory states are preserved.
7. Excel layout can be changed independently from ingestion.
8. A new platform can be added without rewriting the core pipeline.
9. The application can be installed as a Python package.
10. The same processed data can serve Excel, BI, API, ML and AI consumers.

---

# 22. Architectural Principle

The most important rule of this system is:

```text
                PLATFORM-SPECIFIC
                       │
                       │
       ┌───────────────┴───────────────┐
       │                               │
    Shopee                           TikTok
    schema                            schema
    parser                            parser
    rules                             rules
       │                               │
       └───────────────┬───────────────┘
                       │
                       ▼
              PLATFORM DATASETS
                       │
                       ▼
               COMMON DATA CORE
                       │
                       ▼
                 GOLD / METRICS
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
        Excel         API          AI
```

**Specific at the edge. Unified at the core. Independent at consumption.**
