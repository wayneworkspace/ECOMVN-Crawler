# Decisions

Architecture Decision Records for the crawler and pipeline. Numbering follows the original log; paths updated to the platform layout.

Before writing any code, we read the source of 12 Shopee / TikTok Shop crawler repos on GitHub together with the issue log of the `Ecommerce_Price_Gap_Tracker` project. Each decision below avoids a failure someone has already run into.

## 1. Capture the JSON of the real page, do not call the API directly

| Approach | Repos that tried it | Why we do not use it |
|---|---|---|
| `requests` calling `api/v2`, `api/v4` directly | lthoangg, hoangkimminh, dee-ex, nhtlongcs, akherlan, paulodarosa, minhdang206 | Since 2023 Shopee signs every request with the `x-sap-sec` / `af-ac-enc-dat` headers. Unsigned requests are blocked or receive empty data |
| Replaying a cURL copied from DevTools | haucongle/shopee-scraper | The signature is bound to the exact query string and expires after 1–2 minutes. Cannot be automated for 200+ pages |
| Reading the DOM by CSS class | walsptr, BrenoFariasdaSilva, Yaaesthetic (TikTok) | Classes such as `jrzBcd`, `price-w1xvrw` are hashed names that change on every deploy |

**Chosen:** open the page in a real Chrome and listen to the responses the page itself requests (`search_items`, `pdp/get_pc`, `get_ratings`). The signature is produced by Shopee's own JS; the tool only reads the result.

## 2. patchright + a dedicated Chrome profile, log in by hand once

- Visiting a product page anonymously redirects to the login page (Price Gap Tracker, Issue 1).
- Exporting cookies and loading them into a fresh browser makes the fingerprint mismatch, which triggers captchas (Issue 2). PhucHuwu/Metabrain does exactly this, so the tool does not follow it.
- Plain Playwright is usually detected through CDP (Issue 3). `playwright-stealth` avoids the captcha but breaks Shopee's JS: prices do not render (Issue 4).
- **patchright** patches at the CDP layer and injects no JS; it is used together with `launch_persistent_context` + `channel="chrome"`. No custom user agent, locale or headers are set, because every spoofed value is one more fingerprint mismatch.
- **Login is not done inside the controlled browser.** A real run showed that the Shopee login form ignores the LOG IN click when Chrome is driven over CDP: the button is enabled but clicking does nothing. The `ecommerce login` command therefore opens a **plain** Chrome with `--user-data-dir` pointing at the tool's own profile. The user logs in as usual, closes the window, and the crawler reuses that session. Same `chrome.exe`, same profile, same machine, so cookies and fingerprint still match; we verified that cookies written by plain Chrome are read back by the patchright context. Before crawling, the tool checks the session cookies (`SPC_U`, `SPC_ST`) and refuses to run as a guest.

## 3. Wait with `page.wait_for_timeout`, not `time.sleep`

Playwright's sync API only processes network events while it is inside a call to the browser. A `time.sleep()` loop makes responses look as if they "arrived late" by exactly the duration of the loop (Issue 5). `ResponseTap.wait_for` waits with `page.wait_for_timeout` and checks the URL every 0.4 seconds, so a redirect to a captcha is noticed immediately instead of after the full 40-second timeout.

The event handler only stores the `Response` object. The body is read later, on the main thread, because reading the body inside the handler is the root cause of deadlocks in the sync API.

## 4. HTTP 200 is not necessarily success

When blocking, Shopee still returns HTTP 200 with valid JSON `{"error": 1, "data": null}`. Treating that as success turns a broken file into "done" and it is never crawled again. `pdp_item()` rejects this payload, the product is recorded in `failures.json`, and no raw file is written.

Responses are filtered by both path and `item_id`, because the recommendation widget on the page calls the same API for other products.

## 5. Sequential, slow, no multithreading

lthoangg runs 32 threads. Doing that with your main account is putting yourself on the block list (haucongle describes the `scene=crawler_item` captcha loop). This tool runs 1 tab, a random 4–9 second delay, and a 60–120 second rest after every 25 products. Crawling about 230 products takes roughly 1.5 hours.

## 6. Raw first, transform later; the raw file is the checkpoint

- Files are written atomically (write to a temp file, then rename), so a shutdown mid-run leaves no half-written JSON.
- Re-running `crawl` skips products that already have a raw file.
- After fixing a parser, only `export` needs to run; not a single extra request goes to Shopee.

## 7. Missing data stays blank, never 0

"Sold 0" is a false statement when the truth is "unknown". Every field without data is `None` and shows as an empty cell. The `Độ phủ dữ liệu` sheet reports how full each column is, in percent.

## 8. Filter by the first noun in the title

Shops name the main product first and the gift after: "Bình giữ nhiệt … tặng túi" is a flask, while "Túi giữ nhiệt đựng bình sữa" is a bag. Short words are wrapped in `\b` so that "áo" does not match inside "báo nhiệt độ" and "tất" does not match inside "tất cả". Every dropped product is listed in the `Bị loại` sheet with its reason, for review.

## 9. Images: shrink before embedding

Learned from te-papa/embed-xlsx-images: download the `_tn` variant from the CDN, shrink to 110px, then embed, with `object_position=1` so the image follows the cell when sorting or filtering. 200 products × 3 images end up at a few MB instead of hundreds of MB. Images come from the public CDN, so they do not go through the logged-in session.

## 10. TikTok Shop: no search box, walk the keyword-page graph

Direct survey of `shop.tiktok.com/vn` on 11/09 (after solving the slide-puzzle captcha once):

- `shop-vn.tiktok.com` redirects to `shop.tiktok.com/vn`. The VN web **has no search box**; every `/search?q=` path is 404. Third-party docs (ReefAPI, ScrapeCreators) also say keyword search on the web exists only in the US.
- There are **SEO keyword pages** `/vn/k/<slug>`: `/vn/k/giu-nhiet` has 55 products, no pagination (`has_more: false`). Each page has a "Related Searches" block pointing to other keyword pages. The tool walks these pages breadth-first, following only slugs containing `giu-nhiet` and excluding slugs for clothing / lunch boxes / bags… (regexes in the domain profile, `configs/domains/<name>.yaml`). A trial walk of 40 pages yielded 990 products, of which 782 were insulated flasks/cups; the sales threshold of the 200th product was about 1,300.
- The category page (`/vn/c/vacuum-flasks/600032`) is capped at 100 products and is not sorted by sales, so it is not used.
- **No "Best selling" sort exists**: the tool merges everything, filters, opens the detail page for the `target × 1.6` products with the highest sales figure on the keyword page, then ranks by **total sold on the product page**. The two numbers agreed for 5/6 products checked; they differ when TikTok merges several listings.
- The data is already in the HTML (`<script id="__MODERN_ROUTER_DATA__">`), including **exact per-SKU stock** (`sku_quantity.available_quantity`) and per-SKU price. No need to click through variations as on Shopee.
- The tool **does not navigate the tab** to each product; instead the tab that already passed the captcha issues an `XMLHttpRequest` to fetch the HTML and returns only the JSON block: same cookies, same TLS fingerprint, same origin as a real user, but without downloading images/videos (~5 MB per page). XHR is used because TikTok's security SDK wraps `window.fetch` on product pages and breaks `response.text()` for HTML.
- TikTok does not have: 30-day sales (and no listing date to derive it), price after voucher, shop address (the shop page is 404 on the web). The first two columns are dropped from the TikTok file rather than left blank; "Địa chỉ shop" is only filled when the mandatory attribute "Địa chỉ tổ chức chịu trách nhiệm hàng hóa" looks like a real address.
- Response rate = `store_sub_score` of type 1, matching the "100% replies in 24h" text TikTok shows in the shop description.
- On a "Security Check" page, the tool opens that page in the tab so the captcha renders, then stops and waits for a person (it does not solve captchas itself).

## 11. Open a plain Chrome and "attach" to it, do not let patchright launch it

Real run on 11/09: after a few dozen products Shopee redirected to `/verify/captcha`, TikTok showed "Security Check" on the very first page. In a Chrome **launched by** patchright (`launch_persistent_context`, showing the "unsupported command-line flag: --disable-blink-features=AutomationControlled" bar), the captcha widget of **both sites was blank**, so even a person could not solve it. The same captcha renders fine in a manually opened browser.

Therefore, by default (`browser.mode: attach` in `configs/platforms/<name>/config.yaml`) the tool itself runs `chrome.exe --user-data-dir=<profile> --remote-debugging-port=<random port>` as an ordinary Chrome window (no automation flags), and patchright only does `connect_over_cdp` to listen to responses and navigate. Profile, cookies and fingerprint remain those of a real Chrome. `mode: launch` keeps the old behaviour; the integration tests run in both modes (`ECOMMERCE_BROWSER_MODE`).

`ecommerce login --platform tiktok` opens the `/vn/k/giu-nhiet` page in a plain Chrome to solve the TikTok captcha once before crawling (TikTok Shop needs no login).

## 12. Pydantic for config and data; parsers split by field

- **Config** (`src/ecommerce/settings.py`): every YAML section is a typed model with value ranges and `extra="forbid"`. A typo such as `shopee.taget` or a value like `delay_min_s: "ba giây"` fails at startup instead of silently falling back to a default and crawling wrongly for hours. Models are `frozen`: to change one (e.g. `--pass 1`) you create a re-validated copy via `with_updates()`.
- **Data** (`src/ecommerce/domain/`): parsers return a `Product` instead of a dict with ~70 keys, so a wrong field name is an error at the assignment site rather than an empty Excel column. `to_row()` keeps the old key names for the Excel layer.
- **Candidate** allows unknown keys (`extra="allow"`) because raw files from older crawls must remain readable.
- Shopee's `parse_product` (~150 lines) was split into per-field functions: `price`, `sales`, `stock`, `rating`, `shop`, `variants`, `content` (`src/ecommerce/platforms/shopee/parse/`). `product.py` only assembles. Each function receives a `ShopeeRaw` (the JSON blocks already separated), so each part can be tested on its own.
- The split was locked down by a **golden test**: run the old and new code on 40 real raw products per platform and compare key by key: no key differed.

## 13. Data contracts: know early when a site changes its JSON

The tool reads the site's JSON, not its UI, so colour / layout changes have no effect. The dangerous case is a **renamed field**: the tool crawls quietly for hours and the empty column only shows up at Excel export.

- `src/ecommerce/contracts/shopee.py`, `tiktok.py` record the ~20–25 fields the tool actually reads, each with **every location** the reader can take it from (in fallback order). The whole JSON is not checked: the site adds / removes hundreds of unused fields, and checking all of them would raise an alarm every day.
- **During the crawl:** every saved file is checked immediately; 3 consecutive products missing a core field pause the run and ask a person. You know after 3 products instead of after 200.
- **After the crawl:** `ecommerce check-schema` compares per-field coverage against the baseline of a known-good run, and compares the whole structure to suggest a new name when a field disappears.
- To keep the rules in step with the code, `tests/test_contracts.py` checks each rule in both directions: removing every source must empty the Excel column; keeping one source must keep the column filled. While being written, the test caught two real mismatches.
- Rules are written as a declarative table rather than Pydantic models for the raw JSON: a field can have 5–10 fallback locations, and a table is far easier to read and edit.
- Kept inside the project (not a separate package) because the rules must travel with the readers and must run inside the crawl loop; but the package only reads raw JSON and does not depend on `platforms/*/extract/`, so splitting it out later would be quick.

## 14. Tried calling the Shopee API directly (failed) and re-measured crawl time

A full Shopee crawl took ~19 hours, TikTok only ~1.3 hours. Hypothesis: copy the TikTok approach — call the API directly from the tab instead of opening the whole product page. Tried with a standalone script, without touching `src/`. (The script was deleted once the conclusion was reached; the table below is the full set of measurements.)

**Measurements (13/09, real account, ~15 requests):**

| Way of calling `api/v4/pdp/get_pc` | Result |
|---|---|
| Bare XHR inside the shopee.vn tab | HTTP 403, `error 90309999` |
| The page's own `window.fetch` | HTTP 403, `error 90309999` |
| fetch/XHR + headers captured from a real page request | HTTP 200 but still `error 90309999` |
| Opening the product page as today | 4.8–8.3 seconds, complete data |

The page attaches `af-ac-enc-dat`, `d-nonptcha-sync`, `x-sap-ri`, `x-csrftoken` — single-use signatures generated by JS per request. Replaying an old signature gets past the gate (403 → 200), but the risk-control layer still refuses. Stock goes through **POST** `api/v4/pdp/cart_panel/select_variation_pc`, which needs the same kind of signature.

**Decision: stop this direction.** Going further means re-implementing the signature algorithm, i.e. breaking the anti-bot mechanism. Shopee requires opening the real page and clicking for real.

**Re-measuring where the 19 hours go** (207 products, 3,888 SKUs, click counts taken from the raw data itself — 0.94 clicks per SKU):

| Item | Before | After |
|---|---|---|
| Clicking variations (pass 2) | 7.6 h | 4.1 h |
| Anti-block rests | 5.0 h | 3.3 h |
| Long breaks + pauses between products | 4.4 h | 4.4 h |
| **Total** | **~17–19 h** | **~11–12 h** |

Changed: `click_pause` 5–10 → 3–5 seconds (`timeouts.click_pause_min_ms` / `click_pause_max_ms` in `configs/app.yaml`), `cooldown_every` 16 → 24 products (`pacing:` in `configs/platforms/shopee/config.yaml`). Still slower than the 0.6–1.5 second pace that got blocked repeatedly (decision 11). If captchas appear, restore the old values on those lines.

**One optimisation rejected, recorded so it is not redone:** we planned to skip clicking SKUs the JSON already reports as out of stock (`has_stock: false`, 23% of SKUs). Measured on real data: 181/704 out-of-stock SKUs **already cost no click at all** — Shopee disables the button, and the code writes 0 and moves on when it sees a disabled button. Savings are zero, so that code was removed; one test in `tests/integration/test_sku_stock.py` is kept to assert this property.

## 15. Every crawl is a snapshot: `crawl` starts a new run, `resume` continues one

Prices, promotions, stock and the "Bán chạy" ranking on both platforms change daily; stock changes hourly. An Excel file is therefore a snapshot at a point in time, not a live table.

Even within one run there is drift: measured on real data, the Shopee products of the 10/09 run were fetched between 09:14 one day and 07:56 the next — **22.7 hours apart**; TikTok only 1.3 hours. Evidence of drift: one product had 12,890 reviews one day and 12,892 the next; another changed price 473,388 → 478,170 after a day.

Hence the command-line defaults changed:

| Command | Before | Now |
|---|---|---|
| `ecommerce crawl` | continue the latest run | **always start a new run** |
| `ecommerce resume` | (did not exist) | continue the latest interrupted run |
| `ecommerce crawl --run <name>` | as before | as before: target exactly one run |

Starting a new run while the previous one is unfinished makes the tool warn with progress ("only 1/5 products so far") and suggest `resume`, rather than silently mixing two days into one file.

Trade-off: each crawl takes extra disk — measured at 193 KB per product on average, i.e. about **39 MB for a 207-product run**. Raw data lives in `data/raw/<platform>/<run id>/`; old directories can be deleted at any time, exported Excel files no longer depend on them.

Consequence for merged passes: a merged run (`crawl` without `--pass`) takes ~12 hours, two separate passes take ~20 hours because the whole list is walked twice. Merged is both faster and a tighter snapshot in time.

## 16. Cut 279 lines of code that feed no Excel column

The question: if we remove code to slim down, does the Excel file change? The way to answer it: **export — cut — export again — compare cell by cell**, no reasoning by inspection.

Three parts were cut, chosen by a single criterion: *there is no path from it to a cell in Excel.*

| # | What was cut | Why | Lines |
|---|---|---|---|
| A | `platforms/shopee/extract/probe_stock.py` + the `probe` command | Single-product stock probing tool used during development. Moved to `to_delete/shopee_probe_stock_tool.py`, still runnable by hand | 223 |
| B | Per-review content: `parse_reviews`, `reviews` in `Product`, `reviews_per_item`, the click-through to the reviews page | `consumption/excel/` never printed reviews to Excel (decision 6: the product page only loads featured reviews, 148/148 were 5 stars). Replaced by `rating_summary()` which takes only the star summary block | 47 |
| C | `small_image_url()` + `_SIZE_RX` in `platforms/tiktok/parse/common.py` | Dead function: searched the whole source, nothing calls it | 9 |

### Evidence: cell-by-cell comparison of the file before and after

Re-exported from the exact same old raw data, compared **every cell, every sheet**:

| File | Cells compared | Differences |
|---|---|---|
| Shopee (39 products, 6 sheets) | 19,266 | **1** — the "export time" cell in the Thông tin sheet |
| TikTok (40 products, 6 sheets) | 20,558 | **0** |

No column was completely empty in the sample (except the image column, exported with `--no-images`), so the comparison touched every column. Embedded images were compared by md5 inside the .xlsx: identical.

### A trap we nearly fell into — recorded so it is not repeated

The first cut also deleted `_load_more_reviews`, which contained **the page-scroll loop**. The re-exported Excel was still identical — because it was exported from old raw data. But a **new crawl** would break: Shopee lazy-loads the reviews block and the shop block; without scrolling to them, `get_ratings` and `get_shop_*` never fire, losing the shop columns (followers, shop rating, join date) and the counts of reviews with photos / with text. In pass 2 (SKU stock) there is not even the `human_scroll` fallback.

So 10 lines of `_load_side_blocks()` are kept: **scroll until `get_ratings` answers, then stop**, with no click-through to the reviews page. Safe, and still saves the clicks.

> Lesson: "the Excel files compare equal" only proves the **reading** side (`platforms/*/parse/`) is unchanged. The **fetching** side (`platforms/*/extract/`) must be checked with an integration test against a fake Shopee page — `tests/integration/test_browser_flow.py` asserts that `get_ratings` still runs after the cut.

After the cut: 257 unit tests + 7 integration tests green; `src/` is 5,937 lines.

## 17. Tooling: add `ruff` + `pytest-cov`, no data-quality libraries

Principle: **a library comes in only when it deletes our own code**, not because it is popular.

| Tool | Decision | Reason |
|---|---|---|
| **ruff** | Added (dev) | Replaces `pyflakes` + `isort` + `pyupgrade` with one command. Found 142 real lint errors in 66 files (65 old `Optional[X]`, 17 files with mis-ordered imports, 2 `raise` statements swallowing the root cause, 2 variables named `l`) |
| **pytest-cov** | Added (dev) | Without it we cannot tell what is untested. Measured: **82%** — `transformation/`, `platforms/*/parse/` and `consumption/excel/` near 100%; the low part is `platforms/*/extract/` because it needs a real browser |
| Great Expectations | No | `contracts/` already does the part that matters: checking the **raw** JSON at crawl time. GE checks DataFrames, i.e. after parsing — later than where things usually break |
| pandera | No | Its role is already played by `domain/product.py` (Pydantic) |
| tenacity | No | The retry loop here must know *why* it failed (captcha → wait for a person; traffic block → long rest; 404 → skip). That is bespoke logic, not generic retry |
| typer | No | Measured: switching `argparse` to `typer` cuts ~40 lines but adds a runtime dependency. Not worth it |
| Scrapy / Crawlee | No | See decision 14: Shopee requires opening real pages in a Chrome with a logged-in profile. These frameworks shine at bulk request sending — exactly what cannot be used here |

The ruff config sets `line-length = 120` and disables `E501`: Vietnamese comments are longer than English ones, and forcing 79 columns only makes the code uglier. In exchange, `B` (bugbear) and `SIM` are enabled — two rule groups that catch real bugs.

Cleanup alongside: deleted the 3 API-trial scripts (470 lines; the conclusion lives in decision 14), moved `verify_excel_output.py` to `tools/` because it is still used, deleted `build/`, `*.egg-info/`, `.pytest_cache/`.

## 18. Re-arranged the main sheet columns: 7 blocks, frozen through the product name

An outside reader asked to review the repo pointed out: open the file, scroll right to see prices, and **the product name is gone**, because "Tên sản phẩm" was column 7 while only the first 3 columns were frozen (Hạng / Mã SP / Số SKU).

All 38 columns re-measured on 39 Shopee + 40 TikTok products:

| Problem | Measurement |
|---|---|
| The "Phân loại" cell crammed with **every SKU combination** | average **707 characters**, longest **3,654**; 22/39 products had a cell > 255 characters |
| The "Màu sắc" cell | average **13.5 colours**, longest 1,330 characters |
| The "Mô tả" cell | many shops type ~15 blank lines at the top; opening the cell shows only whitespace |
| Long text columns between numeric ones | "Khuyến mãi" (89 characters) sat between the price block and the sold block |

### Changed

| Column | Before | After |
|---|---|---|
| Order | Hạng \| Mã SP \| Số SKU \| Ảnh 1-3 \| Tên… | **7 blocks**: identity → price → sales & stock → rating → attributes → shop → raw data |
| Frozen panes | 3 columns: Hạng / Mã SP / Số SKU | 3 columns: **Hạng / Ảnh 1 / Tên sản phẩm** |
| "Phân loại" | Every SKU combination | **Group names** (`Màu Sắc / Dịch Vụ`) — uses the existing `tier_names` |
| "Màu sắc" | The whole list | First 5 colours + `(+N màu)` |
| "Mô tả" | Verbatim | Leading/trailing blank lines trimmed (only when writing Excel; raw JSON untouched) |
| Ảnh 2, Ảnh 3 | Columns 5-6 | End of the table; only Ảnh 1 in the identity block |
| Added | — | **"Ngày mở shop"** (Shopee 40/40, TikTok lacks it → in `drop_columns`), **"Link shop"** (both platforms 40/40) |

The Detail sheet **did not change a single column** — per-SKU detail is still there; the main sheet simply stops repeating it.

### `lead = 3` is gone

The three image cells used to be inserted by **hand-counted position** (`consumption/excel/excel.py`: `columns[:3]`, then insert images, then `columns[3:]`), so reordering columns made the images jump to another column. Now image cells are declared directly in `COLUMNS` with `kind="image"`, and the writer allocates an image column when it meets one. Reorder as many times as you like and nothing shifts; with `embedded_images=2` only the first two image cells are kept.

### New test blocking silent failures

`excel.py` reads values with `r.get(key)` → a typo in a key name in `columns.py` yields **an empty column with no warning**. Tried for real: renaming `shop_location` to `shop_locaton` → 39/39 cells empty while 257 tests stayed green. Now `test_moi_cot_excel_deu_tro_vao_khoa_co_that` checks that every `Col.key` exists in `to_row()` (and every Detail-sheet key exists in `Variant`).

### Verification

Re-exported from the same 10/09 raw run, compared **by column header** (not by position):

| Platform | Columns lost | Columns added | Columns with changed values |
|---|---|---|---|
| Shopee | **0** | Ngày mở shop, Link shop | Phân loại (39 cells), Màu sắc (30), Mô tả (28) — exactly the 3 intended places |
| TikTok | **0** | Link shop | Phân loại (40), Màu sắc (30), Mô tả (3) |
| Detail (both) | **0** | **0** | **0** |

## 19. "Highest price" must really be the highest: merge product-level price with per-SKU prices

Opening the main sheet next to the Detail sheet showed a contradiction:

```
main sheet  : 420.000đ – 420.000đ
Detail sheet: 300.000 · 320.000 · 330.000 · 420.000 · 600.000 · 640.000 · 660.000 · 880.000
```

The cause is in the JSON, not in the reader:

```
pdp.data.item.price_min = pdp.data.item.price_max = 420.000đ
pdp.data.item.models[].price                     = 300.000 … 880.000đ
```

Shopee sets `price_min = price_max` to the price of **one** variation currently on promotion. 420,000 is neither the min nor the max — it sits in the middle.

The old `price.py` preferred the product-level field and used SKU prices only when that field was empty (`low or min(prices)`). It is never empty, so SKU prices were **never** used.

### Measured before fixing (40 Shopee products with multiple SKUs)

| Check | Result |
|---|---|
| `item.price_max` **differs** from the highest SKU price | **13/40** |
| Of which Shopee collapsed to a single price | 6/40 |
| Shopee reports **lower** than every SKU price | **0/40** |
| Shopee reports **higher** than every SKU price | **0/40** |

The last two rows are the basis for a safe fix: the product-level field is **never wider** than the SKU range, so merging both sources and taking min/max can only **widen**, never narrow.

### Fixed

`_khoang()` merges the product-level field with all SKU prices and takes the smallest / largest, applied to both the selling price and the original price (`src/ecommerce/platforms/shopee/parse/price.py`).

### Verification: export before / fix / export after, cell by cell

| Sheet | Column changed | Cells |
|---|---|---|
| Shopee | Giá bán cao nhất | **13** |
| | Giá bán thấp nhất | 4 |
| | Giá gốc | 4 |
| | % giảm | 3 |
| | Khuyến mãi (string containing the % discount) | 3 |
| **Detail** | — | **0** |
| **Checklist đề bài** | — | **0** |
| **TikTok (all 6 sheets)** | — | **0** |

Invariant "main sheet covers the Detail sheet":

| | Before | After |
|---|---|---|
| Highest price ≥ most expensive SKU | 26/39 | **39/39** |
| Lowest price ≤ cheapest SKU | 35/39 | **39/39** |

`test_khoang_gia_sheet_chinh_bao_trum_moi_sku` guards this property: it builds a product where the platform collapses the price range to one level while the SKUs spread wide, and asserts the main sheet still covers them.

### What could NOT be fixed: the "Bán 30 ngày" column

The same inspection showed the "Bán 30 ngày (TB tháng)" column is unreliable (details in `docs/cau_hoi_mentor.md`, question 5): across 40 products, 17 had a "30-day" figure above 50% of lifetime sales, the highest at 93% on a listing **23.5 months old**; compared with the true average (total ÷ age), Shopee reports a median 4× higher, in one case 39×, but there are also cases 4× lower.

Unlike price, **there is no other source in the JSON to cross-check** — the old `item.sold` / `historical_sold` fields are now entirely empty. So only the **column name and note** can be fixed, not the number. Not done yet; waiting for a new run's data to compare.

## 20. TikTok "Link shop": the web has no store page — keep the platform's link and say so

A user reported that clicking the shop link in the TikTok file gives 404. Traced to the end (13/09, in a separate browser, without touching the running crawl):

**Step 1 — the platform-level link.** 40/40 products have it, consistent format, containing the correct `seller_id`:

```
product_info.shop_info.shop_link = "https://shop.tiktok.com/vn/store/ntt-store-hn/7494696250630900350"
```

**Step 2 — tried 4 URL shapes:**

| URL | Result |
|---|---|
| `shop.tiktok.com/vn/store/<slug>/<id>` — exactly what the platform returns | **404 Not Found** |
| `shop.tiktok.com/view/shop?seller_id=<id>` | 502 Bad Gateway |
| `www.tiktok.com/shop/store/<id>` | Bounced to the home page |
| `www.tiktok.com/shop/vn/store/<slug>/<id>` | Not 404, but a **blank page** even when logged in |

The fourth shape was once mistaken for "fixed" because it no longer returned 404. **Not-404 is not enough** — a user opening it with a logged-in account still sees a blank page with only the Sell / More menu.

**Step 3 — ask the product page directly.** Opened the PDP and inspected the DOM around "Sold by":

```
SPAN  ->  DIV  ->  DIV  ->  DIV        (no <a> tag anywhere)
```

The whole page has 42 links, **none** pointing to `store` / `seller`. So on the desktop web, **the shop name is not a link** — TikTok Shop has no store page on the web, only in the app.

**Final decision:** **drop the "Link shop" column from the TikTok file** (`shop_url` added to `drop_columns` in `configs/reports/default.yaml`). The value stays intact in the raw JSON — it just is not exported to Excel, so readers do not click a broken link.

We tried the option "keep the column, rename the header to *Link shop (mở bằng app)*" together with a `rename_columns` mechanism, but abandoned it: a column that does nothing when clicked on a computer is junk in the delivered file no matter how it is annotated. The `rename_columns` mechanism was removed too, since nothing uses it any more.

The Shopee shop link (`https://shopee.vn/shop/<shopid>`) was tested and opens normally — header "Link shop" kept.

> Lesson, worth more than the fix itself: **"not 404" is not "works".** The first time I concluded it was fixed just because the URL did not return 404, while the page was still blank. To verify something visible, look at what is displayed, not at the status code.

## 21. Plugging four holes in the TikTok data contract

Review: which columns in the Excel file **have no rule watching them**? Measured by matching `COLUMNS` against the `feeds` of every rule:

| Group | Columns | Needs a rule |
|---|---|---|
| Read straight from JSON | `promotions`, `brand`, `shop_location`, `stock_state` (TikTok); `promotions`, `shop_joined` (Shopee) | **Yes** — if the platform renames the field the column goes silently empty |
| Computed from other columns | `discount_pct`, `variant_count` | No — the sources already have rules |
| Regex over text | `capacity`, `features`, `origin`, `size`, `warranty`, `product_type` | No — they scan title + description + attribute table, all three already have rules |
| `rating_2/3/4` | | No — same `rating_count` array as `rating_5`/`rating_1` |

The worst was **"Khuyến mãi"**: the reader takes it from ~12 raw paths with no rule watching any of them. If TikTok renames `placement_labels`, the column is empty and `check-schema` still reports ✅.

### Added 4 rules for TikTok

| Rule | Source | `feeds` |
|---|---|---|
| In-stock / out-of-stock state | `skus[].sku_stock_status` | *(none)* |
| Promotions | `promotion_tag.placement_labels`, `promotion_logistic_list[].freeShipping`, `...logisticText.discountViews[].discountDescText` | `promotions` |
| Brand | `candidate.brand` (+ `also`: the "Thương hiệu" row in the attribute table) | `brand` |
| Shop-declared attribute table | `product_model.product_properties` | *(none)* |

**Why two rules declare no `feeds`** — and this is the part worth recording:

- *Stock state*: if `sku_stock_status` disappears, the text "Còn hàng (x/y SKU)" **can still be produced** from the stock counts, just wrongly. Declaring `feeds` would make the test "remove every source → column must be empty" fail, and fail correctly: the column really is not empty.
- *Attribute table*: the reader **filters out meaningless values** (many shops write the address as "TQ"), so the "Địa chỉ shop" column is empty even when the field is intact.

Those two rules only watch the **presence** of the field, not the path to the column. That is a real limit of the current rule language, stated explicitly in `note` rather than declaring a `feeds` just to make the table look complete.

### Verification

The two bidirectional sync tests run automatically for the new rules: **264 tests green**. Baseline regenerated and `ecommerce check-schema --platform tiktok` run on 40 real products:

```
✅ Tình trạng còn / hết hàng      quan trọng có ở 100%
✅ Khuyến mãi                     phụ        có ở 100%
✅ Thương hiệu                    phụ        có ở  52%
✅ Bảng thuộc tính shop khai      quan trọng có ở  95%
```

No rule raised a false alarm.

**Still owed:** the two Shopee rules (`promotions`, `shop_joined`) — not done yet because `contracts/` is the package `SchemaGuard` uses **during the crawl**, and a Shopee run is in progress. To be done once that run finishes.
