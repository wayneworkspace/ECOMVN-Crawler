# E-commerce Data Platform

Multi-platform e-commerce data engineering system. Crawls product data from
Shopee Việt Nam, TikTok Shop Việt Nam and Lazada Việt Nam for any keyword, keeps the raw responses
immutable, validates and transforms them per platform, and exports the result to
Excel (one row per product, one row per SKU, embedded pictures).

**Platform-specific at the edge, unified at the core, independent at consumption.**

```
ecommerce crawl  --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet --max-products 200
ecommerce export --platform shopee --keyword "bình giữ nhiệt"
```

This release is the migration of the proven single-purpose crawler into the
platform layout described in [`docs/architecture/overview.md`](docs/architecture/overview.md).
The layers that exist run for real and are tested (274 unit + integration tests);
the layers that do not exist yet are documented, not scaffolded — see
[`docs/architecture/roadmap.md`](docs/architecture/roadmap.md).

---

## What you get

| Layer | Where | What it does |
|---|---|---|
| User input | `ecommerce` CLI | `--platform`, `--keyword`, `--domain`, `--max-products`; keyword is a run-time input, never configuration |
| Platform edge | `src/ecommerce/platforms/<name>/` + `configs/platforms/<name>/config.yaml` | Each platform owns its config, extraction, parsers and dataset builder behind one `PlatformAdapter` interface |
| Ingestion | `src/ecommerce/ingestion/` | Real Chrome/Edge in *attach* mode, block / captcha detection, pacing and cooldowns, atomic raw writes |
| Bronze / raw | `data/raw/<platform>/<run>/` | Immutable JSON per captured page + `run.json` metadata; the raw files are the checkpoint and the replay source |
| Data contracts | `src/ecommerce/contracts/` | Which JSON fields each platform must have; schema-drift guard while crawling, `check-schema` against a baseline |
| Transformation | `src/ecommerce/transformation/` + `platforms/<name>/parse/` | Platform parsers → typed `Product` model; domain profile drives the product filter and attribute extraction |
| Consumption | `src/ecommerce/consumption/excel/` + `configs/reports/default.yaml` | Excel layout declared in YAML: sheets, order, columns, per-platform styling |

### Output

`output/<platform>/<prefix>_<platform>_top<N>_<run>_<time>.xlsx`

| Sheet | Content |
|---|---|
| **Shopee** / **TikTok Shop** | 1 row per product: identity → price → sales & stock → rating → attributes → shop → raw text; 3 pictures embedded, all image links in one cell |
| **Detail** | 1 row per SKU: rank · name · SKU picture · ids · the shop's variation groups verbatim · capacity · price · list price · % off · voucher price · stock · status · image link |
| **Checklist đề bài** | Coverage of each requirement of the original brief (domain-specific; disable in the layout for other domains) |
| **Bị loại** | Search results dropped by the domain filter, with the reason |
| **Lỗi crawl** | Products whose page could not be captured |
| **Thông tin** | Keyword, domain, sort order, run id, counts |

Column headers and sheet content are Vietnamese (they are the deliverable); code,
configuration comments and documentation are English.

---

## Install

Requirements: Python 3.10+, Google Chrome or Microsoft Edge (Windows: installed in the default location).

```powershell
cd E-commerce_Scraping
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[crawler,dev]"
ecommerce platforms          # sanity check: lists shopee / tiktok
```

Build a wheel: `python -m build` → `dist/ecommerce_data_platform-0.1.0-py3-none-any.whl`.
An installed wheel works without the repo: it carries a copy of `configs/`; run
`ecommerce init` in any folder to copy them out for editing.

## Run

```powershell
# 1. Log in to Shopee ONCE. A normal browser window opens on the tool's own profile:
#    log in (QR is easiest), reach the home page, then CLOSE that window.
ecommerce login --platform shopee

# 2. Try 20 products, export, open the Excel and compare a few products with the site.
ecommerce probe --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet

# 3. Full run (~11-12 h with the anti-block pacing). `crawl` ALWAYS opens a new run
#    = one snapshot of the top N at that moment. Interrupted? `ecommerce resume ...`.
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt" --domain giu_nhiet

#    Shopee blocks accounts that click many variations -> split in two passes:
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt" --pass 1   # product pages only
ecommerce crawl --platform shopee --keyword "bình giữ nhiệt" --pass 2   # per-SKU stock (Detail sheet)

# 4. Export (any number of times, no browser)
ecommerce export --platform shopee --keyword "bình giữ nhiệt"
```

TikTok Shop needs no login. If a "Security Check" puzzle appears the tool pauses;
solve it in the browser window and press Enter.

```powershell
ecommerce probe  --platform tiktok --keyword "bình giữ nhiệt" --limit 20
ecommerce crawl  --platform tiktok --keyword "bình giữ nhiệt"        # top 200 (~40-60 min)
ecommerce export --platform tiktok --keyword "bình giữ nhiệt"
ecommerce status --platform tiktok
```

Lazada works as a guest; logging in once (`ecommerce login --platform lazada`) means
fewer slider captchas. When a captcha shows, the tool pauses; solve it in the
browser window and press Enter.

```powershell
ecommerce login  --platform lazada                                   # optional
ecommerce probe  --platform lazada --keyword "dầu nhớt xe máy" --limit 20
ecommerce crawl  --platform lazada --keyword "dầu nhớt xe máy"      # top 200 (~1.5 h)
ecommerce export --platform lazada --keyword "dầu nhớt xe máy"
```

All platforms can run at the same time (one terminal and one browser profile each).

Other commands:

```powershell
ecommerce status --platform shopee                 # progress of the latest run
ecommerce resume --platform shopee --keyword "..." # continue an interrupted run
ecommerce export --no-images                       # fast export without pictures
ecommerce inspect 11_111 --part pdp                # key tree of one product's JSON
ecommerce check-schema --platform shopee           # do the saved files still have the fields the tool reads?
ecommerce check-schema --save-baseline             # make this good run the comparison baseline
```

**When a site changes its JSON:** the crawl pauses after 3 consecutive products
missing a core field. Run `check-schema` to see which fields disappeared and the
suggested new names, then follow [`src/ecommerce/contracts/README.md`](src/ecommerce/contracts/README.md).
The raw data is already saved, so after the fix only `export` is needed.

**When a captcha appears:** the tool pauses and prints instructions. Solve it in
the browser window, press Enter, and the same product is retried.

---

## Configuration

```
configs/
├── app.yaml                       shared: default platform / domain, paths, timeouts, export, contracts
├── platforms/
│   ├── shopee/config.yaml         browser profile, pacing, sort, pages, per-SKU stock
│   └── tiktok/config.yaml         browser profile, pacing, keyword-page budget
├── domains/
│   └── giu_nhiet.yaml             domain profile: product filter, attribute vocabularies, TikTok discovery
└── reports/
    └── default.yaml               Excel layout: sheets, order, columns, per-platform styling
```

* **Keyword** — always `--keyword`. Never in YAML.
* **Domain profile** (`--domain`, default `app.yaml: default_domain`) — the
  product-category knowledge: which title nouns to keep / drop ("bình" keeps,
  "túi" drops), material and feature vocabularies, which TikTok keyword pages
  to walk. `--domain none` crawls any keyword with no filtering and no
  attribute extraction. Copy `giu_nhiet.yaml` to make a profile for another category.
* **Report layout** — change the sheet list or column order in
  `configs/reports/default.yaml`; nothing in ingestion or parsing changes.
  Column *values* are computed in `src/ecommerce/consumption/excel/columns.py`.
* All YAML is validated with Pydantic at start-up: a typo or wrong type fails
  immediately with the field name.
* `ECOMMERCE_HOME` (default: current directory) is where `configs/`, `data/`,
  `output/` and browser profiles live. `ECOMMERCE_CHROME_EXECUTABLE` overrides
  the browser binary.

---

## How it works

```
  ecommerce crawl  (platforms/<p>/extract)                    ecommerce export  (parse -> consumption)
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────┐
│ discovery            │   │ product pages        │   │ platforms/<p>/parse/     │   │ consumption/excel    │
│ search / keyword     │──►│ capture the JSON the │──►│ raw JSON -> Product      │──►│ layout YAML -> xlsx  │
│ pages -> candidates  │   │ page itself loads    │   │ + domain profile         │   │                      │
└──────────┬───────────┘   └──────────┬───────────┘   └────────────▲─────────────┘   └──────────────────────┘
           ▼                          ▼                            │
   data/raw/<p>/<run>/search/   data/raw/<p>/<run>/items/  ────────┘   (bronze layer = checkpoint + replay)
```

1. **No HTML/CSS parsing.** The tool opens the real page in Chrome and *listens*
   to the JSON responses the page itself requests (`search_items`, `pdp/get_pc`,
   `get_ratings`). CSS classes are hashed and change every deploy; JSON is stable.
2. **Raw first, transform later.** Every captured page is saved verbatim under
   `data/raw/`. The raw files are the checkpoint (a product with a file is done)
   and the replay source: a parser fix is applied by re-running `export`.
3. **Rank** = position in the platform's own "best selling" order (ads excluded).

Why each technical choice was made, and the failures it avoids:
[`docs/decisions/README.md`](docs/decisions/README.md).

### Shopee vs TikTok Shop vs Lazada

| | Shopee | TikTok Shop (web VN) | Lazada |
|---|---|---|---|
| Discovery | Search box, sort "Bán chạy" | **No search box, no sort.** Walk `/vn/k/<slug>` keyword pages + "Related Searches" (domain profile), rank by total sold | Search, sort "Bán chạy" (`sort=popularity`), JSON via `ajax=true` |
| Data | JSON API the page calls | JSON embedded in the HTML (`__MODERN_ROUTER_DATA__`), read by XHR in the tab that passed the captcha | `window.__moduleData__` cut out of the product HTML, read by XHR in the tab |
| Per-SKU stock | Click each variation | **Exact, in the JSON** | In the JSON (`skuInfos`) |
| 30-day sales / voucher price / shop opening date | Yes | Not published → columns dropped in the layout | Not published → columns dropped |

### Data limits (read before analysing)

| Field | Limit |
|---|---|
| Shop address | Shopee publishes only the shipping province |
| Price | List price after the shop's discount (same for everyone); "Giá sau voucher" depends on the crawling account |
| Stock | Shopee JSON has no per-SKU count; the tool selects each variation and reads "N pieces available" (max 40 clicks / product) |
| Reviews | Only score, total and star distribution; the page loads featured 5-star reviews only, so review text is not exported |
| Material / origin / warranty / size | Attribute table first, then regex on title and description; the "Nguồn trích xuất" column says where it came from |

---

## Development

```powershell
pytest                       # 267 unit tests: parsers (incl. malformed payloads), regex, filter, config, contracts, Excel
ruff check src tests tools   # lint
pytest --cov=ecommerce       # coverage

$env:ECOMMERCE_CHROME_EXECUTABLE="C:\Program Files\Google\Chrome\Application\chrome.exe"
pytest tests/integration     # 7 tests driving real Chrome against fake Shopee / TikTok sites served locally
python tools\verify_excel_output.py output\shopee\giu_nhiet_*.xlsx --sample 10   # checks on an exported file
```

### Repository layout

```
configs/                          YAML: app, platforms/<name>, domains/<name>, reports/<name>
src/ecommerce/
  cli.py                          commands
  settings.py                     typed config + CrawlRequest (runtime input) + paths
  domain/                         Product / Variant / Shop..., candidates, Dataset, DomainProfile
  ingestion/                      browser (attach mode, block detection), raw_store (bronze layer), images
  platforms/
    base.py, __init__.py          PlatformAdapter interface + registry
    shopee/  adapter.py           extract/ (listing, detail, sku_stock, session)  parse/ (raw -> Product, dataset)
    tiktok/  adapter.py           extract/ (fetch, crawl)                          parse/ (raw -> Product, dataset)
    lazada/  adapter.py           extract/ (fetch, crawl, session)                 parse/ (common, listing, product, dataset)
  contracts/                      data contracts, schema-drift guard, check-schema, baselines
  transformation/                 domain filter + spec extractors (capacity, materials, ...)
  consumption/excel/              layout (YAML), column registry, checklist, writer
  resources/configs/              copy of configs/ shipped in the wheel (tests assert both are identical)
tests/                            unit + integration (real Chrome on fake sites)
tools/                            manual verification of an exported Excel file
docs/                             architecture, roadmap, decisions, data notes
data/raw/                         bronze layer (not committed)     output/   Excel files (not committed)
```

### Adding a platform

1. `src/ecommerce/platforms/<name>/` with `adapter.py` (subclass `PlatformAdapter`), `extract/`, `parse/`.
2. A settings class in `settings.py` and `configs/platforms/<name>/config.yaml`.
3. Contract rules in `src/ecommerce/contracts/<name>.py` + a baseline.
4. One entry in `platforms/__init__.py`. Styling in `configs/reports/default.yaml`.

Nothing else changes.

## Usage note

The tool reads public product pages only, sequentially, with long random pauses
(20-45 s between products, 4-8 min every 8, 20-30 min every 24; on
`/verify/traffic` it backs off 60 → 120 → 180 → 240 min). It is intended for
market research on public data.
